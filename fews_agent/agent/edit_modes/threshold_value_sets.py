"""Hand-rolled handler for ``inputs/thresholdValueSets.yaml``.

A thresholdValueSet binds:
  - a list of levelThresholdValue entries (each levelThresholdId →
    valueFunction numeric)
  - one or more timeSeriesSet targets (which series to watch)

POC scope: one set per session, multiple levelThresholdValue entries
in a loop, one timeSeriesSet target. Configurator can extend yaml
later for stage/discharge translation, multiple targets, qualifiers.
"""
from __future__ import annotations

from pathlib import Path

import yaml as _yaml

from fews_agent.schema import ThresholdValueSets


def advance(state, user_message, project_dir):
    edit = state["_editing"]
    stage = edit.get("stage", "_start")
    msg = (user_message or "").strip()
    edit.setdefault("draft", {})
    edit["draft"].setdefault("thresholdValueSet", [])
    edit.setdefault("current", {})
    edit.setdefault("ltv_list", [])

    if stage == "_start":
        edit["stage"] = "ask_add"
        return (
            "Entering edit mode for thresholdValueSets.yaml. Each set "
            "binds threshold levels (declared in thresholds.yaml) to "
            "specific numeric values for a targeted time series. Type "
            "/cancel-edit to abort.\nAdd a thresholdValueSet? (y/n)",
            False,
        )

    if stage == "ask_add":
        if msg.lower() in {"y", "yes"}:
            edit["current"] = {}
            edit["ltv_list"] = []
            edit["stage"] = "tvs_id"
            return ("thresholdValueSet id (e.g. TVS_PC_Liard):", False)
        if msg.lower() in {"n", "no"}:
            if not edit["draft"]["thresholdValueSet"]:
                return ("Need at least one set. Add one? (y/n)", False)
            edit["stage"] = "review"
            return (_summary(edit["draft"]), False)
        return ("y or n.", False)

    if stage == "tvs_id":
        if not msg:
            return ("Id can't be empty:", False)
        edit["current"]["id"] = msg
        edit["stage"] = "ltv_id"
        return (
            "levelThresholdId for this value (matches a level in "
            "thresholds.yaml, e.g. L1_Flood):",
            False,
        )

    if stage == "ltv_id":
        if not msg:
            return ("levelThresholdId can't be empty:", False)
        edit["_ltv"] = {"levelThresholdId": msg}
        edit["stage"] = "ltv_value"
        return (
            "valueFunction (numeric or FEWS placeholder, e.g. 5 or "
            "@AlertLevel@):",
            False,
        )

    if stage == "ltv_value":
        if not msg:
            return ("valueFunction can't be empty:", False)
        edit["_ltv"]["valueFunction"] = msg
        edit["ltv_list"].append(edit["_ltv"])
        edit["_ltv"] = {}
        edit["stage"] = "more_ltv"
        return (
            f"Added level value (total in this set: {len(edit['ltv_list'])}). "
            "Add another level value? (y/n)",
            False,
        )

    if stage == "more_ltv":
        if msg.lower() in {"y", "yes"}:
            edit["stage"] = "ltv_id"
            return ("levelThresholdId:", False)
        if msg.lower() in {"n", "no"}:
            edit["current"]["levelThresholdValue"] = edit["ltv_list"]
            edit["stage"] = "tss_module"
            return (
                "Target moduleInstanceId for this set "
                "(e.g. ImportWSCHourly):",
                False,
            )
        return ("y or n.", False)

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
        return ("Target parameterId (e.g. Q.observed):", False)

    if stage == "tss_param":
        if not msg:
            return ("parameterId can't be empty:", False)
        edit["_tss"]["parameterId"] = msg
        edit["stage"] = "tss_locset"
        return ("Target locationSetId (e.g. WSCStations):", False)

    if stage == "tss_locset":
        if not msg:
            return ("locationSetId can't be empty:", False)
        edit["_tss"]["locationSetId"] = msg
        edit["current"]["timeSeriesSet"] = [edit["_tss"]]
        edit["draft"]["thresholdValueSet"].append(edit["current"])
        sid = edit["current"]["id"]
        edit["current"] = {}
        edit["_tss"] = {}
        edit["ltv_list"] = []
        edit["stage"] = "ask_add"
        n = len(edit["draft"]["thresholdValueSet"])
        return (
            f"Added '{sid}' (total: {n}). Add another set? (y/n)",
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
        f"Ready to write thresholdValueSets.yaml with "
        f"{len(draft['thresholdValueSet'])} set(s):"
    ]
    for s in draft["thresholdValueSet"]:
        levels = ", ".join(
            f"{v['levelThresholdId']}={v['valueFunction']}"
            for v in s.get("levelThresholdValue", [])
        )
        lines.append(f"  - {s['id']}: [{levels}]")
    lines.append("Confirm? (y/n)")
    return "\n".join(lines)


def _validate_and_write(draft, project_dir):
    try:
        ThresholdValueSets.model_validate(draft)
    except Exception as exc:  # noqa: BLE001
        return (f"Validation failed: {type(exc).__name__}: {str(exc)[:200]}", True)
    inputs_dir = project_dir / "inputs"
    inputs_dir.mkdir(parents=True, exist_ok=True)
    path = inputs_dir / "thresholdValueSets.yaml"
    path.write_text(
        _yaml.safe_dump(draft, sort_keys=False, default_flow_style=False),
        encoding="utf-8",
    )
    return (f"Wrote {path}.", True)


__all__ = ["advance"]
