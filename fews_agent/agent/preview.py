"""On-demand file preview: show how a file WILL generate, in the chat.

Rendering is a pure function of project state (Jinja + Pydantic, in memory —
``blueprint.expand`` never touches disk), and it is fast (~10 ms per file
after warm-up, measured), so previews are computed FRESH on every request.
Nothing is cached and nothing regenerates in the background; the preview can
never be stale with respect to the slots.

Two sources, in order:
  live render      — files a pattern instance produces, rendered now from the
                     current state (the ~25 module files);
  last build       — files only the full pipeline produces (CSV-ingested
                     Locations.xml, derived Topology, sa_global.Properties…)
                     are read from <session>/generated as of the last build,
                     clearly labelled as such.

Shared by the ``/show`` · ``/present`` slash commands and the ``preview_file``
patch op, so prose and commands render identically.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

PATTERN_ROOT = Path(__file__).resolve().parents[1] / "patterns"

# How much file content to show in chat before truncating.
MAX_CHARS = 6000
MAX_FILES = 3


@dataclass
class PreviewFile:
    relpath: str
    content: str
    xsd_ok: bool | None      # None = not XML (e.g. sa_global.Properties)
    source: str              # "live render" | "last build"
    label: str               # instance label ("GFS") or "" for disk files


def preview_files(
    state: dict, target: str, output_root: Path | None = None,
) -> list[PreviewFile]:
    """Render/collect the files matching ``target`` (instance label like
    "GFS", or a filename fragment like "ImportGFS" / "Topology.xml")."""
    from fews_agent.agent.blueprint import Blueprint, PatternRef, expand
    from fews_agent.agent.turn_engine import _LABEL_VAR_KEYS
    from fews_agent.validation.xsd import validate_xsd

    want = (target or "").strip().lower()
    if not want:
        return []

    out: list[PreviewFile] = []

    # --- live render from the current state -------------------------------
    refs, labels = [], {}
    for p in state.get("patterns") or []:
        insts = p.get("instances") or [{}]
        refs.append(PatternRef(pattern=p["pattern"], instances=list(insts)))
        for inst in insts:
            lbl = next((str(inst[k]) for k in _LABEL_VAR_KEYS if inst.get(k)),
                       p["pattern"].rsplit("/", 1)[-1])
            labels[id(inst)] = lbl
    if refs:
        bp = Blueprint(
            name=state.get("name") or "preview", output_root=Path("preview"),
            patterns=refs,
            singleton_seeds=dict(state.get("singleton_seeds") or {}),
        )
        result = expand(bp, PATTERN_ROOT)
        for f in result.rendered_files:
            lbl = f.instance_label or ""
            if want in f.relpath.lower() or want == lbl.lower():
                is_xml = f.relpath.lower().endswith(".xml")
                ok = validate_xsd(f.content.encode("utf-8"))[0] if is_xml else None
                out.append(PreviewFile(
                    relpath=f.relpath.replace("\\", "/"), content=f.content,
                    xsd_ok=ok, source="live render", label=lbl,
                ))

    # --- fallback: last build output on disk -------------------------------
    if not out and output_root is not None:
        root = Path(output_root)
        if root.is_dir():
            for p in sorted(root.rglob("*")):
                if not p.is_file():
                    continue
                rel = p.relative_to(root).as_posix()
                if want in rel.lower():
                    content = p.read_text(encoding="utf-8", errors="replace")
                    is_xml = rel.lower().endswith(".xml")
                    ok = (validate_xsd(content.encode("utf-8"))[0]
                          if is_xml else None)
                    out.append(PreviewFile(
                        relpath=rel, content=content, xsd_ok=ok,
                        source="last build", label="",
                    ))
    return out


def format_previews(previews: list[PreviewFile], target: str) -> str:
    """Chat-ready markdown: header + XSD badge + fenced content per file.

    One shared formatter so ``/show``, ``/present`` and the ``preview_file``
    op render identically in every shell.
    """
    if not previews:
        return (
            f"Nothing in the project matches **{target}** — nothing to "
            f"preview. (Configured sources render live; files produced only "
            f"at assembly appear here after a build.)"
        )
    parts: list[str] = []
    shown = previews[:MAX_FILES]
    if len(previews) > MAX_FILES:
        rest = ", ".join(f"`{p.relpath}`" for p in previews[MAX_FILES:])
        parts.append(
            f"_{len(previews)} files match — showing the first "
            f"{MAX_FILES}; also: {rest}_"
        )
    for pf in shown:
        badge = ("✅ XSD-valid" if pf.xsd_ok
                 else "❌ XSD-INVALID" if pf.xsd_ok is False else "(not XML)")
        parts.append(f"**`{pf.relpath}`** · {badge} · _{pf.source}_")
        body = pf.content
        if len(body) > MAX_CHARS:
            body = body[:MAX_CHARS] + f"\n… (truncated, {len(pf.content)} chars total)"
        lang = "xml" if pf.relpath.lower().endswith(".xml") else ""
        parts.append(f"```{lang}\n{body}\n```")
    return "\n\n".join(parts)
