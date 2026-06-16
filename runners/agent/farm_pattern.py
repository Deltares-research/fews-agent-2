"""Pattern-farming CLI.

Read N InstanceInputs from a JSON file, farm a ``pattern.yaml`` via
an LLM, write the result, report exact-round-trip status.

The provider defaults to local Ollama. ``--escalate`` walks a ladder
of progressively stronger models until one produces an exact-round-
trip pattern (or the ladder exhausts).

Usage::

    # Default local model (Ollama qwen2.5:7b-instruct):
    python -m runners.agent.farm_pattern \\
        --instances instances.json \\
        --name nwp_grid_eccc_HRDPS_farmed \\
        --out /tmp/farmed

    # Stronger HF model:
    HF_TOKEN=hf_xxx python -m runners.agent.farm_pattern \\
        --instances instances.json \\
        --name nwp_grid_eccc_HRDPS_farmed \\
        --provider hf \\
        --model Qwen/Qwen2.5-72B-Instruct \\
        --out /tmp/farmed

    # Model-iteration ladder (weak → strong via HF until success):
    HF_TOKEN=hf_xxx python -m runners.agent.farm_pattern \\
        --instances instances.json \\
        --name nwp_grid_eccc_HRDPS_farmed \\
        --escalate \\
        --out /tmp/farmed

instances.json shape::

    [
        {
            "label": "HRDPS",
            "variable_hints": {"nwp_name": "HRDPS"},
            "outputs": [
                {"schema": "TimeSeriesImportRun", "output": "...", "data": {...}},
                {"schema": "Workflow",            "output": "...", "data": {...}}
            ]
        },
        ...
    ]
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from rich.console import Console
from rich.table import Table

from fews_agent.agent.providers.factory import get_provider
from fews_agent.pattern_farm import farm
from fews_agent.pattern_farm.ir import InstanceInput
from fews_agent.pattern_farm.renderer import write_pattern_yaml
from fews_agent.pattern_farm.xml_ingest import parse_instance_config


# Default escalation ladder for HF-backed runs. Ordered weakest → strongest.
HF_LADDER = [
    "Qwen/Qwen2.5-7B-Instruct",
    "Qwen/Qwen2.5-Coder-7B-Instruct",
    "meta-llama/Llama-3.1-8B-Instruct",
    "Qwen/Qwen2.5-Coder-32B-Instruct",
    "Qwen/Qwen2.5-72B-Instruct",
]

# Default escalation ladder for local Ollama. Assumes models exist;
# the entrypoint emits a clear error if any aren't pulled.
OLLAMA_LADDER = [
    "qwen2.5:7b-instruct",
    "qwen2.5-coder:7b",
    "qwen2.5:14b-instruct",
    "qwen2.5-coder:32b",
    "qwen2.5:72b-instruct",
]


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    src = p.add_mutually_exclusive_group(required=True)
    src.add_argument("--instances", type=Path,
                     help="Path to instances JSON (pre-built dicts)")
    src.add_argument("--xml-config", type=Path,
                     help="Path to YAML manifest naming XML files per instance "
                          "(see fews_agent.pattern_farm.xml_ingest.parse_instance_config)")
    p.add_argument("--name", required=True,
                   help="Farmed pattern name (folder under --out)")
    p.add_argument("--description", default="",
                   help="Description embedded in pattern.yaml")
    p.add_argument("--out", required=True, type=Path,
                   help="Output directory; pattern.yaml goes under <out>/<name>/")
    p.add_argument("--provider", default=None,
                   choices=["ollama", "hf", "anthropic", "litellm", "azure"],
                   help="Provider backend (defaults to env FEWS_AGENT_PROVIDER or ollama)")
    p.add_argument("--model", default=None,
                   help="Single model ID. Overrides provider default.")
    p.add_argument("--escalate", action="store_true",
                   help="Walk weak→strong ladder until exact round-trip.")
    p.add_argument("--max-repair-retries", type=int, default=3,
                   help="Per-output repair attempts in the validate loop")
    p.add_argument("--oracle", type=Path, default=None,
                   help="Optional: path to existing pattern.yaml for byte-diff")
    return p.parse_args(argv)


def load_instances(path: Path) -> list[InstanceInput]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise SystemExit(f"--instances must hold a JSON array; got {type(raw).__name__}")
    return [InstanceInput.model_validate(item) for item in raw]


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    console = Console()

    if args.xml_config is not None:
        instances = parse_instance_config(args.xml_config)
        console.print(f"[dim]Loaded {len(instances)} instance(s) from XML manifest "
                      f"{args.xml_config}[/dim]")
    else:
        instances = load_instances(args.instances)
    console.print(
        f"[bold]Farming pattern[/bold] from {len(instances)} instance(s): "
        f"{', '.join(i.label for i in instances)}"
    )

    provider_name = args.provider or os.environ.get("FEWS_AGENT_PROVIDER") or "ollama"
    ladder = _build_ladder(provider_name, args.model, args.escalate)
    console.print(f"[dim]Provider:[/dim] {provider_name}")
    console.print(f"[dim]Model ladder:[/dim] {ladder}")

    last_result = None
    for model in ladder:
        console.print(f"\n[cyan]▶ Trying model:[/cyan] {model}")
        provider = get_provider(name=provider_name, model=model)
        try:
            result = farm(
                instances=instances,
                name=args.name,
                provider=provider,
                description=args.description,
                max_repair_retries=args.max_repair_retries,
                log=lambda m: console.print(f"  [dim]{m}[/dim]"),
            )
        except Exception as exc:  # noqa: BLE001
            console.print(f"  [red]model {model} crashed:[/red] {exc}")
            continue

        last_result = result
        _print_validation(console, result, instances)
        if result.ok:
            console.print(f"[bold green]✓ exact round-trip on model {model}[/bold green]")
            break
        console.print(f"[yellow]✗ model {model} did not converge[/yellow]")

    if last_result is None:
        console.print("[red]all models in ladder failed to run[/red]")
        return 1

    target_dir = args.out / args.name
    out_path = write_pattern_yaml(last_result.spec, target_dir)
    console.print(f"\nWrote: [bold]{out_path}[/bold]")

    if args.oracle is not None and args.oracle.is_file():
        _diff_against_oracle(console, out_path, args.oracle)

    return 0 if last_result.ok else 2


def _build_ladder(
    provider_name: str, model_override: str | None, escalate: bool,
) -> list[str]:
    if model_override and not escalate:
        return [model_override]
    if escalate:
        base = HF_LADDER if provider_name == "hf" else OLLAMA_LADDER
        if model_override and model_override in base:
            i = base.index(model_override)
            return base[i:]
        return list(base)
    return [model_override] if model_override else [_default_for(provider_name)]


def _default_for(provider_name: str) -> str:
    return {
        "ollama": "qwen2.5:7b-instruct",
        "hf": "Qwen/Qwen2.5-7B-Instruct",
        "anthropic": "claude-haiku-4-5",
        "litellm": "huggingface/Qwen/Qwen2.5-7B-Instruct",
    }.get(provider_name, "qwen2.5:7b-instruct")


def _print_validation(console: Console, result, instances) -> None:
    table = Table(title=f"Validation — pattern '{result.spec.name}'")
    table.add_column("output #")
    table.add_column("schema")
    table.add_column("status")
    table.add_column("retries")
    for idx, out_spec in enumerate(result.spec.outputs):
        bad = [d for d in result.validation.diffs
               if d.output_index == idx and not d.is_empty()]
        status = "ok" if not bad else f"{len(bad)} instance(s) diverge"
        table.add_row(
            str(idx), out_spec.schema_class, status,
            str(result.retries_per_output.get(idx, 0)),
        )
    console.print(table)
    if not result.validation.ok:
        console.print("[dim]" + result.validation.summary() + "[/dim]")


def _diff_against_oracle(console: Console, farmed: Path, oracle: Path) -> None:
    farmed_text = farmed.read_text(encoding="utf-8")
    oracle_text = oracle.read_text(encoding="utf-8")
    if farmed_text == oracle_text:
        console.print(f"[bold green]✓ byte-equivalent to oracle:[/bold green] {oracle}")
        return
    import difflib
    diff = difflib.unified_diff(
        oracle_text.splitlines(keepends=True),
        farmed_text.splitlines(keepends=True),
        fromfile=str(oracle), tofile=str(farmed), n=3,
    )
    console.print("[yellow]Diff vs oracle (first 60 lines):[/yellow]")
    for i, line in enumerate(diff):
        if i >= 60:
            console.print("[dim]... truncated[/dim]")
            break
        sys.stdout.write(line)


if __name__ == "__main__":
    sys.exit(main())
