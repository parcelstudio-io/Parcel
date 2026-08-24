"""H7 capability proof — the MAP-role contract, on synthetic scans.

One test module, six cells, no MuJoCo and no eval substrate: the bench in
``research/20260823/localization-delegation-bench/`` owns the measured rows, and
this file owns the *capability* — that the contract composes, refuses, and
recovers — plus one cell that pins the row H7 MISSED, so the miss cannot be
quietly forgotten.  It runs in a few seconds so it can live in a targeted run.

The world here is a synthetic, deliberately asymmetric 10 x 8 m room, sampled at
2 cm and scanned by exact ray-free geometry (nearest sampled point per bearing).
That is not a sensor model and does not pretend to be one: it exists so the
cells below test the *provider*, not MuJoCo.

Skipped wholesale when the optional ``localization`` extra is absent, because
the delegated matcher is the point — a fallback that silently tested nothing
would be worse than a skip.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from parcel_robot.localization.contract import (
    LocalizationUpdate,
    LocalizerProvider,
    ScanFrame,
    compose_se2,
    invert_se2,
)
from parcel_robot.localization.gicp_provider import (
    ScanMatchConfig,
    ScanMatchLocalizer,
    small_gicp_available,
)
from parcel_robot.localization.pose_adapter import LocalizedPoseProvider
from parcel_robot.pose import (
    DriftingOdomProvider,
    Frame,
    PoseEstimate,
    PoseHealth,
    PoseProvider,
    provider_from_config,
)

pytestmark = pytest.mark.skipif(
    not small_gicp_available(),
    reason="the localization extra (small-gicp) is not installed",
)

#: A deliberately ASYMMETRIC room.  The first version of this fixture was a
#: bare 10 x 8 rectangle with one centred island, and a kidnapping to the
#: opposite side of the circuit went undetected — the scan there is the scan
#: here, rotated 180 degrees.  That is a real property of scan matching and it
#: is measured on the real scenes in the bench; here it would only make the
#: capability cells test the fixture's symmetry group.  So: a corner cut, a
#: stub wall off the south face, and an off-centre pillar.
ROOM = (
    (-5.0, -4.0, 5.0, -4.0), (5.0, -4.0, 5.0, 4.0), (5.0, 4.0, -3.0, 4.0),
    (-3.0, 4.0, -5.0, 2.0), (-5.0, 2.0, -5.0, -4.0),
    (-1.0, -1.0, 1.0, -1.0), (1.0, -1.0, 1.0, 1.5),
    (1.0, 1.5, -1.0, 1.5), (-1.0, 1.5, -1.0, -1.0),
    (2.5, -4.0, 2.5, -2.0), (2.5, -2.0, 3.2, -2.0),
    (3.4, 2.0, 4.0, 2.0), (4.0, 2.0, 4.0, 2.6), (4.0, 2.6, 3.4, 2.6),
    (3.4, 2.6, 3.4, 2.0),
)


def _world_points() -> np.ndarray:
    segments = []
    for x0, y0, x1, y1 in ROOM:
        count = max(2, int(math.hypot(x1 - x0, y1 - y0) / 0.02))
        t = np.linspace(0.0, 1.0, count)
        segments.append(np.stack([x0 + t * (x1 - x0), y0 + t * (y1 - y0)], axis=1))
    return np.concatenate(segments, axis=0)


WORLD = _world_points()


def _scan_at(pose: tuple[float, float, float], stamp_s: float, rays: int = 360) -> ScanFrame:
    """Nearest world point per bearing, in the body frame."""

    delta = WORLD - np.array(pose[:2])
    ranges = np.hypot(delta[:, 0], delta[:, 1])
    bearings = np.arctan2(delta[:, 1], delta[:, 0]) - pose[2]
    bins = np.floor((bearings + math.pi) / (2 * math.pi) * rays).astype(int) % rays
    best = np.full(rays, np.inf)
    np.minimum.at(best, bins, ranges)
    keep = np.isfinite(best)
    angles = (-math.pi + (np.arange(rays) + 0.5) * 2 * math.pi / rays)[keep]
    kept = best[keep]
    points = np.stack([kept * np.cos(angles), kept * np.sin(angles)], axis=1)
    return ScanFrame(points_xy=points, stamp_ns=round(stamp_s * 1e9))


def _straight_track(steps: int = 60, step_m: float = 0.1) -> list[tuple[float, float, float]]:
    return [(-3.0 + index * step_m, -2.5, 0.0) for index in range(steps)]


def _walk(provider: LocalizedPoseProvider, track, *, silent_from: int | None = None):
    """Feed a track; return the per-tick (truth, MAP pose) pairs."""

    out = []
    for index, truth in enumerate(track):
        scan = None if silent_from is not None and index >= silent_from else _scan_at(
            truth, index / 10.0
        )
        provider.scan = scan
        provider.update_truth(*truth, stamp_monotonic_s=index / 10.0)
        out.append((truth, provider.get_pose(Frame.MAP)))
    return out


class _Holder(LocalizedPoseProvider):
    """A provider whose scan for the next tick is set by the caller."""

    scan: ScanFrame | None = None

    def __init__(self, localizer, odom, **kwargs):
        super().__init__(localizer, odom, scan_source=lambda _t: self.scan, **kwargs)


def _provider(**config) -> _Holder:
    return _Holder(ScanMatchLocalizer(ScanMatchConfig(**config)), DriftingOdomProvider())


def test_the_types_satisfy_both_protocols() -> None:
    """The localizer IS a LocalizerProvider and the adapter IS a PoseProvider."""

    provider = _provider()
    assert isinstance(provider.localizer, LocalizerProvider)
    assert isinstance(provider, PoseProvider)
    assert isinstance(provider.get_pose(Frame.MAP), PoseEstimate)
    # And the shipped seam feeds it without knowing what it is.
    from parcel_robot.pose import observation_pose

    class _Observation:
        def __init__(self) -> None:
            self.position = (1.0, 2.0, 0.27)
            self.heading_deg = 0.0
            self.extras = {"pose_provider": provider, "time_s": 0.0}

    assert observation_pose(_Observation(), Frame.MAP).frame is Frame.MAP


def test_map_pose_is_t_map_odom_composed_with_odom() -> None:
    """REP-105, arithmetically: the adapter composes, it does not re-estimate."""

    provider = _provider()
    walked = _walk(provider, _straight_track(30))
    odom = provider.get_pose(Frame.ODOM)
    update = provider.last_update
    assert update is not None
    expected = compose_se2(update.T_map_odom, (odom.x, odom.y, odom.yaw))
    map_pose = walked[-1][1]
    assert map_pose.x == pytest.approx(expected[0], abs=1e-9)
    assert map_pose.y == pytest.approx(expected[1], abs=1e-9)
    # And the correction really is a correction: it is not the identity, because
    # the ODOM source has drifted away from truth by now.
    assert math.hypot(*invert_se2(update.T_map_odom)[:2]) > 0.0


def test_the_localizer_holds_the_map_frame_while_odom_drifts() -> None:
    """The capability claim: MAP error stays small while ODOM error grows."""

    provider = _Holder(ScanMatchLocalizer(), provider_from_config(profile="go2_degraded"))
    walked = _walk(provider, _straight_track(60))
    map_errors = [math.hypot(pose.x - truth[0], pose.y - truth[1]) for truth, pose in walked]
    odom = provider.get_pose(Frame.ODOM)
    odom_error = math.hypot(odom.x - walked[-1][0][0], odom.y - walked[-1][0][1])
    assert max(map_errors[5:]) < 0.15
    assert odom_error > max(map_errors[5:])


def test_a_scan_dropout_degrades_then_loses_then_recovers() -> None:
    """The refusal is observable, and it comes back."""

    provider = _provider(degraded_after_s=0.5, lost_after_s=1.5)
    track = _straight_track(60)
    healths = []
    for index, truth in enumerate(track):
        provider.scan = None if 20 <= index < 45 else _scan_at(truth, index / 10.0)
        provider.update_truth(*truth, stamp_monotonic_s=index / 10.0)
        healths.append(provider.get_pose(Frame.MAP).health)
    assert healths[19] is PoseHealth.HEALTHY
    # DEGRADED within 1 s of the last scan, LOST after the longer threshold.
    assert PoseHealth.DEGRADED in healths[20:31]
    assert healths[:20].count(PoseHealth.LOST) == 0
    assert PoseHealth.LOST in healths[20:45]
    # Recovery is earned over more than one frame, never granted on one.
    assert healths[-1] is PoseHealth.HEALTHY
    assert healths[45] is not PoseHealth.HEALTHY


def _rect_track(step_m: float = 0.1) -> list[tuple[float, float, float]]:
    """A closed circuit inside the room — so a kidnapping can land on mapped ground."""

    corners = [(-3.5, -2.8), (3.5, -2.8), (3.5, 2.8), (-3.5, 2.8)]
    poses: list[tuple[float, float, float]] = []
    for index, corner in enumerate(corners):
        following = corners[(index + 1) % len(corners)]
        span = (following[0] - corner[0], following[1] - corner[1])
        count = max(1, round(math.hypot(*span) / step_m))
        yaw = math.atan2(span[1], span[0])
        for k in range(count):
            poses.append((corner[0] + span[0] * k / count, corner[1] + span[1] * k / count, yaw))
    return poses


CIRCUIT = _rect_track()
KIDNAP_AT = 378  # 1.5 laps of mapping before the body is moved


def _kidnap(provider: _Holder, offset: int):
    """Map the circuit, then move the body ``offset`` samples around it.

    Proprioception never sees the move: the ODOM feed keeps walking the circuit
    from where the body was, which is what makes this a kidnapping.
    """

    for index in range(KIDNAP_AT):
        truth = CIRCUIT[index % len(CIRCUIT)]
        provider.scan = _scan_at(truth, index / 10.0)
        provider.update_truth(*truth, stamp_monotonic_s=index / 10.0)
    rows = []
    for index in range(KIDNAP_AT, KIDNAP_AT + 40):
        truth = CIRCUIT[(index + offset) % len(CIRCUIT)]
        feed = CIRCUIT[index % len(CIRCUIT)]
        provider.scan = _scan_at(truth, index / 10.0)
        provider.update_truth(*feed, stamp_monotonic_s=index / 10.0)
        rows.append((truth, provider.get_pose(Frame.MAP)))
    return rows


def test_a_kidnapping_is_NOT_detected_the_H7_finding() -> None:
    """A 9 m kidnapping is accepted as a 0.56 m correction.  This is the finding.

    The body is moved to the opposite side of a mapped circuit and turned 180
    degrees; proprioception does not see it.  What the matcher then reports is
    **not** a large correction it could be gated on: it reports 714 inliers, a
    0.23 m RMS point-to-plane residual and a 0.56 m correction — inside every
    acceptance gate the provider has — and settles into a locally consistent
    basin nine metres from the truth, publishing HEALTHY and a floor-level
    covariance for the rest of the run.

    That is structural, not a threshold that needs raising: a kidnapped scan
    matcher does not travel to the right answer and report the distance, it
    converges to the nearest wrong one.  H7 row L4 measures the same thing on
    the real scenes — missed on the symmetric product scene, caught on the
    asymmetric held-out one (named in the L4 row itself; the held-out scene
    guard is why neither is named here — this file loads NO scene, it builds
    the synthetic ROOM above) — and
    the milestone ADR's conclusion follows from it: a MAP-role contract needs
    global place recognition or an independent jump detector, which no
    scan-matching provider supplies.  See
    ``research/20260823/localization-delegation-bench/RESULTS.md`` row L4.

    This cell asserts the DEFECT.  When a provider lands that closes it, this
    is the test that goes red and says so.
    """

    rows = _kidnap(_provider(), len(CIRCUIT) // 2)
    healths = [pose.health for _truth, pose in rows]
    truth, pose = rows[-1]
    error_m = math.hypot(pose.x - truth[0], pose.y - truth[1])
    assert PoseHealth.LOST not in healths, "if this now fires, the finding is FIXED"
    assert error_m > 1.0, "and the silent acceptance leaves the MAP pose metres wrong"
    assert pose.position_sigma_m < 0.1, "while the published covariance says it is sure"


def test_the_jump_term_is_published_and_is_a_body_displacement() -> None:
    """``localization_jump_m`` exists, is finite, and is measured at the body."""

    provider = _provider()
    jumps = []
    for index, truth in enumerate(_straight_track(40)):
        provider.scan = _scan_at(truth, index / 10.0)
        update = provider.update_truth(*truth, stamp_monotonic_s=index / 10.0)
        assert isinstance(update, LocalizationUpdate)
        jumps.append(update.jump_m)
    assert all(math.isfinite(value) and value >= 0.0 for value in jumps)
    assert provider.max_jump_m == pytest.approx(max(jumps))
    # Nominal tracking produces small corrections; the term is not a constant 0
    # (which would make it un-evidence) and not unbounded.
    assert 0.0 < max(jumps) < 0.5
