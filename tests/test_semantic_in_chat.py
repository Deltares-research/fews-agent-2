"""Semantic (cross-file ID reference) results surfaced to the chat agent.

Two layers:
  - unit: ``build_digest`` renders the semantic summary fields into the
    LLM's build digest (capped examples, zero-unresolved wording).
  - integration: the FULL build path (``build_from_blueprint``) actually
    runs the semantic pass over the models kept from the render sites
    and puts the fields in the returned summary — without disturbing the
    small-project oracle (29 files, all XSD-valid).
"""
from __future__ import annotations

from pathlib import Path

import pytest
from rich.console import Console

from fews_agent.agent.llm_turn import build_digest

REPO_ROOT = Path(__file__).resolve().parents[1]
PATTERNS_ROOT = REPO_ROOT / "fews_agent" / "patterns"
SMALL_BLUEPRINT = (
    REPO_ROOT / "projects" / "small" / "small_2026-05-07_120000"
    / "project.yaml"
)


# ---------------------------------------------------------------------------
# Unit: build_digest formatting
# ---------------------------------------------------------------------------

def _digest_for(summary: dict) -> str:
    return build_digest({"last_build_summary": summary})


def test_digest_reports_unresolved_refs_capped_at_eight():
    entries = [
        f"MissingId{i} (idMapId) referenced by ModuleConfigFiles/F{i}.xml"
        for i in range(12)
    ]
    digest = _digest_for({
        "files_total": 30,
        "files_xsd_ok": 29,
        "files_xml": 29,
        "semantic_refs": 250,
        "semantic_unresolved": entries,
        "semantic_unresolved_count": 12,
    })
    assert "cross-file references: 250 checked, 12 unresolved" in digest
    # The explanation the model relays to the configurator.
    assert "used but never declared" in digest
    # Examples are capped at 8 even though 12 were supplied.
    assert digest.count("  unresolved:") == 8
    assert "MissingId0 (idMapId)" in digest
    assert "MissingId7" in digest
    assert "MissingId8" not in digest


def test_digest_all_resolve_line_when_zero_unresolved():
    digest = _digest_for({
        "files_total": 29,
        "semantic_refs": 180,
        "semantic_unresolved": [],
        "semantic_unresolved_count": 0,
    })
    assert "cross-file references: all resolve" in digest
    assert "unresolved (" not in digest


def test_digest_omits_semantic_lines_when_fields_absent():
    # Scoped builds (and a crashed pass) carry no semantic fields —
    # the digest must not mention cross-file references at all.
    digest = _digest_for({"files_total": 8, "files_xsd_ok": 8})
    assert "cross-file references" not in digest


# ---------------------------------------------------------------------------
# Integration: the full build populates the semantic summary fields
# ---------------------------------------------------------------------------

@pytest.mark.skipif(
    not SMALL_BLUEPRINT.is_file(),
    reason="projects/ fixtures are gitignored; small oracle absent",
)
def test_full_build_summary_carries_semantic_fields():
    from runners.agent.build_from_blueprint import build_from_blueprint

    summary = build_from_blueprint(
        blueprint_path=SMALL_BLUEPRINT,
        pattern_root=PATTERNS_ROOT,
        console=Console(quiet=True),
    )
    # The small-project oracle must be undisturbed by the semantic pass.
    # (43 files on this branch — the documented 29 predates the extra
    # bundled standard_inputs; verified identical pre/post this change.
    # Was 47, then 45: modifierTypes/productsFile/filtersFile/
    # spatialDisplayFile are now correctly dropped for a project with no
    # WSC/RDPS/GDPS/REPS content to scope them to — see
    # _MODULE_INSTANCE_TRIMMED_SPECS in build_from_blueprint.py, and the
    # SpatialDisplay whole-file-skip next to it.)
    assert summary["ok"] is True, summary.get("errors")
    assert summary["files_total"] == 43

    # Semantic fields present and sane. Don't pin exact counts —
    # content evolves with the pattern library; the digest test above
    # pins the formatting.
    assert summary["semantic_refs"] > 0
    assert isinstance(summary["semantic_unresolved"], list)
    assert summary["semantic_unresolved_count"] == len(
        summary["semantic_unresolved"]
    ) or summary["semantic_unresolved_count"] > 40  # list capped at 40
    for line in summary["semantic_unresolved"]:
        assert "referenced by" in line
