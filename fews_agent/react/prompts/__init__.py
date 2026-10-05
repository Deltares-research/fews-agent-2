"""Prompt loader for the ReAct agent (standing rule: prompts live as
``.txt`` files in this folder, never inline in Python).

Same contract as ``fews_agent.agent.prompts``: Jinja with square-bracket
delimiters (``[[ var ]]``, ``[% if %]``) because prompt text is full of
literal ``{ }`` (JSON) and ``$…$`` (FEWS placeholders); StrictUndefined
fails loudly on a missing variable.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined

_PROMPTS_DIR = Path(__file__).parent

_env = Environment(
    loader=FileSystemLoader(str(_PROMPTS_DIR)),
    variable_start_string="[[",
    variable_end_string="]]",
    block_start_string="[%",
    block_end_string="%]",
    comment_start_string="[#",
    comment_end_string="#]",
    keep_trailing_newline=True,
    autoescape=False,
    undefined=StrictUndefined,
    trim_blocks=True,
    lstrip_blocks=True,
)


@lru_cache(maxsize=None)
def _template(filename: str):
    return _env.get_template(filename)


def load(name: str, /, **variables) -> str:
    """Render prompt ``name`` (``.txt`` suffix optional) with ``variables``."""
    filename = name if name.endswith(".txt") else f"{name}.txt"
    return _template(filename).render(**variables)


__all__ = ["load"]
