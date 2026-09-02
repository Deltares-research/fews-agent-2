"""Chat wiring for the process/maintenance tail of the FEWS-Caribbean farm.

Pure-function tests (no LLM). Cover:
  * the ``wants_maintenance`` flag -> an orphan-sweep amalgamate module (valid
    in any project, no dangling workflow refs),
  * the IOC sea-level companion: importing IOC auto-adds the aggregate+shift
    processing (tpl_aggregate_shift_sealevel).
The coastal process chain (wind/precip/hindcast/interp/forecast-start) is
covered by test_coastal_wiring.py's forecasting-template tests.
"""
from __future__ import annotations

import pytest

from fews_agent.agent import project_intents as pi

_PATHS = {
    "auto/gfs/deterministic", "auto/wf_import/noaa_grids",
    "auto/import_sealevel_ioc", "auto/tpl_aggregate_shift_sealevel",
    "auto/amalgamate",
}


def _names(res):
    return {r["pattern"] for r in res}


@pytest.mark.parametrize(
    "text",
    ["run daily amalgamate", "keep the datastore lean", "add datastore maintenance"],
)
def test_detect_wants_maintenance(text):
    assert pi.detect_wants_maintenance(text) is True


def test_detect_wants_maintenance_none_on_miss():
    assert pi.detect_wants_maintenance("import GFS and run a model") is None


def test_maintenance_flag_adds_orphan_sweep_amalgamate():
    got = pi._resolve_data_import_only_patterns(
        {"imports": ["GFS"], "wants_maintenance": True}, _PATHS
    )
    amalg = [r for r in got if r["pattern"] == "auto/amalgamate"]
    assert amalg, "amalgamate not added"
    inst = amalg[0]["instances"][0]
    assert inst["workflow_ids"] == [] and inst["amalgamate_orphans"] is True


def test_no_maintenance_flag_no_amalgamate():
    got = _names(pi._resolve_data_import_only_patterns({"imports": ["GFS"]}, _PATHS))
    assert "auto/amalgamate" not in got


def test_ioc_import_pulls_in_sealevel_processing():
    got = _names(pi._resolve_data_import_only_patterns({"imports": ["IOC"]}, _PATHS))
    assert "auto/import_sealevel_ioc" in got
    assert "auto/tpl_aggregate_shift_sealevel" in got


def test_non_ioc_import_has_no_sealevel_processing():
    got = _names(pi._resolve_data_import_only_patterns({"imports": ["GFS"]}, _PATHS))
    assert "auto/tpl_aggregate_shift_sealevel" not in got
