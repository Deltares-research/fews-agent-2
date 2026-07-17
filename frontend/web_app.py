"""Streamlit POC frontend for the FEWS configurator chat agent.

Run with:

    streamlit run frontend/web_app.py

Each chat lives in a session folder
``sessions/<username>_<YYYY-MM-DD_HHMMSS>/`` containing:

  * ``.chat_state.json``    — current state (intent, slots, patterns)
  * ``.chat_history.json``  — full role/message history
  * ``_conversation.md``    — markdown transcript with engine internals
  * ``_app.log``            — structured turn events
  * ``project.yaml``        — written here when the user types ``done``

The sidebar lets the user pick their username (defaults to the system
user) and either start a new session or resume one of their existing
ones.
"""
from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

# Streamlit launches this script with ``frontend/`` (not the repo root)
# on ``sys.path``, so importing ``app.chatter`` (and its imports of
# ``fews_agent`` / ``runners``) only resolves once the repo root is on
# the path. Prepend it defensively so the app runs out of the box.
_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

# Load ``.env`` from the repo root before anything reads os.environ.
# Real process env (e.g. Azure App Settings) wins — ``override=False``
# means we don't clobber values set by the container runtime.
try:
    from dotenv import load_dotenv
    load_dotenv(_REPO_ROOT / ".env", override=False)
except ImportError:  # python-dotenv missing → silently skip
    pass

import streamlit as st

from app.chatter import (
    ChatSession,
    SESSIONS_ROOT,
    list_ollama_models,
    list_sessions,
    new_session_dir,
)
from fews_agent.agent.project_intents import (
    INTENTS,
    compute_input_status,
    is_intent_ready,
    next_unfilled_question,
    scan_inputs,
)


st.set_page_config(
    page_title="FEWS configurator agent",
    page_icon="💧",
    layout="wide",
)


def _ensure_session(
    username: str, project_name: str, model: str, resume_path: str | None
) -> ChatSession:
    """Cache one ChatSession in Streamlit session_state, keyed by chosen folder."""
    key = f"chat::{resume_path or 'new'}::{username}::{model}"
    if st.session_state.get("_chat_key") != key:
        if resume_path:
            session_dir = SESSIONS_ROOT / resume_path
        else:
            session_dir = new_session_dir(username)
        st.session_state["chat"] = ChatSession(
            project_name=project_name,
            model=model,
            session_dir=session_dir,
            username=username,
        )
        st.session_state["_chat_key"] = key
        # Drop the previous session's validation stash so the panel
        # doesn't bleed across sessions. The panel's render guard
        # also checks chat_key, so this is belt-and-braces.
        st.session_state.pop("_last_done", None)
    return st.session_state["chat"]


# ----- sidebar: user + session ----------------------------------------------

with st.sidebar:
    # Two slots reserved at the very top — the /done button + the
    # inputs uploader. Both depend on state that isn't computed yet
    # (chat session, readiness, intent), so we fill them with
    # ``slot.container()`` further down once those values exist.
    # Defining empty slots here pins their visual order to the top
    # of the sidebar.
    _done_slot = st.empty()
    _inputs_slot = st.empty()
    st.markdown("---")

    st.header("Session")

    username = st.text_input("Username", value="user").strip() or "user"

    existing = list_sessions(username)
    options = ["<new session>"] + [p.name for p in existing]
    choice = st.selectbox("Open / create", options=options, index=0)

    if choice == "<new session>":
        project_name = st.text_input("Project name", value="demo").strip() or "demo"
        resume_path: str | None = None
    else:
        project_name = ""  # loaded from persisted state inside ChatSession
        resume_path = choice

    # Provider selection is env-driven (FEWS_AGENT_PROVIDER). For
    # Ollama we list locally-installed models so the user can pick;
    # for Azure (and other cloud providers) the "model" is a deployment
    # name owned by the env vars — we surface it read-only and skip
    # the Ollama-specific selector entirely.
    import os as _os
    _provider_env = (_os.environ.get("FEWS_AGENT_PROVIDER") or "ollama").lower().strip()
    if _provider_env in {"azure_openai", "azure-openai", "azureopenai"}:
        _provider_env = "azure"

    if _provider_env == "ollama":
        # Populated from `ollama list`. If Ollama is down or has no
        # models, ``available_models`` is empty and we fall back to a
        # disabled selectbox + a prominent error in the main panel.
        available_models = list_ollama_models()
        if available_models:
            # Default selection: the project was tuned against
            # ``qwen2.5:7b-instruct`` (strong tool-calling JSON, ~7B
            # params), so prefer it. Fall back to other small/known
            # models in order of expected quality. Honour the user's
            # last pick this session.
            prev = st.session_state.get("_last_model")
            if prev in available_models:
                default_idx = available_models.index(prev)
            else:
                _preferred = ("qwen2.5:7b-instruct",
                              "phi3.5:latest", "phi3.5", "phi3")
                default_idx = next(
                    (available_models.index(m) for m in _preferred
                     if m in available_models),
                    0,
                )
            model = st.selectbox(
                "Model", options=available_models, index=default_idx,
            )
            st.session_state["_last_model"] = model
        else:
            model = ""
            st.selectbox("Model", options=["(no models found)"], disabled=True)

        if st.button("Refresh models"):
            st.rerun()
    else:
        # Cloud provider — the "model" is a deployment name owned by
        # the AZURE_OPENAI_DEPLOYMENT env var. Show it read-only.
        _deployment = (
            _os.environ.get("AZURE_OPENAI_DEPLOYMENT")
            or _os.environ.get("FEWS_AGENT_MODEL")
            or "gpt-4o-mini"
        )
        st.selectbox(
            f"Model (provider: {_provider_env})",
            options=[_deployment],
            disabled=True,
        )
        model = _deployment
        available_models = [_deployment]

    show_internals = st.toggle("Show engine internals", value=False)

    st.markdown("---")
    st.caption(
        "**Tip:** the first project-related message after picking a model is "
        "slow — Ollama loads the model into RAM. Subsequent replies are fast."
    )
    st.caption("Commands:")
    st.caption(
        "**Project**: `/done` (write project.yaml — also the big "
        "button), `/force-done` (write with open warnings), "
        "`/preview` (dry-run project.yaml)."
    )
    st.caption(
        "**Build & edit (one module at a time)**: `/list` (modules + "
        "editable vars), `/phases` (the imports→process→model→visualize "
        "plan), `/add <name>` (e.g. `/add GFS`, `/add Liard uses raven`), "
        "`/remove <name>`, `/set <name> <var> <value>` (e.g. "
        "`/set GFS horizon 7-day`), `/build <phase|name>` (build + "
        "XSD-validate one module/phase now). You can also just say it in "
        "plain language — *“also add an HRDPS import”*, *“drop RDPS”*."
    )
    st.caption(
        "**Inspect**: `/help` (commands + concept glossary; follow "
        "up with *'more'*, *'example'*, *'compare X and Y'*), "
        "`/status` (what's filled / missing)."
    )
    st.caption(
        "**State**: `/undo` (roll back last turn — up to 10 deep), "
        "`/reset` (clear state, keeps session folder; asks to "
        "confirm), `/edit <file>` / `/cancel-edit`, `yes`/`no` "
        "(confirm/cancel a pending action)."
    )

    if st.button("Reset cached session"):
        st.session_state.pop("chat", None)
        st.session_state.pop("_chat_key", None)
        st.session_state.pop("_last_done", None)
        st.rerun()


if _provider_env == "ollama":
    _llm_ok = bool(available_models) and bool(model)
    _llm_err_msg = (
        "Cannot reach Ollama at `http://localhost:11434`, or no models are "
        "installed. Start it with `ollama serve` and `ollama pull <model>`, "
        "then click **Refresh models** in the sidebar."
    )
else:
    # Cloud provider: model selector is read-only, just check the
    # required env vars are present. The actual network reachability
    # is exercised on the first chat turn.
    _missing = [
        v for v in ("AZURE_OPENAI_ENDPOINT", "AZURE_OPENAI_API_KEY")
        if not _os.environ.get(v)
    ] if _provider_env == "azure" else []
    _llm_ok = not _missing
    _llm_err_msg = (
        f"FEWS_AGENT_PROVIDER={_provider_env} but the required "
        "environment variable(s) are missing: " + ", ".join(_missing)
        + ". Set them (e.g. in `.env`) and restart."
    ) if _missing else ""

chat = _ensure_session(
    username, project_name or "demo", model or "qwen2.5:7b-instruct", resume_path,
)

# State derivatives are hoisted to the top of the main panel so the
# top-left /done button (rendered immediately below) can read them.
# Reused throughout the rest of the panel — metrics, warnings, status.
state = chat.state
slots = state.get("slots") or {}
intent = state.get("intent") or "—"
patterns_count = len(state.get("patterns") or [])
warnings_count = len(state.get("warnings") or [])

# ----- /done readiness ------------------------------------------------------

# Computed once here and reused for both the top-left button and the
# inline trigger logic. Readiness = everything '/done' would refuse
# is satisfied: intent classified, all required slots filled, no open
# warnings, no missing required CSVs in inputs/.
_intent_obj = INTENTS.get(state.get("intent") or "")
_slots = slots
_input_scan_for_button = scan_inputs(chat.session_dir / "inputs")
_input_status_for_button = compute_input_status(
    state.get("intent"), _input_scan_for_button, _slots,
)
_missing_required_csvs = list(
    _input_status_for_button.get("csvs_required_missing") or []
)
_ready_for_done = (
    bool(_intent_obj)
    and is_intent_ready(_intent_obj, _slots)
    and warnings_count == 0
    and not _missing_required_csvs
)

# Why-not-ready reasons for the disabled-button tooltip.
_done_reasons: list[str] = []
if not _intent_obj:
    _done_reasons.append("no project intent yet — describe what you want to build")
elif not is_intent_ready(_intent_obj, _slots):
    _done_reasons.append(
        f"missing slot: {next_unfilled_question(_intent_obj, _slots)}"
    )
if _missing_required_csvs:
    _done_reasons.append(
        "missing required CSV(s) in inputs/: "
        + ", ".join(_missing_required_csvs)
    )
if warnings_count:
    _done_reasons.append(f"{warnings_count} open warning(s)")
_done_help = (
    "Writes project.yaml into the session folder. "
    "Equivalent to typing '/done' in the chat."
    if _ready_for_done
    else "Not ready — fix:\n• " + "\n• ".join(_done_reasons)
)

# ----- sidebar slots: /done button + inputs uploader -----------------------

# Fill the placeholders defined at the very top of the sidebar.
# Button stays type="primary" in both states so the disabled form
# stays visible (disabled-secondary buttons vanish on dark themes).
with _done_slot.container():
    st.caption(
        "**Status: ready — click to write**"
        if _ready_for_done
        else f"**Status: not ready** ({len(_done_reasons)} item(s))"
    )
    done_clicked = st.button(
        "Write project.yaml  ( /done )"
        if _ready_for_done
        else "/done — locked until ready",
        type="primary",
        use_container_width=True,
        disabled=not _ready_for_done,
        help=_done_help,
        key="done_button",
    )

with _inputs_slot.container():
    with st.expander("Project inputs (CSVs / yaml / shapefile)", expanded=False):
        inputs_dir = chat.session_dir / "inputs"
        inputs_dir.mkdir(parents=True, exist_ok=True)

        uploaded = st.file_uploader(
            "Drop files for inputs/",
            accept_multiple_files=True,
            type=["csv", "yaml", "yml", "shp", "dbf", "shx", "prj", "cpg",
                  "json", "txt"],
            label_visibility="collapsed",
            key="inputs_uploader",
        )
        if uploaded:
            for f in uploaded:
                (inputs_dir / f.name).write_bytes(f.getbuffer())
            st.caption(f"Saved {len(uploaded)} file(s) to `inputs/`.")

        existing_inputs = sorted(
            p.name for p in inputs_dir.iterdir() if p.is_file()
        )
        if existing_inputs:
            st.caption("**In `inputs/`:**")
            for _n in existing_inputs:
                st.caption(f"• `{_n}`")
        else:
            st.caption("_No input files yet._")
        st.caption(
            "Auto-detected on the next message; missing/recommended "
            "files for the active intent are flagged."
        )

# ----- header ---------------------------------------------------------------

st.title("FEWS configurator agent")
st.caption(f"session: `{chat.session_dir.name}`  ·  project: `{chat.project_name}`")
st.caption(f"`{chat.session_dir}`  ·  model: `{chat.model}`")

if not _llm_ok:
    st.error(_llm_err_msg)

# Project-level snapshot. "project intent" is explicit so it's clear
# the metric only reflects the build_* intent (slot/pattern driver);
# the per-turn meta intents — status_check, help — fire without
# mutating state["intent"] and so are intentionally invisible here.
c1, c2, c3 = st.columns(3)
c1.metric("project intent", intent)
c2.metric("patterns", patterns_count)
c3.metric("warnings", warnings_count)

# Standing warnings (carry over from the previous turn until cleared).
for w in state.get("warnings") or []:
    st.warning(w)


# ----- conversation history -------------------------------------------------

for msg in chat.messages:
    role = "user" if msg["role"] == "user" else "assistant"
    with st.chat_message(role):
        st.markdown(msg["message"])

# ----- input + new turn -----------------------------------------------------

prompt = st.chat_input(
    "Message the agent (or click the /done button above when ready)"
    if _llm_ok
    else "LLM unavailable — /done still works via the button",
    disabled=not _llm_ok,
)
if done_clicked and not prompt:
    prompt = "/done"
if prompt:
    with st.chat_message("user"):
        st.markdown(prompt)
    with st.chat_message("assistant"):
        with st.spinner("Thinking…"):
            result = chat.send(prompt)
        st.markdown(result.agent_message)
        for w in result.warnings:
            st.warning(w)
        if result.kind in ("done", "build") and result.project_yaml_path:
            if result.kind == "done":
                st.success(f"Wrote `{result.project_yaml_path}`")
            # Stash everything the validation panel needs in
            # session_state, keyed by the active chat session. The
            # panel is rendered OUTSIDE the prompt block (further
            # down) so that Streamlit reruns triggered by the
            # Download button — which fire with no ``prompt`` — don't
            # cause the panel to disappear.
            st.session_state["_last_done"] = {
                "chat_key": st.session_state.get("_chat_key"),
                "project_path": str(result.project_yaml_path),
                "build_error": result.build_error,
                "validation_summary": result.validation_summary,
            }
        elif result.kind == "coordinates":
            # Open the grid-coordinates subwindow on the next rerun. Stash the
            # eligible grids keyed by the active session so a stray rerun
            # doesn't reopen it for the wrong chat.
            st.session_state["_coords_request"] = {
                "chat_key": st.session_state.get("_chat_key"),
                "grids": result.coordinates_request or [],
            }
        elif result.kind == "error":
            st.error(result.agent_message)
        if show_internals and result.internals:
            with st.expander("Engine internals (this turn)", expanded=False):
                st.markdown(result.internals)


# ----- grid coordinates subwindow -------------------------------------------

# Opened by the ``/coordinates`` command (ChatSession returns kind=="coordinates"
# with the eligible NWP grids). Renders a modal (st.dialog when available, else
# an inline panel) to set a firstCellCenter + rows/columns; submitting calls
# ChatSession.apply_grid_geometry (cell size is inherited). Rendered outside the
# prompt block so the modal survives the reruns its own widgets trigger.
def _render_coords_form(chat, grids: list[dict]) -> None:
    names = [g["name"] for g in grids]
    sel = st.selectbox("NWP grid import", names, key="_coords_sel")
    cur = next((g.get("geometry") for g in grids if g["name"] == sel), None) or {}
    c1, c2 = st.columns(2)
    x = c1.number_input(
        "First cell centre — longitude (x)",
        value=float(cur.get("first_x", 0.0)), format="%.4f", key="_coords_x",
    )
    y = c2.number_input(
        "First cell centre — latitude (y)",
        value=float(cur.get("first_y", 0.0)), format="%.4f", key="_coords_y",
    )
    c3, c4 = st.columns(2)
    cols = c3.number_input(
        "Columns (rows-X)", min_value=1, step=1,
        value=int(cur.get("columns", 100)), key="_coords_cols",
    )
    rows = c4.number_input(
        "Rows (rows-Y)", min_value=1, step=1,
        value=int(cur.get("rows", 100)), key="_coords_rows",
    )
    st.caption(
        "The top-left cell centre + grid size. Cell size is inherited from the "
        "import's resolution / bundled default — this only repositions and "
        "resizes the grid."
    )
    apply_col, cancel_col = st.columns(2)
    if apply_col.button("Apply", type="primary", use_container_width=True):
        chat.apply_grid_geometry(
            sel, first_x=float(x), first_y=float(y),
            columns=int(cols), rows=int(rows),
        )
        st.session_state.pop("_coords_request", None)
        st.rerun()
    if cancel_col.button("Cancel", use_container_width=True):
        st.session_state.pop("_coords_request", None)
        st.rerun()


_coords_req = st.session_state.get("_coords_request")
if _coords_req and _coords_req.get("chat_key") == st.session_state.get("_chat_key"):
    _grids = _coords_req.get("grids") or []
    if hasattr(st, "dialog"):  # Streamlit >= 1.31 modal
        st.dialog("Set grid coordinates")(
            lambda: _render_coords_form(chat, _grids)
        )()
    else:  # graceful fallback: inline panel
        with st.expander("Set grid coordinates", expanded=True):
            _render_coords_form(chat, _grids)


# ----- validation panel (persists across reruns) ----------------------------

# Rendered OUTSIDE the chat-message bubble and outside ``if prompt:`` so
# the download button's rerun (which fires with no prompt) doesn't make
# the panel vanish. Driven entirely by ``st.session_state["_last_done"]``;
# cleared when the user switches sessions (chat_key changes).
_done_stash = st.session_state.get("_last_done")
if _done_stash and _done_stash.get("chat_key") == st.session_state.get("_chat_key"):
    _build_error = _done_stash.get("build_error")
    _vs = _done_stash.get("validation_summary")

    if _build_error:
        st.error(
            "**Build pipeline crashed before validation could run.** "
            "The project.yaml above is valid, but no XMLs were "
            "generated. Details:\n\n```\n"
            + _build_error
            + "\n```"
        )
    elif _vs is not None:
        _n_total = _vs.get("files_total", 0)
        _n_xsd = _vs.get("files_xsd_ok", 0)
        _errors = _vs.get("errors") or []
        _files = _vs.get("files") or []
        _xsd_failed = [f for f in _files if not f.get("xsd_ok")]

        _hdr_col = "green" if _vs.get("ok") else "red"
        st.markdown(
            f"### Schema validation  "
            f"<span style='color:{_hdr_col}'>"
            f"{'✓ passed' if _vs.get('ok') else '✗ issues found'}"
            f"</span>",
            unsafe_allow_html=True,
        )

        _n_xml = _vs.get(
            "files_xml",
            _n_total - _vs.get("files_non_xml", 0),
        )

        v1, v2, v3 = st.columns(3)
        v1.metric("files generated", _n_total)
        v2.metric(
            "XSD valid (XML only)",
            f"{_n_xsd}/{_n_xml}" if _n_xml else "0/0",
            delta=None if _n_xsd == _n_xml else f"-{_n_xml - _n_xsd}",
            delta_color="inverse",
        )
        v3.metric(
            "Pydantic/render errors",
            len(_errors),
            delta=None if not _errors else f"+{len(_errors)}",
            delta_color="inverse",
        )
        st.caption(f"output: `{_vs.get('output_root', '?')}`")

        # One-click bundle of everything under output_root — XMLs +
        # sa_global.Properties + any mirrored assets — zipped in
        # memory so colleagues can grab the whole config in a single
        # download. Rebuilt each script run; cost is trivial at demo
        # scale (~30 files, <1MB). The zip filename embeds a
        # SESSION-STABLE timestamp (taken from ``_last_done``) so it
        # doesn't change on every rerun — streamlit treats the new
        # ``data`` as a different payload otherwise and the download
        # offer can flicker.
        _out_root_path = Path(_vs.get("output_root", ""))
        if _out_root_path.is_dir():
            import io as _io
            import zipfile as _zip
            _buf = _io.BytesIO()
            _file_count = 0
            with _zip.ZipFile(_buf, "w", _zip.ZIP_DEFLATED) as _zf:
                for _fp in sorted(_out_root_path.rglob("*")):
                    if _fp.is_file():
                        _zf.write(_fp, _fp.relative_to(_out_root_path))
                        _file_count += 1
            _zip_bytes = _buf.getvalue()
            _stash_dt = _done_stash.setdefault(
                "zip_timestamp",
                datetime.now().strftime("%Y%m%d-%H%M%S"),
            )
            _zip_name = f"{chat.project_name}-config-{_stash_dt}.zip"
            st.download_button(
                f"⬇ Download all {_file_count} generated files (.zip, "
                f"{len(_zip_bytes) // 1024} KB)",
                data=_zip_bytes,
                file_name=_zip_name,
                mime="application/zip",
                type="primary",
                use_container_width=True,
                key="download_bundle",
            )

        # Pydantic / render-time errors — these prevented files
        # from being generated, so they don't appear in the
        # per-file XSD table below.
        if _errors:
            with st.expander(
                f"Pydantic / render errors ({len(_errors)})",
                expanded=True,
            ):
                for e in _errors:
                    st.markdown(f"- `{e}`")

        # XSD failures get their own expander so they're easy
        # to find without scrolling through the OK rows.
        if _xsd_failed:
            with st.expander(
                f"XSD failures ({len(_xsd_failed)})",
                expanded=True,
            ):
                for f in _xsd_failed:
                    st.markdown(
                        f"- **`{f['path']}`** — "
                        f"{f.get('xsd_msg', '(no detail)')}"
                    )

        # Full per-file table — collapsed by default to keep the
        # panel skimmable. ``st.dataframe`` accepts a list of dicts
        # directly so no explicit pandas import (pandas comes in
        # transitively via streamlit, but depending on it explicitly
        # would be a silent coupling).
        with st.expander(f"All files ({_n_total})", expanded=False):
            st.dataframe(
                [
                    {
                        "file": f["path"],
                        "xsd": "✓" if f.get("xsd_ok") else "✗",
                        "detail": f.get("xsd_msg") or "",
                    }
                    for f in _files
                ],
                hide_index=True,
                use_container_width=True,
            )

# ----- footer: persisted files ----------------------------------------------

with st.sidebar:
    st.markdown("---")
    st.caption("**Files in this session**")
    for name in ("project.yaml", ".chat_state.json", ".chat_history.json",
                 "_conversation.md", "_app.log"):
        p = chat.session_dir / name
        marker = "✓" if p.exists() else "·"
        st.caption(f"{marker} `{name}`")
