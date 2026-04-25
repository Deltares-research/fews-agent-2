"""WhatIfScenariosDescriptors.xml — registry of available WhatIfScenarios files."""
from __future__ import annotations

from pydantic import Field

from .common import FewsModel


class WhatIfScenariosDescriptor(FewsModel):
    id: str
    name: str | None = None
    description: str | None = None


class WhatIfScenariosDescriptors(FewsModel):
    """Root of WhatIfScenariosDescriptors.xml."""

    whatIfScenariosDescriptor: list[WhatIfScenariosDescriptor] = Field(min_length=1)
    # XSD fixes version at 1.1 for this file (other *Descriptors are 1.0).
    version: str = "1.1"
