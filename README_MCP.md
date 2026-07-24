# FEWS Agent MCP Server

Expose the FEWS config-generation agent to AI applications like Claude Desktop, VS Code Copilot, and other MCP-compatible clients via the [Model Context Protocol](https://modelcontextprotocol.io/).

## Quick Start

### 1. Get the code and install

An MCP STDIO server runs as a local subprocess, so you need the repository on
your machine (it ships the pattern library and XSD schemas the agent needs).
Clone it and install into a Python 3.11+ environment:

```bash
git clone <your-repo-url> fews-agent-2
cd fews-agent-2
pip install -e .
# or with poetry
poetry install
```

> The folder you clone into is **your** repo root. Everywhere below refers to
> it as `<path-to-fews-agent-2>` — substitute your own absolute path (e.g.
> `C:\Users\you\fews-agent-2`). It does **not** have to match anyone else's.

### 2. Configure credentials (`.env`) — optional

> **The MCP server no longer runs its own LLM.** Editing is done with typed,
> deterministic tools (`add_import`, `add_basin`, …) — *your* MCP client's
> model (VS Code Copilot, Claude Desktop) is the reasoning engine. An LLM is
> only used by the `build` step to draft `Filters.xml`, and that call
> **falls back to a bundled standard** if no provider is reachable. So a
> `.env` is optional; without one, editing and building still work.

If you *do* want the filter drafter to use a model, the server reads its LLM
provider config from a `.env` file in the repo root — the **same file** the
web app uses, and it is **gitignored**, so your keys never get committed. Copy
`.env.example` to `.env` and fill it in:

```properties
FEWS_AGENT_PROVIDER=litellm
AZURE_AI_API_BASE=https://<resource>.services.ai.azure.com/models
AZURE_AI_API_KEY=<your-resource-key>
FEWS_AGENT_MODEL=azure_ai/gpt-5.4-mini
```

Because credentials live in `.env`, **you do not put any keys in the MCP
client config** (`.vscode/mcp.json` / `claude_desktop_config.json`). The
server loads `.env` automatically at startup.

> Prefer OS environment variables or a secret store for shared/production
> keys. A real process env var always wins over `.env`.

### 3. Register with VS Code Copilot

Create a `.vscode/mcp.json` file in your workspace (or add to it if it exists).
No secrets here — `cwd` points the server at your repo root so it finds `.env`
(replace `<path-to-fews-agent-2>` with your clone's absolute path):

```json
{
  "servers": {
    "fews-agent": {
      "type": "stdio",
      "command": "fews-mcp",
      "cwd": "<path-to-fews-agent-2>"
    }
  }
}
```

If `fews-mcp` isn't on your PATH, point at Python directly:

```json
{
  "servers": {
    "fews-agent": {
      "type": "stdio",
      "command": "<path-to-python>",
      "args": ["-m", "app.mcp_server"],
      "cwd": "<path-to-fews-agent-2>"
    }
  }
}
```

Then open the Copilot Chat view, switch to **Agent** mode, and click the tools
(🔧) icon — the `fews-agent` tools appear in the list. Or run
**MCP: List Servers** from the Command Palette to start/stop the server and
view its logs.

> To register the server for **all** workspaces, run **MCP: Open User
> Configuration** from the Command Palette and add the same `servers` block
> there instead of `.vscode/mcp.json`.

> **Finding your paths.** From the repo root, run `pwd` (or `Get-Location` in
> PowerShell) for `<path-to-fews-agent-2>`, and `where fews-mcp` /
> `where python` (Windows) or `which fews-mcp` / `which python` (macOS/Linux)
> for the executables. On **Windows, escape every backslash in JSON** — write
> `C:\\Users\\you\\fews-agent-2`, not `C:\Users\you\fews-agent-2`.

### 4. Register with Claude Desktop

Add to your Claude Desktop config file:

**Windows:** `%APPDATA%\Claude\claude_desktop_config.json`  
**macOS:** `~/Library/Application Support/Claude/claude_desktop_config.json`

```json
{
  "mcpServers": {
    "fews-agent": {
      "command": "fews-mcp"
    }
  }
}
```

If `fews-mcp` isn't in your PATH, use the full path (still no keys — the server
reads `.env` from the `cwd`; replace the placeholders with your own paths):

```json
{
  "mcpServers": {
    "fews-agent": {
      "command": "<path-to-python>",
      "args": ["-m", "app.mcp_server"],
      "cwd": "<path-to-fews-agent-2>"
    }
  }
}
```

### 5. Restart Claude Desktop

Fully quit and restart Claude Desktop. You should see the FEWS agent tools available in the Connectors menu.

## Available Tools

The server is **blueprint-first**: the blueprint (`project.yaml`) plus the
`inputs/` folder are the only things you edit. The generated XML tree is
derived output — never hand-edit it; rebuild instead. Editing is done with
typed, deterministic tools that validate every request against the pattern
catalog and **drop invalid input loudly** (unknown import, unknown model
adapter, bad variable). Your MCP client's model decides *what* to call; the
tools guarantee *what gets written* is valid.

### Project management

| Tool | Description |
|------|-------------|
| `create_project` | Create a new FEWS configuration project. Pass **`workspace_dir`** (absolute path to the user's open IDE folder) so files land in their workspace — see [Workspace output](#workspace-output) |
| `list_projects` | List existing projects (optionally scoped with `workspace_dir`) |
| `get_status` | Get current project state (imports, basins, patterns, absolute paths, build status) |

### Discover capabilities

| Tool | Description |
|------|-------------|
| `list_capabilities` | Every capability that can be added: catalog digest (each pattern's required/optional variables + files produced) plus the canonical import-source names |
| `list_imports` | Available NWP import sources (GFS, HRDPS, ERA5, …) and their pattern paths |
| `list_modules` | FEWS modules and their folder structure |

### Edit the blueprint (typed, deterministic)

| Tool | Description |
|------|-------------|
| `add_import` | Add an NWP/data import: `name` (+ optional `data_types`, `grid_resolution`, `forecast_horizon_hours`). Unknown names/variables dropped loudly |
| `add_basin` | Add a basin model run: `basin_name` + `model_adapter` (`raven`/`wflow`/`hbv96`). An unknown adapter is dropped, never guessed |
| `add_capability` | Add any other pattern from `list_capabilities` (e.g. spatial display, interpolation) |
| `set_variables` | Set variables on an import/basin (`target`) or project-wide (`target=""`): `values` mapping, e.g. `{"grid_resolution": "0p50"}` |
| `remove_item` | Remove an import/basin/capability, or clear one variable (`variable`) |
| `get_blueprint` | Read the current `project.yaml` text + a structured digest (patterns, imports, basins, seeds, inputs, build status). Auto-syncs a hand-edited blueprint back into the session |
| `reload_blueprint` | Force a reverse-sync of a hand-edited `project.yaml` into the session (normally automatic on the next edit tool) |

### Build & validate

| Tool | Description |
|------|-------------|
| `build` | Run the full build pipeline (generate all XML); returns absolute `output_root`, file counts, XSD status. Also snapshots the tree for drift detection |
| `build_phase` | Build a single phase: `imports`, `process`, `model`, or `visualize` |
| `validate` | XSD + cross-reference check over the generated tree **on disk** — catches issues in hand-edited files too, without rebuilding |
| `check_drift` | Detect whether the generated tree was hand-edited since the last build (a rebuild would overwrite those edits) |

## Workspace output

The MCP server's `cwd` must stay on the **agent repo** (patterns, XSDs, `.env`).
Generated FEWS XML does **not** have to — pass the user's open folder as
`workspace_dir` so they can browse the files in their own VS Code workspace.

| `create_project` call | Where sessions + `generated/` go |
|-----------------------|----------------------------------|
| `workspace_dir` set to the user's IDE folder | `<workspace_dir>/fews-projects/<name>/<name>_<timestamp>/` |
| `workspace_dir` omitted | Agent repo `projects/<name>/<name>_<timestamp>/` (same as CLI / web app) |

**VS Code Copilot:** when the user is working in another folder, ask the host
to pass that workspace's absolute path as `workspace_dir` on `create_project`
(and optionally on `list_projects` / `get_status` / `build`). The server also
indexes the session under the agent repo so later edit / `build` calls can
find it by `session_id` alone.

After `build`, tools return absolute `output_root` / `project_dir` — tell the
user that path so they can open `generated/` in the explorer.

Example (user workspace `D:\work\rhine-config`):

```
create_project(
  project_name="rhine-forecast",
  workspace_dir="D:\\work\\rhine-config"
)
→ D:\work\rhine-config\fews-projects\rhine-forecast\rhine-forecast_<timestamp>\
```

## Example Conversation

In Claude Desktop / VS Code Copilot (Agent mode) your client's model reads
your intent and calls the typed tools directly — there is no second agent LLM.

> **You:** Create a FEWS project called "rhine-forecast" in my current workspace

The client calls `create_project` with `project_name="rhine-forecast"` and
`workspace_dir` set to the open workspace folder, then returns the session ID.

> **You:** Add a GFS import with precipitation and temperature, and an HRDPS import

The client calls `add_import(name="GFS", data_types=["precipitation", "temperature"])`
and `add_import(name="HRDPS")`. Each returns the applied notes, anything
dropped, and the refreshed blueprint. (Unsure of the exact name? Call
`list_capabilities` first.)

> **You:** What's configured so far?

The client calls `get_blueprint` (or `get_status`) to show the current
`project.yaml` and resolved patterns, including absolute paths.

> **You:** Build the project

The client calls `build`, then reports the validation results and the absolute
`output_root` to open in the explorer. Follow up with `validate` to re-check
the tree, or `check_drift` to see whether generated files were hand-edited.

## Environment Variables

The MCP server's editing tools are deterministic and need **no** LLM. A
provider is only consulted by the `build` step's filter drafter, which falls
back to a bundled standard if none is configured. When you do configure one,
it uses the same provider config as the web app, loaded from the gitignored
`.env` in the repo root (see `.env.example`):

| Variable | Description | Default |
|----------|-------------|---------|
| `FEWS_AGENT_PROVIDER` | LLM backend: `ollama`, `azure`, `anthropic`, `litellm`, `hf` | `ollama` |
| `FEWS_AGENT_MODEL` | Model ID (for Azure, the deployment name; for `litellm`, a prefixed id like `azure_ai/...`) | `qwen2.5:7b-instruct` |

**For Azure AI via LiteLLM** (the deployed configuration — `FEWS_AGENT_PROVIDER=litellm`):
- `AZURE_AI_API_BASE` — e.g. `https://<resource>.services.ai.azure.com/models`
- `AZURE_AI_API_KEY` — the resource key
- `FEWS_AGENT_MODEL` — e.g. `azure_ai/Llama-3.3-70B-Instruct`

**For the native Azure OpenAI provider** (`FEWS_AGENT_PROVIDER=azure`):
- `AZURE_OPENAI_ENDPOINT`, `AZURE_OPENAI_API_KEY`, optional `AZURE_OPENAI_API_VERSION`

**For Anthropic** (`FEWS_AGENT_PROVIDER=anthropic`):
- `ANTHROPIC_API_KEY`

> **Keep keys in `.env`, not in the MCP client config.** `.env` is gitignored
> so credentials never get committed, and the server loads it automatically.
> A real process env var (or an `env` block in the client config) still wins
> over `.env` if you need to override per-client.

## Session Persistence

- **Default (no `workspace_dir`):** `projects/<name>/<name>_<timestamp>/` under the
  agent repo — same layout as the CLI, web app, and HTTP API.
- **With `workspace_dir`:** `<workspace_dir>/fews-projects/<name>/<name>_<timestamp>/`
  so the user can open generated XML next to their own code. A small session
  index under the agent repo's `projects/.mcp_session_index.json` maps
  `session_id` → absolute path so follow-up tools still resolve the session.

A project started via MCP with the default store can be resumed from any other
interface; workspace-scoped projects are meant to be opened from that workspace.

## Troubleshooting

### "fews-mcp not found"

The script wasn't installed. Either:
1. Run `pip install -e .` in the repo root
2. Use the full path in the config (see example above)

### "Session not found"

You're using an invalid session_id. Use `list_projects` to see valid IDs, or `create_project` to start fresh.
If the project was created with `workspace_dir`, pass the same path to `list_projects` /
`get_status`, or rely on the session index (restarting the MCP server keeps the index on disk
under the agent repo's `projects/.mcp_session_index.json`).

### Generated files are still under the agent repo

`create_project` was called without `workspace_dir`. Recreate the project and pass the absolute
path of the user's open VS Code folder as `workspace_dir`. Restart the MCP server after pulling
this change so Copilot picks up the updated tool schemas.

### "Build reported a filter-drafter warning"

The optional LLM used to draft `Filters.xml` wasn't reachable, so the build
fell back to the bundled standard filter file. The build still succeeds and is
XSD-valid. If you want model-drafted filters, check:
1. For Ollama: is `ollama serve` running?
2. For Azure/Anthropic: are the env vars set correctly in `.env`?

The editing tools (`add_import`, `add_basin`, …) never call an LLM, so they
work regardless.

### Logs

Claude Desktop logs MCP activity to:
- Windows: `%APPDATA%\Claude\logs\mcp*.log`
- macOS: `~/Library/Logs/Claude/mcp*.log`

## Manual Testing

Run the server directly:

```bash
python -m app.mcp_server
```

This starts an STDIO-based MCP server. You can interact with it using the MCP CLI tools:

```bash
mcp dev app/mcp_server.py
```

## Architecture

The MCP server is the **fourth driver shell** (after CLI, Streamlit, HTTP API) over the same agent engine. It is **blueprint-first**: typed tools mutate the blueprint deterministically; no second LLM runs per turn.

```
Claude Desktop / VS Code  (the reasoning model lives here)
        ↓ (MCP/STDIO, typed tool calls)
   app/mcp_server.py
        ↓ (direct call)
   fews_agent/agent/patch_ops.py     ← validate against catalog, drop loudly
        ↓
   project.yaml  (the blueprint — the single editing surface)
        ↓
   runners/agent/build_from_blueprint.py
        ↓  (XSD + cross-reference validation gates every file)
   Generated XML in:
     • <workspace>/fews-projects/.../generated/  (when workspace_dir is set)
     • projects/<name>/.../generated/            (default / agent-repo)
```

No HTTP hop — the MCP server imports and calls the engine functions directly.
A hand edit to `project.yaml` is reverse-synced back into the session
(`load_blueprint_into_state`) so the typed tools and status stay coherent.
