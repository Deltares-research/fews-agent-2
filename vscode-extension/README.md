# FEWS Config Agent (VS Code extension)

A fourth shell over the `fews-agent-2` chat agent (alongside the CLI, the
Streamlit app, and the HTTP API). It does **not** delegate reasoning to
Copilot's model — the `@fews` chat participant is a UI surface inside the
Copilot Chat panel whose request handler calls this repo's own
`app/api/server.py` (Azure/LiteLLM under the hood). It also gives you a
sidebar for browsing the FEWS XML files the agent generates, live, as the
container (re)builds them.

## What it adds

- **`@fews` in Copilot Chat** — talk to the agent from the IDE. Slash
  commands: `/status` (route position + module build status), `/build`
  (full assembly), `/new` (fresh session).
- **"Generated Files" view** (FEWS Agent activity bar icon) — a read-only
  file tree over the container's `generated/` folder, with an XSD-valid
  badge per file. Opens files as normal read-only editors; right-click →
  "Show diff since last build" opens VS Code's native diff editor. Updates
  automatically after every `@fews` turn or build — no manual refresh.
- **"Project Route" view** — the GPS journey stepper (add a source → choose
  variables → map area → basin adapter → required CSVs → assemble) and the
  green/amber/grey per-module build status.

## Requirements

- VS Code 1.95+ with the GitHub Copilot Chat extension installed and signed
  in (the chat participant surface is part of the Copilot Chat panel; this
  extension does not use Copilot's model for anything).
- The FEWS agent API (`app/api/server.py`) reachable at the URL configured
  in `fewsAgent.apiBaseUrl`.

## Setup

```
cd vscode-extension
npm install
npm run compile
```

Press **F5** in VS Code (with `vscode-extension/` open as the workspace) to
launch an Extension Development Host with the extension loaded.

### Pointing at the API

`fewsAgent.apiBaseUrl` (Settings → search "FEWS Agent"):

- **Local dev**: run `uvicorn app.api.server:app --port 8000` from the repo
  root, leave the default `http://localhost:8000`.
- **Deployed container** (see `../DEPLOY.md`): tunnel in with
  `az ssh vm ... -L 8501:localhost:8501`, then set
  `http://localhost:8501/api` (nginx strips the `/api` prefix in front of
  the bundled container).

## Design notes (why it's built this way)

- **API-mediated only.** The extension never assumes it shares a
  filesystem with the running agent — every read (files, route, module
  status) goes through HTTP. The container's own per-session git tracking
  (`app/project_git.py`) stays entirely server-side; it's used to serve a
  "content before the last build" baseline for diffing (`?rev=prev`), but
  the extension never touches git itself, so your IDE workspace's own git
  repo is never involved.
- **No polling, no server push.** After every `/turn` or `/build` call the
  extension itself makes, it refreshes its own views. That's the whole
  "container regenerated → IDE updates" mechanism for v1 — sufficient
  because the only thing that changes the container's state is this
  extension's own actions.
- **Auth: none, by design, for now.** The API has no auth of its own today
  (see `DEPLOY.md` — access is via SSH tunnel / Entra Easy Auth in front of
  the deployed container). This extension makes plain unauthenticated
  requests, matching that posture. Known gap, not addressed in v1.

## Known limitations

- Desktop VS Code only (uses Node APIs — `Buffer`, `fetch`); not tested
  against the web extension host (vscode.dev / github.dev).
- No CI wiring yet for this package (no Node/TS pipeline exists elsewhere
  in the repo).
