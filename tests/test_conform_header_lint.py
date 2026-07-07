"""FEWS-Conform CSV header lint (option 3).

``lint_conform_headers`` is advisory: it flags columns that become
location attributeIds but violate the Conform attributeId convention
(PascalCase, no spaces/_/-/.), plus duplicate headers. It must produce
**zero** warnings on the minimal lowercase CSVs the agent already
accepts (those columns map by alias, not by becoming attributes).
"""
from __future__ import annotations

from fews_agent.agent.csv_ingest import ingest_csv, lint_conform_headers


def test_clean_conform_headers_pass():
    headers = ["FewsId", "Name", "Lat", "Lon", "Type", "ModelId"]
    attrs = ["Type", "ModelId"]  # the non-reserved (attribute-bound) columns
    assert lint_conform_headers(headers, attrs) == []


def test_minimal_lowercase_csv_produces_no_warnings():
    # All columns map by alias → none become attributes → nothing to lint.
    headers = ["id", "name", "lat", "lon", "description"]
    assert lint_conform_headers(headers, attribute_headers=[]) == []


def test_underscore_attribute_flagged():
    warns = lint_conform_headers(["FewsId", "wflow_id"], ["wflow_id"])
    assert len(warns) == 1
    assert "wflow_id" in warns[0]
    assert "valid one" in warns[0]


def test_space_attribute_flagged():
    warns = lint_conform_headers(["FewsId", "Model Id"], ["Model Id"])
    assert any("Model Id" in w and "valid one" in w for w in warns)


def test_lowercase_attribute_suggests_pascalcase():
    warns = lint_conform_headers(["FewsId", "modelId"], ["modelId"])
    assert len(warns) == 1
    assert "PascalCase" in warns[0]
    assert "'ModelId'" in warns[0]  # the suggestion


def test_duplicate_headers_flagged_case_insensitive():
    warns = lint_conform_headers(["Type", "type", "Name"], [])
    assert any("duplicate" in w.lower() for w in warns)


def test_lint_flows_into_ingestresult_warnings(tmp_path):
    csv = tmp_path / "locations.csv"
    csv.write_text(
        "FewsId,Name,Lat,Lon,wflow_id\n"
        "L1,Gauge,1.0,2.0,42\n",
        encoding="utf-8",
    )
    result = ingest_csv(csv)
    assert result.rows_parsed == 1                 # ingest still succeeds
    assert any("wflow_id" in w for w in result.warnings)


def test_lint_scoped_to_locations_not_parameters(tmp_path):
    # A dropped non-PascalCase column in parameters.csv is NOT an
    # attributeId, so it must not trigger the attribute lint.
    csv = tmp_path / "parameters.csv"
    csv.write_text(
        "parameterId,name,unit,parameterType,some_extra\n"
        "Q,Discharge,m3/s,instantaneous,x\n",
        encoding="utf-8",
    )
    result = ingest_csv(csv)
    assert not any("some_extra" in w for w in result.warnings)
