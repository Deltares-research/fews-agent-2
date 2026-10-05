"""Web tools against httpx.MockTransport — no network."""
from __future__ import annotations

import json

import httpx
import pytest

from fews_agent.react.tools import web_tools
from fews_agent.react.tools.web_tools import (
    FEWS_WIKI_LOOKUP,
    SEARCH_STATIONS,
)

OVERPASS_JSON = {
    "elements": [
        {"id": 1, "lat": 5.55, "lon": -0.21,
         "tags": {"name": "Accra Gauge", "waterway": "gauge"}},
        {"id": 2, "lat": 4.89, "lon": -1.75,
         "tags": {"man_made": "monitoring_station"}},
    ]
}

NOMINATIM_JSON = [{"boundingbox": ["4.0", "6.0", "-2.0", "1.0"]}]


@pytest.fixture
def transport(monkeypatch):
    """Install a MockTransport; the test sets `handler.fn`."""
    class Holder:
        fn = None

    holder = Holder()

    def _dispatch(request: httpx.Request) -> httpx.Response:
        assert holder.fn is not None, "test forgot to set handler.fn"
        return holder.fn(request)

    monkeypatch.setattr(web_tools, "_transport",
                        httpx.MockTransport(_dispatch))
    return holder


def test_search_stations_bbox(ctx, transport):
    def fn(request):
        assert "overpass" in request.url.host
        return httpx.Response(200, json=OVERPASS_JSON)

    transport.fn = fn
    result = SEARCH_STATIONS.handler(ctx, {"bbox": [4.0, -2.0, 6.0, 1.0]})
    assert result["count"] == 2
    assert result["stations"][0] == {
        "id": "osm_1", "name": "Accra Gauge",
        "lat": 5.55, "lon": -0.21, "kind": "gauge",
    }
    assert result["stations"][1]["name"] == "Station 2"


def test_search_stations_region_resolves_bbox(ctx, transport):
    def fn(request):
        if request.url.host == "nominatim.openstreetmap.org":
            return httpx.Response(200, json=NOMINATIM_JSON)
        from urllib.parse import unquote_plus
        body = unquote_plus(request.read().decode())
        assert "4.0,-2.0,6.0,1.0" in body
        return httpx.Response(200, json=OVERPASS_JSON)

    transport.fn = fn
    result = SEARCH_STATIONS.handler(ctx, {"region": "Gulf of Guinea"})
    assert result["bbox"] == [4.0, -2.0, 6.0, 1.0]
    assert result["count"] == 2


def test_search_stations_unknown_region(ctx, transport):
    transport.fn = lambda request: httpx.Response(200, json=[])
    result = SEARCH_STATIONS.handler(ctx, {"region": "Atlantis"})
    assert "error" in result


def test_search_stations_mirror_fallback_then_error(ctx, transport):
    hosts = []

    def fn(request):
        hosts.append(request.url.host)
        return httpx.Response(504)

    transport.fn = fn
    result = SEARCH_STATIONS.handler(ctx, {"bbox": [4, -2, 6, 1]})
    assert "error" in result and "Overpass unavailable" in result["error"]
    assert len(set(hosts)) == 2  # both endpoints tried


def test_search_stations_rejects_unknown_kind(ctx, transport):
    result = SEARCH_STATIONS.handler(
        ctx, {"bbox": [4, -2, 6, 1], "kinds": ["volcano"]})
    assert "unknown kinds" in result["error"]


def test_wiki_search(ctx, transport):
    def fn(request):
        assert request.url.host == "publicwiki.deltares.nl"
        assert request.url.params["cql"] == 'siteSearch ~ "grid display"'
        return httpx.Response(200, json={"results": [
            {"title": "Grid Display",
             "_links": {"webui": "/display/FEWSDOC/Grid+Display"}},
        ]})

    transport.fn = fn
    result = FEWS_WIKI_LOOKUP.handler(ctx, {"query": "grid display"})
    assert result["hits"][0]["title"] == "Grid Display"
    assert result["hits"][0]["url"].startswith(
        "https://publicwiki.deltares.nl/display")


def test_wiki_page_fetch_strips_html(ctx, transport):
    page = ("<html><body><div id='main-content'><h1>Imports</h1>"
            "<p>Use timeSeriesImportRun.</p></div></body></html>")
    transport.fn = lambda request: httpx.Response(200, text=page)
    result = FEWS_WIKI_LOOKUP.handler(ctx, {
        "url": "https://publicwiki.deltares.nl/display/FEWSDOC/Imports"})
    assert "Use timeSeriesImportRun." in result["text"]
    assert "<p>" not in result["text"]


def test_wiki_rejects_foreign_url(ctx, transport):
    result = FEWS_WIKI_LOOKUP.handler(ctx, {"url": "https://evil.test/x"})
    assert "error" in result


def test_registry_dispatch_encodes_http_error(ctx, transport):
    # Through the registry, an unexpected exception becomes {"error"}.
    from fews_agent.agent.providers.base import ToolCall
    from fews_agent.react.registry import ToolRegistry

    def fn(request):
        raise httpx.ConnectTimeout("no route")

    transport.fn = fn
    reg = ToolRegistry([FEWS_WIKI_LOOKUP])
    result = reg.dispatch(ctx, ToolCall(
        id="c1", name="fews_wiki_lookup", arguments={"query": "x"}))
    assert "error" in json.loads(result.content)
