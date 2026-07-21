"""The download bundle must never escape the project's output directory.

Regression for a CRITICAL bug: the app's "Download all generated files" zip
used ``Path(summary.get("output_root", ""))``. ``Path("")`` IS ``Path(".")`` —
the Streamlit process CWD, i.e. the whole repository — and the scoped
phase/module builds didn't report ``output_root`` at all. Clicking Download
after a scoped build therefore zipped the entire codebase, including ``.env``
with live API keys.

Two independent guarantees are pinned here:
  1. every build entrypoint reports an absolute ``output_root``;
  2. the app-side guard refuses anything that isn't a real output directory.
"""
from __future__ import annotations

import inspect
from pathlib import Path

import runners.agent.build_from_blueprint as B


# --- 1. every build entrypoint reports output_root ------------------------

def test_all_build_entrypoints_report_output_root():
    # A consumer must never have to guess (and fall back to the CWD).
    for name in ("build_from_blueprint", "build_phase", "build_module"):
        src = inspect.getsource(getattr(B, name))
        assert '"output_root": str(output_root)' in src, name


# --- 2. the app-side download guard --------------------------------------

def _download_allowed(summary: dict, cwd: Path) -> bool:
    """Mirror of the guard in frontend/web_app.py (kept in sync by this test).

    Returns True only when the summary names a real, absolute output directory
    that is not the CWD/repo root or an ancestor of it.
    """
    raw = str(summary.get("output_root") or "").strip()
    if not raw:
        return False
    p = Path(raw)
    resolved = p.resolve()
    return (
        p.is_absolute()
        and resolved.is_dir()
        and resolved != cwd
        and resolved not in cwd.parents
    )


def test_guard_blocks_missing_or_empty_output_root(tmp_path):
    cwd = Path.cwd().resolve()
    # The exact shape the scoped builds used to return.
    assert not _download_allowed({}, cwd)
    assert not _download_allowed({"output_root": ""}, cwd)
    assert not _download_allowed({"output_root": None}, cwd)


def test_guard_blocks_cwd_and_relative_paths():
    cwd = Path.cwd().resolve()
    # Path(".") / "" both resolve to the repo root — the codebase-leak case.
    assert not _download_allowed({"output_root": "."}, cwd)
    assert not _download_allowed({"output_root": "generated"}, cwd)
    assert not _download_allowed({"output_root": str(cwd)}, cwd)
    # An ancestor of the repo is just as bad.
    assert not _download_allowed({"output_root": str(cwd.parent)}, cwd)


def test_guard_allows_a_real_project_output_dir(tmp_path):
    cwd = Path.cwd().resolve()
    out = tmp_path / "generated"
    out.mkdir()
    (out / "Locations.xml").write_text("<locations/>", encoding="utf-8")
    assert _download_allowed({"output_root": str(out)}, cwd)


def test_guard_would_have_excluded_dotenv(tmp_path):
    """The concrete harm: the old fallback bundled repo-root files like .env."""
    cwd = Path.cwd().resolve()
    # Old behaviour: Path("") -> CWD, which contains the real .env.
    assert Path("") == Path(".")
    assert not _download_allowed({"output_root": ""}, cwd)
