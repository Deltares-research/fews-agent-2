"""RdbmsExport.xml — legacy RDBMS time-series export config.

Marked ``LEGACY, NO LONGER USED``. Exports time series to an external
database via JDBC: driver/connection + credentials + export window +
optional moduleInstance/filter scopes.

XSD choice: exactly one of ``password`` / ``encryptedPassword``.
"""
from __future__ import annotations

from pydantic import Field, model_validator

from .common import FewsModel, RelativePeriod


class RdbmsExportFilter(FewsModel):
    filterID: str


class RdbmsExportModuleInstance(FewsModel):
    moduleInstanceID: str


class RdbmsExport(FewsModel):
    jdbcDriverClass: str
    jdbcConnectionString: str
    user: str
    exportTimeWindow: RelativePeriod
    exportTimeZone: str
    password: str | None = None
    encryptedPassword: str | None = None
    moduleInstance: list[RdbmsExportModuleInstance] = Field(default_factory=list)
    filter: list[RdbmsExportFilter] = Field(default_factory=list)

    @model_validator(mode="after")
    def _one_password(self) -> RdbmsExport:
        has_pw = self.password is not None
        has_enc = self.encryptedPassword is not None
        if has_pw == has_enc:
            raise ValueError(
                "rdbmsExport: supply exactly one of password / encryptedPassword"
            )
        return self
