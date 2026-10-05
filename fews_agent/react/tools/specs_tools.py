"""Spec discovery tools: what file types can the writer produce?

217 registered specs — `list_specs` returns names + output paths only
(never schemas), `describe_spec` returns ONE spec's JSON Schema, trimmed
with a `$defs` drill-down when the full schema would blow the context.
"""
from __future__ import annotations

import json
from typing import Any

from fews_agent.agent.providers.base import ToolSpec
from fews_agent.generators import SPECS

from ..context import ToolContext
from ..registry import Tool

# Serialized-schema size above which describe_spec switches to the
# trimmed top-level + component drill-down shape.
MAX_SCHEMA_CHARS = 45_000

_SPEC_BY_NAME = {s.name: s for s in SPECS}

# JSON-Schema annotation keys that are pure noise for a model that
# already sees field names: Pydantic stamps a "title" on every node.
_SCHEMA_MAP_KEYS = ("properties", "$defs", "patternProperties")


def strip_schema_noise(node: Any, *, _in_map: bool = False) -> Any:
    """Drop Pydantic's per-node "title" annotations and null defaults.

    ``_in_map`` marks dicts that are name->schema maps (`properties`,
    `$defs`): their KEYS are field/component names and must never be
    dropped — a FEWS field literally named `title` stays intact; only
    the annotation key inside a schema node is removed.
    """
    if isinstance(node, dict):
        out: dict[str, Any] = {}
        for key, value in node.items():
            if not _in_map:
                if key == "title" and isinstance(value, str):
                    continue
                if key == "default" and value is None:
                    continue
            out[key] = strip_schema_noise(
                value, _in_map=(not _in_map and key in _SCHEMA_MAP_KEYS))
        return out
    if isinstance(node, list):
        return [strip_schema_noise(v) for v in node]
    return node


def _list_specs(ctx: ToolContext, args: dict[str, Any]) -> Any:
    needle = str(args.get("filter") or "").lower()
    rows = []
    for s in SPECS:
        hay = f"{s.name} {s.output_relpath.as_posix()} {s.model_class.__name__}"
        if needle and needle not in hay.lower():
            continue
        rows.append(f"{s.name} {s.output_relpath.as_posix()} "
                    f"{s.model_class.__name__}")
    # One compact text block (not per-row JSON objects): this listing is
    # re-sent with every later model call, so framing overhead matters.
    return {"count": len(rows), "columns": "name output_path model",
            "specs": "\n".join(rows)}


def _describe_spec(ctx: ToolContext, args: dict[str, Any]) -> Any:
    spec_name = str(args.get("spec_name") or "")
    schema_name = str(args.get("schema") or "")
    if schema_name and not spec_name:
        from fews_agent.agent.blueprint import schema_class_for
        try:
            model_class = schema_class_for(schema_name)
        except KeyError as exc:
            return {"error": str(exc)}
        spec = None
        spec_name = schema_name
    else:
        spec = _SPEC_BY_NAME.get(spec_name)
        if spec is None:
            close = [n for n in _SPEC_BY_NAME
                     if spec_name.lower() in n.lower()]
            return {"error": f"unknown spec {spec_name!r}"
                    + (f"; close matches: {close[:10]}" if close else
                       "; call list_specs first")}
        model_class = spec.model_class
    schema = strip_schema_noise(model_class.model_json_schema())
    component = args.get("component")
    if component:
        defs = schema.get("$defs", {})
        if component not in defs:
            return {"error": f"no component {component!r} in {spec_name}; "
                    f"available: {sorted(defs)[:40]}"}
        return {"spec_name": spec_name, "component": component,
                "schema": defs[component]}
    base = {
        "spec_name": spec_name,
        "model": model_class.__name__,
    }
    if spec is not None:
        base["default_output_relpath"] = spec.output_relpath.as_posix()
    if len(json.dumps(schema, separators=(",", ":"))) <= MAX_SCHEMA_CHARS:
        return {**base, "schema": schema}
    return {
        **base,
        "note": ("schema too large to return whole; top-level properties "
                 "below reference $defs components — re-call with "
                 "component='<Name>' for one definition"),
        "properties": schema.get("properties", {}),
        "required": schema.get("required", []),
        "components": sorted(schema.get("$defs", {})),
    }


LIST_SPECS = Tool(
    spec=ToolSpec(
        name="list_specs",
        description=(
            "List the FEWS file types the deterministic writer can produce "
            "(name, default output path, model name). Optional substring "
            "filter. Call describe_spec for one spec's data schema."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "filter": {
                    "type": "string",
                    "description": "case-insensitive substring over "
                                   "name/path/model",
                },
            },
            "additionalProperties": False,
        },
    ),
    handler=_list_specs,
)

DESCRIBE_SPEC = Tool(
    spec=ToolSpec(
        name="describe_spec",
        description=(
            "Return the JSON Schema for one writer payload — by spec_name "
            "(from list_specs) or by schema (a model class name like "
            "'Workflow'). Large schemas come back trimmed to top-level "
            "properties plus a component list — drill into one with "
            "component='<Name>'."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "spec_name": {"type": "string"},
                "schema": {"type": "string",
                           "description": "model class name; alternative "
                                          "to spec_name"},
                "component": {
                    "type": "string",
                    "description": "a $defs component name from a previous "
                                   "trimmed response",
                },
            },
            "additionalProperties": False,
        },
    ),
    handler=_describe_spec,
)
