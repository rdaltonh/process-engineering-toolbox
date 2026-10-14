"""Corrugated hose pressure drop: hand-calc and source-data checks (spec section 6, 8)."""

import math
import statistics

import pytest

import hose_calc
from hose_calc import (
    GAS,
    HAWTHORNE,
    LSU,
    Bend,
    ChokedFlowError,
    HoseCalculator,
    HoseInputError,
    HoseInputs,
    hawthorne_cb,
    hawthorne_dp_psi,
    hawthorne_k_C,
    lsu_alpha_beta,
    lsu_bend_ratio,
)
from proctoolbox_core.fluids import FluidState, state_PT
from proctoolbox_core.io import Project, dumps, loads

IN = 0.0254
FT = 0.3048
PSI = 6894.757293168

# LSU Table I: 1.012 in close-pitch hose (inches).
CP1 = dict(D=1.012 * IN, pitch=0.181 * IN, depth=0.219 * IN, width=0.1094 * IN)
# 1 1/2 in close-pitch hose, used for gas cases.
CP15 = dict(D=1.483 * IN, pitch=0.219 * IN, depth=0.250 * IN, width=0.125 * IN)


def _water(**kw):
    base = dict(fluid="Water", P_in=5e5, T_in=293.15, m_dot=2.0, length=3.0, **CP1)
    base.update(kw)
    return HoseInputs(**base)


def _n2(m_dot, length=10.0, P_in=10e5, **kw):
    return HoseInputs(fluid="Nitrogen", P_in=P_in, T_in=300.0, m_dot=m_dot, length=length, **{**CP15, **kw})


# ---------------------------------------------------------------- wrapper

def test_coolprop_wrapper_water_and_air():
    w = state_PT("Water", 101325, 293.15)
    assert w.is_liquid and w.rho == pytest.approx(998.2, rel=1e-3) and w.mu == pytest.approx(1.0016e-3, rel=1e-2)
    a = state_PT("Air", 101325, 293.15)
    assert not a.is_liquid and a.rho == pytest.approx(1.204, rel=2e-3)


# ---------------------------------------------------------------- Hawthorne

def test_hawthorne_us_form_matches_si():
    """Eq. 5 with the paper's 9266 constant equals N*C*rho*V^2/2 (9266 = 2*32.174*144, rounded)."""
    D, S, L = 1.0 * IN, 0.15 * IN, 1.0
    k, C = hawthorne_k_C(D, S)
    N = L / S
    rho, V = 998.0, 3.0
    dp_si = N * C * rho * V**2 / 2
    dp_us = hawthorne_dp_psi(N, C, V / FT, rho * 0.0624279606) * PSI
    assert dp_us == pytest.approx(dp_si, rel=5e-5)


# Hawthorne p. 100 test table: D, S (in), test C, test f, "C by Eq 5" (spec section 6.2).
H_TABLE = [
    (0.765, 0.125, 0.01225, 0.0750, 0.01667), (1.000, 0.128, 0.01350, 0.1050, 0.01068),
    (1.016, 0.138, 0.01015, 0.0745, 0.01191), (1.284, 0.150, 0.00927, 0.0793, 0.00902),
    (1.500, 0.163, 0.00724, 0.0666, 0.00789), (1.517, 0.200, 0.01050, 0.0795, 0.01128),
    (3.990, 0.252, 0.00376, 0.0598, 0.00282), (3.990, 0.375, 0.00548, 0.0584, 0.00601),
    (4.016, 0.178, 0.00198, 0.0448, 0.00142), (4.016, 0.353, 0.00454, 0.0515, 0.00530),
    (2.000, 0.212, 0.00683, 0.0647, 0.00753), (4.460, 0.167, 0.00168, 0.0448, 0.00102),
]


@pytest.mark.parametrize("D,S,C_test,f_test,C_eq5", H_TABLE)
def test_hawthorne_table(D, S, C_test, f_test, C_eq5):
    assert hawthorne_k_C(D * IN, S * IN)[1] == pytest.approx(C_eq5, abs=5e-6)
    assert f_test * S / D == pytest.approx(C_test, rel=5e-3)  # table's own C = f*S/D note


def test_bend_chart_interpolation():
    assert hawthorne_cb(2.0) == pytest.approx(0.217)
    assert hawthorne_cb(2.125) == pytest.approx((0.217 + 0.187) / 2)
    assert hawthorne_cb(9.0) == pytest.approx(0.074)  # held beyond the chart


# ---------------------------------------------------------------- LSU

# LSU Table III (air): hose ID (in), predicted f/f0 at 60/120/180 deg. Hoses ~10 ft, bent as one arc.
LSU_T3 = [
    (1.299, (1.143, 1.266, 1.382)), (1.560, (1.168, 1.313, 1.450)), (2.573, (1.264, 1.490, 1.705)),
    (1.266, (1.140, 1.260, 1.374)), (1.500, (1.162, 1.302, 1.435)), (2.535, (1.260, 1.484, 1.696)),
]


@pytest.mark.parametrize("D,pred", LSU_T3)
def test_lsu_table3_bend_ratio(D, pred):
    for theta, p in zip((60, 120, 180), pred):
        R = 10 * FT / math.radians(theta)
        assert lsu_bend_ratio(D * IN, R) == pytest.approx(p, rel=5e-3)


def test_cross_check_1in_close_pitch():
    alpha, beta = lsu_alpha_beta("liquid", "annular", CP1["pitch"], CP1["depth"], CP1["width"])
    assert alpha * 1e5**beta == pytest.approx(0.02623, rel=5e-3)
    k, C = hawthorne_k_C(CP1["D"], CP1["pitch"])
    assert C * CP1["D"] / (4 * CP1["pitch"]) == pytest.approx(0.02740, rel=5e-3)


# LSU QPR4 App. III raw water data, 1.012 in close pitch, 0 deg: (Re, Fanning f). Rows with legible f.
QPR4 = [
    (11409, .02131), (16515, .01876), (19087, .01769), (24519, .01839), (33785, .01788), (39164, .01900),
    (43847, .01921), (45541, .01930), (50933, .01950), (56497, .0202), (67790, .0251), (52078, .02306),
    (72181, .02684), (74702, .0193), (77524, .0258), (67285, .01931), (86195, .0168), (69818, .0201),
    (93515, .0223), (83872, .02130), (83872, .02166), (90076, .0219),
    (115764, .0231), (119277, .0237), (121244, .0235), (117726, .0241), (125425, .02461), (131378, .0241),
    (128261, .0258), (101347, .0211), (136922, .0254), (107792, .0235), (141750, .0252), (137990, .0254),
    (146329, .0252), (148664, .0254), (147074, .0255), (153297, .0254), (120760, .0225), (121870, .0244),
    (158691, .0247), (160962, .0259), (155626, .0255), (165605, .02480), (167582, .02609), (167680, .02646),
    (168975, .02638), (163730, .02562), (135474, .02306),
]


@pytest.mark.parametrize("lo,hi", [(1e4, 1e5), (1e5, 1e6)])
def test_lsu_vs_qpr4_raw_water_data(lo, hi):
    alpha, beta = lsu_alpha_beta("liquid", "annular", CP1["pitch"], CP1["depth"], CP1["width"])
    rows = [(re, f) for re, f in QPR4 if lo <= re < hi]
    re_med = statistics.median(r for r, _ in rows)
    f_med = statistics.median(f for _, f in rows)
    assert alpha * re_med**beta == pytest.approx(f_med, rel=0.25)


# ---------------------------------------------------------------- full calc: liquid

def test_liquid_hand_calc_with_sweep_and_tight_bend():
    """Water, 1 in close pitch, 30-deg sweep at R = 4 ft plus 90-deg tight bend at r/D = 2."""
    inp = _water(bends=[Bend(30, 4 * FT), Bend(90, 2 * CP1["D"])])
    res = HoseCalculator(inp).run()
    s = state_PT("Water", inp.P_in, inp.T_in)
    A = math.pi * inp.D**2 / 4
    V = inp.m_dot / (s.rho * A)
    Re = s.rho * V * inp.D / s.mu
    q = s.rho * V**2 / 2
    alpha, beta = lsu_alpha_beta("liquid", "annular", inp.pitch, inp.depth, inp.width)
    f = alpha * Re**beta
    arc = 4 * FT * math.radians(30)
    sweep = 4 * f * arc / inp.D * (lsu_bend_ratio(inp.D, 4 * FT) - 1) * q
    tight = 0.217 * q
    t = res.tracks[LSU]
    assert res.governing == LSU
    assert t.dp_straight == pytest.approx(4 * f * inp.length / inp.D * q, rel=1e-3)
    assert t.dp_bends[0] == pytest.approx(sweep, rel=1e-3)
    assert t.dp_bends[1] == pytest.approx(tight, rel=1e-3)
    assert t.dp_total == pytest.approx(t.dp_straight + sweep + tight, rel=1e-3)
    h = res.tracks[HAWTHORNE]
    k, C = hawthorne_k_C(inp.D, inp.pitch)
    assert h.dp_straight == pytest.approx(inp.length / inp.pitch * C * q, rel=1e-3)
    assert res.spread == pytest.approx(h.dp_total / t.dp_total - 1)
    assert [b.regime for b in res.bends] == ["sweep", "tight"]
    codes = {w.code for w in res.warnings}
    assert "ASSUMPTION" in codes  # partial-arc sweep


def test_laminar_uses_16_over_re():
    res = HoseCalculator(_water(m_dot=0.01)).run()
    for t in res.tracks.values():
        assert t.Re_in < 2000 and t.f_F == pytest.approx(16 / t.Re_in, rel=1e-12)


def test_hawthorne_governs_without_depth_width():
    res = HoseCalculator(_water(depth=None, width=None)).run()
    assert res.governing == HAWTHORNE and LSU not in res.tracks and res.spread is None
    assert any("Hawthorne governs" in w.message for w in res.warnings)


def test_gap_regime_takes_larger():
    D = CP1["D"]
    res = HoseCalculator(_water(bends=[Bend(90, 8 * D)])).run()
    b = res.bends[0]
    assert b.regime == "gap" and b.C_B == pytest.approx(0.074) and b.f_ratio is not None
    t = res.tracks[LSU]
    q = state_PT("Water", 5e5, 293.15).rho * t.V_in**2 / 2
    sweep = 4 * t.f_F * b.arc_length / D * (b.f_ratio - 1)
    assert t.dp_bends[0] == pytest.approx(max(sweep, 0.074) * q, rel=1e-9)


def test_cavitation_flagged_invalid():
    res = HoseCalculator(_water(P_in=1.3e5, T_in=368.15, m_dot=1.0, length=10.0)).run()
    t = res.tracks[LSU]
    assert not t.valid and "cavitation" in t.invalid_reason
    assert any(w.code == "INVALID_RESULT" for w in res.warnings)


# ---------------------------------------------------------------- full calc: gas

@pytest.mark.parametrize("m_dot,basis,lo,hi", [
    (0.20, "inlet density", 0.0, 0.10),
    (0.37, "average density", 0.10, 0.40),
    (0.46, "segment march", 0.40, 1.0),
])
def test_gas_density_branches(m_dot, basis, lo, hi):
    res = HoseCalculator(_n2(m_dot)).run()
    t = res.tracks[LSU]
    assert res.fluid_kind == GAS
    assert t.density_basis.startswith(basis)
    assert lo < t.dp_total / 10e5 <= hi
    assert t.mach_out < 1
    if basis != "inlet density":
        assert t.dp_acc > 0
        assert t.dp_total == pytest.approx(t.dp_straight + sum(t.dp_bends) + t.dp_acc, rel=1e-6)


def test_segment_march_converges():
    calc = HoseCalculator(_n2(0.46, bends=[Bend(90, 3 * CP15["D"], 0.5)]))
    res = calc.run()
    t = res.tracks[LSU]
    s1 = state_PT("Nitrogen", 10e5, 300.0)
    G = 0.46 / (math.pi * CP15["D"] ** 2 / 4)
    track = hose_calc._Track(LSU, calc.inp, GAS, res.bends)
    r2, _ = calc._march(track, s1, G, 2 * t.n_segments)
    assert r2.dp_total == pytest.approx(t.dp_total, rel=5e-3)


def test_choked_flow_refused():
    with pytest.raises(ChokedFlowError):
        HoseCalculator(_n2(0.65)).run()


def test_gas_velocity_limit_warning():
    res = HoseCalculator(_n2(0.40)).run()
    assert res.tracks[LSU].V_out > 42.672
    assert any("UNCONSERVATIVE" in w.message for w in res.warnings)


def test_sweep_points_and_regimes():
    res = HoseCalculator(_n2(0.1, length=3.0, P_in=3e5, sweep_points=12)).run()
    assert len(res.sweep) == 12
    assert res.sweep[0]["m_dot"] == pytest.approx(0.01)
    assert res.sweep[-1]["m_dot"] == pytest.approx(0.2)
    assert {p["regime"] for p in res.sweep} == {"tested", "high_velocity"}
    assert all(p["dp_lsu"] > 0 and p["dp_hawthorne"] > 0 for p in res.sweep)


def test_sweep_marks_choked_points():
    res = HoseCalculator(_n2(0.37, sweep_points=12)).run()
    assert res.sweep[-1]["dp_lsu"] is None and res.sweep[-1]["invalid_lsu"].startswith("Choked")


# ---------------------------------------------------------------- refusals

@pytest.mark.parametrize("bend", [Bend(90, 0.5 * CP1["D"]), Bend(200, 0.5), Bend(0, 0.5)])
def test_bad_bends_refused(bend):
    with pytest.raises(HoseInputError):
        HoseCalculator(_water(bends=[bend])).run()


def test_arc_longer_than_hose_refused():
    with pytest.raises(HoseInputError, match="arc length"):
        HoseCalculator(_water(length=1.0, bends=[Bend(180, 1.0)])).run()


def test_alpha_nonpositive_refused():
    with pytest.raises(HoseInputError, match="alpha"):
        HoseCalculator(_water(width=0.17 * IN)).run()


def test_two_phase_inlet_refused(monkeypatch):
    s = state_PT("Water", 101325, 293.15)
    fake = FluidState(s.fluid, s.P, s.T, s.rho, s.mu, s.h, s.a, "twophase")
    monkeypatch.setattr(hose_calc, "state_PT", lambda *a: fake)
    with pytest.raises(HoseInputError, match="two-phase"):
        HoseCalculator(_water()).run()


# ---------------------------------------------------------------- project file

def test_project_roundtrip():
    inp = _water(bends=[Bend(30, 4 * FT, 0.25), Bend(90, 2 * CP1["D"])], hose_type="helical")
    res = HoseCalculator(inp).run()
    p = Project(app_name="corrugated_hose_dp", app_version="0.1.0", inputs={"hose": inp.to_project_inputs()},
                results=res.to_dict(), warnings=res.warnings, material_citations=res.citations)
    q = loads(dumps(p))
    assert HoseInputs.from_project_inputs(q.inputs["hose"]) == inp
    assert q.results == p.results
    assert q.warnings == p.warnings
