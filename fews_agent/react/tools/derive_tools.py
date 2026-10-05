"""Deterministic derivers behind one tool: descriptors, topology,
locationsets, global properties.

Each walks the already-rendered files in the ToolContext and produces
its output deterministically — the same derivers the blueprint build
uses, re-runnable here (a re-derive after new workflows overwrites the
previous derivation)."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from fews_agent.agent.blueprint import Blueprint, PatternRef
from fews_agent.agent.descriptor_derivation import derive_descriptor_singletons
from fews_agent.agent.global_properties_derivation import (
    derive_global_properties,
)
from fews_agent.agent.locationsets_derivation import derive_locationsets_yaml
from fews_agent.agent.providers.base import ToolSpec
from fews_agent.agent.topology_derivation import (
    _collect_workflow_stems,
    derive_topology_yaml,
)
from fews_agent.generators import SPECS
from fews_agent.generators.base import render as render_template
from fews_agent.validation.xsd import validate_xsd

from ..context import ToolContext
from ..registry import Tool

_SPEC_BY_NAME = {s.name: s for s in SPECS}

GLOBAL_PROPERTIES_RELPATH = "RootConfigFiles/sa_global.Properties"

_WHAT = ("descriptors", "topology", "locationsets", "global_properties")


def _store_spec_output(ctx: ToolContext, spec_name: str,
                       data: dict[str, Any]) -> dict[str, Any]:
    spec = _SPEC_BY_NAME[spec_name]
    model = spec.model_class.model_validate(data)
    xml = render_template(spec.template_name, model)
    ok, msg = validate_xsd(xml.encode("utf-8"))
    if not ok:
        return {"error": f"derived {spec_name} failed XSD: {msg}"}
    relpath = spec.output_relpath.as_posix()
    ctx.store(relpath, xml, spec_name, model)
    return {"ok": True, "path": relpath}


def _derive_descriptors(ctx: ToolContext) -> dict[str, Any]:
    # Exclude previous descriptor outputs so a re-derive regenerates them
    # from the current module/workflow set instead of being skipped.
    descriptor_paths = {
        _SPEC_BY_NAME[n].output_relpath.as_posix()
        for n in ("moduleInstanceDescriptors", "workflowDescriptors")
        if n in _SPEC_BY_NAME
    }
    source = [f for f in ctx.rendered_list()
              if f.relpath not in descriptor_paths]
    derived = derive_descriptor_singletons(source)
    if not derived:
        return {"ok": True, "paths": [],
                "note": "nothing to describe — no module configs or "
                        "workflows rendered yet"}
    paths = []
    for rf in derived:
        ok, msg = validate_xsd(rf.content.encode("utf-8"))
        if not ok:
            return {"error": f"derived {rf.relpath} failed XSD: {msg}"}
        ctx.store(rf.relpath, rf.content, rf.instance_label, rf.model)
        paths.append(rf.relpath)
    return {"ok": True, "paths": paths}


def _topology_workflow_ids(node: Any) -> set[str]:
    """All workflowId values reachable in a topology node tree."""
    found: set[str] = set()
    if isinstance(node, dict):
        wid = node.get("workflowId")
        if wid:
            found.add(str(wid))
        for value in node.values():
            found |= _topology_workflow_ids(value)
    elif isinstance(node, list):
        for item in node:
            found |= _topology_workflow_ids(item)
    return found


def _derive_topology(ctx: ToolContext) -> dict[str, Any]:
    data = derive_topology_yaml(ctx.rendered_list())
    if data is None:
        return {"error": "no workflow files rendered yet — write the "
                         "workflows first, then derive topology"}
    # The shared deriver buckets workflows by tutorial-era name rules
    # and silently drops the rest. The react agent names workflows
    # freely, so append any workflow the derived tree doesn't reach as
    # a generic group — every workflow must be runnable from Topology.
    reached = _topology_workflow_ids(data.get("nodes"))
    missing = [s for s in _collect_workflow_stems(ctx.rendered_list())
               if s not in reached]
    if missing:
        data.setdefault("nodes", []).append({
            "id": "ProjectWorkflowNodes",
            "name": "Workflows",
            "node": [{
                "id": stem,
                "name": stem,
                "workflowId": stem,
                "graceTime": {"unit": "hour", "multiplier": 6},
                "localRun": True,
                "showRunApprovedForecastButton": True,
            } for stem in sorted(missing)],
        })
    result = _store_spec_output(ctx, "topology", data)
    if result.get("ok") and missing:
        result["note"] = (f"workflows outside the known naming buckets "
                          f"were added under a generic 'Workflows' "
                          f"group: {sorted(missing)}")
    return result


def _derive_locationsets(ctx: ToolContext) -> dict[str, Any]:
    locsets_path = _SPEC_BY_NAME["locationSetsFile"].output_relpath.as_posix()
    source = [f for f in ctx.rendered_list() if f.relpath != locsets_path]
    data = derive_locationsets_yaml(source)
    if data is None:
        return {"ok": True, "paths": [],
                "note": "no locationSetId references found — nothing to "
                        "stub"}
    return _store_spec_output(ctx, "locationSetsFile", data)


def _derive_global_properties(ctx: ToolContext,
                              args: dict[str, Any]) -> dict[str, Any]:
    project_name = str(args.get("project_name")
                       or ctx.session_dir.parent.name or "FEWS Project")
    model_names = [str(n) for n in (args.get("model_names") or [])]
    seeds: dict[str, Any] = {"Locations": {}}
    if args.get("time_zone"):
        seeds["Locations"]["timeZone"] = str(args["time_zone"])
    if args.get("region"):
        seeds["Locations"]["region"] = str(args["region"])
    bp = Blueprint(
        name=project_name,
        output_root=Path("."),
        patterns=[
            PatternRef(pattern="auto/raven_basin",
                       instances=[{"basin_name": n}])
            for n in model_names
        ],
        singleton_seeds=seeds,
    )
    text = derive_global_properties(bp)
    if text is None:
        return {"error": "nothing to derive — pass time_zone (and "
                         "model_names/region when relevant)"}
    extra = args.get("extra_properties") or {}
    if not isinstance(extra, dict):
        return {"error": "extra_properties must be an object of "
                         "NAME: value pairs"}
    if extra:
        lines = [f"{str(k).strip()}={v}" for k, v in extra.items()]
        text = text.rstrip("\n") + "\n\n#Project-specific properties\n" \
            + "\n".join(lines) + "\n"
    ctx.store(GLOBAL_PROPERTIES_RELPATH, text, "sa_global", None)
    return {"ok": True, "path": GLOBAL_PROPERTIES_RELPATH,
            "extra_defined": sorted(str(k) for k in extra)}


def _derive(ctx: ToolContext, args: dict[str, Any]) -> Any:
    what = str(args.get("what") or "")
    if what == "descriptors":
        return _derive_descriptors(ctx)
    if what == "topology":
        return _derive_topology(ctx)
    if what == "locationsets":
        return _derive_locationsets(ctx)
    if what == "global_properties":
        return _derive_global_properties(ctx, args)
    return {"error": f"what must be one of {_WHAT}"}


DERIVE = Tool(
    spec=ToolSpec(
        name="derive",
        description=(
            "Run a deterministic deriver over the files written so far: "
            "'descriptors' (ModuleInstanceDescriptors + "
            "WorkflowDescriptors from module/workflow filenames), "
            "'topology' (Topology.xml grouping workflows), "
            "'locationsets' (stub LocationSets.xml for every referenced "
            "locationSetId, station sets auto-backed from Locations.xml), "
            "'global_properties' (RootConfigFiles/sa_global.Properties "
            "mapping $PLACEHOLDER$s — pass time_zone, optional region, "
            "model_names, and extra_properties for any additional "
            "$NAME$ your files reference, e.g. "
            "{\"MAPLAYERSCACHE_FOLDER\": \"%REGION_HOME%/MapLayerFiles\"}). "
            "Run these AFTER the content files; re-running refreshes "
            "them."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "what": {"type": "string", "enum": list(_WHAT)},
                "project_name": {"type": "string"},
                "model_names": {"type": "array",
                                "items": {"type": "string"}},
                "time_zone": {"type": "string"},
                "region": {"type": "string"},
                "extra_properties": {
                    "type": "object",
                    "description": "additional NAME: value property "
                                   "definitions appended to sa_global",
                },
            },
            "required": ["what"],
            "additionalProperties": False,
        },
    ),
    handler=_derive,
)
