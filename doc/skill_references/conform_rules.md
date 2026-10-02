# Conform rules

House naming. Reported, never auto-fixed on the generation path.
Call `uv run fews-check --json explain RULE_ID` for the fix hint,
then repair, then re-validate.

| rule_id | severity | meaning |
|---|---|---|
| `conform.csv_attr_pascal` | convention | CSV attributeIds are PascalCase (`WflowId`, not `wflow_id`) |
| `conform.idmap_casing` | warning | `<idMapId>` must match the IdMap filename stem (Linux-safe) |
| `conform.filename_id_agreement` | warning | root `@id` must match the file stem |
| `conform.param_suffix` | convention | `PC.nwp` / `TA.obs` / `Q.sim` |

Prefer `fews-check validate-config` over `conform-lint` unless the
user asked only for house naming.

Gauntlet rule ids you will also see:

| rule_id | meaning |
|---|---|
| `xsd.schema` | element order / required children (xsd:sequence) |
| `semantic.unresolved` | a referenced id is not declared in the tree |
| `fews.unavailable` | `FEWS_CHECK_CMD` unset — skip, not a fail |
| `fews.config` | FewsCLI `VALIDATE_CONFIG_FILES` rejected the tree |
| `fews.exit` | FewsCLI exited non-zero; read `evidence` |
| `fews.failed` | checker did not run (OS / timeout / empty zip) |
