# R1 — Realtime Companion lane core (fake-first)

**Date:** 2026-08-16 · **Card:** `scrum/20260816/task_7` · **Executor:** Claude Opus
**Baseline:** `8473a51` + other sessions' uncommitted work (untouched)
**Venv:** `/home/jaewoo-jang/Desktop/Projects/Parcel/.parcel/bin/python`
**Design of record:** *Parcel Realtime Companion* (2026-08-16, artifact
`d222ecb3-e5a9-4426-b1c0-2499cf6cfe49`), §1 sink ownership, §3 restricted
ingress, §9 the four blocking review findings.

## What landed, in one paragraph

The R1 software slice of the hosted Realtime lane, entirely offline: a typed,
fail-closed codec for the Realtime event subset; a `Transport` seam whose only
R1 implementation is an in-process queue pair; a scripted `FakeRealtimeServer`
that can express a normal turn, barge-in, a silent stall, a mid-turn
disconnect, a malformed frame and a function call; a restricted transcript
ingress that normalizes punctuation and then reads exactly five things
(emergency / closed intent / follow / hold / nothing); a both-sides turn ledger
on additive nullable columns; a playback bridge that coalesces to ≥240 ms and
WAV-wraps at 24 kHz; a session manager with an injectable-clock watchdog,
rollover and reconnect-with-tail; a fail-closed arming gate; and a tool broker
that refuses every call. **No live API call, no credentials, no new
dependencies, nothing committed.**

## Files

| File | Lines | What |
| --- | --- | --- |
| `src/parcel_robot/realtime/__init__.py` | 83 | package surface |
| `src/parcel_robot/realtime/protocol.py` | 537 | typed event codec; unknown type ⇒ `UnknownEventType` |
| `src/parcel_robot/realtime/transport.py` | 160 | `Transport` Protocol + in-process pair, injectable clock |
| `src/parcel_robot/realtime/fake_server.py` | 360 | `Step` script + `FakeRealtimeServer` + six turn builders |
| `src/parcel_robot/realtime/ingress.py` | 230 | `normalize` / `scan` / `RealtimeTranscriptOutcome` |
| `src/parcel_robot/realtime/config.py` | 193 | fail-closed `configs/realtime.yaml` loader |
| `src/parcel_robot/realtime/lane.py` | 860 | `RealtimeLane`, arming gate, playback bridge, watchdog |
| `tests/test_realtime_protocol.py` | 342 | 29 tests |
| `tests/test_realtime_ingress.py` | 236 | 93 tests |
| `tests/test_realtime_lane.py` | 1158 | 65 tests (fake-driven end-to-end + runtime integration) |
| `src/parcel_robot/memory.py` | +116 / −0 | additive nullable columns, guarded migration, `write_realtime_turn` |
| `src/parcel_robot/runtime.py` | +171 / −1 | origin constant, `submit_realtime_transcript`, flag-gated lane |
| `scrum/20260816/task_7/R1_STATUS.md` | this file | |

`git diff --numstat` on the two edited files reads `116 0 memory.py` and
`178 2 runtime.py`; **7 insertions and 1 deletion of the runtime.py figure
belong to another session's concurrent `first_clause_chars` edit at
runtime.py:1039**, which was left exactly as found. This card's runtime.py diff
is 171 insertions / 1 deletion across five hunks (imports, the origin constant,
lane construction, the `submit_voice_text` guard, and
`submit_realtime_transcript` + its ledger helper).

## Frozen contract surface

**Protocol (`protocol.py`).** Client: `session.update`,
`input_audio_buffer.append`, `conversation.item.create`,
`conversation.item.truncate`, `response.create`, `response.cancel`. Server:
`session.created`, `input_audio_buffer.speech_started` / `.speech_stopped`,
`conversation.item.input_audio_transcription.completed`,
`response.output_audio_transcript.delta` / `.done`,
`response.output_audio.delta` / `.done`,
`response.function_call_arguments.done`, `response.done` (with usage), `error`.
`SERVER_EVENT_TYPES` / `CLIENT_EVENT_TYPES` are pinned by test; an unknown type
raises `UnknownEventType`, a known type missing a required field raises
`MalformedEvent`, and both are `RealtimeProtocolError(ValueError)`.

**Ingress (`ingress.py`).** `normalize(text)` collapses whitespace and strips
`. , ! ? …` from both ends, preserving case. `scan(text) -> IngressScan` with
`kind ∈ {emergency, closed_intent, follow, hold, none}`. Phrase sets are
**read, never copied**: `EMERGENCY_STOP_PHRASES is
closed_intent_phrases(ClosedIntent.STOP)`, closed intents via
`parse_closed_intent`, follow/hold read off `brain.router._FOLLOW` / `._HOLD`
through the module object (a test monkeypatches `_FOLLOW` and the lane follows
it, proving drift is impossible).

**Runtime (`runtime.py`).** `TRANSCRIPT_ORIGIN_REALTIME = "realtime"` added to
`TRANSCRIPT_ORIGINS`; `submit_realtime_transcript(text, *, item_id=None,
session_id=None) -> RealtimeTranscriptOutcome`; `runtime.realtime_config` and
`runtime.realtime_lane` (the latter `None` unless a config file enables it).

**Ledger (`memory.py`).** `messages` gains nullable `session_id`, `speaker`,
`origin`, `provider_item_id` via a `PRAGMA table_info`-guarded `ALTER TABLE`.
`write_realtime_turn(*, session_id, speaker, text, origin, provider_item_id)`
maps `owner|robot|system → user|assistant|tool`; `realtime_turns(...)` returns
oldest-first rows where `speaker IS NOT NULL`, so a local typed turn can never
be replayed to the provider as hosted history.

**Config (`config.py`).** Schema exactly `{enabled, model, voice,
stall_timeout_s, session_max_s, monthly_budget_usd}`. Unknown key ⇒
`RealtimeConfigError`. Absent file ⇒ `RealtimeConfig(enabled=False,
source="absent")`. Location: `configs/realtime.yaml`, overridable for tests via
`PARCEL_REALTIME_CONFIG`.

**Lane (`lane.py`).** `RealtimeArmingDecision(armed, code, reason)` mirroring
`MicArmingDecision`; codes `armed`, `realtime_disabled`, `no_handshake_token`,
`no_mic_gesture`, `monthly_budget_exhausted`, `no_transport`. `RealtimeLane`
exposes `arm`, `open_session`, `send_audio`, `pump`, `tick`, `close`,
`played_ms`, `assert_sink_free`, `assert_lane_not_speaking`, `snapshot`.
`TOOL_REFUSAL_OUTPUT == '{"error": "tools are not enabled in R1"}'`.

## The four binding constraints, and where each is proven

### 1. Hosted transcripts never reach `submit_voice_text`

`submit_realtime_transcript` does four things and stops: normalize → emergency
latch (`engage_emergency_stop` + `emergency_stop` + `barge_in`, the same three
actions as runtime.py's voice fast path) → closed intents + follow/hold through
the same runtime handlers the router path uses → ledger write. It never touches
`voice_session.submit_text`, so there is no speech-epoch bump, no barge-in
interrupt-latch, no planner, no conversation model.

Enforced structurally as well as by convention: `submit_voice_text` now
**refuses** `origin="realtime"` with a message naming the right door. The
constant is still in `TRANSCRIPT_ORIGINS` because the ledger's provenance
vocabulary needs it; what the guard removes is the ability to use that
vocabulary entry as an ingress permission.

Proven by `test_follow_me_executes_once_and_never_reaches_the_planner` (spies
on `set_behavior`, `agent.handle_text`, `voice_session.submit_text` and the
language model: exactly one `set_behavior("follow")`, zero of everything else),
`test_submit_voice_text_refuses_the_hosted_origin_outright`, and
`test_chit_chat_executes_nothing_locally_but_is_still_ledgered`.

### 2. Punctuation normalization is load-bearing

`test_realtime_ingress.py` feeds every emergency phrase (4), every admitted
closed intent's phrase set (21 phrases across pause/resume/faster/slower/come)
and every follow (4) and hold (4) phrase through six suffixes
(`.` `!` `?` `...` `…` `,`) — 60 parametrized cases — and
`test_the_unnormalized_text_really_does_match_nothing` states the premise as an
executable fact (`parse_closed_intent("stop.") is None`). End-to-end,
`test_every_punctuated_emergency_phrase_halts_end_to_end` drives four punctuated
variants through a real `RobotRuntime` and asserts
`agent.safety.emergency_stopped`.

### 3. Sink ownership

`_begin_response` calls `sink.begin_utterance()` at each hosted response start
(the sink never re-arms on `enqueue`, so a post-barge-in reply would otherwise
be silent — pinned by `test_the_sink_is_rearmed_for_the_reply_after_a_barge_in`).
Audio is coalesced to ≥240 ms and wrapped with
`pcm16_wav(sample_rate_hz=24000)`. Ownership is **asserted, not assumed**:
`assert_sink_free()` runs before every claim and raises `SinkOwnershipError`
when a `DuplexVoiceSession` output is live, and `assert_lane_not_speaking()` is
the same rule in the other direction. The runtime wires
`duplex_output_active` to the very field `speak_system` consults
(`voice_session._active_output`).

### 4. Spoken stop is cloud-dependent — stated, not glossed

**A spoken "stop" in this lane travels through the cloud to become text.** There
is no local ASR in the hosted hot path. What R1 proves is that once the text
exists, it latches the *same* e-stop the panel does, synchronously, before
anything else runs. The cloud-independent stop paths — the panel STOP button,
the independent operator stop, every local watchdog — are untouched by this
card and remain the guarantee. Making spoken stop cloud-independent means
forking the mic stream to the local whisper.cpp stop-phrase spotter; that is an
R3 decision, not an assumption, and nothing here should be read as having made
it.

## Design decisions worth naming

* **Follow / hold / come take `set_behavior`, not `_admit_local_sketch`.**
  The agent prefers a `PlanSketch → PlanIR` admission when `_local_plan_ready()`,
  but that path needs a routed `IntentFrame` and the agent's planner-output
  adapter — i.e. the machinery constraint 1 forbids. R1 uses the runtime's own
  `set_behavior` door, which is exactly what `behavior_publisher` exposes to the
  agent and what the agent uses with no local planner. Follow/stay through PlanIR
  admission is scheduled as R4 in the design's own milestone table.
* **`ClosedIntent.COME` routes to `set_behavior("follow")`, not
  `_apply_closed_intent`.** `resolve_cap(COME)` returns a directive whose only
  content is a `sketch`; `_apply_closed_intent` matches none of its branches and
  would fall through to `return directive.reply` — replying *"Okay—I'll come to
  you safely"* while doing nothing. The agent handles COME before its
  closed-intent handler for the same reason.
* **`ClosedIntent.GOAL_AMEND` is excluded from the ingress.** It is a request to
  re-plan, and re-planning is the deliberative planner. It scans as `none`, the
  hosted model answers it conversationally, and nothing local moves.
* **Cost rows are JSONL beside the ledger, not a sqlite table.** One file, one
  query for invoice ÷ committed turns, and a cost write can never take a lock
  the conversation ledger needs mid-turn. Path is injected
  (`cost_log_path`); the runtime does not set one in R1.
* **The ledger stores the sentence as spoken; normalization is for matching
  only.** `submit_realtime_transcript` writes the whitespace-collapsed original
  (`"Stop."`) and acts on the normalized form (`"Stop"`).
* **Who writes the owner row.** With a runtime ingress wired, the runtime writes
  the owner side and the lane writes the robot side. With no ingress (lane-only
  unit wiring) the lane writes both. Exactly one owner row either way —
  `test_both_sides_land_in_the_ledger_for_a_full_hosted_turn` pins the shipped
  wiring.
* **`PARCEL_REALTIME_CONFIG`.** Flag-on had to be testable without adding
  `configs/realtime.yaml` to the repo, since the shipped default is *file
  absent*. The env var is read only inside
  `realtime/config.resolve_realtime_config_path`.

## Gate table

```
$ .parcel/bin/python scripts/ci_gate.py --tier commit
CI GATE — tier=commit  (2026-08-17T00:19:54Z)
==============================================================================
[  PASS] HARD  ruff                       7 violation(s), baseline 7, new 0
[  PASS] HARD  hard-safety                nav frozen baseline nav-instruct-v1-baseline-v4-20260811T070536Z: collisions=0 false_arrival=0 | mutation panel clean: collisions=0 no_false_arrival=True | mutation panel freshness: committed fields reproduce live = True | follow-bench: 7 row(s), hard_collision_total all 0 = True | walk_with_me: 1/2 row(s) with hard_collision_total, all 0 = True
[  PASS] HARD  frozen-digest-sentinels    4 immutable manifest(s) byte-identical to pin
[  PASS] HARD  release-parity             91 packaged asset(s) byte-identical to canonical source
[  PASS] HARD  latency-tail-ledger        latest row latency-20260810T082415Z-4d83035f: 6 metric series within 1.2x tail ceiling (rows=5, window=5)
[  PASS] HARD  follow-bench-jerk-ratchet  latest shipped row follow-bench-v1-20260811023618Z-93eba090.json: 1.2187 <= 1.46244 (baseline 1.2187 x 1.2)
[  PASS] HARD  model-off-non-inferiority  23 passed in 0.45s
[  PASS] HARD  frozen-digest-integrity    6 passed, 1 warning in 0.33s
[  PASS] HARD  release-parity-integrity   10 passed in 0.72s
[  PASS] HARD  mutation-panel-freshness   2 passed, 3 warnings in 4.27s
[  PASS] HARD  latency-tail               6 passed, 2 warnings in 0.29s
[  PASS] HARD  default-suite              5658 passed, 9 skipped, 40 deselected, 5 warnings in 230.87s (0:03:50)
==============================================================================
RESULT: PASS — every hard gate green.
  elapsed 243.4s
```

`ruff` reports `new 0` against the pinned baseline of 7 (the baseline was not
regenerated). The default suite carries this card's 187 new tests; it read
5375 in the 2026-08-15 FIX-A run and 5658 here, the difference being these 187
plus other sessions' concurrent additions. **This is the second run:** the first
(00:15:32Z, identical verdicts) was started before a last one-line addition to
`RealtimeLane.snapshot()`, so it was re-run on the final tree rather than
reported against a stale one.

## Seeded-failure table

`scratchpad/seed_r1.py` (under the session scratchpad, never the repo) mutates
one shipped source file per seed, runs the owning test file(s), and restores the
file in a `finally` block. `git status --short` before and after the whole run
is byte-identical, and the clean suite is re-run at the end.

| # | Seeded defect | File | Result | First failing test(s) |
| --- | --- | --- | --- | --- |
| S1 | normalization removed (`return collapsed`) — hosted punctuation defeats every phrase set | `realtime/ingress.py` | **RED** 83 failed, 75 passed | `test_every_punctuated_emergency_phrase_still_latches[.-halt]`, `test_a_new_router_follow_phrase_reaches_this_lane_without_an_edit` |
| S2 | follow routed through the full local agent (`self.handle_text`) instead of the closed door | `runtime.py` | **RED** 1 failed, 64 passed | `test_follow_me_executes_once_and_never_reaches_the_planner` |
| S3 | owner-side ledger write dropped | `runtime.py` | **RED** 3 failed, 62 passed | `test_chit_chat_executes_nothing_locally_but_is_still_ledgered`, `test_both_sides_land_in_the_ledger_for_a_full_hosted_turn` |
| S4 | 24 kHz WAV wrapper removed (`sink.enqueue(chunk)`) | `realtime/lane.py` | **RED** 3 failed, 62 passed | `test_a_normal_turn_plays_wav_wrapped_24k_audio_and_closes_with_usage`, `test_raw_24k_pcm_would_play_slow_which_is_why_the_wrapper_exists` |
| S5 | stall watchdog disabled | `realtime/lane.py` | **RED** 1 failed, 64 passed | `test_the_watchdog_fires_on_a_silent_stall_and_reinjects_the_tail` |
| S6 | lane constructed unconditionally (`if True:`) | `runtime.py` | **RED** 1 failed, 64 passed | `test_flag_off_leaves_the_lane_unconstructed` |
| S7 | barge-in skips `conversation.item.truncate` | `realtime/lane.py` | **RED** 1 failed, 64 passed | `test_barge_in_interrupts_cancels_and_truncates_at_played_milliseconds` |
| S8 | unknown config keys accepted | `realtime/config.py` | **RED** 1 failed, 64 passed | `test_an_unknown_config_key_refuses_at_load` |

8 seeds, 8 RED. `=== tree restored: YES ===`, then
`clean: PASS :: 187 passed, 2 warnings in 1.27s`.

## Test runs

```
$ .parcel/bin/python -m pytest tests/test_realtime_protocol.py \
    tests/test_realtime_ingress.py tests/test_realtime_lane.py -q
187 passed, 2 warnings in 1.45s
```

```
$ .parcel/bin/python -m pytest tests/test_runtime.py tests/test_tiered_memory.py \
    tests/test_agent.py tests/test_closed_intent_product_path.py \
    tests/test_fixa_transcript_persistence.py tests/test_fixa_mic_arming.py \
    tests/test_duplex_integration.py tests/test_k6_voice_lanes.py \
    tests/test_false_positive_memory.py tests/test_instructnav_memory.py -q
209 passed, 3 warnings in 11.76s
```

```
$ .parcel/bin/python tools/sync_runtime_assets.py --check
release parity OK: 91 packaged file(s) match source
```

```
$ .parcel/bin/python -m ruff check src/parcel_robot/realtime/ \
    src/parcel_robot/memory.py src/parcel_robot/runtime.py \
    tests/test_realtime_*.py
All checks passed!
```

Every new file is also `ruff format`-clean.

## OWNS compliance

`git status --short` after the full run contains, from this card and nothing
else:

```
 M src/parcel_robot/memory.py
 M src/parcel_robot/runtime.py
?? src/parcel_robot/realtime/
?? tests/test_realtime_ingress.py
?? tests/test_realtime_lane.py
?? tests/test_realtime_protocol.py
?? scrum/20260816/          (this card + R1_STATUS.md)
```

Everything else in `git status` — `backlog/*`, `docs/*`, `configs/robot.yaml`,
`pyproject.toml`, `scripts/ci_gate.py`, `tools/sync_runtime_assets.py`,
`src/parcel_robot/bridge/`, `src/parcel_robot/providers.py`,
`src/parcel_robot/paths.py`, the gateway/release-parity tests, the
`runtime_assets/` navigation models — was already modified or untracked when
this card started and was **not** read-modified, staged, reverted, or committed
here. `configs/robot.yaml` gained zero bytes. Nothing was committed
(land-whole-waves).

## does_not_prove

* **Nothing here has spoken to OpenAI.** There is no `websockets`, no
  `aiohttp`, no `openai` in `.parcel` and no `OPENAI_API_KEY` on this host. Every
  behavioural claim above is a claim about `FakeRealtimeServer`. The provider's
  real event ordering, its real timing, and its real tolerance for a truncate
  arriving after a cancel are **verified in documentation only**. The live
  WebSocket transport is R1.5.
* **The sink is a fake in every test.** `_FakeSink` reproduces the two
  `SpeakerSink` behaviours the bridge depends on (`begin_utterance` clears the
  first-chunk anchor; the anchor is stamped when a chunk starts), but it treats
  "was enqueued" as "started playing". The real sink stamps
  `first_chunk_started_monotonic` on its worker thread at *write* start, which
  the virtual-rig eval measured 0.54–0.64 s ahead of audibility. **Played-ms in
  a truncate is therefore an upper bound on what was heard, not a measurement of
  it**, and no audio was ever played on this host (PortAudio is not loadable
  here).
* **`speak_system` diversion is not implemented.** R1 asserts the ownership rule
  and refuses a conflicting claim; it does not yet route
  `_brain_vocalize` / `speak_system` into the hosted session, so with a session
  live a system utterance would simply be refused rather than spoken. That is
  R2 in the design.
* **`configs/realtime.yaml` is deliberately NOT in the ship set.** The file does
  not exist in the repo, is not added to `tools/sync_runtime_assets.py`'s
  packaged set, and `--check` stays green precisely because nothing was added.
  A wheel install therefore has no way to enable the lane, which is the intended
  R1 posture and will need a sync-set entry when R1.5 ships a real transport.
* **The runtime can construct the lane but can never open a session in R1.**
  With `enabled: true` the lane object exists and the arming gate refuses with
  `no_transport`. So "flag-on works" means "the object is built and refuses
  correctly", not "a hosted conversation happened".
* **No claim about latency or cost.** The design's ~0.7–1.2 s voice-to-voice
  budget and the $/min figures are unmeasured here. Usage rows are parsed and
  written; no invoice has ever been compared against them.
* **Input transcripts are approximate.** They come from a separate ASR pass at
  the provider, not from what the model heard. The ledger records them as the
  owner's words because that is all this lane can see; B21's human corpus
  remains the honest ground truth for accuracy claims.
* **Prosody and expression are not wired.** The bridge coalesces to ≥240 ms *so
  that* `analyze_pcm16` could produce accents, and enqueues WAV so the sink's
  `on_chunk_start` could anchor them — but R1 enqueues directly on the sink and
  does not call the prosody path or `_enqueue_speech_chunk`. Beat nods on hosted
  audio are R3.
* **The migration was exercised on a fresh file and a synthetic legacy file,
  not on the live `parcel_memory.sqlite3`.** The live database was never opened
  by this card.
* **Hosted turns do not appear in `/api/state`'s chat block or in
  `TieredMemory`.** `submit_realtime_transcript` deliberately does not call
  `_chat_item` — that would pull in `_remember_turn` → `prompting.memory`, i.e.
  a second store and a second write path, which "nothing else" forbids. The
  hosted conversation lives in the sqlite ledger only. Surfacing it in the panel
  is a small, separate change and is not made here.
* **The `submit_voice_text` guard is one line beyond the card's literal
  wording.** The card asked for the constant and the frozenset entry; refusing
  `origin="realtime"` at that door is how binding constraint 1 stops being a
  convention. It is strictly a refusal — it can only reject calls that do not
  exist today — and it is called out here rather than buried.
* **Barge-in ledgering keeps the transcript deltas received before the cancel.**
  If the provider's transcript stream runs ahead of its audio stream, the
  ledgered "heard" text over-reports by that lead. R1 has no way to measure the
  lead; the design's "truncate-to-heard" is R2.

## Handoffs

* **R1.5 — live transport.** Implement `Transport` over `websockets` against the
  same `send` / `receive` / `close` contract; nothing in `lane.py` should need
  to change. Requires the owner to install `websockets` and provide a key, plus
  a loopback audio listener carrying the panel's CSRF token in its handshake
  (the arming gate already has the `no_handshake_token` code for it).
* **R2 — memory + cost.** Wire the summarize hook to the local reasoner (the
  stub currently ledgers `"[session rollover] summarization is not implemented
  in R1"`), set `cost_log_path` from config, implement `speak_system`
  diversion, and tighten truncate-to-heard once real playback marks are
  available.
* **R3 — tools.** The broker stub is one method (`_on_function_call`); the
  design's six-tool table and the utterance-scoped `already_done` rule replace
  its refusal.
* **Sink construction.** `RealtimeLane` accepts `sink_factory` so it can build
  its own `SpeakerSink` when the local synthesizer never loaded; the runtime
  currently passes the existing `self._speaker_sink` (which is `None` in
  text-only mode) and no factory. Whoever ships R1.5 must pass
  `sink_factory=SpeakerSink` or hosted audio has nowhere to go.
