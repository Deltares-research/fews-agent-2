"""Checklist loader for the elicitation side of the agent.

Reads `data/variables/file_to_variables.json` — a structured per-
file-type list of variables with `kind`, `required`, `allowed_values`,
`ref`, `declares`, `repeating_group` annotations. Both the chat
side (system prompt injection) and the wizard side (thematic groups
in `wizard.py`) pull from this single source of truth so their views
stay in sync.

The file_to_variables keys are PascalCase FEWS type names ("Locations",
"Parameters"); `spec.name` in the generator registry is lowercase
("locations", "parameters"). `_SPEC_TO_FILE_TYPE` bridges. Missing
entries log a warning and return an empty list rather than raise —
most specs don't have first-class checklists yet, and we'd rather
have the agent ask the user than crash.
"""
from __future__ import annotations

import json
import logging
from functools import lru_cache
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[2]
_CHECKLIST_PATH = _REPO_ROOT / "data" / "variables" / "file_to_variables.json"

_logger = logging.getLogger(__name__)

# Spec-registry name → file_to_variables.json key. Populated for slice 1
# (Locations) and the obvious one-to-one matches; extend as we add wizard
# coverage for more specs.
_SPEC_TO_FILE_TYPE: dict[str, str] = {
    "locations": "Locations",
    "parameters": "Parameters",
    "qualifiers": "Qualifiers",
    "thresholdWarningLevels": "ThresholdWarningLevels",
    "thresholds": "Thresholds",
    "thresholdValueSets": "ThresholdValueSets",
    "moduleInstanceSets": "ModuleInstanceSets",
    "permissions": "Permissions",
    "userGroups": "UserGroups",
    "validationRuleSets": "ValidationRuleSets",
    "modifierTypes": "ModifierTypes",
    "topology": "Topology",
    "timeSteps": "TimeSteps",
    "locationIcons": "LocationIcons",
    "moduleInstanceDescriptors": "ModuleInstanceDescriptors",
    "workflowDescriptors": "WorkflowDescriptors",
    "timeSeriesDisplayConfig": "TimeSeriesDisplay",
    "manualForecastDisplay": "ManualForecastDisplay",
    "modifierDisplay": "ModifierDisplay",
    "forecasterNotesDisplay": "ForecasterNotesDisplay",
}


@lru_cache(maxsize=1)
def load_checklist() -> dict[str, Any]:
    """Full parsed `file_to_variables.json`. Cached for the process life."""
    if not _CHECKLIST_PATH.exists():
        raise FileNotFoundError(f"checklist not found: {_CHECKLIST_PATH}")
    with _CHECKLIST_PATH.open("r", encoding="utf-8") as f:
        return json.load(f)


def file_type_for(spec_name: str) -> str | None:
    """file_to_variables.json key for the given spec name, or None if unmapped."""
    return _SPEC_TO_FILE_TYPE.get(spec_name)


def checklist_for(spec_name: str) -> list[dict[str, Any]]:
    """Variables list for a spec's file type.

    Returns [] and logs a warning when:
      - the spec is not in `_SPEC_TO_FILE_TYPE`
      - the file_to_variables.json doesn't include that key
    """
    file_type = file_type_for(spec_name)
    if file_type is None:
        _logger.warning(
            "no file_to_variables mapping for spec %r; returning empty checklist",
            spec_name,
        )
        return []
    data = load_checklist()
    entry = data.get("file_types", {}).get(file_type)
    if entry is None:
        _logger.warning(
            "file_to_variables.json has no %r entry; returning empty checklist",
            file_type,
        )
        return []
    return list(entry.get("variables", []))


def required_fields(spec_name: str) -> list[dict[str, Any]]:
    return [v for v in checklist_for(spec_name) if v.get("required") and v.get("kind") != "static"]


def optional_fields(spec_name: str) -> list[dict[str, Any]]:
    return [v for v in checklist_for(spec_name) if not v.get("required")]


def shared_ids() -> list[str]:
    """Cross-file id types the agent tracks once and reuses.

    Read from the _meta.shared_substructures block where present; falls
    back to the hardcoded set the semantic validator already registers
    (LocationId, ParameterId, ModuleInstanceId, WorkflowId, ...).
    """
    return [
        "locationId",
        "locationSetId",
        "parameterId",
        "parameterGroupId",
        "qualifierId",
        "moduleInstanceId",
        "workflowId",
        "idMapId",
        "unitConversionsId",
        "thresholdGroupId",
        "warningLevelId",
        "validationRuleSetId",
        "modifierId",
    ]
