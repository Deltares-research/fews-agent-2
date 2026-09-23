"""Keyword lookup over the example corpus (no embeddings).

Searches ``examples/config-tutorial`` (when present), pattern.yaml
descriptions, and any XML that ships under ``tests/fixtures``.
"""
from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
_TUTORIAL = REPO_ROOT / "examples" / "config-tutorial"
_PATTERNS = REPO_ROOT / "fews_agent" / "patterns"
_FIXTURES = REPO_ROOT / "tests" / "fixtures"


def _score(query: str, text: str) -> int:
    q = query.lower().split()
    blob = text.lower()
    return sum(1 for tok in q if tok and tok in blob)


def _snippet(text: str, limit: int = 1200) -> str:
    text = text.strip()
    if len(text) <= limit:
        return text
    return text[: limit - 3] + "..."


def find_examples(query: str, k: int = 5) -> list[dict[str, str]]:
    """Return up to ``k`` matching files with a text snippet."""
    query = (query or "").strip()
    if not query:
        return []
    hits: list[tuple[int, dict[str, str]]] = []

    roots: list[tuple[Path, str]] = []
    if _TUTORIAL.is_dir():
        roots.append((_TUTORIAL, "tutorial"))
    if _FIXTURES.is_dir():
        roots.append((_FIXTURES, "fixture"))
    if _PATTERNS.is_dir():
        roots.append((_PATTERNS, "pattern"))

    for root, provenance in roots:
        for path in root.rglob("*"):
            if not path.is_file():
                continue
            if path.suffix.lower() not in {".xml", ".yaml", ".yml", ".j2"}:
                continue
            if any(p.startswith(".") for p in path.parts):
                continue
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            hay = f"{path.name}\n{text}"
            score = _score(query, hay)
            if score <= 0:
                continue
            rel = path.relative_to(REPO_ROOT)
            hits.append((score, {
                "path": str(rel).replace("\\", "/"),
                "snippet": _snippet(text),
                "provenance": provenance,
            }))

    hits.sort(key=lambda item: (-item[0], item[1]["path"]))
    # Dedup by path
    seen: set[str] = set()
    out: list[dict[str, str]] = []
    for _, row in hits:
        if row["path"] in seen:
            continue
        seen.add(row["path"])
        out.append(row)
        if len(out) >= max(1, int(k)):
            break
    return out
