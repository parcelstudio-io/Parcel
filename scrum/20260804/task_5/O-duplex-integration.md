# Workstream O — Opus: D0 wiring, fillers, logging, eval

Owns existing files; builds against the S-card signatures as written.

## D-O1 — Filler policy wiring · after D-S3 lands (scaffold now)

1. **Predictive trigger:** at the exact points where a turn routes to a slow
   path — planner invocation (`plan_timeout` routes), information-tool
   calls, any model search — emit the filler *before* dispatching the slow
   work. The filler plays through the normal TTS path (a real utterance,
   sentence-chunked, barge-in-able) plus its gesture via the activity
   coordinator.
2. **Watchdog:** end-of-turn commit starts a ~700 ms timer (config
   `duplex.filler_watchdog_s`); if no first token has reached the TTS queue,
   fire a filler. Cancel the timer on first token.
3. **Clause-boundary handoff:** if the real reply arrives mid-filler, the
   filler's current sentence finishes, then the reply plays (never cut
   mid-word; the sentence-chunked pipeline gives this nearly free).
4. **Metric:** `FillerLatency` (end-of-turn → filler audible) and
   `ResponseCeilingBreach` counter (any turn where neither answer nor
   filler was audible within 2.0 s — target zero, exposed in `/api/state`).
   Config under `duplex:` with fail-closed keys.

## D-O2 — D0 system-composed producer · after D-S1 + D-S2

1. Instantiate `FrameInterleaver` on the control-loop clock (10 Hz tick in
   `_control_loop`, same place expression steps).
2. **TEXT feed:** the streamed LLM reply (existing sentence stream) pushes
   word/chunk tokens; TTS consumption is unchanged — the frame stream
   *observes* the same tokens it speaks.
3. **ACT feed:** adapt existing events into codec tokens: attention-arbiter
   decisions → gaze/emote tokens; active twist dispatches (post-arbiter,
   post-gate — encode what was *actually commanded*) → twist bins; skill
   dispatches → `<skill:name>`; filler firings → filler tokens; otherwise
   the interleaver fills `<idle>`.
4. **Epoch integration:** wire the existing speech-epoch bump (barge-in /
   supersession) into `interleaver.set_epoch`; add the atomicity test — no
   post-epoch frame content executes or logs as current.
5. **Executor direction (D1-ready):** a `DuplexFrameConsumer` that would
   route decoded `ActCommand`s into the admissibility chain. In D0 it runs
   in **shadow mode** (frames are derived FROM executed behavior, so
   consuming them would double-execute); the eval asserts shadow decode
   round-trips to the executed command. This is the seam D1's model plugs
   into.

## D-O3 — Aligned-stream logging · after D-O2

`logs/duplex/<session>.jsonl`, rotating: per frame `{t, epoch, text, act}`
plus per-tick context features (the attention feature vector, owner
geometry, activity) and per-turn outcomes (TTFT, filler used, barge-in).
This is the D1 training corpus — schema documented in the design record;
gitignored; a privacy note in the doc (transcripts stay local). Budget:
< 2 MB/hour; a `duplex.logging: false` kill switch.

## D-O4 — `DUPLEX_V1` eval · after D-O1 + D-O2

Headless, scripted turns (text-injected, no audio hardware): fast-answer
turn (TTFT P50 < 1 s, no filler), slow-answer turn (forced planner route:
filler audible < 1 s, real answer follows at clause boundary, ceiling
breaches == 0), repeated slow turns (filler variation — no consecutive
repeats), barge-in mid-reply and mid-filler (atomicity: both streams die,
frame log shows the epoch cliff), continuity (zero missing frames over the
session), shadow-decode round-trip. Nav regression: follow-bench + embodied
suites in the same lane, rows unchanged from the 2026-08-04 post-speed
values. Ledger + `does_not_prove` (scripted text turns ≠ live audio; D0
frames derive from behavior rather than driving it — that flips in D1).
