# File-set map (what a loadable config must contain)

A Delft-FEWS Stand-Alone region needs more than one import XML.

**Always present in a loadable region**

- `RootConfigFiles/` — client config; `sa_global.Properties` holds
  `$PLACEHOLDER$` values (`TIMEZONE`, `REGION`, `MODELNAME1`, …)
- `RegionConfigFiles/Locations.xml` (or a csvFile LocationSet)
- `RegionConfigFiles/Parameters.xml`
- `RegionConfigFiles/LocationSets.xml`
- `RegionConfigFiles/Filters.xml` (or a split `Filters<Basin>.xml`)
- `SystemConfigFiles/TimeSteps.xml`
- descriptors: `ModuleInstanceDescriptors.xml`,
  `WorkflowDescriptors.xml`

**Per capability (the weld)**

- `ModuleConfigFiles/` + matching `WorkflowFiles/`
- `IdMapFiles/` when the import/export remaps IDs

**Delivery vs generation layout**

The generation tree keeps tutorial names (`WorkflowFiles/`,
`sa_global.Properties`). A FEWS-loadable zip remaps
`WorkflowFiles/` → `Config/Workflows/` and puts lowercase
`sa_global.properties` at the region root. FewsCLI `regionpath=` wants
a zip of the Config dir. Do not rewrite the generation tree to match
delivery; the remap is delivery-time only.

**Inputs the user must supply** (gauntlet cannot invent these)

- station list (`locations.csv`) if interpolating or showing points
- parameter definitions if not using bundled defaults
- map extent / timezone / region name
- download folder or URL for an import
