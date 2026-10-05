"""Content-grounding fixes: read_example tool, undefined-$PROPERTY$
check, extra_properties on the global-properties deriver."""
from __future__ import annotations

import pytest

from fews_agent.react.tools.derive_tools import DERIVE
from fews_agent.react.tools.example_tools import EXAMPLES_ROOT, READ_EXAMPLE
from fews_agent.react.tools.file_tools import WRITE_CONFIG_FILE
from fews_agent.react.tools.validate_tools import VALIDATE_PROJECT

needs_reference = pytest.mark.skipif(
    not EXAMPLES_ROOT.is_dir(),
    reason="reference config not present on this checkout",
)


@needs_reference
def test_read_example_listing_and_fetch(ctx):
    listing = READ_EXAMPLE.handler(ctx, {"filter": "idimportgfs"})
    assert listing["count"] >= 1
    path = listing["files"].splitlines()[0]
    page = READ_EXAMPLE.handler(ctx, {"path": path})
    assert page["content"].startswith("<?xml")
    assert "idMap" in page["content"]


@needs_reference
def test_read_example_rejects_escape_and_missing(ctx):
    assert "error" in READ_EXAMPLE.handler(ctx, {"path": "../../.env"})
    missing = READ_EXAMPLE.handler(ctx, {"path": "Nope/Missing.xml"})
    assert "error" in missing


def test_undefined_properties_flagged_then_fixed(ctx):
    # A workflow referencing a $PROPERTY$ nothing defines.
    wf = WRITE_CONFIG_FILE.handler(ctx, {
        "schema": "Workflow",
        "output_path": "WorkflowFiles/ImportDemoGrids.xml",
        "data": {"version": "1.1", "activity": [{
            "runIndependent": True,
            "moduleInstanceId": "ImportDemo",
            "description": "$MAPLAYERSCACHE_FOLDER$",
        }]},
    })
    assert wf.get("ok"), wf
    report = VALIDATE_PROJECT.handler(ctx, {})
    names = {u["property"] for u in report["undefined_properties"]}
    assert "MAPLAYERSCACHE_FOLDER" in names
    # Deriving sa_global with extra_properties clears it.
    derived = DERIVE.handler(ctx, {
        "what": "global_properties",
        "time_zone": "GMT",
        "extra_properties": {
            "MAPLAYERSCACHE_FOLDER": "%REGION_HOME%/MapLayerFiles",
        },
    })
    assert derived.get("ok"), derived
    assert derived["extra_defined"] == ["MAPLAYERSCACHE_FOLDER"]
    report = VALIDATE_PROJECT.handler(ctx, {})
    names = {u["property"] for u in report["undefined_properties"]}
    assert "MAPLAYERSCACHE_FOLDER" not in names
    # Base-derived properties (IMPORT_FOLDER etc.) count as defined too.
    sa = ctx.rendered["RootConfigFiles/sa_global.Properties"].content
    assert "MAPLAYERSCACHE_FOLDER=%REGION_HOME%/MapLayerFiles" in sa


def test_derive_topology_covers_unbucketed_workflows(ctx):
    # A workflow name outside the tutorial-era buckets (the live GFS
    # run produced ImportAndProcessGFS_GulfOfGuinea) must still get a
    # topology node.
    wf = WRITE_CONFIG_FILE.handler(ctx, {
        "schema": "Workflow",
        "output_path": "WorkflowFiles/ImportAndProcessGFS_GoG.xml",
        "data": {"version": "1.1", "activity": [{
            "runIndependent": True, "moduleInstanceId": "ImportGFS_GoG",
        }]},
    })
    assert wf.get("ok"), wf
    result = DERIVE.handler(ctx, {"what": "topology"})
    assert result.get("ok"), result
    assert "ImportAndProcessGFS_GoG" in result.get("note", "")
    topo = ctx.rendered["RegionConfigFiles/Topology.xml"].content
    assert ("<workflowId>ImportAndProcessGFS_GoG</workflowId>" in topo)
    # A bucketed name still lands in its named group, not the catch-all.
    WRITE_CONFIG_FILE.handler(ctx, {
        "schema": "Workflow",
        "output_path": "WorkflowFiles/Import/NOAA/ImportGFSGrids.xml",
        "data": {"version": "1.1", "activity": [{
            "runIndependent": True, "moduleInstanceId": "ImportGFS",
        }]},
    })
    again = DERIVE.handler(ctx, {"what": "topology"})
    assert again.get("ok"), again
    topo = ctx.rendered["RegionConfigFiles/Topology.xml"].content
    assert "<workflowId>ImportGFSGrids</workflowId>" in topo
    assert 'id="ImportNOAAGridNodes"' in topo


def test_stem_declarations_cover_model_less_files(ctx):
    # A file registered without a retained model (e.g. produced by a
    # generic path) still declares its moduleInstanceId by filename
    # stem, so a typed workflow referencing it resolves.
    ctx.store(
        "ModuleConfigFiles/ImportDemo.xml",
        '<timeSeriesImportRun xmlns="http://www.wldelft.nl/fews"/>',
        "generic:timeSeriesImportRun",
        None,
    )
    wf = WRITE_CONFIG_FILE.handler(ctx, {
        "schema": "Workflow",
        "output_path": "WorkflowFiles/ImportDemoGrids.xml",
        "data": {"version": "1.1", "activity": [{
            "runIndependent": True, "moduleInstanceId": "ImportDemo",
        }]},
    })
    assert wf.get("ok"), wf
    report = VALIDATE_PROJECT.handler(ctx, {})
    assert report["files"] == 2
    assert report["semantic"]["unresolved_count"] == 0, report["semantic"]


def test_expression_issues_flagged(ctx):
    # Content with unsupported expression vocabulary (stored directly —
    # the scanner reads rendered text, and files without a pinned XSD
    # hint skip XSD).
    ctx.store(
        "ModuleConfigFiles/ProcessDemo.xml",
        "<transformationModule>"
        "<expression>MOD(270-ATAN2(V,U)*180/PI,360)</expression>"
        "<expression>sqrt(U*U+V*V)</expression>"
        "</transformationModule>",
        "TransformationModule",
    )
    report = VALIDATE_PROJECT.handler(ctx, {})
    issues = report["expression_issues"]
    assert len(issues) == 1
    assert issues[0]["path"] == "ModuleConfigFiles/ProcessDemo.xml"
    assert "ATAN2" in issues[0]["unsupported"]
    assert "MOD(" in issues[0]["unsupported"]
    assert "PI" in issues[0]["unsupported"]


def test_expression_issues_allow_lowercase_vocabulary(ctx):
    ctx.store(
        "ModuleConfigFiles/WindDemo.xml",
        "<transformationModule><expression>"
        "if ( U &gt;= 0, 270 - (360/(2*pi))*atan(V/U), 90 )"
        "</expression></transformationModule>",
        "TransformationModule",
    )
    report = VALIDATE_PROJECT.handler(ctx, {})
    assert report["expression_issues"] == []


def test_undefined_properties_ignores_fews_internal_tokens(ctx):
    wf = WRITE_CONFIG_FILE.handler(ctx, {
        "schema": "Workflow",
        "output_path": "WorkflowFiles/ImportDemoGrids.xml",
        "data": {"version": "1.1", "activity": [{
            "runIndependent": True,
            "moduleInstanceId": "ImportDemo",
            "description": "%REGION_HOME%/x %TIME_ZERO(yyyyMMdd)%",
        }]},
    })
    assert wf.get("ok"), wf
    report = VALIDATE_PROJECT.handler(ctx, {})
    assert report["undefined_properties"] == []
