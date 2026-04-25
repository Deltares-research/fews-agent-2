"""HymosTransferDbImportRun generator."""
from __future__ import annotations

from fews_agent.schema import HymosTransferDbImportRun

from .base import render


def generate(model: HymosTransferDbImportRun) -> str:
    return render("module/hymos_transfer_db_import_run.xml.j2", model)
