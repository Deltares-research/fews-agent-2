"""EncodedPartitionSequences generator."""
from __future__ import annotations

from fews_agent.schema import EncodedPartitionSequences

from .base import render


def generate(model: EncodedPartitionSequences) -> str:
    return render("system/encoded_partition_sequences.xml.j2", model)
