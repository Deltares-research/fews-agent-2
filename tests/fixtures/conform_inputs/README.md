# Conform-convention CSV inputs

A minimal, complete set of configurator CSV inputs authored to the
[FEWS-Conform](https://github.com/Deltares/FEWS-Conform) conventions, and
verified by `tests/test_conform_inputs_fixture.py` to flow cleanly through
the agent's CSV ingest, the header linter, and the csvFile-LocationSet
build path.

Copy these into any project's `inputs/` directory as a starting point.

## Conventions applied

- **PascalCase headers, no spaces / `_` / `-`** — every column header is a
  valid FEWS `attributeId` (Conform: *the column header is the attributeId*).
- **`FewsId` as the id column**, `Lat`/`Lon`/`Alt` for coordinates,
  `Datum` per row (lifted to the LocationSet `geoDatum`).
- **Rich attribute columns** on locations (`Type`, `ModelId`,
  `WflowIdDischarge`, `WflowIdWaterLevel`) — preserved as location
  `<attribute>`s when built with `metadata.locations_as_csvfile: true`
  (they are dropped by plain `Locations.xml` ingest by design).
- **Full `Parameters` column set** (`DisplayUnit`, `UsesDatum`,
  `AllowMissing`, `ValueResolution`, …) rather than the 6-column minimum.

## Files

| File | Drives |
|---|---|
| `locations.csv` | `LocationSets.xml` csvFile set (with attributes) / `Locations.xml` |
| `parameters.csv` | `Parameters.xml` |
| `qualifiers.csv` | `Qualifiers.xml` |
| `thresholdWarningLevels.csv` | `ThresholdWarningLevels.xml` |

## Recommended blueprint metadata

```yaml
metadata:
  locations_as_csvfile: true   # reference locations.csv in place; keep attributes
  # location_set_id: Stations  # optional; auto-matches an interpolation set if present
```
