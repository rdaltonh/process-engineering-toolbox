"""Corrugated Hose Pressure Drop: Streamlit UI.

Run standalone:  streamlit run apps/fluid_analysis_design/corrugated_hose_dp/app.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from proctoolbox_core.fluids import COMMON_FLUIDS
from proctoolbox_core.io import Project
from proctoolbox_core.ui import load_app_meta, page_header, save_load_panel, unit_system_toggle, warning_badge
from proctoolbox_core.units import UNIT_SYSTEMS, display_unit, from_si, to_si

from hose_calc import (
    GAS,
    HAWTHORNE,
    HOSE_TYPES,
    LSU,
    METHOD_LABELS,
    SCOPE_NOTE,
    Bend,
    HoseCalculator,
    HoseInputError,
    HoseInputs,
    HoseResults,
    correlations,
)

META = load_app_meta(__file__)
OTHER = "Other (CoolProp name)"

# Widget key -> (HoseInputs attribute, unit kind or None, default in US units).
FIELDS: dict[str, tuple[str, str | None, object]] = {
    "hd_P": ("P_in", "pressure", 100.0),
    "hd_T": ("T_in", "temperature", 70.0),
    "hd_m": ("m_dot", "mass_flow", 10000.0),
    "hd_type": ("hose_type", None, "annular"),
    "hd_D": ("D", "small_length", 1.012),
    "hd_pitch": ("pitch", "small_length", 0.181),
    "hd_depth": ("depth", "small_length", 0.219),
    "hd_width": ("width", "small_length", 0.1094),
    "hd_L": ("length", "length", 10.0),
}
UI_DEFAULTS = {
    "unit_system": "US",
    "_unit_system_prev": "US",
    "hd_fluid": "Water",
    "hd_fluid_other": "",
    "hd_smin": 10.0,
    "hd_smax": 200.0,
    "hd_bends_ver": 0,
}
BEND_COLS = ["Angle (deg)", "Radius", "Position (0-1)"]
for k, v in UI_DEFAULTS.items():
    st.session_state.setdefault(k, v)
for k, (_, _, v) in FIELDS.items():
    st.session_state.setdefault(k, v)
st.session_state.setdefault("hd_bends_df", pd.DataFrame(columns=BEND_COLS, dtype=float))

FIG1 = (
    "LSU Fig. 1 nomenclature (wall section along the hose):\n\n"
    "```\n"
    "   ╭─╮   ╭─╮   ╭─╮      ← outward cavities\n"
    "   │ │   │ │   │ │  ε   (depth: ID line to cavity bottom)\n"
    "───╯ ╰───╯ ╰───╯ ╰───   ← inward convolutions at min ID (D)\n"
    "     |←σ→|              σ = width of the inward convolution\n"
    "   |←— λ —→|            λ = pitch\n"
    "```"
)


def _units() -> str:
    return st.session_state.get("unit_system") or "US"


def u(kind: str) -> str:
    return display_unit(kind, _units())


def _convert_bends(df: pd.DataFrame, old: str, new: str) -> pd.DataFrame:
    df = df.copy()
    if len(df):
        df["Radius"] = [None if pd.isna(r) else round(from_si(to_si(r, UNIT_SYSTEMS[old]["small_length"], "small_length"),
                                                              "small_length", new), 6) for r in df["Radius"]]
    return df


def _set_bends(df: pd.DataFrame) -> None:
    st.session_state["hd_bends_df"] = df.reset_index(drop=True)
    st.session_state["hd_bends_ver"] += 1  # fresh editor key so the new frame is shown


def _on_unit_change() -> None:
    new = st.session_state.get("unit_system") or st.session_state["_unit_system_prev"]
    st.session_state["unit_system"] = new
    old = st.session_state["_unit_system_prev"]
    if new == old:
        return
    for key, (_, kind, _) in FIELDS.items():
        val = st.session_state.get(key)
        if kind and val is not None:
            st.session_state[key] = round(from_si(to_si(val, UNIT_SYSTEMS[old][kind], kind), kind, new), 6)
    cur = st.session_state.get("hd_bends_cur", st.session_state["hd_bends_df"])
    _set_bends(_convert_bends(cur, old, new))
    st.session_state["_unit_system_prev"] = new


def _fluid() -> str:
    s = st.session_state
    return (s["hd_fluid_other"] or "").strip() if s["hd_fluid"] == OTHER else s["hd_fluid"]


def build_inputs(bends_df: pd.DataFrame) -> HoseInputs:
    s, sys_ = st.session_state, _units()
    inp = HoseInputs(fluid=_fluid(), sweep_min=s["hd_smin"] / 100, sweep_max=s["hd_smax"] / 100)
    for key, (attr, kind, _) in FIELDS.items():
        val = s.get(key)
        if kind and val is not None:
            val = to_si(val, UNIT_SYSTEMS[sys_][kind], kind)
        setattr(inp, attr, val)
    for _, row in bends_df.iterrows():
        if pd.isna(row["Angle (deg)"]) and pd.isna(row["Radius"]):
            continue
        if pd.isna(row["Angle (deg)"]) or pd.isna(row["Radius"]):
            raise HoseInputError("Each bend row needs both an angle and a radius.")
        pos = 1.0 if pd.isna(row["Position (0-1)"]) else float(row["Position (0-1)"])
        inp.bends.append(Bend(float(row["Angle (deg)"]),
                              to_si(float(row["Radius"]), UNIT_SYSTEMS[sys_]["small_length"], "small_length"), pos))
    return inp


def apply_inputs(inp: HoseInputs) -> None:
    """Push saved inputs into widget state (called from a load callback)."""
    s, sys_ = st.session_state, _units()
    for key, (attr, kind, _) in FIELDS.items():
        val = getattr(inp, attr)
        if kind and val is not None:
            val = round(from_si(val, kind, sys_), 6)
        s[key] = val
    if inp.fluid in COMMON_FLUIDS:
        s["hd_fluid"], s["hd_fluid_other"] = inp.fluid, ""
    else:
        s["hd_fluid"], s["hd_fluid_other"] = OTHER, inp.fluid
    s["hd_smin"], s["hd_smax"] = inp.sweep_min * 100, inp.sweep_max * 100
    _set_bends(pd.DataFrame(
        [[b.angle_deg, round(from_si(b.radius, "small_length", sys_), 6), b.position] for b in inp.bends],
        columns=BEND_COLS, dtype=float))


# ---------------------------------------------------------------- layout

page_header(META)
unit_system_toggle(on_change=_on_unit_change)
left, right = st.columns([5, 7], gap="large")

with left:
    inputs_box = st.container(height=720, border=False)
with inputs_box:
    with st.container(border=True):
        st.markdown("**Fluid & inlet state** (properties: CoolProp)")
        c1, c2 = st.columns(2)
        c1.selectbox("Fluid", list(COMMON_FLUIDS) + [OTHER], key="hd_fluid",
                     format_func=lambda f: COMMON_FLUIDS.get(f, f))
        if st.session_state["hd_fluid"] == OTHER:
            c2.text_input("CoolProp fluid name", key="hd_fluid_other", placeholder="e.g. Propane")
        c1, c2, c3 = st.columns(3)
        c1.number_input(f"Inlet pressure, abs ({u('pressure')})", key="hd_P", min_value=0.0)
        c2.number_input(f"Inlet temperature ({u('temperature')})", key="hd_T")
        c3.number_input(f"Mass flow ({u('mass_flow')})", key="hd_m", min_value=0.0)

    with st.container(border=True):
        st.markdown("**Hose geometry**")
        st.radio("Corrugation type", list(HOSE_TYPES), key="hd_type", format_func=HOSE_TYPES.get, horizontal=True)
        c1, c2, c3 = st.columns(3)
        sl = u("small_length")
        c1.number_input(f"Min ID, D ({sl})", key="hd_D", min_value=0.0, format="%.4f",
                        help="Minimum inside diameter at the inward convolutions (not nominal size).")
        c2.number_input(f"Pitch, λ ({sl})", key="hd_pitch", min_value=0.0, format="%.4f")
        c3.number_input(f"Live length, L ({u('length')})", key="hd_L", min_value=0.0,
                        help="Developed length along the hose centerline, including bends.")
        c1, c2 = st.columns(2)
        c1.number_input(f"Corrugation depth, ε ({sl})", key="hd_depth", min_value=0.0, format="%.4f",
                        placeholder="optional (LSU)", help=FIG1)
        c2.number_input(f"Inward convolution width, σ ({sl})", key="hd_width", min_value=0.0,
                        format="%.4f", placeholder="optional (LSU)", help=FIG1)
        st.caption("Depth and width enable the LSU correlation (governs). Without them, Hawthorne governs.")

    with st.container(border=True):
        st.markdown("**Bends**")
        st.caption(f"Radius = bend centerline radius ({sl}). R/D ≤ 5: Hawthorne chart; R/D ≥ 12.7: LSU sweep; "
                   "between: larger of the two. Position (fraction of length from inlet) is used only by the gas "
                   "segment march; default 1 = outlet end (worst case).")
        bends_df = st.data_editor(
            st.session_state["hd_bends_df"], key=f"hd_bends_ed_{st.session_state['hd_bends_ver']}",
            num_rows="dynamic", width="stretch", hide_index=True,
            column_config={
                "Angle (deg)": st.column_config.NumberColumn(min_value=0.0, max_value=180.0, step=5.0),
                "Radius": st.column_config.NumberColumn(f"Radius ({sl})", min_value=0.0, format="%.3f"),
                "Position (0-1)": st.column_config.NumberColumn(min_value=0.0, max_value=1.0, step=0.1),
            })
        st.session_state["hd_bends_cur"] = bends_df

    with st.container(border=True):
        st.markdown("**ΔP vs flow sweep**")
        c1, c2 = st.columns(2)
        c1.number_input("From (% of design flow)", key="hd_smin", min_value=1.0, step=10.0)
        c2.number_input("To (% of design flow)", key="hd_smax", min_value=2.0, step=10.0)

# ---------------------------------------------------------------- compute

inputs: HoseInputs | None = None
results: HoseResults | None = None
error = None
try:
    inputs = build_inputs(bends_df)
    results = HoseCalculator(inputs).run()
except (HoseInputError, ValueError) as e:
    error = str(e)


def build_project() -> Project:
    return Project(
        app_name=META["id"],
        app_version=META["version"],
        inputs={"hose": inputs.to_project_inputs() if inputs else {}, "ui": {"unit_system": _units()}},
        results=results.to_dict() if results else {},
        warnings=results.warnings if results else [],
        material_citations=results.citations if results else [],
    )


def on_load(project: Project) -> None:
    apply_inputs(HoseInputs.from_project_inputs(project.inputs["hose"]))


with left:
    save_load_panel(META, build_project, on_load)

# ---------------------------------------------------------------- results

sys_ = _units()
P_u, m_u, v_u = u("pressure"), u("mass_flow"), u("velocity")


def _p(x: float | None) -> str:
    return "-" if x is None else f"{from_si(x, 'pressure', sys_):,.3f}"


def sweep_chart(res: HoseResults) -> go.Figure:
    fig = go.Figure()
    pts = res.sweep
    xs = [from_si(p["m_dot"], "mass_flow", sys_) for p in pts]
    # Shade contiguous non-tested regimes.
    shades = {"laminar": ("rgba(120,120,120,0.15)", "Laminar"), "untested": ("rgba(230,160,0,0.15)", "Outside tested Re"),
              "high_velocity": ("rgba(220,60,60,0.15)", "Gas V > 140 ft/s")}
    start = 0
    for j in range(1, len(pts) + 1):
        if j == len(pts) or pts[j]["regime"] != pts[start]["regime"]:
            reg = pts[start]["regime"]
            if reg in shades:
                x0 = xs[start] if start == 0 else (xs[start - 1] + xs[start]) / 2
                x1 = xs[j - 1] if j == len(pts) else (xs[j - 1] + xs[j]) / 2
                fig.add_vrect(x0=x0, x1=x1, fillcolor=shades[reg][0], line_width=0,
                              annotation_text=shades[reg][1], annotation_position="top left")
            start = j
    for meth, dash in ((LSU, "solid"), (HAWTHORNE, "dash")):
        if f"dp_{meth}" not in pts[0]:
            continue
        ys = [None if p[f"dp_{meth}"] is None else from_si(p[f"dp_{meth}"], "pressure", sys_) for p in pts]
        fig.add_trace(go.Scatter(x=xs, y=ys, mode="lines", name=METHOD_LABELS[meth], line=dict(dash=dash, width=2.5),
                                 hovertemplate=f"%{{x:,.4g}} {m_u}<br>ΔP %{{y:,.4g}} {P_u}<extra>{METHOD_LABELS[meth]}</extra>"))
        bad = [(x, p[f"invalid_{meth}"]) for x, p in zip(xs, pts) if p[f"dp_{meth}"] is None]
        if bad:
            fig.add_trace(go.Scatter(x=[b[0] for b in bad], y=[0] * len(bad), mode="markers", marker_symbol="x",
                                     marker_size=9, name=f"Invalid ({meth})", text=[b[1] for b in bad],
                                     hovertemplate="%{x:,.4g} " + m_u + "<br>%{text}<extra></extra>"))
    g = res.governing_track
    if g.valid:
        fig.add_trace(go.Scatter(x=[from_si(inputs.m_dot, "mass_flow", sys_)], y=[from_si(g.dp_total, "pressure", sys_)],
                                 mode="markers", marker=dict(size=13, symbol="diamond", color="black"),
                                 name="Design point"))
    fig.update_layout(xaxis_title=f"Mass flow ({m_u})", yaxis_title=f"ΔP ({P_u})", height=430,
                      margin=dict(l=10, r=10, t=30, b=10), legend=dict(orientation="h", y=-0.2))
    return fig


with right:
    if error:
        st.warning(f"**Cannot compute:** {error}")
    else:
        res = results
        warning_badge(res.warnings)
        g = res.governing_track
        if not g.valid:
            st.error(f"**Design point invalid:** {g.invalid_reason}")
        c1, c2, c3, c4 = st.columns(4)
        c1.metric(f"ΔP ({P_u})", _p(g.dp_total if g.valid else None), help=f"Governing: {METHOD_LABELS[res.governing]}")
        c2.metric(f"Outlet P, abs ({P_u})", _p(g.P_out if g.valid else None))
        c3.metric(f"Velocity in ({v_u})", f"{from_si(g.V_in, 'velocity', sys_):,.2f}")
        c4.metric("Reynolds (inlet)", f"{g.Re_in:,.0f}")
        if res.spread is not None:
            st.caption(f"Governing: **{METHOD_LABELS[res.governing]}**. Hawthorne differs by "
                       f"**{res.spread:+.0%}**: a rough indicator of method uncertainty.")
        else:
            st.caption(f"Governing: **{METHOD_LABELS[res.governing]}** (LSU needs depth and width).")
        st.plotly_chart(sweep_chart(res), width="stretch")

        tab_m, tab_b, tab_s, tab_basis = st.tabs(["Methods", "Bends", "Sweep table", "Basis"])
        with tab_m:
            rows = []
            for meth, t in res.tracks.items():
                rows.append({
                    "Method": METHOD_LABELS[meth] + (" (governs)" if meth == res.governing else ""),
                    f"ΔP total ({P_u})": _p(t.dp_total) if t.valid else "invalid",
                    f"Straight ({P_u})": _p(t.dp_straight),
                    f"Bends ({P_u})": _p(sum(t.dp_bends)) if t.dp_bends else "-",
                    f"Acceleration ({P_u})": _p(t.dp_acc) if t.dp_acc else "-",
                    "Fanning f (inlet)": f"{t.f_F:.5f}",
                    f"V out ({v_u})": f"{from_si(t.V_out, 'velocity', sys_):,.2f}" if t.valid else "-",
                    "Mach out": f"{t.mach_out:.3f}" if t.mach_out is not None else "-",
                    "Density basis": t.density_basis,
                    "Note": t.invalid_reason,
                })
            st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
            prm = res.params
            sl = u("small_length")
            txt = (f"Hawthorne: k = 0.219·λ = {from_si(prm['k'], 'small_length', sys_):.4f} {sl}, "
                   f"C = {prm['C']:.5f} per corrugation, N = L/λ = {prm['N']:,.0f}.")
            if "alpha" in prm:
                txt += (f"  LSU: α = {prm['alpha']:.5f}, β = {prm['beta']:.4f}, "
                        f"(λ-σ)/ε = {prm['pitch_param']:.3f}, σε/λ² = {prm['shape_param']:.3f}.")
            st.caption(txt)
            st.caption(f"Inlet: {res.phase.replace('_', ' ')}, ρ = {from_si(res.rho_in, 'density', sys_):.4g} "
                       f"{u('density')}, μ = {from_si(res.mu_in, 'viscosity', sys_):.4g} {u('viscosity')}. "
                       f"Treated as {'gas (compressible)' if res.fluid_kind == GAS else 'liquid'}.")
        with tab_b:
            if not res.bends:
                st.caption("No bends entered.")
            else:
                gb = res.governing_track.dp_bends
                st.dataframe(pd.DataFrame([{
                    "#": n, "Angle (deg)": b.angle_deg, "R/D": round(b.r_over_D, 2),
                    "Regime": {"sweep": "LSU sweep", "tight": "Hawthorne tight", "gap": "Gap: larger of both"}[b.regime],
                    "C_B (×θ/90)": "-" if b.C_B is None else f"{b.C_B:.3f}",
                    "LSU f/f0": "-" if b.f_ratio is None else f"{b.f_ratio:.3f}",
                    f"ΔP ({P_u})": _p(gb[n - 1]) if n - 1 < len(gb) else "-",
                    "Dashed chart": "yes" if b.dashed else "",
                } for n, b in enumerate(res.bends, 1)]), hide_index=True, width="stretch")
        with tab_s:
            df = pd.DataFrame([{
                f"Mass flow ({m_u})": from_si(p["m_dot"], "mass_flow", sys_),
                f"Vol. flow in ({u('volume_flow')})": from_si(p["vol_flow_in"], "volume_flow", sys_),
                "Re (inlet)": p["Re"],
                **{f"ΔP {m} ({P_u})": (None if p[f"dp_{m}"] is None else from_si(p[f"dp_{m}"], "pressure", sys_))
                   for m in res.tracks},
                "Regime": p["regime"],
                "Note": "; ".join(p[f"invalid_{m}"] for m in res.tracks if p[f"invalid_{m}"]),
            } for p in res.sweep])
            st.dataframe(df, hide_index=True, width="stretch")
            st.download_button("Download sweep (.csv)", df.to_csv(index=False), file_name="hose_dp_sweep.csv",
                               mime="text/csv")
        with tab_basis:
            c = correlations()
            st.markdown(SCOPE_NOTE)
            st.markdown(
                "- **LSU (governs when depth and width are given):** Fanning f = α·Re^β; "
                "α = a·(λ−σ)/ε + b by fluid (water/air fit) and corrugation type; β = 0.2987·σε/λ² − 0.0313. "
                "Gentle sweeps: f/f₀ = 1 + 7.898·(D/R)^0.896 over the bent arc. "
                "Tested: Re 6,000–380,000 (water), 14,000–580,000 (air, V ≤ 140 ft/s); D 0.535–3.111 in.\n"
                "- **Hawthorne (cross-check / fallback):** each corrugation is a sudden expansion, "
                "k = 0.219·λ, C = [1 − (D/(D+2k))²]², ΔP = (N·C + C_B·θ/90)·ρV²/2. Tested Re 2.4×10⁴–1.3×10⁶.\n"
                "- **Gas:** Crane TP-410: inlet density for ΔP/P₁ ≤ 10%; average density with acceleration term "
                "to 40%; above that, an isenthalpic segment march (≤ 10% ΔP per segment). Mach 1 is refused.\n"
                "- **Liquid:** inlet properties; outlet below saturation pressure is flagged as cavitation.")
            for m in res.tracks:
                st.caption(f"{METHOD_LABELS[m]}: {c[m]['citation']}")
            st.caption("Spec: docs/app-specs/corrugated-hose-dp.md")
