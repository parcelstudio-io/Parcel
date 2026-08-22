"""Card P1-C — the owner's appearance gallery: what it refuses, and why.

Every assertion here is about a REFUSAL, because the gallery's whole job is to
be the thing that cannot be talked into saying "yes". The three that matter:

* an empty gallery is unrepresentable (``None`` is the only spelling of
  un-enrolled), so no downstream code can be handed one and claim an owner;
* a gallery whose owner scores no better than a known stranger is REFUSED at
  build time with both numbers printed, rather than written and quietly wrong;
* a file that exists and does not parse RAISES; it never degrades to "absent",
  because that would turn identity off while ``--show`` still said it was on.
"""

from __future__ import annotations

import json
import math
import stat

import pytest

from parcel_robot.owner_tracking.gallery import (
    GALLERY_SCHEMA,
    MIN_THRESHOLD,
    AppearanceGallery,
    AppearanceGalleryError,
    average_embedding,
    build_gallery,
    cosine,
    default_gallery_path,
    load_gallery,
    normalize,
    save_gallery,
    self_consistency,
    threshold_from_self_consistency,
)

#: ``MIN_DIM`` is 8, so every hand-written vector is right-padded to that. The
#: padding is zeros and identical in every vector, so it changes no cosine.
_DIM = 8


def _vec(*values: float) -> tuple[float, ...]:
    padded = list(values) + [0.0] * (_DIM - len(values))
    return normalize(padded)


def _owner_set(jitter: float = 0.02) -> list[tuple[float, ...]]:
    """Six near-parallel vectors: one person, six poses."""

    return [_vec(1.0, jitter * index, 0.05 * (index % 2), 0.0) for index in range(6)]


def _stranger(offset: float = 0.65) -> tuple[float, ...]:
    return _vec(1.0, offset, offset, 0.1)


# ------------------------------------------------------------------ vectors
def test_cosine_is_bounded_and_dimension_strict() -> None:
    assert cosine((1.0, 0.0), (1.0, 0.0)) == pytest.approx(1.0)
    assert cosine((1.0, 0.0), (-1.0, 0.0)) == pytest.approx(-1.0)
    assert -1.0 <= cosine((0.3, -0.9), (0.7, 0.2)) <= 1.0
    with pytest.raises(ValueError):
        cosine((1.0, 0.0), (1.0, 0.0, 0.0))
    with pytest.raises(ValueError):
        cosine((), ())
    # A zero vector scores 0.0 rather than raising: the CALLER refuses it, and
    # the gallery does exactly that at construction.
    assert cosine((0.0, 0.0), (1.0, 0.0)) == 0.0


def test_average_embedding_renormalizes() -> None:
    mean = average_embedding([_vec(1.0, 0.0), _vec(0.0, 1.0)])
    assert math.sqrt(sum(v * v for v in mean)) == pytest.approx(1.0)


def test_self_consistency_is_leave_one_out_max_not_centroid() -> None:
    """The statistic must be the one ``similarity()`` will actually run.

    Five tight vectors plus one outlier. Leave-one-out reports the OUTLIER's
    best match against the others, which is what a runtime query on that pose
    would score. A centroid metric reports something else, and a threshold
    derived from one and applied to the other is a number nobody measured.
    """

    tight = [_vec(1.0, 0.01 * i, 0.0) for i in range(5)]
    outlier = _vec(0.4, 1.0, 0.0)
    measured = self_consistency([*tight, outlier])
    expected = max(cosine(outlier, other) for other in tight)
    assert measured == pytest.approx(expected)
    assert measured < 0.9  # the outlier, not the tight cluster, sets the floor
    with pytest.raises(ValueError):
        self_consistency([_vec(1.0, 0.0)])


def test_threshold_derivation_is_clamped_on_both_sides() -> None:
    assert threshold_from_self_consistency(0.99, slack=0.08) == pytest.approx(0.91)
    assert threshold_from_self_consistency(0.10) == MIN_THRESHOLD  # floor
    assert threshold_from_self_consistency(1.00, slack=0.0) == 0.95  # ceiling


# ------------------------------------------------------------------ the DTO
def test_zero_crops_is_unrepresentable() -> None:
    """The card's "no owner claims with an empty gallery" row, at the type level."""

    with pytest.raises(AppearanceGalleryError, match="not an enrollment"):
        AppearanceGallery(owner_id="owner-1", model="m", embeddings=(), threshold=0.9)


def test_a_zero_vector_crop_is_refused() -> None:
    with pytest.raises(AppearanceGalleryError, match="zero vector"):
        AppearanceGallery(
            owner_id="owner-1",
            model="m",
            embeddings=(_vec(1.0, 0.0), (0.0,) * _DIM),
            threshold=0.9,
        )


def test_an_unnamed_model_is_refused() -> None:
    with pytest.raises(AppearanceGalleryError, match="name the encoder"):
        AppearanceGallery(owner_id="o", model="  ", embeddings=(_vec(1.0, 0.0),), threshold=0.9)


def test_mismatched_dimensions_are_refused_at_build_and_at_query() -> None:
    nine = normalize([1.0] + [0.0] * 8)
    with pytest.raises(AppearanceGalleryError, match="dimension"):
        AppearanceGallery(
            owner_id="o", model="m", embeddings=(_vec(1.0, 0.0), nine), threshold=0.9
        )
    gallery = AppearanceGallery(owner_id="o", model="m", embeddings=(_vec(1.0, 0.0),), threshold=0.9)
    # Scoring against another encoder's output RAISES rather than returning 0.0:
    # a silent 0.0 reads as "not the owner", i.e. a system that works and never
    # recognises anybody.
    with pytest.raises(ValueError):
        gallery.similarity(nine)


def test_similarity_is_max_over_crops_not_centroid() -> None:
    """A pose far from the centroid but close to ONE enrolled crop must score high."""

    front = _vec(1.0, 0.0, 0.0)
    behind = _vec(0.0, 0.0, 1.0)
    gallery = AppearanceGallery(
        owner_id="o", model="m", embeddings=(front, front, front, behind), threshold=0.9
    )
    assert gallery.similarity(behind) == pytest.approx(1.0)
    assert cosine(behind, gallery.centroid) < 0.7


def test_derived_threshold_may_not_sink_below_the_floor() -> None:
    with pytest.raises(AppearanceGalleryError, match="below the floor"):
        AppearanceGallery(owner_id="o", model="m", embeddings=(_vec(1.0, 0.0),), threshold=0.10)


def test_a_calibrated_threshold_may_go_below_the_floor_because_it_was_measured() -> None:
    """The floor guards a GUESS. It must not overrule evidence."""

    gallery = AppearanceGallery(
        owner_id="o",
        model="m",
        embeddings=(_vec(1.0, 0.0), _vec(1.0, 0.01)),
        threshold=0.41,
        negative_reference=0.30,
        calibrated=True,
    )
    assert gallery.threshold == pytest.approx(0.41)


def test_a_calibrated_threshold_below_its_own_negative_is_refused() -> None:
    with pytest.raises(AppearanceGalleryError, match="does not clear its own measured negative"):
        AppearanceGallery(
            owner_id="o",
            model="m",
            embeddings=(_vec(1.0, 0.0),),
            threshold=0.60,
            negative_reference=0.70,
            calibrated=True,
        )


def test_calibrated_without_a_negative_reference_is_refused() -> None:
    with pytest.raises(AppearanceGalleryError, match="without a measured negative_reference"):
        AppearanceGallery(
            owner_id="o", model="m", embeddings=(_vec(1.0, 0.0),), threshold=0.9, calibrated=True
        )


# ------------------------------------------------------------------- build
def test_build_without_negatives_is_uncalibrated_and_says_so() -> None:
    gallery = build_gallery(_owner_set(), model="test/v1")
    assert gallery.calibrated is False
    assert gallery.negative_reference == -1.0
    assert gallery.threshold == pytest.approx(
        threshold_from_self_consistency(gallery.measured_self_consistency)
    )


def test_build_with_negatives_puts_the_threshold_in_the_measured_gap() -> None:
    owner = _owner_set()
    gallery = build_gallery(owner, model="test/v1", negatives=[_stranger()])
    assert gallery.calibrated is True
    assert gallery.negative_reference < gallery.threshold < gallery.measured_self_consistency
    assert gallery.threshold == pytest.approx(
        0.5 * (gallery.measured_self_consistency + gallery.negative_reference)
    )
    # And the calibration does what it is for.
    assert gallery.similarity(_stranger()) < gallery.threshold
    assert gallery.similarity(owner[0]) >= gallery.threshold


def test_build_refuses_an_enrollment_with_no_separation_and_prints_both_numbers() -> None:
    """SEEDED RED for "a gallery that cannot identify its owner is still written"."""

    owner = _owner_set()
    impostor = owner[0]  # a "negative" that is literally an enrolled crop
    with pytest.raises(AppearanceGalleryError) as excinfo:
        build_gallery(owner, model="test/v1", negatives=[impostor])
    message = str(excinfo.value)
    assert "cannot identify its owner" in message
    assert "agree with each other at" in message and "NON-owner crop scores" in message


def test_build_refuses_an_empty_negatives_sequence() -> None:
    with pytest.raises(AppearanceGalleryError, match="supplied but empty"):
        build_gallery(_owner_set(), model="test/v1", negatives=[])


def test_build_needs_two_crops_to_measure_anything() -> None:
    with pytest.raises(AppearanceGalleryError, match="at least two crops"):
        build_gallery([_vec(1.0, 0.0)], model="test/v1")


# ------------------------------------------------------------------ on disk
def test_save_is_0600_and_atomic_and_round_trips(tmp_path) -> None:
    gallery = build_gallery(_owner_set(), model="test/v1", negatives=[_stranger()])
    target = tmp_path / "nested" / "owner_appearance_gallery.json"
    written = save_gallery(gallery, target)
    assert written == target
    mode = stat.S_IMODE(target.stat().st_mode)
    assert mode == 0o600, f"gallery mode is {oct(mode)}"
    assert not list(tmp_path.rglob("*.tmp"))  # the temp file is gone
    back = load_gallery(target)
    assert back is not None
    assert back.crops == gallery.crops
    assert back.calibrated is True
    assert back.threshold == pytest.approx(gallery.threshold)
    assert back.negative_reference == pytest.approx(gallery.negative_reference)
    assert back.model == gallery.model
    assert back.source == str(target)


def test_absent_is_none_and_broken_raises(tmp_path) -> None:
    assert load_gallery(tmp_path / "nothing.json") is None
    broken = tmp_path / "broken.json"
    broken.write_text("{not json", encoding="utf-8")
    with pytest.raises(AppearanceGalleryError, match="cannot be read"):
        load_gallery(broken)


@pytest.mark.parametrize(
    ("mutate", "match"),
    [
        (lambda d: d.update(schema="parcel.something_else.v1"), "declares schema"),
        (lambda d: d.update(embeddings=[]), "carries no crops"),
        (lambda d: d.update(model=""), "does not name the encoder"),
        (lambda d: d.pop("threshold"), "carries no numeric threshold"),
        (lambda d: d.update(embeddings=[["x", "y"]]), "non-numeric"),
        (lambda d: d.update(calibrated="yes"), "non-boolean"),
    ],
)
def test_present_and_broken_never_degrades_to_absent(tmp_path, mutate, match) -> None:
    gallery = build_gallery(_owner_set(), model="test/v1", negatives=[_stranger()])
    payload = dict(gallery.as_dict())
    mutate(payload)
    target = tmp_path / "g.json"
    target.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(AppearanceGalleryError, match=match):
        load_gallery(target)


def test_the_written_file_names_its_schema_and_its_operating_point(tmp_path) -> None:
    gallery = build_gallery(_owner_set(), model="test/v1", negatives=[_stranger()])
    target = save_gallery(gallery, tmp_path / "g.json")
    payload = json.loads(target.read_text(encoding="utf-8"))
    assert payload["schema"] == GALLERY_SCHEMA
    # The operating point a verdict was produced under must be recoverable from
    # the artefact, not from whatever the code defaults to today.
    for key in ("threshold", "min_margin", "measured_self_consistency", "negative_reference"):
        assert key in payload, key
    assert payload["calibrated"] is True


def test_default_path_is_outside_the_repo_and_beside_the_config(tmp_path) -> None:
    beside = default_gallery_path(tmp_path / "realtime.yaml")
    assert beside.parent == tmp_path
    fallback = default_gallery_path(None)
    assert fallback.parent.name == "parcel"
    assert ".config" in str(fallback)
