"""OvertoppingModule.xml — seawall overtopping rate calculator."""
from __future__ import annotations

from typing import Literal

from pydantic import Field

from .common import FewsModel


class OvertoppingGeneral(FewsModel):
    inputDir: str
    outputDir: str
    diagnosticFile: str
    lookupDataSetDir: str | None = None
    debugLevel: int | None = None


class OvertoppingFile(FewsModel):
    filename: str
    fileType: Literal[
        "timeseries", "supportSite", "lookup", "twodimlookupmatrix", "sectiondetails"
    ]
    mappingId: str
    coefficientId: str | None = None
    outputvariableId: str | None = None


class OvertoppingFileDataMapping(FewsModel):
    # The XSD constrains `variable` to a ~30-value enum of
    # Overtopping-specific tokens. We pass through as str; the XSD
    # validates.
    variable: str
    column: int = Field(gt=0)
    dataType: str | None = None
    ordering: Literal["ascending", "descending"] | None = None
    columnHeader: str | None = None


class OvertoppingFileDataMappings(FewsModel):
    id: str
    mapping: list[OvertoppingFileDataMapping] = Field(min_length=1)


class OvertoppingDataCoefficient(FewsModel):
    variable: str
    value: str | None = None
    dataType: str | None = None


class OvertoppingDataCoefficientMappings(FewsModel):
    id: str
    coefficient: list[OvertoppingDataCoefficient] = Field(min_length=1)


class OvertoppingModule(FewsModel):
    """Root of OvertoppingModule.xml."""

    general: OvertoppingGeneral
    # Only one method enumerated today but XSD-declared — pass through
    # as str for forward compat.
    overtoppingMethod: str
    input: list[OvertoppingFile] = Field(min_length=1)
    output: list[OvertoppingFile] = Field(min_length=1)
    mappings: list[OvertoppingFileDataMappings] = Field(min_length=1)
    coefficients: list[OvertoppingDataCoefficientMappings] = Field(default_factory=list)
    version: str = "1.1"
