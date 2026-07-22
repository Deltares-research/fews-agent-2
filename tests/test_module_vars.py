"""`/vars` — discoverability of the ~291 defaulted pattern variables.

Across the library only ~45 of ~336 pattern variables are required; the rest
carry an explicit default (``blueprint._apply_defaults``: instance value →
default → loud error when a required one is missing). That is correct — the
agent should not interrogate the user about 291 knobs — but it left them
undiscoverable: ``/set`` existed with no way to learn which names were valid,
what the current value was, or whether it came from the user or the default.

``/vars`` closes that. These tests pin the two questions it answers and the
user-set vs default distinction.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from fews_agent.agent import turn_engine as TE
from fews_agent.agent.project_chat import build_pattern_catalog

REPO = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def catalog():
    return build_pattern_catalog(REPO / "fews_agent" / "patterns")


@pytest.fixture()
def state(catalog):
    st = {
        "slots": {"imports": ["GFS"], "data_types": ["precipitation"]},
        "current_module": "processing",
        "intent": "build_data_import_only",
    }
    TE.resolve_patterns(st, catalog)
    return st


# --- the library-wide invariant this feature rests on ---------------------

def test_every_optional_pattern_variable_has_a_default(catalog):
    """If an optional variable had no default, omitting it would render an
    undefined value instead of a known-good one — the whole "the agent only
    asks for required vars" design depends on this holding."""
    offenders = []
    for entry in catalog:
        for name, spec in (getattr(entry, "variables", {}) or {}).items():
            if not isinstance(spec, dict):
                continue
            if not spec.get("required") and "default" not in spec:
                offenders.append(f"{entry.path}:{name}")
    assert offenders == [], f"optional vars without a default: {offenders}"


# --- bare /vars: what's in the project ------------------------------------

def test_bare_vars_lists_the_instances(state, catalog):
    text = TE.module_vars_text(state, catalog, None)
    assert "Modules in this project" in text
    assert "GFS" in text
    # It points at the detail view in PLAIN LANGUAGE (the agent doesn't teach
    # slash syntax) — only /help is allowed to name commands.
    assert "what can I change" in text
    assert "/vars" not in text
    assert "/build" not in text


# --- /vars <name>: what can I tune ----------------------------------------

def test_vars_for_instance_shows_value_and_source(state, catalog):
    text = TE.module_vars_text(state, catalog, "GFS")
    # The variable the user supplied, marked as theirs...
    assert "`nwp_name`" in text
    assert "you set this" in text
    # ...and an untouched one, marked as a default with its effective value.
    assert "`grid_resolution`" in text
    assert "0p25" in text
    assert "default" in text
    # And it tells them how to change one — in plain language, not syntax.
    assert "just say it" in text
    assert "make GFS half-degree" in text
    assert "/set" not in text


def test_vars_is_case_insensitive_on_the_label(state, catalog):
    assert "nwp_name" in TE.module_vars_text(state, catalog, "gfs")


def test_vars_for_unknown_instance_lists_what_exists(state, catalog):
    text = TE.module_vars_text(state, catalog, "NOPE")
    assert "NOPE" in text
    assert "GFS" in text          # tells them what IS available
    assert "`nwp_name`" not in text  # ...and doesn't invent a variable table


def test_vars_reply_appends_the_next_step_hint(state, catalog):
    reply = TE.module_vars_reply(state, catalog, "GFS")
    assert "`nwp_name`" in reply
    assert "?" in reply  # the proactive follow-up question rides along


def test_list_reply_is_the_bare_vars_overview(state, catalog):
    """`list`/`show` are aliases, not a second overlapping concept."""
    assert (
        TE.module_list_reply(state, catalog)
        == TE.module_vars_reply(state, catalog, None)
    )
