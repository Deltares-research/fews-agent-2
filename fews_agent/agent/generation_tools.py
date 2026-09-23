"""Path-based generation tools (MCP / HTTP serialize these).

Known shapes go pattern → Jinja → XSD. Unknown shapes are admitted
only after the snippet gauntlet. No session_id — the project folder is
the key.
"""
from __future__ import annotations

import io
import json
from pathlib import Path
from typing import Any

from rich.console import Console

from fews_agent.agent.authoring import AuthoredFile, write_authored
from fews_agent.agent.patch_ops import apply_patch
from fews_agent.agent.project_chat import (
    build_pattern_catalog,
    initial_state,
    write_project,
)
from fews_agent.agent.session_io import load_session, save_session, state_path
from fews_agent.agent.turn_engine import resolve_patterns
from fews_agent.validation.gauntlet import validate_xml

REPO_ROOT = Path(__file__).resolve().parents[2]
PATTERNS_ROOT = REPO_ROOT / "fews_agent" / "patterns"


def _catalog():
    return build_pattern_catalog(PATTERNS_ROOT)


def _config_root(path: Path) -> Path:
    """Where XML lives: ``generated/`` for a session, else the folder itself."""
    root = Path(path)
    if (root / "project.yaml").is_file():
        dest = root / "generated"
        dest.mkdir(parents=True, exist_ok=True)
        return dest
    return root


def _parse_ops(ops: Any) -> list:
    if ops is None or ops == "":
        return []
    if isinstance(ops, str):
        parsed = json.loads(ops)
    else:
        parsed = ops
    if not isinstance(parsed, list):
        raise ValueError("ops must be a JSON array of {op, ...} objects")
    return parsed


def tool_list_patterns(query: str | None = None) -> dict[str, Any]:
    qtoks = [t for t in (query or "").lower().split() if t]
    items: list[dict[str, Any]] = []
    for p in _catalog():
        blob = " ".join([
            p.path, p.name, p.description or "", " ".join(p.keywords or []),
        ]).lower()
        if qtoks and not all(t in blob for t in qtoks):
            continue
        items.append({
            "path": p.path,
            "name": p.name,
            "description": (p.description or "")[:240],
            "variables": p.variables,
            "outputs": p.outputs,
        })
    return {"query": query, "count": len(items), "patterns": items}


def tool_create_project(path: str, name: str | None = None) -> dict[str, Any]:
    root = Path(path)
    root.mkdir(parents=True, exist_ok=True)
    (root / "inputs").mkdir(exist_ok=True)
    if state_path(root).is_file():
        state, _ = load_session(root)
        return {
            "path": str(root.resolve()),
            "name": state.get("name"),
            "reopened": True,
            "patterns": state.get("patterns") or [],
        }
    project_name = (name or root.name).strip() or "fews-project"
    state = initial_state(project_name)
    state.setdefault("intent", None)
    state.setdefault("slots", {})
    save_session(root, state, [])
    write_project(state, root)
    return {
        "path": str(root.resolve()),
        "name": project_name,
        "reopened": False,
        "patterns": [],
    }


def tool_apply_slots(path: str, ops: Any) -> dict[str, Any]:
    root = Path(path)
    if not state_path(root).is_file():
        return {"error": f"no session at {root} — call create_project first"}
    try:
        parsed = _parse_ops(ops)
    except (ValueError, json.JSONDecodeError) as exc:
        return {"error": f"ops: {exc}"}
    state, history = load_session(root)
    catalog = _catalog()
    result = apply_patch(state, parsed, catalog)
    resolve_patterns(state, catalog)
    write_project(state, root)
    save_session(root, state, history)
    dropped = [
        d.replace("use author_file", "use admit_file (or author_file in chat)")
        if isinstance(d, str) else d
        for d in result.dropped
    ]
    return {
        "path": str(root.resolve()),
        "notes": list(result.notes),
        "dropped": dropped,
        "patterns": state.get("patterns") or [],
        "slots": state.get("slots") or {},
        "intent": state.get("intent"),
    }


def tool_build_project(path: str, phase: str | None = None) -> dict[str, Any]:
    from fews_agent.agent.phases import normalize_phase
    from runners.agent.build_from_blueprint import (
        build_from_blueprint,
        build_phase,
    )

    root = Path(path)
    if not state_path(root).is_file():
        return {"error": f"no session at {root} — call create_project first"}
    state, history = load_session(root)
    catalog = _catalog()
    resolve_patterns(state, catalog)
    if not state.get("patterns"):
        return {
            "error": "No patterns resolved — apply_slots with add_import / "
            "add_basin first. Do not hand-write XML for a catalog pattern.",
            "dropped": [],
        }
    project_path = write_project(state, root)
    save_session(root, state, history)
    silent = Console(file=io.StringIO(), force_terminal=False)
    inputs_dir = root / "inputs"
    try:
        if phase:
            ph = normalize_phase(phase)
            if ph is None:
                return {"error": f"unknown phase {phase!r}"}
            summary = build_phase(
                blueprint_path=Path(project_path),
                pattern_root=PATTERNS_ROOT,
                phase=ph,
                console=silent,
            )
        else:
            summary = build_from_blueprint(
                blueprint_path=Path(project_path),
                pattern_root=PATTERNS_ROOT,
                inputs_dir=inputs_dir if inputs_dir.is_dir() else None,
                console=silent,
            )
    except Exception as exc:  # noqa: BLE001
        return {"error": f"build failed ({type(exc).__name__}: {exc})"}
    return {
        "path": str(root.resolve()),
        "output_root": summary.get("output_root"),
        "ok": summary.get("ok"),
        "files_total": summary.get("files_total"),
        "files_xsd_ok": summary.get("files_xsd_ok"),
        "files_xml": summary.get("files_xml"),
        "skipped": list(summary.get("skipped") or []),
        "errors": list(summary.get("errors") or []),
        "files": summary.get("files") or [],
    }


def tool_admit_file(
    path: str,
    relpath: str,
    xml: str,
    spec: str | None = None,
) -> dict[str, Any]:
    """Host-authored XML: gauntlet (xsd+conform) then write origin=llm."""
    report = validate_xml(xml, spec=spec, tiers=["xsd", "conform"])
    payload: dict[str, Any] = {
        "ok": report.ok,
        "relpath": relpath,
        "diagnostics": [d.to_dict() for d in report.diagnostics],
    }
    if not report.ok:
        payload["error"] = "admit_file: gauntlet rejected the draft"
        return payload
    authored = AuthoredFile(
        relpath=relpath,
        content=xml,
        ok=True,
        verified=["xsd", "conform"],
        diagnostics=list(report.diagnostics),
    )
    dest_root = _config_root(Path(path))
    written = write_authored(dest_root, authored)
    if written is None:
        payload["ok"] = False
        payload["error"] = authored.error or "admit_file: not written"
        return payload
    payload["written"] = str(written)
    payload["origin"] = "llm"
    return payload
