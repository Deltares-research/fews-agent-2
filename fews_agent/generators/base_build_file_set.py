"""BaseBuildFileSet generator."""
from __future__ import annotations

from fews_agent.schema import BaseBuildFileSet

from .base import render


def generate(model: BaseBuildFileSet) -> str:
    return render("root/base_build_file_set.xml.j2", model)
