"""Materials Property Engine.

Temperature-dependent material properties with a citation on every value.
Property data lives in data/*.json, one file per material; this module holds no numbers.

Property kinds:
  constant     -- single value, temperature-independent
  tabular      -- (T, value) points, linear interpolation
  placeholder  -- no trustworthy value yet; always warns

Every lookup returns a PropertyResult carrying value (SI), citation, and any
warnings (unverified data, opted-in extrapolation, service-temperature notes).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import numpy as np

from ..io import ProjectWarning
from ..units import convert

_DATA_DIR = Path(__file__).parent / "data"

# Internal SI unit for each property id.
PROPERTY_SI_UNITS: dict[str, str] = {
    "E": "Pa",
    "density": "kg/m**3",
    "allowable_stress": "Pa",  # B31.3 basic allowable stress S (Sh at temperature)
    # Total linear thermal expansion relative to the table's reference temperature
    # (B31.3 Table C-1 style), stored as dimensionless strain dL/L.
    "thermal_expansion_total": "dimensionless",
}


class MaterialDataError(ValueError):
    """Lookup outside data range, unknown material/property, or bad data file."""


@dataclass(frozen=True)
class PropertyResult:
    value: float | None  # SI, None only for an empty placeholder
    unit: str
    citation: str
    warnings: tuple[ProjectWarning, ...] = ()
    is_placeholder: bool = False


@dataclass
class Material:
    id: str
    name: str
    spec: str
    group: str
    properties: dict[str, dict]
    service_notes: list[dict] = field(default_factory=list)
    occasional_notes: list[dict] = field(default_factory=list)

    def citations(self) -> list[dict]:
        out = []
        for prop, pdata in self.properties.items():
            out.append({
                "material": self.id,
                "property": prop,
                "citation": pdata.get("citation", ""),
                "verified": bool(pdata.get("verified", False)),
            })
        return out


def _strain_from_per_100ft(value: float, unit: str) -> float:
    """Convert 'length change per 100 ft' (e.g. in/100ft) to strain."""
    return convert(value, unit, "ft") / 100.0


def _to_si(prop: str, value: float, unit: str) -> float:
    if prop == "thermal_expansion_total" and unit.endswith("/100ft"):
        return _strain_from_per_100ft(value, unit.removesuffix("/100ft"))
    return convert(value, unit, PROPERTY_SI_UNITS[prop])


class MaterialDatabase:
    def __init__(self, data_dir: Path = _DATA_DIR):
        self._materials: dict[str, Material] = {}
        for path in sorted(Path(data_dir).glob("*.json")):
            self.add(json.loads(path.read_text(encoding="utf-8")))

    def add(self, d: dict) -> Material:
        """Register a material from a dict (same shape as the JSON files)."""
        for key in ("id", "name", "properties"):
            if key not in d:
                raise MaterialDataError(f"Material data missing '{key}'.")
        mat = Material(
            id=d["id"],
            name=d["name"],
            spec=d.get("spec", ""),
            group=d.get("group", ""),
            properties=d["properties"],
            service_notes=d.get("service_notes", []),
            occasional_notes=d.get("occasional_notes", []),
        )
        self._materials[mat.id] = mat
        return mat

    def ids(self) -> list[str]:
        return list(self._materials)

    def material(self, material_id: str) -> Material:
        try:
            return self._materials[material_id]
        except KeyError:
            raise MaterialDataError(f"Unknown material '{material_id}'.") from None

    def get(
        self,
        material_id: str,
        prop: str,
        T: float | None = None,
        allow_extrapolation: bool = False,
    ) -> PropertyResult:
        """Look up a property. T in kelvin (required for tabular data)."""
        mat = self.material(material_id)
        if prop not in mat.properties:
            raise MaterialDataError(f"{mat.name}: no data for property '{prop}'.")
        p = mat.properties[prop]
        source = f"materials:{mat.id}/{prop}"
        si_unit = PROPERTY_SI_UNITS[prop]
        citation = p.get("citation", "")
        warnings: list[ProjectWarning] = []
        if not p.get("verified", False) and p["kind"] != "placeholder":
            warnings.append(ProjectWarning(
                "UNVERIFIED_DATA",
                f"{mat.name} {prop}: {p.get('verification_note', 'value not yet verified against source.')}",
                source,
            ))

        kind = p["kind"]
        if kind == "placeholder":
            msg = p.get("warning") or f"{mat.name} {prop} is a placeholder; no sourced value."
            warnings.append(ProjectWarning("PLACEHOLDER", msg, source))
            value = p.get("value")
            si = _to_si(prop, value, p["unit"]) if value is not None else None
            return PropertyResult(si, si_unit, citation, tuple(warnings), True)

        if kind == "constant":
            si = _to_si(prop, p["value"], p["unit"])
            return PropertyResult(si, si_unit, citation, tuple(warnings))

        if kind == "tabular":
            if T is None:
                raise MaterialDataError(f"{mat.name} {prop}: temperature required.")
            T_src = convert(T, "kelvin", p["T_unit"])
            pts = np.asarray(p["points"], dtype=float)
            Ts, vals = pts[:, 0], pts[:, 1]
            lo, hi = Ts.min(), Ts.max()
            if T_src < lo or T_src > hi:
                if not allow_extrapolation:
                    raise MaterialDataError(
                        f"{mat.name} {prop}: T = {T_src:.1f} {p['T_unit']} outside data "
                        f"range {lo:g} to {hi:g} {p['T_unit']}."
                    )
                warnings.append(ProjectWarning(
                    "EXTRAPOLATED",
                    f"{mat.name} {prop} extrapolated to {T_src:.1f} {p['T_unit']} "
                    f"(data range {lo:g} to {hi:g}).",
                    source,
                ))
                i = 0 if T_src < lo else -2
                slope = (vals[i + 1] - vals[i]) / (Ts[i + 1] - Ts[i])
                v = vals[i] + slope * (T_src - Ts[i])
            else:
                v = float(np.interp(T_src, Ts, vals))
            return PropertyResult(_to_si(prop, v, p["unit"]), si_unit, citation, tuple(warnings))

        raise MaterialDataError(f"{mat.name} {prop}: unknown data kind '{kind}'.")

    def service_warnings(self, material_id: str, T: float) -> list[ProjectWarning]:
        """Warnings from a material's service-temperature notes (T in kelvin)."""
        mat = self.material(material_id)
        out = []
        for note in mat.service_notes:
            T_note = convert(T, "kelvin", note["T_unit"])
            above = "T_max" in note and T_note > note["T_max"]
            below = "T_min" in note and T_note < note["T_min"]
            if above or below:
                out.append(ProjectWarning("SERVICE_LIMIT", note["message"], f"materials:{mat.id}"))
        return out


    def occasional_warnings(self, material_id: str) -> list[ProjectWarning]:
        """Notes that apply when occasional-load checks (1.33 Sh) are used."""
        mat = self.material(material_id)
        return [ProjectWarning(n["code"], n["message"], f"materials:{mat.id}") for n in mat.occasional_notes]


@lru_cache(maxsize=1)
def default_database() -> MaterialDatabase:
    return MaterialDatabase()
