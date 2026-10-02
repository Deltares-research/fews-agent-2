# Generation ladder

Prefer the first rung that applies. Do not skip down.

Coding agents call **`uv run fews-check --json <command>`**. Do not
Write XML with the editor. `--json` is accepted anywhere and is the
default. Payloads (`--data`, `--xml`) are a file path, `-` (stdin),
or inline JSON/XML.

1. **Typed intermediate representation (default).**
   `uv run fews-check --json schema-shape Workflow` for the Pydantic
   class (e.g. `Workflow`, `TimeSeriesImportRun`, `IdMap`). Fill a
   JSON object matching `required` + `enums`. Then
   `uv run fews-check --json render-spec Workflow --data payload.json`.
   Gate: `ok` is true and `validation_errors` is empty. Then
   `uv run fews-check --json admit PATH --from-render render.json`
   (uses `xml` + `suggested_relpath` unless you pass `--relpath`).

2. **Raw XML (fallback).** Only when no SPECS class fits, or
   `render-spec` cannot represent a generic-body file. Then
   `schema-shape` + `find-examples` → draft XML →
   `uv run fews-check --json validate-xml --xml draft.xml --spec SPEC`
   → `uv run fews-check --json admit PATH --relpath REL --xml draft.xml --spec SPEC`.

3. **Pattern as example, not a generator.** `find-examples` already
   searches `fews_agent/patterns`. A slightly-wrong pattern is a bad
   generator (ships wrong XML stamped `origin: pattern`) and a good
   example (you adapt it, then must pass the gauntlet). Do not call
   `list_patterns` / `create_project` / `apply_slots` / `build_project`
   as the write path.

`render-spec` is read-only. The write gate is always `admit`.
If `build_project` is invoked anyway, it must not clobber
`origin: human` or `origin: llm`.
