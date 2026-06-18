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


def derive_locationsets_yaml(
    rendered_files: list["RenderedFile"],
) -> dict[str, Any] | None:
    """Build a LocationSets yaml from rendered locationSetId references.

    Most entries are id-only stubs — placeholders the configurator backs
    with csvFile/esriShapeFile. The exception is interpolation station
    sets (see module docstring): when ``Locations.xml`` is present, those
    get explicit ``<locationId>`` membership so the interpolation resolves
    against real targets. Returns ``None`` if no references were found.
    """
    ids = _collect_referenced_set_ids(rendered_files)
    if not ids:
        return None
    station_set_ids = _collect_interpolation_target_set_ids(rendered_files)
    location_ids = _collect_location_ids(rendered_files)

    body: list[dict[str, Any]] = []
    for sid in sorted(ids):
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
    "unbacked_interpolation_station_sets",
]
