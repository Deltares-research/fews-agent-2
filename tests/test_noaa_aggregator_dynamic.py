"""wf_import_noaa_grids -- the ImportNOAAGrids aggregator workflow's
<activity> list is now dynamic (scoped to the project's actual NOAA
sources), not a hardcoded GFS+NAM+SREF triple.

Colleague-reported: a GFS-only project's ImportNOAAGrids.xml referenced
ImportNAMGrids/ImportSREFGrids workflows that never existed in that
project -- confirmed unresolved by the build's own semantic check. Root
cause: the pattern's activity list was hardcoded; the resolver appended it
whenever ANY of GFS/NAM/SREF was imported, not just when the sibling
workflows it references were ALSO present.
"""
from __future__ import annotations

from pathlib import Path

from fews_agent.agent.blueprint import Blueprint, PatternRef, expand
from fews_agent.agent.project_chat import build_pattern_catalog
from fews_agent.agent import turn_engine as TE
from fews_agent.validation.xsd import validate_xsd

REPO_ROOT = Path(__file__).resolve().parents[1]
PATTERNS_ROOT = REPO_ROOT / "fews_agent" / "patterns"
PATTERN = "auto/wf_import/noaa_grids"


def _render(noaa_sources=None):
    inst = {"template_name": "ImportNOAAGrids"}
    if noaa_sources is not None:
        inst["noaa_sources"] = noaa_sources
    bp = Blueprint(name="t", output_root=Path("out"),
                   patterns=[PatternRef(pattern=PATTERN, instances=[inst])])
    res = expand(bp, PATTERNS_ROOT)
    assert not res.errors, res.errors
    return res.rendered_files[0].content


# --- pattern-level: activity list follows noaa_sources ----------------------

def test_default_reproduces_all_three_sources_in_canonical_order():
    xml = _render()
    ok, msg = validate_xsd(xml.encode("utf-8"))
    assert ok, msg
    assert xml.count("<activity>") == 3
    assert xml.index("ImportGFSGrids") < xml.index("ImportNAMGrids") < xml.index("ImportSREFGrids")


def test_single_source_emits_one_activity_only():
    xml = _render(["GFS"])
    ok, msg = validate_xsd(xml.encode("utf-8"))
    assert ok, msg
    assert xml.count("<activity>") == 1
    assert "ImportGFSGrids" in xml
    assert "ImportNAMGrids" not in xml
    assert "ImportSREFGrids" not in xml


def test_two_sources_emits_two_activities_in_request_order():
    xml = _render(["NAM", "SREF"])
    assert xml.count("<activity>") == 2
    assert "ImportGFSGrids" not in xml
    assert "ImportNAMGrids" in xml
    assert "ImportSREFGrids" in xml


# --- resolver: scopes noaa_sources to what's actually imported --------------

def _resolved_agg_instance(imports):
    catalog = build_pattern_catalog(PATTERNS_ROOT)
    st = {"slots": {"imports": imports}, "intent": "build_data_import_only"}
    TE.resolve_patterns(st, catalog)
    agg = next((p for p in st["patterns"] if p["pattern"] == PATTERN), None)
    return agg["instances"][0] if agg else None


def test_resolver_omits_aggregator_for_a_single_noaa_source():
    # A single NOAA source doesn't get the aggregator at all -- its only
    # value is bundling MULTIPLE workflows; wrapping one real workflow in
    # another that does nothing else is exactly the redundant file a
    # colleague flagged in review. ImportGFSGrids.xml already runs on its
    # own without it.
    inst = _resolved_agg_instance(["GFS"])
    assert inst is None


def test_resolver_scopes_to_present_sources_canonical_order():
    # HRDPS isn't a NOAA source; only GFS/SREF should land in noaa_sources,
    # in canonical (not request) order. Two sources -- the aggregator IS
    # warranted here.
    inst = _resolved_agg_instance(["SREF", "HRDPS", "GFS"])
    assert inst is not None
    assert inst["noaa_sources"] == ["GFS", "SREF"]


def test_resolver_omits_aggregator_when_no_noaa_source_present():
    inst = _resolved_agg_instance(["HRDPS"])
    assert inst is None
