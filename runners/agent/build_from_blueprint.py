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
        --blueprint projects/eccc-nwp-demo/eccc-nwp-demo_<datetime>/project.yaml

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
    Blueprint, PatternRef, expand, load_blueprint, merge_contributions,
    write_output,
)
from fews_agent.agent.phases import PHASE_LABELS, classify_phase
from fews_agent.agent.csv_ingest import IngestResult, ingest_directory
from fews_agent.agent.descriptor_derivation import derive_descriptor_singletons
from fews_agent.agent.filter_drafter import (
    collect_filter_context, draft_filters_yaml,
)
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


def _collect_idmap_references(rendered_files: list) -> set[str]:
    """Walk rendered XMLs; return set of referenced idMap IDs.

    Two sources of referenced ids:
      1. Direct refs via ``<idMapId>``, ``<importIdMap>``, ``<exportIdMap>``
         elements (module-config and adapter-run files).
      2. Inferred refs from ``<moduleInstanceId>Import<X></...>`` in
         workflow files: by FEWS convention the matching idMap is
         ``IdImport<X>``. This catches the case where a workflow
         schedules an Import* module instance whose module-config
         file isn't generated by our patterns (e.g. NAM, SREF —
         covered only at the workflow level in the tutorial).
    """
    from lxml import etree
    referenced: set[str] = set()
    for rf in rendered_files:
        try:
            tree = etree.fromstring(rf.content.encode("utf-8"))
        except etree.XMLSyntaxError:
            continue
        for tag in ("idMapId", "importIdMap", "exportIdMap"):
            for el in tree.iter(f"{{*}}{tag}"):
                t = (el.text or "").strip()
                if t:
                    referenced.add(t)
        # Inference: workflow's Import<X> module instance → IdImport<X>.
        for el in tree.iter("{*}moduleInstanceId"):
            t = (el.text or "").strip()
            if t.startswith("Import") and not t.startswith("ImportSREFforHistoricMerge"):
                # Strip a few known suffixes that aren't part of the idMap name.
                suffix = t[len("Import"):]
                referenced.add(f"IdImport{suffix}")
    return referenced


def _collect_parameter_ids(rendered_files: list) -> set[str]:
    """Walk rendered XMLs; return set of <parameterId> references.
    Used to filter idMap content to only include mappings for
    parameters the project actually uses."""
    from lxml import etree
    ids: set[str] = set()
    for rf in rendered_files:
        try:
            tree = etree.fromstring(rf.content.encode("utf-8"))
        except etree.XMLSyntaxError:
            continue
        for el in tree.iter("{*}parameterId"):
            t = (el.text or "").strip()
            if t and not t.startswith("$"):
                ids.add(t)
    return ids


def _collect_referenced_module_instances(rendered_files: list) -> set[str]:
    """Walk rendered XMLs; collect <moduleInstanceId> references."""
    from lxml import etree
    ids: set[str] = set()
    for rf in rendered_files:
        try:
            tree = etree.fromstring(rf.content.encode("utf-8"))
        except etree.XMLSyntaxError:
            continue
        for el in tree.iter("{*}moduleInstanceId"):
            t = (el.text or "").strip()
            if t and not t.startswith("$"):
                ids.add(t)
    return ids


def _collect_location_ids(rendered_files: list) -> set[str]:
    """Walk rendered XMLs; return set of <locationId> references."""
    from lxml import etree
    ids: set[str] = set()
    for rf in rendered_files:
        try:
            tree = etree.fromstring(rf.content.encode("utf-8"))
        except etree.XMLSyntaxError:
            continue
        for el in tree.iter("{*}locationId"):
            t = (el.text or "").strip()
            if t:
                ids.add(t)
    return ids


def _filter_displaygroups_content(
    data: dict, project_module_instance_ids: set[str],
) -> dict:
    """Drop only plot body entries whose moduleInstanceId references
    aren't in the project. displayGroup entries reference plots
    indirectly (via plotId), so we don't filter them — XSD requires
    at least one displayGroup, and dropping them would invalidate."""
    if not isinstance(data, dict) or "body" not in data:
        return data
    original = data.get("body") or []
    if not original or not project_module_instance_ids:
        return data

    def _references_known(entry: Any) -> bool:
        if isinstance(entry, dict):
            for k, v in entry.items():
                if k == "moduleInstanceId" and v in project_module_instance_ids:
                    return True
                if _references_known(v):
                    return True
            return False
        if isinstance(entry, list):
            return any(_references_known(x) for x in entry)
        return False

    kept = []
    for entry in original:
        # Only filter `plot` entries; pass through `displayGroup` and others.
        if isinstance(entry, dict) and "plot" in entry:
            if _references_known(entry):
                kept.append(entry)
        else:
            kept.append(entry)
    if not kept:
        return data  # safeguard
    return {**data, "body": kept}


_BASIN_PATTERNS = frozenset({"auto/raven_basin", "auto/wflow_basin"})


def _count_basin_instances(bp) -> int:
    """Count basin pattern instances in the blueprint. Drives MODELNAME1/2
    placeholder gating in the SpatialDisplay trim — a $MODELNAME2$ panel
    is only "alive" if the project has >=2 basins."""
    n = 0
    for p in bp.patterns:
        if p.pattern in _BASIN_PATTERNS:
            n += len(p.instances)
    return n


def _plot_is_alive(
    plot: Any, alive_modules: set[str], basin_count: int,
) -> bool:
    """A gridPlot is alive if any of its moduleInstanceId references
    resolves: literal in the project's rendered module set, or a
    $MODELNAME1$/$MODELNAME2$ placeholder whose basin slot is filled."""
    ids: list[str] = []

    def collect(obj: Any) -> None:
        if isinstance(obj, dict):
            for k, v in obj.items():
                if k == "moduleInstanceId" and isinstance(v, str):
                    ids.append(v)
                else:
                    collect(v)
        elif isinstance(obj, list):
            for x in obj:
                collect(x)

    collect(plot)
    for mid in ids:
        if mid in alive_modules:
            return True
        if "$MODELNAME1$" in mid and basin_count >= 1:
            return True
        if "$MODELNAME2$" in mid and basin_count >= 2:
            return True
    return False


def _trim_spatial_group(
    group: dict, alive_modules: set[str], basin_count: int,
) -> dict | None:
    """Recursively prune a gridPlotGroup. Returns None if the group
    becomes empty (no subgroups, no plots). Mutation-free: returns a
    new dict with kept children."""
    out = {k: v for k, v in group.items() if k not in ("gridPlotGroup", "gridPlot")}

    # Recurse into nested gridPlotGroup (singular dict or list).
    nested = group.get("gridPlotGroup")
    if isinstance(nested, list):
        kept_subs = [
            t for sub in nested
            if (t := _trim_spatial_group(sub, alive_modules, basin_count))
            is not None
        ]
        if kept_subs:
            out["gridPlotGroup"] = kept_subs
    elif isinstance(nested, dict):
        trimmed = _trim_spatial_group(nested, alive_modules, basin_count)
        if trimmed is not None:
            out["gridPlotGroup"] = trimmed

    # Filter own gridPlot (singular dict or list).
    plot = group.get("gridPlot")
    if isinstance(plot, list):
        kept_plots = [
            p for p in plot
            if _plot_is_alive(p, alive_modules, basin_count)
        ]
        if kept_plots:
            out["gridPlot"] = kept_plots
    elif isinstance(plot, dict):
        if _plot_is_alive(plot, alive_modules, basin_count):
            out["gridPlot"] = plot

    if "gridPlotGroup" not in out and "gridPlot" not in out:
        return None
    return out


def _resolve_region_bbox(
    region: str | None,
    custom_bbox: tuple[float, float, float, float] | list | None = None,
) -> tuple[str, tuple[float, float, float, float]] | None:
    """Pick the bbox to use for SpatialDisplay / NWP grid cropping.

    Free-form ``custom_bbox`` (parsed from prose) wins over the gazetteer
    lookup so the user can override a named region's default extent or
    specify an area the gazetteer doesn't know about. Returns the label
    to stamp on the extent's ``@id`` and the bbox tuple, or None if
    nothing usable is set.
    """
    from fews_agent.agent.project_intents import REGION_BBOX

    if custom_bbox is not None:
        try:
            left, right, top, bottom = (float(v) for v in custom_bbox)
        except (TypeError, ValueError):
            pass
        else:
            label = region if region else "Custom Region"
            return label, (left, right, top, bottom)
    if region and region in REGION_BBOX:
        return region, REGION_BBOX[region]
    return None


def _apply_region_extent(
    data: dict,
    region: str | None,
    custom_bbox: tuple[float, float, float, float] | list | None = None,
) -> dict:
    """Override SpatialDisplay defaults.geoMap.defaultExtent for the
    project region. No-op if neither ``region`` nor ``custom_bbox``
    resolves to a known bbox — the bundled defaults stay (MacKenzie-
    shaped, wrong for any non-tutorial project but at least valid)."""
    resolved = _resolve_region_bbox(region, custom_bbox)
    if resolved is None or not isinstance(data, dict):
        return data
    body = data.get("body") or []
    if not body:
        return data
    label, (left, right, top, bottom) = resolved
    rewritten = []
    for entry in body:
        if (isinstance(entry, dict) and "defaults" in entry
                and isinstance(entry["defaults"], dict)
                and isinstance(entry["defaults"].get("geoMap"), dict)
                and isinstance(
                    entry["defaults"]["geoMap"].get("defaultExtent"), dict)):
            new_entry = {**entry}
            new_defaults = {**entry["defaults"]}
            new_geomap = {**new_defaults["geoMap"]}
            new_geomap["defaultExtent"] = {
                "@id": label,
                "left": str(left),
                "right": str(right),
                "top": str(top),
                "bottom": str(bottom),
            }
            new_defaults["geoMap"] = new_geomap
            new_entry["defaults"] = new_defaults
            rewritten.append(new_entry)
        else:
            rewritten.append(entry)
    return {**data, "body": rewritten}


def _filter_spatial_display_content(
    data: dict, alive_modules: set[str], basin_count: int,
    allow_empty: bool = False,
) -> dict:
    """Drop SpatialDisplay body entries whose moduleInstanceId
    references the project doesn't have. Pass through non-group
    entries (title, defaults). Default behavior is to keep the
    original when every panel would be dropped (FEWS prefers a
    redundant panel to no panel). Set ``allow_empty=True`` when
    pattern contributions will append project-specific panels after
    this trim — in that case an empty-after-trim body is correct."""
    if not isinstance(data, dict) or "body" not in data:
        return data
    body = data.get("body") or []
    if not body:
        return data

    kept: list = []
    dropped_any_panel = False
    kept_any_panel = False
    for entry in body:
        if not isinstance(entry, dict) or "gridPlotGroup" not in entry:
            kept.append(entry)
            continue
        trimmed = _trim_spatial_group(
            entry["gridPlotGroup"], alive_modules, basin_count,
        )
        if trimmed is None:
            dropped_any_panel = True
            continue
        kept_any_panel = True
        kept.append({"gridPlotGroup": trimmed})

    if dropped_any_panel and not kept_any_panel and not allow_empty:
        return data
    return {**data, "body": kept}


_NWP_PATTERN_PREFIXES: tuple[str, ...] = (
    "auto/nwp_grid_",
)


def _nwp_location_ids_from_blueprint(bp) -> set[str]:
    """Collect NWP source names declared by NWP patterns in the blueprint.

    These match the ``@locationId`` values in gridsFile entries (e.g.
    GFS, HRDPS, RDPS) so the region-bbox rewriter knows which grids to
    crop.
    """
    out: set[str] = set()
    for p in bp.patterns:
        if not any(p.pattern.startswith(pref) for pref in _NWP_PATTERN_PREFIXES):
            continue
        for inst in p.instances:
            if not isinstance(inst, dict):
                continue
            name = inst.get("nwp_name") or inst.get("source_name")
            if isinstance(name, str) and name:
                out.add(name)
    return out


# NOAA URL slug → degrees. Other NWP patterns can extend this map as
# they add their own slugs (ECCC HRDPS, GDPS, etc.).
_GRID_RESOLUTION_DEGREES: dict[str, float] = {
    "0p25": 0.25,
    "0p50": 0.5,
    "1p00": 1.0,
}


def _nwp_resolutions_from_blueprint(bp) -> dict[str, float]:
    """Walk blueprint NWP instances; return {locationId: cell_size_deg}.

    Only entries whose ``grid_resolution`` resolves to a known slug are
    returned. Instances without the field (or with an unknown slug) are
    skipped so the bundled defaults stay.
    """
    out: dict[str, float] = {}
    for p in bp.patterns:
        if not any(p.pattern.startswith(pref) for pref in _NWP_PATTERN_PREFIXES):
            continue
        for inst in p.instances:
            if not isinstance(inst, dict):
                continue
            name = inst.get("nwp_name") or inst.get("source_name")
            slug = inst.get("grid_resolution")
            if not isinstance(name, str) or not isinstance(slug, str):
                continue
            deg = _GRID_RESOLUTION_DEGREES.get(slug)
            if deg is not None:
                out[name] = deg
    return out


def _apply_nwp_resolutions_to_grids(
    data: dict, nwp_resolutions: dict[str, float],
) -> dict:
    """Override xCellSize/yCellSize on bundled gridsFile entries whose
    ``@locationId`` matches an NWP instance that asked for a non-default
    resolution. Runs BEFORE the region-bbox crop so rows/columns are
    recomputed from the new cell size."""
    if not nwp_resolutions or not isinstance(data, dict):
        return data
    body = data.get("body") or []
    if not body:
        return data
    rewritten = []
    for entry in body:
        if not isinstance(entry, dict) or "regular" not in entry:
            rewritten.append(entry)
            continue
        inner = entry["regular"]
        loc_id = inner.get("@locationId") if isinstance(inner, dict) else None
        if not isinstance(loc_id, str) or loc_id not in nwp_resolutions:
            rewritten.append(entry)
            continue
        deg = nwp_resolutions[loc_id]
        new_inner = {**inner, "xCellSize": str(deg), "yCellSize": str(deg)}
        rewritten.append({"regular": new_inner})
    return {**data, "body": rewritten}


def _apply_region_to_grids(
    data: dict,
    region: str | None,
    nwp_location_ids: set[str],
    custom_bbox: tuple[float, float, float, float] | list | None = None,
) -> dict:
    """Crop NWP grid entries to the project's region bbox.

    Only rewrites ``regular`` grid entries whose ``@locationId`` is in
    ``nwp_location_ids`` (so user-authored grid entries are left alone).
    Recomputes rows/columns from xCellSize/yCellSize; falls back to the
    original entry if cell size is missing or non-numeric.
    """
    resolved = _resolve_region_bbox(region, custom_bbox)
    if resolved is None or not isinstance(data, dict) or not nwp_location_ids:
        return data
    _label, (left, right, top, bottom) = resolved
    body = data.get("body") or []
    if not body:
        return data
    rewritten = []
    for entry in body:
        if not isinstance(entry, dict) or "regular" not in entry:
            rewritten.append(entry)
            continue
        inner = entry["regular"]
        if (not isinstance(inner, dict)
                or inner.get("@locationId") not in nwp_location_ids):
            rewritten.append(entry)
            continue
        try:
            x_cell = float(inner.get("xCellSize", ""))
            y_cell = float(inner.get("yCellSize", ""))
        except (TypeError, ValueError):
            rewritten.append(entry)
            continue
        if x_cell <= 0 or y_cell <= 0:
            rewritten.append(entry)
            continue
        cols = max(1, int(round((right - left) / x_cell)))
        rows = max(1, int(round((top - bottom) / y_cell)))
        new_inner = {**inner}
        new_inner["rows"] = str(rows)
        new_inner["columns"] = str(cols)
        new_inner["firstCellCenter"] = {
            "x": str(left + x_cell / 2),
            "y": str(top - y_cell / 2),
        }
        rewritten.append({"regular": new_inner})
    return {**data, "body": rewritten}


def _filter_grids_content(
    data: dict, project_location_ids: set[str],
) -> dict:
    """Drop grid entries whose @locationId isn't referenced by the project.

    Keeps placeholder entries (those with a $...$ placeholder) since
    those are FEWS runtime templates that resolve at execution time.
    Empty-result safeguard: if all would be dropped, keep original.
    """
    if not isinstance(data, dict) or "body" not in data:
        return data
    original = data.get("body") or []
    if not original:
        return data
    kept = []
    for entry in original:
        # Each body item has one of: regular, irregular, raster, etc.
        # The locationId is on the inner dict.
        inner = next(iter(entry.values())) if entry else {}
        loc_id = inner.get("@locationId", "") if isinstance(inner, dict) else ""
        if (
            loc_id.startswith("$")
            or loc_id in project_location_ids
            or not loc_id
        ):
            kept.append(entry)
    if not kept:
        return data
    return {**data, "body": kept}


def _filter_idmap_content(
    data: dict, project_parameter_ids: set[str],
) -> dict:
    """Drop idMap entries whose internalParameter isn't used by the project.

    Map entries with no internalParameter (e.g. location-only mappings)
    are kept as-is. If filtering drops everything, returns data unchanged
    (safer to emit a slightly redundant idMap than miss mappings).
    """
    if not isinstance(data, dict) or "map" not in data:
        return data
    original = data.get("map") or []
    if not original:
        return data
    kept = [
        e for e in original
        if e.get("internalParameter") is None
        or e.get("internalParameter") in project_parameter_ids
    ]
    if not kept:
        return data  # don't risk an empty idMap
    return {**data, "map": kept}


def _spec_is_idmap(spec_name: str) -> bool:
    """An idMap spec is one whose name starts with idImport/idExport."""
    return spec_name.startswith(("idImport", "idExport"))


def _idmap_is_referenced(
    spec_name: str, referenced_ids: set[str],
) -> bool:
    """Match spec name to a referenced ID. SPECS use camelCase
    (``idImportCanadaWCS``); references use PascalCase
    (``IdImportCanadaWCS``). Comparison is case-insensitive — the
    tutorial's ``IdImportGlobSnow`` reference vs the file's
    ``IdImportGLOBSNOW`` declaration is a documented FEWS quirk
    (works on Windows, breaks on Linux); the agent treats the spec
    as referenced regardless of case so the bundled standard renders."""
    if not referenced_ids:
        return False
    pascal = spec_name[:1].upper() + spec_name[1:]
    refs_lower = {r.lower() for r in referenced_ids}
    return pascal.lower() in refs_lower


def _render_yaml_inputs(
    inputs_dir: Path, result: object, label: str = "yaml",
    filter_idmaps_by_ref: bool = False,
    basin_count: int = 0,
    region: str | None = None,
    nwp_location_ids: set[str] | None = None,
    custom_bbox: tuple[float, float, float, float] | list | None = None,
    nwp_resolutions: dict[str, float] | None = None,
) -> int:
    """Walk ``inputs_dir`` for *.yaml and *.yml files, render each as a spec.

    When ``filter_idmaps_by_ref=True``, idMap yamls (idImport*/idExport*)
    are only rendered if their canonical ID is referenced somewhere in
    the already-rendered XMLs. Used for the standard-inputs fallback to
    avoid emitting dead idMap files in projects that don't use all 14
    bundled data sources.
    """
    import yaml as _yaml

    from fews_agent.agent.blueprint import RenderedFile
    from fews_agent.generators import SPECS
    from fews_agent.generators.base import render as render_template

    spec_by_name = {s.name: s for s in SPECS}
    already_produced = {
        rf.relpath.replace("\\", "/") for rf in result.rendered_files
    }
    referenced_idmap_ids = (
        _collect_idmap_references(result.rendered_files)
        if filter_idmaps_by_ref else set()
    )
    project_parameter_ids = (
        _collect_parameter_ids(result.rendered_files)
        if filter_idmaps_by_ref else set()
    )
    project_location_ids = (
        _collect_location_ids(result.rendered_files)
        if filter_idmaps_by_ref else set()
    )
    n = 0
    for path in sorted(inputs_dir.iterdir()):
        if not path.is_file() or path.suffix.lower() not in {".yaml", ".yml"}:
            continue
        spec_name = path.stem
        spec = spec_by_name.get(spec_name)
        if spec is None:
            continue
        target_relpath = str(spec.output_relpath).replace("\\", "/")
        if target_relpath in already_produced and label != "yaml":
            continue
        # Project-aware idMap filtering.
        if (
            filter_idmaps_by_ref
            and _spec_is_idmap(spec_name)
            and not _idmap_is_referenced(spec_name, referenced_idmap_ids)
        ):
            continue
        try:
            data = _yaml.safe_load(path.read_text(encoding="utf-8"))
            if data is None:
                continue
            # Trim idMap content to project-used parameters.
            if (
                filter_idmaps_by_ref
                and _spec_is_idmap(spec_name)
                and project_parameter_ids
            ):
                data = _filter_idmap_content(data, project_parameter_ids)
            # Trim gridsFile content to project-used locations, override
            # NWP cell sizes per the blueprint, then crop to the region
            # bbox. Resolution rewrite runs BEFORE the crop so the
            # rows/columns recompute from the user-chosen cell size.
            if (
                filter_idmaps_by_ref
                and spec_name == "gridsFile"
                and project_location_ids
            ):
                data = _filter_grids_content(data, project_location_ids)
                data = _apply_nwp_resolutions_to_grids(
                    data, nwp_resolutions or {},
                )
                data = _apply_region_to_grids(
                    data, region, nwp_location_ids or set(),
                    custom_bbox=custom_bbox,
                )
            # Trim displayGroups body to project-used module instances.
            if (
                filter_idmaps_by_ref
                and spec_name == "displayGroupsFile"
            ):
                project_module_ids = (
                    _collect_referenced_module_instances(result.rendered_files)
                )
                data = _filter_displaygroups_content(data, project_module_ids)
            # Trim SpatialDisplay body to project-used modules / declared
            # basin slots. Fires only on the standard-inputs fallback —
            # if a pattern contributed to SpatialDisplay, the merger
            # already produced it (and pre-seed handled the trim there).
            if (
                filter_idmaps_by_ref
                and spec_name == "spatialDisplayFile"
            ):
                project_module_ids = (
                    _collect_referenced_module_instances(result.rendered_files)
                )
                data = _filter_spatial_display_content(
                    data, project_module_ids, basin_count,
                )
                data = _apply_region_extent(data, region, custom_bbox)
            model = spec.model_class.model_validate(data)
            xml = render_template(spec.template_name, model)
            result.rendered_files.append(
                RenderedFile(
                    relpath=target_relpath,
                    content=xml,
                    pattern=f"({label})",
                    instance_label=spec_name,
                )
            )
            already_produced.add(target_relpath)
            n += 1
        except Exception as exc:  # noqa: BLE001
            result.errors.append(
                f"{label} input {path.name}: {type(exc).__name__}: {exc}"
            )
    return n


# Bundled standard yamls — universally-standard FEWS configuration that
# almost never varies per project. Falls back here when the project's
# inputs/ doesn't provide a yaml for these specs.
STANDARD_INPUTS_DIR = REPO_ROOT / "fews_agent" / "agent" / "standard_inputs"


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

    # 1b) FEWS-Conform opt-in: reference locations.csv in place from a
    # csvFile-backed LocationSet instead of materialising Locations.xml.
    # This preserves every non-reserved CSV column as a location attribute
    # (Type/ModelId/WflowId... — which plain ingest drops). Gated on
    # ``metadata.locations_as_csvfile`` so the default byte-equivalent
    # oracle path is untouched. See locationsets_derivation.
    csvfile_locsets: list[dict] = []
    csvfile_copies: list[tuple[str, str]] = []  # (relpath, raw content)
    if bp.metadata.get("locations_as_csvfile"):
        from fews_agent.agent.locationsets_derivation import (
            locationset_csvfile_body,
        )
        set_id = bp.metadata.get("location_set_id", "Stations")
        seed_datum = (
            (bp.singleton_seeds.get("Locations") or {}).get("geoDatum")
            if bp.singleton_seeds else None
        )
        for spec_name, r in list(ingest_results.items()):
            if r.spec_name != "locations" or r.model is None:
                continue
            headers = list(r.column_mapping.keys())
            geo = (
                seed_datum
                or r.inferred_file_fields.get("geoDatum")
                or "WGS 1984"
            )
            csv_name = r.csv_path.name
            csvfile_locsets.append(
                locationset_csvfile_body(
                    csv_name, headers, set_id=set_id, geo_datum=str(geo),
                )
            )
            # Copy the raw CSV into the config tree (MapLayerFiles/) so the
            # locationSet's <file> reference resolves at FEWS runtime.
            try:
                csvfile_copies.append((
                    f"MapLayerFiles/{csv_name}",
                    r.csv_path.read_text(encoding="utf-8-sig"),
                ))
            except OSError:
                pass
            # Suppress Locations.xml materialisation from this CSV — Conform
            # declares locations via LocationSets, never Locations.xml.
            ingest_results.pop(spec_name, None)

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

    # Emit the raw locations CSV copies (Conform csvFile opt-in) as
    # non-XML config-tree files that the csvFile LocationSets reference.
    if csvfile_copies:
        from fews_agent.agent.blueprint import RenderedFile
        for relpath, content in csvfile_copies:
            result.rendered_files.append(RenderedFile(
                relpath=relpath,
                content=content,
                pattern="(conform-csv)",
                instance_label=Path(relpath).name,
            ))

    # Merge cross-pattern contributions into singleton files.
    # Base data has three layers, applied in order (later wins):
    #   1) blueprint.singleton_seeds — declared scalars (e.g. geoDatum)
    #   2) CSV-derived data — the configurator's tabular inputs
    #   3) pattern contributions — added by the merger itself
    merged_base: dict[str, dict] = {}
    # Pre-seed bundled-standard bodies for any spec class that a pattern
    # contributes to. Without this, the merger emits a singleton XML
    # whose body contains ONLY the pattern contribution — and because
    # the file is already produced, the standard-inputs fallback later
    # skips it. The bundled body would be lost. By pre-loading the
    # bundled yaml into merged_base, contributions APPEND to the
    # standard body instead of replacing it.
    contrib_target_classes = {
        c.target_file.split("::", 1)[0]
        for c in result.contributions
        if "::" in c.target_file
    }
    if contrib_target_classes and STANDARD_INPUTS_DIR.is_dir():
        import yaml as _yaml_seed
        from fews_agent.generators import SPECS as _SPECS_seed
        spec_by_cls = {s.model_class.__name__: s for s in _SPECS_seed}
        # Module IDs already in the rendered pattern files — used to
        # trim bundled SpatialDisplay panels referencing absent modules.
        pre_seed_module_ids = _collect_referenced_module_instances(
            result.rendered_files
        )
        basin_count = _count_basin_instances(bp)
        for cls_name in contrib_target_classes:
            spec = spec_by_cls.get(cls_name)
            if spec is None:
                continue
            std_path = STANDARD_INPUTS_DIR / f"{spec.input_key}.yaml"
            if not std_path.is_file():
                continue
            try:
                data = _yaml_seed.safe_load(
                    std_path.read_text(encoding="utf-8")
                )
            except Exception:  # noqa: BLE001
                continue
            if not isinstance(data, dict):
                continue
            # Spec-specific trim of the pre-seeded body so contributions
            # append onto a project-relevant base (not the full bundled
            # smorgasbord of dead panels).
            if spec.name == "spatialDisplayFile":
                data = _filter_spatial_display_content(
                    data, pre_seed_module_ids, basin_count,
                    allow_empty=True,
                )
                _locations_seed_2 = (
                    (bp.singleton_seeds.get("Locations") or {})
                    if bp.singleton_seeds else {}
                )
                data = _apply_region_extent(
                    data,
                    _locations_seed_2.get("region"),
                    _locations_seed_2.get("regionBbox"),
                )
            merged_base.setdefault(cls_name, {})
            for field_name, field_val in data.items():
                merged_base[cls_name].setdefault(field_name, field_val)
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

    # Per-spec YAML files in inputs/ — one file per non-tabular
    # singleton (Filters, Topology, DisplayGroups, ...). The runner
    # renders these via the existing template path. Configurator
    # authors each file in its natural shape.
    if inputs_dir is not None and inputs_dir.is_dir():
        n_yaml = _render_yaml_inputs(inputs_dir, result)
        if n_yaml:
            console.print(
                f"[dim]Per-spec YAML inputs: {n_yaml} rendered from "
                f"{inputs_dir}[/dim]"
            )

    # Direct singletons (legacy path): render specs straight from a
    # JSON seed file. Used for projects that prefer one big JSON over
    # split per-spec yamls.
    if bp.direct_singletons_source and bp.direct_singletons_specs:
        n_direct = _render_direct_singletons(
            bp.direct_singletons_source, bp.direct_singletons_specs, result,
        )
        console.print(
            f"[dim]Direct singletons: {n_direct} rendered from "
            f"{bp.direct_singletons_source.name}[/dim]"
        )

    # LLM filter drafter — proposes a filtersFile based on the project's
    # actual moduleInstanceIds + parameterIds (extracted from rendered
    # XMLs). Runs only when the configurator hasn't provided their own
    # filtersFile.yaml.
    from fews_agent.generators import SPECS as _SPECS
    filters_spec = next(
        (s for s in _SPECS if s.name == "filtersFile"), None
    )
    if filters_spec:
        filters_relpath = str(filters_spec.output_relpath).replace("\\", "/")
        already_have_filters = any(
            rf.relpath.replace("\\", "/") == filters_relpath
            for rf in result.rendered_files
        )
        if not already_have_filters:
            ctx = collect_filter_context(result.rendered_files)
            draft = draft_filters_yaml(ctx)
            if draft:
                try:
                    from fews_agent.agent.blueprint import RenderedFile
                    from fews_agent.generators.base import (
                        render as render_template,
                    )
                    model = filters_spec.model_class.model_validate(draft)
                    xml = render_template(filters_spec.template_name, model)
                    result.rendered_files.append(RenderedFile(
                        relpath=filters_relpath,
                        content=xml,
                        pattern="(filter-drafter)",
                        instance_label="filtersFile",
                    ))
                    console.print(
                        f"[dim]LLM-drafted filtersFile from "
                        f"{len(ctx.get('moduleInstanceIds', []))} module IDs"
                        f"[/dim]"
                    )
                except Exception as exc:  # noqa: BLE001
                    console.print(
                        f"[yellow]LLM filter draft invalid, will fall back "
                        f"to standard: {type(exc).__name__}[/yellow]"
                    )

    # Standard-inputs fallback: bundled yamls (timeSteps, unit
    # conversions) for specs the project didn't author its own version
    # of. Configurator-provided files always win; standards only fill
    # gaps.
    if STANDARD_INPUTS_DIR.is_dir():
        _locations_seed = (
            (bp.singleton_seeds.get("Locations") or {})
            if bp.singleton_seeds else {}
        )
        _region_seed = _locations_seed.get("region")
        _bbox_seed = _locations_seed.get("regionBbox")
        n_std = _render_yaml_inputs(
            STANDARD_INPUTS_DIR, result, label="standard",
            filter_idmaps_by_ref=True,
            basin_count=_count_basin_instances(bp),
            region=_region_seed,
            nwp_location_ids=_nwp_location_ids_from_blueprint(bp),
            custom_bbox=_bbox_seed,
            nwp_resolutions=_nwp_resolutions_from_blueprint(bp),
        )
        if n_std:
            console.print(
                f"[dim]Standard inputs filled: {n_std} spec(s)[/dim]"
            )

    # Auto-derive Topology.xml from rendered workflow files. Only fires
    # when the configurator hasn't provided their own topology.yaml.
    topology_spec = next((s for s in _SPECS if s.name == "topology"), None)
    if topology_spec:
        topology_relpath = str(topology_spec.output_relpath).replace("\\", "/")
        already_have_topology = any(
            rf.relpath.replace("\\", "/") == topology_relpath
            for rf in result.rendered_files
        )
        if not already_have_topology:
            from fews_agent.agent.topology_derivation import derive_topology_yaml
            topo_data = derive_topology_yaml(result.rendered_files)
            if topo_data:
                try:
                    from fews_agent.agent.blueprint import RenderedFile
                    from fews_agent.generators.base import (
                        render as render_template,
                    )
                    model = topology_spec.model_class.model_validate(topo_data)
                    xml = render_template(topology_spec.template_name, model)
                    result.rendered_files.append(RenderedFile(
                        relpath=topology_relpath,
                        content=xml,
                        pattern="(auto-topology)",
                        instance_label="topology",
                    ))
                    n_groups = len(topo_data.get("nodes", []))
                    console.print(
                        f"[dim]Auto-derived topology: {n_groups} top-level "
                        f"group(s)[/dim]"
                    )
                except Exception as exc:  # noqa: BLE001
                    console.print(
                        f"[yellow]Topology derivation produced invalid output: "
                        f"{type(exc).__name__}: {str(exc)[:120]}[/yellow]"
                    )

    # Auto-derive a stub LocationSets.xml when no user yaml exists.
    # Stubs are id-only; configurator fills in the data backing later.
    locsets_spec = next(
        (s for s in _SPECS if s.name == "locationSetsFile"), None,
    )
    if locsets_spec:
        locsets_relpath = str(locsets_spec.output_relpath).replace("\\", "/")
        already_have_locsets = any(
            rf.relpath.replace("\\", "/") == locsets_relpath
            for rf in result.rendered_files
        )
        if not already_have_locsets:
            from fews_agent.agent.locationsets_derivation import (
                derive_locationsets_yaml,
            )
            ls_data = derive_locationsets_yaml(
                result.rendered_files, extra_sets=csvfile_locsets or None,
            )
            if ls_data:
                try:
                    from fews_agent.agent.blueprint import RenderedFile
                    from fews_agent.generators.base import (
                        render as render_template,
                    )
                    model = locsets_spec.model_class.model_validate(ls_data)
                    xml = render_template(locsets_spec.template_name, model)
                    result.rendered_files.append(RenderedFile(
                        relpath=locsets_relpath,
                        content=xml,
                        pattern="(auto-locsets)",
                        instance_label="locationSetsFile",
                    ))
                    body = ls_data.get("body", [])
                    n_total = len(body)
                    n_populated = sum(
                        1 for e in body
                        if e.get("locationSet", {}).get("locationId")
                    )
                    n_stubs = n_total - n_populated
                    if n_populated:
                        console.print(
                            f"[dim]Auto-derived LocationSets: {n_populated} "
                            f"interpolation station set(s) populated from "
                            f"Locations.xml"
                            + (
                                f", {n_stubs} id-only stub(s) for the "
                                f"configurator to back"
                                if n_stubs else ""
                            )
                            + "[/dim]"
                        )
                    else:
                        console.print(
                            f"[yellow]Auto-stubbed LocationSets: {n_stubs} "
                            f"id-only stub(s) — configurator must fill csv/"
                            f"shapefile backing[/yellow]"
                        )
                except Exception as exc:  # noqa: BLE001
                    console.print(
                        f"[yellow]LocationSets stub invalid: "
                        f"{type(exc).__name__}: {str(exc)[:120]}[/yellow]"
                    )

    # Loud failure: an interpolation that writes to a station set with no
    # backing produces no point time series. This usually means
    # locations.csv (the interpolation targets) wasn't provided. Warn
    # rather than ship a silently inert interpolation. Runs independent of
    # the deriver above, so it also catches a user-provided LocationSets
    # yaml that left an interpolation set as a bare stub.
    from fews_agent.agent.locationsets_derivation import (
        unbacked_interpolation_station_sets,
    )
    _unbacked = unbacked_interpolation_station_sets(result.rendered_files)
    if _unbacked:
        _sets = ", ".join(sorted(_unbacked))
        console.print(Panel(
            f"Interpolation writes to locationSet(s) {_sets}, but they have "
            f"no backing data (empty id-only stubs). The interpolation will "
            f"produce no point time series until they are populated.\n"
            f"Fix: provide a locations.csv (the station targets) in inputs/, "
            f"or back the set with a csvFile / esriShapeFile in a "
            f"locationSetsFile.yaml.",
            title="Warning: interpolation has no station targets",
            border_style="yellow",
        ))

    # Auto-derive descriptor singletons from rendered XMLs. Only fires
    # for descriptor specs that aren't already produced by patterns or
    # by user-provided yamls.
    derived = derive_descriptor_singletons(result.rendered_files)
    if derived:
        result.rendered_files.extend(derived)
        console.print(
            f"[dim]Auto-derived descriptors: "
            f"{', '.join(d.instance_label for d in derived)}[/dim]"
        )

    # Auto-derive sa_global.Properties so FEWS can resolve runtime
    # placeholders ($MODELNAME1$, $TIMEZONE$, $DAY_TIMESTEP$, ...).
    # Without this file, FEWS won't load the config — placeholders are
    # left literal by both patterns and bundled standards on purpose
    # (FEWS, not the agent, owns runtime substitution).
    sa_relpath = "RootConfigFiles/sa_global.Properties"
    already_have_sa = any(
        rf.relpath.replace("\\", "/") == sa_relpath
        for rf in result.rendered_files
    )
    if not already_have_sa:
        from fews_agent.agent.global_properties_derivation import (
            derive_global_properties,
        )
        sa_text = derive_global_properties(bp)
        if sa_text:
            from fews_agent.agent.blueprint import RenderedFile
            result.rendered_files.append(RenderedFile(
                relpath=sa_relpath,
                content=sa_text,
                pattern="(auto-globals)",
                instance_label="sa_global.Properties",
            ))
            console.print(
                f"[dim]Auto-derived sa_global.Properties for FEWS "
                f"runtime placeholder resolution[/dim]"
            )

    if result.errors:
        for err in result.errors:
            console.print(f"[red]error:[/red] {err}")

    manifest = write_output(result, output_root)

    # Static-asset mirror: ``inputs/assets/<subpath>`` → ``<output_root>/<subpath>``.
    # Convention for non-generated, non-validated, configurator-supplied
    # files (shapefile metadata, third-party binary distributions, map
    # layer XMLs). Subdir structure is preserved verbatim.
    if inputs_dir is not None:
        assets_dir = inputs_dir / "assets"
        if assets_dir.is_dir():
            n_assets = 0
            for src in assets_dir.rglob("*"):
                if not src.is_file():
                    continue
                rel = src.relative_to(assets_dir)
                dst = output_root / rel
                dst.parent.mkdir(parents=True, exist_ok=True)
                import shutil as _shutil
                _shutil.copy2(src, dst)
                manifest["written"].append({
                    "path": str(rel).replace("\\", "/"),
                    "pattern": "(asset)",
                    "instance": "asset-mirror",
                    "bytes": src.stat().st_size,
                })
                n_assets += 1
            if n_assets:
                console.print(
                    f"[dim]Mirrored {n_assets} static asset(s) from "
                    f"inputs/assets/[/dim]"
                )

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
    n_non_xml = 0
    for entry in manifest["written"]:
        file_path = output_root / entry["path"]
        data = file_path.read_bytes()
        if entry["pattern"] == "(asset)":
            # Mirrored static asset (configurator-provided, often non-FEWS XSD).
            xsd_ok, xsd_msg = True, "(asset)"
            n_non_xml += 1
        elif not entry["path"].lower().endswith(".xml"):
            # Non-XML outputs (sa_global.Properties etc.) — XSD doesn't apply.
            xsd_ok, xsd_msg = True, "(not XML)"
            n_non_xml += 1
        else:
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
        f"[bold]XSD-valid:[/bold] {n_xsd_ok}/{len(manifest['written']) - n_non_xml}"
        + (f" (+{n_non_xml} non-XML)" if n_non_xml else ""),
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

    n_xml = len(manifest["written"]) - n_non_xml
    summary = {
        # ``ok`` is the overall pass/fail. Requires every XML file to
        # be XSD-valid AND no render-time errors (which include
        # Pydantic model-construction failures — those don't show up
        # in the file table because the file simply isn't written).
        # Non-XML outputs (sa_global.Properties, mirrored assets) are
        # excluded from the XSD denominator — they don't have an XSD
        # to validate against.
        "ok": n_xsd_ok == n_xml and not result.errors,
        "blueprint": bp.name,
        "output_root": str(output_root),
        "files_total": len(manifest["written"]),
        "files_xml": n_xml,
        "files_non_xml": n_non_xml,
        "files_xsd_ok": n_xsd_ok,
        # Render-time errors collected during pattern expansion + per-spec
        # render. Surfacing these alongside the XSD report lets a UI
        # distinguish "Pydantic validation failed" (errors populated,
        # file missing) from "XSD validation failed" (file present,
        # xsd_ok=False).
        "errors": list(result.errors),
        # Interpolation station sets left unbacked (no locations.csv / no
        # csvFile backing) — the interpolation resolves to nothing. Empty
        # list is the healthy case. Lets the chat `done` path re-surface
        # the warning to the configurator.
        "unbacked_interpolation_sets": sorted(_unbacked),
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


def build_phase(
    blueprint_path: Path,
    pattern_root: Path,
    phase: str,
    *,
    console: Console | None = None,
) -> dict:
    """Render + XSD-validate ONLY the patterns belonging to one phase.

    This is the per-module (capability-group) build used by the guided
    flow. It deliberately does NOT run the singleton merge, bundled
    standards, derivers, or the semantic cross-reference check — those
    need the whole project and belong to final assembly (``done`` →
    :func:`build_from_blueprint`). Here we render just this phase's
    pattern outputs into the shared output tree and confirm each file is
    XSD-valid, so the user sees concrete, valid files for one capability
    before moving on.

    Files accumulate in the same ``output_root`` across phase builds.
    """
    if console is None:
        console = Console()

    bp = load_blueprint(blueprint_path, pattern_root)
    output_root = (blueprint_path.parent / bp.output_root).resolve()
    output_root.mkdir(parents=True, exist_ok=True)

    phase_patterns = [
        p for p in bp.patterns if classify_phase(p.pattern) == phase
    ]

    console.print(Panel(
        f"[bold]Phase:[/bold] {phase} — {PHASE_LABELS.get(phase, '')}\n"
        f"[dim]blueprint: {bp.name}[/dim]\n"
        f"[dim]output: {output_root}[/dim]\n"
        f"[bold]{len(phase_patterns)}[/bold] pattern(s) in this phase",
        border_style="cyan",
    ))

    if not phase_patterns:
        console.print(
            f"[yellow]No patterns resolved for phase '{phase}'. "
            f"Nothing to build yet.[/yellow]"
        )
        return {
            "ok": True, "phase": phase, "files_total": 0,
            "files_xsd_ok": 0, "errors": [],
        }

    sub_bp = Blueprint(
        name=f"{bp.name} [{phase}]",
        output_root=bp.output_root,
        patterns=phase_patterns,
        singleton_seeds=bp.singleton_seeds,
    )
    result = expand(sub_bp, pattern_root)
    if result.errors:
        for err in result.errors:
            console.print(f"[red]error:[/red] {err}")
        return {
            "ok": False, "phase": phase, "files_total": 0,
            "files_xsd_ok": 0, "errors": list(result.errors),
        }

    manifest = write_output(result, output_root)

    table = Table(
        title=f"Phase '{phase}' — files ({len(manifest['written'])})",
        show_lines=False,
    )
    table.add_column("file", overflow="fold")
    table.add_column("pattern")
    table.add_column("instance")
    table.add_column("xsd", justify="center")

    n_xsd_ok = 0
    n_non_xml = 0
    files_report = []
    for entry in manifest["written"]:
        file_path = output_root / entry["path"]
        data = file_path.read_bytes()
        if not entry["path"].lower().endswith(".xml"):
            xsd_ok, xsd_msg = True, "(not XML)"
            n_non_xml += 1
        else:
            xsd_ok, xsd_msg = validate_xsd(data)
            if xsd_ok:
                n_xsd_ok += 1
        table.add_row(
            entry["path"],
            entry["pattern"].split("/")[-1],
            entry["instance"],
            "[green]OK[/green]" if xsd_ok else "[red]FAIL[/red]",
        )
        files_report.append(
            {"path": entry["path"], "xsd_ok": xsd_ok, "xsd_msg": xsd_msg}
        )

    console.print(table)
    n_xml = len(manifest["written"]) - n_non_xml
    ok = n_xsd_ok == n_xml and not result.errors
    border = "green" if ok else "yellow"
    console.print(Panel(
        f"[bold]Phase '{phase}' built:[/bold] "
        f"{len(manifest['written'])} file(s), "
        f"XSD-valid {n_xsd_ok}/{n_xml}"
        + (f" (+{n_non_xml} non-XML)" if n_non_xml else "")
        + "\n[dim]Cross-file references are checked at final assembly "
          "(done).[/dim]",
        title="Phase complete", border_style=border,
    ))
    return {
        "ok": ok,
        "phase": phase,
        "files_total": len(manifest["written"]),
        "files_xml": n_xml,
        "files_xsd_ok": n_xsd_ok,
        "errors": list(result.errors),
        "files": files_report,
    }


def _instance_matches(inst: dict, match: dict | None) -> bool:
    """True if every key/value in ``match`` is present and equal in ``inst``.

    ``match`` is a label-only dict (e.g. ``{"nwp_name": "GFS"}``) so a
    single module can be selected out of a pattern that has several
    instances. ``None`` matches everything.
    """
    if not match:
        return True
    return all(inst.get(k) == v for k, v in match.items())


def build_module(
    blueprint_path: Path,
    pattern_root: Path,
    pattern: str,
    instance_match: dict | None = None,
    *,
    console: Console | None = None,
) -> dict:
    """Render + XSD-validate ONE module — a single pattern, optionally a
    single instance within it.

    The per-import (finest) granularity of the guided flow: build just
    "the GFS import" rather than the whole imports phase. Like
    :func:`build_phase`, it skips the singleton merge, bundled standards,
    derivers, and the semantic cross-reference check — those belong to
    final assembly (``done``). Files accumulate in the shared
    ``output_root`` alongside any other phase/module builds.
    """
    if console is None:
        console = Console()

    bp = load_blueprint(blueprint_path, pattern_root)
    output_root = (blueprint_path.parent / bp.output_root).resolve()
    output_root.mkdir(parents=True, exist_ok=True)

    matched: list[PatternRef] = []
    for p in bp.patterns:
        if p.pattern != pattern:
            continue
        insts = [i for i in p.instances if _instance_matches(i, instance_match)]
        if insts:
            matched.append(PatternRef(pattern=p.pattern, instances=insts))

    label = pattern.rsplit("/", 1)[-1]
    if instance_match:
        label += " " + ", ".join(f"{k}={v}" for k, v in instance_match.items())

    console.print(Panel(
        f"[bold]Module:[/bold] {label}\n"
        f"[dim]blueprint: {bp.name}[/dim]\n"
        f"[dim]output: {output_root}[/dim]\n"
        f"[bold]{sum(len(m.instances) for m in matched)}[/bold] "
        f"instance(s) to build",
        border_style="cyan",
    ))

    if not matched:
        console.print(
            f"[yellow]No instance of '{pattern}'"
            + (f" matching {instance_match}" if instance_match else "")
            + " is in the project. Nothing to build.[/yellow]"
        )
        return {
            "ok": False, "module": pattern, "files_total": 0,
            "files_xsd_ok": 0, "errors": ["no matching instance"],
        }

    sub_bp = Blueprint(
        name=f"{bp.name} [{label}]",
        output_root=bp.output_root,
        patterns=matched,
        singleton_seeds=bp.singleton_seeds,
    )
    result = expand(sub_bp, pattern_root)
    if result.errors:
        for err in result.errors:
            console.print(f"[red]error:[/red] {err}")
        return {
            "ok": False, "module": pattern, "files_total": 0,
            "files_xsd_ok": 0, "errors": list(result.errors),
        }

    manifest = write_output(result, output_root)

    table = Table(
        title=f"Module '{label}' — files ({len(manifest['written'])})",
        show_lines=False,
    )
    table.add_column("file", overflow="fold")
    table.add_column("pattern")
    table.add_column("instance")
    table.add_column("xsd", justify="center")

    n_xsd_ok = 0
    n_non_xml = 0
    files_report = []
    for entry in manifest["written"]:
        file_path = output_root / entry["path"]
        data = file_path.read_bytes()
        if not entry["path"].lower().endswith(".xml"):
            xsd_ok, xsd_msg = True, "(not XML)"
            n_non_xml += 1
        else:
            xsd_ok, xsd_msg = validate_xsd(data)
            if xsd_ok:
                n_xsd_ok += 1
        table.add_row(
            entry["path"],
            entry["pattern"].split("/")[-1],
            entry["instance"],
            "[green]OK[/green]" if xsd_ok else "[red]FAIL[/red]",
        )
        files_report.append(
            {"path": entry["path"], "xsd_ok": xsd_ok, "xsd_msg": xsd_msg}
        )

    console.print(table)
    n_xml = len(manifest["written"]) - n_non_xml
    ok = n_xsd_ok == n_xml and not result.errors
    border = "green" if ok else "yellow"
    console.print(Panel(
        f"[bold]Module '{label}' built:[/bold] "
        f"{len(manifest['written'])} file(s), "
        f"XSD-valid {n_xsd_ok}/{n_xml}"
        + (f" (+{n_non_xml} non-XML)" if n_non_xml else "")
        + "\n[dim]Cross-file references are checked at final assembly "
          "(done).[/dim]",
        title="Module complete", border_style=border,
    ))
    return {
        "ok": ok,
        "module": pattern,
        "instance_match": instance_match,
        "files_total": len(manifest["written"]),
        "files_xml": n_xml,
        "files_xsd_ok": n_xsd_ok,
        "errors": list(result.errors),
        "files": files_report,
    }


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
    parser.add_argument(
        "--phase",
        default=None,
        help=(
            "Build only one capability group (imports / process / model / "
            "visualize) instead of the whole project. Renders + XSD-"
            "validates just that phase's pattern outputs."
        ),
    )
    parser.add_argument(
        "--module",
        default=None,
        help=(
            "Build only one pattern (e.g. auto/nwp_grid_noaa) instead of the "
            "whole project — finer than --phase. Optionally narrow to a "
            "single instance with --instance-match 'nwp_name=GFS'."
        ),
    )
    parser.add_argument(
        "--instance-match",
        default=None,
        help=(
            "With --module, select one instance via 'key=value' (e.g. "
            "'nwp_name=GFS'). Omit to build all instances of the pattern."
        ),
    )
    args = parser.parse_args(argv)

    blueprint_path = Path(args.blueprint).resolve()
    if args.module:
        match: dict | None = None
        if args.instance_match and "=" in args.instance_match:
            k, _, v = args.instance_match.partition("=")
            match = {k.strip(): v.strip()}
        summary = build_module(
            blueprint_path=blueprint_path,
            pattern_root=Path(args.pattern_root).resolve(),
            pattern=args.module,
            instance_match=match,
        )
        return 0 if summary.get("ok") else 1
    if args.phase:
        summary = build_phase(
            blueprint_path=blueprint_path,
            pattern_root=Path(args.pattern_root).resolve(),
            phase=args.phase,
        )
        return 0 if summary.get("ok") else 1
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
