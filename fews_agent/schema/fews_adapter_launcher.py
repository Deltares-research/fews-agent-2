"""FewsAdapterLauncher.xml — launcher for external adapter executables.

Sequence: description? · workingDir · splashPictureFile · executeActivity+
          · logConfigFile?

Each `executeActivity` reuses the existing ExecuteActivity model from
general_adapter_run — they share ExecuteActivityComplexType.
"""
from __future__ import annotations

from pydantic import Field

from .common import FewsModel
from .general_adapter_run import ExecuteActivity


class FewsAdapterLauncher(FewsModel):
    description: str | None = None
    workingDir: str
    splashPictureFile: str
    executeActivity: list[ExecuteActivity] = Field(min_length=1)
    logConfigFile: str | None = None
