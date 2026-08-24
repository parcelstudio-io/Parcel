"""Card MARK-1: the browser's half of an honest interruption, and which ear it opens.

WHAT THIS FILE PINS
-------------------
* **The played-ack timer exists in the shipped panel.** ``ui/index.html`` is
  never executed by any test on this host — there is no browser and no DOM — so
  R7's technique applies: the JS is pinned by source assertion, and the Python
  port that the measurement rig in ``test_mark1_barge_in_mark.py`` actually runs
  is pinned to the same lines. If the two ever drift, the numbers in
  ``MARK1_STATUS.md`` stop being about the shipped panel and this file goes red.
* **The played clock only moves forward inside one reply.** Heard audio does not
  un-hear itself, so an ack that reports less than an earlier ack for the same
  utterance is dropped and counted rather than trusted. This is the server-side
  backstop for a browser whose own bookkeeping is wrong — including the one that
  shipped before MARK-1.
* **One final ack after an interrupt, for the record and for nothing else.**
* **Which ear the browser opened is always recorded and only refused against a
  pin.** The reSpeaker XVF3800 presents two capture channels (measured on this
  host: ``hw:2,0`` is S16_LE / 16 kHz / ``CHANNELS: 2``); asking for one makes
  the stack average the conference beam and the ASR beam together. The gateway
  now says which beam it wants in ``hello`` and the browser reports which it
  got. Unpinned — the shipped default — nothing is refused, because taking the
  owner's microphone away over a beam index is a worse failure than a worse
  microphone, and the fix is a commissioning step (card AIR-1).
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from parcel_robot.realtime.audio_gateway import BrowserAudioGateway

REPO = Path(__file__).resolve().parents[1]
PANEL = REPO / "src" / "parcel_robot" / "ui" / "index.html"
TOKEN = "panel-token-mark1"


def _panel() -> str:
    return PANEL.read_text(encoding="utf-8")


#: A real ECMAScript engine, if this host has one. ``gjs`` (SpiderMonkey) is
#: present on this box; ``node`` is not. Where it exists, the panel's own
#: expressions are EVALUATED rather than pattern-matched — see
#: :func:`_eval_wants`.
JS_ENGINE = shutil.which("gjs") or shutil.which("node") or shutil.which("qjs")


def _wants_expression() -> str:
    """Lift ``armEar``'s pin test out of the shipped panel, verbatim.

    Extracted rather than restated: a test that re-typed the expression would
    pass while the panel shipped a different one, which is exactly the class of
    mistake this test exists to catch.
    """

    panel = _panel()
    body = panel[panel.index("async function armEar(mic, pin) {") :]
    match = re.search(r"^\s*const wants = .*;$", body, re.MULTILINE)
    assert match, "armEar must decide whether a beam is pinned in one `const wants` line"
    return match.group(0).strip()


def _eval_wants(pin: dict | None, tmp_path: Path) -> object:
    """Run the panel's own pin test, in a real JS engine, against one hello."""

    script = tmp_path / "wants.js"
    script.write_text(
        "function wantsOf(pin) {\n"
        f"  {_wants_expression()}\n"
        "  return wants;\n"
        "}\n"
        f"print(JSON.stringify({{ wants: wantsOf({json.dumps(pin)}) }}));\n",
        encoding="utf-8",
    )
    proc = subprocess.run(
        [JS_ENGINE, str(script)], capture_output=True, text=True, check=False, timeout=60
    )
    assert proc.returncode == 0, f"{JS_ENGINE} failed: {proc.stderr.strip()}"
    return json.loads(proc.stdout.strip())["wants"]


class _Clock:
    def __init__(self, start: float = 1_000.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> float:
        self.now += seconds
        return self.now


def _gateway(**kwargs) -> tuple[BrowserAudioGateway, list[bool]]:
    """A started, token-bound gateway plus the list its mic hook writes into."""

    arms: list[bool] = []
    gateway = BrowserAudioGateway(
        on_audio=lambda _pcm: None,
        on_mic=arms.append,
        **kwargs,
    )
    gateway.bind_token(TOKEN)
    gateway.start()
    return gateway, arms


# ============================================ A. the shipped panel acks on a timer
def test_the_panel_reports_what_was_heard_on_a_timer_not_only_on_arrival() -> None:
    """The defect was a REPORTING schedule, so the schedule is what is pinned."""

    panel = _panel()
    assert "const PLAYED_ACK_INTERVAL_MS = 100;" in panel
    assert "mic.ackTimer = setInterval(() => {" in panel
    assert "const rendering = mic.playAt > mic.playback.currentTime;" in panel
    assert "          sendPlayed(mic, false);" in panel
    assert "}, PLAYED_ACK_INTERVAL_MS);" in panel
    # And it dies with the microphone it reports on.
    assert "try { if (mic.ackTimer) clearInterval(mic.ackTimer); } catch (_) {}" in panel


def test_the_panel_says_so_once_when_its_schedule_runs_dry() -> None:
    """Correction pass, defect 3. The timer goes quiet exactly when it matters.

    A timer that only reports WHILE audio renders stops reporting at the one
    moment the audio clock and the wall clock diverge, and the gateway then
    extrapolates the played position forward through silence. One ack on the
    drain EDGE (once, not every tick) is what lets the gateway freeze instead.
    """

    panel = _panel()
    assert "const rendering = mic.playAt > mic.playback.currentTime;" in panel
    assert "} else if (mic.wasRendering) {" in panel
    assert "sendPlayed(mic, true);" in panel
    assert "mic.wasRendering = rendering;" in panel
    assert 'type: "played", utterance: mic.utterance, ms: playedMs(mic), drained: !!drained,' in panel
    # The arrival ack is a RESUMPTION and must never be flagged drained.
    assert "sendPlayed(mic, false);" in panel


def test_the_panels_played_position_is_scheduled_minus_not_yet_played() -> None:
    """The formula, and the absence of the one it replaces.

    ``currentTime - playStart`` is only the heard position while playback is
    unbroken; ``playStart`` is re-stamped on every underrun, so mid-reply it
    reported ~0. Its absence from the panel is the seeded-RED anchor for the
    browser half of this card: put that expression back and this test fails.
    """

    panel = _panel()
    assert "function playedMs(mic) {" in panel
    assert "const remaining = Math.max(0, (mic.playAt - mic.playback.currentTime) * 1000);" in panel
    assert (
        "return Math.max(0, Math.min(mic.scheduledMs, mic.scheduledMs - remaining));" in panel
    )
    assert "mic.scheduledMs += audio.duration * 1000;" in panel
    assert "(mic.playback.currentTime - mic.playStart) * 1000" not in panel, (
        "the arrival-only formula is the defect; it must not be in the shipped panel"
    )


def test_the_panel_sends_one_last_position_before_it_throws_the_state_away() -> None:
    panel = _panel()
    stop = panel[panel.index("function stopPlayback(mic) {") :]
    stop = stop[: stop.index("\n    }")]
    assert "sendPlayed(mic, true);" in stop
    assert stop.index("sendPlayed(mic, true);") < stop.index("mic.sources.splice(0)"), (
        "the final position must be read before the sources that define it are stopped"
    )
    assert "mic.scheduledMs = 0;" in stop


def test_the_python_port_of_the_panel_uses_the_same_two_numbers() -> None:
    """The rig's headless browser is a PORT. This is the link, asserted.

    ``test_mark1_barge_in_mark.py`` measures a Python object, and every number in
    ``MARK1_STATUS.md`` comes from it. The claim that those numbers describe the
    shipped panel rests entirely on the port being faithful, so the two
    expressions that matter are checked against each other here rather than
    trusted.
    """

    from tests.test_mark1_barge_in_mark import _HeadlessBrowser

    port = _HeadlessBrowser.position_ms.__doc__ or ""
    assert port, "the port's position formula must be documented"
    source = Path(__file__).with_name("test_mark1_barge_in_mark.py").read_text(encoding="utf-8")
    assert "remaining = max(0.0, (self.play_at - self.context.current_time) * 1000.0)" in source
    assert "return max(0.0, min(self.scheduled_ms, self.scheduled_ms - remaining))" in source
    # ...and the panel's two lines, again, so a change to either side fails here.
    panel = _panel()
    assert "const remaining = Math.max(0, (mic.playAt - mic.playback.currentTime) * 1000);" in panel
    assert (
        "return Math.max(0, Math.min(mic.scheduledMs, mic.scheduledMs - remaining));" in panel
    )


# ==================================== B. the played clock only moves forward
def test_an_ack_that_walks_the_played_clock_backwards_is_dropped_and_counted() -> None:
    """Card MARK-1's server-side backstop, and its seeded RED.

    Delete the ``clamped < self._played_ack_ms`` guard in ``ack_played`` and the
    second ack below re-anchors the clock 400 ms later, which is exactly how the
    shipped panel dragged a truncate point back into the middle of a reply.
    """

    clock = _Clock()
    gateway, _arms = _gateway(clock=clock)
    gateway.attach(TOKEN)
    gateway.begin_utterance()
    gateway.send_audio(b"\x00" * 48_000)  # 1 000 ms transmitted
    clock.advance(0.5)
    assert gateway.ack_played(1, 500.0) is True
    anchor = gateway.played_started_monotonic
    assert anchor is not None

    assert gateway.ack_played(1, 100.0) is False, "heard audio does not un-hear itself"
    assert gateway.snapshot()["regressive_acks"] == 1
    assert gateway.played_started_monotonic == pytest.approx(anchor), "the anchor must not move"

    # Forward is still forward.
    clock.advance(0.3)
    assert gateway.ack_played(1, 800.0) is True
    assert gateway.snapshot()["played_acks"] == 2
    assert gateway.snapshot()["regressive_acks"] == 1


def test_the_monotonic_floor_is_per_utterance_not_per_session() -> None:
    """Otherwise the second reply is pinned at the first reply's length."""

    gateway, _arms = _gateway()
    gateway.attach(TOKEN)
    gateway.begin_utterance()
    gateway.send_audio(b"\x00" * 48_000)
    assert gateway.ack_played(1, 900.0) is True
    gateway.begin_utterance()
    gateway.send_audio(b"\x00" * 48_000)
    assert gateway.ack_played(2, 40.0) is True, "a new reply starts from zero heard"
    assert gateway.snapshot()["regressive_acks"] == 0


def test_the_one_ack_after_an_interrupt_is_recorded_and_anchors_nothing() -> None:
    gateway, _arms = _gateway()
    gateway.attach(TOKEN)
    gateway.begin_utterance()
    gateway.send_audio(b"\x00" * 48_000)  # 1 000 ms transmitted
    assert gateway.ack_played(1, 300.0) is True
    gateway.interrupt()
    assert gateway.played_started_monotonic is None

    assert gateway.ack_played(1, 900.0) is False, "a final ack never re-anchors a dead utterance"
    snapshot = gateway.snapshot()
    assert snapshot["final_acks"] == 1
    assert snapshot["last_final_played_ms"] == pytest.approx(900.0)
    assert snapshot["stale_acks"] == 0
    assert gateway.played_started_monotonic is None

    # Correction pass, defect 6: FOLDED, not latched. A later post-interrupt ack
    # that reports MORE heard audio replaces the earlier one.
    assert gateway.ack_played(1, 950.0) is False
    assert gateway.snapshot()["final_acks"] == 2
    assert gateway.snapshot()["last_final_played_ms"] == pytest.approx(950.0)
    assert gateway.snapshot()["stale_acks"] == 0


def test_a_final_ack_cannot_claim_more_than_was_transmitted_either() -> None:
    gateway, _arms = _gateway()
    gateway.attach(TOKEN)
    gateway.begin_utterance()
    gateway.send_audio(b"\x00" * 4_800)  # 100 ms transmitted
    gateway.interrupt()
    assert gateway.ack_played(1, 999_999.0) is False
    assert gateway.snapshot()["last_final_played_ms"] == pytest.approx(100.0)


# ================================================= C. which ear did you open
def test_the_hello_says_which_ear_to_open_and_which_beam_is_the_one() -> None:
    unpinned, _arms = _gateway()
    assert unpinned.hello()["capture"] == {"channels": 1, "beam": None}

    pinned, _arms2 = _gateway(capture_channels=2, capture_beam=1)
    assert pinned.hello()["capture"] == {"channels": 2, "beam": 1}
    # ``input`` still describes the PCM the browser must SEND. Two questions.
    assert pinned.hello()["input"]["channels"] == 1


def test_a_downmixed_ear_is_refused_when_a_beam_is_pinned() -> None:
    """Pre-registered R3b, and the seeded RED for the pin.

    Delete the ``_check_capture_pin`` call in ``set_mic`` and the downmix below
    is accepted silently, which is the state this card found the panel in.
    """

    gateway, arms = _gateway(capture_channels=2, capture_beam=1)
    conn = gateway.attach(TOKEN)
    conn.drain()

    assert gateway.set_mic(conn, True, channels=1, beam=0) is False
    assert conn.mic_open is False
    snapshot = gateway.snapshot()
    assert snapshot["capture_pin_refusals"] == 1
    assert snapshot["mic_opens"] == 0
    assert snapshot["capture_channels_reported"] == 1
    assert arms == [], "a mic that is going to be refused must not open a paid session first"
    refusal = [json.loads(f) for f in conn.drain() if isinstance(f, str)][-1]
    assert refusal["type"] == "mic" and refusal["on"] is False
    assert "downmixed" in refusal["reason"]


def test_the_pinned_beam_arms_the_microphone() -> None:
    gateway, arms = _gateway(capture_channels=2, capture_beam=1)
    conn = gateway.attach(TOKEN)
    assert gateway.set_mic(conn, True, channels=2, beam=1) is True
    assert conn.mic_open is True
    assert arms == [True]
    snapshot = gateway.snapshot()
    assert snapshot["capture_pin_refusals"] == 0
    assert snapshot["capture_beam_reported"] == 1
    assert snapshot["capture_channels_reported"] == 2


def test_the_wrong_beam_of_a_wide_enough_ear_is_still_refused() -> None:
    gateway, _arms = _gateway(capture_channels=2, capture_beam=1)
    conn = gateway.attach(TOKEN)
    assert gateway.set_mic(conn, True, channels=2, beam=0) is False
    assert gateway.snapshot()["capture_pin_refusals"] == 1


def test_a_client_that_says_nothing_about_its_ear_is_refused_only_by_a_pin() -> None:
    """The shipped default accepts the pre-MARK-1 client. A pin does not."""

    unpinned, arms = _gateway()
    conn = unpinned.attach(TOKEN)
    assert unpinned.set_mic(conn, True) is True, "no pin ⇒ no refusal, exactly as before"
    assert unpinned.snapshot()["capture_pin_refusals"] == 0
    assert arms == [True]

    pinned, arms2 = _gateway(capture_channels=2, capture_beam=1)
    conn2 = pinned.attach(TOKEN)
    assert pinned.set_mic(conn2, True) is False
    assert pinned.snapshot()["capture_pin_refusals"] == 1
    assert arms2 == []


def test_the_ear_the_browser_reports_is_recorded_even_with_no_pin() -> None:
    """Refusing is optional. Knowing what microphone this was is not."""

    gateway, _arms = _gateway()
    conn = gateway.attach(TOKEN)
    gateway.handle_control(conn, json.dumps({"type": "mic", "on": True, "channels": 2, "beam": 1}))
    snapshot = gateway.snapshot()
    assert snapshot["mic_opens"] == 1
    assert snapshot["capture_channels_reported"] == 2
    assert snapshot["capture_beam_reported"] == 1
    assert snapshot["capture_pin_refusals"] == 0


def test_the_panel_asks_for_the_pinned_beam_and_sends_the_one_it_got() -> None:
    panel = _panel()
    assert "async function armEar(mic, pin) {" in panel
    assert "await track.applyConstraints({" in panel
    assert "channelCount: Number(wants.channels) || 2," in panel
    # The array does AEC and NS on-chip; Chrome's AEC3 downmixes to mono to work.
    assert "echoCancellation: false," in panel
    assert 'type: "mic", on: true, channels: mic.captureChannels, beam: mic.beam,' in panel
    # ...and the capture graph actually takes that channel rather than an average.
    assert (
        "mic.processor = mic.capture.createScriptProcessor(frames, mic.captureChannels, 1);"
        in panel
    )
    assert "const ear = Math.min(mic.beam, event.inputBuffer.numberOfChannels - 1);" in panel
    assert "event.inputBuffer.getChannelData(ear)" in panel
    assert "event.inputBuffer.getChannelData(0)" not in panel, (
        "channel 0 is the conference beam; taking it unconditionally is the defect"
    )


# ========== D. the unpinned hello must not touch the owner's microphone (gjs)
@pytest.mark.skipif(JS_ENGINE is None, reason="no ECMAScript engine on this host")
def test_the_unpinned_hello_leaves_the_microphone_alone(tmp_path: Path) -> None:
    """The correction pass's blocker, evaluated in a real engine.

    The gateway the runtime builds is UNPINNED (``runtime.py`` constructs
    ``BrowserAudioGateway`` with neither ``capture_channels`` nor
    ``capture_beam``), so the hello every owner session actually receives is
    ``capture: {"channels": 1, "beam": null}``.

    ``Number.isFinite(Number(null))`` is ``true`` — ECMA-262 ToNumber(null) is
    ``+0``. The first version of ``armEar`` used exactly that test, so on the
    shipped hello it treated "no pin" as "pin channel 0" and ran
    ``applyConstraints({channelCount: 1, echoCancellation: false, ...})`` on the
    owner's microphone on the first click. With no array AEC reference routed
    yet (card AIR-1), Chrome's AEC3 is the only echo canceller in the loop, so
    that is the robot barging in on its own voice for a whole owner session.

    The expression is lifted out of ``index.html`` and evaluated, not restated.
    Seed: put ``Number.isFinite(Number(pin.beam))`` back and this goes RED.
    """

    shipped = _eval_wants(_gateway()[0].hello()["capture"], tmp_path)
    assert shipped is None, (
        "the SHIPPED hello must read as 'no pin': anything else runs applyConstraints "
        "and turns Chrome's AEC off on the owner's microphone"
    )

    pinned_hello = _gateway(capture_channels=2, capture_beam=1)[0].hello()["capture"]
    assert _eval_wants(pinned_hello, tmp_path) == pinned_hello, "a real pin must still arm"

    # Beam 0 is a legitimate pin and must be distinguishable from no pin at all.
    assert _eval_wants({"channels": 2, "beam": 0}, tmp_path) == {"channels": 2, "beam": 0}
    # ...and a hello with no capture block at all is no pin.
    assert _eval_wants(None, tmp_path) is None


@pytest.mark.skipif(JS_ENGINE is None, reason="no ECMAScript engine on this host")
def test_the_engine_agrees_that_the_old_test_would_have_been_wrong(tmp_path: Path) -> None:
    """The defect itself, reproduced, so the fix is not a claim about nothing."""

    script = tmp_path / "coercion.js"
    script.write_text(
        'print(JSON.stringify({'
        ' finite: Number.isFinite(Number(null)),'
        ' integer: Number.isInteger(null),'
        ' number: Number(null) }));\n',
        encoding="utf-8",
    )
    proc = subprocess.run(
        [JS_ENGINE, str(script)], capture_output=True, text=True, check=False, timeout=60
    )
    assert proc.returncode == 0, proc.stderr
    verdict = json.loads(proc.stdout.strip())
    assert verdict == {"finite": True, "integer": False, "number": 0}


# ========== E. AIR-1's handoff: an interrupted reply says WHEN it was cut
def test_an_interrupted_robot_segment_carries_the_moment_it_was_cut(tmp_path) -> None:
    """Correction pass, defect 5 — AIR-1 (task_25) reads this field.

    ``interrupted: true`` answers "was this reply cut off". Through-air barge-in
    is a LATENCY measurement: the owner's voice reaches the array at one instant
    and this WAV stops at another, and without a stamp the second instant can
    only be recovered by counting bytes and trusting the tee never dropped one.

    ``interrupted_at`` is the wall clock ``_offer`` read on the RELAY thread —
    the moment ``interrupt()`` ran — not the moment the writer thread reached
    the queue entry, which can be a whole drain batch later. Seed: drop the
    ``wall`` argument at the caller and this goes RED.
    """

    import wave

    from parcel_robot.audio.voice_loop import pcm16_wav
    from parcel_robot.realtime.audio_gateway import (
        CAPTURE_INDEX_NAME,
        SessionAudioCapture,
    )

    capture = SessionAudioCapture(
        root=tmp_path / "recordings", session_id="sess_mark1", sample_rate_hz=24_000
    )
    gateway, _arms = _gateway(capture=capture)
    conn = gateway.attach(TOKEN)
    conn.mic_open = True
    gateway.begin_utterance()
    gateway.send_audio(pcm16_wav(b"\x55\x66" * 480, sample_rate_hz=24_000))
    gateway.interrupt()
    gateway.stop()

    index = json.loads((capture.directory / CAPTURE_INDEX_NAME).read_text(encoding="utf-8"))
    segment = index["streams"]["robot"]["segments"][0]
    assert segment["interrupted"] is True
    assert segment.get("interrupted_at"), "AIR-1 cannot time a barge-in without this"
    # It is a real instant on the same clock as the segment's own bounds, and it
    # falls inside them.
    assert segment["started_at"] <= segment["interrupted_at"] <= segment["ended_at"]
    # ...and it names the byte, so the cut can be found in the WAV itself.
    assert segment["interrupted_byte"] == segment["end_byte"]
    with wave.open(str(capture.directory / "robot.wav"), "rb") as handle:
        assert handle.getnframes() > 0


def test_an_uninterrupted_segment_gains_no_interrupt_stamp(tmp_path) -> None:
    """The field is evidence, not decoration: absent when nothing was cut."""

    from parcel_robot.audio.voice_loop import pcm16_wav
    from parcel_robot.realtime.audio_gateway import (
        CAPTURE_INDEX_NAME,
        SessionAudioCapture,
    )

    capture = SessionAudioCapture(
        root=tmp_path / "recordings", session_id="sess_mark1", sample_rate_hz=24_000
    )
    gateway, _arms = _gateway(capture=capture)
    gateway.attach(TOKEN)
    gateway.begin_utterance()
    gateway.send_audio(pcm16_wav(b"\x11\x22" * 480, sample_rate_hz=24_000))
    gateway.stop()

    index = json.loads((capture.directory / CAPTURE_INDEX_NAME).read_text(encoding="utf-8"))
    segment = index["streams"]["robot"]["segments"][0]
    assert segment["interrupted"] is False
    assert "interrupted_at" not in segment


def test_a_timer_ack_in_flight_cannot_steal_the_final_position(tmp_path) -> None:
    """Correction pass, defect 6 — and its seeded RED.

    ``interrupt()`` clears ``_first_send_at`` at once, but on a real socket the
    browser's ~100 ms timer may already have a ``played`` frame in flight. That
    frame arrives BEFORE the browser has even seen ``stop``, so with a single
    latched slot it won, and the position recorded as "the browser's last word"
    was up to one timer period early — silently, in the field AIR-1's
    through-air row compares against ``audio_end_ms``.

    Seed: latch the slot again (``self._final_ack_seen`` as the gate) and this
    goes RED.
    """

    gateway, _arms = _gateway()
    gateway.attach(TOKEN)
    gateway.begin_utterance()
    gateway.send_audio(b"\x00" * 48_000)  # 1 000 ms transmitted
    gateway.ack_played(1, 300.0)
    gateway.interrupt()

    # The timer's frame, sent before `stop` was seen, lands first...
    assert gateway.ack_played(1, 320.0) is False
    # ...and then the browser's real final position, from `stopPlayback`.
    assert gateway.ack_played(1, 405.0, True) is False

    snapshot = gateway.snapshot()
    assert snapshot["last_final_played_ms"] == pytest.approx(405.0), (
        "the browser's last word must win, whatever order the frames arrive in"
    )
    assert snapshot["final_acks"] == 2
    assert snapshot["stale_acks"] == 0


def test_post_interrupt_acks_are_bounded_so_a_chatty_client_cannot_spin_a_counter() -> None:
    from parcel_robot.realtime.audio_gateway import (
        MAX_FINAL_ACKS_PER_UTTERANCE,
    )

    gateway, _arms = _gateway()
    gateway.attach(TOKEN)
    gateway.begin_utterance()
    gateway.send_audio(b"\x00" * 48_000)
    gateway.interrupt()
    for index in range(MAX_FINAL_ACKS_PER_UTTERANCE + 3):
        gateway.ack_played(1, float(index))
    snapshot = gateway.snapshot()
    assert snapshot["final_acks"] == MAX_FINAL_ACKS_PER_UTTERANCE
    assert snapshot["stale_acks"] == 3


def test_the_final_position_does_not_leak_into_the_next_reply() -> None:
    gateway, _arms = _gateway()
    gateway.attach(TOKEN)
    gateway.begin_utterance()
    gateway.send_audio(b"\x00" * 48_000)
    gateway.interrupt()
    gateway.ack_played(1, 700.0, True)
    assert gateway.snapshot()["last_final_played_ms"] == pytest.approx(700.0)

    gateway.begin_utterance()
    gateway.send_audio(b"\x00" * 4_800)
    gateway.interrupt()
    assert gateway.snapshot()["last_final_played_ms"] is None, (
        "a new reply's record must not open holding the previous reply's number"
    )
    assert gateway.snapshot()["final_acks"] == 0


@pytest.mark.skipif(JS_ENGINE is None, reason="no ECMAScript engine on this host")
def test_the_shipped_panel_actually_parses(tmp_path: Path) -> None:
    """Correction pass. A real engine, not a brace count.

    MARK-1 originally claimed there was no JS engine on this host and fell back
    to a regex-aware brace/paren balance over the ``<script>`` block. That was
    wrong — ``gjs`` (SpiderMonkey) is installed — and a balance check would have
    passed a file with, say, a stray ``=>`` in it. ``new Function(src)`` COMPILES
    the source and throws ``SyntaxError`` without executing a line of it, which
    is a real syntax gate over the panel the owner's browser will load.

    Still not "the panel works": nothing here has a DOM, a socket or an
    ``AudioContext``. It is the difference between "this file is JavaScript" and
    "this file is the right JavaScript", and only the first is claimed.
    """

    script = tmp_path / "parse.js"
    script.write_text(
        "const GLib = imports.gi.GLib;\n"
        f"const [ok, bytes] = GLib.file_get_contents({json.dumps(str(PANEL))});\n"
        "if (!ok) { printerr('unreadable'); imports.system.exit(2); }\n"
        "const html = imports.byteArray.toString(bytes);\n"
        "const open = html.indexOf('<script>');\n"
        "const close = html.lastIndexOf('</script>');\n"
        "new Function(html.slice(open + 8, close));\n"
        "print('PARSE OK');\n",
        encoding="utf-8",
    )
    proc = subprocess.run(
        [JS_ENGINE, str(script)], capture_output=True, text=True, check=False, timeout=120
    )
    assert proc.returncode == 0, f"the shipped panel does not parse:\n{proc.stderr}"
    assert "PARSE OK" in proc.stdout
