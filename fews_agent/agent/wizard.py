"""Rich-driven wizard for thematic field entry.

Deterministic sibling to the LLM chat loop. Walks the user through a
registered ``WizardSpec`` for any spec the registry supports — no model
required for the flow itself, though an optional ``provider`` enables
LLM-backed bulk parsing (one natural-language ask per item, parser
extracts structured fields).

Group design (Locations example; same shape works for other specs):
  1. Identity        — id, name                                 (required)
  2. Coordinates     — x, y, z (z optional)                     (required)
  3. Display         — shortName, description                   (optional)
  4. Hierarchy       — parentLocationId, relation               (optional)
  5. Attributes      — key/value pairs                          (optional, repeating)

File-level fields (e.g. Locations.geoDatum) live on the ``WizardSpec``
and are elicited once before the per-item loop.

To add a new spec:
  1. Define its ``WizardField``s + ``WizardGroup``s.
  2. Register a ``WizardSpec`` in ``WIZARD_SPECS``.
  3. Done — ``run_wizard(spec_name, ...)`` dispatches generically.

Control keys:
  /back   — return to previous group (drops its entries; field-by-field mode only)
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


@dataclass
class FileLevelSetter:
    """A single file-level field elicited once before the per-item loop.

    Stored at ``project_data[input_key][field]``. Skipped on subsequent
    runs if a value is already present.
    """

    field: str
    prompt: str
    default: str | None = None
    required: bool = True


@dataclass
class WizardSpec:
    """All metadata needed to drive a wizard for one FEWS spec.

    The registry (``WIZARD_SPECS``) maps spec names to instances of this
    class. The runner dispatches generically — no per-spec branches in
    ``run_wizard``.
    """

    name: str                              # SPECS registry key, e.g. "locations"
    input_key: str                         # project_data key, usually == name
    item_label: str                        # singular noun for prompts: "location"
    item_field: str                        # repeating-list key in state: "location"
    file_level: list[FileLevelSetter] = field(default_factory=list)
    item_groups: list[WizardGroup] = field(default_factory=list)
    bulk_prompt: str | None = None
    supports_attributes: bool = False      # tiny attribute (k/v) sub-loop after each item

    @property
    def bulk_fields(self) -> list[WizardField]:
        """All fields across all groups, used for the bulk-ask path."""
        return [f for g in self.item_groups for f in g.fields]


# ---------------------------------------------------------------------------
# Registry — add new specs here.
# ---------------------------------------------------------------------------

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


LOCATIONS_SPEC = WizardSpec(
    name="locations",
    input_key="locations",
    item_label="location",
    item_field="location",
    file_level=[
        FileLevelSetter(
            field="geoDatum",
            prompt="geoDatum (geographic datum / projection)",
            default="WGS 1984",
            required=True,
        ),
    ],
    item_groups=LOCATIONS_GROUPS,
    bulk_prompt=(
        "Tell me about a location. Include any of: id, name, x, y, "
        "z (elevation, optional), shortName, description, "
        "parentLocationId, relation. You can answer naturally — e.g. "
        '"id RDPS, name Regional Deterministic Prediction System (10 km), '
        'shortName RDPS, x -142.8968, y 18.1429".'
    ),
    supports_attributes=True,
)


# --- IdMapDescriptors --------------------------------------------------
#
# Tiny spec used to demonstrate the wizard's spec-genericity. Items have
# id (required) + optional name/description. No file-level fields.

ID_MAP_DESCRIPTORS_GROUPS: list[WizardGroup] = [
    WizardGroup(
        name="Identity",
        description="Unique idMapDescriptor id and optional metadata.",
        required=True,
        fields=[
            WizardField("id", "IdMap descriptor id (unique)"),
            WizardField("name", "Display name (optional)", optional=True),
            WizardField(
                "description",
                "Description (optional)",
                optional=True,
            ),
        ],
    ),
]


ID_MAP_DESCRIPTORS_SPEC = WizardSpec(
    name="id_map_descriptors",
    input_key="idMapDescriptors",
    item_label="idMapDescriptor",
    item_field="idMapDescriptor",
    file_level=[],
    item_groups=ID_MAP_DESCRIPTORS_GROUPS,
    bulk_prompt=(
        "Tell me about an idMapDescriptor. Include the id (required) and "
        "optional name and description. e.g. \"id IdImportObs, name "
        "Observed imports, description Maps external observation ids to "
        "FEWS internal ids.\""
    ),
    supports_attributes=False,
)


WIZARD_SPECS: dict[str, WizardSpec] = {
    "locations": LOCATIONS_SPEC,
    "id_map_descriptors": ID_MAP_DESCRIPTORS_SPEC,
}

# Back-compat alias for any caller that still expects a list of groups.
WIZARDS: dict[str, list[WizardGroup]] = {
    name: spec.item_groups for name, spec in WIZARD_SPECS.items()
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Generic state writes — no per-spec branches in the wizard runner.
# ---------------------------------------------------------------------------


def _ensure_bucket(spec: WizardSpec, ctx: Any) -> dict[str, Any]:
    bucket = ctx.project_data.setdefault(spec.input_key, {})
    bucket.setdefault(spec.item_field, [])
    return bucket


def _generic_set_field(spec: WizardSpec, field_: str, value: str, ctx: Any) -> None:
    bucket = _ensure_bucket(spec, ctx)
    bucket[field_] = value
    ctx.store.save(ctx.project_name, ctx.project_data)


def _generic_upsert(spec: WizardSpec, item: dict[str, Any], ctx: Any) -> dict[str, Any]:
    """Insert-or-update by ``id``; persists synchronously."""
    if "id" not in item or not str(item.get("id", "")).strip():
        return {"error": f"{spec.item_label}.id is required"}
    bucket = _ensure_bucket(spec, ctx)
    items = bucket[spec.item_field]
    target_id = item["id"]
    for i, existing in enumerate(items):
        if existing.get("id") == target_id:
            items[i] = {**existing, **item}
            ctx.store.save(ctx.project_name, ctx.project_data)
            return {"action": "updated", "id": target_id, "count": len(items)}
    items.append(item)
    ctx.store.save(ctx.project_name, ctx.project_data)
    return {"action": "inserted", "id": target_id, "count": len(items)}


# ---------------------------------------------------------------------------
# Bulk and field-by-field item flows
# ---------------------------------------------------------------------------


def _bulk_ask_item(
    spec: WizardSpec,
    ctx: Any,
    console: Console,
    provider: Any,
    on_parse: Any | None = None,
) -> dict[str, Any] | None:
    """Single-shot natural-language ask for a whole item.

    Returns the item dict on success, or None on /cancel. If the parser
    couldn't extract a required field, the wizard re-prompts that one
    field directly (per-field fallback).
    """
    from .nl_parser import parse_group  # local import — avoid cycle

    console.print(Panel(
        f"[bold]New {spec.item_label}[/bold] — answer in your own words.",
        border_style="cyan",
    ))
    raw = Prompt.ask(spec.bulk_prompt or "Tell me about it.", default="")
    if raw is None:
        raw = ""
    if raw.strip().lower() == "/cancel":
        console.print("[dim]Wizard cancelled. Nothing saved.[/dim]")
        return None

    fields = spec.bulk_fields
    parsed = parse_group(
        raw,
        fields,
        provider,
        group_label=f"A {spec.item_label} for the {spec.name} spec",
    )
    if on_parse is not None:
        try:
            on_parse(parsed)
        except Exception:  # noqa: BLE001
            pass
    if parsed.error:
        console.print(
            f"[yellow]Parser failed ({parsed.error}); falling back to "
            f"field-by-field.[/yellow]"
        )

    result: dict[str, Any] = {}
    by_path = {f.path: f for f in fields}
    for path, value in parsed.values.items():
        f = by_path.get(path)
        if f is None:
            continue
        if f.kind == "decimal":
            try:
                _validate_decimal(value)
            except ValueError as exc:
                console.print(
                    f"[yellow]parser produced invalid {f.path}={value!r} "
                    f"({exc}); will re-ask.[/yellow]"
                )
                continue
        result[path] = value

    # Per-field fallback for any required field the parser didn't fill.
    for f in fields:
        if f.optional or f.path in result:
            continue
        answer = _ask_field(f, ctx, console)
        if answer == "/cancel":
            console.print("[dim]Wizard cancelled. Nothing saved.[/dim]")
            return None
        if answer == "/back":
            console.print("[dim]/back not supported in bulk mode; treating as cancel of this item.[/dim]")
            return None
        if answer is not None:
            result[f.path] = answer
    return result


def _field_by_field_ask_item(
    spec: WizardSpec,
    ctx: Any,
    console: Console,
) -> dict[str, Any] | None:
    """Original group-walking flow (no LLM). Used when no provider is given."""
    groups = spec.item_groups
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
        if backed:
            for f in group.fields:
                result.pop(f.path, None)
            g_idx -= 1
            continue
        result.update(group_values)
        g_idx += 1
    return result


# ---------------------------------------------------------------------------
# Public entry points
# ---------------------------------------------------------------------------


def run_item_wizard(
    spec: WizardSpec,
    ctx: Any,
    console: Console,
    provider: Any | None = None,
    on_parse: Any | None = None,
) -> dict[str, Any] | None:
    """Walk the wizard for one new/edited item.

    Returns the item dict on success (also written to project state via
    the generic upsert). Returns None on /cancel.
    """
    if provider is not None and hasattr(provider, "generate_json"):
        result = _bulk_ask_item(spec, ctx, console, provider, on_parse=on_parse)
    else:
        result = _field_by_field_ask_item(spec, ctx, console)
    if result is None:
        return None

    if spec.supports_attributes and Confirm.ask(
        f"Add any attributes (key/value pairs) to this {spec.item_label}?",
        default=False,
    ):
        attrs: list[dict[str, str]] = []
        while True:
            key = Prompt.ask("attribute key (enter to finish)", default="")
            if not key.strip():
                break
            value = Prompt.ask(
                f"attribute value for [bold]{key}[/bold]", default=""
            )
            attrs.append({"key": key.strip(), "value": value})
        if attrs:
            result["attribute"] = attrs

    outcome = _generic_upsert(spec, result, ctx)
    console.print(
        f"[green]✓[/green] {spec.item_label.capitalize()} "
        f"[bold]{result.get('id')}[/bold] "
        f"{outcome.get('action', 'saved')} — {outcome.get('count')} total."
    )
    return result


def run_file_level_wizard(spec: WizardSpec, ctx: Any, console: Console) -> None:
    """Ask once for each file-level field on the spec.

    Skips fields that already have a value in project state, so re-running
    the wizard on a half-filled project doesn't re-prompt.
    """
    if not spec.file_level:
        return
    bucket = _ensure_bucket(spec, ctx)
    pending = [s for s in spec.file_level if not bucket.get(s.field)]
    if not pending:
        return
    console.print(Panel(
        f"[bold]File setup[/bold] — {spec.name}: needs "
        f"{', '.join(s.field for s in pending)}.",
        border_style="cyan",
    ))
    for setter in pending:
        value = Prompt.ask(setter.prompt, default=setter.default)
        if value is None or not str(value).strip():
            if setter.required:
                console.print(f"[red]{setter.field} is required.[/red]")
                # Re-ask once; if still empty, give up gracefully.
                value = Prompt.ask(setter.prompt, default=setter.default)
            if not value:
                continue
        _generic_set_field(spec, setter.field, str(value).strip(), ctx)
        console.print(
            f"[green]✓[/green] {setter.field} set to "
            f"[bold]{value}[/bold]."
        )


def run_wizard(
    spec_name: str,
    ctx: Any,
    console: Console,
    provider: Any | None = None,
    on_parse: Any | None = None,
) -> None:
    """Top-level wizard entry. Dispatches generically via WIZARD_SPECS.

    If ``provider`` is given AND it implements ``generate_json``, the
    wizard uses LLM-backed bulk parsing for each item. Otherwise it
    walks field-by-field deterministically.

    ``on_parse`` is an optional callback receiving each ``ParseResult``;
    the replay runner uses it to capture token usage per parse call.
    """
    spec = WIZARD_SPECS.get(spec_name)
    if spec is None:
        console.print(
            f"[yellow]No wizard registered for spec {spec_name!r} yet. "
            f"Add a WizardSpec to WIZARD_SPECS in agent/wizard.py.[/yellow]"
        )
        return
    run_file_level_wizard(spec, ctx, console)
    while True:
        run_item_wizard(spec, ctx, console, provider=provider, on_parse=on_parse)
        if not Confirm.ask(f"Add another {spec.item_label}?", default=False):
            break


# ---------------------------------------------------------------------------
# Backwards-compatible aliases — legacy callers that referenced the
# Locations-specific helpers still work without changes.
# ---------------------------------------------------------------------------


def run_location_wizard(
    ctx: Any,
    console: Console,
    provider: Any | None = None,
    on_parse: Any | None = None,
) -> dict[str, Any] | None:
    """Backwards-compat shim for the original Locations-only entry point."""
    return run_item_wizard(
        LOCATIONS_SPEC, ctx, console, provider=provider, on_parse=on_parse
    )
