"""Streaming replies + per-session LLM telemetry.

The turn's response is one JSON object, so raw streaming would show the user
braces and op names — ``ReplyStreamExtractor`` yields only the ``"reply"``
string's content as it arrives. Telemetry: every provider call's usage +
latency accumulates on ``state["llm_usage"]`` (persisted with the session).
"""
from __future__ import annotations

from pathlib import Path

import pytest

from fews_agent.agent import turn_engine as TE
from fews_agent.agent.llm_turn import run_llm_turn
from fews_agent.agent.project_chat import build_pattern_catalog
from fews_agent.agent.reply_stream import ReplyStreamExtractor

REPO = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def catalog():
    return build_pattern_catalog(REPO / "fews_agent" / "patterns")


@pytest.fixture()
def state(catalog):
    st = {"slots": {}, "intent": "build_data_import_only"}
    TE.resolve_patterns(st, catalog)
    return st


# --- the extractor (pure) ---------------------------------------------------

def _feed_all(chunks):
    ex = ReplyStreamExtractor()
    return "".join(ex.feed(c) for c in chunks)


def test_extractor_yields_only_the_reply_text():
    out = _feed_all(['{"reply": "Added GFS.", "patch": []}'])
    assert out == "Added GFS."


def test_extractor_survives_chunk_boundaries_everywhere():
    full = '{"reply": "Added GFS. Want more?", "patch": [{"op": "none"}]}'
    for size in (1, 2, 3, 7):
        chunks = [full[i:i + size] for i in range(0, len(full), size)]
        assert _feed_all(chunks) == "Added GFS. Want more?", f"size={size}"


def test_extractor_unescapes():
    out = _feed_all(['{"reply": "line1\\nsaid \\"hi\\" \\u00e9", "patch": []}'])
    assert out == 'line1\nsaid "hi" é'


def test_extractor_ignores_text_before_the_key():
    out = _feed_all(['{"patch": [], "reply": "After."}'])
    assert out == "After."


# --- telemetry --------------------------------------------------------------

class _Resp:
    def __init__(self, data, usage=None):
        self.data = data
        self.usage = usage


def test_usage_accumulates_on_state(state, catalog):
    class _P:
        def generate_json(self, system, user, schema):
            return _Resp({"reply": "ok", "patch": []},
                         usage={"prompt_tokens": 100, "completion_tokens": 20,
                                "total_tokens": 120})

    run_llm_turn(state, "hello", catalog, provider=_P())
    run_llm_turn(state, "hello again", catalog, provider=_P())
    u = state["llm_usage"]
    assert u["prompt_tokens"] == 200
    assert u["completion_tokens"] == 40
    assert u["calls"] == 2
    assert u["seconds"] >= 0


def test_usage_without_provider_usage_counts_calls(state, catalog):
    class _P:
        def generate_json(self, system, user, schema):
            return _Resp({"reply": "ok", "patch": []})

    run_llm_turn(state, "hi", catalog, provider=_P())
    assert state["llm_usage"]["calls"] == 1
    assert state["llm_usage"]["prompt_tokens"] == 0


# --- streaming callback routing --------------------------------------------

def test_callback_reaches_a_streaming_capable_provider(state, catalog):
    got = []

    class _Streamy:
        def generate_json(self, system, user, schema, on_delta=None):
            if on_delta:
                on_delta("Added ")
                on_delta("GFS.")
            return _Resp({"reply": "Added GFS.",
                          "patch": [{"op": "add_import", "name": "GFS"}]})

    res = run_llm_turn(state, "add GFS", catalog, provider=_Streamy(),
                       on_reply_delta=got.append)
    assert got == ["Added ", "GFS."]
    assert res.kind == "edit"


def test_callback_skipped_for_plain_providers(state, catalog):
    """A provider whose generate_json has no on_delta parameter must still
    work — the callback is simply not offered to it."""
    class _Plain:
        def generate_json(self, system, user, schema):
            return _Resp({"reply": "ok", "patch": []})

    res = run_llm_turn(state, "hello", catalog, provider=_Plain(),
                       on_reply_delta=lambda t: None)
    assert res.reply == "ok"
