"""Agent package — LLM-first elicitation (see PLAN.md).

The old tool-wizard stack (AgentLoop, checklist, progress, wizard, db)
was removed with the LLM-first refactor; providers are the only
package-level export.
"""
from .providers import default_model, get_provider

__all__ = ["default_model", "get_provider"]
