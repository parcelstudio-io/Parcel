"""Value-directed ScanBehavior over :class:`SemanticValueMap2D` (vsearch C2).

``full_turn_scan_spec`` remains the VLFM-style initialization on first UNSEEN.
After that, the next dwell yaw is chosen by GP-UCB expected value gain
(``mu + sqrt(beta) * sigma``; look-again-vs-commit). Scan stops are planned as
SE2 viewpoints for ProposerBus / base-lease arbitration.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass, field
from enum import Enum

from parcel_robot.instructnav.arbiter import SE2Goal
from parcel_robot.instructnav.scan import ScanPlanSpec, ScanStop, full_turn_scan_spec, scan_stops
from parcel_robot.navigation.value_map import CellRegion, SemanticValueMap2D, ViewCone

SCAN_PROPOSER_SOURCE = "scan_behavior"


class ScanLookDecision(str, Enum):
    """GP-UCB look-again-vs-commit outcome."""

    LOOK = "look"
    COMMIT = "commit"


@dataclass(frozen=True)
class LookCandidate:
    """One discrete camera yaw to score under GP-UCB."""

    yaw_rad: float
    mu: float
    sigma: float
    ucb: float
    unknown_fraction: float


@dataclass(frozen=True)
class ValueDirectedLookChoice:
    decision: ScanLookDecision
    yaw_rad: float | None
    ucb: float
    mu: float
    sigma: float
    detail: str


@dataclass
class ValueDirectedScanSession:
    """Lifecycle: full-turn init → GP-UCB looks → commit handoff.

    Flag-off callers keep using :class:`ScanBehaviorController` alone; this
    session is opt-in (``value_directed_search=True``).
    """

    value_map: SemanticValueMap2D
    fov_rad: float = math.radians(70.0)
    max_range_m: float = 8.0
    min_range_m: float = 0.4
    beta: float = 2.0
    n_heading_candidates: int = 16
    commit_margin: float = 0.05
    max_value_looks: int = 6
    init_spec: ScanPlanSpec = field(default_factory=full_turn_scan_spec)
    _init_done: bool = False
    _value_looks: int = 0
    _visited_yaws: list[float] = field(default_factory=list)
    _suspended: bool = False

    def reset(self) -> None:
        self._init_done = False
        self._value_looks = 0
        self._visited_yaws.clear()
        self._suspended = False

    @property
    def init_done(self) -> bool:
        return self._init_done

    @property
    def suspended(self) -> bool:
        return self._suspended

    def suspend(self) -> None:
        """Summons / attention path: suspend in-flight scan (do not cancel)."""

        self._suspended = True

    def resume(self) -> None:
        self._suspended = False

    def mark_init_complete(self) -> None:
        self._init_done = True

    def init_plan_spec(self) -> ScanPlanSpec:
        """First-UNSEEN VLFM initialization — the only use of full_turn_scan_spec."""

        return self.init_spec

    def init_stops(self, start_yaw_rad: float) -> tuple[ScanStop, ...]:
        return scan_stops(start_yaw_rad, self.init_spec)

    def choose_next_look(
        self,
        *,
        origin_world_xy: tuple[float, float],
        current_yaw_rad: float,
        default_prior: float = 0.0,
    ) -> ValueDirectedLookChoice:
        """GP-UCB look-again-vs-commit over discrete heading candidates."""

        if self._suspended:
            return ValueDirectedLookChoice(
                decision=ScanLookDecision.COMMIT,
                yaw_rad=None,
                ucb=0.0,
                mu=0.0,
                sigma=0.0,
                detail="suspended",
            )
        if not self._init_done:
            raise RuntimeError("choose_next_look requires init (full_turn) first")
        # VS-5 empty-map contract (FOLLOWUP_DESIGNS.md §2.2(d)): with no
        # query-relevant evidence in the map there is nothing for GP-UCB to be
        # directed BY — every heading scores the same prior, so an "informed"
        # extra look is an uninformed one that costs dwell steps the baseline
        # full turn does not spend. Return COMMIT, which is exactly the baseline
        # behaviour: the flag-on scan is then the flag-off scan.
        if _evidence_count_of(self.value_map) == 0:
            return ValueDirectedLookChoice(
                decision=ScanLookDecision.COMMIT,
                yaw_rad=None,
                ucb=0.0,
                mu=0.0,
                sigma=0.0,
                detail="empty_map_no_evidence",
            )
        if self._value_looks >= self.max_value_looks:
            return ValueDirectedLookChoice(
                decision=ScanLookDecision.COMMIT,
                yaw_rad=None,
                ucb=0.0,
                mu=0.0,
                sigma=0.0,
                detail="value_look_budget_exhausted",
            )

        scored = score_heading_candidates(
            self.value_map,
            origin_world_xy=origin_world_xy,
            fov_rad=self.fov_rad,
            max_range_m=self.max_range_m,
            min_range_m=self.min_range_m,
            beta=self.beta,
            n_candidates=self.n_heading_candidates,
            default_prior=default_prior,
            avoid_yaws=self._visited_yaws + [current_yaw_rad],
        )
        if not scored:
            return ValueDirectedLookChoice(
                decision=ScanLookDecision.COMMIT,
                yaw_rad=None,
                ucb=0.0,
                mu=0.0,
                sigma=0.0,
                detail="no_heading_candidates",
            )
        best = max(scored, key=lambda c: (c.ucb, -abs(_wrap_pi(c.yaw_rad - current_yaw_rad))))
        # Look-again-vs-commit: if the optimistic gain is within commit_margin of
        # the best already-observed mean, stop looking and hand off.
        best_observed_mu = max((c.mu for c in scored if c.unknown_fraction < 0.5), default=0.0)
        if best.ucb <= best_observed_mu + self.commit_margin and best.unknown_fraction < 0.25:
            return ValueDirectedLookChoice(
                decision=ScanLookDecision.COMMIT,
                yaw_rad=None,
                ucb=best.ucb,
                mu=best.mu,
                sigma=best.sigma,
                detail="gp_ucb_commit",
            )
        return ValueDirectedLookChoice(
            decision=ScanLookDecision.LOOK,
            yaw_rad=best.yaw_rad,
            ucb=best.ucb,
            mu=best.mu,
            sigma=best.sigma,
            detail="gp_ucb_look",
        )

    def record_look(self, yaw_rad: float) -> None:
        self._visited_yaws.append(float(yaw_rad))
        self._value_looks += 1

    def se2_viewpoint(
        self,
        *,
        x: float,
        y: float,
        yaw_rad: float,
        now_s: float,
        confidence: float = 0.55,
        plan_step_id: str = "scan_behavior",
        task_id: str = "",
        plan_revision: int = 0,
        priority: int = 5,
    ) -> SE2Goal:
        """Base-lease scan stop: same (x,y), yaw is the look direction."""

        return SE2Goal(
            source=SCAN_PROPOSER_SOURCE,
            pose=(float(x), float(y), float(yaw_rad)),
            confidence=max(0.0, min(1.0, float(confidence))),
            ttl_s=2.5,
            plan_step_id=plan_step_id,
            issued_s=float(now_s),
            priority=int(priority),
            task_id=task_id,
            plan_revision=plan_revision,
        )


def score_heading_candidates(
    value_map: SemanticValueMap2D,
    *,
    origin_world_xy: tuple[float, float],
    fov_rad: float,
    max_range_m: float,
    min_range_m: float = 0.0,
    beta: float = 2.0,
    n_candidates: int = 16,
    default_prior: float = 0.0,
    avoid_yaws: Sequence[float] = (),
    avoid_rad: float = 0.4,
) -> tuple[LookCandidate, ...]:
    """Score evenly spaced headings with GP-UCB over the value map."""

    if n_candidates < 2:
        raise ValueError("n_candidates must be ≥ 2")
    if not math.isfinite(beta) or beta < 0.0:
        raise ValueError("beta must be finite and ≥ 0")
    sqrt_beta = math.sqrt(beta)
    out: list[LookCandidate] = []
    for index in range(n_candidates):
        yaw = -math.pi + (2.0 * math.pi * index) / n_candidates
        if any(abs(_wrap_pi(yaw - avoided)) < avoid_rad for avoided in avoid_yaws):
            continue
        mu, sigma, unknown = _cone_belief(
            value_map,
            origin_world_xy=origin_world_xy,
            heading_rad=yaw,
            fov_rad=fov_rad,
            max_range_m=max_range_m,
            min_range_m=min_range_m,
            default_prior=default_prior,
        )
        out.append(
            LookCandidate(
                yaw_rad=yaw,
                mu=mu,
                sigma=sigma,
                ucb=mu + sqrt_beta * sigma,
                unknown_fraction=unknown,
            )
        )
    return tuple(out)


def paint_look(
    value_map: SemanticValueMap2D,
    *,
    origin_world_xy: tuple[float, float],
    heading_rad: float,
    value: float,
    conf: float = 1.0,
    fov_rad: float = math.radians(70.0),
    max_range_m: float = 8.0,
    min_range_m: float = 0.4,
    is_evidence: bool = False,
) -> int:
    """Convenience write of one camera look into the shared belief map.

    ``is_evidence`` is the third field of VS-3's paint tuple, passed straight
    through to :meth:`SemanticValueMap2D.write`; it defaults to ``False`` so
    every pre-existing caller paints exactly what it painted before.
    """

    return value_map.write(
        ViewCone(
            origin_world_xy=origin_world_xy,
            heading_rad=heading_rad,
            fov_rad=fov_rad,
            max_range_m=max_range_m,
            min_range_m=min_range_m,
        ),
        value,
        conf,
        is_evidence=is_evidence,
    )


def _evidence_count_of(value_map: object) -> int:
    """VS-3's ``evidence_count``, read defensively off any map-like object.

    A test double that predates the surface reports no evidence, which keeps
    the empty-map clause a no-op for it rather than a crash.
    """

    return int(getattr(value_map, "evidence_count", 0) or 0)


def _cone_belief(
    value_map: SemanticValueMap2D,
    *,
    origin_world_xy: tuple[float, float],
    heading_rad: float,
    fov_rad: float,
    max_range_m: float,
    min_range_m: float,
    default_prior: float,
) -> tuple[float, float, float]:
    """Return ``(mu, sigma, unknown_fraction)`` for cells in the look cone.

    ``mu`` is the mean of *observed* cell values (or ``default_prior`` when the
    cone is entirely unknown). Unknown cells raise ``sigma`` only — they must
    not inflate ``mu``, or pure-exploration headings always beat a real cue.
    """

    cells = _cells_in_cone(
        value_map,
        origin_world_xy=origin_world_xy,
        heading_rad=heading_rad,
        fov_rad=fov_rad,
        max_range_m=max_range_m,
        min_range_m=min_range_m,
    )
    if not cells:
        return (float(default_prior), 1.0, 1.0)

    observed: list[float] = []
    confidences: list[float] = []
    unknown = 0
    for cell in cells:
        value, conf = value_map.read(cell)
        if conf <= 0.0:
            unknown += 1
            confidences.append(0.0)
        else:
            observed.append(float(value))
            confidences.append(float(conf))
    n = len(confidences)
    unknown_fraction = unknown / n
    if observed:
        mu = sum(observed) / len(observed)
    else:
        mu = float(default_prior)
    # GP-style epistemic uncertainty: unknown cells dominate sigma; observed
    # cells shrink it by accumulated confidence weight.
    mean_inv_conf = sum(1.0 / (1.0 + c) for c in confidences) / n
    sigma = max(1e-6, math.sqrt(max(unknown_fraction, 1e-6) * mean_inv_conf))
    return (mu, sigma, unknown_fraction)


def _cells_in_cone(
    value_map: SemanticValueMap2D,
    *,
    origin_world_xy: tuple[float, float],
    heading_rad: float,
    fov_rad: float,
    max_range_m: float,
    min_range_m: float,
) -> list[tuple[int, int]]:
    res = value_map.resolution_m
    ox, oy = origin_world_xy
    # Bound the search to a square covering the cone range.
    pad = math.ceil(max_range_m / res) + 1
    origin_cell = (math.floor(ox / res), math.floor(oy / res))
    region = CellRegion(
        min_cell=(origin_cell[0] - pad, origin_cell[1] - pad),
        max_cell_exclusive=(origin_cell[0] + pad + 1, origin_cell[1] + pad + 1),
    )
    half_fov = fov_rad / 2.0
    selected: list[tuple[int, int]] = []
    for cell in region:
        cx = (cell[0] + 0.5) * res
        cy = (cell[1] + 0.5) * res
        dx = cx - ox
        dy = cy - oy
        distance = math.hypot(dx, dy)
        if distance < min_range_m or distance > max_range_m:
            continue
        theta = 0.0 if distance == 0.0 else abs(_wrap_pi(math.atan2(dy, dx) - heading_rad))
        if theta <= half_fov:
            selected.append(cell)
    return selected


def _wrap_pi(yaw: float) -> float:
    return (yaw + math.pi) % (2.0 * math.pi) - math.pi
