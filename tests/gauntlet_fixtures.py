"""Shared XML snippets for gauntlet / conform / toolbelt tests."""
from __future__ import annotations

from pathlib import Path

NS = (
    'xmlns="http://www.wldelft.nl/fews" '
    'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"'
)

IMPORT_XML = f"""\
<?xml version="1.0" encoding="UTF-8"?>
<timeSeriesImportRun {NS} xsi:schemaLocation="http://www.wldelft.nl/fews http://fews.wldelft.nl/schemas/version1.0/timeSeriesImportRun.xsd">
  <import>
    <general>
      <importType>NETCDF-CF_GRID</importType>
      <folder>$REGION_HOME$/Import/GFS</folder>
      <idMapId>IdImportGFS</idMapId>
    </general>
    <timeSeriesSet>
      <moduleInstanceId>ImportGFS</moduleInstanceId>
      <valueType>grid</valueType>
      <parameterId>PC.nwp</parameterId>
      <locationId>GFS</locationId>
      <timeSeriesType>external forecasting</timeSeriesType>
      <timeStep unit="hour" multiplier="3"/>
      <readWriteMode>add originals</readWriteMode>
    </timeSeriesSet>
  </import>
</timeSeriesImportRun>
"""

# Same import but the GlobSnow casing bug: ref does not match file stem.
IMPORT_GLOB_XML = IMPORT_XML.replace(
    "IdImportGFS", "IdImportGlobSnow",
).replace("ImportGFS", "ImportGLOBSNOW").replace("GFS", "GLOBSNOW")

IDMAP_XML = f"""\
<?xml version="1.0" encoding="UTF-8"?>
<idMap version="1.1" {NS} xsi:schemaLocation="http://www.wldelft.nl/fews http://fews.wldelft.nl/schemas/version1.0/idMap.xsd">
  <parameter internal="PC.nwp" external="apcpsfc"/>
</idMap>
"""

PARAMETERS_XML = f"""\
<?xml version="1.0" encoding="UTF-8"?>
<parameterGroups version="1.0" {NS} xsi:schemaLocation="http://www.wldelft.nl/fews http://fews.wldelft.nl/schemas/version1.0/parameters.xsd">
  <parameterGroup id="Precipitation">
    <parameterType>instantaneous</parameterType>
    <unit>mm</unit>
    <parameter id="PC.nwp">
      <shortName>Precip NWP</shortName>
    </parameter>
    <parameter id="not a valid id">
      <shortName>Bad</shortName>
    </parameter>
  </parameterGroup>
</parameterGroups>
"""

FILTERS_MISNAMED_XML = f"""\
<?xml version="1.0" encoding="UTF-8"?>
<filters {NS} xsi:schemaLocation="http://www.wldelft.nl/fews http://fews.wldelft.nl/schemas/version1.0/filters.xsd" id="AllData">
  <filter id="AllData" name="All">
    <timeSeriesSet>
      <moduleInstanceId>ImportGFS</moduleInstanceId>
      <valueType>scalar</valueType>
      <parameterId>PC.nwp</parameterId>
      <locationSetId>AllLocations</locationSetId>
      <timeSeriesType>external forecasting</timeSeriesType>
      <timeStep unit="nonequidistant"/>
      <readWriteMode>read complete forecast</readWriteMode>
    </timeSeriesSet>
  </filter>
</filters>
"""

BROKEN_XML = f"""\
<?xml version="1.0" encoding="UTF-8"?>
<timeSeriesImportRun {NS} xsi:schemaLocation="http://www.wldelft.nl/fews http://fews.wldelft.nl/schemas/version1.0/timeSeriesImportRun.xsd">
  <notARealChild/>
</timeSeriesImportRun>
"""


def write_mini_config(root: Path, *, glob_casing: bool = True) -> Path:
    """Write a tiny FEWS-shaped tree used by unit tests."""
    (root / "ModuleConfigFiles" / "Import").mkdir(parents=True)
    (root / "IdMapFiles").mkdir(parents=True)
    (root / "RegionConfigFiles").mkdir(parents=True)
    if glob_casing:
        (root / "ModuleConfigFiles" / "Import" / "ImportGLOBSNOW.xml").write_text(
            IMPORT_GLOB_XML, encoding="utf-8",
        )
        (root / "IdMapFiles" / "IdImportGLOBSNOW.xml").write_text(
            IDMAP_XML, encoding="utf-8",
        )
    else:
        (root / "ModuleConfigFiles" / "Import" / "ImportGFS.xml").write_text(
            IMPORT_XML, encoding="utf-8",
        )
        (root / "IdMapFiles" / "IdImportGFS.xml").write_text(
            IDMAP_XML, encoding="utf-8",
        )
    (root / "RegionConfigFiles" / "Parameters.xml").write_text(
        PARAMETERS_XML, encoding="utf-8",
    )
    # Root @id AllData vs filename Filters.xml
    (root / "RegionConfigFiles" / "Filters.xml").write_text(
        FILTERS_MISNAMED_XML, encoding="utf-8",
    )
    (root / "locations.csv").write_text(
        "FewsId,Name,Lat,Lon,wflow_id\nL1,Gauge,1,2,42\n",
        encoding="utf-8",
    )
    return root
