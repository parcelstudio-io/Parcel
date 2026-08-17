"""Isolated gateway contract and deterministic fake-Sport evidence.

This package is a Wave-0 software/fake boundary.  It is deliberately not
wired into :mod:`parcel_robot.runtime`, the physical controller factory, or a
vendor SDK.  The native, credential-isolated product gateway remains N28.
"""

from .protocol import (
    GATEWAY_PROTOCOL_VERSION,
    MAX_GATEWAY_PACKET_BYTES,
    MAX_LOCAL_TTL_MS,
    GatewayAckV1,
    GatewayAcquireV1,
    GatewayCommandV1,
    GatewayHashesV1,
    GatewayHelloV1,
    GatewayPhaseV1,
    GatewayStateQueryV1,
    GatewayStateV1,
    GatewayStopReportV1,
    GatewayStopV1,
    decode_gateway_message,
    encode_gateway_message,
)

__all__ = [
    "GATEWAY_PROTOCOL_VERSION",
    "MAX_GATEWAY_PACKET_BYTES",
    "MAX_LOCAL_TTL_MS",
    "GatewayAckV1",
    "GatewayAcquireV1",
    "GatewayCommandV1",
    "GatewayHashesV1",
    "GatewayHelloV1",
    "GatewayPhaseV1",
    "GatewayStateQueryV1",
    "GatewayStateV1",
    "GatewayStopReportV1",
    "GatewayStopV1",
    "decode_gateway_message",
    "encode_gateway_message",
]
