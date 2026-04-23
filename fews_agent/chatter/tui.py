"""Rich terminal UI for the FEWS agent.

Entry point for `fews-agent` (see [project.scripts] in pyproject.toml).

Layout is menu-driven rather than split-pane so it works in any
terminal size and doesn't require alt-screen redraws:

  Header (always visible): project · spec · progress summary
  Menu (Prompt.ask with choices):
    chat      — LLM-driven conversation (`/back` to return)
    wizard    — thematic step-through of the current spec
    state     — table view of project data + progress
    generate  — render + XSD validate + preview XML
    quit

Cache-authoritative state: project_data reloads from disk at the top of
every menu cycle, so a wizard-driven change is visible to the chat
(and vice versa) without any in-memory plumbing.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

# secrets/.env lives at the repo root, two levels above this file
# (fews_agent/chatter/tui.py). Resolving explicitly means `fews-agent` works
# from any cwd, not just the repo root.
_ENV_PATH = Path(__file__).resolve().parents[2] / "secrets" / ".env"
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm, Prompt
from rich.syntax import Syntax
from rich.table import Table
from rich.text import Text

from ..agent import (
    AgentLoop,
    ProjectStore,
    compute_progress,
    default_model,
    get_provider,
)
from ..agent.tools.generate_tool import generate as generate_tool_fn
from ..agent.wizard import run_wizard

_MENU = ["chat", "wizard", "state", "generate", "quit"]
_SPEC_SLICE1 = "locations"


def _header(console: Console, loop: AgentLoop) -> None:
    data = loop.project_data()
    prog = compute_progress(loop.spec_name, data)
    file_missing = prog.file_level_missing
    item_count = prog.item_count
    incomplete = sum(1 for p in prog.per_item if not p.complete)
    status_bits = [
        f"[bold]{loop.project_name}[/bold]",
        f"spec=[cyan]{loop.spec_name}[/cyan]",
        f"model=[dim]{loop.provider.model}[/dim]",
        f"{item_count} item(s)"
        + (f", [yellow]{incomplete} incomplete[/yellow]" if incomplete else ""),
    ]
    if file_missing:
        status_bits.append(f"[red]missing file-level: {', '.join(file_missing)}[/red]")
    console.rule(" · ".join(status_bits))


def _choose_project(console: Console, store: ProjectStore) -> str:
    existing = store.list()
    if existing:
        console.print(
            Panel(
                "Existing projects:\n  " + "\n  ".join(existing) + "\n\n"
                "Type a name to load, or a new name to start fresh.",
                title="Project",
                border_style="cyan",
            )
        )
    else:
        console.print(
            Panel("No existing projects. Type a name for a new one.",
                  title="Project", border_style="cyan")
        )
    while True:
        name = Prompt.ask("Project name").strip()
        if name:
            if not store.exists(name):
                store.save(name, {})
                console.print(f"[green]✓[/green] Created project [bold]{name}[/bold].")
            return name


def _choose_provider(console: Console) -> tuple[str, str]:
    provider_default = os.environ.get("FEWS_AGENT_PROVIDER", "ollama").lower()
    provider = Prompt.ask(
        "Provider",
        choices=["ollama", "anthropic"],
        default=provider_default,
    )
    model_default = os.environ.get("FEWS_AGENT_MODEL", default_model(provider))
    model = Prompt.ask("Model", default=model_default).strip()
    return provider, model


def _run_chat(console: Console, loop: AgentLoop) -> None:
    console.print(Panel(
        "Chat mode — describe what you want and I'll call the tools.\n"
        "[dim]Commands: /back (menu), /help[/dim]",
        border_style="green",
    ))
    while True:
        try:
            user = Prompt.ask("[bold green]you[/bold green]").strip()
        except (EOFError, KeyboardInterrupt):
            console.print()
            return
        if not user:
            continue
        low = user.lower()
        if low in {"/back", "/exit", "/quit"}:
            return
        if low == "/help":
            console.print(
                "[dim]Just ask the assistant what to do. "
                "Example: 'Add a location STN_LON at 51.5074, -0.0877'.[/dim]"
            )
            continue
        try:
            reply = loop.turn(user)
        except Exception as exc:
            console.print(f"[red]provider error: {type(exc).__name__}: {exc}[/red]")
            continue
        console.print(Panel(reply or "[dim](no text)[/dim]",
                            title="assistant", border_style="blue"))


def _state_view(console: Console, loop: AgentLoop) -> None:
    data = loop.project_data()
    prog = compute_progress(loop.spec_name, data)

    meta = Table(title="Project metadata", show_header=False, box=None, padding=(0, 2))
    meta.add_row("Project", loop.project_name)
    meta.add_row("Spec", loop.spec_name)
    meta.add_row("Provider", loop.provider.model)
    meta.add_row("Storage", str(loop.store.path_for(loop.project_name)))
    locations = data.get("locations", {}) if isinstance(data, dict) else {}
    meta.add_row("geoDatum", locations.get("geoDatum", "[red](missing)[/red]"))
    meta.add_row(
        "Fully complete",
        "[green]yes[/green]" if prog.fully_complete else "[yellow]no[/yellow]",
    )
    console.print(meta)

    items = locations.get("location", []) if isinstance(locations, dict) else []
    if not items:
        console.print("[dim]No locations yet.[/dim]")
        return
    t = Table(title="Locations", show_lines=False)
    for col in ("id", "name", "x", "y", "z", "parent", "status"):
        t.add_column(col)
    by_index = {p.index: p for p in prog.per_item}
    for i, loc in enumerate(items):
        progress = by_index.get(i)
        status = Text("complete", style="green") if progress and progress.complete else Text(
            f"missing: {', '.join(progress.missing)}" if progress else "unknown",
            style="yellow",
        )
        t.add_row(
            str(loc.get("id", "")),
            str(loc.get("name", "")),
            str(loc.get("x", "")),
            str(loc.get("y", "")),
            str(loc.get("z", "")),
            str(loc.get("parentLocationId", "")),
            status,
        )
    console.print(t)


def _run_generate(console: Console, loop: AgentLoop) -> None:
    data = loop.project_data()
    params = data.get("locations")
    if not params:
        console.print("[yellow]Nothing to generate yet — add at least one location.[/yellow]")
        return
    result = generate_tool_fn(name=loop.spec_name, params=params, ctx=loop.ctx)
    if "error" in result:
        console.print(f"[red]{result['error']}[/red]")
        return
    if "validation_errors" in result:
        console.print("[red]Pydantic rejected the current inputs:[/red]")
        for err in result["validation_errors"]:
            console.print(f"  - {err.get('loc')}: {err.get('msg')}")
        return
    xml = result.get("xml", "")
    xsd_ok = result.get("xsd_ok")
    xsd_msg = result.get("xsd_msg", "")
    header = (
        "[green]✓[/green] "
        if xsd_ok
        else "[red]✘[/red] "
    ) + f"XSD: {xsd_msg}"
    console.print(header)
    console.print(Syntax(xml, "xml", theme="monokai", line_numbers=False, word_wrap=False))
    out_path = loop.store.write_artifact(
        loop.project_name, result["output_relpath"], xml
    )
    console.print(f"[dim]wrote {out_path}[/dim]")


def main(argv: list[str] | None = None) -> int:
    load_dotenv(_ENV_PATH)
    console = Console()
    console.print(Panel.fit(
        "[bold]FEWS agent[/bold] — conversational FEWS XML authoring\n"
        "[dim]slice 1: locations[/dim]",
        border_style="magenta",
    ))

    store = ProjectStore()
    project = _choose_project(console, store)
    provider_name, model = _choose_provider(console)
    try:
        provider = get_provider(provider_name, model)
    except Exception as exc:
        console.print(f"[red]provider init failed: {exc}[/red]")
        return 1
    loop = AgentLoop(
        provider=provider, store=store, project_name=project, spec_name=_SPEC_SLICE1
    )

    while True:
        loop.reload()
        _header(console, loop)
        choice = Prompt.ask(
            "menu", choices=_MENU, default="wizard"
        )
        if choice == "quit":
            if Confirm.ask("Quit?", default=True):
                console.print("[dim]bye.[/dim]")
                return 0
            continue
        if choice == "chat":
            _run_chat(console, loop)
        elif choice == "wizard":
            try:
                run_wizard(loop.spec_name, loop.ctx, console)
            except KeyboardInterrupt:
                console.print("\n[dim]wizard interrupted.[/dim]")
        elif choice == "state":
            _state_view(console, loop)
        elif choice == "generate":
            _run_generate(console, loop)


if __name__ == "__main__":
    sys.exit(main())
