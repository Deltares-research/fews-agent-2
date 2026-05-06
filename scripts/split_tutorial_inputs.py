"""Split tutorial-input.json into per-spec input files.

For each entry in ``examples/config-tutorial-input.json``:
  - Tabular specs (locations, parameters, qualifiers,
    thresholdWarningLevels) → CSV files (already handled by
    build_tutorial_full.py).
  - Pattern-covered specs → skip (project.yaml provides them).
  - Everything else → ``inputs/<spec_name>.yaml``.

Result: a self-contained project at
``examples/blueprints/tutorial-full/inputs/`` that the runner can
read directly. No reference to tutorial-input.json from the project.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from fews_agent.generators import SPECS  # noqa: E402

PROJECT_ROOT = REPO_ROOT / "examples" / "blueprints" / "tutorial-full"
INPUTS_DIR = PROJECT_ROOT / "inputs"
TUTORIAL_INPUT = REPO_ROOT / "examples" / "config-tutorial-input.json"
CLUSTERS_DIR = REPO_ROOT / "data" / "patterns" / "clusters"


def _pattern_covered_input_keys() -> set[str]:
    """Compute input_keys handled by the pattern library (from cluster yamls)."""
    covered: set[str] = set()
    for cluster_yaml in CLUSTERS_DIR.glob("*.yaml"):
        cfg = yaml.safe_load(cluster_yaml.read_text(encoding="utf-8"))
        labels = cfg.get("instances", [])
        for out in cfg.get("outputs", []):
            template = out.get("input_key_template", "")
            for label in labels:
                covered.add(template.format(
                    label=label,
                    label_lower=label.lower(),
                    label_upper=label.upper(),
                    label_title=label[:1].upper() + label[1:] if label else label,
                ))
    return covered


def main() -> int:
    INPUTS_DIR.mkdir(parents=True, exist_ok=True)
    tutorial_input = json.loads(TUTORIAL_INPUT.read_text(encoding="utf-8"))
    pattern_keys = _pattern_covered_input_keys()
    csv_keys = {
        "locations", "parameters", "qualifiers", "thresholdWarningLevels",
    }
    spec_by_input_key = {s.input_key: s for s in SPECS}

    # Note: we write yamls for the CSV-covered specs too, because
    # CSV→XML round-tripping is lossy. The yaml is the lossless source;
    # the CSV is configurator-friendly authoring. The runner's per-spec
    # yaml path runs last and overwrites the CSV-rendered file, so
    # both paths can coexist for these specs.
    n_yaml = n_skipped_pattern = n_unknown = 0
    for input_key, dict_value in tutorial_input.items():
        if input_key in pattern_keys:
            n_skipped_pattern += 1
            continue
        spec = spec_by_input_key.get(input_key)
        if spec is None:
            n_unknown += 1
            continue
        out_path = INPUTS_DIR / f"{spec.name}.yaml"
        out_path.write_text(
            yaml.safe_dump(dict_value, sort_keys=False, width=200),
            encoding="utf-8",
        )
        n_yaml += 1

    print(f"Wrote {n_yaml} per-spec YAML files to {INPUTS_DIR}")
    print(f"  pattern-covered (skipped): {n_skipped_pattern}")
    print(f"  unknown spec (skipped):    {n_unknown}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
