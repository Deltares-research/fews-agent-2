"""Trivial stub handler for ``inputs/manualForecastDisplay.yaml``.

All-optional UI config; empty yaml renders an XSD-valid XML. Configurator
can hand-edit for runningPredefined / coldState / warmState policies.
"""
from . import _stub

advance = _stub.make_advance(
    output_filename="manualForecastDisplay.yaml",
    intro_text=(
        "Entering edit mode for manualForecastDisplay.yaml. This drives "
        "the Manual Forecast dialog UI; all fields optional, FEWS uses "
        "defaults. Type /cancel-edit to abort."
    ),
)

__all__ = ["advance"]
