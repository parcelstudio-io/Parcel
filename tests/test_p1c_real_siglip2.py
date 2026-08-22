"""Card P1-C — the same rows, against the REAL SigLIP-2 fp16 encoder.

``test_p1c_owner_tracker.py`` proves the mechanism with a colour-histogram
stand-in, on any host, in under a second. That is worth having and it is not
enough: a re-ID design that only works because the stand-in separates two people
at 0.28 has proved nothing about the encoder the robot will actually run.

So this file runs the same clip through
``instructnav.siglip2_onnx``'s ``embed_image`` at ``cuda_fp16`` (P0-C's
installed path) and measures four things that the stand-in cannot answer:

  R6  owner-vs-stranger separation on held-out frames      pre-registered ≥ 0.05
  R7  crop-embed latency, cuda_fp16                        pre-registered p50 ≤ 15 ms
  R6b a CALIBRATED gallery makes zero false owner claims   pre-registered 0
  R6c an UNCALIBRATED gallery does NOT                     the measured defect

R6c is the important one and it is asserted as a **positive**: this file pins
the fact that the derived-threshold fallback claims a stranger. If a future
change makes that stop being true, the enroller's insistence on negatives can
be relaxed — and this test failing is how anyone would find out.

Skipped, never silently passed, when the weights are absent or the env switch is
off. The exact command is in ``scrum/20260822/task_8/P1C_STATUS.md`` §5.
"""

from __future__ import annotations

import math
import os
import statistics
import time
from pathlib import Path

import pytest

from parcel_robot.owner_tracking.embedder import (
    PROVIDER_ENV,
    SIGLIP2_ENABLE_ENV,
    default_weights_dir,
    resolve_embed_fn,
)
from parcel_robot.owner_tracking.gallery import build_gallery, cosine
from parcel_robot.owner_tracking.synthetic_clip import ClipScript, crop_for, iter_clip
from parcel_robot.owner_tracking.tracker import OwnerTracker, OwnerTrackerConfig

CLIP_PATH = Path(__file__).resolve().parent / "data" / "p1c_two_person_clip.json"
ENROLLMENT_FRAMES = (0, 1, 2, 3, 4, 5)
OCCLUSION_FRAMES = (13, 14, 15, 16)

#: Pre-registered before the first measurement. See P1C_STATUS.md §2.
PREREGISTERED_MIN_SEPARATION = 0.05
PREREGISTERED_P50_MS = 15.0

pytestmark = pytest.mark.skipif(
    os.environ.get(SIGLIP2_ENABLE_ENV, "").strip().lower() not in {"1", "true", "yes", "on"},
    reason=f"real-encoder rows are opt-in: set {SIGLIP2_ENABLE_ENV}=1",
)


@pytest.fixture(scope="module")
def encoder():
    weights = default_weights_dir()
    if not weights.is_dir():
        pytest.skip(f"SigLIP-2 weights absent under {weights}; run scripts/fetch_siglip2.sh")
    resolution = resolve_embed_fn()
    if not resolution.available:
        pytest.skip(f"no usable SigLIP-2 encoder: {resolution.reason}")
    return resolution


@pytest.fixture(scope="module")
def script() -> ClipScript:
    return ClipScript.load(CLIP_PATH)


@pytest.fixture(scope="module")
def vectors(encoder, script):
    """Every crop in the clip, embedded once. Frames 0-5 are the enrollment set."""

    embed = encoder.embed_fn
    owner = {}
    other = {}
    for index in range(script.frame_count):
        crop = crop_for(script, index, "owner")
        if crop is not None:
            owner[index] = embed(crop)
        other[index] = embed(crop_for(script, index, "other"))
    return owner, other


def test_the_encoder_is_the_vision_model_on_the_gpu(encoder) -> None:
    """The gallery header must name the encoder that produced the vectors."""

    assert "vision_model" in encoder.model, encoder.model
    requested = os.environ.get(PROVIDER_ENV, "").strip().lower()
    if requested == "cuda_fp16":
        assert encoder.provider == "cuda_fp16", encoder.provider
        assert "fp16" in encoder.model
    assert encoder.dim >= 256


def test_R6_owner_and_stranger_separate_on_held_out_frames(encoder, script, vectors) -> None:
    owner, other = vectors
    gallery_vectors = [owner[i] for i in ENROLLMENT_FRAMES]
    held_out_owner = [
        max(cosine(owner[i], g) for g in gallery_vectors)
        for i in range(6, script.frame_count)
        if i in owner
    ]
    held_out_other = [
        max(cosine(other[i], g) for g in gallery_vectors) for i in range(6, script.frame_count)
    ]
    separation = statistics.mean(held_out_owner) - statistics.mean(held_out_other)
    assert separation >= PREREGISTERED_MIN_SEPARATION, (
        f"owner mean {statistics.mean(held_out_owner):.4f} vs stranger mean "
        f"{statistics.mean(held_out_other):.4f} — separation {separation:.4f}"
    )
    # And the thing the docstring of gallery.py claims: the ABSOLUTE cosines sit
    # high and close together, which is why an absolute floor cannot be guessed.
    assert min(held_out_owner) > 0.85
    assert max(held_out_other) > 0.85


def test_R7_crop_embed_latency_on_the_shipping_path(encoder, script) -> None:
    embed = encoder.embed_fn
    crops = [crop_for(script, i % 13, pid) for i in range(30) for pid in ("owner", "other")]
    crops = [c for c in crops if c is not None]
    for crop in crops[:4]:  # warm the session; the first call builds the graph
        embed(crop)
    samples = []
    for crop in crops:
        started = time.perf_counter()
        embed(crop)
        samples.append((time.perf_counter() - started) * 1000.0)
    p50 = statistics.median(samples)
    assert p50 <= PREREGISTERED_P50_MS, f"p50 {p50:.2f} ms over {len(samples)} crops"


def test_R6b_a_calibrated_gallery_makes_zero_false_owner_claims(encoder, script, vectors) -> None:
    """The stranger is alone in frame for four frames. Nobody may be claimed."""

    owner, other = vectors
    gallery = build_gallery(
        [owner[i] for i in ENROLLMENT_FRAMES],
        model=encoder.model,
        provider=encoder.provider,
        negatives=[other[i] for i in ENROLLMENT_FRAMES],
    )
    assert gallery.calibrated is True
    tracker = OwnerTracker(gallery=gallery, embed_fn=encoder.embed_fn)
    false_claims = []
    owner_ids = set()
    claimed_frames: list[int] = []
    labels_by_frame: dict[int, str] = {}
    for index, rgb, frame in iter_clip(script):
        update = tracker.update(frame, rgb=rgb)
        labels_by_frame[index] = "owner" if update.owner_claimed else update.state
        if not update.owner_claimed:
            continue
        claimed_frames.append(index)
        owner_ids.add(update.owner_track.track_id)
        poses = script.frames[index]["poses"]
        nearest = min(
            ((name, math.hypot(update.owner_track.world_x - p["x"], update.owner_track.world_y - p["y"]))
             for name, p in poses.items() if p["visible"]),
            key=lambda item: item[1],
        )[0]
        if nearest != "owner":
            false_claims.append(index)
    # Every occluded frame must be an honest "I do not see you", asserted on the
    # per-frame CLAIM record. The first draft of this block wrote
    # ``for index in OCCLUSION_FRAMES: assert index not in owner_ids`` — an int
    # against a set of track-id STRINGS, so it could never fail and proved
    # nothing at all. Caught in verification.
    #
    # Asserted BEFORE the stranger/identity rows on purpose: a build that keeps
    # the claim while coasting also trips ``false_claims`` (a coasted track's
    # stale pose sits nearest the only visible person, who is the stranger), and
    # if that fired first this row would never be the one under test. Seeded RED
    # receipt in scrum/20260822/task_8/P1C_STATUS.md §11.
    claimed_while_occluded = sorted(set(claimed_frames) & set(OCCLUSION_FRAMES))
    assert claimed_while_occluded == [], (
        f"an owner was claimed while the owner was occluded, on frames "
        f"{claimed_while_occluded}"
    )
    assert all(labels_by_frame[i] == "searching" for i in OCCLUSION_FRAMES), {
        i: labels_by_frame[i] for i in OCCLUSION_FRAMES
    }
    # ...and the converse, so "no claims on occluded frames" cannot pass by the
    # tracker simply never claiming anybody.
    assert claimed_frames, "the clip produced no owner claims at all"
    assert len(claimed_frames) >= script.frame_count - len(OCCLUSION_FRAMES) - 4

    assert false_claims == [], f"claimed the stranger on frames {false_claims}"
    assert len(owner_ids) == 1, f"the owner changed identity mid-clip: {owner_ids}"


def test_R6c_the_uncalibrated_fallback_is_measurably_unsafe(encoder, script, vectors) -> None:
    """The measured reason ``--negative-frames`` is not optional.

    Asserted as a POSITIVE so it cannot rot into a vacuous pass: on this clip,
    with these weights, the derived-threshold gallery claims the stranger. The
    day that stops being true, this test fails and somebody gets to decide
    whether the enroller may relax.
    """

    owner, other = vectors
    uncalibrated = build_gallery([owner[i] for i in ENROLLMENT_FRAMES], model=encoder.model)
    assert uncalibrated.calibrated is False
    stranger_scores = [
        uncalibrated.similarity(other[i]) for i in range(6, script.frame_count)
    ]
    assert max(stranger_scores) > uncalibrated.threshold, (
        f"the derived floor {uncalibrated.threshold:.4f} now excludes the stranger "
        f"(best {max(stranger_scores):.4f}); re-read the enroller's refusal"
    )


def test_R3b_seeded_RED_position_dominated_association_swaps_on_the_real_encoder(
    encoder, script, vectors
) -> None:
    """RED-2, re-measured on the encoder the robot will actually run.

    ``test_p1c_owner_tracker.py`` proves this with the colour-histogram
    stand-in, which scores the stranger at 0.28 against the owner's crops — an
    appearance signal so strong that "appearance beats geometry" is nearly
    free. SigLIP-2 scores the same stranger at ~0.92. If the swap guard only
    worked because the stand-in separates people easily, it is a claim about
    the stand-in and not about the robot, so the RED has to be run here too.

    Promoted out of the executor's scratch notes during verification, where it
    had been measured once and never pinned.
    """

    owner, other = vectors
    gallery = build_gallery(
        [owner[i] for i in ENROLLMENT_FRAMES],
        model=encoder.model,
        negatives=[other[i] for i in ENROLLMENT_FRAMES],
    )

    def owner_track_ids(config: OwnerTrackerConfig | None) -> set[str]:
        tracker = OwnerTracker(gallery=gallery, embed_fn=encoder.embed_fn, config=config)
        found: set[str] = set()
        for _index, rgb, frame in iter_clip(script):
            update = tracker.update(frame, rgb=rgb)
            if update.owner_claimed:
                found.add(update.owner_track.track_id)
        return found

    red = owner_track_ids(
        OwnerTrackerConfig(appearance_weight=0.01, position_weight=10.0, max_assoc_cost=20.0)
    )
    green = owner_track_ids(None)
    assert len(red) > 1, f"seeded RED did not go red on the real encoder: {red}"
    assert len(green) == 1, f"the shipped config swapped on the real encoder: {green}"


def test_R4_the_real_encoder_also_produces_a_varying_sub_unit_confidence(
    encoder, script, vectors
) -> None:
    owner, other = vectors
    gallery = build_gallery(
        [owner[i] for i in ENROLLMENT_FRAMES],
        model=encoder.model,
        negatives=[other[i] for i in ENROLLMENT_FRAMES],
    )
    tracker = OwnerTracker(gallery=gallery, embed_fn=encoder.embed_fn)
    held_out = []
    for index, rgb, frame in iter_clip(script):
        update = tracker.update(frame, rgb=rgb)
        if update.owner_claimed and index not in ENROLLMENT_FRAMES:
            held_out.append(update.owner_track.identity_score)
    assert held_out
    assert all(0.0 < score < 1.0 for score in held_out), held_out
    assert len({round(score, 6) for score in held_out}) >= 5
