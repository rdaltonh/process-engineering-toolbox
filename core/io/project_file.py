"""Save/load project files.

pint Quantities anywhere in inputs/results serialize as {"value": x, "unit": "..."}
and are restored as Quantities on load, so units survive the round trip.
"""

from __future__ import annotations

import json
from pathlib import Path

from ..units import Q_, ureg
from .config_schema import Project, _now


def _encode(obj):
    if isinstance(obj, ureg.Quantity):
        return {"value": obj.magnitude, "unit": f"{obj.units}"}
    raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")


def _decode(d: dict):
    if set(d) == {"value", "unit"} and isinstance(d["unit"], str):
        return Q_(d["value"], d["unit"])
    return d


def dumps(project: Project) -> str:
    return json.dumps(project.to_dict(), default=_encode, indent=2)


def loads(text: str) -> Project:
    return Project.from_dict(json.loads(text, object_hook=_decode))


def save(project: Project, path: str | Path) -> Path:
    """Write a project file, updating its 'modified' timestamp."""
    project.modified = _now()
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(dumps(project), encoding="utf-8")
    return path


def load(path: str | Path) -> Project:
    return loads(Path(path).read_text(encoding="utf-8"))
