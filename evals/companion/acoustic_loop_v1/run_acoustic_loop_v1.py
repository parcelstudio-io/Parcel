#!/usr/bin/env python
"""ACOUSTIC_LOOP_V1 — Tier-1 acoustic evaluation over a virtual PipeWire rig.

WHAT THIS MEASURES THAT THE SOFTWARE TIER CANNOT
    ``duplex_v1`` asserts at the session API: it knows when a chunk was
    *enqueued*. This suite asserts at the audio boundary: it knows when sound
    actually started and stopped, because every timestamp is anchored to a
    null-sink monitor recording rather than to a callback return. That is the
    difference between "the code decided to speak" and "audio existed".

    Four case families, all on frozen fixtures:
      endpointing  ep50/ep90/ep-cutoff against Silero-derived ground-truth
                   turn ends, over complete / incomplete / pause-heavy turns.
      bargein      interrupt onset -> detection -> queue flush -> acoustic
                   silence, decomposed, plus false-barge-in rate on noise.
      duplex       acoustically-anchored end-of-owner-speech -> first audible
                   robot audio, decomposed against the enqueue-time number
                   the software ledger would have reported.
      prosody      nod apexes (scheduled from the synthesis-side beat track,
                   as the runtime schedules them) vs the pitch accents present
                   in the CAPTURED audio.

WHAT IT DOES NOT PROVE  (repeated in every report's does_not_prove)
    There is no air in this rig. No room acoustics, no reverberation, no real
    microphone, no real loudspeaker, no acoustic coupling and therefore no
    real echo. Nothing here says anything about how the robot behaves in a
    room, and no result from this suite may be quoted as a hardware or
    room-acoustics claim. Acoustic echo cancellation cannot be evaluated here
    at all — that is Tier-2 (acoustic_rig_v1), which is blocked on a physical
    transducer being attached. The speech is synthetic (Piper), so these are
    not human-voice numbers either.

USAGE
    .parcel/bin/python -m evals.companion.acoustic_loop_v1.run_acoustic_loop_v1
    ... --families endpointing,bargein --output results/run.json
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import platform
import shutil
import statistics
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

from parcel_robot.audio import prosody
from parcel_robot.audio.endpointing import SileroVad, TurnEndpointer
from parcel_robot.audio.voice_loop import (
    FRAME_SAMPLES,
    SAMPLE_RATE_HZ,
    MicrophoneVoiceLoop,
    SpeakerSink,
)

from . import rig as rig_mod

SUITE_ID = "parcel-acoustic-loop-v1"
RUNNER_VERSION = "virtual-pipewire-rig-v1"
RNG_SEED = 20260804

PACK_DIR = Path(__file__).resolve().parent
REPO_ROOT = PACK_DIR.parents[2]
MANIFEST_PATH = PACK_DIR / "manifest.json"
CORPUS_PATH = PACK_DIR / "fixtures" / "corpus.json"
RESULTS_DIR = PACK_DIR / "results"

VAD_MODEL = REPO_ROOT / "models" / "endpointing" / "silero_vad_v6.onnx"
TURN_MODEL = REPO_ROOT / "models" / "endpointing" / "smart_turn_v3.onnx"

# Analysis constants. Frozen here rather than tuned per run: an eval whose
# thresholds move with its results measures nothing.
ONSET_RMS_THRESHOLD = 150.0      # int16 RMS over 10 ms frames
SILENCE_RMS_THRESHOLD = 80.0     # "acoustically stopped" for the monitor
ANALYSIS_FRAME = 160             # 10 ms at 16 kHz
ACCENT_MATCH_WINDOW_S = 0.150    # head-nod / pitch-accent alignment literature

GATES = {
    "endpointing_ep_cutoff_rate_max": 0.05,
    "endpointing_ep50_s_max": 0.500,
    "endpointing_ep90_s_max": 1.000,
    "bargein_detection_s_max": 0.400,
    "bargein_flush_s_max": 0.060,
    "bargein_acoustic_stop_s_max": 0.520,
    "bargein_false_rate_max": 0.02,
    "duplex_ack_p50_s_max": 0.700,
    "prosody_apex_within_window_min": 0.80,
}


class EvalError(RuntimeError):
    pass


# ------------------------------------------------------------------ helpers
def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return float(ordered[0])
    position = fraction * (len(ordered) - 1)
    low = int(position)
    high = min(low + 1, len(ordered) - 1)
    weight = position - low
    return float(ordered[low] * (1 - weight) + ordered[high] * weight)


def verify_manifest(manifest_path: Path) -> dict:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    locked = manifest.get("locked_files")
    if not isinstance(locked, list) or not locked:
        raise EvalError("manifest locked_files must be a non-empty list")
    for item in locked:
        path = REPO_ROOT / str(item["path"])
        if not path.is_file():
            raise EvalError(f"locked file missing: {item['path']}")
        actual = sha256_of(path)
        if actual != item["sha256"]:
            raise EvalError(
                f"locked file {item['path']} changed\n"
                f"  expected {item['sha256']}\n  actual   {actual}\n"
                "The frozen pack was edited. Re-freeze deliberately or restore it."
            )
    return manifest


def _envelope(samples: np.ndarray, frame: int = ANALYSIS_FRAME) -> np.ndarray:
    return rig_mod.frame_rms(samples, frame)


def _onset_after(
    samples: np.ndarray, *, after_s: float, threshold: float = ONSET_RMS_THRESHOLD
) -> float | None:
    """First frame above ``threshold`` at or after ``after_s``."""

    rms = _envelope(samples)
    start = max(0, int(after_s * SAMPLE_RATE_HZ / ANALYSIS_FRAME))
    if start >= rms.size:
        return None
    hits = np.where(rms[start:] > threshold)[0]
    if hits.size == 0:
        return None
    return float((start + hits[0]) * ANALYSIS_FRAME / SAMPLE_RATE_HZ)


def align_lag_s(
    needle: np.ndarray,
    haystack: np.ndarray,
    *,
    search_from_s: float = 0.0,
    search_to_s: float | None = None,
) -> float | None:
    """Where does ``needle`` sit inside ``haystack``? (10 ms resolution)

    The virtual microphone is linked into the speaker node, so the clean
    mic-only capture is also present, mixed, inside the sink-monitor
    recording. Cross-correlating the two RMS envelopes recovers the exact
    offset between the two streams — which is what turns "two recordings with
    no shared clock" into one timeline, with no reliance on process
    start-up timing at all.

    Envelope-domain correlation (not sample-domain) because the two streams
    went through different resampling paths; only the energy contour is
    guaranteed to survive.
    """

    a = _envelope(needle)
    b = _envelope(haystack)
    # The needle must be materially SHORTER than the haystack or "valid"
    # correlation offers almost no candidate lags and the argmax degenerates
    # to a constant. Callers pass a short active window, not a whole capture.
    if a.size < 8 or b.size < a.size + 8:
        return None
    a = a - a.mean()
    b = b - b.mean()
    if not np.any(a) or not np.any(b):
        return None
    correlation = np.correlate(b, a, mode="valid")
    if correlation.size == 0:
        return None
    # Restrict the candidate lags. Without this the argmax happily locks onto
    # whatever is LOUDEST in the haystack (the robot's own speech) rather than
    # the quieter signal actually being located — the failure that produced a
    # constant 1.4 s "interrupt onset" at every sweep offset in the first
    # baseline. Callers who know roughly where to look must say so.
    low = max(0, int(search_from_s * SAMPLE_RATE_HZ / ANALYSIS_FRAME))
    high = (
        correlation.size
        if search_to_s is None
        else min(correlation.size, int(search_to_s * SAMPLE_RATE_HZ / ANALYSIS_FRAME) + 1)
    )
    if low >= high:
        return None
    window = correlation[low:high]
    peak = low + int(np.argmax(window))
    if float(np.max(window)) <= 0.0:
        return None
    return float(peak * ANALYSIS_FRAME / SAMPLE_RATE_HZ)


def robot_only_envelope(
    haystack: np.ndarray, needle: np.ndarray, needle_lag_s: float
) -> np.ndarray:
    """Remove the owner's injected audio from the sink-monitor envelope.

    The virtual mic is linked into the speaker node, so the monitor recording
    carries BOTH the robot and the owner. Reading "when did the robot stop"
    straight off that mix charges the robot for the owner's own interrupt
    tail — which is exactly the error that made the first baseline report a
    4.6 s stop time for a sink that had in fact already gone quiet.

    Uncorrelated signals add in power, so subtracting the aligned mic power
    from the mixed power recovers the robot's contribution. This is an
    approximation (the two are not perfectly uncorrelated) but it errs toward
    LEAVING energy in, i.e. toward reporting a slower stop, which is the safe
    direction for a gate.
    """

    mixed = _envelope(haystack)
    owner = _envelope(needle)
    offset = round(needle_lag_s * SAMPLE_RATE_HZ / ANALYSIS_FRAME)
    aligned = np.zeros_like(mixed)
    end = min(mixed.size, offset + owner.size)
    if offset < mixed.size and end > offset:
        aligned[offset:end] = owner[: end - offset]
    residual = np.square(mixed) - np.square(aligned)
    return np.sqrt(np.maximum(residual, 0.0))


@dataclass
class TeeFrames:
    """Frame source that records what the loop consumed, and when.

    The loop's own clock is a SAMPLE clock (frames * 30 ms). Pairing every
    frame with ``time.monotonic()`` at read time is what lets an acoustic
    event located in the recorded stream be converted to a wall-clock instant
    without trusting any cross-process timestamp.
    """

    source: Any
    frames: list[np.ndarray] = field(default_factory=list)
    stamps: list[float] = field(default_factory=list)

    def __iter__(self):
        for frame in self.source:
            self.frames.append(frame)
            self.stamps.append(time.monotonic())
            yield frame

    def samples(self) -> np.ndarray:
        if not self.frames:
            return np.zeros(0, dtype=np.int16)
        return np.concatenate(self.frames)

    def monotonic_at(self, seconds: float) -> float | None:
        """Convert a time offset inside the captured stream to monotonic."""

        if not self.stamps:
            return None
        frame_index = int(seconds * SAMPLE_RATE_HZ // FRAME_SAMPLES)
        index = min(frame_index, len(self.stamps) - 1)
        return self.stamps[index]


class FakeRecognizer:
    """Records what was submitted without paying for STT in timing cases."""

    def __init__(self, transcript: str = "scripted") -> None:
        self.transcript = transcript
        self.calls = 0

    def transcribe(self, wav_bytes: bytes) -> str:
        del wav_bytes
        self.calls += 1
        return self.transcript


def load_corpus() -> dict[str, dict]:
    corpus = json.loads(CORPUS_PATH.read_text(encoding="utf-8"))
    return {entry["name"]: entry for entry in corpus["utterances"]}


def fixture_path(entry: dict) -> Path:
    return PACK_DIR / entry["file"]


def wav_pcm16(path: Path) -> tuple[bytes, int]:
    import wave

    with wave.open(str(path), "rb") as reader:
        rate = reader.getframerate()
        return reader.readframes(reader.getnframes()), rate


# ------------------------------------------------------- family: endpointing
def run_endpointing(rig: rig_mod.AcousticRig, corpus: dict[str, dict]) -> list[dict]:
    """Inject each turn; measure when the semantic endpointer commits."""

    cases: list[dict] = []
    targets = [
        entry
        for entry in corpus.values()
        if entry["kind"] in {"complete", "incomplete", "pause_heavy"}
    ]
    for entry in sorted(targets, key=lambda item: item["name"]):
        neural = SileroVad(str(VAD_MODEL))
        endpointer = TurnEndpointer(str(TURN_MODEL))
        commits: list[float] = []

        stop = threading.Event()
        tee = TeeFrames(rig.capture_frames(stop=stop))
        loop = MicrophoneVoiceLoop(
            recognizer=FakeRecognizer(),
            submit_text=lambda *a, **k: None,
            barge_in=lambda: None,
            playback_active=lambda: False,
            frames=tee,
            neural_vad=neural,
            endpointer=endpointer,
            on_turn_commit=commits.append,
        )
        loop.start()
        time.sleep(0.6)  # let capture link before injecting
        rig.play_file(fixture_path(entry))
        # Wait for a commit, bounded by the incomplete-turn timeout plus slack.
        deadline = time.monotonic() + 6.0
        while time.monotonic() < deadline and loop.turn_commits == 0:
            time.sleep(0.02)
        commit_elapsed = loop._elapsed_s
        fired = loop.turn_commits > 0
        stop.set()
        loop.close()

        captured = tee.samples()
        onset = rig_mod.audio_onset_s(
            captured, threshold=ONSET_RMS_THRESHOLD, frame=ANALYSIS_FRAME
        )
        detail: dict[str, Any] = {
            "name": entry["name"],
            "kind": entry["kind"],
            "family": "endpointing",
            "fired": bool(fired),
            "captured_s": round(captured.size / SAMPLE_RATE_HZ, 4),
            "capture_onset_s": round(onset, 4) if onset is not None else None,
        }
        if not fired or onset is None or entry["speech_end_s"] is None:
            detail["verdict"] = "no_commit" if not fired else "no_onset"
            detail["ep_s"] = None
            cases.append(detail)
            continue

        # The injected waveform's speech interval is preserved through the
        # rig, so ground truth inside the capture is the capture onset plus
        # the fixture's own speech-start -> speech-end distance.
        speech_span = float(entry["speech_end_s"]) - float(entry["speech_start_s"])
        ground_truth = onset + speech_span
        ep = commit_elapsed - ground_truth
        detail.update(
            {
                "ground_truth_end_s": round(ground_truth, 4),
                "commit_s": round(commit_elapsed, 4),
                "ep_s": round(ep, 4),
                "cutoff": bool(ep < 0.0),
                "verdict": "cutoff" if ep < 0.0 else "ok",
                "endpointer_detail": endpointer.detail,
            }
        )
        cases.append(detail)
    return cases


# ----------------------------------------------------------- family: bargein
def run_bargein(rig: rig_mod.AcousticRig, corpus: dict[str, dict]) -> list[dict]:
    """Interrupt a long reply; decompose detection / flush / acoustic stop."""

    cases: list[dict] = []
    robot = corpus["robot_long_01"]
    robot_pcm, robot_rate = wav_pcm16(fixture_path(robot))
    sink_index = rig.sounddevice_index(rig.sink_name, "output")

    interrupts = [corpus["interrupt_01"], corpus["interrupt_02"]]
    noises = [corpus["noise_01"], corpus["noise_02"]]

    # Offsets into the robot's speech at which the owner cuts in.
    plan: list[tuple[dict, float, bool]] = []
    for offset in (2.0, 4.0, 6.0):
        for entry in interrupts:
            plan.append((entry, offset, True))
    for entry in noises:
        plan.append((entry, 3.0, False))

    for entry, offset_s, is_speech in plan:
        monitor_raw = RESULTS_DIR / ".tmp" / f"monitor_{entry['name']}_{offset_s}.raw"
        speaker = SpeakerSink(device=sink_index)
        playback_started: list[float] = []
        detections: list[float] = []
        stop = threading.Event()
        tee = TeeFrames(rig.capture_frames(stop=stop))

        def on_barge_in(_sink: list[float] = detections) -> None:
            # Bind the per-case list explicitly: a closure over the loop
            # variable would record into whichever case ran last.
            _sink.append(time.monotonic())

        loop = MicrophoneVoiceLoop(
            recognizer=FakeRecognizer(),
            submit_text=lambda *a, **k: None,
            barge_in=on_barge_in,
            playback_active=lambda _s=speaker: _s.playback_active,
            frames=tee,
            neural_vad=SileroVad(str(VAD_MODEL)),
            endpointer=TurnEndpointer(str(TURN_MODEL)),
            # The shipped half-duplex floor. There is no acoustic coupling in
            # this rig, so this guard is exercised but not stressed - which is
            # exactly why AEC cannot be evaluated at Tier 1.
            echo_guard_scale=2.5,
        )

        with rig.record_monitor(rig.sink_monitor_name, monitor_raw):
            loop.start()
            time.sleep(0.5)
            speaker.begin_utterance()
            # Chunk the reply so interrupt() has in-flight audio to abort.
            chunk_samples = int(robot_rate)  # 1 s chunks
            data = np.frombuffer(robot_pcm, dtype=np.int16)
            for start in range(0, data.size, chunk_samples):
                speaker.enqueue(
                    data[start : start + chunk_samples].tobytes(), token=None
                )
            playback_started.append(time.monotonic())
            time.sleep(offset_s)
            injector = rig.play_file_async(fixture_path(entry))
            interrupt_requested = None
            flush_done = None
            deadline = time.monotonic() + 5.0
            while time.monotonic() < deadline:
                if detections:
                    interrupt_requested = time.monotonic()
                    speaker.interrupt()
                    flush_done = time.monotonic()
                    break
                time.sleep(0.005)
            time.sleep(1.2)  # let the monitor capture the acoustic tail
            with contextlib.suppress(Exception):
                injector.terminate()
            speaker.close()
            stop.set()
            loop.close()

        monitor = rig_mod.read_raw_s16(monitor_raw)
        # The mic is linked into the sink, so the clean mic-only capture is
        # also present (mixed) inside this recording. Aligning a SHORT active
        # window of the mic against the file puts the interrupt onset on the
        # monitor's own sample clock — one timeline, no cross-process
        # anchoring anywhere in the number.
        captured = tee.samples()
        onset_monotonic = None
        interrupt_onset_file = None
        acoustic_end = None
        interrupt_onset_in_capture = rig_mod.audio_onset_s(
            captured, threshold=ONSET_RMS_THRESHOLD, frame=ANALYSIS_FRAME
        )
        playback_onset_file = rig_mod.audio_onset_s(
            monitor, threshold=ONSET_RMS_THRESHOLD, frame=ANALYSIS_FRAME
        )
        if interrupt_onset_in_capture is not None and playback_onset_file is not None:
            onset_monotonic = tee.monotonic_at(interrupt_onset_in_capture)
            start = int(interrupt_onset_in_capture * SAMPLE_RATE_HZ)
            window = captured[start : start + SAMPLE_RATE_HZ]  # 1 s of the burst
            # By construction the interrupt is injected offset_s after the
            # robot's first audible sample; pw-play adds a small startup
            # delay. Search only that neighbourhood.
            expected = playback_onset_file + offset_s
            lag = align_lag_s(
                window,
                monitor,
                search_from_s=max(0.0, expected - 0.5),
                search_to_s=expected + 1.5,
            )
            if lag is not None:
                interrupt_onset_file = lag
                robot_env = robot_only_envelope(
                    monitor, captured, lag - interrupt_onset_in_capture
                )
                loud = np.where(robot_env > SILENCE_RMS_THRESHOLD)[0]
                if loud.size:
                    acoustic_end = float(
                        (loud[-1] + 1) * ANALYSIS_FRAME / SAMPLE_RATE_HZ
                    )

        detail: dict[str, Any] = {
            "name": f"{entry['name']}@{offset_s:g}s",
            "family": "bargein",
            "kind": "speech_interrupt" if is_speech else "noise_only",
            "offset_s": offset_s,
            "detected": bool(detections),
            "monitor_samples": int(monitor.size),
            "echo_guard_suppressions": int(loop.echo_guard_suppressions),
        }
        if is_speech and detections and onset_monotonic is not None:
            detection_lag = detections[0] - onset_monotonic
            flush = (flush_done - interrupt_requested) if flush_done else None
            # Acoustic stop measured entirely inside the monitor file: from
            # the interrupt's own onset to the last sample the sink emitted.
            stop_lag = None
            if interrupt_onset_file is not None and acoustic_end is not None:
                stop_lag = acoustic_end - interrupt_onset_file
            detail.update(
                {
                    "detection_s": round(detection_lag, 4),
                    "flush_s": round(flush, 6) if flush is not None else None,
                    "acoustic_stop_s": round(stop_lag, 4)
                    if stop_lag is not None
                    else None,
                    "interrupt_onset_file_s": round(interrupt_onset_file, 4)
                    if interrupt_onset_file is not None
                    else None,
                    "acoustic_end_file_s": round(acoustic_end, 4)
                    if acoustic_end is not None
                    else None,
                    "verdict": "ok" if detection_lag >= 0 else "impossible",
                }
            )
        elif not is_speech:
            detail["false_barge_in"] = bool(detections)
            detail["verdict"] = "false_positive" if detections else "ok"
        else:
            detail["verdict"] = "not_detected"
        cases.append(detail)
        with contextlib.suppress(OSError):
            monitor_raw.unlink()
    return cases


# ------------------------------------------------------------ family: duplex
def run_duplex(rig: rig_mod.AcousticRig, corpus: dict[str, dict]) -> list[dict]:
    """Acoustic ack: end of owner speech -> first AUDIBLE robot audio.

    A scripted responder stands in for the language model on purpose. The
    quantity under test is the audio boundary, and an LLM in the loop would
    make the number a statement about Gemma's latency instead.
    """

    cases: list[dict] = []
    sink_index = rig.sounddevice_index(rig.sink_name, "output")
    reply = corpus["query_01"]  # stands in for the robot's spoken ack
    reply_pcm, _reply_rate = wav_pcm16(fixture_path(reply))

    for name in ("query_01", "query_02", "query_03"):
        entry = corpus[name]
        monitor_raw = RESULTS_DIR / ".tmp" / f"duplex_{name}.raw"
        speaker = SpeakerSink(device=sink_index)
        stop = threading.Event()
        tee = TeeFrames(rig.capture_frames(stop=stop))
        spoke_at: list[float] = []

        def respond(
            _text: str,
            _speaker: SpeakerSink = speaker,
            _spoke_at: list[float] = spoke_at,
            **_kwargs: Any,
        ) -> None:
            # The moment the transcript lands, the reply is enqueued. This is
            # the software ack; the acoustic ack is read off the monitor.
            # Loop variables are bound as defaults so each case writes to its
            # own sink and list rather than the last iteration's.
            _speaker.begin_utterance()
            _speaker.enqueue(reply_pcm, token=None)
            _spoke_at.append(time.monotonic())

        loop = MicrophoneVoiceLoop(
            recognizer=FakeRecognizer("scripted transcript"),
            submit_text=respond,
            barge_in=lambda: None,
            playback_active=lambda _s=speaker: _s.playback_active,
            frames=tee,
            neural_vad=SileroVad(str(VAD_MODEL)),
            endpointer=TurnEndpointer(str(TURN_MODEL)),
        )

        with rig.record_monitor(rig.sink_monitor_name, monitor_raw):
            loop.start()
            time.sleep(0.5)
            rig.play_file(fixture_path(entry))
            deadline = time.monotonic() + 6.0
            while time.monotonic() < deadline and not spoke_at:
                time.sleep(0.02)
            time.sleep(1.5)
            speaker.close()
            stop.set()
            loop.close()

        captured = tee.samples()
        onset = rig_mod.audio_onset_s(
            captured, threshold=ONSET_RMS_THRESHOLD, frame=ANALYSIS_FRAME
        )
        monitor = rig_mod.read_raw_s16(monitor_raw)

        detail: dict[str, Any] = {
            "name": name,
            "family": "duplex",
            "kind": "acoustic_ack",
            "responded": bool(spoke_at),
        }
        if onset is not None and entry["speech_end_s"] is not None and spoke_at:
            # Put the owner's speech on the monitor's clock, then read the
            # robot's first audible sample off the SAME file. Both ends of the
            # ack interval are therefore acoustic, which is the entire point:
            # the software ledger can only see the enqueue instant.
            span = float(entry["speech_end_s"]) - float(entry["speech_start_s"])
            lag = align_lag_s(captured, monitor)
            if lag is None:
                detail["verdict"] = "unalignable"
                cases.append(detail)
                with contextlib.suppress(OSError):
                    monitor_raw.unlink()
                continue
            owner_end_file = onset + span + lag
            robot_onset_file = _onset_after(
                monitor, after_s=owner_end_file + 0.02
            )
            if robot_onset_file is None:
                detail["verdict"] = "no_robot_audio"
            else:
                ack = robot_onset_file - owner_end_file
                # The enqueue-time number the software ledger would have
                # reported, for the honest side-by-side.
                enqueue_ack = None
                owner_end_monotonic = tee.monotonic_at(onset + span)
                if owner_end_monotonic is not None:
                    enqueue_ack = spoke_at[0] - owner_end_monotonic
                detail.update(
                    {
                        "acoustic_ack_s": round(ack, 4),
                        "enqueue_ack_s": round(enqueue_ack, 4)
                        if enqueue_ack is not None
                        else None,
                        "sink_presentation_s": round(ack - enqueue_ack, 4)
                        if enqueue_ack is not None
                        else None,
                        "owner_end_file_s": round(owner_end_file, 4),
                        "robot_onset_file_s": round(robot_onset_file, 4),
                        "ack_anchor": (
                            "acoustic end-of-owner-speech -> first audible robot "
                            "sample, both read off one sink-monitor recording"
                        ),
                        "verdict": "ok",
                    }
                )
        else:
            detail["verdict"] = "no_response"
        cases.append(detail)
        with contextlib.suppress(OSError):
            monitor_raw.unlink()
    return cases


# ----------------------------------------------------------- family: prosody
def run_prosody(rig: rig_mod.AcousticRig, corpus: dict[str, dict]) -> list[dict]:
    """Do nods land on the accents the owner actually HEARS?

    The runtime schedules a nod apex from the beat track of the audio it is
    about to synthesize. This case recomputes that synthesis-side schedule,
    then measures it against the accents present in the captured monitor
    audio. Any divergence is transport distortion the owner experiences and
    the synthesis-side fakes cannot see.
    """

    entry = corpus["expressive_01"]
    pcm, rate = wav_pcm16(fixture_path(entry))
    synth_track = prosody.analyze_pcm16(pcm, rate)

    sink_index = rig.sounddevice_index(rig.sink_name, "output")
    monitor_raw = RESULTS_DIR / ".tmp" / "prosody.raw"
    chunk_started: list[float] = []
    # on_chunk_start is the runtime's own beat anchor; using it here keeps the
    # eval on the same seam the production nod scheduling rides.
    speaker = SpeakerSink(
        device=sink_index,
        on_chunk_start=lambda _t: chunk_started.append(time.monotonic()),
    )

    with rig.record_monitor(rig.sink_monitor_name, monitor_raw):
        time.sleep(0.3)
        speaker.begin_utterance()
        speaker.enqueue(pcm, token="prosody")
        deadline = time.monotonic() + 30.0
        time.sleep(0.5)
        while time.monotonic() < deadline and speaker.playback_active:
            time.sleep(0.05)
        time.sleep(0.8)
        speaker.close()

    monitor = rig_mod.read_raw_s16(monitor_raw)
    onset = rig_mod.audio_onset_s(
        monitor, threshold=ONSET_RMS_THRESHOLD, frame=ANALYSIS_FRAME
    )
    with contextlib.suppress(OSError):
        monitor_raw.unlink()

    if onset is None or monitor.size == 0:
        return [
            {
                "name": entry["name"],
                "family": "prosody",
                "kind": "nod_sync",
                "verdict": "no_audio",
            }
        ]

    # Trim the recording to the utterance so both tracks share an origin.
    captured = monitor[int(onset * SAMPLE_RATE_HZ) :]
    captured_track = prosody.analyze_pcm16(captured.tobytes(), SAMPLE_RATE_HZ)

    # Nod apexes are scheduled at the synthesis-side accent times (the runtime
    # adds beats.lag_compensation_s, which is 0.0 in the shipped config).
    apexes = [accent.time_s for accent in synth_track.accents]
    heard = [accent.time_s for accent in captured_track.accents]
    lags: list[float] = []
    matched = 0
    for apex in apexes:
        if not heard:
            break
        nearest = min(heard, key=lambda t: abs(t - apex))
        lag = apex - nearest
        lags.append(lag)
        if abs(lag) <= ACCENT_MATCH_WINDOW_S:
            matched += 1

    within = (matched / len(apexes)) if apexes else 0.0
    return [
        {
            "name": entry["name"],
            "family": "prosody",
            "kind": "nod_sync",
            "synthesis_accents": len(apexes),
            "captured_accents": len(heard),
            "apexes_within_window": matched,
            "within_window_rate": round(within, 4),
            "median_signed_lag_s": round(statistics.median(lags), 4) if lags else None,
            "abs_lag_p95_s": round(percentile([abs(v) for v in lags], 0.95), 4)
            if lags
            else None,
            "match_window_s": ACCENT_MATCH_WINDOW_S,
            "verdict": "ok" if apexes and heard else "no_accents",
        }
    ]


# ------------------------------------------------------------------ metrics
def summarize(cases: list[dict]) -> dict[str, Any]:
    metrics: dict[str, Any] = {}

    ep_cases = [c for c in cases if c["family"] == "endpointing"]
    clean = [c for c in ep_cases if c.get("ep_s") is not None]
    eps = [float(c["ep_s"]) for c in clean]
    if ep_cases:
        cutoffs = [c for c in clean if c.get("cutoff")]
        # ep50/ep90 are defined over turns that ACTUALLY ended — the standard
        # endpointing-latency definition. An incomplete turn is supposed to be
        # held for incomplete_silence_s; folding that deliberate 2.5 s wait
        # into a latency percentile would measure the design, not the
        # implementation, and would make the number meaningless in both
        # directions. Incomplete turns are judged by ep-cutoff (did the
        # endpointer wrongly cut the owner off) and reported separately.
        ended = [c for c in clean if c["kind"] in {"complete", "pause_heavy"}]
        ended_eps = [float(c["ep_s"]) for c in ended]
        held = [float(c["ep_s"]) for c in clean if c["kind"] == "incomplete"]
        metrics["endpointing"] = {
            "cases": len(ep_cases),
            "committed": len(clean),
            "ep_definition": (
                "commit minus Silero-derived ground-truth turn end, over turns "
                "that actually ended (complete + pause_heavy)"
            ),
            "ep50_s": percentile(ended_eps, 0.50),
            "ep90_s": percentile(ended_eps, 0.90),
            "ep_cutoff_rate": (len(cutoffs) / len(clean)) if clean else None,
            "ep50_all_kinds_s": percentile(eps, 0.50),
            "incomplete_hold_p50_s": percentile(held, 0.50),
            "by_kind": {
                kind: {
                    "n": len([c for c in clean if c["kind"] == kind]),
                    "ep50_s": percentile(
                        [float(c["ep_s"]) for c in clean if c["kind"] == kind], 0.50
                    ),
                }
                for kind in sorted({c["kind"] for c in ep_cases})
            },
        }

    bi = [c for c in cases if c["family"] == "bargein"]
    speech = [c for c in bi if c["kind"] == "speech_interrupt"]
    noise = [c for c in bi if c["kind"] == "noise_only"]
    if bi:
        detections = [
            float(c["detection_s"]) for c in speech if c.get("detection_s") is not None
        ]
        flushes = [float(c["flush_s"]) for c in speech if c.get("flush_s") is not None]
        stops = [
            float(c["acoustic_stop_s"])
            for c in speech
            if c.get("acoustic_stop_s") is not None
        ]
        metrics["bargein"] = {
            "speech_cases": len(speech),
            "detected": len([c for c in speech if c["detected"]]),
            "detection_p50_s": percentile(detections, 0.50),
            "detection_p90_s": percentile(detections, 0.90),
            "flush_p50_s": percentile(flushes, 0.50),
            "flush_max_s": max(flushes) if flushes else None,
            "acoustic_stop_p50_s": percentile(stops, 0.50),
            "acoustic_stop_p90_s": percentile(stops, 0.90),
            "noise_cases": len(noise),
            "false_barge_in_rate": (
                len([c for c in noise if c.get("false_barge_in")]) / len(noise)
            )
            if noise
            else None,
        }

    dx = [c for c in cases if c["family"] == "duplex"]
    if dx:
        acks = [
            float(c["acoustic_ack_s"]) for c in dx if c.get("acoustic_ack_s") is not None
        ]
        metrics["duplex"] = {
            "cases": len(dx),
            "responded": len([c for c in dx if c.get("responded")]),
            "acoustic_ack_p50_s": percentile(acks, 0.50),
            "acoustic_ack_p90_s": percentile(acks, 0.90),
        }

    pr = [c for c in cases if c["family"] == "prosody"]
    if pr:
        metrics["prosody"] = {
            "within_window_rate": pr[0].get("within_window_rate"),
            "median_signed_lag_s": pr[0].get("median_signed_lag_s"),
            "abs_lag_p95_s": pr[0].get("abs_lag_p95_s"),
        }
    return metrics


def evaluate_gates(metrics: dict[str, Any]) -> dict[str, Any]:
    """Compare against the frozen gates. Baselines are recorded, never tuned."""

    results: dict[str, Any] = {}

    def gate(name: str, value: float | None, limit: float, direction: str) -> None:
        if value is None:
            results[name] = {"value": None, "limit": limit, "status": "not_measured"}
            return
        ok = value <= limit if direction == "max" else value >= limit
        results[name] = {
            "value": round(float(value), 4),
            "limit": limit,
            "direction": direction,
            "status": "pass" if ok else "FAIL",
        }

    ep = metrics.get("endpointing", {})
    gate("endpointing_ep_cutoff_rate", ep.get("ep_cutoff_rate"),
         GATES["endpointing_ep_cutoff_rate_max"], "max")
    gate("endpointing_ep50_s", ep.get("ep50_s"), GATES["endpointing_ep50_s_max"], "max")
    gate("endpointing_ep90_s", ep.get("ep90_s"), GATES["endpointing_ep90_s_max"], "max")

    bi = metrics.get("bargein", {})
    gate("bargein_detection_p50_s", bi.get("detection_p50_s"),
         GATES["bargein_detection_s_max"], "max")
    gate("bargein_flush_max_s", bi.get("flush_max_s"), GATES["bargein_flush_s_max"], "max")
    gate("bargein_acoustic_stop_p50_s", bi.get("acoustic_stop_p50_s"),
         GATES["bargein_acoustic_stop_s_max"], "max")
    gate("bargein_false_rate", bi.get("false_barge_in_rate"),
         GATES["bargein_false_rate_max"], "max")

    dx = metrics.get("duplex", {})
    gate("duplex_acoustic_ack_p50_s", dx.get("acoustic_ack_p50_s"),
         GATES["duplex_ack_p50_s_max"], "max")

    pr = metrics.get("prosody", {})
    gate("prosody_apex_within_window_rate", pr.get("within_window_rate"),
         GATES["prosody_apex_within_window_min"], "min")
    return results


DOES_NOT_PROVE = [
    "room acoustics: this rig has no air, no reverberation and no room",
    "real microphone or loudspeaker behaviour: both endpoints are null sinks",
    "acoustic echo cancellation: there is no acoustic coupling to cancel",
    "human speech: the corpus is Piper-synthesized, not recorded from a person",
    "the sub-700ms ack bar end to end: the reply here is scripted, not generated",
    "hardware AEC (XVF3800) performance: no device has ever been enumerated",
]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", default=str(MANIFEST_PATH))
    parser.add_argument("--output", default=None)
    parser.add_argument(
        "--families",
        default="endpointing,bargein,duplex,prosody",
        help="comma-separated subset to run",
    )
    parser.add_argument("--audio-profile", default="virtual-pipewire-null-sink")
    parser.add_argument("--node-prefix", default=None)
    args = parser.parse_args(argv)

    available, reason = rig_mod.rig_available()
    if not available:
        print(f"acoustic_loop_v1: rig unavailable: {reason}", file=sys.stderr)
        return 2

    manifest = verify_manifest(Path(args.manifest))
    corpus = load_corpus()
    families = [f.strip() for f in args.families.split(",") if f.strip()]
    prefix = args.node_prefix or rig_mod.default_prefix()

    (RESULTS_DIR / ".tmp").mkdir(parents=True, exist_ok=True)
    started = time.time()
    cases: list[dict] = []
    orphans: list[str] = []

    with rig_mod.AcousticRig(prefix=prefix) as rig:
        # One recording, one clock: everything the virtual mic hears is also
        # written to the speaker's monitor, so acoustic intervals are read
        # inside a single file instead of across two unsynchronized processes.
        rig.link_mic_into_sink()
        if "endpointing" in families:
            cases.extend(run_endpointing(rig, corpus))
        if "bargein" in families:
            cases.extend(run_bargein(rig, corpus))
        if "duplex" in families:
            cases.extend(run_duplex(rig, corpus))
        if "prosody" in families:
            cases.extend(run_prosody(rig, corpus))

    # Teardown assertion: the rig context manager destroyed its nodes; nothing
    # carrying our prefix may survive.
    time.sleep(0.5)
    orphans = rig_mod.orphan_nodes(prefix)
    # Raw monitor recordings are scratch, not evidence; the report carries the
    # derived timestamps. Leaving hundreds of MB of PCM behind would make the
    # results directory unusable as a committed artifact.
    shutil.rmtree(RESULTS_DIR / ".tmp", ignore_errors=True)

    metrics = summarize(cases)
    gates = evaluate_gates(metrics)
    verdicts = {case["name"]: case.get("verdict") for case in cases}

    report = {
        "schema_version": 1,
        "suite_id": SUITE_ID,
        "runner_version": RUNNER_VERSION,
        "tier": 1,
        "rng_seed": RNG_SEED,
        "started_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(started)),
        "duration_s": round(time.time() - started, 2),
        "families": families,
        "audio_profile": args.audio_profile,
        "node_prefix": prefix,
        "manifest_sha256": sha256_of(Path(args.manifest)),
        "locked_files": manifest["locked_files"],
        "environment": {
            "python": platform.python_version(),
            "platform": platform.platform(),
            "pipewire": _pipewire_version(),
        },
        "orphan_nodes_after_teardown": orphans,
        "teardown_clean": not orphans,
        "case_count": len(cases),
        "cases": cases,
        "case_verdicts": verdicts,
        "metrics": metrics,
        "gates": gates,
        "gates_passed": all(g["status"] == "pass" for g in gates.values()),
        "human_review_required": False,
        "does_not_prove": DOES_NOT_PROVE,
    }

    output = Path(args.output) if args.output else (
        RESULTS_DIR
        / f"acoustic-loop-v1-{time.strftime('%Y%m%d-%H%M%S', time.gmtime(started))}.json"
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

    print(json.dumps({"metrics": metrics, "gates": gates,
                      "teardown_clean": not orphans}, indent=2))
    print(f"\nreport: {output}")
    return 0


def _pipewire_version() -> str:
    try:
        result = subprocess.run(
            ["pw-cli", "--version"], capture_output=True, timeout=10, check=False
        )
        for line in (result.stdout or b"").decode().splitlines():
            if "libpipewire" in line:
                return line.strip()
    except (subprocess.SubprocessError, OSError):
        pass
    return "unknown"


if __name__ == "__main__":
    raise SystemExit(main())
