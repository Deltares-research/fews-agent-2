"""TopologyGroup generator."""
from __future__ import annotations

from .base import render
from ..schema.topology_group import TopologyGroup


def generate(model: TopologyGroup) -> str:
    return render("region/topology_group.xml.j2", model)
