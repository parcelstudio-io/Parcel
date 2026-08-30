# LIT-1 — the well-instrumented loop: sim + runtime + Model B + hosted voice, replayable

Author: Fable (parcel-0e), 2026-08-29. Pre-registered before any run.
Evidence tiers: `desktop-sim` (MuJoCo static city via the live runtime) for
the loop; `hosted-live` for the voice rows (through the governor, inside the
wave's $5 cap shared with MB-1). Physical: NO-GO.

## Deliverable (this is a harness, with two measured hypotheses)

`sim_loop.py`: one process that (1) starts the MuJoCo static-city sim on a
unique socket (systemd-run scope, MemoryMax=12G), (2) builds the runtime the
way `tests/test_voice_nav_e2e.py::_LiveRuntime` does (`PARCEL_MEMORY_PATH`
→ scratch; commissioned sim config), (3) attaches Model B's plan-queue
whisper (MB-1) as the context source for a Realtime lane — either the
product's `FakeRealtimeServer` with scripted turns (deterministic tier) or
the live hosted lane, (4) feeds the owner's utterances (text, or TTS →
the lane's audio path when it exists) on a scripted timeline, and (5) logs
EVERY hop with a monotonic timestamp to one JSONL: utterance in, cue/intent,
executive submit/suspend/resume receipts, navigator state changes, body-lane
velocity samples (1 Hz), narration events, whisper refreshes, hosted request
/ response timestamps, spoken text, $ rows. `replay.py` renders a JSONL into
a self-contained HTML timeline (no external assets) so a reader can see
speech and movement on one axis — the "well-lit" part.

Scenario of record (`scenarios/door_sofa_keys.json`): the robot is sent
to the door (a landmark stand-in on the demo city); at 50 % of the path the
owner says "actually, go back to the sofa and check if I left my keys";
the robot revises (or queues) and goes; on arrival the voice reports done and
offers to return; the owner says "yes"; the robot resumes the door goal.
Plus 5 variants: blocked route, unreachable goal (clarify), queue phrasing,
sound event mid-route (liveness), and a no-op utterance ("nice weather").

## Hypotheses (falsifiable)

**H-LIT1a (the loop closes end to end, deterministically).** With the fake
server, the scenario of record runs to terminal state with the expected
receipt sequence (start door → suspend → start sofa → arrived sofa →
resume door → arrived door) in 5 of 5 seeded runs, byte-identical receipt
order, and the HTML replay renders every hop.

**H-LIT1b (hop latencies are known).** With the hosted lane, per hop p50/p95
over ≥ 3 live runs: utterance → cue, cue → executive receipt, receipt →
whisper refresh, whisper → first spoken token (TTFT), and the end-to-end
"owner finishes speaking → robot starts turning toward the new goal";
report against the bars: switch ≤ 1.5 s, TTFT ≤ 1.2 s. UNMEASURED if the
governor refuses.

## Measurements

Receipt sequences; per-hop latencies; total $ per run; replay artifact size;
any collision/false arrival (must be 0); the narration grounding score from
MB-1's scorer on the live transcripts.

## Success criteria

a: 5/5 deterministic; b: bars met on p50 (p95 reported).

## What it does NOT prove

No audio hardware, no real robot, no real owner; the "door" and "sofa" are
demo-city landmarks; hosted behaviour sampled on one date.

## OWNS / must not touch

OWNS `research/20260829/sim-loop-1/**`. Reads (never imports) the e2e
test; uses `realtime/fake_server.py`, `lane.py`, `driver.py`, the whisperer
and the tool broker as the product exposes them. Never `:8765` /
`/tmp/parcel_sim.sock`; unique socket; `TMPDIR` unset; no product edits.

## Reproduction

`.parcel/bin/python research/20260829/sim-loop-1/sim_loop.py --scenario door_sofa_keys --voice fake --seed 20260829`
`.parcel/bin/python research/20260829/sim-loop-1/sim_loop.py --scenario door_sofa_keys --voice hosted --runs 3`
`.parcel/bin/python research/20260829/sim-loop-1/replay.py <jsonl> --html out.html`
