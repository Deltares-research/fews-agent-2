"""Project-level validation: XSD sweep + cross-file semantic pass.

The semantic pass reflects over the RETAINED Pydantic models
(`ToolContext.rendered[*].model`), so only files written through the
typed writer participate. IDs declared inside generic bodies are
invisible to the reflection walker; `_generic_body_declarations` closes
the common cases (locationSet/filter/classBreaks ids) by harvesting
id attributes from the rendered XML directly, so references to them
don't surface as phantom unresolved refs (the first live GFS run hit
exactly this on LocationSets.xml).
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from lxml import etree

from fews_agent.agent.providers.base import ToolSpec
from fews_agent.validation.semantic import validate_semantic
from fews_agent.validation.xsd import validate_xsd

from ..context import ToolContext
from ..registry import Tool

_GENERIC_BODY_NOTE = (
    "IDs declared inside generic-body files are mostly harvested from "
    "the rendered XML (locationSet/filter/classBreaks ids). An "
    "unresolved ref of another id type declared only in a generic body "
    "may still be a false positive — judge it by reading the declaring "
    "file, not by rewriting the reference."
)

MAX_UNRESOLVED_LISTED = 80

# Element tag (FEWS namespace) -> the NewType its `id` attribute
# declares. Covers files whose declarations the reflection walker
# cannot see: generic-body files, and any file registered without a
# retained model.
_GENERIC_DECLARING_TAGS = {
    "locationSet": "LocationSetId",
    "filter": "FilterId",
    "classBreaks": "ClassBreaksId",
    "location": "LocationId",
    "parameter": "ParameterId",
    "timeStep": "TimeStepId",
}

# Folder prefix -> the NewType a file's STEM declares (the semantic
# module's FILENAME_DECLARES, replayed from paths so declarations hold
# even for files without model instances).
_STEM_DECLARES = {
    "ModuleConfigFiles/": "ModuleInstanceId",
    "WorkflowFiles/": "WorkflowId",
    "IdMapFiles/": "IdMapId",
    "UnitConversionsFiles/": "UnitConversionsId",
}

_FEWS_NS = "{http://www.wldelft.nl/fews}"


def _generic_body_declarations(ctx: ToolContext) -> dict[str, set[str]]:
    """Harvest declarations the reflection walker cannot see: `id`
    attributes of known declaring elements in any rendered XML, plus
    filename-stem declarations by folder convention. Cheap lxml scan;
    malformed files are skipped (the XSD sweep reports those)."""
    declared: dict[str, set[str]] = {}
    for f in ctx.rendered_list():
        rel = f.relpath
        for prefix, id_type in _STEM_DECLARES.items():
            if rel.startswith(prefix):
                declared.setdefault(id_type, set()).add(Path(rel).stem)
        if not rel.lower().endswith(".xml"):
            continue
        try:
            root = etree.fromstring(f.content.encode("utf-8"))
        except etree.XMLSyntaxError:
            continue
        for tag, id_type in _GENERIC_DECLARING_TAGS.items():
            for el in root.iter(f"{_FEWS_NS}{tag}"):
                value = el.get("id")
                if value:
                    declared.setdefault(id_type, set()).add(value)
    return declared


# FEWS "simple formula" expressions support lowercase functions
# (atan, sqrt, ...) and the constant `pi`. ATAN2 / MOD / uppercase PI
# are NOT in the vocabulary — the repo's own wind-direction pattern
# (tpl_process_wind_uv_to_speed_dir) hand-expands quadrant logic for
# exactly this reason. XSD can't catch it (expression is free text),
# so a bad expression silently kills one parameter at runtime.
_EXPRESSION_RE = re.compile(r"<expression>([^<]*)</expression>")
_BAD_EXPRESSION_TOKENS = ("ATAN2", "MOD(", re.compile(r"\bPI\b"))


def _expression_issues(ctx: "ToolContext") -> list[dict[str, str]]:
    issues = []
    for f in ctx.rendered_list():
        if not f.relpath.lower().endswith(".xml"):
            continue
        for match in _EXPRESSION_RE.finditer(f.content):
            expr = match.group(1)
            hits = [t if isinstance(t, str) else "PI"
                    for t in _BAD_EXPRESSION_TOKENS
                    if (t.search(expr) if hasattr(t, "search")
                        else t in expr)]
            if hits:
                issues.append({
                    "path": f.relpath,
                    "expression": expr[:160],
                    "unsupported": ", ".join(hits),
                })
    return issues


# $NAME$ runtime placeholders FEWS resolves from sa_global.Properties.
# (%TOKEN% style like %REGION_HOME%/%TIME_ZERO(...)% is FEWS-internal,
# not sa_global-resolved — excluded on purpose.)
_PROPERTY_TOKEN = re.compile(r"\$([A-Z][A-Z0-9_]*)\$")

GLOBAL_PROPERTIES_RELPATH = "RootConfigFiles/sa_global.Properties"


def _undefined_properties(ctx: ToolContext) -> dict[str, list[str]]:
    """Which $NAME$ tokens are referenced but not defined in sa_global?

    Returns {token: [referencing files...]} — the first live GFS run
    shipped $MAPLAYERSCACHE_FOLDER$ with no definition; FEWS would use
    the literal string as a path, silently.
    """
    defined: set[str] = set()
    sa = ctx.rendered.get(GLOBAL_PROPERTIES_RELPATH)
    if sa is not None:
        for line in sa.content.splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                defined.add(line.split("=", 1)[0].strip())
    refs: dict[str, list[str]] = {}
    for f in ctx.rendered_list():
        if f.relpath == GLOBAL_PROPERTIES_RELPATH:
            continue
        for token in set(_PROPERTY_TOKEN.findall(f.content)):
            if token not in defined:
                refs.setdefault(token, []).append(f.relpath)
    return refs


def _validate_project(ctx: ToolContext, args: dict[str, Any]) -> Any:
    xsd_failures = []
    for f in ctx.rendered_list():
        if not f.relpath.lower().endswith(".xml"):
            continue
        ok, msg = validate_xsd(f.content.encode("utf-8"))
        if not ok:
            xsd_failures.append({"path": f.relpath, "message": msg})

    loaded = [
        (f.instance_label, f.model, Path(f.relpath))
        for f in ctx.rendered_list()
        if f.model is not None
    ]
    report = validate_semantic(loaded)
    generic_declared = _generic_body_declarations(ctx)
    remaining = [
        r for r in report.unresolved
        if r.value not in generic_declared.get(r.id_type_name, ())
    ]
    unresolved = [
        {"id_type": r.id_type_name, "value": r.value, "source": r.source}
        for r in remaining[:MAX_UNRESOLVED_LISTED]
    ]
    undefined_props = _undefined_properties(ctx)
    expression_issues = _expression_issues(ctx)
    return {
        "files": len(ctx.rendered),
        "xsd_failures": xsd_failures,
        "expression_issues": expression_issues,
        "undefined_properties": [
            {"property": name, "referenced_by": files}
            for name, files in sorted(undefined_props.items())
        ],
        "semantic": {
            "declared": (report.total_declared()
                         + sum(len(v) for v in generic_declared.values())),
            "refs": len(report.refs),
            "placeholders_skipped": len(report.placeholders),
            "unresolved_count": len(remaining),
            "unresolved": unresolved,
        },
        "notes": _GENERIC_BODY_NOTE,
    }


VALIDATE_PROJECT = Tool(
    spec=ToolSpec(
        name="validate_project",
        description=(
            "Validate the whole generated config: XSD per file, "
            "cross-file ID reference resolution (does every "
            "moduleInstanceId/locationId/parameterId/idMapId you "
            "referenced actually get declared somewhere?), and "
            "$PROPERTY$ placeholders referenced but not defined in "
            "sa_global.Properties (fix via derive global_properties "
            "with extra_properties), and transformation <expression>s "
            "using functions FEWS does not support (ATAN2/MOD/PI — "
            "rewrite with lowercase atan/pi and hand-expanded quadrant "
            "logic). Run this before finishing; repair until "
            "xsd_failures, expression_issues, undefined_properties and "
            "unresolved_count are all empty/0 or explained."
        ),
        input_schema={
            "type": "object",
            "properties": {},
            "additionalProperties": False,
        },
    ),
    handler=_validate_project,
)
