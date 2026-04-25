"""Replay script: simulate a real user answering the wizard's questions.

The wizard drives the conversation. The script just provides the user
side — natural-language answers in the order the wizard asks. The LLM
parser inside the wizard handles converting prose into structured field
values; the wizard's deterministic flow handles "add another?" loops,
optional-group skips, and validation.

Wizard prompt order (Locations spec):
  1. file-level: geoDatum
  2. for each location:
       a. one bulk ask covering id, name, x, y, z, shortName,
          description, parentLocationId, relation
       b. confirm: add attributes?  (we say "no")
       c. confirm: add another location?
"""
from __future__ import annotations

# Per-location bulk answers, in tutorial order. One natural-language
# sentence each — the parser extracts id/name/x/y plus any optional
# fields the user mentioned.
_LOCATIONS = [
    "id RDPS, name Regional Deterministic Prediction System (10 km), "
    "shortName RDPS, x -142.8968, y 18.1429",

    "id GDPS, name Global Deterministic Prediction System (25 km), "
    "shortName GDPS, x -180, y -90",

    "id RDPA, name Regional Deterministic Precipitation Analysis "
    "(RDPA - CaPA) 10km, shortName RDPA, x 0, y 0",

    "id REPS, name Regional Ensemble Prediction System, "
    "shortName REPS, x 0, y 0",

    "id GEPS, name Global Ensemble Prediction System, "
    "shortName GEPS, x 0, y 0",

    # No shortName from here on except where explicitly listed.
    "id GFS, name GFS Forecast, x 0, y 0",

    "id GLOBSNOW, name Globsnow (ESA), shortName GLOBSNOW, x -180, y 90",

    "id IMERG_world, name IMerge Rainfall, x 0, y 0",
    "id IMERG, name IMerge Rainfall, x 0, y 0",
    "id GFS_world, name GFS Forecast, x 0, y 0",
    "id GSMAP_world, name GSMAP Rainfall, x 0, y 0",
    "id GSMAP, name GSMAP Rainfall, x 0, y 0",
    "id E2O_25, name E2O_25 0.25 degree grid, x 0, y 0",
    "id E2O_5, name E2O_5 0.5 degree grid, x 0, y 0",
    "id SNODAS, name SNODAS, x 0, y 0",

    # Last one — the dollar signs are literal, not template placeholders.
    "id $MODELNAME1$Grid, name $MODELNAME1$Grid, x 0, y 0",
]


def _build_answers() -> list[str]:
    answers: list[str] = ["WGS 1984"]  # geoDatum
    for i, bulk in enumerate(_LOCATIONS):
        answers.append(bulk)               # bulk-ask reply
        answers.append("no")               # add attributes? → no
        # add another location? — yes for all but the last
        answers.append("yes" if i < len(_LOCATIONS) - 1 else "no")
    return answers


SCRIPT = {
    "project_name": "tutorial",
    "spec_name": "locations",
    "fixture_root": "examples/config-tutorial",
    "description": (
        "Wizard-driven replay: the wizard asks; the script answers in "
        "natural prose; an LLM parser extracts structured fields per ask."
    ),
    "answers": _build_answers(),
}
