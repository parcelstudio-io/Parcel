"""Whole-map relocalization: the best hypothesis, its rival, and the gap.

This is fix 4 from ``research/20260824/nav-core/RESULTS.md`` moved into the
product.  ``ScanMatchLocalizer._relocalize`` scores keyframes, keeps the best
and never reports a runner-up, so CLAUDE_RESPONSE addendum A4's re-arm path
(a) — "a relocalization match whose second-best candidate is worse by a
pre-registered margin **across the whole map**, not a local residual gate" —
was not computable anywhere in the tree.  It was computable in NAV-CORE's
harness (``research/20260824/nav-core/relocalize.py``'s ``GlobalMatcher``),
which is the reference this module productizes; the numbers that shape belongs
to are in RESULTS §"Refuter 4b": margins of **2.2–30.7 in a normal layout
against 0.002–0.03 in the aliased one**, threshold 0.25.

**Two stages, because one is not enough.**  A coarse grid at
:data:`GRID_M` puts the true pose up to 0.28 m from the nearest hypothesis,
and in a room-scale venue 0.2 m of position error costs about 0.5 m of scan
RMS — the same order as an aliased twin's residual, which would make the
margin meaningless.  So the coarse pass only picks WHERE to look: the winning
cell and the best cell at least :data:`HYPOTHESIS_SEPARATION_M` away are each
re-scored on a :data:`REFINE_M` sub-grid, and the margin is computed from the
refined residuals.  Refinement can overturn the coarse ordering (it does,
whenever the true pose fell between coarse cells), so the two are re-ordered
AFTER refining or the margin is signed by an artefact of the grid.

**The yaw sweep is exact, not sampled.**  A uniform full-circle range ring
taken at the same position with a different heading is a circular shift of the
same ranges, so one template per position covers every heading.  That is a
*precondition*, not a convenience: :meth:`WholeMapMatcher.match` refuses a ring
whose length disagrees with the templates, because a non-uniform or partial
ring makes the shift meaningless.

**What this module is not.**  It is not a place-recognition system and it does
not learn descriptors.  It answers one question — "is the pose this scan
implies globally alone?" — over a hypothesis set some *other* object supplies
through :class:`RangeTemplateSource`.  In sim that source is the room; on a
robot it is whatever can render an expected ring from the stored map.  Nothing
here names a body, a sensor vendor or a venue.
"""

from __future__ import annotations

import math
from typing import Any, Protocol, runtime_checkable

import numpy as np

from parcel_robot.localization.contract import RelocalizationMatch, wrap_angle

__all__ = [
    "GLOBAL_MATCH_MARGIN_MIN",
    "GRID_M",
    "HYPOTHESIS_SEPARATION_M",
    "OPERATOR_AGREEMENT_RMS_M",
    "REFINE_M",
    "RangeTemplateSource",
    "WholeMapMatcher",
    "agreement_rms_m",
]

#: Hypothesis grid over the mapped area, metres.  0.4 m is four GICP voxels at
#: ``ScanMatchConfig.downsample_m``: fine enough that the true pose is always
#: within half a cell of a hypothesis, coarse enough that a room is a couple of
#: hundred templates.  Pre-registered by NAV-CORE's harness.
GRID_M = 0.40

#: Sub-grid the two finalists are re-scored on, metres.
REFINE_M = 0.10

#: A rival nearer than this is the same hypothesis, not a competitor.
HYPOTHESIS_SEPARATION_M = 1.00

#: PRE-REGISTERED (NAV-CORE ``relocalize.MARGIN_MIN``).  Re-arm needs the
#: runner-up to be at least this much worse, as a fraction of the winner's
#: residual.  Measured separation on that study: normal layouts 2.2–30.7,
#: the C2-aliased layout 0.002–0.03.
GLOBAL_MATCH_MARGIN_MIN = 0.25

#: PRE-REGISTERED.  An operator's stated pose is accepted only if the observed
#: ring agrees with it this well (RMS over matched rays, metres).
OPERATOR_AGREEMENT_RMS_M = 0.35


@runtime_checkable
class RangeTemplateSource(Protocol):
    """Whatever can say "is this floor" and "what would a ring look like here".

    ``template`` returns the expected uniform full-circle ring at ``(x, y)``
    with heading ZERO.  Every heading is then reachable by circular shift, so a
    source that cannot honour the zero-heading convention must not be used
    here — the sweep would be comparing rings taken about different axes.
    """

    def free(self, x: float, y: float) -> bool: ...

    def template(self, x: float, y: float) -> Any: ...


def _ranges(raw: Any, name: str) -> np.ndarray:
    values = np.asarray(raw, dtype=np.float64).reshape(-1)
    if values.size == 0:
        raise ValueError(f"{name} must carry at least one ray")
    return values


def agreement_rms_m(observed: Any, expected: Any) -> float:
    """RMS disagreement between two rings over the rays both of them returned.

    ``inf`` when they share no finite ray — an absence of evidence, which the
    operator transaction must read as "not verified" rather than as agreement.
    """

    left = _ranges(observed, "observed ranges")
    right = _ranges(expected, "expected ranges")
    if left.size != right.size:
        raise ValueError("ring lengths differ; the yaw sweep would be meaningless")
    mask = np.isfinite(left) & np.isfinite(right)
    if not mask.any():
        return math.inf
    delta = left[mask] - right[mask]
    return float(math.sqrt(float((delta * delta).mean())))


class WholeMapMatcher:
    """Score one observed ring against every pose in the mapped area.

    One instance per map: the coarse template bank is built once, lazily, and
    reused.  Building it eagerly in ``__init__`` would make constructing the
    object expensive in a code path that may never ask a question.
    """

    name = "whole_map"

    def __init__(
        self,
        source: RangeTemplateSource,
        *,
        bounds: tuple[float, float, float, float],
        grid_m: float = GRID_M,
        refine_m: float = REFINE_M,
        separation_m: float = HYPOTHESIS_SEPARATION_M,
    ) -> None:
        if not hasattr(source, "template") or not hasattr(source, "free"):
            raise TypeError("source must implement RangeTemplateSource")
        min_x, min_y, max_x, max_y = (float(value) for value in bounds)
        if not (max_x > min_x and max_y > min_y):
            raise ValueError("bounds must be (min_x, min_y, max_x, max_y) and non-empty")
        for name, value in (("grid_m", grid_m), ("refine_m", refine_m)):
            if float(value) <= 0.0:
                raise ValueError(f"{name} must be positive")
        self.source = source
        self.bounds = (min_x, min_y, max_x, max_y)
        self.grid_m = float(grid_m)
        self.refine_m = float(refine_m)
        self.separation_m = float(separation_m)
        self._positions: list[tuple[float, float]] = []
        self._templates: np.ndarray | None = None

    # -- the bank ----------------------------------------------------------

    def _build(self) -> None:
        if self._templates is not None:
            return
        min_x, min_y, max_x, max_y = self.bounds
        positions: list[tuple[float, float]] = []
        rows: list[np.ndarray] = []
        steps_x = round((max_x - min_x) / self.grid_m)
        steps_y = round((max_y - min_y) / self.grid_m)
        for i in range(steps_x + 1):
            for j in range(steps_y + 1):
                x = min_x + i * self.grid_m
                y = min_y + j * self.grid_m
                if not self.source.free(x, y):
                    continue
                positions.append((x, y))
                rows.append(_ranges(self.source.template(x, y), "template"))
        self._positions = positions
        self._templates = np.stack(rows) if rows else np.zeros((0, 1))

    @property
    def hypotheses(self) -> int:
        self._build()
        return len(self._positions)

    # -- the question ------------------------------------------------------

    def match(self, observed: Any) -> RelocalizationMatch:
        """Best and runner-up for one observed ring, with the margin between."""

        self._build()
        assert self._templates is not None
        query = _ranges(observed, "observed ranges")
        if self._templates.shape[0] == 0 or not np.isfinite(query).any():
            return RelocalizationMatch(
                pose=(0.0, 0.0, 0.0),
                residual_m=math.inf,
                runner_up=(0.0, 0.0, 0.0),
                runner_up_residual_m=math.inf,
                separation_m=self.separation_m,
                hypotheses=max(1, self._templates.shape[0]),
                source=self.name,
            )
        if self._templates.shape[1] != query.size:
            raise ValueError(
                "observed ring has "
                f"{query.size} rays but the templates have "
                f"{self._templates.shape[1]}; the circular-shift yaw sweep "
                "requires the same uniform full-circle ring"
            )
        coarse, _shift = self._sweep(self._templates, query)
        order = np.argsort(coarse)
        top = int(order[0])
        rival: int | None = None
        for index in order[1:]:
            far = math.dist(self._positions[int(index)], self._positions[top])
            if far >= self.separation_m:
                rival = int(index)
                break
        best_pose, best_rms = self._refine(self._positions[top], query)
        if rival is None:
            return RelocalizationMatch(
                pose=best_pose,
                residual_m=best_rms,
                runner_up=best_pose,
                runner_up_residual_m=math.inf,
                separation_m=self.separation_m,
                hypotheses=len(self._positions),
                source=self.name,
            )
        rival_pose, rival_rms = self._refine(self._positions[rival], query)
        if rival_rms < best_rms:
            best_pose, best_rms, rival_pose, rival_rms = (
                rival_pose,
                rival_rms,
                best_pose,
                best_rms,
            )
        return RelocalizationMatch(
            pose=best_pose,
            residual_m=best_rms,
            runner_up=rival_pose,
            runner_up_residual_m=rival_rms,
            separation_m=math.dist(best_pose[:2], rival_pose[:2]),
            hypotheses=len(self._positions),
            source=self.name,
        )

    def expected_ring(self, pose: tuple[float, float, float]) -> np.ndarray:
        """The ring a body at ``pose`` should see, by shift from the template.

        Same convention as :meth:`_sweep`: the zero-heading template equals the
        observed ring rolled forward by the heading's share of the ring, so the
        expected ring at a heading is the template rolled back by it.
        """

        self._build()
        template = _ranges(self.source.template(pose[0], pose[1]), "template")
        shift = self._shift_for(wrap_angle(float(pose[2])), template.size)
        return np.roll(template, -shift)

    def agreement_rms_m(self, observed: Any, pose: tuple[float, float, float]) -> float:
        """How well an observed ring agrees with a STATED pose (A4 path (b))."""

        return agreement_rms_m(observed, self.expected_ring(pose))

    # -- machinery ---------------------------------------------------------

    @staticmethod
    def _shift_for(yaw: float, rays: int) -> int:
        return round(yaw / (2.0 * math.pi) * rays) % rays

    @staticmethod
    def _sweep(templates: np.ndarray, query: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """Per-template best RMS over every heading, and the shift that won."""

        rays = templates.shape[1]
        best_rms = np.full(templates.shape[0], math.inf)
        best_shift = np.zeros(templates.shape[0], dtype=int)
        finite_t = np.isfinite(templates)
        # A no-return ray is ``inf``, and ``inf - inf`` is NaN, so the
        # non-finite entries are zeroed BEFORE the subtraction rather than
        # masked after it: ``np.where`` evaluates both branches.
        safe_t = np.where(finite_t, templates, 0.0)
        for shift in range(rays):
            rotated = np.roll(query, shift)
            finite_q = np.isfinite(rotated)
            mask = finite_q & finite_t
            delta = np.where(mask, safe_t - np.where(finite_q, rotated, 0.0), 0.0)
            counts = mask.sum(axis=1)
            rms = np.where(
                counts > 0,
                np.sqrt((delta * delta).sum(axis=1) / np.maximum(counts, 1)),
                math.inf,
            )
            improved = rms < best_rms
            best_rms = np.where(improved, rms, best_rms)
            best_shift = np.where(improved, shift, best_shift)
        return best_rms, best_shift

    def _refine(
        self, around: tuple[float, float], query: np.ndarray
    ) -> tuple[tuple[float, float, float], float]:
        """Re-score one neighbourhood on the fine sub-grid, full heading sweep."""

        positions: list[tuple[float, float]] = []
        rows: list[np.ndarray] = []
        for i in range(-2, 3):
            for j in range(-2, 3):
                x = around[0] + i * self.refine_m
                y = around[1] + j * self.refine_m
                if not self.source.free(x, y):
                    continue
                positions.append((x, y))
                rows.append(_ranges(self.source.template(x, y), "template"))
        if not rows:
            return (around[0], around[1], 0.0), math.inf
        rms, shift = self._sweep(np.stack(rows), query)
        index = int(np.argmin(rms))
        rays = query.size
        yaw = 2.0 * math.pi * int(shift[index]) / rays
        return (
            positions[index][0],
            positions[index][1],
            wrap_angle(yaw),
        ), float(rms[index])
