"""Writer tools: happy path, repairable errors, path safety, Decimal."""
from __future__ import annotations

from pathlib import Path

import yaml

from fews_agent.react.tools.file_tools import (
    LIST_PROJECT_FILES,
    READ_PROJECT_FILE,
    WRITE_CONFIG_FILE,
    _floats_to_decimal,
    safe_relpath,
)
from fews_agent.react.tools.specs_tools import DESCRIBE_SPEC, LIST_SPECS
from fews_agent.react.tools.validate_tools import VALIDATE_PROJECT

STANDARDS = (Path(__file__).resolve().parents[2]
             / "fews_agent" / "agent" / "standard_inputs")


def _timesteps_data() -> dict:
    return yaml.safe_load(
        (STANDARDS / "timeSteps.yaml").read_text(encoding="utf-8")
    )


def test_write_config_file_happy_path(ctx):
    result = WRITE_CONFIG_FILE.handler(ctx, {
        "spec_name": "timeSteps",
        "data": _timesteps_data(),
    })
    assert result.get("ok"), result
    rel = result["path"]
    assert rel in ctx.rendered
    assert (ctx.generated_dir / rel).is_file()
    assert ctx.rendered[rel].model is not None  # retained for semantic pass
    assert "XSD" in result["xsd"]


def test_write_config_file_overwrite_flagged(ctx):
    data = _timesteps_data()
    WRITE_CONFIG_FILE.handler(ctx, {"spec_name": "timeSteps", "data": data})
    again = WRITE_CONFIG_FILE.handler(ctx, {"spec_name": "timeSteps",
                                            "data": data})
    assert again.get("ok") and again.get("overwrote") is True


def test_write_config_file_bad_data_returns_error(ctx):
    result = WRITE_CONFIG_FILE.handler(ctx, {
        "spec_name": "timeSteps",
        "data": {"timeStep": [{"definitely_not_a_field": 1}]},
    })
    assert "error" in result
    assert not ctx.rendered  # nothing stored on failure


def test_write_config_file_unknown_spec(ctx):
    result = WRITE_CONFIG_FILE.handler(ctx, {"spec_name": "nope", "data": {}})
    assert "unknown spec" in result["error"]


def test_output_path_escape_rejected(ctx):
    result = WRITE_CONFIG_FILE.handler(ctx, {
        "spec_name": "timeSteps",
        "data": _timesteps_data(),
        "output_path": "../outside.xml",
    })
    assert "error" in result
    assert not ctx.rendered


def test_safe_relpath():
    assert safe_relpath("Config/A.xml") == "Config/A.xml"
    assert safe_relpath("Config\\B.xml") == "Config/B.xml"
    assert safe_relpath("../x.xml") is None
    assert safe_relpath("a/../../x.xml") is None
    assert safe_relpath("C:/abs.xml") is None
    assert safe_relpath("/abs.xml") is None


def test_floats_to_decimal_recursive():
    out = _floats_to_decimal({"a": 0.25, "b": [1.5, {"c": 2}], "d": "x"})
    assert str(out["a"]) == "0.25"
    assert str(out["b"][0]) == "1.5"
    assert out["b"][1]["c"] == 2
    assert out["d"] == "x"


def test_read_and_list(ctx):
    WRITE_CONFIG_FILE.handler(ctx, {"spec_name": "timeSteps",
                                    "data": _timesteps_data()})
    (ctx.inputs_dir / "locations.csv").write_text("id,name\n", encoding="utf-8")
    listing = LIST_PROJECT_FILES.handler(ctx, {})
    assert len(listing["generated"]) == 1
    assert listing["inputs"] == ["locations.csv"]
    rel = listing["generated"][0]["path"]
    read = READ_PROJECT_FILE.handler(ctx, {"path": rel})
    assert read["content"].startswith("<?xml")
    missing = READ_PROJECT_FILE.handler(ctx, {"path": "nope.xml"})
    assert "error" in missing


def test_list_and_describe_specs(ctx):
    listing = LIST_SPECS.handler(ctx, {"filter": "timeSteps"})
    rows = listing["specs"].splitlines()
    assert any(r.startswith("timeSteps ") for r in rows)
    assert listing["count"] == len(rows)
    described = DESCRIBE_SPEC.handler(ctx, {"spec_name": "timeSteps"})
    assert "schema" in described or "properties" in described
    unknown = DESCRIBE_SPEC.handler(ctx, {"spec_name": "zzz"})
    assert "error" in unknown


def test_validate_project_clean_after_write(ctx):
    WRITE_CONFIG_FILE.handler(ctx, {"spec_name": "timeSteps",
                                    "data": _timesteps_data()})
    report = VALIDATE_PROJECT.handler(ctx, {})
    assert report["files"] == 1
    assert report["xsd_failures"] == []
