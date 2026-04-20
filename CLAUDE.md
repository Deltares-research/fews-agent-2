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
templates/           Jinja2 templates, one per FEWS file type
  partials/          Shared macros (timeSeriesSet, locationSet, period, ...)
generators/          Python functions: params dict -> rendered XML
  base.py            Shared rendering + validation helpers
  <file_type>.py     One module per FEWS file type
schemas/             FEWS XSDs, pinned to a specific FEWS version
validation/
  xsd.py             XSD validation via lxml
  semantic.py        Cross-file reference checks
base_config/         Near-static files copied verbatim or patched
agent/               LLM orchestration, parameter elicitation, tool defs
tests/
  fixtures/          Real FEWS configs used as regression oracles
  test_<type>.py     Per-generator tests
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

## Notes for Claude Code specifically

- When asked to add a generator, read the XSD first, then one or two
  example files, then write the template and generator together with tests
  in the same change.
- When asked to "just generate some XML," push back and ask whether a
  template should exist for this file type instead.
- Prefer small, composable partials over large monolithic templates.
- If a change would require loosening validation to pass, stop and flag it
  rather than loosening validation.
