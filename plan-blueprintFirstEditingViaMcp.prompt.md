# Plan: Blueprint-first editing via MCP

## Goal
Make the blueprint (project.yaml) + inputs/ the ONLY editing surface. Generated
XML tree becomes read-only derived output. Edits route through typed
deterministic MCP tools (patch_ops) OR manual yaml edits; every change is
applied by rebuild + validate. Copilot is the single brain (no second LLM on
the editing path). Cascade (e.g. "delete precipitation") is solved by
regeneration, not by editing 50 XML files.

## Key codebase findings (verified)
- `app/mcp_server.py` — MCP shell. Tools today: chat (2nd LLM), create_project,
  get_status, list_projects, build, build_phase, list_imports, list_modules.
  Session I/O via `_load`/`_save`; `write_project(state, dir)` derives
  project.yaml from state.slots; `resolve_patterns(state, catalog)` rebuilds
  patterns from slots.
- `fews_agent/agent/patch_ops.py` — `apply_patch(state, ops, catalog) ->
  PatchResult`. 11 ops: add_import, add_basin, add_capability, set_variables,
  remove, set_focus, open_coordinates, show_variables, build, assemble, none.
  Validates against catalog, drops invalid LOUDLY. Pure, no I/O.
- `fews_agent/validation/xsd.py` `validate_xsd(bytes)->(ok,msg)` — byte-oriented,
  file-agnostic. Only used as build gate today.
- `scripts/check_references.py` `analyze(root: Path) -> {ref_kind:{resolved,
  unresolved}}` — DISK-NATIVE reference walker (parameterId/locationSetId/
  locationId/idMapId/moduleInstanceId), handles idMap by filename + generic
  bodies. Reused by tests/test_conform_reference_projects.py. THIS is the
  standalone semantic tool building block.
- `runners/agent/build_from_blueprint.py` `build_from_blueprint(blueprint_path,
  pattern_root, inputs_dir, console)` reads project.yaml DIRECTLY (not state) →
  manual yaml edits can drive rebuild with no round-trip.
- GAP: no reverse yaml->slots loader. state.slots is source, project.yaml is
  derived. Manual yaml edits won't reflect in typed tools/status without a
  reverse-sync.
- `fews_agent/agent/llm_turn.py` has `catalog_digest` etc. for listing addable
  capabilities.

## Phases

### Phase 1 — Blueprint as the read surface
- Add `get_blueprint(session)` MCP tool: resolve_patterns + write_project to
  refresh project.yaml, return its text + a parsed digest (patterns, slots,
  inputs present, last build/validate status).
- Add `list_capabilities(session)` tool: surface catalog_digest (addable
  imports/basins/capabilities + their required variables). Reuse
  llm_turn.catalog_digest / project_intents.
- (list_imports / list_modules / get_status already exist.)

### Phase 2 — Typed deterministic edit tools (patch_ops as MCP tools)
Wrap each mutating op as its own MCP tool so Copilot drives them (no 2nd LLM):
- `add_import(session, name, data_types?)`
- `add_basin(session, name, adapter)`
- `add_capability(session, name, variables?)`
- `set_variables(session, target, variables)`
- `remove_item(session, name)`
Each: _load state -> apply_patch(state, [op], catalog) -> resolve_patterns ->
write_project -> _save -> return {applied notes, dropped (loud), patterns,
blueprint_path}. Shared helper `_apply_ops(project_dir, ops)`.

### Phase 3 — reverse-sync (yaml -> slots) so manual + tool edits converge
- Add `reload_blueprint(session)` tool + internal `_sync_blueprint_to_state`:
  parse project.yaml back into state.slots (inverse of write_project). Call it
  automatically when project.yaml mtime > .chat_state.json mtime (detect manual
  edits) at the top of get_status/get_blueprint/typed tools.
- This is the only genuinely new logic. Keep it small: map blueprint patterns +
  singleton_seeds back to the slots write_project consumes.

### Phase 4 — Standalone validate tool
- Add `validate(session)` MCP tool: iterate generated tree, `validate_xsd` per
  *.xml (collect pass/fail + messages); run `scripts.check_references.analyze`
  for cross-refs; return {xsd: per-file, references: unresolved-by-kind,
  ok: bool}. NO rebuild — validates whatever is on disk (covers manual edits).
- Optionally fold the analyze() report into build's summary too.

### Phase 5 — Generated tree = derived/read-only + drift detection
- On build, write a manifest (relpath->sha256) to
  project_dir/.generated_manifest.json.
- `build` (and a new `check_drift`) compares current generated files to the
  manifest; if any differ -> warn "generated tree was hand-edited; rebuild will
  overwrite. Edit the blueprint instead."
- Drop a `generated/_README_DERIVED.txt` marker on build.
- Update FastMCP `instructions` to state the discipline: edit blueprint +
  inputs/, never the generated tree; rebuild to apply; validate to check.

### Phase 6 — De-emphasize 2nd LLM + tests/docs
- Keep `chat` tool but re-document as FALLBACK for non-LLM clients; primary path
  = typed tools + Copilot. No removal.
- Tests (deterministic, no LLM): get_blueprint refresh; each typed tool
  applied/dropped; reload_blueprint round-trip (write_project -> edit -> sync ==
  original slots); validate over a known built tree (reuse a projects/ fixture
  or build small in-test); drift detection flips on a hand edit.
- Reuse tests/test_patch_ops.py style + build fixtures.

## Relevant files
- `app/mcp_server.py` — add the new tools + `_apply_ops` + `_sync_blueprint_to_state`
  + drift manifest helpers; update FastMCP instructions.
- `fews_agent/agent/patch_ops.py` — reuse apply_patch as-is (no change expected).
- `fews_agent/agent/project_chat.py` — `write_project`; add inverse
  `load_blueprint_into_state` here (co-located with write_project).
- `fews_agent/validation/xsd.py` — reuse validate_xsd.
- `scripts/check_references.py` — reuse analyze() for the validate tool.
- `runners/agent/build_from_blueprint.py` — reuse; optionally add analyze() to
  the summary.
- `tests/` — new test_mcp_blueprint_tools.py (+ reuse test_patch_ops style).

## Verification
1. `python -m pytest tests/ -q` — existing suite still green; new MCP tool tests
   pass.
2. Regression oracles unchanged: tutorial build 120 files 120/120 XSD; small
   29 files 28/28.
3. Manual MCP loop in VS Code: create_project -> add_import(GFS) ->
   get_blueprint shows GFS -> hand-edit project.yaml (add temperature) ->
   reload_blueprint reflects it -> build -> validate returns xsd ok + refs
   resolved -> hand-edit a generated XML -> build warns drift.
4. reload_blueprint round-trip test: slots -> write_project -> load == slots.

## Decisions / further considerations
1. Source of truth: slots vs project.yaml.
   - Rec: project.yaml is the canonical editable source; slots become a cache
     kept in sync via mtime-triggered reverse-sync (Option A). Alt B: slots
     canonical, manual yaml edits overwritten on next tool call (simpler, less
     friendly). Alt C: dual with explicit reconcile command only.
2. Keep the `chat` tool? Rec: KEEP as fallback for non-LLM MCP clients; not the
   primary editing path.
3. inputs/ (CSVs, policy yamls) editing surface. Rec: out of scope for v1 beyond
   listing them in get_blueprint; add an inputs-validate later.
4. Cascade graph (idMap-anchored impact report) is NOT needed if blueprint-only
   editing is enforced; it becomes optional insurance if hand-edits are allowed.
   Excluded from this plan.
