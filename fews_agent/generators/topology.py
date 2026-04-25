"""Topology generator (recursive nodes tree)."""
from __future__ import annotations

from fews_agent.schema import Topology

from .base import render


def generate(model: Topology) -> str:
    return render("region/topology.xml.j2", model)
