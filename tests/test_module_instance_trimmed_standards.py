"""modifierTypes/productsFile/thresholdValueSets/validationRuleSets --
bundled standards whose entries are each scoped to specific module
instances, previously rendered wholesale regardless of project content.

Colleague-reported: a GFS-only project's ModuleInstanceDescriptors.xml
listed ImportRDPS/ImportREPS/ModifyGDPS/etc -- traced to these four files
(unlike idMaps/gridsFile/displayGroupsFile, they had no trimming at all),
whose generic tutorial-inherited content the descriptor deriver faithfully
(but wrongly) harvested moduleInstanceIds from.
"""
from __future__ import annotations

from pathlib import Path

import yaml
from rich.console import Console

from runners.agent.build_from_blueprint import (
    _filter_by_module_instance_refs,
    _has_module_instance_ref,
    _references_known_module_instance,
    build_from_blueprint,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
PATTERNS_ROOT = REPO_ROOT / "fews_agent" / "patterns"


def _build(tmp_path, patterns):
    bp = {"name": "t", "output_root": "out", "patterns": patterns,
          "singleton_seeds": {"Locations": {"geoDatum": "WGS 1984"}}}
    proj = tmp_path / "project.yaml"
    proj.write_text(yaml.safe_dump(bp), encoding="utf-8")
    return build_from_blueprint(
        blueprint_path=proj, pattern_root=PATTERNS_ROOT,
        console=Console(quiet=True),
    )


# --- pure unit tests on the recursive filter --------------------------------

def test_entry_with_no_module_ref_is_kept_unconditionally():
    data = {"thing": [{"id": "A", "note": "no module instance here"}]}
    out = _filter_by_module_instance_refs(data, {"ImportGFS"})
    assert out == data


def test_entry_referencing_known_id_is_kept():
    data = {"thing": [{"id": "A", "moduleInstanceId": "ImportGFS"}]}
    out = _filter_by_module_instance_refs(data, {"ImportGFS"})
    assert out["thing"] == [{"id": "A", "moduleInstanceId": "ImportGFS"}]


def test_entry_referencing_only_unknown_id_is_dropped():
    data = {"thing": [
        {"id": "A", "moduleInstanceId": "ImportGFS"},
        {"id": "B", "moduleInstanceId": "ImportRDPS"},
    ]}
    out = _filter_by_module_instance_refs(data, {"ImportGFS"})
    assert out["thing"] == [{"id": "A", "moduleInstanceId": "ImportGFS"}]


def test_safeguard_keeps_everything_when_all_would_drop():
    data = {"thing": [{"id": "A", "moduleInstanceId": "ImportRDPS"}]}
    out = _filter_by_module_instance_refs(data, {"ImportGFS"})
    assert out == data


def test_nested_list_gets_the_same_treatment():
    # productsFile's real shape: body -> productCategory -> product, where
    # the filterable entries are TWO levels below the top-level list key.
    data = {"body": [{"productCategory": {"product": [
        {"id": "RDPSForecast", "timeSeriesFilter": [
            {"moduleInstanceId": "ImportRDPS"}]},
        {"id": "GFSForecast", "timeSeriesFilter": [
            {"moduleInstanceId": "ImportGFS"}]},
    ]}}]}
    out = _filter_by_module_instance_refs(data, {"ImportGFS"})
    kept_ids = {p["id"] for p in out["body"][0]["productCategory"]["product"]}
    assert kept_ids == {"GFSForecast"}


def test_references_known_and_has_any_ref_helpers():
    data = {"a": [{"moduleInstanceId": "ImportGFS"}]}
    assert _has_module_instance_ref(data)
    assert _references_known_module_instance(data, {"ImportGFS"})
    assert not _references_known_module_instance(data, {"ImportRDPS"})
    assert not _has_module_instance_ref({"a": [{"note": "nothing here"}]})


# --- integration: real build -------------------------------------------------

def test_whole_file_skipped_when_entirely_unrelated(tmp_path):
    # productsFile.yaml is entirely ECCC-forecast scoped; a GFS-only
    # project references none of it -- skipped outright, not emitted
    # wholesale.
    summary = _build(tmp_path, [
        {"pattern": "auto/gfs/deterministic", "instances": [{"nwp_name": "GFS"}]},
    ])
    assert summary["ok"], summary.get("errors")
    paths = {f["path"] for f in summary["files"]}
    assert "RegionConfigFiles/Products.xml" not in paths
    assert "RegionConfigFiles/ModifierTypes.xml" not in paths


def test_filters_and_spatialdisplay_skipped_when_entirely_unrelated(tmp_path):
    # filtersFile.yaml (bundled fallback) and spatialDisplayFile.yaml are
    # both entirely WSC/ECCC/RDPS/GDPS-scoped -- a GFS-only project
    # references none of it. filtersFile now goes through the same
    # _MODULE_INSTANCE_TRIMMED_SPECS mechanism as modifierTypes/
    # productsFile; spatialDisplayFile has its own whole-file skip
    # (gridDisplay.xsd requires >=1 populated gridPlotGroup, so there's no
    # valid "empty" fallback the way the other four specs have).
    # This was the actual root cause behind lingering
    # ModuleInstanceDescriptors clutter after the first four specs were
    # trimmed -- filtersFile's generic ImportWSC/ImportECCCScalar example
    # content made every OTHER trim in the same build think those sources
    # were "referenced" by the project.
    summary = _build(tmp_path, [
        {"pattern": "auto/gfs/deterministic", "instances": [{"nwp_name": "GFS"}]},
    ])
    assert summary["ok"], summary.get("errors")
    paths = {f["path"] for f in summary["files"]}
    assert "RegionConfigFiles/Filters.xml" not in paths
    assert "DisplayConfigFiles/SpatialDisplay.xml" not in paths
    descriptors = (
        Path(tmp_path) / "out" / "RegionConfigFiles" / "ModuleInstanceDescriptors.xml"
    ).read_text(encoding="utf-8")
    for extra in ("ImportRDPS", "ImportREPS", "ImportGDPS", "ImportWSC",
                  "ImportECCCScalar", "PreprocessGDPS"):
        assert extra not in descriptors, f"{extra} should not be in descriptors"
    assert "ImportGFS" in descriptors


def test_spatialdisplay_kept_and_trimmed_when_genuinely_relevant(tmp_path):
    summary = _build(tmp_path, [
        {"pattern": "auto/eccc/RDPS", "instances": [{"nwp_name": "RDPS"}]},
    ])
    assert summary["ok"], summary.get("errors")
    spatial = (
        Path(tmp_path) / "out" / "DisplayConfigFiles" / "SpatialDisplay.xml"
    ).read_text(encoding="utf-8")
    assert "RDPS" in spatial
    assert "gridPlotGroup" in spatial


def test_partial_relevance_trims_to_matching_entries(tmp_path):
    # An RDPS-only project keeps Products.xml, but only the RDPS-scoped
    # product entry -- GDPS/HRDPS/REPS entries from the bundled default
    # are dropped.
    summary = _build(tmp_path, [
        {"pattern": "auto/eccc/RDPS", "instances": [{"nwp_name": "RDPS"}]},
    ])
    assert summary["ok"], summary.get("errors")
    products = (Path(tmp_path) / "out" / "RegionConfigFiles" / "Products.xml").read_text(
        encoding="utf-8",
    )
    assert "RDPSForecast" in products
    assert "GDPSForecast" not in products
    assert "HRDPSForecast" not in products
