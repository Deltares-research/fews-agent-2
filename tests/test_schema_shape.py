"""schema_shape — pinned grammar, loud on unknown spec."""
from __future__ import annotations

import pytest

from fews_agent.validation.schema_shape import schema_shape
from fews_agent.validation.toolbelt import tool_schema_shape


def test_time_series_import_run_shape():
    shape = schema_shape("TimeSeriesImportRun")
    assert shape["name"] == "TimeSeriesImportRun"
    assert "import" in shape["required"] or "import_" in str(shape["json_schema"])
    assert shape["xsd_rel"] == "timeSeriesImportRun.xsd"
    assert isinstance(shape["enums"], dict)
    assert shape["xsd_fragment"]
    assert "timeSeriesImportRun" in shape["xsd_fragment"]


def test_unknown_spec_fails_loud():
    with pytest.raises(KeyError):
        schema_shape("NotARealSpec")


def test_tool_unknown_spec_returns_error_payload():
    out = tool_schema_shape("Nope")
    assert "error" in out
    assert out["known_specs_sample"]
