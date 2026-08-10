"""Pure multi-view confirmation and false-positive memory for ``DetectionMsg``.

Frozen contract
---------------
``MultiViewConfirm.update(detection) -> (confirmed, credibility, rejected_ids)``.
The input is the existing pixel-path :class:`~parcel_robot.contracts.DetectionMsg`
contract (or ``None`` for an explicitly empty view).  The result is a boolean
for the observation's associated hypothesis, its rolling credibility in
``[0, 1]``, and the currently remembered rejected hypothesis ids.

The default decision is 3-of-5 distinct views.  Credibility is accumulated as
``1 - product(1 - score_i)`` over hits in the rolling window, so detector
scores in the observed lamppost range (0.28--0.42) can cross the default 0.65
commit threshold after repeated views without a class-specific score gate.
A single frame can never commit, regardless of score.

Rejected hypotheses enter a bounded geometric memory.  Re-observing the same
``track_id`` (or a nearby class/bearing/range box when no id exists) is
suppressed until that memory expires, preventing the next scan from reviving
the same one-frame false positive.

This module deliberately does *not* implement IPDA.  ``existence_probability``
remains the documented future seam; credibility here is finite-window evidence,
not a recursive probability of existence.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from parcel_robot.contracts import DetectionMsg

DOES_NOT_PROVE = (
    (
        "Pure confirmation cells prove finite-window evidence and false-positive "
        "memory behavior, not detector precision or real D455 recognition."
    ),
    (
        "Repeated, view-consistent hallucinations can satisfy M-of-N; IPDA and the "
        "full runtime T-cam false-arrival gate remain deferred."
    ),
)


@dataclass(frozen=True, slots=True)
class MultiViewConfig:
    """Frozen, class-agnostic confirmation policy."""

    confirm_hits: int = 3
    confirm_window: int = 5
    credibility_threshold: float = 0.65
    association_bearing_rad: float = math.radians(8.0)
    association_range_m: float = 0.75
    rejected_memory_views: int = 30
    max_hypotheses: int = 64

    def __post_init__(self) -> None:
        if not 1 <= self.confirm_hits <= self.confirm_window:
            raise ValueError("confirm_hits must satisfy 1 <= M <= N")
        if not 0.0 <= self.credibility_threshold <= 1.0:
            raise ValueError("credibility_threshold must be in [0, 1]")
        if not math.isfinite(self.association_bearing_rad) or (
            self.association_bearing_rad < 0.0
        ):
            raise ValueError("association_bearing_rad must be finite and >= 0")
        if not math.isfinite(self.association_range_m) or self.association_range_m < 0.0:
            raise ValueError("association_range_m must be finite and >= 0")
        if self.rejected_memory_views < 1:
            raise ValueError("rejected_memory_views must be >= 1")
        if self.max_hypotheses < 1:
            raise ValueError("max_hypotheses must be >= 1")


@dataclass(slots=True)
class _Hypothesis:
    hypothesis_id: str
    class_id: str
    track_id: str
    bearing_rad: float
    range_m: float
    hits: list[bool] = field(default_factory=list)
    scores: list[float] = field(default_factory=list)
    confirmed: bool = False
    last_view: object | None = None

    @property
    def credibility(self) -> float:
        miss_product = 1.0
        for hit, score in zip(self.hits, self.scores, strict=True):
            if hit:
                miss_product *= 1.0 - score
        return max(0.0, min(1.0, 1.0 - miss_product))


@dataclass(slots=True)
class _Rejected:
    hypothesis_id: str
    class_id: str
    track_id: str
    bearing_rad: float
    range_m: float
    views_left: int


class MultiViewConfirm:
    """Stateful pure evidence accumulator implementing the frozen contract."""

    def __init__(self, config: MultiViewConfig | None = None) -> None:
        self.config = config if config is not None else MultiViewConfig()
        self._hypotheses: list[_Hypothesis] = []
        self._rejected: list[_Rejected] = []
        self._view_token: object | None = None
        self._empty_view_counter = 0
        self._next_id = 1

    @property
    def rejected_ids(self) -> tuple[str, ...]:
        """Active false-positive-memory ids, stable and sorted."""

        return tuple(sorted(item.hypothesis_id for item in self._rejected))

    def reset(self) -> None:
        self._hypotheses.clear()
        self._rejected.clear()
        self._view_token = None
        self._empty_view_counter = 0
        self._next_id = 1

    def update(
        self, detection: DetectionMsg | None
    ) -> tuple[bool, float, tuple[str, ...]]:
        """Consume one detection or one explicit empty-view marker.

        Detections sharing ``envelope.source_timestamp_ns`` belong to one view
        and cannot add multiple M-of-N hits.  ``None`` always advances one empty
        view.  The detector must therefore call ``update(None)`` for a frame
        with no boxes if misses are to count toward rejection.
        """

        if detection is not None and not isinstance(detection, DetectionMsg):
            raise TypeError("detection must be DetectionMsg or None")

        view_token: object
        if detection is None:
            self._empty_view_counter += 1
            view_token = ("empty", self._empty_view_counter)
        else:
            view_token = ("timestamp", detection.envelope.source_timestamp_ns)

        if view_token != self._view_token:
            self._advance_view(view_token)

        if detection is None:
            return (False, 0.0, self.rejected_ids)

        remembered = self._match_rejected(detection)
        if remembered is not None:
            return (False, 0.0, self.rejected_ids)

        hypothesis = self._match_live(detection)
        if hypothesis is None:
            hypothesis = self._birth(detection)
        self._record_hit(hypothesis, detection, view_token)
        return (hypothesis.confirmed, hypothesis.credibility, self.rejected_ids)

    def _advance_view(self, view_token: object) -> None:
        for rejected in self._rejected:
            rejected.views_left -= 1
        self._rejected = [item for item in self._rejected if item.views_left > 0]

        # Finalize the complete window before opening the next view.  This
        # permits multiple boxes from one timestamp without prematurely
        # rejecting a hypothesis before its matching box is consumed.
        keep: list[_Hypothesis] = []
        for hypothesis in self._hypotheses:
            if (
                not hypothesis.confirmed
                and len(hypothesis.hits) >= self.config.confirm_window
                and sum(hypothesis.hits) < self.config.confirm_hits
            ):
                self._remember(hypothesis)
            else:
                keep.append(hypothesis)
        self._hypotheses = keep

        for hypothesis in self._hypotheses:
            hypothesis.hits.append(False)
            hypothesis.scores.append(0.0)
            self._trim(hypothesis)
        self._view_token = view_token

    def _birth(self, detection: DetectionMsg) -> _Hypothesis:
        hypothesis_id = detection.track_id or f"mv-{self._next_id}"
        self._next_id += 1
        hypothesis = _Hypothesis(
            hypothesis_id=hypothesis_id,
            class_id=detection.class_id,
            track_id=detection.track_id,
            bearing_rad=float(detection.bearing_rad),
            range_m=float(detection.range_m),
            hits=[False],
            scores=[0.0],
        )
        self._hypotheses.append(hypothesis)
        if len(self._hypotheses) > self.config.max_hypotheses:
            tentative = next((h for h in self._hypotheses if not h.confirmed), None)
            doomed = tentative if tentative is not None else self._hypotheses[0]
            self._hypotheses.remove(doomed)
            self._remember(doomed)
        return hypothesis

    def _record_hit(
        self, hypothesis: _Hypothesis, detection: DetectionMsg, view_token: object
    ) -> None:
        if hypothesis.last_view != view_token:
            hypothesis.hits[-1] = True
            hypothesis.scores[-1] = float(detection.score)
            hypothesis.last_view = view_token
        else:
            # Multiple boxes for one hypothesis in one view are one witness;
            # retain only the strongest score.
            hypothesis.scores[-1] = max(hypothesis.scores[-1], float(detection.score))
        hypothesis.bearing_rad = float(detection.bearing_rad)
        hypothesis.range_m = float(detection.range_m)
        self._trim(hypothesis)
        if (
            sum(hypothesis.hits) >= self.config.confirm_hits
            and hypothesis.credibility >= self.config.credibility_threshold
        ):
            hypothesis.confirmed = True

    def _trim(self, hypothesis: _Hypothesis) -> None:
        excess = len(hypothesis.hits) - self.config.confirm_window
        if excess > 0:
            del hypothesis.hits[:excess]
            del hypothesis.scores[:excess]

    def _match_live(self, detection: DetectionMsg) -> _Hypothesis | None:
        if detection.track_id:
            exact = next(
                (h for h in self._hypotheses if h.track_id == detection.track_id), None
            )
            if exact is not None:
                return exact
        candidates = [
            h
            for h in self._hypotheses
            if h.class_id == detection.class_id and self._near(h, detection)
        ]
        if not candidates:
            return None
        return min(
            candidates,
            key=lambda h: (
                abs(_angle_delta(h.bearing_rad, detection.bearing_rad)),
                abs(h.range_m - detection.range_m),
            ),
        )

    def _match_rejected(self, detection: DetectionMsg) -> _Rejected | None:
        if detection.track_id:
            exact = next(
                (r for r in self._rejected if r.track_id == detection.track_id), None
            )
            if exact is not None:
                return exact
        return next(
            (
                r
                for r in self._rejected
                if r.class_id == detection.class_id and self._near(r, detection)
            ),
            None,
        )

    def _near(self, item: _Hypothesis | _Rejected, detection: DetectionMsg) -> bool:
        return (
            abs(_angle_delta(item.bearing_rad, detection.bearing_rad))
            <= self.config.association_bearing_rad
            and abs(item.range_m - detection.range_m)
            <= self.config.association_range_m
        )

    def _remember(self, hypothesis: _Hypothesis) -> None:
        self._rejected = [
            item for item in self._rejected if item.hypothesis_id != hypothesis.hypothesis_id
        ]
        self._rejected.append(
            _Rejected(
                hypothesis_id=hypothesis.hypothesis_id,
                class_id=hypothesis.class_id,
                track_id=hypothesis.track_id,
                bearing_rad=hypothesis.bearing_rad,
                range_m=hypothesis.range_m,
                views_left=self.config.rejected_memory_views,
            )
        )


def _angle_delta(left: float, right: float) -> float:
    return (float(left) - float(right) + math.pi) % (2.0 * math.pi) - math.pi
