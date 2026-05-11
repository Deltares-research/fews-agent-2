"""Hand-rolled handler for ``inputs/validationRuleSets.yaml``.

Minimum XSD-valid entry:
  validationRuleSet
    @validationRuleSetId, @timeZone (XSD-required attribute)
    extremeValues with at least hardMax + hardMin (constantLimit each)
    timeSeriesSet with module/param/locSet binding

POC scope: one rule set per session, with the four extreme bounds and
a single timeSeriesSet target. Configurator can extend yaml later for
rateOfChange, sameReading, multiple targets, etc.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml as _yaml

from fews_agent.schema import ValidationRuleSets


def advance(state, user_message, project_dir):
    edit = state["_editing"]
    stage = edit.get("stage", "_start")
    msg = (user_message or "").strip()
    edit.setdefault("draft", {})
    edit["draft"].setdefault("validationRuleSet", [])
    edit.setdefault("current", {})

    if stage == "_start":
        edit["stage"] = "ask_add"
        return (
            "Entering edit mode for validationRuleSets.yaml. Each rule "
            "set checks one (module, parameter, locationSet) triple "
            "against extreme-value bounds. Type /cancel-edit to abort.\n"
            "Add a validationRuleSet? (y/n)",
            False,
        )

    if stage == "ask_add":
        if msg.lower() in {"y", "yes"}:
            edit["current"] = {}
            edit["stage"] = "vrs_id"
            return ("validationRuleSetId (e.g. VRS_PC):", False)
        if msg.lower() in {"n", "no"}:
            if not edit["draft"]["validationRuleSet"]:
                return ("Need at least one rule set. Add one? (y/n)", False)
            edit["stage"] = "review"
            return (_summary(edit["draft"]), False)
        return ("y or n.", False)

    if stage == "vrs_id":
        if not msg:
            return ("Id can't be empty:", False)
        edit["current"]["validationRuleSetId"] = msg
        edit["stage"] = "timezone"
        return ("Time zone (e.g. GMT, PST):", False)

    if stage == "timezone":
        if not msg:
            return ("Time zone can't be empty:", False)
        edit["current"]["timeZone"] = msg
        edit["stage"] = "hard_max"
        return ("hardMax bound (numeric, e.g. 10000):", False)

    if stage == "hard_max":
        if not msg:
            return ("hardMax can't be empty:", False)
        edit["current"]["extremeValues"] = {"hardMax": {"constantLimit": msg}}
        edit["stage"] = "hard_min"
        return ("hardMin bound (numeric, e.g. -10000):", False)

    if stage == "hard_min":
        if not msg:
            return ("hardMin can't be empty:", False)
        edit["current"]["extremeValues"]["hardMin"] = {"constantLimit": msg}
        edit["stage"] = "tss_module"
        return (
            "Target moduleInstanceId for this rule (e.g. ImportWSCHourly):",
            False,
        )

    if stage == "tss_module":
        if not msg:
            return ("moduleInstanceId can't be empty:", False)
        edit["_tss"] = {
            "moduleInstanceId": msg, "valueType": "scalar",
            "timeSeriesType": "external historical",
            "timeStep": {"id": "$DAY_TIMESTEP$"},
            "readWriteMode": "read only",
        }
        edit["stage"] = "tss_param"
        return ("Target parameterId (e.g. PC.nwp, Q.observed):", False)

    if stage == "tss_param":
        if not msg:
            return ("parameterId can't be empty:", False)
        edit["_tss"]["parameterId"] = msg
        edit["stage"] = "tss_locset"
        return ("Target locationSetId (e.g. AllLocations):", False)

    if stage == "tss_locset":
        if not msg:
            return ("locationSetId can't be empty:", False)
        edit["_tss"]["locationSetId"] = msg
        edit["current"]["timeSeriesSet"] = [edit["_tss"]]
        edit["draft"]["validationRuleSet"].append(edit["current"])
        rid = edit["current"]["validationRuleSetId"]
        edit["current"] = {}
        edit["_tss"] = {}
        edit["stage"] = "ask_add"
        n = len(edit["draft"]["validationRuleSet"])
        return (
            f"Added '{rid}' (total: {n}). Add another rule set? (y/n)",
            False,
        )

    if stage == "review":
        if msg.lower() in {"y", "yes"}:
            return _validate_and_write(edit["draft"], project_dir)
        if msg.lower() in {"n", "no"}:
            return ("Cancelled.", True)
        return ("y or n.", False)

    return (f"(unknown stage {stage!r}; aborting)", True)


def _summary(draft):
    lines = [
        f"Ready to write validationRuleSets.yaml with "
        f"{len(draft['validationRuleSet'])} rule set(s):"
    ]
    for r in draft["validationRuleSet"]:
        ev = r.get("extremeValues", {})
        h_max = ev.get("hardMax", {}).get("constantLimit", "?")
        h_min = ev.get("hardMin", {}).get("constantLimit", "?")
        tss = (r.get("timeSeriesSet") or [{}])[0]
        lines.append(
            f"  - {r['validationRuleSetId']}: "
            f"[{h_min}, {h_max}] on "
            f"{tss.get('moduleInstanceId','?')}/"
            f"{tss.get('parameterId','?')}/"
            f"{tss.get('locationSetId','?')}"
        )
    lines.append("Confirm? (y/n)")
    return "\n".join(lines)


def _validate_and_write(draft, project_dir):
    try:
        ValidationRuleSets.model_validate(draft)
    except Exception as exc:  # noqa: BLE001
        return (f"Validation failed: {type(exc).__name__}: {str(exc)[:200]}", True)
    inputs_dir = project_dir / "inputs"
    inputs_dir.mkdir(parents=True, exist_ok=True)
    path = inputs_dir / "validationRuleSets.yaml"
    path.write_text(
        _yaml.safe_dump(draft, sort_keys=False, default_flow_style=False),
        encoding="utf-8",
    )
    return (f"Wrote {path}.", True)


__all__ = ["advance"]
