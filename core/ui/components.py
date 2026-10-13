"""Shared Streamlit widgets so every app looks and behaves the same."""

from __future__ import annotations

import hashlib
import tomllib
from pathlib import Path
from typing import Callable

import streamlit as st

from ..io import Project, ProjectFileError, ProjectWarning, dumps, loads, save
from ..units import UNIT_SYSTEMS

CATEGORIES: dict[str, str] = {
    "piping_structural": "Piping Structural",
    "fluid_analysis_design": "Fluid Analysis & Design",
    "component_design_material": "Component Design & Material Choice",
    "thermodynamic_design": "Thermodynamic Design",
    "process_hazards_analysis": "Process Hazards Analysis",
    "project_management_costing": "Project Management & Costing",
}

STATUS_LABELS = {"available": "Available", "planned": "Planned"}

_WARNING_TITLES = {
    "PLACEHOLDER": "Placeholder data",
    "UNVERIFIED_DATA": "Unverified data",
    "EXTRAPOLATED": "Extrapolated",
    "SERVICE_LIMIT": "Service limit",
    "UNCITED_INPUT": "Uncited input",
}


def load_app_meta(app_file: str | Path) -> dict:
    """Read the app.toml that sits beside an app's app.py."""
    path = Path(app_file).parent / "app.toml"
    with path.open("rb") as f:
        meta = tomllib.load(f)
    meta["dir"] = str(Path(app_file).parent)
    return meta


def page_header(meta: dict) -> None:
    try:
        st.set_page_config(page_title=meta["name"], layout="wide")
    except st.errors.StreamlitAPIException:
        pass  # already configured by the launcher
    st.title(meta["name"])
    cat = CATEGORIES.get(meta.get("category", ""), "")
    st.caption(f"{cat} · v{meta.get('version', '0.0.0')}")


def warning_banner(warnings: list[ProjectWarning]) -> None:
    """Prominent, consistent display of data-quality warnings."""
    if not warnings:
        return
    with st.container(border=True):
        st.markdown(f"**:orange[⚠ {len(warnings)} data warning(s): review before relying on results]**")
        for w in warnings:
            title = _WARNING_TITLES.get(w.code, w.code)
            st.markdown(f"- **{title}**: {w.message}")


def unit_system_toggle(key: str = "unit_system", on_change: Callable | None = None) -> str:
    st.session_state.setdefault(key, "US")
    return st.segmented_control(
        "Units", list(UNIT_SYSTEMS), key=key, on_change=on_change, selection_mode="single",
    ) or "US"


def save_load_panel(
    meta: dict,
    build_project: Callable[[], Project],
    on_load: Callable[[Project], None],
) -> None:
    """Download/upload JSON and save/load from the app's projects/ folder.

    on_load runs inside a widget callback (before the next rerun renders),
    so it may freely set widget session_state keys.
    """
    projects_dir = Path(meta["dir"]) / "projects"
    app_name = meta["id"]

    def _apply(text: str, origin: str) -> None:
        try:
            project = loads(text)
        except (ProjectFileError, ValueError, KeyError) as e:
            st.session_state["_load_error"] = f"Could not load {origin}: {e}"
            return
        if project.app_name != app_name:
            st.session_state["_load_error"] = (
                f"{origin} belongs to '{project.app_name}', not '{app_name}'."
            )
            return
        on_load(project)
        st.session_state["_load_ok"] = f"Loaded {origin}."

    def _on_upload() -> None:
        f = st.session_state.get("_upload")
        if f is None:
            return
        data = f.getvalue()
        digest = hashlib.sha256(data).hexdigest()
        if st.session_state.get("_upload_digest") == digest:
            return
        st.session_state["_upload_digest"] = digest
        _apply(data.decode("utf-8"), f.name)

    def _on_open() -> None:
        name = st.session_state.get("_open_name")
        if name:
            _apply((projects_dir / name).read_text(encoding="utf-8"), name)

    with st.expander("Project file: save / load", expanded=False):
        for key, show in (("_load_error", st.error), ("_load_ok", st.success)):
            if key in st.session_state:
                show(st.session_state.pop(key))
        c1, c2 = st.columns(2)
        with c1:
            st.markdown("**Save**")
            name = st.text_input("File name", value=f"{app_name}_project", key="_save_name")
            project = build_project()
            st.download_button(
                "Download .json", dumps(project), file_name=f"{name}.json",
                mime="application/json", width="stretch",
            )
            if st.button("Save to projects folder", width="stretch"):
                path = save(project, projects_dir / f"{name}.json")
                st.success(f"Saved {path.name}")
        with c2:
            st.markdown("**Load**")
            st.file_uploader("Upload .json", type=["json"], key="_upload", on_change=_on_upload)
            files = sorted(p.name for p in projects_dir.glob("*.json")) if projects_dir.exists() else []
            if files:
                st.selectbox("Or open from projects folder", files, key="_open_name")
                st.button("Open", on_click=_on_open, width="stretch")


def run_stub(app_file: str | Path) -> None:
    """Render a placeholder page for an app that isn't built yet."""
    meta = load_app_meta(app_file)
    page_header(meta)
    st.info(f"**Not yet implemented.** {meta.get('description', '')}")
    if meta.get("roadmap_note"):
        st.caption(f"Roadmap: {meta['roadmap_note']}")
