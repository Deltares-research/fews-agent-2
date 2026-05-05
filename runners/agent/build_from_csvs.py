"""CSV-first project builder — point at a folder, get a FEWS config.

Phase-1 POC entry point. The user drops the canonical CSVs (locations,
parameters, qualifiers, thresholdWarningLevels) into ``--inputs`` and
the agent does the rest:

  1. Ingest each CSV into the matching Pydantic model.
  2. Run gap detection: missing specs → auto-stub or default; surface
     anomalies; guess file-level fields (``geoDatum`` etc.).
  3. Render one consolidated review screen with proposals.
  4. Single Y/N → apply proposals, generate XML, XSD-validate.
  5. Fall back to the existing interactive wizard *only* for specs that
     truly cannot be auto-stubbed.

Compared to ``build_project.py``, this runner replaces the per-spec
wizard with CSV ingestion + initiative. The wizard remains the
fallback path. End-to-end happy path: zero prompts beyond the one
"apply?" confirm.

Usage::

    python -m runners.agent.build_from_csvs \\
        --inputs examples/csv-inputs \\
        --project-name demo

    # No-confirm (good for smoke tests / CI):
    python -m runners.agent.build_from_csvs \\
        --inputs examples/csv-inputs --project-name demo --no-confirm
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

from fews_agent.agent.csv_ingest import ingest_directory
from fews_agent.agent.initiative import (
    AnalysisReport,
    DEFAULT_TARGET_SPECS,
    Proposal,
    analyse,
)
from fews_agent.agent.review import confirm_apply, render_report
from fews_agent.agent.tools import ToolContext, generate_tool
from fews_agent.agent.wizard import run_wizard
from fews_agent.db import ProjectStore
from fews_agent.generators import SPECS
from fews_agent.generators.base import canonicalize
from fews_agent.validation import validate_xsd

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT_ROOT = REPO_ROOT / "validation"

_PROJECT_NAME_RE = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_\-]*$")


def _spec_by_name(spec_name: str):
    for s in SPECS:
        if s.name == spec_name:
            return s
    raise KeyError(f"unknown spec {spec_name!r}")


def _apply_proposals(
    report: AnalysisReport,
) -> tuple[dict[str, object], list[Proposal]]:
    """Build per-spec models from CSVs + accepted proposals.

    Returns ``(models_by_spec, asks)``. ``asks`` are Proposals of kind
    ``ask`` that need interactive fallback for the remaining specs.
    """
    models: dict[str, object] = {}

    # Start from CSV-ingested models.
    for spec_name in report.target_specs:
        r = report.csv_results.get(spec_name)
        if r is not None and r.model is not None:
            models[spec_name] = r.model

    asks: list[Proposal] = []

    # Apply file-field proposals (mutate the existing Pydantic model
    # in place — Pydantic v2 allows attribute set on FewsModel).
    for p in report.proposals:
        if p.kind == "file_field":
            payload = p.payload or {}
            field_name = payload.get("field")
            value = payload.get("value")
            target = models.get(p.spec_name)
            if target is not None and field_name:
                setattr(target, field_name, value)
        elif p.kind in {"auto_stub", "default_skip"}:
            if p.payload is not None:
                models[p.spec_name] = p.payload
        elif p.kind == "ask":
            asks.append(p)

    return models, asks


def _seed_ctx(
    spec_name: str, model: object, ctx: ToolContext
) -> None:
    """Push a Pydantic model into ToolContext under the spec's input_key."""
    spec = _spec_by_name(spec_name)
    # model_dump(mode="python") gives Decimal/Enum-friendly dicts that
    # match the JSON shape generators expect.
    ctx.project_data[spec.input_key] = (
        model.model_dump(mode="python", exclude_none=True)  # type: ignore[attr-defined]
    )
    ctx.store.save(ctx.project_name, ctx.project_data)


def _validate_artifacts(
    workspace_generated: Path,
    run_dir: Path,
) -> list[dict[str, Any]]:
    """Walk generated/, copy to run dir, XSD-validate."""
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
        files_report.append(
            {
                "relpath": str(relpath).replace("\\", "/"),
                "xsd_ok": xsd_ok,
                "xsd_msg": xsd_msg,
            }
        )
    return files_report


def build_from_csvs(
    *,
    inputs_dir: Path,
    project_name: str,
    output_root: Path,
    target_specs: list[str] | None = None,
    no_confirm: bool = False,
    provider_name: str | None = None,
    model: str | None = None,
    console: Console | None = None,
    fresh: bool = True,
) -> dict[str, Any]:
    if console is None:
        console = Console()
    if target_specs is None:
        target_specs = list(DEFAULT_TARGET_SPECS)

    os.environ["FEWS_AGENT_ALL_SPECS"] = "1"

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_dir = output_root / project_name / timestamp
    run_dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------ ingest
    console.print(Panel(
        f"[bold]CSV-first build[/bold] · project={project_name} · "
        f"inputs={inputs_dir}",
        border_style="cyan",
    ))
    ingest_results = ingest_directory(inputs_dir)
    report = analyse(ingest_results, target_specs=target_specs)
    render_report(report, console)

    # ------------------------------------------------------------------ confirm
    if not no_confirm:
        if not confirm_apply(report, console):
            console.print("[yellow]Cancelled by user.[/yellow]")
            return {"ok": False, "cancelled": True, "run_dir": str(run_dir)}

    # ------------------------------------------------------------------ apply
    models, asks = _apply_proposals(report)

    # Initialise project store + ctx for the generator + fallback wizard.
    store_home = run_dir / "_workspace"
    store = ProjectStore(home=store_home)
    proj_dir = store.path_for(project_name)
    if fresh and proj_dir.exists():
        shutil.rmtree(proj_dir)

    project_data: dict[str, Any] = {}
    base_ctx = ToolContext(
        store=store,
        project_name=project_name,
        spec_name="",
        project_data=project_data,
    )
    store.save(project_name, project_data)

    for spec_name, m in models.items():
        ctx = ToolContext(
            store=store,
            project_name=project_name,
            spec_name=spec_name,
            project_data=store.load(project_name),
        )
        _seed_ctx(spec_name, m, ctx)

    # ------------------------------------------------------------------ asks (fallback)
    if asks:
        from fews_agent.agent.providers.factory import get_provider
        inner_provider = get_provider(provider_name, model)
        for p in asks:
            console.print(Panel(
                f"[bold]Fallback wizard:[/bold] {p.spec_name}\n"
                f"[dim]{p.reasoning}[/dim]",
                border_style="yellow",
            ))
            ctx = ToolContext(
                store=store,
                project_name=project_name,
                spec_name=p.spec_name,
                project_data=store.load(project_name),
            )
            try:
                run_wizard(p.spec_name, ctx, console, provider=inner_provider)
            except KeyboardInterrupt:
                console.print(
                    f"\n[yellow]Skipped {p.spec_name} (interrupted).[/yellow]"
                )
                continue
            except Exception as exc:  # noqa: BLE001
                console.print(
                    f"[red]wizard failed for {p.spec_name}: {exc}[/red]"
                )
                continue

    # ------------------------------------------------------------------ generate
    generated_specs: list[str] = []
    for spec_name in target_specs:
        ctx = ToolContext(
            store=store,
            project_name=project_name,
            spec_name=spec_name,
            project_data=store.load(project_name),
        )
        spec = _spec_by_name(spec_name)
        if spec.input_key not in ctx.project_data:
            console.print(
                f"[dim]skipping {spec_name} — no data after wizard fallback.[/dim]"
            )
            continue
        gen_result = generate_tool.generate(name=spec_name, ctx=ctx)
        if "error" in gen_result or "validation_errors" in gen_result:
            console.print(
                f"[red]✗ {spec_name} failed:[/red] "
                f"{gen_result.get('error') or gen_result.get('validation_errors')}"
            )
            continue
        rel = gen_result.get("output_relpath", "?")
        console.print(f"[green]✓[/green] {spec_name} → {rel}")
        generated_specs.append(spec_name)

    # ------------------------------------------------------------------ validate
    workspace_generated = store.path_for(project_name) / "generated"
    files_report = _validate_artifacts(workspace_generated, run_dir)
    n_total = len(files_report)
    n_xsd = sum(1 for r in files_report if r["xsd_ok"])

    table_lines = [
        f"[bold]Generated:[/bold] {n_total} file(s)",
        f"[bold]XSD-valid:[/bold] {n_xsd}/{n_total}",
        f"[bold]Specs covered:[/bold] {len(generated_specs)}/{len(target_specs)}",
        f"[bold]Run dir:[/bold] {run_dir}",
    ]
    border = "green" if n_total and n_xsd == n_total else "yellow"
    console.print(Panel(
        "\n".join(table_lines),
        title="Build complete",
        border_style=border,
    ))

    summary = {
        "ok": n_total > 0 and n_xsd == n_total,
        "project": project_name,
        "run_dir": str(run_dir),
        "specs_generated": generated_specs,
        "files_total": n_total,
        "files_xsd_ok": n_xsd,
        "files": files_report,
        "proposals_applied": [
            {"spec": p.spec_name, "kind": p.kind, "summary": p.summary}
            for p in report.proposals if p.kind != "ask"
        ],
        "asks_fallback_to_wizard": [p.spec_name for p in asks],
        "anomalies": [
            {"spec": a.spec_name, "severity": a.severity, "message": a.message}
            for a in report.anomalies
        ],
    }
    summary_path = run_dir / "summary.json"
    summary_path.write_text(
        json.dumps(summary, indent=2, default=str), encoding="utf-8"
    )
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--inputs",
        required=True,
        help="Directory containing the CSV input files.",
    )
    parser.add_argument(
        "--project-name", default="csv_demo",
        help="Project name (alphanumeric / underscore / hyphen).",
    )
    parser.add_argument(
        "--target-specs",
        default=None,
        help="Comma-separated spec names (default: locations,parameters,"
        "qualifiers,thresholdWarningLevels).",
    )
    parser.add_argument(
        "--output-root",
        default=str(DEFAULT_OUTPUT_ROOT),
        help="Where each run writes <project>/<timestamp>/.",
    )
    parser.add_argument("--provider", default=None, help="ollama | anthropic")
    parser.add_argument("--model", default=None)
    parser.add_argument(
        "--no-confirm", action="store_true",
        help="Skip the 'apply all?' confirm. Good for CI / smoke tests.",
    )
    args = parser.parse_args(argv)

    if not _PROJECT_NAME_RE.match(args.project_name):
        print(
            f"error: project name {args.project_name!r} must match "
            f"^[A-Za-z0-9_][A-Za-z0-9_\\-]*$",
            file=sys.stderr,
        )
        return 2

    targets: list[str] | None = None
    if args.target_specs:
        targets = [
            s.strip() for s in args.target_specs.split(",") if s.strip()
        ]

    summary = build_from_csvs(
        inputs_dir=Path(args.inputs),
        project_name=args.project_name,
        output_root=Path(args.output_root),
        target_specs=targets,
        no_confirm=args.no_confirm,
        provider_name=args.provider,
        model=args.model,
    )

    print(json.dumps(summary, indent=2, default=str))
    return 0 if summary.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
