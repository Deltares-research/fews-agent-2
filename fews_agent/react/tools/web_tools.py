"""Web lookup tools: OSM station discovery + FEWS public wiki.

`search_stations` resolves a region name to a bbox (Nominatim) and
queries the Overpass API for hydrometric assets — this is how the agent
self-discovers stations instead of demanding a CSV. `fews_wiki_lookup`
searches/fetches publicwiki.deltares.nl (Confluence).

Both fail LOUDLY as `{"error": ...}` tool results — the model decides
whether to retry narrower, use another kind, or fall back to its own
knowledge of major stations/cities (and say so in its report).

Tests inject `httpx.MockTransport` via the module-level `_transport`.
"""
from __future__ import annotations

from typing import Any

import httpx
from lxml import html as lxml_html

from fews_agent.agent.providers.base import ToolSpec

from ..context import ToolContext
from ..registry import Tool

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
OVERPASS_URLS = (
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
)
WIKI_BASE = "https://publicwiki.deltares.nl"

USER_AGENT = "fews-agent/0.1 (Delft-FEWS configuration agent; research)"

MAX_STATIONS = 200
DEFAULT_STATIONS = 50
MAX_PAGE_CHARS = 8_000

# kind -> Overpass node selector
_KIND_SELECTORS = {
    "monitoring_station": '["man_made"="monitoring_station"]',
    "water_level": '["monitoring:water_level"="yes"]',
    "gauge": '["waterway"="gauge"]',
    "weather_station": '["man_made"="monitoring_station"]'
                       '["monitoring:weather"="yes"]',
}

# Test seam: set to an httpx.BaseTransport to intercept all requests.
_transport: httpx.BaseTransport | None = None


def _client(ctx: ToolContext) -> httpx.Client:
    return httpx.Client(
        transport=_transport,
        timeout=ctx.http_timeout,
        headers={"User-Agent": USER_AGENT},
        follow_redirects=True,
    )


def _resolve_region_bbox(client: httpx.Client,
                         region: str) -> list[float] | dict[str, str]:
    resp = client.get(NOMINATIM_URL,
                      params={"q": region, "format": "json", "limit": 1})
    resp.raise_for_status()
    hits = resp.json()
    if not hits:
        return {"error": f"Nominatim found no region named {region!r} — "
                         "pass an explicit bbox [south, west, north, east]"}
    south, north, west, east = (float(v) for v in hits[0]["boundingbox"])
    return [south, west, north, east]


def _overpass_query(bbox: list[float], kinds: list[str],
                    limit: int) -> str:
    s, w, n, e = bbox
    selectors = [_KIND_SELECTORS[k] for k in kinds]
    lines = "".join(f"node{sel}({s},{w},{n},{e});" for sel in selectors)
    return f"[out:json][timeout:25];({lines});out body {limit};"


def _search_stations(ctx: ToolContext, args: dict[str, Any]) -> Any:
    bbox = args.get("bbox")
    region = args.get("region")
    if not bbox and not region:
        return {"error": "pass bbox [south, west, north, east] or a "
                         "region name"}
    kinds = args.get("kinds") or ["monitoring_station", "water_level",
                                  "gauge"]
    try:
        limit = min(MAX_STATIONS, max(1, int(args.get("limit")
                                             or DEFAULT_STATIONS)))
    except (TypeError, ValueError):
        limit = DEFAULT_STATIONS
    unknown = [k for k in kinds if k not in _KIND_SELECTORS]
    if unknown:
        return {"error": f"unknown kinds {unknown}; "
                         f"valid: {sorted(_KIND_SELECTORS)}"}
    with _client(ctx) as client:
        if not bbox:
            resolved = _resolve_region_bbox(client, str(region))
            if isinstance(resolved, dict):
                return resolved
            bbox = resolved
        if not (isinstance(bbox, list) and len(bbox) == 4):
            return {"error": "bbox must be [south, west, north, east]"}
        bbox = [float(v) for v in bbox]
        query = _overpass_query(bbox, kinds, limit)
        last_error = ""
        for url in OVERPASS_URLS:
            try:
                resp = client.post(url, data={"data": query})
                resp.raise_for_status()
                elements = resp.json().get("elements", [])
                break
            except Exception as exc:  # noqa: BLE001 — try the mirror
                last_error = f"{type(exc).__name__}: {exc}"
        else:
            return {"error": f"Overpass unavailable ({last_error}); "
                             "retry with a smaller bbox or fewer kinds, "
                             "or fall back to your own knowledge of major "
                             "stations and say so"}
    stations = []
    for el in elements[:limit]:
        tags = el.get("tags", {})
        kind = (tags.get("waterway") or tags.get("man_made")
                or "monitoring_station")
        # 5 decimals ~ 1 m — plenty for station placement, and shorter
        # coordinates keep the result (re-sent every iteration) small.
        stations.append({
            "id": f"osm_{el.get('id')}",
            "name": tags.get("name") or f"Station {el.get('id')}",
            "lat": round(float(el.get("lat", 0.0)), 5),
            "lon": round(float(el.get("lon", 0.0)), 5),
            "kind": kind,
        })
    return {"bbox": bbox, "count": len(stations), "stations": stations,
            "note": ("empty result means OSM has no tagged hydrometric "
                     "assets there — widen the bbox, try other kinds, or "
                     "use your own knowledge of major stations/cities"
                     if not stations else "")}


def _fews_wiki_lookup(ctx: ToolContext, args: dict[str, Any]) -> Any:
    query = args.get("query")
    url = args.get("url")
    if not query and not url:
        return {"error": "pass query (search) or url (fetch one page)"}
    with _client(ctx) as client:
        if url:
            target = str(url)
            if not target.startswith(WIKI_BASE):
                return {"error": f"url must start with {WIKI_BASE}"}
            resp = client.get(target)
            resp.raise_for_status()
            doc = lxml_html.fromstring(resp.text)
            main = doc.get_element_by_id("main-content", None)
            node = main if main is not None else doc
            text = " ".join(node.text_content().split())
            out: dict[str, Any] = {"url": target,
                                   "text": text[:MAX_PAGE_CHARS]}
            if len(text) > MAX_PAGE_CHARS:
                out["truncated_chars"] = len(text) - MAX_PAGE_CHARS
            return out
        resp = client.get(
            f"{WIKI_BASE}/rest/api/content/search",
            params={"cql": f'siteSearch ~ "{query}"', "limit": 5},
        )
        resp.raise_for_status()
        results = resp.json().get("results", [])
        hits = []
        for r in results:
            webui = (r.get("_links", {}) or {}).get("webui", "")
            hits.append({"title": r.get("title", ""),
                         "url": f"{WIKI_BASE}{webui}" if webui else ""})
        return {"query": query, "hits": hits}


SEARCH_STATIONS = Tool(
    spec=ToolSpec(
        name="search_stations",
        description=(
            "Discover hydrometric assets from OpenStreetMap: monitoring "
            "stations, water-level sites, river gauges inside a bbox or "
            "a named region. Returns rows ready for write_input_csv "
            "(locations.csv). An empty result is normal in sparsely "
            "tagged regions — then fall back to your own knowledge of "
            "major stations/ports/cities and say so in your report."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "bbox": {
                    "type": "array",
                    "items": {"type": "number"},
                    "minItems": 4, "maxItems": 4,
                    "description": "[south, west, north, east] degrees",
                },
                "region": {"type": "string",
                           "description": "named region/area, resolved "
                                          "via geocoding when bbox absent"},
                "kinds": {
                    "type": "array",
                    "items": {"type": "string",
                              "enum": sorted(_KIND_SELECTORS)},
                },
                "limit": {
                    "type": "integer",
                    "description": f"max stations returned (default "
                                   f"{DEFAULT_STATIONS}, cap "
                                   f"{MAX_STATIONS}) — ask only for "
                                   f"what you will actually use",
                },
            },
            "additionalProperties": False,
        },
    ),
    handler=_search_stations,
)

FEWS_WIKI_LOOKUP = Tool(
    spec=ToolSpec(
        name="fews_wiki_lookup",
        description=(
            "Search the public Delft-FEWS documentation wiki "
            "(publicwiki.deltares.nl) or fetch one page's text. Use it "
            "to check FEWS config element semantics you are unsure "
            "about (import types, display options, module behaviour)."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "url": {"type": "string"},
            },
            "additionalProperties": False,
        },
    ),
    handler=_fews_wiki_lookup,
)
