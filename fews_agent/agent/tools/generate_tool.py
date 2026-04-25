"""The `generate` tool — the deterministic XML-emission step.

Flow: look up the spec → validate params with Pydantic → render via
`spec.generate` → validate shape with XSD → return XML + XSD status.

Pydantic `ValidationError` does NOT raise out of here. We return the
error list as JSON so the model can read it in the next turn and fix
its arguments. Same for unknown spec names and slice-1 guard misses.
"""
from __future__ import annotations

import os
from typing import Any

from pydantic import ValidationError

from fews_agent.generators import SPECS
from fews_agent.validation import validate_xsd

from ..providers.base import ToolSpec
from .spec_tools import SLICE1_ALLOWED, _allow_all


def generate(
    name: str,
    params: dict[str, Any] | None = None,
    ctx: Any = None,
) -> dict[str, Any]:
    if not _allow_all() and name not in SLICE1_ALLOWED:
        return {
            "error": (
                f"Slice 1 only generates {sorted(SLICE1_ALLOWED)}. "
                "Set FEWS_AGENT_ALL_SPECS=1 to unlock more specs."
            )
        }
    spec = next((s for s in SPECS if s.name == name), None)
    if spec is None:
        return {"error": f"unknown spec: {name!r}"}

    # Fall back to project state when the model didn't supply params —
    # this is the preferred path because it sidesteps re-transcription
    # errors (small models tend to paraphrase strings or coerce string
    # coords back into floats when they reconstruct the dict from
    # conversation history).
    if not params:
        if ctx is None:
            return {"error": "params is empty and no project state is available"}
        params = ctx.project_data.get(spec.input_key) or {}
        if not params:
            return {
                "error": (
                    f"params is empty and project state has nothing under "
                    f"'{spec.input_key}'. Populate state via the upsert/"
                    f"set tools first, or pass params explicitly."
                )
            }

    try:
        model = spec.model_class.model_validate(params)
    except ValidationError as exc:
        return {"validation_errors": exc.errors()}

    xml = spec.generate(model)
    xsd_ok, xsd_msg = validate_xsd(xml.encode("utf-8"))

    # Stash on context so the TUI can display the latest XML without
    # re-running generation. Agent loop also reads these back.
    if ctx is not None:
        ctx.last_xml = xml
        ctx.last_xsd_ok = xsd_ok
        ctx.last_xsd_msg = xsd_msg
        # Persist the generated artifact alongside the project.
        try:
            ctx.store.write_artifact(ctx.project_name, spec.output_relpath, xml)
        except Exception:
            # Non-fatal — tool returns still succeed, artifact write is a side benefit.
            pass

    return {
        "spec_name": spec.name,
        "output_relpath": str(spec.output_relpath),
        "xml": xml,
        "xsd_ok": xsd_ok,
        "xsd_msg": xsd_msg,
    }


GENERATE_TOOL = ToolSpec(
    name="generate",
    description=(
        "Render a FEWS XML file. PREFERRED USAGE: call with just `name` "
        "(omit `params`) after you've populated project state via the "
        "upsert/set tools — the generator will read state directly, "
        "which sidesteps name paraphrasing or coord-format drift. Pass "
        "`params` explicitly only when you want to override or bypass "
        "project state. Returns {xml, xsd_ok, xsd_msg, output_relpath} "
        "on success, or {validation_errors: [...]} if the inputs don't "
        "conform to the spec's Pydantic model. Coordinate fields "
        "(x, y, z) should remain strings to preserve exact digits."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "Spec name (e.g. 'locations')."},
            "params": {
                "type": "object",
                "description": (
                    "Optional. Full input matching the spec's Pydantic "
                    "model. Omit to pull from project state — that is "
                    "the preferred path."
                ),
                "additionalProperties": True,
            },
        },
        "required": ["name"],
        "additionalProperties": False,
    },
)
