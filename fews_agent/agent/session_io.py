"""Session dir I/O — ``.chat_state.json`` + ``.chat_history.json``.

HTTP/Streamlit/MCP all persist the same layout. Blob sync stays on the
HTTP wrapper; this module is local disk only.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

STATE_NAME = ".chat_state.json"
HISTORY_NAME = ".chat_history.json"


def state_path(project_dir: Path) -> Path:
    return Path(project_dir) / STATE_NAME


def history_path(project_dir: Path) -> Path:
    return Path(project_dir) / HISTORY_NAME


def load_session(project_dir: Path) -> tuple[dict[str, Any], list]:
    """Load state + history. Missing history is ``[]``. Raises if no state."""
    root = Path(project_dir)
    state = json.loads(state_path(root).read_text(encoding="utf-8"))
    hp = history_path(root)
    history = json.loads(hp.read_text(encoding="utf-8")) if hp.is_file() else []
    return state, history


def save_session(
    project_dir: Path, state: dict[str, Any], history: list | None = None,
) -> None:
    root = Path(project_dir)
    root.mkdir(parents=True, exist_ok=True)
    state_path(root).write_text(
        json.dumps(state, indent=2, default=str), encoding="utf-8",
    )
    history_path(root).write_text(
        json.dumps(history or [], indent=2, default=str), encoding="utf-8",
    )
