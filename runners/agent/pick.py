"""Interactive wizard-spec picker.

Run me to scope a project: I show every wizard-driveable spec grouped
by FEWS config category, accept a comma-separated mix of presets /
categories / exact spec names, and print the resolved selection.

Usage::

    python -m runners.agent.pick
    python -m runners.agent.pick --select essentials,filters
    python -m runners.agent.pick --out /tmp/picked.txt

The picker has no LLM dependency. The chosen list is suitable as
input to ``replay.py --specs ...`` (forthcoming) or any future
``build_project.py`` runner.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from rich.console import Console

from fews_agent.agent.wizard_picker import (
    PRESETS,
    categorize_specs,
    expand_selection,
    pick_specs_interactive,
    render_summary,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--select",
        default=None,
        help="Non-interactive mode: comma-separated mix of presets / "
        "categories / exact spec names. Example: 'essentials,filters'.",
    )
    parser.add_argument(
        "--out",
        default=None,
        help="Write the chosen list to this path (one per line). "
        "Stdout still prints a comma-separated form.",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="Just print the categorised registry and exit.",
    )
    args = parser.parse_args(argv)

    console = Console(stderr=True)  # status to stderr; result on stdout
    rows = categorize_specs()

    if args.list:
        render_summary(rows, console)
        return 0

    if args.select:
        chosen, unknown = expand_selection(args.select, rows, PRESETS)
        if unknown:
            console.print(
                f"[yellow]Ignored unknown tokens: "
                f"{', '.join(unknown)}[/yellow]"
            )
        if not chosen:
            console.print("[red]Nothing matched.[/red]")
            return 2
    else:
        chosen = pick_specs_interactive(rows=rows, console=console)
        if not chosen:
            return 1

    # Result on stdout — pipeable.
    print(",".join(chosen))

    if args.out:
        Path(args.out).write_text(
            "\n".join(chosen) + "\n", encoding="utf-8"
        )
        console.print(f"[green]Wrote {len(chosen)} names to {args.out}[/green]")
    return 0


if __name__ == "__main__":
    sys.exit(main())
