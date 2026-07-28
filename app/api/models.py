"""Pydantic v2 request/response models for the HTTP API.

These are the transport contracts for ``app/api/server.py`` — the third
driver shell over the shared chat turn-engine
(``fews_agent/agent/turn_engine.py``) and the deterministic build path
(``runners/agent/build_from_blueprint.py``). They intentionally mirror
the fields the CLI driver (``runners/agent/chat_step.py``) and the
Streamlit driver (``app/chatter.py``) surface per turn, so an HTTP
client sees the same information a terminal or the web UI would.
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


# --------------------------------------------------------------------------
# Sessions
# --------------------------------------------------------------------------

class CreateSessionRequest(BaseModel):
    """Create a new chat session (a fresh project instance on disk)."""

    project_name: str | None = Field(
        default=None,
        description="Project name. A datetime-stamped instance directory "
        "`projects/<name>/<name>_<YYYY-MM-DD_HHMMSS>/` is created. "
        "Defaults to an auto-generated name.",
    )
    model: str | None = Field(
        default=None,
        description="LLM model id for the chat half (Ollama). Defaults to "
        "qwen2.5:7b-instruct (or FEWS_AGENT_MODEL if set).",
    )


class CreateSessionResponse(BaseModel):
    session_id: str = Field(description="Opaque id — the instance dir name.")
    project_name: str
    project_dir: str = Field(description="Absolute path to the session dir.")
    model: str


class SessionStateResponse(BaseModel):
    """The resolved intermediate variables for a session."""

    session_id: str
    project_name: str
    intent: str | None = None
    slots: dict[str, Any] = Field(default_factory=dict)
    patterns: list[dict[str, Any]] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    built_phases: list[str] = Field(default_factory=list)


# --------------------------------------------------------------------------
# Turn
# --------------------------------------------------------------------------

class TurnRequest(BaseModel):
    message: str = Field(description="The user's chat message for this turn.")


class TurnResponse(BaseModel):
    """Mirrors what the CLI/Streamlit drivers surface after one turn."""

    reply: str = Field(description="The agent's user-facing reply (or the "
                       "disambiguation question when short_circuit is true).")
    short_circuit: bool = Field(
        description="True when the intent-disambiguation gate asked an "
        "either/or question and resolved nothing this turn.",
    )
    intent: str | None = None
    patterns: list[dict[str, Any]] = Field(default_factory=list)
    slots: dict[str, Any] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)
    ready: bool = False
    next_question: str | None = None
    new_patterns: list[str] = Field(default_factory=list)
    internals: str | None = Field(
        default=None,
        description="Engine-internals diagnostics markdown (skills → intent "
        "→ slot-fill → resolution). Null on a disambiguation short-circuit.",
    )
    # --- module-mode ---
    module_mode: bool = Field(
        default=False,
        description="True when this turn was handled in module-mode (a "
        "FEWS-folder module is in focus) rather than the whole-project "
        "intent pipeline.",
    )
    current_module: str | None = Field(
        default=None,
        description="The module in focus after this turn (module-mode), e.g. "
        "'processing'. Null when no module is focused.",
    )
    wants_build: bool = Field(
        default=False,
        description="True when the turn asked to build the focused module. "
        "The turn endpoint does not build; POST /sessions/{id}/build to "
        "assemble, or build the scoped phase via the build tooling.",
    )
    confirmation: str = Field(
        default="",
        description="The mechanical 'what changed' fact for a module-mode edit "
        "(e.g. \"Applied: imports=['GFS']\"). The UI renders this muted/grey "
        "above the model-composed `reply`. Empty for non-edit turns.",
    )


# --------------------------------------------------------------------------
# Build
# --------------------------------------------------------------------------

class BuildRequest(BaseModel):
    force: bool = Field(
        default=False,
        description="Write project.yaml + build even if the intent has "
        "unfilled required slots or open warnings (mirrors force-done). "
        "Ignored for scoped (phase/module) builds — those are meant to run "
        "mid-elicitation.",
    )
    phase: str | None = Field(
        default=None,
        description="Scoped build: render + XSD-validate ONLY this capability "
        "phase (imports | process | model | visualize), skipping singleton "
        "merge / bundled standards / derivers / cross-file checks (those need "
        "the whole project). Mutually exclusive with `module`.",
    )
    module: str | None = Field(
        default=None,
        description="Scoped build: build every capability phase the focused "
        "FEWS-folder module owns (e.g. 'processing', 'display'). Mutually "
        "exclusive with `phase`.",
    )


class BuildFileResult(BaseModel):
    path: str
    xsd_ok: bool
    xsd_msg: str | None = None
    byte_equivalent: bool | None = None


class BuildResponse(BaseModel):
    """The per-file XSD-validation table from a full or scoped build."""

    ok: bool
    scope: str = Field(
        default="full",
        description="What was built: 'full' (whole project assembly), "
        "'phase:<name>' (one capability phase), or 'module:<key>' (all phases "
        "a FEWS-folder module owns). Scoped builds skip singleton merge / "
        "bundled standards / derivers / cross-file checks.",
    )
    built_phases: list[str] = Field(
        default_factory=list,
        description="Capability phases built (populated for scoped builds).",
    )
    blueprint: str | None = None
    project_yaml: str = Field(description="Absolute path to the written "
                             "project.yaml.")
    output_root: str | None = None
    files_total: int = 0
    files_xml: int = 0
    files_non_xml: int = 0
    files_xsd_ok: int = 0
    errors: list[str] = Field(default_factory=list)
    unbacked_interpolation_sets: list[str] = Field(default_factory=list)
    files: list[BuildFileResult] = Field(default_factory=list)


# --------------------------------------------------------------------------
# Generated files (read-only browsing/diffing — e.g. for an IDE extension)
# --------------------------------------------------------------------------

class FilesResponse(BaseModel):
    """The generated-file manifest — everything on disk under ``generated/``
    right now, freshly XSD-validated per file (not a cached build summary,
    so it stays correct across any mix of full/scoped builds)."""

    built: bool = Field(
        description="False when no build has run yet for this session — "
        "`files` is empty in that case.",
    )
    files: list[BuildFileResult] = Field(default_factory=list)


class FileContentResponse(BaseModel):
    relpath: str
    content: str
    source: str = Field(
        description="'generated' for the current on-disk content, or "
        "'rev:<rev>' when a historical revision was requested via `?rev=`.",
    )


# --------------------------------------------------------------------------
# Route (the "GPS" journey stepper)
# --------------------------------------------------------------------------

class LegModel(BaseModel):
    id: str
    title: str
    kind: str = Field(description="'blocking' or 'advisory'.")
    active: bool
    done: bool
    guidance: str = ""
    detail: str = ""


class RouteResponse(BaseModel):
    """Mirrors ``project_route.route_position`` — where the project stands
    in the add-source → variables → map-area → basin-adapter → inputs →
    assemble journey."""

    legs: list[LegModel] = Field(default_factory=list)
    current: str | None = Field(
        default=None, description="Id of the current leg, if any.",
    )
    blocking_open: list[str] = Field(default_factory=list)
    advisory_open: list[str] = Field(default_factory=list)
    ready_to_assemble: bool = False
    assembled: bool = False


# --------------------------------------------------------------------------
# Module status (the green/amber/grey sidebar signal)
# --------------------------------------------------------------------------

class ModuleStatusModel(BaseModel):
    key: str
    label: str
    built: bool
    status: str = Field(description="'built' | 'none' | 'forced' | 'stale'.")
    focused: bool


class ModulesResponse(BaseModel):
    modules: list[ModuleStatusModel] = Field(default_factory=list)


# --------------------------------------------------------------------------
# Preview (live, pre-build render of one pattern instance's files)
# --------------------------------------------------------------------------

class PreviewFileModel(BaseModel):
    relpath: str
    content: str
    xsd_ok: bool | None = Field(
        description="None for non-XML output (nothing to validate).",
    )
    source: str = Field(description="'live render' or 'last build'.")
    label: str


class PreviewResponse(BaseModel):
    target: str
    files: list[PreviewFileModel] = Field(default_factory=list)


# --------------------------------------------------------------------------
# Health
# --------------------------------------------------------------------------

class HealthResponse(BaseModel):
    status: str = Field(description="Always 'ok' when the service is up.")
    provider: str
    model: str
    ollama_reachable: bool = Field(
        description="Whether the configured LLM backend is reachable and "
        "the model is available. The build path works even when False.",
    )
    detail: str | None = Field(
        default=None,
        description="Human-readable reason when ollama_reachable is False.",
    )
