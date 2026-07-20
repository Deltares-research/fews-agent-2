"""FEWS-Conform ModuleInstanceSets contribution for raven_basin.

Conform groups a model's run instances into named ModuleInstanceSets so
Filters / DisplayGroups reference a stable set id instead of enumerating
instances. `raven_basin` contributes two such sets per basin — but only
when `conform_module_instance_sets: true`, because the byte-equivalent
tutorial oracle has no ModuleInstanceSets.xml and the default must not
add one.

Tested at the expand() layer (where contributions are collected) plus an
XSD render check. The projects/ fixtures are gitignored, so this is the
durable oracle.
"""
from __future__ import annotations

from pathlib import Path

from fews_agent.agent.blueprint import Blueprint, PatternRef, expand
from fews_agent.agent.global_properties_derivation import (
    derive_global_properties,
)
from fews_agent.generators import SPECS
from fews_agent.generators.base import render as render_template
from fews_agent.validation.xsd import validate_xsd

REPO_ROOT = Path(__file__).resolve().parents[1]
PATTERNS_ROOT = REPO_ROOT / "patterns"


def _expand(flag):
    inst = {"basin_name": "Liard"}
    if flag is not None:
        inst["conform_module_instance_sets"] = flag
    bp = Blueprint(
        name="raven-mis-test",
        output_root=Path("out"),
        patterns=[PatternRef(pattern="auto/raven_basin", instances=[inst])],
    )
    res = expand(bp, PATTERNS_ROOT)
    assert not res.errors, res.errors
    return res


def _mis_contributions(flag):
    """Expand raven_basin(Liard) and return its ModuleInstanceSets payloads."""
    return [
        c.payload for c in _expand(flag).contributions
        if c.target_file.startswith("ModuleInstanceSets::")
    ]


def _filter_files(flag):
    """Rendered Filters files (relpath → content) from the expansion."""
    return {
        rf.relpath.replace("\\", "/"): rf.content
        for rf in _expand(flag).rendered_files
        if "Filters" in rf.relpath
    }


def _expand_inst(**inst):
    inst.setdefault("basin_name", "Liard")
    bp = Blueprint(
        name="raven-id-test",
        output_root=Path("out"),
        patterns=[PatternRef(pattern="auto/raven_basin", instances=[inst])],
    )
    res = expand(bp, PATTERNS_ROOT)
    assert not res.errors, res.errors
    return res


def _run_module(res):
    rf = next(
        rf for rf in res.rendered_files
        if rf.relpath.replace("\\", "/").endswith("LiardHistoricTemplate.xml")
    )
    return rf.content


def test_off_by_default_no_contribution():
    # No flag → default false → oracle-safe (no ModuleInstanceSets added).
    assert _mis_contributions(None) == []
    assert _mis_contributions(False) == []


def test_on_emits_forecast_and_historic_sets():
    payloads = _mis_contributions(True)
    by_id = {p["id"]: p for p in payloads}
    assert set(by_id) == {"LiardRavenForecast", "LiardRavenHistoric"}
    # basin_name is baked into the set id at expand time...
    assert by_id["LiardRavenForecast"]["moduleInstanceId"] == [
        "$MODELNAME2$GDPSForecast",
        "$MODELNAME2$RDPSForecast",
        "$MODELNAME2$REPSForecast",
    ]
    # ...while $MODELNAME2$ stays literal (FEWS resolves it at startup, so
    # membership tracks whatever the run modules register).
    assert by_id["LiardRavenHistoric"]["moduleInstanceId"] == [
        "$MODELNAME2$Historic",
    ]


def test_contribution_renders_xsd_valid():
    payloads = _mis_contributions(True)
    spec = next(s for s in SPECS if s.name == "moduleInstanceSets")
    model = spec.model_class.model_validate({"moduleInstanceSet": payloads})
    xml = render_template(spec.template_name, model)
    ok, msg = validate_xsd(xml.encode("utf-8"))
    assert ok, msg
    assert 'id="LiardRavenForecast"' in xml
    assert "$MODELNAME2$Historic" in xml


# ---------------------------------------------------------------------------
# The payoff: a split Filters file that references the sets via
# <moduleInstanceSetId> (not enumerated instances), FEWS-merged alongside
# the drafter's base Filters.xml.
# ---------------------------------------------------------------------------

def test_off_by_default_no_split_filter():
    # raven_basin always emits its ModuleConfig/Workflow files, but no
    # Filters file unless the Conform flag is on.
    assert _filter_files(None) == {}
    assert _filter_files(False) == {}


def test_on_emits_split_filter_referencing_the_sets():
    files = _filter_files(True)
    assert set(files) == {"RegionConfigFiles/ModelRun/FiltersLiard.xml"}
    xml = files["RegionConfigFiles/ModelRun/FiltersLiard.xml"]
    # The filter references the ModuleInstanceSet, not concrete instances —
    # this indirection is the whole point.
    assert "<moduleInstanceSetId>LiardRavenForecast</moduleInstanceSetId>" in xml
    assert "<moduleInstanceSetId>LiardRavenHistoric</moduleInstanceSetId>" in xml
    # And the filter tree wires the timeSeriesSets in.
    assert '<timeSeriesSetsId>LiardRavenForecast</timeSeriesSetsId>' in xml
    assert '<filter id="LiardRaven" name="Liard">' in xml
    ok, msg = validate_xsd(xml.encode("utf-8"))
    assert ok, msg


# ---------------------------------------------------------------------------
# basin_local_ids: per-basin identity (the fix for the $MODELNAME2$ farming
# artifact). Off = placeholders preserved (oracle-safe); on = concrete ids
# + Conform wildcard sets, and the line-562 inconsistency is corrected.
# ---------------------------------------------------------------------------

def test_local_ids_off_preserves_placeholders():
    xml = _run_module(_expand_inst())  # basin_local_ids defaults false
    assert "$MODELNAME2$Historic" in xml
    assert "$MODELNAME1$Basins" in xml


def test_local_ids_on_uses_concrete_basin_ids():
    xml = _run_module(_expand_inst(basin_local_ids=True))
    assert "<moduleInstanceId>LiardHistoric</moduleInstanceId>" in xml
    assert "<locationSetId>LiardSubBasins</locationSetId>" in xml
    assert "<locationSetId>LiardBasins</locationSetId>" in xml
    # No unresolved project-global placeholders remain.
    assert "$MODELNAME1$" not in xml
    assert "$MODELNAME2$" not in xml


def test_local_ids_on_fixes_line562_inconsistency():
    # The stray $MODELNAME1$REPSForecast becomes the consistent
    # LiardREPSForecast (every other forecast run used MODELNAME2).
    res = _expand_inst(basin_local_ids=True)
    reps = next(
        rf for rf in res.rendered_files
        if rf.relpath.replace("\\", "/").endswith("RunLiardREPSForecast.xml")
    )
    assert "LiardREPSForecast" in reps.content
    assert "$MODELNAME1$" not in reps.content


def test_local_ids_on_sets_use_conform_wildcards():
    payloads = {
        c.payload["id"]: c.payload
        for c in _expand_inst(
            basin_local_ids=True, conform_module_instance_sets=True,
        ).contributions
        if c.target_file.startswith("ModuleInstanceSets::")
    }
    assert payloads["LiardRavenForecast"]["moduleInstanceIdPattern"] == [
        "Liard*Forecast",
    ]
    assert payloads["LiardRavenHistoric"]["moduleInstanceIdPattern"] == [
        "Liard*Historic",
    ]


# ---------------------------------------------------------------------------
# Fix C: a single-basin project must resolve $MODELNAME2$ (the raven pattern
# references its own runs via it). Before, MODELNAME2 was only emitted for
# >=2 basins, leaving those ids dead at FEWS startup.
# ---------------------------------------------------------------------------

def _bp(*basins):
    return Blueprint(
        name="props-test",
        output_root=Path("out"),
        patterns=[PatternRef(
            pattern="auto/raven_basin",
            instances=[{"basin_name": b} for b in basins],
        )],
    )


def test_single_basin_resolves_modelname2():
    props = derive_global_properties(_bp("Liard"))
    assert "MODELNAME1 = Liard" in props
    assert "MODELNAME2 = Liard" in props   # was absent → $MODELNAME2$ was dead
    assert "MODEL2_TIMESTEP=" in props


def test_two_basins_keep_positional_mapping():
    # Tutorial shape: MODELNAME2 is the *second* basin (oracle unchanged).
    props = derive_global_properties(_bp("Liard", "Snare"))
    assert "MODELNAME1 = Liard" in props
    assert "MODELNAME2 = Snare" in props
