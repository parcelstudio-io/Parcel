"""Low-viewpoint gate pack — dog-height (≈35 cm) failure-mode predicates.

Named gates for OCR-at-upward-angle, legs-first ReID, VPR@35 cm, and curb
detection from height map with D455 dropped. Each returns pass/fail + reason.

These are **sim / synthetic-metric gates**. Passing them does not prove real
D455 low-viewpoint performance (see hardware-readiness HR-4).
"""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass

from parcel_robot.camera_channel.d455 import MOUNT_HEIGHT_M

# Gate identifiers (stable for CI / status docs / HR-4 re-run).
GATE_OCR_UPWARD_ANGLE = "ocr_upward_angle"
GATE_LEGS_FIRST_REID = "legs_first_reid"
GATE_VPR_AT_35CM = "vpr_at_35cm"
GATE_CURB_HEIGHT_MAP_NO_D455 = "curb_height_map_without_d455"

LOW_VIEWPOINT_GATE_IDS = frozenset(
    {
        GATE_OCR_UPWARD_ANGLE,
        GATE_LEGS_FIRST_REID,
        GATE_VPR_AT_35CM,
        GATE_CURB_HEIGHT_MAP_NO_D455,
    }
)

DOES_NOT_PROVE = (
    "Sim/synthetic low-viewpoint gates do not prove real D455 optics, lighting, "
    "motion blur, or domain gap (hardware-readiness HR-4).",
    "Passing OCR/ReID/VPR/curb predicates on authored metrics does not validate "
    "field storefront confirmation or owner ReID at 35 cm.",
)


@dataclass(frozen=True, slots=True)
class GateResult:
    """Pass/fail outcome for one named low-viewpoint gate."""

    gate_id: str
    passed: bool
    reason: str

    def __post_init__(self) -> None:
        if self.gate_id not in LOW_VIEWPOINT_GATE_IDS:
            raise ValueError(f"unknown low-viewpoint gate_id: {self.gate_id!r}")
        if not isinstance(self.passed, bool):
            raise TypeError("passed must be a boolean")
        if not isinstance(self.reason, str) or not self.reason:
            raise ValueError("reason must be a non-empty string")


@dataclass(frozen=True, slots=True)
class LowViewpointThresholds:
    """Declared sim thresholds — not field acceptance criteria."""

    mount_height_m: float = MOUNT_HEIGHT_M
    mount_height_tolerance_m: float = 0.05
    # Storefront sign OCR under extreme upward look.
    min_sign_elevation_rad: float = math.radians(25.0)
    min_ocr_char_recall: float = 0.70
    # Pedestrians appear legs-first from dog height.
    min_legs_visible_fraction: float = 0.55
    require_reid_top1: bool = True
    # Place recognition at the same mount height.
    min_vpr_recall_at_1: float = 0.60
    # Curb via height-map discontinuity without RGB-D.
    require_curb_from_height_map: bool = True
    require_d455_dropped: bool = True

    def __post_init__(self) -> None:
        for name, value in (
            ("mount_height_m", self.mount_height_m),
            ("mount_height_tolerance_m", self.mount_height_tolerance_m),
            ("min_sign_elevation_rad", self.min_sign_elevation_rad),
            ("min_ocr_char_recall", self.min_ocr_char_recall),
            ("min_legs_visible_fraction", self.min_legs_visible_fraction),
            ("min_vpr_recall_at_1", self.min_vpr_recall_at_1),
        ):
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise TypeError(f"{name} must be numeric")
            if not math.isfinite(float(value)):
                raise ValueError(f"{name} must be finite")
        if self.mount_height_m <= 0.0:
            raise ValueError("mount_height_m must be positive")
        if self.mount_height_tolerance_m < 0.0:
            raise ValueError("mount_height_tolerance_m must be non-negative")
        for name, value in (
            ("min_ocr_char_recall", self.min_ocr_char_recall),
            ("min_legs_visible_fraction", self.min_legs_visible_fraction),
            ("min_vpr_recall_at_1", self.min_vpr_recall_at_1),
        ):
            if not 0.0 <= float(value) <= 1.0:
                raise ValueError(f"{name} must be in [0, 1]")
        if not isinstance(self.require_reid_top1, bool):
            raise TypeError("require_reid_top1 must be a boolean")
        if not isinstance(self.require_curb_from_height_map, bool):
            raise TypeError("require_curb_from_height_map must be a boolean")
        if not isinstance(self.require_d455_dropped, bool):
            raise TypeError("require_d455_dropped must be a boolean")


@dataclass(frozen=True, slots=True)
class LowViewpointSample:
    """One observation / trial for the low-viewpoint gate pack.

    Metrics are caller-supplied (sim instrumentation or bag-derived scores).
    This module only judges them against named thresholds.
    """

    mount_height_m: float
    # OCR / storefront
    sign_elevation_angle_rad: float
    ocr_char_recall: float
    # ReID / person appearance
    legs_visible_fraction: float
    torso_visible_fraction: float
    reid_top1_correct: bool
    # VPR
    vpr_recall_at_1: float
    # Curb / height map with D455 absent
    curb_detected_from_height_map: bool
    d455_depth_available: bool

    def __post_init__(self) -> None:
        for name, value in (
            ("mount_height_m", self.mount_height_m),
            ("sign_elevation_angle_rad", self.sign_elevation_angle_rad),
            ("ocr_char_recall", self.ocr_char_recall),
            ("legs_visible_fraction", self.legs_visible_fraction),
            ("torso_visible_fraction", self.torso_visible_fraction),
            ("vpr_recall_at_1", self.vpr_recall_at_1),
        ):
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise TypeError(f"{name} must be numeric")
            if not math.isfinite(float(value)):
                raise ValueError(f"{name} must be finite")
        for name, value in (
            ("ocr_char_recall", self.ocr_char_recall),
            ("legs_visible_fraction", self.legs_visible_fraction),
            ("torso_visible_fraction", self.torso_visible_fraction),
            ("vpr_recall_at_1", self.vpr_recall_at_1),
        ):
            if not 0.0 <= float(value) <= 1.0:
                raise ValueError(f"{name} must be in [0, 1]")
        if not isinstance(self.reid_top1_correct, bool):
            raise TypeError("reid_top1_correct must be a boolean")
        if not isinstance(self.curb_detected_from_height_map, bool):
            raise TypeError("curb_detected_from_height_map must be a boolean")
        if not isinstance(self.d455_depth_available, bool):
            raise TypeError("d455_depth_available must be a boolean")

    @property
    def is_legs_first(self) -> bool:
        return self.legs_visible_fraction >= self.torso_visible_fraction


def _mount_ok(sample: LowViewpointSample, thresholds: LowViewpointThresholds) -> bool:
    return abs(sample.mount_height_m - thresholds.mount_height_m) <= thresholds.mount_height_tolerance_m


def gate_ocr_upward_angle(
    sample: LowViewpointSample,
    thresholds: LowViewpointThresholds | None = None,
) -> GateResult:
    """OCR must hold under extreme upward sign angles at dog height."""

    thr = thresholds or LowViewpointThresholds()
    if not _mount_ok(sample, thr):
        return GateResult(
            GATE_OCR_UPWARD_ANGLE,
            False,
            f"mount_height_m={sample.mount_height_m:.3f} not within "
            f"±{thr.mount_height_tolerance_m} of {thr.mount_height_m}",
        )
    if sample.sign_elevation_angle_rad < thr.min_sign_elevation_rad:
        return GateResult(
            GATE_OCR_UPWARD_ANGLE,
            False,
            f"sign elevation {sample.sign_elevation_angle_rad:.3f} rad below "
            f"stress minimum {thr.min_sign_elevation_rad:.3f} rad",
        )
    if sample.ocr_char_recall < thr.min_ocr_char_recall:
        return GateResult(
            GATE_OCR_UPWARD_ANGLE,
            False,
            f"ocr_char_recall={sample.ocr_char_recall:.3f} < {thr.min_ocr_char_recall:.3f}",
        )
    return GateResult(
        GATE_OCR_UPWARD_ANGLE,
        True,
        f"ocr_char_recall={sample.ocr_char_recall:.3f} at elevation "
        f"{sample.sign_elevation_angle_rad:.3f} rad from {sample.mount_height_m:.2f} m mount",
    )


def gate_legs_first_reid(
    sample: LowViewpointSample,
    thresholds: LowViewpointThresholds | None = None,
) -> GateResult:
    """ReID must survive legs-first / truncated-torso appearance at 35 cm."""

    thr = thresholds or LowViewpointThresholds()
    if not _mount_ok(sample, thr):
        return GateResult(
            GATE_LEGS_FIRST_REID,
            False,
            f"mount_height_m={sample.mount_height_m:.3f} not dog-height nominal",
        )
    if sample.legs_visible_fraction < thr.min_legs_visible_fraction:
        return GateResult(
            GATE_LEGS_FIRST_REID,
            False,
            f"legs_visible_fraction={sample.legs_visible_fraction:.3f} < "
            f"{thr.min_legs_visible_fraction:.3f} (not a legs-first stress case)",
        )
    if not sample.is_legs_first:
        return GateResult(
            GATE_LEGS_FIRST_REID,
            False,
            "torso dominates legs — not a legs-first viewpoint failure mode",
        )
    if thr.require_reid_top1 and not sample.reid_top1_correct:
        return GateResult(
            GATE_LEGS_FIRST_REID,
            False,
            "reid_top1_correct=False under legs-first visibility",
        )
    return GateResult(
        GATE_LEGS_FIRST_REID,
        True,
        f"reid_top1_correct with legs_visible={sample.legs_visible_fraction:.3f} "
        f"torso_visible={sample.torso_visible_fraction:.3f}",
    )


def gate_vpr_at_35cm(
    sample: LowViewpointSample,
    thresholds: LowViewpointThresholds | None = None,
) -> GateResult:
    """Visual place recognition recall@1 at the 35 cm mount."""

    thr = thresholds or LowViewpointThresholds()
    if not _mount_ok(sample, thr):
        return GateResult(
            GATE_VPR_AT_35CM,
            False,
            f"mount_height_m={sample.mount_height_m:.3f} not within dog-height band",
        )
    if sample.vpr_recall_at_1 < thr.min_vpr_recall_at_1:
        return GateResult(
            GATE_VPR_AT_35CM,
            False,
            f"vpr_recall_at_1={sample.vpr_recall_at_1:.3f} < {thr.min_vpr_recall_at_1:.3f}",
        )
    return GateResult(
        GATE_VPR_AT_35CM,
        True,
        f"vpr_recall_at_1={sample.vpr_recall_at_1:.3f} at mount {sample.mount_height_m:.2f} m",
    )


def gate_curb_height_map_without_d455(
    sample: LowViewpointSample,
    thresholds: LowViewpointThresholds | None = None,
) -> GateResult:
    """Curb from height-map discontinuity with D455 depth dropped."""

    thr = thresholds or LowViewpointThresholds()
    if thr.require_d455_dropped and sample.d455_depth_available:
        return GateResult(
            GATE_CURB_HEIGHT_MAP_NO_D455,
            False,
            "d455_depth_available=True — gate requires D455 dropped",
        )
    if thr.require_curb_from_height_map and not sample.curb_detected_from_height_map:
        return GateResult(
            GATE_CURB_HEIGHT_MAP_NO_D455,
            False,
            "curb_detected_from_height_map=False with D455 dropped",
        )
    return GateResult(
        GATE_CURB_HEIGHT_MAP_NO_D455,
        True,
        "curb detected from height map with D455 depth unavailable",
    )


_GATE_FNS: Mapping[str, Callable[[LowViewpointSample, LowViewpointThresholds | None], GateResult]] = {
    GATE_OCR_UPWARD_ANGLE: gate_ocr_upward_angle,
    GATE_LEGS_FIRST_REID: gate_legs_first_reid,
    GATE_VPR_AT_35CM: gate_vpr_at_35cm,
    GATE_CURB_HEIGHT_MAP_NO_D455: gate_curb_height_map_without_d455,
}


def evaluate_gate(
    gate_id: str,
    sample: LowViewpointSample,
    thresholds: LowViewpointThresholds | None = None,
) -> GateResult:
    if gate_id not in _GATE_FNS:
        raise ValueError(f"unknown low-viewpoint gate_id: {gate_id!r}")
    return _GATE_FNS[gate_id](sample, thresholds)


def evaluate_all_gates(
    sample: LowViewpointSample,
    thresholds: LowViewpointThresholds | None = None,
    *,
    gate_ids: Sequence[str] | None = None,
) -> tuple[GateResult, ...]:
    ids = tuple(gate_ids) if gate_ids is not None else tuple(sorted(LOW_VIEWPOINT_GATE_IDS))
    unknown = set(ids) - LOW_VIEWPOINT_GATE_IDS
    if unknown:
        raise ValueError(f"unknown low-viewpoint gate ids: {sorted(unknown)}")
    return tuple(evaluate_gate(gate_id, sample, thresholds) for gate_id in ids)


def all_passed(results: Sequence[GateResult]) -> bool:
    return all(item.passed for item in results)
