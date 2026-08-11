"""The perception chain — the ONE semantic-candidate ingress on the mission path.

Stratum 2 (``docs/STRATA_GENERALIZATION_PLAN.md``). Before this module the
navigator read ``SimObservation.semantic_objects`` / ``semantic_regions``
directly: oracle rows with stable ids, exact world coordinates, and a literal
confidence. The built-but-unwired ``detection_adapter`` chain existed beside
that path and nothing on the mission path consumed it.

This module makes the chain the ingress. Every semantic candidate the
navigator will ever see is lifted to :class:`GroundTruthDetection`, passed
through a detector-shaped stage, and reconstructed — for regions as well as
objects, in the runtime and in every headless harness.

Two tiers ship (``configs/navigation/default.yaml``):

``T0`` — **pass-through, the default.** The structural round-trip runs in
full, but the stage is the identity: no RNG is drawn, no row is dropped, no
class is confused, and every reconstructed row is *the caller's own dict
object*. This is not an approximation of equality; see
:meth:`PerceptionChain.process`.

``T1`` — **calibrated.** D455 quadratic range sigma, range-scaled dropout,
false positives at a datasheet-traceable rate, and confidences drawn from an
*overlapping* true-positive / false-positive pair. T1 is measurement, not a
gate.

**Not built, deliberately (plan anti-goal):** IPDA existence probability. The
drop-in seam is named in :class:`NoiseTier` — a per-detection existence
probability would multiply into ``confidence`` here and be consumed by the
tracker's ``M``-of-``N`` confirmation as a weight rather than a count. Nothing
in this file guesses at it today.
"""

from __future__ import annotations

import math
import random
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from parcel_robot.detection_adapter.adapter import GroundTruthDetection
from parcel_robot.detection_adapter.noise import (
    DEFAULT_SIM_VOCABULARY,
    default_person_confusion,
)
from parcel_robot.detection_adapter.sim_bridge import (
    bearing_range_from_pose,
    label_embedding,
)

#: Tier names. ``T0`` is the shipping default and changes nothing.
TIER_T0 = "T0"
TIER_T1 = "T1"

#: The COMPLETE set of tiers :meth:`PerceptionChain.from_tier` can construct, and
#: therefore the complete set ``use_perception_chain`` can install on the mission
#: path. Exported so a claim about a tier can be checked instead of believed.
#:
#: Read this before writing "T-cam" in a report. There is **no T-cam tier**. The
#: ``T-cam*`` ids in ``evals/nav_instruct/cam_*.py`` are card-local REPORT labels
#: on standalone cells that call the detector/localizer modules directly; none of
#: them travels through this seam, so none of them exercises the noise model,
#: the false-positive injector, or the T0 byte-equality short-circuit. Fable's
#: independent audit of task_15 returned every "T-cam" gate row for exactly that
#: conflation; those cells now carry ``T-cam-proxy-*`` ids. Registering a real
#: ``T-CAM`` tier means giving it a :class:`NoiseTier` whose candidates come from
#: rendered pixels rather than the GT oracle ``_lift`` reads — a wiring card, not
#: a rename.
REGISTERED_TIERS: tuple[str, ...] = (TIER_T0, TIER_T1)

#: Intel RealSense D455 depth-error model. RMS depth error for a stereo pair is
#: ``sigma_z(z) = z^2 * sigma_disparity / (focal_px * baseline_m)``. For the
#: D455: baseline 0.095 m; 1280 px across an 87 deg horizontal FOV gives
#: ``focal_px = 640 / tan(43.5 deg) = 674.4``; sub-pixel matching sigma is taken
#: at 0.08 px. That is ``0.08 / (674.4 * 0.095) = 1.25e-3`` per metre, i.e.
#: 0.02 m at 4 m — 0.5 % of range RMS, consistent with the datasheet's "<2 % at
#: 4 m" *bound* at roughly 4 sigma. Traceable, not tuned.
D455_DEPTH_SIGMA_COEFF_PER_M = 1.25e-3

#: Angular localisation sigma. A detection's box centroid is good to ~2 px on
#: the same intrinsics: ``2 / 674.4 = 3.0e-3 rad``. Widened to 1.0e-2 rad to
#: cover box jitter on a partially occluded object, which the pixel model does
#: not capture. Documented as widened, not derived.
D455_BEARING_SIGMA_RAD = 1.0e-2


def _finite(value: object, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a finite number")  # noqa: TRY004
    out = float(value)
    if not math.isfinite(out):
        raise ValueError(f"{name} must be a finite number")
    return out


def _unit(value: object, name: str) -> float:
    out = _finite(value, name)
    if not 0.0 <= out <= 1.0:
        raise ValueError(f"{name} must be in [0, 1]")
    return out


def _nonneg(value: object, name: str) -> float:
    out = _finite(value, name)
    if out < 0.0:
        raise ValueError(f"{name} must be non-negative")
    return out


@dataclass(frozen=True)
class ConfidenceModel:
    """Overlapping true-positive / false-positive score distributions.

    The literal ``0.98`` this replaces was not a measurement; it was a
    placeholder that made every candidate maximally trusted and made any
    confidence threshold vacuous. A real detector's TP and FP score
    distributions *overlap* — that overlap is the whole reason a threshold has
    to be calibrated rather than chosen.

    Scores are drawn from truncated normals on ``[0, 1]``. ``temperature``
    scales both standard deviations: ``1.0`` is the calibrated shipping shape,
    ``> 1`` widens the overlap (a worse-calibrated detector), ``0`` collapses
    to the two means.
    """

    tp_mean: float = 0.75
    tp_std: float = 0.12
    fp_mean: float = 0.55
    fp_std: float = 0.15
    temperature: float = 1.0

    def __post_init__(self) -> None:
        _unit(self.tp_mean, "tp_mean")
        _unit(self.fp_mean, "fp_mean")
        _nonneg(self.tp_std, "tp_std")
        _nonneg(self.fp_std, "fp_std")
        _nonneg(self.temperature, "temperature")

    def sample_true_positive(self, rng: random.Random) -> float:
        return self._draw(rng, self.tp_mean, self.tp_std)

    def sample_false_positive(self, rng: random.Random) -> float:
        return self._draw(rng, self.fp_mean, self.fp_std)

    def _draw(self, rng: random.Random, mean: float, std: float) -> float:
        spread = std * self.temperature
        if spread <= 0.0:
            return float(mean)
        return max(0.0, min(1.0, rng.gauss(mean, spread)))


@dataclass(frozen=True)
class NoiseTier:
    """One rung of the noise ladder.

    ``passthrough`` is the T0 contract and is checked, not assumed: a tier that
    claims pass-through while carrying non-zero noise is rejected at
    construction, so nobody can silently perturb the frozen tier.
    """

    name: str
    passthrough: bool = True
    range_cutoff_m: float = math.inf
    depth_sigma_coeff_per_m: float = 0.0
    bearing_sigma_rad: float = 0.0
    #: Miss probability at (and below) ``dropout_near_range_m``.
    dropout_near: float = 0.0
    #: Miss probability at (and beyond) ``dropout_far_range_m``.
    dropout_far: float = 0.0
    dropout_near_range_m: float = 1.5
    dropout_far_range_m: float = 8.0
    #: Expected spurious detections per 100 frames (datasheet band 0.5-2.0).
    false_positives_per_100_frames: float = 0.0
    #: Radius of the annulus a false positive is placed in, around the robot.
    false_positive_range_m: tuple[float, float] = (1.5, 6.0)
    #: Mean lifetime of a spurious detection, in frames. **Not a datasheet
    #: number** — no detector datasheet quotes one — but a false positive that
    #: teleports every frame is a strawman: the tracker's M-of-N kills it for
    #: free and the confidence threshold is never asked anything. Real
    #: false positives persist because whatever caused them (a texture, a
    #: shadow, a mannequin) persists. Modelling choice, stated as such;
    #: 1 frame reproduces the memoryless behaviour exactly.
    false_positive_persistence_frames: float = 1.0
    confusion: Mapping[str, Mapping[str, float]] = field(default_factory=dict)
    confidence: ConfidenceModel = field(default_factory=ConfidenceModel)
    vocabulary: frozenset[str] = DEFAULT_SIM_VOCABULARY
    #: IPDA seam (documented, not built). When a real existence-probability
    #: filter lands it writes here and the tracker consumes it as a weight.
    existence_probability_source: str = "none"

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not self.name:
            raise ValueError("tier name must be non-empty")
        _nonneg(self.depth_sigma_coeff_per_m, "depth_sigma_coeff_per_m")
        _nonneg(self.bearing_sigma_rad, "bearing_sigma_rad")
        _unit(self.dropout_near, "dropout_near")
        _unit(self.dropout_far, "dropout_far")
        _nonneg(self.dropout_near_range_m, "dropout_near_range_m")
        _nonneg(self.false_positives_per_100_frames, "false_positives_per_100_frames")
        if self.dropout_far_range_m <= self.dropout_near_range_m:
            raise ValueError("dropout_far_range_m must exceed dropout_near_range_m")
        lo, hi = self.false_positive_range_m
        if not 0.0 <= float(lo) < float(hi):
            raise ValueError("false_positive_range_m must satisfy 0 <= lo < hi")
        if self.passthrough and (
            self.depth_sigma_coeff_per_m
            or self.bearing_sigma_rad
            or self.dropout_near
            or self.dropout_far
            or self.false_positives_per_100_frames
            or self.false_positive_persistence_frames > 1.0
            or self.confusion
            or math.isfinite(self.range_cutoff_m)
        ):
            raise ValueError(
                "a pass-through tier must carry no noise: T0 is an equality "
                "commitment, not a low-noise setting"
            )

    def dropout_probability(self, range_m: float) -> float:
        """Range-scaled miss probability (linear between the two anchors)."""

        distance = max(0.0, float(range_m))
        if distance <= self.dropout_near_range_m:
            return self.dropout_near
        if distance >= self.dropout_far_range_m:
            return self.dropout_far
        span = self.dropout_far_range_m - self.dropout_near_range_m
        t = (distance - self.dropout_near_range_m) / span
        return self.dropout_near + t * (self.dropout_far - self.dropout_near)

    def range_sigma_m(self, range_m: float) -> float:
        """D455 quadratic range sigma."""

        distance = max(0.0, float(range_m))
        return self.depth_sigma_coeff_per_m * distance * distance


def tier_t0() -> NoiseTier:
    """The shipping tier. Nothing changes for existing runs."""

    return NoiseTier(name=TIER_T0, passthrough=True)


def tier_t1(*, temperature: float = 1.0) -> NoiseTier:
    """Calibrated tier — every constant traceable, none tuned against a result."""

    return NoiseTier(
        name=TIER_T1,
        passthrough=False,
        range_cutoff_m=8.0,
        depth_sigma_coeff_per_m=D455_DEPTH_SIGMA_COEFF_PER_M,
        bearing_sigma_rad=D455_BEARING_SIGMA_RAD,
        dropout_near=0.1,
        dropout_far=0.3,
        false_positives_per_100_frames=1.0,
        # Modelling choice, not a datasheet value: a phantom lives ~4 frames,
        # long enough for the tracker's 3-of-5 confirmation to be a real test
        # rather than a formality. See NoiseTier.
        false_positive_persistence_frames=4.0,
        confusion=default_person_confusion(),
        confidence=ConfidenceModel(temperature=float(temperature)),
    )


class PerceptionChain:
    """Sim semantic candidates → detector-shaped candidates.

    One instance per run (it owns an RNG and a false-positive counter).
    ``reset()`` restores the seeded stream so paired episodes are comparable.
    """

    def __init__(self, tier: NoiseTier | None = None, *, seed: int = 0) -> None:
        self._tier = tier if tier is not None else tier_t0()
        if isinstance(seed, bool) or not isinstance(seed, int):
            raise ValueError("seed must be an integer")  # noqa: TRY004
        self._seed = int(seed)
        self._rng = random.Random(self._seed)
        self._frame = 0
        self._false_positive_serial = 0
        self._active_false_positives: list[dict[str, Any]] = []

    @classmethod
    def from_tier(cls, tier_name: str, *, seed: int = 0, **kwargs: Any) -> PerceptionChain:
        name = str(tier_name).strip().upper()
        if name == TIER_T0:
            return cls(tier_t0(), seed=seed)
        if name == TIER_T1:
            return cls(tier_t1(**kwargs), seed=seed)
        raise ValueError(
            f"unknown perception tier: {tier_name!r}; registered tiers are "
            f"{list(REGISTERED_TIERS)} (a 'T-cam' label in an eval report is a "
            "report id, not a tier — see REGISTERED_TIERS)"
        )

    @property
    def tier(self) -> NoiseTier:
        return self._tier

    @property
    def frame_index(self) -> int:
        return self._frame

    def reset(self) -> None:
        self._rng = random.Random(self._seed)
        self._frame = 0
        self._false_positive_serial = 0
        self._active_false_positives = []

    def process(
        self,
        candidates: Sequence[Mapping[str, Any]],
        *,
        robot_x: float,
        robot_y: float,
        robot_yaw_rad: float,
    ) -> list[dict[str, Any]]:
        """Run the chain over one frame of oracle candidates.

        **The T0 equality argument, exactly.** At a pass-through tier the
        method still lifts every row to :class:`GroundTruthDetection` (so the
        contract validation is genuinely on the mission path, and a row the
        detector contract would reject is rejected here too), but:

        1. no random number is drawn — the RNG stream is untouched, so nothing
           downstream that shares a seeded stream can shift;
        2. the emitted bearing / range / score / class are bit-identical to the
           lifted ones, which makes the reconstruction step's exactness
           short-circuit fire for every row;
        3. that short-circuit returns **the caller's own ``dict`` object**, not
           a rebuilt copy — so world coordinates, polygons and metadata cannot
           move by a ULP through a ``hypot``/``atan2``/``cos``/``sin``
           round-trip.

        The short-circuit is the same discipline stratum 1 used for
        ``p_inside_polygon`` at zero covariance: the exact branch is what makes
        the seam safe to wire at all.
        """

        self._frame += 1
        rx = _finite(robot_x, "robot_x")
        ry = _finite(robot_y, "robot_y")
        yaw = _finite(robot_yaw_rad, "robot_yaw_rad")
        tier = self._tier

        out: list[dict[str, Any]] = []
        for index, raw in enumerate(candidates):
            if not isinstance(raw, Mapping):
                continue
            lifted = self._lift(raw, index, robot_x=rx, robot_y=ry, robot_yaw_rad=yaw)
            if lifted is None:
                continue
            gt, cx, cy = lifted
            if tier.passthrough:
                # Identity stage. No RNG, no drop, no confusion: emit and
                # reconstruct exactly, which returns ``raw`` itself.
                out.append(dict(raw) if not isinstance(raw, dict) else raw)
                continue
            emitted = self._emit_noisy(gt)
            if emitted is None:
                continue
            klass, bearing, range_m, score = emitted
            out.append(
                self._reconstruct(
                    raw,
                    gt,
                    class_id=klass,
                    bearing_rad=bearing,
                    range_m=range_m,
                    score=score,
                    robot_x=rx,
                    robot_y=ry,
                    robot_yaw_rad=yaw,
                    original_xy=(cx, cy),
                )
            )

        if not tier.passthrough:
            out.extend(self._sample_false_positives(robot_x=rx, robot_y=ry))
        return out

    # ---- stages -----------------------------------------------------------

    def _lift(
        self,
        raw: Mapping[str, Any],
        index: int,
        *,
        robot_x: float,
        robot_y: float,
        robot_yaw_rad: float,
    ) -> tuple[GroundTruthDetection, float, float] | None:
        """Oracle candidate dict → ``GroundTruthDetection`` (+ its world xy)."""

        center = raw.get("position") or raw.get("centroid")
        polygon = raw.get("polygon") or ()
        if center is None and polygon:
            try:
                center = (
                    sum(float(p[0]) for p in polygon) / len(polygon),
                    sum(float(p[1]) for p in polygon) / len(polygon),
                )
            except (IndexError, TypeError, ValueError):
                return None
        if not isinstance(center, (list, tuple)) or len(center) < 2:
            return None
        try:
            cx = float(center[0])
            cy = float(center[1])
        except (TypeError, ValueError):
            return None
        if not (math.isfinite(cx) and math.isfinite(cy)):
            return None
        label = str(raw.get("label") or "")
        if not label:
            return None
        bearing, range_m = bearing_range_from_pose(
            robot_x=robot_x,
            robot_y=robot_y,
            robot_yaw_rad=robot_yaw_rad,
            target_x=cx,
            target_y=cy,
        )
        try:
            confidence = float(raw.get("confidence", 0.0))
        except (TypeError, ValueError):
            return None
        confidence = max(0.0, min(1.0, confidence)) if math.isfinite(confidence) else 0.0
        try:
            gt = GroundTruthDetection(
                class_id=label,
                embedding=label_embedding(label),
                bearing_rad=bearing,
                range_m=range_m,
                track_id=str(raw.get("id") or f"candidate-{index}"),
                score=confidence,
            )
        except (TypeError, ValueError):
            return None
        return gt, cx, cy

    def _emit_noisy(
        self, gt: GroundTruthDetection
    ) -> tuple[str, float, float, float] | None:
        tier = self._tier
        rng = self._rng
        if gt.range_m > tier.range_cutoff_m:
            return None
        if rng.random() < tier.dropout_probability(gt.range_m):
            return None
        klass = self._confuse(gt.class_id, rng)
        sigma_r = tier.range_sigma_m(gt.range_m)
        range_m = gt.range_m + (rng.gauss(0.0, sigma_r) if sigma_r > 0.0 else 0.0)
        range_m = max(0.0, range_m)
        if range_m > tier.range_cutoff_m:
            return None
        bearing = gt.bearing_rad + (
            rng.gauss(0.0, tier.bearing_sigma_rad) if tier.bearing_sigma_rad > 0.0 else 0.0
        )
        bearing = _wrap(bearing)
        # A confused class is a false positive *of that class*, so it draws
        # from the FP distribution — this is what makes the two distributions
        # overlap in practice and not only in principle.
        score = (
            tier.confidence.sample_true_positive(rng)
            if klass == gt.class_id
            else tier.confidence.sample_false_positive(rng)
        )
        return klass, bearing, range_m, score

    def _confuse(self, true_class: str, rng: random.Random) -> str:
        row = self._tier.confusion.get(true_class)
        if not row:
            return true_class
        draw = rng.random()
        cumulative = 0.0
        last = true_class
        for predicted, probability in row.items():
            cumulative += float(probability)
            last = predicted
            if draw <= cumulative:
                return predicted
        return last

    def _reconstruct(
        self,
        raw: Mapping[str, Any],
        gt: GroundTruthDetection,
        *,
        class_id: str,
        bearing_rad: float,
        range_m: float,
        score: float,
        robot_x: float,
        robot_y: float,
        robot_yaw_rad: float,
        original_xy: tuple[float, float],
    ) -> dict[str, Any]:
        """Detector output → candidate dict, world-projected.

        Exactness short-circuit: when the stage returned the class, bearing and
        range unchanged, the original row's own geometry is reused rather than
        re-derived. That is the only reason a T0 diff can be empty.
        """

        unchanged = (
            class_id == gt.class_id
            and bearing_rad == gt.bearing_rad
            and range_m == gt.range_m
        )
        if unchanged and score == gt.score:
            return dict(raw) if not isinstance(raw, dict) else raw

        item = dict(raw)
        item["label"] = class_id
        item["confidence"] = float(score)
        metadata = dict(item.get("metadata") or {})
        metadata["perception_tier"] = self._tier.name
        metadata["detector_class"] = class_id
        metadata["true_class"] = gt.class_id
        item["metadata"] = metadata
        item["source"] = "detection_adapter"
        if unchanged:
            return item
        world_angle = robot_yaw_rad + bearing_rad
        nx = robot_x + range_m * math.cos(world_angle)
        ny = robot_y + range_m * math.sin(world_angle)
        dx = nx - original_xy[0]
        dy = ny - original_xy[1]
        if item.get("polygon"):
            try:
                item["polygon"] = [
                    [float(p[0]) + dx, float(p[1]) + dy] for p in item["polygon"]
                ]
            except (IndexError, TypeError, ValueError):
                pass
        position = item.get("position")
        if isinstance(position, (list, tuple)) and len(position) >= 2:
            z = float(position[2]) if len(position) > 2 else 0.0
            item["position"] = [nx, ny, z]
        elif position is not None or not item.get("polygon"):
            item["position"] = [nx, ny, 0.0]
        return item

    def _sample_false_positives(
        self, *, robot_x: float, robot_y: float
    ) -> list[dict[str, Any]]:
        tier = self._tier
        rate = tier.false_positives_per_100_frames / 100.0
        if rate <= 0.0:
            return []

        # Bernoulli per frame at the datasheet rate. At 0.5-2 per 100 frames the
        # Poisson correction is below the reporting resolution, so the simpler
        # draw is the honest one.
        while self._rng.random() < rate and len(self._active_false_positives) < 4:
            self._false_positive_serial += 1
            lo, hi = tier.false_positive_range_m
            distance = self._rng.uniform(float(lo), float(hi))
            angle = self._rng.uniform(-math.pi, math.pi)
            label = self._rng.choice(sorted(tier.vocabulary - {"unknown"}))
            lifetime = self._draw_lifetime()
            self._active_false_positives.append(
                {
                    "id": f"fp-{tier.name}-{self._false_positive_serial}",
                    "label": label,
                    "x": robot_x + distance * math.cos(angle),
                    "y": robot_y + distance * math.sin(angle),
                    "remaining": lifetime,
                }
            )

        out: list[dict[str, Any]] = []
        survivors: list[dict[str, Any]] = []
        for phantom in self._active_false_positives:
            out.append(
                {
                    "id": str(phantom["id"]),
                    "label": str(phantom["label"]),
                    "position": [float(phantom["x"]), float(phantom["y"]), 0.0],
                    # The score is re-drawn every frame: a persistent phantom
                    # has a persistent *cause*, not a frozen score.
                    "confidence": tier.confidence.sample_false_positive(self._rng),
                    "kind": "object",
                    "source": "detection_adapter",
                    "reachable": True,
                    "metadata": {
                        "perception_tier": tier.name,
                        "false_positive": True,
                    },
                }
            )
            phantom["remaining"] = int(phantom["remaining"]) - 1
            if int(phantom["remaining"]) > 0:
                survivors.append(phantom)
        self._active_false_positives = survivors
        return out

    def _draw_lifetime(self) -> int:
        """Geometric lifetime with the configured mean, floored at one frame."""

        mean = float(self._tier.false_positive_persistence_frames)
        if mean <= 1.0:
            return 1
        p = 1.0 / mean
        draw = self._rng.random()
        # Inverse-CDF of the geometric distribution on {1, 2, ...}.
        return max(1, min(64, math.ceil(math.log(max(draw, 1e-12)) / math.log(1.0 - p))))


def _wrap(bearing: float) -> float:
    wrapped = (bearing + math.pi) % (2.0 * math.pi) - math.pi
    return max(-math.pi, min(math.pi, wrapped))


# --- process-default injection seam ---------------------------------------
#
# Mirrors ``parcel_robot.pose.use_pose_provider``: eval harnesses and tests
# install a chain for the process instead of every call site growing an
# argument. The default is a T0 chain, which is why installing nothing and
# installing T0 are the same run.

_ACTIVE_CHAIN: PerceptionChain | None = None


def active_perception_chain() -> PerceptionChain:
    """The chain every ingress consults. T0 until something installs otherwise."""

    global _ACTIVE_CHAIN
    if _ACTIVE_CHAIN is None:
        _ACTIVE_CHAIN = PerceptionChain(tier_t0())
    return _ACTIVE_CHAIN


def use_perception_chain(chain: PerceptionChain | None) -> None:
    """Install (or clear, with ``None``) the process-default chain."""

    global _ACTIVE_CHAIN
    if chain is not None and not isinstance(chain, PerceptionChain):
        raise TypeError("chain must be a PerceptionChain or None")
    _ACTIVE_CHAIN = chain
