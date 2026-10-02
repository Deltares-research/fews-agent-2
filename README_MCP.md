# FEWS-agent MCP / HTTP toolbelt

Use this repo as a **verification harness** plus a **deterministic generator**
for farmed shapes. The host LLM (Cursor, Claude Desktop, Copilot) talks to
the tools; Python owns XML emission and the gauntlet.

Install: `pip install -e .` (needs the `mcp` extra). `cwd` **must** be this
repo so patterns and pinned XSDs resolve.

## Cursor / VS Code

`.cursor/mcp.json` or `.vscode/mcp.json`:

```json
{
  "servers": {
    "fews-agent": {
      "type": "stdio",
      "command": "python",
      "args": ["-m", "app.mcp_server"],
      "cwd": "<absolute-path-to-fews-agent-2>"
    }
  }
}
```

Or `command`: `fews-mcp` after install. On Windows use the full `python.exe`
path if the server does not start.

## Claude Desktop

`claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "fews-agent": {
      "command": "python",
      "args": ["-m", "app.mcp_server"],
      "cwd": "<absolute-path-to-fews-agent-2>"
    }
  }
}
```

## Two loops

**Known shape** (GFS, HRDPS, GEFS, Raven, … — anything `list_patterns` returns):

1. `list_patterns` — confirm it is farmed.
2. `create_project(path)` — empty session dir, no XML yet.
3. `apply_slots` — `add_import` / `add_basin` / `set_variables`.
4. `build_project` — pattern → Jinja → XSD. **Do not hand-write XML.**
5. `validate_config` on `generated/` if you want the full gauntlet.

**Unknown shape or an existing tree:**

1. `list_patterns` first. If there is no match, do not invent a pattern.
2. Brownfield: `open_config_folder` / `validate_config` / `id_registry`.
3. `schema_shape` + `find_examples` → draft XML.
4. `validate_xml` → repair from `rule_id` / `fix_hint`.
5. `admit_file` writes only on pass (`origin: llm`). A later rebuild will
   not clobber that file.

Never let `build_project` overwrite `origin: human` or `origin: llm` files.

## Remote hosts (ChatGPT / Copilot Studio)

These cannot see `C:\...` on your laptop. Run the HTTP adapter where the
config lives:

```bash
uvicorn app.api.server:app --port 8000
```

Use `POST /validate/xml`, `GET /schema/{spec}`, `GET /examples`. Path routes
only work if the API process can see that folder. Session routes
(`POST /sessions`, `/turn`, `/build`) are the older chat → blueprint path;
they still work.

Longer architecture notes: [doc/ADR_mcp.md](doc/ADR_mcp.md).
