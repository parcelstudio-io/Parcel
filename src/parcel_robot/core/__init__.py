"""Runtime command arbitration and composition primitives."""

from .activities import ActivityContext, ActivityCoordinator, ActivityRecord, ActivitySubmission
from .arbiter import CommandArbiter, SubmitResult
from .channels import BehaviorChannel, BehaviorChannelRegistry
from .commands import MotionIntent
from .details import FollowDetail, NavigationDetail, SpatialDetail, VoiceDetail
from .motion_shaping import MotionShapingConfig
from .preemption import PreemptionAction, PreemptionDecision, PreemptionTable
from .resume import GenerationTokens, ResumeIntent, ResumeStore
from .velocity_smoother import VelocitySmoother

__all__ = [
    "ActivityContext",
    "ActivityCoordinator",
    "ActivityRecord",
    "ActivitySubmission",
    "BehaviorChannel",
    "BehaviorChannelRegistry",
    "CommandArbiter",
    "FollowDetail",
    "GenerationTokens",
    "MotionIntent",
    "MotionShapingConfig",
    "NavigationDetail",
    "PreemptionAction",
    "PreemptionDecision",
    "PreemptionTable",
    "ResumeIntent",
    "ResumeStore",
    "SpatialDetail",
    "SubmitResult",
    "VelocitySmoother",
    "VoiceDetail",
]
