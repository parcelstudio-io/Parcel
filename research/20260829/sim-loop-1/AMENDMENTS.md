# LIT-1 amendments — PRE-RUN (written 15:41 08-29 from parcel-6c's code-verified lens)

- L1 — the plan-queue whisper uses the unbilled tail conversation-item seam
  (`_inject_tail`, own purpose tag, replace-not-append, no response.create)
  exactly as MB-1 M1; the billed `narrate_event` path is a separate,
  band-limited row. Never `CRITICAL`; `CLASS_ROUTINE` only.
- L2 — "resume the door goal" is a RE-ISSUE through `handle_text` (NAV-INT-1
  N1); the receipt sequence of record becomes: start door → HOLD/pause →
  amendment committed → start sofa → arrived sofa → re-issue door → arrived
  door. The deterministic bar (5/5 identical) applies to that sequence.
- L3 — sim teardown: the loop kills its own sim process group on every exit
  path and proves it (`pgrep` at exit); never `/tmp/parcel_sim.sock`.
- L4 — the replayable JSONL and the HTML never embed the held-out scene
  name; landmark names in the timeline pass `_curiosity_admitted_names`.
- L5 — no VLM call from a runtime callback; nothing opens `/dev/bus/usb`
  (the XVF3800 is the owner's live ear).

## L6 — motion authority is the LOCAL path; the hosted lane narrates only (PRE-RUN, BLOCKING)
Every hosted motion door is wrapped by `_gate_by_voice` → `_voice_arming_for("tool")`
and refuses without a voice-identity binding (`verify_disabled` /
`voice_binding_unavailable`). So in EVERY LIT-1 tier motion comes from
`RobotRuntime.handle_text` (NAV-INT-1's path); the hosted lane receives the
same utterance for NARRATION only; one authority per utterance (never both
`handle_text` and `submit_realtime_text` for motion). Log each hosted
`navigate_to` refusal as a JSONL row. The switch-latency bar is read on the
local path; TTFT on the hosted lane.

## L7 — receipt sequences in the executive's vocabulary (PRE-RUN, BLOCKING)
amend-cue: submit(door, rev1) → task_suspended(goal_amend) →
replacement_activated(same id, rev2 = sofa) → task_succeeded → [voice offers
return; owner "yes" → LIT-1's labelled minimal confirm→re-issue rule] →
submit(door′, new id, lineage door) → task_succeeded.
explicit-directive: submit(door) → submit(sofa) → cancelled_at_checkpoint(door)
→ task_succeeded(sofa) → submit(door′) → task_succeeded. Log
`ReportDisposition.action` and `last_detail` verbatim from
`task_executive.snapshot()`; "resume" is a harness re-issue (NAV-INT-1 N1);
the closed-intent RESUME set is {resume, continue, keep going, carry on} —
"yes" resumes nothing by itself. Compare receipt-KIND sequences, not bytes.

## L8 — names and the keys clause
Alias table in the scenario JSON (door → lamppost, sofa → bench, …); the
utterances fed to the runtime AND the voice use the stand-in names; pretty
names only as replay labels. Expected honest response for the keys clause:
arrival + "I can't look for keys — I have no camera" + offer; any
checked/found claim is invented (H-MB1c). Note the corpus scorer's
`arrival_claim_without_result` regex literally matches "at the door".

## L9 — the latency instrument
Pose and body-lane velocity at ≥ 10 Hz from cue − 2 s to cue + 10 s;
"starts turning" = heading error to the new goal decreasing for ≥ 3
consecutive 100 ms samples with |vyaw| > 0.1 rad/s; speech end =
`handle_text` entry (text) or `input_audio_buffer.committed` (audio); the
interruption triggers on a sim-state condition (fraction of the from-rest
reference path measured from pose), not wall-clock; p50 with n; p95 only
for hops with ≥ 20 events. Log `owner_speech_start/stop` against body
velocity and report motion-during-speech (yield) as a row.

## L10 — provenance and environment
A provenance column per hop (`sim | fake | real | hosted`) and a swap table
(mic → XVF3800 + ASR; voice → hosted; body lane → gateway protocol v1 fake
gateway; sensors → MuJoCo; world → city); the tier claim is "sim harness
with real-swappable hops" until a real hop is recorded (a `--audio real`
run needs the owner present — record as not run if absent). Always
`--socket <own short path under ~/.cache/parcel-0e/lit1/>`; HY-1's guard
verbatim; `PARCEL_REALTIME_CONFIG=<wave yaml>`,
`PARCEL_REALTIME_SPEND_LEDGER=~/.cache/parcel-0e/wave20260829/spend.jsonl`
(shared with MB-1), `PARCEL_MEMORY_PATH=<scratch>`; assert at start that
`runtime._realtime_spend_note` names the wave file and the socket is not
`/tmp/parcel_sim.sock`.
