"""Headless FEWS configuration check (gauntlet tier 4).

Optional and degradable: when ``FEWS_CHECK_CMD`` / ``FEWS_HOME`` are
unset, or the subprocess fails to start, this module emits a *skip*
diagnostic and never raises. Same contract as ``app.project_git`` when
git is missing.

Env:

- ``FEWS_CHECK_CMD`` — full command template.
  ``{path}`` is replaced with the config root (generation-tree folder).
  ``{zip}`` is replaced with a temp Config-only region zip (FewsCLI
  ``regionpath=``). Example::

      Delft-FEWSc.exe -Xmx1G "-Wclasspath.1=%FEWS_HOME%/patch.jar"
      "-Wclasspath.2=%FEWS_HOME%/bin/*.jar"
      -Wmain.class=nl.wldelft.fews.tools.FewsConfigCLI
      regionpath={zip} loglevel=warn VALIDATE_CONFIG_FILES

- ``FEWS_HOME`` — if set and ``FEWS_CHECK_CMD`` is not, we refuse to
  guess a command (skip, never crash).
"""
from __future__ import annotations

import os
import re
import subprocess
import tempfile
from pathlib import Path

from fews_agent.validation.diagnostic import Diagnostic

_LINE_RE = re.compile(
    r"^(?P<file>\S+?)(?::(?P<line>\d+))?:\s*(?P<sev>ERROR|WARN|WARNING|INFO)"
    r"[:\s]+(?P<msg>.+)$",
    re.IGNORECASE,
)

# FewsCLI / Delft-FEWS log lines, e.g.
#   ERROR - Config.Workflows.ImportGFS: workflow does not exist
#   WARN  2026-01-01 12:00:00,001 [main] nl.wldelft... - message
_FEWS_LOG_RE = re.compile(
    r"^(?P<sev>ERROR|WARN|WARNING|INFO)\b"
    r"(?:\s+\d{4}-\d{2}-\d{2}[^\]]*\]?)?"
    r"(?:\s+\[[^\]]+\])?"
    r"(?:\s+\S+)?"
    r"\s*[-:]\s*(?P<msg>.+)$",
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
            "folder (use {path} for the folder, {zip} for a Config-only "
            "region zip). Tier 4 is skipped."
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

    tmp_zip: Path | None = None
    try:
        cmd = cmd_tmpl.replace("{path}", str(path))
        if "{zip}" in cmd:
            from fews_agent.validation.fews_bundle import write_region_zip

            tmp_dir = Path(tempfile.mkdtemp(prefix="fews-cli-"))
            tmp_zip = tmp_dir / "region.zip"
            written = write_region_zip(path, tmp_zip, config_only=True)
            if written is None:
                return [Diagnostic(
                    file=str(path),
                    line=None,
                    severity="skip",
                    rule_id="fews.failed",
                    message="FEWS check {zip}: tree produced an empty region zip.",
                    evidence=cmd_tmpl,
                    tier="fews_check",
                )]
            cmd = cmd.replace("{zip}", str(written))
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
    finally:
        if tmp_zip is not None:
            try:
                tmp_zip.unlink(missing_ok=True)
                tmp_zip.parent.rmdir()
            except OSError:
                pass

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


def _severity(sev_raw: str) -> str | None:
    sev = sev_raw.upper()
    if sev == "ERROR":
        return "error"
    if sev in ("WARN", "WARNING"):
        return "warning"
    return None


def _parse_output(text: str) -> list[Diagnostic]:
    out: list[Diagnostic] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        m = _LINE_RE.match(line)
        if m:
            severity = _severity(m.group("sev"))
            if severity is None:
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
            continue
        m = _FEWS_LOG_RE.match(line)
        if not m:
            continue
        severity = _severity(m.group("sev"))
        if severity is None:
            continue
        out.append(Diagnostic(
            file="-",
            line=None,
            severity=severity,  # type: ignore[arg-type]
            rule_id="fews.config",
            message=m.group("msg").strip(),
            evidence=line,
            tier="fews_check",
        ))
    return out
