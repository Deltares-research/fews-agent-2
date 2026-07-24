# ADR: Blueprint-first editing via MCP

Status: Accepted — 2026-07-24
Scope: `app/mcp_server.py`, `fews_agent/agent/project_chat.py`

## Context

The FEWS config agent turns a fuzzy request into ~50–135 interrelated
Delft-FEWS XML files. The pipeline is deterministic once intent is fixed:
`slots` → `resolve_patterns` → `project.yaml` (the *blueprint*) →
`build_from_blueprint` → rendered XML, gated by XSD + cross-reference checks.

The MCP server is the fourth driver shell (alongside CLI, Streamlit, HTTP).
Its original `chat` tool embedded a *second* LLM (`run_llm_turn`) inside each
call — so an MCP client that already has a capable model (VS Code Copilot,
Claude Desktop) paid for two models, and the editing surface was free-text
prose interpreted by the inner model rather than the structured blueprint.

Two facts drove this decision:

1. **The blueprint is the only sound editing surface.** Editing rendered XML
   directly is unsafe: a single change (e.g. deleting a precipitation import)
   cascades through idMaps, workflows, filters, and display groups. The
   blueprint is the one place where an edit re-derives the whole tree
   consistently. `build_from_blueprint` already reads `project.yaml` directly
   from disk, so a hand edit to the blueprint drives a correct rebuild without
   any round-trip through agent state.
2. **The calling model is the reasoning engine.** With a capable MCP client,
   the inner LLM is redundant. What the client needs are *deterministic,
   validated* tools, not another conversational black box.

## Decision

Make the blueprint (`project.yaml`) the single editing surface exposed over
MCP, and remove the embedded-LLM fallback.

1. **Typed, deterministic edit tools** over the existing `patch_ops` vocabulary:
   `add_import`, `add_basin`, `add_capability`, `set_variables`, `remove_item`.
   Each validates against the pattern catalog and drops invalid requests
   *loudly* (unknown import, unknown model adapter — the "Rhine rule" — bad
   variable). All route through one shared path, `_apply_ops`:
   load → auto-sync → `apply_patch` → re-derive intent from slots →
   `resolve_patterns` → `write_project` → save.
2. **Read tools**: `get_blueprint` (on-disk `project.yaml` text + a structured
   digest) and `list_capabilities` (catalog digest + import sources).
3. **Reverse-sync** (`load_blueprint_into_state`, the inverse of
   `write_project`): a hand-edited `project.yaml` is reconstructed back into
   slots so typed tools and status stay coherent. It is applied automatically
   when `project.yaml` is newer than the saved state (mtime check in
   `_maybe_sync_blueprint`), or on demand via `reload_blueprint`.
4. **Standalone validation**: `validate` runs XSD + cross-reference (`analyze`)
   over whatever is on disk — so it also catches hand edits to generated files.
5. **Drift detection**: `build` writes a `.generated_manifest.json` (relpath →
   sha256); `check_drift` reports whether the derived tree was hand-edited
   since the last build. A `_README_DERIVED.txt` marker warns in-tree.
6. **Removed the `chat` tool** and its inner LLM (`run_llm_turn`,
   `get_provider_or_ollama`). The FastMCP `instructions` now state the
   blueprint-first discipline: edit `project.yaml` / `inputs/`, never the
   generated tree; rebuild to apply; validate to check.

## Consequences

**Positive**

- One editing surface; edits are deterministic and catalog-validated.
- No second model — lower cost/latency, no divergent reasoning.
- Hand edits to `project.yaml` are first-class (build reads it directly;
  reverse-sync keeps tools coherent).
- Generated-tree tampering is detectable (drift) and always re-checkable
  (validate), independent of a rebuild.

**Negative / trade-offs**

- **Slots are canonical for *tool* edits.** Reverse-sync reconstructs
  everything the tools emit (imports, basins, overrides, feature flags) and
  preserves unrecognised hand-authored patterns via `extra_patterns`. But a
  hand edit expressible only as raw pattern internals may be normalised on the
  next typed-tool edit (which re-derives yaml from slots). Accepted for v1:
  `project.yaml` is canonical for *build*; slots are canonical for *tool edits*.
- Clients without their own LLM lose the conversational path. Acceptable —
  the target clients (Copilot, Claude Desktop) supply the model.

## Alternatives considered

- **Keep the embedded `chat` LLM.** Rejected: redundant model, free-text
  surface, double cost.
- **Let the model edit generated XML directly.** Rejected: unsafe cascades
  across dozens of coupled files; no single consistent re-derivation point.
- **Full bidirectional slot⇄yaml equivalence.** Rejected for v1: overkill —
  build already reads yaml directly, so exact invertibility isn't required for
  correctness, only for tool/status coherence, which reverse-sync provides.

## Validation

- New deterministic (LLM-free) suite `tests/test_mcp_blueprint_tools.py`
  (13 tests): typed-edit apply/drop, blueprint round-trip
  (`write_project` → edit → `load_blueprint_into_state`), auto mtime sync,
  manifest/drift flip on hand edit, and validate over a tree.
- `project_chat.py` and `mcp_server.py` import cleanly with no diagnostics.
