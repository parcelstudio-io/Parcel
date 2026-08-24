"""Capability proof for the H6 noticing seam (``perception.noticing``).

Research folder: ``research/20260823/noticing-loop-perception/`` (DESIGN.md is
the contract, RESULTS.md carries the measured rows). This file pins the
DECISION the measurements are about — a detection becomes a noticing only when
it is far from everything the running gallery holds, clears the quality gates,
and the rate limiter still has room — and the arithmetic the vectorised
measurement gallery had to reproduce.

Deliberately model-free except for one opt-in cell: the whole policy is pure
and must stay testable on a machine with no GPU. The opt-in cell runs the real
loop against a perception daemon when ``PARCEL_H6_SOCKET`` names one, which is
how a verifier re-runs the headline decision through real pixels.
"""

from __future__ import annotations

import math
import os

import pytest

from parcel_robot.perception.noticing import (
    DEFAULT_GALLERY_LIMIT,
    NOTICING_DOES_NOT_PROVE,
    Noticing,
    NoticingGate,
    NoticingLoop,
    NoveltyGallery,
    Observation,
    cosine,
    unit,
)

BIG_BOX = (0, 0, 200, 200)


def _vector(seed: int, dims: int = 16) -> tuple[float, ...]:
    """Deterministic pseudo-random unit-ish vector (no numpy, no RNG state)."""

    return tuple(math.sin(seed * 7.31 + index * 1.97) for index in range(dims))


def _observation(
    seed: int, *, label: str = "person", score: float = 0.6, ns: int = 0,
    box: tuple[int, int, int, int] = BIG_BOX,
) -> Observation:
    return Observation(
        label=label, score=score, box=box, embedding=_vector(seed), monotonic_ns=ns
    )


def test_a_thing_it_has_never_seen_is_noticed_and_the_same_thing_again_is_not() -> None:
    """The whole capability in one cell: novelty admits, familiarity refuses."""

    loop = NoticingLoop(gate=NoticingGate(novelty_tau=0.35, cooldown_s=0.0))
    first = loop.observe(_observation(1))
    assert isinstance(first, Noticing)
    assert first.first_ever and first.novelty == pytest.approx(1.0)

    again = loop.observe(_observation(1, ns=10**9))
    assert again is None, "an identical embedding must read as familiar"
    assert loop.stats.rejected_familiar == 1

    different = loop.observe(_observation(2, ns=2 * 10**9))
    assert different is not None, "an unrelated embedding must still be novel"
    assert 0.0 <= different.nearest_cosine <= 1.0
    assert different.gallery_size == 2


def test_the_quality_gates_refuse_before_the_gallery_is_ever_touched() -> None:
    loop = NoticingLoop(gate=NoticingGate(min_score=0.2, min_box_pixels=32 * 32))
    assert loop.observe(_observation(3, score=0.1)) is None
    assert loop.observe(_observation(4, box=(0, 0, 10, 10))) is None
    assert loop.stats.rejected_score == 1
    assert loop.stats.rejected_size == 1
    assert len(loop.gallery) == 0, "a refused detection must not enter the map"


def test_the_rate_limiter_and_the_cooldown_bound_how_loud_the_loop_can_get() -> None:
    gate = NoticingGate(novelty_tau=0.0, cooldown_s=5.0, max_per_minute=2)
    loop = NoticingLoop(gate=gate)
    # Same label inside the cooldown: one noticing, then silence.
    assert loop.observe(_observation(10, ns=0)) is not None
    assert loop.observe(_observation(11, ns=1_000_000_000)) is None
    assert loop.stats.rejected_cooldown == 1
    # Different labels escape the cooldown but not the per-minute ceiling.
    assert loop.observe(_observation(12, label="dog", ns=6_000_000_000)) is not None
    assert loop.observe(_observation(13, label="tree", ns=7_000_000_000)) is None
    assert loop.stats.rejected_rate_limit == 1
    # A minute later the bucket has drained.
    assert loop.observe(_observation(14, label="tree", ns=70_000_000_000)) is not None


def test_the_gallery_is_bounded_so_a_long_session_cannot_go_silent_by_growth() -> None:
    gallery = NoveltyGallery(limit=4)
    for seed in range(10):
        gallery.add(_vector(seed))
    assert len(gallery) == 4
    assert gallery.limit == 4
    assert NoticingGate().gallery_limit == DEFAULT_GALLERY_LIMIT


def test_novelty_is_one_minus_max_cosine_and_a_dead_encoder_degrades_that_crop() -> None:
    gallery = NoveltyGallery()
    left, right = _vector(20), _vector(21)
    gallery.add(left)
    gallery.add(right)
    probe = _vector(20)
    expected = max(cosine(probe, unit(left)), cosine(probe, unit(right)))
    assert gallery.nearest_cosine(probe) == pytest.approx(expected)
    assert gallery.novelty(probe) == pytest.approx(1.0 - expected)
    # A zero vector (encoder failure on one crop) is neither a crash nor a match.
    assert unit((0.0, 0.0, 0.0)) == (0.0, 0.0, 0.0)
    assert gallery.nearest_cosine((0.0,) * 16) == 0.0


def test_the_vectorised_measurement_gallery_agrees_with_the_pure_one() -> None:
    """The H6 rows were measured with a numpy gallery; it must be the same maths.

    Reproduced here against numpy directly rather than by importing the harness,
    so the product module's semantics are pinned without the test depending on
    research code.
    """

    numpy = pytest.importorskip("numpy")
    gallery = NoveltyGallery(limit=64)
    held = [_vector(seed, dims=32) for seed in range(12)]
    for vector in held:
        gallery.add(vector)
    matrix = numpy.asarray([unit(vector) for vector in held], dtype=numpy.float64)
    for seed in (3, 40, 41):
        probe = _vector(seed, dims=32)
        probe_unit = numpy.asarray(unit(probe), dtype=numpy.float64)
        assert gallery.nearest_cosine(probe) == pytest.approx(
            float((matrix @ probe_unit).max()), abs=1e-9
        )


def test_novelty_of_is_side_effect_free_so_calibration_cannot_move_the_gallery() -> None:
    loop = NoticingLoop()
    loop.observe(_observation(50))
    before = len(loop.gallery)
    scores = [loop.novelty_of(_observation(51)) for _ in range(5)]
    assert len(loop.gallery) == before
    assert len(set(scores)) == 1, "a read must not change what the next read sees"


def test_the_module_says_what_it_does_not_prove() -> None:
    assert len(NOTICING_DOES_NOT_PROVE) >= 2
    assert any("view" in claim.lower() for claim in NOTICING_DOES_NOT_PROVE)


@pytest.mark.skipif(
    not os.environ.get("PARCEL_H6_SOCKET"),
    reason="PARCEL_H6_SOCKET not set (opt-in: needs a running perception daemon)",
)
def test_real_pixels_through_a_daemon_produce_a_noticing_then_familiarity() -> None:
    """Opt-in verifier cell: the same decision, over the real detector/embedder."""

    numpy = pytest.importorskip("numpy")
    from parcel_robot.perception_daemon.client import DaemonClient

    client = DaemonClient(os.environ["PARCEL_H6_SOCKET"])
    frame = numpy.zeros((360, 640, 3), dtype=numpy.uint8)
    frame[80:300, 200:420] = (200, 60, 60)  # one big saturated block
    response = client.detect(frame, ["person", "box", "wall"])
    loop = NoticingLoop(gate=NoticingGate(novelty_tau=0.35, cooldown_s=0.0))
    crop = numpy.ascontiguousarray(frame[80:300, 200:420])
    vector = tuple(float(value) for value in client.embed_image(crop))
    client.close()
    assert response.get("provider_profile") == "cuda_fp16"
    assert len(vector) > 64, "the daemon returned no usable embedding"
    first = loop.observe(
        Observation(label="box", score=0.5, box=(200, 80, 420, 300),
                    embedding=vector, monotonic_ns=0)
    )
    second = loop.observe(
        Observation(label="box", score=0.5, box=(200, 80, 420, 300),
                    embedding=vector, monotonic_ns=10**9)
    )
    assert first is not None and second is None
