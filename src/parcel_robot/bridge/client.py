"""Small test client for the isolated N24 fake gateway process."""

from __future__ import annotations

import socket
from pathlib import Path
from typing import Self

from .protocol import (
    MAX_GATEWAY_PACKET_BYTES,
    GatewayAcquireV1,
    GatewayCommandV1,
    GatewayHelloV1,
    GatewayMessage,
    GatewayStateQueryV1,
    GatewayStateV1,
    decode_gateway_message,
    encode_gateway_message,
)


class FakeGatewayClientV1:
    def __init__(self, connection: socket.socket, hello: GatewayHelloV1) -> None:
        self._connection = connection
        self.hello = hello

    @classmethod
    def connect(cls, socket_path: str | Path, *, timeout_s: float = 2.0) -> FakeGatewayClientV1:
        connection = socket.socket(socket.AF_UNIX, socket.SOCK_SEQPACKET)
        connection.settimeout(timeout_s)
        connection.connect(str(socket_path))
        hello = cls._receive_from(connection)
        if not isinstance(hello, GatewayHelloV1):
            connection.close()
            raise TypeError("fake gateway did not start with GatewayHelloV1")
        return cls(connection, hello)

    def request(self, message: GatewayMessage) -> GatewayMessage:
        self._connection.sendall(encode_gateway_message(message))
        return self._receive_from(self._connection)

    def acquire(self, *, writer_id: str, sequence: int = 1, ttl_ms: int = 350) -> GatewayMessage:
        return self.request(
            GatewayAcquireV1(
                writer_id=writer_id,
                boot_epoch=self.hello.boot_epoch,
                sequence=sequence,
                local_ttl_ms=ttl_ms,
                hashes=self.hello.required_hashes,
            )
        )

    def command(
        self,
        *,
        writer_id: str,
        sequence: int,
        vx_mps: float,
        vy_mps: float = 0.0,
        vyaw_rad_s: float = 0.0,
        ttl_ms: int = 350,
    ) -> GatewayMessage:
        return self.request(
            GatewayCommandV1(
                writer_id=writer_id,
                boot_epoch=self.hello.boot_epoch,
                sequence=sequence,
                local_ttl_ms=ttl_ms,
                frame_id="base_link",
                vx_mps=vx_mps,
                vy_mps=vy_mps,
                vyaw_rad_s=vyaw_rad_s,
                task_id="n24-process-proof",
                trace_id="n24-process-proof",
                hashes=self.hello.required_hashes,
            )
        )

    def state(self, *, sequence: int) -> GatewayStateV1:
        response = self.request(GatewayStateQueryV1(sequence=sequence))
        if not isinstance(response, GatewayStateV1):
            raise TypeError(f"expected GatewayStateV1, received {response.kind}")
        return response

    def close(self) -> None:
        self._connection.close()

    @staticmethod
    def _receive_from(connection: socket.socket) -> GatewayMessage:
        packet = connection.recv(MAX_GATEWAY_PACKET_BYTES + 1)
        if not packet:
            raise ConnectionError("fake gateway closed the seqpacket connection")
        return decode_gateway_message(packet)

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()
