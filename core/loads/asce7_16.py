"""ASCE 7-16 environmental loads on an individual horizontal pipe, per unit length.

Equations follow ASCE/SEI 7-16. Table values live in data/asce7_16.json with
page citations. ASCE equations are evaluated in their native US customary
units (ft, psf, mph, pcf) and results are returned in SI (N/m).
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from ..units import convert

_DATA = Path(__file__).parent / "data" / "asce7_16.json"

RISK_CATEGORIES = ("I", "II", "III", "IV")
EXPOSURES = ("B", "C", "D")
SNOW_EXPOSURE_CONDITIONS = ("fully_exposed", "partially_exposed", "sheltered")
SURFACE_ROUGHNESS = ("moderately_smooth", "rough", "very_rough")


@lru_cache(maxsize=1)
def data() -> dict:
    return json.loads(_DATA.read_text(encoding="utf-8"))


def piping_types() -> dict[str, dict]:
    d = dict(data()["seismic"]["piping_types"])
    d.pop("citation")
    return d


def _plf_to_si(plf: float) -> float:
    return convert(plf, "lbf/ft", "N/m")


# ---------------------------------------------------------------- wind

def kz(z_ft: float, exposure: str) -> float:
    """Velocity pressure exposure coefficient, Table 26.10-1 Note 1."""
    t = data()["wind"]["terrain_exposure_constants"][exposure]
    f = data()["wind"]["kz_formula"]
    z = max(z_ft, f["z_min_ft"])
    z = min(z, t["zg_ft"])
    return f["coefficient"] * (z / t["zg_ft"]) ** (2.0 / t["alpha"])


def ke(ground_elevation_ft: float | None) -> float:
    """Ground elevation factor, Table 26.9-1 Note 2. None -> 1.0 (permitted)."""
    if ground_elevation_ft is None:
        return 1.0
    c = data()["wind"]["ke_formula"]["coefficient_per_ft"]
    return math.exp(-c * max(ground_elevation_ft, 0.0))


def velocity_pressure_psf(V_mph: float, z_ft: float, exposure: str, Kzt: float = 1.0,
                          Kd: float | None = None, Ke: float = 1.0) -> float:
    """q_z = 0.00256 Kz Kzt Kd Ke V^2 (Eq. 26.10-1)."""
    if Kd is None:
        Kd = data()["wind"]["kd_round"]["value"]
    return 0.00256 * kz(z_ft, exposure) * Kzt * Kd * Ke * V_mph**2


def cf_round(D_ft: float, qz_psf: float, roughness: str) -> float:
    """Force coefficient for a long round member, Fig. 29.4-1 (h/D = 25 column)."""
    c = data()["wind"]["cf_round_h_over_d_25"]
    if D_ft * math.sqrt(qz_psf) > c["d_sqrt_qz_threshold"]:
        return c["above_threshold"][roughness]
    return c["at_or_below_threshold"]


@dataclass(frozen=True)
class WindResult:
    qz_psf: float
    Kz: float
    Cf: float
    G: float
    w: float  # N/m, strength level


def wind_load(V_mph: float, D_proj_m: float, z_ft: float, exposure: str, Kzt: float = 1.0,
              Ke: float = 1.0, roughness: str = "moderately_smooth", Cf: float | None = None) -> WindResult:
    """Wind force per unit length on a round pipe, F/L = q_z G C_f D (Eq. 29.4-1)."""
    D_ft = convert(D_proj_m, "m", "ft")
    qz = velocity_pressure_psf(V_mph, z_ft, exposure, Kzt, Ke=Ke)
    G = data()["wind"]["gust_factor_rigid"]["value"]
    cf = Cf if Cf is not None else cf_round(D_ft, qz, roughness)
    return WindResult(qz, kz(z_ft, exposure), cf, G, _plf_to_si(qz * G * cf * D_ft))


# ---------------------------------------------------------------- snow

def flat_roof_snow_psf(pg_psf: float, exposure: str, condition: str, risk_category: str,
                       Ct: float | None = None) -> float:
    """p_f = 0.7 Ce Ct Is pg (Eq. 7.3-1)."""
    s = data()["snow"]
    Ce = s["exposure_factor_ce"][exposure][condition]
    Ct = Ct if Ct is not None else s["thermal_factor_ct_unheated"]["value"]
    Is = data()["importance_factors"]["snow_Is"][risk_category]
    return s["pf_coefficient"]["value"] * Ce * Ct * Is * pg_psf


def snow_density_pcf(pg_psf: float) -> float:
    """gamma = 0.13 pg + 14 <= 30 pcf (Eq. 7.7-1)."""
    d = data()["snow"]["density"]
    return min(d["a"] * pg_psf + d["b_pcf"], d["max_pcf"])


@dataclass(frozen=True)
class SnowResult:
    pf_psf: float
    gamma_pcf: float
    shape: str  # "triangular" | "trapezoidal" | "exempt"
    w: float    # N/m


def snow_load(pg_psf: float, D_proj_m: float, exposure: str, condition: str, risk_category: str,
              surface_above_45F: bool = False) -> SnowResult:
    """Snow on an individual pipe, Sec. 7.13.3 / Fig. 7.13-2a,b."""
    pf = flat_roof_snow_psf(pg_psf, exposure, condition, risk_category)
    gamma = snow_density_pcf(pg_psf)
    if surface_above_45F or pf <= 0:
        return SnowResult(pf, gamma, "exempt", 0.0)
    m = data()["snow"]["pipe_method"]
    D = convert(D_proj_m, "m", "ft")
    h = pf / gamma  # balanced snow height, ft
    if D <= m["transition_coefficient"] * h:
        shape = "triangular"
        area = 0.5 * D * m["triangle_height_over_d"] * D
    else:
        shape = "trapezoidal"
        top = D - 2.0 * h / math.tan(math.radians(m["angle_of_repose_deg"]))
        area = h * (D + max(top, 0.0)) / 2.0
    return SnowResult(pf, gamma, shape, _plf_to_si(gamma * area))


# ---------------------------------------------------------------- ice

@dataclass(frozen=True)
class IceResult:
    td_in: float
    fz: float
    w_ice: float       # N/m, ice weight D_i
    w_wind_ice: float  # N/m, concurrent wind on ice-covered pipe, strength level
    qz_psf: float


def ice_load(t_in: float, Vc_mph: float, D_proj_m: float, z_ft: float, exposure: str,
             risk_category: str, Kzt: float = 1.0, Ke: float = 1.0) -> IceResult:
    """Freezing-rain ice on a round pipe plus concurrent wind (Secs. 10.4, 10.5)."""
    d = data()["ice"]
    imp = data()["importance_factors"]
    fz = min((max(z_ft, 0.0) / d["height_factor"]["z_ref_ft"]) ** d["height_factor"]["exponent"],
             d["height_factor"]["max"]) if z_ft > 0 else 0.0
    td = t_in * imp["ice_thickness_Ii"][risk_category] * fz * Kzt ** d["kzt_exponent"]["value"]
    Dc = convert(D_proj_m, "m", "ft")
    td_ft = td / 12.0
    Ai = math.pi * td_ft * (Dc + td_ft)
    w_ice = _plf_to_si(d["density_pcf"]["value"] * Ai)
    Iw = imp["ice_wind_Iw"][risk_category]
    qz = velocity_pressure_psf(Vc_mph, z_ft, exposure, Kzt, Ke=Ke) * Iw
    G = data()["wind"]["gust_factor_rigid"]["value"]
    Cf = d["cf_round_ice_covered"]["value"]
    w_wind = _plf_to_si(qz * G * Cf * (Dc + 2 * td_ft))
    return IceResult(td, fz, w_ice, w_wind, qz)


# ---------------------------------------------------------------- seismic

@dataclass(frozen=True)
class SeismicResult:
    ap: float
    Rp: float
    fp_coeff_raw: float
    fp_coeff: float     # Fp / Wp after bounds (horizontal), strength level
    ev_coeff: float     # vertical, fraction of Wp, strength level
    bound: str          # "none" | "upper" | "lower"


def seismic_coefficients(SDS: float, Ip: float, z_over_h: float, piping_type: str) -> SeismicResult:
    """Fp/Wp per Eqs. 13.3-1..3 and vertical 0.2 SDS (Sec. 13.3.1.2)."""
    s = data()["seismic"]
    pt = piping_types()[piping_type]
    zh = min(max(z_over_h, 0.0), 1.0)
    raw = s["fp_equation"]["coefficient"] * pt["ap"] * SDS * (1 + 2 * zh) / (pt["Rp"] / Ip)
    hi = s["fp_equation"]["upper"] * SDS * Ip
    lo = s["fp_equation"]["lower"] * SDS * Ip
    coeff, bound = raw, "none"
    if raw > hi:
        coeff, bound = hi, "upper"
    elif raw < lo:
        coeff, bound = lo, "lower"
    return SeismicResult(pt["ap"], pt["Rp"], raw, coeff, s["vertical"]["coefficient"] * SDS, bound)
