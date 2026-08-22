"""Bounded exploration patrol — the capability E-2 §6 item 1 names (card MOVE-1).

E2-D2 asked why 160/160 accepted motion requests produced ~0.3 m of
displacement. The measured answer (``scrum/20260821/task_20/MOVE1_STATUS.md``)
is that the requests commanded a **fixed heading that was blocked by the
robot's own owner**: the reactive safety gate refused every translating tick at
``reactive_safety.py:243``, the person predictive-stop branch, while the
arbiter — a different authority, arbitrating *intent* — accepted all 160.

The lesson is the design of this package: **a patrol must never spend its
budget commanding a heading the safety gate will refuse.** It senses the lane
it is about to drive into, and turns instead of pushing.
"""

from __future__ import annotations

from .mission import (
    DEFAULT_MAP_SWEEP_VOCABULARY,
    SAFETY_LEASE_QUERY,
    MapGrowthSample,
    PathSample,
    PatrolCommand,
    PatrolLimits,
    PatrolPolicy,
    PatrolReport,
    PatrolRunner,
    PatrolSense,
    forward_clearance_from_scan,
    ingress_queries,
    sense_from_snapshot,
)

__all__ = [
    "DEFAULT_MAP_SWEEP_VOCABULARY",
    "SAFETY_LEASE_QUERY",
    "MapGrowthSample",
    "PathSample",
    "PatrolCommand",
    "PatrolLimits",
    "PatrolPolicy",
    "PatrolReport",
    "PatrolRunner",
    "PatrolSense",
    "forward_clearance_from_scan",
    "ingress_queries",
    "sense_from_snapshot",
]
