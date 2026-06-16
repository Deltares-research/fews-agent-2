"""Pattern-farmer IR.

Shapes the LLM output before it touches the filesystem. Every field
has a hard type so junk fails at the Pydantic gate, not at FEWS load.

Mirrors ``pattern.yaml`` exactly so ``renderer.py`` is a single
``yaml.safe_dump``.
"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


# Match the existing pattern.yaml shape — variables is a dict keyed by
# variable name; each entry has type + required (and optional default).
class VariableSpec(BaseModel):
    type: Literal["str", "int", "float", "bool"] = "str"
    required: bool = True
    default: Any | None = None


class OutputSpec(BaseModel):
    # The schema class name MUST exist in fews_agent.schema. We
    # validate at the renderer boundary using schema_class_for().
    schema_class: str = Field(alias="schema")
    output: str        # Jinja-templated relative path
    data: dict[str, Any]  # Jinja-templated payload

    model_config = {"populate_by_name": True}


class PatternSpec(BaseModel):
    name: str
    description: str = ""
    variables: dict[str, VariableSpec] = Field(default_factory=dict)
    outputs: list[OutputSpec] = Field(default_factory=list)
    contributions: list[dict[str, Any]] = Field(default_factory=list)


# --- farmer input -----------------------------------------------------

class InstanceOutput(BaseModel):
    """One rendered output from a concrete instance."""

    schema_class: str = Field(alias="schema")
    output: str        # Concrete (non-templated) relative path
    data: dict[str, Any]  # Concrete data dict that Pydantic.model_validate accepts

    model_config = {"populate_by_name": True}


class InstanceInput(BaseModel):
    """One concrete instance of the capability being farmed."""

    label: str         # Human-readable, e.g. "HRDPS"
    variable_hints: dict[str, Any] = Field(default_factory=dict)
    outputs: list[InstanceOutput]
