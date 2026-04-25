"""ColdModuleInstanceStateGroups.xml — cold-state group definitions.

Structure:
  - defaultGroup (exactly one, required)
  - seasonalGroup[] (optional, each carries a <season> period)
  - additionalGroup[] (optional)

Each group has id (required attribute), name (optional attribute), and
an optional <description> child.  Root attribute `version` is fixed="1.0"
per XSD.
"""
from __future__ import annotations

from pydantic import Field

from .common import FewsModel, SeasonCondition


class ColdModuleInstanceStateGroup(FewsModel):
    id: str
    name: str | None = None
    description: str | None = None


class SeasonalColdModuleInstanceStateGroup(ColdModuleInstanceStateGroup):
    """ColdModuleInstanceStateGroup + required <season> period."""

    season: SeasonCondition


class ColdModuleInstanceStateGroups(FewsModel):
    version: str = "1.0"
    defaultGroup: ColdModuleInstanceStateGroup
    seasonalGroup: list[SeasonalColdModuleInstanceStateGroup] = Field(
        default_factory=list
    )
    additionalGroup: list[ColdModuleInstanceStateGroup] = Field(
        default_factory=list
    )
