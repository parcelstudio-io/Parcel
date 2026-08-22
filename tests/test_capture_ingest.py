"""Card PS-G: the ingest layer that PS-1 shipped without.

``record.py:resolve_live_source`` refused for **every** transport and
``preflight.py`` defaulted to ``unavailable_reader_factory``, so the capture
stack had a recorder and nothing to record. The morning of the physical session
would have started with somebody writing subscriber code against a live,
battery-limited robot. This file is the gate on the fix.

None of ``rclpy``, ``pyrealsense2`` or ``unilidar_sdk2`` exists on this host and
the board forbids installing them, so the file is organised around what can
honestly be measured here and says so where it cannot:

* **G1 read-only** — the *ingest-specific* half of the no-arm argument: the
  allowlists on this package's three vendor facades, and the DDS session's
  attribute surface. The general pin no longer lives here. It lives in
  ``tests/test_no_arm_pin.py``, which globs **recursively** over
  ``src/parcel_robot/capture/`` and all of ``scripts/parcel_capture/``, folds
  string constants before matching them, censuses every reach builtin, and
  imports every module in a subprocess against a fake vendor SDK whose
  publisher-creating entry points raise. The version of G1 that used to live
  here globbed ``*.py`` in one directory and matched literal symbols; an
  auditor planted a module one directory down that published to ``/cmd_vel``
  and called ``SportClient().Move()``, and all 47 tests in this file passed.
  The tests below delegate to the tranche pin rather than keeping a second,
  weaker copy of it.
* **G2 refusal**   — every live adapter refuses on this box naming its module
  and a remedy, with no traceback anywhere.
* **G3 clock**     — a frame cannot carry a source timestamp on a channel whose
  matrix row declares no device clock. ``LowState``'s wrapping ``tick`` is the
  case that motivated it.
* **G4 decoders**  — the message-shape corrections from ``RISK_ASSESSMENT.md``
  (12 not 20 joints, both foot-force arrays, no BMS voltage, millivolts,
  ``range_obstacle``) are exercised against synthetic messages.
* **G5 path**      — ``FakeIngest`` drives the real interface end to end:
  adapter -> receipt -> preflight probe -> plausibility verdict, and
  adapter -> ``CaptureRecorder`` -> MCAP -> sidecar.
* **G6 census**    — every matrix channel either has an adapter or a *stated*
  reason it has none.
"""

from __future__ import annotations

import json
import math
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

# The no-arm pin is ONE pin for the whole tranche and it lives next door
# (tests/test_no_arm_pin.py). This file used to carry its own copy:
# ``PACKAGE.glob("*.py")`` plus a literal-symbol AST scan. That copy had two
# holes an audit walked straight through — the glob does not descend into
# subdirectories, and the scan is defeated by ordinary aliasing — so it is gone
# rather than kept alongside a stronger one. Two divergent pins is how a reader
# ends up trusting the weaker.
from test_no_arm_pin import capture_stack_files, static_violations

from parcel_robot.capture import CHANNELS, Transport, UnknownChannelError, channel
from parcel_robot.capture.channels import SourceClock, WireNaming, subscribe_name
from parcel_robot.evidence_origin import EvidenceOrigin
from scripts.parcel_capture import preflight as preflight_module
from scripts.parcel_capture.ingest import (
    LIVE_ADAPTERS,
    NEVER_ALLOWED,
    UNSERVED_TRANSPORTS,
    DdsIngest,
    DevicePresence,
    FakeIngest,
    IngestFrame,
    IngestRefusedError,
    IngestUnavailableError,
    L2Ingest,
    PayloadKind,
    ReadOnlyHandle,
    RealSenseIngest,
    adapter_for,
    channel_reader_factory,
    coverage,
    decoder_for_channel,
    dependency_report_text,
    ros_message_type,
    ros_subscribe_name,
)
from scripts.parcel_capture.ingest import base as ingest_base
from scripts.parcel_capture.ingest import dds as dds_module
from scripts.parcel_capture.ingest import l2 as l2_module
from scripts.parcel_capture.ingest import realsense as rs_module
from scripts.parcel_capture.preflight import (
    ChannelClass,
    PlausibilityVerdict,
    ProbeStatus,
    RestPeriod,
    SampleReceipt,
    assess_plausibility,
    classify_channel,
    probe_all_channels,
    probe_channel,
)
from scripts.parcel_capture.record import LiveSourceUnavailableError, resolve_live_source

PACKAGE = REPO / "scripts" / "parcel_capture" / "ingest"


# ---------------------------------------------------------------------------
# G1 — read-only: the ingest-specific half
# ---------------------------------------------------------------------------


def test_the_tranche_wide_no_arm_pin_covers_every_file_in_this_package() -> None:
    """Delegation, verified — not delegation assumed.

    Every ``.py`` file under ``scripts/parcel_capture/ingest/``, **recursively**,
    must be inside the tranche pin's file set and must be clean under its static
    rules. If somebody plants ``ingest/sub/armed_reader.py`` it lands here as
    well as in ``tests/test_no_arm_pin.py``; under the old local glob it landed
    in neither, and all 47 tests in this file passed with a module in the tree
    that published to ``/cmd_vel`` and called ``SportClient().Move()``.
    """

    pinned = {path.resolve() for path in capture_stack_files()}
    package_files = sorted(PACKAGE.rglob("*.py"))
    assert package_files, "the ingest package has no sources — the walk is broken"
    for path in package_files:
        assert path.resolve() in pinned, f"{path} is outside the tranche pin"
        relpath = path.resolve().relative_to(REPO).as_posix()
        assert static_violations(relpath, path.read_text(encoding="utf-8")) == [], relpath


def test_seeded_failure_the_tranche_pin_still_catches_what_this_file_used_to() -> None:
    """The mutants the deleted local pin checked, re-run through the new one.

    Every one of these was caught before; none may be lost in the handover. The
    two at the end are the ones the *old* pin missed — a name assembled at
    runtime, and a raw vendor object read off another object's mangled slot.
    """

    relpath = "scripts/parcel_capture/ingest/mutant.py"
    mutants = {
        "publisher": "node.create_publisher(Twist, 'cmd_vel', 10)",
        "sport_client": "from unitree_sdk2py.go2.sport.sport_client import SportClient",
        "vendor_sdk": "import unitree_sdk2py",
        "runtime": "import parcel_robot.runtime as rt",
        "lidar_mode": "reader.setLidarWorkMode(1)",
        "lidar_start": "reader.startLidar()",
        "device_reset": "device.hardware_reset()",
        "camera_option": "sensor.set_option(rs.option.exposure, 100)",
        "file_write": "def write(self, blob):\n    return blob\n",
        "move": "def move(self, command):\n    return command\n",
        # NEW: the two spellings the old pin let through.
        "assembled_name": "reach = getattr\nname = 'create_' + 'publisher'\n",
        "mangled_reach": "raw = session._SubscribeOnlySession__node\n",
    }
    for name, mutant in mutants.items():
        assert static_violations(relpath, mutant), f"mutant {name!r} slipped the pin"

    # ...and it does not fire on the sensor vocabulary the package legitimately
    # uses, which is what makes it a pin rather than noise.
    assert (
        static_violations(
            relpath,
            "topic = '/wirelesscontroller'\n"
            "kind = 'unitree_go/msg/LowState'\n"
            "subscription = session.subscribe(cls, topic, sink, 10)\n",
        )
        == []
    )


def test_the_facade_refuses_a_computed_reach_for_a_command_surface() -> None:
    """The runtime half of the pin: an AST scan cannot see ``getattr(x, name)``.

    A raw ``rclpy`` node has ``create_publisher`` on it. A handle does not
    resolve it, whether the name is written down or assembled at runtime.
    """

    class _FakeNode:
        def create_subscription(self, *args: object) -> str:
            return "subscription"

        def create_publisher(self, *args: object) -> str:  # pragma: no cover - never reached
            return "publisher"

    handle = ReadOnlyHandle(_FakeNode(), allowed=("create_subscription",), label="fake node")
    assert handle.create_subscription(1, 2, 3, 4) == "subscription"

    # Two independent refusal branches, and the assembled name must hit both
    # kinds. A name on NEVER_ALLOWED is refused at access time whatever the
    # allowlist says; any other unlisted name is refused by the allowlist.
    assembled = "create_" + "publisher"
    assert assembled in NEVER_ALLOWED
    with pytest.raises(IngestRefusedError) as caught:
        getattr(handle, assembled)
    assert "NEVER_ALLOWED" in str(caught.value)

    unlisted = "destroy_" + "node"
    assert unlisted not in NEVER_ALLOWED
    with pytest.raises(IngestRefusedError) as caught:
        getattr(handle, unlisted)
    assert "not on the read-only allowlist" in str(caught.value)

    # getattr's default does not swallow it either: the refusal is an exception
    # of our own type, not AttributeError.
    with pytest.raises(IngestRefusedError):
        getattr(handle, assembled, None)
    with pytest.raises(IngestRefusedError):
        handle.anything = 1


def test_seeded_failure_a_handle_cannot_be_configured_to_reach_a_never_allowed_name() -> None:
    """Defence in depth: the allowlist itself is checked against a denylist.

    A later editor who "just needs" ``startLidar`` cannot get it by widening the
    allowlist; the construction refuses.
    """

    for name in ("create_publisher", "startLidar", "set_option", "SportClient"):
        assert name in NEVER_ALLOWED
        with pytest.raises(IngestRefusedError) as caught:
            ReadOnlyHandle(object(), allowed=("get_name", name), label="widened")
        assert "cannot be configured into a writable one" in str(caught.value)


def test_the_l2_allowlist_contains_no_mode_changing_name() -> None:
    """The one sensor whose vendor API is genuinely bidirectional."""

    assert set(l2_module._READER_ALLOWLIST).isdisjoint(NEVER_ALLOWED)
    for name in ("startLidar", "stopLidar", "setLidarWorkMode"):
        assert name not in l2_module._READER_ALLOWLIST
        assert name in NEVER_ALLOWED


def test_the_rclpy_node_allowlist_has_three_names_and_no_publisher_among_them() -> None:
    assert dds_module._NODE_ALLOWLIST == ("create_subscription", "destroy_node", "get_name")
    assert set(dds_module._NODE_ALLOWLIST).isdisjoint(NEVER_ALLOWED)


def test_the_only_place_handed_a_raw_node_keeps_no_attribute_that_yields_it() -> None:
    """``_SubscribeOnlySession`` is the sole holder of a raw ``rclpy`` node.

    Its public surface is pinned so the reach cannot widen silently. The pin
    used to accept a name-mangled ``__node`` slot; the no-arm-pin card showed
    that ``session._SubscribeOnlySession__node`` is what mangling actually
    produces and that another module can read it in one line, so the session now
    keeps **no** attribute holding the node or the ``rclpy`` module at all —
    only the allowlisted handle and two :func:`sealed_call` closures. This test
    asserts the stronger property: no slot may name either one.

    The residual is stated rather than hidden: an in-process caller can still
    recover the node from a closure cell or through ``gc``, and
    ``tests/test_no_arm_pin.py`` is the tranche-wide pin that asserts that
    residual out loud. This test pins the attribute surface only.
    """

    session_class = dds_module._SubscribeOnlySession
    public = {name for name in vars(session_class) if not name.startswith("_")}
    assert public == {"subscribe", "spin_once", "close", "handle"}

    slots = set(session_class.__slots__)
    assert slots == {"_shutdown", "_spin", "_subscriptions", "handle"}
    # Neither the node nor the module survives as an attribute, by any spelling.
    for banned in ("node", "_node", "__node", "rclpy", "_rclpy", "context", "_context"):
        assert banned not in slots, banned
        assert not hasattr(session_class, banned), banned
    # And the two entry points that need the raw node as an ARGUMENT are bound
    # through sealed_call, which returns a function and keeps the binding in a
    # closure rather than on the instance.
    source = (PACKAGE / "dds.py").read_text(encoding="utf-8")
    assert source.count("sealed_call(") == 2


# ---------------------------------------------------------------------------
# G2 — every live adapter refuses here, actionably, with no traceback
# ---------------------------------------------------------------------------


def _hide_module(monkeypatch: pytest.MonkeyPatch, module_name: str) -> None:
    """Make ``find_spec(module_name)`` answer None, as if it were never installed.

    The module-absent arm of the guard below. ``rclpy`` and ``unilidar_sdk2``
    genuinely are absent here; ``pyrealsense2`` is not, since card P1-A
    installed it into ``.parcel`` on 2026-08-22 for the desk-camera venue. Both
    arms must be tested on every adapter regardless, because which of the two a
    given box is in changes with a `pip install` and the refusal contract must
    not.
    """

    import importlib.util

    real = importlib.util.find_spec

    def fake(name: str, package: str | None = None):
        if name == module_name:
            return None
        return real(name, package)

    monkeypatch.setattr(importlib.util, "find_spec", fake)


@pytest.mark.parametrize(
    ("factory", "module_name"),
    [
        (DdsIngest, "rclpy"),
        (RealSenseIngest, "pyrealsense2"),
        (L2Ingest, "unilidar_sdk2"),
    ],
)
def test_each_live_adapter_refuses_here_naming_the_missing_module_or_the_missing_device(
    factory: type, module_name: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Card ENV-1. Two arms, because "installed" and "attached" are two facts.

    The old form of this guard asserted ``not report.satisfied`` for all three
    adapters, which encoded an ENVIRONMENT PREMISE — "this box has no vendor
    SDK" — that stopped being true on 2026-08-22 when P1-A installed
    ``pyrealsense2`` for the desk camera. The PROPERTY it was protecting is
    kept and strengthened: **no live adapter ever reads on this box, and the
    refusal names which of the two things is missing, with a remedy, never a
    traceback.**

    * MODULE-ABSENT arm: ``dependency_missing``, module named, remedy names the
      Orin. Monkeypatched for whichever adapters happen to be installed here.
    * MODULE-PRESENT arm: the dependency probe is satisfied and the refusal
      moves to ``device_node_missing``, naming the ``/dev`` node that is not
      there. Exercised for real on ``pyrealsense2``; monkeypatched for the two
      whose SDKs are genuinely absent.
    """

    adapter = factory()
    entry = adapter.channels()[0]

    # --- arm 1: the module is not installed --------------------------------
    _hide_module(monkeypatch, module_name)
    report = adapter.dependency_report()
    assert not report.satisfied
    assert module_name in report.missing
    assert module_name in report.remedy
    assert "Orin" in report.remedy

    with pytest.raises(IngestUnavailableError) as caught:
        list(adapter.read(entry, 0.01))
    message = str(caught.value)
    assert module_name in message
    assert caught.value.reason.value == "dependency_missing"
    assert caught.value.remedy
    assert ".parcel/" in caught.value.remedy or "Orin" in caught.value.remedy

    # --- arm 2: the module IS installed, and no device is here -------------
    monkeypatch.undo()
    if not adapter.device_nodes:
        # dds and l2 reach the hardware over a network or a socket and declare
        # no /dev node; the filesystem cannot answer for them and must say so
        # rather than guessing "attached".
        assert adapter.device_report().presence is DevicePresence.NOT_ATTESTABLE
        return

    monkeypatch.setattr(
        type(adapter),
        "dependency_report",
        classmethod(
            lambda cls: ingest_base.DependencyReport(
                adapter=cls.adapter_name,
                satisfied=True,
                present=(module_name,),
                missing=(),
                remedy="",
            )
        ),
    )
    device = adapter.device_report()
    assert device.presence is DevicePresence.ABSENT, (
        f"a {module_name} device is attached to this host; this arm needs an empty bus"
    )

    with pytest.raises(IngestUnavailableError) as absent:
        list(adapter.read(entry, 0.01))
    assert absent.value.reason.value == "device_node_missing"
    assert "/dev/" in str(absent.value)
    assert "Traceback" not in str(absent.value)
    assert absent.value.remedy, "a device refusal with no remedy is one nobody can act on"
    assert "USB" in absent.value.remedy


def test_the_module_present_refusal_never_imported_the_vendor_sdk() -> None:
    """The device gate must run BEFORE the import, not after it.

    If the ``/dev`` census ran after the import — or not at all — a box with the
    wheel would load the vendor SDK to discover there is nothing to talk to, and
    ``test_a_full_preflight_run_never_imports_a_vendor_sdk`` would be measuring
    a property the code no longer has.

    Card ENV-1b: which refusal comes back depends on the venv, so the guard asks
    the venv instead of assuming it. ``pyrealsense2`` is installed in ``.parcel``
    (P1-A put it there for the desk camera) but the ``dev`` extra does not carry
    it — there is no aarch64 wheel, so adding it would break ``pip install .[dev]``
    on the Orin — and a fresh ``.[dev]`` venv therefore has no wheel at all. Both
    venvs must reach a *named* refusal with the SDK still unimported; only the
    reason differs, and the branch names which one this run measured.
    """

    import importlib.util

    wheel_installed = importlib.util.find_spec("pyrealsense2") is not None

    script = (
        "import sys;"
        f"sys.path.insert(0, {str(REPO)!r});"
        "from scripts.parcel_capture.ingest import RealSenseIngest, IngestUnavailableError;"
        "from parcel_robot.capture import channel;"
        "adapter = RealSenseIngest();"
        "print('SATISFIED', adapter.dependency_report().satisfied);"
        "\ntry:\n"
        "    list(adapter.read(channel('d455.color'), 0.01))\n"
        "except IngestUnavailableError as error:\n"
        "    print('REASON', error.reason.value)\n"
        "else:\n"
        "    print('REASON none')\n"
        "print('IMPORTED', 'pyrealsense2' in sys.modules)"
    )
    proc = subprocess.run(
        [sys.executable, "-B", "-c", script],
        capture_output=True,
        text=True,
        cwd=REPO,
        timeout=180,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    assert "Traceback" not in proc.stderr
    assert f"SATISFIED {wheel_installed}" in proc.stdout, proc.stdout
    if wheel_installed:
        # The module arm cannot fire, so the /dev census is the only thing that
        # can produce this refusal — and it produced it without the import.
        assert "REASON device_node_missing" in proc.stdout, proc.stdout
    else:
        # A fresh ``.[dev]`` venv: the module arm refuses first, by name.
        assert "REASON dependency_missing" in proc.stdout, proc.stdout
    # Either way the vendor SDK was never loaded. This half is the property.
    assert "IMPORTED False" in proc.stdout, proc.stdout


def test_no_adapter_import_ever_installs_or_imports_a_vendor_module() -> None:
    """The dependency probe uses ``find_spec``. Importing to check availability
    would already have done the thing the board forbids.

    Card GREEN-1: measured in a FRESH INTERPRETER, because ``sys.modules`` is
    process-global and this cell used to read whatever the rest of the sweep had
    already loaded into it. ``tests/test_venue1_physical_venue.py`` calls
    ``connected_devices()`` at MODULE scope (it feeds a ``skipif``), so
    ``pyrealsense2`` is in ``sys.modules`` before a single cell of this file
    runs — and the guard went red in the sweep while passing alone, for a reason
    that has nothing to do with the probe. Deleting the ``pyrealsense2`` line
    would have made it green and blind.

    The subprocess is the instrument the rest of the stack already uses for this
    question (``test_the_module_present_refusal_never_imported_the_vendor_sdk``
    directly above, ``test_a_full_preflight_run_never_imports_a_vendor_sdk`` in
    ``tests/test_capture_preflight.py``), and it measures the property STRICTLY
    HARDER than the in-process version did: the report now runs against a
    ``sys.modules`` nothing else has touched, so ``BEFORE`` is a real starting
    line rather than an accident of ordering, and ``pyrealsense2`` is checked
    AFTER the call too — which the in-process version could not do on a box
    where P1-A's wheel had already been dragged in by a neighbour.
    """

    script = (
        "import sys;"
        f"sys.path.insert(0, {str(REPO)!r});"
        "from scripts.parcel_capture.ingest import dependency_report_text;"
        "vendor = ('rclpy', 'pyrealsense2', 'unilidar_sdk2');"
        "print('BEFORE', sorted(m for m in vendor if m in sys.modules));"
        "text = dependency_report_text();"
        "print('AFTER', sorted(m for m in vendor if m in sys.modules));"
        "print('REPORTED', all(m in text for m in vendor))"
    )
    proc = subprocess.run(
        [sys.executable, "-B", "-c", script],
        capture_output=True,
        text=True,
        cwd=REPO,
        timeout=180,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    assert "Traceback" not in proc.stderr
    assert "BEFORE []" in proc.stdout, proc.stdout
    assert "AFTER []" in proc.stdout, proc.stdout
    # ...and the report was not empty of them: every vendor module is NAMED in
    # the text it produced without importing any of them, so "AFTER []" cannot
    # be satisfied by a probe that simply never ran.
    assert "REPORTED True" in proc.stdout, proc.stdout


def test_the_dependency_report_names_each_module_state_and_is_never_a_traceback() -> None:
    """Card ENV-1: three states, not two, and every module named in one of them.

    Was ``test_the_dependency_report_is_actionable_text_and_never_a_traceback``,
    which asserted every module appeared somewhere in the text. That held for
    the wrong reason once ``pyrealsense2`` was installed: the realsense line
    read a bare ``READY`` and the module's name only survived inside a note.
    A report that calls an adapter READY on a box with no camera is precisely
    the go/no-go lie this package exists to prevent, so the guard now asks the
    report to distinguish *absent* from *installed but no device*.

    Card ENV-1b: *which* of the two the realsense line shows is a fact about the
    venv, not about the code. ``.parcel`` has P1-A's wheel; a fresh
    ``pip install .[dev]`` venv does not (the ``dev`` extra cannot carry
    ``pyrealsense2`` — no aarch64 wheel, so it would break the Orin install). The
    guard therefore branches on ``find_spec`` and asserts the *other* state in
    the other venv, rather than skipping: in both, the line must be one of the
    two refusals and must never read a bare ``READY``.
    """

    import importlib.util

    text = dependency_report_text()
    assert "Traceback" not in text
    assert "usbfs_memory_mb" in text  # the reboot-required risk is printed, not buried

    lines = text.splitlines()

    def block(adapter_name: str) -> str:
        start = next(i for i, line in enumerate(lines) if line.startswith(adapter_name))
        end = next(
            (i for i in range(start + 1, len(lines)) if lines[i] == ""), len(lines)
        )
        return "\n".join(lines[start:end])

    dds_block = block("dds")
    assert "UNAVAILABLE (missing: rclpy)" in dds_block
    assert "not_attestable" in dds_block  # a dog on a network makes no /dev node

    l2_block = block("l2")
    assert "UNAVAILABLE (missing: unilidar_sdk2)" in l2_block

    # The module P1-A installed: present, and its device is not — or, in a venv
    # built from the `dev` extra alone, the module arm.
    rs_block = block("realsense")
    assert "READY" not in rs_block
    if importlib.util.find_spec("pyrealsense2") is None:
        assert "UNAVAILABLE (missing: pyrealsense2)" in rs_block
    else:
        assert "NO DEVICE (installed: pyrealsense2)" in rs_block
    # Both arms still name the device half, so an operator who installs the wheel
    # is not then handed a bare READY.
    assert "/dev/video*" in rs_block
    assert "USB 3 (BLUE)" in rs_block


def test_resolve_live_source_now_resolves_through_the_registry_and_still_refuses_here() -> None:
    """The blocking defect, at the seam where it lived.

    Before this card the second branch of ``resolve_live_source`` said "no live
    backend ships in card PS-B". It now resolves an adapter. On this box the
    first branch still fires, because ``rclpy`` is genuinely absent — but for a
    different reason than before, and the message says which.
    """

    with pytest.raises(LiveSourceUnavailableError) as caught:
        resolve_live_source(channel("go2.lowstate"))
    assert "rclpy" in str(caught.value)

    source = (REPO / "scripts" / "parcel_capture" / "record.py").read_text(encoding="utf-8")
    assert "no live backend ships in card PS-B" not in source
    assert "from .ingest import adapter_for" in source


# ---------------------------------------------------------------------------
# G3 — the fail-closed clock rule
# ---------------------------------------------------------------------------


def test_a_frame_cannot_carry_a_source_timestamp_on_a_channel_with_no_device_clock() -> None:
    """``LowState`` has no timestamp field at all — only ``tick``, a ``uint32``
    millisecond counter that WRAPS. A decoder that promoted it would produce a
    dataset that is wrong and looks right."""

    assert channel("go2.lowstate").source_clock is SourceClock.WRAPPING_COUNTER
    with pytest.raises(ingest_base.IngestContractError) as caught:
        IngestFrame(
            channel_id="go2.lowstate",
            host_monotonic_ns=1,
            host_realtime_ns=2,
            payload=b"{}",
            payload_kind=PayloadKind.DERIVED_SUMMARY,
            source_timestamp_ns=1234,
        )
    message = str(caught.value)
    assert "wrapping_counter" in message
    assert "wrong and looks right" in message


def test_the_same_rule_lets_a_real_anchor_through() -> None:
    """``SportModeState.stamp`` is the only real source-clock anchor the dog
    emits, and the constructor must not block it."""

    assert channel("go2.sportmodestate").source_clock is SourceClock.DEVICE_TIMESPEC
    frame = IngestFrame(
        channel_id="go2.sportmodestate",
        host_monotonic_ns=1,
        host_realtime_ns=2,
        payload=b"{}",
        payload_kind=PayloadKind.DERIVED_SUMMARY,
        source_timestamp_ns=1234,
    )
    assert frame.source_timestamp_ns == 1234
    assert frame.to_receipt().source_timestamp_ns == 1234


def test_the_d455_carries_no_anchor_until_the_uvc_metadata_question_is_settled() -> None:
    """Every D455 row is ``UNVERIFIED`` because the pip wheel is reported to drop
    per-frame metadata. The device value is recorded in the summary, never as a
    clock, and flipping the matrix row is what turns it on."""

    for channel_id in ("d455.color", "d455.accel"):
        assert channel(channel_id).source_clock is SourceClock.UNVERIFIED
        with pytest.raises(ingest_base.IngestContractError):
            IngestFrame(
                channel_id=channel_id,
                host_monotonic_ns=1,
                host_realtime_ns=2,
                payload=b"{}",
                payload_kind=PayloadKind.DERIVED_SUMMARY,
                source_timestamp_ns=99,
            )

    frame = rs_module.frame_from_realsense(
        channel("d455.accel"),
        _FakeMotionFrame(x=0.0, y=0.0, z=9.81, timestamp=123.5, domain="hardware_clock"),
    )
    assert frame.source_timestamp_ns is None
    summary = json.loads(frame.payload)
    assert summary["device_timestamp_ms"] == 123.5
    assert summary["timestamp_domain"] == "hardware_clock"


def test_a_frame_refuses_an_empty_payload_an_unknown_channel_and_a_wrong_kind() -> None:
    with pytest.raises(ingest_base.IngestContractError, match="not a message"):
        IngestFrame("go2.lowstate", 1, 2, b"", PayloadKind.DERIVED_SUMMARY)
    with pytest.raises(UnknownChannelError):
        IngestFrame("go2.not_a_channel", 1, 2, b"x", PayloadKind.DERIVED_SUMMARY)

    class _LyingAdapter(FakeIngest):
        adapter_name = "lying"

        def read_frames(self, entry, window_s):  # type: ignore[no-untyped-def]
            yield IngestFrame(entry.channel_id, 1, 2, b"x", PayloadKind.WIRE_BYTES)

    adapter = _LyingAdapter(channel_ids=["go2.lowstate"])
    with pytest.raises(ingest_base.IngestContractError, match="payload_kind"):
        list(adapter.read(channel("go2.lowstate"), 0.01))


# ---------------------------------------------------------------------------
# G4 — decoders, against the RISK_ASSESSMENT corrections
# ---------------------------------------------------------------------------


class _Bag:
    """A duck-typed stand-in for a generated ROS message."""

    def __init__(self, **fields: object) -> None:
        for key, value in fields.items():
            setattr(self, key, value)


class _FakeMotionFrame:
    def __init__(self, *, x: float, y: float, z: float, timestamp: float, domain: str) -> None:
        self.motion_data = _Bag(x=x, y=y, z=z)
        self.timestamp = timestamp
        self.timestamp_domain = _Bag(name=domain)
        self.frame_number = 7


def _low_state(*, motors: int = 20, padding_q: float = 0.0) -> _Bag:
    return _Bag(
        imu_state=_Bag(
            accelerometer=[0.02, -0.01, 9.80],
            gyroscope=[0.001, 0.0, -0.002],
            rpy=[0.0, 0.0, 0.1],
            quaternion=[1.0, 0.0, 0.0, 0.0],
            temperature=41,
        ),
        motor_state=[
            _Bag(
                q=(padding_q if index >= 12 else 0.1 * index),
                dq=0.0,
                ddq=0.0,
                tau_est=1.5,
                q_raw=0.1 * index,
                dq_raw=0.0,
                ddq_raw=0.0,
                temperature=35,
                lost=0,
            )
            for index in range(motors)
        ],
        foot_force=[12, 14, 11, 13],
        foot_force_est=[10, 15, 9, 12],
        power_v=28.6,
        power_a=1.25,
        bms_state=_Bag(cell_vol=[3800] * 15, soc=87, current=-1200),
        fan_frequency=[100, 101, 0, 0],
        temperature_ntc1=44,
        temperature_ntc2=45,
        wireless_remote=[0] * 40,
        tick=4_294_967_000,
    )


def test_low_state_decodes_twelve_joints_not_twenty() -> None:
    """``MotorState[20]`` is a fixed union array; a Go2 has 12 actuated joints.

    Decoding all twenty would report eight dropped channels that never existed.
    """

    _samples, summary = dds_module.decode_low_state(_low_state())
    assert summary["motor_state_declared_len"] == 20
    assert summary["actuated_joints"] == 12
    assert len(summary["motor_state"]) == 12
    assert summary["motor_state_padding_nonzero"] == []


def test_low_state_reports_non_zero_padding_as_a_finding_not_as_sensors() -> None:
    _samples, summary = dds_module.decode_low_state(_low_state(padding_q=0.5))
    assert summary["motor_state_padding_nonzero"] == list(range(12, 20))
    assert any("12 actuated joints" in note for note in summary["findings"])
    assert len(summary["motor_state"]) == 12  # still twelve; the finding is a finding


def test_low_state_records_both_foot_force_arrays() -> None:
    """Their difference is free evidence about which one is sensed."""

    samples, summary = dds_module.decode_low_state(_low_state())
    foot = next(s for s in samples if type(s).__name__ == "FootForceSample")
    assert foot.counts == (12, 14, 11, 13)
    assert foot.counts_est == (10, 15, 9, 12)
    assert summary["foot_force"] != summary["foot_force_est"]


def test_bms_has_no_voltage_field_so_the_decoder_converts_millivolts_and_records_both() -> None:
    """Correction 6: ``BmsState`` carries no voltage. Pack voltage is
    ``power_v`` or ``sum(cell_vol)``, and ``cell_vol`` is MILLIVOLTS — PS-J's
    ``PowerSample`` is documented in volts and refuses to guess units."""

    samples, summary = dds_module.decode_low_state(_low_state())
    power = next(s for s in samples if type(s).__name__ == "PowerSample")
    assert power.power_v == 28.6
    assert power.power_a == 1.25
    assert all(math.isclose(value, 3.8) for value in power.cell_volts)
    assert math.isclose(summary["bms_cell_sum_v"], 57.0)


def test_the_substitution_when_power_v_is_absent_is_recorded_not_silent() -> None:
    message = _low_state()
    del message.power_v
    samples, summary = dds_module.decode_low_state(message)
    power = next(s for s in samples if type(s).__name__ == "PowerSample")
    assert math.isclose(power.power_v, 57.0)
    assert any("BmsState itself has no voltage field" in note for note in summary["findings"])
    assert "power_v" not in summary["missing_fields"]


def test_tick_is_recorded_as_a_wrapping_counter_and_never_as_a_clock() -> None:
    _samples, summary = dds_module.decode_low_state(_low_state())
    assert summary["tick_ms"] == 4_294_967_000
    assert summary["tick_modulus"] == 1 << 32
    assert "stamp_ns" not in summary

    frame = dds_module.frame_from_message(channel("go2.lowstate"), _low_state())
    assert frame.source_timestamp_ns is None


def test_a_missing_field_is_recorded_as_missing_rather_than_crashing_the_probe() -> None:
    """Every row of the matrix is documentation about *other* Go2 EDUs. A
    decoder that assumes a field exists turns a documentation error into a
    crashed probe forty minutes into a battery."""

    message = _low_state()
    del message.foot_force
    del message.wireless_remote
    _samples, summary = dds_module.decode_low_state(message)
    assert "foot_force" in summary["missing_fields"]
    assert "wireless_remote" in summary["missing_fields"]
    assert summary["power_v"] == 28.6  # the rest of the message still decoded


def test_sport_mode_state_carries_range_obstacle_and_the_dogs_only_clock_anchor() -> None:
    """``range_obstacle[4]`` is the only non-LiDAR proximity sensing on the dog
    and appeared in no PS-1 document."""

    message = _Bag(
        stamp=_Bag(sec=1_700_000_000, nanosec=500_000_000),
        imu_state=_Bag(accelerometer=[0.0, 0.0, 9.81], gyroscope=[0.0, 0.0, 0.0]),
        range_obstacle=[1.5, 1.6, 1.4, 1.7],
        foot_force=[9, 8, 10, 11],
        position=[1.0, 2.0, 0.3],
        velocity=[0.1, 0.0, 0.0],
        yaw_speed=0.02,
        mode=1,
        gait_type=0,
        error_code=0,
        body_height=0.32,
        foot_raise_height=0.09,
        foot_position_body=[0.0] * 12,
        foot_speed_body=[0.0] * 12,
    )
    samples, summary = dds_module.decode_sport_mode_state(message)
    assert summary["range_obstacle"] == [1.5, 1.6, 1.4, 1.7]
    assert summary["stamp_ns"] == 1_700_000_000_500_000_000

    frame = dds_module.frame_from_message(channel("go2.sportmodestate"), message)
    assert frame.source_timestamp_ns == 1_700_000_000_500_000_000
    assert len(samples) == 2


def test_a_declared_anchor_that_the_message_does_not_carry_is_null_not_substituted() -> None:
    message = _Bag(imu_state=_Bag(accelerometer=[0.0, 0.0, 9.81]))
    frame = dds_module.frame_from_message(channel("go2.sportmodestate"), message)
    assert frame.source_timestamp_ns is None
    summary = json.loads(frame.payload)
    assert any("null" in note for note in summary["findings"])


def test_the_imu_decoder_passes_the_1e24_pathology_through_unclamped() -> None:
    """Two independent field reports describe ``utlidar/imu`` emitting
    ~-2.17e24 m/s^2. PS-J's sensor-range rule exists to FAIL on it; a decoder
    that sanitised it here would attest a broken IMU as healthy."""

    message = _Bag(
        header=_Bag(stamp=_Bag(sec=5, nanosec=6)),
        linear_acceleration=_Bag(x=-2.17e24, y=-2.17e24, z=-2.17e24),
        angular_velocity=_Bag(x=0.0, y=0.0, z=0.0),
        orientation=_Bag(x=0.0, y=0.0, z=0.0, w=1.0),
    )
    samples, summary = dds_module.decode_imu(message)
    assert samples[0].accel_mps2 == (-2.17e24, -2.17e24, -2.17e24)
    assert summary["stamp_ns"] == 5_000_000_006

    verdict = assess_plausibility(channel("go2.utlidar.imu"), (
        SampleReceipt("go2.utlidar.imu", 1, 32, measurements=samples),
    )).verdict
    assert verdict is PlausibilityVerdict.FAIL


def test_point_cloud_fields_are_recorded_verbatim_and_ranges_are_decoded() -> None:
    """``fields[]`` is the single most session-critical thing here that is
    unrecoverable after power-down."""

    import struct as _struct

    points = b"".join(
        _struct.pack("<fff", 1.0 * index, 0.0, 0.0) + _struct.pack("<f", 0.5)
        for index in range(1, 5)
    )
    message = _Bag(
        header=_Bag(stamp=_Bag(sec=1, nanosec=0)),
        height=1,
        width=4,
        point_step=16,
        data=points,
        is_dense=True,
        fields=[
            _Bag(name="x", offset=0, datatype=7, count=1),
            _Bag(name="y", offset=4, datatype=7, count=1),
            _Bag(name="z", offset=8, datatype=7, count=1),
            _Bag(name="intensity", offset=12, datatype=7, count=1),
        ],
    )
    samples, summary = dds_module.decode_point_cloud2(message)
    assert samples[0].field_names == ("x", "y", "z", "intensity")
    assert samples[0].point_count == 4
    assert samples[0].ranges_m == (1.0, 2.0, 3.0, 4.0)
    assert [item["name"] for item in summary["fields"]] == ["x", "y", "z", "intensity"]


def test_an_unrecognised_cloud_layout_is_refused_rather_than_decoded_on_a_guess() -> None:
    message = _Bag(
        height=1,
        width=2,
        point_step=6,
        data=b"\x00" * 12,
        fields=[
            _Bag(name="x", offset=0, datatype=3, count=1),
            _Bag(name="y", offset=2, datatype=3, count=1),
            _Bag(name="z", offset=4, datatype=3, count=1),
        ],
    )
    samples, summary = dds_module.decode_point_cloud2(message)
    assert samples[0].ranges_m == ()
    assert samples[0].field_names == ("x", "y", "z")
    assert any("not a single float layout" in note for note in summary["findings"])


def test_an_undecoded_message_yields_no_measurement_and_says_so() -> None:
    """Empty measurements produce UNKNOWN downstream, never PASS."""

    samples, summary = dds_module.decode_generic(_Bag(header=_Bag(stamp=_Bag(sec=0, nanosec=1))))
    assert samples == ()
    assert "no typed decoder" in summary["note"]


def test_the_l2_decoder_records_the_sdk_field_names_verbatim() -> None:
    cloud = _Bag(
        stamp=1.5,
        ringNum=4,
        points=[_Bag(x=1.0, y=0.0, z=0.0, intensity=10.0, time=0.001, ring=1)],
    )
    samples, summary = l2_module.decode_l2_cloud(cloud)
    assert samples[0].field_names == ("x", "y", "z", "intensity", "time", "ring")
    assert summary["stamp_ns"] == 1_500_000_000


# ---------------------------------------------------------------------------
# G4b — naming: the failure that is silent by construction
# ---------------------------------------------------------------------------


def test_the_ros_subscriber_name_is_never_the_raw_dds_wire_name() -> None:
    """A raw-DDS reader on an unmangled name gets zero messages and no error;
    an rclpy subscriber on the MANGLED name gets the same silence."""

    entry = channel("go2.lowstate")
    assert ros_subscribe_name(entry) == "/lowstate"
    assert subscribe_name(entry.channel_id, WireNaming.RAW_DDS) == "rt/lowstate"
    for item in CHANNELS:
        if item.transport is Transport.DDS:
            assert not ros_subscribe_name(item).startswith("/rt/")


def test_the_ros_name_lookup_refuses_a_channel_that_is_not_addressed_by_a_topic() -> None:
    with pytest.raises(IngestRefusedError, match="not\n?.*addressed by a ROS topic name"):
        ros_subscribe_name(channel("l2.cloud"))


def test_the_wire_message_type_is_translated_to_a_ros_interface_name() -> None:
    assert ros_message_type(channel("go2.lowstate")) == "unitree_go/msg/LowState"
    assert ros_message_type(channel("go2.utlidar.cloud")) == "sensor_msgs/msg/PointCloud2"


# ---------------------------------------------------------------------------
# G5 — the whole path, driven by the synthetic backend
# ---------------------------------------------------------------------------


def test_the_fake_backend_drives_a_real_preflight_probe_to_present() -> None:
    """The interface is exercised end to end on a box with no ROS at all."""

    adapter = FakeIngest(channel_ids=["go2.lowstate", "go2.utlidar.cloud"])
    factory = channel_reader_factory(adapter)
    entry = channel("go2.lowstate")
    probe = probe_channel(entry, factory(entry), window_s=0.2, expected_rate_hz=500.0)
    assert probe.status is ProbeStatus.PRESENT
    assert probe.messages_received == 100


def test_a_silent_channel_reads_as_absent_and_not_as_an_error() -> None:
    adapter = FakeIngest(channel_ids=["go2.lowstate"], silent=["go2.lowstate"])
    factory = channel_reader_factory(adapter)
    entry = channel("go2.lowstate")
    probe = probe_channel(entry, factory(entry), window_s=0.05, expected_rate_hz=500.0)
    assert probe.status is ProbeStatus.ABSENT
    assert probe.absence is not None
    assert probe.messages_received == 0


def test_a_rate_deficit_is_detected_through_the_real_probe() -> None:
    adapter = FakeIngest(channel_ids=["go2.lowstate"], rate_scale={"go2.lowstate": 0.5})
    factory = channel_reader_factory(adapter)
    entry = channel("go2.lowstate")
    probe = probe_channel(entry, factory(entry), window_s=0.2, expected_rate_hz=500.0)
    assert probe.status is ProbeStatus.DEGRADED
    assert probe.messages_received == 50


def test_an_implausible_channel_is_recorded_and_fails_the_plausibility_gate() -> None:
    """A suspect channel is evidence: it stays PRESENT and is still recorded.
    What changes is that the attestation says so."""

    adapter = FakeIngest(
        channel_ids=["go2.utlidar.imu"], implausible=["go2.utlidar.imu"]
    )
    entry = channel("go2.utlidar.imu")
    frames = list(adapter.read(entry, 0.2))
    receipts = tuple(frame.to_receipt() for frame in frames)
    probe = probe_channel(entry, lambda *_: receipts, window_s=0.2, expected_rate_hz=200.0)
    assert probe.status is ProbeStatus.PRESENT

    plausibility = assess_plausibility(
        entry, receipts, rest=RestPeriod(attested_by="test", note="synthetic")
    )
    assert plausibility.verdict is PlausibilityVerdict.FAIL
    assert any("sensor_range" in rule or "range" in rule for rule in plausibility.failed_rules)


def test_probe_all_channels_runs_over_the_whole_matrix_through_the_adapter_seam() -> None:
    """A factory that refuses for a channel it does not serve must not cost the
    other channels their report."""

    adapter = FakeIngest(channel_ids=["go2.lowstate"])
    probes = probe_all_channels(
        reader_factory=channel_reader_factory(adapter), window_s=0.02
    )
    assert len(probes) == len(CHANNELS)
    by_id = {probe.channel_id: probe for probe in probes}
    assert by_id["go2.lowstate"].status is ProbeStatus.PRESENT
    assert by_id["d455.color"].status is ProbeStatus.ABSENT


def test_frames_flow_into_the_parcel_recorder_and_out_through_the_sidecar(tmp_path) -> None:
    """The SECONDARY path, end to end: adapter -> recorder -> MCAP -> sidecar."""

    from scripts.parcel_capture.record import CaptureRecorder, SpaceBudget, read_mcap
    from scripts.parcel_capture.sidecar import BagFormat, RecorderRole, build_sidecar

    channel_ids = ["go2.lowstate", "go2.sportmodestate"]
    adapter = FakeIngest(channel_ids=channel_ids)
    entries = [channel(item) for item in channel_ids]
    bag = tmp_path / "secondary.mcap"
    recorder = CaptureRecorder(
        bag,
        bag_id="ingest-secondary",
        channels=entries,
        origin=EvidenceOrigin.SIMULATION,
        budget=SpaceBudget(bytes_per_second=100_000, duration_s=60),
        fixture_label="ps-g-fake-ingest",
    )
    feed = ingest_base.RecorderFeed(adapter)
    for entry in entries:
        feed.pump(recorder, entry, 0.1)
    recorder.close(reason="test complete")

    scan = read_mcap(bag)
    assert scan.is_clean
    assert scan.counts() == {"go2.lowstate": 50, "go2.sportmodestate": 5}

    sidecar = build_sidecar(bag_id="ingest-secondary", mcap_path=bag, scan=scan)
    assert sidecar["capture"]["bag_format"] == BagFormat.PARCEL_MCAP.value
    assert sidecar["capture"]["role"] == RecorderRole.SECONDARY.value
    assert any(
        "never be the sole copy" in line for line in sidecar["does_not_prove"]
    )


def test_the_fake_backend_is_deterministic_byte_for_byte() -> None:
    """Same construction, same frames, same bytes. A rehearsal whose payloads
    move cannot be digest-bound, and a digest that moves proves nothing."""

    pinned = {"channel_ids": ["go2.lowstate"], "epoch_ns": 1_000_000_000,
              "realtime_epoch_ns": 1_700_000_000_000_000_000}
    first = list(FakeIngest(**pinned).read(channel("go2.lowstate"), 0.05))
    second = list(FakeIngest(**pinned).read(channel("go2.lowstate"), 0.05))
    assert [frame.payload for frame in first] == [frame.payload for frame in second]
    assert [frame.host_monotonic_ns for frame in first] == [
        frame.host_monotonic_ns for frame in second
    ]


def test_the_synthetic_backend_is_not_in_the_live_registry() -> None:
    """A synthetic backend must never be selected by accident on the day."""

    assert FakeIngest not in LIVE_ADAPTERS
    assert set(LIVE_ADAPTERS) == {DdsIngest, RealSenseIngest, L2Ingest}


# ---------------------------------------------------------------------------
# G6 — the census: every channel has a reader or a stated reason
# ---------------------------------------------------------------------------


def test_every_matrix_channel_either_has_an_adapter_or_a_stated_reason() -> None:
    census = coverage()
    assert len(census["served"]) + len(census["unserved"]) == len(CHANNELS)
    assert len(census["served"]) == 23
    for channel_id in census["unserved"]:
        entry = channel(channel_id)
        assert entry.transport in UNSERVED_TRANSPORTS, channel_id
        assert UNSERVED_TRANSPORTS[entry.transport].strip()


def test_the_dds_adapter_claims_exactly_the_fifteen_dds_rows() -> None:
    dds_rows = [entry.channel_id for entry in CHANNELS if entry.transport is Transport.DDS]
    assert len(dds_rows) == 15
    assert [entry.channel_id for entry in DdsIngest().channels()] == dds_rows


def test_adapter_for_refuses_an_unserved_channel_with_the_reason_in_the_message() -> None:
    with pytest.raises(IngestRefusedError) as caught:
        adapter_for(channel("uwb.owner_fob"))
    assert "undocumented" in str(caught.value)
    with pytest.raises(IngestRefusedError) as caught:
        adapter_for(channel("go2.front_camera_h264"))
    assert "media stack" in str(caught.value)


def test_the_front_cameras_jpeg_twin_is_served_even_though_its_h264_path_is_not() -> None:
    """Correction 1: the front camera IS on the DDS topic set, as JPEG per frame.
    Only the H.264 elementary stream is RTP-over-multicast."""

    adapter = adapter_for(channel("go2.front_camera"))
    assert isinstance(adapter, DdsIngest)
    assert channel("go2.front_camera").transport is Transport.DDS
    assert channel("go2.front_camera_h264").transport is Transport.VENDOR_VIDEO


# ---------------------------------------------------------------------------
# G7 — decoder/rule agreement. PS-N finding 2, made structural.
# ---------------------------------------------------------------------------
#
# ``go2.sportmodestate`` is CRITICALITY.CRITICAL. Its live DDS decoder emits an
# ``ImuSample`` and a ``FootForceSample`` for every message. And
# ``preflight.classify_channel`` returned ``()`` for it, so the plausibility
# layer had no rule to apply and every one of those measurements was discarded
# before any rule saw it: ``samples_assessed == 0``, verdict UNKNOWN, forever,
# on the channel that carries the dog's only real source-clock anchor and its
# only non-LiDAR proximity sensing.
#
# Fixing that one row is not the fix. The fix is that the class of bug cannot
# recur: below, every channel in the matrix is run through the decoder the live
# adapters would actually use, against a synthetic message with every field its
# decoder reads populated, and the sample types that come out are required to
# have rules. A new decoder, or a new channel, or a new sample type, fails here
# until the rules exist.


def _synthetic_imu_state() -> _Bag:
    return _Bag(
        accelerometer=[0.02, -0.01, 9.80],
        gyroscope=[0.001, 0.0, -0.002],
        rpy=[0.0, 0.0, 0.1],
        quaternion=[1.0, 0.0, 0.0, 0.0],
        temperature=41,
    )


def _sport_mode_state() -> _Bag:
    return _Bag(
        stamp=_Bag(sec=1_700_000_000, nanosec=250_000_000),
        imu_state=_synthetic_imu_state(),
        foot_force=[12, 14, 11, 13],
        range_obstacle=[1.5, 1.6, 1.4, 1.7],
        mode=1,
        gait_type=0,
        error_code=0,
        body_height=0.32,
        foot_raise_height=0.09,
        position=[0.0, 0.0, 0.32],
        velocity=[0.0, 0.0, 0.0],
        yaw_speed=0.0,
        foot_position_body=[0.0] * 12,
        foot_speed_body=[0.0] * 12,
    )


def _ros_imu() -> _Bag:
    return _Bag(
        header=_Bag(stamp=_Bag(sec=1_700_000_000, nanosec=5_000_000), frame_id="imu"),
        linear_acceleration=_Bag(x=0.02, y=-0.01, z=9.80),
        angular_velocity=_Bag(x=0.001, y=0.0, z=-0.002),
        orientation=_Bag(x=0.0, y=0.0, z=0.0, w=1.0),
    )


def _point_cloud2() -> _Bag:
    import struct as _struct

    points = [(1.0, 0.0, 0.0), (0.0, 2.0, 0.0), (0.0, 0.0, 3.0), (4.0, 0.0, 0.0)]
    blob = b"".join(_struct.pack("<ffff", x, y, z, 7.0) for x, y, z in points)
    return _Bag(
        header=_Bag(stamp=_Bag(sec=1_700_000_000, nanosec=0), frame_id="lidar"),
        height=1,
        width=len(points),
        point_step=16,
        row_step=16 * len(points),
        is_dense=True,
        data=blob,
        fields=[
            _Bag(name="x", offset=0, datatype=7, count=1),
            _Bag(name="y", offset=4, datatype=7, count=1),
            _Bag(name="z", offset=8, datatype=7, count=1),
            _Bag(name="intensity", offset=12, datatype=7, count=1),
        ],
    )


def _l2_cloud() -> _Bag:
    return _Bag(
        stamp=1.5,
        ringNum=4,
        points=[
            _Bag(x=1.0, y=0.0, z=0.0, intensity=10.0, time=0.001, ring=1),
            _Bag(x=0.0, y=2.0, z=0.0, intensity=11.0, time=0.002, ring=2),
        ],
    )


def _l2_imu() -> _Bag:
    return _Bag(
        stamp=2.5,
        linear_acceleration=[0.01, -0.02, 9.79],
        angular_velocity=[0.0, 0.001, 0.0],
    )


def _rs_video_frame() -> _Bag:
    return _Bag(
        width=848,
        height=480,
        bytes_per_pixel=2,
        stride=1696,
        frame_number=11,
        timestamp=1234.5,
        timestamp_domain=_Bag(name="hardware_clock"),
    )


#: One fully-populated synthetic message per decoder the adapters can dispatch
#: to, keyed by the decoder's own ``__name__``. Keyed by decoder rather than by
#: channel on purpose: a channel list here would be the second enumeration this
#: tranche keeps deleting, and a new decoder with no fixture fails loudly below
#: rather than being quietly skipped.
DECODER_FIXTURES = {
    "decode_low_state": _low_state,
    "decode_sport_mode_state": _sport_mode_state,
    "decode_imu": _ros_imu,
    "decode_point_cloud2": _point_cloud2,
    "decode_generic": lambda: _Bag(header=_Bag(stamp=_Bag(sec=1, nanosec=2))),
    "decode_l2_cloud": _l2_cloud,
    "decode_l2_imu": _l2_imu,
    "decode_motion_frame": lambda: _FakeMotionFrame(
        x=0.02, y=-0.01, z=9.80, timestamp=99.5, domain="hardware_clock"
    ),
    "decode_video_frame": _rs_video_frame,
}


def _decoder_name(decoder) -> str:
    """The underlying function's name, through ``functools.partial`` if needed."""

    direct = getattr(decoder, "__name__", None)
    if direct is not None:
        return direct
    return decoder.func.__name__


def _samples_a_decoder_emits(entry) -> tuple[type, ...]:
    """Run this channel's real decoder over a populated message; return the types."""

    decoder = decoder_for_channel(entry)
    name = _decoder_name(decoder)
    assert name in DECODER_FIXTURES, (
        f"{entry.channel_id} dispatches to {name}, which has no synthetic message here. "
        f"A decoder with no fixture cannot be checked against the rule set, which is "
        f"exactly how go2.sportmodestate went unnoticed — add one."
    )
    samples, summary = decoder(DECODER_FIXTURES[name]())
    assert isinstance(summary, dict) and "missing_fields" in summary
    return tuple(dict.fromkeys(type(sample) for sample in samples))


def test_no_channel_whose_decoder_emits_samples_has_an_empty_rule_set() -> None:
    """PS-N finding 2, as a property rather than a patched row.

    For every channel in the matrix: run the decoder the live adapter would run,
    and for every kind of physical sample that comes out, require that
    ``classify_channel`` names the rule set that consumes it. A decoder that
    emits an ``ImuSample`` into a channel with no IMU rule is a measurement
    thrown away in silence, which is the one thing this layer must never do.

    Fails on the pre-fix code at ``go2.sportmodestate`` and
    ``go2.lf.sportmodestate``, whose decoder emits ``ImuSample`` +
    ``FootForceSample`` and whose rule set was ``()``.
    """

    sample_type_to_class = {
        sample_type: channel_class
        for channel_class, sample_type in preflight_module._CLASS_SAMPLE_TYPE.items()
    }
    checked = 0
    for entry in CHANNELS:
        try:
            emitted = _samples_a_decoder_emits(entry)
        except IngestRefusedError:
            continue  # no live adapter serves it; G6 already states why
        checked += 1
        if not emitted:
            continue
        classes = set(classify_channel(entry))
        for sample_type in emitted:
            assert sample_type in sample_type_to_class, (
                f"{entry.channel_id}: its decoder emits {sample_type.__name__}, which no "
                f"ChannelClass consumes — the plausibility layer would discard it"
            )
            required = sample_type_to_class[sample_type]
            assert required in classes, (
                f"{entry.channel_id}: decoder {_decoder_name(decoder_for_channel(entry))} "
                f"emits {sample_type.__name__} but classify_channel returned "
                f"{sorted(item.value for item in classes)} — every one of those samples "
                f"is discarded by the plausibility layer, silently"
            )
    assert checked == 23, checked


def test_seeded_failure_the_structural_pin_catches_a_decoder_whose_rules_were_removed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The refutation: with the fix reverted for one row, the pin fires.

    ``classify_channel`` is patched to return ``()`` for ``SportModeState``
    exactly as it did before PS-N, and the structural test above must fail. A
    pin that passes against the bug it was written for is not a pin.
    """

    real = preflight_module.classify_channel

    def reverted(entry):
        if "sportmodestate" in entry.message_type.strip().lower():
            return ()
        return real(entry)

    monkeypatch.setattr(preflight_module, "classify_channel", reverted)
    monkeypatch.setattr(
        sys.modules[test_no_channel_whose_decoder_emits_samples_has_an_empty_rule_set.__module__],
        "classify_channel",
        reverted,
    )
    with pytest.raises(AssertionError, match="discarded by the plausibility layer"):
        test_no_channel_whose_decoder_emits_samples_has_an_empty_rule_set()


def test_the_sport_mode_state_decoder_really_does_emit_both_kinds_of_sample() -> None:
    """The premise of the finding, measured rather than asserted.

    If this decoder stopped emitting samples the structural pin above would go
    quiet for the right reason; this test makes the premise visible so that
    silence would be noticed.
    """

    samples, summary = dds_module.decode_sport_mode_state(_sport_mode_state())
    kinds = sorted(type(sample).__name__ for sample in samples)
    assert kinds == ["FootForceSample", "ImuSample"]
    assert summary["stamp_ns"] == 1_700_000_000_250_000_000
    assert summary["range_obstacle"] == [1.5, 1.6, 1.4, 1.7]
    assert summary["missing_fields"] == []

    classes = set(classify_channel(channel("go2.sportmodestate")))
    assert classes == {ChannelClass.IMU, ChannelClass.FOOT_FORCE}
    # And NOT power: SportModeState carries no power_v and no BmsState, so a
    # POWER rule would park a CRITICAL channel at UNKNOWN for the whole session
    # with nothing to rule on.
    assert ChannelClass.POWER not in classes


def test_every_decoder_dispatch_is_reached_and_refuses_outside_its_own_channels() -> None:
    """The dispatch functions the structural pin leans on, exercised directly."""

    reached = {_decoder_name(decoder_for_channel(entry)) for entry in CHANNELS
               if entry.transport in {Transport.DDS, Transport.REALSENSE,
                                      Transport.UNILIDAR_SDK2}}
    assert reached == set(DECODER_FIXTURES)

    with pytest.raises(IngestRefusedError, match="not an L2 channel"):
        l2_module.decoder_for(channel("go2.lowstate"))
    with pytest.raises(IngestRefusedError, match="no RealSense stream profile"):
        rs_module.decoder_for(channel("go2.lowstate"))
    with pytest.raises(IngestRefusedError, match="has no decoder"):
        decoder_for_channel(channel("orin.tegrastats"))
    with pytest.raises(IngestRefusedError, match="expected a Channel"):
        decoder_for_channel("go2.lowstate")


# ---------------------------------------------------------------------------
# G8 — the live read paths, driven by fake SDKs. PS-N finding 3.
# ---------------------------------------------------------------------------
#
# 202 of 743 executable lines in the three live adapters had never executed, and
# the status doc claimed the decoders were exercised. Neither ``rclpy`` nor
# ``pyrealsense2`` nor ``unilidar_sdk2`` may be installed here — that absence is
# the tranche's motion guarantee — so the honest maximum is a **test double** in
# ``sys.modules``: minimal, read-only, and asserted to have had none of its
# command surfaces touched. What that reaches is the transport loop, the frame
# builders, and every decoder error branch. What it does NOT reach is the vendor
# libraries themselves; the residual is counted and named in PSN_STATUS.md.

import importlib.machinery
import types


def _fake_module(name: str) -> types.ModuleType:
    """A module object ``importlib.util.find_spec`` will report as present."""

    module = types.ModuleType(name)
    module.__spec__ = importlib.machinery.ModuleSpec(name, loader=None)
    return module


class _Tripwire:
    """Any attribute reach that is not expected raises. The double is not inert."""

    def __init__(self) -> None:
        self.touched: list[str] = []


@pytest.fixture
def fake_rclpy(monkeypatch: pytest.MonkeyPatch):
    """A read-only ``rclpy`` double that delivers three ``LowState`` messages."""

    delivered = _low_state()
    log: dict[str, object] = {"subscribed": [], "spins": 0, "destroyed": 0, "shutdown": 0}

    class _Node:
        def __init__(self, name: str, context: object) -> None:
            self.name = name
            self.context = context
            self.sinks: list = []

        def create_subscription(self, message_class, topic, sink, depth):
            log["subscribed"].append((message_class, topic, depth))
            self.sinks.append(sink)
            return object()

        def destroy_node(self) -> None:
            log["destroyed"] = int(log["destroyed"]) + 1

        def get_name(self) -> str:
            return self.name

        def create_publisher(self, *args, **kwargs):  # pragma: no cover - must never run
            raise AssertionError("the adapter reached a publisher")

    holder: dict[str, _Node] = {}

    rclpy = _fake_module("rclpy")
    node_module = _fake_module("rclpy.node")

    class _Context:
        pass

    def _init(*, context):
        log["init_context"] = context

    def _node(name, *, context):
        holder["node"] = _Node(name, context)
        return holder["node"]

    def _spin_once(node, *, timeout_sec):
        log["spins"] = int(log["spins"]) + 1
        if int(log["spins"]) <= 3:
            for sink in node.sinks:
                sink(delivered)

    def _shutdown(*, context):
        log["shutdown"] = int(log["shutdown"]) + 1

    rclpy.Context = _Context
    rclpy.init = _init
    rclpy.spin_once = _spin_once
    rclpy.shutdown = _shutdown
    rclpy.node = node_module
    node_module.Node = _node

    unitree_go = _fake_module("unitree_go")
    unitree_msg = _fake_module("unitree_go.msg")
    unitree_msg.LowState = type("LowState", (), {})
    unitree_go.msg = unitree_msg

    for name, module in (
        ("rclpy", rclpy),
        ("rclpy.node", node_module),
        ("unitree_go", unitree_go),
        ("unitree_go.msg", unitree_msg),
    ):
        monkeypatch.setitem(sys.modules, name, module)
    return log


def test_the_dds_read_loop_executes_end_to_end_against_a_read_only_double(
    fake_rclpy,
) -> None:
    """The ``rclpy`` branch of ``dds.py``, executed in-process for the first time.

    Everything here is the real adapter: ``require_dependencies``,
    ``open_session``, ``_SubscribeOnlySession``'s sealed calls, the subscribe,
    the spin loop, ``frame_from_message``, and ``close``. Only the module behind
    them is a double.
    """

    entry = channel("go2.lowstate")
    adapter = DdsIngest(node_name="ps_n_probe", queue_depth=7)
    assert adapter.dependency_report().satisfied

    frames = list(adapter.read(entry, 0.02))
    assert frames, "the loop yielded nothing — it did not execute"
    assert {frame.channel_id for frame in frames} == {"go2.lowstate"}
    assert all(frame.payload_kind is PayloadKind.DERIVED_SUMMARY for frame in frames)
    # LowState carries no device clock: the frame constructor refuses one, and
    # the decoder records ``tick`` as a counter instead.
    assert all(frame.source_timestamp_ns is None for frame in frames)
    payload = json.loads(frames[0].payload.decode("utf-8"))
    assert payload["actuated_joints"] == 12
    assert payload["tick_modulus"] == 1 << 32

    # The subscription used the ROS name and the configured depth, and the
    # session was closed exactly once through the sealed shutdown.
    (subscription,) = fake_rclpy["subscribed"]
    assert subscription[1] == "/lowstate"
    assert subscription[2] == 7
    assert fake_rclpy["destroyed"] == 1
    assert fake_rclpy["shutdown"] == 1


def test_the_dds_session_holds_the_node_only_behind_the_allowlist(fake_rclpy) -> None:
    """The session is constructed for real here, so the facade is exercised, not
    merely inspected."""

    adapter = DdsIngest()
    session = adapter.open_session()
    try:
        assert session.handle.get_name() == "parcel_capture_ingest"
        with pytest.raises(IngestRefusedError):
            getattr(session.handle, "create_" + "publisher")
    finally:
        session.close()
    assert fake_rclpy["shutdown"] == 1


def test_the_message_class_lookup_resolves_and_refuses_for_named_reasons(
    fake_rclpy, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``_message_class`` is the Orin-only path that turns a matrix row into a
    generated type. Both refusals name a remedy an operator can run."""

    assert dds_module._message_class(channel("go2.lowstate")) is sys.modules[
        "unitree_go.msg"
    ].LowState

    # The interface exists in the package but not under that name.
    with pytest.raises(IngestUnavailableError) as caught:
        dds_module._message_class(channel("go2.sportmodestate"))
    assert "has no interface named" in str(caught.value)
    assert "ros2 interface show" in caught.value.remedy

    # The package itself is missing.
    monkeypatch.delitem(sys.modules, "unitree_go.msg")
    monkeypatch.delitem(sys.modules, "unitree_go")
    with pytest.raises(IngestUnavailableError) as caught:
        dds_module._message_class(channel("go2.lowstate"))
    assert "is not importable" in str(caught.value)
    assert "never install it into .parcel/" in caught.value.remedy


@pytest.fixture
def fake_unilidar(monkeypatch: pytest.MonkeyPatch):
    return _install_fake_unilidar(monkeypatch, attached=True)


def _install_fake_unilidar(monkeypatch: pytest.MonkeyPatch, *, attached: object = True):
    """A ``unilidar_sdk2`` double. ``attached`` is what ``checkInit()`` reports.

    ``attached=False`` models a freshly constructed ``UnitreeLidarReader()``,
    which is exactly what this adapter holds: the constructor does not open the
    socket, so every getter returns nothing forever.
    """

    log: dict[str, object] = {"clouds": 0, "imus": 0, "checks": 0}
    no_check = attached is None

    class _Reader:
        def checkInit(self):
            log["checks"] = int(log["checks"]) + 1
            if isinstance(attached, BaseException):
                raise attached
            return attached

        def getPointCloud(self):
            log["clouds"] = int(log["clouds"]) + 1
            if not attached:
                return None
            return _l2_cloud() if int(log["clouds"]) <= 2 else None

        def getImu(self):
            log["imus"] = int(log["imus"]) + 1
            if not attached:
                return None
            return _l2_imu() if int(log["imus"]) <= 2 else None

        def startLidar(self):
            raise AssertionError("the adapter changed the LiDAR's mode")

    if no_check:
        del _Reader.checkInit

    module = _fake_module("unilidar_sdk2")
    module.UnitreeLidarReader = _Reader
    monkeypatch.setitem(sys.modules, "unilidar_sdk2", module)
    return log


def test_the_l2_read_loop_executes_for_both_of_its_channels(fake_unilidar) -> None:
    adapter = L2Ingest()
    assert adapter.dependency_report().satisfied

    cloud_frames = list(adapter.read(channel("l2.cloud"), 0.02))
    assert cloud_frames
    cloud = json.loads(cloud_frames[0].payload.decode("utf-8"))
    assert cloud["fields"] == ["x", "y", "z", "intensity", "time", "ring"]
    assert cloud["point_count"] == 2

    imu_frames = list(adapter.read(channel("l2.imu"), 0.02))
    assert imu_frames
    assert any(
        type(sample).__name__ == "ImuSample" for sample in imu_frames[0].measurements
    )
    assert fake_unilidar["clouds"] >= 2 and fake_unilidar["imus"] >= 2


def test_the_l2_handle_cannot_reach_a_mode_change_even_though_the_double_has_one(
    fake_unilidar,
) -> None:
    """The double deliberately ships ``startLidar``; the handle still cannot."""

    handle = L2Ingest().open_reader()
    assert callable(handle.getPointCloud)
    for name in ("startLidar", "stopLidar", "setLidarWorkMode"):
        with pytest.raises(IngestRefusedError):
            getattr(handle, name)


def _rs_motion_frame() -> object:
    return _FakeMotionFrame(x=0.01, y=-0.02, z=9.81, timestamp=77.0, domain="hardware_clock")


def _install_fake_realsense(
    monkeypatch: pytest.MonkeyPatch, *, honours_config: bool, devices: int = 1
):
    """A ``pyrealsense2`` double that either honours ``rs.config`` or ignores it.

    ``honours_config=False`` models what librealsense actually does when the
    pipeline is started with no config: it runs the DEFAULT profile — depth and
    colour — whatever stream the caller meant.

    ``devices`` is card ENV-1's addition: the double now also models the BUS.
    Every read-loop test below is about what happens once a camera is attached,
    so the default stages one — both halves of the presence question, the
    ``/dev`` census and ``rs.context().query_devices()``. ``devices=0`` stages
    the wheel-installed, empty-bus host this dev box actually is.
    """

    log: dict[str, object] = {
        "started": 0, "stopped": 0, "polls": 0, "queried": 0, "enabled": []
    }

    class _Config:
        def __init__(self) -> None:
            self.streams: list = []

        def enable_stream(self, stream, index=0):
            self.streams.append((stream, index))
            log["enabled"].append((stream, index))

    class _Pipeline:
        def __init__(self) -> None:
            self.config = None
            self.polls = 0  # per pipeline: one read must not starve the next

        def start(self, *args):
            log["started"] = int(log["started"]) + 1
            self.config = args[0] if args else None

        def stop(self):
            log["stopped"] = int(log["stopped"]) + 1

        def poll_for_frames(self):
            log["polls"] = int(log["polls"]) + 1
            self.polls += 1
            if self.polls > 2:
                return []
            if not honours_config or self.config is None:
                return [_rs_video_frame()]  # the DEFAULT profile: colour
            kinds = {name for name, _index in self.config.streams}
            if kinds & {"accel", "gyro"}:
                return [_rs_motion_frame()]
            return [_rs_video_frame()]

        def hardware_reset(self):  # pragma: no cover - must never run
            raise AssertionError("the adapter reset the device")

    class _Context:
        def query_devices(self):
            log["queried"] = int(log["queried"]) + 1
            return [_Bag(serial=f"D455-{index}") for index in range(devices)]

    module = _fake_module("pyrealsense2")
    module.pipeline = _Pipeline
    module.config = _Config
    module.context = _Context
    # ``rs.stream`` is an enum namespace; the names are all that matter here.
    module.stream = _Bag(color="color", depth="depth", infrared="infrared",
                         accel="accel", gyro="gyro")
    module.format = _Bag(rgb8="rgb8", z16="z16", y8="y8", motion_xyz32f="motion_xyz32f")
    monkeypatch.setitem(sys.modules, "pyrealsense2", module)
    # The /dev census is import-free and runs BEFORE the import, so a double
    # installed into sys.modules is not enough to reach the read loop: the node
    # this host does not have has to be staged too.
    monkeypatch.setattr(
        rs_module.RealSenseIngest,
        "device_report",
        classmethod(
            lambda cls: ingest_base.DeviceReport(
                adapter=cls.adapter_name,
                presence=(
                    ingest_base.DevicePresence.ATTACHED
                    if devices
                    else ingest_base.DevicePresence.ABSENT
                ),
                detail=f"staged: {devices} device(s) on the bus",
                remedy="plug the D455 into a USB 3 (BLUE) port",
                nodes=tuple(f"/dev/video{index}" for index in range(devices)),
            )
        ),
    )
    return log


@pytest.fixture
def fake_realsense(monkeypatch: pytest.MonkeyPatch):
    return _install_fake_realsense(monkeypatch, honours_config=True)


def test_the_realsense_read_loop_executes_and_never_configures_the_device(
    fake_realsense,
) -> None:
    adapter = RealSenseIngest()
    assert adapter.dependency_report().satisfied

    frames = list(adapter.read(channel("d455.color"), 0.02))
    assert frames
    summary = json.loads(frames[0].payload.decode("utf-8"))
    assert summary["width"] == 848 and summary["height"] == 480
    assert summary["timestamp_domain"] == "hardware_clock"
    # The UVC-metadata question is unsettled, so the device number is evidence
    # in the summary and NEVER a source clock on the frame.
    assert summary["device_timestamp_ms"] == 1234.5
    assert frames[0].source_timestamp_ns is None
    assert fake_realsense["started"] == 1 and fake_realsense["stopped"] == 1

    handle = adapter.open_pipeline(channel("d455.depth"))
    with pytest.raises(IngestRefusedError):
        getattr(handle, "hardware_" + "reset")
    with pytest.raises(IngestRefusedError):
        getattr(handle, "set_option")  # noqa: B009 - the point is the getattr route


def test_the_realsense_pipeline_refuses_a_channel_with_no_declared_profile(
    fake_realsense,
) -> None:
    with pytest.raises(IngestRefusedError, match="no RealSense stream profile"):
        RealSenseIngest().open_pipeline(channel("go2.lowstate"))
    with pytest.raises(IngestRefusedError, match="no RealSense stream profile"):
        RealSenseIngest().stream_selection(channel("go2.lowstate"))


# ---------------------------------------------------------------------------
# G8b — my own finding: the pipeline was UNCONFIGURED, so preflight could report
# the D455's gyroscope PRESENT on the strength of colour pixels.
# ---------------------------------------------------------------------------


def test_the_pipeline_is_started_against_a_config_naming_this_channels_stream(
    fake_realsense,
) -> None:
    """As shipped, ``read_frames`` called ``handle.start()`` with no argument.

    librealsense then runs its DEFAULT profile — depth + colour — for every one
    of the six D455 rows, which makes them indistinguishable. Measured before
    the fix, with a double modelling exactly that: reading ``d455.gyro`` for
    10 ms yielded 1094 colour frames and ``probe_channel`` reported the
    gyroscope PRESENT with 935 messages.
    """

    adapter = RealSenseIngest()
    frames = list(adapter.read(channel("d455.gyro"), 0.02))
    assert fake_realsense["enabled"] == [("gyro", 0)]
    assert frames, "the gyro stream was selected but nothing came back"
    assert all(len(frame.measurements) == 1 for frame in frames)

    fake_realsense["enabled"].clear()
    list(adapter.read(channel("d455.infra2"), 0.02))
    # infra1 and infra2 are the SAME stream type at two indices; without the
    # index they are one channel wearing two names.
    assert fake_realsense["enabled"] == [("infrared", 2)]

    fake_realsense["enabled"].clear()
    list(adapter.read(channel("d455.infra1"), 0.02))
    assert fake_realsense["enabled"] == [("infrared", 1)]

    fake_realsense["enabled"].clear()
    list(adapter.read(channel("d455.color"), 0.02))
    assert fake_realsense["enabled"] == [("color", 0)]


def test_seeded_failure_a_pipeline_that_ignores_the_config_reads_absent_not_present(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The fail-closed gate behind the config, on the exact defect.

    A build (or a device) that hands back the default profile anyway must not
    turn colour frames into evidence about the gyroscope. Every such frame is
    discarded, the channel reads ABSENT, and ABSENT is the correct answer.

    Pre-fix, this same double produced ``ProbeStatus.PRESENT`` with 935 messages.
    """

    _install_fake_realsense(monkeypatch, honours_config=False)
    entry = channel("d455.gyro")
    adapter = RealSenseIngest()

    frames = list(adapter.read(entry, 0.02))
    assert frames == [], "colour frames were counted as gyroscope samples"

    probe = probe_channel(
        entry, channel_reader_factory(adapter)(entry), window_s=0.02, expected_rate_hz=None
    )
    assert probe.status is ProbeStatus.ABSENT
    assert probe.messages_received == 0

    # ...while the channel the default profile REALLY delivers still reads.
    colour = channel("d455.color")
    assert list(adapter.read(colour, 0.02))


def test_a_webcam_on_dev_video_is_not_a_realsense_and_the_enumeration_says_so(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Card ENV-1, the precise half of the presence question.

    ``/dev/video*`` is created by ANY UVC camera, so the import-free census
    passes on a laptop with a built-in webcam and no RealSense. Without a second
    gate the adapter then imports the SDK, calls ``pipeline.start()``, and the
    operator is told ``probe_raised — RuntimeError`` with no device named and no
    remedy — which is verbatim what this box printed for all six D455 rows
    before this card. ``rs.context().query_devices()`` is the check that can
    tell the two apart, and it runs once the SDK is legitimately in memory.
    """

    log = _install_fake_realsense(monkeypatch, honours_config=True, devices=0)
    # The census says a camera-shaped node exists; librealsense says it is not
    # one of ours. The refusal must come from the second fact.
    monkeypatch.setattr(
        rs_module.RealSenseIngest,
        "device_report",
        classmethod(
            lambda cls: ingest_base.DeviceReport(
                adapter=cls.adapter_name,
                presence=ingest_base.DevicePresence.ATTACHED,
                detail="staged: a UVC webcam is on /dev/video0",
                remedy="",
                nodes=("/dev/video0",),
            )
        ),
    )

    with pytest.raises(IngestUnavailableError) as caught:
        list(RealSenseIngest().read(channel("d455.color"), 0.02))
    assert caught.value.reason.value == "device_node_missing"
    assert "query_devices() enumerates 0 devices" in str(caught.value)
    assert "USB 3 (BLUE)" in caught.value.remedy
    assert log["queried"] == 1
    # And the pipeline was never started, so no vendor RuntimeError can be the
    # thing the operator reads.
    assert log["started"] == 0


def test_a_build_with_no_rs_context_refuses_instead_of_falling_through_to_start(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Card ENV-1b item 5: the enumeration gate was fail-OPEN and is now closed.

    ``_require_enumerated_device`` used to ``return`` when ``read_field(rs,
    'context')`` found nothing, on the reasoning that an uninterrogable build
    should let the open speak for itself. The open does not speak — it crashes.
    A webcam-only host (``/dev/video0`` present, no RealSense) then reached
    ``pipeline.start()``, and preflight filed ``probe_raised — RuntimeError``:
    the unattributable absence, naming no device and offering no remedy, that
    card ENV-1 was written to remove. It is also the opposite of what
    ``stream_selection`` does two methods down, which refuses UNPARSEABLE when a
    build exposes no ``rs.stream``/``rs.config``.

    So the missing symbol is named, and — the half that matters — the pipeline
    is never started, because a librealsense traceback attributed to the camera
    is a lie about which thing is broken.
    """

    log = _install_fake_realsense(monkeypatch, honours_config=True, devices=0)
    # A webcam-shaped node IS there: the import-free census cannot refuse, so
    # this gate is the only thing between the operator and pipeline.start().
    monkeypatch.setattr(
        rs_module.RealSenseIngest,
        "device_report",
        classmethod(
            lambda cls: ingest_base.DeviceReport(
                adapter=cls.adapter_name,
                presence=ingest_base.DevicePresence.ATTACHED,
                detail="staged: a UVC webcam is on /dev/video0",
                remedy="",
                nodes=("/dev/video0",),
            )
        ),
    )
    # A build that spells the symbol differently, or does not ship it at all.
    monkeypatch.delattr(sys.modules["pyrealsense2"], "context")

    with pytest.raises(IngestUnavailableError) as caught:
        list(RealSenseIngest().read(channel("d455.color"), 0.02))
    assert caught.value.reason.value == "unparseable"
    assert "rs.context" in str(caught.value)
    assert "Traceback" not in str(caught.value)
    assert caught.value.remedy, "a refusal with no remedy is one nobody can act on"
    assert "pyrealsense2" in caught.value.remedy
    assert log["queried"] == 0
    assert log["started"] == 0, (
        "the adapter fell through to pipeline.start(); the operator gets "
        "probe_raised — RuntimeError instead of the missing symbol"
    )


def test_a_failed_start_is_not_masked_by_the_stop_in_the_finally(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Seeded on the exact defect this box printed six times.

    ``read_frames`` unconditionally called ``handle.stop()`` in its ``finally``.
    When ``start()`` raised — which is what a device-less librealsense does —
    ``stop()`` raised *its own* ``RuntimeError: stop() cannot be called before
    start()`` from the ``finally``, replacing the real failure. Preflight filed
    that second error as the reason, so every D455 row read
    ``probe_raised — RuntimeError: stop() cannot be called before start()``:
    the wrong call, no device named, no remedy.
    """

    _install_fake_realsense(monkeypatch, honours_config=True, devices=1)
    module = sys.modules["pyrealsense2"]
    pipeline_class = module.pipeline

    class _DeadPipeline(pipeline_class):
        def start(self, *args):
            raise RuntimeError("No device connected")

        def stop(self):
            raise AssertionError("stop() ran after a start() that never succeeded")

    monkeypatch.setattr(module, "pipeline", _DeadPipeline)
    with pytest.raises(RuntimeError) as caught:
        list(RealSenseIngest().read(channel("d455.color"), 0.02))
    assert "No device connected" in str(caught.value)
    assert "stop() cannot be called before start()" not in str(caught.value)


def test_a_build_that_cannot_select_a_stream_is_a_named_refusal_not_a_default_profile(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Fail closed on the vendor build too: no ``rs.config``, no read."""

    _install_fake_realsense(monkeypatch, honours_config=True)
    module = sys.modules["pyrealsense2"]
    monkeypatch.delattr(module, "config")
    with pytest.raises(IngestUnavailableError) as caught:
        RealSenseIngest().stream_selection(channel("d455.color"))
    assert "no rs.config" in str(caught.value)
    assert "must not be used for the D455 rows" in caught.value.remedy

    _install_fake_realsense(monkeypatch, honours_config=True)
    monkeypatch.setattr(sys.modules["pyrealsense2"], "stream", _Bag(depth="depth"))
    with pytest.raises(IngestUnavailableError, match="rs.stream.color"):
        RealSenseIngest().stream_selection(channel("d455.color"))


def test_the_frame_builders_run_for_every_live_channel_they_serve() -> None:
    """``frame_from_*`` is where the fail-closed clock rule is applied per
    transport, and none of the three had ever been called for the L2 or the
    RealSense rows."""

    cloud = l2_module.frame_from_l2(channel("l2.cloud"), _l2_cloud())
    assert cloud.channel_id == "l2.cloud"
    assert cloud.payload_kind is PayloadKind.DERIVED_SUMMARY
    imu = l2_module.frame_from_l2(channel("l2.imu"), _l2_imu())
    assert imu.measurements and type(imu.measurements[0]).__name__ == "ImuSample"
    with pytest.raises(IngestRefusedError, match="not an L2 channel"):
        l2_module.frame_from_l2(channel("go2.lowstate"), _l2_cloud())

    for channel_id in ("d455.color", "d455.depth", "d455.infra1", "d455.infra2"):
        frame = rs_module.frame_from_realsense(channel(channel_id), _rs_video_frame())
        assert frame.channel_id == channel_id
        assert frame.source_timestamp_ns is None
    for channel_id in ("d455.accel", "d455.gyro"):
        frame = rs_module.frame_from_realsense(
            channel(channel_id),
            _FakeMotionFrame(x=0.0, y=0.0, z=9.81, timestamp=1.0, domain="global_time"),
        )
        assert len(frame.measurements) == 1


def test_every_decoder_records_a_missing_field_rather_than_crashing_the_probe() -> None:
    """The branch that exists because every matrix row is transcribed from
    documentation about somebody ELSE's Go2. A field that is not there must cost
    a named entry in ``missing_fields``, not a probe forty minutes into a
    battery."""

    empty = _Bag()

    _samples, low = dds_module.decode_low_state(empty)
    assert {"imu_state", "motor_state", "foot_force", "foot_force_est"} <= set(
        low["missing_fields"]
    )
    assert low["tick_ms"] is None

    _samples, sport = dds_module.decode_sport_mode_state(empty)
    assert {"imu_state", "foot_force", "range_obstacle"} <= set(sport["missing_fields"])
    assert sport["stamp_ns"] is None

    samples, imu = dds_module.decode_imu(empty)
    assert samples == ()
    assert imu["missing_fields"] == ["linear_acceleration", "angular_velocity"]
    assert imu["orientation_xyzw"] is None

    _samples, l2imu = l2_module.decode_l2_imu(empty)
    assert l2imu["missing_fields"] == ["accel", "gyro"]
    assert l2imu["stamp_ns"] is None

    _samples, l2cloud = l2_module.decode_l2_cloud(empty)
    assert l2cloud["missing_fields"] == ["points"]
    assert l2cloud["ring_count"] is None

    _samples, video = rs_module.decode_video_frame("d455.color", empty)
    assert video["missing_fields"] == ["width", "height"]
    assert video["timestamp_domain"] is None
    _samples, motion = rs_module.decode_motion_frame("d455.accel", empty)
    assert motion["missing_fields"] == ["motion_data"]


def test_a_wrong_length_motor_array_is_a_finding_and_still_decodes_twelve() -> None:
    _samples, summary = dds_module.decode_low_state(_low_state(motors=16))
    assert any("not the documented 20" in note for note in summary["findings"])
    assert len(summary["motor_state"]) == 12


def test_the_alternative_timespec_spelling_is_read_and_a_malformed_one_is_null() -> None:
    """``sec``/``nsec`` and ``sec``/``nanosec`` are both in the wild; a stamp
    that is neither is null, never a guess."""

    assert dds_module.timespec_ns(_Bag(sec=2, nsec=500)) == 2_000_000_500
    assert dds_module.timespec_ns(_Bag(sec=2, nanosec=500)) == 2_000_000_500
    assert dds_module.timespec_ns(_Bag(sec="two", nanosec=0)) is None
    assert dds_module.timespec_ns(_Bag(sec=2)) is None
    assert dds_module.timespec_ns(None) is None
    assert dds_module.header_stamp_ns(_Bag()) is None


@pytest.mark.parametrize(
    ("message", "fragment"),
    [
        (
            _Bag(height=1, width=1, point_step=16, data=b"\x00" * 16, fields=[]),
            "no x/y/z fields",
        ),
        (
            _Bag(
                height=1, width=1, point_step=0, data=b"",
                fields=[
                    _Bag(name=axis, offset=index * 4, datatype=7, count=1)
                    for index, axis in enumerate(("x", "y", "z"))
                ],
            ),
            "point_step is 0",
        ),
    ],
)
def test_an_unusable_cloud_layout_is_named_rather_than_sampled_on_a_guess(
    message, fragment: str
) -> None:
    samples, summary = dds_module.decode_point_cloud2(message)
    assert samples[0].ranges_m == ()
    assert any(fragment in note for note in summary["findings"])


def test_a_cloud_whose_data_ends_inside_a_point_stops_sampling_and_says_so() -> None:
    # Two whole 16-byte points by ``len(data) // point_step``, but ``z`` sits at
    # offset 14 — so the SECOND point's z runs two bytes past the end. This is
    # the shape a truncated DDS fragment actually has, and the decoder must stop
    # and say so rather than raise inside a probe.
    truncated = _Bag(
        height=1,
        width=2,
        point_step=16,
        data=b"\x00" * 32,
        fields=[
            _Bag(name="x", offset=0, datatype=7, count=1),
            _Bag(name="y", offset=4, datatype=7, count=1),
            _Bag(name="z", offset=14, datatype=7, count=1),
        ],
    )
    samples, summary = dds_module.decode_point_cloud2(truncated)
    assert samples[0].point_count == 2
    assert len(samples[0].ranges_m) == 1
    assert any("ended inside a point" in note for note in summary["findings"])


def test_the_adapters_refuse_their_own_malformed_construction() -> None:
    with pytest.raises(IngestRefusedError, match="queue_depth"):
        DdsIngest(queue_depth=0)
    with pytest.raises(IngestRefusedError, match="endpoint must be non-empty"):
        L2Ingest(endpoint="   ")


def test_the_ros_interface_translation_refuses_a_shape_it_would_have_to_guess() -> None:
    already_ros = _Bag(channel_id="x", message_type="unitree_go/msg/LowState",
                       transport=Transport.DDS)
    assert ros_message_type(already_ros) == "unitree_go/msg/LowState"
    for bad in ("unitree_go", "a/b/c/d", "a/b/dds_/NoTrailingUnderscore"):
        with pytest.raises(IngestRefusedError, match="will not guess"):
            ros_message_type(_Bag(channel_id="x", message_type=bad, transport=Transport.DDS))


def test_an_array_with_a_non_numeric_element_decodes_to_nothing_not_to_a_guess() -> None:
    """A string in a numeric array is a documentation error about OUR unit, and
    the whole array is discarded rather than partly believed."""

    assert dds_module._floats([1.0, "two", 3.0]) == []
    assert dds_module._ints([1, None, 3]) == []
    assert dds_module._floats("1.0 2.0 3.0") == []  # a string is not an array
    assert dds_module._ints(b"\x01\x02") == []
    assert dds_module._vec3([1.0, 2.0]) is None
    assert dds_module._xyz(_Bag(x=1.0, y=2.0)) is None

    _samples, summary = dds_module.decode_low_state(
        _Bag(foot_force=[1, "x", 3, 4], foot_force_est=[1, 2, 3, 4])
    )
    assert "foot_force" in summary["missing_fields"]
    assert "foot_force_est" not in summary["missing_fields"]


def test_a_non_integral_or_non_finite_timespec_is_null_never_a_partial_clock() -> None:
    """A partially decoded clock is worse than an absent one: the absent one is
    visible in the record."""

    assert dds_module.timespec_ns(_Bag(sec=True, nanosec=1)) is None
    assert dds_module.timespec_ns(_Bag(sec=1, nanosec=True)) is None
    assert dds_module.timespec_ns(_Bag(sec=1, nanosec=[2])) is None
    assert dds_module.timespec_ns(_Bag(sec=float("nan"), nanosec=0)) is None
    assert dds_module.timespec_ns(_Bag(sec=1, nanosec=float("inf"))) is None


def test_an_imu_state_that_carries_neither_vector_yields_no_sample_but_keeps_its_summary() -> None:
    """The distinction that keeps a half-broken IMU visible: the state was
    present, its temperature was read, and there is still nothing to rule on."""

    sample, summary = dds_module._imu_from_state(_Bag(temperature=39, rpy=[0.0, 0.0, 0.0]))
    assert sample is None
    assert summary["present"] is True
    assert summary["temperature_c"] == 39.0
    assert summary["accelerometer_mps2"] is None

    absent_sample, absent_summary = dds_module._imu_from_state(None)
    assert absent_sample is None and absent_summary == {"present": False}


@pytest.mark.parametrize(
    ("overrides", "fragment"),
    [
        ({"point_step": None}, "no point_step/data"),
        ({"data": None}, "no point_step/data"),
        ({"data": object()}, "not byte-addressable"),
        ({"data": b"\x00" * 4}, "no whole points"),
    ],
)
def test_every_unusable_cloud_shape_is_named_and_none_of_them_raises(
    overrides, fragment: str
) -> None:
    fields = [
        _Bag(name=axis, offset=index * 4, datatype=7, count=1)
        for index, axis in enumerate(("x", "y", "z"))
    ]
    message = _Bag(height=1, width=1, point_step=16, data=b"\x00" * 16, fields=fields)
    for key, value in overrides.items():
        setattr(message, key, value)
    samples, summary = dds_module.decode_point_cloud2(message)
    assert samples[0].ranges_m == ()
    assert any(fragment in note for note in summary["findings"])


def test_a_full_size_cloud_is_subsampled_to_the_stated_ceiling() -> None:
    """Preflight does not hold a cloud. A 10 Hz L2 sweep is ~100k points and the
    range statistic is capped, so the probe cost is bounded."""

    import struct as _struct

    count = dds_module.MAX_RANGE_SAMPLES * 3
    blob = b"".join(_struct.pack("<fff", 1.0, 0.0, 0.0) for _ in range(count))
    message = _Bag(
        height=1,
        width=count,
        point_step=12,
        data=blob,
        fields=[
            _Bag(name=axis, offset=index * 4, datatype=7, count=1)
            for index, axis in enumerate(("x", "y", "z"))
        ],
    )
    samples, _summary = dds_module.decode_point_cloud2(message)
    assert samples[0].point_count == count
    assert len(samples[0].ranges_m) == dds_module.MAX_RANGE_SAMPLES


def test_the_l2_decoders_read_both_vector_spellings_and_count_unusable_points() -> None:
    """The SDK hands back plain objects in some builds and sequences in others,
    and a point with a non-numeric coordinate is COUNTED rather than dropped in
    silence — the count is what tells you the sweep was partly garbage."""

    _sample, summary = l2_module.decode_l2_imu(
        _Bag(
            timestamp=3.25,
            acceleration=_Bag(x=0.0, y=0.0, z=9.81),
            angular_velocity_=_Bag(x=0.0, y=0.0, z=0.0),
        )
    )
    assert summary["stamp_ns"] == 3_250_000_000
    assert summary["linear_acceleration_mps2"] == [0.0, 0.0, 9.81]

    samples, cloud = l2_module.decode_l2_cloud(
        _Bag(
            stamp=1.0,
            ringNum=None,
            points=[
                _Bag(x=1.0, y=0.0, z=0.0, intensity=1.0, time=0.0, ring=0),
                _Bag(x="nope", y=0.0, z=0.0, intensity=1.0, time=0.0, ring=1),
            ],
        )
    )
    assert samples[0].point_count == 2
    assert samples[0].nonfinite_points == 1
    assert cloud["ring_count"] is None


def test_the_realsense_motion_decoder_falls_back_to_the_as_motion_frame_spelling() -> None:
    """``pyrealsense2`` exposes the vector under two names depending on build."""

    frame = _Bag(
        as_motion_frame=_Bag(x=0.0, y=0.0, z=9.81),
        frame_number=3,
        timestamp=None,
        timestamp_domain=None,
    )
    samples, summary = rs_module.decode_motion_frame("d455.accel", frame)
    assert summary["vector"] == [0.0, 0.0, 9.81]
    assert summary["device_timestamp_ms"] is None
    assert summary["timestamp_domain"] is None
    assert len(samples) == 1


@pytest.mark.parametrize(
    ("adapter_factory", "module_name", "opener", "attach_device"),
    [
        (lambda: DdsIngest(), "rclpy", lambda a: a.open_session(), False),
        (lambda: L2Ingest(), "unilidar_sdk2", lambda a: a.open_reader(), False),
        (
            lambda: RealSenseIngest(),
            "pyrealsense2",
            lambda a: a.open_pipeline(channel("d455.color")),
            True,
        ),
    ],
)
def test_a_module_that_vanishes_between_the_probe_and_the_open_is_a_named_refusal(
    adapter_factory,
    module_name: str,
    opener,
    attach_device: bool,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The race the ``except ImportError`` arms exist for, actually run.

    ``dependency_report`` answers by ``find_spec`` and never imports; the open
    imports. Between the two, an overlay can be unsourced or a PYTHONPATH entry
    can go away — on the Orin, by somebody opening a second shell. The adapter
    must name the module and a remedy, not raise ``ImportError`` out of a probe.

    Card ENV-1: the realsense arm needs two extra fictions now. Its device gate
    runs before the import and would refuse first on this camera-less box, so
    the arm pretends a camera is attached; and its module really IS installed,
    so deleting it from ``sys.modules`` merely re-imports it — the vanish is
    staged at ``importlib.import_module`` instead. Both fictions are about
    getting the interpreter INTO the race; the assertions below are unchanged.
    """

    from scripts.parcel_capture.ingest.base import DependencyReport, DeviceReport

    adapter = adapter_factory()
    monkeypatch.setattr(
        type(adapter),
        "dependency_report",
        classmethod(
            lambda cls: DependencyReport(
                adapter=cls.adapter_name,
                satisfied=True,
                present=(module_name,),
                missing=(),
                remedy="",
            )
        ),
    )
    if attach_device:
        monkeypatch.setattr(
            type(adapter),
            "device_report",
            classmethod(
                lambda cls: DeviceReport(
                    adapter=cls.adapter_name,
                    presence=DevicePresence.ATTACHED,
                    detail="staged: a camera is on the bus",
                    remedy="",
                    nodes=("/dev/video0",),
                )
            ),
        )

        def vanished(name: str, package: str | None = None):
            raise ImportError(f"No module named {name!r}")

        monkeypatch.setattr(rs_module.importlib, "import_module", vanished)
    monkeypatch.delitem(sys.modules, module_name, raising=False)

    with pytest.raises(IngestUnavailableError) as caught:
        opener(adapter)
    assert "became unimportable between the probe and the open" in str(caught.value)
    assert module_name in str(caught.value)
    assert caught.value.reason.value == "dependency_missing"
    assert caught.value.remedy, "a refusal with no remedy is a refusal nobody can act on"
    assert "Orin only" in caught.value.remedy


def test_the_dds_adapter_refuses_rather_than_serving_nothing_if_the_matrix_loses_its_rows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A matrix with no DDS rows is our own defect, not a quiet empty result.

    ``channels()`` reads PS-A's table live so it can never drift from it. The
    price of that is that a broken table would make the adapter serve zero
    channels and report success; it refuses instead.
    """

    import parcel_robot.capture as capture_module

    monkeypatch.setattr(capture_module, "CHANNELS", ())
    with pytest.raises(Exception) as caught:
        DdsIngest().channels()
    assert "declares no DDS rows" in str(caught.value)


# ---------------------------------------------------------------------------
# G8c — my own finding: an un-attached L2 reader was indistinguishable from a
# dead L2, on the CRITICAL half of the pair.
# ---------------------------------------------------------------------------


def test_an_unattached_l2_reader_is_a_named_refusal_not_an_anonymous_silence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``UnitreeLidarReader()`` constructs a reader; it does not open the socket.

    As shipped, ``open_reader`` returned that fresh reader and ``read_frames``
    polled it until the window elapsed. Every getter returned nothing, so
    ``l2.cloud`` — CRITICAL — came back ABSENT with "the reader finished early
    having yielded nothing": the same words preflight would print for an L2 that
    is unplugged, on session morning.

    This adapter still does not call ``initialize()`` — its signature is
    unverified against our unit — but the refusal now says which of the two
    states it is in, and hands over a command.
    """

    log = _install_fake_unilidar(monkeypatch, attached=False)
    adapter = L2Ingest()

    with pytest.raises(IngestUnavailableError) as caught:
        adapter.open_reader()
    assert "reports it is not initialised" in str(caught.value)
    assert "does not call initialize()" in str(caught.value)
    assert "vendor ROS 2 node" in caught.value.remedy
    assert "192.168.1.2" in caught.value.remedy  # the NIC collision, where it bites
    assert log["checks"] == 1
    assert log["clouds"] == 0, "the adapter polled a reader it had not attached"

    # ...and through the preflight seam it is an ABSENT with a REASON, which is
    # the whole difference. Pre-fix this was NO_MESSAGE with no explanation.
    entry = channel("l2.cloud")
    reader = channel_reader_factory(adapter)(entry)
    probe = probe_channel(entry, reader, window_s=0.02, expected_rate_hz=None)
    assert probe.status is ProbeStatus.ABSENT
    assert probe.absence is not None
    assert probe.absence.value == "not_attempted"
    assert "not initialised" in (probe.absence_detail or "")


def test_a_build_with_no_checkinit_refuses_rather_than_assuming_it_is_attached(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Unknown is absent. A build that cannot say is not a build that says yes."""

    _install_fake_unilidar(monkeypatch, attached=None)
    with pytest.raises(IngestUnavailableError) as caught:
        L2Ingest().open_reader()
    assert "exposes no checkInit()" in str(caught.value)
    assert "rosbag2 primary recording" in caught.value.remedy


def test_a_checkinit_that_raises_is_absent_and_points_at_the_network_first(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The L2 ships on 192.168.1.2 and the Go2 is on 192.168.1.7. One NIC
    carrying both is how a session begins with no LiDAR, so that is the first
    thing the remedy names."""

    _install_fake_unilidar(monkeypatch, attached=OSError("no route to host"))
    with pytest.raises(IngestUnavailableError) as caught:
        L2Ingest().open_reader()
    assert caught.value.reason.value == "probe_raised"
    assert "OSError" in str(caught.value)
    assert "own NIC" in caught.value.remedy or "SECOND NIC" in caught.value.remedy


def test_an_attached_l2_still_reads_and_the_check_is_not_a_new_wall(
    fake_unilidar,
) -> None:
    """The refutation: the gate must not turn a working L2 into a refusal."""

    frames = list(L2Ingest().read(channel("l2.cloud"), 0.02))
    assert frames
    assert fake_unilidar["checks"] == 1
