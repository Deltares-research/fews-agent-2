"""Cache-authoritative project store.

Each agent session has a named project. `input.json` under the project
directory is the source of truth — the TUI reloads it before every menu
render, and every mutating tool persists synchronously. Reloading a
project restores full state (data + chat history).

Root defaults to `~/.fews-agent/projects` and is override-able via
`FEWS_AGENT_HOME` so tests can redirect to a tmp dir. User-local (not
repo-local) so project files don't get caught in git.
"""
from __future__ import annotations

import json
import os
from dataclasses import asdict, is_dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any


def _default_home() -> Path:
    override = os.environ.get("FEWS_AGENT_HOME")
    if override:
        return Path(override)
    return Path.home() / ".fews-agent"


class ProjectStore:
    """Per-project JSON persistence with atomic writes."""

    def __init__(self, home: Path | None = None) -> None:
        self.home = Path(home) if home else _default_home()
        self.projects_dir = self.home / "projects"
        self.projects_dir.mkdir(parents=True, exist_ok=True)

    def path_for(self, name: str) -> Path:
        return self.projects_dir / name

    def input_path(self, name: str) -> Path:
        return self.path_for(name) / "input.json"

    def history_path(self, name: str) -> Path:
        return self.path_for(name) / "history.jsonl"

    def list(self) -> list[str]:
        return sorted(
            p.name
            for p in self.projects_dir.iterdir()
            if p.is_dir() and (p / "input.json").exists()
        )

    def exists(self, name: str) -> bool:
        return self.input_path(name).exists()

    def load(self, name: str) -> dict[str, Any]:
        path = self.input_path(name)
        if not path.exists():
            return {}
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)

    def save(self, name: str, data: dict[str, Any]) -> None:
        """Atomic write: `.tmp` then `os.replace` so readers never see a
        half-written file if the process dies mid-save."""
        target = self.input_path(name)
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_suffix(target.suffix + ".tmp")
        with tmp.open("w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False, default=_json_default)
            f.write("\n")
        os.replace(tmp, target)

    def append_message(self, name: str, message: dict[str, Any]) -> None:
        """Append-only chat log; one JSON object per line."""
        path = self.history_path(name)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(message, ensure_ascii=False, default=_json_default))
            f.write("\n")

    def read_history(self, name: str) -> list[dict[str, Any]]:
        path = self.history_path(name)
        if not path.exists():
            return []
        with path.open("r", encoding="utf-8") as f:
            return [json.loads(line) for line in f if line.strip()]

    def write_artifact(self, name: str, relpath: str | Path, content: str) -> Path:
        """Generated XML outputs go under `<project>/generated/<relpath>`."""
        out = self.path_for(name) / "generated" / Path(relpath)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(content, encoding="utf-8")
        return out


def _json_default(obj: Any) -> Any:
    """Preserve Decimal exactly and unwrap dataclasses the agent produces."""
    if isinstance(obj, Decimal):
        return str(obj)
    if is_dataclass(obj):
        return asdict(obj)
    if isinstance(obj, Path):
        return str(obj)
    raise TypeError(f"Not JSON-serializable: {type(obj).__name__}")
