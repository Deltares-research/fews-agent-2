"""Auto-derive descriptor singletons from rendered XML.

Phase 1 of input-yaml auto-generation. Scans the project's rendered
XML files for moduleInstanceIds and workflowIds, then generates the
matching descriptor singletons (ModuleInstanceDescriptors,
WorkflowDescriptors) if the configurator hasn't provided them.

Why post-build derivation: the descriptor lists are pure aggregations
of IDs that already appear elsewhere in the project. The configurator
shouldn't have to re-list every module instance — it's mechanical work
the runner can do for them.

Tradeoff: auto-derived descriptions are generic ("Auto: ImportHRDPS"),
not the human-written ones. Configurator can override by providing
their own ``moduleInstanceDescriptors.yaml`` in inputs/.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import TYPE_CHECKING

from lxml import etree

if TYPE_CHECKING:
    from .blueprint import RenderedFile


# Placeholder IDs that should be excluded from descriptor lists. These
# are FEWS runtime placeholders (e.g. $MODELNAME1$Historic) which won't
# resolve to real module instances at descriptor-write time.
_PLACEHOLDER_PATTERN = re.compile(r"\$[A-Z0-9_]+\$")


def _is_placeholder(value: str) -> bool:
    return bool(_PLACEHOLDER_PATTERN.search(value or ""))


def extract_module_instance_ids(
    rendered_files: list["RenderedFile"],
) -> set[str]:
    """Walk every rendered XML; collect every <moduleInstanceId>X</...> value.

    Filters out FEWS runtime placeholders (e.g. ``$MODELNAME1$Historic``)
    since they aren't real module instances at config-write time.
    """
    ids: set[str] = set()
    for rf in rendered_files:
        try:
            tree = etree.fromstring(rf.content.encode("utf-8"))
        except etree.XMLSyntaxError:
            continue
        for el in tree.iter("{*}moduleInstanceId"):
            text = (el.text or "").strip()
            if text and not _is_placeholder(text):
                ids.add(text)
    return ids


def extract_workflow_ids(
    rendered_files: list["RenderedFile"],
) -> set[str]:
    """Workflow IDs come from workflow filenames (the file's stem)."""
    ids: set[str] = set()
    for rf in rendered_files:
        if "WorkflowFiles" not in rf.relpath:
            continue
        stem = Path(rf.relpath).stem
        if stem and not _is_placeholder(stem):
            ids.add(stem)
    return ids


def has_output_at(
    rendered_files: list["RenderedFile"], output_relpath: str,
) -> bool:
    """Check whether a singleton was already produced (by yaml or merger)."""
    target = output_relpath.replace("\\", "/")
    return any(rf.relpath.replace("\\", "/") == target for rf in rendered_files)


def derive_descriptor_singletons(
    rendered_files: list["RenderedFile"],
) -> list["RenderedFile"]:
    """Return new RenderedFile entries for any descriptor singletons not
    already produced.

    Only generates files that are MISSING — never overwrites an
    existing output (whether from a yaml in inputs/ or from the
    contribution merger).
    """
    from .blueprint import RenderedFile  # late import to avoid cycle
    from fews_agent.generators import SPECS
    from fews_agent.generators.base import render as render_template
    from fews_agent.schema import (
        ModuleInstanceDescriptor,
        ModuleInstanceDescriptors,
        WorkflowDescriptor,
        WorkflowDescriptors,
    )

    new_files: list["RenderedFile"] = []
    spec_by_class = {s.model_class.__name__: s for s in SPECS}

    # Module instance descriptors.
    mid_spec = spec_by_class.get("ModuleInstanceDescriptors")
    if mid_spec and not has_output_at(
        rendered_files, str(mid_spec.output_relpath).replace("\\", "/")
    ):
        ids = extract_module_instance_ids(rendered_files)
        if ids:
            try:
                model = ModuleInstanceDescriptors(
                    moduleInstanceDescriptor=[
                        ModuleInstanceDescriptor(
                            id=mid, description=f"Auto: {mid}",
                        )
                        for mid in sorted(ids)
                    ]
                )
                xml = render_template(mid_spec.template_name, model)
                new_files.append(RenderedFile(
                    relpath=str(mid_spec.output_relpath).replace("\\", "/"),
                    content=xml,
                    pattern="(auto-descriptor)",
                    instance_label="ModuleInstanceDescriptors",
                ))
            except Exception:
                pass  # silently skip if Pydantic rejects (e.g. id format)

    # Workflow descriptors.
    wf_spec = spec_by_class.get("WorkflowDescriptors")
    if wf_spec and not has_output_at(
        rendered_files, str(wf_spec.output_relpath).replace("\\", "/")
    ):
        ids = extract_workflow_ids(rendered_files)
        if ids:
            try:
                model = WorkflowDescriptors(
                    workflowDescriptor=[
                        WorkflowDescriptor(
                            id=wid, name=wid,
                            description=f"Auto: {wid}",
                        )
                        for wid in sorted(ids)
                    ]
                )
                xml = render_template(wf_spec.template_name, model)
                new_files.append(RenderedFile(
                    relpath=str(wf_spec.output_relpath).replace("\\", "/"),
                    content=xml,
                    pattern="(auto-descriptor)",
                    instance_label="WorkflowDescriptors",
                ))
            except Exception:
                pass

    return new_files


__all__ = [
    "derive_descriptor_singletons",
    "extract_module_instance_ids",
    "extract_workflow_ids",
    "has_output_at",
]
