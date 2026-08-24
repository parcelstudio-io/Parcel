"""CLI for the DUPLEX_V1 headless duplex dual-stream eval (D0).

Scripted text turns exercise TTFT, filler policy, ACT continuity, barge-in
atomicity, and shadow decode round-trips. Navigation suites are a regression
gate: follow-bench + embodied ledger rows must match the 2026-08-04
post-speed-raise freeze.

Usage:
    .parcel/bin/python -m evals.companion.duplex_v1.run_duplex_v1 \
        --out evals/companion/duplex_v1/results
"""

from __future__ import annotations

import argparse
import itertools
import json
import re
import statistics
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from parcel_robot.duplex.config import DuplexConfig
from parcel_robot.duplex.coordinator import DuplexCoordinator
from parcel_robot.duplex.fillers import FillerPool
from parcel_robot.providers import SentenceChunkedSynthesizer
from parcel_robot.voice.pipeline import DuplexVoiceSession, VoiceStage

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_RESULTS_DIR = Path(__file__).resolve().parent / "results"

# Follow-bench ledger row the duplex nav-regression gate mirrors (shipped
# features). RE-PINNED 2026-08-09 (card pedestrian-evidence-refresh): a fresh
# run on the current tree — after the F-1 near-band inset, the surface-anchored
# next_to band, and the yield policy — flipped follow_success 8/9 -> 9/9 with
# hard collisions still 0 and navigate still 2/2, and jerk essentially unchanged
# (0.553 -> 0.6025 m/s^3). The stale 2026-08-04 row (…104134Z, the earlier
# lane's 8/9) is retained in the append-only ledger; this pin now tracks the
# fresh 9/9 latest-shipped row, resolving the 8/9-vs-live-9/9 mismatch honestly.
#
# RE-PINNED AGAIN 2026-08-10 (lane E5, EXPLICIT OWNER AUTHORIZATION — "1. person
# clearance. Implement your recommendation"): **9/9 -> 6/9**. This is a real
# capability regression and it is pinned as one, not smoothed over.
#
# What moved and what did not:
#   * hard_collision_total 0 and navigate_success 2/2 are UNCHANGED. The gate's
#     actual safety invariants did not move.
#   * min_pedestrian_surface_m 0.3566 -> 0.5300 m (+0.17) and
#     personal_space_time_total_s 3.8 -> 2.3 s. Pedestrian safety IMPROVED.
#   * follow_success 9/9 -> 6/9 (pedestrian_group, pedestrian_cut_in,
#     owner_turn_90 fall out of the [1.2, 3.0] m band by falling BEHIND).
#
# Measured factorial attribution over the four retuned quantities (all cells on
# this tree, FOLLOW_BENCH_V1 all 11 scenarios — see
# scrum/20260809/task_15/E5_PERSON_CLEARANCE_STATUS.md):
#   safety.person_slow_m 2.0 -> 2.5      : 9/9 -> 6/9   AND 0.3566 -> 0.5300 m
#   safety.person_stop_m 1.0 -> 1.2      : 9/9 -> 9/9   (costs nothing)
#   owner_follow.owner_keepout_m -> 1.75 : 9/9 -> 9/9   (costs nothing)
#   FollowConfig.desired_distance_m 1.85 : 9/9 -> 9/9   (costs nothing)
# The benefit and the cost are the SAME knob. Raising the follow distance
# further does NOT buy the rows back (2.2 m -> 6/9, 2.6 m -> 5/9), which refutes
# the "follow target inside its own keepout" diagnosis for this loss.
# Mechanism, proven by owner_turn_90 (which has NO pedestrians at all and still
# drops 0.821 -> 0.500): apply_reactive_safety applies ONE comfort band to both
# strangers and the OWNER, so widening it to 2.5 m throttles the follow
# controller at every distance it operates at. The follow-up card is to give the
# owner branch its own band; that is a change to the gate function itself and
# was NOT in this card's authorization.
#
# RE-PINNED AGAIN 2026-08-11 (lane E6, EXPLICIT OWNER AUTHORIZATION for exactly
# that follow-up card): **6/9 -> 7/9**, a partial recovery, pinned as partial.
#
# The change: apply_reactive_safety now gives a positively-identified owner its
# own comfort band, derived as person_stop_m + OWNER_STAND_OFF_MARGIN_M = 1.30 m
# of clearance = the follow controller's own 1.85 m stand-off expressed in the
# gate's coordinates. It is granted only while no stranger is on the person
# channel; anything else FAILS CLOSED to the 2.5 m stranger band. The owner's
# hard stop, the predictive stop, TTC and the collision gate are untouched.
#
# What moved and what did not (2x2 attribution: old-code = this tree at E5,
# new-code = that tree plus E6; both measured today on all 11 scenarios):
#   * follow_success 6/9 -> 7/9. The single recovered episode is owner_turn_90
#     (band_fraction 0.500 -> 0.953), which is precisely the episode E5 proved
#     was owner-only: it contains ZERO pedestrians.
#   * min_pedestrian_surface_m 0.5300 and personal_space_time_total_s 2.3 are
#     UNCHANGED — not "within noise", unchanged. Every episode containing a
#     pedestrian re-measures bit-identical to E5 (pedestrian_group 0.584,
#     pedestrian_cut_in 0.525, pedestrian_cut_in_predictive 0.7154 /
#     0.818256373512604, navigate_crossing_ped 0.5300 / 2.3 s), because the
#     two-body interlock makes the gate provably the same function whenever a
#     stranger is perceived.
#   * hard_collision_total 0, pedestrian_contact_total 0, intimate 0.0,
#     navigate_success 2/2, reactive_gate_stop_total 2: all unchanged.
#   * mean_band_fraction 0.63986 -> 0.70878; mean_rms_commanded_jerk_mps3
#     0.8918 -> 1.2187 (the dog now accelerates to hold formation instead of
#     being throttled into it; not gated, reported).
#
# 9/9 was NOT reached and is NOT reachable through the owner band. Measured
# sweep of the owner band with the interlock OFF (most favourable case for
# following), all on this tree:
#   owner band 2.50 (= no separation) : 6/9  min_ped 0.5300
#   owner band 2.00                   : 7/9  min_ped 0.3824
#   owner band 1.75                   : 8/9  min_ped 0.2182
#   owner band 1.30 (the derivation)  : 8/9  min_ped 0.1794
# pedestrian_group fails in EVERY cell (0.584 / 0.636 / 0.652 / 0.652 against a
# 0.75 threshold): it is not an owner-band episode at all. The remaining two
# failures are the STRANGER band's cost, i.e. the pedestrian-clearance knob E5
# bought the +0.17 m with, and buying them back means selling that clearance.
# Full factorial: scrum/20260809/task_15/E6_OWNER_BAND_STATUS.md.
# Card J-C (2026-08-11): the comfort number joins this mirror, WITH its
# attribution, because leaving it out was how a 58% drift stayed unexplained
# through two lanes. It is re-pinned, not "fixed": the whole movement is three
# deliberate, committed decisions.
#
#   0.6025 (be20471)
#     +0.09  terminal-approach floor  — 60ecea2 grid_navigator.py
#            TERMINAL_APPROACH_FLOOR_MPS=0.12 (owner pacing seam; single-hunk
#            revert restores navigate_near_wall to exactly 1.1401). A ~+0.29
#            residual on navigate_crossing_ped is attributed BY ELIMINATION to
#            the same commit's pipeline.py scan-creep seam and is not
#            single-hunk isolated.
#     +0.23  instant-zero            — 6bd945d card P0-A: emergency stops went
#            from an accel-limited ramp to exact (0,0,0). Reverting only that
#            hunk returns the mean to exactly 0.7212, the 60ecea2 value. P0-A
#            is the verdict-ranked hard-stop contract and stays.
#     +0.33  E6 dynamics x instant-zero — 0.8918 -> 1.2187. E6's own
#            band-edge-transition explanation is REFUTED by trace: the owner
#            band is granted 200/200 and 180/180 ticks and owner centre
#            distance stays 2.00-2.18 m, never inside the 0.10 m ramp. 96.7% /
#            96.3% of summed squared jerk sits on emergency-ADJACENT ticks,
#            where the runtime routes ANY zero intent through the same
#            emergency bypass as a safety stop.
#   = 1.2187 (dd2e857), the value pinned below and ratcheted at 1.20x by
#   scripts/ci_gate.py's follow-bench-jerk-ratchet against
#   evals/companion_nav/results/jerk_baseline.json.
#
# Card J-B landed a severity split (nominal zero intents may ramp; emergency
# stops keep the instant zero) behind motion.shaping.nominal_stop_ramp, DEFAULT
# OFF, so this number is unchanged. Measured flag-ON: 1.0813 — below the
# flag-off value but ABOVE the pre-registered 1.05 bar, so the default flip is
# STOP-and-report and stays an owner decision (FOLLOWUP_DESIGNS.md §8 q1).
# If it is ever flipped, this pin and the baseline move DOWN, with a 2x2.
FOLLOW_BENCH_POST_SPEED = {
    "features": "shipped",
    "follow_success": "7/9",
    "hard_collision_total": 0,
    "navigate_success": "2/2",
    "mean_rms_commanded_jerk_mps3": 1.2187,
    "report": "follow-bench-v1-20260811023618Z-93eba090.json",
}

# Embodied-plan aggregate mirror (authority:
# tests/test_embodied_plan_eval.py::test_full_gate_executes_physics...).
# 1146 -> 1072 on 2026-08-06, then 1072 -> 1250 on 2026-08-07 (region-instance
# selection: complete the look-around before choosing among interchangeable
# instances — see tests/test_embodied_plan_eval.py provenance), in lockstep
# with that suite's honest re-freezes:
# -35 from configs/navigation/default.yaml safety.max_vx 0.45 -> 0.9 and -37
# from the K0 shared-GoalRegion arrival trigger in navigation/pipeline.py
# (measured 2x2 attribution; see the provenance block in the test).
# 1250 -> 1219 on 2026-08-09 (Wave-2, near-band-inset: the lamppost `near` pose
# insets to the band centre) then 1219 -> 997 (Wave-2, seamless-pacing: region
# "inside" convergence + terminal creep floor). All five cases still pass; the
# two invariants this gate actually guards — zero collisions and a 1.0
# supported-case success rate — are unchanged, which is why this stays a pacing
# re-freeze and not a nav regression. _embodied_suite_freeze_agrees() keeps
# the mirror and the suite from drifting apart silently.
EMBODIED_POST_SPEED = {
    "simulator_step_count": 997,
    "collision_count": 0,
    "supported_case_success_rate": 1.0,
}

DOES_NOT_PROVE = (
    "live audio / acoustic barge-in (turns are text-injected; no mic or speaker)",
    "D0 frames derive from executed behavior rather than driving it — that flips in D1",
    "real planner / model TTFT on production weights (slow path is injected)",
    "navigation quality from this script alone (nav is a ledger regression gate)",
)


class _ScriptedAgent:
    """Deterministic agent with configurable per-turn latency + reply."""

    def __init__(self, replies: dict[str, tuple[float, str]]) -> None:
        self._replies = replies
        self.calls: list[str] = []

    def handle_text(self, text: str) -> str:
        self.calls.append(text)
        delay_s, reply = self._replies.get(text, (0.02, f"echo:{text}"))
        if delay_s > 0:
            time.sleep(delay_s)
        return reply


class _InstantSynth:
    def synthesize(self, text: str) -> bytes:
        # Minimal non-empty payload so the voice session treats synthesis as success.
        return b"RIFF" + str(text).encode("utf-8")[:64]


def _latency_row_from_stages(stages: list[VoiceStage]) -> dict[str, object] | None:
    """Replay real ``VoiceStage`` clocks into a ``LatencyTracker`` ledger row.

    Why this exists (card C-A debt, Fable's independent task_15 audit):
    ``evals/latency/ledger.jsonl`` held exactly one hand-seeded row for its whole
    life, because the only writer was ``RobotRuntime.close()`` behind a
    ``PARCEL_LATENCY_LEDGER`` env nothing in the repo ever set. ci_gate's
    ``latency-tail-ledger`` ratchet was therefore permanently ``skip`` — a gate
    that could not fire. The duplex eval already drives a real
    ``DuplexVoiceSession`` and already collects its stage clocks to compute TTFT;
    turning those same clocks into a ledger row costs no new measurement and
    makes rows accumulate from every duplex run.

    The timestamps are the session's own ``time.monotonic()`` marks, not
    re-derived. Stage names outside the tracker vocabulary are dropped rather
    than mapped onto a near-neighbour.
    """

    from parcel_robot.observability import STAGES, LatencyTracker, latency_ledger_row

    by_turn: dict[int, list[VoiceStage]] = {}
    for stage in stages:
        by_turn.setdefault(int(stage.turn_id), []).append(stage)
    if not by_turn:
        return None

    tracker = LatencyTracker()
    for turn_id, turn_stages in sorted(by_turn.items()):
        ordered = sorted(turn_stages, key=lambda item: float(item.timestamp))
        anchor = next((s for s in ordered if s.name == "query_end"), ordered[0])
        transcript = str(getattr(anchor, "transcript", "") or f"duplex turn {turn_id}")
        tracker.start(turn_id, transcript, source="text", now=float(anchor.timestamp))
        for stage in ordered:
            if stage.name in STAGES:
                tracker.mark(turn_id, stage.name, now=float(stage.timestamp))
        last = ordered[-1]
        reply = next(
            (str(s.reply) for s in reversed(ordered) if getattr(s, "reply", None)),
            "",
        )
        tracker.finish(
            turn_id,
            reply or "(no reply text recorded)",
            reasoning_source="duplex-v1-scripted",
            status="completed",
            now=float(last.timestamp),
        )
    return latency_ledger_row(
        tracker.snapshot(),
        source="duplex-v1",
        extra={
            "seed": False,
            "note": (
                "Live DuplexVoiceSession stage clocks from the duplex-v1 scripted "
                "session. The text path has no microphone, endpointer or audio "
                "sink, so the N19 acoustic spans (AcousticAck, EndpointDecision, "
                "SttTranscribe, PlaybackEnqueueToFirstSample) are ABSENT by "
                "omission, not zero. A sub-700 ms acoustic ack still needs a real "
                "capture/playback run."
            ),
        },
    )


def _emit_latency_ledger_row(stages: list[VoiceStage]) -> str | None:
    """Append the duplex latency row to the resolved ledger; return its path."""

    from parcel_robot.observability import (
        append_latency_ledger_row,
        resolve_latency_ledger_path,
    )

    row = _latency_row_from_stages(stages)
    if row is None:
        return None
    target = resolve_latency_ledger_path()
    if target is None:
        return None
    written = append_latency_ledger_row(row, target)
    return None if written is None else str(written)


def _measure_ttft_via_voice_pipeline(
    collected_stages: list[VoiceStage] | None = None,
) -> list[float]:
    """Measure query_end → tts_first_chunk on a real DuplexVoiceSession path."""

    agent = _ScriptedAgent(
        {
            "fast please": (0.03, "Sure thing."),
            "another fast": (0.04, "On it."),
        }
    )
    stages: list[VoiceStage] = []
    synth = SentenceChunkedSynthesizer(_InstantSynth(), max_chars=220)
    played: list[bytes] = []

    with DuplexVoiceSession(
        agent,
        synthesizer=synth,
        audio_chunk_player=played.append,
        on_stage=stages.append,
    ) as session:
        for transcript in ("fast please", "another fast"):
            session.submit_text(transcript)
            assert session.wait_until_idle(3.0)

    ttfts: list[float] = []
    by_turn: dict[int, dict[str, float]] = {}
    for stage in stages:
        row = by_turn.setdefault(stage.turn_id, {})
        if stage.name == "query_end":
            row["query_end"] = stage.timestamp
        elif stage.name == "tts_first_chunk" and "ttft" not in row:
            query_end = row.get("query_end")
            if query_end is not None:
                row["ttft"] = stage.timestamp - query_end
                ttfts.append(row["ttft"])
    assert ttfts, "voice-pipeline TTFT measurement produced no samples"
    assert played, "synthesizer path never enqueued audio"
    if collected_stages is not None:
        collected_stages.extend(stages)
    return ttfts


def _producer_continuity_session(duplex: DuplexCoordinator) -> int:
    """Faithful control-loop replica: 10 Hz ticks with ACT/TEXT pushes."""

    duplex.set_epoch(100)
    missing_before = int(duplex.snapshot()["missing_frames"])
    t0 = 1000.0
    for i in range(200):
        now = t0 + i * 0.1
        if i % 7 == 0:
            duplex.push_twist(0.4, 0.0, epoch=100)
        if i % 11 == 0:
            duplex.push_gaze_owner(epoch=100)
        if i % 13 == 0:
            duplex.push_skill("NavigateTo", epoch=100)
        if i % 17 == 0:
            duplex.push_text_tokens(f"word{i}", epoch=100)
        frame = duplex.tick(now_s=now, context={"tick": i})
        assert frame is not None
        assert frame.t == i or frame.t >= 0
    missing_after = int(duplex.snapshot()["missing_frames"])
    return missing_after - missing_before


def _scripted_session() -> dict[str, object]:
    """Run scripted duplex turns against coordinator + voice-pipeline timing."""

    config = DuplexConfig(
        enabled=True,
        filler_watchdog_s=0.7,
        response_ceiling_s=2.0,
        logging=False,
        rng_seed=7,
    )
    duplex = DuplexCoordinator(
        config,
        skills=("NavigateTo",),
        emotes=("bow",),
    )
    frames: list[dict[str, object]] = []
    filler_latencies: list[float] = []
    fillers_used: list[str] = []

    # --- Measured TTFT from the local voice pipeline (not hardcoded) ---
    voice_stages: list[VoiceStage] = []
    ttfts = _measure_ttft_via_voice_pipeline(voice_stages)

    # --- Fast-answer turn on the coordinator (TEXT observe + ACT) ---
    duplex.set_epoch(1)
    duplex.on_turn_start(now_s=0.0)
    # Simulate TTS-queue arrival (not reasoning_response alone).
    duplex.on_first_token(now_s=ttfts[0] if ttfts else 0.12)
    duplex.push_text_tokens("Sure thing.", epoch=1)
    duplex.push_emote("bow", epoch=1)
    for i in range(5):
        frame = duplex.tick(now_s=0.2 + i * 0.1)
        assert frame is not None
        frames.append(
            {"t": frame.t, "epoch": frame.epoch, "text": frame.text, "act": frame.act}
        )

    # --- Slow-answer turn: predictive filler < 1 s, then clause-boundary reply ---
    duplex.set_epoch(2)
    duplex.on_turn_start(now_s=10.0)
    fire = duplex.predictive_filler(reason="predictive", now_s=10.05)
    assert fire is not None
    duplex.on_filler_audible(now_s=10.08)
    assert duplex.filler.filler_latency_s is not None
    filler_latencies.append(float(duplex.filler.filler_latency_s))
    fillers_used.append(fire.entry.text)
    duplex.push_filler_act(index=0, epoch=2)
    duplex.tick(now_s=10.1)
    duplex.filler.note_clause_boundary_pending("Here is the plan.")
    pending = duplex.filler.take_pending_reply()
    assert pending == "Here is the plan."
    duplex.on_first_token(now_s=11.0)
    duplex.push_text_tokens(pending, epoch=2)
    duplex.push_skill("NavigateTo", epoch=2)
    for i in range(5):
        frame = duplex.tick(now_s=11.0 + i * 0.1)
        assert frame is not None
        frames.append(
            {"t": frame.t, "epoch": frame.epoch, "text": frame.text, "act": frame.act}
        )

    # --- Repeated slow turns: filler variation (no consecutive repeats) ---
    for turn_i in range(3):
        epoch = 3 + turn_i
        duplex.set_epoch(epoch)
        t0 = 20.0 + turn_i * 5.0
        duplex.on_turn_start(now_s=t0)
        fire = duplex.predictive_filler(reason="predictive", now_s=t0 + 0.05)
        assert fire is not None
        fillers_used.append(fire.entry.text)
        duplex.on_filler_audible(now_s=t0 + 0.1)
        assert duplex.filler.filler_latency_s is not None
        filler_latencies.append(float(duplex.filler.filler_latency_s))
        duplex.on_first_token(now_s=t0 + 1.2)
        duplex.push_text_tokens(f"Answer {turn_i}", epoch=epoch)
        duplex.tick(now_s=t0 + 1.3)

    consecutive_repeats = sum(1 for a, b in itertools.pairwise(fillers_used) if a == b)

    # --- Barge-in mid-reply: epoch cliff, no post-epoch content ---
    duplex.set_epoch(10)
    duplex.on_turn_start(now_s=40.0)
    duplex.push_text_tokens("Long answer that will be cut", epoch=10)
    duplex.push_twist(0.4, 0.0, epoch=10)
    before = duplex.tick(now_s=40.0)
    assert before is not None
    frames.append(
        {"t": before.t, "epoch": before.epoch, "text": before.text, "act": before.act}
    )
    duplex.set_epoch(11)  # barge-in
    duplex.push_text_tokens("stale", epoch=10)  # must not appear
    after = duplex.tick(now_s=40.1)
    assert after is not None
    frames.append(
        {"t": after.t, "epoch": after.epoch, "text": after.text, "act": after.act}
    )
    atomicity_ok = after.epoch == 11 and after.text != "stale"

    # --- Continuity via coordinator producer ticks (not bare interleaver) ---
    continuity_missing = _producer_continuity_session(duplex)

    # --- Shadow decode round-trip ---
    token = duplex.codec.encode_twist(0.4, 0.0)
    command = duplex.codec.decode(token)
    shadow_ok = duplex.consumer.shadow_matches(token, vx=0.4, vyaw=0.0)
    shadow_ok = shadow_ok and command.kind == "twist"
    gaze_token = duplex.codec.encode_gaze_owner()
    shadow_ok = shadow_ok and duplex.codec.decode(gaze_token).kind == "gaze"

    # --- Watchdog path: LLM-fast / TTS-stalled still fires ---
    duplex.set_epoch(20)
    duplex.on_turn_start(now_s=50.0)
    # Deliberately do NOT call on_first_token (simulates stalled TTS despite text).
    watchdog = duplex.poll_watchdog(now_s=50.75)
    assert watchdog is not None and watchdog.reason == "watchdog"
    duplex.on_filler_audible(now_s=50.8)
    assert duplex.filler.filler_latency_s is not None
    filler_latencies.append(float(duplex.filler.filler_latency_s))

    # --- Ceiling breach counter stays zero when filler audible ---
    duplex.set_epoch(21)
    duplex.on_turn_start(now_s=60.0)
    duplex.predictive_filler(now_s=60.1)
    duplex.on_filler_audible(now_s=60.2)
    breached = duplex.filler.poll_ceiling_breach(now_s=62.5)
    assert breached is False

    # --- Per-turn outcome write ---
    duplex.record_turn_outcome(
        {
            "turn_id": 1,
            "ttft_s": ttfts[0] if ttfts else None,
            "filler_used": None,
            "barge_in": False,
        }
    )

    ttft_p50 = statistics.median(ttfts) if ttfts else float("inf")
    return {
        "ttft_p50_s": ttft_p50,
        "ttft_samples_s": ttfts,
        "ttft_source": "DuplexVoiceSession query_end→tts_first_chunk",
        "filler_latencies_s": filler_latencies,
        "filler_audible_max_s": max(filler_latencies) if filler_latencies else None,
        "filler_consecutive_repeats": consecutive_repeats,
        "fillers_used": fillers_used,
        "continuity_missing_frames": continuity_missing,
        "continuity_source": "DuplexCoordinator 10Hz ticks with ACT/TEXT pushes",
        "atomicity_ok": atomicity_ok,
        "shadow_round_trip_ok": shadow_ok,
        "response_ceiling_breaches": duplex.filler.response_ceiling_breaches,
        "frames_sample": frames[-12:],
        "frames_emitted": duplex.snapshot()["frames_emitted"],
        "latency_ledger_row": _emit_latency_ledger_row(voice_stages),
    }


def _embodied_suite_freeze_agrees() -> bool:
    """Cross-check this pin against the embodied suite freeze assertion."""

    text = (REPO_ROOT / "tests" / "test_embodied_plan_eval.py").read_text(encoding="utf-8")
    # Match the current frozen aggregate pin in test_full_gate_... The literal
    # is read from EMBODIED_POST_SPEED so the mirror cannot be updated without
    # the suite agreeing (2026-08-06: 1146 -> 1072).
    step_ok = bool(
        re.search(
            rf'"simulator_step_count":\s*{EMBODIED_POST_SPEED["simulator_step_count"]}\b',
            text,
        )
    )
    collision_ok = bool(re.search(r'"collision_count":\s*0', text))
    rate_ok = bool(re.search(r'"supported_case_success_rate":\s*1\.0', text))
    return step_ok and collision_ok and rate_ok


def _nav_regression_gate() -> dict[str, object]:
    """Confirm frozen ledger rows match the post-speed-raise values."""

    follow_ledger = REPO_ROOT / "evals/companion_nav/results/ledger.jsonl"
    rows = [
        json.loads(line)
        for line in follow_ledger.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    shipped = [row for row in rows if row.get("features") == "shipped"]
    assert shipped, "missing shipped follow-bench ledger row"
    latest = shipped[-1]
    follow_ok = (
        latest.get("follow_success") == FOLLOW_BENCH_POST_SPEED["follow_success"]
        and latest.get("hard_collision_total") == FOLLOW_BENCH_POST_SPEED["hard_collision_total"]
        and latest.get("navigate_success") == FOLLOW_BENCH_POST_SPEED["navigate_success"]
    )
    embodied_pin_ok = (
        # 1146 -> 1072 (2026-08-06) -> 1250 (2026-08-07 region-instance
        # selection) -> 1219 -> 997 (2026-08-09 Wave-2 near-band-inset +
        # seamless-pacing); the two invariants below are what this gate guards
        # and neither moved (zero collisions, 1.0 supported success rate).
        EMBODIED_POST_SPEED["simulator_step_count"] == 997
        and EMBODIED_POST_SPEED["collision_count"] == 0
        and EMBODIED_POST_SPEED["supported_case_success_rate"] == 1.0
        and _embodied_suite_freeze_agrees()
    )
    embodied_gate = {
        "simulator_step_count": EMBODIED_POST_SPEED["simulator_step_count"],
        "collision_count": EMBODIED_POST_SPEED["collision_count"],
        "supported_case_success_rate": EMBODIED_POST_SPEED["supported_case_success_rate"],
        "source": "tests/test_embodied_plan_eval.py frozen aggregate",
        "suite_freeze_agrees": _embodied_suite_freeze_agrees(),
    }
    return {
        "follow_bench_latest_shipped": {
            "follow_success": latest.get("follow_success"),
            "hard_collision_total": latest.get("hard_collision_total"),
            "navigate_success": latest.get("navigate_success"),
            "mean_band_fraction": latest.get("mean_band_fraction"),
            "report": latest.get("report"),
        },
        "follow_bench_unchanged": follow_ok,
        "embodied_post_speed": embodied_gate,
        "embodied_unchanged": embodied_pin_ok,
    }


def build_report() -> dict[str, object]:
    started = time.perf_counter()
    metrics = _scripted_session()
    nav = _nav_regression_gate()
    elapsed_ms = (time.perf_counter() - started) * 1000.0
    hard_gates = {
        "ttft_p50_under_1s": float(metrics["ttft_p50_s"]) < 1.0,
        "no_response_over_2s_without_filler": (
            metrics["response_ceiling_breaches"] == 0
            and (
                metrics["filler_audible_max_s"] is None
                or float(metrics["filler_audible_max_s"]) < 2.0
            )
        ),
        "act_continuity_zero_missing": metrics["continuity_missing_frames"] == 0,
        "barge_in_atomicity": bool(metrics["atomicity_ok"]),
        "shadow_round_trip": bool(metrics["shadow_round_trip_ok"]),
        "nav_regression_unchanged": bool(nav["follow_bench_unchanged"])
        and bool(nav["embodied_unchanged"]),
        "filler_no_consecutive_repeats": metrics["filler_consecutive_repeats"] == 0,
    }
    return {
        "schema_version": 1,
        "suite_id": "parcel-duplex-v1",
        "runner_version": "duplex-d0-scripted-v2",
        "utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "elapsed_ms": round(elapsed_ms, 3),
        "metrics": metrics,
        "nav_regression": nav,
        "hard_gates": hard_gates,
        "hard_gates_pass": all(hard_gates.values()),
        "does_not_prove": list(DOES_NOT_PROVE),
        "pool_size": FillerPool.default().size,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--out",
        type=Path,
        default=DEFAULT_RESULTS_DIR,
        help="results directory for the immutable report and ledger.jsonl",
    )
    args = parser.parse_args(argv)
    out_dir = args.out
    out_dir.mkdir(parents=True, exist_ok=True)
    report = build_report()
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    nonce = uuid.uuid4().hex[:8]
    path = out_dir / f"duplex-v1-{stamp}Z-{nonce}.json"
    path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    ledger = {
        "suite": "duplex-v1",
        "utc": report["utc"],
        "report": path.name,
        "hard_gates_pass": report["hard_gates_pass"],
        "ttft_p50_s": report["metrics"]["ttft_p50_s"],
        "response_ceiling_breaches": report["metrics"]["response_ceiling_breaches"],
        "continuity_missing_frames": report["metrics"]["continuity_missing_frames"],
        "nav_regression_unchanged": report["hard_gates"]["nav_regression_unchanged"],
    }
    with (out_dir / "ledger.jsonl").open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(ledger, separators=(",", ":")) + "\n")
    print(json.dumps({"report": str(path), "hard_gates_pass": report["hard_gates_pass"]}))
    return 0 if report["hard_gates_pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
