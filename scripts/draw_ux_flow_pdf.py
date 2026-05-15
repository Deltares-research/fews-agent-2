"""Render the FEWS-agent user→XML pipeline as a single-page PDF flowchart.

Run:
    python scripts/draw_ux_flow_pdf.py [out_pdf]

Default output: docs/ux-flow.pdf
"""
from __future__ import annotations

import sys
from pathlib import Path

import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch


# ---------------------------------------------------------------------------
# Layout helpers
# ---------------------------------------------------------------------------

def add_box(
    ax,
    x: float,
    y: float,
    w: float,
    h: float,
    title: str,
    body: str | None = None,
    fill: str = "#f5f7fa",
    edge: str = "#1f2933",
    title_color: str = "#0b1726",
    body_color: str = "#3b4a5a",
    title_size: int = 11,
    body_size: int = 8,
    bold_title: bool = True,
    title_align: str = "center",
) -> tuple[float, float, float, float]:
    """Draw a rounded rectangle with optional title + body text."""
    patch = FancyBboxPatch(
        (x, y),
        w,
        h,
        boxstyle="round,pad=0.02,rounding_size=0.08",
        linewidth=1.4,
        edgecolor=edge,
        facecolor=fill,
        zorder=2,
    )
    ax.add_patch(patch)

    title_x = x + w / 2 if title_align == "center" else x + 0.15
    title_y = y + h - 0.22 if body else y + h / 2
    ax.text(
        title_x,
        title_y,
        title,
        ha=title_align,
        va="top" if body else "center",
        fontsize=title_size,
        fontweight="bold" if bold_title else "normal",
        color=title_color,
        zorder=3,
    )
    if body:
        ax.text(
            x + 0.15,
            y + h - 0.45,
            body,
            ha="left",
            va="top",
            fontsize=body_size,
            color=body_color,
            zorder=3,
            family="monospace",
        )
    return x, y, x + w, y + h


def arrow(
    ax,
    x1: float,
    y1: float,
    x2: float,
    y2: float,
    label: str | None = None,
    color: str = "#1f2933",
    style: str = "-|>",
    lw: float = 1.4,
    label_offset: tuple[float, float] = (0.05, 0.05),
) -> None:
    """Draw a directional arrow with optional label."""
    a = FancyArrowPatch(
        (x1, y1),
        (x2, y2),
        arrowstyle=style,
        mutation_scale=14,
        color=color,
        linewidth=lw,
        zorder=4,
    )
    ax.add_patch(a)
    if label:
        ax.text(
            (x1 + x2) / 2 + label_offset[0],
            (y1 + y2) / 2 + label_offset[1],
            label,
            ha="center",
            va="bottom",
            fontsize=8,
            color="#5b6b7a",
            style="italic",
            zorder=4,
        )


# ---------------------------------------------------------------------------
# The flowchart
# ---------------------------------------------------------------------------

def draw_flowchart(pdf: PdfPages) -> None:
    fig, ax = plt.subplots(figsize=(11, 15.5))
    ax.set_xlim(0, 10)
    ax.set_ylim(0, 22)
    ax.set_aspect("equal")
    ax.axis("off")

    # Title
    ax.text(
        5, 21.4,
        "USER  →  FEWS-ready XML",
        ha="center", va="center",
        fontsize=16, fontweight="bold", color="#0b1726",
    )
    ax.text(
        5, 20.9,
        "fews-agent pipeline — chat to validated config",
        ha="center", va="center",
        fontsize=10, color="#5b6b7a", style="italic",
    )

    # ─── USER box ────────────────────────────────────────────────────
    add_box(
        ax, 4.0, 19.5, 2.0, 0.9,
        title="USER",
        body="configurator",
        fill="#fef3c7", edge="#92400e",
        title_size=12, body_size=8,
    )

    # ─── Two paths down: prose | files ───────────────────────────────
    arrow(ax, 4.6, 19.5, 2.5, 18.2, label="prose")
    arrow(ax, 5.4, 19.5, 7.5, 18.2, label="files")

    # ─── CHAT AGENT box (left branch) ────────────────────────────────
    add_box(
        ax, 0.5, 16.4, 4.0, 1.8,
        title="CHAT AGENT  (chat_step.py)",
        body=(
            "1. skills      regex (basin, adapter, imports)\n"
            "2. intent      LLM (qwen2.5)\n"
            "3. slot fill   additive merge\n"
            "4. pattern     resolver  ->  pattern instances\n"
            "5. reply       LLM (qwen2.5)"
        ),
        fill="#dbeafe", edge="#1e40af",
        title_size=10, body_size=8,
    )
    arrow(ax, 2.5, 16.4, 2.5, 15.7)

    # ─── project.yaml ────────────────────────────────────────────────
    add_box(
        ax, 1.0, 14.8, 3.0, 0.9,
        title="project.yaml",
        body="blueprint  ·  patterns + singleton_seeds",
        fill="#fef9c3", edge="#854d0e",
        title_size=11, body_size=8,
    )

    # ─── inputs/ folder (right branch) ───────────────────────────────
    add_box(
        ax, 5.5, 14.8, 4.0, 3.4,
        title="inputs/  (configurator files)",
        body=(
            "CSVs           locations · parameters ·\n"
            "               qualifiers · thresholds\n"
            "policy yamls   modifierTypes ·\n"
            "               locationIcons · …\n"
            "starters       Explorer · Products · …\n"
            "assets/        shp sidecars · wflow bin"
        ),
        fill="#dcfce7", edge="#166534",
        title_size=10, body_size=8,
    )

    # Both feed into the builder
    arrow(ax, 2.5, 14.8, 5.0, 13.8)
    arrow(ax, 7.5, 14.8, 5.0, 13.8)

    # ─── BUILDER super-box ───────────────────────────────────────────
    builder_x, builder_y, builder_w, builder_h = 0.4, 4.0, 9.2, 9.7
    box_outer = FancyBboxPatch(
        (builder_x, builder_y),
        builder_w,
        builder_h,
        boxstyle="round,pad=0.02,rounding_size=0.12",
        linewidth=2.2,
        edgecolor="#1f2933",
        facecolor="#f8fafc",
        zorder=1,
    )
    ax.add_patch(box_outer)
    ax.text(
        builder_x + builder_w / 2,
        builder_y + builder_h - 0.35,
        "BUILDER   (build_from_blueprint.py)",
        ha="center", va="top",
        fontsize=12, fontweight="bold", color="#0b1726",
    )

    # Sources (5 parallel feeders → one Pydantic+Jinja+XSD pass)
    src_y = 11.0
    src_h = 1.0
    feeders = [
        ("PATTERN EXPANSION",
         "patterns/auto/<name>/pattern.yaml\nJinja(data) → typed dict",
         "#fde68a", "#b45309"),
        ("CSV INGEST",
         "inputs/*.csv  →  pandas\n→ typed dict",
         "#bae6fd", "#075985"),
        ("PER-SPEC YAML INGEST",
         "inputs/*.yaml  +  templates/yaml-starters/*\n→ typed dict",
         "#bbf7d0", "#166534"),
        ("LLM FILTER DRAFTER",
         "qwen2.5 over rendered IDs\n→ Filters.xml payload",
         "#e9d5ff", "#6b21a8"),
        ("BUNDLED STANDARDS",
         "standard_inputs/*.yaml\nproject-trimmed by IDs",
         "#fecaca", "#991b1b"),
    ]
    feeder_w = 1.65
    feeder_gap = 0.13
    feeder_start = builder_x + 0.45
    for i, (title, body, fill, edge) in enumerate(feeders):
        fx = feeder_start + i * (feeder_w + feeder_gap)
        add_box(
            ax, fx, src_y, feeder_w, src_h,
            title=title, body=body,
            fill=fill, edge=edge,
            title_size=8, body_size=7,
        )
        # Arrow down to common pipeline
        arrow(ax, fx + feeder_w / 2, src_y, fx + feeder_w / 2, src_y - 0.4)

    # ─── COMMON pipeline: Pydantic → Jinja → XSD ─────────────────────
    pipe_y = 8.7
    add_box(
        ax, 0.8, pipe_y, 8.4, 1.6,
        title="Pydantic schema   →   Jinja2 template   →   XSD validation",
        body=(
            "every payload passes 3 gates — no XML touches disk\n"
            "without surviving all of them; fails fast and loud."
        ),
        fill="#e2e8f0", edge="#0f172a",
        title_size=10, body_size=8,
    )

    # Connect feeders bottom to pipe top
    for i in range(len(feeders)):
        fx = feeder_start + i * (feeder_w + feeder_gap) + feeder_w / 2
        arrow(ax, fx, 11.0 - 0.05, fx, pipe_y + 1.6 + 0.05, style="-")
    # Pipe bottom → next pass
    arrow(ax, 5.0, pipe_y, 5.0, pipe_y - 0.5)

    # ─── DETERMINISTIC DERIVERS ──────────────────────────────────────
    deriv_y = 6.85
    add_box(
        ax, 0.8, deriv_y, 8.4, 1.3,
        title="DETERMINISTIC DERIVERS   (post-render passes)",
        body=(
            "Topology.xml   (from workflow filenames)         LocationSets.xml\n"
            "ModuleInstanceDescriptors / WorkflowDescriptors  sa_global.Properties"
        ),
        fill="#fee2e2", edge="#7f1d1d",
        title_size=10, body_size=8,
    )
    arrow(ax, 5.0, deriv_y, 5.0, deriv_y - 0.45)

    # ─── STATIC ASSET MIRROR ─────────────────────────────────────────
    mirror_y = 5.0
    add_box(
        ax, 0.8, mirror_y, 8.4, 1.0,
        title="STATIC ASSET MIRROR",
        body="inputs/assets/**   →   generated/**   (verbatim copy)",
        fill="#e0e7ff", edge="#3730a3",
        title_size=10, body_size=8,
    )
    arrow(ax, 5.0, mirror_y, 5.0, mirror_y - 0.5)

    # ─── BUILDER exit arrow → output ─────────────────────────────────
    arrow(ax, 5.0, builder_y, 5.0, 3.2, style="-|>")

    # ─── OUTPUT ──────────────────────────────────────────────────────
    add_box(
        ax, 1.5, 0.5, 7.0, 2.5,
        title="generated/   —   FEWS-ready XML tree",
        body=(
            "RegionConfigFiles/       Filters · Grids · TimeSteps · Topology · …\n"
            "ModuleConfigFiles/       one per pattern instance\n"
            "WorkflowFiles/           one per pattern instance\n"
            "IdMapFiles/              bundled, project-trimmed\n"
            "SystemConfigFiles/       Explorer · DisplayGroups · …\n"
            "DisplayConfigFiles/      SpatialDisplay · TimeSeriesDisplay · …\n"
            "RootConfigFiles/         sa_global.Properties\n"
            "summary.json             build manifest"
        ),
        fill="#fef3c7", edge="#92400e",
        title_size=11, body_size=8,
    )

    # Stamp
    ax.text(
        5, 0.1,
        "✓ XSD-valid · ready to drop into Delft-FEWS",
        ha="center", va="bottom",
        fontsize=10, fontweight="bold", color="#166534",
    )

    pdf.savefig(fig, bbox_inches="tight", pad_inches=0.3)
    plt.close(fig)


# ---------------------------------------------------------------------------
# Page 2 — pattern role (1 simple sentence)
# ---------------------------------------------------------------------------

def draw_pattern_role_page(pdf: PdfPages) -> None:
    fig, ax = plt.subplots(figsize=(11, 8.5))
    ax.set_xlim(0, 10)
    ax.set_ylim(0, 8)
    ax.set_aspect("equal")
    ax.axis("off")

    ax.text(
        5, 7.4, "What is a pattern?",
        ha="center", va="center",
        fontsize=22, fontweight="bold", color="#0b1726",
    )
    ax.text(
        5, 6.85,
        "page 2",
        ha="center", va="center",
        fontsize=10, color="#94a3b8", style="italic",
    )

    # Big single sentence in simple terms
    add_box(
        ax, 0.5, 4.0, 9.0, 2.2,
        title="",
        body="",
        fill="#fef3c7", edge="#92400e",
    )
    ax.text(
        5, 5.1,
        "A pattern is a recipe.",
        ha="center", va="center",
        fontsize=24, fontweight="bold", color="#0b1726",
    )
    ax.text(
        5, 4.35,
        "The user picks the recipes they want.\nThe agent uses them to write the files.",
        ha="center", va="center",
        fontsize=14, color="#3b4a5a",
    )

    # Small visual: pattern → many files
    add_box(
        ax, 1.0, 2.0, 2.5, 1.0,
        title="HRDPS pattern",
        body="1 recipe",
        fill="#dbeafe", edge="#1e40af",
        title_size=11, body_size=9,
    )
    arrow(ax, 3.5, 2.5, 5.2, 2.5)
    ax.text(4.35, 2.7, "fires", ha="center", va="bottom",
            fontsize=9, color="#5b6b7a", style="italic")

    add_box(
        ax, 5.2, 1.5, 3.8, 2.0,
        title="4 FEWS files",
        body=(
            "ImportHRDPS.xml\n"
            "ImportHRDPSGrids.xml\n"
            "+ idMap entry\n"
            "+ topology entry"
        ),
        fill="#dcfce7", edge="#166534",
        title_size=11, body_size=9,
    )

    ax.text(
        5, 0.6,
        "Same recipe can be reused: GFS, NAM, GDPS… each one a new instance.",
        ha="center", va="center",
        fontsize=11, color="#5b6b7a", style="italic",
    )

    pdf.savefig(fig, bbox_inches="tight", pad_inches=0.3)
    plt.close(fig)


# ---------------------------------------------------------------------------
# Page 3 — steps in words
# ---------------------------------------------------------------------------

def draw_steps_page(pdf: PdfPages) -> None:
    fig, ax = plt.subplots(figsize=(11, 14))
    ax.set_xlim(0, 10)
    ax.set_ylim(0, 20)
    ax.set_aspect("equal")
    ax.axis("off")

    ax.text(
        5, 19.3, "How the agent builds a FEWS config",
        ha="center", va="center",
        fontsize=20, fontweight="bold", color="#0b1726",
    )
    ax.text(
        5, 18.75,
        "page 3  ·  the pipeline in plain words",
        ha="center", va="center",
        fontsize=10, color="#94a3b8", style="italic",
    )

    steps = [
        ("1", "The user talks to the agent in plain English.",
         "Just tells it what basins to model and what data sources to import."),
        ("2", "The agent extracts the facts.",
         "Deterministic regex (skills) pulls out names; a small LLM confirms intent."),
        ("3", "The agent picks recipes from a library.",
         "Each fact maps to one or more pattern.yaml files in patterns/auto/."),
        ("4", "The agent writes project.yaml.",
         "This is the single source of truth for the whole project."),
        ("5", "The user drops project data into inputs/.",
         "A few CSVs (stations, parameters), optional shapefiles and policy yamls."),
        ("6", "The builder expands every pattern.",
         "Each recipe + its variable values becomes structured FEWS payloads."),
        ("7", "Each payload is checked against a typed schema (Pydantic).",
         "Bad shape = fail loud. No silent surprises."),
        ("8", "Validated payloads are rendered to XML (Jinja2 templates).",
         "Deterministic, diffable, byte-stable output."),
        ("9", "Every XML is validated against the official FEWS XSDs.",
         "If any file fails, the build stops with a clear error."),
        ("10", "Cross-file derivers fill in dependent pieces.",
         "Topology, descriptors, sa_global.Properties — built from the rendered tree."),
        ("11", "Static assets are mirrored verbatim.",
         "Shapefile sidecars and binaries are copied without touching them."),
        ("12", "Output: a FEWS-ready folder tree.",
         "~50–135 XML files, 100% XSD-valid, ready to drop into Delft-FEWS."),
    ]

    y = 17.6
    step_h = 1.35
    for num, headline, detail in steps:
        # Number circle
        ax.text(
            0.6, y - 0.45, num,
            ha="center", va="center",
            fontsize=18, fontweight="bold", color="#0b1726",
        )
        # Headline
        ax.text(
            1.4, y - 0.15, headline,
            ha="left", va="top",
            fontsize=12, fontweight="bold", color="#0b1726",
        )
        # Detail
        ax.text(
            1.4, y - 0.55, detail,
            ha="left", va="top",
            fontsize=10, color="#3b4a5a", style="italic",
        )
        # Separator
        ax.plot([0.3, 9.7], [y - 1.05, y - 1.05],
                color="#e2e8f0", lw=0.6, zorder=0)
        y -= step_h

    pdf.savefig(fig, bbox_inches="tight", pad_inches=0.3)
    plt.close(fig)


# ---------------------------------------------------------------------------
# Page 4 — tasks of the LLM
# ---------------------------------------------------------------------------

def draw_llm_tasks_page(pdf: PdfPages) -> None:
    fig, ax = plt.subplots(figsize=(11, 10))
    ax.set_xlim(0, 10)
    ax.set_ylim(0, 13)
    ax.set_aspect("equal")
    ax.axis("off")

    ax.text(
        5, 12.3, "What the LLM actually does",
        ha="center", va="center",
        fontsize=20, fontweight="bold", color="#0b1726",
    )
    ax.text(
        5, 11.75,
        "page 4  ·  three small jobs, each with a typed contract",
        ha="center", va="center",
        fontsize=10, color="#94a3b8", style="italic",
    )

    # ─── Job 1 ───────────────────────────────────────────────────────
    add_box(
        ax, 0.5, 9.0, 9.0, 2.0,
        title="① Intent classification",
        body=(
            "When:    once, on the configurator's first message.\n"
            "Input:   the prose + extracted regex facts.\n"
            "Output:  one of  {build_forecasting_project, build_data_import_only,\n"
            "                  build_basin_model_only}  + supporting entities.\n"
            "Fallback: heuristic from filled slots if the LLM picks an invalid label."
        ),
        fill="#dbeafe", edge="#1e40af",
        title_size=13, body_size=10,
    )

    # ─── Job 2 ───────────────────────────────────────────────────────
    add_box(
        ax, 0.5, 6.5, 9.0, 2.0,
        title="② Reply composition",
        body=(
            "When:    every turn.\n"
            "Input:   user message + KNOWN/UNKNOWN slot split + next question.\n"
            "Output:  1–3 sentence reply, plain English, no JSON.\n"
            "Guardrail: anti-fabrication prompt — values under UNKNOWN must\n"
            "          not appear in the reply."
        ),
        fill="#bbf7d0", edge="#166534",
        title_size=13, body_size=10,
    )

    # ─── Job 3 ───────────────────────────────────────────────────────
    add_box(
        ax, 0.5, 4.0, 9.0, 2.0,
        title="③ Filter drafting",
        body=(
            "When:    once per build, after pattern expansion.\n"
            "Input:   ~28 moduleInstanceIds + parameterIds gathered from\n"
            "         the rendered XMLs.\n"
            "Output:  3–6 proposed filter groups for Filters.xml.\n"
            "Fallback: bundled standard filtersFile if output is malformed or\n"
            "          references unknown IDs."
        ),
        fill="#e9d5ff", edge="#6b21a8",
        title_size=13, body_size=10,
    )

    # ─── What the LLM does NOT do ────────────────────────────────────
    add_box(
        ax, 0.5, 0.7, 9.0, 2.7,
        title="What the LLM does NOT do",
        body=(
            "✗ Write XML directly.        Every XML comes from a Jinja template.\n"
            "✗ Pick pattern instances.    A deterministic resolver does that.\n"
            "✗ Validate against XSDs.     lxml does that, in Python.\n"
            "✗ Author project policy.     Configurator does that via /edit or copy-paste.\n"
            "✗ Touch the /edit walker.    The walker is pure schema introspection.\n"
            "\n"
            "Three gated, narrow LLM calls. Outside them, the pipeline is deterministic."
        ),
        fill="#fee2e2", edge="#7f1d1d",
        title_size=12, body_size=10,
    )

    pdf.savefig(fig, bbox_inches="tight", pad_inches=0.3)
    plt.close(fig)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def render_pdf(out_pdf: Path) -> None:
    out_pdf.parent.mkdir(parents=True, exist_ok=True)
    with PdfPages(out_pdf) as pdf:
        draw_flowchart(pdf)
        draw_pattern_role_page(pdf)
        draw_steps_page(pdf)
        draw_llm_tasks_page(pdf)
    print(f"Wrote {out_pdf}  (4 pages)")


if __name__ == "__main__":
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("docs/ux-flow.pdf")
    render_pdf(out)
