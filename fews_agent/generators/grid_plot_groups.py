"""GridPlotGroups generator."""
from __future__ import annotations

from .base import render
from ..schema.grid_plot_groups import GridPlotGroups


def generate(model: GridPlotGroups) -> str:
    return render("display/grid_plot_groups.xml.j2", model)
