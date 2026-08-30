"""Filesystem reachability and kernel-peer identity for the deployed gateway."""

from __future__ import annotations

import os
import socket
import stat
import subprocess
import sys
import threading
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from gateway import process as process_module
from gateway import server as server_module
from gateway.core import GatewayCoreV1
from gateway.credentials import single_writer_policy
from gateway.limits import default_limits
from gateway.process import BENCH_HASHES
from gateway.seam import cli
from gateway.server import (
    PRIVATE_SOCKET_MODE,
    SHARED_SOCKET_MODE,
    SINGLETON_LOCK_MODE,
    GatewayServerV1,
)
from parcel_robot.bridge.fake_sport import FakeSportServiceV1
from parcel_robot.bridge.protocol import GatewayBodyKindV1

REPO = Path(__file__).resolve().parents[1]
GATEWAY_SERVICE = REPO / "deploy/orin/services/parcel-gateway.service"
RUNTIME_SERVICE = REPO / "deploy/orin/services/parcel-runtime.service"
SERVICES_README = REPO / "deploy/orin/services/README.md"
SHARED_SOCKET = "/run/parcel-gateway/gateway.sock"


def _core() -> GatewayCoreV1:
    sport = FakeSportServiceV1()
    return GatewayCoreV1(
        sport,
        policy=single_writer_policy(
            required_hashes=BENCH_HASHES,
            writer_id="parcel-runtime",
        ),
        limits=default_limits(),
        body_kind=GatewayBodyKindV1.FAKE,
    )


def _fake_settings() -> cli.LaunchSettingsV1:
    args = cli._parser().parse_args(["--disarmed"])
    return cli.settings_from(
        args,
        {
            cli.ARMED_ENV: "0",
            cli.SPORT_ENV: "fake",
            cli.STATE_DIRECTORY_ENV: "/tmp",
            cli.LOGS_DIRECTORY_ENV: "/tmp",
        },
    )


def _vendor_environment() -> dict[str, str]:
    return {
        cli.ARMED_ENV: "0",
        cli.SPORT_ENV: "vendor",
        cli.SOCKET_ENV: "/run/parcel-gateway/gateway.sock",
        cli.AUDIT_LOG_ENV: "/var/log/parcel/gateway/audit.jsonl",
        cli.CLIENT_UID_ENV: str(os.geteuid()),
        cli.CLIENT_GID_ENV: str(os.getegid()),
        cli.STOP_CLIENT_UID_ENV: str(os.geteuid() + 1),
        cli.SOCKET_MODE_ENV: "0660",
        cli.CONFIG_SHA256_ENV: "1" * 64,
        cli.CAPABILITY_SHA256_ENV: "2" * 64,
        cli.CALIBRATION_SHA256_ENV: "3" * 64,
        cli.FIRMWARE_SHA256_ENV: "4" * 64,
        cli.UNITREE_INTERFACE_ENV: "robot0",
        cli.UNITREE_DOMAIN_ID_ENV: "0",
        cli.UNITREE_ALLOWED_MODES_ENV: "0,1",
        cli.UNITREE_ALLOWED_ERROR_CODES_ENV: "0",
        cli.UNITREE_STATE_VELOCITY_FRAME_ENV: "base_link",
        cli.UNITREE_LATERAL_SIGN_ENV: "1",
        cli.UNITREE_YAW_SIGN_ENV: "1",
        cli.UNITREE_AXES_COMMISSIONED_ENV: "true",
        cli.UNITREE_STATE_FRAME_COMMISSIONED_ENV: "true",
        cli.UNITREE_SPORT_STATE_STAMP_MONOTONIC_COMMISSIONED_ENV: "true",
        cli.UNITREE_BATTERY_SOC_PERCENT_COMMISSIONED_ENV: "true",
        cli.UNITREE_MINIMUM_BATTERY_SOC_PERCENT_ENV: "8",
        cli.UNITREE_LOW_STATE_TICK_MONOTONIC_COMMISSIONED_ENV: "true",
    }


def test_fake_launch_keeps_the_private_same_user_default() -> None:
    settings = _fake_settings()
    assert settings.client_uid == os.geteuid()
    assert settings.client_gid == os.getegid()
    assert settings.socket_mode == PRIVATE_SOCKET_MODE
    assert settings.socket_gid is None
    assert cli._policy_from_settings(settings).allowed_uids == frozenset({os.geteuid()})


@pytest.mark.parametrize(
    "missing",
    [cli.CLIENT_UID_ENV, cli.CLIENT_GID_ENV, cli.SOCKET_MODE_ENV],
)
def test_vendor_launch_refuses_a_missing_explicit_client_access_field(missing: str) -> None:
    environ = _vendor_environment()
    del environ[missing]
    args = cli._parser().parse_args(["--disarmed"])
    with pytest.raises(cli.GatewayLaunchError, match="vendor client/socket access"):
        cli.settings_from(args, environ)


def test_vendor_launch_binds_policy_and_socket_to_the_resolved_principal() -> None:
    settings = cli.settings_from(
        cli._parser().parse_args(["--disarmed"]),
        _vendor_environment(),
    )
    assert settings.client_uid == os.geteuid()
    assert settings.client_gid == os.getegid()
    assert settings.socket_mode == SHARED_SOCKET_MODE
    assert settings.socket_gid == os.getegid()
    policy = cli._policy_from_settings(settings)
    assert policy.allowed_uids == frozenset({os.geteuid(), os.geteuid() + 1})
    assert policy.lease_uids == frozenset({os.geteuid()})


def test_named_client_user_and_group_are_resolved_and_membership_checked(monkeypatch) -> None:
    monkeypatch.setattr(
        process_module.pwd,
        "getpwnam",
        lambda name: SimpleNamespace(pw_name=name, pw_uid=1234, pw_gid=4321),
    )
    monkeypatch.setattr(
        process_module.grp,
        "getgrnam",
        lambda name: SimpleNamespace(gr_name=name, gr_gid=4321, gr_mem=[]),
    )
    environ = _vendor_environment()
    environ.pop(cli.CLIENT_UID_ENV)
    environ.pop(cli.CLIENT_GID_ENV)
    environ[cli.CLIENT_USER_ENV] = "parcel-runtime"
    environ[cli.CLIENT_GROUP_ENV] = "parcel-runtime"
    settings = cli.settings_from(cli._parser().parse_args(["--disarmed"]), environ)
    assert (settings.client_uid, settings.client_gid) == (1234, 4321)
    assert settings.socket_gid == 4321


@pytest.mark.parametrize(
    ("mode", "gid"),
    [(0o666, None), (SHARED_SOCKET_MODE, None), (PRIVATE_SOCKET_MODE, 123)],
)
def test_server_refuses_ambiguous_or_broad_socket_access(mode: int, gid: int | None) -> None:
    core = _core()
    try:
        with pytest.raises(ValueError):
            GatewayServerV1("/tmp/not-opened.sock", core, socket_mode=mode, socket_gid=gid)
    finally:
        core.close()


@pytest.mark.skipif(
    os.name != "posix" or not hasattr(socket, "SOCK_SEQPACKET"),
    reason="requires Unix SOCK_SEQPACKET",
)
def test_shared_socket_is_exactly_0660_and_owned_by_the_client_group(tmp_path: Path) -> None:
    path = tmp_path / "gateway.sock"
    core = _core()
    server = GatewayServerV1(
        path,
        core,
        socket_mode=SHARED_SOCKET_MODE,
        socket_gid=os.getegid(),
    )
    try:
        server.open()
        metadata = path.lstat()
        assert metadata.st_mode & 0o777 == SHARED_SOCKET_MODE
        assert metadata.st_gid == os.getegid()
        assert cli._socket_is_listening(path, SHARED_SOCKET_MODE, os.getegid())
        assert not cli._socket_is_listening(path, PRIVATE_SOCKET_MODE, None)
        assert not cli._socket_is_listening(path, SHARED_SOCKET_MODE, metadata.st_gid + 1)
    finally:
        server.close()


@pytest.mark.skipif(
    os.name != "posix" or not hasattr(socket, "SOCK_SEQPACKET"),
    reason="requires Unix SOCK_SEQPACKET",
)
def test_failed_group_assignment_removes_the_socket_and_closes_the_core(
    tmp_path: Path,
    monkeypatch,
) -> None:
    path = tmp_path / "gateway.sock"
    core = _core()
    server = GatewayServerV1(
        path,
        core,
        socket_mode=SHARED_SOCKET_MODE,
        socket_gid=os.getegid(),
    )

    def refuse_group(*_args: object) -> None:
        raise PermissionError("no group")

    monkeypatch.setattr(server_module.os, "chown", refuse_group)
    with pytest.raises(PermissionError, match="no group"):
        server.open()
    assert not path.exists()
    assert core._closed is True


@pytest.mark.skipif(
    os.name != "posix" or not hasattr(socket, "SOCK_SEQPACKET"),
    reason="requires POSIX flock and Unix SOCK_SEQPACKET",
)
def test_live_gateway_listener_cannot_be_displaced_and_lock_is_interprocess(
    tmp_path: Path,
) -> None:
    path = tmp_path / "gateway.sock"
    lock_path = tmp_path / "gateway.sock.lock"
    first = GatewayServerV1(path, _core())
    second = GatewayServerV1(path, _core())
    try:
        first.open()
        bound = path.lstat()
        assert stat.S_IMODE(lock_path.lstat().st_mode) == SINGLETON_LOCK_MODE

        lock_probe = subprocess.run(
            [
                sys.executable,
                "-c",
                (
                    "import fcntl, os, sys; "
                    "fd = os.open(sys.argv[1], os.O_RDWR); "
                    "\ntry: fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)"
                    "\nexcept BlockingIOError: raise SystemExit(0)"
                    "\nraise SystemExit(1)"
                ),
                str(lock_path),
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=5.0,
        )
        assert lock_probe.returncode == 0, lock_probe.stderr

        with pytest.raises(FileExistsError, match="another gateway holds"):
            second.open()
        current = path.lstat()
        assert (current.st_dev, current.st_ino) == (bound.st_dev, bound.st_ino)
    finally:
        second.close()
        first.close()


@pytest.mark.skipif(
    os.name != "posix" or not hasattr(socket, "SOCK_SEQPACKET"),
    reason="requires POSIX flock and Unix SOCK_SEQPACKET",
)
def test_live_listener_without_the_lock_is_refused_by_the_socket_probe(
    tmp_path: Path,
) -> None:
    path = tmp_path / "gateway.sock"
    listener = socket.socket(socket.AF_UNIX, socket.SOCK_SEQPACKET)
    listener.bind(str(path))
    listener.listen(1)
    bound = path.lstat()
    candidate = GatewayServerV1(path, _core())
    try:
        with pytest.raises(FileExistsError, match="live gateway listener"):
            candidate.open()
        current = path.lstat()
        assert (current.st_dev, current.st_ino) == (bound.st_dev, bound.st_ino)
        assert candidate.core._closed is True
    finally:
        candidate.close()
        listener.close()
        path.unlink(missing_ok=True)


@pytest.mark.skipif(
    os.name != "posix" or not hasattr(socket, "SOCK_SEQPACKET"),
    reason="requires POSIX flock and Unix SOCK_SEQPACKET",
)
def test_stale_socket_is_reclaimed_after_stable_connection_refusal(tmp_path: Path) -> None:
    path = tmp_path / "gateway.sock"
    stale = socket.socket(socket.AF_UNIX, socket.SOCK_SEQPACKET)
    stale.bind(str(path))
    stale.close()

    server = GatewayServerV1(path, _core())
    try:
        server.open()
        current = path.lstat()
        assert stat.S_ISSOCK(current.st_mode)
        assert server._bound_identity == (current.st_dev, current.st_ino)
    finally:
        server.close()


@pytest.mark.skipif(
    os.name != "posix" or not hasattr(socket, "SOCK_SEQPACKET"),
    reason="requires POSIX flock and Unix SOCK_SEQPACKET",
)
def test_non_socket_open_failure_releases_the_singleton_lock(tmp_path: Path) -> None:
    path = tmp_path / "gateway.sock"
    path.write_text("do not replace", encoding="utf-8")
    refused = GatewayServerV1(path, _core())

    with pytest.raises(FileExistsError, match="non-socket"):
        refused.open()
    assert path.read_text(encoding="utf-8") == "do not replace"
    assert refused.core._closed is True

    path.unlink()
    replacement = GatewayServerV1(path, _core())
    try:
        replacement.open()
        assert stat.S_ISSOCK(path.lstat().st_mode)
    finally:
        replacement.close()


@pytest.mark.skipif(
    os.name != "posix" or not hasattr(socket, "SOCK_SEQPACKET"),
    reason="requires POSIX flock and Unix SOCK_SEQPACKET",
)
def test_close_does_not_unlink_a_replacement_socket_inode(tmp_path: Path) -> None:
    path = tmp_path / "gateway.sock"
    moved = tmp_path / "original-gateway.sock"
    server = GatewayServerV1(path, _core())
    replacement = socket.socket(socket.AF_UNIX, socket.SOCK_SEQPACKET)
    try:
        server.open()
        path.rename(moved)
        replacement.bind(str(path))
        replacement.listen(1)
        replacement_identity = path.lstat()

        server.close()

        current = path.lstat()
        assert (current.st_dev, current.st_ino) == (
            replacement_identity.st_dev,
            replacement_identity.st_ino,
        )
    finally:
        server.close()
        replacement.close()
        path.unlink(missing_ok=True)
        moved.unlink(missing_ok=True)


def test_systemd_units_share_only_the_commissioned_runtime_group_socket() -> None:
    gateway = GATEWAY_SERVICE.read_text(encoding="utf-8")
    runtime = RUNTIME_SERVICE.read_text(encoding="utf-8")
    socket_environment = f"PARCEL_GATEWAY_SOCKET={SHARED_SOCKET}"
    assert socket_environment in gateway
    assert socket_environment in runtime
    assert "PARCEL_GATEWAY_SOCKET_MODE=0660" in gateway
    assert "PARCEL_GATEWAY_CLIENT_USER=parcel-runtime" in gateway
    assert "PARCEL_GATEWAY_CLIENT_GROUP=parcel-motion" in gateway
    assert "PARCEL_GATEWAY_STOP_CLIENT_USER=parcel-safety" in gateway
    assert "SupplementaryGroups=parcel-motion" in gateway
    assert "SupplementaryGroups=parcel-motion" in runtime
    assert "RuntimeDirectory=parcel-gateway" in gateway
    assert "0666" not in gateway
    assert "0666" not in runtime


def test_gateway_systemd_lifecycle_bounds_cover_the_derived_cleanup_budgets() -> None:
    gateway = GATEWAY_SERVICE.read_text(encoding="utf-8")

    assert gateway.count("TimeoutStartSec=") == 1
    assert gateway.count("TimeoutStopSec=") == 1
    assert "TimeoutStartSec=15" in gateway
    assert "13 s total, with 2 s scheduler margin" in gateway
    assert "TimeoutStopSec=10" in gateway
    assert "8.1 s with shipped defaults" in gateway
    assert "leaves 1.9 s for scheduling" in gateway


def test_gateway_systemd_restart_limits_are_unit_directives() -> None:
    gateway = GATEWAY_SERVICE.read_text(encoding="utf-8")
    unit, service = gateway.split("\n[Service]\n", maxsplit=1)

    assert "[Unit]" in unit
    assert unit.count("StartLimitIntervalSec=300") == 1
    assert unit.count("StartLimitBurst=5") == 1
    assert "StartLimitIntervalSec=" not in service
    assert "StartLimitBurst=" not in service


@pytest.mark.skipif(
    not hasattr(socket, "SOCK_SEQPACKET"),
    reason="requires Unix SOCK_SEQPACKET",
)
def test_readiness_refuses_a_stale_socket_before_this_server_opens(
    tmp_path: Path,
) -> None:
    path = tmp_path / "gateway.sock"
    settings = replace(
        _fake_settings(),
        socket_path=path,
        ready_timeout_s=0.03,
    )
    stale = socket.socket(socket.AF_UNIX, socket.SOCK_SEQPACKET)
    stale.bind(str(path))
    os.chmod(path, PRIVATE_SOCKET_MODE)

    class _Liveness:
        calls = 0

        def announce_ready(self, *, status: str = "") -> bool:
            del status
            self.calls += 1
            return True

        def start(self) -> None:
            raise AssertionError("stale socket started liveness")

    liveness = _Liveness()
    try:
        cli._announce_when_ready(
            liveness,  # type: ignore[arg-type]
            settings,
            "boot-stale",
            threading.Event(),
            threading.Event(),
        )
        assert liveness.calls == 0
    finally:
        stale.close()


def test_deployment_hashes_do_not_claim_observed_robot_or_dds_identity() -> None:
    gateway = GATEWAY_SERVICE.read_text(encoding="utf-8")
    readme = SERVICES_README.read_text(encoding="utf-8")
    deployment_contract = f"{gateway}\n{readme}"

    assert "physical identity hashes" not in deployment_contract
    assert "not bound to the observed robot or DDS" in gateway
    assert "authenticate or encrypt DDS traffic" in readme
    assert "Physical qualification remains blocked" in readme
    assert "launch-provided hashes alone do not satisfy" in readme
