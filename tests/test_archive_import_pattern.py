"""archive_import — the inbound half of the archive round-trip.

Farmed from FEWS-Conform (FromArchiveData.xml + FromArchiveHistoricalEvents.xml).
Driven by a `categories` list; the time-series categories share a
timeSeriesSetIdMap and read <archive_root>/<subfolder>, messages/ratingCurves
are folder-only, historicalEvents reads <archive_root> via idMapId. Tests
render both source variants through expand() and XSD-validate.
"""
from __future__ import annotations

from pathlib import Path

from fews_agent.agent.blueprint import Blueprint, PatternRef, expand
from fews_agent.validation.xsd import validate_xsd

REPO_ROOT = Path(__file__).resolve().parents[1]
PATTERNS_ROOT = REPO_ROOT / "patterns"
PATTERN = "auto/archive_import"

DATA = {
    "name": "Data",
    "archive_root": "$ArchiveDownloadFolder$",
    "categories": ["simulated", "externalForecast", "observed",
                   "messages", "ratingCurves"],
    "id_map": "IdArchiveImportStation",
}
HIST = {
    "name": "HistoricalEvents",
    "archive_root": "$ToFewsFolder$/HistoricEvents",
    "categories": ["historicalEvents"],
    "historical_events_id_map": "IdArchive",
}


def _render(inst):
    bp = Blueprint(
        name="ai-test", output_root=Path("out"),
        patterns=[PatternRef(pattern=PATTERN, instances=[inst])],
    )
    res = expand(bp, PATTERNS_ROOT)
    assert not res.errors, res.errors
    return {rf.relpath.replace("\\", "/"): rf.content for rf in res.rendered_files}


def _xsd_ok(xml):
    ok, msg = validate_xsd(xml.encode("utf-8"))
    assert ok, msg


def test_data_import_all_categories():
    files = _render(DATA)
    mc = files["ModuleConfigFiles/Archive/FromArchiveData.xml"]
    wf = files["WorkflowFiles/Archive/From_Archive_Data.xml"]
    _xsd_ok(mc)
    _xsd_ok(wf)
    # Every requested kind present.
    for kind in ("importSimulated", "importExternalForecast", "importObserved",
                 "importMessages", "importRatingCurves"):
        assert f"<{kind}>" in mc
    # ts-categories carry the shared idMap + their subfolder.
    assert mc.count("<timeSeriesSetIdMap>IdArchiveImportStation</timeSeriesSetIdMap>") == 3
    assert "<importFolder>$ArchiveDownloadFolder$/externalforecasts</importFolder>" in mc
    # 3 ts-categories × 1 idMap each — folder-only kinds add none.
    assert mc.count("<timeSeriesSetIdMap>") == 3
    assert "<importFolder>$ArchiveDownloadFolder$/messages</importFolder>" in mc
    assert "<moduleInstanceId>FromArchiveData</moduleInstanceId>" in wf


def test_historical_events_variant():
    mc = _render(HIST)["ModuleConfigFiles/Archive/FromArchiveHistoricalEvents.xml"]
    _xsd_ok(mc)
    assert "<importHistoricalEvents>" in mc
    assert "<importFolder>$ToFewsFolder$/HistoricEvents</importFolder>" in mc
    assert "<idMapId>IdArchive</idMapId>" in mc
    # No timeSeriesSetIdMap on the historical-events shape.
    assert "<timeSeriesSetIdMap>" not in mc


def test_only_selected_categories_emitted():
    inst = {"name": "Obs", "archive_root": "$ArchiveDownloadFolder$",
            "categories": ["observed"], "id_map": "IdArchiveImportStation"}
    mc = _render(inst)["ModuleConfigFiles/Archive/FromArchiveObs.xml"]
    _xsd_ok(mc)
    assert "<importObserved>" in mc
    assert "<importSimulated>" not in mc
    assert "<importMessages>" not in mc
