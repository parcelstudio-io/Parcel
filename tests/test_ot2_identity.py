"""Card OT-2 — the running robot stops believing the owner at 1.0.

P1-C built the producer and proved its failure modes; nothing constructed one.
``headless_city`` handed the control loop a mocap body at confidence 1.0 and
``reactive_safety`` read that 1.0 through a floor of 0.65 — a floor that, on the
cosine scale P1-C actually produces, is met by every person-shaped crop in the
room (the stranger scored 0.9295 against the owner's own gallery).

What this file pins, in the order the card asks for it:

* the identity gate now branches on WHERE the number came from, and a measured
  identity is judged on the producer's ``state``, on whether that producer's
  boundary was CALIBRATED against a known non-owner, and on the HEADROOM the
  claim had above it — never on the number (rows R1-R4);
* the legacy/mocap path is byte-identical, over 648 reactive-safety cases (R5);
* driving P1-C's two-person clip through the RUNTIME's own frame door produces
  an owner confidence that moves, never reaches 1.0, and is trusted by the gate
  only while the tracker has actually confirmed somebody (R6);
* a lost owner degrades to ``searching`` with confidence 0.0 rather than
  repeating its last good answer (R7).

The encoder here is P1-C's deterministic fixture encoder, not SigLIP-2: these
rows measure the MECHANISM. The numbers 0.917 / 0.9295 / 0.9591 are P1-C's
published real-encoder measurements and appear below as direct inputs to the
gate rows, never re-derived.
"""

from __future__ import annotations

import ast
import hashlib
import json
import math
import time
from pathlib import Path
from typing import Any

import pytest

from parcel_robot.audio_io import AudioDeviceStatus
from parcel_robot.backends.base import (
    LidarObstacle,
    OwnerTrack,
    RobotPose,
    SimObservation,
)
from parcel_robot.headless_city import MOCAP_OWNER_CONFIDENCE, MOCAP_OWNER_STATE
from parcel_robot.models import VelocityCommand
from parcel_robot.navigation import reactive_safety as rs
from parcel_robot.owner_tracking.gallery import build_gallery
from parcel_robot.owner_tracking.synthetic_clip import (
    ClipScript,
    crop_for,
    histogram_embed_image,
    iter_clip,
)
from parcel_robot.owner_tracking.tracker import (
    STATE_AMBIGUOUS,
    STATE_CONFIRMED,
    STATE_SEARCHING,
    OwnerTracker,
)
from parcel_robot.runtime import RobotRuntime

REPO = Path(__file__).resolve().parents[1]
RUNTIME_PATH = REPO / "src" / "parcel_robot" / "runtime.py"
CLIP_PATH = Path(__file__).resolve().parent / "data" / "p1c_two_person_clip.json"

#: The pre-registered cosine grid. 41 points, 0.60 -> 1.00 in 0.01 steps.
GRID: tuple[float, ...] = tuple(round(0.60 + 0.01 * i, 2) for i in range(41))

#: P1-C's measured numbers, quoted rather than recomputed (P1C_STATUS.md §0).
STRANGER_AGAINST_UNCALIBRATED = 0.9295
STRANGER_CHANNEL_PRIOR_EQUIVALENT = 0.917
CALIBRATED_THRESHOLD = 0.9591
OWNER_CONFIDENCE_FLOOR = 0.94

#: The clip's own header (same constants P1-C's tracker test uses). Identity
#: rows are measured on 6-19 ONLY, "so no cosine is a crop against itself".
ENROLLMENT_FRAMES = (0, 1, 2, 3, 4, 5)
ENROLLMENT_FRAME_SET = frozenset(ENROLLMENT_FRAMES)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _track(**kwargs: Any) -> OwnerTrack:
    base: dict[str, Any] = {"owner_id": "owner-1", "x": 1.9, "y": 0.0, "visible": True}
    base.update(kwargs)
    return OwnerTrack(**base)


def _trusted(**kwargs: Any) -> bool:
    return rs._owner_identity_trusted(_track(**kwargs))


def _audio() -> AudioDeviceStatus:
    return AudioDeviceStatus(
        status="text mode",
        driver="test",
        capture_hardware=False,
        connected_input=False,
        connected_output=False,
        detail="deterministic test status",
    )


class _Backend:
    name = "fake"

    def __init__(self, observation: SimObservation) -> None:
        self._observation = observation

    def observe(self) -> SimObservation:
        return self._observation

    def move(self, command: object) -> None:
        pass

    def stop(self) -> None:
        pass

    def pose(self, pose: object) -> None:
        pass

    def trajectory(self, skill: object) -> None:
        pass

    def move_owner(self, dx: float, dy: float) -> None:
        pass


class _PixelIngress:
    """The frame-buffer handle the runtime asks an ingress for.

    P1-C handoff 3: ``CameraDetectionFrame`` carries boxes and no pixels, and
    ``ingress.py`` is P1-B's file that no wave-2 card may edit — so the runtime
    duck-types ``latest_rgb()`` and this stands in for the one-line handle that
    belongs there. Nothing in the RUNTIME path differs between this object and
    a real ingress that grows the method.
    """

    def __init__(self) -> None:
        self.rgb: Any = None

    def latest_rgb(self) -> Any:
        return self.rgb

    def stop(self) -> None:
        pass


def _observation(*, timestamp: float | None = None) -> SimObservation:
    return SimObservation(
        timestamp=time.monotonic() if timestamp is None else timestamp,
        robot=RobotPose(x=0.0, y=0.0, yaw=0.0),
        owner=OwnerTrack(
            owner_id="owner-1",
            x=3.0,
            y=0.0,
            visible=True,
            confidence=MOCAP_OWNER_CONFIDENCE,
            state=MOCAP_OWNER_STATE,
            identity_source=rs.IDENTITY_SOURCE_MOCAP,
        ),
        backend="fake",
    )


def _config(tmp_path: Path) -> Path:
    tmp_path.mkdir(parents=True, exist_ok=True)
    path = tmp_path / "robot.yaml"
    path.write_text(
        f"""
skills:
  root: {REPO / "configs" / "skills"}
navigation:
  enabled: false
motion:
  backend: rl
  max_vx: 0.6
  max_vy: 0.4
  max_vyaw: 1.0
  rl:
    enabled: true
    policy_path: ""
memory:
  path: ":memory:"
poses: {{}}
modules: []
perception:
  spatial_sensors: [camera, lidar]
""",
        encoding="utf-8",
    )
    return path


@pytest.fixture(scope="module")
def script() -> ClipScript:
    return ClipScript.load(CLIP_PATH)


@pytest.fixture(scope="module")
def calibrated_gallery(script: ClipScript):
    owner = [histogram_embed_image(crop_for(script, i, "owner")) for i in ENROLLMENT_FRAMES]
    negative = [histogram_embed_image(crop_for(script, i, "other")) for i in ENROLLMENT_FRAMES]
    return build_gallery(owner, model="fixture:histogram_embed_image/v1", negatives=negative)


@pytest.fixture
def runtime(tmp_path: Path) -> RobotRuntime:
    made = RobotRuntime(_config(tmp_path / "cfg"), _Backend(_observation()), audio_status=_audio())
    yield made
    made.close()


def _drive_clip(
    runtime: RobotRuntime, script: ClipScript, gallery: Any
) -> list[dict[str, Any]]:
    """The clip through the RUNTIME's own frame door. This is the product path.

    ``_publish_camera_frame`` is the callback ``CameraIngress.on_frame`` is set
    to at the attach site, and ``_ot2_apply_owner_identity`` is the seam
    ``_control_loop`` calls one line after ``backend.observe()``. Nothing here
    reaches around either of them.
    """

    ingress = _PixelIngress()
    runtime.attach_camera_ingress(ingress, start=False)
    runtime.install_owner_tracker(
        OwnerTracker(gallery=gallery, embed_fn=histogram_embed_image)
    )
    rows: list[dict[str, Any]] = []
    for index, rgb, frame in iter_clip(script):
        ingress.rgb = rgb
        runtime._publish_camera_frame(frame)
        observed = runtime._ot2_apply_owner_identity(_observation())
        owner = observed.owner
        # EVERY frame is FED (the robot does not get to skip frames), and only
        # the HELD-OUT ones are SCORED. That is P1-C's own protocol for this
        # fixture and the clip header states it: "Frames 0-5 are the enrollment
        # set; identity rows are measured on 6-19 so no cosine is a crop
        # against itself."
        #
        # The first version of this helper scored all twenty, so six of the
        # "measured" cosines were enrollment crops compared with themselves and
        # came back at exactly 1.0 — and the pre-registered ``max < 1.0`` was
        # then WEAKENED to accommodate them, on an invented claim that the
        # encoder self-matches. It does not: over all 16 visible owner crops,
        # pairs of DIFFERENT frames at exactly 1.0 = 0 and the max off-diagonal
        # cosine is 0.9999731. (Fable, OT-2 verification, item 3.)
        if index in ENROLLMENT_FRAME_SET:
            continue
        rows.append(
            {
                "index": index,
                "confidence": owner.confidence,
                "state": owner.state,
                "source": owner.identity_source,
                "margin": owner.identity_margin,
                "visible": owner.visible,
                "trusted": rs._owner_identity_trusted(owner),
            }
        )
    return rows


# ---------------------------------------------------------------------------
# the seam DOOR-1 reads — shape, published and unmoved
# ---------------------------------------------------------------------------


def test_ot2_publishes_the_identity_seam_without_moving_what_door1_reads() -> None:
    """DOOR-1 consumes this module read-only WHILE this card is being written.

    Everything DOOR-1 imports keeps its name, its value and its meaning; this
    card is additive. If that ever stops being true it must be said in
    ``OT2_STATUS.md`` first, and this test is what makes "must be said" into
    "cannot be missed".
    """

    from parcel_robot.navigation.follow import FollowConfig
    from parcel_robot.navigation.search_owner import SearchOwnerConfig

    assert rs.OWNER_IDENTITY_CONFIDENCE_MIN == 0.65
    assert FollowConfig.min_confidence == rs.OWNER_IDENTITY_CONFIDENCE_MIN
    assert SearchOwnerConfig.owner_confidence_min == rs.OWNER_IDENTITY_CONFIDENCE_MIN
    assert rs.OWNER_STAND_OFF_MARGIN_M == pytest.approx(0.10)
    # and the three additions, named so a consumer can depend on them
    assert rs.OWNER_IDENTITY_MARGIN_MIN == 0.005
    assert rs.CALIBRATED_IDENTITY_SOURCES == frozenset({rs.IDENTITY_SOURCE_PIXEL_REID})
    assert rs.OWNER_IDENTITY_TRUSTED_STATES == frozenset({STATE_CONFIRMED})
    # the DECISION under a public name — an alias, so the pinned definition
    # stays the only definition
    assert rs.owner_identity_trusted is rs._owner_identity_trusted


def test_ot2_the_identity_vocabulary_agrees_with_the_producer() -> None:
    """One vocabulary, two modules. A drift here is a silent trust change."""

    assert rs.OWNER_IDENTITY_TRUSTED_STATES <= {
        STATE_CONFIRMED,
        STATE_AMBIGUOUS,
        STATE_SEARCHING,
    }
    assert RobotRuntime.OT2_STATE_CONFIRMED == STATE_CONFIRMED
    assert RobotRuntime.OT2_STATE_AMBIGUOUS == STATE_AMBIGUOUS
    assert RobotRuntime.OT2_STATE_SEARCHING == STATE_SEARCHING
    assert MOCAP_OWNER_STATE == STATE_CONFIRMED


# ---------------------------------------------------------------------------
# R1-R4 — the gate, exactly
# ---------------------------------------------------------------------------


def test_R1_a_calibrated_confirmed_claim_with_headroom_is_trusted() -> None:
    """41 of 41. The owner the gallery confirmed keeps the owner band."""

    trusted = [
        c
        for c in GRID
        if _trusted(
            confidence=c,
            state=STATE_CONFIRMED,
            identity_source=rs.IDENTITY_SOURCE_PIXEL_REID,
            identity_margin=0.02,
        )
    ]
    assert len(trusted) == len(GRID) == 41
    # and the card's named case: the enrolled owner at >= 0.94, confirmed by a
    # calibrated gallery whose operating point P1-C measured at 0.9591.
    assert _trusted(
        confidence=0.9739,
        state=STATE_CONFIRMED,
        identity_source=rs.IDENTITY_SOURCE_PIXEL_REID,
        identity_margin=0.9739 - CALIBRATED_THRESHOLD,
    )
    assert 0.9739 >= OWNER_CONFIDENCE_FLOOR


def test_ot2_an_uncalibrated_gallery_can_never_grant_the_owner_band() -> None:
    """R2 — 0 of 41, at ANY cosine, with generous headroom. Seed S3's target.

    This is P1-C's headline finding as a rule. An uncalibrated gallery derives
    its threshold from the owner's own crops; on real SigLIP-2 whole-body crops
    that derivation landed at 0.9103 and the stranger in the same room scored
    0.9295, so the stranger CLEARED it — with 0.0192 of headroom, which any
    headroom test alone would wave through. The calibration flag is the only
    thing that catches it, and it travels all the way from the enrollment file.
    """

    trusted = [
        c
        for c in GRID
        if _trusted(
            confidence=c,
            state=STATE_CONFIRMED,
            identity_source=rs.IDENTITY_SOURCE_PIXEL_REID_UNCALIBRATED,
            identity_margin=0.10,
        )
    ]
    assert trusted == []
    assert not _trusted(
        confidence=STRANGER_AGAINST_UNCALIBRATED,
        state=STATE_CONFIRMED,
        identity_source=rs.IDENTITY_SOURCE_PIXEL_REID_UNCALIBRATED,
        identity_margin=STRANGER_AGAINST_UNCALIBRATED - 0.9103,
    )


def test_ot2_a_measured_identity_is_never_judged_on_the_raw_cosine() -> None:
    """R3 — 0 of 41 for an AMBIGUOUS calibrated claim. Seed S2's target.

    The comparison that makes this a measurement rather than an assertion: a
    raw-cosine gate at the old 0.65 would have trusted 36 of the same 41
    points, every one of them a track the producer had just said it could not
    tell apart from somebody else.
    """

    trusted = [
        c
        for c in GRID
        if _trusted(
            confidence=c,
            state=STATE_AMBIGUOUS,
            identity_source=rs.IDENTITY_SOURCE_PIXEL_REID,
            identity_margin=0.02,
        )
    ]
    raw_gate_would_trust = [c for c in GRID if c >= rs.OWNER_IDENTITY_CONFIDENCE_MIN]
    assert trusted == []
    assert len(raw_gate_would_trust) == 36
    # the stranger P1-C measured, arriving as a confident-looking cosine
    assert not _trusted(
        confidence=STRANGER_CHANNEL_PRIOR_EQUIVALENT,
        state=STATE_AMBIGUOUS,
        identity_source=rs.IDENTITY_SOURCE_PIXEL_REID,
        identity_margin=0.30,
    )


def test_R4_the_gate_keys_on_state_not_on_the_number() -> None:
    """164 cases, exactly 41 trusted, and all 41 are the confirmed row."""

    outcomes = {
        (state, c): _trusted(
            confidence=c,
            state=state,
            identity_source=rs.IDENTITY_SOURCE_PIXEL_REID,
            identity_margin=0.02,
        )
        for state in (STATE_CONFIRMED, STATE_AMBIGUOUS, "lost", STATE_SEARCHING)
        for c in GRID
    }
    assert len(outcomes) == 164
    assert sum(outcomes.values()) == 41
    assert {state for (state, _c), ok in outcomes.items() if ok} == {STATE_CONFIRMED}


def test_ot2_the_headroom_floor_is_the_derived_one() -> None:
    """A claim made inside the boundary's own reproducibility is not a claim.

    0.005 = 10x the 2.02e-4 fp16/CUDA re-enrollment spread P1-C measured,
    rounded up to the next 5e-3 grid point. Pre-registered before measurement.
    """

    def at(margin: float) -> bool:
        return _trusted(
            confidence=0.98,
            state=STATE_CONFIRMED,
            identity_source=rs.IDENTITY_SOURCE_PIXEL_REID,
            identity_margin=margin,
        )

    assert not at(0.0)
    assert not at(0.000202)  # the measured reproducibility itself
    assert not at(0.0049)
    assert at(rs.OWNER_IDENTITY_MARGIN_MIN)
    assert at(0.02)


def test_ot2_the_follow_and_search_admissions_still_read_the_raw_cosine() -> None:
    """THE GAP THIS CARD DID NOT CLOSE, pinned as a positive assertion.

    Fable, OT-2 verification, item 2. The card's §3 claimed 0.65 "is never
    applied to a measured cosine". That was false the moment the overlay
    started feeding one to the whole control loop: ``follow.py`` (three sites)
    and ``search_owner.py`` still threshold ``owner.confidence`` at 0.65, and
    those two now receive P1-C's cosine.

    The concrete consequence, measured below: a calibrated gallery that says
    ``ambiguous`` — "there are two people here and I cannot tell them apart" —
    produces a cosine the identity gate REFUSES and the follow controller
    ACCEPTS. The dog declines to grant the owner band and then walks after them
    anyway.

    This is pinned rather than fixed because ``follow.py`` is DOOR-1's file
    this wave and ``search_owner.py`` is being edited concurrently too; the
    patch is in ``OT2_STATUS.md`` §10 as a named handoff. It is written as an
    assertion that the gap EXISTS (P1-C's own convention for its uncalibrated
    finding) so that the day somebody closes it, this reddens and the handoff
    gets struck rather than quietly rotting.
    """

    from parcel_robot.navigation.follow import FollowConfig
    from parcel_robot.navigation.search_owner import SearchOwnerConfig

    ambiguous = _track(
        confidence=0.85,
        state=STATE_AMBIGUOUS,
        identity_source=rs.IDENTITY_SOURCE_PIXEL_REID,
        identity_margin=0.20,
    )
    # the identity gate: not the owner
    assert not rs._owner_identity_trusted(ambiguous)
    # the two controllers: still the owner, on the raw number
    assert ambiguous.confidence >= FollowConfig().min_confidence
    assert ambiguous.confidence >= SearchOwnerConfig().owner_confidence_min

    # ... and an UNCALIBRATED claim, which is P1-C's stranger at 0.9295
    stranger = _track(
        confidence=STRANGER_AGAINST_UNCALIBRATED,
        state=STATE_CONFIRMED,
        identity_source=rs.IDENTITY_SOURCE_PIXEL_REID_UNCALIBRATED,
        identity_margin=0.02,
    )
    assert not rs._owner_identity_trusted(stranger)
    assert stranger.confidence >= FollowConfig().min_confidence

    # the seam that would close it, published by this card and unused by them
    assert rs.owner_identity_trusted is rs._owner_identity_trusted


def test_ot2_the_direction_of_the_change_is_measured_not_asserted() -> None:
    """"Strictly fewer" was a claim, and it was wrong. This is the measurement.

    Fable, OT-2 verification, item 4. The first version of this card asserted
    in three places that the new gate grants a strict subset of what HEAD
    granted. It does not: the measured arm has no floor on the cosine at all,
    so a calibrated gallery whose operating point sits below 0.65 produces
    grants HEAD refused. That is intended — it is what "retired on the cosine
    scale" MEANS — but it has to be stated as what it is.

    Reproduces HEAD's rule inline (blank id / non-numeric / non-finite are
    False, else ``confidence >= 0.65``) rather than importing it, because the
    point is to compare against a rule that no longer exists in the tree.
    """

    sources = (
        "",
        rs.IDENTITY_SOURCE_MOCAP,
        rs.IDENTITY_SOURCE_CHANNEL_PRIOR,
        rs.IDENTITY_SOURCE_PIXEL_REID,
        rs.IDENTITY_SOURCE_PIXEL_REID_UNCALIBRATED,
        "vendor_magic",
    )
    states = ("", STATE_CONFIRMED, STATE_AMBIGUOUS, "lost", STATE_SEARCHING)
    confidences = tuple(round(0.02 * i, 4) for i in range(51))
    margins = (-0.05, 0.0, 0.004, rs.OWNER_IDENTITY_MARGIN_MIN, 0.05)

    def head_rule(track: OwnerTrack) -> bool:
        if not isinstance(track.owner_id, str) or not track.owner_id.strip():
            return False
        value = track.confidence
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return False
        return math.isfinite(value) and value >= rs.OWNER_IDENTITY_CONFIDENCE_MIN

    granted: list[tuple[str, str, float, float]] = []
    refused = unchanged = 0
    for source in sources:
        for state in states:
            for confidence in confidences:
                for margin in margins:
                    track = _track(
                        confidence=confidence,
                        state=state,
                        identity_source=source,
                        identity_margin=margin,
                    )
                    now = rs._owner_identity_trusted(track)
                    before = head_rule(track)
                    if now and not before:
                        granted.append((source, state, confidence, margin))
                    elif before and not now:
                        refused += 1
                    else:
                        unchanged += 1

    assert len(sources) * len(states) * len(confidences) * len(margins) == 7650
    assert refused == 1314
    assert len(granted) == 66
    assert unchanged == 6270
    # and the 66 are one narrow shape, not a general loosening
    assert {row[0] for row in granted} == {rs.IDENTITY_SOURCE_PIXEL_REID}
    assert {row[1] for row in granted} == {STATE_CONFIRMED}
    assert max(row[2] for row in granted) < rs.OWNER_IDENTITY_CONFIDENCE_MIN
    assert min(row[3] for row in granted) >= rs.OWNER_IDENTITY_MARGIN_MIN
    # they buy a BAND, never a stop distance
    policy = rs.ReactiveSafetyPolicy()
    assert policy.owner_slow_m > policy.person_stop_m
    assert policy.person_stop_m == rs.ReactiveSafetyPolicy().person_stop_m


def test_ot2_an_unrecognised_identity_source_is_not_an_identity() -> None:
    """The one new "no", and it costs a band rather than refusing to move."""

    assert not _trusted(confidence=1.0, identity_source="vendor_magic")
    assert not _trusted(confidence=1.0, identity_source="uwb_only", state=STATE_CONFIRMED)


# ---------------------------------------------------------------------------
# R5 — the legacy path did not move
# ---------------------------------------------------------------------------

#: sha256 of the 648-case disposition matrix, captured on the PRE-OT-2 tree
#: (``scrum/20260822/task_17/OT2_STATUS.md`` row R5) before a line was edited.
PRE_OT2_DISPOSITION_SHA = "f16316b33b5c4899513a1cd1c9f628def58b10091202d1e9f4be15f30001982c"


def test_R5_the_mocap_and_legacy_paths_are_byte_identical() -> None:
    """648 reactive-safety cases over tracks with NO identity provenance.

    The matrix is 3 owner ids x 2 visibilities x 27 confidences x 2 person-
    channel states x 2 orbit flags, and it is the same script that produced
    the pinned digest on the pre-card tree.
    """

    policy = rs.ReactiveSafetyPolicy()
    confidences = [round(0.04 * i, 4) for i in range(26)] + [1.0]
    rows: list[dict[str, object]] = []
    for owner_id in ("owner-1", "", "   "):
        for visible in (True, False):
            for confidence in confidences:
                for person in (None, 1.4):
                    for orbit in (False, True):
                        observation = SimObservation(
                            timestamp=100.0,
                            robot=RobotPose(x=0.0, y=0.0, z=0.0, yaw=0.0),
                            owner=OwnerTrack(
                                owner_id=owner_id,
                                x=1.9,
                                y=0.0,
                                visible=visible,
                                confidence=confidence,
                            ),
                            nearest_obstacle_m=3.5,
                            nearest_obstacle_bearing_rad=0.0,
                            lidar_obstacles=(
                                LidarObstacle(distance_m=3.5, bearing_rad=0.0),
                            ),
                            nearest_person_m=person,
                            nearest_person_bearing_rad=(None if person is None else 0.3),
                            backend="headless_mujoco_city",
                        )
                        command, state = rs.apply_reactive_safety(
                            VelocityCommand(vx=0.6, vy=0.0, vyaw=0.0),
                            observation,
                            policy=policy,
                            owner_orbit=orbit,
                            orbit_radius_m=(1.2 if orbit else 0.0),
                            now=100.0,
                        )
                        rows.append(
                            {
                                "owner_id": owner_id,
                                "visible": visible,
                                "confidence": confidence,
                                "person": person,
                                "orbit": orbit,
                                "vx": round(command.vx, 12),
                                "vy": round(command.vy, 12),
                                "vyaw": round(command.vyaw, 12),
                                "state": state,
                            }
                        )
    blob = json.dumps(rows, sort_keys=True, separators=(",", ":")).encode()
    assert len(rows) == 648
    assert hashlib.sha256(blob).hexdigest() == PRE_OT2_DISPOSITION_SHA


def test_ot2_the_mocap_venue_says_it_is_ground_truth() -> None:
    """1.0 stays 1.0 — and now says which kind of 1.0 it is."""

    assert MOCAP_OWNER_CONFIDENCE == 1.0
    assert rs.IDENTITY_SOURCE_MOCAP in rs.CHANNEL_PRIOR_IDENTITY_SOURCES
    assert _trusted(
        confidence=MOCAP_OWNER_CONFIDENCE,
        state=MOCAP_OWNER_STATE,
        identity_source=rs.IDENTITY_SOURCE_MOCAP,
    )
    source = (REPO / "src" / "parcel_robot" / "headless_city.py").read_text()
    assert "confidence=1.0," not in source, (
        "the mocap owner emission is back to a bare literal; the venue must say "
        "whether 1.0 is a measurement or ground truth"
    )


# ---------------------------------------------------------------------------
# R6/R7 — through the runtime
# ---------------------------------------------------------------------------


def test_ot2_the_overlay_is_wired_into_the_control_loop() -> None:
    """The seam exists WHERE it has to, and nothing reads around it.

    A static check rather than a spun-up control thread, and it is the stronger
    of the two for this property: it asserts the call sits between
    ``backend.observe()`` and every downstream reader in the loop body, which a
    single timed iteration could pass while a later refactor moved it.
    """

    tree = ast.parse(RUNTIME_PATH.read_text())
    # ``_control_loop`` delegates to ``_control_loop_body`` (a concurrent card's
    # control-thread marking); take whichever of the two actually observes, so
    # this pin follows the loop rather than a name.
    loop = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef)
        and node.name in {"_control_loop", "_control_loop_body"}
        and "observation = self.backend.observe()" in ast.unparse(node)
    )
    body = ast.unparse(loop)
    assert "observation = self._ot2_apply_owner_identity(observation)" in body
    observe_at = body.index("observation = self.backend.observe()")
    overlay_at = body.index("observation = self._ot2_apply_owner_identity(observation)")
    sink_at = body.index("self._observation_sink")
    assert observe_at < overlay_at < sink_at

    # the follow/standoff consumers read the SAME track (card rule 3): the
    # overlay lands before ``follow.observe_owner`` and before the sighting
    # record, so no consumer can be looking at the mocap body while the gate
    # looks at the measured one.
    assert overlay_at < body.index("self.follow.observe_owner")
    assert overlay_at < body.index("self._record_owner_sighting")

    publish = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "_publish_camera_frame"
    )
    assert "self._ot2_note_camera_frame(frame)" in ast.unparse(publish)


def test_ot2_the_runtime_never_emits_a_constant_owner_confidence(
    runtime: RobotRuntime, script: ClipScript, calibrated_gallery: Any
) -> None:
    """R6 — the clip through ``_publish_camera_frame``. Seed S1's target.

    The audit's finding, retired on the product path: the owner confidence the
    control loop hands to the safety gate moves frame to frame, comes from a
    cosine somebody measured, and never reaches 1.0.
    """

    rows = _drive_clip(runtime, script, calibrated_gallery)
    claimed = [row for row in rows if row["state"] == STATE_CONFIRMED]
    confidences = {round(float(row["confidence"]), 6) for row in claimed}

    assert claimed, "the calibrated gallery never confirmed anybody on the clip"
    assert len(confidences) >= 5, sorted(confidences)
    # THE PRE-REGISTERED ASSERTION (PREREGISTRATION.md R6), restored. It was
    # weakened once, on a cause that was never measured; see ``_drive_clip``.
    assert max(confidences) < 1.0, sorted(confidences)
    assert 1.0 not in confidences
    # and the artefact cannot come back: nothing scored here may be a crop the
    # gallery was built from.
    assert not (ENROLLMENT_FRAME_SET & {int(row["index"]) for row in rows})
    # every confirmed frame carries a MEASURED source, never a channel prior
    assert {row["source"] for row in claimed} == {rs.IDENTITY_SOURCE_PIXEL_REID}
    # and the gate agrees with the producer, both ways
    assert all(row["trusted"] for row in claimed)
    assert not any(row["trusted"] for row in rows if row["state"] != STATE_CONFIRMED)

    snapshot = runtime.owner_identity_snapshot()
    assert snapshot is not None
    # every frame was FED (20), fewer are SCORED (the 14 held-out ones)
    assert snapshot["frames_seen"] == len(script.frames) == 20
    assert snapshot["frames_seen"] > len(rows) == 14
    assert snapshot["owner_claims"] >= len(claimed)
    assert snapshot["errors"] == 0
    assert 0.0 < float(snapshot["identity_confidence"]) < 1.0


def test_ot2_an_unclaimed_frame_degrades_to_searching_and_never_guesses(
    runtime: RobotRuntime, script: ClipScript, calibrated_gallery: Any
) -> None:
    """R7 — after a loss the IDENTITY is absent, not stale. Never the last number.

    Note what is asserted and what is deliberately NOT. The identity fields go
    to their "I do not know" values. ``visible`` does not: it is carried
    through from the backend, because in ``apply_reactive_safety`` the owner is
    appended to the people list only ``if observation.owner.visible``, so
    clearing it would delete the person from the gate rather than demote their
    band. The first version of this test asserted ``visible is False`` and was
    therefore pinning the defect in place (Fable, OT-2 verification, item 1).
    """

    rows = _drive_clip(runtime, script, calibrated_gallery)
    unclaimed = [row for row in rows if row["state"] != STATE_CONFIRMED]
    assert unclaimed, "the clip never loses the owner; the row is untestable"
    for row in unclaimed:
        assert row["confidence"] == 0.0, row
        assert row["state"] == STATE_SEARCHING, row
        assert row["margin"] == 0.0, row
        assert row["trusted"] is False, row
        # presence survives the loss of identity, and is the backend's answer
        assert row["visible"] is True, row


def test_ot2_a_stale_track_stops_being_an_identity(
    runtime: RobotRuntime, script: ClipScript, calibrated_gallery: Any
) -> None:
    """Freshness is part of identity: an owner seen ten seconds ago is not seen."""

    _drive_clip(runtime, script, calibrated_gallery)
    assert runtime.owner_track is not None or runtime._ot2_owner_track is None
    # age the published answer past the runtime's own telemetry budget
    runtime._ot2_owner_track_at = time.monotonic() - (runtime.telemetry_stale_s + 1.0)
    assert runtime.owner_track is None
    observed = runtime._ot2_apply_owner_identity(_observation())
    assert observed.owner.confidence == 0.0
    assert observed.owner.state == STATE_SEARCHING
    assert not rs._owner_identity_trusted(observed.owner)


def test_ot2_a_degraded_owner_still_gets_a_persons_clearance(
    runtime: RobotRuntime, script: ClipScript, calibrated_gallery: Any
) -> None:
    """THE SAFETY ROW. A dog that cannot tell who you are must not walk into you.

    Fable, OT-2 verification, item 1, and it is the correction this pass exists
    for. The degrade used to set ``visible=False``, and ``apply_reactive_safety``
    appends the owner to its people list only ``if observation.owner.visible`` —
    so "I have lost the identity" was silently spelled "there is nobody there",
    which costs the person their CLEARANCE and not merely the relaxed band.

    Measured at 0.7 m of owner centre distance (0.15 m of clearance once the
    0.55 m owner collision envelope is removed, against a 1.2 m person stop):

    * the identity gate refuses the relaxed band — correct, nobody knows who
      this is;
    * the reactive gate still returns ``stopped`` and zero translation.

    Seed to reproduce the defect: put ``visible=False`` back in the not-fresh
    branch of ``_ot2_apply_owner_identity``.
    """

    ingress = _PixelIngress()
    runtime.attach_camera_ingress(ingress, start=False)
    runtime.install_owner_tracker(
        OwnerTracker(gallery=calibrated_gallery, embed_fn=histogram_embed_image)
    )
    # no frame has ever been published: the tracker is installed and has no
    # claim, which is exactly the reacquisition state R7 describes.
    close = SimObservation(
        timestamp=100.0,
        robot=RobotPose(x=0.0, y=0.0, yaw=0.0),
        owner=OwnerTrack(
            owner_id="owner-1",
            x=0.7,
            y=0.0,
            visible=True,
            confidence=MOCAP_OWNER_CONFIDENCE,
            state=MOCAP_OWNER_STATE,
            identity_source=rs.IDENTITY_SOURCE_MOCAP,
        ),
        nearest_obstacle_m=6.0,
        nearest_obstacle_bearing_rad=0.0,
        lidar_obstacles=(LidarObstacle(distance_m=6.0, bearing_rad=0.0),),
        backend="fake",
    )
    degraded = runtime._ot2_apply_owner_identity(close)

    assert degraded.owner.confidence == 0.0
    assert degraded.owner.state == STATE_SEARCHING
    assert not rs._owner_identity_trusted(degraded.owner)
    # the person is still IN the gate's world
    assert degraded.owner.visible is True

    policy = rs.ReactiveSafetyPolicy()
    command, state = rs.apply_reactive_safety(
        VelocityCommand(vx=0.6, vy=0.0, vyaw=0.0),
        degraded,
        policy=policy,
        now=100.0,
    )
    assert state == "stopped", state
    assert (command.vx, command.vy) == (0.0, 0.0)
    # and the band it lost is the relaxed one, not the stop ring
    assert rs._owner_comfort_band_m(degraded, policy) == policy.person_slow_m
    assert policy.person_stop_m == 1.2
    assert 0.7 - policy.owner_collision_envelope_m == pytest.approx(0.15)


def test_ot2_without_a_tracker_the_observation_is_the_same_object(
    runtime: RobotRuntime,
) -> None:
    """Flag-off identity: not equivalent, IDENTICAL. And no snapshot key."""

    observation = _observation()
    assert runtime._ot2_apply_owner_identity(observation) is observation
    assert runtime.owner_identity_snapshot() is None
    assert runtime.owner_track is None


def test_ot2_an_unenrolled_tracker_claims_nobody(
    runtime: RobotRuntime, script: ClipScript
) -> None:
    """P1-C's "zero owner claims without a gallery", holding at runtime."""

    ingress = _PixelIngress()
    runtime.attach_camera_ingress(ingress, start=False)
    runtime.install_owner_tracker(OwnerTracker(gallery=None, embed_fn=histogram_embed_image))
    for _index, rgb, frame in iter_clip(script):
        ingress.rgb = rgb
        runtime._publish_camera_frame(frame)
        observed = runtime._ot2_apply_owner_identity(_observation())
        assert observed.owner.confidence == 0.0
        assert not rs._owner_identity_trusted(observed.owner)
    snapshot = runtime.owner_identity_snapshot()
    assert snapshot is not None
    assert snapshot["owner_claims"] == 0


def test_ot2_no_pixels_is_a_degrade_and_not_a_claim(
    runtime: RobotRuntime, script: ClipScript, calibrated_gallery: Any
) -> None:
    """The gap this card cannot close, pinned as a fact rather than left implicit.

    ``CameraDetectionFrame`` carries no image and ``ingress.py`` is P1-B's file,
    so an ingress with no ``latest_rgb()`` yields no identity at all. The
    correct behaviour is a degrade — the robot cannot see who that is — and NOT
    a fallback to the simulator's ground-truth body.
    """

    class _NoPixels:
        def stop(self) -> None:
            pass

    runtime.attach_camera_ingress(_NoPixels(), start=False)
    runtime.install_owner_tracker(
        OwnerTracker(gallery=calibrated_gallery, embed_fn=histogram_embed_image)
    )
    for _index, _rgb, frame in iter_clip(script):
        runtime._publish_camera_frame(frame)
        observed = runtime._ot2_apply_owner_identity(_observation())
        assert observed.owner.confidence == 0.0
        assert observed.owner.state == STATE_SEARCHING
    assert runtime.owner_identity_snapshot()["owner_claims"] == 0


def test_ot2_a_throwing_tracker_costs_the_identity_and_not_the_eye(
    runtime: RobotRuntime, script: ClipScript
) -> None:
    """A broken producer degrades to "I cannot see who that is". Never a crash."""

    class _Boom:
        gallery = None

        def update(self, frame: Any, **kwargs: Any) -> Any:
            raise RuntimeError("encoder fell over")

    ingress = _PixelIngress()
    runtime.attach_camera_ingress(ingress, start=False)
    runtime.install_owner_tracker(_Boom())
    for _index, rgb, frame in iter_clip(script):
        ingress.rgb = rgb
        runtime._publish_camera_frame(frame)
    snapshot = runtime.owner_identity_snapshot()
    assert snapshot is not None
    assert snapshot["errors"] > 0
    assert snapshot["owner_claims"] == 0
    observed = runtime._ot2_apply_owner_identity(_observation())
    assert observed.owner.confidence == 0.0
    assert not rs._owner_identity_trusted(observed.owner)


def test_ot2_the_presence_seam_reads_the_measured_track(
    runtime: RobotRuntime, script: ClipScript, calibrated_gallery: Any
) -> None:
    """P2-B's greeting stops running on the mocap body's flat 1.0.

    ``owner_presence_sample`` was written as a drop-in seam for exactly this
    card and needed no edit — it reaches for ``self.owner_track`` and gets one
    now. The property that matters: the confidence it reports is the measured
    cosine, and the source it stamps is the pixel one.
    """

    from parcel_robot.realtime.whisperer import OWNER_SOURCE_MOCAP, OWNER_SOURCE_PIXELS

    before = runtime.owner_presence_sample(_observation(), time.monotonic())
    assert before.source == OWNER_SOURCE_MOCAP
    assert before.confidence == 1.0

    _drive_clip(runtime, script, calibrated_gallery)
    after = runtime.owner_presence_sample(_observation(), time.monotonic())
    assert after.source == OWNER_SOURCE_PIXELS
    assert after.confidence < 1.0
