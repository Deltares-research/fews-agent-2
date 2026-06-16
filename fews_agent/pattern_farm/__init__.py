"""Pattern-farming agent.

Given N concrete instances of a FEWS capability (each instance is a
list of rendered output specs — schema class, output path, data dict),
abstract them into a single reusable ``pattern.yaml`` with Jinja-
templated variables.

Design mirrors the rest of the agent:

  - rigid Pydantic IR (the LLM fills, not invents)
  - deterministic preprocessing (``diff_finder``) surfaces variable
    candidates before any LLM call
  - three small LLM jobs (variables → templating → repair)
  - validate by re-rendering against the input instances; failure
    → loop with the error in context
  - capped retries, loud failure on exhaustion

Privacy: the LLM call is the only externalised step. Default provider
is Ollama (local). The CLI also supports HF via LiteLLM for stronger
models when the local box can't host them — gated by an explicit flag.
"""
from .ir import PatternSpec, OutputSpec, VariableSpec, InstanceInput
from .farmer import farm

__all__ = ["PatternSpec", "OutputSpec", "VariableSpec", "InstanceInput", "farm"]
