"""OR-1: the harness that meets the Orin first, tested where the Orin is not.

This desktop has no ROS, no ``rclpy``, no ``pyrealsense2``, no ``fio``, no D455
and no Jetson. That is not an obstacle to testing
:mod:`scripts.parcel_capture.orin_rehearsal` — it is the *point*. The paths that
matter most tomorrow are the refusal paths, and a machine with none of the
dependencies is the only place they can be exercised honestly.

Every phase takes its command runner as an injected callable, so each test here
builds a fake machine out of a dict of command outputs and asserts what the
harness concludes about it. Five of them are seeded failures with a named
consequence:

============================ =========================================
Seed                         Asserted
============================ =========================================
``usbfs_memory_mb`` = 16     P1 FAILs and the remedy names extlinux + a reboot
fio tail below the budget    P2 FAILs and the message states the deficit
robot LAN, no attestation    P3 hard-refuses, citing the CVE class and ADR 0002
``--firmware-attested 1.1.9``P3 REFUSES — proving the compare is not a string one
distro is not Humble         P0 REPORTs; it does not crash and does not fail
``--verify-help`` rejection  P5 refuses BEFORE a byte is recorded
============================ =========================================

The generated-document pin follows ``tests/test_bandwidth_budget_doc.py``: the
committed ``ORIN_RUNBOOK.md`` must be byte-identical to
:func:`render_runbook`, and a seeded change in the phase table must redden it —
without that second test the first could be passing over nothing.
"""

from __future__ import annotations

import json
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
for _entry in (str(REPO_ROOT), str(REPO_ROOT / "src")):
    if _entry not in sys.path:
        sys.path.insert(0, _entry)

from scripts.parcel_capture.orin_rehearsal import (
    BENCH_SOURCES,
    FIRMWARE_PIN,
    FIRMWARE_PIN_TEXT,
    PHASE_IDS,
    PHASES,
    USBFS_PARAM_PATH,
    CommandResult,
    Context,
    OrinDistro,
    PhaseReport,
    RehearsalRefused,
    RosDistro,
    Status,
    Verdict,
    bench_plan,
    bench_source_argv,
    build_verdict,
    classify_distro,
    firmware_meets_pin,
    parse_firmware_version,
    parse_ip_brief,
    refuse_unless_bench_topic,
    render_runbook,
    ros_distro_for_plan,
    run_p0_identity,
    run_p1_environment,
    run_p2_storage,
    run_p3_network,
    run_p5_recorder,
    run_rehearsal,
    runbook_path,
)

# ---------------------------------------------------------------------------
# The fake machine
# ---------------------------------------------------------------------------


class FakeMachine:
    """A dict of ``argv prefix -> (rc, stdout, stderr)``, callable as a runner.

    Longest-prefix wins, so a test can set a broad default and override one
    command. Anything unmatched comes back as *not on PATH*, which is the
    honest default for a machine that has almost nothing: an unlisted command
    is one this fake machine does not have.
    """

    def __init__(self, table: dict[str, tuple[int, str, str]] | None = None) -> None:
        self.table = dict(table or {})
        self.calls: list[tuple[str, ...]] = []

    def __call__(
        self,
        argv: Sequence[str],
        *,
        timeout_s: float = 60.0,
        env_extra: Any = None,
    ) -> CommandResult:
        argv = tuple(str(item) for item in argv)
        self.calls.append(argv)
        line = " ".join(argv)
        best: str | None = None
        for key in self.table:
            if line.startswith(key) and (best is None or len(key) > len(best)):
                best = key
        if best is None:
            return CommandResult(argv, None, "", "", 0.0, error=f"{argv[0]!r} is not on PATH")
        rc, out, err = self.table[best]
        return CommandResult(argv, rc, out, err, 0.0)

    def ran(self, needle: str) -> bool:
        return any(needle in " ".join(call) for call in self.calls)


#: A plausible Orin: JetPack 6.2, Ubuntu 22.04, Humble, python3.10, a big NVMe.
ORIN_LIKE: dict[str, tuple[int, str, str]] = {
    "cat /etc/nv_tegra_release": (
        0,
        "# R36 (release), REVISION: 4.3, GCID: 12345, BOARD: generic, EABI: aarch64\n",
        "",
    ),
    "lsb_release -a": (0, "Distributor ID:\tUbuntu\nDescription:\tUbuntu 22.04.5 LTS\n", ""),
    "uname -r": (0, "5.15.148-tegra\n", ""),
    "uname -m": (0, "aarch64\n", ""),
    "ls /opt/ros": (0, "humble\n", ""),
    "python3 --version": (0, "Python 3.10.12\n", ""),
    "python3.10 --version": (0, "Python 3.10.12\n", ""),
    "lsblk": (0, "nvme0n1  259:0  0  1.8T  0 disk\n", ""),
    "df -h": (0, "Filesystem  Size  Used Avail Use% Mounted on\n/dev/nvme0n1p1 1.8T 200G 1.5T 12% /\n", ""),
}


def orin_machine(overrides: dict[str, tuple[int, str, str]] | None = None) -> FakeMachine:
    table = dict(ORIN_LIKE)
    table.update(overrides or {})
    return FakeMachine(table)


def make_context(tmp_path: Path, machine: FakeMachine, **kwargs: Any) -> Context:
    evidence = tmp_path / "evidence"
    evidence.mkdir(parents=True, exist_ok=True)
    target = kwargs.pop("record_target", None) or evidence
    return Context(evidence_dir=evidence, record_target=target, runner=machine, **kwargs)


# ---------------------------------------------------------------------------
# Parsers, each fail-closed
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("listing", "expected"),
    [
        ("humble\n", OrinDistro.HUMBLE),
        ("jazzy\n", OrinDistro.JAZZY),
        ("foxy\n", OrinDistro.FOXY),
        ("humble  jazzy\n", OrinDistro.UNKNOWN),
        ("iron\n", OrinDistro.NONE),
        ("", OrinDistro.NONE),
    ],
)
def test_the_distro_is_classified_from_what_ls_actually_printed(
    listing: str, expected: OrinDistro
) -> None:
    """Every row here is a SUCCESSFUL listing: exit 0, and whatever it printed.

    The exit code is deliberately 0 even for the empty row — a successful read
    of an empty ``/opt/ros`` is the one and only way to reach NONE, and the
    failed-read rows live in the test below.
    """

    result = classify_distro(CommandResult(("ls", "/opt/ros"), 0, listing, "", 0.0))
    assert result[0] is expected


def test_an_unavailable_ls_is_unknown_and_not_none() -> None:
    """"The command could not run" and "there is no ROS" are different facts.

    Both refuse to produce an argv, but they have different remedies, and a
    harness that conflated them would tell an operator to install ROS on a
    machine whose coreutils are missing.
    """

    unavailable = CommandResult(("ls", "/opt/ros"), None, "", "", 0.0, error="not on PATH")
    assert classify_distro(unavailable)[0] is OrinDistro.UNKNOWN


# -- FX-2 F5c: a listing that FAILED is UNKNOWN, never NONE ------------------


@pytest.mark.parametrize(
    ("returncode", "stderr"),
    [
        (2, "ls: cannot open directory '/opt/ros': Permission denied"),
        (2, "ls: cannot access '/opt/ros': No such file or directory"),
        (1, "ls: reading directory '/opt/ros': Input/output error"),
        (126, ""),
    ],
)
def test_a_failed_ls_is_unknown_and_only_a_successful_empty_read_is_none(
    returncode: int, stderr: str
) -> None:
    """Fail closed on the listing, not just on the executable.

    On the shipped code every one of these returned NONE — "there is no ROS
    distro installed", an owner-decision REPORT — off a directory the harness
    was never able to read. Unreadable is not an answer; only exit 0 with
    nothing in it is.
    """

    failed = CommandResult(("ls", "/opt/ros"), returncode, "", stderr, 0.0)
    assert classify_distro(failed)[0] is OrinDistro.UNKNOWN

    empty_but_read = CommandResult(("ls", "/opt/ros"), 0, "", "", 0.0)
    assert classify_distro(empty_but_read)[0] is OrinDistro.NONE


def test_p0_quotes_the_failed_listing_so_the_operator_can_tell_the_cases_apart(
    tmp_path: Path,
) -> None:
    machine = orin_machine(
        {"ls /opt/ros": (2, "", "ls: cannot access '/opt/ros': No such file or directory")}
    )
    ctx = make_context(tmp_path, machine)
    report = run_p0_identity(ctx)

    assert report.verdict is Verdict.PASS
    assert report.facts["distro"] == "UNKNOWN"
    assert report.facts["opt_ros_listing_ok"] is False
    joined = " ".join(report.reports)
    assert "No such file or directory" in joined
    assert "classified UNKNOWN, never NONE" in joined


@pytest.mark.parametrize("distro", [OrinDistro.FOXY, OrinDistro.NONE, OrinDistro.UNKNOWN])
def test_no_argv_is_rendered_for_a_distro_whose_cli_nobody_has_read(
    distro: OrinDistro,
) -> None:
    with pytest.raises(RehearsalRefused) as refusal:
        ros_distro_for_plan(distro)
    assert "guessing a CLI nobody has read" in str(refusal.value)


def test_humble_and_jazzy_map_onto_the_recorder_dialects() -> None:
    assert ros_distro_for_plan(OrinDistro.HUMBLE) is RosDistro.HUMBLE
    assert ros_distro_for_plan(OrinDistro.JAZZY) is RosDistro.JAZZY


def test_ip_brief_is_parsed_into_interfaces_and_addresses() -> None:
    text = (
        "lo               UNKNOWN        127.0.0.1/8 ::1/128\n"
        "eth0             UP             192.168.123.222/24\n"
        "eth1             DOWN\n"
    )
    parsed = parse_ip_brief(text)
    assert parsed["eth0"] == ("192.168.123.222/24",)
    assert parsed["eth1"] == ()
    assert parsed["lo"] == ("127.0.0.1/8",)


# ---------------------------------------------------------------------------
# SEEDED FAILURE 1 — the version compare is not a string compare
# ---------------------------------------------------------------------------


def test_the_firmware_compare_is_numeric_and_1_1_9_is_below_the_pin() -> None:
    """The one comparison a string would get exactly backwards.

    ``"1.1.9" >= "1.1.13"`` is **True** in Python: string order puts ``9``
    after ``1``. 1.1.9 is precisely a version the pin exists to exclude, so a
    string compare would clear the firmware the control was written for.
    """

    naive_low, naive_high = "1.1.9", "1.1.13"
    assert naive_low >= naive_high, "the string compare this test exists to rule out"
    assert firmware_meets_pin("1.1.9") is False
    assert firmware_meets_pin("V1.1.9") is False
    assert firmware_meets_pin("1.1.13") is True
    assert firmware_meets_pin("V1.1.13") is True
    assert firmware_meets_pin("1.2.0") is True
    assert firmware_meets_pin("2.0.0") is True
    assert parse_firmware_version("V1.1.13") == FIRMWARE_PIN


@pytest.mark.parametrize("text", ["1.1", "V1", "latest", "", "1.1.13-beta", "v1.1.x"])
def test_an_unparseable_attestation_is_a_refusal_not_a_lenient_compare(text: str) -> None:
    with pytest.raises(RehearsalRefused) as refusal:
        parse_firmware_version(text)
    assert "Unknown = below pin" in str(refusal.value)


def test_p3_refuses_an_attestation_below_the_pin_even_off_the_robot_lan(
    tmp_path: Path,
) -> None:
    machine = FakeMachine({"ip -brief addr": (0, "lo UNKNOWN 127.0.0.1/8\neth0 UP 10.0.0.5/24\n", "")})
    ctx = make_context(tmp_path, machine, firmware_attested="1.1.9")
    report = run_p3_network(ctx)

    assert report.verdict is Verdict.FAIL
    assert report.hard_stop is True
    refusal = " ".join(report.refusals)
    assert "BELOW the pin" in refusal
    assert "CVE-2026-27509" in refusal
    assert "adr/0002-firmware-pin.md" in refusal
    assert "DEGRADE-MMP" in refusal
    assert report.facts["firmware_attested_parsed"] == [1, 1, 9]


def test_p3_refuses_a_malformed_attestation_before_it_looks_at_anything_else(
    tmp_path: Path,
) -> None:
    machine = FakeMachine({"ip -brief addr": (0, "lo UNKNOWN 127.0.0.1/8\n", "")})
    ctx = make_context(tmp_path, machine, firmware_attested="latest")
    report = run_p3_network(ctx)

    assert report.verdict is Verdict.FAIL
    assert report.hard_stop is True
    assert "Unknown = below pin" in " ".join(report.refusals)


# ---------------------------------------------------------------------------
# SEEDED FAILURE 2 — on the robot LAN with no attestation
# ---------------------------------------------------------------------------


def test_p3_hard_refuses_when_the_host_is_on_the_robot_lan_unattested(
    tmp_path: Path,
) -> None:
    machine = FakeMachine(
        {
            "ip -brief addr": (
                0,
                "lo UNKNOWN 127.0.0.1/8\neth0 UP 192.168.123.222/24\neth1 UP 192.168.1.1/24\n",
                "",
            ),
            "ip route": (0, "default via 10.0.0.1 dev wlan0\n", ""),
        }
    )
    ctx = make_context(tmp_path, machine)
    report = run_p3_network(ctx)

    assert report.verdict is Verdict.FAIL
    assert report.hard_stop is True
    refusal = " ".join(report.refusals)
    assert "192.168.123." in refusal
    assert "CVE-2026-27509 / 27510 class findings" in refusal
    assert "unauthenticated by design" in refusal
    assert "Unknown = below pin" in refusal
    assert report.facts["robot_lan_joined"] is True


def test_a_hard_refusal_stops_the_run_even_under_keep_going(tmp_path: Path) -> None:
    """``--keep-going`` is an operator convenience. The pin is not negotiable.

    Every other failure may be pushed past deliberately; this one may not, and
    the assertion is on the phases that follow it rather than on a flag.
    """

    machine = orin_machine()
    machine.table["ip -brief addr"] = (0, "eth0 UP 192.168.123.222/24\n", "")
    machine.table["cat " + USBFS_PARAM_PATH] = (0, "1000\n", "")
    ctx = make_context(tmp_path, machine, keep_going=True)
    verdict = run_rehearsal(ctx)

    assert verdict["phases"]["p3_network"] == "FAIL"
    assert verdict["phases"]["p4_sensors"] == "SKIPPED"
    assert verdict["phases"]["p5_recorder"] == "SKIPPED"
    assert any("192.168.123." in line for line in verdict["refusals"])


def test_p3_passes_and_says_so_when_the_host_is_not_on_the_robot_lan(
    tmp_path: Path,
) -> None:
    machine = FakeMachine(
        {"ip -brief addr": (0, "lo UNKNOWN 127.0.0.1/8\neth0 UP 10.1.2.3/24\neth1 DOWN\n", "")}
    )
    report = run_p3_network(make_context(tmp_path, machine))

    assert report.verdict is Verdict.PASS
    assert report.facts["robot_lan_joined"] is False
    assert any("never joins it" in line for line in report.reports)


def test_p3_fails_closed_when_it_cannot_enumerate_interfaces_at_all(
    tmp_path: Path,
) -> None:
    """No ``ip`` means no answer, and no answer is not "not on the robot LAN"."""

    report = run_p3_network(make_context(tmp_path, FakeMachine()))
    assert report.verdict is Verdict.FAIL
    assert "will not assert" in " ".join(report.remedies)


def test_p3_flags_the_l2_factory_subnet_collision(tmp_path: Path) -> None:
    machine = FakeMachine(
        {"ip -brief addr": (0, "lo UNKNOWN 127.0.0.1/8\nwlan0 UP 192.168.1.171/24\n", "")}
    )
    report = run_p3_network(make_context(tmp_path, machine))

    assert report.verdict is Verdict.PASS
    assert any("192.168.1.2" in line for line in report.findings)


# ---------------------------------------------------------------------------
# SEEDED FAILURE 3 — usbfs is the 16 MB default
# ---------------------------------------------------------------------------


def test_p1_fails_on_the_16mb_usb_buffer_and_the_remedy_names_extlinux_and_a_reboot(
    tmp_path: Path,
) -> None:
    machine = orin_machine()
    machine.table["cat " + USBFS_PARAM_PATH] = (0, "16\n", "")
    report = run_p1_environment(make_context(tmp_path, machine, distro=OrinDistro.HUMBLE))

    assert report.verdict is Verdict.FAIL
    assert report.facts["usbfs_memory_mb"] == 16
    usbfs = next(item for item in report.observations if item.name == "usbfs_memory_mb")
    assert usbfs.status is Status.ABSENT
    assert "/boot/extlinux/extlinux.conf" in usbfs.remedy
    assert "REBOOT" in usbfs.remedy
    assert "usbcore.usbfs_memory_mb=1000" in usbfs.remedy
    assert "no second dock" in usbfs.remedy
    assert "kernel default" in usbfs.detail


def test_p1_accepts_the_buffer_once_it_is_raised(tmp_path: Path) -> None:
    machine = orin_machine()
    machine.table["cat " + USBFS_PARAM_PATH] = (0, "1000\n", "")
    report = run_p1_environment(make_context(tmp_path, machine, distro=OrinDistro.HUMBLE))

    usbfs = next(item for item in report.observations if item.name == "usbfs_memory_mb")
    assert usbfs.status is Status.PRESENT


def test_a_missing_module_is_reported_by_its_error_line_not_by_the_word_traceback(
    tmp_path: Path,
) -> None:
    """FX-2 F5b. Python prints the cause LAST; the detail took the first line.

    The operator's whole view of the probe is that one line, and on this
    desktop every absent module read ``Traceback (most recent call last):``.
    """

    machine = orin_machine()
    traceback_text = (
        "Traceback (most recent call last):\n"
        '  File "<string>", line 1, in <module>\n'
        "    import pyrealsense2 as probed; print('pyrealsense2 at', probed.__file__)\n"
        "ModuleNotFoundError: No module named 'pyrealsense2'\n"
    )
    machine.table["python3.10 -c import pyrealsense2"] = (1, "", traceback_text)
    report = run_p1_environment(make_context(tmp_path, machine, distro=OrinDistro.HUMBLE))

    probe = next(item for item in report.observations if item.name == "pyrealsense2")
    assert probe.status is Status.ABSENT
    assert probe.detail == "ModuleNotFoundError: No module named 'pyrealsense2'"
    assert "Traceback" not in probe.detail


def test_an_unreadable_usb_buffer_is_unknown_which_is_absent(tmp_path: Path) -> None:
    machine = orin_machine()
    machine.table["cat " + USBFS_PARAM_PATH] = (1, "", "No such file or directory\n")
    report = run_p1_environment(make_context(tmp_path, machine, distro=OrinDistro.HUMBLE))

    usbfs = next(item for item in report.observations if item.name == "usbfs_memory_mb")
    assert usbfs.status is Status.UNKNOWN
    assert report.verdict is Verdict.FAIL


def test_an_import_under_the_wrong_interpreter_does_not_verify_the_310_claim(
    tmp_path: Path,
) -> None:
    """A clean import under 3.14 is evidence about 3.14 and nothing else.

    This is the trap the claim has been sitting in: the capture package's 3.10
    support has only ever been checked statically, and a green import on a
    developer box would look exactly like the verification nobody has done.
    """

    machine = orin_machine()
    machine.table["python3.10 --version"] = (127, "", "not found\n")
    machine.table["python3 --version"] = (0, "Python 3.14.4\n", "")
    machine.table["python3 -c import sys, parcel_robot.capture"] = (
        0,
        "IMPORT OK 3.14.4 28 channels\n",
        "",
    )
    report = run_p1_environment(make_context(tmp_path, machine, distro=OrinDistro.HUMBLE))

    claim = next(
        item for item in report.observations if item.name.startswith("python3.10 import")
    )
    assert claim.status is Status.UNKNOWN
    assert report.facts["python310_is_310"] is False
    assert "static only" in claim.remedy


def test_every_absent_package_carries_the_install_command_as_its_remedy(
    tmp_path: Path,
) -> None:
    machine = orin_machine()
    machine.table["cat " + USBFS_PARAM_PATH] = (0, "1000\n", "")
    report = run_p1_environment(make_context(tmp_path, machine, distro=OrinDistro.HUMBLE))

    assert report.verdict is Verdict.FAIL
    remedies = " ".join(report.remedies)
    assert "pip install --user pyrealsense2" in remedies
    assert "ros-humble-rosbag2-storage-mcap" in remedies
    assert "ros-humble-realsense2-camera" in remedies
    assert "colcon build --packages-select unitree_go unitree_api" in remedies
    assert "unilidar_sdk2" in remedies
    for item in report.observations:
        if item.status is not Status.PRESENT and item.required:
            assert item.remedy, f"{item.name} is ABSENT with no remedy"


def test_the_package_name_cannot_be_guessed_when_the_distro_is_unknown(
    tmp_path: Path,
) -> None:
    """``ros-<distro>-...`` has no value to fill in, so the answer is UNKNOWN."""

    machine = orin_machine({"ls /opt/ros": (1, "", "No such file or directory\n")})
    machine.table["cat " + USBFS_PARAM_PATH] = (0, "1000\n", "")
    report = run_p1_environment(make_context(tmp_path, machine, distro=OrinDistro.NONE))

    mcap = next(item for item in report.observations if item.name.startswith("rosbag2"))
    assert mcap.status is Status.UNKNOWN
    assert "cannot name the package" in mcap.detail


# ---------------------------------------------------------------------------
# SEEDED FAILURE 4 — the sustained-write tail is below the budget
# ---------------------------------------------------------------------------


def _seed_fio_log(target: Path, values_kib: list[float]) -> None:
    """Write an fio bandwidth log in fio's own CSV shape."""

    lines = ["#time, bw, direction, blocksize, offset"]
    lines += [f"{index * 1000}, {value}, 1, 1048576, 0" for index, value in enumerate(values_kib)]
    (target / "parcel_rehearsal_fio_bw.1.log").write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_p2_fails_and_names_the_deficit_when_the_tail_is_below_the_budget(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A tail of 40 MiB/s against a 91.87 MiB/s plan is a 51.87 MiB/s deficit.

    The number matters: "storage is too slow" sends an operator to a forum, and
    "you are 52 MiB/s short of the plan of record" sends them to the drop
    ladder with a target.
    """

    import scripts.parcel_capture.orin_rehearsal as harness

    target = tmp_path / "record"
    target.mkdir()
    monkeypatch.setattr(harness.shutil, "which", lambda name: "/usr/bin/fio" if name == "fio" else None)

    machine = FakeMachine({"fio": (0, "", "")})
    original = machine.__call__

    def runner(argv: Sequence[str], **kwargs: Any) -> CommandResult:
        result = original(argv, **kwargs)
        if argv and argv[0] == "fio":
            _seed_fio_log(target, [900_000.0] * 30 + [40.0 * 1024] * 60)
        return result

    ctx = make_context(tmp_path, machine, record_target=target)
    ctx.runner = runner
    report = run_p2_storage(ctx)

    assert report.verdict is Verdict.FAIL
    assert "deficit" in report.summary
    assert "91.87 MiB/s" in report.summary
    assert report.facts["write_measurement"]["tail_mib_per_second"] == pytest.approx(40.0, abs=0.6)
    assert report.facts["write_measurement"]["knee_visible"] is True
    assert report.facts["write_measurement"]["weaker"] is False
    assert "drop ladder" in " ".join(report.remedies)


def test_p2_passes_when_the_tail_clears_the_budget(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import scripts.parcel_capture.orin_rehearsal as harness

    target = tmp_path / "record"
    target.mkdir()
    monkeypatch.setattr(harness.shutil, "which", lambda name: "/usr/bin/fio" if name == "fio" else None)
    monkeypatch.setattr(
        harness.shutil, "disk_usage", lambda path: type("U", (), {"free": 900 * harness.GIB, "total": 1800 * harness.GIB})()
    )

    machine = FakeMachine({"fio": (0, "", "")})
    original = machine.__call__

    def runner(argv: Sequence[str], **kwargs: Any) -> CommandResult:
        result = original(argv, **kwargs)
        if argv and argv[0] == "fio":
            _seed_fio_log(target, [300.0 * 1024] * 90)
        return result

    ctx = make_context(tmp_path, machine, record_target=target)
    ctx.runner = runner
    report = run_p2_storage(ctx)

    assert report.verdict is Verdict.PASS, report.summary
    assert report.facts["write_measurement"]["tool"] == "fio"


def test_p2_labels_the_dd_fallback_as_the_weaker_measurement(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``dd`` is allowed to stand in for ``fio``. It is not allowed to pass for it."""

    import scripts.parcel_capture.orin_rehearsal as harness

    target = tmp_path / "record"
    target.mkdir()
    monkeypatch.setattr(harness.shutil, "which", lambda name: None)
    monkeypatch.setattr(
        harness.shutil, "disk_usage", lambda path: type("U", (), {"free": 900 * harness.GIB, "total": 1800 * harness.GIB})()
    )
    machine = FakeMachine(
        {"dd": (0, "", "2147483648 bytes (2.1 GB, 2.0 GiB) copied, 8.0 s, 268 MB/s\n")}
    )
    report = run_p2_storage(make_context(tmp_path, machine, record_target=target))

    measurement = report.facts["write_measurement"]
    assert measurement["tool"] == "dd"
    assert measurement["weaker"] is True
    assert measurement["peak_mib_per_second"] is None
    assert "cannot show the knee" in measurement["weakness"]
    assert report.verdict is Verdict.PASS
    assert any("WEAKER" in line for line in report.degradations)


def test_p2_refuses_an_unmeasured_destination_rather_than_assuming_it_is_fine(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import scripts.parcel_capture.orin_rehearsal as harness

    target = tmp_path / "record"
    target.mkdir()
    monkeypatch.setattr(harness.shutil, "which", lambda name: None)
    monkeypatch.setattr(
        harness.shutil, "disk_usage", lambda path: type("U", (), {"free": 900 * harness.GIB, "total": 1800 * harness.GIB})()
    )
    report = run_p2_storage(make_context(tmp_path, FakeMachine(), record_target=target))

    assert report.verdict is Verdict.FAIL
    assert "unmeasured is not a pass" in report.summary


def test_p2_requirement_comes_from_the_generated_budget_not_a_transcription(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The figure in the phase must equal what ``budget.py`` computes today.

    The stale-84.60 finding is exactly this failure mode one layer up: an
    operator-facing number transcribed once and then left behind by the model.
    """

    import scripts.parcel_capture.orin_rehearsal as harness
    from scripts.parcel_capture.budget import RECOMMENDED_PROFILE, build_budget

    target = tmp_path / "record"
    target.mkdir()
    monkeypatch.setattr(harness.shutil, "which", lambda name: None)
    machine = FakeMachine({"dd": (0, "", "2147483648 bytes copied, 8.0 s, 268 MB/s\n")})
    report = run_p2_storage(make_context(tmp_path, machine, record_target=target))

    budget = build_budget(RECOMMENDED_PROFILE)
    assert report.facts["budget"]["required_mib_per_second"] == round(budget.mib_per_second, 3)
    assert report.facts["budget"]["required_free_gib_for_take"] == budget.required_free_gib(
        20.0 * 60.0
    )
    assert "budget.py::build_budget" in report.facts["budget"]["source"]


# ---------------------------------------------------------------------------
# SEEDED FAILURE 5 — a non-Humble distro is a REPORT, not a crash
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("listing", "expected"),
    [
        ("jazzy\n", OrinDistro.JAZZY),
        ("foxy\n", OrinDistro.FOXY),
        ("", OrinDistro.NONE),
    ],
)
def test_p0_reports_a_non_humble_distro_and_does_not_fail_on_it(
    tmp_path: Path, listing: str, expected: OrinDistro
) -> None:
    # Exit 0 on every row, including the empty one: NONE is a SUCCESSFUL read of
    # an empty /opt/ros. A failed read is UNKNOWN and has its own tests.
    machine = orin_machine({"ls /opt/ros": (0, listing, "")})
    ctx = make_context(tmp_path, machine)
    report = run_p0_identity(ctx)

    assert report.verdict is Verdict.PASS
    assert report.facts["distro"] == expected.value
    assert ctx.distro is expected
    joined = " ".join(report.reports)
    assert "REPORT" in joined
    assert "not a harness failure" in joined
    assert report.facts["distro_consequence"]


def test_p0_states_the_foxy_consequence_in_full(tmp_path: Path) -> None:
    """Foxy moves four things at once, and the operator must read all four."""

    machine = orin_machine({"ls /opt/ros": (0, "foxy\n", "")})
    report = run_p0_identity(make_context(tmp_path, machine))

    consequence = report.facts["distro_consequence"]
    assert "sqlite3" in consequence
    assert "3.8" in consequence
    assert "pyrealsense2" in consequence
    assert "NetworkInterfaceAddress" in consequence


def test_p0_renders_the_run_header_the_day_needs(tmp_path: Path) -> None:
    report = run_p0_identity(make_context(tmp_path, orin_machine()))

    header = report.facts["run_header_markdown"]
    assert "JetPack 6.x" in header
    assert "Ubuntu 22.04.5 LTS" in header
    assert "5.15.148-tegra" in header
    assert "HUMBLE" in header
    assert report.facts["is_jetson"] is True
    assert report.facts["l4t_release"] == "R36 REVISION 4.3"


def test_p0_says_out_loud_when_the_host_is_not_a_jetson(tmp_path: Path) -> None:
    """The desktop case. A pass here must never read as evidence about the Orin."""

    machine = FakeMachine(
        {
            "lsb_release -a": (0, "Description:\tUbuntu 26.04 LTS\n", ""),
            "uname -r": (0, "7.0.0-28-generic\n", ""),
            "ls /opt/ros": (2, "", "No such file or directory\n"),
            "python3 --version": (0, "Python 3.14.4\n", ""),
        }
    )
    ctx = make_context(tmp_path, machine)
    report = run_p0_identity(ctx)

    assert report.verdict is Verdict.PASS
    assert report.facts["is_jetson"] is False
    assert any("NOT a Jetson" in line for line in report.reports)

    ctx.reports["p0_identity"] = report
    verdict = build_verdict(ctx)
    assert verdict["all_green"] is False
    assert any("not a Jetson" in line for line in verdict["blockers"])
    assert verdict["evidence_for"] is None


def test_p0_fails_only_when_nothing_at_all_could_be_executed(tmp_path: Path) -> None:
    report = run_p0_identity(make_context(tmp_path, FakeMachine()))
    assert report.verdict is Verdict.FAIL
    assert "not one identity command" in report.summary


# ---------------------------------------------------------------------------
# SEEDED FAILURE 6 — verify-help rejection stops P5 before a byte is written
# ---------------------------------------------------------------------------

#: A Humble-shaped ``--help``: no ``--topics``, no keyboard flag, no node name.
HUMBLE_HELP = (
    "usage: ros2 bag record [-h] [-o OUTPUT] [-s STORAGE] [-a] [-e REGEX]\n"
    "  --output OUTPUT\n  --storage STORAGE\n  --max-cache-size MAX_CACHE_SIZE\n"
    "  --max-bag-size MAX_BAG_SIZE\n  --max-bag-duration MAX_BAG_DURATION\n"
    "  --storage-config-file STORAGE_CONFIG_FILE\n"
    "  --qos-profile-overrides-path QOS_PROFILE_OVERRIDES_PATH\n"
)

#: Every flag the Jazzy plan renders, so a Jazzy argv clears against it. Kept
#: to the flags this module's argv actually uses; the full captured help text
#: lives in tests/test_rosbag2_sidecar.py, which owns the recorder surface.
JAZZY_HELP = (
    "usage: ros2 bag record [-h] [-o OUTPUT] [[Topic ...] ...]\n"
    "  -o OUTPUT, --output OUTPUT\n  -s {sqlite3,mcap}, --storage {sqlite3,mcap}\n"
    "  --topics Topic [Topic ...]\n  --max-cache-size MAX_CACHE_SIZE\n"
    "  --node-name NODE_NAME\n  --disable-keyboard-controls\n"
    "  -b MAX_BAG_SIZE, --max-bag-size MAX_BAG_SIZE\n"
    "  -d MAX_BAG_DURATION, --max-bag-duration MAX_BAG_DURATION\n"
    "  --storage-config-file STORAGE_CONFIG_FILE\n"
)


def test_p5_refuses_before_recording_when_the_argv_carries_an_unsupported_flag(
    tmp_path: Path,
) -> None:
    """A Jazzy argv against a Humble recorder: argparse exit 2, zero bytes.

    The refusal must land before ``ros2 bag record`` is ever started, so the
    assertion is on the *calls the harness made*, not merely on the verdict.
    """

    machine = FakeMachine(
        {
            "ros2 bag record --help": (0, HUMBLE_HELP, ""),
            "ros2 topic list -t": (0, "/camera/camera/color/image_raw [sensor_msgs/msg/Image]\n", ""),
        }
    )
    ctx = make_context(tmp_path, machine)
    ctx.distro = OrinDistro.JAZZY  # renders --topics, which Humble's recorder lacks
    report = run_p5_recorder(ctx)

    assert report.verdict is Verdict.FAIL
    assert "REFUSED before recording" in report.summary
    refusal = " ".join(report.refusals)
    assert "--topics" in refusal
    assert "ZERO bytes" in refusal
    assert not any(call[:3] == ("ros2", "bag", "record") and "--help" not in call for call in machine.calls)
    assert not (ctx.record_target / "parcel_rehearsal_bench_bag").exists()


def test_p5_refuses_a_help_text_it_does_not_recognise(tmp_path: Path) -> None:
    """An unreadable help text is not clearance. Unknown never reads as fine."""

    machine = FakeMachine(
        {
            "ros2 bag record --help": (0, "command not found, did you mean...\n", ""),
            "ros2 topic list -t": (0, "", ""),
        }
    )
    ctx = make_context(tmp_path, machine)
    ctx.distro = OrinDistro.HUMBLE
    report = run_p5_recorder(ctx)

    assert report.verdict is Verdict.FAIL
    assert "does not look like" in " ".join(report.refusals)


def test_p5_refuses_when_no_help_could_be_captured_at_all(tmp_path: Path) -> None:
    ctx = make_context(tmp_path, FakeMachine())
    ctx.distro = OrinDistro.HUMBLE
    report = run_p5_recorder(ctx)

    assert report.verdict is Verdict.FAIL
    assert "did not produce help text" in report.summary
    assert "argparse exit 2" in " ".join(report.remedies)


def test_p5_refuses_to_render_an_argv_for_an_unread_distro(tmp_path: Path) -> None:
    ctx = make_context(tmp_path, FakeMachine())
    ctx.distro = OrinDistro.FOXY
    report = run_p5_recorder(ctx)

    assert report.verdict is Verdict.FAIL
    assert "cannot render a recorder argv for distro FOXY" in report.summary
    assert not any("--help" in " ".join(call) for call in ctx.runner.calls)


def test_the_humble_argv_is_cleared_by_a_humble_help_text(tmp_path: Path) -> None:
    """The positive control: the default dialect passes the same gate."""

    from scripts.parcel_capture.rosbag2 import record_command, validate_argv_against_help

    plan = bench_plan(
        tmp_path / "bag",
        [("/parcel_rehearsal/imu", "sensor_msgs/msg/Imu")],
        distro=RosDistro.HUMBLE,
    )
    argv = record_command(plan)
    assert "--topics" not in argv
    assert argv[-1] == "/parcel_rehearsal/imu"
    assert validate_argv_against_help(argv, HUMBLE_HELP)


# ---------------------------------------------------------------------------
# FX-2 F2 — P5 step 8: a support-topic gate that THREW is not a gate that passed
#
# These drive the whole of P5 in-process: a fake machine answers `--help` and
# `ros2 topic list -t`, the recorder is replaced by a writer that lays down a
# real rosbag2-shaped fixture bag, and the bag is then read, sidecar'd and
# reconciled by the real code. Nothing here needs ROS, and nothing here starts
# a process.
# ---------------------------------------------------------------------------


def _p5_machine() -> FakeMachine:
    return FakeMachine(
        {
            "ros2 bag record --help": (0, JAZZY_HELP, ""),
            "ros2 topic list -t": (0, "\n", ""),
            "ls -l": (0, "", ""),
        }
    )


def _fake_recorder(monkeypatch: pytest.MonkeyPatch) -> None:
    """Replace the recorder and the bench sources; write a real fixture bag."""

    import scripts.parcel_capture.orin_rehearsal as harness
    from scripts.parcel_capture import rosbag2 as rb

    def _write(ctx, report, argv, seconds):
        output = Path(argv[argv.index("--output") + 1])
        output.mkdir(parents=True, exist_ok=True)
        payload = b"\x00\x01\x00\x00" + b"\x00" * 8
        messages = [
            ("/parcel_rehearsal/imu", 10**9 + index * 33_000_000, payload)
            for index in range(30)
        ] + [
            ("/parcel_rehearsal/range", 10**9 + index * 100_000_000, payload)
            for index in range(10)
        ]
        rb.write_fixture_bag(
            output / f"{output.name}_0.mcap",
            messages,
            types={
                "/parcel_rehearsal/imu": "sensor_msgs/msg/Imu",
                "/parcel_rehearsal/range": "sensor_msgs/msg/Range",
            },
        )
        (output / "metadata.yaml").write_text(
            "rosbag2_bagfile_information:\n  storage_identifier: mcap\n"
            "  relative_file_paths:\n"
            f"    - {output.name}_0.mcap\n",
            encoding="utf-8",
        )
        return CommandResult(tuple(argv), 0, "", "", 0.0)

    monkeypatch.setattr(harness, "_record_for", _write)
    monkeypatch.setattr(harness, "_start_bench_sources", lambda ctx, report, sources: [])


def test_p5_passes_when_the_support_reconciliation_actually_runs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The positive control for the two tests below: same path, gate intact."""

    _fake_recorder(monkeypatch)
    ctx = make_context(tmp_path, _p5_machine())
    ctx.distro = OrinDistro.JAZZY
    report = run_p5_recorder(ctx)

    assert report.verdict is Verdict.PASS, report.summary
    assert report.facts["support_reconciliation"]["ok"] is False  # no driver on a bench
    assert "refused the unmapped bench bag" in report.summary


def test_p5_fails_when_the_support_reconciliation_raises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """FX-2 F2. The shipped code recorded a finding and then declared PASS.

    On the Orin, with real PHYSICAL topics on the graph, that meant a crashed
    support-topic check read as a green P5 — and OR1_STATUS section 7 claimed
    the opposite ("P5 fails with the message verbatim").
    """

    from scripts.parcel_capture import preflight

    _fake_recorder(monkeypatch)

    def _raise(_text):
        raise TypeError("reconcile_support_topics() takes a Mapping now, not str")

    monkeypatch.setattr(preflight, "reconcile_support_topics", _raise)
    ctx = make_context(tmp_path, _p5_machine())
    ctx.distro = OrinDistro.JAZZY
    report = run_p5_recorder(ctx)

    assert report.verdict is Verdict.FAIL
    assert "support reconciliation could not run" in report.summary
    assert "TypeError: reconcile_support_topics() takes a Mapping now" in report.summary
    assert "certifies nothing about camera_info" in report.summary
    assert report.facts["support_reconciliation"]["error"].startswith("TypeError:")
    assert "Traceback" not in report.summary
    assert any("preflight.py" in item for item in report.remedies)


def test_p5_fails_when_the_support_reconciliation_cannot_even_be_imported(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The lazy import is inside the same try, so ImportError swallowed too."""

    _fake_recorder(monkeypatch)
    monkeypatch.setitem(sys.modules, "scripts.parcel_capture.preflight", None)
    ctx = make_context(tmp_path, _p5_machine())
    ctx.distro = OrinDistro.JAZZY
    report = run_p5_recorder(ctx)

    assert report.verdict is Verdict.FAIL
    assert "support reconciliation could not run" in report.summary
    assert "ImportError" in report.summary or "ModuleNotFoundError" in report.summary


# ---------------------------------------------------------------------------
# P4 — a stream that runs is not a stream that is healthy
# ---------------------------------------------------------------------------


#: The six streams ``_D455_FRAMES_SCRIPT`` enables, spelled the way a
#: ``pyrealsense2`` profile reports them. Every fixture below carries all six,
#: because the whole point of FX-2 F1 is that P4 scores the CONFIGURED set.
ALL_STREAMS = ("Color", "Depth", "Infrared 1", "Infrared 2", "Accel", "Gyro")


def _frames_json(
    fractions: dict[str, float],
    *,
    seconds: int = 60,
    configured: Sequence[str] | None = None,
) -> str:
    """The child script's JSON, in the shape it really emits.

    ``configured`` is what ``profile.get_streams()`` reported; ``streams``
    carries one entry per configured stream INCLUDING the ones that delivered
    nothing, which is the shape
    ``test_the_real_frame_count_script_reports_every_configured_stream``
    proves the real script produces.
    """

    names = list(ALL_STREAMS if configured is None else configured)
    streams = {}
    for name in names:
        fraction = fractions.get(name, 0.0)
        streams[name] = {
            "delivered": round(30 * seconds * fraction),
            "configured_hz": 30.0,
            "expected": float(30 * seconds),
            "fraction": fraction,
        }
    for name, fraction in fractions.items():  # a stream nobody configured
        streams.setdefault(
            name,
            {
                "delivered": round(30 * seconds * fraction),
                "configured_hz": 30.0,
                "expected": float(30 * seconds),
                "fraction": fraction,
            },
        )
    return json.dumps(
        {
            "ok": True,
            "mode": "callback",
            "elapsed_s": float(seconds),
            "configured": names,
            "streams": streams,
        }
    )


def _all_good(**overrides: float) -> dict[str, float]:
    fractions = dict.fromkeys(ALL_STREAMS, 0.999)
    fractions.update(overrides)
    return fractions


def _sensor_machine(frames_payload: str) -> FakeMachine:
    return FakeMachine(
        {
            "python3 -c \nimport json\ntry:\n    import pyrealsense2": (
                0,
                json.dumps(
                    {
                        "ok": True,
                        "devices": [
                            {
                                "name": "Intel RealSense D455",
                                "serial": "123456789",
                                "firmware": "5.16.0.1",
                                "usb": "3.2",
                            }
                        ],
                    }
                )
                + "\n",
                "",
            ),
            "python3 -c \nimport collections, json, sys, time": (0, frames_payload + "\n", ""),
        }
    )


def test_p4_fails_when_a_stream_reproduces_the_reported_rgb_drop(tmp_path: Path) -> None:
    """80% of the frames missing is the failure this phase exists to catch.

    A per-stream count against a per-stream expectation is the only probe that
    sees it: the pipeline runs, frames arrive, and one stream delivers a fifth
    of them.
    """

    from scripts.parcel_capture.orin_rehearsal import run_p4_sensors

    machine = _sensor_machine(_frames_json(_all_good(Color=0.20)))
    report = run_p4_sensors(make_context(tmp_path, machine))

    assert report.verdict is Verdict.FAIL
    assert "20.0%" in report.summary
    remedy = " ".join(report.remedies)
    assert "drop ladder" in remedy
    assert "848x480@30 C+D" in remedy
    colour = next(item for item in report.observations if item.name == "stream Color")
    assert colour.status is Status.ABSENT


def test_p4_records_a_degraded_stream_as_a_quantified_deficit_not_a_failure(
    tmp_path: Path,
) -> None:
    from scripts.parcel_capture.orin_rehearsal import run_p4_sensors

    machine = _sensor_machine(_frames_json(_all_good(Color=0.95)))
    report = run_p4_sensors(make_context(tmp_path, machine))

    assert report.verdict is Verdict.PASS
    colour = next(item for item in report.observations if item.name == "stream Color")
    assert colour.status is Status.DEGRADED
    assert "95.0%" in colour.detail
    assert any("DEGRADED" in line for line in report.degradations)


def test_p4_counts_both_ir_streams_and_passes_only_when_all_four_hold(
    tmp_path: Path,
) -> None:
    from scripts.parcel_capture.orin_rehearsal import run_p4_sensors

    machine = _sensor_machine(_frames_json(_all_good()))
    report = run_p4_sensors(make_context(tmp_path, machine))

    assert report.verdict is Verdict.PASS
    names = {item.name for item in report.observations}
    assert {"stream Infrared 1", "stream Infrared 2"} <= names
    assert report.facts["d455_devices"][0]["serial"] == "123456789"


def test_p4_fails_when_no_camera_enumerates_and_says_what_to_check(
    tmp_path: Path,
) -> None:
    from scripts.parcel_capture.orin_rehearsal import run_p4_sensors

    report = run_p4_sensors(make_context(tmp_path, FakeMachine()))

    assert report.verdict is Verdict.FAIL
    enumeration = next(item for item in report.observations if item.name == "D455 enumeration")
    assert enumeration.status is Status.ABSENT
    assert "pip install --user pyrealsense2" in enumeration.remedy


# ---------------------------------------------------------------------------
# FX-2 F1 — a stream that delivered NOTHING is not an unscored stream
#
# The tally in the child script is keyed by frames that ARRIVED, so a stream
# that delivered zero frames was absent from the score entirely and the phase
# reported "worst stream 100.0%" — over three dead streams, and over a camera
# that delivered nothing at all. Every test below drives the real child
# script's JSON shape, and the first one drives the real child script.
# ---------------------------------------------------------------------------


_STUB_PYREALSENSE2 = '''
"""Stand-in for pyrealsense2: enough of the API for _D455_FRAMES_SCRIPT to run.

PARCEL_STUB_DELIVERS names the streams that actually deliver frames; every
stream in _CONFIGURED is configured whether it delivers or not, which is the
situation a dead IR emitter or a dropped IMU produces on the bench.
"""
import os

_CONFIGURED = [("Color", 30.0), ("Depth", 30.0), ("Infrared 1", 30.0),
               ("Infrared 2", 30.0), ("Accel", 63.0), ("Gyro", 200.0)]


class _E:
    def __init__(self, name):
        self.name = name


class stream:
    color = _E("Color"); depth = _E("Depth"); infrared = _E("Infrared")
    accel = _E("Accel"); gyro = _E("Gyro")


class format:
    rgb8 = "rgb8"; z16 = "z16"; y8 = "y8"


class _Profile:
    def __init__(self, name, fps):
        self._name, self._fps = name, fps

    def stream_name(self):
        return self._name

    def fps(self):
        return self._fps


class _Frame:
    def __init__(self, name, fps):
        self.profile = _Profile(name, fps)

    def is_frameset(self):
        return False


class _FrameSet:
    def __init__(self, frames):
        self._frames = frames

    def is_frameset(self):
        return True

    def as_frameset(self):
        return list(self._frames)


class config:
    def enable_stream(self, *args):
        return None


class _PipelineProfile:
    def get_streams(self):
        return [_Profile(name, fps) for name, fps in _CONFIGURED]


class pipeline:
    def __init__(self):
        self._delivers = [item for item in
                          os.environ.get("PARCEL_STUB_DELIVERS", "").split(",") if item]

    def start(self, cfg, callback=None):
        if callback is not None:
            raise RuntimeError("no callback start in this build")
        return _PipelineProfile()

    def wait_for_frames(self):
        rates = dict(_CONFIGURED)
        return _FrameSet([_Frame(name, rates.get(name, 0.0)) for name in self._delivers])

    def stop(self):
        return None
'''


def _run_real_frames_script(tmp_path: Path, delivers: str) -> dict:
    """Execute the REAL _D455_FRAMES_SCRIPT against the stub, return its JSON."""

    from scripts.parcel_capture.orin_rehearsal import _D455_FRAMES_SCRIPT

    stub_dir = tmp_path / "stub"
    stub_dir.mkdir(parents=True, exist_ok=True)
    (stub_dir / "pyrealsense2.py").write_text(_STUB_PYREALSENSE2, encoding="utf-8")
    proc = subprocess.run(
        [sys.executable, "-B", "-c", _D455_FRAMES_SCRIPT, "848", "480", "30", "1"],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
        env={
            "PATH": "/usr/bin:/bin",
            "PYTHONPATH": str(stub_dir),
            "PARCEL_STUB_DELIVERS": delivers,
            "PYTHONDONTWRITEBYTECODE": "1",
        },
    )
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout.strip().splitlines()[-1])


def test_the_real_frame_count_script_reports_every_configured_stream(
    tmp_path: Path,
) -> None:
    """The child script is what the Orin runs, so the shape is proven by running it.

    Before FX-2 F1 the script emitted one entry per stream that DELIVERED, and
    the three dead streams below were simply absent from its answer.
    """

    payload = _run_real_frames_script(tmp_path, "Color,Depth,Infrared 1")

    assert payload["ok"] is True
    assert sorted(payload["configured"]) == sorted(ALL_STREAMS)
    assert sorted(payload["streams"]) == sorted(ALL_STREAMS)
    for dead in ("Infrared 2", "Accel", "Gyro"):
        assert payload["streams"][dead]["delivered"] == 0
    assert payload["streams"]["Color"]["delivered"] > 0


def test_p4_fails_naming_a_configured_stream_that_delivered_nothing(
    tmp_path: Path,
) -> None:
    """FX-2 F1, through the real child script: dead IR2 + dead IMU, others fine.

    On the shipped code this phase PASSED at "worst stream 100.0%", because a
    stream with no frames never entered the tally.
    """

    from scripts.parcel_capture.orin_rehearsal import run_p4_sensors

    payload = _run_real_frames_script(tmp_path, "Color,Depth,Infrared 1")
    report = run_p4_sensors(make_context(tmp_path, _sensor_machine(json.dumps(payload))))

    assert report.verdict is Verdict.FAIL
    assert "ZERO frames" in report.summary
    for dead in ("Infrared 2", "Accel", "Gyro"):
        assert dead in report.summary
    assert "100.0%" not in report.summary
    assert report.facts["delivered_by_stream"]["Infrared 2"] == 0
    assert report.facts["delivered_by_stream"]["Color"] > 0


def test_p4_fails_naming_a_total_loss_when_no_stream_delivers_at_all(
    tmp_path: Path,
) -> None:
    """The all-zero case has its own message: nothing arrived, from anything."""

    from scripts.parcel_capture.orin_rehearsal import run_p4_sensors

    payload = _run_real_frames_script(tmp_path, "")
    assert all(item["delivered"] == 0 for item in payload["streams"].values())
    report = run_p4_sensors(make_context(tmp_path, _sensor_machine(json.dumps(payload))))

    assert report.verdict is Verdict.FAIL
    assert "TOTAL LOSS" in report.summary
    assert "worst stream 100" not in report.summary
    remedy = " ".join(report.remedies)
    assert "usbfs_memory_mb" in remedy and "USB 3" in remedy


def test_p4_passes_only_when_every_configured_stream_including_the_imu_delivers(
    tmp_path: Path,
) -> None:
    """The positive control: the same real script, with all six delivering."""

    from scripts.parcel_capture.orin_rehearsal import run_p4_sensors

    payload = _run_real_frames_script(tmp_path, ",".join(ALL_STREAMS))
    report = run_p4_sensors(make_context(tmp_path, _sensor_machine(json.dumps(payload))))

    assert report.verdict is Verdict.PASS
    assert sorted(report.facts["configured_streams"]) == sorted(ALL_STREAMS)
    assert all(count > 0 for count in report.facts["delivered_by_stream"].values())


def test_p4_refuses_to_score_a_frame_count_that_names_no_configured_stream(
    tmp_path: Path,
) -> None:
    """No configured set is no expectation, and no expectation is not a pass."""

    from scripts.parcel_capture.orin_rehearsal import run_p4_sensors

    payload = json.dumps(
        {"ok": True, "mode": "polling", "elapsed_s": 60.0, "configured": [], "streams": {}}
    )
    report = run_p4_sensors(make_context(tmp_path, _sensor_machine(payload)))

    assert report.verdict is Verdict.FAIL
    assert "no CONFIGURED stream" in report.summary
    assert report.facts["frame_count_scored"] is False


def test_p4_fails_when_the_profile_never_configured_the_imu(tmp_path: Path) -> None:
    """A profile missing a stream of the plan is a finding about the profile.

    Every stream it DID configure delivered, so no other leg catches this.
    """

    from scripts.parcel_capture.orin_rehearsal import run_p4_sensors

    four = ("Color", "Depth", "Infrared 1", "Infrared 2")
    machine = _sensor_machine(
        _frames_json(dict.fromkeys(four, 0.999), configured=four)
    )
    report = run_p4_sensors(make_context(tmp_path, machine))

    assert report.verdict is Verdict.FAIL
    assert "never configured" in report.summary
    assert "accel (IMU)" in report.summary and "gyro (IMU)" in report.summary


# ---------------------------------------------------------------------------
# The bench source may never become a command surface
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "topic",
    [
        "/rt/api/motion_switcher/request",
        "/parcel_rehearsal/api/request",
        "/utlidar/cmd",
        "/wirelesscontroller",
        "/joy",
    ],
)
def test_the_bench_source_refuses_any_command_or_request_topic(topic: str) -> None:
    with pytest.raises(RehearsalRefused) as refusal:
        refuse_unless_bench_topic(topic)
    assert "command" in str(refusal.value).lower()


@pytest.mark.parametrize(
    "topic",
    ["/camera/camera/color/image_raw", "/utlidar/cloud", "/tonight/color", "/imu"],
)
def test_the_bench_source_refuses_any_topic_outside_its_own_namespace(topic: str) -> None:
    """Even a perfectly innocent sensor topic. The namespace is the whole guard.

    A test tool that can publish onto a real driver's topic name can shadow the
    driver, and a recorder cannot tell the two apart.
    """

    with pytest.raises(RehearsalRefused) as refusal:
        refuse_unless_bench_topic(topic)
    assert "/parcel_rehearsal/" in str(refusal.value)


def test_every_declared_bench_source_is_a_sensor_message_in_the_rehearsal_namespace() -> None:
    for topic, message_type, rate in BENCH_SOURCES:
        assert refuse_unless_bench_topic(topic) == topic
        assert message_type.startswith("sensor_msgs/msg/")
        assert rate > 0
        argv = bench_source_argv(topic, message_type, rate)
        assert argv[:3] == ("ros2", "topic", "pub")
        assert argv[-2] == message_type


# -- FX-2 F5a: the guard must read the MESSAGE TYPE, not only the name --------


@pytest.mark.parametrize(
    "message_type",
    [
        "geometry_msgs/msg/Twist",
        "geometry_msgs/msg/TwistStamped",
        "unitree_api/msg/Request",
        "unitree_go/msg/WirelessController",
        "unitree_go/msg/LowCmd",
        "sensor_msgs/msg/Joy",
    ],
)
def test_the_bench_source_refuses_a_command_message_type_on_a_clean_topic_name(
    message_type: str,
) -> None:
    """A name-only guard is half a guard.

    ``/parcel_rehearsal/steer`` carries no command marker in its NAME, and on
    the shipped code ``bench_source_argv`` happily rendered
    ``ros2 topic pub … geometry_msgs/msg/Twist`` for it — a velocity command
    published by this harness. The type is now checked independently, so this
    and the namespace rule are provable separately.
    """

    with pytest.raises(RehearsalRefused) as refusal:
        bench_source_argv("/parcel_rehearsal/steer", message_type, 10.0)
    assert "command" in str(refusal.value).lower()


def test_the_bench_source_refuses_a_message_type_outside_the_sensor_allow_list() -> None:
    """The deny-list can only name the command surfaces somebody thought of."""

    with pytest.raises(RehearsalRefused) as refusal:
        bench_source_argv("/parcel_rehearsal/thing", "some_pkg/msg/Whatever", 5.0)
    assert "allow-list" in str(refusal.value)
    assert bench_source_argv("/parcel_rehearsal/imu", "sensor_msgs/msg/Imu", 30.0)


def test_p5_refuses_a_bench_plan_whose_type_is_a_command_before_it_starts_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The type guard is wired into P5, not only into the helper.

    Seeded through BENCH_SOURCES itself: a source list smuggling a Twist must
    stop the phase before ``ros2 topic pub`` or ``ros2 bag record`` is started.
    """

    import scripts.parcel_capture.orin_rehearsal as harness

    monkeypatch.setattr(
        harness,
        "BENCH_SOURCES",
        (("/parcel_rehearsal/steer", "geometry_msgs/msg/Twist", 10.0),),
    )
    machine = FakeMachine(
        {
            "ros2 bag record --help": (0, JAZZY_HELP, ""),
            "ros2 topic list -t": (0, "\n", ""),
        }
    )
    ctx = make_context(tmp_path, machine)
    ctx.distro = OrinDistro.JAZZY
    report = run_p5_recorder(ctx)

    assert report.verdict is Verdict.FAIL
    assert "refused before anything was recorded" in report.summary
    assert any("command/request message type" in item for item in report.refusals)
    assert not machine.ran("topic pub")
    assert not (ctx.record_target / "parcel_rehearsal_bench_bag").exists()


def test_a_synthetic_bench_topic_maps_to_no_channel_so_the_sidecar_must_refuse() -> None:
    """Why P5 asserts a refusal rather than a manifest on a synthetic bench.

    ``build_rosbag2_sidecar`` refuses a bag whose topics map to no channel of
    the matrix — "a bag with no known channel is a finding, not a manifest".
    Every rehearsal topic is deliberately outside the matrix, so that refusal
    is the *expected* outcome and P5 fails if it does not happen.
    """

    from scripts.parcel_capture.rosbag2 import CHANNEL_BY_TOPIC

    for topic, _message_type, _rate in BENCH_SOURCES:
        assert topic not in CHANNEL_BY_TOPIC
    assert "/camera/camera/color/image_raw" in CHANNEL_BY_TOPIC


def test_the_bench_plan_never_records_with_dash_a() -> None:
    plan = bench_plan(
        Path("/tmp/x"),
        [("/parcel_rehearsal/imu", "sensor_msgs/msg/Imu")],
        distro=RosDistro.HUMBLE,
    )
    from scripts.parcel_capture.rosbag2 import record_command

    argv = record_command(plan)
    assert "-a" not in argv
    assert "--all-topics" not in argv


# ---------------------------------------------------------------------------
# The driver: ordering, skipping, and the evidence bundle
# ---------------------------------------------------------------------------


def test_a_failed_phase_stops_the_ones_after_it_and_every_phase_still_gets_a_file(
    tmp_path: Path,
) -> None:
    machine = orin_machine()
    machine.table["cat " + USBFS_PARAM_PATH] = (0, "16\n", "")
    ctx = make_context(tmp_path, machine)
    verdict = run_rehearsal(ctx)

    assert verdict["phases"]["p0_identity"] == "PASS"
    assert verdict["phases"]["p1_environment"] == "FAIL"
    for phase in ("p2_storage", "p3_network", "p4_sensors", "p5_recorder"):
        assert verdict["phases"][phase] == "SKIPPED"
    for phase in PHASE_IDS:
        path = ctx.evidence_dir / f"{phase}.json"
        assert path.is_file(), f"{phase} left no evidence file"
        payload = json.loads(path.read_text(encoding="utf-8"))
        assert payload["schema"] == "parcel.orin_rehearsal.phase.v1"
        assert payload["verdict"] in {"PASS", "FAIL", "SKIPPED"}
    assert (ctx.evidence_dir / "verdict.json").is_file()


def test_keep_going_runs_the_later_phases_after_an_ordinary_failure(
    tmp_path: Path,
) -> None:
    machine = orin_machine()
    machine.table["cat " + USBFS_PARAM_PATH] = (0, "16\n", "")
    machine.table["ip -brief addr"] = (0, "lo UNKNOWN 127.0.0.1/8\neth0 UP 10.0.0.4/24\n", "")
    ctx = make_context(tmp_path, machine, keep_going=True)
    verdict = run_rehearsal(ctx)

    assert verdict["phases"]["p1_environment"] == "FAIL"
    assert verdict["phases"]["p3_network"] == "PASS"


def test_until_stops_the_run_and_marks_the_rest_not_requested(tmp_path: Path) -> None:
    ctx = make_context(tmp_path, orin_machine())
    verdict = run_rehearsal(ctx, until="p0_identity")

    assert verdict["phases"]["p0_identity"] == "PASS"
    assert verdict["phases"]["p1_environment"] == "SKIPPED"
    payload = json.loads((ctx.evidence_dir / "p1_environment.json").read_text(encoding="utf-8"))
    assert "not requested" in payload["summary"]


def test_the_verdict_never_issues_the_readiness_decision_itself(tmp_path: Path) -> None:
    """A harness that graded its own run is what the board's split prevents."""

    ctx = make_context(tmp_path, orin_machine())
    verdict = run_rehearsal(ctx, until="p0_identity")

    assert verdict["schema"] == "parcel.orin_rehearsal.verdict.v1"
    assert "AU-F/Fable" in verdict["authority"]
    assert "evidence FOR" in verdict["authority"] or "evidence" in verdict["authority"]
    assert verdict["does_not_prove"], "does_not_prove must never be empty"
    assert any("never run on a real Orin" in line for line in verdict["does_not_prove"])
    assert verdict["evidence_for"] is None


def test_a_skipped_phase_is_a_blocker_because_not_run_is_not_a_pass(
    tmp_path: Path,
) -> None:
    ctx = make_context(tmp_path, orin_machine())
    verdict = run_rehearsal(ctx, until="p0_identity")

    assert any("p5_recorder: NOT RUN" in line for line in verdict["blockers"])
    assert verdict["all_green"] is False


def test_the_bundle_digests_every_phase_file_it_wrote(tmp_path: Path) -> None:
    ctx = make_context(tmp_path, orin_machine())
    verdict = run_rehearsal(ctx, until="p0_identity")

    assert set(verdict["bundle_sha256"]) == {f"{phase}.json" for phase in PHASE_IDS}
    for digest in verdict["bundle_sha256"].values():
        assert len(digest) == 64


# ---------------------------------------------------------------------------
# Never a traceback: the harness runs here, on a box with none of the deps
# ---------------------------------------------------------------------------


def test_the_harness_runs_on_this_dependency_free_desktop_without_a_traceback(
    tmp_path: Path,
) -> None:
    """The whole fail-closed promise, executed rather than asserted about.

    A real subprocess, the real runner, this real machine — which has no ROS,
    no rclpy, no pyrealsense2, no fio, no D455 and is not a Jetson. It must
    exit non-zero, print no traceback, and leave a complete bundle.
    """

    evidence = tmp_path / "evidence"
    proc = subprocess.run(
        [
            sys.executable,
            "-B",
            "-m",
            "scripts.parcel_capture.orin_rehearsal",
            "--evidence-dir",
            str(evidence),
            "--record-target",
            str(tmp_path),
            "--until",
            "p1_environment",
        ],
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
        env={"PATH": "/usr/bin:/bin", "PYTHONDONTWRITEBYTECODE": "1", "HOME": str(tmp_path)},
        timeout=300,
        check=False,
    )

    assert proc.returncode != 0, "a desktop with none of the dependencies must not pass"
    combined = proc.stdout + proc.stderr
    assert "Traceback (most recent call last)" not in combined
    assert "HARNESS ERROR" not in combined
    assert "RESULT: NOT green" in proc.stdout
    verdict = json.loads((evidence / "verdict.json").read_text(encoding="utf-8"))
    assert verdict["phases"]["p0_identity"] == "PASS"
    assert verdict["phases"]["p1_environment"] == "FAIL"
    assert verdict["evidence_for"] is None
    identity = json.loads((evidence / "p0_identity.json").read_text(encoding="utf-8"))
    assert identity["facts"]["is_jetson"] is False
    # This desktop has no /opt/ros AT ALL, so `ls` exits non-zero and the
    # classification is UNKNOWN — fail closed (FX-2 F5c). It used to read NONE,
    # which is the settled statement "there is no ROS distro installed here",
    # off a listing the harness never managed to read.
    assert identity["facts"]["distro"] == "UNKNOWN"
    assert identity["facts"]["opt_ros_listing_ok"] is False
    assert identity["commands"], "P0 must record the raw output of what it ran"
    listing = next(
        item for item in identity["commands"] if item["argv"] == ["ls", "/opt/ros"]
    )
    assert listing["returncode"] != 0
    assert listing["stderr"].strip(), "the raw reason must survive into the bundle"


def test_a_missing_evidence_directory_parent_is_a_refusal_not_a_traceback(
    tmp_path: Path,
) -> None:
    proc = subprocess.run(
        [
            sys.executable,
            "-B",
            "-m",
            "scripts.parcel_capture.orin_rehearsal",
            "--evidence-dir",
            str(tmp_path / "nope" / "evidence"),
            "--firmware-attested",
            "not-a-version",
        ],
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
        env={"PATH": "/usr/bin:/bin", "PYTHONDONTWRITEBYTECODE": "1", "HOME": str(tmp_path)},
        timeout=120,
        check=False,
    )

    assert proc.returncode == 2
    assert "REFUSED" in proc.stdout
    assert "Traceback" not in proc.stdout + proc.stderr


# ---------------------------------------------------------------------------
# The generated runbook, pinned the way BANDWIDTH_BUDGET.md is
# ---------------------------------------------------------------------------


def test_the_committed_runbook_is_byte_identical_to_the_generator() -> None:
    path = runbook_path()
    assert path.is_file(), f"{path} is missing; run --emit-runbook"
    assert path.read_text(encoding="utf-8") == render_runbook(), (
        "ORIN_RUNBOOK.md has drifted from render_runbook(). It is generated: run "
        "`.parcel/bin/python -m scripts.parcel_capture.orin_rehearsal --emit-runbook`"
    )


def test_the_runbook_names_every_phase_the_harness_actually_runs() -> None:
    """The drift this pin exists for: a phase added to one and missed by the other."""

    text = render_runbook()
    for phase_id, purpose in PHASES:
        assert f"`{phase_id}`" in text, f"{phase_id} is not in the runbook"
        assert purpose in text, f"{phase_id}'s purpose is not in the runbook"
        assert f"{phase_id}.json" in text


def test_a_change_to_the_phase_table_reddens_the_runbook_pin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Without this, the byte-identity test could be passing over nothing."""

    import scripts.parcel_capture.orin_rehearsal as harness

    baseline = harness.render_runbook()
    assert runbook_path().read_text(encoding="utf-8") == baseline

    seeded = (*harness.PHASES, ("p6_planted", "A phase nobody wrote into the runbook."))
    monkeypatch.setattr(harness, "PHASES", seeded)
    # The generator refuses outright rather than emitting a row it cannot describe:
    # a phase with no stated proof and no stated failure condition is exactly the
    # silent drift this pin exists to catch.
    with pytest.raises(KeyError):
        harness.render_runbook()


def test_the_runbook_carries_the_stop_rules_and_the_no_vendor_sdk_rule() -> None:
    text = render_runbook()
    assert "rsync -av --exclude '.parcel/'" in text
    assert "No vendor SDK is ever installed into any Parcel venv" in text
    assert "STOP rules" in text
    assert f"V{FIRMWARE_PIN_TEXT}" in text
    assert "two-dock rule is unmet" in text
    assert "python3 -m scripts.parcel_capture.orin_rehearsal" in text
    assert "does NOT prove" in text
    assert "AU-F" in text


def test_the_runbook_says_until_does_not_run_a_phase_whose_predecessor_failed() -> None:
    """FX-2 F5d. `--until p3_network` alone leaves p3_network SKIPPED here.

    OR1_STATUS M10 recorded `p3_network PASS` for a command with no
    `--keep-going` in it; on this desktop P1 fails, so P2 and P3 are SKIPPED and
    the flag row must say so rather than letting the next reader repeat it.
    """

    row = next(
        line for line in render_runbook().splitlines() if line.startswith("| `--until PHASE`")
    )
    assert "does **not** make PHASE run" in row
    assert "`--keep-going`" in row


def test_the_runbook_states_the_writable_home_requirement() -> None:
    """FX-2 F5e. Measured: a read-only $HOME stops the recorder before byte one."""

    text = render_runbook()
    assert "$HOME` must be WRITABLE" in text
    assert "$HOME/.ros/log" in text


def test_the_runbook_p4_row_states_the_zero_delivery_failure(tmp_path: Path) -> None:
    """FX-2 F1's operator-facing half: the doc must state what P4 now fails on."""

    text = render_runbook()
    p4_row = next(line for line in text.splitlines() if line.startswith("| `p4_sensors`"))
    assert "ZERO frames" in p4_row
    assert "total loss" in p4_row
    assert "IMU" in p4_row
    stop_rule = next(line for line in text.splitlines() if line.startswith("4. **A stream"))
    assert "delivers nothing" in stop_rule


def test_the_runbook_p5_row_states_that_a_gate_which_could_not_run_fails() -> None:
    """FX-2 F2's operator-facing half."""

    p5_row = next(
        line for line in render_runbook().splitlines() if line.startswith("| `p5_recorder`")
    )
    assert "reconciliation could not run" in p5_row


def test_the_runbook_states_the_flags_the_harness_actually_accepts() -> None:
    from scripts.parcel_capture.orin_rehearsal import build_parser

    text = render_runbook()
    parser = build_parser()
    usage = parser.format_help()
    options = {token.rstrip(",") for token in usage.split() if token.startswith("--")}
    for flag in ("--full", "--until", "--keep-going", "--firmware-attested", "--take-minutes"):
        assert flag in options
        assert f"`{flag}" in text


# ---------------------------------------------------------------------------
# Contracts the rest of the harness leans on
# ---------------------------------------------------------------------------


def test_a_command_that_is_not_on_path_is_a_result_and_never_an_exception() -> None:
    from scripts.parcel_capture.orin_rehearsal import run_command

    result = run_command(("this-command-does-not-exist-anywhere", "--version"))
    assert result.returncode is None
    assert result.available is False
    assert "not on PATH" in result.error


def test_a_command_that_times_out_is_a_result_and_never_an_exception() -> None:
    from scripts.parcel_capture.orin_rehearsal import run_command

    result = run_command(("/bin/sleep", "5"), timeout_s=0.2)
    assert result.returncode is None
    assert "timed out" in result.error


def test_the_phase_report_serialises_every_command_it_ran() -> None:
    report = PhaseReport("p0_identity", "purpose")
    report.add(CommandResult(("uname", "-r"), 0, "6.0\n", "", 0.01))
    payload = report.to_dict()

    assert payload["commands"][0]["command"] == "uname -r"
    assert payload["commands"][0]["stdout"] == "6.0\n"
    assert payload["verdict"] == "SKIPPED"


def test_the_phase_ids_are_unique_ordered_and_have_a_runner_each() -> None:
    from scripts.parcel_capture.orin_rehearsal import PHASE_FUNCTIONS

    assert len(set(PHASE_IDS)) == len(PHASE_IDS)
    assert set(PHASE_FUNCTIONS) == set(PHASE_IDS)
    assert PHASE_IDS[0] == "p0_identity"
    assert PHASE_IDS[-1] == "p5_recorder"
