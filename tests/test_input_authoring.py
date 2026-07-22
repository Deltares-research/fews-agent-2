"""N1 — the agent writes input CSVs from prose (`write_input_file` op).

The human-test gap verbatim: the agent collected station A (1,1), then said
"I can't write or attach the CSV file itself here" — and the pasted fallback
text used headers the ingest doesn't read. Now the op validates rows against
the SAME alias table the CSV ingest uses and writes/upserts inputs/<file>,
so a written file is ingestible by construction.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from fews_agent.agent import turn_engine as TE
from fews_agent.agent.csv_ingest import ingest_csv
from fews_agent.agent.input_files import (
    build_csv,
    merge_rows,
    validate_rows,
    write_input_file,
)
from fews_agent.agent.llm_turn import run_llm_turn
from fews_agent.agent.patch_ops import apply_patch
from fews_agent.agent.project_chat import build_pattern_catalog

REPO = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def catalog():
    return build_pattern_catalog(REPO / "fews_agent" / "patterns")


@pytest.fixture()
def state(catalog):
    st = {"slots": {"imports": ["GFS"]}, "intent": "build_data_import_only"}
    TE.resolve_patterns(st, catalog)
    return st


class _Resp:
    def __init__(self, data):
        self.data = data


class _Scripted:
    def __init__(self, *payloads):
        self.payloads = list(payloads)
        self.calls = []

    def generate_json(self, system, user, schema):
        self.calls.append({"system": system, "user": user})
        if not self.payloads:
            raise RuntimeError("script exhausted")
        return _Resp(self.payloads.pop(0))


# --- validation (pure) ------------------------------------------------------

def test_location_rows_accept_lat_lon_aliases():
    clean, errors = validate_rows(
        "locations.csv", [{"id": "A", "name": "A", "lat": 1.0, "lon": 2.0}])
    assert errors == []
    assert clean[0]["y"] == 1.0 and clean[0]["x"] == 2.0


def test_location_row_out_of_range_rejects_batch():
    clean, errors = validate_rows(
        "locations.csv",
        [{"id": "A", "lat": 91.0, "lon": 0.0},
         {"id": "B", "lat": 10.0, "lon": 0.0}])
    assert clean == []                       # all-or-nothing
    assert any("out of range" in e for e in errors)


def test_location_row_missing_coords_rejected():
    _, errors = validate_rows("locations.csv", [{"id": "A", "name": "A"}])
    assert any("missing required" in e for e in errors)


def test_duplicate_ids_in_batch_rejected():
    _, errors = validate_rows(
        "locations.csv",
        [{"id": "A", "lat": 1, "lon": 1}, {"id": "A", "lat": 2, "lon": 2}])
    assert any("duplicate id" in e for e in errors)


def test_unsupported_file_rejected():
    _, errors = validate_rows("secrets.csv", [{"id": "x"}])
    assert any("unsupported" in e for e in errors)


def test_parameter_rows_need_only_id():
    clean, errors = validate_rows(
        "parameters.csv", [{"id": "Q", "unit": "m3/s"}])
    assert errors == [] and clean[0]["id"] == "Q"


# --- merge + round-trip through the REAL ingest -----------------------------

def test_merge_upserts_by_id():
    rows, added, updated = merge_rows(
        [{"id": "A", "name": "Old", "x": 1.0, "y": 1.0}],
        [{"id": "A", "name": "New"}, {"id": "B", "x": 2.0, "y": 2.0}])
    assert (added, updated) == (1, 1)
    assert rows[0]["name"] == "New" and rows[0]["x"] == 1.0  # update keeps x


def test_written_file_is_ingestible(tmp_path):
    """The whole point: what we write, the build's CSV ingest can read."""
    write_input_file(tmp_path, "locations.csv",
                     [{"id": "A", "name": "Alpha", "y": 52.1, "x": 4.4}])
    result = ingest_csv(tmp_path / "locations.csv")
    assert not result.errors
    text = (tmp_path / "locations.csv").read_text(encoding="utf-8")
    assert text.splitlines()[0].startswith("id,name,lat,lon")


def test_existing_unknown_columns_preserved(tmp_path):
    (tmp_path / "locations.csv").write_text(
        "id,name,lat,lon,Basin\nA,Alpha,1.0,2.0,Liard\n", encoding="utf-8")
    write_input_file(tmp_path, "locations.csv",
                     [{"id": "B", "y": 3.0, "x": 4.0}])
    text = (tmp_path / "locations.csv").read_text(encoding="utf-8")
    assert "Basin" in text.splitlines()[0]      # configurator column survives
    assert "Liard" in text


# --- the op through patch_ops + llm_turn ------------------------------------

def test_op_validates_and_defers_write(state, catalog):
    res = apply_patch(state, [{"op": "write_input_file",
                               "file": "locations.csv",
                               "rows": [{"id": "A", "lat": 1, "lon": 1}]}],
                      catalog)
    assert res.dropped == []
    assert res.input_writes and res.input_writes[0][0] == "locations.csv"


def test_op_bad_rows_dropped_loudly(state, catalog):
    res = apply_patch(state, [{"op": "write_input_file",
                               "file": "locations.csv",
                               "rows": [{"id": "A", "lat": 999, "lon": 0}]}],
                      catalog)
    assert res.input_writes == []
    assert any("out of range" in d for d in res.dropped)


def test_llm_turn_writes_the_file_and_confirms(state, catalog, tmp_path):
    """The human-test scenario end-to-end: station given in chat → file on
    disk with ingest-ready headers → grey note + honest reply."""
    prov = _Scripted({"reply": "Station A saved to locations.csv.",
                      "patch": [{"op": "write_input_file",
                                 "file": "locations.csv",
                                 "rows": [{"id": "A", "name": "A",
                                           "lat": 1.0, "lon": 1.0}]}]})
    res = run_llm_turn(state, 'location name "A", coordinates x=1, y=1',
                       catalog, provider=prov, inputs_dir=tmp_path)
    assert (tmp_path / "locations.csv").is_file()
    assert res.input_files_written == ["locations.csv"]
    assert res.kind == "edit"
    assert "locations.csv" in res.confirmation      # the grey note
    # Second station merges — no clobber.
    prov2 = _Scripted({"reply": "Added station B.",
                       "patch": [{"op": "write_input_file",
                                  "file": "locations.csv",
                                  "rows": [{"id": "B", "lat": 2.0,
                                            "lon": 2.0}]}]})
    run_llm_turn(state, "station B at 2,2", catalog, provider=prov2,
                 inputs_dir=tmp_path)
    text = (tmp_path / "locations.csv").read_text(encoding="utf-8")
    assert "A" in text and "B" in text


def test_llm_turn_without_inputs_dir_repairs_the_claim(state, catalog):
    """No inputs dir → the write fails → the success-claiming draft is
    rewritten (B1 covers the new op too)."""
    prov = _Scripted(
        {"reply": "Station A saved to locations.csv.",
         "patch": [{"op": "write_input_file", "file": "locations.csv",
                    "rows": [{"id": "A", "lat": 1, "lon": 1}]}]},
        {"reply": "I couldn't save station A — this session has no inputs "
                  "folder."},
    )
    res = run_llm_turn(state, "station A at 1,1", catalog, provider=prov,
                       inputs_dir=None)
    assert "saved to locations.csv." not in res.reply.split("[!]")[0]
    assert "couldn't save" in res.reply
    assert res.input_files_written == []


def test_delete_row_by_id(tmp_path):
    write_input_file(tmp_path, "locations.csv",
                     [{"id": "A", "y": 1.0, "x": 1.0},
                      {"id": "B", "y": 2.0, "x": 2.0}])
    note = write_input_file(tmp_path, "locations.csv", [],
                            delete_ids=["A"])
    assert "removed A" in note
    text = (tmp_path / "locations.csv").read_text(encoding="utf-8")
    assert "B" in text and "\nA," not in text


def test_delete_missing_id_reported_not_silent(tmp_path):
    write_input_file(tmp_path, "locations.csv",
                     [{"id": "A", "y": 1.0, "x": 1.0}])
    note = write_input_file(tmp_path, "locations.csv", [],
                            delete_ids=["Z"])
    assert "Not found" in note and "Z" in note


def test_pure_delete_op_needs_no_rows(state, catalog):
    res = apply_patch(state, [{"op": "write_input_file",
                               "file": "locations.csv",
                               "delete_ids": ["A"]}], catalog)
    assert res.dropped == []
    assert res.input_writes == [("locations.csv", [], ["A"])]


def test_llm_turn_delete_flows_through(state, catalog, tmp_path):
    write_input_file(tmp_path, "locations.csv",
                     [{"id": "A", "y": 1.0, "x": 1.0}])
    prov = _Scripted({"reply": "Removed station A.",
                      "patch": [{"op": "write_input_file",
                                 "file": "locations.csv",
                                 "delete_ids": ["A"]}]})
    res = run_llm_turn(state, "remove station A", catalog, provider=prov,
                       inputs_dir=tmp_path)
    assert res.input_files_written == ["locations.csv"]
    text = (tmp_path / "locations.csv").read_text(encoding="utf-8")
    assert "A" not in text.splitlines()[-1] or len(text.splitlines()) == 1


def test_chatter_shows_diff_for_agent_csv_edit(tmp_path, monkeypatch):
    """End-to-end: agent writes a station, then edits the file — the second
    turn's reply carries a ```diff of the pre-existing CSV."""
    from app import chatter as C
    from app import project_git
    if not project_git.available():
        pytest.skip("git not on PATH")
    monkeypatch.setattr(C, "check_ollama_for_model", lambda *a, **k: None)

    payloads = [
        {"reply": "Station A saved.",
         "patch": [{"op": "write_input_file", "file": "locations.csv",
                    "rows": [{"id": "A", "lat": 1.0, "lon": 1.0}]}]},
        {"reply": "Station B added.",
         "patch": [{"op": "write_input_file", "file": "locations.csv",
                    "rows": [{"id": "B", "lat": 2.0, "lon": 2.0}]}]},
    ]

    class _Prov:
        def generate_json(self, system, user, schema):
            return _Resp(payloads.pop(0))

    monkeypatch.setattr(C, "get_provider", lambda *a, **k: _Prov())
    s = C.ChatSession(project_name="csvdiff", session_dir=tmp_path,
                      username="t")
    first = s.send("station A at 1,1")
    assert "```diff" not in first.agent_message      # first write: new file
    second = s.send("station B at 2,2")
    assert "```diff" in second.agent_message
    assert "+B" in second.agent_message


def test_gap_clears_after_the_write(state, catalog, tmp_path):
    """Writing locations.csv actually closes the build gap it was blocking."""
    from fews_agent.agent.llm_turn import gap_digest
    before = gap_digest(state, tmp_path)
    assert "locations.csv" in before
    write_input_file(tmp_path, "locations.csv",
                     [{"id": "A", "y": 1.0, "x": 1.0}])
    after = gap_digest(state, tmp_path)
    assert "required input file missing: locations.csv" not in after
