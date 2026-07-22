"""MCP server — the fourth driver shell over the FEWS chat agent.

Exposes the FEWS config-generation agent to Claude Desktop, VS Code Copilot,
and other MCP-compatible AI applications via the Model Context Protocol.

This is a **direct-call** implementation (Option B from the design doc): the
MCP server imports and calls the same engine functions the HTTP API uses —
``run_llm_turn``, ``build_from_blueprint``, etc. — with no HTTP hop. Sessions
persist under ``projects/`` (the same folder the CLI, Streamlit, and HTTP
drivers use), so a project started via MCP is resumable from any other shell.

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
    write_project,
)
from fews_agent.agent.llm_turn import run_llm_turn
from fews_agent.agent.modules import list_modules as _list_modules
from fews_agent.agent.project_intents import _IMPORT_PATTERN_MAP
from fews_agent.agent.providers.factory import get_provider_or_ollama
from fews_agent.agent.turn_engine import resolve_patterns
from runners.agent.build_from_blueprint import (
    build_from_blueprint,
    build_phase as _build_phase,
)

# ---------------------------------------------------------------------------
# Paths & constants
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parents[1]
PATTERNS_ROOT = REPO_ROOT / "patterns"
OUTPUT_ROOT = REPO_ROOT / "projects"
DEFAULT_MODEL = "qwen2.5:7b-instruct"

# ---------------------------------------------------------------------------
# Session persistence — identical to app/api/server.py
# ---------------------------------------------------------------------------


def _state_path(project_dir: Path) -> Path:
    return project_dir / ".chat_state.json"


def _history_path(project_dir: Path) -> Path:
    return project_dir / ".chat_history.json"


def _new_session_dir(project_name: str) -> Path:
    """Mint a fresh datetime-stamped instance dir for a new session."""
    parent = OUTPUT_ROOT / project_name
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


def _resolve_session_dir(session_id: str) -> Path | None:
    """Find the instance dir for a session id, or None if not found."""
    if "/" in session_id or "\\" in session_id or ".." in session_id:
        return None
    for cand in OUTPUT_ROOT.glob(f"*/{session_id}"):
        if cand.is_dir() and _state_path(cand).is_file():
            return cand
    return None


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


def _model_for(state: dict) -> str:
    return state.get("model") or DEFAULT_MODEL


def _sanitize_project_name(name: str) -> str:
    """Make a project name filesystem-safe."""
    return "".join(c if (c.isalnum() or c in "-_.") else "-" for c in name)


# ---------------------------------------------------------------------------
# MCP Server
# ---------------------------------------------------------------------------

mcp = FastMCP(
    "fews-agent",
    instructions=(
        "FEWS config-generation agent. Use these tools to create Delft-FEWS "
        "XML configuration files through a conversational interface.\n\n"
        "Typical workflow:\n"
        "1. create_project — start a new project\n"
        "2. chat — add imports (GFS, HRDPS...), basin models (Raven, Wflow...), "
        "set parameters\n"
        "3. build — generate the XML files\n\n"
        "Use list_imports to see valid NWP sources. Use get_status to check "
        "current state. Sessions persist under projects/ and can be resumed."
    ),
)


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


@mcp.tool()
def create_project(project_name: str | None = None) -> str:
    """Create a new FEWS configuration project.

    Args:
        project_name: Name for the project. If not provided, a timestamped
            name is generated. The name becomes a folder under projects/.

    Returns:
        JSON with session_id (use this for subsequent calls) and project_dir.
    """
    name = (project_name or "").strip() or (
        "mcp-project-" + datetime.now().strftime("%Y%m%d-%H%M%S")
    )
    safe = _sanitize_project_name(name)
    project_dir = _new_session_dir(safe)
    (project_dir / "inputs").mkdir(exist_ok=True)

    state = initial_state(safe)
    state.setdefault("intent", None)
    state.setdefault("slots", {})
    state["model"] = os.environ.get("FEWS_AGENT_MODEL") or DEFAULT_MODEL
    _save(project_dir, state, [])

    return json.dumps({
        "session_id": project_dir.name,
        "project_name": safe,
        "project_dir": str(project_dir),
        "message": f"Created project '{safe}'. Use the session_id in subsequent calls.",
    })


@mcp.tool()
def chat(session_id: str, message: str) -> str:
    """Send a message to the FEWS agent and get a response.

    This is the main conversational interface. Use it to:
    - Add NWP imports: "add a GFS import with precipitation and temperature"
    - Add basin models: "add a Raven model for the Liard basin"
    - Set parameters: "set the forecast horizon to 7 days"
    - Ask questions: "what imports are configured?"

    Args:
        session_id: The session_id from create_project.
        message: Your message to the agent.

    Returns:
        JSON with the agent's reply, any confirmation of changes made,
        new patterns added, and whether a build was requested.
    """
    project_dir = _resolve_session_dir(session_id)
    if project_dir is None:
        return json.dumps({
            "error": f"Session '{session_id}' not found. Use create_project first.",
        })

    try:
        state, history = _load(project_dir)
    except Exception as e:
        return json.dumps({"error": f"Failed to load session: {e}"})

    catalog = _catalog()
    model = _model_for(state)
    history.append({"role": "user", "message": message})

    try:
        provider = get_provider_or_ollama(model)
        result = run_llm_turn(
            state, message, catalog, provider=provider,
            history=history, inputs_dir=project_dir / "inputs",
        )
    except Exception as e:
        return json.dumps({
            "error": f"LLM call failed: {e}. Check that the LLM backend is running.",
            "hint": "Set FEWS_AGENT_PROVIDER and related env vars if using Azure/Anthropic.",
        })

    history.append({"role": "agent", "message": result.reply})
    _save(project_dir, state, history)

    response = {
        "reply": result.reply,
        "confirmation": result.confirmation or None,
        "new_patterns": result.new_patterns or [],
        "wants_build": result.wants_build or result.wants_assemble,
    }
    if result.wants_build or result.wants_assemble:
        response["hint"] = "Use the build tool to generate XML files."

    return json.dumps(response)


@mcp.tool()
def get_status(session_id: str) -> str:
    """Get the current status of a project.

    Returns the configured imports, basins, patterns, warnings, and build progress.

    Args:
        session_id: The session_id from create_project.

    Returns:
        JSON with current project state including slots, patterns, and build status.
    """
    project_dir = _resolve_session_dir(session_id)
    if project_dir is None:
        return json.dumps({"error": f"Session '{session_id}' not found."})

    try:
        state, _ = _load(project_dir)
    except Exception as e:
        return json.dumps({"error": f"Failed to load session: {e}"})

    slots = state.get("slots") or {}
    return json.dumps({
        "project_name": state.get("name"),
        "imports": slots.get("imports") or [],
        "basins": slots.get("basins") or [],
        "patterns": [p.get("pattern") for p in (state.get("patterns") or [])],
        "warnings": state.get("warnings") or [],
        "built_phases": state.get("built_phases") or [],
        "full_build_ok": state.get("full_build_ok", False),
        "current_module": state.get("current_module"),
    })


@mcp.tool()
def list_projects() -> str:
    """List all existing FEWS projects.

    Returns:
        JSON with list of projects, each with name, session_id, and last modified time.
    """
    projects = []
    if OUTPUT_ROOT.is_dir():
        for project_folder in sorted(OUTPUT_ROOT.iterdir()):
            if not project_folder.is_dir():
                continue
            # Find session dirs within the project folder
            for session_dir in sorted(project_folder.iterdir(), reverse=True):
                state_file = _state_path(session_dir)
                if state_file.is_file():
                    try:
                        mtime = datetime.fromtimestamp(state_file.stat().st_mtime)
                        projects.append({
                            "project_name": project_folder.name,
                            "session_id": session_dir.name,
                            "last_modified": mtime.isoformat(),
                        })
                    except OSError:
                        continue

    return json.dumps({
        "projects": projects,
        "count": len(projects),
    })


@mcp.tool()
def build(session_id: str, force: bool = False) -> str:
    """Build the full FEWS configuration (generate XML files).

    This runs the complete build pipeline: writes project.yaml, expands
    patterns, ingests CSVs, applies bundled standards, runs derivers,
    and validates all XML against XSD schemas.

    Args:
        session_id: The session_id from create_project.
        force: If True, build even if there are warnings. Default False.

    Returns:
        JSON with build results: ok (bool), file counts, XSD validation status,
        output directory, and any errors.
    """
    project_dir = _resolve_session_dir(session_id)
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
            "error": "No patterns resolved yet. Use chat to add imports or models first.",
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

    return json.dumps({
        "ok": bool(summary.get("ok")),
        "files_total": summary.get("files_total", 0),
        "files_xml": summary.get("files_xml", 0),
        "files_xsd_ok": summary.get("files_xsd_ok", 0),
        "errors": list(summary.get("errors") or []),
        "output_root": summary.get("output_root"),
        "project_yaml": str(project_path),
        "message": (
            f"Build complete: {summary.get('files_xsd_ok', 0)}/{summary.get('files_xml', 0)} "
            f"XML files passed XSD validation."
            if summary.get("ok")
            else f"Build completed with errors: {len(summary.get('errors') or [])} error(s)."
        ),
    })


@mcp.tool()
def build_phase(session_id: str, phase: str) -> str:
    """Build a single capability phase (scoped build).

    Use this to build incrementally: imports → process → model → visualize.
    Scoped builds skip whole-project stages (singletons, derivers).

    Args:
        session_id: The session_id from create_project.
        phase: One of: imports, process, model, visualize.

    Returns:
        JSON with build results for that phase.
    """
    valid_phases = ("imports", "process", "model", "visualize")
    phase_lower = phase.lower().strip()
    if phase_lower not in valid_phases:
        return json.dumps({
            "error": f"Invalid phase '{phase}'. Valid phases: {', '.join(valid_phases)}",
        })

    project_dir = _resolve_session_dir(session_id)
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
            "error": "No patterns resolved yet. Use chat to add imports or models first.",
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

    return json.dumps({
        "ok": bool(summary.get("ok")),
        "phase": phase_lower,
        "files_total": summary.get("files_total", 0),
        "files_xsd_ok": summary.get("files_xsd_ok", 0),
        "errors": list(summary.get("errors") or []),
        "message": (
            f"Phase '{phase_lower}' built: {summary.get('files_xsd_ok', 0)} files XSD-valid."
            if summary.get("ok")
            else f"Phase '{phase_lower}' completed with errors."
        ),
    })


@mcp.tool()
def list_imports() -> str:
    """List available NWP import sources.

    These are the valid source names you can add with the chat tool,
    e.g., "add a GFS import" or "add HRDPS with precipitation".

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
        "usage": "Use 'add a <name> import' in the chat tool, e.g., 'add a GFS import'.",
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
# Entry point
# ---------------------------------------------------------------------------


def main():
    """Run the MCP server with STDIO transport."""
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
