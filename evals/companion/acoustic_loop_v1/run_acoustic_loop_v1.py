#!/usr/bin/env python
"""ACOUSTIC_LOOP_V1 — Tier-1 acoustic evaluation over a virtual PipeWire rig.

WHAT THIS MEASURES THAT THE SOFTWARE TIER CANNOT
    ``duplex_v1`` asserts at the session API: it knows when a chunk was
    *enqueued*. This suite asserts at the audio boundary: it knows when sound
    actually started and stopped, because every timestamp is anchored to a
    null-sink monitor recording rather than to a callback return. That is the
    difference between "the code decided to speak" and "audio existed".

    Four case families, all on frozen fixtures:
      endpointing  every commit on the loop sample clock, with ep50/ep90 only
                   over cases having exactly one valid post-final commit.
      bargein      interrupt onset -> detection -> queue flush, plus a retained
                   mixed-channel STOP diagnostic that is not gate evidence.
      duplex       acoustically-anchored end-of-owner-speech -> first audible
                   robot audio, decomposed against the enqueue-time number
                   the software ledger would have reported.
      prosody      one-to-one pitch-accent preservation through the virtual
                   transport. No motion command or actuator is observed.

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
import functools
import hashlib
import itertools
import json
import platform
import shutil
import statistics
import subprocess
import sys
import threading
import time
from collections.abc import Mapping
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
RUNNER_VERSION = "virtual-pipewire-rig-v2-measurement-validity"
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
    "endpointing_commit_validity_failure_rate_max": 0.0,
    "endpointing_ep50_s_max": 0.500,
    "endpointing_ep90_s_max": 1.000,
    "bargein_detection_s_max": 0.400,
    "bargein_flush_s_max": 0.060,
    "bargein_acoustic_stop_s_max": 0.520,
    "bargein_false_rate_max": 0.02,
    "duplex_virtual_audible_ack_p50_s_max": 0.700,
    "prosody_audio_transport_match_min": 0.80,
}

ISOLATED_ROBOT_CHANNEL_BASIS = "isolated_robot_output_channel"
MIXED_STOP_UNMEASURED_REASON = (
    "the sink monitor mixes owner and robot audio; mixed-minus-owner power "
    "subtraction is diagnostic only and is not an isolated robot-output channel"
)
PHYSICAL_MOTION_UNMEASURED_REASON = (
    "this family observes audio transport only; it does not construct BeatLayer, "
    "observe a motion command, or measure an actuator"
)


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


def assess_endpoint_commits(
    *,
    kind: str,
    commit_sample_clocks_s: list[float],
    final_speech_end_s: float,
    incomplete_hold_s: float,
) -> dict[str, Any]:
    """Classify every commit on the loop's sample clock.

    Complete and pause-heavy turns are valid only when exactly one commit
    follows final speech and no earlier commit fired. Incomplete fixtures are
    not required to commit, but any commit before their full hold interval is
    an explicit failure. Multiple or non-monotonic callbacks invalidate every
    kind rather than allowing a convenient commit to hide the others.
    """

    commits = [float(value) for value in commit_sample_clocks_s]
    premature = [value for value in commits if value < final_speech_end_s]
    post_final = [value for value in commits if value >= final_speech_end_s]
    non_monotonic = any(
        current < previous for previous, current in itertools.pairwise(commits)
    )
    multiple = len(commits) > 1
    incomplete_not_before = final_speech_end_s + incomplete_hold_s
    incomplete_early = kind == "incomplete" and any(
        value < incomplete_not_before for value in commits
    )

    reasons: list[str] = []
    if premature:
        reasons.append("premature_commit")
    if multiple:
        reasons.append("multiple_commits")
    if non_monotonic:
        reasons.append("non_monotonic_commit_clock")
    if kind in {"complete", "pause_heavy"} and len(post_final) != 1:
        reasons.append("expected_exactly_one_post_final_commit")
    if incomplete_early:
        reasons.append("incomplete_early_commit")

    valid = not reasons
    ep_s: float | None = None
    if valid and kind in {"complete", "pause_heavy"}:
        ep_s = post_final[0] - final_speech_end_s
    elif valid and kind == "incomplete" and commits:
        ep_s = commits[0] - final_speech_end_s

    return {
        "commit_sample_clocks_s": commits,
        "commit_count": len(commits),
        "premature_commit_sample_clocks_s": premature,
        "post_final_commit_sample_clocks_s": post_final,
        "premature_commit": bool(premature),
        "multiple_commits": multiple,
        "non_monotonic_commits": non_monotonic,
        "incomplete_early": incomplete_early,
        "incomplete_commit_not_before_s": (
            incomplete_not_before if kind == "incomplete" else None
        ),
        "endpoint_measurement_valid": valid,
        "endpoint_invalid_reasons": reasons,
        "ep_s": ep_s,
    }


def monotonic_one_to_one_matches(
    expected_s: list[float],
    observed_s: list[float],
    *,
    window_s: float,
) -> list[tuple[float, float]]:
    """Return the maximum-cardinality ordered matching inside ``window_s``.

    A captured accent can be used at most once. Among matchings with the same
    cardinality, the one with the lowest total absolute lag wins. Inputs must
    already be on the same origin and monotonically ordered.
    """

    if not np.isfinite(window_s) or window_s < 0.0:
        raise ValueError("match window must be finite and non-negative")
    expected = tuple(float(value) for value in expected_s)
    observed = tuple(float(value) for value in observed_s)
    for name, values in (("expected", expected), ("observed", observed)):
        if any(not np.isfinite(value) for value in values):
            raise ValueError(f"{name} accent clocks must be finite")
        if any(
            current < previous for previous, current in itertools.pairwise(values)
        ):
            raise ValueError(f"{name} accent clocks must be monotonic")

    @functools.cache
    def solve(expected_index: int, observed_index: int) -> tuple[tuple[int, int], ...]:
        if expected_index >= len(expected) or observed_index >= len(observed):
            return ()
        candidates = [
            solve(expected_index + 1, observed_index),
            solve(expected_index, observed_index + 1),
        ]
        if abs(observed[observed_index] - expected[expected_index]) <= window_s:
            candidates.append(
                ((expected_index, observed_index),)
                + solve(expected_index + 1, observed_index + 1)
            )

        def rank(pairs: tuple[tuple[int, int], ...]) -> tuple[Any, ...]:
            total_lag = sum(
                abs(observed[observed_i] - expected[expected_i])
                for expected_i, observed_i in pairs
            )
            return (-len(pairs), total_lag, pairs)

        return min(candidates, key=rank)

    return [
        (expected[expected_index], observed[observed_index])
        for expected_index, observed_index in solve(0, 0)
    ]


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
    # A recorder can begin after the injected owner utterance has already
    # started.  In that case ``offset`` is negative: discard the portion of
    # the owner envelope that lies before the mixed capture and align the
    # remaining overlap at frame zero.  Assigning with a negative slice start
    # used to create an empty destination and crash the whole barge-in suite.
    if offset < 0:
        owner = owner[-offset:]
        offset = 0
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
        commit_sample_clocks_s: list[float] = []
        loop_ref: list[MicrophoneVoiceLoop] = []

        stop = threading.Event()
        tee = TeeFrames(rig.capture_frames(stop=stop))

        # The observer's payload is an utterance duration in the current
        # runtime, not a commit timestamp. Read the loop sample clock inside
        # the synchronous callback instead. Accept arbitrary observer args so
        # evaluator validity does not depend on a decorative callback shape.
        def record_commit(
            *_args: Any,
            _sink: list[float] = commit_sample_clocks_s,
            _loop_ref: list[MicrophoneVoiceLoop] = loop_ref,
            **_kwargs: Any,
        ) -> None:
            if _loop_ref:
                _sink.append(float(_loop_ref[0]._elapsed_s))

        loop = MicrophoneVoiceLoop(
            recognizer=FakeRecognizer(),
            submit_text=lambda *a, **k: None,
            barge_in=lambda: None,
            playback_active=lambda: False,
            frames=tee,
            neural_vad=neural,
            endpointer=endpointer,
            on_turn_commit=record_commit,
        )
        loop_ref.append(loop)
        loop.start()
        time.sleep(0.6)  # let capture link before injecting
        rig.play_file(fixture_path(entry))
        # Do not stop at the first commit: that hid an internal-pause cutoff
        # followed by a second commit after resumed speech. Observe beyond the
        # incomplete timeout so every commit relevant to this fixture is kept.
        deadline = time.monotonic() + endpointer.incomplete_silence_s + 0.75
        while time.monotonic() < deadline:
            time.sleep(0.02)
        stop.set()
        loop.close()
        observation_end_s = float(loop._elapsed_s)

        captured = tee.samples()
        onset = rig_mod.audio_onset_s(
            captured, threshold=ONSET_RMS_THRESHOLD, frame=ANALYSIS_FRAME
        )
        detail: dict[str, Any] = {
            "name": entry["name"],
            "kind": entry["kind"],
            "family": "endpointing",
            "fired": bool(commit_sample_clocks_s),
            "captured_s": round(captured.size / SAMPLE_RATE_HZ, 4),
            "capture_onset_s": round(onset, 4) if onset is not None else None,
            "loop_sample_clock_observed_until_s": round(observation_end_s, 4),
            "commit_count": len(commit_sample_clocks_s),
            "commit_sample_clocks_s": [
                round(value, 4) for value in commit_sample_clocks_s
            ],
            "multiple_commits": len(commit_sample_clocks_s) > 1,
            "commit_observer_complete": (
                len(commit_sample_clocks_s) == loop.turn_commits
            ),
            "endpointer_detail": endpointer.detail,
        }
        if onset is None or entry["speech_end_s"] is None:
            detail["verdict"] = "no_onset"
            detail["endpoint_measurement_valid"] = False
            detail["endpoint_invalid_reasons"] = ["no_capture_onset"]
            detail["ep_s"] = None
            cases.append(detail)
            continue

        # The injected waveform's speech interval is preserved through the
        # rig, so ground truth inside the capture is the capture onset plus
        # the fixture's own speech-start -> speech-end distance.
        speech_span = float(entry["speech_end_s"]) - float(entry["speech_start_s"])
        ground_truth = onset + speech_span
        assessment = assess_endpoint_commits(
            kind=str(entry["kind"]),
            commit_sample_clocks_s=commit_sample_clocks_s,
            final_speech_end_s=ground_truth,
            incomplete_hold_s=endpointer.incomplete_silence_s,
        )
        if len(commit_sample_clocks_s) != loop.turn_commits:
            assessment["endpoint_measurement_valid"] = False
            assessment["endpoint_invalid_reasons"].append(
                "commit_observer_count_mismatch"
            )
            assessment["ep_s"] = None
        for field_name in (
            "commit_sample_clocks_s",
            "premature_commit_sample_clocks_s",
            "post_final_commit_sample_clocks_s",
        ):
            assessment[field_name] = [
                round(value, 4) for value in assessment[field_name]
            ]
        if assessment["incomplete_commit_not_before_s"] is not None:
            assessment["incomplete_commit_not_before_s"] = round(
                assessment["incomplete_commit_not_before_s"], 4
            )
        if assessment["ep_s"] is not None:
            assessment["ep_s"] = round(assessment["ep_s"], 4)
        detail.update(
            {
                "ground_truth_end_s": round(ground_truth, 4),
                **assessment,
                "cutoff": bool(
                    assessment["premature_commit"]
                    or assessment["incomplete_early"]
                ),
                "verdict": (
                    "ok"
                    if assessment["endpoint_measurement_valid"]
                    else assessment["endpoint_invalid_reasons"][0]
                ),
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

        with rig.record_monitor(rig.sink_name, monitor_raw):
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
        diagnostic_residual_end = None
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
                    diagnostic_residual_end = float(
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
        if is_speech:
            detail.update(
                {
                    "acoustic_stop_s": None,
                    "acoustic_stop_status": "not_measured",
                    "acoustic_stop_measurement_basis": (
                        "mixed_sink_monitor_without_isolated_robot_channel"
                    ),
                    "acoustic_stop_unmeasured_reason": MIXED_STOP_UNMEASURED_REASON,
                }
            )
        if is_speech and detections and onset_monotonic is not None:
            detection_lag = detections[0] - onset_monotonic
            flush = (flush_done - interrupt_requested) if flush_done else None
            # Retain the historical subtraction for diagnosis only. The sink
            # monitor mixes owner and robot paths that have separate filtering
            # and resampling, so subtracting their powers cannot establish when
            # robot output stopped.
            diagnostic_residual_stop_lag = None
            if (
                interrupt_onset_file is not None
                and diagnostic_residual_end is not None
            ):
                diagnostic_residual_stop_lag = (
                    diagnostic_residual_end - interrupt_onset_file
                )
            detail.update(
                {
                    "detection_s": round(detection_lag, 4),
                    "flush_s": round(flush, 6) if flush is not None else None,
                    "diagnostic_mixed_minus_owner_stop_s": round(
                        diagnostic_residual_stop_lag, 4
                    )
                    if diagnostic_residual_stop_lag is not None
                    else None,
                    "interrupt_onset_file_s": round(interrupt_onset_file, 4)
                    if interrupt_onset_file is not None
                    else None,
                    "diagnostic_residual_end_file_s": round(
                        diagnostic_residual_end, 4
                    )
                    if diagnostic_residual_end is not None
                    else None,
                    "verdict": (
                        "detection_ok_acoustic_stop_unmeasured"
                        if detection_lag >= 0
                        else "impossible"
                    ),
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
    # Preserve the fixture's declared sample rate. Passing its raw 22.05 kHz
    # PCM to SpeakerSink would invoke the 16 kHz raw default and stretch the
    # leading silence, manufacturing presentation latency.
    reply_wav = fixture_path(reply).read_bytes()

    for name in ("query_01", "query_02", "query_03"):
        entry = corpus[name]
        monitor_raw = RESULTS_DIR / ".tmp" / f"duplex_{name}.raw"
        speaker = SpeakerSink(device=sink_index)
        stop = threading.Event()
        tee = TeeFrames(rig.capture_frames(stop=stop))
        enqueue_attempts: list[float] = []

        def respond(
            _text: str,
            _speaker: SpeakerSink = speaker,
            _enqueue_attempts: list[float] = enqueue_attempts,
            **_kwargs: Any,
        ) -> None:
            # This clock is queue admission ATTEMPT, not playback. Keep it as
            # a separate diagnostic from the output-buffer write attempt and
            # the monitor-observed virtual presentation below.
            # Loop variables are bound as defaults so each case writes to its
            # own sink and list rather than the last iteration's.
            _speaker.begin_utterance()
            _enqueue_attempts.append(time.monotonic())
            _speaker.enqueue(reply_wav, token=None)

        loop = MicrophoneVoiceLoop(
            recognizer=FakeRecognizer("scripted transcript"),
            submit_text=respond,
            barge_in=lambda: None,
            playback_active=lambda _s=speaker: _s.playback_active,
            frames=tee,
            neural_vad=SileroVad(str(VAD_MODEL)),
            endpointer=TurnEndpointer(str(TURN_MODEL)),
        )

        with rig.record_monitor(rig.sink_name, monitor_raw):
            loop.start()
            time.sleep(0.5)
            rig.play_file(fixture_path(entry))
            deadline = time.monotonic() + 6.0
            while time.monotonic() < deadline and not enqueue_attempts:
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
            "kind": "virtual_audible_ack",
            "enqueue_attempted": bool(enqueue_attempts),
            "virtual_audible_presented": False,
            "enqueue_attempt_count": len(enqueue_attempts),
        }
        if (
            onset is not None
            and entry["speech_end_s"] is not None
            and enqueue_attempts
        ):
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
                enqueue_attempt_ack = None
                output_write_attempt_ack = None
                owner_end_monotonic = tee.monotonic_at(onset + span)
                if owner_end_monotonic is not None:
                    enqueue_attempt_ack = (
                        enqueue_attempts[0] - owner_end_monotonic
                    )
                    write_attempt_monotonic = getattr(
                        speaker,
                        "first_chunk_write_attempt_monotonic",
                        None,
                    )
                    if isinstance(write_attempt_monotonic, (int, float)):
                        output_write_attempt_ack = (
                            float(write_attempt_monotonic) - owner_end_monotonic
                        )
                detail.update(
                    {
                        "virtual_audible_ack_s": round(ack, 4),
                        "virtual_audible_presented": True,
                        "enqueue_attempt_ack_s": round(enqueue_attempt_ack, 4)
                        if enqueue_attempt_ack is not None
                        else None,
                        "output_write_attempt_ack_s": round(
                            output_write_attempt_ack, 4
                        )
                        if output_write_attempt_ack is not None
                        else None,
                        "owner_end_file_s": round(owner_end_file, 4),
                        "robot_onset_file_s": round(robot_onset_file, 4),
                        "ack_clock_labels": {
                            "enqueue_attempt_ack_s": (
                                "owner end -> SpeakerSink.enqueue call attempt; "
                                "not a playback timestamp"
                            ),
                            "output_write_attempt_ack_s": (
                                "owner end -> first output-buffer write attempt; "
                                "not device acceptance or audible presentation"
                            ),
                            "virtual_audible_ack_s": (
                                "virtual acoustic owner end -> first robot sample, "
                                "both read from one sink-monitor recording"
                            ),
                        },
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
    """Measure accent preservation through virtual audio transport.

    This family has no motion observer. It compares the synthesis-side accent
    track with the sink-monitor track on a common first-audible-sample origin;
    physical BeatLayer/actuator synchronization is reported separately as
    unmeasured.
    """

    entry = corpus["expressive_01"]
    pcm, rate = wav_pcm16(fixture_path(entry))
    synth_track = prosody.analyze_pcm16(pcm, rate)
    source_frame = max(1, round(rate * ANALYSIS_FRAME / SAMPLE_RATE_HZ))
    source_onset = rig_mod.audio_onset_s(
        np.frombuffer(pcm, dtype=np.int16),
        threshold=ONSET_RMS_THRESHOLD,
        frame=source_frame,
        rate=rate,
    )

    sink_index = rig.sounddevice_index(rig.sink_name, "output")
    monitor_raw = RESULTS_DIR / ".tmp" / "prosody.raw"
    speaker = SpeakerSink(device=sink_index)

    with rig.record_monitor(rig.sink_name, monitor_raw):
        time.sleep(0.3)
        speaker.begin_utterance()
        # Keep the WAV header so SpeakerSink uses the fixture's real 22.05 kHz
        # rate instead of treating raw bytes as its 16 kHz default.
        speaker.enqueue(fixture_path(entry).read_bytes(), token="prosody")
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

    if source_onset is None or onset is None or monitor.size == 0:
        return [
            {
                "name": entry["name"],
                "family": "prosody",
                "kind": "audio_transport_accent_preservation",
                "physical_motion_status": "not_measured",
                "physical_motion_sync_s": None,
                "physical_motion_unmeasured_reason": (
                    PHYSICAL_MOTION_UNMEASURED_REASON
                ),
                "verdict": "no_audio",
            }
        ]

    captured_track = prosody.analyze_pcm16(monitor.tobytes(), SAMPLE_RATE_HZ)

    # Both tracks retain their own leading silence during analysis. Subtract
    # each track's measured audible onset only after accent extraction so the
    # compared values share one utterance-local presentation origin.
    expected = [accent.time_s - source_onset for accent in synth_track.accents]
    observed = [accent.time_s - onset for accent in captured_track.accents]
    matches = monotonic_one_to_one_matches(
        expected,
        observed,
        window_s=ACCENT_MATCH_WINDOW_S,
    )
    lags = [captured_s - source_s for source_s, captured_s in matches]
    matched = len(matches)
    within = (matched / len(expected)) if expected else 0.0
    return [
        {
            "name": entry["name"],
            "family": "prosody",
            "kind": "audio_transport_accent_preservation",
            "source_audio_onset_s": round(source_onset, 4),
            "captured_audio_onset_s": round(onset, 4),
            "transport_clock_origin": "first audible sample in each audio track",
            "transport_matching": "monotonic_one_to_one",
            "synthesis_accents": len(expected),
            "captured_accents": len(observed),
            "transport_accents_matched": matched,
            "transport_within_window_rate": round(within, 4),
            "median_transport_lag_s": round(statistics.median(lags), 4)
            if lags
            else None,
            "transport_abs_lag_p95_s": round(
                percentile([abs(value) for value in lags], 0.95), 4
            )
            if lags
            else None,
            "match_window_s": ACCENT_MATCH_WINDOW_S,
            "physical_motion_status": "not_measured",
            "physical_motion_sync_s": None,
            "physical_motion_unmeasured_reason": PHYSICAL_MOTION_UNMEASURED_REASON,
            "verdict": "transport_ok" if expected and observed else "no_accents",
        }
    ]


# ------------------------------------------------------------------ metrics
def summarize(cases: list[dict]) -> dict[str, Any]:
    metrics: dict[str, Any] = {}

    ep_cases = [c for c in cases if c["family"] == "endpointing"]
    clean = [
        c
        for c in ep_cases
        if c.get("endpoint_measurement_valid") is True
        and c.get("ep_s") is not None
    ]
    eps = [float(c["ep_s"]) for c in clean]
    if ep_cases:
        invalid = [
            c for c in ep_cases if c.get("endpoint_measurement_valid") is not True
        ]
        cutoffs = [c for c in ep_cases if c.get("cutoff")]
        ended = [c for c in clean if c["kind"] in {"complete", "pause_heavy"}]
        ended_eps = [float(c["ep_s"]) for c in ended]
        held = [float(c["ep_s"]) for c in clean if c["kind"] == "incomplete"]
        metrics["endpointing"] = {
            "cases": len(ep_cases),
            "cases_with_commits": len(
                [c for c in ep_cases if int(c.get("commit_count", 0)) > 0]
            ),
            "total_commits": sum(int(c.get("commit_count", 0)) for c in ep_cases),
            "valid_latency_cases": len(clean),
            "ep_definition": (
                "the sole post-final commit sample clock minus final speech end "
                "on the same captured-sample clock, over valid complete and "
                "pause-heavy cases"
            ),
            "ep50_s": percentile(ended_eps, 0.50),
            "ep90_s": percentile(ended_eps, 0.90),
            "ep_cutoff_rate": len(cutoffs) / len(ep_cases),
            "commit_validity_failure_rate": len(invalid) / len(ep_cases),
            "premature_cases": len(
                [c for c in ep_cases if c.get("premature_commit")]
            ),
            "multiple_commit_cases": len(
                [c for c in ep_cases if c.get("multiple_commits")]
            ),
            "incomplete_early_cases": len(
                [c for c in ep_cases if c.get("incomplete_early")]
            ),
            "missing_or_extra_post_final_cases": len(
                [
                    c
                    for c in ep_cases
                    if "expected_exactly_one_post_final_commit"
                    in c.get("endpoint_invalid_reasons", [])
                ]
            ),
            "ep50_all_kinds_s": percentile(eps, 0.50),
            "incomplete_hold_p50_s": percentile(held, 0.50),
            "by_kind": {
                kind: {
                    "n": len([c for c in ep_cases if c["kind"] == kind]),
                    "valid_n": len([c for c in clean if c["kind"] == kind]),
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
        isolated_stops = [
            float(c["acoustic_stop_s"])
            for c in speech
            if c.get("acoustic_stop_measurement_basis")
            == ISOLATED_ROBOT_CHANNEL_BASIS
            and c.get("acoustic_stop_s") is not None
        ]
        stop_fully_measured = bool(speech) and len(isolated_stops) == len(speech)
        diagnostic_residual_stops = [
            float(c["diagnostic_mixed_minus_owner_stop_s"])
            for c in speech
            if c.get("diagnostic_mixed_minus_owner_stop_s") is not None
        ]
        stop_reason = None
        if not stop_fully_measured:
            stop_reason = next(
                (
                    str(c["acoustic_stop_unmeasured_reason"])
                    for c in speech
                    if c.get("acoustic_stop_unmeasured_reason")
                ),
                MIXED_STOP_UNMEASURED_REASON,
            )
        metrics["bargein"] = {
            "speech_cases": len(speech),
            "detected": len([c for c in speech if c.get("detected")]),
            "detection_p50_s": percentile(detections, 0.50),
            "detection_p90_s": percentile(detections, 0.90),
            "flush_p50_s": percentile(flushes, 0.50),
            "flush_max_s": max(flushes) if flushes else None,
            "acoustic_stop_status": (
                "measured" if stop_fully_measured else "not_measured"
            ),
            "acoustic_stop_measurement_basis": (
                ISOLATED_ROBOT_CHANNEL_BASIS if stop_fully_measured else None
            ),
            "acoustic_stop_unmeasured_reason": stop_reason,
            "acoustic_stop_p50_s": percentile(isolated_stops, 0.50)
            if stop_fully_measured
            else None,
            "acoustic_stop_p90_s": percentile(isolated_stops, 0.90)
            if stop_fully_measured
            else None,
            "diagnostic_mixed_minus_owner_stop_p50_s": percentile(
                diagnostic_residual_stops, 0.50
            ),
            "noise_cases": len(noise),
            "false_barge_in_rate": (
                len([c for c in noise if c.get("false_barge_in")]) / len(noise)
            )
            if noise
            else None,
        }

    dx = [c for c in cases if c["family"] == "duplex"]
    if dx:
        virtual_acks = [
            float(c["virtual_audible_ack_s"])
            for c in dx
            if c.get("virtual_audible_ack_s") is not None
        ]
        enqueue_attempt_acks = [
            float(c["enqueue_attempt_ack_s"])
            for c in dx
            if c.get("enqueue_attempt_ack_s") is not None
        ]
        write_attempt_acks = [
            float(c["output_write_attempt_ack_s"])
            for c in dx
            if c.get("output_write_attempt_ack_s") is not None
        ]
        virtual_ack_complete = len(virtual_acks) == len(dx)
        metrics["duplex"] = {
            "cases": len(dx),
            "enqueue_attempted": len(
                [c for c in dx if c.get("enqueue_attempted")]
            ),
            "virtual_audible_presented": len(virtual_acks),
            "enqueue_attempt_ack_p50_s": percentile(enqueue_attempt_acks, 0.50),
            "output_write_attempt_ack_p50_s": percentile(write_attempt_acks, 0.50),
            "virtual_audible_ack_status": (
                "measured" if virtual_ack_complete else "not_measured"
            ),
            "virtual_audible_ack_p50_s": percentile(virtual_acks, 0.50)
            if virtual_ack_complete
            else None,
            "virtual_audible_ack_p90_s": percentile(virtual_acks, 0.90)
            if virtual_ack_complete
            else None,
            "virtual_audible_ack_unmeasured_reason": None
            if virtual_ack_complete
            else "not every duplex case had a monitor-observed robot onset",
        }

    pr = [c for c in cases if c["family"] == "prosody"]
    if pr:
        metrics["prosody"] = {
            "audio_transport": {
                "within_window_rate": pr[0].get("transport_within_window_rate"),
                "median_lag_s": pr[0].get("median_transport_lag_s"),
                "abs_lag_p95_s": pr[0].get("transport_abs_lag_p95_s"),
                "clock_origin": pr[0].get("transport_clock_origin"),
                "matching": pr[0].get("transport_matching"),
            },
            "physical_motion": {
                "status": pr[0].get("physical_motion_status", "not_measured"),
                "sync_s": pr[0].get("physical_motion_sync_s"),
                "unmeasured_reason": pr[0].get(
                    "physical_motion_unmeasured_reason",
                    PHYSICAL_MOTION_UNMEASURED_REASON,
                ),
            },
        }
    return metrics


def evaluate_gates(metrics: dict[str, Any]) -> dict[str, Any]:
    """Compare against the frozen gates. Baselines are recorded, never tuned."""

    results: dict[str, Any] = {}

    def gate(
        name: str,
        value: float | None,
        limit: float,
        direction: str,
        *,
        unmeasured_reason: str | None = None,
    ) -> None:
        if value is None:
            results[name] = {
                "value": None,
                "limit": limit,
                "direction": direction,
                "status": "not_measured",
                "reason": unmeasured_reason or "required metric was absent",
            }
            return
        ok = value <= limit if direction == "max" else value >= limit
        results[name] = {
            "value": round(float(value), 4),
            "limit": limit,
            "direction": direction,
            "status": "pass" if ok else "FAIL",
        }

    ep = metrics.get("endpointing", {})
    gate(
        "endpointing_ep_cutoff_rate",
        ep.get("ep_cutoff_rate"),
        GATES["endpointing_ep_cutoff_rate_max"],
        "max",
    )
    gate(
        "endpointing_commit_validity_failure_rate",
        ep.get("commit_validity_failure_rate"),
        GATES["endpointing_commit_validity_failure_rate_max"],
        "max",
    )
    gate(
        "endpointing_ep50_s",
        ep.get("ep50_s"),
        GATES["endpointing_ep50_s_max"],
        "max",
    )
    gate(
        "endpointing_ep90_s",
        ep.get("ep90_s"),
        GATES["endpointing_ep90_s_max"],
        "max",
    )

    bi = metrics.get("bargein", {})
    gate(
        "bargein_detection_p50_s",
        bi.get("detection_p50_s"),
        GATES["bargein_detection_s_max"],
        "max",
    )
    gate(
        "bargein_flush_max_s",
        bi.get("flush_max_s"),
        GATES["bargein_flush_s_max"],
        "max",
    )
    gate(
        "bargein_acoustic_stop_p50_s",
        bi.get("acoustic_stop_p50_s"),
        GATES["bargein_acoustic_stop_s_max"],
        "max",
        unmeasured_reason=bi.get("acoustic_stop_unmeasured_reason"),
    )
    gate(
        "bargein_false_rate",
        bi.get("false_barge_in_rate"),
        GATES["bargein_false_rate_max"],
        "max",
    )

    dx = metrics.get("duplex", {})
    gate(
        "duplex_virtual_audible_ack_p50_s",
        dx.get("virtual_audible_ack_p50_s"),
        GATES["duplex_virtual_audible_ack_p50_s_max"],
        "max",
        unmeasured_reason=dx.get("virtual_audible_ack_unmeasured_reason"),
    )

    pr = metrics.get("prosody", {})
    audio_transport = pr.get("audio_transport", {})
    gate(
        "prosody_audio_transport_accent_match_rate",
        audio_transport.get("within_window_rate"),
        GATES["prosody_audio_transport_match_min"],
        "min",
    )
    physical_motion = pr.get("physical_motion", {})
    results["prosody_physical_motion_sync"] = {
        "value": physical_motion.get("sync_s"),
        "status": physical_motion.get("status", "not_measured"),
        "reason": physical_motion.get(
            "unmeasured_reason", PHYSICAL_MOTION_UNMEASURED_REASON
        ),
    }
    return results


def quality_exit_code(report: Mapping[str, Any]) -> int:
    """Translate a completed acoustic report into an automation-safe status."""

    return 0 if report.get("gates_passed") is True and report.get("teardown_clean") is True else 1


DOES_NOT_PROVE = [
    "room acoustics: this rig has no air, no reverberation and no room",
    "real microphone or loudspeaker behaviour: both endpoints are null sinks",
    "acoustic echo cancellation: there is no acoustic coupling to cancel",
    "human speech: the corpus is Piper-synthesized, not recorded from a person",
    "the sub-700ms ack bar end to end: the reply here is scripted, not generated",
    "spoken STOP recognition or emergency-latch timing: barge-in uses generic VAD",
    "robot acoustic STOP: this rig has no isolated robot-output capture channel",
    "physical prosody synchronization: no motion command or actuator is observed",
    "hardware AEC (XVF3800) performance: this null-sink run exercises no physical device",
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
    orphan_processes: list[str] = []

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
    orphan_processes = rig.live_child_processes()
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
        "orphan_processes_after_teardown": orphan_processes,
        "teardown_clean": not orphans and not orphan_processes,
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
                      "teardown_clean": not orphans and not orphan_processes}, indent=2))
    print(f"\nreport: {output}")
    # A quality runner must communicate its frozen gates to automation.  The
    # historical implementation always returned zero after successfully
    # writing a report, even when five of the nine gates were red.  That made
    # a shell/CI invocation indistinguishable from a passing measurement unless
    # a second program happened to reopen and interpret the JSON.  Preserve 2
    # above for an unavailable rig; use 1 for a completed but red/invalid run.
    return quality_exit_code(report)


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
