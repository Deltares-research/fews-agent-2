"""ContentUpdateChecker.xml — polls a file or URL for new content at a
workflow boundary."""
from __future__ import annotations

from pydantic import Field, model_validator

from .common import FewsModel, TimeStep


class ContentUpdateChecker(FewsModel):
    """XSD choice: either file OR (url + optional user/password)."""

    file: str | None = None
    url: str | None = None
    user: str | None = None
    password: str | None = None
    eventCode: str
    messagePrefix: str
    interval: TimeStep | None = None
    timeout: TimeStep | None = None
    stopAfterNewContent: bool | None = None
    contentIgnorePattern: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _file_xor_url(self) -> ContentUpdateChecker:
        has_file = self.file is not None
        has_url = self.url is not None
        if has_file == has_url:
            raise ValueError(
                "contentUpdateChecker: supply exactly one of file or url"
            )
        if has_file and (self.user is not None or self.password is not None):
            raise ValueError(
                "contentUpdateChecker: user/password only valid with url"
            )
        return self
