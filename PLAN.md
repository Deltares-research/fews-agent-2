# PLAN.md — LLM-first elicitation (branch `simplify-elicitation`)

Read this whole file before changing elicitation code. It is written to be
followed without prior context. The generation half (patterns → Jinja →
Pydantic → XSD) is FINISHED and CORRECT — do not touch it for any task in
this plan.

## 1. The spirit (why this architecture exists)

The old elicitation was a Python pipeline built for a weak local model
(qwen2.5:7b): intent classification into a fixed taxonomy, 23 regex
detectors, module-support gates, deterministic reply templates. With a strong
model (deployed: `azure_ai/gpt-5.4-mini`) that scaffolding SUPPRESSED the
model — documented evidence: a user said "i need it for the rhine basin",
the classifier misrouted to the Root module, the gate refused "use the Rhine
basin" ("Root doesn't support 'set'"), and a template lied ("this module is
ready"). Every wrong sentence was ours; every correct one was the model's.

**The rule that replaced all of it:**

> The LLM decides and phrases. Python briefs (context) and validates
> (trust boundary). Python NEVER decides what the user meant.

Consequences you must preserve:
- ONE model call per prose turn (not an agent loop). Feasible because the
  whole domain fits in the prompt (~72 patterns ≈ 6k tokens).
- Anything the model wants to change arrives as a PATCH of small ops;
  every op is validated against the catalog; invalid ops are dropped
  LOUDLY (shown to the user), never silently.
- Slots (`state["slots"]`) remain the single source of truth; the
  deterministic resolvers rebuild `state["patterns"]` from slots each turn.
- Slash commands (`/vars`, `/build`, `/add`, `/module`, `/done`, ...) bypass
  the LLM entirely — the deterministic escape hatch.
- Module focus is ADVISORY context for the model — NEVER a gate. Do not
  reintroduce "module X doesn't support action Y" on any prose path.
- Capable-model dependency is accepted and documented. Do not add fallback
  heuristics "for weaker models" — that is the old architecture returning.

## 2. Architecture (one screen)

```
user prose ─► llm_turn.run_llm_turn(state, msg, catalog, provider, history, inputs_dir)
                │  Python assembles ONE prompt from digests:
                │    catalog_digest  – every pattern: name, description,
                │                      required/optional vars, output files
                │    state_digest    – slots, focused module (advisory), built
                │    gap_digest      – computed gap to a buildable project
                │    inputs_digest   – CSVs in inputs/ (headers + row counts)
                │    build_digest    – last build summary (files, XSD, errors)
                │    _history_text   – last ~8 turns
                ▼
              model returns ONE JSON: {"reply": str, "patch": [op, ...]}
                ▼
              patch_ops.apply_patch(state, ops, catalog)
                │  validate each op → apply via existing slot machinery
                │  invalid → PatchResult.dropped (appended loudly to reply)
                │  build/assemble/open_coordinates → SIGNALS (no state change)
                ▼
              ModuleTurnResult(reply, confirmation=grey applied-notes,
                               wants_build, build_scope, wants_assemble,
                               coordinates_for, new_patterns)
slash cmds ─► existing deterministic handlers (never call the LLM)
```

## 3. File map (what owns what)

| File | Role | Touch when |
|---|---|---|
| `fews_agent/agent/llm_turn.py` | the single call + the 5 digests | adding grounding info, changing the call |
| `fews_agent/agent/patch_ops.py` | op vocabulary + validation + apply | adding/changing an op |
| `fews_agent/agent/prompts/llm_turn.system.txt` | THE elicitation program: rules (priority-ordered), op schema, few-shot examples | any behaviour change in how the model acts |
| `fews_agent/agent/prompts/llm_turn.user.txt` | template holding the digests | adding a digest section |
| `app/chatter.py` `send()` | app wiring: prose→run_llm_turn, signals→build/coords/done | shell behaviour |
| `app/chatter.py` `module_statuses()` | sidebar grey/green per FEWS module | status logic |
| `frontend/web_app.py` | sidebar module navigator + chat render | UI only |
| `runners/agent/eval_llm_turn.py` | golden-transcript LIVE eval | after ANY prompt change |
| `tests/test_patch_ops.py`, `tests/test_llm_turn.py` | deterministic oracles | with every engine change |

Legacy (still used by CLI + parts kept for slash commands — see §6):
`turn_engine.py` (run_module_turn, run_turn_pipeline, module_vars_text,
_history_text, apply_extracted_fields...), `extractor.py`,
`project_intents.py` (detectors, resolvers — resolvers are KEPT forever).

## 4. Contracts (do not change without updating both sides)

### Patch ops (model → patch_ops)
```
add_import       {name, data_types?[], grid_resolution?, forecast_horizon_hours?}
add_basin        {basin_name, model_adapter}   adapter ∈ raven|wflow|hbv96, NEVER guessed
add_capability   {pattern}                     catalog name/path; errors list required vars
set_variables    {target, values{}}            per-import scalars; grid_geometry dict;
                                               data_types keys are intercepted → additive list
remove           {target}                      import | basin | data type | capability
set_focus        {module}                      advisory focus only
open_coordinates {name?}                       UI signal
build {scope?} · assemble {} · none {}         signals / no-op
```
Both sides = `patch_ops.py` AND the op table + examples in
`llm_turn.system.txt`. Change one → change the other → run the eval.

### Model response
`{"reply": str, "patch": [ {"op": name, ...args} ]}` — enforced by
`_RESPONSE_SCHEMA`, one repair round on malformed output, then a graceful
fallback reply (nothing applied).

### Prompt rules that MUST survive edits (each fixed a real failure)
1. Never invent domain objects (catalog is the only source of names).
2. Never guess a missing required value — ask, leave the op out (Rhine rule).
3. Correctness beats brevity — never claim "ready/nothing left" against the gap digest.
4. No internal vocabulary in replies (slot, pattern, resolver, runner, ...).
5. No slash commands in replies (except pointing at /help when asked).

## 5. How to verify (run after EVERY change)

```bash
python -m pytest tests/ -q                      # deterministic suite (488 at handoff)
python -m runners.agent.eval_llm_turn           # LIVE model, 4 scenarios, needs .env
python -m pytest tests/test_patch_ops.py tests/test_llm_turn.py -q   # fast inner loop
streamlit run frontend/web_app.py               # manual: sidebar modules, chat, build
```
The eval asserts on PATCH CONTENT and banned vocabulary — never exact
wording. If you change a prompt and the eval fails, the prompt change is
wrong, not the eval.

## 6. Roadmap (in order; each step keeps the suite green)

- [x] patch_ops + llm_turn + prompts + app wiring + sidebar navigator
- [x] golden-transcript eval (4/4 live)
- [ ] **API switchover**: `app/api/server.py` `/turn` still runs
      run_module_turn/run_turn_pipeline — replace the prose path with
      run_llm_turn exactly like chatter.send (keep `_module_command` slash
      bypass; map signals onto TurnResponse; migrate the API tests that
      stubbed the old seams the way tests/test_chatter_*.py were migrated).
- [ ] **CLI switchover**: `runners/agent/chat_step.py` same treatment.
- [ ] **Strangle** (only AFTER both switchovers; delete in this order, running
      the suite between deletions):
      1. `turn_engine.run_turn_pipeline` + intent-disambiguation machinery
      2. `turn_engine.run_module_turn` + compose_module_reply + _next_step_hint
      3. `extractor.parse_turn` / `extract_operation` / `deterministic_module_op`
      4. prose detectors in `project_intents.py` that nothing imports anymore
         (KEEP: resolvers, _IMPORT_PATTERN_MAP, _ADAPTER_PHRASES,
         _DATA_TYPE_TO_PARAMETER — patch_ops validates against these;
         KEEP: detect_* used by slash parsing / csv ingest)
      5. prompts of retired paths (parse_turn.*, module_reply.*, compose_reply.*)
- [ ] **Stale-green**: a module edited after building stays 🟢 — flip back to
      ⚪ when its slots change post-build (compare a hash captured at build).
- [ ] **Optional repair round**: when apply_patch drops ops, give the model
      ONE extra call with the drop reasons before replying (only on turns
      that actually erred). Do not build an agent loop.

## 7. Gotchas (all cost real debugging time — believe them)

- `.env` loads via `load_dotenv(REPO/".env", override=True)` — plain
  `load_dotenv()` in a script outside the repo silently finds nothing and you
  test against Ollama instead of Azure.
- `FEWS_AGENT_MODEL` is the SINGLE source of the model/deployment name
  (AZURE_OPENAI_DEPLOYMENT was removed — do not reintroduce it).
- LiteLLM: `litellm.drop_params = True` (set in litellm_provider.py) is what
  makes gpt-5.x accept our calls (it rejects temperature≠1). Removing it
  silently breaks EVERY llm call into fallbacks.
- Windows console is cp1252: no emoji in engine strings (the sidebar's ⚪🟢
  live only in web_app.py). Set utf-8 wrapper in scripts that print replies.
- Streamlit does NOT reload deep modules — after engine changes, fully
  Ctrl+C and restart the app; "Rerun" is not enough.
- Prompts live as .txt under `fews_agent/agent/prompts/` (gitignore negation
  exists). Loader uses `[[ ]]` delimiters, StrictUndefined — a missing
  template var fails loudly at load.
- The agent (Claude) must NEVER run git write commands — draft commit
  messages; the user runs them.
- `projects/` fixtures are gitignored — tests are the durable oracle.
- Regression oracles for the GENERATION half (must stay intact):
  tutorial build 120 files / 118 byte-equal; small build 29 files. See
  CLAUDE.md "Verification checklist".

## 8. Non-goals (do not build these)

No embeddings/RAG (domain fits in the prompt). No multi-round agent loop
(single call is the design; see §6 repair-round for the only sanctioned
extension). No fine-tuning. No forms beyond the existing coordinates modal.
No re-introduction of intent taxonomies, confidence gates, or
module-support refusals on prose paths.
