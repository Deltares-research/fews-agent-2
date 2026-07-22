"""The Conform-convention CSV input set is genuinely Conform-compatible.

`tests/fixtures/conform_inputs/` holds a minimal configurator input set
authored to FEWS-Conform conventions (PascalCase headers, FewsId ids, rich
attribute columns, full Parameters columns). This pins that the agent
ingests it cleanly, the header linter stays silent, and the csvFile
LocationSet build path preserves the attribute columns.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from fews_agent.agent.csv_ingest import ingest_directory
from runners.agent.build_from_blueprint import build_from_blueprint

REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURE = REPO_ROOT / "tests" / "fixtures" / "conform_inputs"
PATTERNS_ROOT = REPO_ROOT / "fews_agent" / "patterns"


def test_all_four_csvs_ingest_cleanly():
    results = ingest_directory(FIXTURE)
    assert set(results) == {
        "locations", "parameters", "qualifiers", "thresholdWarningLevels",
    }
    for name, r in results.items():
        assert r.model is not None, (name, r.errors)
        assert r.rows_failed == 0, (name, r.errors)


def test_conform_headers_produce_no_lint_warnings():
    # PascalCase attribute headers (Type/ModelId/WflowId...) are valid
    # attributeIds → the Conform header lint must stay silent.
    results = ingest_directory(FIXTURE)
    all_warnings = [w for r in results.values() for w in r.warnings]
    assert all_warnings == [], all_warnings


def test_pascalcase_ids_and_altitude_map():
    loc = ingest_directory(FIXTURE)["locations"]
    ids = [l.id for l in loc.model.location]
    assert ids[0] == "L_041457"                    # FewsId → id (not blank)
    assert any(l.z and l.z != 0 for l in loc.model.location)  # Alt → z
    # Attribute columns are unmapped (they become <attribute>s on the
    # csvFile path, not typed Location fields).
    assert "Type" in loc.unknown_headers
    assert "WflowIdDischarge" in loc.unknown_headers


def test_rich_parameter_fields_land():
    par = ingest_directory(FIXTURE)["parameters"]
    groups = {g.id: g for g in par.model.parameterGroup}
    # DisplayUnit / ParameterGroupName / UsesDatum / AllowMissing all flow.
    assert groups["WaterLevel"].usesDatum is True
    assert groups["Precipitation"].displayUnit == "mm"
    precip = groups["Precipitation"].parameter[0]
    assert precip.allowMissing is True


def test_csvfile_build_preserves_attributes(tmp_path):
    # Build a project pointing at the fixture with the Conform csvFile
    # opt-in; the attribute columns must survive into LocationSets.xml and
    # no Locations.xml is materialised.
    import yaml

    bp = {
        "name": "conform-inputs-build",
        "output_root": "out",
        "metadata": {"locations_as_csvfile": True, "location_set_id": "Stations"},
        "patterns": [],
        "singleton_seeds": {"Locations": {"geoDatum": "WGS 1984"}},
    }
    bp_path = tmp_path / "project.yaml"
    bp_path.write_text(yaml.safe_dump(bp), encoding="utf-8")

    summary = build_from_blueprint(
        blueprint_path=bp_path,
        pattern_root=PATTERNS_ROOT,
        inputs_dir=FIXTURE,
    )
    assert summary["ok"] is not False

    out = (bp_path.parent / "out").resolve()
    locsets = (out / "RegionConfigFiles" / "LocationSets.xml").read_text(
        encoding="utf-8"
    )
    assert '<locationSet id="Stations">' in locsets
    assert "<csvFile>" in locsets
    # The Conform attribute columns are preserved as location attributes.
    for attr in ("Type", "ModelId", "WflowIdDischarge", "WflowIdWaterLevel"):
        assert f'<attribute id="{attr}">' in locsets
    # Conform: locations live in LocationSets, never Locations.xml.
    assert not (out / "RegionConfigFiles" / "Locations.xml").exists()
