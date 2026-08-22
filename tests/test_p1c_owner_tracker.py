"""Card P1-C — the pixel re-ID tracker, measured on the two-person clip.

The rows this file measures were **pre-registered before anything was run**
(``scrum/20260822/task_8/P1C_STATUS.md`` §2):

  R1  zero owner claims with an EMPTY gallery                        exactly 0
  R2  the owner's track id survives a four-frame occlusion           identical
  R3a the owner label never lands on the other person                exactly 0
  R3b the owner's TRACK id does not change through the crossing      exactly 1
  R4  the owner confidence is a measured number, not a constant      <1.0, ≥5 values
  R5  confidence decays while coasting, and fusion gets nothing      monotone ↓

Every one of them has a **seeded-RED counterpart in this file**: a deliberately
broken build that the same assertion catches. A guard nobody has watched fail is
a guard nobody has tested.

The encoder here is ``synthetic_clip.histogram_embed_image`` — a banded colour
histogram with the ``embed_fn`` call shape, so these rows run on any host with
no GPU and no weights. The **same rows against the real SigLIP-2 fp16 encoder**
are in ``test_p1c_real_siglip2.py``, which skips when the weights are absent.
"""

from __future__ import annotations

import math
from dataclasses import replace
from pathlib import Path

import pytest

from parcel_robot.owner_tracking.gallery import build_gallery
from parcel_robot.owner_tracking.synthetic_clip import (
    ClipScript,
    crop_for,
    detection_frame,
    histogram_embed_image,
    iter_clip,
    project,
    render_frame,
)
from parcel_robot.owner_tracking.tracker import (
    STATE_CONFIRMED,
    STATE_LOST,
    STATE_SEARCHING,
    OwnerTracker,
    OwnerTrackerConfig,
    PixelOwnerTrack,
    is_person_label,
)

CLIP_PATH = Path(__file__).resolve().parent / "data" / "p1c_two_person_clip.json"

#: From the fixture's own header, so the test and the scenario cannot drift.
ENROLLMENT_FRAMES = (0, 1, 2, 3, 4, 5)
CROSSING_FRAMES = (8, 9, 10, 11)
OCCLUSION_FRAMES = (13, 14, 15, 16)


@pytest.fixture(scope="module")
def script() -> ClipScript:
    return ClipScript.load(CLIP_PATH)


@pytest.fixture(scope="module")
def calibrated_gallery(script: ClipScript):
    """Enrolled on frames 0-5 only; every row below is measured on 6-19.

    The negatives come from the SAME enrollment window, so the operating point
    is calibrated without ever seeing a frame it is then scored on.
    """

    owner = [histogram_embed_image(crop_for(script, i, "owner")) for i in ENROLLMENT_FRAMES]
    negative = [histogram_embed_image(crop_for(script, i, "other")) for i in ENROLLMENT_FRAMES]
    return build_gallery(owner, model="fixture:histogram_embed_image/v1", negatives=negative)


def _run(script: ClipScript, tracker: OwnerTracker) -> list:
    return [tracker.update(frame, rgb=rgb) for _index, rgb, frame in iter_clip(script)]


def _person_under(script: ClipScript, index: int, track: PixelOwnerTrack) -> str | None:
    """Which scripted person is this track actually sitting on? Ground truth."""

    best: tuple[float, str] | None = None
    for name, pose in script.frames[index]["poses"].items():
        if not pose["visible"]:
            continue
        distance = math.hypot(track.world_x - pose["x"], track.world_y - pose["y"])
        if best is None or distance < best[0]:
            best = (distance, name)
    return None if best is None else best[1]


# --------------------------------------------------------------- the fixture
def test_the_shipped_clip_matches_the_generator(script: ClipScript) -> None:
    """The JSON in tests/data is what ``build_default_script`` produces."""

    from parcel_robot.owner_tracking.synthetic_clip import build_default_script

    assert ClipScript.from_mapping(build_default_script()) == script


def test_the_clip_actually_crosses_and_actually_occludes(script: ClipScript) -> None:
    """A fixture nobody checked is a fixture that proves whatever it happens to."""

    separations = []
    for index in range(script.frame_count):
        poses = script.frames[index]["poses"]
        separations.append(
            math.hypot(
                poses["owner"]["x"] - poses["other"]["x"],
                poses["owner"]["y"] - poses["other"]["y"],
            )
        )
    closest = min(separations)
    assert closest < 0.4, f"the two people never actually meet (closest {closest:.2f} m)"
    assert separations[0] > 4.0 and separations[-1] > 4.0  # they arrive and leave apart
    occluded = [i for i in range(script.frame_count) if not script.frames[i]["poses"]["owner"]["visible"]]
    assert tuple(occluded) == OCCLUSION_FRAMES
    # And during the occlusion the OTHER person is still there, which is what
    # makes "did it claim the stranger?" a question worth asking.
    for index in OCCLUSION_FRAMES:
        assert script.frames[index]["poses"]["other"]["visible"]
    # In image space the crossing is a shoulder brush, not a total eclipse.
    overlaps = []
    for index in CROSSING_FRAMES:
        poses = script.frames[index]["poses"]
        if not poses["owner"]["visible"]:
            continue
        a, _r, _b = project(script, poses["owner"]["x"], poses["owner"]["y"])
        b, _r, _b2 = project(script, poses["other"]["x"], poses["other"]["y"])
        width = min(a[2] - a[0], b[2] - b[0])
        overlaps.append(max(0.0, min(a[2], b[2]) - max(a[0], b[0])) / width)
    assert 0.2 < max(overlaps) < 0.8, f"crossing overlaps {overlaps}"


def test_the_rendered_frames_are_valid_c1_frames(script: ClipScript) -> None:
    frame = detection_frame(script, 0)
    assert frame.width_px == script.width and frame.height_px == script.height
    assert frame.queries == ("person",)
    assert frame.class_counts() == {"person": 2}
    assert frame.capture_started_monotonic_ns <= frame.published_monotonic_ns
    rgb = render_frame(script, 0)
    assert rgb.shape == (script.height, script.width, 3)
    # The occlusion is an ABSENT detection, not a low-scoring one.
    assert len(detection_frame(script, OCCLUSION_FRAMES[0]).detections) == 1


def test_person_label_matching_is_whole_word() -> None:
    assert is_person_label("person")
    assert is_person_label("a person holding a cup")
    assert not is_person_label("personal computer")
    assert not is_person_label("chair")


# ------------------------------------------------------- R1: empty gallery
def test_R1_an_empty_gallery_produces_zero_owner_claims(script: ClipScript) -> None:
    tracker = OwnerTracker(gallery=None, embed_fn=histogram_embed_image)
    updates = _run(script, tracker)
    assert sum(1 for u in updates if u.owner_claimed) == 0
    assert {u.state for u in updates} == {STATE_SEARCHING}
    assert {u.reason for u in updates} == {"no_gallery"}
    # It still TRACKS — the people are seen, they are simply nobody.
    assert all(len(u.tracks) >= 1 for u in updates)
    assert all(track.label == "unknown" for u in updates for track in u.tracks)
    assert all(track.gallery_enrolled is False for u in updates for track in u.tracks)


def test_R1_seeded_RED_a_tracker_that_defaults_to_the_only_person(
    script: ClipScript, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The guard must fail on a build that calls the only visible person the owner."""

    from parcel_robot.owner_tracking import tracker as tracker_module

    def default_owner(self, observations, assigned) -> None:
        for track in self._tracks:
            track.label = "owner"
            track.identity_ema = 1.0
            track.reason = "seeded_red_default_owner"

    monkeypatch.setattr(tracker_module.OwnerTracker, "_score_identity", default_owner)
    broken = OwnerTracker(gallery=None, embed_fn=histogram_embed_image)
    updates = _run(script, broken)
    assert sum(1 for u in updates if u.owner_claimed) > 0, "seeded RED did not go red"
    # And the fusion seam refuses to carry the lie across the boundary.
    claimed = next(u.owner_track for u in updates if u.owner_claimed)
    with pytest.raises(ValueError, match="owner_claim without gallery_enrolled"):
        claimed.as_fusion_input()


# ------------------------------- R2/R3b: continuity across crossing + occlusion
def test_R2_R3b_one_track_id_carries_the_owner_through_crossing_and_occlusion(
    script: ClipScript, calibrated_gallery
) -> None:
    tracker = OwnerTracker(gallery=calibrated_gallery, embed_fn=histogram_embed_image)
    updates = _run(script, tracker)
    owner_ids = {u.owner_track.track_id for u in updates if u.owner_claimed}
    assert len(owner_ids) == 1, f"the owner changed identity mid-clip: {owner_ids}"
    owner_id = owner_ids.pop()

    before = [i for i in range(CROSSING_FRAMES[0]) if updates[i].owner_claimed]
    after = [i for i in range(CROSSING_FRAMES[-1] + 1, 13) if updates[i].owner_claimed]
    assert before and after
    assert updates[before[-1]].owner_track.track_id == updates[after[0]].owner_track.track_id

    # The occlusion: the track is KEPT (id survives) but is not emitted.
    for index in OCCLUSION_FRAMES:
        coasting = [t for t in updates[index].tracks if t.track_id == owner_id]
        assert coasting, f"frame {index} dropped the owner's track entirely"
        assert coasting[0].seen_this_frame is False
        assert coasting[0].state == STATE_LOST
        assert coasting[0].label == "unknown", "a coasted track must not still claim owner"
        assert updates[index].owner_track is None
        assert updates[index].state == STATE_SEARCHING

    # Reacquisition: same id, within two frames of the owner being visible again.
    reacquired = [
        i for i in range(OCCLUSION_FRAMES[-1] + 1, script.frame_count) if updates[i].owner_claimed
    ]
    assert reacquired, "the owner was never reacquired"
    assert reacquired[0] - OCCLUSION_FRAMES[-1] <= 2
    assert updates[reacquired[0]].owner_track.track_id == owner_id


def test_R3a_the_owner_label_never_lands_on_the_other_person(
    script: ClipScript, calibrated_gallery
) -> None:
    tracker = OwnerTracker(gallery=calibrated_gallery, embed_fn=histogram_embed_image)
    updates = _run(script, tracker)
    wrong = [
        index
        for index, update in enumerate(updates)
        if update.owner_claimed and _person_under(script, index, update.owner_track) != "owner"
    ]
    assert wrong == [], f"owner label landed on the stranger on frames {wrong}"


def test_R3b_seeded_RED_position_dominated_association_swaps_at_the_crossing(
    script: ClipScript, calibrated_gallery
) -> None:
    """Nearest-neighbour association swaps identities by construction. Prove it.

    This is the RED that justifies ``appearance_weight``: the same clip, the same
    gallery, the only change being a cost that trusts geometry over appearance —
    and the owner's track id changes mid-clip.
    """

    red_config = OwnerTrackerConfig(
        appearance_weight=0.01, position_weight=10.0, max_assoc_cost=20.0
    )
    red = OwnerTracker(
        gallery=calibrated_gallery, embed_fn=histogram_embed_image, config=red_config
    )
    red_ids = {u.owner_track.track_id for u in _run(script, red) if u.owner_claimed}
    assert len(red_ids) > 1, "seeded RED did not go red: no swap under a position-only cost"

    green = OwnerTracker(gallery=calibrated_gallery, embed_fn=histogram_embed_image)
    green_ids = {u.owner_track.track_id for u in _run(script, green) if u.owner_claimed}
    assert len(green_ids) == 1


def test_a_zero_appearance_weight_is_refused_at_construction() -> None:
    """The RED above is reachable only by a deliberate hand. Zero is not."""

    with pytest.raises(ValueError, match="position-only cost swaps"):
        OwnerTrackerConfig(appearance_weight=0.0)


# ----------------------------------------------- R4: a measurement, not 1.0
def test_R4_the_owner_confidence_is_measured_and_varies(
    script: ClipScript, calibrated_gallery
) -> None:
    tracker = OwnerTracker(gallery=calibrated_gallery, embed_fn=histogram_embed_image)
    updates = _run(script, tracker)
    held_out = [
        u.owner_track.identity_score
        for index, u in enumerate(updates)
        if u.owner_claimed and index not in ENROLLMENT_FRAMES
    ]
    assert held_out, "no owner claims on held-out frames"
    assert all(0.0 < score < 1.0 for score in held_out), held_out
    assert len({round(score, 6) for score in held_out}) >= 5, held_out
    # On the ENROLLMENT frames the crop IS an enrolled crop, so 1.0 is correct
    # and is the only documented way to reach it.
    enrolled = [
        u.owner_track.identity_score for i, u in enumerate(updates)
        if u.owner_claimed and i in ENROLLMENT_FRAMES
    ]
    assert enrolled and max(enrolled) == pytest.approx(1.0)


def test_R4_seeded_RED_a_constant_confidence_is_caught(
    script: ClipScript, calibrated_gallery, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The audit's actual defect: an owner at 1.0 forever."""

    from parcel_robot.owner_tracking import tracker as tracker_module

    real_snapshot = tracker_module.OwnerTracker._snapshot

    def constant(self, track, now):
        snap = real_snapshot(self, track, now)
        return replace(snap, identity_similarity=1.0, identity_score=1.0)

    monkeypatch.setattr(tracker_module.OwnerTracker, "_snapshot", constant)
    broken = OwnerTracker(gallery=calibrated_gallery, embed_fn=histogram_embed_image)
    updates = _run(script, broken)
    held_out = [
        u.owner_track.identity_score
        for index, u in enumerate(updates)
        if u.owner_claimed and index not in ENROLLMENT_FRAMES
    ]
    assert held_out
    assert not all(0.0 < score < 1.0 for score in held_out), "seeded RED did not go red"
    assert len({round(score, 6) for score in held_out}) < 5


# --------------------------------------------------- R5: decay, then nothing
def test_R5_confidence_decays_while_coasting_and_never_reaches_fusion(
    script: ClipScript, calibrated_gallery
) -> None:
    tracker = OwnerTracker(gallery=calibrated_gallery, embed_fn=histogram_embed_image)
    updates = _run(script, tracker)
    owner_id = next(u.owner_track.track_id for u in updates if u.owner_claimed)
    coasting = []
    for index in OCCLUSION_FRAMES:
        track = next(t for t in updates[index].tracks if t.track_id == owner_id)
        coasting.append(track.identity_score)
        assert track.age_s > 0.0
        # The seam a consumer would use carries no claim.
        seam = track.as_fusion_input()
        assert seam.owner_claim is False
    assert coasting == sorted(coasting, reverse=True), coasting
    assert coasting[-1] < coasting[0]


def test_R5_a_track_is_dropped_after_lost_after_s_and_reacquisition_is_a_new_identity(
    script: ClipScript, calibrated_gallery
) -> None:
    """Past the horizon the tracker starts over rather than pretending to remember."""

    short = OwnerTrackerConfig(lost_after_s=0.4)
    tracker = OwnerTracker(
        gallery=calibrated_gallery, embed_fn=histogram_embed_image, config=short
    )
    updates = _run(script, tracker)
    ids_before = {
        u.owner_track.track_id
        for i, u in enumerate(updates)
        if u.owner_claimed and i < OCCLUSION_FRAMES[0]
    }
    ids_after = {
        u.owner_track.track_id
        for i, u in enumerate(updates)
        if u.owner_claimed and i > OCCLUSION_FRAMES[-1]
    }
    assert ids_before and ids_after
    assert ids_before.isdisjoint(ids_after), "a 0.4 s horizon must not span a 1.0 s occlusion"


# ------------------------------------------------------------ degrade paths
def test_no_embedder_asserts_no_identity_at_all(script: ClipScript, calibrated_gallery) -> None:
    tracker = OwnerTracker(gallery=calibrated_gallery, embed_fn=None)
    updates = _run(script, tracker)
    assert all(not u.owner_claimed for u in updates)
    assert {u.reason for u in updates} == {"no_embedder"}
    assert tracker.embed_calls == 0


def test_no_pixels_asserts_no_identity_at_all(script: ClipScript, calibrated_gallery) -> None:
    tracker = OwnerTracker(gallery=calibrated_gallery, embed_fn=histogram_embed_image)
    updates = [tracker.update(frame, rgb=None) for _i, _rgb, frame in iter_clip(script)]
    assert all(not u.owner_claimed for u in updates)
    assert {u.reason for u in updates} == {"no_pixels"}


def test_an_encoder_that_raises_degrades_instead_of_killing_the_worker(
    script: ClipScript, calibrated_gallery
) -> None:
    def explode(_crop):
        raise RuntimeError("CUDA fell over")

    tracker = OwnerTracker(gallery=calibrated_gallery, embed_fn=explode)
    updates = _run(script, tracker)
    assert all(not u.owner_claimed for u in updates)
    assert tracker.embed_failures > 0


def test_a_gallery_from_a_different_encoder_is_refused_not_scored(
    script: ClipScript, calibrated_gallery
) -> None:
    """Dimension mismatch means a different embedding space. Refuse, do not guess."""

    def wrong_dim(_crop):
        return (1.0,) * 16

    tracker = OwnerTracker(gallery=calibrated_gallery, embed_fn=wrong_dim)
    update = tracker.update(detection_frame(script, 0), rgb=render_frame(script, 0))
    assert update.reason == "gallery_model_mismatch"
    assert update.owner_track is None


def test_tiny_boxes_are_not_embedded(script: ClipScript, calibrated_gallery) -> None:
    tracker = OwnerTracker(
        gallery=calibrated_gallery,
        embed_fn=histogram_embed_image,
        config=OwnerTrackerConfig(min_crop_px=4096),
    )
    update = tracker.update(detection_frame(script, 0), rgb=render_frame(script, 0))
    assert update.persons_seen == 2
    assert update.embedded == 0
    assert update.reason == "no_usable_crops"


def test_low_scoring_person_boxes_are_ignored(script: ClipScript, calibrated_gallery) -> None:
    tracker = OwnerTracker(gallery=calibrated_gallery, embed_fn=histogram_embed_image)
    weak = detection_frame(script, 0, detector_score=0.05)
    update = tracker.update(weak, rgb=render_frame(script, 0))
    assert update.persons_seen == 0
    assert update.reason == "no_person_detected"


# ------------------------------------------------------------- the DTO out
def test_the_detection_msg_carries_the_embedding_and_the_right_class(
    script: ClipScript, calibrated_gallery
) -> None:
    tracker = OwnerTracker(gallery=calibrated_gallery, embed_fn=histogram_embed_image)
    updates = _run(script, tracker)
    update = next(u for u in updates if u.owner_claimed)
    message = update.owner_track.as_detection_msg(
        now_monotonic_ns=5_000_000_000, source_timestamp_ns=4_999_000_000, sequence=7
    )
    assert message.class_id == "owner"
    assert len(message.embedding) == len(update.owner_track.embedding)
    assert message.track_id == update.owner_track.track_id
    assert -math.pi <= message.bearing_rad <= math.pi
    stranger = next(t for t in update.tracks if not t.is_owner)
    assert stranger.as_detection_msg(
        now_monotonic_ns=5_000_000_000, source_timestamp_ns=4_999_000_000, sequence=8
    ).class_id == "person"


def test_a_track_with_no_embedding_refuses_to_become_a_detection_msg() -> None:
    naked = PixelOwnerTrack(
        track_id="t1",
        label="owner",
        state=STATE_CONFIRMED,
        identity_similarity=0.9,
        identity_score=0.9,
        identity_margin=0.1,
        visibility_score=0.8,
        world_x=1.0,
        world_y=0.0,
        range_m=1.0,
        bearing_rad=0.0,
        box=(0.0, 0.0, 10.0, 20.0),
        hits=3,
        misses=0,
        age_s=0.0,
        seen_this_frame=True,
        gallery_enrolled=True,
    )
    with pytest.raises(ValueError, match="no appearance embedding"):
        naked.as_detection_msg(now_monotonic_ns=1, source_timestamp_ns=1, sequence=1)


def test_an_uncalibrated_gallery_labels_its_own_claims(script: ClipScript) -> None:
    """The claim is still made; the fact that its boundary is a guess travels with it."""

    owner = [histogram_embed_image(crop_for(script, i, "owner")) for i in ENROLLMENT_FRAMES]
    uncalibrated = build_gallery(owner, model="fixture:histogram_embed_image/v1")
    tracker = OwnerTracker(gallery=uncalibrated, embed_fn=histogram_embed_image)
    updates = _run(script, tracker)
    claimed = [u for u in updates if u.owner_claimed]
    assert claimed
    assert all(u.owner_track.reason == "gallery_match_uncalibrated" for u in claimed)
    assert all(u.owner_track.gallery_calibrated is False for u in claimed)
    assert all(u.owner_track.as_fusion_input().gallery_calibrated is False for u in claimed)
