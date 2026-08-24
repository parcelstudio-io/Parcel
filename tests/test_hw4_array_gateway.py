"""Card HW-4 (task_37): the ear moves from Chrome to the XVF3800.

WHAT THIS FILE PROVES
---------------------
1. **The resamplers are exact.** 16 ↔ 24 kHz is 3/2 and 2/3, so a rational
   polyphase FIR is not an approximation of anything; the tone tests assert the
   closed-form output length, the spectral peak to within one bin, and that the
   filter's images are ≤ −40 dB. They also assert the property that makes the
   filter usable on a live stream at all: resampling a signal in 1-, 7-, 640-
   and 4 096-sample blocks is **byte-identical** to resampling it in one call.
2. **The chunk contract is the browser's.** ``BrowserAudioGateway.hello()`` and
   ``ui/index.html`` are read here, in this file, and the numbers they state are
   what :class:`ArrayAudioGateway` is then held to. Pinning it from the source
   rather than restating it is what stops the two ears drifting apart.
3. **Device-absence is a typed refusal, never a silent browser.**
4. **FLAG-OFF IDENTITY**, through the real ``RobotRuntime._build_realtime_sink``
   with a real ``configs/robot.yaml`` and a real profile overlay on disk. No
   gateway class is monkeypatched anywhere in this file — if the identity claim
   were made against a stub it would prove nothing about what boots.
5. **A corpus fixture replays onto the array**, through a real ``RealtimeLane``
   against ``FakeRealtimeServer``, ending as 16 kHz PCM at a (fake) DAC.

WHAT IT CANNOT PROVE
--------------------
Anything about the Orin, the dog, or the array's amplifier. PortAudio is a
stand-in here on purpose: the real device is exercised by the measurement
recorded in ``HW4_STATUS.md`` (rows H1–H4), and nothing in this file is allowed
to depend on hardware being plugged in.
"""

from __future__ import annotations

import io
import json
import re
import threading
import time
import wave
from pathlib import Path
from typing import Any

import numpy as np
import pytest
import yaml

from evals.companion.realtime_convo_v1.schema import Fixture, fixture_to_script, load_fixtures
from parcel_robot.memory.conversation import ConversationMemory
from parcel_robot.realtime.audio_gateway import (
    ARRAY_ASR_CHANNEL,
    ARRAY_CAPTURE_CHANNELS,
    ARRAY_RATE_HZ,
    ARRAY_UDEV_RULE_PATH,
    ARRAY_USB_ID,
    AUDIO_GATEWAY_ARRAY,
    AUDIO_GATEWAY_BROWSER,
    DEFAULT_MAX_INBOUND_FRAME_BYTES,
    DEFAULT_POLL_S,
    ArrayAudioGateway,
    ArrayDeviceError,
    BrowserAudioGateway,
    GatewayError,
    GatewayNotRunningError,
    RationalResampler,
    resolve_audio_gateway_selection,
)
from parcel_robot.realtime.browser_sink import BrowserSink
from parcel_robot.realtime.config import RealtimeConfig
from parcel_robot.realtime.fake_server import FakeRealtimeServer
from parcel_robot.realtime.lane import RealtimeLane
from parcel_robot.realtime.prompting import render_session_instructions
from parcel_robot.realtime.protocol import PCM16_SAMPLE_RATE_HZ
from parcel_robot.realtime.transport import transport_pair

REPO = Path(__file__).resolve().parents[1]
PANEL = REPO / "src" / "parcel_robot" / "ui" / "index.html"

#: The array's PortAudio enumeration on this host, copied verbatim from
#: ``sounddevice.query_devices()`` on 2026-08-23. Two entries match "XVF3800"
#: with two input channels — the raw ALSA node and the PipeWire node — which is
#: exactly the ambiguity the gateway's "prefer ``hw:``" rule exists to settle:
#: the PipeWire node resamples and remixes behind our back, and a remixed
#: two-beam array is the downmix this whole card refuses.
HOST_DEVICES: tuple[dict[str, Any], ...] = (
    {"name": "HDA NVidia: HDMI 0 (hw:0,3)", "max_input_channels": 0, "max_output_channels": 8},
    {
        "name": "reSpeaker XVF3800 4-Mic Array: USB Audio (hw:1,0)",
        "max_input_channels": 2,
        "max_output_channels": 2,
    },
    {
        "name": "HD-Audio Generic: ALC1220 Analog (hw:2,0)",
        "max_input_channels": 2,
        "max_output_channels": 2,
    },
    {"name": "pipewire", "max_input_channels": 128, "max_output_channels": 128},
    {
        "name": "alsa_input.usb-Seeed_Studio_reSpeaker_XVF3800_4-Mic_Array-00.analog-stereo",
        "max_input_channels": 2,
        "max_output_channels": 0,
    },
)

#: The same host with the array unplugged.
NO_ARRAY_DEVICES = tuple(entry for entry in HOST_DEVICES if "XVF3800" not in str(entry["name"]))


# ============================================================ the PortAudio stand-in
class _FakeInputStream:
    """A ``sounddevice.InputStream`` with a hand crank instead of a sound card."""

    def __init__(self, owner: _FakeAudio, **kwargs: Any) -> None:
        self.owner = owner
        self.kwargs = kwargs
        self.callback = kwargs["callback"]
        self.started = False
        self.stopped = False
        self.aborted = False
        self.closed = False
        # The window HO-5 lives in: from here until `start()` returns, this
        # gateway is MID-OPEN. A transition that completes inside this window
        # has interleaved with the open, which is the thing being pinned.
        owner.open_in_progress = True

    def start(self) -> None:
        # The verifier's `race_probe.py` shape: a device whose open costs more
        # than `DEFAULT_POLL_S`. This desk's array opened in 7-11 ms, which is
        # why finding F2 never bit here; PipeWire on the Orin will not.
        if self.owner.open_delay_s:
            time.sleep(self.owner.open_delay_s)
        self.started = True
        self.owner.open_in_progress = False

    def abort(self) -> None:
        if self.owner.unplugged:
            raise self.owner.PortAudioError("Error aborting stream [PaErrorCode -9988]")
        self.aborted = True

    def stop(self) -> None:
        if self.owner.unplugged:
            raise self.owner.PortAudioError("Error stopping stream [PaErrorCode -9988]")
        self.stopped = True

    def close(self) -> None:
        self.closed = True

    def feed(self, block: np.ndarray, status: object = 0) -> None:
        """Deliver one capture block the way PortAudio's own thread would."""

        self.callback(block, int(block.shape[0]), None, status)


class _FakeOutputStream:
    def __init__(self, owner: _FakeAudio, **kwargs: Any) -> None:
        self.owner = owner
        self.kwargs = kwargs
        self.callback = kwargs["callback"]
        self.channels = int(kwargs["channels"])
        self.started = False
        self.closed = False

    def start(self) -> None:
        self.started = True

    def stop(self) -> None:
        if self.owner.unplugged:
            raise self.owner.PortAudioError("Error stopping stream [PaErrorCode -9988]")
        self.started = False

    def close(self) -> None:
        self.closed = True

    def pull(self, frames: int) -> np.ndarray:
        """Ask for ``frames`` of playback, as the DAC would."""

        outdata = np.zeros((frames, self.channels), dtype=np.int16)
        self.callback(outdata, frames, None, 0)
        return outdata


class _FakeAudio:
    """Shaped exactly like the four ``sounddevice`` names the gateway touches.

    ``PortAudioError`` is one of them, and it is a class attribute for the same
    reason it is one in ``sounddevice``: it subclasses ``Exception`` DIRECTLY,
    so the gateway has to fetch it off the loaded module to be able to name it.
    """

    class PortAudioError(Exception):
        """``sounddevice.PortAudioError``'s shape: straight off ``Exception``."""

    def __init__(
        self,
        devices: tuple[dict[str, Any], ...] = HOST_DEVICES,
        *,
        open_delay_s: float = 0.0,
        input_raises: bool = False,
        unplugged: bool = False,
    ) -> None:
        self.devices = [dict(entry) for entry in devices]
        self.open_delay_s = open_delay_s
        self.input_raises = input_raises
        #: The array pulled out of the USB port mid-session: every teardown call
        #: on an open stream answers with a ``PortAudioError``.
        self.unplugged = unplugged
        #: True while an input stream is being constructed and started.
        self.open_in_progress = False
        self.input_streams: list[_FakeInputStream] = []
        self.output_streams: list[_FakeOutputStream] = []

    def query_devices(self) -> list[dict[str, Any]]:
        return [dict(entry) for entry in self.devices]

    def InputStream(self, **kwargs: Any) -> _FakeInputStream:
        if self.input_raises:
            raise OSError("PortAudio: device unavailable [PaErrorCode -9985]")
        stream = _FakeInputStream(self, **kwargs)
        self.input_streams.append(stream)
        return stream

    def OutputStream(self, **kwargs: Any) -> _FakeOutputStream:
        stream = _FakeOutputStream(self, **kwargs)
        self.output_streams.append(stream)
        return stream


def _tone_pcm16(
    rate_hz: int,
    *,
    hz: float = 1000.0,
    seconds: float = 1.0,
    amplitude: float = 0.5,
    phase: float = 0.0,
) -> bytes:
    count = int(rate_hz * seconds)
    t = np.arange(count, dtype=np.float64) / rate_hz
    wave_ = amplitude * np.sin(2.0 * np.pi * hz * t + phase)
    return np.rint(wave_ * 32768.0).clip(-32768, 32767).astype("<i2").tobytes()


def _spectrum(pcm: bytes, rate_hz: int) -> tuple[np.ndarray, np.ndarray]:
    samples = np.frombuffer(pcm, dtype="<i2").astype(np.float64) / 32768.0
    windowed = samples * np.hanning(samples.size)
    return np.fft.rfftfreq(samples.size, 1.0 / rate_hz), np.abs(np.fft.rfft(windowed))


def _out_of_band_db(pcm: bytes, rate_hz: int, *, hz: float = 1000.0, guard: float = 150.0) -> float:
    freqs, spec = _spectrum(pcm, rate_hz)
    inside = np.abs(freqs - hz) <= guard
    power_in = float((spec[inside] ** 2).sum())
    power_out = float((spec[~inside] ** 2).sum())
    return 10.0 * np.log10(max(power_out, 1e-30) / max(power_in, 1e-30))


def _wait_for(predicate: Any, *, timeout: float = 5.0) -> bool:
    """Poll a real product thread rather than reaching into it."""

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.005)
    return predicate()


def _armed_gateway(
    audio: _FakeAudio, **kwargs: Any
) -> tuple[ArrayAudioGateway, list[bytes], _FakeInputStream]:
    """A started, mic-open gateway plus the list its ``on_audio`` fills."""

    heard: list[bytes] = []
    gateway = ArrayAudioGateway(on_audio=heard.append, audio=audio, **kwargs)
    gateway.start()
    assert gateway.set_mic(True) is True
    return gateway, heard, audio.input_streams[-1]


def _two_beam_block(samples: int, *, seed: int = 0) -> np.ndarray:
    """A capture block whose two beams are DIFFERENT, so a downmix is visible.

    ch0 is the conference beam and ch1 is the ASR beam (AIR-1 §4). They are
    given different tones on purpose: a gateway that took ch0, or the average,
    would produce a stream whose spectrum names its own mistake.
    """

    t = (np.arange(samples, dtype=np.float64) + seed * samples) / ARRAY_RATE_HZ
    conference = 0.4 * np.sin(2.0 * np.pi * 300.0 * t)
    asr = 0.5 * np.sin(2.0 * np.pi * 1000.0 * t)
    stacked = np.stack((conference, asr), axis=1)
    return np.rint(stacked * 32768.0).clip(-32768, 32767).astype(np.int16)


# ================================================================ A1–A4 · resampling
def test_the_up_resampler_is_exact_on_a_tone() -> None:
    """Row A1 + A3. 16 kHz → 24 kHz: exactly 3/2, and it stays a 1 kHz tone."""

    resampler = RationalResampler(from_hz=ARRAY_RATE_HZ, to_hz=PCM16_SAMPLE_RATE_HZ)
    assert (resampler.up, resampler.down) == (3, 2), "16 → 24 kHz is exactly 3/2"

    source = _tone_pcm16(ARRAY_RATE_HZ)
    out = resampler.process_pcm16(source)
    samples = len(out) // 2
    assert samples == (16000 * 3 - 1) // 2 + 1 == 24000
    assert samples == resampler.output_length(16000)

    freqs, spec = _spectrum(out, PCM16_SAMPLE_RATE_HZ)
    bin_hz = PCM16_SAMPLE_RATE_HZ / samples
    assert abs(float(freqs[int(np.argmax(spec))]) - 1000.0) <= bin_hz
    assert _out_of_band_db(out, PCM16_SAMPLE_RATE_HZ) <= -40.0


def test_the_down_resampler_is_exact_on_a_tone() -> None:
    """Row A2 + A3. 24 kHz → 16 kHz: exactly 2/3, and it stays a 1 kHz tone."""

    resampler = RationalResampler(from_hz=PCM16_SAMPLE_RATE_HZ, to_hz=ARRAY_RATE_HZ)
    assert (resampler.up, resampler.down) == (2, 3), "24 → 16 kHz is exactly 2/3"

    source = _tone_pcm16(PCM16_SAMPLE_RATE_HZ)
    out = resampler.process_pcm16(source)
    samples = len(out) // 2
    assert samples == (24000 * 2 - 1) // 3 + 1 == 16000
    assert samples == resampler.output_length(24000)

    freqs, spec = _spectrum(out, ARRAY_RATE_HZ)
    bin_hz = ARRAY_RATE_HZ / samples
    assert abs(float(freqs[int(np.argmax(spec))]) - 1000.0) <= bin_hz
    assert _out_of_band_db(out, ARRAY_RATE_HZ) <= -40.0


@pytest.mark.parametrize("chunk_samples", [1, 7, 640, 4096])
def test_the_resampler_is_chunk_size_invariant(chunk_samples: int) -> None:
    """Row A4. The property that makes the filter usable on a live stream.

    A resampler that restarts at every block boundary puts a click every 40 ms
    into the owner's audio and a broadband smear into the false-barge-in number
    this card exists to produce. Seed: drop ``self._history`` between calls and
    this goes red at every chunk size but the last.
    """

    source = _tone_pcm16(ARRAY_RATE_HZ)
    whole = RationalResampler(from_hz=ARRAY_RATE_HZ, to_hz=PCM16_SAMPLE_RATE_HZ)
    expected = whole.process_pcm16(source)

    streamed = RationalResampler(from_hz=ARRAY_RATE_HZ, to_hz=PCM16_SAMPLE_RATE_HZ)
    parts = [
        streamed.process_pcm16(source[offset : offset + chunk_samples * 2])
        for offset in range(0, len(source), chunk_samples * 2)
    ]
    assert b"".join(parts) == expected


# ======================================================= A5–A7 · the inbound contract
def test_the_browser_chunk_contract_is_what_this_card_pins() -> None:
    """Row A5. Read the contract off its TWO sources, here, and pin it.

    The claim ``ArrayAudioGateway`` makes is "the same chunk contract as the
    browser path". That claim is only worth something if the browser path's own
    numbers are asserted rather than remembered — so ``hello()`` is called and
    ``ui/index.html`` is read, and the rest of this file is held to what they
    say.
    """

    browser = BrowserAudioGateway(on_audio=lambda _payload: None)
    assert browser.hello()["input"] == {
        "format": "pcm16",
        "rate": PCM16_SAMPLE_RATE_HZ,
        "channels": 1,
        "max_frame_bytes": DEFAULT_MAX_INBOUND_FRAME_BYTES,
    }
    assert PCM16_SAMPLE_RATE_HZ == 24_000
    assert DEFAULT_MAX_INBOUND_FRAME_BYTES == 32 * 1024

    panel = PANEL.read_text(encoding="utf-8")
    assert "const frames = 2048;" in panel, "the panel's capture block size"
    assert "createScriptProcessor(frames, mic.captureChannels, 1)" in panel, (
        "one channel OUT of the node — the mono the gateway receives"
    )
    assert (
        "encodeMicFrame(event.inputBuffer.getChannelData(ear), "
        "mic.capture.sampleRate, mic.rate)" in panel
    ), "the browser resamples its hardware rate down to the gateway's rate"
    assert re.search(r"out\.setInt16\(index \* 2, .*, true\)", panel), "PCM16 little-endian"

    # And the bound is the one the product method enforces, read off the object
    # the browser path actually uses.
    assert browser._max_inbound_frame_bytes == DEFAULT_MAX_INBOUND_FRAME_BYTES


def test_the_array_gateway_feeds_the_lane_the_browser_contract() -> None:
    """Row A6. Every frame that leaves this gateway would be accepted by the lane.

    Seed: take ``data[:, 0]`` (the conference beam) in ``_offer_block`` and the
    spectral assertion goes red; ask PortAudio for one channel and the opened
    stream's ``channels`` assertion goes red.
    """

    audio = _FakeAudio()
    gateway, heard, stream = _armed_gateway(audio, frame_ms=40)
    try:
        assert stream.kwargs["channels"] == ARRAY_CAPTURE_CHANNELS == 2, (
            "a one-channel open averages the conference and ASR beams"
        )
        assert stream.kwargs["samplerate"] == ARRAY_RATE_HZ == 16_000
        assert stream.kwargs["dtype"] == "int16"
        assert stream.kwargs["blocksize"] == 640, "40 ms at 16 kHz"

        blocks = [_two_beam_block(640, seed=index) for index in range(25)]
        for block in blocks:
            stream.feed(block)
        assert _wait_for(lambda: len(heard) >= len(blocks))
    finally:
        gateway.stop()

    for payload in heard:
        assert payload, "an empty frame is never handed to the lane"
        assert len(payload) % 2 == 0, "PCM16"
        assert len(payload) <= DEFAULT_MAX_INBOUND_FRAME_BYTES, "the lane's inbound cap"
        samples = len(payload) // 2
        assert abs(samples - 960) <= 1, "40 ms at 24 kHz, within one output sample"

    # The whole capture equals the resampler's own output for column 1, and only
    # for column 1: a 300 Hz conference beam would show up in the spectrum.
    joined = b"".join(heard)
    reference = RationalResampler(from_hz=ARRAY_RATE_HZ, to_hz=PCM16_SAMPLE_RATE_HZ)
    expected = reference.process_pcm16(
        np.concatenate([block[:, ARRAY_ASR_CHANNEL] for block in blocks]).astype("<i2").tobytes()
    )
    assert joined == expected
    freqs, spec = _spectrum(joined, PCM16_SAMPLE_RATE_HZ)
    peak_hz = float(freqs[int(np.argmax(spec))])
    assert abs(peak_hz - 1000.0) <= 2.0, f"the ASR beam is 1 kHz; got {peak_hz:.1f} Hz"
    conference = spec[np.abs(freqs - 300.0) <= 20.0].max()
    asr = spec[np.abs(freqs - 1000.0) <= 20.0].max()
    assert conference < asr / 100.0, "the conference beam must not be in the stream at all"


def test_the_tee_and_the_identity_gate_ride_in_the_same_order() -> None:
    """Row A7. R17's tee and F1-SI's gate are passengers here exactly as they are
    on ``accept_audio`` — same order, same bytes, before the lane."""

    calls: list[tuple[str, bytes]] = []

    class _Tee:
        def offer_owner(self, payload: bytes) -> bool:
            calls.append(("tee", payload))
            return True

        def offer_robot(self, payload: bytes) -> bool:
            calls.append(("tee_robot", payload))
            return True

        def note_interrupt(self, sequence: int, onset_ago_s: float | None = None) -> None:
            calls.append(("tee_interrupt", b""))

        def snapshot(self) -> dict[str, object]:
            return {}

    class _Identity:
        def observe_frame(self, payload: bytes) -> None:
            calls.append(("identity", payload))

    audio = _FakeAudio()
    heard: list[bytes] = []
    gateway = ArrayAudioGateway(
        on_audio=lambda payload: (calls.append(("lane", payload)), heard.append(payload))[1],
        audio=audio,
        capture=_Tee(),  # type: ignore[arg-type]
        voice_identity=_Identity(),
    )
    gateway.start()
    gateway.set_mic(True)
    try:
        audio.input_streams[-1].feed(_two_beam_block(640))
        assert _wait_for(lambda: len(heard) == 1)
    finally:
        gateway.stop()

    assert [name for name, _ in calls] == ["tee", "identity", "lane"]
    assert {payload for _, payload in calls} == {heard[0]}


# ============================================================== A8 · the outbound half
def _wav(pcm: bytes, rate_hz: int = PCM16_SAMPLE_RATE_HZ) -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as writer:
        writer.setnchannels(1)
        writer.setsampwidth(2)
        writer.setframerate(rate_hz)
        writer.writeframes(pcm)
    return buffer.getvalue()


def test_playback_unwraps_the_wav_and_reaches_the_array_at_16k() -> None:
    """Row A8. The mouth: 24 kHz WAV in, 16 kHz PCM at the array's own DAC.

    Seed: hand ``pcm`` straight to the queue without ``self._down`` and the
    sample-count assertion goes red.
    """

    audio = _FakeAudio()
    gateway = ArrayAudioGateway(on_audio=lambda _payload: None, audio=audio)
    gateway.start()
    try:
        assert audio.output_streams == [], "nothing is opened until there is audio to play"
        assert gateway.played_started_monotonic is None
        gateway.begin_utterance()
        gateway.send_audio(b"")
        assert audio.output_streams == [], "an empty chunk is not a reason to take a speaker"

        pcm24 = _tone_pcm16(PCM16_SAMPLE_RATE_HZ, seconds=0.24)
        gateway.send_audio(_wav(pcm24))
        assert len(audio.output_streams) == 1
        stream = audio.output_streams[0]
        assert stream.kwargs["samplerate"] == ARRAY_RATE_HZ == 16_000
        assert stream.kwargs["dtype"] == "int16"
        assert stream.started is True
        assert gateway.played_started_monotonic is None, "nothing has left the DAC yet"

        played = stream.pull(4000)
        assert gateway.played_started_monotonic is not None
        mono = played[:, 0]
        assert np.array_equal(mono, played[:, -1]), "mono is duplicated across the channels"
        expected = np.frombuffer(
            RationalResampler(from_hz=PCM16_SAMPLE_RATE_HZ, to_hz=ARRAY_RATE_HZ).process_pcm16(
                pcm24
            ),
            dtype="<i2",
        )
        assert expected.size == 3840, "0.24 s at 16 kHz"
        assert np.array_equal(mono[: expected.size], expected)
        assert not mono[expected.size :].any(), "the tail is silence, not a repeat"
    finally:
        gateway.stop()


def test_an_interrupt_stops_the_amplifier_and_a_duck_only_quietens_it() -> None:
    """DUPLEX-1's two seams, on a real amplifier instead of a control frame."""

    audio = _FakeAudio()
    gateway = ArrayAudioGateway(on_audio=lambda _payload: None, audio=audio)
    gateway.start()
    try:
        gateway.begin_utterance()
        gateway.send_audio(_wav(_tone_pcm16(PCM16_SAMPLE_RATE_HZ, seconds=0.24)))
        stream = audio.output_streams[0]

        gateway.duck(0.2)
        quiet = stream.pull(160)[:, 0].astype(np.float64)
        gateway.duck(1.0)
        loud = stream.pull(160)[:, 0].astype(np.float64)
        assert np.abs(quiet).max() < np.abs(loud).max()
        assert gateway.ducks == 2 and gateway.duck_resumes == 1

        gateway.interrupt(onset_ago_s=0.3)
        assert gateway.interrupts == 1
        assert gateway.frames_discarded_interrupt >= 1
        assert not stream.pull(160).any(), "a barge-in is silence, immediately"
    finally:
        gateway.stop()


# ================================================================== A9 · the refusal
def test_an_absent_array_is_a_typed_refusal_naming_the_udev_rule() -> None:
    """Row A9. No device ⇒ a raise that names the fix, never a browser ear."""

    audio = _FakeAudio(NO_ARRAY_DEVICES)
    gateway = ArrayAudioGateway(on_audio=lambda _payload: None, audio=audio)
    gateway.start()
    assert gateway.device_error is not None, "start() says so, loudly, and boots anyway"
    try:
        with pytest.raises(ArrayDeviceError) as raised:
            gateway.set_mic(True)
    finally:
        gateway.stop()

    message = str(raised.value)
    # The three things to check, by their literal text, in the order you would
    # check them. The constants and the literals are both asserted so that
    # renaming a constant cannot quietly empty the message.
    assert ARRAY_USB_ID == "2886:001a"
    assert ARRAY_UDEV_RULE_PATH == "/etc/udev/rules.d/99-respeaker-xvf3800.rules"
    assert "2886:001a" in message
    assert "scripts/env-audio.sh" in message
    assert "/etc/udev/rules.d/99-respeaker-xvf3800.rules" in message
    assert isinstance(raised.value, GatewayError), "the gateway's own error family"
    assert not isinstance(gateway, BrowserAudioGateway)
    assert gateway.mic_open is False
    assert gateway.device_refusals == 1
    assert audio.input_streams == [], "nothing was opened"


def test_the_raw_alsa_node_wins_over_the_pipewire_one() -> None:
    """The two XVF3800 entries on this host, and why the ``hw:`` one is taken.

    The PipeWire node resamples and remixes; a remixed two-beam array is the
    downmix AIR-1 §4 measured and MARK-1 refused. Seed: return
    ``candidates[0]`` first and this goes red.
    """

    gateway = ArrayAudioGateway(on_audio=lambda _payload: None, audio=_FakeAudio())
    index, name = gateway.resolve_device()
    assert "hw:" in name and "XVF3800" in name
    assert index == 1


def test_an_explicit_device_index_is_honoured_and_validated() -> None:
    """``audio.device`` exists because PortAudio indices move between reboots."""

    audio = _FakeAudio()
    gateway = ArrayAudioGateway(on_audio=lambda _payload: None, audio=audio, device=1)
    assert gateway.resolve_device()[0] == 1

    deaf = ArrayAudioGateway(on_audio=lambda _payload: None, audio=audio, device=0)
    with pytest.raises(ArrayDeviceError, match="input channel"):
        deaf.resolve_device()


# ==================================================== A10–A13 · the config and the boot
def _runtime_tree(
    tmp_path: Path,
    *,
    profile: str | None,
    audio_section: dict[str, Any] | None,
) -> Path:
    """The shipped base plus, optionally, a REAL sibling profile overlay.

    No product symbol is monkeypatched — the base is a byte copy of
    ``configs/robot.yaml`` and the overlay is the file ``ConfigStore`` itself
    goes looking for when ``$PARCEL_PROFILE`` is set. This is the path an
    operator actually takes.
    """

    from parcel_robot.paths import resolve_config_yaml

    base = tmp_path / "robot.yaml"
    base.write_text(resolve_config_yaml().read_text(encoding="utf-8"), encoding="utf-8")
    if profile is not None:
        overlay = tmp_path / f"robot.{profile}.yaml"
        overlay.write_text(yaml.safe_dump({"audio": audio_section}), encoding="utf-8")
    return base


def _audio_mode_runtime(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    profile: str | None = None,
    audio_section: dict[str, Any] | None = None,
) -> Any:
    """A real ``RobotRuntime`` in ``mode: audio``, built by the product launcher."""

    base = _runtime_tree(tmp_path, profile=profile, audio_section=audio_section)
    realtime = tmp_path / "realtime.yaml"
    realtime.write_text(
        yaml.safe_dump({"enabled": True, "mode": "audio", "model": "gpt-realtime-2.1"}),
        encoding="utf-8",
    )
    monkeypatch.setenv("PARCEL_REALTIME_CONFIG", str(realtime))
    monkeypatch.setenv("PARCEL_MEMORY_PATH", str(tmp_path / "memory.sqlite3"))
    monkeypatch.setenv("PARCEL_REALTIME_SPEND_LEDGER", str(tmp_path / "spend.jsonl"))
    monkeypatch.delenv("PARCEL_REALTIME_KEY_ENV", raising=False)
    if profile is not None:
        monkeypatch.setenv("PARCEL_PROFILE", profile)
    else:
        monkeypatch.delenv("PARCEL_PROFILE", raising=False)

    from parcel_robot import web_panel

    return web_panel.build_runtime(base, tmp_path / "sim.sock", use_llm=False)


def test_with_no_audio_key_the_runtime_builds_exactly_what_head_builds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Row A10 — FLAG-OFF IDENTITY, through the real construction path.

    The whole card rests on this: with no ``audio:`` block the runtime must
    construct the SAME class with the SAME wiring it constructed before HW-4
    existed. Nothing here is stubbed — a stubbed gateway class would make this
    test pass while the product built something else. Seed: make the runtime
    branch select the array whenever the section resolves, and this goes red.
    """

    runtime = _audio_mode_runtime(tmp_path, monkeypatch)
    gateway = runtime.realtime_gateway
    assert type(gateway) is BrowserAudioGateway
    assert isinstance(runtime.realtime_lane._sink, BrowserSink)
    assert gateway.running is True
    # The five keyword arguments HEAD passed, read back off the object.
    assert gateway._on_audio == runtime._realtime_owner_audio
    assert gateway._on_mic == runtime._realtime_mic_gesture
    assert gateway._capture is None, "the R17 tee is off by default"
    assert gateway._sample_rate_hz == PCM16_SAMPLE_RATE_HZ
    # Verifier note N1: the first pass pinned the TYPE and three of HEAD's five
    # keyword arguments, so seeds that DROPPED `on_event=` or `voice_identity=`
    # from the `else` arm stayed green. Both are pinned now, and `on_event` is
    # pinned by USING it — a callable that goes nowhere is not a wiring.
    assert gateway._voice_identity is runtime.realtime_voice_identity
    assert gateway._on_event is not None
    before = len(runtime._events)
    gateway._on_event("hw4: proving the event sink is the runtime's own")
    assert len(runtime._events) == before + 1
    assert "hw4: proving the event sink" in str(runtime._events[-1])
    assert gateway.snapshot()["mic_open"] is False
    assert resolve_audio_gateway_selection(runtime.store.section("audio")) == (
        AUDIO_GATEWAY_BROWSER,
        None,
    )


def test_the_audio_gateway_key_selects_the_array(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Row A11. The other half: the knob CAN be turned, by a real profile.

    Constructing and starting the array gateway must open NO audio device — a
    runtime that took the microphone at boot would be listening before anybody
    asked it to, which is the browser gateway's rule 2 and applies here too.
    """

    runtime = _audio_mode_runtime(
        tmp_path, monkeypatch, profile="hw4array", audio_section={"gateway": "array"}
    )
    gateway = runtime.realtime_gateway
    assert type(gateway) is ArrayAudioGateway
    assert isinstance(runtime.realtime_lane._sink, BrowserSink)
    assert gateway.running is True
    assert gateway.mic_open is False, "existing is not listening"
    assert gateway._on_audio == runtime._realtime_owner_audio
    assert gateway.snapshot()["kind"] == AUDIO_GATEWAY_ARRAY
    assert gateway.snapshot()["capture_beam"] == ARRAY_ASR_CHANNEL == 1
    runtime.realtime_gateway.stop()


def test_a_misspelled_audio_key_refuses_the_boot_by_name(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The read-site guard is WIRED, not merely present.

    The ``audio`` subtree is exempt from ``check_overlay_keys``, so the overlay
    MERGES the typo — if the construction branch does not check, nothing
    anywhere refuses and the operator gets the browser ear while the file on
    disk says ``array``. Seed: delete the
    ``resolve_audio_gateway_selection`` call from ``_build_realtime_sink``.
    """

    with pytest.raises(ValueError, match="gatewayy"):
        _audio_mode_runtime(
            tmp_path, monkeypatch, profile="hw4typo", audio_section={"gatewayy": "array"}
        )


def test_the_audio_section_is_introducible_and_its_typos_are_refused() -> None:
    """Row A12. Both halves of the division of labour, asserted together."""

    from parcel_robot.config import OVERLAY_INTRODUCIBLE_KEYS, check_overlay_keys
    from parcel_robot.paths import resolve_config_yaml

    base = yaml.safe_load(resolve_config_yaml().read_text(encoding="utf-8")) or {}
    assert "audio" not in base, "if the base grows the section, this card's premise changes"
    assert "audio" in OVERLAY_INTRODUCIBLE_KEYS
    assert not any(str(key).startswith("audio.") for key in OVERLAY_INTRODUCIBLE_KEYS), (
        "the loader stops descending at an exempt parent, so listing audio.gateway "
        "would look like a spelling guard and be inert"
    )
    # The exemption is what makes the read-site guard load-bearing: a typo
    # merges cleanly here and is refused THERE.
    check_overlay_keys(base, {"audio": {"gatewayy": "array"}})

    assert resolve_audio_gateway_selection(None) == (AUDIO_GATEWAY_BROWSER, None)
    assert resolve_audio_gateway_selection({}) == (AUDIO_GATEWAY_BROWSER, None)
    assert resolve_audio_gateway_selection({"gateway": "browser"}) == (AUDIO_GATEWAY_BROWSER, None)
    assert resolve_audio_gateway_selection({"gateway": "array", "device": "ReSpeaker"}) == (
        AUDIO_GATEWAY_ARRAY,
        "ReSpeaker",
    )
    with pytest.raises(ValueError, match="gatewayy"):
        resolve_audio_gateway_selection({"gatewayy": "array"})
    with pytest.raises(ValueError, match="chrome"):
        resolve_audio_gateway_selection({"gateway": "chrome"})
    with pytest.raises(TypeError):
        resolve_audio_gateway_selection(["array"])


def test_the_survey_of_unreachable_config_sections_is_still_empty() -> None:
    """Row A13. CAP-1's property, re-asserted from this card's side.

    ``runtime._build_realtime_sink`` now reads ``store.section("audio")``, which
    puts a new name into ``admission.product_config_sections()``. Without the
    ``OVERLAY_INTRODUCIBLE_KEYS`` entry that name would be unreachable and this
    would go red — which is the point of the survey.
    """

    from parcel_robot import admission
    from parcel_robot.config import OVERLAY_INTRODUCIBLE_KEYS
    from parcel_robot.paths import resolve_config_yaml

    base = yaml.safe_load(resolve_config_yaml().read_text(encoding="utf-8")) or {}
    sections = admission.product_config_sections()
    assert "audio" in sections, "the runtime reads it; the survey must see it"
    unreachable = {
        name for name in sections if name not in base and name not in OVERLAY_INTRODUCIBLE_KEYS
    }
    assert unreachable == set()


# ============================================================ A14 · the corpus replay
def test_a_corpus_fixture_replays_through_the_array_gateway() -> None:
    """Row A14. Fixture → real lane → BrowserSink → ArrayAudioGateway → 16 kHz DAC.

    The existing corpus replay proves the pipeline into a list of WAV chunks.
    This proves the same pipeline into the array's mouth, which is the only way
    to show that the new gateway satisfies the sink contract as the LANE calls
    it rather than as a test calls it.
    """

    fixture: Fixture = next(f for f in load_fixtures() if f.family == "conversation")
    audio = _FakeAudio()
    gateway = ArrayAudioGateway(on_audio=lambda _payload: None, audio=audio)
    gateway.start()
    ledger = ConversationMemory(":memory:")
    now = [1_000.0]
    script = fixture_to_script(fixture, synthetic_audio_ms=300)
    servers: list[FakeRealtimeServer] = []

    def _factory() -> Any:
        lane_end, server_end = transport_pair(clock=lambda: now[0])
        servers.append(
            FakeRealtimeServer(transport=server_end, script=list(script), clock=lambda: now[0])
        )
        return lane_end

    lane = RealtimeLane(
        config=RealtimeConfig(enabled=True, source="hw4-replay"),
        instructions=render_session_instructions(
            profile_id=fixture.si_profile, flags=fixture.flags
        ).text,
        transport_factory=_factory,
        sink=BrowserSink(gateway),
        ledger=ledger,
        clock=lambda: now[0],
        session_id_factory=lambda: f"rt_{fixture.thread_id}",
    )
    try:
        lane.open_session(handshake_token="csrf-token", mic_gesture=True)
        servers[-1].pump()
        lane.pump()
        for _ in fixture.turns:
            lane.send_audio(b"\x00\x00" * 240)
            servers[-1].pump()
            lane.pump()

        rows = ledger.realtime_turns(limit=500)
        expected: list[tuple[str, str]] = []
        for turn in fixture.turns:
            expected.append(("user", turn.owner_text))
            if turn.robot_text:
                expected.append(("assistant", turn.robot_text))
        assert [(str(row["role"]), str(row["content"])) for row in rows] == expected
        assert lane.protocol_errors == [] and lane.server_errors == []

        assert gateway.frames_out > 0, "the lane really played something"
        assert len(audio.output_streams) == 1
        stream = audio.output_streams[0]
        assert stream.kwargs["samplerate"] == ARRAY_RATE_HZ
        # 24 kHz in, 16 kHz out: two array samples for every three lane samples.
        played = stream.pull(gateway.bytes_out // 2)
        assert played[:, 0].any(), "silence at the DAC would mean the mouth never opened"
    finally:
        gateway.stop()
        lane.close()


def test_the_playback_sample_count_is_two_thirds_of_the_lane_s() -> None:
    """The arithmetic behind A14, isolated so a miss names itself."""

    audio = _FakeAudio()
    gateway = ArrayAudioGateway(on_audio=lambda _payload: None, audio=audio)
    gateway.start()
    try:
        gateway.begin_utterance()
        lane_samples = 0
        for index in range(8):
            pcm = _tone_pcm16(PCM16_SAMPLE_RATE_HZ, seconds=0.24, phase=index)
            lane_samples += len(pcm) // 2
            gateway.send_audio(_wav(pcm))
        array_samples = gateway.bytes_out // 2
        assert array_samples == (lane_samples * 2 - 1) // 3 + 1
    finally:
        gateway.stop()


def test_the_gateway_carries_the_four_methods_the_runtime_calls() -> None:
    """``RobotRuntime`` calls these on whatever gateway it built; both must have
    them, or array mode dies at the first idle hang-up rather than at boot."""

    for kind in (BrowserAudioGateway, ArrayAudioGateway):
        for name in ("bind_token", "start", "stop", "close_mic", "snapshot"):
            assert callable(getattr(kind, name, None)), f"{kind.__name__}.{name}"
    audio = _FakeAudio()
    gateway = ArrayAudioGateway(on_audio=lambda _payload: None, audio=audio)
    gateway.bind_token("panel-token-hw4")
    gateway.start()
    try:
        gateway.set_mic(True)
        assert gateway.mic_open is True
        assert gateway.close_mic("the session hung up after a long silence") is False
        assert gateway.mic_open is False
        assert gateway.mic_closes_by_runtime == 1
        assert json.dumps(gateway.snapshot(), default=str)
    finally:
        gateway.stop()


def test_the_runtime_refuses_to_arm_a_gateway_it_never_started() -> None:
    """Fail closed, exactly as the browser gateway does."""

    from parcel_robot.realtime.audio_gateway import GatewayNotRunningError

    gateway = ArrayAudioGateway(on_audio=lambda _payload: None, audio=_FakeAudio())
    with pytest.raises(GatewayNotRunningError):
        gateway.set_mic(True)


def test_a_runtime_refusal_closes_the_streams_again() -> None:
    """The runtime is asked SECOND now (F5), so its refusal has to undo the open.

    No session, no budget, no credential still means no ear: the streams are
    opened, the runtime says no, and both are closed again. Rule 2 lives one
    layer lower — see the unarmed-frames test below.
    """

    audio = _FakeAudio()

    def _refuse(_open: bool) -> None:
        raise RuntimeError("the hosted lane refused to open a session")

    gateway = ArrayAudioGateway(on_audio=lambda _payload: None, audio=audio, on_mic=_refuse)
    gateway.start()
    try:
        assert gateway.set_mic(True) is False
        assert gateway.mic_open is False
        assert gateway.mic_refusals == 1
        assert audio.input_streams and audio.input_streams[-1].closed is True
        assert audio.output_streams and audio.output_streams[-1].closed is True
    finally:
        gateway.stop()


def test_a_device_refusal_never_opens_a_billed_session() -> None:
    """Verifier finding F5, stated as a guard.

    ``on_mic`` is ``RobotRuntime._realtime_mic_gesture``, and that opens a
    HOSTED session — money. The first pass called it before touching the device,
    so an array that would not open left the owner paying for a lane with no ear
    and no way to find out. The device comes first now.

    Seed S10: swap the two blocks in ``set_mic`` back.
    """

    asked: list[bool] = []
    audio = _FakeAudio(input_raises=True)
    gateway = ArrayAudioGateway(on_audio=lambda _payload: None, audio=audio, on_mic=asked.append)
    gateway.start()
    try:
        with pytest.raises(ArrayDeviceError):
            gateway.set_mic(True)
    finally:
        gateway.stop()

    assert asked == [], "no hosted session may be opened for a device that will not open"
    assert gateway.mic_open is False
    assert gateway.device_refusals == 1
    assert audio.output_streams and audio.output_streams[-1].closed is True


def test_frames_before_the_owners_gesture_never_reach_the_lane() -> None:
    """Rule 2, one layer lower than it used to be (F5).

    "Existing is not listening" can no longer mean "the device is shut", because
    the device is opened before consent is asked. So it means this: not one
    frame reaches ``on_audio``, the tee or the identity gate until ``_mic_open``
    is true, and the ones the sound card produced meanwhile are counted.

    Seed S11: delete the ``armed`` gate at the top of ``_offer_block``.
    """

    audio = _FakeAudio()
    heard: list[bytes] = []
    gateway = ArrayAudioGateway(on_audio=heard.append, audio=audio)
    gateway.start()
    try:
        # Reach past `set_mic` to the product's own open, so the window between
        # "the device is live" and "the owner said yes" can be observed at all.
        gateway._open_capture()
        stream = audio.input_streams[-1]
        stream.feed(_two_beam_block(640))
        assert _wait_for(lambda: gateway.frames_dropped_unarmed == 1)
        assert heard == [], "unarmed audio must never reach the lane"
        assert gateway.frames_in == 0

        gateway.set_mic(True)
        stream.feed(_two_beam_block(640, seed=1))
        assert _wait_for(lambda: len(heard) == 1)
        assert gateway.frames_dropped_unarmed == 1
    finally:
        gateway.stop()


def test_a_slow_device_open_still_reaches_the_lane() -> None:
    """Verifier finding F2 — the reader-thread race, stated as a guard.

    ``_reader_loop`` exits when ``_in_stream`` is ``None`` and its queue is
    empty. The first pass started that thread BEFORE the stream was opened, so
    any device whose open took longer than ``DEFAULT_POLL_S`` (50 ms) lost its
    reader silently: blocks queued to the cap and were dropped, ``on_audio`` got
    nothing, and ``_check_deaf`` — which lives in that loop — could never fire,
    so every counter read healthy.

    Seed S9: put the reader back before the open.
    """

    audio = _FakeAudio(open_delay_s=4 * DEFAULT_POLL_S)
    heard: list[bytes] = []
    gateway = ArrayAudioGateway(on_audio=heard.append, audio=audio, deaf_after_s=0.5)
    gateway.start()
    try:
        assert gateway.set_mic(True) is True
        blocks = [_two_beam_block(640, seed=index) for index in range(10)]
        for block in blocks:
            audio.input_streams[-1].feed(block)
        assert _wait_for(lambda: len(heard) == 10), (
            f"the reader died during a {4 * DEFAULT_POLL_S:.2f}s open: "
            f"heard={len(heard)} frames_in={gateway.frames_in}"
        )
        assert gateway.frames_dropped_capture_overflow == 0
        # ...and the deaf check is REACHABLE, which it is not when the reader is
        # dead — that is the half of F2 that hides the other half.
        assert "parcel-array-capture" in {t.name for t in threading.enumerate()}
    finally:
        gateway.stop()


def test_the_ear_and_the_clock_are_opened_together() -> None:
    """Verifier finding F1 — the diagnosis, stated as a guard.

    This device's capture endpoint does not clock unless its playback endpoint
    is running: capture alone returns `Input/output error` at every layer and
    delivers zero frames; the same capture beside a stream of digital zeros
    delivers 16 kHz exactly. So the playback stream is opened WITH the ear, not
    lazily on the first hosted chunk, and closed with it.

    Seed S12: make ``_open_capture`` skip ``_ensure_output()``.
    """

    audio = _FakeAudio()
    gateway = ArrayAudioGateway(on_audio=lambda _payload: None, audio=audio)
    gateway.start()
    assert audio.output_streams == [], "start() opens nothing at all"
    try:
        gateway.set_mic(True)
        assert len(audio.output_streams) == 1, "the ear without the clock is a deaf ear"
        clock = audio.output_streams[0]
        assert clock.started is True
        assert clock.kwargs["samplerate"] == ARRAY_RATE_HZ == 16_000
        # And it emits silence, not garbage, while nobody is talking.
        assert not clock.pull(640).any()
        assert gateway.playback_underruns == 0, "an idle clock is not an underrun"
        assert gateway.silence_clock_frames == 1

        gateway.set_mic(False)
        assert clock.closed is True, "they were opened together; they close together"
        assert audio.input_streams[-1].closed is True
    finally:
        gateway.stop()


def test_an_armed_array_that_delivers_nothing_says_so() -> None:
    """NOT PRE-REGISTERED — added after row H3 missed, and because of how it missed.

    On 2026-08-23 the real XVF3800 enumerated, opened, reported
    ``stream.active is True`` and returned ``Input/output error`` on the first
    read at every layer (ALSA, PipeWire, PortAudio, and the card's own
    ``tools/xvf3800_probe.py --rms``). The gateway sat there with every counter
    reading healthy. A microphone that opens and is then silent forever must be
    a REPORTED fact; this is that report, said once per arming.

    Seed: delete the ``self._check_deaf()`` call from ``_reader_loop``.
    """

    now = [1_000.0]
    audio = _FakeAudio()
    events: list[str] = []
    gateway = ArrayAudioGateway(
        on_audio=lambda _payload: None,
        on_event=events.append,
        audio=audio,
        clock=lambda: now[0],
        deaf_after_s=3.0,
    )
    gateway.start()
    events.clear()
    gateway.set_mic(True)
    try:
        now[0] += 2.0
        assert _wait_for(lambda: gateway.deaf_warnings > 0, timeout=0.3) is False
        now[0] += 2.0
        assert _wait_for(lambda: gateway.deaf_warnings == 1)
        assert "NOT ONE frame has arrived" in " ".join(events)
        assert "arecord -D hw:" in " ".join(events)
        # Said ONCE, not once per wake-up.
        now[0] += 60.0
        assert _wait_for(lambda: gateway.deaf_warnings > 1, timeout=0.3) is False

        # And a gateway that IS hearing never says it.
        audio.input_streams[-1].feed(_two_beam_block(640))
        assert _wait_for(lambda: gateway.frames_in == 1)
        assert gateway.deaf_warnings == 1
    finally:
        gateway.stop()


def test_an_array_unplugged_mid_session_can_still_be_shut() -> None:
    """Verifier's final note. A teardown that raises is a gateway that cannot be shut.

    ``sounddevice.PortAudioError`` subclasses ``Exception`` DIRECTLY, so the
    narrow tuple the rest of this module uses does not catch it — and the one
    place it actually turns up is the one place nothing may raise: ``abort`` /
    ``stop`` / ``close`` on a stream whose device has just been pulled out of
    the USB port. Before this, that error escaped ``set_mic(False)`` and
    ``close_mic()``, so an unplugged array left a gateway that could not be
    closed and a runtime that could not hang up.

    Seed: put ``ARRAY_THREAD_ERRORS`` back in ``_close_capture`` /
    ``_close_output`` in place of ``_teardown_errors()``.
    """

    audio = _FakeAudio()
    gateway = ArrayAudioGateway(on_audio=lambda _payload: None, audio=audio)
    gateway.start()
    assert gateway.set_mic(True) is True
    ear, clock = audio.input_streams[-1], audio.output_streams[-1]

    # ...and now somebody pulls the cable.
    audio.unplugged = True
    assert gateway.set_mic(False) is False, "shutting an unplugged array must not raise"
    assert gateway.mic_open is False
    assert ear.closed is True, "close() runs even after abort()/stop() refused"
    assert clock.closed is True
    # `stop()` must survive it too — that is the path `runtime.close()` takes.
    gateway.stop()
    assert gateway.running is False


def test_close_mic_survives_an_unplugged_array() -> None:
    """The same law on the runtime's own path: the idle hang-up (``close_mic``).

    ``runtime._realtime_idle_hangup`` calls ``close_mic`` inside a ``try`` that
    only catches ``(OSError, RuntimeError, TypeError, ValueError)`` — a
    ``PortAudioError`` would go straight past it and take the hang-up down.
    """

    audio = _FakeAudio()
    told: list[bool] = []
    gateway = ArrayAudioGateway(on_audio=lambda _payload: None, audio=audio, on_mic=told.append)
    gateway.start()
    gateway.set_mic(True)
    audio.unplugged = True
    try:
        assert gateway.close_mic("the session hung up after a long silence") is False
        assert gateway.mic_open is False
        assert gateway.mic_closes_by_runtime == 1
        assert told == [True, False], "the runtime is still told the ear closed"
    finally:
        gateway.stop()


def _race(gateway: ArrayAudioGateway, first: Any, second: Any, gap_s: float) -> list[Any]:
    """Run two transitions from two threads, ``second`` starting ``gap_s`` in."""

    results: list[Any] = [None, None]

    def _run(index: int, call: Any, delay: float) -> None:
        if delay:
            time.sleep(delay)
        try:
            results[index] = call()
        except (
            ArrayDeviceError,
            GatewayNotRunningError,
            OSError,
            RuntimeError,
            TypeError,
            ValueError,
        ) as error:
            # A racing transition may legitimately refuse; the race must carry
            # that refusal back to the assertions rather than lose it on a
            # worker thread. Named, because the brief forbids `noqa`.
            results[index] = error

    threads = [
        threading.Thread(target=_run, args=(0, first, 0.0)),
        threading.Thread(target=_run, args=(1, second, gap_s)),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10.0)
    assert not any(thread.is_alive() for thread in threads), "a transition deadlocked"
    return results


def _assert_shut_and_consistent(gateway: ArrayAudioGateway, audio: _FakeAudio) -> None:
    """The postcondition HO-5 is about: shut, and SAYING it is shut."""

    assert gateway.mic_open is False
    assert audio.input_streams and audio.input_streams[-1].closed is True
    assert audio.output_streams and audio.output_streams[-1].closed is True
    assert _wait_for(
        lambda: "parcel-array-capture" not in {t.name for t in threading.enumerate()}
    ), "a reader thread outlived a closed microphone"
    assert gateway.snapshot()["mic_open"] is False


def test_a_hangup_landing_inside_an_arm_leaves_no_deaf_ear() -> None:
    """Finding HO-5, from HW-MIC's verifier, stated as a guard.

    ``close_mic`` is the runtime's idle hang-up and it does NOT go through the
    panel's arm route, so the route's own lock could not serialise it. Landing
    inside ``set_mic(True)``'s device-open window, it closed streams the open
    had not yet assigned; the open then completed and set ``mic_open`` TRUE with
    no streams and a dead reader. The panel's repair poll could not fix that,
    because it repairs on ``mic_open == false``.

    Seed S14: turn ``_mic_lock`` into a null context.
    """

    audio = _FakeAudio(open_delay_s=0.3)
    gateway = ArrayAudioGateway(on_audio=lambda _payload: None, audio=audio)
    gateway.start()
    try:
        seen: list[bool] = []

        def _hang_up() -> bool:
            result = gateway.close_mic("the session hung up after a long silence")
            # Sampled the instant the hang-up returns: the runtime is entitled
            # to believe the ear is shut AT THAT MOMENT, which it is not if the
            # arm is still opening a device somewhere else.
            seen.append(audio.open_in_progress)
            return result

        armed, closed = _race(gateway, lambda: gateway.set_mic(True), _hang_up, gap_s=0.05)
        assert not isinstance(armed, Exception), armed
        assert not isinstance(closed, Exception), closed
        assert closed is False
        assert seen == [False], (
            "close_mic returned while set_mic was still opening the device: the two "
            "transitions interleaved"
        )
        _assert_shut_and_consistent(gateway, audio)
    finally:
        gateway.stop()


def test_an_arm_landing_inside_a_hangup_leaves_no_deaf_ear() -> None:
    """The same race the other way round: the hang-up starts first.

    Whichever wins, the post-state must be self-consistent — either shut with no
    streams, or open with both streams and a live reader. What may never happen
    is the pair that HO-5 found.
    """

    audio = _FakeAudio(open_delay_s=0.3)
    gateway = ArrayAudioGateway(on_audio=lambda _payload: None, audio=audio)
    gateway.start()
    gateway.set_mic(True)
    assert gateway.mic_open is True
    try:
        closed, armed = _race(
            gateway,
            lambda: gateway.close_mic("the session hung up after a long silence"),
            lambda: gateway.set_mic(True),
            gap_s=0.01,
        )
        assert not isinstance(closed, Exception), closed
        assert not isinstance(armed, Exception), armed
        # The arm ran second and won, so the ear is open — and OPEN has to mean
        # every physical fact behind it, not just the flag.
        if gateway.mic_open:
            assert audio.input_streams[-1].closed is False
            assert audio.output_streams[-1].closed is False
            assert "parcel-array-capture" in {t.name for t in threading.enumerate()}
            heard: list[bytes] = []
            gateway._on_audio = heard.append
            audio.input_streams[-1].feed(_two_beam_block(640))
            assert _wait_for(lambda: len(heard) == 1), "an ear that says open must hear"
        else:
            _assert_shut_and_consistent(gateway, audio)
    finally:
        gateway.stop()


def test_a_stop_landing_inside_an_arm_leaves_the_gateway_stopped() -> None:
    """The other bypass HO-5 names: ``runtime.close()`` → ``stop()``.

    ``running`` False and ``mic_open`` True at the same time is the same lie in
    a different costume.
    """

    audio = _FakeAudio(open_delay_s=0.3)
    gateway = ArrayAudioGateway(on_audio=lambda _payload: None, audio=audio)
    gateway.start()
    armed, _stopped = _race(gateway, lambda: gateway.set_mic(True), gateway.stop, gap_s=0.05)
    assert not isinstance(_stopped, Exception), _stopped
    assert gateway.running is False
    assert gateway.mic_open is False, "a stopped gateway may never report a live ear"
    if isinstance(armed, Exception):
        assert isinstance(armed, GatewayNotRunningError)
    _assert_shut_and_consistent(gateway, audio)


def test_no_capture_thread_survives_stop() -> None:
    """HY-1's rule applied to this card: nothing this gateway starts outlives it."""

    before = {thread.name for thread in threading.enumerate()}
    audio = _FakeAudio()
    gateway = ArrayAudioGateway(on_audio=lambda _payload: None, audio=audio)
    gateway.start()
    gateway.set_mic(True)
    audio.input_streams[-1].feed(_two_beam_block(640))
    gateway.stop()
    assert _wait_for(
        lambda: (
            not [
                thread for thread in threading.enumerate() if thread.name == "parcel-array-capture"
            ]
        )
    ), f"a capture thread outlived stop(); before={sorted(before)}"
