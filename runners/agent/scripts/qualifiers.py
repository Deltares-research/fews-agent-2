"""Replay script: drive the auto-derived multi-section Qualifiers wizard.

Proves the multi-section path: ``qualifiers`` has TWO repeating
sections (``qualifier[]`` and ``csvFile[]``) plus a file-level boolean
(``allowReferencingUndefinedQualifiers``). The tutorial uses 10
qualifiers and zero csvFiles.

Wizard flow:
  1. file-level: allowReferencingUndefinedQualifiers
  2. section 1: qualifier — 10 bulk asks + 9 "yes" + 1 "no"
  3. section 2: csvFile — "skip" (sentinel — exit section without items)
"""
from __future__ import annotations


_QUALIFIERS = [
    'id="mean", name="mean"',
    'id="max", name="max"',
    'id="min", name="min"',
    'id="25%", name="25%"',
    'id="75%", name="75%"',
    'id="Observed", name="Observed"',
    'id="GFS", name="GFS"',
    'id="E2O", name="E2O"',
    'id="rainonly", name="rainonly"',
    'id="snowonly", name="snowonly"',
]


def _build_answers() -> list[str]:
    answers: list[str] = []
    # File-level: allowReferencingUndefinedQualifiers
    answers.append("false")
    # Section 1 — qualifier. Each: bulk ask + add-another confirm.
    for i, bulk in enumerate(_QUALIFIERS):
        answers.append(bulk)
        answers.append("yes" if i < len(_QUALIFIERS) - 1 else "no")
    # Section 2 — csvFile. We have none in the tutorial; sentinel
    # answer 'skip' exits the section cleanly.
    answers.append("skip")
    return answers


SCRIPT = {
    "project_name": "tutorial-qualifiers",
    "spec_name": "qualifiers",
    "fixture_root": "examples/config-tutorial",
    "description": (
        "Multi-section auto-derived spec: Qualifiers has qualifier[] + "
        "csvFile[] + a file-level boolean. Tutorial uses 10 qualifiers, "
        "no csvFiles."
    ),
    "answers": _build_answers(),
}
