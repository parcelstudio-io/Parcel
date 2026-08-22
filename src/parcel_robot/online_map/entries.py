"""The things a persistent semantic map is made of (card C-2).

Every type in this file exists so that a later reader can answer, without
guessing: **what was seen, where exactly, by which eye, how sure, how often,
when first, when last, and in whose embedding space.** A map entry that cannot
answer those is not evidence, it is a rumour with coordinates.

Naming note
-----------
This package is ``parcel_robot.online_map``, deliberately NOT
``parcel_robot.semantic_map``: :mod:`parcel_robot.navigation.semantic_map`
already exists and is the *consumer-side* sidecar-backed candidate source that
C-3 owns. Two modules with one name is how a later executor edits the wrong
one.
"""

from __future__ import annotations

import math
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

# --------------------------------------------------------------------------
# Schema + vocabulary constants.
# --------------------------------------------------------------------------

#: Bumped whenever a persisted row's meaning changes. A store written by a
#: different schema is refused on load rather than reinterpreted.
MAP_SCHEMA = "parcel.online_map.v1"

#: The map's own store path override. Same discipline as R27's
#: ``PARCEL_MEMORY_PATH``: ``:memory:`` or an absolute path, never relative.
ENV_MAP_PATH = "PARCEL_ONLINE_MAP_PATH"

# -- entry lifecycle --------------------------------------------------------

#: Observed recently enough to be believed. The ONLY retrievable status.
STATUS_ACTIVE = "active"
#: Expected and not seen, repeatedly. Kept forever, excluded from retrieval.
STATUS_DECAYED = "decayed"
#: Refused persistence-as-truth by a hygiene gate. Kept for audit, never served.
STATUS_QUARANTINED = "quarantined"

STATUSES: frozenset[str] = frozenset(
    {STATUS_ACTIVE, STATUS_DECAYED, STATUS_QUARANTINED}
)
#: REVISION 3(c): decay-marked means EXCLUDED FROM RETRIEVAL, not annotated.
RETRIEVABLE_STATUSES: frozenset[str] = frozenset({STATUS_ACTIVE})

# -- retrieval channels -----------------------------------------------------

#: REVISION 1: the primary channel. A query noun matches fused detector labels.
CHANNEL_DETECTOR_LABEL = "detector_label"
#: REVISION 1: the second half. Names/captions retrieved text-to-text.
CHANNEL_TEXT_NAME = "text_name"
#: REVISION 1: re-ranking ONLY. This channel may reorder an existing candidate
#: list and can NEVER introduce a candidate into it, which is what makes an
#: absolute-threshold hallucination structurally impossible rather than merely
#: discouraged.
CHANNEL_EMBEDDING = "embedding_rerank"

# -- name provenance --------------------------------------------------------

#: The detector said so. Always admissible: it is what the label channel is.
NAME_DETECTOR_LABEL = "detector_label"
#: REVISION 5: a VLM proposed it during an idle-time batch pass. NOT admissible
#: vocabulary until the k-visit gate promotes it.
NAME_VLM_PROPOSED = "vlm_proposed"
#: Promoted after ``NAME_PROMOTION_VISITS`` independent visits agreed.
NAME_PROMOTED = "promoted"

NAME_PROVENANCES: frozenset[str] = frozenset(
    {NAME_DETECTOR_LABEL, NAME_VLM_PROPOSED, NAME_PROMOTED}
)

#: REVISION 5. Bench says naming is ~82-87% accurate — roughly one name in
#: seven is wrong — so a single confident naming is not vocabulary. Three
#: INDEPENDENT visits (distinct visit ids, not three frames of one stare)
#: is the gate that makes the error rate survivable.
NAME_PROMOTION_VISITS = 3

#: Absence on this many consecutive expected-visible visits marks an entry
#: decayed. Not a deletion; see :meth:`MapEntry.decayed`.
DECAY_MARK_AFTER_MISSES = 3

# -- bounds (a map that can grow without bound is a memory leak with a story)-
MAX_ENTRIES = 4096
MAX_NAMES_PER_ENTRY = 8
MAX_HISTORY_PER_ENTRY = 64
MAX_THUMBNAIL_BYTES = 16384
MAX_EMBEDDING_DIM = 4096

_WORD = re.compile(r"[a-z0-9]+")
_STOPWORDS: frozenset[str] = frozenset(
    {"a", "an", "the", "of", "some", "this", "that", "nearest", "closest"}
)


# --------------------------------------------------------------------------
# Small validators. Local, so this module has no import cost beyond stdlib.
# --------------------------------------------------------------------------


def _finite(value: object, name: str) -> float:
    try:
        out = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError) as exc:
        raise TypeError(f"{name} must be a real number") from exc
    if not math.isfinite(out):
        raise ValueError(f"{name} must be finite")
    return out


def _count(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{name} must be an int")
    if value < 0:
        raise ValueError(f"{name} must be non-negative")
    return value


def _text(value: object, name: str, *, limit: int = 128) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{name} must be a string")
    out = value.strip()
    if not out:
        raise ValueError(f"{name} must not be empty")
    if len(out) > limit:
        raise ValueError(f"{name} exceeds {limit} characters")
    return out


def normalize_label(value: object) -> str:
    """Lowercase, collapse whitespace, strip punctuation noise.

    One normalizer for ingest and for query, because a label that normalizes
    one way going in and another coming out is an entry nobody can retrieve.
    """

    if not isinstance(value, str):
        raise TypeError("label must be a string")
    return " ".join(_WORD.findall(value.lower()))


def label_tokens(value: object) -> tuple[str, ...]:
    """Content tokens of a label or query, stopwords removed."""

    return tuple(t for t in normalize_label(value).split() if t not in _STOPWORDS)


# --------------------------------------------------------------------------
# Embedding versioning — REVISION 2.
# --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class EmbeddingStamp:
    """Which space an embedding lives in, and how to get back there.

    REVISION 2 in one object. Without all four fields, a cosine between two
    vectors is an arithmetic operation with no meaning: the same 768 floats
    from two model revisions are two different coordinate systems, and
    comparing them produces a number that looks exactly like a similarity.
    """

    model_id: str
    revision: str
    dim: int
    preprocessing: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "model_id", _text(self.model_id, "model_id", limit=96))
        object.__setattr__(self, "revision", _text(self.revision, "revision", limit=64))
        object.__setattr__(
            self,
            "preprocessing",
            _text(self.preprocessing, "preprocessing", limit=96),
        )
        dim = _count(self.dim, "dim")
        if dim < 1 or dim > MAX_EMBEDDING_DIM:
            raise ValueError(f"dim must be within [1, {MAX_EMBEDDING_DIM}]")
        object.__setattr__(self, "dim", dim)

    @property
    def space_key(self) -> str:
        """The identity of the vector space. Equality here is the ONLY licence
        to take a cosine between two embeddings."""

        return f"{self.model_id}@{self.revision}/{self.dim}/{self.preprocessing}"

    def compatible_with(self, other: object) -> bool:
        return isinstance(other, EmbeddingStamp) and self.space_key == other.space_key

    def as_dict(self) -> dict[str, Any]:
        return {
            "model_id": self.model_id,
            "revision": self.revision,
            "dim": self.dim,
            "preprocessing": self.preprocessing,
        }

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> EmbeddingStamp:
        if not isinstance(data, Mapping):
            raise TypeError("embedding stamp must be a mapping")
        expected = {"model_id", "revision", "dim", "preprocessing"}
        unknown = set(data) - expected
        if unknown:
            raise ValueError(f"unknown embedding stamp keys: {sorted(unknown)}")
        missing = expected - set(data)
        if missing:
            raise ValueError(f"missing embedding stamp keys: {sorted(missing)}")
        return cls(
            model_id=str(data["model_id"]),
            revision=str(data["revision"]),
            dim=int(data["dim"]),
            preprocessing=str(data["preprocessing"]),
        )


# --------------------------------------------------------------------------
# Writer provenance — R27 discipline.
# --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class WriterProvenance:
    """WHO wrote this entry: which session, which eye, which world.

    The ``seat`` field is REVISION 4's whole landing surface. OWLv2 holds the
    in-loop query seat today; OmDet-Turbo tiny is meant to hold the async
    keyframe map-building seat. Recording the seat per entry means a later
    cutover can ask "which of these places did the new eye actually write?"
    instead of assuming the map is homogeneous.
    """

    session_id: str
    seat: str
    detector_name: str
    scene_id: str

    def __post_init__(self) -> None:
        for name, limit in (
            ("session_id", 96),
            ("seat", 48),
            ("detector_name", 96),
            ("scene_id", 96),
        ):
            object.__setattr__(self, name, _text(getattr(self, name), name, limit=limit))

    def as_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "seat": self.seat,
            "detector_name": self.detector_name,
            "scene_id": self.scene_id,
        }

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> WriterProvenance:
        if not isinstance(data, Mapping):
            raise TypeError("provenance must be a mapping")
        expected = {"session_id", "seat", "detector_name", "scene_id"}
        unknown = set(data) - expected
        if unknown:
            raise ValueError(f"unknown provenance keys: {sorted(unknown)}")
        missing = expected - set(data)
        if missing:
            raise ValueError(f"missing provenance keys: {sorted(missing)}")
        return cls(
            session_id=str(data["session_id"]),
            seat=str(data["seat"]),
            detector_name=str(data["detector_name"]),
            scene_id=str(data["scene_id"]),
        )


# --------------------------------------------------------------------------
# Names — REVISION 5's k-gate.
# --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ProposedName:
    """A candidate name for a place, and how many independent visits agreed.

    ``visits`` counts DISTINCT visit ids. Three frames of one stare is one
    visit and does not promote anything; that is the entire point of the gate,
    because a VLM that is wrong about an object is reliably wrong about it from
    the same viewpoint.
    """

    text: str
    provenance: str
    visits: int = 0
    supporting_visit_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "text", _text(self.text, "name text", limit=96))
        prov = _text(self.provenance, "provenance", limit=48)
        if prov not in NAME_PROVENANCES:
            raise ValueError(f"unknown name provenance {prov!r}")
        object.__setattr__(self, "provenance", prov)
        object.__setattr__(self, "visits", _count(self.visits, "visits"))
        ids = tuple(str(v) for v in self.supporting_visit_ids)
        if len(set(ids)) != len(ids):
            raise ValueError("supporting_visit_ids must be distinct")
        if len(ids) > NAME_PROMOTION_VISITS * 4:
            ids = ids[-NAME_PROMOTION_VISITS * 4 :]
        object.__setattr__(self, "supporting_visit_ids", ids)
        if self.visits != len(ids) and ids:
            object.__setattr__(self, "visits", len(ids))

    @property
    def admissible(self) -> bool:
        """May this name be served as vocabulary or matched by the text channel?

        A detector label always may — it IS the label channel. A VLM proposal
        may only after the k-gate. There is no third way in, which is what
        seed 13 pins.
        """

        if self.provenance == NAME_DETECTOR_LABEL:
            return True
        return (
            self.provenance == NAME_PROMOTED and self.visits >= NAME_PROMOTION_VISITS
        )

    def with_visit(self, visit_id: str) -> ProposedName:
        """Record one more independent visit that agreed on this name."""

        vid = _text(visit_id, "visit_id", limit=96)
        if vid in self.supporting_visit_ids:
            return self
        ids = (*self.supporting_visit_ids, vid)
        provenance = self.provenance
        if (
            provenance == NAME_VLM_PROPOSED
            and len(ids) >= NAME_PROMOTION_VISITS
        ):
            provenance = NAME_PROMOTED
        return ProposedName(
            text=self.text,
            provenance=provenance,
            visits=len(ids),
            supporting_visit_ids=ids,
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "text": self.text,
            "provenance": self.provenance,
            "visits": self.visits,
            "supporting_visit_ids": list(self.supporting_visit_ids),
        }

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> ProposedName:
        if not isinstance(data, Mapping):
            raise TypeError("name must be a mapping")
        expected = {"text", "provenance", "visits", "supporting_visit_ids"}
        unknown = set(data) - expected
        if unknown:
            raise ValueError(f"unknown name keys: {sorted(unknown)}")
        missing = expected - set(data)
        if missing:
            raise ValueError(f"missing name keys: {sorted(missing)}")
        return cls(
            text=str(data["text"]),
            provenance=str(data["provenance"]),
            visits=int(data["visits"]),
            supporting_visit_ids=tuple(str(v) for v in data["supporting_visit_ids"]),
        )


# --------------------------------------------------------------------------
# One observation of one object, in one frame.
# --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class MapObservation:
    """One localized detection, in the shape the map ingests.

    Deliberately a DIFFERENT type from
    :class:`~parcel_robot.camera_channel.ingress.CameraDetectionRecord`: that
    one is C-1's diagnostic observation record, and converting through an
    explicit seam is what stops "the stream said so" from silently becoming
    "the map says so". :func:`observation_from_camera_frame` is the only
    sanctioned conversion and it is where hygiene inputs get attached.

    ``surface_x``/``surface_y`` follow the PG-2 convention: the point scored
    against a place is its **surface**, not its centroid, for every
    ``localization_target == "surface"`` class. The nearest-face back-projection
    C-1 already performs is what makes this available.
    """

    label: str
    score: float
    surface_x: float
    surface_y: float
    surface_z: float
    range_m: float
    bearing_rad: float
    depth_m: float
    #: Metric width/height back-projected from the detection box at ``depth_m``.
    extent_w_m: float
    extent_h_m: float
    #: Pixel support behind the localization. Doubles as the view-quality term.
    inlier_pixels: int
    frame_id: str
    visit_id: str
    observed_wall_s: float
    robot_x: float
    robot_y: float
    provenance: WriterProvenance
    #: Optional best-view embedding for THIS view, with its space stamp.
    embedding: tuple[float, ...] | None = None
    embedding_stamp: EmbeddingStamp | None = None
    #: Optional bounded source crop so re-embedding is possible (REVISION 2).
    thumbnail: bytes | None = None
    #: Optional measured depth relief across the box. ``None`` means the
    #: producing stream did not carry one — NOT that the object is planar.
    relief_m: float | None = None
    relief_samples: int = 0

    def __post_init__(self) -> None:
        object.__setattr__(self, "label", normalize_label(self.label))
        if not self.label:
            raise ValueError("observation label must not be empty after normalization")
        score = _finite(self.score, "score")
        if not 0.0 <= score <= 1.0:
            raise ValueError("score must be within [0, 1]")
        object.__setattr__(self, "score", score)
        for name in (
            "surface_x",
            "surface_y",
            "surface_z",
            "range_m",
            "bearing_rad",
            "depth_m",
            "extent_w_m",
            "extent_h_m",
            "observed_wall_s",
            "robot_x",
            "robot_y",
        ):
            object.__setattr__(self, name, _finite(getattr(self, name), name))
        if self.range_m < 0.0 or self.depth_m <= 0.0:
            raise ValueError("range must be non-negative and depth strictly positive")
        if self.extent_w_m < 0.0 or self.extent_h_m < 0.0:
            raise ValueError("metric extents must be non-negative")
        object.__setattr__(
            self, "inlier_pixels", _count(self.inlier_pixels, "inlier_pixels")
        )
        object.__setattr__(self, "frame_id", _text(self.frame_id, "frame_id"))
        object.__setattr__(self, "visit_id", _text(self.visit_id, "visit_id"))
        if not isinstance(self.provenance, WriterProvenance):
            raise TypeError("provenance must be a WriterProvenance")

        emb = self.embedding
        stamp = self.embedding_stamp
        if emb is not None:
            vec = tuple(_finite(v, "embedding component") for v in emb)
            if not vec:
                raise ValueError("embedding must not be empty")
            if len(vec) > MAX_EMBEDDING_DIM:
                raise ValueError("embedding exceeds the dimension ceiling")
            if stamp is None:
                raise ValueError(
                    "an embedding without an EmbeddingStamp is a vector in an "
                    "unknown space; REVISION 2 refuses it rather than guessing"
                )
            if not isinstance(stamp, EmbeddingStamp):
                raise TypeError("embedding_stamp must be an EmbeddingStamp")
            if len(vec) != stamp.dim:
                raise ValueError("embedding length disagrees with its stamped dim")
            object.__setattr__(self, "embedding", vec)
        elif stamp is not None:
            raise ValueError("embedding_stamp given without an embedding")

        thumb = self.thumbnail
        if thumb is not None:
            if not isinstance(thumb, (bytes, bytearray)):
                raise TypeError("thumbnail must be bytes")
            if len(thumb) > MAX_THUMBNAIL_BYTES:
                raise ValueError("thumbnail exceeds the byte ceiling")
            object.__setattr__(self, "thumbnail", bytes(thumb))

        relief = self.relief_m
        if relief is not None:
            relief = _finite(relief, "relief_m")
            if relief < 0.0:
                raise ValueError("relief_m must be non-negative")
            object.__setattr__(self, "relief_m", relief)
        object.__setattr__(
            self, "relief_samples", _count(self.relief_samples, "relief_samples")
        )
        if self.relief_m is not None and self.relief_samples <= 0:
            raise ValueError(
                "relief_m without samples is a claim without a measurement"
            )

    @property
    def view_quality(self) -> float:
        """How good a look this was — the best-view selector's ordering key.

        Pixel support times detection score. REVISION 2 says store the
        best-view embedding and NEVER average across views; a scalar the map
        can order views by is what makes "best" a decision instead of a mood.
        """

        return float(self.inlier_pixels) * self.score


def _round(value: float, places: int = 4) -> float:
    return round(float(value), places)


# --------------------------------------------------------------------------
# One place the dog knows.
# --------------------------------------------------------------------------


@dataclass
class MapEntry:
    """One object-centric place, with the evidence that earned it.

    Mutable by design — this is an *online* map and an entry is the thing that
    grows. What it never does is shrink: :meth:`mark_decayed` changes a status
    and appends history; there is no code path in this package that removes an
    entry from the store, and seed 1 exists to prove it.
    """

    entry_id: str
    label: str
    surface_x: float
    surface_y: float
    surface_z: float
    provenance: WriterProvenance
    first_seen_wall_s: float
    last_seen_wall_s: float
    #: Detections fused into this entry, whatever they were called.
    detection_count: int = 0
    #: Detections whose label equals this entry's label.
    label_support: int = 0
    #: Distinct frames that observed it.
    evidence_frames: int = 0
    #: Distinct visits that observed it. The k-gate and decay both count these.
    visit_ids: tuple[str, ...] = ()
    #: Best detector score ever fused into this entry. This is PG-3's
    #: ``peak_probability`` and it must be a real detector output, not a
    #: rescaled evidence count — the gate's whole job is to notice when the
    #: label head never actually answered loudly.
    peak_score: float = 0.0
    status: str = STATUS_ACTIVE
    #: Consecutive expected-visible visits with no observation.
    consecutive_misses: int = 0
    names: tuple[ProposedName, ...] = ()
    embedding: tuple[float, ...] | None = None
    embedding_stamp: EmbeddingStamp | None = None
    best_view_quality: float = 0.0
    thumbnail: bytes | None = None
    #: Median metric extents across observations, for the size gate + reporting.
    extent_w_m: float = 0.0
    extent_h_m: float = 0.0
    #: Best measured depth relief, and whether anything ever measured one.
    relief_m: float | None = None
    #: Machine-readable hygiene note, e.g. ``ok`` or ``relief_unverified``.
    hygiene_note: str = "relief_unverified"
    #: Append-only audit trail: (wall_s, event, detail).
    history: tuple[tuple[float, str, str], ...] = ()
    #: Nearest ``route_memory`` place-graph keyframe, when one is bound.
    place_graph_index: int | None = None
    #: Bag of per-observation surface points, for the median fuse.
    _points: list[tuple[float, float, float]] = field(default_factory=list, repr=False)
    _extents: list[tuple[float, float]] = field(default_factory=list, repr=False)

    def __post_init__(self) -> None:
        self.entry_id = _text(self.entry_id, "entry_id")
        self.label = normalize_label(self.label)
        if not self.label:
            raise ValueError("entry label must not be empty")
        if self.status not in STATUSES:
            raise ValueError(f"unknown status {self.status!r}")
        if not isinstance(self.provenance, WriterProvenance):
            raise TypeError("provenance must be a WriterProvenance")
        for name in (
            "surface_x",
            "surface_y",
            "surface_z",
            "first_seen_wall_s",
            "last_seen_wall_s",
            "best_view_quality",
            "extent_w_m",
            "extent_h_m",
            "peak_score",
        ):
            setattr(self, name, _finite(getattr(self, name), name))
        if not 0.0 <= self.peak_score <= 1.0:
            raise ValueError("peak_score must be a detector probability in [0, 1]")
        for name in ("detection_count", "label_support", "evidence_frames",
                     "consecutive_misses"):
            setattr(self, name, _count(getattr(self, name), name))
        if self.label_support > self.detection_count:
            raise ValueError("label_support exceeds detection_count")
        if self.last_seen_wall_s < self.first_seen_wall_s:
            raise ValueError("an entry cannot be last seen before it is first seen")
        self.visit_ids = tuple(dict.fromkeys(str(v) for v in self.visit_ids))
        self.names = tuple(self.names)[:MAX_NAMES_PER_ENTRY]
        for item in self.names:
            if not isinstance(item, ProposedName):
                raise TypeError("names must be ProposedName")
        if self.embedding is not None:
            if self.embedding_stamp is None:
                raise ValueError("stored embedding requires its stamp")
            self.embedding = tuple(float(v) for v in self.embedding)
        self.history = tuple(self.history)[-MAX_HISTORY_PER_ENTRY:]

    # -- lifecycle ---------------------------------------------------------

    @property
    def retrievable(self) -> bool:
        """REVISION 3(c). The single place retrieval eligibility is decided."""

        return self.status in RETRIEVABLE_STATUSES

    @property
    def visits(self) -> int:
        return len(self.visit_ids)

    @property
    def label_purity(self) -> float:
        if self.detection_count <= 0:
            return 0.0
        return self.label_support / self.detection_count

    def note(self, wall_s: float, event: str, detail: str = "") -> None:
        """Append one audit row. Bounded, oldest dropped, never emptied."""

        row = (_finite(wall_s, "wall_s"), str(event)[:48], str(detail)[:160])
        self.history = (*self.history, row)[-MAX_HISTORY_PER_ENTRY:]

    def mark_decayed(self, wall_s: float, detail: str = "") -> None:
        """Absence, recorded. **Not** a deletion — the entry and its whole
        history stay; what changes is that retrieval stops serving it."""

        if self.status == STATUS_ACTIVE:
            self.status = STATUS_DECAYED
            self.note(wall_s, "decayed", detail)

    def revive(self, wall_s: float) -> None:
        """Seen again after a decay. The decay episode stays in history."""

        if self.status == STATUS_DECAYED:
            self.status = STATUS_ACTIVE
            self.note(wall_s, "revived", "observed again after decay")
        self.consecutive_misses = 0

    def quarantine(self, wall_s: float, reason: str) -> None:
        self.status = STATUS_QUARANTINED
        self.note(wall_s, "quarantined", reason)

    # -- admissible vocabulary --------------------------------------------

    def admissible_names(self) -> tuple[str, ...]:
        """Names this entry may be *called* — REVISION 5's gate, applied."""

        return tuple(n.text for n in self.names if n.admissible)

    def as_dict(self) -> dict[str, Any]:
        return {
            "entry_id": self.entry_id,
            "label": self.label,
            "surface_x": _round(self.surface_x),
            "surface_y": _round(self.surface_y),
            "surface_z": _round(self.surface_z),
            "provenance": self.provenance.as_dict(),
            "first_seen_wall_s": _round(self.first_seen_wall_s, 3),
            "last_seen_wall_s": _round(self.last_seen_wall_s, 3),
            "detection_count": self.detection_count,
            "label_support": self.label_support,
            "evidence_frames": self.evidence_frames,
            "visit_ids": list(self.visit_ids),
            "peak_score": _round(self.peak_score, 6),
            "status": self.status,
            "consecutive_misses": self.consecutive_misses,
            "names": [n.as_dict() for n in self.names],
            "embedding": (
                [_round(v, 6) for v in self.embedding]
                if self.embedding is not None
                else None
            ),
            "embedding_stamp": (
                self.embedding_stamp.as_dict()
                if self.embedding_stamp is not None
                else None
            ),
            "best_view_quality": _round(self.best_view_quality, 3),
            "extent_w_m": _round(self.extent_w_m),
            "extent_h_m": _round(self.extent_h_m),
            "relief_m": (_round(self.relief_m) if self.relief_m is not None else None),
            "hygiene_note": self.hygiene_note,
            "history": [[_round(t, 3), e, d] for t, e, d in self.history],
            "place_graph_index": self.place_graph_index,
        }

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> MapEntry:
        if not isinstance(data, Mapping):
            raise TypeError("entry must be a mapping")
        stamp = data.get("embedding_stamp")
        emb = data.get("embedding")
        entry = cls(
            entry_id=str(data["entry_id"]),
            label=str(data["label"]),
            surface_x=float(data["surface_x"]),
            surface_y=float(data["surface_y"]),
            surface_z=float(data["surface_z"]),
            provenance=WriterProvenance.from_mapping(data["provenance"]),
            first_seen_wall_s=float(data["first_seen_wall_s"]),
            last_seen_wall_s=float(data["last_seen_wall_s"]),
            detection_count=int(data["detection_count"]),
            label_support=int(data["label_support"]),
            evidence_frames=int(data["evidence_frames"]),
            visit_ids=tuple(str(v) for v in data["visit_ids"]),
            peak_score=float(data["peak_score"]),
            status=str(data["status"]),
            consecutive_misses=int(data["consecutive_misses"]),
            names=tuple(ProposedName.from_mapping(n) for n in data["names"]),
            embedding=(tuple(float(v) for v in emb) if emb is not None else None),
            embedding_stamp=(
                EmbeddingStamp.from_mapping(stamp) if stamp is not None else None
            ),
            best_view_quality=float(data["best_view_quality"]),
            extent_w_m=float(data["extent_w_m"]),
            extent_h_m=float(data["extent_h_m"]),
            relief_m=(
                float(data["relief_m"]) if data.get("relief_m") is not None else None
            ),
            hygiene_note=str(data["hygiene_note"]),
            history=tuple(
                (float(row[0]), str(row[1]), str(row[2])) for row in data["history"]
            ),
            place_graph_index=(
                int(data["place_graph_index"])
                if data.get("place_graph_index") is not None
                else None
            ),
        )
        return entry


__all__ = [
    "CHANNEL_DETECTOR_LABEL",
    "CHANNEL_EMBEDDING",
    "CHANNEL_TEXT_NAME",
    "DECAY_MARK_AFTER_MISSES",
    "ENV_MAP_PATH",
    "MAP_SCHEMA",
    "MAX_ENTRIES",
    "MAX_THUMBNAIL_BYTES",
    "NAME_DETECTOR_LABEL",
    "NAME_PROMOTED",
    "NAME_PROMOTION_VISITS",
    "NAME_VLM_PROPOSED",
    "RETRIEVABLE_STATUSES",
    "STATUSES",
    "STATUS_ACTIVE",
    "STATUS_DECAYED",
    "STATUS_QUARANTINED",
    "EmbeddingStamp",
    "MapEntry",
    "MapObservation",
    "ProposedName",
    "WriterProvenance",
    "label_tokens",
    "normalize_label",
]
