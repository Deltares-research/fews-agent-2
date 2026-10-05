"""Token-trim behaviours: schema noise stripping, compact encoding,
station limit/rounding."""
from __future__ import annotations

import json

import httpx

from fews_agent.agent.providers.base import ToolCall, ToolSpec
from fews_agent.react.registry import Tool, ToolRegistry
from fews_agent.react.tools.specs_tools import (
    DESCRIBE_SPEC,
    strip_schema_noise,
)
from fews_agent.react.tools.web_tools import SEARCH_STATIONS


def test_strip_schema_noise_removes_annotations():
    schema = {
        "title": "Workflow",
        "type": "object",
        "properties": {
            "activity": {"title": "Activity", "type": "array",
                         "items": {"$ref": "#/$defs/Activity"}},
            # A FEWS field literally named "title" must survive.
            "title": {"title": "Title", "type": "string",
                      "default": None},
        },
        "$defs": {
            "Activity": {"title": "Activity", "type": "object",
                         "properties": {}},
        },
    }
    out = strip_schema_noise(schema)
    assert "title" not in out  # root annotation gone
    assert "title" in out["properties"]  # the FIELD named title kept
    assert "title" not in out["properties"]["title"]  # its annotation gone
    assert "default" not in out["properties"]["title"]  # null default gone
    assert "title" not in out["properties"]["activity"]
    assert "Activity" in out["$defs"]
    assert "title" not in out["$defs"]["Activity"]


def test_describe_spec_schema_is_stripped_and_smaller(ctx):
    from fews_agent.agent.blueprint import schema_class_for
    raw = json.dumps(
        schema_class_for("Workflow").model_json_schema(),
        separators=(",", ":"))
    described = DESCRIBE_SPEC.handler(ctx, {"schema": "Workflow"})
    body = described.get("schema") or described.get("properties")
    stripped = json.dumps(body, separators=(",", ":"))
    assert '"title":"' not in stripped
    assert len(stripped) < len(raw) * 0.85


def test_registry_encodes_compact(ctx):
    reg = ToolRegistry([Tool(
        spec=ToolSpec(name="echo", description="echo",
                      input_schema={"type": "object", "properties": {}}),
        handler=lambda c, a: {"a": 1, "b": [1, 2]},
    )])
    result = reg.dispatch(ctx, ToolCall(id="c1", name="echo",
                                        arguments={}))
    assert result.content == '{"a":1,"b":[1,2]}'


def test_search_stations_limit_and_rounding(ctx, monkeypatch):
    from fews_agent.react.tools import web_tools

    overpass = {"elements": [
        {"id": i, "lat": 5.123456789, "lon": -0.987654321,
         "tags": {"name": f"S{i}", "waterway": "gauge"}}
        for i in range(10)
    ]}
    captured = {}

    def fn(request: httpx.Request) -> httpx.Response:
        captured["body"] = request.read().decode()
        return httpx.Response(200, json=overpass)

    monkeypatch.setattr(web_tools, "_transport", httpx.MockTransport(fn))
    result = SEARCH_STATIONS.handler(ctx, {"bbox": [4, -2, 6, 1],
                                           "limit": 3})
    assert "out body 3" in captured["body"].replace("+", " ")
    assert result["count"] == 3
    assert result["stations"][0]["lat"] == 5.12346  # 5 decimals
    assert result["stations"][0]["lon"] == -0.98765
