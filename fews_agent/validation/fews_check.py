"""Headless FEWS configuration check (gauntlet tier 4).

Optional and degradable: when ``FEWS_CHECK_CMD`` / ``FEWS_HOME`` are
unset, or the subprocess fails to start, this module emits a *skip*
diagnostic and never raises. Same contract as ``app.project_git`` when
git is missing.

Env:

- ``FEWS_CHECK_CMD`` — full command template. ``{path}`` is replaced
  with the config root. Example:
  ``java -jar "%FEWS_HOME%/bin/fews-lcc.jar" --check {path}``
- ``FEWS_HOME`` — if set and ``FEWS_CHECK_CMD`` is not, we look for a
  conventional checker under that install. Until the exact CLI is
  pinned, this also degrades to skip (we refuse to guess a command
  that would fail loudly on every machine).
"""
from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

from fews_agent.validation.diagnostic import Diagnostic

_LINE_RE = re.compile(
    r"^(?P<file>\S+?)(?::(?P<line>\d+))?:\s*(?P<sev>ERROR|WARN|WARNING|INFO)"
    r"[:\s]+(?P<msg>.+)$",
    re.IGNORECASE,
)


def available() -> bool:
    """True when a check command has been configured."""
    return bool(os.environ.get("FEWS_CHECK_CMD", "").strip())


def run_fews_check(path: Path, timeout: int = 120) -> list[Diagnostic]:
    """Run the configured FEWS checker against ``path``.

    Returns skip diagnostics when unconfigured; never raises.
    """
    path = Path(path)
    cmd_tmpl = os.environ.get("FEWS_CHECK_CMD", "").strip()
    if not cmd_tmpl:
        hint = (
            "Set FEWS_CHECK_CMD to a command that checks a FEWS config "
            "folder (use {path} for the folder). Tier 4 is skipped."
        )
        if os.environ.get("FEWS_HOME"):
            hint = (
                "FEWS_HOME is set but FEWS_CHECK_CMD is not — refusing "
                "to guess the checker CLI. " + hint
            )
        return [Diagnostic(
            file=str(path),
            line=None,
            severity="skip",
            rule_id="fews.unavailable",
            message=hint,
            tier="fews_check",
        )]

    cmd = cmd_tmpl.replace("{path}", str(path))
    try:
        proc = subprocess.run(
            cmd,
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return [Diagnostic(
            file=str(path),
            line=None,
            severity="skip",
            rule_id="fews.failed",
            message=f"FEWS check did not run: {exc}",
            evidence=cmd,
            tier="fews_check",
        )]

    text = (proc.stdout or "") + "\n" + (proc.stderr or "")
    found = _parse_output(text)
    if found:
        return found
    if proc.returncode != 0:
        return [Diagnostic(
            file=str(path),
            line=None,
            severity="error",
            rule_id="fews.exit",
            message=f"FEWS check exited {proc.returncode}",
            evidence=text.strip()[:800],
            tier="fews_check",
        )]
    return []


def _parse_output(text: str) -> list[Diagnostic]:
    out: list[Diagnostic] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        m = _LINE_RE.match(line)
        if not m:
            continue
        sev_raw = m.group("sev").upper()
        if sev_raw == "ERROR":
            severity: str = "error"
        elif sev_raw in ("WARN", "WARNING"):
            severity = "warning"
        else:
            continue
        line_no = None
        if m.group("line"):
            try:
                line_no = int(m.group("line"))
            except ValueError:
                line_no = None
        out.append(Diagnostic(
            file=m.group("file"),
            line=line_no,
            severity=severity,  # type: ignore[arg-type]
            rule_id="fews.check",
            message=m.group("msg").strip(),
            evidence=line,
            tier="fews_check",
        ))
    return out
