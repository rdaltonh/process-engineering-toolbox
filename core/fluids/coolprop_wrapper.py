"""Thin CoolProp interface: the suite's single fluid-property backend.

All values SI: Pa (absolute), K, kg/m^3, Pa*s, J/kg, m/s. Apps never call
CoolProp directly, so a backend change (or caching) happens here once.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass

import CoolProp
import CoolProp.CoolProp as CP

# Fluids offered in app dropdowns (CoolProp names). Any CoolProp fluid string
# is accepted by the functions below.
COMMON_FLUIDS: dict[str, str] = {
    "Water": "Water",
    "Nitrogen": "Nitrogen",
    "Helium": "Helium",
    "Argon": "Argon",
    "Hydrogen": "Hydrogen",
    "Oxygen": "Oxygen",
    "Neon": "Neon",
    "Air": "Air",
    "CarbonDioxide": "Carbon dioxide",
    "Methane": "Methane",
}

# CoolProp phase strings that behave as an incompressible liquid.
LIQUID_PHASES = {"liquid", "supercritical_liquid"}


class FluidError(ValueError):
    """Raised for unknown fluids or states CoolProp cannot evaluate."""


@dataclass(frozen=True)
class FluidState:
    fluid: str
    P: float      # Pa abs
    T: float      # K
    rho: float    # kg/m^3
    mu: float     # Pa*s
    h: float      # J/kg
    a: float      # speed of sound, m/s
    phase: str    # CoolProp phase string

    @property
    def is_liquid(self) -> bool:
        return self.phase in LIQUID_PHASES

    @property
    def is_two_phase(self) -> bool:
        return self.phase == "twophase"


_PHASE_NAMES = {
    CoolProp.iphase_liquid: "liquid",
    CoolProp.iphase_gas: "gas",
    CoolProp.iphase_twophase: "twophase",
    CoolProp.iphase_supercritical: "supercritical",
    CoolProp.iphase_supercritical_gas: "supercritical_gas",
    CoolProp.iphase_supercritical_liquid: "supercritical_liquid",
    CoolProp.iphase_critical_point: "critical_point",
}


_local = threading.local()  # AbstractState is mutable: one per thread (Streamlit serves sessions on threads)


def _abstract_state(fluid: str) -> CP.AbstractState:
    # Low-level interface: ~7x faster than PropsSI for repeated state updates (segment marches, sweeps).
    cache = _local.__dict__.setdefault("states", {})
    if fluid not in cache:
        try:
            cache[fluid] = CP.AbstractState("HEOS", fluid)
        except ValueError as e:
            raise FluidError(f"Unknown fluid '{fluid}': {e}") from e
    return cache[fluid]


def _props(fluid: str, pair: int, v1: float, v2: float, desc: str) -> FluidState:
    AS = _abstract_state(fluid)
    try:
        AS.update(pair, v1, v2)
        phase = _PHASE_NAMES.get(AS.phase(), "unknown")
        rho, T, P, h = AS.rhomass(), AS.T(), AS.p(), AS.hmass()
        if phase == "twophase":
            mu = a = float("nan")
        else:
            mu, a = AS.viscosity(), AS.speed_sound()
    except ValueError as e:
        raise FluidError(f"CoolProp could not evaluate {fluid} at {desc}: {e}") from e
    return FluidState(fluid, P, T, rho, mu, h, a, phase)


def state_PT(fluid: str, P: float, T: float) -> FluidState:
    """State from absolute pressure and temperature."""
    return _props(fluid, CoolProp.PT_INPUTS, P, T, f"P={P:g} Pa, T={T:g} K")


def state_PH(fluid: str, P: float, h: float) -> FluidState:
    """State from absolute pressure and specific enthalpy (e.g. isenthalpic expansion)."""
    return _props(fluid, CoolProp.HmassP_INPUTS, h, P, f"P={P:g} Pa, h={h:g} J/kg")


def critical_point(fluid: str) -> tuple[float, float]:
    """(P_crit, T_crit)."""
    try:
        return CP.PropsSI("Pcrit", fluid), CP.PropsSI("Tcrit", fluid)
    except ValueError as e:
        raise FluidError(f"Unknown fluid '{fluid}': {e}") from e


def p_sat(fluid: str, T: float) -> float | None:
    """Saturation (bubble-point) pressure at T; None above the critical point or outside the model range."""
    try:
        return CP.PropsSI("P", "T", T, "Q", 0, fluid)
    except ValueError:
        return None


def t_sat(fluid: str, P: float) -> float | None:
    """Saturation (dew-point) temperature at P; None above the critical pressure or outside the model range."""
    try:
        return CP.PropsSI("T", "P", P, "Q", 1, fluid)
    except ValueError:
        return None
