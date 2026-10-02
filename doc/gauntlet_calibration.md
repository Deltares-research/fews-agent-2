# Gauntlet calibration

Baseline for mining conform rules. Tier 4 is skip (`fews.unavailable`)
unless `FEWS_CHECK_CMD` is set — that skip **is** the recorded baseline.
Do not invent a confusion matrix from guessed FEWS output.

`examples/config-tutorial` is not present on this clone. Re-run:

```
python -m runners.agent.calibrate_gauntlet --config examples/config-tutorial --out doc/gauntlet_calibration.md
```

---

# Mini fixture — `tests/gauntlet_fixtures.write_mini_config`

files_checked: 4
ok (no errors): False
tiers: xsd, semantic, conform, fews_check

| tier | severity | count |
| --- | --- | ---: |
| xsd | warning | 1 |
| xsd | error | 1 |
| semantic | error | 2 |
| conform | warning | 2 |
| conform | convention | 2 |
| fews_check | skip | 1 |

## First diagnostics

- `load.schema` [warning] `RegionConfigFiles/Filters.xml`: typed parse as Filters failed (root `@id` is not on the Filters model).
- `xsd.schema` [error] `RegionConfigFiles/Filters.xml`: Filters XSD rejects the extra root `@id`.
- `semantic.unresolved` [error] `ModuleConfigFiles/Import/ImportGLOBSNOW.xml`: `IdImportGlobSnow` (`IdMapId`) is referenced but not declared (case-only vs `IdImportGLOBSNOW`).
- `semantic.unresolved` [error] `ModuleConfigFiles/Import/ImportGLOBSNOW.xml`: `GLOBSNOW` (`LocationId`) is referenced but not declared.
- `conform.csv_attr_pascal` [convention] `locations.csv`: column `wflow_id` is not a PascalCase attributeId.
- `conform.idmap_casing` [warning] `ModuleConfigFiles/Import/ImportGLOBSNOW.xml`: `idMapId` `IdImportGlobSnow` vs stem `IdImportGLOBSNOW`.
- `conform.filename_id_agreement` [warning] `RegionConfigFiles/Filters.xml`: root id `AllData` vs stem `Filters`.
- `conform.param_suffix` [convention] `RegionConfigFiles/Parameters.xml`: parameterId `not a valid id`.
- `fews.unavailable` [skip]: `FEWS_CHECK_CMD` unset.

What XSD + semantic already catch (casing / missing location) the conform
rules also name, so a host LLM can repair from `rule_id` without guessing.
Tier 4 has no FEWS oracle on this machine.
