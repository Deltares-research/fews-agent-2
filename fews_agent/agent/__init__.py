# Core exports — keep this module Rich-free so headless callers don't
# pull the TUI stack just to instantiate an AgentLoop. `run_wizard` and
# `WIZARDS` live in `.wizard` and are imported directly by the Rich TUI.
from ..db import ProjectStore
from .checklist import checklist_for, optional_fields, required_fields
from .loop import AgentLoop
from .progress import ItemProgress, ProjectProgress, compute_progress
from .providers import default_model, get_provider

__all__ = [
    "AgentLoop",
    "ItemProgress",
    "ProjectProgress",
    "ProjectStore",
    "checklist_for",
    "compute_progress",
    "default_model",
    "get_provider",
    "optional_fields",
    "required_fields",
]
