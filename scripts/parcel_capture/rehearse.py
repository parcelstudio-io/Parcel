"""Synthetic-publisher rehearsal: the whole capture stack, with no hardware.

Card PS-E of tranche PS-1 (``scrum/20260813/task_1/README.md``). One sentence
governs this file:

    **The first time this stack runs must not be on the dog.**

So it drives the *real* PS-A/B/C/D modules — PS-A's ``ChannelSequenceBook`` and
matrix, PS-B's ``CaptureRecorder``/``build_sidecar``, PS-C's ``build_clock_map``,
PS-D's ``run_preflight``/``attest``, and PS-E's own ``budget`` — from synthetic
publishers on a box with no ROS, no vendor SDK, no camera and no robot. Nothing
here re-implements any of them. If they do not compose, this file is where that
shows up, and ``PSE_STATUS.md`` reports it rather than working around it.

What a rehearsal has to prove
-----------------------------
Not that the happy path works. That a **fault is named correctly**, because on
session morning the only thing anyone will have is the sidecar, and a sidecar
that calls a sensor dropout a truncation sends the operator to debug the wrong
half of the rig. :func:`classify` therefore derives each verdict from evidence
that the other verdicts cannot produce:

* ``BACKPRESSURE_LOSS`` — an **interior** hole in one channel's number line.
* ``SENSOR_SILENCE`` — a rate deficit **plus** a silence many nominal periods
  long.
* ``RATE_DEGRADATION`` — a rate deficit with **no** long silence.
* ``CLOCK_STEP`` — a discontinuity in PS-C's segmented fit.
* ``PROCESS_KILL`` — no ``DataEnd``, no ``Footer``, no terminal magic, and no
  latch recorded anywhere.
* ``WRITE_EXHAUSTION`` — a latch, from the bag's close record if the recorder
  managed to write one and from the summary beside the bag if it did not.

:func:`check_expectations` then asserts both directions: every seeded fault is
detected, and **no unseeded fault is**. The second half is the one that catches
a drop being reported as a truncation.

Two honest limits, both encoded rather than papered over
--------------------------------------------------------
**A truncation does not name its cause.** A SIGKILL and a volume that filled up
produce the same bytes: no footer, no close record. The recorder's latch dies
with the process, so :attr:`FaultKind.WRITE_EXHAUSTION` is detectable only from
an artifact written *outside* the bag — which is why :func:`record_take` writes
``<bag>.recorder-summary.json`` the instant the recorder closes, and why
:class:`Classification` carries the ``source`` of every verdict.

**A stopped channel and a slowed channel deliver the same count.** Fifty per
cent of nominal and silence for half the session are the same number of
messages. Only the inter-message gap separates them, and the sidecar does not
carry gaps — so :func:`channel_gaps` computes them here from the bag's own
host-monotonic stamps and :func:`classify` refuses to choose between the two
verdicts when they are not supplied.
"""

from __future__ import annotations

import argparse
import errno
import itertools
import json
import math
import os
import platform
import random
import resource
import signal
import subprocess
import sys
import time
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

# Absolute imports plus this bootstrap, following attest.py's pattern: the same
# file has to work as `python -m scripts.parcel_capture.<mod>` in this venv and
# as `python3 scripts/parcel_capture/<mod>.py` from a bare checkout on the Orin,
# where `parcel_robot` is not installed and relative imports have no package to
# resolve against.
_REPO_ROOT = Path(__file__).resolve().parents[2]
for _entry in (str(_REPO_ROOT), str(_REPO_ROOT / "src")):
    if _entry not in sys.path:
        sys.path.insert(0, _entry)

from parcel_robot.capture import (  # after the deploy-path bootstrap above
    CHANNELS_BY_ID,
    Channel,
    ChannelHealth,
    RateKind,
    SourceDevice,
    channel,
)
from parcel_robot.evidence_origin import EvidenceOrigin
from scripts.parcel_capture.attest import HardwareAttestationV1, attest
from scripts.parcel_capture.budget import (
    GIB,
    MIB,
    Budget,
    BudgetRefusedError,
    D455Profile,
    build_budget,
    parse_profile,
)
from scripts.parcel_capture.clockmap import (
    ClockMapV1,
    build_clock_map,
    clock_map_digest,
    planned_elapsed_ns,
    sidecar_clock_block,
    synthesize_samples,
)
from scripts.parcel_capture.preflight import (
    OperatorObservation,
    PreflightReport,
    SampleReceipt,
    run_preflight,
)
from scripts.parcel_capture.record import (
    CaptureRecorder,
    RecorderLatchedError,
    RecorderSummary,
    SpaceBudget,
    read_mcap,
)
from scripts.parcel_capture.sidecar import (
    SIDECAR_EXTRA_KEY,
    finalize,
    sidecar_digest,
    verify_sidecar,
)

#: Every rehearsal artifact carries this prefix in its session label. A bag,
#: a clock map and an attestation from this module must be impossible to
#: mistake for a session's six months from now, and PS-A enforces the same
#: property structurally on the envelope (``SYNTHETIC_ORIGINS`` require a
#: ``fixture_label``). The prefix is the human-readable half of that.
REHEARSAL_PREFIX = "REHEARSAL-SYNTHETIC"

#: What every synthetic receipt says about itself, so the string survives into
#: PS-D's ``evidence`` field and into the attestation JSON.
FIXTURE_MARKER = "SYNTHETIC REHEARSAL FIXTURE - no sensor was involved"

#: A channel is judged *stalled* rather than *slow* when its longest silence
#: exceeds this many nominal periods. Same constant PS-D's preflight uses for
#: its own stall detector (``preflight.MAX_GAP_PERIODS``), mirrored here rather
#: than imported so a change to either side reddens
#: ``test_the_stall_threshold_matches_preflights``.
STALL_GAP_PERIODS = 5.0

#: Default scale applied to every payload. A 300 GiB/hour profile cannot be
#: rehearsed at full size in a test suite, so payloads are shrunk by this factor
#: and the factor is written into the sidecar's session notes. It changes how
#: many bytes move, never how many messages, which sequence numbers they carry,
#: or how anything is classified.
DEFAULT_PAYLOAD_SCALE = 1.0 / 4096.0

#: Floor on the clock-map window. PS-C's schedule needs two 10-second bursts
#: and a 300-second span before a fit is certifiable (``clockmap.MIN_SPAN_NS``),
#: and refuses to plan a schedule below the burst floor at all. A 20-second take
#: therefore cannot own a clock map; it inherits the session's.
MIN_CLOCK_SPAN_S = 900.0

#: Firmware the rehearsal's fake robot reports. At or above the ADR-0002 pin, so
#: the rehearsal exercises the GO_RECORD path; PS-D's own suite owns the
#: below-pin refusal.
REHEARSAL_FIRMWARE = "1.1.13"


class RehearsalError(RuntimeError):
    """Base for every refusal raised by this module."""


class RehearsalRefusedError(RehearsalError):
    """A rehearsal that cannot be run honestly is not run at all."""


class FaultKind(str, Enum):
    """The fault classes a rehearsal can seed and a sidecar must name apart."""

    #: A sensor stops publishing part-way through the take. Nothing is lost
    #: between receipt and record; the messages never arrive.
    SENSOR_SILENCE = "sensor_silence"
    #: A sensor publishes throughout, at a fraction of its nominal rate.
    RATE_DEGRADATION = "rate_degradation"
    #: Messages arrive and the recorder cannot write them. PS-A's sequence is
    #: minted at receipt, so this leaves an interior hole naming the channel.
    BACKPRESSURE_LOSS = "backpressure_loss"
    #: A device clock jumps mid-session.
    CLOCK_STEP = "clock_step"
    #: The volume runs out under the recorder.
    WRITE_EXHAUSTION = "write_exhaustion"
    #: The recorder process is killed mid-write.
    PROCESS_KILL = "process_kill"

    @property
    def is_bag_terminating(self) -> bool:
        """Ends the recording, rather than degrading one channel of it."""

        return self in (FaultKind.WRITE_EXHAUSTION, FaultKind.PROCESS_KILL)


class Verdict(str, Enum):
    """What the artifacts say about one fault class."""

    DETECTED = "detected"
    ABSENT = "absent"
    #: The evidence needed to rule on this class was not supplied. Fail closed:
    #: this is not ``ABSENT`` and it is certainly not a pass.
    UNRESOLVED = "unresolved"


@dataclass(frozen=True)
class Fault:
    """One seeded fault, with everything needed to reproduce it exactly."""

    kind: FaultKind
    channel_id: str | None = None
    #: Where in the take it starts, as a fraction of the duration.
    at_fraction: float = 0.5
    #: Surviving share of nominal, for :attr:`FaultKind.RATE_DEGRADATION`.
    keep_fraction: float = 0.9
    #: Step size for :attr:`FaultKind.CLOCK_STEP`.
    magnitude_ns: int = 500_000_000
    #: Which device's clock steps.
    device: SourceDevice = SourceDevice.GO2

    def __post_init__(self) -> None:
        if not isinstance(self.kind, FaultKind):
            raise RehearsalRefusedError(f"fault kind must be a FaultKind, got {self.kind!r}")
        needs_channel = self.kind in (
            FaultKind.SENSOR_SILENCE,
            FaultKind.RATE_DEGRADATION,
            FaultKind.BACKPRESSURE_LOSS,
        )
        if needs_channel:
            if self.channel_id is None:
                raise RehearsalRefusedError(
                    f"{self.kind.value} must name the channel it happens to — a fault "
                    f"nobody can attribute is exactly the defect this tranche exists to fix"
                )
            channel(self.channel_id)  # unknown id is PS-A's refusal
        elif self.channel_id is not None:
            raise RehearsalRefusedError(
                f"{self.kind.value} is not a per-channel fault; drop channel_id"
            )
        for name in ("at_fraction", "keep_fraction"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise RehearsalRefusedError(f"{name} must be a number, got {value!r}")
            if not math.isfinite(value) or not 0.0 < float(value) <= 1.0:
                raise RehearsalRefusedError(f"{name} must be in (0, 1], got {value!r}")
        if isinstance(self.magnitude_ns, bool) or not isinstance(self.magnitude_ns, int):
            raise RehearsalRefusedError(f"magnitude_ns must be an int, got {self.magnitude_ns!r}")
        if not isinstance(self.device, SourceDevice):
            raise RehearsalRefusedError(f"device must be a SourceDevice, got {self.device!r}")

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind.value,
            "channel_id": self.channel_id,
            "at_fraction": self.at_fraction,
            "keep_fraction": self.keep_fraction,
            "magnitude_ns": self.magnitude_ns,
            "device": self.device.value,
        }

    @classmethod
    def from_dict(cls, record: Mapping[str, Any]) -> Fault:
        try:
            return cls(
                kind=FaultKind(record["kind"]),
                channel_id=record.get("channel_id"),
                at_fraction=float(record.get("at_fraction", 0.5)),
                keep_fraction=float(record.get("keep_fraction", 0.9)),
                magnitude_ns=int(record.get("magnitude_ns", 500_000_000)),
                device=SourceDevice(record.get("device", SourceDevice.GO2.value)),
            )
        except (KeyError, TypeError, ValueError) as error:
            raise RehearsalRefusedError(f"malformed fault record {record!r}: {error}") from error


@dataclass(frozen=True)
class RehearsalPlan:
    """What to rehearse. Deterministic: same plan, same bytes."""

    session_label: str
    profile: D455Profile
    duration_s: float = 20.0
    payload_scale: float = DEFAULT_PAYLOAD_SCALE
    faults: tuple[Fault, ...] = ()
    seed: int = 20260813
    #: Channels to publish. Defaults to every matrix channel the budget models.
    channels: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.session_label.startswith(REHEARSAL_PREFIX):
            raise RehearsalRefusedError(
                f"a rehearsal session label must start with {REHEARSAL_PREFIX!r}; got "
                f"{self.session_label!r}. Every artifact this module writes has to be "
                f"unmistakable for a session artifact, and the label is the half a human "
                f"reads."
            )
        if not isinstance(self.profile, D455Profile):
            raise RehearsalRefusedError(f"profile must be a D455Profile, got {self.profile!r}")
        for name, bound in (("duration_s", None), ("payload_scale", 1.0)):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise RehearsalRefusedError(f"{name} must be a number, got {value!r}")
            if not math.isfinite(value) or value <= 0.0:
                raise RehearsalRefusedError(f"{name} must be finite and positive, got {value!r}")
            if bound is not None and value > bound:
                raise RehearsalRefusedError(f"{name} must be <= {bound}, got {value!r}")
        seeded = [fault.kind for fault in self.faults]
        if len(set(seeded)) != len(seeded):
            raise RehearsalRefusedError(
                f"one fault of each kind per rehearsal; got {sorted(k.value for k in seeded)}. "
                f"Two faults of a kind make the classification ambiguous and the point of "
                f"this module is that classifications are not ambiguous."
            )
        if sum(1 for kind in seeded if kind.is_bag_terminating) > 1:
            raise RehearsalRefusedError(
                "a take can only end once; seed at most one bag-terminating fault"
            )

    @property
    def duration_ns(self) -> int:
        return int(self.duration_s * 1_000_000_000)

    @property
    def clock_span_s(self) -> float:
        """Window the clock prober covers, which is the SESSION, not the take.

        PS-C refuses to plan a schedule under two burst windows and will not
        certify a fit under ``clockmap.MIN_SPAN_NS`` (300 s), so a short take
        borrows the surrounding session's map. :data:`MIN_CLOCK_SPAN_S` is the
        floor this module applies.
        """

        return max(self.duration_s, MIN_CLOCK_SPAN_S)

    @property
    def clock_span_ns(self) -> int:
        return int(self.clock_span_s * 1_000_000_000)

    def fault(self, kind: FaultKind) -> Fault | None:
        for item in self.faults:
            if item.kind is kind:
                return item
        return None

    def seeded_kinds(self) -> frozenset[FaultKind]:
        return frozenset(item.kind for item in self.faults)

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_label": self.session_label,
            "profile": (
                f"{self.profile.width}x{self.profile.height}@{self.profile.fps}:"
                + "".join(
                    flag
                    for flag, on in (
                        ("C", self.profile.color),
                        ("D", self.profile.depth),
                        ("I", self.profile.infrared),
                    )
                    if on
                )
            ),
            "duration_s": self.duration_s,
            "payload_scale": self.payload_scale,
            "faults": [fault.to_dict() for fault in self.faults],
            "seed": self.seed,
            "channels": list(self.channels),
        }

    @classmethod
    def from_dict(cls, record: Mapping[str, Any]) -> RehearsalPlan:
        try:
            return cls(
                session_label=str(record["session_label"]),
                profile=parse_profile(str(record["profile"])),
                duration_s=float(record["duration_s"]),
                payload_scale=float(record["payload_scale"]),
                faults=tuple(Fault.from_dict(item) for item in record.get("faults", ())),
                seed=int(record.get("seed", 20260813)),
                channels=tuple(str(item) for item in record.get("channels", ())),
            )
        except (KeyError, TypeError, ValueError, BudgetRefusedError) as error:
            raise RehearsalRefusedError(f"malformed rehearsal plan: {error}") from error


# ---------------------------------------------------------------------------
# The synthetic publishers
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SyntheticMessage:
    """One message a synthetic publisher offers to the recorder."""

    channel_id: str
    elapsed_ns: int
    payload: bytes
    source_timestamp_ns: int


def plan_budget(plan: RehearsalPlan) -> Budget:
    """The PS-E budget this plan publishes against. One source of rates."""

    return build_budget(plan.profile, session_duration_s=plan.duration_s)


def _payload_blocks(plan: RehearsalPlan, budget: Budget) -> dict[str, bytes]:
    """One deterministic block per channel, generated once.

    Generated up front so a throughput measurement times the capture stack and
    not this module's random number generator.
    """

    rng = random.Random(plan.seed)
    blocks: dict[str, bytes] = {}
    for row in budget.rows:
        size = max(1, int(row.payload_bytes_per_message * plan.payload_scale))
        blocks[row.channel_id] = bytes(rng.randrange(256) for _ in range(min(size, 4096))) * (
            1 + size // 4096
        )
        blocks[row.channel_id] = blocks[row.channel_id][:size]
    return blocks


def timetable(plan: RehearsalPlan, budget: Budget | None = None) -> Iterator[SyntheticMessage]:
    """Every message every synthetic publisher offers, in receipt order.

    Publisher-side faults live here, because that is where they live in
    reality: a sensor that stops or slows never reaches the recorder at all,
    and so leaves **no hole** in a number line minted at receipt. That is the
    whole reason :attr:`FaultKind.SENSOR_SILENCE` and
    :attr:`FaultKind.BACKPRESSURE_LOSS` are different findings.
    """

    budget = budget or plan_budget(plan)
    blocks = _payload_blocks(plan, budget)
    wanted = frozenset(plan.channels) if plan.channels else None
    duration_ns = plan.duration_ns

    silence = plan.fault(FaultKind.SENSOR_SILENCE)
    degrade = plan.fault(FaultKind.RATE_DEGRADATION)

    offered: list[SyntheticMessage] = []
    for row in budget.rows:
        if wanted is not None and row.channel_id not in wanted:
            continue
        period_ns = 1_000_000_000.0 / row.messages_per_second
        count = int(duration_ns / period_ns)
        keep_every: float | None = None
        if degrade is not None and degrade.channel_id == row.channel_id:
            keep_every = degrade.keep_fraction
        stop_at: int | None = None
        if silence is not None and silence.channel_id == row.channel_id:
            stop_at = int(duration_ns * silence.at_fraction)
        for index in range(count):
            elapsed = int(index * period_ns)
            if stop_at is not None and elapsed >= stop_at:
                break
            if keep_every is not None and math.floor((index + 1) * keep_every) == math.floor(
                index * keep_every
            ):
                # Uniform thinning: exactly keep_fraction of the messages
                # survive, spread evenly, so the gap never grows long enough to
                # look like a stall. That separation is the point.
                continue
            offered.append(
                SyntheticMessage(
                    channel_id=row.channel_id,
                    elapsed_ns=elapsed,
                    payload=blocks[row.channel_id],
                    # A synthetic device clock: the host instant plus a fixed
                    # per-device offset, so source and host stamps are never
                    # accidentally equal and a consumer that confuses them
                    # produces a visibly wrong number.
                    source_timestamp_ns=elapsed + _device_offset_ns(row.channel_id),
                )
            )
    offered.sort(key=lambda message: (message.elapsed_ns, message.channel_id))
    yield from offered


def _device_offset_ns(channel_id: str) -> int:
    """A stable, distinct fake epoch per device. Not a measurement."""

    device = CHANNELS_BY_ID[channel_id].device
    return 1_000_000_000 * (1 + sorted(SourceDevice).index(device))


# ---------------------------------------------------------------------------
# Driving PS-D from the same publishers
# ---------------------------------------------------------------------------


def rehearsal_reader_factory(plan: RehearsalPlan, budget: Budget | None = None) -> Any:
    """A PS-D ``ChannelReaderFactory`` backed by this plan's load model.

    Every receipt says :data:`FIXTURE_MARKER` in its ``detail``, which PS-D
    copies into ``ChannelProbe.evidence`` and from there into the attestation
    JSON. **That string is the only marker an attestation carries.** PS-D
    derives ``EvidenceOrigin.PHYSICAL`` from ``messages_received >= 1`` alone,
    with no notion of a synthetic reader, so an attestation built from this
    factory claims PHYSICAL for channels no sensor produced. Recorded as a
    finding in ``PSE_STATUS.md``; the fix is PS-D's, and until it lands this
    module never writes an attestation outside its own rehearsal directory.
    """

    budget = budget or plan_budget(plan)
    rates = {row.channel_id: row.messages_per_second for row in budget.rows}
    sizes = {
        row.channel_id: max(1, int(row.payload_bytes_per_message * plan.payload_scale))
        for row in budget.rows
    }

    def factory(_entry: Channel) -> Any:
        def reader(target: Channel, window_s: float) -> Iterator[SampleReceipt]:
            rate = rates.get(target.channel_id)
            if rate is None:
                # A channel the budget does not model publishes nothing here,
                # and PS-D will rule it ABSENT with a reason. Fail closed.
                return
            start = time.monotonic_ns()
            period_ns = int(1_000_000_000 / rate)
            for index in range(max(1, round(rate * window_s))):
                yield SampleReceipt(
                    channel_id=target.channel_id,
                    host_monotonic_ns=start + index * period_ns,
                    payload_bytes=sizes[target.channel_id],
                    source_timestamp_ns=start
                    + index * period_ns
                    + _device_offset_ns(target.channel_id),
                    detail=FIXTURE_MARKER,
                )

        return reader

    return factory


def configured_rates(budget: Budget) -> dict[str, float]:
    """Rates for every channel whose rate is a capture-configuration decision.

    PS-D refuses an override on an EVENT_DRIVEN channel — "a configured rate
    would turn normal silence into a fault" — so the handheld is excluded. Every
    other channel gets the rate the budget was computed at, which is what makes
    the budget an assertable expectation rather than a wish: the same number
    sizes the disk, sets the recorder's SpaceBudget, and is what PS-B's sidecar
    holds each channel to.
    """

    return {
        row.channel_id: row.messages_per_second
        for row in budget.rows
        if CHANNELS_BY_ID[row.channel_id].rate_kind is not RateKind.EVENT_DRIVEN
    }


def rehearsal_preflight(
    plan: RehearsalPlan,
    *,
    storage_path: Path | str,
    budget: Budget | None = None,
    window_s: float = 1.0,
) -> PreflightReport:
    """Run PS-D's real preflight against this plan's synthetic publishers."""

    budget = budget or plan_budget(plan)
    return run_preflight(
        reader_factory=rehearsal_reader_factory(plan, budget),
        window_s=window_s,
        configured_rates=configured_rates(budget),
        storage_path=storage_path,
        robot_reader=lambda: {
            "edition": "EDU",
            "firmware_version": REHEARSAL_FIRMWARE,
            "serial": f"{REHEARSAL_PREFIX}-GO2-SERIAL",
        },
        builtin_lidar_reader=lambda: {
            "model": "Unitree L2 (built-in)",
            "serial": f"{REHEARSAL_PREFIX}-LIDAR-SERIAL",
        },
        builtin_lidar_operator=OperatorObservation(
            value="Unitree L2 (built-in)",
            operator=f"{REHEARSAL_PREFIX} fixture ({FIXTURE_MARKER})",
            photo_id="P02",
        ),
        d455_reader=lambda: {
            "firmware_version": "5.16.0.1",
            "serial": f"{REHEARSAL_PREFIX}-D455-SERIAL",
        },
        l2_reader=lambda: {
            "firmware_version": "1.0.0",
            "serial": f"{REHEARSAL_PREFIX}-L2-SERIAL",
        },
    )


# ---------------------------------------------------------------------------
# The take
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class TakeResult:
    """What one recording run did, measured while it did it."""

    bag_path: Path
    summary: RecorderSummary | None
    messages_offered: int
    messages_recorded: int
    messages_dropped: int
    payload_bytes: int
    wall_seconds: float
    latched: bool
    summary_path: Path | None
    summary_write_error: str

    @property
    def throughput_bytes_per_second(self) -> float:
        if self.wall_seconds <= 0.0:
            return 0.0
        written = self.summary.bytes_written if self.summary is not None else self.payload_bytes
        return written / self.wall_seconds

    def to_dict(self) -> dict[str, Any]:
        return {
            "bag_path": str(self.bag_path),
            "messages_offered": self.messages_offered,
            "messages_recorded": self.messages_recorded,
            "messages_dropped": self.messages_dropped,
            "payload_bytes": self.payload_bytes,
            "wall_seconds": round(self.wall_seconds, 6),
            "throughput_mib_per_second": round(self.throughput_bytes_per_second / MIB, 3),
            "latched": self.latched,
            "summary": None if self.summary is None else self.summary.to_dict(),
            "summary_path": None if self.summary_path is None else str(self.summary_path),
            "summary_write_error": self.summary_write_error,
        }


def summary_path_for(bag_path: Path | str) -> Path:
    path = Path(bag_path)
    return path.with_name(path.name + ".recorder-summary.json")


def record_take(
    plan: RehearsalPlan,
    bag_path: Path | str,
    *,
    budget: Budget | None = None,
    kill_after_messages: int | None = None,
    start_realtime_ns: int = 1_800_000_000_000_000_000,
    start_monotonic_ns: int = 10_000_000_000,
) -> TakeResult:
    """Drive PS-B's real ``CaptureRecorder`` from the synthetic publishers.

    Clocks are *virtual*: ``host_monotonic_ns`` comes from the timetable, not
    from ``time.monotonic_ns()``. That makes a 20-minute take reproducible in
    milliseconds and makes every derived rate exact. It also means this run
    proves nothing about real-time behaviour, which is stated in
    ``PSE_STATUS.md``'s ``does_not_prove`` and is why
    :func:`measure_stack_throughput` exists separately.

    ``kill_after_messages`` exists for the SIGKILL rehearsal: the child sends
    itself a real ``SIGKILL`` from inside the record loop once it has accepted
    that many messages. Killing from inside is deterministic in a way that a
    parent racing a byte threshold is not, and the cut still lands wherever
    userspace last flushed — the recorder's buffer goes with the process.
    """

    budget = budget or plan_budget(plan)
    path = Path(bag_path)
    entries = [CHANNELS_BY_ID[row.channel_id] for row in budget.rows]
    space = SpaceBudget(**budget.space_budget_kwargs(plan.duration_s))
    scaled = SpaceBudget(
        bytes_per_second=max(space.bytes_per_second * plan.payload_scale, 1.0),
        duration_s=space.duration_s,
        margin=space.margin,
    )

    backpressure = plan.fault(FaultKind.BACKPRESSURE_LOSS)
    drop_from = (
        int(plan.duration_ns * backpressure.at_fraction) if backpressure is not None else None
    )
    drop_until = (
        int(drop_from + plan.duration_ns * 0.05) if drop_from is not None else None
    )

    recorder = CaptureRecorder(
        path,
        bag_id=plan.session_label,
        channels=entries,
        origin=EvidenceOrigin.SIMULATION,
        fixture_label=plan.session_label,
        budget=scaled,
        calibration_ref=f"{REHEARSAL_PREFIX}-uncalibrated",
        fsync_every_ns=1_000_000_000,
    )

    offered = 0
    recorded = 0
    dropped = 0
    payload_bytes = 0
    latched = False
    started = time.monotonic()
    for message in timetable(plan, budget):
        offered += 1
        host_monotonic = start_monotonic_ns + message.elapsed_ns
        host_realtime = start_realtime_ns + message.elapsed_ns
        if (
            backpressure is not None
            and message.channel_id == backpressure.channel_id
            and drop_from is not None
            and drop_until is not None
            and drop_from <= message.elapsed_ns < drop_until
        ):
            recorder.drop(
                message.channel_id,
                reason=f"{REHEARSAL_PREFIX}: seeded bounded-queue backpressure",
            )
            dropped += 1
            continue
        try:
            recorder.record(
                message.channel_id,
                message.payload,
                host_monotonic_ns=host_monotonic,
                host_realtime_ns=host_realtime,
                source_timestamp_ns=start_realtime_ns + message.source_timestamp_ns,
                health=ChannelHealth.NOMINAL,
            )
        except RecorderLatchedError:
            latched = True
            break
        recorded += 1
        payload_bytes += len(message.payload)
        if kill_after_messages is not None and recorded >= kill_after_messages:
            # A real SIGKILL to this process, from inside the record loop. The
            # bytes that survive are exactly the ones userspace had flushed,
            # which is the state a session-morning crash leaves behind.
            os.kill(os.getpid(), signal.SIGKILL)
    wall = time.monotonic() - started

    summary = recorder.close(reason="latched" if latched else "rehearsal complete")

    # The latch dies with the process and cannot be written into a bag on a
    # volume that has no room for it, so it is written beside the bag the
    # instant the recorder closes. On a genuinely full volume this write fails
    # too, and the failure is recorded rather than swallowed.
    summary_path: Path | None = summary_path_for(path)
    write_error = ""
    try:
        summary_path.write_text(
            json.dumps(summary.to_dict(), indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
    except OSError as error:
        write_error = f"{type(error).__name__}({error.errno}): {error}"
        summary_path = None

    return TakeResult(
        bag_path=path,
        summary=summary,
        messages_offered=offered,
        messages_recorded=recorded,
        messages_dropped=dropped,
        payload_bytes=payload_bytes,
        wall_seconds=wall,
        latched=latched,
        summary_path=summary_path,
        summary_write_error=write_error,
    )


# ---------------------------------------------------------------------------
# The clock half
# ---------------------------------------------------------------------------


def rehearsal_clock_map(
    plan: RehearsalPlan,
    *,
    start_monotonic_ns: int = 10_000_000_000,
    start_realtime_ns: int = 1_800_000_000_000_000_000,
    created_at_utc: str = "2026-08-13T00:00:00Z",
) -> ClockMapV1:
    """Offset triples on PS-C's own schedule, fitted by PS-C's own fitter.

    Uses ``clockmap.synthesize_samples`` rather than a fixture of this module's
    own, deliberately: a rehearsal that generates its inputs differently from
    the module under test proves something about the fixture, not the module.

    The map spans :attr:`RehearsalPlan.clock_span_s`, **not** the take. PS-C's
    schedule needs two 10-second bursts and a 300-second minimum span before it
    will certify a fit (``clockmap.MIN_SPAN_NS``), and it refuses outright below
    that — correctly, since a 20-second window cannot separate offset from
    drift. The consequence for the session is concrete and belongs on the run
    sheet: **the clock prober runs across the whole session, not once per
    take**, and short takes inherit the session's map rather than owning one.
    """

    step = plan.fault(FaultKind.CLOCK_STEP)
    span_ns = plan.clock_span_ns
    elapsed = planned_elapsed_ns(duration_ns=span_ns)
    samples = []
    for index, device in enumerate((SourceDevice.GO2, SourceDevice.D455, SourceDevice.L2)):
        stepping = step is not None and step.device is device
        samples.extend(
            synthesize_samples(
                device=device,
                start_host_ns=start_monotonic_ns,
                start_realtime_ns=start_realtime_ns,
                elapsed_ns=elapsed,
                offset_ns=_device_offset_ns_for_device(device),
                drift_ppm=40.0 + 5.0 * index,
                round_trip_ns=2_000_000,
                jitter_ns=50_000,
                step_at_elapsed_ns=(int(span_ns * step.at_fraction) if stepping else None),
                step_ns=step.magnitude_ns if stepping else 0,
                seed=plan.seed + index,
            )
        )
    return build_clock_map(
        samples,
        session_id=plan.session_label,
        created_at_utc=created_at_utc,
        host_id=f"{REHEARSAL_PREFIX}-host",
        origin=EvidenceOrigin.SIMULATION,
        fixture_label=plan.session_label,
    )


def _device_offset_ns_for_device(device: SourceDevice) -> int:
    return 1_000_000_000 * (1 + sorted(SourceDevice).index(device))


# ---------------------------------------------------------------------------
# Reading the bag back
# ---------------------------------------------------------------------------


def channel_gaps(bag_path: Path | str) -> dict[str, float]:
    """Longest silence per channel, in seconds, from the bag's own stamps.

    The sidecar does not carry this and it is the only thing that separates a
    channel that **stopped** from one that **slowed** — both deliver the same
    count and the same deficit. The information is in the bag (PS-A puts
    ``host_monotonic_ns`` on every envelope); nothing reads it. Recorded as a
    finding in ``PSE_STATUS.md``.

    The silence is bracketed by the **bag's own span**, not by the channel's
    first and last message. A channel that dies half-way through a take has no
    *interior* gap at all — its messages are evenly spaced right up to the
    moment it stops — so an interior-only measure calls it *slow* rather than
    *stopped*. The first version of this function made exactly that mistake and
    the rehearsal caught it (``PSE_STATUS.md`` seeded-failure row S7). PS-D's
    ``probe_channel`` brackets the same way, for the same reason.
    """

    scan = read_mcap(bag_path)
    stamps: dict[str, list[int]] = {}
    for message in scan.messages:
        stamps.setdefault(message.channel.channel_id, []).append(
            message.envelope.host_monotonic_ns
        )
    if not stamps:
        return {}
    session_start = min(min(values) for values in stamps.values())
    session_end = max(max(values) for values in stamps.values())
    gaps: dict[str, float] = {}
    for channel_id, values in stamps.items():
        values.sort()
        boundaries = [session_start, *values, session_end]
        widest = max(
            (later - earlier for earlier, later in itertools.pairwise(boundaries)),
            default=0,
        )
        gaps[channel_id] = max(widest, 0) / 1e9
    return gaps


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Classification:
    """What the artifacts say about one fault class, and on what evidence."""

    kind: FaultKind
    verdict: Verdict
    channel_ids: tuple[str, ...]
    evidence: tuple[str, ...]
    #: Which artifact the verdict came from: ``bag``, ``clock_map``,
    #: ``out_of_band`` (the recorder summary beside the bag), or ``none``.
    source: str

    @property
    def detected(self) -> bool:
        return self.verdict is Verdict.DETECTED

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind.value,
            "verdict": self.verdict.value,
            "channel_ids": list(self.channel_ids),
            "evidence": list(self.evidence),
            "source": self.source,
        }


def classify(
    sidecar: Mapping[str, Any],
    *,
    clock_map: ClockMapV1 | None = None,
    gaps: Mapping[str, float] | None = None,
    recorder_summary: Mapping[str, Any] | None = None,
) -> dict[FaultKind, Classification]:
    """Rule on every fault class from the artifacts alone.

    This function never sees the plan. That is deliberate and it is what makes
    :func:`check_expectations` mean something: a classifier that knew what was
    seeded could not fail to find it.
    """

    block = sidecar.get(SIDECAR_EXTRA_KEY)
    if not isinstance(block, Mapping):
        raise RehearsalRefusedError(
            f"sidecar carries no {SIDECAR_EXTRA_KEY!r} block; this is not a parcel-capture "
            f"manifest and nothing can be classified from it"
        )
    termination = block.get("termination", {})
    channels = block.get("channels", {})
    kind = termination.get("kind")

    results: dict[FaultKind, Classification] = {}

    # --- interior holes: loss between receipt and record -------------------
    holes = {
        channel_id: int(entry["sequence"]["missing_count"])
        for channel_id, entry in channels.items()
        if int(entry.get("sequence", {}).get("missing_count", 0)) > 0
    }
    results[FaultKind.BACKPRESSURE_LOSS] = Classification(
        kind=FaultKind.BACKPRESSURE_LOSS,
        verdict=Verdict.DETECTED if holes else Verdict.ABSENT,
        channel_ids=tuple(sorted(holes)),
        evidence=tuple(
            (
                f"{channel_id}: {count} interior sequence hole(s) — minted at receipt, "
                f"never written; the framing is intact, so this is loss, not truncation"
            )
            for channel_id, count in sorted(holes.items())
        )
        or ("no channel's number line has an interior hole",),
        source="bag",
    )

    # --- rate deficits: stopped vs slowed ----------------------------------
    deficits: dict[str, tuple[float, float]] = {}
    for channel_id, entry in channels.items():
        deficit = entry.get("deficit_fraction")
        expected_rate = entry.get("expected_rate_hz")
        if (
            entry.get("verdict") == "degraded"
            and isinstance(deficit, (int, float))
            and deficit > 0.0
            and isinstance(expected_rate, (int, float))
            and expected_rate > 0.0
            and int(entry.get("sequence", {}).get("missing_count", 0)) == 0
        ):
            deficits[channel_id] = (float(deficit), float(expected_rate))

    if gaps is None:
        unresolved = (
            (
                "no inter-message gap evidence was supplied. The sidecar does not carry "
                "gaps, and a channel that stopped delivers the same count as one that "
                "slowed, so these two verdicts cannot be separated from the sidecar alone."
            ),
        )
        for stall_kind in (FaultKind.SENSOR_SILENCE, FaultKind.RATE_DEGRADATION):
            results[stall_kind] = Classification(
                kind=stall_kind,
                verdict=Verdict.UNRESOLVED if deficits else Verdict.ABSENT,
                channel_ids=tuple(sorted(deficits)),
                evidence=unresolved if deficits else ("no channel shows a rate deficit",),
                source="bag",
            )
    else:
        stalled: dict[str, str] = {}
        slowed: dict[str, str] = {}
        for channel_id, (deficit, expected_rate) in sorted(deficits.items()):
            observed_gap = float(gaps.get(channel_id, 0.0))
            allowed = STALL_GAP_PERIODS / expected_rate
            note = (
                f"{channel_id}: {deficit:.1%} short of its expected count, longest silence "
                f"{observed_gap:.3f} s against {allowed:.3f} s "
                f"({STALL_GAP_PERIODS:g} nominal periods)"
            )
            if observed_gap > allowed:
                stalled[channel_id] = note + " — it STOPPED"
            else:
                slowed[channel_id] = note + " — it SLOWED, evenly"
        results[FaultKind.SENSOR_SILENCE] = Classification(
            kind=FaultKind.SENSOR_SILENCE,
            verdict=Verdict.DETECTED if stalled else Verdict.ABSENT,
            channel_ids=tuple(sorted(stalled)),
            evidence=tuple(stalled.values())
            or ("no channel is short of its count with a multi-period silence",),
            source="bag",
        )
        results[FaultKind.RATE_DEGRADATION] = Classification(
            kind=FaultKind.RATE_DEGRADATION,
            verdict=Verdict.DETECTED if slowed else Verdict.ABSENT,
            channel_ids=tuple(sorted(slowed)),
            evidence=tuple(slowed.values())
            or ("no channel is short of its count with an even delivery",),
            source="bag",
        )

    # --- the bag's ending --------------------------------------------------
    latch = _latch_from(termination, recorder_summary)
    truncated = kind == "truncated"
    results[FaultKind.WRITE_EXHAUSTION] = Classification(
        kind=FaultKind.WRITE_EXHAUSTION,
        verdict=Verdict.DETECTED if latch is not None else Verdict.ABSENT,
        channel_ids=(),
        evidence=(
            (
                f"the recorder latched under {latch[0]!r}: {latch[1]}",
                f"evidence source: {latch[2]}",
            )
            if latch is not None
            else ("no latch is recorded in the bag or in the recorder summary beside it",)
        ),
        source=latch[2] if latch is not None else "bag",
    )
    results[FaultKind.PROCESS_KILL] = Classification(
        kind=FaultKind.PROCESS_KILL,
        verdict=Verdict.DETECTED if truncated and latch is None else Verdict.ABSENT,
        channel_ids=(),
        evidence=(
            (
                f"the bag ends without its terminal structure ({termination.get('detail', '')})",
                (
                    "no latch is recorded anywhere, so the process died rather than running "
                    "out of room — this distinction is NOT recoverable from the bag alone, "
                    "only from the recorder summary written beside it"
                ),
            )
            if truncated and latch is None
            else (
                "the bag carries its DataEnd/Footer/terminal magic"
                if not truncated
                else "the bag is truncated, but a latch says why: this is write exhaustion"
            ),
        ),
        source="bag",
    )

    # --- the clocks --------------------------------------------------------
    results[FaultKind.CLOCK_STEP] = _classify_clock(clock_map)
    return results


def _latch_from(
    termination: Mapping[str, Any], recorder_summary: Mapping[str, Any] | None
) -> tuple[str, str, str] | None:
    """A latch, and where the evidence for it came from."""

    if termination.get("kind") == "latched_write_failure":
        close = termination.get("evidence", {}).get("recorder_close_record") or {}
        return (
            str(close.get("latch_reason", "unknown")),
            str(close.get("latch_detail", termination.get("detail", ""))),
            "bag",
        )
    if recorder_summary is not None and recorder_summary.get("latch_reason"):
        return (
            str(recorder_summary["latch_reason"]),
            str(recorder_summary.get("latch_detail", "")),
            "out_of_band",
        )
    return None


def _classify_clock(clock_map: ClockMapV1 | None) -> Classification:
    if clock_map is None:
        return Classification(
            kind=FaultKind.CLOCK_STEP,
            verdict=Verdict.UNRESOLVED,
            channel_ids=(),
            evidence=(
                (
                    "no clock map was supplied; without offset triples a device clock step "
                    "is permanently invisible, which is the whole of PS-C's argument"
                ),
            ),
            source="none",
        )
    steps: list[str] = []
    devices: list[str] = []
    for relation in clock_map.relations:
        for step in relation.steps:
            label = relation.device.value if relation.device is not None else "host"
            devices.append(label)
            steps.append(
                f"{label}: step of {step.magnitude_ns / 1e6:+.3f} ms at "
                f"host_monotonic {step.at_host_monotonic_ns}"
            )
    return Classification(
        kind=FaultKind.CLOCK_STEP,
        verdict=Verdict.DETECTED if steps else Verdict.ABSENT,
        channel_ids=tuple(sorted(set(devices))),
        evidence=tuple(steps)
        or ("PS-C's segmented fit found no discontinuity in any device relation",),
        source="clock_map",
    )


def check_expectations(
    plan: RehearsalPlan, classification: Mapping[FaultKind, Classification]
) -> tuple[str, ...]:
    """Both directions. Returns the violations; empty means green.

    The second loop is the one that matters: an **unseeded** fault class that
    reads DETECTED is a misclassification, and that is precisely how "a drop
    reported as a truncation" is caught.
    """

    seeded = plan.seeded_kinds()
    violations: list[str] = []
    for kind in FaultKind:
        result = classification.get(kind)
        if result is None:
            violations.append(f"{kind.value}: no classification was produced at all")
            continue
        fault = plan.fault(kind)
        if kind in seeded:
            if not result.detected:
                violations.append(
                    f"{kind.value}: SEEDED but the artifacts read {result.verdict.value} "
                    f"({'; '.join(result.evidence)})"
                )
            elif fault is not None and fault.channel_id is not None:
                if fault.channel_id not in result.channel_ids:
                    violations.append(
                        f"{kind.value}: seeded on {fault.channel_id}, attributed to "
                        f"{list(result.channel_ids)} — a fault attributed to the wrong "
                        f"channel is the defect this tranche exists to fix"
                    )
                elif len(result.channel_ids) > 1:
                    violations.append(
                        f"{kind.value}: seeded on {fault.channel_id} alone but also "
                        f"attributed to {sorted(set(result.channel_ids) - {fault.channel_id})}"
                    )
        elif result.verdict is Verdict.DETECTED:
            violations.append(
                f"{kind.value}: NOT seeded, yet the artifacts report it "
                f"({'; '.join(result.evidence)}) — a misclassification"
            )
        elif result.verdict is Verdict.UNRESOLVED:
            violations.append(
                f"{kind.value}: NOT seeded and the artifacts cannot rule it out "
                f"({'; '.join(result.evidence)})"
            )
    return tuple(violations)


# ---------------------------------------------------------------------------
# The whole rehearsal
# ---------------------------------------------------------------------------


@dataclass
class RehearsalOutcome:
    """Everything one rehearsal produced, and whether it was green."""

    plan: RehearsalPlan
    workdir: Path
    budget: Budget
    take: TakeResult | None
    preflight: PreflightReport
    attestation: HardwareAttestationV1
    clock_map: ClockMapV1
    sidecar: Mapping[str, Any]
    sidecar_path: Path
    gaps: Mapping[str, float]
    classification: Mapping[FaultKind, Classification]
    violations: tuple[str, ...]
    notes: tuple[str, ...] = ()

    @property
    def green(self) -> bool:
        return not self.violations

    def to_dict(self) -> dict[str, Any]:
        return {
            "plan": self.plan.to_dict(),
            "workdir": str(self.workdir),
            "green": self.green,
            "violations": list(self.violations),
            "notes": list(self.notes),
            "budget": {
                "profile": self.budget.profile.label,
                "mib_per_second": round(self.budget.mib_per_second, 3),
                "gib_per_hour": round(self.budget.gib_per_hour, 3),
                "required_free_gib": self.budget.required_free_gib(),
            },
            "take": None if self.take is None else self.take.to_dict(),
            "attestation": {
                "session_label": self.attestation.session_label,
                "verdict": self.attestation.verdict.value,
                "digest": self.attestation.digest(),
                "physical_channels": list(self.attestation.physical_channels),
            },
            "clock_map": {
                "digest": clock_map_digest(self.clock_map),
                "certifiable": self.clock_map.is_certifiable,
                "devices": [device.value for device in self.clock_map.devices],
            },
            "sidecar": {
                "path": str(self.sidecar_path),
                "digest": sidecar_digest(self.sidecar),
                "source": self.sidecar.get("source"),
                "hardware_claims": self.sidecar.get("hardware_claims"),
                "termination": self.sidecar[SIDECAR_EXTRA_KEY]["termination"]["kind"],
            },
            "gaps_s": {key: round(value, 6) for key, value in sorted(self.gaps.items())},
            "classification": {
                kind.value: result.to_dict() for kind, result in self.classification.items()
            },
        }


def run_rehearsal(plan: RehearsalPlan, workdir: Path | str) -> RehearsalOutcome:
    """Preflight, attest, record, map the clocks, emit and verify the sidecar.

    The bag-terminating faults are run in a **child process**, because a
    ``SIGKILL`` and an exhausted volume are both things that happen to a
    process, not to a function. The post-mortem then happens here, from the
    bytes on disk — exactly the order a session-morning crash forces.
    """

    root = Path(workdir)
    root.mkdir(parents=True, exist_ok=True)
    budget = plan_budget(plan)
    bag = root / f"{plan.session_label}.mcap"
    if bag.exists():
        bag.unlink()

    preflight = rehearsal_preflight(plan, storage_path=root, budget=budget)
    attestation = attest(
        preflight,
        session_label=plan.session_label,
        operator=f"{REHEARSAL_PREFIX} fixture",
        generated_realtime_ns=1_800_000_000_000_000_000,
        required_free_bytes=int(budget.required_free_gib() * GIB),
    )

    notes: list[str] = []
    take: TakeResult | None = None
    terminating = next((f for f in plan.faults if f.kind.is_bag_terminating), None)
    if terminating is None:
        take = record_take(plan, bag, budget=budget)
    else:
        note = _run_terminating_child(plan, bag, terminating)
        notes.append(note)

    clock_map = rehearsal_clock_map(plan)
    summary_path = summary_path_for(bag)
    recorder_summary: Mapping[str, Any] | None = None
    if summary_path.exists():
        recorder_summary = json.loads(summary_path.read_text(encoding="utf-8"))

    sidecar, sidecar_path = finalize(
        bag,
        bag_id=plan.session_label,
        created_at_utc="2026-08-13T00:00:00Z",
        expected_channels=[CHANNELS_BY_ID[row.channel_id] for row in budget.rows],
        configured_rates=configured_rates(budget),
        attestation_digest=attestation.digest(),
        clock_map_digest=clock_map_digest(clock_map),
        session_notes=_session_notes(plan, budget, recorder_summary, clock_map),
        extra_does_not_prove=REHEARSAL_DOES_NOT_PROVE,
    )
    verification = verify_sidecar(sidecar, bag)
    if not verification.ok:
        raise RehearsalRefusedError(
            f"the sidecar this rehearsal just wrote does not bind its own bag: "
            f"{'; '.join(verification.failures)}"
        )

    gaps = channel_gaps(bag)
    classification = classify(
        sidecar,
        clock_map=clock_map,
        gaps=gaps,
        recorder_summary=recorder_summary,
    )
    return RehearsalOutcome(
        plan=plan,
        workdir=root,
        budget=budget,
        take=take,
        preflight=preflight,
        attestation=attestation,
        clock_map=clock_map,
        sidecar=sidecar,
        sidecar_path=sidecar_path,
        gaps=gaps,
        classification=classification,
        violations=check_expectations(plan, classification),
        notes=tuple(notes),
    )


#: Lines this module adds to every sidecar it produces. They are about the
#: rehearsal, not about the recorder, and they are what stops a rehearsal bag
#: being read as evidence about hardware six months from now.
REHEARSAL_DOES_NOT_PROVE: tuple[str, ...] = (
    (
        "This bag was produced by scripts/parcel_capture/rehearse.py from SYNTHETIC "
        "publishers. No sensor, robot, camera or LiDAR was involved. Every envelope "
        "declares EvidenceOrigin.SIMULATION and names its fixture."
    ),
    (
        "Payload sizes are scaled down from the PS-E budget model; message counts, rates "
        "and sequence numbers are at full nominal, byte volumes are not."
    ),
    (
        "Host clocks in this bag are VIRTUAL — derived from the timetable, not read from "
        "time.monotonic_ns() — so nothing here measures real-time behaviour, jitter, or "
        "whether any destination sustains the write rate."
    ),
    (
        "The bound attestation was built by PS-D from synthetic readers. PS-D derives "
        "EvidenceOrigin.PHYSICAL from a positive message count alone, so that attestation "
        "claims PHYSICAL for channels no sensor produced; the ONLY markers are this "
        "sidecar's simulation origin and the REHEARSAL-SYNTHETIC session label."
    ),
)


def _session_notes(
    plan: RehearsalPlan,
    budget: Budget,
    recorder_summary: Mapping[str, Any] | None,
    clock_map: ClockMapV1,
) -> tuple[str, ...]:
    notes = [
        f"rehearsal plan: {json.dumps(plan.to_dict(), sort_keys=True)}",
        (
            f"PS-E budget for this profile: {budget.mib_per_second:.3f} MiB/s, "
            f"{budget.gib_per_hour:.2f} GiB/hour, "
            f"{budget.required_free_gib():g} GiB required for {budget.session_duration_s:g} s"
        ),
        f"payload scale applied to every channel: {plan.payload_scale:g}",
        # PS-C builds a clocks block that carries certifiability and its
        # shortfalls (clockmap.sidecar_clock_block); PS-B's build_sidecar
        # composes its own clocks block instead and binds the map by digest
        # only, so whether the bound map can be certified reaches no field of
        # the manifest. Carried here as prose until that seam is closed.
        (
            f"PS-C clocks block (NOT used by build_sidecar, which composes its own): "
            f"{json.dumps(sidecar_clock_block(clock_map), sort_keys=True)}"
        ),
    ]
    if recorder_summary is not None:
        notes.append(
            f"recorder summary written beside the bag: "
            f"{json.dumps(recorder_summary, sort_keys=True)}"
        )
    else:
        notes.append(
            "no recorder summary survives beside this bag; if it is truncated, why it "
            "ended is not recoverable"
        )
    return tuple(notes)


def _child_env() -> dict[str, str]:
    """Environment for the child take: the repo and ``src`` on ``PYTHONPATH``.

    The child is launched with ``-m`` so its relative imports resolve, which
    needs the repo root importable *before* the interpreter starts — the
    in-module ``sys.path`` bootstrap at the top of this file runs too late for
    that. Setting it explicitly is also what makes the child work on an Orin
    with no editable install of ``parcel_robot``.
    """

    root = Path(__file__).resolve().parents[2]
    existing = os.environ.get("PYTHONPATH", "")
    parts = [str(root), str(root / "src")] + ([existing] if existing else [])
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join(parts)
    return env


def _run_terminating_child(plan: RehearsalPlan, bag: Path, fault: Fault) -> str:
    """Run the take in a child so it can really die, and say how it died."""

    plan_path = bag.with_name(bag.name + ".plan.json")
    plan_path.write_text(json.dumps(plan.to_dict(), indent=2, sort_keys=True), encoding="utf-8")
    argv = [
        sys.executable,
        "-m",
        "scripts.parcel_capture.rehearse",
        "--child",
        str(plan_path),
        "--bag",
        str(bag),
    ]
    if fault.kind is FaultKind.WRITE_EXHAUSTION:
        argv += ["--fsize-limit", str(_exhaustion_limit(plan))]
    else:
        argv += ["--kill-after-messages", str(_kill_threshold(plan))]
    completed = subprocess.run(
        argv, capture_output=True, text=True, check=False, env=_child_env()
    )
    if fault.kind is FaultKind.PROCESS_KILL and completed.returncode != -signal.SIGKILL:
        raise RehearsalRefusedError(
            f"the SIGKILL rehearsal child exited {completed.returncode}, not -9; it was "
            f"supposed to die mid-write. stderr: {completed.stderr[-400:]}"
        )
    if fault.kind is FaultKind.WRITE_EXHAUSTION and completed.returncode != 0:
        raise RehearsalRefusedError(
            f"the write-exhaustion child exited {completed.returncode}; it was supposed to "
            f"latch and close. stderr: {completed.stderr[-400:]}"
        )
    return (
        f"{fault.kind.value}: child pid exited {completed.returncode} "
        f"({'SIGKILL' if completed.returncode == -signal.SIGKILL else 'closed after latching'})"
    )


def _exhaustion_limit(plan: RehearsalPlan) -> int:
    """A file-size ceiling the take will hit part-way through.

    ``RLIMIT_FSIZE`` is a genuine kernel refusal to extend a file — the write
    returns ``EFBIG`` rather than ``ENOSPC``, and PS-B latches it as
    ``WRITE_FAILED`` rather than ``DISK_FULL``. Both are the same lane for this
    rehearsal's purpose: the recorder stops, the bytes survive, and the bag
    ends without a footer. The errno-to-reason mapping itself is PS-B's own
    gate (``M6``: ``_DISK_FULL_ERRNOS`` emptied is caught), and this rehearsal
    does not restate it. What no unprivileged process on this host can produce
    is a genuinely full filesystem, which is stated in ``PSE_STATUS.md``.
    """

    return max(256 * 1024, int(_expected_bag_bytes(plan) * 0.4))


def _kill_threshold(plan: RehearsalPlan) -> int:
    """Messages to accept before the child kills itself. Deterministic."""

    return max(50, sum(1 for _ in timetable(plan)) // 2)


def _expected_bag_bytes(plan: RehearsalPlan) -> int:
    budget = plan_budget(plan)
    scaled = math.fsum(
        row.messages_per_second
        * (
            max(1, int(row.payload_bytes_per_message * plan.payload_scale))
            + row.framing_bytes_per_message
        )
        for row in budget.rows
    )
    return max(1, int(scaled * plan.duration_s))


# ---------------------------------------------------------------------------
# Throughput through the real stack, in real time
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class StackThroughput:
    """What the whole capture path achieves on this host, wall-clock."""

    bag_bytes: int
    messages: int
    seconds: float
    host: str
    profile: str
    note: str

    @property
    def bytes_per_second(self) -> float:
        return self.bag_bytes / self.seconds

    @property
    def mib_per_second(self) -> float:
        return self.bytes_per_second / MIB

    @property
    def messages_per_second(self) -> float:
        return self.messages / self.seconds

    def to_dict(self) -> dict[str, Any]:
        return {
            "bag_bytes": self.bag_bytes,
            "messages": self.messages,
            "seconds": round(self.seconds, 6),
            "mib_per_second": round(self.mib_per_second, 3),
            "messages_per_second": round(self.messages_per_second, 1),
            "host": self.host,
            "profile": self.profile,
            "note": self.note,
        }


def measure_stack_throughput(
    profile: D455Profile,
    workdir: Path | str,
    *,
    duration_s: float = 2.0,
    payload_scale: float = 1.0,
    note: str = "dev-host, to be re-measured on the Orin",
) -> StackThroughput:
    """Push a full-size take through the real recorder and time it.

    This is the measurement PS-B's ``does_not_prove`` #9 asks for: not raw disk
    speed, but what survives JSON envelope encoding, MCAP framing, a buffered
    handle and a 1 Hz fsync. It runs as fast as the machine allows — the
    timetable's virtual clock is not throttled to real time — so the number is
    an upper bound on what this host could record, not a simulation of a take.
    """

    plan = RehearsalPlan(
        session_label=f"{REHEARSAL_PREFIX}-throughput",
        profile=profile,
        duration_s=duration_s,
        payload_scale=payload_scale,
    )
    root = Path(workdir)
    root.mkdir(parents=True, exist_ok=True)
    bag = root / "throughput.mcap"
    if bag.exists():
        bag.unlink()
    take = record_take(plan, bag)
    size = bag.stat().st_size
    bag.unlink(missing_ok=True)
    summary_path_for(bag).unlink(missing_ok=True)
    return StackThroughput(
        bag_bytes=size,
        messages=take.messages_recorded,
        seconds=take.wall_seconds,
        host=platform.node(),
        profile=profile.label,
        note=note,
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


DEFAULT_PLAN_FAULTS: tuple[Fault, ...] = (
    Fault(FaultKind.SENSOR_SILENCE, channel_id="go2.utlidar.cloud", at_fraction=0.5),
    Fault(FaultKind.RATE_DEGRADATION, channel_id="go2.sportmodestate", keep_fraction=0.9),
    Fault(FaultKind.BACKPRESSURE_LOSS, channel_id="go2.lowstate", at_fraction=0.5),
    Fault(FaultKind.CLOCK_STEP, at_fraction=0.5, magnitude_ns=500_000_000),
)


def selftest_plans() -> tuple[RehearsalPlan, ...]:
    """The plans ``--selftest`` runs: clean, per-channel faults, and both deaths."""

    profile = D455Profile(848, 480, 30)
    return (
        RehearsalPlan(
            session_label=f"{REHEARSAL_PREFIX}-clean", profile=profile, duration_s=20.0
        ),
        RehearsalPlan(
            session_label=f"{REHEARSAL_PREFIX}-faults",
            profile=profile,
            duration_s=20.0,
            faults=DEFAULT_PLAN_FAULTS,
        ),
        RehearsalPlan(
            session_label=f"{REHEARSAL_PREFIX}-kill",
            profile=profile,
            duration_s=20.0,
            faults=(Fault(FaultKind.PROCESS_KILL),),
        ),
        RehearsalPlan(
            session_label=f"{REHEARSAL_PREFIX}-exhaustion",
            profile=profile,
            duration_s=20.0,
            faults=(Fault(FaultKind.WRITE_EXHAUSTION),),
        ),
    )


def format_outcome(outcome: RehearsalOutcome) -> str:
    lines = [
        f"REHEARSAL {outcome.plan.session_label}",
        (
            f"  profile      {outcome.budget.profile.label}  "
            f"{outcome.budget.mib_per_second:.2f} MiB/s  "
            f"{outcome.budget.gib_per_hour:.1f} GiB/h  "
            f"required {outcome.budget.required_free_gib():g} GiB"
        ),
        (
            f"  preflight    {len(outcome.preflight.channels)} channel(s), "
            f"verdict {outcome.attestation.verdict.value}"
        ),
        (
            f"  clock map    {len(outcome.clock_map.devices)} device(s), "
            f"certifiable={outcome.clock_map.is_certifiable}"
        ),
        (
            f"  sidecar      source={outcome.sidecar.get('source')} "
            f"hardware_claims={outcome.sidecar.get('hardware_claims')} "
            f"termination={outcome.sidecar[SIDECAR_EXTRA_KEY]['termination']['kind']}"
        ),
    ]
    if outcome.take is not None:
        lines.append(
            f"  take         offered {outcome.take.messages_offered}, recorded "
            f"{outcome.take.messages_recorded}, dropped {outcome.take.messages_dropped}"
        )
    for note in outcome.notes:
        lines.append(f"  note         {note}")
    lines.append("  classification:")
    for kind in FaultKind:
        result = outcome.classification[kind]
        mark = {
            Verdict.DETECTED: "DETECTED ",
            Verdict.ABSENT: "absent   ",
            Verdict.UNRESOLVED: "UNRESOLVED",
        }[result.verdict]
        seeded = "seeded" if kind in outcome.plan.seeded_kinds() else "      "
        lines.append(f"    [{mark}] {seeded} {kind.value:<20} via {result.source}")
        for item in result.evidence:
            lines.append(f"        {item}")
    if outcome.green:
        lines.append("  RESULT: GREEN — every seeded fault named, no unseeded fault claimed.")
    else:
        lines.append("  RESULT: RED")
        for violation in outcome.violations:
            lines.append(f"    ! {violation}")
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="parcel-capture-rehearse",
        description=(
            "Drive the whole PS-1 capture stack from synthetic publishers, with seeded "
            "faults, on a host with no hardware and no ROS."
        ),
    )
    parser.add_argument("--workdir", default=None, help="where to write bags and sidecars")
    parser.add_argument("--selftest", action="store_true", help="run every built-in plan")
    parser.add_argument("--plan", default=None, help="path to a rehearsal plan JSON")
    parser.add_argument("--profile", default="848x480@30", help="D455 profile for --selftest")
    parser.add_argument("--duration", type=float, default=20.0, help="take length in seconds")
    parser.add_argument("--json", action="store_true", help="emit the outcome as JSON")
    parser.add_argument("--child", default=None, help=argparse.SUPPRESS)
    parser.add_argument("--bag", default=None, help=argparse.SUPPRESS)
    parser.add_argument(
        "--kill-after-messages", type=int, default=None, help=argparse.SUPPRESS
    )
    parser.add_argument("--fsize-limit", type=int, default=None, help=argparse.SUPPRESS)
    return parser


def _run_child(args: argparse.Namespace) -> int:
    """The recording half, in its own process, so it can really die."""

    plan = RehearsalPlan.from_dict(json.loads(Path(args.child).read_text(encoding="utf-8")))
    if args.fsize_limit is not None:
        signal.signal(signal.SIGXFSZ, signal.SIG_IGN)
        resource.setrlimit(resource.RLIMIT_FSIZE, (args.fsize_limit, args.fsize_limit))
    take = record_take(plan, args.bag, kill_after_messages=args.kill_after_messages)
    print(json.dumps(take.to_dict(), sort_keys=True))
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.child is not None:
            if args.bag is None:
                raise RehearsalRefusedError("--child needs --bag")
            return _run_child(args)

        workdir = Path(
            args.workdir
            if args.workdir is not None
            else Path.cwd() / f"rehearsal-{int(time.time())}"
        )
        if args.plan is not None:
            plans: Sequence[RehearsalPlan] = (
                RehearsalPlan.from_dict(json.loads(Path(args.plan).read_text(encoding="utf-8"))),
            )
        elif args.selftest:
            plans = selftest_plans()
        else:
            plans = (
                RehearsalPlan(
                    session_label=f"{REHEARSAL_PREFIX}-cli",
                    profile=parse_profile(args.profile),
                    duration_s=args.duration,
                ),
            )

        outcomes = [run_rehearsal(plan, workdir / plan.session_label) for plan in plans]
        if args.json:
            print(json.dumps([outcome.to_dict() for outcome in outcomes], indent=2))
        else:
            for outcome in outcomes:
                print(format_outcome(outcome))
                print()
        return 0 if all(outcome.green for outcome in outcomes) else 1
    except (RehearsalError, BudgetRefusedError) as error:
        print(f"REFUSED: {error}", file=sys.stderr)
        return 2
    except OSError as error:
        if error.errno in (errno.ENOSPC, errno.EDQUOT):
            print(
                f"REFUSED: the rehearsal destination is full ({error}); this is the one "
                f"failure a capture rehearsal cannot rehearse around",
                file=sys.stderr,
            )
            return 2
        raise


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    raise SystemExit(main())


__all__ = [
    "DEFAULT_PAYLOAD_SCALE",
    "FIXTURE_MARKER",
    "REHEARSAL_DOES_NOT_PROVE",
    "REHEARSAL_PREFIX",
    "STALL_GAP_PERIODS",
    "Classification",
    "Fault",
    "FaultKind",
    "RehearsalError",
    "RehearsalOutcome",
    "RehearsalPlan",
    "RehearsalRefusedError",
    "StackThroughput",
    "TakeResult",
    "Verdict",
    "channel_gaps",
    "check_expectations",
    "classify",
    "configured_rates",
    "measure_stack_throughput",
    "record_take",
    "rehearsal_clock_map",
    "rehearsal_preflight",
    "rehearsal_reader_factory",
    "run_rehearsal",
    "selftest_plans",
    "timetable",
]
