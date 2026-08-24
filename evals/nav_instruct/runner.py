"""NAV_INSTRUCT headless episode runner over HeadlessCityWorld.

Drives directive → grounder → planner → control, records the trace fields
N-S1's scorer needs, and attributes failures. Baseline mode intentionally
uses today's frustum-gated grounding (no SemanticMemory / ScanForTarget).

Arrival rules (re-freeze correction (c))
----------------------------------------
The runner ends an episode one 0.1 s control tick after the mission's own
``arrived_verified``, while ``score_episode`` wants the robot inside the goal
and stopped for ``arrival_hold_s = 1.0 s``. Under the v1 rule those two facts
are incompatible and the hold can never accumulate — U31. The v2 default is
``hold-or-trace-end-v1``, the rule ``evals/nav_instruct/rescore.py`` documents
and applied to the persisted v1 traces: arrived iff the frozen hold accumulates
**or** the trace ends inside-and-stopped without being cut off by the step
limit. Both numbers are recorded on every episode
(``score`` under the active rule, ``frozen_rule_success`` under the v1 rule), so
switching the rule can never hide what the old rule would have said.

The rule lives here and **not** in ``instructnav/scoring.py``: the scorer is the
shared K0 authority used by the runtime and by two other harnesses, and a rule
that reasons about *how the recording ended* is a property of this harness, not
of arrival.
"""

from __future__ import annotations

import hashlib
import math
from collections.abc import Mapping
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from evals.nav_instruct.generator import (
    DEFAULT_EPISODE_SET_VERSION,
    EpisodeSpec,
    episode_set_spec,
    generate_episode_matrix,
    generate_minival,
)
from evals.nav_instruct.rescore import (
    DERIVED_RULE_ID,
    derived_arrival,
    promoted_derived_score,
)
from parcel_robot.instructnav.scoring import (
    ARRIVAL_BOUNDARY_EPSILON_M,
    AuthorityCategory,
    EpisodeScore,
    FailureClass,
    score_episode,
    system_arrival_claim,
)
from parcel_robot.models import VelocityCommand
from parcel_robot.navigation.goals import navigation_directive_from_text
from parcel_robot.navigation.pipeline import DirectiveNavigator
from parcel_robot.navigation.reactive_safety import apply_reactive_safety
from parcel_robot.navigation.spatial import parse_follow_intent, parse_spatial_intent
from parcel_robot.pose import (
    Frame,
    PoseHealth,
    PoseProvider,
    provider_from_config,
)
from parcel_robot.simulation.headless_city import (
    DEFAULT_ROBOT_CONFIG,
    HeadlessCityQualityHarness,
    HeadlessCityWorld,
    _nav_observation,
)

RUNNER_VERSION = "nav-instruct-v1.1-k0-arrival"

#: Pipeline flags the harness is allowed to flip for a paired flag-on/flag-off
#: A/B. Deliberately a closed set: the runner is the frozen measurement rig, and
#: an open ``**overrides`` passthrough would let a run silently reconfigure the
#: navigator in a way no persisted row records. All five names are pre-registered
#: card flags (V-D value-directed search, V-E detection lock-on, D15-B
#: person-aware navigation, VS-4 verify-on-approach lock-on, RM-2 route memory)
#: and all five default to False inside ``DirectiveNavigator``, so the flag-OFF
#: arm of the A/B is the same navigator every frozen row was measured with.
ALLOWED_NAVIGATOR_OVERRIDES: frozenset[str] = frozenset(
    {
        "value_directed_search",
        "detection_lock_on",
        "person_aware_nav",
        # Card VS-4 (FOLLOWUP_DESIGNS.md §6, Wave 2) — one name, additive.
        "lock_on_verify_on_approach",
        # Card RM-3 (SLAM_M_PLAN.md r2, Wave 3) — one name, additive, and the
        # enumerated amendment RM2_STATUS.md §8.2 handoff 2 asked for: RM-2 wired
        # ``route_memory`` on the product path behind a default-OFF flag and the
        # eval runner had no way to reach it, so no eval arm had EVER run flag-ON.
        # ``DirectiveNavigator.__init__`` defaults it to False and every RM-2
        # branch is gated on ``self._route_memory is not None``, so a run that
        # does not name it makes the byte-identical ``from_config`` call.
        "route_memory",
    }
)

# --- DR-2: the degraded-pose arm ---------------------------------------------
#
# Injection, in one sentence: name a profile from ``configs/navigation/pose.yaml``
# and every episode of the run builds ONE FRESH provider for it, feeds it this
# tick's sim truth, and hands it to the navigator through the pose seam.
#
# The seam already existed. ``HeadlessCityQualityHarness`` takes ``pose_profile=``
# and exposes ``new_pose_provider()``; ``_nav_observation`` takes
# ``pose_provider=``; ``parcel_robot.pose.observation_pose`` is the only way
# navigation reads a pose. DR-2 adds no seam and edits nothing in
# ``headless_city.py`` or ``pose.py``. Navigator overrides deliberately do NOT
# appear here: ``DirectiveNavigator.from_config`` has no pose keyword, so the
# override set cannot reach the pose source and is left untouched.

#: The reference per-episode divergence distribution, in **percent of distance
#: travelled**, over the 60 seeds ``0..59`` on the straight 11.9 m run DR1_STATUS
#: §6 uses. Re-measured here rather than transcribed as prose, and pinned by
#: ``tests/test_dr2_pose_drift_arm.py`` against a fresh sweep, so a pose.yaml
#: change that moves a profile reddens instead of silently widening a band.
#:
#: **Which columns reproduce, exactly.** The mean, median and max reproduce
#: DR1_STATUS §6's published table to the last published digit — 3.42 / 2.89 /
#: 11.44, 6.83 / 5.76 / 22.73, 14.21 / 12.43 / 46.95 — which is the independent
#: corroboration that this instrument is DR-1's instrument.
#:
#: The **p90 does NOT**, under either estimator, and saying it did was wrong:
#: measured 6.396 / 12.822 / 29.812 by the sorted-index method and 6.384 /
#: 12.755 / 28.409 by linear interpolation, against DR-1's published 6.38 /
#: 12.75 / 28.25. The first two profiles agree to a rounding; ``go2_degraded``
#: is off by 1.4-1.6 points, which is an estimator difference in the tail of a
#: 60-sample distribution, not a difference in the underlying draw (the max
#: agrees exactly, and the max is the harder number to match by luck).
#:
#: It has **no behavioural consequence**: only ``min`` and ``max`` feed the band
#: below, and both reproduce. The p90 is used in exactly one place — the test
#: that asserts the band clears the tail — where it is re-measured locally and
#: never compared to a transcribed figure.
DIVERGENCE_REFERENCE_DISTANCE_M = 11.9
DIVERGENCE_REFERENCE_SEEDS = 60
#: ``profile -> (min, max)`` of that 60-seed distribution.
DIVERGENCE_REFERENCE_PCT: dict[str, tuple[float, float]] = {
    "calibrated_go2": (0.21, 11.44),
    "calibrated_go2_lost": (0.21, 11.44),
    "calibrated_go2_reanchoring": (0.21, 11.44),
    "go2_aggressive": (0.42, 22.73),
    "go2_aggressive_lost": (0.42, 22.73),
    "go2_degraded": (0.42, 46.95),
    "go2_degraded_lost": (0.42, 46.95),
}

#: How the per-episode band is built from that reference. Fixed BEFORE Stage A,
#: applied identically to every profile, and never re-derived from an eval
#: number.
#:
#: The band's job is *not* to separate the tiers per episode — DR1_STATUS §6
#: proves that is impossible, because one episode can sit anywhere in a
#: distribution whose max is 3x its mean. Its job is the falsifiable claim a
#: single row can carry: **this episode's divergence lies inside the envelope
#: this profile's own 60-seed sweep produced**, so a row cannot have been
#: measured with the injector off (below the floor) or with a runaway integrator
#: (above the ceiling).
#:
#: **It cannot catch a tier mix-up, and must not be read as if it could.**
#: Quantified on the Stage-A rows: all 33/33 in-band ``calibrated_go2`` episodes
#: also satisfy ``go2_degraded``'s band, and 17 of 22 ``go2_degraded`` episodes
#: also satisfy ``calibrated_go2``'s. The bands overlap almost completely, by
#: construction — each is its own profile's full 60-seed envelope widened
#: (0.5x, 2.0x), and the envelopes nest. The check that catches an arm running
#: the wrong tier is :func:`run_drift_arms.ladder_monotone`, at the ARM MEAN,
#: which is the statistic the per-episode seed variation exists to make
#: meaningful. DR2_STATUS.md §3 states the same split.
DIVERGENCE_BAND_LOW_FACTOR = 0.5
DIVERGENCE_BAND_HIGH_FACTOR = 2.0
#: Below this distance the percentage has no meaning and the band is not
#: applied (the row still records the raw metres). Derived: the alpha model's
#: sigma grows like ``sqrt(D)`` (``pose.py``'s units-trap docstring), so a
#: percentage is only comparable to the reference within a factor of ``sqrt(2)``
#: of the reference length — i.e. at least half of it.
DIVERGENCE_BAND_MIN_TRAVEL_M = DIVERGENCE_REFERENCE_DISTANCE_M / 2.0


#: The pipeline's note for "MAP localization is LOST, so hold the body".
#:
#: The runner used to end an episode on ANY commanded stop, which reads this
#: hold as a terminal decision. It is not one: ``pipeline._pose_lost_hold``'s
#: own docstring says LOST "stops the body; it does **not** fail the mission,
#: because the goal is still valid and health can return". Under that reading a
#: scheduled dropout window could never be observed to RECOVER — the episode
#: ended on the window's first tick, 2.9 m into a 10 m route (measured) — so the
#: ``*_lost`` arm's recovery assertion was unprovable rather than false.
#:
#: This cannot move a frozen row. ``TruthPoseProvider`` is HEALTHY by
#: construction and the same docstring states that only a config-injected drift
#: provider can reach the branch at all, so on every truth-pose run the note is
#: never emitted and the condition is byte-identical to the old one. Pinned by
#: ``tests/test_dr2_pose_drift_arm.py``.
POSE_LOST_HOLD_NOTE = "pose_lost_hold"


def divergence_band_pct(profile: str) -> tuple[float, float]:
    """The pre-registered per-episode divergence band for ``profile``."""

    try:
        low, high = DIVERGENCE_REFERENCE_PCT[profile]
    except KeyError:
        raise ValueError(
            f"no pre-registered divergence reference for pose profile "
            f"{profile!r}; known: {sorted(DIVERGENCE_REFERENCE_PCT)}"
        ) from None
    return (low * DIVERGENCE_BAND_LOW_FACTOR, high * DIVERGENCE_BAND_HIGH_FACTOR)


def episode_pose_seed(profile_seed: int, episode_id: str) -> int:
    """The per-episode drift seed: ``profile seed XOR a stable episode hash``.

    **Why this exists at all.** Every profile in ``configs/navigation/pose.yaml``
    ships ONE seed (20260807). Running n episodes of an arm on it replays one
    identical draw n times — a sample of size one dressed as n — and that single
    draw is not typical: DR1_STATUS §6 measures it at 25.8 % divergence against
    a 60-seed mean of 14.2 % on ``go2_degraded``. A band gate written against the
    mean would then red spuriously, and an arm mean would carry no information
    about the profile.

    The derivation is a XOR against ``sha256(episode_id)`` rather than against a
    positional index, on purpose: an episode's seed then depends on the episode
    and nothing else, so slicing the set with ``--limit``, reordering it, or
    adding a cell does not silently re-roll any other episode's draw. Because
    the profile seeds are all equal, the same episode also draws the same seed
    under every profile — common random numbers across the ladder, which is the
    right pairing for a cross-profile comparison, and free.

    Deterministic and reproducible: the returned value is recorded on the
    episode's persisted row, so any row can be re-run exactly.
    """

    digest = hashlib.sha256(str(episode_id).encode("utf-8")).digest()[:4]
    return (int(profile_seed) ^ int.from_bytes(digest, "big")) & 0xFFFFFFFF


class _DriftSeededHarness(HeadlessCityQualityHarness):
    """A harness whose fresh-per-episode provider carries a per-episode seed.

    A subclass rather than an edit: ``headless_city.py`` is out of DR-2's OWNS,
    and it already does the one thing that matters — ``new_pose_provider()``
    builds a brand-new provider per run so drift can never cross episodes. All
    this adds is the seed variation the measurement needs, on top of ``super()``,
    which also means the spatial families (which reach the provider only through
    ``harness.run``) inherit it without the runner having to reach inside.
    """

    #: Set by the runner before each episode; ``None`` = use the shipped seed.
    episode_id: str | None = None
    #: The provider the last ``new_pose_provider()`` call handed out, so a caller
    #: that cannot see inside ``harness.run`` can still read its metrics.
    last_pose_provider: PoseProvider | None = None
    #: The seed that provider was reset with (``None`` for a truth passthrough).
    last_pose_seed: int | None = None

    def new_pose_provider(self) -> PoseProvider:
        provider = super().new_pose_provider()
        params = getattr(provider, "params", None)
        seed: int | None = None
        if params is not None and self.episode_id is not None:
            seed = episode_pose_seed(params.seed, self.episode_id)
            # ``params`` is a frozen dataclass and ``provider.params`` is a plain
            # attribute, so this replaces the whole parameter block rather than
            # mutating one field of a shared object. ``reset()`` then rebuilds
            # the RNG from it and re-draws the per-run systematic biases — the
            # same lifecycle a fresh construction would have had.
            provider.params = replace(params, seed=seed)
            provider.reset()
        elif params is not None:
            seed = int(params.seed)
        self.last_pose_provider = provider
        self.last_pose_seed = seed
        return provider


class _PoseDriftObserver:
    """Per-tick observations a provider does not count for itself.

    Three of DR-2's required metrics are *events over the episode* rather than
    end-state properties, and none of them can be read off the provider
    afterwards:

    * **POSE_LOST hold and recovery.** ``PoseHealth`` is instantaneous. Whether a
      scheduled window both held and then RECOVERED is only visible by watching.
    * **MAP re-anchor events.** ``_maybe_correct_map`` sets ``MAP := truth``
      exactly, so a re-anchor is precisely the tick on which a strictly positive
      MAP-vs-truth error becomes exactly zero. Counting the zero-crossings needs
      no access to provider internals and cannot double-count a plateau.
    * **Distance travelled at the moment of each event**, for the report.

    Sampling is read-only: ``get_pose`` draws no randomness, so an observed
    episode and an unobserved one are bit-identical.
    """

    #: MAP-vs-truth error at or below this counts as re-anchored. The provider
    #: assigns truth exactly, so the tolerance only absorbs float formatting.
    REANCHOR_TOLERANCE_M = 1e-9

    def __init__(self, provider: PoseProvider) -> None:
        self.provider = provider
        self.lost_ticks = 0
        self.healthy_ticks = 0
        self.reanchor_events = 0
        self.first_lost_t_s: float | None = None
        self.last_lost_t_s: float | None = None
        self.recovered_t_s: float | None = None
        self._prev_map_error_m: float | None = None

    def sample(self, truth_xy: tuple[float, float], t_s: float) -> None:
        pose = self.provider.get_pose(Frame.ODOM)
        if pose.health is PoseHealth.LOST:
            self.lost_ticks += 1
            if self.first_lost_t_s is None:
                self.first_lost_t_s = float(t_s)
            self.last_lost_t_s = float(t_s)
        else:
            self.healthy_ticks += 1
            # Recovery = the first healthy tick AFTER a lost one. Recorded once.
            if self.last_lost_t_s is not None and self.recovered_t_s is None:
                self.recovered_t_s = float(t_s)
        map_pose = self.provider.get_pose(Frame.MAP)
        error = math.hypot(map_pose.x - truth_xy[0], map_pose.y - truth_xy[1])
        if (
            self._prev_map_error_m is not None
            and self._prev_map_error_m > self.REANCHOR_TOLERANCE_M
            and error <= self.REANCHOR_TOLERANCE_M
        ):
            self.reanchor_events += 1
        self._prev_map_error_m = error


def pose_drift_record(
    provider: PoseProvider | None,
    *,
    profile: str | None,
    seed: int | None,
    observer: _PoseDriftObserver | None = None,
) -> dict[str, Any] | None:
    """The per-episode drift evidence a persisted row carries. ``None`` = no arm.

    Every field is measured, never assumed: ``distance_m`` and ``divergence_m``
    come from the provider's own counters, ``divergence_pct`` is their ratio, and
    ``in_band`` is the pre-registered band applied to THIS episode's numbers.
    """

    if provider is None or profile is None:
        return None
    travelled = float(getattr(provider, "travelled_m", 0.0))
    error_m = float(getattr(provider, "odom_error_m", 0.0))
    yaw_error = float(getattr(provider, "odom_yaw_error_rad", 0.0))
    pct = 100.0 * error_m / travelled if travelled > 0.0 else float("nan")
    low, high = divergence_band_pct(profile)
    banded = travelled >= DIVERGENCE_BAND_MIN_TRAVEL_M
    record: dict[str, Any] = {
        "profile": profile,
        "seed": seed,
        "distance_m": travelled,
        "divergence_m": error_m,
        "divergence_pct": pct,
        "yaw_divergence_rad": yaw_error,
        "slip_events": int(getattr(provider, "slip_events", 0)),
        "band_pct": [low, high],
        "band_applied": bool(banded),
        "in_band": bool(banded and low <= pct <= high),
    }
    if observer is not None:
        record.update(
            {
                "lost_ticks": observer.lost_ticks,
                "healthy_ticks": observer.healthy_ticks,
                "reanchor_events": observer.reanchor_events,
                "first_lost_t_s": observer.first_lost_t_s,
                "last_lost_t_s": observer.last_lost_t_s,
                "recovered_t_s": observer.recovered_t_s,
                "lost_recovered": bool(
                    observer.lost_ticks > 0 and observer.recovered_t_s is not None
                ),
            }
        )
    return record


# --- RM-3: the taught-prior-route arm ----------------------------------------
#
# Two additive seams, and nothing else. Both are inert unless the caller asks
# for them, which is what keeps every frozen row and every DR-2 arm byte-exact:
#
# * ``pre_drive`` — a callable invoked ONCE per navigation episode, after the
#   navigator is constructed and BEFORE ``navigator.start(directive)``, i.e.
#   before the measured mission exists and before a single step of its budget is
#   spent. It is how card RM-3 teaches a route the way the robot would actually
#   learn one: by DRIVING it. Whatever it does to the world it must undo (the
#   contract below), because the measured episode has to begin from exactly the
#   pose the episode spec declares.
# * ``route_memory`` telemetry — RM-2's non-vacuity counters, copied onto the
#   persisted row so an ON-arm win can be read as "it came through the waypoint
#   chain" rather than assumed. Stamped only when the run named the flag, on the
#   same rule ``pose_drift_profile`` uses.

#: What a ``pre_drive`` callable is handed and what it must return.
#:
#: **Contract, in three clauses.**
#:
#: 1. It may drive the world freely — that is the point; ingestion into the
#:    place graph happens because the NAVIGATOR is stepped over real motion.
#: 2. It MUST leave the world at the episode's declared start pose with the
#:    episode's placement overrides applied and the collision counter zeroed,
#:    i.e. it must end with the same ``world.reset(...)`` +
#:    ``apply_placement_overrides(...)`` pair ``run_episode`` opened with. The
#:    measured episode is then bit-identical to one that never pre-drove, which
#:    is exactly what makes the flag the only difference between the paired arms.
#: 3. It MUST leave the navigator with no live mission (``navigator.stop()``),
#:    so ``start()`` below is a real mission boundary — RM-2 breaks the place
#:    graph's ingest track there, and an unbroken track would record the reset
#:    teleport as a traversal (AUDIT_WAVE1_FABLE.md's named failure).
#:
#: The returned mapping is recorded verbatim under ``route_memory.pre_drive`` on
#: the episode row; ``None`` records nothing.
PreDrive = Any

#: Counter names copied off the live ``DirectiveNavigator``. Every one of them is
#: RM-2's own append-only evidence (RM2_STATUS.md §2), read by no decision.
_ROUTE_MEMORY_COUNTERS: tuple[str, ...] = (
    "route_memory_keyframes",
    "route_memory_routes_found",
    "route_memory_proposals",
    "route_memory_wins",
    "route_memory_vetoes",
    "route_memory_chain_ticks",
    "route_memory_deferred_releases",
    "route_memory_flushes",
    "route_memory_handbacks",
)


def route_memory_record(navigator: Any) -> dict[str, Any]:
    """RM-2's per-episode non-vacuity counters, off the live navigator.

    ``hook`` is :meth:`RouteMemoryPlaceHook.snapshot` — the graph's own view
    (keyframes, edges, routes queried vs found, proposals made/won/vetoed) —
    and it is ``None`` flag-OFF, where the hook does not exist. That asymmetry is
    the evidence, not a gap: a flag-OFF row that carried a hook snapshot would
    mean the flag did not turn anything off.
    """

    record: dict[str, Any] = {
        "enabled": bool(getattr(navigator, "route_memory", False)),
    }
    for name in _ROUTE_MEMORY_COUNTERS:
        record[name.removeprefix("route_memory_")] = int(getattr(navigator, name, 0))
    hook = getattr(navigator, "_route_memory", None)
    snapshot = getattr(hook, "snapshot", None)
    record["hook"] = snapshot() if callable(snapshot) else None
    return record


#: The v1 arrival rule: ``score_episode``'s hold, exactly as frozen.
FROZEN_ARRIVAL_RULE = "frozen-hold-v1"
#: The v2 arrival rule (re-freeze correction (c)).
DERIVED_ARRIVAL_RULE = DERIVED_RULE_ID
ARRIVAL_RULES: tuple[str, ...] = (FROZEN_ARRIVAL_RULE, DERIVED_ARRIVAL_RULE)

#: The rule a fresh run uses unless told otherwise. Changing this default does
#: not and cannot move a frozen row — frozen rows are persisted artifacts.
DEFAULT_ARRIVAL_RULE = DERIVED_ARRIVAL_RULE

#: Which arrival rule each episode-set version was frozen under.
ARRIVAL_RULE_FOR_VERSION: dict[str, str] = {
    "v1": FROZEN_ARRIVAL_RULE,
    "v1a-scene-truth-only": FROZEN_ARRIVAL_RULE,
    "v2": DERIVED_ARRIVAL_RULE,
    # v3 changes the next_to band only; the arrival rule is v2's, unchanged, so
    # a v2 -> v3 difference cannot contain a rule change.
    "v3": DERIVED_ARRIVAL_RULE,
    # v4 changes the follow_owner goal radius only (correction (e), owner-
    # authorized 2026-08-11). The arrival rule is still v2's, so a v3 -> v4
    # difference cannot contain a rule change either — every delta has to be the
    # resized region. See evals/nav_instruct/bridge_v3_v4.py.
    "v4": DERIVED_ARRIVAL_RULE,
}
DOES_NOT_PROVE = (
    "sim ground-truth semantics ≠ camera perception — closes with hardware perception",
    "absent-target honesty under open-vocab detectors (tier E guards the class only)",
    "downloaded VLM/VLA policies (rungs 6–7)",
)

# --- step-budget policies (card budget-honest-minival, 2026-08-09) ------------
#: "fixed" is the frozen behaviour every persisted row was run under: one flat
#: ``max_steps`` for every episode, regardless of how far its start pose sits
#: from the goal. That conflates capability with distance — the audit's
#: "candidate SR 0.12 -> 0.48 by raising --max-steps alone" artifact, where a
#: 56 m tier-E reach and a 3 m tier-A reach are scored under the identical clock.
#: "scaled-path-v1" derives a per-episode budget from the episode's OWN
#: ``shortest_path_m`` so a tier-E truncation is attributable to a genuine miss,
#: not to budget starvation. It is a NEW policy version: the default stays
#: "fixed", so every frozen row and every existing test is byte-identical.
FIXED_BUDGET_POLICY = "fixed"
SCALED_BUDGET_POLICY = "scaled-path-v1"
BUDGET_POLICIES: tuple[str, ...] = (FIXED_BUDGET_POLICY, SCALED_BUDGET_POLICY)
DEFAULT_BUDGET_POLICY = FIXED_BUDGET_POLICY

#: Only the point-goal families scale with a path. The spatial families
#: (follow/circle) are continuous behaviours whose budget is a duration, not a
#: distance, so they keep the flat base budget under every policy.
_PATH_SCALED_FAMILIES = frozenset({"region_goal", "object_goal", "object_relative"})
#: Fixed overhead a navigation episode pays regardless of path length: the
#: opening look-around/scan to acquire the target (~80 steps for a revolution at
#: the search yaw-rate) plus the terminal align + settle + verification hold
#: (~40). Measured from the pacing traces.
_BUDGET_OVERHEAD_STEPS = 120
#: Effective net planning progress along the path (m/s). Deliberately well below
#: the 0.85 m/s cruise: it amortises slowdown, alignment, detours and the
#: reactive gate over the whole path. A SMALLER number is a MORE generous
#: budget, which is the safe direction for "not budget starvation".
_BUDGET_PLANNING_SPEED_MPS = 0.30
#: The sim control tick the runner's world advances at.
_BUDGET_CONTROL_DT_S = 0.1
#: Upper bound so a phantom tier-E path (absent target ~56 m away) cannot demand
#: an unbounded run: an absent target completes its bounded scan+frontier search
#: and reports NOT_FOUND well inside this, and a present far target is reachable
#: within it. Keeps the honest-failure claim without an open-ended compute cost.
_BUDGET_CAP_STEPS = 1200


def scaled_step_budget(episode: EpisodeSpec, base_steps: int, policy: str) -> int:
    """Per-episode step budget under ``policy`` (see :data:`BUDGET_POLICIES`).

    ``fixed`` returns ``base_steps`` unchanged for every episode — byte-identical
    to every frozen row. ``scaled-path-v1`` derives a budget from the episode's
    own ``shortest_path_m`` for the point-goal families, floored at ``base_steps``
    (a scaled budget only ever ADDS room, never removes it) and capped at
    ``_BUDGET_CAP_STEPS``.
    """

    if policy == FIXED_BUDGET_POLICY:
        return int(base_steps)
    if policy != SCALED_BUDGET_POLICY:
        raise ValueError(f"budget_policy must be one of {BUDGET_POLICIES}")
    if episode.family not in _PATH_SCALED_FAMILIES:
        return int(base_steps)
    travel_steps = math.ceil(
        max(0.0, float(episode.shortest_path_m))
        / (_BUDGET_PLANNING_SPEED_MPS * _BUDGET_CONTROL_DT_S)
    )
    return int(max(base_steps, min(_BUDGET_CAP_STEPS, _BUDGET_OVERHEAD_STEPS + travel_steps)))


@dataclass(frozen=True)
class EpisodeRunResult:
    episode_id: str
    family: str
    tier: str
    instruction: str
    score: EpisodeScore
    collision_count: int
    semantic_scan_steps: int
    mission_status: str
    reason: str
    grounding_outcome: str
    trace: tuple[dict[str, Any], ...]
    mode: str
    #: Which arrival rule produced ``score.success``.
    arrival_rule: str = FROZEN_ARRIVAL_RULE
    #: What the frozen v1 hold rule would have said about this same trace.
    #: Equal to ``score.success`` when ``arrival_rule`` is the frozen one.
    frozen_rule_success: bool = False
    #: Which half of ``hold-or-trace-end-v1`` fired: ``frozen_hold`` /
    #: ``trace_end_hold`` / ``none``.
    arrival_branch: str = "frozen_hold"
    #: The effective step budget this episode ran under (card
    #: budget-honest-minival). Under the "fixed" policy every episode carries the
    #: same base; under "scaled-path-v1" it is the per-episode scaled budget, so
    #: a truncation can be read against the room the episode actually had.
    max_steps: int = 0
    #: DR-2: the pose profile this episode ran under, ``None`` for the shipping
    #: truth passthrough every frozen row was measured with.
    pose_drift_profile: str | None = None
    #: DR-2: this episode's measured drift evidence (see :func:`pose_drift_record`).
    #: ``None`` whenever ``pose_drift_profile`` is ``None``.
    pose_drift: dict[str, Any] | None = None
    #: RM-3: RM-2's non-vacuity counters for this episode (see
    #: :func:`route_memory_record`), plus whatever the ``pre_drive`` returned.
    #: ``None`` unless the run named the ``route_memory`` flag — on either arm,
    #: so the OFF arm's zeros are recorded rather than inferred.
    route_memory: dict[str, Any] | None = None

    @property
    def scorer_arrival(self) -> bool:
        """K0 GoalRegion predicate on the final pose (no settle hold)."""

        return bool(self.score.scorer_arrival)

    @property
    def system_arrival(self) -> bool | None:
        """The navigator's own arrival claim for this episode."""

        return self.score.system_arrival

    @property
    def authority_category(self) -> str:
        """Differential-authority verdict category (eval instrument 5)."""

        return self.score.authority_category.value

    def as_dict(self) -> dict[str, Any]:
        payload = self._as_dict()
        if self.pose_drift_profile is not None:
            # Stamped only on a drift arm, exactly like ``navigator_flags``: a
            # truth-pose row keeps the byte-identical shape every row already in
            # the ledger has, and EVERY row of a drift arm names its arm and
            # carries the seed it was drawn with.
            payload["pose_drift_profile"] = self.pose_drift_profile
            payload["pose_drift"] = self.pose_drift
        if self.route_memory is not None:
            # RM-3, same rule: a run that never named the flag keeps the
            # byte-identical row shape every frozen row already has.
            payload["route_memory"] = self.route_memory
        return payload

    def _as_dict(self) -> dict[str, Any]:
        return {
            "episode_id": self.episode_id,
            "family": self.family,
            "tier": self.tier,
            "instruction": self.instruction,
            "score": self.score.as_dict(),
            "collision_count": self.collision_count,
            "semantic_scan_steps": self.semantic_scan_steps,
            "mission_status": self.mission_status,
            "reason": self.reason,
            "grounding_outcome": self.grounding_outcome,
            "mode": self.mode,
            # Correction (c) — both rules, always, so neither can hide the other.
            "arrival_rule": self.arrival_rule,
            "frozen_rule_success": self.frozen_rule_success,
            "arrival_branch": self.arrival_branch,
            # Instrument 5 — both arrival authorities, logged every episode.
            "scorer_arrival": self.scorer_arrival,
            "system_arrival": self.system_arrival,
            "authority_category": self.authority_category,
            "arrival_epsilon_m": ARRIVAL_BOUNDARY_EPSILON_M,
            "max_steps": self.max_steps,
            "trace_len": len(self.trace),
            "trace": list(self.trace),
        }


class NavInstructRunner:
    """Deterministic NAV_INSTRUCT_V1 executor."""

    def __init__(
        self,
        *,
        robot_config: str | Path = DEFAULT_ROBOT_CONFIG,
        max_steps: int = 400,
        mode: str = "baseline",
        arrival_rule: str = DEFAULT_ARRIVAL_RULE,
        scene: str | Path | None = None,
        budget_policy: str = DEFAULT_BUDGET_POLICY,
        navigator_overrides: Mapping[str, Any] | None = None,
        pose_drift_profile: str | None = None,
        pre_drive: PreDrive | None = None,
    ) -> None:
        self.robot_config = robot_config
        self.max_steps = int(max_steps)
        # RM-3: ``None`` — the default and what every frozen row ran under — is
        # not "an empty pre-drive": ``_run_navigation`` never calls it, so the
        # measured path gains no code at all.
        self.pre_drive = pre_drive
        # Opt-in pipeline flags (card V-D ``value_directed_search`` / card V-E
        # ``detection_lock_on``). EMPTY by default, and an empty mapping expands
        # to no keyword at all in ``_navigator``, so every frozen row and every
        # existing caller makes the byte-identical ``from_config`` call.
        self.navigator_overrides: dict[str, Any] = dict(navigator_overrides or {})
        unknown = set(self.navigator_overrides) - ALLOWED_NAVIGATOR_OVERRIDES
        if unknown:
            raise ValueError(
                "navigator_overrides may only carry the pre-registered flags "
                f"{sorted(ALLOWED_NAVIGATOR_OVERRIDES)}; got {sorted(unknown)}"
            )
        mode_norm = str(mode).strip().lower()
        if mode_norm not in {"baseline", "candidate"}:
            raise ValueError("mode must be 'baseline' or 'candidate'")
        self.mode = mode_norm
        policy = str(budget_policy).strip()
        if policy not in BUDGET_POLICIES:
            raise ValueError(f"budget_policy must be one of {BUDGET_POLICIES}")
        self.budget_policy = policy
        rule = str(arrival_rule).strip()
        if rule not in ARRIVAL_RULES:
            raise ValueError(f"arrival_rule must be one of {ARRIVAL_RULES}")
        self.arrival_rule = rule
        # RM-3: whether this run's rows carry route-memory telemetry. Keyed on
        # the flag being NAMED, not on its value, so the OFF arm of a paired A/B
        # records its zeros (routes_found == 0 is the load-bearing control row)
        # while a run that never mentions route memory is untouched.
        self.route_memory_arm = "route_memory" in self.navigator_overrides
        self.pose_drift_profile = (
            None if pose_drift_profile is None else str(pose_drift_profile).strip()
        )
        if self.pose_drift_profile is not None:
            # Fail loudly HERE, not on episode 1 of 61: an unknown profile name
            # or an unknown yaml key raises out of the DR-1 seam, and a mistyped
            # arm must never quietly measure the nominal tier and be reported as
            # degraded. The provider built for the check is discarded.
            provider_from_config(profile=self.pose_drift_profile)
            divergence_band_pct(self.pose_drift_profile)
        self.world = (
            HeadlessCityWorld() if scene is None else HeadlessCityWorld(scene)
        )
        self.scene = str(self.world.scene)
        # With no profile named, the harness is constructed EXACTLY as it always
        # was — same class, same arguments — so the truth-pose path gains no new
        # code at all and cannot move.
        self.harness = (
            HeadlessCityQualityHarness(self.world, robot_config=robot_config)
            if self.pose_drift_profile is None
            else _DriftSeededHarness(
                self.world,
                robot_config=robot_config,
                pose_profile=self.pose_drift_profile,
            )
        )

    def run_episode(self, episode: EpisodeSpec) -> EpisodeRunResult:
        owner = None
        placement = dict(episode.placement_overrides or {})
        owner_spec = placement.get("owner")
        if isinstance(owner_spec, dict) and "x" in owner_spec and "y" in owner_spec:
            owner = (float(owner_spec["x"]), float(owner_spec["y"]))
        self.world.reset(robot=episode.start_pose, owner=owner, restore_semantics=True)
        self.world.apply_placement_overrides(placement)
        if isinstance(self.harness, _DriftSeededHarness):
            # Which episode the next ``new_pose_provider()`` draws its seed for.
            # Set before dispatch so BOTH the navigation path (which builds the
            # provider itself) and the spatial path (where the provider is built
            # inside ``harness.run``) get the same per-episode draw.
            self.harness.episode_id = episode.episode_id
            self.harness.last_pose_provider = None
            self.harness.last_pose_seed = None
        family = episode.family
        if family in {"follow_owner", "circle_owner"}:
            return self._run_spatial(episode)
        return self._run_navigation(episode)

    def _apply_arrival_rule(
        self,
        score: EpisodeScore,
        trace: list[dict[str, Any]],
        episode: EpisodeSpec,
        *,
        anchor_xy: tuple[float, float] | None,
    ) -> tuple[EpisodeScore, bool, str]:
        """Return ``(score under the active rule, frozen verdict, branch)``.

        Only the navigation families reach this: the spatial families are scored
        with ``arrival_hold_s = 0.0``, where the derived rule is a no-op by
        construction, and the refusal paths never claim arrival at all.
        """

        frozen_success = bool(score.success)
        if self.arrival_rule == FROZEN_ARRIVAL_RULE:
            return score, frozen_success, "frozen_hold" if frozen_success else "none"
        derived_success, branch = derived_arrival(
            trace, episode.goal, frozen_success=frozen_success, anchor_xy=anchor_xy
        )
        if derived_success == frozen_success:
            return score, frozen_success, branch
        promoted = promoted_derived_score(
            score, trace, shortest_path_m=episode.shortest_path_m
        )
        return promoted, frozen_success, branch

    def _navigator(self) -> DirectiveNavigator:
        """Baseline disables N-O2 memory/scan/frontier; candidate enables them."""

        return DirectiveNavigator.from_config(
            self.harness.navigation_config,
            instructnav_recovery=(self.mode == "candidate"),
            **self.navigator_overrides,
        )

    def _episode_max_steps(self, episode: EpisodeSpec) -> int:
        """The effective step budget for ``episode`` under the active policy."""

        return scaled_step_budget(episode, self.max_steps, self.budget_policy)

    def _new_pose_provider(self) -> tuple[PoseProvider | None, int | None]:
        """One FRESH provider for this episode, or ``(None, None)`` with no arm.

        ``None`` is not "a truth provider": it is the pre-seam call
        ``_nav_observation`` has always made, where the pose accessor falls back
        to the observation's own truth fields. Keeping it literally ``None``
        rather than passing a ``TruthPoseProvider`` is what makes "no profile
        named ⇒ no behavioural change" structural instead of argued.
        """

        harness = self.harness
        if not isinstance(harness, _DriftSeededHarness):
            return None, None
        provider = harness.new_pose_provider()
        return provider, harness.last_pose_seed

    def run_matrix(
        self,
        episodes: tuple[EpisodeSpec, ...] | None = None,
        *,
        seed: int = 20260804,
        minival: bool = False,
        version: str = DEFAULT_EPISODE_SET_VERSION,
    ) -> list[EpisodeRunResult]:
        if episodes is None:
            episodes = (
                generate_minival(seed=seed, version=version)
                if minival
                else generate_episode_matrix(seed=seed, per_family=25, version=version)
            )
        return [self.run_episode(ep) for ep in episodes]

    def _run_navigation(self, episode: EpisodeSpec) -> EpisodeRunResult:
        text = episode.instruction
        budget = self._episode_max_steps(episode)
        directive = navigation_directive_from_text(text)
        if directive is None:
            # Honest baseline refusal path when the parser rejects the utterance.
            trace = [
                {
                    "t_s": 0.0,
                    "x": episode.start_pose[0],
                    "y": episode.start_pose[1],
                    "stopped": True,
                    "refusal": True,
                    "reply": "I couldn't form a safe, grounded plan yet.",
                    "grounding_outcome": "REFUSAL",
                    "note": "directive_not_understood",
                }
            ]
            score = score_episode(
                trace,
                episode.goal,
                shortest_path_m=episode.shortest_path_m,
                max_time_s=budget * self.world.control_dt_s,
                system_arrival=system_arrival_claim("failed", "directive_not_understood"),
            )
            return EpisodeRunResult(
                episode_id=episode.episode_id,
                family=episode.family,
                tier=episode.tier,
                instruction=text,
                score=score,
                collision_count=0,
                semantic_scan_steps=0,
                mission_status="failed",
                reason="directive_not_understood",
                grounding_outcome="REFUSAL",
                trace=tuple(trace),
                mode=self.mode,
                arrival_rule=self.arrival_rule,
                frozen_rule_success=bool(score.success),
                arrival_branch="frozen_hold" if score.success else "none",
                max_steps=budget,
                pose_drift_profile=self.pose_drift_profile,
                pose_drift=None,
            )

        navigator = self._navigator()
        # RM-3: the taught leg. It runs BEFORE ``start()`` — so before the
        # measured mission exists and before one tick of ``budget`` is spent —
        # and it hands the world back at the episode's declared start pose. See
        # :data:`PreDrive` for the three clauses of its contract.
        pre_drive_record: dict[str, Any] | None = None
        if self.pre_drive is not None:
            pre_drive_record = self.pre_drive(self, navigator, episode)
        mission = navigator.start(directive)
        trace: list[dict[str, Any]] = []
        scan_steps = 0
        grounding_outcome = "UNSEEN"
        reason = "navigation_step_limit"
        terminal_status = mission.status
        # DR-2: ONE fresh provider per episode. Built here, after the parser has
        # accepted the directive and before the first tick, so its clock starts
        # with the episode's first truth sample.
        pose_provider, pose_seed = self._new_pose_provider()
        pose_observer = (
            None if pose_provider is None else _PoseDriftObserver(pose_provider)
        )
        try:
            for _ in range(budget):
                observation = self.world.observe()
                nav_observation = _nav_observation(
                    observation,
                    measured_velocity=self.world.command,
                    stop_confirmed=self.world.stopped,
                    settled_linear_speed_mps=self.harness._settled_linear_speed_mps,
                    settled_yaw_speed_rad_s=self.harness._settled_yaw_speed_rad_s,
                    pose_provider=pose_provider,
                )
                if pose_observer is not None:
                    # After ``_nav_observation`` (which fed this tick's truth in)
                    # and before the navigator consumes it, so what is recorded
                    # is exactly the pose the navigator is about to read.
                    pose_observer.sample(
                        (float(observation.robot.x), float(observation.robot.y)),
                        float(observation.timestamp),
                    )
                command = navigator.step(nav_observation)
                note = command.note or ""
                if note.startswith("semantic_search_scan"):
                    scan_steps += 1
                resolution = str(mission.metadata.get("resolution_state") or "")
                if resolution == "resolved":
                    grounding_outcome = "RESOLVED"
                elif resolution == "searching" or resolution == "not_found":
                    grounding_outcome = "UNSEEN"
                elif resolution == "unreachable":
                    grounding_outcome = "RESOLVED"

                requested = (
                    VelocityCommand()
                    if command.stop
                    else VelocityCommand(command.vx, command.vy, command.vyaw)
                )
                velocity, _ = apply_reactive_safety(
                    requested,
                    observation,
                    policy=self.harness.reactive_safety,
                    owner_orbit=False,
                    orbit_radius_m=0.0,
                    now=observation.timestamp,
                    require_fresh_telemetry=False,
                )
                stopped = (
                    abs(velocity.vx) <= 1e-9
                    and abs(velocity.vy) <= 1e-9
                    and abs(velocity.vyaw) <= 1e-9
                )
                robot = observation.robot
                step_rec: dict[str, Any] = {
                    "t_s": float(observation.timestamp),
                    "x": float(robot.x),
                    "y": float(robot.y),
                    "stopped": stopped,
                    "vx": float(velocity.vx),
                    "vy": float(velocity.vy),
                    "note": note,
                    "resolution_state": resolution,
                    "grounding_outcome": grounding_outcome,
                    "collision": self.world.collision_count > 0,
                    "attempted": True,
                }
                if resolution == "not_found":
                    step_rec["not_found"] = True
                    if scan_steps > 0 or "frontier" in note:
                        step_rec["search_error"] = True
                    else:
                        step_rec["grounding_error"] = True
                if resolution == "unseen" and mission.status == "failed":
                    step_rec["not_found"] = True
                    step_rec["grounding_error"] = True
                if "semantic_target_not_found" in note:
                    reply = str(mission.metadata.get("reply") or "")
                    if scan_steps > 0 or self._frontier_attempted(trace, note):
                        step_rec["search_error"] = True
                        step_rec["not_found"] = True
                        step_rec["reply"] = reply or (
                            "I looked around and couldn't find the target nearby"
                        )
                    else:
                        step_rec["grounding_error"] = True
                        step_rec["not_found"] = True
                        step_rec["reply"] = reply or (
                            "I couldn't form a safe, grounded plan yet."
                        )
                        if self.mode == "baseline":
                            step_rec["refusal"] = True
                if mission.status == "failed" and resolution in {"", "unresolved"}:
                    step_rec["refusal"] = True
                    step_rec["reply"] = "I couldn't form a safe, grounded plan yet."
                trace.append(step_rec)
                self.world.apply(velocity)
                if (
                    command.stop
                    and mission.status != "verifying"
                    and note != POSE_LOST_HOLD_NOTE
                ) or navigator.done():
                    reason = note
                    terminal_status = mission.status
                    break
                self.world.step()
            else:
                mission.status = "failed"
                terminal_status = "timed_out"
                reason = "navigation_step_limit"
                if trace and episode.goal.contains(
                    float(trace[-1]["x"]),
                    float(trace[-1]["y"]),
                    anchor_xy=episode.goal.center,
                ):
                    reason = "navigation_step_limit_inside_goal"
                    trace[-1]["termination_error"] = True
                    trace[-1]["step_limit"] = True
                    trace[-1]["note"] = reason
                elif trace:
                    trace[-1]["step_limit"] = True
                    trace[-1]["note"] = reason
        finally:
            # RM-3: read the counters off the LIVE navigator, before ``close()``
            # disposes of it. Guarded so a run that never named the flag builds
            # nothing and stamps nothing.
            route_memory_row: dict[str, Any] | None = None
            if self.route_memory_arm:
                route_memory_row = route_memory_record(navigator)
                if pre_drive_record is not None:
                    route_memory_row["pre_drive"] = pre_drive_record
            self.world.stop()
            navigator.close()

        if not trace:
            trace = [
                {
                    "t_s": 0.0,
                    "x": episode.start_pose[0],
                    "y": episode.start_pose[1],
                    "stopped": True,
                    "refusal": True,
                    "reply": "I couldn't form a safe, grounded plan yet.",
                }
            ]

        if (
            terminal_status == "failed"
            and grounding_outcome == "UNSEEN"
            and scan_steps > 0
            and not any(step.get("search_error") or step.get("grounding_error") for step in trace)
        ):
            trace[-1]["search_error"] = True
            trace[-1]["not_found"] = True

        if episode.absent_target and terminal_status == "failed":
            # Tier E: bounded miss then report — search only if recovery ran.
            if scan_steps > 0 or any(
                "frontier" in str(step.get("note") or "")
                or "scan" in str(step.get("note") or "")
                for step in trace
            ):
                trace[-1]["search_error"] = True
            else:
                trace[-1]["grounding_error"] = True
            trace[-1]["not_found"] = True

        # Instrument 5: the navigator's own arrival claim, recorded next to the
        # scorer's K0 predicate on every episode — never merged into it.
        claimed_arrival = system_arrival_claim(terminal_status, reason)
        if trace:
            trace[-1]["system_arrival"] = claimed_arrival
        score = score_episode(
            trace,
            episode.goal,
            shortest_path_m=max(episode.shortest_path_m, 1e-3),
            max_time_s=budget * self.world.control_dt_s,
            arrival_hold_s=1.0,
            anchor_xy=episode.goal.center,
            system_arrival=claimed_arrival,
        )
        score, frozen_success, branch = self._apply_arrival_rule(
            score, trace, episode, anchor_xy=episode.goal.center
        )
        return EpisodeRunResult(
            episode_id=episode.episode_id,
            family=episode.family,
            tier=episode.tier,
            instruction=text,
            score=score,
            collision_count=int(self.world.collision_count),
            semantic_scan_steps=scan_steps,
            mission_status=str(terminal_status),
            reason=reason,
            grounding_outcome=grounding_outcome,
            trace=tuple(trace),
            mode=self.mode,
            arrival_rule=self.arrival_rule,
            frozen_rule_success=frozen_success,
            arrival_branch=branch,
            max_steps=budget,
            pose_drift_profile=self.pose_drift_profile,
            pose_drift=pose_drift_record(
                pose_provider,
                profile=self.pose_drift_profile,
                seed=pose_seed,
                observer=pose_observer,
            ),
            route_memory=route_memory_row,
        )

    def _run_spatial(self, episode: EpisodeSpec) -> EpisodeRunResult:
        """Follow/circle regression lane via the existing spatial/follow harness."""

        text = episode.instruction
        budget = self._episode_max_steps(episode)
        understood = parse_follow_intent(text) or parse_spatial_intent(text) is not None
        result = self.harness.run(text, max_steps=budget)
        # The spatial lane's provider is built and consumed INSIDE ``harness.run``
        # — the runner never sees a tick — so only the end-of-episode counters
        # are available here, never the per-tick LOST / re-anchor observations.
        # Recorded as such rather than papered over; the drift cells DR-2 floors
        # are all navigation-family and take the observed path above.
        spatial_provider = getattr(self.harness, "last_pose_provider", None)
        spatial_record = pose_drift_record(
            spatial_provider,
            profile=self.pose_drift_profile,
            seed=getattr(self.harness, "last_pose_seed", None),
        )
        trace = _trace_from_harness(result, episode)
        if not understood or result.reason == "directive_not_understood":
            if trace:
                trace[-1]["refusal"] = True
                trace[-1]["reply"] = "I couldn't form a safe, grounded plan yet."
            score = score_episode(
                trace,
                episode.goal,
                shortest_path_m=max(episode.shortest_path_m, 1e-3),
                max_time_s=budget * self.world.control_dt_s,
                system_arrival=system_arrival_claim(result.status, result.reason),
            )
            return EpisodeRunResult(
                episode_id=episode.episode_id,
                family=episode.family,
                tier=episode.tier,
                instruction=text,
                score=score,
                collision_count=int(result.collision_count),
                semantic_scan_steps=int(result.semantic_scan_steps),
                mission_status=str(result.status),
                reason=str(result.reason),
                grounding_outcome="REFUSAL",
                trace=tuple(trace),
                mode=self.mode,
                arrival_rule=self.arrival_rule,
                frozen_rule_success=bool(score.success),
                arrival_branch="frozen_hold" if score.success else "none",
                max_steps=budget,
                pose_drift_profile=self.pose_drift_profile,
                pose_drift=spatial_record,
            )

        if result.collision_count > 0:
            trace[-1]["collision"] = True
            trace[-1]["control_error"] = True
        claimed_arrival = system_arrival_claim(result.status, result.reason)
        if trace:
            trace[-1]["system_arrival"] = claimed_arrival
        # Score real poses only — never teleport into the goal disc.
        score = score_episode(
            trace,
            episode.goal,
            shortest_path_m=max(episode.shortest_path_m, 1e-3),
            max_time_s=budget * self.world.control_dt_s,
            arrival_hold_s=0.0,
            system_arrival=claimed_arrival,
        )
        return EpisodeRunResult(
            episode_id=episode.episode_id,
            family=episode.family,
            tier=episode.tier,
            instruction=text,
            score=score,
            collision_count=int(result.collision_count),
            semantic_scan_steps=int(result.semantic_scan_steps),
            mission_status=str(result.status),
            reason=str(result.reason),
            grounding_outcome="RESOLVED",
            trace=tuple(trace),
            mode=self.mode,
            # arrival_hold_s is 0.0 for the spatial families, so the derived
            # rule is a no-op here by construction (see rescore.SPATIAL_FAMILIES).
            arrival_rule=self.arrival_rule,
            frozen_rule_success=bool(score.success),
            arrival_branch="frozen_hold" if score.success else "none",
            max_steps=budget,
            pose_drift_profile=self.pose_drift_profile,
            pose_drift=spatial_record,
        )

    @staticmethod
    def _frontier_attempted(trace: list[dict[str, Any]], note: str) -> bool:
        if "frontier" in note or "scan_for_target" in note:
            return True
        return any(
            "frontier" in str(step.get("note") or "")
            or "scan_for_target" in str(step.get("note") or "")
            for step in trace
        )


def _trace_from_harness(result: Any, episode: EpisodeSpec) -> list[dict[str, Any]]:
    samples = list(getattr(result, "trace", ()) or ())
    if not samples:
        return [
            {
                "t_s": 0.0,
                "x": episode.start_pose[0],
                "y": episode.start_pose[1],
                "stopped": True,
                "attempted": True,
                "note": str(getattr(result, "reason", "")),
            }
        ]
    out: list[dict[str, Any]] = []
    for sample in samples:
        robot = sample.robot
        cmd = sample.command
        stopped = abs(cmd.vx) <= 1e-9 and abs(cmd.vy) <= 1e-9 and abs(cmd.vyaw) <= 1e-9
        if hasattr(robot, "x"):
            rx, ry = float(robot.x), float(robot.y)
        else:
            rx, ry = float(robot[0]), float(robot[1])
        out.append(
            {
                "t_s": float(sample.time_s),
                "x": rx,
                "y": ry,
                "stopped": stopped,
                "vx": float(cmd.vx),
                "vy": float(cmd.vy),
                "note": str(sample.note),
                "attempted": True,
            }
        )
    return out


def aggregate_results(
    results: list[EpisodeRunResult],
    *,
    episode_set_version: str | None = None,
    scene: str | None = None,
) -> dict[str, Any]:
    """Family × tier dashboard: SR, SPL, DTG, failure histogram.

    ``sr`` is the headline under whichever arrival rule the run used;
    ``sr_frozen_rule`` is always what the v1 hold rule would have said about the
    same traces, so correction (c) is isolated inside every single report.
    """

    cells: dict[str, dict[str, Any]] = {}
    failure_hist: dict[str, int] = {item.value: 0 for item in FailureClass}
    authority_hist: dict[str, int] = {item.value: 0 for item in AuthorityCategory}
    collisions = 0
    for result in results:
        authority_hist[result.authority_category] += 1
        key = f"{result.family}|{result.tier}"
        cell = cells.setdefault(
            key,
            {
                "family": result.family,
                "tier": result.tier,
                "n": 0,
                "successes": 0,
                "spl_sum": 0.0,
                "dtg_sum": 0.0,
                "failures": {item.value: 0 for item in FailureClass},
            },
        )
        cell["n"] += 1
        cell["successes"] += int(result.score.success)
        cell["spl_sum"] += float(result.score.spl)
        dtg = result.score.distance_to_goal_m
        cell["dtg_sum"] += 0.0 if not math.isfinite(dtg) else float(dtg)
        cell["failures"][result.score.failure.value] += 1
        failure_hist[result.score.failure.value] += 1
        collisions += int(result.collision_count)

    dashboard = []
    for key in sorted(cells):
        cell = cells[key]
        n = max(cell["n"], 1)
        dashboard.append(
            {
                "family": cell["family"],
                "tier": cell["tier"],
                "n": cell["n"],
                "sr": cell["successes"] / n,
                "spl": cell["spl_sum"] / n,
                "dtg_m": cell["dtg_sum"] / n,
                "failures": cell["failures"],
            }
        )
    n_all = max(len(results), 1)
    rules = sorted({r.arrival_rule for r in results}) or [DEFAULT_ARRIVAL_RULE]
    mean_dtg = sum(
        0.0 if not math.isfinite(r.score.distance_to_goal_m) else r.score.distance_to_goal_m
        for r in results
    ) / n_all
    aggregate: dict[str, Any] = {
        "runner_version": RUNNER_VERSION,
        "n": len(results),
        "sr": sum(1 for r in results if r.score.success) / n_all,
        "spl": sum(r.score.spl for r in results) / n_all,
        "mean_dtg_m": mean_dtg,
        "collision_total": collisions,
        "failure_histogram": failure_hist,
        "authority_histogram": authority_hist,
        "arrival_epsilon_m": ARRIVAL_BOUNDARY_EPSILON_M,
        # Correction (c), isolated inside the run itself.
        "arrival_rule": rules[0] if len(rules) == 1 else "|".join(rules),
        "sr_frozen_rule": sum(1 for r in results if r.frozen_rule_success) / n_all,
        "arrival_branch_histogram": _histogram(r.arrival_branch for r in results),
        "by_family_tier": dashboard,
        "does_not_prove": list(DOES_NOT_PROVE),
    }
    drift = aggregate_pose_drift(results)
    if drift is not None:
        aggregate["pose_drift"] = drift
    if episode_set_version is not None:
        aggregate["episode_set_version"] = episode_set_version
        aggregate["episode_set_provenance"] = episode_set_spec(
            episode_set_version
        ).provenance
    if scene is not None:
        aggregate["scene"] = scene
    return aggregate


def aggregate_pose_drift(results: list[EpisodeRunResult]) -> dict[str, Any] | None:
    """The arm-level drift summary, or ``None`` when no profile was named.

    Deliberately reports ``episodes_in_band`` as a COUNT against
    ``episodes_banded``, not as a mean: the non-vacuity claim DR-2 registers is
    per episode, and a mean would let one wildly out-of-envelope row hide behind
    fifty ordinary ones.
    """

    rows = [r.pose_drift for r in results if r.pose_drift is not None]
    if not rows:
        return None
    profiles = sorted({str(row["profile"]) for row in rows})
    banded = [row for row in rows if row.get("band_applied")]
    distances = [float(row["distance_m"]) for row in rows]
    pcts = [float(row["divergence_pct"]) for row in banded]
    summary: dict[str, Any] = {
        "profile": profiles[0] if len(profiles) == 1 else "|".join(profiles),
        "episodes": len(rows),
        "episodes_banded": len(banded),
        "episodes_in_band": sum(1 for row in banded if row.get("in_band")),
        "band_pct": banded[0]["band_pct"] if banded else None,
        "distance_m_total": sum(distances),
        "distance_m_mean": sum(distances) / len(distances),
        "distance_m_min": min(distances),
        "divergence_m_mean": sum(float(row["divergence_m"]) for row in rows) / len(rows),
        "divergence_pct_mean": (sum(pcts) / len(pcts)) if pcts else float("nan"),
        "divergence_pct_min": min(pcts) if pcts else float("nan"),
        "divergence_pct_max": max(pcts) if pcts else float("nan"),
        "slip_events_total": sum(int(row.get("slip_events", 0)) for row in rows),
        "lost_ticks_total": sum(int(row.get("lost_ticks", 0) or 0) for row in rows),
        "episodes_with_lost": sum(1 for row in rows if (row.get("lost_ticks") or 0) > 0),
        "episodes_lost_recovered": sum(1 for row in rows if row.get("lost_recovered")),
        "reanchor_events_total": sum(
            int(row.get("reanchor_events", 0) or 0) for row in rows
        ),
        "episodes_with_reanchor": sum(
            1 for row in rows if (row.get("reanchor_events") or 0) > 0
        ),
        "seeds_distinct": len({row.get("seed") for row in rows}),
    }
    return summary


def _histogram(values: Any) -> dict[str, int]:
    out: dict[str, int] = {}
    for value in values:
        key = str(value)
        out[key] = out.get(key, 0) + 1
    return dict(sorted(out.items()))
