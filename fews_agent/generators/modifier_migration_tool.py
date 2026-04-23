"""ModifierMigrationTool generator."""
from __future__ import annotations

from fews_agent.schema import ModifierMigrationTool

from .base import render


def generate(model: ModifierMigrationTool) -> str:
    return render("module/modifier_migration_tool.xml.j2", model)
