"""End-to-end project builder: patterns + CSVs → ~100 XML files.

Given a project layout::

    my-project/
    ├── project.yaml          # blueprint: which patterns + their variables
    └── inputs/               # configurator's tabular data (optional)
        ├── locations.csv
        ├── parameters.csv
        ├── qualifiers.csv
        └── thresholdWarningLevels.csv

This runner:

  1. Ingests CSVs into Pydantic instances for tabular singletons
     (Locations, Parameters, Qualifiers, ThresholdWarningLevels).
  2. Expands the blueprint — each pattern instance renders its
     own files and emits ``contributions`` to project-shared
     singletons (e.g. ModuleInstanceDescriptors).
  3. Merges contributions on top of the CSV-derived data — locations.csv
     gives N stations + patterns add the NWP grids as additional
     locations, all in one Locations.xml.
  4. Validates every output against XSD; optional fixture diff for
     byte-equivalence regression checks.

Single command. The CSV path covers tabular configurator data; the
pattern path covers reusable feature shapes; the merger combines them.

Usage::

    # Patterns only (no CSV inputs):
    python -m runners.agent.build_from_blueprint \\
        --blueprint examples/blueprints/eccc-nwp-demo/project.yaml

    # Patterns + CSVs:
    python -m runners.agent.build_from_blueprint \\
        --blueprint my-project/project.yaml \\
        --inputs my-project/inputs

    # With tutorial regression check:
    python -m runners.agent.build_from_blueprint \\
        --blueprint my-project/project.yaml \\
        --inputs my-project/inputs \\
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

from fews_agent.agent.blueprint import (
    expand, load_blueprint, merge_contributions, write_output,
)
from fews_agent.agent.csv_ingest import IngestResult, ingest_directory
from fews_agent.generators.base import canonicalize
from fews_agent.validation import validate_xsd

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PATTERN_ROOT = REPO_ROOT / "patterns"


def _csv_results_to_base_data(
    ingest_results: dict[str, IngestResult],
) -> dict[str, dict[str, list]]:
    """Convert CSV ingestion results into the merger's ``base_data`` shape.

    The merger expects ``{ClassName: {field_name: [...]}}`` to seed
    aggregated singletons. Each CSV's IngestResult holds a Pydantic
    model (e.g. ``Locations`` with geoDatum + location list); we
    model_dump it and key it by the class name.
    """
    base_data: dict[str, dict[str, list]] = {}
    for spec_name, result in ingest_results.items():
        if result.model is None or spec_name.startswith("_unrecognised"):
            continue
        cls_name = type(result.model).__name__
        base_data[cls_name] = result.model.model_dump(
            mode="python", exclude_none=True
        )
    return base_data


def _render_direct_singletons(
    source_path: Path, spec_names: list[str], result: object,
) -> int:
    """Render specs by feeding their dict from ``source_path`` JSON.

    For each spec name, look up the SPEC entry in the registry, pull
    the matching dict from the JSON file, validate via Pydantic,
    render via the existing template, append a RenderedFile to result.
    Used for project-specific singletons that don't fit a pattern.
    """
    import json as _json

    from fews_agent.agent.blueprint import RenderedFile
    from fews_agent.generators import SPECS
    from fews_agent.generators.base import render as render_template

    spec_by_name = {s.name: s for s in SPECS}

    try:
        seed_data = _json.loads(source_path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        result.errors.append(f"direct singletons read failed: {exc}")
        return 0

    n = 0
    for spec_name in spec_names:
        spec = spec_by_name.get(spec_name)
        if spec is None:
            result.errors.append(f"direct singleton: unknown spec {spec_name!r}")
            continue
        if spec.input_key not in seed_data:
            result.errors.append(
                f"direct singleton {spec_name}: input_key "
                f"{spec.input_key!r} not in {source_path.name}"
            )
            continue
        try:
            model = spec.model_class.model_validate(seed_data[spec.input_key])
            xml = render_template(spec.template_name, model)
            relpath = str(spec.output_relpath).replace("\\", "/")
            result.rendered_files.append(
                RenderedFile(
                    relpath=relpath,
                    content=xml,
                    pattern="(direct)",
                    instance_label=spec_name,
                )
            )
            n += 1
        except Exception as exc:  # noqa: BLE001
            result.errors.append(
                f"direct singleton {spec_name}: "
                f"{type(exc).__name__}: {exc}"
            )
    return n


def _csv_singleton_outputs(
    ingest_results: dict[str, IngestResult],
    target_class_names_with_contributions: set[str],
) -> list[tuple[str, object]]:
    """Pick CSV-derived models that have NO pattern contributions —
    they go straight to render without going through the merger.

    Returns ``[(spec_name, model), ...]`` for direct emission.
    """
    out: list[tuple[str, object]] = []
    for spec_name, result in ingest_results.items():
        if result.model is None or spec_name.startswith("_unrecognised"):
            continue
        cls_name = type(result.model).__name__
        if cls_name in target_class_names_with_contributions:
            continue  # merger handles it
        out.append((spec_name, result.model))
    return out


def build_from_blueprint(
    blueprint_path: Path,
    pattern_root: Path,
    *,
    inputs_dir: Path | None = None,
    diff_against: Path | None = None,
    console: Console | None = None,
) -> dict:
    if console is None:
        console = Console()

    bp = load_blueprint(blueprint_path, pattern_root)
    output_root = (blueprint_path.parent / bp.output_root).resolve()
    output_root.mkdir(parents=True, exist_ok=True)

    # 1) Ingest CSVs (if an inputs/ directory was provided).
    ingest_results: dict[str, IngestResult] = {}
    if inputs_dir is not None and inputs_dir.is_dir():
        ingest_results = ingest_directory(inputs_dir)

    csv_base_data = _csv_results_to_base_data(ingest_results)

    console.print(Panel(
        f"[bold]Blueprint:[/bold] {bp.name}\n"
        f"[dim]source: {blueprint_path}[/dim]\n"
        f"[dim]output: {output_root}[/dim]\n"
        f"[bold]{len(bp.patterns)}[/bold] pattern(s), "
        f"[bold]{sum(len(p.instances) for p in bp.patterns)}[/bold] "
        f"instance(s)"
        + (
            f"\n[bold]CSV inputs:[/bold] "
            + ", ".join(
                f"{spec_name}({r.rows_parsed})"
                for spec_name, r in ingest_results.items()
                if r.model is not None
            )
            if ingest_results else ""
        ),
        border_style="cyan",
    ))

    result = expand(bp, pattern_root)
    if result.errors:
        for err in result.errors:
            console.print(f"[red]error:[/red] {err}")
        return {"ok": False, "errors": result.errors}

    # Merge cross-pattern contributions into singleton files.
    # Base data has three layers, applied in order (later wins):
    #   1) blueprint.singleton_seeds — declared scalars (e.g. geoDatum)
    #   2) CSV-derived data — the configurator's tabular inputs
    #   3) pattern contributions — added by the merger itself
    merged_base: dict[str, dict] = {}
    for source in (bp.singleton_seeds, csv_base_data):
        for cls_name, fields in source.items():
            merged_base.setdefault(cls_name, {}).update(fields)
    merged = merge_contributions(result, base_data=merged_base)
    result.rendered_files.extend(merged)

    # CSV-derived singletons that have NO pattern contributions get
    # rendered directly (the merger only handles classes that show up
    # in the contributions list).
    classes_with_contribs = {
        c.target_file.split("::", 1)[0]
        for c in result.contributions if "::" in c.target_file
    }
    direct_singletons = _csv_singleton_outputs(
        ingest_results, classes_with_contribs,
    )
    if direct_singletons:
        from fews_agent.agent.blueprint import (
            template_for_schema, _output_relpath_for_class,
        )
        from fews_agent.generators.base import render as render_template
        from fews_agent.agent.blueprint import RenderedFile

        for spec_name, model in direct_singletons:
            try:
                template_name = template_for_schema(type(model))
                xml = render_template(template_name, model)
                relpath = _output_relpath_for_class(type(model))
                result.rendered_files.append(
                    RenderedFile(
                        relpath=relpath,
                        content=xml,
                        pattern="(csv)",
                        instance_label=spec_name,
                    )
                )
            except Exception as exc:  # noqa: BLE001
                result.errors.append(
                    f"csv→{type(model).__name__}: {exc}"
                )

    # Direct singletons: render specs straight from a JSON seed file.
    # Used for project-specific singletons that don't fit patterns or
    # the canonical CSV set (Filters, Topology, DisplayGroups, etc.).
    if bp.direct_singletons_source and bp.direct_singletons_specs:
        n_direct = _render_direct_singletons(
            bp.direct_singletons_source, bp.direct_singletons_specs, result,
        )
        console.print(
            f"[dim]Direct singletons: {n_direct} rendered from "
            f"{bp.direct_singletons_source.name}[/dim]"
        )

    if result.errors:
        for err in result.errors:
            console.print(f"[red]error:[/red] {err}")

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
        f"{len(manifest['contributions'])} merged into singletons",
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
        "--inputs", default=None,
        help=(
            "Optional directory of CSV inputs (locations.csv, parameters.csv, "
            "...). Defaults to a sibling 'inputs/' next to the blueprint."
        ),
    )
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

    blueprint_path = Path(args.blueprint).resolve()
    # Auto-detect a sibling inputs/ directory if --inputs not specified.
    if args.inputs:
        inputs_dir: Path | None = Path(args.inputs).resolve()
    else:
        candidate = blueprint_path.parent / "inputs"
        inputs_dir = candidate if candidate.is_dir() else None

    summary = build_from_blueprint(
        blueprint_path=blueprint_path,
        pattern_root=Path(args.pattern_root).resolve(),
        inputs_dir=inputs_dir,
        diff_against=Path(args.diff_against).resolve() if args.diff_against else None,
    )

    return 0 if summary.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
