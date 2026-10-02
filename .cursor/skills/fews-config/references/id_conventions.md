# ID conventions

Copy IDs. Do not invent them.

**Before drafting into an existing tree:** call
`uv run fews-check --json id-registry PATH`.
Reuse `parameterId`, `moduleInstanceId`, `idMapId`, `locationId`,
`locationSetId` from `declared`. Unresolved refs are the ones you must
fix, not new names you get to pick.

**Filename declares the id** for IdMap, Workflow, and ModuleInstance:
the file stem *is* the id. `IdImportGFS.xml` declares `IdImportGFS`.
`ImportGFS.xml` declares `ImportGFS`. Linux filesystems are
case-sensitive — `IdImportGlobSnow` ≠ `IdImportGLOBSNOW`.

**parameterId** looks like `quantity[.source]`: `PC.nwp`, `TA.obs`,
`Q.sim`. See `conform.param_suffix`.

**Placeholders** (`$MODELNAME1$`, `$REGION$`, `$DAY_TIMESTEP$`) stay
literal in XML. They resolve at FEWS startup from
`sa_global.Properties`. Do not substitute them at author time.

**Generic-body files** are invisible to the semantic walker. If
`fews-check id-registry` says no typed models loaded, do not treat an empty
`declared` set as permission to invent IDs — look at the XML.
