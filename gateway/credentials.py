"""Kernel-authenticated runtime and stop-only gateway credentials.

HLD §8.8: the gateway has "one robot-network credential and one vendor command
writer" and "one authenticated local client lease".  V1 of the wire contract
(``bridge/protocol.py``) carries no credential, token or nonce field, so
authentication here is composed from the two things that *are* available and
are not forgeable by a message alone:

* the **transport peer credential** — ``SO_PEERCRED`` on the accepted
  ``AF_UNIX``/``SOCK_SEQPACKET`` connection gives the kernel's own answer for
  the peer's pid/uid/gid.  A process that is neither the commissioned runtime
  nor the separately commissioned stop-only principal never reaches the
  protocol layer at all; and
* the **contract identity** — ``GatewayHashesV1`` (config/capability/
  calibration/firmware) must equal this gateway's required hashes exactly, so
  a client built against a different config or capability manifest cannot
  acquire, and ``writer_id`` must be on the launch-time allowlist.

That is peer authentication plus contract authentication, not a challenge/
response: a *replay from the same uid inside the same boot* is defeated by the
monotonic sequence fence in the core, not here.  Adding a signed nonce needs a
V2 message and is recorded as an open protocol question in
``scrum/20260824/task_2/M1_0_STATUS.md``.
"""

from __future__ import annotations

import os
import socket
import struct
from dataclasses import dataclass

from parcel_robot.bridge.protocol import GatewayHashesV1

#: ``struct ucred { pid_t pid; uid_t uid; gid_t gid; }`` — three 32-bit ints.
_UCRED_FORMAT = "3i"
_UCRED_SIZE = struct.calcsize(_UCRED_FORMAT)


class PeerCredentialError(RuntimeError):
    """The kernel would not name the peer. Fail closed; never guess."""


@dataclass(frozen=True)
class PeerCredentialV1:
    pid: int
    uid: int
    gid: int


def peer_credentials_supported() -> bool:
    return hasattr(socket, "SO_PEERCRED")


def read_peer_credential(connection: socket.socket) -> PeerCredentialV1:
    if not peer_credentials_supported():
        raise PeerCredentialError("SO_PEERCRED is unavailable on this platform")
    raw = connection.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, _UCRED_SIZE)
    pid, uid, gid = struct.unpack(_UCRED_FORMAT, raw)
    return PeerCredentialV1(pid=pid, uid=uid, gid=gid)


@dataclass(frozen=True)
class CredentialPolicyV1:
    """Who may connect/STOP, who may lease, and against which contract.

    ``allowed_uids`` is the connection allowlist. Every admitted peer may read
    state and invoke the gateway's unconditional STOP path. ``lease_uids`` is
    the strict subset that may acquire or refresh motion authority. Leaving it
    unset preserves the historical one-principal policy exactly.
    """

    required_hashes: GatewayHashesV1
    allowed_writer_ids: frozenset[str]
    allowed_uids: frozenset[int]
    lease_uids: frozenset[int] | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.required_hashes, GatewayHashesV1):
            raise TypeError("required_hashes must be a GatewayHashesV1")
        if not self.allowed_writer_ids:
            raise ValueError("the writer allowlist may not be empty")
        if not self.allowed_uids:
            raise ValueError("the uid allowlist may not be empty")
        lease_uids = self.allowed_uids if self.lease_uids is None else self.lease_uids
        if not lease_uids:
            raise ValueError("the lease uid allowlist may not be empty")
        if not lease_uids <= self.allowed_uids:
            raise ValueError("lease uids must be a subset of connected uids")
        object.__setattr__(self, "lease_uids", frozenset(lease_uids))

    def admits_peer(self, peer: PeerCredentialV1) -> bool:
        return peer.uid in self.allowed_uids

    def admits_lease_peer(self, peer: PeerCredentialV1) -> bool:
        """Whether this kernel peer may create or refresh positive authority."""

        lease_uids = self.lease_uids
        return lease_uids is not None and peer.uid in lease_uids

    def is_stop_only_peer(self, peer: PeerCredentialV1) -> bool:
        """Whether the peer can observe/STOP but never hold a lease."""

        return self.admits_peer(peer) and not self.admits_lease_peer(peer)

    def admits_writer(self, writer_id: str) -> bool:
        return writer_id in self.allowed_writer_ids

    def admits_hashes(self, hashes: GatewayHashesV1) -> bool:
        return hashes == self.required_hashes


def single_writer_policy(
    *,
    required_hashes: GatewayHashesV1,
    writer_id: str,
    uid: int | None = None,
) -> CredentialPolicyV1:
    """The prototype's policy: one writer id, one uid (this process's, by default)."""

    return CredentialPolicyV1(
        required_hashes=required_hashes,
        allowed_writer_ids=frozenset({writer_id}),
        allowed_uids=frozenset({os.geteuid() if uid is None else uid}),
    )


def writer_with_stop_only_policy(
    *,
    required_hashes: GatewayHashesV1,
    writer_id: str,
    writer_uid: int,
    stop_uid: int,
) -> CredentialPolicyV1:
    """One lease UID plus one distinct observe/latched-STOP-only UID."""

    if isinstance(writer_uid, bool) or not isinstance(writer_uid, int) or writer_uid < 0:
        raise ValueError("writer_uid must be a non-negative integer")
    if isinstance(stop_uid, bool) or not isinstance(stop_uid, int) or stop_uid < 0:
        raise ValueError("stop_uid must be a non-negative integer")
    if writer_uid == stop_uid:
        raise ValueError("stop-only uid must differ from the writer uid")
    return CredentialPolicyV1(
        required_hashes=required_hashes,
        allowed_writer_ids=frozenset({writer_id}),
        allowed_uids=frozenset({writer_uid, stop_uid}),
        lease_uids=frozenset({writer_uid}),
    )
