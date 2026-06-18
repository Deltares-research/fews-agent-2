"""Slice B tests: populate interpolation station LocationSets from CSV.

``locationsets_derivation.derive_locationsets_yaml`` normally emits id-only
stubs. The exception is a locationSet that a spatial-interpolation module
(``wf_interpolate_nwp_to_stations``) writes its scalar output to: that set
*is* the configurator's station list (from ``locations.csv`` →
``Locations.xml``), so the deriver fills it with explicit ``<locationId>``
membership instead of a bare stub.
"""
from __future__ import annotations

from fews_agent.agent.blueprint import RenderedFile
from fews_agent.agent.locationsets_derivation import derive_locationsets_yaml
from fews_agent.generators.base import render as render_template
from fews_agent.schema import LocationSets
from fews_agent.validation.xsd import validate_xsd


# An interpolation module: grid input (valueType=grid, locationId) +
# scalar output written to a locationSet (the station targets).
_INTERP_MODULE = """<?xml version="1.0" encoding="UTF-8"?>
<transformationModule xmlns="http://www.wldelft.nl/fews" version="1.0">
  <variable>
    <variableId>Grid_PC_nwp</variableId>
    <timeSeriesSet>
      <moduleInstanceId>ImportGFS</moduleInstanceId>
      <valueType>grid</valueType>
      <parameterId>PC.nwp</parameterId>
      <locationId>GFS</locationId>
      <timeSeriesType>external forecasting</timeSeriesType>
      <timeStep unit="hour" multiplier="3"/>
      <readWriteMode>read complete forecast</readWriteMode>
    </timeSeriesSet>
  </variable>
  <variable>
    <variableId>Station_PC_nwp</variableId>
    <timeSeriesSet>
      <moduleInstanceId>InterpolateGFSToStations</moduleInstanceId>
      <valueType>scalar</valueType>
      <parameterId>PC.nwp</parameterId>
      <locationSetId>InterpolationStations</locationSetId>
      <timeSeriesType>external forecasting</timeSeriesType>
      <timeStep unit="hour" multiplier="3"/>
      <readWriteMode>add originals</readWriteMode>
    </timeSeriesSet>
  </variable>
  <transformation id="interpolate_PC_nwp">
    <interpolationSpatial>
      <closestDistance>
        <inputVariable><variableId>Grid_PC_nwp</variableId></inputVariable>
        <distanceGeoDatum>WGS 1984</distanceGeoDatum>
        <outputVariable><variableId>Station_PC_nwp</variableId></outputVariable>
      </closestDistance>
    </interpolationSpatial>
  </transformation>
</transformationModule>
"""

# A workflow that references some OTHER locationSet (a non-interpolation
# reference that must stay an id-only stub).
_OTHER_REF = """<?xml version="1.0" encoding="UTF-8"?>
<workflow xmlns="http://www.wldelft.nl/fews" version="1.1">
  <activity>
    <runIndependent>true</runIndependent>
    <activity>
      <moduleInstanceId>SomeOtherModule</moduleInstanceId>
    </activity>
  </activity>
</workflow>
"""

_LOCATIONS = """<?xml version="1.0" encoding="UTF-8"?>
<locations xmlns="http://www.wldelft.nl/fews" version="1.1">
  <geoDatum>WGS 1984</geoDatum>
  <location id="STN001"><x>2.0</x><y>5.0</y></location>
  <location id="STN002"><x>3.0</x><y>6.0</y></location>
  <location id="STN003"><x>4.0</x><y>7.0</y></location>
</locations>
"""

# A bare display ref to a non-station set, to assert stubs still happen.
_DISPLAY_REF = """<?xml version="1.0" encoding="UTF-8"?>
<gridDisplay xmlns="http://www.wldelft.nl/fews">
  <gridPlotGroup id="G">
    <gridPlot id="P">
      <timeSeriesSet>
        <moduleInstanceId>ImportGFS</moduleInstanceId>
        <valueType>scalar</valueType>
        <parameterId>PC.nwp</parameterId>
        <locationSetId>BasinOutlets</locationSetId>
        <timeSeriesType>external forecasting</timeSeriesType>
        <timeStep unit="hour" multiplier="3"/>
        <readWriteMode>read only</readWriteMode>
      </timeSeriesSet>
    </gridPlot>
  </gridPlotGroup>
</gridDisplay>
"""


def _rf(relpath, content):
    return RenderedFile(
        relpath=relpath, content=content,
        pattern="(test)", instance_label="t",
    )


def _files(with_locations=True, station_set="InterpolationStations"):
    module = _INTERP_MODULE.replace("InterpolationStations", station_set)
    files = [
        _rf("ModuleConfigFiles/Interpolate/InterpolateGFSToStations.xml", module),
        _rf("DisplayConfigFiles/GridDisplay_GFS.xml", _DISPLAY_REF),
    ]
    if with_locations:
        files.append(_rf("MapLayerFiles/Locations.xml", _LOCATIONS))
    return files


def _by_id(body):
    return {e["locationSet"]["@id"]: e["locationSet"] for e in body}


def test_station_set_populated_from_locations():
    data = derive_locationsets_yaml(_files())
    sets = _by_id(data["body"])
    assert sets["InterpolationStations"]["locationId"] == ["STN001", "STN002", "STN003"]


def test_non_interpolation_ref_stays_a_stub():
    data = derive_locationsets_yaml(_files())
    sets = _by_id(data["body"])
    assert "locationId" not in sets["BasinOutlets"]  # id-only stub


def test_without_locations_station_set_is_stub():
    data = derive_locationsets_yaml(_files(with_locations=False))
    sets = _by_id(data["body"])
    assert "locationId" not in sets["InterpolationStations"]


def test_station_set_id_matches_workflow_variable():
    # The populated id must be whatever the interpolation actually writes
    # to — not a hardcoded default.
    data = derive_locationsets_yaml(_files(station_set="GuineaStations"))
    sets = _by_id(data["body"])
    assert sets["GuineaStations"]["locationId"] == ["STN001", "STN002", "STN003"]
    assert "GuineaStations" in sets


def test_populated_locationsets_xsd_valid():
    data = derive_locationsets_yaml(_files())
    model = LocationSets.model_validate(data)
    xml = render_template("region/location_sets.xml.j2", model)
    ok, msg = validate_xsd(xml.encode("utf-8"))
    assert ok, msg
    # The membership really landed in the XML.
    assert "<locationId>STN001</locationId>" in xml
    assert "<locationId>STN003</locationId>" in xml


def test_returns_none_when_no_refs():
    files = [_rf("Locations.xml", _LOCATIONS)]  # locations but no set refs
    assert derive_locationsets_yaml(files) is None
