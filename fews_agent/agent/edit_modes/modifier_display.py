"""Trivial stub handler for ``inputs/modifierDisplay.yaml``.

The Pydantic model has all-optional fields and FEWS provides UI
defaults for everything; an empty yaml is XSD-valid. Configurator can
hand-edit later if they want non-default behaviour.
"""
from . import _stub

advance = _stub.make_advance(
    output_filename="modifierDisplay.yaml",
    intro_text=(
        "Entering edit mode for modifierDisplay.yaml. This UI config "
        "has only optional fields — FEWS uses sensible defaults for any "
        "you don't set. Type /cancel-edit to abort."
    ),
)

__all__ = ["advance"]
