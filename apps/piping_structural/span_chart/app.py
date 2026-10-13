"""Span Chart: Streamlit UI.

Run standalone:  streamlit run apps/piping_structural/span_chart/app.py
"""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from proctoolbox_core.io import Project
from proctoolbox_core.loads import asce7_16 as asce
from proctoolbox_core.materials import MaterialDataError, default_database
from proctoolbox_core.piping import SIZE_LABEL, WALL_LABEL, list_nps, list_schedules, mill_tolerance, wall_label
from proctoolbox_core.ui import load_app_meta, page_header, save_load_panel, unit_system_toggle, warning_badge
from proctoolbox_core.units import UNIT_SYSTEMS, display_unit, from_si, to_si

from span_calc import (
    CASE_BASIS,
    CASE_LABELS,
    DEFLECTION,
    END_CONDITIONS,
    OCCASIONAL,
    SCOPE_NOTE,
    SUSTAINED,
    SpanCalculator,
    SpanInputError,
    SpanInputs,
    SpanResults,
)
import span_refs
from span_report import build_pdf, default_nps_range, generate_tables

META = load_app_meta(__file__)
DB = default_database()

# Widget key -> (SpanInputs attribute path, unit kind or None, default shown in US units).
# Unit-bearing values live in session state in the current display system.
FIELDS: dict[str, tuple[str, str | None, object]] = {
    "sc_material": ("material_id", None, "carbon_steel"),
    "sc_product": ("product", None, "pipe"),
    "sc_T": ("design_temperature", "temperature", 70.0),
    "sc_P": ("design_pressure", "pressure", 0.0),
    "sc_sg": ("contents_sg", None, 1.0),
    "sc_Sh_override": ("allowable_override", "stress", None),
    "sc_Sh_src": ("allowable_override_source", None, ""),
    "sc_defl": ("deflection_limit", "deflection", None),
    "sc_defl_basis": ("deflection_limit_basis", None, ""),
    "sc_ca": ("corrosion_allowance", "small_length", 0.0),
    "sc_mill": ("mill_tolerance", None, True),
    "sc_conds": ("end_conditions", None, ["simply_supported", "continuous"]),
    "sc_nspans": ("continuous_spans", None, 3),
    # site
    "sc_rc": ("site.risk_category", None, "II"),
    "sc_exp": ("site.exposure", None, "C"),
    "sc_z": ("site.height", "length", 10.0),
    "sc_kzt": ("site.kzt", None, 1.0),
    "sc_elev": ("site.ground_elevation", "length", None),
    "sc_ins": ("site.insulation_thickness", "small_length", 0.0),
    # wind
    "sc_wind": ("wind.enabled", None, False),
    "sc_V": ("wind.speed", "speed", 115.0),
    "sc_rough": ("wind.roughness", None, "moderately_smooth"),
    "sc_cf": ("wind.cf_override", None, None),
    # snow
    "sc_snow": ("snow.enabled", None, False),
    "sc_pg": ("snow.ground_snow", "area_load", 20.0),
    "sc_snowcond": ("snow.condition", None, "fully_exposed"),
    "sc_warm": ("snow.surface_above_45F", None, False),
    "sc_snowcat": ("snow.category", None, SUSTAINED),
    # ice
    "sc_ice": ("ice.enabled", None, False),
    "sc_t_ice": ("ice.thickness", "small_length", 0.5),
    "sc_Vc": ("ice.concurrent_wind", "speed", 40.0),
    "sc_icecat": ("ice.category", None, SUSTAINED),
    # seismic
    "sc_eq": ("seismic.enabled", None, False),
    "sc_sds": ("seismic.sds", None, 0.5),
    "sc_ip": ("seismic.ip", None, 1.0),
    "sc_h": ("seismic.structure_height", "length", 30.0),
    "sc_ptype": ("seismic.piping_type", None, "b31_welded"),
}
UI_DEFAULTS = {
    "unit_system": "US",
    "_unit_system_prev": "US",
    "sc_mode": "Size sweep",
    "sc_schedule": "40",
    "sc_nps": "2",
    "sc_nps_from": "1/2",
    "sc_nps_to": "24",
    "sc_twall": "0.035",
    "sc_tnps": "1/2",
    "sc_tnps_from": "1/4",
    "sc_tnps_to": "2",
    "tbl_twalls": ["0.035", "0.049", "0.065"],
    "tbl_tfrom": "1/4",
    "tbl_tto": "2",
    "sc_override_on": False,
    "tbl_scheds": ["40", "80"],
    "tbl_from": "1/2",
    "tbl_to": "24",
}
for k, v in UI_DEFAULTS.items():
    st.session_state.setdefault(k, v)
for k, (_, _, v) in FIELDS.items():
    st.session_state.setdefault(k, list(v) if isinstance(v, list) else v)


KEYS = {
    "pipe": {"sched": "sc_schedule", "size": "sc_nps", "from": "sc_nps_from", "to": "sc_nps_to"},
    "tube": {"sched": "sc_twall", "size": "sc_tnps", "from": "sc_tnps_from", "to": "sc_tnps_to"},
}
TABLE_KEYS = {
    "pipe": {"walls": "tbl_scheds", "from": "tbl_from", "to": "tbl_to"},
    "tube": {"walls": "tbl_twalls", "from": "tbl_tfrom", "to": "tbl_tto"},
}


def _product() -> str:
    return st.session_state.get("sc_product") or "pipe"


def _units() -> str:
    return st.session_state.get("unit_system") or "US"


def u(kind: str) -> str:
    return display_unit(kind, _units())


def _on_unit_change() -> None:
    new = st.session_state.get("unit_system") or st.session_state["_unit_system_prev"]
    st.session_state["unit_system"] = new
    old = st.session_state["_unit_system_prev"]
    if new == old:
        return
    for key, (_, kind, _) in FIELDS.items():
        val = st.session_state.get(key)
        if kind and val is not None:
            si = to_si(val, UNIT_SYSTEMS[old][kind], kind)
            st.session_state[key] = round(from_si(si, kind, new), 6)
    st.session_state["_unit_system_prev"] = new


def _sweep_nps() -> list[str]:
    k = KEYS[_product()]
    all_nps = list_nps(_product())
    if st.session_state["sc_mode"] == "Single size":
        return [st.session_state[k["size"]]]
    i, j = all_nps.index(st.session_state[k["from"]]), all_nps.index(st.session_state[k["to"]])
    return all_nps[min(i, j): max(i, j) + 1]


def _set(obj, path: str, value) -> None:
    *parents, attr = path.split(".")
    for p in parents:
        obj = getattr(obj, p)
    setattr(obj, attr, value)


def _get(obj, path: str):
    for p in path.split("."):
        obj = getattr(obj, p)
    return obj


def build_inputs() -> SpanInputs:
    s = st.session_state
    sys_ = _units()
    inp = SpanInputs(material_id="", schedule="", nps_list=_sweep_nps(), design_temperature=0.0,
                     deflection_limit=None, deflection_limit_basis="")
    for key, (path, kind, _) in FIELDS.items():
        val = s.get(key)
        if kind and val is not None:
            val = to_si(val, UNIT_SYSTEMS[sys_][kind], kind)
        if isinstance(val, list):
            val = list(val)
        _set(inp, path, val)
    inp.schedule = s[KEYS[inp.product]["sched"]]
    if not s["sc_override_on"]:
        inp.allowable_override = None
    if inp.corrosion_allowance is None:
        inp.corrosion_allowance = 0.0
    return inp


def apply_inputs(inp: SpanInputs, ui_state: dict) -> None:
    """Push saved inputs into widget state (called from a load callback)."""
    s = st.session_state
    sys_ = _units()
    for key, (path, kind, _) in FIELDS.items():
        val = _get(inp, path)
        if kind and val is not None:
            val = round(from_si(val, kind, sys_), 6)
        s[key] = val
    s["sc_override_on"] = inp.allowable_override is not None
    k = KEYS[inp.product]
    s[k["sched"]] = inp.schedule
    s["sc_mode"] = ui_state.get("mode", "Size sweep")
    if s["sc_mode"] == "Single size":
        s[k["size"]] = inp.nps_list[0]
    else:
        s[k["from"]], s[k["to"]] = inp.nps_list[0], inp.nps_list[-1]


# ---------------------------------------------------------------- layout

page_header(META)
unit_system_toggle(on_change=_on_unit_change)
left, right = st.columns([5, 7], gap="large")

# ---------------------------------------------------------------- inputs (left, scrollable)

ref_boxes: dict = {}
with left:
    inputs_box = st.container(height=700, border=False)
with inputs_box:
    with st.container(border=True):
        st.markdown("**Pipe / tube**")
        st.radio("Product", ["pipe", "tube"], key="sc_product", format_func=str.title, horizontal=True,
                 help="Pipe: NPS × schedule (B36.10M/B36.19M). Tube: OD × wall (stainless, ASTM A269).")
        prod = _product()
        k = KEYS[prod]
        mats = DB.ids(prod)
        if st.session_state["sc_material"] not in mats:
            st.session_state["sc_material"] = mats[0]
        st.selectbox("Material", mats, key="sc_material",
                     format_func=lambda m: DB.material(m).name,
                     help="Tube is offered in stainless grades only." if prod == "tube" else None)
        c1, c2 = st.columns(2)
        c1.selectbox(WALL_LABEL[prod], list_schedules(prod), key=k["sched"],
                     format_func=lambda w: wall_label(w, prod) if prod == "tube" else w)
        c2.radio("Mode", ["Size sweep", "Single size"], key="sc_mode", horizontal=True)
        if st.session_state["sc_mode"] == "Single size":
            st.selectbox(SIZE_LABEL[prod], list_nps(prod), key=k["size"])
        else:
            c1, c2 = st.columns(2)
            c1.selectbox(f"From {SIZE_LABEL[prod]}", list_nps(prod), key=k["from"])
            c2.selectbox(f"To {SIZE_LABEL[prod]}", list_nps(prod), key=k["to"])

    with st.container(border=True):
        st.markdown("**Design condition & allowables (B31.3)**")
        c1, c2 = st.columns(2)
        c1.number_input(f"Temperature ({u('temperature')})", key="sc_T", help="v1 range: -40°F to +300°F")
        c2.number_input(f"Pressure, gauge ({u('pressure')})", key="sc_P", min_value=0.0,
                        help="Adds longitudinal pressure stress P·Do/(4t) to every case.")
        c1.number_input("Contents SG", key="sc_sg", min_value=0.0, step=0.05,
                        help="Relative to water at 60°F (= 1.0). 0 = empty pipe.")
        c2.number_input(f"Deflection limit ({u('deflection')})", key="sc_defl", min_value=0.0, placeholder="Required",
                        help="Checked on pipe + contents only. Common practice is 0.1 in (2.5 mm); a design choice, not a code value.")
        st.text_input("Deflection limit basis", key="sc_defl_basis",
                      placeholder="e.g. project piping spec / drainage requirement")
        st.checkbox("Override Sh (default: B31.3 Table A-1 at design T; sustained ≤ Sh, occasional ≤ 1.33 Sh)",
                    key="sc_override_on")
        if st.session_state["sc_override_on"]:
            c1, c2 = st.columns(2)
            c1.number_input(f"Sh override ({u('stress')})", key="sc_Sh_override", min_value=0.0, placeholder="Required")
            c2.text_input("Override source", key="sc_Sh_src", placeholder="e.g. B31.3-2022 Table A-1")

    with st.container(border=True):
        st.markdown("**Section basis & beam model**")
        st.multiselect("End conditions", list(END_CONDITIONS), key="sc_conds", format_func=END_CONDITIONS.get)
        c1, c2 = st.columns(2)
        c1.number_input(f"Corrosion allowance ({u('small_length')})", key="sc_ca", min_value=0.0,
                        step=0.01 if _units() == "US" else 0.5, format="%.3f")
        c2.number_input("Spans (continuous)", key="sc_nspans", min_value=2, max_value=10, step=1)
        st.checkbox(f"Apply {mill_tolerance(_product()):.1%} mill under-tolerance (Z, I, pressure stress)", key="sc_mill",
                    help="12.5% for pipe (A312/A106); 10% for tube (A269).")

    with st.container(border=True):
        st.markdown("**Environmental loads (ASCE 7-16)**")
        t1, t2, t3, t4 = st.columns(4)
        t1.toggle("Wind", key="sc_wind")
        t2.toggle("Snow", key="sc_snow")
        t3.toggle("Ice", key="sc_ice")
        t4.toggle("Seismic", key="sc_eq")
        s = st.session_state
        enabled = [k for k, on in (("Wind", s["sc_wind"]), ("Snow", s["sc_snow"]), ("Ice", s["sc_ice"]),
                                   ("Seismic", s["sc_eq"])) if on]
        if not enabled:
            st.caption("Off: sustained (W + P) and deflection only. Toggle a load to add its occasional case(s).")
        else:
            st.markdown("*Site (shared)*")
            c1, c2, c3 = st.columns(3)
            c1.selectbox("Risk category", asce.RISK_CATEGORIES, key="sc_rc", help="Table 1.5-1")
            c2.selectbox("Exposure", asce.EXPOSURES, key="sc_exp", help="Sec. 26.7.3")
            c3.number_input("K_zt", key="sc_kzt", min_value=1.0, step=0.05, help="Topographic factor, 1.0 if flat (Sec. 26.8.2)")
            c1, c2, c3 = st.columns(3)
            c1.number_input(f"Pipe height z ({u('length')})", key="sc_z", min_value=0.0, help="Centerline above grade")
            c2.number_input(f"Ground elev. ({u('length')})", key="sc_elev", min_value=0.0, placeholder="K_e = 1.0",
                            help="For K_e (Table 26.9-1). Blank uses K_e = 1.0 (always permitted).")
            c3.number_input(f"Insulation ({u('small_length')})", key="sc_ins", min_value=0.0,
                            help="Projected D = OD + 2 × insulation, filled in per pipe size (Fig. 7.13-2 note). "
                                 "Affects wind/snow/ice area only; insulation weight not included.")
            tabs = dict(zip(enabled, st.tabs(enabled)))
            if "Wind" in tabs:
                with tabs["Wind"]:
                    st.caption("OCC-WIND = W + P + 0.6W (Comb. 5)")
                    c1, c2 = st.columns(2)
                    c1.number_input(f"Basic wind speed V ({u('speed')})", key="sc_V", min_value=0.0,
                                    help="Fig. 26.5-1 for risk category")
                    c2.selectbox("Surface", asce.SURFACE_ROUGHNESS, key="sc_rough",
                                 format_func=lambda x: x.replace("_", " "), help="Fig. 29.4-1 (used when D·√q_z > 2.5)")
                    st.number_input("C_f override", key="sc_cf", min_value=0.0, placeholder="Fig. 29.4-1")
                    ref_boxes["wind"] = st.expander("Code tables & worked values")
            if "Snow" in tabs:
                with tabs["Snow"]:
                    st.caption("Sec. 7.13.3 / Fig. 7.13-2 snow on pipes")
                    c1, c2 = st.columns(2)
                    c1.number_input(f"Ground snow p_g ({u('area_load')})", key="sc_pg", min_value=0.0,
                                    help="Fig. 7.2-1 / site study")
                    c2.selectbox("Exposure condition", asce.SNOW_EXPOSURE_CONDITIONS, key="sc_snowcond",
                                 format_func=lambda x: x.replace("_", " "), help="Table 7.3-1")
                    st.radio("Treat snow as", [SUSTAINED, OCCASIONAL], key="sc_snowcat", horizontal=True,
                             help="B31.3 301.6 lists snow under weight effects (sustained); occasional uses 1.33 Sh.")
                    st.checkbox("Wintertime pipe surface > 45°F (snow exempt)", key="sc_warm", help="Sec. 7.13.3")
                    ref_boxes["snow"] = st.expander("Code tables & worked values")
            if "Ice" in tabs:
                with tabs["Ice"]:
                    st.caption("OCC-ICE = W + P + 0.7D_i + 0.7W_i (+S) (Sec. 2.4.3)")
                    c1, c2 = st.columns(2)
                    c1.number_input(f"Ice thickness t ({u('small_length')})", key="sc_t_ice", min_value=0.0,
                                    help="Figs. 10.4-2 to 10.4-6")
                    c2.number_input(f"Concurrent wind V_c ({u('speed')})", key="sc_Vc", min_value=0.0,
                                    help="Figs. 10.4-2 to 10.4-6")
                    st.radio("Treat ice weight as", [SUSTAINED, OCCASIONAL], key="sc_icecat", horizontal=True,
                             help="Sustained adds 0.7D_i to the SUS case (Sec. 2.4.3 item 4).")
                    ref_boxes["ice"] = st.expander("Code tables & worked values")
            if "Seismic" in tabs:
                with tabs["Seismic"]:
                    st.caption("OCC-SEISMIC = W + P + 0.7(E_v + E_h) (Comb. 8)")
                    c1, c2, c3 = st.columns(3)
                    c1.number_input("S_DS (g)", key="sc_sds", min_value=0.0, step=0.05, help="Sec. 11.4.5")
                    c2.selectbox("I_p", [1.0, 1.5], key="sc_ip", help="Sec. 13.1.3")
                    c3.number_input(f"Roof height h ({u('length')})", key="sc_h", min_value=0.0,
                                    help="Average roof height; z/h uses pipe height z (≤ 1.0)")
                    types = asce.piping_types()
                    st.selectbox("Piping type (Table 13.6-1)", list(types), key="sc_ptype",
                                 format_func=lambda k: f"{types[k]['label']} (a_p {types[k]['ap']:g}, R_p {types[k]['Rp']:g})")
                    ref_boxes["seismic"] = st.expander("Code tables & worked values")

# ---------------------------------------------------------------- calculation

inputs = build_inputs()
results: SpanResults | None = None
error: str | None = None
try:
    results = SpanCalculator(inputs, DB).run()
except (SpanInputError, MaterialDataError, ValueError, KeyError) as e:
    error = str(e)


def build_project() -> Project:
    return Project(
        app_name=META["id"],
        app_version=META["version"],
        inputs={"span": inputs.to_project_inputs(),
                "ui": {"mode": st.session_state["sc_mode"], "unit_system": _units()}},
        results=results.to_dict() if results else {},
        warnings=results.warnings if results else [],
        material_citations=results.citations if results else [],
    )


def on_load(project: Project) -> None:
    apply_inputs(SpanInputs.from_project_inputs(project.inputs["span"]), project.inputs.get("ui", {}))


# ---------------------------------------------------------------- chart styling

sys_ = _units()
L_u, d_u, s_u, w_u = u("length"), u("deflection"), u("stress"), u("line_weight")
SZ = SIZE_LABEL[inputs.product]
_theme = getattr(getattr(st, "context", None), "theme", None)
DARK = getattr(_theme, "type", "dark") != "light"
# Reference categorical palette (dataviz skill), fixed per governing case so color follows the case.
_CASE_ORDER = [DEFLECTION, "SUS", "OCC-WIND", "OCC-SEISMIC", "OCC-ICE", "OCC-WIND+SNOW", "OCC-SEISMIC+SNOW", "OCC-SNOW"]
_LIGHT = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#4a3aa7", "#e34948"]
_DARKS = ["#3987e5", "#d95926", "#199e70", "#c98500", "#d55181", "#008300", "#9085e9", "#e66767"]
CASE_COLORS = dict(zip(_CASE_ORDER, _DARKS if DARK else _LIGHT))
MARKERS = {DEFLECTION: "diamond", "SUS": "circle", "OCC-WIND": "triangle-right", "OCC-SEISMIC": "square",
           "OCC-ICE": "star", "OCC-WIND+SNOW": "triangle-left", "OCC-SEISMIC+SNOW": "square-open", "OCC-SNOW": "hexagon"}
END_DASH = {"simply_supported": "solid", "fixed_fixed": "dash", "continuous": "dot", "cantilever": "dashdot"}
LINE_INK = "#8b8a84" if DARK else "#7a7974"
SURFACE = "#0e1117" if DARK else "#ffffff"


def span_chart(results: SpanResults) -> go.Figure:
    fig = go.Figure()
    for cond in inputs.end_conditions:
        xs, ys = [], []
        for sz in results.sizes:
            ec = next(c for c in sz.by_condition if c.end_condition == cond)
            xs.append(sz.nps)
            ys.append(from_si(ec.span, "length", sys_))
        fig.add_trace(go.Scatter(x=xs, y=ys, mode="lines", name=END_CONDITIONS[cond], hoverinfo="skip",
                                 line=dict(color=LINE_INK, width=2, dash=END_DASH[cond]),
                                 legendgroup="ec", legendgrouptitle_text="End condition"))
        if xs:
            fig.add_annotation(x=xs[-1], y=ys[-1], text=END_CONDITIONS[cond], showarrow=False,
                               xanchor="left", xshift=8, font=dict(size=11))
    for case in _CASE_ORDER:
        xs, ys, hover = [], [], []
        for sz in results.sizes:
            for ec in sz.by_condition:
                if ec.governs != case:
                    continue
                others = " · ".join(f"{cs.case} {from_si(cs.span, 'length', sys_):.1f}" for cs in ec.cases)
                xs.append(sz.nps)
                ys.append(from_si(ec.span, "length", sys_))
                hover.append(f"<b>{SZ} {sz.nps} · {END_CONDITIONS[ec.end_condition]}</b><br>"
                             f"Span {ys[-1]:.2f} {L_u}: {CASE_LABELS[case]} governs<br>"
                             f"<span style='font-size:11px'>All cases ({L_u}): {others}</span>")
        if xs:
            fig.add_trace(go.Scatter(
                x=xs, y=ys, mode="markers", name=CASE_LABELS[case], text=hover, hovertemplate="%{text}<extra></extra>",
                marker=dict(color=CASE_COLORS[case], symbol=MARKERS[case], size=11,
                            line=dict(color=SURFACE, width=2)),
                legendgroup="case", legendgrouptitle_text="Governing case"))
    fig.update_layout(
        xaxis=dict(title=SZ + (" (in)" if inputs.product == "tube" else ""), type="category", categoryorder="array",
                   categoryarray=[sz.nps for sz in results.sizes], showgrid=False),
        yaxis=dict(title=f"Max support span ({L_u})", rangemode="tozero", gridwidth=1),
        height=380, margin=dict(t=10, r=95, b=30, l=50), hovermode="closest",
        legend=dict(orientation="h", y=-0.22, groupclick="toggleitem"),
    )
    return fig


# ---------------------------------------------------------------- results (right, always visible)

with right:
    if error:
        st.warning(f"**Cannot compute:** {error}")
    elif results:
        warning_badge(results.warnings)
        st.caption(f"Sh {from_si(results.allowable, 'stress', sys_):,.0f} {s_u} · occasional 1.33 Sh = "
                   f"{from_si(1.33 * results.allowable, 'stress', sys_):,.0f} {s_u} · "
                   f"E {from_si(results.E, 'modulus', sys_):.2f} {u('modulus')}"
                   + (f" · {wall_label(inputs.schedule, inputs.product)} not listed for {SZ} {', '.join(results.skipped)}"
                      if results.skipped else ""))
        if len(results.sizes) == 1:
            sz = results.sizes[0]
            st.markdown(f"#### {SZ} {sz.nps} × {wall_label(sz.schedule, inputs.product)}")
            cols = st.columns(len(sz.by_condition))
            for col, c in zip(cols, sz.by_condition):
                col.metric(END_CONDITIONS[c.end_condition], f"{from_si(c.span, 'length', sys_):.2f} {L_u}",
                           f"{CASE_LABELS[c.governs]} governs", delta_color="off")
        elif results.sizes:
            st.plotly_chart(span_chart(results), width="stretch")

        summary, full = [], []
        for sz in results.sizes:
            for c in sz.by_condition:
                summary.append({
                    SZ: sz.nps, "End condition": END_CONDITIONS[c.end_condition],
                    f"Span ({L_u})": from_si(c.span, "length", sys_), "Governing case": CASE_LABELS[c.governs],
                    f"δ pipe+contents ({d_u})": from_si(c.deflection_pipe_contents, "deflection", sys_),
                    f"δ sustained total ({d_u})": from_si(c.deflection_sustained, "deflection", sys_),
                })
                row = {SZ: sz.nps, "End condition": END_CONDITIONS[c.end_condition],
                       f"Span ({L_u})": from_si(c.span, "length", sys_), "Governs": c.governs}
                for cs in c.cases:
                    row[f"{cs.case} span ({L_u})"] = from_si(cs.span, "length", sys_)
                row[f"S_lp pressure ({s_u})"] = from_si(sz.pressure_stress, "stress", sys_)
                for name, val in sz.loads.items():
                    if val:
                        row[f"w {name} ({w_u})"] = from_si(val, "line_weight", sys_)
                row[f"OD ({u('small_length')})"] = from_si(sz.od, "small_length", sys_)
                row[f"Wall used ({u('small_length')})"] = from_si(sz.wall_used, "small_length", sys_)
                row[f"Z ({u('section_modulus')})"] = from_si(sz.section_modulus, "section_modulus", sys_)
                full.append(row)
        df_sum, df = pd.DataFrame(summary), pd.DataFrame(full)

        tab_sum, tab_all, tab_detail, tab_basis = st.tabs(["Summary", "All cases & loads", "Pipe detail", "Basis"])
        with tab_sum:
            st.dataframe(df_sum, hide_index=True, width="stretch", height=250,
                         column_config={c: st.column_config.NumberColumn(format="%.2f" if "Span" in c else "%.3f")
                                        for c in df_sum.columns if df_sum[c].dtype.kind == "f"})
            st.download_button("Download full table (.csv)", df.to_csv(index=False), file_name="span_chart.csv",
                               mime="text/csv")
        with tab_all:
            st.dataframe(df, hide_index=True, width="stretch", height=250,
                         column_config={c: st.column_config.NumberColumn(format="%.2f" if "span" in c.lower() else "%.3f")
                                        for c in df.columns if df[c].dtype.kind == "f"})
        by_nps = {sz.nps: sz for sz in results.sizes}
        detail = None
        with tab_detail:
            if by_nps:
                if len(by_nps) > 1:
                    pick = st.selectbox(f"{SZ} (also drives the worked values in each load's code-table panel)",
                                        list(by_nps), index=list(by_nps).index("4") if "4" in by_nps else 0,
                                        key="sc_detail_nps")
                else:
                    pick = next(iter(by_nps))
                detail = by_nps[pick]
                st.caption(f"{SZ} {detail.nps} × {wall_label(detail.schedule, inputs.product)}")
                span_refs.pipe_properties(detail, sys_)
        with tab_basis:
            if results.sizes:
                for cl in results.sizes[0].case_loads:
                    st.markdown(f"- **{CASE_LABELS[cl.case]}**: {CASE_BASIS[cl.case]}")
                st.markdown(f"- **{CASE_LABELS[DEFLECTION]}**: {CASE_BASIS[DEFLECTION]}")
            st.markdown("**Data citations**")
            for c in results.citations:
                flag = "✓ verified" if c["verified"] else "⚠ unverified"
                st.markdown(f"- `{c['property']}`: {c['citation']} ({flag})")
            st.markdown("- ASCE 7-16 loads: licensed copy, page cites in `core/loads/data/asce7_16.json` (✓ transcribed)")
            st.caption(SCOPE_NOTE)
        for name, box in ref_boxes.items():
            with box:
                getattr(span_refs, name)(inputs, results, detail)

# ---------------------------------------------------------------- span table generator (PDF) & project file

st.divider()
with st.container(border=True):
    st.markdown(f"**Generate span tables (PDF)**: one table per end condition, {SZ} rows × "
                f"{WALL_LABEL[inputs.product].lower()} columns, using all inputs above")
    gk = TABLE_KEYS[inputs.product]
    c0, c1, c2, c3 = st.columns([6, 1.3, 1.3, 1.6], vertical_alignment="bottom")
    c0.pills(WALL_LABEL[inputs.product] + "s", list_schedules(inputs.product), key=gk["walls"], selection_mode="multi",
             format_func=(lambda w: wall_label(w, "tube")) if inputs.product == "tube" else None)
    c1.selectbox(f"From {SZ}", list_nps(inputs.product), key=gk["from"])
    c2.selectbox(f"To {SZ}", list_nps(inputs.product), key=gk["to"])
    if c3.button("Generate Tables", type="primary", width="stretch"):
        try:
            tables = generate_tables(inputs, list(st.session_state[gk["walls"]] or []),
                                     default_nps_range(st.session_state[gk["from"]], st.session_state[gk["to"]],
                                                       inputs.product), DB)
            stamp = datetime.now().astimezone()
            st.session_state["_tbl_pdf"] = build_pdf(tables, inputs, sys_, META["version"], stamp, DB)
            st.session_state["_tbl_name"] = f"span_tables_{stamp:%Y%m%d_%H%M%S}.pdf"
            st.session_state["_tbl_preview"] = tables
            st.session_state.pop("_tbl_error", None)
        except (SpanInputError, MaterialDataError, ValueError, KeyError) as e:
            st.session_state["_tbl_error"] = str(e)
    if "_tbl_error" in st.session_state:
        st.warning(f"**Cannot generate:** {st.session_state['_tbl_error']}")
    elif "_tbl_pdf" in st.session_state:
        st.download_button(f"Download {st.session_state['_tbl_name']}", st.session_state["_tbl_pdf"],
                           file_name=st.session_state["_tbl_name"], mime="application/pdf")
        t = st.session_state["_tbl_preview"]
        cond = t.end_conditions[0]
        prev = pd.DataFrame(
            {wall_label(sc, t.product): [("-" if t.cells[cond][n][sc] is None else
                            f"{from_si(t.cells[cond][n][sc][0], 'length', sys_):.1f} {t.cells[cond][n][sc][1]}")
                           for n in t.nps] for sc in t.schedules}, index=t.nps)
        with st.expander(f"Preview: {END_CONDITIONS[cond]}, span ({L_u}) and governing case"):
            st.dataframe(prev, width="stretch")

save_load_panel(META, build_project, on_load)
