"""Shared unit registry and conversion helpers.

All calculations in the suite run in SI internally. pint is used at the
boundaries: UI input/output and project-file serialization.
"""

from __future__ import annotations

import pint

ureg = pint.UnitRegistry()
ureg.define("psf = lbf / foot**2")
ureg.define("plf = lbf / foot")
Q_ = ureg.Quantity

# Display unit sets, keyed by quantity "kind". Apps pick a system and look up
# the unit for each kind instead of hard-coding unit strings in widgets.
UNIT_SYSTEMS: dict[str, dict[str, str]] = {
    "US": {
        "temperature": "degF",
        "stress": "psi",
        "modulus": "Mpsi",
        "length": "ft",
        "small_length": "in",
        "deflection": "in",
        "line_weight": "lbf/ft",
        "section_modulus": "in**3",
        "inertia": "in**4",
        "area": "in**2",
        "density": "lb/in**3",
        "expansion_per_100ft": "in",
        "pressure": "psi",
        "speed": "mph",
        "area_load": "psf",
    },
    "SI": {
        "temperature": "degC",
        "stress": "MPa",
        "modulus": "GPa",
        "length": "m",
        "small_length": "mm",
        "deflection": "mm",
        "line_weight": "N/m",
        "section_modulus": "mm**3",
        "inertia": "mm**4",
        "area": "mm**2",
        "density": "kg/m**3",
        "expansion_per_100ft": "mm",
        "pressure": "kPa",
        "speed": "m/s",
        "area_load": "kPa",
    },
}

# SI base unit used internally for each kind.
SI_UNITS: dict[str, str] = {
    "temperature": "kelvin",
    "stress": "Pa",
    "modulus": "Pa",
    "length": "m",
    "small_length": "m",
    "deflection": "m",
    "line_weight": "N/m",
    "section_modulus": "m**3",
    "inertia": "m**4",
    "area": "m**2",
    "density": "kg/m**3",
    "expansion_per_100ft": "m",
    "pressure": "Pa",
    "speed": "m/s",
    "area_load": "Pa",
}


def convert(value: float, from_unit: str, to_unit: str) -> float:
    """Convert a scalar between units (handles offset temperatures)."""
    return Q_(value, from_unit).to(to_unit).magnitude


def to_si(value: float, unit: str, kind: str) -> float:
    """Convert a display value of the given kind to its internal SI unit."""
    return convert(value, unit, SI_UNITS[kind])


def from_si(value: float, kind: str, system: str) -> float:
    """Convert an internal SI value of the given kind to a display system."""
    return convert(value, SI_UNITS[kind], UNIT_SYSTEMS[system][kind])


def display_unit(kind: str, system: str) -> str:
    """Short, human-readable unit label for a kind in a display system."""
    return f"{ureg.Unit(UNIT_SYSTEMS[system][kind]):~P}"
