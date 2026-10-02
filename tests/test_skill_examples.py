"""Gauntlet-check XML under .cursor/skills/*/examples/.

Placeholder-only directories (PLACEHOLDER.md, no XML) are skipped so
an empty open-source slot does not redden CI.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from fews_agent.validation.gauntlet import validate_xml

REPO = Path(__file__).resolve().parents[1]
SKILLS = REPO / ".cursor" / "skills"


def _example_roots() -> list[Path]:
    if not SKILLS.is_dir():
        return []
    roots: list[Path] = []
    for skill in SKILLS.iterdir():
        examples = skill / "examples"
        if not examples.is_dir():
            continue
        for child in examples.iterdir():
            if child.is_dir() and child.name != "__pycache__":
                roots.append(child)
    return roots


def _xml_files(root: Path) -> list[Path]:
    return [
        p for p in root.rglob("*.xml")
        if p.is_file() and not any(part.startswith(".") for part in p.parts)
    ]


def _is_placeholder(root: Path) -> bool:
    return (root / "PLACEHOLDER.md").is_file() and not _xml_files(root)


EXAMPLE_ROOTS = _example_roots()


@pytest.mark.skipif(not EXAMPLE_ROOTS, reason="no skill example directories")
@pytest.mark.parametrize(
    "root",
    EXAMPLE_ROOTS,
    ids=lambda p: str(p.relative_to(REPO)).replace("\\", "/"),
)
def test_skill_example_xml_passes_xsd(root: Path):
    if _is_placeholder(root):
        pytest.skip(f"placeholder-only corpus: {root.name}")
    xmls = _xml_files(root)
    if not xmls:
        pytest.skip(f"no XML in {root.name}")
    for path in xmls:
        report = validate_xml(
            path.read_text(encoding="utf-8"),
            tiers=["xsd", "conform"],
        )
        assert report.ok, (
            f"{path.relative_to(REPO)} failed: "
            f"{[d.to_dict() for d in report.errors]}"
        )
