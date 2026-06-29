"""Tests for ask-on-ambiguity intent disambiguation (Slice 1: pure helpers).

These exercise only the deterministic detector + answer parser — no LLM,
no chat-state wiring (that's Slice 2). The detector decides *when* the
agent should ask instead of silently defaulting to forecasting; the parser
maps the user's answer back onto an intent.
"""
from __future__ import annotations

import pytest

from fews_agent.agent.project_intents import (
    intent_disambiguation_needed,
    intent_disambiguation_question,
    parse_intent_disambiguation_answer,
)


# --- intent_disambiguation_needed: the ambiguous single-half cases -------

def test_imports_only_no_signal_is_ambiguous():
    # GFS mentioned, no basin, no explicit narrowing/forecasting phrase.
    # (Prose avoids the word "only" — bare "only" is itself a narrowing
    # signal in _NARROWING_PHRASES and would correctly suppress the question.)
    assert intent_disambiguation_needed(
        "Import NOAA GFS grids for precipitation and temperature.",
        {"imports": ["GFS"]},
    ) == "imports"


def test_bare_only_is_treated_as_a_narrowing_signal():
    # "precipitation only" trips the broad "only" narrowing phrase, so the
    # request is taken as import-only and no question is asked. Documents
    # the (pre-existing, intentional) breadth of _NARROWING_PHRASES.
    assert intent_disambiguation_needed(
        "Import NOAA GFS grids, precipitation only.",
        {"imports": ["GFS"]},
    ) is None


def test_basin_only_no_signal_is_ambiguous():
    assert intent_disambiguation_needed(
        "Set up a Raven model for the Liard.",
        {"basins": [{"basin_name": "Liard", "model_adapter": "raven"}]},
    ) == "basin"


def test_basin_via_singular_slot_is_ambiguous():
    # basin_name without the canonical basins pair still counts as a half.
    assert intent_disambiguation_needed(
        "Run a model for the Athabasca.",
        {"basin_name": "Athabasca"},
    ) == "basin"


# --- intent_disambiguation_needed: the UN-ambiguous cases (no question) ---

def test_both_halves_is_not_ambiguous():
    assert intent_disambiguation_needed(
        "Import GFS and run Raven on the Liard.",
        {"imports": ["GFS"], "basins": [{"basin_name": "Liard"}]},
    ) is None


def test_neither_half_is_not_ambiguous():
    # No content yet → normal slot elicitation, not this gate.
    assert intent_disambiguation_needed("Hi, I want to build a config.", {}) is None
    assert intent_disambiguation_needed("anything", None) is None


def test_explicit_narrowing_phrase_suppresses_question():
    assert intent_disambiguation_needed(
        "Import GFS grids, no basin model.", {"imports": ["GFS"]},
    ) is None


def test_data_viewer_phrase_is_a_narrowing_signal():
    # "Data Viewer" / interpolation prose already reads as a data pipeline.
    assert intent_disambiguation_needed(
        "Import GFS and interpolate to stations for the Data Viewer.",
        {"imports": ["GFS"]},
    ) is None


def test_explicit_forecasting_phrase_suppresses_question():
    assert intent_disambiguation_needed(
        "Build a full forecasting project; start with a GFS import.",
        {"imports": ["GFS"]},
    ) is None
    assert intent_disambiguation_needed(
        "I want forecasting for the Liard.",
        {"basin_name": "Liard"},
    ) is None


# Representative turn-1 prose from the on-disk demo fixtures (gitignored, so
# absent on a fresh clone — this pins the behaviour durably). Every one
# carries a narrowing signal, a forecasting signal, or both halves, so the
# gate must stay silent. A regression here would mean the gate started
# firing on already-recorded conversations and changed their build output.
@pytest.mark.parametrize("prose,slots", [
    ("Configure a NOAA GFS import for the Gulf of Guinea with precipitation "
     "and temperature, and visualize the grids in the Spatial Display. "
     "No basin model.", {"imports": ["GFS"]}),
    ("Import NOAA GFS grids, precipitation only. No basin model.",
     {"imports": ["GFS"]}),
    ("Configure a NOAA GFS import for the Gulf of Guinea with wind speed, "
     "wind direction and mean sea level pressure. Interpolate to stations "
     "for the Data Viewer.", {"imports": ["GFS"]}),
    ("Build a forecasting project for the Liard basin: import GFS grids, "
     "run Raven.", {"imports": ["GFS"], "basins": [{"basin_name": "Liard"}]}),
])
def test_known_fixture_turn1_prose_skips_the_gate(prose, slots):
    assert intent_disambiguation_needed(prose, slots) is None


# --- intent_disambiguation_question: wording per half --------------------

def test_question_wording_differs_by_half():
    q_imp = intent_disambiguation_question("imports")
    q_bas = intent_disambiguation_question("basin")
    assert "no model" in q_imp and "basin + model adapter" in q_imp
    assert "no data imports" in q_bas and "wire in NWP imports" in q_bas
    # Both offer the same either/or shorthands.
    for q in (q_imp, q_bas):
        assert "(a)" in q and "(b)" in q


# --- parse_intent_disambiguation_answer ----------------------------------

@pytest.mark.parametrize("text", ["a", "A", "a)", "(a)", "a.", "option a"])
def test_parse_bare_a_is_import_only(text):
    assert parse_intent_disambiguation_answer(text) == "build_data_import_only"


@pytest.mark.parametrize("text", ["b", "B", "b)", "(b)", "option b"])
def test_parse_bare_b_is_forecasting(text):
    assert parse_intent_disambiguation_answer(text) == "build_forecasting_project"


def test_parse_import_phrasings():
    for t in ["imports only", "just imports", "data only", "no model please"]:
        assert parse_intent_disambiguation_answer(t) == "build_data_import_only"


def test_parse_basin_phrasings():
    for t in ["model only", "just the basin", "no imports for now"]:
        assert parse_intent_disambiguation_answer(t) == "build_basin_model_only"


def test_parse_forecasting_phrasings():
    for t in ["the full project", "forecasting", "everything", "both"]:
        assert parse_intent_disambiguation_answer(t) == "build_forecasting_project"


def test_parse_leading_a_with_full_project_reads_as_forecasting():
    # "a full project" — the 'a' is an article, not the shorthand; the
    # phrase wins so the user gets the full build they described.
    assert parse_intent_disambiguation_answer(
        "a full project") == "build_forecasting_project"


def test_parse_unclear_answer_is_none():
    for t in ["", "   ", "hmm not sure", "what do you recommend?"]:
        assert parse_intent_disambiguation_answer(t) is None
