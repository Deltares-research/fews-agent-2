"""LLM-drafted filtersFile from project context.

Phase 3 of input-yaml auto-generation. Where Phase 1+2 used
deterministic bundling and rendering, the filter drafter actually
asks qwen to *propose* a sensible filter tree given the project's
imports, parameters, and basins. The LLM is constrained to use only
IDs that appear in the project (no hallucination).

Why a separate phase: filters genuinely encode project intent
("show me observations / forecasts / model outputs separately"). No
deterministic default works across projects. But a tutorial-shaped
template adapted to the project's actual imports/parameters/basins
is good enough as a starting draft — configurator reviews and tweaks.

Fallback chain:
  1. If the project provides ``inputs/filtersFile.yaml`` → use it.
  2. Otherwise, the LLM drafter produces a draft from the project's
     IDs.
  3. If the LLM drafter fails (Ollama down, validation fails), the
     standard ``filtersFile.yaml`` (bundled) is rendered as final
     fallback.
"""
from __future__ import annotations

import re
from typing import Any

from .providers.ollama_provider import OllamaProvider


def collect_filter_context(
    rendered_files: list[Any],
) -> dict[str, list[str]]:
    """Walk rendered XMLs to collect IDs the LLM can safely reference.

    Returns lists of valid moduleInstanceIds, parameterIds, and
    locationIds the LLM can use in its filter draft. Anything outside
    these lists gets dropped post-render.
    """
    from lxml import etree

    module_ids: set[str] = set()
    parameter_ids: set[str] = set()
    location_ids: set[str] = set()
    for rf in rendered_files:
        try:
            tree = etree.fromstring(rf.content.encode("utf-8"))
        except etree.XMLSyntaxError:
            continue
        for el in tree.iter("{*}moduleInstanceId"):
            t = (el.text or "").strip()
            if t and not t.startswith("$"):
                module_ids.add(t)
        for el in tree.iter("{*}parameterId"):
            t = (el.text or "").strip()
            if t and not t.startswith("$"):
                parameter_ids.add(t)
        for el in tree.iter("{*}locationId"):
            t = (el.text or "").strip()
            if t and not t.startswith("$"):
                location_ids.add(t)
    return {
        "moduleInstanceIds": sorted(module_ids),
        "parameterIds": sorted(parameter_ids),
        "locationIds": sorted(location_ids),
    }


def draft_filters_yaml(
    context: dict[str, list[str]],
    project_intent: str | None = None,
    provider: OllamaProvider | None = None,
    model: str = "qwen2.5:7b-instruct",
) -> dict[str, Any] | None:
    """Ask qwen to draft a filtersFile.yaml structure.

    Returns a dict shaped like ``{"body": [...]}`` ready for
    ``Filters.model_validate()``. Returns ``None`` if the LLM call
    fails or the output can't be made valid.
    """
    if provider is None:
        from .providers.factory import get_provider_or_ollama
        provider = get_provider_or_ollama(model)

    module_ids = context.get("moduleInstanceIds", [])
    param_ids = context.get("parameterIds", [])

    if not module_ids:
        return None  # nothing to filter on

    system = (
        "You design a FEWS filtersFile.xml structure. Filters group "
        "time-series data so users can pick what to display. RULES:\n"
        "1) Use ONLY moduleInstanceIds from the provided list. Don't "
        "invent any.\n"
        "2) Use ONLY parameterIds from the provided list.\n"
        "3) Group filters semantically: typically one filter group per "
        "data category (NWP forecasts, station observations, model "
        "outputs, snow imports).\n"
        "4) Each filter group has a unique snake/camel id and a list "
        "of timeSeriesSet entries.\n"
        "5) Output JSON in this shape:\n"
        '   {"groups": [{"id": "...", "name": "...", "module_instance_ids": '
        '[...], "parameter_ids": [...]}, ...]}\n'
        "6) Output JSON only, no prose."
    )
    user = (
        f"Available moduleInstanceIds ({len(module_ids)}): "
        f"{', '.join(module_ids[:30])}"
        + (" ..." if len(module_ids) > 30 else "") + "\n"
        f"Available parameterIds ({len(param_ids)}): "
        f"{', '.join(param_ids[:30])}"
        + (" ..." if len(param_ids) > 30 else "") + "\n\n"
        f"Project intent: {project_intent or 'flood/hydrological forecasting'}\n\n"
        f"Propose 3-6 filter groups."
    )
    schema = {
        "type": "object",
        "properties": {
            "groups": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string"},
                        "name": {"type": "string"},
                        "module_instance_ids": {
                            "type": "array",
                            "items": {"type": "string"},
                        },
                        "parameter_ids": {
                            "type": "array",
                            "items": {"type": "string"},
                        },
                    },
                    "required": ["id"],
                },
            },
        },
        "required": ["groups"],
    }

    try:
        resp = provider.generate_json(system=system, user=user, schema=schema)
    except Exception:
        return None
    data = resp.data or {}
    groups = data.get("groups") or []
    if not groups:
        return None

    valid_modules = set(module_ids)
    valid_params = set(param_ids)

    body: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for g in groups:
        gid = re.sub(r"[^A-Za-z0-9_]", "_", str(g.get("id", "")).strip())
        if not gid or gid in seen_ids:
            continue
        seen_ids.add(gid)
        # Filter to valid IDs only.
        mids = [m for m in g.get("module_instance_ids", []) if m in valid_modules]
        pids = [p for p in g.get("parameter_ids", []) if p in valid_params]
        if not mids:
            continue
        # Build simple timeSeriesSet entries — one per (module, parameter) pair.
        # Keeps the draft minimal; configurator extends.
        ts_sets: list[dict[str, Any]] = []
        for mid in mids:
            for pid in pids or [None]:
                # XSD requires fields in this order; locationSetId is
                # a required choice (locationId / locationSetId /
                # chainageLocationSetId). We use a placeholder here;
                # configurator can override with project-specific
                # location sets.
                entry: dict[str, Any] = {
                    "moduleInstanceId": mid,
                    "valueType": "scalar",
                }
                if pid:
                    entry["parameterId"] = pid
                else:
                    entry["parameterId"] = "Q.simulated"  # placeholder
                entry.update({
                    "locationSetId": "AllLocations",  # PLACEHOLDER
                    "timeSeriesType": "external historical",
                    "timeStep": {"@id": "$DAY_TIMESTEP$"},
                    "readWriteMode": "add originals",
                })
                ts_sets.append(entry)
        body.append({
            "timeSeriesSets": {
                "@id": gid,
                "timeSeriesSet": ts_sets,
            },
        })

    if not body:
        return None

    # XSD requires at least one <filter> entry. Add a minimal parent
    # filter that references each timeSeriesSets group as a child.
    # Configurator will replace this with a proper filter tree later.
    body.append({
        "filter": {
            "@id": "AllData",
            "@name": "All Data (auto-drafted)",
            "child": [{"@foreignKey": gid} for gid in seen_ids],
        },
    })

    # Default to the parent filter as the visible default.
    body.insert(0, {"defaultFilterId": "AllData"})
    return {"body": body}


__all__ = ["collect_filter_context", "draft_filters_yaml"]
