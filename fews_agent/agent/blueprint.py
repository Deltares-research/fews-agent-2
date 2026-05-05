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


def load_blueprint(path: Path, pattern_root: Path) -> Blueprint:
    """Parse a YAML blueprint, resolve CSV instance loaders."""
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))

    bp = Blueprint(
        name=raw["name"],
        output_root=Path(raw.get("output_root") or path.parent / "out"),
        metadata=raw.get("metadata", {}),
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
    """Walk the blueprint, render every instance of every pattern."""
    result = ExpandResult()

    for pat_ref in blueprint.patterns:
        pat_dir = pattern_root / pat_ref.pattern
        if not pat_dir.is_dir():
            result.errors.append(f"pattern dir missing: {pat_dir}")
            continue
        spec = yaml.safe_load(
            (pat_dir / "pattern.yaml").read_text(encoding="utf-8")
        )
        env = Environment(
            loader=FileSystemLoader(str(pat_dir)),
            undefined=StrictUndefined,
            keep_trailing_newline=True,
        )

        for inst in pat_ref.instances:
            label = str(inst.get("nwp_name") or inst.get("_label") or "?")
            try:
                full_vars = _apply_defaults(spec, inst)
            except ValueError as e:
                result.errors.append(
                    f"{pat_ref.pattern}#{label}: {e}"
                )
                continue

            for file_spec in spec.get("files", []):
                out_relpath = env.from_string(file_spec["output"]).render(**full_vars)
                template = env.get_template(file_spec["template"])
                content = template.render(**full_vars)
                result.rendered_files.append(
                    RenderedFile(
                        relpath=out_relpath,
                        content=content,
                        pattern=pat_ref.pattern,
                        instance_label=label,
                    )
                )

            for target_file, contributions in spec.get("contributions", {}).items():
                for entry in contributions:
                    payload = _render_dict(entry, env, full_vars)
                    result.contributions.append(
                        Contribution(
                            target_file=target_file,
                            payload=payload,
                            pattern=pat_ref.pattern,
                            instance_label=label,
                        )
                    )

    return result


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
