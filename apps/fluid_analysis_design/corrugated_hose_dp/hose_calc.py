"""Corrugated hose pressure-drop engine (no UI).

Two straight-hose methods are evaluated side by side (spec
docs/app-specs/corrugated-hose-dp.md):

- "lsu": LSU / NASA-CR-62061 Fanning correlation f = alpha*Re^beta from pitch,
  depth and width of the corrugation (governs when depth and width are given).
- "hawthorne": Hawthorne & von Helms (1963) series-of-orifices model,
  k = 0.219*pitch, C = [1 - (D/(D+2k))^2]^2 per corrugation.

Bends: gentle sweeps (R/D >= 12.7) use the LSU curved-hose ratio over the arc;
tight bends (R/D <= 5) use the Hawthorne C_B chart scaled linearly by theta/90;
the gap between takes the larger of the two. Gas follows the Crane TP-410
density rule with a segment march above 40% dP/P1. All quantities SI.
"""

from __future__ import annotations

import copy
import json
import math
from dataclasses import asdict, dataclass, field, fields
from functools import lru_cache
from pathlib import Path

import numpy as np

from proctoolbox_core.fluids import FluidError, FluidState, p_sat, state_PH, state_PT, t_sat
from proctoolbox_core.io import ProjectWarning
from proctoolbox_core.units import Q_, ureg

DATA_DIR = Path(__file__).parent / "data"

LSU = "lsu"
HAWTHORNE = "hawthorne"
METHOD_LABELS = {LSU: "LSU / NASA-CR-62061", HAWTHORNE: "Hawthorne & von Helms (1963)"}

ANNULAR = "annular"
HELICAL = "helical"
HOSE_TYPES = {ANNULAR: "Annular (close or open pitch)", HELICAL: "Helical"}

LIQUID = "liquid"
GAS = "gas"

RE_LAMINAR = 2000.0
SWEEP_MIN_R_OVER_D = 1.0 / 0.0787   # 12.7: LSU tested D/R_B <= 0.0787
TIGHT_MAX_R_OVER_D = 5.0             # end of the Hawthorne chart
TIGHT_MIN_R_OVER_D = 0.7             # start of the plotted Hawthorne curve
INLET_DENSITY_LIMIT = 0.10           # Crane TP-410 dP/P1 thresholds
AVERAGE_DENSITY_LIMIT = 0.40
SEGMENT_DP_LIMIT = 0.10

SCOPE_NOTE = (
    "Pressure drop of turbulent single-phase flow through one corrugated metal hose (annular or helical), "
    "including bends. Empirical correlations from 1960s air/water tests on 1/2-4 1/2 in hose; results are "
    "engineering estimates (about +/-20 to 40%). Where the hose manufacturer publishes a pressure-drop curve, "
    "that data takes precedence."
)


class HoseInputError(ValueError):
    """Inputs the method refuses to evaluate."""


class ChokedFlowError(HoseInputError):
    """Gas flow reaches Mach 1 (or zero outlet pressure) inside the hose."""


# ---------------------------------------------------------------- data

@lru_cache(maxsize=1)
def correlations() -> dict:
    return json.loads((DATA_DIR / "correlations.json").read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def bend_chart() -> dict:
    return json.loads((DATA_DIR / "hawthorne_bend_cb.json").read_text(encoding="utf-8"))


def hawthorne_cb(r_over_D: float) -> float:
    """90-deg bend coefficient from the digitized chart (linear interpolation, held beyond the ends)."""
    pts = bend_chart()["points"]
    x = [p["r_over_D"] for p in pts]
    y = [p["C_B"] for p in pts]
    return float(np.interp(r_over_D, x, y))


def _cb_dashed(r_over_D: float) -> bool:
    pts = bend_chart()["points"]
    solid = [p["r_over_D"] for p in pts if not p["dashed"]]
    return not (min(solid) <= r_over_D <= max(solid))


# ---------------------------------------------------------------- correlations

def lsu_alpha_beta(fluid_kind: str, hose_type: str, pitch: float, depth: float, width: float) -> tuple[float, float]:
    c = correlations()["lsu"]
    a, b = c["alpha"][fluid_kind][hose_type]
    alpha = a * (pitch - width) / depth + b
    beta = c["beta"]["a"] * (width * depth / pitch**2) + c["beta"]["b"]
    return alpha, beta


def hawthorne_k_C(D: float, pitch: float) -> tuple[float, float]:
    k = correlations()["hawthorne"]["k_over_pitch"] * pitch
    C = (1.0 - (D / (D + 2.0 * k)) ** 2) ** 2
    return k, C


def hawthorne_dp_psi(N: float, C: float, V_fps: float, rho_lbft3: float, C_B: float = 0.0) -> float:
    """Paper's US-unit form, Eq. 5/6: dP[psi] = (N*C + C_B) * V^2 * rho / 9266."""
    return (N * C + C_B) * V_fps**2 * rho_lbft3 / 9266.0


def lsu_bend_ratio(D: float, R: float) -> float:
    c = correlations()["lsu"]["bend"]
    return 1.0 + c["a"] * (D / R) ** c["n"]


# ---------------------------------------------------------------- inputs

@dataclass
class Bend:
    angle_deg: float
    radius: float          # m, bend centerline radius
    position: float = 1.0  # fraction of hose length (gas segment march only)


@dataclass
class HoseInputs:
    """All values SI. P_in absolute (Pa), T_in in K, m_dot in kg/s."""

    fluid: str = "Water"
    P_in: float = 0.0
    T_in: float = 0.0
    m_dot: float = 0.0
    hose_type: str = ANNULAR
    D: float = 0.0                 # m, minimum inside diameter
    pitch: float = 0.0             # m
    length: float = 0.0            # m, developed (live) length
    depth: float | None = None     # m, corrugation depth (LSU)
    width: float | None = None     # m, width of the inward convolution (LSU)
    bends: list[Bend] = field(default_factory=list)
    sweep_min: float = 0.1         # fraction of design m_dot
    sweep_max: float = 2.0
    sweep_points: int = 50

    UNIT_FIELDS = {
        "P_in": "Pa", "T_in": "kelvin", "m_dot": "kg/s",
        "D": "m", "pitch": "m", "length": "m", "depth": "m", "width": "m",
    }

    def to_project_inputs(self) -> dict:
        d = asdict(self)
        for key, unit in self.UNIT_FIELDS.items():
            if d[key] is not None:
                d[key] = Q_(d[key], unit)
        for b in d["bends"]:
            b["radius"] = Q_(b["radius"], "m")
        return d

    @classmethod
    def from_project_inputs(cls, d: dict) -> "HoseInputs":
        d = copy.deepcopy(d)
        for key, unit in cls.UNIT_FIELDS.items():
            if isinstance(d.get(key), ureg.Quantity):
                d[key] = d[key].to(unit).magnitude
        bends = []
        for b in d.get("bends") or []:
            if isinstance(b.get("radius"), ureg.Quantity):
                b["radius"] = b["radius"].to("m").magnitude
            bends.append(Bend(**{k: v for k, v in b.items() if k in {f.name for f in fields(Bend)}}))
        known = {f.name for f in fields(cls)}
        kwargs = {k: v for k, v in d.items() if k in known and k != "bends"}
        return cls(bends=bends, **kwargs)

    @property
    def has_lsu_geometry(self) -> bool:
        return bool(self.depth) and bool(self.width)


# ---------------------------------------------------------------- results

@dataclass
class TrackResult:
    method: str
    dp_total: float = math.nan       # Pa
    dp_straight: float = math.nan
    dp_bends: list[float] = field(default_factory=list)
    dp_acc: float = 0.0
    P_out: float = math.nan
    f_F: float = math.nan            # Fanning, straight hose, at inlet
    Re_in: float = math.nan
    Re_out: float = math.nan
    V_in: float = math.nan
    V_out: float = math.nan
    mach_out: float | None = None
    density_basis: str = ""
    n_segments: int = 0
    valid: bool = True
    invalid_reason: str = ""


@dataclass
class BendInfo:
    angle_deg: float
    r_over_D: float
    regime: str          # "sweep" | "tight" | "gap"
    C_B: float | None    # Hawthorne chart value used (tight/gap)
    f_ratio: float | None  # LSU f/f0 (sweep/gap)
    arc_length: float
    dashed: bool


@dataclass
class HoseResults:
    tracks: dict[str, TrackResult]
    governing: str
    spread: float | None              # (hawthorne - lsu) / lsu
    fluid_kind: str
    phase: str
    rho_in: float
    mu_in: float
    params: dict
    bends: list[BendInfo]
    sweep: list[dict]
    warnings: list[ProjectWarning]
    citations: list[dict]

    @property
    def governing_track(self) -> TrackResult:
        return self.tracks[self.governing]

    def to_dict(self) -> dict:
        return {
            "governing": self.governing,
            "spread": self.spread,
            "fluid_kind": self.fluid_kind,
            "phase": self.phase,
            "rho_in": self.rho_in,
            "mu_in": self.mu_in,
            "params": self.params,
            "tracks": {k: asdict(v) for k, v in self.tracks.items()},
            "bends": [asdict(b) for b in self.bends],
            "sweep": self.sweep,
        }


# ---------------------------------------------------------------- model

class _Track:
    """Friction and bend losses for one straight-hose method."""

    def __init__(self, method: str, inp: HoseInputs, kind: str, bends: list[BendInfo]):
        self.method, self.inp, self.kind, self.bends = method, inp, kind, bends
        if method == LSU:
            self.alpha, self.beta = lsu_alpha_beta(kind, inp.hose_type, inp.pitch, inp.depth, inp.width)
        else:
            self.k, self.C = hawthorne_k_C(inp.D, inp.pitch)

    def f(self, Re: float) -> float:
        """Straight-hose Fanning friction factor."""
        if Re < RE_LAMINAR:
            return 16.0 / Re
        if self.method == LSU:
            return self.alpha * Re**self.beta
        return self.C * self.inp.D / (4.0 * self.inp.pitch)

    def bend_K(self, b: BendInfo, Re: float) -> float:
        """Extra loss coefficient (velocity heads at D) for one bend."""
        if Re < RE_LAMINAR:
            return 0.0
        sweep = tight = 0.0
        if b.f_ratio is not None:
            sweep = 4.0 * self.f(Re) * b.arc_length / self.inp.D * (b.f_ratio - 1.0)
        if b.C_B is not None:
            tight = b.C_B * b.angle_deg / 90.0
        return max(sweep, tight)


def _classify_bends(inp: HoseInputs) -> list[BendInfo]:
    out = []
    arcs = 0.0
    for i, b in enumerate(inp.bends, 1):
        if not 0 < b.angle_deg <= 180:
            raise HoseInputError(f"Bend {i}: angle must be in (0, 180] deg (tested range).")
        if b.radius <= 0:
            raise HoseInputError(f"Bend {i}: radius must be positive.")
        if not 0.0 <= b.position <= 1.0:
            raise HoseInputError(f"Bend {i}: position must be a fraction 0-1 of the hose length.")
        rd = b.radius / inp.D
        if rd < TIGHT_MIN_R_OVER_D:
            raise HoseInputError(
                f"Bend {i}: R/D = {rd:.2f} is below the plotted Hawthorne bend curve (0.7); "
                "the hose would be bent tighter than any source covers.")
        arc = b.radius * math.radians(b.angle_deg)
        arcs += arc
        if rd >= SWEEP_MIN_R_OVER_D:
            regime, C_B, ratio = "sweep", None, lsu_bend_ratio(inp.D, b.radius)
        elif rd <= TIGHT_MAX_R_OVER_D:
            regime, C_B, ratio = "tight", hawthorne_cb(rd), None
        else:
            regime, C_B, ratio = "gap", hawthorne_cb(min(rd, TIGHT_MAX_R_OVER_D)), lsu_bend_ratio(inp.D, b.radius)
        out.append(BendInfo(b.angle_deg, rd, regime, C_B, ratio, arc, regime != "sweep" and _cb_dashed(rd)))
    if arcs > inp.length * (1 + 1e-9):
        raise HoseInputError(
            f"Total bend arc length ({arcs:.3f} m) exceeds the hose length ({inp.length:.3f} m).")
    return out


class HoseCalculator:
    def __init__(self, inputs: HoseInputs):
        self.inp = inputs

    # ------------------------------------------------------------ validation
    def _validate(self) -> None:
        i = self.inp
        for name in ("P_in", "T_in", "m_dot", "D", "pitch", "length"):
            if not getattr(i, name) or getattr(i, name) <= 0:
                raise HoseInputError(f"{name} must be positive.")
        if i.hose_type not in HOSE_TYPES:
            raise HoseInputError(f"Unknown hose type '{i.hose_type}'.")
        if (i.depth is None) != (i.width is None) or (i.depth is not None and (i.depth <= 0 or i.width <= 0)):
            raise HoseInputError("Corrugation depth and width must both be given (positive) or both left blank.")
        if i.width is not None and i.width >= i.pitch:
            raise HoseInputError("Convolution width must be less than the pitch.")
        if not (0 < i.sweep_min < i.sweep_max) or i.sweep_points < 2:
            raise HoseInputError("Sweep range must satisfy 0 < min < max with at least 2 points.")

    def run(self) -> HoseResults:
        self._validate()
        i = self.inp
        warnings: list[ProjectWarning] = []
        try:
            s1 = state_PT(i.fluid, i.P_in, i.T_in)
        except FluidError as e:
            raise HoseInputError(str(e)) from e
        if s1.is_two_phase:
            raise HoseInputError("Inlet state is two-phase; this tool covers single-phase flow only.")
        kind = LIQUID if s1.is_liquid else GAS
        warnings += self._phase_warnings(s1, kind)

        bends = _classify_bends(i)
        tracks: dict[str, _Track] = {HAWTHORNE: _Track(HAWTHORNE, i, kind, bends)}
        params: dict = {"k": tracks[HAWTHORNE].k, "C": tracks[HAWTHORNE].C, "N": i.length / i.pitch}
        if i.has_lsu_geometry:
            t = _Track(LSU, i, kind, bends)
            if t.alpha <= 0:
                raise HoseInputError(
                    f"LSU alpha = {t.alpha:.5f} <= 0: geometry (pitch-width)/depth = "
                    f"{(i.pitch - i.width) / i.depth:.3f} is outside the correlation's domain.")
            tracks[LSU] = t
            params.update(alpha=t.alpha, beta=t.beta,
                          pitch_param=(i.pitch - i.width) / i.depth,
                          shape_param=i.width * i.depth / i.pitch**2)
        governing = LSU if LSU in tracks else HAWTHORNE

        results = {m: self._solve(t, s1, kind, i.m_dot) for m, t in tracks.items()}
        for m, r in results.items():
            if not r.valid and isinstance(r.invalid_reason, str) and r.invalid_reason.startswith("CHOKED"):
                raise ChokedFlowError(f"{METHOD_LABELS[m]}: {r.invalid_reason[7:]}")
        spread = None
        if LSU in results and results[LSU].dp_total > 0:
            spread = results[HAWTHORNE].dp_total / results[LSU].dp_total - 1.0

        warnings += self._method_warnings(i, kind, results, governing, bends)
        sweep = self._sweep(tracks, s1, kind, governing)
        cites = [{"source": correlations()[m]["citation"], "verified": correlations()[m]["verified"]} for m in tracks]
        if any(b.regime != "sweep" for b in bends):
            cites.append({"source": bend_chart()["citation"], "verified": bend_chart()["verified"]})
        return HoseResults(results, governing, spread, kind, s1.phase, s1.rho, s1.mu, params, bends, sweep,
                           _dedupe(warnings), cites)

    # ------------------------------------------------------------ solvers
    def _solve(self, t: _Track, s1: FluidState, kind: str, m_dot: float) -> TrackResult:
        if kind == LIQUID:
            return self._solve_liquid(t, s1, m_dot)
        try:
            return self._solve_gas(t, s1, m_dot)
        except ChokedFlowError as e:
            return TrackResult(t.method, valid=False, invalid_reason=f"CHOKED:{e}")

    def _area(self) -> float:
        return math.pi * self.inp.D**2 / 4.0

    def _losses(self, t: _Track, Re: float, length: float, bends: list[BendInfo]) -> tuple[float, list[float]]:
        """(K_straight over length, [K per bend]) at one Reynolds number."""
        return 4.0 * t.f(Re) * length / self.inp.D, [t.bend_K(b, Re) for b in bends]

    def _solve_liquid(self, t: _Track, s1: FluidState, m_dot: float) -> TrackResult:
        i = self.inp
        G = m_dot / self._area()
        V = G / s1.rho
        Re = G * i.D / s1.mu
        K_s, K_b = self._losses(t, Re, i.length, t.bends)
        q = s1.rho * V**2 / 2.0
        dp_s, dp_b = K_s * q, [k * q for k in K_b]
        dp = dp_s + sum(dp_b)
        r = TrackResult(t.method, dp, dp_s, dp_b, 0.0, i.P_in - dp, t.f(Re), Re, Re, V, V,
                        density_basis="liquid (inlet properties)")
        if r.P_out <= 0:
            r.valid, r.invalid_reason = False, "Outlet pressure at or below zero absolute."
        else:
            ps = p_sat(i.fluid, i.T_in)
            if ps is not None and r.P_out < ps:
                r.valid, r.invalid_reason = False, (
                    f"Outlet pressure below saturation pressure at inlet temperature: cavitation/flashing, "
                    f"single-phase result invalid.")
        return r

    def _outlet(self, P: float, h: float) -> FluidState:
        if P <= 0:
            raise ChokedFlowError("outlet pressure reaches zero: flow is choked.")
        try:
            return state_PH(self.inp.fluid, P, h)
        except FluidError as e:
            raise ChokedFlowError(f"no valid outlet state ({e}).") from e

    def _check_mach(self, G: float, s: FluidState) -> float:
        M = G / s.rho / s.a
        if M >= 1.0:
            raise ChokedFlowError(f"flow reaches Mach 1 inside the hose (choked; last step gave Mach {M:.2f}).")
        return M

    def _solve_gas(self, t: _Track, s1: FluidState, m_dot: float) -> TrackResult:
        i = self.inp
        G = m_dot / self._area()
        Re1 = G * i.D / s1.mu
        # 1) inlet density
        K_s, K_b = self._losses(t, Re1, i.length, t.bends)
        q1 = G**2 / (2.0 * s1.rho)
        dp = (K_s + sum(K_b)) * q1
        if dp / i.P_in <= INLET_DENSITY_LIMIT:
            s2 = self._outlet(i.P_in - dp, s1.h)
            return TrackResult(t.method, dp, K_s * q1, [k * q1 for k in K_b], 0.0, i.P_in - dp, t.f(Re1),
                               Re1, G * i.D / s2.mu, G / s1.rho, G / s2.rho, self._check_mach(G, s2),
                               "inlet density (dP/P1 <= 10%)", 1)
        # 2) average density, iterated, with acceleration term
        avg = self._gas_average(t, s1, G)
        if avg is not None and avg.dp_total / i.P_in <= AVERAGE_DENSITY_LIMIT:
            return avg
        # 3) segment march
        return self._gas_march(t, s1, G)

    def _gas_average(self, t: _Track, s1: FluidState, G: float) -> TrackResult | None:
        i = self.inp
        P2 = i.P_in * (1 - INLET_DENSITY_LIMIT)
        for _ in range(200):
            try:
                s2 = self._outlet(P2, s1.h)
            except ChokedFlowError:
                return None
            rho_m, mu_m = (s1.rho + s2.rho) / 2.0, (s1.mu + s2.mu) / 2.0
            Re = G * i.D / mu_m
            K_s, K_b = self._losses(t, Re, i.length, t.bends)
            q = G**2 / (2.0 * rho_m)
            dp_acc = G**2 * (1.0 / s2.rho - 1.0 / s1.rho)
            P2_new = i.P_in - (K_s + sum(K_b)) * q - dp_acc
            if P2_new <= 0:
                return None
            if abs(P2_new - P2) < 1e-9 * i.P_in:
                P2 = P2_new
                break
            P2 = 0.5 * (P2 + P2_new)
        else:
            return None
        s2 = self._outlet(P2, s1.h)
        try:
            M = self._check_mach(G, s2)
        except ChokedFlowError:
            return None
        dp_s, dp_b = K_s * q, [k * q for k in K_b]
        return TrackResult(t.method, i.P_in - P2, dp_s, dp_b, dp_acc, P2, t.f(G * i.D / s1.mu),
                           G * i.D / s1.mu, G * i.D / s2.mu, G / s1.rho, G / s2.rho, M,
                           "average density, iterated (10% < dP/P1 <= 40%)", 1)

    def _gas_march(self, t: _Track, s1: FluidState, G: float, n0: int = 20) -> TrackResult:
        n = n0
        while True:
            r, worst = self._march(t, s1, G, n)
            if worst <= SEGMENT_DP_LIMIT or n >= 5120:
                return r
            n *= 2

    def _march(self, t: _Track, s1: FluidState, G: float, n: int) -> tuple[TrackResult, float]:
        i = self.inp
        dx = i.length / n
        # Bend j is lumped into the segment containing its position.
        seg_of = [min(int(b.position * n), n - 1) for b in i.bends]
        s = s1
        dp_s, dp_b, dp_acc, worst = 0.0, [0.0] * len(i.bends), 0.0, 0.0
        for k in range(n):
            here = [j for j, sg in enumerate(seg_of) if sg == k]
            # Segment properties: mean of inlet and outlet (trapezoidal, second order in dx),
            # iterated from an inlet-property first guess.
            so = s
            for _ in range(5):
                rho_m, mu_m = (s.rho + so.rho) / 2.0, (s.mu + so.mu) / 2.0
                K_s, K_b = self._losses(t, G * i.D / mu_m, dx, [t.bends[j] for j in here])
                q = G**2 / (2.0 * rho_m)
                dpf = (K_s + sum(K_b)) * q
                acc = G**2 * (1.0 / so.rho - 1.0 / s.rho)
                P_out = s.P - dpf - acc
                so = self._outlet(P_out, s1.h)
            self._check_mach(G, so)
            worst = max(worst, (s.P - P_out) / s.P)
            dp_s += K_s * q
            for j, kb in zip(here, K_b):
                dp_b[j] += kb * q
            dp_acc += acc
            s = so
        Re1 = G * i.D / s1.mu
        r = TrackResult(t.method, i.P_in - s.P, dp_s, dp_b, dp_acc, s.P, t.f(Re1), Re1, G * i.D / s.mu,
                        G / s1.rho, G / s.rho, G / s.rho / s.a,
                        f"segment march, {n} segments (dP/P1 > 40%)", n)
        return r, worst

    # ------------------------------------------------------------ sweep
    def _sweep(self, tracks: dict[str, _Track], s1: FluidState, kind: str, governing: str) -> list[dict]:
        i = self.inp
        c = correlations()
        re_lo, re_hi = (c["lsu"]["validity"]["re_" + kind] if governing == LSU else c["hawthorne"]["validity"]["re"])
        v_max = c["lsu"]["validity"]["gas_velocity_max_m_s"]
        pts = []
        for m in np.linspace(i.sweep_min * i.m_dot, i.sweep_max * i.m_dot, i.sweep_points):
            G = float(m) / self._area()
            Re = G * i.D / s1.mu
            row: dict = {"m_dot": float(m), "vol_flow_in": float(m / s1.rho), "Re": Re, "V_in": G / s1.rho}
            v_top = G / s1.rho
            for meth, t in tracks.items():
                r = self._solve(t, s1, kind, float(m))
                row[f"dp_{meth}"] = r.dp_total if r.valid else None
                row[f"invalid_{meth}"] = r.invalid_reason.replace("CHOKED:", "Choked: ") if not r.valid else ""
                if meth == governing and r.valid:
                    v_top = max(r.V_in, r.V_out)
            row["regime"] = ("laminar" if Re < RE_LAMINAR else
                             "untested" if not re_lo <= Re <= re_hi else
                             "high_velocity" if kind == GAS and v_top > v_max else "tested")
            pts.append(row)
        return pts

    # ------------------------------------------------------------ warnings
    def _phase_warnings(self, s1: FluidState, kind: str) -> list[ProjectWarning]:
        i, w = self.inp, []
        src = "corrugated_hose_dp:fluid"
        if kind == LIQUID:
            ps = p_sat(i.fluid, i.T_in)
            if ps is not None and i.P_in < 1.1 * ps:
                w.append(ProjectWarning("NEAR_SATURATION", f"Inlet is within 10% of the saturation pressure "
                                        f"({ps / 1e3:.1f} kPa); small pressure losses may flash the liquid.", src))
        else:
            ts = t_sat(i.fluid, i.P_in)
            if ts is not None and i.T_in - ts < 3.0:
                w.append(ProjectWarning("NEAR_SATURATION", f"Inlet gas is within 3 K of its dew point "
                                        f"({ts:.1f} K); condensation would invalidate the single-phase result.", src))
            if s1.phase == "supercritical":
                w.append(ProjectWarning("INFO", "Inlet is supercritical; treated as a compressible gas with the air fit.", src))
        return w

    def _method_warnings(self, i: HoseInputs, kind: str, res: dict[str, TrackResult], governing: str,
                         bends: list[BendInfo]) -> list[ProjectWarning]:
        c = correlations()
        w: list[ProjectWarning] = []
        add = lambda code, msg, src="corrugated_hose_dp": w.append(ProjectWarning(code, msg, src))  # noqa: E731

        for m in res:
            if not c[m]["verified"]:
                add("UNVERIFIED_DATA", f"{METHOD_LABELS[m]} coefficients transcribed by Claude; not yet "
                    "spot-checked against the source.", f"correlations:{m}")
        if any(b.regime != "sweep" for b in bends) and not bend_chart()["verified"]:
            add("UNVERIFIED_DATA", "Hawthorne 90-deg bend chart (C_B) was digitized from a scan "
                "(+/-0.005); unverified.", "data:hawthorne_bend_cb")

        if LSU not in res:
            add("INFO", "Corrugation depth/width not entered: the LSU correlation was skipped and Hawthorne governs.")
        add("INFO", "Accuracy: LSU claims about +/-20% (its Table II shows up to ~50% for 2 1/2-3 in close pitch); "
            "Hawthorne predicts its own test data within -39%/+36%.")

        fit = c["lsu"]["fit_fluid"][kind]
        if LSU in res and i.fluid.lower() != ("water" if kind == LIQUID else "air"):
            add("EXTRAPOLATED", f"LSU {kind} fit was derived for {fit}; applied to {i.fluid}.")

        for m, r in res.items():
            if not r.valid:
                add("INVALID_RESULT", f"{METHOD_LABELS[m]}: {r.invalid_reason}")
                continue
            lo_re, hi_re = min(r.Re_in, r.Re_out), max(r.Re_in, r.Re_out)
            if lo_re < RE_LAMINAR:
                add("EXTRAPOLATED", f"{METHOD_LABELS[m]}: Re = {lo_re:,.0f} is laminar; Fanning f = 16/Re used and "
                    "bend losses omitted (no laminar bend data).")
                continue
            rng = c["lsu"]["validity"]["re_" + kind] if m == LSU else c["hawthorne"]["validity"]["re"]
            if lo_re < rng[0] or hi_re > rng[1]:
                add("EXTRAPOLATED", f"{METHOD_LABELS[m]}: Re {lo_re:,.0f}-{hi_re:,.0f} is outside the tested "
                    f"range {rng[0]:,.0f}-{rng[1]:,.0f}.")
            if m == LSU and kind == GAS and max(r.V_in, r.V_out) > c["lsu"]["validity"]["gas_velocity_max_m_s"]:
                add("EXTRAPOLATED", f"Gas velocity reaches {max(r.V_in, r.V_out) * 3.28084:.0f} ft/s, above the "
                    "140 ft/s LSU limit: measured friction rose faster than the fit, so this result is likely "
                    "UNCONSERVATIVE.")

        g = c["lsu"]["validity"]
        if LSU in res:
            pp = (i.pitch - i.width) / i.depth
            sp = i.width * i.depth / i.pitch**2
            lo, hi = g["pitch_param"][i.hose_type]
            if not lo <= pp <= hi:
                add("EXTRAPOLATED", f"LSU (pitch-width)/depth = {pp:.3f} is outside the fitted range {lo}-{hi} "
                    f"({i.hose_type}).")
            if not g["shape_param"][0] <= sp <= g["shape_param"][1]:
                add("EXTRAPOLATED", f"LSU width*depth/pitch^2 = {sp:.3f} is outside the fitted range "
                    f"{g['shape_param'][0]}-{g['shape_param'][1]}.")
            if not g["D_m"][0] <= i.D <= g["D_m"][1]:
                add("EXTRAPOLATED", f"D = {i.D / 0.0254:.3f} in is outside the LSU tested range 0.535-3.111 in.")
        h = c["hawthorne"]["validity"]
        if not h["pitch_m"][0] <= i.pitch <= h["pitch_m"][1]:
            add("EXTRAPOLATED", f"Pitch {i.pitch / 0.0254:.3f} in is outside the Hawthorne tested range 0.125-0.375 in.")
        if not h["D_m"][0] <= i.D <= h["D_m"][1]:
            add("EXTRAPOLATED", f"D = {i.D / 0.0254:.3f} in is outside the Hawthorne tested range 0.765-4.46 in.")

        for n, b in enumerate(bends, 1):
            if b.regime == "gap":
                add("EXTRAPOLATED", f"Bend {n}: R/D = {b.r_over_D:.1f} falls between the Hawthorne chart (<= 5) and the "
                    "LSU sweep data (>= 12.7); no source covers it, the larger of the two losses is used.")
            if b.dashed:
                add("EXTRAPOLATED", f"Bend {n}: R/D = {b.r_over_D:.2f} is on the dashed (extrapolated) part of the "
                    "Hawthorne bend chart.")
            if b.regime in ("tight", "gap") and b.angle_deg != 90:
                add("ASSUMPTION", f"Bend {n}: Hawthorne 90-deg coefficient scaled linearly by theta/90 "
                    "(the paper's sub-90-deg exponent is illegible; linear is conservative below 90 deg).")
            if b.regime in ("sweep", "gap") and b.arc_length < i.length * 0.999:
                add("ASSUMPTION", f"Bend {n}: LSU curved-hose ratio applied over the bent arc only "
                    f"({b.arc_length:.2f} m of {i.length:.2f} m); LSU tested hoses bent along their full length.")
        if kind == GAS and len(i.bends) and any(r.n_segments > 1 for r in res.values()):
            add("INFO", "Segment march: bend losses are lumped at each bend's position along the hose.")
        return w


def _dedupe(warnings: list[ProjectWarning]) -> list[ProjectWarning]:
    seen, out = set(), []
    for w in warnings:
        key = (w.code, w.message)
        if key not in seen:
            seen.add(key)
            out.append(w)
    return out
