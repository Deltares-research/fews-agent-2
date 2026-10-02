# ADR_mcp — Verification-first FEWS agent

Status: accepted (Phases 0–4 shipped; Phase 5 not started).

The host LLM (Cursor, Claude) **fills a typed intermediate representation** (or, as fallback, authors XML). This repo is the **ground-truth toolkit**: schema, render, validate, lint, list IDs, fetch examples. Preferred write path is `fews-check schema-shape` → fill JSON → `render-spec` → `admit`. Pattern → Jinja still exists for manual/legacy calls and is **not** a host route. Patterns are a searchable corpus of farmed shapes — a last snapshot that passed XSD, not operationally correct XML. Procedure lives in repo-local Skills (`.cursor/skills/`). Coding agents call **`uv run fews-check --json`**. FastMCP / HTTP are leftover adapters over the same toolbelt.

Nothing reaches disk unverified. Who wrote the file (pattern / LLM / human) only decides whether it may be regenerated.

## Architecture

```
host LLM  ──fills Pydantic JSON──►  render_spec (Jinja) ──►  gauntlet
        └──raw XML fallback─────────────────────────────►     1 XSD
                                                              2 semantic (cross-file IDs)
                                                              3 conform (naming)
                                                              4 FewsCLI (optional)
            pass → admit_file + ledger     fail → structured diagnostics → repair
```

One Python library; the coding-agent surface is the `fews-check` CLI. MCP and FastAPI are leftover adapters that only serialize `GauntletReport`. Skills are unenforced prose; the gauntlet is the gate.

| Layer | Role | Where |
|---|---|---|
| Procedure | Phases, elicitation, gotchas | `.cursor/skills/` (`fews-config`, `fews-author-file`, `fews-diagnose`) |
| Author | Fill a typed intermediate representation / draft XML | Cursor / Copilot / Claude / ChatGPT — or our `author_file` op |
| Typed intermediate representation | Pydantic JSON → Jinja XML | `render_spec` + 217 SPECS / 230 templates |
| Corpus (not a generator) | Farmed shapes as examples | `patterns/auto/` via `find_examples` |
| Gauntlet | Admit or reject | `fews_agent/validation/` |
| Ledger | Provenance per file | `.fews-agent/ledger.yaml` (`pattern` / `llm` / `human`) |
| CLI | Coding agents (Cursor, Claude) | `uv run fews-check --json` |
| MCP | Leftover local adapter | `python -m app.mcp_server` |
| HTTP | Leftover OpenAPI adapter | `uvicorn app.api.server:app` |

**Existing configs are first-class.** `validate_config(path)` and `open_config(path)` work on any FEWS folder. This agent does not need to have created it. `open_config` only writes the ledger; it does not rewrite XML.

**CLI write path (typed intermediate representation, preferred):** `fews-check id-registry` (if a tree exists) → `schema-shape` → fill JSON → `render-spec` → `admit`. Raw-XML fallback when no spec fits: `schema-shape` + `find-examples` → `validate-xml` → `admit`. Allowed even when a catalog name exists (GFS, Raven, …). Do not invent a pattern. Do not invent IDs. Do not Write XML with the editor. `list_patterns` / `create_project` / `apply_slots` / `build_project` stay on the leftover MCP server for manual/legacy calls and are not a skill route. If `build_project` is invoked anyway, it must not clobber `origin: human` or `origin: llm` files, or a drifted `origin: pattern` fingerprint.

**Why patterns are a corpus, not a generator.** A slightly-wrong pattern is a bad generator (ships wrong XML stamped `origin: pattern`) and a good example (the model adapts it, then must pass the gauntlet). That is why 70 imperfect patterns stop being a maintenance liability.

The older chat / HTTP `/sessions` / `build_from_blueprint` path still works.

## Gauntlet tiers

| Tier | What it answers | Skip if |
|---|---|---|
| XSD | Shape / order / enums vs pinned `fews_agent/schemas/` | no `xsi:schemaLocation` (treated as skip, not fail) |
| Semantic | Do `parameterId` / `moduleInstanceId` / … resolve across files? | no typed models loaded |
| Conform | House naming (see below) | — |
| FEWS check | Does a real FEWS checker accept the tree? | `FEWS_CHECK_CMD` unset |

Set `FEWS_CHECK_CMD` to a command that checks a folder. `{path}` is the generation-tree folder; `{zip}` is a temp Config-only region zip for [FewsCLI](https://publicwiki.deltares.nl/spaces/FEWSDOC/pages/404390665/FewsCLI+utility) `VALIDATE_CONFIG_FILES` (`regionpath=`). If unset, tier 4 emits `fews.unavailable` and never crashes. FewsCLI log lines parse as `fews.config`; an unparsed non-zero exit is `fews.exit`. Shipped disabled until a FEWS install is available — which zip variant `regionpath=` accepts (`config_only` vs region-root `sa_global.properties`) is still empirical.

Conform rules (reported, never auto-fixed on the generation path):

- `conform.csv_attr_pascal` — PascalCase CSV attributeIds
- `conform.idmap_casing` — `idMapId` vs IdMap filename (Linux-safe)
- `conform.filename_id_agreement` — root `@id` vs file stem
- `conform.param_suffix` — `PC.nwp` / `TA.obs` style

Diagnostics are structured (`file`, `line`, `severity`, `rule_id`, `message`, `fix_hint`) so a model can repair without guessing.

## Tools (CLI is the skill path; MCP / HTTP leftover)

| Tool | CLI (`fews-check --json`) | Leftover MCP | Leftover HTTP |
|---|---|---|---|
| Validate a folder | `validate-config PATH` | `validate_config` | `POST /validate/config` |
| Validate a snippet | `validate-xml --xml FILE` | `validate_xml` | `POST /validate/xml` |
| Conform lint | `conform-lint` / `conform-lint-xml` | `conform_lint` / `conform_lint_xml` | `POST /conform` |
| Pinned grammar | `schema-shape SPEC` | `schema_shape` | `GET /schema/{spec}` |
| Typed intermediate representation → XML | `render-spec SPEC --data FILE` | `render_spec` | `POST /render/spec` |
| Example snippets | `find-examples QUERY` | `find_examples` | `GET /examples?query=` |
| Declared / unresolved IDs | `id-registry PATH` | `id_registry` | `POST /ids` |
| Explain a rule | `explain RULE_ID` | `explain_diagnostic` | `GET /diagnostics/{rule_id}` |
| Open existing tree | `open-config PATH` | `open_config_folder` | `POST /open_config` |
| Admit host XML | `admit PATH --from-render FILE` | `admit_file` | — |
| List farmed patterns | — (not a skill route) | `list_patterns` | — |
| New project folder | — (not a skill route) | `create_project` | — |
| Fill slots | — (not a skill route) | `apply_slots` | — |
| Pattern → Jinja → XSD | — (not a skill route) | `build_project` | — |

`spec` is a Pydantic class name, e.g. `TimeSeriesImportRun`, `Workflow`, `IdMap`.

Skill + CLI setup: [.cursor/skills/README.md](../.cursor/skills/README.md). Leftover MCP/HTTP: [README_MCP.md](../README_MCP.md).

### What each tool does

The host LLM fills JSON (or, as fallback, drafts XML); `fews-check` is the ground-truth toolkit. Same functions sit under leftover MCP/HTTP adapters.

```
validate folder ──► open_config_folder → validate_config
                    (+ id_registry if IDs matter)

naming only     ──► conform_lint / conform_lint_xml
                    (prefer validate_config unless naming-only)

pasted snippet  ──► validate_xml

add / edit file ──► id_registry + schema_shape
                    → fill JSON → render_spec
                    fail → explain_diagnostic → repair → re-render
                    ok → admit_file
                    (raw XML fallback: find_examples → validate_xml)
```

The inviolable core for leftover MCP is in FastMCP `instructions` (`fews_agent/agent/mcp_instructions.py`). Coding agents follow `.cursor/skills/fews-config` and call `fews-check`. Ordered calls:

| Situation | Ordered calls |
|---|---|
| Validate a folder | `open_config_folder` → `validate_config` (`id_registry` if IDs matter). No `list_patterns`. |
| Naming only | `conform_lint` / `conform_lint_xml` (prefer `validate_config` unless naming-only) |
| Pasted snippet | `validate_xml` (no cross-file IDs) |
| Add or edit a file | `id_registry` (if a tree exists) → `schema_shape` → fill JSON → `render_spec` → `admit_file`. Raw XML only when no spec fits. |
| Failed gauntlet | `explain_diagnostic(rule_id)` → repair from `fix_hint` → re-validate / re-render. Do not `admit_file` until `ok`. |

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

**`schema_shape(spec)`** — Pinned grammar for one file type: Pydantic JSON schema + a capped XSD fragment + collected enums. The contract the host fills for `render_spec`. Unknown spec fails loudly and returns a sample of known names. Remote-safe.

**`render_spec(spec, data)`** — Validate `data` against the Pydantic class, render the registered Jinja template, run XSD + conform. Returns `{ok, xml, suggested_relpath, diagnostics, validation_errors}`. Pydantic errors are structured `loc`/`msg`, never raised. Read-only — write via `admit_file`. Remote-safe.

**`find_examples(query, k?)`** — Keyword search (no embeddings) over the tutorial, pattern YAMLs, and test fixtures. Returns up to `k` (default 5) path + snippet + provenance. Evidence for a draft (with `schema_shape`), not a generator. Remote-safe.

**`explain_diagnostic(rule_id)`** — Prose + `fix_hint` + citation + example for a gauntlet or conform rule (`xsd.schema`, `semantic.unresolved`, `fews.unavailable`, `fews.config`, `fews.exit`, `conform.idmap_casing`, …). Lets a model repair from a structured `rule_id` instead of guessing. Remote-safe.

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

## Skills

Repo-local `.cursor/skills/` (versioned with the code):

- `fews-config` — orchestrator (entry-point detection + generation ladder)
- `fews-author-file` — elicit, then `schema_shape` / `render_spec` / `admit_file`
- `fews-diagnose` — brownfield gauntlet → `explain_diagnostic` → repair

Canonical reference bodies live in `doc/skill_references/` and are copied into each skill by `scripts/sync_skill_references.py` (`--check` fails CI on drift). Skills are procedure; they never decide a file is correct.

## How to use it

### Cursor / VS Code Copilot

1. Install: `uv sync --group dev`.
2. Register STDIO in `.cursor/mcp.json` or `.vscode/mcp.json`:

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

Or `uv run fews-mcp` after sync. `cwd` must be this repo (patterns + XSDs).

3. In Agent mode, ask to generate or fix a config. The `fews-config` skill (`.cursor/skills/`) carries procedure. Validate a folder with `open_config_folder` → `validate_config`. New files: `schema_shape` → fill JSON → `render_spec` → `admit_file`. On failure: `explain_diagnostic` → repair → re-render. Do not call `list_patterns` first.

### Claude Desktop

Same server. In `claude_desktop_config.json`:

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

On Windows use the full `uv.exe` path if needed.

### ChatGPT / Microsoft Copilot

These hosts cannot open `C:\...` on your laptop. Run the API where the config lives (or paste XML):

```bash
uv run uvicorn app.api.server:app --port 8000
```

Import OpenAPI from `http://<host>:8000/docs`. Primary write: `POST /render/spec` with `{"spec": "Workflow", "data": {…}}`, then admit locally. Also `POST /validate/xml`, `GET /schema/{spec}`, `GET /examples`, `GET /diagnostics/{rule_id}`. Path routes only work if the API process can see that folder.

Session routes (`POST /sessions`, `/turn`, `/build`) are the older greenfield chat → blueprint → build path. They still work; they are not required for verification-only use.

### This repo's own chat agent

A pattern miss can use the `author_file` patch op. The engine drafts XML, runs the gauntlet (one repair round), and writes only on pass (`origin: llm`). Unknown catalog names are dropped loudly and point at `author_file`.

## Typical loops

**Existing config (brownfield)** — the main path:

1. `open_config_folder` / `validate_config` on the folder (no `list_patterns`)
2. `id_registry` if IDs matter
3. Host fills a typed intermediate representation (`schema_shape` → `render_spec`); raw XML only if no spec fits
4. On failure: `explain_diagnostic` → repair from `fix_hint` → re-render until `ok`
5. `admit_file` only after pass
6. `validate_config` again after a weld

Example prompts (Agent mode, fews-agent tools connected):

> Open `C:\configs\coolmunda` and validate it. Report XSD, cross-file IDs, and naming issues. Do not change any file yet.

> In `C:\configs\coolmunda`, add a workflow that runs the existing `ImportGFS` module instance. Look up IDs already declared in this tree, check the Workflow schema, and copy the shape from a similar workflow in the examples. Write the file only after validation passes. If a check fails, explain the rule, repair from the fix hint, and validate again.

> `IdMapFiles/SpecialImport/IdImportGLOBSNOW.xml` fails `conform.idmap_casing`. Explain that rule, then fix the `idMapId` so it matches the filename. Re-validate the folder and stop when the report is ok.

**New file (any source, including GFS / HRDPS / Raven names):**

1. `id_registry` if a tree already exists
2. `schema_shape` → fill JSON → `render_spec` (chat can still use `author_file` for raw XML)
3. `admit_file` (ledger `origin: llm`). Do not invent a pattern.

Example prompts:

> Draft a NOAA GFS import for precipitation and temperature. Look up the TimeSeriesImportRun schema and examples, validate the snippet, and write it with admit_file only after it passes. Copy IDs from the tree if one exists.

> There is no pattern for a Python virtualenv download of ERA5. Draft the general-adapter run XML, validate it (XSD, IDs, naming), and repair until it passes. Write it with origin `llm`.

> Add a "MysteryModel" grid import. Do not invent a pattern. Draft the import XML, run the gauntlet, and keep the file only if it passes.

## File map

| Path | What |
|---|---|
| `fews_agent/validation/gauntlet.py` | Orchestrator |
| `fews_agent/validation/render_spec.py` | Typed intermediate representation → Jinja XML → XSD + conform |
| `fews_agent/validation/fews_bundle.py` | Delivery-layout region zip (`{zip}` / `config_zip`) |
| `fews_agent/validation/fews_check.py` | Tier 4: `{path}` / `{zip}`, FewsCLI log parser |
| `fews_agent/validation/load_tree.py` | Read any config folder |
| `fews_agent/validation/conform.py` | Naming rules |
| `fews_agent/cli/check.py` | `fews-check` coding-agent surface |
| `fews_agent/validation/toolbelt.py` | Shared CLI / leftover MCP / HTTP functions |
| `fews_agent/agent/ledger.py` | Provenance |
| `fews_agent/agent/config_tree.py` | `open_config` |
| `fews_agent/agent/authoring.py` | Gauntlet-gated write (`admit_file` / chat `author_file`) |
| `fews_agent/agent/mcp_instructions.py` | FastMCP namespace hint (typed intermediate representation first; points at the skill) |
| `fews_agent/agent/generation_tools.py` | Path-based list/create/apply/build/admit (legacy; not a host route) |
| `.cursor/skills/` | Procedure (`fews-config`, `fews-author-file`, `fews-diagnose`) |
| `doc/skill_references/` | Canonical skill bodies (synced into each skill) |
| `fews_agent/agent/session_io.py` | `.chat_state.json` load/save |
| `app/mcp_server.py` | Leftover MCP adapter |
| `app/api/server.py` | Leftover HTTP adapter |
| `runners/agent/calibrate_gauntlet.py` | Compare tiers on a folder (`--config`) |
| `README_MCP.md` | Leftover MCP/HTTP registration |
| `doc/gauntlet_calibration.md` | Phase 0 baseline (tier 4 skip unless `FEWS_CHECK_CMD`) |

Calibration (not in default pytest):

```bash
python -m runners.agent.calibrate_gauntlet --config <config-folder> --out doc/gauntlet_calibration.md
```
