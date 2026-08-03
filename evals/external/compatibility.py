"""Machine-readable compatibility records for external navigation benchmarks."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class BenchmarkFit:
    """How Parcel can (or cannot) evaluate against an external challenge."""

    id: str
    name: str
    url: str
    official_possible_today: bool
    offline_proxy_available: bool
    task_shapes: tuple[str, ...]
    success_criteria: str
    primary_metrics: tuple[str, ...]
    blockers: tuple[str, ...]
    parcel_bridge: str
    recommendation: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


COMPATIBILITY: tuple[BenchmarkFit, ...] = (
    BenchmarkFit(
        id="habitat2020_pointnav",
        name="Habitat Challenge 2020 PointNav",
        url="https://aihabitat.org/challenge/2020/",
        official_possible_today=False,
        offline_proxy_available=True,
        task_shapes=("pointnav",),
        success_criteria=(
            "Issue STOP within success radius of the relative goal "
            "(Habitat used 0.36 m for LoCoBot-sized agent)."
        ),
        primary_metrics=("success_rate", "spl", "soft_spl", "distance_to_goal"),
        blockers=(
            "No Habitat-Sim / Gibson dataset integration",
            "No RGB-D observation stream in Parcel runtime",
            "GPS-free visual localization not implemented (Habitat 2020 PointNav removes GPS+compass)",
            "Embodiment and action noise model differ from LoCoBot",
        ),
        parcel_bridge=(
            "Map relative goal → NavObservation + GoalPose; mid-level vx/vy/vyaw; "
            "score with metrics.spl using Euclidean or grid shortest path."
        ),
        recommendation=(
            "Use offline PointNav proxy for formula regression. Pursue Habitat only if "
            "adding a visual stack is an explicit product goal."
        ),
    ),
    BenchmarkFit(
        id="habitat2020_objectnav",
        name="Habitat Challenge 2020 ObjectNav",
        url="https://aihabitat.org/challenge/2020/",
        official_possible_today=False,
        offline_proxy_available=True,
        task_shapes=("objectnav",),
        success_criteria=(
            "STOP within 1.0 m of any target-category instance with oracle visibility "
            "from the stop pose (turn/look allowed, no translation)."
        ),
        primary_metrics=("success_rate", "spl", "soft_spl", "distance_to_goal"),
        blockers=(
            "No Matterport3D scenes",
            "No RGB-D category recognition pipeline",
            "Sim semantic polygons are diagnostics_only, not production perception",
        ),
        parcel_bridge=(
            "SemanticGoal + ObservationSemanticMap / synthetic labeled objects; "
            "SPL to closest instance from start."
        ),
        recommendation=(
            "Offline ObjectNav proxy is useful for goal-verification logic. "
            "Do not report Habitat ObjectNav numbers from sim-truth labels alone."
        ),
    ),
    BenchmarkFit(
        id="barn",
        name="BARN / BARN Challenge (metric ground navigation)",
        url="https://www.cs.utexas.edu/~xiao/BARN/BARN.html",
        official_possible_today=False,
        offline_proxy_available=True,
        task_shapes=("barn_clutter",),
        success_criteria=(
            "Reach goal with zero collisions; score uses OT/AT clip formula from BARN Challenge."
        ),
        primary_metrics=("success_rate", "barn_score", "collision_rate", "traversal_time_s"),
        blockers=(
            "The pinned source works in a cache-only Bubblewrap/PRoot diagnostic rootfs, but the upstream-tested SingularityCE/SIF path remains unavailable",
            "Parcel's content-addressed world-0 hook is classified policy_no_translation before the evaluator starts a trial",
            "An official result requires organizer-attested 50-hidden-world x 10-trial execution",
            "The 2026 deadline has passed and post-event organizer evaluation is not confirmed",
            "Go2 footprint and max speed differ from the standardized Jackal 2 m/s protocol",
        ),
        parcel_bridge=(
            "Synthetic narrow corridors + cylinder clutter; LiDAR/proximity extras; "
            "BARN score with Go2 vmax from robot.yaml."
        ),
        recommendation=(
            "Use the pinned ROS 2 Jazzy Singularity route for public compatibility and keep "
            "the native sensor-only runner for fast regression. Never promote either to an "
            "official score without the organizer's hidden evaluation and attestation."
        ),
    ),
    BenchmarkFit(
        id="threewe",
        name="3WE standardized embodied benchmarks",
        url="https://3we.org/benchmarks",
        official_possible_today=False,
        offline_proxy_available=True,
        task_shapes=("pointnav", "objectnav", "exploration"),
        success_criteria=(
            "PointNav/ObjectNav: SR + SPL over ≥100 episodes for official submits; "
            "Exploration: coverage within time budget + efficiency."
        ),
        primary_metrics=("success_rate", "spl", "coverage", "efficiency"),
        blockers=(
            "Pinned runner has no immutable external-agent observation/action hook",
            "Seed/reset/timeouts, PointNav success/SPL, ObjectNav, and Exploration semantics conflict with documentation",
            "Isaac is a no-op stub and the office pose/world/bridge coordinate contract is inconsistent",
            "Documented, runner, validator, and static leaderboard schemas/results diverge",
            "Shipped simulator is a holonomic mecanum robot, not a Unitree Go2",
            "No backend-specific cohort is large or authoritative enough to freeze a percentile",
        ),
        parcel_bridge=(
            "Mirror only generic task shapes and metric formulas in explicitly synthetic, "
            "rank-ineligible local tests; no adapter is admitted against the audited revision."
        ),
        recommendation=(
            "Keep all three targets unresolved. Wait for an organizer-confirmed, task-correct, "
            "backend-specific evaluator with a neutral agent hook before building an adapter."
        ),
    ),
    BenchmarkFit(
        id="social_hm3d",
        name="Social-HM3D / Falcon SocialNav",
        url="https://zeying-gong.github.io/projects/falcon/",
        official_possible_today=False,
        offline_proxy_available=True,
        task_shapes=("socialnav",),
        success_criteria=(
            "Reach goal while measuring human collisions and personal-space compliance."
        ),
        primary_metrics=("success_rate", "spl", "psc", "human_collision_rate"),
        blockers=(
            "Requires Habitat + HM3D/MP3D + ORCA humanoids",
            "Parcel living city uses seeded routes, not full reciprocal ORCA crowds",
        ),
        parcel_bridge=(
            "Synthetic pedestrians in kinematic episodes; reuse proximity thresholds "
            "aligned with Parcel safety config."
        ),
        recommendation=(
            "Use offline SocialNav metrics beside the MuJoCo living-city harness. "
            "Official Social-HM3D remains a research-only dependency."
        ),
    ),
)


def compatibility_table() -> list[dict[str, Any]]:
    return [item.to_dict() for item in COMPATIBILITY]


def get_fit(benchmark_id: str) -> BenchmarkFit:
    for item in COMPATIBILITY:
        if item.id == benchmark_id:
            return item
    raise KeyError(f"unknown benchmark id: {benchmark_id}")
