"""Low-viewpoint (≈35 cm) gate pack for Parcel K5 (Sol lane).

Pure pass/fail predicates for dog-height failure modes. Sim evidence only —
does not claim real camera validation (HR-4).
"""

from __future__ import annotations

from parcel_robot.low_viewpoint.gates import (
    DOES_NOT_PROVE,
    GATE_CURB_HEIGHT_MAP_NO_D455,
    GATE_LEGS_FIRST_REID,
    GATE_OCR_UPWARD_ANGLE,
    GATE_VPR_AT_35CM,
    LOW_VIEWPOINT_GATE_IDS,
    GateResult,
    LowViewpointSample,
    LowViewpointThresholds,
    all_passed,
    evaluate_all_gates,
    evaluate_gate,
    gate_curb_height_map_without_d455,
    gate_legs_first_reid,
    gate_ocr_upward_angle,
    gate_vpr_at_35cm,
)
from parcel_robot.low_viewpoint.samples import (
    SampleExpectation,
    SamplePack,
    SampleSmokeResult,
    assert_pack_expectations,
    default_samples_path,
    load_sample_pack,
    smoke_default_pack,
    smoke_sample,
)

__all__ = [
    "DOES_NOT_PROVE",
    "GATE_CURB_HEIGHT_MAP_NO_D455",
    "GATE_LEGS_FIRST_REID",
    "GATE_OCR_UPWARD_ANGLE",
    "GATE_VPR_AT_35CM",
    "LOW_VIEWPOINT_GATE_IDS",
    "GateResult",
    "LowViewpointSample",
    "LowViewpointThresholds",
    "SampleExpectation",
    "SamplePack",
    "SampleSmokeResult",
    "all_passed",
    "assert_pack_expectations",
    "default_samples_path",
    "evaluate_all_gates",
    "evaluate_gate",
    "gate_curb_height_map_without_d455",
    "gate_legs_first_reid",
    "gate_ocr_upward_angle",
    "gate_vpr_at_35cm",
    "load_sample_pack",
    "smoke_default_pack",
    "smoke_sample",
]
