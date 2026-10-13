"""Pipe dimensional data (ASME B36.10M / B36.19M) and section properties.

Only OD and nominal wall are stored (data/pipe_dimensions.json). Everything
else is computed. All returned values are SI (metres).
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from ..io import ProjectWarning
from ..units import convert

_DATA = Path(__file__).parent / "data" / "pipe_dimensions.json"

MILL_TOLERANCE = 0.125  # standard -12.5% wall under-tolerance for seamless pipe


@lru_cache(maxsize=1)
def _table() -> dict:
    return json.loads(_DATA.read_text(encoding="utf-8"))


def _nps_value(nps: str) -> float:
    whole, _, frac = nps.partition("-")
    if "/" in whole:
        frac, whole = whole, "0"
    value = float(whole)
    if frac:
        num, den = frac.split("/")
        value += float(num) / float(den)
    return value


def list_nps() -> list[str]:
    return [s["nps"] for s in _table()["sizes"]]


def nps_value(nps: str) -> float:
    return _nps_value(nps)


# Conventional thin-to-thick display order.
SCHEDULE_ORDER = ["5S", "10S", "10", "20", "30", "STD", "40", "40S", "60", "XS", "80", "80S",
                  "100", "120", "140", "160", "XXS"]


def list_schedules() -> list[str]:
    seen: list[str] = []
    for s in _table()["sizes"]:
        for sch in s["schedules"]:
            if sch not in seen:
                seen.append(sch)
    return sort_schedules(seen)


def sort_schedules(schedules: list[str]) -> list[str]:
    rank = {s: i for i, s in enumerate(SCHEDULE_ORDER)}
    return sorted(schedules, key=lambda s: rank.get(s, len(rank)))


def schedules_for(nps: str) -> list[str]:
    return list(_size(nps)["schedules"])


def _size(nps: str) -> dict:
    for s in _table()["sizes"]:
        if s["nps"] == nps:
            return s
    raise KeyError(f"NPS {nps} not in pipe dimension table.")


def data_warnings() -> list[ProjectWarning]:
    t = _table()
    if t.get("verified"):
        return []
    return [ProjectWarning("UNVERIFIED_DATA", t["verification_note"], "piping:pipe_dimensions")]


@dataclass(frozen=True)
class PipeSection:
    nps: str
    schedule: str
    standard: str
    od: float          # m
    wall_nominal: float  # m
    wall_used: float     # m, wall for stress/stiffness after allowances

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
        return _table()["citations"][self.standard]


def get_section(
    nps: str,
    schedule: str,
    corrosion_allowance: float = 0.0,
    mill_tolerance: bool = False,
) -> PipeSection:
    """Look up a pipe and compute the wall used for stress/stiffness.

    wall_used = wall_nominal * (1 - 0.125 if mill_tolerance) - corrosion_allowance
    corrosion_allowance is in metres.
    """
    size = _size(nps)
    if schedule not in size["schedules"]:
        raise KeyError(f"Schedule {schedule} not listed for NPS {nps}.")
    entry = size["schedules"][schedule]
    unit = _table()["unit"]
    od = convert(size["od"], unit, "m")
    wall = convert(entry["wall"], unit, "m")
    used = wall * (1 - MILL_TOLERANCE if mill_tolerance else 1.0) - corrosion_allowance
    if used <= 0:
        raise ValueError(
            f"NPS {nps} Sch {schedule}: allowances exceed wall thickness."
        )
    return PipeSection(nps, schedule, entry["standard"], od, wall, used)
