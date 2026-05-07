"""Derive a stub LocationSets.xml from rendered XML references.

Phase (a) deterministic deriver. Real location sets need a CSV or
shapefile backing them — the agent can't invent that data. But the
project's rendered XMLs already declare which locationSet IDs are
referenced (workflows, displayGroups, filters use ``<locationSetId>``).

The deriver emits one ``<locationSet id="X"/>`` stub per unique non-
placeholder reference. The result XSD-validates and serves as a
checklist for the configurator: each stub is a set they need to
back with real data (csvFile/esriShapeFile/locationId list).

When the configurator provides their own ``locationSetsFile.yaml``, the
deriver doesn't fire — input wins.
"""
from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

from lxml import etree

if TYPE_CHECKING:
    from .blueprint import RenderedFile


_PLACEHOLDER_RE = re.compile(r"\$[A-Z0-9_]+\$")


def _is_placeholder(value: str) -> bool:
    return bool(_PLACEHOLDER_RE.search(value or ""))


def _collect_referenced_set_ids(
    rendered_files: list["RenderedFile"],
) -> set[str]:
    ids: set[str] = set()
    for rf in rendered_files:
        try:
            tree = etree.fromstring(rf.content.encode("utf-8"))
        except etree.XMLSyntaxError:
            continue
        for el in tree.iter("{*}locationSetId"):
            text = (el.text or "").strip()
            if text and not _is_placeholder(text):
                ids.add(text)
    return ids


def derive_locationsets_yaml(
    rendered_files: list["RenderedFile"],
) -> dict[str, Any] | None:
    """Build a stub LocationSets yaml from rendered locationSetId references.

    Each entry is a placeholder — the configurator must fill in the
    csvFile/esriShapeFile backing the set. Returns ``None`` if no
    references were found.
    """
    ids = _collect_referenced_set_ids(rendered_files)
    if not ids:
        return None
    body = [
        {"locationSet": {"@id": sid}}
        for sid in sorted(ids)
    ]
    return {"body": body}


__all__ = ["derive_locationsets_yaml"]
