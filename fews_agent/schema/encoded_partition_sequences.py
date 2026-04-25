"""EncodedPartitionSequences.xml — per-workflow partition-sequence
encoding values (used by the FEWS MC scheduler)."""
from __future__ import annotations

from pydantic import Field

from .common import FewsModel


class EncodedPartitionSequence(FewsModel):
    workflowId: str
    value: str


class EncodedPartitionSequences(FewsModel):
    """Root of EncodedPartitionSequences.xml."""

    encodedPartitionSequence: list[EncodedPartitionSequence] = Field(default_factory=list)
