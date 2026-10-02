---
name: fews-diagnose
description: >
  Diagnose and repair an existing Delft-FEWS config folder or a pasted
  XML snippet. Runs fews-check, explains rule ids, repairs, and
  re-validates. Triggers on: "validate this config", "check this
  folder", "what's wrong with this XML", "XSD error", "unresolved
  moduleInstanceId", "conform lint", "fix IdImportGlobSnow".
---

# Diagnose a FEWS config

Repair loop only. Do not add new capabilities here — hand off to
`fews-author-file` if the user wants a new file. Call
`uv run fews-check --json <command>`. Do not Write XML with the
editor.

## Critical Rules

1. **Do not call `list_patterns`.** This is a brownfield check.
2. **Folder vs snippet.** A directory on disk →
   `fews-check open-config` (once; ledger only) → `validate-config`.
   Pasted XML → `fews-check validate-xml --xml …` (no cross-file IDs).
3. **Naming only** when the user asked only for house naming:
   `conform-lint` / `conform-lint-xml`. Otherwise prefer
   `validate-config`.
4. **Repair from `rule_id`.** `fews-check explain RULE_ID` → apply
   `fix_hint` → re-validate the **same** surface. Do not `admit`
   until `ok`.
5. **IDs.** `fews-check id-registry` when unresolved refs matter.
   Copy, do not invent.
6. **Tier 4 may skip.** `fews.unavailable` means FewsCLI is not
   configured. That is not a failure. Do not invent a FEWS install.
7. **Be concise.** Report errors first, then warnings. Do not
   re-recite the whole file.

## Loop

```
uv run fews-check --json open-config PATH          (folder, once)
    → fews-check validate-config PATH
    → or: fews-check validate-xml --xml snippet.xml --spec SPEC
    → if errors: fews-check explain RULE_ID → repair → re-validate
    → fews-check admit PATH … only after the snippet/file passes
    → validate-config again if you wrote anything
```

**Gate:** `validate-config` / `validate-xml` reports no errors you
were asked to fix. Warnings may remain — say so, do not silently
"fix" tutorial fixtures.

## Key references

| Reference | When to read |
|---|---|
| `references/conform_rules.md` | Any diagnostic |
| `references/id_conventions.md` | Unresolved IDs |
| `references/gotchas.md` | Repair that touches templates / aliases |
| `references/file_set_map.md` | "what's missing from this region" |
| `references/the_weld.md` | A dangling moduleInstanceId after an add |
| `references/generation_ladder.md` | If the repair is a rewrite |
