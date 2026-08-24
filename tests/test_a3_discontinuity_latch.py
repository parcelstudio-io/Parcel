"""Card A3 — DISCONTINUITY-LATCH: the six A10 signals, the margin, the reset.

Grounding, all of it measured before this card existed:

* ``research/20260824/nav-core/RESULTS.md`` §"Refuter 4b" — both shipped arms
  kept translating after a kidnap into a C2-aliased room, on 824-840 of 840
  HEALTHY ticks, 0.84 m for arm A.  The modelled A4/A10 latch held them at
  0.00 m; the whole-map margin measured 2.2-30.7 in a normal layout against
  0.002-0.03 in the aliased one, threshold 0.25.
* ``research/20260824/nav-core/REFUTER_4B_REMEASURE.md`` — the operator arm's
  first measurement was an artefact: a 1 Hz live-truth feed re-armed **79
  times** in one episode.  Re-measured as a ONE-SHOT transaction it re-arms
  once, the standing ambiguity re-latches, and every episode ends latched.
* ``research/20260824/nav-core/VERDICT.md`` Amendment note 2 — the
  kidnap-ONSET catch in a NORMAL layout, through the jump bound, "was never
  exercised and is now an A3 acceptance criterion.  No journal anywhere fires
  ``localization_jump_m`` yet."  That row is :func:`
  test_a_normal_layout_kidnap_onset_fires_the_jump_bound_and_journals_it`.
* ``CLAUDE_RESPONSE.md`` addenda A4 (the re-arm rule) and A10 (the six
  signals), and NAV-CORE fix 5 (R3's false arrival at ``p = 0.9922`` with the
  body 0.534 m out).

**The world here is replicated, not imported.**  NAV-CORE's room is MuJoCo and
its harness carries a whole navigator; this file needs two rooms and a ray
engine, so it builds them the way ``tests/test_h7_localization_contract.py``
does — polylines sampled at 2 cm, nearest sampled point per bearing.  That is
not a sensor model and does not pretend to be one.  What it IS, and what the
kidnap rows depend on, is checked rather than assumed: the aliased room's C2
image produces a scan identical to float noise (:func:
`test_the_aliased_room_is_aliased_to_float_noise`) and the normal room's does
not (:func:`test_the_whole_map_margin_separates_a_normal_room_from_an_aliased_one`).

**Every headline row has a control.**  A latch that fires on everything holds a
body at 0.00 m too, so each cell that asserts a refusal is paired with the run
that must NOT refuse: the same kidnap with the latch disabled (2.7 m of motion),
the same travel with no kidnap (no jump trigger), signals just inside their
bounds, and the shipped relocalization that still commits.
"""

from __future__ import annotations

import math
import sys
from functools import lru_cache
from pathlib import Path

import numpy as np
import pytest

REPO = Path(__file__).resolve().parents[1]
if str(REPO / "src") not in sys.path:
    sys.path.insert(0, str(REPO / "src"))

from parcel_robot.backends.base import (
    LidarObstacle,
    OwnerTrack,
    RobotPose,
    SimObservation,
    VelocityCommand,
)
from parcel_robot.bridge.timing import (
    ENVELOPE_RECORD_SCHEMA_V1,
    ENVELOPE_TERMS_V1,
    UNMEASURED,
    derive_envelope,
    load_stopping_envelope_record,
)
from parcel_robot.core.input_health import HealthAction
from parcel_robot.localization.contract import (
    RelocalizationMatch,
    ScanFrame,
    compose_se2,
    invert_se2,
)
from parcel_robot.localization.discontinuity import (
    LOCALIZATION_JUMP_BOUND_M,
    ArmingLatch,
    BodySignals,
    CarriedSignature,
    DiscontinuityTrigger,
    LatchBounds,
    OperatorPoseReset,
    OperatorResetState,
    StubCarriedSignatureSource,
)
from parcel_robot.localization.gicp_provider import (
    ScanMatchConfig,
    ScanMatchLocalizer,
    small_gicp_available,
)
from parcel_robot.localization.global_match import (
    GLOBAL_MATCH_MARGIN_MIN,
    OPERATOR_AGREEMENT_RMS_M,
    WholeMapMatcher,
)
from parcel_robot.localization.jump_journal import (
    ENVELOPE_JUMP_TERM,
    LocalizationJumpJournal,
)
from parcel_robot.localization.pose_adapter import LocalizedPoseProvider
from parcel_robot.navigation.reactive_safety import (
    ReactiveSafetyPolicy,
    apply_reactive_safety,
)
from parcel_robot.pose import DriftingOdomProvider, Frame, PoseEstimate, PoseHealth
from parcel_robot.robot_profile import DEFAULT_ROBOT_PROFILE

#: The C2-aliased margin NAV-CORE measured (0.002-0.03 with its 8 m room and
#: MuJoCo rays).  This room's alias is exact to float noise, so the bar here is
#: the card's: at or under 0.005.
ALIASED_MARGIN_MAX = 0.005

RAYS = 360
DT_S = 0.1
FOOTPRINT_M = DEFAULT_ROBOT_PROFILE.footprint_radius_m
HALF_M = 3.0
BEARINGS = -math.pi + (np.arange(RAYS) + 0.5) * 2 * math.pi / RAYS

pytestmark = pytest.mark.skipif(
    not small_gicp_available(),
    reason="the localization extra (small-gicp) is not installed",
)


# ---------------------------------------------------------------------------
# two rooms
# ---------------------------------------------------------------------------
def _rect(cx: float, cy: float, hx: float, hy: float) -> list[tuple[float, ...]]:
    return [
        (cx - hx, cy - hy, cx + hx, cy - hy),
        (cx + hx, cy - hy, cx + hx, cy + hy),
        (cx + hx, cy + hy, cx - hx, cy + hy),
        (cx - hx, cy + hy, cx - hx, cy - hy),
    ]


def c2_image(pose: tuple[float, float, float]) -> tuple[float, float, float]:
    """The 180 degree rotation of a pose about the room centre."""

    x, y, yaw = pose
    return (-x, -y, math.atan2(math.sin(yaw + math.pi), math.cos(yaw + math.pi)))


def _c2_segment(segment: tuple[float, ...]) -> tuple[float, ...]:
    x0, y0, x1, y1 = segment
    return (-x0, -y0, -x1, -y1)


#: HALF the aliased room; the other half is this half's exact 180 degree image,
#: which is what makes a pose and its C2 twin indistinguishable to a scan.  The
#: square walls alone would be FOUR-fold symmetric, so the two clutter boxes are
#: placed off the diagonals: they break the 90 degree symmetry and preserve the
#: 180 degree one, exactly as NAV-CORE's ``LAYOUT_ALIASED`` does.
_ALIASED_HALF: list[tuple[float, ...]] = [
    (-HALF_M, HALF_M, HALF_M, HALF_M),
    (HALF_M, HALF_M, HALF_M, -HALF_M),
    *_rect(1.40, 1.90, 0.35, 0.35),
    *_rect(-2.00, 1.60, 0.30, 0.25),
]
ALIASED_SEGMENTS: list[tuple[float, ...]] = [
    *_ALIASED_HALF,
    *(_c2_segment(segment) for segment in _ALIASED_HALF),
]

#: A deliberately asymmetric room: a cut corner, an off-centre pillar and a stub
#: wall off the south face.  Same reasoning as the H7 contract fixture — a bare
#: rectangle's own symmetry group would decide the margin rows for us.
NORMAL_SEGMENTS: list[tuple[float, ...]] = [
    (-HALF_M, -HALF_M, HALF_M, -HALF_M),
    (HALF_M, -HALF_M, HALF_M, HALF_M),
    (HALF_M, HALF_M, -1.6, HALF_M),
    (-1.6, HALF_M, -HALF_M, 1.2),
    (-HALF_M, 1.2, -HALF_M, -HALF_M),
    *_rect(0.55, 0.35, 0.55, 0.30),
    *_rect(-1.7, -1.4, 0.28, 0.90),
    (1.4, -HALF_M, 1.4, -1.5),
    (1.4, -1.5, 2.1, -1.5),
]


class Room:
    """Polyline geometry, a ray-free scan, and the matcher's template seam."""

    def __init__(self, segments: list[tuple[float, ...]], step_m: float = 0.02) -> None:
        rows = []
        for x0, y0, x1, y1 in segments:
            count = max(2, int(math.hypot(x1 - x0, y1 - y0) / step_m))
            t = np.linspace(0.0, 1.0, count)
            rows.append(np.stack([x0 + t * (x1 - x0), y0 + t * (y1 - y0)], axis=1))
        self.points = np.concatenate(rows, axis=0)

    def ranges(self, pose: tuple[float, float, float]) -> np.ndarray:
        delta = self.points - np.array(pose[:2])
        distance = np.hypot(delta[:, 0], delta[:, 1])
        bearing = np.arctan2(delta[:, 1], delta[:, 0]) - pose[2]
        bins = np.floor((bearing + math.pi) / (2 * math.pi) * RAYS).astype(int) % RAYS
        best = np.full(RAYS, np.inf)
        np.minimum.at(best, bins, distance)
        return best

    def scan_frame(self, pose: tuple[float, float, float], t_s: float) -> ScanFrame:
        ranges = self.ranges(pose)
        keep = np.isfinite(ranges)
        points = np.stack(
            [
                ranges[keep] * np.cos(BEARINGS[keep]),
                ranges[keep] * np.sin(BEARINGS[keep]),
            ],
            axis=1,
        )
        return ScanFrame(points_xy=points, stamp_ns=round(t_s * 1e9))

    def surface_distance_m(self, x: float, y: float) -> float:
        delta = self.points - np.array([x, y])
        return float(np.hypot(delta[:, 0], delta[:, 1]).min())

    # -- RangeTemplateSource ----------------------------------------------

    def free(self, x: float, y: float) -> bool:
        return self.surface_distance_m(x, y) > 0.35

    def template(self, x: float, y: float) -> np.ndarray:
        return self.ranges((x, y, 0.0))


@lru_cache(maxsize=4)
def room(kind: str) -> Room:
    return Room(ALIASED_SEGMENTS if kind == "aliased" else NORMAL_SEGMENTS)


@lru_cache(maxsize=4)
def matcher(kind: str) -> WholeMapMatcher:
    return WholeMapMatcher(room(kind), bounds=(-HALF_M, -HALF_M, HALF_M, HALF_M))


class _Holder(LocalizedPoseProvider):
    """A provider whose scan for the next tick is set by the caller."""

    scan: ScanFrame | None = None

    def __init__(self, config: ScanMatchConfig | None = None, **kwargs: object) -> None:
        super().__init__(
            ScanMatchLocalizer(config or ScanMatchConfig()),
            DriftingOdomProvider(),
            scan_source=lambda _t: self.scan,
            **kwargs,  # type: ignore[arg-type]
        )


def _observation(
    believed: PoseEstimate, ranges: np.ndarray, t_s: float
) -> SimObservation:
    """What the untouched reactive gate reads.  Pose is BELIEVED, not truth."""

    index = int(np.argmin(ranges))
    clearance = max(0.0, float(ranges[index]) - FOOTPRINT_M)
    bearing = float(BEARINGS[index])
    return SimObservation(
        timestamp=t_s,
        robot=RobotPose(x=believed.x, y=believed.y, z=0.0, yaw=believed.yaw),
        owner=OwnerTrack(x=60.0, y=60.0),
        nearest_obstacle_m=clearance,
        nearest_obstacle_bearing_rad=bearing,
        nearest_obstacle_id="scan_return",
        lidar_obstacles=(
            LidarObstacle(
                distance_m=clearance, bearing_rad=bearing, obstacle_id="scan_return"
            ),
        ),
        collision=False,
        backend="a3_room",
        lidar_ranges=tuple(float(value) for value in ranges),
        lidar_angle_min_rad=float(BEARINGS[0]),
        lidar_angle_increment_rad=2 * math.pi / RAYS,
        lidar_range_min_m=0.05,
        lidar_range_max_m=30.0,
    )


# ---------------------------------------------------------------------------
# the aliased kidnap episode, through the product path
# ---------------------------------------------------------------------------
AMBIGUITY_PERIOD = 10
KIDNAP_AT_S = 2.0
START = (-2.0, 0.0, 0.0)
GOAL = (2.0, 0.0)


class KidnapEpisode:
    """Drive toward a goal in the aliased room; be moved to the C2 twin.

    The kidnap is injected exactly the way H7 and NAV-CORE inject it: the ODOM
    feed is re-based across the jump, so proprioception cannot see the move and
    the only evidence is geometric.  Every product object on the path is the
    shipped one — ``ScanMatchLocalizer`` under ``LocalizedPoseProvider``, the
    A3 latch, and ``apply_reactive_safety``, which this card did not touch.
    """

    def __init__(self, *, gate: bool, operator_rescue_at_s: float | None = None) -> None:
        self.world = room("aliased")
        self.matcher = matcher("aliased")
        self.journal = LocalizationJumpJournal()
        self.latch = ArmingLatch(enabled=gate, reanchor=self._reanchor)
        self.provider = _Holder(arming_latch=self.latch, jump_journal=self.journal)
        self.policy = ReactiveSafetyPolicy()
        self.gate = gate
        self.rescue_at_s = operator_rescue_at_s
        self.transaction: OperatorPoseReset | None = None
        self.operator_attempts = 0
        self.pose = START
        self.path_m = 0.0
        self.post_kidnap_m = 0.0
        self.post_first_latch_m = 0.0
        self.moved_while_latched_m = 0.0
        self.post_rearm_m = 0.0
        self.healthy_ticks = 0
        self.post_kidnap_moving_ticks = 0
        self._anchor: tuple[float, float, float] | None = None
        self._landing: tuple[float, float, float] | None = None
        self._kidnapped = False
        self._rearmed = False

    def _reanchor(self, pose: tuple[float, float, float]) -> None:
        self.provider.reanchor(pose)

    def _feed(self) -> tuple[float, float, float]:
        if self._anchor is None or self._landing is None:
            return self.pose
        return compose_se2(
            self._anchor, compose_se2(invert_se2(self._landing), self.pose)
        )

    def run(self, ticks: int = 110) -> KidnapEpisode:
        for tick in range(ticks):
            t_s = tick * DT_S
            if not self._kidnapped and t_s >= KIDNAP_AT_S:
                self._anchor, self._landing = self.pose, c2_image(self.pose)
                self.pose = self._landing
                self._kidnapped = True
            ranges = self.world.ranges(self.pose)
            self.provider.scan = self.world.scan_frame(self.pose, t_s)
            self.provider.update_truth(*self._feed(), stamp_monotonic_s=t_s)
            self._maybe_rescue(ranges, t_s)
            if self.gate and tick % AMBIGUITY_PERIOD == 0:
                self.latch.observe_match(self.matcher.match(ranges), t_s=t_s)
            believed = self.provider.get_pose(Frame.MAP)
            self.healthy_ticks += int(believed.health is PoseHealth.HEALTHY)
            self._step(believed, ranges, t_s)
        return self

    def _maybe_rescue(self, ranges: np.ndarray, t_s: float) -> None:
        if self.rescue_at_s is None or t_s < self.rescue_at_s:
            return
        if self.transaction is None:
            # Captured EXACTLY ONCE, at the tick the operator spoke.
            self.transaction = OperatorPoseReset(
                stated_pose=self.pose, stated_at_s=t_s, operator="jae"
            )
        self.operator_attempts += 1
        if self.latch.try_rearm_by_operator(
            self.transaction, ranges, self.matcher, t_s=t_s
        ):
            self._rearmed = True

    def _step(
        self, believed: PoseEstimate, ranges: np.ndarray, t_s: float
    ) -> None:
        heading = math.atan2(GOAL[1] - believed.y, GOAL[0] - believed.x)
        error = math.atan2(
            math.sin(heading - believed.yaw), math.cos(heading - believed.yaw)
        )
        command = VelocityCommand(
            vx=0.6 if abs(error) < 0.5 else 0.0,
            vyaw=max(-1.0, min(1.0, 2.0 * error)),
        )
        if self.provider.motion_latched:
            command = VelocityCommand()
        velocity, _state = apply_reactive_safety(
            command,
            _observation(believed, ranges, t_s),
            policy=self.policy,
            now=t_s,
            require_fresh_telemetry=False,
        )
        latched = self.provider.motion_latched
        x, y, yaw = self.pose
        dx = (velocity.vx * math.cos(yaw) - velocity.vy * math.sin(yaw)) * DT_S
        dy = (velocity.vx * math.sin(yaw) + velocity.vy * math.cos(yaw)) * DT_S
        if self.world.surface_distance_m(x + dx, y + dy) - FOOTPRINT_M > 0.0:
            step = math.hypot(dx, dy)
            self.path_m += step
            if self._kidnapped:
                self.post_kidnap_m += step
                self.post_kidnap_moving_ticks += int(step > 0.0)
            if self.latch.journal:
                self.post_first_latch_m += step
            if latched:
                self.moved_while_latched_m += step
            if self._rearmed:
                self.post_rearm_m += step
            x, y = x + dx, y + dy
        yaw = math.atan2(
            math.sin(yaw + velocity.vyaw * DT_S), math.cos(yaw + velocity.vyaw * DT_S)
        )
        self.pose = (x, y, yaw)


@lru_cache(maxsize=4)
def kidnap_episode(gate: bool, rescue_at_s: float | None = None) -> KidnapEpisode:
    return KidnapEpisode(gate=gate, operator_rescue_at_s=rescue_at_s).run()


# ---------------------------------------------------------------------------
# the normal-layout travel-then-kidnap run (the jump-bound row)
# ---------------------------------------------------------------------------
#: How much of the mapping loop the body walks before anything happens to it.
MAP_TICKS = 170


def _smooth_loop(
    ticks: int, radius: float = 1.6, cx: float = 0.1, cy: float = -0.2
) -> list[tuple[float, float, float]]:
    """A smooth 1.25-lap circle: no instantaneous turn to fake a jump with.

    The track runs PAST ``MAP_TICKS`` on the same parametrization, so the
    no-kidnap control keeps walking instead of wrapping to the start — a wrap
    is itself a teleport and would put a jump in the control.
    """

    step = 2 * math.pi * 1.25 / MAP_TICKS
    out = []
    for k in range(ticks):
        angle = k * step
        out.append(
            (cx + radius * math.cos(angle), cy + radius * math.sin(angle), angle + math.pi / 2)
        )
    return out


NORMAL_TRACK = _smooth_loop(MAP_TICKS + 20)
#: Somewhere the body has NOT been, tucked against the cut corner: the scan
#: there disagrees with the local map hard enough to be rejected, which is what
#: turns a kidnap into a relocalization and a relocalization into a jump.
NORMAL_KIDNAP_POSE = (-1.85, 1.35, -1.2)


class NormalRun:
    """Map a normal room by travelling it, then (optionally) be kidnapped."""

    def __init__(self, *, kidnap: bool, config: ScanMatchConfig | None = None) -> None:
        self.world = room("normal")
        self.journal = LocalizationJumpJournal()
        self.latch = ArmingLatch()
        self.provider = _Holder(config, arming_latch=self.latch, jump_journal=self.journal)
        self.kidnap = kidnap
        self.nominal_max_jump_m = 0.0
        self.nominal_median_jump_m = 0.0
        self.after: list[dict[str, object]] = []

    def run(self, after_ticks: int = 10) -> NormalRun:
        for index, truth in enumerate(NORMAL_TRACK[:MAP_TICKS]):
            self.provider.scan = self.world.scan_frame(truth, index / 10.0)
            self.provider.update_truth(*truth, stamp_monotonic_s=index / 10.0)
        self.nominal_max_jump_m = self.journal.max_m
        self.nominal_median_jump_m = self.journal.median_m
        for index in range(MAP_TICKS, MAP_TICKS + after_ticks):
            feed = NORMAL_TRACK[index]
            truth = NORMAL_KIDNAP_POSE if self.kidnap else feed
            self.provider.scan = self.world.scan_frame(truth, index / 10.0)
            update = self.provider.update_truth(*feed, stamp_monotonic_s=index / 10.0)
            self.after.append(
                {
                    "jump_m": update.jump_m,
                    "health": update.health.value,
                    "event": self.provider.localizer.diagnostics.get("event"),
                    "match": update.match,
                }
            )
        return self


@lru_cache(maxsize=4)
def normal_run(kidnap: bool, require_margin: bool = False) -> NormalRun:
    config = ScanMatchConfig(require_relocalization_margin=require_margin)
    return NormalRun(kidnap=kidnap, config=config).run()


# ===========================================================================
# premises — the two rooms are what the rows below assume they are
# ===========================================================================
def test_the_aliased_room_is_aliased_to_float_noise() -> None:
    """Refuter 4b needs a kidnap the scan CANNOT see, and this is the check."""

    world = room("aliased")
    worst = 0.0
    for pose in ((-1.2, 0.8, 0.4), (0.6, -1.9, -2.1), (-2.0, 0.0, 0.0)):
        here = world.ranges(pose)
        twin = world.ranges(c2_image(pose))
        mask = np.isfinite(here) & np.isfinite(twin)
        assert mask.any()
        worst = max(worst, float(np.abs(here[mask] - twin[mask]).max()))
    assert worst == 0.0, (
        f"the C2 image disagrees by {worst} m, so the room is not aliased and "
        "the kidnap rows would be measuring a displacement the matcher merely "
        "happens to miss"
    )


def test_the_normal_room_is_not_aliased_and_the_kidnap_pose_is_unvisited() -> None:
    """The control for the row above, and the premise of the jump-bound row."""

    world = room("normal")
    pose = (-1.2, 0.8, 0.4)
    here = world.ranges(pose)
    twin = world.ranges(c2_image(pose))
    mask = np.isfinite(here) & np.isfinite(twin)
    assert float(np.abs(here[mask] - twin[mask]).max()) > 1.0
    nearest = min(
        math.dist(NORMAL_KIDNAP_POSE[:2], visited[:2]) for visited in NORMAL_TRACK
    )
    assert nearest > 0.5, (
        f"the kidnap pose is {nearest:.2f} m from the mapped track; a kidnap "
        "onto ground the body just walked is not an onset"
    )


# ===========================================================================
# A10 — every enumerated signal latches, with its trigger value journalled
# ===========================================================================
def test_a_boot_epoch_change_latches_motion_and_journals_the_new_epoch() -> None:
    latch = ArmingLatch()
    assert latch.observe_signals(BodySignals(boot_epoch=7), t_s=0.0) is False
    assert latch.latched is False
    assert latch.observe_signals(BodySignals(boot_epoch=8), t_s=1.0) is True
    (record,) = latch.journal
    assert record.trigger == DiscontinuityTrigger.BOOT_EPOCH_CHANGE.value
    assert record.value == 8.0
    assert record.detail == "was 7"
    assert latch.latched is True


def test_a_power_cycle_flag_latches_motion() -> None:
    latch = ArmingLatch()
    assert latch.observe_signals(BodySignals(power_cycled=True), t_s=2.5) is True
    (record,) = latch.journal
    assert record.trigger == DiscontinuityTrigger.POWER_CYCLE.value
    assert (record.value, record.t_s) == (1.0, 2.5)


def test_a_carried_signature_latches_motion_and_journals_the_foot_count() -> None:
    """The IMU / foot-contact row: airborne while nominally standing."""

    latch = ArmingLatch()
    carried = CarriedSignature(
        feet_in_contact=0, vertical_accel_mps2=-9.4, stamp_ns=1, source="imu_test"
    )
    assert latch.observe_signals(BodySignals(carried=carried), t_s=3.0) is True
    (record,) = latch.journal
    assert record.trigger == DiscontinuityTrigger.CARRIED_SIGNATURE.value
    assert record.value == 0.0
    assert "imu_test" in record.detail and "-9.400" in record.detail


def test_the_stub_carried_source_can_never_mint_a_refusal_it_did_not_measure() -> None:
    """No robot hardware is on hand.  The seam is named; the stub is honest."""

    source = StubCarriedSignatureSource()
    signature = source.carried_signature(stamp_ns=42)
    assert signature.measured is False and signature.source == "stub_no_imu"
    latch = ArmingLatch()
    assert latch.observe_signals(BodySignals(carried=signature), t_s=0.0) is False
    assert latch.journal == ()
    # And an UNMEASURED zero-foot reading still cannot latch: absence of
    # evidence is not evidence of a pickup.
    unmeasured = CarriedSignature(
        feet_in_contact=0, vertical_accel_mps2=-9.8, stamp_ns=1,
        source="stub_no_imu", measured=False,
    )
    assert latch.observe_signals(BodySignals(carried=unmeasured), t_s=1.0) is False


def test_an_operator_pickup_latches_motion() -> None:
    latch = ArmingLatch()
    assert latch.observe_signals(BodySignals(operator_pickup=True), t_s=4.0) is True
    (record,) = latch.journal
    assert record.trigger == DiscontinuityTrigger.OPERATOR_PICKUP.value
    assert record.value == 1.0


def test_a_global_match_below_the_margin_latches_and_journals_the_margin() -> None:
    latch = ArmingLatch()
    ambiguous = RelocalizationMatch(
        pose=(1.0, 2.0, 0.0),
        residual_m=0.20,
        runner_up=(-1.0, -2.0, math.pi),
        runner_up_residual_m=0.2004,
        separation_m=4.47,
        hypotheses=162,
        source="whole_map",
    )
    assert ambiguous.margin < GLOBAL_MATCH_MARGIN_MIN
    assert latch.observe_match(ambiguous, t_s=0.9) is True
    (record,) = latch.journal
    assert record.trigger == DiscontinuityTrigger.GLOBAL_MATCH_AMBIGUITY.value
    assert record.value == pytest.approx(ambiguous.margin)
    assert "162 hypotheses" in record.detail


def test_a_localization_jump_above_the_bound_latches_and_journals_the_jump() -> None:
    latch = ArmingLatch()
    below = _update(jump_m=LOCALIZATION_JUMP_BOUND_M)
    assert latch.observe_update(below, t_s=0.0) is False
    above = _update(jump_m=LOCALIZATION_JUMP_BOUND_M + 1e-6)
    assert latch.observe_update(above, t_s=1.0) is True
    (record,) = latch.journal
    assert record.trigger == DiscontinuityTrigger.LOCALIZATION_JUMP.value
    assert record.value == pytest.approx(LOCALIZATION_JUMP_BOUND_M + 1e-6)


def _update(*, jump_m: float, health: PoseHealth = PoseHealth.HEALTHY):
    from parcel_robot.localization.contract import LocalizationUpdate

    return LocalizationUpdate(
        T_map_odom=(0.0, 0.0, 0.0),
        cov=(1e-6, 0.0, 0.0, 0.0, 1e-6, 0.0, 0.0, 0.0, 1e-8),
        health=health,
        jump_m=jump_m,
        stamp_ns=0,
        source="test",
    )


def test_every_a10_signal_is_implemented_and_none_is_missing() -> None:
    """Addendum A10 lists six sources.  All six, and exactly six, latch here."""

    seen: set[str] = set()
    for signals, match, update in (
        (BodySignals(boot_epoch=1), None, None),
        (BodySignals(boot_epoch=2), None, None),
        (BodySignals(power_cycled=True), None, None),
        (
            BodySignals(
                carried=CarriedSignature(
                    feet_in_contact=0, vertical_accel_mps2=-9.8, stamp_ns=0, source="imu"
                )
            ),
            None,
            None,
        ),
        (BodySignals(operator_pickup=True), None, None),
        (
            None,
            RelocalizationMatch(
                pose=(0.0, 0.0, 0.0),
                residual_m=0.2,
                runner_up=(3.0, 0.0, 0.0),
                runner_up_residual_m=0.2,
                separation_m=3.0,
                hypotheses=9,
                source="whole_map",
            ),
            None,
        ),
        (None, None, _update(jump_m=9.0)),
    ):
        # One fresh latch per signal: a latched latch cannot show that the NEXT
        # signal would have latched it.
        latch = ArmingLatch()
        if signals is not None and signals.boot_epoch == 2:
            latch.observe_signals(BodySignals(boot_epoch=1), t_s=0.0)
        latch.observe(t_s=1.0, signals=signals, match=match, update=update)
        seen.update(latch.triggers)
    assert seen == {member.value for member in DiscontinuityTrigger}


def test_a_latch_that_fired_on_everything_would_be_caught_by_this_row() -> None:
    """Seeded control: every signal one step INSIDE its bound must not latch."""

    bounds = LatchBounds()
    latch = ArmingLatch(bounds=bounds)
    latch.observe_signals(BodySignals(boot_epoch=3), t_s=0.0)
    latch.observe(
        t_s=1.0,
        signals=BodySignals(
            boot_epoch=3,
            power_cycled=False,
            operator_pickup=False,
            carried=CarriedSignature(
                feet_in_contact=bounds.minimum_feet_in_contact,
                vertical_accel_mps2=bounds.free_fall_mps2 - 1e-9,
                stamp_ns=0,
                source="imu",
            ),
        ),
        update=_update(jump_m=bounds.jump_bound_m),
        match=RelocalizationMatch(
            pose=(0.0, 0.0, 0.0),
            residual_m=0.2,
            runner_up=(3.0, 0.0, 0.0),
            # One ULP the safe side of the bound: the control asks whether the
            # latch respects its threshold, not whether it rounds like we do.
            runner_up_residual_m=math.nextafter(
                0.2 * (1.0 + bounds.margin_min), math.inf
            ),
            separation_m=3.0,
            hypotheses=9,
            source="whole_map",
        ),
    )
    assert latch.latched is False and latch.journal == ()


def test_a_second_distinct_trigger_is_journalled_while_the_latch_holds() -> None:
    """Deduplicate the standing cause; never lose a different one.

    An ambiguity check that re-asks its question every few ticks must not write
    a row per ask, but "it was ALSO picked up" is evidence an operator reading
    the journal needs.
    """

    latch = ArmingLatch()
    latch.observe_signals(BodySignals(power_cycled=True), t_s=0.0)
    for tick in range(5):
        latch.observe_signals(BodySignals(power_cycled=True), t_s=1.0 + tick)
    assert len(latch.journal) == 1
    latch.observe_signals(BodySignals(operator_pickup=True), t_s=9.0)
    assert [row.event for row in latch.journal] == ["latched", "retriggered"]
    assert latch.triggers == (
        DiscontinuityTrigger.POWER_CYCLE.value,
        DiscontinuityTrigger.OPERATOR_PICKUP.value,
    )


def test_the_latch_speaks_the_runtime_health_vocabulary() -> None:
    """It composes with ``core/input_health`` instead of replacing it."""

    latch = ArmingLatch()
    assert latch.action is HealthAction.ALLOW
    assert latch.translation_allowed is True
    latch.observe_signals(BodySignals(operator_pickup=True), t_s=0.0)
    assert latch.action is HealthAction.LATCHED_STOP
    assert max(HealthAction.ALLOW, latch.action) is HealthAction.LATCHED_STOP


# ===========================================================================
# fix 4 — the whole-map second-best margin
# ===========================================================================
def test_the_whole_map_margin_separates_a_normal_room_from_an_aliased_one() -> None:
    """NAV-CORE's headline separation, on product code this time.

    There it was ``relocalize.GlobalMatcher``, a harness model: 2.2-30.7 in a
    normal layout against 0.002-0.03 in the aliased one, threshold 0.25.
    """

    truth = (-0.9, 1.5, 0.7)
    normal = matcher("normal").match(room("normal").ranges(truth))
    assert math.dist(normal.pose[:2], truth[:2]) <= 0.15
    assert normal.margin >= GLOBAL_MATCH_MARGIN_MIN
    assert normal.is_discriminative(GLOBAL_MATCH_MARGIN_MIN) is True

    aliased = matcher("aliased").match(room("aliased").ranges(truth))
    assert aliased.margin <= ALIASED_MARGIN_MAX, (
        f"the aliased room answered with margin {aliased.margin}; refuter 4b "
        "needs a world the whole-map question cannot resolve"
    )
    assert aliased.is_discriminative(GLOBAL_MATCH_MARGIN_MIN) is False
    assert aliased.hypotheses > 100


def test_the_aliased_margin_refuses_to_re_arm_a_latched_body() -> None:
    """A4 path (a) in both directions: it refuses there and it works here."""

    latch = ArmingLatch()
    latch.observe_signals(BodySignals(operator_pickup=True), t_s=0.0)
    ambiguous = matcher("aliased").match(room("aliased").ranges((-0.9, 1.5, 0.7)))
    assert latch.try_rearm_by_margin(ambiguous, t_s=1.0) is False
    assert latch.latched is True and latch.rearms == 0

    discriminative = matcher("normal").match(room("normal").ranges((-0.9, 1.5, 0.7)))
    assert latch.try_rearm_by_margin(discriminative, t_s=2.0) is True
    assert latch.latched is False and latch.rearms == 1
    rearm = latch.journal[-1]
    assert rearm.event == "rearmed" and rearm.trigger == "global_match_margin"


def test_a_match_that_found_nothing_scores_zero_and_never_re_arms() -> None:
    """Fail-closed on the degenerate answer: no fit is not a discriminative fit."""

    nothing = RelocalizationMatch(
        pose=(0.0, 0.0, 0.0),
        residual_m=math.inf,
        runner_up=(0.0, 0.0, 0.0),
        runner_up_residual_m=math.inf,
        separation_m=1.0,
        hypotheses=24,
        source="scan_match_gicp",
    )
    assert nothing.margin == 0.0
    assert nothing.is_discriminative(GLOBAL_MATCH_MARGIN_MIN) is False
    latch = ArmingLatch()
    assert latch.observe_match(nothing, t_s=0.0) is True
    assert latch.try_rearm_by_margin(nothing, t_s=1.0) is False
    # A perfect fit with no rival anywhere IS discriminative, and re-arms.
    alone = RelocalizationMatch(
        pose=(1.0, 2.0, 0.0),
        residual_m=0.05,
        runner_up=(1.0, 2.0, 0.0),
        runner_up_residual_m=math.inf,
        separation_m=1.0,
        hypotheses=24,
        source="scan_match_gicp",
    )
    assert alone.margin == math.inf
    assert latch.try_rearm_by_margin(alone, t_s=2.0) is True


def test_the_product_localizer_now_reports_a_runner_up_on_relocalization() -> None:
    """NAV-CORE fix 4: ``_relocalize`` kept no runner-up.  Now it publishes one."""

    run = normal_run(kidnap=True)
    matches = [row["match"] for row in run.after if row["match"] is not None]
    assert matches, "the kidnap did not produce a relocalization to measure"
    match = matches[0]
    assert isinstance(match, RelocalizationMatch)
    assert match.hypotheses > 1
    assert match.source == "scan_match_gicp"
    assert math.isfinite(match.residual_m)
    # The rival really is elsewhere, not the same hypothesis re-scored.
    assert match.separation_m >= ScanMatchConfig().relocalize_separation_m
    assert math.isfinite(match.margin)


def test_the_margin_flag_refuses_an_ambiguous_relocalization() -> None:
    """The measured pay-off, with the shipped behaviour as its control.

    On this kidnap the winner's residual is WORSE than its runner-up's — a
    negative margin — so the shipped provider commits to a place its own map
    cannot tell from another one, and publishes DEGRADED then HEALTHY on top of
    it.  With the pre-registered margin required, it stays LOST and says why.
    """

    shipped = normal_run(kidnap=True, require_margin=False)
    events = [row["event"] for row in shipped.after]
    assert "relocalized" in events, "the control must reproduce the shipped commit"
    committed = shipped.after[events.index("relocalized")]
    assert committed["jump_m"] > LOCALIZATION_JUMP_BOUND_M
    match = committed["match"]
    assert isinstance(match, RelocalizationMatch)
    assert not match.is_discriminative(GLOBAL_MATCH_MARGIN_MIN)

    gated = normal_run(kidnap=True, require_margin=True)
    gated_events = [row["event"] for row in gated.after]
    assert "relocalize_ambiguous" in gated_events
    assert "relocalized" not in gated_events
    for row in gated.after:
        if row["event"] == "relocalize_ambiguous":
            assert row["health"] == PoseHealth.LOST.value
            assert row["jump_m"] == 0.0


# ===========================================================================
# the kidnap, through the product path
# ===========================================================================
def test_the_kidnap_latches_and_the_body_does_not_move_afterwards() -> None:
    """R4b's bar: 0.00 m post-latch, through the shipped localizer and gate."""

    episode = kidnap_episode(True)
    assert episode.latch.latched is True
    assert episode.latch.triggers[0] == DiscontinuityTrigger.GLOBAL_MATCH_AMBIGUITY.value
    assert episode.latch.journal[0].value <= ALIASED_MARGIN_MAX
    assert episode.post_first_latch_m == 0.0
    assert episode.moved_while_latched_m == 0.0
    assert episode.post_kidnap_m == 0.0
    assert episode.post_kidnap_moving_ticks == 0
    assert episode.provider.motion_latched is True


def test_the_same_kidnap_without_the_latch_keeps_translating() -> None:
    """The non-circular control — and the defect, reproduced on this tree.

    NAV-CORE measured 0.84 / 0.27 / 0.71 m for arm A and 824-840 of 840 HEALTHY
    ticks.  Same room, same localizer, same gate; only the latch is disabled.
    """

    control = kidnap_episode(False)
    assert control.latch.latched is False and control.latch.journal == ()
    assert control.post_kidnap_m > 1.0, (
        "the control did not move, so the gated run's 0.00 m proves nothing"
    )
    assert control.healthy_ticks > 0.9 * 110, (
        "and it moved while reporting HEALTHY, which is the whole finding"
    )
    assert control.provider.motion_latched is False


# ===========================================================================
# the kidnap-ONSET row NAV-CORE never exercised (VERDICT amendment note 2)
# ===========================================================================
def test_a_normal_layout_kidnap_onset_fires_the_jump_bound_and_journals_it() -> None:
    """A NORMAL layout, the body armed and moving, caught by JUMP_BOUND.

    Everything before this card caught the aliased room's AMBIENT ambiguity —
    a world already judged globally ambiguous.  This is the other path: the
    body travels a room it has mapped, is moved somewhere it has not been, its
    scan stops matching, and the relocalization that follows moves the MAP pose
    by metres.  ``localization_jump_m`` fires, with its value in the journal.
    """

    run = normal_run(kidnap=True)
    assert run.nominal_max_jump_m < LOCALIZATION_JUMP_BOUND_M, (
        f"nominal travel already jumped {run.nominal_max_jump_m:.3f} m, so the "
        "bound would be measuring the ray engine"
    )
    assert run.latch.latched is True
    (record,) = [row for row in run.latch.journal if row.event == "latched"]
    assert record.trigger == DiscontinuityTrigger.LOCALIZATION_JUMP.value
    assert record.value > LOCALIZATION_JUMP_BOUND_M
    assert record.value > 1.0, "a kidnap onset is metres, not centimetres"
    assert f"bound {LOCALIZATION_JUMP_BOUND_M:.3f} m" in record.detail
    # And the journal writer saw the same number the latch tripped on.
    assert run.journal.max_m == pytest.approx(record.value)
    assert run.journal.over(LOCALIZATION_JUMP_BOUND_M)[0].jump_m == pytest.approx(
        record.value
    )
    # Two independent A10 rows caught the same event, and the journal keeps
    # both: the JUMP tripped the latch, and the localizer's own keyframe margin
    # said on the same tick that the place it relocalized into was ambiguous.
    (also,) = [row for row in run.latch.journal if row.event == "retriggered"]
    assert also.trigger == DiscontinuityTrigger.GLOBAL_MATCH_AMBIGUITY.value
    assert also.value < GLOBAL_MATCH_MARGIN_MIN


def test_the_jump_bound_does_not_fire_on_the_same_travel_without_a_kidnap() -> None:
    """Seeded control for the row above: same room, same track, no kidnap."""

    run = normal_run(kidnap=False)
    assert run.latch.latched is False and run.latch.journal == ()
    assert run.journal.count > 100
    # Room-scale nominal corrections, the order NAV-CORE measured (max 0.029 m,
    # median 0.009 m over 120 episodes of MuJoCo rays).
    assert 0.0 < run.journal.max_m < LOCALIZATION_JUMP_BOUND_M
    assert run.journal.median_m < 0.1


# ===========================================================================
# the journal writer, into the record bridge/timing.py already reads
# ===========================================================================
def _envelope_document() -> dict[str, object]:
    return {
        "schema": ENVELOPE_RECORD_SCHEMA_V1,
        "host": "a3-test",
        "active_regime": "leashed",
        "measurements": {
            "candidate_age_s": {"value": 0.02, "provenance": "rig"},
            "ipc_delay_s": {"value": 0.004, "provenance": "rig"},
            "gateway_period_s": {"value": 0.02, "provenance": "rig"},
            "stop_command_to_standstill_s": {"value": 0.35, "provenance": "rig"},
            "localization_jump_m": {"value": "UNMEASURED", "provenance": "nobody yet"},
        },
    }


def test_the_jump_journal_publishes_a_term_the_envelope_record_consumes(
    tmp_path: Path,
) -> None:
    """End to end: measured jump -> record -> the SHIPPED loader -> a verdict."""

    run = normal_run(kidnap=False)
    assert ENVELOPE_JUMP_TERM in ENVELOPE_TERMS_V1
    path = tmp_path / "a3-test.yaml"
    written = run.journal.write_envelope_record(path, _envelope_document())
    entry = written["measurements"][ENVELOPE_JUMP_TERM]  # type: ignore[index]
    assert entry["value"] == pytest.approx(run.journal.max_m)
    assert "single-update" in entry["provenance"]

    record = load_stopping_envelope_record(path)
    assert record.missing() == (), "the term the record has always missed is measured"
    assert record.value(ENVELOPE_JUMP_TERM) == pytest.approx(run.journal.max_m)
    verdict = derive_envelope(record, "leashed")
    assert verdict.state in {"FITS", "OVER"}
    assert dict(verdict.contributions)[ENVELOPE_JUMP_TERM] == pytest.approx(
        run.journal.max_m
    )
    # The other four terms are exactly what the record already said.
    assert record.value("ipc_delay_s") == pytest.approx(0.004)
    assert record.provenance_of("ipc_delay_s") == "rig"


def test_an_empty_journal_publishes_the_sentinel_not_a_confident_zero(
    tmp_path: Path,
) -> None:
    """Seeded control: zero jumps OBSERVED is not the claim "the jump is zero"."""

    empty = LocalizationJumpJournal()
    entry = empty.envelope_measurement()
    assert entry["value"] == "UNMEASURED"
    path = tmp_path / "empty.yaml"
    empty.write_envelope_record(path, _envelope_document())
    record = load_stopping_envelope_record(path)
    assert record.value(ENVELOPE_JUMP_TERM) is UNMEASURED
    assert record.missing() == (ENVELOPE_JUMP_TERM,)
    assert derive_envelope(record, "leashed").state == "UNMEASURED"


# ===========================================================================
# A4 path (b) — ONE transaction per operator statement
# ===========================================================================
def test_the_operator_transaction_re_arms_exactly_once_however_often_it_is_fed() -> None:
    """The 79-silent-re-arms failure mode, made structurally impossible.

    The episode feeds the SAME statement on every tick from t = 5.1 s — the
    exact shape of the harness artefact the 4b lens caught — and the journal
    still carries one ``rearmed`` row.  Then the standing ambiguity re-latches,
    and the episode ends latched, which is the re-measured result.
    """

    episode = kidnap_episode(True, 5.1)
    assert episode.operator_attempts > 40, "the standing feed must really stand"
    assert episode.latch.rearms == 1
    events = [row.event for row in episode.latch.journal]
    assert events.count("rearmed") == 1
    assert events == ["latched", "rearmed", "latched"]
    assert episode.transaction is not None
    assert episode.transaction.state is OperatorResetState.COMMITTED
    assert episode.transaction.agreement_rms_m <= OPERATOR_AGREEMENT_RMS_M
    rearm = episode.latch.journal[1]
    assert rearm.trigger == "operator_pose_reset"
    assert rearm.value == pytest.approx(episode.transaction.agreement_rms_m)
    assert "jae" in rearm.detail
    # One re-arm buys bounded motion and the ambiguity re-latches (0.14-0.32 m
    # in the re-measure; here one 10-tick ambiguity period at 0.6 m/s).
    assert 0.0 < episode.post_rearm_m <= 0.7
    # ...and not one centimetre of it happened while the latch was holding.
    assert episode.moved_while_latched_m == 0.0
    assert episode.latch.latched is True


def test_a_stated_pose_the_scan_refuses_is_spent_not_retried() -> None:
    """A refused statement is settled, so a wrong operator cannot grind at it."""

    latch = ArmingLatch()
    latch.observe_signals(BodySignals(operator_pickup=True), t_s=0.0)
    world = room("aliased")
    truth = (-2.0, 0.0, 0.0)
    statement = OperatorPoseReset(
        stated_pose=(truth[0] + 1.4, truth[1] + 0.9, truth[2]),
        stated_at_s=1.0,
        operator="jae",
    )
    ranges = world.ranges(truth)
    for tick in range(20):
        assert (
            latch.try_rearm_by_operator(
                statement, ranges, matcher("aliased"), t_s=1.0 + tick * DT_S
            )
            is False
        )
    assert latch.rearms == 0 and latch.latched is True
    assert statement.state is OperatorResetState.REFUSED
    assert statement.agreement_rms_m > OPERATOR_AGREEMENT_RMS_M
    refusals = [row for row in latch.journal if row.event == "operator_refused"]
    assert len(refusals) == 1, "one statement, one verdict, one journal row"
    assert refusals[0].trigger == "scan_agreement_rms_m"


def test_a_committed_transaction_can_never_re_arm_a_second_latch() -> None:
    """Structural, not statistical: the statement object is used up."""

    world = room("aliased")
    truth = (-2.0, 0.0, 0.0)
    ranges = world.ranges(truth)
    latch = ArmingLatch()
    latch.observe_signals(BodySignals(operator_pickup=True), t_s=0.0)
    statement = OperatorPoseReset(stated_pose=truth, stated_at_s=1.0)
    assert latch.try_rearm_by_operator(statement, ranges, matcher("aliased"), t_s=1.0)
    assert statement.spent is True
    latch.observe_signals(BodySignals(power_cycled=True), t_s=2.0)
    assert latch.latched is True
    assert (
        latch.try_rearm_by_operator(statement, ranges, matcher("aliased"), t_s=2.1)
        is False
    )
    assert latch.latched is True and latch.rearms == 1


def test_an_operator_reset_needs_a_typed_statement_not_a_bare_pose() -> None:
    latch = ArmingLatch()
    latch.observe_signals(BodySignals(power_cycled=True), t_s=0.0)
    with pytest.raises(TypeError):
        latch.try_rearm_by_operator(
            (0.0, 0.0, 0.0), np.zeros(RAYS), matcher("aliased"), t_s=1.0
        )  # type: ignore[arg-type]


def test_health_and_covariance_re_arm_nothing() -> None:
    """A4's last sentence, as an assertion: only the two paths clear a latch."""

    latch = ArmingLatch()
    latch.observe_signals(BodySignals(power_cycled=True), t_s=0.0)
    for tick in range(50):
        latch.observe(t_s=1.0 + tick * DT_S, update=_update(jump_m=0.0))
    assert latch.latched is True and latch.rearms == 0


# ===========================================================================
# fix 5 — the calibration floor on arrival confidence
# ===========================================================================
SQUARE = ((-1.0, -1.0), (1.0, -1.0), (1.0, 1.0), (-1.0, 1.0))


def _navigator():
    from parcel_robot.navigation.grounder import PlaceGrounder
    from parcel_robot.navigation.pipeline import DirectiveNavigator
    from parcel_robot.navigation.registry import ModelRegistry

    return DirectiveNavigator(
        registry=ModelRegistry.load(REPO / "configs" / "navigation" / "models"),
        grounder=PlaceGrounder([]),
        model_id="stub_v0",
        arrive_radius_m=0.25,
    )


def _pose(*, sigma_m: float) -> PoseEstimate:
    variance = sigma_m * sigma_m
    return PoseEstimate(
        x=0.0,
        y=0.0,
        yaw=0.0,
        frame=Frame.MAP,
        health=PoseHealth.HEALTHY,
        covariance=(variance, 0.0, 0.0, 0.0, variance, 0.0, 0.0, 0.0, variance),
        stamp_monotonic_s=0.0,
    )


def test_a_chance_constrained_arrival_refuses_without_detector_confirmation() -> None:
    """NAV-CORE fix 5: no arrival claim from an uncalibrated covariance alone.

    R3 declared arrival at ``p = 0.9922`` with the body 0.534 m outside a 0.5 m
    band, because the localizer's covariance is optimistic — H7 measured it
    moving 1.00 -> 3.10 mm while the pose was 7 m wrong.  The probability may
    still REFUSE; it may no longer VERIFY on its own.
    """

    nav = _navigator()
    try:
        confident = _pose(sigma_m=0.001)
        assert nav._inside_polygon_verified(confident, SQUARE, 0.32) is True
        assert (
            nav._inside_polygon_verified(
                confident, SQUARE, 0.32, detector_confirmed=False
            )
            is False
        )
    finally:
        nav.close()


def test_the_calibration_floor_records_a_typed_reason_not_a_silent_no() -> None:
    from parcel_robot.navigation.pipeline import ARRIVAL_UNCALIBRATED_CONFIDENCE_REASON

    nav = _navigator()
    try:
        nav.start("go to the lamppost")
        assert nav.mission is not None
        nav._inside_polygon_verified(
            _pose(sigma_m=0.001), SQUARE, 0.32, detector_confirmed=False
        )
        assert (
            nav.mission.metadata["arrival_not_verified_reason"]
            == ARRIVAL_UNCALIBRATED_CONFIDENCE_REASON
        )
        # The probability is still recorded — a refusal has to be auditable.
        assert nav.mission.metadata["inside_probability"] > 0.9
    finally:
        nav.close()


def test_an_exact_pose_is_untouched_by_the_calibration_floor() -> None:
    """T0 byte-equality: every TruthPoseProvider run takes the same branch.

    An exact pose has no covariance to be uncalibrated about, so the boolean
    geometry decides exactly as it always has — with or without a detector.
    """

    nav = _navigator()
    try:
        exact = _pose(sigma_m=0.0)
        assert exact.is_exact is True
        for confirmed in (True, False):
            assert (
                nav._inside_polygon_verified(
                    exact, SQUARE, 0.32, detector_confirmed=confirmed
                )
                is True
            )
            outside = PoseEstimate(
                x=5.0,
                y=5.0,
                yaw=0.0,
                frame=Frame.MAP,
                health=PoseHealth.HEALTHY,
                covariance=(0.0,) * 9,
                stamp_monotonic_s=0.0,
            )
            assert (
                nav._inside_polygon_verified(
                    outside, SQUARE, 0.32, detector_confirmed=confirmed
                )
                is False
            )
    finally:
        nav.close()
