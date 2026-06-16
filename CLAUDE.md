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

```
fews_agent/
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

patterns/                          Pattern library — one folder per pattern
  auto/<pattern_name>/
    pattern.yaml                   Variables + outputs (Jinja-templated)
    contributions.yaml             Optional: cross-file singleton fragments

runners/
  agent/
    build_from_blueprint.py        Main runner: project.yaml → rendered config tree
    chat_step.py                   Single-turn chat driver
    replay.py                      Re-run a saved chat history

schemas/                           FEWS XSDs, pinned to a specific FEWS version
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
  / `HRDPA` in their timeSeriesSets. These aren't locations in
  `Locations.xml`; they're declared in `LocationSets.xml` (generic-body
  file). The typed reflection walker can't see declarations inside
  `GenericXmlFile.body` dicts — they register as unresolved until the
  validator is extended to scan generic bodies.

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

## Chat agent (`runners/agent/chat_step.py`)

Turn-by-turn driver that composes a `project.yaml` from natural-
language conversation. The flow per turn:

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
4. **Pattern resolution**: the active intent's `resolver` maps
   `(slots, catalog) → list of pattern instances`. Each intent owns
   its own resolver in `project_intents.py`.
5. **LLM reply** (`compose_reply`): qwen2.5 phrases the user-facing
   acknowledgment + question. The system prompt is hardened against
   fabrication: it gets a KNOWN/UNKNOWN slot split and a rule that
   values under UNKNOWN must not appear in the reply.

State persists under
`projects/<project>/<project>_<datetime>/.chat_state.json`. Special commands:
`done` writes the project.yaml (validates intent readiness first);
`yes`/`no` confirm a proposed pattern removal.

### Adding a new skill

A skill is a deterministic function `text → value` (or `→ list[value]`).
Add it to `project_intents.py`, wire it into `extract_skills(text)`,
and add the slot key to the relevant intent's `required_slots` /
`optional_slots`. Skills are regex/keyword based — no LLM. If the
extraction is genuinely fuzzy, push it into the LLM intent classifier
instead.

### Adding a new intent

Three pieces:
1. A `resolver(slots, catalog) → list of pattern instances` function.
2. An `Intent(...)` entry in the `INTENTS` registry with required/
   optional slots and slot-question text.
3. An `INTENT_INPUT_EXPECTATIONS[<name>]` block listing required CSVs,
   recommended CSVs, configurator-required yamls, and
   auto-generated yamls. The reply LLM uses this to know what to
   ask the user for and what NOT to ask for.

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

Branch: **`build-pattern-agent`**. Last committed work: `a227062
End-to-end configurator UX: /edit handlers, yaml starters, output
relocation`. The HEAD commit gives a working end-to-end chat → build
pipeline; everything below is layered on top.

**Active context:** the user is prepping a presentation about this
system. Most recent work clusters around (a) eliminating chat-agent
false positives so the demos are clean, (b) building reference
projects to show off each behaviour, and (c) clarifying the mental
model for the audience. No active in-flight code change.

### Mental model in 30 seconds

The agent has **two halves**:

1. **Elicitation half (chat).** LLM talks to the user, extracts
   structured facts, decides which patterns are needed, writes
   `project.yaml`. Lives in `runners/agent/chat_step.py` +
   `fews_agent/agent/project_intents.py`.
2. **Generation half (build).** Deterministic pipeline reads
   `project.yaml`, expands patterns, ingests CSVs, fills with
   bundled standards, runs derivers, validates twice (Pydantic +
   XSD), writes XML. Lives in `runners/agent/build_from_blueprint.py`.

Only **4 LLM jobs** in the whole system — everything else is templating
or deterministic code:

| # | Where | Job | Model |
|---|---|---|---|
| 1 | chat | Intent classification (build_forecasting_project / data_import_only / basin_model_only) | qwen2.5 |
| 2 | chat | Entity extraction backup (when regex skills miss) | qwen2.5 |
| 3 | chat | Compose user-facing reply | qwen2.5 |
| 4 | build | Draft `Filters.xml` from project IDs | qwen2.5 |

If Ollama is down, the chat half fails loudly; the build half still
works end-to-end (job 4 falls back to the bundled standard
`filtersFile.yaml`).

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

Today the bbox/resolution/horizon plumbing is NOAA-only (the only
pattern hard-wired into `_PARAMETERIZED_NWP_PATTERNS`). Extending to
ECCC (HRDPS/GDPS/RDPS/REPS) is symmetric work if anyone wants it.

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
  and drops 16 stale template patterns. Same 36/35 build.

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
```

If any of (2)–(5) drift, **stop** — the build path is the foundation
of every demo, and silent drift here invalidates everything else.

### File-pointer guide (where everything lives)

When picking up cold, these are the files that matter most. Read in
this order to recover context fast:

```
CLAUDE.md                                         this file (top-of-mind context)

# Elicitation half
runners/agent/chat_step.py                        turn loop, special commands, warning surfacing
fews_agent/agent/project_intents.py               skills, intent registry, resolvers, blocklist
fews_agent/agent/project_chat.py                  state I/O, pattern catalog loading
fews_agent/agent/providers/ollama_provider.py     the only place that talks to qwen2.5

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
6. **Support a free-form, multi-capability "import + interpolate +
   visualize" request style.** A colleague wants the agent to handle
   prompts shaped like:

   > "Configure a NOAA GFS import for the Gulf of Guinea with wind
   > speed, wind direction, and mean sea level pressure. Interpolate
   > the imported gridded data to locations for visualizing in the
   > Data Viewer, and visualize the spatial data in the Spatial
   > Display. The list of locations with coordinates is provided in
   > the .csv file." (+ attached locations CSV)

   This is a richer intent than the current `build_data_import_only`
   path covers. Gaps to close:
   - **Parameter selection from prose.** Extract a *specific* NWP
     variable subset (wind speed, wind direction, MSLP) and map each
     to FEWS parameterIds — today's import patterns pull a fixed set,
     not a user-chosen subset.
   - **Region as a grid extent, not a basin.** "Gulf of Guinea" is an
     area/grid bbox, not a Raven basin — needs a region/extent slot
     distinct from `basin_name`.
   - **Grid→point interpolation step.** Emit the interpolation module
     config (gridded import → interpolated-to-locations timeseries)
     so the data lands in the **Data Viewer**.
   - **Spatial Display output.** Emit/extend `gridDisplay` /
     `SpatialDisplay` config so the gridded field is viewable.
   - **Attached locations CSV** drives `Locations.xml` /
     `LocationSets.xml` (the interpolation targets) — wire the
     uploaded CSV into the existing CSV-ingest layer.

   Likely needs: a new intent (e.g. `build_import_interpolate_visualize`)
   with its own resolver + `INTENT_INPUT_EXPECTATIONS`, a parameter-
   subset skill, an extent/region slot, and possibly a new
   interpolation pattern under `patterns/auto/`.

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
  `docker-entrypoint.sh`, CMD = `streamlit run app/web_app.py`.
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
