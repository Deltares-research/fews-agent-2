"""Per-project git: track the agent's file changes, show diffs in chat.

Each session folder gets its OWN local git repository (no remotes, never
pushed) covering what the agent generates: ``generated/`` + ``project.yaml``.
After every agent action that (re)writes files, ``commit_and_diff``:

  1. diffs the work tree against HEAD — which, because we commit after every
     action, contains exactly the files that PRE-EXISTED this action. Files
     created for the first time are untracked and therefore never shown;
  2. commits everything, making this action the next action's baseline;
  3. returns the per-file unified diffs for the chat.

SAFETY — confinement. ``projects/`` lives inside the development repo's tree
(gitignored). A bare ``git -C <session>`` without a repo there would walk UP
and operate on the development repository. Every command here therefore runs
with explicit ``--git-dir=<session>/.git --work-tree=<session>``, and no
command runs unless that ``.git`` directory actually exists.

Failure policy: git missing or any command failing → log + empty result;
never break a build. Chat-state files, logs and inputs/ are excluded via the
session repo's own .gitignore (the diffs are about what the AGENT generates).
"""
from __future__ import annotations

import logging
import shutil
import subprocess
from pathlib import Path

_logger = logging.getLogger(__name__)

MAX_FILES = 5           # diffs shown per action
MAX_LINES = 120         # lines shown per file diff

# inputs/* is ignored EXCEPT the CSVs: the agent can WRITE input CSVs
# (write_input_file op) and edit uploaded ones — those changes get the same
# diff treatment as generated files. Shapefiles/yamls stay untracked
# (binary / bulk uploads the agent never edits).
_SESSION_GITIGNORE = """\
.chat_state.json
.chat_history.json
_conversation.md
_app.log
inputs/*
!inputs/*.csv
"""


def available() -> bool:
    return shutil.which("git") is not None


def _run(session_dir: Path, *args: str) -> subprocess.CompletedProcess:
    """Run git strictly confined to the session repo (never the dev repo)."""
    return subprocess.run(
        ["git", f"--git-dir={session_dir / '.git'}",
         f"--work-tree={session_dir}", *args],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=30,
    )


def ensure_repo(session_dir: Path) -> bool:
    """Init the per-session repo (idempotent). True when usable."""
    session_dir = Path(session_dir)
    if not available() or not session_dir.is_dir():
        return False
    git_dir = session_dir / ".git"
    try:
        if not git_dir.is_dir():
            init = subprocess.run(
                ["git", "init", "--initial-branch=main", str(session_dir)],
                capture_output=True, text=True, timeout=30,
            )
            if init.returncode != 0 or not git_dir.is_dir():
                _logger.warning("project git init failed: %s", init.stderr)
                return False
            # The ignore rules MUST exist before the baseline add — without
            # them the baseline would commit chat state and logs.
            (session_dir / ".gitignore").write_text(
                _SESSION_GITIGNORE, encoding="utf-8",
            )
            _run(session_dir, "config", "user.email", "agent@fews.local")
            _run(session_dir, "config", "user.name", "FEWS Agent")
            # Baseline commit (--allow-empty guarantees HEAD exists so every
            # later `diff HEAD` is well-defined).
            _run(session_dir, "add", "-A")
            _run(session_dir, "commit", "--allow-empty", "-m", "baseline")
        # Keep the ignore rules current for repos made by older versions —
        # rewriting the same content is a no-op for git.
        gi = session_dir / ".gitignore"
        if (not gi.is_file()
                or gi.read_text(encoding="utf-8") != _SESSION_GITIGNORE):
            gi.write_text(_SESSION_GITIGNORE, encoding="utf-8")
        return True
    except Exception as exc:  # noqa: BLE001
        _logger.warning("project git unavailable for %s: %s: %s",
                        session_dir.name, type(exc).__name__, exc)
        return False


def commit_and_diff(session_dir: Path, label: str) -> list[tuple[str, str]]:
    """Diff pre-existing files changed by this action, then commit everything.

    Returns ``[(relpath, unified_diff), ...]`` for files that existed BEFORE
    this action (tracked at HEAD) and were modified by it. First-time files
    are committed silently — they become diffable from the next action on.
    """
    session_dir = Path(session_dir)
    if not ensure_repo(session_dir):
        return []
    try:
        # Created / removed files are announced by NAME only (no content
        # dump): new-file content is all-new by definition, and a removal's
        # "diff" would be the whole file in minus lines.
        # -uall lists untracked FILES (default collapses new dirs to "dir/")
        status0 = _run(session_dir, "status", "--porcelain", "-uall")
        created, removed = [], []
        for ln in status0.stdout.splitlines():
            code, _, path = ln[:2], ln[2], ln[3:].strip().strip('"')
            path = path.replace("\\", "/")
            if code == "??" and Path(path).name != ".gitignore":
                created.append(path)
            elif "D" in code:
                removed.append(path)

        changed = _run(session_dir, "diff", "HEAD", "--name-only")
        names = [n for n in changed.stdout.splitlines()
                 if n.strip() and n.replace("\\", "/") not in removed]
        diffs: list[tuple[str, str]] = []
        for name in names[:MAX_FILES]:
            d = _run(session_dir, "diff", "HEAD", "--unified=3", "--", name)
            # The filename is our own header, and the reader wants ONLY the
            # changed lines (colored by the ```diff fence) — drop git's
            # preamble, @@ hunk markers, and unchanged context lines.
            lines = [ln for ln in d.stdout.splitlines()
                     if (ln.startswith("+") or ln.startswith("-"))
                     and not ln.startswith(("+++", "---"))]
            if len(lines) > MAX_LINES:
                lines = lines[:MAX_LINES] + [
                    f"… (truncated, {len(d.stdout.splitlines())} lines total)"
                ]
            diffs.append((name.replace("\\", "/"), "\n".join(lines)))
        if len(names) > MAX_FILES:
            diffs.append((f"(+{len(names) - MAX_FILES} more changed files)", ""))

        def _name_line(verb: str, paths: list[str]) -> None:
            if not paths:
                return
            shown = ", ".join(f"`{p}`" for p in paths[:8])
            more = f" (+{len(paths) - 8} more)" if len(paths) > 8 else ""
            diffs.append((f"{verb}: {shown}{more}", ""))

        _name_line("New files", sorted(created))
        _name_line("Removed", sorted(removed))

        if status0.stdout.strip():
            _run(session_dir, "add", "-A")
            _run(session_dir, "commit", "-m", label)
        return diffs
    except Exception as exc:  # noqa: BLE001
        _logger.warning("project git diff failed for %s: %s: %s",
                        session_dir.name, type(exc).__name__, exc)
        return []


def format_diffs(diffs: list[tuple[str, str]]) -> str:
    """Chat-ready markdown for the changed pre-existing files ('' if none)."""
    if not diffs:
        return ""
    parts = ["**Changed since the last action:**"]
    for name, text in diffs:
        if not text:
            parts.append(f"_{name}_")
            continue
        parts.append(f"`{name}`\n```diff\n{text}\n```")
    return "\n\n".join(parts)
