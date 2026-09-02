"""auto/gfs/deterministic's idMap -- generated from its own `parameters`,
not a separate bundled standard.

Regression coverage for the colleague-reported bug: PA.nwp/WS10.nwp were
configured in a real generated import with ZERO idMap backing (the vocab
advertised phrases the bundled idImportGFS.yaml never mapped). The fix:
`external` now lives on each parameter/vocabulary row, and the pattern
emits its own `- schema: IdMap` output via the shared
_partials/idmap_from_parameters.yaml.j2 macro -- so a row can never
advertise an id without idMap coverage, by construction. `wind speed`/
`wind direction`/`relative humidity`/`humidity` were dropped from the
vocabulary rather than given a fabricated external name.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from lxml import etree

from fews_agent.agent.blueprint import Blueprint, PatternRef, expand
from fews_agent.agent.project_chat import build_pattern_catalog
from fews_agent.validation.xsd import validate_xsd

REPO_ROOT = Path(__file__).resolve().parents[1]
PATTERNS_ROOT = REPO_ROOT / "fews_agent" / "patterns"
PATTERN = "auto/gfs/deterministic"


def _render(inst=None):
    bp = Blueprint(
        name="gfs-det-test", output_root=Path("out"),
        patterns=[PatternRef(pattern=PATTERN, instances=[inst or {"nwp_name": "GFS"}])],
    )
    res = expand(bp, PATTERNS_ROOT)
    assert not res.errors, res.errors
    return {rf.relpath.replace("\\", "/"): rf.content for rf in res.rendered_files}


def _idmap_pairs(idmap_xml: str) -> set[tuple[str, str]]:
    root = etree.fromstring(idmap_xml.encode("utf-8"))
    ns = {"f": "http://www.wldelft.nl/fews"}
    return {
        (el.get("internal"), el.get("external"))
        for el in root.findall("f:parameter", ns)
    }


def _vocab():
    catalog = build_pattern_catalog(PATTERNS_ROOT)
    return next(p for p in catalog if p.path == PATTERN).data_type_vocabulary


def test_idmap_is_self_generated_and_xsd_valid():
    files = _render()
    idmap = files["IdMapFiles/NOAA/IdImportGFS.xml"]
    ok, msg = validate_xsd(idmap.encode("utf-8"))
    assert ok, msg


def test_default_parameters_match_tutorial_idmap_content():
    # Order-agnostic: the tutorial's original bundled yaml interleaved rows
    # by naming era ([PC-long, TA-long, PC-short, TA-short]); the
    # self-generated idMap groups by parameter instead. Content must be
    # identical; row order is a documented, harmless divergence (same class
    # as the two pre-existing byte-divergent tutorial files).
    idmap = _render()["IdMapFiles/NOAA/IdImportGFS.xml"]
    assert _idmap_pairs(idmap) == {
        ("PC.nwp", "Total_precipitation_surface_6_Hour_Accumulation"),
        ("PC.nwp", "apcpsfc"),
        ("TA.nwp", "Temperature_height_above_ground"),
        ("TA.nwp", "tmp2m"),
    }


def test_enableOneToOneMapping_is_not_emitted():
    # The original bundled idMap never set this (unlike gfs/gribfilter's
    # own, which deliberately does) -- the macro must default to omitting
    # it, not silently opting every caller into strict 1:1 validation.
    idmap = _render()["IdMapFiles/NOAA/IdImportGFS.xml"]
    assert "enableOneToOneMapping" not in idmap


def test_dropped_phrases_are_absent_not_fabricated():
    vocab = _vocab()
    for phrase in ("wind speed", "wind direction", "relative humidity", "humidity"):
        assert phrase not in vocab, (
            f"{phrase!r} should have been dropped (no verified external "
            f"name), not silently offered"
        )


@pytest.mark.parametrize("phrase", [
    "precipitation", "precip", "temperature", "air temperature", "temp",
    "mean sea level pressure", "mslp", "pressure",
    "dewpoint temperature", "dew point", "dewpoint",
])
def test_every_vocabulary_phrase_is_idmap_backed(phrase):
    # The regression class the colleague hit: a phrase resolves to a
    # parameterId the idMap never maps, so FEWS can never actually receive
    # data for it. For every phrase still offered, rendering GFS with ONLY
    # that phrase selected must produce an idMap entry for its id.
    vocab = _vocab()
    row = vocab[phrase]
    files = _render({"nwp_name": "GFS", "parameters": [row],
                      "contribute_parameters": True})
    idmap = files["IdMapFiles/NOAA/IdImportGFS.xml"]
    pairs = _idmap_pairs(idmap)
    backed_ids = {internal for internal, _external in pairs}
    assert row["id"] in backed_ids, (
        f"{phrase!r} -> {row['id']} has no idMap entry: {pairs}"
    )
