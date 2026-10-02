# Gotchas (mined from failures)

Every item here was a real bug. Treat them as Critical Rules.

- **`extra="forbid"`.** Fields the Pydantic schema does not model are
  rejected, not ignored. Drop unknown keys; do not invent elements.
- **Jinja dict-method collisions.** Fields named `items`, `keys`, or
  `values` need bracket lookup (`obj["items"]`) in templates, not
  `obj.items`.
- **Pydantic aliases do not reach the template.** `model_dump()` emits
  the field name. Templates use `import_`, `validate_`, not the XML
  alias `import`. When filling JSON for `fews-check render-spec`, either key
  usually works (`populate_by_name`); prefer the Python field name.
- **Typed vs generic-body `timeStep`.** Inside a typed schema use
  `unit` / `multiplier`. A generic-body dict needs `@unit` / `@value`.
- **`xsd:sequence` — element order matters.** `fews-check render-spec`
  owns order. If you fall back to raw XML, match the XSD fragment from
  `fews-check schema-shape`, not a remembered wiki order.
- **Bare `python` / `pytest`.** This repo is uv-managed. Run
  `uv run pytest` / `uv run python` / `uv run fews-check`. Bare
  `python -m pytest` uses the wrong interpreter on a fresh machine.
- **Do not Write XML.** The editor is not the write gate. Render and
  admit only via `uv run fews-check --json`.
- **Do not invent IDs.** Copy from `fews-check id-registry`. Casing
  mismatches pass on Windows and break on Linux FEWS.
- **Placeholders stay literal.** `$MODELNAME1$` is FEWS-owned.
- **Confidential configs are never examples.** `fews-check find-examples`
  ships snippets to the host model. Private trees are gauntlet
  *targets* (`fews-check validate-config PATH`), never corpus entries.
- **A well-formed file can still be operationally wrong.** Wrong
  timestep, wrong URL, missing weld sibling — XSD will pass. After a
  weld, run `fews-check validate-config`. FewsCLI (tier 4) is the only remaining
  oracle; it is skip until `FEWS_CHECK_CMD` is set.
