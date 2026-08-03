"""Load and evaluate frozen BARN goals without conflating proxy and official runs."""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

DEFAULT_BARN_TARGET_PATH = Path(__file__).resolve().parent / "targets" / "barn_2026_top_decile.json"


def load_barn_top_decile_target(path: str | Path = DEFAULT_BARN_TARGET_PATH) -> dict[str, Any]:
    """Load and validate the frozen 2026 simulation target manifest."""

    target_path = Path(path).expanduser().resolve()
    try:
        document = json.loads(target_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot load BARN target manifest {target_path}: {exc}") from exc
    if not isinstance(document, dict) or document.get("schema_version") != 1:
        raise ValueError("BARN target manifest must be a schema-version-1 object")
    target = document.get("target")
    scores = document.get("published_scores_descending")
    benchmark = document.get("benchmark")
    eligibility = document.get("eligibility")
    if not all(isinstance(value, dict) for value in (target, benchmark, eligibility)):
        raise ValueError("BARN target manifest is missing target/benchmark/eligibility objects")
    if not isinstance(scores, list) or not scores:
        raise ValueError("BARN target manifest must include published scores")
    numeric_scores = [float(entry["score"]) for entry in scores]
    ranks = [int(entry["rank"]) for entry in scores]
    if ranks != list(range(1, len(scores) + 1)):
        raise ValueError("BARN published score ranks must be contiguous from one")
    if numeric_scores != sorted(numeric_scores, reverse=True):
        raise ValueError("BARN published scores must be descending")
    threshold = float(target["minimum_official_mean_navigation_score"])
    rank_cutoff = int(target["rank_cutoff_in_registered_cohort"])
    numeric_cutoff = int(target["nearest_rank_cutoff_in_numeric_cohort"])
    registered_count = int(benchmark["registered_team_count"])
    expected_registered_cutoff = math.ceil(registered_count * 0.10)
    expected_numeric_cutoff = len(scores) - math.ceil(0.90 * len(scores)) + 1
    if rank_cutoff != expected_registered_cutoff or numeric_cutoff != expected_numeric_cutoff:
        raise ValueError("BARN top-decile cutoff does not match the frozen cohorts")
    if threshold != numeric_scores[numeric_cutoff - 1]:
        raise ValueError("BARN target threshold does not match the published rank cutoff")
    return document


def evaluate_barn_top_decile_target(
    navigation_score: float,
    *,
    official_protocol: bool,
    path: str | Path = DEFAULT_BARN_TARGET_PATH,
) -> dict[str, Any]:
    """Evaluate one score while preserving official-vs-proxy eligibility.

    A native score may be compared numerically to make progress visible, but it
    can never pass the official gate.  Only a standardized hidden-world Gazebo
    result may set ``official_gate_pass`` to true.
    """

    score = float(navigation_score)
    if not math.isfinite(score) or score < 0.0:
        raise ValueError("navigation_score must be finite and non-negative")
    manifest = load_barn_top_decile_target(path)
    threshold = float(manifest["target"]["minimum_official_mean_navigation_score"])
    numeric_reference_met = score >= threshold
    if official_protocol:
        status = "passed" if numeric_reference_met else "failed"
        official_gate_pass = numeric_reference_met
    else:
        status = "native_proxy_reference_only"
        official_gate_pass = False
    return {
        "target_id": manifest["target_id"],
        "status": status,
        "score": score,
        "minimum_official_score": threshold,
        "score_gap": score - threshold,
        "numeric_reference_met": numeric_reference_met,
        "official_gate_eligible": bool(official_protocol),
        "official_gate_pass": official_gate_pass,
        "leaderboard_claim_allowed": bool(official_protocol and official_gate_pass),
        "source": manifest["benchmark"]["source"],
        "note": (
            "Native proxy scores are not official or leaderboard-comparable."
            if not official_protocol
            else "Eligibility assumes the complete standardized hidden-world protocol."
        ),
    }


__all__ = [
    "DEFAULT_BARN_TARGET_PATH",
    "evaluate_barn_top_decile_target",
    "load_barn_top_decile_target",
]
