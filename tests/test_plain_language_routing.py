"""The agent talks in plain language; /help is where commands live.

Configurator feedback: the replies kept teaching syntax ("/coordinates",
"/build") instead of just describing the action. Two things have to hold for
that to be safe:

  1. the deterministic guidance must never advertise a slash command, and
  2. every action it describes must actually work when said in plain English —
     otherwise removing the command hints strands the user.

The command catalogue itself stays discoverable via ``/help``.
"""
from __future__ import annotations

import pytest

from fews_agent.agent import modules as M
from fews_agent.agent import turn_engine as TE
from fews_agent.agent.extractor import deterministic_build_op
from fews_agent.agent.project_intents import detect_coordinates_request


# --- 1. the deterministic guidance suggests no commands -------------------

_SLASHES = ("/build", "/coordinates", "/list", "/vars", "/set", "/add",
            "/remove", "/done", "/phases", "/module")


@pytest.mark.parametrize("key", [m.key for m in M.list_modules()])
def test_next_step_hint_never_suggests_a_slash_command(key):
    mod = M.get_module(key)
    # Walk a few plausible states so every branch of the hint is exercised.
    for slots in (
        {},
        {"imports": ["GFS"]},
        {"imports": ["GFS"], "data_types": ["precipitation"]},
        {"imports": ["GFS"], "wants_visualization": True},
        {"geoDatum": "WGS 1984"},
        {"imports": ["GFS"], "wants_visualization": True,
         "forecast_horizon_hours": 168},
    ):
        hint = TE._next_step_hint({"slots": slots, "current_module": key}, mod)
        for cmd in _SLASHES:
            assert cmd not in hint, f"{key} hint suggests {cmd}: {hint!r}"


# --- 2. what the guidance describes must work in plain language -----------

@pytest.mark.parametrize("phrase", [
    "build it", "build", "generate it", "go ahead and build",
    "build what you have", "run the build",
])
def test_plain_build_is_recognised(phrase):
    assert deterministic_build_op(phrase)


@pytest.mark.parametrize("phrase", [
    "lets build the import module",   # module ENTRY, not a build action
    "build a forecasting project",    # whole-project description
])
def test_build_detector_does_not_hijack_module_entry(phrase):
    assert not deterministic_build_op(phrase)


@pytest.mark.parametrize("phrase", [
    "set the map area", "set GFS's map area", "i want to set coordinates",
    "define the grid extent", "change the bounding box",
    "what area should it cover", "set its area",
])
def test_plain_coordinates_request_is_recognised(phrase):
    assert detect_coordinates_request(phrase)


@pytest.mark.parametrize("phrase", [
    "add GFS", "the Gulf of Guinea", "use precipitation",
    "remove temperature", "build it",
])
def test_coordinates_detector_is_conservative(phrase):
    # Naming a region must NOT open the grid-geometry subwindow.
    assert not detect_coordinates_request(phrase)


# --- 3. commands remain discoverable in /help -----------------------------

def test_help_still_lists_the_commands():
    from fews_agent.agent.project_intents import compose_help_reply
    help_text = compose_help_reply("help")
    for cmd in ("/vars", "/coordinates", "/build", "/add", "/remove", "/help"):
        assert cmd in help_text, f"{cmd} missing from /help"
