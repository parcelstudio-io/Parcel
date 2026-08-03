"""Validate the frozen, conjunctive external-evaluation portfolio objective."""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

from .barn_targets import load_barn_top_decile_target

DEFAULT_PORTFOLIO_TARGET_PATH = Path(__file__).resolve().parent / "targets" / "portfolio.json"


def _require_object(value: object, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise TypeError(f"{label} must be an object")
    return value


def _require_nonempty_list(value: object, label: str) -> list[Any]:
    if not isinstance(value, list) or not value:
        raise ValueError(f"{label} must be a non-empty list")
    return value


def validate_portfolio_target(
    document: dict[str, Any],
    *,
    manifest_dir: str | Path = DEFAULT_PORTFOLIO_TARGET_PATH.parent,
) -> None:
    """Validate claim classes, rank math, and the referenced BARN target.

    The validator deliberately does not infer achievement from a numeric proxy.
    Results and target definitions remain separate artifacts.
    """

    if document.get("schema_version") != 1:
        raise ValueError("portfolio target must use schema version 1")
    if not isinstance(document.get("portfolio_id"), str) or not document["portfolio_id"]:
        raise ValueError("portfolio_id must be a non-empty string")

    objective = _require_object(document.get("objective"), "objective")
    quantile = float(objective.get("quantile", float("nan")))
    if not math.isfinite(quantile) or not 0.0 < quantile < 1.0:
        raise ValueError("objective.quantile must be between zero and one")
    if objective.get("aggregation") != "conjunctive":
        raise ValueError("portfolio aggregation must be conjunctive")
    if objective.get("averaging_across_evaluators_allowed") is not False:
        raise ValueError("portfolio cannot average away a weak evaluator")
    if objective.get("recorded_achievement") is not None:
        raise ValueError("the target manifest must not record an achievement result")

    official = _require_nonempty_list(
        document.get("official_ranked_targets"), "official_ranked_targets"
    )
    proxies = _require_nonempty_list(
        document.get("proxy_development_gates"), "proxy_development_gates"
    )
    internal = _require_nonempty_list(
        document.get("internal_pass_fail_gates"), "internal_pass_fail_gates"
    )
    unresolved = _require_nonempty_list(document.get("unresolved_targets"), "unresolved_targets")

    all_entries = official + proxies + internal + unresolved
    ids = [entry.get("id") for entry in all_entries if isinstance(entry, dict)]
    if len(ids) != len(all_entries) or any(not isinstance(item, str) or not item for item in ids):
        raise ValueError("every portfolio entry must have a non-empty id")
    if len(ids) != len(set(ids)):
        raise ValueError("portfolio entry ids must be unique")
    if any(entry.get("adopted") is not True for entry in all_entries):
        raise ValueError("every entry in this portfolio version must be explicitly adopted")

    top_fraction = 1.0 - quantile
    targets_dir = Path(manifest_dir).expanduser().resolve()
    for entry in official:
        if entry.get("claim_class") != "official_ranked":
            raise ValueError(f"{entry['id']} has the wrong official claim class")
        cohort = _require_object(entry.get("cohort"), f"{entry['id']}.cohort")
        cohort_size = int(cohort.get("published_ranked_entries", 0))
        rank_cutoff = int(cohort.get("top_decile_rank_cutoff", 0))
        if cohort_size <= 0:
            raise ValueError(f"{entry['id']} must freeze a positive cohort")
        expected_cutoff = math.ceil(top_fraction * cohort_size - 1e-12)
        if rank_cutoff != expected_cutoff:
            raise ValueError(f"{entry['id']} rank cutoff does not match the quantile rule")
        metric = _require_object(entry.get("metric"), f"{entry['id']}.metric")
        threshold = float(metric.get("threshold", float("nan")))
        if not math.isfinite(threshold):
            raise ValueError(f"{entry['id']} must have a finite metric threshold")
        eligibility = _require_object(entry.get("eligibility"), f"{entry['id']}.eligibility")
        if eligibility.get("requires_exact_official_protocol") is not True:
            raise ValueError(f"{entry['id']} must require its exact official protocol")
        if eligibility.get("parcel_offline_proxy_eligible") is not False:
            raise ValueError(f"{entry['id']} cannot accept Parcel's offline proxy")

        barn_ref = entry.get("target_manifest_ref")
        if barn_ref is not None:
            if not isinstance(barn_ref, str) or not barn_ref:
                raise ValueError("BARN target_manifest_ref must be a non-empty string")
            barn_path = (targets_dir / barn_ref).resolve()
            if barn_path.parent != targets_dir:
                raise ValueError("target_manifest_ref must stay inside the targets directory")
            barn = load_barn_top_decile_target(barn_path)
            barn_threshold = float(barn["target"]["minimum_official_mean_navigation_score"])
            if entry["protocol_id"] != barn["benchmark"]["id"]:
                raise ValueError("portfolio BARN protocol does not match its target manifest")
            if cohort_size != int(barn["benchmark"]["registered_team_count"]):
                raise ValueError("portfolio BARN cohort does not match its target manifest")
            if rank_cutoff != int(barn["target"]["rank_cutoff_in_registered_cohort"]):
                raise ValueError("portfolio BARN cutoff does not match its target manifest")
            if threshold != barn_threshold:
                raise ValueError("portfolio BARN threshold does not match its target manifest")

    for entry in proxies:
        if entry.get("claim_class") != "proxy_development_gate":
            raise ValueError(f"{entry['id']} has the wrong proxy claim class")
        if entry.get("claim_eligible") is not False:
            raise ValueError(f"{entry['id']} must be ineligible for ranked claims")
        _require_object(entry.get("promotion_gate"), f"{entry['id']}.promotion_gate")

    for entry in internal:
        if entry.get("claim_class") != "internal_pass_fail":
            raise ValueError(f"{entry['id']} has the wrong internal claim class")
        if entry.get("gate") != "all_tests_pass":
            raise ValueError(f"{entry['id']} must remain an all-tests-pass gate")
        _require_nonempty_list(entry.get("test_paths"), f"{entry['id']}.test_paths")

    for entry in unresolved:
        if entry.get("claim_class") != "unresolved_top_decile":
            raise ValueError(f"{entry['id']} has the wrong unresolved claim class")
        if entry.get("numeric_threshold") is not None:
            raise ValueError(f"{entry['id']} cannot invent an unresolved numeric threshold")
        if entry.get("blocks_portfolio_claim") is not True:
            raise ValueError(f"{entry['id']} must block the conjunctive portfolio claim")
        if not entry.get("reason") or not entry.get("resolution_required"):
            raise ValueError(f"{entry['id']} must explain how to resolve its target")
        lock_key = entry.get("source_lock_key")
        source_commit = entry.get("source_commit")
        snapshot = entry.get("leaderboard_snapshot")
        if lock_key is not None or source_commit is not None or snapshot is not None:
            if not isinstance(lock_key, str) or not lock_key:
                raise ValueError(f"{entry['id']} must declare a source_lock_key")
            if (
                not isinstance(source_commit, str)
                or len(source_commit) != 40
                or any(character not in "0123456789abcdef" for character in source_commit)
            ):
                raise ValueError(f"{entry['id']} must pin a full lowercase git commit")
            source_lock_path = targets_dir.parent / "sources.lock.json"
            try:
                source_lock = json.loads(source_lock_path.read_text(encoding="utf-8"))
                locked_commit = source_lock["sources"][lock_key]["commit"]
            except (OSError, KeyError, TypeError, json.JSONDecodeError) as exc:
                raise ValueError(
                    f"{entry['id']} cannot resolve {lock_key!r} in sources.lock.json"
                ) from exc
            if locked_commit != source_commit:
                raise ValueError(f"{entry['id']} source commit does not match its source lock")
            snapshot_object = _require_object(snapshot, f"{entry['id']}.leaderboard_snapshot")
            snapshot_path = snapshot_object.get("path")
            snapshot_sha = snapshot_object.get("sha256")
            if (
                not isinstance(snapshot_path, str)
                or not snapshot_path
                or Path(snapshot_path).is_absolute()
                or ".." in Path(snapshot_path).parts
            ):
                raise ValueError(f"{entry['id']} leaderboard path must be repository-relative")
            if (
                not isinstance(snapshot_sha, str)
                or len(snapshot_sha) != 64
                or any(character not in "0123456789abcdef" for character in snapshot_sha)
            ):
                raise ValueError(f"{entry['id']} must pin a leaderboard SHA-256")


def load_portfolio_target(
    path: str | Path = DEFAULT_PORTFOLIO_TARGET_PATH,
) -> dict[str, Any]:
    """Load and validate the versioned portfolio target."""

    target_path = Path(path).expanduser().resolve()
    try:
        document = json.loads(target_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot load portfolio target {target_path}: {exc}") from exc
    if not isinstance(document, dict):
        raise TypeError("portfolio target must be a JSON object")
    validate_portfolio_target(document, manifest_dir=target_path.parent)
    return document


def portfolio_claim_preconditions(
    path: str | Path = DEFAULT_PORTFOLIO_TARGET_PATH,
) -> dict[str, Any]:
    """Report static claim blockers without pretending to evaluate a model run."""

    document = load_portfolio_target(path)
    unresolved_ids = [
        item["id"] for item in document["unresolved_targets"] if item["blocks_portfolio_claim"]
    ]
    return {
        "portfolio_id": document["portfolio_id"],
        "aggregation": document["objective"]["aggregation"],
        "recorded_achievement": document["objective"]["recorded_achievement"],
        "claim_possible_from_targets_alone": False,
        "unresolved_target_ids": unresolved_ids,
        "ranked_target_ids": [item["id"] for item in document["official_ranked_targets"]],
    }


__all__ = [
    "DEFAULT_PORTFOLIO_TARGET_PATH",
    "load_portfolio_target",
    "portfolio_claim_preconditions",
    "validate_portfolio_target",
]
