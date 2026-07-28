"""FastAPI HTTP driver — the third shell over the FEWS chat agent.

Two existing drivers front the agent's two halves: the CLI
(``runners/agent/chat_step.py``) and the Streamlit app
(``app/chatter.py``). This module is a *third* driver shell that exposes
the same two halves over HTTP/REST:

  * the **elicitation half** — one turn through the shared per-turn
    pipeline ``fews_agent.agent.turn_engine.run_turn_pipeline`` (the same
    Phases 1–5 both other drivers run), and
  * the **generation half** — the deterministic build path
    ``runners.agent.build_from_blueprint.build_from_blueprint``.

Like the other drivers it owns only its transport concerns (HTTP I/O,
session lookup, persistence, provider resolution) and delegates all
elicitation logic to ``turn_engine`` and all XML generation to the build
runner. It reimplements none of that logic.

Persistence is identical to the CLI driver: a session is a
datetime-stamped project instance
``projects/<name>/<name>_<YYYY-MM-DD_HHMMSS>/`` holding
``.chat_state.json`` / ``.chat_history.json``. The session id is the
instance directory name.

Run it with::

    uvicorn app.api.server:app --reload

The chat/turn endpoints need Ollama (qwen2.5) reachable; the build
endpoints are fully deterministic and work without it.
"""
from __future__ import annotations

import io
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, HTTPException
from rich.console import Console

# Load .env before anything reads os.environ (LLM provider/model, blob creds).
# The other two shells (Streamlit, eval) already do this; the API didn't, so
# `uvicorn app.api.server:app` came up with no backend configured. Real
# process env wins (override=False) so Azure App Settings are never clobbered.
# NOT under pytest: loading .env at import would leak PHASE/creds into the
# whole test session (tests must control their own env).
if "PYTEST_CURRENT_TEST" not in os.environ and "pytest" not in sys.modules:
    try:
        from dotenv import load_dotenv
        load_dotenv(Path(__file__).resolve().parents[2] / ".env",
                    override=False)
    except ImportError:  # python-dotenv absent → rely on real env
        pass

# --- reuse the existing agent machinery; do not reinvent it ---------------
from fews_agent.agent.project_chat import (
    build_pattern_catalog,
    initial_state,
    write_project,
)
from fews_agent.agent import module_focus, module_status
from fews_agent.agent.llm_turn import run_llm_turn
from fews_agent.agent.modules import (
    get_module,
    list_modules,
    module_for_pattern,
    normalize_module,
)
from fews_agent.agent.phases import normalize_phase, phase_plan
from fews_agent.agent.preview import preview_files
from fews_agent.agent.project_route import route_position
from fews_agent.agent.providers.factory import get_provider_or_ollama
from fews_agent.validation.xsd import validate_xsd
from fews_agent.agent.turn_engine import (
    _module_list_text,
    apply_disambiguation_answer,
    module_list_reply,
    module_vars_reply,
    module_welcome,
    resolve_patterns,
    run_module_turn,
    run_turn_pipeline,
)
from runners.agent.build_from_blueprint import build_from_blueprint, build_phase

# The generic "is the LLM reachable?" pre-flight, shared with the Streamlit
# driver. Imported into this module's namespace so tests can patch
# ``app.api.server.check_ollama_for_model`` (mirrors how the chatter tests
# patch ``chatter.check_ollama_for_model``) and run offline.
from app.chatter import check_ollama_for_model
from app import blob_store
from app import project_git

from app.api.models import (
    BuildFileResult,
    BuildRequest,
    BuildResponse,
    CreateSessionRequest,
    CreateSessionResponse,
    FileContentResponse,
    FilesResponse,
    HealthResponse,
    LegModel,
    ModulesResponse,
    ModuleStatusModel,
    PreviewFileModel,
    PreviewResponse,
    RouteResponse,
    SessionStateResponse,
    TurnRequest,
    TurnResponse,
)

# This module lives at app/api/server.py, so the repo root is two
# levels up (parents[0]=app/api, parents[1]=app, parents[2]=repo root).
REPO_ROOT = Path(__file__).resolve().parents[2]
PATTERNS_ROOT = REPO_ROOT / "fews_agent" / "patterns"
# Sessions live under the same tree the CLI driver uses, so a session
# started over HTTP is inspectable/rerunnable from the terminal and vice
# versa. Overridable in tests via monkeypatch.
OUTPUT_ROOT = REPO_ROOT / "projects"

DEFAULT_MODEL = "qwen2.5:7b-instruct"

app = FastAPI(
    title="FEWS config-generation agent API",
    description="HTTP wrapper over the FEWS chat/elicitation turn loop and "
    "the deterministic XML build path.",
    version="0.1.0",
)


# --------------------------------------------------------------------------
# Session persistence — identical layout to runners/agent/chat_step.py
# --------------------------------------------------------------------------

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
    # In the (unlikely) event two sessions land on the same second, append a
    # disambiguating suffix so we never collide with an existing session.
    if new_dir.exists():
        n = 2
        while (parent / f"{project_name}_{dt}_{n}").exists():
            n += 1
        new_dir = parent / f"{project_name}_{dt}_{n}"
    new_dir.mkdir(parents=True, exist_ok=True)
    return new_dir


def _resolve_session_dir(session_id: str) -> Path:
    """Find the instance dir for a session id, or 404.

    The id is the instance directory name; it lives two levels under
    ``OUTPUT_ROOT`` (``<project_name>/<session_id>/``). Globbing avoids
    having to parse the project name back out of the id (which may itself
    contain underscores).
    """
    if "/" in session_id or "\\" in session_id or ".." in session_id:
        raise HTTPException(status_code=400, detail="Invalid session id.")
    for cand in OUTPUT_ROOT.glob(f"*/{session_id}"):
        if cand.is_dir() and _state_path(cand).is_file():
            return cand
    # PHASE=prod: a session created before a container restart lives only in
    # blob — restore it into projects/ and carry on as local.
    if "_" in session_id:
        project = session_id.rsplit("_", 2)[0]
        pulled = blob_store.pull_session(project, session_id, OUTPUT_ROOT)
        if pulled is not None and _state_path(pulled).is_file():
            return pulled
    raise HTTPException(
        status_code=404, detail=f"No session {session_id!r}.",
    )


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
    # PHASE=prod: mirror to blob (no-op in dev; failures logged, never raised).
    blob_store.sync_session_up(project_dir)


def _catalog():
    return build_pattern_catalog(PATTERNS_ROOT)


def _model_for(state: dict) -> str:
    return state.get("model") or DEFAULT_MODEL


def _provider_name() -> str:
    """The configured LLM backend (default ollama), lower-cased."""
    return (os.environ.get("FEWS_AGENT_PROVIDER") or "ollama").lower().strip()


def _llm_preflight(model: str) -> str | None:
    """Provider-aware LLM readiness probe.

    Only Ollama exposes a local daemon we can cheaply ping. For hosted
    backends (litellm / azure / anthropic / hf) there is nothing to probe
    without spending a real call, so we skip the pre-flight and let the
    actual ``run_turn_pipeline`` call surface any failure as a 503. This
    is what makes the turn endpoint usable once ``FEWS_AGENT_PROVIDER`` is
    switched away from ollama — otherwise the Ollama probe would 503 even
    though the real backend is reachable.

    Returns an error string when unreachable, else ``None``.
    """
    if _provider_name() in ("ollama", ""):
        return check_ollama_for_model(model)
    return None


# --------------------------------------------------------------------------
# Endpoints
# --------------------------------------------------------------------------

@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    """Liveness + whether the chat LLM backend is reachable.

    The build endpoints work regardless of this; only the turn endpoint
    needs the LLM.
    """
    provider = _provider_name()
    model = os.environ.get("FEWS_AGENT_MODEL") or DEFAULT_MODEL
    err = _llm_preflight(model)
    detail = err
    if err is None and provider not in ("ollama", ""):
        # No local daemon to probe for a hosted backend; report the
        # configured provider rather than implying an Ollama check ran.
        detail = f"provider={provider}; reachability not probed (hosted backend)"
    return HealthResponse(
        status="ok",
        provider=provider,
        model=model,
        ollama_reachable=err is None,
        detail=detail,
    )


@app.post("/sessions", response_model=CreateSessionResponse, status_code=201)
def create_session(req: CreateSessionRequest) -> CreateSessionResponse:
    """Create a new chat session (a fresh project instance on disk)."""
    project_name = (req.project_name or "").strip() or (
        "api-session-" + datetime.now().strftime("%Y%m%d-%H%M%S")
    )
    # Sanitise: the name becomes a directory, so keep it filesystem-safe.
    safe = "".join(
        c if (c.isalnum() or c in "-_.") else "-" for c in project_name
    )
    project_dir = _new_session_dir(safe)
    (project_dir / "inputs").mkdir(exist_ok=True)

    state = initial_state(safe)
    state.setdefault("intent", None)
    state.setdefault("slots", {})
    state["model"] = (req.model or DEFAULT_MODEL)
    _save(project_dir, state, [])

    return CreateSessionResponse(
        session_id=project_dir.name,
        project_name=safe,
        project_dir=str(project_dir),
        model=state["model"],
    )


@app.get("/sessions/{session_id}", response_model=SessionStateResponse)
def get_session(session_id: str) -> SessionStateResponse:
    """Return the resolved intermediate variables (slots + patterns)."""
    project_dir = _resolve_session_dir(session_id)
    state, _ = _load(project_dir)
    return SessionStateResponse(
        session_id=session_id,
        project_name=state.get("name", session_id),
        intent=state.get("intent"),
        slots=state.get("slots", {}) or {},
        patterns=state.get("patterns", []) or [],
        warnings=state.get("warnings", []) or [],
        built_phases=state.get("built_phases", []) or [],
    )


def _module_command(state: dict, message: str, catalog) -> str | None:
    """Deterministic module-mode commands (no LLM): /modules, /module[ <name>],
    /list. Returns the reply text, or None if the message isn't one of them.

    Mirrors the CLI/Streamlit command set so an HTTP client drives module-mode
    with the same verbs. Kept here (transport concern) but every reply comes
    from the shared ``module_focus`` / ``_module_list_text`` helpers.
    """
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
        _parts = message.strip().split(None, 1)
        _target = _parts[1].strip() if len(_parts) > 1 else None
        return module_vars_reply(state, catalog, _target)
    return None


@app.post("/sessions/{session_id}/turn", response_model=TurnResponse)
def run_turn(session_id: str, req: TurnRequest) -> TurnResponse:
    """Run one turn — the LLM-first single-call architecture (see PLAN.md).

    Deterministic module commands (/vars, /module, ...) bypass the LLM; any
    other message is ONE model call: Python assembles the grounding digests,
    the model returns a reply + a slot PATCH, ``patch_ops`` validates and
    applies it. No intent classification, no module gating — the focused
    module is advisory context only.

    Returns 503 (not 500) when the LLM backend is unreachable, so a client
    gets an actionable message rather than a crash.
    """
    project_dir = _resolve_session_dir(session_id)
    state, history = _load(project_dir)
    catalog = _catalog()
    model = _model_for(state)

    message = req.message
    history.append({"role": "user", "message": message})

    # Deterministic module-mode commands run without the LLM.
    cmd_reply = _module_command(state, message, catalog)
    if cmd_reply is not None:
        history.append({"role": "agent", "message": cmd_reply})
        _save(project_dir, state, history)
        return TurnResponse(
            reply=cmd_reply, short_circuit=False, intent=state.get("intent"),
            patterns=state.get("patterns", []) or [],
            slots=state.get("slots", {}) or {},
            module_mode=True, current_module=state.get("current_module"),
        )

    # Pre-flight the LLM so an unreachable backend fails loudly + actionably
    # here rather than 500-ing deep in the engine. Patched to None in tests.
    llm_err = _llm_preflight(model)
    if llm_err:
        _save(project_dir, state, history)
        raise HTTPException(status_code=503, detail=llm_err)

    provider = get_provider_or_ollama(model)

    res = run_llm_turn(
        state, message, catalog, provider=provider,
        history=history, inputs_dir=project_dir / "inputs",
    )

    reply = res.reply
    if res.wants_build or res.wants_assemble:
        reply += (
            f"\n\n(To run the build over HTTP: POST "
            f"/sessions/{session_id}/build"
            + (" with {\"phase\": \"...\"} for a scoped build" if
               res.wants_build and not res.wants_assemble else "")
            + ".)"
        )
    history.append({"role": "agent", "message": reply})
    _save(project_dir, state, history)
    return TurnResponse(
        reply=reply, short_circuit=False, intent=state.get("intent"),
        patterns=state.get("patterns", []) or [],
        slots=state.get("slots", {}) or {},
        new_patterns=res.new_patterns,
        module_mode=True, current_module=state.get("current_module"),
        wants_build=res.wants_build or res.wants_assemble,
        confirmation=res.confirmation,
    )


def _files_from_summary(summary: dict) -> list[BuildFileResult]:
    return [
        BuildFileResult(
            path=f.get("path", ""),
            xsd_ok=bool(f.get("xsd_ok")),
            xsd_msg=f.get("xsd_msg"),
            byte_equivalent=f.get("byte_equivalent"),
        )
        for f in summary.get("files", [])
    ]


def _merge_summaries(summaries: list[dict]) -> dict:
    """Aggregate several per-phase build summaries into one (module scope)."""
    merged: dict = {
        "ok": all(s.get("ok") for s in summaries) if summaries else True,
        "files_total": 0, "files_xml": 0, "files_non_xml": 0,
        "files_xsd_ok": 0, "errors": [], "files": [],
    }
    for s in summaries:
        merged["files_total"] += s.get("files_total", 0)
        merged["files_xml"] += s.get("files_xml", 0)
        merged["files_non_xml"] += s.get("files_non_xml", 0)
        merged["files_xsd_ok"] += s.get("files_xsd_ok", 0)
        merged["errors"].extend(s.get("errors") or [])
        merged["files"].extend(s.get("files") or [])
    return merged


def _module_target_phases(state: dict, module) -> list[str]:
    """The capability phases a focused folder-module owns that have resolved
    content — the same mapping the CLI's ``_run_module_scope_build`` uses."""
    plan = phase_plan(state.get("patterns") or [])
    return [
        e["phase"] for e in plan
        if e["patterns"]
        and module_for_pattern(e["patterns"][0]["pattern"]) == module.key
    ]


@app.post("/sessions/{session_id}/build", response_model=BuildResponse)
def build_session(session_id: str, req: BuildRequest | None = None) -> BuildResponse:
    """Build the project — full assembly (default) or a scoped phase/module.

    Full (no ``phase``/``module``): write project.yaml (the ``done`` path) and
    run the whole deterministic pipeline (singletons + bundled standards +
    derivers + cross-file check). Scoped: render + XSD-validate ONLY one
    capability phase (``phase``) or every phase a FEWS-folder module owns
    (``module``) — the mid-elicitation build the CLI/Streamlit shells run on
    ``/build``, now over HTTP. Scoped builds skip the whole-project stages and
    ignore ``force`` (they're meant to run before the project is complete).

    Fully deterministic — needs no LLM. The filter drafter falls back to a
    bundled standard when Ollama is unreachable.
    """
    req = req or BuildRequest()
    if req.phase and req.module:
        raise HTTPException(
            status_code=400,
            detail="Pass at most one of `phase` / `module` — they're "
            "mutually exclusive scoped-build selectors.",
        )
    project_dir = _resolve_session_dir(session_id)
    state, history = _load(project_dir)
    catalog = _catalog()

    # Resolve patterns from the current slots, then write project.yaml. Guard
    # against an empty project so we don't shell a build with nothing to emit.
    resolve_patterns(state, catalog)
    if not state.get("patterns"):
        raise HTTPException(
            status_code=409,
            detail="No patterns resolved yet — run at least one turn that "
            "describes what to build before building.",
        )

    # Resolve the scoped selector to a concrete list of phases to build.
    scope = "full"
    target_phases: list[str] = []
    if req.phase is not None:
        phase = normalize_phase(req.phase)
        if phase is None:
            raise HTTPException(
                status_code=400,
                detail=f"Unknown phase {req.phase!r}. Valid phases: "
                "imports, process, model, visualize.",
            )
        scope, target_phases = f"phase:{phase}", [phase]
    elif req.module is not None:
        mod_key = normalize_module(req.module)
        module = get_module(mod_key) if mod_key else None
        if module is None:
            raise HTTPException(
                status_code=400, detail=f"Unknown module {req.module!r}.",
            )
        if not module.phases:
            raise HTTPException(
                status_code=409,
                detail=f"The '{module.label}' module isn't built on its own — "
                "it comes from inputs or final assembly. Build the full "
                "project (omit `phase`/`module`) to include it.",
            )
        target_phases = _module_target_phases(state, module)
        if not target_phases:
            raise HTTPException(
                status_code=409,
                detail=f"Nothing resolved for the '{module.label}' module yet "
                "— add something (e.g. an import) before building it.",
            )
        scope = f"module:{mod_key}"
    else:
        # Full assembly honours the warnings gate (scoped builds don't).
        warnings = list(state.get("warnings") or [])
        if warnings and not req.force:
            raise HTTPException(
                status_code=409,
                detail={
                    "message": f"{len(warnings)} unresolved warning(s); pass "
                    "force=true to build anyway.",
                    "warnings": warnings,
                },
            )

    project_path = write_project(state, project_dir)
    _save(project_dir, state, history)

    inputs_dir = project_dir / "inputs"
    silent = Console(file=io.StringIO(), force_terminal=False)
    try:
        if target_phases:
            summaries = [
                build_phase(
                    blueprint_path=Path(project_path),
                    pattern_root=PATTERNS_ROOT, phase=ph, console=silent,
                )
                for ph in target_phases
            ]
            summary = _merge_summaries(summaries)
        else:
            summary = build_from_blueprint(
                blueprint_path=Path(project_path),
                pattern_root=PATTERNS_ROOT,
                inputs_dir=inputs_dir if inputs_dir.is_dir() else None,
                console=silent,
            )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=500,
            detail=f"Build failed ({type(exc).__name__}: {exc}).",
        ) from exc

    # Persist build awareness into state — without this the next llm turn's
    # build/gap digests were amnesiac about an HTTP build (and the app sidebar
    # stayed grey when the session was resumed there).
    if isinstance(summary, dict):
        state["last_build_summary"] = summary
        if summary.get("ok"):
            if target_phases:
                built = state.setdefault("built_phases", [])
                for ph in target_phases:
                    if ph not in built:
                        built.append(ph)
                # Fingerprint stamping parity with the Streamlit shell (see
                # chatter.py's scoped-build call sites) — without this, an
                # API-driven build never marks module_fingerprints and
                # GET /modules' "stale" detection never fires for it.
                for entry in phase_plan(state.get("patterns") or []):
                    if entry["phase"] in target_phases and entry.get("patterns"):
                        module_status.stamp_module_fingerprint(
                            state, catalog,
                            module_for_pattern(entry["patterns"][0]["pattern"]),
                        )
            else:
                state["full_build_ok"] = True
                for m in list_modules():
                    module_status.stamp_module_fingerprint(state, catalog, m.key)
        _save(project_dir, state, history)
        project_git.commit_and_diff(project_dir, f"api build {scope}")
        blob_store.sync_session_up(project_dir, full=True)

    return BuildResponse(
        ok=bool(summary.get("ok")),
        scope=scope,
        built_phases=target_phases,
        blueprint=summary.get("blueprint"),
        project_yaml=str(project_path),
        output_root=summary.get("output_root"),
        files_total=summary.get("files_total", 0),
        files_xml=summary.get("files_xml", 0),
        files_non_xml=summary.get("files_non_xml", 0),
        files_xsd_ok=summary.get("files_xsd_ok", 0),
        errors=list(summary.get("errors") or []),
        unbacked_interpolation_sets=list(
            summary.get("unbacked_interpolation_sets") or []
        ),
        files=_files_from_summary(summary),
    )


# --------------------------------------------------------------------------
# Generated files — read-only browsing/diffing (e.g. for an IDE extension).
#
# Container-authoritative by design: a client never assumes it shares a
# filesystem with the running agent (local uvicorn, or the Azure VM behind
# an SSH tunnel — see DEPLOY.md). The per-session git repo in project_git.py
# stays entirely server-side; these endpoints expose just enough of it
# (current content + a named historical revision) for a client to render a
# file tree and a native diff view without ever touching git themselves.
# --------------------------------------------------------------------------

_REV_PATTERN = re.compile(r"HEAD(~\d+)?|[0-9a-f]{7,40}")


@app.get("/sessions/{session_id}/files", response_model=FilesResponse)
def list_files(session_id: str) -> FilesResponse:
    """The generated-file manifest — everything actually on disk under
    ``generated/`` right now, freshly XSD-validated per file.

    Deliberately NOT sourced from ``generated/summary.json`` (only written
    by full-project assembly) or ``state["last_build_summary"]`` (only the
    MOST RECENT build's file set — a scoped phase/module build would make
    an earlier phase's files vanish from that view even though they're
    still on disk). Walking disk + validating live is the same "computed
    fresh, never stale" convention ``preview.py`` already uses, and it's
    the only source that stays correct across any mix of full/scoped
    builds. ``built=False`` (empty ``files``) before the first build.
    """
    project_dir = _resolve_session_dir(session_id)
    generated = project_dir / "generated"
    if not generated.is_dir():
        return FilesResponse(built=False, files=[])
    files: list[BuildFileResult] = []
    for p in sorted(generated.rglob("*")):
        if not p.is_file() or p.name == "summary.json":
            continue
        rel = p.relative_to(generated).as_posix()
        if rel.lower().endswith(".xml"):
            xsd_ok, xsd_msg = validate_xsd(p.read_bytes())
        else:
            # Non-XML outputs (sa_global.Properties, ...) — XSD doesn't
            # apply. Same convention as build_from_blueprint's file table.
            xsd_ok, xsd_msg = True, "(not XML)"
        files.append(BuildFileResult(path=rel, xsd_ok=bool(xsd_ok), xsd_msg=xsd_msg))
    return FilesResponse(built=bool(files), files=files)


@app.get(
    "/sessions/{session_id}/files/{file_path:path}",
    response_model=FileContentResponse,
)
def get_file(
    session_id: str, file_path: str, rev: str | None = None,
) -> FileContentResponse:
    """One generated file's content — current, or (via ``?rev=``) a prior
    revision from the session's own git history.

    ``rev`` accepts ``prev`` (alias for the revision before the most recent
    build — i.e. "before the last build", the natural diff baseline),
    ``HEAD``/``HEAD~<n>``, or an explicit commit sha. Anything else is a 400,
    not a silent empty diff.
    """
    project_dir = _resolve_session_dir(session_id)
    generated = (project_dir / "generated").resolve()
    target = (generated / file_path).resolve()
    if not target.is_relative_to(generated):
        raise HTTPException(status_code=400, detail="Invalid path.")

    if rev is None:
        if not target.is_file():
            raise HTTPException(
                status_code=404,
                detail=f"No such generated file: {file_path!r}.",
            )
        content = target.read_text(encoding="utf-8", errors="replace")
        return FileContentResponse(
            relpath=file_path, content=content, source="generated",
        )

    resolved_rev = "HEAD~1" if rev == "prev" else rev
    if not _REV_PATTERN.fullmatch(resolved_rev):
        raise HTTPException(
            status_code=400, detail=f"Unrecognised rev {rev!r}.",
        )
    blob = project_git.read_blob(
        project_dir, f"generated/{file_path}", resolved_rev,
    )
    if blob is None:
        raise HTTPException(
            status_code=404,
            detail=f"No revision {rev!r} of {file_path!r}.",
        )
    return FileContentResponse(
        relpath=file_path, content=blob, source=f"rev:{resolved_rev}",
    )


# --------------------------------------------------------------------------
# Route (the "GPS" journey stepper) + module status (green/amber/grey)
# --------------------------------------------------------------------------

@app.get("/sessions/{session_id}/route", response_model=RouteResponse)
def get_route(session_id: str) -> RouteResponse:
    """Where the project stands on the route to a complete config.

    Pure, state-only (no LLM) — mirrors ``project_route.route_position``,
    the same model the elicitation prompt's ROUTE section is built from.
    """
    project_dir = _resolve_session_dir(session_id)
    state, _ = _load(project_dir)
    pos = route_position(state, project_dir / "inputs")
    legs = [
        LegModel(
            id=lg.id, title=lg.title, kind=lg.kind, active=lg.active,
            done=lg.done, guidance=lg.guidance, detail=lg.detail,
        )
        for lg in pos.legs
    ]
    return RouteResponse(
        legs=legs,
        current=(pos.current.id if pos.current else None),
        blocking_open=[lg.id for lg in pos.blocking_open],
        advisory_open=[lg.id for lg in pos.advisory_open],
        ready_to_assemble=pos.ready_to_assemble,
        assembled=pos.assembled,
    )


@app.get("/sessions/{session_id}/modules", response_model=ModulesResponse)
def get_modules(session_id: str) -> ModulesResponse:
    """Per-FEWS-module build status — the green/amber/grey sidebar signal.

    Mirrors the Streamlit sidebar navigator (``ChatSession.module_statuses``,
    now shared via ``fews_agent.agent.module_status``). Resolves patterns
    from current slots as a side effect (same as the Streamlit call site),
    so the result is persisted back to state.
    """
    project_dir = _resolve_session_dir(session_id)
    state, history = _load(project_dir)
    catalog = _catalog()
    statuses = module_status.module_statuses(state, catalog)
    _save(project_dir, state, history)
    return ModulesResponse(
        modules=[ModuleStatusModel(**s) for s in statuses],
    )


# --------------------------------------------------------------------------
# Preview — live, pre-build render of one pattern instance's files
# --------------------------------------------------------------------------

@app.get("/sessions/{session_id}/preview", response_model=PreviewResponse)
def get_preview(session_id: str, target: str) -> PreviewResponse:
    """Live-render the files matching ``target`` (an instance label like
    "GFS", or a filename fragment like "ImportGFS"/"Topology.xml").

    Distinct from ``/files``: this is a transient, explicitly-labeled render
    ("live render" vs "last build", per ``PreviewFile.source``) for files a
    pattern instance produces NOW from current slots — not what's actually
    on disk in the container. Never mixed into the ``/files`` manifest.
    """
    project_dir = _resolve_session_dir(session_id)
    state, _ = _load(project_dir)
    previews = preview_files(
        state, target, output_root=project_dir / "generated",
    )
    return PreviewResponse(
        target=target,
        files=[
            PreviewFileModel(
                relpath=p.relpath, content=p.content, xsd_ok=p.xsd_ok,
                source=p.source, label=p.label,
            )
            for p in previews
        ],
    )
