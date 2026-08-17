"""Load authored low-viewpoint sample configs and smoke-evaluate gate pack."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from parcel_robot.low_viewpoint.gates import (
    DOES_NOT_PROVE,
    GateResult,
    LowViewpointSample,
    LowViewpointThresholds,
    all_passed,
    evaluate_all_gates,
)
from parcel_robot.paths import resolve_asset

DEFAULT_SAMPLES_REL = Path("configs/perception/low_viewpoint_samples.yaml")


@dataclass(frozen=True, slots=True)
class SampleExpectation:
    sample_id: str
    sample: LowViewpointSample
    expect_all_passed: bool
    expect_failed_gates: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class SamplePack:
    version: int
    thresholds: LowViewpointThresholds
    samples: tuple[SampleExpectation, ...]
    does_not_prove: tuple[str, ...]
    source_path: Path

    def smoke(self) -> tuple[SampleSmokeResult, ...]:
        return tuple(smoke_sample(item, self.thresholds) for item in self.samples)


@dataclass(frozen=True, slots=True)
class SampleSmokeResult:
    sample_id: str
    results: tuple[GateResult, ...]
    all_passed: bool
    expectation_ok: bool
    detail: str


def default_samples_path() -> Path:
    return resolve_asset(*DEFAULT_SAMPLES_REL.parts, kind="file")


def load_sample_pack(path: Path | str | None = None) -> SamplePack:
    """Load YAML sample pack (runtime_assets default)."""

    resolved = Path(path) if path is not None else default_samples_path()
    if not resolved.is_file():
        raise FileNotFoundError(f"low-viewpoint sample pack not found: {resolved}")
    with resolved.open("r", encoding="utf-8") as handle:
        raw = yaml.safe_load(handle)
    if not isinstance(raw, Mapping):
        raise TypeError("sample pack root must be a mapping")
    version = int(raw.get("version", 1))
    thr_raw = raw.get("thresholds") or {}
    if not isinstance(thr_raw, Mapping):
        raise TypeError("thresholds must be a mapping")
    thresholds = LowViewpointThresholds(
        mount_height_m=float(thr_raw.get("mount_height_m", 0.35)),
        mount_height_tolerance_m=float(thr_raw.get("mount_height_tolerance_m", 0.05)),
        min_sign_elevation_rad=float(thr_raw.get("min_sign_elevation_rad", 0.436332313)),
        min_ocr_char_recall=float(thr_raw.get("min_ocr_char_recall", 0.70)),
        min_legs_visible_fraction=float(thr_raw.get("min_legs_visible_fraction", 0.55)),
        require_reid_top1=bool(thr_raw.get("require_reid_top1", True)),
        min_vpr_recall_at_1=float(thr_raw.get("min_vpr_recall_at_1", 0.60)),
        require_curb_from_height_map=bool(thr_raw.get("require_curb_from_height_map", True)),
        require_d455_dropped=bool(thr_raw.get("require_d455_dropped", True)),
    )
    samples_raw = raw.get("samples")
    if not isinstance(samples_raw, list) or not samples_raw:
        raise ValueError("samples must be a non-empty list")
    samples: list[SampleExpectation] = []
    for item in samples_raw:
        if not isinstance(item, Mapping):
            raise TypeError("each sample must be a mapping")
        sample_id = str(item["id"])
        metrics = item.get("metrics")
        if not isinstance(metrics, Mapping):
            raise TypeError(f"sample {sample_id!r} metrics must be a mapping")
        failed = item.get("expect_failed_gates") or []
        if not isinstance(failed, list):
            raise TypeError(f"sample {sample_id!r} expect_failed_gates must be a list")
        samples.append(
            SampleExpectation(
                sample_id=sample_id,
                sample=_sample_from_metrics(metrics),
                expect_all_passed=bool(item.get("expect_all_passed", False)),
                expect_failed_gates=tuple(str(g) for g in failed),
            )
        )
    dnp = raw.get("does_not_prove") or list(DOES_NOT_PROVE)
    if not isinstance(dnp, list) or not dnp:
        raise ValueError("does_not_prove must be a non-empty list")
    return SamplePack(
        version=version,
        thresholds=thresholds,
        samples=tuple(samples),
        does_not_prove=tuple(str(x) for x in dnp),
        source_path=resolved,
    )


def smoke_sample(
    expectation: SampleExpectation,
    thresholds: LowViewpointThresholds | None = None,
) -> SampleSmokeResult:
    thr = thresholds or LowViewpointThresholds()
    results = evaluate_all_gates(expectation.sample, thr)
    passed = all_passed(results)
    failed_ids = tuple(r.gate_id for r in results if not r.passed)
    if expectation.expect_all_passed:
        ok = passed
        detail = "all gates passed" if ok else f"unexpected failures: {failed_ids}"
    else:
        expected = set(expectation.expect_failed_gates)
        actual = set(failed_ids)
        ok = (not passed) and expected.issubset(actual)
        detail = (
            f"failed={failed_ids}"
            if ok
            else f"expected failures {sorted(expected)}, got {failed_ids}"
        )
    return SampleSmokeResult(
        sample_id=expectation.sample_id,
        results=results,
        all_passed=passed,
        expectation_ok=ok,
        detail=detail,
    )


def smoke_default_pack() -> tuple[SampleSmokeResult, ...]:
    return load_sample_pack().smoke()


def assert_pack_expectations(results: Sequence[SampleSmokeResult]) -> None:
    bad = [r for r in results if not r.expectation_ok]
    if bad:
        lines = ", ".join(f"{r.sample_id}: {r.detail}" for r in bad)
        raise AssertionError(f"low-viewpoint sample expectations failed: {lines}")


def _sample_from_metrics(metrics: Mapping[str, Any]) -> LowViewpointSample:
    return LowViewpointSample(
        mount_height_m=float(metrics["mount_height_m"]),
        sign_elevation_angle_rad=float(metrics["sign_elevation_angle_rad"]),
        ocr_char_recall=float(metrics["ocr_char_recall"]),
        legs_visible_fraction=float(metrics["legs_visible_fraction"]),
        torso_visible_fraction=float(metrics["torso_visible_fraction"]),
        reid_top1_correct=bool(metrics["reid_top1_correct"]),
        vpr_recall_at_1=float(metrics["vpr_recall_at_1"]),
        curb_detected_from_height_map=bool(metrics["curb_detected_from_height_map"]),
        d455_depth_available=bool(metrics["d455_depth_available"]),
    )
