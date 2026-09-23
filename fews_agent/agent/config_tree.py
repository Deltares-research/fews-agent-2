"""Brownfield read: open an existing FEWS config as a loaded tree + ledger."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from fews_agent.agent.ledger import Ledger, load_ledger
from fews_agent.validation.load_tree import LoadedTree, load_tree
from fews_agent.validation.semantic import validate_semantic


def open_config(path: str | Path) -> dict[str, Any]:
    """Load a config folder. First open marks every file ``origin: human``.

    Does not rewrite XML. Round-trip (open → no writes) is byte-identical
    because this function only writes ``.fews-agent/ledger.yaml``.
    """
    root = Path(path).resolve()
    tree = load_tree(root)
    ledger = load_ledger(root)
    rels = [str(f.relpath).replace("\\", "/") for f in tree.files]
    bytes_for = {str(f.relpath).replace("\\", "/"): f.data for f in tree.files}
    ledger.mark_human_tree(rels, bytes_for=bytes_for)
    ledger.save()
    return summarize(tree, ledger)


def summarize(tree: LoadedTree, ledger: Ledger | None = None) -> dict[str, Any]:
    declared: dict[str, list[str]] = {}
    unresolved: list[str] = []
    loaded = tree.models_for_semantic()
    if loaded:
        sem = validate_semantic(loaded)
        declared = {k: sorted(v) for k, v in sem.declared.items()}
        unresolved = [f"{r.value} ({r.id_type_name})" for r in sem.unresolved]
    origins: dict[str, int] = {}
    if ledger is not None:
        for entry in ledger.files.values():
            origins[entry.origin] = origins.get(entry.origin, 0) + 1
    return {
        "path": str(tree.root),
        "files": len(tree.files),
        "typed_models": len(loaded),
        "declared_counts": {k: len(v) for k, v in declared.items()},
        "unresolved_count": len(unresolved),
        "unresolved_examples": unresolved[:8],
        "ledger_origins": origins,
        "ledger_path": str(ledger.path) if ledger is not None else None,
    }


def load_open(path: str | Path) -> tuple[LoadedTree, Ledger]:
    root = Path(path).resolve()
    return load_tree(root), load_ledger(root)
