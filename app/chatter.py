"""Reusable chat-session wrapper for the Streamlit demo app.

Wraps the single-turn driver in ``runners/agent/chat_step.py`` as a
``ChatSession`` class:

  * one ``send(message)`` call per turn
  * state + history persisted to disk on every turn:
    ``.chat_state.json``, ``.chat_history.json``,
    ``_conversation.md`` (full markdown transcript), ``_app.log``
    (structured turn events via Python logging)
  * artifacts live in a session folder
    ``sessions/<username>_<YYYY-MM-DD_HHMMSS>/`` — one folder per chat
    session, scoped to the user who started it

When ``done`` is sent and the project is ready, ``project.yaml`` is
written to the same session folder (alongside the conversation).
Resuming an existing session picks up its prior history; the
``project_name`` is loaded from the persisted state.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from fews_agent.agent.project_chat import (
    apply_removal,
    build_pattern_catalog,
    initial_state,
    write_project,
)
from fews_agent.agent.project_intents import (
    INTENTS,
    build_status_report,
    compose_help_reply,
    compose_status_reply,
    compute_input_status,
    detect_coordinates_request,
    detect_help_query,
    detect_status_query,
    is_intent_ready,
    next_unfilled_question,
    scan_inputs,
    status_prose_fallback,
)
from fews_agent.agent.phases import (
    PHASE_ORDER,
    next_unbuilt_phase,
    normalize_phase,
    phase_plan,
)
from fews_agent.agent.providers.factory import get_provider
from runners.agent.build_from_blueprint import build_from_blueprint
from fews_agent.agent.turn_engine import (
    _format_internals,
    _module_list_text,
    apply_disambiguation_answer,
    apply_edit_action,
    module_edit_reply,
    module_list_reply,
    module_vars_reply,
    module_welcome,
    resolve_patterns,
    run_module_turn,
    run_turn_pipeline,
)
from fews_agent.agent import module_focus
from app import blob_store
from fews_agent.agent.llm_turn import run_llm_turn
from fews_agent.agent.modules import module_for_pattern
from fews_agent.agent.project_chat import set_grid_geometry


_BUNDLED_CELL_SIZES: dict[str, float] | None = None


def _bundled_grid_cell_size(name: str) -> float | None:
    """xCellSize (deg) for ``name`` from the bundled standard gridsFile, or
    None (unknown / projected grid). Cached; case-insensitive on locationId."""
    global _BUNDLED_CELL_SIZES
    if _BUNDLED_CELL_SIZES is None:
        _BUNDLED_CELL_SIZES = {}
        try:
            import yaml
            from runners.agent.build_from_blueprint import STANDARD_INPUTS_DIR
            data = yaml.safe_load(
                (STANDARD_INPUTS_DIR / "gridsFile.yaml").read_text(
                    encoding="utf-8"
                )
            )
            for entry in (data or {}).get("body") or []:
                reg = entry.get("regular") if isinstance(entry, dict) else None
                if not isinstance(reg, dict):
                    continue
                loc = reg.get("@locationId")
                cs = reg.get("xCellSize")
                if isinstance(loc, str) and cs is not None:
                    try:
                        _BUNDLED_CELL_SIZES[loc.lower()] = float(cs)
                    except (TypeError, ValueError):
                        pass
        except Exception:  # noqa: BLE001 — a missing/odd bundle just means no default
            _BUNDLED_CELL_SIZES = {}
    return _BUNDLED_CELL_SIZES.get(str(name).lower())
from runners.agent.chat_step import (
    _parse_slash_edit,
    _phase_plan_text,
    _resolve_module_target,
)


def _current_provider_name() -> str:
    """Resolve FEWS_AGENT_PROVIDER once, with the same defaulting/aliasing
    rules as ``providers.factory.get_provider``. Used to skip
    Ollama-specific pre-flight checks when the deployed app is running
    against a cloud provider (Azure OpenAI)."""
    import os

    name = (os.environ.get("FEWS_AGENT_PROVIDER") or "ollama").lower().strip()
    if name in {"azure_openai", "azure-openai", "azureopenai"}:
        name = "azure"
    return name

REPO_ROOT = Path(__file__).resolve().parents[1]
PATTERNS_ROOT = REPO_ROOT / "fews_agent" / "patterns"
OUTPUT_ROOT = REPO_ROOT / "projects"
# --- projects/ store (the app's project picker; shared layout with the CLI) --
#
# A *project* is a folder ``projects/<name>/`` holding one or more
# datetime-stamped chat sessions ``<name>_<YYYY-MM-DD_HHMMSS>/`` — the same
# layout ``runners/agent/chat_step.py`` and ``app/api/server.py`` use, so a
# project started in any shell is listable/resumable in the app.

def safe_project_name(name: str) -> str:
    """Filesystem-safe project name (the folder + instance-name stem)."""
    cleaned = "".join(
        c if (c.isalnum() or c in "-_.") else "-" for c in str(name).strip()
    )
    return cleaned or "project"


def list_projects(root: Path = OUTPUT_ROOT) -> list[str]:
    """Project names under ``projects/`` that hold at least one chat session,
    most-recently-active first (so the picker shows resumable work, not the
    build-only regression fixtures that carry no ``.chat_state.json``)."""
    if not root.is_dir():
        return []
    entries: list[tuple[float, str]] = []
    for d in root.iterdir():
        if not d.is_dir():
            continue
        instances = [
            i for i in d.iterdir()
            if i.is_dir() and i.name.startswith(f"{d.name}_")
            and (i / ".chat_state.json").is_file()
        ]
        if instances:
            entries.append((max(i.stat().st_mtime for i in instances), d.name))
    local = [name for _, name in sorted(entries, reverse=True)]
    # PHASE=prod: projects that only exist in blob (fresh container disk)
    # appear too — picking one pulls it down in latest_project_session_dir.
    for name in blob_store.list_remote_projects():
        if name not in local:
            local.append(name)
    return local


def latest_project_session_dir(
    name: str, root: Path = OUTPUT_ROOT,
) -> Path | None:
    """The newest chat-session instance for a project, or None if it has none.

    PHASE=prod: when the project isn't on local disk (fresh container after a
    restart/redeploy) the newest session is RESTORED from blob into projects/
    first, then returned — resuming feels identical to dev."""
    parent = root / name
    instances = sorted(
        i for i in parent.iterdir()
        if i.is_dir() and i.name.startswith(f"{name}_")
    ) if parent.is_dir() else []
    if instances:
        return instances[-1]
    remote_id = blob_store.latest_remote_session_id(name)
    if remote_id:
        return blob_store.pull_session(name, remote_id, root)
    return None


def new_project_session_dir(name: str, root: Path = OUTPUT_ROOT) -> Path:
    """Mint a fresh ``projects/<name>/<name>_<YYYY-MM-DD_HHMMSS>/`` instance."""
    safe = safe_project_name(name)
    parent = root / safe
    parent.mkdir(parents=True, exist_ok=True)
    dt = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    out = parent / f"{safe}_{dt}"
    if out.exists():  # two clicks in the same second
        n = 2
        while (parent / f"{safe}_{dt}_{n}").exists():
            n += 1
        out = parent / f"{safe}_{dt}_{n}"
    out.mkdir(parents=True, exist_ok=True)
    return out


def _ollama_model_names(raw: object) -> list[str]:
    """Best-effort extraction of model names from an ``ollama.list()`` response.

    Tolerates the dict-shape returned by older ollama SDKs and the
    pydantic-style ``ListResponse(models=[Model(name=...), ...])`` returned
    by newer ones.
    """
    items = raw.get("models") if isinstance(raw, dict) else getattr(raw, "models", [])
    names: list[str] = []
    for m in items or []:
        if isinstance(m, dict):
            n = m.get("name") or m.get("model")
        else:
            n = getattr(m, "name", None) or getattr(m, "model", None)
        if n:
            names.append(str(n))
    return names


def list_ollama_models() -> list[str]:
    """Return locally-installed Ollama model names, or ``[]`` if unreachable."""
    try:
        import ollama
        return _ollama_model_names(ollama.Client().list())
    except Exception:  # noqa: BLE001
        return []


def check_ollama_for_model(model: str) -> str | None:
    """Pre-flight check before invoking the LLM.

    When ``FEWS_AGENT_PROVIDER`` selects a non-Ollama backend, delegate
    to that provider's own readiness check (env-var presence for
    Azure). The function name kept for call-site stability — it's the
    generic "is the LLM reachable?" pre-flight regardless of provider.

    Returns ``None`` if the LLM is ready, otherwise a human-readable
    error string suitable for showing in the chat UI.
    """
    provider_name = _current_provider_name()
    if provider_name == "azure":
        return _check_azure_openai_ready()
    if provider_name != "ollama":
        # Anthropic etc. — assume the API client will surface its own
        # error on first call. We don't pre-flight those.
        return None

    try:
        import ollama
        raw = ollama.Client().list()
    except Exception as exc:  # noqa: BLE001
        return (
            f"Cannot reach Ollama at http://localhost:11434 "
            f"({type(exc).__name__}: {exc}).\n\n"
            f"Start it with `ollama serve`, then refresh."
        )
    names = _ollama_model_names(raw)
    if not names:
        return (
            "Ollama is reachable but no models are installed.\n\n"
            "Pull one first, e.g.:  `ollama pull qwen2.5:7b-instruct`"
        )
    if model not in names:
        return (
            f"Model `{model}` is not available locally.\n\n"
            f"Installed models: {', '.join(names)}.\n\n"
            f"Either pick one of those in the sidebar, or pull this one with "
            f"`ollama pull {model}`."
        )
    return None


def _check_azure_openai_ready() -> str | None:
    """Verify the AZURE_OPENAI_* env vars needed by AzureOpenAIProvider
    are present. Doesn't make a network call — those happen on first
    chat turn — but catches the common "forgot to set the key"
    misconfig before the user types anything."""
    import os

    missing: list[str] = []
    if not os.environ.get("AZURE_OPENAI_ENDPOINT"):
        missing.append("AZURE_OPENAI_ENDPOINT")
    if not os.environ.get("AZURE_OPENAI_API_KEY"):
        missing.append("AZURE_OPENAI_API_KEY")
    if missing:
        return (
            "Azure OpenAI is selected (FEWS_AGENT_PROVIDER=azure) but "
            "required environment variables are missing: "
            + ", ".join(missing)
            + ".\n\nSet them in your environment (or `.env`) and restart."
        )
    return None


@dataclass
class TurnResult:
    """Outcome of one ``ChatSession.send`` call.

    ``kind`` is one of:
      ``reply``   — normal agent reply
      ``done``    — project.yaml written
      ``refused`` — done refused (warnings present, or required slots unfilled)
      ``edit``    — message handled by edit-mode
      ``pending`` — confirm/cancel of a pending-removal proposal
      ``coordinates`` — open the grid-coordinates subwindow (see
                        ``coordinates_request``)
      ``error``   — exception during turn processing
    """
    agent_message: str
    kind: str = "reply"
    # The mechanical "what changed" fact (e.g. "Applied: imports=['GFS']"),
    # rendered MUTED (grey) above the main reply so the LLM's guidance is the
    # main voice. Empty for non-edit turns.
    confirmation: str = ""
    internals: str | None = None
    warnings: list[str] = field(default_factory=list)
    ready: bool = False
    next_question: str | None = None
    new_patterns: list[str] = field(default_factory=list)
    project_yaml_path: Path | None = None
    # Populated when kind=="coordinates": the eligible NWP grid imports the
    # subwindow lets the user set a firstCellCenter + rows/columns for. Each
    # is {"name": str, "geometry": {...} | None} (None = not yet set).
    coordinates_request: list[dict] | None = None
    # Populated after kind=="done": the summary dict returned by
    # build_from_blueprint() — see runners/agent/build_from_blueprint.py
    # for the schema. None when /done refused or when the build failed
    # to even start (in which case ``build_error`` describes why).
    validation_summary: dict | None = None
    build_error: str | None = None


class ChatSession:
    """One configurator-driven chat session, persisted on disk."""

    def __init__(
        self,
        project_name: str,
        model: str = "qwen2.5:7b-instruct",
        session_dir: Path | None = None,
        username: str | None = None,
    ) -> None:
        self.project_name = project_name
        self.model = model
        if session_dir is None:
            raise ValueError(
                "session_dir is required — sessions live in the shared "
                "projects/ store (new_project_session_dir / "
                "latest_project_session_dir)."
            )
        self.session_dir = session_dir
        self.state, self.history = self._load_state()
        # If resuming, prefer the project_name persisted in state.
        if self.state.get("name"):
            self.project_name = self.state["name"]
        # Persist the model into state so the chat_state.json records
        # which model is currently driving the session. Updates on each
        # construction so switching models mid-resume is reflected.
        self.state["model"] = self.model
        self.catalog = build_pattern_catalog(PATTERNS_ROOT)
        self._logger = self._make_logger()
        self._logger.info(
            "session_open project=%s dir=%s model=%s prior_turns=%d",
            self.project_name, self.session_dir, self.model, self._turn_count(),
        )

    # ---- paths / persistence -------------------------------------------------

    def _state_path(self) -> Path:
        return self.session_dir / ".chat_state.json"

    def _history_path(self) -> Path:
        return self.session_dir / ".chat_history.json"

    def _log_md_path(self) -> Path:
        return self.session_dir / "_conversation.md"

    def _log_app_path(self) -> Path:
        return self.session_dir / "_app.log"

    def _turn_count(self) -> int:
        return len([h for h in self.history if h["role"] == "user"])

    def _load_state(self) -> tuple[dict, list]:
        sp, hp = self._state_path(), self._history_path()
        if sp.is_file() and hp.is_file():
            return (
                json.loads(sp.read_text(encoding="utf-8")),
                json.loads(hp.read_text(encoding="utf-8")),
            )
        s = initial_state(self.project_name)
        s.setdefault("intent", None)
        s.setdefault("slots", {})
        return s, []

    def _save(self) -> None:
        self.session_dir.mkdir(parents=True, exist_ok=True)
        self._state_path().write_text(
            json.dumps(self.state, indent=2, default=str), encoding="utf-8"
        )
        self._history_path().write_text(
            json.dumps(self.history, indent=2, default=str), encoding="utf-8"
        )
        # PHASE=prod: mirror the per-turn core files to blob (no-op in dev;
        # failures are logged by the store and never break a turn).
        blob_store.sync_session_up(self.session_dir)

    def _make_logger(self) -> logging.Logger:
        # Unique logger per session_dir so re-opening doesn't double-handle.
        name = f"fews_agent.chatter.{self.session_dir.name}"
        logger = logging.getLogger(name)
        if not logger.handlers:
            self.session_dir.mkdir(parents=True, exist_ok=True)
            handler = logging.FileHandler(self._log_app_path(), encoding="utf-8")
            handler.setFormatter(logging.Formatter(
                "%(asctime)s %(levelname)s %(message)s"
            ))
            logger.addHandler(handler)
            logger.setLevel(logging.INFO)
            logger.propagate = False
        return logger

    def _append_md(
        self,
        turn: int,
        role: str,
        message: str,
        note: str | None = None,
        internals: str | None = None,
    ) -> None:
        log = self._log_md_path()
        if not log.is_file():
            log.write_text(
                f"# Conversation: {self.session_dir.name}\n"
                f"Project: {self.project_name}\n"
                f"Model: {self.model}\n"
                f"Created: {datetime.now().isoformat(timespec='seconds')}\n\n",
                encoding="utf-8",
            )
        block = [f"## Turn {turn} ({role})"]
        if note:
            block.append(f"_{note}_")
        block.append("")
        block.append(message)
        block.append("")
        if internals:
            block.append("<details><summary>Engine internals</summary>")
            block.append("")
            block.append(internals)
            block.append("</details>")
            block.append("")
        with log.open("a", encoding="utf-8") as fh:
            fh.write("\n".join(block) + "\n")

    def _resolve_patterns(self) -> None:
        """Thin wrapper over the shared resolver (kept for in-class callers)."""
        resolve_patterns(self.state, self.catalog)

    # ---- build pipeline ------------------------------------------------------

    def _run_build(
        self, project_yaml_path: Path,
    ) -> tuple[dict | None, str | None]:
        """Run ``build_from_blueprint`` and return ``(summary, error)``.

        Streamlit captures stdout for the chat bubble, so we route the
        builder's Rich Console at an in-memory file to keep its
        progress noise out of the UI. The returned dict mirrors the
        schema documented at ``build_from_blueprint``'s return.

        On exception (template bug, missing pattern, etc.) we return
        ``(None, traceback-tail)`` so the UI can surface a graceful
        failure without losing the (already-written) project.yaml.
        """
        import io
        import traceback
        from rich.console import Console

        inputs_dir = self.session_dir / "inputs"
        try:
            silent_console = Console(file=io.StringIO(), force_terminal=False)
            summary = build_from_blueprint(
                blueprint_path=project_yaml_path,
                pattern_root=PATTERNS_ROOT,
                inputs_dir=inputs_dir if inputs_dir.is_dir() else None,
                console=silent_console,
            )
            if isinstance(summary, dict):
                # Grounds the next llm turn (build_digest) + turns the
                # deriver modules green in the sidebar when assembly is ok.
                self.state["last_build_summary"] = summary
                if summary.get("ok"):
                    self.state["full_build_ok"] = True
            blob_store.sync_session_up(self.session_dir, full=True)
            return summary, None
        except Exception as exc:  # noqa: BLE001
            self._logger.exception("build_from_blueprint crashed: %s", exc)
            tb = traceback.format_exc()
            # Keep the tail — full tracebacks are huge in the UI.
            tail = "\n".join(tb.splitlines()[-12:])
            return None, f"{type(exc).__name__}: {exc}\n\n{tail}"

    # ---- stepwise partial builds (one phase / one module) --------------------

    def _run_partial_build(self, fn):
        """Run a phase/module build callable with a silent console.

        Mirrors ``_run_build``'s error handling — returns ``(summary,
        error)`` so a build crash surfaces gracefully in the UI instead
        of losing the (already-written) project.yaml.
        """
        import io
        import traceback
        from rich.console import Console

        try:
            console = Console(file=io.StringIO(), force_terminal=False)
            summary = fn(console)
            # Ground the NEXT llm turn: the model reads this via build_digest
            # so "why did that file fail?" gets an answered, not a guess.
            if isinstance(summary, dict):
                self.state["last_build_summary"] = summary
            return summary, None
        except Exception as exc:  # noqa: BLE001
            self._logger.exception("partial build crashed: %s", exc)
            tail = "\n".join(traceback.format_exc().splitlines()[-12:])
            return None, f"{type(exc).__name__}: {exc}\n\n{tail}"

    def _build_summary_line(self, summary: dict | None, label: str,
                            error: str | None = None) -> str:
        if error or summary is None:
            return f"{label} build crashed before validation — see error below."
        n_total = summary.get("files_total", 0)
        n_xml = summary.get(
            "files_xml", n_total - summary.get("files_non_xml", 0)
        )
        n_xsd = summary.get("files_xsd_ok", 0)
        if summary.get("ok"):
            return f"{label} built: {n_total} file(s), {n_xsd}/{n_xml} XSD-valid."
        n_err = len(summary.get("errors") or [])
        return (
            f"{label} built with issues — {n_xsd}/{n_xml} XSD-valid"
            + (f", {n_err} error(s)" if n_err else "")
            + ". See the validation panel below."
        )

    def _build_note(self, turn: int, msg: str) -> TurnResult:
        """A plain text reply for a build that couldn't start (no panel)."""
        self.history.append({"role": "agent", "message": msg})
        self._append_md(turn, "agent", msg, note="build")
        self._save()
        return TurnResult(agent_message=msg, kind="reply")

    def _handle_build(self, message: str, cmd: str, turn: int) -> TurnResult:
        """Route ``/build`` to the next unbuilt phase, a named phase, or a
        single module (``/build GFS``). Mirrors chat_step.py::main."""
        if cmd == "/build":
            # Module-mode: a bare /build with a module in focus builds THAT
            # module (its capability phases), not the next unbuilt phase.
            focus = module_focus.get_focus(self.state)
            if focus is not None:
                return self._app_module_scope_build(focus, turn)
            self._resolve_patterns()
            phase = next_unbuilt_phase(
                self.state.get("patterns") or [], self.state.get("built_phases"),
            )
            if phase is None:
                return self._build_note(
                    turn,
                    "No unbuilt phases — every resolved module is built. "
                    "Type 'done' to assemble the full project.",
                )
            return self._app_phase_build(phase, turn)

        token = message.strip().split(None, 1)[1].strip()
        phase = normalize_phase(token)
        if phase is None:
            # Not a phase name. A bare "/build <token>" treats the token as a
            # single module (e.g. /build GFS); the explicit phase-only forms
            # still error.
            if cmd.startswith("/build ") and "-phase" not in cmd:
                return self._app_module_build(token, turn)
            return self._build_note(
                turn,
                f"Unknown phase '{token}'. Valid phases: "
                f"{', '.join(PHASE_ORDER)}.",
            )
        return self._app_phase_build(phase, turn)

    def _app_phase_build(self, phase: str, turn: int) -> TurnResult:
        from runners.agent.build_from_blueprint import build_phase

        self._resolve_patterns()
        plan = {e["phase"] for e in phase_plan(self.state.get("patterns") or [])}
        if phase not in plan:
            return self._build_note(
                turn,
                f"No '{phase}' modules resolved yet. Phases with content: "
                f"{', '.join(sorted(plan)) or '(none)'}.",
            )
        project_path = write_project(self.state, self.session_dir)
        summary, error = self._run_partial_build(
            lambda c: build_phase(
                blueprint_path=Path(project_path),
                pattern_root=PATTERNS_ROOT, phase=phase, console=c,
            )
        )
        if summary and summary.get("ok"):
            built = self.state.setdefault("built_phases", [])
            if phase not in built:
                built.append(phase)
            nxt = next_unbuilt_phase(self.state.get("patterns") or [], built)
            tail = (
                f" Next phase: **{nxt}** — `/build {nxt}`, or `done` to assemble."
                if nxt else " All phases done — type `done` to assemble."
            )
            msg = self._build_summary_line(summary, f"Phase '{phase}'") + tail
        else:
            msg = self._build_summary_line(summary, f"Phase '{phase}'", error)
        self.history.append({"role": "agent", "message": msg})
        self._append_md(turn, "agent", msg, note=f"build phase {phase}")
        self._save()
        self._logger.info(
            "phase_build turn=%d phase=%s ok=%s", turn, phase,
            summary.get("ok") if summary else None,
        )
        return TurnResult(
            agent_message=msg, kind="build",
            project_yaml_path=Path(project_path),
            validation_summary=summary, build_error=error,
        )

    def _app_module_build(self, name: str, turn: int) -> TurnResult:
        from runners.agent.build_from_blueprint import build_module

        target = _resolve_module_target(self.state, self.catalog, name)
        if target is None:
            return self._build_note(
                turn,
                f"No module named '{name}' in the project.\n\n"
                + _module_list_text(self.state, self.catalog),
            )
        pattern, match = target
        project_path = write_project(self.state, self.session_dir)
        summary, error = self._run_partial_build(
            lambda c: build_module(
                blueprint_path=Path(project_path),
                pattern_root=PATTERNS_ROOT, pattern=pattern,
                instance_match=match, console=c,
            )
        )
        label = next(iter(match.values()))
        if summary and summary.get("ok"):
            built = self.state.setdefault("built_modules", [])
            key = f"{pattern}::{label}"
            if key not in built:
                built.append(key)
            msg = self._build_summary_line(summary, f"Module '{label}'") + (
                " Build another with `/build <name>`, or `/phases` for the plan."
            )
        else:
            msg = self._build_summary_line(summary, f"Module '{label}'", error)
        self.history.append({"role": "agent", "message": msg})
        self._append_md(turn, "agent", msg, note=f"build module {label}")
        self._save()
        self._logger.info(
            "module_build turn=%d module=%s ok=%s", turn, label,
            summary.get("ok") if summary else None,
        )
        return TurnResult(
            agent_message=msg, kind="build",
            project_yaml_path=Path(project_path),
            validation_summary=summary, build_error=error,
        )

    def _app_module_scope_build(self, focus, turn: int) -> TurnResult:
        """Build every capability phase the focused FEWS-folder module owns.

        Mirrors the CLI ``_run_module_scope_build``: a folder-module maps to
        one or more capability phases; build each that has resolved content,
        reusing the per-phase build. View/deriver modules aren't built on
        their own.
        """
        if not focus.phases:
            return self._build_note(
                turn,
                f"The '{focus.label}' module isn't built on its own — it's "
                f"produced from your inputs or at final assembly. Type "
                f"`done` to assemble the project.",
            )
        self._resolve_patterns()
        plan = phase_plan(self.state.get("patterns") or [])
        target_phases = [
            e["phase"] for e in plan
            if e["patterns"]
            and module_for_pattern(e["patterns"][0]["pattern"]) == focus.key
        ]
        if not target_phases:
            return self._build_note(
                turn,
                f"Nothing resolved for the '{focus.label}' module yet. Add "
                f"something first (e.g. `/add GFS`), then `/build`.",
            )
        # Build each phase (each appends its own panel to history); return
        # the last phase's result for the turn's TurnResult.
        result: TurnResult | None = None
        for ph in target_phases:
            result = self._app_phase_build(ph, turn)
        return result

    def _reply(
        self, turn: int, message: str, note: str, kind: str = "reply",
        **tr_kwargs,
    ) -> TurnResult:
        """Append an agent reply to history + transcript, save, return.

        A muted ``confirmation`` (the "what changed" fact) is stored on the
        history entry too, so the grey caption survives Streamlit reruns that
        replay the conversation."""
        confirmation = tr_kwargs.get("confirmation", "")
        entry = {"role": "agent", "message": message}
        if confirmation:
            entry["confirmation"] = confirmation
        self.history.append(entry)
        self._append_md(turn, "agent", message, note=note)
        self._save()
        return TurnResult(agent_message=message, kind=kind, **tr_kwargs)

    def _run_module_operation(
        self, focus, message: str, turn: int, provider,
        just_entered: bool = False,
    ) -> TurnResult:
        """Module-mode prose turn (Streamlit shell over ``run_module_turn``).

        The shared engine extracts + applies the one operation; this shell
        maps its driver-agnostic result to a ``TurnResult`` and, on a
        ``build`` action, runs the app's scoped phase build.
        """
        res = run_module_turn(
            self.state, message, self.catalog, focus, provider=provider,
            just_entered=just_entered, history=self.history,
        )
        if res.wants_build:
            return self._app_module_scope_build(focus, turn)
        self._logger.info("module_op turn=%d note=%s", turn, res.note)
        return self._reply(
            turn, res.reply, res.note, kind=res.kind,
            new_patterns=res.new_patterns, confirmation=res.confirmation,
        )

    def module_statuses(self) -> list[dict]:
        """Per-FEWS-module status for the sidebar navigator, in registry order.

        Each entry: ``{"key", "label", "built", "focused"}``. ``built`` (the
        green light) means the module's XMLs actually exist: for modules that
        own capability phases (processing, display) — every phase of theirs
        with resolved content is in ``built_phases`` (and there IS content);
        for the deriver/view modules (locations, filters, topology, ...) —
        their files only exist after final assembly, so green requires
        ``full_build_ok``. Grey = not worked/built yet.
        """
        from fews_agent.agent.modules import list_modules

        self._resolve_patterns()
        plan = phase_plan(self.state.get("patterns") or [])
        built_phases = set(self.state.get("built_phases") or [])
        full_ok = bool(self.state.get("full_build_ok"))
        focused = self.state.get("current_module")

        # phase → has resolved content, per the same mapping the scoped
        # build uses (module_for_pattern on the phase's patterns).
        module_phases: dict[str, list[tuple[str, bool]]] = {}
        for entry in plan:
            pats = entry.get("patterns") or []
            if not pats:
                continue
            mod_key = module_for_pattern(pats[0]["pattern"])
            module_phases.setdefault(mod_key, []).append(
                (entry["phase"], entry["phase"] in built_phases)
            )

        out: list[dict] = []
        for m in list_modules():
            short = m.label.split(" (")[0].strip() or m.key
            if m.phases:
                phases_here = module_phases.get(m.key) or []
                built = bool(phases_here) and all(ok for _, ok in phases_here)
            else:
                built = full_ok
            out.append({
                "key": m.key, "label": short,
                "built": built, "focused": m.key == focused,
            })
        return out

    # ---- download bundles (sidebar) ------------------------------------------

    @property
    def output_root(self) -> Path:
        """Where this session's builds render: <session>/generated."""
        return self.session_dir / "generated"

    def _generated_files(self) -> list[tuple[Path, str]]:
        """(abs_path, posix_relpath) for every rendered file, session-scoped."""
        root = self.output_root
        if not root.is_dir():
            return []
        return sorted(
            (p, p.relative_to(root).as_posix())
            for p in root.rglob("*") if p.is_file()
        )

    def module_zip(self, module_key: str) -> tuple[bytes, int] | None:
        """Zip ONE module's rendered files (for the sidebar ⬇ next to its
        name). Scoping comes from the module registry's ``folders`` — a
        trailing-slash entry is a directory prefix; a ``…/X.xml`` entry also
        matches split variants (``FiltersLiard.xml``) via its stem. Returns
        ``(zip_bytes, n_files)`` or None when the module has nothing yet."""
        import io
        import zipfile

        from fews_agent.agent.modules import get_module

        module = get_module(module_key)
        if module is None:
            return None
        prefixes = [
            f[:-4] if f.endswith(".xml") else f for f in module.folders
        ]
        picked = [
            (p, rel) for p, rel in self._generated_files()
            if any(rel.startswith(pre) for pre in prefixes)
        ]
        if not picked:
            return None
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for p, rel in picked:
                zf.write(p, rel)
        return buf.getvalue(), len(picked)

    def config_zip(self) -> tuple[bytes, int] | None:
        """Zip the whole rendered tree as a ``Config/`` folder — including an
        EMPTY directory entry for every folder a Delft-FEWS Config normally
        carries (CONFIG_FOLDERS), so the bundle drops into a FEWS region as a
        complete skeleton even where this project generated nothing."""
        import io
        import zipfile

        from fews_agent.agent.modules import CONFIG_FOLDERS

        files = self._generated_files()
        if not files:
            return None
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for folder in CONFIG_FOLDERS:
                zf.writestr(zipfile.ZipInfo(f"Config/{folder}/"), b"")
            for p, rel in files:
                zf.write(p, f"Config/{rel}")
        return buf.getvalue(), len(files)

    # ---- grid coordinates subwindow -----------------------------------------

    def _nwp_grid_imports(self) -> list[dict]:
        """The project's NWP grid imports eligible for /coordinates, each as
        ``{"name", "geometry", "cell_size"}``.

        ``geometry`` is the current override (or None); ``cell_size`` is the
        *effective inherited* cell size in degrees, so the subwindow can draw
        the grid box on a map without asking for it (it's what the build will
        use)."""
        resolve_patterns(self.state, self.catalog)
        overrides = (self.state.get("slots") or {}).get("import_overrides") or {}
        out: list[dict] = []
        seen: set[str] = set()
        for p in self.state.get("patterns") or []:
            if not str(p.get("pattern", "")).startswith("auto/nwp_grid_"):
                continue
            for inst in p.get("instances") or []:
                name = inst.get("nwp_name") or inst.get("source_name")
                if not name or name in seen:
                    continue
                seen.add(name)
                geom = (overrides.get(name) or {}).get("grid_geometry")
                out.append({
                    "name": name, "geometry": geom,
                    "cell_size": self._effective_cell_size(name),
                })
        return out

    def _effective_cell_size(self, name: str) -> float:
        """The cell size (deg) the build will use for ``name`` — a resolution
        override's slug if set, else the bundled gridsFile default, else 0.25.
        Used only to DRAW the grid box (cell size stays inherited)."""
        slots = self.state.get("slots") or {}
        ov = (slots.get("import_overrides") or {}).get(name) or {}
        slug = ov.get("grid_resolution") or slots.get("grid_resolution")
        from runners.agent.build_from_blueprint import _GRID_RESOLUTION_DEGREES
        if slug and slug in _GRID_RESOLUTION_DEGREES:
            return _GRID_RESOLUTION_DEGREES[slug]
        return _bundled_grid_cell_size(name) or 0.25

    def _open_coordinates(self, turn: int, token: str = "") -> TurnResult:
        """Open the grid-coordinates subwindow for one or all NWP grids.

        Shared by the ``/coordinates`` command AND the free-language route
        (``detect_coordinates_request`` — "set GFS's map area"), so the agent
        can talk in plain English instead of instructing the user to type a
        slash command. ``token`` optionally pre-selects a grid by name.
        """
        grids = self._nwp_grid_imports()
        if not grids:
            reply = (
                "There's no gridded import to set an area for yet — add one "
                "first, for example by saying \"add GFS\"."
            )
            self.history.append({"role": "agent", "message": reply})
            self._append_md(turn, "agent", reply, note="coordinates: none")
            self._save()
            return TurnResult(agent_message=reply, kind="reply")
        want = (token or "").strip().lower()
        if want:
            grids = [g for g in grids if g["name"].lower() in want] or grids
        names = ", ".join(g["name"] for g in grids)
        reply = f"Set the map area for {names} below."
        self.history.append({"role": "agent", "message": reply})
        self._append_md(turn, "agent", reply, note="coordinates: open")
        self._save()
        self._logger.info("coordinates turn=%d grids=%d", turn, len(grids))
        return TurnResult(
            agent_message=reply, kind="coordinates", coordinates_request=grids,
        )

    def apply_grid_geometry(
        self, name: str, *,
        first_x: float, first_y: float, columns: int, rows: int,
    ) -> TurnResult:
        """Apply a grid geometry from the coordinates subwindow.

        Sets the per-import ``grid_geometry`` override (firstCellCenter +
        rows/columns; cell size inherited), re-resolves, persists, and returns
        an ``edit`` result. Called by the web app when the modal is submitted.
        """
        note = set_grid_geometry(
            self.state, name, first_x=first_x, first_y=first_y,
            columns=columns, rows=rows,
        )
        resolve_patterns(self.state, self.catalog)
        turn = len([h for h in self.history if h.get("role") == "user"]) or 1
        reply = note + "\n\n" + _module_list_text(self.state, self.catalog)
        self._logger.info(
            "grid_geometry name=%s cols=%d rows=%d", name, columns, rows,
        )
        return self._reply(turn, reply, "coordinates: applied", kind="edit")

    # ---- undo support --------------------------------------------------------

    # Max snapshots kept; older ones evicted. Each snapshot is a
    # JSON-roundtripped copy of state minus the stack itself.
    _UNDO_DEPTH = 10

    def _push_undo_snapshot(self) -> None:
        """Push a copy of the current state onto state['_undo_stack'].

        Called at the start of every non-/undo turn, so /undo on the
        NEXT turn rolls back THIS turn's mutations. JSON-roundtripped
        for deep-copy — state is already JSON-serializable (it gets
        written to .chat_state.json each turn).
        """
        snap = json.loads(json.dumps(self.state, default=str))
        snap.pop("_undo_stack", None)
        stack = self.state.setdefault("_undo_stack", [])
        stack.append(snap)
        if len(stack) > self._UNDO_DEPTH:
            del stack[0]  # drop oldest

    def _pop_undo_snapshot(self) -> bool:
        """Restore state from the latest snapshot. False if stack empty.

        Mutates ``self.state`` in-place to preserve dict identity for
        any other code holding the same reference. Keeps the running
        ``model`` pinned so resuming a session with a switched model
        doesn't get rolled back into the previous selection.
        """
        stack = self.state.get("_undo_stack") or []
        if not stack:
            return False
        snap = stack.pop()
        new_stack = list(stack)
        self.state.clear()
        self.state.update(snap)
        self.state["_undo_stack"] = new_stack
        self.state["model"] = self.model
        return True

    # ---- public surface ------------------------------------------------------

    @property
    def messages(self) -> list[dict]:
        """Chat history as a list of ``{role, message}`` dicts (a snapshot copy)."""
        return list(self.history)

    def send(self, message: str) -> TurnResult:
        """Process one user message; persist state, history, markdown, and app log."""
        try:
            return self._send_inner(message)
        except Exception as exc:  # noqa: BLE001
            self._logger.exception("send_failed message=%r", message[:200])
            return TurnResult(
                agent_message=f"Error processing turn: {exc}",
                kind="error",
            )

    # ---- the turn pipeline (mirrors runners/agent/chat_step.py::main) --------

    def _send_inner(self, message: str) -> TurnResult:
        turn = self._turn_count() + 1
        self.history.append({"role": "user", "message": message})
        self._append_md(turn, "user", message)
        self._logger.info("turn_start turn=%d msg=%r", turn, message[:200])

        cmd = message.lower().strip()

        # /undo — must precede the snapshot push for this turn, otherwise
        # we'd push current state and immediately pop the very snapshot we
        # just made. After restoring, the /undo turn itself stays in
        # history (history is append-only) so the transcript is honest
        # about what happened.
        if cmd in {"/undo", "undo"}:
            if not self._pop_undo_snapshot():
                reply = "Nothing to undo — no prior state snapshot recorded."
            else:
                intent = self.state.get("intent") or "(none)"
                slots = self.state.get("slots") or {}
                filled = sum(1 for v in slots.values() if v)
                patterns = len(self.state.get("patterns") or [])
                depth = len(self.state.get("_undo_stack") or [])
                reply = (
                    f"Undone — state rolled back. Now: intent="
                    f"{intent}, {filled} slot(s) filled, "
                    f"{patterns} pattern(s). "
                    f"{depth} more snapshot(s) available."
                )
            self.history.append({"role": "agent", "message": reply})
            self._append_md(turn, "agent", reply, note="undo")
            self._save()
            self._logger.info("undo turn=%d", turn)
            return TurnResult(agent_message=reply, kind="reply")

        # Snapshot before any other handler mutates state, so /undo on
        # the next turn can roll back this turn's changes.
        self._push_undo_snapshot()

        # Pending intent disambiguation: a prior turn asked "imports only or a
        # full forecasting project?" and is awaiting the answer. The shared
        # helper consumes this turn's message as that answer (commits + latches
        # on a clear choice, else clears the flag so the Phase 3.5 gate
        # re-evaluates against this turn's slots).
        apply_disambiguation_answer(self.state, message)

        # done / force-done -----------------------------------------------------
        # Collects ALL blocking issues into one refusal message so the
        # user sees everything that needs fixing at once, not turn-by-
        # turn. Slots are HARD-blocking (write_project would produce a
        # malformed yaml without them — /force-done cannot override).
        # Missing required CSVs and open warnings are SOFT-blocking —
        # /force-done lets the user accept the risk and write anyway.
        if cmd in {"done", "/done", "quit", "force-done", "/force-done"}:
            force = cmd in {"force-done", "/force-done"}
            intent = INTENTS.get(self.state.get("intent") or "")
            slots = self.state.get("slots") or {}

            next_q: str | None = None
            if intent and not is_intent_ready(intent, slots):
                next_q = next_unfilled_question(intent, slots)
            elif not intent:
                next_q = (
                    "describe the project first — I don't know what "
                    "you want to build yet"
                )

            inputs_dir = self.session_dir / "inputs"
            input_scan = scan_inputs(inputs_dir)
            input_status = compute_input_status(
                self.state.get("intent"), input_scan, slots,
            )
            missing_csvs = list(input_status.get("csvs_required_missing", []))
            warnings = list(self.state.get("warnings") or [])

            hard_block = next_q is not None
            soft_block = (missing_csvs or warnings) and not force

            if hard_block or soft_block:
                lines = ["**Cannot write project.yaml yet.** Missing inputs:"]
                if next_q:
                    lines.append(f"- **Required slot**: {next_q}")
                if missing_csvs:
                    lines.append(
                        f"- **Required CSV(s)** missing from `inputs/`: "
                        f"{', '.join(missing_csvs)}. Upload via the "
                        f"sidebar."
                    )
                if warnings:
                    lines.append(f"- **{len(warnings)} open warning(s)**:")
                    for w in warnings:
                        lines.append(f"  - {w}")
                if not hard_block:
                    lines.append(
                        "\nType `/force-done` to write anyway, or fix "
                        "the items above and retry."
                    )
                note = "\n".join(lines)
                self.history.append({"role": "agent", "message": note})
                self._append_md(turn, "agent", note, note="done refused")
                self._save()
                self._logger.info(
                    "done_refused hard=%s slots=%s csvs=%d warnings=%d",
                    hard_block, bool(next_q), len(missing_csvs), len(warnings),
                )
                return TurnResult(
                    agent_message=note, kind="refused",
                    next_question=next_q, ready=False, warnings=warnings,
                )

            self._resolve_patterns()
            project_path = write_project(self.state, self.session_dir)
            msg_parts = [f"Wrote `{project_path}`."]
            if force and (missing_csvs or warnings):
                forced = []
                if missing_csvs:
                    forced.append(f"{len(missing_csvs)} missing CSV(s)")
                if warnings:
                    forced.append(f"{len(warnings)} warning(s)")
                msg_parts.append(
                    f"Forced through {' and '.join(forced)} — "
                    f"address these before running the build."
                )

            # Run the full build pipeline so the UI can show Pydantic
            # + XSD validation for every emitted XML. Wrapped in a
            # try/except so a build crash doesn't lose the (already
            # successful) project.yaml write — the user can still
            # inspect the file and re-run via CLI.
            validation_summary, build_error = self._run_build(
                Path(project_path),
            )
            if build_error:
                msg_parts.append(
                    f"Build pipeline failed before completion — "
                    f"see error below."
                )
            elif validation_summary is not None:
                n_total = validation_summary.get("files_total", 0)
                n_xml = validation_summary.get(
                    "files_xml",
                    n_total - validation_summary.get("files_non_xml", 0),
                )
                n_xsd = validation_summary.get("files_xsd_ok", 0)
                n_err = len(validation_summary.get("errors") or [])
                if validation_summary.get("ok"):
                    msg_parts.append(
                        f"Build: {n_total} files generated, "
                        f"{n_xsd}/{n_xml} XSD-valid, 0 Pydantic errors."
                    )
                else:
                    msg_parts.append(
                        f"Build completed with issues — "
                        f"{n_xsd}/{n_xml} XSD-valid"
                        + (f", {n_err} Pydantic/render error(s)" if n_err else "")
                        + ". See validation panel below."
                    )

            msg = " ".join(msg_parts)
            self.history.append({"role": "agent", "message": msg})
            self._append_md(turn, "agent", msg, note="done")
            self._save()
            self._logger.info(
                "done path=%s build_ok=%s",
                project_path,
                validation_summary.get("ok") if validation_summary else None,
            )
            return TurnResult(
                agent_message=msg, kind="done",
                project_yaml_path=Path(project_path), ready=True,
                validation_summary=validation_summary,
                build_error=build_error,
            )

        # ----- stepwise module flow: phases / list / edits / build -----------
        # Deterministic (no LLM): mutate slots then re-resolve. Mirrors the
        # CLI driver (runners/agent/chat_step.py::main) so the web app and
        # terminal behave identically.

        # /modules — list the FEWS-folder modules you can build one at a time.
        if cmd in {"/modules", "modules"}:
            reply = module_focus.modules_overview()
            cur = self.state.get("current_module")
            if cur:
                reply += f"\n\nIn focus now: {cur}."
            self.history.append({"role": "agent", "message": reply})
            self._append_md(turn, "agent", reply, note="module overview")
            self._save()
            self._logger.info("modules turn=%d", turn)
            return TurnResult(agent_message=reply, kind="reply")

        # /module [name] — put ONE module in focus (or report current focus).
        if cmd == "/module" or cmd.startswith("/module "):
            confirmation = ""
            if cmd == "/module":
                cur = module_focus.get_focus(self.state)
                if cur:
                    reply = module_welcome(self.state, cur)
                    confirmation = module_focus.focus_card(self.state, cur)
                else:
                    reply = ("No module in focus. Pick one with  /module <name>"
                             "  (see  /modules  for the list).")
            else:
                token = message.strip().split(None, 1)[1].strip()
                _module, reply = module_focus.set_focus(self.state, token)
                if _module is not None:
                    reply = module_welcome(self.state, _module)
                    confirmation = module_focus.focus_card(self.state, _module)
            entry = {"role": "agent", "message": reply}
            if confirmation:
                entry["confirmation"] = confirmation
            self.history.append(entry)
            self._append_md(turn, "agent", reply, note="module focus")
            self._save()
            self._logger.info("module_focus turn=%d cur=%s", turn,
                              self.state.get("current_module"))
            return TurnResult(agent_message=reply, kind="reply",
                              confirmation=confirmation)

        # /phases — phase-level plan (finer build groups within processing/display).
        if cmd in {"/phases", "phases", "/plan", "plan"}:
            reply = _phase_plan_text(self.state, self.catalog)
            self.history.append({"role": "agent", "message": reply})
            self._append_md(turn, "agent", reply, note="phase plan")
            self._save()
            self._logger.info("phases turn=%d", turn)
            return TurnResult(agent_message=reply, kind="reply")

        # /show <target> · /present <target> — render how a file WILL generate
        # (fresh, in memory, from current state) and print it in the chat.
        if cmd.startswith(("/show ", "/present ", "show ", "present "))                 or cmd in {"/show", "/present"}:
            from fews_agent.agent.preview import format_previews, preview_files
            _parts = message.strip().split(None, 1)
            _target = _parts[1].strip() if len(_parts) > 1 else ""
            if not _target:
                reply = ("Tell me what to preview — an instance "
                         "(**/show GFS**) or a filename (**/show Topology**).")
            else:
                reply = format_previews(
                    preview_files(self.state, _target,
                                  output_root=self.output_root),
                    _target,
                )
            self.history.append({"role": "agent", "message": reply})
            self._append_md(turn, "agent", reply, note="preview")
            self._save()
            return TurnResult(agent_message=reply, kind="reply")

        # /vars [name] — bare: what's in the project (the old /list); with a
        # name: that instance's tunable variables + which are still defaults.
        # list/show stay as aliases of the bare form.
        if cmd in {"/vars", "vars"} or cmd.startswith(("/vars ", "vars ")) \
                or cmd in {"/list", "list", "/show", "show"}:
            _parts = message.strip().split(None, 1)
            _target = _parts[1].strip() if len(_parts) > 1 else None
            reply = module_vars_reply(self.state, self.catalog, _target)
            self.history.append({"role": "agent", "message": reply})
            self._append_md(turn, "agent", reply, note="module list")
            self._save()
            self._logger.info("list turn=%d", turn)
            return TurnResult(agent_message=reply, kind="reply")

        # /coordinates [<name>] — open the grid-coordinates subwindow to set a
        # firstCellCenter + rows/columns for an NWP grid import. Deterministic:
        # returns a UI signal (kind="coordinates") the web app turns into a
        # modal; submitting it calls apply_grid_geometry().
        if cmd == "/coordinates" or cmd.startswith(("/coordinates ", "/coords")):
            parts = message.strip().split(None, 1)
            return self._open_coordinates(
                turn, parts[1].strip() if len(parts) > 1 else "",
            )

        # /add /remove /drop /set — explicit edits. The command IS the
        # confirmation; the engine-proposed yes/no flow stays for ambiguous
        # NL-driven removals only.
        if cmd.startswith(("/add ", "/remove ", "/drop ", "/set ")):
            verb = message.strip().split(None, 1)[0].lstrip("/").lower()
            op = "remove" if verb == "drop" else verb
            rest = message.strip().split(None, 1)[1].strip()
            edits = _parse_slash_edit(op, rest)
            if not edits:
                reply = (
                    "Couldn't parse that edit. Usage:  /add <name>  ·  "
                    "/remove <name>  ·  /set <name> <var> <value>"
                )
                self.history.append({"role": "agent", "message": reply})
                self._append_md(turn, "agent", reply, note="edit parse fail")
                self._save()
                return TurnResult(agent_message=reply, kind="reply")
            edit_notes = [
                apply_edit_action(self.state, e, self.catalog) for e in edits
            ]
            reply = module_edit_reply("\n".join(edit_notes), self.state)
            self.history.append({"role": "agent", "message": reply})
            self._append_md(turn, "agent", reply, note=f"edit:{op}")
            self._save()
            self._logger.info("edit turn=%d op=%s n=%d", turn, op, len(edits))
            return TurnResult(agent_message=reply, kind="edit")

        # /build [phase|module] — build one capability group or one module.
        if cmd == "/build" or cmd.startswith(
            ("/build ", "/build-phase ", "build phase ")
        ):
            return self._handle_build(message, cmd, turn)

        # /preview — dry-run what /done would write, no file created -----------
        if cmd in {"/preview", "preview"}:
            import yaml
            self._resolve_patterns()
            project = {
                "name": self.state.get("name") or self.project_name,
                "output_root": "generated",
                "patterns": self.state.get("patterns", []),
                "singleton_seeds": self.state.get("singleton_seeds", {}),
            }
            yaml_text = yaml.safe_dump(project, sort_keys=False, width=200)
            reply = (
                "This is what `/done` would write right now — nothing "
                "has been saved yet:\n\n```yaml\n" + yaml_text + "```"
            )
            self.history.append({"role": "agent", "message": reply})
            self._append_md(turn, "agent", reply, note="preview")
            self._save()
            self._logger.info(
                "preview turn=%d patterns=%d", turn, len(project["patterns"]),
            )
            return TurnResult(agent_message=reply, kind="reply")

        # /reset — clear state (asks to confirm) --------------------------------
        if cmd in {"/reset", "reset"}:
            intent = self.state.get("intent") or "(none)"
            slots = self.state.get("slots") or {}
            filled = sum(1 for v in slots.values() if v)
            patterns = len(self.state.get("patterns") or [])
            self.state["_pending_reset"] = True
            reply = (
                f"Reset will clear: intent={intent}, {filled} filled "
                f"slot(s), {patterns} pattern(s), warnings, and undo "
                f"history. The session folder, uploaded inputs/, and "
                f"conversation transcript stay. Type 'yes' to confirm "
                f"or 'no' to cancel."
            )
            self.history.append({"role": "agent", "message": reply})
            self._append_md(turn, "agent", reply, note="reset pending")
            self._save()
            self._logger.info("reset_pending turn=%d", turn)
            return TurnResult(agent_message=reply, kind="pending")

        # confirm / cancel pending removals + pending reset ---------------------
        pending = self.state.get("_pending_removals") or []
        pending_reset = bool(self.state.get("_pending_reset"))
        if (pending or pending_reset) and cmd in {"yes", "y", "confirm", "ok"}:
            if pending_reset:
                from fews_agent.agent.project_chat import (
                    initial_state as _initial_state,
                )
                preserved_stack = list(self.state.get("_undo_stack") or [])
                new_state = _initial_state(self.project_name)
                new_state.setdefault("intent", None)
                new_state.setdefault("slots", {})
                new_state["model"] = self.model
                # Preserve undo stack so the user can /undo the reset.
                new_state["_undo_stack"] = preserved_stack
                self.state.clear()
                self.state.update(new_state)
                msg = (
                    "State reset. Tell me what you want to build next. "
                    "Type '/undo' if you want the previous state back."
                )
                self.history.append({"role": "agent", "message": msg})
                self._append_md(turn, "agent", msg, note="reset confirmed")
                self._save()
                self._logger.info("reset_confirmed turn=%d", turn)
                return TurnResult(agent_message=msg, kind="pending")
            for r in pending:
                apply_removal(self.state, r["pattern"])
            self.state["_pending_removals"] = []
            msg = f"Removed {len(pending)} pattern(s)."
            self.history.append({"role": "agent", "message": msg})
            self._append_md(turn, "agent", msg, note="removal confirmed")
            self._save()
            return TurnResult(agent_message=msg, kind="pending")
        if (pending or pending_reset) and cmd in {"no", "n", "cancel"}:
            if pending_reset:
                self.state.pop("_pending_reset", None)
                msg = "Reset cancelled — state untouched."
            else:
                self.state["_pending_removals"] = []
                msg = "Cancelled removal."
            self.history.append({"role": "agent", "message": msg})
            self._append_md(turn, "agent", msg, note="cancel")
            self._save()
            return TurnResult(agent_message=msg, kind="pending")

        # /edit start ----------------------------------------------------------
        if cmd.startswith("/edit "):
            from fews_agent.agent import edit_modes
            target = message.strip().split(None, 1)[1].strip()
            reply, done = edit_modes.start(self.state, target, self.session_dir)
            if done:
                self.state.pop("_editing", None)
            self.history.append({"role": "agent", "message": reply})
            self._append_md(turn, "agent", reply, note="edit-mode start")
            self._save()
            return TurnResult(agent_message=reply, kind="edit")

        # /cancel-edit ---------------------------------------------------------
        if cmd in {"/cancel-edit", "cancel-edit", "/abort-edit"}:
            had = bool(self.state.get("_editing"))
            self.state.pop("_editing", None)
            reply = "Edit session cancelled." if had else "No active edit session."
            self.history.append({"role": "agent", "message": reply})
            self._append_md(turn, "agent", reply, note="edit cancel")
            self._save()
            return TurnResult(agent_message=reply, kind="edit")

        # routed to active edit session ----------------------------------------
        if self.state.get("_editing"):
            from fews_agent.agent import edit_modes
            reply, done = edit_modes.advance_turn(
                self.state, message, self.session_dir
            )
            if done:
                self.state.pop("_editing", None)
            self.history.append({"role": "agent", "message": reply})
            self._append_md(turn, "agent", reply, note="edit-mode")
            self._save()
            return TurnResult(agent_message=reply, kind="edit")

        # Greeting short-circuit: pure chitchat doesn't carry any
        # project intent, so don't fire two LLM calls (intent classify
        # + compose reply) on it. The first response on a fresh session
        # is the slowest one — Ollama has to load the model into RAM —
        # and "hi" / "hello" should not pay that cost.
        _stripped = cmd.rstrip("?.!,").strip()
        _GREETINGS = {
            "hi", "hello", "hey", "yo", "howdy", "sup", "hiya", "ola", "olla",
            "good morning", "good afternoon", "good evening",
            "how are you", "how's it going", "whats up", "what's up",
            "thanks", "thank you", "ty", "thx",
            "ok", "okay", "k", "cool", "nice", "great",
        }
        if _stripped in _GREETINGS and self.state.get("intent") is None:
            reply = (
                "Hi! Tell me what you'd like to build. For example:\n\n"
                "*\"a forecasting project for the Liard basin using Raven, "
                "with HRDPS and GFS imports\"*."
            )
            self.history.append({"role": "agent", "message": reply})
            self._append_md(turn, "agent", reply, note="greeting short-circuit")
            self._save()
            self._logger.info("greeting_shortcircuit turn=%d", turn)
            return TurnResult(agent_message=reply, kind="reply")

        # Help meta intent: explain-the-system questions ("what is a
        # slot?", "explain patterns", "help"), follow-ups ("tell me
        # more", "give an example"), comparatives ("compare slots and
        # intents"). Mutually exclusive with status_check because
        # detect_help_query requires either (a) help-phrase + concept,
        # (b) comparative + concept, or (c) follow-up phrase right
        # after a prior help turn. "what is missing?" has neither —
        # it falls through to status.
        prev_was_help = (
            self.state.get("_last_help_turn") == turn - 1
        )
        if detect_help_query(message, prev_was_help=prev_was_help):
            # Bare "help" → static topic list (no LLM, instant).
            # Everything else → LLM grounded in CLAUDE.md + glossary
            # entry + recent history. Falls back to the static
            # glossary entry when Ollama is down.
            bare_help = message.strip().lower().rstrip("?.!,").strip() in {
                "help", "/help",
            }
            if bare_help:
                reply = compose_help_reply(message)
                source = "topic list (static)"
            else:
                llm_err = check_ollama_for_model(self.model)
                if llm_err:
                    reply = compose_help_reply(message)  # static glossary fallback
                    source = "static fallback (LLM unavailable)"
                else:
                    provider = get_provider(model=self.model)
                    reply = compose_help_reply(
                        user_message=message,
                        history=self.history,
                        docs=_load_project_docs(),
                        provider=provider,
                    )
                    source = "LLM + CLAUDE.md"
            self.state["_last_help_turn"] = turn
            self.history.append({"role": "agent", "message": reply})
            self._append_md(
                turn, "agent", reply, note=f"help — {source}",
            )
            self._save()
            self._logger.info(
                "help_query turn=%d prev_was_help=%s source=%s",
                turn, prev_was_help, source,
            )
            return TurnResult(agent_message=reply, kind="reply")

        # Status-check meta intent: meta-queries ("what's missing?",
        # "summary", "status") don't add project info, so bypass the
        # slot-fill / pattern-resolve / warnings pipeline and answer
        # from a deterministic snapshot. Runs BEFORE the Ollama
        # pre-flight so the configurator can still get a status answer
        # (via the deterministic fallback) when the LLM is down.
        if detect_status_query(message):
            inputs_dir = self.session_dir / "inputs"
            input_scan = scan_inputs(inputs_dir)
            input_status = compute_input_status(
                self.state.get("intent"), input_scan,
                self.state.get("slots") or {},
            )
            report = build_status_report(self.state, input_status)
            llm_err = check_ollama_for_model(self.model)
            if llm_err:
                reply = status_prose_fallback(report)
            else:
                provider = get_provider(model=self.model)
                reply = compose_status_reply(
                    user_message=message,
                    report=report,
                    provider=provider,
                )
            internals = _format_internals(
                prose_facts={"status_query": True},
                llm_intent=None,
                llm_entities=None,
                chosen_intent=self.state.get("intent"),
                notes=[
                    "status_check (meta intent)",
                    "LLM unavailable — used deterministic fallback"
                    if llm_err else "compose_status_reply (LLM)",
                ],
                state=self.state,
                new_patterns=[],
                ready=report.get("ready", False),
                next_q=None,
                input_status=input_status,
                warnings=list(self.state.get("warnings") or []),
            )
            self.history.append({"role": "agent", "message": reply})
            self._append_md(
                turn, "agent", reply,
                note="status-check", internals=internals,
            )
            self._save()
            self._logger.info(
                "status_check turn=%d intent=%s missing_csvs=%d ready=%s",
                turn,
                self.state.get("intent"),
                len(report.get("csvs_required_missing", [])),
                report.get("ready", False),
            )
            return TurnResult(
                agent_message=reply,
                kind="reply",
                internals=internals,
                warnings=list(self.state.get("warnings") or []),
                ready=report.get("ready", False),
            )

        # Pre-flight: every remaining normal turn ends at compose_reply
        # (LLM), so fail loudly here if Ollama is unreachable or the
        # model isn't installed. Without this, compose_reply silently
        # falls back to a literal "Updated." string and the UI looks
        # broken.
        llm_err = check_ollama_for_model(self.model)
        if llm_err:
            self.history.append({"role": "agent", "message": llm_err})
            self._append_md(turn, "agent", llm_err, note="LLM unavailable")
            self._save()
            self._logger.error("llm_unavailable model=%s", self.model)
            return TurnResult(agent_message=llm_err, kind="error")

        # Phases 1–5 run in the shared turn engine (the same pipeline the CLI
        # driver uses — fews_agent/agent/turn_engine). The provider is resolved
        # here, after the pre-flight above; the engine mutates `self.state` and
        # returns the reply + diagnostics. nag_suppression=True preserves the
        # app's repeat-turn missing-input snooze (a CLI-absent behaviour).
        provider = get_provider(model=self.model)

        # LLM-first turn: ONE model call — Python assembles the grounding
        # context (state, catalog, gap, inputs, last build, history), the
        # model returns a reply + a slot PATCH, patch_ops validates + applies.
        # No intent classification, no module gating, no detector pre-pass —
        # the module in focus rides along as ADVISORY context only.
        res = run_llm_turn(
            self.state, message, self.catalog, provider=provider,
            history=self.history, inputs_dir=self.session_dir / "inputs",
        )
        self._logger.info("llm_turn turn=%d note=%s", turn, res.note)

        # Signals → the existing deterministic machinery.
        if res.coordinates_for is not None:
            # Record the model's reply first so the modal has conversational
            # context above it, then open the subwindow.
            self.history.append({"role": "agent", "message": res.reply})
            self._append_md(turn, "agent", res.reply, note=res.note)
            self._save()
            return self._open_coordinates(turn, res.coordinates_for)
        if res.wants_assemble:
            self._reply(turn, res.reply, res.note, kind=res.kind,
                        confirmation=res.confirmation)
            return self.send("/done")
        if res.wants_build:
            self._reply(turn, res.reply, res.note, kind=res.kind,
                        confirmation=res.confirmation)
            focus = module_focus.get_focus(self.state)
            if res.build_scope:
                normalized = normalize_phase(res.build_scope)
                if normalized:
                    return self._app_phase_build(normalized, turn)
            if focus is not None:
                return self._app_module_scope_build(focus, turn)
            self._resolve_patterns()
            nxt = next_unbuilt_phase(
                self.state.get("patterns") or [],
                self.state.get("built_phases") or [],
            )
            if nxt:
                return self._app_phase_build(nxt, turn)
            return self._build_note(
                turn, "Everything configured is already built — say "
                "you're done to assemble the full project.",
            )

        return self._reply(
            turn, res.reply, res.note, kind=res.kind,
            new_patterns=res.new_patterns, confirmation=res.confirmation,
        )
