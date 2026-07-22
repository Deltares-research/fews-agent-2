"""The LLM-first single-call turn — contract tests with a scripted provider.

No live model: the provider returns fixed JSON, and we assert on what the
turn DOES with it — validation, application, signals, fallbacks. The live
behaviour is exercised by runners/agent/eval_llm_turn.py (opt-in).
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from fews_agent.agent.llm_turn import (
    build_digest,
    catalog_digest,
    gap_digest,
    inputs_digest,
    run_llm_turn,
    state_digest,
)
from fews_agent.agent.project_chat import build_pattern_catalog

REPO = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def catalog():
    return build_pattern_catalog(REPO / "fews_agent" / "patterns")


@pytest.fixture()
def state():
    return {"slots": {}, "current_module": "processing",
            "intent": "build_data_import_only"}


class _Resp:
    def __init__(self, data):
        self.data = data


class _Scripted:
    """Returns queued JSON payloads; records the prompts it was given."""

    def __init__(self, *payloads):
        self.payloads = list(payloads)
        self.calls: list[dict] = []

    def generate_json(self, system, user, schema):
        self.calls.append({"system": system, "user": user})
        if not self.payloads:
            raise RuntimeError("script exhausted")
        return _Resp(self.payloads.pop(0))


class _Down:
    def generate_json(self, *a, **k):
        raise ConnectionError("no backend")


# --- the digests (pure) ---------------------------------------------------

def test_catalog_digest_carries_names_requirements_outputs(catalog):
    text = catalog_digest(catalog)
    assert "nwp_grid_noaa" in text
    assert "coastal_sfincs" in text
    assert "requires: basin_name" in text          # raven_basin's contract
    assert "Import.xml" in text                    # outputs preview


def test_state_digest_reports_focus_slots_and_builds(catalog):
    st = {"slots": {"imports": ["GFS"],
                    "import_overrides": {"GFS": {"grid_resolution": "0p50"}}},
          "current_module": "processing", "built_phases": ["imports"]}
    text = state_digest(st)
    # Focus is spoken as the FEWS folder label, never the internal key.
    assert "ModuleConfigFiles + WorkflowFiles" in text and "advisory" in text
    assert "NEVER change their view" in text
    assert '"GFS"' in text
    assert "0p50" in text
    assert "imports" in text  # built phases


def test_gap_digest_names_missing_csvs(state, tmp_path):
    state["slots"]["imports"] = ["GFS"]
    state["slots"]["wants_interpolation"] = True
    text = gap_digest(state, tmp_path)  # empty inputs dir
    assert "locations.csv" in text


def test_inputs_digest_reads_headers_and_row_counts(tmp_path):
    (tmp_path / "locations.csv").write_text(
        "id,name,lat,lon\nA,Alpha,1,2\nB,Beta,3,4\n", encoding="utf-8",
    )
    text = inputs_digest(tmp_path)
    assert "locations.csv: 2 rows" in text
    assert "id,name,lat,lon" in text


def test_build_digest_reports_last_summary():
    st = {"last_build_summary": {
        "phase": "imports", "files_total": 8, "files_xml": 8,
        "files_xsd_ok": 7,
        "files": [{"path": "Bad.xml", "xsd_ok": False}],
    }}
    text = build_digest(st)
    assert "7/8" in text
    assert "Bad.xml" in text


# --- the turn -------------------------------------------------------------

def test_valid_patch_applies_and_reports_grey(state, catalog):
    prov = _Scripted({"reply": "Added GFS. What variables should it carry?",
                      "patch": [{"op": "add_import", "name": "GFS"}]})
    res = run_llm_turn(state, "add GFS", catalog, provider=prov)
    assert res.kind == "edit"
    assert "GFS" in state["slots"]["imports"]
    assert "GFS" in res.confirmation           # grey channel
    assert "Added GFS" in res.reply
    # The prompt carried the full grounding context.
    user_prompt = prov.calls[0]["user"]
    for section in ("CATALOG", "PROJECT STATE", "GAP", "INPUT FILES",
                    "LAST BUILD", "RECENT CONVERSATION"):
        assert section in user_prompt


def test_invalid_ops_dropped_loudly_valid_kept(state, catalog):
    prov = _Scripted({"reply": "Done.",
                      "patch": [{"op": "add_import", "name": "GFS"},
                                {"op": "add_import", "name": "MysteryModel"}]})
    res = run_llm_turn(state, "add gfs and mysterymodel", catalog,
                       provider=prov)
    assert "GFS" in state["slots"]["imports"]
    assert "MysteryModel" in res.reply         # surfaced, not silent
    assert "Not applied" in res.reply


def test_rhine_scenario_guessed_adapter_is_refused(state, catalog):
    """If the model violates the never-guess rule, the trust boundary still
    holds: the bogus adapter is dropped loudly, state untouched."""
    prov = _Scripted({"reply": "Added the Rhine basin.",
                      "patch": [{"op": "add_basin", "basin_name": "Rhine",
                                 "model_adapter": "sobek"}]})
    res = run_llm_turn(state, "i need it for the rhine basin", catalog,
                       provider=prov)
    assert state["slots"].get("basins") in (None, [])
    assert "sobek" in res.reply and "Not applied" in res.reply


def test_rhine_scenario_asking_is_a_clean_reply(state, catalog):
    prov = _Scripted({"reply": "Which model does Rhine run on — raven, "
                               "wflow, or hbv96?", "patch": []})
    res = run_llm_turn(state, "i need it for the rhine basin", catalog,
                       provider=prov)
    assert res.kind == "reply"                 # nothing changed
    assert res.confirmation == ""              # no grey fact for a question
    assert "raven" in res.reply


def test_compound_patch_single_turn(state, catalog):
    prov = _Scripted({"reply": "Swapped GFS for ECMWF at half degree.",
                      "patch": [
                          {"op": "add_import", "name": "GFS"},
                          {"op": "remove", "target": "GFS"},
                          {"op": "add_import", "name": "ECMWF",
                           "grid_resolution": "0p50"},
                      ]})
    res = run_llm_turn(state, "swap", catalog, provider=prov)
    assert state["slots"]["imports"] == ["ECMWF"]
    assert res.kind == "edit"


def test_signals_surface_on_result(state, catalog):
    prov = _Scripted({"reply": "Building now.",
                      "patch": [{"op": "build", "scope": "imports"}]})
    res = run_llm_turn(state, "build it", catalog, provider=prov)
    assert res.wants_build and res.build_scope == "imports"

    prov2 = _Scripted({"reply": "Opening the map for GFS.",
                       "patch": [{"op": "open_coordinates", "name": "GFS"}]})
    res2 = run_llm_turn(state, "set the map area", catalog, provider=prov2)
    assert res2.coordinates_for == "GFS"


def test_malformed_json_gets_one_repair_round(state, catalog):
    prov = _Scripted(
        {"nonsense": True},                                   # attempt 1: bad
        {"reply": "Added GFS.",                               # attempt 2: good
         "patch": [{"op": "add_import", "name": "GFS"}]},
    )
    res = run_llm_turn(state, "add GFS", catalog, provider=prov)
    assert len(prov.calls) == 2
    assert "invalid" in prov.calls[1]["user"]  # repair note appended
    assert "GFS" in state["slots"]["imports"]
    assert res.kind == "edit"


def test_provider_down_is_a_graceful_reply(state, catalog):
    res = run_llm_turn(state, "add GFS", catalog, provider=_Down())
    assert res.kind == "reply"
    assert state["slots"].get("imports") in (None, [])
    assert "slash commands" in res.reply.lower() or "/vars" in res.reply


def test_history_reaches_the_prompt(state, catalog):
    prov = _Scripted({"reply": "ok", "patch": []})
    history = [{"role": "user", "message": "add GFS"},
               {"role": "agent", "message": "Added GFS."}]
    run_llm_turn(state, "and temperature?", catalog, provider=prov,
                 history=history)
    assert "Added GFS." in prov.calls[0]["user"]


def test_show_variables_appends_the_deterministic_table(state, catalog):
    from fews_agent.agent.patch_ops import apply_patch
    apply_patch(state, [{"op": "add_import", "name": "GFS"}], catalog)
    prov = _Scripted({"reply": "Here's everything GFS carries:",
                      "patch": [{"op": "show_variables", "target": "GFS"}]})
    res = run_llm_turn(state, "what are the vars of GFS?", catalog,
                       provider=prov)
    # The model's intro + the EXACT deterministic table (same as /vars GFS).
    assert "Here's everything GFS carries:" in res.reply
    assert "`nwp_name`" in res.reply
    assert "`grid_resolution`" in res.reply
    assert "you set this" in res.reply


def test_prompt_carries_modules_map_and_pattern_module_tags(state, catalog):
    prov = _Scripted({"reply": "ok", "patch": []})
    run_llm_turn(state, "hello", catalog, provider=prov)
    user = prov.calls[0]["user"]
    # The modules map (folder names + keys) and per-pattern module tags — the
    # model's "what goes where" awareness.
    assert "FEWS MODULES" in user
    assert "RootConfigFiles (key: root)" in user
    assert "[lives in ModuleConfigFiles + WorkflowFiles]" in user
    # The no-silent-focus instruction rides the state digest too.
    assert "NEVER change their view" in user
