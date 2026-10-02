# fews-agent

Delft-FEWS configuration assistant: the host LLM fills a typed
intermediate representation;
Python renders and validates XML.

**Getting started (skills + `fews-check` CLI):**
[.cursor/skills/README.md](.cursor/skills/README.md)

```bash
uv sync --group dev
uv run fews-check --json schema-shape Workflow
```

Architecture: [doc/ADR_mcp.md](doc/ADR_mcp.md). Leftover MCP/HTTP
adapters: [README_MCP.md](README_MCP.md).
