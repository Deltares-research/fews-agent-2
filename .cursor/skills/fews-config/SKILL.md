---
name: fews-config
description: >
  Orchestrate Delft-FEWS XML configuration with the fews-check CLI.
  Detects whether the user is starting a new project, adding a
  capability to an existing tree, or diagnosing a failing config.
  Triggers on: "new FEWS project", "create a FEWS config", "add an
  import", "add a workflow", "add a basin model", "validate this
  config", "fix this FEWS folder", "configure Delft-FEWS", "GFS
  import", "HRDPS", "Raven", "Wflow".
---

# FEWS config orchestrator

You coordinate FEWS configuration work. You do **not** decide that a
file is correct — `uv run fews-check` does. You pick the entry point,
load the matching sub-skill, and refuse to skip a gate.

## Critical Rules

1. **Nothing reaches disk unverified.** Draft → validate →
   `uv run fews-check --json admit`. Do not Write XML with the editor.
2. **Prefer a typed intermediate representation.**
   `schema-shape` → fill JSON → `render-spec` → `admit`. Raw XML only
   when no spec fits.
3. **Patterns are examples, not a generator.** Do not call
   `list_patterns`, `create_project`, `apply_slots`, or `build_project`
   as the write path.
4. **Do not invent IDs.** `fews-check id-registry` first when a tree
   exists.
5. **The weld is one unit.** An import is module + workflow + idMap.
   Read `references/the_weld.md` before adding a capability.
6. **Do not dump a menu.** After a gate passes, proceed. Do not ask
   "would you like me to validate?"
7. **Be concise.** State what you are doing, show results, ask only
   when a value is operationally required and unknown.
8. **Confidential configs stay out of the example corpus.** Validate
   them by absolute path.

## Entry point detection

### Start at diagnose (`fews-diagnose`) if

- The user points at an existing folder and wants a check or a fix
- They paste a failing diagnostic / XSD error
- They say "validate", "lint", "what's wrong", "unused files"

### Start at author (`fews-author-file`) if

- They want a new file or a new capability in a tree that already
  exists (or a path they just named)
- They name a source or model (GFS, HRDPS, Raven, …) and want XML

### Start a new project (still `fews-author-file`) if

- No tree exists. Create the destination folder (empty), then author
  the weld one file at a time. Do **not** call `create_project`.

### Ambiguous

Ask once, then proceed:

> I can (1) check an existing config folder, (2) add a file / import /
> workflow to a folder, or (3) start a new config from scratch. Which?

## Generation ladder

Read `references/generation_ladder.md` before drafting.

Gate after each file: `fews-check render-spec` returns `ok` **or**
`validate-xml` returns `ok`. Then `admit`. After a weld (or on
request): `fews-check validate-config`.

## Key references

| Reference | When to read |
|---|---|
| `references/generation_ladder.md` | Before any write |
| `references/the_weld.md` | Adding an import / model / process step |
| `references/file_set_map.md` | New project / "what's missing" |
| `references/id_conventions.md` | Before choosing any id |
| `references/conform_rules.md` | After a conform / gauntlet failure |
| `references/gotchas.md` | Before filling `render-spec` JSON |

## Examples

`examples/minimal_gfs_import/` is a self-generated, gauntlet-checked
workflow. Open-source full configs are listed in `examples/README.md`
and are **placeholders until added**.
