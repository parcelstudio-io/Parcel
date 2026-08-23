"""The dog's own map: online, object-centric, persistent (card C-2).

What this replaces
------------------
Every semantic place Parcel can navigate to today comes from a curated sidecar
(``configs/scenes/*.semantics.yaml``, read through ``scene_semantics()``): a
labelled world handed to the robot in advance. Delete the sidecar and the robot
knows nothing. This module is the other thing — places the robot *saw*, kept
across sessions, with the evidence that earned them still attached, and a
vocabulary that emerges from its own entries rather than from a prompt list.

The retrieval architecture, and why it is not cosine
----------------------------------------------------
REVISION 2026-08-21 §1 is binding and it inverts the obvious design. Query
resolution is **detector-label-primary with a text-side channel**:

1. :data:`~.entries.CHANNEL_DETECTOR_LABEL` — the query noun against fused
   detector labels. **No label match, no candidates, refuse.**
2. :data:`~.entries.CHANNEL_TEXT_NAME` — admissible names/captions matched
   text-to-text (the BinTrack pattern: 67.4% vs 44.6% for the cosine baseline).
3. :data:`~.entries.CHANNEL_EMBEDDING` — image-text cosine, admissible **only**
   as within-query relative ranking over the candidates the first two channels
   already produced.

That third channel's constraint is structural, not documentary:
:meth:`OnlineSemanticMap.resolve` builds the candidate list, and only then
hands it to :func:`_rerank_by_embedding`, which returns a *permutation*. It has
no access to the entry table and therefore cannot introduce a place. A channel
that cannot add a candidate cannot hallucinate one. The reason to want that
guarantee is measured: cross-modal cosines over this map spanned 0.060-0.135
with top-vs-runner-up margins of 0.0004-0.01 — the textbook modality-gap
signature, which a bigger embedder narrows and never removes.

Growth, decay, and the thing that never happens
-----------------------------------------------
Re-observation fuses and strengthens. Absence on a visit where an entry was
*expected to be visible* increments a miss counter, and
:data:`~.entries.DECAY_MARK_AFTER_MISSES` misses mark the entry decayed.
**Marked means quarantined**: decayed entries are excluded from retrieval, from
the vocabulary and from the scene answer (REVISION §3(c)) — not merely
annotated, because an annotated-but-still-retrievable entry is not a defence.
Nothing is ever deleted; there is no delete path in this package.
"""

from __future__ import annotations

import math
import statistics
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from typing import Any

from parcel_robot.perception_abstention import (
    AbstentionPolicy,
    AbstentionVerdict,
    DetectorSupport,
    PlaceEvidence,
    assess_place_query,
)

from .entries import (
    CHANNEL_DETECTOR_LABEL,
    CHANNEL_EMBEDDING,
    CHANNEL_TEXT_NAME,
    DECAY_MARK_AFTER_MISSES,
    MAP_SCHEMA,
    MAX_ENTRIES,
    NAME_DETECTOR_LABEL,
    NAME_VLM_PROPOSED,
    STATUS_QUARANTINED,
    EmbeddingStamp,
    MapEntry,
    MapObservation,
    ProposedName,
    WriterProvenance,
    label_tokens,
    normalize_label,
    origins_conflict,
)
from .hygiene import (
    NOTE_OK,
    NOTE_RELIEF_UNVERIFIED,
    HygieneVerdict,
    is_volatile_label,
    screen_observation,
)
from .store import OnlineMapStore

#: Two observations of the same class within this distance are the same thing.
#: Sized from the bench: back-projection + fusion put the lamppost within
#: 1-3 cm of truth, so a metre of slack absorbs viewpoint spread without
#: merging genuinely distinct street furniture (the two lamp posts in the dev
#: scene are 12 m apart).
DEFAULT_FUSE_RADIUS_M = 1.0

#: An entry is "expected visible" for decay purposes when the robot passed
#: within this range of it during a visit. Absence beyond it is not absence.
DEFAULT_VISIBILITY_RANGE_M = 8.0

#: Evidence weighting for ranking. Corroborated entries score 2.8-8.2 and stray
#: single-detection labels 0.12 under this shape, which is the separation the
#: retrieval bench measured for the label-primary arm.
_EVIDENCE_FRAME_WEIGHT = 1.0
_PURITY_WEIGHT = 2.0

# -- navigability, measured by the robot's own body -------------------------
#
# PG-3's fourth signal is ``ground_evidence_fraction``: "fraction of its depth
# returns at or below GROUND_BAND_M", i.e. is there floor next to this place.
# C-1's ``CameraDetectionRecord`` does not carry depth returns, and the one
# height it does carry — ``world_z`` — is the localized SURFACE point, which on
# the real stream sits at 0.70-2.11 m for lampposts because it is halfway up
# the pole. Thresholding that against a 0.35 m ground band would report every
# real place as un-navigable, and hardcoding 1.0 instead would fabricate the
# signal outright.
#
# So the map measures navigability the way an embodied agent actually can: the
# robot walked there. Probe points on a ring around the place are checked
# against the path the robot's own pose history says it occupied. This is
# sidecar-free, it is a measurement rather than an assumption, and it is
# honestly a DIFFERENT quantity from PG-3's depth-return fraction — which is
# why every entry records which source produced it.
NAV_PROBE_RING_M = 1.5
NAV_PROBE_TOLERANCE_M = 1.5
NAV_PROBE_POINTS = 8
#: Poses closer together than this are the same place for probe purposes.
NAV_PATH_DECIMATION_M = 0.25
MAX_PATH_POSES = 4096

GROUND_SOURCE_UNMEASURED = "unmeasured"
GROUND_SOURCE_TRAVERSAL = "robot_traversal"
GROUND_SOURCE_DEPTH = "depth_ground_returns"


class MapRefused(RuntimeError):
    """The map declined to do something that would corrupt it."""


def _mad(values: Sequence[float]) -> float:
    """Median absolute deviation — the denominator of PG-3's ranking margin.

    Computed here purely as a DIAGNOSTIC, so a caller can see the measured
    reason a verdict came back ``indecisive_ranking``:
    :func:`~parcel_robot.perception_abstention.ranking_margin` returns exactly
    ``0.0`` when this is ``0.0``, and an evidence-weighted background where the
    well-observed places tie has a MAD of exactly ``0.0``. C-2 reports that
    rather than tuning the gate it does not own.
    """

    finite = [float(v) for v in values if math.isfinite(float(v))]
    if len(finite) < 3:
        return 0.0
    median = statistics.median(finite)
    return statistics.median(sorted(abs(v - median) for v in finite))


# --------------------------------------------------------------------------
# Ingest outcome.
# --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class IngestOutcome:
    """What one observation did to the map.

    ``persisted`` False with ``observed`` True is the important row: it is what
    a person walking past looks like. The robot saw them, counted them, will
    report them — and did not write them down as a place.
    """

    observed: bool
    persisted: bool
    entry_id: str | None
    created: bool
    hygiene: HygieneVerdict

    def as_dict(self) -> dict[str, Any]:
        return {
            "observed": self.observed,
            "persisted": self.persisted,
            "entry_id": self.entry_id,
            "created": self.created,
            "hygiene": self.hygiene.as_dict(),
        }


@dataclass(frozen=True, slots=True)
class MapCandidate:
    """One place offered in answer to a query, with its evidence."""

    entry_id: str
    label: str
    x: float
    y: float
    z: float
    distance_m: float
    evidence_frames: int
    detection_count: int
    label_support: int
    visits: int
    score: float
    channels: tuple[str, ...]
    names: tuple[str, ...]
    hygiene_note: str
    similarity: float | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "entry_id": self.entry_id,
            "label": self.label,
            "x": round(self.x, 4),
            "y": round(self.y, 4),
            "z": round(self.z, 4),
            "distance_m": round(self.distance_m, 4),
            "evidence_frames": self.evidence_frames,
            "detection_count": self.detection_count,
            "label_support": self.label_support,
            "visits": self.visits,
            "score": round(self.score, 4),
            "channels": list(self.channels),
            "names": list(self.names),
            "hygiene_note": self.hygiene_note,
            "similarity": (
                round(self.similarity, 6) if self.similarity is not None else None
            ),
        }


@dataclass(frozen=True, slots=True)
class MapQueryResult:
    """The query API's answer: candidates, evidence, and a PG-3 verdict.

    The verdict is **always** present, including on refusals, and is produced by
    :func:`parcel_robot.perception_abstention.assess_place_query` — the shipped
    gate, not a local re-implementation. Seed 6 exists because a query API that
    returns candidates without a verdict is an abstention mechanism that has
    been quietly switched off.
    """

    query: str
    candidates: tuple[MapCandidate, ...]
    verdict: AbstentionVerdict
    channels_used: tuple[str, ...]
    embedding_status: str
    #: Why the verdict came out the way it did, in numbers. Carries
    #: ``ranking_background_degenerate`` — see
    #: :meth:`OnlineSemanticMap._assess` for the measured incompatibility it
    #: exists to make visible instead of mysterious.
    diagnostics: Mapping[str, Any] = field(default_factory=dict)

    @property
    def admitted(self) -> bool:
        return bool(self.verdict.admitted)

    @property
    def best(self) -> MapCandidate | None:
        return self.candidates[0] if self.candidates else None

    def as_dict(self) -> dict[str, Any]:
        return {
            "query": self.query,
            "candidates": [c.as_dict() for c in self.candidates],
            "verdict": self.verdict.as_dict(),
            "channels_used": list(self.channels_used),
            "embedding_status": self.embedding_status,
            "admitted": self.admitted,
            "diagnostics": dict(self.diagnostics),
        }


# --------------------------------------------------------------------------
# The embedding channel, isolated so its powerlessness is checkable.
# --------------------------------------------------------------------------

#: Reported on every result so a reader knows what the third channel did.
EMBEDDING_UNUSED = "unused"
EMBEDDING_RERANKED = "reranked"
EMBEDDING_UNAVAILABLE_VERSION = "unavailable_version_mismatch"
EMBEDDING_UNAVAILABLE_ABSENT = "unavailable_no_embedding"


def cosine(a: Sequence[float], b: Sequence[float]) -> float:
    """Plain cosine. Meaningful ONLY between vectors of one stamped space."""

    if len(a) != len(b):
        raise ValueError("cosine between different dimensions is not a similarity")
    num = sum(float(x) * float(y) for x, y in zip(a, b))
    na = math.sqrt(sum(float(x) * float(x) for x in a))
    nb = math.sqrt(sum(float(y) * float(y) for y in b))
    if na <= 0.0 or nb <= 0.0:
        return 0.0
    return num / (na * nb)


def _rerank_by_embedding(
    candidates: Sequence[MapCandidate],
    entries: Mapping[str, MapEntry],
    query_embedding: Sequence[float] | None,
    query_stamp: EmbeddingStamp | None,
) -> tuple[tuple[MapCandidate, ...], str]:
    """Reorder an EXISTING candidate list. Cannot add, cannot remove.

    This signature is the enforcement. The function receives the candidates and
    returns a permutation of exactly those candidates; it never sees the entry
    table's keys as a search space. REVISION §1's "NEVER an absolute threshold,
    NEVER an absence/presence verdict" is therefore a property of the call
    graph rather than a promise in a docstring.

    Version discipline (REVISION §2): a stamp mismatch yields
    ``embedding unavailable`` and the ORIGINAL order — never a cross-space
    cosine, which is an arithmetic operation that looks exactly like a
    similarity and means nothing.
    """

    if query_embedding is None or query_stamp is None:
        return tuple(candidates), EMBEDDING_UNUSED
    if not candidates:
        return tuple(candidates), EMBEDDING_UNUSED

    # (sort key, original index, candidate). The original index keeps the sort
    # stable, so candidates the embedding cannot judge retain their
    # label-channel order instead of being shuffled by an accident of hashing.
    scored: list[tuple[float, int, MapCandidate]] = []
    compatible = 0
    for index, cand in enumerate(candidates):
        entry = entries.get(cand.entry_id)
        if (
            entry is None
            or entry.embedding is None
            or entry.embedding_stamp is None
            or not entry.embedding_stamp.compatible_with(query_stamp)
        ):
            # Sorts to the back; NOT dropped. A place the embedder cannot see
            # is still a place the label channel found.
            scored.append((float("-inf"), index, cand))
            continue
        compatible += 1
        sim = cosine(query_embedding, entry.embedding)
        scored.append((sim, index, replace(cand, similarity=sim)))

    if compatible == 0:
        any_embedding = any(
            (entry := entries.get(c.entry_id)) is not None and entry.embedding is not None
            for c in candidates
        )
        status = (
            EMBEDDING_UNAVAILABLE_VERSION
            if any_embedding
            else EMBEDDING_UNAVAILABLE_ABSENT
        )
        return tuple(candidates), status

    scored.sort(key=lambda row: (-row[0], row[1]))
    return tuple(row[2] for row in scored), EMBEDDING_RERANKED


# --------------------------------------------------------------------------
# The map.
# --------------------------------------------------------------------------


class OnlineSemanticMap:
    """Object-centric semantic memory that grows, decays, and persists.

    Construct with a store for a persistent map, or without one for an
    in-process map (tests, replay, dry runs). ``reload=True`` on construction is
    what makes the dog that walked yesterday know the lamppost today; seed 5
    turns it off and every persistence property collapses.
    """

    def __init__(
        self,
        store: OnlineMapStore | None = None,
        *,
        provenance: WriterProvenance,
        fuse_radius_m: float = DEFAULT_FUSE_RADIUS_M,
        visibility_range_m: float = DEFAULT_VISIBILITY_RANGE_M,
        decay_after_misses: int = DECAY_MARK_AFTER_MISSES,
        policy: AbstentionPolicy | None = None,
        reload: bool = True,
    ) -> None:
        if not isinstance(provenance, WriterProvenance):
            raise TypeError("the map must know who is writing to it")
        radius = float(fuse_radius_m)
        if not math.isfinite(radius) or radius <= 0.0:
            raise ValueError("fuse_radius_m must be finite and positive")
        vis = float(visibility_range_m)
        if not math.isfinite(vis) or vis <= 0.0:
            raise ValueError("visibility_range_m must be finite and positive")
        if isinstance(decay_after_misses, bool) or not isinstance(
            decay_after_misses, int
        ):
            raise TypeError("decay_after_misses must be an int")
        if decay_after_misses < 1:
            raise ValueError("decay_after_misses must be at least 1")

        self._store = store
        self._provenance = provenance
        self._fuse_radius_m = radius
        self._visibility_range_m = vis
        self._decay_after_misses = decay_after_misses
        self._policy = policy
        self._entries: dict[str, MapEntry] = {}
        self._frames_seen = 0
        #: Normalized query phrase -> frames in which the detector was ASKED
        #: about it. PG-3 refuses a term nobody asked about, and it can only do
        #: that if the map records what was asked rather than inferring it from
        #: what came back.
        self._asked_terms: dict[str, int] = {}
        self._observations_seen = 0
        self._refused_volatile = 0
        self._refused_hygiene = 0
        self._place_graph: Any = None
        #: Decimated history of poses the robot's body actually occupied. This
        #: is the navigability evidence; see the NAV_PROBE_* block above.
        self._path: list[tuple[float, float]] = []

        if store is not None and reload:
            self.reload()

    # -- properties --------------------------------------------------------

    @property
    def provenance(self) -> WriterProvenance:
        return self._provenance

    @property
    def store(self) -> OnlineMapStore | None:
        return self._store

    @property
    def fuse_radius_m(self) -> float:
        return self._fuse_radius_m

    def __len__(self) -> int:
        return len(self._entries)

    def entries(self) -> tuple[MapEntry, ...]:
        """EVERY entry, including decayed and quarantined ones.

        Retrieval filters; the audit surface does not. An auditor asking what
        the robot stopped believing, and when, gets an answer here.
        """

        return tuple(sorted(self._entries.values(), key=lambda e: e.entry_id))

    def active_entries(self) -> tuple[MapEntry, ...]:
        return tuple(e for e in self.entries() if e.retrievable)

    def stats(self) -> dict[str, Any]:
        by_status: dict[str, int] = {}
        for entry in self._entries.values():
            by_status[entry.status] = by_status.get(entry.status, 0) + 1
        return {
            "schema": MAP_SCHEMA,
            "entries": len(self._entries),
            "by_status": by_status,
            "frames_seen": self._frames_seen,
            "observations_seen": self._observations_seen,
            "refused_volatile": self._refused_volatile,
            "refused_hygiene": self._refused_hygiene,
            "fuse_radius_m": self._fuse_radius_m,
            "store": None if self._store is None else self._store.path,
            # Card P1-B. The three facts that separate "the map has rows" from
            # "the map learned something", published where an operator and a
            # status doc read the same number:
            #   embedded  — entries carrying a REAL vector with its space stamp,
            #               not the 8-dim label hash the ingress used to fall
            #               back to (the fallback IS a valid embedding, so the
            #               only honest test is the stamp, not the presence);
            #   thumbnails— entries that could be re-embedded after a model
            #               upgrade (AU-C2-1's whole point);
            #   relief    — entries where the planarity defence actually
            #               MEASURED something instead of reporting
            #               ``relief_unverified``.
            "origin": self._provenance.origin,
            "entries_embedded": sum(
                1 for e in self._entries.values() if e.embedding_stamp is not None
            ),
            "entries_with_thumbnail": sum(
                1 for e in self._entries.values() if e.thumbnail
            ),
            "entries_relief_measured": sum(
                1 for e in self._entries.values() if e.relief_m is not None
            ),
        }

    # -- ingest ------------------------------------------------------------

    def note_frame(self, queries: Sequence[str] = ()) -> None:
        """Record that a frame was looked at, and WHAT it was asked about.

        A frame with zero detections is a real observation — evidence of
        looking and seeing nothing. The denominator matters: without it,
        ``frames_fired / frames_observed`` is unanswerable and PG-3's detector
        support cannot be built honestly.

        ``queries`` is the batch the detector actually answered (C-1's
        ``frame.queries``). Recording it is what makes the null control real:
        "fire hydrant" is refused because **nobody asked**, which is a
        different and more honest refusal than "we asked and saw none".
        """

        self._frames_seen += 1
        for term in queries:
            phrase = normalize_label(term)
            if phrase:
                self._asked_terms[phrase] = self._asked_terms.get(phrase, 0) + 1

    def asked_terms(self) -> dict[str, int]:
        """The detector's own query history: phrase -> frames asked."""

        return dict(self._asked_terms)

    def note_pose(self, x: float, y: float) -> None:
        """Record a pose the robot's body actually occupied.

        Bounded and decimated. This is the map's navigability evidence: ground
        the robot has stood on is ground the robot can stand on, which is the
        only navigability claim an embodied map can make without reading a
        sidecar that tells it where the pavement is.
        """

        point = (float(x), float(y))
        if not all(math.isfinite(v) for v in point):
            raise ValueError("pose must be finite")
        if self._path and math.dist(self._path[-1], point) < NAV_PATH_DECIMATION_M:
            return
        self._path.append(point)
        if len(self._path) > MAX_PATH_POSES:
            del self._path[0]

    @property
    def path_length(self) -> int:
        return len(self._path)

    def navigability(self, entry: MapEntry) -> tuple[float, str]:
        """How much of the ground around this place has the robot stood on?

        Returns ``(fraction, source)``. ``0.0`` with
        :data:`GROUND_SOURCE_UNMEASURED` means *nothing measured it* — which
        PG-3 correctly reads as a refusal. The map does not invent this number;
        a fabricated navigability signal is a robot walking into a flowerbed
        because a dataclass field wanted a float.
        """

        if not self._path:
            return 0.0, GROUND_SOURCE_UNMEASURED
        reached = 0
        for index in range(NAV_PROBE_POINTS):
            angle = 2.0 * math.pi * index / NAV_PROBE_POINTS
            probe = (
                entry.surface_x + NAV_PROBE_RING_M * math.cos(angle),
                entry.surface_y + NAV_PROBE_RING_M * math.sin(angle),
            )
            for pose in self._path:
                if math.dist(pose, probe) <= NAV_PROBE_TOLERANCE_M:
                    reached += 1
                    break
        return reached / NAV_PROBE_POINTS, GROUND_SOURCE_TRAVERSAL

    def observe(self, observation: MapObservation) -> IngestOutcome:
        """Ingest one localized detection. Fuse, create, or refuse."""

        if not isinstance(observation, MapObservation):
            raise TypeError("observe() takes a MapObservation")
        self._refuse_foreign_origin(observation)
        self._observations_seen += 1

        verdict = screen_observation(
            label=observation.label,
            extent_w_m=observation.extent_w_m,
            extent_h_m=observation.extent_h_m,
            relief_m=observation.relief_m,
            relief_samples=observation.relief_samples,
        )
        if not verdict.admitted:
            if is_volatile_label(observation.label):
                self._refused_volatile += 1
            else:
                self._refused_hygiene += 1
            return IngestOutcome(
                observed=True,
                persisted=False,
                entry_id=None,
                created=False,
                hygiene=verdict,
            )

        entry = self._nearest_same_class(observation)
        created = entry is None
        if entry is None:
            if len(self._entries) >= MAX_ENTRIES:
                raise MapRefused(
                    f"map is full at {MAX_ENTRIES} entries; refusing to grow "
                    "without bound"
                )
            entry = MapEntry(
                entry_id=f"place-{uuid.uuid4().hex[:16]}",
                label=observation.label,
                surface_x=observation.surface_x,
                surface_y=observation.surface_y,
                surface_z=observation.surface_z,
                provenance=observation.provenance,
                first_seen_wall_s=observation.observed_wall_s,
                last_seen_wall_s=observation.observed_wall_s,
                hygiene_note=verdict.note,
            )
            entry.names = (
                ProposedName(
                    text=observation.label,
                    provenance=NAME_DETECTOR_LABEL,
                    visits=1,
                    supporting_visit_ids=(observation.visit_id,),
                ),
            )
            entry.note(observation.observed_wall_s, "created", observation.frame_id)
            self._entries[entry.entry_id] = entry

        self._fuse(entry, observation, verdict)
        return IngestOutcome(
            observed=True,
            persisted=True,
            entry_id=entry.entry_id,
            created=created,
            hygiene=verdict,
        )

    def _refuse_foreign_origin(self, obs: MapObservation) -> None:
        """Card P1-B. A map is one world; refuse the frame, not the store.

        :meth:`OnlineMapStore.load_all` refuses a store that is ALREADY mixed.
        This is the other end of the same invariant and it is the useful one:
        it fires on the observation that would have made the store mixed, in
        the process that fed it, naming both origins — instead of leaving the
        discovery to whoever reloads the file tomorrow.

        ``unknown`` on either side is not a conflict (see
        :func:`~.entries.origins_conflict`): a fixture that never declared an
        origin has not claimed anything.
        """

        if not origins_conflict({self._provenance.origin, obs.provenance.origin}):
            return
        raise MapRefused(
            f"this map's writer is stamped {self._provenance.origin!r} and the "
            f"observation is stamped {obs.provenance.origin!r}; refusing to fuse "
            "pixels from two different worlds into one place. Build a second "
            "map (and a second store) for the second venue."
        )

    def _nearest_same_class(self, obs: MapObservation) -> MapEntry | None:
        best: MapEntry | None = None
        best_d = self._fuse_radius_m
        for entry in self._entries.values():
            if entry.status == STATUS_QUARANTINED:
                continue
            if entry.label != obs.label:
                continue
            d = math.dist(
                (entry.surface_x, entry.surface_y), (obs.surface_x, obs.surface_y)
            )
            if d < best_d:
                best, best_d = entry, d
        return best

    def _fuse(
        self, entry: MapEntry, obs: MapObservation, verdict: HygieneVerdict
    ) -> None:
        """Re-observation strengthens. Position is the median of surface points.

        Median rather than mean because a single bad depth return should not
        drag a place across the pavement, and because the bench's 1-3 cm result
        was measured with a median fuse.
        """

        entry._points.append((obs.surface_x, obs.surface_y, obs.surface_z))
        entry._extents.append((obs.extent_w_m, obs.extent_h_m))
        entry.surface_x = statistics.median(p[0] for p in entry._points)
        entry.surface_y = statistics.median(p[1] for p in entry._points)
        entry.surface_z = statistics.median(p[2] for p in entry._points)
        entry.extent_w_m = statistics.median(e[0] for e in entry._extents)
        entry.extent_h_m = statistics.median(e[1] for e in entry._extents)

        entry.detection_count += 1
        if obs.label == entry.label:
            entry.label_support += 1
        entry.evidence_frames += 1
        if obs.visit_id not in entry.visit_ids:
            entry.visit_ids = (*entry.visit_ids, obs.visit_id)
        entry.last_seen_wall_s = max(entry.last_seen_wall_s, obs.observed_wall_s)
        entry.peak_score = max(entry.peak_score, obs.score)
        entry.revive(obs.observed_wall_s)

        # A measured relief upgrades the hygiene note; an unmeasured one never
        # downgrades a verified entry back to unverified.
        if verdict.relief_verified:
            entry.relief_m = (
                verdict.relief_m
                if entry.relief_m is None
                else max(entry.relief_m, float(verdict.relief_m))
            )
            entry.hygiene_note = NOTE_OK
        elif entry.hygiene_note != NOTE_OK:
            entry.hygiene_note = NOTE_RELIEF_UNVERIFIED

        self._maybe_take_best_view(entry, obs)

    def _maybe_take_best_view(self, entry: MapEntry, obs: MapObservation) -> None:
        """REVISION §2: keep the BEST view's embedding. Never average.

        There is no arithmetic on two embeddings anywhere in this method, and
        that is the point — averaging across views measurably degrades
        retrieval, and it degrades it *silently*, producing a vector that is a
        valid input to every downstream call and describes no view that
        existed. Seed 10 replaces this body with a running mean.
        """

        if obs.embedding is None or obs.embedding_stamp is None:
            return
        if obs.view_quality <= entry.best_view_quality:
            return
        entry.embedding = obs.embedding
        entry.embedding_stamp = obs.embedding_stamp
        entry.best_view_quality = obs.view_quality
        if obs.thumbnail is not None:
            entry.thumbnail = obs.thumbnail

    # -- decay -------------------------------------------------------------

    def close_visit(
        self,
        visit_id: str,
        *,
        wall_s: float,
        robot_path: Sequence[tuple[float, float]] = (),
    ) -> tuple[str, ...]:
        """End a visit; decay entries that were expected visible and were not seen.

        "Expected visible" is deliberately narrow: an entry counts as expected
        only if the robot's own path passed within ``visibility_range_m`` of it
        during this visit. A robot that never went down that street has not
        observed the lamppost's absence, and treating it as if it had is how a
        map erases the parts of the world it stopped patrolling.

        Returns the ids newly marked decayed. Nothing is deleted, ever.
        """

        vid = str(visit_id)
        path = [(float(x), float(y)) for x, y in robot_path]
        newly: list[str] = []
        for entry in self._entries.values():
            if entry.status == STATUS_QUARANTINED:
                continue
            if vid in entry.visit_ids:
                continue  # seen this visit
            if not self._was_expected_visible(entry, path):
                continue
            entry.consecutive_misses += 1
            entry.note(wall_s, "missed", f"visit={vid}")
            if entry.consecutive_misses >= self._decay_after_misses:
                was = entry.status
                entry.mark_decayed(
                    wall_s, f"{entry.consecutive_misses} consecutive expected-visible misses"
                )
                if was != entry.status:
                    newly.append(entry.entry_id)
        return tuple(newly)

    def _was_expected_visible(
        self, entry: MapEntry, path: Sequence[tuple[float, float]]
    ) -> bool:
        for x, y in path:
            if math.dist((x, y), (entry.surface_x, entry.surface_y)) <= (
                self._visibility_range_m
            ):
                return True
        return False

    # -- naming (REVISION §5) ---------------------------------------------

    def propose_name(
        self,
        entry_id: str,
        text: str,
        *,
        visit_id: str,
        wall_s: float,
    ) -> ProposedName:
        """Record one VLM-proposed name for a place. IDLE-TIME BATCH ONLY.

        This method must never be called on the patrol path. Every VLM size
        measured breaches the 100 ms detector bound *while generating*, so a
        naming pass inside the loop is a safety regression wearing a vocabulary
        costume. The contract is enforced socially (this docstring, the card,
        C-3's duty cycle) and mechanically at the only place C-2 owns: the name
        enters as :data:`~.entries.NAME_VLM_PROPOSED` and is **not admissible
        vocabulary** until :data:`~.entries.NAME_PROMOTION_VISITS` independent
        visits have agreed. Bench: naming is 16/20 with perfect consistency on
        distinctive classes and poor on ambiguous ones — roughly one name in
        seven is wrong, which is exactly survivable behind a k-gate and not
        survivable in front of one.
        """

        entry = self._entries.get(str(entry_id))
        if entry is None:
            raise MapRefused(f"no such entry {entry_id!r}")
        wanted = normalize_label(text)
        if not wanted:
            raise ValueError("a proposed name must not be empty")

        names = list(entry.names)
        for index, name in enumerate(names):
            if name.text == wanted:
                updated = name.with_visit(str(visit_id))
                names[index] = updated
                entry.names = tuple(names)
                if updated.admissible and not name.admissible:
                    entry.note(wall_s, "name_promoted", updated.text)
                return updated

        fresh = ProposedName(
            text=wanted,
            provenance=NAME_VLM_PROPOSED,
            visits=1,
            supporting_visit_ids=(str(visit_id),),
        )
        names.append(fresh)
        entry.names = tuple(names)
        entry.note(wall_s, "name_proposed", fresh.text)
        return fresh

    # -- query API ---------------------------------------------------------

    def resolve(
        self,
        query: str,
        *,
        robot_xy: tuple[float, float] = (0.0, 0.0),
        query_embedding: Sequence[float] | None = None,
        query_stamp: EmbeddingStamp | None = None,
        limit: int = 5,
    ) -> MapQueryResult:
        """C-3's grounding entry point: label/text -> candidates + PG-3 verdict."""

        text = " ".join(str(query).strip().split())
        wanted = set(label_tokens(text))
        channels: list[str] = []

        candidates: list[MapCandidate] = []
        seen: set[str] = set()

        # Channel 1 — detector labels. Primary. No match here and no match in
        # channel 2 means REFUSE; there is no third way to become a candidate.
        for entry in self._entries.values():
            if not entry.retrievable:
                continue  # REVISION 3(c): quarantine, not annotation
            if wanted and wanted & set(label_tokens(entry.label)):
                candidates.append(self._candidate(entry, robot_xy,
                                                  (CHANNEL_DETECTOR_LABEL,)))
                seen.add(entry.entry_id)
        if candidates:
            channels.append(CHANNEL_DETECTOR_LABEL)

        # Channel 2 — admissible names, text-to-text.
        text_hits = 0
        for entry in self._entries.values():
            if not entry.retrievable or entry.entry_id in seen:
                continue
            for name in entry.admissible_names():
                if wanted and wanted & set(label_tokens(name)):
                    candidates.append(
                        self._candidate(entry, robot_xy, (CHANNEL_TEXT_NAME,))
                    )
                    seen.add(entry.entry_id)
                    text_hits += 1
                    break
        if text_hits:
            channels.append(CHANNEL_TEXT_NAME)

        candidates.sort(key=lambda c: (-c.score, c.distance_m, c.entry_id))

        # Channel 3 — embedding re-rank over EXACTLY these candidates.
        ordered, embedding_status = _rerank_by_embedding(
            candidates, self._entries, query_embedding, query_stamp
        )
        if embedding_status == "reranked":
            channels.append(CHANNEL_EMBEDDING)
        ordered = ordered[: max(0, int(limit))]

        verdict, diagnostics = self._assess(text, ordered)
        return MapQueryResult(
            query=text,
            candidates=ordered,
            verdict=verdict,
            channels_used=tuple(channels),
            embedding_status=embedding_status,
            diagnostics=diagnostics,
        )

    @staticmethod
    def _entry_score(entry: MapEntry) -> float:
        """Evidence weight. REVISION §1's ranking signal — not a cosine.

        Shaped so corroboration separates from strays: the retrieval bench
        measured corroborated entries at 2.8-8.2 and stray single-detection
        labels at 0.12 on exactly this ordering.
        """

        return (
            _EVIDENCE_FRAME_WEIGHT * math.log1p(entry.evidence_frames)
            + _PURITY_WEIGHT * entry.label_purity
        ) * math.log1p(max(1, entry.visits))

    def _candidate(
        self,
        entry: MapEntry,
        robot_xy: tuple[float, float],
        channels: tuple[str, ...],
    ) -> MapCandidate:
        distance = math.dist(
            (float(robot_xy[0]), float(robot_xy[1])),
            (entry.surface_x, entry.surface_y),
        )
        score = self._entry_score(entry)
        return MapCandidate(
            entry_id=entry.entry_id,
            label=entry.label,
            x=entry.surface_x,
            y=entry.surface_y,
            z=entry.surface_z,
            distance_m=distance,
            evidence_frames=entry.evidence_frames,
            detection_count=entry.detection_count,
            label_support=entry.label_support,
            visits=entry.visits,
            score=score,
            channels=channels,
            names=entry.admissible_names(),
            hygiene_note=entry.hygiene_note,
        )

    def _assess(
        self, query: str, candidates: Sequence[MapCandidate]
    ) -> tuple[AbstentionVerdict, dict[str, Any]]:
        """Hand the shipped PG-3 gate the evidence and take its answer.

        Note what is NOT here: any local decision about whether the query is
        grounded. The map supplies evidence; ``assess_place_query`` decides.
        Seed 6 replaces this call with ``admitted=True`` and every abstention
        property in the card dies at once, which is the point of pinning it.
        """

        wanted = set(label_tokens(query))
        fired = 0
        peak = 0.0
        places: list[PlaceEvidence] = []
        for cand in candidates:
            entry = self._entries[cand.entry_id]
            matches = bool(wanted & set(label_tokens(entry.label)))
            support = entry.label_support if matches else 0
            if matches:
                fired = max(fired, entry.evidence_frames)
                peak = max(peak, entry.peak_score)
            ground, _source = self.navigability(entry)
            places.append(
                PlaceEvidence(
                    place_id=cand.entry_id,
                    label=entry.label,
                    x=entry.surface_x,
                    y=entry.surface_y,
                    z=entry.surface_z,
                    label_support=support,
                    detection_count=entry.detection_count,
                    evidence_frames=entry.evidence_frames,
                    ground_evidence_fraction=ground,
                    similarity=float(cand.score),
                    # Card P1-D (one line, declared out-of-OWNS): the entry's
                    # bounded best-view crop rides along so the VLM veto has
                    # something to look at. The gate never decodes it.
                    crop_png=entry.thumbnail,
                )
            )

        # Was the detector ever ASKED about this term? Not asking is not
        # evidence of absence, and PG-3 refuses on `asked=False` rather than
        # letting an unasked term look like a searched-for-and-not-found one.
        observed = 0
        for phrase, frames in self._asked_terms.items():
            if wanted & set(label_tokens(phrase)):
                observed = max(observed, frames)
        asked = observed > 0
        # A map built by a harness that never recorded its query batch would
        # otherwise refuse everything; fall back to the frame count and SAY so
        # by leaving `asked` driven purely by the recorded history.
        if not self._asked_terms:
            observed = self._frames_seen
            asked = bool(query)
        fired = min(fired, observed) if observed else 0

        support = DetectorSupport(
            term=query or "?",
            asked=asked,
            frames_observed=observed,
            frames_fired=fired,
            peak_probability=peak,
        )
        # The ranking margin is a robust z-score of the top candidate against
        # the whole map's background FOR THIS QUERY. Both halves matter and
        # getting either wrong breaks it in a way that looks like it works:
        #
        # * Only the candidate list -> the top match is compared against its
        #   own siblings, so a map with one lamppost calls "lamppost"
        #   indecisive forever.
        # * Query-INDEPENDENT scores -> in a healthy map every well-evidenced
        #   place ties, the median absolute deviation is 0, and `ranking_margin`
        #   returns 0.0 for everything. Measured: five equally-observed places
        #   produced margin 0.0 and five abstentions.
        #
        # A place with no label support for THIS query contributes 0.0: it is a
        # real member of the background and it has genuinely no support here.
        background = [
            self._entry_score(entry)
            if wanted & set(label_tokens(entry.label))
            else 0.0
            for entry in self._entries.values()
            if entry.retrievable
        ]
        verdict = assess_place_query(
            query,
            support=support,
            places=places,
            policy=self._policy,
            map_similarities=background,
        )
        diagnostics = {
            "asked": asked,
            "frames_observed": observed,
            "frames_fired": fired,
            "peak_probability": peak,
            "navigability_source": (
                GROUND_SOURCE_TRAVERSAL if self._path else GROUND_SOURCE_UNMEASURED
            ),
            "background_size": len(background),
            "background_mad": _mad(background),
            "ranking_background_degenerate": _mad(background) <= 0.0,
        }
        return verdict, diagnostics

    # -- R18 / R20 consumers ----------------------------------------------

    def around_me(
        self,
        x: float,
        y: float,
        yaw_rad: float,
        *,
        radius_m: float = 15.0,
        limit: int = 12,
    ) -> tuple[dict[str, Any], ...]:
        """R18 scene answerability: what is around me, by kind and bearing."""

        out: list[dict[str, Any]] = []
        for entry in self.active_entries():
            dx = entry.surface_x - float(x)
            dy = entry.surface_y - float(y)
            distance = math.hypot(dx, dy)
            if distance > float(radius_m):
                continue
            bearing = math.atan2(dy, dx) - float(yaw_rad)
            bearing = (bearing + math.pi) % (2.0 * math.pi) - math.pi
            out.append(
                {
                    "entry_id": entry.entry_id,
                    "label": entry.label,
                    "names": list(entry.admissible_names()),
                    "distance_m": round(distance, 3),
                    "bearing_rad": round(bearing, 4),
                    "evidence_frames": entry.evidence_frames,
                    "hygiene_note": entry.hygiene_note,
                }
            )
        out.sort(key=lambda row: (row["distance_m"], row["entry_id"]))
        return tuple(out[: max(0, int(limit))])

    # ============ CARD ROAM-2 (task_33) — THE ONE COVERAGE QUERY ==========
    #
    # ONE new public reader and NOT ONE LINE of the writer. Everything below
    # is derived from fields ``observe``/``_fuse`` already maintain
    # (``last_seen_wall_s``, ``surface_x/y``, ``status``); nothing here can
    # change what the map remembers, and a caller that never calls it gets a
    # byte-identical map.
    #
    # WHY IT LIVES HERE rather than in the patrol package: the visibility rule
    # is the MAP's (``_visibility_range_m``, the same number ``close_visit``
    # decays against in ``_was_expected_visible``), and a second copy of it in
    # a policy would drift the day somebody constructs a map with a different
    # range. The patrol stays pure by taking ONE bearing and ONE age.
    # =====================================================================

    def coverage_candidates(
        self,
        x: float,
        y: float,
        yaw_rad: float,
        *,
        now_wall_s: float | None = None,
        limit: int = 8,
        exclude_visible: bool = True,
        max_radius_m: float | None = None,
    ) -> tuple[dict[str, Any], ...]:
        """Which known places has this map NOT seen lately, and which way are they?

        The coverage objective card ROAM-2 needs, answered by the only thing
        that knows it: **least recently seen first**, each row carrying its own
        body-frame bearing and its own age, so the consumer never has to invent
        either. Rows are ordered oldest-age first; a row whose age cannot be
        computed sorts LAST and carries ``age_s: None`` rather than a zero,
        because "I do not know when I last saw it" is not "I saw it just now".

        ``exclude_visible`` drops entries the robot can see from where it is
        standing, by the MAP's own ``visibility_range_m`` — the same rule
        :meth:`close_visit` decays against. That is what makes this a coverage
        objective rather than a compass: a bench four metres behind the robot
        is already being observed, and pointing the dog back at it would spend
        the whole budget spinning on the spot.

        Never raises on an empty or a broken clock: an empty tuple is a real
        answer and means "nothing to go and look at", which the consumer is
        required to read as *wander*, never as *stop*.
        """

        try:
            ox = float(x)
            oy = float(y)
            yaw = float(yaw_rad)
        except (TypeError, ValueError):
            return ()
        if not all(math.isfinite(value) for value in (ox, oy, yaw)):
            return ()

        clock: float | None
        try:
            clock = None if now_wall_s is None else float(now_wall_s)
        except (TypeError, ValueError):
            clock = None
        if clock is not None and not math.isfinite(clock):
            clock = None

        reach = self._visibility_range_m
        ceiling = None if max_radius_m is None else float(max_radius_m)
        rows: list[dict[str, Any]] = []
        for entry in self.active_entries():
            dx = entry.surface_x - ox
            dy = entry.surface_y - oy
            distance = math.hypot(dx, dy)
            if ceiling is not None and distance > ceiling:
                continue
            visible_now = distance <= reach
            if exclude_visible and visible_now:
                continue
            bearing = math.atan2(dy, dx) - yaw
            bearing = (bearing + math.pi) % (2.0 * math.pi) - math.pi
            age: float | None = None
            if clock is not None:
                delta = clock - entry.last_seen_wall_s
                # A negative age is a clock that disagrees with the store (a
                # reloaded map stamped by another host, a wall clock stepped
                # backwards). Unknown, not zero: zero would read as "seen just
                # now" and would hide the very place the robot should visit.
                if math.isfinite(delta) and delta >= 0.0:
                    age = delta
            rows.append(
                {
                    "entry_id": entry.entry_id,
                    "label": entry.label,
                    "surface_x": round(entry.surface_x, 6),
                    "surface_y": round(entry.surface_y, 6),
                    "distance_m": round(distance, 3),
                    "bearing_rad": round(bearing, 4),
                    "last_seen_wall_s": entry.last_seen_wall_s,
                    "age_s": None if age is None else round(age, 3),
                    "within_visibility": visible_now,
                    "visibility_range_m": reach,
                }
            )
        # Oldest first; unknown ages last; entry_id breaks every tie so the
        # order is stable and a test can pin it.
        rows.sort(
            key=lambda row: (
                1 if row["age_s"] is None else 0,
                -(row["age_s"] or 0.0),
                row["entry_id"],
            )
        )
        return tuple(rows[: max(0, int(limit))])

    # ============ END CARD ROAM-2 coverage query ==========================

    def known_places(self) -> tuple[str, ...]:
        """R20 vocabulary: what this map can be asked about — learned, not labelled.

        Only ACTIVE entries, only ADMISSIBLE names. A decayed place is not
        offered, and an unpromoted VLM guess is not vocabulary.
        """

        vocabulary: set[str] = set()
        for entry in self.active_entries():
            vocabulary.add(entry.label)
            vocabulary.update(entry.admissible_names())
        return tuple(sorted(vocabulary))

    # -- route_memory integration -----------------------------------------

    def bind_place_graph(self, graph: Any) -> int:
        """Attach entries to the EXISTING ``route_memory`` place graph.

        The smallest honest touch is **no touch**: ``RoutePlaceGraph`` already
        takes ``semantic_labels`` on ``record_visit`` and already exposes
        ``nearest_index``, so the place-level graph is reused through its public
        API and not one line of ``route_memory/`` changes. An entry records the
        keyframe it sits nearest; re-localization then rides the graph that
        already survives across sessions instead of a second one invented here.

        Returns the number of entries bound.
        """

        if graph is None:
            raise TypeError("bind_place_graph needs a RoutePlaceGraph")
        self._place_graph = graph
        bound = 0
        for entry in self._entries.values():
            found = graph.nearest_index((entry.surface_x, entry.surface_y))
            index = found[0] if isinstance(found, tuple) else found
            if index is None:
                continue
            entry.place_graph_index = int(index)
            bound += 1
        return bound

    def semantic_labels_near(
        self, x: float, y: float, *, radius_m: float | None = None
    ) -> tuple[str, ...]:
        """Labels to hand ``RoutePlaceGraph.record_visit(semantic_labels=...)``.

        This is the whole integration surface in the other direction: the map
        tells the place graph what the robot can see from here, using the
        graph's own existing parameter.
        """

        reach = self._visibility_range_m if radius_m is None else float(radius_m)
        labels: set[str] = set()
        for entry in self.active_entries():
            if math.dist((float(x), float(y)), (entry.surface_x, entry.surface_y)) <= reach:
                labels.add(entry.label)
        return tuple(sorted(labels))

    # -- persistence -------------------------------------------------------

    def persist(self) -> int:
        """Write every entry to the map's own store. Returns rows written."""

        if self._store is None:
            raise MapRefused("this map has no store; construct it with one")
        written = self._store.save_all(self._entries.values())
        self._store.set_meta("session_id", self._provenance.session_id)
        self._store.set_meta("scene_id", self._provenance.scene_id)
        # Card P1-B. The store's own answer to "which world is this file?",
        # written where a reader looks first — ``load_all`` checks the ROWS, so
        # this meta is a convenience and never the authority.
        self._store.set_meta("origin", self._provenance.origin)
        self._store.set_meta("persisted_entries", str(written))
        return written

    def reload(self) -> int:
        """Rebuild from the store. Returns rows read.

        This is the method the card's "the dog that walked yesterday knows the
        lamppost today" reduces to, and seed 5 is a one-line ``return 0``.
        """

        if self._store is None:
            raise MapRefused("this map has no store; construct it with one")
        loaded = self._store.load_all()
        self._entries = {entry.entry_id: entry for entry in loaded}
        for entry in self._entries.values():
            # Restore the fuse bags from the persisted summary so a reloaded
            # map keeps fusing where it left off rather than snapping to the
            # next observation.
            entry._points = [(entry.surface_x, entry.surface_y, entry.surface_z)]
            entry._extents = [(entry.extent_w_m, entry.extent_h_m)]
        return len(loaded)

    def close(self) -> None:
        """Release the store, checkpointing its WAL. Card P1-B.

        Separate from :meth:`persist` on purpose: persisting is a decision
        (``persist_on_close``) and releasing the file is not. A map whose store
        is never closed leaves its freshly written rows in ``<store>-wal``
        until the interpreter exits, so anything that reads the store file
        during or just after a run — an operator, a copy, a second process —
        sees a map with fewer places in it than the robot learned.

        Idempotent, and the map keeps its entries: after ``close()`` this is an
        in-process map that has forgotten only where it used to live, so a
        caller reading ``entries()`` during teardown still gets an answer.
        Persisting after closing is a refusal, not a silent no-op.
        """

        store = self._store
        if store is None:
            return
        self._store = None
        store.close()


__all__ = [
    "DEFAULT_FUSE_RADIUS_M",
    "DEFAULT_VISIBILITY_RANGE_M",
    "EMBEDDING_RERANKED",
    "EMBEDDING_UNAVAILABLE_ABSENT",
    "EMBEDDING_UNAVAILABLE_VERSION",
    "EMBEDDING_UNUSED",
    "IngestOutcome",
    "MapCandidate",
    "MapQueryResult",
    "MapRefused",
    "OnlineSemanticMap",
    "cosine",
]
