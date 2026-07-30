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

### 2. Configure credentials (`.env`)

The MCP server reads its LLM provider config from a `.env` file in the repo
root — the **same file** the web app uses, and it is **gitignored**, so your
keys never get committed. Copy `.env.example` to `.env` and fill it in:

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

### Project Management

| Tool | Description |
|------|-------------|
| `create_project` | Create a new FEWS configuration project. Pass **`workspace_dir`** (absolute path to the user's open IDE folder) so files land in their workspace — see [Workspace output](#workspace-output) |
| `list_projects` | List existing projects (optionally scoped with `workspace_dir`) |
| `get_status` | Get current project state (imports, basins, patterns, route next-step, input readiness, absolute paths) |

### Conversation

| Tool | Description |
|------|-------------|
| `chat` | Send a message to the agent — the main interface for adding imports, models, setting parameters. Returns `wants_build` / `wants_assemble` / `build_scope` so the host knows whether to call `build` or `build_phase`. Slash commands (`/vars`, `/module`, `/list`, `/undo`) bypass the LLM. |

### Build

| Tool | Description |
|------|-------------|
| `build` | Run the full build pipeline (generate all XML files); returns absolute `output_root` |
| `build_phase` | Build a single phase: `imports`, `process`, `model`, or `visualize` |

### Reference

| Tool | Description |
|------|-------------|
| `list_imports` | List available NWP import sources (GFS, HRDPS, etc.) |
| `list_modules` | List FEWS modules and their folder structure |

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
indexes the session under the agent repo so later `chat` / `build` calls can
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

In Claude Desktop / VS Code Copilot (Agent mode):

> **You:** Create a FEWS project called "rhine-forecast" in my current workspace

The client should call `create_project` with `project_name="rhine-forecast"`
and `workspace_dir` set to the open workspace folder, then return the session ID.

> **You:** Add a GFS import with precipitation and temperature, and an HRDPS import

Claude will use `chat` with that message. The agent adds the imports and resolves the patterns.

> **You:** What's configured so far?

Claude will use `get_status` to show you the current state (including absolute paths).

> **You:** Build the project

Claude will use `build` to generate all XML files and report validation results
plus the absolute `output_root` to open in the explorer.

## Environment Variables

The MCP server uses the same provider configuration as the web app, loaded
from the gitignored `.env` in the repo root (see `.env.example`):

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

### "LLM call failed"

The LLM backend isn't reachable. Check:
1. For Ollama: is `ollama serve` running?
2. For Azure/Anthropic: are the env vars set correctly in the MCP config?

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

The MCP server is the **fourth driver shell** (after CLI, Streamlit, HTTP API) over the same agent engine:

```
Claude Desktop / VS Code
        ↓ (MCP/STDIO)
   app/mcp_server.py
        ↓ (direct call)
   fews_agent/agent/llm_turn.py
        ↓
   fews_agent/agent/patch_ops.py
        ↓
   runners/agent/build_from_blueprint.py
        ↓
   Generated XML in:
     • <workspace>/fews-projects/.../generated/  (when workspace_dir is set)
     • projects/<name>/.../generated/            (default / agent-repo)
```

Patterns and XSDs live under `fews_agent/patterns/` and `fews_agent/schemas/`
(same paths the Streamlit app and HTTP API use). No HTTP hop — the MCP server
imports and calls the engine functions directly.

**Build signals from `chat`:** when the model asks to assemble, the response
sets `wants_assemble=true` → call `build`. When it asks for a scoped build,
`wants_build=true` and `build_scope` is a phase name (`imports` / `process` /
`model` / `visualize`) → call `build_phase`.
