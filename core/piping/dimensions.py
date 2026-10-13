"""Pipe and tube dimensional data and section properties.

Pipe:  ASME B36.10M / B36.19M, NPS with schedules (data/pipe_dimensions.json).
Tube:  stainless tubing by OD and wall, e.g. ASTM A269 (data/tube_dimensions.json).

Only OD and nominal wall are stored; everything else is computed. All returned
values are SI (metres). Every function takes ``product`` ("pipe" or "tube");
the default "pipe" keeps the original pipe-only API unchanged.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from ..io import ProjectWarning
from ..units import convert

_DATA_DIR = Path(__file__).parent / "data"
_FILES = {"pipe": "pipe_dimensions.json", "tube": "tube_dimensions.json"}
PRODUCTS = ("pipe", "tube")

MILL_TOLERANCE = 0.125  # standard -12.5% wall under-tolerance for seamless pipe
SIZE_LABEL = {"pipe": "NPS", "tube": "Tube OD"}
WALL_LABEL = {"pipe": "Schedule", "tube": "Wall"}


@lru_cache(maxsize=2)
def _table(product: str = "pipe") -> dict:
    if product not in _FILES:
        raise KeyError(f"Unknown product '{product}' (expected one of {PRODUCTS}).")
    return json.loads((_DATA_DIR / _FILES[product]).read_text(encoding="utf-8"))


def mill_tolerance(product: str = "pipe") -> float:
    """Wall under-tolerance fraction applied when the mill-tolerance option is on."""
    return _table(product).get("mill_tolerance", MILL_TOLERANCE)


def _nps_value(nps: str) -> float:
    whole, _, frac = nps.partition("-")
    if "/" in whole:
        frac, whole = whole, "0"
    value = float(whole)
    if frac:
        num, den = frac.split("/")
        value += float(num) / float(den)
    return value


def list_nps(product: str = "pipe") -> list[str]:
    return [s["nps"] for s in _table(product)["sizes"]]


def nps_value(nps: str) -> float:
    return _nps_value(nps)


# Conventional thin-to-thick display order for pipe schedules.
SCHEDULE_ORDER = ["5S", "10S", "10", "20", "30", "STD", "40", "40S", "60", "XS", "80", "80S",
                  "100", "120", "140", "160", "XXS"]


def list_schedules(product: str = "pipe") -> list[str]:
    seen: list[str] = []
    for s in _table(product)["sizes"]:
        for sch in s["schedules"]:
            if sch not in seen:
                seen.append(sch)
    return sort_schedules(seen)


def sort_schedules(schedules: list[str]) -> list[str]:
    """Pipe schedules thin-to-thick; tube walls (numeric strings) ascending."""
    rank = {s: i for i, s in enumerate(SCHEDULE_ORDER)}

    def key(s: str):
        if s in rank:
            return (0, rank[s])
        try:
            return (1, float(s))
        except ValueError:
            return (2, 0.0)

    return sorted(schedules, key=key)


def wall_label(schedule: str, product: str = "pipe") -> str:
    """Display label: 'Sch 40' for pipe, '0.035"' for tube."""
    return f'{schedule}"' if product == "tube" else f"Sch {schedule}"


def schedules_for(nps: str, product: str = "pipe") -> list[str]:
    return list(_size(nps, product)["schedules"])


def _size(nps: str, product: str = "pipe") -> dict:
    for s in _table(product)["sizes"]:
        if s["nps"] == nps:
            return s
    raise KeyError(f"{SIZE_LABEL[product]} {nps} not in {product} dimension table.")


def data_warnings(product: str = "pipe") -> list[ProjectWarning]:
    t = _table(product)
    if t.get("verified"):
        return []
    return [ProjectWarning("UNVERIFIED_DATA", t["verification_note"], f"piping:{product}_dimensions")]


@dataclass(frozen=True)
class PipeSection:
    nps: str
    schedule: str
    standard: str
    od: float          # m
    wall_nominal: float  # m
    wall_used: float     # m, wall for stress/stiffness after allowances
    product: str = "pipe"

    @property
    def id_nominal(self) -> float:
        return self.od - 2 * self.wall_nominal

    @property
    def metal_area_nominal(self) -> float:
        return math.pi / 4 * (self.od**2 - self.id_nominal**2)

    @property
    def flow_area(self) -> float:
        return math.pi / 4 * self.id_nominal**2

    @property
    def _id_used(self) -> float:
        return self.od - 2 * self.wall_used

    @property
    def inertia(self) -> float:
        """Moment of inertia (m^4) based on wall_used."""
        return math.pi / 64 * (self.od**4 - self._id_used**4)

    @property
    def section_modulus(self) -> float:
        """Elastic section modulus (m^3) based on wall_used."""
        return self.inertia / (self.od / 2)

    @property
    def citation(self) -> str:
        return _table(self.product)["citations"][self.standard]


def get_section(
    nps: str,
    schedule: str,
    corrosion_allowance: float = 0.0,
    mill_tolerance: bool = False,
    product: str = "pipe",
) -> PipeSection:
    """Look up a pipe or tube and compute the wall used for stress/stiffness.

    wall_used = wall_nominal * (1 - tolerance if mill_tolerance) - corrosion_allowance,
    with tolerance 12.5% for pipe and the tube table's value (10%) for tube.
    corrosion_allowance is in metres.
    """
    size = _size(nps, product)
    if schedule not in size["schedules"]:
        raise KeyError(f"{wall_label(schedule, product)} not listed for {SIZE_LABEL[product]} {nps}.")
    entry = size["schedules"][schedule]
    unit = _table(product)["unit"]
    od = convert(size["od"], unit, "m")
    wall = convert(entry["wall"], unit, "m")
    tol = _table(product).get("mill_tolerance", MILL_TOLERANCE)
    used = wall * (1 - tol if mill_tolerance else 1.0) - corrosion_allowance
    if used <= 0:
        raise ValueError(f"{SIZE_LABEL[product]} {nps} {wall_label(schedule, product)}: allowances exceed wall thickness.")
    return PipeSection(nps, schedule, entry["standard"], od, wall, used, product)
