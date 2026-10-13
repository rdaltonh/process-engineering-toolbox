"""Extension point for neutron-fluence-adjusted material properties.

Deferred (roadmap Phase 4). The interface is fixed now so later work plugs in
without changing callers.
"""

from __future__ import annotations

from .database import PropertyResult


def apply_fluence(result: PropertyResult, fluence_n_per_m2: float) -> PropertyResult:
    """Return a fluence-adjusted copy of a property result."""
    raise NotImplementedError("Neutron-fluence property adjustment is not implemented yet.")
