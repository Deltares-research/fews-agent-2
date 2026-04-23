"""Spec discovery tools.

In slice 1, `list_specs` only returns Locations (gated by
`SLICE1_ALLOWED`). Flipping `FEWS_AGENT_ALL_SPECS=1` in the env opens
the full 119-entry registry — useful when extending coverage to more
file types without code changes.

`describe_spec` hands the model both the Pydantic JSON schema (tight,
machine-checkable) and the checklist slice (narrative — kind, required,
allowed_values, refs). The model uses the checklist to pick good
questions for the user and the JSON schema to shape the `generate` call.
"""
from __future__ import annotations

import os
from typing import Any

from fews_agent.generators import SPECS

from ..checklist import checklist_for
from ..providers.base import ToolSpec

SLICE1_ALLOWED: set[str] = {"locations"}


def _allow_all() -> bool:
    return os.environ.get("FEWS_AGENT_ALL_SPECS", "").strip() == "1"


def list_specs(ctx: Any = None) -> dict[str, Any]:
    """Return the generator specs the agent may target."""
    allow_all = _allow_all()
    entries = []
    for s in SPECS:
        if not allow_all and s.name not in SLICE1_ALLOWED:
            continue
        entries.append(
            {
                "name": s.name,
                "input_key": s.input_key,
                "output_relpath": str(s.output_relpath),
            }
        )
    return {"specs": entries, "slice1_only": not allow_all}


def describe_spec(name: str, ctx: Any = None) -> dict[str, Any]:
    """Full shape of one spec: JSON schema + checklist."""
    if not _allow_all() and name not in SLICE1_ALLOWED:
        return {
            "error": (
                f"Slice 1 only exposes {sorted(SLICE1_ALLOWED)}. "
                "Set FEWS_AGENT_ALL_SPECS=1 to unlock the full registry."
            )
        }
    spec = next((s for s in SPECS if s.name == name), None)
    if spec is None:
        return {"error": f"unknown spec: {name!r}"}
    return {
        "name": spec.name,
        "input_key": spec.input_key,
        "output_relpath": str(spec.output_relpath),
        "json_schema": spec.model_class.model_json_schema(),
        "checklist": checklist_for(spec.name),
    }


LIST_SPECS_TOOL = ToolSpec(
    name="list_specs",
    description=(
        "List the FEWS file-type generators the agent can produce. "
        "Returns name, input_key, output_relpath for each. In slice 1 "
        "this is just 'locations' unless FEWS_AGENT_ALL_SPECS=1 is set."
    ),
    input_schema={"type": "object", "properties": {}, "additionalProperties": False},
)

DESCRIBE_SPEC_TOOL = ToolSpec(
    name="describe_spec",
    description=(
        "Return the full input shape for a spec: Pydantic JSON schema "
        "(strict, machine-checkable) plus the human-oriented checklist "
        "of required/optional fields with kinds, allowed_values, and "
        "id references. Call this before your first `generate(name, ...)`."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "description": "Spec name as returned by list_specs (e.g. 'locations').",
            }
        },
        "required": ["name"],
        "additionalProperties": False,
    },
)
