"""The bounded local IPC surface: one ``AF_UNIX``/``SOCK_SEQPACKET`` listener.

``SOCK_SEQPACKET`` and not ``SOCK_STREAM`` because the contract is a sequence
of whole, bounded, ordered messages: there is no framing code here to get
wrong, a short read cannot deliver half a command, and an oversized packet is
refused by size rather than by a parser.

Two things happen before a byte is parsed.  The listening socket is private
(``0600``) by default.  A deployed split-principal gateway may instead opt in
to exactly ``0660`` and an explicit client-group owner; no other access mode is
accepted.  Before inspecting that socket pathname, the process takes a private
sibling ``flock`` for the listener lifetime and probes any existing socket;
only a stable, repeatedly connection-refused inode is reclaimed.  Every
accepted connection is then named by the kernel through
``SO_PEERCRED`` and checked against the credential policy.  A peer the policy
does not admit is closed without ever reaching
``decode_gateway_message`` — and without stopping the robot, because it never
held authority to lose.

Anything that *does* parse badly is a different matter: unknown kind, unknown
field, wrong schema version, duplicate JSON key, oversize packet, non-UTF-8
bytes all raise out of the frozen decoder, and the core turns that into an
exact-zero latched stop while the gateway is armed.  There is no permissive
fallback path in this file.
"""

from __future__ import annotations

import errno
import fcntl
import os
import selectors
import socket
import stat
import threading
import time
from collections.abc import Callable
from pathlib import Path
from types import TracebackType

from parcel_robot.bridge.protocol import (
    MAX_GATEWAY_PACKET_BYTES,
    GatewayAcquireV1,
    GatewayCommandV1,
    GatewayMessage,
    GatewayStateQueryV1,
    GatewayStateQueryV2,
    GatewayStopV1,
    decode_gateway_message,
    encode_gateway_message,
)

from .core import GatewayCoreV1
from .credentials import PeerCredentialError, PeerCredentialV1, read_peer_credential

#: Owner-only is the safe desktop/bench default.
PRIVATE_SOCKET_MODE = 0o600
#: The only deployed split-principal mode: owner and one commissioned group.
SHARED_SOCKET_MODE = 0o660
#: Backwards-compatible name for callers that assert the private default.
SOCKET_MODE = PRIVATE_SOCKET_MODE

#: The singleton file is gateway-internal authority, not a client IPC surface.
SINGLETON_LOCK_MODE = 0o600
#: A live local listener should answer immediately.  A timeout is not evidence
#: that it is stale (a saturated backlog is still a live authority), so only
#: explicit ``ECONNREFUSED`` is eligible for stale cleanup.
_LIVE_SOCKET_PROBE_TIMEOUT_S = 0.2
#: Probe twice so a listener crossing bind/listen cannot be displaced after one
#: transient refusal.  The lock excludes every server that follows this
#: contract; this grace period is for an older/non-cooperating process.
_STALE_SOCKET_PROBE_ATTEMPTS = 2
_STALE_SOCKET_PROBE_INTERVAL_S = 0.025

SocketIdentity = tuple[int, int]


def validate_socket_access(socket_mode: int, socket_gid: int | None) -> None:
    """Validate the complete filesystem access contract before binding.

    ``0660`` without a group silently depends on the gateway's own primary
    group and is therefore not an explicit client-access contract.  Conversely,
    a group on ``0600`` is misleading configuration.  Refuse both.
    """

    if isinstance(socket_mode, bool) or socket_mode not in {
        PRIVATE_SOCKET_MODE,
        SHARED_SOCKET_MODE,
    }:
        raise ValueError("socket_mode must be exactly 0600 or 0660")
    if socket_gid is not None and (
        isinstance(socket_gid, bool) or not isinstance(socket_gid, int) or socket_gid < 0
    ):
        raise ValueError("socket_gid must be a non-negative integer")
    if socket_mode == PRIVATE_SOCKET_MODE and socket_gid is not None:
        raise ValueError("socket_gid must be omitted when socket_mode is 0600")
    if socket_mode == SHARED_SOCKET_MODE and socket_gid is None:
        raise ValueError("socket_gid is required when socket_mode is 0660")


class GatewayServerV1:
    def __init__(
        self,
        socket_path: str | Path,
        core: GatewayCoreV1,
        *,
        backlog: int = 8,
        require_peer_credentials: bool = True,
        socket_mode: int = SOCKET_MODE,
        socket_gid: int | None = None,
    ) -> None:
        validate_socket_access(socket_mode, socket_gid)
        self.socket_path = Path(socket_path)
        self.core = core
        self._backlog = backlog
        self._require_peer_credentials = require_peer_credentials
        self._socket_mode = socket_mode
        self._socket_gid = socket_gid
        self._selector = selectors.DefaultSelector()
        self._listener: socket.socket | None = None
        self._connections: dict[socket.socket, tuple[int, PeerCredentialV1]] = {}
        self._next_connection_id = 1
        self._bound_identity: SocketIdentity | None = None
        # Persistent, sibling and deliberately private.  Do not unlink this
        # file: unlinking a held advisory lock would let another process lock a
        # new inode under the same name.  The containing directory is therefore
        # part of this Linux/POSIX authority boundary.
        self._singleton_lock_path = self.socket_path.with_name(
            f"{self.socket_path.name}.lock"
        )
        self._singleton_lock_fd: int | None = None
        self._closed = False

    def serve(
        self,
        stop_event: threading.Event,
        *,
        opened_event: threading.Event | None = None,
    ) -> None:
        """Serve until stopped, publishing ``opened_event`` only after startup.

        The event is set after :meth:`open` has bound and registered this
        process's listener and started the core. A supervisor can therefore use
        it as a readiness prerequisite without trusting a stale pathname from
        an older process.
        """

        try:
            self.open()
            if opened_event is not None:
                opened_event.set()
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
        if self._closed:
            raise RuntimeError("cannot open a closed gateway server")
        if self._listener is not None or self._singleton_lock_fd is not None:
            raise RuntimeError("gateway server is already open")
        try:
            self._acquire_singleton_lock()
            self._remove_stale_socket_if_safe()
            listener = socket.socket(socket.AF_UNIX, socket.SOCK_SEQPACKET)
            self._listener = listener
            listener.setblocking(False)
            listener.bind(str(self.socket_path))
            metadata = self.socket_path.lstat()
            if not stat.S_ISSOCK(metadata.st_mode):
                raise RuntimeError("bound gateway path is not a socket")
            self._bound_identity = _socket_identity(metadata)
            if self._socket_gid is not None:
                os.chown(self.socket_path, -1, self._socket_gid)
            os.chmod(self.socket_path, self._socket_mode)
            metadata = self.socket_path.lstat()
            if (metadata.st_mode & 0o777) != self._socket_mode:
                raise PermissionError("bound socket mode does not match the requested mode")
            if self._socket_gid is not None and metadata.st_gid != self._socket_gid:
                raise PermissionError("bound socket gid does not match the requested group")
            listener.listen(self._backlog)
            self._selector.register(listener, selectors.EVENT_READ)
            self.core.start()
        except BaseException:
            self.close()
            raise

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        cleanup_errors: list[tuple[BaseException, TracebackType | None]] = []

        def cleanup(action: Callable[[], None]) -> None:
            try:
                action()
            # Teardown must reach the lock release even across cancellation or
            # a faulty resource-specific close hook.
            except BaseException as exc:  # noqa: BLE001
                cleanup_errors.append((exc, exc.__traceback__))

        for connection in list(self._connections):
            cleanup(lambda connection=connection: self._close_connection(connection))
        if self._listener is not None:
            listener = self._listener
            self._listener = None
            try:
                self._selector.unregister(listener)
            except (KeyError, ValueError):
                pass
            cleanup(listener.close)
        cleanup(self.core.close)
        cleanup(self._selector.close)
        cleanup(self._remove_bound_socket)
        # Release last: while close verifies/unlinks its own pathname, a new
        # compliant process must not be able to bind a replacement there.
        cleanup(self._release_singleton_lock)
        if cleanup_errors:
            error, traceback = cleanup_errors[0]
            raise error.with_traceback(traceback)

    def _acquire_singleton_lock(self) -> None:
        flags = os.O_RDWR | os.O_CREAT
        flags |= getattr(os, "O_CLOEXEC", 0)
        flags |= getattr(os, "O_NOFOLLOW", 0)
        lock_fd = os.open(self._singleton_lock_path, flags, SINGLETON_LOCK_MODE)
        try:
            metadata = os.fstat(lock_fd)
            if not stat.S_ISREG(metadata.st_mode):
                raise FileExistsError(
                    f"refusing non-regular gateway lock {self._singleton_lock_path}"
                )
            if metadata.st_uid != os.geteuid():
                raise PermissionError(
                    f"gateway lock is not owned by uid {os.geteuid()}: "
                    f"{self._singleton_lock_path}"
                )
            try:
                fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as exc:
                if exc.errno in {errno.EACCES, errno.EAGAIN}:
                    raise FileExistsError(
                        errno.EEXIST,
                        f"another gateway holds {self._singleton_lock_path}",
                        str(self._singleton_lock_path),
                    ) from exc
                raise
            os.fchmod(lock_fd, SINGLETON_LOCK_MODE)
            current = self._singleton_lock_path.lstat()
            if (
                not stat.S_ISREG(current.st_mode)
                or _socket_identity(current) != _socket_identity(metadata)
            ):
                raise FileExistsError(
                    f"gateway lock path changed while acquiring {self._singleton_lock_path}"
                )
        except BaseException:
            os.close(lock_fd)
            raise
        self._singleton_lock_fd = lock_fd

    def _release_singleton_lock(self) -> None:
        lock_fd = self._singleton_lock_fd
        self._singleton_lock_fd = None
        if lock_fd is None:
            return
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_UN)
        finally:
            os.close(lock_fd)

    def _remove_stale_socket_if_safe(self) -> None:
        try:
            existing = self.socket_path.lstat()
        except FileNotFoundError:
            return
        if not stat.S_ISSOCK(existing.st_mode):
            raise FileExistsError(f"refusing to replace non-socket path {self.socket_path}")
        existing_identity = _socket_identity(existing)

        for attempt in range(_STALE_SOCKET_PROBE_ATTEMPTS):
            probe = socket.socket(socket.AF_UNIX, socket.SOCK_SEQPACKET)
            probe.settimeout(_LIVE_SOCKET_PROBE_TIMEOUT_S)
            try:
                probe.connect(str(self.socket_path))
            except OSError as exc:
                if exc.errno == errno.ENOENT:
                    # The observed inode disappeared.  Do not unlink anything
                    # that may subsequently have appeared under the name.
                    try:
                        self.socket_path.lstat()
                    except FileNotFoundError:
                        return
                    raise FileExistsError(
                        f"gateway socket changed while probing {self.socket_path}"
                    ) from exc
                if exc.errno != errno.ECONNREFUSED:
                    raise FileExistsError(
                        f"cannot prove existing gateway socket is stale: {self.socket_path}"
                    ) from exc
            else:
                raise FileExistsError(
                    errno.EEXIST,
                    f"refusing to replace live gateway listener {self.socket_path}",
                    str(self.socket_path),
                )
            finally:
                probe.close()

            self._same_existing_socket(existing_identity)
            if attempt + 1 < _STALE_SOCKET_PROBE_ATTEMPTS:
                time.sleep(_STALE_SOCKET_PROBE_INTERVAL_S)

        # The same socket inode explicitly refused both connection attempts.
        # Keep the singleton held across this final identity check and unlink.
        self._same_existing_socket(existing_identity)
        self.socket_path.unlink()

    def _same_existing_socket(self, expected: SocketIdentity) -> os.stat_result:
        try:
            current = self.socket_path.lstat()
        except FileNotFoundError as exc:
            raise FileExistsError(
                f"gateway socket disappeared while probing {self.socket_path}"
            ) from exc
        if not stat.S_ISSOCK(current.st_mode) or _socket_identity(current) != expected:
            raise FileExistsError(
                f"gateway socket changed while probing {self.socket_path}"
            )
        return current

    def _remove_bound_socket(self) -> None:
        bound_identity = self._bound_identity
        self._bound_identity = None
        if bound_identity is None:
            return
        try:
            metadata = self.socket_path.lstat()
        except FileNotFoundError:
            return
        if stat.S_ISSOCK(metadata.st_mode) and _socket_identity(metadata) == bound_identity:
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
        if isinstance(message, GatewayStateQueryV2):
            return self.core.state_query_v2(message)
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


def _socket_identity(metadata: os.stat_result) -> SocketIdentity:
    """Return the filesystem identity used for race-safe socket cleanup."""

    return metadata.st_dev, metadata.st_ino
