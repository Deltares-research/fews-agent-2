"""Every SKILL.md parses and every referenced references/*.md exists."""
from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SKILLS = REPO / ".cursor" / "skills"
FRONTMATTER_RE = re.compile(r"^---\n(.*?)\n---\n", re.DOTALL)
REF_LINK_RE = re.compile(r"`references/([^`]+)`")


def _skill_mds() -> list[Path]:
    if not SKILLS.is_dir():
        return []
    return sorted(SKILLS.glob("*/SKILL.md"))


SKILL_MDS = _skill_mds()


@pytest.mark.skipif(not SKILL_MDS, reason="no .cursor/skills")
@pytest.mark.parametrize("path", SKILL_MDS, ids=lambda p: p.parent.name)
def test_skill_frontmatter_and_references(path: Path):
    text = path.read_text(encoding="utf-8")
    m = FRONTMATTER_RE.match(text)
    assert m, f"{path} missing YAML frontmatter"
    fm = m.group(1)
    assert re.search(r"^name:\s*\S+", fm, re.M), f"{path} missing name"
    assert "description:" in fm, f"{path} missing description"
    refs = REF_LINK_RE.findall(text)
    for name in refs:
        dest = path.parent / "references" / name
        assert dest.is_file(), f"{path.name} points at missing {dest}"


def test_canonical_references_are_synced():
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "sync_skill_references",
        REPO / "scripts" / "sync_skill_references.py",
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert mod.sync(check=True) == 0
