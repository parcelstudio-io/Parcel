"""Thread-safe, shadow-only runtime observer for ``SOCIAL-PROGRESS-1``.

This leaf adapts the stamped navigation snapshot into the pure proposal policy.
Value contracts and the bounded public projection live in sibling leaves so
this mechanism stays below Parcel's module and function-size ratchets.
"""

from __future__ import annotations

import hashlib
import math
import threading
from collections import deque
from collections.abc import Mapping
from dataclasses import replace
from itertools import islice, pairwise

from parcel_robot.contracts.navigation_snapshot_v2 import (
    RANGE_CONVENTION_BASE_CENTRE,
    RANGE_CONVENTION_BODY_SURFACE,
    DynamicTrackV2,
    NavigationSnapshotV2,
    TraversabilityV1,
)
from parcel_robot.navigation.social_progress import (
    MAX_TRACK_CLASS_ID_CHARS,
    MAX_TRACK_COVARIANCE_ENTRIES,
    MAX_TRACK_ID_CHARS,
    SemanticContextV1,
    SocialLivenessV1,
    SocialProgressMemoryV1,
    SocialTrackEvidenceV1,
    VisibilityEvidenceV1,
    VisibilityStateV1,
    decide_social_progress,
)
from parcel_robot.navigation.social_progress_observer_contracts import (
    MAX_DYNAMIC_TRACKS,
    MAX_OBSERVER_HISTORY,
    MAX_OBSTACLE_ID_CHARS,
    MAX_OBSTACLE_ROWS,
    MAX_PLANAR_SCAN_RAYS,
    MAX_PUBLIC_HISTORY_SUMMARIES,
    MAX_PUBLIC_SNAPSHOT_BYTES,
    MAX_SNAPSHOT_EPOCH_ROWS,
    MAX_SNAPSHOT_EVIDENCE_IDS,
    OBSERVER_SCHEMA_VERSION,
    PlannerFactsV1,
    SocialProgressObserverConfigV1,
    SocialProgressObserverSampleV1,
    VelocityEvidenceV1,
    VelocityPrimitiveV1,
    _finite,
    _nonnegative_int,
    _RememberedTrack,
    _ScanTiming,
    _validate_snapshot_public_integers,
)
from parcel_robot.navigation.social_progress_observer_public import (
    public_latest as _public_latest,
)
from parcel_robot.navigation.social_progress_observer_public import (
    public_summary as _public_summary,
)


def _angle_delta(angle: float, reference: float) -> float:
    return math.atan2(math.sin(angle - reference), math.cos(angle - reference))


class SocialProgressObserverV1:
    """Adapt evidence and retain a bounded, atomically readable shadow trace."""

    def __init__(
        self,
        config: SocialProgressObserverConfigV1 | Mapping[str, object] | None = None,
    ) -> None:
        if isinstance(config, SocialProgressObserverConfigV1):
            parsed = config
        else:
            parsed = SocialProgressObserverConfigV1.from_mapping(config)
        self._config = parsed
        self._lock = threading.RLock()
        self._history: deque[SocialProgressObserverSampleV1] = deque(maxlen=parsed.history_size)
        self._generation: int | None = None
        self._sample_sequence = 0
        self._memory = SocialProgressMemoryV1(
            recovery_budget_remaining=parsed.decision_config.initial_recovery_budget
        )
        self._remembered_tracks: dict[str, _RememberedTrack] = {}
        self._blocked_since_s: float | None = None

    @property
    def enabled(self) -> bool:
        return self._config.enabled

    @property
    def mode(self) -> str:
        return self._config.mode

    def _reset_locked(self, navigation_generation: int | None) -> None:
        self._history.clear()
        self._generation = navigation_generation
        self._sample_sequence = 0
        self._memory = SocialProgressMemoryV1(
            recovery_budget_remaining=self._config.decision_config.initial_recovery_budget
        )
        self._remembered_tracks.clear()
        self._blocked_since_s = None

    def reset(self, navigation_generation: int | None = None) -> None:
        if navigation_generation is not None:
            _nonnegative_int(navigation_generation, "navigation_generation")
        with self._lock:
            self._reset_locked(navigation_generation)

    def _validated_observe_context(
        self,
        *,
        navigation_generation: int,
        now_monotonic_s: float,
        snapshot: NavigationSnapshotV2 | None,
        requested_velocity: VelocityEvidenceV1,
        final_velocity: VelocityEvidenceV1,
        achieved_velocity: VelocityEvidenceV1,
        planner: PlannerFactsV1,
        semantics: SemanticContextV1 | None,
        liveness: SocialLivenessV1 | None,
    ) -> tuple[int, float, SemanticContextV1]:
        generation = _nonnegative_int(navigation_generation, "navigation_generation")
        now = _finite(now_monotonic_s, "now_monotonic_s", minimum=0.0)
        if snapshot is not None and not isinstance(snapshot, NavigationSnapshotV2):
            raise TypeError("snapshot must be NavigationSnapshotV2 or None")
        for name, velocity in (
            ("requested_velocity", requested_velocity),
            ("final_velocity", final_velocity),
            ("achieved_velocity", achieved_velocity),
        ):
            if not isinstance(velocity, VelocityEvidenceV1):
                raise TypeError(f"{name} must be VelocityEvidenceV1")
            if velocity.sample_monotonic_s > now:
                raise ValueError(f"{name} cannot be sampled after now_monotonic_s")
        if not isinstance(planner, PlannerFactsV1):
            raise TypeError("planner must be PlannerFactsV1")
        context = SemanticContextV1() if semantics is None else semantics
        if not isinstance(context, SemanticContextV1):
            raise TypeError("semantics must be SemanticContextV1 or None")
        if liveness is not None and not isinstance(liveness, SocialLivenessV1):
            raise TypeError("liveness must be SocialLivenessV1 or None")
        if liveness is not None and liveness.progress_requested != planner.progress_demand:
            raise ValueError("liveness.progress_requested must match planner.progress_demand")
        if self._config.enabled and snapshot is not None:
            _validate_snapshot_public_integers(snapshot)
            self._validate_snapshot_bounds(snapshot)
            assembled_s = snapshot.assembled_monotonic_ns / 1_000_000_000.0
            if assembled_s > now:
                raise ValueError("snapshot assembly time cannot be after now_monotonic_s")
        return generation, now, context

    def observe(
        self,
        *,
        navigation_generation: int,
        now_monotonic_s: float,
        snapshot: NavigationSnapshotV2 | None,
        requested_velocity: VelocityEvidenceV1,
        final_velocity: VelocityEvidenceV1,
        achieved_velocity: VelocityEvidenceV1,
        planner: PlannerFactsV1,
        semantics: SemanticContextV1 | None = None,
        liveness: SocialLivenessV1 | None = None,
    ) -> SocialProgressObserverSampleV1 | None:
        """Observe one evidence-only tick; disabled mode is a mutation-free no-op."""

        generation, now, context = self._validated_observe_context(
            navigation_generation=navigation_generation,
            now_monotonic_s=now_monotonic_s,
            snapshot=snapshot,
            requested_velocity=requested_velocity,
            final_velocity=final_velocity,
            achieved_velocity=achieved_velocity,
            planner=planner,
            semantics=semantics,
            liveness=liveness,
        )
        if not self._config.enabled:
            return None

        with self._lock:
            if self._generation != generation:
                self._reset_locked(generation)
            if snapshot is None:
                tracks: tuple[SocialTrackEvidenceV1, ...] = ()
                corridor = None
                derived_liveness = self._derive_liveness(
                    now=now,
                    snapshot=None,
                    planner=planner,
                    achieved=achieved_velocity,
                    tracks=tracks,
                    supplied=liveness,
                )
                revision = None
                assembled_ns = None
                evidence_ids: tuple[str, ...] = ()
                epochs: tuple[tuple[str, int], ...] = ()
            else:
                heading = self._requested_heading(requested_velocity, final_velocity, planner)
                tracks = self._derive_tracks(snapshot=snapshot, now=now, heading=heading)
                corridor = self._derive_corridor_evidence(
                    snapshot=snapshot,
                    now=now,
                    heading=heading,
                    tracks=tracks,
                )
                derived_liveness = self._derive_liveness(
                    now=now,
                    snapshot=snapshot,
                    planner=planner,
                    achieved=achieved_velocity,
                    tracks=tracks,
                    supplied=liveness,
                )
                revision = snapshot.revision
                assembled_ns = snapshot.assembled_monotonic_ns
                evidence_ids = tuple(header.evidence_id for header in snapshot.headers)
                epochs = snapshot.contributing_epochs

            decision = decide_social_progress(
                now_monotonic_s=now,
                tracks=tracks,
                corridor_evidence=corridor,
                semantics=context,
                liveness=derived_liveness,
                memory=self._memory,
                config=self._config.decision_config,
            )
            self._memory = decision.next_memory
            self._sample_sequence += 1
            sample = SocialProgressObserverSampleV1(
                sample_sequence=self._sample_sequence,
                navigation_generation=generation,
                observed_monotonic_s=now,
                snapshot_missing=snapshot is None,
                snapshot_revision=revision,
                snapshot_assembled_monotonic_ns=assembled_ns,
                snapshot_evidence_ids=evidence_ids,
                snapshot_epochs=epochs,
                requested_velocity=requested_velocity,
                final_velocity=final_velocity,
                achieved_velocity=achieved_velocity,
                planner=planner,
                tracks=tracks,
                corridor_evidence=corridor,
                decision=decision,
            )
            self._history.append(sample)
            return sample

    def snapshot(self) -> dict[str, object]:
        """Return the bounded public diagnostic view.

        Full immutable samples stay in ``_history`` for a future non-public
        sink.  This method performs work only for the detailed latest row and
        the last :data:`MAX_PUBLIC_HISTORY_SUMMARIES` compact rows; it never
        materializes or serializes all retained samples.
        """

        with self._lock:
            generation = self._generation
            retained_count = len(self._history)
            latest = self._history[-1] if self._history else None
            newest = tuple(islice(reversed(self._history), MAX_PUBLIC_HISTORY_SUMMARIES))
        summaries = tuple(reversed(newest))
        return {
            "schema_version": OBSERVER_SCHEMA_VERSION,
            "public_schema": "social_progress_observer_public_v1",
            "enabled": self._config.enabled,
            "mode": self._config.mode,
            "navigation_generation": generation,
            "history_capacity": self._config.history_size,
            "sample_count": retained_count,
            "public_history_limit": MAX_PUBLIC_HISTORY_SUMMARIES,
            "public_history_count": len(summaries),
            "history_truncated": retained_count > len(summaries),
            "latest": None if latest is None else _public_latest(latest),
            "history": [_public_summary(item) for item in summaries],
        }

    def _requested_heading(
        self,
        requested: VelocityEvidenceV1,
        final: VelocityEvidenceV1,
        planner: PlannerFactsV1,
    ) -> float | None:
        if not planner.progress_demand:
            return None
        for sample in (requested, final):
            velocity = sample.primitive
            if velocity.planar_speed_mps >= self._config.motion_epsilon_mps:
                return math.atan2(velocity.vy_mps, velocity.vx_mps)
        return None

    @staticmethod
    def _validate_snapshot_bounds(snapshot: NavigationSnapshotV2) -> None:
        """Refuse oversized nested data before sorting/derivation/history."""

        if len(snapshot.dynamic_tracks) > MAX_DYNAMIC_TRACKS:
            raise ValueError(f"dynamic_tracks exceeds {MAX_DYNAMIC_TRACKS} rows")
        if len(snapshot.traversability.obstacles) > MAX_OBSTACLE_ROWS:
            raise ValueError(f"traversability obstacles exceeds {MAX_OBSTACLE_ROWS} rows")
        if len(snapshot.traversability.ranges) > MAX_PLANAR_SCAN_RAYS:
            raise ValueError(f"planar scan exceeds {MAX_PLANAR_SCAN_RAYS} rays")

        # Every nested length check precedes covariance iteration in the pure
        # wrapper.  Thus even a hostile 250k-entry tuple is rejected by len()
        # before sorting, hashing, copying into retained memory, or derivation.
        for track in snapshot.dynamic_tracks:
            if not track.track_id or len(track.track_id) > MAX_TRACK_ID_CHARS:
                raise ValueError(
                    "dynamic track track_id must be non-empty and at most "
                    f"{MAX_TRACK_ID_CHARS} characters"
                )
            if not track.class_id or len(track.class_id) > MAX_TRACK_CLASS_ID_CHARS:
                raise ValueError(
                    "dynamic track class_id must be non-empty and at most "
                    f"{MAX_TRACK_CLASS_ID_CHARS} characters"
                )
            if len(track.covariance) > MAX_TRACK_COVARIANCE_ENTRIES:
                raise ValueError(
                    f"dynamic track covariance exceeds {MAX_TRACK_COVARIANCE_ENTRIES} entries"
                )
        track_ids = tuple(track.track_id for track in snapshot.dynamic_tracks)
        if len(set(track_ids)) != len(track_ids):
            raise ValueError("dynamic_tracks cannot contain duplicate track_id values")
        obstacle_ids = tuple(
            obstacle.obstacle_id
            for obstacle in snapshot.traversability.obstacles
            if obstacle.obstacle_id is not None
        )
        for obstacle_id in obstacle_ids:
            if not obstacle_id or len(obstacle_id) > MAX_OBSTACLE_ID_CHARS:
                raise ValueError(
                    f"obstacle_id must be non-empty and at most {MAX_OBSTACLE_ID_CHARS} characters"
                )
        for name, identifier in (
            ("nearest_obstacle_id", snapshot.traversability.nearest_obstacle_id),
            ("person_id", snapshot.person_proximity.person_id),
        ):
            if identifier is not None and (
                not identifier or len(identifier) > MAX_OBSTACLE_ID_CHARS
            ):
                raise ValueError(
                    f"{name} must be non-empty and at most {MAX_OBSTACLE_ID_CHARS} characters"
                )

    def _derive_tracks(
        self,
        *,
        snapshot: NavigationSnapshotV2,
        now: float,
        heading: float | None,
    ) -> tuple[SocialTrackEvidenceV1, ...]:
        current = tuple(sorted(snapshot.dynamic_tracks, key=lambda item: item.track_id))
        current_ids = {track.track_id for track in current}
        rows: list[SocialTrackEvidenceV1] = []
        next_memory: dict[str, _RememberedTrack] = {}
        for track in current:
            next_memory[track.track_id] = _RememberedTrack(
                track=track,
                last_seen_monotonic_s=now,
                last_snapshot_revision=snapshot.revision,
            )
            rows.append(self._current_track_evidence(snapshot, track, now, heading))

        missing_capacity = MAX_DYNAMIC_TRACKS - len(current)
        retained = tuple(
            sorted(
                (
                    (track_id, remembered)
                    for track_id, remembered in self._remembered_tracks.items()
                    if track_id not in current_ids
                    and now - remembered.last_seen_monotonic_s
                    <= self._config.missing_track_retention_s
                ),
                key=lambda item: (-item[1].last_seen_monotonic_s, item[0]),
            )[:missing_capacity]
        )
        for track_id, remembered in retained:
            next_memory[track_id] = remembered
            rows.append(self._missing_track_evidence(snapshot, remembered, now, heading))
        self._remembered_tracks = next_memory
        return tuple(rows)

    def _track_relative_body(
        self, snapshot: NavigationSnapshotV2, track: DynamicTrackV2
    ) -> tuple[float, float, float, float]:
        robot_x, robot_y, robot_yaw = snapshot.base_in_map
        dx = track.x - robot_x
        dy = track.y - robot_y
        cos_yaw = math.cos(robot_yaw)
        sin_yaw = math.sin(robot_yaw)
        body_x = cos_yaw * dx + sin_yaw * dy
        body_y = -sin_yaw * dx + cos_yaw * dy
        return body_x, body_y, math.hypot(body_x, body_y), math.atan2(body_y, body_x)

    def _in_corridor(
        self,
        snapshot: NavigationSnapshotV2,
        track: DynamicTrackV2,
        heading: float | None,
    ) -> tuple[bool, float]:
        body_x, body_y, distance, _ = self._track_relative_body(snapshot, track)
        if heading is None:
            return False, distance
        along = math.cos(heading) * body_x + math.sin(heading) * body_y
        lateral = abs(-math.sin(heading) * body_x + math.cos(heading) * body_y)
        robot_radius = self._robot_footprint_radius(snapshot.traversability)
        # Unknown base-centre footprint cannot prove separation.  Retain a
        # conservatively widened social corridor while clear certification is
        # refused separately.
        if robot_radius is None:
            robot_radius = self._config.corridor_half_width_m
        in_corridor = (
            -robot_radius - track.radius_m
            <= along
            <= self._config.corridor_lookahead_m + robot_radius + track.radius_m
            and lateral <= max(self._config.corridor_half_width_m, robot_radius) + track.radius_m
        )
        return in_corridor, distance

    def _scan_timing(self, snapshot: NavigationSnapshotV2, now: float) -> _ScanTiming | None:
        """Validate source age, transport, clock uncertainty, and health.

        ``EvidenceHeaderV1.transport_age_ns`` may be larger than the apparent
        capture-to-assembly gap.  The larger value is the effective transport
        and is preserved in the sidecar's source/receive stamps; it is never
        hidden by replacing receive time with ``now``.
        """

        now_ns = int(now * 1_000_000_000)
        header = snapshot.traversability.header
        capture_ns = header.capture_monotonic_ns
        assembled_ns = snapshot.assembled_monotonic_ns
        if capture_ns > now_ns or capture_ns > assembled_ns or assembled_ns > now_ns:
            return None
        effective_transport_ns = max(
            header.transport_age_ns,
            assembled_ns - capture_ns,
        )
        receive_ns = capture_ns + effective_transport_ns
        if receive_ns > now_ns:
            return None
        source_age_ns = now_ns - capture_ns
        max_source_age_ns = min(
            header.max_age_ns,
            int(self._config.lidar_max_age_s * 1_000_000_000),
            int(self._config.decision_config.max_source_age_s * 1_000_000_000),
        )
        max_transport_ns = int(self._config.decision_config.max_transport_delay_s * 1_000_000_000)
        max_clock_uncertainty_ns = int(self._config.max_clock_uncertainty_s * 1_000_000_000)
        if (
            source_age_ns > max_source_age_ns
            or effective_transport_ns > max_transport_ns
            or header.clock_map_uncertainty_ns > max_clock_uncertainty_ns
            or header.clock_map_uncertainty_ns > header.max_age_ns
            or header.health_reasons
        ):
            return None
        source_s = capture_ns / 1_000_000_000.0
        receive_s = receive_ns / 1_000_000_000.0
        if receive_ns > capture_ns:
            # Integer nanoseconds above are authoritative.  Round the float
            # representation one ULP inward so an exact configured transport
            # bound cannot become spuriously over-bound after subtraction
            # (for example, ``10.08 - 10.0 > 0.08`` in binary64).
            receive_s = max(source_s, math.nextafter(receive_s, source_s))
        return _ScanTiming(
            source_monotonic_s=source_s,
            receive_monotonic_s=receive_s,
            effective_transport_s=effective_transport_ns / 1_000_000_000.0,
        )

    def _scan_fresh(self, snapshot: NavigationSnapshotV2, now: float) -> bool:
        return self._scan_timing(snapshot, now) is not None

    def _track_scan_visible(
        self,
        snapshot: NavigationSnapshotV2,
        track: DynamicTrackV2,
        now: float,
    ) -> bool:
        scan = snapshot.traversability
        if not self._scan_fresh(snapshot, now):
            return False
        _, _, distance, bearing = self._track_relative_body(snapshot, track)
        expected_center_range = max(0.0, distance - track.radius_m)
        for obstacle in scan.obstacles:
            if obstacle.obstacle_id != track.track_id:
                continue
            measured_center_range = self._range_from_base_center(scan, obstacle.distance_m)
            if (
                measured_center_range is not None
                and math.isfinite(obstacle.bearing_rad)
                and abs(_angle_delta(obstacle.bearing_rad, bearing))
                <= self._config.lidar_mark_angular_tolerance_rad
                and abs(measured_center_range - expected_center_range)
                <= self._config.lidar_mark_tolerance_m
            ):
                return True
        if (
            not scan.ranges
            or scan.angle_min_rad is None
            or scan.angle_increment_rad is None
            or scan.angle_increment_rad == 0.0
        ):
            return False
        nearest = min(
            range(len(scan.ranges)),
            key=lambda index: abs(
                _angle_delta(
                    scan.angle_min_rad + index * scan.angle_increment_rad,
                    bearing,
                )
            ),
        )
        ray_error = abs(
            _angle_delta(
                scan.angle_min_rad + nearest * scan.angle_increment_rad,
                bearing,
            )
        )
        if ray_error > self._config.lidar_mark_angular_tolerance_rad:
            return False
        measured_center_range = self._range_from_base_center(scan, scan.ranges[nearest])
        if measured_center_range is None:
            return False
        return (
            abs(measured_center_range - expected_center_range)
            <= self._config.lidar_mark_tolerance_m
        )

    def _current_track_evidence(
        self,
        snapshot: NavigationSnapshotV2,
        track: DynamicTrackV2,
        now: float,
        heading: float | None,
    ) -> SocialTrackEvidenceV1:
        scan = snapshot.traversability
        in_corridor, distance = self._in_corridor(snapshot, track, heading)
        scan_fresh = self._scan_fresh(snapshot, now)
        visible = self._track_scan_visible(snapshot, track, now)
        _, _, _, bearing = self._track_relative_body(snapshot, track)
        if visible:
            visibility = VisibilityStateV1.VISIBLE
        elif not scan_fresh:
            visibility = VisibilityStateV1.STALE
        elif self._bearing_in_scan(scan, bearing):
            visibility = VisibilityStateV1.OCCLUDED
        else:
            visibility = VisibilityStateV1.OUT_OF_FOV
        source_s, receive_s = self._evidence_times(snapshot, now, use_scan=visible)
        evidence = VisibilityEvidenceV1(
            evidence_id=self._track_evidence_id(
                track_id=track.track_id,
                kind="lidar" if visible else "snapshot",
                lineage=(scan.header.evidence_id if visible else str(snapshot.revision)),
            ),
            visibility=visibility,
            source_monotonic_s=source_s,
            receive_monotonic_s=receive_s,
            lidar_mark_evidence_refs=(scan.header.evidence_id,) if visible else (),
        )
        confidence = min(1.0, max(0.0, track.confidence))
        surface_distance = self._surface_distance(snapshot, distance, track.radius_m)
        within_hard = surface_distance <= self._config.hard_envelope_m
        proximity_risk = max(
            0.0,
            1.0 - surface_distance / max(self._config.corridor_lookahead_m, 1e-9),
        )
        risk = 1.0 if within_hard else min(1.0, confidence * proximity_risk)
        return SocialTrackEvidenceV1(
            track=track,
            existence_probability=confidence,
            visibility_evidence=evidence,
            in_swept_corridor=in_corridor,
            risk_upper_bound=risk,
            within_hard_envelope=within_hard,
        )

    def _missing_track_evidence(
        self,
        snapshot: NavigationSnapshotV2,
        remembered: _RememberedTrack,
        now: float,
        heading: float | None,
    ) -> SocialTrackEvidenceV1:
        track = remembered.track
        in_corridor, distance = self._in_corridor(snapshot, track, heading)
        age = max(0.0, now - remembered.last_seen_monotonic_s)
        visibility = (
            VisibilityStateV1.OCCLUDED
            if age <= self._config.decision_config.max_source_age_s
            else VisibilityStateV1.STALE
        )
        evidence = VisibilityEvidenceV1(
            evidence_id=self._track_evidence_id(
                track_id=track.track_id,
                kind="missing-after",
                lineage=str(remembered.last_snapshot_revision),
            ),
            visibility=visibility,
            source_monotonic_s=remembered.last_seen_monotonic_s,
            receive_monotonic_s=remembered.last_seen_monotonic_s,
        )
        confidence = min(1.0, max(0.0, track.confidence))
        surface_distance = self._surface_distance(snapshot, distance, track.radius_m)
        within_hard = surface_distance <= self._config.hard_envelope_m
        return SocialTrackEvidenceV1(
            track=track,
            existence_probability=confidence,
            visibility_evidence=evidence,
            in_swept_corridor=in_corridor,
            risk_upper_bound=(
                1.0
                if within_hard
                else min(
                    1.0,
                    confidence
                    * max(
                        0.0,
                        1.0 - surface_distance / max(self._config.corridor_lookahead_m, 1e-9),
                    ),
                )
            ),
            within_hard_envelope=within_hard,
        )

    @staticmethod
    def _track_evidence_id(*, track_id: str, kind: str, lineage: str) -> str:
        """Hash bounded producer lineage into one fixed-size retained ID."""

        digest = hashlib.sha256(f"{track_id}\x00{kind}\x00{lineage}".encode()).hexdigest()
        return f"track-evidence:{digest}"

    def _evidence_times(
        self, snapshot: NavigationSnapshotV2, now: float, *, use_scan: bool
    ) -> tuple[float, float]:
        if use_scan:
            timing = self._scan_timing(snapshot, now)
            if timing is None:
                raise ValueError("fresh scan evidence timing is unavailable")
            return timing.source_monotonic_s, timing.receive_monotonic_s
        assembled_s = snapshot.assembled_monotonic_ns / 1_000_000_000.0
        return assembled_s, assembled_s

    @staticmethod
    def _bearing_in_scan(scan: TraversabilityV1, bearing: float) -> bool:
        if (
            not scan.ranges
            or scan.angle_min_rad is None
            or scan.angle_increment_rad is None
            or scan.angle_increment_rad == 0.0
        ):
            return False
        offsets = [
            _angle_delta(scan.angle_min_rad + i * scan.angle_increment_rad, bearing)
            for i in (0, len(scan.ranges) - 1)
        ]
        if len(scan.ranges) * abs(scan.angle_increment_rad) >= 2.0 * math.pi - 1e-3:
            return True
        return offsets[0] == 0.0 or offsets[1] == 0.0 or offsets[0] * offsets[1] <= 0.0

    def _derive_corridor_evidence(
        self,
        *,
        snapshot: NavigationSnapshotV2,
        now: float,
        heading: float | None,
        tracks: tuple[SocialTrackEvidenceV1, ...],
    ) -> VisibilityEvidenceV1 | None:
        if (
            heading is None
            or not snapshot.translation_allowed
            or any(track.in_swept_corridor for track in tracks)
            or self._person_proximity_contradicts(snapshot, now, heading)
        ):
            return None
        scan = snapshot.traversability
        if not self._complete_free_scan(snapshot, now, heading):
            return None
        source_s, receive_s = self._evidence_times(snapshot, now, use_scan=True)
        evidence_id = self._clear_certificate_id(scan)
        return VisibilityEvidenceV1(
            evidence_id=evidence_id,
            visibility=VisibilityStateV1.EXPLICIT_FREE,
            source_monotonic_s=source_s,
            receive_monotonic_s=receive_s,
            corridor_fully_observed=True,
            corridor_coverage=1.0,
            lidar_clear_evidence_refs=(scan.header.evidence_id,),
        )

    @staticmethod
    def _clear_certificate_id(scan: TraversabilityV1) -> str:
        header = scan.header
        lineage = "\x00".join(
            (
                header.source_id,
                str(header.process_epoch),
                str(header.sequence),
                str(header.capture_monotonic_ns),
                header.calibration_hash,
            )
        ).encode("utf-8")
        return f"corridor-free:{hashlib.sha256(lineage).hexdigest()}"

    def _complete_free_scan(
        self, snapshot: NavigationSnapshotV2, now: float, heading: float
    ) -> bool:
        scan = snapshot.traversability
        if not self._scan_fresh(snapshot, now):
            return False
        if scan.range_convention not in {
            RANGE_CONVENTION_BASE_CENTRE,
            RANGE_CONVENTION_BODY_SURFACE,
        }:
            return False
        robot_radius = self._robot_footprint_radius(scan)
        if robot_radius is None:
            # A base-centre range cannot prove swept-body clearance without a
            # commissioned centre-to-footprint conversion.
            return False
        if (
            not scan.ranges
            or scan.angle_min_rad is None
            or scan.angle_increment_rad is None
            or scan.angle_increment_rad == 0.0
            or scan.range_max_m is None
            or math.isnan(scan.range_max_m)
            or scan.range_max_m <= 0.0
        ):
            return False
        if self._config.corridor_half_width_m < robot_radius:
            return False
        rows: list[tuple[float, float]] = []
        for index, distance in enumerate(scan.ranges):
            angle = scan.angle_min_rad + index * scan.angle_increment_rad
            phase = (angle - heading) % (2.0 * math.pi)
            rows.append((phase, distance))
        if len(rows) < self._config.minimum_corridor_rays:
            return False
        rows.sort(key=lambda item: item[0])
        gaps = [right[0] - left[0] for left, right in pairwise(rows)]
        gaps.append(rows[0][0] + 2.0 * math.pi - rows[-1][0])
        if max(gaps) > self._config.max_corridor_ray_gap_rad + 1e-12:
            return False
        max_center_range = self._range_from_base_center(scan, scan.range_max_m)
        if max_center_range is None:
            return False
        for phase, distance in rows:
            boundary = self._swept_rectangle_boundary_m(
                delta_rad=_angle_delta(phase, 0.0),
                robot_radius_m=robot_radius,
            )
            measured_center_range = self._range_from_base_center(scan, distance)
            if measured_center_range is None:
                return False
            usable_center_range = min(measured_center_range, max_center_range)
            if usable_center_range <= boundary + 1e-12:
                return False
        for obstacle in scan.obstacles:
            obstacle_center_range = self._range_from_base_center(scan, obstacle.distance_m)
            if obstacle_center_range is None:
                return False
            boundary = self._swept_rectangle_boundary_m(
                delta_rad=_angle_delta(obstacle.bearing_rad, heading),
                robot_radius_m=robot_radius,
            )
            if obstacle_center_range <= boundary + 1e-12:
                return False
        if scan.nearest_obstacle_m is not None:
            if scan.nearest_obstacle_bearing_rad is None:
                return False
            nearest_center_range = self._range_from_base_center(scan, scan.nearest_obstacle_m)
            if nearest_center_range is None:
                return False
            boundary = self._swept_rectangle_boundary_m(
                delta_rad=_angle_delta(scan.nearest_obstacle_bearing_rad, heading),
                robot_radius_m=robot_radius,
            )
            if nearest_center_range <= boundary + 1e-12:
                return False
        return True

    def _swept_rectangle_boundary_m(
        self,
        *,
        delta_rad: float,
        robot_radius_m: float,
    ) -> float:
        """Distance from base centre to the full swept-rectangle boundary.

        In travel coordinates the occupied region spans the current rear body
        edge ``-robot_radius`` through ``lookahead + robot_radius`` and both
        lateral sides.  Because the ray starts inside that rectangle, its exit
        is the nearer of the longitudinal and lateral intersections.  This is
        why a pedestrian at +/-60 degrees is checked near the side wall rather
        than ignored by an endpoint-only wedge.
        """

        cosine = math.cos(delta_rad)
        sine = math.sin(delta_rad)
        if cosine > 1e-12:
            longitudinal_exit = (self._config.corridor_lookahead_m + robot_radius_m) / cosine
        elif cosine < -1e-12:
            longitudinal_exit = robot_radius_m / -cosine
        else:
            longitudinal_exit = math.inf
        lateral_exit = (
            self._config.corridor_half_width_m / abs(sine) if abs(sine) > 1e-12 else math.inf
        )
        return min(longitudinal_exit, lateral_exit)

    @staticmethod
    def _range_from_base_center(scan: TraversabilityV1, distance_m: float) -> float | None:
        if math.isnan(distance_m) or distance_m < 0.0:
            return None
        if scan.range_convention == RANGE_CONVENTION_BASE_CENTRE:
            return distance_m
        if scan.range_convention == RANGE_CONVENTION_BODY_SURFACE:
            return distance_m + scan.footprint_radius_m
        return None

    def _person_proximity_contradicts(
        self,
        snapshot: NavigationSnapshotV2,
        now: float,
        heading: float,
    ) -> bool:
        proximity = snapshot.person_proximity
        if proximity.distance_m is None:
            return False
        assembled_s = snapshot.assembled_monotonic_ns / 1_000_000_000.0
        fresh = (
            snapshot.translation_allowed
            and assembled_s <= now
            and now - assembled_s <= self._config.decision_config.max_source_age_s
        )
        if not fresh:
            return False
        # Zero/negative/non-finite proximity cannot be evidence of clearance.
        if not math.isfinite(proximity.distance_m) or proximity.distance_m <= 0.0:
            return True
        if proximity.bearing_rad is None or not math.isfinite(proximity.bearing_rad):
            # The person is fresh but cannot be placed outside the swept area.
            return True
        robot_radius = self._robot_footprint_radius(snapshot.traversability)
        person_center_range = self._range_from_base_center(
            snapshot.traversability,
            proximity.distance_m,
        )
        if robot_radius is None or person_center_range is None:
            return True
        boundary = self._swept_rectangle_boundary_m(
            delta_rad=_angle_delta(proximity.bearing_rad, heading),
            robot_radius_m=robot_radius,
        )
        return person_center_range <= boundary + 1e-12

    def _robot_footprint_radius(self, scan: TraversabilityV1) -> float | None:
        if scan.range_convention == RANGE_CONVENTION_BODY_SURFACE:
            return scan.footprint_radius_m
        if scan.range_convention == RANGE_CONVENTION_BASE_CENTRE:
            return self._config.robot_footprint_radius_m
        return None

    def _surface_distance(
        self,
        snapshot: NavigationSnapshotV2,
        centre_distance_m: float,
        track_radius_m: float,
    ) -> float:
        robot_radius = self._robot_footprint_radius(snapshot.traversability)
        if robot_radius is None:
            # Unknown footprint cannot establish positive separation.  This is
            # intentionally conservative and affects shadow proposals only.
            return 0.0
        return max(0.0, centre_distance_m - robot_radius - track_radius_m)

    def _derive_liveness(
        self,
        *,
        now: float,
        snapshot: NavigationSnapshotV2 | None,
        planner: PlannerFactsV1,
        achieved: VelocityEvidenceV1,
        tracks: tuple[SocialTrackEvidenceV1, ...],
        supplied: SocialLivenessV1 | None,
    ) -> SocialLivenessV1:
        moving = (
            achieved.fresh
            and achieved.primitive.planar_speed_mps >= self._config.motion_epsilon_mps
        )
        blocked = planner.progress_demand and planner.body_is_still and not moving
        if blocked:
            if self._blocked_since_s is None:
                self._blocked_since_s = now
            block_duration = max(0.0, now - self._blocked_since_s)
        else:
            self._blocked_since_s = None
            block_duration = 0.0

        snapshot_sensor_ok = (
            snapshot is not None
            and snapshot.translation_allowed
            and not snapshot.health_reasons
            and self._scan_fresh(snapshot, now)
        )
        # When the whole snapshot is absent, STALE_SENSOR is the precise
        # primary diagnosis; there is no localization datum from which to
        # assert a localization-specific failure.
        localization_ok = snapshot is None or (
            snapshot.localization.health == "healthy" and not snapshot.localization.motion_latched
        )
        live_corridor_track = any(
            track.in_swept_corridor
            and track.visibility_evidence.visibility is VisibilityStateV1.VISIBLE
            for track in tracks
        )
        costmap_ghost = (
            planner.progress_demand
            and planner.body_is_still
            and planner.steps_gate_blocked > 0
            and not live_corridor_track
        )
        hard_envelope = any(
            track.within_hard_envelope
            and track.visibility_evidence.visibility is VisibilityStateV1.VISIBLE
            for track in tracks
        )
        derived_stable = planner.progress_demand and moving and not planner.body_is_still

        if supplied is None:
            return SocialLivenessV1(
                progress_requested=planner.progress_demand,
                sensor_health_ok=snapshot_sensor_ok and achieved.fresh,
                localization_healthy=localization_ok,
                planner_healthy=planner.planner_healthy,
                hard_envelope_violated=hard_envelope,
                costmap_blocked_without_live_track=costmap_ghost,
                block_duration_s=block_duration,
                stable_progress_confirmed=derived_stable,
            )
        return replace(
            supplied,
            sensor_health_ok=supplied.sensor_health_ok and snapshot_sensor_ok and achieved.fresh,
            localization_healthy=supplied.localization_healthy and localization_ok,
            planner_healthy=supplied.planner_healthy and planner.planner_healthy,
            hard_envelope_violated=supplied.hard_envelope_violated or hard_envelope,
            costmap_blocked_without_live_track=(
                supplied.costmap_blocked_without_live_track or costmap_ghost
            ),
            block_duration_s=max(supplied.block_duration_s, block_duration),
            stable_progress_confirmed=supplied.stable_progress_confirmed and derived_stable,
        )


__all__ = [
    "MAX_DYNAMIC_TRACKS",
    "MAX_OBSERVER_HISTORY",
    "MAX_OBSTACLE_ID_CHARS",
    "MAX_OBSTACLE_ROWS",
    "MAX_PLANAR_SCAN_RAYS",
    "MAX_PUBLIC_HISTORY_SUMMARIES",
    "MAX_PUBLIC_SNAPSHOT_BYTES",
    "MAX_SNAPSHOT_EPOCH_ROWS",
    "MAX_SNAPSHOT_EVIDENCE_IDS",
    "OBSERVER_SCHEMA_VERSION",
    "PlannerFactsV1",
    "SocialProgressObserverConfigV1",
    "SocialProgressObserverSampleV1",
    "SocialProgressObserverV1",
    "VelocityEvidenceV1",
    "VelocityPrimitiveV1",
]
