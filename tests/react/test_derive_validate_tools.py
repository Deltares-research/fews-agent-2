"""Schema-mode writes + generic writer + derivers + semantic validation,
exercised the way the agent would: a mini import config end-to-end."""
from __future__ import annotations

from fews_agent.react.tools.csv_tools import INGEST_CSVS, WRITE_INPUT_CSV
from fews_agent.react.tools.derive_tools import DERIVE
from fews_agent.react.tools.file_tools import (
    WRITE_CONFIG_FILE,
    WRITE_GENERIC_FILE,
)
from fews_agent.react.tools.validate_tools import VALIDATE_PROJECT

WORKFLOW_DATA = {
    "version": "1.1",
    "activity": [{"runIndependent": True, "moduleInstanceId": "ImportDemo"}],
}


def _write_workflow(ctx, stem: str = "ImportDemoGrids"):
    return WRITE_CONFIG_FILE.handler(ctx, {
        "schema": "Workflow",
        "data": WORKFLOW_DATA,
        "output_path": f"WorkflowFiles/Import/{stem}.xml",
    })


def test_write_by_schema_requires_output_path(ctx):
    missing = WRITE_CONFIG_FILE.handler(ctx, {
        "schema": "Workflow", "data": WORKFLOW_DATA,
    })
    assert "output_path is required" in missing["error"]
    both = WRITE_CONFIG_FILE.handler(ctx, {
        "schema": "Workflow", "spec_name": "timeSteps", "data": {},
    })
    assert "exactly one" in both["error"]


def test_write_by_schema_happy_path(ctx):
    result = _write_workflow(ctx)
    assert result.get("ok"), result
    assert result["path"] == "WorkflowFiles/Import/ImportDemoGrids.xml"
    assert ctx.rendered[result["path"]].model is not None


def test_write_generic_file(ctx):
    result = WRITE_GENERIC_FILE.handler(ctx, {
        "root_tag": "gridDisplay",
        "xsd_name": "gridDisplay.xsd",
        "output_path": "DisplayConfigFiles/GridDisplayDemo.xml",
        "body": {
            "title": "Demo",
            "gridPlotGroup": {
                "@id": "Demo",
                "gridPlot": {
                    "@id": "DemoPlot",
                    "@name": "Demo plot",
                    "timeSeriesSet": {
                        "moduleInstanceId": "ImportDemo",
                        "valueType": "grid",
                        "parameterId": "PC.nwp",
                        "locationId": "Demo",
                        "timeSeriesType": "external forecasting",
                        "timeStep": {"@unit": "hour", "@multiplier": "3"},
                        "readWriteMode": "read only",
                    },
                },
            },
        },
    })
    assert result.get("ok"), result
    assert "gridDisplay.xsd" in result["xsd"]


def test_write_generic_file_unknown_xsd(ctx):
    result = WRITE_GENERIC_FILE.handler(ctx, {
        "root_tag": "x", "xsd_name": "nope.xsd",
        "output_path": "a.xml", "body": {},
    })
    assert "unknown XSD" in result["error"]


def test_derive_descriptors_and_topology(ctx):
    _write_workflow(ctx)
    descriptors = DERIVE.handler(ctx, {"what": "descriptors"})
    assert descriptors.get("ok"), descriptors
    assert ("RegionConfigFiles/WorkflowDescriptors.xml"
            in descriptors["paths"])
    topology = DERIVE.handler(ctx, {"what": "topology"})
    assert topology.get("ok"), topology
    assert "Topology.xml" in topology["path"]
    # Re-derive refreshes rather than skips.
    _write_workflow(ctx, "ImportDemo2Grids")
    again = DERIVE.handler(ctx, {"what": "descriptors"})
    assert again.get("ok") and again["paths"]


def test_derive_topology_without_workflows_errors(ctx):
    assert "error" in DERIVE.handler(ctx, {"what": "topology"})


def test_derive_global_properties(ctx):
    result = DERIVE.handler(ctx, {
        "what": "global_properties",
        "project_name": "gfs-demo",
        "time_zone": "GMT",
        "region": "Gulf of Guinea",
    })
    assert result.get("ok"), result
    content = ctx.rendered[result["path"]].content
    assert "TIMEZONE=GMT" in content
    assert "REGION=Gulf of Guinea" in content


def test_validate_project_flags_dangling_module_instance(ctx):
    # A workflow referencing ImportDemo with no module config of that name.
    _write_workflow(ctx)
    report = VALIDATE_PROJECT.handler(ctx, {})
    assert report["xsd_failures"] == []
    unresolved_values = {u["value"] for u in report["semantic"]["unresolved"]}
    assert "ImportDemo" in unresolved_values


def test_generic_body_locationset_declaration_resolves(ctx):
    # A typed module references a locationSetId declared ONLY inside the
    # generic-body LocationSets.xml — the reflection walker can't see it,
    # the XML harvest must (the first live GFS run hit exactly this).
    module = WRITE_CONFIG_FILE.handler(ctx, {
        "schema": "TimeSeriesImportRun",
        "output_path": "ModuleConfigFiles/Import/ImportDemo.xml",
        "data": {
            "import": [{
                "general": {
                    "importType": "CanadaMeteoWCS",
                    "serverUrl": "https://example.test/wcs",
                },
                "timeSeriesSet": [{
                    "moduleInstanceId": "ImportDemo",
                    "valueType": "scalar",
                    "parameterId": "PC.nwp",
                    "locationSetId": "GulfStations",
                    "timeSeriesType": "external forecasting",
                    "timeStep": {"unit": "hour", "multiplier": 3},
                    "readWriteMode": "add originals",
                }],
            }],
        },
    })
    assert module.get("ok"), module
    report = VALIDATE_PROJECT.handler(ctx, {})
    values = {u["value"] for u in report["semantic"]["unresolved"]}
    assert "GulfStations" in values  # not declared yet
    declared = WRITE_CONFIG_FILE.handler(ctx, {
        "spec_name": "locationSetsFile",
        "data": {"body": [{"locationSet": {
            "@id": "GulfStations", "locationId": ["ST1"],
        }}]},
    })
    assert declared.get("ok"), declared
    report = VALIDATE_PROJECT.handler(ctx, {})
    values = {u["value"] for u in report["semantic"]["unresolved"]}
    assert "GulfStations" not in values


def test_mini_import_project_semantics_resolve(ctx):
    # Stations -> Locations.xml.
    WRITE_INPUT_CSV.handler(ctx, {
        "filename": "locations.csv",
        "header": ["id", "name", "lat", "lon"],
        "rows": [["ST1", "Accra", "5.55", "-0.21"]],
    })
    WRITE_INPUT_CSV.handler(ctx, {
        "filename": "parameters.csv",
        "header": ["id", "name", "group", "unit", "parametertype"],
        "rows": [["PC.nwp", "Precipitation NWP", "Precip", "mm",
                  "accumulative"]],
    })
    INGEST_CSVS.handler(ctx, {})
    # A module config whose filename declares ImportDemo...
    module = WRITE_CONFIG_FILE.handler(ctx, {
        "schema": "TimeSeriesImportRun",
        "output_path": "ModuleConfigFiles/Import/ImportDemo.xml",
        "data": {
            "import": [{
                "general": {
                    "importType": "CanadaMeteoWCS",
                    "serverUrl": "https://example.test/wcs",
                    "idMapId": "IdImportDemo",
                },
                "timeSeriesSet": [{
                    "moduleInstanceId": "ImportDemo",
                    "valueType": "scalar",
                    "parameterId": "PC.nwp",
                    "locationId": "ST1",
                    "timeSeriesType": "external forecasting",
                    "timeStep": {"unit": "hour", "multiplier": 3},
                    "readWriteMode": "add originals",
                }],
            }],
        },
    })
    assert module.get("ok"), module
    # ...an idMap declaring IdImportDemo by filename...
    idmap = WRITE_CONFIG_FILE.handler(ctx, {
        "schema": "IdMap",
        "output_path": "IdMapFiles/IdImportDemo.xml",
        "data": {"parameter": [{"internal": "PC.nwp",
                                "external": "precip"}]},
    })
    assert idmap.get("ok"), idmap
    # ...and the workflow invoking ImportDemo.
    _write_workflow(ctx)
    report = VALIDATE_PROJECT.handler(ctx, {})
    assert report["xsd_failures"] == []
    assert report["semantic"]["unresolved_count"] == 0, report["semantic"]
