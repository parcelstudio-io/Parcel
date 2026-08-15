"""Card PS-A — channel matrix, ``CaptureEnvelope``, and per-channel sequence.

Provenance: ``scrum/20260813/task_1/README.md`` §PS-A,
``scrum/20260813/task_1/CHANNEL_MATRIX.md`` (the authoritative matrix: 25
channel rows expanding to 28 channels, plus 11 payload-field rows), and
``scrum/20260813/task_1/PHYSICAL_SESSION_PLAN.md`` (why the tranche exists).
The matrix cells were rewritten by card **PS-H** of the corrective tranche PS-2
against ``scrum/20260813/task_1/RISK_ASSESSMENT.md`` "Channel-matrix
corrections"; every cell below that pins an external claim also pins its
confidence marker, because a claim that arrives marked LIKELY and is stored
unmarked has been silently promoted to a fact. Precedents followed here:
``tests/test_w0a_physical_provenance.py::
test_evidence_origin_module_is_a_stdlib_only_leaf`` for the AST + subprocess
leaf pin, and ``tests/test_p4_place_graph.py`` for the import-graph pin idiom.

The defect under test is named and located: ``bags/recorder.py`` stamps
``sequence=self._sequence`` at line 98 and increments it at line 114 — ONE
counter for the whole bag, advanced only after a successful write. Every cell
below that claims per-channel sequencing works carries a seeded-failure
companion that runs the old scheme on the same data and shows it cannot see
what ours sees. A test that only asserts the fixed behaviour cannot tell you
the oracle would have caught the defect.
"""

from __future__ import annotations

import ast
import json
import subprocess
import sys
from pathlib import Path

import pytest

from parcel_robot.bags.recorder import BagRecorder
from parcel_robot.bags.schema import is_privileged_key, validate_topic
from parcel_robot.capture import (
    CHANNEL_MATRIX_ROWS,
    CHANNELS,
    CHANNELS_BY_ID,
    ENVELOPE_SCHEMA,
    MATRIX_ROW_TITLES,
    NON_SPATIAL_FRAME,
    UNCALIBRATED,
    CaptureEnvelope,
    CaptureError,
    CaptureRefusedError,
    Channel,
    ChannelHealth,
    ChannelPresence,
    ChannelSequenceBook,
    ChannelSequenceLedger,
    Criticality,
    RateKind,
    RefusalReason,
    SourceDevice,
    Transport,
    UnknownChannelError,
    canonical_json,
    channel,
    channel_ids,
    envelope_digest,
    select_channels,
)

# PS-H's additions live on the module rather than the package root: the package
# ``__init__`` is PS-A's surface and this card does not own it.
from parcel_robot.capture.channels import (
    DDS_ROS_TOPIC_PREFIX,
    DECLARATION_BASIS,
    FIELD_ROW_TITLES,
    MEASUREMENT_WINDOW,
    PAYLOAD_FIELD_ROWS,
    PAYLOAD_FIELDS,
    PAYLOAD_FIELDS_BY_ID,
    Confidence,
    PayloadField,
    SourceClock,
    UnknownPayloadFieldError,
    WireNaming,
    payload_field,
    payload_fields_of,
    subscribe_name,
)
from parcel_robot.evidence_origin import EvidenceOrigin

PACKAGE_DIR = Path(__file__).resolve().parents[1] / "src" / "parcel_robot" / "capture"

#: Two channels with very different rates and devices, used as the A/B pair in
#: the sequence cells. Both are LIVE and CRITICAL, so a drop on either is a
#: session-grade event rather than a curiosity.
CHANNEL_A = "go2.utlidar.cloud"
CHANNEL_B = "go2.lowstate"

NOW_MONO = 1_000_000_000
NOW_REAL = 1_786_000_000_000_000_000


def _package_sources() -> dict[Path, str]:
    sources = {
        path: path.read_text(encoding="utf-8") for path in sorted(PACKAGE_DIR.glob("*.py"))
    }
    assert {path.name for path in sources} == {
        "__init__.py",
        "channels.py",
        "envelope.py",
    }, f"unexpected package layout: {sorted(p.name for p in sources)}"
    return sources


def _stamp(book: ChannelSequenceBook, channel_id: str, tick: int) -> CaptureEnvelope:
    """One received message, sequenced at receipt."""

    return book.stamp(
        channel_id,
        host_monotonic_ns=NOW_MONO + tick,
        host_realtime_ns=NOW_REAL + tick,
        origin=EvidenceOrigin.PHYSICAL,
        source_timestamp_ns=NOW_MONO + tick - 500,
        health=ChannelHealth.NOMINAL,
    )


# ---------------------------------------------------------------------------
# GATE 1 — the matrix is transcribed completely, and the table refuses nonsense
# ---------------------------------------------------------------------------


def test_every_matrix_row_is_covered_and_no_channel_invents_a_row() -> None:
    """Coverage of CHANNEL_MATRIX.md table A, checked in both directions.

    THE COUNT, reconciled (RISK_ASSESSMENT.md correction 8). Three different
    numbers were in circulation — ``README.md:53`` said 15, the matrix had 19
    rows, PS-A built 22 channels — and each was answering a different question.
    They are now three named quantities and every document quotes all three:

    * 25 numbered channel rows in table A;
    * 28 channels, because rows 7, 14 and 15 each bundle two streams that
      arrive and drop separately ("lf/lowstate" + "lf/sportmodestate";
      "Infrared x2"; "accel + gyro");
    * 11 payload-field rows in table B, which are NOT channels.

    PS-A's expansion rule is the load-bearing half and it is pinned here:
    collapsing a bundled row back into one channel would reintroduce, at small
    scale, the exact defect this package exists to fix — a stereo pair sharing
    one counter cannot say which eye dropped.
    """

    assert len(MATRIX_ROW_TITLES) == CHANNEL_MATRIX_ROWS == 25
    covered = {entry.matrix_row for entry in CHANNELS}
    assert covered == set(MATRIX_ROW_TITLES), (
        f"rows with no channel: {sorted(set(MATRIX_ROW_TITLES) - covered)}; "
        f"channels citing a non-row: {sorted(covered - set(MATRIX_ROW_TITLES))}"
    )
    multi = {row for row in covered if sum(c.matrix_row == row for c in CHANNELS) > 1}
    assert multi == {7, 14, 15}, (
        "only the three rows that textually bundle two streams may expand; "
        f"got {sorted(multi)}"
    )
    assert len(CHANNELS) == 28


def test_the_channels_the_ps1_matrix_missed_are_all_present() -> None:
    """RISK_ASSESSMENT.md "Channels I missed entirely, all free".

    Each of these costs a second physical session to recover and there is no
    second session, so their presence is pinned by name rather than by count.
    The list is split by what they actually are: six are separate topics and
    therefore separate channels; the rest are FIELDS inside messages we were
    already recording, and minting those as channels would fabricate a
    sequence space for something that has no independent arrival.
    """

    added_channels = {
        "go2.utlidar.lidar_state",
        "go2.utlidar.cloud_deskewed",
        "go2.utlidar.robot_odom",
        "go2.utlidar.switch",
        "go2.front_camera_h264",
        "go2.uwbstate",
    }
    assert added_channels <= set(CHANNELS_BY_ID)

    added_fields = {
        "go2.sportmodestate.range_obstacle",
        "go2.lowstate.power_v_power_a",
        "go2.lowstate.wireless_remote",
        "go2.lowstate.fan_frequency",
        "go2.lowstate.temperature_ntc",
    }
    assert added_fields <= set(PAYLOAD_FIELDS_BY_ID)
    # ... and none of them became a channel with a sequence space of its own.
    assert not added_fields & set(CHANNELS_BY_ID)

    # lidar_state is the row that settles L1-vs-L2 electronically, so it must
    # not be an optional extra that a bandwidth trim quietly drops.
    assert channel("go2.utlidar.lidar_state").criticality is Criticality.IMPORTANT


def test_every_payload_field_row_is_covered_and_names_a_real_parent() -> None:
    """Table B coverage, in both directions, plus the parent join.

    A field of record is only meaningful if the message it rides in is being
    recorded — so every parent must be a channel, and asking for the fields of
    a channel that does not exist is a refusal rather than an empty tuple.
    """

    assert len(FIELD_ROW_TITLES) == PAYLOAD_FIELD_ROWS == 11
    assert len(PAYLOAD_FIELDS) == 11
    assert {f.matrix_field_row for f in PAYLOAD_FIELDS} == set(FIELD_ROW_TITLES)
    for entry in PAYLOAD_FIELDS:
        assert entry.parent_channel_id in CHANNELS_BY_ID
        assert entry.field_id.startswith(entry.parent_channel_id + ".")
        assert payload_field(entry.field_id) is entry
        assert isinstance(entry.confidence, Confidence)
        assert entry.spec.strip() and entry.note.strip()

    assert len(payload_fields_of("go2.lowstate")) == 9
    assert len(payload_fields_of("go2.sportmodestate")) == 2
    assert payload_fields_of("d455.color") == ()

    with pytest.raises(UnknownChannelError):
        payload_fields_of("go2.nope")
    with pytest.raises(UnknownPayloadFieldError):
        payload_field("go2.lowstate.voltage")  # the field BmsState does not have


def test_channel_ids_are_unique_stable_and_usable_as_bag_topics() -> None:
    """PS-B needs one string per channel that ``bags/schema.py`` accepts."""

    ids = channel_ids()
    assert len(set(ids)) == len(ids) == len(CHANNELS)
    assert set(ids) == set(CHANNELS_BY_ID)
    for entry in CHANNELS:
        validate_topic(entry.bag_topic)  # raises BagSchemaError if unusable
        assert not is_privileged_key(entry.bag_topic.replace("/", "_"))
        assert channel(entry.channel_id) is entry


def test_every_channel_carries_a_complete_declaration() -> None:
    for entry in CHANNELS:
        assert isinstance(entry.device, SourceDevice)
        assert isinstance(entry.transport, Transport)
        assert isinstance(entry.criticality, Criticality)
        assert isinstance(entry.presence, ChannelPresence)
        assert isinstance(entry.rate_kind, RateKind)
        assert isinstance(entry.source_clock, SourceClock)
        assert isinstance(entry.confidence, Confidence)
        assert entry.human_name.strip()
        assert entry.address.strip()
        assert entry.message_type.strip()
        assert entry.frame_id.strip()
        assert entry.note.strip(), f"{entry.channel_id} must say why it is here"
        # A rate expectation exists if and only if the device fixes the rate.
        if entry.rate_kind is RateKind.PERIODIC:
            assert isinstance(entry.nominal_rate_hz, float) and entry.nominal_rate_hz > 0
        else:
            assert entry.nominal_rate_hz is None


def test_the_table_says_where_its_facts_came_from_and_when_they_expire() -> None:
    """RISK_ASSESSMENT.md's own closing paragraph, enforced in the data.

    Every external claim in this table is "true of Go2 EDUs described online",
    not of our unit. Two module constants carry that, so a consumer six months
    from now reads the provenance off the table instead of inferring it, and no
    row can be born as an unmarked fact.
    """

    assert DECLARATION_BASIS == "documentation_derived"
    assert MEASUREMENT_WINDOW == "session_first_45_minutes"
    assert {c.confidence for c in CHANNELS} <= set(Confidence)
    # The corrections that arrived marked LIKELY are still marked LIKELY.
    assert channel("go2.utlidar.robot_pose").confidence is Confidence.LIKELY
    assert channel("go2.sportmodestate").confidence is Confidence.LIKELY
    assert channel("uwb.owner_fob").confidence is Confidence.UNVERIFIED
    # ... and the ones with a message definition behind them say CONFIRMED.
    assert channel("go2.front_camera").confidence is Confidence.CONFIRMED
    assert channel("go2.lowstate").confidence is Confidence.CONFIRMED


def test_non_spatial_channels_are_exactly_the_four_that_carry_no_geometry() -> None:
    """A frame that silently means ``base_link`` is how frames get lost."""

    non_spatial = {c.channel_id for c in CHANNELS if c.frame_id == NON_SPATIAL_FRAME}
    assert non_spatial == {
        "go2.wirelesscontroller",
        "orin.tegrastats",
        "go2.utlidar.lidar_state",
        "go2.utlidar.switch",
    }
    assert all(c.is_spatial for c in CHANNELS if c.channel_id not in non_spatial)


def test_presence_fails_closed_where_the_matrix_hedges() -> None:
    """Board rule 3: unknown is absent, so "LIVE if published" is not LIVE.

    ``CHANNEL_MATRIX.md`` transcribes ``utlidar/imu`` as "LIVE if published".
    A conditional is not a confirmation, and the whole point of the presence
    column is to tell PS-D what still needs proving.
    """

    assert channel("go2.utlidar.imu").presence is ChannelPresence.CONFIRM_ON_HAND
    unconfirmed = {
        c.channel_id for c in select_channels(presence=ChannelPresence.CONFIRM_ON_HAND)
    }
    assert unconfirmed == {
        "go2.utlidar.imu",
        "gnss.zed_f9p",
        "uwb.owner_fob",
        "go2.uwbstate",
    }
    awaiting = {
        c.channel_id for c in select_channels(presence=ChannelPresence.AWAITING_HARDWARE)
    }
    assert awaiting == {"mic.xvf3800"}
    # The free vendor baselines the plan says Sol never mentioned are recorded.
    assert {"go2.utlidar.robot_pose", "go2.utlidar.voxel_map", "go2.lowstate"} <= set(
        CHANNELS_BY_ID
    )


def test_service_gated_rows_are_not_live_and_say_so_in_their_own_state() -> None:
    """RISK_ASSESSMENT.md correction 2, and the reason it needed a new state.

    ``sportmodestate``, ``utlidar/robot_pose``, ``utlidar/voxel_map_compressed``
    and ``utlidar/robot_odom`` are produced by on-robot SERVICES, not by sensor
    firmware. The topic can exist, advertise a publisher, and emit nothing —
    which at the DDS layer is indistinguishable from a bad network config, and
    a first-hand report of exactly that exists for a shipping unit. Folding
    them into ``CONFIRM_ON_HAND`` would have said "the box might not be in the
    room", which is a different and wrong diagnosis, so they carry their own
    state and PS-D triages them differently.
    """

    gated = {
        c.channel_id for c in select_channels(presence=ChannelPresence.VERIFY_IN_SESSION)
    }
    assert {
        "go2.sportmodestate",
        "go2.lf.sportmodestate",
        "go2.utlidar.robot_pose",
        "go2.utlidar.voxel_map",
        "go2.utlidar.robot_odom",
    } <= gated
    assert ChannelPresence.VERIFY_IN_SESSION is not ChannelPresence.CONFIRM_ON_HAND
    for channel_id in ("go2.sportmodestate", "go2.utlidar.robot_pose"):
        assert channel(channel_id).presence is not ChannelPresence.LIVE
    # The mutual-exclusion question is recorded as a QUESTION, not as a plan:
    # running our own SLAM plausibly needs the built-in obstacle avoidance off,
    # and that is what drives these same outputs. The "free vendor baseline"
    # and "our own SLAM" may therefore not be obtainable in the same take.
    anchor = channel("go2.utlidar.robot_pose").note.lower()
    assert "obstacle avoidance" in anchor
    assert "open question" in anchor
    for channel_id in ("go2.utlidar.voxel_map", "go2.utlidar.robot_odom"):
        assert "obstacle-avoidance-off question" in channel(channel_id).note.lower()


def test_every_dds_row_carries_both_names_and_nothing_else_carries_one() -> None:
    """RISK_ASSESSMENT.md correction 4: the ``rt/`` mangling, made unmissable.

    On the raw DDS wire every ROS topic is ``rt/<name>``. A raw-DDS subscriber
    on the unmangled name receives ZERO MESSAGES AND NO ERROR — it looks
    exactly like a robot that is not publishing, which on a one-session day
    buys hours of debugging aimed at the wrong layer. So both names live on
    every DDS row, and no non-DDS row may carry one (an L2 over UDP has no
    topic name to mangle, and pretending it does would answer a question that
    was never asked).
    """

    dds = select_channels(transport=Transport.DDS)
    assert len(dds) == 15
    for entry in dds:
        assert entry.wire_address == DDS_ROS_TOPIC_PREFIX + entry.address
        assert not entry.address.startswith(DDS_ROS_TOPIC_PREFIX)
        assert subscribe_name(entry.channel_id, WireNaming.ROS2) == entry.address
        assert subscribe_name(entry.channel_id, WireNaming.RAW_DDS) == entry.wire_address
    for entry in CHANNELS:
        if entry.transport is not Transport.DDS:
            assert entry.wire_address is None

    assert subscribe_name("go2.lowstate", WireNaming.RAW_DDS) == "rt/lowstate"
    assert subscribe_name("go2.utlidar.cloud", WireNaming.RAW_DDS) == "rt/utlidar/cloud"


def test_seeded_failure_the_wire_naming_cannot_be_guessed_or_defaulted() -> None:
    """The silent failure, refuted three ways.

    1. There is no default for ``naming``: a caller that has not decided which
       stack it is on cannot get an answer at all.
    2. A bare string does not select the wire — the same fail-closed rule
       ``select_channels`` uses.
    3. A non-DDS channel refuses rather than handing back its ``address``,
       which would let a caller believe the question had been answered.
    """

    import inspect

    signature = inspect.signature(subscribe_name)
    assert signature.parameters["naming"].default is inspect.Parameter.empty

    with pytest.raises(TypeError):
        subscribe_name("go2.lowstate")  # type: ignore[call-arg]
    with pytest.raises(CaptureError, match="WireNaming member"):
        subscribe_name("go2.lowstate", "raw_dds")  # type: ignore[arg-type]
    with pytest.raises(CaptureError, match="not addressed by topic name"):
        subscribe_name("l2.cloud", WireNaming.RAW_DDS)
    with pytest.raises(UnknownChannelError):
        subscribe_name("go2.lowstat", WireNaming.RAW_DDS)

    # And the table itself cannot be edited into the silent state: a DDS row
    # whose wire name is not the mangled ROS name is a construction refusal.
    base = {
        "channel_id": "go2.test",
        "human_name": "test",
        "device": SourceDevice.GO2,
        "transport": Transport.DDS,
        "address": "test/topic",
        "wire_address": "rt/test/topic",
        "message_type": "test/Type",
        "rate_kind": RateKind.PERIODIC,
        "nominal_rate_hz": 10.0,
        "source_clock": SourceClock.ABSENT,
        "frame_id": "base_link",
        "criticality": Criticality.OPPORTUNISTIC,
        "presence": ChannelPresence.LIVE,
        "confidence": Confidence.LIKELY,
        "matrix_row": 1,
        "note": "test",
    }
    Channel(**base)  # the control
    with pytest.raises(CaptureError, match="wire_address must be"):
        Channel(**{**base, "wire_address": None})
    with pytest.raises(CaptureError, match="wire_address must be"):
        Channel(**{**base, "wire_address": "test/topic"})  # unmangled: the trap
    with pytest.raises(CaptureError, match="is the raw-DDS name"):
        Channel(**{**base, "address": "rt/test/topic"})
    with pytest.raises(CaptureError, match="wire_address is DDS-only"):
        Channel(**{**base, "transport": Transport.SERIAL})


def test_the_payload_clock_is_declared_per_channel_and_lowstate_has_none() -> None:
    """RISK_ASSESSMENT.md correction 8, which is what redesigns the clock card.

    ``LowState`` — the 500 Hz IMU channel, the densest and most valuable stream
    on the dog — carries NO timestamp field. Only ``tick``, a ``uint32``
    millisecond counter that wraps. ``SportModeState.stamp`` is the only real
    source-clock anchor the robot emits, and it arrives on a SERVICE-GATED
    channel. Declaring this per channel is what lets PS-I know, before the
    session, which streams it can fit an offset against and which ones the
    physical sync ritual is the only evidence for.
    """

    assert channel("go2.lowstate").source_clock is SourceClock.WRAPPING_COUNTER
    assert not channel("go2.lowstate").carries_a_time_anchor
    assert channel("go2.lf.lowstate").source_clock is SourceClock.WRAPPING_COUNTER
    assert channel("go2.sportmodestate").source_clock is SourceClock.DEVICE_TIMESPEC
    assert channel("go2.sportmodestate").carries_a_time_anchor
    assert payload_field("go2.lowstate.tick").spec.startswith("uint32")
    assert "wrap" in payload_field("go2.lowstate.tick").note.lower()

    # A counter is never an anchor, and neither is an unread field.
    assert not SourceClock.WRAPPING_COUNTER.is_usable_anchor
    assert not SourceClock.UNVERIFIED.is_usable_anchor
    assert not SourceClock.ABSENT.is_usable_anchor
    assert SourceClock.DEVICE_TIMESPEC.is_usable_anchor

    # The RealSense streams are UNVERIFIED, not assumed good: the pip wheel is
    # reported to cost the UVC per-frame metadata PS-I depends on.
    for channel_id in ("d455.color", "d455.depth", "d455.accel", "d455.gyro"):
        assert channel(channel_id).source_clock is SourceClock.UNVERIFIED

    anchors = {c.channel_id for c in CHANNELS if c.carries_a_time_anchor}
    assert "go2.lowstate" not in anchors
    assert "orin.tegrastats" not in anchors


def test_the_two_imu_pathologies_the_plausibility_gate_exists_for_are_recorded() -> None:
    """RISK_ASSESSMENT.md correction 9 / change 4: arrival is not health.

    ``utlidar/imu`` has two independent reports of emitting ~1e24 m/s^2, which
    a receipt-count probe attests as healthy. The matrix cannot fix that — only
    PS-J's physical-plausibility assertion can — but it must hand PS-J the
    warning rather than leaving it in a research document.
    """

    entry = channel("go2.utlidar.imu")
    assert entry.presence is ChannelPresence.CONFIRM_ON_HAND
    assert "1e24" in entry.note
    assert "9.81" in entry.note


def test_seeded_failure_the_table_refuses_a_malformed_channel() -> None:
    """Mutants that a hand-maintained table really does grow."""

    good = channel(CHANNEL_A)
    base = {
        "channel_id": "go2.test",
        "human_name": "test",
        "device": SourceDevice.GO2,
        "transport": Transport.DDS,
        "address": "test/topic",
        "wire_address": "rt/test/topic",
        "message_type": "test/Type",
        "rate_kind": RateKind.PERIODIC,
        "nominal_rate_hz": 10.0,
        "source_clock": SourceClock.ABSENT,
        "frame_id": "base_link",
        "criticality": Criticality.OPPORTUNISTIC,
        "presence": ChannelPresence.LIVE,
        "confidence": Confidence.LIKELY,
        "matrix_row": 1,
        "note": "test",
    }
    Channel(**base)  # the control: the shape is otherwise valid

    with pytest.raises(CaptureError, match="dotted"):
        Channel(**{**base, "channel_id": "flat"})
    with pytest.raises(CaptureError, match="lowercase"):
        Channel(**{**base, "channel_id": "GO2.Test"})
    with pytest.raises(CaptureError, match="not a row"):
        Channel(**{**base, "matrix_row": 26})
    with pytest.raises(CaptureError, match="note must be non-empty"):
        Channel(**{**base, "note": "   "})
    # A rate nobody chose is not an expectation.
    with pytest.raises(CaptureError, match="must not carry a nominal_rate_hz"):
        Channel(**{**base, "rate_kind": RateKind.CONFIGURED})
    with pytest.raises(CaptureError, match="finite positive"):
        Channel(**{**base, "nominal_rate_hz": float("inf")})
    with pytest.raises(CaptureError, match="finite positive"):
        Channel(**{**base, "nominal_rate_hz": float("nan")})
    # An external claim smuggled in without its confidence marker, and a
    # payload clock nobody declared, are both refusals: an unmarked claim reads
    # as a fact, and an undeclared clock is how a null timestamp becomes an
    # assumed one.
    with pytest.raises(CaptureError, match="confidence must be a Confidence"):
        Channel(**{**base, "confidence": "confirmed"})
    with pytest.raises(CaptureError, match="confidence must be a Confidence"):
        Channel(**{**base, "confidence": None})
    with pytest.raises(CaptureError, match="source_clock must be a SourceClock"):
        Channel(**{**base, "source_clock": "device_timespec"})
    with pytest.raises(CaptureError, match="source_clock must be a SourceClock"):
        Channel(**{**base, "source_clock": None})
    # ... and the real table is untouched by any of that.
    assert channel(CHANNEL_A) is good


def test_seeded_failure_the_field_table_refuses_a_malformed_row() -> None:
    """A field of record that cannot be joined back to its message is noise."""

    base = {
        "field_id": "go2.lowstate.test",
        "human_name": "test",
        "parent_channel_id": "go2.lowstate",
        "spec": "uint8[4]",
        "confidence": Confidence.LIKELY,
        "matrix_field_row": 1,
        "note": "test",
    }
    PayloadField(**base)  # the control

    with pytest.raises(CaptureError, match="must be dotted under its parent"):
        PayloadField(**{**base, "parent_channel_id": "go2.sportmodestate"})
    with pytest.raises(CaptureError, match="lowercase"):
        PayloadField(**{**base, "field_id": "GO2.lowstate.Test"})
    with pytest.raises(CaptureError, match="not a table-B row"):
        PayloadField(**{**base, "matrix_field_row": 12})
    with pytest.raises(CaptureError, match="spec must be non-empty"):
        PayloadField(**{**base, "spec": " "})
    with pytest.raises(CaptureError, match="confidence must be a Confidence"):
        PayloadField(**{**base, "confidence": "likely"})


def test_seeded_failure_an_unknown_channel_id_is_absent_not_new() -> None:
    """A typo at 03:00 on a session morning must not mint a stream."""

    with pytest.raises(UnknownChannelError, match="unknown channel_id"):
        channel("go2.lowstat")
    with pytest.raises(UnknownChannelError):
        channel("")
    with pytest.raises(UnknownChannelError):
        channel(None)  # type: ignore[arg-type]
    with pytest.raises(UnknownChannelError):
        ChannelSequenceBook().next_sequence("d455.colour")


def test_select_channels_never_widens_on_a_malformed_filter() -> None:
    assert select_channels() == CHANNELS
    with pytest.raises(CaptureError, match="raw string"):
        select_channels(presence="live")  # type: ignore[arg-type]
    with pytest.raises(CaptureError, match="non-empty"):
        select_channels(device=[])
    with pytest.raises(CaptureError, match="non-empty"):
        select_channels(criticality=[ChannelPresence.LIVE])  # type: ignore[list-item]
    with pytest.raises(CaptureError, match="raw string"):
        select_channels(transport="dds")  # type: ignore[arg-type]
    assert len(select_channels(criticality=Criticality.CRITICAL)) == 6
    assert len(select_channels(transport=Transport.DDS)) == 15
    assert len(select_channels(device=SourceDevice.D455)) == 6


# ---------------------------------------------------------------------------
# GATE 2 — per-channel sequence, and the two refutations of the global scheme
# ---------------------------------------------------------------------------
#
# The receipt schedule below is shared by every cell in this section so the
# three schemes are compared on identical data. ``WRITER_DROPS`` are messages
# the capture process RECEIVED and then failed to write — the failure mode a
# recorder can actually observe. (A message lost in transit was never
# sequenced by us and is out of scope; see the module docstring of
# ``parcel_robot.capture.envelope``.)

#: 20 receipts, alternating, with channel A's 4th/5th/6th receipts lost by the
#: writer. Indices are into the per-channel production order.
_RECEIPTS: tuple[tuple[str, int], ...] = tuple(
    item
    for pair in ((CHANNEL_A, i) for i in range(10))
    for item in (pair, (CHANNEL_B, pair[1]))
)
_WRITER_DROPS = frozenset({(CHANNEL_A, 3), (CHANNEL_A, 4), (CHANNEL_A, 5)})


def _world_writer_lost_three() -> list[CaptureEnvelope]:
    """World 1: channel A published 10 messages and the writer lost 3.

    All 20 receipts are stamped — the sequence is minted in the reader, before
    anything can fail — and 17 reach the record.
    """

    book = ChannelSequenceBook()
    written: list[CaptureEnvelope] = []
    for tick, (channel_id, index) in enumerate(_RECEIPTS):
        envelope = _stamp(book, channel_id, tick)
        if (channel_id, index) not in _WRITER_DROPS:
            written.append(envelope)
    return written


def _world_sensor_published_three_fewer() -> list[CaptureEnvelope]:
    """World 2: channel A only ever published 7. Nothing was lost.

    The three messages are never received, so they are never stamped and A's
    number line is 0..6 with no hole. Same 17 messages reach the record, in the
    same order, at the same host clocks.
    """

    book = ChannelSequenceBook()
    written: list[CaptureEnvelope] = []
    for tick, (channel_id, index) in enumerate(_RECEIPTS):
        if (channel_id, index) in _WRITER_DROPS:
            continue
        written.append(_stamp(book, channel_id, tick))
    return written


def test_per_channel_sequence_attributes_a_drop_to_exactly_one_channel() -> None:
    """The card's headline gate: A drops 3 while B is continuous."""

    written = _world_writer_lost_three()
    assert len(_RECEIPTS) == 20 and len(written) == 17

    ledger = ChannelSequenceLedger()
    ledger.observe_all(written)
    report = ledger.report()

    assert set(report) == {CHANNEL_A, CHANNEL_B}
    a_report = report[CHANNEL_A]
    b_report = report[CHANNEL_B]

    assert a_report.missing == (3, 4, 5)
    assert a_report.missing_count == 3
    assert a_report.received == 7
    assert a_report.first_sequence == 0 and a_report.last_sequence == 9
    assert a_report.has_gap and not a_report.is_clean

    assert b_report.missing == () and b_report.missing_count == 0
    assert b_report.received == 10
    assert b_report.is_clean, "the continuous channel must not be implicated"

    # And the report is JSON-safe for the PS-B sidecar.
    assert json.loads(json.dumps(ledger.to_dict()))[CHANNEL_A]["missing"] == [3, 4, 5]


def test_seeded_failure_the_shipped_global_recorder_cannot_see_the_drop_at_all(
    tmp_path,
) -> None:
    """The mutant is the shipped ``bags/recorder.py``, run for real.

    Its counter is minted AFTER a successful write (``recorder.py:114``), so a
    message that is never written leaves no hole. Two worlds are constructed —
    one where channel A published 10 and the writer lost 3, one where A only
    ever published 7 — and the resulting bags are shown to be IDENTICAL in
    topic order and sequence. No function of that bag can tell a dropped
    message from a slow sensor, which is precisely the evidence the physical
    session needs and would not have had.
    """

    def _record_world(name: str, envelopes: list[CaptureEnvelope]) -> list[dict]:
        recorder = BagRecorder(
            tmp_path / name,
            bag_id=f"ps-a-{name}",
            source="sim",
            topics=[channel(CHANNEL_A).bag_topic, channel(CHANNEL_B).bag_topic],
        )
        for envelope in envelopes:
            recorder.record(
                envelope.channel.bag_topic,
                {"tick": envelope.host_monotonic_ns},
                source="ps-a-refutation",
                source_timestamp_ns=envelope.source_timestamp_ns or 0,
                received_monotonic_ns=envelope.host_monotonic_ns,
                frame_id=envelope.frame_id,
                # Identical across worlds on purpose: the comparison below is
                # about what the SCHEME records, not about bag identifiers.
                evidence_id=f"{envelope.channel_id}@{envelope.host_monotonic_ns}",
            )
        recorder.close()
        lines = (recorder.bag_dir / "messages.jsonl").read_text(encoding="utf-8")
        return [json.loads(line) for line in lines.splitlines()]

    dropped = _world_writer_lost_three()
    slow_sensor = _world_sensor_published_three_fewer()
    assert len(dropped) == len(slow_sensor) == 17

    world_dropped = _record_world("dropped", dropped)
    world_slow_sensor = _record_world("slow", slow_sensor)

    # The two bags are IDENTICAL, message for message. The global counter runs
    # 0..16 in both, because it only ever counts successful writes.
    assert world_dropped == world_slow_sensor
    assert [m["envelope"]["sequence"] for m in world_dropped] == list(range(17))

    def loss_is_visible_oracle(records: list[dict]) -> None:
        sequences = sorted(m["envelope"]["sequence"] for m in records)
        assert sequences != list(range(len(sequences))), "no evidence of loss"

    with pytest.raises(AssertionError, match="no evidence of loss"):
        loss_is_visible_oracle(world_dropped)

    # The same two worlds, under the per-channel scheme, are distinguishable:
    # the drop is attributed to A, and the slow sensor is clean.
    def _report(envelopes: list[CaptureEnvelope]) -> dict:
        ledger = ChannelSequenceLedger()
        ledger.observe_all(envelopes)
        return ledger.report()

    assert _report(dropped)[CHANNEL_A].missing == (3, 4, 5)
    assert _report(slow_sensor)[CHANNEL_A].missing == ()
    assert _report(slow_sensor)[CHANNEL_A].last_sequence == 6
    assert _report(slow_sensor)[CHANNEL_A].is_clean


def test_seeded_failure_a_receipt_assigned_global_counter_still_cannot_attribute() -> None:
    """A strictly stronger mutant, and it still loses the attribution.

    Move the global counter to receipt time — the obvious "fix" — and a gap
    does appear. It still names no channel: two worlds are built whose written
    records are byte-identical (same topics, same global sequences) but in
    which the lost messages belonged to DIFFERENT channels. The per-channel
    ledger separates them; the global gap cannot, because the evidence that
    would distinguish them is exactly what was lost.
    """

    head = [CHANNEL_A, CHANNEL_B, CHANNEL_A, CHANNEL_B]
    tail = [CHANNEL_A, CHANNEL_B, CHANNEL_A, CHANNEL_B]
    world_a_lost = head + [CHANNEL_A, CHANNEL_A] + tail
    world_b_lost = head + [CHANNEL_B, CHANNEL_B] + tail
    lost_positions = {4, 5}  # the two receipts the writer drops, in both worlds

    def run(schedule: list[str]) -> tuple[list[tuple[str, int]], list[CaptureEnvelope]]:
        book = ChannelSequenceBook()
        global_written: list[tuple[str, int]] = []
        per_channel_written: list[CaptureEnvelope] = []
        for position, channel_id in enumerate(schedule):
            envelope = _stamp(book, channel_id, position)
            if position in lost_positions:
                continue
            global_written.append((channel_id, position))  # receipt-assigned
            per_channel_written.append(envelope)
        return global_written, per_channel_written

    global_a, per_channel_a = run(world_a_lost)
    global_b, per_channel_b = run(world_b_lost)

    # The receipt-assigned global record is identical in both worlds: same
    # topic at every surviving position, same global sequence, same gap.
    assert global_a == global_b
    assert [pos for _c, pos in global_a] == [0, 1, 2, 3, 6, 7, 8, 9]

    def attribution_oracle(reports: dict, expected_owner: str) -> None:
        gapped = {cid for cid, rep in reports.items() if rep.has_gap}
        assert gapped == {expected_owner}, f"loss attributed to {gapped}"

    ledger_a = ChannelSequenceLedger()
    ledger_a.observe_all(per_channel_a)
    ledger_b = ChannelSequenceLedger()
    ledger_b.observe_all(per_channel_b)

    attribution_oracle(ledger_a.report(), CHANNEL_A)
    attribution_oracle(ledger_b.report(), CHANNEL_B)

    # The global record cannot answer the question at all: identical evidence,
    # two different owners. Feeding it to the oracle is a coin flip.
    assert global_a == global_b
    with pytest.raises(AssertionError):
        attribution_oracle(ledger_a.report(), CHANNEL_B)


def test_the_ledger_makes_a_silent_channel_visible_when_it_is_expected() -> None:
    """A channel missing from a report is the easiest loss to overlook."""

    book = ChannelSequenceBook()
    ledger = ChannelSequenceLedger()
    for tick in range(4):
        ledger.observe(_stamp(book, CHANNEL_B, tick))

    bare = ledger.report()
    assert CHANNEL_A not in bare  # total silence leaves no trace by itself

    watched = ledger.report(expected=[CHANNEL_A, CHANNEL_B])
    assert watched[CHANNEL_A].received == 0
    assert watched[CHANNEL_A].first_sequence is None
    assert watched[CHANNEL_A].last_sequence is None
    assert not watched[CHANNEL_A].has_gap  # nothing was minted, so nothing is lost
    assert watched[CHANNEL_B].received == 4

    with pytest.raises(UnknownChannelError):
        ledger.report(expected=["not.a.channel"])


def test_duplicates_and_late_arrivals_are_classified_apart_from_loss() -> None:
    """A re-delivered message is not a drop, and a late one is not a loss."""

    book = ChannelSequenceBook()
    stream = [_stamp(book, CHANNEL_A, tick) for tick in range(6)]

    ledger = ChannelSequenceLedger()
    # 0 1 2 [skip 3] 4 5, then 3 arrives late, then 5 is re-delivered.
    ledger.observe_all([stream[0], stream[1], stream[2], stream[4], stream[5]])
    interim = ledger.report()[CHANNEL_A]
    assert interim.missing == (3,) and interim.out_of_order == 0

    ledger.observe(stream[3])
    ledger.observe(stream[5])
    final = ledger.report()[CHANNEL_A]

    assert final.missing == () and final.missing_count == 0
    assert final.out_of_order == 1
    assert final.duplicated == (5,) and final.duplicate_count == 1
    assert final.received == 7
    assert not final.is_clean


def test_sequences_are_per_channel_and_independent_from_the_first_message() -> None:
    book = ChannelSequenceBook()
    assert book.issued(CHANNEL_A) == 0
    first_a = _stamp(book, CHANNEL_A, 0)
    first_b = _stamp(book, CHANNEL_B, 1)
    second_a = _stamp(book, CHANNEL_A, 2)

    assert (first_a.sequence, first_b.sequence, second_a.sequence) == (0, 0, 1)
    assert book.issued(CHANNEL_A) == 2 and book.issued(CHANNEL_B) == 1
    # A global counter would have produced 0, 1, 2 here — the difference is the
    # whole card.
    assert [first_a.sequence, first_b.sequence, second_a.sequence] != [0, 1, 2]


def test_a_huge_sequence_jump_is_counted_exactly_without_a_huge_set() -> None:
    """Memory is bounded by loss, and the count stays exact past the bound."""

    from parcel_robot.capture.envelope import MISSING_TRACKING_CAP

    ledger = ChannelSequenceLedger()
    ledger.observe(
        CaptureEnvelope(
            channel_id=CHANNEL_A,
            sequence=0,
            source_timestamp_ns=None,
            host_monotonic_ns=NOW_MONO,
            host_realtime_ns=NOW_REAL,
            frame_id=channel(CHANNEL_A).frame_id,
            origin=EvidenceOrigin.PHYSICAL,
        )
    )
    ledger.observe(
        CaptureEnvelope(
            channel_id=CHANNEL_A,
            sequence=10_000_000,
            source_timestamp_ns=None,
            host_monotonic_ns=NOW_MONO,
            host_realtime_ns=NOW_REAL,
            frame_id=channel(CHANNEL_A).frame_id,
            origin=EvidenceOrigin.PHYSICAL,
        )
    )
    report = ledger.report()[CHANNEL_A]
    assert report.missing_count == 9_999_999
    assert report.missing_truncated
    assert len(report.missing) == MISSING_TRACKING_CAP


# ---------------------------------------------------------------------------
# GATE 3 — every field round-trips to a JSON-safe dict and back, byte-stable
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("channel_id", channel_ids())
def test_every_channel_round_trips_byte_stably(channel_id: str) -> None:
    entry = channel(channel_id)
    envelope = CaptureEnvelope(
        channel_id=channel_id,
        sequence=7,
        source_timestamp_ns=None if entry.device is SourceDevice.ORIN else 12_345,
        host_monotonic_ns=NOW_MONO,
        host_realtime_ns=NOW_REAL,
        frame_id=entry.frame_id,
        origin=EvidenceOrigin.PHYSICAL,
        calibration_ref="ps-a-selftest",
        health=ChannelHealth.NOMINAL,
    )

    first = canonical_json(envelope)
    decoded = CaptureEnvelope.from_dict(json.loads(first))
    assert decoded == envelope
    assert canonical_json(decoded) == first  # byte-stable, not merely equal
    assert envelope_digest(decoded) == envelope_digest(envelope)
    # Every value in the dict is JSON-native; nothing leaks an enum object.
    for value in envelope.to_dict().values():
        assert value is None or isinstance(value, (str, int))
    assert envelope.to_dict()["schema"] == ENVELOPE_SCHEMA
    assert envelope.to_dict()["origin"] == "physical"


def test_the_digest_moves_when_any_field_moves() -> None:
    base = _stamp(ChannelSequenceBook(), CHANNEL_A, 0)
    digests = {envelope_digest(base)}
    from dataclasses import replace

    for change in (
        {"sequence": 1},
        {"source_timestamp_ns": None},
        {"host_monotonic_ns": NOW_MONO + 1},
        {"host_realtime_ns": NOW_REAL + 1},
        {"calibration_ref": "other"},
        {"health": ChannelHealth.DEGRADED},
        {"channel_id": CHANNEL_B, "frame_id": channel(CHANNEL_B).frame_id},
    ):
        digests.add(envelope_digest(replace(base, **change)))
    assert len(digests) == 8


def test_seeded_failure_a_malformed_record_is_refused_not_defaulted() -> None:
    """Board rule 3: a malformed input is a refusal, never a default."""

    good = _stamp(ChannelSequenceBook(), CHANNEL_A, 0).to_dict()
    assert CaptureEnvelope.from_dict(good)  # the control

    def _refused(record: object, reason: RefusalReason) -> None:
        with pytest.raises(CaptureRefusedError) as caught:
            CaptureEnvelope.from_dict(record)  # type: ignore[arg-type]
        assert caught.value.reason is reason

    _refused({k: v for k, v in good.items() if k != "sequence"},
             RefusalReason.MALFORMED_RECORD)
    _refused({**good, "surprise": 1}, RefusalReason.MALFORMED_RECORD)
    _refused({**good, "schema": "parcel.capture.envelope.v2"},
             RefusalReason.SCHEMA_MISMATCH)
    _refused({**good, "origin": "definitely_physical"}, RefusalReason.MALFORMED_RECORD)
    _refused({**good, "health": "fine"}, RefusalReason.MALFORMED_RECORD)
    _refused([good], RefusalReason.MALFORMED_RECORD)

    # Clocks: nanosecond integers or nothing. No rounding, no coercion.
    _refused({**good, "host_monotonic_ns": 1.5}, RefusalReason.NON_INTEGER_FIELD)
    _refused({**good, "host_monotonic_ns": float("nan")}, RefusalReason.NON_INTEGER_FIELD)
    _refused({**good, "host_realtime_ns": True}, RefusalReason.NON_INTEGER_FIELD)
    _refused({**good, "host_realtime_ns": "1786000000"}, RefusalReason.NON_INTEGER_FIELD)
    _refused({**good, "host_realtime_ns": None}, RefusalReason.NON_INTEGER_FIELD)
    _refused({**good, "source_timestamp_ns": 1.0}, RefusalReason.NON_INTEGER_FIELD)
    _refused({**good, "sequence": -1}, RefusalReason.NEGATIVE_FIELD)
    _refused({**good, "host_monotonic_ns": -1}, RefusalReason.NEGATIVE_FIELD)

    # An unknown channel is absent, not a new stream — a distinct refusal type.
    with pytest.raises(UnknownChannelError):
        CaptureEnvelope.from_dict({**good, "channel_id": "go2.nope"})

    # A frame swap is unrecoverable once the bracket is unbolted.
    _refused({**good, "frame_id": "base_link"}, RefusalReason.FRAME_MISMATCH)
    _refused({**good, "calibration_ref": "  "}, RefusalReason.EMPTY_CALIBRATION_REF)


def test_canonical_json_refuses_to_emit_a_non_json_token() -> None:
    """``json.dumps`` emits a bare ``NaN`` by default, which is not JSON."""

    assert json.dumps(float("nan")) == "NaN"  # the trap, demonstrated
    with pytest.raises(ValueError):
        json.dumps(float("nan"), allow_nan=False)
    # And no envelope can carry one in the first place.
    with pytest.raises(CaptureRefusedError):
        CaptureEnvelope(
            channel_id=CHANNEL_A,
            sequence=0,
            source_timestamp_ns=float("nan"),  # type: ignore[arg-type]
            host_monotonic_ns=NOW_MONO,
            host_realtime_ns=NOW_REAL,
            frame_id=channel(CHANNEL_A).frame_id,
            origin=EvidenceOrigin.PHYSICAL,
        )


# ---------------------------------------------------------------------------
# GATE 4 — origin fails closed; UNKNOWN is never a capture authority
# ---------------------------------------------------------------------------


def test_origin_defaults_to_unknown_and_unknown_is_never_recorded_under() -> None:
    default = CaptureEnvelope(
        channel_id=CHANNEL_A,
        sequence=0,
        source_timestamp_ns=None,
        host_monotonic_ns=NOW_MONO,
        host_realtime_ns=NOW_REAL,
        frame_id=channel(CHANNEL_A).frame_id,
    )
    assert default.origin is EvidenceOrigin.UNKNOWN
    assert default.calibration_ref == UNCALIBRATED
    assert default.health is ChannelHealth.UNKNOWN
    assert not default.health.is_asserted_good

    book = ChannelSequenceBook()
    with pytest.raises(CaptureRefusedError) as caught:
        book.stamp(
            CHANNEL_A,
            host_monotonic_ns=NOW_MONO,
            host_realtime_ns=NOW_REAL,
            origin=EvidenceOrigin.UNKNOWN,
        )
    assert caught.value.reason is RefusalReason.ORIGIN_NOT_DECLARED
    # A refusal must not have consumed a sequence number.
    assert book.issued(CHANNEL_A) == 0


def test_seeded_failure_a_string_is_not_an_origin_declaration() -> None:
    """W0-A's finding, re-pinned on this surface: no string mints authority."""

    book = ChannelSequenceBook()
    for spoof in ("physical", "PHYSICAL", "unknown", "", None, 1):
        with pytest.raises(CaptureRefusedError) as caught:
            book.stamp(
                CHANNEL_A,
                host_monotonic_ns=NOW_MONO,
                host_realtime_ns=NOW_REAL,
                origin=spoof,  # type: ignore[arg-type]
            )
        assert caught.value.reason is RefusalReason.ORIGIN_NOT_TYPED
    assert book.issued(CHANNEL_A) == 0


def test_a_synthetic_origin_must_name_its_fixture_and_physical_must_not() -> None:
    """PS-E drives this same stack from synthetic publishers.

    A rehearsal envelope and a session envelope must be impossible to confuse
    once both are sitting in a bag six months from now, so a synthetic origin
    carries a mandatory label and a physical one is forbidden to carry any.
    """

    book = ChannelSequenceBook()
    for origin in (EvidenceOrigin.SIMULATION, EvidenceOrigin.REPLAY):
        with pytest.raises(CaptureRefusedError) as caught:
            book.stamp(
                CHANNEL_A,
                host_monotonic_ns=NOW_MONO,
                host_realtime_ns=NOW_REAL,
                origin=origin,
            )
        assert caught.value.reason is RefusalReason.FIXTURE_LABEL_MISSING

        labelled = book.stamp(
            CHANNEL_A,
            host_monotonic_ns=NOW_MONO,
            host_realtime_ns=NOW_REAL,
            origin=origin,
            fixture_label="ps-e-rehearsal-v1",
        )
        assert labelled.fixture_label == "ps-e-rehearsal-v1"
        assert CaptureEnvelope.from_dict(labelled.to_dict()) == labelled

    with pytest.raises(CaptureRefusedError) as caught:
        book.stamp(
            CHANNEL_A,
            host_monotonic_ns=NOW_MONO,
            host_realtime_ns=NOW_REAL,
            origin=EvidenceOrigin.PHYSICAL,
            fixture_label="looks-real-enough",
        )
    assert caught.value.reason is RefusalReason.FIXTURE_LABEL_FORBIDDEN


def test_stamp_takes_the_frame_from_the_matrix_not_from_the_caller() -> None:
    """There is no argument on this path that can put a wrong frame on data."""

    book = ChannelSequenceBook()
    envelope = book.stamp(
        "d455.infra2",
        host_monotonic_ns=NOW_MONO,
        host_realtime_ns=NOW_REAL,
        origin=EvidenceOrigin.PHYSICAL,
    )
    assert envelope.frame_id == "camera_infra2_optical_frame"
    assert "frame_id" not in ChannelSequenceBook.stamp.__code__.co_varnames


# ---------------------------------------------------------------------------
# GATE 5 — stdlib-only leaf: AST import walk plus a subprocess sys.modules probe
# ---------------------------------------------------------------------------

#: Every module the package is allowed to import. Each stdlib entry shipped in
#: CPython 3.10.0 (docs/library index) AND is in this interpreter's
#: ``sys.stdlib_module_names``; both halves are asserted below.
ALLOWED_IMPORTS = frozenset(
    {
        "__future__",
        "collections.abc",
        "dataclasses",
        "enum",
        "hashlib",
        "json",
        "types",
        "typing",
        "parcel_robot.evidence_origin",
    }
)

#: Relative imports the package may make — intra-package only, by name.
ALLOWED_RELATIVE_IMPORTS = frozenset({".channels", ".envelope"})


def _imports_of(source: str) -> list[str]:
    names: list[str] = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            names.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                names.append("." * node.level + (node.module or ""))
            else:
                names.append(node.module or "")
    return names


def test_the_capture_package_is_a_stdlib_only_leaf() -> None:
    """The deployment constraint, measured. Precedent: W0-A's leaf pin.

    The Orin runs Python 3.10 under JetPack 6.2.x with no Parcel wheel
    installed; this dev venv is 3.14.4 on Ubuntu 26.04. The two share no
    third-party dependency, so the only way one package serves both is to
    import the standard library and ``evidence_origin`` and nothing else.
    """

    for path, source in _package_sources().items():
        for name in _imports_of(source):
            if name.startswith("."):
                assert name in ALLOWED_RELATIVE_IMPORTS, f"{path.name}: {name}"
                continue
            assert name in ALLOWED_IMPORTS, (
                f"{path.name} imports {name!r}, which is outside the leaf budget "
                f"{sorted(ALLOWED_IMPORTS)}"
            )
            root = name.split(".", 1)[0]
            if root != "parcel_robot":
                assert root in sys.stdlib_module_names, f"{name} is not stdlib"

    # The parcel_robot budget is exactly one module, and it is the leaf one.
    parcel_imports = {
        name
        for source in _package_sources().values()
        for name in _imports_of(source)
        if name.startswith("parcel_robot")
    }
    assert parcel_imports == {"parcel_robot.evidence_origin"}


def test_importing_the_capture_package_pulls_in_nothing_else() -> None:
    """The property the AST walk is a proxy for, measured directly.

    Compared against a control subprocess so that whatever ``site`` injects on
    this host (``.pth`` hooks, setuptools shims) cannot mask a real import.
    """

    def _modules(code: str) -> set[str]:
        probe = subprocess.run(
            [
                sys.executable,
                "-c",
                f"{code}\nimport sys, json\nprint(json.dumps(sorted(sys.modules)))",
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        return set(json.loads(probe.stdout))

    control = _modules("pass")
    loaded = _modules("import parcel_robot.capture")
    added = loaded - control

    assert {name for name in added if name.startswith("parcel_robot")} == {
        "parcel_robot",
        "parcel_robot.capture",
        "parcel_robot.capture.channels",
        "parcel_robot.capture.envelope",
        "parcel_robot.evidence_origin",
    }, f"importing capture pulled in extra parcel_robot modules: {sorted(added)}"

    non_stdlib = {
        name
        for name in added
        if name.split(".", 1)[0] not in sys.stdlib_module_names
        and not name.startswith("parcel_robot")
        and not name.startswith("_")
    }
    assert not non_stdlib, f"capture dragged in third-party modules: {sorted(non_stdlib)}"


def test_seeded_failure_the_leaf_walk_catches_a_forbidden_import() -> None:
    """The mutant: a future edit reaches for the runtime or a vendor SDK."""

    for smuggled in (
        "from parcel_robot.runtime import RobotRuntime",
        "import rclpy",
        "from parcel_robot.navigation import pipeline",
        "from ..control import manager",
    ):
        names = _imports_of(smuggled)
        assert names
        assert not all(
            name in ALLOWED_IMPORTS or name in ALLOWED_RELATIVE_IMPORTS for name in names
        ), f"the leaf budget failed to reject {smuggled!r}"


# ---------------------------------------------------------------------------
# GATE 6 — read-only pin: nothing in the package names a way to move the robot
# ---------------------------------------------------------------------------

#: Case-folded substrings forbidden in any SYMBOL (identifier, attribute,
#: import name, parameter). Named by the card.
FORBIDDEN_SYMBOL_SUBSTRINGS = ("publish", "control", "sdk2py", "estop", "cmd_vel")

#: Case-folded whole symbols that are too short to match as substrings without
#: false positives ("arm" in "warm", "move" in "remove").
FORBIDDEN_SYMBOLS_EXACT = frozenset({"move", "set_target", "lease", "arm", "disarm"})

#: Forbidden inside any non-docstring string literal, which is where a dynamic
#: ``getattr``/``import_module`` reach would have to hide. Docstrings are
#: excluded: prose cannot execute, and the module docstrings deliberately name
#: these things in order to say the package must not do them.
FORBIDDEN_LITERAL_SUBSTRINGS = (
    "create_publisher",
    "controlmanager",
    "set_target",
    "parcel_robot.control",
    "parcel_robot.runtime",
    "unitree_sdk2py",
)


def _symbols_and_literals(source: str) -> tuple[set[str], set[str]]:
    tree = ast.parse(source)
    docstrings = set()
    for node in ast.walk(tree):
        body = getattr(node, "body", None)
        if not isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef,
                                 ast.AsyncFunctionDef)) or not body:
            continue
        first = body[0]
        if (
            isinstance(first, ast.Expr)
            and isinstance(first.value, ast.Constant)
            and isinstance(first.value.value, str)
        ):
            docstrings.add(id(first.value))

    symbols: set[str] = set()
    literals: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            symbols.add(node.id)
        elif isinstance(node, ast.Attribute):
            symbols.add(node.attr)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            symbols.add(node.name)
        elif isinstance(node, ast.arg) or (isinstance(node, ast.keyword) and node.arg):
            symbols.add(node.arg)
        elif isinstance(node, ast.Import):
            symbols.update(alias.name for alias in node.names)
            symbols.update(alias.asname for alias in node.names if alias.asname)
        elif isinstance(node, ast.ImportFrom):
            symbols.add(node.module or "")
            symbols.update(alias.name for alias in node.names)
        elif (
            isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and id(node) not in docstrings
        ):
            literals.add(node.value)
    return symbols, literals


def _read_only_violations(source: str) -> list[str]:
    symbols, literals = _symbols_and_literals(source)
    violations: list[str] = []
    for symbol in symbols:
        folded = symbol.casefold()
        if folded in FORBIDDEN_SYMBOLS_EXACT or any(
            token in folded for token in FORBIDDEN_SYMBOL_SUBSTRINGS
        ):
            violations.append(f"symbol {symbol!r}")
    for literal in literals:
        folded = literal.casefold()
        for token in FORBIDDEN_LITERAL_SUBSTRINGS:
            if token in folded:
                violations.append(f"literal {literal!r} contains {token!r}")
    return violations


def test_no_symbol_in_the_capture_package_can_reach_a_motion_surface() -> None:
    """Read-only by import graph, which is where the property actually holds.

    ``PHYSICAL_SESSION_PLAN.md`` rejects a runtime mode enum for exactly this
    reason: a Python enum is weaker than an absent SDK, and a mode enforced at
    the health join would have inherited finding F-1 (a latched input-health
    stop still permits yaw, ``runtime.py:5711-5712``). This package cannot
    publish because it names nothing that publishes.
    """

    for path, source in _package_sources().items():
        violations = _read_only_violations(source)
        assert not violations, f"{path.name}: {violations}"


def test_seeded_failure_the_read_only_pin_catches_every_named_surface() -> None:
    """One mutant per surface the card names, each caught by the same scan."""

    mutants = {
        "publisher": "node.create_publisher(Twist, 'cmd_vel', 10)",
        "control_manager": "from parcel_robot.control.manager import ControlManager",
        "move": "def move(self, command):\n    return command\n",
        "set_target": "backend.set_target(1.0)",
        "control_module": "import parcel_robot.control as c",
        "dynamic_reach": "getattr(mod, 'create_publisher')",
        "vendor_sdk": "import unitree_sdk2py",
        "lease": "lease = api.acquire()",
    }
    for name, mutant in mutants.items():
        assert _read_only_violations(mutant), f"mutant {name!r} slipped the pin"

    # ... and the scan does not fire on the sensor channels that legitimately
    # carry vendor names, which is what makes the pin usable rather than noise.
    assert not _read_only_violations(
        "topic = 'wirelesscontroller'\n"
        "message_type = 'unitree_go/msg/dds_/WirelessController_'\n"
        "transport = 'unilidar_sdk2'\n"
    )


# ---------------------------------------------------------------------------
# GATE 7 — import-clean under BOTH Python 3.10 and 3.14
# ---------------------------------------------------------------------------
#
# HONESTY STATEMENT, and it belongs in the test rather than only the status
# doc: this host has NO Python 3.10 interpreter (`ls /usr/bin/python3*` →
# 3.14 only; no uv, pyenv, docker or podman), so no 3.10 process was executed.
# The 3.10 claim is therefore STATIC, made of three measured checks:
#   1. `ast.parse(..., feature_version=(3, 10))` accepts the syntax;
#   2. every import is in ALLOWED_IMPORTS, each of which shipped in 3.10;
#   3. no symbol in the package is one of the post-3.10 stdlib/typing
#      additions enumerated below.
# The 3.14 claim is dynamic: the module imports and every other cell in this
# file runs on 3.14.4. What remains unproven is stated in the status doc.

#: Names added to the stdlib/typing surface AFTER 3.10. Using any of these
#: would import-fail or attribute-fail on the Orin. Versions in comments.
POST_310_SYMBOLS = frozenset(
    {
        "StrEnum",          # enum, 3.11
        "verify",           # enum.verify, 3.11
        "tomllib",          # 3.11
        "Self",             # typing, 3.11
        "LiteralString",    # typing, 3.11
        "Never",            # typing, 3.11
        "assert_never",     # typing, 3.11
        "assert_type",      # typing, 3.11
        "Required",         # typing, 3.11
        "NotRequired",      # typing, 3.11
        "Unpack",           # typing, 3.11
        "dataclass_transform",  # typing, 3.11
        "ExceptionGroup",   # builtins, 3.11
        "BaseExceptionGroup",   # builtins, 3.11
        "add_note",         # BaseException.add_note, 3.11
        "TaskGroup",        # asyncio, 3.11
        "file_digest",      # hashlib, 3.11
        "batched",          # itertools, 3.12
        "override",         # typing, 3.12
        "TypeAliasType",    # typing, 3.12
        "deprecated",       # warnings, 3.13
        "ReadOnly",         # typing, 3.13
        "TypeIs",           # typing, 3.13
    }
)


def test_the_package_parses_as_python_310_and_uses_no_post_310_surface() -> None:
    for path, source in _package_sources().items():
        # 1. Syntax: 3.10 would accept this file.
        ast.parse(source, filename=str(path), feature_version=(3, 10))
        # 2. Syntax: so does the interpreter running this test (3.14 here).
        compile(source, str(path), "exec", dont_inherit=True)
        # 3. Surface: nothing that only exists after 3.10.
        symbols, _literals = _symbols_and_literals(source)
        assert not symbols & POST_310_SYMBOLS, (
            f"{path.name} uses post-3.10 names: {sorted(symbols & POST_310_SYMBOLS)}"
        )
    # 4. Imports: each shipped in 3.10 and each is stdlib on this interpreter.
    for name in ALLOWED_IMPORTS:
        root = name.split(".", 1)[0]
        if root == "parcel_robot":
            continue
        assert root in sys.stdlib_module_names


def test_seeded_failure_the_dual_python_gate_catches_a_311_only_edit() -> None:
    """Mutants a 3.14 developer writes without noticing. All must be caught."""

    syntax_mutants = (
        "try:\n    pass\nexcept* ValueError:\n    pass\n",  # PEP 654, 3.11
        "type Alias = int\n",                               # PEP 695, 3.12
        "def f[T](x: T) -> T:\n    return x\n",             # PEP 695, 3.12
    )
    for mutant in syntax_mutants:
        compile(mutant, "<mutant>", "exec", dont_inherit=True)  # fine on 3.14
        with pytest.raises(SyntaxError):
            ast.parse(mutant, feature_version=(3, 10))

    surface_mutants = (
        "from enum import StrEnum\n",
        "from typing import Self\n",
        "import tomllib\n",
        "digest = hashlib.file_digest(handle, 'sha256')\n",
    )
    for mutant in surface_mutants:
        ast.parse(mutant, feature_version=(3, 10))  # syntax alone says nothing
        symbols, _literals = _symbols_and_literals(mutant)
        assert symbols & POST_310_SYMBOLS, f"surface gate missed {mutant!r}"


# ---------------------------------------------------------------------------
# S-1 — the support-artifact class beside the payload matrix
# ---------------------------------------------------------------------------
#
# The verified P0 (AU-H, 2026-08-14): the matrix enumerated sensor channels
# and never modelled calibration/transform SUPPORT ARTIFACTS as a class, so
# four optical streams were planned with no camera_info, no /tf and no
# /tf_static. These cells pin the new class: BESIDE the 28 payload channels,
# never among them, never minting a payload sequence space, and with the
# CameraInfo topic names DERIVED from image topic names rather than kept as a
# second hand-written list.

from parcel_robot.capture.channels import (
    SUPPORT_ARTIFACT_ROWS,
    SUPPORT_ARTIFACTS,
    SUPPORT_ARTIFACTS_BY_ID,
    SupportArtifact,
    SupportArtifactKind,
    SupportNeed,
    SupportScope,
    UnknownSupportArtifactError,
    camera_info_topic_for,
    certified_optical_channel_ids,
    support_artifact,
    support_artifacts_for,
)


def test_support_artifacts_live_beside_the_matrix_never_inside_it() -> None:
    """The payload matrix stays payload-only: still 28 channels, still 25 rows,
    and not one support id can collide with a channel id — a support artifact
    must never be able to mint a payload sequence space."""

    assert len(CHANNELS) == 28
    assert len(SUPPORT_ARTIFACTS) == SUPPORT_ARTIFACT_ROWS == 8
    for artifact in SUPPORT_ARTIFACTS:
        assert artifact.support_id.startswith("support.")
        assert artifact.support_id not in CHANNELS_BY_ID
        # No arrival semantics: the class has no rate, no presence prior, no
        # sequence space — structurally, not by convention.
        assert not hasattr(artifact, "nominal_rate_hz")
        assert not hasattr(artifact, "presence")
        for channel_id in artifact.supports_channel_ids:
            assert channel_id in CHANNELS_BY_ID


def test_every_required_optical_stream_has_a_camera_info_artifact() -> None:
    """The four D455 optical streams are the GO-RECORD certification set; the
    Go2 front camera is deliberately NOT in it — no CameraInfo publisher
    exists, and that absence is documented rather than gated or ignored."""

    assert certified_optical_channel_ids() == (
        "d455.color", "d455.depth", "d455.infra1", "d455.infra2",
    )
    front = support_artifact("support.go2.front_camera.camera_info")
    assert front.need is SupportNeed.UNAVAILABLE_DOCUMENTED
    assert front.message_type is None  # not a topic: nothing publishes it
    assert "NO PUBLISHER" in front.human_name
    # tf_static is snapshot-substitutable; dynamic tf is opportunistic.
    assert support_artifact("support.tf_static").need is SupportNeed.SNAPSHOT_SUBSTITUTABLE
    assert support_artifact("support.tf").need is SupportNeed.RECORDED_OPPORTUNISTIC


def test_camera_info_topics_are_derived_from_image_topics_never_guessed() -> None:
    assert (
        camera_info_topic_for("/camera/camera/color/image_raw")
        == "/camera/camera/color/camera_info"
    )
    assert (
        camera_info_topic_for("/camera/camera/depth/image_rect_raw")
        == "/camera/camera/depth/camera_info"
    )
    # Fail closed: a leaf that is not an image topic is refused, not mangled —
    # a wrong support-topic name is silent at record time.
    for hostile in (
        "/camera/camera/color/points",
        "relative/image_raw",
        "/camera/camera/color/image_raw/",
        "/image_raw",
    ):
        with pytest.raises(CaptureError):
            camera_info_topic_for(hostile)


def test_support_artifacts_for_joins_per_channel_and_rig_spatial_scopes() -> None:
    for_color = {item.support_id for item in support_artifacts_for("d455.color")}
    assert for_color == {
        "support.d455.color.camera_info",
        "support.calibration.digest",
        "support.tf",
        "support.tf_static",
    }
    # A non-spatial channel gets no rig-spatial transform artifacts.
    for_tegrastats = {item.support_id for item in support_artifacts_for("orin.tegrastats")}
    assert "support.tf_static" not in for_tegrastats
    with pytest.raises(UnknownChannelError):
        support_artifacts_for("not.a.channel")


def test_seeded_failure_the_support_table_refuses_malformed_rows() -> None:
    good = {
        "support_id": "support.mutant.camera_info",
        "kind": SupportArtifactKind.CAMERA_INFO,
        "human_name": "mutant",
        "supports_channel_ids": ("d455.color",),
        "need": SupportNeed.REQUIRED,
        "scope": SupportScope.PER_CHANNEL,
        "message_type": "sensor_msgs/msg/CameraInfo",
        "confidence": Confidence.UNVERIFIED,
        "note": "mutant row",
    }
    SupportArtifact(**good)  # the baseline construction is legal

    mutants: tuple[tuple[str, object, str], ...] = (
        ("support_id", "d455.color", "support."),
        ("need", "required", "SupportNeed"),
        ("kind", "camera_info", "SupportArtifactKind"),
        ("scope", "per_channel", "SupportScope"),
        ("supports_channel_ids", (), "PER_CHANNEL"),
        ("message_type", "", "non-empty"),
        ("note", " ", "non-empty"),
    )
    for field_name, value, match in mutants:
        with pytest.raises(CaptureError, match=match):
            SupportArtifact(**{**good, field_name: value})
    # RIG_SPATIAL restating its channel set is a second list that can drift.
    with pytest.raises(CaptureError, match="derives its channel set"):
        SupportArtifact(
            **{
                **good,
                "scope": SupportScope.RIG_SPATIAL,
                "kind": SupportArtifactKind.TF,
            }
        )


def test_seeded_failure_an_unknown_support_id_is_absent_not_new() -> None:
    with pytest.raises(UnknownSupportArtifactError, match="unknown support_id"):
        support_artifact("support.d455.color.camerainfo")  # typo'd id
    assert set(SUPPORT_ARTIFACTS_BY_ID) == {
        item.support_id for item in SUPPORT_ARTIFACTS
    }
