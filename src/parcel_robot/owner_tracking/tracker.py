"""Person pixels → a short-horizon re-ID track → a measured owner confidence.

Card P1-C. The audit's finding was that the owner is a mocap body with
``confidence=1.0`` (``headless_city.py``): there is no identity, no re-ID, and
reacquisition after a loss has never once succeeded because nothing was ever
lost. This module is the missing middle. It consumes the C-1 detection stream
(:class:`~parcel_robot.camera_channel.ingress.CameraDetectionFrame`), crops each
person box out of the RGB frame, embeds the crop through **P1-B's ``embed_fn``
seam** (the same callable ``CameraIngress.embed_fn`` carries — consumed, not
re-implemented), and maintains one track per person with an appearance vector.

THE THREE THINGS IT REFUSES TO DO
---------------------------------
1. **Claim an owner without a gallery.** ``gallery is None`` ⇒ every person is
   ``unknown``, forever, with ``reason="no_gallery"``. There is no default
   owner, no "the nearest person", no "the only person".
2. **Report a confidence it did not measure.** ``identity_score`` is a cosine
   against the enrolled crops. The only way to get 1.0 out of it is to hand it
   a crop byte-identical to an enrolled one.
3. **Guess after a loss.** A track that is not seen this frame is *coasted* —
   kept, so its ``transient_track_id`` survives an occlusion and the same
   identity resumes — but it is **not emitted to fusion**. Its confidence
   decays, and the fusion seam therefore returns no track at all, which is what
   makes the follow controller degrade to searching (``follow.py``'s
   ``invalid_owner_track`` path and ``search_owner``) rather than walk at a
   guess.

WHY THE OWNER TEST IS FLOOR **AND** MARGIN
------------------------------------------
See :mod:`parcel_robot.owner_tracking.gallery`. SigLIP-2 is an image↔text
encoder, not a person-verification network; its absolute cosines between two
different people in the same room are not reliably below its cosines between
two poses of one person. So the claim needs the enrollment-derived floor AND a
discriminative margin over every other person in the same frame. When two people
score within ``min_margin`` of each other the answer is "I do not know", which
is ``ambiguous`` — not a coin flip.

WHY ASSOCIATION IS APPEARANCE-FIRST
-----------------------------------
The failure this card is measured on is a *swap on crossing*. Nearest-neighbour
association in world coordinates swaps by construction at the crossing point,
because at that instant the wrong person is nearer. So position is a **gate**
(a person cannot teleport) and appearance is the **cost** (who is who). The
seeded-RED proof for this is a build where the weights are inverted.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field, replace
from typing import Any

from parcel_robot.camera_channel.ingress import CameraDetectionFrame, CameraDetectionRecord
from parcel_robot.contracts.freshness import expires_from_ttl
from parcel_robot.contracts.v1 import SCHEMA_VERSION, DetectionMsg, EvidenceEnvelopeV1
from parcel_robot.owner_tracking.gallery import AppearanceGallery, cosine, normalize

#: Detector labels that mean "a human body". Whole-word match, matching
#: ``owlv2_onnx.SAFETY_RELEVANT_LABELS``'s convention, so "person holding a cup"
#: is a person and "personal computer" is not.
PERSON_LABELS = frozenset({"person", "people", "human", "man", "woman", "pedestrian"})

#: Tracker states. ``confirmed``/``ambiguous``/``lost`` are the contract's
#: ``OWNER_TRACK_STATES``; ``searching`` is this module's *frame-level* answer
#: when no track holds an owner claim at all, and it is the word the follow
#: controller's degrade path uses. It is never written into ``OwnerTrackV1``.
STATE_CONFIRMED = "confirmed"
STATE_AMBIGUOUS = "ambiguous"
STATE_LOST = "lost"
STATE_SEARCHING = "searching"


def is_person_label(label: str) -> bool:
    """True when a detector label names a human body (whole-word)."""

    return any(word in PERSON_LABELS for word in str(label).lower().replace("-", " ").split())


@dataclass(frozen=True, slots=True)
class OwnerTrackerConfig:
    """Every knob, with the reason it exists. No config file reads this yet.

    Deliberately a dataclass and not a YAML section: P1-C owns no config path
    (the board's OWNS list), and a prototype key that only one package reads is
    better as a declared default than as a shipped file nobody edits. The
    handoff to ``configs/robot.prototype.yaml`` is recorded in the status doc.
    """

    #: Detector score under which a person box is not worth embedding.
    min_person_score: float = 0.20
    #: Crop pixels below which the embedding is noise, not a person.
    min_crop_px: int = 24
    #: How fast a person can plausibly move, for the association GATE. 2.5 m/s
    #: is a brisk walk; it is a gate and not a motion model.
    max_person_speed_mps: float = 2.5
    #: Slack added to the gate radius, absorbing localization error on a single
    #: monocular depth sample.
    assoc_slack_m: float = 0.60
    #: Association cost weights. Appearance dominates ON PURPOSE — see module
    #: docstring. Inverting these is the seeded-RED proof for swap-on-crossing.
    appearance_weight: float = 1.0
    position_weight: float = 0.25
    #: Cost above which a detection is a NEW person rather than a bad match.
    max_assoc_cost: float = 0.75
    #: Appearance EMA. Low alpha keeps the track's vector near what it was when
    #: the track was clean, so a half-occluded frame cannot drag the identity.
    appearance_ema_alpha: float = 0.25
    #: Identity-score EMA, same argument.
    identity_ema_alpha: float = 0.4
    #: Consecutive hits before a track may be called ``confirmed``.
    min_hits: int = 2
    #: Confidence decay constant while coasting. After ``decay_tau_s`` seconds
    #: unseen the score is 1/e of what it was.
    decay_tau_s: float = 1.5
    #: How long a coasted track is kept (so its id survives an occlusion) before
    #: it is dropped and reacquisition starts a NEW identity.
    lost_after_s: float = 4.0
    #: Cap on simultaneous tracks, so a crowd cannot grow the state unboundedly.
    max_tracks: int = 12
    #: TTL on the DetectionMsg this module publishes into fusion.
    detection_ttl_ns: int = 500_000_000

    def __post_init__(self) -> None:
        for name in (
            "min_person_score",
            "appearance_weight",
            "position_weight",
            "max_assoc_cost",
            "appearance_ema_alpha",
            "identity_ema_alpha",
        ):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise TypeError(f"{name} must be numeric")
            if not math.isfinite(float(value)) or float(value) < 0.0:
                raise ValueError(f"{name} must be finite and non-negative")
        for name in ("max_person_speed_mps", "assoc_slack_m", "decay_tau_s", "lost_after_s"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise TypeError(f"{name} must be numeric")
            if not math.isfinite(float(value)) or float(value) <= 0.0:
                raise ValueError(f"{name} must be finite and positive")
        for name in ("min_crop_px", "min_hits", "max_tracks", "detection_ttl_ns"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise ValueError(f"{name} must be a positive integer")
        if self.appearance_weight <= 0.0:
            raise ValueError(
                "appearance_weight must be positive: a position-only cost swaps "
                "identities at every crossing by construction (card P1-C)"
            )


@dataclass(frozen=True, slots=True)
class PersonObservation:
    """One person detection with its crop embedding, ready to associate."""

    label: str
    score: float
    box: tuple[float, float, float, float]
    world_x: float
    world_y: float
    range_m: float
    bearing_rad: float
    embedding: tuple[float, ...]
    gallery_similarity: float = 0.0

    @classmethod
    def from_record(
        cls,
        record: CameraDetectionRecord,
        embedding: Sequence[float],
        *,
        gallery_similarity: float = 0.0,
    ) -> PersonObservation:
        return cls(
            label=record.label,
            score=float(record.score),
            box=tuple(float(v) for v in record.box),  # type: ignore[arg-type]
            world_x=float(record.world_x),
            world_y=float(record.world_y),
            range_m=float(record.range_m),
            bearing_rad=float(record.bearing_rad),
            embedding=normalize(embedding),
            gallery_similarity=float(gallery_similarity),
        )


@dataclass(frozen=True, slots=True)
class PixelOwnerTrack:
    """One tracked person as the rest of the stack reads it.

    ``identity_similarity`` is the RAW cosine (it may be negative — SigLIP-2
    embeddings are not constrained to a positive orthant). ``identity_score`` is
    the same number clamped into [0, 1] because that is what
    ``contracts.v1._probability`` accepts. Both are carried so nobody has to
    reverse a clamp to know what was measured.
    """

    track_id: str
    label: str
    state: str
    identity_similarity: float
    identity_score: float
    identity_margin: float
    visibility_score: float
    world_x: float
    world_y: float
    range_m: float
    bearing_rad: float
    box: tuple[float, float, float, float]
    hits: int
    misses: int
    age_s: float
    seen_this_frame: bool
    embedding: tuple[float, ...] = ()
    gallery_enrolled: bool = False
    #: Card P1-C. False when the gallery's threshold was DERIVED from the
    #: owner's own crops rather than measured against a known non-owner. A claim
    #: from an uncalibrated gallery is still a measurement, but its boundary is
    #: a guess — and on SigLIP-2 whole-body crops that guess was measured to
    #: admit a stranger. Carried out to the fusion seam so the difference
    #: survives the trip rather than being folded into one float.
    gallery_calibrated: bool = False
    reason: str = ""

    @property
    def is_owner(self) -> bool:
        return self.label == "owner"

    def as_detection_msg(
        self,
        *,
        now_monotonic_ns: int,
        source_timestamp_ns: int,
        sequence: int,
        frame_id: str = "camera_color_optical_frame",
        source: str = "owner_tracking_reid",
        calibration_id: str = "owner-tracking-reid-v1",
        ttl_ns: int = 500_000_000,
    ) -> DetectionMsg:
        """The pixel channel as ``OwnerFusionStub`` already knows how to read it.

        ``class_id`` is ``owner`` only when this track holds a gallery-backed
        claim; otherwise ``person``. ``score`` is the DETECTOR's confidence that
        there is a person there, which is a different question from identity —
        identity travels in :meth:`as_fusion_input`.
        """

        if not self.embedding:
            raise ValueError(
                f"track {self.track_id} has no appearance embedding; a DetectionMsg "
                "without one would be a pose with a fabricated identity"
            )
        envelope = EvidenceEnvelopeV1(
            schema_version=SCHEMA_VERSION,
            evidence_id=f"pixel-owner-{self.track_id}-{sequence}",
            source=source,
            source_timestamp_ns=int(source_timestamp_ns),
            received_monotonic_ns=int(now_monotonic_ns),
            sequence=int(sequence),
            frame_id=frame_id,
            scene_revision=0,
            expires_monotonic_ns=expires_from_ttl(
                received_monotonic_ns=int(now_monotonic_ns), ttl_ns=int(ttl_ns)
            ),
            calibration_id=calibration_id,
            provenance=("owner_tracking_v1", "siglip2_crop_reid"),
        )
        return DetectionMsg(
            envelope=envelope,
            class_id="owner" if self.is_owner else "person",
            embedding=tuple(self.embedding),
            bearing_rad=_wrap_pi(self.bearing_rad),
            range_m=max(0.0, min(200.0, self.range_m)),
            score=max(0.0, min(1.0, self.visibility_score)),
            track_id=self.track_id,
        )

    def as_fusion_input(self, *, source_timestamp_ns: int = 0) -> Any:
        """The identity seam ``uwb.fusion`` consumes. Imported lazily (no cycle)."""

        from parcel_robot.uwb.fusion import PixelTrackInput

        return PixelTrackInput(
            transient_track_id=self.track_id,
            identity_similarity=self.identity_score,
            visibility=max(0.0, min(1.0, self.visibility_score)),
            owner_claim=self.is_owner,
            gallery_enrolled=self.gallery_enrolled,
            gallery_calibrated=self.gallery_calibrated,
            source_timestamp_ns=int(source_timestamp_ns),
        )


@dataclass(frozen=True, slots=True)
class OwnerTrackerUpdate:
    """One frame's answer. ``owner_track`` is ``None`` when nobody is claimed."""

    frame_id: str
    sequence: int
    state: str
    reason: str
    owner_track: PixelOwnerTrack | None
    tracks: tuple[PixelOwnerTrack, ...]
    persons_seen: int
    embedded: int

    @property
    def owner_claimed(self) -> bool:
        return self.owner_track is not None and self.owner_track.is_owner


@dataclass
class _Track:
    """Mutable internal state. Never handed out; :class:`PixelOwnerTrack` is."""

    track_id: str
    embedding: tuple[float, ...]
    world_x: float
    world_y: float
    range_m: float
    bearing_rad: float
    box: tuple[float, float, float, float]
    visibility: float
    identity_ema: float
    last_seen_ns: int
    hits: int = 1
    misses: int = 0
    label: str = "unknown"
    last_similarity: float = 0.0
    last_margin: float = 0.0
    reason: str = ""
    history: list[float] = field(default_factory=list)


def _wrap_pi(bearing: float) -> float:
    wrapped = (float(bearing) + math.pi) % (2.0 * math.pi) - math.pi
    return max(-math.pi, min(math.pi, wrapped))


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


class OwnerTracker:
    """Short-horizon multi-person re-ID track over the C-1 detection stream.

    Not thread-safe and not meant to be: it is driven from exactly one place —
    the consumer of ``CameraIngress.on_frame`` — and a lock here would be a lock
    held across the ingress publish seam, which is the lock-order edge R24's
    roster exists to prevent.
    """

    def __init__(
        self,
        *,
        gallery: AppearanceGallery | None = None,
        embed_fn: Callable[[Any], Sequence[float]] | None = None,
        config: OwnerTrackerConfig | None = None,
    ) -> None:
        if embed_fn is not None and not callable(embed_fn):
            raise TypeError("embed_fn must be callable")
        if gallery is not None and not isinstance(gallery, AppearanceGallery):
            raise TypeError("gallery must be an AppearanceGallery or None")
        self._gallery = gallery
        self._embed_fn = embed_fn
        self._config = config if config is not None else OwnerTrackerConfig()
        self._tracks: list[_Track] = []
        self._next_id = 0
        self._embed_calls = 0
        self._embed_failures = 0

    # ---------------------------------------------------------------- surface
    @property
    def config(self) -> OwnerTrackerConfig:
        return self._config

    @property
    def gallery(self) -> AppearanceGallery | None:
        return self._gallery

    @property
    def enrolled(self) -> bool:
        return self._gallery is not None

    @property
    def embed_calls(self) -> int:
        return self._embed_calls

    @property
    def embed_failures(self) -> int:
        return self._embed_failures

    def reset(self) -> None:
        self._tracks.clear()

    # ------------------------------------------------------------ the update
    def update(
        self,
        frame: CameraDetectionFrame,
        *,
        rgb: Any | None = None,
        now_monotonic_ns: int | None = None,
    ) -> OwnerTrackerUpdate:
        """Consume one published C-1 frame. ``rgb`` is the image the boxes index.

        ``rgb`` may be ``None`` (the frame arrived without pixels, or no encoder
        is configured). That is a DEGRADE, not a failure: tracks still coast on
        position so the follow controller keeps a pose, but no identity is
        asserted and ``reason`` says why. The one thing that never happens is an
        owner claim without an embedding.
        """

        cfg = self._config
        now = int(now_monotonic_ns) if now_monotonic_ns is not None else int(
            frame.published_monotonic_ns
        )
        records = [
            record
            for record in frame.detections
            if is_person_label(record.label) and float(record.score) >= cfg.min_person_score
        ]
        observations, embed_reason = self._embed(records, rgb)
        assigned = self._associate(observations, now)
        self._score_identity(observations, assigned)
        self._retire(now)
        tracks = tuple(self._snapshot(track, now) for track in self._tracks)
        owner = next((track for track in tracks if track.is_owner and track.seen_this_frame), None)
        if owner is not None:
            state = owner.state
            reason = owner.reason or "ok"
        elif not self._gallery:
            state = STATE_SEARCHING
            reason = "no_gallery"
        elif embed_reason:
            state = STATE_SEARCHING
            reason = embed_reason
        elif any(track.seen_this_frame for track in tracks):
            state = STATE_SEARCHING
            reason = "no_gallery_match"
        else:
            state = STATE_SEARCHING
            reason = "no_person_detected"
        return OwnerTrackerUpdate(
            frame_id=str(frame.frame_id),
            sequence=int(frame.sequence),
            state=state,
            reason=reason,
            owner_track=owner,
            tracks=tracks,
            persons_seen=len(records),
            embedded=len(observations),
        )

    # ------------------------------------------------------------- internals
    def _embed(
        self, records: Sequence[CameraDetectionRecord], rgb: Any | None
    ) -> tuple[list[PersonObservation], str]:
        """Crop → ``embed_fn`` → :class:`PersonObservation`. Never raises out."""

        if self._embed_fn is None:
            return [], "no_embedder"
        if rgb is None:
            return [], "no_pixels"
        observations: list[PersonObservation] = []
        cfg = self._config
        for record in records:
            crop = _crop(rgb, record.box, minimum_px=cfg.min_crop_px)
            if crop is None:
                continue
            try:
                self._embed_calls += 1
                raw = self._embed_fn(crop)
            except Exception:  # noqa: BLE001 — an encoder fault degrades, never kills the track
                self._embed_failures += 1
                continue
            vector = normalize([float(v) for v in raw])
            if not any(vector):
                self._embed_failures += 1
                continue
            similarity = 0.0
            if self._gallery is not None:
                try:
                    similarity = self._gallery.similarity(vector)
                except ValueError:
                    # Dimension mismatch: the gallery was computed with a
                    # different encoder. Refusing to score is the whole reason
                    # the gallery carries a model name.
                    self._embed_failures += 1
                    return [], "gallery_model_mismatch"
            observations.append(
                PersonObservation.from_record(record, vector, gallery_similarity=similarity)
            )
        if records and not observations:
            return [], "no_usable_crops"
        return observations, ""

    def _associate(
        self, observations: Sequence[PersonObservation], now: int
    ) -> dict[int, int]:
        """Greedy min-cost assignment, position-gated and appearance-driven.

        Returns ``{observation index: track index}``. Deterministic: ties break
        on (cost, track index, observation index), so the same frame always
        produces the same association.
        """

        cfg = self._config
        pairs: list[tuple[float, int, int]] = []
        for track_index, track in enumerate(self._tracks):
            dt_s = max(1e-3, (now - track.last_seen_ns) / 1e9)
            gate_m = cfg.max_person_speed_mps * dt_s + cfg.assoc_slack_m
            for obs_index, obs in enumerate(observations):
                distance = math.hypot(obs.world_x - track.world_x, obs.world_y - track.world_y)
                if distance > gate_m:
                    continue  # a person cannot teleport; this is the GATE
                appearance = 1.0 - cosine(track.embedding, obs.embedding)
                cost = (
                    cfg.appearance_weight * appearance
                    + cfg.position_weight * (distance / gate_m)
                )
                if cost > cfg.max_assoc_cost:
                    continue
                pairs.append((cost, track_index, obs_index))
        pairs.sort()
        taken_tracks: set[int] = set()
        taken_obs: set[int] = set()
        assigned: dict[int, int] = {}
        for _cost, track_index, obs_index in pairs:
            if track_index in taken_tracks or obs_index in taken_obs:
                continue
            taken_tracks.add(track_index)
            taken_obs.add(obs_index)
            assigned[obs_index] = track_index
            self._absorb(self._tracks[track_index], observations[obs_index], now)
        for obs_index, obs in enumerate(observations):
            if obs_index in taken_obs:
                continue
            if len(self._tracks) >= cfg.max_tracks:
                continue
            assigned[obs_index] = len(self._tracks)
            self._tracks.append(self._spawn(obs, now))
        for track_index, track in enumerate(self._tracks):
            if track_index not in taken_tracks and track.last_seen_ns != now:
                track.misses += 1
        return assigned

    def _absorb(self, track: _Track, obs: PersonObservation, now: int) -> None:
        alpha = self._config.appearance_ema_alpha
        blended = [
            (1.0 - alpha) * old + alpha * new
            for old, new in zip(track.embedding, obs.embedding, strict=True)
        ]
        track.embedding = normalize(blended)
        track.world_x = obs.world_x
        track.world_y = obs.world_y
        track.range_m = obs.range_m
        track.bearing_rad = obs.bearing_rad
        track.box = obs.box
        track.visibility = obs.score
        track.last_seen_ns = now
        track.hits += 1
        track.misses = 0

    def _spawn(self, obs: PersonObservation, now: int) -> _Track:
        self._next_id += 1
        return _Track(
            track_id=f"pixel-person-{self._next_id}",
            embedding=obs.embedding,
            world_x=obs.world_x,
            world_y=obs.world_y,
            range_m=obs.range_m,
            bearing_rad=obs.bearing_rad,
            box=obs.box,
            visibility=obs.score,
            identity_ema=0.0,
            last_seen_ns=now,
        )

    def _score_identity(
        self, observations: Sequence[PersonObservation], assigned: dict[int, int]
    ) -> None:
        """Floor + margin, over the persons seen in THIS frame. Fails to unknown."""

        gallery = self._gallery
        cfg = self._config
        for obs_index, track_index in assigned.items():
            track = self._tracks[track_index]
            similarity = observations[obs_index].gallery_similarity if gallery else 0.0
            alpha = cfg.identity_ema_alpha
            track.identity_ema = (
                similarity if track.hits <= 1 else (1.0 - alpha) * track.identity_ema
                + alpha * similarity
            )
            track.last_similarity = similarity
            track.history.append(similarity)
        if gallery is None:
            for track in self._tracks:
                track.label = "unknown"
                track.last_margin = 0.0
                track.reason = "no_gallery"
            return
        scored = sorted(
            ((observations[i].gallery_similarity, t) for i, t in assigned.items()),
            key=lambda item: item[0],
            reverse=True,
        )
        best_track = scored[0][1] if scored else None
        best_similarity = scored[0][0] if scored else 0.0
        runner_up = scored[1][0] if len(scored) > 1 else 0.0
        margin = best_similarity - runner_up
        for track in self._tracks:
            track.last_margin = 0.0
        for _similarity, track_index in scored:
            track = self._tracks[track_index]
            if track_index == best_track:
                track.last_margin = margin
                if best_similarity < gallery.threshold:
                    track.label = "unknown"
                    track.reason = "below_threshold"
                elif margin < gallery.min_margin:
                    # Two people the encoder cannot tell apart. "I do not know"
                    # is the answer; a coin flip is not.
                    track.label = "unknown"
                    track.reason = "ambiguous_margin"
                else:
                    track.label = "owner"
                    track.reason = (
                        "gallery_match" if gallery.calibrated else "gallery_match_uncalibrated"
                    )
            else:
                track.label = "unknown"
                track.reason = "not_best_match"

    def _retire(self, now: int) -> None:
        limit_ns = int(self._config.lost_after_s * 1e9)
        self._tracks = [track for track in self._tracks if now - track.last_seen_ns <= limit_ns]

    def _snapshot(self, track: _Track, now: int) -> PixelOwnerTrack:
        cfg = self._config
        age_s = max(0.0, (now - track.last_seen_ns) / 1e9)
        seen = track.last_seen_ns == now
        decayed = track.identity_ema * math.exp(-age_s / cfg.decay_tau_s) if age_s > 0 else (
            track.identity_ema
        )
        if not seen:
            state = STATE_LOST
        elif track.label == "owner" and track.hits >= cfg.min_hits:
            state = STATE_CONFIRMED
        else:
            state = STATE_AMBIGUOUS
        return PixelOwnerTrack(
            track_id=track.track_id,
            # A coasted track is NOT an owner claim, whatever it was last frame:
            # the label is what the pixels said this frame, and this frame has
            # no pixels of this person.
            label=track.label if seen else "unknown",
            state=state,
            identity_similarity=decayed,
            identity_score=_clamp01(decayed),
            identity_margin=track.last_margin if seen else 0.0,
            visibility_score=_clamp01(track.visibility * math.exp(-age_s / cfg.decay_tau_s)),
            world_x=track.world_x,
            world_y=track.world_y,
            range_m=track.range_m,
            bearing_rad=track.bearing_rad,
            box=track.box,
            hits=track.hits,
            misses=track.misses,
            age_s=age_s,
            seen_this_frame=seen,
            embedding=track.embedding,
            gallery_enrolled=self._gallery is not None,
            gallery_calibrated=bool(self._gallery is not None and self._gallery.calibrated),
            reason=track.reason if seen else "coasting",
        )


def _crop(rgb: Any, box: Sequence[float], *, minimum_px: int) -> Any | None:
    """Slice a box out of an HxWx3 array. ``None`` when it is too small to mean anything."""

    try:
        height = int(rgb.shape[0])
        width = int(rgb.shape[1])
    except (AttributeError, IndexError, TypeError):
        return None
    u0, v0, u1, v1 = (float(v) for v in box)
    x0 = max(0, min(width, math.floor(min(u0, u1))))
    x1 = max(0, min(width, math.ceil(max(u0, u1))))
    y0 = max(0, min(height, math.floor(min(v0, v1))))
    y1 = max(0, min(height, math.ceil(max(v0, v1))))
    if (x1 - x0) < minimum_px or (y1 - y0) < minimum_px:
        return None
    crop = rgb[y0:y1, x0:x1]
    if getattr(crop, "size", 0) == 0:
        return None
    return crop


def replace_config(tracker: OwnerTracker, **changes: Any) -> OwnerTracker:
    """A fresh tracker with a modified config. Used by the seeded-RED proofs."""

    return OwnerTracker(
        gallery=tracker.gallery,
        embed_fn=tracker._embed_fn,
        config=replace(tracker.config, **changes),
    )


__all__ = [
    "PERSON_LABELS",
    "STATE_AMBIGUOUS",
    "STATE_CONFIRMED",
    "STATE_LOST",
    "STATE_SEARCHING",
    "OwnerTracker",
    "OwnerTrackerConfig",
    "OwnerTrackerUpdate",
    "PersonObservation",
    "PixelOwnerTrack",
    "is_person_label",
    "replace_config",
]
