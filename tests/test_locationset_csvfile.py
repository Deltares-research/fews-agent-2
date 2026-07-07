"""FEWS-Conform csvFile LocationSet emitter (option b).

``locationset_csvfile_body`` turns a CSV's headers into a
``<locationSet><csvFile>`` body that references the CSV in place and
promotes every non-reserved column to a location ``<attribute>`` — the
Conform convention that plain ``Locations.xml`` ingest can't express.

These tests are the durable oracle: the ``projects/`` fixtures are
gitignored, so behaviour is pinned here and by an XSD round-trip through
the real template.
"""
from __future__ import annotations

from fews_agent.agent.locationsets_derivation import (
    derive_locationsets_yaml,
    locationset_csvfile_body,
    merge_csvfile_sets_into_locationsets,
)
from fews_agent.generators import SPECS
from fews_agent.generators.base import render as render_template
from fews_agent.validation.xsd import validate_xsd


CONFORM_HEADERS = [
    "FewsId", "Name", "ShortName", "Lat", "Lon", "Alt", "Datum",
    "Type", "ModelId", "WflowIdDischarge", "WflowIdWaterLevel",
]


def _csv_file(body: dict) -> dict:
    return body["locationSet"]["csvFile"]


def test_core_columns_map_to_reserved_elements():
    body = locationset_csvfile_body(
        "locations.csv", CONFORM_HEADERS, set_id="StationsWflow"
    )
    cf = _csv_file(body)
    assert body["locationSet"]["@id"] == "StationsWflow"
    assert cf["file"] == "locations.csv"
    assert cf["id"] == "%FewsId%"
    assert cf["name"] == "%Name%"
    assert cf["shortName"] == "%ShortName%"
    assert cf["x"] == "%Lon%"   # longitude → x
    assert cf["y"] == "%Lat%"   # latitude → y
    assert cf["z"] == "%Alt%"


def test_non_reserved_columns_become_attributes():
    body = locationset_csvfile_body(
        "locations.csv", CONFORM_HEADERS, set_id="StationsWflow"
    )
    attrs = {a["@id"]: a["text"] for a in _csv_file(body)["attribute"]}
    # The columns plain ingest drops are preserved verbatim as attributes.
    assert attrs == {
        "Type": "%Type%",
        "ModelId": "%ModelId%",
        "WflowIdDischarge": "%WflowIdDischarge%",
        "WflowIdWaterLevel": "%WflowIdWaterLevel%",
    }


def test_datum_column_lifts_to_geodatum_not_attribute():
    body = locationset_csvfile_body(
        "locations.csv", CONFORM_HEADERS, set_id="S", geo_datum="GDA94"
    )
    cf = _csv_file(body)
    assert cf["geoDatum"] == "GDA94"
    assert "Datum" not in {a["@id"] for a in cf.get("attribute", [])}


def test_duplicate_reserved_column_falls_through_to_attribute():
    # Two columns both claim x/id — first wins the reserved slot, the
    # second is preserved as an attribute (no silent loss).
    body = locationset_csvfile_body(
        "l.csv", ["Id", "LocationId", "Lat", "Lon"], set_id="S"
    )
    cf = _csv_file(body)
    assert cf["id"] == "%Id%"
    assert {a["@id"] for a in cf.get("attribute", [])} == {"LocationId"}


def test_no_attributes_omits_attribute_key():
    body = locationset_csvfile_body(
        "l.csv", ["FewsId", "Name", "Lat", "Lon"], set_id="S"
    )
    assert "attribute" not in _csv_file(body)


def test_renders_xsd_valid_through_real_template():
    body = locationset_csvfile_body(
        "locations.csv", CONFORM_HEADERS, set_id="StationsWflow"
    )
    spec = next(s for s in SPECS if s.name == "locationSetsFile")
    model = spec.model_class.model_validate(
        derive_locationsets_yaml([], extra_sets=[body])
    )
    xml = render_template(spec.template_name, model)
    ok, msg = validate_xsd(xml.encode("utf-8"))
    assert ok, msg
    # The Conform attribute survived the render round-trip.
    assert '<attribute id="WflowIdDischarge">' in xml
    assert "<z>%Alt%</z>" in xml


def test_deriver_merge_csvfile_set_beats_stub_of_same_id():
    # A referenced id that also has a csvFile backing must not also emit a
    # bare stub — the real backing wins, and there's exactly one entry.
    class _RF:
        def __init__(self, relpath, content):
            self.relpath = relpath
            self.content = content

    rendered = [_RF(
        "wf.xml",
        '<workflow xmlns="http://www.wldelft.nl/fews">'
        "<locationSetId>StationsWflow</locationSetId>"
        "<locationSetId>OtherSet</locationSetId></workflow>",
    )]
    body = locationset_csvfile_body(
        "locations.csv", CONFORM_HEADERS, set_id="StationsWflow"
    )
    data = derive_locationsets_yaml(rendered, extra_sets=[body])
    entries = data["body"]
    by_id = {e["locationSet"]["@id"]: e["locationSet"] for e in entries}
    assert len(entries) == 2                         # no duplicate StationsWflow
    assert "csvFile" in by_id["StationsWflow"]       # backed, not a stub
    assert by_id["OtherSet"] == {"@id": "OtherSet"}  # untouched referenced set stays a stub


# ---------------------------------------------------------------------------
# merge_csvfile_sets_into_locationsets — grafting into an existing file
# ---------------------------------------------------------------------------

_EXISTING = (
    '<?xml version="1.0" encoding="UTF-8"?>\n'
    '<locationSets xmlns="http://www.wldelft.nl/fews" version="1.1">'
    "<allowEmptyLocationSets>true</allowEmptyLocationSets>"
    '<locationSet id="Stations"/>'          # bare stub — csvFile should replace it
    '<locationSet id="ModelBasins"/>'       # unrelated — must survive untouched
    "</locationSets>"
)


def test_merge_replaces_stub_of_same_id_in_place():
    body = locationset_csvfile_body(
        "locations.csv", CONFORM_HEADERS, set_id="Stations"
    )
    merged = merge_csvfile_sets_into_locationsets(_EXISTING, [body])
    # csvFile backing replaced the stub; the unrelated set is preserved.
    assert '<locationSet id="Stations"><csvFile>' in merged
    assert '<locationSet id="ModelBasins"/>' in merged
    # No duplicate Stations, and position preserved (before ModelBasins).
    assert merged.count('id="Stations"') == 1
    assert merged.index('id="Stations"') < merged.index('id="ModelBasins"')
    # The attribute survived the graft.
    assert '<attribute id="WflowIdDischarge">' in merged


def test_merge_appends_new_id_and_keeps_default_namespace():
    body = locationset_csvfile_body(
        "locations.csv", CONFORM_HEADERS, set_id="NewStations"
    )
    merged = merge_csvfile_sets_into_locationsets(_EXISTING, [body])
    assert '<locationSet id="NewStations"><csvFile>' in merged
    assert '<locationSet id="Stations"/>' in merged      # existing stub untouched
    # Namespace stays default (no ns0: prefixing from lxml re-serialisation).
    assert "ns0:" not in merged
    assert 'xmlns="http://www.wldelft.nl/fews"' in merged


def test_merge_result_is_xsd_valid():
    body = locationset_csvfile_body(
        "locations.csv", CONFORM_HEADERS, set_id="Stations"
    )
    merged = merge_csvfile_sets_into_locationsets(_EXISTING, [body])
    ok, msg = validate_xsd(merged.encode("utf-8"))
    assert ok, msg
