# Task 7 — Realtime Companion R1: lane core, fake-first

**Date:** 2026-08-16 · **Executor:** Claude Opus (agent) · **Auditor:** Fable
**Design of record:** the 2026-08-16 *Parcel Realtime Companion* design
(artifact `d222ecb3-e5a9-4426-b1c0-2499cf6cfe49`; adversarially reviewed, 13
findings folded in — the four blocking fixes below are BINDING).
**Baseline:** `8473a51` + uncommitted concurrent work (do not touch it).

## Objective

Land the R1 software slice of the OpenAI Realtime conversational lane,
entirely offline and deterministic: typed protocol, injectable transport with a
scripted fake server, restricted transcript ingress, both-sides turn ledger,
playback bridge, session manager with watchdog/rollover, and a flag-off
byte-identity proof. No live API call, no credentials, no new dependencies.

## Hard environment facts

- `.parcel` has **no** `websockets`/`aiohttp`/`openai` and `OPENAI_API_KEY` is
  absent. The provider client must sit behind a `Transport` seam; the only
  transport built here is in-process against `FakeRealtimeServer`. The real
  WebSocket transport is R1.5, gated on the owner installing `websockets` and
  providing a key.
- `configs/robot.yaml` is hash-locked (embodied_plan_v1 + DIGEST_SENTINELS).
  **Zero bytes change there.** Lane config is a NEW optional file
  `configs/realtime.yaml`; absent file or `enabled: false` ⇒ the lane does not
  construct. Unknown keys fail closed.
- The BARN external-eval source digests are already stale (pre-N27, measured);
  new modules under `src/parcel_robot/` are current practice (Sol's `bridge/`
  landed today). Do NOT re-pin any BARN digest.
- Other sessions hold uncommitted work in this checkout (`backlog/*`, `docs/*`,
  `src/parcel_robot/bridge/`, gateway tests, `pyproject.toml`). Re-run
  `git status` before starting; never revert, restage, or edit their files.

## Binding design constraints (from the adversarial review)

1. **Never route hosted transcripts through `submit_voice_text` /
   `DuplexVoiceSession.submit_text`.** That is the front door to the whole
   local agent (double replies, double motion) and its barge-in machinery
   (interrupt-latches the sink). Build `RobotRuntime.submit_realtime_transcript()`:
   punctuation-normalize → emergency latch (same actions as the
   `runtime.py:4208` path) → closed-intent + `_FOLLOW`/`_HOLD` sets only →
   ledger write. Nothing else. No planner, no grammars, no conversation LLM,
   no epoch bump.
2. **Punctuation normalization is load-bearing.** `"Stop."` must halt. A
   regression test feeds punctuated variants of every emergency phrase and
   closed intent through the ingress.
3. **Sink ownership.** The lane constructs a `SpeakerSink` when the local
   synthesizer is absent; calls `begin_utterance()` at each hosted response
   start; hosted PCM is coalesced to ≥240 ms chunks and WAV-wrapped
   `pcm16_wav(sample_rate_hz=24000)` (the sink infers rate from the first RIFF
   header — unwrapped 24 kHz plays slow). While a session is active the lane
   owns the sink exclusively; `speak_system` diversion is R-later, but the
   design's ownership rule must hold in R1: the lane never enqueues while a
   DuplexVoiceSession output is live and vice versa (assert, don't assume).
4. **Spoken stop is cloud-dependent — say so.** The status doc must not claim
   otherwise. The panel STOP path is untouched and remains the guarantee.

## Scope — OWNS (create/edit only these)

- `src/parcel_robot/realtime/` (new package): `__init__.py`, `protocol.py`
  (typed events: session.update, item.create/truncate, response.create/cancel,
  transcript deltas/completed, function_call, usage, speech_started, errors),
  `transport.py` (Transport protocol + in-process pair), `fake_server.py`
  (scripted FakeRealtimeServer: happy turns, barge-in, silent stall,
  disconnect, malformed event), `lane.py` (RealtimeLane: relay, session
  manager, watchdog, rollover, ledger writer, playback bridge, arming gate,
  tool-refusal stub), `ingress.py` (normalization + the restricted scan),
  `config.py` (fail-closed loader for `configs/realtime.yaml`).
- `tests/test_realtime_protocol.py`, `tests/test_realtime_ingress.py`,
  `tests/test_realtime_lane.py` (fake-driven end-to-end + seeded failures).
- `src/parcel_robot/runtime.py` — MINIMAL diff: new
  `TRANSCRIPT_ORIGIN_REALTIME` constant + `TRANSCRIPT_ORIGINS` entry,
  `submit_realtime_transcript()`, flag-gated lane construction. Nothing else.
- `src/parcel_robot/memory.py` — additive nullable columns only
  (`session_id`, `speaker`, `origin`, `provider_item_id`), migration over the
  existing rows, existing readers keep working (prove with the existing
  memory tests).
- `scrum/20260816/task_7/R1_STATUS.md` — the status register: frozen contract
  surface, gate table with fresh `ci_gate --tier commit` output, seeded-failure
  table (≥6 seeds, each RED then restored), OWNS compliance with
  `git diff --stat` counts, does_not_prove, handoffs.

## MUST NOT TOUCH

`configs/robot.yaml`, `evals/**` (any manifest), `scripts/ci_gate.py`,
`pyproject.toml`, `tools/`, `src/parcel_robot/bridge/`, `backlog/*`, `docs/*`,
any file another session has modified (check `git status` first),
`providers.py`, `voice_pipeline.py`, `agent.py`, `brain/router.py` (read them;
call them; do not edit them). Run `tools/sync_runtime_assets.py --check` at the
end — it must stay green (configs/realtime.yaml is deliberately NOT in the ship
set for R1; note that in does_not_prove).

## Behaviors and seeded failures (minimum)

| # | Behavior | Seed that must go RED |
| --- | --- | --- |
| S1 | Punctuated "Stop." fires the emergency latch via the ingress | remove normalization |
| S2 | "follow me." executes the closed intent exactly once, never the planner | route ingress through the full agent |
| S3 | Chit-chat executes nothing locally; ledger still gets both sides | drop the ledger write |
| S4 | Hosted 24 kHz PCM is WAV-wrapped before the sink | remove the wrap (rate mismatch detected by test) |
| S5 | Watchdog fires on the fake server's silent stall; reconnect reinjects the tail | disable watchdog |
| S6 | Flag-off: no `configs/realtime.yaml` ⇒ lane not constructed, runtime boots identically | construct unconditionally |
| S7 | Barge-in: speech_started ⇒ sink interrupt + response.cancel + item.truncate with played-ms | skip truncate |
| S8 | Unknown config key refuses at load | accept unknown keys |

## Definition of done

`ci_gate --tier commit` fully green (ruff `new 0`, release-parity green,
frozen sentinels green, default suite green with the new tests riding it);
every seed RED then restored; `R1_STATUS.md` complete; working tree contains
only OWNS files plus the other sessions' untouched work; nothing committed
(land-whole-waves convention). The Fable audit runs after completion —
expect an adversarial pass on exactly the four binding constraints.
