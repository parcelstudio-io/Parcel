#!/usr/bin/env python
"""The five policy arms, run in order, scored by one rule.

DESIGN v2: "Arms run SEQUENTIALLY with early stop; ONE consolidated pass rule —
an arm passes only if every row passes." The early stop is implemented, and this
run reports honestly whether it could ever fire: two rows of the consolidated
rule (AEC >= 20 dB through the XVF3800 -> CQRobot path, barge-in acoustic stop)
require a loudspeaker this host does not have, so no arm can be shown to pass
the whole rule here. That is a finding, not a failure of an arm, and the DESIGN's
own failure clause then selects push-to-talk for M1.
"""

from __future__ import annotations

import argparse
import platform
import subprocess
import time
from collections.abc import Callable
from pathlib import Path

import numpy as np

from .arena import AEC_SWEEP_DB, Arena
from .arena import build as build_arena
from .asr import WhisperClient
from .gate import (
    Admission,
    Arm,
    Decision,
    FakeTransport,
    GateConfig,
    Placement,
    Tape,
    push_to_talk_arm,
    restricted_listening_arm,
    run_gate,
    vad_only_arm,
)
from .identity import OwnerIdentity
from .rows import owner_quality, score
from .session import load_bed, load_manifest, speech_level_dbfs, write_result

ArmFactory = Callable[[Tape], Arm]

WAKE_TOKENS = ("hey parcel", "hey, parcel", "parcel")
#: Matched as PREFIXES, so "going" and "following" count. The row asks whether
#: the robot's own voice could be read as a motion instruction, and a stemmer's
#: opinion about inflection is not the safety property.
MOTION_STEMS = ("go", "walk", "follow", "come", "turn", "stop", "sit", "stay", "fetch", "move")


def wake_word_arm(client: WhisperClient) -> Arm:
    """Whisper on the gated window; the wake phrase must be in the first words."""

    def arm(window, _open_s: float, _placement: Placement | None) -> Decision:
        transcript = client.transcribe(window.astype(float) / 32768.0)
        text = transcript.normalized
        hit = any(token in text for token in WAKE_TOKENS)
        return Decision(
            admit=hit,
            reason="wake_phrase" if hit else "no_wake_phrase",
            detail=transcript.text,
        )

    return arm


def gesture_windows(tape: Tape, roles: tuple[str, ...]) -> list[tuple[float, float]]:
    """The owner's finger, or the camera's opinion, as an oracle interval list.

    Both push-to-talk and restricted listening are modeled with a PERFECT
    signal — the owner never fumbles the button and the presence detector never
    errs. Every number they produce is therefore an upper bound on the real arm.

    Windows are per TAPE: each tape has its own time axis, and an interval list
    built from one tape means nothing on another.
    """

    return [
        (placement.speech_start_s - 1.0, placement.speech_end_s + 1.0)
        for placement in tape.placements
        if placement.role in roles
    ]


#: Who is holding the button. Not the replay tape: a spoofer playing a recording
#: at the dog does not also have the owner's push-to-talk control, and the
#: RESULTS state that assumption where the replay row is read.
PTT_ROLES = ("owner", "stop", "wake")

#: When a person is in the room at all. The television tape is the "nobody home,
#: TV left on" case on purpose; with a person present the restricted arm
#: degenerates to VAD-only, which is arm (a)'s row.
PRESENCE_ROLES = ("owner", "owner_replay", "second_person", "stop", "wake")


def run_over(arena: Arena, make_arm: ArmFactory, config: GateConfig) -> dict:
    out: dict[str, tuple[list[Admission], FakeTransport, Tape]] = {}
    for name, tape in arena.named().items():
        admissions, transport = run_gate(tape, make_arm(tape), config=config)
        out[name] = (admissions, transport, tape)
    return out


def score_stats(admissions: list[Admission]) -> dict:
    values = [admission.score for admission in admissions if admission.score is not None]
    if not values:
        return {}
    array = np.asarray(values, dtype=float)
    return {
        "n": int(array.size),
        "p5": float(np.percentile(array, 5)),
        "p50": float(np.percentile(array, 50)),
        "p95": float(np.percentile(array, 95)),
        "min": float(array.min()),
        "max": float(array.max()),
    }


def summarize(name: str, runs: dict, client: WhisperClient) -> dict:
    owner_admissions, owner_transport, owner_tape = runs["owner"]
    replay_admissions, replay_transport, replay_tape = runs["owner_replay"]
    second_admissions, second_transport, second_tape = runs["second_person"]
    tv_admissions, tv_transport, tv_tape = runs["tv"]
    self_admissions, self_transport, self_tape = runs["self_tts"]
    fan_admissions, fan_transport, fan_tape = runs["fan"]
    wake_admissions, wake_transport, wake_tape = runs["wake"]

    self_by_level: dict[str, dict] = {}
    for attenuation in AEC_SWEEP_DB:
        suffix = f"_aec{int(-attenuation)}"
        targets = [p for p in self_tape.placements if p.name.endswith(suffix)]
        admitted = 0
        transcribed_motion = 0
        for placement in targets:
            span = next(
                (
                    admission
                    for admission in self_admissions
                    if admission.admitted
                    and admission.open_s <= placement.speech_end_s
                    and admission.close_s >= placement.speech_start_s
                ),
                None,
            )
            if span is None:
                continue
            admitted += 1
            start = int(span.upload_from_s * 16_000)
            end = int(span.close_s * 16_000)
            transcript = client.transcribe(self_tape.samples[start:end].astype(float) / 32768.0)
            if any(word.startswith(MOTION_STEMS) for word in transcript.words()):
                transcribed_motion += 1
        self_by_level[f"{attenuation:g}dB"] = {
            "trials": len(targets),
            "admitted": admitted,
            "self_transcribed_motion_commands": transcribed_motion,
        }

    return {
        "arm": name,
        "owner": score(owner_tape, owner_admissions, owner_transport, "owner"),
        "owner_quality": owner_quality(owner_tape, owner_admissions),
        "wake_quality": owner_quality(wake_tape, wake_admissions, roles=("wake",)),
        "owner_replay": score(replay_tape, replay_admissions, replay_transport, "owner_replay"),
        "second_person": score(
            second_tape, second_admissions, second_transport, "second_person"
        ),
        "tv": score(tv_tape, tv_admissions, tv_transport, "tv"),
        "self_tts": score(self_tape, self_admissions, self_transport, "self_tts"),
        "self_tts_by_aec_level": self_by_level,
        "fan": score(fan_tape, fan_admissions, fan_transport, "wind"),
        # Arm (c)'s own recall denominator: the owner turns that CONTAIN the wake
        # phrase. The owner tape is real human speech with no "hey Parcel" in it,
        # so arm (c) scored against it measures nothing but that absence.
        "wake_turns": score(wake_tape, wake_admissions, wake_transport, "wake"),
        "identity_scores": {
            tape_name: score_stats(admissions)
            for tape_name, (admissions, _transport, _tape) in runs.items()
        },
        "hosted_bytes_non_owner": (
            tv_transport.uploaded_bytes
            + second_transport.uploaded_bytes
            + self_transport.uploaded_bytes
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--scratch", type=Path, required=True)
    parser.add_argument("--tape", type=Path, required=True)
    parser.add_argument(
        "--arms",
        default="vad_only,owner_id,owner_id_calibrated,wake_phrase,push_to_talk,restricted",
    )
    parser.add_argument(
        "--calibrated-threshold",
        type=float,
        default=0.352,
        help="from results/identity_roc.json: the threshold at which owner recall reaches "
        "0.95 with a 2.0 s window and a channel-matched gallery",
    )
    parser.add_argument("--calibrated-window-s", type=float, default=2.0)
    args = parser.parse_args()

    manifest = load_manifest()
    bed = load_bed(args.tape)
    speech_dbfs = speech_level_dbfs(bed)
    started = time.time()
    arena = build_arena(manifest, bed, speech_dbfs)
    config = GateConfig()
    client = WhisperClient()
    if not client.available():
        raise SystemExit("whisper-server is not answering on 127.0.0.1:8099")

    identity = OwnerIdentity(args.scratch / "gallery" / "research_owner_voice.json")
    calibrated = OwnerIdentity(
        args.scratch / "gallery_matched" / "research_owner_voice.json",
        threshold=args.calibrated_threshold,
    )
    wake = wake_word_arm(client)
    wide = GateConfig(decision_window_s=args.calibrated_window_s)
    builders: dict[str, tuple[ArmFactory, GateConfig]] = {
        "vad_only": (lambda _tape: vad_only_arm, config),
        "owner_id": (lambda _tape: identity.arm, config),
        "owner_id_calibrated": (lambda _tape: calibrated.arm, wide),
        "wake_phrase": (lambda _tape: wake, config),
        "push_to_talk": (lambda tape: push_to_talk_arm(gesture_windows(tape, PTT_ROLES)), config),
        "restricted": (
            lambda tape: restricted_listening_arm(gesture_windows(tape, PRESENCE_ROLES)),
            config,
        ),
    }

    summaries = []
    for name in args.arms.split(","):
        arm_started = time.time()
        factory, arm_config = builders[name]
        runs = run_over(arena, factory, arm_config)
        summary = summarize(name, runs, client)
        summary["wall_s"] = time.time() - arm_started
        summaries.append(summary)
        print(
            f"{name:14s} owner {summary['owner']['acceptance_rate']:.3f}  "
            f"second {summary['second_person']['acceptance_rate']:.3f}  "
            f"tv opens/h {summary['tv']['opens_per_hour']:.1f}  "
            f"non-owner hosted bytes {summary['hosted_bytes_non_owner']}  "
            f"({summary['wall_s']:.0f}s)"
        )

    payload = {
        "tier": "replay",
        "tier_note": (
            "no stimulus was presented through air: this host has no loudspeaker but the "
            "array's own DAC, and playing a stimulus through it would hand the XVF3800's "
            "AEC its own reference. The room floor under every tape is real."
        ),
        "host": platform.node(),
        "git_head": subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, check=False
        ).stdout.strip(),
        "hosted_usd": 0.0,
        "room_floor_dbfs": bed.floor_dbfs,
        "speech_level_dbfs_at_1m": speech_dbfs,
        "gate_config": vars(config),
        "calibrated_arm": {
            "threshold": args.calibrated_threshold,
            "decision_window_s": args.calibrated_window_s,
            "gallery": "channel_matched",
            "caveat": (
                "the threshold is read off identity_roc.json, which fitted it on the SAME "
                "36 owner trials scored here; the calibrated arm's recall is an upper bound"
            ),
        },
        "tape_seconds": {name: tape.seconds for name, tape in arena.named().items()},
        "tape_placements": {
            name: len(tape.placements) for name, tape in arena.named().items()
        },
        "whisper_calls": client.calls,
        "whisper_mean_latency_s": client.total_latency_s / max(1, client.calls),
        "wall_s": time.time() - started,
        "arms": summaries,
    }
    path = write_result("arms.json", payload)
    print(f"-> {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
