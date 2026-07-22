"""PHASE-switched session store: local in dev, Azure Blob-backed in prod.

The engine and the whole generation half stay filesystem-based — sessions
always MATERIALIZE under ``projects/<name>/<session_id>/`` on local disk.
What this module adds is durability for ``PHASE=prod`` (App Service container
disk is EPHEMERAL — without this, every restart/redeploy wiped projects/):

    write path:  local save → ``sync_session_up`` mirrors the session to blob
    read path:   picker/API lookup misses locally → ``pull_session`` restores
                 it from blob into projects/ and everything proceeds as local

Blob layout:  <AZURE_STORAGE_PREFIX/><project>/<session_id>/<relpath>

Environment (all read lazily — NEVER at import time):
    PHASE                            dev (default) | prod
    AZURE_STORAGE_CONNECTION_STRING  storage account → Access keys
    AZURE_STORAGE_CONTAINER          e.g. fews-projects
    AZURE_STORAGE_PREFIX             optional subpath, may be empty

Failure policy: sync problems in prod are logged LOUDLY and never crash a
turn — the local copy stays authoritative for the running session. The
azure-storage-blob SDK is imported only when enabled, so dev/test
environments need neither the package configured nor credentials.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path

_logger = logging.getLogger(__name__)

# The small per-turn files worth mirroring on EVERY save; everything else
# (inputs/, generated/) is mirrored on the full syncs after uploads/builds.
CORE_FILES = (
    ".chat_state.json", ".chat_history.json", "_conversation.md",
    "project.yaml",
)

_container_cache = None


def phase() -> str:
    return (os.environ.get("PHASE") or "dev").strip().lower()


def enabled() -> bool:
    """Prod phase AND storage configured. Missing config in prod logs once."""
    if phase() != "prod":
        return False
    if not (os.environ.get("AZURE_STORAGE_CONNECTION_STRING")
            and os.environ.get("AZURE_STORAGE_CONTAINER")):
        _logger.warning(
            "PHASE=prod but AZURE_STORAGE_CONNECTION_STRING / "
            "AZURE_STORAGE_CONTAINER are not set — sessions stay LOCAL ONLY "
            "and will not survive a container restart."
        )
        return False
    return True


def _container():
    """The (cached) ContainerClient. Lazy SDK import; creates the container
    on first use so a fresh storage account works without manual steps."""
    global _container_cache
    if _container_cache is not None:
        return _container_cache
    from azure.storage.blob import BlobServiceClient  # lazy — prod only

    svc = BlobServiceClient.from_connection_string(
        os.environ["AZURE_STORAGE_CONNECTION_STRING"]
    )
    container = svc.get_container_client(os.environ["AZURE_STORAGE_CONTAINER"])
    try:
        container.create_container()
    except Exception:  # noqa: BLE001 — already exists / no create permission
        pass
    _container_cache = container
    return _container_cache


def _prefix() -> str:
    p = (os.environ.get("AZURE_STORAGE_PREFIX") or "").strip().strip("/")
    return f"{p}/" if p else ""


def _session_prefix(project: str, session_id: str) -> str:
    return f"{_prefix()}{project}/{session_id}/"


# ---------------------------------------------------------------------------
# write path
# ---------------------------------------------------------------------------

def sync_session_up(session_dir: Path, full: bool = False) -> int:
    """Mirror a local session folder to blob. Returns files uploaded (0 when
    disabled or on failure — loudly logged, never raised)."""
    if not enabled():
        return 0
    session_dir = Path(session_dir)
    project = session_dir.parent.name
    prefix = _session_prefix(project, session_dir.name)
    try:
        container = _container()
        if full:
            paths = [p for p in session_dir.rglob("*") if p.is_file()
                     and ".git" not in p.relative_to(session_dir).parts]
        else:
            paths = [session_dir / f for f in CORE_FILES
                     if (session_dir / f).is_file()]
        for p in paths:
            rel = p.relative_to(session_dir).as_posix()
            with p.open("rb") as fh:
                container.upload_blob(prefix + rel, fh, overwrite=True)
        return len(paths)
    except Exception as exc:  # noqa: BLE001
        _logger.error("blob sync UP failed for %s: %s: %s — session remains "
                      "local-only this turn", session_dir.name,
                      type(exc).__name__, exc)
        return 0


# ---------------------------------------------------------------------------
# read path
# ---------------------------------------------------------------------------

def list_remote_projects() -> list[str]:
    """Project names present in the container (empty when disabled/failing)."""
    if not enabled():
        return []
    try:
        pre = _prefix()
        names = set()
        for blob in _container().list_blobs(name_starts_with=pre):
            rest = blob.name[len(pre):]
            if "/" in rest:
                names.add(rest.split("/", 1)[0])
        return sorted(names)
    except Exception as exc:  # noqa: BLE001
        _logger.error("blob list failed: %s: %s", type(exc).__name__, exc)
        return []


def latest_remote_session_id(project: str) -> str | None:
    """Newest session id for a project (ids embed a sortable datetime)."""
    if not enabled():
        return None
    try:
        pre = f"{_prefix()}{project}/"
        ids = set()
        for blob in _container().list_blobs(name_starts_with=pre):
            rest = blob.name[len(pre):]
            if "/" in rest:
                ids.add(rest.split("/", 1)[0])
        return max(ids) if ids else None
    except Exception as exc:  # noqa: BLE001
        _logger.error("blob list failed for %s: %s: %s", project,
                      type(exc).__name__, exc)
        return None


def pull_session(project: str, session_id: str, projects_root: Path) -> Path | None:
    """Restore one session from blob into projects/. Returns the local dir,
    or None when disabled / nothing remote / failure (loudly logged)."""
    if not enabled():
        return None
    dest = Path(projects_root) / project / session_id
    prefix = _session_prefix(project, session_id)
    try:
        container = _container()
        blobs = list(container.list_blobs(name_starts_with=prefix))
        if not blobs:
            return None
        for blob in blobs:
            rel = blob.name[len(prefix):]
            if not rel:
                continue
            target = dest / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open("wb") as fh:
                fh.write(container.download_blob(blob.name).readall())
        _logger.info("restored session %s/%s from blob (%d files)",
                     project, session_id, len(blobs))
        return dest
    except Exception as exc:  # noqa: BLE001
        _logger.error("blob pull failed for %s/%s: %s: %s", project,
                      session_id, type(exc).__name__, exc)
        return None
