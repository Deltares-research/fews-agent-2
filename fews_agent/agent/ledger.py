"""Provenance ledger — who owns each file in a config tree.

Origins:
  pattern  — regenerable from a pattern instance (safe to overwrite
             unless the fingerprint drifted)
  llm      — authored once, verified; never auto-regenerated
  human    — pre-existing or user-edited; read-only unless the user
             explicitly asks to edit

The ledger lives at ``<config>/.fews-agent/ledger.yaml`` so it is never
counted as a FEWS config file (tutorial file-count oracle stays).
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any, Literal

import yaml

Origin = Literal["pattern", "llm", "human"]
LEDGER_DIR = ".fews-agent"
LEDGER_NAME = "ledger.yaml"


def fingerprint(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


@dataclass
class LedgerEntry:
    origin: Origin
    fingerprint: str | None = None
    pattern: str | None = None
    instance: dict[str, Any] | None = None
    authored: str | None = None
    verified: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"origin": self.origin}
        if self.fingerprint:
            out["fingerprint"] = self.fingerprint
        if self.pattern:
            out["pattern"] = self.pattern
        if self.instance:
            out["instance"] = self.instance
        if self.authored:
            out["authored"] = self.authored
        if self.verified:
            out["verified"] = list(self.verified)
        return out

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> LedgerEntry:
        return cls(
            origin=raw.get("origin") or "human",
            fingerprint=raw.get("fingerprint"),
            pattern=raw.get("pattern"),
            instance=raw.get("instance"),
            authored=raw.get("authored"),
            verified=list(raw.get("verified") or []),
        )


@dataclass
class Ledger:
    root: Path
    files: dict[str, LedgerEntry] = field(default_factory=dict)

    @property
    def path(self) -> Path:
        return self.root / LEDGER_DIR / LEDGER_NAME

    def get(self, relpath: str) -> LedgerEntry | None:
        return self.files.get(_norm(relpath))

    def set(self, relpath: str, entry: LedgerEntry) -> None:
        self.files[_norm(relpath)] = entry

    def mark_human_tree(self, relpaths: list[str], *, bytes_for: dict[str, bytes] | None = None) -> None:
        """First-open: every existing file is human-owned."""
        for rel in relpaths:
            key = _norm(rel)
            if key in self.files:
                continue
            fp = None
            if bytes_for and key in bytes_for:
                fp = fingerprint(bytes_for[key])
            self.files[key] = LedgerEntry(origin="human", fingerprint=fp)

    def mark_llm(
        self, relpath: str, data: bytes, verified: list[str],
    ) -> None:
        self.set(relpath, LedgerEntry(
            origin="llm",
            fingerprint=fingerprint(data),
            authored=date.today().isoformat(),
            verified=list(verified),
        ))

    def mark_pattern(
        self,
        relpath: str,
        pattern: str,
        instance: dict[str, Any] | None = None,
        data: bytes | None = None,
    ) -> None:
        self.set(relpath, LedgerEntry(
            origin="pattern",
            pattern=pattern,
            instance=instance,
            fingerprint=fingerprint(data) if data is not None else None,
        ))

    def may_overwrite(self, relpath: str, new_bytes: bytes | None = None) -> tuple[bool, str]:
        """Return (ok, reason). human is never overwritten; drifted
        pattern fingerprints are flagged, not clobbered."""
        entry = self.get(relpath)
        if entry is None:
            return True, "untracked"
        if entry.origin == "human":
            return False, "origin=human is read-only"
        if entry.origin == "llm":
            return False, "origin=llm is not auto-regenerated"
        if entry.origin == "pattern" and entry.fingerprint and new_bytes is not None:
            if fingerprint(new_bytes) != entry.fingerprint:
                # Caller is proposing a *new* pattern render — the on-disk
                # bytes aren't passed here. Drift is checked separately.
                pass
        return True, "ok"

    def drifted_pattern(self, relpath: str, on_disk: bytes) -> bool:
        entry = self.get(relpath)
        if entry is None or entry.origin != "pattern" or not entry.fingerprint:
            return False
        return fingerprint(on_disk) != entry.fingerprint

    def to_dict(self) -> dict[str, Any]:
        return {
            "files": {k: v.to_dict() for k, v in sorted(self.files.items())},
        }

    def save(self) -> Path:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            yaml.safe_dump(self.to_dict(), sort_keys=False, width=200),
            encoding="utf-8",
        )
        return self.path


def _norm(relpath: str) -> str:
    return str(relpath).replace("\\", "/").lstrip("./")


def load_ledger(root: Path) -> Ledger:
    root = Path(root)
    ledger = Ledger(root=root)
    if ledger.path.is_file():
        raw = yaml.safe_load(ledger.path.read_text(encoding="utf-8")) or {}
        for rel, entry in (raw.get("files") or {}).items():
            if isinstance(entry, dict):
                ledger.files[_norm(rel)] = LedgerEntry.from_dict(entry)
    return ledger


def sync_patterns_from_blueprint(
    ledger: Ledger,
    patterns: list[dict[str, Any]],
) -> Ledger:
    """Increment 4: project.yaml pattern instances become ledger rows.

    We do not know the rendered relpaths until expand time, so each
    instance is recorded under a synthetic key
    ``pattern:<path>#<index>`` plus any ``output`` hints. Existing
    human/llm rows are never overwritten.
    """
    for i, block in enumerate(patterns or []):
        path = str(block.get("pattern") or "")
        instances = block.get("instances") or [{}]
        if isinstance(instances, dict):
            instances = [instances]
        for j, inst in enumerate(instances):
            key = f"pattern:{path}#{i}.{j}"
            existing = ledger.get(key)
            if existing and existing.origin in {"human", "llm"}:
                continue
            ledger.mark_pattern(key, path, instance=dict(inst) if isinstance(inst, dict) else {})
    return ledger
