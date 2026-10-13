import json

import pytest

from proctoolbox_core.io import Project, ProjectFileError, ProjectWarning, dumps, load, loads, save
from proctoolbox_core.materials import MaterialDatabase, MaterialDataError, default_database
from proctoolbox_core.piping import get_section, list_nps, schedules_for
from proctoolbox_core.units import Q_, convert, from_si, to_si

IN = 0.0254


# ---------------------------------------------------------------- units

def test_temperature_and_engineering_units():
    assert convert(-40, "degF", "degC") == pytest.approx(-40)
    assert convert(1, "Mpsi", "psi") == pytest.approx(1e6)
    assert convert(1, "ksi", "MPa") == pytest.approx(6.894757, rel=1e-6)
    assert from_si(to_si(300, "degF", "temperature"), "temperature", "US") == pytest.approx(300)


# ---------------------------------------------------------------- io

def _project():
    return Project(
        app_name="dummy", app_version="0.1.0",
        inputs={"T": Q_(300.0, "kelvin"), "label": "x", "nested": {"L": Q_(2.5, "m")}},
        results={"span": Q_(3.1, "m"), "list": [1, 2, 3]},
        warnings=[ProjectWarning("PLACEHOLDER", "test placeholder", "test")],
        material_citations=[{"material": "m", "property": "E", "citation": "c", "verified": False}],
    )


def test_roundtrip_lossless(tmp_path):
    p = _project()
    path = save(p, tmp_path / "p.json")
    q = load(path)
    assert q.inputs == p.inputs
    assert q.results == p.results
    assert q.warnings == p.warnings
    assert q.material_citations == p.material_citations
    assert q.created == p.created
    assert q.inputs["T"].units == Q_(1, "kelvin").units


def test_unknown_schema_version_rejected():
    d = json.loads(dumps(_project()))
    d["schema_version"] = "9.0"
    with pytest.raises(ProjectFileError, match="Unsupported"):
        loads(json.dumps(d))


def test_malformed_project_rejected():
    d = json.loads(dumps(_project()))
    del d["inputs"]
    with pytest.raises(ProjectFileError):
        loads(json.dumps(d))


# ---------------------------------------------------------------- piping

def test_pipe_section_properties_match_handbook():
    s = get_section("2", "40")
    assert s.od / IN == pytest.approx(2.375)
    assert s.wall_nominal / IN == pytest.approx(0.154)
    assert s.inertia / IN**4 == pytest.approx(0.666, rel=2e-3)
    assert s.section_modulus / IN**3 == pytest.approx(0.561, rel=2e-3)
    s = get_section("4", "40")
    assert s.inertia / IN**4 == pytest.approx(7.23, rel=2e-3)
    assert s.section_modulus / IN**3 == pytest.approx(3.21, rel=2e-3)


def test_allowances_reduce_wall_used_only():
    s = get_section("4", "40", corrosion_allowance=0.0625 * IN, mill_tolerance=True)
    assert s.wall_used / IN == pytest.approx(0.237 * 0.875 - 0.0625)
    assert s.wall_nominal / IN == pytest.approx(0.237)


def test_pipe_table_coverage():
    nps = list_nps()
    assert nps[0] == "1/2" and nps[-1] == "24"
    assert "40S" in schedules_for("24")
    with pytest.raises(KeyError):
        get_section("3-1/2", "160")


# ---------------------------------------------------------------- materials

def test_tabular_interpolation_and_unverified_warning():
    db = default_database()
    r = db.get("carbon_steel", "E", convert(250, "degF", "kelvin"))
    assert convert(r.value, "Pa", "Mpsi") == pytest.approx((28.8 + 28.3) / 2)
    assert any(w.code == "UNVERIFIED_DATA" for w in r.warnings)
    assert "C-6" in r.citation


def test_out_of_range_raises_unless_extrapolation_opted_in():
    db = default_database()
    T = convert(400, "degF", "kelvin")
    with pytest.raises(MaterialDataError, match="outside data range"):
        db.get("ss304", "E", T)
    r = db.get("ss304", "E", T, allow_extrapolation=True)
    assert any(w.code == "EXTRAPOLATED" for w in r.warnings)


def test_placeholder_always_flagged():
    db = MaterialDatabase(data_dir=__import__("pathlib").Path("nonexistent"))
    db.add({"id": "x", "name": "X", "properties": {
        "E": {"kind": "placeholder", "unit": "Pa", "value": None, "warning": "awaiting source"}}})
    r = db.get("x", "E")
    assert r.is_placeholder and r.value is None
    assert r.warnings[0].code == "PLACEHOLDER"


def test_service_notes():
    db = default_database()
    assert db.service_warnings("al5083", convert(200, "degF", "kelvin"))
    assert not db.service_warnings("al5083", convert(100, "degF", "kelvin"))
    assert db.service_warnings("carbon_steel", convert(-40, "degF", "kelvin"))


def test_thermal_expansion_strain():
    db = default_database()
    r = db.get("ss304", "thermal_expansion_total", convert(300, "degF", "kelvin"))
    assert r.value * 100 * 12 == pytest.approx(2.61)  # in per 100 ft
