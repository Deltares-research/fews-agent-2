"""Spec picker — let the user choose which wizard specs to run.

The wizard registry holds 200+ auto-derived specs; running every one
in a single session is regression-test territory, not user UX. The
picker turns that into a friendly "what does your project actually
need?" prompt by:

  - Grouping registered specs by FEWS top-level config directory
    (Region / Module / Display / System / ... — derived from the
    GeneratorSpec's output_relpath).
  - Offering curated presets ("essentials" = the must-have core).
  - Accepting a comma-separated mix of preset names, category names,
    and exact spec names in one prompt.

The picker is purely advisory — the rest of the wizard stack works
the same on a 5-spec selection as on a 109-spec one. ``replay.py``'s
``--specs`` flag and the future ``build_project.py`` runner both
consume the picker's output.

The picker has no LLM dependency — it's all dict lookups and
``rich.prompt.Prompt.ask``. Safe to run in any environment.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePath
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from rich.console import Console


# Map of FEWS top-level config dir → short, human-friendly category
# slug used in the picker UI. Anything outside this map falls into
# "other".
_DIR_TO_CATEGORY: dict[str, str] = {
    "RegionConfigFiles": "region",
    "ModuleConfigFiles": "module",
    "DisplayConfigFiles": "display",
    "SystemConfigFiles": "system",
    "WorkflowFiles": "workflow",
    "IdMapFiles": "idmap",
    "RootConfigFiles": "root",
    "UnitConversionsFiles": "units",
    "ModuleParFiles": "modulepar",
}


# Curated presets — names referenced here that aren't actually
# registered in WIZARD_SPECS are silently dropped at expansion time,
# so it's safe to list aspirational names.
PRESETS: dict[str, list[str]] = {
    # Smallest set that produces a recognisable FEWS project skeleton.
    # Locations + Parameters anchor every other config; the descriptor
    # files and module-instance/workflow descriptors plug everything
    # together.
    "essentials": [
        "locations",
        "parameters",
        "qualifiers",
        "id_map_descriptors",
        "moduleInstanceDescriptors",
        "workflowDescriptors",
    ],
    # Common region-level files plus essentials.
    "minimal": [
        "locations",
        "parameters",
        "qualifiers",
        "id_map_descriptors",
        "moduleInstanceDescriptors",
        "workflowDescriptors",
        "thresholds",
        "thresholdValueSets",
        "thresholdWarningLevels",
        "topology",
    ],
}


@dataclass
class SpecCategory:
    """Categorised registry entry surfaced in the picker UI."""

    name: str
    category: str
    output_relpath: str  # forward-slash form, for stable display


def categorize_specs() -> list[SpecCategory]:
    """Walk the SPECS + WIZARD_SPECS registries, return categorised rows.

    Specs without a registered wizard entry are filtered out — the
    picker can't drive them. The returned list is sorted by
    ``(category, name)``.
    """
    from fews_agent.generators import SPECS

    from .wizard import WIZARD_SPECS

    rows: list[SpecCategory] = []
    seen: set[str] = set()
    for gs in SPECS:
        if gs.name in seen:
            continue
        seen.add(gs.name)
        if gs.name not in WIZARD_SPECS:
            continue
        relpath = PurePath(str(gs.output_relpath)).as_posix()
        top = relpath.split("/", 1)[0] if "/" in relpath else relpath
        category = _DIR_TO_CATEGORY.get(top, "other")
        rows.append(
            SpecCategory(
                name=gs.name, category=category, output_relpath=relpath
            )
        )
    rows.sort(key=lambda r: (r.category, r.name))
    return rows


def by_category(rows: list[SpecCategory]) -> dict[str, list[SpecCategory]]:
    """Group categorised rows for display."""
    grouped: dict[str, list[SpecCategory]] = {}
    for r in rows:
        grouped.setdefault(r.category, []).append(r)
    return grouped


# ---------------------------------------------------------------------------
# Selection expansion
# ---------------------------------------------------------------------------


def expand_selection(
    text: str,
    rows: list[SpecCategory],
    presets: dict[str, list[str]] = PRESETS,
) -> tuple[list[str], list[str]]:
    """Resolve user input into a concrete spec name list.

    Accepts a comma-separated mix of:
      - preset names (``essentials``, ``minimal``)
      - category slugs (``region``, ``module``, ...)
      - exact spec names (``locations``, ``parameters``)
      - the special token ``all``

    Returns ``(selected, unknown)`` where ``selected`` is dedup'd in
    ``rows`` order and ``unknown`` lists tokens that matched neither a
    preset, category, nor a registered spec.
    """
    available_names = {r.name for r in rows}
    by_cat = by_category(rows)

    chosen: list[str] = []
    seen: set[str] = set()
    unknown: list[str] = []

    def _add(name: str) -> None:
        if name in available_names and name not in seen:
            chosen.append(name)
            seen.add(name)

    for raw in text.replace("\n", ",").split(","):
        token = raw.strip()
        if not token:
            continue
        low = token.lower()
        if low == "all":
            for r in rows:
                _add(r.name)
            continue
        if low in presets:
            for n in presets[low]:
                _add(n)
            continue
        if low in by_cat:
            for r in by_cat[low]:
                _add(r.name)
            continue
        if token in available_names:
            _add(token)
            continue
        # Case-insensitive exact match against spec names — protects
        # users from worrying about camelCase.
        ci_match = next(
            (r.name for r in rows if r.name.lower() == low), None
        )
        if ci_match:
            _add(ci_match)
            continue
        unknown.append(token)

    # Re-order chosen so it follows ``rows`` order (category, name).
    order = {r.name: i for i, r in enumerate(rows)}
    chosen.sort(key=lambda n: order.get(n, 1_000_000))
    return chosen, unknown


# ---------------------------------------------------------------------------
# Interactive picker
# ---------------------------------------------------------------------------


def render_summary(rows: list[SpecCategory], console: Console) -> None:
    """Print the categorised summary used at the top of the picker."""
    from rich.table import Table

    grouped = by_category(rows)
    table = Table(
        title=f"Registered wizard specs ({len(rows)} total)",
        show_lines=False,
        header_style="bold",
    )
    table.add_column("category", style="cyan")
    table.add_column("count", justify="right")
    table.add_column("examples", overflow="fold")
    for cat in sorted(grouped):
        items = grouped[cat]
        examples = ", ".join(r.name for r in items[:5])
        if len(items) > 5:
            examples += f", … (+{len(items) - 5} more)"
        table.add_row(cat, str(len(items)), examples)
    console.print(table)


def pick_specs_interactive(
    *,
    rows: list[SpecCategory] | None = None,
    presets: dict[str, list[str]] = PRESETS,
    console: Console | None = None,
    default: str = "essentials",
) -> list[str]:
    """One-prompt picker. Returns selected spec names in registry order.

    Loops until the user provides at least one valid selection or
    types ``cancel`` (returns ``[]``). The default response (empty
    input) maps to ``default`` — usually ``"essentials"``.
    """
    from rich.console import Console as _Console
    from rich.prompt import Prompt

    if console is None:
        console = _Console()
    if rows is None:
        rows = categorize_specs()

    render_summary(rows, console)

    preset_summary = ", ".join(
        f"[bold]{name}[/bold] ({len(specs)})" for name, specs in presets.items()
    )
    console.print(
        "\n[bold]Presets:[/bold] " + preset_summary
        + " · [bold]all[/bold] (every spec)"
    )
    console.print(
        "[dim]Enter a comma-separated mix of preset names "
        "(e.g. essentials), category names (region, module), or exact "
        "spec names. Type 'cancel' to abort.[/dim]"
    )

    while True:
        text = Prompt.ask(
            "Selection",
            default=default,
        )
        if text is None:
            text = ""
        if text.strip().lower() in {"cancel", "/cancel", "quit", "q"}:
            return []
        if not text.strip():
            text = default

        chosen, unknown = expand_selection(text, rows, presets)
        if unknown:
            console.print(
                f"[yellow]Ignored unknown tokens: "
                f"{', '.join(unknown)}[/yellow]"
            )
        if not chosen:
            console.print(
                "[red]Nothing matched — try again, or 'cancel' to abort.[/red]"
            )
            continue

        console.print(
            f"\n[bold]Selected {len(chosen)} spec(s):[/bold]"
        )
        for name in chosen:
            console.print(f"  • {name}")
        return chosen


__all__ = [
    "PRESETS",
    "SpecCategory",
    "by_category",
    "categorize_specs",
    "expand_selection",
    "pick_specs_interactive",
    "render_summary",
]
