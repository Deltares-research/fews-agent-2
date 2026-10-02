---
name: fews-author-file
description: >
  Author one Delft-FEWS XML file (or one capability weld) via a typed
  intermediate representation. Phase 1 elicits required values; Phase 2
  calls fews-check schema-shape, render-spec, and admit. Triggers on:
  "add a workflow", "draft an import", "write IdMap", "add GFS",
  "create TimeSeriesImportRun", "author a FEWS file", "add a module
  config".
---

# Author a FEWS file

Two phases. Complete Phase 1 before Phase 2. `uv run fews-check`
owns truth. Do not Write XML with the editor.

## Critical Rules

1. **Phase 1 is conversation only.** Do not call `fews-check admit`
   in Phase 1.
2. **Phase 2 requires no user interaction** unless `render-spec`
   returns `validation_errors` you cannot repair from `schema-shape`.
3. **Typed first.** `schema-shape` → JSON → `render-spec`. Raw XML
   only when no spec fits. Read `references/generation_ladder.md`.
4. **Copy IDs.** If a tree exists, `fews-check id-registry` before
   choosing any `parameterId` / `moduleInstanceId` / `idMapId`.
5. **The weld.** Adding an import means module + workflow + idMap.
   Read `references/the_weld.md`. Admit each file only after its
   own gate passes.
6. **Do not invent a pattern.**
7. **After the last admit, `fews-check validate-config`** on the
   folder.
8. **Be concise.** One question at a time for unknown operational
   values (timezone, download folder, forecast length, parameter
   list). Schema-optional is not operationally-optional — ask.

## Phase 1 — Elicit

**Objective:** enough values to fill the spec(s) without guessing
operational fields.

**Gate:** you can name `spec`, `relpath`, and a JSON object whose
required fields are known. IDs are copied from `id-registry` or
explicitly chosen by the user.

If a tree exists: `uv run fews-check --json open-config PATH` once
(ledger only), then `id-registry`.

Ask for what the schema and the weld still need. Do not ask for
element order, namespaces, or XSD boilerplate — the template owns
those.

## Phase 2 — Emit

**Objective:** render and admit.

For each file in the weld:

1. `uv run fews-check --json schema-shape SPEC`
2. Fill JSON (Python field names; see `references/gotchas.md`)
3. `uv run fews-check --json render-spec SPEC --data payload.json`
4. If `validation_errors`: repair from `loc`/`msg`. Re-render.
5. If `ok` is false with XSD/conform diagnostics:
   `uv run fews-check --json explain RULE_ID` → repair → re-render.
6. `uv run fews-check --json admit PATH --from-render render.json`
   only when `ok`.

**Gate:** `render-spec` (or `validate-xml`) `ok` for every file, then
folder `validate-config` reports no new errors you introduced.

**Transition:** do not stop to ask "should I validate the folder?".
Validate, report, stop.

## Key references

| Reference | When to read |
|---|---|
| `references/generation_ladder.md` | Start of Phase 2 |
| `references/the_weld.md` | More than one file |
| `references/id_conventions.md` | Before IDs |
| `references/file_set_map.md` | New project |
| `references/conform_rules.md` | Failed gate |
| `references/gotchas.md` | Filling JSON |
