"""ExternalTablesMirrorUpdate.xml — kicks a full mirror refresh from
the external database into the FEWS blobbed TS mirror (since 2015.01)."""
from __future__ import annotations

from .common import FewsModel


class ExternalTablesMirrorUpdate(FewsModel):
    """Root of ExternalTablesMirrorUpdate.xml.

    importManualEditsTable is required in the XSD (no minOccurs="0"),
    even though the XSD declares a default of "true". We require it in
    Pydantic too so callers state their intent explicitly.
    """

    importManualEditsTable: bool
