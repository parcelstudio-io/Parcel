"""Out-of-process GPU perception for the Parcel prototype (card P1-A).

The detector and the SigLIP-2 encoders live in their OWN process, behind an
AF_UNIX socket, and the robot runtime talks to them through
:class:`~parcel_robot.perception_daemon.client.DaemonDetector` — a drop-in for
the existing ``detection_adapter.Detector`` protocol.

Why: OWLv2 costs ~98 ms on an idle GPU and 132–139 ms under this wave's
concurrent load (P0-C; Fable's verification row C-1), against a 300 ms
detection TTL and a 10 Hz reactive loop. In-process, one CUDA stall or one
model reload lands on the control loop. Out of process, the worst case is a
socket read that fails and a detector that reports ``stale`` — which the ingress
already survives.

Start it::

    scripts/launch_detector_daemon.sh --socket /run/user/1000/parcel_perception.sock

Use it::

    from parcel_robot.perception_daemon import DaemonDetector
    ingress.detector = DaemonDetector("/run/user/1000/parcel_perception.sock")

``ingress.py`` is NOT modified by this card: ``CameraIngress`` already accepts
any object satisfying the detector protocol, so the daemon plugs into the seam
that was already there (P1-B owns the ingress).
"""

from __future__ import annotations

from parcel_robot.perception_daemon.client import (
    DaemonClient,
    DaemonDetector,
    DaemonEmbedder,
    DaemonRequestFailed,
)
from parcel_robot.perception_daemon.protocol import (
    MAX_QUERY_PHRASES,
    PROTOCOL_VERSION,
    DaemonUnavailable,
    ProtocolError,
    default_socket_path,
)
from parcel_robot.perception_daemon.server import PerceptionDaemon

__all__ = [
    "MAX_QUERY_PHRASES",
    "PROTOCOL_VERSION",
    "DaemonClient",
    "DaemonDetector",
    "DaemonEmbedder",
    "DaemonRequestFailed",
    "DaemonUnavailable",
    "PerceptionDaemon",
    "ProtocolError",
    "default_socket_path",
]
