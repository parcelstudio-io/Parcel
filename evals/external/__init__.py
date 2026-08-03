"""Offline external navigation evaluation proxies for Parcel."""

from .compatibility import COMPATIBILITY, BenchmarkFit, compatibility_table, get_fit
from .metrics import (
    EpisodeMetrics,
    aggregate,
    barn_score,
    coverage_ratio,
    path_length,
    personal_space_compliance,
    soft_spl,
    success_weighted_path_length,
)
from .runner import run_suite, write_report

__all__ = [
    "COMPATIBILITY",
    "BenchmarkFit",
    "EpisodeMetrics",
    "aggregate",
    "barn_score",
    "compatibility_table",
    "coverage_ratio",
    "get_fit",
    "path_length",
    "personal_space_compliance",
    "run_suite",
    "soft_spl",
    "success_weighted_path_length",
    "write_report",
]
