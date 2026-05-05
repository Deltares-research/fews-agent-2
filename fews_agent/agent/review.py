"""One-screen review UI for the CSV-first agent.

This is the *single* user interaction in the happy path: render the
ingestion summary, the anomalies, and the agent's proposals; ask one
"apply?" question. If the user says yes (and no proposal is of kind
``ask``), generation proceeds with zero further prompts.

The review module is presentation only — applying the proposals to
the project state lives in ``build_from_csvs.py``. This way the same
review render is reusable from a future web UI without dragging the
generator code along.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from rich.console import Console

from .initiative import AnalysisReport, Anomaly, Proposal


def render_report(report: AnalysisReport, console: Console) -> None:
    """Print the consolidated review screen."""
    from rich.panel import Panel
    from rich.table import Table

    # --- 1. CSV ingestion summary ---------------------------------------
    csv_table = Table(
        title="CSV ingestion",
        header_style="bold",
        show_lines=False,
    )
    csv_table.add_column("file", style="cyan")
    csv_table.add_column("spec", style="green")
    csv_table.add_column("rows", justify="right")
    csv_table.add_column("failed", justify="right")
    csv_table.add_column("notes", overflow="fold")

    if not report.csv_results:
        csv_table.add_row("(none)", "—", "—", "—", "no CSVs found in inputs dir")
    for key, r in report.csv_results.items():
        notes_parts: list[str] = []
        if r.unknown_headers:
            notes_parts.append(
                f"unknown cols: {', '.join(r.unknown_headers[:3])}"
            )
        if r.warnings:
            notes_parts.append(f"{len(r.warnings)} warning(s)")
        if r.errors and not r.model:
            notes_parts.append(f"PARSE FAILED: {r.errors[0][:60]}")
        spec_display = r.spec_name or "[red]?[/red]"
        csv_table.add_row(
            r.csv_path.name,
            spec_display,
            str(r.rows_parsed),
            str(r.rows_failed),
            "; ".join(notes_parts) or "[dim]ok[/dim]",
        )
    console.print(csv_table)

    # --- 2. Anomalies ---------------------------------------------------
    if report.anomalies:
        anomaly_table = Table(
            title=f"Anomalies ({len(report.anomalies)})",
            header_style="bold yellow",
        )
        anomaly_table.add_column("sev", style="bold")
        anomaly_table.add_column("spec")
        anomaly_table.add_column("issue", overflow="fold")
        anomaly_table.add_column("proposed fix", overflow="fold")
        for a in report.anomalies:
            sev_style = "red" if a.severity == "error" else "yellow"
            anomaly_table.add_row(
                f"[{sev_style}]{a.severity}[/{sev_style}]",
                a.spec_name,
                a.message,
                a.proposed_fix,
            )
        console.print(anomaly_table)

    # --- 3. Proposals ---------------------------------------------------
    if report.proposals:
        proposal_table = Table(
            title=f"Proposals ({len(report.proposals)})",
            header_style="bold",
        )
        proposal_table.add_column("#", style="dim", justify="right")
        proposal_table.add_column("kind", style="magenta")
        proposal_table.add_column("spec", style="cyan")
        proposal_table.add_column("proposal", overflow="fold")
        proposal_table.add_column("why", overflow="fold", style="dim")
        for i, p in enumerate(report.proposals, start=1):
            kind_style = _kind_color(p.kind)
            proposal_table.add_row(
                str(i),
                f"[{kind_style}]{p.kind}[/{kind_style}]",
                p.spec_name,
                p.summary,
                p.reasoning,
            )
        console.print(proposal_table)

    # --- 4. Unrecognised CSVs ------------------------------------------
    if report.unrecognised_csvs:
        bullets = "\n".join(f"  • {p}" for p in report.unrecognised_csvs)
        console.print(Panel(
            f"[yellow]Unrecognised CSVs (skipped):[/yellow]\n{bullets}\n"
            f"[dim]Filename must match one of: locations.csv, parameters.csv, "
            f"qualifiers.csv, thresholdWarningLevels.csv[/dim]",
            border_style="yellow",
        ))

    # --- 5. Footer summary ---------------------------------------------
    n_ok = sum(
        1 for r in report.csv_results.values()
        if r.spec_name and r.model is not None
    )
    n_specs = len(report.target_specs)
    summary_lines = [
        f"[bold]{n_ok}/{n_specs}[/bold] target specs covered by CSVs",
        f"[bold]{len(report.proposals)}[/bold] proposal(s) "
        f"[bold]{len(report.anomalies)}[/bold] anomaly(ies)",
    ]
    if report.needs_user_input:
        summary_lines.append(
            "[yellow]Some proposals need follow-up input "
            "(falling back to interactive prompts for those).[/yellow]"
        )
    else:
        summary_lines.append(
            "[green]All proposals are auto-applicable — one Y/N below "
            "completes the build.[/green]"
        )
    console.print(Panel(
        "\n".join(summary_lines),
        title="Summary",
        border_style="green" if not report.needs_user_input else "yellow",
    ))


def confirm_apply(report: AnalysisReport, console: Console) -> bool:
    """Single Y/N: apply all proposals and proceed with generation?"""
    from rich.prompt import Confirm
    return Confirm.ask(
        "[bold]Apply all proposals and generate XML?[/bold]",
        default=True,
        console=console,
    )


def _kind_color(kind: str) -> str:
    return {
        "auto_stub": "green",
        "default_skip": "blue",
        "file_field": "cyan",
        "ask": "yellow",
    }.get(kind, "white")


__all__ = ["render_report", "confirm_apply"]
