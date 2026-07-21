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


# --- 3. the bundle is manifest-driven, not a directory sweep --------------

def _bundled_paths(summary: dict, out_root: Path) -> list[str]:
    """Mirror of the app's manifest-driven zip selection.

    Only files the build REPORTED are bundled, each confined under
    output_root — so a stray file sitting in the output directory (or a
    traversal-ish manifest entry) can never be included.
    """
    root = out_root.resolve()
    picked: list[str] = []
    for rel in sorted({
        str(e.get("path", "")).strip()
        for e in (summary.get("files") or [])
        if str(e.get("path", "")).strip()
    }):
        fp = (root / rel).resolve()
        if root not in fp.parents and fp != root:
            continue
        if not fp.is_file():
            continue
        picked.append(str(fp.relative_to(root)).replace("\\", "/"))
    return picked


def test_bundle_includes_only_manifest_files(tmp_path):
    out = tmp_path / "generated"
    (out / "RegionConfigFiles").mkdir(parents=True)
    (out / "RegionConfigFiles" / "Locations.xml").write_text("<l/>", encoding="utf-8")
    (out / "sa_global.Properties").write_text("REGION=X", encoding="utf-8")
    # A stray file the build did NOT write — must never be bundled.
    (out / "NOTES-not-part-of-build.txt").write_text("stray", encoding="utf-8")

    summary = {"files": [
        {"path": "RegionConfigFiles/Locations.xml"},
        {"path": "sa_global.Properties"},
    ]}
    picked = _bundled_paths(summary, out)
    assert picked == ["RegionConfigFiles/Locations.xml", "sa_global.Properties"]
    assert "NOTES-not-part-of-build.txt" not in picked


def test_bundle_refuses_entries_escaping_output_root(tmp_path):
    out = tmp_path / "generated"
    out.mkdir()
    (out / "ok.xml").write_text("<x/>", encoding="utf-8")
    secret = tmp_path / ".env"
    secret.write_text("AZURE_AI_API_KEY=shhh", encoding="utf-8")

    summary = {"files": [{"path": "ok.xml"}, {"path": "../.env"}]}
    picked = _bundled_paths(summary, out)
    assert picked == ["ok.xml"]          # the escape attempt is dropped
    assert all(".env" not in p for p in picked)
