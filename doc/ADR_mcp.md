# ADR_mcp — Verification-first FEWS agent

Status: accepted (Phases 0–4 shipped; Phase 5 not started).

The host LLM (Cursor, Copilot, Claude, ChatGPT) **authors** FEWS XML. This repo is the **ground-truth toolkit**: validate, lint, show schema, list IDs, fetch examples. MCP host routing is **draft + gauntlet only** (`admit_file`). Pattern → Jinja still exists for manual/legacy calls and is **not** a host route. Pattern output is a last farmed snapshot that passed XSD, not operationally correct XML.

Nothing reaches disk unverified. Who wrote the file (pattern / LLM / human) only decides whether it may be regenerated.

## Architecture

```
host LLM  ──writes XML / edits an existing tree──►  gauntlet
                                                      1 XSD
                                                      2 semantic (cross-file IDs)
                                                      3 conform (naming)
                                                      4 FEWS check (optional)
            pass → write + ledger     fail → structured diagnostics → repair
```

One Python library, two adapters. Validation logic is **not** in MCP or FastAPI — those only serialize `GauntletReport`.

| Layer | Role | Where |
|---|---|---|
| Author | Wiki, reasoning, writing XML | Cursor / Copilot / Claude / ChatGPT — or our `author_file` op |
| Fast path (not an MCP host route) | Deterministic XML for farmed shapes | `patterns/auto/` → Jinja → Pydantic → XSD |
| Gauntlet | Admit or reject | `fews_agent/validation/` |
| Ledger | Provenance per file | `.fews-agent/ledger.yaml` (`pattern` / `llm` / `human`) |
| MCP | Local hosts (shared filesystem) | `python -m app.mcp_server` |
| HTTP | Remote hosts (OpenAPI) | `uvicorn app.api.server:app` |

**Existing configs are first-class.** `validate_config(path)` and `open_config(path)` work on any FEWS folder. This agent does not need to have created it. `open_config` only writes the ledger; it does not rewrite XML.

**MCP write path:** `id_registry` (if a tree exists) → `schema_shape` + `find_examples` → draft → `validate_xml` → `admit_file`. Allowed even when a catalog name exists (GFS, Raven, …). Do not invent a pattern. Do not invent IDs. `list_patterns` / `create_project` / `apply_slots` / `build_project` stay registered for manual/legacy calls; FastMCP `instructions` must not steer the host toward them. If `build_project` is invoked anyway, it must not clobber `origin: human` or `origin: llm` files, or a drifted `origin: pattern` fingerprint.

The older chat / HTTP `/sessions` / `build_from_blueprint` path still works.

## Gauntlet tiers

| Tier | What it answers | Skip if |
|---|---|---|
| XSD | Shape / order / enums vs pinned `fews_agent/schemas/` | no `xsi:schemaLocation` (treated as skip, not fail) |
| Semantic | Do `parameterId` / `moduleInstanceId` / … resolve across files? | no typed models loaded |
| Conform | House naming (see below) | — |
| FEWS check | Does a real FEWS checker accept the tree? | `FEWS_CHECK_CMD` unset |

Set `FEWS_CHECK_CMD` to a command that checks a folder; `{path}` is replaced. If unset, tier 4 emits `fews.unavailable` and never crashes.

Conform rules (reported, never auto-fixed on the generation path):

- `conform.csv_attr_pascal` — PascalCase CSV attributeIds
- `conform.idmap_casing` — `idMapId` vs IdMap filename (Linux-safe)
- `conform.filename_id_agreement` — root `@id` vs file stem
- `conform.param_suffix` — `PC.nwp` / `TA.obs` style

Diagnostics are structured (`file`, `line`, `severity`, `rule_id`, `message`, `fix_hint`) so a model can repair without guessing.

## Tools (same on MCP and HTTP)

| Tool | MCP | HTTP | Remote-safe? |
|---|---|---|---|
| Validate a folder | `validate_config(path, tiers?)` | `POST /validate/config` | no — needs a path on the host |
| Validate a snippet | `validate_xml(xml, spec?)` | `POST /validate/xml` | **yes** — use this from ChatGPT |
| Conform lint | `conform_lint` / `conform_lint_xml` | `POST /conform` | xml yes, path no |
| Pinned grammar | `schema_shape(spec)` | `GET /schema/{spec}` | yes |
| Example snippets | `find_examples(query, k?)` | `GET /examples?query=` | yes |
| Declared / unresolved IDs | `id_registry(path)` | `POST /ids` | no |
| Explain a rule | `explain_diagnostic(rule_id)` | `GET /diagnostics/{rule_id}` | yes |
| Open existing tree | `open_config_folder(path)` | `POST /open_config` | no |
| List farmed patterns | `list_patterns(query?)` | — | yes |
| New project folder | `create_project(path, name?)` | — | no |
| Fill slots | `apply_slots(path, ops)` | — | no |
| Pattern → Jinja → XSD | `build_project(path, phase?)` | — | no |
| Admit host XML | `admit_file(path, relpath, xml, spec?)` | — | no |

`spec` is a Pydantic class name, e.g. `TimeSeriesImportRun`, `Workflow`, `IdMap`.

Client registration: [README_MCP.md](../README_MCP.md).

### What each tool does

The host LLM writes XML; these tools are the ground-truth toolkit. Same functions sit under HTTP; MCP is the local-filesystem adapter.

```
validate folder ──► open_config_folder → validate_config
                    (+ id_registry if IDs matter)

naming only     ──► conform_lint / conform_lint_xml
                    (prefer validate_config unless naming-only)

pasted snippet  ──► validate_xml

add / edit file ──► id_registry + schema_shape + find_examples
                    → draft → validate_xml
                    fail → explain_diagnostic → repair → re-validate
                    ok → admit_file
```

Those sequences are baked into FastMCP `instructions` (`fews_agent/agent/mcp_instructions.py` — what the host agent sees). Ordered calls:

| Situation | Ordered calls |
|---|---|
| Validate a folder | `open_config_folder` → `validate_config` (`id_registry` if IDs matter). No `list_patterns`. |
| Naming only | `conform_lint` / `conform_lint_xml` (prefer `validate_config` unless naming-only) |
| Pasted snippet | `validate_xml` (no cross-file IDs) |
| Add or edit a file | `id_registry` (if a tree exists) → `schema_shape` + `find_examples` → draft → `validate_xml` → `admit_file` |
| Failed gauntlet | `explain_diagnostic(rule_id)` → repair from `fix_hint` → re-validate the same surface. Do not `admit_file` until `ok`. |

Hard bans: do not invent a pattern; do not invent IDs (`parameterId` / `moduleInstanceId` / `idMapId`). If `build_project` is invoked anyway, it must not clobber `origin: human` / `origin: llm`. There is no catalog-hit write ban: `admit_file` is allowed even when a catalog name exists.

#### Verification (existing tree or snippet)

**`validate_config(path, tiers?)`** — Full gauntlet on a FEWS folder on disk: XSD, semantic (cross-file IDs), conform (naming), and optional FEWS check (`FEWS_CHECK_CMD`; otherwise `fews.unavailable`, never a crash). `tiers` can restrict that list (`xsd,semantic,conform,fews_check`). Works on any FEWS folder, not just ones this agent created. Not remote-safe.

**`validate_xml(xml, spec?)`** — Same idea for a pasted snippet, no folder. Runs XSD (+ conform). Semantic and FEWS-check are skipped: a lone file cannot resolve sibling IDs. `spec` names the Pydantic class. Remote-safe — this is the tool ChatGPT / Copilot should use.

**`conform_lint(path)` / `conform_lint_xml(xml, spec?)`** — Naming lint only, no XSD/semantic. Rules are reported, never auto-fixed on the generation path:

| Rule | Meaning |
|---|---|
| `conform.csv_attr_pascal` | CSV attributeIds must be PascalCase |
| `conform.idmap_casing` | `idMapId` must match the IdMap filename (Linux-safe) |
| `conform.filename_id_agreement` | root `@id` must match the file stem |
| `conform.param_suffix` | parameters look like `PC.nwp` / `TA.obs` |

Folder vs snippet: path needs the host filesystem; XML is remote-safe.

**`id_registry(path)`** — Walks typed models in a folder and returns declared IDs, all refs, and unresolved refs (`type` / `value` / `source`). Use this before inventing a `moduleInstanceId` or `parameterId`. Generic-body files are invisible to the walker — it says so if nothing typed loaded. Path-only.

**`open_config_folder(path)`** — Brownfield entry. Loads the folder, writes `.fews-agent/ledger.yaml` marking every file `origin: human`, and returns a summary (file count, declared-ID counts, unresolved examples). Does not rewrite XML. A later `build_project` must not clobber `human` or `llm` files.

#### Discovery (what to write / how to fix)

**`schema_shape(spec)`** — Pinned grammar for one file type: Pydantic JSON schema + a capped XSD fragment + collected enums. Antidote to wiki-recalled prose. Unknown spec fails loudly and returns a sample of known names. Remote-safe.

**`find_examples(query, k?)`** — Keyword search (no embeddings) over the tutorial, pattern YAMLs, and test fixtures. Returns up to `k` (default 5) path + snippet + provenance. Evidence for a draft (with `schema_shape`), not a generator. Remote-safe.

**`explain_diagnostic(rule_id)`** — Prose + `fix_hint` + citation + example for a gauntlet or conform rule (`xsd.schema`, `semantic.unresolved`, `fews.unavailable`, `conform.idmap_casing`, …). Lets a model repair from a structured `rule_id` instead of guessing. Remote-safe.

Diagnostics from the gauntlet are structured (`file`, `line`, `severity`, `rule_id`, `message`, `fix_hint`) so a failed check is a repair instruction, not a pile of XML to guess at.

#### Generation tools (registered, not a host route)

These stay on MCP for manual/legacy calls (no HTTP twins). Path is the session key — no `session_id`. FastMCP `instructions` tell the host **not** to use them for new writes.

**`list_patterns(query?)`** — Catalog of farmed patterns: path, name, description, variables, outputs. Filter by keyword. Do not use for new writes; use `admit_file`. Remote-safe.

**`create_project(path, name?)`** — Creates a project folder: `project.yaml`, chat state, empty `inputs/`. No XML yet. Reopening an existing session is a no-op (`reopened: true`). Do not use for new writes.

**`apply_slots(path, ops)`** — Mutates slots via a JSON array of patch ops, then re-resolves patterns:

- `add_import` — e.g. `{"op":"add_import","name":"GFS"}`
- `add_basin`
- `set_variables`
- `add_capability`
- `remove`

Unknown catalog names are dropped loudly (not invented). Writes `project.yaml` + session state. Do not use for new writes.

**`build_project(path, phase?)`** — Expands resolved patterns → Jinja → Pydantic → XSD into `generated/`. Optional phase: `imports` | `process` | `model` | `visualize`. Full build also runs CSV ingest, bundled standards, and derivers. Must not overwrite `origin: human` or `origin: llm` files, or a drifted `origin: pattern` fingerprint. Returns per-file XSD status. Do not use for new writes.

**`admit_file(path, relpath, xml, spec?)`** — Write gate for host-authored XML. Runs XSD + conform; writes only on pass, stamped `origin: llm` so a later rebuild does not delete it. Allowed even when a catalog name exists (GFS, HRDPS, Raven, …). Never invent a pattern.

## How to use it

### Cursor / VS Code Copilot

1. Install: `pip install -e .` (needs `mcp`).
2. Register STDIO in `.cursor/mcp.json` or `.vscode/mcp.json`:

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

Or `command`: `fews-mcp` after install. `cwd` must be this repo (patterns + XSDs).

3. In Agent mode, ask to generate or fix a config. Validate a folder with `open_config_folder` → `validate_config`. New files: `schema_shape` + `find_examples` → `validate_xml` → `admit_file`. On failure: `explain_diagnostic` → repair → re-validate. Do not call `list_patterns` first.

### Claude Desktop

Same server. In `claude_desktop_config.json`:

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

On Windows use the full `python.exe` path if needed.

### ChatGPT / Microsoft Copilot

These hosts cannot open `C:\...` on your laptop. Run the API where the config lives (or paste XML):

```bash
uvicorn app.api.server:app --port 8000
```

Import OpenAPI from `http://<host>:8000/docs`. Primary action: `POST /validate/xml` with `{"xml": "...", "spec": "TimeSeriesImportRun"}`. Also `GET /schema/{spec}`, `GET /examples`, `GET /diagnostics/{rule_id}`. Path routes only work if the API process can see that folder.

Session routes (`POST /sessions`, `/turn`, `/build`) are the older greenfield chat → blueprint → build path. They still work; they are not required for verification-only use.

### This repo's own chat agent

A pattern miss can use the `author_file` patch op. The engine drafts XML, runs the gauntlet (one repair round), and writes only on pass (`origin: llm`). Unknown catalog names are dropped loudly and point at `author_file`.

## Typical loops

**Existing config (brownfield)** — the main path:

1. `open_config_folder` / `validate_config` on the folder (no `list_patterns`)
2. `id_registry` if IDs matter
3. Host writes or edits XML (`schema_shape` + `find_examples`)
4. `validate_xml` (or `validate_config` again)
5. On failure: `explain_diagnostic` → repair from `fix_hint` → re-validate until `ok`
6. `admit_file` only after pass

Example prompts (Agent mode, fews-agent tools connected):

> Open `C:\configs\coolmunda` and validate it. Report XSD, cross-file IDs, and naming issues. Do not change any file yet.

> In `C:\configs\coolmunda`, add a workflow that runs the existing `ImportGFS` module instance. Look up IDs already declared in this tree, check the Workflow schema, and copy the shape from a similar workflow in the examples. Write the file only after validation passes. If a check fails, explain the rule, repair from the fix hint, and validate again.

> `IdMapFiles/SpecialImport/IdImportGLOBSNOW.xml` fails `conform.idmap_casing`. Explain that rule, then fix the `idMapId` so it matches the filename. Re-validate the folder and stop when the report is ok.

**New file (any source, including GFS / HRDPS / Raven names):**

1. `id_registry` if a tree already exists
2. Host drafts XML (`schema_shape` + `find_examples`); chat can use `author_file`
3. `validate_xml` then `admit_file` (ledger `origin: llm`). Do not invent a pattern.

Example prompts:

> Draft a NOAA GFS import for precipitation and temperature. Look up the TimeSeriesImportRun schema and examples, validate the snippet, and write it with admit_file only after it passes. Copy IDs from the tree if one exists.

> There is no pattern for a Python virtualenv download of ERA5. Draft the general-adapter run XML, validate it (XSD, IDs, naming), and repair until it passes. Write it with origin `llm`.

> Add a "MysteryModel" grid import. Do not invent a pattern. Draft the import XML, run the gauntlet, and keep the file only if it passes.

## File map

| Path | What |
|---|---|
| `fews_agent/validation/gauntlet.py` | Orchestrator |
| `fews_agent/validation/load_tree.py` | Read any config folder |
| `fews_agent/validation/conform.py` | Naming rules |
| `fews_agent/validation/toolbelt.py` | Shared MCP/HTTP functions |
| `fews_agent/agent/ledger.py` | Provenance |
| `fews_agent/agent/config_tree.py` | `open_config` |
| `fews_agent/agent/authoring.py` | Gauntlet-gated write (`admit_file` / chat `author_file`) |
| `fews_agent/agent/mcp_instructions.py` | FastMCP host routing (draft + gauntlet) |
| `fews_agent/agent/generation_tools.py` | Path-based list/create/apply/build/admit (legacy; not a host route) |
| `fews_agent/agent/session_io.py` | `.chat_state.json` load/save |
| `app/mcp_server.py` | MCP adapter |
| `app/api/server.py` | HTTP adapter |
| `runners/agent/calibrate_gauntlet.py` | Compare tiers on a folder (`--config`) |
| `README_MCP.md` | Client registration + verification/write loop |
| `doc/gauntlet_calibration.md` | Phase 0 baseline (tier 4 skip unless `FEWS_CHECK_CMD`) |

Calibration (not in default pytest):

```bash
python -m runners.agent.calibrate_gauntlet --config <config-folder> --out doc/gauntlet_calibration.md
```
