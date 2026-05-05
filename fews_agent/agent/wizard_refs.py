"""Reference index — map FEWS cross-spec id field names to ref_sources.

Source of truth: ``data/variables/variable_to_files.json``. Its
``shared_cross_file_references`` block already documents, for each
cross-spec id (``parameterId``, ``locationId``, etc.), which spec
declares the canonical id and at which path. We translate that into
the wizard's own ``ref_source`` format (``<input_key>.<path>``) so the
auto-derived ``WizardField``s can carry ``kind="ref"`` automatically.

A leaf field whose name matches an entry here is promoted from
``scalar`` to ``ref`` at auto-derive time. The wizard's existing
``_resolve_ref_choices`` then walks project_data using the ref_source
and offers the declared ids in field-by-field mode. The bulk-ask path
can also use the index post-parse to validate that the LLM extracted
a known id.
"""
from __future__ import annotations

import json
import logging
from functools import lru_cache
from pathlib import Path

_logger = logging.getLogger(__name__)
REPO_ROOT = Path(__file__).resolve().parents[2]
JSON_PATH = REPO_ROOT / "data" / "variables" / "variable_to_files.json"


def _file_type_to_input_key() -> dict[str, str]:
    """Invert the existing _SPEC_TO_FILE_TYPE map.

    Computed lazily here (rather than imported at module load) to
    avoid pulling agent/checklist into wizard_refs's import cycle.
    """
    from .checklist import _SPEC_TO_FILE_TYPE
    return {file_type: spec_name for spec_name, file_type in _SPEC_TO_FILE_TYPE.items()}


@lru_cache(maxsize=1)
def load_ref_index() -> dict[str, str]:
    """Return ``{ref_name: ref_source}`` for every known shared FEWS id.

    Ref names are field-name keys (``parameterId``, ``locationId``,
    etc.) — match against the LEAF segment of a wizard path.
    Ref sources are wizard-format strings the existing
    ``_resolve_ref_choices`` already understands.

    Returns an empty dict when the JSON catalog isn't available, so
    callers can ignore the index without conditional logic.
    """
    if not JSON_PATH.exists():
        _logger.warning("variable_to_files.json not found at %s", JSON_PATH)
        return {}
    with JSON_PATH.open("r", encoding="utf-8") as f:
        data = json.load(f)
    file_type_map = _file_type_to_input_key()
    out: dict[str, str] = {}
    for ref_name, info in data.get("shared_cross_file_references", {}).items():
        decl = info.get("declared_in") or {}
        ft = decl.get("file_type")
        path = decl.get("path")
        if not ft or not path:
            continue
        # Some catalog entries trail "(assumed; not sampled)" or similar
        # explanatory parentheticals after the path. Strip them — the
        # wizard's ref-source parser doesn't tolerate non-path tail.
        if "(" in path:
            path = path.split("(", 1)[0].strip()
        input_key = file_type_map.get(ft)
        if not input_key:
            # The catalog references a file_type the agent doesn't yet
            # map (likely a not-yet-promoted spec). Skip — this just
            # means the wizard won't auto-promote that field to ref.
            continue
        out[ref_name] = f"{input_key}.{path}"
    return out


__all__ = ["load_ref_index"]
