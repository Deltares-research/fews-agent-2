"""Pinned grammar for one FEWS spec — antidote to wiki-recalled prose."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from fews_agent.agent.blueprint import schema_class_for
from fews_agent.validation.xsd import SCHEMAS_DIR


def _xsd_rel_for_spec(name: str) -> str | None:
    stem = name[0].lower() + name[1:] if name else ""
    candidate = f"{stem}.xsd"
    if (SCHEMAS_DIR / candidate).exists():
        return candidate
    # A few SPECS names don't match the XSD filename 1:1.
    aliases = {
        "TimeSeriesImportRun": "timeSeriesImportRun.xsd",
        "IdMap": "idMap.xsd",
        "Workflow": "workflow.xsd",
        "Parameters": "parameters.xsd",
        "Locations": "locations.xsd",
        "TransformationModule": "transformationModule.xsd",
        "GeneralAdapterRun": "generalAdapterRun.xsd",
    }
    alt = aliases.get(name)
    if alt and (SCHEMAS_DIR / alt).exists():
        return alt
    return None


def _collect_enums(schema: dict[str, Any], prefix: str = "") -> dict[str, list[str]]:
    enums: dict[str, list[str]] = {}
    props = schema.get("properties") or {}
    for key, spec in props.items():
        if not isinstance(spec, dict):
            continue
        path = f"{prefix}.{key}" if prefix else key
        if "enum" in spec:
            enums[path] = [str(x) for x in spec["enum"]]
        if spec.get("type") == "array" and isinstance(spec.get("items"), dict):
            enums.update(_collect_enums(spec["items"], path))
        if spec.get("type") == "object":
            enums.update(_collect_enums(spec, path))
    defs = schema.get("$defs") or schema.get("definitions") or {}
    for dname, dspec in defs.items():
        if isinstance(dspec, dict) and "enum" in dspec:
            enums[dname] = [str(x) for x in dspec["enum"]]
    return enums


def schema_shape(spec: str) -> dict[str, Any]:
    """Return the pinned JSON schema + XSD path for a SPECS class name.

    Raises ``KeyError`` on an unknown spec (loud — do not guess).
    """
    name = str(spec or "").strip()
    if not name:
        raise KeyError("schema_shape: spec is empty")
    cls = schema_class_for(name)
    js = cls.model_json_schema()
    return {
        "name": cls.__name__,
        "json_schema": js,
        "required": list(js.get("required") or []),
        "enums": _collect_enums(js),
        "xsd_rel": _xsd_rel_for_spec(cls.__name__),
        "xsd_dir": str(Path(SCHEMAS_DIR)),
    }


def list_specs() -> list[str]:
    from fews_agent.generators import SPECS
    return sorted({s.model_class.__name__ for s in SPECS})
