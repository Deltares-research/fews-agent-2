"""Blueprint-driven project builder.

Given a project blueprint (``project.yaml``) and the pattern library,
this runner expands every pattern instance into XML files, writes them
to the output tree, and reports per-file XSD-validation status. Single
command, zero prompts.

Usage::

    python -m runners.agent.build_from_blueprint \\
        --blueprint examples/blueprints/eccc-nwp-demo/project.yaml

    # Compare against tutorial for byte-equivalence diagnostics:
    python -m runners.agent.build_from_blueprint \\
        --blueprint examples/blueprints/eccc-nwp-demo/project.yaml \\
        --diff-against examples/config-tutorial
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from fews_agent.agent.blueprint import expand, load_blueprint, write_output
from fews_agent.generators.base import canonicalize
from fews_agent.validation import validate_xsd

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PATTERN_ROOT = REPO_ROOT / "patterns"


def build_from_blueprint(
    blueprint_path: Path,
    pattern_root: Path,
    *,
    diff_against: Path | None = None,
    console: Console | None = None,
) -> dict:
    if console is None:
        console = Console()

    bp = load_blueprint(blueprint_path, pattern_root)
    output_root = (blueprint_path.parent / bp.output_root).resolve()
    output_root.mkdir(parents=True, exist_ok=True)

    console.print(Panel(
        f"[bold]Blueprint:[/bold] {bp.name}\n"
        f"[dim]source: {blueprint_path}[/dim]\n"
        f"[dim]output: {output_root}[/dim]\n"
        f"[bold]{len(bp.patterns)}[/bold] pattern(s), "
        f"[bold]{sum(len(p.instances) for p in bp.patterns)}[/bold] "
        f"instance(s)",
        border_style="cyan",
    ))

    result = expand(bp, pattern_root)
    if result.errors:
        for err in result.errors:
            console.print(f"[red]error:[/red] {err}")
        return {"ok": False, "errors": result.errors}

    manifest = write_output(result, output_root)

    # Per-file validation table.
    table = Table(
        title=f"Generated files ({len(manifest['written'])})",
        show_lines=False,
    )
    table.add_column("file", overflow="fold")
    table.add_column("pattern")
    table.add_column("instance")
    table.add_column("xsd", justify="center")
    if diff_against is not None:
        table.add_column("vs tutorial", justify="center")

    n_xsd_ok = 0
    n_byte_eq = 0
    n_compared = 0
    files_report = []
    for entry in manifest["written"]:
        file_path = output_root / entry["path"]
        data = file_path.read_bytes()
        xsd_ok, xsd_msg = validate_xsd(data)
        if xsd_ok:
            n_xsd_ok += 1
        row = [
            entry["path"],
            entry["pattern"].split("/")[-1],
            entry["instance"],
            "[green]OK[/green]" if xsd_ok else "[red]FAIL[/red]",
        ]
        report_entry = {
            "path": entry["path"],
            "xsd_ok": xsd_ok,
            "xsd_msg": xsd_msg,
        }
        if diff_against is not None:
            tutorial_path = diff_against / entry["path"]
            if tutorial_path.is_file():
                n_compared += 1
                try:
                    eq = canonicalize(data) == canonicalize(tutorial_path.read_bytes())
                except Exception:
                    eq = False
                if eq:
                    n_byte_eq += 1
                    row.append("[green]match[/green]")
                else:
                    row.append("[red]drift[/red]")
                report_entry["byte_equivalent"] = eq
            else:
                row.append("[dim]—[/dim]")
                report_entry["byte_equivalent"] = None
        table.add_row(*row)
        files_report.append(report_entry)

    console.print(table)

    summary_lines = [
        f"[bold]Files generated:[/bold] {len(manifest['written'])}",
        f"[bold]XSD-valid:[/bold] {n_xsd_ok}/{len(manifest['written'])}",
        f"[bold]Pattern contributions:[/bold] "
        f"{len(manifest['contributions'])} (singletons not yet merged)",
    ]
    if diff_against is not None:
        summary_lines.append(
            f"[bold]Byte-equivalent vs tutorial:[/bold] {n_byte_eq}/{n_compared}"
        )
    border = (
        "green" if n_xsd_ok == len(manifest["written"]) else "yellow"
    )
    console.print(Panel(
        "\n".join(summary_lines), title="Build complete", border_style=border,
    ))

    summary = {
        "ok": n_xsd_ok == len(manifest["written"]),
        "blueprint": bp.name,
        "output_root": str(output_root),
        "files_total": len(manifest["written"]),
        "files_xsd_ok": n_xsd_ok,
        "byte_equivalent_vs_tutorial": (
            f"{n_byte_eq}/{n_compared}" if diff_against else None
        ),
        "files": files_report,
        "contributions": manifest["contributions"],
    }
    summary_path = output_root / "summary.json"
    summary_path.write_text(
        json.dumps(summary, indent=2, default=str), encoding="utf-8"
    )
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--blueprint", required=True)
    parser.add_argument(
        "--pattern-root",
        default=str(DEFAULT_PATTERN_ROOT),
        help="Root of the pattern library (default: patterns/).",
    )
    parser.add_argument(
        "--diff-against",
        default=None,
        help="Optional dir to compare against (e.g. examples/config-tutorial).",
    )
    args = parser.parse_args(argv)

    summary = build_from_blueprint(
        blueprint_path=Path(args.blueprint).resolve(),
        pattern_root=Path(args.pattern_root).resolve(),
        diff_against=Path(args.diff_against).resolve() if args.diff_against else None,
    )

    return 0 if summary.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
