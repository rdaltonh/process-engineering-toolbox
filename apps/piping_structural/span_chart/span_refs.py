"""In-app ASCE 7-16 reference tables and worked values for the Span Chart.

Each render_* function writes into a Streamlit container: the governing code
equations, the source tables (with the row in use highlighted), and the
values actually used for the pipe size being inspected.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from proctoolbox_core.loads import asce7_16 as asce
from proctoolbox_core.units import display_unit, from_si

from span_calc import SizeResult, SpanInputs, SpanResults

HIGHLIGHT = "background-color: rgba(255, 170, 0, 0.25)"


def _table(rows: list[dict], highlight: str | None = None, key: str = "") -> None:
    df = pd.DataFrame(rows).map(lambda v: f"{v:g}" if isinstance(v, float) else v)
    if highlight is not None and key in df.columns:
        styled = df.style.apply(lambda r: [HIGHLIGHT if r[key] == highlight else "" for _ in r], axis=1)
        st.dataframe(styled, hide_index=True, width="stretch")
    else:
        st.dataframe(df, hide_index=True, width="stretch")


def _worked(rows: list[tuple[str, str]]) -> None:
    st.dataframe(pd.DataFrame(rows, columns=["Quantity", "Value"]), hide_index=True, width="stretch")


def pipe_properties(sz: SizeResult, system: str) -> None:
    u = lambda k: display_unit(k, system)  # noqa: E731
    rows = [
        ("OD", f"{from_si(sz.od, 'small_length', system):.3f} {u('small_length')}"),
        ("Wall, nominal / used for Z, I, S_lp", f"{from_si(sz.wall_nominal, 'small_length', system):.3f} / "
                                                 f"{from_si(sz.wall_used, 'small_length', system):.3f} {u('small_length')}"),
        ("ID (nominal)", f"{from_si(sz.od - 2 * sz.wall_nominal, 'small_length', system):.3f} {u('small_length')}"),
        ("Metal area (nominal)", f"{from_si(sz.metal_area, 'area', system):.3f} {u('area')}"),
        ("Flow area (nominal ID)", f"{from_si(sz.flow_area, 'area', system):.3f} {u('area')}"),
        ("Projected diameter D (OD + 2·insulation)", f"{from_si(sz.projected_diameter, 'small_length', system):.3f} {u('small_length')}"),
        ("Moment of inertia I", f"{from_si(sz.inertia, 'inertia', system):.4g} {u('inertia')}"),
        ("Section modulus Z", f"{from_si(sz.section_modulus, 'section_modulus', system):.4g} {u('section_modulus')}"),
        ("Pipe weight", f"{from_si(sz.loads['pipe'], 'line_weight', system):.3f} {u('line_weight')}"),
        ("Contents weight", f"{from_si(sz.loads['contents'], 'line_weight', system):.3f} {u('line_weight')}"),
        ("Longitudinal pressure stress P·Do/(4t)", f"{from_si(sz.pressure_stress, 'stress', system):,.0f} {u('stress')}"),
    ]
    _worked(rows)


def wind(inp: SpanInputs, res: SpanResults, sz: SizeResult | None) -> None:
    d = asce.data()["wind"]
    st.markdown(
        "**Equations**  \n"
        "q_z = 0.00256 K_z K_zt K_d K_e V² (psf, V mph): Eq. 26.10-1, p. 268  \n"
        "K_z = 2.01 (z/z_g)^(2/α) for 15 ft ≤ z ≤ z_g; z < 15 ft uses z = 15 ft: Table 26.10-1 Note 1  \n"
        "K_e = e^(−0.0000362 z_g,elev), or 1.0: Table 26.9-1 Note 2  \n"
        "F = q_z G C_f A_f, so w = q_z G C_f D per unit length: Eq. 29.4-1, p. 322  \n"
        "ASD: OCC-WIND uses 0.6W (Comb. 5); with snow 0.75(0.6W) + 0.75S (Comb. 6): Sec. 2.4.1, p. 8"
    )
    st.markdown("**Table 26.11-1 Terrain Exposure Constants** (p. 269)")
    t = d["terrain_exposure_constants"]
    _table([{"Exposure": e, "α": t[e]["alpha"], "z_g (ft)": t[e]["zg_ft"]} for e in asce.EXPOSURES],
           inp.site.exposure, "Exposure")
    cf = d["cf_round_h_over_d_25"]
    st.markdown("**Fig. 29.4-1 Force Coefficient C_f, round, h/D = 25** (p. 325) · "
                f"K_d = {d['kd_round']['value']} (Table 26.6-1 round) · G = {d['gust_factor_rigid']['value']} (Sec. 26.11.1)")
    rough = inp.wind.roughness
    rows = [{"Condition": f"D√q_z > 2.5, {k.replace('_', ' ')}", "C_f": v} for k, v in cf["above_threshold"].items()]
    rows.append({"Condition": "D√q_z ≤ 2.5, all surfaces", "C_f": cf["at_or_below_threshold"]})
    sel = None
    if sz and "wind" in sz.env_details:
        sel = ("D√q_z ≤ 2.5, all surfaces" if sz.env_details["wind"]["D_sqrt_qz"] <= 2.5
               else f"D√q_z > 2.5, {rough.replace('_', ' ')}")
    _table(rows, sel, "Condition")
    if sz and "wind" in sz.env_details:
        w, g = sz.env_details["wind"], res.load_details["wind"]
        st.markdown(f"**Worked values, NPS {sz.nps}**")
        _worked([
            ("K_z", f"{g['Kz']:.3f}"), ("K_e", f"{g['Ke']:.3f}"), ("q_z", f"{g['qz_psf']:.2f} psf"),
            ("D (projected)", f"{w['D_ft']:.4f} ft"), ("D√q_z", f"{w['D_sqrt_qz']:.3f}"), ("C_f", f"{w['Cf']:.2f}"),
            ("w = q_z G C_f D (strength)", f"{w['w_plf']:.3f} lb/ft"), ("0.6 w (ASD)", f"{0.6 * w['w_plf']:.3f} lb/ft"),
        ])


def snow(inp: SpanInputs, res: SpanResults, sz: SizeResult | None) -> None:
    d = asce.data()["snow"]
    imp = asce.data()["importance_factors"]
    st.markdown(
        "**Equations**  \n"
        "p_f = 0.7 C_e C_t I_s p_g: Eq. 7.3-1, p. 51  \n"
        "γ = 0.13 p_g + 14 ≤ 30 pcf: Eq. 7.7-1, p. 59  \n"
        "Pipe (Sec. 7.13.3, Fig. 7.13-2, p. 64): D ≤ 0.73 p_f/γ: triangle 1.37D high, w = ½·D·1.37D·γ; "
        "D > 0.73 p_f/γ: trapezoid h = p_f/γ with 70° sides, w = γ·h·(D + D − 2h/tan 70°)/2  \n"
        "Not required if wintertime pipe surface > 45°F. C_t = 1.2 for unheated/open-air (Table 7.3-2, Sec. 7.13)"
    )
    st.markdown("**Table 7.3-1 Exposure Factor C_e** (p. 58)")
    ce = d["exposure_factor_ce"]
    rows = [{"Surface roughness": e, **{k.replace("_", " "): v for k, v in ce[e].items()}} for e in asce.EXPOSURES]
    _table(rows, inp.site.exposure, "Surface roughness")
    st.markdown("**Table 1.5-2 Snow Importance Factor I_s** (p. 5)")
    _table([{"Risk category": k, "I_s": v} for k, v in imp["snow_Is"].items()], inp.site.risk_category, "Risk category")
    if sz and "snow" in sz.env_details:
        s, g = sz.env_details["snow"], res.load_details["snow"]
        st.markdown(f"**Worked values, NPS {sz.nps}**")
        _worked([
            ("p_f", f"{g['pf_psf']:.2f} psf"), ("γ", f"{g['gamma_pcf']:.2f} pcf"), ("h = p_f/γ", f"{s['h_ft']:.3f} ft"),
            ("Transition D = 0.73 p_f/γ", f"{s['transition_D_ft']:.3f} ft"), ("D (projected)", f"{s['D_ft']:.4f} ft"),
            ("Shape", s["shape"]), ("w (snow on pipe)", f"{s['w_plf']:.3f} lb/ft"),
        ])


def ice(inp: SpanInputs, res: SpanResults, sz: SizeResult | None) -> None:
    d = asce.data()["ice"]
    imp = asce.data()["importance_factors"]
    st.markdown(
        "**Equations**  \n"
        "t_d = t I_i f_z (K_zt)^0.35: Eq. 10.4-5, p. 71 · f_z = (z/33)^0.10 ≤ 1.4: Eq. 10.4-4, p. 70  \n"
        "A_i = π t_d (D_c + t_d): Eq. 10.4-1, p. 70 · ice density ≥ 56 pcf (Sec. 10.4.1)  \n"
        "Wind on ice: projected D + 2t_d, concurrent V_c, I_w = 1.0, C_f = 1.2 (Sec. 10.5.1 → Fig. 29.4-1)  \n"
        "ASD (Sec. 2.4.3, pp. 8–9): 0.7D_i added to D; D + 0.7D_i + 0.7W_i + S"
    )
    st.markdown("**Table 1.5-2 Ice Importance Factors** (p. 5)")
    _table([{"Risk category": k, "I_i (thickness)": imp["ice_thickness_Ii"][k], "I_w (wind)": imp["ice_wind_Iw"][k]}
            for k in asce.RISK_CATEGORIES], inp.site.risk_category, "Risk category")
    if sz and "ice" in sz.env_details:
        i, g = sz.env_details["ice"], res.load_details["ice"]
        st.markdown(f"**Worked values, NPS {sz.nps}**")
        _worked([
            ("f_z", f"{g['fz']:.3f}"), ("t_d", f"{g['td_in']:.3f} in"), ("D_c (projected)", f"{i['Dc_ft']:.4f} ft"),
            ("A_i", f"{i['Ai_ft2']:.5f} ft²"), (f"D_i = {d['density_pcf']['value']:g} pcf × A_i", f"{i['Di_plf']:.3f} lb/ft"),
            ("Concurrent q_z", f"{g['qz_concurrent_psf']:.2f} psf"), ("D for wind (D + 2t_d)", f"{i['D_wind_ft']:.4f} ft"),
            ("W_i (strength)", f"{i['Wi_plf']:.3f} lb/ft"),
        ])


def seismic(inp: SpanInputs, res: SpanResults, sz: SizeResult | None) -> None:
    st.markdown(
        "**Equations** (Sec. 13.3.1, p. 123)  \n"
        "F_p = 0.4 a_p S_DS W_p (1 + 2z/h) / (R_p/I_p): Eq. 13.3-1 · z/h ≤ 1.0  \n"
        "0.3 S_DS I_p W_p ≤ F_p ≤ 1.6 S_DS I_p W_p: Eqs. 13.3-2, 13.3-3  \n"
        "Vertical: concurrent ±0.2 S_DS W_p (Sec. 13.3.1.2)  \n"
        "ASD (Sec. 2.4.5, p. 9): 0.7(E_v + E_h) (Comb. 8); with snow 0.525E + 0.75S (Comb. 9)"
    )
    st.markdown("**Table 13.6-1 Distribution Systems (piping)** (p. 129)")
    types = asce.piping_types()
    _table([{"Piping": v["label"], "a_p": v["ap"], "R_p": v["Rp"]} for v in types.values()],
           types[inp.seismic.piping_type]["label"], "Piping")
    if sz and "seismic" in sz.env_details:
        s, g = sz.env_details["seismic"], res.load_details["seismic"]
        zh = min(inp.site.height / inp.seismic.structure_height, 1.0) if inp.seismic.structure_height else 0
        st.markdown(f"**Worked values, NPS {sz.nps}**")
        _worked([
            ("z/h", f"{zh:.3f}"), ("F_p/W_p by Eq. 13.3-1", f"{g['Fp_over_Wp_raw']:.4f}"),
            ("Bounds", f"{0.3 * inp.seismic.sds * inp.seismic.ip:.4f} to {1.6 * inp.seismic.sds * inp.seismic.ip:.4f}"),
            ("F_p/W_p used", f"{g['Fp_over_Wp']:.4f} ({g['bound']} bound)" if g["bound"] != "none" else f"{g['Fp_over_Wp']:.4f}"),
            ("W_p (pipe + contents)", f"{s['Wp_plf']:.3f} lb/ft"), ("F_p (strength)", f"{s['Fp_plf']:.3f} lb/ft"),
            ("E_v = 0.2 S_DS W_p", f"{s['Ev_plf']:.3f} lb/ft"),
            ("ASD: 0.7F_p / 0.7E_v", f"{0.7 * s['Fp_plf']:.3f} / {0.7 * s['Ev_plf']:.3f} lb/ft"),
        ])
