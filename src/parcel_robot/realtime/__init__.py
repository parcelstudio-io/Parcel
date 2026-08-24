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

# DEC-IG-1: the eight ``lane`` SYMBOL re-exports (GUARDRAILS, RealtimeLane,
# build_instructions, RealtimeArmingDecision, RealtimeLaneError,
# SinkOwnershipError, TOOL_REFUSAL_OUTPUT, decide_realtime_arming) are gone --
# an AST sweep of src/, tests/, scripts/, tools/ and examples/ found zero
# importers of any of them through this barrel.
#
# The submodule import below is deliberately RETAINED.  Dropping it would stop
# this ``__init__`` from executing lane.py, which is a real structural win
# (lane.py + tool_broker.py, ~6.8k lines, leave the import path and this
# package's import SCC falls 7 -> 5) -- but it flips a documented, test-pinned
# import side effect owned by another card:
#   tools/replay_turn_detection.py:679  (docstring asserting the side effect)
#   tests/test_truth1_texts.py::test_the_offline_modes_reach_lane_and_never_reach_ws_transport
# Both are outside this card's OWNS, so the side effect is preserved here and
# the decision is handed on.  See scrum/20260823/task_15/DECIG1_STATUS.md.
from . import lane
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
    SpeakerLabel,
    VoiceArmingDecision,
    VoiceIdentityError,
    VoiceIdentityGate,
    VoiceVerdict,
    gate_decision,
    gates_kind,
    speaker_label,
)

__all__ = [
    "KIND_CLOSED_INTENT",
    "KIND_EMERGENCY",
    "KIND_FOLLOW",
    "KIND_HOLD",
    "KIND_NONE",
    "SPEND_LEDGER_NAME",
    "IngressScan",
    "MalformedEvent",
    "MonthToDateSpend",
    "RealtimeConfig",
    "RealtimeConfigError",
    "RealtimeProtocolError",
    "RealtimeTranscriptOutcome",
    "SpeakerLabel",
    "SpendLedger",
    "Transport",
    "TransportClosed",
    "UnknownEventType",
    "VoiceArmingDecision",
    "VoiceIdentityError",
    "VoiceIdentityGate",
    "VoiceVerdict",
    "default_realtime_config",
    "gate_decision",
    "gates_kind",
    "lane",
    "load_realtime_config",
    "month_key",
    "normalize",
    "parse_server_event",
    "realtime_config_from_mapping",
    "resolve_realtime_config_path",
    "resolve_spend_ledger_path",
    "scan",
    "speaker_label",
    "transport_pair",
]
