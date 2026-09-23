"""Structured diagnostics shared by every verification tier.

Host LLMs (Cursor, Copilot, Claude Desktop, ChatGPT) consume these to
repair XML. Free-text errors force them to guess; this shape does not.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal

Severity = Literal["error", "warning", "convention", "skip"]
Tier = Literal["xsd", "semantic", "conform", "fews_check"]


@dataclass(frozen=True)
class Diagnostic:
    """One finding from one gauntlet tier."""

    file: str
    line: int | None
    severity: Severity
    rule_id: str
    message: str
    fix_hint: str = ""
    evidence: str = ""
    tier: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class GauntletReport:
    """Outcome of ``validate_config`` / ``validate_xml``."""

    path: str
    diagnostics: list[Diagnostic] = field(default_factory=list)
    files_checked: int = 0
    tiers_run: list[str] = field(default_factory=list)

    @property
    def errors(self) -> list[Diagnostic]:
        return [d for d in self.diagnostics if d.severity == "error"]

    @property
    def warnings(self) -> list[Diagnostic]:
        return [d for d in self.diagnostics if d.severity == "warning"]

    @property
    def skips(self) -> list[Diagnostic]:
        return [d for d in self.diagnostics if d.severity == "skip"]

    @property
    def ok(self) -> bool:
        """True when no *errors* were raised. Warnings / convention / skip
        do not fail the gauntlet (same idea as an advisory linter)."""
        return not self.errors

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "ok": self.ok,
            "files_checked": self.files_checked,
            "tiers_run": list(self.tiers_run),
            "diagnostics": [d.to_dict() for d in self.diagnostics],
            "error_count": len(self.errors),
            "warning_count": len(self.warnings),
        }
