"""Versioned JSON project-file schema (roadmap Section 3.3)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable

CURRENT_SCHEMA_VERSION = "1.0"

# Migrations keyed by the version they upgrade *from*. Each takes the raw
# dict and returns a dict at the next version. Empty until 1.0 changes.
MIGRATIONS: dict[str, Callable[[dict], dict]] = {}


class ProjectFileError(ValueError):
    """Raised when a project file is malformed or of an unsupported version."""


@dataclass
class ProjectWarning:
    """A structured warning carried in metadata.warnings.

    code    -- stable identifier, e.g. "UNVERIFIED_DATA", "PLACEHOLDER"
    message -- human-readable explanation
    source  -- what raised it, e.g. "materials:carbon_steel/E"
    """

    code: str
    message: str
    source: str = ""

    def to_dict(self) -> dict:
        return {"code": self.code, "message": self.message, "source": self.source}

    @classmethod
    def from_dict(cls, d: dict) -> "ProjectWarning":
        return cls(code=d["code"], message=d["message"], source=d.get("source", ""))


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass
class Project:
    app_name: str
    app_version: str
    inputs: dict[str, Any] = field(default_factory=dict)
    results: dict[str, Any] = field(default_factory=dict)
    warnings: list[ProjectWarning] = field(default_factory=list)
    material_citations: list[dict] = field(default_factory=list)
    schema_version: str = CURRENT_SCHEMA_VERSION
    created: str = field(default_factory=_now)
    modified: str = field(default_factory=_now)

    def to_dict(self) -> dict:
        return {
            "schema_version": self.schema_version,
            "app_name": self.app_name,
            "app_version": self.app_version,
            "created": self.created,
            "modified": self.modified,
            "inputs": self.inputs,
            "results": self.results,
            "metadata": {
                "warnings": [w.to_dict() for w in self.warnings],
                "material_citations": self.material_citations,
            },
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Project":
        d = migrate(d)
        validate(d)
        meta = d["metadata"]
        return cls(
            app_name=d["app_name"],
            app_version=d["app_version"],
            inputs=d["inputs"],
            results=d["results"],
            warnings=[ProjectWarning.from_dict(w) for w in meta["warnings"]],
            material_citations=meta["material_citations"],
            schema_version=d["schema_version"],
            created=d["created"],
            modified=d["modified"],
        )


_REQUIRED: dict[str, type] = {
    "schema_version": str,
    "app_name": str,
    "app_version": str,
    "created": str,
    "modified": str,
    "inputs": dict,
    "results": dict,
    "metadata": dict,
}


def validate(d: dict) -> None:
    """Check structure of a project dict at CURRENT_SCHEMA_VERSION."""
    if not isinstance(d, dict):
        raise ProjectFileError("Project file root must be a JSON object.")
    for key, typ in _REQUIRED.items():
        if key not in d:
            raise ProjectFileError(f"Missing required field '{key}'.")
        if not isinstance(d[key], typ):
            raise ProjectFileError(f"Field '{key}' must be {typ.__name__}.")
    meta = d["metadata"]
    for key in ("warnings", "material_citations"):
        if not isinstance(meta.get(key), list):
            raise ProjectFileError(f"metadata.{key} must be a list.")
    for w in meta["warnings"]:
        if not isinstance(w, dict) or "code" not in w or "message" not in w:
            raise ProjectFileError("Each warning needs 'code' and 'message'.")


def migrate(d: dict) -> dict:
    """Upgrade an older project dict to CURRENT_SCHEMA_VERSION."""
    version = d.get("schema_version")
    if version is None:
        raise ProjectFileError("Missing 'schema_version'.")
    while version != CURRENT_SCHEMA_VERSION:
        if version not in MIGRATIONS:
            raise ProjectFileError(
                f"Unsupported schema_version '{version}' "
                f"(this build reads {CURRENT_SCHEMA_VERSION})."
            )
        d = MIGRATIONS[version](d)
        version = d["schema_version"]
    return d
