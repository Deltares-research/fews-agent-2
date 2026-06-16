"""Prompts for the three LLM jobs.

Each prompt is tightly scoped so the model does one transformation,
not "design a pattern from scratch". The structured-output schemas
match the IR exactly — a model that can't produce valid JSON for
these can't pass the Pydantic gate either, so failure is loud.
"""
from __future__ import annotations

import json
from typing import Any

from .diff_finder import DiffReport
from .ir import InstanceInput


# --- Job 1: propose variables -----------------------------------------

VARIABLES_SYSTEM = (
    "You abstract a reusable FEWS pattern. Your ONLY job in this turn: "
    "name each atomic value-set listed below. ONE variable per atomic "
    "value-set.\n\n"
    "The diff has already been preprocessed: token-groups that derive "
    "from another via a constant prefix are NOT shown to you — they "
    "will be rewritten automatically downstream (e.g. 'ImportHRDPS' → "
    "'Import{{ nwp_name }}'). You see only the atomic value-sets.\n\n"
    "Rules:\n"
    " - Output EXACTLY ONE variable per atomic value-set shown.\n"
    " - Do NOT propose variables for any value-set not listed.\n"
    " - Use snake_case names. Pick the canonical, suffix-stripped form "
    "(e.g. 'nwp_name' for {HRDPS, GFS}, not 'module_instance_id').\n"
    " - Number/bool atomic groups → type int/float/bool.\n"
    " - variable_hints from the user override your judgement on conflict.\n"
    "Return JSON ONLY, no prose."
)


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

ABSTRACT_SYSTEM = (
    "You rewrite ONE output spec — output path + data dict — replacing "
    "concrete instance-specific values with Jinja placeholders.\n\n"
    "Rules:\n"
    " - Use exactly `{{ var }}` (double curlies, single space). NO other "
    "Jinja constructs.\n"
    " - FORBIDDEN: Jinja conditionals like `{{ '3' if nwp_name == 'GFS' else "
    "'1' }}`, expressions like `{{ a + b }}`, block tags `{% if %}`. If a "
    "value differs across instances, USE THE NUMERIC OR BOOLEAN VARIABLE "
    "from the 'Variables in scope' list — one of them was added precisely "
    "for that purpose.\n"
    " - Apply the 'Rewrite rules' table EXACTLY as given. Every occurrence "
    "of a listed literal at the matching path MUST be replaced by the "
    "shown template — no exceptions, no second-guessing.\n"
    " - Use ONLY variables from the 'Variables in scope' list. Do NOT "
    "invent new variable names.\n"
    " - Preserve the dict shape and key order. Don't add, remove, or rename keys.\n"
    " - Schema class name stays EXACTLY as the source — it's set by code "
    "downstream regardless, so don't change it.\n"
    "Return JSON ONLY, no prose."
)


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

REPAIR_SYSTEM = (
    "You repair ONE output spec whose Jinja substitution didn't "
    "reproduce the input instances. You're told exactly which paths "
    "diverged. Edit ONLY the failing positions; preserve everything "
    "else byte-for-byte.\n\n"
    "Return the FULL corrected output spec as JSON. No prose."
)


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
