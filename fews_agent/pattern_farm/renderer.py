"""PatternSpec → ``patterns/auto/<name>/pattern.yaml``.

Single YAML dump, ordering matched to the existing patterns so
diffs against an oracle pattern read cleanly.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from .ir import PatternSpec


def write_pattern_yaml(spec: PatternSpec, target_dir: Path) -> Path:
    """Write ``pattern.yaml`` under ``target_dir`` (created if missing)."""
    target_dir.mkdir(parents=True, exist_ok=True)
    payload = to_yaml_dict(spec)
    out = target_dir / "pattern.yaml"
    out.write_text(
        yaml.safe_dump(payload, sort_keys=False, default_flow_style=False),
        encoding="utf-8",
    )
    return out


def to_yaml_dict(spec: PatternSpec) -> dict[str, Any]:
    """Produce a dict whose key order matches existing patterns."""
    out: dict[str, Any] = {"name": spec.name}
    if spec.description:
        out["description"] = spec.description
    out["variables"] = {
        name: _variable_dict(var)
        for name, var in spec.variables.items()
    }
    out["outputs"] = [_output_dict(o) for o in spec.outputs]
    out["contributions"] = spec.contributions
    return out


def _variable_dict(var: Any) -> dict[str, Any]:
    d: dict[str, Any] = {"type": var.type, "required": var.required}
    if var.default is not None:
        d["default"] = var.default
    return d


def _output_dict(o: Any) -> dict[str, Any]:
    return {
        "schema": o.schema_class,
        "output": o.output,
        "data": o.data,
    }
