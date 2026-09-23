"""Host-agnostic verification toolbelt.

MCP and HTTP only serialize these return values. All logic lives here.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Sequence

from fews_agent.validation.conform import explain_rule, lint_tree
from fews_agent.validation.examples import find_examples
from fews_agent.validation.gauntlet import validate_config, validate_xml
from fews_agent.validation.load_tree import load_tree
from fews_agent.validation.schema_shape import list_specs, schema_shape
from fews_agent.validation.semantic import validate_semantic


def tool_validate_config(
    path: str, tiers: Sequence[str] | None = None,
) -> dict[str, Any]:
    return validate_config(path, tiers=tiers).to_dict()


def tool_validate_xml(
    xml: str, spec: str | None = None, tiers: Sequence[str] | None = None,
) -> dict[str, Any]:
    return validate_xml(xml, spec=spec, tiers=tiers).to_dict()


def tool_conform_lint(path: str) -> dict[str, Any]:
    tree = load_tree(Path(path))
    diags = lint_tree(tree)
    return {
        "path": str(Path(path)),
        "ok": not any(d.severity == "error" for d in diags),
        "diagnostics": [d.to_dict() for d in diags],
    }


def tool_conform_lint_xml(xml: str, spec: str | None = None) -> dict[str, Any]:
    report = validate_xml(xml, spec=spec, tiers=["conform"])
    return report.to_dict()


def tool_schema_shape(spec: str) -> dict[str, Any]:
    try:
        return schema_shape(spec)
    except KeyError as exc:
        return {
            "error": str(exc),
            "known_specs_sample": list_specs()[:20],
        }


def tool_find_examples(query: str, k: int = 5) -> dict[str, Any]:
    return {"query": query, "examples": find_examples(query, k=k)}


def tool_id_registry(path: str) -> dict[str, Any]:
    tree = load_tree(Path(path))
    loaded = tree.models_for_semantic()
    if not loaded:
        return {
            "path": str(Path(path)),
            "declared": {},
            "refs": [],
            "unresolved": [],
            "note": "No typed models loaded — generic-body files are invisible "
            "to the NewType walker.",
        }
    report = validate_semantic(loaded)
    return {
        "path": str(Path(path)),
        "declared": {k: sorted(v) for k, v in report.declared.items()},
        "refs": [
            {"type": r.id_type_name, "value": r.value, "source": r.source}
            for r in report.refs
        ],
        "unresolved": [
            {"type": r.id_type_name, "value": r.value, "source": r.source}
            for r in report.unresolved
        ],
        "placeholders": len(report.placeholders),
    }


def tool_explain_diagnostic(rule_id: str) -> dict[str, Any]:
    # Built-in gauntlet rules that are not in the conform registry.
    builtins = {
        "xsd.schema": {
            "rule_id": "xsd.schema",
            "severity": "error",
            "title": "XML does not match the pinned FEWS XSD",
            "fix_hint": "Fix element order and required children "
            "(FEWS XSDs use xsd:sequence).",
            "citation": "fews_agent/schemas (pinned version1.0)",
            "example": "<timeSeriesImportRun> with a child that is not "
            "in the XSD sequence (e.g. <notARealChild/>).",
        },
        "semantic.unresolved": {
            "rule_id": "semantic.unresolved",
            "severity": "error",
            "title": "Cross-file ID reference does not resolve",
            "fix_hint": "Declare the ID in the owning file or fix casing.",
            "citation": "fews_agent/validation/semantic.py",
            "example": "A workflow names <moduleInstanceId>ImportSREF"
            "</moduleInstanceId> but no module-config file declares it.",
        },
        "fews.unavailable": {
            "rule_id": "fews.unavailable",
            "severity": "skip",
            "title": "Headless FEWS check is not configured",
            "fix_hint": "Set FEWS_CHECK_CMD (use {path} for the folder).",
            "citation": "fews_agent/validation/fews_check.py",
            "example": "FEWS_CHECK_CMD unset → tier 4 is skip, never a crash.",
        },
    }
    info = builtins.get(rule_id) or explain_rule(rule_id)
    if info is None:
        return {"error": f"unknown rule_id {rule_id!r}"}
    return dict(info)
