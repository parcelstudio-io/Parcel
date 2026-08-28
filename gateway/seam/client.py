"""Compatibility import for the product-owned motion-gateway client.

The Unix client is packaged with :mod:`parcel_robot` because the product uses
it to cross the process boundary.  ``parcel-gateway`` already depends on the
product distribution for the shared wire contract, so this historical import
path can re-export the client without reversing the dependency direction.
"""

from parcel_robot.bridge.gateway_client import (
    BODY_FRAME_V1,
    LOCAL_DEADLINE_MARGIN_S,
    ArmResultV1,
    CommandResultV1,
    ConnectResultV1,
    GatewayAuthorityError,
    GatewayIdentityV1,
    GatewayProtocolError,
    GatewayUnavailableError,
    MotionGatewayClientV1,
    MotionGatewayError,
    MotionStateV1,
    StopResultV1,
)

__all__ = [
    "BODY_FRAME_V1",
    "LOCAL_DEADLINE_MARGIN_S",
    "ArmResultV1",
    "CommandResultV1",
    "ConnectResultV1",
    "GatewayAuthorityError",
    "GatewayIdentityV1",
    "GatewayProtocolError",
    "GatewayUnavailableError",
    "MotionGatewayClientV1",
    "MotionGatewayError",
    "MotionStateV1",
    "StopResultV1",
]
