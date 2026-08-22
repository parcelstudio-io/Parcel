from __future__ import annotations

import math
import time
from dataclasses import dataclass

from parcel_robot.authority import (
    CLEARANCE_CONVENTION,
    DEFAULT_SAFETY_ENVELOPE,
    DEFAULT_STAND_OFF_ENVELOPE,
    ClearanceProfile,
    SafetyEnvelope,
    gate_lateral_clearance_m,
)
from parcel_robot.backends.base import OwnerTrack, SimObservation
from parcel_robot.core.input_health import (
    InputEvidence,
    RequiredInput,
    RequiredInputSpec,
    evaluate_input_health,
    evidence_origin,
)
from parcel_robot.models import VelocityCommand

#: robot.yaml ``safety.obstacle_stop_m`` commissioning floor. Stricter than
#: ``SafetyEnvelope.obstacle_stop_floor_m`` (0.6); unifying downward would
#: loosen the live reactive gate (forbidden). Under
#: :data:`~parcel_robot.authority.CLEARANCE_CONVENTION` both thresholds are
#: base-center-to-surface metres; consumers must not re-add the footprint.
_REACTIVE_OBSTACLE_STOP_FLOOR_M = 0.65

#: The margin the authority already puts between a *minimum clearance* ring and
#: the *stand-off that wraps it*: ``arrival_radius_m`` (the controller's terminal
#: position tolerance, 0.06) + ``stand_off_margin_m`` (the authority's standing
#: trailing margin, 0.04) = 0.10 m. ``StandOffEnvelope`` uses exactly this pair
#: (``stand_off(r) - minimum_vicinity(r) == arrival_radius_m +
#: stand_off_margin_m``), and the owner stand-off family in
#: :mod:`parcel_robot.navigation.follow` is built on it.
#:
#: It is DEFINED here rather than in ``follow.py`` (which now imports it) because
#: this module is the one that must not import ``follow`` — and because the gate
#: below is now a consumer: the owner comfort band is this margin. One
#: definition, so the controller's stand-off and the gate's owner band cannot
#: fork.
OWNER_STAND_OFF_MARGIN_M = (
    DEFAULT_STAND_OFF_ENVELOPE.arrival_radius_m
    + DEFAULT_STAND_OFF_ENVELOPE.stand_off_margin_m
)

#: The confidence at which a track is treated as POSITIVELY IDENTIFIED as the
#: owner, and therefore eligible for the owner comfort band below.
#:
#: Not a new number and not a safety threshold invented here: it is the value the
#: rest of the stack already uses to answer the same question — "is this track
#: the owner?" — in ``FollowConfig.min_confidence`` (which imports it from here)
#: and ``SearchOwnerConfig.owner_confidence_min``. The gate may not be more
#: willing to grant the owner's band than the controller is to follow the track.
#:
#: Deliberately a module-level FLOOR and not a ``ReactiveSafetyPolicy`` field: a
#: commissioning file may lower a *controller's* willingness to act on a weak
#: track, but it must not widen the set of tracks that get relaxed clearance
#: from the final safety gate.
OWNER_IDENTITY_CONFIDENCE_MIN = 0.65

# =====================================================================
# ---- CARD OT-2: THE PUBLISHED IDENTITY SEAM.  DOOR-1 READS THIS. ----
#
# Stability contract, because DOOR-1 (task_19) consumes this module
# read-only while this card is being written: **nothing above this marker
# moved.** ``OWNER_IDENTITY_CONFIDENCE_MIN`` keeps its name, its value
# (0.65) and its meaning; ``OWNER_STAND_OFF_MARGIN_M`` keeps all three.
# Everything below is ADDITIVE. The only behaviour this card changes is
# inside ``_owner_identity_trusted``.
#
# THE DIRECTION OF THAT CHANGE, MEASURED — not "strictly fewer", which is
# what the first version of this comment claimed and which is false (Fable,
# OT-2 verification, item 4). Over a 7,650-case enumeration (6 sources x 5
# states x 51 confidences x 5 margins) against HEAD's rule: **1,314 newly
# REFUSED, 66 newly GRANTED, 6,270 unchanged**
# (``test_ot2_the_direction_of_the_change_is_measured_not_asserted``).
#
# Every one of the 66 is the same narrow shape: ``pixel_reid`` (a gallery
# calibrated against a known non-owner) AND ``confirmed`` AND headroom above
# the noise floor AND a cosine BELOW 0.65. They exist because a calibrated
# operating point can legitimately sit low — the fixture encoder in
# ``tests/test_ot2_identity.py`` calibrates to **0.639943** — and refusing
# them would mean re-importing a channel-prior number onto the cosine scale,
# which is the one thing this card was told not to do. What they buy is the
# relaxed comfort BAND only; the stop ring is ``person_stop_m`` on both sides
# of this predicate.
#
# Nothing here can move a stop distance, a comfort band's value, the
# predictive stop, the TTC brake, the orbit gate or the obstacle path.
#
# WHY ANY OF THIS EXISTS. Until P1-C, ``confidence`` was a channel prior —
# the fusion stub's hard-coded 0.55 (UWB) / 0.70 (vision) trust in whatever
# supplied pose — and the mocap simulator's flat 1.0. 0.65 is the right
# question to ask of a number like that. P1-C made ``confidence`` a
# MEASURED COSINE against an enrolled gallery, and 0.65 is a meaningless
# question to ask of one: P1-C measured a STRANGER at 0.9295 against the
# owner's crops. Every person-shaped crop clears 0.65.
#
# So a measured identity is not judged on the number at all. It is judged
# on the three things the producer knows and a float cannot carry: WHAT the
# producer decided (``state``), WHETHER the boundary it decided against was
# calibrated against a known non-owner or merely guessed
# (``identity_source``), and HOW MUCH HEADROOM the claim had above that
# boundary (``identity_margin``).
# =====================================================================

#: ``OwnerTrack.identity_source`` values this module understands.
IDENTITY_SOURCE_UNSTATED = ""
IDENTITY_SOURCE_MOCAP = "mocap_ground_truth"
IDENTITY_SOURCE_CHANNEL_PRIOR = "channel_prior"
IDENTITY_SOURCE_PIXEL_REID = "pixel_reid"
IDENTITY_SOURCE_PIXEL_REID_UNCALIBRATED = "pixel_reid_uncalibrated"

#: Sources whose ``confidence`` is a MEASUREMENT of who this is. These are
#: judged by state + calibration + headroom, never by the float.
MEASURED_IDENTITY_SOURCES: frozenset[str] = frozenset(
    {IDENTITY_SOURCE_PIXEL_REID, IDENTITY_SOURCE_PIXEL_REID_UNCALIBRATED}
)

#: Of those, the ones whose decision boundary was itself MEASURED against a
#: known non-owner. ``pixel_reid_uncalibrated`` is deliberately absent, and
#: that absence is card P1-C's headline finding turned into a rule: its
#: threshold is derived from the owner's own crops, and on real SigLIP-2
#: whole-body crops that derivation landed at 0.9103 while the stranger in
#: the same room scored 0.9295 — it claimed the stranger on 2 of 20 frames.
#: An uncalibrated gallery may still drive follow and conversation; it may
#: never buy the relaxed clearance the owner band is.
CALIBRATED_IDENTITY_SOURCES: frozenset[str] = frozenset({IDENTITY_SOURCE_PIXEL_REID})

#: Sources whose ``confidence`` is a PRIOR about a channel rather than a
#: measurement of a person. These keep the pre-OT-2 rule, unchanged, at the
#: unchanged 0.65 — which is the only question that number was ever able to
#: answer. ``""`` is here because every producer that predates this card
#: emits it, and their behaviour may not move.
CHANNEL_PRIOR_IDENTITY_SOURCES: frozenset[str] = frozenset(
    {
        IDENTITY_SOURCE_UNSTATED,
        IDENTITY_SOURCE_MOCAP,
        IDENTITY_SOURCE_CHANNEL_PRIOR,
    }
)

#: The producer states that count as "I have positively identified them".
#: One entry, and it is one on purpose: ``ambiguous`` is the producer saying
#: it could not tell two people apart, ``lost``/``searching`` is the
#: producer saying it cannot see them, and none of those is an identity.
OWNER_IDENTITY_TRUSTED_STATES: frozenset[str] = frozenset({"confirmed"})

#: Minimum HEADROOM, in cosine units, above the producer's own measured
#: operating point before a measured claim buys the owner band.
#:
#: DERIVED, and the derivation is the point (pre-registered in
#: ``scrum/20260822/task_17/PREREGISTRATION.md`` D-1 before it was
#: measured). P1-C measured the gallery's own REPRODUCIBILITY at 2.02e-4:
#: two enrollments of the same six crops produced ``negative_reference``
#: 0.928006 and 0.928208 on fp16 CUDA. A claim whose headroom is smaller
#: than the boundary's own reproducibility is noise, not evidence. Ten times
#: that spread is 2.02e-3; rounded up to the next 5e-3 grid point:
#:
#:     0.005
#:
#: It is a NOISE FLOOR, not an operating point. The operating point is the
#: gallery's, it was measured at enrollment, and this module does not
#: second-guess it — it only refuses to treat a decision made inside its own
#: measurement noise as a decision.
OWNER_IDENTITY_MARGIN_MIN = 0.005
# ---- END CARD OT-2 identity seam ------------------------------------


@dataclass(frozen=True)
class ReactiveSafetyPolicy:
    """Final body-frame proximity gate; distances from :class:`SafetyEnvelope`.

    Clearance convention matches :data:`~parcel_robot.authority.CLEARANCE_CONVENTION`
    (``base_center_to_obstacle_surface``). Person/obstacle slow bands and the
    reaction horizon are envelope-derived; obstacle stop keeps the stricter
    commissioning floor via ``max(envelope.floor, 0.65)``.

    **The gate's LOGIC is not in this class** — it is ``apply_reactive_safety``
    below, which card P1-E did not touch. What this class holds is the
    distances, and as of P1-E the person clearance's SOURCE is config
    (``safety.person_stop_m``) floored at
    :data:`~parcel_robot.authority.PERSON_SOCIAL_ZONE_FLOOR_M`, rather than
    config floored at the shipped 1.2 m social zone (which made the shipped
    value its own floor and refused every indoor commissioning).
    """

    clearance_convention: str = CLEARANCE_CONVENTION
    obstacle_stop_m: float = max(
        DEFAULT_SAFETY_ENVELOPE.obstacle_stop_floor_m,
        _REACTIVE_OBSTACLE_STOP_FLOOR_M,
    )
    obstacle_slow_m: float = DEFAULT_SAFETY_ENVELOPE.obstacle_comfort_band_m
    person_stop_m: float = DEFAULT_SAFETY_ENVELOPE.person_stop(0.0)
    person_slow_m: float = DEFAULT_SAFETY_ENVELOPE.person_comfort_band_m
    telemetry_stale_s: float = 0.6
    owner_collision_envelope_m: float = 0.55
    orbit_clearance_margin_m: float = 0.10
    orbit_waypoint_tolerance_m: float = 0.16
    reaction_time_s: float = DEFAULT_SAFETY_ENVELOPE.reaction_latency_s
    #: The authority this policy floors itself against (card P1-E). Injectable
    #: so a scaled body brings its own footprint / latency / braking terms; the
    #: Go2 default is the same object every un-injected call site already used,
    #: so leaving it alone reproduces the previous behaviour exactly.
    envelope: SafetyEnvelope = DEFAULT_SAFETY_ENVELOPE

    def __post_init__(self) -> None:
        if self.clearance_convention != CLEARANCE_CONVENTION:
            raise ValueError(
                "reactive safety clearance_convention must be "
                f"{CLEARANCE_CONVENTION!r} (got {self.clearance_convention!r})"
            )
        values = (
            self.obstacle_stop_m,
            self.obstacle_slow_m,
            self.person_stop_m,
            self.person_slow_m,
            self.telemetry_stale_s,
            self.owner_collision_envelope_m,
            self.orbit_clearance_margin_m,
            self.orbit_waypoint_tolerance_m,
            self.reaction_time_s,
        )
        if any(not math.isfinite(value) or value <= 0.0 for value in values):
            raise ValueError("reactive safety limits must be positive and finite")
        if self.obstacle_stop_m >= self.obstacle_slow_m:
            raise ValueError("obstacle stop distance must be below slow distance")
        if self.person_stop_m >= self.person_slow_m:
            raise ValueError("person stop distance must be below slow distance")
        # Card DOOR-1 (2026-08-22) changes the SOURCE of the number on the right,
        # and nothing else — the same move card P1-E made one ring out, for the
        # same reason. It used to be ``self.envelope.obstacle_stop_floor_m``, the
        # SHIPPED 0.6 m field, which made the shipped envelope its own floor: an
        # indoor profile could not commission a ring under 0.6 m, and at 0.6 m
        # the DIRECTIONAL gate still refuses every corridor narrower than
        # 2*0.6*sin(1.15) = 1.10 m — a standard 0.8-0.9 m interior doorway
        # included. Now the configured ``obstacle_stop_m`` COMMISSIONS the
        # envelope's obstacle ring (``SafetyEnvelope.with_obstacle_stop_ring``)
        # and the floor underneath is the authority's named
        # ``OBSTACLE_STOP_FLOOR_M`` — the body's ISO/TS-15066 stopping distance
        # at the APPROACH regime, which no commissioning may undercut. The
        # refusal is unchanged in kind: still a construction error, still fails
        # closed, still names what was violated.
        try:
            self.envelope.with_obstacle_stop_ring(self.obstacle_stop_m)
        except ValueError as error:
            # Re-raised in the gate's own vocabulary so the operator sees the
            # CONFIG KEY they set and the FLOOR they have to clear in one line.
            raise ValueError(
                f"reactive obstacle_stop_m must not undercut the commissioning "
                f"floor: {error}"
            ) from error
        # SYMMETRIC as of the owner-authorized person-clearance retune
        # (2026-08-10, "1. person clearance. Implement your recommendation").
        # Mirrors the obstacle floor immediately above: the person clearance may
        # be commissioned STRICTER than the authority but never looser. This
        # could not land before, because the shipped ``robot.yaml`` injected
        # ``person_stop_m: 1.0`` — 0.2 m under the HUMAN-bucket social zone — and
        # every runtime built from it would have raised. The paired yaml retune
        # (1.2 / 2.5), the derived ``owner_keepout_m`` (1.75) and follow
        # stand-off (1.85), and the re-frozen rows are recorded in
        # scrum/20260809/task_15/E5_PERSON_CLEARANCE_STATUS.md.
        #
        # Card P1-E (2026-08-22) changes the SOURCE of the number on the right,
        # and nothing else. It used to be ``DEFAULT_SAFETY_ENVELOPE.person_stop(0.0)``
        # — the SHIPPED social zone, 1.2 m — which made the shipped commissioning
        # value its own floor: no config could ever set a smaller person
        # clearance, and an overlay that tried (indoor 0.7 m) did not relax the
        # robot, it stopped the robot from booting (P0-A blocker;
        # WAVE_P0_VERIFICATION_FABLE.md row A-1). Now the configured
        # ``person_stop_m`` COMMISSIONS the envelope's social zone, and the
        # floor underneath is the authority's named
        # ``PERSON_SOCIAL_ZONE_FLOOR_M`` — the body's ISO/TS-15066 stopping
        # distance at cruise, which no commissioning may undercut. The refusal
        # itself is unchanged in kind: still a construction error, still fails
        # closed, still names what was violated. ``with_person_social_zone``
        # raises on an under-floor value, so the message an operator sees for
        # ``safety.person_stop_m: 0.6`` names the floor and the number.
        try:
            commissioned = self.envelope.with_person_social_zone(self.person_stop_m)
        except ValueError as error:
            # Re-raised in the gate's own vocabulary so the operator sees the
            # CONFIG KEY they set and the FLOOR they have to clear in one line,
            # and so the refusal is greppable under both names.
            raise ValueError(
                f"reactive person_stop_m must not undercut the commissioning "
                f"floor: {error}"
            ) from error
        # WHY THIS SECOND CHECK STAYS (asked under P1-E verification, which read
        # it as vestigial). ``commissioned.person_stop(0.0)`` is
        # ``max(person_stop_m, stop_distance(0.0))``, and ``stop_distance(0.0)``
        # is the body itself — ``footprint_radius_m + Zs + Zr``. At GO2 SCALE it
        # is 0.32 m, the 0.68 m floor above dominates it, and this branch is
        # indeed unreachable. It is not unreachable for an INJECTED envelope,
        # which is the whole point of the ``envelope`` field: a body with a
        # footprint (or a sensing-intrusion / pose-uncertainty term) wider than
        # the commissioned person clearance would otherwise be allowed to
        # commission a stop ring INSIDE its own hull. So this is the physics
        # floor and the constant above is the proxemics floor; they bind for
        # different robots. Reachability is demonstrated, not asserted, by
        # ``tests/test_p1e_social_zone_is_config.py``
        # ::test_the_physics_floor_still_binds_for_a_wider_body.
        if self.person_stop_m + 1e-12 < commissioned.person_stop(0.0):
            raise ValueError(
                "reactive person_stop_m must not undercut "
                "SafetyEnvelope.person_stop(0.0)"
            )
        # Card DOOR-1: the obstacle twin of the physics floor immediately above,
        # and it sits HERE rather than beside the obstacle commissioning check so
        # that a wide injected body reports the PERSON violation first — the
        # order P1-E's ``test_the_physics_floor_still_binds_for_a_wider_body``
        # reads, and the more useful message when both are true. Same argument as
        # its person twin: at Go2 scale ``stop_distance(0.0)`` is 0.32 m and the
        # 0.41 m commissioning floor dominates it, but for an INJECTED envelope
        # (a wider hull, a sensing-intrusion or pose-uncertainty term) it is the
        # binding one, and a robot may not commission an obstacle stop ring
        # inside its own body.
        if self.obstacle_stop_m + 1e-12 < self.envelope.stop_distance(0.0):
            raise ValueError(
                "reactive obstacle_stop_m must not undercut "
                "SafetyEnvelope.stop_distance(0.0)"
            )
        # Lane E6 (2026-08-11, owner-band separation). ``owner_slow_m`` is
        # DERIVED, never configured, so the only way it can degenerate is an
        # authority whose stand-off margin is zero. Caught here so that becomes a
        # construction error instead of a zero-width ramp (or a division by zero)
        # inside the gate. The owner's STOP distance is not involved: it is
        # ``person_stop_m``, identical to a stranger's, and is floored above.
        if self.owner_slow_m <= self.person_stop_m:
            raise ValueError(
                "owner comfort band must sit strictly outside the shared "
                "person stop distance"
            )

    @property
    def owner_slow_m(self) -> float:
        """Comfort band for a POSITIVELY-IDENTIFIED owner track (DERIVED).

        Lane E6, 2026-08-11. Strangers keep ``person_slow_m``
        (``SafetyEnvelope.person_comfort_band_m``, 2.5 m — the human social
        zone). The owner is a person the dog is *supposed* to walk beside, and
        applying the social zone to them throttled the follow controller at every
        distance it operates at: measured on FOLLOW_BENCH_V1, ``person_slow_m``
        2.0 -> 2.5 alone dropped ``follow_success`` 9/9 -> 6/9, including on
        ``owner_turn_90``, a scenario with **zero pedestrians**
        (``scrum/20260809/task_15/E5_PERSON_CLEARANCE_STATUS.md`` §4).

        The band is derived, not chosen. This gate compares a CLEARANCE (owner
        center distance minus ``owner_collision_envelope_m``) while the follow
        controller aims at a CENTER distance, so converting the controller's own
        stand-off into this gate's coordinates makes the envelope cancel::

            owner_slow_m = desired_distance_m - owner_collision_envelope_m
                         = (owner_keepout_m + OWNER_STAND_OFF_MARGIN_M)
                           - owner_collision_envelope_m
                         = (person_stop_m + owner_collision_envelope_m
                            + OWNER_STAND_OFF_MARGIN_M)
                           - owner_collision_envelope_m
                         = person_stop_m + OWNER_STAND_OFF_MARGIN_M

        At the shipped values that is ``1.2 + 0.10 = 1.30 m`` of clearance, i.e.
        ``1.85 m`` of center distance — **exactly** ``FollowConfig``'s nominal
        stand-off. So the comfort ramp occupies exactly the stand-off margin, the
        slack the authority already reserves between a keepout ring and the
        stand-off that wraps it. Read as behaviour: holding the formation is not
        throttled; closing inside the formation eases off; and at the keepout
        ring the SAME hard stop as any stranger fires. That is the same defect
        E5 fixed one ring out (a stand-off must not sit inside its own keepout),
        applied to the comfort band instead of the stop.

        Clamped by ``person_slow_m`` so the owner can never be given a *wider*
        band than a stranger under an unusual commissioning.
        """

        return min(self.person_stop_m + OWNER_STAND_OFF_MARGIN_M, self.person_slow_m)

    @property
    def commissioned_envelope(self) -> SafetyEnvelope:
        """This gate's authority with the social zone COMMISSIONED from config.

        Card P1-E. ``person_stop_m`` arrives from ``configs/robot*.yaml``
        ``safety.person_stop_m``; this is that number wearing the authority's
        type, so every derived quantity (``person_stop(v)``, the stand-off
        family, the planner inflation below) comes off ONE object rather than
        off a constant that config can silently disagree with.
        """

        return self.envelope.with_person_social_zone(self.person_stop_m).with_obstacle_stop_ring(
            self.obstacle_stop_m
        )

    @property
    def clearance_profile(self) -> ClearanceProfile:
        """The ONE immutable commissioned profile the planner must be built from.

        Card DOOR-1 / design DW-4. ``ReactiveSafetyPolicy`` is what the runtime
        actually commissions from ``configs/robot*.yaml``; this is that
        commissioning expressed as the shared type, so a planner construction
        site can take ``policy.clearance_profile.obstacle_ring_m`` and be
        derived from the SAME number this gate will enforce rather than from a
        second opinion about the body.

        Note what does NOT happen here: the profile does not tell the gate
        anything. ``apply_reactive_safety`` still reads ``obstacle_stop_m``
        directly, and ``ClearanceProfile.final_gate_ring_m`` recomputes the
        gate's ring from the profile independently, so the two can be compared.
        """

        return ClearanceProfile(obstacle_ring_m=self.obstacle_stop_m, envelope=self.envelope)

    @property
    def planner_inflation_m(self) -> float:
        """Lateral inflation a grid planner needs to AGREE with this gate.

        Card P1-E / audit §6, "one number, two consumers". The obstacle ring is
        the binding one for a lidar occupancy map, and the gate's directional
        cone converts a stop ring into a lateral radius (see
        :func:`~parcel_robot.authority.gate_lateral_clearance_m`). Feed this to
        ``GridPlannerConfig.gate_clearance_m`` and the planner stops choosing
        corridors this gate will refuse to drive down.

        A map whose cells are PEOPLE takes ``person_stop_m`` instead — same
        function, the other ring — which is why the number is derived here and
        not frozen into the planner.
        """

        return gate_lateral_clearance_m(self.obstacle_stop_m)


def apply_reactive_safety(
    command: VelocityCommand,
    observation: SimObservation | None,
    *,
    policy: ReactiveSafetyPolicy,
    owner_orbit: bool = False,
    orbit_radius_m: float = 0.0,
    now: float | None = None,
    require_fresh_telemetry: bool = True,
) -> tuple[VelocityCommand, str]:
    """Apply the final body-frame safety gate used in runtime and quality tests."""

    if observation is None:
        return _stop_translation(command) if _translating(command) else (command, "clear")
    timestamp = time.monotonic() if now is None else now
    if require_fresh_telemetry and timestamp - observation.timestamp > policy.telemetry_stale_s:
        return _stop_translation(command) if _translating(command) else (command, "clear")

    translating = _translating(command)
    # P0-B: a present observation with no scan must not authorize translation.
    # Route through the core input-health join (missing → HOLD), never "clear".
    if translating and not _scan_health_allows_translation(observation, now=timestamp):
        return _stop_translation(command)
    predictive_state = "clear"
    owner_dx = observation.owner.x - observation.robot.x
    owner_dy = observation.owner.y - observation.robot.y
    owner_center_distance = math.hypot(owner_dx, owner_dy)
    # (clearance_m, bearing_rad, comfort_band_m). Only the BAND varies per
    # person; the stop distance below is ``policy.person_stop_m`` for every
    # entry, owner included (lane E6, 2026-08-11).
    people: list[tuple[float, float | None, float]] = []
    if observation.nearest_person_m is not None:
        people.append(
            (
                observation.nearest_person_m,
                observation.nearest_person_bearing_rad,
                policy.person_slow_m,
            )
        )
    if observation.owner.visible and not owner_orbit:
        owner_clearance = max(
            0.0,
            owner_center_distance - policy.owner_collision_envelope_m,
        )
        people.append(
            (
                owner_clearance,
                _wrap(math.atan2(owner_dy, owner_dx) - observation.robot.yaw),
                _owner_comfort_band_m(observation, policy),
            )
        )
    for person_distance, person_bearing, person_slow_m in people if translating else ():
        toward_person = _toward(command, person_bearing)
        predictive_person_stop = (
            policy.person_stop_m
            + math.hypot(command.vx, command.vy) * policy.reaction_time_s
        )
        if toward_person and person_distance <= predictive_person_stop:
            return _stop_translation(command)
        if toward_person and person_distance < person_slow_m:
            scale = max(
                0.15,
                (person_distance - policy.person_stop_m)
                / (person_slow_m - policy.person_stop_m),
            )
            command = _scale_translation(command, scale)
            predictive_state = "slowing"

    if owner_orbit and translating:
        minimum_center_distance = max(
            policy.obstacle_stop_m
            + policy.owner_collision_envelope_m
            + policy.orbit_clearance_margin_m,
            orbit_radius_m - policy.orbit_waypoint_tolerance_m,
        )
        owner_bearing = _wrap(
            math.atan2(owner_dy, owner_dx) - observation.robot.yaw
        )
        if owner_center_distance <= minimum_center_distance and _toward(
            command,
            owner_bearing,
            half_angle=math.pi / 2.0,
        ):
            return _stop_translation(command)

    person_ttc = observation.nearest_person_ttc_s
    if translating and person_ttc is not None:
        if person_ttc <= 0.8:
            return _stop_translation(command)
        if person_ttc < 1.8:
            command = _scale_translation(
                command,
                max(0.15, (person_ttc - 0.8) / 1.0),
            )
            predictive_state = "slowing"
    if not translating:
        return command, "clear"

    toward_obstacle = True
    distance: float | None
    if observation.lidar_obstacles:
        directional = [
            item
            for item in observation.lidar_obstacles
            if not (
                owner_orbit
                and item.obstacle_id is not None
                and item.obstacle_id.startswith("owner_")
            )
            if _toward(command, item.bearing_rad)
        ]
        if not directional:
            return command, predictive_state
        distance = min(directional, key=lambda item: item.distance_m).distance_m
    else:
        distance = observation.nearest_obstacle_m
        bearing = observation.nearest_obstacle_bearing_rad
        # A sparse range without a bearing fails closed for every translation.
        toward_obstacle = bearing is None or _toward(command, bearing)
    if observation.collision and toward_obstacle:
        return _stop_translation(command)
    if not toward_obstacle or distance is None:
        return command, predictive_state
    if distance <= policy.obstacle_stop_m:
        return _stop_translation(command)
    predictive_obstacle_stop = (
        policy.obstacle_stop_m
        + math.hypot(command.vx, command.vy) * policy.reaction_time_s
    )
    if distance <= predictive_obstacle_stop:
        return _stop_translation(command)
    if distance < policy.obstacle_slow_m:
        scale = max(
            0.15,
            (distance - policy.obstacle_stop_m)
            / (policy.obstacle_slow_m - policy.obstacle_stop_m),
        )
        return _scale_translation(command, scale), "slowing"
    return command, predictive_state


def _owner_comfort_band_m(
    observation: SimObservation,
    policy: ReactiveSafetyPolicy,
) -> float:
    """Which comfort band the owner entry gets this tick. Returns metres.

    Lane E6, 2026-08-11. Two conditions, both of which must hold before the
    relaxed :attr:`ReactiveSafetyPolicy.owner_slow_m` is granted; every other
    outcome returns the stranger band ``policy.person_slow_m``. Neither
    condition can change the STOP distance, which is ``policy.person_stop_m``
    for the owner exactly as for a stranger.

    1. **Identity.** ``_owner_identity_trusted`` — a positively-identified owner
       track, never "the nearest person" and never an unlabeled one.
    2. **Two-body interlock.** No stranger perceived AT ALL. The relaxation is a
       TWO-BODY contract: the owner chose to walk beside the dog, so the dog
       need not treat holding that formation as an intrusion. A bystander made
       no such choice, and a bystander cannot consent on the dog's timetable.
       While any stranger is on the person channel the scene is not two-body and
       the social band governs the whole command again — including the part of
       it that is chasing the owner.

       **Deliberately a presence test and not a range test.** A range-based
       interlock was built first, at the obvious ring (``person_slow_m``), and
       REJECTED BY MEASUREMENT: FOLLOW_BENCH_V1's
       ``pedestrian_cut_in_predictive`` still gave back 0.25 m of pedestrian
       clearance with it (``min_pedestrian_surface_m`` 0.8183 -> 0.2810 m, dwell
       0.0 -> 1.6 s), because the give-back is not a throttle that fired late —
       it is the dog having travelled further up the corridor before an
       unrelated brake stopped it, so it stands 0.54 m deeper into the
       pedestrian's scripted path. No ring fixes that; only refusing the
       relaxation while a stranger exists does. Choosing a ring that happened to
       hold the bench would have been fitting a safety constant to an eval.

       The presence test also has no free parameter to tune, and it makes the
       lane's central safety claim checkable by construction rather than by
       trend: in every episode where a pedestrian is perceived, this gate is
       bit-identical to the one E5 measured, so no stranger clearance can move.

    What this costs, stated where the code is: the dog will lag its owner in a
    crowd. That is the intended reading of the two-body rule, not a defect.
    What it cannot do is bounded exactly — the relaxation moves ONE band, for
    ONE entry, between ``owner_slow_m`` and ``person_slow_m``. It cannot touch
    the stop ring, the predictive stop, the TTC brake, the collision gate, the
    obstacle path, or any stranger entry.

    Residual, flagged not fixed: ``nearest_person_m is None`` cannot distinguish
    "nobody there" from "no person channel", so a deployment with no person
    sensing at all reads as two-body. Bounded by the paragraph above (the worst
    case is the dog closing on ITS OWN OWNER to 1.85 m of center distance before
    the same hard stop as ever), and by P0-B, which already refuses to translate
    at all when the scan channel is missing. Widening the test to
    ``dynamic_agents`` is the obvious extension seam and is left to a card that
    owns that channel.
    """

    if not _owner_identity_trusted(observation.owner):
        return policy.person_slow_m
    if observation.nearest_person_m is not None:
        return policy.person_slow_m
    return policy.owner_slow_m


def _owner_identity_trusted(owner: OwnerTrack) -> bool:
    """True only for a POSITIVELY-IDENTIFIED owner track. Fails closed.

    The one question that decides whether the relaxed owner comfort band applies
    (lane E6, 2026-08-11). Every uncertain answer is ``False``, and ``False``
    means the track is treated as a stranger — same stop distance either way, but
    the wider 2.5 m social band. In particular an absent/blank ``owner_id``, a
    non-finite or missing confidence, and any confidence below
    :data:`OWNER_IDENTITY_CONFIDENCE_MIN` all fall back to the stranger band.

    ``visible`` is checked by the caller: a track that is not visible is not in
    the people list at all.

    Pinned by ``REACTIVE_SAFETY_PIN`` alongside the gate itself — this predicate
    is now part of the safety authority, so it may not move silently.

    **CARD OT-2 (2026-08-22) — this is the one symbol the card moves.** Before
    it, the whole predicate was "is this float ≥ 0.65". That was the right
    question of a channel prior and is a meaningless question of a cosine: P1-C
    measured a STRANGER at 0.9295 against the owner's own crops, so a 0.65 floor
    on a measured identity trusts every person-shaped thing in the room. The
    predicate now branches on WHERE the number came from
    (``OwnerTrack.identity_source``):

    * a MEASURED identity (pixels) is judged on the producer's own verdict
      (``state == "confirmed"``), on whether that verdict was made against a
      boundary calibrated with a known non-owner, and on the HEADROOM the claim
      had above that boundary — never on the number itself;
    * a CHANNEL PRIOR (UWB/vision trust, the mocap body, or any producer that
      predates this card and stamps nothing) keeps the pre-OT-2 rule at the
      pre-OT-2 constant, byte for byte;
    * a source this module does not recognise is not an identity. It is the one
      new "no" here, and it is a no to a RELAXATION, not a refusal to move: the
      track drops to the stranger band the whole stack shipped with.

    Everything E6 said still holds: every uncertain answer is ``False``, and
    ``False`` costs the owner the wider social band and nothing else. The stop
    distance is ``policy.person_stop_m`` on both sides of this branch.
    """

    owner_id = owner.owner_id
    if not isinstance(owner_id, str) or not owner_id.strip():
        return False
    confidence = owner.confidence
    if isinstance(confidence, bool) or not isinstance(confidence, (int, float)):
        return False
    if not math.isfinite(confidence):
        return False
    source = getattr(owner, "identity_source", IDENTITY_SOURCE_UNSTATED)
    if not isinstance(source, str):
        return False
    if source in MEASURED_IDENTITY_SOURCES:
        if source not in CALIBRATED_IDENTITY_SOURCES:
            return False
        state = getattr(owner, "state", "")
        if not isinstance(state, str) or state not in OWNER_IDENTITY_TRUSTED_STATES:
            return False
        margin = getattr(owner, "identity_margin", 0.0)
        if isinstance(margin, bool) or not isinstance(margin, (int, float)):
            return False
        return math.isfinite(margin) and margin >= OWNER_IDENTITY_MARGIN_MIN
    if source not in CHANNEL_PRIOR_IDENTITY_SOURCES:
        return False
    return confidence >= OWNER_IDENTITY_CONFIDENCE_MIN


# ---- CARD OT-2: the identity DECISION, published under a public name ----
# An ALIAS and not a wrapper, deliberately. A wrapper would move the logic out
# of ``_owner_identity_trusted`` and therefore out of ``REACTIVE_SAFETY_PIN``,
# which watches that symbol by name — a consumer-facing convenience would have
# quietly cost the safety authority its ratchet. Binding the same function
# object to a second name costs nothing and leaves the pinned definition the
# only definition.
#
# For DOOR-1 and any other consumer: ask this rather than re-deriving a
# threshold. The threshold is not the rule any more.
owner_identity_trusted = _owner_identity_trusted
# ---- END CARD OT-2 ------------------------------------------------------


def _translating(command: VelocityCommand) -> bool:
    return math.hypot(command.vx, command.vy) > 1e-6


def scan_present(observation: SimObservation) -> bool:
    """True when any commissioned scan channel carries a sample this tick."""

    if observation.lidar_obstacles:
        return True
    if observation.nearest_obstacle_m is not None:
        return True
    return bool(observation.lidar_ranges)


def scan_evidence_from_observation(observation: SimObservation) -> InputEvidence | None:
    """Build scan ``InputEvidence`` for the core health join, or ``None`` if missing."""

    if not scan_present(observation):
        return None
    # Simulated backends are labeled fixtures; unlabeled sim is rejected by the
    # health join. Physical / unknown backends stay unlabeled physical samples.
    # One shared stamper (``evidence_origin``) so no channel can hard-code
    # PHYSICAL and defeat the fixture check.
    origin, fixture_label = evidence_origin(observation.backend)
    return InputEvidence(
        captured_at=observation.timestamp,
        frame_id="base_link",
        payload_valid=True,
        origin=origin,
        fixture_label=fixture_label,
    )


def _scan_health_allows_translation(observation: SimObservation, *, now: float) -> bool:
    """Fail closed on missing/stale/malformed scan via the core health join."""

    verdict = evaluate_input_health(
        {RequiredInput.SCAN: scan_evidence_from_observation(observation)},
        now=now,
        requirements={
            RequiredInput.SCAN: RequiredInputSpec(
                frame_id="base_link",
                max_age_s=0.25,
                sim_fixture_allowed=True,
            ),
        },
    )
    return verdict.translation_allowed


def _toward(
    command: VelocityCommand,
    bearing: float | None,
    *,
    half_angle: float = 1.15,
) -> bool:
    if bearing is None:
        return True
    travel_angle = math.atan2(command.vy, command.vx)
    return abs(_wrap(bearing - travel_angle)) < half_angle


def _scale_translation(command: VelocityCommand, scale: float) -> VelocityCommand:
    return VelocityCommand(
        vx=command.vx * scale,
        vy=command.vy * scale,
        vyaw=command.vyaw,
    )


def _stop_translation(command: VelocityCommand) -> tuple[VelocityCommand, str]:
    return VelocityCommand(vyaw=command.vyaw), "stopped"


def _wrap(angle: float) -> float:
    return (angle + math.pi) % (2.0 * math.pi) - math.pi
