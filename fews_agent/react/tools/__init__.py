"""Tool assembly — the one place the registry is built."""
from __future__ import annotations

from ..context import ToolContext
from ..registry import Tool, ToolRegistry
from .csv_tools import INGEST_CSVS, WRITE_INPUT_CSV
from .derive_tools import DERIVE
from .example_tools import READ_EXAMPLE
from .file_tools import (
    LIST_PROJECT_FILES,
    READ_PROJECT_FILE,
    WRITE_CONFIG_FILE,
    WRITE_GENERIC_FILE,
)
from .specs_tools import DESCRIBE_SPEC, LIST_SPECS
from .standards_tools import GET_STANDARD
from .validate_tools import VALIDATE_PROJECT
from .web_tools import FEWS_WIKI_LOOKUP, SEARCH_STATIONS


def build_registry(ctx: ToolContext) -> ToolRegistry:
    """All v1 tools. `ctx` is threaded at dispatch time, not bound here;
    the parameter stays so later tools (web lookups) can condition on
    session settings without changing the call site."""
    tools: list[Tool] = [
        LIST_SPECS,
        DESCRIBE_SPEC,
        READ_EXAMPLE,
        WRITE_CONFIG_FILE,
        WRITE_GENERIC_FILE,
        READ_PROJECT_FILE,
        LIST_PROJECT_FILES,
        GET_STANDARD,
        WRITE_INPUT_CSV,
        INGEST_CSVS,
        DERIVE,
        VALIDATE_PROJECT,
        SEARCH_STATIONS,
        FEWS_WIKI_LOOKUP,
    ]
    return ToolRegistry(tools)
