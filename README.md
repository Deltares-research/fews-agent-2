# fews-agent

Delft-FEWS configuration assistant: the host LLM fills a typed
intermediate representation;
Python renders and validates XML.

**Getting started (skills + `fews-check` CLI):**
[.cursor/skills/README.md](.cursor/skills/README.md)

No repo and no `.venv` yet? Start at
[Setup](.cursor/skills/README.md#setup)
(Git → uv → clone → Cursor **or VS Code** → `uv sync --group dev`
→ smoke-test). After that, from the repo root:

```bash
uv sync --group dev
uv run fews-check --json schema-shape Workflow
```

Architecture: [doc/ADR_mcp.md](doc/ADR_mcp.md). Leftover MCP/HTTP
adapters: [README_MCP.md](README_MCP.md).
