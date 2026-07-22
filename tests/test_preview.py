"""/show · /present · preview_file — render how a file WILL generate, in chat.

Previews are computed FRESH per request (pure in-memory expand, ~10 ms/file
measured) — nothing cached, nothing regenerating in the background, so a
preview can never be stale with respect to the slots. Files only the full
pipeline produces fall back to the last build on disk, labelled as such.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from fews_agent.agent import turn_engine as TE
from fews_agent.agent.preview import format_previews, preview_files
from fews_agent.agent.project_chat import build_pattern_catalog

REPO = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def catalog():
    return build_pattern_catalog(REPO / "fews_agent" / "patterns")


@pytest.fixture()
def state(catalog):
    st = {"slots": {"imports": ["GFS"], "data_types": ["precipitation"]},
          "intent": "build_data_import_only"}
    TE.resolve_patterns(st, catalog)
    return st


# --- live render ------------------------------------------------------------

def test_preview_by_instance_label_renders_fresh(state):
    previews = preview_files(state, "GFS")
    assert previews, "GFS instance should render"
    assert all(p.source == "live render" for p in previews)
    assert any("Import" in p.relpath for p in previews)
    assert all(p.xsd_ok is True for p in previews if p.relpath.endswith(".xml"))
    assert "<" in previews[0].content              # actual XML, not a stub


def test_preview_reflects_current_state_not_a_cache(state, catalog):
    """The whole point: change a setting → the very next preview shows it."""
    before = preview_files(state, "GFS")
    assert "gfs_0p50" not in " ".join(p.content for p in before)
    state["slots"].setdefault("import_overrides", {}).setdefault(
        "GFS", {})["grid_resolution"] = "0p50"
    TE.resolve_patterns(state, catalog)
    after = preview_files(state, "GFS")
    assert "gfs_0p50" in " ".join(p.content for p in after)


def test_preview_by_filename_fragment(state):
    previews = preview_files(state, "gfsgrids")
    assert previews
    assert all("ImportGFSGrids" in p.relpath for p in previews)


def test_preview_unknown_target_is_empty_and_formatted_honestly(state):
    assert preview_files(state, "Narnia") == []
    text = format_previews([], "Narnia")
    assert "Narnia" in text and "nothing to preview" in text.lower()


# --- last-build fallback ----------------------------------------------------

def test_preview_falls_back_to_last_build_on_disk(state, tmp_path):
    out = tmp_path / "generated" / "RegionConfigFiles"
    out.mkdir(parents=True)
    (out / "Topology.xml").write_text("<topology/>", encoding="utf-8")
    previews = preview_files(state, "Topology",
                             output_root=tmp_path / "generated")
    assert len(previews) == 1
    assert previews[0].source == "last build"
    assert previews[0].relpath == "RegionConfigFiles/Topology.xml"


# --- formatting -------------------------------------------------------------

def test_format_previews_fences_and_badges(state):
    text = format_previews(preview_files(state, "GFS"), "GFS")
    assert "```xml" in text
    assert "XSD-valid" in text
    assert "live render" in text


def test_format_truncates_huge_files(state):
    from fews_agent.agent.preview import MAX_CHARS, PreviewFile
    big = PreviewFile(relpath="X.xml", content="x" * (MAX_CHARS + 500),
                      xsd_ok=True, source="live render", label="X")
    text = format_previews([big], "X")
    assert "truncated" in text


# --- wiring: op signal + llm turn + slash ----------------------------------

def test_preview_op_sets_signal(state, catalog):
    from fews_agent.agent.patch_ops import apply_patch
    res = apply_patch(state, [{"op": "preview_file", "target": "GFS"}], catalog)
    assert res.preview_for == "GFS"


def test_llm_turn_appends_preview(state, catalog):
    from fews_agent.agent.llm_turn import run_llm_turn

    class _R:
        def __init__(self, d): self.data = d

    class _P:
        def generate_json(self, system, user, schema):
            return _R({"reply": "Here's the GFS import as it will generate:",
                       "patch": [{"op": "preview_file", "target": "GFS"}]})

    res = run_llm_turn(state, "show me the GFS import file", catalog,
                       provider=_P())
    assert "```xml" in res.reply
    assert "XSD-valid" in res.reply


def test_slash_show_in_the_app(tmp_path, monkeypatch):
    from app import chatter as C
    monkeypatch.setattr(C, "check_ollama_for_model", lambda *a, **k: None)

    class _Boom:
        def generate_json(self, *a, **k):
            raise AssertionError("slash /show must not call the LLM")

    monkeypatch.setattr(C, "get_provider", lambda *a, **k: _Boom())
    s = C.ChatSession(project_name="prev", session_dir=tmp_path, username="t")
    s.send("/module processing")
    s.send("/add GFS")
    res = s.send("/show GFS")
    assert "```xml" in res.agent_message
    assert "XSD-valid" in res.agent_message
    # /present is an alias
    res2 = s.send("/present GFS")
    assert "```xml" in res2.agent_message
