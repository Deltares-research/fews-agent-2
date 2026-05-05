"""Round-trip a pattern: instantiate it, diff against the tutorial.

Given a pattern dir + a list of variable bindings, this tool:

  1. Loads the pattern's variables and Jinja templates.
  2. Renders each output file under ``/tmp/pattern_check/<output>``.
  3. Canonicalizes the rendered XML and the matching tutorial XML.
  4. Reports byte-equivalence per file.

Use this to validate that a hand-written pattern reproduces tutorial
output before declaring the pattern "done". If the diff is non-empty,
the pattern's templates are wrong (or the variable bindings are
incomplete).

Usage::

    python scripts/validate_pattern.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import yaml
from jinja2 import Environment, FileSystemLoader, StrictUndefined

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from fews_agent.generators.base import canonicalize  # noqa: E402

TUTORIAL = REPO_ROOT / "examples" / "config-tutorial"


def render_pattern(
    pattern_dir: Path,
    variables: dict,
    out_dir: Path,
) -> list[tuple[Path, Path]]:
    """Render the pattern under ``out_dir``. Return list of (output, tutorial)."""
    spec = yaml.safe_load((pattern_dir / "pattern.yaml").read_text(encoding="utf-8"))
    env = Environment(
        loader=FileSystemLoader(str(pattern_dir)),
        undefined=StrictUndefined,
        keep_trailing_newline=True,
    )

    # Apply defaults from the pattern spec (variable defaults).
    full_vars = {}
    for var_name, var_spec in spec.get("variables", {}).items():
        if var_name in variables:
            full_vars[var_name] = variables[var_name]
        elif "default" in var_spec:
            full_vars[var_name] = var_spec["default"]
        elif var_spec.get("required"):
            raise ValueError(f"missing required variable: {var_name}")

    rendered: list[tuple[Path, Path]] = []
    for file_spec in spec["files"]:
        # Output paths can also be templated.
        out_relpath = env.from_string(file_spec["output"]).render(**full_vars)
        out_path = out_dir / out_relpath
        out_path.parent.mkdir(parents=True, exist_ok=True)
        template = env.get_template(file_spec["template"])
        out_path.write_text(template.render(**full_vars), encoding="utf-8")
        tutorial_path = TUTORIAL / out_relpath
        rendered.append((out_path, tutorial_path))

    return rendered


def diff_pattern(
    pattern_dir: Path,
    instances: list[dict],
    out_root: Path,
) -> dict:
    """Render each instance, return a per-file equivalence report."""
    out_root.mkdir(parents=True, exist_ok=True)
    summary = {
        "pattern": pattern_dir.name,
        "instances": [],
    }
    for inst in instances:
        instance_name = inst.get(
            "_label", inst.get("nwp_name", "unnamed")
        )
        out_dir = out_root / instance_name
        rendered = render_pattern(pattern_dir, inst, out_dir)
        files: list[dict] = []
        for out_path, tut_path in rendered:
            entry = {
                "file": str(tut_path.relative_to(TUTORIAL)).replace("\\", "/"),
                "rendered_exists": out_path.is_file(),
                "tutorial_exists": tut_path.is_file(),
            }
            if entry["rendered_exists"] and entry["tutorial_exists"]:
                rendered_bytes = out_path.read_bytes()
                tutorial_bytes = tut_path.read_bytes()
                try:
                    entry["byte_equivalent"] = (
                        canonicalize(rendered_bytes) == canonicalize(tutorial_bytes)
                    )
                except Exception as exc:
                    entry["byte_equivalent"] = False
                    entry["error"] = str(exc)
            files.append(entry)
        summary["instances"].append({"name": instance_name, "files": files})
    return summary


if __name__ == "__main__":
    pattern_dir = REPO_ROOT / "patterns" / "imports" / "nwp_grid"
    out_root = REPO_ROOT / "data" / "patterns" / "_validate"

    # Two instances drawn from the tutorial — should both be byte-equivalent
    # to ImportHRDPS.xml / ImportGDPS.xml + their workflow files.
    instances = [
        {
            "_label": "HRDPS",
            "nwp_name": "HRDPS",
            "time_step_hours": 1,
            "forecast_horizon_hours": 48,
            "start_lookback_hours": 1,
            "expiry_time_days": 7,
            "subset_property_kind": "bool",
            "subset_property_key": "useSubset",
            "subset_property_value": "false",
        },
        {
            "_label": "GDPS",
            "nwp_name": "GDPS",
            "time_step_hours": 3,
            "forecast_horizon_hours": 240,
            "start_lookback_hours": 3,
            "expiry_time_days": 7,
            "subset_property_kind": "string",
            "subset_property_key": "subsettingCrs",
            "subset_property_value": "EPSG:4326",
            "workflow_shape": "delegated",
        },
        {
            "_label": "RDPS",
            "nwp_name": "RDPS",
            "time_step_hours": 3,
            "forecast_horizon_hours": 72,
            "start_lookback_hours": 3,
            "expiry_time_days": 7,
            "subset_property_kind": "bool",
            "subset_property_key": "useSubset",
            "subset_property_value": "false",
            "workflow_shape": "delegated",
        },
    ]

    summary = diff_pattern(pattern_dir, instances, out_root)
    import json
    print(json.dumps(summary, indent=2))

    n_total = sum(len(i["files"]) for i in summary["instances"])
    n_eq = sum(
        1 for i in summary["instances"] for f in i["files"]
        if f.get("byte_equivalent")
    )
    print(f"\n{n_eq}/{n_total} files byte-equivalent")
    sys.exit(0 if n_eq == n_total else 1)
