"""Typed intermediate representation → Jinja XML → XSD + conform.

The host LLM fills a typed intermediate representation (the Pydantic
model for one SPECS class). Python owns element order, namespaces, and
escaping. This is read-only: the caller writes via ``admit_file``.
"""
from __future__ import annotations

from typing import Any

from pydantic import ValidationError

from fews_agent.agent.blueprint import (
    output_relpath_for_class,
    schema_class_for,
    template_for_schema,
)
from fews_agent.generators.base import render as render_template
from fews_agent.validation.gauntlet import validate_xml
from fews_agent.validation.schema_shape import list_specs


def _validation_errors(exc: ValidationError) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for err in exc.errors():
        loc = err.get("loc") or ()
        out.append({
            "loc": [str(x) for x in loc],
            "msg": str(err.get("msg") or ""),
            "type": str(err.get("type") or ""),
        })
    return out


def render_spec(spec: str, data: Any) -> dict[str, Any]:
    """Validate ``data`` against ``spec``, render XML, then XSD + conform.

    Never raises on unknown spec / Pydantic / render failures — returns
    a structured dict the host can repair from.
    """
    name = str(spec or "").strip()
    empty: dict[str, Any] = {
        "spec": name,
        "ok": False,
        "xml": "",
        "suggested_relpath": None,
        "diagnostics": [],
        "validation_errors": [],
    }
    if not name:
        empty["validation_errors"] = [{
            "loc": ["spec"],
            "msg": "spec is empty",
            "type": "value_error",
        }]
        empty["known_specs_sample"] = list_specs()[:20]
        return empty
    try:
        cls = schema_class_for(name)
    except KeyError as exc:
        empty["validation_errors"] = [{
            "loc": ["spec"],
            "msg": str(exc),
            "type": "key_error",
        }]
        empty["known_specs_sample"] = list_specs()[:20]
        return empty

    if not isinstance(data, dict):
        empty["validation_errors"] = [{
            "loc": ["data"],
            "msg": "data must be a JSON object",
            "type": "type_error",
        }]
        return empty

    try:
        model = cls.model_validate(data)
    except ValidationError as exc:
        empty["validation_errors"] = _validation_errors(exc)
        return empty

    try:
        suggested = output_relpath_for_class(cls)
    except KeyError:
        suggested = None

    try:
        xml = render_template(template_for_schema(cls), model)
    except Exception as exc:  # noqa: BLE001
        empty["suggested_relpath"] = suggested
        empty["validation_errors"] = [{
            "loc": ["render"],
            "msg": f"{type(exc).__name__}: {exc}",
            "type": "render_error",
        }]
        return empty

    report = validate_xml(xml, spec=cls.__name__, tiers=["xsd", "conform"])
    return {
        "spec": cls.__name__,
        "ok": report.ok,
        "xml": xml,
        "suggested_relpath": suggested,
        "diagnostics": [d.to_dict() for d in report.diagnostics],
        "validation_errors": [],
    }
