"""A bench client for the M1-0 gateway, and the SIGKILL subject for the process proof.

This is the *client* half of the seam only far enough to exercise the gateway:
the product's real client is a later card.  It exists here so the suite can
speak V1 over a real ``SOCK_SEQPACKET`` connection — including deliberately
malformed bytes, which is why :meth:`BenchGatewayClientV1.send_raw` bypasses
the DTOs entirely.

As a CLI it acquires the lease and then refreshes a nonzero command at the
control rate until something kills it.  Refreshing (rather than sending one
command and sleeping forever) is what makes the process proof deterministic:
the TTL never expires on its own, so when the test sends ``SIGKILL`` the only
cause available for the stop that follows is ``client_disconnected``.
"""

from __future__ import annotations

import argparse
import json
import socket
import time
from pathlib import Path
from typing import TYPE_CHECKING

from parcel_robot.bridge.protocol import (
    MAX_GATEWAY_PACKET_BYTES,
    GatewayAckDispositionV1,
    GatewayAckV1,
    GatewayAcquireV1,
    GatewayCommandV1,
    GatewayHashesV1,
    GatewayHelloV1,
    GatewayMessage,
    GatewayStateQueryV1,
    GatewayStateQueryV2,
    GatewayStateV1,
    GatewayStateV2,
    GatewayStopV1,
    decode_gateway_message,
    encode_gateway_message,
)

# ``typing.Self`` is 3.11+ and the dog's Orin NX runs JetPack's CPython 3.10
# (the same reason ``bridge/client.py`` carries this fence, card HW-1). This
# module opens with ``from __future__ import annotations``, so the one use of
# the name — the return annotation of ``__enter__`` — is a string at runtime
# and no ``typing.Self`` object is ever built.
if TYPE_CHECKING:  # pragma: no cover - annotations only; never evaluated at runtime
    from typing import Self


class BenchGatewayClientV1:
    def __init__(self, connection: socket.socket, hello: GatewayHelloV1) -> None:
        self._connection = connection
        self.hello = hello

    @classmethod
    def connect(
        cls,
        socket_path: str | Path,
        *,
        timeout_s: float = 2.0,
    ) -> BenchGatewayClientV1:
        connection = socket.socket(socket.AF_UNIX, socket.SOCK_SEQPACKET)
        connection.settimeout(timeout_s)
        connection.connect(str(socket_path))
        hello = cls._receive_from(connection)
        if not isinstance(hello, GatewayHelloV1):
            connection.close()
            raise TypeError("gateway did not open with GatewayHelloV1")
        return cls(connection, hello)

    @property
    def boot_epoch(self) -> str:
        return self.hello.boot_epoch

    @property
    def hashes(self) -> GatewayHashesV1:
        return self.hello.required_hashes

    def send(self, message: GatewayMessage) -> None:
        self._connection.sendall(encode_gateway_message(message))

    def send_raw(self, packet: bytes) -> None:
        """Bypass the DTOs. Used only to prove the decoder fails closed."""

        self._connection.sendall(packet)

    def receive(self) -> GatewayMessage:
        return self._receive_from(self._connection)

    def request(self, message: GatewayMessage) -> GatewayMessage:
        self.send(message)
        return self.receive()

    def acquire(
        self,
        *,
        writer_id: str,
        sequence: int = 1,
        ttl_ms: int = 350,
        boot_epoch: str | None = None,
        hashes: GatewayHashesV1 | None = None,
    ) -> GatewayMessage:
        return self.request(
            GatewayAcquireV1(
                writer_id=writer_id,
                boot_epoch=self.boot_epoch if boot_epoch is None else boot_epoch,
                sequence=sequence,
                local_ttl_ms=ttl_ms,
                hashes=self.hashes if hashes is None else hashes,
            )
        )

    def command(
        self,
        *,
        writer_id: str,
        sequence: int,
        vx_mps: float = 0.0,
        vy_mps: float = 0.0,
        vyaw_rad_s: float = 0.0,
        ttl_ms: int = 350,
        boot_epoch: str | None = None,
        hashes: GatewayHashesV1 | None = None,
        task_id: str = "m1-0-bench",
        trace_id: str = "m1-0-bench",
    ) -> GatewayMessage:
        return self.request(
            GatewayCommandV1(
                writer_id=writer_id,
                boot_epoch=self.boot_epoch if boot_epoch is None else boot_epoch,
                sequence=sequence,
                local_ttl_ms=ttl_ms,
                frame_id="base_link",
                vx_mps=vx_mps,
                vy_mps=vy_mps,
                vyaw_rad_s=vyaw_rad_s,
                task_id=task_id,
                trace_id=trace_id,
                hashes=self.hashes if hashes is None else hashes,
            )
        )

    def stop(
        self,
        *,
        writer_id: str,
        sequence: int,
        reason: str = "bench_stop",
        emergency: bool = False,
    ) -> GatewayMessage:
        return self.request(
            GatewayStopV1(
                writer_id=writer_id,
                boot_epoch=self.boot_epoch,
                sequence=sequence,
                reason=reason,
                emergency=emergency,
            )
        )

    def state(self, *, sequence: int) -> GatewayStateV1:
        response = self.request(GatewayStateQueryV1(sequence=sequence))
        if not isinstance(response, GatewayStateV1):
            raise TypeError(f"expected GatewayStateV1, received {response.kind}")
        return response

    def state_v2(self, *, sequence: int) -> GatewayStateV2:
        response = self.request(GatewayStateQueryV2(sequence=sequence))
        if not isinstance(response, GatewayStateV2):
            raise TypeError(f"expected GatewayStateV2, received {response.kind}")
        return response

    def close(self) -> None:
        self._connection.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()

    @staticmethod
    def _receive_from(connection: socket.socket) -> GatewayMessage:
        packet = connection.recv(MAX_GATEWAY_PACKET_BYTES + 1)
        if not packet:
            raise ConnectionError("gateway closed the seqpacket connection")
        return decode_gateway_message(packet)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--socket", required=True)
    parser.add_argument("--writer-id", default="m1-0-bench-client")
    parser.add_argument("--vx-mps", type=float, default=0.04)
    parser.add_argument("--ttl-ms", type=int, default=350)
    parser.add_argument("--hz", type=float, default=50.0)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    client = BenchGatewayClientV1.connect(args.socket)
    acquired = client.acquire(writer_id=args.writer_id, sequence=1, ttl_ms=args.ttl_ms)
    if (
        not isinstance(acquired, GatewayAckV1)
        or acquired.disposition is not GatewayAckDispositionV1.ACCEPTED
    ):
        raise RuntimeError(f"gateway acquire failed: {acquired}")
    sequence = 2
    period = 1.0 / args.hz
    announced = False
    while True:
        admitted = client.command(
            writer_id=args.writer_id,
            sequence=sequence,
            vx_mps=args.vx_mps,
            ttl_ms=args.ttl_ms,
        )
        if (
            not isinstance(admitted, GatewayAckV1)
            or admitted.disposition is not GatewayAckDispositionV1.ACCEPTED
        ):
            raise RuntimeError(f"gateway command failed: {admitted}")
        if not announced:
            print(
                json.dumps(
                    {
                        "event": "nonzero_admitted",
                        "boot_epoch": client.boot_epoch,
                        "ack_scope": admitted.ack_scope,
                    },
                    sort_keys=True,
                ),
                flush=True,
            )
            announced = True
        sequence += 1
        time.sleep(period)


if __name__ == "__main__":  # pragma: no cover - exercised as a subprocess
    raise SystemExit(main())
