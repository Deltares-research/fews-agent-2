"""Build a real XML-input fixture and manifest for the farmer.

Renders the existing nwp_grid_eccc_HRDPS pattern with two values
(HRDPS and a synthetic GFS twin where every 'HRDPS' is substituted),
writes the rendered XML to disk under <out>/instances/<label>/, and
emits the YAML manifest that farm_pattern.py --xml-config consumes.

This is the "could be real example XMLs" test fixture — once it
works end-to-end, replacing the synthetic step with actual real-
world XMLs is purely external.
"""
from __future__ import annotations

import argparse
import copy
import sys
from pathlib import Path
from typing import Any

import yaml
from jinja2 import Environment, StrictUndefined

from fews_agent.agent.blueprint import schema_class_for, template_for_schema
from fews_agent.generators.base import render


def deep_sub(obj: Any, old: str, new: str) -> Any:
    if isinstance(obj, str):
        return obj.replace(old, new)
    if isinstance(obj, dict):
        return {k: deep_sub(v, old, new) for k, v in obj.items()}
    if isinstance(obj, list):
        return [deep_sub(v, old, new) for v in obj]
    return obj


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--source-pattern", type=Path, required=True)
    p.add_argument("--source-token", required=True)
    p.add_argument("--variant-token", required=True)
    p.add_argument("--variable-name", default="nwp_name")
    p.add_argument("--out", type=Path, required=True,
                   help="Directory under which 'instances/<label>/*.xml' and "
                        "'manifest.yaml' will be written")
    args = p.parse_args(argv)

    env = Environment(undefined=StrictUndefined, keep_trailing_newline=True)
    raw = args.source_pattern.read_text(encoding="utf-8")
    spec = yaml.safe_load(env.from_string(raw).render(**{args.variable_name: args.source_token}))

    instances_dir = args.out / "instances"

    manifest: dict[str, Any] = {"instances": []}
    for label, token in [(args.source_token, args.source_token), (args.variant_token, args.variant_token)]:
        inst_dir = instances_dir / label
        inst_dir.mkdir(parents=True, exist_ok=True)
        inst_outputs = []
        for i, out in enumerate(spec["outputs"]):
            cls = schema_class_for(out["schema"])
            data = out["data"] if token == args.source_token else deep_sub(out["data"], args.source_token, args.variant_token)
            output_path = out["output"] if token == args.source_token else out["output"].replace(args.source_token, args.variant_token)
            model = cls.model_validate(data)
            xml = render(template_for_schema(cls), model)
            xml_file = inst_dir / Path(output_path).name
            xml_file.write_text(xml, encoding="utf-8")
            inst_outputs.append({
                "path": str(xml_file.relative_to(args.out)),
                "schema": out["schema"],
                "output": output_path,
            })
        manifest["instances"].append({
            "label": label,
            "variable_hints": {args.variable_name: token},
            "outputs": inst_outputs,
        })

    manifest_path = args.out / "manifest.yaml"
    manifest_path.write_text(yaml.safe_dump(manifest, sort_keys=False), encoding="utf-8")
    print(f"Wrote {len(manifest['instances'])} instances under {instances_dir}/")
    print(f"Manifest: {manifest_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
