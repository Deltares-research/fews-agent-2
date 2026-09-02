# CLAUDE.md

Guidance for Claude Code when working in this repository.

## Project

An agent that automates generation of Delft-FEWS XML input files. A FEWS
configuration spans roughly 50 interrelated XML files (IdMapFiles, LocationSets,
Parameters, ModuleConfigFiles, Workflows, Import configs, etc.) validated
against FEWS XSDs and cross-referenced by IDs that no XSD enforces.

## Architecture

Split responsibilities by what each tool is good at:

- **LLM** handles the fuzzy front end: conversing with the user, eliciting
  parameters, disambiguating intent, picking the right template, and
  orchestrating generation as tool calls.
- **Python + Jinja2 + lxml** handle XML emission deterministically. Templates
  are the specification. Rendering is a compile step, not an inference step.
- **XSD validation** gates every generated file. Semantic validation
  (cross-file ID references) runs as a second pass before anything is
  returned.

The LLM does not write XML directly in the default path. XML generation is
deterministic, diff-able, unit-testable, and pinned to the FEWS schema
version.

### End-to-end pipeline

The path from natural-language description to a working FEWS config:

```
chat agent (LLM + skills) ──► project.yaml (blueprint)
                                  │
                                  ▼
                        blueprint expander
                                  │
                                  ▼
   ┌─ pattern instances ──► pattern-derived XMLs (~25 files)
   ├─ CSV ingest ────────► Locations.xml, Parameters.xml, ...
   ├─ per-spec yaml inputs (configurator-authored) ─► one XML per yaml
   ├─ LLM filter drafter ─────► Filters.xml
   ├─ bundled standards (+ project-trim) ─► TimeSteps.xml, idMaps, grids,
   │                                         displayGroups
   └─ deterministic derivers ─────────────► Topology.xml, LocationSets.xml,
                                            descriptors, sa_global.Properties
                                  │
                                  ▼
                        XSD validation per file
                                  │
                                  ▼
                          rendered config tree
```

Each stage either succeeds or fails loudly. The runner
(`runners/agent/build_from_blueprint.py`) orchestrates the stages and
prints a per-file table with XSD status (and byte-equivalence vs tutorial
when `--diff-against` is set).

## Design principles

1. **Match the tool to the shape of the problem.** Structured output with a
   rigid schema is a templating problem, not a generation problem. Free-form
   elicitation is an LLM problem. Keep them separate.
2. **Prefer the simplest thing that works.** Reach for complexity only when
   simpler approaches have been tried and shown to fail, with evidence.
3. **Determinism where correctness matters.** Operational forecast configs
   cannot tolerate silent nondeterminism. If two runs with the same inputs
   produce different XML, that is a bug.
4. **Validate twice.** XSD-valid XML is not FEWS-valid XML. Always run the
   semantic reference check.
5. **Fail loudly, never silently.** If generation or validation fails,
   surface the error with actionable context. Never ship unvalidated XML.

## Repository layout

> **Relocation note (2026-07-22):** `patterns/` and `schemas/` now live INSIDE
> `fews_agent/` (`fews_agent/patterns/`, `fews_agent/schemas/`). Older prose in
> this file may still say the root-level paths. The wizard-era stack
> (wizard/checklist/progress/nl_parser/tools/loop/db/TUI + its runners and the
> sessions/ store) was deleted in the LLM-first cleanup — see PLAN.md.

```
fews_agent/
  patterns/                        Pattern library (moved from repo root 2026-07-22)
  schemas/                         FEWS XSDs, pinned (moved from repo root 2026-07-22)
  schema/                          Pydantic v2 models, one module per FEWS spec
    common.py                      FewsModel base + shared types
    ids.py                         Typed id strings (LocationId, WorkflowId, ...)
    <spec>.py                      One module per FEWS file type
    __init__.py                    Re-exports
  generators/
    base.py                        render() helper + Jinja env + filters
    <spec>.py                      Per-spec one-liner generate() wrapping render()
    templates/
      <area>/<spec>.xml.j2         Jinja templates (region, system, module, ...)
      _partials/                   Shared sub-template macros
    __init__.py                    SPECS list — name, model_class, template, output path
  validation/
    xsd.py                         XSD validation via lxml
    semantic.py                    Cross-file reference walker
  agent/
    blueprint.py                   Blueprint dataclass, expander, RenderedFile
    project_chat.py                Chat state, pattern catalog, project.yaml writer
    project_intents.py             Skills, intent ontology, slot-filling, LLM reply
    descriptor_derivation.py       Auto-derive ModuleInstance/Workflow descriptors
    topology_derivation.py         Auto-derive Topology.xml from workflow filenames
    locationsets_derivation.py     Auto-derive id-stub LocationSets.xml
    global_properties_derivation.py  Auto-derive sa_global.Properties
    filter_drafter.py              LLM-drafted filtersFile.xml (qwen2.5)
    standard_inputs/               Bundled fallback yamls (timeSteps, idMaps, ...)
    providers/ollama_provider.py   LLM gateway (qwen2.5 via Ollama HTTP)

runners/
  agent/
    build_from_blueprint.py        Main runner: project.yaml → rendered config tree
    chat_step.py                   Single-turn chat driver
    replay.py                      Re-run a saved chat history

examples/
  config-tutorial/                 Reference FEWS config (regression fixture)
projects/                          Per-project blueprints (one folder per project)
  <project_name>/
    <project_name>_<datetime>/     One snapshot per chat session / iteration
      project.yaml
      inputs/                      Configurator-authored CSVs + yamls
      .chat_state.json, .chat_history.json, _conversation.md
  tutorial/tutorial_2026-05-07_120000/    Reproduces config-tutorial 119/119 byte-equivalent
  small/small_2026-05-07_120000/          Minimal HRDPS+GFS+Liard project (no inputs/)
validation/                        Per-project rendered output (gitignored)
```

## Working conventions

### Adding a new generator

1. Start from the XSD fragment for the target element, not from an example
   file alone. Examples miss optionals, cardinality, and enum constraints.
2. Define a typed parameter dict (Pydantic model preferred) as the
   generator's input contract.
3. Compose shared partials rather than duplicating sub-structure.
4. Every generator ends with XSD validation before returning. No exceptions.
5. Add at least one test that renders a realistic parameter dict and
   validates it.

### Editing templates

- FEWS XSDs use `xsd:sequence` — element order matters. Do not reorder.
- Escape user-supplied strings. Prefer `|e` or build with lxml for anything
  involving untrusted content.
- Namespace declarations stay on the root element and match the pinned
  schema version exactly.

### When something feels like it needs an LLM

Ask first whether it's actually an elicitation problem (LLM-appropriate) or
a generation problem (templating-appropriate). If the output has a schema,
default to templating. Reach for LLM generation only for genuinely novel
structures outside the templated set, and even then:

- Put the XSD fragment in context, not just examples.
- Generate into a typed intermediate representation, not raw XML.
- Run the validate-repair loop with a capped retry count.
- Fall back to a clear error if retries exhaust.

### Cross-file references

FEWS IDs (locationId, parameterId, moduleInstanceId, etc.) must resolve
across the config set. The semantic validator maintains the authoritative
set of declared IDs per config. A generator that references an ID not in
that set should fail fast.

## What to avoid

- Writing XML by string concatenation outside templates.
- Skipping XSD validation "just for this one."
- Adding a template for a file type that changes once a year; patch the
  base config instead.
- Introducing runtime LLM calls on the hot path for file types that have
  working templates.
- Coupling to a specific LLM model without pinning the version.

## Testing

- Every generator has a round-trip test: params -> render -> XSD validate.
- Semantic validation runs across the full generated config set in
  integration tests.
- Regression fixtures live in `tests/fixtures/` and are real configs known
  to work in FEWS. Changes to templates or prompts must not break them.

## Known findings in `examples/config-tutorial/`

The semantic validator (`fews_agent/validation/semantic.py`) walks the
loaded Pydantic models after rendering and reports unresolved cross-file
ID references. Running it over all 119 tutorial files surfaces three
known issues — they exist in the hand-authored tutorial, not in our
generators, and they are expected to appear in the run summary:

- **`IdImportGlobSnow` casing mismatch.**
  `ModuleConfigFiles/Import/Snow/ImportGLOBSNOW.xml` references
  `<idMapId>IdImportGlobSnow</idMapId>`, but the declaring file is
  `IdMapFiles/SpecialImport/IdImportGLOBSNOW.xml` (all caps). Works on
  Windows (case-insensitive FS), breaks on Linux FEWS.

- **Grid names used as `locationId` (`HRDPS`, `HRDPA`).**
  `ImportHRDPS.xml` and `ImportHRDPA.xml` put `<locationId>HRDPS</locationId>`
  / `HRDPA` in their timeSeriesSets. Corrected 2026-08: these aren't
  declared **anywhere** in the real tutorial reproduction — not in
  `Locations.xml`, not in `LocationSets.xml` either (an earlier version of
  this note claimed LocationSets.xml; checked the actual file, it isn't
  there). A genuine tutorial-fixture gap, left as-is for the same
  byte-equivalence reason as the other two. For a **fresh, non-tutorial**
  project this specific gap is now closed: `build_from_blueprint.py`
  auto-stubs a plain `<location id="X">` entry into `Locations.xml` for
  every NWP grid name the project's imports reference and nothing else
  declared (see "Stub grid locationIds", `_stub_missing_grid_locations`/
  `_stub_missing_grid_locations_model`) — grid names belong in
  `Locations.xml`, never `LocationSets.xml`, matching the real config's own
  convention for `GFS`/`RDPS`/`GDPS`/etc.

- **Module instances referenced by workflows but never declared (23 refs).**
  Several workflow files invoke moduleInstanceIds that no module-config
  filename and no `ModuleInstanceDescriptors.xml` entry declares. The
  cluster spans 7 distinct ids:
  - `ImportRDPSforHistoricMerge` (1 ref, MergeHistoricGrids workflow)
  - `ImportSREF` (1 ref, ImportSREFGrids workflow)
  - `PreprocessHRDPS` (3 refs, ImportHRDPSGrids workflow)
  - `PreprocessRDPSforHistoricMerge` (8 refs, MergeHistoricGrids +
    UpdateHistoricGrids workflows)
  - `RetrieveRDPA` (1 ref, UpdateHistoricGrids workflow)
  - `RetrieveRDPSforHistoricMerge` (2 refs, MergeHistoricGrids +
    UpdateHistoricGrids workflows)
  - `RetrieveSREF` (1 ref, ImportSREFGrids workflow)
  - `SnareHistoric` (2 refs, SnareForecastTemplate +
    SnareHistoricTemplate's exportStateActivity)

  The total of 1 + 3 + 23 = 27 matches the runner's "27 unresolved"
  count. Likely genuine tutorial bugs or an implicit FEWS convention we
  haven't captured.

When adding a new generator or editing templates, these three clusters
should stay at the expected counts. A change in any other unresolved
reference indicates a new content regression worth investigating.

**Why we don't fix them.** Fixing any of the three would require editing
the input JSON (changing `IdImportGlobSnow` → `IdImportGLOBSNOW`, adding
HRDPS/HRDPA locations, adding PreprocessHRDPS/HRDPA module instance
descriptors). That would break C14N equivalence against the tutorial
XML, which is the stronger regression oracle. The tutorial is the
fixture; its bugs are part of the fixture. When we generate a
non-tutorial config, these bugs disappear because the new input won't
carry them — and the semantic report is how we'll confirm that.

## Notes for Claude Code specifically

- When asked to add a generator, read the XSD first, then one or two
  example files, then write the template and generator together with tests
  in the same change.
- When asked to "just generate some XML," push back and ask whether a
  template should exist for this file type instead.
- Prefer small, composable partials over large monolithic templates.
- If a change would require loosening validation to pass, stop and flag it
  rather than loosening validation.

## Patterns and the blueprint

A **pattern** is a reusable bundle of FEWS files for one capability
(e.g. "import HRDPS forecasts", "run a Raven basin model"). It lives in
`patterns/auto/<name>/pattern.yaml` with:

- `variables`: typed slots the user fills in (`basin_name: str`,
  `nwp_name: str`, ...).
- `outputs`: list of files to render. Each entry has a `schema` (a
  Pydantic class name from `fews_agent.schema`), an `output` path
  (Jinja-templated against variables), and a `data` payload (also
  Jinja-templated).
- `contributions` (optional): payloads merged into singleton files
  (e.g. each Import pattern contributes one `<idMap>` row to
  `IdMapDescriptors.xml`).

A **blueprint** (`project.yaml`) lists which patterns to instantiate and
with which variable values:

```yaml
name: liard-project
output_root: ../../../validation/liard/generated
patterns:
  - pattern: auto/nwp_grid_eccc_HRDPS
    instances: [{nwp_name: HRDPS}]
  - pattern: auto/raven_basin
    instances: [{basin_name: Liard}]
singleton_seeds:
  Locations:
    geoDatum: WGS 1984
```

The blueprint is the **only** project-level artefact the configurator
must keep in version control. Everything else is either inputs in
`inputs/` or derived from the rendered output.

## FEWS-Conform pattern families

A batch of patterns farmed from the **FEWS-Conform** reference config
(`Deltares/FEWS-Conform` — Australian Coolmunda; ECMWF/GFS/ERA5/IMERG/
GEFS/GHCND imports; a DIMR-style Wflow). This is a **different source
lineage** from the older library (which was farmed from the ECCC/Canadian
tutorial + FEWS-Caribbean), so it added capabilities the library lacked.
Each was derived directly from the Conform source XML, is XSD-validated for
every variant, and has a round-trip test (the durable oracle — the
`projects/` fixtures are gitignored). All are tracked via the
`!patterns/auto/**/*.yaml` negation.

| Pattern | Capability | Key vars / notes |
|---|---|---|
| `archive_export_netcdf` | Export time series to the Open Archive as NetCDF (`exportArchiveModule`) + `To_Archive_<Name>` workflow | `export_kind` (`exportExternalForecast` grid / `exportObserved` scalar); type/mode derived from it |
| `archive_import` | Import from the Open Archive (`importArchiveModule`) + `From_Archive_<Name>` workflow | `categories` list → per-kind blocks (ts-cats share a `timeSeriesSetIdMap`; `historicalEvents` uses `idMapId`) |
| `download_via_python_venv` | "Call an external Python venv / CDS API" `generalAdapterRun` (from `DownloadEra5`) | credential-preserving purge, `runinfo.xml` Area/Parameter, venv `executeActivity`; `source_name`-driven |
| `import_era5` | ERA5 (Copernicus) reanalysis import+process chain (5 artifacts) | folder-based NetCDF import (pairs with `download_via_python_venv`) → `forecastLengthEstimator` → grid→scalar `closestDistance` |
| `import_imerg` | NASA GPM IMERG satellite precip, Early/Late/Final | `product` bakes the `$ImergPostfix$/$ProductForUrl$/$UrlDash$` encoding; **rate→accumulation `meanToMean`** before interpolation |
| `nwp_grid_noaa_gefs` | NOAA GEFS ensemble import | two `<import>` blocks (perturbed `gep%COUNTER(01-30-1)%` + control `gec00`), `ensembleId`/`synchLevel` tagged |
| `tpl_generate_reference_et` | Penman-Monteith / Makkink reference ET (`user/simple` formula transforms + `coefficientSet`) | `tpl_` shared template (FEWS `$PLACEHOLDER$`s literal); `simulation_type` switches type/mode/view |

ECMWF ECWAM **waves** was added as an instance of `nwp_grid_ecmwf_ifs`
(not a new pattern) via new `s3_subpath` (`oper`/`wave`) + `module_suffix`
(`Meteo`/`Waves`) knobs — see "One pattern per *shape*, not per instance".

**Alignment features shipped alongside** (opt-in, oracle-safe — gated so
the byte-equivalent tutorial is untouched):

- **csvFile LocationSets** (`metadata.locations_as_csvfile`): reference
  `locations.csv` in place from a `LocationSet`'s `<csvFile>` and promote
  every non-reserved column to a location `<attribute>` (Conform's "column
  header *is* the attributeId"), suppressing `Locations.xml`. Auto-matches
  an interpolation target set; merges into an existing `LocationSets.xml`.
  See `locationsets_derivation.locationset_csvfile_body`.
- **CSV header lint** (`csv_ingest.lint_conform_headers`): warns on
  non-PascalCase / duplicate attributeId columns; scoped to locations so
  minimal lowercase CSVs stay silent.
- **Widened CSV aliases**: `FewsId`/`Alt` (locations), `allowMissing`/
  `displayUnit`/`parameterGroupName` (parameters) — Conform-shaped CSVs no
  longer drop ids/altitude/fields. Fixture: `tests/fixtures/conform_inputs/`.
- **ModuleInstanceSets + split Filters** for `raven_basin`
  (`conform_module_instance_sets`): group the basin's runs into a set that
  a split `Filters<Basin>.xml` references via `<moduleInstanceSetId>`.
- **Per-basin identity** for `raven_basin` (`basin_local_ids`): replace the
  farmed `$MODELNAME1$/$MODELNAME2$` project-global placeholders with
  `basin_name`-derived ids (fixes the single-basin `$MODELNAME2$`-unresolved
  runtime bug + enables wildcards). Off = byte-identical.
- **Model-asset stubs** (`model_asset_stubs`, opt-in
  `metadata.emit_model_asset_stubs`): detect general-adapter model runs and
  loudly flag / scaffold the external ColdState + ModuleDataSet files no
  layer generates (Conform folders-ending-in-`.zip`).

### Farming gotchas (recurring — hit while farming the above)

- **Dict-typed pattern variables break variable discovery.** The
  empty-context discovery pass raises on `{{ dict.field }}`. Flatten to
  scalar vars (`period_unit`, not `relative_period.unit`). Iterating a list
  of dicts is fine (0 iterations during discovery → no access).
- **A Jinja var in YAML *key* position** (`- {{ export_kind }}:`) renders
  to `- :` during discovery → give it a non-empty fallback via a
  top-of-file `{% set ek = export_kind or '...' %}`.
- **`{% set %}` must be at the very top of the file** — mid-file placement
  throws `'x' is undefined`.
- **Typed vs generic-body rendering.** Inside a *typed* schema
  (GeneralAdapterRun, TimeSeriesImportRun, TransformationModule), `timeStep`
  takes plain `unit`/`multiplier` — **not** the `@unit` generic-body form.
  A `transformation.body` dict *is* generic, so attributes there need
  `@id`/`@value` (e.g. `coefficient`), and each transform nests under
  `body:`.
- **`extra="forbid"`.** Fields the schema doesn't model are rejected, not
  ignored — e.g. `GeneralAdapterGeneral` has no `importUnitConversionsId`,
  `PurgeActivity` no `description`, `Tolerance` no `locationId`. Omit them
  (usually a redundant/default element).

## Auto-generation layers

The runner produces FEWS XML from five sources, applied in order. Files
emitted by an earlier source win; later sources only fill gaps.

| Order | Source | Contents |
|---|---|---|
| 1 | Pattern expansion | ~25 XMLs per project (workflows, imports, preprocess, model runs) |
| 2 | CSV ingest | `Locations.xml`, `Parameters.xml`, `Qualifiers.xml`, `ThresholdWarningLevels.xml` (from per-spec CSVs in `inputs/`) |
| 3 | Per-spec yaml inputs | One XML per `inputs/<spec>.yaml` (configurator-authored: modifierTypes, locationIcons, ...) |
| 4 | LLM filter drafter | `Filters.xml` proposed from project's IDs (qwen2.5; falls back to bundled standard if it fails) |
| 5 | Bundled standards (`standard_inputs/`) | timeSteps, idMaps, gridsFile, displayGroupsFile, unit conversions — universal or near-universal defaults, project-trimmed by referenced IDs |
| 6 | Deterministic derivers | Descriptors (ModuleInstance, Workflow), Topology, LocationSets stub, sa_global.Properties — generated from rendered XML state |

A configurator-provided yaml in `inputs/` always wins over a bundled
standard; a deterministic deriver fires only if no earlier source
produced its target file.

## Bundled standards

`fews_agent/agent/standard_inputs/` holds hand-authored yamls for
configuration that almost never varies per project (timeSteps,
unit conversions, idMaps for common data sources). They render through
the same per-spec template path as user-provided yamls.

Two important behaviours:

1. **Project-trimmed content filtering.** For idMaps, gridsFile, and
   displayGroupsFile, the runner walks rendered XMLs to find which
   IDs the project actually references, then filters the bundled
   yaml's body to drop entries that won't resolve. A safeguard
   prevents an empty result from passing through (returns the
   unfiltered body if filtering would empty the file).
2. **Placeholders are kept literal.** Bundled standards contain
   FEWS-runtime placeholders (`$MODELNAME1$`, `$DAY_TIMESTEP$`, ...)
   verbatim. They're resolved by FEWS at startup from
   `sa_global.Properties` (see below) — not by our agent.

Adding a new bundled standard: drop a `<spec_name>.yaml` into
`standard_inputs/` matching the spec's `input_key`. The runner picks
it up automatically.

## Deterministic derivers

Each deriver walks the already-rendered XMLs and produces one output
file deterministically. They're project-aware (they adapt to the
project's actual workflows, IDs, basin names) but contain no LLM
inference.

- **`descriptor_derivation.py`** — emits
  `ModuleInstanceDescriptors.xml` and `WorkflowDescriptors.xml` from
  module IDs found in rendered XMLs and workflow filenames.
- **`topology_derivation.py`** — emits `Topology.xml` by grouping
  workflow filenames by category prefix (Import/Run) and basin/model
  name. Includes a static "Information Sources" subtree.
- **`locationsets_derivation.py`** — emits a stub `LocationSets.xml`
  with one `<locationSet id="X"/>` per non-placeholder
  `locationSetId` reference. The configurator backs each set with
  csv/shapefile data later.
- **`global_properties_derivation.py`** — emits
  `RootConfigFiles/sa_global.Properties` (text, not XML) with
  `MODELNAME1`/`MODELNAME2` from basin pattern instances and
  `TIMEZONE`/`REGION` from singleton seeds.

A deriver only fires when no earlier source produced its output.
Configurator-provided files always win.

## LLM filter drafter

`filter_drafter.py` is the only LLM call on the generation path (the
chat agent is the only one in the elicitation path). It takes the
project's moduleInstanceIds + parameterIds (extracted from rendered
XMLs) and asks qwen2.5 for 3-6 filter group proposals, validates the
result (drops any IDs the LLM hallucinated), and renders to
`Filters.xml`. If the LLM fails or output is invalid, the runner falls
back to the bundled standard `filtersFile.yaml`.

This is the canonical example of "templating where structure is
known, LLM where intent is genuinely fuzzy" — filter group taxonomy
is a project-intent decision (no deterministic answer), but the
filter XML structure is a templating problem.

## FEWS runtime placeholders (`$MODELNAME1$`, etc.)

FEWS resolves placeholders like `$MODELNAME1$`, `$REGION$`,
`$TIMEZONE$`, `$DAY_TIMESTEP$` at startup from
`RootConfigFiles/sa_global.Properties`. Both pattern outputs and
bundled standards keep these placeholders **literal** in their
rendered XML — that's by design. The tutorial does the same.

The agent-side responsibility is to produce a `sa_global.Properties`
file that maps every placeholder to a project-specific value. The
deterministic deriver
`global_properties_derivation.derive_global_properties` handles this:
it reads the blueprint and emits `MODELNAME1`/`MODELNAME2` from basin
instances, `TIMEZONE` from singleton seeds, derives
`DAY_TIMESTEP=day_<TIMEZONE>` etc.

**Do not** "fix" placeholders by substituting them into the XML at
config-author time. They're FEWS-owned, not agent-owned.

## Chat agent (shared `turn_engine` + three driver shells)

There are **three driver shells** — the CLI (`runners/agent/chat_step.py`),
the Streamlit app (`app/chatter.py::ChatSession`), and the HTTP API
(`app/api/server.py`) — but they share a **single per-turn pipeline**,
`fews_agent/agent/turn_engine.py`, and a **single module-mode turn**
(`turn_engine.run_module_turn`). The shells differ only where they
legitimately must (command sets, I/O, persistence, provider resolution,
app-only meta-intents like greeting/help/status/undo/reset/preview/pre-flight);
the elicitation *logic* lives in one place so it can't drift (it did, twice,
before the pipeline unification — and again with module-mode, which the API
shell missed entirely until `run_module_turn` was extracted).

**`turn_engine.run_turn_pipeline(state, message, catalog, *, provider,
inputs_dir, nag_suppression=False) -> PipelineResult`** runs Phases 1–5
(below), mutating `state` in place and returning the reply + diagnostics.
It does **no** history/log/save/print I/O and resolves no provider — each
driver passes its own `provider` + `inputs_dir` and owns persistence +
output rendering. On a disambiguation short-circuit it returns
`PipelineResult(short_circuit=True, agent_message=<question>)` and the
driver renders that; otherwise it returns the composed reply. The module
also owns the pipeline-exclusive helpers (`forced_intent_override`,
`apply_edit_action`, `apply_disambiguation_answer`, `resolve_patterns`,
`_format_internals`, `_IMPORT_LABEL_KEYS`). The LLM seams
`classify_intent` / `compose_reply` are referenced from turn_engine's
namespace — **tests patch `turn_engine.classify_intent` /
`turn_engine.compose_reply`** (one seam for both drivers); driver-level
seams (`chat_step.OUTPUT_ROOT`, `chatter.check_ollama_for_model`,
`chatter.get_provider`) stay on their modules.

Each driver: append user msg → `apply_disambiguation_answer(state, msg)`
→ its own command dispatch (+ app-only meta-intents/pre-flight) → resolve
provider → `run_turn_pipeline(...)` → render `PipelineResult`. The CLI
appends its next-phase nudge (console-only, no app equivalent); the app
maps `PipelineResult` → `TurnResult`. **When adding an elicitation-phase
feature, change `turn_engine` once — never re-port into both shells.**

The flow per turn (Phases 1–5, in `run_turn_pipeline`):

1. **Skills** (deterministic regex extractors): `extract_skills(text)`
   pulls structured facts — basins, model adapters (raven/wflow/hbv96),
   imports (HRDPS/GFS/...), geo datum, locations source, plus the
   prose-driven NWP slots: `data_types` (wind speed → WS10.nwp etc.),
   `wants_interpolation`, `region` (gazetteer of named regions),
   `custom_bbox` (free-form lat/lon with hemisphere markers),
   `grid_resolution` (NOAA 0p25/0p50/1p00), `forecast_horizon_hours`.
2. **Intent classification** (LLM, only on first turn): qwen2.5/HF
   picks one of `build_forecasting_project`, `build_data_import_only`,
   `build_basin_model_only` based on the user's prose. Falls back to
   a heuristic on filled slots if the LLM output is unparseable.
   **Mid-conversation override**: subsequent turns can re-classify the
   intent if the user types a strong intent-naming phrase ("data
   import only", "no basin model", "no model"). The override clears
   `state["patterns"]` so the resolver rebuilds from current slots.
   Without this, an early misclassify locks the conversation onto the
   wrong template set.
3. **Slot filling** (additive): merges skill output into project state
   without overwriting explicit user-set values. Includes cross-turn
   promotion: if `basin_name` and `model_adapter` were filled in
   different turns, synthesise the canonical `basins` list slot.
4. **Intent disambiguation gate** (deterministic; see below): when the
   request names *exactly one* half (imports XOR basin model) with no
   explicit narrowing/forecasting signal, ASK an either/or question and
   short-circuit the turn instead of silently defaulting to the full
   forecasting project.
5. **Pattern resolution**: the active intent's `resolver` maps
   `(slots, catalog) → list of pattern instances`. Each intent owns
   its own resolver in `project_intents.py`.
6. **LLM reply** (`compose_reply`): qwen2.5 phrases the user-facing
   acknowledgment + question. The system prompt is hardened against
   fabrication: it gets a KNOWN/UNKNOWN slot split and a rule that
   values under UNKNOWN must not appear in the reply.

State persists under
`projects/<project>/<project>_<datetime>/.chat_state.json`. Special commands:
`done` writes the project.yaml (validates intent readiness first);
`yes`/`no` confirm a proposed pattern removal.

**`projects/` is the single, shared session store for all three shells.**
The CLI (`_resolve_project_dir`), the HTTP API (`_new_session_dir`), and the
Streamlit app all persist under `projects/<name>/<name>_<datetime>/`, so a
project started in any shell is resumable in the others. The Streamlit app
opens on a **project picker** (`web_app._render_project_picker`, gated before
the chat renders): *New project* (name → `new_project_session_dir`) or *Load
existing* (dropdown of `list_projects` → `latest_project_session_dir` resumes
the newest session). `list_projects` only surfaces folders that carry a
`.chat_state.json`, so build-only regression fixtures (tutorial/small) stay
out of the picker. The app's old username-keyed `sessions/` store is retired
(the `SESSIONS_ROOT` helpers remain in `chatter` but are no longer wired into
the UI). Helpers live in `app/chatter.py`
(`list_projects`/`new_project_session_dir`/`latest_project_session_dir`/
`safe_project_name`); tested in `tests/test_project_store.py`.

### Ask on ambiguous intent (Phase 3.5 gate)

The default-to-forecasting bias used to silently promote a single-half
request (e.g. "import GFS grids", no model) to the full forecasting
project. The gate replaces that silent default with a question — the
agent refuses to guess when the intent is genuinely ambiguous.

The taxonomy lives in `project_intents.py` (pure, unit-tested, no LLM):

- **`intent_disambiguation_needed(prose, slots) → "imports" | "basin" |
  None`.** Ambiguous only when *exactly one* half is present
  (`imports` XOR `basins`/`basin_name`) AND the prose carries neither an
  explicit narrowing signal (`_prose_signals_narrower_intent` —
  "imports only", "no basin model", "data viewer", "interpolate to
  stations", ...) nor a forecasting signal (`_prose_signals_forecasting`
  — "full project", "forecasting", "end-to-end", ...). Both halves
  (→ forecasting) or neither (→ normal slot elicitation) return `None`.
- **`intent_disambiguation_question(which)`** — the fixed either/or text.
  Deliberately **not** LLM-composed, so the disambiguation never drifts.
- **`parse_intent_disambiguation_answer(text) → intent | None`** — maps
  the reply onto an intent: bare `a`/`b` shorthands (with optional
  punctuation / "option "), then natural phrasings ("imports only",
  "the full project", ...). `None` when the answer isn't a clear choice.

The wiring lives in `chat_step.py` as two pieces around the resolve step:

- **Top answer-handler** (before command dispatch): when
  `awaiting_intent_disambiguation` is set, this turn's message is the
  answer. Parse it (falling back to `forced_intent_override`); on a
  clear choice, commit `state["intent"]`, latch `intent_disambiguated`,
  clear `state["patterns"]` (the resolver rebuilds from slots), and fall
  through. An unclear answer just clears the awaiting flag and falls
  through so the gate below re-evaluates against this turn's (possibly
  fuller) slots.
- **Phase 3.5 gate** (after slot-fill, before resolve): if not yet
  `intent_disambiguated` and the request is ambiguous, ASK — append the
  question to history, `_save`, print it, and `return 0` (no resolve, no
  `compose_reply`). Re-asks are capped at `intent_disambiguation_asks`
  >= 2, after which it falls back to `build_forecasting_project` with a
  visible note rather than looping.

State keys: `awaiting_intent_disambiguation`, `intent_disambiguated`
(latch — once set, the gate never re-asks), `intent_disambiguation_asks`
(re-ask counter), `intent_disambiguation_which`.

**Why the question is deterministic, not LLM-composed:** disambiguation
is a control-flow decision, not phrasing — drift here would change which
patterns get built. The gate fires *before* `compose_reply`, so the
elicitation LLM never sees the ambiguous turn.

Existing fixtures are unaffected: their turn-1 prose all carries a
narrowing signal, a forecasting signal, or both halves (a parametrized
regression in `tests/test_intent_disambiguation.py` pins this, since the
`projects/` fixtures are gitignored and absent on a fresh clone). Tests:
`tests/test_intent_disambiguation.py` (pure helpers + fixture-prose
regression) and `tests/test_intent_disambiguation_turn.py` (the turn
loop end-to-end with `classify_intent` / `compose_reply` stubbed — no
Ollama).

### Vocabulary: "prose filtering" vs "skills"

The word **skill** was reclaimed this session — mind the two distinct
concepts:

- **Prose filtering** — the old regex layer. Deterministic functions
  `text → value` (`detect_*`, aggregated by `filter_prose`, formerly
  `extract_skills`) that scan prose and surface known tokens (basins,
  imports, data types, ...). They **decide and act on nothing** — their
  output fills slots via the additive merge and is *not* fed to the LLM.
- **Skills** — intent-connected **actions**. A skill is a `(intent,
  action)` pair bound to a handler that mutates project state (e.g.
  `build_processing` + `add`). They live in `skills.py`; the registry is
  the single source of truth for which actions an intent supports.

#### Adding a new prose filter

A prose filter is a deterministic function `text → value` (or
`→ list[value]`). Add it to `project_intents.py`, wire it into
`filter_prose(text)`, and add the slot key to the relevant intent's
`required_slots` / `optional_slots`. Prose filters are regex/keyword
based — no LLM. If the extraction is genuinely fuzzy, let the unified
`parse_turn` LLM parser handle it instead (validate its output against
the catalog — never trust it raw).

#### Adding a new skill

Skills are **derived from the module registry**, so you rarely hand-write
one: `skills._build_registry()` emits a skill per `(build_<module>,
action)` for every mutating action (`add`/`set`/`remove`) a module
declares in its `operations`, plus the full editing surface for each
whole-project intent. To give a module a new capability, add the action
to that module's `operations` in `modules.py` (a view-only module that
lists only `list`/`build` registers no mutating skills — exactly the
support policy). To change *how* an action executes, edit its handler in
`turn_engine` (`apply_extracted_fields` for add/set, `apply_removal` for
remove); `skills._action_handlers` binds them (lazily, to avoid a
load-time cycle — `turn_engine.apply_operation` imports `skills`, not the
reverse). Dispatch flows `apply_operation → find_skill(intent, action) →
skill.handler`.

### Adding a new intent

Three pieces:
1. A `resolver(slots, catalog) → list of pattern instances` function.
2. An `Intent(...)` entry in the `INTENTS` registry with required/
   optional slots and slot-question text.
3. An `INTENT_INPUT_EXPECTATIONS[<name>]` block listing required CSVs,
   recommended CSVs, configurator-required yamls, and
   auto-generated yamls. The reply LLM uses this to know what to
   ask the user for and what NOT to ask for.

## Module-mode (build one FEWS-folder module at a time)

The chat UX. Instead of eliciting a whole-project *intent*
(`build_forecasting_project`, ...) and resolving everything at once, the
configurator **focuses one module and operates on it in plain language**.
Configurator feedback drove this: "stop making me do the whole project at
once."

**The Streamlit app is PURE module-mode** — there is no user-facing
whole-project intent (no "build a forecasting project", no "imports only or a
full project?" disambiguation). Un-focused prose either enters a module (cold
entry), **auto-focuses `processing`** for a clear catalog op ("add GFS"), or
asks which module to work on (`chatter._module_pick_prompt`); the app never
calls `run_turn_pipeline`. **`state["intent"]` is now only an internal
resolver-selector**, DERIVED from the slots each module-mode turn by
`turn_engine._sync_module_intent` (imports-only → `build_data_import_only` so
`/done` doesn't demand a basin; imports+basins → `build_forecasting_project`) —
so the three whole-project intents survive **only** as
`resolve_patterns`'s slot→pattern mapper, never as a choice the user sees. The
current module is shown in a grey caption **below** the conversation
(`web_app`), not as a top metric. The CLI/API drivers still carry the
whole-project `run_turn_pipeline` (with its disambiguation gate) for now —
retiring it there is a follow-up; the app is the reference for the pure-module
UX.

**A "module" = one coherent unit of config work.** This mostly lines up
with the always-present FEWS output folders, with two principled
exceptions baked into the registry (`fews_agent/agent/modules.py`):

- **Weld:** `ModuleConfigFiles` + `WorkflowFiles` (+ `ModuleParFiles`) are
  ONE `processing` module — because a single capability (an import, a
  model run) emits its config + workflow + id-map row *together*.
  Splitting them would re-introduce the cross-file coordination the
  patterns exist to eliminate.
- **Split:** `RegionConfigFiles` fans out into `locations` / `parameters`
  / `filters` / `topology` — one folder holding independent files from
  four unrelated sources.

The 9 modules: `locations`, `parameters`, **`processing`** (the weld),
`display`, `filters`, `topology`, `idmap`, `system`, `root`.
`processing` is intentionally broad; the fine granularity comes from the
*operations* inside it ("add an import", "add a model run"), not from
splitting the folder. `phases.py` still classifies patterns into
capability phases *within* `processing`/`display` for scoped builds.

**The pieces (all under `fews_agent/agent/`):**

- **`modules.py`** — the static `Module` registry: each module's folders,
  backing source, capability `phases`, `variables`, `shared_reads/writes`,
  `inputs`, allowed `operations`, and a focused prompt. Plus
  `normalize_module`, `module_for_pattern`, `modules_present`.
- **`module_focus.py`** — the pure, state-aware focus layer:
  `set_focus`/`get_focus`, `focus_card` (what loads + what's inherited +
  what's still needed), `module_shared_context`, `next_unfilled_variable`,
  and **`detect_module_entry`** (deterministic cold entry — see below).
  There is **no separate shared-variable store**: `state["slots"]` already
  persists across turns and `project.yaml` is its serialized form, so
  "shared variables persist" is free.
- **`extractor.py`** — the **single unified LLM parser** `parse_turn(
  message, focus_module, provider) -> ParsedTurn{intent, action, fields,
  dropped, confidence}`. ONE call classifies the overarching intent from
  **all 12** (the 3 whole-project intents + one `build_<module>` per
  FEWS-folder module), plus the operation and fields. `.module` /
  `.is_project_intent` are derived properties. The model extracts freely;
  then **deterministic `validate_fields` checks every value against the
  catalog** (import names + aliases, adapters, `_DATA_TYPE_TO_PARAMETER`,
  resolutions, `normalize_module`) and drops anything unknown into `dropped`
  (surfaced loudly, never applied) — the same "validate, don't trust"
  boundary as the filter drafter. `fields` is the SAME slot shape
  `extract_skills` produces, so add/set flow through the existing additive
  slot-fill + resolve unchanged. **`classify_intent` (whole-project) and
  `extract_operation` (module-op) are now thin ADAPTERS over `parse_turn`** —
  kept for their call sites + test seams, so both drivers, the pipeline, the
  reply split, and cold-entry are unchanged, but the LLM parsing is one
  implementation + one prompt (`prompts/parse_turn.{system,user}.txt`).

**Turn flow when a module is in focus** — the ONE shared implementation
`turn_engine.run_module_turn(state, message, catalog, focus, *, provider,
just_entered)` that **all three shells** (CLI, Streamlit, HTTP API) call:
prose → `extract_operation` → route the action: `add`/`set`
→ `turn_engine.apply_extracted_fields` (honours add=fill vs set=override) →
resolve; `remove` → `extracted_removal_edits`; `select_module` → `set_focus`;
`build`/`list` → the scoped handlers. `apply_operation` is the shared action
router so "apply now" and "apply after confirm" can't diverge.

**Prose is as reliable as the slash commands** — `extract_operation` runs a
**deterministic pre-pass** (`extractor.deterministic_module_op`) *before*
`parse_turn`: a clear add/remove of catalog entities ("add GFS", "GFS and
HRDPS", bare "GFS", "drop RDPS") is *known structure*, so the regex detectors
(`detect_imports`/`detect_basins_with_adapters` + the `_EDIT_*` cue sets) parse
it — no LLM, `confidence=1.0`, so `"add GFS" ≡ "/add GFS"`. It also fixes the
cold-entry one-shot ("set up the imports module with a GFS import" now enters
*and* adds — "set up" reads as an add cue even though bare "set" is a change
cue). It defers to the LLM (`parse_turn`) only when the message is genuinely
fuzzy — a scalar change ("make GFS half-degree"), a question ("what is GFS?"),
or an entity the detectors miss ("the usual american forecast"); those still
get catalog-validated so a hallucinated import is dropped. An explicit module
switch (`detect_module_switch`) still wins over both. It returns a
driver-agnostic `ModuleTurnResult` (reply, note, kind, new_patterns,
`wants_build`); each shell only renders it (console / `TurnResult` / JSON) and
runs its own scoped build on `wants_build`. The instance listing
(`_module_list_text`) also lives in `turn_engine` (its own docstring: "fews_agent
must not import runners, so every pipeline helper lives here"). This unification
is what let the **HTTP API driver gain module-mode without a third copy** — it
had drifted (whole-project intents only) precisely because the routing was
duplicated in the CLI + Streamlit shells and never ported. `run_module_turn`,
`ModuleTurnResult`, and `_module_list_text` are the shared seam; add a
module-mode feature there once.

**Conversational replies (short confirmation + ONE focused question).** An
edit reply is `module_edit_reply(note, state)` = the confirmation + a single
progress-aware follow-up **question** from `_next_step_hint` (deterministic,
not LLM) — e.g. add an import → *"Which weather variables should GFS carry?
(e.g. precipitation, temperature)"*; once variables are set → *"Want to set
GFS's map area (/coordinates), add another source, or /build?"*. It does **not**
dump the full module list / command menu on every turn (configurator feedback:
"it dumps a pile and never asks"). The full listing lives in `/list`
(`module_list_reply` = list + the same question). Used by the shared
`run_module_turn` apply branch **and** each shell's `/add`//`set`//`remove`
slash handlers, so every edit path is equally terse and guiding.

**Cold entry** (`detect_module_entry`, deterministic + conservative): when
nothing is in focus, a clear single-module request enters that module
before the intent pipeline. Fires only on (1) the literal word "module"
("the imports module"), (2) an entry verb + a distinct-name module
("configure locations"), or (3) a bare module name ("filters"). It
**ignores bare imports/model** (they read as a whole-project spec), so it
never hijacks a forecasting request. One-shot ("set up the imports module
with a GFS import" → enter + add) and pure entry (→ focus card) both work.

**Confidence gate** (extractor `confidence` 0..1 + `needs_confirmation`):
a low-confidence op that WOULD change state is stashed in
`state["_pending_operation"]` and the agent asks "did you want to …?
(yes/no)" instead of applying silently. Missing/garbage confidence defaults
HIGH (apply), so existing behaviour is unchanged. `resolve_pending_operation`
maps the yes/no; an unclear answer drops the stale pending op and processes
the message fresh.

**Commands** (both CLI `chat_step.py` and app `chatter.py`): `/modules`
(list the 9), `/module <name>` (focus + card), bare `/build` (builds the
focused module's phases). All documented in `/help` (the `Modules` group in
`project_intents.COMMANDS`). Tests: `test_modules.py`, `test_extractor.py`,
`test_chatter_module_mode.py`, and `test_module_mode_e2e.py` (drives cold
entry → extractor add → done → build, asserting 36/36 XSD-valid + the
weld — the durable oracle since `projects/` fixtures are gitignored).

## Module-by-module building (enforced flow)

The agent does **not** build the whole project in one shot. It guides
the configurator through one **capability group ("phase")** at a time:

```
imports  →  process  →  model  →  visualize
```

A phase is a coarse grouping of patterns by what the configurator is
doing at that step. Each phase is rendered and XSD-validated on its own
(just that phase's pattern outputs) so the user sees concrete, valid
files for one capability before moving to the next. The full cross-file
assembly (singleton merge, bundled standards, derivers, semantic
cross-reference check) is deferred to **final assembly** (`done`).

Pieces:

- **`fews_agent/agent/phases.py`** — the phase taxonomy. `classify_phase`
  (deterministic, name-based) maps a pattern path to a phase;
  `PHASE_ORDER`, `phase_plan`, `next_unbuilt_phase`, `normalize_phase`.
  This is the single source of truth for which pattern belongs to which
  phase.
- **`build_phase()`** in `runners/agent/build_from_blueprint.py` — the
  scoped build. Renders + XSD-validates ONLY the patterns in one phase
  into the shared output tree. Deliberately skips the singleton merge,
  bundled standards, and derivers (those need the whole project). Also
  exposed as `--phase imports|process|model|visualize` on the build CLI.
- **Chat commands** (`chat_step.py`): `/phases` (show the plan with
  built/ready marks), `/build <phase>` (build one phase), `/build`
  (build the next unbuilt phase). `state["built_phases"]` tracks
  progress; a deterministic next-phase nudge is appended after every
  reply (not LLM-composed, so it never drifts).
- **`done`** is still the full one-shot assembly via
  `build_from_blueprint` — kept as the final step, framed as "assemble
  the modules you've built" (singletons + derivers + cross-file check),
  not "generate everything at once."

When extending: a new pattern is auto-classified by `classify_phase`
on its folder name — add a name rule there if a new capability shape
doesn't fall into an existing phase. Do **not** reintroduce a path that
silently resolves and builds every pattern at once.

### The `visualize` phase pattern (`spatial_display_grid`)

The `visualize` phase used to resolve empty for most projects — nothing
emitted a standalone display config. `patterns/auto/spatial_display_grid/`
is its first-class pattern. It makes "view the imported grids in the
Spatial Display / Data Viewer" an explicit module the configurator adds,
rather than a side-effect of an import pattern.

- **Shape.** One `<gridDisplay>` root per gridded source, written to a
  per-source filename `DisplayConfigFiles/GridDisplay_<source_name>.xml`
  so multiple visualize instances never silently overwrite each other (and
  never clobber a contribution-merged `SpatialDisplay.xml`). It emits one
  `<gridPlot>` per requested parameter, each pointing at
  `moduleInstanceId=Import<source_name>` / `locationId=<source_name>` —
  the ids a bare `nwp_grid_*` import reliably registers.
- **Variables.** `source_name` (required; match an import's `nwp_name`),
  `parameters` (list of `{id}`; defaults to precip + temperature),
  `forecast_horizon_hours` (optional → emits a `relativeViewPeriod` window
  per plot), `time_step_hours` (default 3), `time_series_type` (default
  `external forecasting`). `PC*` parameters get `classBreaksId
  Class.Precipitation`, `TA*` get `Class.Temperature`.
- **Generic-body, not typed.** It uses `schema: SpatialDisplay` (the
  generic-body render path) **on purpose**: the typed `GridDisplay`
  template hardcodes `<gridPlotGroup>` and `_dict_to_xml` drops root-level
  `@`-keys, so the required `@id` on the group would be lost. The
  SpatialDisplay path renders `@id` correctly. Root element is still
  `<gridDisplay>`.
- **How it gets resolved.** The `detect_wants_visualization` skill (in
  `project_intents.py`) sets the `wants_visualization` slot from prose
  ("visualize", "spatial display", "view the grids", "Data Viewer", ...).
  Both `_resolve_forecasting_patterns` and
  `_resolve_data_import_only_patterns` pass it to `_resolve_import_patterns`,
  which appends one `spatial_display_grid` instance per `auto/nwp_grid_*`
  import (carrying the selected `parameters` and `forecast_horizon_hours`).
  Like `wants_interpolation`, `wants_visualization` is **not** in any
  intent's `optional_slots` — it flows through chat_step's additive slot
  merge.

### The `interpolate` step (`wf_interpolate_nwp_to_stations`)

The `process` phase's grid→point leg. It lands an imported NWP grid as
**scalar point time series at station locations** so the data shows up in
the Data Viewer — the missing middle of the *import → interpolate →
visualize* path. `patterns/auto/wf_interpolate_nwp_to_stations/` is its
pattern. Implemented in four slices (A–D) plus an ECCC widening; the
full feature is summarised in the memory file
`import-interpolate-visualize-feature.md`.

- **Shape.** Two outputs per NWP source: a `TransformationModule`
  (`ModuleConfigFiles/Interpolate/Interpolate<nwp>ToStations.xml`) with
  one `Grid_<param>` input + `Station_<param>` output +
  `interpolationSpatial/closestDistance` transform per parameter, and the
  `Workflow` that runs it. Fully concrete — no FEWS `$PLACEHOLDER$`.
- **The defining property.** The grid input reads from the **upstream
  `Import<nwp>` instance** (`moduleInstanceId=Import<nwp>`,
  `locationId=<nwp>`), *not* from a model-run instance like the basin
  patterns' `PostprocessModelOutputToStationTemplate` does. That's what
  makes interpolation work in a **no-basin import-only** project.
- **Variables.** `nwp_name` (req), `parameters` (list of `{id}`; default
  precip + temperature), `station_locationset_id` (default
  `InterpolationStations`), `time_step_hours` (default 3),
  `time_series_type` (default `external forecasting`), `geo_datum`
  (default `WGS 1984`, used as the `closestDistance` distanceGeoDatum).
- **How it gets resolved (Slice C).** `detect_wants_interpolation` sets
  the `wants_interpolation` slot; `_resolve_import_patterns` emits one
  instance per eligible NWP import. It emits **only** this pattern — the
  old inert `tpl_postprocess_to_station` force-fit was dropped.
  `classify_phase` routes `interpolate` names to the **process** phase.
- **Which imports are eligible (`_INTERPOLATABLE_IMPORTS`).** A
  per-source descriptor in `project_intents.py` records each import's
  importable `parameters` and grid `time_step_hours`. The resolver
  **intersects** the requested params with what the import actually
  carries and reads at the import's **own timeStep** (HRDPS is hourly →
  `multiplier=1`, not the 3-hour default; XSD won't catch a step
  mismatch). Current set: `GFS` (parameterized, 3h), `HRDPS` (PC.nwp/
  TA.nwp, 1h), `GDPS`/`RDPS` (PC.nwp/TA.nwp, 3h). **Excluded on
  purpose:** `REPS` (ensemble grid — needs ensemble-aware interpolation),
  `HRDPA`/`RDPA` (analysis precip as `PC.sim`, not the `.nwp` forecast
  convention). A source carrying none of the requested params is skipped.
- **Station targets come from `locations.csv` (Slice B).** The
  `locationsets_derivation` deriver detects which set the interpolation
  writes its scalar output to and backs **that** set with explicit
  `<locationId>` membership pulled from the rendered `Locations.xml`
  (the CSV-ingest output) — so the id auto-matches
  `station_locationset_id` and the interpolation resolves against real
  targets. Every other referenced set stays an id-only stub.
- **Loud failure when targets are missing (Slice D).**
  `unbacked_interpolation_station_sets` flags any interpolation set left
  as a bare stub (usually because no `locations.csv` was provided); the
  build prints a warning Panel and surfaces `unbacked_interpolation_sets`
  in the build summary. The build still succeeds (XSD-valid) — it warns,
  it doesn't abort.
- **Tests / oracles.** `tests/test_interpolate_pattern.py` (pattern +
  resolver), `tests/test_locationsets_deriv.py` (CSV-backed sets),
  `tests/test_interpolation_e2e.py` (end-to-end XSD + semantic-by-parsing
  for both GFS and HRDPS, plus the loud-failure path). These are the
  durable oracle — the `projects/` interpolation fixtures are gitignored.

### Module export (`/export <name>` — the closure walker)

`done` + a full build emits a whole config (~30+ files). A configurator
who wants **one module** — to drop into an existing config, or as a
minimal standalone — needs the module plus exactly the files that
declare what it references, and nothing else. `/export <name>` produces
that. Implemented in `fews_agent/agent/module_export.py` (pure, I/O-free,
unit-tested) and wired into `chat_step.py` as `_run_module_export`.

- **What it does.** Builds the full project (so every declarer exists),
  identifies the module's own rendered files (the *seeds*), then walks
  **outgoing** id references — `parameterId`, `locationId`, `idMapId`,
  `unitConversionsId`, ... — pulling in the files that *declare* those
  ids, transitively. It stops at the chrome boundary: files that
  reference *into* the module (Topology, Filters, DisplayGroups,
  descriptors) are dependents, not dependencies, and are excluded.
  Writes the subset + a `MANIFEST.md` to `generated/_export_<name>/`.
- **Three buckets** (`compute_closure → ExportResult`): **needed** (the
  module + dependency files it pulled in — a self-contained, XSD-valid
  subset), **external** (refs no dependency file satisfied — a sibling
  module's instance, or an id only declared in chrome; these become a
  manifest "your target config must already declare these"), **chrome**
  (everything excluded). A module's own `moduleInstanceId` is declared
  by its config filename, so descriptors are never pulled in.
- **Dependency trimming (`trim_dependency_files`).** The full build emits
  `Parameters.xml` / `Grids.xml` / `LocationSets.xml` / `TimeSteps.xml`
  whole — they carry entries beyond what one module references. The
  exporter trims each to only the referenced entries via an
  **entry-level closure**: it seeds from the refs carried by the
  *non-trimmable* needed files (module + idMap + unitConversions), then
  keeps only the declared entries those refs reach — **transitively**, so
  a kept `locationSet` pulls in the sets it names. Unreferenced
  `parameter` / grid / `locationSet` / `timeStep` entries are removed; a
  `parameterGroup` left empty is dropped. Concretely, a GFS-only export's
  `Grids.xml` loses the basin `$MODELNAME1$Grid` placeholder and keeps
  just `locationId="GFS"`. **Empty-result safeguard** (same convention as
  the build runner's idMap/grid trimmers): a file with nothing to drop,
  or where trimming would remove *every* entry, is left whole. An **XSD
  safety net** in the handler falls back to the full file if a trim would
  produce invalid XML — never ship unvalidated output. The MANIFEST
  labels each dep `_(trimmed to the referenced entries)_` vs
  `_(emitted whole; every entry is referenced)_`.
- **Why ElementTree, not the build-runner trimmers.** The build runner
  trims the pre-render *yaml dicts* (`_filter_grids_content`,
  `_filter_idmap_content`); the exporter works on already-rendered XML
  strings, so it reuses the *principle* (keep referenced, safeguard
  against emptying) but parses/re-serializes with ElementTree. The
  default FEWS namespace is re-declared on re-serialization so a trimmed
  file round-trips without ElementTree's `ns0:` prefixing.
- **Tests / oracle.** `tests/test_module_export.py` — synthetic
  `{relpath: content}` unit tests for the closure + trimming (parameter
  trim + empty-group removal, grid placeholder drop, locationSet
  transitivity, all-referenced omission, namespace preservation), plus
  one integration test that runs the real GFS build and asserts the
  trimmed `Grids.xml` drops the placeholder and still XSD-validates.

## Configurator inputs (what the user provides)

For a single-basin forecasting project, the configurator's minimum-
viable input set is **6 files**:

```
project.yaml                              (or chat agent writes it)
inputs/
  locations.csv                           stations: id, name, lat/lon, attrs
  parameters.csv                          parameter defs (PC, TA, Q, ...)
  hydrometric_<Basin>.csv                 station→model-cell mapping
  <Basin>Watersheds.shp + Extent.shp      basin geometry (FEWS loads at runtime)
  idImport<Adapter>.yaml                  per-adapter ID map (raven/wflow)
```

Strongly recommended for operational quality (build still succeeds
without them):

```
inputs/
  qualifiers.csv                          qualifier defs
  thresholdWarningLevels.csv              station warning thresholds
  modifierTypes.yaml                      what interventions operators can do
  modifierDisplay.yaml                    UI for modifiers
  locationIcons.yaml                      map icons
```

Everything else (~40 of the ~52 files in `projects/tutorial/
tutorial_<datetime>/inputs/`) is auto-generated by one of the layers above.
The tutorial's input set is large because it predates the
auto-generation layers; it's **not** a baseline for new projects.

When a configurator asks "do I need to provide X.yaml?" — check the
appropriate `INTENT_INPUT_EXPECTATIONS` entry. If X is in
`auto_generated_yamls`, no. If X is in `recommended_yamls_examples`,
yes (unless they're OK with the runner's defaults).

## Regression oracles

Two projects under `projects/` pin the agent's behaviour:

- **`projects/tutorial/tutorial_2026-05-07_120000/`** — reproduces
  `examples/config-tutorial/`. Target: 120/120 XSD-valid, 118/120
  byte-equivalent (the 2 byte-divergent files are documented
  WSCHourly drift, not regressions). The `--diff-against
  examples/config-tutorial` flag prints a per-file byte-equivalence
  column.
- **`projects/small/small_2026-05-07_120000/`** — HRDPS + GFS +
  raven_basin(Liard), no `inputs/` directory. Target: 29/29
  XSD-valid (28 XML + 1 non-XML `sa_global.Properties`). Exercises
  the full auto-generation path for a project that doesn't carry
  tutorial assumptions.

Run both after non-trivial changes:

```
python -m runners.agent.build_from_blueprint \
    --blueprint projects/tutorial/tutorial_2026-05-07_120000/project.yaml \
    --diff-against examples/config-tutorial
python -m runners.agent.build_from_blueprint \
    --blueprint projects/small/small_2026-05-07_120000/project.yaml
```

Tutorial regression: file count 120, XSD 120/120, byte-eq 118/120 must
hold. Small-project: file count 29, XSD 28/28 + 1 non-XML must hold.

## Session pickup notes (resume from another laptop)

Branch: **`make-agent-stepwise`**. The chat → build pipeline works
end-to-end; everything below is layered on top.

**Most recent workstream (2026-06-18): import → interpolate → visualize.**
The agent now handles a free-form "import a grid, interpolate it to my
stations, visualize it" request end-to-end on the existing
`build_data_import_only` intent — no new intent needed. Shipped as four
slices (A–D) plus an ECCC widening, all with tests
(`tests/test_interpolate_pattern.py`, `tests/test_locationsets_deriv.py`,
`tests/test_interpolation_e2e.py`). The mechanics live under **"The
`interpolate` step (`wf_interpolate_nwp_to_stations`)"** above; the
one-paragraph version:

- **A** — the interpolation pattern (grid→station `closestDistance` per
  parameter + its workflow), reading the grid from the upstream
  `Import<nwp>` instance so it works without a basin.
- **C** — resolver wiring: emit only this pattern (dropped the inert
  `tpl_postprocess_to_station`); route `interpolate` → `process` phase.
- **B** — the LocationSets deriver auto-backs the interpolation's station
  set from `locations.csv` (explicit `<locationId>` membership).
- **D** — loud-failure guard (`unbacked_interpolation_sets`) when a
  station set has no backing; end-to-end XSD + semantic-by-parsing oracle.
- **ECCC widening** — `_INTERPOLATABLE_IMPORTS` adds HRDPS/GDPS/RDPS to
  GFS, intersecting requested params with each import's fixed set and
  reading at the import's own timeStep (HRDPS = 1h).

Live-verified the full chat→resolve→build loop on the colleague prompt at
`projects/interp-chat-verify/...` (gitignored): 1 turn → 4 patterns → 38
files, 37/37 XSD-valid, station set populated. Full suite: **138 passing**
(was 81 at the time of this workstream; +39 intent disambiguation,
+18 Streamlit-driver parity / shared turn-engine).

**Prior workstream (2026-06-18): stepwise build + mid-chat edits.**
The agent builds **one module at a time** and supports editing the
in-progress project (add / remove a module, change a variable) via both
slash commands and natural language. Shipped in four slices plus an
intent fix, all committed with tests (`tests/test_stepwise_edits.py`,
35 tests):

- **Slice 1** — per-instance build (`build_module()` + `--module`); slash
  edits `/add` `/remove` `/set` `/list` and `/build <name>`; slot mutators
  `add_module`/`remove_module`/`set_variable` (edits mutate `slots`, never
  `patterns`, because `_resolve_patterns` rebuilds patterns from slots
  every turn).
- **Slice 2** — `detect_edit_action` NL skill (verb-gated, positional cue
  disambiguation, remove + scalar-override), wired as Phase 2.5 in
  `chat_step.py` with re-add suppression.
- **Slice 3** — `compose_reply` reoriented to one-module-at-a-time;
  acknowledges completed edits past-tense (gated on a per-turn RECENT EDIT
  line), keeps the anti-fabrication rules.
- **Slice 4** — per-instance scoping for `grid_resolution` /
  `forecast_horizon_hours` via `slots["import_overrides"]`; unnamed set
  stays a project-wide default. Resolver applies override → project
  fallback per instance.
- **Turn-1 intent fix** — `forced_intent_override()` runs deterministically
  on **every** turn, so "no basin model" yields `build_data_import_only`
  on turn 1; an explicit "forecasting" request blocks greedy narrowing.

The showcase fixture is
`projects/stepwise-edit-demo/stepwise-edit-demo_2026-06-18_101706/`
(documented under "Demo / experiment projects on disk").

**Active context:** the user is prepping a presentation about this
system. The import→interpolate→visualize feature (above) is complete and
verified across chat / resolve / build. No active in-flight code change.

### Mental model in 30 seconds

The agent has **two halves**:

1. **Elicitation half (chat).** LLM talks to the user, extracts
   structured facts, decides which patterns are needed, writes
   `project.yaml`. Two modes: **module-mode** (focus one FEWS-folder
   module, operate on it in plain language via `extractor.py` — the newer,
   preferred UX; see "Module-mode") and the older **whole-project intent**
   flow (fallback when no module is in focus). The per-turn pipeline lives
   in `fews_agent/agent/turn_engine.py` (shared by the CLI driver
   `runners/agent/chat_step.py` and the Streamlit driver
   `app/chatter.py`); skills/intents/resolvers in
   `fews_agent/agent/project_intents.py`; the module registry + focus in
   `modules.py` / `module_focus.py`.
2. **Generation half (build).** Deterministic pipeline reads
   `project.yaml`, expands patterns, ingests CSVs, fills with
   bundled standards, runs derivers, validates twice (Pydantic +
   XSD), writes XML. Lives in `runners/agent/build_from_blueprint.py`.

The core **LLM jobs** — everything else is templating or deterministic
code. The **model is provider-configurable** via `FEWS_AGENT_PROVIDER` /
`FEWS_AGENT_MODEL` (Ollama / Azure / LiteLLM — see `providers/factory.py`);
the "qwen2.5" default is just the Ollama fallback, not a hard dependency.

| # | Where | Job |
|---|---|---|
| 1 | chat | **`parse_turn`** (`extractor.py`) — ONE unified parser: classifies the intent from all 12 (3 whole-project + 9 `build_<module>`) + the operation + catalog-validated fields + confidence. `classify_intent`/`extract_operation` are thin adapters over it. |
| 2 | chat (whole-project) | Compose user-facing reply (`compose_reply`; module-ops use deterministic replies) |
| 3 | build | Draft `Filters.xml` from project IDs (falls back to the bundled `filtersFile.yaml`) |

(Plus the app-only `compose_status_reply` / `compose_help_reply` meta
replies.) If the LLM is down, the chat half fails loudly; the build half
still works end-to-end. Note: job 1 subsumes what used to be two separate
LLM calls (intent classification + operation extraction).

**The regex skills are no longer fed to the classifier.** `extract_skills`
still runs and fills slots deterministically, but its output is NOT shown
to the LLM (feeding a regex pre-pass to a capable model anchors it to, and
via the old "skills win" merge is overridden by, the weaker extractor). The
model now classifies + extracts from prose alone; validation-against-catalog
is the trust boundary.

**All LLM prompts live as `.txt` files** in `fews_agent/agent/prompts/`,
loaded via `prompts.load("name", **vars)` — never inline in Python
(standing rule). The loader is Jinja with **`[[ ]]` / `[% %]` delimiters**
so literal `{ }` (JSON) and `$…$` (FEWS placeholders) in prompt text never
collide; `StrictUndefined` fails loud on a missing var. The blanket
`*.txt` gitignore is negated for this folder (`!fews_agent/agent/prompts/
*.txt`) — without it the loader `FileNotFoundError`s on a fresh clone.

### One pattern per *shape*, not per instance

A confusion point worth flagging up front: `patterns/auto/raven_basin/`
is **one** pattern.yaml — it handles every Raven basin (Liard, Snare,
Athabasca, ...) as different instances. New patterns are only needed
when the *shape* of the output files changes (Raven vs Wflow, ECCC
grid vs NOAA grid). Within a shape, instances are just different
values plugged into `{{ basin_name }}` or `{{ nwp_name }}`.

### Prose-driven NWP slots (shipped during the Kun-prompt work)

A batch of skills added to close gaps surfaced by Kun's prose prompt
("Configure a NOAA GFS import for the Gulf of Guinea with wind speed,
wind direction, and mean sea level pressure. Interpolate to locations
for the Data Viewer. 7-day forecast, half-degree resolution."). All
generic — nothing Gulf-of-Guinea-specific in the code.

- **`region`** — `detect_region` matches a small gazetteer
  (`REGION_BBOX`: Gulf of Guinea, North Sea, Mediterranean, Baltic
  Sea, Gulf of Mexico, Caribbean, Bay of Bengal, South China Sea).
  Slot lands in `singleton_seeds.Locations.region` →
  `sa_global.Properties` gets `REGION=<name>` (resolves `$REGION$` at
  FEWS startup) and the bundled `spatialDisplayFile.yaml`
  `defaultExtent` is rewritten with the region's bbox. Extend by
  adding a row to `REGION_BBOX`.
- **`custom_bbox`** — `detect_custom_bbox` parses freeform lat/lon
  prose with hemisphere markers ("from 8N to -5N, -10E to 10E").
  Explicit sign wins over hemisphere letter so `-10E` reads as 10W.
  Lands in `singleton_seeds.Locations.regionBbox`. Overrides the
  gazetteer when both are set so a configurator can name a region
  but tighten the bbox.
- **`grid_resolution`** — `detect_grid_resolution` maps prose like
  "half-degree GFS" to NOAA URL slugs (`0p25`/`0p50`/`1p00`). Slot
  flows onto the NOAA pattern instance, parameterising the DODS URL
  twice; at build time `_apply_nwp_resolutions_to_grids` overrides
  the bundled gridsFile `xCellSize`/`yCellSize` and the region-bbox
  crop recomputes rows/columns from the chosen cell size.
- **`forecast_horizon_hours`** — `detect_forecast_horizon_hours`
  parses "N days", "N hours", "weekly", "two-week", etc. Slot lands
  on the NOAA pattern instance; pattern.yaml conditionally emits a
  `relativeViewPeriod` in each SpatialDisplay timeSeriesSet so the
  plot shows just the requested window.
- **`data_types`** — `detect_data_types` expanded vocab (relative
  humidity → RH.nwp, dewpoint → TD.nwp, ...). LLM-extracted
  data_types are merged in when the regex pass returns `[]` (empty
  list no longer shadows the LLM). Phrases the parameter mapper
  can't translate surface as a user-visible warning via
  `unrecognised_data_types`.
- **`wants_visualization`** — `detect_wants_visualization` matches
  visualization prose ("visualize", "spatial display", "view/plot
  the grids", "Data Viewer", ...). When true, the resolver appends one
  `auto/spatial_display_grid` instance per `auto/nwp_grid_*` import,
  carrying the selected `parameters` and `forecast_horizon_hours`. This
  is what populates the `visualize` phase (see "The `visualize` phase
  pattern" above). Like `wants_interpolation`, it returns `None` on no
  match (not `False`) so a turn-1 miss doesn't shadow a later turn, and
  it is not in any intent's `optional_slots` — it rides chat_step's
  additive slot merge.

The intent register also gained:
- **Mid-conversation intent override** in `chat_step.py`: strong
  intent-naming phrases ("data import only", "no basin model")
  re-classify mid-run and clear `state["patterns"]` so the resolver
  rebuilds from current slots.
- **Slot-conditional reminders** in `compute_input_status`: when
  `wants_interpolation` is true → tell the configurator
  `locations.csv` carries the interpolation targets; when imports
  are present without a region → nudge toward setting one.

Build-side wiring lives in `runners/agent/build_from_blueprint.py`:
- `_resolve_region_bbox` picks the bbox (custom_bbox wins over
  gazetteer), used by both `_apply_region_extent` (SpatialDisplay
  defaultExtent) and `_apply_region_to_grids` (NWP grid crop).
- `_apply_nwp_resolutions_to_grids` runs BEFORE the region crop so
  rows/columns recompute from the new cell size.
- `_nwp_location_ids_from_blueprint` and
  `_nwp_resolutions_from_blueprint` walk the blueprint's
  `nwp_grid_*` instances to extract names and resolutions for the
  rewriters.

**What actually reaches ECCC vs what doesn't** (the earlier "all
NOAA-only" note was imprecise — the three legs differ, and prose
extraction is generic to all of them). The prose slots
(`detect_grid_resolution` / `detect_custom_bbox` /
`detect_forecast_horizon_hours`) are source-agnostic — the agent
extracts them from ECCC prose today; the *application* to grid geometry
is what varies by source:

- **bbox / region crop — already covers ECCC.** `_apply_region_to_grids`
  + `_nwp_location_ids_from_blueprint` key on the `auto/nwp_grid_`
  *prefix*, so they crop HRDPS/GDPS/RDPS grid entries (present in the
  bundled `gridsFile.yaml`) exactly as they crop GFS. Pinned by
  `tests/test_nwp_grid_rewriters.py::test_bbox_crop_covers_eccc_grids`.
- **forecast horizon — already covers any source.** It's emitted as a
  `relativeViewPeriod` by the `spatial_display_grid` visualize pattern
  from `forecast_horizon_hours`, independent of NWP lineage.
- **resolution — NOAA-shaped, and correctly so.** NOAA's DODS URL takes
  a resolution *slug* (`gfs_0p50`), so it's a real user-selectable knob;
  `_apply_nwp_resolutions_to_grids` fires only for an instance carrying a
  known slug (`_GRID_RESOLUTION_DEGREES`). ECCC products (HRDPS ≈2.5 km,
  RDPS ≈10 km, GDPS ≈15 km) are **fixed native resolution** served from a
  WCS endpoint — there is no slug to request, so the override
  deliberately no-ops on them (pinned by
  `test_resolution_override_noops_on_eccc_without_slug`). "Extending
  resolution to ECCC" is largely a category error; the right behaviour is
  for the agent to *state* the resolution is fixed, not accept a knob.

Separately, `_PARAMETERIZED_NWP_PATTERNS` (in `project_intents.py`) is
about **parameter selection** — which pattern accepts a `data_types` ->
`parameters` variable — and is genuinely NOAA-only (ECCC imports a fixed
parameter set, intersected at resolve). It is unrelated to the
bbox/resolution/horizon plumbing above.

### Explicit grid coordinates (`/coordinates` subwindow)

Beyond the prose knobs (region/bbox/resolution), a configurator can set an
NWP grid's geometry **directly**: `firstCellCenter` (x, y) + `columns`
(rows-X) + `rows` (rows-Y). Chosen shape: **point + counts, cell size
inherited** — the override only repositions/resizes the grid; `xCellSize`/
`yCellSize` stay whatever the resolution rewriter or bundled default set. This
composes with, and takes precedence over, the region-bbox crop.

- **Data model.** A per-import `grid_geometry` override
  (`slots["import_overrides"][<name>]["grid_geometry"] = {first_x, first_y,
  columns, rows}`), the same scoped channel as `grid_resolution` /
  `forecast_horizon_hours`. Written by
  `project_chat.set_grid_geometry(state, name, ...)`.
- **Flow.** The resolver attaches `grid_geometry` to the instance for **any**
  `auto/nwp_grid_*` import (NOAA and ECCC) — the pattern doesn't reference it,
  so `_apply_defaults` ignores it during rendering, but it serializes to
  `project.yaml`. At build time
  `_nwp_geometries_from_blueprint` → `_apply_grid_geometry_to_grids` stamps it
  onto the matching `<regular>` entry (runs AFTER the resolution + bbox
  rewriters; leaves cell size; skips projected `polarStereographic`/
  `gridCorners` grids, which have no `firstCellCenter`).
- **UX (Streamlit-only for now).** `/coordinates [<name>]` in the app returns
  `TurnResult(kind="coordinates", coordinates_request=[{name, geometry,
  cell_size}, ...])`; `frontend/web_app.py` opens an `st.dialog` modal
  (expander fallback) with number inputs, and submitting calls
  `ChatSession.apply_grid_geometry(...)`. **Live map:** the modal draws the
  grid box + first-cell-centre on a pydeck map that re-renders on every input
  change — computed by the pure `project_chat.grid_bbox(...)` from the point +
  counts + the **effective inherited cell size** (`ChatSession._effective_cell_
  size` → resolution slug degrees, else the bundled gridsFile default via
  `_bundled_grid_cell_size`, else 0.25). pydeck ships with Streamlit; a missing
  import degrades to a numeric extent readout. The CLI has a stub pointing at
  the web app (no modal); the build/data model is shared, so CLI/API can adopt
  it later. Tests: `test_nwp_grid_rewriters.py` (mutator + rewriter +
  precedence + skip-cases + `grid_bbox`, the durable oracle) and
  `test_chatter_module_mode.py` (the `/coordinates` command +
  `apply_grid_geometry` + effective cell size).

### Demo / experiment projects on disk (reference fixtures, not regression oracles)

Created during the recent presentation prep — each captures a specific
behaviour you may want to inspect or rerun:

- **`projects/full-demo/full-demo_2026-05-12_111230/`** — fresh
  end-to-end demo. 7 configurator inputs (4 CSVs + 2 yamls + 1
  shapefile) → 2-turn chat → 57 rendered files. Good "what does the
  happy path produce" reference. Contains real `project.yaml` showing
  20 pattern entries (HRDPS, GFS, raven_basin(Liard), 13 tpl_*,
  4 wf_*).
- **`projects/tutorial-csv-only/tutorial-csv-only_2026-05-13_085951/`**
  — recreates the tutorial from CSV inputs only (no per-spec yamls).
  Outcome: 36 patterns, 0 warnings, 100 files, 99/99 XSD-valid; ~73%
  coverage of the tutorial's 135 XMLs. The missing ~27% are
  configurator-policy yamls, project-specific module configs, vendor
  binaries, and map-layer assets — i.e. genuinely external to what
  CSVs + patterns can produce. Use this to demonstrate "minimum
  viable input set" claims.
- **`projects/rhine-blocklist/rhine-blocklist_2026-05-12_102438/`** —
  4-turn rhine experiment that confirmed the
  `ENGLISH_WORD_BLOCKLIST` fix kills the "We" false positive. Also
  exercises the loud-failure contract: turn 1 surfaces a
  HARMONIE/ICON warning (no pattern in library); `done` is refused on
  turn 2; turn 3 drops them; turn 4's `done` succeeds. 47 files,
  46/46 XSD-valid + 1 non-XML.
- **`projects/gulf-of-guinea-demo/gulf-of-guinea-demo_2026-06-15_120000/`**
  — hand-authored fixture exercising every prose-driven NWP slot we
  shipped: `region: Gulf of Guinea`, `regionBbox` override,
  `grid_resolution: 0p50`, `forecast_horizon_hours: 168`, custom
  `parameters` list, interpolation patterns. 36 files / 35-of-35
  XSD-valid. Use this to spot regressions in any of region/bbox/
  resolution/horizon — drift on this single project covers all four.
- **`projects/kun-hf-full/kun-hf-full_2026-06-15_002841/`** — single
  HF-driven turn exercising the same slots from one prose prompt.
  Demonstrates the LLM extraction + slot fill path end-to-end. Same
  build artefacts as gulf-of-guinea-demo.
- **`projects/kun-stepwise/kun-stepwise_2026-06-15_004449/`** — same
  prompt **drip-fed across 4 chat turns** instead of one. Surfaced
  and validates the mid-conversation intent override: turn 1
  misclassifies as `build_forecasting_project`; turn 2 ("Just data
  import, no basin model") re-classifies to `build_data_import_only`
  and drops 16 stale template patterns. Same 36/35 build. **Note:** the
  turn-1 misclassification this fixture documents was later *fixed* (see
  "Stepwise build + mid-chat edits" below) — `forced_intent_override`
  now runs on turn 1, so a fresh run of this prompt classifies correctly
  on the first turn.
- **`projects/stepwise-edit-demo/stepwise-edit-demo_2026-06-18_101706/`**
  — the showcase for the stepwise-build + mid-chat-edit work (Slices 1–4
  + the turn-1 intent fix). 6 turns: (1) "NOAA GFS for the Gulf of Guinea,
  precip+temp, visualize, no basin model" → correctly classifies
  `build_data_import_only` on **turn 1**; (2) NL "also add an HRDPS
  import"; (3) NL "make GFS a 7-day forecast" → per-import horizon=168;
  (4) slash `/set HRDPS horizon 3-day` → per-import horizon=72; (5)
  `/list` shows the two grids with **distinct** display windows; (6)
  `done`. Builds to **40 files, 39/39 XSD + 1 non-XML**. The payoff is
  verifiable in the rendered XML: `DisplayConfigFiles/GridDisplay_GFS.xml`
  has `relativeViewPeriod end="168"`, `GridDisplay_HRDPS.xml` has
  `end="72"`. Use this to demo add/remove/set edits and per-instance
  scoping end-to-end. (Caveat: a couple of the qwen2.5 reply lines drift
  — e.g. a fabricated "Mackenzie basin" mention on turn 3 — so cherry-pick
  turns when presenting; the engine internals in `_conversation.md` are
  correct.)
- **`projects/stepwise-edit-demo/stepwise-edit-demo_2026-07-08_120000/`**
  — the **module-mode** showcase (the newer UX; see "Module-mode"). 10
  turns, fully **reproducible** (module-mode replies are deterministic; the
  extractor is scripted, so no qwen drift): (1) cold entry *"set up the
  imports module — a NOAA GFS import for precip and temperature"* → enters
  `processing` + one-shot add; (2) NL *"also add an HRDPS import"*; (3)
  low-confidence *"make GFS half-degree"* → agent **asks to confirm**; (4)
  *"yes"* → applies `grid_resolution=0p50`; (5) *"add the GEFS ensemble and
  the MysteryModel grids"* → GEFS added, **MysteryModel dropped** by catalog
  validation (surfaced loudly); (6) `/build` → scoped build *"phase imports:
  8/8 XSD-valid"*; (7) *"switch to the display module"* → focus card shows
  **`Inherited from this session → imports=['GFS','HRDPS','GEFS']`** (shared
  vars persist across modules); (8) *"visualize the GFS and HRDPS grids"* →
  `spatial_display_grid` per source; (9) `/list`; (10) `done`. Full build
  **42/42 XSD-valid**. Reproduce by driving `chat_step.main` over the 10
  turns with the extractor's provider stubbed (keyword→op), the way
  `test_module_mode_e2e.py` stubs it; or just read `_conversation.md`. Use
  this to demo the whole module-mode arc.

None of these are the regression oracle — that's still
`projects/tutorial/tutorial_2026-05-07_120000/` (120 files,
byte-equivalent against `examples/config-tutorial/`) and
`projects/small/small_2026-05-07_120000/` (29 files, XSD only).

### Re-running on the other laptop

After pulling the branch:

```
python -m runners.agent.chat_step \
    --project-dir projects/full-demo/full-demo_2026-05-12_111230

python -m runners.agent.build_from_blueprint \
    --blueprint projects/full-demo/full-demo_2026-05-12_111230/project.yaml
```

The chat agent expects qwen2.5:7b-instruct on the local Ollama
endpoint (`http://localhost:11434`). If Ollama isn't running, the
chat agent fails loudly; the build path is fully deterministic and
needs no LLM (filter drafter falls back to the bundled standard).

### Verification checklist (run after pulling on the new laptop)

Run these in order. Each has a known target — anything different is a
regression worth investigating before doing anything else.

```
# 1. Branch state
git status --short
git log --oneline -5

# 2. Tutorial regression oracle (byte-equivalent)
python -m runners.agent.build_from_blueprint \
    --blueprint projects/tutorial/tutorial_2026-05-07_120000/project.yaml \
    --diff-against examples/config-tutorial
   # expect: file count 120, XSD 120/120, byte-eq 118/120,
   #         27 unresolved semantic refs (documented in "Known findings")

# 3. Small-project regression oracle (XSD only)
python -m runners.agent.build_from_blueprint \
    --blueprint projects/small/small_2026-05-07_120000/project.yaml
   # expect: 29 files, XSD 28/28 + 1 non-XML sa_global.Properties

# 4. Gulf-of-Guinea fixture (covers all prose-driven NWP slots)
python -m runners.agent.build_from_blueprint \
    --blueprint projects/gulf-of-guinea-demo/gulf-of-guinea-demo_2026-06-15_120000/project.yaml
   # expect: 36 files, 35/35 XSD-valid + 1 non-XML.
   # Spot-check the URL points at gfs_0p50, GFS grid is 48x30 at
   # firstCellCenter (-11.75, 8.75), defaultExtent id="Gulf of Guinea",
   # three relativeViewPeriod end="168" blocks, REGION=Gulf of Guinea.

# 5. Full-demo rebuild (proves the chat agent + build path)
python -m runners.agent.build_from_blueprint \
    --blueprint projects/full-demo/full-demo_2026-05-12_111230/project.yaml
   # expect: 57 files, all XSD-valid

# 6. Tutorial-from-CSVs-only rebuild (the "minimum input" demo)
python -m runners.agent.build_from_blueprint \
    --blueprint projects/tutorial-csv-only/tutorial-csv-only_2026-05-13_085951/project.yaml
   # expect: 100 files, 99/99 XSD-valid (1 non-XML)

# 7. Test suite (the durable oracle — survives a fresh clone, unlike the
#    gitignored projects/ fixtures above). Covers stepwise edits +
#    import->interpolate->visualize (pattern, CSV-backed sets, e2e) +
#    module export closure + dependency trimming + intent disambiguation
#    (pure helpers + the turn loop with the LLM stubbed) + Streamlit-driver
#    parity (test_chatter_*.py drive the shared turn_engine via ChatSession).
python -m pytest tests/ -q
   # expect: 138 passed (the interpolation e2e + module-export integration
   #         tests invoke the build path + the filter-drafter LLM, ~60s)
```

If any of (2)–(5) drift, **stop** — the build path is the foundation
of every demo, and silent drift here invalidates everything else.

### File-pointer guide (where everything lives)

When picking up cold, these are the files that matter most. Read in
this order to recover context fast:

```
CLAUDE.md                                         this file (top-of-mind context)

# Elicitation half
fews_agent/agent/turn_engine.py                   SHARED per-turn pipeline (Phases 1-5) + run_module_turn (module-mode); all 3 shells call it
runners/agent/chat_step.py                        CLI driver: command dispatch + console I/O around turn_engine
app/chatter.py                                     Streamlit driver: command dispatch + TurnResult around turn_engine; projects/ store helpers (list_projects, new/latest_project_session_dir)
frontend/web_app.py                                Streamlit UI: startup project picker (new/load) + chat render + coordinates map
app/api/server.py                                  HTTP API driver: FastAPI endpoints (/turn does module-mode + intent pipeline; /build does full OR scoped phase/module) around turn_engine
fews_agent/agent/project_intents.py               skills, intent registry, resolvers, blocklist, COMMANDS (/help)
fews_agent/agent/modules.py                        module registry (module = FEWS folder; the weld + RegionConfig split)
fews_agent/agent/module_focus.py                   focus layer + cold entry (detect_module_entry)
fews_agent/agent/extractor.py                      parse_turn — the ONE unified LLM parser (intent+operation+fields); classify_intent/extract_operation are adapters over it
fews_agent/agent/prompts/                          ALL LLM prompts as .txt (loader in __init__.py; [[ ]] delimiters)
fews_agent/agent/project_chat.py                  state I/O, pattern catalog loading
fews_agent/agent/providers/factory.py              provider resolution (Ollama / Azure / LiteLLM via env)

# Generation half
runners/agent/build_from_blueprint.py             the orchestrator; read this to follow the pipeline
fews_agent/agent/blueprint.py                     blueprint dataclass + pattern expander
fews_agent/agent/filter_drafter.py                LLM job #4
fews_agent/agent/*_derivation.py                  the 4 deterministic derivers
fews_agent/agent/standard_inputs/                 bundled fallback yamls

# The pattern library (the asset that grows over time)
patterns/auto/<name>/pattern.yaml                 one per capability
patterns/auto/<name>/contributions.yaml           optional, for singleton-file merges

# The schema layer
fews_agent/schema/<spec>.py                       Pydantic models, one per FEWS spec
fews_agent/generators/<spec>.py                   one-liner generate() wrappers
fews_agent/generators/templates/<area>/<spec>.xml.j2   Jinja XML templates
fews_agent/generators/__init__.py                 SPECS list — the master registry

# Validation
fews_agent/validation/xsd.py                      XSD gate
fews_agent/validation/semantic.py                 cross-file ID walker
```

### Common gotchas (and how to debug them)

- **Ollama not running.** `chat_step.py` will fail with a connection
  error on first turn. Start Ollama, confirm with
  `curl http://localhost:11434/api/tags`. The build path doesn't need
  it.
- **Phantom basin extracted from prose.** The
  `ENGLISH_WORD_BLOCKLIST` (in `project_intents.py`) is the single
  source of truth. Add the offending capitalised word there; both the
  chat agent and the basin-extractor pick it up. Do *not* add it to a
  second list in `chat_step.py` — that list was removed for exactly
  this reason.
- **Spurious "no pattern in library" warning.** The detector in
  `chat_step.py` checks both instance-variable values *and* pattern
  names by substring. If a new pattern hides the source name inside a
  workflow name (like `wf_import_nam_grids` for "NAM"), the substring
  check catches it. If you add a pattern with a name that doesn't
  contain the source name in any form, add an explicit alias entry to
  `_IMPORT_PATTERN_MAP` so the warning detector finds it.
- **Tutorial byte-equivalence drift.** Almost always a template
  ordering issue (FEWS XSDs use `xsd:sequence` — element order
  matters). Diff the offending file with `diff -u` against
  `examples/config-tutorial/<path>` and look for swapped elements.
- **`Coverage: 119/120` instead of 120.** Usually means a generator
  is silently raising and the wrapper is swallowing it — check
  `_render_one` in `build_from_blueprint.py` and re-raise during
  debug.
- **`27 unresolved` semantic refs.** **Not a regression.** These are
  the three documented tutorial-bug clusters in "Known findings"
  above. Only worry if the number *changes*.

### Presentation demo script (the journey we tell)

The narrative the user has been refining for the talk:

1. **The problem (1 slide).** A FEWS config is ~135 interlocking XML
   files. Configurators write the same 70% of content every time.
   Show one ECCC import XML as evidence of repetition.
2. **The split (1 slide).** Two halves: LLM for fuzzy elicitation,
   deterministic templates for rigid XML. Use the diagram from
   `CLAUDE.md` "End-to-end pipeline."
3. **Live chat demo.** Run `chat_step.py` against
   `projects/full-demo/.../`. Show the engine internals
   `<details>` blocks in `_conversation.md` to make the 4 stages
   (skills → intent → slot-fill → pattern resolution) tangible.
4. **Loud failures.** Switch to `projects/rhine-blocklist/.../`.
   Show turn 1's HARMONIE/ICON warning, the refused `done`, the
   recovery in turn 3. Talking point: "the agent refuses to ship
   silently incomplete work."
5. **The build path.** Run
   `build_from_blueprint --blueprint projects/full-demo/.../project.yaml`.
   Show the per-file table with XSD column. Open one rendered XML
   (e.g. `ImportHRDPS.xml`) and compare to the matching
   `patterns/auto/nwp_grid_eccc_HRDPS/pattern.yaml`. Talking point:
   "this is what the LLM never sees — pure templating."
6. **The CSV-only demo.** Switch to
   `projects/tutorial-csv-only/.../`. 4 CSVs in, 99 XMLs out, 73% of
   the tutorial. Talking point: "the inputs that *aren't* templated
   are genuinely external — policy decisions, vendor binaries, map
   layers."
7. **What's deterministic vs LLM.** Reuse the 4-LLM-jobs table from
   the mental model. Audience-friendly: "we use LLMs exactly where
   the structure is unknown, and not one place more."
8. **Same engine, three shells — the HTTP API (optional, for a
   technical audience).** The whole elicitation+build loop is a
   library, not a CLI: the CLI, the Streamlit app, and a FastAPI
   service (`app/api/server.py`) are three thin shells over one
   `turn_engine`. Bring it up and drive the *same* module-mode loop
   over HTTP:

   ```
   uvicorn app.api.server:app --reload            # or --port 8000
   # curl needs --json (curl >=7.82) so FastAPI parses the body as JSON;
   # plain `-d` sends form-encoding and 422s. `-H 'Content-Type:
   # application/json' -d '...'` works on older curl.

   # 1) a session (a fresh project instance on disk, same layout as the CLI)
   curl -s --json '{"project_name":"api-demo"}' localhost:8000/sessions

   # 2) module-mode over HTTP: cold entry + one-shot add (returns
   #    module_mode=true, current_module="processing", the resolved patterns)
   curl -s --json '{"message":"set up the imports module with a NOAA GFS import for precip and temperature"}' \
     localhost:8000/sessions/<id>/turn
   #    then a follow-up edit in the same focused module
   curl -s --json '{"message":"also add an HRDPS import"}' localhost:8000/sessions/<id>/turn

   # 3) scoped build over HTTP — render + XSD-validate just the imports phase
   curl -s --json '{"phase":"imports"}' localhost:8000/sessions/<id>/build
   #    (scope="phase:imports", per-file XSD table; no derivers/singletons)

   # 4) full assembly — the `done` path as JSON
   curl -s --json '{"force":true}' localhost:8000/sessions/<id>/build
   ```
   (Chat/turn steps need the LLM backend reachable; the two `/build`
   calls are deterministic and work even when it isn't. Or skip curl
   entirely and drive it from the interactive docs at
   `localhost:8000/docs`.)

   Talking points: (a) **one brain, many faces** — the API reuses
   `run_turn_pipeline` + `run_module_turn`, so a terminal, the web
   app, and an HTTP client behave identically; (b) **the trust
   boundary is in the engine, not the UI** — POST a bogus model name
   and the response's `dropped`/reply shows it was rejected, over
   HTTP, by the same `validate_fields`; (c) **it's automatable** —
   scoped `/build` returns a machine-readable per-file XSD table, so
   CI or another service can drive config generation without a human.
   Nice contrast slide to "this isn't a chatbot demo, it's a
   service."

### Open threads / next likely tasks

In rough priority order:

1. **Commit the two dirty files.** Suggested message:
   `Eliminate basin-regex and warning-detector false positives`
   (blocklist + pattern-name substring check; tested via
   rhine-blocklist + tutorial-csv-only demos).
2. **Decide what to do with `scripts/draw_ux_flow_pdf.py`.** Keep
   (commit it under `scripts/`) or discard. Not on any build path
   either way.
3. **Consider promoting `ENGLISH_WORD_BLOCKLIST`** from a frozenset
   literal to a data file if the list grows past ~50 entries —
   current scale doesn't justify it yet.
4. **Tutorial coverage gap (~27%).** Document the four buckets
   discovered in tutorial-csv-only: (a) configurator-policy yamls
   (15 files, e.g. `modifierTypes`, `locationIcons`), (b)
   project-specific module configs (3 files), (c) adapter assets
   (2 files), (d) map-layer/vendor binaries (16 files). None are
   solvable by "more patterns" — they're inherently external.
   Worth a slide in the talk if there's room.
5. **The plan file
   `~/.claude/plans/now-lets-build-the-bubbly-spark.md`** (29
   typed-spec promotions + tutorial sharpening) is an older plan;
   it is **not the active workstream** on this branch. The
   pattern-agent thread is.
6. **Free-form "import + interpolate + visualize" request style — SHIPPED.**
   The colleague prompt below now works end-to-end on the existing
   `build_data_import_only` intent — **no new intent was needed**:

   > "Configure a NOAA GFS import for the Gulf of Guinea with wind
   > speed, wind direction, and mean sea level pressure. Interpolate
   > the imported gridded data to locations for visualizing in the
   > Data Viewer, and visualize the spatial data in the Spatial
   > Display. The list of locations with coordinates is provided in
   > the .csv file." (+ attached locations CSV)

   Each erstwhile gap is closed and how:
   - **Parameter selection from prose** — `detect_data_types` already
     maps a user-chosen subset to FEWS parameterIds; the NOAA pattern is
     parameterized, ECCC imports a fixed set (intersected at resolve).
   - **Region as a grid extent** — handled by the prose-driven NWP slots
     (`region` / `custom_bbox`); see "Prose-driven NWP slots".
   - **Grid→point interpolation step** — the
     `wf_interpolate_nwp_to_stations` pattern (see "The `interpolate`
     step" above). Verified for GFS and ECCC HRDPS/GDPS/RDPS.
   - **Spatial Display output** — the `spatial_display_grid` pattern
     (see "The `visualize` phase pattern").
   - **Attached locations CSV** — drives `Locations.xml` via CSV ingest,
     and the LocationSets deriver auto-backs the interpolation's station
     set from it (Slice B).

   Live-verified the full chat→resolve→build loop on this exact prompt
   (`projects/interp-chat-verify/...`, gitignored): 1 turn →
   `build_data_import_only` → 4 patterns → 38 files, 37/37 XSD-valid,
   `InterpolationStations` populated from the CSV. **Remaining options
   (not blockers):** widen interpolation to REPS (ensemble) / analysis
   grids; today's `_INTERPOLATABLE_IMPORTS` covers the deterministic
   forecast grids.

### Azure deployment (decided: bundled-Ollama on a GPU VM)

**Decision made.** The "quick & dirty" deploy is a **single
self-contained Docker image** (`Dockerfile.bundled`) that bundles
**Ollama + the Streamlit chat UI**, built and run on **one Azure GPU
VM** on the Deltares subscription. No Azure OpenAI, no ACR, no
Kubernetes, no compose. The full runbook is in **`DEPLOY.md`** — read
that first; this section is the why-and-where summary.

**Why this shape.** qwen2.5:7b-instruct is 15–45 s/turn on CPU vs
2–5 s on a T4 GPU, and Azure Container Apps has no GPU — so a fast,
always-warm, self-hosted experience means a GPU VM. One image keeps
the box dead simple: `git clone` → `docker build` → `docker run` →
done. The model (~4.7 GB) downloads once into a named volume; later
starts are instant.

**Artifacts in the repo (this branch):**

- **`Dockerfile.bundled`** — all-in-one image. `FROM
  python:3.11-slim` (NOT `ollama/ollama`, which ships Python 3.10 and
  violates `requires-python>=3.11`). Installs `curl ca-certificates
  zstd` (the Ollama installer extracts its payload with **zstd** —
  slim lacks it; omitting it fails the build), then
  `curl … ollama.com/install.sh | sh`. Installs the package +
  `pyyaml` (pyyaml is a known gap in `pyproject.toml`). ENV pins
  `FEWS_AGENT_PROVIDER=ollama`, `FEWS_AGENT_MODEL=qwen2.5:7b-instruct`,
  `OLLAMA_HOST=http://127.0.0.1:11434` (read by BOTH the server bind
  and our client, so they meet inside the container). Entrypoint =
  `docker-entrypoint.sh`, CMD = `streamlit run frontend/web_app.py`.
- **`docker-entrypoint.sh`** — starts `ollama serve &`, waits for it,
  `ollama pull` the model (no-op if the volume already has it), then
  `exec "$@"`. So the default CMD runs Streamlit with Ollama already
  up; override CMD with `bash` (or `docker exec -it fews bash`) for a
  terminal in the same container.
- **`.gitattributes`** — forces `*.sh` + `docker-entrypoint.sh` to
  **LF** so the entrypoint doesn't get CRLF on Windows checkout and
  die with "bad interpreter" inside the Linux container.
- **`DEPLOY.md`** — the runbook: prerequisites (GPU quota check), VM
  create, build/run, colleague access, ops, CPU fallback, Bastion
  option.

The original agent-only **`Dockerfile`** (expects an external Ollama
or Azure OpenAI) is still there for the cloud-PaaS path; the bundled
one is the chosen self-hosted GPU-VM path.

**Security model (implemented in `DEPLOY.md`).** The app has **no
login of its own**; access is gated by Azure identity:

- Container binds `-p 127.0.0.1:8501:8501` (VM loopback only) and
  **no NSG rule opens 8501** — the app is never on the public
  internet.
- VM created with `--assign-identity` + the `AADSSHLoginForLinux`
  extension → colleagues sign in over SSH with their **Deltares Entra
  ID** (short-lived cert, no shared keys).
- **RBAC is the guest list:** `Virtual Machine User Login` for
  colleagues (tunnel only), `Virtual Machine Administrator Login` for
  the owner (sudo to build/run), scoped to the VM. Revoke = delete
  the role assignment.
- Access path: `az ssh vm … -- -L 8501:localhost:8501` then browse
  `http://localhost:8501`. The SSH tunnel is the only pipe in.

**VM specifics:** `--image microsoft-dsvm:ubuntu-hpc:2204:latest`
(NVIDIA driver + container toolkit preinstalled — avoids driver-install
pain), `--size Standard_NC4as_T4_v3` (T4 16 GB, fits qwen2.5:7b 4-bit
easily, ~$0.50/hr running and $0 when `az vm deallocate`'d). CPU
fallback is `Standard_D8s_v5` minus `--gpus all`.

**Status.** Files written; test-building `Dockerfile.bundled` locally
on Windows Docker Desktop. First build surfaced the missing-`zstd`
issue (now fixed). Not yet deployed to Azure — running `az`/deploy is
billable + outward-facing, so the agent writes the scripts and the
**user runs them**. Next after a clean local build: draft a commit
message for the four new files (agent must not run git writes), then
the user executes the `DEPLOY.md` steps.

### Memory anchors (from `~/.claude/projects/.../memory/`)

Three persistent constraints that survive across sessions — duplicated
here so the other laptop's first read of CLAUDE.md surfaces them
without needing to load the memory store:

- **Never run git write commands** (no push/commit/add/pull/fetch/
  merge). Draft commit messages for the user to run by hand.
- **Jinja dict-method collisions in templates.** Fields named
  `items`, `keys`, or `values` need bracket lookup (`obj["items"]`)
  not attribute access (`obj.items`), because Jinja sees the dict
  method first.
- **Pydantic field aliases don't reach the template.** Aliases are
  for input JSON parsing only. `model_dump()` emits the field name,
  so templates must use the suffixed form (`import_`, `validate_`,
  etc.) rather than the aliased form.

## LLM-first elicitation (branch `simplify-elicitation`)

The app's prose turns no longer run intent classification, detectors, or
module-support gating. One model call per turn (`fews_agent/agent/llm_turn.py`):
Python assembles grounding digests — catalog (all patterns + required vars +
outputs), state, gap-to-buildable, inputs (CSV headers/rows), last build,
history — and the model returns `{reply, patch}`. The patch is a small CRUD
vocabulary on slots (`fews_agent/agent/patch_ops.py`): each op validates
against the catalog and applies through the existing slot machinery; invalid
ops are dropped LOUDLY. Slots stay the single source of truth; resolvers and
the entire generation half are untouched. Slash commands bypass the LLM
entirely (deterministic). Module focus is ADVISORY context, never a gate.

The sidebar is a FEWS module navigator: click = a `/module` turn (recorded in
history, feeds the model's context); ⚪ = not built, 🟢 = XMLs built
(`ChatSession.module_statuses()`; deriver modules go green on `full_build_ok`).

**This bakes in a capable-model dependency** (gpt-4-class+; deployed:
`azure_ai/gpt-5.4-mini`). A small local model will converse WORSE than the old
deterministic pipeline — deliberate trade, per the Rhine-transcript evidence
that the old scaffolding suppressed strong models.

**File preview (`/show` · `/present` · prose).** The agent shows how a file
WILL generate, in the chat: `/show GFS` / `/show Topology` (deterministic, no
LLM) or prose ("show me the GFS import file") via the `preview_file` patch op.
Rendering is a pure function of state — `blueprint.expand` in memory, ~10 ms
per file measured — so previews are computed fresh per request: no cache, no
background regeneration, structurally never stale. Pattern files render live;
assembly-only files (derived Topology, sa_global.Properties, CSV-ingested
Locations) are shown from the last build, labelled as such. One shared
formatter (`fews_agent/agent/preview.py`) renders header + XSD badge + fenced
XML identically for slash and prose. The prompt forbids the model writing XML
itself — what appears in chat is always the deterministic render.

**The advisor / route model (`fews_agent/agent/project_route.py`) — the GPS.**
The agent used to take orders: after a source was added it pushed "build?"
while variables were still on silent defaults, and forgot unfinished steps
(tester histories). The route model fixes this as *navigation*, NOT domain
judgment (the agent never second-guesses the user's meteorological choices —
"human drives, GPS routes"). It's a PURE, deterministic model of the legs to
a complete config: add a source/model → choose each source's weather
variables (advisory — defaults are OK) → set a map area (advisory) → basin
adapter (blocking) → required input CSVs (blocking, reuses
`compute_input_status`) → assemble. `route_position(state, inputs)` reports
where you are (completed legs, the `current` step in journey ORDER,
`blocking_open`, `advisory_open`, `ready_to_assemble`, `assembled`);
`route_digest` renders it as the prompt's **ROUTE** section (replaced the
retired `gap_digest`). Prompt rules 4a/4b/4e make the model navigate: lead
with the NEXT STEP, never steer to `done` until `ready_to_assemble`, and on
a topic-closer ("thanks") give a brief ack — never re-recite the always-on
ROUTE (the #1 nag). The live eval (`runners/agent/eval_llm_turn.py`, 15
scenarios) is the behavioral spec — `no-premature-assembly`, `routes-in-order`,
`reroute-follows-driver`, plus the mechanical-bug pins (delete-defaulted-var,
adapter-given-first, horizon-bare-number-is-days) all born from real tester
failures. Follow-up not yet done: fold `turn_engine._next_step_hint` (the
CLI/module-mode deterministic next-step, still with the old build-push
phrasing) onto the route so there's ONE guidance source.

**Per-project git change tracking (`app/project_git.py`).** Every session dir
carries its own local git repo (no remotes) over what the agent generates
(`generated/` + `project.yaml`; chat state/logs/inputs excluded via the
session repo's `.gitignore`). After each agent action (`/build`, module
build, full assembly — all three shells) `commit_and_diff` appends unified
diffs to the build reply for files that PRE-EXISTED the action and changed;
first-time files are untracked → never shown → committed as the next
baseline. Diffs land in chat history, so the LLM can answer "why did that
line change?". Confinement is load-bearing: `projects/` sits inside this dev
repo's tree, so every command uses explicit `--git-dir`/`--work-tree`
(pinned by a test); git missing → logged no-op. Docker images install git.
`blob_store` full-sync skips `.git/`.

**Human-test hardening batch (2026-07-22, all shipped).** Driven by two
configurator test transcripts: (1) **honest replies** — dropped ops trigger a
repair call that rewrites the success-claiming draft (`llm_repair.*` prompts;
deterministic fallback); (2) **catalog-driven `set_variables`** — any variable
the target's pattern declares is settable (typed coercion → `import_overrides`
→ resolver stamps it on the instance); (3) **input CSV authoring** —
`write_input_file` op writes/upserts/deletes rows in `inputs/*.csv` validated
against the ingest's own alias table (`input_files.py`); CSVs are git-tracked
(diffs in chat; uploads baseline-commit) and downloadable per-file; (4) prompt
rules 4b–4d (no nagging, changeable=vars-table + ECCC resolution fixed, scoped
build needs no CSVs) pinned by 8 live eval scenarios; (5) **FEWS-loadable
Config bundle** — `fews_bundle_path` remaps `WorkflowFiles/`→`Config/Workflows/`
and puts lowercase `sa_global.properties` at the region root (delivery-time
only; generation tree keeps the tutorial layout for the byte-eq oracle); (6)
**stale/forced amber sidebar** — builds stamp content fingerprints, mismatch →
🟠, `/force-done` → 🟠 until a clean done; (7) **prose undo** op (double-pop
snapshot); (8) **streaming replies** (`reply_stream.py` extracts the reply
field from the JSON stream; LiteLLM-only, falls back silently) + **telemetry**
(`state["llm_usage"]` totals, header caption); (9) **semantic validation in
chat** — full assembly retains rendered Pydantic models, runs
`validate_semantic`, and `build_digest` carries refs/unresolved (+examples).
Sidebar module click sends "Let's build <folder>!" not `/module`. Deliberately
NOT done: concurrency lock, CLI switchover + strangling (both user-skipped).

Prompts: `prompts/llm_turn.{system,user}.txt` — the system prompt IS the
elicitation program (priority-ordered rules, op schema, few-shot examples incl.
the never-guess-an-adapter Rhine case). Prompt regressions are caught by the
golden-transcript eval `python -m runners.agent.eval_llm_turn` (LIVE model,
opt-in; asserts on patches + banned internal vocabulary, never exact wording).
Deterministic oracles: `tests/test_patch_ops.py`, `tests/test_llm_turn.py`.
CLI/API still run the older module-mode path — switchover after app parity.
