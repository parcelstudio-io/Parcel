"""Card A8 — FOLLOW-COMPOSE: the tracker gets a caller, Follow gets a HOLD.

WHAT IS BEING PROVEN, AND WITH WHAT
-----------------------------------
The owner chose option (a) — Follow is IN M1 (``CLAUDE_RESPONSE.md`` addendum
A12) — and the owner's OFFLINE FLOOR names it explicitly: *"Sorry but I am
currently offline so all I can do is follow you until we are connected to the
internet."*  Addendum A3 then measured why that floor was not buildable:
``install_owner_tracker`` had **no product caller**, ``uwb/`` is a declared sim
stand-in, and the pixel/range association had no synchronization contract.
This file is the proof for the five things card A8 builds:

1.  the tracker is installed **through the product route** (a config knob, an
    encoder from the camera venue, a gallery from disk) — ``off`` builds
    nothing and a refused knob is loud and additive;
2.  the follow target's bearing/range and identity come from ONE carrier
    epoch, and a mixed-epoch or stale pair is a TYPED refusal, never a guess;
3.  two plausible owners ⇒ HOLD + one honest sentence + **no track switch**;
    loss ⇒ HOLD inside a bounded reacquisition window;
4.  follow's commanded speed obeys the commissioned reactive gate — A2's ONE
    clearance authority — and A8 adds no clearance number of its own;
5.  A3's discontinuity latch and A6's local STOP both beat Follow, through the
    routes they already own rather than through parallel flags.

Plus the UWB decision, taken FROM MEASUREMENT: a deterministic two-person
crossing corpus, the real ``OwnerTracker`` over it, and the shipped UWB noise
model asked whether a range beacon would have disambiguated what appearance
could not.

WHAT IS NOT PROVEN HERE — ALL OF IT BOX-DAY
-------------------------------------------
No robot and no camera exist on this host (only the reSpeaker XVF3800 mic
array).  The identity arm therefore runs P1-C's SYNTHESIZED two-person clip
through P1-C's 72-dimension histogram fixture encoder: these rows measure the
MECHANISM — margin gate, refusal direction, HOLD composition — and they are
not an identity performance number.  The real-encoder numbers quoted below are
P1-C's own published SigLIP-2 measurements, cited and never re-derived.  The
UWB arm's noise model is zero-mean Gaussian with **no NLOS bias term**, so its
rows are an optimistic bound on real indoor ranging.  Real camera identity,
mounted tracking, clothing/lighting, and the ENABLE decision itself are the
box-day study (F5, HLD Gate 6) and nothing here substitutes for them.
"""

from __future__ import annotations

import copy
import dataclasses
import hashlib
import importlib
import math
import random
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest

from parcel_robot.audio.devices import AudioDeviceStatus
from parcel_robot.audio.stop_hotword import StopHotwordConfig, StopLatch, StopSpot
from parcel_robot.authority import DEFAULT_SAFETY_ENVELOPE, ClearanceProfile
from parcel_robot.backends.base import (
    LidarObstacle,
    OwnerTrack,
    RobotPose,
    SimObservation,
)
from parcel_robot.contracts.evidence_header import EvidenceHeaderV1
from parcel_robot.contracts.navigation_snapshot_v2 import (
    RANGE_CONVENTION_BODY_SURFACE,
    NavigationSnapshotV2,
)
from parcel_robot.localization.discontinuity import ArmingLatch, BodySignals
from parcel_robot.localization.installer import LocalizationInstallation
from parcel_robot.models import VelocityCommand
from parcel_robot.navigation import follow_compose as fc
from parcel_robot.navigation.follow import FollowConfig, FollowOwnerController
from parcel_robot.navigation.reactive_safety import apply_reactive_safety
from parcel_robot.observation.assembler import SnapshotAssembler
from parcel_robot.observation.sources import CarrierObservationSource
from parcel_robot.owner_tracking import install as ot_install
from parcel_robot.owner_tracking.gallery import build_gallery, save_gallery
from parcel_robot.owner_tracking.synthetic_clip import (
    ClipScript,
    build_default_script,
    crop_for,
    detection_frame,
    histogram_embed_image,
    project,
    render_frame,
)
from parcel_robot.owner_tracking.tracker import OwnerTracker
from parcel_robot.runtime import (
    SAFETY_SOURCE_PANEL,
    SAFETY_SOURCE_VOICE,
    RobotRuntime,
)
from parcel_robot.uwb.model import GroundTruthUwb, UwbNoiseModel
from parcel_robot.uwb.noise import UwbNoiseConfig

REPO = Path(__file__).resolve().parents[1]

#: P1-C's enrollment/scoring split, quoted from the clip header so no measured
#: cosine is ever a crop against itself.
ENROLLMENT_FRAMES = tuple(range(6))
SCORED_FRAMES = tuple(range(6, 20))
#: The clip's own scripted events.
CROSSING_FRAMES = (8, 9, 10, 11)
OCCLUSION_FRAMES = (13, 14, 15, 16)

#: P1-C's REAL-ENCODER numbers (``P1C_STATUS.md`` §0 / ``test_p1c_real_siglip2``),
#: quoted as inputs and never re-derived on this host.
REAL_ENCODER_OWNER_STRANGER_SEPARATION = 0.05
REAL_ENCODER_STRANGER_UNCALIBRATED = 0.9295

#: How many noise draws each beacon row averages.  Large enough that a rate is
#: stable to ~0.02, small enough that the suite stays a commit-tier suite.
BEACON_SEEDS = 200


# ===========================================================================
# fixtures — the product's own objects, built the way the product builds them
# ===========================================================================
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
        self.observation = observation

    def observe(self) -> SimObservation:
        return self.observation

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
    """A camera venue that carries an encoder — P1-B's ``embed_fn`` seam.

    ``embedder.from_ingress`` is structural on purpose (it must not pin P1-B's
    type), so this object exercises the same resolution path a real ingress
    with a loaded SigLIP-2 session takes.
    """

    embed_model = "fixture:histogram_embed_image/v1"

    def __init__(self) -> None:
        self.rgb: Any = None
        self.embed_fn = histogram_embed_image

    def latest_rgb(self) -> Any:
        return self.rgb

    def stop(self) -> None:
        pass


def _observation(
    *,
    timestamp: float | None = None,
    owner_visible: bool = True,
    owner_state: str = "confirmed",
    owner_confidence: float = 0.9,
    owner_xy: tuple[float, float] = (3.0, 0.0),
    obstacle_m: float | None = 4.0,
) -> SimObservation:
    obstacles = ()
    if obstacle_m is not None:
        obstacles = (LidarObstacle(distance_m=obstacle_m, bearing_rad=0.0, obstacle_id="wall"),)
    return SimObservation(
        timestamp=time.monotonic() if timestamp is None else timestamp,
        robot=RobotPose(x=0.0, y=0.0, yaw=0.0),
        owner=OwnerTrack(
            owner_id="owner-1",
            x=owner_xy[0],
            y=owner_xy[1],
            visible=owner_visible,
            confidence=owner_confidence,
            state=owner_state,
            identity_source="mocap",
            identity_margin=0.2,
        ),
        nearest_obstacle_m=obstacle_m,
        nearest_obstacle_bearing_rad=None if obstacle_m is None else 0.0,
        nearest_obstacle_id=None if obstacle_m is None else "wall",
        lidar_obstacles=obstacles,
        backend="fake",
    )


def _config(tmp_path: Path, tracker_block: str = "") -> Path:
    """A standalone robot config — the shape ``--config`` hands the panel.

    Deliberately NOT a profile overlay: ``owner_follow.tracker`` is reachable
    from a config file today and is NOT reachable from an overlay on the
    SHA-locked base, and both halves of that are asserted below.
    """

    tmp_path.mkdir(parents=True, exist_ok=True)
    path = tmp_path / "robot.yaml"
    body = tracker_block or "  behind_distance_m: 1.9\n"
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
owner_follow:
{body}
""",
        encoding="utf-8",
    )
    return path


@pytest.fixture
def runtime(tmp_path: Path) -> Iterator[RobotRuntime]:
    made = RobotRuntime(_config(tmp_path / "cfg"), _Backend(_observation()), audio_status=_audio())
    yield made
    made.close()


@pytest.fixture(scope="module")
def script() -> ClipScript:
    return ClipScript.from_mapping(build_default_script())


@pytest.fixture(scope="module")
def gallery(script: ClipScript):
    """The enrollment the OWNER did: his own crops, the other person as negatives."""

    return build_gallery(
        [histogram_embed_image(crop_for(script, i, "owner")) for i in ENROLLMENT_FRAMES],
        model="fixture:histogram_embed_image/v1",
        negatives=[histogram_embed_image(crop_for(script, i, "other")) for i in ENROLLMENT_FRAMES],
    )


@pytest.fixture
def gallery_file(gallery, tmp_path: Path) -> Path:
    return save_gallery(gallery, tmp_path / "gallery.json")


def _snapshot(observation: SimObservation) -> NavigationSnapshotV2:
    """One tick through the PRODUCT's own snapshot source and assembler."""

    source = CarrierObservationSource(
        lambda: observation,
        range_convention=RANGE_CONVENTION_BODY_SURFACE,
        footprint_radius_m=0.31,
    )
    built = source.snapshot_for(observation)
    return SnapshotAssembler().review(built, now_monotonic_ns=built.assembled_monotonic_ns)


def _reheader(header: EvidenceHeaderV1, **changes: Any) -> EvidenceHeaderV1:
    return dataclasses.replace(header, **changes)


def _reload(path: Path, module: Any) -> None:
    """Reload ``module`` from source, defeating the bytecode cache.

    THE DEFECT THIS EXISTS FOR, and it is worth naming because it made a green
    suite lie for one run: CPython invalidates a ``.pyc`` on (mtime, size), and
    the seeds below swap ``min`` for ``max`` — three bytes for three bytes,
    inside the same second. The restore therefore left a POISONED cache whose
    bytecode still carried the mutant while the file on disk read correctly, so
    the next test in the file measured the seed instead of the product.
    """

    cache = path.parent / "__pycache__"
    if cache.is_dir():
        for stale in cache.glob(f"{path.stem}.*.pyc"):
            stale.unlink()
    importlib.invalidate_caches()
    importlib.reload(module)


@contextmanager
def _mutated_source(path: Path, old: str, new: str, module: Any) -> Iterator[None]:
    """Seed a real defect into a product FILE and reload it, sha-restored.

    Both files this is used on are import-time-pure leaves, which is what makes
    reloading them safe: no thread, no socket, no runtime object is built at
    import.  The sha is checked before AND after, so a restore that silently
    failed reddens instead of leaving a mutant in the tree.
    """

    original = path.read_text(encoding="utf-8")
    digest = hashlib.sha256(original.encode("utf-8")).hexdigest()
    assert original.count(old) == 1, f"seed anchor is not unique in {path.name}: {old!r}"
    try:
        path.write_text(original.replace(old, new), encoding="utf-8")
        _reload(path, module)
        yield
    finally:
        path.write_text(original, encoding="utf-8")
        restored = hashlib.sha256(path.read_text(encoding="utf-8").encode("utf-8")).hexdigest()
        assert restored == digest, f"{path.name} was not restored byte-for-byte"
        _reload(path, module)


FOLLOW_COMPOSE_PATH = REPO / "src" / "parcel_robot" / "navigation" / "follow_compose.py"
INSTALL_PATH = REPO / "src" / "parcel_robot" / "owner_tracking" / "install.py"


# ===========================================================================
# 1 · the tracker's PRODUCT installation
# ===========================================================================
def test_the_installer_now_has_a_product_caller() -> None:
    """Addendum A3's finding, closed: a grep that used to find only a docstring.

    The assertion is on the CALL, not on the outcome, because "a composition
    root nothing calls" is exactly the defect and an outcome test would pass on
    a build where the test itself was the only caller.
    """

    source = (REPO / "src" / "parcel_robot" / "runtime.py").read_text(encoding="utf-8")
    calls = [
        line.strip()
        for line in source.splitlines()
        if "self.install_owner_tracker(" in line and not line.strip().startswith("#")
    ]
    assert calls, "install_owner_tracker still has no product caller"
    assert "_build_owner_tracker" in source
    builds = [
        line.strip()
        for line in source.splitlines()
        if "self._build_owner_tracker(" in line and not line.strip().startswith("#")
    ]
    assert len(builds) == 2, (
        f"expected exactly two build sites (construction + camera attach), got {builds}"
    )


def test_off_builds_nothing_at_all(tmp_path: Path) -> None:
    """``off`` is not a disabled tracker — it is no tracker, and no snapshot key."""

    config = _config(tmp_path / "off", "  tracker:\n    mode: off\n")
    made = RobotRuntime(config, _Backend(_observation()), audio_status=_audio())
    try:
        assert made._ot2_owner_tracker is None
        assert made._owner_tracker_detail == "off (owner_follow.tracker.mode=off)"
        # R1 discipline: a flag-off run is byte-identical on the wire.
        assert made.owner_identity_snapshot() is None
        # The identity seam returns the SAME OBJECT, not an equal copy.
        observation = _observation()
        assert made._ot2_apply_owner_identity(observation) is observation
        # Attaching a camera does not sneak one in either.
        made.attach_camera_ingress(_PixelIngress(), start=False)
        assert made._ot2_owner_tracker is None
    finally:
        made.close()


def test_a_bare_yaml_off_is_the_boolean_false_and_still_means_off(tmp_path: Path) -> None:
    """YAML 1.1 resolves a bare ``off`` to False. The knob says so rather than trapping."""

    made = RobotRuntime(
        _config(tmp_path / "yamloff", "  tracker:\n    mode: off\n"),
        _Backend(_observation()),
        audio_status=_audio(),
    )
    try:
        assert made._owner_tracker_detail.startswith("off (")
    finally:
        made.close()
    assert ot_install.OwnerTrackerSettings.from_mapping({"mode": False}).mode == "off"
    with pytest.raises(TypeError, match="quote it"):
        ot_install.OwnerTrackerSettings.from_mapping({"mode": True})


def test_a_refused_config_is_loud_and_additive(tmp_path: Path) -> None:
    """A typo'd key refuses BY NAME, emits at error, and changes nothing else."""

    config = _config(tmp_path / "bad", "  tracker:\n    moode: gallery\n")
    made = RobotRuntime(config, _Backend(_observation()), audio_status=_audio())
    try:
        assert made._owner_tracker_detail.startswith("refused: unknown owner_follow.tracker")
        assert "moode" in made._owner_tracker_detail
        assert made._ot2_owner_tracker is None
        errors = [
            row
            for row in made.snapshot().get("events", [])
            if row.get("level") == "error" and "Owner tracker" in str(row.get("text", ""))
        ]
        assert errors, "a refused tracker config must be LOUD"
        # Additive: the panel latch, the reactive gate and the follow floors are
        # exactly what they were.
        assert made.arbiter.emergency_stopped is False
        assert made.follow.config.obstacle_stop_m == pytest.approx(0.65)
        assert made.reactive_safety_policy.obstacle_stop_m == pytest.approx(0.65)
    finally:
        made.close()


def test_an_unknown_mode_and_a_bad_type_refuse_by_name() -> None:
    with pytest.raises(ValueError, match="owner_follow.tracker.mode must be one of"):
        ot_install.OwnerTrackerSettings.from_mapping({"mode": "uwb"})
    with pytest.raises(TypeError, match="gallery_path must be a string"):
        ot_install.OwnerTrackerSettings.from_mapping({"gallery_path": 7})
    with pytest.raises(TypeError, match="require_calibrated must be a boolean"):
        ot_install.OwnerTrackerSettings.from_mapping({"require_calibrated": "yes"})
    with pytest.raises(TypeError, match="must be a mapping"):
        ot_install.OwnerTrackerSettings.from_mapping(["mode"])


def test_the_tracker_installs_through_the_camera_venue(tmp_path: Path, gallery_file: Path) -> None:
    """The product route end to end: knob -> camera venue -> encoder -> gallery."""

    config = _config(
        tmp_path / "on", f"  tracker:\n    mode: gallery\n    gallery_path: {gallery_file}\n"
    )
    made = RobotRuntime(config, _Backend(_observation()), audio_status=_audio())
    try:
        # Before a camera venue: nothing installed, and the reason names the gap.
        assert made._ot2_owner_tracker is None
        assert "no encoder resolved" in made._owner_tracker_detail
        made.attach_camera_ingress(_PixelIngress(), start=False)
        assert isinstance(made._ot2_owner_tracker, OwnerTracker)
        assert "calibrated=True" in made._owner_tracker_detail
        snapshot = made.owner_identity_snapshot()
        assert snapshot is not None and snapshot["gallery_threshold"] > 0.0
        # And a second attach does not replace a working tracker.
        installed = made._ot2_owner_tracker
        made.attach_camera_ingress(_PixelIngress(), start=False)
        assert made._ot2_owner_tracker is installed
    finally:
        made.close()


def test_an_uncalibrated_gallery_is_refused_by_default(tmp_path: Path, script: ClipScript) -> None:
    """P1-C's measured reason: the stranger scored 0.9295 against an uncalibrated
    boundary, which is above the reactive gate's 0.65 floor."""

    uncalibrated = build_gallery(
        [histogram_embed_image(crop_for(script, i, "owner")) for i in ENROLLMENT_FRAMES],
        model="fixture:histogram_embed_image/v1",
    )
    assert uncalibrated.calibrated is False
    path = save_gallery(uncalibrated, tmp_path / "uncal.json")
    settings = ot_install.OwnerTrackerSettings(mode="gallery", gallery_path=str(path))
    build = ot_install.build_owner_tracker(settings, ingress=_PixelIngress())
    assert build.tracker is None and build.refused is True
    assert "UNCALIBRATED" in build.detail
    assert str(REAL_ENCODER_STRANGER_UNCALIBRATED) in build.detail
    # An operator may still say so out loud, and only that way.
    relaxed = dataclasses.replace(settings, require_calibrated=False)
    assert ot_install.build_owner_tracker(relaxed, ingress=_PixelIngress()).tracker is not None


def test_a_gallery_from_another_encoder_is_refused(tmp_path: Path, gallery) -> None:
    """A cosine across two encoders is not a cosine."""

    foreign = dataclasses.replace(gallery, model="siglip2-b16/fp16")
    path = save_gallery(foreign, tmp_path / "foreign.json")
    build = ot_install.build_owner_tracker(
        ot_install.OwnerTrackerSettings(mode="gallery", gallery_path=str(path)),
        ingress=_PixelIngress(),
    )
    assert build.tracker is None and build.refused is True
    assert "not a cosine" in build.detail


def test_a_missing_gallery_degrades_rather_than_raising(tmp_path: Path) -> None:
    build = ot_install.build_owner_tracker(
        ot_install.OwnerTrackerSettings(mode="gallery", gallery_path=str(tmp_path / "nope.json")),
        ingress=_PixelIngress(),
    )
    assert build.tracker is None and build.refused is True
    assert "no enrolled gallery" in build.detail


def test_the_installer_seeded_red(tmp_path: Path, gallery_file: Path) -> None:
    """Seeded-RED: an installer that installs an uncalibrated gallery anyway."""

    settings = ot_install.OwnerTrackerSettings(mode="gallery", gallery_path=str(gallery_file))
    with _mutated_source(
        INSTALL_PATH,
        "    if settings.require_calibrated and not gallery.calibrated:",
        "    if False and settings.require_calibrated and not gallery.calibrated:",
        ot_install,
    ):
        mutant = importlib.import_module("parcel_robot.owner_tracking.install")
        uncal = dataclasses.replace(settings, require_calibrated=True)
        # The calibrated gallery still installs, so the seed is aimed at the
        # guard rather than at the happy path — which is what makes it a seed.
        assert mutant.build_owner_tracker(uncal, ingress=_PixelIngress()).tracker is not None
        source = INSTALL_PATH.read_text(encoding="utf-8")
        assert "if False and settings.require_calibrated" in source
    assert "if False" not in INSTALL_PATH.read_text(encoding="utf-8")


# ===========================================================================
# 2 · synchronized pixel/range — ONE carrier epoch or a typed refusal
# ===========================================================================
def test_a_single_epoch_snapshot_yields_a_target() -> None:
    snapshot = _snapshot(_observation())
    assert fc.owner_range_sync_reasons(snapshot) == ()
    assert snapshot.translation_allowed is True


def test_a_mixed_epoch_pair_is_a_typed_refusal() -> None:
    """The owner channel from one process epoch, the scan from another."""

    snapshot = _snapshot(_observation())
    mixed = dataclasses.replace(
        snapshot,
        owner=dataclasses.replace(
            snapshot.owner, header=_reheader(snapshot.owner.header, process_epoch=9)
        ),
    )
    reasons = fc.owner_range_sync_reasons(mixed)
    assert fc.REASON_MIXED_EPOCH in reasons, reasons
    composer = fc.FollowComposer(FollowOwnerController(), reacquire_window_s=3.0)
    composer.follower.start()
    decision = composer.step(mixed, now=1.0)
    assert decision.hold == fc.HOLD_UNSYNCHRONIZED
    assert decision.line == fc.UNSYNCHRONIZED_EVIDENCE_LINE
    assert decision.command == VelocityCommand()
    assert fc.REASON_MIXED_EPOCH in decision.reasons


def test_a_capture_skew_wider_than_the_tighter_ttl_is_a_typed_refusal() -> None:
    """The bound is DERIVED — ``min`` of the two producers' own TTLs, no new number."""

    snapshot = _snapshot(_observation())
    bound = min(snapshot.owner.header.max_age_ns, snapshot.traversability.header.max_age_ns)
    inside = dataclasses.replace(
        snapshot,
        owner=dataclasses.replace(
            snapshot.owner,
            header=_reheader(
                snapshot.owner.header,
                capture_monotonic_ns=snapshot.owner.header.capture_monotonic_ns + bound,
            ),
        ),
    )
    assert fc.REASON_CAPTURE_SKEW not in fc.owner_range_sync_reasons(inside)
    outside = dataclasses.replace(
        snapshot,
        owner=dataclasses.replace(
            snapshot.owner,
            header=_reheader(
                snapshot.owner.header,
                capture_monotonic_ns=snapshot.owner.header.capture_monotonic_ns + bound + 1,
            ),
        ),
    )
    assert fc.REASON_CAPTURE_SKEW in fc.owner_range_sync_reasons(outside)


def test_a_stale_channel_is_a_typed_refusal() -> None:
    snapshot = _snapshot(_observation())
    stale_owner = dataclasses.replace(
        snapshot,
        owner=dataclasses.replace(
            snapshot.owner,
            header=_reheader(
                snapshot.owner.header,
                transport_age_ns=snapshot.owner.header.max_age_ns + 1,
            ),
        ),
    )
    assert fc.REASON_OWNER_STALE in fc.owner_range_sync_reasons(stale_owner)
    stale_scan = dataclasses.replace(
        snapshot,
        traversability=dataclasses.replace(
            snapshot.traversability,
            header=_reheader(
                snapshot.traversability.header,
                transport_age_ns=snapshot.traversability.header.max_age_ns + 1,
            ),
        ),
    )
    assert fc.REASON_SCAN_STALE in fc.owner_range_sync_reasons(stale_scan)


def test_the_assemblers_own_refusal_is_carried_not_replaced() -> None:
    """A8 is ADDITIVE to the spine's fail-closed controls, never a substitute."""

    snapshot = dataclasses.replace(_snapshot(_observation()), health_reasons=("scan:stale",))
    reasons = fc.owner_range_sync_reasons(snapshot)
    assert reasons[0] == "scan:stale", reasons


def test_the_sync_check_seeded_red() -> None:
    """Seeded-RED: a bound taken from the LOOSER of the two TTLs."""

    snapshot = _snapshot(_observation())
    tight = min(snapshot.owner.header.max_age_ns, snapshot.traversability.header.max_age_ns)
    skewed = dataclasses.replace(
        snapshot,
        owner=dataclasses.replace(
            snapshot.owner,
            header=_reheader(
                snapshot.owner.header,
                max_age_ns=snapshot.owner.header.max_age_ns * 4,
                capture_monotonic_ns=snapshot.owner.header.capture_monotonic_ns + tight * 2,
            ),
        ),
    )
    assert fc.REASON_CAPTURE_SKEW in fc.owner_range_sync_reasons(skewed)
    with _mutated_source(
        FOLLOW_COMPOSE_PATH,
        "    bound_ns = min(owner.max_age_ns, scan.max_age_ns)",
        "    bound_ns = max(owner.max_age_ns, scan.max_age_ns)",
        fc,
    ):
        mutant = importlib.import_module("parcel_robot.navigation.follow_compose")
        assert mutant.REASON_CAPTURE_SKEW not in mutant.owner_range_sync_reasons(skewed)


# ===========================================================================
# 3 · ambiguity ⇒ HOLD + the canned line + NO track switch; loss ⇒ HOLD
# ===========================================================================
def _ambiguous(snapshot: NavigationSnapshotV2) -> NavigationSnapshotV2:
    return dataclasses.replace(
        snapshot,
        owner=dataclasses.replace(
            snapshot.owner, state="ambiguous", confidence=0.0, ambiguity_reason="ambiguous_margin"
        ),
    )


def test_two_plausible_owners_hold_and_say_one_sentence() -> None:
    follower = FollowOwnerController()
    follower.start()
    composer = fc.FollowComposer(follower, reacquire_window_s=3.0)
    decision = composer.step(_ambiguous(_snapshot(_observation())), now=1.0)
    assert decision.hold == fc.HOLD_AMBIGUOUS
    assert decision.line == fc.AMBIGUOUS_OWNER_LINE
    assert decision.command == VelocityCommand()
    assert decision.decision.state == "holding"
    assert "ambiguous_margin" in decision.reasons[0]


def test_an_ambiguous_frame_never_reaches_the_controllers_motion_history() -> None:
    """ "No track switch" made structural: the controller is NOT asked.

    A HOLD that still fed the ambiguous track to ``follow.step`` would leave the
    heading filter anchored on a person who may not be the owner, and the next
    confident frame would inherit it.
    """

    follower = FollowOwnerController()
    follower.start()
    composer = fc.FollowComposer(follower, reacquire_window_s=3.0)
    good = _snapshot(_observation(owner_xy=(3.0, 0.0)))
    composer.step(good, now=1.0)
    anchored = follower.heading_snapshot(now=1.0)

    calls: list[Any] = []
    original = follower.step
    follower.step = lambda *a, **k: (calls.append(a), original(*a, **k))[1]  # type: ignore[method-assign]
    decision = composer.step(_ambiguous(_snapshot(_observation(owner_xy=(-3.0, 4.0)))), now=1.25)
    follower.step = original  # type: ignore[method-assign]

    assert calls == [], "the controller was consulted on an ambiguous frame"
    assert decision.hold == fc.HOLD_AMBIGUOUS
    after = follower.heading_snapshot(now=1.25)
    assert after["owner_id"] == anchored["owner_id"]
    assert after["heading_rad"] == anchored["heading_rad"]
    assert after["track_status"] == anchored["track_status"]


def test_loss_holds_inside_a_bounded_reacquisition_window() -> None:
    follower = FollowOwnerController()
    follower.start()
    composer = fc.FollowComposer(follower, reacquire_window_s=3.0)
    composer.step(_snapshot(_observation()), now=10.0)
    lost = _snapshot(_observation(owner_visible=False, owner_state="lost"))
    first = composer.step(lost, now=10.5)
    assert first.hold == fc.HOLD_LOST
    assert first.line == fc.LOST_OWNER_LINE
    assert first.command == VelocityCommand()
    assert first.reacquire_remaining_s == pytest.approx(2.5)
    # The window runs from the last CONFIRMED sighting and does not restart.
    later = composer.step(lost, now=12.0)
    assert later.reacquire_remaining_s == pytest.approx(1.0)
    closed = composer.step(lost, now=99.0)
    assert closed.reacquire_remaining_s == pytest.approx(0.0)
    # Reacquisition is allowed: one confident frame ends the hold.
    back = composer.step(_snapshot(_observation()), now=99.5)
    assert back.hold == fc.HOLD_NONE
    assert composer.last_confirmed_s == pytest.approx(99.5)


def test_loss_does_not_veto_the_controller_and_ambiguity_does() -> None:
    """The two holds are different on purpose, and the difference is the reason.

    A lost owner already produces a zero command AND the ``lost`` state string
    the runtime's owner-search route keys on, so vetoing it would replace a
    working reacquisition route with a second one.
    """

    assert fc.HOLD_AMBIGUOUS in fc.FOLLOW_HOLD_VETOES
    assert fc.HOLD_UNSYNCHRONIZED in fc.FOLLOW_HOLD_VETOES
    assert fc.HOLD_LATCHED in fc.FOLLOW_HOLD_VETOES
    assert fc.HOLD_LOST not in fc.FOLLOW_HOLD_VETOES


def test_every_hold_carries_a_sentence() -> None:
    for hold in (
        fc.HOLD_NO_SNAPSHOT,
        fc.HOLD_UNSYNCHRONIZED,
        fc.HOLD_LATCHED,
        fc.HOLD_AMBIGUOUS,
        fc.HOLD_LOST,
    ):
        assert fc.HOLD_LINES[hold].strip(), hold
        assert fc.HOLD_LINES[hold].endswith(".")


def test_the_ambiguity_hold_reaches_the_product(
    tmp_path: Path, gallery_file: Path, script: ClipScript
) -> None:
    """Through the RUNTIME's own frame door, with two people who look identical.

    Nothing here reaches around ``_publish_camera_frame`` or
    ``_ot2_apply_owner_identity`` — the same product path card OT-2 pinned.
    """

    twins = copy.deepcopy(build_default_script())
    owner, other = twins["people"]
    for key in ("shirt", "trouser", "skin", "pattern"):
        other[key] = owner[key]
    twin_script = ClipScript.from_mapping(twins)

    config = _config(
        tmp_path / "amb", f"  tracker:\n    mode: gallery\n    gallery_path: {gallery_file}\n"
    )
    made = RobotRuntime(config, _Backend(_observation()), audio_status=_audio())
    try:
        ingress = _PixelIngress()
        made.attach_camera_ingress(ingress, start=False)
        assert made._ot2_owner_tracker is not None
        states: list[str] = []
        for index in SCORED_FRAMES:
            ingress.rgb = render_frame(twin_script, index)
            made._publish_camera_frame(detection_frame(twin_script, index))
            observed = made._ot2_apply_owner_identity(_observation())
            states.append(observed.owner.state)
        assert "ambiguous" in states, states
        # And that state is what the contract's own property reads.
        ambiguous_observation = made._ot2_apply_owner_identity(_observation())
        snapshot = _snapshot(ambiguous_observation)
        assert snapshot.owner.ambiguous is True
        assert snapshot.owner.lost is False
        made.follow.start()
        decision = made._follow_compose.step(snapshot, now=time.monotonic())
        assert decision.hold == fc.HOLD_AMBIGUOUS
        assert decision.command == VelocityCommand()
    finally:
        made.close()


def test_the_ambiguity_signal_is_the_trackers_own_margin_gate(gallery, script: ClipScript) -> None:
    """Seeded-RED for the row above, and the mechanism named.

    ``ambiguous_margin`` is the tracker saying the best candidate cleared the
    gallery threshold with a runner-up inside ``min_margin`` — Gate 6's "two
    plausible owners" verbatim. With two DIFFERENT-looking people the same
    corpus produces none of it, so the row above is measuring the mechanism and
    not a constant.
    """

    tracker = OwnerTracker(gallery=gallery, embed_fn=histogram_embed_image)
    reasons: set[str] = set()
    for index in SCORED_FRAMES:
        update = tracker.update(detection_frame(script, index), rgb=render_frame(script, index))
        reasons.update(track.reason for track in update.tracks)
    assert "ambiguous_margin" not in reasons, reasons

    twins = copy.deepcopy(build_default_script())
    owner, other = twins["people"]
    for key in ("shirt", "trouser", "skin", "pattern"):
        other[key] = owner[key]
    twin_script = ClipScript.from_mapping(twins)
    twin_tracker = OwnerTracker(gallery=gallery, embed_fn=histogram_embed_image)
    twin_reasons: set[str] = set()
    for index in SCORED_FRAMES:
        update = twin_tracker.update(
            detection_frame(twin_script, index), rgb=render_frame(twin_script, index)
        )
        twin_reasons.update(track.reason for track in update.tracks)
    assert "ambiguous_margin" in twin_reasons, twin_reasons


def test_the_control_loop_asks_the_composer_before_the_controller() -> None:
    """Order is the property: a veto that ran AFTER ``follow.step`` would already
    have fed the ambiguous frame to the motion history it exists to protect."""

    source = (REPO / "src" / "parcel_robot" / "runtime.py").read_text(encoding="utf-8")
    body = source[source.index("def _control_loop_body") :]
    body = body[: body.index("def ", 40)]
    composer_at = body.index("self._follow_compose.step(")
    controller_at = body.index("decision = self.follow.step(")
    assert composer_at < controller_at, "the composer runs after the controller"
    assert "if compose.hold in FOLLOW_HOLD_VETOES:" in body
    assert "self._announce_follow_hold(compose)" in body


def test_the_hold_line_is_said_once_per_transition(runtime: RobotRuntime) -> None:
    """Edge-triggered: a dog that repeats the sentence at 10 Hz is a smoke alarm."""

    follower = runtime.follow
    follower.start()
    ambiguous = _ambiguous(_snapshot(_observation()))

    def _lines() -> list[str]:
        return [
            str(row.get("text", ""))
            for row in runtime.snapshot().get("chat", [])
            if row.get("role") == "assistant"
        ]

    before = len(_lines())
    first = runtime._follow_compose.step(ambiguous, now=1.0)
    runtime._announce_follow_hold(first)
    runtime._announce_follow_hold(runtime._follow_compose.step(ambiguous, now=1.1))
    runtime._announce_follow_hold(runtime._follow_compose.step(ambiguous, now=1.2))
    said = _lines()[before:]
    assert said.count(fc.AMBIGUOUS_OWNER_LINE) == 1, said
    assert runtime.follow_hold_snapshot() == {
        "hold": fc.HOLD_AMBIGUOUS,
        "line": fc.AMBIGUOUS_OWNER_LINE,
        "reasons": ["owner:ambiguous:ambiguous_margin"],
        "reacquire_remaining_s": None,
        "vetoed_controller": True,
    }
    # A new hold reason is a new sentence.
    runtime._announce_follow_hold(
        runtime._follow_compose.step(
            _snapshot(_observation(owner_visible=False, owner_state="lost")), now=1.3
        )
    )
    assert fc.LOST_OWNER_LINE in _lines()[before:]
    # And a clean frame stops the holding entirely.
    runtime._announce_follow_hold(runtime._follow_compose.step(_snapshot(_observation()), now=1.4))
    assert runtime.follow_hold_snapshot() is None


def test_the_knob_is_reachable_from_a_config_and_not_from_an_overlay() -> None:
    """Both halves of the honest statement about where this knob can be written.

    ``config.py`` sits exactly on the DEC-0 1,000-line ceiling and A8 leaves it
    BYTE-UNCHANGED, so ``owner_follow.tracker`` is settable in a configuration
    file handed to ``--config`` (which is what every row above uses) and is NOT
    settable from a profile overlay on the SHA-locked base until one line is
    added to ``OVERLAY_INTRODUCIBLE_KEYS``. ``A8_STATUS.md`` carries that line.
    """

    import yaml

    from parcel_robot.config import OVERLAY_INTRODUCIBLE_KEYS, ProfileError, check_overlay_keys

    base = yaml.safe_load((REPO / "configs" / "robot.yaml").read_text(encoding="utf-8"))
    assert "owner_follow" in base
    assert "tracker" not in base["owner_follow"]
    assert "owner_follow.tracker" not in OVERLAY_INTRODUCIBLE_KEYS
    with pytest.raises(ProfileError, match="owner_follow.tracker"):
        check_overlay_keys(base, {"owner_follow": {"tracker": {"mode": "gallery"}}})
    # The same shape ``owner_follow.yield_aside`` already has, so this is a
    # standing property of the section rather than a new debt A8 created.
    with pytest.raises(ProfileError, match="owner_follow.yield_aside"):
        check_overlay_keys(base, {"owner_follow": {"yield_aside": {"enabled": True}}})


# ===========================================================================
# 4 · follow speed obeys the commissioned gate — and A8 adds no clearance number
# ===========================================================================
def test_the_follow_controller_shares_the_runtimes_gate_object(runtime: RobotRuntime) -> None:
    """Identity, not equality: one policy object, so one authority."""

    assert runtime.follow._safety_policy is runtime.reactive_safety_policy


def test_a_follow_command_at_a_wall_is_held_by_the_gate(runtime: RobotRuntime) -> None:
    """Drive Follow at a wall in replay; the gate's hold wins, every time."""

    runtime.follow.start()
    policy = runtime.reactive_safety_policy
    held = 0
    ring = policy.obstacle_stop_m
    for distance in (2.0, 1.5, 1.0, ring + 0.05, ring, ring - 0.1, 0.2):
        observation = _observation(owner_xy=(6.0, 0.0), obstacle_m=distance)
        decision = runtime.follow.step(observation, now=observation.timestamp)
        gated, state = apply_reactive_safety(
            decision.command, observation, policy=policy, now=observation.timestamp
        )
        if distance <= ring:
            assert math.hypot(gated.vx, gated.vy) == pytest.approx(0.0), (distance, gated, state)
            held += 1
        # The gate can only ever reduce translation.
        assert (
            math.hypot(gated.vx, gated.vy)
            <= math.hypot(decision.command.vx, decision.command.vy) + 1e-9
        )
    assert held >= 3, "the wall sweep never reached the gate's ring"


def test_a8_adds_no_clearance_number(runtime: RobotRuntime) -> None:
    """The floors are exactly what they were, and A2 remains the one authority."""

    assert FollowConfig().obstacle_stop_m == pytest.approx(0.65)
    assert runtime.follow.config.obstacle_stop_m == pytest.approx(0.65)
    assert runtime.reactive_safety_policy.obstacle_stop_m == pytest.approx(0.65)
    assert runtime.follow.config.obstacle_slow_m == pytest.approx(
        DEFAULT_SAFETY_ENVELOPE.obstacle_comfort_band_m
    )
    policy = runtime.reactive_safety_policy
    assert policy.planner_gate_ring_m == pytest.approx(policy.clearance_profile.gate_range_ring_m)
    assert isinstance(policy.clearance_profile, ClearanceProfile)
    # And nothing in A8's own source states a clearance in metres.
    for path in (FOLLOW_COMPOSE_PATH, INSTALL_PATH):
        source = path.read_text(encoding="utf-8")
        for token in ("_m = 0.", "_m=0.", "stop_m", "clearance_m", "keepout"):
            assert token not in source, f"{path.name} states a clearance ({token})"


def test_the_hold_can_only_subtract(runtime: RobotRuntime) -> None:
    """A HOLD is a zero command; it can never authorize what the gate refused."""

    runtime.follow.start()
    observation = _observation(owner_xy=(6.0, 0.0), obstacle_m=5.0)
    moving = runtime.follow.step(observation, now=observation.timestamp)
    assert moving.command.vx > 0.0, "the wall sweep needs a moving baseline"
    held = fc.hold_command(moving)
    assert held.command == VelocityCommand()
    gated, _ = apply_reactive_safety(
        held.command, observation, policy=runtime.reactive_safety_policy, now=observation.timestamp
    )
    assert gated == VelocityCommand()


# ===========================================================================
# 5 · A3's latch beats Follow
# ===========================================================================
def _latched_installation() -> tuple[LocalizationInstallation, ArmingLatch]:
    latch = ArmingLatch()
    assert latch.observe_signals(BodySignals(operator_pickup=True), t_s=0.0) is True
    assert latch.latched is True
    return LocalizationInstallation(latch=latch), latch


def test_the_latch_reaches_the_published_snapshot(runtime: RobotRuntime) -> None:
    """``motion_latched`` was a field nothing populated. Now it is the latch."""

    before = runtime._stamp_localization_health(_snapshot(_observation()))
    assert before.localization.motion_latched is False
    installation, _ = _latched_installation()
    runtime._localization = installation
    after = runtime._stamp_localization_health(_snapshot(_observation()))
    assert after.localization.motion_latched is True
    assert after.translation_allowed is False


def test_a_disarmed_latch_makes_follow_emit_no_translation(runtime: RobotRuntime) -> None:
    runtime.follow.start()
    installation, _ = _latched_installation()
    runtime._localization = installation
    observation = _observation(owner_xy=(6.0, 0.0), obstacle_m=5.0)
    snapshot = runtime._stamp_localization_health(_snapshot(observation))
    decision = runtime._follow_compose.step(snapshot, now=observation.timestamp)
    assert decision.hold == fc.HOLD_LATCHED
    assert decision.line == fc.LATCHED_LINE
    assert decision.command == VelocityCommand()
    # And the runtime's OWN dispatch join refuses translation independently, so
    # this is a composition and not a replacement.
    health = runtime._evaluate_dispatch_input_health(observation, now=observation.timestamp)
    assert health.translation_allowed is False


def test_the_uncommissioned_default_publishes_the_same_snapshot(runtime: RobotRuntime) -> None:
    """With no localizer commissioned the argument is returned as the SAME object."""

    snapshot = _snapshot(_observation())
    assert runtime._localization.latch is None
    assert runtime._stamp_localization_health(snapshot) is snapshot


def test_the_latch_hold_seeded_red(runtime: RobotRuntime) -> None:
    """Seeded-RED: a composer that checks the owner before the body."""

    runtime.follow.start()
    installation, _ = _latched_installation()
    runtime._localization = installation
    snapshot = runtime._stamp_localization_health(_snapshot(_observation()))
    with _mutated_source(
        FOLLOW_COMPOSE_PATH,
        "        if snapshot.localization.motion_latched:",
        "        if False and snapshot.localization.motion_latched:",
        fc,
    ):
        mutant = importlib.import_module("parcel_robot.navigation.follow_compose")
        composer = mutant.FollowComposer(runtime.follow, reacquire_window_s=3.0)
        decision = composer.step(snapshot, now=time.monotonic())
        assert decision.hold != mutant.HOLD_LATCHED


# ===========================================================================
# 6 · A6's local STOP latches while Follow is active — identity, not a flag
# ===========================================================================
def _latch_event() -> StopLatch:
    config = StopHotwordConfig()
    return StopLatch(
        spot=StopSpot(text="Parcel, stop.", phrase="stop", mode=config.mode, named=True),
        window_end_s=1.0,
        compute_s=0.1,
        latch_s=1.1,
        trigger="close_edge",
    )


def test_a_local_stop_during_follow_latches_the_panels_own_latch(
    runtime: RobotRuntime,
) -> None:
    runtime._enable_owner_follow("direct")
    assert runtime.follow.enabled is True

    runtime.action("emergency_stop")
    panel_state = (runtime.arbiter.emergency_stopped, runtime.agent.safety.emergency_stopped)
    assert panel_state[0] is True
    runtime.clear_emergency_stop()
    runtime._enable_owner_follow("direct")

    runtime._stop_hotword_latched(_latch_event())
    assert runtime.arbiter.emergency_stopped is True, "the spoken stop missed the motion latch"
    assert runtime.arbiter.emergency_stopped == panel_state[0]
    sources = [
        row.get("source")
        for row in runtime.snapshot().get("safety_log", [])
        if isinstance(row, dict)
    ]
    assert SAFETY_SOURCE_PANEL in sources and SAFETY_SOURCE_VOICE in sources, sources
    # Follow is preempted by the SAME emergency route, not by a follow-side flag.
    assert runtime.arbiter.current(time.monotonic()) is None
    with pytest.raises(RuntimeError):
        runtime._enable_owner_follow("direct")


def test_the_stop_target_list_names_follow(runtime: RobotRuntime) -> None:
    """Seeded-RED companion: the preempt targets are pinned, so dropping
    ``follow`` from them reddens instead of silently leaving it running."""

    source = (REPO / "src" / "parcel_robot" / "runtime.py").read_text(encoding="utf-8")
    marker = 'reason="emergency_stop",'
    index = source.index(marker)
    window = source[index : index + 240]
    assert '"follow"' in window, window


def test_the_composer_cannot_outlive_a_follow_episode(runtime: RobotRuntime) -> None:
    """The reacquisition clock and the spoken hold state end with the episode."""

    composer = runtime._follow_compose
    composer.step(_snapshot(_observation()), now=5.0)
    assert composer.last_confirmed_s == pytest.approx(5.0)
    composer.reset()
    assert composer.last_confirmed_s is None


# ===========================================================================
# 7 · the offline floor
# ===========================================================================
def test_the_offline_floor_is_the_owners_own_sentence() -> None:
    floor = fc.offline_floor(connected=False, follow_commissioned=True)
    assert floor.line == fc.OFFLINE_FOLLOW_LINE
    assert "follow you" in floor.line
    assert floor.follow_available is True
    assert floor.stop_available is True


def test_the_ungated_floor_is_hold_plus_the_line() -> None:
    """F5: ship floor until the gate passes = local STOP + HOLD + the canned line."""

    floor = fc.offline_floor(connected=False, follow_commissioned=False)
    assert floor.line == fc.OFFLINE_HOLD_LINE
    assert floor.follow_available is False
    assert floor.hold_available is True
    assert floor.stop_available is True


def test_a_connected_run_says_nothing() -> None:
    assert fc.offline_floor(connected=True, follow_commissioned=True).line == ""
    assert fc.offline_floor(connected=True, follow_commissioned=False).line == ""


def test_the_runtime_wires_the_floor_to_its_own_connectivity_signal(
    runtime: RobotRuntime,
) -> None:
    """The signal is ``_model_status`` — the model lanes, not the Internet.

    That is what this build HAS, it is named in ``offline_floor``'s docstring
    and in ``A8_STATUS.md``, and it is a recorded box-day follow-up rather than
    a faked link check.
    """

    assert runtime.offline_floor().line == ""
    runtime._model_status = "offline"
    floor = runtime.offline_floor()
    assert floor.line == fc.OFFLINE_HOLD_LINE, "an uncommissioned identity may not offer Follow"
    assert floor.follow_available is False
    assert floor.stop_available is True


def test_the_floor_offers_follow_only_behind_a_calibrated_identity(
    tmp_path: Path, gallery_file: Path
) -> None:
    config = _config(
        tmp_path / "floor", f"  tracker:\n    mode: gallery\n    gallery_path: {gallery_file}\n"
    )
    made = RobotRuntime(config, _Backend(_observation()), audio_status=_audio())
    try:
        made._model_status = "offline"
        assert made.offline_floor().follow_available is False
        made.attach_camera_ingress(_PixelIngress(), start=False)
        floor = made.offline_floor()
        assert floor.follow_available is True
        assert floor.line == fc.OFFLINE_FOLLOW_LINE
    finally:
        made.close()


def test_the_software_half_of_the_gate_is_never_sufficient() -> None:
    """The docstring is the assertion here, and it is deliberate.

    ``_owner_identity_commissioned`` can only ever check that a calibrated
    gallery sits behind an installed tracker. The half that decides ENABLE is
    the box-day two-person crossing / occlusion / clothing study, and it has no
    representation in this process.
    """

    source = (REPO / "src" / "parcel_robot" / "runtime.py").read_text(encoding="utf-8")
    index = source.index("def _owner_identity_commissioned")
    window = source[index : index + 900]
    assert "box-day" in window and "necessary, never sufficient" in window


# ===========================================================================
# 8 · the UWB decision, FROM MEASUREMENT
# ===========================================================================
UWB = UwbNoiseConfig()


def _polar(script: ClipScript, pose: dict) -> tuple[float, float]:
    _, range_m, bearing = project(script, pose["x"], pose["y"])
    return range_m, bearing


def _people(script: ClipScript, index: int) -> tuple[dict, dict]:
    poses = script.frames[index]["poses"]
    return poses["owner"], poses["other"]


def _beacon_row(script: ClipScript, index: int, *, seeds: int = BEACON_SEEDS) -> dict:
    """Would a beacon on the OWNER pick the owner over the other person?

    The rule is parameter-free: assign the owner to whichever candidate's true
    measurement the beacon's noisy sample is closest to. No threshold, no
    k-sigma — nothing this card could have chosen to flatter an answer.
    """

    owner, other = _people(script, index)
    r_owner, b_owner = _polar(script, owner)
    r_other, b_other = _polar(script, other)
    model = UwbNoiseModel(UWB)
    range_hits = polar_hits = drawn = 0
    errors: list[float] = []
    for seed in range(seeds):
        model.reset()
        sample = model.observe(
            GroundTruthUwb(fob_id="owner-fob-1", bearing_rad=b_owner, range_m=r_owner),
            rng=random.Random(9_000 + seed),
            received_monotonic_ns=1_000_000_000 + index * 250_000_000,
        )
        if sample is None:
            continue
        drawn += 1
        errors.append(abs(sample.range_m - r_owner))
        if abs(sample.range_m - r_owner) <= abs(sample.range_m - r_other):
            range_hits += 1
        px = sample.range_m * math.cos(sample.bearing_rad)
        py = sample.range_m * math.sin(sample.bearing_rad)
        d_owner = math.hypot(px - r_owner * math.cos(b_owner), py - r_owner * math.sin(b_owner))
        d_other = math.hypot(px - r_other * math.cos(b_other), py - r_other * math.sin(b_other))
        if d_owner <= d_other:
            polar_hits += 1
    return {
        "sep_range_m": abs(r_owner - r_other),
        "sep_2d_m": math.hypot(owner["x"] - other["x"], owner["y"] - other["y"]),
        "range_only": range_hits / max(1, drawn),
        "range_bearing": polar_hits / max(1, drawn),
        "mean_range_error_m": sum(errors) / max(1, len(errors)),
        "visible": bool(owner["visible"]),
    }


def _vision_rows(script: ClipScript, gallery) -> list[dict]:
    tracker = OwnerTracker(gallery=gallery, embed_fn=histogram_embed_image)
    rows: list[dict] = []
    for index in range(script.frame_count):
        update = tracker.update(detection_frame(script, index), rgb=render_frame(script, index))
        owner, other = _people(script, index)
        claim = update.owner_track
        verdict = "no_claim"
        if claim is not None and claim.is_owner:
            d_owner = math.hypot(claim.world_x - owner["x"], claim.world_y - owner["y"])
            d_other = math.hypot(claim.world_x - other["x"], claim.world_y - other["y"])
            verdict = "correct" if d_owner <= d_other else "swap"
        rows.append({"index": index, "visible": bool(owner["visible"]), "verdict": verdict})
    return rows


def _appearance_variant(alpha: float, *, same_pattern: bool) -> ClipScript:
    data = copy.deepcopy(build_default_script())
    owner, other = data["people"]
    for key in ("shirt", "trouser", "skin"):
        other[key] = [
            round(a + (b - a) * alpha) for a, b in zip(other[key], owner[key], strict=True)
        ]
    if same_pattern:
        other["pattern"] = owner["pattern"]
    return ClipScript.from_mapping(data)


def test_vision_only_never_swaps_the_owner_on_the_two_person_corpus(gallery) -> None:
    """The headline vision row: 0 swaps across the whole appearance sweep.

    Ten variants of the crossing corpus, the OTHER person's clothing swept from
    his own to the owner's, the real ``OwnerTracker`` over a CALIBRATED gallery.
    Its failure mode is REFUSAL, never a wrong claim — which is the direction
    that makes A8's HOLD a safe floor rather than a fig leaf.
    """

    swaps = 0
    losses = 0
    visible_frames = 0
    for same_pattern in (False, True):
        for alpha in (0.0, 0.5, 0.9, 0.95, 1.0):
            rows = _vision_rows(_appearance_variant(alpha, same_pattern=same_pattern), gallery)
            scored = [r for r in rows if r["index"] in SCORED_FRAMES and r["visible"]]
            visible_frames += len(scored)
            swaps += sum(1 for r in scored if r["verdict"] == "swap")
            losses += sum(1 for r in scored if r["verdict"] == "no_claim")
    assert visible_frames == 100, visible_frames
    assert swaps == 0, f"{swaps} owner swaps in {visible_frames} visible frames"
    # And the sweep DOES reach the failure point, so the zero is not vacuous:
    # at total appearance identity the tracker refuses on every visible frame.
    assert losses == 10, losses


def test_vision_claims_nothing_through_the_occlusion(gallery, script: ClipScript) -> None:
    """Four occluded frames, one second: appearance has nothing to offer."""

    rows = _vision_rows(script, gallery)
    occluded = [r for r in rows if r["index"] in OCCLUSION_FRAMES]
    assert all(r["visible"] is False for r in occluded)
    assert all(r["verdict"] == "no_claim" for r in occluded), occluded


def test_a_range_only_beacon_does_not_resolve_the_crossing(script: ClipScript) -> None:
    """The decisive geometry row, and it is why UWB is NOT recommended for M1.

    At the crossing the two people's RANGE separation is 0.12-0.28 m while the
    shipped model's range sigma is 0.25 m, so a range-only tag is barely better
    than a coin toss exactly when it would be needed.
    """

    rows = {index: _beacon_row(script, index) for index in CROSSING_FRAMES}
    for index, row in rows.items():
        assert row["sep_range_m"] < UWB.range_jitter_std_m * 1.2, (index, row)
        assert 0.55 <= row["range_only"] <= 0.80, (index, row)
    mean = sum(row["range_only"] for row in rows.values()) / len(rows)
    assert 0.60 <= mean <= 0.75, mean


def test_even_an_aoa_beacon_is_marginal_at_closest_approach(script: ClipScript) -> None:
    """Range+bearing is perfect while the two are apart and marginal when they are not."""

    apart = _beacon_row(script, 0)
    assert apart["sep_2d_m"] > 4.0
    assert apart["range_bearing"] == pytest.approx(1.0)
    closest = min((_beacon_row(script, i) for i in CROSSING_FRAMES), key=lambda r: r["sep_2d_m"])
    assert closest["sep_2d_m"] < 0.40, closest
    assert 0.65 <= closest["range_bearing"] <= 0.85, closest


def test_where_a_beacon_would_actually_pay_is_the_occlusion(script: ClipScript) -> None:
    """The honest value proposition: continuity, not disambiguation.

    UWB does not need line of sight, so through the four frames where the
    camera has nothing the beacon still holds the owner to a mean range error
    of about 0.2 m. That is a CONTINUITY gain, and the floor already HOLDs
    there, which is why it does not buy safety.
    """

    rows = [_beacon_row(script, index) for index in OCCLUSION_FRAMES]
    assert all(row["visible"] is False for row in rows)
    mean_error = sum(row["mean_range_error_m"] for row in rows) / len(rows)
    assert 0.10 <= mean_error <= 0.30, mean_error
    assert mean_error < UWB.range_jitter_std_m


def test_the_separation_at_which_a_beacon_becomes_reliable() -> None:
    """The decision boundary, measured — the number a purchase would need.

    Owner 3 m dead ahead, the other displaced laterally. Range-only needs about
    3 m of separation to reach 0.99; range+bearing reaches 0.95 at about 0.75 m.
    Two people crossing in a corridor are inside both.
    """

    model = UwbNoiseModel(UWB)
    measured: dict[float, tuple[float, float]] = {}
    for separation in (0.3, 0.75, 1.5, 3.0):
        r_owner, b_owner = 3.0, 0.0
        other = (3.0, separation)
        r_other = math.hypot(*other)
        range_hits = polar_hits = drawn = 0
        for seed in range(BEACON_SEEDS):
            model.reset()
            sample = model.observe(
                GroundTruthUwb(fob_id="owner-fob-1", bearing_rad=b_owner, range_m=r_owner),
                rng=random.Random(4_000 + seed),
                received_monotonic_ns=2_000_000_000,
            )
            if sample is None:
                continue
            drawn += 1
            if abs(sample.range_m - r_owner) <= abs(sample.range_m - r_other):
                range_hits += 1
            px = sample.range_m * math.cos(sample.bearing_rad)
            py = sample.range_m * math.sin(sample.bearing_rad)
            if math.hypot(px - 3.0, py) <= math.hypot(px - other[0], py - other[1]):
                polar_hits += 1
        measured[separation] = (range_hits / max(1, drawn), polar_hits / max(1, drawn))

    assert measured[0.3][0] < 0.60, measured
    assert measured[0.3][1] < 0.80, measured
    assert measured[0.75][1] >= 0.90, measured
    assert measured[1.5][1] >= 0.99, measured
    assert measured[3.0][0] >= 0.95, measured
    # Range-only is monotone in separation and never beats range+bearing here.
    assert all(measured[s][0] <= measured[s][1] for s in measured), measured


def test_the_product_cannot_consume_uwb_today_and_says_so() -> None:
    """The BOM half of the recommendation: this is a purchase, not a wire.

    ``uwb/`` declares itself a sim stand-in, the ground-truth source is
    single-fob by construction (there is no second-person UWB sample anywhere
    in the tree), and the fusion stub with ``primary="uwb"`` and no vision can
    only ever reach ``ambiguous``.
    """

    from parcel_robot.uwb import DOES_NOT_PROVE
    from parcel_robot.uwb.fusion import OwnerFusionConfig, OwnerFusionStub
    from parcel_robot.uwb.model import DEFAULT_UWB_TTL_NS

    header = (REPO / "src" / "parcel_robot" / "uwb" / "__init__.py").read_text(encoding="utf-8")
    assert "No real UWB hardware" in header
    assert DOES_NOT_PROVE

    stub = OwnerFusionStub(OwnerFusionConfig(primary="uwb"))
    model = UwbNoiseModel(UWB)
    sample = model.observe(
        GroundTruthUwb(fob_id="owner-fob-1", bearing_rad=0.0, range_m=3.0),
        rng=random.Random(1),
        received_monotonic_ns=1_000_000_000,
    )
    assert sample is not None
    result = stub.fuse(
        robot_x=0.0,
        robot_y=0.0,
        robot_yaw_rad=0.0,
        now_monotonic_ns=1_000_000_000 + DEFAULT_UWB_TTL_NS // 2,
        uwb=sample,
    )
    assert result.track is not None
    assert result.track.state == "ambiguous", (
        "UWB alone reaching 'confirmed' would change the recommendation"
    )


def test_the_real_encoder_margin_is_quoted_not_invented(gallery) -> None:
    """The fixture encoder measures the MECHANISM; the real margin is P1-C's.

    SigLIP-2 separated owner from stranger by >= 0.05 on held-out frames with a
    calibrated gallery, against a ``min_margin`` of 0.02 — about 0.03 of
    headroom, and clothing/lighting change is exactly what eats it. That thin
    margin is the box-day study's subject, and it is the reason the ENABLE
    decision is not taken here.
    """

    assert gallery.calibrated is True
    assert gallery.min_margin == pytest.approx(0.02)
    assert REAL_ENCODER_OWNER_STRANGER_SEPARATION > gallery.min_margin
    headroom = REAL_ENCODER_OWNER_STRANGER_SEPARATION - gallery.min_margin
    assert 0.02 <= headroom <= 0.04, headroom


def test_the_beacon_measurement_seeded_red(script: ClipScript) -> None:
    """Seeded-RED: a beacon with no range noise resolves everything, which is
    how we know the rows above are measuring the noise model and not the code."""

    quiet = UwbNoiseConfig(range_jitter_std_m=1e-6, bearing_jitter_std_rad=1e-6)
    model = UwbNoiseModel(quiet)
    owner, other = _people(script, CROSSING_FRAMES[-1])
    r_owner, b_owner = _polar(script, owner)
    r_other, _ = _polar(script, other)
    hits = 0
    for seed in range(50):
        model.reset()
        sample = model.observe(
            GroundTruthUwb(fob_id="owner-fob-1", bearing_rad=b_owner, range_m=r_owner),
            rng=random.Random(seed),
            received_monotonic_ns=1_000_000_000,
        )
        assert sample is not None
        if abs(sample.range_m - r_owner) <= abs(sample.range_m - r_other):
            hits += 1
    assert hits == 50, hits
    # ... and the shipped sigma does NOT, which is the finding.
    assert _beacon_row(script, CROSSING_FRAMES[-1])["range_only"] < 0.75


def test_the_noise_model_carries_no_nlos_bias() -> None:
    """The honesty row that bounds every beacon number above.

    Real indoor UWB NLOS adds a POSITIVE range bias, usually well beyond this
    model's 0.25 m sigma. This model is zero-mean Gaussian with dropouts, so
    every rate above is an OPTIMISTIC bound and the real answer is worse —
    which strengthens the defer rather than weakening it.
    """

    source = (REPO / "src" / "parcel_robot" / "uwb" / "noise.py").read_text(encoding="utf-8")
    assert "bias" not in source.lower(), "the noise model grew a bias term; re-measure"
    model_source = (REPO / "src" / "parcel_robot" / "uwb" / "model.py").read_text(encoding="utf-8")
    assert "rng.gauss(0.0" in model_source
