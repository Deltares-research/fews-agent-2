"""ReAct tool-calling agent — the parallel prototype.

The LLM plans freely and calls tools; the deterministic writer
(Pydantic + Jinja + XSD, `fews_agent/generators`) is the ONLY way XML
is produced. No patterns, no slots, no intent pipeline — this package
must never import `fews_agent.patterns`, the elicitation half
(`turn_engine`, `project_intents`, `extractor`, `llm_turn`), or `app/`.

Pieces:
  - `context.ToolContext`   — per-session workspace the tools operate on
  - `registry.ToolRegistry` — name -> (ToolSpec, handler) dispatch
  - `loop.run_react`        — the provider-agnostic ReAct loop
  - `tools/`                — the tool handlers (writer, standards, CSV,
                              derivers, validation, web lookups)

Entry point: ``python -m runners.react.run_react``.
"""
