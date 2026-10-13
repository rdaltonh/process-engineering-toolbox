"""ASCE 7-16 load functions vs. table values and hand calculations."""

import math

import pytest

from proctoolbox_core.loads import asce7_16 as a
from proctoolbox_core.units import convert

IN = 0.0254
PLF = convert(1, "lbf/ft", "N/m")


@pytest.mark.parametrize("z,exp,table", [
    (15, "B", 0.57), (30, "B", 0.70), (100, "B", 0.99),
    (15, "C", 0.85), (30, "C", 0.98), (60, "C", 1.13),
    (15, "D", 1.03), (100, "D", 1.43), (500, "D", 1.89),
])
def test_kz_matches_table_26_10_1(z, exp, table):
    assert a.kz(z, exp) == pytest.approx(table, abs=0.01)  # formula permitted (Note 1); table is rounded


def test_ke():
    assert a.ke(None) == 1.0
    assert a.ke(1000) == pytest.approx(0.96, abs=0.005)  # Table 26.9-1
    assert a.ke(5000) == pytest.approx(0.83, abs=0.005)


def test_wind_hand_calc_small_pipe():
    # 4" pipe, V = 115 mph, z = 20 ft, Exp C: D*sqrt(qz) < 2.5 -> Cf = 1.2
    D_ft = 4.5 / 12
    qz = 0.00256 * a.kz(20, "C") * 1.0 * 1.0 * 1.0 * 115**2
    w = a.wind_load(115, 4.5 * IN, 20, "C")
    assert w.Cf == 1.2
    assert w.w / PLF == pytest.approx(qz * 0.85 * 1.2 * D_ft, rel=1e-9)


def test_wind_cf_large_pipe_uses_roughness():
    w = a.wind_load(150, 24 * IN, 50, "D", roughness="rough")
    assert (24 / 12) * math.sqrt(w.qz_psf) > 2.5
    assert w.Cf == 0.9


def test_snow_pf_and_density():
    # pf = 0.7 * Ce(C, fully) 0.9 * Ct 1.2 * Is(II) 1.0 * 30
    assert a.flat_roof_snow_psf(30, "C", "fully_exposed", "II") == pytest.approx(0.7 * 0.9 * 1.2 * 30)
    assert a.snow_density_pcf(30) == pytest.approx(0.13 * 30 + 14)
    assert a.snow_density_pcf(200) == 30.0


def test_snow_triangle_small_pipe():
    s = a.snow_load(30, 4.5 * IN, "C", "fully_exposed", "II")
    D = 4.5 / 12
    assert s.shape == "triangular"
    assert s.w / PLF == pytest.approx(0.5 * D * 1.37 * D * s.gamma_pcf, rel=1e-9)


def test_snow_trapezoid_large_pipe_and_continuity():
    s = a.snow_load(30, 24 * IN, "C", "fully_exposed", "II")
    assert s.shape == "trapezoidal"
    h = s.pf_psf / s.gamma_pcf
    D = 2.0
    top = D - 2 * h / math.tan(math.radians(70))
    assert s.w / PLF == pytest.approx(s.gamma_pcf * h * (D + top) / 2, rel=1e-9)
    # At the transition D = 0.73 pf/gamma the two shapes agree within rounding of 0.73 / 1.37.
    D_t = 0.73 * h
    tri = 0.5 * D_t * 1.37 * D_t
    trap = h * (D_t + max(D_t - 2 * h / math.tan(math.radians(70)), 0)) / 2
    assert tri == pytest.approx(trap, rel=0.01)


def test_snow_exempt_warm_pipe():
    assert a.snow_load(30, 4.5 * IN, "C", "fully_exposed", "II", surface_above_45F=True).w == 0.0


def test_ice_hand_calc():
    r = a.ice_load(1.0, 40, 4.5 * IN, 20, "C", "III")
    fz = (20 / 33) ** 0.10
    td = 1.0 * 1.15 * fz
    Ai = math.pi * (td / 12) * (4.5 / 12 + td / 12)
    assert r.td_in == pytest.approx(td)
    assert r.w_ice / PLF == pytest.approx(56 * Ai, rel=1e-9)
    qz = 0.00256 * a.kz(20, "C") * 1.0 * 40**2
    assert r.w_wind_ice / PLF == pytest.approx(qz * 0.85 * 1.2 * (4.5 / 12 + 2 * td / 12), rel=1e-9)


def test_seismic_fp_and_bounds():
    r = a.seismic_coefficients(1.0, 1.0, 1.0, "b31_threaded")  # 0.4*2.5*1*(3)/6 = 0.5
    assert r.fp_coeff_raw == pytest.approx(0.5) and r.bound == "none"
    r = a.seismic_coefficients(1.0, 1.0, 0.0, "b31_welded")    # 0.4*2.5/12 = 0.083 -> 0.3
    assert r.fp_coeff == pytest.approx(0.3) and r.bound == "lower"
    r = a.seismic_coefficients(1.0, 1.5, 1.0, "low_deformability")  # 0.4*2.5*3/(3/1.5)=1.5, cap 2.4
    assert r.fp_coeff == pytest.approx(1.5)
    assert r.ev_coeff == pytest.approx(0.2)
    assert a.seismic_coefficients(1.0, 1.0, 5.0, "b31_threaded").fp_coeff_raw == pytest.approx(0.5)  # z/h capped at 1


def test_table_13_6_1_values():
    t = a.piping_types()
    assert (t["b31_welded"]["ap"], t["b31_welded"]["Rp"]) == (2.5, 12.0)
    assert (t["b31_threaded"]["ap"], t["b31_threaded"]["Rp"]) == (2.5, 6.0)
