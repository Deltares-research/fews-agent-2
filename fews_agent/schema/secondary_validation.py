"""SecondaryValidation.xml — secondary validation checks (logging-only or
flag-altering) run on time series outside the import path.

XSD root: ``secondaryValidation`` (SecondaryValidationComplexType).

Top-level structure:
  - 0..n ``variableDefinition`` entries (named time series usable in checks)
  - 1..n choice between 11 check kinds: minNumberOfValuesCheck,
    minNonMissingValuesCheck, minReliableOrDoubtfulValuesCheck,
    minReliableValuesCheck, seriesComparisonCheck, flagsComparisonCheck,
    spatialHomogeneityCheck, mannKendallCheck, flagPersistencyCheck,
    plus a couple more from the inheritance chain.

The XSD's choice means sibling order across the 11 element kinds may
matter. We model it as a list of single-key dicts — same convention as
Grids.xml's interleaved <regular>/<irregular>. Each dict entry has a
single tag key (e.g. ``minNumberOfValuesCheck``) whose value is the
check body as a ``dict[str, Any]``. variableDefinition is a list of
the same shape (single typed field for the structural slot).
"""
from __future__ import annotations

from typing import Any

from pydantic import Field

from .common import FewsModel


class SecondaryValidation(FewsModel):
    """Root of SecondaryValidation.xml.

    ``checks`` is an ordered list of single-key dicts where each key is
    one of the 11 XSD check element names; the value is a ``dict[str,
    Any]`` for the check body. This preserves declared sibling order
    across heterogeneous check kinds.
    """

    variableDefinition: list[dict[str, Any]] = Field(default_factory=list)
    checks: list[dict[str, Any]] = Field(min_length=1)
