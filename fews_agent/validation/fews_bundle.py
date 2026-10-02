"""Build a FEWS region zip from a generation-tree folder.

Tiers 1–3 validate the generation layout (tutorial-shaped). Tier 4
(FewsCLI) needs the *delivery* layout: ``WorkflowFiles/`` →
``Config/Workflows/``, and optionally ``sa_global.properties`` at the
region root. Which zip variant FewsCLI ``regionpath=`` accepts
(``config_only`` vs region-root properties) is still empirical — both
are available here.
"""
from __future__ import annotations

import io
import zipfile
from pathlib import Path

from fews_agent.agent.modules import CONFIG_FOLDERS, fews_bundle_path


def iter_tree_files(tree: Path) -> list[tuple[Path, str]]:
    """``(abs_path, posix_relpath)`` for every file under ``tree``."""
    root = Path(tree)
    if not root.is_dir():
        return []
    return sorted(
        (p, p.relative_to(root).as_posix())
        for p in root.rglob("*") if p.is_file()
    )


def build_region_zip(
    tree: Path,
    *,
    config_only: bool = False,
    include_empty_folders: bool = True,
) -> bytes | None:
    """Zip a generation tree using the delivery remaps.

    ``config_only=True`` drops region-root files (``sa_global.properties``)
    so the archive contains only ``Config/`` — the shape FewsCLI's wiki
    page describes. ``config_only=False`` keeps the Stand-Alone layout
    (properties at the region root) that ``ChatSession.config_zip`` ships.
    """
    files = iter_tree_files(tree)
    if not files:
        return None
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        if include_empty_folders:
            for folder in CONFIG_FOLDERS:
                zf.writestr(zipfile.ZipInfo(f"Config/{folder}/"), b"")
        for path, rel in files:
            dest = fews_bundle_path(rel)
            if config_only and not dest.startswith("Config/"):
                continue
            zf.write(path, dest)
    return buf.getvalue()


def write_region_zip(
    tree: Path,
    dest: Path,
    *,
    config_only: bool = True,
) -> Path | None:
    """Write a region zip to ``dest``. Returns ``dest`` or None if empty."""
    data = build_region_zip(tree, config_only=config_only)
    if data is None:
        return None
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(data)
    return dest
