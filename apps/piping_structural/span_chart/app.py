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
from proctoolbox_core.piping import list_nps, list_schedules
from proctoolbox_core.ui import load_app_meta, page_header, save_load_panel, unit_system_toggle, warning_banner
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
    "sc_schedule": ("schedule", None, "40"),
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
    "sc_nps": "2",
    "sc_nps_from": "1/2",
    "sc_nps_to": "24",
    "sc_override_on": False,
    "tbl_scheds": ["40", "80"],
    "tbl_from": "1/2",
    "tbl_to": "24",
}
for k, v in UI_DEFAULTS.items():
    st.session_state.setdefault(k, v)
for k, (_, _, v) in FIELDS.items():
    st.session_state.setdefault(k, list(v) if isinstance(v, list) else v)


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
    all_nps = list_nps()
    if st.session_state["sc_mode"] == "Single size":
        return [st.session_state["sc_nps"]]
    i, j = all_nps.index(st.session_state["sc_nps_from"]), all_nps.index(st.session_state["sc_nps_to"])
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
    s["sc_mode"] = ui_state.get("mode", "Size sweep")
    if s["sc_mode"] == "Single size":
        s["sc_nps"] = inp.nps_list[0]
    else:
        s["sc_nps_from"], s["sc_nps_to"] = inp.nps_list[0], inp.nps_list[-1]


def _label(options: dict[str, str]):
    return lambda k: options.get(k, k)


# ---------------------------------------------------------------- inputs UI

page_header(META)
unit_system_toggle(on_change=_on_unit_change)

with st.container(border=True):
    st.markdown("**Pipe**")
    c1, c2, c3, c4, c5 = st.columns([3, 2, 2, 2, 2])
    c1.selectbox("Material", DB.ids(), key="sc_material", format_func=lambda m: DB.material(m).name)
    c2.selectbox("Schedule", list_schedules(), key="sc_schedule")
    c3.radio("Mode", ["Size sweep", "Single size"], key="sc_mode", horizontal=True)
    if st.session_state["sc_mode"] == "Single size":
        c4.selectbox("NPS", list_nps(), key="sc_nps")
    else:
        c4.selectbox("From NPS", list_nps(), key="sc_nps_from")
        c5.selectbox("To NPS", list_nps(), key="sc_nps_to")
    pipe_box = st.container()

with st.container(border=True):
    st.markdown("**Design condition & allowables (B31.3)**")
    c1, c2, c3 = st.columns(3)
    c1.number_input(f"Design temperature ({u('temperature')})", key="sc_T", help="v1 range: -40°F to +300°F")
    c1.number_input(f"Design pressure, gauge ({u('pressure')})", key="sc_P", min_value=0.0,
                    help="Adds longitudinal pressure stress P·Do/(4t) to every case.")
    c1.number_input("Specific gravity of contents (water @ 60°F = 1.0)", key="sc_sg", min_value=0.0, step=0.05,
                    help="0 = empty pipe")
    c2.markdown("Sh from **B31.3 Table A-1** at design temperature (sustained ≤ Sh, occasional ≤ 1.33 Sh).")
    c2.checkbox("Override Sh", key="sc_override_on")
    if st.session_state["sc_override_on"]:
        c2.number_input(f"Sh override ({u('stress')})", key="sc_Sh_override", min_value=0.0, placeholder="Required")
        c2.text_input("Override source", key="sc_Sh_src", placeholder="e.g. B31.3-2022 Table A-1, A106 B @ 300°F")
    c3.number_input(f"Deflection limit ({u('deflection')})", key="sc_defl", min_value=0.0, placeholder="Required",
                    help="Checked on pipe + contents only. Common practice is 0.1 in (2.5 mm); a design choice, not a code value.")
    c3.text_input("Deflection limit basis", key="sc_defl_basis",
                  placeholder="e.g. project piping spec / drainage requirement")

with st.container(border=True):
    st.markdown("**Section basis & beam model**")
    c1, c2 = st.columns(2)
    c1.number_input(f"Corrosion allowance ({u('small_length')})", key="sc_ca", min_value=0.0,
                    step=0.01 if _units() == "US" else 0.5, format="%.3f")
    c1.checkbox("Apply 12.5% mill under-tolerance to wall (for Z, I, and pressure stress)", key="sc_mill")
    c2.multiselect("End conditions", list(END_CONDITIONS), key="sc_conds", format_func=END_CONDITIONS.get)
    c2.number_input("Number of spans (continuous)", key="sc_nspans", min_value=2, max_value=10, step=1)

ref_boxes: dict = {}
with st.container(border=True):
    st.markdown("**Environmental loads (ASCE 7-16)**: each toggles its own load case(s)")
    t1, t2, t3, t4 = st.columns(4)
    t1.toggle("Wind", key="sc_wind")
    t2.toggle("Snow", key="sc_snow")
    t3.toggle("Ice", key="sc_ice")
    t4.toggle("Seismic", key="sc_eq")
    s = st.session_state
    if s["sc_wind"] or s["sc_snow"] or s["sc_ice"] or s["sc_eq"]:
        st.markdown("*Site (shared)*")
        c1, c2, c3, c4, c5 = st.columns(5)
        c1.selectbox("Risk category", asce.RISK_CATEGORIES, key="sc_rc", help="Table 1.5-1")
        c2.selectbox("Exposure", asce.EXPOSURES, key="sc_exp", help="Sec. 26.7.3")
        c3.number_input(f"Pipe height above grade z ({u('length')})", key="sc_z", min_value=0.0)
        c4.number_input("K_zt", key="sc_kzt", min_value=1.0, step=0.05, help="Topographic factor, 1.0 if flat (Sec. 26.8.2)")
        c5.number_input(f"Ground elevation ({u('length')})", key="sc_elev", min_value=0.0, placeholder="K_e = 1.0",
                        help="For K_e (Table 26.9-1). Blank uses K_e = 1.0 (always permitted).")
        st.number_input(f"Insulation thickness ({u('small_length')})", key="sc_ins", min_value=0.0,
                        help="Projected diameter D = OD + 2 × insulation, filled in per pipe size (ASCE 7-16 Fig. 7.13-2 note). "
                             "Affects wind/snow/ice area only; insulation weight is not included.")
    if s["sc_wind"]:
        st.markdown("*Wind (Ch. 26/29): OCC-WIND = W+P + 0.6W*")
        c1, c2, c3 = st.columns(3)
        c1.number_input(f"Basic wind speed V ({u('speed')})", key="sc_V", min_value=0.0, help="Fig. 26.5-1 for risk category")
        c2.selectbox("Surface", asce.SURFACE_ROUGHNESS, key="sc_rough", format_func=lambda x: x.replace("_", " "),
                     help="Fig. 29.4-1 (only used when D·√q_z > 2.5)")
        c3.number_input("C_f override", key="sc_cf", min_value=0.0, placeholder="Fig. 29.4-1")
        ref_boxes["wind"] = st.expander("ASCE 7-16 wind: code tables & worked values")
    if s["sc_snow"]:
        st.markdown("*Snow (Sec. 7.13.3, Fig. 7.13-2)*")
        c1, c2, c3, c4 = st.columns(4)
        c1.number_input(f"Ground snow p_g ({u('area_load')})", key="sc_pg", min_value=0.0, help="Fig. 7.2-1 / site study")
        c2.selectbox("Exposure condition", asce.SNOW_EXPOSURE_CONDITIONS, key="sc_snowcond",
                     format_func=lambda x: x.replace("_", " "), help="Table 7.3-1")
        c3.radio("Treat snow as", [SUSTAINED, OCCASIONAL], key="sc_snowcat", horizontal=True,
                 help="B31.3 301.6 lists snow under weight effects (sustained); occasional uses 1.33 Sh.")
        c4.checkbox("Wintertime pipe surface > 45°F (exempt)", key="sc_warm", help="Sec. 7.13.3")
        ref_boxes["snow"] = st.expander("ASCE 7-16 snow: code tables & worked values")
    if s["sc_ice"]:
        st.markdown("*Ice (Ch. 10): OCC-ICE = W+P + 0.7Di + 0.7Wi (+S)*")
        c1, c2, c3 = st.columns(3)
        c1.number_input(f"Nominal ice thickness t ({u('small_length')})", key="sc_t_ice", min_value=0.0,
                        help="Figs. 10.4-2 to 10.4-6")
        c2.number_input(f"Concurrent wind V_c ({u('speed')})", key="sc_Vc", min_value=0.0, help="Figs. 10.4-2 to 10.4-6")
        c3.radio("Treat ice weight as", [SUSTAINED, OCCASIONAL], key="sc_icecat", horizontal=True,
                 help="Sustained adds 0.7Di to the SUS case (ASCE 2.4.3 item 4).")
        ref_boxes["ice"] = st.expander("ASCE 7-16 ice: code tables & worked values")
    if s["sc_eq"]:
        st.markdown("*Seismic (Sec. 13.3.1): OCC-SEISMIC = W+P + 0.7(Ev + Eh)*")
        c1, c2, c3, c4 = st.columns(4)
        c1.number_input("S_DS (g)", key="sc_sds", min_value=0.0, step=0.05, help="Sec. 11.4.5")
        c2.selectbox("I_p", [1.0, 1.5], key="sc_ip", help="Sec. 13.1.3")
        c3.number_input(f"Average roof height h ({u('length')})", key="sc_h", min_value=0.0,
                        help="z/h uses pipe height z above; z/h ≤ 1.0")
        types = asce.piping_types()
        c4.selectbox("Piping type (Table 13.6-1)", list(types), key="sc_ptype",
                     format_func=lambda k: f"{types[k]['label']} (a_p {types[k]['ap']:g}, R_p {types[k]['Rp']:g})")
        ref_boxes["seismic"] = st.expander("ASCE 7-16 seismic: code tables & worked values")

st.info(SCOPE_NOTE)

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


# ---------------------------------------------------------------- results UI

sys_ = _units()
L_u, d_u, s_u, w_u = u("length"), u("deflection"), u("stress"), u("line_weight")
MARKERS = {"SUS": "circle", "DEFLECTION": "diamond", "OCC-WIND": "triangle-right", "OCC-WIND+SNOW": "triangle-left",
           "OCC-SEISMIC": "square", "OCC-SEISMIC+SNOW": "square-open", "OCC-ICE": "star", "OCC-SNOW": "hexagon"}

if error:
    st.warning(f"**Cannot compute:** {error}")
elif results:
    warning_banner(results.warnings)
    st.caption(f"Sh = {from_si(results.allowable, 'stress', sys_):,.0f} {s_u} ({results.allowable_citation}); "
               f"occasional limit 1.33 Sh = {from_si(1.33 * results.allowable, 'stress', sys_):,.0f} {s_u}; "
               f"E = {from_si(results.E, 'modulus', sys_):.2f} {u('modulus')}")
    if results.skipped:
        st.caption(f"Schedule {inputs.schedule} not listed for NPS: {', '.join(results.skipped)}")

    # Pipe properties and worked values for one size (auto-populated from the evaluated pipe).
    by_nps = {sz.nps: sz for sz in results.sizes}
    detail = None
    if by_nps:
        with pipe_box:
            if len(by_nps) > 1:
                pick = st.selectbox("Show pipe properties & worked load values for NPS", list(by_nps),
                                    index=min(len(by_nps) - 1, list(by_nps).index("4") if "4" in by_nps else 0),
                                    key="sc_detail_nps")
            else:
                pick = next(iter(by_nps))
            detail = by_nps[pick]
            with st.expander(f"Pipe properties: NPS {detail.nps} Sch {detail.schedule}"):
                span_refs.pipe_properties(detail, sys_)
    for name, box in ref_boxes.items():
        with box:
            getattr(span_refs, name)(inputs, results, detail)

    rows = []
    for sz in results.sizes:
        for c in sz.by_condition:
            row = {
                "NPS": sz.nps,
                "End condition": END_CONDITIONS[c.end_condition],
                f"Span ({L_u})": from_si(c.span, "length", sys_),
                "Governs": c.governs,
                f"δ pipe+contents ({d_u})": from_si(c.deflection_pipe_contents, "deflection", sys_),
                f"δ sustained total ({d_u})": from_si(c.deflection_sustained, "deflection", sys_),
            }
            for cs in c.cases:
                row[f"{cs.case} span ({L_u})"] = from_si(cs.span, "length", sys_)
            row[f"S_lp pressure ({s_u})"] = from_si(sz.pressure_stress, "stress", sys_)
            for name, val in sz.loads.items():
                if val:
                    row[f"w {name} ({w_u})"] = from_si(val, "line_weight", sys_)
            row[f"OD ({u('small_length')})"] = from_si(sz.od, "small_length", sys_)
            row[f"Wall used ({u('small_length')})"] = from_si(sz.wall_used, "small_length", sys_)
            row[f"Z ({u('section_modulus')})"] = from_si(sz.section_modulus, "section_modulus", sys_)
            rows.append(row)
    df = pd.DataFrame(rows)

    if len(results.sizes) == 1:
        sz = results.sizes[0]
        st.subheader(f"NPS {sz.nps} Sch {sz.schedule}")
        cols = st.columns(len(sz.by_condition))
        for col, c in zip(cols, sz.by_condition):
            col.metric(END_CONDITIONS[c.end_condition], f"{from_si(c.span, 'length', sys_):.2f} {L_u}",
                       f"{CASE_LABELS[c.governs]} governs", delta_color="off")
    elif results.sizes:
        fig = go.Figure()
        for cond in inputs.end_conditions:
            sub = df[df["End condition"] == END_CONDITIONS[cond]]
            fig.add_trace(go.Scatter(
                x=sub["NPS"], y=sub[f"Span ({L_u})"], mode="lines+markers", name=END_CONDITIONS[cond],
                marker=dict(symbol=[MARKERS.get(g, "circle") for g in sub["Governs"]], size=10),
                customdata=sub[["Governs"]],
                hovertemplate="NPS %{x}<br>Span %{y:.2f} " + L_u + "<br>%{customdata[0]} governs<extra>%{fullData.name}</extra>",
            ))
        fig.update_layout(xaxis_title="NPS", yaxis_title=f"Max support span ({L_u})", xaxis=dict(type="category"),
                          height=460, margin=dict(t=30), legend=dict(orientation="h", y=1.08))
        st.plotly_chart(fig, width="stretch")
        present = sorted({g for g in df["Governs"]})
        st.caption("Governing case markers: " + " · ".join(f"{MARKERS.get(g, 'circle')} = {CASE_LABELS[g]}" for g in present))

    st.dataframe(df, hide_index=True, width="stretch",
                 column_config={c: st.column_config.NumberColumn(format="%.3f") for c in df.columns if df[c].dtype.kind == "f"})
    st.download_button("Download table (.csv)", df.to_csv(index=False), file_name="span_chart.csv", mime="text/csv")

    with st.expander("Load cases & basis"):
        if results.sizes:
            for cl in results.sizes[0].case_loads:
                st.markdown(f"- **{CASE_LABELS[cl.case]}**: {CASE_BASIS[cl.case]}")
            st.markdown(f"- **{CASE_LABELS[DEFLECTION]}**: {CASE_BASIS[DEFLECTION]}")
        d = results.load_details
        if "wind" in d:
            st.markdown(f"- Wind: q_z = {d['wind']['qz_psf']:.2f} psf, K_z = {d['wind']['Kz']:.3f}, "
                        f"K_e = {d['wind']['Ke']:.3f}, G = {d['wind']['G']}, K_d = 1.0")
        if "snow" in d:
            st.markdown(f"- Snow: p_f = {d['snow']['pf_psf']:.2f} psf, γ = {d['snow']['gamma_pcf']:.1f} pcf")
        if "ice" in d:
            st.markdown(f"- Ice: t_d = {d['ice']['td_in']:.3f} in (f_z = {d['ice']['fz']:.3f}), "
                        f"concurrent q_z = {d['ice']['qz_concurrent_psf']:.2f} psf")
        if "seismic" in d:
            e = d["seismic"]
            st.markdown(f"- Seismic: a_p = {e['ap']:g}, R_p = {e['Rp']:g}, F_p/W_p = {e['Fp_over_Wp']:.3f} "
                        f"(eq. 13.3-1 gives {e['Fp_over_Wp_raw']:.3f}; bound: {e['bound']}), E_v/W_p = {e['Ev_over_Wp']:.3f}")
        st.markdown("**Data citations**")
        for c in results.citations:
            flag = "✓ verified" if c["verified"] else "⚠ unverified"
            st.markdown(f"- `{c['property']}`: {c['citation']} ({flag})")
        st.markdown("- ASCE 7-16 loads: Dalton's licensed copy, page cites in `core/loads/data/asce7_16.json` (✓ transcribed from source)")

# ---------------------------------------------------------------- span table generator (PDF)

with st.container(border=True):
    st.markdown("**Generate span tables (PDF)**: one table per end condition, NPS rows × schedule columns, "
                "using all inputs above")
    st.pills("Schedules", list_schedules(), key="tbl_scheds", selection_mode="multi")
    c1, c2, c3 = st.columns([2, 2, 3])
    c1.selectbox("From NPS", list_nps(), key="tbl_from")
    c2.selectbox("To NPS", list_nps(), key="tbl_to")
    if c3.button("Generate Tables", type="primary", width="stretch"):
        try:
            tables = generate_tables(inputs, list(st.session_state["tbl_scheds"] or []),
                                     default_nps_range(st.session_state["tbl_from"], st.session_state["tbl_to"]), DB)
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
            {f"Sch {sc}": [("-" if t.cells[cond][n][sc] is None else
                            f"{from_si(t.cells[cond][n][sc][0], 'length', sys_):.1f} {t.cells[cond][n][sc][1]}")
                           for n in t.nps] for sc in t.schedules}, index=t.nps)
        st.caption(f"Preview: {END_CONDITIONS[cond]}, span ({L_u}) and governing case")
        st.dataframe(prev, width="stretch")

save_load_panel(META, build_project, on_load)
