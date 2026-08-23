"""The owner's appearance gallery — a handful of enrolled crops, on disk.

Card P1-C. The voice side of this household already solved the same problem
(``realtime/voice_identity.py``): a small file, outside the repository, mode
0600, that names the model its vectors were computed with, and whose loader
distinguishes ABSENT (nobody enrolled) from PRESENT-AND-BROKEN (an operator
error that must be read, not absorbed). This module is the appearance twin of
that file, and it is deliberately a SEPARATE file from the voice profile and
from ``parcel_memory.sqlite3``:

* separate from the memory store because R27's isolation rule says the owner's
  sqlite is never opened read-write by a test or a harness, and an enrollment
  is exactly the kind of thing that would want to write to it;
* separate from the voice profile because the two enrollments have different
  lifetimes (a haircut invalidates one and not the other) and different models,
  and one file with two meanings is how a threshold silently starts being
  scored in the wrong embedding space.

WHY THE MODEL NAME IS IN THE FILE
---------------------------------
Identical to the voice argument. A cosine of 0.83 means "the owner" only inside
the geometry of the network that produced both vectors. A gallery that did not
name its encoder could be scored against a threshold measured on a different
one, and the number would look exactly as convincing as a real one.

WHY THERE IS A ``threshold`` **AND** A ``min_margin``
-----------------------------------------------------
An absolute cosine floor alone is not a defensible owner test for SigLIP-2 image
embeddings: the encoder is trained for image↔text alignment, not for face/person
verification, so two *different* people photographed in the same room can sit
much closer together than two crops of the same person in different poses. So
the owner claim in :mod:`parcel_robot.owner_tracking.tracker` needs BOTH:

* ``threshold`` — an absolute floor, and it is **derived from the enrollment's
  own measured self-consistency**, not invented. If the owner's own crops only
  agree with each other at 0.78, a runtime floor of 0.9 would never fire and a
  floor of 0.5 would admit the sofa. See :func:`threshold_from_self_consistency`.
* ``min_margin`` — the enrolled person must beat every *other* person in the
  same frame by this much. That is a discriminative test, and unlike the floor
  it does not depend on the absolute scale of the encoder at all.

Both are stored in the file, so the number a verdict was produced under is
recoverable from the artefact rather than from whatever the code happens to
default to today.

WHAT AN EMPTY GALLERY MEANS
---------------------------
It is unrepresentable. :class:`AppearanceGallery` refuses to exist with zero
crops, exactly as the voice loader refuses a zero vector, because "enrolled with
nothing" and "not enrolled" are the same fact and only one of them should have a
spelling. Un-enrolled is ``None``, and ``None`` can never produce an owner claim
(:mod:`.tracker`, and the contract-level guard in
``uwb.fusion.PixelTrackInput``).
"""

from __future__ import annotations

import json
import math
import os
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

# ---- CARD HW-1 py310-clean (scrum/20260822/task_35) ----
# ``datetime.UTC`` is 3.11+; the Orin's JetPack CPython is 3.10 (design §5.1,
# seam S22). ``datetime.UTC`` IS ``timezone.utc`` — the same singleton — so the
# alias keeps every call site, ``tzinfo`` identity and ``isoformat`` unchanged.
UTC = timezone.utc
# ---- END CARD HW-1 py310-clean ----

#: Schema tag written into every gallery file. A file that does not carry it is
#: refused rather than guessed at.
GALLERY_SCHEMA = "parcel.owner_appearance_gallery.v1"

#: File name, beside the realtime config or under the fallback directory.
GALLERY_NAME = "owner_appearance_gallery.json"

#: Where the gallery lives when no realtime config path is supplied. Same
#: directory the voice profile falls back to — one place outside the repo where
#: this household keeps owner-identifying material.
GALLERY_FALLBACK_DIR = Path("~/.config/parcel")

#: 0600. The bytes describe a person's appearance; they are not world-readable.
GALLERY_MODE = 0o600

#: Minimum crops that count as an enrollment. Five is the voice enroller's
#: number for the same reason: fewer than that and one bad sample is 25% of the
#: identity.
MIN_CROPS = 5

#: Upper bound, so a runaway capture cannot write a 10 MB "gallery".
MAX_CROPS = 64

#: Embedding dimensionality bounds (SigLIP-2 base is 768).
MIN_DIM = 8
MAX_DIM = 4096

#: Absolute floor under the derived threshold. A gallery whose own crops agree
#: only at 0.3 is not an enrollment of one person, and the enroller refuses it
#: long before this clamp matters; the clamp exists so a hand-edited file cannot
#: set a floor of 0.0 and turn "owner" into "any person-shaped thing".
MIN_THRESHOLD = 0.55

#: Ceiling, so a freakishly self-consistent enrollment (ten frames of a person
#: standing perfectly still) cannot produce a threshold no live crop can reach.
MAX_THRESHOLD = 0.95

#: How far below its own measured self-consistency the runtime floor sits. The
#: enrollment is a best case — same lighting, same ten seconds, same pose family
#: — so the runtime floor must be looser than it or the owner stops being the
#: owner the moment they turn around. UNCALIBRATED on real data; see the
#: handoff in ``scrum/20260822/task_8/P1C_STATUS.md``.
THRESHOLD_SLACK = 0.08

#: Default discriminative margin the enrolled person must beat every other
#: person in frame by. Small on purpose: it is a tie-breaker, not the test.
DEFAULT_MIN_MARGIN = 0.02


class AppearanceGalleryError(RuntimeError):
    """A gallery file exists and is not usable. Never raised for an absent file."""


# --------------------------------------------------------------- vector maths
# Mirrors ``realtime/voice_identity.py``'s helpers deliberately rather than
# importing them: that module is the voice identity stack (card P2-B owns it),
# and a re-ID gallery must not acquire a dependency on the microphone.


def normalize(vector: Sequence[float]) -> tuple[float, ...]:
    """L2-normalize. A zero vector stays zero — the caller must refuse it."""

    values = [float(v) for v in vector]
    norm = math.sqrt(sum(v * v for v in values))
    if norm <= 0.0:
        return tuple(values)
    return tuple(v / norm for v in values)


def cosine(left: Sequence[float], right: Sequence[float]) -> float:
    """Cosine similarity of two vectors, in [-1, 1]. Mismatched dims raise."""

    a = [float(v) for v in left]
    b = [float(v) for v in right]
    if len(a) != len(b):
        raise ValueError(f"cosine needs equal dimensions, got {len(a)} and {len(b)}")
    if not a:
        raise ValueError("cosine of an empty vector is undefined")
    na = math.sqrt(sum(v * v for v in a))
    nb = math.sqrt(sum(v * v for v in b))
    if na <= 0.0 or nb <= 0.0:
        return 0.0
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    return max(-1.0, min(1.0, dot / (na * nb)))


def average_embedding(embeddings: Sequence[Sequence[float]]) -> tuple[float, ...]:
    """Mean of L2-normalized vectors, re-normalized. Refuses an empty input."""

    if not embeddings:
        raise ValueError("average_embedding needs at least one vector")
    units = [normalize(vec) for vec in embeddings]
    dim = len(units[0])
    if any(len(unit) != dim for unit in units):
        raise ValueError("average_embedding needs equal dimensions")
    mean = [sum(unit[i] for unit in units) / len(units) for i in range(dim)]
    return normalize(mean)


def self_consistency(embeddings: Sequence[Sequence[float]]) -> float:
    """Worst LEAVE-ONE-OUT crop score in the set. The enrollment's own floor.

    Leave-one-out and MAX-over-the-others, because that is exactly the query
    :meth:`AppearanceGallery.similarity` will run at inference: "how well does
    this crop match the best of the enrolled ones". Scoring against the centroid
    instead — which an earlier draft of this module did — measures a different
    statistic than the runtime uses, and a threshold derived from one and
    applied to the other is a number nobody measured.

    The MINIMUM over crops, not the mean: the mean hides one crop that is a
    photograph of the wall, and one crop of the wall is what makes a gallery
    quietly match everything.
    """

    if len(embeddings) < 2:
        raise ValueError("self_consistency needs at least two vectors")
    return min(
        max(cosine(vec, other) for index, other in enumerate(embeddings) if index != position)
        for position, vec in enumerate(embeddings)
    )


def threshold_from_self_consistency(
    consistency: float, *, slack: float = THRESHOLD_SLACK
) -> float:
    """The runtime floor, derived from the enrollment's own agreement.

    ``floor = clamp(consistency - slack, MIN_THRESHOLD, MAX_THRESHOLD)``. Every
    term is measured or declared; nothing here is a number chosen because it
    made a fixture pass.
    """

    value = float(consistency) - float(slack)
    return max(MIN_THRESHOLD, min(MAX_THRESHOLD, value))


# ------------------------------------------------------------------- the DTO
@dataclass(frozen=True, slots=True)
class AppearanceGallery:
    """An enrolled owner's appearance, as the runtime reads it.

    ``embeddings`` are L2-normalized at construction. ``similarity`` is a MAX
    over the crops rather than a cosine against the centroid: a person seen from
    behind is genuinely far from a centroid built mostly of frontal crops, and
    averaging that away is how reacquisition after a turn fails.
    """

    owner_id: str
    model: str
    embeddings: tuple[tuple[float, ...], ...]
    threshold: float
    min_margin: float = DEFAULT_MIN_MARGIN
    measured_self_consistency: float = 0.0
    #: The best score a MEASURED not-the-owner crop got against this gallery.
    #: ``-1.0`` means no negative was ever shown to the enrollment.
    negative_reference: float = -1.0
    #: True only when ``threshold`` sits in a MEASURED gap between the owner's
    #: own leave-one-out floor and the best score a known non-owner achieved.
    #: False means the threshold is a conservative derivation from the owner's
    #: crops alone — which, on SigLIP-2 whole-body crops, is measurably not
    #: enough to reject a stranger (see ``scrum/20260822/task_8/P1C_STATUS.md``).
    calibrated: bool = False
    created_at: str = ""
    provider: str = ""
    model_sha256: str = ""
    source: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.owner_id, str) or not self.owner_id.strip():
            raise AppearanceGalleryError("gallery owner_id must be a non-empty string")
        if not isinstance(self.model, str) or not self.model.strip():
            raise AppearanceGalleryError(
                "gallery must name the encoder it was computed with; a cosine "
                "threshold is only meaningful inside one embedding space"
            )
        raw = tuple(self.embeddings)
        if not raw:
            # The whole point of this refusal: "enrolled with nothing" and "not
            # enrolled" are one fact, and only ``None`` gets to spell it.
            raise AppearanceGalleryError(
                "an appearance gallery with zero crops is not an enrollment — "
                "un-enrolled is None, not an empty gallery"
            )
        if len(raw) > MAX_CROPS:
            raise AppearanceGalleryError(f"gallery holds {len(raw)} crops, cap is {MAX_CROPS}")
        units: list[tuple[float, ...]] = []
        dim = None
        for index, vec in enumerate(raw):
            values = [float(v) for v in vec]
            if dim is None:
                dim = len(values)
                if not MIN_DIM <= dim <= MAX_DIM:
                    raise AppearanceGalleryError(
                        f"gallery embedding dimension {dim} outside [{MIN_DIM}, {MAX_DIM}]"
                    )
            elif len(values) != dim:
                raise AppearanceGalleryError(
                    f"gallery crop {index} has dimension {len(values)}, expected {dim}"
                )
            if any(not math.isfinite(v) for v in values):
                raise AppearanceGalleryError(f"gallery crop {index} has a non-finite value")
            unit = normalize(values)
            if not any(unit):
                raise AppearanceGalleryError(
                    f"gallery crop {index} is a zero vector: it would score 0.0 against "
                    "every person on earth, which is not an enrollment"
                )
            units.append(unit)
        object.__setattr__(self, "embeddings", tuple(units))
        for name in ("threshold", "min_margin", "measured_self_consistency", "negative_reference"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise AppearanceGalleryError(f"gallery {name} must be numeric")
            number = float(value)
            if not math.isfinite(number) or not -1.0 <= number <= 1.0:
                raise AppearanceGalleryError(f"gallery {name} must be a finite cosine in [-1, 1]")
            object.__setattr__(self, name, number)
        if not isinstance(self.calibrated, bool):
            raise AppearanceGalleryError("gallery calibrated must be a bool")
        if self.calibrated and self.negative_reference < 0.0:
            raise AppearanceGalleryError(
                "a gallery cannot be calibrated without a measured negative_reference"
            )
        if self.calibrated and self.threshold <= self.negative_reference:
            raise AppearanceGalleryError(
                f"gallery threshold {self.threshold:.4f} does not clear its own measured "
                f"negative {self.negative_reference:.4f}: it would admit the very crop "
                "the enrollment showed it was not the owner"
            )
        if not self.calibrated and self.threshold < MIN_THRESHOLD:
            # The floor guards the DERIVED threshold only. A calibrated one is a
            # measurement — if a real negative set puts the boundary at 0.41, a
            # floor of 0.55 would be this module overruling the evidence, which
            # is the failure mode the whole file is written against.
            raise AppearanceGalleryError(
                f"gallery threshold {self.threshold:.3f} is below the floor "
                f"{MIN_THRESHOLD}; a gallery derived without measured negatives "
                "may not set a boundary that admits anything"
            )
        if self.min_margin < 0.0:
            raise AppearanceGalleryError("gallery min_margin must be non-negative")

    @property
    def dim(self) -> int:
        return len(self.embeddings[0])

    @property
    def crops(self) -> int:
        return len(self.embeddings)

    @property
    def centroid(self) -> tuple[float, ...]:
        return average_embedding(self.embeddings)

    def similarity(self, vector: Sequence[float]) -> float:
        """Best cosine against any enrolled crop. Raises on a dimension mismatch.

        The raise is on purpose. A gallery scored against a different encoder's
        output is the failure this module's ``model`` field exists to prevent,
        and a silent 0.0 would present it as "not the owner" — which reads as a
        working system that never recognises anybody.
        """

        return max(cosine(vector, crop) for crop in self.embeddings)

    def as_dict(self) -> dict[str, object]:
        return {
            "schema": GALLERY_SCHEMA,
            "owner_id": self.owner_id,
            "model": self.model,
            "model_sha256": self.model_sha256,
            "provider": self.provider,
            "dim": self.dim,
            "crops": self.crops,
            "embeddings": [list(vec) for vec in self.embeddings],
            "threshold": self.threshold,
            "min_margin": self.min_margin,
            "measured_self_consistency": self.measured_self_consistency,
            "negative_reference": self.negative_reference,
            "calibrated": self.calibrated,
            "created_at": self.created_at,
        }


def build_gallery(
    embeddings: Iterable[Sequence[float]],
    *,
    owner_id: str = "owner-1",
    model: str,
    provider: str = "",
    model_sha256: str = "",
    min_margin: float = DEFAULT_MIN_MARGIN,
    slack: float = THRESHOLD_SLACK,
    negatives: Iterable[Sequence[float]] | None = None,
    created_at: str | None = None,
) -> AppearanceGallery:
    """Build the DTO, deriving the operating point from what was measured.

    Two modes, and the difference between them is the most important thing in
    this package:

    **Calibrated** (``negatives`` supplied — crops of somebody who is NOT the
    owner). The threshold is the midpoint of the measured gap between the
    owner's leave-one-out floor and the best score any negative achieved. Every
    term is a number this enrollment measured; nothing is chosen because it made
    a fixture pass. If the gap is not positive the enrollment is REFUSED with
    both numbers printed — a gallery whose owner scores no better than a
    stranger cannot identify anybody, and writing it would produce a system that
    looks configured and is not.

    **Uncalibrated** (no negatives). The threshold falls back to
    :func:`threshold_from_self_consistency` — the owner's own agreement minus a
    declared slack. This is a guess about where the negatives *would* be, and on
    SigLIP-2 whole-body crops it was **measured to be too loose**: on the P1-C
    fixture the stranger scores 0.9295 against a fallback floor of 0.9103 and is
    claimed as the owner on every frame where the owner is occluded. The
    resulting gallery is flagged ``calibrated=False`` and the tracker says so in
    its ``reason``. Enrolling this way is a choice, not a default.

    Every cosine quoted here and in ``tools/enroll_owner_appearance.py`` is from
    one measured run of ``scrum/20260822/task_8/P1C_STATUS.md`` §3. They move by
    roughly 2e-4 between runs — fp16 CUDA is not deterministic — so read them to
    three decimals and never as a value to compare against exactly. Nothing in
    this package hashes or pins a cosine, on purpose.
    """

    vectors = [normalize(vec) for vec in embeddings]
    if len(vectors) < 2:
        raise AppearanceGalleryError("a gallery needs at least two crops to measure agreement")
    consistency = self_consistency(vectors)
    negative_reference = -1.0
    calibrated = False
    threshold = threshold_from_self_consistency(consistency, slack=slack)
    if negatives is not None:
        negative_vectors = [normalize(vec) for vec in negatives]
        if not negative_vectors:
            raise AppearanceGalleryError(
                "negatives was supplied but empty; pass None to enroll uncalibrated"
            )
        negative_reference = max(
            max(cosine(negative, crop) for crop in vectors) for negative in negative_vectors
        )
        if consistency <= negative_reference:
            raise AppearanceGalleryError(
                f"this enrollment cannot identify its owner: the owner's own crops agree "
                f"with each other at {consistency:.4f} while a NON-owner crop scores "
                f"{negative_reference:.4f} against them. There is no threshold that "
                "admits the owner and rejects the stranger. Re-record with more varied "
                "owner frames, or with a negative who looks less like the owner."
            )
        threshold = 0.5 * (consistency + negative_reference)
        calibrated = True
    return AppearanceGallery(
        owner_id=owner_id,
        model=model,
        embeddings=tuple(vectors),
        threshold=threshold,
        min_margin=min_margin,
        measured_self_consistency=consistency,
        negative_reference=negative_reference,
        calibrated=calibrated,
        created_at=created_at or datetime.now(UTC).isoformat(timespec="seconds"),
        provider=provider,
        model_sha256=model_sha256,
    )


# ------------------------------------------------------------------ on disk
def default_gallery_path(config_path: str | Path | None = None) -> Path:
    """Beside the realtime config when one is named, else ``~/.config/parcel``.

    Same rule as ``voice_identity.default_profile_path`` and for the same
    reason: an operator running two households gets two directories rather than
    one file with two meanings.
    """

    if config_path:
        candidate = Path(config_path).expanduser()
        parent = candidate.parent if candidate.suffix else candidate
        return parent / GALLERY_NAME
    return GALLERY_FALLBACK_DIR.expanduser() / GALLERY_NAME


def load_gallery(path: str | Path) -> AppearanceGallery | None:
    """ABSENT ⇒ ``None``; PRESENT-AND-BROKEN ⇒ raise. Never silently un-enrolls.

    The asymmetry is the whole fail-closed story: an absent file is a household
    that has not enrolled an appearance, and every consumer already has a
    correct answer for that (nobody is the owner). A file that exists and does
    not parse is an operator error, and absorbing it would turn identity off
    while ``--show`` still reported a configured gallery.
    """

    target = Path(path).expanduser()
    if not target.is_file():
        return None
    try:
        raw = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise AppearanceGalleryError(
            f"owner appearance gallery {target} exists and cannot be read: {error}. "
            "Refusing to treat an unreadable gallery as an absent one — re-run "
            f"tools/enroll_owner_appearance.py or delete {target}."
        ) from None
    if not isinstance(raw, Mapping):
        raise AppearanceGalleryError(f"owner appearance gallery {target} is not a JSON object")
    schema = raw.get("schema")
    if schema != GALLERY_SCHEMA:
        raise AppearanceGalleryError(
            f"owner appearance gallery {target} declares schema {schema!r}, expected "
            f"{GALLERY_SCHEMA!r}"
        )
    embeddings = raw.get("embeddings")
    if not isinstance(embeddings, list) or not embeddings:
        raise AppearanceGalleryError(f"owner appearance gallery {target} carries no crops")
    vectors: list[list[float]] = []
    for index, item in enumerate(embeddings):
        if not isinstance(item, list) or not item:
            raise AppearanceGalleryError(
                f"owner appearance gallery {target} crop {index} is not a non-empty list"
            )
        values: list[float] = []
        for value in item:
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise AppearanceGalleryError(
                    f"owner appearance gallery {target} crop {index} has a non-numeric value"
                )
            values.append(float(value))
        vectors.append(values)
    model = str(raw.get("model", "")).strip()
    if not model:
        raise AppearanceGalleryError(
            f"owner appearance gallery {target} does not name the encoder it was "
            "computed with; a cosine threshold is only meaningful within one space"
        )
    threshold = raw.get("threshold")
    if isinstance(threshold, bool) or not isinstance(threshold, (int, float)):
        raise AppearanceGalleryError(
            f"owner appearance gallery {target} carries no numeric threshold; the "
            "operating point a verdict was produced under must be in the artefact"
        )
    calibrated = raw.get("calibrated", False)
    if not isinstance(calibrated, bool):
        raise AppearanceGalleryError(
            f"owner appearance gallery {target} has a non-boolean 'calibrated' flag"
        )
    return AppearanceGallery(
        owner_id=str(raw.get("owner_id", "owner-1")),
        model=model,
        embeddings=tuple(tuple(v) for v in vectors),
        threshold=float(threshold),
        min_margin=float(raw.get("min_margin", DEFAULT_MIN_MARGIN)),
        measured_self_consistency=float(raw.get("measured_self_consistency", 0.0)),
        negative_reference=float(raw.get("negative_reference", -1.0)),
        calibrated=calibrated,
        created_at=str(raw.get("created_at", "")),
        provider=str(raw.get("provider", "")),
        model_sha256=str(raw.get("model_sha256", "")),
        source=str(target),
    )


def save_gallery(gallery: AppearanceGallery, path: str | Path) -> Path:
    """Write at mode 0600, atomically. Re-enrollment OVERWRITES; there is no merge.

    Atomic because a half-written gallery is exactly the "present and broken"
    case :func:`load_gallery` refuses on, and an interrupted enrollment must not
    be able to brick recognition. 0600 is set on the TEMPORARY file before the
    rename, so the bytes are never briefly world-readable. No merge on purpose:
    averaging today's jacket into a gallery recorded in a different room is how
    a threshold drifts without anybody choosing to move it.
    """

    target = Path(path).expanduser()
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(target.name + ".tmp")
    payload = dict(gallery.as_dict())
    handle = os.open(str(temporary), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, GALLERY_MODE)
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            stream.write(json.dumps(payload, indent=1, sort_keys=True) + "\n")
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise
    os.chmod(temporary, GALLERY_MODE)
    os.replace(temporary, target)
    return target


__all__ = [
    "DEFAULT_MIN_MARGIN",
    "GALLERY_FALLBACK_DIR",
    "GALLERY_MODE",
    "GALLERY_NAME",
    "GALLERY_SCHEMA",
    "MAX_CROPS",
    "MAX_THRESHOLD",
    "MIN_CROPS",
    "MIN_THRESHOLD",
    "THRESHOLD_SLACK",
    "AppearanceGallery",
    "AppearanceGalleryError",
    "average_embedding",
    "build_gallery",
    "cosine",
    "default_gallery_path",
    "load_gallery",
    "normalize",
    "save_gallery",
    "self_consistency",
    "threshold_from_self_consistency",
]
