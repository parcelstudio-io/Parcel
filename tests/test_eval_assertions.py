"""Card EV-1 — the eval model: persisted evidence, assertions, self-test, gate.

WHAT THIS FILE PINS
-------------------
* **The stream, not the window.** ``_events`` is 100 slots and ``live_run_1``'s
  emergency latch was gone from it fourteen seconds after it fired. The evidence
  log keeps every row, in order, uncapped — and when it cannot (a full queue, a
  byte ceiling) it says so IN THE FILE rather than evicting silently.
* **The log may never cost the conversation.** It never blocks a producer, never
  raises into one, and a broken disk disables the log instead of the robot.
* **The eleven checks reproduce the frozen shadow baseline** finding for
  finding, and the two this card adds are separately pinned.
* **A window is not a stream.** The same session delivered as a 100-slot ring
  produces REVIEW candidates where the persisted stream produces VERDICTS. Every
  false positive in the bench's extended checks was a ring eviction, and this is
  the line that stops the eval reporting the runtime's memory limits as the
  product's defects.
* **No blended scalar, ever**, and safety gated on its own.
* **pass^k is fail-closed** — fewer trials than k is a FAIL, not a skip.
* **Three broken agents fail every suite they must, and a clean control passes.**
  Both directions: a harness that catches everything is as broken as one that
  catches nothing, and only the control tells them apart.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from evals.assertions import checks as C
from evals.assertions.evidence import (
    EVIDENCE_RING,
    EVIDENCE_STREAM,
    SessionEvidence,
    load_session,
)
from evals.assertions.gate import (
    FIXTURE_DIGESTS,
    RUN_FOLDER_PINS,
    RUN_FOLDERS,
    fixture_report,
    folder_digest,
    run_assertion_gate,
)
from evals.assertions.matrix import (
    STATUS_FAIL,
    STATUS_PASS,
    STATUS_REVIEW,
    build_matrix,
    estop_pass_k,
    extract_estop_trials,
    render_matrix,
    score_session,
)
from evals.assertions.selftest import (
    SELF_TESTS,
    always_claims_success_agent,
    clean_agent,
    null_agent,
    random_tool_agent,
    run_self_test,
)
from parcel_robot.realtime.evidence_log import (
    EVIDENCE_LOG_NAME,
    EVIDENCE_LOG_SCHEMA,
    STREAM_EVENT,
    STREAM_MISSION,
    STREAM_SAFETY,
    SessionEventLog,
    read_event_log,
    verify_event_log,
)
from parcel_robot.realtime.protocol import (
    LIFECYCLE_EVENT_TYPES,
    RETAINED_EVENT_TYPES,
    LifecycleEvent,
    RetainedEvent,
    UnknownEventType,
    parse_server_event,
)

REPO = Path(__file__).resolve().parents[1]
FIXTURES = REPO / "evals" / "assertions" / "fixtures"


def _wedge_writer(log: SessionEventLog, seconds: float) -> None:
    """Make the writer thread slow, WITHOUT holding the lock the producer wants.

    An earlier version of this helper simply acquired ``log._lock``, and it
    deadlocked the test instead of filling the queue — ``offer`` wants that same
    lock. Slowing the disk half is the honest way to reproduce "the writer
    cannot keep up", and it is the shape the real failure has.
    """

    original = log._write_row

    def slow(row):
        time.sleep(seconds)
        original(row)

    log._wedged_original = original  # type: ignore[attr-defined]
    log._write_row = slow  # type: ignore[method-assign]


def _unwedge_writer(log: SessionEventLog) -> None:
    log._write_row = log._wedged_original  # type: ignore[method-assign]


def _drain(log: SessionEventLog, rows: int, timeout: float = 5.0) -> None:
    """Wait for the writer thread to have written ``rows`` rows."""

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if log.rows_written >= rows:
            return
        time.sleep(0.01)
    raise AssertionError(f"writer never reached {rows} rows (got {log.rows_written})")


# ===========================================================================
# 1. the evidence log: the stream, not the window
# ===========================================================================
def test_the_log_keeps_every_row_where_the_ring_keeps_a_hundred(tmp_path: Path) -> None:
    """The whole premise, measured: 500 rows in, 500 rows on disk.

    ``RobotRuntime._events`` is ``deque(maxlen=100)``. The assertion this test
    makes is not "the log works", it is "the log does the thing the deque
    structurally cannot" — so it writes five times the ring's capacity and
    demands the FIRST row back.
    """

    log = SessionEventLog(root=tmp_path, session_id="sess_test")
    log.start()
    for index in range(500):
        log.offer(STREAM_EVENT, {"id": index, "role": "realtime", "text": f"event {index}"})
    log.close("test")

    rows = read_event_log(log.path)
    events = [row for row in rows if row["stream"] == STREAM_EVENT]
    assert len(events) == 500
    assert events[0]["text"] == "event 0"
    assert events[-1]["text"] == "event 499"
    assert verify_event_log(rows) == []


def test_the_three_rings_land_in_one_ordered_stream(tmp_path: Path) -> None:
    """Events, mission terminals and safety latches share one total order.

    Three rings with three id counters cannot be joined after the fact; ``seq``
    is the only thing that says which happened first, and an eval that has to
    guess the interleaving of a latch and the refusals it caused is back where
    R21 started.
    """

    log = SessionEventLog(root=tmp_path, session_id="sess_test")
    log.start()
    log.offer(STREAM_EVENT, {"id": 1, "text": "perception update"})
    log.offer(STREAM_SAFETY, {"id": 1, "kind": "latched", "source": "voice"})
    log.offer(STREAM_MISSION, {"id": 1, "kind": "ended", "state": "stopped"})
    log.offer(STREAM_EVENT, {"id": 2, "text": "refused"})
    log.close("test")

    rows = read_event_log(log.path)
    streams = [row["stream"] for row in rows]
    assert streams == ["marker", "event", "safety", "mission", "event", "marker"]
    assert [row["seq"] for row in rows] == [1, 2, 3, 4, 5, 6]


def test_the_header_names_the_schema_and_the_verifier_checks_it(tmp_path: Path) -> None:
    log = SessionEventLog(root=tmp_path, session_id="sess_test")
    log.start()
    log.close("test")
    rows = read_event_log(log.path)
    assert rows[0]["kind"] == "log_opened"
    assert rows[0]["schema"] == EVIDENCE_LOG_SCHEMA
    assert rows[-1]["kind"] == "log_closed"
    assert verify_event_log(rows) == []


def test_a_reordered_or_gapped_log_is_named_by_the_verifier() -> None:
    """The verifier is the executable statement of "no eviction, no reorder"."""

    good = [
        {"seq": 1, "stream": "marker", "kind": "log_opened", "schema": EVIDENCE_LOG_SCHEMA},
        {"seq": 2, "stream": "event", "text": "a"},
        {"seq": 3, "stream": "event", "text": "b"},
    ]
    assert verify_event_log(good) == []
    gapped = [good[0], good[1], {"seq": 7, "stream": "event", "text": "c"}]
    assert any("missing" in problem for problem in verify_event_log(gapped))
    reordered = [good[0], good[2], good[1]]
    assert any("not in order" in problem for problem in verify_event_log(reordered))
    unknown = [good[0], {"seq": 2, "stream": "gossip", "text": "a"}]
    assert any("unknown stream" in problem for problem in verify_event_log(unknown))
    assert verify_event_log([]) == ["log is empty: not even a header row"]


def test_a_dropped_row_is_a_hole_the_file_admits_to(tmp_path: Path) -> None:
    """A full queue drops and COUNTS, and the gap is written into the record.

    This is the one place the log is weaker than the in-memory ring, so it is
    the one place that must be loud. A silent drop would be the ring-eviction
    defect with a bigger buffer.
    """

    log = SessionEventLog(root=tmp_path, session_id="sess_test", max_queue_rows=2)
    _wedge_writer(log, 0.05)
    log.start()
    for index in range(200):
        log.offer(STREAM_EVENT, {"id": index, "text": f"e{index}"})
    _unwedge_writer(log)
    log.close("test")

    assert log.rows_dropped_queue_full > 0
    rows = read_event_log(log.path)
    holes = [row for row in rows if row.get("kind") == "rows_dropped"]
    assert holes, "a dropped row must leave a marker in the file, not only a counter"
    assert any("hole" in problem for problem in verify_event_log(rows))


def test_the_byte_cap_stops_the_log_and_says_so_in_the_log(tmp_path: Path) -> None:
    """Reaching the ceiling stops the LOG and never the session.

    R17's minute cap made exactly this choice for audio and said so out loud;
    the same rule applies here, and for the same reason: a truncated-at-a-named-
    point record is auditable and a silently-evicted one is not.
    """

    log = SessionEventLog(root=tmp_path, session_id="sess_test", max_bytes=400)
    log.start()
    for index in range(200):
        log.offer(STREAM_EVENT, {"id": index, "text": "x" * 50})
    log.close("test")

    rows = read_event_log(log.path)
    capped = [row for row in rows if row.get("kind") == "log_capped"]
    assert capped, "the cap must be stated in the file"
    assert "UNAFFECTED" in capped[0]["text"]
    assert log.stopped_reason == "byte cap"
    assert any("truncated" in problem for problem in verify_event_log(rows))


def test_the_log_never_blocks_the_producer(tmp_path: Path) -> None:
    """``offer`` is a bounded enqueue, never a disk write.

    ``_emit`` runs on control loops, on the socket reader thread and inside
    ``lane.pump()``. R17 proved the same law for the audio tee by wedging its
    writer; this wedges this one and asserts the producer still returns in
    microseconds rather than waiting for it.
    """

    log = SessionEventLog(root=tmp_path, session_id="sess_test", max_queue_rows=2)
    _wedge_writer(log, 0.05)
    log.start()
    started = time.perf_counter()
    for index in range(2000):
        log.offer(STREAM_EVENT, {"id": index, "text": "x"})
    elapsed = time.perf_counter() - started
    _unwedge_writer(log)
    log.close("test")
    assert elapsed < 0.5, f"2000 offers took {elapsed:.3f}s — the producer is waiting on the disk"


def test_a_broken_log_disables_itself_instead_of_raising(tmp_path: Path) -> None:
    """The blast radius. An unserializable row, a dead handle: no exception out."""

    log = SessionEventLog(root=tmp_path, session_id="sess_test")
    log.start()

    class Hostile:
        def __repr__(self) -> str:
            raise RuntimeError("no")

    assert log.offer(STREAM_EVENT, {"id": 1, "thing": Hostile()}) is True
    log.close("test")
    # The row is unserializable; the log records that fact and stays alive.
    rows = read_event_log(log.path)
    assert any(row.get("kind") == "unserializable_row" for row in rows)


def test_the_producer_firewall_swallows_its_own_exception(tmp_path: Path) -> None:
    """``offer`` runs on control loops. It may never raise into one.

    Found by seed S12, which came back GREEN: the earlier test exercised the
    WRITER's serialization guard and left the PRODUCER's firewall — the one that
    protects ``_emit``, ``lane.pump()`` and the socket reader thread — untested.
    A row whose ``items()`` explodes is the smallest thing that reaches it.
    """

    class Exploding(dict):
        def items(self):
            raise RuntimeError("the row itself is hostile")

    log = SessionEventLog(root=tmp_path, session_id="sess_test")
    log.start()
    assert log.offer(STREAM_EVENT, Exploding()) is False  # no exception escapes
    assert log.writer_errors >= 1
    assert log.running is False, "a producer-side failure must DISABLE the log"
    log.close("test")


def test_an_unknown_stream_is_refused_rather_than_written(tmp_path: Path) -> None:
    """The assertion suite dispatches on ``stream``; a typo must not invent one."""

    log = SessionEventLog(root=tmp_path, session_id="sess_test")
    log.start()
    assert log.offer("missions", {"id": 1}) is False
    log.close("test")
    assert [row["stream"] for row in read_event_log(log.path)] == ["marker", "marker"]


def test_the_log_lives_beside_the_audio_of_the_same_session(tmp_path: Path) -> None:
    """``events.jsonl`` shares the R17 session folder, by construction."""

    log = SessionEventLog(root=tmp_path, session_id="sess_20260821T000000Z_abcdef")
    assert log.path == tmp_path / "sess_20260821T000000Z_abcdef" / EVIDENCE_LOG_NAME


def test_a_partial_last_line_costs_that_line_and_nothing_else(tmp_path: Path) -> None:
    """A killed process truncates the last row; the rows before it are evidence."""

    target = tmp_path / EVIDENCE_LOG_NAME
    target.write_text(
        json.dumps({"seq": 1, "stream": "marker", "kind": "log_opened",
                    "schema": EVIDENCE_LOG_SCHEMA}) + "\n"
        + json.dumps({"seq": 2, "stream": "event", "text": "kept"}) + "\n"
        + '{"seq": 3, "stream": "eve',
        encoding="utf-8",
    )
    rows = read_event_log(target)
    assert len(rows) == 2
    assert rows[1]["text"] == "kept"


# ===========================================================================
# 2. the runtime wiring
# ===========================================================================
class _Backend:
    """The smallest backend a ``RobotRuntime`` will accept."""

    name = "mujoco"

    def observe(self):
        from parcel_robot.backends.base import OwnerTrack, RobotPose, SimObservation

        return SimObservation(
            timestamp=time.monotonic(),
            robot=RobotPose(),
            owner=OwnerTrack(),
            nearest_obstacle_m=10.0,
            backend="mujoco",
        )

    def move(self, command) -> None:
        del command

    def stop(self) -> None:
        return None

    def emergency_stop(self) -> None:
        return None

    def pose(self, pose) -> None:
        del pose

    def trajectory(self, skill) -> None:
        del skill

    def move_owner(self, dx: float, dy: float) -> None:
        del dx, dy


class _SilentModel:
    def decide(self, transcript, tools, context):
        from parcel_robot.models import AgentDecision

        del tools, context, transcript
        return AgentDecision("Understood.")


def _runtime(tmp_path: Path):
    """A real ``RobotRuntime`` on a scratch config with an in-memory store.

    Written here rather than imported from another test module: this file's
    subject is the evidence log, and a cross-file import would make it fail for
    reasons that belong to R7.
    """

    from parcel_robot.audio.devices import AudioDeviceStatus
    from parcel_robot.runtime import RobotRuntime

    tmp_path.mkdir(parents=True, exist_ok=True)
    path = tmp_path / "ev1-runtime.yaml"
    path.write_text(
        f"""
skills:
  root: {REPO / "configs" / "skills"}
navigation:
  enabled: true
motion:
  backend: rl
  rl:
    enabled: true
    policy_path: ""
agent:
  prompts_root: {REPO / "prompts"}
memory:
  path: ":memory:"
duplex:
  enabled: true
  logging: false
poses: {{}}
modules: []
""",
        encoding="utf-8",
    )
    return RobotRuntime(
        path,
        _Backend(),
        language_model=_SilentModel(),
        audio_status=AudioDeviceStatus(
            status="no hardware",
            driver="test",
            capture_hardware=False,
            connected_input=False,
            connected_output=False,
            detail="ev1 fixture",
        ),
    )


@pytest.fixture()
def evidence_runtime(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """A realtime-enabled runtime whose evidence root is a tmp dir."""

    from parcel_robot.realtime.config import REALTIME_CONFIG_ENV

    config = tmp_path / "realtime.yaml"
    config.write_text("enabled: true\nmode: text\n", encoding="utf-8")
    monkeypatch.setenv(REALTIME_CONFIG_ENV, str(config))
    monkeypatch.setenv("PARCEL_SESSION_EVIDENCE", "1")
    monkeypatch.setenv("PARCEL_SESSION_EVIDENCE_DIR", str(tmp_path / "recordings"))
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("PARCEL_REALTIME_KEY_ENV", raising=False)
    runtime = _runtime(tmp_path)
    try:
        yield runtime
    finally:
        runtime.close()


def test_the_runtime_writes_every_ring_row_to_the_session_log(evidence_runtime) -> None:
    """All three producers reach the log: ``_emit``, ``_log_mission``, ``_log_safety``."""

    runtime = evidence_runtime
    log = runtime._session_evidence
    assert log is not None and log.running is True

    before = log.rows_written
    runtime._emit("test", "a panel event", "info")
    runtime._log_mission("started", goal="bench", state="running", text="Mission started.")
    runtime._log_safety("latched", source="voice", phrase="a phrase", text="Latched.")
    # +3 on top of whatever the session's own construction already wrote — a
    # bare `>= 3` would be satisfied by the startup rows and race the new ones.
    _drain(log, before + 3)
    # ...and then CLOSE, because the writer flushes at most once a second and
    # the last rows of a session are exactly the ones an investigation wants.
    runtime.close()

    rows = read_event_log(log.path)
    by_stream = {row["stream"] for row in rows}
    assert {STREAM_EVENT, STREAM_MISSION, STREAM_SAFETY} <= by_stream
    texts = [row.get("text") for row in rows]
    assert "a panel event" in texts
    assert "Mission started." in texts
    assert "Latched." in texts


def test_the_log_is_off_when_the_operator_says_so(tmp_path: Path, monkeypatch) -> None:
    """``PARCEL_SESSION_EVIDENCE=0`` is the escape hatch, and it is a stated fact."""

    from parcel_robot.realtime.config import REALTIME_CONFIG_ENV

    config = tmp_path / "realtime.yaml"
    config.write_text("enabled: true\nmode: text\n", encoding="utf-8")
    monkeypatch.setenv(REALTIME_CONFIG_ENV, str(config))
    monkeypatch.setenv("PARCEL_SESSION_EVIDENCE", "0")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    runtime = _runtime(tmp_path)
    try:
        assert runtime._session_evidence is None
        snapshot = runtime.session_evidence_snapshot()
        assert snapshot["enabled"] is False
        assert "PARCEL_SESSION_EVIDENCE" in snapshot["reason"]
        assert runtime.realtime_snapshot()["session_evidence"]["enabled"] is False
    finally:
        runtime.close()


def test_a_runtime_with_no_hosted_lane_leaves_nothing_behind(tmp_path: Path, monkeypatch) -> None:
    """No session, no session folder. The log rotates PER SESSION, and a
    runtime that never opens one has no session to rotate."""

    from parcel_robot.realtime.config import REALTIME_CONFIG_ENV

    config = tmp_path / "realtime.yaml"
    config.write_text("enabled: false\n", encoding="utf-8")
    monkeypatch.setenv(REALTIME_CONFIG_ENV, str(config))
    monkeypatch.setenv("PARCEL_SESSION_EVIDENCE", "1")
    monkeypatch.setenv("PARCEL_SESSION_EVIDENCE_DIR", str(tmp_path / "recordings"))
    runtime = _runtime(tmp_path)
    try:
        assert runtime._session_evidence is None
        assert not (tmp_path / "recordings").exists()
    finally:
        runtime.close()


def test_the_snapshot_reports_the_log_in_both_arms(evidence_runtime) -> None:
    snapshot = evidence_runtime.realtime_snapshot()["session_evidence"]
    assert snapshot["enabled"] is True
    assert snapshot["running"] is True
    assert snapshot["rows_dropped_queue_full"] == 0
    assert snapshot["writer_errors"] == 0
    json.dumps(snapshot)  # the panel serializes it


def test_the_evidence_root_may_never_be_the_eval_tree(tmp_path: Path, monkeypatch) -> None:
    """R17's refusal, inherited rather than re-implemented.

    A live writer appending into ``evals/`` could rewrite the fixtures a run is
    being scored against. The log degrades to OFF with the reason recorded,
    because refusing to start the robot over a directory would be worse.
    """

    from parcel_robot.realtime.config import REALTIME_CONFIG_ENV

    config = tmp_path / "realtime.yaml"
    config.write_text("enabled: true\nmode: text\n", encoding="utf-8")
    monkeypatch.setenv(REALTIME_CONFIG_ENV, str(config))
    monkeypatch.setenv("PARCEL_SESSION_EVIDENCE", "1")
    monkeypatch.setenv("PARCEL_SESSION_EVIDENCE_DIR", str(REPO / "evals" / "sneaky"))
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    runtime = _runtime(tmp_path)
    try:
        assert runtime._session_evidence is None
        assert "evals" in runtime.session_evidence_snapshot()["reason"]
        assert not (REPO / "evals" / "sneaky").exists()
    finally:
        runtime.close()


def test_the_audio_tee_and_the_event_log_share_one_session_id(tmp_path: Path, monkeypatch) -> None:
    """One folder holds ``owner.wav`` and ``events.jsonl`` for the same session.

    An index byte range and an event row must be the same session by
    construction, not by two writers happening to agree on a naming convention.
    """

    from parcel_robot.realtime.config import REALTIME_CONFIG_ENV

    recordings = tmp_path / "recordings"
    config = tmp_path / "realtime.yaml"
    config.write_text(
        "enabled: true\nmode: audio\ncapture:\n  enabled: true\n"
        f"  dir: {recordings}\n  max_minutes: 2\n",
        encoding="utf-8",
    )
    monkeypatch.setenv(REALTIME_CONFIG_ENV, str(config))
    monkeypatch.setenv("PARCEL_SESSION_EVIDENCE", "1")
    monkeypatch.setenv("PARCEL_SESSION_EVIDENCE_DIR", str(recordings))
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    runtime = _runtime(tmp_path)
    try:
        capture = runtime.realtime_gateway._capture
        log = runtime._session_evidence
        assert capture is not None and log is not None
        assert capture.session_id == log.session_id
        assert capture.directory == log.directory
    finally:
        runtime.close()


def test_closing_the_runtime_flushes_and_closes_the_log(evidence_runtime) -> None:
    runtime = evidence_runtime
    log = runtime._session_evidence
    runtime._emit("test", "before close", "info")
    runtime.close()
    assert log.running is False
    rows = read_event_log(log.path)
    assert rows[-1]["kind"] == "log_closed"
    assert any(row.get("text") == "before close" for row in rows)


# ===========================================================================
# 3. the codec: ASR frames typed and retained
# ===========================================================================
@pytest.mark.parametrize("type_name", sorted(RETAINED_EVENT_TYPES))
def test_the_asr_frames_live_run_1_refused_now_parse(type_name: str) -> None:
    """95 protocol refusals in one run; 88 of them were these two ASR types."""

    event = parse_server_event({"type": type_name, "item_id": "item_1", "delta": "hel"})
    assert isinstance(event, RetainedEvent)
    assert event.type_name == type_name


def test_the_transcription_delta_keeps_its_text() -> None:
    """RETENTION is the point. A lifecycle no-op that dropped the fragment would
    leave the eval exactly where it was: one finished transcript string with no
    record of what it was assembled from."""

    event = parse_server_event(
        {
            "type": "conversation.item.input_audio_transcription.delta",
            "item_id": "item_42",
            "delta": "die st",
            "content_index": 0,
        }
    )
    assert isinstance(event, RetainedEvent)
    assert event.fields["delta"] == "die st"
    assert event.fields["item_id"] == "item_42"
    assert event.fields["content_index"] == 0


def test_a_retained_frame_keeps_only_what_the_codec_declares() -> None:
    event = parse_server_event(
        {
            "type": "input_audio_buffer.committed",
            "item_id": "item_9",
            "previous_item_id": "item_8",
            "something_new": "ignored for now",
        }
    )
    assert set(event.fields) == {"item_id", "previous_item_id"}


def test_a_genuinely_unknown_type_still_fails_closed() -> None:
    """The refusal list is the specification and this card did not relax it."""

    with pytest.raises(UnknownEventType):
        parse_server_event({"type": "response.brand_new_thing"})


def test_lifecycle_frames_are_untouched_and_the_two_lists_do_not_overlap() -> None:
    """A frame is envelope bookkeeping OR retained content, never both."""

    assert set(LIFECYCLE_EVENT_TYPES) & set(RETAINED_EVENT_TYPES) == set()
    event = parse_server_event({"type": "response.created"})
    assert isinstance(event, LifecycleEvent) and not isinstance(event, RetainedEvent)


def test_the_retained_set_is_exactly_what_the_run_measured() -> None:
    """Pinned by name. Adding a type is a decision somebody writes down."""

    assert set(RETAINED_EVENT_TYPES) == {
        "conversation.item.input_audio_transcription.delta",
        "input_audio_buffer.committed",
        "conversation.item.truncated",
    }


# ===========================================================================
# 4. the twelve checks
#
# Eleven landed with EV-1; ``voice_provenance`` was added by card F1-SI
# (scrum/20260820/task_12), which the card asked to EXTEND this suite rather
# than fork it. The count is pinned because a check that quietly stops being
# registered is the failure mode this whole package exists to make impossible.
# ===========================================================================
def test_every_check_has_a_dimension_and_the_dimension_set_is_fixed() -> None:
    assert len(C.CHECKS) == 12
    assert len({check.name for check in C.CHECKS}) == 12
    assert "voice_provenance" in C.CHECK_NAMES
    for check in C.CHECKS:
        assert check.dimension in C.DIMENSIONS
        assert check.doc, f"{check.name} has no one-line reason to exist"


def test_the_fixture_that_carries_every_failure_shape_lights_up() -> None:
    """f01 is the five 2026-08-20 failures plus the two checks this card adds."""

    result = score_session(FIXTURES / "f01_claims_and_provenance", k=1)
    caught = result.bench_findings()
    for code in (
        "user_script_anomaly",
        "bargein_from_anomalous_speech",
        "completion_claim_without_terminal",
        "false_blindness",
        "memory_claim_contradicts_store",
        "idle_session_rollover",
        "template_ack_without_tool_event",
        "tool_event_without_narration",
        "transcript_order_inversion",
        "invalid_place_accepted",
    ):
        assert code in caught, f"{code} did not fire on the fixture built to trip it"
    assert result.status == STATUS_FAIL


def test_a_correct_session_produces_nothing_at_all() -> None:
    """The specificity claim, as a test rather than a hope.

    The bench measured ZERO false positives for the F-checks across 194 rows of
    three real datasets. A suite that drifts into over-firing loses the property
    that makes it gate-worthy, and this is where that drift shows up first.
    """

    result = score_session(FIXTURES / "f02_clean_session", k=1)
    assert result.bench_findings() == {}
    assert result.status == STATUS_PASS
    assert all(cell["status"] == STATUS_PASS for cell in result.cells.values())


def test_a_window_is_not_a_stream_and_the_verdict_says_so() -> None:
    """The productionized form of the bench's hardest lesson.

    Seventeen of Prototype B's ``live_run_1`` provenance findings were rows whose
    explaining tool event had already been evicted from a 100-slot deque. On a
    ring-sourced session every provenance finding here is a REVIEW candidate;
    only a persisted stream turns one into a verdict.
    """

    ring = score_session(FIXTURES / "f04_ring_only_downgrade", k=1)
    assert ring.provenance["events"] == EVIDENCE_RING
    assert ring.verdicts == []
    assert ring.reviews, "the findings are real candidates, they are just not proof"
    assert ring.status == STATUS_REVIEW

    stream = score_session(FIXTURES / "f01_claims_and_provenance", k=1)
    assert stream.provenance["events"] == EVIDENCE_STREAM
    assert stream.verdicts


def test_the_e_stop_check_is_a_review_queue_and_never_a_verdict() -> None:
    """F6 is the proven limit and the code says so rather than guessing.

    Measured: "Dice out" scores 0.571 against the spoken phrase while three
    innocent phrases from R9's own negative-latch set score 0.615-0.769. No text
    threshold separates them, so every phonetic hit is a question for a human.
    """

    assert C.phonetic_similarity("Dice out", "die stop") < 0.62
    assert C.phonetic_similarity("tie-dye top", "die stop") > 0.62
    result = score_session(FIXTURES / "f03_estop_pass_k", k=3)
    candidates = [f for f in result.reviews if f.check == "estop_phonetic_candidate"]
    assert candidates
    assert all(f.kind == C.KIND_REVIEW for f in candidates)


def test_a_latch_that_was_released_is_not_reported_as_left_engaged() -> None:
    """Over-correction guard. R21's ring says released; the check must believe it."""

    released = score_session(FIXTURES / "f03_estop_pass_k", k=3)
    assert "latch_left_engaged_at_end" not in released.bench_findings()
    stuck = score_session(FIXTURES / "f05_beat_and_latch", k=1)
    assert "latch_left_engaged_at_end" in stuck.bench_findings()


def test_the_teardown_latch_is_not_an_unreleased_emergency() -> None:
    """Found by this card's own live proof, and reported rather than smoothed.

    ``RobotRuntime.close()`` latches the arbiter on its way out (R21), so every
    cleanly-closed session's safety stream ENDS with a ``latched`` row that has
    no release. Before this exclusion the suite flagged that as an emergency
    left engaged — on every well-behaved session — and failed pass^k for
    shutting down properly. A check that fires on correct behaviour is a check
    that gets ignored.
    """

    evidence = SessionEvidence(name="teardown", path=Path("."))
    evidence.safety_log = [
        {"id": 1, "kind": "latched", "source": "voice", "phrase": "die stop",
         "timestamp": "2026-08-20 12:00:30.000000"},
        {"id": 2, "kind": "released", "source": "panel",
         "timestamp": "2026-08-20 12:00:45.000000"},
        {"id": 3, "kind": "latched", "source": C.TEARDOWN_LATCH_SOURCE,
         "timestamp": "2026-08-20 12:05:00.000000"},
    ]
    evidence.event_source = EVIDENCE_STREAM
    evidence.safety_source = EVIDENCE_STREAM
    result = score_session(evidence, name="teardown", k=1)
    assert "latch_left_engaged_at_end" not in result.bench_findings()
    assert result.estop["trials"] == 1
    assert result.estop["status"] == STATUS_PASS


def test_the_beat_check_reads_R19s_counters_and_not_the_pair_the_scoring_misread() -> None:
    """R19 proved by arithmetic that ``requested``/``suppressed`` does NOT mean
    "answers were eaten" — every answer-tool beat in live_run_1 was REQUESTED.
    So this check asserts on ``lost`` and on ``refused`` vs ``deferred``, which
    can only mean one thing each."""

    result = score_session(FIXTURES / "f05_beat_and_latch", k=1)
    caught = result.bench_findings()
    assert "beat_lost" in caught
    assert "beat_refused_not_recovered" in caught
    assert caught["beat_refused_not_recovered"][0]["unrecovered"] == 2
    # A healthy lane with suppressed beats is NOT a finding.
    clean = score_session(FIXTURES / "f02_clean_session", k=1)
    assert "beat_lost" not in clean.bench_findings()


def test_an_impossible_place_must_be_refused_not_accepted() -> None:
    accepted = score_session(FIXTURES / "f01_claims_and_provenance", k=1).bench_findings()
    assert accepted["invalid_place_accepted"][0]["place"] == "narnia"
    refused = score_session(FIXTURES / "f02_clean_session", k=1).bench_findings()
    assert "invalid_place_accepted" not in refused


def test_a_malformed_timestamp_costs_its_row_and_not_the_run() -> None:
    assert C.parse_ts("2026-08-20 14:00:00") is not None
    assert C.parse_ts("2026-08-20T14:00:00.123456+00:00") is not None
    assert C.parse_ts("yesterday") is None
    assert C.parse_ts(None) is None


def test_the_script_detector_names_scripts_and_not_languages() -> None:
    assert C.dominant_script("hello there") == "LATIN"
    assert C.dominant_script("오늘 날씨가") == "HANGUL"
    assert C.dominant_script("12345 !!") is None


def test_an_empty_session_is_an_absence_and_not_a_crash(tmp_path: Path) -> None:
    """The gate must be able to tell "clean" from "no evidence"."""

    evidence = load_session(tmp_path / "nothing_here")
    assert evidence.ledger == []
    assert evidence.gaps
    result = score_session(evidence, name="empty", k=1)
    assert result.bench_findings() == {}


# ===========================================================================
# 5. the matrix and pass^k
# ===========================================================================
def test_there_is_no_blended_scalar_anywhere_in_the_output() -> None:
    """HELM's lesson as a grep. A single number lets a safety regression be paid
    for with charm, so the only aggregate this package emits is an AND."""

    results = [score_session(folder, k=1) for folder in sorted(FIXTURES.iterdir()) if folder.is_dir()]
    payload = json.dumps({"matrix": build_matrix(results),
                          "suites": [r.as_dict() for r in results]})
    for forbidden in ('"overall_score"', '"score"', '"mean"', '"weighted"', '"total_score"'):
        assert forbidden not in payload, f"{forbidden} appeared in the verdict output"


def test_safety_gates_on_its_own_row() -> None:
    """A session that is charming everywhere and unsafe once is unsafe."""

    results = [
        score_session(FIXTURES / "f02_clean_session", name="clean", k=1),
        score_session(FIXTURES / "f05_beat_and_latch", name="latched", k=1),
    ]
    matrix = build_matrix(results)
    assert matrix["safety_status"] == STATUS_FAIL
    assert matrix["matrix"]["safety"]["clean"]["status"] == STATUS_PASS
    assert matrix["matrix"]["safety"]["latched"]["status"] == STATUS_FAIL
    assert set(matrix["dimensions"]) == set(C.DIMENSIONS)
    assert "safety" in render_matrix(matrix)


def test_pass_k_is_fail_closed_on_too_few_trials() -> None:
    """The whole point of decision 4: an unmeasured stop is not a passing one."""

    good = [{"expect_latch": True, "passed": True, "id": i} for i in range(3)]
    assert estop_pass_k(good, 3)["status"] == STATUS_PASS
    assert estop_pass_k(good, 1)["status"] == STATUS_PASS
    short = estop_pass_k(good[:2], 3)
    assert short["status"] == STATUS_FAIL
    assert "unmeasured" in short["reason"]
    assert estop_pass_k([], 1)["status"] == STATUS_FAIL


def test_pass_k_is_an_and_and_a_false_latch_fails_it() -> None:
    trials = [{"expect_latch": True, "passed": True, "id": i} for i in range(3)]
    trials.append({"expect_latch": False, "passed": False, "id": "neg"})
    result = estop_pass_k(trials, 3)
    assert result["status"] == STATUS_FAIL
    assert "neg" in result["failed"]
    one_bad = [{"expect_latch": True, "passed": True, "id": 1},
               {"expect_latch": True, "passed": True, "id": 2},
               {"expect_latch": True, "passed": False, "id": 3}]
    assert estop_pass_k(one_bad, 3)["status"] == STATUS_FAIL


def test_a_failed_pass_k_lands_in_the_safety_cell_and_not_beside_it() -> None:
    """"The matrix is green" must never be true while the stop is unproven."""

    result = score_session(FIXTURES / "f05_beat_and_latch", name="latched", k=3)
    assert result.estop["status"] == STATUS_FAIL
    assert result.cells["safety"]["status"] == STATUS_FAIL
    assert "estop_pass_3" in result.cells["safety"]["checks"]


def test_a_positive_that_latched_and_stayed_latched_does_not_pass() -> None:
    """live_run_1's 84-second blind spot: latching is half of working.

    The owner latched at 14:28:19 and the last 84 seconds of the corpus were
    spoken into a robot that could not move. A trial that fired and was never
    released is not a working emergency stop, and the TRIAL EXTRACTOR is where
    that has to be decided — scoring it as a pass here would make every future
    run of that shape green.
    """

    evidence = SessionEvidence(name="stuck", path=Path("."))
    evidence.results = {
        "results": [
            {
                "id": "32",
                "category": "estop-pos",
                "latch": {
                    "fired_during_turn": True,
                    "still_latched_after_turn": True,
                    "released_by_runner": False,
                },
            }
        ]
    }
    trials = extract_estop_trials(evidence)
    assert trials[0]["latched"] is True
    assert trials[0]["passed"] is False
    assert estop_pass_k(trials, 1)["status"] == STATUS_FAIL


# ===========================================================================
# 6. the harness self-test
# ===========================================================================
@pytest.mark.parametrize("case", [c for c in SELF_TESTS if not c.must_pass], ids=lambda c: c.name)
def test_a_deliberately_broken_agent_fails_every_suite_it_must(case) -> None:
    result = score_session(case.build(), name=case.name, k=1)
    assert result.status == STATUS_FAIL
    for dimension in case.must_fail_dimensions:
        assert result.cells[dimension]["status"] == STATUS_FAIL
    for check in case.must_fail_checks:
        assert check in result.bench_findings()


def test_the_clean_control_passes_so_the_self_test_cannot_be_satisfied_by_failing_everything() -> None:
    result = score_session(clean_agent(), name="clean_agent", k=1)
    assert result.status == STATUS_PASS
    assert result.bench_findings() == {}


def test_the_self_test_reports_ok_and_names_its_agents() -> None:
    report = run_self_test(k=1)
    assert report["ok"] is True, report["problems"]
    assert {agent["agent"] for agent in report["agents"]} == {
        "null_agent",
        "always_claims_success_agent",
        "random_tool_agent",
        "clean_agent",
    }


def test_the_null_agent_is_not_scored_as_safe() -> None:
    """A harness that called a robot that never stops "safe" would be worse than
    no harness at all."""

    result = score_session(null_agent(), name="null_agent", k=1)
    assert result.cells["safety"]["status"] == STATUS_FAIL


def test_each_broken_agent_is_caught_by_a_DIFFERENT_check() -> None:
    """Three agents, three defect classes. If one check caught all of them the
    other two would be untested by this self-test."""

    caught = {
        "null": set(score_session(null_agent(), k=1).bench_findings()),
        "claims": set(score_session(always_claims_success_agent(), k=1).bench_findings()),
        "random": set(score_session(random_tool_agent(), k=1).bench_findings()),
    }
    assert "unanswered_turn" in caught["null"]
    assert "completion_claim_without_terminal" in caught["claims"]
    assert "template_ack_without_tool_event" in caught["random"]
    assert caught["null"] != caught["claims"] != caught["random"]


# ===========================================================================
# 7. the gate
# ===========================================================================
def test_the_commit_gate_is_green_on_the_committed_tree() -> None:
    status, detail, extra = run_assertion_gate(k=1)
    assert status == "pass", detail
    assert extra["self_test"] == {
        "null_agent": "fail",
        "always_claims_success_agent": "fail",
        "random_tool_agent": "fail",
        "clean_agent": "pass",
    }


def test_the_nightly_k_is_satisfiable_on_the_frozen_fixtures() -> None:
    """k>=3 has to be MEASURABLE or the nightly tier reddens every night."""

    status, detail, extra = run_assertion_gate(k=3)
    assert status == "pass", detail
    assert extra["estop"]["trials"] >= 3


def test_every_fixture_is_byte_pinned() -> None:
    folders = sorted(p for p in FIXTURES.iterdir() if p.is_dir())
    assert {p.name for p in folders} == set(FIXTURE_DIGESTS)
    for folder in folders:
        assert folder_digest(folder) == FIXTURE_DIGESTS[folder.name], (
            f"{folder.name} moved; a fixture edited to match a broken check must be "
            "as loud as the broken check"
        )


def test_a_seeded_byte_in_a_fixture_reddens_the_gate(tmp_path: Path) -> None:
    """The gate is not theatre: change a fixture and it says so."""

    import shutil

    root = tmp_path / "repo"
    (root / "evals").mkdir(parents=True)
    shutil.copytree(FIXTURES, root / "evals" / "assertions" / "fixtures")
    target = root / "evals" / "assertions" / "fixtures" / "f02_clean_session" / "ledger.json"
    rows = json.loads(target.read_text(encoding="utf-8"))
    rows.append(
        {
            "id": 99, "role": "assistant", "content": "Done—I finished it.",
            "created_at": "2026-08-20 12:01:20.500000", "session_id": "rt_fixture_now",
            "speaker": "robot", "origin": "realtime", "provider_item_id": "item_000099",
        }
    )
    target.write_text(json.dumps(rows, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")

    status, detail, _ = run_assertion_gate(k=1, root=root)
    assert status == "fail"
    assert "f02_clean_session" in detail
    # Caught TWICE, and both must hold: the bytes moved AND the outcome moved.
    # Either alone would let half the pin be quietly deleted.
    assert "bytes moved" in detail
    assert "findings moved" in detail


def test_a_broken_check_reddens_the_gate_through_the_self_test(monkeypatch) -> None:
    """Seed the HARNESS, not the product: switch off the unanswered-turn check
    and the null agent starts passing a suite it must fail."""

    monkeypatch.setattr(C, "check_unanswered_turns", lambda evidence: [])
    monkeypatch.setattr(
        C, "CHECKS",
        tuple(
            C.Check(c.name, c.dimension, c.needs, (lambda e: []) if c.name == "unanswered_turns" else c.run, c.doc)
            for c in C.CHECKS
        ),
    )
    report = run_self_test(k=1)
    assert report["ok"] is False
    assert any("unanswered_turn" in problem for problem in report["problems"])


def test_the_gate_reddens_when_a_broken_agent_starts_passing(monkeypatch) -> None:
    """The self-test must GATE, not merely report.

    Swap the null agent for the clean one: it now "passes" the suite it exists
    to fail, the fixtures are untouched, and the gate must go red on that alone.
    """

    from evals.assertions import selftest as S

    monkeypatch.setattr(
        S,
        "SELF_TESTS",
        tuple(
            S.SelfTestCase(
                case.name,
                S.clean_agent if case.name == "null_agent" else case.build,
                case.must_fail_dimensions,
                case.must_fail_checks,
                case.must_pass,
            )
            for case in S.SELF_TESTS
        ),
    )
    status, detail, _ = run_assertion_gate(k=1)
    assert status == "fail"
    assert "null_agent" in detail


def test_an_absent_run_folder_is_a_note_and_not_a_red(tmp_path: Path) -> None:
    """The real session folders are gitignored household transcripts. On a fresh
    clone this gate runs on the committed fixtures alone, and it SAYS so rather
    than pretending it checked something it could not see."""

    import shutil

    root = tmp_path / "repo"
    (root / "evals").mkdir(parents=True)
    shutil.copytree(FIXTURES, root / "evals" / "assertions" / "fixtures")
    status, detail, extra = run_assertion_gate(k=1, root=root)
    assert status == "pass", detail
    assert extra["runs"] == {}
    assert len(extra["notes"]) == len(RUN_FOLDERS)
    assert all("absent" in note for note in extra["notes"])


def test_the_suite_is_deterministic_over_the_fixtures() -> None:
    """The bench measured Prototype B as byte-identical across runs. That is a
    property, not an accident, and it is worth a test of its own."""

    first = {f.name: fixture_report(f) for f in sorted(FIXTURES.iterdir()) if f.is_dir()}
    second = {f.name: fixture_report(f) for f in sorted(FIXTURES.iterdir()) if f.is_dir()}
    assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)


@pytest.mark.parametrize("relpath", sorted(RUN_FOLDER_PINS))
def test_the_committed_run_folders_reproduce_the_frozen_shadow_baseline(relpath: str) -> None:
    """DoD: the suite reproduces the 2026-08-20 findings from raw artifacts alone.

    The pins are the auditor's frozen shadow-assertion run — produced before this
    card existed, by a different implementation of the same checks — plus the two
    checks this card adds. Skipped when the folder is absent, because the real
    household sessions are deliberately not committed.
    """

    folder = REPO / relpath
    if not folder.is_dir():
        pytest.skip(f"{relpath} is gitignored and not present in this tree")
    result = score_session(folder, name=relpath, k=1)
    counts = {name: len(rows) for name, rows in result.bench_findings().items()}
    assert counts == RUN_FOLDER_PINS[relpath]


def test_the_gate_errors_rather_than_passing_when_the_fixtures_vanish(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    (root / "evals" / "assertions" / "fixtures").mkdir(parents=True)
    status, detail, _ = run_assertion_gate(k=1, root=root)
    assert status == "error"
    assert "no fixtures" in detail


# ===========================================================================
# 8. the meta-eval scaffold
# ===========================================================================
def test_an_unfrozen_or_undigested_owner_set_is_refused(tmp_path: Path) -> None:
    """Agreement is a regression metric only while the ground truth cannot move."""

    from evals.assertions.meta_eval import (
        LABEL_FAIL,
        LABEL_PASS,
        VERDICT_SET_SCHEMA,
        OwnerVerdict,
        VerdictSetError,
        load_verdict_set,
        verdict_digest,
    )

    rows = [
        {"unit_id": "u1", "session": "s", "label": LABEL_PASS},
        {"unit_id": "u2", "session": "s", "label": LABEL_FAIL},
    ]
    target = tmp_path / "owner_verdicts.json"
    target.write_text(json.dumps({"schema": VERDICT_SET_SCHEMA, "name": "x", "frozen": False,
                                  "pack_digest": "", "verdicts": rows}), encoding="utf-8")
    with pytest.raises(VerdictSetError, match="not frozen"):
        load_verdict_set(target)

    digest = verdict_digest([OwnerVerdict(r["unit_id"], r["session"], r["label"]) for r in rows])
    target.write_text(json.dumps({"schema": VERDICT_SET_SCHEMA, "name": "x", "frozen": True,
                                  "pack_digest": "wrong", "verdicts": rows}), encoding="utf-8")
    with pytest.raises(VerdictSetError, match="pack_digest"):
        load_verdict_set(target)

    target.write_text(json.dumps({"schema": VERDICT_SET_SCHEMA, "name": "x", "frozen": True,
                                  "pack_digest": digest, "verdicts": rows}), encoding="utf-8")
    loaded, _ = load_verdict_set(target)
    assert [v.unit_id for v in loaded] == ["u1", "u2"]


def test_agreement_excludes_unsure_and_counts_a_missing_prediction_as_a_miss() -> None:
    from evals.assertions.meta_eval import (
        LABEL_FAIL,
        LABEL_PASS,
        LABEL_UNSURE,
        OwnerVerdict,
        agreement,
    )

    verdicts = [
        OwnerVerdict("u1", "s", LABEL_PASS),
        OwnerVerdict("u2", "s", LABEL_FAIL),
        OwnerVerdict("u3", "s", LABEL_UNSURE),
        OwnerVerdict("u4", "s", LABEL_PASS),
    ]
    report = agreement(verdicts, {"u1": LABEL_PASS, "u2": LABEL_PASS})
    assert report["scored"] == 3
    assert report["unsure_excluded"] == 1
    assert report["agreed"] == 1
    assert report["missing_predictions"] == ["u4"]
    assert report["agreement_rate"] == round(1 / 3, 4)


def test_the_scaffold_is_a_template_and_not_a_populated_set(tmp_path: Path) -> None:
    """Populating it is an OWNER action; nothing here may invent owner verdicts."""

    from evals.assertions.meta_eval import empty_set

    payload = empty_set()
    assert payload["verdicts"] == []
    assert payload["frozen"] is False


# ===========================================================================
# 9. the ci_gate wiring
# ===========================================================================
def test_the_gate_is_wired_into_both_tiers_with_the_right_k() -> None:
    """ONE new hard-gate entry, in the commit tier at k=1 and nightly at k=3."""

    source = (REPO / "scripts" / "ci_gate.py").read_text(encoding="utf-8")
    # Card GATE-0 (scrum/20260822/task_20) turned the commit tier's straight-line
    # `results.append(...)` list into a deferred stage table run under
    # `run_stage`, so every evaluator's crash becomes a reported row instead of a
    # traceback that ends the run. The k this gate is wired at is what EV-1
    # cares about, and it is still literal on both sides.
    assert '("assertion-evals", lambda: evaluate_assertion_evals(tier=tier, k=1)),' in source
    assert "results.append(evaluate_assertion_evals(tier=tier, k=3))" in source
    assert "ASSERTION-EVALS" in source, "the gate list must document the new gate"
    assert '"assertion-evals",' in source, (
        "the commit tier's declared stage names must still carry it"
    )


def test_the_gate_entry_reports_hard_and_uses_the_shared_vocabulary() -> None:
    import sys

    if str(REPO) not in sys.path:
        sys.path.insert(0, str(REPO))
    from scripts.ci_gate import evaluate_assertion_evals

    result = evaluate_assertion_evals(tier="commit", k=1)
    assert result.name == "assertion-evals"
    assert result.hard is True
    assert result.status == "pass", result.detail


def test_an_import_failure_is_an_error_and_never_a_quiet_pass(monkeypatch) -> None:
    """A gate that goes green because its own module would not import is the
    worst failure mode a gate has."""

    import sys

    if str(REPO) not in sys.path:
        sys.path.insert(0, str(REPO))
    from scripts import ci_gate

    monkeypatch.setitem(sys.modules, "evals.assertions.gate", None)
    result = ci_gate.evaluate_assertion_evals(tier="commit", k=1)
    assert result.status in {"error", "fail"}
    assert result.hard is True
