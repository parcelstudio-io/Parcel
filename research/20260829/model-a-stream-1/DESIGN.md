# MA-1 — a trainable streaming Model A cloned from the real navigation stack (headless city)

Author: Fable (parcel-0e), 2026-08-29. Pre-registered before any run.
Evidence tier: `desktop-sim` (headless city, kinematic, no audio). Physical: NO-GO.

## The object under test

Model A v0 = a small causal transformer (BM-1's BehaviorFormer family, ~5 M
params) that every 100 ms reads a **state-of-the-world frame** and emits
(i) an act token from the existing codec (`<twist:i:j>`, `<gaze_*>`,
`<emote:*>`, `<skill:*>`, `<hold>`), and (ii) a **narration event token**
from a small closed vocabulary constrained to what the product can claim:
`none`, `nav.start:<target>`, `nav.progress`, `nav.blocked:<class>`,
`nav.replan`, `nav.arrived:<target>`, `nav.failed:<class>`,
`plan.revised:<target>`, `plan.queued:<target>`, `plan.resumed:<target>`,
`attend.sound:<bearing>`, `attend.owner`. The narration token is the
"representation ChatGPT live can narrate from"; it is exactly the set of
facts the whisperer / receipts can already back.

The frame (all producible today or in the headless sim): BM-1's social
channels + navigation channels — goal kind/target (bounded vocabulary), goal
bearing bin (8), goal distance bin (5), local free-space per 8 sectors (3
bins each, from the LiDAR occupancy grid), plan step kind, plan progress
bin, blocked class, replan count bin, owner visible/bearing/distance, a
`cmd:<name>` / `steer:` cue channel, an `event:sound(bearing)` channel, and
the last-minute summary as 6 coarse "what happened" tokens (BM-1's history
mechanism generalized: last K = 6 narration events).

Teacher: the **real product stack** in the headless city — `DirectiveNavigator`
+ grid planner + executive receipts + the whisperer's forwarding rules +
`awareness_sweep` (liveness) — driven by a scripted owner who issues an
initial directive and, in a fraction of episodes, an interruption
(revise / queue) at a random progress point, and by scripted sound events.
The teacher's act stream is the navigator's velocity command quantized to the
codec bins plus the awareness-sweep gaze; its narration stream is derived
deterministically from executive receipts and mission-block events.

## Hypotheses (falsifiable)

**H-MA1a (closed-loop imitation transfers to held-out layouts).** Trained on
≥ 3,000 teacher episodes over procedurally perturbed headless-city layouts
(landmark positions jittered, obstacles added, start poses sampled), Model A
driving the kinematic robot *closed-loop* on 200 held-out layouts reaches
≥ 0.85 × the teacher's success rate and ≤ 1.25 × its path length, with
collision rate ≤ teacher + 0.02. Refuted below 0.6 × teacher success.

**H-MA1b (interruptions are absorbed in-stream).** On held-out episodes with
a mid-route `cmd:` revise or queue cue, Model A switches to the new goal
within 1.0 s (twist heading toward the new goal bearing) in ≥ 0.9 of cases
and, for queue cues, emits `plan.queued` then `plan.resumed` in the right
order in ≥ 0.8; the frozen reflex-table baseline (BM-1's A′ extended with
the nav channels) is reported beside it.

**H-MA1c (narration events are right and on time).** Event-conditional F1 of
narration tokens vs the teacher-derived gold on held-out episodes ≥ 0.85
for `nav.start`, `nav.arrived`, `nav.blocked`, `plan.revised/queued/resumed`,
each within a 1.0 s window; false-event rate (an event with no backing
receipt) ≤ 0.05 — this is the grounding property QEV-1 found the hosted
model lacks (2/10).

**H-MA1d (liveness does not cost navigation).** With sound events, Model A
emits `attend.sound` + a gaze toward the bearing within 0.5 s in ≥ 0.8 of
events, and its success/path metrics on those episodes are within 0.03 /
5 % of episodes without sound events.

## Arms

- T: teacher (the product stack) — ceiling.
- A′n: reflex table over the current frame (BM-1's A′ + nav channels) —
  the "rules suffice" baseline.
- C: Model A (BehaviorFormer, ctx 128 frames, class-weighted CE on both
  heads, early stopping on dev — pre-registered this time).
- ALWAYS-IDLE / straight-to-goal-bearing references.

## Measurements

Closed-loop success (goal band as the headless harness scores it), SPL,
path ratio, collisions, time-to-switch, narration F1/timing/false-event rate,
sound-attend rate, per-frame latency (GPU / 1 CPU thread), training steps and
wall; all on dev and on the 200 held-out layouts; layouts leakage-grouped.

## Success criteria

CONFIRMED if a, b, c, d all meet their bars on held-out layouts; PARTIAL if
c and at least one of a/b meet; REFUTED otherwise. Beating A′n by ≥ 0.10 on
b's time-to-switch success or on a's success is the "sequence model earns its
place" clause (else "rules + memory suffice").

## What it does NOT prove

Kinematic world (no gait, no real LiDAR noise beyond the harness's
profile), scripted owner, no audio; a high score means the policy learned
the product teacher's behaviour on this city family.

## OWNS / must not touch

OWNS `research/20260829/model-a-stream-1/**`, scratch `~/.cache/parcel-0e/ma1/`.
Reads `simulation/headless_city.py`, `navigation/*`, `brain/executive.py`,
`realtime/whisperer.py`, `duplex/act_codec.py`, and BM-1's `worldsim.py`
(read-only, import by path). No product edits. GPU ≤ 12 GB, one job at a
time; CPU ≤ 48 threads for rollout generation.

## Reproduction

`~/.cache/parcel-0e/venv/bin/python research/20260829/model-a-stream-1/run.py --all --seed 20260829`
