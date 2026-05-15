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
   pulls structured facts — basins (any capitalised name, including
   multi-word like "Mackenzie River basin"), model adapters
   (raven/wflow/hbv96), imports (HRDPS/GFS/...), geo datum, locations
   source.
2. **Intent classification** (LLM, only on first turn): qwen2.5
   picks one of `build_forecasting_project`, `build_data_import_only`,
   `build_basin_model_only` based on the user's prose. Falls back to
   a heuristic on filled slots if the LLM output is unparseable.
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

### Uncommitted local changes (worth committing once verified)

Two files are dirty on this branch:

- **`fews_agent/agent/project_intents.py`** — adds
  `ENGLISH_WORD_BLOCKLIST` (frozenset) and `_is_blocked_basin(name)`
  helper. Applied at all four basin-extraction sites in
  `extract_skills` and the LLM-intent fallback path. Fixes a
  false-positive where common English words ("We", "It", "Next", "Hi",
  "Our", "Imports", ...) leaked through the capitalised-name regex
  and became phantom basins. The blocklist is the single source of
  truth — `chat_step.py` imports it rather than maintaining a parallel
  set.
- **`runners/agent/chat_step.py`** — two changes:
  1. Replaces the local `bad_basin_tokens` literal with an import of
     `ENGLISH_WORD_BLOCKLIST` from `project_intents`.
  2. Hardens the "no pattern in library" warning detector. Previously
     it only matched `mentioned_imports` against instance-variable
     values like `nwp_name` or `template_name`, which caused
     false-positive warnings for sources like `NAM` and `SREF` whose
     patterns expose `template_name: ImportNAMGrids` (a workflow
     name, not the source name). The detector now also checks the
     pattern names themselves by substring:
     `if not any(m.lower() in pn for pn in pattern_names_lower)`.

Untracked: **`scripts/draw_ux_flow_pdf.py`** — a presentation helper
that emits a UX-flow PDF. Not on any build path; safe to keep or
discard.

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

### Open threads / next likely tasks

- Commit the two dirty files. Suggested message:
  `Eliminate basin-regex and warning-detector false positives`
  (blocklist + pattern-name substring check; tested via rhine-blocklist
  + tutorial-csv-only demos).
- Consider promoting `ENGLISH_WORD_BLOCKLIST` from a frozenset literal
  to a data file if the list grows past ~50 entries — current scale
  doesn't justify it yet.
- The plan file
  `~/.claude/plans/now-lets-build-the-bubbly-spark.md` (29 typed-spec
  promotions + tutorial sharpening) is an older plan; it is **not the
  active workstream** on this branch. The pattern-agent thread is.
