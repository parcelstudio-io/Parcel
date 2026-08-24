"""Refuter 4b's machinery: whole-map global matching, and the A4/A10 latch.

Two things live here, and they are different in kind.

:class:`GlobalMatcher` is a **measurement**: given the observed scan, it scores
every pose hypothesis in the room and reports the best, the best hypothesis at
least :data:`SEPARATION_M` away from it, and the relative gap between them.
That gap is A4's "globally discriminative geometric evidence — a relocalization
match whose second-best candidate is worse by a pre-registered margin across
the whole map, not a local residual gate".  The shipped
``ScanMatchLocalizer._relocalize`` computes a best-scoring keyframe and never
reports a runner-up, so this number does not exist in the product; that is a
fix-list line, and here it is computed in the harness so the refuter can ask
the question A4 asks.

:class:`ArmingLatch` is a **proposed policy**, modelled here and wired in front
of an arm only in the ``gate=on`` configuration.  Neither arm carries it today,
which is exactly what refuter 4b is measuring.

The yaw sweep is exact rather than sampled: the simulator's rays are uniform
over 2 pi, so the scan a body would take at the same position with a different
yaw is a circular shift of the same ranges.  One raycast per position covers
every heading.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

import numpy as np
from room import ROOM_HALF_M, SCAN_RAYS, RoomWorld
from stack import PoseStack

from parcel_robot.localization.contract import compose_se2, invert_se2

#: Hypothesis grid over the room, metres.  0.4 m is four GICP voxels: fine
#: enough that the true pose is always within half a cell of a hypothesis, and
#: coarse enough that the whole map is 200-odd raycasts.
GRID_M = 0.40
#: Sub-grid the two finalists are re-scored on, metres.
REFINE_M = 0.10
#: A runner-up nearer than this is the same hypothesis, not a competitor.
SEPARATION_M = 1.00
#: PRE-REGISTERED.  Re-arm needs the runner-up to be at least this much worse,
#: as a fraction of the best hypothesis's residual.
MARGIN_MIN = 0.25
#: PRE-REGISTERED.  ``bridge/timing.py``'s ``localization_jump_m`` is UNMEASURED
#: on every host, so the latch's jump bound is stated here instead of imported:
#: 0.35 m is below the 0.5 m arrival band, so a jump that could move the robot
#: across the band cannot pass unlatched.
JUMP_BOUND_M = 0.35
#: How often the latch re-asks the whole-map question, in control ticks.
AMBIGUITY_PERIOD = 10
#: Operator pose-reset transaction: the stated pose is accepted only if the
#: scan agrees with it this well (RMS over matched rays, metres).
OPERATOR_AGREEMENT_RMS_M = 0.35


@dataclass(frozen=True)
class GlobalMatch:
    """The whole-map answer: where, how well, and how alone."""

    pose: tuple[float, float, float]
    rms_m: float
    runner_up: tuple[float, float, float]
    runner_up_rms_m: float

    @property
    def margin(self) -> float:
        """Relative gap to the best competitor at least ``SEPARATION_M`` away."""

        if not math.isfinite(self.rms_m) or self.rms_m <= 0.0:
            return math.inf if math.isfinite(self.runner_up_rms_m) else 0.0
        if not math.isfinite(self.runner_up_rms_m):
            return math.inf
        return (self.runner_up_rms_m - self.rms_m) / self.rms_m


class GlobalMatcher:
    """Scan-vs-room matching over every pose in the room.  One per world."""

    def __init__(self, world: RoomWorld) -> None:
        self.world = world
        self._positions: list[tuple[float, float]] = []
        self._templates: np.ndarray | None = None

    def _build(self) -> None:
        if self._templates is not None:
            return
        rng = np.random.default_rng(0)
        positions: list[tuple[float, float]] = []
        rows: list[np.ndarray] = []
        steps = int(2 * ROOM_HALF_M / GRID_M)
        for i in range(steps + 1):
            for j in range(steps + 1):
                x = -ROOM_HALF_M + i * GRID_M
                y = -ROOM_HALF_M + j * GRID_M
                if self.world.clearance_m(x, y) <= 0.0:
                    continue
                scan = self.world.scan(x, y, 0.0, rng)
                positions.append((x, y))
                rows.append(np.asarray(scan.ranges_m, dtype=np.float64))
        self._positions = positions
        self._templates = np.stack(rows) if rows else np.zeros((0, SCAN_RAYS))

    def match(self, observed: Any) -> GlobalMatch:
        """Best and runner-up hypotheses for one observed :class:`PlanarScan`.

        Two stages, because one is not enough.  A 0.4 m grid puts the true pose
        up to 0.28 m from the nearest hypothesis, and 0.2 m of position error
        costs about 0.5 m of RMS in a room this size — the same order as the
        aliased twin's residual, which would make the margin meaningless.  So
        the coarse pass only picks WHERE to look: the best cell and the best
        cell at least :data:`SEPARATION_M` away are each refined on a 0.1 m
        sub-grid, and the margin is computed from the refined residuals.
        """

        self._build()
        assert self._templates is not None
        query = np.asarray(observed.ranges_m, dtype=np.float64)
        if not np.isfinite(query).any() or self._templates.shape[0] == 0:
            return GlobalMatch((0.0, 0.0, 0.0), math.inf, (0.0, 0.0, 0.0), math.inf)
        coarse_rms, _ = self._sweep(self._templates, query)
        order = np.argsort(coarse_rms)
        top = int(order[0])
        rival = None
        for index in order[1:]:
            if math.dist(self._positions[int(index)], self._positions[top]) >= SEPARATION_M:
                rival = int(index)
                break
        best_pose, best_rms = self._refine(self._positions[top], query)
        if rival is None:
            return GlobalMatch(best_pose, best_rms, best_pose, math.inf)
        rival_pose, rival_rms = self._refine(self._positions[rival], query)
        # Refinement can overturn the coarse ordering — and does, whenever the
        # true pose fell between coarse cells. Order AFTER refining, or the
        # margin is signed by an artefact of the grid.
        if rival_rms < best_rms:
            best_pose, best_rms, rival_pose, rival_rms = (
                rival_pose, rival_rms, best_pose, best_rms
            )
        return GlobalMatch(best_pose, best_rms, rival_pose, rival_rms)

    def _sweep(
        self, templates: np.ndarray, query: np.ndarray
    ) -> tuple[np.ndarray, np.ndarray]:
        """Per-template best RMS over every heading, and the shift that won."""

        best_rms = np.full(templates.shape[0], math.inf)
        best_shift = np.zeros(templates.shape[0], dtype=int)
        finite_t = np.isfinite(templates)
        for shift in range(SCAN_RAYS):
            rotated = np.roll(query, shift)
            mask = np.isfinite(rotated) & finite_t
            diff = np.where(mask, templates - rotated, 0.0)
            counts = mask.sum(axis=1)
            rms = np.where(
                counts > 0,
                np.sqrt((diff * diff).sum(axis=1) / np.maximum(counts, 1)),
                math.inf,
            )
            improved = rms < best_rms
            best_rms = np.where(improved, rms, best_rms)
            best_shift = np.where(improved, shift, best_shift)
        return best_rms, best_shift

    def _refine(
        self, around: tuple[float, float], query: np.ndarray
    ) -> tuple[tuple[float, float, float], float]:
        """Re-score one neighbourhood on a 0.1 m sub-grid, full heading sweep."""

        rng = np.random.default_rng(0)
        positions: list[tuple[float, float]] = []
        rows: list[np.ndarray] = []
        for i in range(-2, 3):
            for j in range(-2, 3):
                x = around[0] + i * REFINE_M
                y = around[1] + j * REFINE_M
                if self.world.clearance_m(x, y) <= 0.0:
                    continue
                positions.append((x, y))
                rows.append(np.asarray(self.world.scan(x, y, 0.0, rng).ranges_m))
        if not rows:
            return (around[0], around[1], 0.0), math.inf
        rms, shift = self._sweep(np.stack(rows), query)
        index = int(np.argmin(rms))
        yaw = 2.0 * math.pi * int(shift[index]) / SCAN_RAYS
        return (
            positions[index][0],
            positions[index][1],
            math.atan2(math.sin(yaw), math.cos(yaw)),
        ), float(rms[index])

    def agreement_rms_m(self, observed: Any, pose: tuple[float, float, float]) -> float:
        """How well the observed scan agrees with a STATED pose (operator path)."""

        rng = np.random.default_rng(0)
        expected = np.asarray(
            self.world.scan(pose[0], pose[1], pose[2], rng).ranges_m, dtype=np.float64
        )
        query = np.asarray(observed.ranges_m, dtype=np.float64)
        mask = np.isfinite(expected) & np.isfinite(query)
        if not mask.any():
            return math.inf
        diff = expected[mask] - query[mask]
        return float(math.sqrt(float((diff * diff).mean())))


@dataclass
class ArmingRecord:
    """One journalled latch or re-arm event.  A4 requires the journal."""

    t_s: float
    event: str
    trigger: str
    value: float


class ArmingLatch:
    """A4 + A10, modelled: latch on discontinuity, re-arm only two ways.

    The A10 sources this study can see are the localization jump and whole-map
    ambiguity.  The pickup/restart signals are deliberately DISARMED for
    refuter 4b — the kidnap keeps the ODOM feed continuous and raises no boot
    epoch, so an arm that catches it must catch it geometrically or not at all.
    That is the H7 mechanism, and a latch fed a pickup flag would be testing
    the flag.
    """

    def __init__(self, matcher: GlobalMatcher, *, enabled: bool = True) -> None:
        self.matcher = matcher
        self.enabled = bool(enabled)
        self.latched = False
        self.journal: list[ArmingRecord] = []
        self._ticks = 0
        self._rearm_ticks = 0
        self.last_margin: float = math.inf

    def observe(self, *, update: Any, scan: Any, t_s: float) -> None:
        """One tick of evidence.  Latches; never re-arms."""

        if not self.enabled:
            return
        self._ticks += 1
        jump = float(getattr(update, "jump_m", 0.0) or 0.0)
        if jump > JUMP_BOUND_M and not self.latched:
            self.latched = True
            self.journal.append(ArmingRecord(t_s, "latched", "localization_jump_m", jump))
            return
        if scan is None or self._ticks % AMBIGUITY_PERIOD:
            return
        match = self.matcher.match(scan)
        self.last_margin = match.margin
        if match.margin < MARGIN_MIN and not self.latched:
            self.latched = True
            self.journal.append(
                ArmingRecord(t_s, "latched", "global_match_ambiguity", match.margin)
            )

    def try_rearm_by_margin(self, scan: Any, stack: PoseStack, t_s: float) -> bool:
        """A4 path (a): globally discriminative geometry, whole map."""

        if not self.latched or scan is None:
            return False
        # A whole-map match is a relocalization, not a control-rate signal:
        # asking every tick would both misrepresent its cost and dominate the
        # bench's runtime.  Same cadence as the ambiguity check.
        self._rearm_ticks += 1
        if self._rearm_ticks % AMBIGUITY_PERIOD:
            return False
        match = self.matcher.match(scan)
        self.last_margin = match.margin
        if match.margin < MARGIN_MIN:
            return False
        _reanchor(stack, match.pose)
        self.latched = False
        self.journal.append(
            ArmingRecord(t_s, "rearmed", "global_match_margin", match.margin)
        )
        return True

    def try_rearm_by_operator(
        self,
        scan: Any,
        stack: PoseStack,
        stated: tuple[float, float, float],
        t_s: float,
    ) -> bool:
        """A4 path (b): the operator states the pose, the scan has to agree."""

        if not self.latched or scan is None:
            return False
        rms = self.matcher.agreement_rms_m(scan, stated)
        if rms > OPERATOR_AGREEMENT_RMS_M:
            self.journal.append(
                ArmingRecord(t_s, "operator_refused", "scan_agreement_rms_m", rms)
            )
            return False
        _reanchor(stack, stated)
        self.latched = False
        self.journal.append(
            ArmingRecord(t_s, "rearmed", "operator_pose_reset", rms)
        )
        return True


def _reanchor(stack: PoseStack, pose: tuple[float, float, float]) -> None:
    """Re-bind MAP to a verified pose without disturbing the ODOM integrator."""

    odom = stack.odom_pose()
    localizer = stack.localizer
    localizer._T_map_odom = compose_se2(pose, invert_se2((odom.x, odom.y, odom.yaw)))
    localizer._pose_map_base = pose
