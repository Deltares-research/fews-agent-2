# Leftover MCP / HTTP adapters

Coding agents (Cursor, Claude) should use **`uv run fews-check --json`**
and the skills in `.cursor/skills/`. See
[.cursor/skills/README.md](.cursor/skills/README.md).

MCP (`fews-mcp`) and HTTP (`uvicorn app.api.server:app`) still wrap
the same `toolbelt.py` functions. They are leftover adapters, not the
skill path.

Install: `uv sync --group dev`. `cwd` **must** be this repo so pinned
XSDs (and optional example files) resolve.

## MCP registration (optional)

`.cursor/mcp.json` or `.vscode/mcp.json`:

```json
{
  "servers": {
    "fews-agent": {
      "type": "stdio",
      "command": "uv",
      "args": ["run", "python", "-m", "app.mcp_server"],
      "cwd": "<absolute-path-to-fews-agent-2>"
    }
  }
}
```

Or `command`: `uv`, `args`: `["run", "fews-mcp"]`.

Claude Desktop (`claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "fews-agent": {
      "command": "uv",
      "args": ["run", "python", "-m", "app.mcp_server"],
      "cwd": "<absolute-path-to-fews-agent-2>"
    }
  }
}
```

## HTTP (optional)

```bash
uv run uvicorn app.api.server:app --port 8000
```

`POST /render/spec`, `POST /validate/xml`, `GET /schema/{spec}`,
`GET /examples`. Session routes (`POST /sessions`, `/turn`, `/build`)
are the older chat → blueprint path.

Longer architecture notes: [doc/ADR_mcp.md](doc/ADR_mcp.md).
