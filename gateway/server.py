"""The bounded local IPC surface: one ``AF_UNIX``/``SOCK_SEQPACKET`` listener.

``SOCK_SEQPACKET`` and not ``SOCK_STREAM`` because the contract is a sequence
of whole, bounded, ordered messages: there is no framing code here to get
wrong, a short read cannot deliver half a command, and an oversized packet is
refused by size rather than by a parser.

Two things happen before a byte is parsed.  The listening socket is created
with mode ``0600`` (owner only), and every accepted connection is named by the
kernel through ``SO_PEERCRED`` and checked against the credential policy.  A
peer the policy does not admit is closed without ever reaching
``decode_gateway_message`` — and without stopping the robot, because it never
held authority to lose.

Anything that *does* parse badly is a different matter: unknown kind, unknown
field, wrong schema version, duplicate JSON key, oversize packet, non-UTF-8
bytes all raise out of the frozen decoder, and the core turns that into an
exact-zero latched stop while the gateway is armed.  There is no permissive
fallback path in this file.
"""

from __future__ import annotations

import os
import selectors
import socket
import stat
import threading
from pathlib import Path

from parcel_robot.bridge.protocol import (
    MAX_GATEWAY_PACKET_BYTES,
    GatewayAcquireV1,
    GatewayCommandV1,
    GatewayMessage,
    GatewayStateQueryV1,
    GatewayStopV1,
    decode_gateway_message,
    encode_gateway_message,
)

from .core import GatewayCoreV1
from .credentials import PeerCredentialError, PeerCredentialV1, read_peer_credential

#: Owner-only. The lease is authenticated, so the socket is not a public door.
SOCKET_MODE = 0o600


class GatewayServerV1:
    def __init__(
        self,
        socket_path: str | Path,
        core: GatewayCoreV1,
        *,
        backlog: int = 8,
        require_peer_credentials: bool = True,
    ) -> None:
        self.socket_path = Path(socket_path)
        self.core = core
        self._backlog = backlog
        self._require_peer_credentials = require_peer_credentials
        self._selector = selectors.DefaultSelector()
        self._listener: socket.socket | None = None
        self._connections: dict[socket.socket, tuple[int, PeerCredentialV1]] = {}
        self._next_connection_id = 1
        self._bound_inode: int | None = None
        self._closed = False

    def serve(self, stop_event: threading.Event) -> None:
        self.open()
        try:
            while not stop_event.is_set():
                events = self._selector.select(timeout=self.core.limits.watchdog_period_s)
                for key, _mask in events:
                    if key.fileobj is self._listener:
                        self._accept()
                    else:
                        self._read(key.fileobj)
                # Belt and braces: the core runs its own watchdog thread, and
                # the serve loop ticks as well, so a wedged thread on either
                # side still leaves a live TTL check.
                self.core.tick()
        finally:
            self.close()

    def open(self) -> None:
        try:
            existing = self.socket_path.lstat()
        except FileNotFoundError:
            existing = None
        if existing is not None:
            if not stat.S_ISSOCK(existing.st_mode):
                raise FileExistsError(f"refusing to replace non-socket path {self.socket_path}")
            self.socket_path.unlink()
        listener = socket.socket(socket.AF_UNIX, socket.SOCK_SEQPACKET)
        listener.setblocking(False)
        listener.bind(str(self.socket_path))
        os.chmod(self.socket_path, SOCKET_MODE)
        listener.listen(self._backlog)
        self._bound_inode = self.socket_path.lstat().st_ino
        self._listener = listener
        self._selector.register(listener, selectors.EVENT_READ)
        self.core.start()

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        for connection in list(self._connections):
            self._close_connection(connection)
        if self._listener is not None:
            self._selector.unregister(self._listener)
            self._listener.close()
            self._listener = None
        self.core.close()
        self._selector.close()
        try:
            metadata = self.socket_path.lstat()
        except FileNotFoundError:
            return
        if self._bound_inode is not None and metadata.st_ino == self._bound_inode:
            self.socket_path.unlink()

    def _accept(self) -> None:
        assert self._listener is not None
        connection, _address = self._listener.accept()
        connection.setblocking(False)
        try:
            peer = read_peer_credential(connection)
        except PeerCredentialError:
            if self._require_peer_credentials:
                self.core.audit.record(
                    "peer_credential_unavailable",
                    boot_epoch=self.core.boot_epoch,
                    phase=self.core.phase.value,
                )
                connection.close()
                return
            peer = PeerCredentialV1(pid=0, uid=os.geteuid(), gid=os.getegid())
        if not self.core.policy.admits_peer(peer):
            self.core.audit.record(
                "peer_credential_refused",
                boot_epoch=self.core.boot_epoch,
                phase=self.core.phase.value,
                peer_uid=peer.uid,
                peer_pid=peer.pid,
            )
            connection.close()
            return
        connection_id = self._next_connection_id
        self._next_connection_id += 1
        self._connections[connection] = (connection_id, peer)
        self._selector.register(connection, selectors.EVENT_READ)
        self.core.audit.record(
            "client_connected",
            boot_epoch=self.core.boot_epoch,
            phase=self.core.phase.value,
            connection_id=connection_id,
            peer_uid=peer.uid,
            peer_pid=peer.pid,
        )
        self._send(connection, self.core.hello())

    def _read(self, fileobj: object) -> None:
        if not isinstance(fileobj, socket.socket):
            return
        connection = fileobj
        entry = self._connections.get(connection)
        if entry is None:
            return
        connection_id, peer = entry
        try:
            packet = connection.recv(MAX_GATEWAY_PACKET_BYTES + 1)
        except (BlockingIOError, InterruptedError):
            return
        except OSError:
            self._close_connection(connection)
            return
        if not packet:
            self._close_connection(connection)
            return
        try:
            message = decode_gateway_message(packet)
            response = self._dispatch(connection_id, peer, message)
        except (TypeError, ValueError) as exc:
            self.core.protocol_fault(connection_id, str(exc))
            self._close_connection(connection)
            return
        if response is not None:
            self._send(connection, response)

    def _dispatch(
        self,
        connection_id: int,
        peer: PeerCredentialV1,
        message: GatewayMessage,
    ) -> GatewayMessage | None:
        if isinstance(message, GatewayAcquireV1):
            return self.core.acquire(connection_id, peer, message)
        if isinstance(message, GatewayCommandV1):
            return self.core.command(connection_id, peer, message)
        if isinstance(message, GatewayStopV1):
            return self.core.explicit_stop(connection_id, peer, message)
        if isinstance(message, GatewayStateQueryV1):
            return self.core.state_query(message)
        raise ValueError(f"client cannot send gateway response kind {message.kind!r}")

    def _send(self, connection: socket.socket, message: GatewayMessage) -> None:
        try:
            connection.sendall(encode_gateway_message(message))
        except (BlockingIOError, BrokenPipeError, OSError):
            self._close_connection(connection)

    def _close_connection(self, connection: socket.socket) -> None:
        entry = self._connections.pop(connection, None)
        if entry is None:
            return
        connection_id, _peer = entry
        try:
            self._selector.unregister(connection)
        except (KeyError, ValueError):
            pass
        connection.close()
        self.core.client_lost(connection_id)
