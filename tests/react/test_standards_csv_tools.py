"""get_standard + write_input_csv + ingest_csvs."""
from __future__ import annotations

from fews_agent.react.tools.csv_tools import INGEST_CSVS, WRITE_INPUT_CSV
from fews_agent.react.tools.file_tools import WRITE_CONFIG_FILE
from fews_agent.react.tools.standards_tools import GET_STANDARD


def test_get_standard_catalog(ctx):
    catalog = GET_STANDARD.handler(ctx, {})
    assert catalog["count"] >= 30
    names = {row["name"] for row in catalog["standards"]}
    assert {"timeSteps", "gridsFile", "idImportGFS"} <= names


def test_get_standard_single_roundtrips_through_writer(ctx):
    std = GET_STANDARD.handler(ctx, {"name": "timeSteps"})
    assert std["spec_name"] == "timeSteps"
    result = WRITE_CONFIG_FILE.handler(ctx, {
        "spec_name": std["spec_name"], "data": std["data"],
    })
    assert result.get("ok"), result


def test_get_standard_unknown(ctx):
    assert "error" in GET_STANDARD.handler(ctx, {"name": "zzz"})


def test_write_input_csv_and_ingest(ctx):
    written = WRITE_INPUT_CSV.handler(ctx, {
        "filename": "locations.csv",
        "header": ["id", "name", "lat", "lon"],
        "rows": [
            ["ST1", "Accra Gauge", "5.55", "-0.21"],
            ["ST2", "Takoradi Gauge", "4.89", "-1.75"],
        ],
    })
    assert written.get("ok") and written["rows_written"] == 2
    report = INGEST_CSVS.handler(ctx, {})
    entries = {e["csv"]: e for e in report["ingested"]}
    loc = entries["locations.csv"]
    assert loc["rows_parsed"] == 2, loc
    assert loc["written"] == "RegionConfigFiles/Locations.xml"
    rel = loc["written"]
    assert rel in ctx.rendered
    assert ctx.rendered[rel].model is not None
    assert "ST1" in ctx.rendered[rel].content


def test_write_input_csv_rejects_bad_shape(ctx):
    assert "error" in WRITE_INPUT_CSV.handler(ctx, {
        "filename": "locations.csv", "header": ["id"], "rows": [["a", "b"]],
    })
    assert "error" in WRITE_INPUT_CSV.handler(ctx, {
        "filename": "../evil.csv", "header": ["id"], "rows": [],
    })
    assert "error" in WRITE_INPUT_CSV.handler(ctx, {
        "filename": "notes.txt", "header": ["id"], "rows": [],
    })


def test_ingest_reports_unrecognized_csv(ctx):
    WRITE_INPUT_CSV.handler(ctx, {
        "filename": "mystery.csv", "header": ["a"], "rows": [["1"]],
    })
    report = INGEST_CSVS.handler(ctx, {})
    entries = {e["csv"]: e for e in report["ingested"]}
    assert entries["mystery.csv"]["spec_name"] is None
    assert "unrecognized" in entries["mystery.csv"]["note"]
