"""DetectionMsg Habitat-style noise adapter (Parcel K5 Sol lane).

GT / clean detections → ``contracts.DetectionMsg`` with range cutoff,
``p_detect(distance)``, class confusion, and jitter. No pixels, no EGL.
"""

from __future__ import annotations

from parcel_robot.detection_adapter.adapter import (
    DetectionNoiseAdapter,
    GroundTruthDetection,
    ground_truth_from_detection,
)
from parcel_robot.detection_adapter.noise import (
    DEFAULT_SIM_VOCABULARY,
    DetectionNoiseConfig,
    default_person_confusion,
)
from parcel_robot.detection_adapter.owlv2_onnx import (
    DOES_NOT_PROVE as OWLV2_DOES_NOT_PROVE,
)
from parcel_robot.detection_adapter.owlv2_onnx import (
    OwlV2Detector,
    load_owlv2_detector,
    owlv2_weights_present,
)
from parcel_robot.detection_adapter.owlv2_onnx import (
    default_weights_dir as owlv2_default_weights_dir,
)
from parcel_robot.detection_adapter.owlv2_onnx import (
    onnx_enabled as owlv2_onnx_enabled,
)
from parcel_robot.detection_adapter.pixel_detections import (
    DOES_NOT_PROVE as PIXEL_DETECTIONS_DOES_NOT_PROVE,
)
from parcel_robot.detection_adapter.pixel_detections import (
    CameraExtrinsics,
    Detector,
    LocalizedDetection,
    PixelDetection,
    SegTruthDetector,
    back_project,
    localize_detection,
    localize_frame,
    project,
)
from parcel_robot.detection_adapter.sim_bridge import (
    DOES_NOT_PROVE as SIM_BRIDGE_DOES_NOT_PROVE,
)
from parcel_robot.detection_adapter.sim_bridge import (
    SimTrackObservation,
    bearing_range_from_pose,
    detections_for_agent,
    detections_from_observation,
    label_embedding,
    privileged_gt_from_tracks,
    track_from_owner,
    track_from_semantic_object,
)

__all__ = [
    "DEFAULT_SIM_VOCABULARY",
    "OWLV2_DOES_NOT_PROVE",
    "PIXEL_DETECTIONS_DOES_NOT_PROVE",
    "SIM_BRIDGE_DOES_NOT_PROVE",
    "CameraExtrinsics",
    "DetectionNoiseAdapter",
    "DetectionNoiseConfig",
    "Detector",
    "GroundTruthDetection",
    "LocalizedDetection",
    "OwlV2Detector",
    "PixelDetection",
    "SegTruthDetector",
    "SimTrackObservation",
    "back_project",
    "bearing_range_from_pose",
    "default_person_confusion",
    "detections_for_agent",
    "detections_from_observation",
    "ground_truth_from_detection",
    "label_embedding",
    "load_owlv2_detector",
    "localize_detection",
    "localize_frame",
    "owlv2_default_weights_dir",
    "owlv2_onnx_enabled",
    "owlv2_weights_present",
    "privileged_gt_from_tracks",
    "project",
    "track_from_owner",
    "track_from_semantic_object",
]
