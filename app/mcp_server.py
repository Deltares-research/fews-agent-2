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
from fews_agent.agent import module_focus
from fews_agent.agent.project_chat import (
    build_pattern_catalog,
    initial_state,
    write_project,
)
from fews_agent.agent.llm_turn import run_llm_turn
from fews_agent.agent.modules import list_modules as _list_modules
from fews_agent.agent.project_intents import (
    _IMPORT_PATTERN_MAP,
    compute_input_status,
    scan_inputs,
)
from fews_agent.agent.project_route import route_position
from fews_agent.agent.providers.factory import get_provider_or_ollama
from fews_agent.agent.turn_engine import (
    module_vars_reply,
    module_welcome,
    resolve_patterns,
)
from runners.agent.build_from_blueprint import (
    build_from_blueprint,
    build_phase as _build_phase,
)
from app import project_git

# ---------------------------------------------------------------------------
# Paths & constants
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parents[1]
# Patterns relocated into the package (same path as Streamlit / HTTP API).
PATTERNS_ROOT = REPO_ROOT / "fews_agent" / "patterns"
# Default project store when no workspace_dir is passed (agent-repo local).
OUTPUT_ROOT = REPO_ROOT / "projects"
# Under a client workspace, sessions land in <workspace>/fews-projects/.
WORKSPACE_PROJECTS_SUBDIR = "fews-projects"
# Maps session_id → absolute project_dir so later tools find workspace
# sessions without re-passing workspace_dir every turn.
_SESSION_INDEX_PATH = OUTPUT_ROOT / ".mcp_session_index.json"
DEFAULT_MODEL = "qwen2.5:7b-instruct"
_UNDO_DEPTH = 10

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


def _model_for(state: dict) -> str:
    return state.get("model") or DEFAULT_MODEL


def _generated_dir(project_dir: Path) -> Path:
    return project_dir / "generated"


def _push_undo_snapshot(state: dict) -> None:
    """Snapshot state before a mutating turn (same contract as Streamlit)."""
    snap = json.loads(json.dumps(state, default=str))
    snap.pop("_undo_stack", None)
    stack = state.setdefault("_undo_stack", [])
    stack.append(snap)
    if len(stack) > _UNDO_DEPTH:
        del stack[0]


def _pop_undo_snapshot(state: dict, *, keep_model: str | None = None) -> bool:
    """Restore the latest undo snapshot in-place. False if stack empty."""
    stack = state.get("_undo_stack") or []
    if not stack:
        return False
    snap = stack.pop()
    new_stack = list(stack)
    model = keep_model if keep_model is not None else state.get("model")
    state.clear()
    state.update(snap)
    state["_undo_stack"] = new_stack
    if model:
        state["model"] = model
    return True


def _module_command(state: dict, message: str, catalog) -> str | None:
    """Deterministic slash commands (no LLM) — mirrors the HTTP API shell."""
    cmd = message.lower().strip()
    if cmd in {"/modules", "modules"}:
        reply = module_focus.modules_overview()
        cur = state.get("current_module")
        return reply + (f"\n\nIn focus now: {cur}." if cur else "")
    if cmd == "/module" or cmd.startswith("/module "):
        if cmd == "/module":
            cur = module_focus.get_focus(state)
            return (
                module_welcome(state, cur) if cur
                else "No module in focus. Pick one with  /module <name>  "
                     "(see  /modules  for the list)."
            )
        token = message.strip().split(None, 1)[1].strip()
        _module, reply = module_focus.set_focus(state, token)
        return module_welcome(state, _module) if _module is not None else reply
    if cmd in {"/vars", "vars"} or cmd.startswith(("/vars ", "vars ")) \
            or cmd in {"/list", "list", "/show", "show"}:
        parts = message.strip().split(None, 1)
        target = parts[1].strip() if len(parts) > 1 else None
        return module_vars_reply(state, catalog, target)
    if cmd in {"/undo", "undo"}:
        if not _pop_undo_snapshot(state):
            return "Nothing to undo — no prior state snapshot recorded."
        slots = state.get("slots") or {}
        filled = sum(1 for v in slots.values() if v)
        depth = len(state.get("_undo_stack") or [])
        return (
            f"Rolled back — {filled} setting(s), "
            f"{len(state.get('patterns') or [])} module(s). "
            f"{depth} more snapshot(s) available."
        )
    return None


def _change_diff_text(project_dir: Path, label: str) -> str:
    """Appendable markdown for files changed by the last agent action."""
    return project_git.format_diffs(
        project_git.commit_and_diff(project_dir, label)
    )


def _status_route_block(state: dict, project_dir: Path) -> dict:
    """Compact route + input readiness for get_status (host-LLM grounding)."""
    inputs_dir = project_dir / "inputs"
    pos = route_position(state, inputs_dir if inputs_dir.is_dir() else None)
    scan = scan_inputs(inputs_dir if inputs_dir.is_dir() else None)
    input_status = compute_input_status(
        state.get("intent"), scan, state.get("slots") or {},
    )
    current = None
    if pos.current is not None:
        current = {
            "id": pos.current.id,
            "title": pos.current.title,
            "kind": pos.current.kind,
            "guidance": pos.current.guidance,
        }
    return {
        "current_step": current,
        "ready_to_assemble": pos.ready_to_assemble,
        "assembled": pos.assembled,
        "blocking_open": [
            {"id": lg.id, "title": lg.title, "guidance": lg.guidance}
            for lg in pos.blocking_open
        ],
        "advisory_open": [
            {"id": lg.id, "title": lg.title, "guidance": lg.guidance}
            for lg in pos.advisory_open
        ],
        "inputs": {
            "csvs_present": input_status.get("csvs_present") or [],
            "csvs_required_missing": (
                input_status.get("csvs_required_missing") or []
            ),
            "csvs_recommended_missing": (
                input_status.get("csvs_recommended_missing") or []
            ),
            "extra_notes": input_status.get("extra_notes") or [],
        },
    }


# ---------------------------------------------------------------------------
# MCP Server
# ---------------------------------------------------------------------------

mcp = FastMCP(
    "fews-agent",
    instructions=(
        "FEWS config-generation agent. Use these tools to create Delft-FEWS "
        "XML configuration files through a conversational interface.\n\n"
        "Typical workflow:\n"
        "1. create_project — start a new project. ALWAYS pass workspace_dir "
        "set to the user's open VS Code / IDE workspace folder (absolute "
        "path) so session state and generated XML land in "
        "<workspace>/fews-projects/ where the user can open them. Omit "
        "workspace_dir only when the user is working inside the agent repo.\n"
        "2. chat — add imports (GFS, HRDPS...), basin models (Raven, Wflow...), "
        "set parameters. Slash commands (/vars, /module, /list, /undo) work "
        "without an LLM round-trip.\n"
        "3. When chat returns wants_assemble=true, call build. When "
        "wants_build=true with build_scope set to a phase name (imports/"
        "process/model/visualize), call build_phase with that phase; "
        "otherwise call build for full assembly.\n"
        "4. Tell the user the absolute output_root so they can browse files.\n\n"
        "Use list_imports to see valid NWP sources. Use get_status to check "
        "current state and the next route step. Pass the same workspace_dir "
        "to list_projects / get_status / build when helpful."
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
    project_git.ensure_repo(project_dir)
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
def chat(
    session_id: str,
    message: str,
    workspace_dir: str | None = None,
) -> str:
    """Send a message to the FEWS agent and get a response.

    This is the main conversational interface. Use it to:
    - Add NWP imports: "add a GFS import with precipitation and temperature"
    - Add basin models: "add a Raven model for the Liard basin"
    - Set parameters: "set the forecast horizon to 7 days"
    - Ask questions: "what imports are configured?"
    - Slash commands (no LLM): /vars, /module <name>, /modules, /list, /undo

    Args:
        session_id: The session_id from create_project.
        message: Your message to the agent.
        workspace_dir: Optional. Same workspace path passed to create_project;
            helps locate the session if the index is missing.

    Returns:
        JSON with the agent's reply, applied-change confirmation, new
        patterns, build signals (wants_build / wants_assemble / build_scope),
        and any input files written.
    """
    project_dir = _resolve_session_dir(session_id, workspace_dir)
    if project_dir is None:
        return json.dumps({
            "error": f"Session '{session_id}' not found. Use create_project first.",
            "hint": "If the project was created with workspace_dir, pass the "
                    "same workspace_dir here.",
        })

    try:
        state, history = _load(project_dir)
    except Exception as e:
        return json.dumps({"error": f"Failed to load session: {e}"})

    catalog = _catalog()
    model = _model_for(state)
    history.append({"role": "user", "message": message})

    # /undo must run BEFORE the snapshot push (otherwise we'd snapshot
    # current state and immediately pop that same snapshot).
    cmd_lower = message.lower().strip()
    if cmd_lower in {"/undo", "undo"}:
        reply = _module_command(state, message, catalog) or (
            "Nothing to undo — no prior state snapshot recorded."
        )
        history.append({"role": "agent", "message": reply})
        _save(project_dir, state, history)
        return json.dumps({
            "reply": reply,
            "confirmation": None,
            "new_patterns": [],
            "wants_build": False,
            "wants_assemble": False,
            "build_scope": None,
            "input_files_written": [],
            "slash_command": True,
            "undone": True,
            "project_dir": str(project_dir.resolve()),
        })

    # Snapshot before any other handler mutates state.
    _push_undo_snapshot(state)

    # Deterministic slash commands bypass the LLM (same as HTTP API).
    cmd_reply = _module_command(state, message, catalog)
    if cmd_reply is not None:
        history.append({"role": "agent", "message": cmd_reply})
        _save(project_dir, state, history)
        return json.dumps({
            "reply": cmd_reply,
            "confirmation": None,
            "new_patterns": [],
            "wants_build": False,
            "wants_assemble": False,
            "build_scope": None,
            "input_files_written": [],
            "slash_command": True,
            "project_dir": str(project_dir.resolve()),
        })

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

    reply = result.reply
    confirmation = result.confirmation or None

    # Prose "undo that" → pop this turn's snapshot, then the prior turn.
    if result.wants_undo:
        _pop_undo_snapshot(state, keep_model=model)
        if _pop_undo_snapshot(state, keep_model=model):
            slots = state.get("slots") or {}
            filled = sum(1 for v in slots.values() if v)
            confirmation = (
                f"Rolled back to the previous step — {filled} setting(s), "
                f"{len(state.get('patterns') or [])} module(s)."
            )
        else:
            confirmation = None
            reply = "There's nothing to undo yet — no earlier step recorded."
        history.append({"role": "agent", "message": reply})
        if confirmation:
            history[-1]["confirmation"] = confirmation
        _save(project_dir, state, history)
        return json.dumps({
            "reply": reply,
            "confirmation": confirmation,
            "new_patterns": [],
            "wants_build": False,
            "wants_assemble": False,
            "build_scope": None,
            "input_files_written": [],
            "undone": True,
            "project_dir": str(project_dir.resolve()),
        })

    if result.input_files_written:
        diff_text = _change_diff_text(
            project_dir,
            "update inputs: " + ", ".join(result.input_files_written),
        )
        if diff_text:
            reply += "\n\n" + diff_text

    history.append({"role": "agent", "message": reply})
    if confirmation:
        history[-1]["confirmation"] = confirmation
    _save(project_dir, state, history)

    wants_build = bool(result.wants_build)
    wants_assemble = bool(result.wants_assemble)
    response = {
        "reply": reply,
        "confirmation": confirmation,
        "new_patterns": result.new_patterns or [],
        "wants_build": wants_build or wants_assemble,
        "wants_assemble": wants_assemble,
        "build_scope": result.build_scope,
        "input_files_written": list(result.input_files_written or []),
        "project_dir": str(project_dir.resolve()),
    }
    if wants_assemble:
        response["hint"] = (
            "Call the build tool (full assembly). "
            f"XML will appear under {_generated_dir(project_dir)}."
        )
    elif wants_build:
        scope = result.build_scope
        if scope and scope.lower().strip() in (
            "imports", "process", "model", "visualize",
        ):
            response["hint"] = (
                f"Call build_phase with phase={scope!r} for a scoped build. "
                f"Files land under {_generated_dir(project_dir)}."
            )
        else:
            response["hint"] = (
                "Call build or build_phase to generate XML. "
                f"Files land under {_generated_dir(project_dir)}."
            )

    return json.dumps(response)


@mcp.tool()
def get_status(
    session_id: str,
    workspace_dir: str | None = None,
) -> str:
    """Get the current status of a project.

    Returns the configured imports, basins, patterns, warnings, build
    progress, and the route next-step / input readiness.

    Args:
        session_id: The session_id from create_project.
        workspace_dir: Optional. Same workspace path passed to create_project.

    Returns:
        JSON with current project state including slots, patterns, build
        status, route, inputs, and absolute project_dir / generated_dir paths.
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
    last = state.get("last_build_summary") or {}
    payload = {
        "project_name": state.get("name"),
        "intent": state.get("intent"),
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
        "last_build": {
            "ok": last.get("ok"),
            "files_xsd_ok": last.get("files_xsd_ok"),
            "files_xml": last.get("files_xml"),
            "semantic_unresolved_count": last.get("semantic_unresolved_count"),
            "unbacked_interpolation_sets": last.get(
                "unbacked_interpolation_sets"
            ),
        } if last else None,
    }
    try:
        payload["route"] = _status_route_block(state, project_dir)
    except Exception as e:  # noqa: BLE001 — status must still return
        payload["route"] = {"error": f"route unavailable: {e}"}
    return json.dumps(payload)


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

    diff_text = _change_diff_text(project_dir, "mcp build full")

    output_root = summary.get("output_root") or str(_generated_dir(project_dir))
    result = {
        "ok": bool(summary.get("ok")),
        "files_total": summary.get("files_total", 0),
        "files_xml": summary.get("files_xml", 0),
        "files_xsd_ok": summary.get("files_xsd_ok", 0),
        "errors": list(summary.get("errors") or []),
        "semantic_refs": summary.get("semantic_refs"),
        "semantic_unresolved_count": summary.get("semantic_unresolved_count"),
        "semantic_unresolved": list(summary.get("semantic_unresolved") or [])[:10],
        "unbacked_interpolation_sets": list(
            summary.get("unbacked_interpolation_sets") or []
        ),
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
    }
    if diff_text:
        result["diff"] = diff_text
    return json.dumps(result)


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

    diff_text = _change_diff_text(project_dir, f"mcp build phase:{phase_lower}")

    output_root = summary.get("output_root") or str(_generated_dir(project_dir))
    result = {
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
    }
    if diff_text:
        result["diff"] = diff_text
    return json.dumps(result)


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
