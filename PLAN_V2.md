# PLAN_V2.md — Verification-first FEWS configuration agent

Status: **Phases 0–4 shipped** (verification toolbelt, conform seeds,
brownfield `open_config`, ledger-gated `write_output`, MCP generation
tools). Phase 5 (demote `project.yaml` into the ledger) is **not
started**. Successor to the methodology in `PLAN.md` (LLM-first
*elicitation* on branch `simplify-elicitation`). Read §1–§3 before
judging the phases in §5.

The generation half (patterns → Jinja → Pydantic → XSD) is **not deleted by
this plan**. It is demoted from *the only way to produce XML* to *the fast
path for known shapes*. The regression oracles in `CLAUDE.md` stay green
throughout.

---

## 1. Diagnosis — one root cause, not three problems

Three symptoms were reported:

1. The pattern library is incomplete (70 patterns farmed from past projects;
  anything unfarmed is unreachable).
2. The agent cannot work from, or modify, an **existing** FEWS configuration.
3. A frontier model with the public FEWS wiki (ChatGPT / Claude Desktop)
  authors good-looking config, but has no validation and no sense of
   FEWS-conform naming.

These are one root cause: **the pattern library is a closed generative
vocabulary, and the blueprint is the only representation of project state.**

Everything must be expressible as `slots → resolver → pattern instances → XML`. That single constraint produces all three symptoms:


| Symptom                        | Why the closed vocabulary causes it                                                                                                                                                                          |
| ------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| Coverage gap                   | A capability with no farmed pattern has no representation at all. There is no "author it anyway" path — a pattern miss is a hard stop.                                                                       |
| No brownfield                  | An existing config is not a blueprint, and there is no inverse map XML → blueprint. State lives in `slots`; a config tree cannot be loaded into it.                                                          |
| Can't use the wiki-smart model | The architecture forbids the LLM from writing XML (`CLAUDE.md`: "The LLM does not write XML directly in the default path"). The one thing frontier models are demonstrably good at is structurally excluded. |


The empirical datapoint from the ChatGPT/Claude Desktop test is the most
important input to this plan, and it should be read precisely:

> A frontier model + public wiki is already a competent FEWS config
> **author**. It is a hopeless FEWS config **verifier**.

This repo is the mirror image. It contains a genuinely excellent verifier —
260 pinned XSDs, 218 typed Pydantic spec models, a cross-file ID reference
walker keyed on `NewType` annotations — with a mediocre-coverage author
bolted on top of it. The scarce asset is being used as a gate on the
abundant one.

**The inversion this plan proposes:** stop shipping a generator that happens
to validate. Ship a **verification and grounding harness** that happens to
generate. Coverage then comes from the model (open-world); correctness comes
from the harness (closed-world). Patterns stay for determinism where
determinism is worth paying for.

---



## 2. What each existing asset becomes

The user's question was "combine skills and python scripts or patterns or
examples?" — yes. Here is the division of labour. Nothing valuable is thrown
away; several things change job.


| Asset                                                         | Today                            | Under this plan                                                                 |
| ------------------------------------------------------------- | -------------------------------- | ------------------------------------------------------------------------------- |
| `fews_agent/schemas/` (260 XSDs)                              | validation gate                  | gate **+ authoring grounding** (serve the XSD fragment for a spec to the model) |
| `fews_agent/schema/` (218 Pydantic models, `ids.py` NewTypes) | render-time typing               | the **machine-readable FEWS domain model** — the thing no wiki and no model has |
| `validation/semantic.py`                                      | post-build report                | a callable service over *any* config tree, greenfield or existing               |
| `patterns/auto/` (70)                                         | the only generator               | **fast path** for known shapes + **example corpus** for retrieval               |
| `examples/config-tutorial/`, FEWS-Conform                     | regression fixtures              | fixtures **+ the corpus the conform rules are mined from**                      |
| `pattern_farm/xml_ingest.py`                                  | offline pattern farming          | the **brownfield reader** (XML → typed/generic IR)                              |
| `agent/edit_modes/` (16 modules)                              | per-spec structured editing      | the safe-edit surface for brownfield changes                                    |
| `app/project_git.py`                                          | change tracking in chat          | the **diff/review substrate** for edits to someone's real config                |
| `app/mcp_server.py`                                           | 4th driver shell (session-bound) | **the product surface** — a stateless toolbelt any host LLM can call            |
| `blueprint` / `project.yaml`                                  | the state                        | a **provenance ledger** (see §4)                                                |


Two assets are new: the **conform linter** (§5 Phase 2) and the **headless
FEWS check** (§5 Phase 0).

---



## 3. Target architecture — three layers

```
            ┌─────────────────────────────────────────────────────┐
            │  AUTHOR (open world)                                │
            │  frontier LLM — wiki knowledge, prose, intent        │
            │  writes XML / typed IR / edits to an existing tree   │
            └───────────────┬─────────────────────────────────────┘
                            │  proposes
                            ▼
            ┌─────────────────────────────────────────────────────┐
FAST PATH   │  VERIFICATION GAUNTLET (closed world, deterministic) │
patterns ──►│   1 XSD          shape                               │
            │   2 semantic     cross-file ids resolve              │
            │   3 conform lint naming / convention                 │
            │   4 FEWS check   the real thing loads it             │
            └───────────────┬─────────────────────────────────────┘
                            │  pass → write + commit + diff
                            │  fail → structured errors → repair (capped)
                            ▼
            ┌─────────────────────────────────────────────────────┐
            │  CONFIG TREE + PROVENANCE LEDGER                     │
            │  who owns each file: pattern | llm | human           │
            └─────────────────────────────────────────────────────┘
```

**Layer 1 — Ground truth services.** Pure, stateless, path-based Python.
Each independently callable as an MCP tool. This is the deliverable that
makes the user's ChatGPT experiment *correct* instead of merely plausible.

**Layer 2 — The author.** Open-world. May be our own `llm_turn`, or may be
Claude Desktop / ChatGPT / Copilot calling Layer 1 over MCP. Deliberately
**not** privileged: the harness does not care who authored the XML.

**Layer 3 — Fast paths.** When a request matches a pattern, use the pattern:
deterministic, byte-stable, free, already tested. The single behavioural
change is that **a pattern miss degrades to Layer 2 instead of failing.**

### The key architectural rule

> Nothing reaches disk unverified — but anything that verifies may reach
> disk, regardless of who wrote it.

This is what breaks the coverage ceiling. Today provenance determines
admissibility (only patterns may emit). Under this plan **verification
determines admissibility**, and provenance only determines *regenerability*.

---



## 4. The provenance ledger (what replaces the blueprint as state)

The blueprint's fatal property for brownfield work is that it is *generative*
— it describes how to rebuild everything from scratch, so re-running it
clobbers anything it doesn't know about. An existing config always contains
files it doesn't know about.

Replace it with a ledger that records, per file, **who owns it**:

```yaml
# .fews-agent/ledger.yaml  (lives beside the config tree)
files:
  ModuleConfigFiles/Import/NOAA/ImportGFS.xml:
    origin: pattern            # regenerable — safe to overwrite
    pattern: auto/nwp_grid_noaa
    instance: {nwp_name: GFS}
    fingerprint: sha256:…      # detects human edits since we wrote it
  ModuleConfigFiles/Custom/ImportKNMI.xml:
    origin: llm                # authored once, verified; NEVER auto-regenerated
    authored: 2026-09-21
    verified: [xsd, semantic, conform, fews_check]
  RegionConfigFiles/Filters.xml:
    origin: human              # pre-existing / user-edited — read-only to us
```

Consequences, all of which are properties the current design lacks:

- **Greenfield becomes a special case of brownfield** (an empty tree with an
empty ledger). One code path, not two.
- Re-running generation on a real config is safe: `origin: human` is never
touched, `origin: pattern` with a drifted fingerprint is flagged not
overwritten.
- A one-off LLM-authored file is a *first-class, persistent* artifact rather
than something that must be promoted to a pattern to survive.
- Pattern promotion becomes an explicit, optional step: "you've authored this
shape three times — farm it into a pattern?" That is how the library grows
from real use instead of from archaeology.

`project.yaml` does not disappear; it becomes the `origin: pattern` section
of the ledger.

---



## 5. Implementation phases

Ordered by (value × confidence) ÷ risk. Each phase is independently
shippable and leaves the suite green. Phases 0–2 touch **no existing
behaviour at all** — they are pure additions.

### Phase 0 — Wire the headless FEWS check (new ground truth)

Confirmed available. This matters more than it looks: it is the only oracle
that answers "does FEWS actually accept this?", and every other tier of the
gauntlet is an *approximation* of it. Until it is wired, we are guessing how
good our guessing is.

- **New:** `fews_agent/validation/fews_check.py` — subprocess wrapper, parse
the check output into the same structured-diagnostic shape as the other
validators (file, line, severity, message, rule id).
- **Calibration study** (the real deliverable): run all four tiers over
(a) `examples/config-tutorial/`, (b) the tutorial build output, (c) the
`projects/` fixtures, (d) two or three deliberately broken configs.
Produce a confusion matrix: what does FEWS reject that XSD + semantic +
conform pass, and vice versa?
- **Expected finding, worth being ready for:** XSD+semantic will pass things
FEWS rejects. Every such case is a specification for a new conform rule
(Phase 2) — this is how the rule set gets *mined* rather than invented.
- Keep it **optional and degradable**: no FEWS on the machine → tier 4 is
skipped with a visible note, never a crash (same contract as `project_git`
when git is absent).

**Exit criteria:** `validate_config(path, tiers=[...])` runs all four tiers;
calibration matrix committed as a markdown table; tier 4 absence degrades
cleanly.

### Phase 1 — The verification toolbelt (stateless MCP tools)

The highest value-per-risk step, and the one that directly closes the gap the
user found. Today every MCP tool in `app/mcp_server.py` is **session-bound**
(`create_project` / `chat` / `build` / `get_status` all take a `session_id`).
The new tools must be the opposite: **stateless and path-based**, so they work
on an arbitrary existing config folder that this agent never created.

New tools, all pure functions of a path or a string:


| Tool                 | Signature                                               | Backed by                                              |
| -------------------- | ------------------------------------------------------- | ------------------------------------------------------ |
| `validate_config`    | `(path, tiers?) → diagnostics[]`                        | `xsd.py` + `semantic.py` + Phase 2 + Phase 0           |
| `validate_xml`       | `(xml_string, spec?) → diagnostics[]`                   | `xsd.py` — validate a snippet before it's ever written |
| `conform_lint`       | `(path) → diagnostics[]`                                | Phase 2                                                |
| `schema_shape`       | `(spec) → {xsd_fragment, json_schema, required, enums}` | 218 Pydantic models + XSDs, nearly free                |
| `find_examples`      | `(query, k?) → [{path, xml, provenance}]`               | patterns + tutorial + Conform corpus                   |
| `id_registry`        | `(path) → {declared: {type: [ids]}, refs, unresolved}`  | `semantic.py`                                          |
| `explain_diagnostic` | `(rule_id) → prose + fix + example`                     | Phase 2 rule metadata                                  |


Design notes that matter:

- **Structured diagnostics, not prose.** One dataclass:
`Diagnostic(file, line, severity, rule_id, message, fix_hint, evidence)`.
Every tier emits it. The whole point is that a *model* consumes these and
repairs; free-text errors force it to guess.
- `schema_shape` is the antidote to wiki-recalled prose. The model stops
remembering what `<timeSeriesSet>` allows and reads the pinned grammar. Note
the known gotcha from `CLAUDE.md` — typed vs generic-body rendering,
`extra="forbid"` — exactly the class of error this eliminates.
- **This is the ChatGPT-experiment fix.** With these registered, the user's
Claude Desktop session keeps its wiki fluency and gains the validator it
lacked. That is worth shipping on its own, even if no later phase happens.
- Publish a short `README_MCP.md` section: "using the toolbelt without the
agent" — point it at any config folder.

**Exit criteria:** the seven tools registered and callable from Claude Desktop
against a config folder this repo never generated; a transcript showing a
caught-and-repaired error that the model would otherwise have shipped.

### Phase 2 — `fews_conform_lint` (the unique IP)

This is the piece that exists nowhere else — not in the wiki, not in any
model's weights, not in the XSDs. It is also the cheapest real differentiator
in the plan.

- **New:** `fews_agent/validation/conform.py` — a versioned rule registry.
Each rule: stable `rule_id`, severity, detector, fix hint, and a citation
(which reference config or wiki page motivates it).
- **Seeds already in the repo:** `csv_ingest.lint_conform_headers`
(PascalCase attributeIds, duplicate headers) — generalise it out of the CSV
ingest into the rule registry, keeping the current call site working.
- **Mine, don't invent.** Derive candidate rules empirically from the two
reference corpora already present (`examples/config-tutorial/`, the
FEWS-Conform lineage that produced the `import_era5`/`import_imerg`/
`archive_*` patterns), plus every Phase-0 case where FEWS rejected what our
tiers passed. A rule with no corpus evidence does not ship.
- **Candidate rule families** (to be confirmed against the corpora, not
assumed): parameterId conventions (`PC.nwp` / `TA.obs` — quantity, source
suffix), moduleInstanceId conventions (`Import<Source>`,
`Preprocess<Source>`), idMap file/id agreement (the known
`IdImportGlobSnow` vs `IdImportGLOBSNOW` casing bug is a *ready-made test
case* — it breaks on Linux FEWS and no XSD catches it), file naming vs
declared id, locationId/locationSetId usage, unit consistency per
parameter.
- **Severity discipline:** `error` only for things that break FEWS;
`warning` for portability (the casing bug); `convention` for house style.
A linter that cries wolf gets muted.
- **Do not break the byte-equivalence oracle.** The tutorial contains known
violations (documented in `CLAUDE.md` "Known findings"). The linter must
*report* them; nothing in the generation path may auto-fix them.

**Exit criteria:** rule registry with ≥1 corpus-cited test per rule; the three
documented tutorial bugs are detected by rule id; zero findings on the
FEWS-Conform-derived pattern outputs.

### Phase 3 — Brownfield read (`open_config`)

- **New:** `fews_agent/agent/config_tree.py` — load an existing config folder
into: file index, per-file typed model where a schema exists / generic dict
where not, the id registry, and a ledger (all files `origin: human` on first
open). Reuses `pattern_farm/xml_ingest.py` for the XML → IR half.
- **Pattern recognition (optional, valuable):** match loaded files against the
70 patterns to reclassify `human` → `pattern` where a file is
byte-or-shape-equivalent to a known pattern output. Turns an opaque config
into a partially-understood one. `pattern_farm/diff_finder.py` is the
starting point.
- **Unify greenfield:** a new project is `open_config` on an empty dir. Delete
nothing yet — run both paths in parallel until the oracles agree.
- MCP: `open_config(path) → summary` + make the Phase 1 tools accept a loaded
tree.

**Exit criteria:** `open_config(examples/config-tutorial)` yields a complete
id registry and a ledger over all 135 files; round-trip (open → write
untouched) is byte-identical.

### Phase 4 — Open-world authoring inside the gauntlet

Only now does the LLM get to write XML on the main path.

- **New:** `fews_agent/agent/authoring.py` — `author_file(request, context) → AuthoredFile`. Context = `schema_shape` + `find_examples` + `id_registry`.
Output goes straight into the gauntlet; on failure, feed the structured
diagnostics back for a **capped** repair loop (the `filter_drafter.py`
validate-repair-fallback shape is the proven local precedent — reuse it,
don't invent a new one).
- **Wire the fallback:** pattern miss → author. This is the one line that
removes the coverage ceiling. Everything before this phase exists to make it
safe.
- Ledger marks the result `origin: llm` with the tiers it passed.
- **Editing existing files** uses `edit_modes/` where a mode exists (typed,
safe) and falls back to whole-file authoring with a diff for review; every
edit is committed via `project_git` so the user sees exactly what changed.
- Keep `PLAN.md`'s hard-won rules: validate-don't-trust, drop invalid loudly,
never claim an action that didn't happen.

**Exit criteria:** a capability with no pattern (pick a real one — e.g. a KNMI
or DWD import) is configured end-to-end, passes all four tiers, and survives
a rebuild without being clobbered.

### Phase 5 — Demote the blueprint (optional, last)

Only if Phases 3–4 prove the ledger. Migrate `project.yaml` to the ledger's
pattern section; keep `build_from_blueprint` working for the two regression
oracles. Do not start this while anything above is in flight.

---



## 6. What must not regress

Non-negotiable, checked after every phase (`CLAUDE.md` "Verification
checklist"):

- Tutorial build: **120 files, 120/120 XSD, 118/120 byte-equal**, 27
unresolved semantic refs (the documented tutorial bugs — the number must not
*change*).
- Small build: **29 files, 28/28 XSD + 1 non-XML**.
- `python -m pytest tests/ -q` green (488 at `PLAN.md` handoff, 52 test
modules).
- `python -m runners.agent.eval_llm_turn` (live) unchanged.

Phases 0–2 cannot touch these by construction (pure additions). Phases 3–5
can — run the checklist before and after each.

---



## 7. Revisions to earlier decisions (stated explicitly)

`PLAN.md` §8 lists non-goals. Two are revised here; the rest stand.

- **"No embeddings/RAG."** That non-goal was scoped to the *pattern catalog*,
which genuinely fits in a prompt (~6k tokens). It does not extend to 260
XSDs and a multi-hundred-file example corpus, which do not. `find_examples`
and `schema_shape` are **retrieval over grammar and evidence**, not a
retrofit of the thing that was rejected. Starting point should be plain
keyword/structural lookup — reach for embeddings only if that measurably
fails.
- **"The LLM does not write XML directly"** (`CLAUDE.md`). Revised to: *the
LLM does not write XML that bypasses the gauntlet.* Provenance no longer
gates admissibility; verification does. Determinism is preserved where it is
paid for (patterns, ledger `origin: pattern`) and explicitly traded away
where the alternative is no coverage at all.

Standing rules that do **not** change: never run git write commands (draft
messages for the user); prompts live as `.txt` under `agent/prompts/`; fail
loudly, never silently; validate twice.

---



## 8. Principal risks


| Risk                                                                                                        | Mitigation                                                                                                                                                                        |
| ----------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **XSD+semantic+conform all pass, FEWS still rejects it.** The gauntlet is only as good as its weakest tier. | Phase 0 first, precisely to measure this. Tier 4 is the real oracle; tiers 1–3 are the fast approximation. Every miss becomes a rule.                                             |
| **Loss of determinism** — two runs diverge.                                                                 | Ledger `origin: pattern` stays byte-stable; `origin: llm` is authored **once** and never silently regenerated. The tutorial byte-eq oracle stays.                                 |
| **Conform linter becomes folklore** — unfounded rules, noisy output.                                        | Corpus citation required per rule; three severity levels; no rule ships without a test derived from real config.                                                                  |
| **Scope explosion** — this is five phases.                                                                  | Phases 0–2 are independently valuable and touch nothing. It is legitimate to stop after Phase 2 and simply have the best FEWS validator in existence, usable from any AI client.  |
| **Brownfield data loss** — we corrupt someone's real config.                                                | Never write without a passing gauntlet; every write via `project_git` with a reviewable diff; `origin: human` is read-only by default; operate on a copy until Phase 3 is proven. |


---



## 9. Suggested first commit

Phase 0 only:

```
Add headless FEWS configuration check as validation tier 4

New fews_agent/validation/fews_check.py wraps the FEWS config checker as a
subprocess and parses its output into structured diagnostics. Degrades to a
skip (never a failure) when FEWS is unavailable, matching the project_git
contract.

Includes a calibration run over examples/config-tutorial and the tutorial
build output comparing all four tiers — the baseline for mining conform
rules in the next phase.
```

