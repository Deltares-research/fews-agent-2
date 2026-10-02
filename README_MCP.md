# FEWS-agent MCP / HTTP toolbelt

Use this repo as a **verification harness**. The host LLM (Cursor, Claude
Desktop, Copilot) drafts XML; Python owns the gauntlet. Pattern → Jinja
tools stay registered for manual/legacy calls and are **not** a host route.

Install: `pip install -e .` (needs the `mcp` extra). `cwd` **must** be this
repo so pinned XSDs (and optional example files) resolve.

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

## Verification / write loop

Do **not** start with `list_patterns`. Pattern output is a last farmed
snapshot that passed XSD, not operationally correct XML.

**Validate a folder:** `open_config_folder` (once; ledger only) →
`validate_config`. Add `id_registry` if unresolved IDs matter.

**Pasted snippet:** `validate_xml` (XSD + conform; no cross-file IDs).
Naming only: `conform_lint` / `conform_lint_xml` — prefer
`validate_config` unless the user asked only for house naming.

**Add or edit a file:**

1. `id_registry` if a tree already exists (copy IDs; do not invent them).
2. `schema_shape` + `find_examples` → draft XML.
3. `validate_xml`. On failure: `explain_diagnostic(rule_id)` → repair from
   `fix_hint` → re-validate the same surface.
4. `admit_file` writes only on pass (`origin: llm`). Allowed even when a
   catalog name exists. Do not invent a pattern.

If `build_project` is invoked anyway, it must not overwrite `origin: human`
or `origin: llm` files.

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
