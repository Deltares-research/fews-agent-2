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

from app.api import server


class _Resp:
    def __init__(self, data):
        self.data = data


class _PatchProvider:
    """LLM-first seam: returns scripted {reply, patch} payloads in order,
    then repeats the last one (so helper turns can run any number of times)."""

    def __init__(self, *payloads):
        self.payloads = list(payloads) or [
            {"reply": "Added GFS.",
             "patch": [{"op": "add_import", "name": "GFS"}]},
        ]

    def generate_json(self, system, user, schema):
        payload = (self.payloads.pop(0) if len(self.payloads) > 1
                   else self.payloads[0])
        return _Resp(payload)


@pytest.fixture
def client(tmp_path, monkeypatch):
    """A TestClient with sessions rooted in a tmp dir and the LLM stubbed.

    The default provider answers every prose turn with an add-GFS patch
    (enough for the build tests to resolve a project); individual tests
    override ``server.get_provider_or_ollama`` with their own script.
    """
    monkeypatch.setattr(server, "OUTPUT_ROOT", tmp_path)
    monkeypatch.setattr(
        server, "get_provider_or_ollama", lambda model: _PatchProvider(),
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
    # This test exercises the OLLAMA-down path; pin the provider so it's
    # hermetic regardless of ambient .env (the API loads .env at import).
    monkeypatch.setenv("FEWS_AGENT_PROVIDER", "ollama")
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

def test_turn_applies_patch_and_returns_model_reply(client, monkeypatch):
    monkeypatch.setattr(
        server, "get_provider_or_ollama",
        lambda model: _PatchProvider({
            "reply": "Added GFS with precipitation. Want a map area?",
            "patch": [{"op": "add_import", "name": "GFS",
                       "data_types": ["precipitation"]}],
        }),
    )
    sid = _new_session(client)
    resp = client.post(
        f"/sessions/{sid}/turn",
        json={"message": "Import NOAA GFS grids, no basin model."},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "Added GFS" in body["reply"]              # model's voice, verbatim
    assert "GFS" in body["confirmation"]             # grey applied-facts
    paths = {p["pattern"] for p in body["patterns"]}
    assert "auto/nwp_grid_noaa" in paths
    assert body["slots"].get("imports") == ["GFS"]
    assert body["intent"] == "build_data_import_only"   # derived, not asked

    # State is persisted: GET reflects the resolved patterns.
    state = client.get(f"/sessions/{sid}").json()
    assert {p["pattern"] for p in state["patterns"]} == paths


def test_turn_vague_prose_is_model_handled_not_gated(client, monkeypatch):
    # No disambiguation gate: vague prose gets the model's own question with
    # an empty patch — nothing resolved, nothing asked about "intents".
    monkeypatch.setattr(
        server, "get_provider_or_ollama",
        lambda model: _PatchProvider({
            "reply": "What data should this project bring in?", "patch": [],
        }),
    )
    sid = _new_session(client)
    body = client.post(
        f"/sessions/{sid}/turn", json={"message": "hi, help me build a config"},
    ).json()
    assert body["patterns"] == []
    assert body["confirmation"] == ""
    assert "forecasting project" not in body["reply"].lower()


def test_turn_503_when_llm_unreachable(client, monkeypatch):
    sid = _new_session(client)
    monkeypatch.setenv("FEWS_AGENT_PROVIDER", "ollama")   # test the ollama path
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

# --------------------------------------------------------------------------
# module-mode (focus one FEWS-folder module and operate on it)
# --------------------------------------------------------------------------

def test_module_commands_run_without_llm(client, monkeypatch):
    # /modules and /module are deterministic — they work with the LLM down.
    monkeypatch.setattr(
        server, "check_ollama_for_model", lambda *a, **k: "Ollama down.",
    )
    sid = _new_session(client)
    body = client.post(f"/sessions/{sid}/turn", json={"message": "/modules"}).json()
    assert body["module_mode"] is True
    assert "processing" in body["reply"]
    # Focus a module by its synonym; the card comes back and focus is recorded.
    got = client.post(f"/sessions/{sid}/turn", json={"message": "/module imports"})
    assert got.status_code == 200
    assert got.json()["current_module"] == "processing"


def test_llm_first_add_edit_build_flow_over_http(client, monkeypatch):
    # ONE shared script instance — get_provider_or_ollama is called per turn,
    # so a fresh provider per call would replay payload[0] forever.
    script = _PatchProvider(
        {"reply": "Added GFS with precipitation and temperature.",
         "patch": [{"op": "set_focus", "module": "processing"},
                   {"op": "add_import", "name": "GFS",
                    "data_types": ["precipitation", "temperature"]}]},
        {"reply": "Added HRDPS too.",
         "patch": [{"op": "add_import", "name": "HRDPS"}]},
        {"reply": "Building what you have.",
         "patch": [{"op": "build"}]},
    )
    monkeypatch.setattr(
        server, "get_provider_or_ollama", lambda model: script,
    )
    sid = _new_session(client, name="modeapi")

    r1 = client.post(
        f"/sessions/{sid}/turn",
        json={"message": "set up the imports module with a NOAA GFS import "
                         "for precipitation and temperature"},
    )
    assert r1.status_code == 200, r1.text
    b1 = r1.json()
    assert b1["current_module"] == "processing"      # advisory focus set
    assert "auto/nwp_grid_noaa" in {p["pattern"] for p in b1["patterns"]}
    assert b1["slots"]["imports"] == ["GFS"]
    assert "GFS" in b1["confirmation"]

    # Follow-up add is additive.
    b2 = client.post(
        f"/sessions/{sid}/turn", json={"message": "also add an HRDPS import"},
    ).json()
    assert set(b2["slots"]["imports"]) == {"GFS", "HRDPS"}

    # A build request surfaces wants_build + a hint to POST /build.
    b3 = client.post(
        f"/sessions/{sid}/turn", json={"message": "build the module"},
    ).json()
    assert b3["wants_build"] is True
    assert f"/sessions/{sid}/build" in b3["reply"]

    # And the dedicated build endpoint assembles the focused project.
    built = client.post(f"/sessions/{sid}/build", json={"force": True}).json()
    assert built["ok"] is True
    assert built["files_xsd_ok"] == built["files_xml"]


def test_build_before_resolve_409s(client):
    sid = _new_session(client)
    assert client.post(f"/sessions/{sid}/build").status_code == 409


def _resolve_gfs_project(client, name):
    """Mint a session and resolve a tiny GFS-only import project via one turn."""
    sid = _new_session(client, name=name)
    turn = client.post(
        f"/sessions/{sid}/turn",
        json={"message": "Import NOAA GFS grids, no basin model."},
    )
    assert turn.status_code == 200, turn.text
    assert {p["pattern"] for p in turn.json()["patterns"]}
    return sid


def test_scoped_phase_build_over_http(client):
    sid = _resolve_gfs_project(client, "phasebuild")
    resp = client.post(f"/sessions/{sid}/build", json={"phase": "imports"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["scope"] == "phase:imports"
    assert body["built_phases"] == ["imports"]
    assert body["files_total"] > 0
    # Scoped build renders only the phase's pattern outputs, all XSD-valid.
    assert body["files_xsd_ok"] == body["files_xml"]
    assert body["ok"] is True
    # It skips whole-project assembly, so no deriver/singleton files.
    paths = {f["path"].replace("\\", "/") for f in body["files"]}
    assert any("Import/NOAA/ImportGFS.xml" in p for p in paths)
    assert not any("Topology.xml" in p for p in paths)


def test_scoped_module_build_over_http(client):
    sid = _resolve_gfs_project(client, "modbuild")
    # 'imports' is a synonym for the processing module.
    resp = client.post(f"/sessions/{sid}/build", json={"module": "imports"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["scope"] == "module:processing"
    assert "imports" in body["built_phases"]
    assert body["files_xsd_ok"] == body["files_xml"]
    assert body["ok"] is True


def test_scoped_build_rejects_unknown_phase(client):
    sid = _resolve_gfs_project(client, "badphase")
    resp = client.post(f"/sessions/{sid}/build", json={"phase": "frobnicate"})
    assert resp.status_code == 400
    assert "Unknown phase" in resp.json()["detail"]


def test_view_only_module_not_built_on_its_own(client):
    sid = _resolve_gfs_project(client, "viewonly")
    resp = client.post(f"/sessions/{sid}/build", json={"module": "filters"})
    assert resp.status_code == 409
    assert "isn't built on its own" in resp.json()["detail"]


def test_phase_and_module_mutually_exclusive(client):
    sid = _resolve_gfs_project(client, "bothsel")
    resp = client.post(
        f"/sessions/{sid}/build", json={"phase": "imports", "module": "processing"},
    )
    assert resp.status_code == 400
    assert "mutually exclusive" in resp.json()["detail"]


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
