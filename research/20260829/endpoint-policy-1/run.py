"""Exploratory, in-sample SmartTurn/Silero endpoint-policy replay."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import platform
import sys
import wave
from collections.abc import Callable
from importlib import import_module, metadata
from pathlib import Path
from typing import Any

import numpy as np

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from evals.companion.acoustic_loop_v1 import run_acoustic_loop_v1 as acoustic_eval
from parcel_robot.audio.endpointing import SileroVad, TurnEndpointer

HERE = Path(__file__).resolve().parent
PACK = ROOT / "evals" / "companion" / "acoustic_loop_v1"
MANIFEST = PACK / "manifest.json"
CORPUS = PACK / "fixtures" / "corpus.json"
SILERO = ROOT / "models" / "endpointing" / "silero_vad_v6.onnx"
SMART_TURN = ROOT / "models" / "endpointing" / "smart_turn_v3.onnx"
ENDPOINTING_SOURCE = ROOT / "src" / "parcel_robot" / "audio" / "endpointing.py"
VOICE_LOOP_SOURCE = ROOT / "src" / "parcel_robot" / "audio" / "voice_loop.py"
CORPUS_BUILDER = ROOT / "scripts" / "build_acoustic_corpus.py"
V2_RESULTS = ROOT / "research" / "20260829" / "acoustic-eval-v2" / "results.json"

RATE = 16_000
INPUT_FRAME = 480
SILERO_FRAME = 512
FRAME_S = INPUT_FRAME / RATE
THRESHOLDS = (0.50, 0.70, 0.80, 0.90, 0.95, 0.98)
COMPLETE_SILENCES = (0.20, 0.35, 0.50, 0.75, 0.90)
PHASE_OFFSETS = (0, 120, 240, 360)
INCOMPLETE_SILENCE = 2.5
PROVISIONAL_ACK_S = 0.20
V2_EXPECTED_SHA256 = "40ac53e3ce5ba277c677cdf381f936c81e5455e43a0dae16a61656f8732244c2"
V2_EXPECTED_DEFECTS = frozenset({"pause_01", "pause_03", "incomplete_02", "incomplete_04"})


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * fraction
    low = math.floor(position)
    high = math.ceil(position)
    if low == high:
        return ordered[low]
    weight = position - low
    return ordered[low] * (1.0 - weight) + ordered[high] * weight


def load_wav(path: Path) -> tuple[np.ndarray, int]:
    with wave.open(str(path), "rb") as reader:
        if reader.getsampwidth() != 2:
            raise ValueError(f"{path}: expected PCM16")
        rate = reader.getframerate()
        channels = reader.getnchannels()
        raw = np.frombuffer(reader.readframes(reader.getnframes()), dtype=np.int16)
    if channels > 1:
        raw = np.rint(raw.reshape(-1, channels).mean(axis=1)).astype(np.int16)
    return raw.copy(), int(rate)


def corpus_resample_to_16k(samples: np.ndarray, source_rate: int) -> np.ndarray:
    """Match scripts/build_acoustic_corpus.py's frozen ground-truth resample."""

    if source_rate != 22_050:
        raise ValueError(f"expected frozen 22050 Hz fixture, received {source_rate}")
    ratio = RATE / source_rate
    taps = 101
    cutoff = 0.5 * ratio
    positions = np.arange(taps) - (taps - 1) / 2
    kernel = np.sinc(2 * cutoff * positions) * np.hanning(taps)
    kernel /= kernel.sum()
    filtered = np.convolve(samples.astype(np.float64), kernel, mode="same")
    out_len = int(samples.size * ratio)
    source_index = np.arange(out_len) / ratio
    resampled = np.interp(source_index, np.arange(samples.size), filtered)
    return np.clip(resampled, -32768, 32767).astype(np.int16)


def make_frames(samples: np.ndarray, phase_offset_samples: int) -> list[np.ndarray]:
    if phase_offset_samples not in PHASE_OFFSETS:
        raise ValueError("unregistered phase offset")
    padded = np.concatenate(
        (
            np.zeros(phase_offset_samples, dtype=np.int16),
            samples,
            np.zeros(RATE * 3, dtype=np.int16),
        )
    )
    frames: list[np.ndarray] = []
    for start in range(0, padded.size, INPUT_FRAME):
        frame = padded[start : start + INPUT_FRAME]
        if frame.size < INPUT_FRAME:
            frame = np.pad(frame, (0, INPUT_FRAME - frame.size))
        frames.append(frame.astype(np.int16, copy=False))
    return frames


def production_speech_flags(frames: list[np.ndarray]) -> list[bool]:
    """Reproduce MicrophoneVoiceLoop's continuous 480 -> 512 Silero feed."""

    vad = SileroVad(str(SILERO))
    if not vad.available:
        raise RuntimeError("Silero is unavailable")
    flags: list[bool] = []
    tail = np.empty(0, dtype=np.int16)
    last = False
    for frame in frames:
        tail = np.concatenate((tail, frame))
        while tail.size >= SILERO_FRAME:
            probability = vad.process(tail[:SILERO_FRAME])
            tail = tail[SILERO_FRAME:]
            last = probability >= vad.threshold
        flags.append(last)
    return flags


class SmartTurnProbability:
    """Exact pinned model inference with content-addressed deterministic reuse."""

    def __init__(self) -> None:
        self.probe = TurnEndpointer(str(SMART_TURN))
        if self.probe.detail != "smart-turn-v3":
            raise RuntimeError(f"SmartTurn unavailable: {self.probe.detail}")
        self.cache: dict[str, float] = {}

    def __call__(self, audio_tail: np.ndarray) -> float:
        key = hashlib.sha256(audio_tail.tobytes()).hexdigest()
        if key not in self.cache:
            self.probe._silence_started_at = None
            self.probe._completion_probability = None
            self.probe.observe(is_speech=False, audio_tail=audio_tail, now_s=0.0)
            probability = self.probe._completion_probability
            if not isinstance(probability, float) or not math.isfinite(probability):
                raise RuntimeError("SmartTurn produced no finite probability")
            self.cache[key] = probability
        return self.cache[key]

    def providers(self) -> list[str]:
        session = self.probe._session
        return list(session.get_providers()) if session is not None else []


def replay_policy(
    *,
    frames: list[np.ndarray],
    flags: list[bool],
    probability: Callable[[np.ndarray], float],
    confidence_threshold: float,
    complete_silence_s: float,
    provisional_ack_s: float = PROVISIONAL_ACK_S,
    force_short_timeout: bool = False,
    force_long_timeout: bool = False,
) -> dict[str, Any]:
    """Replay the production state machine and retain every commit/provisional."""

    if len(frames) != len(flags) or not frames:
        raise ValueError("frames and flags must be equally sized and non-empty")
    if not 0.0 <= confidence_threshold <= 1.0:
        raise ValueError("confidence threshold must be in [0, 1]")

    turn_active = False
    utterance = bytearray()
    silence_started_s: float | None = None
    completion_probability: float | None = None
    commits: list[float] = []
    opportunities: list[dict[str, Any]] = []
    active_opportunity: int | None = None
    provisional_open = False
    provisional_triggers: list[float] = []
    provisional_pre_commit_cancellations = 0
    provisional_commit_before_resume_contradictions = 0
    provisional_survived_to_commit = 0

    for index, (frame, is_speech) in enumerate(zip(frames, flags, strict=True)):
        now_s = (index + 1) * FRAME_S
        if is_speech:
            if active_opportunity is not None:
                opportunity = opportunities[active_opportunity]
                opportunity["followed_by_speech"] = True
                if bool(opportunity["provisional_triggered"]):
                    if opportunity["commit_sample_clock_s"] is None:
                        provisional_pre_commit_cancellations += 1
                    else:
                        provisional_commit_before_resume_contradictions += 1
                active_opportunity = None
            provisional_open = False
            silence_started_s = None
            completion_probability = None
            if not turn_active:
                turn_active = True
                utterance.clear()
        if turn_active:
            utterance.extend(frame.tobytes())

        if is_speech:
            continue
        if silence_started_s is None or now_s < silence_started_s:
            silence_started_s = now_s
            completion_probability = None
            if turn_active:
                completion_probability = float(
                    probability(np.frombuffer(bytes(utterance), dtype=np.int16))
                )
                active_opportunity = len(opportunities)
                opportunities.append(
                    {
                        "silence_start_frame": index,
                        "silence_start_s": now_s,
                        "completion_probability": completion_probability,
                        "followed_by_speech": False,
                        "provisional_triggered": False,
                        "provisional_trigger_sample_clock_s": None,
                        "commit_sample_clock_s": None,
                    }
                )

        elapsed_s = max(0.0, now_s - silence_started_s)
        if turn_active and not provisional_open and elapsed_s + 1e-9 >= provisional_ack_s:
            provisional_open = True
            provisional_triggers.append(now_s)
            if active_opportunity is None:
                raise RuntimeError("provisional trigger has no active silence opportunity")
            opportunities[active_opportunity]["provisional_triggered"] = True
            opportunities[active_opportunity]["provisional_trigger_sample_clock_s"] = now_s

        if completion_probability is None:
            continue
        if force_long_timeout:
            timeout_s = INCOMPLETE_SILENCE
        elif force_short_timeout:
            timeout_s = complete_silence_s
        else:
            timeout_s = (
                complete_silence_s
                if completion_probability >= confidence_threshold
                else INCOMPLETE_SILENCE
            )
        if turn_active and elapsed_s + 1e-9 >= timeout_s:
            commits.append(now_s)
            if active_opportunity is None:
                raise RuntimeError("commit has no active silence opportunity")
            opportunities[active_opportunity]["commit_sample_clock_s"] = now_s
            if provisional_open:
                provisional_survived_to_commit += 1
                provisional_open = False
            turn_active = False
            utterance.clear()

    return {
        "commit_sample_clocks_s": commits,
        "opportunities": opportunities,
        "provisional_trigger_sample_clocks_s": provisional_triggers,
        "provisional_pre_commit_cancellation_count": provisional_pre_commit_cancellations,
        "provisional_commit_before_resume_contradiction_count": (
            provisional_commit_before_resume_contradictions
        ),
        "provisional_survived_to_commit_count": provisional_survived_to_commit,
        "observed_until_s": len(frames) * FRAME_S,
        "speech_frame_count": sum(flags),
    }


def assess_replay(
    *,
    name: str,
    kind: str,
    phase_offset_samples: int,
    ground_truth_end_s: float,
    replay: dict[str, Any],
) -> dict[str, Any]:
    commits = [float(value) for value in replay["commit_sample_clocks_s"]]
    assessment = acoustic_eval.assess_endpoint_commits(
        kind=kind,
        commit_sample_clocks_s=commits,
        final_speech_end_s=ground_truth_end_s,
        incomplete_hold_s=INCOMPLETE_SILENCE,
    )
    reasons = list(assessment["endpoint_invalid_reasons"])
    if int(replay["speech_frame_count"]) <= 0:
        reasons.append("no_speech_frames")
    if float(replay["observed_until_s"]) + 1e-9 < ground_truth_end_s + INCOMPLETE_SILENCE:
        reasons.append("observation_window_too_short")
    if len(commits) != 1:
        reasons.append("expected_exactly_one_eventual_commit")
    reasons = list(dict.fromkeys(reasons))
    valid = not reasons
    ep_s: float | None = None
    if valid and kind in {"complete", "pause_heavy"}:
        ep_s = commits[0] - ground_truth_end_s

    return {
        "name": name,
        "kind": kind,
        "phase_offset_samples": phase_offset_samples,
        "ground_truth_end_s": ground_truth_end_s,
        "commit_sample_clocks_s": commits,
        "endpoint_measurement_valid": valid,
        "endpoint_invalid_reasons": reasons,
        "premature_commit": bool(assessment["premature_commit"]),
        "multiple_commits": bool(assessment["multiple_commits"]),
        "incomplete_early": bool(assessment["incomplete_early"]),
        "ep_s": ep_s,
        "opportunities": replay["opportunities"],
        "provisional_trigger_sample_clocks_s": replay["provisional_trigger_sample_clocks_s"],
        "provisional_pre_commit_cancellation_count": replay[
            "provisional_pre_commit_cancellation_count"
        ],
        "provisional_commit_before_resume_contradiction_count": replay[
            "provisional_commit_before_resume_contradiction_count"
        ],
        "provisional_survived_to_commit_count": replay["provisional_survived_to_commit_count"],
    }


def serialize_case(case: dict[str, Any]) -> dict[str, Any]:
    result = dict(case)
    for key in ("ground_truth_end_s", "ep_s"):
        if result.get(key) is not None:
            result[key] = round(float(result[key]), 6)
    for key in (
        "commit_sample_clocks_s",
        "provisional_trigger_sample_clocks_s",
    ):
        result[key] = [round(float(value), 6) for value in result[key]]
    serialized_opportunities = []
    for item in result["opportunities"]:
        serialized = {
            **item,
            "silence_start_s": round(float(item["silence_start_s"]), 6),
            "completion_probability": round(float(item["completion_probability"]), 9),
        }
        for key in ("provisional_trigger_sample_clock_s", "commit_sample_clock_s"):
            if serialized[key] is not None:
                serialized[key] = round(float(serialized[key]), 6)
        serialized_opportunities.append(serialized)
    result["opportunities"] = serialized_opportunities
    return result


def summarize_cases(cases: list[dict[str, Any]]) -> dict[str, Any]:
    expected_cases = 13 * len(PHASE_OFFSETS)
    if len(cases) != expected_cases:
        raise RuntimeError(f"expected {expected_cases} replay cells, got {len(cases)}")
    valid_latency = [
        float(case["ep_s"])
        for case in cases
        if case["endpoint_measurement_valid"]
        and case["kind"] in {"complete", "pause_heavy"}
        and case["ep_s"] is not None
    ]
    expected_latency = 9 * len(PHASE_OFFSETS)
    semantic_valid = all(case["endpoint_measurement_valid"] for case in cases)
    ep50 = percentile(valid_latency, 0.50)
    ep90 = percentile(valid_latency, 0.90)
    latency_complete = len(valid_latency) == expected_latency
    latency_pass = bool(
        latency_complete and ep50 is not None and ep90 is not None and ep50 <= 0.5 and ep90 <= 1.0
    )
    return {
        "case_variant_count": len(cases),
        "valid_case_variant_count": sum(1 for case in cases if case["endpoint_measurement_valid"]),
        "valid_latency_count": len(valid_latency),
        "expected_latency_count": expected_latency,
        "valid_only_conditional_ep50_s": ep50,
        "valid_only_conditional_ep90_s": ep90,
        "latency_percentile_scope": (
            "diagnostic_survivor_subset_unless_latency_completeness_pass"
        ),
        "premature_case_variants": sum(1 for case in cases if case["premature_commit"]),
        "multiple_commit_case_variants": sum(1 for case in cases if case["multiple_commits"]),
        "incomplete_early_case_variants": sum(1 for case in cases if case["incomplete_early"]),
        "semantic_validity_pass": semantic_valid,
        "latency_completeness_pass": latency_complete,
        "latency_pass": latency_pass,
        "declared_grid_point_pass": semantic_valid and latency_pass,
        "provisional_trigger_count": sum(
            len(case["provisional_trigger_sample_clocks_s"]) for case in cases
        ),
        "provisional_pre_commit_cancellation_count": sum(
            int(case["provisional_pre_commit_cancellation_count"]) for case in cases
        ),
        "provisional_commit_before_resume_contradiction_count": sum(
            int(case["provisional_commit_before_resume_contradiction_count"])
            for case in cases
        ),
        "provisional_survived_to_commit_count": sum(
            int(case["provisional_survived_to_commit_count"]) for case in cases
        ),
    }


def verify_and_load_inputs() -> tuple[list[dict[str, Any]], dict[str, Any]]:
    manifest = acoustic_eval.verify_manifest(MANIFEST)
    corpus_document = json.loads(CORPUS.read_text(encoding="utf-8"))
    selected = [
        item
        for item in corpus_document["utterances"]
        if item["kind"] in {"complete", "incomplete", "pause_heavy"}
    ]
    counts = {
        kind: sum(1 for item in selected if item["kind"] == kind)
        for kind in ("complete", "incomplete", "pause_heavy")
    }
    if len(selected) != 13 or counts != {
        "complete": 6,
        "incomplete": 4,
        "pause_heavy": 3,
    }:
        raise RuntimeError(f"unexpected endpoint corpus composition: {counts}")
    locked = {str(item["path"]): str(item["sha256"]) for item in manifest["locked_files"]}
    for item in selected:
        path = PACK / str(item["file"])
        repo_path = str(path.relative_to(ROOT))
        actual = sha256(path)
        if actual != str(item["sha256"]) or actual != locked.get(repo_path):
            raise RuntimeError(f"fixture pin mismatch: {item['name']}")
    if sha256(V2_RESULTS) != V2_EXPECTED_SHA256:
        raise RuntimeError("corrected acoustic-v2 baseline pin mismatch")
    probe_vad = SileroVad(str(SILERO))
    probe_turn = TurnEndpointer(str(SMART_TURN))
    if not probe_vad.available or probe_turn.detail != "smart-turn-v3":
        raise RuntimeError("required endpoint models are unavailable")
    return sorted(selected, key=lambda item: str(item["name"])), manifest


def prepare_variants(selected: list[dict[str, Any]]) -> list[dict[str, Any]]:
    variants: list[dict[str, Any]] = []
    for item in selected:
        path = PACK / str(item["file"])
        source, source_rate = load_wav(path)
        samples = corpus_resample_to_16k(source, source_rate)
        for phase in PHASE_OFFSETS:
            frames = make_frames(samples, phase)
            flags = production_speech_flags(frames)
            variants.append(
                {
                    "name": str(item["name"]),
                    "kind": str(item["kind"]),
                    "phase_offset_samples": phase,
                    "ground_truth_end_s": float(item["speech_end_s"]) + phase / RATE,
                    "frames": frames,
                    "flags": flags,
                }
            )
    if len(variants) != 13 * len(PHASE_OFFSETS):
        raise RuntimeError("variant construction was incomplete")
    return variants


def run_policy(
    variants: list[dict[str, Any]],
    probability: SmartTurnProbability,
    *,
    confidence_threshold: float,
    complete_silence_s: float,
    force_short_timeout: bool = False,
    fixture_label_oracle: bool = False,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    cases: list[dict[str, Any]] = []
    for variant in variants:
        replay = replay_policy(
            frames=variant["frames"],
            flags=variant["flags"],
            probability=probability,
            confidence_threshold=confidence_threshold,
            complete_silence_s=complete_silence_s,
            force_short_timeout=force_short_timeout,
            force_long_timeout=(fixture_label_oracle and variant["kind"] == "incomplete"),
        )
        cases.append(
            assess_replay(
                name=variant["name"],
                kind=variant["kind"],
                phase_offset_samples=variant["phase_offset_samples"],
                ground_truth_end_s=variant["ground_truth_end_s"],
                replay=replay,
            )
        )
    return cases, summarize_cases(cases)


def baseline_parity(cases: list[dict[str, Any]]) -> dict[str, Any]:
    direct = [case for case in cases if case["phase_offset_samples"] == 0]
    defects = sorted(
        case["name"] for case in direct if case["premature_commit"] or case["incomplete_early"]
    )
    v2 = json.loads(V2_RESULTS.read_text(encoding="utf-8"))
    v2_cases = {
        str(case["name"]): case for case in v2["cases"] if case.get("family") == "endpointing"
    }
    direct_cases = {str(case["name"]): case for case in direct}
    expected_names = set(v2_cases)
    names_complete = set(direct_cases) == expected_names and len(expected_names) == 13
    tolerance_s = 0.060
    comparisons: dict[str, dict[str, Any]] = {}
    for name in sorted(expected_names | set(direct_cases)):
        direct_case = direct_cases.get(name)
        v2_case = v2_cases.get(name)
        if direct_case is None or v2_case is None:
            comparisons[name] = {"case_present_in_both": False, "case_parity_pass": False}
            continue
        exact_fields = {
            "kind": str(direct_case["kind"]) == str(v2_case["kind"]),
            "endpoint_measurement_valid": bool(direct_case["endpoint_measurement_valid"])
            == bool(v2_case["endpoint_measurement_valid"]),
            "endpoint_invalid_reasons": sorted(direct_case["endpoint_invalid_reasons"])
            == sorted(v2_case["endpoint_invalid_reasons"]),
            "premature_commit": bool(direct_case["premature_commit"])
            == bool(v2_case["premature_commit"]),
            "multiple_commits": bool(direct_case["multiple_commits"])
            == bool(v2_case["multiple_commits"]),
            "incomplete_early": bool(direct_case["incomplete_early"])
            == bool(v2_case["incomplete_early"]),
        }
        direct_clocks = [float(value) for value in direct_case["commit_sample_clocks_s"]]
        v2_clocks = [float(value) for value in v2_case["commit_sample_clocks_s"]]
        commit_count_exact = len(direct_clocks) == len(v2_clocks)
        # The direct replay and captured rig use different recording origins.
        # Compare each commit relative to its own pinned final-speech clock.
        direct_end = float(direct_case["ground_truth_end_s"])
        v2_end = float(v2_case["ground_truth_end_s"])
        direct_offsets = [clock - direct_end for clock in direct_clocks]
        v2_offsets = [clock - v2_end for clock in v2_clocks]
        clock_offset_deltas = (
            [
                abs(left - right)
                for left, right in zip(direct_offsets, v2_offsets, strict=True)
            ]
            if commit_count_exact
            else []
        )
        clock_offsets_within_tolerance = commit_count_exact and all(
            delta <= tolerance_s + 1e-9 for delta in clock_offset_deltas
        )
        direct_ep = direct_case.get("ep_s")
        v2_ep = v2_case.get("ep_s")
        ep_both_absent = direct_ep is None and v2_ep is None
        ep_applicable = str(direct_case["kind"]) in {"complete", "pause_heavy"}
        ep_delta = (
            abs(float(direct_ep) - float(v2_ep))
            if direct_ep is not None and v2_ep is not None
            else None
        )
        ep_within_tolerance = not ep_applicable or ep_both_absent or (
            ep_delta is not None and ep_delta <= tolerance_s + 1e-9
        )
        case_pass = (
            all(exact_fields.values())
            and clock_offsets_within_tolerance
            and ep_within_tolerance
        )
        comparisons[name] = {
            "case_present_in_both": True,
            "exact_field_matches": exact_fields,
            "commit_count_exact": commit_count_exact,
            "commit_offsets_from_final_speech_direct_s": direct_offsets,
            "commit_offsets_from_final_speech_v2_s": v2_offsets,
            "commit_offset_abs_deltas_s": clock_offset_deltas,
            "commit_offsets_within_tolerance": clock_offsets_within_tolerance,
            "endpoint_latency_applicable": ep_applicable,
            "endpoint_latency_abs_delta_s": ep_delta,
            "endpoint_latency_within_tolerance": ep_within_tolerance,
            "case_parity_pass": case_pass,
        }
    full_case_parity = names_complete and all(
        bool(item["case_parity_pass"]) for item in comparisons.values()
    )
    defect_pass = set(defects) == set(V2_EXPECTED_DEFECTS)
    return {
        "policy": {"confidence_threshold": 0.5, "complete_silence_s": 0.2},
        "phase_offset_samples": 0,
        "expected_v2_defect_cases": sorted(V2_EXPECTED_DEFECTS),
        "direct_replay_defect_cases": defects,
        "defect_set_exact_match": defect_pass,
        "case_names_complete": names_complete,
        "clock_and_latency_tolerance_s": tolerance_s,
        "per_case_comparison": comparisons,
        "all_13_case_signatures_counts_reasons_and_clocks_pass": full_case_parity,
        "parity_pass": defect_pass and full_case_parity,
    }


def environment_record(probability: SmartTurnProbability) -> dict[str, Any]:
    try:
        ort_module_version = str(import_module("onnxruntime").__version__)
    except (ModuleNotFoundError, AttributeError):
        ort_module_version = "unavailable"
    distributions: dict[str, str] = {}
    for distribution in ("onnxruntime", "onnxruntime-gpu"):
        try:
            distributions[distribution] = metadata.version(distribution)
        except metadata.PackageNotFoundError:
            continue
    return {
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "numpy": np.__version__,
        "onnxruntime_module": ort_module_version,
        "onnxruntime_distributions": distributions,
        "onnx_execution_providers": probability.providers(),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=HERE / "results.json")
    args = parser.parse_args()

    selected, manifest = verify_and_load_inputs()
    variants = prepare_variants(selected)
    probability = SmartTurnProbability()
    sweep: list[dict[str, Any]] = []
    baseline_cases: list[dict[str, Any]] | None = None
    for threshold in THRESHOLDS:
        for silence in COMPLETE_SILENCES:
            cases, summary = run_policy(
                variants,
                probability,
                confidence_threshold=threshold,
                complete_silence_s=silence,
            )
            row = {
                "confidence_threshold": threshold,
                "complete_silence_s": silence,
                **summary,
                "cases": [serialize_case(case) for case in cases],
            }
            sweep.append(row)
            if threshold == 0.5 and silence == 0.2:
                baseline_cases = cases
    if baseline_cases is None:
        raise RuntimeError("declared baseline was not evaluated")

    parity = baseline_parity(baseline_cases)
    passing = [row for row in sweep if row["declared_grid_point_pass"]]
    ranked = sorted(
        passing,
        key=lambda row: (
            float(row["valid_only_conditional_ep90_s"]),
            float(row["valid_only_conditional_ep50_s"]),
            -float(row["confidence_threshold"]),
            -float(row["complete_silence_s"]),
        ),
    )
    nomination = None
    if parity["parity_pass"] and ranked:
        nomination = {
            "confidence_threshold": ranked[0]["confidence_threshold"],
            "complete_silence_s": ranked[0]["complete_silence_s"],
            "status": "in_sample_nomination_requires_frozen_holdout",
        }

    timer_cases, timer_summary = run_policy(
        variants,
        probability,
        confidence_threshold=0.5,
        complete_silence_s=0.85,
        force_short_timeout=True,
    )
    stable_cases, stable_summary = run_policy(
        variants,
        probability,
        confidence_threshold=0.5,
        complete_silence_s=0.85,
    )
    oracle_cases, oracle_summary = run_policy(
        variants,
        probability,
        confidence_threshold=0.5,
        complete_silence_s=0.85,
        fixture_label_oracle=True,
    )

    report = {
        "schema": "parcel-endpoint-policy-sensitivity-2",
        "study_class": "exploratory_in_sample_sensitivity_not_promotion_evidence",
        "inputs": {
            "manifest_sha256": sha256(MANIFEST),
            "corpus_sha256": sha256(CORPUS),
            "silero_sha256": sha256(SILERO),
            "smart_turn_sha256": sha256(SMART_TURN),
            "corrected_v2_results_sha256": sha256(V2_RESULTS),
            "run_source_sha256": sha256(Path(__file__)),
            "endpointing_source_sha256": sha256(ENDPOINTING_SOURCE),
            "voice_loop_source_sha256": sha256(VOICE_LOOP_SOURCE),
            "corpus_builder_sha256": sha256(CORPUS_BUILDER),
            "locked_file_count": len(manifest["locked_files"]),
        },
        "environment": environment_record(probability),
        "declared_exploratory_grid": {
            "confidence_thresholds": list(THRESHOLDS),
            "complete_silence_s": list(COMPLETE_SILENCES),
            "phase_offset_samples": list(PHASE_OFFSETS),
            "incomplete_silence_s": INCOMPLETE_SILENCE,
            "grid_point_count": len(sweep),
            "case_variant_count_per_grid_point": len(variants),
        },
        "corpus_case_count": len(selected),
        "baseline_parity": parity,
        "declared_grid_pass_count": len(passing),
        "nomination": nomination,
        "nomination_status": (
            "no_declared_grid_point_passed"
            if not passing
            else (
                "blocked_by_direct_replay_vs_v2_parity"
                if not parity["parity_pass"]
                else "in_sample_only_requires_frozen_holdout"
            )
        ),
        "sweep": sweep,
        "two_stage_diagnostics": {
            "unconditional_timer_0_85_s": {
                **timer_summary,
                "cases": [serialize_case(case) for case in timer_cases],
            },
            "single_smartturn_0_5_then_0_85_s_silence_timeout": {
                **stable_summary,
                "cases": [serialize_case(case) for case in stable_cases],
            },
            "incomplete_fixture_label_oracle_diagnostic": {
                **oracle_summary,
                "cases": [serialize_case(case) for case in oracle_cases],
                "warning": (
                    "overrides only incomplete-fixture timeout; it is not an "
                    "opportunity-level or general endpointing oracle and cannot nominate a policy"
                ),
            },
        },
        "does_not_prove": [
            "generalization beyond the defect-discovery Piper fixtures",
            "PipeWire parity if the explicit parity gate is red",
            "human turn-taking or ASR transcript completeness",
            "room, noise, microphone, speaker, AEC, or network behavior",
            "a provisional-response implementation or cancellation path",
            "robot or mount readiness",
        ],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "baseline_parity": parity,
                "declared_grid_pass_count": len(passing),
                "nomination_status": report["nomination_status"],
                "nomination": nomination,
                "two_stage": {
                    "timer": timer_summary,
                    "single_smartturn_then_silence_timeout": stable_summary,
                    "incomplete_fixture_label_oracle": oracle_summary,
                },
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
