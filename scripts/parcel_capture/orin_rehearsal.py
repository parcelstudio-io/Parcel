"""OR-1: the one command the operator runs on the Orin, and the evidence it leaves.

Why this file exists
--------------------
Tomorrow morning the repository is copied to a Jetson Orin NX that **nobody has
ever executed a command on**. Its JetPack level, its Ubuntu release and its ROS
2 distro are assertions, not observations — ``REVISED_BOARD.md`` H-1 exists
because ``cat /etc/nv_tegra_release`` has never been run, and PS-M proved that
guessing the distro wrong is fatal rather than cosmetic: Humble's recorder has
no ``--topics`` and no ``--disable-keyboard-controls``, argparse exits 2 on an
unknown option, and the session records zero bytes.

The first time this stack meets real hardware must therefore happen through one
audited path, not through improvised shell commands typed at a bench at 09:00.
That path is::

    python3 -m scripts.parcel_capture.orin_rehearsal --evidence-dir ~/orin_evidence

It runs the whole no-dog rehearsal in order, fails closed, and writes a
machine-readable evidence bundle: one JSON file per phase carrying the raw
command outputs, a ``PASS``/``FAIL``/``SKIPPED`` verdict and a remedy on
failure, plus a ``verdict.json`` that maps onto the board's readiness language.

The six phases, and what each one is for
----------------------------------------
``p0_identity``
    The five-minute identity dump (board card H-1). Classifies the ROS distro
    into ``HUMBLE``/``JAZZY``/``FOXY``/``NONE``/``UNKNOWN``. **A non-Humble
    answer is not a harness failure** — it is a report with the retarget
    consequence stated, because retargeting is our software problem and not the
    bench's. This phase's output is rendered as the exact run-header block the
    day's run sheet asks for.

``p1_environment``
    ``usbfs_memory_mb`` (16 is the default that kills dual-IR streaming), the
    first real Python 3.10 execution of ``import parcel_robot.capture``, and
    PRESENT/ABSENT for every package the session needs, each with the install
    command from the no-dog checklist as its remedy.

``p2_storage``
    Sustained write on the actual record target, measured as a **tail** rather
    than a peak, against the free-space requirement rendered from ``budget.py``.
    ``fio`` when it is installed, ``dd`` when it is not — and the ``dd`` result
    is labelled the weaker measurement, never quietly substituted.

``p3_network``
    Interface enumeration, the robot-LAN not-joined check, and a hard refusal
    to continue into anything that would join ``192.168.123.0/24`` without a
    firmware attestation at or above the pin. The pin is a security control
    (ADR 0002), not a checkbox.

``p4_sensors``
    D455 enumeration and a per-stream delivered-vs-expected frame count at
    848x480@30 including both IR, plus a standalone L2 bench read. *Messages
    arrive* is not *the channel is healthy*; only a per-stream count against a
    per-stream expectation catches the reported ~80% RGB drop.

``p5_recorder``
    The whole recorder path end to end on the real machine: capture the
    installed ``ros2 bag record --help``, render the argv from
    ``Rosbag2Plan(distro=<what P0 actually observed>)``, clear it against that
    help **before** first use, record a timed bench bag through that exact
    argv, read the bag back with the repository's own reader, build the
    sidecar, and run preflight's support reconciliation against it.

House rules this file is bound by
---------------------------------
* **Nothing here arms anything.** No publisher, no ``ControlManager``, no
  lease, no motion client, no vendor motion API — the recursive no-arm pin
  covers this file. Launching vendor *sensor* drivers and running
  ``ros2 bag record`` (subscribe-only) through :mod:`subprocess` is permitted;
  commanding motion is not, in any form. The synthetic bench source publishes
  sensor-shaped messages on ``/parcel_rehearsal/*`` only, and the harness
  refuses any other topic name for it.
* **Fail closed.** Unknown is absent. Malformed is a refusal, never a default.
  A missing dependency is an actionable refusal, never a traceback.
* **One source of argv truth.** Every operator-facing command in
  ``ORIN_RUNBOOK.md`` is rendered by :func:`render_runbook` from this module's
  own phase table, and a test reddens if the committed document drifts.

What this file cannot claim
---------------------------
It has never run on a real Orin. Executing it on the development desktop proves
the orchestration and the refusal paths; it proves nothing about the hardware.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import platform
import re
import shutil
import signal
import subprocess
import sys
import time
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

# Absolute imports plus this bootstrap, following budget.py's pattern: the same
# file has to work as `python -m scripts.parcel_capture.orin_rehearsal` in this
# venv and as `python3 scripts/parcel_capture/orin_rehearsal.py` from a bare
# checkout on the Orin, where `parcel_robot` is not installed and relative
# imports have no package to resolve against.
_REPO_ROOT = Path(__file__).resolve().parents[2]
for _entry in (str(_REPO_ROOT), str(_REPO_ROOT / "src")):
    if _entry not in sys.path:
        sys.path.insert(0, _entry)

from parcel_robot.evidence_origin import EvidenceOrigin  # after the bootstrap above
from scripts.parcel_capture.budget import (
    GIB,
    MIB,
    RECOMMENDED_PROFILE,
    build_budget,
)
from scripts.parcel_capture.rosbag2 import (
    CHANNEL_BY_TOPIC,
    Confidence,
    RecordedTopic,
    Rosbag2Error,
    Rosbag2Plan,
    Rosbag2RefusedError,
    RosDistro,
    TopicSource,
    WriterProfile,
    discover_bag,
    read_rosbag2_mcap,
    record_command,
    record_help_command,
    storage_config_yaml,
    validate_argv_against_help,
)

#: Wire schema of every JSON file this harness writes.
PHASE_SCHEMA = "parcel.orin_rehearsal.phase.v1"
VERDICT_SCHEMA = "parcel.orin_rehearsal.verdict.v1"

#: Bumped whenever a phase is added, removed or renamed. The runbook carries it
#: so an evidence bundle can be tied back to the harness that produced it.
HARNESS_VERSION = "or1.1"

#: The Go2 firmware pin, as a comparable tuple and as the text ADR 0002 uses.
#:
#: A tuple, deliberately. ``"1.1.9" >= "1.1.13"`` is TRUE under string
#: comparison — 9 sorts after 1 — so a string compare clears the one firmware
#: revision the pin exists to stop. The parser below refuses anything it cannot
#: turn into three integers.
FIRMWARE_PIN: tuple[int, int, int] = (1, 1, 13)
FIRMWARE_PIN_TEXT = "1.1.13"

#: The vulnerability class the pin is a control for, quoted from ADR 0002.
FIRMWARE_CVE_CLASS = "CVE-2026-27509 / 27510 class findings"

#: The robot's own subnet. The harness never joins it and refuses to proceed
#: into any phase that would, absent an attestation at or above the pin.
ROBOT_LAN_PREFIX = "192.168.123."

#: The add-on L2's factory subnet, which collides with the commonest home
#: network. Present on an interface here is a finding, not a failure.
L2_LAN_PREFIX = "192.168.1."

#: The kernel USB buffer, in MiB. 16 is the default that starves the D455 when
#: colour + depth + both IR stream at once, and the persistent fix needs a boot
#: argument and a reboot.
USBFS_PARAM_PATH = "/sys/module/usbcore/parameters/usbfs_memory_mb"
USBFS_DEFAULT_MB = 16
USBFS_TARGET_MB = 1000

#: Camera profile every frame-count expectation is taken against.
BENCH_WIDTH = 848
BENCH_HEIGHT = 480
BENCH_FPS = 30

#: Frame-count smoke duration: the default is a smoke test, ``--full`` is the
#: no-dog checklist's ten minutes.
SMOKE_SECONDS = 60
FULL_SMOKE_SECONDS = 600

#: Bench recording duration for P5, likewise.
BENCH_RECORD_SECONDS = 20
FULL_BENCH_RECORD_SECONDS = 120

#: Sustained-write sample size. The default is small enough to run anywhere;
#: ``--full`` is the 40 GiB the checklist asks for, which is what actually
#: exhausts an SLC cache and exposes the knee.
WRITE_SAMPLE_BYTES = 2 * GIB
FULL_WRITE_SAMPLE_BYTES = 40 * GIB

#: Per-stream delivery thresholds. At or above ``GOOD`` the stream is healthy;
#: between ``POOR`` and ``GOOD`` it is degraded with the deficit quantified;
#: below ``POOR`` the reported RGB-drop failure has reproduced and the profile
#: must come down the drop ladder before the session.
STREAM_GOOD_FRACTION = 0.99
STREAM_POOR_FRACTION = 0.90

#: The streams ``_D455_FRAMES_SCRIPT`` enables, and the spellings a
#: ``pyrealsense2`` build may report them under. P4 scores against THIS set,
#: not against whatever arrived: a configured stream that delivered nothing is
#: missing from the delivered map entirely, and scoring the delivered map alone
#: reported a total loss as "worst stream 100.0%" (FX-2 F1). Matching is on the
#: normalised name (lowercase, letters and digits only) because the IR and IMU
#: spellings vary between builds.
CONFIGURED_STREAMS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("colour", ("color", "colour", "rgb")),
    ("depth", ("depth",)),
    ("infrared 1", ("infrared1", "infra1", "ir1")),
    ("infrared 2", ("infrared2", "infra2", "ir2")),
    ("accel (IMU)", ("accel", "accelerometer")),
    ("gyro (IMU)", ("gyro", "gyroscope")),
)

#: The only namespace the synthetic bench source may use. Everything the
#: harness starts is a sensor-shaped message on a topic under this prefix; the
#: guard below refuses anything else, so no code path can grow into a command.
BENCH_TOPIC_PREFIX = "/parcel_rehearsal/"

#: Substrings that mark a topic as a command or request surface. A bench source
#: is refused outright if its name carries one, independently of the prefix
#: rule, so the two checks fail separately and a test can prove each.
COMMAND_TOPIC_MARKERS = ("/api/", "/request", "/cmd", "/wirelesscontroller", "/joy")

#: Substrings that mark a MESSAGE TYPE as a command or request surface. The
#: name guard above is not enough on its own: ``/parcel_rehearsal/steer`` with
#: ``geometry_msgs/msg/Twist`` carries no marker in its name and is a velocity
#: command in every other respect (FX-2 F5a). Checked on the lowercased type
#: string, so ``TwistStamped`` and ``unitree_api/msg/Request`` are caught too.
COMMAND_TYPE_MARKERS = (
    "twist",
    "/request",
    "request",
    "cmd",
    "command",
    "wirelesscontroller",
    "joy",
    "ackermann",
    "motorcmd",
    "lowcmd",
    "action",
    "goal",
)

#: Message-type prefixes a bench source may use: sensor data, and nothing else.
#: An allow-list rather than a second deny-list, because the deny-list above can
#: only ever name the command surfaces somebody thought of.
BENCH_TYPE_PREFIXES = ("sensor_msgs/msg/",)

#: The synthetic bench sources: sensor-data message types on sensor-shaped
#: topics, published by ``ros2 topic pub`` only when no real driver topic is on
#: the graph. Publishing sensor messages on a sensor topic from a test tool is
#: how the recorder gets exercised at all on a bench with no camera; it is
#: never a command, and the guard above is what keeps that true.
BENCH_SOURCES: tuple[tuple[str, str, float], ...] = (
    ("/parcel_rehearsal/imu", "sensor_msgs/msg/Imu", 30.0),
    ("/parcel_rehearsal/range", "sensor_msgs/msg/Range", 10.0),
)

#: Default per-command timeout. Long enough for ``apt``-free read-only probes,
#: short enough that a hung command does not eat the bench session.
DEFAULT_TIMEOUT_S = 60.0


class RehearsalRefused(RuntimeError):
    """A fail-closed refusal: malformed input, or an unsafe request."""


class Verdict(str, Enum):
    """The three verdicts a phase may carry. There is no fourth."""

    PASS = "PASS"
    FAIL = "FAIL"
    SKIPPED = "SKIPPED"


class Status(str, Enum):
    """What one observation says. ``UNKNOWN`` is treated as ``ABSENT``."""

    PRESENT = "PRESENT"
    ABSENT = "ABSENT"
    UNKNOWN = "UNKNOWN"
    DEGRADED = "DEGRADED"


class OrinDistro(str, Enum):
    """What ``ls /opt/ros`` actually said, classified.

    ``NONE`` and ``UNKNOWN`` are different facts and are kept apart: ``NONE``
    means the directory was read and holds no distro we target, ``UNKNOWN``
    means the question could not be answered (the command was unavailable, or
    the answer was ambiguous — two distros installed is ambiguous). Both refuse
    to produce a recorder argv, for the same fail-closed reason and with
    different remedies.
    """

    HUMBLE = "HUMBLE"
    JAZZY = "JAZZY"
    FOXY = "FOXY"
    NONE = "NONE"
    UNKNOWN = "UNKNOWN"


#: What a classified distro means for the rest of the day. These strings are
#: the "retarget consequence" the board asks P0 to state out loud.
DISTRO_CONSEQUENCE: Mapping[OrinDistro, str] = {
    OrinDistro.HUMBLE: (
        "The plan of record holds. Rosbag2Plan(distro=HUMBLE) renders the argv: "
        "positional topic list, no --topics, no --disable-keyboard-controls, no "
        "--node-name. S-2's addendum finalizes on this answer."
    ),
    OrinDistro.JAZZY: (
        "REPORT, not a failure. S-2 regenerates the addendum with "
        "Rosbag2Plan(distro=JAZZY); the Humble intersection argv also runs here "
        "(positional topics are deprecated on Jazzy, not removed), so nothing is "
        "blocked. Re-render the run-specific command rows before the session."
    ),
    OrinDistro.FOXY: (
        "REPORT, not a failure, and it moves four things at once: "
        "ros-foxy-rosbag2-storage-mcap does not exist, so the recorder becomes "
        "-s sqlite3 plus an offline conversion and the 'readable by every "
        "downstream tool' claim weakens to 'readable after a conversion step'; "
        "default python3 is 3.8, so the static 3.10 pin is aimed at the wrong "
        "interpreter; the pyrealsense2 wheel target moves; and CycloneDDS wants "
        "the older <NetworkInterfaceAddress> schema. Rosbag2Plan has no FOXY "
        "member, so P5 refuses to render an argv rather than guess one."
    ),
    OrinDistro.NONE: (
        "REPORT, not a failure, and it is an owner decision. The rosbag2-primary "
        "recorder has no host: either a ROS distro is installed (a large mutation "
        "of the only dock — the two-dock rule is unmet) or parcel-capture MCAP is "
        "the sole recorder with a WRITTEN acceptance that no downstream SLAM or "
        "calibration tool reads it without a converter nobody has written."
    ),
    OrinDistro.UNKNOWN: (
        "REPORT. The distro could not be determined, so unknown = absent: P5 "
        "refuses to render an argv. Answer it by hand with `ls /opt/ros` and "
        "`ros2 bag record --help`, then re-run this harness."
    ),
}

#: ``ls /opt/ros`` names this harness can classify. Anything else is UNKNOWN,
#: on purpose: Iron and Rolling are real distros we have never targeted, and
#: pretending otherwise is how an argv reaches the bench untested.
_KNOWN_DISTROS: Mapping[str, OrinDistro] = {
    "humble": OrinDistro.HUMBLE,
    "jazzy": OrinDistro.JAZZY,
    "foxy": OrinDistro.FOXY,
}

#: ``(phase_id, one-line purpose)``, in execution order. This tuple is the only
#: place the phase list exists: the CLI, the driver loop and the generated
#: runbook all read it, so a phase cannot be added to one and missed by another.
PHASES: tuple[tuple[str, str], ...] = (
    ("p0_identity", "Read what this machine actually is, and classify its ROS distro."),
    ("p1_environment", "USB buffer, the Python 3.10 import claim, and every package the session needs."),
    ("p2_storage", "Sustained write on the record target, tail not peak, against the generated budget."),
    ("p3_network", "Interfaces, the robot-LAN not-joined check, and the firmware-pin refusal."),
    ("p4_sensors", "D455 per-stream delivered-vs-expected, and the L2 bench read. No dog."),
    ("p5_recorder", "help -> argv -> record -> read back -> sidecar -> preflight, end to end."),
)

PHASE_IDS: tuple[str, ...] = tuple(item[0] for item in PHASES)


def phase_ids() -> tuple[str, ...]:
    """The phase identifiers, in execution order."""

    return PHASE_IDS


# ---------------------------------------------------------------------------
# Running commands, and never raising while doing it
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class CommandResult:
    """One executed command and everything it said.

    ``returncode is None`` means the command never ran — the executable was not
    on PATH, or it timed out. That is a different fact from "ran and failed",
    and the evidence bundle keeps them apart because their remedies differ.
    """

    argv: tuple[str, ...]
    returncode: int | None
    stdout: str
    stderr: str
    elapsed_s: float
    error: str = ""

    @property
    def ok(self) -> bool:
        return self.returncode == 0

    @property
    def available(self) -> bool:
        """Did the executable exist and run to completion at all?"""

        return self.returncode is not None

    @property
    def text(self) -> str:
        """stdout with stderr appended when stdout is empty. For classifying."""

        return self.stdout if self.stdout.strip() else self.stderr

    def to_dict(self) -> dict[str, Any]:
        return {
            "command": " ".join(self.argv),
            "argv": list(self.argv),
            "returncode": self.returncode,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "elapsed_s": round(self.elapsed_s, 3),
            "error": self.error,
        }


#: A command runner: argv in, :class:`CommandResult` out, and it never raises.
#: Injected so every phase can be driven by a fake in the tests, which is the
#: only way the refusal paths get exercised on a desktop that has none of the
#: hardware.
Runner = Callable[..., CommandResult]


def run_command(
    argv: Sequence[str],
    *,
    timeout_s: float = DEFAULT_TIMEOUT_S,
    env_extra: Mapping[str, str] | None = None,
    cwd: Path | str | None = None,
) -> CommandResult:
    """Run one command, capture everything, and never raise.

    A missing executable, a timeout and a non-zero exit are all *results* here.
    An operator at a bench must never be handed a traceback by this harness.
    """

    argv = tuple(str(item) for item in argv)
    env = dict(os.environ)
    if env_extra:
        env.update(env_extra)
    started = time.monotonic()
    try:
        proc = subprocess.run(
            argv,
            capture_output=True,
            text=True,
            timeout=timeout_s,
            check=False,
            env=env,
            cwd=None if cwd is None else str(cwd),
        )
    except FileNotFoundError:
        return CommandResult(
            argv,
            None,
            "",
            "",
            time.monotonic() - started,
            error=f"{argv[0]!r} is not on PATH",
        )
    except PermissionError as problem:
        return CommandResult(
            argv, None, "", "", time.monotonic() - started, error=f"not executable: {problem}"
        )
    except subprocess.TimeoutExpired as problem:
        return CommandResult(
            argv,
            None,
            _decode(problem.stdout),
            _decode(problem.stderr),
            time.monotonic() - started,
            error=f"timed out after {timeout_s}s",
        )
    except OSError as problem:  # pragma: no cover - defensive, platform specific
        return CommandResult(
            argv, None, "", "", time.monotonic() - started, error=f"could not run: {problem}"
        )
    return CommandResult(
        argv, proc.returncode, proc.stdout, proc.stderr, time.monotonic() - started
    )


def _decode(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", "replace")
    return str(value)


# ---------------------------------------------------------------------------
# Observations and phase reports
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Observation:
    """One PRESENT/ABSENT fact, with the command that would fix it."""

    name: str
    status: Status
    detail: str
    remedy: str = ""
    required: bool = True
    consequence: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "status": self.status.value,
            "detail": self.detail,
            "remedy": self.remedy,
            "required": self.required,
            "consequence": self.consequence,
        }


@dataclass
class PhaseReport:
    """Everything one phase did, said and concluded."""

    phase: str
    purpose: str
    verdict: Verdict = Verdict.SKIPPED
    summary: str = ""
    commands: list[CommandResult] = field(default_factory=list)
    observations: list[Observation] = field(default_factory=list)
    facts: dict[str, Any] = field(default_factory=dict)
    findings: list[str] = field(default_factory=list)
    remedies: list[str] = field(default_factory=list)
    refusals: list[str] = field(default_factory=list)
    reports: list[str] = field(default_factory=list)
    degradations: list[str] = field(default_factory=list)
    #: A refusal that ``--keep-going`` may not override. Reserved for the
    #: firmware/robot-LAN security control: continuing past it is not a matter
    #: of operator preference.
    hard_stop: bool = False
    elapsed_s: float = 0.0

    def add(self, result: CommandResult) -> CommandResult:
        self.commands.append(result)
        return result

    def fail(self, summary: str, *, remedy: str = "") -> None:
        self.verdict = Verdict.FAIL
        self.summary = summary
        if remedy and remedy not in self.remedies:
            self.remedies.append(remedy)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": PHASE_SCHEMA,
            "harness_version": HARNESS_VERSION,
            "phase": self.phase,
            "purpose": self.purpose,
            "verdict": self.verdict.value,
            "summary": self.summary,
            "elapsed_s": round(self.elapsed_s, 3),
            "facts": self.facts,
            "observations": [item.to_dict() for item in self.observations],
            "findings": list(self.findings),
            "reports": list(self.reports),
            "degradations": list(self.degradations),
            "refusals": list(self.refusals),
            "remedies": list(self.remedies),
            "hard_stop": self.hard_stop,
            "commands": [item.to_dict() for item in self.commands],
        }


@dataclass
class Context:
    """Everything the phases share: options, the runner, and P0's answers."""

    evidence_dir: Path
    record_target: Path
    runner: Runner
    full: bool = False
    keep_going: bool = False
    firmware_attested: str | None = None
    take_minutes: float = 20.0
    repo_root: Path = _REPO_ROOT
    #: Filled in by P0 and read by P1 and P5. Unknown until P0 has run, and
    #: unknown is absent.
    distro: OrinDistro = OrinDistro.UNKNOWN
    reports: dict[str, PhaseReport] = field(default_factory=dict)

    def run(
        self,
        report: PhaseReport,
        argv: Sequence[str],
        *,
        timeout_s: float = DEFAULT_TIMEOUT_S,
        env_extra: Mapping[str, str] | None = None,
    ) -> CommandResult:
        """Run a command and file it in ``report``'s evidence list."""

        return report.add(
            self.runner(tuple(argv), timeout_s=timeout_s, env_extra=env_extra)
        )

    @property
    def smoke_seconds(self) -> int:
        return FULL_SMOKE_SECONDS if self.full else SMOKE_SECONDS

    @property
    def bench_record_seconds(self) -> int:
        return FULL_BENCH_RECORD_SECONDS if self.full else BENCH_RECORD_SECONDS

    @property
    def write_sample_bytes(self) -> int:
        return FULL_WRITE_SAMPLE_BYTES if self.full else WRITE_SAMPLE_BYTES

    def verdict_of(self, phase: str) -> Verdict:
        report = self.reports.get(phase)
        return Verdict.SKIPPED if report is None else report.verdict


# ---------------------------------------------------------------------------
# Small parsers, each one fail-closed
# ---------------------------------------------------------------------------

_VERSION_TEXT = re.compile(r"^[Vv]?(\d+)\.(\d+)\.(\d+)$")
_L4T_RELEASE = re.compile(r"#\s*R(\d+)\s*\(release\).*?REVISION:\s*([\d.]+)", re.IGNORECASE)
_PY_VERSION = re.compile(r"(\d+)\.(\d+)\.(\d+)")
_IPV4 = re.compile(r"^(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})(?:/(\d{1,2}))?$")


def parse_firmware_version(text: str) -> tuple[int, int, int]:
    """``V1.1.13`` -> ``(1, 1, 13)``. Anything else is a refusal.

    Deliberately strict. A version this cannot parse is not "probably fine" and
    is not compared leniently — an unparseable attestation is treated exactly
    like no attestation at all, which is how the pin stays a control.
    """

    match = _VERSION_TEXT.match(text.strip())
    if match is None:
        raise RehearsalRefused(
            f"--firmware-attested {text!r} is not a version of the form V1.1.13. "
            f"Unknown = below pin: read the version in the Unitree app's device "
            f"page and pass exactly what it displays, or pass nothing and stay "
            f"off the robot LAN."
        )
    return (int(match.group(1)), int(match.group(2)), int(match.group(3)))


def firmware_meets_pin(text: str) -> bool:
    """Is this attestation at or above the pin? Tuple compare, never string.

    ``"1.1.9" >= "1.1.13"`` is True in Python — string order puts 9 after 1 —
    and 1.1.9 is precisely a version the pin exists to exclude.
    """

    return parse_firmware_version(text) >= FIRMWARE_PIN


def firmware_pin_text() -> str:
    """The pin and its authority, as one line for an operator-facing message."""

    return (
        f"Go2 firmware pin >= V{FIRMWARE_PIN_TEXT} (adr/0002-firmware-pin.md): Unitree "
        f"DDS on the robot LAN is unauthenticated by design and pre-{FIRMWARE_PIN_TEXT} "
        f"firmware is treated as RCE-capable ({FIRMWARE_CVE_CLASS})."
    )


def classify_distro(result: CommandResult) -> tuple[OrinDistro, tuple[str, ...]]:
    """Classify ``ls /opt/ros`` output. Returns the verdict and what was seen.

    Ambiguity is UNKNOWN, not a guess: two distros under ``/opt/ros`` means the
    answer depends on which ``setup.bash`` the operator's shell sourced, and
    that is a question a directory listing cannot settle.

    A ``ls`` that FAILED is also UNKNOWN, not NONE (FX-2 F5c). Permission
    denied, an I/O error and a missing directory all exit non-zero, and only
    the last of them means "there is no ROS here" — "could not answer" and
    "answered: nothing" have different remedies, and the fail-closed one is the
    one that does not let an unreadable directory read as a settled fact. Only
    a SUCCESSFUL empty read is NONE.
    """

    if not result.available:
        return OrinDistro.UNKNOWN, ()
    names = tuple(
        token
        for token in re.split(r"\s+", result.stdout.strip())
        if token and not token.startswith(".")
    )
    if result.returncode != 0:
        return OrinDistro.UNKNOWN, names
    if not names:
        return OrinDistro.NONE, names
    matched = [_KNOWN_DISTROS[name.lower()] for name in names if name.lower() in _KNOWN_DISTROS]
    unmatched = [name for name in names if name.lower() not in _KNOWN_DISTROS]
    if len(matched) == 1 and not unmatched:
        return matched[0], names
    if not matched:
        return OrinDistro.NONE, names
    return OrinDistro.UNKNOWN, names


def ros_distro_for_plan(distro: OrinDistro) -> RosDistro:
    """Map an observed distro onto the recorder's CLI dialect, or refuse.

    There is no ``RosDistro.FOXY`` and there will not be one until somebody has
    read Foxy's ``record.py``. Refusing here is the whole point: an argv built
    for a dialect nobody checked is an argparse exit-2 with zero bytes written.
    """

    if distro is OrinDistro.HUMBLE:
        return RosDistro.HUMBLE
    if distro is OrinDistro.JAZZY:
        return RosDistro.JAZZY
    raise RehearsalRefused(
        f"P0 classified this machine's ROS distro as {distro.value}. The recorder "
        f"plan renders an argv for HUMBLE or JAZZY only; rendering one for "
        f"{distro.value} would mean guessing a CLI nobody has read, and an unknown "
        f"option is argparse exit 2 with zero bytes recorded. "
        f"{DISTRO_CONSEQUENCE[distro]}"
    )


def parse_ip_brief(text: str) -> dict[str, tuple[str, ...]]:
    """Parse ``ip -brief addr`` into ``interface -> addresses``.

    A line this cannot read is dropped from the address map but recorded by the
    caller as raw output, so the operator still sees it. The judgement made on
    this map is only ever "is an address in this subnet present", and a dropped
    line can only make that answer *less* permissive.
    """

    interfaces: dict[str, tuple[str, ...]] = {}
    for line in text.splitlines():
        parts = line.split()
        if len(parts) < 2:
            continue
        name = parts[0]
        addresses = tuple(item for item in parts[2:] if _IPV4.match(item))
        interfaces[name] = addresses
    return interfaces


def parse_int(text: str) -> int | None:
    try:
        return int(text.strip())
    except (TypeError, ValueError):
        return None


def _now_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _sha256_of(path: Path) -> str:
    import hashlib

    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _first_nonempty_line(text: str) -> str:
    for line in text.splitlines():
        if line.strip():
            return line.strip()
    return ""


def _last_nonempty_line(text: str) -> str:
    """The last line a command said — for stderr, the line that names the cause.

    ``ModuleNotFoundError: No module named 'rclpy'`` is the last line of a
    traceback; ``Traceback (most recent call last):`` is the first, and it is
    not a finding.
    """

    for line in reversed(text.splitlines()):
        if line.strip():
            return line.strip()
    return ""


# ---------------------------------------------------------------------------
# P0 — identity. Board card H-1, executed rather than described.
# ---------------------------------------------------------------------------


def run_p0_identity(ctx: Context) -> PhaseReport:
    report = PhaseReport("p0_identity", PHASES[0][1])

    tegra = ctx.run(report, ("cat", "/etc/nv_tegra_release"))
    lsb = ctx.run(report, ("lsb_release", "-a"))
    kernel = ctx.run(report, ("uname", "-r"))
    machine = ctx.run(report, ("uname", "-m"))
    opt_ros = ctx.run(report, ("ls", "/opt/ros"))
    python_version = ctx.run(report, ("python3", "--version"))
    # lsblk and df are recorded for the operator's eyes, not classified here: which
    # device the record target lives on is a judgement P2 makes with findmnt and
    # shutil.disk_usage, and a second parser of df's human-readable columns would be
    # a second thing that can be wrong about it.
    ctx.run(report, ("lsblk",))
    ctx.run(report, ("df", "-h"))

    nvpmodel_path = shutil.which("nvpmodel")
    if nvpmodel_path:
        ctx.run(report, ("nvpmodel", "-q"))
    tegrastats_path = shutil.which("tegrastats")

    distro, distro_names = classify_distro(opt_ros)
    ctx.distro = distro

    l4t = _L4T_RELEASE.search(tegra.stdout) if tegra.ok else None
    is_jetson = bool(l4t) or bool(nvpmodel_path) or bool(tegrastats_path)
    ubuntu = ""
    for line in lsb.stdout.splitlines():
        if line.lower().startswith("description:"):
            ubuntu = line.split(":", 1)[1].strip()
    py_match = _PY_VERSION.search(python_version.text)

    report.facts = {
        "observed_at_utc": _now_utc(),
        "hostname": platform.node(),
        "is_jetson": is_jetson,
        "l4t_release": f"R{l4t.group(1)} REVISION {l4t.group(2)}" if l4t else None,
        "jetpack_family": _jetpack_family(l4t),
        "ubuntu": ubuntu or None,
        "kernel": kernel.stdout.strip() or None,
        "arch": machine.stdout.strip() or None,
        "python3": py_match.group(0) if py_match else None,
        "opt_ros_entries": list(distro_names),
        "distro": distro.value,
        "distro_consequence": DISTRO_CONSEQUENCE[distro],
        "nvpmodel": nvpmodel_path,
        "tegrastats": tegrastats_path,
        "record_target": str(ctx.record_target),
    }
    report.observations.append(
        Observation(
            "tegrastats",
            Status.PRESENT if tegrastats_path else Status.ABSENT,
            f"path: {tegrastats_path}" if tegrastats_path else "not on PATH",
            remedy=(
                "" if tegrastats_path else
                "tegrastats ships with JetPack; its absence is evidence this is not a "
                "Jetson, or that L4T tools are not installed. Equivalent command: "
                "command -v tegrastats"
            ),
            required=False,
        )
    )
    report.observations.append(
        Observation(
            "nvpmodel",
            Status.PRESENT if nvpmodel_path else Status.ABSENT,
            f"path: {nvpmodel_path}" if nvpmodel_path else "not on PATH",
            required=False,
        )
    )

    if not is_jetson:
        report.reports.append(
            "This host is NOT a Jetson: /etc/nv_tegra_release is unreadable and neither "
            "nvpmodel nor tegrastats is on PATH. Every measurement below therefore "
            "describes some other machine, and no evidence collected here can support "
            "READY_FOR_STATIONARY_STAGE0 for the Orin."
        )
    report.facts["opt_ros_listing_ok"] = bool(opt_ros.ok)
    report.reports.append(f"ROS distro classified {distro.value}. {DISTRO_CONSEQUENCE[distro]}")
    if opt_ros.available and not opt_ros.ok:
        # `ls` ran and refused. That is UNKNOWN, not NONE (FX-2 F5c) — but the
        # line it printed usually settles which one it is, so it is quoted here
        # rather than left for somebody to dig out of the raw command list.
        report.reports.append(
            f"`ls /opt/ros` exited {opt_ros.returncode} and printed: "
            f"{_first_nonempty_line(opt_ros.stderr) or '(nothing)'} — a listing that "
            f"FAILED is classified UNKNOWN, never NONE: 'could not read' and 'read, and "
            f"there is nothing there' have different remedies, and only the second is an "
            f"owner decision about installing a distro. Confirm by hand before acting."
        )
    if distro is not OrinDistro.HUMBLE:
        report.reports.append(
            "Non-Humble is a REPORT, not a harness failure: retargeting the recorder "
            "argv is our software problem (S-2 regenerates the command rows from "
            "Rosbag2Plan), not a defect of this machine."
        )

    collected = [item for item in report.commands if item.available]
    if not collected:
        report.fail(
            "not one identity command could be executed on this host",
            remedy=(
                "Run this harness from a shell on the Orin itself with coreutils on "
                "PATH; if even `uname` is unavailable, the machine is not in a state "
                "any later phase can be run against."
            ),
        )
        return report

    report.verdict = Verdict.PASS
    report.summary = (
        f"identity collected: {'Jetson' if is_jetson else 'NOT a Jetson'}, "
        f"{ubuntu or 'unknown Ubuntu'}, kernel {kernel.stdout.strip() or 'unknown'}, "
        f"python3 {py_match.group(0) if py_match else 'unknown'}, ROS distro {distro.value}"
    )
    report.facts["run_header_markdown"] = _render_run_header(report)
    return report


def _jetpack_family(match: re.Match[str] | None) -> str | None:
    """L4T major release -> the JetPack family the checklist branches on."""

    if match is None:
        return None
    major = int(match.group(1))
    if major >= 36:
        return "JetPack 6.x"
    if major >= 35:
        return "JetPack 5.x"
    return f"L4T R{major} (older than JetPack 5)"


def _render_run_header(report: PhaseReport) -> str:
    """The run-header block H-1 asks for, ready to paste into the run sheet."""

    facts = report.facts
    lines = [
        "## Run header — Orin identity (generated by orin_rehearsal P0)",
        "",
        f"- Observed at: {facts.get('observed_at_utc')} UTC on host {facts.get('hostname')}",
        f"- Is a Jetson: {facts.get('is_jetson')}",
        f"- L4T / JetPack: {facts.get('l4t_release')} / {facts.get('jetpack_family')}",
        f"- Ubuntu: {facts.get('ubuntu')}",
        f"- Kernel: {facts.get('kernel')}   Arch: {facts.get('arch')}",
        f"- Default python3: {facts.get('python3')}",
        f"- /opt/ros entries: {facts.get('opt_ros_entries')}",
        f"- ROS distro classification: {facts.get('distro')}",
        f"- Consequence: {facts.get('distro_consequence')}",
        f"- Record target: {facts.get('record_target')}",
        "",
        "Raw output of every command is in p0_identity.json beside this block.",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# P1 — environment
# ---------------------------------------------------------------------------

#: Package remedies, keyed on what is missing. ``{distro}`` is substituted with
#: the distro P0 actually observed, so an operator never types `humble` at a
#: machine running something else.
_APT = "sudo apt-get update && sudo apt-get install -y "


def run_p1_environment(ctx: Context) -> PhaseReport:
    report = PhaseReport("p1_environment", PHASES[1][1])
    distro_name = ctx.distro.value.lower()
    known_distro = ctx.distro in (OrinDistro.HUMBLE, OrinDistro.JAZZY, OrinDistro.FOXY)

    # --- the USB buffer ---------------------------------------------------
    usbfs = ctx.run(report, ("cat", USBFS_PARAM_PATH))
    usbfs_value = parse_int(usbfs.stdout) if usbfs.ok else None
    usbfs_remedy = (
        f"Runtime, reversible, no reboot: "
        f"echo {USBFS_TARGET_MB} | sudo tee {USBFS_PARAM_PATH}. "
        f"Persistent: back up /boot/extlinux/extlinux.conf first "
        f"(sudo cp -a /boot/extlinux/extlinux.conf ~/tonight/extlinux.conf.bak), then "
        f"append ' usbcore.usbfs_memory_mb={USBFS_TARGET_MB}' to the APPEND line of the "
        f"DEFAULT LABEL, change nothing else, and REBOOT. A reboot is the highest-cost "
        f"action on the bench: there is no second dock, so do not reboot without console "
        f"access on hand. If extlinux.conf does not exist, use the runtime write only and "
        f"carry a re-apply-after-every-boot line into the run sheet."
    )
    if usbfs_value is None:
        report.observations.append(
            Observation(
                "usbfs_memory_mb",
                Status.UNKNOWN,
                f"could not read {USBFS_PARAM_PATH}: "
                f"{usbfs.error or usbfs.stderr.strip() or 'no value'}",
                remedy=usbfs_remedy,
                consequence=(
                    "Unknown = absent. Without a known USB buffer the D455 cannot be "
                    "trusted to stream colour + depth + both IR at once, and the failure "
                    "presents as per-frame errors rather than as 'your buffer is too small'."
                ),
            )
        )
    elif usbfs_value == USBFS_DEFAULT_MB:
        report.observations.append(
            Observation(
                "usbfs_memory_mb",
                Status.ABSENT,
                f"value is {usbfs_value} MB — the kernel default, and the exact value that "
                f"starves the D455 when colour + depth + both IR stream together",
                remedy=usbfs_remedy,
                consequence=(
                    "Dual-IR streaming at 848x480@30 will drop frames. Discovering this "
                    "mid-session costs a reboot cycle."
                ),
            )
        )
    elif usbfs_value < USBFS_TARGET_MB:
        report.observations.append(
            Observation(
                "usbfs_memory_mb",
                Status.DEGRADED,
                f"value is {usbfs_value} MB, below the {USBFS_TARGET_MB} MB target",
                remedy=usbfs_remedy,
            )
        )
    else:
        report.observations.append(
            Observation(
                "usbfs_memory_mb",
                Status.PRESENT,
                f"value is {usbfs_value} MB (>= {USBFS_TARGET_MB})",
            )
        )
    report.facts["usbfs_memory_mb"] = usbfs_value

    # --- the Python 3.10 import claim, executed for the first time --------
    interpreter, interpreter_note, is_310 = _pick_python310(ctx, report)
    import_cmd = ctx.run(
        report,
        (
            interpreter,
            "-c",
            ("import sys, parcel_robot.capture as capture; "
            "print('IMPORT OK', sys.version.split()[0], len(capture.CHANNELS), 'channels')"),
        ),
        env_extra={"PYTHONPATH": str(ctx.repo_root / "src"), "PYTHONDONTWRITEBYTECODE": "1"},
    )
    import_ok = import_cmd.ok and "IMPORT OK" in import_cmd.stdout
    # A successful import under 3.14 is NOT the claim. The claim is that the
    # capture package imports under 3.10, which has only ever been checked
    # statically. An import that ran under some other interpreter leaves that
    # claim exactly as untested as it was, so the status is UNKNOWN — which is
    # absent — and the detail says which interpreter actually ran.
    if import_ok and is_310:
        import_status = Status.PRESENT
    elif import_ok:
        import_status = Status.UNKNOWN
    else:
        import_status = Status.ABSENT
    report.observations.append(
        Observation(
            "python3.10 import parcel_robot.capture",
            import_status,
            (
                f"{interpreter}: "
                f"{_first_nonempty_line(import_cmd.stdout) or import_cmd.error or 'failed'}"
                f" [{interpreter_note}]"
            ),
            remedy=(
                "" if import_status is Status.PRESENT else
                "On Ubuntu 22.04 the default python3 IS 3.10.x, so run this on the Orin "
                "with the repository rsynced there (excluding .parcel/). Until a 3.10 "
                "interpreter actually runs it, the capture package's 3.10 claim is "
                "static only (ast feature_version plus a symbol allow-list) and this "
                "harness will not report it as verified."
            ),
        )
    )
    report.facts["python310_interpreter"] = interpreter
    report.facts["python310_is_310"] = is_310
    report.facts["python310_import_ok"] = import_ok
    if import_ok and is_310:
        report.reports.append(
            f"FIRST dynamic execution of the 3.10 import claim: "
            f"{_first_nonempty_line(import_cmd.stdout)} (interpreter {interpreter}, "
            f"{interpreter_note}). Before this line the claim was static only."
        )
    elif import_ok:
        report.reports.append(
            f"parcel_robot.capture imported cleanly under {interpreter} "
            f"({interpreter_note}): {_first_nonempty_line(import_cmd.stdout)}. That is "
            f"evidence about THIS interpreter and not about 3.10; the 3.10 claim remains "
            f"untested here."
        )

    # --- vendor python modules -------------------------------------------
    for module_name, remedy, required in (
        (
            "pyrealsense2",
            ("python3 -m pip install --user pyrealsense2   # ON THE ORIN, never into "
            ".parcel/. No wheel for this interpreter is an owner decision: install a "
            "python3.10/3.12 alongside, or use the ROS driver path only."),
            True,
        ),
        (
            "rclpy",
            (f"source /opt/ros/{distro_name}/setup.bash  # rclpy ships with the distro; if "
            f"there is no distro, see P0's consequence line"),
            True,
        ),
    ):
        probe = ctx.run(
            report,
            (
                interpreter,
                "-c",
                f"import {module_name} as probed; print('{module_name} at', probed.__file__)",
            ),
        )
        report.observations.append(
            Observation(
                module_name,
                Status.PRESENT if probe.ok else Status.ABSENT,
                # On success stdout carries the answer; on failure the LAST line
                # of stderr is the one that says why. The first line of a Python
                # traceback is the word "Traceback", which told the operator
                # nothing (FX-2 F5b) — the raw output is in the bundle either way.
                _first_nonempty_line(probe.stdout)
                or _last_nonempty_line(probe.stderr)
                or probe.error,
                remedy="" if probe.ok else remedy,
                required=required,
            )
        )

    # --- ROS packages -----------------------------------------------------
    package_checks: tuple[tuple[str, str, str, str, bool], ...] = (
        (
            "rosbag2 mcap storage plugin",
            f"ros-{distro_name}-rosbag2-storage-mcap",
            "",
            f"{_APT}ros-{distro_name}-rosbag2-storage-mcap",
            True,
        ),
        (
            "realsense2_camera",
            f"ros-{distro_name}-realsense2-camera",
            "realsense2_camera",
            f"{_APT}ros-{distro_name}-realsense2-camera ros-{distro_name}-realsense2-camera-msgs",
            True,
        ),
        (
            "unitree_go messages",
            "",
            "unitree_go",
            ("git clone https://github.com/unitreerobotics/unitree_ros2.git ~/unitree_ros2 && "
            "cd ~/unitree_ros2/cyclonedds_ws && colcon build --packages-select unitree_go "
            "unitree_api && source install/setup.bash   # interface packages ONLY, never "
            "unitree_sdk2py"),
            True,
        ),
        (
            "unitree_api messages",
            "",
            "unitree_api",
            "see the unitree_go remedy — the same colcon build produces both",
            True,
        ),
        (
            "unilidar ROS driver",
            "",
            "unitree_lidar_ros2",
            ("git clone https://github.com/unitreerobotics/unilidar_sdk2.git ~/unilidar_sdk2 && "
            "cd ~/unilidar_sdk2/unitree_lidar_ros2 && colcon build --symlink-install && "
            "source install/setup.bash   # names come from the SDK's own README"),
            False,
        ),
    )
    for label, apt_name, ros_package, remedy, required in package_checks:
        status, detail = _package_status(ctx, report, apt_name, ros_package, known_distro)
        report.observations.append(
            Observation(
                label,
                status,
                detail,
                remedy="" if status is Status.PRESENT else remedy,
                required=required,
                consequence=_package_consequence(label) if status is not Status.PRESENT else "",
            )
        )

    missing_required = [
        item
        for item in report.observations
        if item.required and item.status is not Status.PRESENT
    ]
    for item in report.observations:
        if item.remedy and item.remedy not in report.remedies:
            report.remedies.append(f"{item.name}: {item.remedy}")
        if item.status is not Status.PRESENT and not item.required:
            report.degradations.append(f"{item.name} {item.status.value}: {item.consequence or item.detail}")
    if missing_required:
        report.fail(
            "required environment items are not satisfied: "
            + ", ".join(f"{item.name} ({item.status.value})" for item in missing_required)
        )
    else:
        report.verdict = Verdict.PASS
        report.summary = "every required environment item is PRESENT"
    return report


def _pick_python310(ctx: Context, report: PhaseReport) -> tuple[str, str, bool]:
    """Choose the interpreter the 3.10 claim is tested against, and say why.

    Returns ``(interpreter, why, actually_3_10)``. The third value is what makes
    the difference between verifying the claim and merely running an import: a
    clean import under 3.14 says nothing about 3.10 and must not be recorded as
    though it did.
    """

    explicit = ctx.run(report, ("python3.10", "--version"))
    if explicit.ok:
        return "python3.10", f"python3.10 is a separate binary here ({explicit.text.strip()})", True
    default = ctx.run(report, ("python3", "--version"))
    match = _PY_VERSION.search(default.text)
    if match and match.group(0).startswith("3.10."):
        return "python3", f"python3 IS {match.group(0)} (Ubuntu 22.04's default)", True
    return (
        "python3",
        (f"NO python3.10 on this host; falling back to python3 "
        f"{match.group(0) if match else 'of unknown version'} — the 3.10 claim is NOT "
        f"tested by this run"),
        False,
    )


def _package_status(
    ctx: Context,
    report: PhaseReport,
    apt_name: str,
    ros_package: str,
    known_distro: bool,
) -> tuple[Status, str]:
    """Is this package installed? ``ros2 pkg prefix`` first, then ``dpkg-query``."""

    if ros_package:
        probe = ctx.run(report, ("ros2", "pkg", "prefix", ros_package))
        if probe.ok and probe.stdout.strip():
            return Status.PRESENT, f"ros2 pkg prefix {ros_package} -> {probe.stdout.strip()}"
        if not probe.available:
            ros_detail = f"ros2 is not on PATH ({probe.error})"
        else:
            ros_detail = (
                f"ros2 pkg prefix {ros_package} exited {probe.returncode}: "
                f"{_first_nonempty_line(probe.stderr) or 'no prefix'}"
            )
    else:
        ros_detail = ""

    if apt_name:
        if not known_distro:
            return (
                Status.UNKNOWN,
                (
                    f"cannot name the package: P0 classified the distro as "
                    f"{ctx.distro.value}, so 'ros-<distro>-...' has no value to fill in. "
                    f"{ros_detail}"
                ).strip(),
            )
        query = ctx.run(report, ("dpkg-query", "-W", "-f=${Package} ${Version}\n", apt_name))
        if query.ok and query.stdout.strip():
            return Status.PRESENT, f"dpkg-query -> {query.stdout.strip()}"
        if not query.available:
            return Status.UNKNOWN, f"dpkg-query is not on PATH ({query.error}). {ros_detail}".strip()
        return (
            Status.ABSENT,
            f"dpkg-query: {_first_nonempty_line(query.stderr) or 'not installed'}. "
            f"{ros_detail}".strip(),
        )
    return Status.ABSENT, ros_detail or "not found"


def _package_consequence(label: str) -> str:
    if label.startswith("rosbag2"):
        return (
            "Without the mcap storage plugin `-s mcap` is an argparse error and the "
            "recorder of record has no format; on a distro that has no such package the "
            "fallback is -s sqlite3 plus an offline conversion."
        )
    if label.startswith("realsense2_camera"):
        return (
            "89% of the byte budget is topics this driver publishes. Without it the D455 "
            "reaches no bag through ros2 bag record at all."
        )
    if label.startswith("unitree"):
        return (
            "ros2 bag record cannot serialise a message type it cannot resolve: without "
            "these interface packages every dog topic on the command line is skipped "
            "SILENTLY — 10.2% of the byte budget, and every channel carrying the dog's "
            "IMU, foot forces, battery, device clock and proximity sensing."
        )
    if label.startswith("unilidar"):
        return (
            "The add-on L2 has no path into the bag, so the two-LiDAR extrinsic — the "
            "session's cross-validation asset — is not captured, and it is unrecoverable "
            "once the bracket comes off. Mount and tape-measure it regardless."
        )
    return ""


# ---------------------------------------------------------------------------
# P2 — storage
# ---------------------------------------------------------------------------


def run_p2_storage(ctx: Context) -> PhaseReport:
    report = PhaseReport("p2_storage", PHASES[2][1])
    target = ctx.record_target

    if not target.is_dir():
        report.fail(
            f"record target {target} is not a directory",
            remedy=(
                f"Create it and pass it explicitly: mkdir -p {target} && "
                f"python3 -m scripts.parcel_capture.orin_rehearsal --record-target {target}"
            ),
        )
        return report

    ctx.run(report, ("df", "-h", str(target)))
    ctx.run(report, ("findmnt", "-no", "SOURCE,FSTYPE,TARGET", "--target", str(target)))

    budget = build_budget(RECOMMENDED_PROFILE)
    required_mib_s = budget.mib_per_second
    required_free_gib = budget.required_free_gib(ctx.take_minutes * 60.0)
    usage = shutil.disk_usage(target)
    free_gib = usage.free / GIB

    ledger = ctx.repo_root / "scrum" / "20260814" / "task_1" / "DISK_LEDGER.md"
    report.facts["budget"] = {
        "profile": RECOMMENDED_PROFILE.label,
        "required_mib_per_second": round(required_mib_s, 3),
        "required_gib_per_hour": round(budget.gib_per_hour, 3),
        "take_minutes": ctx.take_minutes,
        "required_free_gib_for_take": required_free_gib,
        "margin": budget.margin,
        "source": "scripts/parcel_capture/budget.py::build_budget (generated, not transcribed)",
        "disk_ledger": (
            {"path": str(ledger.relative_to(ctx.repo_root)), "sha256": _sha256_of(ledger)}
            if ledger.is_file()
            else None
        ),
    }
    report.facts["free_gib"] = round(free_gib, 3)
    report.facts["total_gib"] = round(usage.total / GIB, 3)

    measurement = _measure_write(ctx, report, target)
    report.facts["write_measurement"] = measurement

    problems: list[str] = []
    if free_gib < required_free_gib:
        problems.append(
            f"free space {free_gib:.1f} GiB is below the {required_free_gib:.1f} GiB a "
            f"{ctx.take_minutes:.0f}-minute take needs at {required_mib_s:.2f} MiB/s "
            f"(deficit {required_free_gib - free_gib:.1f} GiB)"
        )
    tail = measurement.get("tail_mib_per_second")
    if tail is None:
        problems.append(
            f"no sustained-write measurement was obtained ({measurement.get('detail')}); "
            f"unmeasured is not a pass"
        )
    elif tail < required_mib_s:
        problems.append(
            f"sustained write {tail:.1f} MiB/s is below the {required_mib_s:.2f} MiB/s the "
            f"plan of record needs — deficit {required_mib_s - tail:.1f} MiB/s "
            f"({100.0 * (required_mib_s - tail) / required_mib_s:.0f}% short)"
        )
    if measurement.get("weaker"):
        report.degradations.append(
            f"sustained write measured with {measurement.get('tool')}, which is the WEAKER "
            f"measurement: {measurement.get('weakness')}"
        )
    if not ctx.full:
        report.reports.append(
            f"Sample size was {ctx.write_sample_bytes / GIB:.0f} GiB (default). This does "
            f"not exhaust a DRAM-less NVMe's SLC cache, so a tail that equals the peak has "
            f"disproven nothing. Re-run with --full for the checklist's 40 GiB."
        )

    if problems:
        report.fail(
            "; ".join(problems),
            remedy=(
                "Walk the drop ladder in BANDWIDTH_BUDGET.md section 2 until the "
                "requirement is under half the measured tail, or change the record "
                "destination (external NVMe over USB 3). Re-check that the path measured "
                "here is the path the recorder will write to, not the eMMC. If fio was "
                "absent: sudo apt-get install -y fio, and re-run for the real number."
            ),
        )
        return report
    report.verdict = Verdict.PASS
    report.summary = (
        f"{target}: {free_gib:.1f} GiB free (needs {required_free_gib:.1f}), sustained "
        f"{tail:.1f} MiB/s (needs {required_mib_s:.2f})"
    )
    return report


def _measure_write(ctx: Context, report: PhaseReport, target: Path) -> dict[str, Any]:
    """fio when it exists, dd when it does not, and it says which it used."""

    sample_bytes = ctx.write_sample_bytes
    timeout = 900.0 if ctx.full else 300.0
    if shutil.which("fio"):
        return _measure_with_fio(ctx, report, target, sample_bytes, timeout)
    return _measure_with_dd(ctx, report, target, sample_bytes, timeout)


def _measure_with_fio(
    ctx: Context, report: PhaseReport, target: Path, sample_bytes: int, timeout: float
) -> dict[str, Any]:
    data = target / "parcel_rehearsal_fio.bin"
    log_base = target / "parcel_rehearsal_fio"
    result = ctx.run(
        report,
        (
            "fio",
            "--name=parcel_rehearsal",
            "--rw=write",
            "--bs=1M",
            f"--size={sample_bytes // GIB}G",
            "--end_fsync=1",
            f"--filename={data}",
            "--ioengine=psync",
            "--direct=0",
            f"--write_bw_log={log_base}",
            "--log_avg_msec=1000",
            "--eta=never",
        ),
        timeout_s=timeout,
    )
    peak = tail = None
    samples = 0
    logs = sorted(target.glob("parcel_rehearsal_fio_bw.*.log"))
    for log in logs:
        values: list[float] = []
        for line in log.read_text(encoding="utf-8", errors="replace").splitlines():
            parts = line.split(",")
            if len(parts) < 2:
                continue
            try:
                values.append(float(parts[1].strip()) / 1024.0)
            except ValueError:
                continue
        if values:
            samples = len(values)
            peak = max(values)
            window = values[-60:]
            tail = math.fsum(window) / len(window)
    for path in (data, *logs):
        _remove_quietly(path)
    return {
        "tool": "fio",
        "ok": result.ok and tail is not None,
        "weaker": False,
        "sample_bytes": sample_bytes,
        "samples": samples,
        "peak_mib_per_second": None if peak is None else round(peak, 2),
        "tail_mib_per_second": None if tail is None else round(tail, 2),
        "tail_window_s": min(60, samples),
        "knee_visible": None if (peak is None or tail is None) else bool(peak > tail * 1.25),
        "detail": (
            "fio 1 MiB buffered+fsynced writes; the tail is the mean of the last 60 "
            "one-second bandwidth samples, which is the number a DRAM-less NVMe fails on"
            if tail is not None
            else f"fio produced no bandwidth log ({result.error or result.stderr.strip()[:200]})"
        ),
    }


def _measure_with_dd(
    ctx: Context, report: PhaseReport, target: Path, sample_bytes: int, timeout: float
) -> dict[str, Any]:
    data = target / "parcel_rehearsal_dd.bin"
    blocks = max(1, sample_bytes // MIB)
    result = ctx.run(
        report,
        (
            "dd",
            "if=/dev/zero",
            f"of={data}",
            "bs=1M",
            f"count={blocks}",
            "conv=fdatasync",
        ),
        timeout_s=timeout,
    )
    rate = None
    match = re.search(r"(\d+)\s+bytes.*?copied,\s*([\d.eE+-]+)\s*s", result.stderr, re.DOTALL)
    if match:
        written = float(match.group(1))
        seconds = float(match.group(2))
        if seconds > 0:
            rate = written / seconds / MIB
    _remove_quietly(data)
    return {
        "tool": "dd",
        "ok": result.ok and rate is not None,
        "weaker": True,
        "weakness": (
            "dd reports ONE aggregate rate over the whole write. It cannot show a tail, "
            "cannot show the knee where an SLC cache is exhausted, and therefore cannot "
            "disprove the failure mode this phase exists to catch. Install fio for the "
            "real measurement: sudo apt-get install -y fio"
        ),
        "sample_bytes": sample_bytes,
        "peak_mib_per_second": None,
        "tail_mib_per_second": None if rate is None else round(rate, 2),
        "detail": (
            f"dd {blocks} MiB with conv=fdatasync"
            if rate is not None
            else f"dd produced no parseable rate ({result.error or result.stderr.strip()[:200]})"
        ),
    }


def _remove_quietly(path: Path) -> None:
    try:
        path.unlink()
    except OSError:
        pass


# ---------------------------------------------------------------------------
# P3 — network, and the one refusal --keep-going cannot override
# ---------------------------------------------------------------------------


def run_p3_network(ctx: Context) -> PhaseReport:
    report = PhaseReport("p3_network", PHASES[3][1])

    brief = ctx.run(report, ("ip", "-brief", "addr"))
    ctx.run(report, ("ip", "route"))

    if not brief.available:
        report.fail(
            f"could not enumerate interfaces: {brief.error}",
            remedy=(
                "Install iproute2 (sudo apt-get install -y iproute2) and re-run. Unknown "
                "network state is absent: this harness will not assert that the host is "
                "off the robot LAN without having looked."
            ),
        )
        return report

    interfaces = parse_ip_brief(brief.stdout)
    addresses = {
        name: [item.split("/")[0] for item in addrs] for name, addrs in interfaces.items()
    }
    on_robot_lan = sorted(
        f"{name}={addr}"
        for name, addrs in addresses.items()
        for addr in addrs
        if addr.startswith(ROBOT_LAN_PREFIX)
    )
    on_l2_lan = sorted(
        f"{name}={addr}"
        for name, addrs in addresses.items()
        for addr in addrs
        if addr.startswith(L2_LAN_PREFIX)
    )
    ethernet = sorted(
        name
        for name in interfaces
        if name != "lo" and not name.startswith(("wl", "docker", "veth", "br-", "virbr"))
    )
    report.facts["interfaces"] = addresses
    report.facts["ethernet_candidates"] = ethernet
    report.facts["robot_lan_joined"] = bool(on_robot_lan)
    report.facts["robot_lan_addresses"] = on_robot_lan
    report.facts["l2_subnet_addresses"] = on_l2_lan
    report.facts["firmware_pin"] = FIRMWARE_PIN_TEXT

    # --- the firmware attestation ----------------------------------------
    attested_ok = False
    if ctx.firmware_attested is not None:
        try:
            attested_ok = firmware_meets_pin(ctx.firmware_attested)
        except RehearsalRefused as refusal:
            report.hard_stop = True
            report.refusals.append(str(refusal))
            report.fail(
                f"--firmware-attested {ctx.firmware_attested!r} is malformed",
                remedy=firmware_pin_text(),
            )
            return report
        parsed = parse_firmware_version(ctx.firmware_attested)
        report.facts["firmware_attested"] = ctx.firmware_attested
        report.facts["firmware_attested_parsed"] = list(parsed)
        report.facts["firmware_meets_pin"] = attested_ok
        if not attested_ok:
            report.hard_stop = True
            report.refusals.append(
                f"REFUSED: attested firmware V{'.'.join(str(item) for item in parsed)} is "
                f"BELOW the pin V{FIRMWARE_PIN_TEXT}. {firmware_pin_text()} Nothing may "
                f"join {ROBOT_LAN_PREFIX}0/24 at this version. The session takes the "
                f"DEGRADE-MMP branch: mount, measure, photograph, record nothing — which "
                f"is a legitimate outcome, and finding it now rather than at 10:00 is the "
                f"point of reading the version first."
            )
            report.fail(
                f"attested firmware {ctx.firmware_attested} is below the pin "
                f"V{FIRMWARE_PIN_TEXT}",
                remedy=(
                    "Update the Go2 to at least V1.1.13 from the Unitree app, then re-run "
                    "with the version the app displays. Until then, keep the Orin and the "
                    "laptop off the robot LAN entirely."
                ),
            )
            return report
        report.reports.append(
            f"Firmware attested V{'.'.join(str(item) for item in parsed)} >= pin "
            f"V{FIRMWARE_PIN_TEXT}. This is an operator declaration read from the Unitree "
            f"app, not a measurement this harness made."
        )
    else:
        report.facts["firmware_attested"] = None
        report.facts["firmware_meets_pin"] = False

    # --- the robot-LAN gate ----------------------------------------------
    if on_robot_lan and not attested_ok:
        report.hard_stop = True
        report.refusals.append(
            f"REFUSED: this host holds {', '.join(on_robot_lan)} on the robot LAN "
            f"({ROBOT_LAN_PREFIX}0/24) and no firmware attestation at or above the pin was "
            f"supplied. {firmware_pin_text()} Unknown = below pin. Take the host off that "
            f"subnet, or re-run with --firmware-attested <version read from the Unitree "
            f"app> once the version is known to be at or above V{FIRMWARE_PIN_TEXT}."
        )
        report.fail(
            f"host is on the robot LAN without a cleared firmware attestation "
            f"({', '.join(on_robot_lan)})",
            remedy=(
                f"sudo ip addr del <addr>/24 dev <iface> to leave {ROBOT_LAN_PREFIX}0/24, "
                f"or read the firmware version in the Unitree app and pass "
                f"--firmware-attested V<version>."
            ),
        )
        return report

    if on_robot_lan:
        report.reports.append(
            f"Host is on the robot LAN ({', '.join(on_robot_lan)}) with an attestation at "
            f"or above the pin. No phase of this harness sends anything to the dog; the "
            f"attestation is what makes being on that segment permissible at all."
        )
    else:
        report.reports.append(
            f"Host is NOT on {ROBOT_LAN_PREFIX}0/24. This harness never joins it and "
            f"refuses to run any phase that would without an attestation at or above the "
            f"pin."
        )

    # --- the second NIC (checklist N6) -----------------------------------
    if len(ethernet) < 2:
        report.degradations.append(
            f"only {len(ethernet)} non-wireless interface(s) found ({', '.join(ethernet) or 'none'}): "
            f"the add-on L2 wants its own NIC on {L2_LAN_PREFIX}1/24 with no default route. "
            f"Options, decided at the bench: (a) a USB-Ethernet adapter; (b) an IP alias on "
            f"the single NIC, after which the dog and the LiDAR share one link and one "
            f"bandwidth budget; (c) run the L2 over /dev/ttyACM0 serial instead."
        )
    else:
        report.reports.append(
            f"{len(ethernet)} non-wireless interfaces present ({', '.join(ethernet)}), so a "
            f"dedicated L2 NIC is available without an alias."
        )
    if on_l2_lan:
        report.findings.append(
            f"an interface already carries an address in {L2_LAN_PREFIX}0/24 "
            f"({', '.join(on_l2_lan)}). The L2's factory address is {L2_LAN_PREFIX}2 and "
            f"that subnet is also the commonest home network: a collision here produces a "
            f"LiDAR that pings and delivers nothing, which looks exactly like broken "
            f"hardware. Turn Wi-Fi off at the bench, or move the L2 to its own NIC with no "
            f"default route."
        )

    report.verdict = Verdict.PASS
    report.summary = (
        f"{len(interfaces)} interface(s); robot LAN "
        f"{'JOINED (attested)' if on_robot_lan else 'not joined'}; "
        f"{len(ethernet)} wired candidate(s)"
    )
    return report


# ---------------------------------------------------------------------------
# P4 — sensors on a bench, with no dog
# ---------------------------------------------------------------------------

#: Enumerate D455 devices and print one JSON line. Refuses in the child rather
#: than raising into the parent's evidence: an operator gets a sentence, not a
#: traceback, and the harness gets a machine-readable answer either way.
_D455_ENUMERATE_SCRIPT = """
import json
try:
    import pyrealsense2 as rs
except Exception as problem:
    print(json.dumps({"ok": False, "reason": "pyrealsense2 unavailable: %s" % problem}))
    raise SystemExit(0)
try:
    context = rs.context()
    devices = []
    for device in context.devices:
        devices.append({
            "name": device.get_info(rs.camera_info.name),
            "serial": device.get_info(rs.camera_info.serial_number),
            "firmware": device.get_info(rs.camera_info.firmware_version),
            "usb": device.get_info(rs.camera_info.usb_type_descriptor),
        })
    print(json.dumps({"ok": True, "devices": devices}))
except Exception as problem:
    print(json.dumps({"ok": False, "reason": "enumeration failed: %s" % problem}))
"""

#: Count delivered frames per stream against the rate the profile actually
#: reports, for a fixed window. The callback form is tried first and a plain
#: polling loop is the documented fallback, because the callback spelling
#: varies between pyrealsense2 builds; the requirement is a per-stream
#: delivered-vs-expected count, not one particular API shape.
_D455_FRAMES_SCRIPT = """
import collections, json, sys, time
try:
    import pyrealsense2 as rs
except Exception as problem:
    print(json.dumps({"ok": False, "reason": "pyrealsense2 unavailable: %s" % problem}))
    raise SystemExit(0)

width, height, fps, seconds = (int(value) for value in sys.argv[1:5])
counts = collections.Counter()
mode = "callback"


def configure():
    config = rs.config()
    config.enable_stream(rs.stream.color, width, height, rs.format.rgb8, fps)
    config.enable_stream(rs.stream.depth, width, height, rs.format.z16, fps)
    config.enable_stream(rs.stream.infrared, 1, width, height, rs.format.y8, fps)
    config.enable_stream(rs.stream.infrared, 2, width, height, rs.format.y8, fps)
    config.enable_stream(rs.stream.accel)
    config.enable_stream(rs.stream.gyro)
    return config


def tally(frame):
    try:
        if frame.is_frameset():
            for sub in frame.as_frameset():
                counts[str(sub.profile.stream_name())] += 1
            return
    except Exception:
        pass
    counts[str(frame.profile.stream_name())] += 1


rates = {}
started = time.time()
try:
    pipeline = rs.pipeline()
    try:
        profile = pipeline.start(configure(), tally)
    except Exception:
        mode = "polling"
        profile = pipeline.start(configure())
    rates = {stream.stream_name(): stream.fps() for stream in profile.get_streams()}
    if mode == "callback":
        while time.time() - started < seconds:
            time.sleep(0.5)
    else:
        while time.time() - started < seconds:
            tally(pipeline.wait_for_frames())
    pipeline.stop()
except Exception as problem:
    print(json.dumps({"ok": False, "reason": "streaming failed: %s" % problem,
                      "mode": mode, "counts": dict(counts)}))
    raise SystemExit(0)

elapsed = time.time() - started
# Score the CONFIGURED set, not the delivered set. A stream that delivered
# nothing is absent from `counts`, and scoring `counts` alone would report a
# total loss as "worst stream 100%".
streams = {}
for name in sorted(set(rates) | set(counts)):
    delivered = counts.get(name, 0)
    configured = float(rates.get(name, 0.0))
    expected = configured * elapsed
    streams[name] = {
        "delivered": delivered,
        "configured_hz": configured,
        "expected": round(expected, 1),
        "fraction": round(delivered / expected, 4) if expected else None,
    }
print(json.dumps({"ok": True, "mode": mode, "elapsed_s": round(elapsed, 2),
                  "configured": sorted(rates), "streams": streams}))
"""


def run_p4_sensors(ctx: Context) -> PhaseReport:
    report = PhaseReport("p4_sensors", PHASES[4][1])
    interpreter = str(ctx.reports.get("p1_environment", PhaseReport("", "")).facts.get(
        "python310_interpreter", "python3"
    ))

    enumerate_result = ctx.run(report, (interpreter, "-c", _D455_ENUMERATE_SCRIPT))
    enumerated = _json_line(enumerate_result.stdout)
    devices = enumerated.get("devices") or []
    report.facts["d455_devices"] = devices
    if not enumerated.get("ok"):
        report.observations.append(
            Observation(
                "D455 enumeration",
                Status.ABSENT,
                str(enumerated.get("reason") or enumerate_result.error or "no JSON answer"),
                remedy=(
                    "python3 -m pip install --user pyrealsense2 ON THE ORIN, then re-run. "
                    "If the module is present and no device enumerates: USB 3 blue port, "
                    "direct, no hub; then lsusb | grep -i intel and dmesg | tail -40."
                ),
            )
        )
        report.fail("the D455 could not be enumerated")
        _bench_l2(ctx, report)
        return report
    if not devices:
        report.observations.append(
            Observation(
                "D455 enumeration",
                Status.ABSENT,
                "pyrealsense2 imported but no device is attached",
                remedy=(
                    "USB 3 (blue) port, direct, no hub. Free the camera first: only one "
                    "process may hold it, so stop any other script before re-running."
                ),
            )
        )
        report.fail("no RealSense device is attached")
        _bench_l2(ctx, report)
        return report

    report.observations.append(
        Observation(
            "D455 enumeration",
            Status.PRESENT,
            "; ".join(
                f"{item.get('name')} serial {item.get('serial')} fw {item.get('firmware')} "
                f"usb {item.get('usb')}"
                for item in devices
            ),
        )
    )

    seconds = ctx.smoke_seconds
    frames_result = ctx.run(
        report,
        (
            interpreter,
            "-c",
            _D455_FRAMES_SCRIPT,
            str(BENCH_WIDTH),
            str(BENCH_HEIGHT),
            str(BENCH_FPS),
            str(seconds),
        ),
        timeout_s=seconds + 120.0,
    )
    frames = _json_line(frames_result.stdout)
    report.facts["frame_count"] = frames
    report.facts["frame_count_window_s"] = seconds
    if not frames.get("ok"):
        report.fail(
            f"frame count did not complete: "
            f"{frames.get('reason') or frames_result.error or 'no JSON answer'}",
            remedy=(
                "Check that P1's usbfs_memory_mb is in effect for THIS process, that the "
                "camera is on a direct USB 3 port, and that nothing else holds the device."
            ),
        )
        _bench_l2(ctx, report)
        return report

    reported = frames.get("streams") or {}
    configured = [str(name) for name in (frames.get("configured") or [])]
    report.facts["configured_streams"] = configured
    if not configured:
        report.fail(
            "the frame count reported no CONFIGURED stream, so no stream could be "
            "scored — a count with nothing to compare against is not a pass",
            remedy=(
                "This is the pipeline profile coming back empty from "
                "profile.get_streams(). Re-run the count; if it stays empty, the "
                "pyrealsense2 build reports its profile differently and P4's score "
                "must be adapted to it BEFORE the session, not after."
            ),
        )
        report.facts["frame_count_scored"] = False
        _bench_l2(ctx, report)
        return report

    delivered_by = {
        str(name): int((body or {}).get("delivered") or 0)
        for name, body in reported.items()
    }
    for name in configured:
        delivered_by.setdefault(name, 0)
    missing_kinds = _missing_configured_streams(configured)
    zero_streams = sorted(name for name in configured if delivered_by.get(name, 0) <= 0)
    total_delivered = sum(delivered_by.values())
    report.facts["delivered_by_stream"] = dict(sorted(delivered_by.items()))
    report.facts["frame_count_scored"] = True

    worst = 1.0
    for name, stream in sorted(reported.items()):
        fraction = stream.get("fraction")
        if fraction is None:
            report.findings.append(
                f"{name}: {stream.get('delivered')} frames but the profile reported no "
                f"configured rate, so no expectation could be formed — recorded, not scored"
            )
            continue
        worst = min(worst, float(fraction))
        if fraction >= STREAM_GOOD_FRACTION:
            status = Status.PRESENT
        elif fraction >= STREAM_POOR_FRACTION:
            status = Status.DEGRADED
        else:
            status = Status.ABSENT
        detail = (
            f"{stream.get('delivered')} delivered / {stream.get('expected')} expected at "
            f"{stream.get('configured_hz')} Hz = {100.0 * float(fraction):.1f}%"
        )
        report.observations.append(Observation(f"stream {name}", status, detail, required=True))
        if status is Status.DEGRADED:
            report.degradations.append(
                f"stream {name} is DEGRADED: {detail}. The deficit is quantified here and "
                f"must be carried into the sidecar rather than smoothed away."
            )

    report.facts["worst_stream_fraction"] = round(worst, 4)
    _bench_l2(ctx, report)

    # Zero delivery is judged BEFORE the fraction ladder, and independently of
    # it: a stream with no configured rate has no fraction at all, and "no
    # expectation could be formed" must never be the reason a dead stream reads
    # as healthy.
    ladder_remedy = (
        "Step down the drop ladder in BANDWIDTH_BUDGET.md section 2 and re-run "
        "this exact count at each rung until one holds at 99%: 848x480@30 C+D (IR "
        "off), then 848x480@15 C+D+IR, then 848x480@30 D+IR (colour off). Whatever "
        "profile survives is the session's profile and the driver's launch profile."
    )
    if total_delivered <= 0:
        report.fail(
            f"TOTAL LOSS: not one frame arrived on any of the "
            f"{len(configured)} configured stream(s) ({', '.join(configured)}) in "
            f"{seconds}s. The pipeline started and delivered nothing",
            remedy=(
                "Nothing arrived at all, so this is not the drop ladder: check that "
                "usbfs_memory_mb from P1 is in effect for THIS process, that the "
                "camera is on a direct USB 3 (blue) port with no hub, that no other "
                "process holds the device, and re-run. dmesg | tail -40 after the run."
            ),
        )
        return report
    if zero_streams:
        report.fail(
            f"configured stream(s) {', '.join(zero_streams)} delivered ZERO frames in "
            f"{seconds}s while others delivered; a configured stream that delivers "
            f"nothing is a lost stream, not an unscored one",
            remedy=ladder_remedy,
        )
        return report
    if missing_kinds:
        report.fail(
            f"the frame count never configured {', '.join(missing_kinds)}: the plan "
            f"profile enables colour, depth, both infrared and the IMU, and the "
            f"pipeline reported only {configured}",
            remedy=(
                "Either the stream failed to enable — read the phase's raw output for "
                "the pipeline error — or this pyrealsense2 build spells the stream "
                "differently, in which case the name it DID report is in the bundle "
                "and CONFIGURED_STREAMS must learn it before the session, not after."
            ),
        )
        return report

    if worst < STREAM_POOR_FRACTION:
        report.fail(
            f"a stream delivered only {100.0 * worst:.1f}% of its expected frames — the "
            f"reported ~80% RGB-drop failure has reproduced on this unit",
            remedy=ladder_remedy,
        )
        return report
    report.verdict = Verdict.PASS
    report.summary = (
        f"D455 enumerated ({len(devices)} device(s)); {len(configured)} configured "
        f"stream(s) all delivering, worst stream "
        f"{100.0 * worst:.1f}% over {seconds}s at {BENCH_WIDTH}x{BENCH_HEIGHT}@{BENCH_FPS}"
    )
    return report


def _normalise_stream_name(name: str) -> str:
    return "".join(character for character in name.lower() if character.isalnum())


def _missing_configured_streams(reported: Sequence[str]) -> list[str]:
    """Which of :data:`CONFIGURED_STREAMS` no reported name accounts for."""

    normalised = [_normalise_stream_name(name) for name in reported]
    missing: list[str] = []
    for label, spellings in CONFIGURED_STREAMS:
        if not any(
            candidate == spelling or candidate.startswith(spelling)
            for candidate in normalised
            for spelling in spellings
        ):
            missing.append(label)
    return missing


def _bench_l2(ctx: Context, report: PhaseReport) -> None:
    """The add-on L2 bench read, through the ingest adapter that already serves it."""

    try:
        from scripts.parcel_capture.ingest.l2 import L2Ingest
    except ImportError as problem:
        report.observations.append(
            Observation(
                "L2 bench read",
                Status.UNKNOWN,
                f"the l2 ingest adapter could not be imported: {problem}",
                remedy="Run from the repository root so scripts.parcel_capture is importable.",
                required=False,
            )
        )
        return

    dependencies = L2Ingest.dependency_report()
    if not dependencies.satisfied:
        report.observations.append(
            Observation(
                "L2 bench read",
                Status.ABSENT,
                f"adapter {dependencies.adapter} missing {list(dependencies.missing)}",
                remedy=dependencies.remedy
                or (
                    "Build unilidar_sdk2 on the Orin and put its python binding on "
                    "PYTHONPATH. Never into .parcel/."
                ),
                required=False,
                consequence=_package_consequence("unilidar ROS driver"),
            )
        )
        report.degradations.append(
            "L2 bench read ABSENT: the add-on LiDAR was not read on this bench, so the "
            "two-LiDAR cross-validation asset is unproven. Tape-measure the geometry "
            "regardless — it is unrecoverable once the bracket comes off."
        )
        return

    adapter = L2Ingest()
    counts: dict[str, int] = {}
    problems: dict[str, str] = {}
    window = 5.0
    for entry in adapter.channels():
        try:
            counts[entry.channel_id] = sum(1 for _ in adapter.read(entry, window))
        # Blind on purpose: an adapter refusal, a vendor binding raising something
        # of its own, and a transport timeout are all EVIDENCE about the bench. None
        # of them may become a traceback in front of an operator.
        except Exception as problem:  # noqa: BLE001
            problems[entry.channel_id] = f"{type(problem).__name__}: {problem}"
    report.facts["l2_bench"] = {"window_s": window, "counts": counts, "problems": problems}
    cloud = any("cloud" in key and value > 0 for key, value in counts.items())
    imu = any("imu" in key and value > 0 for key, value in counts.items())
    report.observations.append(
        Observation(
            "L2 bench read",
            Status.PRESENT if (cloud and imu) else Status.ABSENT,
            f"over {window:.0f}s: counts={counts} problems={problems}",
            remedy=(
                ""
                if (cloud and imu)
                else "Check the second-NIC address and the L2's factory IP; then the serial "
                "path (/dev/ttyACM*) if Ethernet does not answer."
            ),
            required=False,
        )
    )
    if not (cloud and imu):
        report.degradations.append(
            "L2 bench read did not produce both a cloud and IMU samples; the two-LiDAR "
            "extrinsic is not captured by this session."
        )


def _json_line(text: str) -> dict[str, Any]:
    """The last JSON object a child printed, or an empty mapping. Never raises."""

    for line in reversed(text.splitlines()):
        line = line.strip()
        if line.startswith("{") and line.endswith("}"):
            try:
                parsed = json.loads(line)
            except ValueError:
                continue
            if isinstance(parsed, dict):
                return parsed
    return {}


# ---------------------------------------------------------------------------
# P5 — the whole recorder path, end to end, on the real machine
# ---------------------------------------------------------------------------


def refuse_unless_bench_topic(topic: str) -> str:
    """Guard every topic the harness itself would source. Refuses everything else.

    Two independent checks, so a test can prove each one separately: the name
    must live under the rehearsal namespace, and it must carry no marker of a
    command or request surface. A bench source exists to give the recorder
    something sensor-shaped to subscribe to; it is not a route to the robot.
    """

    folded = topic.lower()
    if any(marker in folded for marker in COMMAND_TOPIC_MARKERS):
        raise RehearsalRefused(
            f"{topic!r} carries a command/request marker. This harness sources sensor "
            f"messages only and never a command surface, in any form."
        )
    if not topic.startswith(BENCH_TOPIC_PREFIX):
        raise RehearsalRefused(
            f"{topic!r} is outside {BENCH_TOPIC_PREFIX}. The bench source may only use "
            f"the rehearsal namespace, so nothing it starts can collide with a real "
            f"sensor topic or reach the robot's graph."
        )
    return topic


def refuse_unless_bench_message_type(message_type: str) -> str:
    """Guard the MESSAGE TYPE a bench source would publish. Refuses commands.

    A topic name is only half the surface. ``ros2 topic pub`` publishes a type,
    and a ``geometry_msgs/msg/Twist`` on a sensor-shaped name is a velocity
    command whatever the name says. Two independent checks again, so each is
    provable on its own: the type must carry no command/request marker, and it
    must come from the sensor-data allow-list.
    """

    folded = message_type.lower()
    if any(marker in folded for marker in COMMAND_TYPE_MARKERS):
        raise RehearsalRefused(
            f"{message_type!r} is a command/request message type. This harness "
            f"publishes sensor data only; a command type on a bench topic is still "
            f"a command surface."
        )
    if not any(folded.startswith(prefix) for prefix in BENCH_TYPE_PREFIXES):
        raise RehearsalRefused(
            f"{message_type!r} is outside the bench allow-list "
            f"{list(BENCH_TYPE_PREFIXES)}. The bench source exists to give the "
            f"recorder something sensor-shaped to subscribe to; anything else needs "
            f"a reason nobody has written down."
        )
    return message_type


def bench_source_argv(topic: str, message_type: str, rate_hz: float) -> tuple[str, ...]:
    """The exact argv for one synthetic sensor-shaped bench source."""

    refuse_unless_bench_topic(topic)
    refuse_unless_bench_message_type(message_type)
    return ("ros2", "topic", "pub", "-r", f"{rate_hz:g}", topic, message_type, "{}")


def bench_plan(
    output_dir: Path,
    topics: Sequence[tuple[str, str]],
    *,
    distro: RosDistro,
    storage_config_path: Path | None = None,
) -> Rosbag2Plan:
    """A recording plan over exactly the topics that were observed to exist."""

    recorded = tuple(
        RecordedTopic(
            topic=topic,
            message_type=message_type,
            source=TopicSource.DRIVER_NODE,
            channel_id=None,
            # CONFIRMED is about the strength of what is KNOWN about the row, and
            # this row was read straight off `ros2 topic list -t` on the machine
            # that will record it. That is the strongest basis a topic row can
            # have; it is not a claim that the topic carries good data.
            confidence=Confidence.CONFIRMED,
            note="observed on the graph by `ros2 topic list -t` during the OR-1 rehearsal",
            prerequisite="the driver or bench source that publishes it is running",
        )
        for topic, message_type in topics
    )
    return Rosbag2Plan(
        output_dir=output_dir,
        topics=recorded,
        profile=WriterProfile.CRASH_SAFE,
        distro=distro,
        storage_config_path=storage_config_path,
    )


def run_p5_recorder(ctx: Context) -> PhaseReport:
    report = PhaseReport("p5_recorder", PHASES[5][1])

    # 1. the distro gate — refuse rather than guess a CLI dialect
    try:
        plan_distro = ros_distro_for_plan(ctx.distro)
    except RehearsalRefused as refusal:
        report.refusals.append(str(refusal))
        report.fail(
            f"cannot render a recorder argv for distro {ctx.distro.value}",
            remedy=(
                "Answer P0's question by hand (ls /opt/ros; ros2 bag record --help) and "
                "re-run. S-2's addendum finalizes on that answer."
            ),
        )
        return report
    report.facts["plan_distro"] = plan_distro.value

    # 2. the installed recorder's own help, captured before anything is typed
    help_result = ctx.run(report, record_help_command())
    if not help_result.ok or not help_result.stdout.strip():
        report.fail(
            f"`{' '.join(record_help_command())}` did not produce help text "
            f"({help_result.error or help_result.stderr.strip()[:200] or 'empty output'})",
            remedy=(
                f"source /opt/ros/{ctx.distro.value.lower()}/setup.bash, then "
                f"{_APT}ros-{ctx.distro.value.lower()}-rosbag2-storage-mcap, then re-run. "
                f"Without the installed help text the argv is unverified, and an unknown "
                f"option is argparse exit 2 with zero bytes recorded."
            ),
        )
        return report

    # 3. what is actually on the graph right now
    topic_list = ctx.run(report, ("ros2", "topic", "list", "-t"))
    observed = _parse_topic_types(topic_list.stdout)
    report.facts["observed_topics"] = {name: list(types) for name, types in observed.items()}
    sensor_topics = sorted(
        (name, types[0])
        for name, types in observed.items()
        if name.startswith(("/camera/", "/unilidar/")) and types
    )

    # The bench bag is written to the RECORD TARGET, not to the evidence
    # directory. P2 measured the sustained write of the record destination;
    # rehearsing the recorder onto some other volume measures a different disk
    # and tells the session nothing — the no-dog checklist says so in as many
    # words at N4d. The bag stays there (with `--full` and real camera topics it
    # is gibibytes, which nobody wants to copy home); the evidence bundle carries
    # its path, its per-file digests and its sidecar.
    bench_dir = ctx.record_target / "parcel_rehearsal_bench_bag"
    if bench_dir.exists():
        shutil.rmtree(bench_dir, ignore_errors=True)
    storage_config = ctx.evidence_dir / "bench_storage_config.yaml"
    storage_config.write_text(storage_config_yaml(WriterProfile.CRASH_SAFE), encoding="utf-8")

    sources: list[tuple[str, str, float]] = []
    if sensor_topics:
        record_topics = list(sensor_topics)
        origin = EvidenceOrigin.PHYSICAL
        report.reports.append(
            f"Recording {len(record_topics)} REAL driver topic(s) observed on the graph. "
            f"This is the end-to-end proof: a driver node's topics, its QoS and its "
            f"burstiness, through the exact argv the session will type."
        )
    else:
        sources = list(BENCH_SOURCES)
        record_topics = [(topic, message_type) for topic, message_type, _ in sources]
        # SIMULATION, declared explicitly. build_rosbag2_sidecar defaults to
        # PHYSICAL because ros2 bag record cannot run without a live graph — but a
        # graph fed by this harness's own bench source is not a sensor, and a
        # rehearsal that inherited PHYSICAL would mint physical authority for
        # bytes nothing measured.
        origin = EvidenceOrigin.SIMULATION
        report.reports.append(
            "No /camera/ or /unilidar/ topic was on the graph, so the recorder is driven "
            "by synthetic sensor-shaped sources under "
            f"{BENCH_TOPIC_PREFIX}. This proves the argv, the recorder and the reader, and "
            "it exercises the sidecar as far as its refusal. It does NOT prove that a "
            "driver node's topics reach the recorder — different QoS, different "
            "burstiness, a different message type, and it competes for the same CPU — "
            "which is a different failure mode with a different remedy."
        )

    try:
        for topic, message_type in record_topics:
            if not sensor_topics:
                refuse_unless_bench_topic(topic)
                refuse_unless_bench_message_type(message_type)
        plan = bench_plan(
            bench_dir, record_topics, distro=plan_distro, storage_config_path=storage_config
        )
        argv = record_command(plan)
    except (RehearsalRefused, Rosbag2Error) as refusal:
        report.refusals.append(str(refusal))
        report.fail("the recording plan was refused before anything was recorded")
        return report
    report.facts["rendered_argv"] = list(argv)
    report.facts["record_topics"] = [name for name, _ in record_topics]
    report.facts["origin_declared"] = origin.value

    # 4. clear the argv against the installed help BEFORE first use
    try:
        checked = validate_argv_against_help(argv, help_result.stdout)
    except Rosbag2RefusedError as refusal:
        report.refusals.append(str(refusal))
        report.fail(
            "the rendered argv carries a flag the installed recorder does not have — "
            "REFUSED before recording",
            remedy=(
                "Re-render with the distro this machine actually runs. This refusal is the "
                "gate working: argparse would have exited 2 and the session would have "
                "recorded zero bytes."
            ),
        )
        return report
    report.facts["verified_flags"] = list(checked)
    report.reports.append(
        f"argv cleared against the installed `ros2 bag record --help`: "
        f"{len(checked)} flag(s) checked, all present."
    )

    # 5. record a timed bench bag through that exact argv
    seconds = ctx.bench_record_seconds
    sourced = _start_bench_sources(ctx, report, sources)
    try:
        record_result = _record_for(ctx, report, argv, seconds)
    finally:
        _stop_processes(sourced)
    if bench_dir.is_dir():
        ctx.run(report, ("ls", "-l", str(bench_dir)))
    if not bench_dir.is_dir():
        report.fail(
            f"the recorder wrote nothing to {bench_dir} "
            f"({record_result.error or record_result.stderr.strip()[:300] or 'no output'})",
            remedy=(
                "Read the recorder's own stderr above: an argparse error means a flag the "
                "installed recorder does not have; 'No storage could be initialized' means "
                "the mcap plugin or the storage config; no subscription means nothing was "
                "publishing on the listed topics."
            ),
        )
        return report

    # 6. read the bag back with the repository's own reader
    try:
        directory = discover_bag(bench_dir)
        scans = [read_rosbag2_mcap(path) for path in directory.files]
    # Blind on purpose: the reader is S-1's surface and in flight. Whatever it
    # raises is reported verbatim as a refusal, never re-raised at the operator.
    except Exception as problem:  # noqa: BLE001
        report.refusals.append(f"{type(problem).__name__}: {problem}")
        report.fail(f"the bag could not be read back: {type(problem).__name__}: {problem}")
        return report
    counts: dict[str, int] = {}
    for scan in scans:
        for topic, count in scan.counts.items():
            counts[topic] = counts.get(topic, 0) + count
    report.facts["bag"] = {
        "directory": str(bench_dir),
        "on_record_target": True,
        "files": {path.name: _sha256_of(path) for path in directory.files},
        "bytes": {path.name: path.stat().st_size for path in directory.files},
        "termination": [scan.termination.value for scan in scans],
        "count_basis": sorted({scan.count_basis.value for scan in scans}),
        "counts": counts,
        "seconds": seconds,
    }
    unclean = [scan for scan in scans if not scan.is_clean]
    if unclean or not counts:
        report.fail(
            f"the bag read back as {[scan.termination.value for scan in scans]} with counts "
            f"{counts}",
            remedy=(
                "A recorder killed before it finalized leaves a truncated tail; a bag with "
                "no counted message means nothing was published on the recorded topics. "
                "Both are findings, not formalities."
            ),
        )
        return report

    # 7. build the sidecar and verify it against its own bytes
    #
    # A bench bag driven by synthetic sources carries no topic that maps to a
    # channel of the matrix, and the sidecar REFUSES such a bag by design — "a
    # bag with no known channel is a finding, not a manifest". So the expected
    # outcome is decided BEFORE the call, from the topics actually recorded, and
    # the refusal is asserted rather than swallowed: a sidecar that minted a
    # manifest over unmapped channels would be a defect in the gate, and this
    # phase would fail on it.
    mapped_topics = sorted(name for name, _ in record_topics if name in CHANNEL_BY_TOPIC)
    report.facts["mapped_topics"] = mapped_topics
    try:
        from scripts.parcel_capture.sidecar import (
            SidecarRefusedError,
            build_rosbag2_sidecar,
            sidecar_digest,
            verify_rosbag2_sidecar,
            write_sidecar,
        )

        sidecar = build_rosbag2_sidecar(
            bag_id=f"or1-bench-{int(time.time())}",
            bag_dir=bench_dir,
            origin=origin,
            session_notes=(
                ("OR-1 no-dog Orin rehearsal bench bag. Nothing in this session commanded "
                "motion; the recorder subscribes and nothing else."),
            ),
            extra_does_not_prove=(
                ("A bench bag proves the recorder path, not the session: no dog was on, no "
                "calibration or transform artifact was recorded, and the take is seconds "
                "rather than the session's minutes."),
            ),
        )
        sidecar_path = ctx.evidence_dir / "bench_bag.parcel-bag.json"
        write_sidecar(sidecar, sidecar_path)
        verification = verify_rosbag2_sidecar(sidecar, bench_dir)
    except SidecarRefusedError as refusal:
        if mapped_topics:
            report.refusals.append(f"SidecarRefusedError: {refusal}")
            report.fail(
                f"the sidecar refused a bag carrying mapped channels {mapped_topics}: "
                f"{refusal}",
                remedy=(
                    "This is the adapter S-1 owns. Report the message verbatim; do not "
                    "edit sidecar.py from this card."
                ),
            )
            return report
        report.facts["sidecar"] = {
            "built": False,
            "expected_refusal": str(refusal),
            "origin": origin.value,
        }
        report.reports.append(
            f"The sidecar REFUSED the synthetic bench bag, which is the correct answer "
            f"and is asserted here rather than tolerated: none of {[n for n, _ in record_topics]} "
            f"maps to a channel of the matrix, and a manifest over unmapped channels "
            f"would be the defect. Refusal text: {refusal}"
        )
        report.degradations.append(
            "the sidecar step was exercised only as far as its refusal, because the bench "
            "had no real sensor topic. Re-run with the RealSense/L2 drivers running to "
            "carry the bench bag through to a written, verified manifest."
        )
    # Blind on purpose, and for the same reason: if S-1 shifts this API mid-run the
    # harness reports the mismatch as a finding. It never edits their file and it
    # never hands the bench a stack trace.
    except Exception as problem:  # noqa: BLE001
        report.refusals.append(f"{type(problem).__name__}: {problem}")
        report.fail(
            f"the sidecar could not be built or verified: {type(problem).__name__}: {problem}",
            remedy=(
                "This is the adapter S-1 owns. Report the message verbatim; do not edit "
                "sidecar.py from this card."
            ),
        )
        return report
    else:
        report.facts["sidecar"] = {
            "built": True,
            "path": str(sidecar_path),
            "digest": sidecar_digest(sidecar),
            "verified": bool(verification.ok),
            "failures": list(verification.failures),
            "origin": origin.value,
        }
        if not verification.ok:
            report.fail(
                f"the sidecar did not verify against its own bag: "
                f"{list(verification.failures)}"
            )
            return report
        if not mapped_topics:
            report.fail(
                "the sidecar built a manifest for a bag whose topics map to NO channel of "
                "the matrix. That is a hole in the gate, not a pass: a bag with no known "
                "channel is a finding, and this harness will not certify one.",
                remedy=(
                    "Report to S-1, who owns sidecar.py. Do not proceed to a session on a "
                    "manifest that cannot name what it recorded."
                ),
            )
            return report

    # 8. preflight's support reconciliation against the observed graph
    #
    # Blind on purpose — preflight is S-1's surface, in flight in this same tree
    # and lazily imported — but blind is not the same as green. A step that
    # THREW did not run, and a step that did not run cannot certify the phase:
    # on the Orin, against real PHYSICAL topics, a crashed support-topic check
    # used to read as a green P5 (FX-2 F2). The exception becomes one sentence
    # and a phase FAIL; the operator still never sees a traceback.
    try:
        from scripts.parcel_capture.preflight import reconcile_support_topics

        reconciliation = reconcile_support_topics(topic_list.stdout)
        report.facts["support_reconciliation"] = reconciliation.to_dict()
    except Exception as problem:  # noqa: BLE001
        detail = f"{type(problem).__name__}: {_first_nonempty_line(str(problem)) or problem}"
        report.facts["support_reconciliation"] = {"error": detail}
        report.refusals.append(detail)
        report.fail(
            f"support reconciliation could not run: {detail} — the support-topic gate "
            f"did not execute, so this phase certifies nothing about camera_info or "
            f"the transform topics",
            remedy=(
                "This is S-1's surface (scripts/parcel_capture/preflight.py). Report "
                "the message verbatim; do not edit their file from this card. Re-run "
                "P5 once it imports and runs — a gate that threw is not a gate that "
                "passed."
            ),
        )
        return report

    if not reconciliation.ok:
        message = (
            f"preflight support reconciliation refuses this graph: "
            f"{list(reconciliation.refusals)}"
        )
        if sensor_topics:
            report.fail(
                message,
                remedy=(
                    "The camera driver must publish camera_info and the transform topics "
                    "before a session bag can finalize GO-RECORD. Launch the driver with "
                    "the profile P4 survived at, and re-check with ros2 topic list -t."
                ),
            )
            return report
        report.reports.append(
            message
            + " — EXPECTED on a synthetic bench with no camera driver running, and it is "
            "S-1's gate doing exactly its job. It does not gate this phase, because a "
            "bench source cannot publish calibration it does not have."
        )

    report.verdict = Verdict.PASS
    sidecar_step = (
        "sidecar built and verified"
        if report.facts["sidecar"].get("built")
        else "sidecar refused the unmapped bench bag, as it must"
    )
    report.summary = (
        f"help verified -> argv rendered for {plan_distro.value} -> {seconds}s recorded -> "
        f"{sum(counts.values())} message(s) read back clean -> {sidecar_step}"
    )
    return report


def _parse_topic_types(text: str) -> dict[str, tuple[str, ...]]:
    """``ros2 topic list -t`` -> ``topic -> types``. Unreadable lines are dropped.

    Dropping a line can only *shrink* the set of topics the harness will record,
    so an unparsed line cannot smuggle a topic onto the command line.
    """

    observed: dict[str, tuple[str, ...]] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line.startswith("/"):
            continue
        if " [" in line and line.endswith("]"):
            name, _, rest = line.partition(" [")
            observed[name.strip()] = tuple(
                item.strip() for item in rest[:-1].split(",") if item.strip()
            )
        else:
            observed[line.split()[0]] = ()
    return observed


def _start_bench_sources(
    ctx: Context, report: PhaseReport, sources: Sequence[tuple[str, str, float]]
) -> list[subprocess.Popen[str]]:
    """Start the synthetic sensor-shaped sources, if any are needed."""

    started: list[subprocess.Popen[str]] = []
    for topic, message_type, rate in sources:
        argv = bench_source_argv(topic, message_type, rate)
        report.facts.setdefault("bench_sources", []).append(" ".join(argv))
        try:
            started.append(
                subprocess.Popen(
                    argv,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    text=True,
                )
            )
        except OSError as problem:
            report.findings.append(f"bench source {topic} could not start: {problem}")
    if started:
        time.sleep(3.0)
    return started


def _stop_processes(processes: Iterable[subprocess.Popen[str]]) -> None:
    for proc in processes:
        try:
            proc.terminate()
            proc.wait(timeout=10)
        except (OSError, ValueError, subprocess.TimeoutExpired):
            try:
                proc.kill()
            except OSError:
                continue


def _record_for(
    ctx: Context, report: PhaseReport, argv: Sequence[str], seconds: int
) -> CommandResult:
    """Run the recorder for a fixed window and stop it the way an operator does.

    ``ros2 bag record`` finalizes on SIGINT — the Ctrl-C on the run sheet — so
    the harness sends exactly that and then waits, rather than killing it and
    then blaming the bag for being truncated.
    """

    started = time.monotonic()
    try:
        proc = subprocess.Popen(
            tuple(argv), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
        )
    except (OSError, ValueError) as problem:
        result = CommandResult(
            tuple(argv), None, "", "", time.monotonic() - started, error=f"could not start: {problem}"
        )
        report.add(result)
        return result
    time.sleep(seconds)
    try:
        proc.send_signal(signal.SIGINT)
        stdout, stderr = proc.communicate(timeout=90)
    except subprocess.TimeoutExpired:
        proc.kill()
        stdout, stderr = proc.communicate()
        stderr = (stderr or "") + "\n[harness] recorder did not exit on SIGINT; killed"
    result = CommandResult(
        tuple(argv), proc.returncode, stdout or "", stderr or "", time.monotonic() - started
    )
    report.add(result)
    return result


# ---------------------------------------------------------------------------
# The driver, the verdict and the CLI
# ---------------------------------------------------------------------------

PHASE_FUNCTIONS: Mapping[str, Callable[[Context], PhaseReport]] = {
    "p0_identity": run_p0_identity,
    "p1_environment": run_p1_environment,
    "p2_storage": run_p2_storage,
    "p3_network": run_p3_network,
    "p4_sensors": run_p4_sensors,
    "p5_recorder": run_p5_recorder,
}


def run_rehearsal(ctx: Context, *, until: str | None = None) -> dict[str, Any]:
    """Run the phases in order, writing each phase's evidence as it completes."""

    ctx.evidence_dir.mkdir(parents=True, exist_ok=True)
    last = PHASE_IDS.index(until) if until else len(PHASE_IDS) - 1
    stopped_by: str | None = None

    for index, (phase_id, purpose) in enumerate(PHASES):
        if index > last:
            report = PhaseReport(phase_id, purpose, Verdict.SKIPPED)
            report.summary = f"not requested (--until {until})"
        elif stopped_by is not None:
            report = PhaseReport(phase_id, purpose, Verdict.SKIPPED)
            report.summary = (
                f"skipped: {stopped_by} failed and a failed phase stops the ones that "
                f"depend on it (pass --keep-going to run them anyway; a security refusal "
                f"is never overridden)"
            )
        else:
            started = time.monotonic()
            report = PHASE_FUNCTIONS[phase_id](ctx)
            report.elapsed_s = time.monotonic() - started
        ctx.reports[phase_id] = report
        _write_json(ctx.evidence_dir / f"{phase_id}.json", report.to_dict())
        print(
            f"[{report.verdict.value:>7}] {phase_id:<14} {report.summary or report.purpose}",
            flush=True,
        )
        for line in report.refusals:
            print(f"          REFUSAL: {line}", flush=True)
        stops_the_rest = report.hard_stop or not ctx.keep_going
        if report.verdict is Verdict.FAIL and stopped_by is None and stops_the_rest:
            stopped_by = phase_id

    verdict = build_verdict(ctx)
    _write_json(ctx.evidence_dir / "verdict.json", verdict)
    return verdict


def build_verdict(ctx: Context) -> dict[str, Any]:
    """Map the phase results onto the board's readiness language, and no further.

    This file records **evidence**. The readiness verdict itself
    (``READY_FOR_STATIONARY_STAGE0`` / ``DEGRADE_MMP_ONLY`` / ``NOT_READY``) is
    AU-F/Fable's to issue, and saying so here is not modesty — a harness that
    graded its own run would be the thing the board's separation of authority
    exists to prevent.
    """

    phases = {phase_id: ctx.verdict_of(phase_id).value for phase_id in PHASE_IDS}
    blockers: list[str] = []
    degradations: list[str] = []
    refusals: list[str] = []
    for phase_id in PHASE_IDS:
        report = ctx.reports.get(phase_id)
        if report is None:
            continue
        degradations.extend(f"{phase_id}: {item}" for item in report.degradations)
        refusals.extend(f"{phase_id}: {item}" for item in report.refusals)
        if report.verdict is Verdict.FAIL:
            blockers.append(f"{phase_id}: {report.summary}")
        elif report.verdict is Verdict.SKIPPED:
            blockers.append(f"{phase_id}: NOT RUN — {report.summary}")

    identity = ctx.reports.get("p0_identity")
    if identity is not None and identity.facts.get("is_jetson") is False:
        blockers.append(
            "p0_identity: this host is not a Jetson, so nothing measured here is evidence "
            "about the Orin"
        )
    all_green = not blockers
    bundle = {}
    if ctx.evidence_dir.is_dir():
        for path in sorted(ctx.evidence_dir.glob("*.json")):
            if path.name != "verdict.json":
                bundle[path.name] = _sha256_of(path)

    return {
        "schema": VERDICT_SCHEMA,
        "harness_version": HARNESS_VERSION,
        "generated_at_utc": _now_utc(),
        "hostname": platform.node(),
        "evidence_dir": str(ctx.evidence_dir),
        "options": {
            "full": ctx.full,
            "keep_going": ctx.keep_going,
            "record_target": str(ctx.record_target),
            "take_minutes": ctx.take_minutes,
            "firmware_attested": ctx.firmware_attested,
        },
        "phases": phases,
        "all_green": all_green,
        "evidence_for": (
            "READY_FOR_STATIONARY_STAGE0" if all_green and not degradations else None
        ),
        "evidence_for_with_degradations": (
            "READY_FOR_STATIONARY_STAGE0" if all_green and degradations else None
        ),
        "blockers": blockers,
        "degradations": degradations,
        "refusals": refusals,
        "authority": (
            "This file is EVIDENCE, not the verdict. Exactly one readiness decision "
            "(READY_FOR_STATIONARY_STAGE0 / DEGRADE_MMP_ONLY / NOT_READY) is recorded at "
            "close by AU-F/Fable, per REVISED_BOARD.md. A green bundle is evidence FOR the "
            "first; it does not issue it."
        ),
        "does_not_prove": [
            ("This harness has never run on a real Orin. A green bundle from any other "
            "machine proves the orchestration and the refusal paths, not the hardware."),
            ("No phase here powers, commands or touches the dog. Nothing in this bundle is "
            "evidence about the robot's own topics, its firmware, or its behaviour."),
            ("P4's frame counts are a bench measurement with the camera on a desk; they are "
            "not evidence about the camera bolted to a walking robot."),
            ("P2's sustained-write figure describes the path it was pointed at for the size "
            "it was given. A short sample does not exhaust an SLC cache and cannot disprove "
            "the knee it exists to find."),
            ("A firmware attestation is an operator declaration read from the vendor app, "
            "not a measurement this harness made."),
        ],
        "bundle_sha256": bundle,
    }


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


# ---------------------------------------------------------------------------
# The generated runbook — one source of operator-command truth
# ---------------------------------------------------------------------------

RUNBOOK_RELATIVE_PATH = "scrum/20260814/task_1/ORIN_RUNBOOK.md"


def runbook_path(root: Path | str | None = None) -> Path:
    return Path(root or _REPO_ROOT) / RUNBOOK_RELATIVE_PATH


def render_runbook() -> str:
    """Render ``ORIN_RUNBOOK.md`` from this module's own phase table.

    Working agreement 7 generalised: an operator-facing document that lists the
    phases, the one command and the flags must not be a second, hand-maintained
    copy of them. Every phase row below is read out of :data:`PHASES`, and the
    committed document is pinned byte-for-byte by ``tests/test_orin_rehearsal.py``.
    """

    lines: list[str] = [
        "# ORIN_RUNBOOK — the one command, and what it proves",
        "",
        "> ## GENERATED FILE — do not hand-edit",
        ">",
        ("> Rendered by `scripts/parcel_capture/orin_rehearsal.py::render_runbook()` from"
        " the harness's own phase table."),
        ("> Hand-editing is a defect: `tests/test_orin_rehearsal.py` reddens until it is"
        " reverted."),
        ">",
        "> ```",
        "> .parcel/bin/python -m scripts.parcel_capture.orin_rehearsal --emit-runbook",
        "> ```",
        "",
        (f"**Card:** OR-1 (board [REVISED_BOARD.md](REVISED_BOARD.md) H-2, software half)"
        f" · **Harness version:** `{HARNESS_VERSION}`"),
        "",
        "## 0 · Before anything: what this is",
        "",
        ("This harness is the **only** way our capture stack is allowed to meet the Orin"
        " for the first time. Not a shell history, not a paste from a status doc — this,"
        " because it fails closed, records raw output, and leaves an evidence bundle"
        " somebody else can audit."),
        "",
        ("It is **sensor-only**. No process it starts can command motion, in any form. It"
        " launches vendor sensor drivers and it subscribes; that is the whole of its"
        " physical authority."),
        "",
        "## 1 · Get the repository onto the Orin",
        "",
        "```bash",
        "# ON THE DEV BOX",
        "rsync -av --exclude '.parcel/' --exclude '__pycache__/' --exclude '.git/' \\",
        "  /home/jaewoo-jang/Desktop/Projects/Parcel/ <orin_user>@<orin_ip>:~/Parcel/",
        "```",
        "",
        ("`--exclude '.parcel/'` is **not optional**. That venv is an x86 3.14 venv, it is"
        " meaningless on aarch64, and its emptiness of any vendor motion SDK is the"
        " project's strongest motion guarantee. It has no business on the robot host."),
        "",
        ("**No vendor SDK is ever installed into any Parcel venv.** `pyrealsense2`,"
        " `unilidar_sdk2` and the ROS driver packages are installed on the Orin, into the"
        " system or a venv **on the Orin**, exactly as the no-dog checklist says."),
        "",
        "## 2 · The one command",
        "",
        "```bash",
        "# ON THE ORIN, from ~/Parcel",
        "source /opt/ros/<the distro P0 reports>/setup.bash    # if there is one",
        "python3 -m scripts.parcel_capture.orin_rehearsal \\",
        "  --evidence-dir ~/orin_evidence \\",
        "  --record-target /data                              # the REAL record destination",
        "```",
        "",
        ("`$HOME` must be WRITABLE for the user running this. `ros2 bag record` opens"
        " its log under `$HOME/.ros/log` before it records a byte, and on a read-only"
        " home it exits with `Failed opening file … Read-only file system` and P5 reads"
        " *the recorder wrote nothing*. Measured, not assumed: that is exactly how P5"
        " fails inside the repository's read-only ROS 2 sandbox until `HOME` is pointed"
        " at the writable bind."),
        "",
        "Useful flags, and none of them is required:",
        "",
        "| Flag | What it changes |",
        "|---|---|",
        (f"| `--full` | The long forms: a {FULL_SMOKE_SECONDS}s frame count instead of"
        f" {SMOKE_SECONDS}s, {FULL_WRITE_SAMPLE_BYTES // GIB} GiB written instead of"
        f" {WRITE_SAMPLE_BYTES // GIB} GiB, {FULL_BENCH_RECORD_SECONDS}s recorded instead"
        f" of {BENCH_RECORD_SECONDS}s. Use it once the short form is green. |"),
        ("| `--until PHASE` | Stop after PHASE. Later phases are written as `SKIPPED`."
        " It does **not** make PHASE run: if an earlier phase FAILs, PHASE is `SKIPPED`"
        " too, so pair it with `--keep-going` when you want the named phase to run"
        " regardless. |"),
        ("| `--keep-going` | Run later phases even after a failure. A security refusal is"
        " never overridden by it. |"),
        ("| `--firmware-attested V1.1.13` | The version **read from the Unitree app**."
        " Required before anything may be on the robot LAN. |"),
        ("| `--take-minutes N` | The take length the free-space requirement is computed"
        " for (default 20). |"),
        "",
        "## 3 · What each phase proves",
        "",
        "| Phase | Proves | Fails when |",
        "|---|---|---|",
    ]
    proofs: Mapping[str, tuple[str, str]] = {
        "p0_identity": (
            "what this machine is, and which ROS distro the recorder argv must target",
            "not one identity command could be run at all",
        ),
        "p1_environment": (
            ("the USB buffer is not the 16 MB default, `import parcel_robot.capture` runs"
            " under 3.10 for the first time ever, and every required package is installed"),
            "any required item is ABSENT, or `usbfs_memory_mb` is 16",
        ),
        "p2_storage": (
            ("the record target sustains the plan's byte rate, measured as a tail, and has"
            " the free space the generated budget requires"),
            ("the tail is below the requirement, free space is short, or nothing could be"
            " measured at all"),
        ),
        "p3_network": (
            ("which interfaces exist, that the host is not on the robot LAN, and that the"
            " firmware pin is honoured"),
            ("the host is on `192.168.123.0/24` without an attestation at or above"
            f" V{FIRMWARE_PIN_TEXT}, or the attestation is below it or malformed"),
        ),
        "p4_sensors": (
            ("that every CONFIGURED stream — colour, depth, both IR and the IMU —"
            " delivers what its configured rate says it should; and whether the L2"
            " reads on a bench"),
            ("the camera does not enumerate, a configured stream delivers ZERO frames"
            " (including all of them: a total loss is named as one), or a stream"
            f" delivers under {int(STREAM_POOR_FRACTION * 100)}% of expectation"),
        ),
        "p5_recorder": (
            ("the whole recorder path: installed `--help` -> argv rendered by"
            " `Rosbag2Plan` -> a real timed recording -> read back by our own reader ->"
            " sidecar built and verified -> preflight run"),
            ("the argv carries a flag the installed recorder lacks, the bag is"
            " unreadable, the sidecar does not verify, or the support-topic"
            " reconciliation could not run at all"),
        ),
    }
    for phase_id, purpose in PHASES:
        proves, fails = proofs[phase_id]
        lines.append(f"| `{phase_id}` | {proves} | {fails} |")
    lines += [
        "",
        ("Every phase writes `<evidence-dir>/<phase>.json` with the **raw stdout and"
        " stderr of every command it ran**, a `PASS`/`FAIL`/`SKIPPED` verdict, and a"
        " remedy on failure. A failed phase stops the ones after it unless"
        " `--keep-going` is passed."),
        "",
        "## 4 · STOP rules",
        "",
        "These are stops, not suggestions.",
        "",
        (f"1. **Firmware below V{FIRMWARE_PIN_TEXT}, or unknown.** Nothing joins"
        f" `{ROBOT_LAN_PREFIX}0/24`. Unknown is treated as below the pin. The harness"
        f" refuses, and `--keep-going` does not override it: the pin is a security"
        f" control ({FIRMWARE_CVE_CLASS}), not a preference."),
        ("2. **The Orin does not come back from a reboot.** There is no second dock and no"
        " golden image. Attach the console, restore the `extlinux.conf` backup, and wake"
        " the owner regardless of whether recovery works."),
        ("3. **P0 reports a distro that is not Humble or Jazzy.** Not a failure — a"
        " report. Do not improvise an upgrade of the only dock. The recorder retargets;"
        " that is our software problem."),
        ("4. **A stream delivers under"
        f" {int(STREAM_POOR_FRACTION * 100)}%, or a configured stream delivers"
        " nothing.** Walk the drop ladder and re-run the count at each rung. Whatever"
        " profile holds is the session's profile. Zero frames on a configured stream is"
        " a LOST stream, never an unscored one: P4 names it and fails."),
        ("5. **The recorder splits, or `messages_lost` is non-zero.** Do not carry a"
        " recorder that drops the camera into a session."),
        ("6. **Anything wants to be fixed by flashing, `apt upgrade`, or editing the"
        " bootloader beyond the one documented `usbfs` argument.** Stop. The two-dock"
        " rule is unmet; the only dock is not sacrificial."),
        "",
        "## 5 · What to bring back",
        "",
        ("The whole evidence directory. It is small, it is JSON, and it is the day's"
        " primary artifact:"),
        "",
        "```bash",
        "# ON THE DEV BOX",
        "rsync -av <orin_user>@<orin_ip>:~/orin_evidence/ ./orin_evidence/",
        "```",
        "",
        "| File | Contents |",
        "|---|---|",
    ]
    for phase_id, purpose in PHASES:
        lines.append(f"| `{phase_id}.json` | {purpose} Raw command output included. |")
    lines += [
        ("| `verdict.json` | Every phase's verdict, the blockers, the degradations, and a"
        " `does_not_prove` list. |"),
        ("| `bench_storage_config.yaml`, `bench_bag.parcel-bag.json` | The exact storage"
        " config P5 passed, and the sidecar it built, if P5 got that far. |"),
        "",
        ("The **bench bag itself stays on the record target**, at"
        " `<record-target>/parcel_rehearsal_bench_bag/` — that is deliberate. P2 measured"
        " the sustained write of the record destination, and rehearsing the recorder onto"
        " a different volume measures a different disk. With `--full` and real camera"
        " topics that bag is gibibytes; do not copy it home. `p5_recorder.json` carries"
        " its path, its per-file sha256 and its message counts."),
        "",
        ("`p0_identity.json` carries a `run_header_markdown` field: that block is the"
        " day's first recorded evidence and pastes straight into the run sheet's run"
        " header."),
        "",
        "## 6 · What a green bundle does NOT prove",
        "",
        ("- It does not issue the readiness verdict. `READY_FOR_STATIONARY_STAGE0` /"
        " `DEGRADE_MMP_ONLY` / `NOT_READY` is recorded once, at close, by AU-F. A green"
        " bundle is evidence **for** the first; it is not the first."),
        ("- It says nothing about the dog: no phase powers it, commands it, or reads its"
        " topics."),
        "- It says nothing about SLAM, camera-LiDAR fusion, or owner tracking.",
        "- A bench frame count is a camera on a desk, not a camera on a walking robot.",
        "",
    ]
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python3 -m scripts.parcel_capture.orin_rehearsal",
        description=(
            "The no-dog Orin rehearsal: identity, environment, storage, network, sensors "
            "and the recorder, in order, fail-closed, into a machine-readable evidence "
            "bundle. Sensor-only; nothing here commands motion."
        ),
    )
    parser.add_argument(
        "--evidence-dir",
        type=Path,
        help="where the evidence bundle is written (created if absent)",
    )
    parser.add_argument(
        "--record-target",
        type=Path,
        default=None,
        help=(
            "the real recording destination, measured by P2 and used by P5. Defaults to "
            "the evidence directory, and P2 says so when it does."
        ),
    )
    parser.add_argument("--until", choices=PHASE_IDS, help="stop after this phase")
    parser.add_argument(
        "--full",
        action="store_true",
        help="the long forms of every measurement (10-minute frame count, 40 GiB write)",
    )
    parser.add_argument(
        "--keep-going",
        action="store_true",
        help="run later phases after a failure (never overrides a security refusal)",
    )
    parser.add_argument(
        "--firmware-attested",
        metavar="VERSION",
        help=(
            f"the Go2 firmware version read from the Unitree app. Required at or above "
            f"V{FIRMWARE_PIN_TEXT} before anything may be on the robot LAN."
        ),
    )
    parser.add_argument(
        "--take-minutes",
        type=float,
        default=20.0,
        help="take length the free-space requirement is computed for (default 20)",
    )
    parser.add_argument(
        "--emit-runbook",
        nargs="?",
        const="",
        metavar="PATH",
        help="write the generated ORIN_RUNBOOK.md and exit (default: its committed path)",
    )
    parser.add_argument(
        "--check-runbook",
        action="store_true",
        help="exit non-zero if the committed runbook differs from the generator",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.emit_runbook is not None:
        target = Path(args.emit_runbook) if args.emit_runbook else runbook_path()
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(render_runbook(), encoding="utf-8")
        print(f"wrote {target}")
        return 0
    if args.check_runbook:
        target = runbook_path()
        if not target.is_file():
            print(f"REFUSED: {target} does not exist; run --emit-runbook")
            return 2
        if target.read_text(encoding="utf-8") != render_runbook():
            print(f"REFUSED: {target} has drifted from render_runbook(); run --emit-runbook")
            return 2
        print(f"{target} matches the generator")
        return 0

    if args.evidence_dir is None:
        parser.error("--evidence-dir is required (or use --emit-runbook / --check-runbook)")

    evidence_dir = Path(args.evidence_dir).expanduser().resolve()
    record_target = (
        Path(args.record_target).expanduser().resolve()
        if args.record_target is not None
        else evidence_dir
    )
    try:
        evidence_dir.mkdir(parents=True, exist_ok=True)
    except OSError as problem:
        print(f"REFUSED: cannot create the evidence directory {evidence_dir}: {problem}")
        return 3

    if args.firmware_attested is not None:
        try:
            parse_firmware_version(args.firmware_attested)
        except RehearsalRefused as refusal:
            print(f"REFUSED: {refusal}")
            return 2

    ctx = Context(
        evidence_dir=evidence_dir,
        record_target=record_target,
        runner=run_command,
        full=bool(args.full),
        keep_going=bool(args.keep_going),
        firmware_attested=args.firmware_attested,
        take_minutes=float(args.take_minutes),
    )
    if args.record_target is None:
        print(
            f"NOTE: --record-target was not given, so P2 and P5 measure {record_target} "
            f"(the evidence directory). Pass the real destination for a real measurement.",
            flush=True,
        )

    try:
        verdict = run_rehearsal(ctx, until=args.until)
    # Blind on purpose, and this one is the whole fail-closed promise: an operator
    # standing at a bench gets a sentence and an evidence directory, never a
    # traceback. A defect in this harness must not read as a verdict about the Orin.
    except Exception as problem:  # noqa: BLE001
        print(f"HARNESS ERROR ({type(problem).__name__}): {problem}")
        print(
            "This is a defect in the harness, not a verdict about the machine. Report it "
            "with the evidence written so far: " + str(evidence_dir)
        )
        return 3

    print()
    print(f"evidence bundle: {evidence_dir}")
    for phase_id, value in verdict["phases"].items():
        print(f"  {phase_id:<14} {value}")
    for line in verdict["blockers"]:
        print(f"  BLOCKER  {line}")
    for line in verdict["degradations"]:
        print(f"  DEGRADED {line}")
    if verdict["all_green"]:
        print(
            "RESULT: all phases green — evidence FOR READY_FOR_STATIONARY_STAGE0. "
            "The verdict itself is AU-F/Fable's to record."
        )
        return 0
    hard = any(
        report.hard_stop for report in ctx.reports.values() if report.verdict is Verdict.FAIL
    )
    print(
        f"RESULT: NOT green — {len(verdict['blockers'])} blocker(s). This bundle is "
        f"evidence for a named blocker, not for readiness."
    )
    return 2 if hard else 1


if __name__ == "__main__":  # pragma: no cover - CLI entry
    raise SystemExit(main())
