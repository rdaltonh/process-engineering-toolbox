"""Span Chart calculation engine (no UI).

Maximum support spacing for straight horizontal pipe. B31.3 load cases:
sustained (W+P) <= Sh and occasional (sustained + ASCE 7-16 ASD-factored
wind / snow / ice / seismic) <= 1.33 Sh, plus a deflection limit on pipe +
contents. Span = min over enabled cases. All quantities are SI internally.
"""

from __future__ import annotations

import copy
import math
from dataclasses import asdict, dataclass, field, fields
from functools import lru_cache

import numpy as np

from proctoolbox_core.io import ProjectWarning
from proctoolbox_core.loads import asce7_16 as asce
from proctoolbox_core.materials import MaterialDatabase, default_database
from proctoolbox_core.piping import PipeSection, data_warnings, get_section, schedules_for
from proctoolbox_core.units import Q_, convert, ureg

G = 9.80665  # m/s^2
# Specific-gravity reference: water at 60°F, 62.37 lb/ft^3.
WATER_DENSITY_60F = convert(62.37, "lb/ft**3", "kg/m**3")

T_MIN_K = convert(-40.0, "degF", "kelvin")
T_MAX_K = convert(300.0, "degF", "kelvin")

SIMPLY_SUPPORTED = "simply_supported"
FIXED_FIXED = "fixed_fixed"
CONTINUOUS = "continuous"
CANTILEVER = "cantilever"

END_CONDITIONS: dict[str, str] = {
    SIMPLY_SUPPORTED: "Simply supported",
    FIXED_FIXED: "Fixed-fixed",
    CONTINUOUS: "Continuous",
    CANTILEVER: "Cantilever / overhang",
}

# Max moment = w L^2 / k. Continuous uses the wL^2/10 industry convention.
MOMENT_DIVISOR = {SIMPLY_SUPPORTED: 8.0, FIXED_FIXED: 12.0, CONTINUOUS: 10.0, CANTILEVER: 2.0}
# Max deflection = c w L^4 / (E I), closed forms. Continuous comes from the solver.
DEFLECTION_COEFF = {SIMPLY_SUPPORTED: 5.0 / 384.0, FIXED_FIXED: 1.0 / 384.0, CANTILEVER: 1.0 / 8.0}

SCOPE_NOTE = (
    "Support-spacing estimate for straight horizontal runs: sustained (pipe + contents + pressure) and "
    "optional ASCE 7-16 wind / snow / ice / seismic occasional cases per B31.3 302.3.5/302.3.6. "
    "Not a substitute for flexibility/stress analysis of the piping system (thermal expansion, "
    "concentrated loads at fittings/valves, support loads)."
)


class SpanInputError(ValueError):
    pass


# ---------------------------------------------------------------- beam solver

@lru_cache(maxsize=32)
def beam_coefficients(n_spans: int, fixed_ends: bool = False, elems_per_span: int = 16) -> tuple[float, float]:
    """Equal-span beam under uniform load, by direct stiffness (Euler-Bernoulli).

    Returns (deflection coefficient c, moment coefficient m) such that
    max |deflection| = c w L^4 / (E I) and max |moment| = m w L^2,
    with L the individual span length. Nodal displacements are exact with
    consistent loads; interior deflection/moment add the element particular
    solution, so results are exact to sampling resolution.
    """
    if n_spans < 1:
        raise ValueError("n_spans must be >= 1")
    m = elems_per_span
    n_el = n_spans * m
    Le = 1.0 / m  # L = EI = w = 1
    n_dof = 2 * (n_el + 1)
    K = np.zeros((n_dof, n_dof))
    F = np.zeros(n_dof)
    ke = np.array([
        [12, 6 * Le, -12, 6 * Le],
        [6 * Le, 4 * Le**2, -6 * Le, 2 * Le**2],
        [-12, -6 * Le, 12, -6 * Le],
        [6 * Le, 2 * Le**2, -6 * Le, 4 * Le**2],
    ]) / Le**3
    fe = np.array([Le / 2, Le**2 / 12, Le / 2, -(Le**2) / 12])
    for e in range(n_el):
        idx = slice(2 * e, 2 * e + 4)
        K[idx, idx] += ke
        F[idx] += fe
    fixed = {2 * (s * m) for s in range(n_spans + 1)}  # vertical dof at supports
    if fixed_ends:
        fixed |= {1, n_dof - 1}
    free = np.array([i for i in range(n_dof) if i not in fixed])
    d = np.zeros(n_dof)
    d[free] = np.linalg.solve(K[np.ix_(free, free)], F[free])

    xs = np.linspace(0.0, Le, 21)
    # Hermite shape functions and second derivatives on [0, Le].
    xi = xs / Le
    N = np.array([1 - 3 * xi**2 + 2 * xi**3, Le * (xi - 2 * xi**2 + xi**3),
                  3 * xi**2 - 2 * xi**3, Le * (-(xi**2) + xi**3)])
    B = np.array([(-6 + 12 * xi) / Le**2, (-4 + 6 * xi) / Le,
                  (6 - 12 * xi) / Le**2, (-2 + 6 * xi) / Le])
    bubble = xs**2 * (Le - xs) ** 2 / 24.0
    bubble_dd = (2 * (Le - xs) ** 2 - 8 * xs * (Le - xs) + 2 * xs**2) / 24.0
    v_max = 0.0
    m_max = 0.0
    for e in range(n_el):
        de = d[2 * e: 2 * e + 4]
        v = de @ N + bubble
        curv = de @ B + bubble_dd
        v_max = max(v_max, float(np.max(np.abs(v))))
        m_max = max(m_max, float(np.max(np.abs(curv))))
    return v_max, m_max


def cantilever_coefficients() -> tuple[float, float]:
    return DEFLECTION_COEFF[CANTILEVER], 1.0 / MOMENT_DIVISOR[CANTILEVER]


# ---------------------------------------------------------------- load cases

SUS = "SUS"
OCC_SNOW = "OCC-SNOW"
OCC_WIND = "OCC-WIND"
OCC_WIND_SNOW = "OCC-WIND+SNOW"
OCC_SEISMIC = "OCC-SEISMIC"
OCC_SEISMIC_SNOW = "OCC-SEISMIC+SNOW"
OCC_ICE = "OCC-ICE"
DEFLECTION = "DEFLECTION"

CASE_LABELS = {
    SUS: "Sustained (W+P)",
    OCC_SNOW: "Occasional: snow",
    OCC_WIND: "Occasional: wind",
    OCC_WIND_SNOW: "Occasional: wind + snow",
    OCC_SEISMIC: "Occasional: seismic",
    OCC_SEISMIC_SNOW: "Occasional: seismic + snow",
    OCC_ICE: "Occasional: ice + wind-on-ice",
    DEFLECTION: "Deflection (pipe + contents)",
}
CASE_BASIS = {
    SUS: "B31.3 302.3.5; ASCE 7-16 2.4.1 Comb. 1 (+0.7Di per 2.4.3)",
    OCC_SNOW: "B31.3 302.3.6; ASCE 7-16 2.4.1 Comb. 3",
    OCC_WIND: "B31.3 302.3.6; ASCE 7-16 2.4.1 Comb. 5 (0.6W)",
    OCC_WIND_SNOW: "B31.3 302.3.6; ASCE 7-16 2.4.1 Comb. 6 (0.75(0.6W) + 0.75S)",
    OCC_SEISMIC: "B31.3 302.3.6; ASCE 7-16 2.4.5 Comb. 8 (0.7Ev + 0.7Eh)",
    OCC_SEISMIC_SNOW: "B31.3 302.3.6; ASCE 7-16 2.4.5 Comb. 9 (0.525E + 0.75S)",
    OCC_ICE: "B31.3 302.3.6; ASCE 7-16 2.4.3 (0.7Di + 0.7Wi + S)",
    DEFLECTION: "User deflection limit on pipe + contents",
}
OCCASIONAL_FACTOR = 1.33  # B31.3 302.3.6

SUSTAINED = "sustained"
OCCASIONAL = "occasional"


# ---------------------------------------------------------------- inputs

@dataclass
class SiteInputs:
    """Shared by wind/snow/ice/seismic."""

    risk_category: str = "II"
    exposure: str = "C"
    height: float = convert(10.0, "ft", "m")  # pipe centerline above grade, m
    kzt: float = 1.0
    ground_elevation: float | None = None     # m; None -> Ke = 1.0
    insulation_thickness: float = 0.0         # m; D_proj = OD + 2*t_ins (ASCE 7-16 Fig. 7.13-2 note)


@dataclass
class WindInputs:
    enabled: bool = False
    speed: float = convert(115.0, "mph", "m/s")  # basic wind speed V, m/s
    roughness: str = "moderately_smooth"
    cf_override: float | None = None


@dataclass
class SnowInputs:
    enabled: bool = False
    ground_snow: float = convert(20.0, "psf", "Pa")  # p_g, Pa
    condition: str = "fully_exposed"
    surface_above_45F: bool = False
    category: str = SUSTAINED


@dataclass
class IceInputs:
    enabled: bool = False
    thickness: float = convert(0.5, "in", "m")            # nominal t, m
    concurrent_wind: float = convert(40.0, "mph", "m/s")  # V_c, m/s
    category: str = SUSTAINED


@dataclass
class SeismicInputs:
    enabled: bool = False
    sds: float = 0.5
    ip: float = 1.0
    structure_height: float = convert(30.0, "ft", "m")  # h, m (z from SiteInputs.height)
    piping_type: str = "b31_welded"


_SECTIONS = {"site": SiteInputs, "wind": WindInputs, "snow": SnowInputs, "ice": IceInputs, "seismic": SeismicInputs}


@dataclass
class SpanInputs:
    """All values SI. Temperatures in kelvin, pressure in Pa (gauge)."""

    material_id: str
    schedule: str
    nps_list: list[str]
    design_temperature: float
    deflection_limit: float | None          # m
    deflection_limit_basis: str
    design_pressure: float = 0.0            # Pa gauge
    allowable_override: float | None = None  # Pa; None -> B31.3 Table A-1 via materials engine
    allowable_override_source: str = ""
    contents_sg: float = 0.0
    corrosion_allowance: float = 0.0        # m
    mill_tolerance: bool = True
    end_conditions: list[str] = field(default_factory=lambda: [SIMPLY_SUPPORTED])
    continuous_spans: int = 3
    site: SiteInputs = field(default_factory=SiteInputs)
    wind: WindInputs = field(default_factory=WindInputs)
    snow: SnowInputs = field(default_factory=SnowInputs)
    ice: IceInputs = field(default_factory=IceInputs)
    seismic: SeismicInputs = field(default_factory=SeismicInputs)

    # Dimensional fields carry units in project files ({value, unit}).
    UNIT_FIELDS = {
        "design_temperature": "kelvin",
        "deflection_limit": "m",
        "design_pressure": "Pa",
        "allowable_override": "Pa",
        "corrosion_allowance": "m",
        "site.height": "m",
        "site.ground_elevation": "m",
        "site.insulation_thickness": "m",
        "wind.speed": "m/s",
        "snow.ground_snow": "Pa",
        "ice.thickness": "m",
        "ice.concurrent_wind": "m/s",
        "seismic.structure_height": "m",
    }

    def to_project_inputs(self) -> dict:
        d = asdict(self)
        for path, unit in self.UNIT_FIELDS.items():
            parent, key = _locate(d, path)
            if parent.get(key) is not None:
                parent[key] = Q_(parent[key], unit)
        return d

    @classmethod
    def from_project_inputs(cls, d: dict) -> "SpanInputs":
        d = copy.deepcopy(d)
        for path, unit in cls.UNIT_FIELDS.items():
            parent, key = _locate(d, path)
            if isinstance(parent.get(key), ureg.Quantity):
                parent[key] = parent[key].to(unit).magnitude
        # Tolerate older project files: drop unknown keys, default missing ones.
        top = {f.name for f in fields(cls)}
        kwargs = {k: v for k, v in d.items() if k in top and k not in _SECTIONS}
        for name, klass in _SECTIONS.items():
            sub = d.get(name) or {}
            known = {f.name for f in fields(klass)}
            kwargs[name] = klass(**{k: v for k, v in sub.items() if k in known})
        return cls(**kwargs)


def _locate(d: dict, path: str) -> tuple[dict, str]:
    if "." in path:
        section, key = path.split(".", 1)
        return d.setdefault(section, {}), key
    return d, path


# ---------------------------------------------------------------- results

@dataclass
class CaseLoads:
    case: str
    w_v: float     # N/m
    w_h: float     # N/m
    limit: float   # Pa

    @property
    def w_eff(self) -> float:
        return math.hypot(self.w_v, self.w_h)


@dataclass
class CaseSpan:
    case: str
    span: float                          # m
    stress_at_span: float | None = None  # Pa (stress cases)


@dataclass
class EndConditionResult:
    end_condition: str
    span: float                      # governing, m
    governs: str                     # case id
    cases: list[CaseSpan]
    moment_coeff: float
    deflection_coeff: float
    deflection_pipe_contents: float  # m at governing span (checked)
    deflection_sustained: float      # m at governing span incl. sustained snow/ice (reported)


@dataclass
class SizeResult:
    nps: str
    schedule: str
    od: float
    wall_nominal: float
    wall_used: float
    inertia: float
    section_modulus: float
    metal_area: float            # m^2, nominal
    flow_area: float             # m^2, nominal ID
    projected_diameter: float    # m, OD + 2*insulation (wind/snow/ice)
    pressure_stress: float       # Pa, longitudinal
    loads: dict[str, float]      # N/m components
    env_details: dict            # per-size intermediate values (Cf, snow shape, ice area, ...)
    case_loads: list[CaseLoads]
    by_condition: list[EndConditionResult]
    pressure_exceeds: list[str]  # cases where S_lp >= limit


@dataclass
class SpanResults:
    allowable: float  # Sh used, Pa
    allowable_citation: str
    E: float
    sizes: list[SizeResult]
    skipped: list[str]
    warnings: list[ProjectWarning]
    citations: list[dict]
    load_details: dict

    def to_dict(self) -> dict:
        return {
            "units": "SI (m, N/m, Pa, m^3, m^4)",
            "allowable": self.allowable,
            "allowable_citation": self.allowable_citation,
            "E": self.E,
            "load_details": self.load_details,
            "sizes": [asdict(s) for s in self.sizes],
            "skipped": self.skipped,
        }


# ---------------------------------------------------------------- calculator

class SpanCalculator:
    def __init__(self, inputs: SpanInputs, db: MaterialDatabase | None = None):
        self.inputs = inputs
        self.db = db or default_database()

    def validate(self) -> None:
        i = self.inputs
        problems = []
        if i.deflection_limit is None or i.deflection_limit <= 0:
            problems.append("Deflection limit is required.")
        if i.allowable_override is not None and i.allowable_override <= 0:
            problems.append("Allowable stress override must be positive.")
        if not (T_MIN_K - 1e-9 <= i.design_temperature <= T_MAX_K + 1e-9):
            problems.append("Design temperature must be within -40°F to +300°F (v1 range).")
        if i.contents_sg < 0:
            problems.append("Contents specific gravity cannot be negative.")
        if i.corrosion_allowance < 0:
            problems.append("Corrosion allowance cannot be negative.")
        if not i.end_conditions:
            problems.append("Select at least one end condition.")
        if not i.nps_list:
            problems.append("Select at least one pipe size.")
        if i.continuous_spans < 2:
            problems.append("Continuous beam needs at least 2 spans.")
        if i.seismic.enabled and (i.seismic.structure_height <= 0 or i.seismic.sds < 0):
            problems.append("Seismic needs S_DS >= 0 and structure height h > 0.")
        if problems:
            raise SpanInputError(" ".join(problems))

    def _coefficients(self, cond: str) -> tuple[float, float]:
        """(deflection coeff, moment coeff)."""
        if cond == CONTINUOUS:
            c, _ = beam_coefficients(self.inputs.continuous_spans)
            return c, 1.0 / MOMENT_DIVISOR[CONTINUOUS]
        return DEFLECTION_COEFF[cond], 1.0 / MOMENT_DIVISOR[cond]

    def run(self) -> SpanResults:
        self.validate()
        i = self.inputs
        T = i.design_temperature
        warnings: list[ProjectWarning] = []
        E_res = self.db.get(i.material_id, "E", T)
        rho_res = self.db.get(i.material_id, "density")
        warnings += list(E_res.warnings) + list(rho_res.warnings)
        if i.allowable_override is not None:
            Sh = i.allowable_override
            sh_cite = i.allowable_override_source or "User override (no source given)"
            if not i.allowable_override_source.strip():
                warnings.append(ProjectWarning("UNCITED_INPUT", "Allowable stress override entered without a source.", "span_chart:inputs"))
        else:
            sh_res = self.db.get(i.material_id, "allowable_stress", T)
            warnings += list(sh_res.warnings)
            Sh, sh_cite = sh_res.value, sh_res.citation
        warnings += self.db.service_warnings(i.material_id, T)
        warnings += data_warnings()
        if not i.deflection_limit_basis.strip():
            warnings.append(ProjectWarning("UNCITED_INPUT", "Deflection limit entered without a basis.", "span_chart:inputs"))
        occasional_on = (i.wind.enabled or i.seismic.enabled or i.ice.enabled
                         or (i.snow.enabled and i.snow.category == OCCASIONAL))
        if occasional_on:
            warnings += self.db.occasional_warnings(i.material_id)
        if i.wind.enabled or i.seismic.enabled or i.ice.enabled:
            warnings.append(ProjectWarning(
                "ASSUMPTION",
                "Horizontal loads assume supports restrain the pipe laterally at the same locations as vertically "
                "(guides); bending combined as the vector resultant of vertical and horizontal moments.",
                "span_chart:method"))
        if i.snow.enabled:
            warnings.append(ProjectWarning(
                "ASSUMPTION",
                "Snow applied uniformly to all spans (ASCE 7-16 7.5.1 partial loading not applied); 'Simply supported' "
                "bounds partial-loading effects. Cornice loads between adjacent pipes (Fig. 7.13-3) not evaluated.",
                "span_chart:snow"))

        E = E_res.value
        rho_metal = rho_res.value
        rho_contents = i.contents_sg * WATER_DENSITY_60F

        sizes: list[SizeResult] = []
        skipped: list[str] = []
        details: dict = {}
        for nps in i.nps_list:
            if i.schedule not in schedules_for(nps):
                skipped.append(nps)
                continue
            sec = get_section(nps, i.schedule, i.corrosion_allowance, i.mill_tolerance)
            sizes.append(self._size(sec, E, Sh, rho_metal, rho_contents, details, warnings))
        if any(s.pressure_exceeds for s in sizes):
            warnings.append(ProjectWarning(
                "PRESSURE_LIMIT", "Longitudinal pressure stress alone reaches the allowable for some sizes/cases "
                "(span reported as 0).", "span_chart:results"))
        mat = self.db.material(i.material_id)
        return SpanResults(Sh, sh_cite, E, sizes, skipped, _dedupe(warnings), mat.citations(), details)

    def _environment(self, D_proj: float, w_op: float, details: dict, warnings: list) -> tuple[dict[str, float], dict]:
        """Strength-level environmental loads per length (N/m) for one pipe size, plus per-size details."""
        i, s = self.inputs, self.inputs.site
        z_ft = convert(s.height, "m", "ft")
        Ke = asce.ke(None if s.ground_elevation is None else convert(s.ground_elevation, "m", "ft"))
        out = {"snow": 0.0, "wind": 0.0, "ice": 0.0, "wind_on_ice": 0.0, "seismic_h": 0.0, "seismic_v": 0.0}
        per: dict = {}
        D_ft = convert(D_proj, "m", "ft")
        if i.wind.enabled:
            wr = asce.wind_load(convert(i.wind.speed, "m/s", "mph"), D_proj, z_ft, s.exposure, s.kzt, Ke,
                                i.wind.roughness, i.wind.cf_override)
            out["wind"] = wr.w
            details["wind"] = {"qz_psf": wr.qz_psf, "Kz": wr.Kz, "G": wr.G, "Ke": Ke}
            per["wind"] = {"D_ft": D_ft, "D_sqrt_qz": D_ft * math.sqrt(wr.qz_psf), "Cf": wr.Cf,
                           "w_plf": convert(wr.w, "N/m", "plf")}
        if i.snow.enabled:
            sr = asce.snow_load(convert(i.snow.ground_snow, "Pa", "psf"), D_proj, s.exposure, i.snow.condition,
                                s.risk_category, i.snow.surface_above_45F)
            out["snow"] = sr.w
            details["snow"] = {"pf_psf": sr.pf_psf, "gamma_pcf": sr.gamma_pcf}
            h_ft = sr.pf_psf / sr.gamma_pcf if sr.gamma_pcf else 0.0
            per["snow"] = {"D_ft": D_ft, "h_ft": h_ft, "transition_D_ft": 0.73 * h_ft, "shape": sr.shape,
                           "w_plf": convert(sr.w, "N/m", "plf")}
            if sr.shape == "exempt" and i.snow.surface_above_45F:
                warnings.append(ProjectWarning("INFO", "Snow on pipe not applied: wintertime surface temperature "
                                               "> 45°F (ASCE 7-16 7.13.3).", "span_chart:snow"))
        if i.ice.enabled:
            ir = asce.ice_load(convert(i.ice.thickness, "m", "in"), convert(i.ice.concurrent_wind, "m/s", "mph"),
                               D_proj, z_ft, s.exposure, s.risk_category, s.kzt, Ke)
            out["ice"], out["wind_on_ice"] = ir.w_ice, ir.w_wind_ice
            details["ice"] = {"td_in": ir.td_in, "fz": ir.fz, "qz_concurrent_psf": ir.qz_psf}
            td_ft = ir.td_in / 12.0
            per["ice"] = {"Dc_ft": D_ft, "Ai_ft2": math.pi * td_ft * (D_ft + td_ft), "D_wind_ft": D_ft + 2 * td_ft,
                          "Di_plf": convert(ir.w_ice, "N/m", "plf"), "Wi_plf": convert(ir.w_wind_ice, "N/m", "plf")}
        if i.seismic.enabled:
            sr = asce.seismic_coefficients(i.seismic.sds, i.seismic.ip, s.height / i.seismic.structure_height,
                                           i.seismic.piping_type)
            out["seismic_h"], out["seismic_v"] = sr.fp_coeff * w_op, sr.ev_coeff * w_op
            details["seismic"] = {"ap": sr.ap, "Rp": sr.Rp, "Fp_over_Wp_raw": sr.fp_coeff_raw,
                                  "Fp_over_Wp": sr.fp_coeff, "bound": sr.bound, "Ev_over_Wp": sr.ev_coeff}
            per["seismic"] = {"Wp_plf": convert(w_op, "N/m", "plf"), "Fp_plf": convert(out["seismic_h"], "N/m", "plf"),
                              "Ev_plf": convert(out["seismic_v"], "N/m", "plf")}
        return out, per

    def _cases(self, w_op: float, env: dict[str, float], Sh: float) -> list[CaseLoads]:
        """B31.3 load cases with ASCE 7-16 ASD factors (see spec Section 0)."""
        i = self.inputs
        occ = OCCASIONAL_FACTOR * Sh
        snow_sus = i.snow.enabled and i.snow.category == SUSTAINED
        ice_sus = i.ice.enabled and i.ice.category == SUSTAINED
        S, Di = env["snow"], env["ice"]
        w_sus = w_op + (S if snow_sus else 0.0) + (0.7 * Di if ice_sus else 0.0)
        snow_occ = S if (i.snow.enabled and not snow_sus) else 0.0
        cases = [CaseLoads(SUS, w_sus, 0.0, Sh)]
        if i.snow.enabled and not snow_sus:
            cases.append(CaseLoads(OCC_SNOW, w_sus + S, 0.0, occ))
        if i.wind.enabled:
            cases.append(CaseLoads(OCC_WIND, w_sus, 0.6 * env["wind"], occ))
            if i.snow.enabled:
                cases.append(CaseLoads(OCC_WIND_SNOW, w_sus + 0.75 * snow_occ, 0.75 * 0.6 * env["wind"], occ))
        if i.seismic.enabled:
            cases.append(CaseLoads(OCC_SEISMIC, w_sus + 0.7 * env["seismic_v"], 0.7 * env["seismic_h"], occ))
            if i.snow.enabled:
                cases.append(CaseLoads(OCC_SEISMIC_SNOW, w_sus + 0.525 * env["seismic_v"] + 0.75 * snow_occ,
                                       0.525 * env["seismic_h"], occ))
        if i.ice.enabled:
            ice_v = 0.0 if ice_sus else 0.7 * Di
            cases.append(CaseLoads(OCC_ICE, w_sus + ice_v + snow_occ, 0.7 * env["wind_on_ice"], occ))
        return cases

    def _size(self, sec: PipeSection, E: float, Sh: float, rho_metal: float, rho_contents: float,
              details: dict, warnings: list) -> SizeResult:
        i = self.inputs
        w_pipe = rho_metal * G * sec.metal_area_nominal
        w_contents = rho_contents * G * sec.flow_area
        w_op = w_pipe + w_contents
        D_proj = sec.od + 2.0 * (i.site.insulation_thickness or 0.0)
        env, per = self._environment(D_proj, w_op, details, warnings)
        cases = self._cases(w_op, env, Sh)
        S_lp = abs(i.design_pressure) * sec.od / (4.0 * sec.wall_used)
        EI = E * sec.inertia
        Z = sec.section_modulus
        exceeds = [c.case for c in cases if S_lp >= c.limit]

        out = []
        for cond in i.end_conditions:
            c_def, c_mom = self._coefficients(cond)
            spans = []
            for c in cases:
                avail = c.limit - S_lp
                L = math.sqrt(avail * Z / (c_mom * c.w_eff)) if avail > 0 and c.w_eff > 0 else 0.0
                spans.append(CaseSpan(c.case, L, S_lp + c_mom * c.w_eff * L**2 / Z))
            L_d = (i.deflection_limit * EI / (c_def * w_op)) ** 0.25
            spans.append(CaseSpan(DEFLECTION, L_d))
            gov = min(spans, key=lambda cs: cs.span)
            L = gov.span
            out.append(EndConditionResult(
                end_condition=cond, span=L, governs=gov.case, cases=spans,
                moment_coeff=c_mom, deflection_coeff=c_def,
                deflection_pipe_contents=c_def * w_op * L**4 / EI,
                deflection_sustained=c_def * cases[0].w_v * L**4 / EI,
            ))
        return SizeResult(
            nps=sec.nps, schedule=sec.schedule, od=sec.od,
            wall_nominal=sec.wall_nominal, wall_used=sec.wall_used,
            inertia=sec.inertia, section_modulus=Z,
            metal_area=sec.metal_area_nominal, flow_area=sec.flow_area, projected_diameter=D_proj,
            pressure_stress=S_lp, loads={"pipe": w_pipe, "contents": w_contents, **env}, env_details=per,
            case_loads=cases, by_condition=out, pressure_exceeds=exceeds,
        )


def _dedupe(warnings: list[ProjectWarning]) -> list[ProjectWarning]:
    seen = set()
    out = []
    for w in warnings:
        key = (w.code, w.message)
        if key not in seen:
            seen.add(key)
            out.append(w)
    return out
