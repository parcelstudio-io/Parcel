"""Card PS-B: the MCAP recorder and its ``parcel.bag.v1`` sidecar.

The gate this file exists for is the third one on the card, and it is worth
naming precisely because getting it wrong is silent:

    a truncated bag that looks like a sensor dropout would corrupt every
    conclusion drawn from the dataset.

So the file is organised around keeping those two failures apart, and every
property cell is paired with a seeded-failure cell that shows the oracle goes
red for the right reason:

* **G1 framing** — a bag round-trips; a bag without a footer is never "clean".
* **G2 digest**  — one mutated byte breaks sidecar verification.
* **G3 crash**   — a real ``SIGKILL`` mid-write leaves a readable, provably
  TRUNCATED bag, and a refutation panel builds two worlds with the *identical*
  recovered message count where a count-only oracle cannot tell truncation from
  loss and this sidecar can.
* **G4 rate**    — 90% of nominal is DEGRADED with the deficit quantified, and
  the refutation shows the per-channel number line alone cannot see it.
* **G5 disk**    — ``ENOSPC``/``EDQUOT`` latch, the record survives, and the
  latch is reported as a latch rather than as a truncation.
* **G6 space**   — no budget, or a budget that does not fit, is a refusal.
* **G7 closed**  — hardware origin, digests, and mount geometry all fail closed.
* **G8 deps**    — this host refuses cleanly, with no traceback and nothing
  installed; nothing in these scripts can arm anything.
"""

from __future__ import annotations

import errno
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from parcel_robot.bags.schema import (
    REQUIRED_MANIFEST_KEYS,
    SCHEMA_VERSION,
    validate_manifest,
    validate_topic,
)
from parcel_robot.capture import (
    CHANNELS,
    CaptureEnvelope,
    ChannelHealth,
    channel,
)
from parcel_robot.evidence_origin import EvidenceOrigin
from scripts.parcel_capture.record import (
    CHANNEL_ID_METADATA_KEY,
    INSTALL_HINTS,
    MCAP_MAGIC,
    MESSAGE_ENCODING,
    OP_MESSAGE,
    TRANSPORT_DEPENDENCIES,
    TRANSPORT_EXECUTABLES,
    CaptureRecorder,
    LatchReason,
    LiveSourceUnavailableError,
    McapWriteError,
    MinimalMcapWriter,
    NotAnMcapFileError,
    RecorderLatchedError,
    RecorderRefusedError,
    ScannedMessage,
    ScanTermination,
    SpaceBudget,
    check_space,
    frame_payload,
    main,
    missing_dependencies,
    missing_requirements,
    module_available,
    read_mcap,
    resolve_live_source,
    sha256_file,
)
from scripts.parcel_capture.sidecar import (
    SIDECAR_EXTRA_KEY,
    SIDECAR_SCHEMA,
    ChannelVerdict,
    SidecarRefusedError,
    TerminationKind,
    build_sidecar,
    classify_termination,
    finalize,
    read_sidecar,
    sidecar_digest,
    sidecar_path_for,
    verify_sidecar,
    verify_sidecar_or_raise,
    write_sidecar,
)

T0 = 1_700_000_000_000_000_000
BUDGET = SpaceBudget(bytes_per_second=1_000_000, duration_s=600)
LIDAR = "go2.utlidar.cloud"
SPORT = "go2.sportmodestate"
HANDHELD = "go2.wirelesscontroller"
COLOR = "d455.color"


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _recorder(path: Path, *, ids=(LIDAR, SPORT), origin=EvidenceOrigin.PHYSICAL, **kwargs):
    return CaptureRecorder(
        path,
        bag_id=kwargs.pop("bag_id", "ps-b-test"),
        channels=[channel(channel_id) for channel_id in ids],
        origin=origin,
        budget=kwargs.pop("budget", BUDGET),
        **kwargs,
    )


def _drive(recorder, plan, *, duration_s: float, t0: int = T0, drops=()) -> None:
    """Emit each channel at its rate over ``duration_s``, host clocks aligned.

    ``drops`` is a set of ``(channel_id, index)`` receipts that are handed to
    :meth:`CaptureRecorder.drop` instead of being written: a message received
    and never recorded, which is the backpressure loss the per-channel number
    line exists to make provable.
    """

    events: list[tuple[int, str, int]] = []
    for channel_id, rate_hz in plan.items():
        count = round(rate_hz * duration_s)
        for index in range(count):
            events.append((t0 + int(index * 1e9 / rate_hz), channel_id, index))
    events.sort()
    dropped = set(drops)
    for stamp, channel_id, index in events:
        if (channel_id, index) in dropped:
            recorder.drop(channel_id, reason="queue_full")
            continue
        recorder.record(
            channel_id,
            bytes(16),
            host_monotonic_ns=stamp,
            host_realtime_ns=stamp,
            source_timestamp_ns=stamp,
            health=ChannelHealth.NOMINAL,
        )


def _clean_bag(path: Path, *, plan=None, duration_s: float = 20.0, drops=(), **kwargs) -> Path:
    plan = plan or {LIDAR: 10.0, SPORT: 50.0}
    recorder = _recorder(path, ids=tuple(plan), **kwargs)
    try:
        _drive(recorder, plan, duration_s=duration_s, drops=drops)
    finally:
        recorder.close()
    return path


def _sidecar(path: Path, **kwargs) -> dict:
    return build_sidecar(bag_id=kwargs.pop("bag_id", "ps-b-test"), mcap_path=path, **kwargs)


def _capture(sidecar: dict) -> dict:
    return sidecar[SIDECAR_EXTRA_KEY]


def _flip_byte(path: Path, offset: int) -> None:
    data = bytearray(path.read_bytes())
    data[offset] ^= 0xFF
    path.write_bytes(bytes(data))


class _FailingHandle:
    """A handle that starts raising after N bytes have been written.

    A genuine ``ENOSPC`` needs a full filesystem, which a test must not create.
    The house precedent for seeding it is ``tests/test_w0b_commissioning.py``,
    which assigns over ``journal._write``; this wraps the writer's handle the
    same way and forwards everything else to the real file.
    """

    def __init__(self, handle, *, fail_after_bytes: int, error: OSError) -> None:
        self._handle = handle
        self._budget = fail_after_bytes
        self._error = error
        self.failed = False

    def write(self, data) -> int:
        if len(data) > self._budget:
            self.failed = True
            raise self._error
        self._budget -= len(data)
        return self._handle.write(data)

    def flush(self) -> None:
        self._handle.flush()

    def fileno(self) -> int:
        return self._handle.fileno()

    def close(self) -> None:
        self._handle.close()


def _seed_write_failure(recorder: CaptureRecorder, *, after_bytes: int, error: OSError):
    # Both the recorder (which fsyncs) and its writer (which appends) hold the
    # handle, so both are swapped or the fault would only fire on one path.
    handle = _FailingHandle(recorder._handle, fail_after_bytes=after_bytes, error=error)
    recorder._handle = handle
    recorder._writer._handle = handle
    return handle


# ---------------------------------------------------------------------------
# G1 — framing
# ---------------------------------------------------------------------------


def test_a_clean_recording_round_trips_every_envelope_and_ends_with_a_footer(tmp_path):
    bag = _clean_bag(tmp_path / "clean.mcap", duration_s=2.0)
    scan = read_mcap(bag, keep_payloads=True)

    assert scan.termination is ScanTermination.CLEAN
    assert scan.saw_data_end and scan.saw_footer and scan.saw_terminal_magic
    assert scan.trailing_bytes == 0
    assert scan.counts() == {LIDAR: 20, SPORT: 100}
    assert bag.read_bytes().startswith(MCAP_MAGIC)
    assert bag.read_bytes().endswith(MCAP_MAGIC)

    for message in scan.messages:
        assert isinstance(message.envelope, CaptureEnvelope)
        assert message.envelope.origin is EvidenceOrigin.PHYSICAL
        assert message.envelope.frame_id == message.channel.frame_id
        assert message.payload == bytes(16)
    reports = scan.ledger().report()
    assert all(report.is_clean for report in reports.values())


def test_the_bag_carries_its_own_channel_table_and_the_recorders_close_record(tmp_path):
    bag = _clean_bag(tmp_path / "clean.mcap", duration_s=1.0)
    scan = read_mcap(bag)

    assert [entry.channel_id for entry in scan.channels] == [LIDAR, SPORT]
    assert scan.close_metadata is not None
    assert scan.close_metadata["reason"] == "complete"
    assert json.loads(scan.close_metadata["counts"]) == scan.counts()
    assert scan.close_metadata["origin"] == EvidenceOrigin.PHYSICAL.value


def test_seeded_failure_a_bag_without_its_footer_is_never_called_clean(tmp_path):
    """The mutant: a recorder that forgets ``finish()``.

    This is the whole basis of the truncation verdict, so it has to redden on
    its own — not only when a process is killed.
    """

    bag = tmp_path / "no-footer.mcap"
    recorder = _recorder(bag)
    _drive(recorder, {LIDAR: 10.0}, duration_s=1.0)
    recorder._handle.flush()
    os.fsync(recorder._handle.fileno())

    scan = read_mcap(bag)
    assert scan.termination is ScanTermination.TRUNCATED
    assert scan.message_count == 10
    assert classify_termination(scan).kind is TerminationKind.TRUNCATED


@pytest.mark.parametrize(
    ("kwargs", "match"),
    [
        ({"sequence": 2**32}, "message.sequence"),
        ({"log_time_ns": 2**64}, "message.log_time"),
        ({"sequence": -1}, "message.sequence"),
        ({"sequence": True}, "must be an int"),
        ({"sequence": 1.0}, "must be an int"),
    ],
)
def test_the_writer_refuses_a_value_the_wire_format_cannot_hold(tmp_path, kwargs, match):
    """A wrapped sequence would fabricate a duplicate. Refuse, never wrap."""

    path = tmp_path / "raw.mcap"
    with path.open("wb") as handle:
        writer = MinimalMcapWriter(handle)
        writer.register(channel(LIDAR))
        payload = {
            "sequence": 0,
            "log_time_ns": T0,
            "publish_time_ns": T0,
            "data": b"x",
            **kwargs,
        }
        with pytest.raises(McapWriteError, match=match):
            writer.write_message(LIDAR, **payload)


def test_a_file_that_is_not_an_mcap_file_is_a_different_finding_from_truncation(tmp_path):
    path = tmp_path / "not-a-bag.mcap"
    path.write_bytes(b"this is a text file, not a bag at all")
    with pytest.raises(NotAnMcapFileError):
        read_mcap(path)

    partial = tmp_path / "partial-magic.mcap"
    partial.write_bytes(MCAP_MAGIC[:5])
    assert read_mcap(partial).termination is ScanTermination.TRUNCATED


# ---------------------------------------------------------------------------
# G2 — digest binding
# ---------------------------------------------------------------------------


def test_a_sidecar_verifies_against_the_bytes_it_was_built_from(tmp_path):
    bag = _clean_bag(tmp_path / "clean.mcap", duration_s=2.0)
    sidecar = _sidecar(bag)

    result = verify_sidecar(sidecar, bag, rescan=True)
    assert result.ok, result.failures
    assert result.computed_sha256 == sha256_file(bag)[0]
    assert _capture(sidecar)["mcap"]["bytes"] == bag.stat().st_size
    verify_sidecar_or_raise(sidecar, bag, rescan=True)


@pytest.mark.parametrize("where", ["head", "middle", "tail"])
def test_seeded_failure_one_mutated_byte_breaks_sidecar_verification(tmp_path, where):
    bag = _clean_bag(tmp_path / "clean.mcap", duration_s=2.0)
    sidecar = _sidecar(bag)
    size = bag.stat().st_size
    offset = {"head": 12, "middle": size // 2, "tail": size - 3}[where]

    _flip_byte(bag, offset)

    assert bag.stat().st_size == size, "the mutation must not change the size"
    result = verify_sidecar(sidecar, bag)
    assert not result.ok
    assert any("digest mismatch" in failure for failure in result.failures)
    with pytest.raises(SidecarRefusedError, match="digest mismatch"):
        verify_sidecar_or_raise(sidecar, bag)


def test_seeded_failure_an_appended_byte_breaks_verification_on_size_and_digest(tmp_path):
    bag = _clean_bag(tmp_path / "clean.mcap", duration_s=1.0)
    sidecar = _sidecar(bag)
    with bag.open("ab") as handle:
        handle.write(b"\x00")

    result = verify_sidecar(sidecar, bag)
    assert not result.ok
    assert any("digest mismatch" in failure for failure in result.failures)
    assert any("size mismatch" in failure for failure in result.failures)


def test_seeded_failure_a_sidecar_does_not_verify_against_a_different_bag(tmp_path):
    first = _clean_bag(tmp_path / "a.mcap", duration_s=1.0)
    second = _clean_bag(tmp_path / "b.mcap", duration_s=2.0)
    assert not verify_sidecar(_sidecar(first), second).ok


@pytest.mark.parametrize(
    "damage",
    [
        {"schema_version": "parcel.bag.v0"},
        {SIDECAR_EXTRA_KEY: {}},
        {SIDECAR_EXTRA_KEY: {"schema": "something.else", "mcap": {}}},
    ],
)
def test_seeded_failure_a_damaged_sidecar_fails_closed_rather_than_passing(tmp_path, damage):
    bag = _clean_bag(tmp_path / "clean.mcap", duration_s=1.0)
    sidecar = _sidecar(bag)
    sidecar.update(damage)
    assert not verify_sidecar(sidecar, bag).ok


def test_the_sidecar_digest_moves_when_any_field_moves(tmp_path):
    """PS-C and PS-D bind back to this digest, so it must cover everything."""

    bag = _clean_bag(tmp_path / "clean.mcap", duration_s=1.0)
    sidecar = _sidecar(bag)
    base = sidecar_digest(sidecar)
    digests = {base}
    for mutation in (
        lambda record: record.update({"bag_id": "other"}),
        lambda record: record["capture"]["mcap"].update({"sha256": "0" * 64}),
        lambda record: record["capture"]["termination"].update({"kind": "clean-ish"}),
        lambda record: record["does_not_prove"].append("another caveat"),
        lambda record: record["capture"]["channels"][LIDAR].update({"messages": 999}),
    ):
        mutated = json.loads(json.dumps(sidecar))
        mutation(mutated)
        digests.add(sidecar_digest(mutated))
    assert len(digests) == 6


# ---------------------------------------------------------------------------
# G3 — crash safety: the single most important gate on this card
# ---------------------------------------------------------------------------

_CRASH_CHILD = '''
import sys
sys.path.insert(0, {repo!r})
from pathlib import Path
from parcel_robot.capture import channel
from parcel_robot.evidence_origin import EvidenceOrigin
from scripts.parcel_capture.record import CaptureRecorder, SpaceBudget

bag, ready = Path(sys.argv[1]), Path(sys.argv[2])
recorder = CaptureRecorder(
    bag,
    bag_id="crash",
    channels=[channel("go2.utlidar.cloud"), channel("go2.sportmodestate")],
    origin=EvidenceOrigin.PHYSICAL,
    budget=SpaceBudget(bytes_per_second=10_000_000, duration_s=600),
    # No fsync: the bytes that survive are exactly the ones userspace flushed,
    # which is the realistic crash boundary and the harshest one for a reader.
    fsync_every_ns=None,
    buffer_bytes=8192,
)
ready.write_text("ready")
index = 0
while True:
    stamp = {t0} + index * 2_000_000
    recorder.record("go2.sportmodestate", b"S" * 48, host_monotonic_ns=stamp,
                    host_realtime_ns=stamp, source_timestamp_ns=stamp)
    if index % 5 == 0:
        recorder.record("go2.utlidar.cloud", b"C" * 192, host_monotonic_ns=stamp,
                        host_realtime_ns=stamp)
    index += 1
'''


def _sigkill_a_running_recorder(tmp_path: Path, *, grow_to: int = 60_000) -> Path:
    bag = tmp_path / "killed.mcap"
    child = tmp_path / "child.py"
    child.write_text(_CRASH_CHILD.format(repo=str(REPO), t0=T0), encoding="utf-8")
    ready = tmp_path / "ready"
    process = subprocess.Popen([sys.executable, str(child), str(bag), str(ready)])
    try:
        deadline = time.monotonic() + 30.0
        while time.monotonic() < deadline:
            if bag.exists() and bag.stat().st_size >= grow_to:
                break
            if process.poll() is not None:
                raise AssertionError(f"the recorder child exited early ({process.returncode})")
            time.sleep(0.005)
        else:
            raise AssertionError(f"the bag never reached {grow_to} bytes")
        os.kill(process.pid, signal.SIGKILL)
    finally:
        process.wait(timeout=30)
    assert process.returncode == -signal.SIGKILL
    return bag


def test_sigkill_mid_recording_leaves_a_readable_bag_recorded_as_truncated(tmp_path):
    """The headline gate. The process dies; the evidence survives and says so."""

    bag = _sigkill_a_running_recorder(tmp_path)
    scan = read_mcap(bag)

    # readable up to the last complete message
    assert scan.message_count >= 50, scan.message_count
    assert scan.termination is ScanTermination.TRUNCATED
    assert not scan.saw_footer and not scan.saw_terminal_magic
    assert scan.close_metadata is None, "a killed recorder cannot have closed its bag"
    assert scan.trailing_bytes == scan.file_bytes - scan.last_complete_offset

    # every recovered message is intact, not merely counted
    for message in scan.messages:
        assert message.envelope.origin is EvidenceOrigin.PHYSICAL
        assert message.envelope.channel_id == message.channel.channel_id

    # nothing BEFORE the cut was lost: each channel's number line runs 0..n-1
    for report in scan.ledger().report().values():
        assert report.is_clean
        assert report.first_sequence == 0
        assert report.last_sequence == report.received - 1

    # and it is recorded AS truncation, with the byte evidence
    sidecar = _sidecar(bag, bag_id="crash")
    termination = _capture(sidecar)["termination"]
    assert termination["kind"] == TerminationKind.TRUNCATED.value
    assert termination["evidence"]["saw_terminal_magic"] is False
    assert termination["evidence"]["recorder_close_record"] is None
    assert any("TRUNCATED" in line for line in sidecar["does_not_prove"])

    # the truncation cut a SUFFIX off every channel, so it left no holes
    for observation in _capture(sidecar)["channels"].values():
        assert observation["sequence"]["missing_count"] == 0
        assert not observation["reason"].startswith("sequence_gap")


def test_a_truncated_bag_and_a_dropping_sensor_are_never_confused(tmp_path):
    """Refutation panel — the two worlds a naive reader cannot tell apart.

    Both bags end up holding exactly 90 LiDAR messages. In one, the recorder
    was cut off after the 90th. In the other, it ran to a clean close and lost
    10 messages to backpressure in the middle. A count-only oracle — which is
    all ``bags/recorder.py``'s global write-time counter could ever support —
    returns the identical answer for both. This sidecar does not.
    """

    truncated = tmp_path / "truncated.mcap"
    _clean_bag(truncated, plan={LIDAR: 10.0}, duration_s=10.0)
    complete = read_mcap(truncated)
    assert complete.message_count == 100
    cut_at = [message.offset for message in complete.messages][90]
    os.truncate(truncated, cut_at)

    dropping = tmp_path / "dropping.mcap"
    _clean_bag(
        dropping,
        plan={LIDAR: 10.0},
        duration_s=10.0,
        drops=[(LIDAR, index) for index in range(40, 50)],
    )

    truncated_scan = read_mcap(truncated)
    dropping_scan = read_mcap(dropping)

    # the count-only oracle: identical.
    assert truncated_scan.message_count == dropping_scan.message_count == 90

    truncated_side = _sidecar(truncated, bag_id="t")
    dropping_side = _sidecar(dropping, bag_id="d")

    # the framing signal fires on one and only one of them
    assert _capture(truncated_side)["termination"]["kind"] == TerminationKind.TRUNCATED.value
    assert _capture(dropping_side)["termination"]["kind"] == TerminationKind.CLEAN.value
    assert _capture(truncated_side)["termination"]["evidence"]["saw_terminal_magic"] is False
    assert _capture(dropping_side)["termination"]["evidence"]["saw_terminal_magic"] is True

    # the number-line signal fires on the other one and only it
    truncated_channel = _capture(truncated_side)["channels"][LIDAR]
    dropping_channel = _capture(dropping_side)["channels"][LIDAR]
    assert truncated_channel["sequence"]["missing_count"] == 0
    assert dropping_channel["sequence"]["missing_count"] == 10
    assert dropping_channel["sequence"]["missing"] == list(range(40, 50))
    assert dropping_channel["verdict"] == ChannelVerdict.DEGRADED.value
    assert dropping_channel["reason"].startswith("sequence_gap")

    # neither report claims the other's failure
    assert not any("TRUNCATED" in line for line in dropping_side["does_not_prove"])
    assert not any(
        "sequence_gap" in observation["reason"]
        for observation in _capture(truncated_side)["channels"].values()
    )

    # and the recorder's own tally agrees with the holes on the bag that has them
    assert _capture(dropping_side)["recorder_account"]["status"] == "agrees"
    assert _capture(dropping_side)["recorder_account"]["declared_drops"][LIDAR] == 10


@pytest.mark.parametrize("shave", [1, 2, 9, 17, 40])
def test_truncation_is_recognised_at_every_cut_point_of_the_final_record(tmp_path, shave):
    """A machine power cut lands mid-record, not on a record boundary.

    The SIGKILL case above always cuts between records, because the writer
    emits one buffered ``write()`` per record. A lost page cache does not, so
    the reader is proved on partial length prefixes and partial contents too.
    """

    bag = _clean_bag(tmp_path / "clean.mcap", plan={LIDAR: 10.0}, duration_s=5.0)
    size = bag.stat().st_size
    os.truncate(bag, size - shave)

    scan = read_mcap(bag)
    assert scan.termination is ScanTermination.TRUNCATED
    assert scan.message_count >= 40
    assert classify_termination(scan).kind is TerminationKind.TRUNCATED


def test_a_bag_truncated_before_its_channel_table_is_refused_not_guessed(tmp_path):
    bag = _clean_bag(tmp_path / "clean.mcap", plan={LIDAR: 10.0}, duration_s=1.0)
    os.truncate(bag, 30)

    scan = read_mcap(bag)
    assert scan.termination is ScanTermination.TRUNCATED
    assert scan.channels == ()
    with pytest.raises(SidecarRefusedError, match="registers no channels"):
        _sidecar(bag)

    # ...but an operator who knows what was requested may say so explicitly,
    # and then every channel is honestly ABSENT rather than invented.
    sidecar = _sidecar(bag, expected_channels=[channel(LIDAR)])
    assert _capture(sidecar)["channels"][LIDAR]["verdict"] == ChannelVerdict.ABSENT.value
    assert sidecar["source"] == "sim", "a bag with no messages cannot claim hardware"


def test_a_corrupt_record_is_corrupt_and_not_reported_as_truncation(tmp_path):
    """Bytes all present, decode impossible. A third, separate classification."""

    bag = _clean_bag(tmp_path / "clean.mcap", plan={LIDAR: 10.0}, duration_s=2.0)
    scan = read_mcap(bag)
    target = scan.messages[10]
    # Corrupt the envelope JSON inside a fully-present record.
    data = bytearray(bag.read_bytes())
    window = data[target.offset : target.offset + 400]
    index = window.find(b'"channel_id"')
    assert index > 0
    data[target.offset + index + 3] = ord("!")
    bag.write_bytes(bytes(data))

    damaged = read_mcap(bag)
    assert damaged.termination is ScanTermination.CORRUPT
    assert damaged.message_count == 10
    sidecar = _sidecar(bag)
    assert _capture(sidecar)["termination"]["kind"] == TerminationKind.CORRUPT.value
    assert not any("TRUNCATED" in line for line in sidecar["does_not_prove"])


def test_a_message_whose_envelope_disagrees_with_its_mcap_sequence_is_corrupt(tmp_path):
    """The bag cross-checks itself: two copies of the sequence must agree."""

    path = tmp_path / "forged.mcap"
    entry = channel(LIDAR)
    envelope = CaptureEnvelope(
        channel_id=LIDAR,
        sequence=7,
        source_timestamp_ns=T0,
        host_monotonic_ns=T0,
        host_realtime_ns=T0,
        frame_id=entry.frame_id,
        origin=EvidenceOrigin.PHYSICAL,
    )
    with path.open("wb") as handle:
        writer = MinimalMcapWriter(handle)
        writer.register(entry)
        writer.write_message(
            LIDAR,
            sequence=6,  # the forgery: MCAP says 6, the envelope says 7
            log_time_ns=T0,
            publish_time_ns=T0,
            data=frame_payload(envelope, b""),
        )
        writer.finish()

    scan = read_mcap(path)
    assert scan.termination is ScanTermination.CORRUPT
    assert "disagrees with envelope sequence" in scan.detail
    assert scan.message_count == 0


def test_a_bag_naming_a_channel_outside_the_matrix_is_refused(tmp_path):
    path = tmp_path / "unknown.mcap"
    with path.open("wb") as handle:
        writer = MinimalMcapWriter(handle)
        writer.register(channel(LIDAR))
        writer.finish()
    data = bytearray(path.read_bytes())
    marker = LIDAR.encode("utf-8")
    # The last occurrence is the Channel record's parcel_channel_id metadata;
    # same length, so only the identity changes.
    index = data.rfind(marker)
    assert index > 0
    data[index : index + len(marker)] = b"go2.utlidar.clouX"
    assert len(data) == path.stat().st_size
    path.write_bytes(bytes(data))

    scan = read_mcap(path)
    assert scan.termination is ScanTermination.CORRUPT
    assert "unknown channel_id" in scan.detail


# ---------------------------------------------------------------------------
# G4 — per-channel expected counts and degradation
# ---------------------------------------------------------------------------


def test_a_channel_at_ninety_percent_of_nominal_is_degraded_with_the_deficit(tmp_path):
    """The card's gate, with the deficit quantified rather than a bare flag."""

    bag = _clean_bag(
        tmp_path / "slow.mcap",
        plan={LIDAR: 9.0, SPORT: 50.0},  # LiDAR nominal is 10 Hz; this is 90%
        duration_s=20.0,
    )
    sidecar = _sidecar(bag)
    lidar = _capture(sidecar)["channels"][LIDAR]
    sport = _capture(sidecar)["channels"][SPORT]

    assert lidar["verdict"] == ChannelVerdict.DEGRADED.value
    assert lidar["reason"].startswith("rate_below_expectation")
    assert lidar["messages"] == 180
    assert lidar["expected_rate_hz"] == 10.0
    assert 8.9 < lidar["observed_rate_hz"] < 9.1
    assert 0.09 < lidar["deficit_fraction"] < 0.11
    assert lidar["deficit_messages"] > 0
    assert lidar["is_fault"] is True

    assert sport["verdict"] == ChannelVerdict.PRESENT.value
    assert sport["is_fault"] is False
    assert _capture(sidecar)["channel_summary"]["faults"] == [LIDAR]
    assert any(LIDAR in line for line in sidecar["does_not_prove"])


def test_refutation_the_per_channel_number_line_alone_cannot_see_a_slow_sensor(tmp_path):
    """Why the rate assertion is a separate gate and not a duplicate of PS-A.

    A sensor that publishes at 90% of nominal delivers a CONTIGUOUS number
    line — the sequence is minted at receipt, so nothing was received and lost.
    PS-A's ledger is clean. Only the expected-count assertion catches it, and
    this cell asserts the ledger's silence explicitly so the two gates can
    never be collapsed into one.
    """

    bag = _clean_bag(tmp_path / "slow.mcap", plan={LIDAR: 9.0}, duration_s=20.0)
    scan = read_mcap(bag)
    report = scan.ledger().report()[LIDAR]

    assert report.is_clean
    assert report.missing_count == 0 and report.duplicate_count == 0
    assert report.first_sequence == 0 and report.last_sequence == 179

    sidecar = _sidecar(bag)
    assert _capture(sidecar)["channels"][LIDAR]["verdict"] == ChannelVerdict.DEGRADED.value


def test_a_channel_delivering_its_nominal_rate_is_present(tmp_path):
    bag = _clean_bag(tmp_path / "ok.mcap", plan={LIDAR: 10.0, SPORT: 50.0}, duration_s=20.0)
    sidecar = _sidecar(bag)
    verdicts = {
        key: value["verdict"] for key, value in _capture(sidecar)["channels"].items()
    }
    assert verdicts == {LIDAR: "present", SPORT: "present"}
    assert _capture(sidecar)["channel_summary"]["fault_count"] == 0


def test_a_silent_periodic_channel_is_absent_and_counts_as_a_fault(tmp_path):
    bag = tmp_path / "silent.mcap"
    recorder = _recorder(bag, ids=(LIDAR, SPORT))
    _drive(recorder, {SPORT: 50.0}, duration_s=5.0)
    recorder.close()

    sidecar = _sidecar(bag)
    lidar = _capture(sidecar)["channels"][LIDAR]
    assert lidar["verdict"] == ChannelVerdict.ABSENT.value
    assert lidar["messages"] == 0
    assert lidar["is_fault"] is True
    assert _capture(sidecar)["channel_summary"]["faults"] == [LIDAR]


def test_a_silent_event_driven_channel_is_absent_and_is_not_a_fault(tmp_path):
    """Silence on the handheld is normal. Fail-closed must not mean noisy."""

    bag = tmp_path / "handheld.mcap"
    recorder = _recorder(bag, ids=(SPORT, HANDHELD))
    _drive(recorder, {SPORT: 50.0}, duration_s=5.0)
    recorder.close()

    handheld = _capture(_sidecar(bag))["channels"][HANDHELD]
    assert handheld["verdict"] == ChannelVerdict.ABSENT.value
    assert handheld["is_fault"] is False
    assert "event_driven_silence" in handheld["reason"]


def test_a_configured_channel_without_a_supplied_rate_is_unassessable_not_present(tmp_path):
    """``d455.color``'s rate is PS-E's budget decision; unassessed is not passed."""

    bag = tmp_path / "camera.mcap"
    recorder = _recorder(bag, ids=(COLOR,))
    _drive(recorder, {COLOR: 30.0}, duration_s=2.0)
    recorder.close()

    bare = _capture(_sidecar(bag))["channels"][COLOR]
    assert bare["verdict"] == ChannelVerdict.UNASSESSABLE.value
    assert bare["expected_rate_hz"] is None
    assert "no_rate_expectation" in bare["reason"]
    assert any("unassessed is not passed" in line for line in _sidecar(bag)["does_not_prove"])

    told = _capture(_sidecar(bag, configured_rates={COLOR: 30.0}))["channels"][COLOR]
    assert told["verdict"] == ChannelVerdict.PRESENT.value
    assert told["expected_rate_hz"] == 30.0

    wrong = _capture(_sidecar(bag, configured_rates={COLOR: 60.0}))["channels"][COLOR]
    assert wrong["verdict"] == ChannelVerdict.DEGRADED.value


@pytest.mark.parametrize("rate", [0.0, -1.0, float("nan"), float("inf"), True, "30"])
def test_seeded_failure_a_malformed_configured_rate_is_refused_never_defaulted(tmp_path, rate):
    bag = _clean_bag(tmp_path / "clean.mcap", plan={LIDAR: 10.0}, duration_s=1.0)
    with pytest.raises(SidecarRefusedError):
        _sidecar(bag, configured_rates={LIDAR: rate})


def test_over_delivery_is_a_finding_about_the_matrix_not_a_pass(tmp_path):
    bag = _clean_bag(tmp_path / "fast.mcap", plan={LIDAR: 20.0}, duration_s=10.0)
    lidar = _capture(_sidecar(bag))["channels"][LIDAR]
    assert lidar["verdict"] == ChannelVerdict.DEGRADED.value
    assert lidar["reason"].startswith("rate_above_expectation")
    assert lidar["deficit_messages"] < 0


# ---------------------------------------------------------------------------
# G5 — disk full: latched, record survives, degradation fails closed
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("code", "expected"),
    [
        (errno.ENOSPC, LatchReason.DISK_FULL),
        (errno.EDQUOT, LatchReason.DISK_FULL),
        (errno.EIO, LatchReason.WRITE_FAILED),
    ],
)
def test_a_write_failure_mid_record_latches_by_name_and_the_record_survives(
    tmp_path, code, expected
):
    bag = tmp_path / "full.mcap"
    recorder = _recorder(bag, ids=(LIDAR,))
    _drive(recorder, {LIDAR: 10.0}, duration_s=3.0)
    before = recorder.messages_written
    _seed_write_failure(recorder, after_bytes=0, error=OSError(code, os.strerror(code)))

    with pytest.raises(RecorderLatchedError) as excinfo:
        recorder.record(LIDAR, b"x", host_monotonic_ns=T0, host_realtime_ns=T0)
    assert excinfo.value.reason is expected

    # every later message is refused, not silently dropped
    with pytest.raises(RecorderLatchedError):
        recorder.record(LIDAR, b"y", host_monotonic_ns=T0, host_realtime_ns=T0)

    summary = recorder.close()
    assert summary.latch_reason is expected
    assert summary.messages_written == before
    assert bag.exists() and bag.stat().st_size > 0, "the bytes already written must survive"


def test_a_latched_recording_is_reported_as_a_latch_not_as_a_truncation(tmp_path):
    """The fourth classification: byte-clean, and still a failed session."""

    bag = tmp_path / "quota.mcap"
    recorder = _recorder(bag, ids=(LIDAR,))
    _drive(recorder, {LIDAR: 10.0}, duration_s=3.0)
    handle = _seed_write_failure(
        recorder, after_bytes=0, error=OSError(errno.EDQUOT, "Disk quota exceeded")
    )
    with pytest.raises(RecorderLatchedError):
        recorder.record(LIDAR, b"x", host_monotonic_ns=T0, host_realtime_ns=T0)
    assert handle.failed
    # Let the close path write the footer to the real file: this proves a bag
    # can be byte-clean and still carry a failed session.
    recorder._handle = handle._handle
    recorder._writer._handle = handle._handle
    recorder.close()

    scan = read_mcap(bag)
    assert scan.termination is ScanTermination.CLEAN
    sidecar = _sidecar(bag)
    termination = _capture(sidecar)["termination"]
    assert termination["kind"] == TerminationKind.LATCHED_WRITE_FAILURE.value
    assert "disk_full" in termination["detail"]
    assert any("latched a write failure" in line for line in sidecar["does_not_prove"])
    assert not any("TRUNCATED" in line for line in sidecar["does_not_prove"])


def test_close_never_raises_when_the_volume_is_still_broken(tmp_path):
    """W0-B's rule: teardown failures cost a digest, never the evidence."""

    bag = tmp_path / "still-full.mcap"
    recorder = _recorder(bag, ids=(LIDAR,))
    _drive(recorder, {LIDAR: 10.0}, duration_s=2.0)
    _seed_write_failure(recorder, after_bytes=0, error=OSError(errno.ENOSPC, "No space"))
    with pytest.raises(RecorderLatchedError):
        recorder.record(LIDAR, b"x", host_monotonic_ns=T0, host_realtime_ns=T0)

    summary = recorder.close()  # must not raise
    assert summary.close_problem
    assert summary.closed_cleanly is False
    assert read_mcap(bag).termination is ScanTermination.TRUNCATED
    assert read_mcap(bag).message_count == 20


def test_the_recorder_declaring_drops_that_the_bag_does_not_show_is_a_finding(tmp_path):
    """Two independent tallies; a disagreement is never reconciled silently."""

    bag = tmp_path / "liar.mcap"
    recorder = _recorder(bag, ids=(LIDAR,))
    _drive(recorder, {LIDAR: 10.0}, duration_s=3.0)
    recorder._drops[LIDAR] = 4
    recorder.close()

    sidecar = _sidecar(bag)
    account = _capture(sidecar)["recorder_account"]
    assert account["status"] == "disagrees"
    assert account["declared_drops"] == {LIDAR: 4}
    assert account["observed_sequence_holes"] == {}
    assert any("Unreconciled finding" in line for line in sidecar["does_not_prove"])


# ---------------------------------------------------------------------------
# G6 — refusing to start
# ---------------------------------------------------------------------------


def test_the_recorder_refuses_to_start_without_a_budget(tmp_path):
    with pytest.raises(RecorderRefusedError, match="unknown is not permission"):
        _recorder(tmp_path / "nobudget.mcap", budget=None)
    assert not (tmp_path / "nobudget.mcap").exists()


def test_the_recorder_refuses_when_free_space_is_below_the_budget(tmp_path, monkeypatch):
    from scripts.parcel_capture import record as record_module

    class _Usage:
        free = 1_000

    monkeypatch.setattr(record_module.shutil, "disk_usage", lambda _path: _Usage)
    with pytest.raises(RecorderRefusedError, match="refusing to start"):
        _recorder(tmp_path / "toobig.mcap", budget=SpaceBudget(1_000_000, 600))

    check = check_space(tmp_path, SpaceBudget(1_000_000, 600))
    assert not check.ok
    assert check.required_bytes > check.free_bytes


@pytest.mark.parametrize(
    "kwargs",
    [
        {"bytes_per_second": 0.0, "duration_s": 10.0},
        {"bytes_per_second": -1.0, "duration_s": 10.0},
        {"bytes_per_second": 1.0, "duration_s": 0.0},
        {"bytes_per_second": float("nan"), "duration_s": 10.0},
        {"bytes_per_second": float("inf"), "duration_s": 10.0},
        {"bytes_per_second": True, "duration_s": 10.0},
        {"bytes_per_second": 1.0, "duration_s": 10.0, "margin": -0.1},
    ],
)
def test_seeded_failure_a_nonsense_budget_is_refused(kwargs):
    with pytest.raises(RecorderRefusedError):
        SpaceBudget(**kwargs)


def test_the_recorder_refuses_to_overwrite_a_non_empty_bag(tmp_path):
    bag = _clean_bag(tmp_path / "clean.mcap", plan={LIDAR: 10.0}, duration_s=1.0)
    with pytest.raises(RecorderRefusedError, match="never reconstructable"):
        _recorder(bag, ids=(LIDAR,))


@pytest.mark.parametrize(
    ("kwargs", "match"),
    [
        ({"origin": EvidenceOrigin.UNKNOWN}, "declared EvidenceOrigin"),
        ({"ids": ()}, "records nothing"),
        ({"ids": (LIDAR, LIDAR)}, "duplicate channel"),
        ({"bag_id": "  "}, "bag_id"),
    ],
)
def test_seeded_failure_the_recorder_refuses_an_underdeclared_session(tmp_path, kwargs, match):
    with pytest.raises(RecorderRefusedError, match=match):
        _recorder(tmp_path / "bad.mcap", **kwargs)


def test_an_undeclared_channel_is_refused_at_record_time(tmp_path):
    bag = tmp_path / "scoped.mcap"
    recorder = _recorder(bag, ids=(LIDAR,))
    try:
        with pytest.raises(RecorderRefusedError, match="not declared"):
            recorder.record(SPORT, b"x", host_monotonic_ns=T0, host_realtime_ns=T0)
    finally:
        recorder.close()


# ---------------------------------------------------------------------------
# G7 — the sidecar fails closed
# ---------------------------------------------------------------------------


def test_the_manifest_is_an_unmodified_parcel_bag_v1(tmp_path):
    """``bags/schema.py`` is called, never edited. Its own validator says so."""

    bag = _clean_bag(tmp_path / "clean.mcap", duration_s=2.0)
    sidecar = _sidecar(bag)

    validate_manifest(sidecar)
    assert sidecar["schema_version"] == SCHEMA_VERSION
    assert REQUIRED_MANIFEST_KEYS <= set(sidecar)
    assert sidecar["source"] == "hardware"
    assert sidecar["clocks"]["source_clock"] == "sensor"
    assert sidecar["frames"]["base_frame"] == "base_link"
    assert sidecar["message_count"] == 120
    assert _capture(sidecar)["schema"] == SIDECAR_SCHEMA
    for topic in sidecar["topics"]:
        validate_topic(topic)
    assert sidecar["topics"] == ["go2/utlidar/cloud", "go2/sportmodestate"]


def test_the_monotonic_origin_is_the_bags_first_sample_not_a_zero(tmp_path):
    """``schema.py:134`` hands back 0, which is the arbitrary-epoch defect."""

    bag = _clean_bag(tmp_path / "clean.mcap", plan={LIDAR: 10.0}, duration_s=1.0)
    sidecar = _sidecar(bag)
    assert sidecar["clocks"]["recording_monotonic_origin_ns"] == T0
    assert "PS-C clock map" in sidecar["clocks"]["note"]


def test_source_hardware_is_reachable_only_from_physical_envelopes(tmp_path):
    physical = _clean_bag(tmp_path / "real.mcap", plan={LIDAR: 10.0}, duration_s=1.0)
    assert _sidecar(physical)["source"] == "hardware"
    assert _sidecar(physical)["hardware_claims"] is True

    rehearsal = tmp_path / "rehearsal.mcap"
    recorder = _recorder(
        rehearsal,
        ids=(LIDAR,),
        origin=EvidenceOrigin.SIMULATION,
        fixture_label="ps-e-rehearsal",
    )
    _drive(recorder, {LIDAR: 10.0}, duration_s=1.0)
    recorder.close()

    sidecar = _sidecar(rehearsal)
    assert sidecar["source"] == "sim"
    assert sidecar["hardware_claims"] is False
    assert _capture(sidecar)["origin"]["observed"] == ["simulation"]
    assert _capture(sidecar)["origin"]["basis"] == "envelopes"


def test_a_bag_that_mixes_origins_is_refused_not_majority_voted(tmp_path):
    bag = _clean_bag(tmp_path / "clean.mcap", plan={LIDAR: 10.0}, duration_s=1.0)
    scan = read_mcap(bag)
    intruder = ScannedMessage(
        channel=channel(LIDAR),
        envelope=CaptureEnvelope(
            channel_id=LIDAR,
            sequence=999,
            source_timestamp_ns=None,
            host_monotonic_ns=T0,
            host_realtime_ns=T0,
            frame_id=channel(LIDAR).frame_id,
            origin=EvidenceOrigin.SIMULATION,
            fixture_label="smuggled",
        ),
        log_time_ns=T0,
        publish_time_ns=T0,
        payload_bytes=0,
        offset=0,
    )
    mixed = type(scan)(**{**scan.__dict__, "messages": scan.messages + (intruder,)})
    with pytest.raises(SidecarRefusedError, match="mixes evidence origins"):
        _sidecar(bag, scan=mixed)


def test_an_absent_clock_map_or_attestation_is_recorded_as_absent(tmp_path):
    bag = _clean_bag(tmp_path / "clean.mcap", plan={LIDAR: 10.0}, duration_s=1.0)
    sidecar = _sidecar(bag)
    for key in ("clock_map", "attestation"):
        block = _capture(sidecar)[key]
        assert block["status"] == "absent"
        assert block["digest"] is None
        assert block["note"]
    assert any("ClockMapV1 is absent" in line for line in sidecar["does_not_prove"])
    assert any("HardwareAttestationV1 is absent" in line for line in sidecar["does_not_prove"])


def test_a_present_clock_map_and_attestation_digest_round_trip_through_extra(tmp_path):
    """PS-C and PS-D bind to this bag by digest and nothing else."""

    bag = _clean_bag(tmp_path / "clean.mcap", plan={LIDAR: 10.0}, duration_s=1.0)
    clock = "a" * 64
    attest = "b" * 64
    sidecar = _sidecar(bag, clock_map_digest=clock, attestation_digest=attest)

    assert _capture(sidecar)["clock_map"]["digest"] == clock
    assert _capture(sidecar)["attestation"]["digest"] == attest
    assert _capture(sidecar)["clock_map"]["status"] == "present"
    assert not any("ClockMapV1 is absent" in line for line in sidecar["does_not_prove"])

    written = write_sidecar(sidecar, sidecar_path_for(bag))
    reloaded = read_sidecar(written)
    assert reloaded[SIDECAR_EXTRA_KEY]["clock_map"]["digest"] == clock
    assert sidecar_digest(reloaded) == sidecar_digest(sidecar)


@pytest.mark.parametrize("digest", ["", "abc", "A" * 64, "a" * 63, "a" * 65, "g" * 64, 12345])
def test_seeded_failure_a_malformed_digest_is_refused_never_recorded_as_absent(tmp_path, digest):
    bag = _clean_bag(tmp_path / "clean.mcap", plan={LIDAR: 10.0}, duration_s=1.0)
    with pytest.raises(SidecarRefusedError, match="must be a 64-character"):
        _sidecar(bag, clock_map_digest=digest)


_GOOD_MOUNT = {
    "d455": {
        "parent_frame": "base_link",
        "xyz_m": [0.21, 0.0, 0.14],
        "rpy_rad": [0.0, 0.18, 0.0],
        "method": "tape measure, bracket face to lens centre",
        "uncertainty_m": 0.005,
        "measured_at_utc": "2026-08-13T09:15:00Z",
    }
}


def test_measured_mount_geometry_lands_in_extra_and_changes_the_frames_note(tmp_path):
    bag = _clean_bag(tmp_path / "clean.mcap", plan={LIDAR: 10.0}, duration_s=1.0)
    sidecar = _sidecar(bag, mount_geometry=_GOOD_MOUNT)

    block = _capture(sidecar)["mount_geometry"]
    assert block["status"] == "measured"
    assert block["sensors"]["d455"]["xyz_m"] == [0.21, 0.0, 0.14]
    assert block["sensors"]["d455"]["uncertainty_m"] == 0.005
    assert "recorded in capture.mount_geometry" in sidecar["frames"]["ownership_note"]
    assert not any("extrinsics were not measured" in line for line in sidecar["does_not_prove"])


def test_absent_mount_geometry_is_unmeasured_and_says_so_twice(tmp_path):
    bag = _clean_bag(tmp_path / "clean.mcap", plan={LIDAR: 10.0}, duration_s=1.0)
    sidecar = _sidecar(bag)
    assert _capture(sidecar)["mount_geometry"]["status"] == "unmeasured"
    assert "UNMEASURED" in sidecar["frames"]["ownership_note"]
    assert any("extrinsics were not measured" in line for line in sidecar["does_not_prove"])


@pytest.mark.parametrize(
    "damage",
    [
        {"method": ""},
        {"uncertainty_m": 0.0},
        {"uncertainty_m": -0.01},
        {"uncertainty_m": float("nan")},
        {"measured_at_utc": "yesterday"},
        {"parent_frame": " "},
        {"xyz_m": [0.0, 0.0]},
        {"xyz_m": "0,0,0"},
        {"rpy_rad": [0.0, 0.0, float("inf")]},
    ],
)
def test_seeded_failure_an_undeclared_mount_extrinsic_is_refused(tmp_path, damage):
    """A triple of numbers with no method or uncertainty is not a measurement."""

    bag = _clean_bag(tmp_path / "clean.mcap", plan={LIDAR: 10.0}, duration_s=1.0)
    geometry = {"d455": {**_GOOD_MOUNT["d455"], **damage}}
    with pytest.raises(SidecarRefusedError):
        _sidecar(bag, mount_geometry=geometry)


def test_seeded_failure_a_mount_entry_missing_a_required_key_is_refused(tmp_path):
    bag = _clean_bag(tmp_path / "clean.mcap", plan={LIDAR: 10.0}, duration_s=1.0)
    for key in _GOOD_MOUNT["d455"]:
        stripped = {name: value for name, value in _GOOD_MOUNT["d455"].items() if name != key}
        with pytest.raises(SidecarRefusedError, match="missing"):
            _sidecar(bag, mount_geometry={"d455": stripped})


def test_does_not_prove_is_non_empty_and_specific_on_every_path(tmp_path):
    bags = {
        "clean": _clean_bag(tmp_path / "a.mcap", plan={LIDAR: 10.0}, duration_s=2.0),
        "dropping": _clean_bag(
            tmp_path / "b.mcap", plan={LIDAR: 10.0}, duration_s=2.0, drops=[(LIDAR, 5)]
        ),
    }
    truncated = _clean_bag(tmp_path / "c.mcap", plan={LIDAR: 10.0}, duration_s=2.0)
    os.truncate(truncated, truncated.stat().st_size - 60)
    bags["truncated"] = truncated

    for name, bag in bags.items():
        sidecar = _sidecar(bag)
        lines = sidecar["does_not_prove"]
        assert lines and all(isinstance(line, str) and line.strip() for line in lines), name
        assert any("reference mcap implementation" in line for line in lines), name


def test_finalize_writes_the_sidecar_atomically_beside_its_bag(tmp_path):
    bag = _clean_bag(tmp_path / "clean.mcap", plan={LIDAR: 10.0}, duration_s=1.0)
    manifest, path = finalize(bag, bag_id="ps-b-final")

    assert manifest["bag_id"] == "ps-b-final"
    assert path == sidecar_path_for(bag)
    assert path.name == "clean.mcap.parcel-bag.json"
    assert not list(tmp_path.glob("*.tmp")), "no temp file may survive a write"
    assert read_sidecar(path)["bag_id"] == "ps-b-final"
    verify_sidecar_or_raise(read_sidecar(path), bag, rescan=True)


def test_read_sidecar_refuses_anything_that_is_not_an_object(tmp_path):
    path = tmp_path / "bad.json"
    path.write_text("[1, 2, 3]", encoding="utf-8")
    with pytest.raises(SidecarRefusedError, match="not a JSON object"):
        read_sidecar(path)
    with pytest.raises(SidecarRefusedError, match="cannot read"):
        read_sidecar(tmp_path / "absent.json")


# ---------------------------------------------------------------------------
# G8 — dependencies, refusals, and the motion guarantee
# ---------------------------------------------------------------------------


def test_no_live_reader_can_run_here_and_the_report_says_which_half_is_missing(tmp_path):
    """A measured claim, re-cut by card ENV-1 — and still the motion guarantee.

    Was ``test_this_host_has_none_of_the_live_capture_dependencies``, which
    asserted six modules were absent. The premise died on 2026-08-22 when P1-A
    installed ``pyrealsense2`` and ``opencv-python-headless`` into ``.parcel``
    for the desk-camera venue. The claim worth making does not depend on that
    afternoon's ``pip list``:

    * the SDKs that can COMMAND the dog stay absent — that is the guarantee,
      and it is unchanged;
    * every live reader still refuses on this host; and
    * the refusal names WHICH half is missing, the module or the device, because
      "install the SDK" and "plug the camera in" are different instructions and
      an operator handed the wrong one loses a session morning.
    """

    for name in ("rclpy", "cyclonedds", "unitree_sdk2py", "mcap"):
        assert not module_available(name), f"{name} must not be installed in this venv"

    missing = missing_dependencies(CHANNELS)
    assert missing, "on this box every transported channel is unavailable"
    assert "unitree_sdk2py" in {name for names in missing.values() for name in names}

    from scripts.parcel_capture.ingest import LIVE_ADAPTERS, DevicePresence

    states: dict[str, str] = {}
    for factory in LIVE_ADAPTERS:
        adapter = factory()
        dependency = adapter.dependency_report()
        device = adapter.device_report()
        if not dependency.satisfied:
            assert dependency.missing and dependency.remedy
            states[adapter.adapter_name] = "module_absent"
            continue
        # The module is here. Something else must still be missing, or this
        # host could read a live sensor — and it has none attached.
        assert device.presence is DevicePresence.ABSENT, (
            f"{adapter.adapter_name}: module present AND device present — this host "
            f"has hardware attached and cannot measure the hardwareless invariant"
        )
        assert device.remedy, "a device refusal with no remedy is one nobody can act on"
        states[adapter.adapter_name] = "device_absent"

    assert set(states) == {"dds", "realsense", "l2"}
    # And the two reasons are actually distinguished, not collapsed into one.
    assert states["dds"] == "module_absent"
    assert states["realsense"] == "device_absent"


def test_every_transport_declares_what_a_live_reader_would_need():
    """An unmapped transport must never read as 'nothing required'."""

    from parcel_robot.capture import Transport

    assert set(TRANSPORT_DEPENDENCIES) == set(Transport)
    assert set(TRANSPORT_EXECUTABLES) == set(Transport)
    for table in (TRANSPORT_DEPENDENCIES, TRANSPORT_EXECUTABLES):
        for names in table.values():
            for name in names:
                assert name in INSTALL_HINTS, name


def test_a_platform_tool_channel_is_probed_for_its_binary_not_just_a_module():
    """``tegrastats`` is an executable. A module-only probe would call a laptop
    READY for Orin telemetry, which is exactly the "unknown reads as ready"
    failure board rule 3 forbids."""

    entry = channel("orin.tegrastats")
    assert TRANSPORT_DEPENDENCIES[entry.transport] == ()
    assert TRANSPORT_EXECUTABLES[entry.transport] == ("tegrastats",)
    on_path = shutil.which("tegrastats") is not None
    assert ("tegrastats" in missing_requirements(entry)) is not on_path


def test_resolve_live_source_refuses_and_names_the_missing_module():
    with pytest.raises(LiveSourceUnavailableError) as excinfo:
        resolve_live_source(channel(LIDAR))
    message = str(excinfo.value)
    assert "rclpy" in message
    assert "NEVER into .parcel/" in message or "Orin" in message


def test_the_cli_refuses_cleanly_with_an_actionable_message_and_no_traceback(capsys):
    code = main(["--check"])
    captured = capsys.readouterr()

    assert code == 3
    assert "Traceback" not in captured.out + captured.err
    assert "REFUSED" in captured.err
    assert "Nothing was installed" in captured.err
    assert "UNAVAILABLE" in captured.out
    assert "mcap reference reader: ABSENT" in captured.out


def test_the_cli_gives_truncation_and_per_channel_loss_different_exit_codes(tmp_path, capsys):
    """Even the exit code refuses to conflate the two failures."""

    bag = _clean_bag(tmp_path / "clean.mcap", plan={LIDAR: 10.0}, duration_s=1.0)
    assert main(["--verify", str(bag)]) == 0
    assert "termination: clean" in capsys.readouterr().out

    dropping = _clean_bag(
        tmp_path / "dropping.mcap", plan={LIDAR: 10.0}, duration_s=1.0, drops=[(LIDAR, 4)]
    )
    assert main(["--verify", str(dropping)]) == 5
    out = capsys.readouterr().out
    assert "termination: clean" in out
    assert "PER-CHANNEL LOSS" in out
    assert "this is loss, not truncation" in out

    os.truncate(bag, read_mcap(bag).messages[-1].offset)
    assert main(["--verify", str(bag)]) == 4
    out = capsys.readouterr().out
    assert "termination: truncated" in out
    assert "recorder close record: ABSENT" in out
    assert "PER-CHANNEL LOSS" not in out


def test_the_cli_never_tracebacks_on_a_missing_or_bogus_bag(tmp_path, capsys):
    assert main(["--verify", str(tmp_path / "nope.mcap")]) == 2
    junk = tmp_path / "junk.mcap"
    junk.write_bytes(b"not a bag")
    assert main(["--verify", str(junk)]) == 2
    captured = capsys.readouterr()
    assert "Traceback" not in captured.out + captured.err
    assert captured.err.count("REFUSED") == 2


_FORBIDDEN_NAMES = frozenset(
    {
        "create_publisher",
        "Publisher",
        "ControlManager",
        "create_control_manager",
        "set_target",
        "acquire_lease",
        "Move",
        "SportClient",
    }
)
_FORBIDDEN_IMPORTS = ("unitree_sdk2py", "parcel_robot.control", "parcel_robot.runtime", "rclpy")


def test_nothing_in_these_scripts_can_arm_anything():
    """Board rule 1, enforced over this card's own AST.

    Module names appear here as STRING data — they are the refusal list — so
    the scan looks at imports and identifiers, never at literals, and the
    negative control below proves the distinction is real rather than lucky.
    """

    import ast

    for path in (
        REPO / "scripts" / "parcel_capture" / "record.py",
        REPO / "scripts" / "parcel_capture" / "sidecar.py",
    ):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert alias.name not in _FORBIDDEN_IMPORTS, f"{path.name}: {alias.name}"
            elif isinstance(node, ast.ImportFrom):
                assert (node.module or "") not in _FORBIDDEN_IMPORTS, f"{path.name}: {node.module}"
            elif isinstance(node, ast.Name):
                assert node.id not in _FORBIDDEN_NAMES, f"{path.name}: {node.id}"
            elif isinstance(node, ast.Attribute):
                assert node.attr not in _FORBIDDEN_NAMES, f"{path.name}: {node.attr}"

    # negative control: the scan really would fire on the real thing.
    mutant = ast.parse("client = ControlManager()\nclient.set_target(1.0)\n")
    hits = {
        node.id
        for node in ast.walk(mutant)
        if isinstance(node, ast.Name) and node.id in _FORBIDDEN_NAMES
    }
    assert hits == {"ControlManager"}


def test_the_scripts_declare_the_module_names_they_refuse_to_import():
    """Companion to the scan: the strings are present and are only strings."""

    source = (REPO / "scripts" / "parcel_capture" / "record.py").read_text(encoding="utf-8")
    assert "unitree_sdk2py" in source
    assert not re.search(r"^\s*import\s+unitree_sdk2py", source, re.MULTILINE)
    assert not re.search(r"^\s*from\s+unitree_sdk2py", source, re.MULTILINE)


def test_the_message_encoding_and_channel_metadata_are_pinned(tmp_path):
    """A bag six months old must be decodable without guessing its framing."""

    bag = _clean_bag(tmp_path / "clean.mcap", plan={LIDAR: 10.0}, duration_s=1.0)
    raw = bag.read_bytes()
    assert MESSAGE_ENCODING.encode() in raw
    assert CHANNEL_ID_METADATA_KEY.encode() in raw
    assert bytes([OP_MESSAGE]) in raw
    # The bag carries its own slice of the channel matrix, as JSON data.
    assert b'"channel_id":"go2.utlidar.cloud"' in raw
    assert b'"matrix_row":1' in raw
    assert b'"nominal_rate_hz":10.0' in raw
    assert b'"frame_id":"go2_utlidar_link"' in raw
