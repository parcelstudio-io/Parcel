"""Card P1-C — the pixel re-ID input seam on ``OwnerFusionStub``.

Two things are proved here and they pull in opposite directions, which is why
they are in one file:

**Nothing moved.** ``fuse()`` called without a ``pixel`` argument produces the
byte-identical ``OwnerTrackV1`` it produced before this card, over a 512-case
matrix that sweeps both primaries × channel presence × quality × freshness ×
multipath × detection class. The digest below was taken from
``git show HEAD:src/parcel_robot/uwb/fusion.py`` loaded as its own module and
run through this exact matrix (see ``scrum/20260822/task_8/P1C_STATUS.md`` §5
for the command). If a future edit changes what an existing call site receives,
this digest moves and the test says so.

**Something did.** When a ``PixelTrackInput`` IS supplied, the identity score
stops being a channel prior and becomes the cosine somebody measured, and
``confirmed`` stops meaning "the channel is fresh" and starts meaning "the
gallery matched". Those are the two sentences the audit said nothing in the
tree could distinguish.
"""

from __future__ import annotations

import hashlib
import json

import pytest

from parcel_robot.contracts import (
    SCHEMA_VERSION,
    DetectionMsg,
    EvidenceEnvelopeV1,
    expires_from_ttl,
)
from parcel_robot.uwb.fusion import (
    OwnerFusionConfig,
    OwnerFusionStub,
    PixelTrackInput,
)
from parcel_robot.uwb.sample import UwbSample

NOW = 1_000_000_000

#: sha256 of the canonical JSON of the 512-case matrix below, produced by
#: HEAD's (pre-P1-C) fusion module. Regenerating it is a deliberate act and it
#: means an existing consumer's track changed shape or value.
PRE_P1C_MATRIX_SHA256 = "a98f47d99404955c6df5be8f4298f1f7d89fb4f17fbcf7f85270403e2cd65c55"


def _envelope(evidence_id: str, source_ts: int, sequence: int, ttl_ns: int) -> EvidenceEnvelopeV1:
    received = NOW - 10_000_000
    return EvidenceEnvelopeV1(
        schema_version=SCHEMA_VERSION,
        evidence_id=evidence_id,
        source="matrix",
        source_timestamp_ns=source_ts,
        received_monotonic_ns=received,
        sequence=sequence,
        frame_id="odom",
        scene_revision=0,
        expires_monotonic_ns=expires_from_ttl(received_monotonic_ns=received, ttl_ns=ttl_ns),
        calibration_id="cal-1",
        provenance=("matrix",),
    )


def _uwb(*, quality: float, fresh: bool, multipath: bool) -> UwbSample:
    return UwbSample(
        envelope=_envelope("u", 900_000_000, 1, 500_000_000 if fresh else 1_000),
        fob_id="fob-1",
        bearing_rad=0.3,
        range_m=2.5,
        quality=quality,
        multipath_suspect=multipath,
    )


def _vision(*, score: float, fresh: bool, class_id: str) -> DetectionMsg:
    return DetectionMsg(
        envelope=_envelope("v", 950_000_000, 2, 500_000_000 if fresh else 1_000),
        class_id=class_id,
        embedding=(0.1, 0.2, 0.3),
        bearing_rad=-0.2,
        range_m=2.2,
        score=score,
        track_id="det-1",
    )


def _matrix_rows() -> list[dict]:
    rows: list[dict] = []
    for primary in ("uwb", "vision"):
        stub = OwnerFusionStub(OwnerFusionConfig(primary=primary))
        for u_present in (False, True):
            for u_quality in (0.2, 0.9):
                for u_fresh in (True, False):
                    for u_mp in (False, True):
                        for v_present in (False, True):
                            for v_score in (0.2, 0.9):
                                for v_fresh in (True, False):
                                    for v_class in ("person", "owner"):
                                        result = stub.fuse(
                                            robot_x=1.0,
                                            robot_y=-0.5,
                                            robot_yaw_rad=0.4,
                                            now_monotonic_ns=NOW,
                                            uwb=_uwb(
                                                quality=u_quality, fresh=u_fresh, multipath=u_mp
                                            )
                                            if u_present
                                            else None,
                                            vision=_vision(
                                                score=v_score, fresh=v_fresh, class_id=v_class
                                            )
                                            if v_present
                                            else None,
                                            transient_track_id="owner-transient-1",
                                        )
                                        rows.append(
                                            {
                                                "key": [
                                                    primary,
                                                    u_present,
                                                    u_quality,
                                                    u_fresh,
                                                    u_mp,
                                                    v_present,
                                                    v_score,
                                                    v_fresh,
                                                    v_class,
                                                ],
                                                "primary_used": result.primary_used,
                                                "reason": result.reason,
                                                "track": None
                                                if result.track is None
                                                else result.track.as_dict(),
                                            }
                                        )
    return rows


def _fresh_stub(primary: str = "uwb") -> OwnerFusionStub:
    return OwnerFusionStub(OwnerFusionConfig(primary=primary))


def _pixel(**overrides) -> PixelTrackInput:
    payload = {
        "transient_track_id": "pixel-person-1",
        "identity_similarity": 0.83,
        "visibility": 0.71,
        "owner_claim": True,
        "gallery_enrolled": True,
        "gallery_calibrated": True,
    }
    payload.update(overrides)
    return PixelTrackInput(**payload)


# ------------------------------------------------------- nothing moved (R8)
def test_R8_fuse_without_a_pixel_track_is_byte_identical_to_HEAD() -> None:
    rows = _matrix_rows()
    assert len(rows) == 512
    payload = json.dumps({"cases": len(rows), "rows": rows}, sort_keys=True, indent=1)
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    assert digest == PRE_P1C_MATRIX_SHA256, (
        "the pixel seam changed what an existing (pixel-less) call site receives. "
        "That is not an additive seam. Regenerate the digest only with the reason "
        "written into scrum/20260822/task_8/P1C_STATUS.md."
    )


def test_R8_seeded_RED_the_digest_actually_notices_a_change() -> None:
    """A digest nobody has watched fail is a digest nobody has tested."""

    rows = _matrix_rows()
    accepted = next(row for row in rows if row["track"] is not None)
    # The exact perturbation the audit found in the wild: an identity score
    # nudged to 1.0 on one case out of 512.
    accepted["track"]["identity_score"] = 1.0
    mutated = hashlib.sha256(
        json.dumps({"cases": len(rows), "rows": rows}, sort_keys=True, indent=1).encode("utf-8")
    ).hexdigest()
    assert mutated != PRE_P1C_MATRIX_SHA256


def test_a_pixel_less_result_says_its_identity_is_a_prior() -> None:
    result = _fresh_stub().fuse(
        robot_x=0.0,
        robot_y=0.0,
        robot_yaw_rad=0.0,
        now_monotonic_ns=NOW,
        uwb=_uwb(quality=0.9, fresh=True, multipath=False),
    )
    assert result.accepted
    assert result.identity_source == "channel_prior"
    assert result.identity_measured is False
    assert result.identity_calibrated is False


# -------------------------------------------------- the seam, when supplied
def test_the_pixel_similarity_replaces_the_channel_prior() -> None:
    stub = _fresh_stub()
    without = stub.fuse(
        robot_x=0.0,
        robot_y=0.0,
        robot_yaw_rad=0.0,
        now_monotonic_ns=NOW,
        uwb=_uwb(quality=0.9, fresh=True, multipath=False),
    )
    with_pixel = _fresh_stub().fuse(
        robot_x=0.0,
        robot_y=0.0,
        robot_yaw_rad=0.0,
        now_monotonic_ns=NOW,
        uwb=_uwb(quality=0.9, fresh=True, multipath=False),
        pixel=_pixel(identity_similarity=0.83),
    )
    assert without.track.identity_score == pytest.approx(0.55)  # the old prior
    assert with_pixel.track.identity_score == pytest.approx(0.83)  # the measurement
    assert with_pixel.identity_source == "pixel_reid"
    assert with_pixel.identity_measured and with_pixel.identity_calibrated
    # Pose is untouched: the pixel channel carries identity, not position.
    assert with_pixel.track.pose == without.track.pose
    assert with_pixel.primary_used == "uwb"


def test_the_pixel_track_id_becomes_the_transient_track_id() -> None:
    result = _fresh_stub().fuse(
        robot_x=0.0,
        robot_y=0.0,
        robot_yaw_rad=0.0,
        now_monotonic_ns=NOW,
        uwb=_uwb(quality=0.9, fresh=True, multipath=False),
        pixel=_pixel(transient_track_id="pixel-person-7"),
        transient_track_id="ignored-default",
    )
    assert result.track.transient_track_id == "pixel-person-7"


def test_confirmed_now_requires_a_gallery_match_not_merely_a_fresh_channel() -> None:
    """The card's one behaviour change, and it moves strictly toward "not sure"."""

    args = {
        "robot_x": 0.0,
        "robot_y": 0.0,
        "robot_yaw_rad": 0.0,
        "now_monotonic_ns": NOW,
        "uwb": _uwb(quality=0.9, fresh=True, multipath=False),
        "vision": _vision(score=0.9, fresh=True, class_id="person"),
    }
    before = _fresh_stub().fuse(**args)
    assert before.track.state == "confirmed"  # fresh vision corroborated UWB

    unmatched = _fresh_stub().fuse(**args, pixel=_pixel(owner_claim=False))
    assert unmatched.track.state == "ambiguous"
    assert unmatched.track.last_confirmed_at_monotonic_ns == 0

    matched = _fresh_stub().fuse(**args, pixel=_pixel(owner_claim=True))
    assert matched.track.state == "confirmed"
    assert matched.track.last_confirmed_at_monotonic_ns == NOW


def test_the_pixel_channel_cannot_make_an_absent_primary_available() -> None:
    """Identity is not pose. A confident re-ID with no pose fix is still lost."""

    for primary, expected in (("uwb", "primary_uwb_unavailable"), ("vision", "primary_vision_unavailable")):
        result = _fresh_stub(primary).fuse(
            robot_x=0.0,
            robot_y=0.0,
            robot_yaw_rad=0.0,
            now_monotonic_ns=NOW,
            pixel=_pixel(identity_similarity=1.0, owner_claim=True),
        )
        assert result.track is None
        assert result.reason == expected
        assert result.identity_source == "channel_prior"


def test_corroboration_still_applies_on_top_of_the_measurement() -> None:
    lone = _fresh_stub().fuse(
        robot_x=0.0,
        robot_y=0.0,
        robot_yaw_rad=0.0,
        now_monotonic_ns=NOW,
        uwb=_uwb(quality=0.9, fresh=True, multipath=False),
        pixel=_pixel(identity_similarity=0.60),
    )
    corroborated = _fresh_stub().fuse(
        robot_x=0.0,
        robot_y=0.0,
        robot_yaw_rad=0.0,
        now_monotonic_ns=NOW,
        uwb=_uwb(quality=0.9, fresh=True, multipath=False),
        vision=_vision(score=0.9, fresh=True, class_id="person"),
        pixel=_pixel(identity_similarity=0.60),
    )
    assert lone.track.identity_score == pytest.approx(0.60)
    assert corroborated.track.identity_score == pytest.approx(0.70)


def test_an_uncalibrated_pixel_claim_is_labelled_as_such() -> None:
    result = _fresh_stub().fuse(
        robot_x=0.0,
        robot_y=0.0,
        robot_yaw_rad=0.0,
        now_monotonic_ns=NOW,
        uwb=_uwb(quality=0.9, fresh=True, multipath=False),
        pixel=_pixel(gallery_calibrated=False),
    )
    assert result.identity_source == "pixel_reid_uncalibrated"
    assert result.identity_measured is True
    assert result.identity_calibrated is False


def test_identity_stays_a_probability_even_with_a_saturating_measurement() -> None:
    result = _fresh_stub().fuse(
        robot_x=0.0,
        robot_y=0.0,
        robot_yaw_rad=0.0,
        now_monotonic_ns=NOW,
        uwb=_uwb(quality=0.9, fresh=True, multipath=False),
        vision=_vision(score=0.9, fresh=True, class_id="person"),
        pixel=_pixel(identity_similarity=1.0),
    )
    assert result.track.identity_score == pytest.approx(1.0)


# ------------------------------------------------- the type-level invariant
def test_owner_claim_without_a_gallery_is_unrepresentable() -> None:
    """Card P1-C's "zero owner claims with an empty gallery" row, as a type error."""

    with pytest.raises(ValueError, match="owner_claim without gallery_enrolled"):
        PixelTrackInput(
            transient_track_id="t",
            identity_similarity=0.99,
            visibility=0.9,
            owner_claim=True,
            gallery_enrolled=False,
        )


def test_calibrated_without_enrolled_is_unrepresentable() -> None:
    with pytest.raises(ValueError, match="gallery_calibrated without gallery_enrolled"):
        PixelTrackInput(
            transient_track_id="t",
            identity_similarity=0.5,
            visibility=0.9,
            owner_claim=False,
            gallery_enrolled=False,
            gallery_calibrated=True,
        )


@pytest.mark.parametrize(
    "overrides",
    [
        {"transient_track_id": ""},
        {"identity_similarity": 1.5},
        {"identity_similarity": float("nan")},
        {"visibility": -0.1},
        {"owner_claim": "yes"},
        {"source_timestamp_ns": -1},
        {"appearance_evidence_refs": tuple(str(i) for i in range(17))},
    ],
)
def test_the_seam_validates_its_own_inputs(overrides) -> None:
    with pytest.raises((ValueError, TypeError)):
        _pixel(**overrides)


def test_fuse_rejects_a_pixel_argument_that_is_not_the_seam_type() -> None:
    with pytest.raises(TypeError, match="PixelTrackInput"):
        _fresh_stub().fuse(
            robot_x=0.0,
            robot_y=0.0,
            robot_yaw_rad=0.0,
            now_monotonic_ns=NOW,
            uwb=_uwb(quality=0.9, fresh=True, multipath=False),
            pixel={"identity_similarity": 0.9},  # a mapping is not a measurement
        )


def test_appearance_refs_merge_without_duplicates_and_stay_capped() -> None:
    result = _fresh_stub().fuse(
        robot_x=0.0,
        robot_y=0.0,
        robot_yaw_rad=0.0,
        now_monotonic_ns=NOW,
        uwb=_uwb(quality=0.9, fresh=True, multipath=False),
        vision=_vision(score=0.9, fresh=True, class_id="person"),
        pixel=_pixel(appearance_evidence_refs=("v", "pixel-1")),
    )
    refs = result.track.appearance_evidence_refs
    assert list(refs) == list(dict.fromkeys(refs))
    assert len(refs) <= 16
    assert "pixel-1" in refs


# ------------------------------------------- the end-to-end producer wiring
def test_a_real_tracker_output_flows_into_the_seam() -> None:
    """The producer and the seam agree without either importing the other's DTO."""

    from pathlib import Path

    from parcel_robot.owner_tracking.gallery import build_gallery
    from parcel_robot.owner_tracking.synthetic_clip import (
        ClipScript,
        crop_for,
        histogram_embed_image,
        iter_clip,
    )
    from parcel_robot.owner_tracking.tracker import OwnerTracker

    script = ClipScript.load(Path(__file__).resolve().parent / "data" / "p1c_two_person_clip.json")
    gallery = build_gallery(
        [histogram_embed_image(crop_for(script, i, "owner")) for i in range(6)],
        model="fixture:histogram_embed_image/v1",
        negatives=[histogram_embed_image(crop_for(script, i, "other")) for i in range(6)],
    )
    tracker = OwnerTracker(gallery=gallery, embed_fn=histogram_embed_image)
    stub = _fresh_stub()
    confirmed = 0
    lost = 0
    for _index, rgb, frame in iter_clip(script):
        update = tracker.update(frame, rgb=rgb)
        pixel = update.owner_track.as_fusion_input() if update.owner_claimed else None
        result = stub.fuse(
            robot_x=0.0,
            robot_y=0.0,
            robot_yaw_rad=0.0,
            now_monotonic_ns=NOW,
            uwb=_uwb(quality=0.9, fresh=True, multipath=False),
            pixel=pixel,
        )
        if pixel is None:
            # No owner claim ⇒ nothing measured ⇒ the old prior, and a track
            # that is explicitly NOT confirmed.
            assert result.identity_source == "channel_prior"
            assert result.track.state == "ambiguous"
            lost += 1
        else:
            assert result.identity_source == "pixel_reid"
            assert result.track.state == "confirmed"
            assert result.track.identity_score == pytest.approx(
                update.owner_track.identity_score, abs=1e-9
            )
            confirmed += 1
    assert confirmed > 0 and lost > 0, "the clip must exercise both branches"
