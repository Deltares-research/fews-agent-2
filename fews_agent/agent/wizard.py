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


FieldKind = Literal[
    "scalar",
    "decimal",
    "enum",
    "ref",
    "bool",
    "list_str",       # list of strings — natural-language: "a, b, c"
    "list_decimal",   # list of numeric strings (preserves source digits)
]


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
class WizardSection:
    """One repeating-item section within a ``WizardSpec``.

    A spec with multiple ``list[PydanticItem]`` fields at the root
    (e.g. ``Parameters`` carries both ``parameterGroup[]`` and
    ``parameter[]``) has multiple sections — each with its own bulk
    prompt, item shape, and ``add another?`` loop.
    """

    item_label: str                        # singular noun for prompts: "location"
    item_field: str                        # repeating-list key in state: "location"
    item_groups: list[WizardGroup] = field(default_factory=list)
    bulk_prompt: str | None = None
    supports_attributes: bool = False      # tiny attribute (k/v) sub-loop after each item

    @property
    def bulk_fields(self) -> list[WizardField]:
        """All fields across all groups, used for the bulk-ask path."""
        return [f for g in self.item_groups for f in g.fields]


@dataclass
class WizardSpec:
    """All metadata needed to drive a wizard for one FEWS spec.

    The registry (``WIZARD_SPECS``) maps spec names to instances of this
    class. The runner dispatches generically — no per-spec branches in
    ``run_wizard``.

    A spec has zero-or-more ``sections`` (one per repeating list field).
    File-level scalar fields are elicited once via ``file_level``
    setters before the section loops run. A spec with empty ``sections``
    (e.g. ``ModuleConfigProperties``) is wizard-friendly too — the
    runner just runs the file-level setters and exits.
    """

    name: str                              # SPECS registry key, e.g. "locations"
    input_key: str                         # project_data key, usually == name
    sections: list[WizardSection] = field(default_factory=list)
    file_level: list[FileLevelSetter] = field(default_factory=list)


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
    file_level=[
        FileLevelSetter(
            field="geoDatum",
            prompt="geoDatum (geographic datum / projection)",
            default="WGS 1984",
            required=True,
        ),
    ],
    sections=[
        WizardSection(
            item_label="location",
            item_field="location",
            item_groups=LOCATIONS_GROUPS,
            bulk_prompt=(
                "Tell me about a location. Include any of: id, name, x, y, "
                "z (elevation, optional), shortName, description, "
                "parentLocationId, relation. You can answer naturally — e.g. "
                '"id RDPS, name Regional Deterministic Prediction System (10 km), '
                'shortName RDPS, x -142.8968, y 18.1429".'
            ),
            supports_attributes=True,
        ),
    ],
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
    file_level=[],
    sections=[
        WizardSection(
            item_label="idMapDescriptor",
            item_field="idMapDescriptor",
            item_groups=ID_MAP_DESCRIPTORS_GROUPS,
            bulk_prompt=(
                "Tell me about an idMapDescriptor. Include the id (required) and "
                "optional name and description. e.g. \"id IdImportObs, name "
                "Observed imports, description Maps external observation ids to "
                "FEWS internal ids.\""
            ),
            supports_attributes=False,
        ),
    ],
)


WIZARD_SPECS: dict[str, WizardSpec] = {
    "locations": LOCATIONS_SPEC,
    "id_map_descriptors": ID_MAP_DESCRIPTORS_SPEC,
}


def _populate_auto_specs() -> dict[str, str]:
    """Walk the SPECS registry and auto-derive WizardSpec entries.

    Hand-authored entries above already populate ``WIZARD_SPECS``; the
    auto path only fills the rest. Result is a mapping
    ``{spec_name: outcome}`` (manual / auto / skipped:reason) — handy
    for the inspection CLI and as a debug log on import.
    """
    from .wizard_autoderive import auto_register_all

    status = auto_register_all(WIZARD_SPECS, overwrite=False)
    n_auto = sum(1 for v in status.values() if v == "auto")
    n_manual = sum(1 for v in status.values() if v == "manual")
    n_skipped = sum(1 for v in status.values() if v.startswith("skipped"))
    import logging as _logging
    _logging.getLogger(__name__).info(
        "wizard registry: %d total (%d manual, %d auto, %d skipped)",
        len(status),
        n_manual,
        n_auto,
        n_skipped,
    )
    return status


# Populated once at module load — adds auto-derived entries to
# WIZARD_SPECS without touching the hand-authored ones above.
AUTO_REGISTRATION_STATUS: dict[str, str] = _populate_auto_specs()


# Back-compat alias for callers that still expect ``WIZARDS[name]`` to
# return a flat list of groups for the spec's primary section.
WIZARDS: dict[str, list[WizardGroup]] = {
    name: (spec.sections[0].item_groups if spec.sections else [])
    for name, spec in WIZARD_SPECS.items()
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


def _unflatten(flat: dict[str, Any]) -> dict[str, Any]:
    """Turn ``{"a.b": 1, "a.c": 2, "x": 3}`` into ``{"a": {"b": 1, "c": 2}, "x": 3}``.

    Used to reconstruct nested Pydantic shapes from the wizard's flat
    dotted-path WizardFields. Only handles 1-level nesting (matches
    ``wizard_autoderive._flat_field``'s recursion cap).
    """
    out: dict[str, Any] = {}
    for k, v in flat.items():
        if "." not in k:
            out[k] = v
            continue
        parent, child = k.split(".", 1)
        existing = out.setdefault(parent, {})
        if not isinstance(existing, dict):
            # A flat value previously claimed this key — e.g. parent
            # also has a non-nested setter. Keep the dict by overwriting.
            existing = {}
            out[parent] = existing
        existing[child] = v
    return out


def _ensure_bucket(spec: WizardSpec, ctx: Any) -> dict[str, Any]:
    bucket = ctx.project_data.setdefault(spec.input_key, {})
    for section in spec.sections:
        bucket.setdefault(section.item_field, [])
    return bucket


def _generic_set_field(spec: WizardSpec, field_: str, value: str, ctx: Any) -> None:
    """Set a single file-level field (or a nested leaf via ``parent.child``).

    Unflattens dotted paths so a nested setter writes into a child
    dict rather than at the top of the bucket.
    """
    bucket = _ensure_bucket(spec, ctx)
    if "." in field_:
        parent, child = field_.split(".", 1)
        target = bucket.setdefault(parent, {})
        if not isinstance(target, dict):
            target = {}
            bucket[parent] = target
        target[child] = value
    else:
        bucket[field_] = value
    ctx.store.save(ctx.project_name, ctx.project_data)


def _generic_upsert(
    spec: WizardSpec,
    section: WizardSection,
    item: dict[str, Any],
    ctx: Any,
) -> dict[str, Any]:
    """Insert-or-update by ``id``; persists synchronously.

    The ``item`` dict may carry dotted-path keys produced by the
    auto-derived 1-level-nested flattening; we unflatten before saving
    so the resulting state matches the Pydantic model's shape.
    """
    item = _unflatten(item)
    if "id" not in item or not str(item.get("id", "")).strip():
        return {"error": f"{section.item_label}.id is required"}
    bucket = _ensure_bucket(spec, ctx)
    items = bucket.setdefault(section.item_field, [])
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
    section: WizardSection,
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
        f"[bold]New {section.item_label}[/bold] — answer in your own words.",
        border_style="cyan",
    ))
    raw = Prompt.ask(section.bulk_prompt or "Tell me about it.", default="")
    if raw is None:
        raw = ""
    raw_lower = raw.strip().lower()
    # Sentinel answers to exit a section without inserting an item.
    # Useful for optional sections (e.g. csvFile) where the user has
    # nothing to add. The empty default also lands here.
    if not raw_lower or raw_lower in {"/cancel", "skip", "none", "no"}:
        console.print(
            f"[dim]No {section.item_label} to add.[/dim]"
        )
        return None

    fields = section.bulk_fields
    parsed = parse_group(
        raw,
        fields,
        provider,
        group_label=f"A {section.item_label} for the {spec.name} spec",
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
        elif f.kind == "list_decimal":
            if not isinstance(value, list):
                continue
            bad = False
            for v in value:
                try:
                    _validate_decimal(str(v))
                except ValueError:
                    bad = True
                    break
            if bad:
                console.print(
                    f"[yellow]parser produced invalid {f.path}={value!r}; will re-ask.[/yellow]"
                )
                continue
        elif f.kind == "list_str":
            if not isinstance(value, list):
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
    section: WizardSection,
    ctx: Any,
    console: Console,
) -> dict[str, Any] | None:
    """Original group-walking flow (no LLM). Used when no provider is given."""
    groups = section.item_groups
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


_BULK_CHUNK_MAX_ITEMS = 8


def _split_bulk_chunks(text: str, max_per_chunk: int = _BULK_CHUNK_MAX_ITEMS) -> list[str]:
    """Split a multi-item bulk reply into balanced chunks.

    Lines starting with ``- `` are item boundaries; other lines are
    treated as continuations of the previous item. Replies with
    ``<= max_per_chunk`` items return a single chunk (no extra LLM cost).

    For longer replies, items are spread across ``ceil(N/max)`` chunks
    of roughly equal size — e.g. 10 items at max=8 splits 5+5 (not 8+2),
    keeping each parser call small and balanced.

    Why chunk: a 7B-class parser model occasionally drops one item from
    a 15+ item bulk. Splitting keeps each parse call small and reliable
    without adding any user-facing prompts.
    """
    items: list[list[str]] = []
    for line in text.splitlines():
        if line.lstrip().startswith("- "):
            items.append([line])
        elif items:
            items[-1].append(line)
        else:
            items.append([line])
    n = len(items)
    if n <= max_per_chunk:
        return [text]
    n_chunks = (n + max_per_chunk - 1) // max_per_chunk
    chunk_size = (n + n_chunks - 1) // n_chunks
    chunks: list[str] = []
    for i in range(0, n, chunk_size):
        block = items[i:i + chunk_size]
        chunks.append("\n".join(line for item in block for line in item))
    return chunks


def _bulk_ask_section(
    spec: WizardSpec,
    section: WizardSection,
    ctx: Any,
    console: Console,
    provider: Any,
    on_parse: Any | None = None,
) -> list[dict[str, Any]] | None:
    """One ask, N items per section. Returns the upserted item list.

    Returns:
      - ``[]`` if the user's reply is the skip sentinel (``""`` /
        ``skip`` / ``no`` / ``/cancel``) — the section ends silently.
      - ``None`` on a hard cancel signal (treated same as ``[]`` for now).
      - A list of upserted item dicts otherwise (one per item the
        parser extracted from the reply).

    Compared to the old per-item flow, this drops 2 prompts per item
    (the bulk-ask and the attributes confirm) and the per-item
    ``Add another?`` confirm too. The user instead types all the
    items (newline-separated, comma-separated, whatever) in one
    message and the parser splits them.

    Long replies (>8 items) are internally split into chunks of <= 8
    so a small parser model doesn't drop items. Chunking is invisible
    to the wizard's interaction count — still ONE ``Prompt.ask`` per
    section.
    """
    from .nl_parser import parse_group_list

    console.print(Panel(
        f"[bold]New {section.item_label}(s)[/bold] — describe one or "
        f"many in one reply (one per line works well).",
        border_style="cyan",
    ))
    raw = Prompt.ask(section.bulk_prompt or "Tell me about it.", default="")
    if raw is None:
        raw = ""
    raw_lower = raw.strip().lower()
    if not raw_lower or raw_lower in {"/cancel", "skip", "none", "no"}:
        console.print(f"[dim]No {section.item_label}s to add.[/dim]")
        return []

    fields = section.bulk_fields
    chunks = _split_bulk_chunks(raw)
    items_raw: list[dict[str, Any]] = []
    for ch_idx, chunk in enumerate(chunks, start=1):
        parsed = parse_group_list(
            chunk,
            fields,
            provider,
            group_label=f"{section.item_label}s for the {spec.name} spec",
        )
        if on_parse is not None:
            try:
                on_parse(parsed)
            except Exception:  # noqa: BLE001
                pass
        if parsed.error:
            console.print(
                f"[yellow]Parser failed on chunk {ch_idx}/{len(chunks)} "
                f"({parsed.error}).[/yellow]"
            )
            continue
        items_raw.extend(parsed.values.get("_items") or [])

    by_path = {f.path: f for f in fields}
    upserted: list[dict[str, Any]] = []
    for item_idx, raw_item in enumerate(items_raw, start=1):
        # Same kind validation as the single-item path.
        result: dict[str, Any] = {}
        for path, value in raw_item.items():
            f = by_path.get(path)
            if f is None:
                continue
            if f.kind == "decimal":
                try:
                    _validate_decimal(value)
                except ValueError as exc:
                    console.print(
                        f"[yellow]item {item_idx}: invalid {f.path}={value!r} "
                        f"({exc}); skipping field.[/yellow]"
                    )
                    continue
            elif f.kind == "list_decimal":
                if not isinstance(value, list):
                    continue
                try:
                    for v in value:
                        _validate_decimal(str(v))
                except ValueError:
                    continue
            elif f.kind == "list_str":
                if not isinstance(value, list):
                    continue
            result[path] = value

        # Required-field check: skip the item if anything required is
        # missing. Cleaner than per-field re-prompting in bulk mode.
        missing_required = [
            f.path for f in fields if not f.optional and f.path not in result
        ]
        if missing_required:
            console.print(
                f"[yellow]item {item_idx}: missing required fields "
                f"{missing_required}; skipping.[/yellow]"
            )
            continue

        outcome = _generic_upsert(spec, section, result, ctx)
        if "error" in outcome:
            console.print(
                f"[yellow]item {item_idx}: {outcome['error']}; skipping.[/yellow]"
            )
            continue
        console.print(
            f"[green]✓[/green] {section.item_label} "
            f"[bold]{result.get('id')}[/bold] "
            f"{outcome.get('action', 'saved')} — {outcome.get('count')} total."
        )
        upserted.append(result)
    return upserted


def run_item_wizard(
    spec: WizardSpec,
    section: WizardSection,
    ctx: Any,
    console: Console,
    provider: Any | None = None,
    on_parse: Any | None = None,
) -> dict[str, Any] | None:
    """Walk the wizard for one new/edited item in the given section.

    Returns the item dict on success (also written to project state via
    the generic upsert). Returns None on /cancel.
    """
    if provider is not None and hasattr(provider, "generate_json"):
        result = _bulk_ask_item(
            spec, section, ctx, console, provider, on_parse=on_parse
        )
    else:
        result = _field_by_field_ask_item(section, ctx, console)
    if result is None:
        return None

    if section.supports_attributes and Confirm.ask(
        f"Add any attributes (key/value pairs) to this {section.item_label}?",
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

    outcome = _generic_upsert(spec, section, result, ctx)
    console.print(
        f"[green]✓[/green] {section.item_label.capitalize()} "
        f"[bold]{result.get('id')}[/bold] "
        f"{outcome.get('action', 'saved')} — {outcome.get('count')} total."
    )
    return result


def _global_field_lookup(ctx: Any, field_name: str) -> str | None:
    """Find a non-empty value for ``field_name`` anywhere in project_data.

    Used for cross-phase reuse: e.g. ``geoDatum`` set during the
    Locations phase becomes the auto-fill for ``geoDatum`` in
    ModifierTypes / ThresholdValueSets / etc. without re-prompting.

    Walks the top level of every spec bucket. Doesn't recurse into
    item lists (different scope). Returns the first non-empty value
    found.
    """
    if not isinstance(ctx.project_data, dict):
        return None
    # Dotted-path setters carry their own nesting. Walk parent.child
    # paths inside each bucket the same way.
    parts = field_name.split(".")
    for spec_data in ctx.project_data.values():
        if not isinstance(spec_data, dict):
            continue
        cur: Any = spec_data
        ok = True
        for p in parts:
            if not isinstance(cur, dict) or p not in cur:
                ok = False
                break
            cur = cur[p]
        if ok and cur not in (None, "", [], {}):
            return cur
    return None


def run_file_level_wizard(spec: WizardSpec, ctx: Any, console: Console) -> None:
    """Ask once for each file-level field on the spec.

    Skips fields that already have a value in project state — both
    *within the same spec's bucket* (resume-on-rerun) and *across
    other specs' buckets* (cross-phase reuse: shared values like
    ``geoDatum`` / ``timeZone`` only get asked once per project).
    """
    if not spec.file_level:
        return
    bucket = _ensure_bucket(spec, ctx)

    # First pass: auto-fill any setter whose value already exists in
    # another phase's bucket. Skips the prompt entirely so the answer
    # queue (in the replay runner) stays in sync.
    for setter in spec.file_level:
        if bucket.get(setter.field):
            continue
        existing = _global_field_lookup(ctx, setter.field)
        if existing is not None:
            _generic_set_field(spec, setter.field, str(existing), ctx)
            console.print(
                f"[dim]✓ {setter.field} = {existing!r} (reused from "
                f"earlier phase)[/dim]"
            )

    # Now ask the user about anything still missing.
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

    Flow:
      1. Walk file-level setters (e.g. geoDatum) once.
      2. For each section, loop "describe one item" → upsert → "add another?"
         until the user says no, then move to the next section.

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
    has_provider = provider is not None and hasattr(provider, "generate_json")
    for section in spec.sections:
        if len(spec.sections) > 1:
            console.print(Panel(
                f"[bold]Section: {section.item_label}[/bold]",
                border_style="green",
            ))
        if has_provider:
            # Section-level multi-item bulk-ask: ONE prompt collects
            # every item the user wants in this section. The reply is
            # internally chunked + parsed if it has more than 8 items
            # (see ``_bulk_ask_section``), so fidelity holds without
            # extra user-facing prompts. Re-running the wizard for the
            # same spec is idempotent (upsert by id), so no
            # ``Add more?`` confirm is needed here.
            _bulk_ask_section(
                spec, section, ctx, console, provider, on_parse=on_parse,
            )
        else:
            # No provider — fall back to the deterministic field-by-field
            # walker (one item per outer iteration).
            while True:
                item = run_item_wizard(
                    spec, section, ctx, console,
                    provider=provider, on_parse=on_parse,
                )
                if item is None:
                    break
                if not Confirm.ask(
                    f"Add another {section.item_label}?", default=False
                ):
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
        LOCATIONS_SPEC,
        LOCATIONS_SPEC.sections[0],
        ctx,
        console,
        provider=provider,
        on_parse=on_parse,
    )
