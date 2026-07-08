"""Prompts for the three LLM jobs.

Each prompt is tightly scoped so the model does one transformation,
not "design a pattern from scratch". The structured-output schemas
match the IR exactly — a model that can't produce valid JSON for
these can't pass the Pydantic gate either, so failure is loud.
"""
from __future__ import annotations

import json
from typing import Any

from fews_agent.agent import prompts as _prompts
from .diff_finder import DiffReport
from .ir import InstanceInput


# --- Job 1: propose variables -----------------------------------------

VARIABLES_SYSTEM = _prompts.load("farm_variables.system")


def variables_user_prompt(
    instances: list[InstanceInput], diff: DiffReport,
) -> str:
    lines = [
        "## Instance labels",
        ", ".join(f"{i.label} (hints: {i.variable_hints or {}})" for i in instances),
        "",
        "## Atomic value-sets to name",
    ]
    for i, g in enumerate(diff.atomic_groups):
        vals = ", ".join(f"{lbl}={v!r}" for lbl, v in g.values_by_label.items())
        lines.append(
            f"  atomic[{i}]: {vals} "
            f"(used at {len(g.divergence_indices)} site(s))"
        )
    if diff.derived_groups:
        lines.append("")
        lines.append("## Derived (auto-rewritten downstream — do NOT name)")
        for g in diff.derived_groups:
            parent = diff.token_groups[g.derived_from]
            lines.append(
                f"  {g.value_set} = {g.prefix!r}+{parent.value_set} "
                f"→ will become '{g.prefix}{{{{ <name-of-parent> }}}}'"
            )
    lines += [
        "",
        f"## What to return ({len(diff.atomic_groups)} variables expected)",
        "Return JSON like:",
        json.dumps(
            {
                "variables": [
                    {
                        "name": "nwp_name",
                        "type": "str",
                        "value_per_instance": {"HRDPS": "HRDPS", "GFS": "GFS"},
                    }
                ]
            },
            indent=2,
        ),
        "",
        "value_per_instance MUST map each instance label to that "
        "instance's value of the variable.",
    ]
    return "\n".join(lines)


VARIABLES_SCHEMA = {
    "type": "object",
    "required": ["variables"],
    "properties": {
        "variables": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["name", "type", "value_per_instance"],
                "properties": {
                    "name": {"type": "string"},
                    "type": {
                        "type": "string",
                        "enum": ["str", "int", "float", "bool"],
                    },
                    "value_per_instance": {
                        "type": "object",
                        "additionalProperties": True,
                    },
                },
            },
        },
    },
}


# --- Job 2: abstract one output ---------------------------------------

ABSTRACT_SYSTEM = _prompts.load("farm_abstract.system")


def abstract_user_prompt(
    output_index: int,
    output_specs_per_instance: list[dict[str, Any]],  # [{schema, output, data}, ...]
    instance_labels: list[str],
    variables: list[dict[str, Any]],  # [{name, type, value_per_instance}, ...]
    rewrite_rules: list[dict[str, Any]] | None = None,  # [{literals, template, sites}, ...]
) -> str:
    lines = [
        f"## Output #{output_index}",
        "",
        "## Variables in scope",
        json.dumps(variables, indent=2),
        "",
    ]
    if rewrite_rules:
        lines.append("## Rewrite rules (apply EXACTLY)")
        for rule in rewrite_rules:
            literals = ", ".join(repr(x) for x in rule["literals"])
            lines.append(f"  {literals}  →  {rule['template']!r}")
        lines.append("")
    lines.append("## Instances")
    for label, spec in zip(instance_labels, output_specs_per_instance):
        lines.append(f"### {label}")
        lines.append(f"output path: {spec['output']}")
        lines.append("data:")
        lines.append(json.dumps(spec["data"], indent=2))
        lines.append("")
    lines.append(
        "## What to return\n"
        "Return JSON like:\n"
        + json.dumps(
            {
                "schema": "TimeSeriesImportRun",
                "output": "ModuleConfigFiles/Import/Import{{ nwp_name }}.xml",
                "data": {"...": "..."},
            },
            indent=2,
        )
    )
    return "\n".join(lines)


ABSTRACT_SCHEMA = {
    "type": "object",
    "required": ["schema", "output", "data"],
    "properties": {
        "schema": {"type": "string"},
        "output": {"type": "string"},
        "data": {"type": "object"},
    },
}


# --- Job 3: repair ----------------------------------------------------

REPAIR_SYSTEM = _prompts.load("farm_repair.system")


def repair_user_prompt(
    output_index: int,
    failing_spec: dict[str, Any],
    instance_labels: list[str],
    expected_per_instance: list[dict[str, Any]],
    diff_details: str,
) -> str:
    lines = [
        f"## Output #{output_index} — REPAIR",
        "",
        "## Current (broken) abstracted spec",
        json.dumps(failing_spec, indent=2),
        "",
        "## Re-render mismatches",
        diff_details,
        "",
        "## Expected per instance",
    ]
    for label, exp in zip(instance_labels, expected_per_instance):
        lines.append(f"### {label}")
        lines.append(json.dumps(exp, indent=2))
        lines.append("")
    lines.append(
        "## What to return\n"
        "Same JSON shape as before: {schema, output, data}."
    )
    return "\n".join(lines)
