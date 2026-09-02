"""Project blueprint — high-level recipe that expands to ~100 XML files.

A blueprint is a small YAML file the configurator authors per project.
It declares which patterns the project uses, how many instances of
each, and the per-instance variable bindings. The expander walks the
blueprint, instantiates every pattern (rendering its Jinja templates
into the output tree), and merges cross-pattern contributions into
singleton files.

Blueprint shape::

    name: rhine-flood-forecast
    output_root: examples/generated-config-tutorial
    patterns:
      - pattern: imports/nwp_grid
        instances:
          - {nwp_name: HRDPS, time_step_hours: 1, ...}
          - {nwp_name: GDPS,  time_step_hours: 3, ...}

Instances may also pull from CSVs::

    instances:
      from_csv: nwps.csv

The expander is deliberately small. It does *not* inject a wizard, an
LLM, or anything fuzzy — that's the upstream concern. Its job is:
"given a fully-specified blueprint, write the files".
"""
from __future__ import annotations

import csv
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from jinja2 import Environment, FileSystemLoader, StrictUndefined

from fews_agent.generators.base import render as render_template

from .pattern_family import merge_family_variables


# ---------------------------------------------------------------------------
# Schema and template registries derived from SPECS
# ---------------------------------------------------------------------------

_SCHEMA_BY_NAME: dict[str, type] | None = None
_TEMPLATE_BY_SCHEMA: dict[type, str] | None = None


def _build_registries() -> None:
    """Lazy-build schema-name → class and class → template lookups."""
    global _SCHEMA_BY_NAME, _TEMPLATE_BY_SCHEMA
    if _SCHEMA_BY_NAME is not None:
        return
    from fews_agent.generators import SPECS

    _SCHEMA_BY_NAME = {}
    _TEMPLATE_BY_SCHEMA = {}
    for s in SPECS:
        _SCHEMA_BY_NAME[s.model_class.__name__] = s.model_class
        # Mapping is 1:1 (verified) — last write wins on duplicates.
        _TEMPLATE_BY_SCHEMA[s.model_class] = s.template_name


def schema_class_for(name: str) -> type:
    """Look up Pydantic class by name (e.g. 'TimeSeriesImportRun')."""
    _build_registries()
    cls = _SCHEMA_BY_NAME.get(name)
    if cls is None:
        raise KeyError(
            f"unknown schema {name!r}; "
            f"valid: {sorted(_SCHEMA_BY_NAME)[:5]}... "
            f"({len(_SCHEMA_BY_NAME)} total)"
        )
    return cls


def template_for_schema(cls: type) -> str:
    _build_registries()
    tpl = _TEMPLATE_BY_SCHEMA.get(cls)
    if tpl is None:
        raise KeyError(f"no Jinja template registered for {cls.__name__}")
    return tpl


# ---------------------------------------------------------------------------
# Blueprint loading
# ---------------------------------------------------------------------------

@dataclass
class PatternRef:
    """One ``patterns:`` entry from the blueprint."""

    pattern: str  # path under PATTERN_ROOT, e.g. "imports/nwp_grid"
    instances: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class Blueprint:
    name: str
    output_root: Path
    patterns: list[PatternRef] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    # Singleton-class-level seed data, keyed by class name. Each value
    # is a partial dict (e.g. {"geoDatum": "WGS 1984"}) that the merger
    # uses as the starting state before appending pattern contributions.
    singleton_seeds: dict[str, dict[str, Any]] = field(default_factory=dict)
    # Direct singletons: SPEC names to render straight from a JSON
    # seed file (no pattern, no contributions, no CSV). For project-
    # specific config files like Filters, Topology, DisplayGroups
    # whose content doesn't generalise into a reusable pattern.
    direct_singletons_source: Path | None = None
    direct_singletons_specs: list[str] = field(default_factory=list)


def load_blueprint(path: Path, pattern_root: Path) -> Blueprint:
    """Parse a YAML blueprint, resolve CSV instance loaders."""
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))

    direct = raw.get("direct_singletons", {}) or {}
    direct_source = (
        path.parent / direct["source"] if direct.get("source") else None
    )
    bp = Blueprint(
        name=raw["name"],
        output_root=Path(raw.get("output_root") or path.parent / "out"),
        metadata=raw.get("metadata", {}),
        singleton_seeds=raw.get("singleton_seeds", {}),
        direct_singletons_source=direct_source,
        direct_singletons_specs=list(direct.get("specs") or []),
    )

    for entry in raw.get("patterns", []):
        instances_decl = entry.get("instances") or []
        instances = _resolve_instances(instances_decl, blueprint_dir=path.parent)
        bp.patterns.append(
            PatternRef(pattern=entry["pattern"], instances=instances)
        )

    return bp


def _resolve_instances(
    decl: Any, blueprint_dir: Path
) -> list[dict[str, Any]]:
    """Convert a blueprint ``instances:`` decl into a flat list of dicts.

    Supports two shapes:
      - inline list of dicts
      - ``{from_csv: file.csv}`` — each CSV row becomes one instance
    """
    if isinstance(decl, list):
        return [dict(item) for item in decl]
    if isinstance(decl, dict) and "from_csv" in decl:
        csv_path = blueprint_dir / decl["from_csv"]
        with csv_path.open(encoding="utf-8-sig", newline="") as fh:
            reader = csv.DictReader(fh)
            rows = [{k: _coerce(v) for k, v in row.items()} for row in reader]
        return rows
    raise ValueError(f"unsupported instances declaration: {decl!r}")


def _coerce(value: str) -> Any:
    """CSV values come in as strings; coerce ints / bools where obvious."""
    if value is None or value == "":
        return value
    s = value.strip()
    # int
    if s.lstrip("-").isdigit():
        return int(s)
    # float
    try:
        return float(s) if "." in s else value
    except ValueError:
        pass
    # bool
    if s.lower() in {"true", "false"}:
        return s.lower() == "true"
    return value


# ---------------------------------------------------------------------------
# Pattern rendering
# ---------------------------------------------------------------------------

@dataclass
class RenderedFile:
    """One file produced by one pattern instance."""

    relpath: str
    content: str
    pattern: str
    instance_label: str
    # The Pydantic instance the content was rendered from, when the
    # render site had one (generic-body copies / non-XML outputs leave
    # it None). Kept so the full build can run the cross-file semantic
    # pass without re-parsing the XML. Not part of the write manifest.
    model: Any = None


@dataclass
class Contribution:
    """One pattern contribution to a singleton file."""

    target_file: str        # e.g. "ModuleInstanceDescriptors.xml"
    payload: dict[str, Any]  # an entry to merge into that file
    pattern: str
    instance_label: str


@dataclass
class ExpandResult:
    rendered_files: list[RenderedFile] = field(default_factory=list)
    contributions: list[Contribution] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def expand(
    blueprint: Blueprint,
    pattern_root: Path,
) -> ExpandResult:
    """Walk the blueprint, render every instance of every pattern.

    Per-instance render loop:
      1. Read pattern.yaml as raw text.
      2. Apply Jinja with the instance's variables to the WHOLE text
         (this lets `{% if %}` blocks inside `data:` produce
         conditional structure).
      3. Parse the rendered text as YAML — gives a python dict.
      4. For each output: look up Pydantic class by `schema:`,
         model_validate the `data:` block, render with the existing
         Jinja template registered for that class.
      5. Collect contributions, render their items.
    """
    result = ExpandResult()
    # Loader lets a pattern.yaml `{% import '_partials/x.yaml.j2' as m %}` a
    # shared macro (e.g. idmap_from_parameters) instead of duplicating the
    # same Jinja block across patterns. Rooted at pattern_root so the import
    # path is relative to patterns/ (matches `_partials/...` used in
    # pattern.yaml files).
    loader = FileSystemLoader(str(pattern_root))
    # Strict env for the per-instance render (real vars must be defined).
    raw_env = Environment(
        loader=loader, undefined=StrictUndefined, keep_trailing_newline=True,
    )
    # Permissive env for the variables-discovery pass — pattern.yaml may
    # contain {% if %} blocks inside `data:` that need Jinja evaluation
    # before YAML can parse it. With default Undefined, conditionals
    # comparing to literal strings collapse to falsy and blocks empty.
    discovery_env = Environment(loader=loader, keep_trailing_newline=True)

    for pat_ref in blueprint.patterns:
        pat_dir = pattern_root / pat_ref.pattern
        pat_yaml_path = pat_dir / "pattern.yaml"
        if not pat_yaml_path.is_file():
            result.errors.append(f"pattern.yaml missing: {pat_yaml_path}")
            continue
        raw_text = pat_yaml_path.read_text(encoding="utf-8")
        # First pass: render with empty context to strip Jinja syntax,
        # then parse YAML to extract variables section. Conditional
        # blocks evaluate to empty here (their content reappears below
        # when the per-instance render runs with real vars).
        try:
            stripped = discovery_env.from_string(raw_text).render()
            spec_for_vars = yaml.safe_load(stripped)
        except Exception as exc:  # noqa: BLE001
            result.errors.append(
                f"{pat_ref.pattern}: variables-discovery parse failed: {exc}"
            )
            continue
        spec_for_vars = merge_family_variables(
            spec_for_vars, pat_yaml_path, raw_text,
        )

        for inst in pat_ref.instances:
            # Best-effort label for telemetry. Try common pattern keys
            # in order; fall back to "?" only if none found.
            label = str(
                inst.get("_label")
                or inst.get("nwp_name")
                or inst.get("basin_name")
                or inst.get("id")
                or inst.get("name")
                or "?"
            )
            try:
                full_vars = _apply_defaults(spec_for_vars, inst)
            except ValueError as e:
                result.errors.append(f"{pat_ref.pattern}#{label}: {e}")
                continue

            # Render the entire pattern.yaml text with this instance's
            # vars, so {% if %} blocks materialise the correct shape.
            try:
                rendered_text = raw_env.from_string(raw_text).render(**full_vars)
                spec = yaml.safe_load(rendered_text)
            except Exception as exc:  # noqa: BLE001
                result.errors.append(
                    f"{pat_ref.pattern}#{label}: pattern.yaml render/parse "
                    f"failed: {exc}"
                )
                continue

            # 1) Render each output via Pydantic + existing template.
            for output in spec.get("outputs", []):
                schema_name = output.get("schema")
                out_relpath = output.get("output")
                data = output.get("data")
                if not (schema_name and out_relpath and data is not None):
                    result.errors.append(
                        f"{pat_ref.pattern}#{label}: output missing "
                        f"schema/output/data"
                    )
                    continue
                try:
                    cls = schema_class_for(schema_name)
                    # No pre-coercion — Pydantic v2 handles "1"→1,
                    # "true"→True for typed fields, and leaves strings
                    # alone for `str` fields. Context-free coercion
                    # would break things like `version: "1.1"`.
                    model = cls.model_validate(data)
                    template_name = template_for_schema(cls)
                    xml = render_template(template_name, model)
                except Exception as exc:  # noqa: BLE001
                    result.errors.append(
                        f"{pat_ref.pattern}#{label} → {schema_name}: "
                        f"{type(exc).__name__}: {exc}"
                    )
                    continue
                result.rendered_files.append(
                    RenderedFile(
                        relpath=out_relpath,
                        content=xml,
                        pattern=pat_ref.pattern,
                        instance_label=label,
                        model=model,
                    )
                )

            # 2) Collect contributions to singletons (merger handles
            # the actual aggregation later).
            for contrib_spec in spec.get("contributions", []):
                target = contrib_spec.get("target")
                field_name = contrib_spec.get("field")
                items = contrib_spec.get("items") or []
                for item in items:
                    result.contributions.append(
                        Contribution(
                            target_file=f"{target}::{field_name}",
                            payload=item if isinstance(item, dict) else {"_": item},
                            pattern=pat_ref.pattern,
                            instance_label=label,
                        )
                    )

    return result


# ---------------------------------------------------------------------------
# Contribution merger
# ---------------------------------------------------------------------------

def merge_contributions(
    result: ExpandResult,
    base_data: dict[str, dict[str, Any]] | None = None,
) -> list[RenderedFile]:
    """Aggregate pattern contributions into singleton XML files.

    Groups contributions by ``(target_class, field)``. For each
    target class, builds a Pydantic instance whose named field is the
    aggregated list, validates, renders via the existing template,
    returns RenderedFile entries.

    ``base_data`` allows pre-seeding singleton fields from non-pattern
    sources (e.g. ``locations.csv`` populates ``Locations.location``
    before pattern contributions are appended). Shape:
    ``{class_name: {field: [...]}}``.
    """
    base_data = base_data or {}

    # Group: (class_name, field_name) → list of payloads.
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for c in result.contributions:
        # target_file is encoded as "ClassName::fieldName"
        if "::" in c.target_file:
            cls_name, field_name = c.target_file.split("::", 1)
        else:
            # backward-compat: no field marker, skip
            continue
        grouped.setdefault((cls_name, field_name), []).append(c.payload)

    rendered: list[RenderedFile] = []
    for (cls_name, field_name), payloads in grouped.items():
        try:
            cls = schema_class_for(cls_name)
        except KeyError as exc:
            result.errors.append(f"merger: {exc}")
            continue

        # Compose the instance data: start from base (CSV-derived),
        # then append pattern contributions to the named field.
        seed = dict(base_data.get(cls_name, {}))
        existing = list(seed.get(field_name, []))
        seed[field_name] = existing + payloads

        try:
            model = cls.model_validate(seed)
            template_name = template_for_schema(cls)
            xml = render_template(template_name, model)
        except Exception as exc:  # noqa: BLE001
            result.errors.append(
                f"merger: {cls_name}::{field_name}: "
                f"{type(exc).__name__}: {exc}"
            )
            continue

        # Output path comes from the existing SPECS registry — find
        # the SPEC that uses this model_class to get its output_relpath.
        out_relpath = _output_relpath_for_class(cls)
        rendered.append(
            RenderedFile(
                relpath=out_relpath,
                content=xml,
                pattern="(merger)",
                instance_label=cls_name,
                model=model,
            )
        )
    return rendered


def _output_relpath_for_class(cls: type) -> str:
    """Find the canonical output path for a singleton class."""
    from fews_agent.generators import SPECS

    for s in SPECS:
        if s.model_class is cls:
            return str(s.output_relpath).replace("\\", "/")
    raise KeyError(f"no SPEC has model_class={cls.__name__}")


def _coerce_for_pydantic(obj: Any) -> Any:
    """Coerce string values that look like ints / bools to native types.

    Jinja substitution always produces strings; Pydantic accepts most
    coercions but a few schemas demand strict types. This walks the
    rendered dict and converts ``"1"``/``"true"``/``"false"`` to ints
    and bools where unambiguous.
    """
    if isinstance(obj, str):
        s = obj.strip()
        if s.lstrip("-").isdigit():
            return int(s)
        if s.lower() in {"true", "false"}:
            return s.lower() == "true"
        try:
            if "." in s:
                return float(s)
        except ValueError:
            pass
        return obj
    if isinstance(obj, dict):
        return {k: _coerce_for_pydantic(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_coerce_for_pydantic(v) for v in obj]
    return obj


def _apply_defaults(
    spec: dict[str, Any], instance: dict[str, Any]
) -> dict[str, Any]:
    full: dict[str, Any] = {}
    for var_name, var_spec in spec.get("variables", {}).items():
        if var_name in instance:
            full[var_name] = instance[var_name]
        elif "default" in var_spec:
            full[var_name] = var_spec["default"]
        elif var_spec.get("required"):
            raise ValueError(f"missing required variable: {var_name}")
    return full


def _render_dict(
    obj: Any, env: Environment, vars: dict[str, Any]
) -> Any:
    """Recursively render Jinja templates inside a contribution dict."""
    if isinstance(obj, str):
        return env.from_string(obj).render(**vars)
    if isinstance(obj, dict):
        return {k: _render_dict(v, env, vars) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_render_dict(v, env, vars) for v in obj]
    return obj


# ---------------------------------------------------------------------------
# Writing the output tree
# ---------------------------------------------------------------------------

def write_output(
    result: ExpandResult, output_root: Path
) -> dict[str, Any]:
    """Write every rendered file under ``output_root``. Returns a manifest."""
    output_root.mkdir(parents=True, exist_ok=True)
    written: list[dict[str, Any]] = []
    for rf in result.rendered_files:
        out_path = output_root / rf.relpath
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(rf.content, encoding="utf-8")
        written.append(
            {
                "path": str(out_path.relative_to(output_root)).replace("\\", "/"),
                "pattern": rf.pattern,
                "instance": rf.instance_label,
                "bytes": len(rf.content.encode("utf-8")),
            }
        )
    return {
        "output_root": str(output_root),
        "written": written,
        "contributions": [
            {
                "target": c.target_file,
                "pattern": c.pattern,
                "instance": c.instance_label,
                "payload": c.payload,
            }
            for c in result.contributions
        ],
        "errors": result.errors,
    }


__all__ = [
    "Blueprint",
    "PatternRef",
    "RenderedFile",
    "Contribution",
    "ExpandResult",
    "load_blueprint",
    "expand",
    "write_output",
]
