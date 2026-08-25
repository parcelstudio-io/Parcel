"""Card DEPLOYABLE-MOTION-SEAM — the installable gateway, the production client,
and bounded vendor I/O, on the desktop bench.

Evidence tier: **desktop/bench**.  Nothing here is on-Orin, target-run,
on-robot, a physical stop, or robot-readiness.  There is no robot, no Unitree
SDK and no vendor firmware in this tree; ``FakeSportServiceV1`` models the
high-level effects the gateway must react to.  "Exact zero at the vendor"
means exact zero in the fake's state.

What this file is required to prove is
``scrum/20260824/task_3/README.md`` §"Required acceptance contract", items 1-9,
adopted verbatim as the definition of done, plus the four named seeded reds.
Each section below names the contract item it discharges.

**It extends card A1's pins rather than re-pinning them.**
``tests/test_m1_0_gateway.py`` is byte-unchanged and stays green; its
import/3.10 pins scan ``gateway/*.py`` (the top level only), so the equivalents
here scan ``gateway/**/*.py`` recursively and are strictly stronger.
"""

from __future__ import annotations

import ast
import json
import os
import signal
import socket
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, replace
from pathlib import Path

import pytest

from gateway import seam as seam_package
from gateway.core import GatewayCoreV1
from gateway.credentials import PeerCredentialV1, single_writer_policy
from gateway.limits import DEFAULT_ACTIVE_REGIME, default_limits
from gateway.process import BENCH_HASHES
from gateway.seam import cli as cli_module
from gateway.seam import client as client_module
from gateway.seam import notify as notify_module
from gateway.seam import vendor_io as vendor_io_module
from gateway.seam.cli import (
    CONSOLE_SCRIPT_NAME,
    PROBE_BUDGET_FACTOR,
    GatewayLaunchError,
    settings_from,
)
from gateway.seam.client import (
    GatewayAuthorityError,
    GatewayUnavailableError,
    MotionGatewayClientV1,
)
from gateway.seam.notify import (
    WATCHDOG_PING_FRACTION,
    GatewayLivenessNotifierV1,
    SdNotifierV1,
    read_supervision,
)
from gateway.seam.vendor_io import BoundedCallLaneV1, BoundedCallOutcomeV1, VendorIoSeamV1
from gateway.server import GatewayServerV1
from parcel_robot.bridge.fake_sport import FakeSportFaultsV1, FakeSportServiceV1

REPO = Path(__file__).resolve().parents[1]
GATEWAY_ROOT = REPO / "gateway"
SERVICE_FILE = REPO / "deploy" / "orin" / "services" / "parcel-gateway.service"
GATEWAY_PYPROJECT = GATEWAY_ROOT / "pyproject.toml"

WRITER = "parcel-runtime"
LOCAL_PEER = PeerCredentialV1(pid=os.getpid(), uid=os.geteuid(), gid=os.getegid())

#: Same shape as A1's bench limits: only the witness budget is shortened so a
#: suite that runs three times stays a suite.  Every other limit is shipped.
SEAM_LIMITS = replace(default_limits(), stop_timeout_s=0.2, stop_retry_s=0.05)

#: How long a *contained* fault may take to produce its bounded stop before the
#: containment claim is considered broken.  Generous on purpose: the claim is a
#: bound, and the bound is ``state_timeout_s + stop_timeout_s`` plus scheduling.
CONTAINMENT_BUDGET_S = 3.0

requires_seqpacket = pytest.mark.skipif(
    os.name != "posix" or not hasattr(socket, "SOCK_SEQPACKET"),
    reason="the motion seam speaks Unix SOCK_SEQPACKET",
)


# --------------------------------------------------------------------------
# the new fault corpus this card adds: hung vendor I/O, each with a witness
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class SeamFaultSeedV1:
    """One seeded fault this card is required to carry, and its named case."""

    seed_id: str
    fault: str
    case: str
    witness: str


#: ``ROBOT_READY_PLAN.md`` §4 work item 4 and README contract item 6: the
#: corpus gains hung-state and hung-stop seeds **with anti-vacuity witnesses**.
#: ``bridge/fixtures/gateway_fault_seeds_v1.json`` is a frozen A-card record
#: and is not this card's to edit, so the new seeds are declared here and
#: :func:`test_every_seam_fault_seed_has_a_named_case_and_a_witness` fails if a
#: seed ever loses its case.
SEAM_FAULT_SEEDS_V1: tuple[SeamFaultSeedV1, ...] = (
    SeamFaultSeedV1(
        seed_id="SMF-001",
        fault="state_never_returns",
        case="test_a_hung_state_call_cannot_wedge_the_watchdog_or_the_stop_path",
        witness="the fake's state() is still inside the call, unreleased, when the core answers",
    ),
    SeamFaultSeedV1(
        seed_id="SMF-002",
        fault="stop_move_never_returns",
        case="test_a_hung_stop_move_still_produces_one_bounded_latched_stop",
        witness="the fake's stop_move() is still inside the call, unreleased, when the core answers",
    ),
    SeamFaultSeedV1(
        seed_id="SMF-003",
        fault="state_and_stop_move_both_never_return",
        case="test_both_vendor_calls_hung_at_once_still_ends_bounded_and_latched",
        witness="both fake calls are still blocked, unreleased, when the core answers",
    ),
    SeamFaultSeedV1(
        seed_id="SMF-004",
        fault="independent_stop_while_vendor_io_is_hung",
        case="test_an_independent_stop_is_still_bounded_while_the_vendor_is_hung",
        witness="the fake calls are still blocked while a second caller's stop returns",
    ),
    SeamFaultSeedV1(
        seed_id="SMF-005",
        fault="stop_move_slower_than_its_budget",
        case="test_a_stop_rpc_that_overruns_its_budget_reads_as_a_failed_stop",
        witness="the delayed stop_move really ran; the classification is unconfirmed and latched",
    ),
)


def test_every_seam_fault_seed_has_a_named_case_and_a_witness() -> None:
    """This suite cannot quietly stop covering the corpus it claims to cover."""

    here = set(globals())
    missing = [seed for seed in SEAM_FAULT_SEEDS_V1 if seed.case not in here]
    assert missing == [], missing
    assert all(seed.witness for seed in SEAM_FAULT_SEEDS_V1)
    assert len({seed.seed_id for seed in SEAM_FAULT_SEEDS_V1}) == len(SEAM_FAULT_SEEDS_V1)


# --------------------------------------------------------------------------
# harness
# --------------------------------------------------------------------------


class HangingSport:
    """A fake vendor whose ``state`` / ``stop_move`` can be made to never return.

    The blocking is *provable*: every blocked call increments a counter before
    it parks on :attr:`released`, and the tests assert the counter moved **and**
    that ``released`` was never set, at the moment the gateway answered.  That
    is the anti-vacuity witness the card requires — without it, "the supervisor
    stayed responsive" could just mean the fault never fired.
    """

    def __init__(self, inner: FakeSportServiceV1) -> None:
        self._inner = inner
        self.hang_state = False
        self.hang_stop = False
        self.stop_delay_s = 0.0
        self.released = threading.Event()
        self._lock = threading.Lock()
        self._blocked_state = 0
        self._blocked_stop = 0
        self._stop_calls = 0

    def __getattr__(self, name: str) -> object:
        return getattr(self._inner, name)

    @property
    def blocked_calls(self) -> int:
        with self._lock:
            return self._blocked_state + self._blocked_stop

    @property
    def blocked_state_calls(self) -> int:
        with self._lock:
            return self._blocked_state

    @property
    def blocked_stop_calls(self) -> int:
        with self._lock:
            return self._blocked_stop

    @property
    def stop_calls(self) -> int:
        with self._lock:
            return self._stop_calls

    def state(self) -> object:
        if self.hang_state:
            with self._lock:
                self._blocked_state += 1
            self.released.wait()
        return self._inner.state()

    def stop_move(self, *, reason: str) -> bool:
        with self._lock:
            self._stop_calls += 1
        if self.hang_stop:
            with self._lock:
                self._blocked_stop += 1
            self.released.wait()
        if self.stop_delay_s:
            time.sleep(self.stop_delay_s)
        return self._inner.stop_move(reason=reason)

    def release(self) -> None:
        self.released.set()


@pytest.fixture
def hanging() -> HangingSport:
    made = HangingSport(FakeSportServiceV1())
    try:
        yield made
    finally:
        made.release()


def _policy(writer_id: str = WRITER) -> object:
    return single_writer_policy(required_hashes=BENCH_HASHES, writer_id=writer_id)


def _core(sport: object, **kwargs: object) -> GatewayCoreV1:
    return GatewayCoreV1(sport, policy=_policy(), limits=SEAM_LIMITS, **kwargs)


def _arm_and_move(core: GatewayCoreV1, sequence: int = 1) -> None:
    from parcel_robot.bridge.protocol import (
        GatewayAckDispositionV1,
        GatewayAcquireV1,
        GatewayCommandV1,
    )

    acquired = core.acquire(
        1,
        LOCAL_PEER,
        GatewayAcquireV1(WRITER, core.boot_epoch, sequence, 350, BENCH_HASHES),
    )
    assert acquired.disposition is GatewayAckDispositionV1.ACCEPTED, acquired.reason
    admitted = core.command(
        1,
        LOCAL_PEER,
        GatewayCommandV1(
            WRITER, core.boot_epoch, sequence + 1, 350, "base_link",
            0.04, 0.0, 0.0, "seam", "seam", BENCH_HASHES,
        ),
    )
    assert admitted.disposition is GatewayAckDispositionV1.ACCEPTED, admitted.reason


def _audit_events(core: GatewayCoreV1, name: str) -> list[object]:
    return list(core.audit.events(name))


@dataclass
class ServedSeam:
    """A gateway core behind a real seqpacket socket, plus its fake vendor."""

    path: Path
    sport: FakeSportServiceV1
    core: GatewayCoreV1
    server: GatewayServerV1
    stop: threading.Event
    thread: threading.Thread

    @classmethod
    def start(cls, path: Path, *, faults: FakeSportFaultsV1 | None = None) -> ServedSeam:
        sport = FakeSportServiceV1(faults=faults)
        core = GatewayCoreV1(sport, policy=_policy(), limits=SEAM_LIMITS)
        server = GatewayServerV1(path, core)
        stop = threading.Event()
        thread = threading.Thread(target=server.serve, args=(stop,), daemon=True)
        made = cls(path=path, sport=sport, core=core, server=server, stop=stop, thread=thread)
        thread.start()
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline:
            if path.exists():
                return made
            time.sleep(0.005)
        raise AssertionError("the gateway socket never appeared")

    def shutdown(self) -> None:
        self.stop.set()
        self.thread.join(timeout=5.0)
        self.sport.close()

    def vendor_velocity(self) -> tuple[float, float, float]:
        sample = self.sport.state()
        return (sample.vx_mps, sample.vy_mps, sample.vyaw_rad_s)

    def vendor_is_exactly_zero(self) -> bool:
        return self.vendor_velocity() == (0.0, 0.0, 0.0)

    def client(self, *, writer_id: str = WRITER) -> MotionGatewayClientV1:
        return MotionGatewayClientV1.connect(self.path, writer_id=writer_id)


@pytest.fixture
def short_dir() -> Path:
    """A SHORT directory. ``AF_UNIX`` paths are capped near 108 bytes."""

    import shutil
    import tempfile

    made = Path(tempfile.mkdtemp(prefix="/tmp/parcel-seam-"))
    try:
        yield made
    finally:
        shutil.rmtree(made, ignore_errors=True)


@pytest.fixture
def served(short_dir: Path) -> ServedSeam:
    made = ServedSeam.start(short_dir / "gw.sock")
    try:
        yield made
    finally:
        made.shutdown()


# --------------------------------------------------------------------------
# contract item 2 — service / CLI parity
# --------------------------------------------------------------------------


def _service_lines() -> list[str]:
    return SERVICE_FILE.read_text(encoding="utf-8").splitlines()


def _service_directive(name: str) -> list[str]:
    prefix = f"{name}="
    return [line[len(prefix):].strip() for line in _service_lines() if line.startswith(prefix)]


def _pyproject() -> dict[str, object]:
    """Read ``gateway/pyproject.toml`` without ``tomllib`` (3.11+; the floor is 3.10)."""

    text = GATEWAY_PYPROJECT.read_text(encoding="utf-8")
    section = ""
    parsed: dict[str, dict[str, str]] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("[") and line.endswith("]"):
            section = line[1:-1]
            parsed.setdefault(section, {})
            continue
        if "=" in line and section:
            key, _, value = line.partition("=")
            parsed[section][key.strip()] = value.strip()
    return parsed


def test_the_distribution_publishes_the_console_script_the_unit_starts() -> None:
    """Contract 2: the installed executable and the unit agree by name."""

    parsed = _pyproject()
    assert parsed["project"]["name"] == '"parcel-gateway"'
    assert parsed["project"]["requires-python"] == '">=3.10"'
    scripts = parsed["project.scripts"]
    assert scripts[CONSOLE_SCRIPT_NAME] == '"gateway.seam.cli:main"'
    exec_start = _service_directive("ExecStart")
    assert len(exec_start) == 1, exec_start
    executable = exec_start[0].split()[0]
    assert Path(executable).name == CONSOLE_SCRIPT_NAME, executable
    # A skeleton pointing at a nonexistent executable cannot pass: the name the
    # unit tests for and the name the unit starts must be the same file.
    assert _service_directive("ExecStartPre") == [f"/usr/bin/test -x {executable}"]


def test_the_unit_start_arguments_are_arguments_the_console_script_accepts() -> None:
    """Contract 2: the unit's ExecStart parses against the real CLI parser."""

    arguments = _service_directive("ExecStart")[0].split()[1:]
    namespace = cli_module._parser().parse_args(arguments)
    assert namespace.disarmed is True
    assert arguments == ["--disarmed"], arguments


def test_the_unit_environment_is_a_launch_profile_the_console_script_understands() -> None:
    """Contract 2: the unit's own Environment= lines drive the real resolver."""

    environ = {}
    for entry in _service_directive("Environment"):
        key, _, value = entry.partition("=")
        environ[key] = value
    assert environ["PARCEL_ARMED"] == "0"
    assert environ["PARCEL_ROLE"] == "gateway"
    # The unit names a body. It names the real one, which refuses to start
    # because no vendor SDK exists — an honest refusal, not a fake body.
    assert environ["PARCEL_GATEWAY_SPORT"] == "vendor"
    environ.update({"STATE_DIRECTORY": "/var/lib/parcel/gateway"})
    environ.update({"LOGS_DIRECTORY": "/var/log/parcel/gateway"})
    args = cli_module._parser().parse_args(["--disarmed"])
    with pytest.raises(GatewayLaunchError) as refusal:
        settings_from(args, environ)
    assert "vendor" in str(refusal.value)


def test_the_unit_directories_are_where_the_console_script_looks() -> None:
    """Contract 2: StateDirectory/LogsDirectory are the socket and audit defaults."""

    assert _service_directive("StateDirectory") == ["parcel/gateway"]
    assert _service_directive("LogsDirectory") == ["parcel/gateway"]
    args = cli_module._parser().parse_args(["--disarmed"])
    settings = settings_from(
        args,
        {
            "PARCEL_ARMED": "0",
            "PARCEL_GATEWAY_SPORT": "fake",
            "STATE_DIRECTORY": "/var/lib/parcel/gateway",
            "LOGS_DIRECTORY": "/var/log/parcel/gateway",
        },
    )
    assert settings.socket_path == Path("/var/lib/parcel/gateway/gateway.sock")
    assert settings.audit_log == Path("/var/log/parcel/gateway/audit.jsonl")
    assert settings.regime_name == DEFAULT_ACTIVE_REGIME
    assert settings.disarmed_asserted is True


def test_the_console_script_has_no_default_body() -> None:
    """A gateway that picks its own body could serve a fake one on a robot."""

    args = cli_module._parser().parse_args(["--disarmed"])
    with pytest.raises(GatewayLaunchError) as refusal:
        settings_from(args, {"PARCEL_ARMED": "0", "STATE_DIRECTORY": "/tmp"})
    assert "no body named" in str(refusal.value)


def test_the_console_script_refuses_to_start_armed() -> None:
    """Contract 5: arming is never a boot property."""

    args = cli_module._parser().parse_args(["--disarmed"])
    with pytest.raises(GatewayLaunchError) as refusal:
        settings_from(
            args,
            {"PARCEL_ARMED": "1", "PARCEL_GATEWAY_SPORT": "fake", "STATE_DIRECTORY": "/tmp"},
        )
    assert "arming is a client transaction" in str(refusal.value)


def test_the_console_script_refuses_an_unknown_regime() -> None:
    args = cli_module._parser().parse_args(["--disarmed"])
    with pytest.raises(GatewayLaunchError):
        settings_from(
            args,
            {
                "PARCEL_GATEWAY_SPORT": "fake",
                "PARCEL_GATEWAY_REGIME": "sprint",
                "STATE_DIRECTORY": "/tmp",
                "LOGS_DIRECTORY": "/tmp",
            },
        )


def test_the_watchdog_ping_period_leaves_margin_under_the_units_watchdogsec() -> None:
    """Contract 2: readiness is not faked, and liveness is not accidentally lost.

    A ping is only sent after a bounded probe of the core lock returns, and a
    *legitimate* stop holds that lock for up to ``stop_timeout_s``.  The worst
    gap between successful pings is therefore ``ping_period + stop_timeout_s``
    and it must stay under the unit's own ``WatchdogSec``.
    """

    watchdog_s = float(_service_directive("WatchdogSec")[0])
    ping_period_s = watchdog_s * WATCHDOG_PING_FRACTION
    shipped = default_limits()
    worst_gap_s = ping_period_s + shipped.stop_timeout_s
    assert worst_gap_s < watchdog_s, (ping_period_s, shipped.stop_timeout_s, watchdog_s)
    # And the probe budget covers a legitimate stop, so a healthy stop never
    # looks like a wedge.
    assert shipped.stop_timeout_s * PROBE_BUDGET_FACTOR > shipped.stop_timeout_s


def test_the_packaging_covers_every_package_directory_in_the_tree() -> None:
    packaged = _pyproject()["tool.setuptools"]["packages"]
    on_disk = {"gateway"} | {
        "gateway." + str(path.parent.relative_to(GATEWAY_ROOT)).replace("/", ".")
        for path in GATEWAY_ROOT.rglob("__init__.py")
        if path.parent != GATEWAY_ROOT and not (set(path.parts) & _TRANSIENT_DIRECTORIES)
    }
    for name in on_disk:
        assert f'"{name}"' in packaged, (name, packaged)


# --------------------------------------------------------------------------
# recursive import / 3.10 pins — A1's rules, applied to the whole tree
# --------------------------------------------------------------------------

#: Every module in the tree, top level and subpackages, and what it may reach.
DEPLOYABLE_SEAM_MODULES = (
    "seam/__init__.py",
    "seam/client.py",
    "seam/notify.py",
    "seam/vendor_io.py",
)
BENCH_SEAM_MODULES = ("seam/cli.py",)

VENDOR_SDK_MARKERS = (
    "unitree_sdk2",
    "unitree_sdk2py",
    "unitree_legged_sdk",
    "unitree",
    "cyclonedds",
    "rclpy",
    "rospy",
)

POST_310_MEMBERS = {
    "datetime": {"UTC"},
    "typing": {
        "Self", "LiteralString", "Never", "NotRequired", "Required", "assert_never",
        "assert_type", "dataclass_transform", "reveal_type", "override", "TypeAliasType",
    },
    "enum": {"StrEnum", "ReprEnum", "verify", "member", "nonmember"},
    "asyncio": {"TaskGroup", "timeout", "Runner", "Barrier"},
    "itertools": {"batched"},
    "contextlib": {"chdir"},
}
POST_310_MODULES = {"tomllib"}


#: Build artefacts a local ``python -m build`` may leave beside the sources.
_TRANSIENT_DIRECTORIES = frozenset({"__pycache__", "build", "dist", ".eggs"})


def _tree_sources() -> dict[str, str]:
    """Every ``.py`` under ``gateway/``, recursively — A1's glob is top level only."""

    return {
        str(path.relative_to(GATEWAY_ROOT)): path.read_text(encoding="utf-8")
        for path in sorted(GATEWAY_ROOT.rglob("*.py"))
        if not (set(path.parts) & _TRANSIENT_DIRECTORIES)
    }


def _imports(source: str, *, runtime_only: bool = False) -> tuple[set[str], list[tuple[str, str]]]:
    tree = ast.parse(source, feature_version=(3, 10))
    guarded: set[int] = set()
    if runtime_only:
        for node in ast.walk(tree):
            if isinstance(node, ast.If) and _is_type_checking_guard(node.test):
                guarded.update(id(inner) for inner in ast.walk(node))
    modules: set[str] = set()
    members: list[tuple[str, str]] = []
    for node in ast.walk(tree):
        if id(node) in guarded:
            continue
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                continue
            module = node.module or ""
            modules.add(module)
            members.extend((module, alias.name) for alias in node.names)
    return modules, members


def _relative_imports(source: str) -> set[str]:
    """``from . import x`` / ``from ..y import z`` — what A1's scanner skips."""

    reached: set[str] = set()
    for node in ast.walk(ast.parse(source, feature_version=(3, 10))):
        if isinstance(node, ast.ImportFrom) and node.level:
            reached.add("." * node.level + (node.module or ""))
    return reached


def _is_type_checking_guard(test: ast.expr) -> bool:
    if isinstance(test, ast.Name):
        return test.id == "TYPE_CHECKING"
    return isinstance(test, ast.Attribute) and test.attr == "TYPE_CHECKING"


def test_the_subpackage_holds_exactly_the_modules_this_card_adds() -> None:
    found = {name for name in _tree_sources() if name.startswith("seam/")}
    assert found == set(DEPLOYABLE_SEAM_MODULES) | set(BENCH_SEAM_MODULES), found


def test_no_vendor_sdk_is_imported_anywhere_in_the_tree_including_subpackages() -> None:
    offenders: dict[str, set[str]] = {}
    for name, source in _tree_sources().items():
        modules, _members = _imports(source)
        hits = {module for module in modules if module.split(".")[0] in VENDOR_SDK_MARKERS}
        if hits:
            offenders[name] = hits
    assert offenders == {}


def test_the_deployable_seam_reaches_exactly_the_frozen_wire_contract() -> None:
    """Contract 3: the production side sees the protocol and stdlib. Nothing else."""

    surface: dict[str, set[str]] = {}
    for name in DEPLOYABLE_SEAM_MODULES:
        modules, _members = _imports(_tree_sources()[name])
        product = {module for module in modules if module.startswith("parcel_robot")}
        if product:
            surface[name] = product
    reached = set().union(*surface.values()) if surface else set()
    assert reached <= {"parcel_robot.bridge.protocol"}, surface
    assert surface.get("seam/client.py") == {"parcel_robot.bridge.protocol"}


def test_the_production_client_cannot_reach_the_vendor_or_the_core() -> None:
    """Contract 3 / stop condition: no runtime caller may bypass the gateway."""

    source = _tree_sources()["seam/client.py"]
    # It imports nothing from this package at all — not ports, not core, not
    # the writer, not the bench client.  The only way out of this module is the
    # Unix socket.
    assert _relative_imports(source) == set()
    modules, _members = _imports(source)
    assert not any(module.startswith("gateway") for module in modules), modules
    assert "parcel_robot.bridge.fake_sport" not in modules


def test_the_gateway_never_reaches_the_product_runtime_or_a_controller() -> None:
    for name, source in _tree_sources().items():
        modules, _members = _imports(source)
        for module in modules:
            assert not module.startswith("parcel_robot.runtime"), (name, module)
            assert not module.startswith("parcel_robot.control"), (name, module)
            assert not module.startswith("parcel_robot.backends"), (name, module)


def test_every_module_in_the_tree_is_python_310_clean() -> None:
    findings: list[tuple[str, str, str]] = []
    for name, source in _tree_sources().items():
        modules, members = _imports(source, runtime_only=True)
        for module in modules:
            if module.split(".")[0] in POST_310_MODULES:
                findings.append((name, module, "module"))
        for module, member in members:
            if member in POST_310_MEMBERS.get(module, set()):
                findings.append((name, f"{module}.{member}", "member"))
    assert findings == []


def test_only_the_bench_modules_may_import_the_fake_vendor() -> None:
    """Prose may *describe* the fake; only the bench modules may reach it.

    ``gateway/__init__.py`` and ``gateway/seam/__init__.py`` both explain what
    a fake-Sport bench run does and does not prove, so this is an import scan
    (including the lazy in-function ones), not a text scan.
    """

    allowed = set(BENCH_SEAM_MODULES) | {"process.py", "bench_client.py"}
    reachers = set()
    for name, source in _tree_sources().items():
        for node in ast.walk(ast.parse(source, feature_version=(3, 10))):
            module = ""
            if isinstance(node, ast.ImportFrom) and not node.level:
                module = node.module or ""
            elif isinstance(node, ast.Import):
                module = ",".join(alias.name for alias in node.names)
            if "fake_sport" in module:
                reachers.add(name)
    assert reachers <= allowed, reachers - allowed
    # Exactly the two modules that BUILD a body, and no third.
    assert reachers == {"process.py", "seam/cli.py"}, reachers


# --------------------------------------------------------------------------
# contract item 3 — the production client boundary
# --------------------------------------------------------------------------

#: The whole public surface. Adding to this list is a contract change.
CLIENT_PUBLIC_SURFACE = frozenset(
    {
        "connect", "close", "reconnect",
        "acquire", "command", "stop",
        "state", "last_stop_report",
        "identity", "boot_epoch", "writer_id", "armed",
        "authority_deadline_monotonic_s",
    }
)

#: What a *bench* client is allowed to have and a production one is not.
BENCH_ONLY_METHODS = frozenset({"send_raw", "send", "request", "receive"})


def test_the_client_public_surface_is_exactly_the_bounded_contract() -> None:
    public = {
        name
        for name in dir(MotionGatewayClientV1)
        if not name.startswith("_")
    }
    assert public == CLIENT_PUBLIC_SURFACE, public ^ CLIENT_PUBLIC_SURFACE


def test_the_client_has_no_raw_packet_or_malformed_message_escape_hatch() -> None:
    """Contract 3 — and the check is not vacuous: the bench client *does* have one."""

    from gateway.bench_client import BenchGatewayClientV1

    for name in BENCH_ONLY_METHODS:
        assert not hasattr(MotionGatewayClientV1, name), name
    # anti-vacuity: the role split is real, not an absence nobody has.
    assert hasattr(BenchGatewayClientV1, "send_raw")
    assert hasattr(BenchGatewayClientV1, "send")


@requires_seqpacket
def test_the_client_owns_no_vendor_object(served: ServedSeam) -> None:
    with served.client() as client:
        client.acquire()
        held = list(vars(client).values())
    for value in held:
        assert not isinstance(value, FakeSportServiceV1), value
        assert not hasattr(value, "stop_move"), value
        assert not hasattr(value, "acquire_writer"), value


# --------------------------------------------------------------------------
# contract item 4 — end-to-end authority over the real socket
# --------------------------------------------------------------------------


@requires_seqpacket
def test_arm_command_and_explicit_stop_over_the_unix_socket(served: ServedSeam) -> None:
    with served.client() as client:
        assert client.armed is False
        armed = client.acquire()
        assert armed.armed is True, armed.reason
        assert client.armed is True
        admitted = client.command(vx_mps=0.04)
        assert admitted.admitted is True, admitted.reason
        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline and served.vendor_is_exactly_zero():
            time.sleep(0.005)
        assert not served.vendor_is_exactly_zero(), "the vendor never moved"
        stopped = client.stop(reason="seam_test")
        assert stopped.confirmed_stationary is True, stopped
        assert served.vendor_is_exactly_zero()
        assert client.armed is False
        with pytest.raises(GatewayAuthorityError):
            client.command(vx_mps=0.04)


@requires_seqpacket
def test_a_command_is_refused_before_any_acquire(served: ServedSeam) -> None:
    with served.client() as client:
        with pytest.raises(GatewayAuthorityError):
            client.command(vx_mps=0.04)
        assert served.vendor_is_exactly_zero()
        assert served.core.active_writer is None


@requires_seqpacket
def test_the_client_refuses_to_command_once_its_own_authority_lapsed(
    served: ServedSeam,
) -> None:
    """The client fails closed locally, before a byte reaches the wire."""

    with served.client() as client:
        armed = client.acquire(local_ttl_ms=20)
        assert armed.armed is True
        time.sleep(0.05)
        assert client.armed is False
        with pytest.raises(GatewayAuthorityError) as refusal:
            client.command(vx_mps=0.04)
        assert "lapsed" in str(refusal.value)
        # And a fresh explicit acquire is what restores it.
        assert client.acquire().armed is True


@requires_seqpacket
def test_a_reconnect_is_disarmed_and_the_next_command_needs_a_new_acquire(
    served: ServedSeam,
) -> None:
    """Contract 5 / seeded red 1's positive half."""

    with served.client() as client:
        client.acquire()
        client.command(vx_mps=0.04)
        assert_reconnect_leaves_the_client_disarmed(client, served)


@requires_seqpacket
def test_client_death_stops_the_body_and_the_next_command_is_refused(
    served: ServedSeam,
) -> None:
    client = served.client()
    client.acquire()
    client.command(vx_mps=0.04)
    deadline = time.monotonic() + 2.0
    while time.monotonic() < deadline and served.vendor_is_exactly_zero():
        time.sleep(0.005)
    assert not served.vendor_is_exactly_zero()
    client.close()
    deadline = time.monotonic() + 3.0
    while time.monotonic() < deadline and not served.vendor_is_exactly_zero():
        time.sleep(0.005)
    assert served.vendor_is_exactly_zero()
    assert served.core.active_writer is None
    with served.client() as fresh, pytest.raises(GatewayAuthorityError):
        fresh.command(vx_mps=0.04)


@requires_seqpacket
def test_ttl_expiry_stops_the_body_and_leaves_no_lease(served: ServedSeam) -> None:
    with served.client() as client:
        client.acquire(local_ttl_ms=60)
        client.command(vx_mps=0.04, local_ttl_ms=60)
        deadline = time.monotonic() + 3.0
        while time.monotonic() < deadline and served.core.stop_sequence < 2:
            time.sleep(0.005)
        assert served.core.stop_sequence >= 2
        assert served.vendor_is_exactly_zero()
        assert served.core.active_writer is None
        assert served.core.last_stop_reason == "local_ttl_expired"
        with pytest.raises(GatewayAuthorityError):
            client.command(vx_mps=0.04)


@requires_seqpacket
def test_stale_feedback_stops_the_body_and_ends_authority(short_dir: Path) -> None:
    made = ServedSeam.start(short_dir / "gw.sock")
    try:
        with made.client() as client:
            client.acquire()
            client.command(vx_mps=0.04)
            made.sport.faults = FakeSportFaultsV1(stale_state_by_s=1.0)
            deadline = time.monotonic() + 3.0
            while time.monotonic() < deadline and made.core.stop_sequence < 2:
                time.sleep(0.005)
            assert made.core.stop_sequence >= 2
            assert made.core.active_writer is None
            assert made.core.last_stop_reason in {"state_stale", "state_frozen"}
            made.sport.faults = FakeSportFaultsV1()
            # The client's own deadline has not lapsed, so it still sends; the
            # gateway refuses, and *that* is what ends the client's authority.
            refused = client.command(vx_mps=0.04)
            assert refused.admitted is False
            assert refused.reason in {"gateway_disarmed", "gateway_latched"}
            assert client.armed is False
            # From here nothing but a fresh explicit arm gets a command out.
            with pytest.raises(GatewayAuthorityError):
                client.command(vx_mps=0.04)
    finally:
        made.shutdown()


@requires_seqpacket
def test_an_old_boot_epoch_is_refused_and_the_body_ends_at_exact_zero(
    served: ServedSeam,
) -> None:
    """Contract 4: an old epoch on the wire is refused through the production client."""

    with served.client() as client:
        client.acquire()
        client.command(vx_mps=0.04)
        # WHITE BOX, deliberately: the production client has no API for
        # forging an epoch, which is the point of contract item 3.  Repinning
        # its cached hello is how this suite drives the *gateway's* refusal
        # through the production encoder rather than a bench one.
        stale = replace(client._hello, boot_epoch="0" * 32)
        client._hello = stale
        client._armed = True
        client._deadline = time.monotonic() + 1.0
        result = client.command(vx_mps=0.04)
        assert result.admitted is False
        assert result.reason == "boot_epoch_mismatch"
        assert served.vendor_is_exactly_zero()
        assert served.core.active_writer is None


@requires_seqpacket
def test_a_regressed_sequence_is_refused_and_the_body_ends_at_exact_zero(
    served: ServedSeam,
) -> None:
    with served.client() as client:
        client.acquire()
        client.command(vx_mps=0.04)
        # White box for the same reason as above.
        client._sequence = 0
        client._armed = True
        client._deadline = time.monotonic() + 1.0
        result = client.command(vx_mps=0.04)
        assert result.admitted is False
        assert result.reason == "client_sequence_not_increasing"
        assert served.vendor_is_exactly_zero()
        assert served.core.active_writer is None


@requires_seqpacket
def test_a_gateway_restart_is_a_new_boot_epoch_and_never_resumes(short_dir: Path) -> None:
    """Contract 5, and seeded red 2's positive half."""

    path = short_dir / "gw.sock"
    first = ServedSeam.start(path)
    try:
        with first.client() as client:
            client.acquire()
            client.command(vx_mps=0.04)
            first_epoch = client.boot_epoch
    finally:
        first.shutdown()
    second = ServedSeam.start(path)
    try:
        assert_restart_is_a_new_boot_epoch(first_epoch, second.core.boot_epoch)
        with second.client() as fresh:
            assert fresh.boot_epoch != first_epoch
            assert fresh.armed is False
            assert second.core.active_writer is None
            assert second.vendor_is_exactly_zero()
            with pytest.raises(GatewayAuthorityError):
                fresh.command(vx_mps=0.04)
            # Only an explicit arm transaction brings authority back.
            assert fresh.acquire().armed is True
    finally:
        second.shutdown()


@requires_seqpacket
def test_a_gateway_death_leaves_the_client_disarmed_and_unable_to_command(
    short_dir: Path,
) -> None:
    path = short_dir / "gw.sock"
    made = ServedSeam.start(path)
    client = made.client()
    try:
        client.acquire()
        client.command(vx_mps=0.04)
        made.shutdown()
        with pytest.raises((GatewayUnavailableError, GatewayAuthorityError)):
            for _ in range(20):
                client.command(vx_mps=0.04)
                time.sleep(0.01)
        assert client.armed is False
    finally:
        client.close()


# --------------------------------------------------------------------------
# contract item 6 — hung vendor I/O containment, with anti-vacuity witnesses
# --------------------------------------------------------------------------


def _answers_within(call: object, budget_s: float) -> bool:
    """Run ``call`` on its own thread; True if it came back inside the budget."""

    done = threading.Event()

    def run() -> None:
        try:
            call()
        finally:
            done.set()

    threading.Thread(target=run, name="seam-probe", daemon=True).start()
    return done.wait(budget_s)


def assert_supervisor_survives_hung_vendor_io(
    core: GatewayCoreV1,
    sport: HangingSport,
    *,
    budget_s: float = CONTAINMENT_BUDGET_S,
) -> None:
    """The shared containment assertion, with its anti-vacuity witness.

    Used by the real cases *and* by the seeded red, so the red proves this
    exact assertion — not a weaker cousin of it — would fail if the seam were
    unbounded.
    """

    assert _answers_within(core.tick, budget_s), (
        "the gateway did not answer inside its budget: a hung vendor call wedged it"
    )
    assert _answers_within(core.state, budget_s), (
        "the gateway could not report state: a hung vendor call wedged it"
    )
    # Anti-vacuity, both halves: the fault really fired, and it is *still*
    # firing at the moment the supervisor answered.
    assert sport.blocked_calls >= 1, "vacuous: no vendor call was ever blocked"
    assert not sport.released.is_set(), "vacuous: the blocked call was released too early"


@requires_seqpacket
def test_a_hung_state_call_cannot_wedge_the_watchdog_or_the_stop_path(
    hanging: HangingSport,
) -> None:
    """SMF-001."""

    core = _core(hanging)
    core.start(watchdog=False)
    try:
        _arm_and_move(core)
        hanging.hang_state = True
        assert_supervisor_survives_hung_vendor_io(core, hanging)
        assert hanging.blocked_state_calls >= 1
        assert core.phase.value == "latched"
        assert core.last_stop_reason == "sport_state_unreadable"
        assert _audit_events(core, "sport_state_timed_out")
        report = core.last_stop_report
        assert report is not None and report.stationary_confirmed is False
    finally:
        hanging.release()
        core.close()


@requires_seqpacket
def test_a_hung_stop_move_still_produces_one_bounded_latched_stop(
    hanging: HangingSport,
) -> None:
    """SMF-002."""

    core = _core(hanging)
    core.start(watchdog=False)
    try:
        _arm_and_move(core)
        hanging.hang_stop = True
        started = time.monotonic()
        assert _answers_within(core.tick, CONTAINMENT_BUDGET_S)
        # Force a stop rather than waiting for a fault to choose one.
        from parcel_robot.bridge.protocol import GatewayStopV1

        assert _answers_within(
            lambda: core.explicit_stop(
                1, LOCAL_PEER, GatewayStopV1(WRITER, core.boot_epoch, 99, "seam", False)
            ),
            CONTAINMENT_BUDGET_S,
        )
        elapsed = time.monotonic() - started
        assert hanging.blocked_stop_calls >= 1, "vacuous: stop_move never blocked"
        assert not hanging.released.is_set(), "vacuous: released too early"
        assert elapsed < CONTAINMENT_BUDGET_S * 2
        assert core.phase.value == "latched"
        report = core.last_stop_report
        assert report is not None
        assert report.stop_rpc_completed is False
        assert report.stationary_confirmed is False
        assert _audit_events(core, "stop_move_timed_out")
    finally:
        hanging.release()
        core.close()


@requires_seqpacket
def test_both_vendor_calls_hung_at_once_still_ends_bounded_and_latched(
    hanging: HangingSport,
) -> None:
    """SMF-003 — the worst case the card names."""

    core = _core(hanging)
    core.start(watchdog=False)
    try:
        _arm_and_move(core)
        hanging.hang_state = True
        hanging.hang_stop = True
        assert_supervisor_survives_hung_vendor_io(core, hanging)
        assert hanging.blocked_state_calls >= 1
        assert hanging.blocked_stop_calls >= 1
        assert core.phase.value == "latched"
        report = core.last_stop_report
        assert report is not None
        assert report.stop_rpc_completed is False
        assert report.stationary_confirmed is False
    finally:
        hanging.release()
        core.close()


@requires_seqpacket
def test_an_independent_stop_is_still_bounded_while_the_vendor_is_hung(
    hanging: HangingSport,
) -> None:
    """SMF-004: a bounded independent stop does not wait for the hung call."""

    from parcel_robot.bridge.protocol import GatewayStopV1

    core = _core(hanging)
    core.start(watchdog=False)
    try:
        _arm_and_move(core)
        hanging.hang_state = True
        hanging.hang_stop = True
        # One thread drives the watchdog into its bounded stop; a *second*,
        # independent caller asks for its own stop at the same time.
        watchdog = threading.Thread(target=core.tick, daemon=True)
        watchdog.start()
        started = time.monotonic()
        answered = _answers_within(
            lambda: core.explicit_stop(
                2, LOCAL_PEER, GatewayStopV1(WRITER, core.boot_epoch, 500, "independent", True)
            ),
            CONTAINMENT_BUDGET_S * 2,
        )
        elapsed = time.monotonic() - started
        assert answered, "an independent stop waited on the hung vendor call"
        assert hanging.blocked_calls >= 1, "vacuous: nothing was blocked"
        assert not hanging.released.is_set(), "vacuous: released too early"
        assert elapsed < CONTAINMENT_BUDGET_S * 2
        watchdog.join(timeout=CONTAINMENT_BUDGET_S)
        assert core.phase.value == "latched"
    finally:
        hanging.release()
        core.close()


@requires_seqpacket
def test_a_stop_rpc_that_overruns_its_budget_reads_as_a_failed_stop(
    hanging: HangingSport,
) -> None:
    """SMF-005: honest classification, in the safe direction."""

    core = _core(hanging)
    core.start(watchdog=False)
    try:
        _arm_and_move(core)
        hanging.stop_delay_s = SEAM_LIMITS.stop_retry_s * 4
        assert _answers_within(core.tick, CONTAINMENT_BUDGET_S)
        from parcel_robot.bridge.protocol import GatewayStopV1

        assert _answers_within(
            lambda: core.explicit_stop(
                1, LOCAL_PEER, GatewayStopV1(WRITER, core.boot_epoch, 77, "slow", False)
            ),
            CONTAINMENT_BUDGET_S,
        )
        # The witness that the seeded delay really ran, not that it was skipped.
        assert hanging.stop_calls >= 1
        report = core.last_stop_report
        assert report is not None
        assert report.stationary_confirmed is False
        assert core.phase.value == "latched"
    finally:
        hanging.release()
        core.close()


def test_a_vendor_call_that_returns_inside_its_budget_is_unaffected() -> None:
    """The containment must not turn a healthy slow-ish vendor into a fault."""

    lane = BoundedCallLaneV1("bench", lambda payload: ("ok", payload))
    try:
        outcome = lane.invoke("payload", 1.0)
        assert outcome.ok is True
        assert outcome.value == ("ok", "payload")
        assert lane.timeouts == 0
    finally:
        lane.close()


def test_a_raising_vendor_call_is_evidence_not_a_timeout() -> None:
    def boom(_payload: object) -> object:
        raise RuntimeError("vendor said no")

    lane = BoundedCallLaneV1("bench", boom)
    try:
        outcome = lane.invoke(None, 1.0)
        assert outcome.completed is True
        assert outcome.timed_out is False
        assert isinstance(outcome.error, RuntimeError)
        assert lane.failures == 1
    finally:
        lane.close()


def test_an_overdue_lane_answers_immediately_instead_of_costing_a_full_budget() -> None:
    """A polling loop against a wedged vendor must stay a polling loop."""

    gate = threading.Event()
    lane = BoundedCallLaneV1("bench", lambda _payload: gate.wait())
    try:
        assert lane.invoke(None, 0.05).timed_out is True
        started = time.monotonic()
        for _ in range(5):
            assert lane.invoke(None, 0.05).timed_out is True
        assert time.monotonic() - started < 0.10, "the overdue lane blocked again"
        assert lane.call_in_flight is True
    finally:
        gate.set()
        lane.close()


def test_the_two_lanes_are_independent(hanging: HangingSport) -> None:
    """A hung ``state()`` must not stand between the gateway and a StopMove."""

    seam = VendorIoSeamV1(hanging)
    try:
        hanging.hang_state = True
        assert seam.sample(0.05).timed_out is True
        stopped = seam.stop_move("independent", 1.0)
        assert stopped.ok is True and stopped.value is True
        assert hanging.blocked_state_calls >= 1
        assert not hanging.released.is_set()
    finally:
        hanging.release()
        seam.close()


def test_the_lane_holds_no_lock_while_the_vendor_call_runs() -> None:
    """Lock discipline, half one: the callable runs with the lane's lock released.

    The callable below reaches back into the lane's *own* public API, which
    takes the lane's condition.  If the worker still held it, this deadlocks.
    """

    holder: dict[str, object] = {}

    def reentrant(_payload: object) -> object:
        holder["in_flight"] = lane.call_in_flight
        holder["age"] = lane.in_flight_age_s()
        return "done"

    lane = BoundedCallLaneV1("reentrant", reentrant)
    try:
        outcome = lane.invoke(None, 1.0)
        assert outcome.ok is True and outcome.value == "done"
        assert holder["in_flight"] is True
    finally:
        lane.close()


def test_the_lane_never_calls_back_into_the_core() -> None:
    """Lock discipline, half two: the leaf really is a leaf.

    If the lane thread could call into ``gateway.core`` it would take the core
    ``RLock`` while a core-lock holder was waiting on the lane's condition, and
    the ordering claim in ``core.py``'s docstring would be false.
    """

    source = _tree_sources()["seam/vendor_io.py"]
    assert _relative_imports(source) == {"..ports"}
    modules, _members = _imports(source)
    assert not any(module.startswith("gateway") for module in modules), modules

    def _parameters(text: str) -> set[str]:
        names: set[str] = set()
        for node in ast.walk(ast.parse(text, feature_version=(3, 10))):
            if isinstance(node, ast.FunctionDef):
                arguments = node.args
                for group in (arguments.args, arguments.kwonlyargs, arguments.posonlyargs):
                    names.update(argument.arg for argument in group)
        return names

    callbacks = {"core", "observer", "on_refused", "on_completed", "audit", "on_stop"}
    assert _parameters(source) & callbacks == set()
    # anti-vacuity: ``writer.py`` really does take core callbacks, so "none
    # here" is a property of this module and not of the check.
    assert _parameters(_tree_sources()["writer.py"]) & callbacks == {"on_refused", "on_completed"}


def test_the_core_survives_concurrent_callers_with_a_healthy_vendor() -> None:
    """The lock ordering under real contention: watchdog + commands + stops."""

    from parcel_robot.bridge.protocol import GatewayStopV1

    sport = FakeSportServiceV1()
    core = _core(sport)
    core.start(watchdog=True)
    stop_flag = threading.Event()
    errors: list[BaseException] = []

    def churn(kind: str) -> None:
        sequence = 100 if kind == "stop" else 0
        try:
            while not stop_flag.is_set():
                if kind == "state":
                    core.state()
                elif kind == "tick":
                    core.tick()
                else:
                    sequence += 1
                    core.explicit_stop(
                        9,
                        LOCAL_PEER,
                        GatewayStopV1(WRITER, core.boot_epoch, sequence, "churn", False),
                    )
                time.sleep(0.001)
        except (TypeError, ValueError, RuntimeError, OSError) as caught:
            # pragma: no cover - failure path
            errors.append(caught)

    workers = [
        threading.Thread(target=churn, args=(kind,), daemon=True)
        for kind in ("state", "tick", "stop", "state")
    ]
    try:
        for worker in workers:
            worker.start()
        time.sleep(1.0)
        stop_flag.set()
        for worker in workers:
            worker.join(timeout=5.0)
            assert not worker.is_alive(), "a caller never came back: lock ordering is wrong"
        assert errors == [], errors
        assert core.stop_sequence > 1
    finally:
        stop_flag.set()
        core.close()


def test_move_keeps_its_own_isolation() -> None:
    """The seam must not have taken ``Move`` away from the writer thread."""

    source = (GATEWAY_ROOT / "seam" / "vendor_io.py").read_text(encoding="utf-8")
    assert ".move(" not in source
    assert "sport.move" not in source
    core_source = (GATEWAY_ROOT / "core.py").read_text(encoding="utf-8")
    # The core still reaches Move only by submitting to the writer.
    assert "self._writer.submit(" in core_source
    assert "self._sport.move(" not in core_source


def test_the_core_no_longer_calls_the_vendor_synchronously_under_its_lock() -> None:
    """The structural half of the containment claim."""

    source = (GATEWAY_ROOT / "core.py").read_text(encoding="utf-8")
    assert "self._sport.stop_move(" not in source
    assert "read_sport_sample(" not in source
    assert "self._vendor_io.stop_move(" in source
    assert "self._vendor_io.sample(" in source
    # The only remaining direct vendor touches are the two that cannot block on
    # motion I/O: the writer handshake and shutdown.
    remaining = {
        line.strip()
        for line in source.splitlines()
        if "self._sport." in line and not line.strip().startswith("#")
    }
    assert remaining == {
        "if not self._sport.acquire_writer(request.writer_id):",
        "self._sport.release_writer(lease.writer_id if lease is not None else None)",
        "self._sport.close()",
    }, remaining


# --------------------------------------------------------------------------
# the four named seeded reds
# --------------------------------------------------------------------------


def assert_reconnect_leaves_the_client_disarmed(
    client: MotionGatewayClientV1,
    served: ServedSeam,
) -> None:
    result = client.reconnect()
    assert result.armed is False, "reconnect reported itself armed"
    assert client.armed is False, "the client armed itself on reconnect"
    assert served.core.active_writer is None, "the gateway still holds a lease"
    try:
        client.command(vx_mps=0.04)
    except GatewayAuthorityError:
        return
    raise AssertionError("a command was accepted after a reconnect with no new acquire")


def assert_restart_is_a_new_boot_epoch(previous: str, current: str) -> None:
    assert previous, "no previous boot epoch was captured"
    assert current != previous, "the gateway reused its boot epoch across a restart"


def assert_reaches_the_body_only_through_the_unix_gateway(
    client: MotionGatewayClientV1,
) -> None:
    vendor_surface = ("move", "stop_move", "acquire_writer", "state")
    for value in vars(client).values():
        held = [name for name in vendor_surface if hasattr(value, name)]
        assert held != list(vendor_surface), f"the client holds a vendor object: {value!r}"
    sockets = [value for value in vars(client).values() if isinstance(value, socket.socket)]
    assert len(sockets) == 1, sockets
    assert sockets[0].family is socket.AF_UNIX
    assert sockets[0].type is socket.SOCK_SEQPACKET


@requires_seqpacket
def test_seeded_red_the_reconnect_check_fails_on_a_client_that_auto_rearms(
    served: ServedSeam,
) -> None:
    """Seeded red 1: the suite must fail if reconnect auto-rearmed."""

    class AutoRearmingClient(MotionGatewayClientV1):
        def reconnect(self, *, settle_timeout_s: float = 2.0) -> object:
            result = super().reconnect(settle_timeout_s=settle_timeout_s)
            self.acquire()
            return replace(result, armed=True)

    mutant = AutoRearmingClient.connect(served.path, writer_id=WRITER)
    try:
        mutant.acquire()
        with pytest.raises(AssertionError):
            assert_reconnect_leaves_the_client_disarmed(mutant, served)
    finally:
        mutant.close()


def test_seeded_red_the_boot_epoch_check_fails_on_a_gateway_that_reuses_its_epoch() -> None:
    """Seeded red 2: the suite must fail if a boot epoch were reused."""

    first = _core(FakeSportServiceV1())
    try:
        reused = GatewayCoreV1(
            FakeSportServiceV1(),
            policy=_policy(),
            limits=SEAM_LIMITS,
            boot_epoch=first.boot_epoch,
        )
        try:
            with pytest.raises(AssertionError):
                assert_restart_is_a_new_boot_epoch(first.boot_epoch, reused.boot_epoch)
        finally:
            reused.close()
        # and the honest case passes
        fresh = _core(FakeSportServiceV1())
        try:
            assert_restart_is_a_new_boot_epoch(first.boot_epoch, fresh.boot_epoch)
        finally:
            fresh.close()
    finally:
        first.close()


@requires_seqpacket
def test_seeded_red_the_gateway_only_check_fails_on_a_client_that_holds_the_vendor(
    served: ServedSeam,
) -> None:
    """Seeded red 3: the suite must fail if the client bypassed the Unix gateway."""

    class BypassingClient(MotionGatewayClientV1):
        def __init__(self, *args: object, **kwargs: object) -> None:
            super().__init__(*args, **kwargs)
            # The exact stop condition: a vendor handle on the runtime side.
            self.sport = FakeSportServiceV1()

    honest = served.client()
    try:
        assert_reaches_the_body_only_through_the_unix_gateway(honest)
    finally:
        honest.close()
    mutant = BypassingClient.connect(served.path, writer_id=WRITER)
    try:
        with pytest.raises(AssertionError):
            assert_reaches_the_body_only_through_the_unix_gateway(mutant)
    finally:
        mutant.sport.close()
        mutant.close()


@requires_seqpacket
def test_seeded_red_the_containment_check_fails_on_an_unbounded_vendor_seam(
    hanging: HangingSport,
) -> None:
    """Seeded red 4: the suite must fail if a hung call could wedge the watchdog.

    The mutant is the code as it stood before this card: ``state()`` and
    ``stop_move()`` called straight through, synchronously, under the core
    lock.
    """

    class UnboundedVendorIoSeam:
        """The pre-card behaviour, restored on purpose."""

        def __init__(self, sport: object) -> None:
            self._sport = sport

        def sample(self, timeout_s: float) -> BoundedCallOutcomeV1:
            from gateway.ports import read_sport_sample

            del timeout_s
            return BoundedCallOutcomeV1(True, False, read_sport_sample(self._sport), None, 0.0, 0.0)

        def stop_move(self, reason: str, timeout_s: float) -> BoundedCallOutcomeV1:
            del timeout_s
            return BoundedCallOutcomeV1(
                True, False, bool(self._sport.stop_move(reason=reason)), None, 0.0, 0.0
            )

        def close(self, **_kwargs: object) -> None:
            return None

    core = _core(hanging)
    core.start(watchdog=False)
    try:
        _arm_and_move(core)
        core._vendor_io = UnboundedVendorIoSeam(hanging)
        hanging.hang_state = True
        with pytest.raises(AssertionError):
            assert_supervisor_survives_hung_vendor_io(core, hanging, budget_s=1.0)
    finally:
        # Release first: the mutant is wedged holding the core lock, and
        # ``close()`` would wait for it.
        hanging.release()
        time.sleep(0.05)
        core.close()


# --------------------------------------------------------------------------
# contract item 2 — sd_notify: readiness that is earned, not announced
# --------------------------------------------------------------------------


class _Recorder:
    def __init__(self) -> None:
        self.gate = threading.Event()
        self.calls = 0

    def fast(self) -> object:
        self.calls += 1
        return self.calls

    def wedged(self) -> object:
        self.calls += 1
        self.gate.wait()
        return None


def test_ready_is_not_announced_until_the_probe_answers() -> None:
    recorder = _Recorder()
    notifier = SdNotifierV1("")
    liveness = GatewayLivenessNotifierV1(
        notifier, recorder.wedged, watchdog_period_s=0.05, probe_timeout_s=0.05
    )
    try:
        assert liveness.announce_ready() is False
        assert liveness.ready_announced is False
        assert notifier.sent == ()
        assert recorder.calls >= 1, "vacuous: the probe never ran"
        assert not recorder.gate.is_set(), "vacuous: the probe was released early"
    finally:
        recorder.gate.set()
        liveness.stop()


def test_ready_is_announced_once_the_probe_answers() -> None:
    recorder = _Recorder()
    notifier = SdNotifierV1("")
    liveness = GatewayLivenessNotifierV1(
        notifier, recorder.fast, watchdog_period_s=0.02, probe_timeout_s=1.0
    )
    try:
        assert liveness.announce_ready(status="disarmed") is True
        assert notifier.sent[0].startswith("READY=1")
        assert "STATUS=disarmed" in notifier.sent[0]
    finally:
        liveness.stop()


def test_a_wedged_core_stops_the_watchdog_pings() -> None:
    """The whole point: a wedged gateway must go quiet, not keep reporting healthy."""

    recorder = _Recorder()
    notifier = SdNotifierV1("")
    liveness = GatewayLivenessNotifierV1(
        notifier, recorder.fast, watchdog_period_s=0.02, probe_timeout_s=0.5
    )
    try:
        assert liveness.announce_ready() is True
        liveness.start()
        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline and liveness.pings < 3:
            time.sleep(0.01)
        assert liveness.pings >= 3, "the healthy case never pinged"
        # now wedge it
        liveness._lane.close(join_timeout_s=0.0)
        wedged = GatewayLivenessNotifierV1(
            notifier, recorder.wedged, watchdog_period_s=0.02, probe_timeout_s=0.05
        )
        try:
            assert wedged.announce_ready() is False
            wedged._ready = True
            wedged.start()
            time.sleep(0.4)
            assert wedged.pings == 0, "a wedged core kept pinging the supervisor"
            assert wedged.missed_probes >= 1
            assert not recorder.gate.is_set()
        finally:
            recorder.gate.set()
            wedged.stop()
    finally:
        recorder.gate.set()
        liveness.stop()


def test_the_notifier_speaks_sd_notify_over_a_real_datagram_socket(short_dir: Path) -> None:
    path = short_dir / "notify.sock"
    listener = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
    listener.bind(str(path))
    listener.settimeout(2.0)
    try:
        notifier = SdNotifierV1(str(path))
        assert notifier.supervised is True
        assert notifier.ready("bench") is True
        assert listener.recv(4096).decode("utf-8") == "READY=1\nSTATUS=bench"
        assert notifier.watchdog() is True
        assert listener.recv(4096).decode("utf-8") == "WATCHDOG=1"
        assert notifier.errors == 0
    finally:
        listener.close()


def test_supervision_is_read_the_way_sd_notify_documents_it() -> None:
    supervision = read_supervision({})
    assert supervision.supervised is False
    assert supervision.watchdog_enabled is False
    supervision = read_supervision(
        {"NOTIFY_SOCKET": "/run/systemd/notify", "WATCHDOG_USEC": "2000000"}
    )
    assert supervision.supervised is True
    assert supervision.watchdog_period_s == pytest.approx(2.0 * WATCHDOG_PING_FRACTION)
    # A WATCHDOG_PID naming another process means the watchdog is not ours.
    supervision = read_supervision(
        {
            "NOTIFY_SOCKET": "/run/systemd/notify",
            "WATCHDOG_USEC": "2000000",
            "WATCHDOG_PID": str(os.getpid() + 1),
        }
    )
    assert supervision.watchdog_enabled is False


def test_the_notifier_is_inert_without_a_supervisor() -> None:
    notifier = SdNotifierV1("")
    assert notifier.supervised is False
    assert notifier.ready() is False
    assert notifier.watchdog() is False
    assert notifier.errors == 0


# --------------------------------------------------------------------------
# contract item 1 — the installed artifact, from a clean CPython 3.10 venv
# --------------------------------------------------------------------------

CLEAN_VENV_ENV = "PARCEL_SEAM_CLEAN_VENV"


def _clean_venv() -> Path | None:
    raw = os.environ.get(CLEAN_VENV_ENV, "").strip()
    if not raw:
        return None
    root = Path(raw)
    return root if (root / "bin" / CONSOLE_SCRIPT_NAME).exists() else None


requires_clean_venv = pytest.mark.skipif(
    _clean_venv() is None,
    reason=(
        f"set {CLEAN_VENV_ENV} to a venv with the built parcel-gateway wheel installed; "
        "see scrum/20260824/task_3/SEAM_STATUS.md for the build recipe"
    ),
)


@requires_clean_venv
def test_the_installed_artifact_does_not_import_from_the_repository_checkout() -> None:
    """Contract 1."""

    venv = _clean_venv()
    assert venv is not None
    probe = (
        "import sys, gateway, gateway.seam.cli, gateway.seam.client;"
        "import parcel_robot.bridge.protocol as p;"
        "print(gateway.__file__);print(p.__file__);"
        f"print([x for x in sys.path if x and {str(REPO)!r} in x])"
    )
    result = subprocess.run(
        [str(venv / "bin" / "python"), "-c", probe],
        cwd="/",
        capture_output=True,
        text=True,
        timeout=60,
        check=True,
        env={"PATH": "/usr/bin:/bin", "HOME": os.environ.get("HOME", "/tmp")},
    )
    gateway_file, protocol_file, repo_paths = result.stdout.strip().splitlines()
    assert gateway_file.startswith(str(venv)), gateway_file
    assert protocol_file.startswith(str(venv)), protocol_file
    assert repo_paths == "[]", repo_paths


@requires_clean_venv
@requires_seqpacket
def test_the_installed_console_script_starts_and_earns_its_readiness(
    short_dir: Path,
) -> None:
    """Contract 1 + 2: service-style start against fake Sport, with sd_notify."""

    venv = _clean_venv()
    assert venv is not None
    with _installed_gateway(venv, short_dir) as running:
        assert running.ready_message.startswith("READY=1")
        assert "disarmed" in running.ready_message
        assert running.process.poll() is None
        # WATCHDOG=1 keeps arriving from a healthy gateway.
        assert running.wait_for("WATCHDOG=1", timeout_s=4.0)


@requires_clean_venv
@requires_seqpacket
def test_the_installed_client_drives_the_installed_gateway_end_to_end(
    short_dir: Path,
) -> None:
    """Contract 1 + 3 + 4, entirely inside the clean venv."""

    venv = _clean_venv()
    assert venv is not None
    with _installed_gateway(venv, short_dir) as running:
        script = _DRIVER_SCRIPT % {"socket": str(running.socket_path), "writer": WRITER}
        result = subprocess.run(
            [str(venv / "bin" / "python"), "-c", script],
            cwd="/",
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
            env={"PATH": "/usr/bin:/bin", "HOME": os.environ.get("HOME", "/tmp")},
        )
        assert result.returncode == 0, result.stderr
        report = json.loads(result.stdout.strip().splitlines()[-1])
        assert report["armed"] is True
        assert report["admitted"] is True
        assert report["moved"] is True
        assert report["stopped_confirmed"] is True
        assert report["stationary_after_stop"] is True
        assert report["armed_after_stop"] is False
        assert report["refused_after_stop"] == "GatewayAuthorityError"
        assert report["reconnect_armed"] is False
        assert report["refused_after_reconnect"] == "GatewayAuthorityError"


@requires_clean_venv
@requires_seqpacket
def test_service_style_kill_and_restart_from_the_installed_artifact(
    short_dir: Path,
) -> None:
    """Contract 1 + 5: a restart is a new boot epoch and resumes nothing."""

    venv = _clean_venv()
    assert venv is not None
    with _installed_gateway(venv, short_dir) as first:
        first_epoch = _installed_boot_epoch(venv, first.socket_path)
        first.process.send_signal(signal.SIGKILL)
        first.process.wait(timeout=10)
    with _installed_gateway(venv, short_dir, name="second") as second:
        second_epoch = _installed_boot_epoch(venv, second.socket_path)
        assert_restart_is_a_new_boot_epoch(first_epoch, second_epoch)
        # And the fresh gateway is disarmed with no lease.
        script = _STATE_SCRIPT % {"socket": str(second.socket_path), "writer": WRITER}
        result = subprocess.run(
            [str(venv / "bin" / "python"), "-c", script],
            cwd="/", capture_output=True, text=True, timeout=60, check=False,
            env={"PATH": "/usr/bin:/bin", "HOME": os.environ.get("HOME", "/tmp")},
        )
        assert result.returncode == 0, result.stderr
        state = json.loads(result.stdout.strip().splitlines()[-1])
        assert state["phase"] == "disarmed"
        assert state["writer_id"] == ""
        assert state["stationary"] is True


@dataclass
class _RunningGateway:
    process: subprocess.Popen
    socket_path: Path
    notify: socket.socket
    ready_message: str
    _seen: list[str]

    def wait_for(self, message: str, *, timeout_s: float) -> bool:
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            if message in self._seen:
                return True
            self.notify.settimeout(max(0.05, deadline - time.monotonic()))
            try:
                self._seen.append(self.notify.recv(4096).decode("utf-8"))
            except OSError:
                continue
        return False


class _installed_gateway:
    """Start ``<venv>/bin/parcel-gateway`` the way the unit would, and wait for READY=1."""

    def __init__(self, venv: Path, short_dir: Path, *, name: str = "first") -> None:
        self._venv = venv
        self._dir = short_dir
        self._name = name

    def __enter__(self) -> _RunningGateway:
        notify_path = self._dir / f"n-{self._name}.sock"
        # Not chosen here: this is the CLI's own $STATE_DIRECTORY default, and
        # the test only works if the console script really uses it.
        socket_path = self._dir / cli_module.DEFAULT_SOCKET_NAME
        listener = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
        listener.bind(str(notify_path))
        listener.settimeout(20.0)
        environment = {
            "PATH": "/usr/bin:/bin",
            "HOME": os.environ.get("HOME", "/tmp"),
            "PARCEL_ARMED": "0",
            "PARCEL_ROLE": "gateway",
            "PARCEL_GATEWAY_SPORT": "fake",
            "PARCEL_GATEWAY_WRITER_ID": WRITER,
            "STATE_DIRECTORY": str(self._dir),
            "LOGS_DIRECTORY": str(self._dir),
            "NOTIFY_SOCKET": str(notify_path),
            "WATCHDOG_USEC": "1000000",
        }
        process = subprocess.Popen(
            [str(self._venv / "bin" / "parcel-gateway"), "--disarmed"],
            cwd="/",
            env=environment,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        self._process = process
        self._listener = listener
        try:
            ready = listener.recv(4096).decode("utf-8")
        except OSError as exc:  # pragma: no cover - failure path
            process.kill()
            listener.close()
            raise AssertionError(f"parcel-gateway never sent READY=1: {exc}") from exc
        return _RunningGateway(
            process=process,
            socket_path=socket_path,
            notify=listener,
            ready_message=ready,
            _seen=[],
        )

    def __exit__(self, *_args: object) -> None:
        if self._process.poll() is None:
            self._process.send_signal(signal.SIGTERM)
            try:
                self._process.wait(timeout=10)
            except subprocess.TimeoutExpired:  # pragma: no cover - failure path
                self._process.kill()
        self._listener.close()


def _installed_boot_epoch(venv: Path, socket_path: Path) -> str:
    script = _STATE_SCRIPT % {"socket": str(socket_path), "writer": WRITER}
    result = subprocess.run(
        [str(venv / "bin" / "python"), "-c", script],
        cwd="/", capture_output=True, text=True, timeout=60, check=False,
        env={"PATH": "/usr/bin:/bin", "HOME": os.environ.get("HOME", "/tmp")},
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout.strip().splitlines()[-1])["boot_epoch"]


_STATE_SCRIPT = """
import json
from gateway.seam.client import MotionGatewayClientV1
with MotionGatewayClientV1.connect(%(socket)r, writer_id=%(writer)r) as client:
    state = client.state()
    print(json.dumps({
        "boot_epoch": client.boot_epoch,
        "phase": state.phase,
        "writer_id": state.writer_id,
        "stationary": state.stationary,
    }))
"""

_DRIVER_SCRIPT = """
import json, time
from gateway.seam.client import GatewayAuthorityError, MotionGatewayClientV1

report = {}
with MotionGatewayClientV1.connect(%(socket)r, writer_id=%(writer)r) as client:
    report["armed"] = client.acquire().armed
    report["admitted"] = client.command(vx_mps=0.04).admitted
    moved = False
    deadline = time.monotonic() + 2.0
    while time.monotonic() < deadline:
        observed = client.state()
        if abs(observed.vx_mps) > 0.0:
            moved = True
            break
        client.command(vx_mps=0.04)
        time.sleep(0.01)
    report["moved"] = moved
    stopped = client.stop(reason="installed_artifact_proof")
    report["stopped_confirmed"] = stopped.confirmed_stationary
    report["stationary_after_stop"] = client.state().stationary
    report["armed_after_stop"] = client.armed
    try:
        client.command(vx_mps=0.04)
        report["refused_after_stop"] = "ACCEPTED"
    except GatewayAuthorityError:
        report["refused_after_stop"] = "GatewayAuthorityError"
    result = client.reconnect()
    report["reconnect_armed"] = result.armed or client.armed
    try:
        client.command(vx_mps=0.04)
        report["refused_after_reconnect"] = "ACCEPTED"
    except GatewayAuthorityError:
        report["refused_after_reconnect"] = "GatewayAuthorityError"
print(json.dumps(report))
"""


# --------------------------------------------------------------------------
# contract item 8 — the honest label, asserted rather than promised
# --------------------------------------------------------------------------

FORBIDDEN_CLAIMS = ("on-Orin", "target-run", "on-robot", "physical stop", "robot-ready")


def test_this_suite_claims_desktop_bench_and_nothing_stronger() -> None:
    """Contract 8. The header may *disclaim* these words; nothing else may use them."""

    source = Path(__file__).read_text(encoding="utf-8")
    assert "desktop/bench" in source
    header = ast.get_docstring(ast.parse(source)) or ""
    assert "desktop/bench" in header
    body = source.replace(header, "")
    for claim in FORBIDDEN_CLAIMS:
        occurrences = [
            line for line in body.splitlines()
            if claim in line and "FORBIDDEN_CLAIMS" not in line
        ]
        assert occurrences == [], (claim, occurrences)


def test_the_seam_package_docstring_records_why_it_is_a_subpackage() -> None:
    """The A1 pin is extended, not evaded — and the reason is written down."""

    doc = seam_package.__doc__ or ""
    assert "test_the_gateway_tree_holds_the_expected_modules" in doc
    assert "recursively" in doc
    for module in (client_module, notify_module, vendor_io_module, cli_module):
        assert (module.__doc__ or "").strip(), module.__name__


def test_the_gateway_suite_this_card_must_not_change_is_untouched() -> None:
    """Contract 6: A1's invariants stay green without weaker limits or re-pins."""

    pinned = REPO / "tests" / "test_m1_0_gateway.py"
    source = pinned.read_text(encoding="utf-8")
    assert 'DEPLOYABLE_MODULES = (' in source
    assert '"seam"' not in source, "A1's module pin was re-pinned"
    assert 'GATEWAY_ROOT.glob("*.py")' in source
    assert sys.version_info >= (3, 10)
