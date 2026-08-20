"""Card R17 §1: the session audio tee — bounded, non-blocking, and honest.

WHAT THIS FILE PINS
-------------------
* **Default OFF.** No config block, no capture. The owner opts in in writing.
* **Fail-closed validation**, the same shape ``whisperer:`` already has: an
  unknown key refuses, a wrong type refuses, a zero cap refuses, and a
  directory inside ``evals/`` refuses — because an eval fixture is the record a
  run is scored against and a microphone tee must never be able to rewrite it.
* **Bounded three ways.** A minute cap that stops CAPTURE and never the
  session; a queue bound that drops and counts instead of growing; and a
  producer path that swallows its own failures rather than propagating them.
* **Non-blocking on the relay path.** ``accept_audio`` runs on the socket
  reader thread and ``send_audio`` runs inside ``lane.pump()``. A stalled
  writer thread and a full queue must cost the relay approximately nothing and
  must not lose a single frame ON THE LANE SIDE.
* **The index cannot drift.** Segments tile each WAV exactly, times are derived
  from byte offsets rather than measured from a clock, and
  ``verify_capture_index`` is the executable statement of both.
"""

from __future__ import annotations

import json
import threading
import time
import wave
from pathlib import Path

import pytest

from parcel_robot.realtime.audio_gateway import (
    CAPTURE_INDEX_NAME,
    CAPTURE_INDEX_SCHEMA,
    BrowserAudioGateway,
    SessionAudioCapture,
    new_capture_session_id,
    pcm_from_playback_chunk,
    verify_capture_index,
)
from parcel_robot.realtime.config import (
    CaptureConfig,
    RealtimeConfig,
    RealtimeConfigError,
    capture_config_from_mapping,
    realtime_config_from_mapping,
    resolve_capture_dir,
)
from parcel_robot.voice_audio import pcm16_wav

RATE = 24_000
FRAME = b"\x11\x22" * 480  # 20 ms of 24 kHz mono PCM16


def _capture(tmp_path: Path, **kwargs) -> SessionAudioCapture:
    kwargs.setdefault("session_id", "sess_test")
    kwargs.setdefault("sample_rate_hz", RATE)
    return SessionAudioCapture(root=tmp_path / "recordings", **kwargs)


def _settle(capture: SessionAudioCapture, timeout: float = 3.0) -> None:
    deadline = time.monotonic() + timeout
    while capture._queue and time.monotonic() < deadline:
        time.sleep(0.01)
    time.sleep(0.05)


# ============================================================== the config gate
def test_capture_is_off_unless_the_owner_writes_it_down() -> None:
    """Absent block, absent key, empty config — all the same answer: OFF."""

    assert RealtimeConfig().capture == CaptureConfig()
    assert RealtimeConfig().capture.enabled is False
    assert capture_config_from_mapping(None).enabled is False
    assert realtime_config_from_mapping({"enabled": True, "mode": "audio"}).capture.enabled is False
    # And it is visible in the snapshot rather than implied by an absent key.
    assert realtime_config_from_mapping({}).as_dict()["capture"] == {
        "enabled": False,
        "dir": "recordings",
        "max_minutes": 30.0,
        "owner_gap_s": 0.75,
    }


@pytest.mark.parametrize(
    "block, fragment",
    [
        ({"enabled": True, "max_minuets": 5}, "unknown realtime.capture key"),
        ({"enabled": "ture"}, "must be a boolean"),
        ({"max_minutes": 0}, "greater than zero"),
        ({"max_minutes": -3}, "greater than zero"),
        ({"max_minutes": "ten"}, "must be a number"),
        ({"owner_gap_s": -1}, "must not be negative"),
        ({"dir": ""}, "non-empty string"),
        ({"dir": 7}, "non-empty string"),
    ],
)
def test_a_typo_in_the_capture_block_is_a_refusal(block: dict, fragment: str) -> None:
    """Same discipline as every other config surface here. A typo is not a default."""

    with pytest.raises(RealtimeConfigError, match=fragment):
        realtime_config_from_mapping({"enabled": True, "capture": block})


def test_capture_may_never_be_pointed_at_the_eval_tree() -> None:
    """SEED-shaped: recordings inside evals/ would rewrite the record being scored."""

    for target in ("evals", "evals/20260820", "evals/20260820/voice_corpus_v1/live_run_1"):
        with pytest.raises(RealtimeConfigError, match="inside"):
            resolve_capture_dir(target)
        with pytest.raises(RealtimeConfigError, match="inside"):
            realtime_config_from_mapping({"capture": {"enabled": True, "dir": target}})
    # The refusal is at LOAD, so an operator reads it before a mic ever opens.
    assert resolve_capture_dir("recordings").name == "recordings"


def test_a_relative_capture_dir_never_depends_on_the_cwd(monkeypatch, tmp_path: Path) -> None:
    """live_run_1's doubled-prefix artifact path came from exactly this mistake."""

    first = resolve_capture_dir("recordings")
    monkeypatch.chdir(tmp_path)
    assert resolve_capture_dir("recordings") == first


# =========================================================== the capture engine
def test_the_index_tiles_both_files_exactly(tmp_path: Path) -> None:
    """The whole point: a byte range in the index IS that audio in the WAV."""

    capture = _capture(tmp_path, owner_gap_s=0.05)
    capture.start()
    for _ in range(4):
        capture.offer_owner(FRAME)
    capture.begin_utterance(1)
    speech = b"\x33\x44" * 960
    capture.offer_robot(pcm16_wav(speech, sample_rate_hz=RATE))
    _settle(capture)
    time.sleep(0.12)  # longer than owner_gap_s: the next frame cuts a new segment
    capture.offer_owner(FRAME)
    capture.begin_utterance(2)
    capture.offer_robot(pcm16_wav(speech, sample_rate_hz=RATE))
    capture.close("test")

    index = json.loads(capture.index_path.read_text(encoding="utf-8"))
    assert index["schema"] == CAPTURE_INDEX_SCHEMA
    assert verify_capture_index(index, session_dir=capture.directory) == []

    owner = index["streams"]["owner"]
    assert owner["data_bytes"] == 5 * len(FRAME)
    assert [segment["frames"] for segment in owner["segments"]] == [4, 1]
    assert owner["segments"][0]["start_byte"] == 0
    assert owner["segments"][0]["end_byte"] == owner["segments"][1]["start_byte"]
    assert owner["segments"][-1]["end_byte"] == owner["data_bytes"]

    robot = index["streams"]["robot"]
    assert [segment["utterance"] for segment in robot["segments"]] == [1, 2]
    assert robot["data_bytes"] == 2 * len(speech)

    # And the extracted range really is the audio: cut utterance 2 out by bytes.
    with wave.open(str(capture.directory / "robot.wav"), "rb") as handle:
        raw = handle.readframes(handle.getnframes())
    cut = robot["segments"][1]
    assert raw[cut["start_byte"] : cut["end_byte"]] == speech


def test_the_verifier_catches_an_index_that_drifts(tmp_path: Path) -> None:
    """SEED: a tee that writes bytes without extending the segment is invisible
    to every other check in this file. The verifier is what sees it."""

    capture = _capture(tmp_path)
    capture.start()
    capture.offer_owner(FRAME)
    capture.close("test")
    good = json.loads(capture.index_path.read_text(encoding="utf-8"))
    assert verify_capture_index(good, session_dir=capture.directory) == []

    # 1. audio the index does not account for
    drifted = json.loads(json.dumps(good))
    drifted["streams"]["owner"]["segments"][-1]["end_byte"] -= 160
    problems = verify_capture_index(drifted)
    assert any("unindexed" in problem for problem in problems)

    # 2. a hole between two segments
    holed = json.loads(json.dumps(good))
    holed["streams"]["owner"]["segments"][0]["start_byte"] = 64
    assert any("does not tile" in problem for problem in verify_capture_index(holed))

    # 3. a time that no longer matches its byte offset
    stamped = json.loads(json.dumps(good))
    stamped["streams"]["owner"]["segments"][-1]["t1_s"] += 0.5
    assert any("does not match byte offset" in p for p in verify_capture_index(stamped))

    # 4. a header patched to the wrong size
    (capture.directory / "owner.wav").write_bytes(
        (capture.directory / "owner.wav").read_bytes() + b"\x00\x00"
    )
    assert any("payload bytes" in p for p in verify_capture_index(good, session_dir=capture.directory))


def test_capture_stops_itself_at_the_cap_and_says_so(tmp_path: Path) -> None:
    """SEED: capture unbounded. The cap stops CAPTURE, never the session."""

    notes: list[str] = []
    capture = _capture(tmp_path, max_minutes=1 / 60.0, on_event=notes.append)  # 1 second
    capture.start()
    for _ in range(200):  # 4 seconds of audio offered at a 1 second cap
        capture.offer_owner(FRAME)
        time.sleep(0.001)
    _settle(capture)

    assert capture.stopped_reason == "max_minutes_reached"
    assert capture.running is False
    assert capture.snapshot()["owner_seconds"] == pytest.approx(1.0, abs=0.05)
    assert capture.frames_dropped_after_stop > 0
    assert any("cap" in note and "UNAFFECTED" in note for note in notes)

    # The bounded file is still a VALID, indexed recording, not a truncated mess.
    index = json.loads(capture.index_path.read_text(encoding="utf-8"))
    assert index["stopped_reason"] == "max_minutes_reached"
    assert verify_capture_index(index, session_dir=capture.directory) == []
    with wave.open(str(capture.directory / "owner.wav"), "rb") as handle:
        assert handle.getnframes() == index["streams"]["owner"]["data_bytes"] // 2

    # And offering more after the cap is a counted no-op, never an exception.
    assert capture.offer_owner(FRAME) is False


def test_a_full_queue_drops_and_counts_and_never_grows(tmp_path: Path) -> None:
    """SEED: the tee's queue is bounded. Nothing here may wait for a disk."""

    capture = _capture(tmp_path, max_queue_frames=4)
    capture._running = True  # armed with NO writer thread: nothing ever drains
    for _ in range(100):
        assert capture.offer_owner(FRAME) in (True, False)
    assert len(capture._queue) == 4
    assert capture.frames_dropped_queue_full == 96
    assert capture.snapshot()["queued"] == 4


def test_nothing_captured_leaves_nothing_behind(tmp_path: Path) -> None:
    capture = _capture(tmp_path)
    capture.start()
    capture.begin_utterance(1)  # a marker with no audio after it
    capture.close("test")
    assert not capture.directory.exists()


def test_playback_chunks_are_unwrapped_into_one_continuous_stream() -> None:
    """The lane wraps EVERY chunk in its own RIFF header; concatenating them
    would put a header every 240 ms inside the recording."""

    pcm = b"\x01\x02" * 100
    assert pcm_from_playback_chunk(pcm16_wav(pcm, sample_rate_hz=RATE)) == pcm
    assert pcm_from_playback_chunk(pcm) == pcm  # raw PCM passes through
    assert pcm_from_playback_chunk(b"") == b""
    assert pcm_from_playback_chunk(b"RIFF") == b"RIFF"


def test_capture_session_ids_are_sortable_and_unique() -> None:
    first = new_capture_session_id()
    assert first.startswith("sess_") and first != new_capture_session_id()


# =================================================== the relay-path contract
def test_the_tee_never_slows_the_relay_down(tmp_path: Path, monkeypatch) -> None:
    """SEED: the tee blocks the relay.

    The two producer call sites are the socket reader thread and ``lane.pump()``.
    Here the writer thread is wedged inside a single drain and the queue is
    tiny, which is the worst case a slow disk can produce. Every relay call must
    still return in microseconds and EVERY frame must still reach the lane.
    """

    wedged = threading.Event()

    def _wedge(self: SessionAudioCapture) -> None:
        wedged.set()
        time.sleep(2.0)

    monkeypatch.setattr(SessionAudioCapture, "_drain", _wedge, raising=True)
    capture = _capture(tmp_path, max_queue_frames=2)
    capture.start()

    heard: list[bytes] = []
    gateway = BrowserAudioGateway(on_audio=heard.append, capture=capture)
    gateway.start()
    gateway.bind_token("token")
    conn = gateway.attach("token")
    conn.mic_open = True
    capture.offer_owner(FRAME)  # gives the writer thread something to wedge on
    assert wedged.wait(2.0), "the writer thread never started"

    started = time.monotonic()
    for _ in range(200):
        assert gateway.accept_audio(conn, FRAME) is True
    elapsed = time.monotonic() - started

    assert len(heard) == 200, "the lane lost frames to the tee"
    assert elapsed < 0.5, f"the tee added {elapsed:.2f}s of latency to 200 relay frames"
    assert capture.frames_dropped_queue_full > 0
    gateway.stop()


def test_a_broken_tee_disables_itself_instead_of_breaking_the_lane(tmp_path: Path) -> None:
    """SEED: an exception in the tee must never reach ``accept_audio``/``pump``."""

    def _explode() -> float:
        raise OSError("the clock is on fire")

    capture = _capture(tmp_path, wall_clock=_explode)
    capture._running = True
    heard: list[bytes] = []
    gateway = BrowserAudioGateway(on_audio=heard.append, capture=capture)
    gateway.bind_token("token")
    gateway._running = True
    conn = gateway.attach("token")
    conn.mic_open = True

    assert gateway.accept_audio(conn, FRAME) is True  # the relay is unharmed
    assert heard == [FRAME]
    assert capture.writer_errors == 1
    assert capture.running is False

    # send_audio is the other half, and it may never raise either.
    gateway.send_audio(pcm16_wav(b"\x00\x01" * 10, sample_rate_hz=RATE))
    assert gateway.snapshot()["frames_out"] == 1


# ================================================== the tee through the gateway
def test_the_gateway_records_both_directions_through_the_real_relay(tmp_path: Path) -> None:
    capture = _capture(tmp_path, owner_gap_s=5.0)
    heard: list[bytes] = []
    gateway = BrowserAudioGateway(on_audio=heard.append, capture=capture)
    gateway.bind_token("token")
    gateway.start()
    conn = gateway.attach("token")
    conn.mic_open = True

    gateway.accept_audio(conn, FRAME)
    gateway.accept_audio(conn, FRAME)
    gateway.begin_utterance()
    speech = b"\x55\x66" * 480
    gateway.send_audio(pcm16_wav(speech, sample_rate_hz=RATE))
    gateway.interrupt()
    gateway.stop()

    index = json.loads((capture.directory / CAPTURE_INDEX_NAME).read_text(encoding="utf-8"))
    assert verify_capture_index(index, session_dir=capture.directory) == []
    with wave.open(str(capture.directory / "owner.wav"), "rb") as handle:
        assert handle.readframes(handle.getnframes()) == FRAME * 2
    with wave.open(str(capture.directory / "robot.wav"), "rb") as handle:
        assert handle.readframes(handle.getnframes()) == speech
    robot_segments = index["streams"]["robot"]["segments"]
    assert robot_segments[0]["utterance"] == 1
    assert robot_segments[0]["interrupted"] is True
    assert gateway.snapshot()["capture"]["session_id"] == "sess_test"


def test_a_gateway_without_capture_says_so_and_behaves_exactly_as_before() -> None:
    """Default OFF is a stated fact in /api/state, not an absent key."""

    heard: list[bytes] = []
    gateway = BrowserAudioGateway(on_audio=heard.append)
    gateway.bind_token("token")
    gateway.start()
    conn = gateway.attach("token")
    conn.mic_open = True
    assert gateway.accept_audio(conn, FRAME) is True
    gateway.begin_utterance()
    gateway.send_audio(pcm16_wav(b"\x00\x01" * 10, sample_rate_hz=RATE))
    gateway.interrupt()
    gateway.stop()
    assert heard == [FRAME]
    assert gateway.snapshot()["capture"] == {"enabled": False}


def test_the_robot_half_records_even_when_no_browser_is_listening(tmp_path: Path) -> None:
    """The file answers 'what did the robot say', not 'what came out of a speaker'."""

    capture = _capture(tmp_path)
    gateway = BrowserAudioGateway(on_audio=lambda _frame: None, capture=capture)
    gateway.start()
    gateway.begin_utterance()
    speech = b"\x07\x08" * 240
    gateway.send_audio(pcm16_wav(speech, sample_rate_hz=RATE))
    gateway.stop()

    assert gateway.snapshot()["frames_dropped_no_client"] == 1
    with wave.open(str(capture.directory / "robot.wav"), "rb") as handle:
        assert handle.readframes(handle.getnframes()) == speech


def test_the_index_survives_a_process_that_is_killed_rather_than_closed(tmp_path: Path) -> None:
    """Found by this card's own live proof: the stack was killed, both WAVs
    survived intact and the index — written only at close — was simply absent.

    The index is now flushed at every segment boundary, and a mid-session index
    includes the segment still being written, so the tiling invariant holds at
    every instant instead of only after a clean shutdown.
    """

    capture = _capture(tmp_path, owner_gap_s=0.05)
    capture.start()
    capture.offer_owner(FRAME)
    capture.begin_utterance(1)
    capture.offer_robot(pcm16_wav(b"\x21\x22" * 480, sample_rate_hz=RATE))
    capture.begin_utterance(2)  # a second boundary: the flush has happened
    capture.offer_robot(pcm16_wav(b"\x23\x24" * 480, sample_rate_hz=RATE))
    _settle(capture)

    # NO close() — this is the killed-process case.
    index = json.loads(capture.index_path.read_text(encoding="utf-8"))
    assert verify_capture_index(index, session_dir=capture.directory) == []
    assert index["streams"]["owner"]["segments"][-1]["open"] is True
    assert index["streams"]["robot"]["data_bytes"] == 2 * 960
    with wave.open(str(capture.directory / "robot.wav"), "rb") as handle:
        assert handle.getnframes() == 960  # the header is patched too, every batch
