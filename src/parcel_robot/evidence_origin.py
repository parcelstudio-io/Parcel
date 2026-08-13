"""Typed provenance for authority-bearing boundary data — card W0-A.

This is a deliberate LEAF module: it imports nothing but the standard library,
so anything in the tree can declare provenance without dragging a package
``__init__`` behind it.

That is not tidiness, it is a measured constraint. ``EvidenceOrigin`` first
lived in :mod:`parcel_robot.core.input_health`, and importing it from
``parcel_robot.control`` pulled in ``parcel_robot.core.__init__``, which
transitively imports ``brain`` and ``instructnav`` — breaking W0-B's
leaf-package invariant for the commissioning seam
(``tests/test_w0b_commissioning.py``, the "does not import the runtime" cell).
Provenance has to be declarable from the boundary layers, so it lives where
declaring it is free.

:mod:`parcel_robot.core.input_health` re-exports both names, so
``from parcel_robot.core.input_health import EvidenceOrigin`` remains valid.
"""

from __future__ import annotations

from enum import Enum


class EvidenceOrigin(str, Enum):
    """Where an authority-bearing sample came from — DECLARED, never inferred.

    Card W0-A, defect P0-2. The retired
    ``PHYSICAL_SOURCE_NAMES = {"", "unknown", "physical"}`` whitelist let an
    *unattributed* producer mint physical authority while the real vendor
    channel (``unitree_sport``/``unitree_sport_state``) was classified a
    simulator fixture. Worse, the DEFAULTS of both boundary dataclasses —
    ``SimObservation.backend`` and ``RobotMotionState.source`` — are the string
    ``"unknown"``, so *declaring nothing* was the strongest authority in the
    system (board decision D-3).

    Provenance now travels ON the boundary datum as one of these members, and
    the only way to reach :attr:`PHYSICAL` is for a source to declare it.
    :attr:`UNKNOWN` is the fail-closed default and is never physical authority.
    """

    PHYSICAL = "physical"
    SIMULATION = "simulation"
    REPLAY = "replay"
    UNKNOWN = "unknown"


#: Origins that stand in for a physical sensor. They satisfy a requirement only
#: where a deployment is explicitly commissioned for fixtures, and only when
#: they carry a non-empty label naming the fixture.
SYNTHETIC_ORIGINS: frozenset[EvidenceOrigin] = frozenset(
    {EvidenceOrigin.SIMULATION, EvidenceOrigin.REPLAY}
)


__all__ = ["SYNTHETIC_ORIGINS", "EvidenceOrigin"]
