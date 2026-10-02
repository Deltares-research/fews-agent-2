# The weld

One capability is several files. No XSD enforces this.

An import is not one XML. It is at least:

- a module config (`ModuleConfigFiles/Import/.../Import<Name>.xml`)
  whose filename stem is the `moduleInstanceId`
- a workflow (`WorkflowFiles/Import/...`) that runs that
  `moduleInstanceId`
- an idMap (`IdMapFiles/.../IdImport<Name>.xml`) whose stem matches
  every `<idMapId>` the import references

A basin model run welds the same way: module config + workflow +
(usually) an adapter idMap + descriptors that later assembly derives.

When adding a capability, emit the weld as one unit. Admit each file
only after `fews-check render-spec` / `validate-xml` passes. After the
last admit, run `fews-check validate-config` on the folder so dangling
IDs surface.

Do not invent a pattern to "hold" the weld. The skill is the
coordinator; the gauntlet is the check.
