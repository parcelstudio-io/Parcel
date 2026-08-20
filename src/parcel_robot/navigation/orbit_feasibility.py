"""Can the robot actually walk a ring around the owner? (card R10, work item 5)

WHY THIS EXISTS AT ALL
----------------------
Until R10 there was no ``circle_owner`` tool, and the nav bench measured what a
hosted model does with a hole in its tool surface: the mini tier fabricated
``navigate_to("with owner")`` / ``("run route")`` / ``("run path")`` 5/6, and
realtime-mini instead DENIED the ability outright — *"I can't do a full circle
around you with the controls I have right now"* — which is a false statement,
because ``OrbitOwner`` is an admitted skill the ingress can run
(``bench_navmodel.md`` §2, §6).

R10 closes the hole, and closing it creates a new honesty obligation: once
``circle_owner`` exists, "I can't walk around you here" must be TRUE when it is
said and must not be said when it is false. That sentence therefore has to come
from geometry, not from the model's guess about its own abilities. This module
is that geometry — SayCan's affordance half, computed locally, returning a
machine-readable cause the local chain templates into speech
(``res_grounding.md`` §SayCan: *"a refusal must be in the always-forward band"*;
*"do not rely on the mini model to compose an accurate refusal from raw state"*).

WHAT IT DOES AND DOES NOT DECIDE
--------------------------------
It answers one question: **at radius r around this centre, which arcs of the
ring are unusable?** It never proposes a velocity, never relaxes a keepout,
never overrides ``apply_reactive_safety`` — a feasible verdict here is not a
promise that motion is safe, it is the absence of a known-blocked ring. The
reactive gate remains the single disposer, running after everything.

Used twice, from the same function, with the same clearance:

* **at admission** — over the whole planned sweep, so an impossible orbit is
  refused with a sentence instead of started and abandoned;
* **mid-orbit** — over a bounded lookahead arc, so a person who walks into the
  path aborts the orbit WITH narration rather than stalling into the existing
  ``spatial_stalled`` timeout, which says nothing an owner can act on.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

__all__ = [
    "CAUSE_BLOCKED",
    "CAUSE_NO_CENTRE",
    "CAUSE_RADIUS",
    "BlockedArc",
    "OrbitFeasibility",
    "evaluate_orbit_annulus",
]

#: Machine-readable causes. The narration templates hang off these, never off a
#: free-text string that could drift between call sites.
CAUSE_BLOCKED = "orbit_annulus_blocked"
CAUSE_RADIUS = "orbit_radius_invalid"
CAUSE_NO_CENTRE = "orbit_centre_unavailable"

#: Ring samples per full revolution. 36 puts a sample every 10 degrees, i.e.
#: every 0.28 m of arc at the 1.6 m default radius — finer than the 0.32 m
#: footprint radius, so no body-width gap can hide between two samples.
DEFAULT_SAMPLES = 36


@dataclass(frozen=True)
class BlockedArc:
    """One contiguous run of unusable ring bearings, in degrees.

    Bearings are absolute (map frame, CCW from +x). ``label`` names what blocked
    it so the refusal can say *why*, not just *no*.
    """

    start_deg: float
    end_deg: float
    label: str = ""
    clearance_m: float = 0.0

    @property
    def width_deg(self) -> float:
        return (self.end_deg - self.start_deg) % 360.0 or 360.0

    @property
    def mid_deg(self) -> float:
        return (self.start_deg + self.width_deg / 2.0) % 360.0

    def as_dict(self) -> dict[str, Any]:
        return {
            "start_deg": round(self.start_deg, 1),
            "end_deg": round(self.end_deg, 1),
            "width_deg": round(self.width_deg, 1),
            "label": self.label,
            "clearance_m": round(self.clearance_m, 3),
        }


@dataclass(frozen=True)
class OrbitFeasibility:
    """The verdict. ``feasible`` false always carries a cause and an arc."""

    feasible: bool
    cause: str = ""
    radius_m: float = 0.0
    clearance_m: float = 0.0
    samples: int = 0
    blocked: tuple[BlockedArc, ...] = ()

    @property
    def worst(self) -> BlockedArc | None:
        if not self.blocked:
            return None
        return max(self.blocked, key=lambda arc: arc.width_deg)

    def refusal_sentence(self, *, reference_deg: float | None = None) -> str:
        """The owner-facing refusal, composed LOCALLY from the failed affordance.

        ``reference_deg`` is the heading "in front of" is measured from — the
        owner's own facing when the tracker has it, else the bearing from the
        owner to the robot, so "on your left" means the owner's left rather than
        the map's. Absent both, the sentence drops the side word instead of
        inventing one.
        """

        if self.feasible:
            return ""
        if self.cause == CAUSE_NO_CENTRE:
            return "I can't circle you — I've lost track of where you are."
        if self.cause == CAUSE_RADIUS:
            return "I can't circle you — there's no room for a safe circle here."
        arc = self.worst
        if arc is None:  # pragma: no cover - blocked implies an arc
            return "I can't walk around you here — there isn't room."
        side = _side_phrase(arc.mid_deg, reference_deg)
        what = f" — {arc.label} is in the way" if arc.label else ""
        where = f" {side}" if side else ""
        return f"I can't walk around you here{what}; there isn't room{where}."

    def as_dict(self) -> dict[str, Any]:
        return {
            "feasible": self.feasible,
            "cause": self.cause,
            "radius_m": round(self.radius_m, 3),
            "clearance_m": round(self.clearance_m, 3),
            "samples": self.samples,
            "blocked": [arc.as_dict() for arc in self.blocked],
        }


def evaluate_orbit_annulus(
    *,
    centre: tuple[float, float] | None,
    radius_m: float,
    clearance_m: float,
    blocked_points: tuple[tuple[str, float, float], ...] = (),
    keepouts: tuple[tuple[str, float, float, float], ...] = (),
    arc_start_deg: float = 0.0,
    arc_sweep_deg: float = 360.0,
    samples: int = DEFAULT_SAMPLES,
) -> OrbitFeasibility:
    """Sample the ring and report which bearings the body cannot occupy.

    ``blocked_points`` are observed SURFACES ``(label, x, y)``; a ring sample is
    unusable when a surface lies within ``clearance_m`` of it. ``keepouts`` are
    ``(label, x, y, radius_m)`` discs — person keepout rings derived from the
    reactive gate, activity spaces — and a sample inside one is unusable at any
    clearance. Both are compared against the ring point, which is a robot
    CENTRE, so ``clearance_m`` must already be a centre-to-surface distance.

    Never raises on bad geometry: a non-finite radius or a missing centre is a
    verdict with a cause, because a crash inside an admission check would take
    down the tool call that was asking a safety question.
    """

    if centre is None or not all(math.isfinite(float(axis)) for axis in centre):
        return OrbitFeasibility(feasible=False, cause=CAUSE_NO_CENTRE)
    radius = float(radius_m)
    clearance = float(clearance_m)
    if not math.isfinite(radius) or radius <= 0.0:
        return OrbitFeasibility(feasible=False, cause=CAUSE_RADIUS, radius_m=0.0)
    if not math.isfinite(clearance) or clearance < 0.0:
        clearance = 0.0
    count = max(4, min(720, int(samples)))
    sweep = float(arc_sweep_deg)
    if not math.isfinite(sweep) or sweep <= 0.0:
        sweep = 360.0
    sweep = min(360.0, sweep)
    # Keep the angular resolution constant when only part of the ring is asked
    # about, so a mid-orbit lookahead is sampled as finely as an admission.
    step_deg = 360.0 / count
    arc_samples = max(2, round(sweep / step_deg) + 1)
    start = float(arc_start_deg)
    if not math.isfinite(start):
        start = 0.0

    cx, cy = float(centre[0]), float(centre[1])
    surfaces = _clean_points(blocked_points)
    discs = _clean_discs(keepouts)

    hits: list[tuple[float, str, float]] = []
    for index in range(arc_samples):
        bearing = (start + index * step_deg) % 360.0
        theta = math.radians(bearing)
        px = cx + radius * math.cos(theta)
        py = cy + radius * math.sin(theta)
        label, gap = _closest_conflict(px, py, surfaces, discs, clearance)
        if label is not None:
            hits.append((bearing, label, gap))
    if not hits:
        return OrbitFeasibility(
            feasible=True,
            radius_m=radius,
            clearance_m=clearance,
            samples=arc_samples,
        )
    return OrbitFeasibility(
        feasible=False,
        cause=CAUSE_BLOCKED,
        radius_m=radius,
        clearance_m=clearance,
        samples=arc_samples,
        blocked=_merge_arcs(hits, step_deg),
    )


# --- internals --------------------------------------------------------------


def _clean_points(
    points: tuple[tuple[str, float, float], ...],
) -> tuple[tuple[str, float, float], ...]:
    cleaned: list[tuple[str, float, float]] = []
    for item in points or ():
        try:
            label, x, y = item[0], float(item[1]), float(item[2])
        except (IndexError, TypeError, ValueError):
            continue
        if math.isfinite(x) and math.isfinite(y):
            cleaned.append((str(label or ""), x, y))
    return tuple(cleaned)


def _clean_discs(
    discs: tuple[tuple[str, float, float, float], ...],
) -> tuple[tuple[str, float, float, float], ...]:
    cleaned: list[tuple[str, float, float, float]] = []
    for item in discs or ():
        try:
            label, x, y, radius = item[0], float(item[1]), float(item[2]), float(item[3])
        except (IndexError, TypeError, ValueError):
            continue
        if math.isfinite(x) and math.isfinite(y) and math.isfinite(radius) and radius > 0.0:
            cleaned.append((str(label or ""), x, y, radius))
    return tuple(cleaned)


def _closest_conflict(
    px: float,
    py: float,
    surfaces: tuple[tuple[str, float, float], ...],
    discs: tuple[tuple[str, float, float, float], ...],
    clearance: float,
) -> tuple[str | None, float]:
    """The nearest thing that makes ``(px, py)`` unusable, or ``(None, inf)``."""

    worst_label: str | None = None
    worst_gap = math.inf
    for label, x, y, radius in discs:
        gap = math.hypot(px - x, py - y) - radius
        if gap < 0.0 and gap < worst_gap:
            worst_label, worst_gap = (label or "someone"), gap
    for label, x, y in surfaces:
        gap = math.hypot(px - x, py - y) - clearance
        if gap < 0.0 and gap < worst_gap:
            worst_label, worst_gap = (label or "something"), gap
    return worst_label, worst_gap


def _merge_arcs(
    hits: list[tuple[float, str, float]],
    step_deg: float,
) -> tuple[BlockedArc, ...]:
    """Group contiguous blocked samples into arcs, keeping the worst label."""

    ordered = sorted(hits, key=lambda item: item[0])
    arcs: list[BlockedArc] = []
    run_start = ordered[0][0]
    run_end = ordered[0][0]
    run_label = ordered[0][1]
    run_gap = ordered[0][2]
    for bearing, label, gap in ordered[1:]:
        if bearing - run_end <= step_deg * 1.5 + 1e-9:
            run_end = bearing
            if gap < run_gap:
                run_label, run_gap = label, gap
            continue
        arcs.append(
            BlockedArc(
                start_deg=run_start,
                end_deg=run_end,
                label=run_label,
                clearance_m=abs(run_gap),
            )
        )
        run_start = run_end = bearing
        run_label, run_gap = label, gap
    arcs.append(
        BlockedArc(
            start_deg=run_start,
            end_deg=run_end,
            label=run_label,
            clearance_m=abs(run_gap),
        )
    )
    # A run that wraps 360 -> 0 is one arc, not two. Only ever merges the first
    # and last runs, and only when they actually touch across the seam.
    if len(arcs) > 1:
        first, last = arcs[0], arcs[-1]
        if (first.start_deg - (last.end_deg - 360.0)) <= step_deg * 1.5 + 1e-9:
            merged = BlockedArc(
                start_deg=last.start_deg,
                end_deg=first.end_deg + 360.0,
                label=last.label if last.clearance_m > first.clearance_m else first.label,
                clearance_m=max(last.clearance_m, first.clearance_m),
            )
            arcs = [merged, *arcs[1:-1]]
    return tuple(arcs)


def _side_phrase(bearing_deg: float, reference_deg: float | None) -> str:
    """"on your left" / "behind you" — relative to the owner, or nothing."""

    if reference_deg is None or not math.isfinite(float(reference_deg)):
        return ""
    delta = (float(bearing_deg) - float(reference_deg) + 180.0) % 360.0 - 180.0
    if -45.0 <= delta <= 45.0:
        return "in front of you"
    if 45.0 < delta <= 135.0:
        return "on your left"
    if -135.0 <= delta < -45.0:
        return "on your right"
    return "behind you"
