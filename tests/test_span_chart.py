import math

import pytest

from proctoolbox_core.io import Project, dumps, loads
from proctoolbox_core.units import convert
from span_calc import (
    CANTILEVER,
    CONTINUOUS,
    DEFLECTION,
    END_CONDITIONS,
    FIXED_FIXED,
    OCC_ICE,
    OCC_SEISMIC,
    OCC_SEISMIC_SNOW,
    OCC_SNOW,
    OCC_WIND,
    OCC_WIND_SNOW,
    OCCASIONAL,
    SIMPLY_SUPPORTED,
    SUS,
    SpanCalculator,
    SpanInputError,
    SpanInputs,
    beam_coefficients,
)

IN = 0.0254
PSI = 6894.757293168
LBF_FT = convert(1, "lbf/ft", "N/m")


# ---------------------------------------------------------------- beam solver

def test_solver_reproduces_closed_forms():
    c, m = beam_coefficients(1)
    assert c == pytest.approx(5 / 384, rel=1e-6) and m == pytest.approx(1 / 8, rel=1e-6)
    c, m = beam_coefficients(1, fixed_ends=True)
    assert c == pytest.approx(1 / 384, rel=1e-6) and m == pytest.approx(1 / 12, rel=1e-6)


def test_solver_continuous_beam_table_values():
    assert beam_coefficients(2)[1] == pytest.approx(0.125, rel=1e-6)
    assert beam_coefficients(3)[1] == pytest.approx(0.100, rel=1e-6)
    assert beam_coefficients(3)[0] == pytest.approx(0.0069, rel=5e-3)
    assert beam_coefficients(5)[1] == pytest.approx(2 / 19, rel=1e-6)


# ---------------------------------------------------------------- helpers

def _inputs(**kw):
    base = dict(
        material_id="carbon_steel", schedule="40", nps_list=["4"],
        design_temperature=convert(70, "degF", "kelvin"),
        deflection_limit=10 * IN, deflection_limit_basis="test",  # loose: let stress cases govern
        contents_sg=1.0, mill_tolerance=False,
        end_conditions=[SIMPLY_SUPPORTED],
    )
    base.update(kw)
    return SpanInputs(**base)


def _section(od=4.5, wall=0.237):
    di = od - 2 * wall
    I = math.pi / 64 * (od**4 - di**4)
    return di, I, I / (od / 2), math.pi / 4 * (od**2 - di**2), math.pi / 4 * di**2


def _w_op_lb_in(od=4.5, wall=0.237, rho=0.283, sg=1.0):
    di, I, Z, Am, Af = _section(od, wall)
    return rho * Am + sg * (62.37 / 1728) * Af


def _span(res, case):
    return next(c.span for c in res.cases if c.case == case)


# ---------------------------------------------------------------- sustained / deflection

@pytest.mark.parametrize("cond,k,c", [(SIMPLY_SUPPORTED, 8, 5 / 384), (FIXED_FIXED, 12, 1 / 384), (CANTILEVER, 2, 1 / 8)])
def test_sustained_and_deflection_match_hand_calc(cond, k, c):
    r = SpanCalculator(_inputs(end_conditions=[cond], deflection_limit=0.1 * IN)).run()
    res = r.sizes[0].by_condition[0]
    di, I, Z, *_ = _section()
    w = _w_op_lb_in()
    Sh = 20000.0  # A-1 carbon steel (unverified data)
    assert r.allowable / PSI == pytest.approx(Sh, rel=1e-6)
    assert _span(res, SUS) / 0.3048 == pytest.approx(math.sqrt(k * Z * Sh / w) / 12, rel=1e-3)
    assert _span(res, DEFLECTION) / 0.3048 == pytest.approx((0.1 * 29.5e6 * I / (c * w)) ** 0.25 / 12, rel=1e-3)


def test_pressure_reduces_available_stress():
    P = 300.0
    r = SpanCalculator(_inputs(design_pressure=P * PSI)).run()
    sz = r.sizes[0]
    di, I, Z, *_ = _section()
    S_lp = P * 4.5 / (4 * 0.237)
    assert sz.pressure_stress / PSI == pytest.approx(S_lp, rel=1e-6)
    L = _span(sz.by_condition[0], SUS) / 0.3048
    assert L == pytest.approx(math.sqrt(8 * Z * (20000 - S_lp) / _w_op_lb_in()) / 12, rel=1e-3)


def test_pressure_alone_exceeding_allowable_gives_zero_span():
    r = SpanCalculator(_inputs(design_pressure=20000 * PSI)).run()
    assert _span(r.sizes[0].by_condition[0], SUS) == 0.0
    assert any(w.code == "PRESSURE_LIMIT" for w in r.warnings)


def test_allowable_override():
    r = SpanCalculator(_inputs(allowable_override=15000 * PSI, allowable_override_source="test")).run()
    assert r.allowable / PSI == pytest.approx(15000)


def test_deflection_reports_both_values():
    inp = _inputs(deflection_limit=0.1 * IN)
    inp.snow.enabled = True
    inp.snow.ground_snow = convert(40, "psf", "Pa")
    res = SpanCalculator(inp).run().sizes[0].by_condition[0]
    assert res.deflection_sustained > res.deflection_pipe_contents
    assert res.governs == DEFLECTION
    assert res.deflection_pipe_contents == pytest.approx(0.1 * IN, rel=1e-9)


# ---------------------------------------------------------------- occasional cases

def test_wind_case_uses_vector_resultant_and_asd_factor():
    inp = _inputs()
    inp.wind.enabled = True
    sz = SpanCalculator(inp).run().sizes[0]
    case = next(c for c in sz.case_loads if c.case == OCC_WIND)
    assert case.w_h == pytest.approx(0.6 * sz.loads["wind"])
    assert case.w_eff == pytest.approx(math.hypot(case.w_v, case.w_h))
    assert case.limit / PSI == pytest.approx(1.33 * 20000, rel=1e-6)
    di, I, Z, *_ = _section()
    L = _span(sz.by_condition[0], OCC_WIND)
    assert L == pytest.approx(math.sqrt(1.33 * 20000 * PSI * Z * IN**3 / (case.w_eff / 8)), rel=1e-6)


def test_seismic_case_factors():
    inp = _inputs()
    inp.seismic.enabled = True
    inp.seismic.sds = 1.0
    sz = SpanCalculator(inp).run().sizes[0]
    w_op = sz.loads["pipe"] + sz.loads["contents"]
    case = next(c for c in sz.case_loads if c.case == OCC_SEISMIC)
    # z/h = 10/30: 0.4*2.5*1.0*(1+2/3)/12 = 0.139 < lower bound 0.3 -> 0.3
    assert sz.loads["seismic_h"] == pytest.approx(0.3 * w_op)
    assert case.w_h == pytest.approx(0.7 * 0.3 * w_op)
    assert case.w_v == pytest.approx(w_op + 0.7 * 0.2 * w_op)


def test_wind_and_seismic_never_combined():
    inp = _inputs()
    inp.wind.enabled = inp.seismic.enabled = True
    sz = SpanCalculator(inp).run().sizes[0]
    for c in sz.case_loads:
        if c.case == OCC_WIND:
            assert c.w_v == pytest.approx(sz.case_loads[0].w_v)  # no seismic vertical
        if c.case == OCC_SEISMIC:
            assert c.w_h == pytest.approx(0.7 * sz.loads["seismic_h"])  # no wind


def test_toggles_only_add_their_own_cases():
    base = {c.case for c in SpanCalculator(_inputs()).run().sizes[0].case_loads}
    assert base == {SUS}
    for attr, expected in [("wind", {OCC_WIND}), ("seismic", {OCC_SEISMIC}), ("ice", {OCC_ICE})]:
        inp = _inputs()
        getattr(inp, attr).enabled = True
        got = {c.case for c in SpanCalculator(inp).run().sizes[0].case_loads}
        assert got == {SUS} | expected


def test_snow_sustained_vs_occasional():
    sus = _inputs()
    sus.snow.enabled = True
    sus.snow.ground_snow = convert(40, "psf", "Pa")
    sz = SpanCalculator(sus).run().sizes[0]
    w_op = sz.loads["pipe"] + sz.loads["contents"]
    assert sz.case_loads[0].w_v == pytest.approx(w_op + sz.loads["snow"])
    assert OCC_SNOW not in {c.case for c in sz.case_loads}

    occ = _inputs()
    occ.snow.enabled = True
    occ.snow.ground_snow = convert(40, "psf", "Pa")
    occ.snow.category = OCCASIONAL
    sz = SpanCalculator(occ).run().sizes[0]
    assert sz.case_loads[0].w_v == pytest.approx(w_op)
    snow_case = next(c for c in sz.case_loads if c.case == OCC_SNOW)
    assert snow_case.w_v == pytest.approx(w_op + sz.loads["snow"])


def test_snow_concurrent_combinations():
    inp = _inputs()
    inp.wind.enabled = inp.seismic.enabled = inp.snow.enabled = True
    inp.snow.category = OCCASIONAL
    sz = SpanCalculator(inp).run().sizes[0]
    cases = {c.case: c for c in sz.case_loads}
    w_op = sz.loads["pipe"] + sz.loads["contents"]
    S = sz.loads["snow"]
    assert cases[OCC_WIND_SNOW].w_v == pytest.approx(w_op + 0.75 * S)
    assert cases[OCC_WIND_SNOW].w_h == pytest.approx(0.75 * 0.6 * sz.loads["wind"])
    assert cases[OCC_SEISMIC_SNOW].w_v == pytest.approx(w_op + 0.525 * sz.loads["seismic_v"] + 0.75 * S)
    assert cases[OCC_SEISMIC_SNOW].w_h == pytest.approx(0.525 * sz.loads["seismic_h"])


def test_ice_sustained_adds_point7_di():
    inp = _inputs()
    inp.ice.enabled = True
    sz = SpanCalculator(inp).run().sizes[0]
    w_op = sz.loads["pipe"] + sz.loads["contents"]
    cases = {c.case: c for c in sz.case_loads}
    assert cases[SUS].w_v == pytest.approx(w_op + 0.7 * sz.loads["ice"])
    assert cases[OCC_ICE].w_v == pytest.approx(cases[SUS].w_v)  # Di already in SUS
    assert cases[OCC_ICE].w_h == pytest.approx(0.7 * sz.loads["wind_on_ice"])


# ---------------------------------------------------------------- validation / io

def test_refuses_without_deflection_limit():
    with pytest.raises(SpanInputError, match="Deflection limit"):
        SpanCalculator(_inputs(deflection_limit=None)).run()


def test_temperature_range_enforced():
    with pytest.raises(SpanInputError, match="-40"):
        SpanCalculator(_inputs(design_temperature=convert(350, "degF", "kelvin"))).run()


def test_5083_refused_above_table_a1_range():
    from proctoolbox_core.materials import MaterialDataError
    with pytest.raises(MaterialDataError, match="allowable_stress"):
        SpanCalculator(_inputs(material_id="al5083", design_temperature=convert(200, "degF", "kelvin"))).run()


def test_sweep_skips_missing_schedule():
    r = SpanCalculator(_inputs(schedule="160", nps_list=["3", "3-1/2", "4"])).run()
    assert r.skipped == ["3-1/2"]
    assert {w.code for w in r.warnings} >= {"UNVERIFIED_DATA"}


def test_span_project_roundtrip():
    inp = _inputs(nps_list=["2", "4", "6"], end_conditions=list(END_CONDITIONS), design_pressure=100 * PSI)
    inp.wind.enabled = inp.snow.enabled = inp.ice.enabled = inp.seismic.enabled = True
    inp.site.ground_elevation = 300.0
    inp.site.insulation_thickness = 2 * IN
    res = SpanCalculator(inp).run()
    p = Project(app_name="span_chart", app_version="0.2.0", inputs={"span": inp.to_project_inputs()},
                results=res.to_dict(), warnings=res.warnings, material_citations=res.citations)
    q = loads(dumps(p))
    assert SpanInputs.from_project_inputs(q.inputs["span"]) == inp
    assert q.results == p.results
    assert q.warnings == p.warnings


def test_v1_project_file_still_loads():
    v1 = {"material_id": "carbon_steel", "schedule": "40", "nps_list": ["2"],
          "design_temperature": 294.26, "allowable_stress": 1.0e8, "allowable_stress_source": "x",
          "deflection_limit": 0.00254, "deflection_limit_basis": "y", "contents_sg": 1.0,
          "corrosion_allowance": 0.0, "mill_tolerance": True, "end_conditions": ["simply_supported"],
          "continuous_spans": 3, "install_temperature": 294.26, "run_length": 0.0}
    inp = SpanInputs.from_project_inputs(v1)
    assert inp.schedule == "40" and not inp.wind.enabled


def test_insulation_sets_projected_diameter_per_size():
    inp = _inputs(nps_list=["2", "8"])
    inp.wind.enabled = True
    inp.site.insulation_thickness = 2 * IN
    r = SpanCalculator(inp).run()
    for sz in r.sizes:
        assert sz.projected_diameter == pytest.approx(sz.od + 4 * IN)
        assert sz.env_details["wind"]["D_ft"] == pytest.approx(sz.projected_diameter / 0.3048)


def test_generate_tables_pivot_and_pdf():
    from span_report import build_pdf, generate_tables
    inp = _inputs(end_conditions=[SIMPLY_SUPPORTED, CONTINUOUS], deflection_limit=0.1 * IN)
    t = generate_tables(inp, ["40", "160"], ["3", "3-1/2", "4"])
    assert t.cells[SIMPLY_SUPPORTED]["3-1/2"]["160"] is None        # Sch 160 not listed at 3-1/2
    single = SpanCalculator(_inputs(schedule="40", nps_list=["4"], deflection_limit=0.1 * IN)).run()
    assert t.cells[SIMPLY_SUPPORTED]["4"]["40"][0] == pytest.approx(single.sizes[0].by_condition[0].span)
    pdf = build_pdf(t, inp, "US", "test")
    assert pdf[:5] == b"%PDF-" and len(pdf) > 2000
