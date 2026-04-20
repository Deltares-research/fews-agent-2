"""FEWS cross-file ID types.

Each ID is a `NewType` over a constrained string (non-empty, trimmed).
NewType gives static-checker distinction (mypy flags passing a ParameterId
where a LocationId is expected); the underlying `Annotated[str, ...]` lets
Pydantic reject empty/whitespace IDs at model construction.

Semantic validation (does a referenced id actually exist in the declaring
file?) is a separate concern — see validation/semantic.py. When the XSD
lands with a real pattern, tighten `_FewsId` in one place.

Declaration sites are documented in data/variable_to_files.json.
"""
from typing import Annotated, NewType

from pydantic import StringConstraints

# Shared constraint: non-empty, whitespace-trimmed. Tighten here once the
# XSD pins a character class (e.g. r"^[A-Za-z0-9_.\-]+$").
_FewsId = Annotated[str, StringConstraints(min_length=1, strip_whitespace=True)]

# Declared in region config files
LocationId = NewType("LocationId", _FewsId)
LocationSetId = NewType("LocationSetId", _FewsId)
ParameterId = NewType("ParameterId", _FewsId)
ParameterGroupId = NewType("ParameterGroupId", _FewsId)
QualifierId = NewType("QualifierId", _FewsId)
TopologyNodeId = NewType("TopologyNodeId", _FewsId)
ThresholdGroupId = NewType("ThresholdGroupId", _FewsId)
LevelThresholdId = NewType("LevelThresholdId", _FewsId)
ThresholdValueSetId = NewType("ThresholdValueSetId", _FewsId)
WarningLevelId = NewType("WarningLevelId", _FewsId)
ValidationRuleSetId = NewType("ValidationRuleSetId", _FewsId)
ModifierId = NewType("ModifierId", _FewsId)
ModuleInstanceSetId = NewType("ModuleInstanceSetId", _FewsId)

# Declared by filename convention (one per file)
ModuleInstanceId = NewType("ModuleInstanceId", _FewsId)
WorkflowId = NewType("WorkflowId", _FewsId)
IdMapId = NewType("IdMapId", _FewsId)
UnitConversionsId = NewType("UnitConversionsId", _FewsId)

# Declared in system config
UserGroupId = NewType("UserGroupId", _FewsId)
PermissionId = NewType("PermissionId", _FewsId)
ClassBreaksId = NewType("ClassBreaksId", _FewsId)

# Module-local (scope: within a single ModuleConfigFile)
VariableId = NewType("VariableId", _FewsId)
ModuleParameterGroupId = NewType("ModuleParameterGroupId", _FewsId)
ModuleParameterId = NewType("ModuleParameterId", _FewsId)
