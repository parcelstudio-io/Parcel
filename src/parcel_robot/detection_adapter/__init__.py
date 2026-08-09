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
from parcel_robot.detection_adapter.sim_bridge import (
    DOES_NOT_PROVE as SIM_BRIDGE_DOES_NOT_PROVE,
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
    "DetectionNoiseAdapter",
    "DetectionNoiseConfig",
    "GroundTruthDetection",
    "SIM_BRIDGE_DOES_NOT_PROVE",
    "SimTrackObservation",
    "bearing_range_from_pose",
    "default_person_confusion",
    "detections_for_agent",
    "detections_from_observation",
    "ground_truth_from_detection",
    "label_embedding",
    "privileged_gt_from_tracks",
    "track_from_owner",
    "track_from_semantic_object",
]
