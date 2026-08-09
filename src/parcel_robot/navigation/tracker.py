"""Classical multi-target tracker — the association authority for stratum 2.

Before this module, "is this the same object I saw last frame?" was answered by
**string equality on an oracle id**. The sim hands out a stable ``object_id``
per body, so the navigator could match candidates across frames, and match a
semantic candidate to a LiDAR return, without ever solving an association
problem. Nothing in that answer survives contact with a detector.

This is the classical standard and nothing more — the plan's binding
anti-goals rule out learned components in dispositive positions, and rule out
IPDA for now:

- **motion model:** 2D constant velocity, state ``[x, y, vx, vy]``, with a
  continuous white-noise-acceleration process covariance;
- **gating:** squared Mahalanobis distance against the innovation covariance,
  compared to ``chi2(2, 0.95) = 5.991`` (:data:`CHI2_2DOF_95`);
- **assignment:** global nearest neighbour by Hungarian (Munkres) assignment
  over the gated cost matrix. ``scipy`` is *not* installed in ``.parcel``, so
  the algorithm is implemented here in pure Python — see :func:`hungarian`;
- **confirmation:** ``M``-of-``N`` (3-of-5 by default);
- **deletion:** a miss streak (5 by default).

**IPDA is the documented upgrade seam, not built.** An existence probability
per track would replace the ``M``-of-``N`` *count* with a recursive
probability, and would let a track survive a gap on evidence rather than on a
counter. The place it lands is named at :attr:`Track.existence_probability`,
which is ``None`` today and is never read by any decision.

Class labels are carried as *evidence*, not as a gate: with class confusion on
(tier T1) the same body is reported ``person`` on one frame and ``owner`` on
the next, so a hard class gate would shred exactly the tracks that matter.
:attr:`Track.class_counts` records what was seen and
:attr:`Track.max_other_class_fraction` reports the disagreement, which is what
the arrival-evidence layer consumes.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass, field
from enum import Enum

import numpy as np

#: Chi-square 95th percentile, 2 degrees of freedom. The standard gate for a
#: 2D position measurement: a true measurement falls inside with probability
#: 0.95, so a gate rejection is a 1-in-20 event, not a modelling choice.
CHI2_2DOF_95 = 5.991

#: Sentinel used to mark a forbidden (out-of-gate) assignment.
_BLOCKED = float("inf")


class TrackStatus(str, Enum):
    """Lifecycle states. Exactly one holds for any track at any time."""

    TENTATIVE = "tentative"
    CONFIRMED = "confirmed"
    DELETED = "deleted"


@dataclass(frozen=True)
class TrackerConfig:
    """All tunables in one frozen place; every default is stated, none tuned."""

    #: Gate on squared Mahalanobis distance.
    gate_chi2: float = CHI2_2DOF_95
    #: Continuous white-noise acceleration, m/s^2. 0.5 covers a pedestrian
    #: changing pace; it is not fitted to any measured trajectory.
    process_accel_sigma: float = 0.5
    #: Measurement sigma, metres. Overridden per detection when the detection
    #: carries its own (the D455 quadratic range sigma does).
    measurement_sigma_m: float = 0.15
    #: Birth velocity uncertainty: a new track's speed is unknown, and saying
    #: so is what lets the first association gate open wide enough to catch it.
    initial_velocity_sigma_mps: float = 1.5
    #: M-of-N confirmation.
    confirm_hits: int = 3
    confirm_window: int = 5
    #: Consecutive misses before deletion.
    max_misses: int = 5
    #: Hard cap so a false-positive storm cannot grow the track set without
    #: bound. Oldest tentative tracks are dropped first.
    max_tracks: int = 64

    def __post_init__(self) -> None:
        for name in ("gate_chi2", "process_accel_sigma", "measurement_sigma_m"):
            value = float(getattr(self, name))
            if not math.isfinite(value) or value <= 0.0:
                raise ValueError(f"{name} must be finite and positive")
        if not math.isfinite(self.initial_velocity_sigma_mps) or (
            self.initial_velocity_sigma_mps < 0.0
        ):
            raise ValueError("initial_velocity_sigma_mps must be finite and >= 0")
        if not 1 <= self.confirm_hits <= self.confirm_window:
            raise ValueError("confirm_hits must satisfy 1 <= M <= N")
        if self.max_misses < 1:
            raise ValueError("max_misses must be >= 1")
        if self.max_tracks < 1:
            raise ValueError("max_tracks must be >= 1")


@dataclass
class Detection:
    """One measurement: a world-frame position plus its label and score."""

    x: float
    y: float
    label: str = ""
    score: float = 0.0
    sigma_m: float | None = None
    source_id: str = ""

    def __post_init__(self) -> None:
        for name in ("x", "y", "score"):
            value = float(getattr(self, name))
            if not math.isfinite(value):
                raise ValueError(f"detection {name} must be finite")
            setattr(self, name, value)
        if self.sigma_m is not None:
            sigma = float(self.sigma_m)
            if not math.isfinite(sigma) or sigma <= 0.0:
                raise ValueError("detection sigma_m must be finite and positive")
            self.sigma_m = sigma


@dataclass
class Track:
    """One tracked target: Kalman state, lifecycle counters, class evidence."""

    track_id: int
    mean: np.ndarray  # (4,) [x, y, vx, vy]
    covariance: np.ndarray  # (4, 4)
    status: TrackStatus = TrackStatus.TENTATIVE
    hits: int = 1
    misses: int = 0
    age: int = 1
    #: Recent hit/miss opportunities, newest last, capped at ``confirm_window``.
    window: list[bool] = field(default_factory=lambda: [True])
    class_counts: dict[str, int] = field(default_factory=dict)
    cumulative_score: float = 0.0
    last_score: float = 0.0
    #: IPDA seam. ``None`` today; nothing reads it.
    existence_probability: float | None = None

    @property
    def position(self) -> tuple[float, float]:
        return (float(self.mean[0]), float(self.mean[1]))

    @property
    def velocity(self) -> tuple[float, float]:
        return (float(self.mean[2]), float(self.mean[3]))

    @property
    def position_covariance(self) -> np.ndarray:
        return self.covariance[:2, :2]

    @property
    def position_sigma_m(self) -> float:
        """Scalar position uncertainty, ``sqrt(trace)`` of the xy block."""

        return float(math.sqrt(max(0.0, float(np.trace(self.covariance[:2, :2])))))

    @property
    def dominant_label(self) -> str:
        if not self.class_counts:
            return ""
        return max(sorted(self.class_counts), key=lambda k: self.class_counts[k])

    @property
    def max_other_class_fraction(self) -> float:
        """Share of observations that disagreed with the dominant label.

        ``0.0`` means every sighting agreed. This is the class half of the
        cumulative evidence an arrival decision needs: a "bench" that was
        called something else on a third of its frames has not been verified.
        """

        total = sum(self.class_counts.values())
        if total <= 0:
            return 0.0
        dominant = self.class_counts.get(self.dominant_label, 0)
        return float(total - dominant) / float(total)

    @property
    def mean_score(self) -> float:
        total = sum(self.class_counts.values())
        return float(self.cumulative_score / total) if total > 0 else 0.0

    def predicted_position(self, horizon_s: float) -> tuple[float, float]:
        """Constant-velocity extrapolation, for the final-metre yield policy.

        This is the tracker's answer to "where will that pedestrian be in
        ``horizon_s``", which is what lets an approach creep through a gap
        instead of stopping dead every time the detection stream blinks.
        """

        dt = float(horizon_s)
        if not math.isfinite(dt):
            raise ValueError("horizon_s must be finite")
        return (
            float(self.mean[0] + self.mean[2] * dt),
            float(self.mean[1] + self.mean[3] * dt),
        )


class MultiObjectTracker:
    """Predict → gate → assign → update → birth/death, once per frame."""

    def __init__(self, config: TrackerConfig | None = None) -> None:
        self.config = config if config is not None else TrackerConfig()
        self._tracks: list[Track] = []
        self._deleted: list[Track] = []
        self._next_id = 1
        self._frame = 0

    # ---- inspection -------------------------------------------------------

    @property
    def tracks(self) -> tuple[Track, ...]:
        """Live tracks (tentative + confirmed). Deleted tracks are not here."""

        return tuple(self._tracks)

    @property
    def confirmed(self) -> tuple[Track, ...]:
        return tuple(t for t in self._tracks if t.status is TrackStatus.CONFIRMED)

    @property
    def tentative(self) -> tuple[Track, ...]:
        return tuple(t for t in self._tracks if t.status is TrackStatus.TENTATIVE)

    @property
    def deleted(self) -> tuple[Track, ...]:
        return tuple(self._deleted)

    @property
    def frame_index(self) -> int:
        return self._frame

    def reset(self) -> None:
        self._tracks = []
        self._deleted = []
        self._next_id = 1
        self._frame = 0

    def track_by_id(self, track_id: int) -> Track | None:
        for track in self._tracks:
            if track.track_id == track_id:
                return track
        return None

    def nearest_confirmed(
        self, x: float, y: float, *, label: str = "", max_distance_m: float = math.inf
    ) -> Track | None:
        """Closest confirmed track, optionally restricted to a dominant label."""

        best: Track | None = None
        best_d = float(max_distance_m)
        for track in self._tracks:
            if track.status is not TrackStatus.CONFIRMED:
                continue
            if label and track.dominant_label != label:
                continue
            distance = math.hypot(track.mean[0] - x, track.mean[1] - y)
            if distance <= best_d:
                best_d = distance
                best = track
        return best

    # ---- the frame --------------------------------------------------------

    def step(self, detections: Sequence[Detection], dt_s: float) -> dict[str, object]:
        """Advance one frame. Returns a small per-frame association report."""

        dt = float(dt_s)
        if not math.isfinite(dt) or dt < 0.0:
            raise ValueError("dt_s must be finite and non-negative")
        self._frame += 1

        for track in self._tracks:
            self._predict(track, dt)

        gate = float(self.config.gate_chi2)
        n_tracks = len(self._tracks)
        n_dets = len(detections)
        cost = np.full((n_tracks, n_dets), _BLOCKED, dtype=float)
        for i, track in enumerate(self._tracks):
            innovation_cov, inv = self._innovation(track, None)
            for j, det in enumerate(detections):
                d2 = self._mahalanobis2(track, det, innovation_cov, inv)
                if d2 <= gate:
                    cost[i, j] = d2

        pairs = hungarian(cost)
        matched_tracks = {i for i, _ in pairs}
        matched_dets = {j for _, j in pairs}

        for i, j in pairs:
            self._update(self._tracks[i], detections[j])
        for i, track in enumerate(self._tracks):
            if i not in matched_tracks:
                self._miss(track)

        born: list[int] = []
        for j, det in enumerate(detections):
            if j in matched_dets:
                continue
            born.append(self._birth(det))

        self._reap()
        return {
            "frame": self._frame,
            "matched": len(pairs),
            "born": tuple(born),
            "missed": n_tracks - len(matched_tracks),
            "tracks": len(self._tracks),
            "confirmed": len(self.confirmed),
        }

    # ---- Kalman -----------------------------------------------------------

    def _predict(self, track: Track, dt: float) -> None:
        f = np.eye(4)
        f[0, 2] = dt
        f[1, 3] = dt
        track.mean = f @ track.mean
        track.covariance = f @ track.covariance @ f.T + self._process_noise(dt)
        track.age += 1

    def _process_noise(self, dt: float) -> np.ndarray:
        """Continuous white-noise-acceleration Q (Bar-Shalom, standard form)."""

        s2 = float(self.config.process_accel_sigma) ** 2
        dt2 = dt * dt
        dt3 = dt2 * dt
        dt4 = dt3 * dt
        q = np.zeros((4, 4))
        q[0, 0] = q[1, 1] = dt4 / 4.0
        q[2, 2] = q[3, 3] = dt2
        q[0, 2] = q[2, 0] = q[1, 3] = q[3, 1] = dt3 / 2.0
        return q * s2

    def _measurement_noise(self, det: Detection | None) -> np.ndarray:
        sigma = (
            float(det.sigma_m)
            if det is not None and det.sigma_m is not None
            else float(self.config.measurement_sigma_m)
        )
        return np.eye(2) * (sigma * sigma)

    def _innovation(
        self, track: Track, det: Detection | None
    ) -> tuple[np.ndarray, np.ndarray]:
        s = track.covariance[:2, :2] + self._measurement_noise(det)
        return s, _inv2(s)

    def _mahalanobis2(
        self,
        track: Track,
        det: Detection,
        innovation_cov: np.ndarray,
        inv: np.ndarray,
    ) -> float:
        if det.sigma_m is not None:
            _innovation_cov, inv = self._innovation(track, det)
        nu = np.array([det.x - track.mean[0], det.y - track.mean[1]], dtype=float)
        return float(nu @ inv @ nu)

    def _update(self, track: Track, det: Detection) -> None:
        h = np.zeros((2, 4))
        h[0, 0] = 1.0
        h[1, 1] = 1.0
        s = track.covariance[:2, :2] + self._measurement_noise(det)
        k = track.covariance @ h.T @ _inv2(s)
        nu = np.array([det.x - track.mean[0], det.y - track.mean[1]], dtype=float)
        track.mean = track.mean + k @ nu
        identity = np.eye(4)
        # Joseph form: stays symmetric positive-definite under floating point,
        # which the gate depends on (an asymmetric P makes d^2 meaningless).
        factor = identity - k @ h
        track.covariance = (
            factor @ track.covariance @ factor.T + k @ self._measurement_noise(det) @ k.T
        )
        track.covariance = 0.5 * (track.covariance + track.covariance.T)
        track.hits += 1
        track.misses = 0
        self._record_window(track, True)
        if det.label:
            track.class_counts[det.label] = track.class_counts.get(det.label, 0) + 1
        track.cumulative_score += float(det.score)
        track.last_score = float(det.score)
        self._maybe_confirm(track)

    def _miss(self, track: Track) -> None:
        track.misses += 1
        self._record_window(track, False)
        self._maybe_confirm(track)

    def _record_window(self, track: Track, hit: bool) -> None:
        track.window.append(bool(hit))
        if len(track.window) > self.config.confirm_window:
            del track.window[0 : len(track.window) - self.config.confirm_window]

    def _maybe_confirm(self, track: Track) -> None:
        if track.status is TrackStatus.CONFIRMED:
            return
        if sum(1 for hit in track.window if hit) >= self.config.confirm_hits:
            track.status = TrackStatus.CONFIRMED

    def _birth(self, det: Detection) -> int:
        sigma = (
            float(det.sigma_m)
            if det.sigma_m is not None
            else float(self.config.measurement_sigma_m)
        )
        mean = np.array([det.x, det.y, 0.0, 0.0], dtype=float)
        covariance = np.zeros((4, 4))
        covariance[0, 0] = covariance[1, 1] = sigma * sigma
        v = float(self.config.initial_velocity_sigma_mps)
        covariance[2, 2] = covariance[3, 3] = v * v
        track = Track(
            track_id=self._next_id,
            mean=mean,
            covariance=covariance,
            class_counts={det.label: 1} if det.label else {},
            cumulative_score=float(det.score),
            last_score=float(det.score),
        )
        self._next_id += 1
        self._maybe_confirm(track)
        self._tracks.append(track)
        return track.track_id

    def _reap(self) -> None:
        keep: list[Track] = []
        for track in self._tracks:
            if track.misses >= self.config.max_misses:
                track.status = TrackStatus.DELETED
                self._deleted.append(track)
                continue
            keep.append(track)
        if len(keep) > self.config.max_tracks:
            # Drop the oldest tentative tracks first: a confirmed track has
            # earned its slot with M-of-N evidence, a tentative one has not.
            tentative = [t for t in keep if t.status is TrackStatus.TENTATIVE]
            surplus = len(keep) - self.config.max_tracks
            doomed = {id(t) for t in tentative[:surplus]}
            for track in tentative[:surplus]:
                track.status = TrackStatus.DELETED
                self._deleted.append(track)
            keep = [t for t in keep if id(t) not in doomed][: self.config.max_tracks]
        self._tracks = keep
        if len(self._deleted) > 256:
            del self._deleted[0 : len(self._deleted) - 256]


def _inv2(matrix: np.ndarray) -> np.ndarray:
    """Analytic 2x2 inverse with a fail-closed singular guard."""

    a, b = float(matrix[0, 0]), float(matrix[0, 1])
    c, d = float(matrix[1, 0]), float(matrix[1, 1])
    det = a * d - b * c
    if not math.isfinite(det) or abs(det) < 1e-15:
        # A singular innovation covariance means the gate cannot be evaluated.
        # Returning a zero inverse makes every squared distance 0.0, which
        # would accept everything; return a huge inverse so it accepts nothing.
        return np.eye(2) * 1e15
    return np.array([[d, -b], [-c, a]], dtype=float) / det


def hungarian(cost: np.ndarray) -> list[tuple[int, int]]:
    """Minimum-cost assignment on a rectangular matrix (pure Python).

    ``scipy.optimize.linear_sum_assignment`` is the usual call; ``scipy`` is
    not installed in ``.parcel``, so this is the O(n^3) Jonker-Volgenant-style
    shortest-augmenting-path Hungarian over the same problem. Entries that are
    ``inf`` are forbidden (outside the gate) and never appear in the result.

    Returns ``(row, column)`` pairs, sorted by row.
    """

    matrix = np.asarray(cost, dtype=float)
    if matrix.ndim != 2:
        raise ValueError("cost must be a 2D matrix")
    n_rows, n_cols = matrix.shape
    if n_rows == 0 or n_cols == 0:
        return []

    # Replace inf with a large finite penalty so the algorithm stays numeric;
    # forbidden pairs are filtered out of the result afterwards.
    finite = matrix[np.isfinite(matrix)]
    big = (float(finite.max()) + 1.0) * (n_rows + n_cols) + 1.0 if finite.size else 1.0
    work = np.where(np.isfinite(matrix), matrix, big)

    transposed = n_rows > n_cols
    if transposed:
        work = work.T
    rows, cols = work.shape

    # Standard O(n^3) potentials formulation (e-maxx form), 1-indexed padding.
    u = [0.0] * (rows + 1)
    v = [0.0] * (cols + 1)
    p = [0] * (cols + 1)  # p[j] = row assigned to column j
    way = [0] * (cols + 1)
    for i in range(1, rows + 1):
        p[0] = i
        j0 = 0
        minv = [math.inf] * (cols + 1)
        used = [False] * (cols + 1)
        while True:
            used[j0] = True
            i0 = p[j0]
            delta = math.inf
            j1 = 0
            for j in range(1, cols + 1):
                if used[j]:
                    continue
                cur = work[i0 - 1, j - 1] - u[i0] - v[j]
                if cur < minv[j]:
                    minv[j] = cur
                    way[j] = j0
                if minv[j] < delta:
                    delta = minv[j]
                    j1 = j
            for j in range(cols + 1):
                if used[j]:
                    u[p[j]] += delta
                    v[j] -= delta
                else:
                    minv[j] -= delta
            j0 = j1
            if p[j0] == 0:
                break
        while j0:
            j1 = way[j0]
            p[j0] = p[j1]
            j0 = j1

    pairs: list[tuple[int, int]] = []
    for j in range(1, cols + 1):
        i = p[j]
        if i == 0:
            continue
        row, col = (j - 1, i - 1) if transposed else (i - 1, j - 1)
        if math.isfinite(matrix[row, col]):
            pairs.append((row, col))
    pairs.sort()
    return pairs
