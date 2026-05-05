"""Replay script: drive the auto-derived ThresholdWarningLevels wizard.

Proves the auto-derivation path: this WizardSpec was inferred from the
``ThresholdWarningLevels`` Pydantic model (no hand-authored entry), and
the wizard runs the same elicitation flow as Locations.

Three thresholds, one user message each, then a "no" to "add another?"
"""
from __future__ import annotations


_LEVELS = [
    "id 0, name No threshold exceeded, color green, "
    "iconName default1.gif, historicOverlayIconName historicwarninglevel1.gif, "
    "forecastOverlayIconName historicwarninglevel1.gif",

    "id 1, name Alert Level, color orange, "
    "iconName warninglevel1.gif, historicOverlayIconName historicwarninglevel1.gif, "
    "forecastOverlayIconName forecastwarninglevel1.gif",

    "id 2, name Major Flood Level, color red, "
    "iconName warninglevel2.gif, historicOverlayIconName historicwarninglevel2.gif, "
    "forecastOverlayIconName forecastwarninglevel2.gif",
]


def _build_answers() -> list[str]:
    answers: list[str] = []
    for i, bulk in enumerate(_LEVELS):
        answers.append(bulk)
        # Auto-derived spec has supports_attributes=False, so no
        # attributes confirm. Just the "Add another?" confirm.
        answers.append("yes" if i < len(_LEVELS) - 1 else "no")
    return answers


SCRIPT = {
    "project_name": "tutorial-twl",
    "spec_name": "thresholdWarningLevels",
    "fixture_root": "examples/config-tutorial",
    "description": (
        "Auto-derived spec smoke test: ThresholdWarningLevels wizard "
        "produces the tutorial XML byte-equivalent via 3 user replies."
    ),
    "answers": _build_answers(),
}
