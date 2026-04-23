"""Rich-driven wizard for thematic field entry.

Deterministic sibling to the LLM chat loop. Walks the user through a
registered sequence of `WizardGroup`s for a given spec — no model
required. Writes results through the same tool hooks as the chat
(`upsert_location`), so wizard + chat entries land in the same
`input.json` and the TUI always sees one source of truth.

Group design (for Locations; extend the registry for other specs):
  1. Identity        — id, name                                 (required)
  2. Coordinates     — x, y, z (z optional)                     (required)
  3. Display         — shortName, description                   (optional)
  4. Hierarchy       — parentLocationId, relation               (optional)
  5. Attributes      — key/value pairs                          (optional, repeating)

File-level fields like `geoDatum` are elicited once via
`run_file_level_wizard` before the per-item loop.

Control keys:
  /back   — return to previous group (drops its entries)
  /cancel — abort the whole wizard, persist nothing
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any, Literal

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm, Prompt
from rich.table import Table


FieldKind = Literal["scalar", "decimal", "enum", "ref", "bool"]


@dataclass
class WizardField:
    path: str              # JSON path under the item (e.g. "id", "x", "parentLocationId")
    prompt: str            # What the human sees
    kind: FieldKind = "scalar"
    optional: bool = False
    allowed_values: list[str] | None = None
    ref_source: str | None = None  # Key under project_data to pull choices from, e.g. "locations.location[].id"


@dataclass
class WizardGroup:
    name: str
    description: str
    fields: list[WizardField]
    required: bool = True


# --- registry ----------------------------------------------------------

LOCATIONS_GROUPS: list[WizardGroup] = [
    WizardGroup(
        name="Identity",
        description="Unique id and a human-friendly name.",
        required=True,
        fields=[
            WizardField("id", "Location id (unique, no spaces)"),
            WizardField("name", "Display name"),
        ],
    ),
    WizardGroup(
        name="Coordinates",
        description="Geographic position. x = longitude (or projected x), y = latitude (or projected y).",
        required=True,
        fields=[
            WizardField("x", "x (longitude)", kind="decimal"),
            WizardField("y", "y (latitude)", kind="decimal"),
            WizardField("z", "z (elevation, optional)", kind="decimal", optional=True),
        ],
    ),
    WizardGroup(
        name="Display",
        description="Short labels and descriptions shown in the UI.",
        required=False,
        fields=[
            WizardField("shortName", "Short name (optional)", optional=True),
            WizardField("description", "Description (optional)", optional=True),
        ],
    ),
    WizardGroup(
        name="Hierarchy",
        description="Optional parent location and relation label.",
        required=False,
        fields=[
            WizardField(
                "parentLocationId",
                "Parent location id (optional)",
                kind="ref",
                optional=True,
                ref_source="locations.location[].id",
            ),
            WizardField("relation", "Relation label (optional)", optional=True),
        ],
    ),
]

WIZARDS: dict[str, list[WizardGroup]] = {
    "locations": LOCATIONS_GROUPS,
}


# --- runner ------------------------------------------------------------


class _WizardAbort(Exception):
    """Raised internally when the user types /cancel."""


def _validate_decimal(value: str) -> str:
    """Accept the raw string if it parses as Decimal; reject garbage.

    We keep the raw string (not the Decimal) so source digits are
    preserved through the generator's `_xmlstr` formatting — same rule
    the existing pipeline uses for C14N equivalence.
    """
    try:
        Decimal(value)
    except InvalidOperation as exc:
        raise ValueError(f"not a number: {value!r}") from exc
    return value


def _resolve_ref_choices(ref_source: str | None, project_data: dict[str, Any]) -> list[str]:
    """Walk a ref_source like 'locations.location[].id' into project_data."""
    if not ref_source:
        return []
    parts = ref_source.split(".")
    cur: Any = project_data
    choices: list[str] = []
    for i, part in enumerate(parts):
        if "[]" in part:
            name, _ = part.split("[]", 1)
            items = cur.get(name, []) if isinstance(cur, dict) else []
            if not isinstance(items, list):
                return []
            remainder = parts[i + 1:]
            leaf = remainder[0] if remainder else None
            for item in items:
                val = item.get(leaf) if leaf else item
                if isinstance(val, (str, int, float)) and str(val).strip():
                    choices.append(str(val))
            return choices
        if isinstance(cur, dict):
            cur = cur.get(part)
        else:
            return []
    return choices


def _ask_field(field: WizardField, ctx: Any, console: Console) -> str | None:
    """Prompt a single field with kind-aware validation."""
    default = "" if field.optional else None
    while True:
        if field.kind == "ref":
            choices = _resolve_ref_choices(field.ref_source, ctx.project_data)
            choices = sorted(set(choices))
            if choices:
                table = Table(title="Available choices", show_header=False, box=None, padding=(0, 2))
                for c in choices:
                    table.add_row(c)
                console.print(table)
            answer = Prompt.ask(
                f"[bold]{field.prompt}[/bold]"
                + (f" (or leave empty to skip)" if field.optional else ""),
                default=default,
            )
        elif field.kind == "enum" and field.allowed_values:
            answer = Prompt.ask(
                f"[bold]{field.prompt}[/bold]",
                choices=field.allowed_values,
                default=default,
            )
        elif field.kind == "bool":
            answer = "true" if Confirm.ask(f"[bold]{field.prompt}[/bold]", default=False) else "false"
        else:
            answer = Prompt.ask(
                f"[bold]{field.prompt}[/bold]"
                + (" (optional)" if field.optional else ""),
                default=default,
            )

        if answer is None:
            answer = ""
        answer = answer.strip()
        if answer.lower() in {"/back", "/cancel"}:
            return answer.lower()

        if not answer:
            if field.optional:
                return None
            console.print("[red]This field is required.[/red]")
            continue

        if field.kind == "decimal":
            try:
                _validate_decimal(answer)
            except ValueError as exc:
                console.print(f"[red]{exc}[/red]")
                continue
        return answer


def run_location_wizard(ctx: Any, console: Console) -> dict[str, Any] | None:
    """Walk the 5 Locations groups for one new/edited location.

    Returns the new location dict on success (also written to project_data
    via upsert_location). Returns None on /cancel.
    """
    from .tools import project_tools  # avoid import cycle at module load

    groups = WIZARDS["locations"]
    result: dict[str, Any] = {}
    g_idx = 0
    while g_idx < len(groups):
        group = groups[g_idx]
        console.print(Panel(
            f"[bold]{group.name}[/bold] — {group.description}"
            + ("" if group.required else "\n[dim](optional group — you can skip)[/dim]"),
            border_style="cyan" if group.required else "yellow",
        ))

        if not group.required:
            if not Confirm.ask(f"Fill in '{group.name}'?", default=False):
                g_idx += 1
                continue

        group_values: dict[str, str] = {}
        aborted = False
        backed = False
        for field_ in group.fields:
            answer = _ask_field(field_, ctx, console)
            if answer == "/cancel":
                console.print("[dim]Wizard cancelled. Nothing saved.[/dim]")
                return None
            if answer == "/back":
                if g_idx == 0:
                    console.print("[dim]Already at the first group; /back ignored.[/dim]")
                    continue
                backed = True
                break
            if answer is not None:
                group_values[field_.path] = answer
        if aborted:
            continue
        if backed:
            # drop any provisional values from the previous (current) group
            for f in group.fields:
                result.pop(f.path, None)
            g_idx -= 1
            continue
        result.update(group_values)
        g_idx += 1

    # Attributes as a tiny repeating sub-loop (handled outside the normal groups
    # because it's a list, not scalars).
    console.print(Panel(
        "[bold]Attributes[/bold] — key/value pairs attached to the location.\n"
        "[dim](optional; press enter on the key to finish)[/dim]",
        border_style="yellow",
    ))
    attrs: list[dict[str, str]] = []
    while True:
        key = Prompt.ask("attribute key (enter to finish)", default="")
        if not key.strip():
            break
        value = Prompt.ask(f"attribute value for [bold]{key}[/bold]", default="")
        attrs.append({"key": key.strip(), "value": value})
    if attrs:
        result["attribute"] = attrs

    # Persist via the shared upsert tool — same path the LLM uses.
    outcome = project_tools.upsert_location(location=result, ctx=ctx)
    console.print(
        f"[green]✓[/green] Location [bold]{result.get('id')}[/bold] "
        f"{outcome.get('action', 'saved')} — {outcome.get('count')} total."
    )
    return result


def run_file_level_wizard(spec_name: str, ctx: Any, console: Console) -> None:
    """Ask once for file-level fields (currently: geoDatum for Locations)."""
    if spec_name != "locations":
        return
    locations = ctx.project_data.setdefault("locations", {})
    if locations.get("geoDatum"):
        return
    console.print(Panel(
        "[bold]File setup[/bold] — needs a geographic datum (projection).",
        border_style="cyan",
    ))
    datum = Prompt.ask("geoDatum", default="WGS 1984")
    locations["geoDatum"] = datum
    locations.setdefault("location", [])
    ctx.store.save(ctx.project_name, ctx.project_data)
    console.print(f"[green]✓[/green] geoDatum set to [bold]{datum}[/bold].")


def run_wizard(spec_name: str, ctx: Any, console: Console) -> None:
    """Top-level wizard entry used by the TUI menu."""
    if spec_name not in WIZARDS:
        console.print(f"[yellow]No wizard registered for spec {spec_name!r} yet.[/yellow]")
        return
    run_file_level_wizard(spec_name, ctx, console)
    while True:
        run_location_wizard(ctx, console)
        if not Confirm.ask("Add another location?", default=False):
            break
