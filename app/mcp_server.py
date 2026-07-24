"""MCP server — the fourth driver shell over the FEWS chat agent.

Exposes the FEWS config-generation agent to Claude Desktop, VS Code Copilot,
and other MCP-compatible AI applications via the Model Context Protocol.

This is a **direct-call** implementation (Option B from the design doc): the
MCP server imports and calls the same engine functions the HTTP API uses —
``run_llm_turn``, ``build_from_blueprint``, etc. — with no HTTP hop.

**Where projects live.** By default sessions persist under the agent repo's
``projects/`` (same as the CLI / Streamlit / HTTP drivers). When the client
passes ``workspace_dir`` to ``create_project``, the session + generated XML
are written under ``<workspace_dir>/fews-projects/`` instead — so a user
working in another VS Code workspace can open the files next to their own
code. The agent repo (``cwd``) still holds patterns, XSDs, and ``.env``.

Run manually for testing::

    python -m app.mcp_server

Or via the installed script (after ``pip install -e .``)::

    fews-mcp

Register with Claude Desktop by adding to ``claude_desktop_config.json``::

    {
      "mcpServers": {
        "fews-agent": {
          "command": "fews-mcp"
        }
      }
    }

On Windows, you may need the full path to the Python executable::

    {
      "mcpServers": {
        "fews-agent": {
          "command": "C:\\\\path\\\\to\\\\python.exe",
          "args": ["-m", "app.mcp_server"],
          "cwd": "C:\\\\path\\\\to\\\\fews-agent-2"
        }
      }
    }
"""
from __future__ import annotations

import io
import json
import os
import sys
from datetime import datetime
from pathlib import Path
import hashlib
# Ensure the repo root is on sys.path so imports resolve when run as a script.
_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

# Load ``.env`` from the repo root before anything reads os.environ, so the
# MCP server picks up FEWS_AGENT_PROVIDER / AZURE_AI_* the same way the web
# app does. Real process env (e.g. an ``env`` block in .vscode/mcp.json)
# wins — ``override=False`` means we don't clobber values set by the client.
try:
    from dotenv import load_dotenv
    load_dotenv(_REPO_ROOT / ".env", override=False)
except ImportError:  # python-dotenv missing → silently skip
    pass

from mcp.server.fastmcp import FastMCP
from rich.console import Console

# --- reuse the existing agent machinery; do not reinvent it ---------------
from fews_agent.agent.project_chat import (
    build_pattern_catalog,
    initial_state,
    load_blueprint_into_state,
    write_project,
)
from fews_agent.agent.llm_turn import catalog_digest
from fews_agent.agent.modules import list_modules as _list_modules
from fews_agent.agent.patch_ops import apply_patch
from fews_agent.agent.project_intents import (
    _IMPORT_PATTERN_MAP,
    heuristic_intent_from_slots,
)
from fews_agent.agent.turn_engine import resolve_patterns
from fews_agent.validation import validate_xsd
from runners.agent.build_from_blueprint import (
    build_from_blueprint,
    build_phase as _build_phase,
)

try:  # disk-native cross-reference walker (semantic-by-parsing)
    from scripts.check_references import analyze as _analyze_refs
except ImportError:  # pragma: no cover - scripts/ always present in repo
    _analyze_refs = None

# ---------------------------------------------------------------------------
# Paths & constants
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parents[1]
PATTERNS_ROOT = REPO_ROOT / "patterns"
# Default project store when no workspace_dir is passed (agent-repo local).
OUTPUT_ROOT = REPO_ROOT / "projects"
# Under a client workspace, sessions land in <workspace>/fews-projects/.
WORKSPACE_PROJECTS_SUBDIR = "fews-projects"
# Maps session_id → absolute project_dir so later tools find workspace
# sessions without re-passing workspace_dir every turn.
_SESSION_INDEX_PATH = OUTPUT_ROOT / ".mcp_session_index.json"
DEFAULT_MODEL = "qwen2.5:7b-instruct"

# ---------------------------------------------------------------------------
# Session persistence — identical layout to app/api/server.py
# ---------------------------------------------------------------------------


def _state_path(project_dir: Path) -> Path:
    return project_dir / ".chat_state.json"


def _history_path(project_dir: Path) -> Path:
    return project_dir / ".chat_history.json"


def _sanitize_project_name(name: str) -> str:
    """Make a project name filesystem-safe."""
    return "".join(c if (c.isalnum() or c in "-_.") else "-" for c in name)


def _is_safe_session_id(session_id: str) -> bool:
    return bool(session_id) and not any(
        c in session_id for c in ("/", "\\", "..")
    )


def resolve_projects_root(
    workspace_dir: str | None,
    *,
    create: bool = False,
) -> tuple[Path | None, str | None]:
    """Return ``(projects_root, error)``.

    * ``workspace_dir is None`` → agent-repo ``projects/``.
    * otherwise → ``<workspace_dir>/fews-projects/``.
      The workspace directory itself must already exist. Pass
      ``create=True`` (create_project) to mkdir the fews-projects folder.
    """
    if workspace_dir is None or not str(workspace_dir).strip():
        return OUTPUT_ROOT, None
    raw = Path(str(workspace_dir).strip()).expanduser()
    try:
        workspace = raw.resolve(strict=False)
    except OSError as exc:
        return None, f"Invalid workspace_dir {workspace_dir!r}: {exc}"
    if not workspace.is_dir():
        return None, (
            f"workspace_dir does not exist or is not a directory: {workspace}"
        )
    projects_root = workspace / WORKSPACE_PROJECTS_SUBDIR
    if create:
        projects_root.mkdir(parents=True, exist_ok=True)
    # Stay inside the workspace (no symlink escape after resolve of children).
    try:
        projects_root.resolve().relative_to(workspace.resolve())
    except ValueError:
        return None, (
            f"Refusing projects root outside workspace: {projects_root}"
        )
    return projects_root, None


def _new_session_dir(project_name: str, projects_root: Path) -> Path:
    """Mint a fresh datetime-stamped instance dir under ``projects_root``."""
    parent = projects_root / project_name
    parent.mkdir(parents=True, exist_ok=True)
    dt = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    new_dir = parent / f"{project_name}_{dt}"
    if new_dir.exists():
        n = 2
        while (parent / f"{project_name}_{dt}_{n}").exists():
            n += 1
        new_dir = parent / f"{project_name}_{dt}_{n}"
    new_dir.mkdir(parents=True, exist_ok=True)
    return new_dir


def _load_session_index() -> dict[str, dict]:
    if not _SESSION_INDEX_PATH.is_file():
        return {}
    try:
        data = json.loads(_SESSION_INDEX_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _save_session_index(index: dict[str, dict]) -> None:
    _SESSION_INDEX_PATH.parent.mkdir(parents=True, exist_ok=True)
    _SESSION_INDEX_PATH.write_text(
        json.dumps(index, indent=2, default=str), encoding="utf-8",
    )


def _index_session(
    session_id: str,
    project_dir: Path,
    *,
    workspace_dir: str | None = None,
) -> None:
    index = _load_session_index()
    entry: dict = {"project_dir": str(project_dir.resolve())}
    if workspace_dir:
        entry["workspace_dir"] = str(Path(workspace_dir).expanduser().resolve())
    index[session_id] = entry
    _save_session_index(index)


def _find_session_under(projects_root: Path, session_id: str) -> Path | None:
    if not projects_root.is_dir():
        return None
    for cand in projects_root.glob(f"*/{session_id}"):
        if cand.is_dir() and _state_path(cand).is_file():
            return cand
    return None


def _resolve_session_dir(
    session_id: str,
    workspace_dir: str | None = None,
) -> Path | None:
    """Find the instance dir for a session id, or None if not found.

    Lookup order:
      1. ``<workspace_dir>/fews-projects/`` when ``workspace_dir`` is given
      2. Session index (workspace sessions created earlier in this agent home)
      3. Default agent-repo ``projects/``
    """
    if not _is_safe_session_id(session_id):
        return None

    if workspace_dir is not None and str(workspace_dir).strip():
        root, err = resolve_projects_root(workspace_dir)
        if err is None and root is not None:
            found = _find_session_under(root, session_id)
            if found is not None:
                return found

    index = _load_session_index()
    entry = index.get(session_id)
    if isinstance(entry, dict):
        raw = entry.get("project_dir")
        if raw:
            cand = Path(str(raw))
            if cand.is_dir() and _state_path(cand).is_file():
                return cand

    return _find_session_under(OUTPUT_ROOT, session_id)


def _list_sessions_under(projects_root: Path) -> list[dict]:
    """Scan one projects root for sessions (newest first per project folder)."""
    projects: list[dict] = []
    if not projects_root.is_dir():
        return projects
    for project_folder in sorted(projects_root.iterdir()):
        if not project_folder.is_dir() or project_folder.name.startswith("."):
            continue
        for session_dir in sorted(project_folder.iterdir(), reverse=True):
            state_file = _state_path(session_dir)
            if not state_file.is_file():
                continue
            try:
                mtime = datetime.fromtimestamp(state_file.stat().st_mtime)
                projects.append({
                    "project_name": project_folder.name,
                    "session_id": session_dir.name,
                    "project_dir": str(session_dir.resolve()),
                    "last_modified": mtime.isoformat(),
                })
            except OSError:
                continue
    return projects


def _load(project_dir: Path) -> tuple[dict, list]:
    state = json.loads(_state_path(project_dir).read_text(encoding="utf-8"))
    hp = _history_path(project_dir)
    history = (
        json.loads(hp.read_text(encoding="utf-8")) if hp.is_file() else []
    )
    return state, history


def _save(project_dir: Path, state: dict, history: list) -> None:
    project_dir.mkdir(parents=True, exist_ok=True)
    _state_path(project_dir).write_text(
        json.dumps(state, indent=2, default=str), encoding="utf-8"
    )
    _history_path(project_dir).write_text(
        json.dumps(history, indent=2, default=str), encoding="utf-8"
    )


def _catalog():
    return build_pattern_catalog(PATTERNS_ROOT)


def _generated_dir(project_dir: Path) -> Path:
    return project_dir / "generated"


# ---------------------------------------------------------------------------
# Blueprint-first helpers (reverse-sync, typed edits, validate, drift)
# ---------------------------------------------------------------------------


def _maybe_sync_blueprint(project_dir: Path, state: dict) -> list[str]:
    """If project.yaml was hand-edited more recently than the saved state,
    reverse-sync it into ``state`` so the typed tools + status stay coherent.

    Returns notes (empty when no sync happened). Does NOT persist — the caller
    saves after using the refreshed state.
    """
    project_path = project_dir / "project.yaml"
    if not project_path.is_file():
        return []
    state_file = _state_path(project_dir)
    try:
        yaml_mtime = project_path.stat().st_mtime
        state_mtime = state_file.stat().st_mtime if state_file.is_file() else 0.0
    except OSError:
        return []
    # Small epsilon so a build's own write_project (which touches both) doesn't
    # look like a hand edit.
    if yaml_mtime <= state_mtime + 1.0:
        return []
    return load_blueprint_into_state(state, project_dir)


def _ensure_intent_and_resolve(state: dict, catalog) -> None:
    """Re-derive the resolver intent from the current slots, then resolve.

    Intent is only a resolver *selector* here (imports-only vs forecasting),
    so it is re-derived from slots on every edit — mirroring the turn engine's
    ``_sync_module_intent``. Deriving it only when missing would let a stale
    ``build_data_import_only`` drop a basin added later.
    """
    state["intent"] = heuristic_intent_from_slots(state.get("slots") or {})
    resolve_patterns(state, catalog)


def _apply_ops(project_dir: Path, ops: list[dict]) -> dict:
    """Load → (auto-sync) → apply typed ops → resolve → write project.yaml.

    The single shared path for every typed edit tool. Returns a JSON-ready
    dict with applied notes, LOUDLY-dropped invalid ops, the resolved pattern
    list, and the blueprint path.
    """
    try:
        state, history = _load(project_dir)
    except Exception as e:  # noqa: BLE001
        return {"error": f"Failed to load session: {e}"}

    catalog = _catalog()
    synced = _maybe_sync_blueprint(project_dir, state)

    result = apply_patch(state, ops, catalog)
    _ensure_intent_and_resolve(state, catalog)

    try:
        project_path = write_project(state, project_dir)
    except Exception as e:  # noqa: BLE001
        return {"error": f"Failed to write project.yaml: {e}"}
    _save(project_dir, state, history)

    return {
        "ok": not result.dropped,
        "applied": list(result.notes),
        "dropped": list(result.dropped),
        "synced_from_blueprint": synced or [],
        "imports": (state.get("slots") or {}).get("imports") or [],
        "basins": [
            b.get("basin_name")
            for b in ((state.get("slots") or {}).get("basins") or [])
        ],
        "patterns": [p.get("pattern") for p in (state.get("patterns") or [])],
        "project_yaml": str(Path(project_path).resolve()),
        "project_dir": str(project_dir.resolve()),
    }


def _manifest_path(project_dir: Path) -> Path:
    return project_dir / ".generated_manifest.json"


def _hash_generated_tree(generated_dir: Path) -> dict[str, str]:
    """Map relpath → sha256 for every file under the generated tree."""
    out: dict[str, str] = {}
    if not generated_dir.is_dir():
        return out
    for p in sorted(generated_dir.rglob("*")):
        if not p.is_file() or p.name == "_README_DERIVED.txt":
            continue
        rel = str(p.relative_to(generated_dir)).replace("\\", "/")
        out[rel] = hashlib.sha256(p.read_bytes()).hexdigest()
    return out


def _write_generated_manifest(project_dir: Path) -> None:
    """Snapshot the just-built tree so later hand-edits are detectable."""
    generated = _generated_dir(project_dir)
    manifest = _hash_generated_tree(generated)
    _manifest_path(project_dir).write_text(
        json.dumps(manifest, indent=2), encoding="utf-8"
    )
    marker = generated / "_README_DERIVED.txt"
    if generated.is_dir():
        marker.write_text(
            "This folder is DERIVED output, regenerated on every build.\n"
            "Do NOT hand-edit these files — your changes will be overwritten.\n"
            "Edit project.yaml (or inputs/) and rebuild instead.\n",
            encoding="utf-8",
        )


def _detect_drift(project_dir: Path) -> dict:
    """Compare the current generated tree to the last build manifest."""
    manifest_file = _manifest_path(project_dir)
    if not manifest_file.is_file():
        return {"has_manifest": False, "changed": [], "added": [], "removed": []}
    try:
        prev = json.loads(manifest_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        prev = {}
    now = _hash_generated_tree(_generated_dir(project_dir))
    changed = sorted(k for k in now.keys() & prev.keys() if now[k] != prev[k])
    added = sorted(now.keys() - prev.keys())
    removed = sorted(prev.keys() - now.keys())
    return {
        "has_manifest": True,
        "changed": changed,
        "added": added,
        "removed": removed,
        "drifted": bool(changed or added or removed),
    }


def _validate_generated(generated_dir: Path) -> dict:
    """XSD-validate every rendered XML + run the cross-reference check.

    Validates whatever is ON DISK — so it also covers files a user or Copilot
    hand-edited, not just a fresh build.
    """
    if not generated_dir.is_dir():
        return {"error": f"No generated tree at {generated_dir}. Build first."}

    xsd_files: list[dict] = []
    xsd_ok = 0
    xml_paths = sorted(generated_dir.rglob("*.xml"))
    for p in xml_paths:
        rel = str(p.relative_to(generated_dir)).replace("\\", "/")
        try:
            ok, msg = validate_xsd(p.read_bytes())
        except Exception as e:  # noqa: BLE001
            ok, msg = False, f"validation raised: {e}"
        if ok:
            xsd_ok += 1
        else:
            xsd_files.append({"file": rel, "message": msg})

    references: dict = {}
    unresolved_total = 0
    if _analyze_refs is not None:
        try:
            raw = _analyze_refs(generated_dir)
            for kind, buckets in raw.items():
                unresolved = sorted(buckets.get("unresolved", set()))
                references[kind] = {
                    "resolved": len(buckets.get("resolved", set())),
                    "unresolved": unresolved,
                }
                unresolved_total += len(unresolved)
        except Exception as e:  # noqa: BLE001
            references = {"error": f"reference check raised: {e}"}

    return {
        "ok": not xsd_files and unresolved_total == 0,
        "xml_total": len(xml_paths),
        "xsd_ok": xsd_ok,
        "xsd_failures": xsd_files,
        "references": references,
        "unresolved_total": unresolved_total,
    }


# ---------------------------------------------------------------------------
# MCP Server
# ---------------------------------------------------------------------------

mcp = FastMCP(
    "fews-agent",
    instructions=(
        "FEWS config-generation agent. Generate Delft-FEWS XML configuration "
        "through a BLUEPRINT-FIRST workflow: the blueprint (project.yaml) plus "
        "the inputs/ folder are the ONLY things you edit. The generated XML "
        "tree is derived output — never hand-edit it; rebuild instead.\n\n"
        "You (the calling model) are the reasoning engine. Use the typed, "
        "deterministic edit tools — each validates against "
        "the pattern catalog and drops invalid requests loudly.\n\n"
        "Typical workflow:\n"
        "1. create_project — start a project. ALWAYS pass workspace_dir set to "
        "the user's open IDE workspace folder (absolute path) so files land in "
        "<workspace>/fews-projects/. Omit only inside the agent repo.\n"
        "2. list_capabilities / list_imports — discover what can be added and "
        "each capability's required variables.\n"
        "3. add_import / add_basin / add_capability / set_variables / "
        "remove_item — edit the blueprint deterministically.\n"
        "4. get_blueprint — read the current project.yaml + a digest. If the "
        "user hand-edits project.yaml, call reload_blueprint (or it auto-syncs "
        "on the next tool).\n"
        "5. build — regenerate the whole config; validate gates every file.\n"
        "6. validate — XSD + cross-reference check over the generated tree "
        "(catches issues in hand-edited files too).\n"
        "7. check_drift — detect whether the generated tree was hand-edited "
        "since the last build."
    ),
)


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


@mcp.tool()
def create_project(
    project_name: str | None = None,
    workspace_dir: str | None = None,
) -> str:
    """Create a new FEWS configuration project.

    Args:
        project_name: Name for the project. If not provided, a timestamped
            name is generated.
        workspace_dir: Absolute path to the user's open IDE workspace.
            When set, the session (and later generated XML) are written under
            ``<workspace_dir>/fews-projects/<name>/<name>_<timestamp>/`` so
            the user can browse them in their own workspace. When omitted,
            files go under the agent repo's ``projects/`` folder. Prefer
            always passing this when the user is not working inside the
            agent repository.

    Returns:
        JSON with session_id (use this for subsequent calls), absolute
        project_dir, workspace_dir, and where generated XML will appear.
    """
    projects_root, err = resolve_projects_root(workspace_dir, create=True)
    if err or projects_root is None:
        return json.dumps({"error": err or "Could not resolve projects root."})

    name = (project_name or "").strip() or (
        "mcp-project-" + datetime.now().strftime("%Y%m%d-%H%M%S")
    )
    safe = _sanitize_project_name(name)
    project_dir = _new_session_dir(safe, projects_root)
    (project_dir / "inputs").mkdir(exist_ok=True)

    workspace_abs = (
        str(Path(workspace_dir).expanduser().resolve())
        if workspace_dir and str(workspace_dir).strip()
        else None
    )

    state = initial_state(safe)
    state.setdefault("intent", None)
    state.setdefault("slots", {})
    state["model"] = os.environ.get("FEWS_AGENT_MODEL") or DEFAULT_MODEL
    if workspace_abs:
        state["workspace_dir"] = workspace_abs
    state["project_dir"] = str(project_dir.resolve())
    _save(project_dir, state, [])
    _index_session(
        project_dir.name, project_dir, workspace_dir=workspace_abs,
    )

    generated = _generated_dir(project_dir)
    return json.dumps({
        "session_id": project_dir.name,
        "project_name": safe,
        "project_dir": str(project_dir.resolve()),
        "workspace_dir": workspace_abs,
        "projects_root": str(projects_root.resolve()),
        "generated_dir": str(generated.resolve()),
        "message": (
            f"Created project '{safe}'. Use session_id in subsequent calls. "
            + (
                f"Session and generated XML live under {projects_root} "
                f"(open generated/ after build in the user's workspace)."
                if workspace_abs
                else f"Session lives under {projects_root} (agent-repo default)."
            )
        ),
    })


@mcp.tool()
def get_status(
    session_id: str,
    workspace_dir: str | None = None,
) -> str:
    """Get the current status of a project.

    Returns the configured imports, basins, patterns, warnings, and build progress.

    Args:
        session_id: The session_id from create_project.
        workspace_dir: Optional. Same workspace path passed to create_project.

    Returns:
        JSON with current project state including slots, patterns, build
        status, and absolute project_dir / generated_dir paths.
    """
    project_dir = _resolve_session_dir(session_id, workspace_dir)
    if project_dir is None:
        return json.dumps({"error": f"Session '{session_id}' not found."})

    try:
        state, _ = _load(project_dir)
    except Exception as e:
        return json.dumps({"error": f"Failed to load session: {e}"})

    slots = state.get("slots") or {}
    generated = _generated_dir(project_dir)
    return json.dumps({
        "project_name": state.get("name"),
        "imports": slots.get("imports") or [],
        "basins": slots.get("basins") or [],
        "patterns": [p.get("pattern") for p in (state.get("patterns") or [])],
        "warnings": state.get("warnings") or [],
        "built_phases": state.get("built_phases") or [],
        "full_build_ok": state.get("full_build_ok", False),
        "current_module": state.get("current_module"),
        "workspace_dir": state.get("workspace_dir"),
        "project_dir": str(project_dir.resolve()),
        "generated_dir": str(generated.resolve()),
        "generated_exists": generated.is_dir(),
    })


@mcp.tool()
def list_projects(workspace_dir: str | None = None) -> str:
    """List existing FEWS projects.

    Args:
        workspace_dir: Optional. When set, list sessions under
            ``<workspace_dir>/fews-projects/``. When omitted, list the
            agent-repo ``projects/`` store (plus any workspace sessions
            still recorded in the session index).

    Returns:
        JSON with list of projects, each with name, session_id,
        absolute project_dir, and last modified time.
    """
    if workspace_dir is not None and str(workspace_dir).strip():
        root, err = resolve_projects_root(workspace_dir)
        if err or root is None:
            return json.dumps({"error": err or "Could not resolve projects root."})
        projects = _list_sessions_under(root)
        return json.dumps({
            "projects": projects,
            "count": len(projects),
            "projects_root": str(root.resolve()),
            "workspace_dir": str(Path(workspace_dir).expanduser().resolve()),
        })

    # Default: agent-repo projects/ + any indexed workspace sessions not
    # already under OUTPUT_ROOT (so list_projects still finds them).
    seen: set[str] = set()
    projects: list[dict] = []
    for entry in _list_sessions_under(OUTPUT_ROOT):
        seen.add(entry["session_id"])
        projects.append(entry)
    for session_id, meta in _load_session_index().items():
        if session_id in seen or not isinstance(meta, dict):
            continue
        raw = meta.get("project_dir")
        if not raw:
            continue
        session_dir = Path(str(raw))
        if not session_dir.is_dir() or not _state_path(session_dir).is_file():
            continue
        try:
            mtime = datetime.fromtimestamp(
                _state_path(session_dir).stat().st_mtime
            )
            projects.append({
                "project_name": session_dir.parent.name,
                "session_id": session_id,
                "project_dir": str(session_dir.resolve()),
                "workspace_dir": meta.get("workspace_dir"),
                "last_modified": mtime.isoformat(),
            })
            seen.add(session_id)
        except OSError:
            continue

    return json.dumps({
        "projects": projects,
        "count": len(projects),
        "projects_root": str(OUTPUT_ROOT.resolve()),
    })


@mcp.tool()
def build(
    session_id: str,
    force: bool = False,
    workspace_dir: str | None = None,
) -> str:
    """Build the full FEWS configuration (generate XML files).

    This runs the complete build pipeline: writes project.yaml, expands
    patterns, ingests CSVs, applies bundled standards, runs derivers,
    and validates all XML against XSD schemas.

    Args:
        session_id: The session_id from create_project.
        force: If True, build even if there are warnings. Default False.
        workspace_dir: Optional. Same workspace path passed to create_project.

    Returns:
        JSON with build results: ok (bool), file counts, XSD validation status,
        absolute output_root / project_dir, and any errors. Tell the user
        where the files are so they can open them in their workspace.
    """
    project_dir = _resolve_session_dir(session_id, workspace_dir)
    if project_dir is None:
        return json.dumps({"error": f"Session '{session_id}' not found."})

    try:
        state, history = _load(project_dir)
    except Exception as e:
        return json.dumps({"error": f"Failed to load session: {e}"})

    catalog = _catalog()

    # Resolve patterns from current slots
    resolve_patterns(state, catalog)
    if not state.get("patterns"):
        return json.dumps({
            "error": "No patterns resolved yet. Add an import or basin first.",
        })

    # Check warnings unless forced
    warnings = list(state.get("warnings") or [])
    if warnings and not force:
        return json.dumps({
            "error": f"{len(warnings)} unresolved warning(s). Pass force=True to build anyway.",
            "warnings": warnings,
        })

    # Write project.yaml
    try:
        project_path = write_project(state, project_dir)
    except Exception as e:
        return json.dumps({"error": f"Failed to write project.yaml: {e}"})

    _save(project_dir, state, history)

    # Run the build
    inputs_dir = project_dir / "inputs"
    silent = Console(file=io.StringIO(), force_terminal=False)

    try:
        summary = build_from_blueprint(
            blueprint_path=Path(project_path),
            pattern_root=PATTERNS_ROOT,
            inputs_dir=inputs_dir if inputs_dir.is_dir() else None,
            console=silent,
        )
    except Exception as e:
        return json.dumps({"error": f"Build failed: {e}"})

    # Update state with build results
    if isinstance(summary, dict):
        state["last_build_summary"] = summary
        if summary.get("ok"):
            state["full_build_ok"] = True
        _save(project_dir, state, history)

    # Snapshot the derived tree so later hand-edits are detectable (drift).
    try:
        _write_generated_manifest(project_dir)
    except OSError:
        pass

    output_root = summary.get("output_root") or str(_generated_dir(project_dir))
    return json.dumps({
        "ok": bool(summary.get("ok")),
        "files_total": summary.get("files_total", 0),
        "files_xml": summary.get("files_xml", 0),
        "files_xsd_ok": summary.get("files_xsd_ok", 0),
        "errors": list(summary.get("errors") or []),
        "output_root": output_root,
        "project_dir": str(project_dir.resolve()),
        "workspace_dir": state.get("workspace_dir"),
        "project_yaml": str(Path(project_path).resolve()),
        "message": (
            f"Build complete: {summary.get('files_xsd_ok', 0)}/{summary.get('files_xml', 0)} "
            f"XML files passed XSD validation. Open the files at: {output_root}"
            if summary.get("ok")
            else f"Build completed with errors: {len(summary.get('errors') or [])} error(s)."
        ),
    })


@mcp.tool()
def build_phase(
    session_id: str,
    phase: str,
    workspace_dir: str | None = None,
) -> str:
    """Build a single capability phase (scoped build).

    Use this to build incrementally: imports → process → model → visualize.
    Scoped builds skip whole-project stages (singletons, derivers).

    Args:
        session_id: The session_id from create_project.
        phase: One of: imports, process, model, visualize.
        workspace_dir: Optional. Same workspace path passed to create_project.

    Returns:
        JSON with build results for that phase, including absolute output_root.
    """
    valid_phases = ("imports", "process", "model", "visualize")
    phase_lower = phase.lower().strip()
    if phase_lower not in valid_phases:
        return json.dumps({
            "error": f"Invalid phase '{phase}'. Valid phases: {', '.join(valid_phases)}",
        })

    project_dir = _resolve_session_dir(session_id, workspace_dir)
    if project_dir is None:
        return json.dumps({"error": f"Session '{session_id}' not found."})

    try:
        state, history = _load(project_dir)
    except Exception as e:
        return json.dumps({"error": f"Failed to load session: {e}"})

    catalog = _catalog()
    resolve_patterns(state, catalog)

    if not state.get("patterns"):
        return json.dumps({
            "error": "No patterns resolved yet. Add an import or basin first.",
        })

    # Write project.yaml
    try:
        project_path = write_project(state, project_dir)
    except Exception as e:
        return json.dumps({"error": f"Failed to write project.yaml: {e}"})

    _save(project_dir, state, history)

    # Run the scoped build
    silent = Console(file=io.StringIO(), force_terminal=False)

    try:
        summary = _build_phase(
            blueprint_path=Path(project_path),
            pattern_root=PATTERNS_ROOT,
            phase=phase_lower,
            console=silent,
        )
    except Exception as e:
        return json.dumps({"error": f"Build phase failed: {e}"})

    # Update state
    if isinstance(summary, dict) and summary.get("ok"):
        built = state.setdefault("built_phases", [])
        if phase_lower not in built:
            built.append(phase_lower)
        state["last_build_summary"] = summary
        _save(project_dir, state, history)

    output_root = summary.get("output_root") or str(_generated_dir(project_dir))
    return json.dumps({
        "ok": bool(summary.get("ok")),
        "phase": phase_lower,
        "files_total": summary.get("files_total", 0),
        "files_xsd_ok": summary.get("files_xsd_ok", 0),
        "errors": list(summary.get("errors") or []),
        "output_root": output_root,
        "project_dir": str(project_dir.resolve()),
        "workspace_dir": state.get("workspace_dir"),
        "message": (
            f"Phase '{phase_lower}' built: {summary.get('files_xsd_ok', 0)} files "
            f"XSD-valid. Open the files at: {output_root}"
            if summary.get("ok")
            else f"Phase '{phase_lower}' completed with errors."
        ),
    })


@mcp.tool()
def list_imports() -> str:
    """List available NWP import sources.

    These are the valid source names you can add with the add_import tool,
    e.g., add_import(name="GFS") or add_import(name="HRDPS").

    Returns:
        JSON with list of import source names and their pattern paths.
    """
    imports = []
    for name, (path, _) in sorted(_IMPORT_PATTERN_MAP.items()):
        imports.append({
            "name": name,
            "pattern": path,
        })

    return json.dumps({
        "imports": imports,
        "count": len(imports),
        "usage": "Pass a name to add_import, e.g. add_import(name='GFS').",
    })


@mcp.tool()
def list_modules() -> str:
    """List FEWS modules (the folder structure of a FEWS configuration).

    Each module represents a group of related configuration files.
    Use this to understand the structure of a FEWS config.

    Returns:
        JSON with list of modules, their keys, and descriptions.
    """
    modules = []
    for m in _list_modules():
        modules.append({
            "key": m.key,
            "label": m.label,
            "description": m.description[:200] if m.description else None,
            "folders": m.folders,
        })

    return json.dumps({
        "modules": modules,
        "count": len(modules),
    })


# ---------------------------------------------------------------------------
# Blueprint-first tools: read surface
# ---------------------------------------------------------------------------


@mcp.tool()
def list_capabilities() -> str:
    """List every capability that can be added to a blueprint.

    Returns the pattern catalog digest: the canonical import-source names
    (for add_import), plus each capability's required and optional variables
    and the files it produces. Use this before add_capability / add_import so
    you name things that actually exist — anything else is dropped loudly.

    Returns:
        JSON with a human-readable ``catalog`` digest and a structured
        ``import_sources`` list.
    """
    catalog = _catalog()
    return json.dumps({
        "catalog": catalog_digest(catalog),
        "import_sources": sorted(_IMPORT_PATTERN_MAP),
        "count": len(catalog),
    })


@mcp.tool()
def get_blueprint(
    session_id: str,
    workspace_dir: str | None = None,
) -> str:
    """Read the project's blueprint (project.yaml) and a structured digest.

    The blueprint is the single editing surface: patterns + singleton seeds.
    If it was hand-edited since the last tool call, it is auto-synced back
    into the session first. If it doesn't exist yet, it is written from the
    current state.

    Args:
        session_id: The session_id from create_project.
        workspace_dir: Optional. Same workspace path passed to create_project.

    Returns:
        JSON with the raw project.yaml text, resolved patterns, imports,
        basins, singleton seeds, the inputs/ file list, and build status.
    """
    project_dir = _resolve_session_dir(session_id, workspace_dir)
    if project_dir is None:
        return json.dumps({"error": f"Session '{session_id}' not found."})

    try:
        state, history = _load(project_dir)
    except Exception as e:  # noqa: BLE001
        return json.dumps({"error": f"Failed to load session: {e}"})

    synced = _maybe_sync_blueprint(project_dir, state)
    project_path = project_dir / "project.yaml"
    if synced:
        _save(project_dir, state, history)
    elif not project_path.is_file():
        catalog = _catalog()
        _ensure_intent_and_resolve(state, catalog)
        try:
            write_project(state, project_dir)
        except Exception as e:  # noqa: BLE001
            return json.dumps({"error": f"Failed to write project.yaml: {e}"})
        _save(project_dir, state, history)

    yaml_text = (
        project_path.read_text(encoding="utf-8")
        if project_path.is_file() else ""
    )
    inputs_dir = project_dir / "inputs"
    inputs = (
        sorted(p.name for p in inputs_dir.iterdir() if p.is_file())
        if inputs_dir.is_dir() else []
    )
    slots = state.get("slots") or {}
    summary = state.get("last_build_summary") or {}
    return json.dumps({
        "project_name": state.get("name"),
        "project_yaml": yaml_text,
        "project_yaml_path": str(project_path.resolve()),
        "patterns": [p.get("pattern") for p in (state.get("patterns") or [])],
        "imports": slots.get("imports") or [],
        "basins": [b.get("basin_name") for b in (slots.get("basins") or [])],
        "singleton_seeds": state.get("singleton_seeds") or {},
        "inputs": inputs,
        "synced_from_blueprint": synced or [],
        "generated_exists": _generated_dir(project_dir).is_dir(),
        "last_build_ok": bool(summary.get("ok")) if summary else None,
        "project_dir": str(project_dir.resolve()),
    })


@mcp.tool()
def reload_blueprint(
    session_id: str,
    workspace_dir: str | None = None,
) -> str:
    """Force a reverse-sync of a hand-edited project.yaml into the session.

    Normally the edit tools auto-sync when project.yaml is newer than the
    saved state. Call this explicitly after editing project.yaml by hand to
    make the change visible to get_blueprint / the typed tools immediately.

    Args:
        session_id: The session_id from create_project.
        workspace_dir: Optional. Same workspace path passed to create_project.

    Returns:
        JSON with the reconstructed imports/basins/patterns and sync notes.
    """
    project_dir = _resolve_session_dir(session_id, workspace_dir)
    if project_dir is None:
        return json.dumps({"error": f"Session '{session_id}' not found."})
    if not (project_dir / "project.yaml").is_file():
        return json.dumps({"error": "No project.yaml to reload. Build or add first."})

    try:
        state, history = _load(project_dir)
    except Exception as e:  # noqa: BLE001
        return json.dumps({"error": f"Failed to load session: {e}"})

    notes = load_blueprint_into_state(state, project_dir)
    _save(project_dir, state, history)
    slots = state.get("slots") or {}
    return json.dumps({
        "notes": notes,
        "imports": slots.get("imports") or [],
        "basins": [b.get("basin_name") for b in (slots.get("basins") or [])],
        "patterns": [p.get("pattern") for p in (state.get("patterns") or [])],
        "project_dir": str(project_dir.resolve()),
    })


# ---------------------------------------------------------------------------
# Blueprint-first tools: typed deterministic edits (patch_ops surface)
# ---------------------------------------------------------------------------


@mcp.tool()
def add_import(
    session_id: str,
    name: str,
    data_types: list[str] | None = None,
    grid_resolution: str | None = None,
    forecast_horizon_hours: int | None = None,
    workspace_dir: str | None = None,
) -> str:
    """Add an NWP/data import to the blueprint (deterministic).

    Args:
        session_id: The session_id from create_project.
        name: Import source name (see list_capabilities / list_imports), e.g.
            GFS, HRDPS, ERA5. Unknown names are dropped loudly.
        data_types: Optional weather variables, e.g. ["precipitation",
            "temperature"]. Unrecognised ones are dropped loudly.
        grid_resolution: Optional NOAA slug (0p25 / 0p50 / 1p00).
        forecast_horizon_hours: Optional per-import display window in hours.
        workspace_dir: Optional. Same workspace path passed to create_project.

    Returns:
        JSON with applied notes, any dropped (invalid) fields, and the
        refreshed blueprint summary.
    """
    project_dir = _resolve_session_dir(session_id, workspace_dir)
    if project_dir is None:
        return json.dumps({"error": f"Session '{session_id}' not found."})
    op: dict = {"op": "add_import", "name": name}
    if data_types:
        op["data_types"] = list(data_types)
    if grid_resolution is not None:
        op["grid_resolution"] = grid_resolution
    if forecast_horizon_hours is not None:
        op["forecast_horizon_hours"] = forecast_horizon_hours
    return json.dumps(_apply_ops(project_dir, [op]))


@mcp.tool()
def add_basin(
    session_id: str,
    basin_name: str,
    model_adapter: str,
    workspace_dir: str | None = None,
) -> str:
    """Add a basin model run to the blueprint (deterministic).

    Args:
        session_id: The session_id from create_project.
        basin_name: The basin's name, e.g. Liard.
        model_adapter: The model adapter — one of raven, wflow, hbv96. An
            unknown adapter is dropped loudly (never guessed).
        workspace_dir: Optional. Same workspace path passed to create_project.

    Returns:
        JSON with applied notes, any dropped ops, and the blueprint summary.
    """
    project_dir = _resolve_session_dir(session_id, workspace_dir)
    if project_dir is None:
        return json.dumps({"error": f"Session '{session_id}' not found."})
    op = {
        "op": "add_basin",
        "basin_name": basin_name,
        "model_adapter": model_adapter,
    }
    return json.dumps(_apply_ops(project_dir, [op]))


@mcp.tool()
def add_capability(
    session_id: str,
    name: str,
    workspace_dir: str | None = None,
) -> str:
    """Add a non-import capability/pattern to the blueprint (deterministic).

    Use for things like spatial display, interpolation, or any pattern from
    list_capabilities that isn't an import or basin. A capability with unmet
    required variables, or one not in the library, is dropped loudly.

    Args:
        session_id: The session_id from create_project.
        name: A pattern name or path from list_capabilities.
        workspace_dir: Optional. Same workspace path passed to create_project.

    Returns:
        JSON with applied notes, any dropped ops, and the blueprint summary.
    """
    project_dir = _resolve_session_dir(session_id, workspace_dir)
    if project_dir is None:
        return json.dumps({"error": f"Session '{session_id}' not found."})
    return json.dumps(_apply_ops(project_dir, [{"op": "add_capability", "pattern": name}]))


@mcp.tool()
def set_variables(
    session_id: str,
    target: str,
    values: dict,
    workspace_dir: str | None = None,
) -> str:
    """Set variables on the blueprint (deterministic).

    Args:
        session_id: The session_id from create_project.
        target: The import/basin the variables apply to (e.g. "GFS"), or ""
            for project-wide settings (geoDatum, region, feature flags).
        values: A mapping of variable → value, e.g.
            {"grid_resolution": "0p50"} or {"forecast_horizon_hours": 168}
            or {"region": "Gulf of Guinea"}. Unknown variables are dropped
            loudly.
        workspace_dir: Optional. Same workspace path passed to create_project.

    Returns:
        JSON with applied notes, any dropped variables, and the blueprint
        summary.
    """
    project_dir = _resolve_session_dir(session_id, workspace_dir)
    if project_dir is None:
        return json.dumps({"error": f"Session '{session_id}' not found."})
    if not isinstance(values, dict) or not values:
        return json.dumps({"error": "values must be a non-empty object."})
    op = {"op": "set_variables", "target": target, "values": values}
    return json.dumps(_apply_ops(project_dir, [op]))


@mcp.tool()
def remove_item(
    session_id: str,
    target: str,
    variable: str | None = None,
    workspace_dir: str | None = None,
) -> str:
    """Remove an import/basin/capability, or clear one variable (deterministic).

    Args:
        session_id: The session_id from create_project.
        target: What to remove — an import name (GFS), a basin name (Liard),
            a data type (precipitation), or a capability. With ``variable``
            set, ``target`` scopes which import the variable is cleared on.
        variable: Optional. When set, clear just this variable instead of
            removing the whole item (e.g. target="GFS", variable="horizon").
        workspace_dir: Optional. Same workspace path passed to create_project.

    Returns:
        JSON with applied notes, anything not matched (dropped loudly), and
        the blueprint summary.
    """
    project_dir = _resolve_session_dir(session_id, workspace_dir)
    if project_dir is None:
        return json.dumps({"error": f"Session '{session_id}' not found."})
    op: dict = {"op": "remove", "target": target}
    if variable is not None:
        op["variable"] = variable
    return json.dumps(_apply_ops(project_dir, [op]))


# ---------------------------------------------------------------------------
# Blueprint-first tools: standalone validate + drift
# ---------------------------------------------------------------------------


@mcp.tool()
def validate(
    session_id: str,
    workspace_dir: str | None = None,
) -> str:
    """Validate the generated config tree on disk (XSD + cross-references).

    Runs WITHOUT rebuilding — it checks whatever XML is currently on disk, so
    it also catches problems introduced by hand-editing generated files.
    Reports per-file XSD failures and unresolved cross-file ID references
    (parameterId, locationSetId, locationId, idMapId, moduleInstanceId),
    excluding FEWS runtime placeholders.

    Args:
        session_id: The session_id from create_project.
        workspace_dir: Optional. Same workspace path passed to create_project.

    Returns:
        JSON with ok, xml_total, xsd_ok, xsd_failures, and references by kind.
    """
    project_dir = _resolve_session_dir(session_id, workspace_dir)
    if project_dir is None:
        return json.dumps({"error": f"Session '{session_id}' not found."})
    report = _validate_generated(_generated_dir(project_dir))
    report["project_dir"] = str(project_dir.resolve())
    return json.dumps(report)


@mcp.tool()
def check_drift(
    session_id: str,
    workspace_dir: str | None = None,
) -> str:
    """Detect whether the generated tree was hand-edited since the last build.

    The blueprint is the source of truth; the generated tree is derived. If
    files there changed since the last build, a rebuild will overwrite them —
    the fix belongs in project.yaml (or inputs/), not the generated XML.

    Args:
        session_id: The session_id from create_project.
        workspace_dir: Optional. Same workspace path passed to create_project.

    Returns:
        JSON with drifted (bool) and the changed/added/removed file lists.
    """
    project_dir = _resolve_session_dir(session_id, workspace_dir)
    if project_dir is None:
        return json.dumps({"error": f"Session '{session_id}' not found."})
    drift = _detect_drift(project_dir)
    if not drift.get("has_manifest"):
        drift["message"] = "No build manifest yet — run build first."
    elif drift.get("drifted"):
        drift["message"] = (
            "Generated files were hand-edited since the last build. Rebuild "
            "will overwrite them — edit project.yaml or inputs/ instead."
        )
    else:
        drift["message"] = "No drift — generated tree matches the last build."
    drift["project_dir"] = str(project_dir.resolve())
    return json.dumps(drift)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main():
    """Run the MCP server with STDIO transport."""
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
