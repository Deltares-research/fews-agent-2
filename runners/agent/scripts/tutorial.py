"""Replay script: drive the wizard through the entire tutorial project.

One project (``tutorial``), multiple phases — one per spec the wizard
walks. Each phase uses the section-level bulk-ask: ALL items for a
section land in one user message; the wizard's parser extracts the
list and upserts each. The wizard no longer asks ``Add more X?`` after
a bulk reply (one-or-many is implicit), so each phase typically has
``<file-level scalars> + <one bulk per section>`` answers — usually
two or three.

To grow tutorial coverage, append more phases below. Each phase is
``{"spec_name": ..., "answers": [<file-level…>, <section-1 bulk>,
<section-2 bulk>, ...]}``. Use ``"skip"`` for an empty section.
"""
from __future__ import annotations


# ---------------------------------------------------------------------------
# Phase 1 — Locations.xml (manual WizardSpec, 1 file-level + 1 section)
# ---------------------------------------------------------------------------

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
    "id $MODELNAME1$Grid, name $MODELNAME1$Grid, x 0, y 0",
]


def _bulk_lines(items: list[str]) -> str:
    return "\n".join(f"- {line}" for line in items)


def _locations_answers() -> list[str]:
    return [
        "WGS 1984",            # geoDatum (file-level)
        _bulk_lines(_LOCATIONS),  # section: location[] — 16 items at once
    ]


# ---------------------------------------------------------------------------
# Phase 2 — Qualifiers.xml (multi-section: qualifier[] + csvFile[])
# ---------------------------------------------------------------------------

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


def _qualifiers_answers() -> list[str]:
    return [
        "false",                  # allowReferencingUndefinedQualifiers
        _bulk_lines(_QUALIFIERS), # section: qualifier[] — 10 at once
        "skip",                   # section: csvFile[] — none
    ]


# ---------------------------------------------------------------------------
# Phase 3 — ThresholdWarningLevels.xml (single section)
# ---------------------------------------------------------------------------

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


def _levels_answers() -> list[str]:
    return [
        _bulk_lines(_LEVELS),  # section: thresholdWarningLevel[] — 3 at once
    ]


# ---------------------------------------------------------------------------
# Project script
# ---------------------------------------------------------------------------

SCRIPT = {
    "project_name": "tutorial",
    "fixture_root": "examples/config-tutorial",
    "description": (
        "Full tutorial project replay using section-level bulk-ask: "
        "each section's items go in a single user reply, parsed as a "
        "list. Total prompt count an order of magnitude smaller than "
        "the per-item flow."
    ),
    "phases": [
        {
            "spec_name": "locations",
            "label": "locations",
            "answers": _locations_answers(),
        },
        {
            "spec_name": "qualifiers",
            "label": "qualifiers",
            "answers": _qualifiers_answers(),
        },
        {
            "spec_name": "thresholdWarningLevels",
            "label": "thresholdWarningLevels",
            "answers": _levels_answers(),
        },
    ],
}
