"""Map hygiene: the gates that decide what is allowed to become a *place*.

REVISION 2026-08-21 §3 calls this a safety surface, and it is the only part of
C-2 whose failure mode is a robot walking somewhere real because of something
that is not there.

The three gates, and why each is shaped the way it is
-----------------------------------------------------

**(a) Volatile-class exclusion.** A person is not a place. Neither is a car, a
bicycle or a dog. They are observed, counted and reportable — they are refused
*persistence*, not perception. This gate is unconditional and has no threshold
to tune, which is what makes it the one defence that cannot be quietly
weakened.

**(b) Class-conditional metric size + depth planarity.** This is the
picture-of-a-thing defence. A photorealistic poster fires the detector, is
re-observed on every patrol so its evidence *strengthens*, sits above navigable
ground, and passes every one of PG-3's four signals. What it cannot do is have
the metric size and the depth relief of the thing it depicts. So:

* **Size** is computed from geometry the stream actually carries — the
  detection box back-projected at the localized depth through the real D455
  focal lengths. A 0.6 m x 0.3 m "storefront" is not a storefront.
* **Relief** is the RGB/depth-agreement half. It needs a *measured* depth
  spread across the box, and this is the honest part: C-1's
  ``CameraDetectionRecord`` does **not** carry one.
  ``CameraDetectionRecord.sigma_range_m`` looks like it would do —
  it is a metre-valued depth uncertainty right there on the record — and it is
  useless here, because ``pixel_detections.py`` computes it as
  ``D455_DEPTH_SIGMA_COEFF_PER_M * range_m ** 2``: a *modelled* sensor sigma
  that is a pure function of range and contains exactly zero information about
  whether the thing is flat. Using it as a planarity signal would produce a
  gate that reports verdicts, looks wired, and cannot see a poster.

  So relief is an **optional measured input**. When the producer supplies one
  (:func:`relief_from_depth_patch`), the gate applies. When it does not, the
  entry is marked :data:`NOTE_RELIEF_UNVERIFIED` and **the picture-defence
  claim is not made for it** — the map says so in the entry rather than
  implying a check that never ran.

**(c) Decay quarantine.** Lives in :mod:`.entries` (status) and :mod:`.online_map`
(retrieval), because "excluded from retrieval" is a property of the query path,
not of a gate function.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from .entries import label_tokens, normalize_label

# --------------------------------------------------------------------------
# (a) Volatile classes — never persisted as places.
# --------------------------------------------------------------------------

#: Tokens that make a detection a moving thing rather than a place. Matched on
#: normalized TOKENS, so "a person", "person walking" and "Person" are one
#: rule, and "person crossing sign" is deliberately NOT (see the exemptions).
VOLATILE_TOKENS: frozenset[str] = frozenset(
    {
        # people
        "person", "people", "pedestrian", "man", "woman", "child", "kid",
        "boy", "girl", "human", "cyclist", "rider", "jogger", "runner",
        "worker", "crowd",
        # animals
        "dog", "cat", "bird", "animal", "pet", "squirrel",
        # vehicles
        "car", "truck", "bus", "van", "taxi", "vehicle", "motorcycle",
        "motorbike", "scooter", "bicycle", "bike", "stroller", "wheelchair",
        "skateboard", "trailer", "forklift", "cart",
    }
)

#: A volatile token inside one of these phrases describes a FIXED thing.
#: "bike rack" is furniture; "person crossing sign" is a sign. Without this the
#: exclusion would delete real places for containing a word.
VOLATILE_EXEMPT_TOKENS: frozenset[str] = frozenset(
    {"rack", "sign", "signal", "crossing", "lane", "parking", "stand",
     "shelter", "stop", "station", "statue", "sculpture", "mural", "poster",
     "billboard", "advertisement", "screen", "display", "shop", "store"}
)


def is_volatile_label(label: object) -> bool:
    """Is this label a moving thing, and therefore never a place?

    ``True`` means: observe it, count it, report it, and do **not** write it to
    the store. DualMap measured what happens when you do not do this — static
    map accuracy 70.5% -> 60.3% on HM3D, 92.3% -> 69.2% in a real meeting room.
    """

    tokens = set(label_tokens(label))
    if not tokens & VOLATILE_TOKENS:
        return False
    # A phrase that also names a fixed thing describes the fixed thing.
    return not (tokens & VOLATILE_EXEMPT_TOKENS)


# --------------------------------------------------------------------------
# (b) Class-conditional metric priors.
# --------------------------------------------------------------------------

#: Hygiene verdict notes. Machine-readable; they end up on the entry and in the
#: status doc's tables, so they are named rather than free text.
NOTE_OK = "ok"
NOTE_VOLATILE = "volatile_class_refused"
NOTE_TOO_SMALL = "metric_size_too_small"
NOTE_TOO_LARGE = "metric_size_too_large"
NOTE_PLANAR = "depth_planar_refused"
NOTE_RELIEF_UNVERIFIED = "relief_unverified"


@dataclass(frozen=True, slots=True)
class SizePrior:
    """What metric extents and relief a real instance of a class has.

    ``min_relief_m`` is the depth variation a *solid* instance must show across
    its own bounding box. It is deliberately small: the gate is meant to catch
    things that are FLAT (a printed poster, a decal, a screen), not to
    adjudicate shape.
    """

    min_w_m: float
    max_w_m: float
    min_h_m: float
    max_h_m: float
    min_relief_m: float

    def __post_init__(self) -> None:
        for name in ("min_w_m", "max_w_m", "min_h_m", "max_h_m", "min_relief_m"):
            value = float(getattr(self, name))
            if not math.isfinite(value) or value < 0.0:
                raise ValueError(f"SizePrior.{name} must be finite and non-negative")
        if self.min_w_m >= self.max_w_m or self.min_h_m >= self.max_h_m:
            raise ValueError("SizePrior bounds must be ordered and non-degenerate")


#: The fail-safe row. Wide enough to admit anything physically plausible and
#: still refuse a 2 cm speck or a 100 m object, with NO relief requirement —
#: an unknown class gets no picture-defence claim, and the entry says so.
DEFAULT_PRIOR = SizePrior(
    min_w_m=0.03, max_w_m=80.0, min_h_m=0.03, max_h_m=60.0, min_relief_m=0.0
)

#: Priors for the corpus classes this scene actually contains, sourced from the
#: geometry in ``evals/nav_instruct/scene_truth.json`` plus ordinary physical
#: ranges. Anything absent falls through to :data:`DEFAULT_PRIOR`.
SIZE_PRIORS: Mapping[str, SizePrior] = {
    "lamppost": SizePrior(0.04, 1.2, 1.5, 9.0, 0.03),
    "lamp post": SizePrior(0.04, 1.2, 1.5, 9.0, 0.03),
    "street light": SizePrior(0.04, 1.2, 1.5, 9.0, 0.03),
    "tree": SizePrior(0.20, 8.0, 1.5, 20.0, 0.08),
    "planter": SizePrior(0.25, 4.0, 0.15, 2.0, 0.04),
    "bench": SizePrior(0.60, 4.0, 0.30, 1.6, 0.04),
    "door": SizePrior(0.50, 2.2, 1.40, 3.2, 0.01),
    "doorway": SizePrior(0.50, 2.2, 1.40, 3.2, 0.01),
    "building": SizePrior(1.50, 90.0, 1.80, 60.0, 0.05),
    "storefront": SizePrior(1.20, 40.0, 1.60, 20.0, 0.05),
    "shop": SizePrior(1.20, 40.0, 1.60, 20.0, 0.05),
    "coffee shop": SizePrior(1.20, 40.0, 1.60, 20.0, 0.05),
    "awning": SizePrior(0.80, 20.0, 0.15, 2.0, 0.02),
    "trash can": SizePrior(0.25, 1.5, 0.40, 1.5, 0.05),
    "fire hydrant": SizePrior(0.15, 0.8, 0.40, 1.2, 0.05),
    # Volatile, so gate (a) refuses them first; the row exists so that a
    # DIAGNOSTIC size check on a person is still class-correct.
    "person": SizePrior(0.20, 1.6, 0.80, 2.4, 0.06),
}


def prior_for(label: object) -> tuple[SizePrior, str]:
    """The prior for a label, and the key it matched.

    Falls back through the whole normalized phrase, then any single token, then
    :data:`DEFAULT_PRIOR`. The matched key is returned so an entry can record
    *which* prior judged it rather than leaving the reader to re-derive it.
    """

    phrase = normalize_label(label)
    if phrase in SIZE_PRIORS:
        return SIZE_PRIORS[phrase], phrase
    for token in label_tokens(label):
        if token in SIZE_PRIORS:
            return SIZE_PRIORS[token], token
    return DEFAULT_PRIOR, ""


# --------------------------------------------------------------------------
# Relief — the measured half of the picture defence.
# --------------------------------------------------------------------------


def relief_from_depth_patch(
    patch: Sequence[Sequence[float]] | Any,
    *,
    depth_min_m: float = 0.05,
    depth_max_m: float = 50.0,
) -> tuple[float | None, int]:
    """Measured depth relief across a detection box, and its sample count.

    Relief is the robust peak-to-plateau spread of the *valid* depths inside
    the box: ``p90 - p10`` of the finite in-range returns. A printed poster or
    a decal is a plane and yields ~0; a solid object yields its own depth
    extent. Returns ``(None, 0)`` when there is nothing measurable, which the
    caller must treat as "unknown", never as "flat".

    Pure stdlib and pure function — it is defined HERE rather than in the
    ingress because C-2 must not touch detector/ingress internals, and because
    a relief number the map computes from a patch it was handed is a number the
    map can be held to.
    """

    values: list[float] = []
    try:
        rows = list(patch)
    except TypeError as exc:  # pragma: no cover - defensive
        raise TypeError("depth patch must be a 2-D sequence") from exc
    for row in rows:
        try:
            cells = list(row)
        except TypeError as exc:
            raise TypeError("depth patch must be a 2-D sequence") from exc
        for cell in cells:
            try:
                value = float(cell)
            except (TypeError, ValueError):
                continue
            if not math.isfinite(value):
                continue
            if value <= float(depth_min_m) or value > float(depth_max_m):
                continue
            values.append(value)
    if len(values) < 8:
        return None, len(values)
    values.sort()
    lo = values[max(0, int(0.10 * (len(values) - 1)))]
    hi = values[min(len(values) - 1, round(0.90 * (len(values) - 1)))]
    return max(0.0, float(hi - lo)), len(values)


# --------------------------------------------------------------------------
# The verdict.
# --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class HygieneVerdict:
    """May this observation become (or strengthen) a persisted place?

    ``admitted`` False means the observation is refused persistence. It is
    still a real observation and callers are expected to keep counting it —
    refusing to persist a thing is not the same as claiming not to have seen
    it, and conflating the two is how a robot stops reporting the pedestrian in
    front of it.
    """

    admitted: bool
    note: str
    prior_key: str
    extent_w_m: float
    extent_h_m: float
    relief_m: float | None
    #: True only when a MEASURED relief was available and passed. False both
    #: when relief failed and when nothing measured one — read ``note``.
    relief_verified: bool

    def as_dict(self) -> dict[str, Any]:
        return {
            "admitted": self.admitted,
            "note": self.note,
            "prior_key": self.prior_key,
            "extent_w_m": round(self.extent_w_m, 4),
            "extent_h_m": round(self.extent_h_m, 4),
            "relief_m": (
                round(self.relief_m, 4) if self.relief_m is not None else None
            ),
            "relief_verified": self.relief_verified,
        }


def metric_extents(
    box: Sequence[float],
    depth_m: float,
    *,
    fx: float,
    fy: float,
) -> tuple[float, float]:
    """Back-project a detection box to metres at the localized depth.

    ``w = (u1-u0) * D / fx``, ``h = (v1-v0) * D / fy`` — the same pinhole
    relation :func:`parcel_robot.camera_channel.ingress.radius_m_from_box_depth`
    uses for footprint radius, kept here as full width and height because the
    size gate needs both axes separately (a decal is wrong in BOTH; a partly
    occluded lamppost is only ever short, never thin).
    """

    if len(box) != 4:
        raise ValueError("box must be (u0, v0, u1, v1)")
    depth = float(depth_m)
    if not math.isfinite(depth) or depth <= 0.0:
        raise ValueError("depth_m must be finite and positive")
    for name, value in (("fx", fx), ("fy", fy)):
        if not math.isfinite(float(value)) or float(value) <= 0.0:
            raise ValueError(f"{name} must be finite and positive")
    u0, v0, u1, v1 = (float(v) for v in box)
    w_px = abs(u1 - u0)
    h_px = abs(v1 - v0)
    return (w_px * depth / float(fx), h_px * depth / float(fy))


def screen_observation(
    *,
    label: str,
    extent_w_m: float,
    extent_h_m: float,
    relief_m: float | None,
    relief_samples: int = 0,
) -> HygieneVerdict:
    """Apply gates (a) and (b) to one observation.

    Order matters and is deliberate: the volatile check runs FIRST and needs no
    measurement, so an unmeasurable person is still refused. A gate that can
    only fire when its inputs happen to be present is not a safety gate.
    """

    prior, prior_key = prior_for(label)
    w = float(extent_w_m)
    h = float(extent_h_m)

    if is_volatile_label(label):
        return HygieneVerdict(
            admitted=False,
            note=NOTE_VOLATILE,
            prior_key=prior_key,
            extent_w_m=w,
            extent_h_m=h,
            relief_m=relief_m,
            relief_verified=False,
        )

    if w < prior.min_w_m or h < prior.min_h_m:
        return HygieneVerdict(
            admitted=False,
            note=NOTE_TOO_SMALL,
            prior_key=prior_key,
            extent_w_m=w,
            extent_h_m=h,
            relief_m=relief_m,
            relief_verified=False,
        )
    if w > prior.max_w_m or h > prior.max_h_m:
        return HygieneVerdict(
            admitted=False,
            note=NOTE_TOO_LARGE,
            prior_key=prior_key,
            extent_w_m=w,
            extent_h_m=h,
            relief_m=relief_m,
            relief_verified=False,
        )

    if relief_m is None or relief_samples <= 0:
        # Admitted on size alone, and SAID SO. The picture-defence claim is not
        # made for this entry.
        return HygieneVerdict(
            admitted=True,
            note=NOTE_RELIEF_UNVERIFIED,
            prior_key=prior_key,
            extent_w_m=w,
            extent_h_m=h,
            relief_m=None,
            relief_verified=False,
        )

    if float(relief_m) < prior.min_relief_m:
        return HygieneVerdict(
            admitted=False,
            note=NOTE_PLANAR,
            prior_key=prior_key,
            extent_w_m=w,
            extent_h_m=h,
            relief_m=float(relief_m),
            relief_verified=False,
        )

    return HygieneVerdict(
        admitted=True,
        note=NOTE_OK,
        prior_key=prior_key,
        extent_w_m=w,
        extent_h_m=h,
        relief_m=float(relief_m),
        relief_verified=True,
    )


__all__ = [
    "DEFAULT_PRIOR",
    "NOTE_OK",
    "NOTE_PLANAR",
    "NOTE_RELIEF_UNVERIFIED",
    "NOTE_TOO_LARGE",
    "NOTE_TOO_SMALL",
    "NOTE_VOLATILE",
    "SIZE_PRIORS",
    "VOLATILE_EXEMPT_TOKENS",
    "VOLATILE_TOKENS",
    "HygieneVerdict",
    "SizePrior",
    "is_volatile_label",
    "metric_extents",
    "prior_for",
    "relief_from_depth_patch",
    "screen_observation",
]
