"""Interactive project builder: pick specs → walk the wizard → generate.

This is the user-facing entry point that turns the wizard architecture
into an actual project-creation flow. Unlike ``replay.py`` (regression
runner with scripted answers), this drives the wizard from real
keyboard input — every ``Prompt.ask`` reaches the user, and the LLM
parser is consulted for each section's bulk reply.

Flow::

    1. Resolve project name (--project-name or interactive prompt).
    2. Pick specs (--specs / --specs-from / interactive picker).
    3. For each picked spec:
         - banner showing "phase N/M: <spec>"
         - run_wizard(...) — file-level setters, section bulks
         - generate_tool.generate(...) — emits XML to the workspace
    4. Walk the workspace's generated/ tree, copy to the run-dir,
       XSD-validate each file, and (optionally) compare against a
       fixture root.
    5. Write events.jsonl + summary.json + report.md.

Cross-phase reuse, section-level bulk-ask + chunking, and the LLM
parser fallback are all inherited from the wizard — no extra wiring.

Usage::

    python -m runners.agent.build_project --project-name my_project
    python -m runners.agent.build_project --specs essentials --quiet
    python -m runners.agent.build_project --provider anthropic --model claude-sonnet-4-6
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm, Prompt
from rich.table import Table

from fews_agent.agent.providers.factory import get_provider
from fews_agent.agent.tools import ToolContext, generate_tool
from fews_agent.agent.wizard import run_wizard
from fews_agent.agent.wizard_picker import (
    PRESETS,
    categorize_specs,
    expand_selection,
    pick_specs_interactive,
)
from fews_agent.db import ProjectStore
from fews_agent.generators.base import canonicalize
from fews_agent.validation import validate_xsd

from .replay import EventLog, Progress, _short

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT_ROOT = REPO_ROOT / "validation"

# Project names land in directory paths and JSON keys; keep it tame.
_PROJECT_NAME_RE = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_\-]*$")


def _resolve_project_name(cli_value: str | None, console: Console) -> str:
    """Return a sanitised project name, prompting if not provided."""
    name = cli_value
    while True:
        if not name:
            name = Prompt.ask("[bold]Project name[/bold]", default="my_project")
        name = (name or "").strip()
        if _PROJECT_NAME_RE.match(name):
            return name
        console.print(
            "[red]Project name must be alphanumeric / underscore / hyphen "
            "and start with a letter or digit.[/red]"
        )
        name = ""


def _resolve_selection(
    args: argparse.Namespace, console: Console
) -> list[str]:
    """Return the chosen spec name list."""
    rows = categorize_specs()

    spec_text = ""
    if args.specs:
        spec_text = args.specs
    if args.specs_from:
        if args.specs_from == "-":
            src = sys.stdin.read()
        else:
            src = Path(args.specs_from).read_text(encoding="utf-8")
        spec_text = (spec_text + "\n" + src).strip(", \n")

    if spec_text:
        chosen, unknown = expand_selection(spec_text, rows, PRESETS)
        if unknown:
            console.print(
                f"[yellow]Ignored unknown tokens: {', '.join(unknown)}[/yellow]"
            )
        return chosen

    return pick_specs_interactive(rows=rows, console=console)


def _validate_artifacts(
    workspace_generated: Path,
    run_dir: Path,
    fixture_root: Path | None,
) -> list[dict[str, Any]]:
    """Walk generated/, copy to the run dir, XSD-validate, optional fixture diff.

    Mirrors the validation block in ``replay.replay`` so build_project
    produces the same per-file report shape — keeps the report.md
    rendering identical.
    """
    files_report: list[dict[str, Any]] = []
    if not workspace_generated.exists():
        return files_report
    for src in sorted(workspace_generated.rglob("*.xml")):
        relpath = src.relative_to(workspace_generated)
        dst = run_dir / "generated" / relpath
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes(src.read_bytes())

        data = src.read_bytes()
        xsd_ok, xsd_msg = validate_xsd(data)
        byte_equivalent: bool | None = None
        fixture_present = False
        if fixture_root is not None:
            fixture = fixture_root / relpath
            fixture_present = fixture.is_file()
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
    return files_report


def _print_summary_table(
    files_report: list[dict[str, Any]], console: Console
) -> None:
    """Render a compact per-file table."""
    if not files_report:
        console.print("[yellow]No XML produced.[/yellow]")
        return
    table = Table(title=f"Generated files ({len(files_report)})", show_lines=False)
    table.add_column("path", overflow="fold")
    table.add_column("xsd", justify="center")
    table.add_column("fixture", justify="center")
    for r in files_report:
        xsd = "[green]OK[/green]" if r["xsd_ok"] else "[red]FAIL[/red]"
        if r["byte_equivalent"] is True:
            fix = "[green]match[/green]"
        elif r["byte_equivalent"] is False:
            fix = "[red]drift[/red]"
        else:
            fix = "[dim]—[/dim]"
        table.add_row(r["relpath"], xsd, fix)
    console.print(table)


def build_project(
    project_name: str,
    specs: list[str],
    run_dir: Path,
    *,
    provider_name: str | None = None,
    model: str | None = None,
    fixture_root: Path | None = None,
    progress: Progress | None = None,
    console: Console | None = None,
    fresh: bool = True,
) -> dict[str, Any]:
    """Drive the wizard for each spec interactively. Returns a summary."""
    if progress is None:
        progress = Progress(project_name, enabled=False)
    if console is None:
        console = Console()
    os.environ["FEWS_AGENT_ALL_SPECS"] = "1"

    run_dir.mkdir(parents=True, exist_ok=True)
    log_path = run_dir / "events.jsonl"
    summary_path = run_dir / "summary.json"

    store_home = run_dir / "_workspace"
    store = ProjectStore(home=store_home)

    proj_dir = store.path_for(project_name)
    if fresh and proj_dir.exists():
        shutil.rmtree(proj_dir)

    inner_provider = get_provider(provider_name, model)
    log = EventLog(log_path)
    log.emit(
        "session_start",
        project=project_name,
        provider=type(inner_provider).__name__,
        model=getattr(inner_provider, "model", "?"),
        specs=specs,
        n_specs=len(specs),
    )
    progress.line(
        f"session_start: provider={type(inner_provider).__name__} "
        f"model={getattr(inner_provider, 'model', '?')} specs={len(specs)}"
    )

    parser_state = {"calls": 0, "prompt": 0, "completion": 0, "errors": 0}

    def _make_on_parse(label: str):
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
                phase=label,
                n_values=len(parsed.values),
                extracted=list(parsed.values.keys()),
                error=parsed.error,
                **(parsed.usage or {}),
            )
        return _on_parse

    for idx, spec_name in enumerate(specs, start=1):
        console.print(Panel(
            f"[bold]Phase {idx}/{len(specs)}: {spec_name}[/bold]",
            border_style="green",
        ))
        log.emit("phase_start", phase=spec_name, spec=spec_name, index=idx)
        progress.line(f"phase {idx}/{len(specs)}: {spec_name}")

        ctx = ToolContext(
            store=store,
            project_name=project_name,
            spec_name=spec_name,
            project_data=store.load(project_name),
        )

        try:
            run_wizard(
                spec_name,
                ctx,
                console,
                provider=inner_provider,
                on_parse=_make_on_parse(spec_name),
            )
        except KeyboardInterrupt:
            console.print("\n[yellow]Interrupted by user.[/yellow]")
            log.emit("interrupted", phase=spec_name)
            return _summary(
                project_name, log_path, log.events, ok=False,
                error="interrupted",
            )
        except Exception as exc:  # noqa: BLE001
            log.emit(
                "error", phase=spec_name, error=f"{type(exc).__name__}: {exc}"
            )
            console.print(f"[red]Wizard error in {spec_name}: {exc}[/red]")
            continue

        gen_result = generate_tool.generate(name=spec_name, ctx=ctx)
        log.emit(
            "generate",
            phase=spec_name,
            spec=spec_name,
            result={
                **{k: v for k, v in gen_result.items() if k != "xml"},
                "xml": _short(gen_result.get("xml", ""), 240),
            },
        )
        if "error" in gen_result or "validation_errors" in gen_result:
            console.print(
                f"[red]✗ {spec_name} failed to generate.[/red] "
                f"{gen_result.get('error') or gen_result.get('validation_errors')}"
            )
            log.emit(
                "phase_failed", phase=spec_name, spec=spec_name,
                result=gen_result,
            )
            continue
        rel = gen_result.get("output_relpath", "?")
        console.print(f"[green]✓[/green] {spec_name} → {rel}")
        log.emit("phase_done", phase=spec_name, spec=spec_name)

    workspace_generated = store.path_for(project_name) / "generated"
    files_report = _validate_artifacts(
        workspace_generated, run_dir, fixture_root
    )
    n_total = len(files_report)
    n_xsd = sum(1 for r in files_report if r["xsd_ok"])
    n_fix = sum(1 for r in files_report if r["fixture_present"])
    n_match = sum(
        1 for r in files_report if r["fixture_present"] and r["byte_equivalent"]
    )
    overall_ok = n_total > 0 and n_xsd == n_total and all(
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

    _print_summary_table(files_report, console)
    progress.line(
        f"validation: {n_xsd}/{n_total} XSD-valid"
        + (f", {n_match}/{n_fix} byte-equivalent" if n_fix else "")
    )

    parser_total = parser_state["prompt"] + parser_state["completion"]
    progress.line(
        f"parser totals: {parser_state['calls']} call(s), "
        f"{parser_total:,} tokens ({parser_state['errors']} parse error(s))"
    )

    summary = _summary(
        project_name,
        log_path,
        log.events,
        ok=overall_ok,
        files=files_report,
        files_total=n_total,
        files_xsd_ok=n_xsd,
        files_with_fixture=n_fix,
        files_byte_equivalent=n_match,
        run_dir=str(run_dir),
        n_specs=len(specs),
        parser_calls=parser_state["calls"],
        parser_errors=parser_state["errors"],
        parser_prompt_tokens=parser_state["prompt"],
        parser_completion_tokens=parser_state["completion"],
        parser_total_tokens=parser_total,
    )
    summary_path.write_text(
        json.dumps(summary, indent=2, default=str), encoding="utf-8"
    )
    console.print(f"[dim]artifacts: {run_dir}[/dim]")
    return summary


def _summary(
    project: str,
    log_path: Path,
    events: list[dict[str, Any]],
    **extras: Any,
) -> dict[str, Any]:
    counts: dict[str, int] = {}
    for e in events:
        counts[e["type"]] = counts.get(e["type"], 0) + 1
    return {
        "project": project,
        "log": str(log_path),
        "event_counts": counts,
        **extras,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--project-name", default=None)
    parser.add_argument(
        "--specs",
        default=None,
        help="Comma-separated mix of preset names (essentials, minimal), "
        "category names (region, module, ...), or exact spec names. "
        "Skip to use the interactive picker.",
    )
    parser.add_argument(
        "--specs-from",
        default=None,
        help="Read specs from a file (one per line) or '-' for stdin.",
    )
    parser.add_argument("--provider", default=None, help="ollama | anthropic")
    parser.add_argument("--model", default=None, help="provider-specific model id")
    parser.add_argument(
        "--output-root",
        default=str(DEFAULT_OUTPUT_ROOT),
        help="Where each run writes <project>/<timestamp>/ (default: validation/).",
    )
    parser.add_argument(
        "--fixture-root",
        default=None,
        help="Optional fixture dir for byte-equivalence comparisons.",
    )
    parser.add_argument(
        "--no-confirm",
        action="store_true",
        help="Skip the post-pick 'walk N specs?' confirm.",
    )
    parser.add_argument("--quiet", "-q", action="store_true")
    parser.add_argument(
        "--no-markdown",
        action="store_true",
        help="Skip the post-run Markdown report render.",
    )
    args = parser.parse_args(argv)

    console = Console()
    project_name = _resolve_project_name(args.project_name, console)
    chosen = _resolve_selection(args, console)
    if not chosen:
        console.print("[yellow]Nothing selected; exiting.[/yellow]")
        return 1

    if not args.no_confirm and not (args.specs or args.specs_from):
        if not Confirm.ask(
            f"Walk the wizard for {len(chosen)} spec(s)?", default=True
        ):
            return 1

    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    run_dir = Path(args.output_root) / project_name / timestamp
    fixture_root = Path(args.fixture_root) if args.fixture_root else None
    progress = Progress(project_name, enabled=not args.quiet)

    summary = build_project(
        project_name,
        chosen,
        run_dir,
        provider_name=args.provider,
        model=args.model,
        fixture_root=fixture_root,
        progress=progress,
        console=console,
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

    return 0 if summary.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
