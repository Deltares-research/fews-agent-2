"""Build instances.json for the HRDPS-recreation test.

Read the existing nwp_grid_eccc_HRDPS pattern.yaml, render its
outputs once with nwp_name=HRDPS (literal data — the
pattern.yaml's data is already 'HRDPS' verbatim), once with all
'HRDPS' tokens replaced by 'GFS'. Dump the result as the farmer's
input instances. Verifying the farmer can recover {{ nwp_name }}
from these two concrete instances is the recreation test.
"""
from __future__ import annotations

import argparse
import copy
import json
import sys
from pathlib import Path
from typing import Any

import yaml
from jinja2 import Environment, StrictUndefined


def deep_substitute(obj: Any, old: str, new: str) -> Any:
    if isinstance(obj, str):
        return obj.replace(old, new)
    if isinstance(obj, dict):
        return {k: deep_substitute(v, old, new) for k, v in obj.items()}
    if isinstance(obj, list):
        return [deep_substitute(v, old, new) for v in obj]
    return obj


def render_pattern_data(
    pattern_yaml: Path, variable_values: dict[str, Any],
) -> list[dict[str, Any]]:
    """Render output[].output paths with the given vars; return a list
    of {schema, output, data} dicts. Data is left as-is (the source
    pattern.yaml's data has literal values, not Jinja).
    """
    env = Environment(undefined=StrictUndefined, keep_trailing_newline=True)
    raw = pattern_yaml.read_text(encoding="utf-8")
    rendered_text = env.from_string(raw).render(**variable_values)
    spec = yaml.safe_load(rendered_text)
    outs = []
    for o in spec["outputs"]:
        outs.append({
            "schema": o["schema"],
            "output": o["output"],
            "data": o["data"],
        })
    return outs


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--source-pattern", type=Path, required=True,
                   help="Existing pattern.yaml to use as the recreation oracle")
    p.add_argument("--source-token", required=True,
                   help="Token to substitute as the variable (e.g. HRDPS)")
    p.add_argument("--variant-token", required=True,
                   help="Token used in the synthetic second instance (e.g. GFS)")
    p.add_argument("--variable-name", default="nwp_name",
                   help="Variable name to record in variable_hints")
    p.add_argument("--out", type=Path, required=True)
    args = p.parse_args(argv)

    # Instance 1 — render the pattern with literal source token in
    # the variables (matches the data, which is hardcoded "HRDPS")
    inst1_outs = render_pattern_data(
        args.source_pattern, {args.variable_name: args.source_token},
    )
    # Instance 2 — same shape, with source→variant substituted
    # through every output.
    inst2_outs = []
    for o in inst1_outs:
        inst2_outs.append({
            "schema": o["schema"],
            "output": o["output"].replace(args.source_token, args.variant_token),
            "data": deep_substitute(o["data"], args.source_token, args.variant_token),
        })

    instances = [
        {
            "label": args.source_token,
            "variable_hints": {args.variable_name: args.source_token},
            "outputs": inst1_outs,
        },
        {
            "label": args.variant_token,
            "variable_hints": {args.variable_name: args.variant_token},
            "outputs": inst2_outs,
        },
    ]
    args.out.write_text(json.dumps(instances, indent=2), encoding="utf-8")
    print(f"Wrote {len(instances)} instances to {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
