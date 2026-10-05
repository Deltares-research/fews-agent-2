"""Per-session workspace shared by every tool handler.

The context owns the session directory layout (``generated/`` output
tree + ``inputs/`` CSVs), the rendered-file ledger, and usage
accounting. Pydantic model instances are RETAINED per rendered file
because `fews_agent.validation.semantic.validate_semantic` reflects
over model instances, not XML text.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from fews_agent.agent.blueprint import RenderedFile


@dataclass
class UsageTally:
    """Token/call accounting across the whole loop run."""

    prompt_tokens: int = 0
    completion_tokens: int = 0
    llm_calls: int = 0
    tool_calls: int = 0

    def add(self, usage: dict[str, int] | None) -> None:
        self.llm_calls += 1
        if not usage:
            return
        self.prompt_tokens += int(usage.get("prompt_tokens", 0) or 0)
        self.completion_tokens += int(usage.get("completion_tokens", 0) or 0)

    def total(self) -> int:
        return self.prompt_tokens + self.completion_tokens


@dataclass
class ToolContext:
    """Everything a tool handler may touch.

    ``rendered`` is keyed by posix relpath under ``generated/``; each
    value keeps the Pydantic model (when the writer had one) so the
    semantic cross-file pass can run without re-parsing XML.
    """

    session_dir: Path
    generated_dir: Path
    inputs_dir: Path
    rendered: dict[str, RenderedFile] = field(default_factory=dict)
    usage: UsageTally = field(default_factory=UsageTally)
    http_timeout: float = 30.0

    @classmethod
    def for_session(cls, session_dir: Path) -> "ToolContext":
        ctx = cls(
            session_dir=session_dir,
            generated_dir=session_dir / "generated",
            inputs_dir=session_dir / "inputs",
        )
        ctx.generated_dir.mkdir(parents=True, exist_ok=True)
        ctx.inputs_dir.mkdir(parents=True, exist_ok=True)
        return ctx

    def store(
        self,
        relpath: str,
        content: str,
        spec_name: str,
        model: Any = None,
    ) -> bool:
        """Write ``generated/<relpath>`` and record it. Returns True when
        an existing file was overwritten (the repair loop depends on
        cheap rewrites, so overwriting is allowed and merely flagged)."""
        rel = Path(relpath).as_posix()
        overwrote = rel in self.rendered
        target = self.generated_dir / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        self.rendered[rel] = RenderedFile(
            relpath=rel,
            content=content,
            pattern="react",
            instance_label=spec_name,
            model=model,
        )
        return overwrote

    def rendered_list(self) -> list[RenderedFile]:
        """Stable listing for the derivers/collectors."""
        return [self.rendered[k] for k in sorted(self.rendered)]
