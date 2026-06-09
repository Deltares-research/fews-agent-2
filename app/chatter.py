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
    ENGLISH_WORD_BLOCKLIST,
    INTENTS,
    build_status_report,
    classify_intent,
    compose_help_reply,
    compose_reply,
    compose_status_reply,
    compute_input_status,
    detect_help_query,
    detect_status_query,
    extract_skills,
    heuristic_intent_from_slots,
    is_intent_ready,
    next_unfilled_question,
    scan_inputs,
    status_prose_fallback,
)
from fews_agent.agent.providers.factory import get_provider
from runners.agent.build_from_blueprint import build_from_blueprint
from runners.agent.chat_step import _format_internals


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
PATTERNS_ROOT = REPO_ROOT / "patterns"
OUTPUT_ROOT = REPO_ROOT / "projects"
SESSIONS_ROOT = REPO_ROOT / "sessions"
DOCS_PATH = REPO_ROOT / "CLAUDE.md"


def _load_project_docs() -> str:
    """Read the project documentation used by the help meta intent.

    Cached per-process: CLAUDE.md is ~40KB / ~12K tokens; loading it
    once per process is fine, and it stays put across a session so
    Ollama's prefix caching can benefit consecutive help turns.
    """
    if not hasattr(_load_project_docs, "_cached"):
        try:
            _load_project_docs._cached = (
                DOCS_PATH.read_text(encoding="utf-8")
                if DOCS_PATH.is_file() else ""
            )
        except Exception:  # noqa: BLE001
            _load_project_docs._cached = ""
    return _load_project_docs._cached


def new_session_dir(username: str, root: Path = SESSIONS_ROOT) -> Path:
    """Create a fresh ``<username>_<YYYY-MM-DD_HHMMSS>/`` session folder."""
    dt = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    safe = "".join(c if (c.isalnum() or c in "-_.") else "_" for c in username)
    out = root / f"{safe}_{dt}"
    out.mkdir(parents=True, exist_ok=True)
    return out


def list_sessions(username: str | None = None, root: Path = SESSIONS_ROOT) -> list[Path]:
    """Return existing session folders, newest first.

    If ``username`` is provided, only sessions whose folder name starts with
    ``<username>_`` are returned.
    """
    if not root.is_dir():
        return []
    prefix = f"{username}_" if username else ""
    return sorted(
        (d for d in root.iterdir() if d.is_dir() and d.name.startswith(prefix)),
        reverse=True,
    )


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
      ``error``   — exception during turn processing
    """
    agent_message: str
    kind: str = "reply"
    internals: str | None = None
    warnings: list[str] = field(default_factory=list)
    ready: bool = False
    next_question: str | None = None
    new_patterns: list[str] = field(default_factory=list)
    project_yaml_path: Path | None = None
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
            import getpass
            session_dir = new_session_dir(username or getpass.getuser() or "user")
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
        intent = INTENTS.get(self.state.get("intent"))
        if not intent:
            return
        paths = {p.path for p in self.catalog}
        self.state["patterns"] = intent.resolver(self.state.get("slots", {}), paths)

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
            return summary, None
        except Exception as exc:  # noqa: BLE001
            self._logger.exception("build_from_blueprint crashed: %s", exc)
            tb = traceback.format_exc()
            # Keep the tail — full tracebacks are huge in the UI.
            tail = "\n".join(tb.splitlines()[-12:])
            return None, f"{type(exc).__name__}: {exc}\n\n{tail}"

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
                self.state.get("intent"), input_scan,
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
                skill_results={"status_query": True},
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

        # Phase 1: skills ------------------------------------------------------
        skill_results = extract_skills(message)

        # Phase 2: intent classification (only on first turn) ------------------
        notes: list[str] = []
        llm_picked: str | None = None
        llm_entities: dict | None = None
        if self.state.get("intent") is None:
            provider = get_provider(model=self.model)
            try:
                cls = classify_intent(message, skill_results, provider=provider)
                llm_picked = cls.get("intent")
                llm_entities = cls.get("entities", {}) or {}
                for k, v in llm_entities.items():
                    if k not in skill_results or skill_results[k] is None:
                        skill_results[k] = v
                        notes.append(f"LLM filled {k}={v}")
            except Exception as exc:  # noqa: BLE001
                notes.append(f"intent classify failed: {str(exc)[:60]}")

            chosen_intent = (
                llm_picked if llm_picked in INTENTS
                else heuristic_intent_from_slots(skill_results)
            )
            self.state["intent"] = chosen_intent
            if chosen_intent:
                notes.append(
                    f"intent: {chosen_intent}"
                    + ("" if llm_picked == chosen_intent else " (heuristic)")
                )
            else:
                notes.append("no intent classified")

        # Phase 3: slot filling (additive) -------------------------------------
        slots = self.state.setdefault("slots", {})
        for k, v in skill_results.items():
            if v is None or v == []:
                continue
            existing = slots.get(k)
            if isinstance(v, list):
                merged = list(existing or [])
                for item in v:
                    if isinstance(item, dict):
                        key = tuple(sorted(item.items()))
                        existing_keys = {
                            tuple(sorted(d.items())) for d in merged
                            if isinstance(d, dict)
                        }
                        if key not in existing_keys:
                            merged.append(item)
                    else:
                        if item not in merged:
                            merged.append(item)
                if merged != existing:
                    slots[k] = merged
                    notes.append(f"slot {k}={merged}")
            else:
                if existing is None:
                    slots[k] = v
                    notes.append(f"slot {k}={v}")

        if slots.get("geoDatum"):
            self.state.setdefault("singleton_seeds", {}).setdefault(
                "Locations", {}
            )["geoDatum"] = slots["geoDatum"]

        if (
            not slots.get("basins")
            and slots.get("basin_name")
            and slots.get("model_adapter")
        ):
            slots["basins"] = [{
                "basin_name": slots["basin_name"],
                "model_adapter": slots["model_adapter"],
            }]
            notes.append(f"derived basins={slots['basins']}")

        if slots.get("locations_source") == "csv":
            if "locations.csv" not in self.state.get("missing_data", []):
                self.state.setdefault("missing_data", []).append("locations.csv")

        # Phase 4: pattern resolution -----------------------------------------
        patterns_before = {p["pattern"] for p in self.state.get("patterns", [])}
        self._resolve_patterns()
        new_patterns = [
            p["pattern"] for p in self.state.get("patterns", [])
            if p["pattern"] not in patterns_before
        ]

        # Phase 4.25: warnings -------------------------------------------------
        warnings: list[str] = []
        mentioned_imports: set[str] = set()
        if llm_entities and isinstance(llm_entities.get("imports"), list):
            mentioned_imports.update(str(x) for x in llm_entities["imports"])
        if isinstance(slots.get("imports"), list):
            mentioned_imports.update(str(x) for x in slots["imports"])
        mapped_imports: set[str] = set()
        pattern_names_lower: set[str] = set()
        for p in self.state.get("patterns", []):
            pname = str(p.get("pattern", ""))
            pattern_names_lower.add(pname.lower())
            for inst in p.get("instances") or []:
                if not isinstance(inst, dict):
                    continue
                for k in ("nwp_name", "source_name", "wsc_variant",
                          "snow_source", "template_name"):
                    v = inst.get(k)
                    if isinstance(v, str):
                        mapped_imports.add(v)
        unmapped_imports = sorted(
            m for m in mentioned_imports - mapped_imports
            if not any(m.lower() in pn for pn in pattern_names_lower)
        )
        if unmapped_imports:
            warnings.append(
                "No pattern in the library for: "
                + ", ".join(unmapped_imports)
                + ". These would be silently skipped. Add a pattern under "
                  "patterns/auto/, or remove them from the request."
            )

        if isinstance(slots.get("basins"), list):
            suspicious = [
                b for b in slots["basins"]
                if isinstance(b, dict)
                and b.get("basin_name") in ENGLISH_WORD_BLOCKLIST
            ]
            if suspicious:
                names = ", ".join(b["basin_name"] for b in suspicious)
                warnings.append(
                    f"Detected '{names}' as a basin name, which looks like an "
                    f"English word, not a basin. Likely a regex false positive — "
                    f"confirm or correct before continuing."
                )

        self.state["warnings"] = warnings

        # Phase 4.5: inputs scan ----------------------------------------------
        inputs_dir = self.session_dir / "inputs"
        input_scan = scan_inputs(inputs_dir)
        input_status = compute_input_status(self.state.get("intent"), input_scan)

        # Suppress the missing-CSV / missing-yaml block from input_status
        # once it's been raised. Otherwise the LLM keeps asking about the
        # same files on every turn even when the user has acknowledged or
        # deferred ("later", "skip", "yes"). The configurator can upload
        # files via the sidebar at any time; we don't need to nag.
        if input_status:
            missing_now = sorted(
                set(input_status.get("csvs_required_missing") or [])
                | set(input_status.get("csvs_recommended_missing") or [])
            )
            already_raised = sorted(self.state.get("_inputs_nagged") or [])
            if missing_now and missing_now == already_raised:
                input_status = dict(input_status)
                input_status["csvs_required_missing"] = []
                input_status["csvs_recommended_missing"] = []
            elif missing_now:
                # First time this exact set is reported — let the LLM
                # mention it this turn, then snooze for future turns.
                self.state["_inputs_nagged"] = missing_now

        # Phase 5: compose reply ----------------------------------------------
        intent = INTENTS.get(self.state.get("intent") or "")
        next_q = next_unfilled_question(intent, slots) if intent else None
        ready = bool(intent) and is_intent_ready(intent, slots)
        provider = get_provider(model=self.model)
        agent_msg = compose_reply(
            user_message=message,
            state=self.state,
            intent=intent,
            slots=slots,
            notes=notes,
            next_question=next_q,
            is_ready=ready,
            new_patterns=new_patterns,
            input_status=input_status,
            warnings=warnings,
            provider=provider,
        )

        internals = _format_internals(
            skill_results=skill_results,
            llm_intent=llm_picked,
            llm_entities=llm_entities,
            chosen_intent=self.state.get("intent"),
            notes=notes,
            state=self.state,
            new_patterns=new_patterns,
            ready=ready,
            next_q=next_q,
            input_status=input_status,
            warnings=warnings,
        )
        self.history.append({"role": "agent", "message": agent_msg})
        self._append_md(turn, "agent", agent_msg, internals=internals)
        self._save()
        self._logger.info(
            "turn_end turn=%d intent=%s slots_filled=%d patterns=%d ready=%s warnings=%d",
            turn,
            self.state.get("intent"),
            sum(1 for v in slots.values() if v),
            len(self.state.get("patterns") or []),
            ready,
            len(warnings),
        )

        return TurnResult(
            agent_message=agent_msg,
            kind="reply",
            internals=internals,
            warnings=warnings,
            ready=ready,
            next_question=next_q,
            new_patterns=new_patterns,
        )
