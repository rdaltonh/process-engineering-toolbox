"""Headless UI smoke tests via Streamlit's AppTest."""

import tomllib

import pytest
from pathlib import Path

from streamlit.testing.v1 import AppTest

from proctoolbox_core.ui import CATEGORIES

ROOT = Path(__file__).resolve().parent.parent
SPAN_APP = ROOT / "apps" / "piping_structural" / "span_chart" / "app.py"


def test_every_manifest_is_valid():
    manifests = list((ROOT / "apps").glob("*/*/app.toml"))
    assert manifests
    ids = set()
    for m in manifests:
        meta = tomllib.loads(m.read_text(encoding="utf-8"))
        assert meta["category"] in CATEGORIES, m
        assert (m.parent / meta.get("entry", "app.py")).exists(), m
        assert meta["id"] not in ids
        ids.add(meta["id"])


def test_launcher_renders():
    at = AppTest.from_file(str(ROOT / "launcher" / "app.py"), default_timeout=30).run()
    assert not at.exception
    assert any("Process Engineering Toolbox" in t.value for t in at.title)


def _results_df(at, column="End condition"):
    return next(d.value for d in at.dataframe if column in getattr(d.value, "columns", []))


def test_span_chart_refuses_then_computes():
    at = AppTest.from_file(str(SPAN_APP), default_timeout=30).run()
    assert not at.exception
    assert any("Cannot compute" in w.value for w in at.warning)

    at.number_input(key="sc_defl").set_value(0.1)
    at.run()
    assert not at.exception
    assert not any("Cannot compute" in w.value for w in at.warning)
    # Default sweep: NPS 1/2-24 Sch 40 (no 22") x 2 end conditions.
    assert len(_results_df(at)) == 20 * 2



def test_span_chart_all_loads_toggled():
    at = AppTest.from_file(str(SPAN_APP), default_timeout=30).run()
    at.number_input(key="sc_defl").set_value(0.1)
    for key in ("sc_wind", "sc_snow", "sc_ice", "sc_eq"):
        at.toggle(key=key).set_value(True)
    at.run()
    assert not at.exception
    assert not any("Cannot compute" in w.value for w in at.warning)
    cols = list(_results_df(at, "Governs").columns)  # "All cases & loads" table
    for case in ("SUS", "OCC-WIND", "OCC-WIND+SNOW", "OCC-SEISMIC", "OCC-SEISMIC+SNOW", "OCC-ICE", "DEFLECTION"):
        assert any(c.startswith(case + " span") for c in cols), case


def test_generate_tables_pdf():
    at = AppTest.from_file(str(SPAN_APP), default_timeout=60).run()
    at.number_input(key="sc_defl").set_value(0.1)
    at.run()
    at.button[[b.label for b in at.button].index("Generate Tables")].click().run()
    assert not at.exception
    pdf = at.session_state["_tbl_pdf"]
    assert pdf[:5] == b"%PDF-"
    t = at.session_state["_tbl_preview"]
    assert t.schedules == ["40", "80"] and "22" in t.nps  # Sch 80 lists 22"


def test_tube_mode_ui():
    at = AppTest.from_file(str(SPAN_APP), default_timeout=60).run()
    at.number_input(key="sc_defl").set_value(0.1)
    at.radio(key="sc_product").set_value("tube")
    at.run()
    assert not at.exception
    assert not any("Cannot compute" in w.value for w in at.warning)
    assert at.selectbox(key="sc_material").value in ("ss304", "ss304_304l", "ss304l", "ss316", "ss316_316l", "ss316l")
    df = _results_df(at, "Tube OD")
    assert list(df["Tube OD"].unique())[:2] == ["1/4", "3/8"]


HOSE_APP = ROOT / "apps" / "fluid_analysis_design" / "corrugated_hose_dp" / "app.py"


def test_hose_app_defaults_compute():
    at = AppTest.from_file(str(HOSE_APP), default_timeout=60).run()
    assert not at.exception
    assert not any("Cannot compute" in w.value for w in at.warning)
    assert any("LSU" in c.value and "governs" in c.value.lower() for c in at.caption)


def test_hose_app_gas_and_units():
    at = AppTest.from_file(str(HOSE_APP), default_timeout=60).run()
    at.selectbox(key="hd_fluid").set_value("Nitrogen")
    at.number_input(key="hd_m").set_value(1000.0)
    at.run()
    assert not at.exception
    assert not any("Cannot compute" in w.value for w in at.warning)
    at.segmented_control(key="unit_system").set_value("SI").run()
    assert not at.exception
    assert at.number_input(key="hd_D").value == pytest.approx(25.7048, rel=1e-4)


def test_hose_app_refuses_zero_length():
    at = AppTest.from_file(str(HOSE_APP), default_timeout=60).run()
    at.number_input(key="hd_L").set_value(0.0).run()
    assert any("Cannot compute" in w.value for w in at.warning)


def test_hose_app_bends_table():
    import pandas as pd
    at = AppTest.from_file(str(HOSE_APP), default_timeout=60)
    at.session_state["hd_bends_df"] = pd.DataFrame(
        [[90.0, 2.024, 1.0], [30.0, 48.0, None]], columns=["Angle (deg)", "Radius", "Position (0-1)"])
    at.run()
    assert not at.exception
    assert not any("Cannot compute" in w.value for w in at.warning)
    bends = next(d.value for d in at.dataframe if "Regime" in getattr(d.value, "columns", []) and "R/D" in d.value.columns)
    assert list(bends["Regime"]) == ["Hawthorne tight", "LSU sweep"]
    assert list(bends["R/D"]) == [2.0, pytest.approx(47.43, abs=0.01)]
