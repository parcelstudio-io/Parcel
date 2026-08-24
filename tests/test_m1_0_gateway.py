"""Card M1-0 GATEWAY — the co-located governor + sole-writer gateway, on the bench.

What this file drives is the **process in ``gateway/``**, not a mock of it: the
real :class:`gateway.core.GatewayCoreV1` state machine, the real
:class:`gateway.server.GatewayServerV1` over a real ``AF_UNIX`` /
``SOCK_SEQPACKET`` socket, speaking the frozen ``bridge/protocol.py`` V1 DTOs,
against ``bridge/fake_sport.py`` with its seeded fault inventory.  Two of the
loss classes cannot be produced inside one interpreter at all — a client that
dies without running any cleanup, and a gateway that restarts — so those run as
subprocesses and use ``SIGKILL``.

The organising claim is the card's: **every loss class ends with the vendor at
exact zero, and the last thing the vendor was told is a stop.**  Each fault
seed in ``bridge/fixtures/gateway_fault_seeds_v1.json`` gets a case here, each
case declares what it expects rather than sharing one weak assertion, and
:func:`test_every_frozen_fault_seed_and_invariant_has_a_named_case_in_this_file`
fails if a seed or an invariant in the frozen manifests has no case at all — so this suite cannot quietly stop
covering the inventory it claims to cover.

**What it does not prove.**  Nothing physical.  There is no robot, no vendor
SDK and no Unitree firmware in this tree; ``FakeSportServiceV1`` models the
high-level effects the gateway must react to, not a Go2.  The latency and
jitter numbers are desktop numbers from a 192-core dev box, not Orin numbers,
and the soak gates only the TTL contract the gateway itself owns — braking
distance, stopping envelope, independent operator stop and scheduling under
real load are box-day rows in ``scrum/20260824/task_2/CLAUDE_RESPONSE.md``.
"""

from __future__ import annotations

import ast
import json
import os
import shutil
import signal
import socket
import statistics
import subprocess
import sys
import tempfile
import threading
import time
from dataclasses import dataclass, replace
from itertools import pairwise
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from gateway import audit as audit_module
from gateway import catalog as catalog_module
from gateway import limits as limits_module
from gateway.audit import BoundedAuditRingV1
from gateway.bench_client import BenchGatewayClientV1
from gateway.catalog import (
    BASE_VELOCITY_ACTION,
    CATALOG_DIGEST_V1,
    UNSUPPORTED_ACTIONS_V1,
    ActionCatalogV1,
    ActionNotAdmittedError,
)
from gateway.core import NON_LATCHING_CAUSES, GatewayCoreV1, VendorWriteOutcomeV1
from gateway.credentials import CredentialPolicyV1, PeerCredentialV1, single_writer_policy
from gateway.governor import (
    AuthorityEvidenceV1,
    DispositionV1,
    FinalGovernorV1,
    MotionCandidateV1,
)
from gateway.limits import GovernorLimitsV1, default_limits, regime
from gateway.process import BENCH_HASHES, AuditExporterV1, _evidence_exit_code
from gateway.server import GatewayServerV1
from parcel_robot.bridge.fake_sport import (
    FakeSportFaultsV1,
    FakeSportServiceV1,
    NonBlockingEventSinkV1,
)
from parcel_robot.bridge.invariants import (
    load_gateway_fault_seeds_v1,
    load_gateway_invariants_v1,
)
from parcel_robot.bridge.protocol import (
    MAX_GATEWAY_PACKET_BYTES,
    MAX_LOCAL_TTL_MS,
    GatewayAckDispositionV1,
    GatewayAckV1,
    GatewayAcquireV1,
    GatewayCommandV1,
    GatewayHashesV1,
    GatewayPhaseV1,
    GatewayStopReportV1,
    GatewayStopV1,
    decode_gateway_message,
    encode_gateway_message,
)
from parcel_robot.bridge.timing import (
    DEFAULT_ACTIVE_REGIME,
    ENVELOPE_REGIMES_V1,
    W0B_MAX_TTL_S,
    W0B_MAX_YAW_RAD_S,
)
from parcel_robot.control.models import ControlTiming

# ``typing.Self`` is 3.11+; the dog's interpreter is 3.10 and this file is read
# on both (card HW-1's fence, as in ``bridge/client.py``).
if TYPE_CHECKING:  # pragma: no cover - annotations only; never evaluated at runtime
    from typing import Self

REPO = Path(__file__).resolve().parents[1]
GATEWAY_ROOT = REPO / "gateway"

HASHES = BENCH_HASHES
OTHER_HASHES = GatewayHashesV1("e" * 64, "f" * 64, "0" * 64, "1" * 64)

WRITER = "m1-0-writer"
SECOND_WRITER = "m1-0-second-writer"

#: The witness budget is shortened for the fault table so a suite that runs
#: three times stays a suite.  Only ``stop_timeout_s`` moves; every other limit
#: is the shipped default, and ``test_default_limits_mirror_*`` pins those.
BENCH_LIMITS = replace(default_limits(), stop_timeout_s=0.2, stop_retry_s=0.05)

LOCAL_PEER = PeerCredentialV1(pid=os.getpid(), uid=os.geteuid(), gid=os.getegid())
FOREIGN_PEER = PeerCredentialV1(pid=1, uid=os.geteuid() + 4242, gid=0)

requires_seqpacket = pytest.mark.skipif(
    os.name != "posix" or not hasattr(socket, "SOCK_SEQPACKET"),
    reason="the M1-0 gateway speaks Unix SOCK_SEQPACKET",
)


# --------------------------------------------------------------------------
# harness
# --------------------------------------------------------------------------


def _policy(*writers: str) -> CredentialPolicyV1:
    names = writers or (WRITER,)
    return CredentialPolicyV1(
        required_hashes=HASHES,
        allowed_writer_ids=frozenset(names),
        allowed_uids=frozenset({os.geteuid()}),
    )


@dataclass(frozen=True)
class StopOutcome:
    report: GatewayStopReportV1
    phase: GatewayPhaseV1
    vendor_velocity: tuple[float, float, float]
    physical_events: list[str]

    @property
    def vendor_is_exactly_zero(self) -> bool:
        return self.vendor_velocity == (0.0, 0.0, 0.0)

    @property
    def last_vendor_action_was_a_stop(self) -> bool:
        return bool(self.physical_events) and self.physical_events[-1].startswith("stop_move")


class Bench:
    """One gateway core over one fake Sport, driven through the core's API."""

    def __init__(
        self,
        *,
        faults: FakeSportFaultsV1 | None = None,
        limits: GovernorLimitsV1 | None = None,
        policy: CredentialPolicyV1 | None = None,
        start: bool = True,
        watchdog: bool = False,
        write_observer: object = None,
        watchdog_observer: object = None,
    ) -> None:
        self.events: list[dict[str, object]] = []
        self.sink = NonBlockingEventSinkV1(self.events.append)
        self.sport = FakeSportServiceV1(faults=faults, event_sink=self.sink)
        self.core = GatewayCoreV1(
            self.sport,
            policy=policy or _policy(),
            limits=limits or BENCH_LIMITS,
            write_observer=write_observer,
            watchdog_observer=watchdog_observer,
        )
        self._sequence = 0
        if start:
            # The default bench drives ``tick`` itself so a fault's stop report
            # is returned instead of being swallowed by a thread; the threaded
            # watchdog gets its own tests.
            self.core.start(watchdog=watchdog)

    # -- driving ---------------------------------------------------------

    def next_sequence(self) -> int:
        self._sequence += 1
        return self._sequence

    def acquire(
        self,
        *,
        writer_id: str = WRITER,
        connection: int = 1,
        sequence: int | None = None,
        ttl_ms: int = MAX_LOCAL_TTL_MS,
        boot_epoch: str | None = None,
        hashes: GatewayHashesV1 | None = None,
        peer: PeerCredentialV1 | None = None,
    ) -> GatewayAckV1:
        return self.core.acquire(
            connection,
            peer or LOCAL_PEER,
            GatewayAcquireV1(
                writer_id=writer_id,
                boot_epoch=boot_epoch or self.core.boot_epoch,
                sequence=self.next_sequence() if sequence is None else sequence,
                local_ttl_ms=ttl_ms,
                hashes=hashes or HASHES,
            ),
        )

    def command(
        self,
        *,
        writer_id: str = WRITER,
        connection: int = 1,
        sequence: int | None = None,
        vx_mps: float = 0.04,
        vy_mps: float = 0.0,
        vyaw_rad_s: float = 0.0,
        ttl_ms: int = MAX_LOCAL_TTL_MS,
        boot_epoch: str | None = None,
        hashes: GatewayHashesV1 | None = None,
        peer: PeerCredentialV1 | None = None,
    ) -> GatewayAckV1:
        return self.core.command(
            connection,
            peer or LOCAL_PEER,
            GatewayCommandV1(
                writer_id=writer_id,
                boot_epoch=boot_epoch or self.core.boot_epoch,
                sequence=self.next_sequence() if sequence is None else sequence,
                local_ttl_ms=ttl_ms,
                frame_id="base_link",
                vx_mps=vx_mps,
                vy_mps=vy_mps,
                vyaw_rad_s=vyaw_rad_s,
                task_id="m1-0",
                trace_id="m1-0",
                hashes=hashes or HASHES,
            ),
        )

    def arm_and_move(self, *, vx_mps: float = 0.04, ttl_ms: int = MAX_LOCAL_TTL_MS) -> None:
        acquired = self.acquire(ttl_ms=ttl_ms)
        assert acquired.disposition is GatewayAckDispositionV1.ACCEPTED, acquired.reason
        admitted = self.command(vx_mps=vx_mps, ttl_ms=ttl_ms)
        assert admitted.disposition is GatewayAckDispositionV1.ACCEPTED, admitted.reason
        self.wait_for_vendor_event("move_applied")
        assert self.vendor_velocity()[0] != 0.0

    # -- observing -------------------------------------------------------

    def vendor_velocity(self) -> tuple[float, float, float]:
        sample = self.sport.state()
        return (sample.vx_mps, sample.vy_mps, sample.vyaw_rad_s)

    def vendor_is_exactly_zero(self) -> bool:
        return self.vendor_velocity() == (0.0, 0.0, 0.0)

    def vendor_events(self, *names: str) -> list[str]:
        self.sink.drain(timeout_s=1.0)
        return [str(item["event"]) for item in list(self.events) if item["event"] in names]

    def physical_events(self) -> list[str]:
        return self.vendor_events("move_applied", "stop_move_succeeded", "stop_move_failed")

    def wait_for_vendor_event(self, name: str, *, timeout_s: float = 2.0) -> None:
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            self.sink.drain(timeout_s=0.05)
            if any(item["event"] == name for item in list(self.events)):
                return
            time.sleep(0.005)
        raise AssertionError(f"vendor event {name!r} never arrived: {self.events}")

    def stop_reports(self) -> list[dict[str, object]]:
        return [dict(record.detail) for record in self.core.audit.events("gateway_stop_report")]

    def pump_until_stop(self, *, timeout_s: float = 4.0) -> StopOutcome:
        """Run the watchdog until the stop sequence advances, then describe it."""

        baseline = self.core.stop_sequence
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            self.core.tick()
            if self.core.stop_sequence > baseline:
                return self.outcome()
            time.sleep(0.002)
        raise AssertionError(
            f"no stop after {timeout_s}s (phase={self.core.phase}, "
            f"last={self.core.last_stop_reason})"
        )

    def outcome(self) -> StopOutcome:
        report = self.core.last_stop_report
        assert report is not None
        return StopOutcome(
            report=report,
            phase=self.core.phase,
            vendor_velocity=self.vendor_velocity(),
            physical_events=self.physical_events(),
        )

    def close(self) -> None:
        self.sport.close()
        self.core.close()


@pytest.fixture
def bench() -> Bench:
    made = Bench()
    try:
        yield made
    finally:
        made.close()


class ServedGateway:
    """A gateway core behind a real seqpacket socket, served on a thread."""

    def __init__(self, path: Path, **kwargs: object) -> None:
        self.bench = Bench(start=False, **kwargs)
        self.server = GatewayServerV1(path, self.bench.core)
        self.path = path
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self.server.serve, args=(self._stop,), daemon=True)

    def __enter__(self) -> Self:
        self._thread.start()
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline:
            if self.path.exists():
                return self
            time.sleep(0.005)
        raise AssertionError("gateway socket never appeared")

    def __exit__(self, *_args: object) -> None:
        self._stop.set()
        self._thread.join(timeout=5.0)
        self.bench.sport.close()

    def client(self) -> BenchGatewayClientV1:
        return BenchGatewayClientV1.connect(self.path)


# --------------------------------------------------------------------------
# the mirrored limits: this package may not import the product's timing module,
# so every constant it copies is pinned back to its source here
# --------------------------------------------------------------------------


def test_the_mirrored_limits_match_the_control_timing_contract() -> None:
    timing = ControlTiming()
    assert limits_module.GATEWAY_CONTROL_HZ == timing.control_hz
    assert limits_module.GATEWAY_WATCHDOG_PERIOD_S == pytest.approx(timing.period_s)
    assert limits_module.MAX_LOCAL_TTL_MS == MAX_LOCAL_TTL_MS
    assert limits_module.MAX_LOCAL_TTL_MS / 1000.0 == pytest.approx(timing.command_timeout_s)
    assert limits_module.MAX_LOCAL_TTL_MS / 1000.0 == pytest.approx(W0B_MAX_TTL_S)
    assert limits_module.STATE_TIMEOUT_S == timing.state_timeout_s
    assert limits_module.STOP_TIMEOUT_S == timing.stop_timeout_s
    assert limits_module.STOP_RETRY_S == timing.stop_retry_s
    assert limits_module.STOP_SETTLED_SAMPLES == timing.stop_settled_samples
    assert limits_module.SETTLED_LINEAR_MPS == timing.settled_linear_speed_mps
    assert limits_module.SETTLED_YAW_RAD_S == timing.settled_yaw_speed_rad_s
    assert limits_module.MAX_YAW_RAD_S == W0B_MAX_YAW_RAD_S
    assert limits_module.VENDOR_WRITE_STALL_S == timing.state_timeout_s
    # The stop witness is exact zero, which is strictly stronger than the
    # production "settled" discrimination floors it must never be confused with.
    assert limits_module.EXACT_ZERO < timing.settled_linear_speed_mps
    assert limits_module.EXACT_ZERO < timing.settled_yaw_speed_rad_s


def test_the_mirrored_speed_regimes_match_the_stopping_envelope_table() -> None:
    assert limits_module.DEFAULT_ACTIVE_REGIME == DEFAULT_ACTIVE_REGIME
    mirrored = {item.name: item.max_linear_mps for item in limits_module.REGIMES_V1}
    source = {item.name: item.speed_mps for item in ENVELOPE_REGIMES_V1}
    assert mirrored == source
    # Until the envelope row is green with measured numbers the commissioned
    # regime is the slowest one, here as in bridge/timing.py.
    assert regime(DEFAULT_ACTIVE_REGIME).max_linear_mps == min(source.values())
    with pytest.raises(ValueError):
        regime("outdoor")


def test_the_shipped_default_limits_are_the_mirrored_ones() -> None:
    shipped = default_limits()
    assert shipped.regime.name == DEFAULT_ACTIVE_REGIME
    assert shipped.max_local_ttl_ms == MAX_LOCAL_TTL_MS
    assert shipped.stop_timeout_s == limits_module.STOP_TIMEOUT_S
    assert shipped.watchdog_period_s == limits_module.GATEWAY_WATCHDOG_PERIOD_S
    with pytest.raises(ValueError):
        GovernorLimitsV1(regime=regime("leashed"), max_local_ttl_ms=MAX_LOCAL_TTL_MS + 1)
    with pytest.raises(ValueError):
        GovernorLimitsV1(regime=regime("leashed"), exact_zero=1.0)


# --------------------------------------------------------------------------
# the seam itself: what this package is allowed to import, and on what runtime
# --------------------------------------------------------------------------

#: The modules that ship inside the vendor venv on the dog.
DEPLOYABLE_MODULES = (
    "__init__",
    "audit",
    "catalog",
    "core",
    "credentials",
    "governor",
    "limits",
    "ports",
    "server",
    "writer",
)

#: The bench harness. It may reach the fake vendor; it is not deployed.
BENCH_ONLY_MODULES = ("bench_client", "process")

#: Every way a vendor SDK could get in. None of them may appear anywhere.
VENDOR_SDK_MARKERS = (
    "unitree_sdk2",
    "unitree_sdk2py",
    "unitree_legged_sdk",
    "unitree",
    "cyclonedds",
    "rclpy",
    "rospy",
)

#: Names that do not exist on CPython 3.10, the interpreter the Orin's JetPack
#: ships (same table shape as ``tests/test_hw1_py310_clean.py``, which guards
#: ``src/parcel_robot``; this package is outside its scan).
POST_310_MEMBERS = {
    "datetime": {"UTC"},
    "typing": {
        "Self",
        "LiteralString",
        "Never",
        "NotRequired",
        "Required",
        "assert_never",
        "assert_type",
        "dataclass_transform",
        "reveal_type",
        "override",
        "TypeAliasType",
    },
    "enum": {"StrEnum", "ReprEnum", "verify", "member", "nonmember"},
    "asyncio": {"TaskGroup", "timeout", "Runner", "Barrier"},
    "itertools": {"batched"},
    "contextlib": {"chdir"},
}
POST_310_MODULES = {"tomllib"}


def _gateway_sources() -> dict[str, str]:
    return {
        path.stem: path.read_text(encoding="utf-8")
        for path in sorted(GATEWAY_ROOT.glob("*.py"))
    }


def _is_type_checking_guard(test: ast.expr) -> bool:
    if isinstance(test, ast.Name):
        return test.id == "TYPE_CHECKING"
    return isinstance(test, ast.Attribute) and test.attr == "TYPE_CHECKING"


def _imports(
    source: str,
    *,
    runtime_only: bool = False,
) -> tuple[set[str], list[tuple[str, str]]]:
    """(dotted module names imported, [(module, imported name)] pairs).

    ``runtime_only`` drops anything inside an ``if TYPE_CHECKING:`` block —
    those names are never bound at runtime under ``from __future__ import
    annotations``, which is exactly how a 3.10 interpreter survives a ``Self``
    annotation.
    """

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


def test_the_gateway_tree_holds_the_expected_modules() -> None:
    assert set(_gateway_sources()) == set(DEPLOYABLE_MODULES) | set(BENCH_ONLY_MODULES)


def test_no_vendor_sdk_is_imported_anywhere_in_the_gateway_tree() -> None:
    offenders: dict[str, set[str]] = {}
    for name, source in _gateway_sources().items():
        modules, _members = _imports(source)
        hits = {
            module
            for module in modules
            if module.split(".")[0] in VENDOR_SDK_MARKERS
        }
        if hits:
            offenders[name] = hits
    assert offenders == {}


def test_the_deployable_gateway_imports_exactly_one_product_module() -> None:
    """The vendor venv needs stdlib plus ``bridge/protocol.py`` and nothing else."""

    surface: dict[str, set[str]] = {}
    for name, source in _gateway_sources().items():
        if name not in DEPLOYABLE_MODULES:
            continue
        modules, _members = _imports(source)
        product = {module for module in modules if module.startswith("parcel_robot")}
        if product:
            surface[name] = product
    reached = set().union(*surface.values()) if surface else set()
    assert reached == {"parcel_robot.bridge.protocol"}, surface
    # And the one module it does reach must itself be stdlib-only, or the
    # claim above buys nothing.
    protocol_modules, _ = _imports(
        (REPO / "src" / "parcel_robot" / "bridge" / "protocol.py").read_text(encoding="utf-8")
    )
    assert not any(module.startswith("parcel_robot") for module in protocol_modules)


def test_the_bench_modules_reach_only_the_fake_vendor() -> None:
    allowed = {"parcel_robot.bridge.protocol", "parcel_robot.bridge.fake_sport"}
    for name, source in _gateway_sources().items():
        if name not in BENCH_ONLY_MODULES:
            continue
        modules, _members = _imports(source)
        product = {module for module in modules if module.startswith("parcel_robot")}
        assert product <= allowed, (name, product)


def test_the_gateway_never_reaches_the_product_runtime_or_a_controller() -> None:
    for name, source in _gateway_sources().items():
        modules, _members = _imports(source)
        for module in modules:
            assert not module.startswith("parcel_robot.runtime"), (name, module)
            assert not module.startswith("parcel_robot.control"), (name, module)
            assert not module.startswith("parcel_robot.backends"), (name, module)


def test_every_gateway_module_is_python_310_clean() -> None:
    """3.10 grammar plus a symbol scan: the dog's JetPack CPython is 3.10."""

    findings: list[tuple[str, str, str]] = []
    for name, source in _gateway_sources().items():
        modules, members = _imports(source, runtime_only=True)
        for module in modules:
            if module.split(".")[0] in POST_310_MODULES:
                findings.append((name, module, "module"))
        for module, member in members:
            if member in POST_310_MEMBERS.get(module, set()):
                findings.append((name, f"{module}.{member}", "member"))
    assert findings == []


# --------------------------------------------------------------------------
# the allowlisted action catalog
# --------------------------------------------------------------------------


def test_the_catalog_admits_only_bounded_base_velocity() -> None:
    catalog = ActionCatalogV1(default_limits())
    assert catalog.version == catalog_module.CATALOG_VERSION_V1
    assert catalog.admitted_names == (BASE_VELOCITY_ACTION,)
    spec = catalog.admit(BASE_VELOCITY_ACTION)
    assert spec.max_duration_s == pytest.approx(MAX_LOCAL_TTL_MS / 1000.0)
    bounds = {bound.name: (bound.minimum, bound.maximum) for bound in spec.parameters}
    active = regime(DEFAULT_ACTIVE_REGIME)
    assert bounds["vx_mps"] == (-active.max_linear_mps, active.max_linear_mps)
    assert bounds["vyaw_rad_s"] == (-active.max_yaw_rad_s, active.max_yaw_rad_s)


@pytest.mark.parametrize("name", [entry for entry, _reason in UNSUPPORTED_ACTIONS_V1])
def test_every_named_unsupported_action_is_refused_with_its_reason(name: str) -> None:
    catalog = ActionCatalogV1(default_limits())
    with pytest.raises(ActionNotAdmittedError) as raised:
        catalog.admit(name)
    assert name in str(raised.value)
    assert str(raised.value) != f"action {name!r} refused: "


def test_an_unknown_action_is_refused_without_being_on_any_list() -> None:
    catalog = ActionCatalogV1(default_limits())
    with pytest.raises(ActionNotAdmittedError):
        catalog.admit("teleport")


def test_the_catalog_structure_digest_is_pinned() -> None:
    """Adding or un-refusing an action changes this; that is the point."""

    assert ActionCatalogV1(default_limits()).digest() == CATALOG_DIGEST_V1
    # The digest is over structure, so commissioning a faster regime does not
    # read as a capability change.
    faster = ActionCatalogV1(GovernorLimitsV1(regime=regime("restricted_free")))
    assert faster.digest() == CATALOG_DIGEST_V1


# --------------------------------------------------------------------------
# the final governor: clamp and veto, never originate or increase
# --------------------------------------------------------------------------


def _healthy_evidence(**overrides: object) -> AuthorityEvidenceV1:
    base = {
        "armed": True,
        "latched": False,
        "lease_active": True,
        "state_fresh": True,
        "state_sequence_ok": True,
        "ttl_remaining_s": 0.2,
        "vendor_writer_healthy": True,
    }
    base.update(overrides)
    return AuthorityEvidenceV1(**base)


def _governor(regime_name: str = DEFAULT_ACTIVE_REGIME) -> FinalGovernorV1:
    limits = GovernorLimitsV1(regime=regime(regime_name))
    return FinalGovernorV1(limits, ActionCatalogV1(limits))


def test_the_disposition_lattice_is_ordered_as_the_hld_states_it() -> None:
    ordered = [
        DispositionV1.PASS,
        DispositionV1.CLAMP,
        DispositionV1.HOLD,
        DispositionV1.STOP,
        DispositionV1.LATCHED_STOP,
    ]
    assert sorted(ordered, key=lambda item: item.value) == ordered
    for lower, higher in pairwise(ordered):
        assert lower < higher
    assert [item for item in ordered if item.permits_motion] == [
        DispositionV1.PASS,
        DispositionV1.CLAMP,
    ]


@pytest.mark.parametrize(
    ("override", "cause"),
    [
        ({"armed": False}, "gateway_disarmed"),
        ({"lease_active": False}, "sport_lease_lost"),
        ({"state_fresh": False}, "state_stale"),
        ({"state_sequence_ok": False}, "state_sequence_not_advancing"),
        ({"ttl_remaining_s": 0.0}, "local_ttl_expired"),
        ({"ttl_remaining_s": -0.001}, "local_ttl_expired"),
        ({"vendor_writer_healthy": False}, "vendor_write_stalled"),
    ],
)
def test_every_missing_positive_evidence_is_an_exact_zero_stop(
    override: dict[str, object],
    cause: str,
) -> None:
    verdict = _governor().evaluate(
        BASE_VELOCITY_ACTION, MotionCandidateV1(0.04, 0.0, 0.0), _healthy_evidence(**override)
    )
    assert verdict.disposition is DispositionV1.STOP
    assert verdict.is_exact_zero
    assert cause in verdict.causes


def test_a_latched_governor_answers_latched_stop_and_nothing_else() -> None:
    verdict = _governor().evaluate(
        BASE_VELOCITY_ACTION, MotionCandidateV1(0.9, 0.9, 0.9), _healthy_evidence(latched=True)
    )
    assert verdict.disposition is DispositionV1.LATCHED_STOP
    assert verdict.is_exact_zero
    assert verdict.causes == ("latched",)


def test_the_governor_clamps_to_the_active_regime_and_says_which_axis() -> None:
    active = regime(DEFAULT_ACTIVE_REGIME)
    verdict = _governor().evaluate(
        BASE_VELOCITY_ACTION, MotionCandidateV1(9.0, -9.0, 9.0), _healthy_evidence()
    )
    assert verdict.disposition is DispositionV1.CLAMP
    assert verdict.vx_mps == active.max_linear_mps
    assert verdict.vy_mps == -active.max_linear_mps
    assert verdict.vyaw_rad_s == active.max_yaw_rad_s
    assert set(verdict.causes) == {"clamped:vx_mps", "clamped:vy_mps", "clamped:vyaw_rad_s"}


def test_a_candidate_inside_the_regime_passes_through_untouched() -> None:
    candidate = MotionCandidateV1(0.01, -0.02, 0.05)
    verdict = _governor().evaluate(BASE_VELOCITY_ACTION, candidate, _healthy_evidence())
    assert verdict.disposition is DispositionV1.PASS
    assert verdict.axes == candidate.axes


def test_the_governor_never_originates_or_increases_motion() -> None:
    """X12's writer rule as a property, swept over the whole sign/scale space."""

    governor = _governor()
    values = [-9.0, -0.3, -0.05, -1e-12, 0.0, 1e-12, 0.05, 0.3, 9.0]
    for vx in values:
        for vy in values:
            for vyaw in values:
                candidate = MotionCandidateV1(vx, vy, vyaw)
                verdict = governor.evaluate(BASE_VELOCITY_ACTION, candidate, _healthy_evidence())
                for proposed, result in zip(candidate.axes, verdict.axes):
                    assert abs(result) <= abs(proposed)
                    assert result * proposed >= 0.0
                if candidate.axes == (0.0, 0.0, 0.0):
                    assert verdict.is_exact_zero


def test_a_shaper_that_increased_motion_would_be_vetoed_into_a_latched_stop() -> None:
    """The veto is real code, so break the clamp and watch it refuse the result."""

    class DoublingGovernor(FinalGovernorV1):
        @staticmethod
        def _clamp(
            spec: object,
            candidate: MotionCandidateV1,
        ) -> tuple[MotionCandidateV1, list[str]]:
            del spec
            doubled = MotionCandidateV1(
                candidate.vx_mps * 2.0,
                candidate.vy_mps,
                candidate.vyaw_rad_s,
            )
            return doubled, []

    limits = default_limits()
    verdict = DoublingGovernor(limits, ActionCatalogV1(limits)).evaluate(
        BASE_VELOCITY_ACTION, MotionCandidateV1(0.01, 0.0, 0.0), _healthy_evidence()
    )
    assert verdict.disposition is DispositionV1.LATCHED_STOP
    assert verdict.is_exact_zero
    assert verdict.causes == ("governor_would_increase_motion",)


def test_an_action_outside_the_catalog_is_an_exact_zero_stop() -> None:
    """The catalog is the governor's first gate, not documentation beside it."""

    verdict = _governor().evaluate(
        "front_flip", MotionCandidateV1(0.04, 0.0, 0.0), _healthy_evidence()
    )
    assert verdict.disposition is DispositionV1.STOP
    assert verdict.is_exact_zero
    assert verdict.causes == ("action_not_in_catalog",)


def test_the_clamp_uses_the_catalogs_bounds_for_the_admitted_action() -> None:
    """Change the commissioned regime and the clamp moves with the catalog."""

    for name in ("one_axis", "leashed", "restricted_free"):
        verdict = _governor(name).evaluate(
            BASE_VELOCITY_ACTION, MotionCandidateV1(9.0, 0.0, 0.0), _healthy_evidence()
        )
        assert verdict.vx_mps == regime(name).max_linear_mps


def test_an_axis_the_catalog_does_not_declare_is_zeroed_not_passed_through() -> None:
    limits = default_limits()
    catalog = ActionCatalogV1(limits)
    narrowed = replace(
        catalog.admit(BASE_VELOCITY_ACTION),
        parameters=tuple(
            bound
            for bound in catalog.admit(BASE_VELOCITY_ACTION).parameters
            if bound.name != "vyaw_rad_s"
        ),
    )
    shaped, clamped = FinalGovernorV1._clamp(narrowed, MotionCandidateV1(0.01, 0.0, 0.1))
    assert shaped.vyaw_rad_s == 0.0
    assert "clamped:vyaw_rad_s" in clamped


# --------------------------------------------------------------------------
# the bounded audit ring
# --------------------------------------------------------------------------


def test_the_audit_ring_is_bounded_and_counts_what_it_dropped() -> None:
    ring = BoundedAuditRingV1(capacity=4)
    for index in range(10):
        ring.record("event", boot_epoch="e", phase="armed", index=index)
    assert len(ring.snapshot()) == 4
    assert ring.total_records == 10
    assert ring.dropped_records == 6
    assert [record.index for record in ring.snapshot()] == [7, 8, 9, 10]


def test_the_audit_ring_cannot_raise_on_a_hostile_detail_value() -> None:
    class Hostile:
        def __repr__(self) -> str:
            raise RuntimeError("a log line must never break a stop")

    ring = BoundedAuditRingV1(capacity=4)
    ring.record("event", boot_epoch="e", phase="armed", hostile=Hostile(), long="x" * 10_000)
    record = ring.snapshot()[-1]
    detail = dict(record.detail)
    assert detail["hostile"] == "<unrenderable>"
    assert len(detail["long"]) == audit_module.MAX_DETAIL_CHARS
    assert ring.coerced_details == 2


def test_the_audit_ring_never_calls_an_observer() -> None:
    """It cannot block on a consumer because it has no consumer to call."""

    source = (GATEWAY_ROOT / "audit.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    record = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "record"
    )
    called = {
        node.func.attr
        for node in ast.walk(record)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }
    assert called <= {"items", "append", "_clock"}
    dumped = ast.dump(record)
    for forbidden in ("open", "write", "sleep", "send", "dumps", "put"):
        assert forbidden not in dumped


# --------------------------------------------------------------------------
# GWI-001 / GWF-015 — boot epoch, restart-DISARMED, exact zero at boot
# --------------------------------------------------------------------------


def test_a_fresh_gateway_boots_disarmed_and_stops_the_vendor_first(bench: Bench) -> None:
    boot = bench.core.boot_stop_report
    assert bench.core.phase is GatewayPhaseV1.DISARMED
    assert not bench.core.latched
    assert boot.reason == "gateway_boot"
    assert boot.stop_rpc_completed and boot.stationary_confirmed
    assert bench.core.stop_sequence == 1
    assert bench.vendor_is_exactly_zero()
    assert bench.physical_events() == ["stop_move_succeeded"]


def test_each_boot_mints_a_new_epoch() -> None:
    epochs = set()
    for _ in range(4):
        made = Bench()
        epochs.add(made.core.boot_epoch)
        made.close()
    assert len(epochs) == 4


def test_a_gateway_restart_zeroes_a_moving_vendor_and_mints_a_new_epoch() -> None:
    """The vendor outlives the gateway; the replacement's first act is a stop.

    A process test cannot show this: the bench vendor lives inside the gateway
    process and dies with it.  So the *same* ``FakeSportServiceV1`` is handed to
    a second core while the first is still armed and the vendor is moving —
    exactly the state a crashed gateway leaves behind.
    """

    events: list[dict[str, object]] = []
    sink = NonBlockingEventSinkV1(events.append)
    sport = FakeSportServiceV1(event_sink=sink)
    first = GatewayCoreV1(sport, policy=_policy(), limits=BENCH_LIMITS)
    first.start(watchdog=False)
    first.acquire(
        1, LOCAL_PEER, GatewayAcquireV1(WRITER, first.boot_epoch, 1, MAX_LOCAL_TTL_MS, HASHES)
    )
    first.command(
        1,
        LOCAL_PEER,
        GatewayCommandV1(
            WRITER, first.boot_epoch, 2, MAX_LOCAL_TTL_MS, "base_link",
            0.04, 0.0, 0.0, "m1-0", "m1-0", HASHES,
        ),
    )
    deadline = time.monotonic() + 2.0
    while time.monotonic() < deadline and sport.state().vx_mps == 0.0:
        time.sleep(0.005)
    assert sport.state().vx_mps != 0.0
    # The first gateway is abandoned, not closed: nothing runs on its behalf.
    second = GatewayCoreV1(sport, policy=_policy(), limits=BENCH_LIMITS)
    try:
        assert second.boot_epoch != first.boot_epoch
        assert second.phase is GatewayPhaseV1.DISARMED
        assert second.boot_stop_report.reason == "gateway_boot"
        assert second.boot_stop_report.stationary_confirmed
        assert (sport.state().vx_mps, sport.state().vy_mps, sport.state().vyaw_rad_s) == (
            0.0,
            0.0,
            0.0,
        )
        sink.drain(timeout_s=1.0)
        physical = [
            str(item["event"])
            for item in list(events)
            if item["event"] in {"move_applied", "stop_move_succeeded"}
        ]
        assert physical[-1] == "stop_move_succeeded"
        # The dead gateway's epoch buys nothing from the new one.
        refused = second.acquire(
            1,
            LOCAL_PEER,
            GatewayAcquireV1(WRITER, first.boot_epoch, 1, MAX_LOCAL_TTL_MS, HASHES),
        )
        assert refused.disposition is GatewayAckDispositionV1.REJECTED
        assert refused.reason == "boot_epoch_mismatch"
    finally:
        second.close()
        sport.close()


# --------------------------------------------------------------------------
# GWI-002 / GWF-001 — a prior boot epoch never holds authority
# --------------------------------------------------------------------------


def test_a_prior_boot_epoch_never_acquires(bench: Bench) -> None:
    refused = bench.acquire(boot_epoch="a-previous-boot")
    assert refused.disposition is GatewayAckDispositionV1.REJECTED
    assert refused.reason == "boot_epoch_mismatch"
    assert bench.core.phase is GatewayPhaseV1.DISARMED
    assert bench.core.stop_sequence == 1  # refusal is not a stop; nothing moved
    assert bench.vendor_is_exactly_zero()


def test_a_prior_boot_epoch_command_stops_and_latches(bench: Bench) -> None:
    bench.arm_and_move()
    refused = bench.command(boot_epoch="a-previous-boot")
    assert refused.disposition is GatewayAckDispositionV1.REJECTED
    assert refused.reason == "boot_epoch_mismatch"
    outcome = bench.outcome()
    assert outcome.phase is GatewayPhaseV1.LATCHED
    assert outcome.vendor_is_exactly_zero
    assert outcome.last_vendor_action_was_a_stop


# --------------------------------------------------------------------------
# GWI-003 / GWF-013 — one writer, and a conflict is a latched stop
# --------------------------------------------------------------------------


def test_a_second_writer_stops_and_latches() -> None:
    made = Bench(policy=_policy(WRITER, SECOND_WRITER))
    try:
        made.arm_and_move()
        refused = made.acquire(writer_id=SECOND_WRITER, connection=2)
        assert refused.disposition is GatewayAckDispositionV1.REJECTED
        assert refused.reason == "writer_conflict"
        outcome = made.outcome()
        assert outcome.phase is GatewayPhaseV1.LATCHED
        assert outcome.vendor_is_exactly_zero
        assert outcome.last_vendor_action_was_a_stop
        # A latched gateway does not re-arm for anyone.
        again = made.acquire(writer_id=WRITER, connection=3)
        assert again.reason == "gateway_latched"
    finally:
        made.close()


def test_a_writer_id_outside_the_allowlist_is_refused(bench: Bench) -> None:
    refused = bench.acquire(writer_id=SECOND_WRITER)
    assert refused.disposition is GatewayAckDispositionV1.REJECTED
    assert refused.reason == "writer_not_authorized"
    assert bench.core.active_writer is None


# --------------------------------------------------------------------------
# GWI-004 / GWF-002 — the per-boot sequence fence
# --------------------------------------------------------------------------


def test_a_regressed_command_sequence_stops_and_latches(bench: Bench) -> None:
    bench.arm_and_move()
    replayed = bench.command(sequence=2)
    assert replayed.disposition is GatewayAckDispositionV1.REJECTED
    assert replayed.reason == "client_sequence_not_increasing"
    outcome = bench.outcome()
    assert outcome.phase is GatewayPhaseV1.LATCHED
    assert outcome.vendor_is_exactly_zero
    assert outcome.last_vendor_action_was_a_stop


def test_a_captured_acquire_cannot_replay_after_the_client_dies(bench: Bench) -> None:
    bench.arm_and_move()
    assert bench.core.client_lost(1) is not None
    assert bench.core.phase is GatewayPhaseV1.DISARMED
    replay = bench.acquire(connection=2, sequence=1)
    assert replay.disposition is GatewayAckDispositionV1.REJECTED
    assert replay.reason == "client_sequence_not_increasing"
    fresh = bench.acquire(connection=2, sequence=500)
    assert fresh.disposition is GatewayAckDispositionV1.ACCEPTED


# --------------------------------------------------------------------------
# GWI-005 / GWF-003, GWF-018 — a duration crosses the wire, never a deadline
# --------------------------------------------------------------------------


def test_only_a_duration_ttl_crosses_the_wire() -> None:
    fields = set(
        GatewayCommandV1(
            WRITER, "epoch", 1, 350, "base_link", 0.0, 0.0, 0.0, "t", "t", HASHES
        ).as_dict()
    )
    assert "local_ttl_ms" in fields
    assert not [name for name in fields if "deadline" in name or "monotonic" in name]


@pytest.mark.parametrize("ttl", [0, MAX_LOCAL_TTL_MS + 1, True, 1.5])
def test_the_schema_refuses_a_bad_duration_ttl(ttl: object) -> None:
    with pytest.raises((TypeError, ValueError)):
        GatewayAcquireV1(WRITER, "epoch", 1, ttl, HASHES)


def test_the_ttl_expires_on_the_receivers_own_clock(bench: Bench) -> None:
    bench.arm_and_move(ttl_ms=40)
    outcome = bench.pump_until_stop()
    assert outcome.report.reason == "local_ttl_expired"
    assert outcome.phase is GatewayPhaseV1.DISARMED
    assert not bench.core.latched
    assert outcome.vendor_is_exactly_zero
    assert outcome.last_vendor_action_was_a_stop
    # No auto-resume: the expired lease is gone, not paused.
    refused = bench.command()
    assert refused.reason == "gateway_disarmed"


def test_the_threaded_watchdog_stops_on_ttl_expiry_with_no_help_from_the_test() -> None:
    """No ``tick`` is called here. If the gateway's own thread is dead, this fails."""

    made = Bench(watchdog=True)
    try:
        made.arm_and_move(ttl_ms=40)
        deadline = time.monotonic() + 3.0
        while time.monotonic() < deadline and made.core.stop_sequence < 2:
            time.sleep(0.005)
        assert made.core.stop_sequence >= 2, "the independent watchdog never fired"
        assert made.core.last_stop_reason == "local_ttl_expired"
        assert made.vendor_is_exactly_zero()
    finally:
        made.close()


def test_a_command_at_or_after_expiry_cannot_revive_authority(bench: Bench) -> None:
    bench.arm_and_move(ttl_ms=40)
    time.sleep(0.06)
    late = bench.command(ttl_ms=40)
    assert late.disposition is GatewayAckDispositionV1.REJECTED
    assert late.reason in {"local_ttl_expired", "gateway_disarmed"}
    assert bench.core.phase is not GatewayPhaseV1.ARMED
    assert bench.vendor_is_exactly_zero()


# --------------------------------------------------------------------------
# GWI-006 / GWF-007 — client loss
# --------------------------------------------------------------------------


def test_client_loss_after_a_nonzero_admission_stops_and_cannot_auto_resume(
    bench: Bench,
) -> None:
    bench.arm_and_move()
    report = bench.core.client_lost(1)
    assert report is not None
    assert report.reason == "client_disconnected"
    assert report.stop_rpc_completed and report.stationary_confirmed
    outcome = bench.outcome()
    assert outcome.phase is GatewayPhaseV1.DISARMED
    assert outcome.vendor_is_exactly_zero
    assert outcome.last_vendor_action_was_a_stop
    assert bench.command().reason == "gateway_disarmed"


def test_a_disconnect_from_a_connection_without_the_lease_stops_nothing(
    bench: Bench,
) -> None:
    bench.arm_and_move()
    assert bench.core.client_lost(99) is None
    assert bench.core.phase is GatewayPhaseV1.ARMED
    assert bench.vendor_velocity()[0] != 0.0


# --------------------------------------------------------------------------
# GWI-007 / GWF-010, GWF-011, GWF-012 — feedback health
# --------------------------------------------------------------------------


def test_sport_lease_loss_stops(bench: Bench) -> None:
    bench.arm_and_move()
    bench.sport.force_lease_loss()
    outcome = bench.pump_until_stop()
    assert outcome.report.reason == "sport_lease_lost"
    assert outcome.vendor_is_exactly_zero
    assert outcome.last_vendor_action_was_a_stop
    assert outcome.phase in {GatewayPhaseV1.DISARMED, GatewayPhaseV1.LATCHED}


def test_stale_feedback_stops_and_cannot_witness_stillness(bench: Bench) -> None:
    bench.arm_and_move()
    bench.sport.faults = FakeSportFaultsV1(stale_state_by_s=0.5)
    outcome = bench.pump_until_stop()
    assert outcome.report.reason == "state_stale"
    assert outcome.vendor_is_exactly_zero
    assert outcome.last_vendor_action_was_a_stop
    # StopMove worked, but stillness cannot be *witnessed* through stale
    # feedback — so the report says so and the gateway latches.
    assert outcome.report.stop_rpc_completed
    assert not outcome.report.stationary_confirmed
    assert outcome.report.state_sequence == 0
    assert outcome.phase is GatewayPhaseV1.LATCHED


def test_out_of_order_feedback_stops_and_latches(bench: Bench) -> None:
    bench.arm_and_move()
    bench.sport.faults = FakeSportFaultsV1(out_of_order_state=True)
    outcome = bench.pump_until_stop()
    assert outcome.report.reason in {"state_out_of_order", "state_frozen"}
    assert outcome.phase is GatewayPhaseV1.LATCHED
    assert outcome.vendor_is_exactly_zero
    assert outcome.last_vendor_action_was_a_stop


def test_a_frozen_feedback_stream_stops_and_latches() -> None:
    """Fresh stamps, never a new sample: the stream itself stopped."""

    class FrozenSequenceSport:
        def __init__(self, inner: FakeSportServiceV1) -> None:
            self._inner = inner
            self.freeze = False
            self._pinned = None

        def __getattr__(self, name: str) -> object:
            return getattr(self._inner, name)

        def state(self) -> object:
            sample = self._inner.state()
            if not self.freeze:
                self._pinned = sample.sequence
                return sample
            return replace(
                sample,
                sequence=self._pinned,
                received_at_monotonic_s=time.monotonic(),
            )

    inner = FakeSportServiceV1()
    sport = FrozenSequenceSport(inner)
    core = GatewayCoreV1(sport, policy=_policy(), limits=BENCH_LIMITS)
    core.start(watchdog=False)
    try:
        core.acquire(
            1, LOCAL_PEER, GatewayAcquireV1(WRITER, core.boot_epoch, 1, MAX_LOCAL_TTL_MS, HASHES)
        )
        core.command(
            1,
            LOCAL_PEER,
            GatewayCommandV1(
                WRITER, core.boot_epoch, 2, MAX_LOCAL_TTL_MS, "base_link",
                0.04, 0.0, 0.0, "m1-0", "m1-0", HASHES,
            ),
        )
        sport.freeze = True
        deadline = time.monotonic() + 3.0
        while time.monotonic() < deadline and core.stop_sequence < 2:
            core.tick()
            time.sleep(0.005)
        assert core.stop_sequence >= 2
        assert core.last_stop_reason == "state_frozen"
        assert core.phase is GatewayPhaseV1.LATCHED
    finally:
        core.close()


def test_a_genuinely_regressed_feedback_sequence_is_named_out_of_order() -> None:
    class RegressingSport:
        def __init__(self, inner: FakeSportServiceV1) -> None:
            self._inner = inner
            self.regress = False

        def __getattr__(self, name: str) -> object:
            return getattr(self._inner, name)

        def state(self) -> object:
            sample = self._inner.state()
            if not self.regress:
                return sample
            return replace(
                sample,
                sequence=max(1, sample.sequence - 50),
                received_at_monotonic_s=time.monotonic(),
            )

    sport = RegressingSport(FakeSportServiceV1())
    core = GatewayCoreV1(sport, policy=_policy(), limits=BENCH_LIMITS)
    core.start(watchdog=False)
    try:
        core.acquire(
            1, LOCAL_PEER, GatewayAcquireV1(WRITER, core.boot_epoch, 1, MAX_LOCAL_TTL_MS, HASHES)
        )
        sport.regress = True
        core.tick()
        assert core.last_stop_reason == "state_out_of_order"
        assert core.phase is GatewayPhaseV1.LATCHED
    finally:
        core.close()


# --------------------------------------------------------------------------
# GWI-008 / GWF-008, GWF-009 — the late-Move hazard
# --------------------------------------------------------------------------


def test_a_delayed_move_crossing_a_stop_epoch_is_followed_by_a_compensating_stop() -> None:
    made = Bench(faults=FakeSportFaultsV1(move_delay_s=0.15))
    try:
        acquired = made.acquire()
        assert acquired.disposition is GatewayAckDispositionV1.ACCEPTED
        admitted = made.command(vx_mps=0.04)
        assert admitted.disposition is GatewayAckDispositionV1.ACCEPTED
        made.wait_for_vendor_event("move_accepted")
        # The client dies while the vendor call is still in flight.
        assert made.core.client_lost(1) is not None
        deadline = time.monotonic() + 4.0
        while time.monotonic() < deadline and made.core.stop_sequence < 3:
            time.sleep(0.005)
        assert made.core.stop_sequence >= 3, "no compensating stop after the late Move"
        assert made.core.last_stop_reason == "late_move_completion_compensation"
        outcome = made.outcome()
        assert outcome.vendor_is_exactly_zero
        assert outcome.last_vendor_action_was_a_stop
        assert "move_applied" in outcome.physical_events
    finally:
        made.close()


def test_a_move_that_never_replies_cannot_block_the_independent_stop() -> None:
    made = Bench(faults=FakeSportFaultsV1(move_no_reply=True))
    try:
        made.acquire()
        made.command(vx_mps=0.04)
        made.wait_for_vendor_event("move_no_reply")
        # The one vendor writer thread is wedged inside Move; the stop path is
        # a different thread and must not care.
        outcome = made.pump_until_stop()
        assert outcome.report.reason == "vendor_write_stalled"
        assert outcome.phase is GatewayPhaseV1.LATCHED
        assert outcome.vendor_is_exactly_zero
        assert outcome.last_vendor_action_was_a_stop
    finally:
        made.close()


def test_a_vendor_move_that_raises_stops_and_latches() -> None:
    class RaisingSport:
        def __init__(self, inner: FakeSportServiceV1) -> None:
            self._inner = inner

        def __getattr__(self, name: str) -> object:
            return getattr(self._inner, name)

        def move(self, **_kwargs: object) -> None:
            raise RuntimeError("vendor Move refused")

    sport = RaisingSport(FakeSportServiceV1())
    core = GatewayCoreV1(sport, policy=_policy(), limits=BENCH_LIMITS)
    core.start(watchdog=False)
    try:
        core.acquire(
            1, LOCAL_PEER, GatewayAcquireV1(WRITER, core.boot_epoch, 1, MAX_LOCAL_TTL_MS, HASHES)
        )
        core.command(
            1,
            LOCAL_PEER,
            GatewayCommandV1(
                WRITER, core.boot_epoch, 2, MAX_LOCAL_TTL_MS, "base_link",
                0.04, 0.0, 0.0, "m1-0", "m1-0", HASHES,
            ),
        )
        deadline = time.monotonic() + 3.0
        while time.monotonic() < deadline and core.stop_sequence < 2:
            time.sleep(0.005)
        assert core.stop_sequence >= 2
        assert core.last_stop_reason.startswith("move_failed:")
        assert core.phase is GatewayPhaseV1.LATCHED
        assert sport.state().vx_mps == 0.0
    finally:
        core.close()


# --------------------------------------------------------------------------
# GWI-009 / GWF-003, 004, 005, 006, 016 — the wire fails closed
# --------------------------------------------------------------------------


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf"), True])
def test_the_schema_refuses_non_finite_or_boolean_velocity(value: object) -> None:
    with pytest.raises((TypeError, ValueError)):
        GatewayCommandV1(WRITER, "epoch", 1, 350, "base_link", value, 0.0, 0.0, "t", "t", HASHES)


@pytest.mark.parametrize("frame", ["odom", "map", "", "base_footprint"])
def test_the_schema_refuses_a_body_frame_that_is_not_base_link(frame: str) -> None:
    with pytest.raises(ValueError):
        GatewayCommandV1(WRITER, "epoch", 1, 350, frame, 0.0, 0.0, 0.0, "t", "t", HASHES)


def test_a_contract_hash_mismatch_on_a_command_stops_and_latches(bench: Bench) -> None:
    bench.arm_and_move()
    refused = bench.command(hashes=OTHER_HASHES)
    assert refused.disposition is GatewayAckDispositionV1.REJECTED
    assert refused.reason == "contract_hash_mismatch"
    outcome = bench.outcome()
    assert outcome.phase is GatewayPhaseV1.LATCHED
    assert outcome.vendor_is_exactly_zero
    assert outcome.last_vendor_action_was_a_stop


def test_a_contract_hash_mismatch_on_an_acquire_is_refused(bench: Bench) -> None:
    refused = bench.acquire(hashes=OTHER_HASHES)
    assert refused.disposition is GatewayAckDispositionV1.REJECTED
    assert refused.reason == "contract_hash_mismatch"
    assert bench.core.active_writer is None


@pytest.mark.parametrize(
    "packet",
    [
        b"",
        b"not json at all",
        b"\xff\xfe\x00",
        b'{"kind":"command","schema_version":2}',
        b'{"kind":"teleport","schema_version":1}',
        b'{"kind":"state_query","schema_version":1,"sequence":1,"sequence":2}',
        b'{"kind":"state_query","schema_version":1,"sequence":1,"extra":true}',
        b"x" * (MAX_GATEWAY_PACKET_BYTES + 1),
    ],
    ids=[
        "empty",
        "not-json",
        "not-utf8",
        "unknown-version",
        "unknown-kind",
        "duplicate-key",
        "unknown-field",
        "oversize",
    ],
)
def test_the_wire_refuses_every_malformed_packet_shape(packet: bytes) -> None:
    with pytest.raises((TypeError, ValueError)):
        decode_gateway_message(packet)


def test_an_overlong_string_cannot_be_encoded_onto_the_wire() -> None:
    with pytest.raises(ValueError):
        GatewayStopV1(WRITER, "epoch", 1, "x" * 200, False)


# --------------------------------------------------------------------------
# GWI-010 / GWF-017 — the ACK is admission, never motion
# --------------------------------------------------------------------------


def test_an_admission_ack_is_not_motion_truth() -> None:
    """The ACK returns while the vendor call is still in flight, by design."""

    made = Bench(faults=FakeSportFaultsV1(move_delay_s=0.2))
    try:
        made.acquire()
        admitted = made.command(vx_mps=0.04)
        assert admitted.disposition is GatewayAckDispositionV1.ACCEPTED
        assert admitted.ack_scope == "gateway_admission"
        # The vendor has not moved yet, and the ACK never claimed it had.
        assert made.vendor_is_exactly_zero()
        made.wait_for_vendor_event("move_applied")
        assert made.vendor_velocity()[0] != 0.0
    finally:
        made.close()


def test_an_ack_cannot_be_built_that_claims_physical_truth() -> None:
    with pytest.raises(ValueError):
        GatewayAckV1(
            boot_epoch="epoch",
            gateway_sequence=1,
            acknowledged_kind="command",
            acknowledged_sequence=1,
            disposition=GatewayAckDispositionV1.ACCEPTED,
            reason="",
            ack_scope="robot_moved",
        )


# --------------------------------------------------------------------------
# GWI-011 / GWF-014 — the stationary witness
# --------------------------------------------------------------------------


def test_a_failed_stopmove_is_never_reported_as_stationary_and_latches(bench: Bench) -> None:
    bench.arm_and_move()
    bench.sport.faults = FakeSportFaultsV1(stop_move_failure=True)
    report = bench.core.client_lost(1)
    assert report is not None
    assert report.reason == "client_disconnected"
    assert not report.stop_rpc_completed
    assert not report.stationary_confirmed
    assert report.state_sequence == 0
    assert bench.core.phase is GatewayPhaseV1.LATCHED
    # It retried within the stop budget rather than giving up on the first no.
    assert len(bench.vendor_events("stop_move_failed")) >= 2


def test_the_stop_report_dto_refuses_to_confirm_what_it_cannot_witness() -> None:
    with pytest.raises(ValueError):
        GatewayStopReportV1(
            boot_epoch="epoch",
            gateway_sequence=1,
            stop_sequence=1,
            reason="client_disconnected",
            stop_rpc_completed=False,
            stationary_confirmed=True,
            state_sequence=4,
        )
    with pytest.raises(ValueError):
        GatewayStopReportV1(
            boot_epoch="epoch",
            gateway_sequence=1,
            stop_sequence=1,
            reason="client_disconnected",
            stop_rpc_completed=True,
            stationary_confirmed=True,
            state_sequence=0,
        )


# --------------------------------------------------------------------------
# stop dominance, clamping, and the classification of causes
# --------------------------------------------------------------------------


def test_arming_alone_never_commands_motion(bench: Bench) -> None:
    acquired = bench.acquire()
    assert acquired.disposition is GatewayAckDispositionV1.ACCEPTED
    assert bench.core.phase is GatewayPhaseV1.ARMED
    assert bench.vendor_is_exactly_zero()
    assert "move_applied" not in bench.physical_events()


def test_the_value_the_vendor_receives_is_the_clamped_one(bench: Bench) -> None:
    active = regime(DEFAULT_ACTIVE_REGIME)
    bench.acquire()
    admitted = bench.command(vx_mps=9.0, vyaw_rad_s=-9.0)
    assert admitted.disposition is GatewayAckDispositionV1.ACCEPTED
    assert admitted.reason == "clamped"
    bench.wait_for_vendor_event("move_applied")
    vx, _vy, vyaw = bench.vendor_velocity()
    assert vx == active.max_linear_mps
    assert vyaw == -active.max_yaw_rad_s


def test_a_stop_is_never_refused_and_always_reaches_the_vendor(bench: Bench) -> None:
    bench.arm_and_move()
    report = bench.core.explicit_stop(
        1, LOCAL_PEER, GatewayStopV1(WRITER, bench.core.boot_epoch, 500, "owner asked", False)
    )
    assert report.reason == "client_stop:owner asked"
    assert report.stop_rpc_completed and report.stationary_confirmed
    assert bench.core.phase is GatewayPhaseV1.DISARMED
    assert bench.vendor_is_exactly_zero()
    assert bench.physical_events()[-1] == "stop_move_succeeded"


def test_an_emergency_stop_latches(bench: Bench) -> None:
    bench.arm_and_move()
    report = bench.core.explicit_stop(
        1, LOCAL_PEER, GatewayStopV1(WRITER, bench.core.boot_epoch, 500, "e-stop", True)
    )
    assert report.stationary_confirmed
    assert bench.core.phase is GatewayPhaseV1.LATCHED
    assert bench.vendor_is_exactly_zero()


def test_a_stop_from_a_connection_without_the_lease_is_still_honoured(bench: Bench) -> None:
    """Refusing a stop is never the safe direction; the gateway latches instead."""

    bench.arm_and_move()
    report = bench.core.explicit_stop(
        7, LOCAL_PEER, GatewayStopV1(WRITER, bench.core.boot_epoch, 500, "stranger", False)
    )
    assert report.stop_rpc_completed
    assert bench.core.phase is GatewayPhaseV1.LATCHED
    assert bench.vendor_is_exactly_zero()


def test_a_replayed_stop_sequence_is_still_honoured_and_latches(bench: Bench) -> None:
    bench.arm_and_move()
    report = bench.core.explicit_stop(
        1, LOCAL_PEER, GatewayStopV1(WRITER, bench.core.boot_epoch, 1, "replay", False)
    )
    assert report.stop_rpc_completed
    assert bench.core.phase is GatewayPhaseV1.LATCHED
    assert bench.vendor_is_exactly_zero()


def test_an_unclassified_stop_cause_latches_by_default() -> None:
    """Fail-closed by construction: only the named recoverable causes disarm."""

    should_latch = GatewayCoreV1._should_latch
    assert should_latch("a_cause_no_card_has_written_yet") is True
    for cause in NON_LATCHING_CAUSES:
        assert should_latch(cause) is False
    assert should_latch("client_stop:whatever the owner said") is False
    assert should_latch("protocol_fault:unsupported gateway schema version 2") is True
    assert NON_LATCHING_CAUSES == frozenset(
        {
            "gateway_boot",
            "gateway_shutdown",
            "client_disconnected",
            "client_stop",
            "local_ttl_expired",
            "sport_lease_lost",
            "state_stale",
            "late_move_completion_compensation",
        }
    )


# --------------------------------------------------------------------------
# the authenticated lease
# --------------------------------------------------------------------------


def test_a_foreign_peer_cannot_command_an_existing_lease(bench: Bench) -> None:
    bench.arm_and_move()
    refused = bench.command(peer=FOREIGN_PEER)
    assert refused.disposition is GatewayAckDispositionV1.REJECTED
    assert refused.reason == "peer_not_authorized"
    assert bench.core.phase is GatewayPhaseV1.LATCHED
    assert bench.vendor_is_exactly_zero()


def test_a_foreign_peer_cannot_acquire(bench: Bench) -> None:
    refused = bench.acquire(peer=FOREIGN_PEER)
    assert refused.disposition is GatewayAckDispositionV1.REJECTED
    assert refused.reason == "peer_not_authorized"
    assert bench.core.active_writer is None


def test_the_credential_policy_refuses_an_empty_allowlist() -> None:
    with pytest.raises(ValueError):
        CredentialPolicyV1(HASHES, frozenset(), frozenset({os.geteuid()}))
    with pytest.raises(ValueError):
        CredentialPolicyV1(HASHES, frozenset({WRITER}), frozenset())
    policy = single_writer_policy(required_hashes=HASHES, writer_id=WRITER)
    assert policy.allowed_uids == frozenset({os.geteuid()})
    assert policy.admits_hashes(HASHES)
    assert not policy.admits_hashes(OTHER_HASHES)


# --------------------------------------------------------------------------
# GWI-012 / GWF-019 — evidence can be lost; control cannot change
# --------------------------------------------------------------------------


def _client_loss_stop_fields(*, capacity: int) -> tuple[dict[str, object], BoundedAuditRingV1]:
    ring = BoundedAuditRingV1(capacity=capacity)
    events: list[dict[str, object]] = []
    sink = NonBlockingEventSinkV1(events.append)
    sport = FakeSportServiceV1(event_sink=sink)
    core = GatewayCoreV1(sport, policy=_policy(), limits=BENCH_LIMITS, audit=ring)
    core.start(watchdog=False)
    try:
        core.acquire(
            1, LOCAL_PEER, GatewayAcquireV1(WRITER, core.boot_epoch, 1, MAX_LOCAL_TTL_MS, HASHES)
        )
        core.command(
            1,
            LOCAL_PEER,
            GatewayCommandV1(
                WRITER, core.boot_epoch, 2, MAX_LOCAL_TTL_MS, "base_link",
                0.04, 0.0, 0.0, "m1-0", "m1-0", HASHES,
            ),
        )
        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline and sport.state().vx_mps == 0.0:
            time.sleep(0.005)
        report = core.client_lost(1)
        assert report is not None
        sample = sport.state()
        return (
            {
                "reason": report.reason,
                "stop_rpc_completed": report.stop_rpc_completed,
                "stationary_confirmed": report.stationary_confirmed,
                "stop_sequence": report.stop_sequence,
                "phase": core.phase,
                "velocity": (sample.vx_mps, sample.vy_mps, sample.vyaw_rad_s),
            },
            ring,
        )
    finally:
        core.close()


def test_a_full_audit_ring_changes_no_stop_and_makes_evidence_exit_nonzero(
    tmp_path: Path,
) -> None:
    roomy, roomy_ring = _client_loss_stop_fields(capacity=512)
    tiny, tiny_ring = _client_loss_stop_fields(capacity=2)
    assert roomy == tiny
    assert roomy["velocity"] == (0.0, 0.0, 0.0)
    assert roomy_ring.dropped_records == 0
    assert tiny_ring.dropped_records > 0
    exporter = AuditExporterV1(tiny_ring, tmp_path / "audit.jsonl")
    assert _evidence_exit_code(roomy_ring, AuditExporterV1(roomy_ring, tmp_path / "ok.jsonl")) == 0
    assert _evidence_exit_code(tiny_ring, exporter) == 2


def test_a_failing_audit_exporter_changes_no_stop_and_exits_nonzero(tmp_path: Path) -> None:
    fields, ring = _client_loss_stop_fields(capacity=512)
    assert fields["velocity"] == (0.0, 0.0, 0.0)
    assert fields["stationary_confirmed"] is True
    exporter = AuditExporterV1(ring, tmp_path / "no-such-directory" / "audit.jsonl")
    exporter.flush()
    assert exporter.write_errors == 1
    assert _evidence_exit_code(ring, exporter) == 2


def test_the_exporter_writes_what_the_ring_held(tmp_path: Path) -> None:
    ring = BoundedAuditRingV1(capacity=8)
    ring.record("first", boot_epoch="e", phase="disarmed", note="hello")
    exporter = AuditExporterV1(ring, tmp_path / "audit.jsonl")
    exporter.flush()
    rows = [
        json.loads(line)
        for line in (tmp_path / "audit.jsonl").read_text(encoding="utf-8").splitlines()
        if line
    ]
    assert rows[0]["event"] == "first"
    assert rows[0]["note"] == "hello"
    assert ring.snapshot() == ()


# --------------------------------------------------------------------------
# over the real socket
# --------------------------------------------------------------------------


@pytest.fixture
def socket_dir() -> Path:
    """A short directory: ``sockaddr_un.sun_path`` is 108 bytes, and pytest's
    ``tmp_path`` plus these test names does not fit inside it."""

    made = Path(tempfile.mkdtemp(prefix="m10-"))
    try:
        yield made
    finally:
        shutil.rmtree(made, ignore_errors=True)


@requires_seqpacket
def test_the_socket_is_owner_only_and_opens_with_hello(socket_dir: Path) -> None:
    path = socket_dir / "gw.sock"
    with ServedGateway(path) as served:
        assert path.stat().st_mode & 0o777 == 0o600
        with served.client() as client:
            assert client.hello.phase is GatewayPhaseV1.DISARMED
            assert client.hello.boot_epoch == served.bench.core.boot_epoch
            assert client.hello.required_hashes == HASHES


@requires_seqpacket
def test_a_full_session_over_the_socket_moves_and_stops_at_exact_zero(
    socket_dir: Path,
) -> None:
    path = socket_dir / "gw.sock"
    with ServedGateway(path) as served:
        client = served.client()
        acquired = client.acquire(writer_id=WRITER, sequence=1)
        assert isinstance(acquired, GatewayAckV1)
        assert acquired.disposition is GatewayAckDispositionV1.ACCEPTED
        for sequence in range(2, 8):
            admitted = client.command(writer_id=WRITER, sequence=sequence, vx_mps=0.03)
            assert isinstance(admitted, GatewayAckV1)
            assert admitted.disposition is GatewayAckDispositionV1.ACCEPTED
            time.sleep(0.02)
        state = client.state(sequence=100)
        assert state.phase is GatewayPhaseV1.ARMED
        assert state.vx_mps == pytest.approx(0.03)
        assert not state.stationary
        client.close()
        deadline = time.monotonic() + 3.0
        while time.monotonic() < deadline and served.bench.core.stop_sequence < 2:
            time.sleep(0.005)
        assert served.bench.core.last_stop_reason == "client_disconnected"
        assert served.bench.vendor_is_exactly_zero()
        assert served.bench.core.phase is GatewayPhaseV1.DISARMED
        with served.client() as observer:
            after = observer.state(sequence=1)
            assert after.phase is GatewayPhaseV1.DISARMED
            assert after.stationary
            assert (after.vx_mps, after.vy_mps, after.vyaw_rad_s) == (0.0, 0.0, 0.0)


@requires_seqpacket
def test_malformed_bytes_over_the_socket_stop_the_vendor_and_latch(socket_dir: Path) -> None:
    path = socket_dir / "gw.sock"
    with ServedGateway(path) as served:
        client = served.client()
        client.acquire(writer_id=WRITER, sequence=1)
        client.command(writer_id=WRITER, sequence=2, vx_mps=0.03)
        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline and served.bench.vendor_velocity()[0] == 0.0:
            time.sleep(0.005)
        assert served.bench.vendor_velocity()[0] != 0.0
        client.send_raw(b'{"kind":"command","schema_version":2}')
        deadline = time.monotonic() + 3.0
        while time.monotonic() < deadline and served.bench.core.stop_sequence < 2:
            time.sleep(0.005)
        assert served.bench.core.last_stop_reason.startswith("protocol_fault:")
        assert served.bench.core.phase is GatewayPhaseV1.LATCHED
        assert served.bench.vendor_is_exactly_zero()
        with served.client() as observer:
            refused = observer.acquire(writer_id=WRITER, sequence=900)
            assert isinstance(refused, GatewayAckV1)
            assert refused.reason == "gateway_latched"


@requires_seqpacket
def test_a_response_kind_sent_by_a_client_is_a_protocol_fault(socket_dir: Path) -> None:
    path = socket_dir / "gw.sock"
    with ServedGateway(path) as served:
        client = served.client()
        client.acquire(writer_id=WRITER, sequence=1)
        client.command(writer_id=WRITER, sequence=2, vx_mps=0.03)
        client.send_raw(encode_gateway_message(served.bench.core.hello()))
        deadline = time.monotonic() + 3.0
        while time.monotonic() < deadline and served.bench.core.stop_sequence < 2:
            time.sleep(0.005)
        assert served.bench.core.phase is GatewayPhaseV1.LATCHED
        assert served.bench.vendor_is_exactly_zero()


@requires_seqpacket
def test_ttl_expiry_over_the_socket_stops_the_vendor_and_disarms(socket_dir: Path) -> None:
    """The same headline row as the in-process case, driven entirely over the wire."""

    path = socket_dir / "gw.sock"
    with ServedGateway(path) as served:
        client = served.client()
        client.acquire(writer_id=WRITER, sequence=1, ttl_ms=60)
        client.command(writer_id=WRITER, sequence=2, vx_mps=0.03, ttl_ms=60)
        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline and served.bench.vendor_velocity()[0] == 0.0:
            time.sleep(0.005)
        assert served.bench.vendor_velocity()[0] != 0.0
        # Stop feeding. Nothing in this test ticks the gateway.
        deadline = time.monotonic() + 3.0
        while time.monotonic() < deadline and served.bench.core.stop_sequence < 2:
            time.sleep(0.005)
        assert served.bench.core.last_stop_reason == "local_ttl_expired"
        assert served.bench.core.phase is GatewayPhaseV1.DISARMED
        assert served.bench.vendor_is_exactly_zero()
        assert served.bench.physical_events()[-1] == "stop_move_succeeded"
        late = client.command(writer_id=WRITER, sequence=3, vx_mps=0.03, ttl_ms=60)
        assert isinstance(late, GatewayAckV1)
        assert late.disposition is GatewayAckDispositionV1.REJECTED
        assert late.reason == "gateway_disarmed"
        client.close()


@requires_seqpacket
def test_a_prior_epoch_command_over_the_socket_stops_and_latches(socket_dir: Path) -> None:
    path = socket_dir / "gw.sock"
    with ServedGateway(path) as served:
        client = served.client()
        client.acquire(writer_id=WRITER, sequence=1)
        client.command(writer_id=WRITER, sequence=2, vx_mps=0.03)
        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline and served.bench.vendor_velocity()[0] == 0.0:
            time.sleep(0.005)
        assert served.bench.vendor_velocity()[0] != 0.0
        refused = client.command(
            writer_id=WRITER, sequence=3, vx_mps=0.03, boot_epoch="a-previous-boot"
        )
        assert isinstance(refused, GatewayAckV1)
        assert refused.reason == "boot_epoch_mismatch"
        assert served.bench.core.phase is GatewayPhaseV1.LATCHED
        assert served.bench.vendor_is_exactly_zero()
        assert served.bench.physical_events()[-1] == "stop_move_succeeded"
        client.close()


@requires_seqpacket
def test_a_second_connection_claiming_the_lease_over_the_socket_latches(
    socket_dir: Path,
) -> None:
    path = socket_dir / "gw.sock"
    with ServedGateway(path, policy=_policy(WRITER, SECOND_WRITER)) as served:
        first = served.client()
        first.acquire(writer_id=WRITER, sequence=1)
        first.command(writer_id=WRITER, sequence=2, vx_mps=0.03)
        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline and served.bench.vendor_velocity()[0] == 0.0:
            time.sleep(0.005)
        assert served.bench.vendor_velocity()[0] != 0.0
        second = served.client()
        conflict = second.acquire(writer_id=SECOND_WRITER, sequence=3)
        assert isinstance(conflict, GatewayAckV1)
        assert conflict.reason == "writer_conflict"
        assert served.bench.core.phase is GatewayPhaseV1.LATCHED
        assert served.bench.vendor_is_exactly_zero()
        assert served.bench.physical_events()[-1] == "stop_move_succeeded"
        first.close()
        second.close()


@requires_seqpacket
def test_a_peer_outside_the_uid_allowlist_never_reaches_the_protocol(
    socket_dir: Path,
) -> None:
    """The kernel names the peer; the policy answers before any byte is parsed."""

    path = socket_dir / "gw.sock"
    hostile = CredentialPolicyV1(
        required_hashes=HASHES,
        allowed_writer_ids=frozenset({WRITER}),
        allowed_uids=frozenset({os.geteuid() + 4242}),
    )
    with ServedGateway(path, policy=hostile) as served:
        with pytest.raises((ConnectionError, OSError, TypeError)):
            served.client()
        refused = served.bench.core.audit.events("peer_credential_refused")
        assert refused, "the connection was closed without naming the reason"
        # Nothing was armed, so nothing was stopped: only the boot stop exists.
        assert served.bench.core.stop_sequence == 1


# --------------------------------------------------------------------------
# GWF-007 / GWF-015 — what only real processes can show
# --------------------------------------------------------------------------


def _subprocess_env() -> dict[str, str]:
    environment = os.environ.copy()
    entries = [str(REPO), str(REPO / "src")]
    current = environment.get("PYTHONPATH")
    if current:
        entries.append(current)
    environment["PYTHONPATH"] = os.pathsep.join(entries)
    return environment


def _spawn_gateway(
    socket_path: Path,
    audit_log: Path,
    vendor_log: Path,
    *,
    writer_id: str,
) -> subprocess.Popen[str]:
    return subprocess.Popen(
        [
            sys.executable,
            "-m",
            "gateway.process",
            "--socket",
            str(socket_path),
            "--audit-log",
            str(audit_log),
            "--vendor-log",
            str(vendor_log),
            "--writer-id",
            writer_id,
        ],
        cwd=REPO,
        env=_subprocess_env(),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )


def _spawn_client(socket_path: Path, *, writer_id: str) -> subprocess.Popen[str]:
    return subprocess.Popen(
        [
            sys.executable,
            "-m",
            "gateway.bench_client",
            "--socket",
            str(socket_path),
            "--writer-id",
            writer_id,
            "--vx-mps",
            "0.04",
        ],
        cwd=REPO,
        env=_subprocess_env(),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )


def _rows(path: Path) -> list[dict[str, object]]:
    if not path.exists():
        return []
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _wait_until(
    predicate: object,
    *,
    processes: tuple[subprocess.Popen[str], ...] = (),
    timeout_s: float = 10.0,
) -> None:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        for process in processes:
            if process.poll() is not None:
                stdout, stderr = process.communicate()
                raise AssertionError(
                    f"subprocess exited early rc={process.returncode}\n{stdout}\n{stderr}"
                )
        if callable(predicate) and predicate():
            return
        time.sleep(0.02)
    raise AssertionError("timed out waiting for subprocess evidence")


def _connect_when_ready(
    socket_path: Path,
    gateway: subprocess.Popen[str],
) -> BenchGatewayClientV1:
    made: list[BenchGatewayClientV1] = []

    def connect() -> bool:
        try:
            made.append(BenchGatewayClientV1.connect(socket_path, timeout_s=0.2))
        except (FileNotFoundError, ConnectionRefusedError, TimeoutError, OSError):
            return False
        return True

    _wait_until(connect, processes=(gateway,))
    return made[0]


def _terminate(process: subprocess.Popen[str] | None) -> None:
    if process is None or process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=5.0)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5.0)


@requires_seqpacket
def test_a_sigkilled_client_stops_the_vendor_and_the_gateway_stays_disarmed(
    socket_dir: Path,
    tmp_path: Path,
) -> None:
    """No cleanup path exists: SIGKILL runs no ``finally`` in the client."""

    socket_path = socket_dir / "gw.sock"
    audit_log = tmp_path / "audit.jsonl"
    vendor_log = tmp_path / "vendor.jsonl"
    gateway = _spawn_gateway(socket_path, audit_log, vendor_log, writer_id="sigkill-client")
    client: subprocess.Popen[str] | None = None
    observer: BenchGatewayClientV1 | None = None
    try:
        probe = _connect_when_ready(socket_path, gateway)
        boot_epoch = probe.hello.boot_epoch
        assert probe.hello.phase is GatewayPhaseV1.DISARMED
        probe.close()

        client = _spawn_client(socket_path, writer_id="sigkill-client")
        _wait_until(
            lambda: any(row["event"] == "move_applied" for row in _rows(vendor_log)),
            processes=(gateway, client),
        )
        client.kill()
        client.wait(timeout=5.0)
        assert client.returncode == -signal.SIGKILL

        _wait_until(
            lambda: any(
                row["event"] == "gateway_stop_report"
                and row.get("reason") == "client_disconnected"
                and row.get("stationary_confirmed") == "True"
                for row in _rows(audit_log)
            ),
            processes=(gateway,),
        )
        physical = [
            str(row["event"])
            for row in _rows(vendor_log)
            if row["event"] in {"move_applied", "stop_move_succeeded"}
        ]
        assert physical[-1] == "stop_move_succeeded"

        observer = _connect_when_ready(socket_path, gateway)
        assert observer.hello.boot_epoch == boot_epoch
        assert observer.hello.phase is GatewayPhaseV1.DISARMED
        state = observer.state(sequence=1)
        assert state.phase is GatewayPhaseV1.DISARMED
        assert state.stationary
        assert (state.vx_mps, state.vy_mps, state.vyaw_rad_s) == (0.0, 0.0, 0.0)
        replay = observer.acquire(writer_id="sigkill-client", sequence=1)
        assert isinstance(replay, GatewayAckV1)
        assert replay.disposition is GatewayAckDispositionV1.REJECTED
        assert replay.reason == "client_sequence_not_increasing"
    finally:
        if observer is not None:
            observer.close()
        if client is not None and client.poll() is None:
            client.kill()
            client.wait(timeout=5.0)
        _terminate(gateway)


@requires_seqpacket
def test_a_restarted_gateway_process_has_a_new_epoch_and_is_disarmed(
    socket_dir: Path,
    tmp_path: Path,
) -> None:
    socket_path = socket_dir / "gw.sock"
    audit_log = tmp_path / "audit.jsonl"
    vendor_log = tmp_path / "vendor.jsonl"
    first = _spawn_gateway(socket_path, audit_log, vendor_log, writer_id=WRITER)
    second: subprocess.Popen[str] | None = None
    observer: BenchGatewayClientV1 | None = None
    try:
        probe = _connect_when_ready(socket_path, first)
        old_epoch = probe.hello.boot_epoch
        probe.close()
        _terminate(first)
        second = _spawn_gateway(socket_path, audit_log, vendor_log, writer_id=WRITER)
        observer = _connect_when_ready(socket_path, second)
        assert observer.hello.boot_epoch != old_epoch
        assert observer.hello.phase is GatewayPhaseV1.DISARMED
        stale = observer.acquire(writer_id=WRITER, sequence=1, boot_epoch=old_epoch)
        assert isinstance(stale, GatewayAckV1)
        assert stale.disposition is GatewayAckDispositionV1.REJECTED
        assert stale.reason == "boot_epoch_mismatch"
        assert observer.state(sequence=2).phase is GatewayPhaseV1.DISARMED
        # Both processes append to one audit log, and the second's exporter
        # pulls from its ring on its own period: wait for the evidence rather
        # than racing it.
        _wait_until(
            lambda: len(
                [row for row in _rows(audit_log) if row["event"] == "gateway_process_started"]
            )
            == 2,
            processes=(second,),
        )
        starts = [row for row in _rows(audit_log) if row["event"] == "gateway_process_started"]
        assert len(starts) == 2
        assert starts[0]["boot_epoch"] != starts[1]["boot_epoch"]
        assert all(row["phase"] == "disarmed" for row in starts)
        boots = [
            row
            for row in _rows(audit_log)
            if row["event"] == "gateway_stop_report" and row.get("reason") == "gateway_boot"
        ]
        assert len(boots) == 2
        assert all(row["stationary_confirmed"] == "True" for row in boots)
    finally:
        if observer is not None:
            observer.close()
        _terminate(second)
        _terminate(first)


@requires_seqpacket
def test_the_process_refuses_to_start_without_a_vendor_writer(tmp_path: Path) -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "gateway.process",
            "--socket",
            str(tmp_path / "unused.sock"),
            "--audit-log",
            str(tmp_path / "unused.jsonl"),
            "--sport",
            "vendor",
        ],
        cwd=REPO,
        env=_subprocess_env(),
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert result.returncode != 0
    assert "vendor" in result.stderr
    assert not (tmp_path / "unused.sock").exists()


# --------------------------------------------------------------------------
# the card's claim in one table: EVERY loss class ends at exact zero
# --------------------------------------------------------------------------


def _loss_client_death(made: Bench) -> StopOutcome:
    made.arm_and_move()
    assert made.core.client_lost(1) is not None
    return made.outcome()


def _loss_epoch_mismatch(made: Bench) -> StopOutcome:
    made.arm_and_move()
    made.command(boot_epoch="a-previous-boot")
    return made.outcome()


def _loss_contract_mismatch(made: Bench) -> StopOutcome:
    made.arm_and_move()
    made.command(hashes=OTHER_HASHES)
    return made.outcome()


def _loss_sequence_replay(made: Bench) -> StopOutcome:
    made.arm_and_move()
    made.command(sequence=2)
    return made.outcome()


def _loss_writer_conflict(made: Bench) -> StopOutcome:
    made.arm_and_move()
    made.acquire(writer_id=SECOND_WRITER, connection=2)
    return made.outcome()


def _loss_foreign_peer(made: Bench) -> StopOutcome:
    made.arm_and_move()
    made.command(peer=FOREIGN_PEER)
    return made.outcome()


def _loss_malformed_message(made: Bench) -> StopOutcome:
    made.arm_and_move()
    made.core.protocol_fault(1, "gateway packet is not strict UTF-8 JSON")
    return made.outcome()


def _loss_version_mismatch(made: Bench) -> StopOutcome:
    made.arm_and_move()
    made.core.protocol_fault(1, "unsupported gateway schema version 2")
    return made.outcome()


def _loss_watchdog_expiry(made: Bench) -> StopOutcome:
    made.arm_and_move(ttl_ms=40)
    return made.pump_until_stop()


def _loss_sport_lease(made: Bench) -> StopOutcome:
    made.arm_and_move()
    made.sport.force_lease_loss()
    return made.pump_until_stop()


def _loss_stale_feedback(made: Bench) -> StopOutcome:
    made.arm_and_move()
    made.sport.faults = FakeSportFaultsV1(stale_state_by_s=0.5)
    return made.pump_until_stop()


def _loss_out_of_order_feedback(made: Bench) -> StopOutcome:
    made.arm_and_move()
    made.sport.faults = FakeSportFaultsV1(out_of_order_state=True)
    return made.pump_until_stop()


def _loss_vendor_write_stall(made: Bench) -> StopOutcome:
    made.arm_and_move()
    made.sport.faults = FakeSportFaultsV1(move_no_reply=True)
    made.command(vx_mps=0.04)
    made.wait_for_vendor_event("move_no_reply")
    return made.pump_until_stop()


def _loss_emergency_stop(made: Bench) -> StopOutcome:
    made.arm_and_move()
    made.core.explicit_stop(
        1, LOCAL_PEER, GatewayStopV1(WRITER, made.core.boot_epoch, 900, "e-stop", True)
    )
    return made.outcome()


def _loss_gateway_shutdown(made: Bench) -> StopOutcome:
    made.arm_and_move()
    made.core.close()
    return made.outcome()


#: Every loss class the card names that one interpreter can produce.  The two
#: it cannot — a client killed with ``SIGKILL`` and a gateway restart — are the
#: subprocess tests above.
IN_PROCESS_LOSS_CLASSES = {
    "client_death": _loss_client_death,
    "boot_epoch_mismatch": _loss_epoch_mismatch,
    "contract_hash_mismatch": _loss_contract_mismatch,
    "sequence_replay": _loss_sequence_replay,
    "writer_conflict": _loss_writer_conflict,
    "foreign_peer": _loss_foreign_peer,
    "malformed_message": _loss_malformed_message,
    "version_mismatch": _loss_version_mismatch,
    "watchdog_expiry": _loss_watchdog_expiry,
    "sport_lease_lost": _loss_sport_lease,
    "stale_feedback": _loss_stale_feedback,
    "out_of_order_feedback": _loss_out_of_order_feedback,
    "vendor_write_stall": _loss_vendor_write_stall,
    "emergency_stop": _loss_emergency_stop,
    "gateway_shutdown": _loss_gateway_shutdown,
}


@pytest.mark.parametrize("loss", sorted(IN_PROCESS_LOSS_CLASSES))
def test_every_loss_class_ends_with_the_vendor_at_exact_zero(loss: str) -> None:
    made = Bench(policy=_policy(WRITER, SECOND_WRITER))
    try:
        outcome = IN_PROCESS_LOSS_CLASSES[loss](made)
        assert outcome.vendor_is_exactly_zero, f"{loss} left the vendor moving"
        assert outcome.last_vendor_action_was_a_stop, f"{loss}: {outcome.physical_events}"
        assert outcome.phase is not GatewayPhaseV1.ARMED
        assert made.core.active_writer is None
        assert made.core.stop_sequence >= 2
        # No auto-resume: whatever the loss was, motion does not come back on
        # its own, and the next command is refused rather than admitted.
        refused = made.command()
        assert refused.disposition is GatewayAckDispositionV1.REJECTED
        assert refused.reason in {"gateway_disarmed", "gateway_latched"}
    finally:
        made.close()


# --------------------------------------------------------------------------
# the soak
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class SoakResult:
    duration_s: float
    commands_sent: int
    writes_applied: int
    writes_refused: int
    deadline_violations: int
    superseded: int
    stops_during_soak: int
    stop_reason: str
    stop_after_last_command_s: float
    latency_ms: dict[str, float]
    watchdog_jitter_ms: dict[str, float]

    def render(self) -> str:
        return json.dumps(
            {
                "duration_s": round(self.duration_s, 3),
                "commands_sent": self.commands_sent,
                "writes_applied": self.writes_applied,
                "writes_refused": self.writes_refused,
                "deadline_violations": self.deadline_violations,
                "superseded": self.superseded,
                "stops_during_soak": self.stops_during_soak,
                "stop_reason": self.stop_reason,
                "stop_after_last_command_s": round(self.stop_after_last_command_s, 4),
                "command_to_vendor_latency_ms": self.latency_ms,
                "watchdog_jitter_ms": self.watchdog_jitter_ms,
            },
            indent=2,
            sort_keys=True,
        )


def _quantiles(values: list[float]) -> dict[str, float]:
    if not values:
        return {}
    ordered = sorted(values)

    def at(quantile: float) -> float:
        index = round(quantile * (len(ordered) - 1))
        return ordered[min(len(ordered) - 1, max(0, index))]

    return {
        "n": float(len(ordered)),
        "p50": round(at(0.50), 4),
        "p95": round(at(0.95), 4),
        "p99": round(at(0.99), 4),
        "max": round(ordered[-1], 4),
        "mean": round(statistics.fmean(ordered), 4),
    }


def _run_soak(
    path: Path,
    *,
    duration_s: float,
    hz: float = 50.0,
    ttl_ms: int = MAX_LOCAL_TTL_MS,
) -> SoakResult:
    outcomes: list[VendorWriteOutcomeV1] = []
    jitter: list[float] = []
    sent: dict[int, float] = {}
    lock = threading.Lock()

    def observe_write(outcome: VendorWriteOutcomeV1) -> None:
        with lock:
            outcomes.append(outcome)

    def observe_watchdog(interval_s: float) -> None:
        with lock:
            jitter.append(interval_s)

    served = ServedGateway(
        path,
        limits=default_limits(),
        write_observer=observe_write,
        watchdog_observer=observe_watchdog,
    )
    with served:
        core = served.bench.core
        client = served.client()
        acquired = client.acquire(writer_id=WRITER, sequence=1, ttl_ms=ttl_ms)
        assert isinstance(acquired, GatewayAckV1)
        assert acquired.disposition is GatewayAckDispositionV1.ACCEPTED, acquired.reason
        period = 1.0 / hz
        sequence = 2
        started = time.monotonic()
        target = started
        while time.monotonic() - started < duration_s:
            issued_at = time.monotonic()
            admitted = client.command(
                writer_id=WRITER, sequence=sequence, vx_mps=0.03, ttl_ms=ttl_ms
            )
            assert isinstance(admitted, GatewayAckV1)
            assert admitted.disposition is GatewayAckDispositionV1.ACCEPTED, admitted.reason
            sent[sequence] = issued_at
            sequence += 1
            target += period
            slack = target - time.monotonic()
            if slack > 0.0:
                time.sleep(slack)
            else:
                target = time.monotonic()
        elapsed = time.monotonic() - started
        last_command_at = time.monotonic()
        stops_during_soak = core.stop_sequence - 1
        # Stop feeding but keep the connection: only the TTL watchdog can end
        # this, and it must end it inside the TTL contract.
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline and core.stop_sequence < 2:
            time.sleep(0.002)
        stop_after = time.monotonic() - last_command_at
        stop_reason = core.last_stop_reason
        superseded = core.writer.superseded
        client.close()

    with lock:
        applied = [item for item in outcomes if item.outcome == "applied"]
        refused = [item for item in outcomes if item.outcome.startswith("refused:")]
        violations = [
            item for item in applied if item.at_monotonic_s >= item.write.deadline_monotonic_s
        ]
        latencies = [
            (item.at_monotonic_s - sent[item.write.client_sequence]) * 1000.0
            for item in applied
            if item.write.client_sequence in sent
        ]
        intervals = [value * 1000.0 for value in jitter]
    return SoakResult(
        duration_s=elapsed,
        commands_sent=len(sent),
        writes_applied=len(applied),
        writes_refused=len(refused),
        deadline_violations=len(violations),
        superseded=superseded,
        stops_during_soak=stops_during_soak,
        stop_reason=stop_reason,
        stop_after_last_command_s=stop_after,
        latency_ms=_quantiles(latencies),
        watchdog_jitter_ms=_quantiles(intervals),
    )


def _assert_soak_holds_the_ttl_contract(result: SoakResult, *, ttl_ms: int) -> None:
    assert result.deadline_violations == 0, result.render()
    assert result.writes_refused == 0, result.render()
    assert result.stops_during_soak == 0, result.render()
    assert result.writes_applied > 0
    assert result.stop_reason == "local_ttl_expired", result.render()
    # The watchdog owns the tail: one TTL plus a few of its own periods.
    ceiling = ttl_ms / 1000.0 + 4 * limits_module.GATEWAY_WATCHDOG_PERIOD_S + 0.2
    assert result.stop_after_last_command_s <= ceiling, result.render()


@requires_seqpacket
@pytest.mark.load_sensitive
def test_a_short_soak_at_50hz_holds_the_ttl_contract(socket_dir: Path) -> None:
    """The default-gate version of the soak: same assertions, seconds not minutes."""

    result = _run_soak(socket_dir / "gw.sock", duration_s=5.0)
    print("\nM1-0 short soak:\n" + result.render())
    _assert_soak_holds_the_ttl_contract(result, ttl_ms=MAX_LOCAL_TTL_MS)


@requires_seqpacket
@pytest.mark.slow
@pytest.mark.load_sensitive
def test_a_ten_minute_soak_at_50hz_holds_the_ttl_contract(socket_dir: Path) -> None:
    """The card's soak. Duration is overridable with ``PARCEL_M1_0_SOAK_S``."""

    duration = float(os.environ.get("PARCEL_M1_0_SOAK_S", "600"))
    result = _run_soak(socket_dir / "gw.sock", duration_s=duration)
    print("\nM1-0 ten-minute soak:\n" + result.render())
    _assert_soak_holds_the_ttl_contract(result, ttl_ms=MAX_LOCAL_TTL_MS)
    assert result.commands_sent >= int(duration * 45), result.render()


# --------------------------------------------------------------------------
# the inventory this suite claims to cover
# --------------------------------------------------------------------------

SEED_COVERAGE: dict[str, tuple[str, ...]] = {
    "GWF-001": (
        "test_a_prior_boot_epoch_never_acquires",
        "test_a_prior_boot_epoch_command_stops_and_latches",
        "test_a_prior_epoch_command_over_the_socket_stops_and_latches",
    ),
    "GWF-002": (
        "test_a_regressed_command_sequence_stops_and_latches",
        "test_a_captured_acquire_cannot_replay_after_the_client_dies",
    ),
    "GWF-003": ("test_the_schema_refuses_a_bad_duration_ttl",),
    "GWF-004": ("test_the_schema_refuses_non_finite_or_boolean_velocity",),
    "GWF-005": ("test_the_schema_refuses_a_body_frame_that_is_not_base_link",),
    "GWF-006": (
        "test_a_contract_hash_mismatch_on_a_command_stops_and_latches",
        "test_a_contract_hash_mismatch_on_an_acquire_is_refused",
    ),
    "GWF-007": (
        "test_a_sigkilled_client_stops_the_vendor_and_the_gateway_stays_disarmed",
        "test_client_loss_after_a_nonzero_admission_stops_and_cannot_auto_resume",
    ),
    "GWF-008": ("test_a_delayed_move_crossing_a_stop_epoch_is_followed_by_a_compensating_stop",),
    "GWF-009": ("test_a_move_that_never_replies_cannot_block_the_independent_stop",),
    "GWF-010": ("test_stale_feedback_stops_and_cannot_witness_stillness",),
    "GWF-011": (
        "test_out_of_order_feedback_stops_and_latches",
        "test_a_genuinely_regressed_feedback_sequence_is_named_out_of_order",
        "test_a_frozen_feedback_stream_stops_and_latches",
    ),
    "GWF-012": ("test_sport_lease_loss_stops",),
    "GWF-013": (
        "test_a_second_writer_stops_and_latches",
        "test_a_second_connection_claiming_the_lease_over_the_socket_latches",
    ),
    "GWF-014": (
        "test_a_failed_stopmove_is_never_reported_as_stationary_and_latches",
        "test_the_stop_report_dto_refuses_to_confirm_what_it_cannot_witness",
    ),
    "GWF-015": (
        "test_a_restarted_gateway_process_has_a_new_epoch_and_is_disarmed",
        "test_a_gateway_restart_zeroes_a_moving_vendor_and_mints_a_new_epoch",
        "test_each_boot_mints_a_new_epoch",
    ),
    "GWF-016": (
        "test_the_wire_refuses_every_malformed_packet_shape",
        "test_an_overlong_string_cannot_be_encoded_onto_the_wire",
        "test_malformed_bytes_over_the_socket_stop_the_vendor_and_latch",
    ),
    "GWF-017": (
        "test_an_admission_ack_is_not_motion_truth",
        "test_an_ack_cannot_be_built_that_claims_physical_truth",
    ),
    "GWF-018": (
        "test_ttl_expiry_over_the_socket_stops_the_vendor_and_disarms",
        "test_the_ttl_expires_on_the_receivers_own_clock",
        "test_the_threaded_watchdog_stops_on_ttl_expiry_with_no_help_from_the_test",
        "test_a_command_at_or_after_expiry_cannot_revive_authority",
    ),
    "GWF-019": (
        "test_a_full_audit_ring_changes_no_stop_and_makes_evidence_exit_nonzero",
        "test_a_failing_audit_exporter_changes_no_stop_and_exits_nonzero",
        "test_the_audit_ring_cannot_raise_on_a_hostile_detail_value",
    ),
}

INVARIANT_COVERAGE: dict[str, tuple[str, ...]] = {
    "GWI-001": (
        "test_a_fresh_gateway_boots_disarmed_and_stops_the_vendor_first",
        "test_each_boot_mints_a_new_epoch",
        "test_a_restarted_gateway_process_has_a_new_epoch_and_is_disarmed",
    ),
    "GWI-002": (
        "test_a_prior_boot_epoch_never_acquires",
        "test_a_prior_boot_epoch_command_stops_and_latches",
    ),
    "GWI-003": (
        "test_a_second_writer_stops_and_latches",
        "test_a_second_connection_claiming_the_lease_over_the_socket_latches",
        "test_a_writer_id_outside_the_allowlist_is_refused",
    ),
    "GWI-004": (
        "test_a_regressed_command_sequence_stops_and_latches",
        "test_a_captured_acquire_cannot_replay_after_the_client_dies",
    ),
    "GWI-005": (
        "test_only_a_duration_ttl_crosses_the_wire",
        "test_ttl_expiry_over_the_socket_stops_the_vendor_and_disarms",
        "test_the_ttl_expires_on_the_receivers_own_clock",
        "test_the_threaded_watchdog_stops_on_ttl_expiry_with_no_help_from_the_test",
    ),
    "GWI-006": (
        "test_client_loss_after_a_nonzero_admission_stops_and_cannot_auto_resume",
        "test_a_sigkilled_client_stops_the_vendor_and_the_gateway_stays_disarmed",
    ),
    "GWI-007": (
        "test_sport_lease_loss_stops",
        "test_stale_feedback_stops_and_cannot_witness_stillness",
        "test_out_of_order_feedback_stops_and_latches",
    ),
    "GWI-008": (
        "test_a_delayed_move_crossing_a_stop_epoch_is_followed_by_a_compensating_stop",
        "test_a_move_that_never_replies_cannot_block_the_independent_stop",
    ),
    "GWI-009": (
        "test_the_schema_refuses_a_bad_duration_ttl",
        "test_the_schema_refuses_non_finite_or_boolean_velocity",
        "test_the_schema_refuses_a_body_frame_that_is_not_base_link",
        "test_the_wire_refuses_every_malformed_packet_shape",
        "test_a_contract_hash_mismatch_on_a_command_stops_and_latches",
    ),
    "GWI-010": (
        "test_an_admission_ack_is_not_motion_truth",
        "test_an_ack_cannot_be_built_that_claims_physical_truth",
    ),
    "GWI-011": (
        "test_a_failed_stopmove_is_never_reported_as_stationary_and_latches",
        "test_the_stop_report_dto_refuses_to_confirm_what_it_cannot_witness",
    ),
    "GWI-012": (
        "test_a_full_audit_ring_changes_no_stop_and_makes_evidence_exit_nonzero",
        "test_a_failing_audit_exporter_changes_no_stop_and_exits_nonzero",
    ),
}


def test_every_frozen_fault_seed_and_invariant_has_a_named_case_in_this_file() -> None:
    """The suite cannot quietly stop covering the inventory it claims to cover."""

    assert set(SEED_COVERAGE) == {case.id for case in load_gateway_fault_seeds_v1()}
    assert set(INVARIANT_COVERAGE) == {item.id for item in load_gateway_invariants_v1()}
    named = [
        name
        for mapping in (SEED_COVERAGE, INVARIANT_COVERAGE)
        for names in mapping.values()
        for name in names
    ]
    missing = sorted({name for name in named if not callable(globals().get(name))})
    assert missing == []
    # Every fixture id a frozen invariant points at is itself a covered seed.
    for invariant in load_gateway_invariants_v1():
        assert set(invariant.fixture_ids) <= set(SEED_COVERAGE), invariant.id
