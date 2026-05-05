"""Replay runner — drives the wizard with scripted natural-language answers.

The wizard owns the conversation flow: which fields to ask for, in what
order, when to confirm, when to add another. The runner just feeds it a
queue of pre-recorded user replies, intercepting ``rich.prompt.Prompt.ask``
and ``rich.prompt.Confirm.ask`` to return the next scripted answer
instead of reading stdin.

The LLM enters the picture only inside the wizard's bulk-ask step,
where ``nl_parser.parse_group`` translates the user's free-form reply
into structured field values. Failed parses fall back to per-field
prompts (which the script must also have answers for).

After the wizard returns, the runner calls ``generate_tool.generate``
to render every spec the project state can produce, then validates each
artifact against ``fixture_root/<output_relpath>``.

Usage::

    python -m runners.agent.replay --script tutorial
    python -m runners.agent.replay --script tutorial --provider anthropic
"""
from __future__ import annotations

import argparse
import importlib
import importlib.util
import json
import os
import shutil
import sys
import time
from collections import deque
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import rich.prompt
from rich.console import Console

from fews_agent.agent.providers.factory import get_provider
from fews_agent.agent.tools import ToolContext
from fews_agent.agent.tools import generate_tool
from fews_agent.agent.wizard import run_wizard
from fews_agent.db import ProjectStore
from fews_agent.generators import SPECS
from fews_agent.generators.base import canonicalize
from fews_agent.validation import validate_xsd

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_DIR = Path(__file__).parent / "scripts"
DEFAULT_VALIDATION_ROOT = REPO_ROOT / "validation"


# ---------------------------------------------------------------------------
# Script schema
# ---------------------------------------------------------------------------

@dataclass
class Phase:
    """One wizard run within a multi-phase project script.

    Each phase targets one spec and carries the natural-language
    answers the wizard will receive. All phases in a script share the
    same project state, so a later phase can reference ids set in an
    earlier one (e.g. `parameters` referencing `locations`).
    """

    spec_name: str
    answers: list[str]
    label: str = ""  # optional human-friendly tag for the report


@dataclass
class Script:
    """A scripted wizard replay — one or more phases against one project.

    Two compatible shapes:
      - ``phases: [{spec_name, answers}, ...]`` for project-style runs
        that walk multiple specs in one go.
      - ``spec_name + answers`` (legacy) for a single-phase script;
        treated as one-phase under the hood.
    """

    project_name: str
    phases: list[Phase]
    fixture_root: str = "examples/config-tutorial"
    description: str = ""

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Script:
        if "phases" in data:
            phases = [
                Phase(
                    spec_name=p["spec_name"],
                    answers=list(p["answers"]),
                    label=p.get("label", p.get("spec_name", "")),
                )
                for p in data["phases"]
            ]
        else:
            # Legacy single-phase script.
            phases = [
                Phase(
                    spec_name=data.get("spec_name", "locations"),
                    answers=list(data.get("answers", [])),
                    label=data.get("spec_name", "locations"),
                )
            ]
        return cls(
            project_name=data["project_name"],
            phases=phases,
            fixture_root=data.get("fixture_root", "examples/config-tutorial"),
            description=data.get("description", ""),
        )


def load_script(name_or_path: str) -> Script:
    p = Path(name_or_path)
    if p.is_file():
        spec = importlib.util.spec_from_file_location(
            f"_replay_script_{p.stem}", p
        )
        module = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
        assert spec.loader is not None
        spec.loader.exec_module(module)
    else:
        candidate = SCRIPTS_DIR / f"{name_or_path}.py"
        if not candidate.exists():
            raise FileNotFoundError(
                f"script {name_or_path!r} not found at {candidate}"
            )
        module = importlib.import_module(f"runners.agent.scripts.{name_or_path}")
    if not hasattr(module, "SCRIPT"):
        raise AttributeError(f"script module {module} has no SCRIPT attribute")
    return Script.from_dict(module.SCRIPT)


# ---------------------------------------------------------------------------
# Progress + JSONL log
# ---------------------------------------------------------------------------

class Progress:
    def __init__(self, project: str, *, enabled: bool = True, stream: Any = sys.stderr) -> None:
        self.project = project
        self.enabled = enabled
        self.stream = stream
        self._t0 = time.monotonic()

    def line(self, message: str) -> None:
        if not self.enabled:
            return
        ts = datetime.now().strftime("%H:%M:%S")
        elapsed = time.monotonic() - self._t0
        self.stream.write(f"[{ts}] [{self.project}] +{elapsed:5.1f}s  {message}\n")
        self.stream.flush()


class EventLog:
    def __init__(self, path: Path) -> None:
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("", encoding="utf-8")
        self.events: list[dict[str, Any]] = []

    def emit(self, type_: str, **payload: Any) -> None:
        evt = {"ts": time.time(), "type": type_, **payload}
        self.events.append(evt)
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(evt, ensure_ascii=False, default=str) + "\n")


# ---------------------------------------------------------------------------
# Rich monkey-patches: feed the answer queue
# ---------------------------------------------------------------------------

@dataclass
class _PatchHandles:
    queue: deque[str]
    log: EventLog
    progress: Progress
    _orig_ask: Any = None
    _orig_confirm: Any = None
    _patched: bool = False

    def install(self) -> None:
        if self._patched:
            return
        self._orig_ask = rich.prompt.Prompt.ask
        self._orig_confirm = rich.prompt.Confirm.ask

        def fake_ask(prompt="", *args, **kwargs):
            text = _strip_markup(prompt)
            if not self.queue:
                # Use the supplied default, or empty — running off the end
                # of the script is logged as a warning rather than fatal.
                default = kwargs.get("default", "")
                if default is ...:
                    default = ""
                self.log.emit(
                    "wizard_ask_underflow",
                    prompt=text,
                    used_default=str(default),
                )
                self.progress.line(
                    f"  ! script ran out of answers; defaulted to {default!r}"
                )
                return str(default) if default is not None else ""
            answer = self.queue.popleft()
            self.log.emit("wizard_ask", prompt=text, answer=answer)
            self.progress.line(f"  ask: {_short(text, 80)}  →  {_short(answer, 80)}")
            return answer

        def fake_confirm(prompt="", *args, **kwargs):
            text = _strip_markup(prompt)
            if not self.queue:
                self.log.emit(
                    "wizard_confirm_underflow", prompt=text, used_default=False
                )
                self.progress.line(
                    f"  ! script ran out of answers for confirm; defaulted to no"
                )
                return False
            answer = self.queue.popleft()
            normalized = answer.strip().lower()
            yes = normalized in {
                "y", "yes", "true", "1", "ok", "sure", "yeah", "yep",
                "add another", "another", "more", "continue",
            }
            no = normalized in {
                "n", "no", "false", "0", "stop", "done", "no more",
                "that's all", "thats all", "finish",
            }
            value = True if yes else False if no else False
            self.log.emit(
                "wizard_confirm",
                prompt=text,
                answer=answer,
                resolved=value,
            )
            self.progress.line(
                f"  confirm: {_short(text, 80)}  →  {answer!r} ({'yes' if value else 'no'})"
            )
            return value

        # ``Prompt.ask`` and ``Confirm.ask`` are classmethods; wrapping
        # in ``classmethod`` keeps the binding consistent.
        rich.prompt.Prompt.ask = classmethod(lambda cls, *a, **kw: fake_ask(*a, **kw))
        rich.prompt.Confirm.ask = classmethod(lambda cls, *a, **kw: fake_confirm(*a, **kw))
        self._patched = True

    def uninstall(self) -> None:
        if not self._patched:
            return
        rich.prompt.Prompt.ask = self._orig_ask
        rich.prompt.Confirm.ask = self._orig_confirm
        self._patched = False


# ---------------------------------------------------------------------------
# Replay
# ---------------------------------------------------------------------------

def replay(
    script: Script,
    run_dir: Path,
    provider_name: str | None = None,
    model: str | None = None,
    fresh_project: bool = True,
    progress: Progress | None = None,
) -> dict[str, Any]:
    """Drive the wizard end-to-end with a scripted answer queue.

    Walks each phase in order: install the phase's answer queue, run
    the wizard for the phase's spec, generate the XML, accumulate
    validation. All phases share one project state and one event log.
    """
    if progress is None:
        progress = Progress(script.project_name, enabled=False)
    os.environ["FEWS_AGENT_ALL_SPECS"] = "1"

    run_dir.mkdir(parents=True, exist_ok=True)
    log_path = run_dir / "events.jsonl"
    summary_path = run_dir / "summary.json"

    store_home = run_dir / "_workspace"
    store = ProjectStore(home=store_home)

    inner_provider = get_provider(provider_name, model)

    proj_dir = store.path_for(script.project_name)
    if fresh_project and proj_dir.exists():
        shutil.rmtree(proj_dir)

    log = EventLog(log_path)
    log.emit(
        "session_start",
        project=script.project_name,
        fixture_root=script.fixture_root,
        provider=type(inner_provider).__name__,
        model=getattr(inner_provider, "model", "?"),
        description=script.description,
        n_phases=len(script.phases),
        phases=[{"spec_name": p.spec_name, "label": p.label,
                 "answers": len(p.answers)} for p in script.phases],
    )
    progress.line(
        f"session_start: provider={type(inner_provider).__name__} "
        f"model={getattr(inner_provider, 'model', '?')} "
        f"phases={len(script.phases)} "
        f"answers_total={sum(len(p.answers) for p in script.phases)}"
    )

    console = Console(quiet=True)  # suppress wizard's own noise

    # Per-project running totals (sum across all phases).
    parser_state = {"calls": 0, "prompt": 0, "completion": 0, "errors": 0}

    def _make_on_parse(phase_label: str):
        """Return an on_parse callback bound to the current phase label."""
        def _on_parse(parsed: Any) -> None:
            parser_state["calls"] += 1
            if parsed.usage:
                parser_state["prompt"] += int(parsed.usage.get("prompt_tokens", 0))
                parser_state["completion"] += int(
                    parsed.usage.get("completion_tokens", 0)
                )
            if parsed.error:
                parser_state["errors"] += 1
            log.emit(
                "parser_call",
                phase=phase_label,
                n_values=len(parsed.values),
                extracted=list(parsed.values.keys()),
                error=parsed.error,
                **(parsed.usage or {}),
            )
            if parsed.usage:
                progress.line(
                    f"  parser: extracted {len(parsed.values)} field(s) "
                    f"({parsed.usage.get('total_tokens', 0):,} tokens)"
                )
            else:
                progress.line(
                    f"  parser: extracted {len(parsed.values)} field(s) "
                    f"(no usage reported)"
                )
        return _on_parse

    # Walk each phase: load fresh ctx so the wizard sees up-to-date
    # project state for that spec, install its answer queue, run, then
    # generate. Errors in one phase abort the project.
    for phase_idx, phase in enumerate(script.phases):
        log.emit(
            "phase_start",
            phase=phase.label,
            spec=phase.spec_name,
            answers_count=len(phase.answers),
            index=phase_idx,
        )
        progress.line(
            f"phase {phase_idx + 1}/{len(script.phases)}: {phase.label} "
            f"(spec={phase.spec_name}, {len(phase.answers)} answers)"
        )

        ctx = ToolContext(
            store=store,
            project_name=script.project_name,
            spec_name=phase.spec_name,
            project_data=store.load(script.project_name),
        )
        queue: deque[str] = deque(phase.answers)
        handles = _PatchHandles(queue=queue, log=log, progress=progress)
        handles.install()

        try:
            run_wizard(
                phase.spec_name,
                ctx,
                console,
                provider=inner_provider,
                on_parse=_make_on_parse(phase.label),
            )
        except Exception as exc:  # noqa: BLE001
            log.emit("error", phase=phase.label, error=f"{type(exc).__name__}: {exc}")
            progress.line(f"ERROR in phase {phase.label}: {exc}")
            handles.uninstall()
            return _summary(script, log_path, log.events, ok=False, error=str(exc))
        finally:
            handles.uninstall()

        if queue:
            log.emit(
                "answers_remaining",
                phase=phase.label,
                count=len(queue),
                unused=list(queue),
            )
            progress.line(
                f"  warning: {len(queue)} scripted answer(s) unused in "
                f"phase {phase.label}"
            )

        # Generate this phase's XML before moving on.
        progress.line(f"  generate({phase.spec_name})")
        gen_result = generate_tool.generate(name=phase.spec_name, ctx=ctx)
        log.emit(
            "generate",
            phase=phase.label,
            spec=phase.spec_name,
            result={
                **{k: v for k, v in gen_result.items() if k != "xml"},
                "xml": _short(gen_result.get("xml", ""), 240),
            },
        )
        if "error" in gen_result or "validation_errors" in gen_result:
            log.emit(
                "phase_failed",
                phase=phase.label,
                spec=phase.spec_name,
                result=gen_result,
            )
            progress.line(f"  generate failed in {phase.label}: {gen_result}")
            # Continue to next phase rather than abort — the user wants
            # to see the per-file table even when some specs fail.
            continue
        log.emit("phase_done", phase=phase.label, spec=phase.spec_name)

    # ------------------------------------------------------------------
    # Walk the workspace's generated/ tree and validate per file.
    # ------------------------------------------------------------------
    workspace_generated = store.path_for(script.project_name) / "generated"
    fixture_root = REPO_ROOT / script.fixture_root
    files_report: list[dict[str, Any]] = []
    if workspace_generated.exists():
        for src in sorted(workspace_generated.rglob("*.xml")):
            relpath = src.relative_to(workspace_generated)
            dst = run_dir / "generated" / relpath
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_bytes(src.read_bytes())

            data = src.read_bytes()
            xsd_ok, xsd_msg = validate_xsd(data)
            fixture = fixture_root / relpath
            fixture_present = fixture.is_file()
            byte_equivalent: bool | None = None
            if fixture_present:
                try:
                    byte_equivalent = (
                        canonicalize(data) == canonicalize(fixture.read_bytes())
                    )
                except Exception as exc:  # noqa: BLE001
                    byte_equivalent = False
                    xsd_msg = f"{xsd_msg}; canonicalize failed: {exc}"
            files_report.append(
                {
                    "relpath": str(relpath).replace("\\", "/"),
                    "xsd_ok": xsd_ok,
                    "xsd_msg": xsd_msg,
                    "fixture_present": fixture_present,
                    "byte_equivalent": byte_equivalent,
                }
            )

    if not files_report:
        log.emit("validation", ok=False, files=[], reason="no XML produced")
        return _summary(script, log_path, log.events, ok=False, error="no XML produced")

    n_total = len(files_report)
    n_xsd = sum(1 for r in files_report if r["xsd_ok"])
    n_fix = sum(1 for r in files_report if r["fixture_present"])
    n_match = sum(
        1 for r in files_report if r["fixture_present"] and r["byte_equivalent"]
    )
    overall_ok = n_xsd == n_total and all(
        (not r["fixture_present"]) or r["byte_equivalent"]
        for r in files_report
    )
    log.emit(
        "validation",
        ok=overall_ok,
        files=files_report,
        files_total=n_total,
        files_xsd_ok=n_xsd,
        files_with_fixture=n_fix,
        files_byte_equivalent=n_match,
    )
    progress.line(
        f"validation: {n_xsd}/{n_total} XSD-valid, {n_match}/{n_fix} byte-equivalent"
    )
    for r in files_report:
        gxsd = "OK" if r["xsd_ok"] else "FAIL"
        if r["byte_equivalent"] is True:
            gbyte = "match"
        elif r["byte_equivalent"] is False:
            gbyte = "DRIFT"
        else:
            gbyte = "no fixture"
        progress.line(f"  {r['relpath']}: xsd={gxsd} byte={gbyte}")

    progress.line(f"artifacts: {run_dir}")

    parser_total = parser_state["prompt"] + parser_state["completion"]
    progress.line(
        f"parser totals: {parser_state['calls']} call(s), "
        f"{parser_state['prompt']:,} prompt + {parser_state['completion']:,} "
        f"completion = {parser_total:,} tokens "
        f"({parser_state['errors']} parse error(s))"
    )

    summary = _summary(
        script,
        log_path,
        log.events,
        ok=overall_ok,
        files=files_report,
        files_total=n_total,
        files_xsd_ok=n_xsd,
        files_with_fixture=n_fix,
        files_byte_equivalent=n_match,
        run_dir=str(run_dir),
        # Sum unused answers reported by per-phase events so the
        # summary can flag scripts that ran short.
        answers_remaining=sum(
            int(e.get("count", 0))
            for e in log.events
            if e["type"] == "answers_remaining"
        ),
        n_phases=len(script.phases),
        parser_calls=parser_state["calls"],
        parser_errors=parser_state["errors"],
        parser_prompt_tokens=parser_state["prompt"],
        parser_completion_tokens=parser_state["completion"],
        parser_total_tokens=parser_total,
    )
    summary_path.write_text(
        json.dumps(summary, indent=2, default=str), encoding="utf-8"
    )
    return summary


def _summary(
    script: Script,
    log_path: Path,
    events: list[dict[str, Any]],
    **extras: Any,
) -> dict[str, Any]:
    counts: dict[str, int] = {}
    for e in events:
        counts[e["type"]] = counts.get(e["type"], 0) + 1
    return {
        "project": script.project_name,
        "log": str(log_path),
        "event_counts": counts,
        **extras,
    }


def _short(s: str, limit: int = 240) -> str:
    if len(s) <= limit:
        return s
    return s[:limit] + f"... <{len(s) - limit} more chars>"


def _strip_markup(text: str) -> str:
    """Strip Rich's [bold], [/bold] markup so logs are readable."""
    import re
    return re.sub(r"\[/?[a-zA-Z][^\]]*\]", "", str(text)).strip()


def _run_dir(validation_root: Path, project_name: str, timestamp: str) -> Path:
    return validation_root / project_name / timestamp


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--script", required=True, help="Script name or path.")
    parser.add_argument("--provider", default=None, help="ollama | anthropic")
    parser.add_argument("--model", default=None, help="provider-specific model id")
    parser.add_argument(
        "--validation-root",
        default=str(DEFAULT_VALIDATION_ROOT),
        help="Where each run writes <project>/<timestamp>/ (default: validation/).",
    )
    parser.add_argument("--quiet", "-q", action="store_true")
    parser.add_argument(
        "--no-markdown",
        action="store_true",
        help="Skip the post-replay Markdown render.",
    )
    parser.add_argument(
        "--max-phases",
        type=int,
        default=None,
        help="Run only the first N phases of the script (for piloting).",
    )
    parser.add_argument(
        "--phase-filter",
        default=None,
        help="Substring or comma-separated list — keep only phases whose "
        "spec_name matches.",
    )
    parser.add_argument(
        "--specs",
        default=None,
        help="Comma-separated list of EXACT spec names to keep (output "
        "of `python -m runners.agent.pick`). Safer than --phase-filter "
        "when names share substrings.",
    )
    parser.add_argument(
        "--specs-from",
        default=None,
        help="Read --specs values from a file (one per line; whitespace "
        "and blank lines ignored). Use '-' for stdin.",
    )
    args = parser.parse_args(argv)

    script = load_script(args.script)
    if args.specs or args.specs_from:
        spec_text = args.specs or ""
        if args.specs_from:
            if args.specs_from == "-":
                src = sys.stdin.read()
            else:
                src = Path(args.specs_from).read_text(encoding="utf-8")
            spec_text = (spec_text + "\n" + src).strip(", \n")
        wanted = {
            tok.strip()
            for tok in spec_text.replace("\n", ",").split(",")
            if tok.strip()
        }
        script.phases = [p for p in script.phases if p.spec_name in wanted]
    if args.phase_filter:
        terms = [t.strip().lower() for t in args.phase_filter.split(",") if t.strip()]
        script.phases = [
            p for p in script.phases
            if any(t in p.spec_name.lower() for t in terms)
        ]
    if args.max_phases is not None:
        script.phases = script.phases[: args.max_phases]
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    run_dir = _run_dir(Path(args.validation_root), script.project_name, timestamp)
    progress = Progress(script.project_name, enabled=not args.quiet)

    summary = replay(
        script,
        run_dir,
        provider_name=args.provider,
        model=args.model,
        progress=progress,
    )

    if not args.no_markdown:
        try:
            from .export_log import load_events, render

            md_path = run_dir / "report.md"
            md_path.write_text(
                render(load_events(run_dir / "events.jsonl")),
                encoding="utf-8",
            )
            progress.line(f"markdown: {md_path}")
        except Exception as exc:  # noqa: BLE001
            progress.line(f"markdown export failed: {exc}")

    print(json.dumps(summary, indent=2, default=str))
    return 0 if summary.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
