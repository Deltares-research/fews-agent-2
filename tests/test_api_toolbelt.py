"""HTTP toolbelt — FastAPI TestClient, no LLM."""
from __future__ import annotations

from fastapi.testclient import TestClient

from app.api import server

from tests.gauntlet_fixtures import BROKEN_XML, IMPORT_XML


def test_validate_xml_endpoint():
    client = TestClient(server.app)
    resp = client.post(
        "/validate/xml",
        json={"xml": BROKEN_XML, "spec": "TimeSeriesImportRun", "tiers": ["xsd"]},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is False
    assert body["error_count"] >= 1


def test_schema_shape_endpoint():
    client = TestClient(server.app)
    resp = client.get("/schema/TimeSeriesImportRun")
    assert resp.status_code == 200
    body = resp.json()
    assert body["name"] == "TimeSeriesImportRun"
    assert body["xsd_rel"] == "timeSeriesImportRun.xsd"


def test_render_spec_endpoint():
    client = TestClient(server.app)
    resp = client.post(
        "/render/spec",
        json={
            "spec": "Workflow",
            "data": {
                "version": "1.1",
                "activity": [{"moduleInstanceId": "ImportGFS"}],
            },
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert "<workflow" in body["xml"]
    assert body["suggested_relpath"]


def test_explain_and_examples():
    client = TestClient(server.app)
    expl = client.get("/diagnostics/xsd.schema")
    assert expl.status_code == 200
    assert expl.json()["rule_id"] == "xsd.schema"
    ex = client.get("/examples", params={"query": "GFS", "k": 2})
    assert ex.status_code == 200
    assert "examples" in ex.json()


def test_validate_xml_well_formed_does_not_500():
    client = TestClient(server.app)
    resp = client.post("/validate/xml", json={"xml": IMPORT_XML})
    assert resp.status_code == 200
    assert "ok" in resp.json()
