# FEWS configuration skills

## Overview

These skills let a coding assistant (Cursor, Claude) **author
Delft-FEWS XML** without writing XML by hand and without trusting farmed
pattern files as a generator.

**Skills carry procedure; `fews-check` carries truth.** The assistant
asks questions and picks the next file. The CLI renders XML and
decides whether it may land on disk.

| Layer | Job | Who owns it |
|---|---|---|
| Skills | When to ask, which file next, the weld | `.cursor/skills/` (this folder) |
| Typed intermediate representation | Fill a JSON object that matches one FEWS file type | Host LLM |
| Render | JSON → Jinja XML (element order, namespaces) | `fews-check render-spec` |
| Gauntlet | Admit or reject | XSD → semantic IDs → conform → optional [FewsCLI](https://publicwiki.deltares.nl/spaces/FEWSDOC/pages/404390665/FewsCLI+utility) |
| Write gate | Disk | `fews-check admit` (`origin: llm`) |

### What is a typed intermediate representation?

A **typed intermediate representation** is a JSON object whose fields
are the Pydantic model for one FEWS file type (`Workflow`,
`TimeSeriesImportRun`, `IdMap`, …) — not the XML itself.

The assistant fills values (`moduleInstanceId`, `parameterId`,
forecast length). Python (`fews-check render-spec`) turns that object
into XML with the registered Jinja template, so **element order,
namespaces, and escaping are unforgeable**. A missing or invented
field fails at Pydantic (`validation_errors` with `loc` / `msg`)
before XSD runs.

Example — the intermediate representation for a one-activity workflow:

```json
{
  "version": "1.1",
  "activity": [
    { "moduleInstanceId": "ImportGFS", "runIndependent": true }
  ]
}
```

`uv run fews-check --json schema-shape Workflow` is the contract
(required fields + enums). `render-spec Workflow --data payload.json`
is the compile step. The XML that comes back is what `admit` writes —
the assistant does not author `<workflow>` tags.

Nothing reaches disk unverified. A skill that drifts from the schemas
produces a rejected draft, not a bad file.

There are **three** skills. Each has a `SKILL.md` (index + Critical
Rules) and `references/` pulled on demand.

| Skill | Description |
|---|---|
| [`fews-config`](fews-config/) | Orchestrator. Detects new project / add a capability / diagnose, then chains the other two. |
| [`fews-author-file`](fews-author-file/) | Workhorse. Phase 1 elicits values; Phase 2 calls `schema-shape` → `render-spec` → `admit`. |
| [`fews-diagnose`](fews-diagnose/) | Brownfield loop. `open-config` → `validate-config` → `explain` → repair → re-validate. |

A read-only consultant skill is deferred until the references
stabilise.

**Limitations of this version**

- Skills load in **Cursor and Claude**. The call surface is the
  `fews-check` CLI (`uv run fews-check --json …`).
- **FewsCLI (gauntlet tier 4) is scaffolded but off** until
  `FEWS_CHECK_CMD` points at a FEWS install. Tiers 1–3 (XSD, semantic,
  conform) always run.
- Open-source full-config examples are a **placeholder**.
  `fews-config/examples/minimal_gfs_import/` is shipped; Conform is
  listed, not vendored. Confidential configs are **never** examples —
  validate them by absolute path.
- Patterns (`fews_agent/patterns/auto/`) stay in the repo as a
  **searchable corpus** (`fews-check find-examples`). They are not the
  write path.
- The MCP server (`fews-mcp`) and HTTP adapter remain in the repo as
  leftover adapters over the same toolbelt. Skills do not name them.

## Architecture

```
  Skills (procedure)          Host LLM              fews-check (truth)
  ─────────────────           ────────              ─────────────────
  fews-config ──┐
  fews-author   ├─►  fill JSON ──► schema-shape
  fews-diagnose ┘         │         render-spec ──► Jinja XML
                          │              │
                          │              ▼
                          │         gauntlet
                          │         1 XSD
                          │         2 semantic (cross-file IDs)
                          │         3 conform (naming)
                          │         4 FewsCLI (optional)
                          │              │
                          └── repair ◄───┤ fail (rule_id + fix_hint)
                                         │
                                         ▼ ok
                                    admit + ledger
```

**Generation ladder** (first rung that applies):

1. **Typed intermediate representation (default).** Fill the JSON
   contract, not XML: `schema-shape` → fill JSON → `render-spec` →
   `admit`.
2. **Raw XML.** Only when no SPECS class fits.
   `find-examples` → `validate-xml` → `admit`.
3. **Pattern as example, not a generator.** Do not call
   `list_patterns` / `create_project` / `apply_slots` / `build_project`
   as the write path.

**The weld.** One capability is several files. No XSD enforces this.
An import is at least: module config + workflow + idMap. Author them
as one unit; run `validate-config` after the last admit.

Longer architecture notes: [doc/ADR_mcp.md](../../doc/ADR_mcp.md).

## Folder structure

```
fews-agent-2/
  .cursor/skills/                         this README + the three skills
    fews-config/                          orchestrator
      SKILL.md
      references/                         synced copies of the shared guide
      examples/
        README.md                         corpus contract (provenance + licence)
        minimal_gfs_import/               self-generated, gauntlet-checked
        fews-conform/PLACEHOLDER.md       open-source slot (not vendored yet)
    fews-author-file/
    fews-diagnose/
  doc/skill_references/                   canonical bodies (CI fails on drift)
  fews_agent/
    cli/check.py                          fews-check (coding-agent surface)
    validation/                           the toolbelt (truth)
      render_spec.py                      typed intermediate representation → XML → xsd+conform
      gauntlet.py  xsd.py  semantic.py  conform.py
      fews_check.py  fews_bundle.py       tier 4, shipped disabled
    schemas/                              258 pinned XSDs
    schema/  generators/templates/        217 SPECS / 230 Jinja templates
    patterns/auto/                        example corpus, not a generator
  app/mcp_server.py                       leftover MCP adapter (not the skill path)
  app/api/server.py                       leftover HTTP adapter
```

Shared references (`generation_ladder`, `the_weld`, `file_set_map`,
`id_conventions`, `conform_rules`, `gotchas`) live in
`doc/skill_references/` and are copied into each skill:

```bash
uv run python scripts/sync_skill_references.py
uv run python scripts/sync_skill_references.py --check
```

## Prerequisites

1. **Python 3.11+** and [uv](https://docs.astral.sh/uv/). This repo
   is uv-managed — `uv sync` then `uv run pytest` / `uv run fews-check`.
   Confirm with `uv --version`. Bare `python -m pytest` uses the
   wrong interpreter on a fresh machine.
2. A coding assistant that loads Cursor Agent Skills (Cursor Agent
   mode is the path this was built for). Claude can use the same
   skills if you copy `.cursor/skills/` into that host's skill dir.
3. Optional: a Delft-FEWS install, only if you want gauntlet tier 4
   ([FewsCLI `VALIDATE_CONFIG_FILES`](https://publicwiki.deltares.nl/spaces/FEWSDOC/pages/404390665/FewsCLI+utility)).
   Without it, tier 4 is `fews.unavailable` (skip, never a crash).

## Setup

```bash
cd fews-agent-2
uv sync --group dev
uv run fews-check --json schema-shape Workflow
```

`--json` is accepted anywhere and is the default. Every command
prints one JSON object. `--data` / `--xml` take a file path, `-`
(stdin), or inline JSON/XML.

Confirm the skills are loaded. In Agent mode:

```
List all skills that are readily available without using another tool or skill
```

You should see `fews-config`, `fews-author-file`, and `fews-diagnose`.

Confirm the CLI:

```
uv run fews-check --json explain xsd.schema
```

## Getting started

### 1. Check an existing config (diagnose)

Open Agent mode. Point at a real folder (brownfield configs are
first-class — this agent does not need to have created them):

> Open `C:\configs\coolmunda` and validate it. Report XSD, cross-file
> IDs, and naming issues. Do not change any file yet.

Expected loop: `fews-check open-config` (ledger only, no XML rewrite)
→ `validate-config` → optional `id-registry`. No `list_patterns`.

If something fails:

> `IdMapFiles/SpecialImport/IdImportGLOBSNOW.xml` fails
> `conform.idmap_casing`. Explain that rule, then fix the `idMapId`
> so it matches the filename. Re-validate the folder and stop when
> the report is ok.

That is `fews-check explain` → repair → re-validate. `admit` only
after pass.

### 2. Add one file to a tree (typed intermediate representation)

> In `C:\configs\coolmunda`, add a workflow that runs the existing
> `ImportGFS` module instance. Look up IDs already declared in this
> tree, fill the Workflow schema, render it, and write the file only
> after validation passes.

Expected loop:

1. `uv run fews-check --json id-registry C:\configs\coolmunda`
2. `uv run fews-check --json schema-shape Workflow`
3. write `payload.json`, e.g. `{"version": "1.1", "activity": [{"moduleInstanceId": "ImportGFS", "runIndependent": true}]}`
4. `uv run fews-check --json render-spec Workflow --data payload.json`
5. `uv run fews-check --json admit C:\configs\coolmunda --from-render render.json`

A worked fragment lives at
[`fews-config/examples/minimal_gfs_import/`](fews-config/examples/minimal_gfs_import/).

### 3. Add a capability (the weld)

> Draft a NOAA GFS import for precipitation and temperature in
> `C:\configs\coolmunda`. Emit the import module, the workflow that
> runs it, and the idMap together. Copy IDs from the tree. Write
> each file only after `render-spec` passes, then validate the folder.

The orchestrator should load `fews-author-file` and refuse to stop
after the first XML. After the last admit it runs `validate-config`
without asking "should I validate?".

### 4. Start from scratch

> Create a new FEWS config at `C:\configs\demo-gfs`. I want a GFS
> import for precip and temperature. Ask me for timezone, map area,
> and download folder before writing.

No `create_project`. Create the destination folder, elicit the
operational values the schema will not guess, then author the weld
one file at a time.

## Example prompts

```
Validate the FEWS config at C:\configs\coolmunda. Do not change files.

What's wrong with this pasted TimeSeriesImportRun XML?

Add a workflow that runs ImportGFS in C:\configs\coolmunda.

Draft a NOAA GFS import for precipitation and temperature. Use
fews-check schema-shape and render-spec; admit only after it passes.

Add a Raven basin model for Liard. Do not invent a pattern. Copy
parameterId / moduleInstanceId from id-registry.

There is no pattern for a Python venv download of ERA5. Draft the
general-adapter run via render-spec (or raw XML if no spec fits),
validate, repair, admit.

Fix conform.idmap_casing on IdImportGLOBSNOW and re-validate.
```

## Tips / best practices

- **Copy IDs.** `fews-check id-registry` before any `parameterId` /
  `moduleInstanceId` / `idMapId`. Casing mismatches pass on Windows
  and break on Linux FEWS.
- **Ask for operational values.** Timezone, download folder, forecast
  length, parameter list. Schema-optional is not operationally-optional.
  XSD will accept a well-formed guess.
- **Do not invent a pattern.** Catalog names (GFS, Raven, …) are fine
  on the `admit` path.
- **Confidential configs** stay out of `examples/` and out of the
  Cursor workspace corpus. `find-examples` ships snippets to the host
  model. Private trees are gauntlet *targets* (`validate-config PATH`).
- **Placeholders stay literal.** `$MODELNAME1$`, `$REGION$` resolve at
  FEWS startup from `sa_global.Properties`.
- **uv.** `uv run pytest tests/test_fews_check_cli.py tests/test_render_spec.py tests/test_skill_examples.py tests/test_skill_frontmatter.py tests/test_mcp_instructions.py -q`

## Appendix — `fews-check` commands the skills call

`--json` is accepted anywhere. Every command prints one JSON object.
Exit `0` when `ok` is true (or the command has no `ok` and no
`error`); exit `1` on failure.

| When | Command |
|---|---|
| Check a folder | `open-config PATH` → `validate-config PATH` (`id-registry` if IDs matter) |
| Naming only | `conform-lint PATH` / `conform-lint-xml --xml FILE` (prefer full validate) |
| Pasted snippet | `validate-xml --xml FILE [--spec SPEC]` |
| New / edit file | `id-registry PATH` → `schema-shape SPEC` → `render-spec SPEC --data payload.json` → `admit PATH --from-render render.json` |
| Failed gate | `explain RULE_ID` → repair → re-render / re-validate |

`SPEC` is a Pydantic class name: `Workflow`, `TimeSeriesImportRun`,
`IdMap`, … — `schema-shape` returns `known_specs_sample` on a miss.

`--data` / `--xml` take a file, `-` (stdin), or inline JSON/XML.
`admit --from-render` reads `xml` and `suggested_relpath` from a
`render-spec` result.

Legacy MCP tools (`list_patterns`, `create_project`, `apply_slots`,
`build_project`) stay registered on the leftover server and are
**not** a host route.
