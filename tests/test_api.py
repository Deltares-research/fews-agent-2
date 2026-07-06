"""HTTP API tests — drive app.api.server via FastAPI's TestClient, offline.

These mirror the existing turn-loop tests: the two LLM seams are patched
on the shared engine (``turn_engine.classify_intent`` /
``turn_engine.compose_reply``) so no Ollama is needed, and the API's own
LLM pre-flight (``app.api.server.check_ollama_for_model``) is stubbed to
"reachable" so the turn endpoint doesn't 503 in an offline test env.

Covered:
  * ``GET /health`` reports liveness + a boolean reachability flag,
  * ``POST /sessions`` mints a session with a resolvable id,
  * ``POST /sessions/{id}/turn`` runs one turn and returns the composed
    reply + resolved patterns/slots (a single-half + narrowing prose so
    the disambiguation gate doesn't short-circuit),
  * ``GET /sessions/{id}`` returns the resolved intermediate variables,
  * the turn endpoint returns 503 when the LLM pre-flight fails,
  * ``POST /sessions/{id}/build`` runs the real deterministic build on a
    tiny GFS-only import project and returns the per-file XSD table.

The build test invokes the real build path (no LLM required — the filter
drafter falls back to a bundled standard), so it is a little slower.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from fews_agent.agent import turn_engine
from app.api import server


@pytest.fixture
def client(tmp_path, monkeypatch):
    """A TestClient with sessions rooted in a tmp dir and the LLM stubbed."""
    monkeypatch.setattr(server, "OUTPUT_ROOT", tmp_path)

    # Stub the two LLM seams on the shared engine (one seam, both drivers).
    # classify_intent emulates the LLM's default-to-forecasting pick; the
    # narrowing prose in the turn test overrides it deterministically.
    monkeypatch.setattr(
        turn_engine, "classify_intent",
        lambda *a, **k: {"intent": "build_forecasting_project", "entities": {}},
    )
    monkeypatch.setattr(
        turn_engine, "compose_reply", lambda *a, **k: "STUB-REPLY",
    )
    # The API's LLM pre-flight → "reachable" so /turn runs offline.
    monkeypatch.setattr(server, "check_ollama_for_model", lambda *a, **k: None)

    return TestClient(server.app)


def _new_session(client, name="apitest") -> str:
    resp = client.post("/sessions", json={"project_name": name})
    assert resp.status_code == 201, resp.text
    return resp.json()["session_id"]


# --------------------------------------------------------------------------
# health
# --------------------------------------------------------------------------

def test_health_ok(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    # Stubbed reachable in this fixture.
    assert body["ollama_reachable"] is True
    assert body["model"]


def test_health_reports_unreachable(client, monkeypatch):
    monkeypatch.setattr(
        server, "check_ollama_for_model", lambda *a, **k: "Ollama down.",
    )
    body = client.get("/health").json()
    assert body["ollama_reachable"] is False
    assert body["detail"] == "Ollama down."


# --------------------------------------------------------------------------
# session creation + retrieval
# --------------------------------------------------------------------------

def test_create_session_returns_resolvable_id(client):
    resp = client.post("/sessions", json={"project_name": "demo"})
    assert resp.status_code == 201, resp.text
    body = resp.json()
    sid = body["session_id"]
    assert sid.startswith("demo_")
    assert body["project_name"] == "demo"
    # The session is immediately retrievable.
    got = client.get(f"/sessions/{sid}")
    assert got.status_code == 200
    assert got.json()["intent"] is None
    assert got.json()["slots"] == {}


def test_get_unknown_session_404s(client):
    assert client.get("/sessions/does-not-exist").status_code == 404


# --------------------------------------------------------------------------
# turn
# --------------------------------------------------------------------------

def test_turn_resolves_patterns_and_returns_reply(client):
    sid = _new_session(client)
    # Single-half import request WITH a narrowing signal ("no basin model"),
    # so the disambiguation gate is skipped and patterns resolve this turn.
    resp = client.post(
        f"/sessions/{sid}/turn",
        json={"message": "Import NOAA GFS grids, no basin model."},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["short_circuit"] is False
    assert body["reply"] == "STUB-REPLY"
    assert body["intent"] == "build_data_import_only"
    paths = {p["pattern"] for p in body["patterns"]}
    assert "auto/nwp_grid_noaa" in paths
    assert body["slots"].get("imports") == ["GFS"]
    # Internals diagnostics are surfaced on a non-short-circuit turn.
    assert body["internals"]

    # State is persisted: GET reflects the resolved patterns.
    state = client.get(f"/sessions/{sid}").json()
    assert {p["pattern"] for p in state["patterns"]} == paths


def test_turn_short_circuits_on_ambiguous_intent(client):
    sid = _new_session(client)
    # A bare single-half request with no narrowing signal → the gate asks.
    resp = client.post(
        f"/sessions/{sid}/turn",
        json={"message": "Import NOAA GFS grids for precipitation."},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["short_circuit"] is True
    assert body["patterns"] == []  # nothing resolved on a short-circuit


def test_turn_503_when_llm_unreachable(client, monkeypatch):
    sid = _new_session(client)
    monkeypatch.setattr(
        server, "check_ollama_for_model", lambda *a, **k: "Ollama down.",
    )
    resp = client.post(
        f"/sessions/{sid}/turn", json={"message": "Import GFS grids."},
    )
    assert resp.status_code == 503
    assert "Ollama down." in resp.json()["detail"]


def test_turn_unknown_session_404s(client):
    resp = client.post("/sessions/nope/turn", json={"message": "hi"})
    assert resp.status_code == 404


# --------------------------------------------------------------------------
# build (real deterministic build path, no LLM)
# --------------------------------------------------------------------------

def test_build_before_resolve_409s(client):
    sid = _new_session(client)
    assert client.post(f"/sessions/{sid}/build").status_code == 409


def test_build_produces_xsd_valid_files(client):
    sid = _new_session(client, name="buildtest")
    # Resolve a tiny GFS-only import project via one stubbed turn.
    turn = client.post(
        f"/sessions/{sid}/turn",
        json={"message": "Import NOAA GFS grids, no basin model."},
    )
    assert turn.status_code == 200, turn.text
    assert {p["pattern"] for p in turn.json()["patterns"]}

    resp = client.post(f"/sessions/{sid}/build", json={"force": True})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["files_total"] > 0
    assert body["project_yaml"].endswith("project.yaml")
    # Every emitted XML validated against its XSD.
    assert body["files_xsd_ok"] == body["files_xml"]
    assert body["ok"] is True
    assert all(f["xsd_ok"] for f in body["files"] if f["path"].endswith(".xml"))
