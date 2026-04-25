"""ModuleRunTableDisplay.xml — declarative trigger (empty root) for the
module-run table UI. The XSD root has an empty sequence; the file is
just a namespaced placeholder."""
from __future__ import annotations

from .common import FewsModel


class ModuleRunTableDisplay(FewsModel):
    """Root of ModuleRunTableDisplay.xml. No fields — emits `<moduleRunTableDisplay/>`."""
