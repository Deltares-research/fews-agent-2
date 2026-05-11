# Yaml starters — copy-paste templates for `inputs/`

These 7 yaml files cover FEWS configuration that the chat agent and `/edit`
mode aren't the right tool for. They're tutorial-derived starters — drop
the relevant ones into your project's `inputs/` directory and tweak.

## When to copy each

### UI configs (4 files) — encode "what the operator sees"

These are aesthetic/layout policy. Better authored in a visual editor or
copied from a similar project than typed through chat prompts. Tutorial
versions are reasonable defaults.

- `explorerFile.yaml` → `Explorer.xml` (FEWS GUI shell: tabs, menus, toolbar)
- `productsFile.yaml` → `Products.xml` (output deliverables: PDF reports, exports)
- `spatialDisplayFile.yaml` → `SpatialDisplay.xml` (map view layers + colour scales)
- `timeSeriesDisplayConfig.yaml` → `TimeSeriesDisplayConfig.xml` (plot defaults)

### Module-config templates (3 files) — operational capabilities

These aren't really configurator *choices* — they're standard FEWS
capabilities a project either has or doesn't. Drop in the ones you need.

- `calculateEnsembleStatisticsTemplate.yaml` — ensemble forecast → percentiles/mean/min-max
- `setForecastLengthTemplate.yaml` — dynamic forecast horizon based on data availability
- `updateModelPackage.yaml` — maintenance task for refreshing model executables

(These would be cleaner as patterns in `patterns/auto/...`; treat the
starters as a stopgap until pattern coverage exists.)

## How to use

```bash
# Copy the ones you want into your project's inputs/
cp templates/yaml-starters/explorerFile.yaml \
   projects/<your-project>/<your-project>_<datetime>/inputs/

# Tweak as needed (search for $MODELNAME1$ etc. — those are FEWS runtime
# placeholders resolved from RootConfigFiles/sa_global.Properties)

# Rebuild
python -m runners.agent.build_from_blueprint \
    --blueprint projects/<your-project>/<your-project>_<datetime>/project.yaml
```

## Why not `/edit` for these?

The chat agent's `/edit` mode handles 13 yaml types where the schema is
shallow enough that a typed elicitation flow is faster than copy-paste.
For these 7, the schemas are either passthrough body dicts (Explorer,
Products, SpatialDisplay) or massive nested configs (TimeSeriesDisplayConfig)
where prompt-driven authoring would be tedious and unrewarding. See
`CLAUDE.md` for the full categorisation.
