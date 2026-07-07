"""Derive a stub LocationSets.xml from rendered XML references.

Phase (a) deterministic deriver. Real location sets need a CSV or
shapefile backing them — the agent can't invent that data. But the
project's rendered XMLs already declare which locationSet IDs are
referenced (workflows, displayGroups, filters use ``<locationSetId>``).

The deriver emits one ``<locationSet id="X"/>`` stub per unique non-
placeholder reference. The result XSD-validates and serves as a
checklist for the configurator: each stub is a set they need to
back with real data (csvFile/esriShapeFile/locationId list).

**Interpolation station sets are the exception (Slice B).** When a
spatial-interpolation module (``Interpolate<nwp>ToStations``, emitted by
``wf_interpolate_nwp_to_stations``) writes its output to a locationSet,
that set *is* the configurator's station list — already provided as
``locations.csv`` and rendered into ``Locations.xml``. For those sets we
emit explicit ``<locationId>`` membership listing every location, so the
interpolation has real targets instead of an empty stub the configurator
has to back by hand. Other referenced sets stay stubs.

When the configurator provides their own ``locationSetsFile.yaml``, the
deriver doesn't fire — input wins.
"""
from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

from lxml import etree

if TYPE_CHECKING:
    from .blueprint import RenderedFile


_PLACEHOLDER_RE = re.compile(r"\$[A-Z0-9_]+\$")

# Workflow `<string key="..." value="..."/>` properties whose value is
# always a locationSet id. The interpolation workflow binds the
# postprocess template's `$STATIONLOCATIONS$` placeholder via this key,
# so the value must declare a real set even though no `<locationSetId>`
# element carries the literal id directly.
_LOCSET_PROPERTY_KEYS: frozenset[str] = frozenset({"STATIONLOCATIONS"})


def _is_placeholder(value: str) -> bool:
    return bool(_PLACEHOLDER_RE.search(value or ""))


def _collect_referenced_set_ids(
    rendered_files: list["RenderedFile"],
) -> set[str]:
    ids: set[str] = set()
    for rf in rendered_files:
        try:
            tree = etree.fromstring(rf.content.encode("utf-8"))
        except etree.XMLSyntaxError:
            continue
        for el in tree.iter("{*}locationSetId"):
            text = (el.text or "").strip()
            if text and not _is_placeholder(text):
                ids.add(text)
        for el in tree.iter("{*}string"):
            key = el.get("key", "")
            value = (el.get("value") or "").strip()
            if (
                key in _LOCSET_PROPERTY_KEYS
                and value
                and not _is_placeholder(value)
            ):
                ids.add(value)
    return ids


def _collect_interpolation_target_set_ids(
    rendered_files: list["RenderedFile"],
) -> set[str]:
    """Find locationSet ids that a spatial-interpolation module writes to.

    A ``wf_interpolate_nwp_to_stations`` transformation module reads a
    grid (valueType=grid, locationId) and writes interpolated point
    series (valueType=scalar, locationSetId). The scalar-output set is
    the interpolation's station targets. We only look inside modules that
    actually carry an ``<interpolationSpatial>`` transform, so unrelated
    scalar locationSet references elsewhere aren't swept in.
    """
    ids: set[str] = set()
    for rf in rendered_files:
        try:
            tree = etree.fromstring(rf.content.encode("utf-8"))
        except etree.XMLSyntaxError:
            continue
        if tree.find(".//{*}interpolationSpatial") is None:
            continue
        for tss in tree.iter("{*}timeSeriesSet"):
            value_type = tss.find("{*}valueType")
            locset = tss.find("{*}locationSetId")
            if (
                value_type is not None
                and (value_type.text or "").strip() == "scalar"
                and locset is not None
            ):
                text = (locset.text or "").strip()
                if text and not _is_placeholder(text):
                    ids.add(text)
    return ids


def _collect_location_ids(
    rendered_files: list["RenderedFile"],
) -> list[str]:
    """Pull the ordered list of location ids from rendered ``Locations.xml``.

    These come from the configurator's ``locations.csv`` via CSV ingest.
    Order is preserved (CSV row order) so the emitted membership is
    deterministic.
    """
    ids: list[str] = []
    seen: set[str] = set()
    for rf in rendered_files:
        if not rf.relpath.replace("\\", "/").endswith("Locations.xml"):
            continue
        try:
            tree = etree.fromstring(rf.content.encode("utf-8"))
        except etree.XMLSyntaxError:
            continue
        for loc in tree.iter("{*}location"):
            lid = (loc.get("id") or "").strip()
            if lid and lid not in seen:
                seen.add(lid)
                ids.append(lid)
    return ids


def unbacked_interpolation_station_sets(
    rendered_files: list["RenderedFile"],
) -> set[str]:
    """Interpolation target sets left as id-only stubs in LocationSets.xml.

    An interpolation module writes its output to a locationSet; that set
    needs real backing (membership / csvFile / shapefile) or the
    interpolation produces no point time series. This returns the station
    target ids that are referenced but appear in the final
    ``LocationSets.xml`` with no child elements — typically because no
    ``locations.csv`` was provided. Empty result means every
    interpolation set is backed (or there's no interpolation at all).

    The build runner uses this to fail loudly rather than ship an
    interpolation that silently resolves to nothing.
    """
    station_ids = _collect_interpolation_target_set_ids(rendered_files)
    if not station_ids:
        return set()
    backed: set[str] = set()
    for rf in rendered_files:
        if not rf.relpath.replace("\\", "/").endswith("LocationSets.xml"):
            continue
        try:
            tree = etree.fromstring(rf.content.encode("utf-8"))
        except etree.XMLSyntaxError:
            continue
        for ls in tree.iter("{*}locationSet"):
            sid = (ls.get("id") or "").strip()
            # Backed iff the set carries at least one child element
            # (locationId / csvFile / esriShapeFile / ...). A bare
            # ``<locationSet id="X"/>`` stub has none.
            if sid and len(ls) > 0:
                backed.add(sid)
    return station_ids - backed


# CSV header (lowercased) → the reserved ``<csvFile>`` child element it
# maps to. Everything NOT in this map, and not ``datum`` (which lifts to
# the set-level ``<geoDatum>``), becomes a location ``<attribute>`` — this
# is the FEWS-Conform convention: the CSV column header *is* the
# attributeId. Order of the values here is the XSD ``<csvFile>`` sequence
# order, so the rendered dict stays schema-valid.
_CSVFILE_CORE: dict[str, str] = {
    "fewsid": "id",
    "id": "id",
    "locationid": "id",
    "name": "name",
    "shortname": "shortName",
    "tooltip": "toolTip",
    "lon": "x",
    "x": "x",
    "longitude": "x",
    "lat": "y",
    "y": "y",
    "latitude": "y",
    "alt": "z",
    "z": "z",
    "altitude": "z",
    "elevation": "z",
}

# Rendered order of the reserved ``<csvFile>`` children (XSD sequence).
_CSVFILE_ELEMENT_ORDER = ["id", "name", "shortName", "toolTip", "x", "y", "z"]


def locationset_csvfile_body(
    csv_filename: str,
    headers: list[str],
    *,
    set_id: str,
    geo_datum: str = "WGS 1984",
) -> dict[str, Any]:
    """Build one ``<locationSet><csvFile>`` body dict from a CSV's headers.

    This is the FEWS-Conform location convention: rather than materialising
    the CSV into ``Locations.xml``, reference it in place from a
    ``LocationSet`` and let FEWS read it at runtime. Reserved columns
    (id/name/x/y/z/...) map to the ``<csvFile>`` child elements via
    ``%Header%`` placeholders; every other column is promoted to a
    ``<attribute id="Header"><text>%Header%</text></attribute>`` — so the
    ``Type`` / ``ModelId`` / ``WflowIdDischarge`` columns that plain
    ingest drops are preserved as location attributes.

    ``datum`` (case-insensitive), if present, is not emitted per-column —
    the caller-supplied ``geo_datum`` carries the set-level ``<geoDatum>``.
    A header that maps to a reserved element already claimed by an earlier
    column is treated as an attribute (first-wins, mirroring the ingest
    de-dup rule).
    """
    core: dict[str, str] = {}
    attributes: list[dict[str, Any]] = []
    for h in headers:
        key = h.strip().lower()
        if not key or key == "datum":
            continue
        target = _CSVFILE_CORE.get(key)
        if target is not None and target not in core:
            core[target] = f"%{h}%"
        else:
            # Unrecognised column (or a duplicate reserved column) → the
            # Conform attribute convention: header becomes the attributeId.
            attributes.append({"@id": h, "text": f"%{h}%"})

    csv_file: dict[str, Any] = {"file": csv_filename, "geoDatum": geo_datum}
    for element in _CSVFILE_ELEMENT_ORDER:
        if element in core:
            csv_file[element] = core[element]
    if attributes:
        csv_file["attribute"] = attributes

    return {"locationSet": {"@id": set_id, "csvFile": csv_file}}


def derive_locationsets_yaml(
    rendered_files: list["RenderedFile"],
    extra_sets: list[dict[str, Any]] | None = None,
) -> dict[str, Any] | None:
    """Build a LocationSets yaml from rendered locationSetId references.

    Most entries are id-only stubs — placeholders the configurator backs
    with csvFile/esriShapeFile. The exception is interpolation station
    sets (see module docstring): when ``Locations.xml`` is present, those
    get explicit ``<locationId>`` membership so the interpolation resolves
    against real targets.

    ``extra_sets`` are pre-built ``{"locationSet": {...}}`` bodies (e.g.
    the csvFile-backed sets from ``locationset_csvfile_body``) that take
    precedence over an auto-stub of the same id — a real csvFile backing
    always beats a bare stub. Returns ``None`` only if there are neither
    references nor extra sets.
    """
    ids = _collect_referenced_set_ids(rendered_files)
    extra_sets = extra_sets or []
    extra_ids = {
        e["locationSet"]["@id"]
        for e in extra_sets
        if e.get("locationSet", {}).get("@id")
    }
    if not ids and not extra_sets:
        return None
    station_set_ids = _collect_interpolation_target_set_ids(rendered_files)
    location_ids = _collect_location_ids(rendered_files)

    body: list[dict[str, Any]] = list(extra_sets)
    for sid in sorted(ids):
        if sid in extra_ids:
            continue  # a csvFile-backed set already declares this id
        if sid in station_set_ids and location_ids:
            body.append({
                "locationSet": {
                    "@id": sid,
                    "locationId": list(location_ids),
                }
            })
        else:
            body.append({"locationSet": {"@id": sid}})
    return {"body": body}


__all__ = [
    "derive_locationsets_yaml",
    "locationset_csvfile_body",
    "unbacked_interpolation_station_sets",
]
