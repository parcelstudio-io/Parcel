"""Scan-to-map matching delegated to ``small-gicp``, behind the MAP contract.

**Why not ``kiss-icp``, which the H7 design named.**  Measured 2026-08-23 in
this repo's venv (CPython 3.14.4): ``pip install kiss-icp`` finds only the
1.3.0 sdist (no cp314 wheel) and its build fails before compiling at all —
``ERROR: Use cmake.version instead of cmake.minimum-version with
scikit-build-core >= 0.8``.  ``open3d``, the design's first fallback, publishes
no cp314 wheel either ("from versions: none").  ``small-gicp`` 1.0.1 does, and
it is the same *class* of thing KISS-ICP is: a C++ registration library
(voxel downsampling, KdTree correspondences, point-to-plane / GICP / VGICP) with
no ROS, no PCL and no torch.  Delegating to it keeps the hypothesis intact —
Parcel does not own a filter — while being honest that the pinned reference
implementation could not be installed.  The design's other fallback, "an ICP in
numpy", was not taken: writing our own matcher is exactly what the delegation
hypothesis is about not doing.

**The algorithm, in one paragraph.**  Every scan is lifted from the planar ring
into three z layers (a planar ring has no out-of-plane structure, so a 6-DoF
matcher sees a rank-deficient problem; three layers give the vertical extent a
real LiDAR ring would have and make surface normals well-defined), downsampled,
and registered against a local map assembled from the last N keyframe clouds in
the MAP frame.  The initial guess is the *odometry* prediction — the previous
``T_map_odom`` composed with this tick's ODOM pose — which is what makes this a
MAP-role estimator rather than a standalone odometry: the smooth frame supplies
the motion prior, the scan supplies the correction.  A keyframe is inserted
whenever the robot has moved past a translation or rotation threshold.  There
is no loop closure and no pose graph; see the class docstring for what that
costs.

**Covariance is pre-registered, not fitted.**  ``Sigma = sigma_range^2 *
inv(H_planar)`` where ``H_planar`` is the ``(tx, ty, rz)`` sub-block of the
registration Hessian and ``sigma_range`` is the sensor's own range noise.  This
is the classical least-squares scan-match covariance (Censi 2007).  Taking the
sub-block rather than marginalising the full 6x6 is the correct planar
statement: z, roll and pitch are *known* here (the body is on the ground), so
conditioning on them is right and marginalising over them would be wrong.  The
Hessian index order ``[rx, ry, rz, tx, ty, tz]`` was verified empirically on
this build — a corridor with no along-track structure yields exactly
``H[3, 3] == 0`` under ``PLANE_ICP``.
"""

from __future__ import annotations

import importlib.util
import math
from dataclasses import dataclass
from typing import Any

import numpy as np

from parcel_robot.localization.contract import (
    IDENTITY_SE2,
    LocalizationUpdate,
    RelocalizationMatch,
    ScanFrame,
    compose_se2,
    invert_se2,
    wrap_angle,
)
from parcel_robot.pose import PoseHealth

__all__ = ["ScanMatchConfig", "ScanMatchLocalizer", "small_gicp_available"]

#: Hessian sub-block indices for the planar DoFs, in ``(x, y, yaw)`` order.
_PLANAR_INDEX = (3, 4, 2)


def small_gicp_available() -> bool:
    """True when the delegated matcher is importable (it is an optional extra)."""

    return importlib.util.find_spec("small_gicp") is not None


@dataclass(frozen=True)
class ScanMatchConfig:
    """Every knob, with the reason it has the value it has.

    The thresholds below are *stated engineering choices*, not calibrations
    against any H7 criterion: they were fixed before the traverses were run.
    """

    #: Voxel size for both scan and local map.  0.10 m is half the map voxel a
    #: 30 m planar scan needs to stay under ~5k points at this room scale.
    downsample_m: float = 0.10
    #: Correspondence gate.  1.0 m is small-gicp's own default and comfortably
    #: exceeds one 0.1 m control step of odometry prediction error.
    max_correspondence_m: float = 1.0
    max_iterations: int = 20
    #: Single-threaded on purpose: ``voxelgrid_sampling`` is documented as
    #: run-by-run non-deterministic with threads, and the L7 latency row is
    #: meant to be a CPU-core number a robot can budget for.
    num_threads: int = 1
    #: ``PLANE_ICP`` rather than ``ICP``: point-to-point's Hessian translation
    #: block is exactly ``N * I`` regardless of geometry, so it cannot express
    #: the aperture problem and its covariance would be isotropic in a corridor.
    registration_type: str = "PLANE_ICP"
    lift_layers_m: tuple[float, ...] = (-0.10, 0.0, 0.10)
    keyframe_translation_m: float = 1.0
    keyframe_rotation_rad: float = 0.35
    local_map_keyframes: int = 12
    #: Range noise of the scan the provider is fed; the only input to the
    #: covariance scale.  Matches ``mujoco_lidar.DEFAULT_SCAN_NOISE_STD_M``.
    sigma_range_m: float = 0.008
    cov_floor_m2: float = 1e-6
    cov_floor_rad2: float = 1e-8
    min_scan_points: int = 40
    min_inliers: int = 60
    #: RMS point-to-plane residual above which a registration is not believed.
    max_residual_m: float = 0.30
    #: A correction larger than this in one tick is not a correction, it is a
    #: relocalization — the robot is somewhere else than it thought.
    teleport_correction_m: float = 1.00
    degraded_after_s: float = 0.50
    lost_after_s: float = 3.00
    lost_failure_streak: int = 3
    recover_streak: int = 2
    relocalize_candidates: int = 24
    # Card A3, NAV-CORE fix 4: the whole-map second-best margin.
    #: A runner-up whose committed pose is nearer than this to the winner is
    #: the same hypothesis re-scored, not a competitor.  Matches
    #: ``global_match.HYPOTHESIS_SEPARATION_M``.
    relocalize_separation_m: float = 1.00
    #: PRE-REGISTERED re-arm margin (``global_match.GLOBAL_MATCH_MARGIN_MIN``).
    #: NAV-CORE measured 2.2-30.7 in a normal layout against 0.002-0.03 in a
    #: C2-aliased one.
    relocalize_margin_min: float = 0.25
    #: OFF by default, and the default is the shipped behaviour to the digit:
    #: with this False the runner-up is COMPUTED and PUBLISHED but decides
    #: nothing, so installing A3 changes no localizer output.  With it True an
    #: ambiguous relocalization is REFUSED — the provider stays LOST rather
    #: than committing to a place it cannot tell from another one.
    require_relocalization_margin: bool = False

    def __post_init__(self) -> None:
        if self.registration_type not in {"ICP", "PLANE_ICP", "GICP", "VGICP"}:
            raise ValueError(f"unknown registration_type {self.registration_type!r}")
        for name in ("downsample_m", "max_correspondence_m", "sigma_range_m"):
            if float(getattr(self, name)) <= 0.0:
                raise ValueError(f"{name} must be positive")


@dataclass
class _Keyframe:
    pose: tuple[float, float, float]
    cloud: Any


class ScanMatchLocalizer:
    """A ``LocalizerProvider`` that publishes ``T_map_odom`` from LiDAR scans.

    **What it does not have, stated up front.**  No loop closure, no pose
    graph, no place recognition over descriptors, no IMU.  Relocalization after
    a detected teleport is a brute search over stored keyframe poses, so it can
    only recover into territory it has already mapped; a kidnapped robot put
    somewhere new stays LOST, correctly and permanently.  Global consistency is
    therefore only as good as the accumulated keyframe chain — this is a
    scan-matching localizer, and the milestone ADR that picks the on-robot
    provider (FAST-LIO2 / Point-LIO class) is the place where loop closure and
    IMU coupling get decided.
    """

    name = "scan_match_gicp"

    def __init__(self, config: ScanMatchConfig | None = None) -> None:
        self.config = config or ScanMatchConfig()
        self._gicp = self._import_backend()
        self._keyframes: list[_Keyframe] = []
        self._target: Any = None
        self._target_tree: Any = None
        self._T_map_odom: tuple[float, float, float] = IDENTITY_SE2
        self._pose_map_base: tuple[float, float, float] = IDENTITY_SE2
        self._cov: tuple[float, ...] = (0.0,) * 9
        self._health = PoseHealth.LOST
        self._failures = 0
        self._good_streak = 0
        self._last_scan_ns: int | None = None
        self._diagnostics: dict[str, Any] = {}
        self._match: RelocalizationMatch | None = None
        self._match_fresh = False
        self.reset()

    @staticmethod
    def _import_backend() -> Any:
        try:
            import small_gicp
        except ImportError as exc:  # pragma: no cover - environment guard
            raise RuntimeError(
                "the localization extra is not installed: "
                "`.parcel/bin/pip install -e '.[localization]'`"
            ) from exc
        return small_gicp

    # -- lifecycle ---------------------------------------------------------

    def reset(self) -> None:
        """Drop the map and go LOST — the honest state before the first scan."""

        self._keyframes = []
        self._target = None
        self._target_tree = None
        self._T_map_odom = IDENTITY_SE2
        self._pose_map_base = IDENTITY_SE2
        self._cov = (0.0,) * 9
        self._health = PoseHealth.LOST
        self._failures = 0
        self._good_streak = 0
        self._last_scan_ns = None
        self._match = None
        self._match_fresh = False
        self._diagnostics = {"event": "reset"}

    @property
    def diagnostics(self) -> dict[str, Any]:
        """Per-tick evidence the contract does not carry (bench reads this)."""

        return dict(self._diagnostics)

    @property
    def keyframe_count(self) -> int:
        return len(self._keyframes)

    @property
    def last_match(self) -> RelocalizationMatch | None:
        """The most recent relocalization's best/runner-up pair (card A3).

        ``None`` until a relocalization has been attempted: an ordinary
        tracking tick asks no global question, and answering one it did not ask
        would be inventing evidence.
        """

        return self._match

    # -- the contract ------------------------------------------------------

    def update(
        self,
        scan: ScanFrame | None,
        odom_pose: tuple[float, float, float],
        *,
        stamp_ns: int,
    ) -> LocalizationUpdate:
        odom = (float(odom_pose[0]), float(odom_pose[1]), float(odom_pose[2]))
        previous = self._T_map_odom
        if scan is None or scan.count < self.config.min_scan_points:
            self._tick_without_scan(stamp_ns, scan)
        else:
            self._tick_with_scan(scan, odom, stamp_ns)
        # THE JUMP IS MEASURED AT THE BODY, NOT AT THE FRAME ORIGIN.  The naive
        # reading — the translation delta of ``T_map_odom`` itself — is
        # origin-dependent: a pure yaw change in the correction moves that
        # translation by |odom translation| * dtheta, which on this bench read
        # 4.4 m for a correction that displaced the robot by about 1 m.  The
        # quantity a stopping envelope needs is how far the ROBOT's MAP pose
        # moved because the correction changed, so it is evaluated at this
        # tick's ODOM pose with the old and the new correction.
        before = compose_se2(previous, odom)
        after = compose_se2(self._T_map_odom, odom)
        jump = math.hypot(after[0] - before[0], after[1] - before[1])
        self._diagnostics["health"] = self._health.value
        self._diagnostics["t_map_odom_delta_m"] = math.hypot(
            self._T_map_odom[0] - previous[0], self._T_map_odom[1] - previous[1]
        )
        published = self._match if self._match_fresh else None
        self._match_fresh = False
        return LocalizationUpdate(
            T_map_odom=self._T_map_odom,
            cov=self._cov,
            health=self._health,
            jump_m=jump,
            stamp_ns=int(stamp_ns),
            source=self.name,
            match=published,
        )

    # -- the two tick shapes ----------------------------------------------

    def _tick_without_scan(self, stamp_ns: int, scan: ScanFrame | None) -> None:
        """Hold the correction; let staleness alone drive health."""

        reason = "no_scan" if scan is None else "too_few_points"
        if self._last_scan_ns is None:
            self._health = PoseHealth.LOST
            self._diagnostics = {"event": reason, "age_s": None}
            return
        age_s = (int(stamp_ns) - self._last_scan_ns) * 1e-9
        if age_s >= self.config.lost_after_s:
            self._health = PoseHealth.LOST
        elif age_s >= self.config.degraded_after_s:
            self._health = PoseHealth.DEGRADED
        if self._health is not PoseHealth.HEALTHY:
            # Staleness invalidates the tracking streak.  Without this a
            # provider that went LOST under a 10 s dropout came back HEALTHY on
            # the FIRST scan after it, because ``_good_streak`` still held the
            # count from before the dropout — a refusal that un-refuses itself
            # on one frame is not a refusal.
            self._good_streak = 0
        self._diagnostics = {"event": reason, "age_s": age_s}

    def _tick_with_scan(
        self,
        scan: ScanFrame,
        odom: tuple[float, float, float],
        stamp_ns: int,
    ) -> None:
        self._last_scan_ns = int(stamp_ns)
        cloud = self._lift(scan.points_xy)
        if not self._keyframes:
            self._anchor(cloud, odom)
            return
        predicted = compose_se2(self._T_map_odom, odom)
        if self._health is PoseHealth.LOST:
            # Relocalization happens on the tick AFTER the one that published
            # LOST, never on the same tick.  Collapsing the two would mean the
            # consumer never observes the refusal it is supposed to act on: the
            # first bench run published DEGRADED on the tick that detected the
            # kidnapping, and the LOST state was unreachable from outside.
            self._relocalize(cloud, odom, predicted)
            return
        result = self._register(cloud, predicted, self._target, self._target_tree)
        accepted, reason = self._accept(result, predicted)
        if accepted:
            self._commit(result, cloud, odom, reason="tracked")
            return
        self._failures += 1
        self._good_streak = 0
        self._health = (
            PoseHealth.LOST
            if self._failures >= self.config.lost_failure_streak
            else PoseHealth.DEGRADED
        )
        self._diagnostics = {"event": "reject", "reason": reason}

    # -- registration ------------------------------------------------------

    def _register(
        self,
        cloud: Any,
        init: tuple[float, float, float],
        target: Any,
        target_tree: Any,
    ) -> Any:
        source, _ = self._gicp.preprocess_points(
            cloud,
            downsampling_resolution=self.config.downsample_m,
            num_threads=self.config.num_threads,
        )
        return self._gicp.align(
            target,
            source,
            target_tree,
            _matrix(init),
            registration_type=self.config.registration_type,
            max_correspondence_distance=self.config.max_correspondence_m,
            num_threads=self.config.num_threads,
            max_iterations=self.config.max_iterations,
        )

    def _accept(self, result: Any, predicted: tuple[float, float, float]) -> tuple[bool, str]:
        inliers = int(result.num_inliers)
        if inliers < self.config.min_inliers:
            return False, "few_inliers"
        rms = math.sqrt(max(0.0, 2.0 * float(result.error) / inliers))
        if rms > self.config.max_residual_m:
            return False, "residual"
        pose = _se2(np.asarray(result.T_target_source))
        correction = math.hypot(pose[0] - predicted[0], pose[1] - predicted[1])
        if correction > self.config.teleport_correction_m:
            return False, "teleport"
        return True, "ok"

    def _commit(
        self,
        result: Any,
        cloud: Any,
        odom: tuple[float, float, float],
        *,
        reason: str,
    ) -> None:
        pose = _se2(np.asarray(result.T_target_source))
        self._pose_map_base = pose
        self._T_map_odom = compose_se2(pose, invert_se2(odom))
        self._cov = self._covariance(np.asarray(result.H))
        self._failures = 0
        self._good_streak += 1
        if self._good_streak >= self.config.recover_streak:
            self._health = PoseHealth.HEALTHY
        elif self._health is PoseHealth.LOST:
            self._health = PoseHealth.DEGRADED
        self._maybe_keyframe(cloud, pose)
        self._diagnostics = {
            "event": reason,
            "inliers": int(result.num_inliers),
            "iterations": int(result.iterations),
            "rms_m": math.sqrt(max(0.0, 2.0 * float(result.error) / max(1, result.num_inliers))),
        }

    def _relocalize(
        self,
        cloud: Any,
        odom: tuple[float, float, float],
        predicted: tuple[float, float, float],
    ) -> None:
        """Brute search over stored keyframes.  Only mapped ground is findable.

        **Card A3 / NAV-CORE fix 4.**  This used to keep the winner and throw
        every other candidate away, which made A4's re-arm rule uncomputable:
        "a relocalization match whose second-best candidate is worse by a
        pre-registered margin **across the whole map**".  It now keeps the best
        RIVAL as well — the next-best candidate whose committed pose is at
        least ``relocalize_separation_m`` from the winner's, because a
        candidate nearer than that is the same hypothesis re-scored — and
        publishes both as a :class:`RelocalizationMatch` on the tick's update.

        Two honest limits, stated rather than implied.  The hypothesis set is
        the KEYFRAME CHAIN sampled at ``relocalize_candidates``, so "whole map"
        here means "everywhere this map has been", not every pose in the venue;
        a venue-wide grid is what
        :class:`~parcel_robot.localization.global_match.WholeMapMatcher` is for.
        And the winner is still chosen by the shipped ``inliers / (1 + rms)``
        score while the margin is computed from the two residuals, so the
        selection is byte-identical to the pre-A3 provider and only the
        reporting is new.
        """

        scored, candidates = self._score_relocalization_candidates(cloud)
        if not scored:
            self._match = self._empty_match(candidates)
            self._match_fresh = True
            self._diagnostics = {"event": "relocalize_failed", "candidates": candidates}
            return
        _score, best_pose, best_rms, best = max(scored, key=lambda row: row[0])
        match = self._match_from(scored, best_pose, best_rms, candidates)
        self._match = match
        self._match_fresh = True
        if self.config.require_relocalization_margin and not match.is_discriminative(
            self.config.relocalize_margin_min
        ):
            # The map cannot tell this place from another one.  Committing here
            # is exactly the false-healthy the milestone forbids, so the
            # provider stays LOST and says why.
            self._diagnostics = {
                "event": "relocalize_ambiguous",
                "candidates": candidates,
                "margin": match.margin,
                "margin_min": self.config.relocalize_margin_min,
            }
            return
        pose = best_pose
        self._pose_map_base = pose
        self._T_map_odom = compose_se2(pose, invert_se2(odom))
        self._cov = self._covariance(np.asarray(best.H))
        self._failures = 0
        self._good_streak = 1
        self._health = PoseHealth.DEGRADED
        self._maybe_keyframe(cloud, pose)
        self._diagnostics = {
            "event": "relocalized",
            "candidates": candidates,
            "shift_m": math.hypot(pose[0] - predicted[0], pose[1] - predicted[1]),
            "margin": match.margin,
        }

    def _score_relocalization_candidates(
        self, cloud: Any
    ) -> tuple[list[tuple[float, tuple[float, float, float], float, Any]], int]:
        """Register the scan against each sampled keyframe; keep what passed.

        Returns ``(rows, candidates_tried)`` where each row is
        ``(score, pose, rms, result)``.  The acceptance gates and the score are
        the shipped ones, unchanged: A3 keeps every survivor instead of only
        the leader, and changes nothing about who leads.
        """

        stride = max(1, len(self._keyframes) // max(1, self.config.relocalize_candidates))
        candidates = self._keyframes[::stride]
        rows: list[tuple[float, tuple[float, float, float], float, Any]] = []
        for keyframe in candidates:
            target, tree = self._gicp.preprocess_points(
                keyframe.cloud,
                downsampling_resolution=self.config.downsample_m,
                num_threads=self.config.num_threads,
            )
            result = self._register(cloud, keyframe.pose, target, tree)
            inliers = int(result.num_inliers)
            if inliers < self.config.min_inliers:
                continue
            rms = math.sqrt(max(0.0, 2.0 * float(result.error) / inliers))
            if rms > self.config.max_residual_m:
                continue
            rows.append(
                (inliers / (1.0 + rms), _se2(np.asarray(result.T_target_source)), rms, result)
            )
        return rows, len(candidates)

    def _match_from(
        self,
        scored: list[tuple[float, tuple[float, float, float], float, Any]],
        best_pose: tuple[float, float, float],
        best_rms: float,
        candidates: int,
    ) -> RelocalizationMatch:
        """Pair the winner with the best hypothesis that is genuinely elsewhere."""

        rival_score = -1.0
        rival_pose: tuple[float, float, float] | None = None
        rival_rms = math.inf
        for score, pose, rms, _result in scored:
            if math.dist(pose[:2], best_pose[:2]) < self.config.relocalize_separation_m:
                continue
            if score > rival_score:
                rival_score, rival_pose, rival_rms = score, pose, rms
        return RelocalizationMatch(
            pose=best_pose,
            residual_m=best_rms,
            runner_up=best_pose if rival_pose is None else rival_pose,
            runner_up_residual_m=math.inf if rival_pose is None else rival_rms,
            separation_m=(
                self.config.relocalize_separation_m
                if rival_pose is None
                else math.dist(best_pose[:2], rival_pose[:2])
            ),
            hypotheses=candidates,
            source=self.name,
        )

    def _empty_match(self, candidates: int) -> RelocalizationMatch:
        """The match a failed relocalization publishes: nothing fitted at all."""

        return RelocalizationMatch(
            pose=self._pose_map_base,
            residual_m=math.inf,
            runner_up=self._pose_map_base,
            runner_up_residual_m=math.inf,
            separation_m=self.config.relocalize_separation_m,
            hypotheses=max(1, candidates),
            source=self.name,
        )

    def reanchor(
        self,
        pose: tuple[float, float, float],
        odom_pose: tuple[float, float, float],
    ) -> None:
        """Re-bind MAP to a VERIFIED pose without disturbing the ODOM integrator.

        The one operation A4's two re-arm paths need and the provider did not
        expose: a whole-map margin or an operator pose-reset transaction
        establishes where the body actually is, and the correction has to move
        to match it.  ODOM is untouched by construction — only ``T_map_odom``
        moves, which is REP-105's whole point and keeps the jump measurable on
        the next update.

        This is NOT a recovery mechanism and must never be called on the
        strength of health or covariance; the caller has to have earned the
        pose.  ``localization/discontinuity.ArmingLatch`` is the object that
        does, and it journals the evidence before it calls.
        """

        verified = tuple(float(value) for value in pose)
        odom = tuple(float(value) for value in odom_pose)
        if len(verified) != 3 or len(odom) != 3:
            raise ValueError("reanchor takes (x, y, yaw) poses")
        if not all(math.isfinite(value) for value in verified + odom):
            raise ValueError("reanchor poses must be finite")
        self._pose_map_base = verified  # type: ignore[assignment]
        self._T_map_odom = compose_se2(verified, invert_se2(odom))  # type: ignore[arg-type]
        self._diagnostics = {"event": "reanchored", "pose": verified}

    # -- map ---------------------------------------------------------------

    def _anchor(self, cloud: Any, odom: tuple[float, float, float]) -> None:
        """First scan: MAP is defined to coincide with ODOM right here."""

        self._T_map_odom = IDENTITY_SE2
        self._pose_map_base = odom
        self._insert_keyframe(cloud, odom)
        self._cov = self._floor_covariance((0.0,) * 9)
        self._good_streak = 1
        self._health = (
            PoseHealth.HEALTHY if self.config.recover_streak <= 1 else PoseHealth.DEGRADED
        )
        self._diagnostics = {"event": "anchor"}

    def _maybe_keyframe(self, cloud: Any, pose: tuple[float, float, float]) -> None:
        last = self._keyframes[-1].pose
        moved = math.hypot(pose[0] - last[0], pose[1] - last[1])
        turned = abs(wrap_angle(pose[2] - last[2]))
        if moved < self.config.keyframe_translation_m and turned < self.config.keyframe_rotation_rad:
            return
        self._insert_keyframe(cloud, pose)

    def _insert_keyframe(self, cloud: Any, pose: tuple[float, float, float]) -> None:
        self._keyframes.append(_Keyframe(pose=pose, cloud=_transform(cloud, pose)))
        window = self._keyframes[-self.config.local_map_keyframes :]
        merged = np.concatenate([keyframe.cloud for keyframe in window], axis=0)
        self._target, self._target_tree = self._gicp.preprocess_points(
            merged,
            downsampling_resolution=self.config.downsample_m,
            num_threads=self.config.num_threads,
        )

    # -- covariance --------------------------------------------------------

    def _covariance(self, hessian: Any) -> tuple[float, ...]:
        block = np.asarray(hessian)[np.ix_(_PLANAR_INDEX, _PLANAR_INDEX)]
        try:
            inverse = np.linalg.inv(block)
        except np.linalg.LinAlgError:
            return self._floor_covariance((0.0,) * 9, degenerate=True)
        sigma = float(self.config.sigma_range_m) ** 2 * inverse
        sigma = 0.5 * (sigma + sigma.T)
        if not np.all(np.isfinite(sigma)) or np.any(np.diag(sigma) < 0.0):
            return self._floor_covariance((0.0,) * 9, degenerate=True)
        return self._floor_covariance(tuple(float(value) for value in sigma.reshape(9)))

    def _floor_covariance(
        self,
        cov: tuple[float, ...],
        *,
        degenerate: bool = False,
    ) -> tuple[float, ...]:
        out = list(cov)
        floor_xy = self.config.cov_floor_m2 * (1e6 if degenerate else 1.0)
        floor_yaw = self.config.cov_floor_rad2 * (1e6 if degenerate else 1.0)
        out[0] = max(out[0], floor_xy)
        out[4] = max(out[4], floor_xy)
        out[8] = max(out[8], floor_yaw)
        return tuple(out)

    def _lift(self, points_xy: Any) -> Any:
        points = np.asarray(points_xy, dtype=np.float64)
        layers = [
            np.concatenate([points, np.full((len(points), 1), z)], axis=1)
            for z in self.config.lift_layers_m
        ]
        return np.concatenate(layers, axis=0)


def _matrix(pose: tuple[float, float, float]) -> Any:
    out = np.eye(4)
    cos_t, sin_t = math.cos(pose[2]), math.sin(pose[2])
    out[0, 0], out[0, 1] = cos_t, -sin_t
    out[1, 0], out[1, 1] = sin_t, cos_t
    out[0, 3], out[1, 3] = pose[0], pose[1]
    return out


def _se2(transform: Any) -> tuple[float, float, float]:
    return (
        float(transform[0, 3]),
        float(transform[1, 3]),
        wrap_angle(math.atan2(float(transform[1, 0]), float(transform[0, 0]))),
    )


def _transform(cloud: Any, pose: tuple[float, float, float]) -> Any:
    points = np.asarray(cloud, dtype=np.float64)
    cos_t, sin_t = math.cos(pose[2]), math.sin(pose[2])
    out = np.empty_like(points)
    out[:, 0] = cos_t * points[:, 0] - sin_t * points[:, 1] + pose[0]
    out[:, 1] = sin_t * points[:, 0] + cos_t * points[:, 1] + pose[1]
    out[:, 2] = points[:, 2]
    return out
