"""OpenAI Realtime conversational lane — R1 slice (fake-first, offline).

R1 is deliberately small and entirely credential-free. Everything here runs
against :class:`~parcel_robot.realtime.fake_server.FakeRealtimeServer` over an
in-process transport pair; the live WebSocket transport is R1.5 and is a new
implementation of :class:`~parcel_robot.realtime.transport.Transport`, not an
edit to the lane.

Flag-off is *file absent*: with no ``configs/realtime.yaml`` the lane is not
constructed and the runtime boots byte-identically.
"""

from __future__ import annotations

from .config import (
    RealtimeConfig,
    RealtimeConfigError,
    default_realtime_config,
    load_realtime_config,
    realtime_config_from_mapping,
    resolve_realtime_config_path,
)
from .ingress import (
    KIND_CLOSED_INTENT,
    KIND_EMERGENCY,
    KIND_FOLLOW,
    KIND_HOLD,
    KIND_NONE,
    IngressScan,
    RealtimeTranscriptOutcome,
    normalize,
    scan,
)
from .lane import (
    GUARDRAILS,
    TOOL_REFUSAL_OUTPUT,
    RealtimeArmingDecision,
    RealtimeLane,
    RealtimeLaneError,
    SinkOwnershipError,
    build_instructions,
    decide_realtime_arming,
)
from .protocol import (
    MalformedEvent,
    RealtimeProtocolError,
    UnknownEventType,
    parse_server_event,
)
from .spend_ledger import (
    SPEND_LEDGER_NAME,
    MonthToDateSpend,
    SpendLedger,
    month_key,
    resolve_spend_ledger_path,
)
from .transport import Transport, TransportClosed, transport_pair
from .voice_identity import (
    VoiceArmingDecision,
    VoiceIdentityError,
    VoiceIdentityGate,
    VoiceVerdict,
    gate_decision,
    gates_kind,
)

__all__ = [
    "GUARDRAILS",
    "KIND_CLOSED_INTENT",
    "KIND_EMERGENCY",
    "KIND_FOLLOW",
    "KIND_HOLD",
    "KIND_NONE",
    "SPEND_LEDGER_NAME",
    "TOOL_REFUSAL_OUTPUT",
    "IngressScan",
    "MalformedEvent",
    "MonthToDateSpend",
    "RealtimeArmingDecision",
    "RealtimeConfig",
    "RealtimeConfigError",
    "RealtimeLane",
    "RealtimeLaneError",
    "RealtimeProtocolError",
    "RealtimeTranscriptOutcome",
    "SinkOwnershipError",
    "SpendLedger",
    "Transport",
    "TransportClosed",
    "UnknownEventType",
    "VoiceArmingDecision",
    "VoiceIdentityError",
    "VoiceIdentityGate",
    "VoiceVerdict",
    "build_instructions",
    "decide_realtime_arming",
    "default_realtime_config",
    "gate_decision",
    "gates_kind",
    "load_realtime_config",
    "month_key",
    "normalize",
    "parse_server_event",
    "realtime_config_from_mapping",
    "resolve_realtime_config_path",
    "resolve_spend_ledger_path",
    "scan",
    "transport_pair",
]
