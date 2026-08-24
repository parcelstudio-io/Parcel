# H3 — drives and initiative · DESIGN (Fable) · 2026-08-23

## Hypothesis (falsifiable)
A persistent **drive model** — four scalar drives (curiosity, social,
comfort, duty) with decay and stimulus-driven rises — feeding a pure goal
generator that emits **bounded** proposals (`LOOK(bearing)`,
`APPROACH(entity, standoff)`, `REMARK(kind)`, `GO_CHECK(place, budget)`,
`REST`) through the existing admission doors makes the dog, in the headless
city with dynamic agents, initiate 3–8 behaviors per hour of which ≥ 80 %
are admitted, reach a max radius from home ≥ 6 m (ROAM-2 measured ~3 m),
touch nothing, yield to owner speech / e-stop within one control tick, and
never initiate inside the quiet window or the night band.

## Why (lifelike-behavior survey)
- No goal generator exists: the only system-initiated plan is owner-search
  after follow loses the owner (`runtime.py:~5900`). Curiosity is a
  remark door on a 4–8 min Poisson gap; the awareness sweep ships OFF and
  cannot translate; roam is owner-commanded and travel tools are
  proactively refused by name (`realtime/config.py:~195-211`) — for a
  good reason (bench finding C1: "a dog that decided to leave").
- The attention core is pure and unwired (`attention/arbiter.py`
  `ReactionArbiter` with Improv scoring + habituation; `StimulusBus`); the
  runtime feeds it only `DIALOGUE_STATE`. `docs/ATTENTION_STEERING_DESIGN.md`
  asks for a *trainable* core later (Stage A tables → Stage B MLP) — every
  tick should log (features, decision, outcome) from day one.
- ROAM-2's H2 fix (minimum candidate distance + forward-bearing preference
  / frontier term) is written in `scrum/20260822/task_33/ROAM2_STATUS.md §7`
  and never applied.
- The safety envelope for initiative already exists as withholding
  thresholds (rate caps, quiet_s=90, night_quiet, R28 input-health, the
  proactive-motion allowlist). The experiment keeps every one of them and
  adds one consent knob: `initiative.travel_radius_m` (default 0 = no
  self-initiated travel), so "the dog leaves" is an owner policy.

## Objective
Show that lifelike initiative is a bounded-proposal problem with a
measurable annoyance budget, and produce the drive/goal contract that H2's
monologue and the milestone's behavior executive both consume.

## Experiment
1. **Pure model** (`attention/drives.py`, new leaf): `DriveState(frozen)`
   with per-drive decay constants and rise rules from typed stimuli
   (`attention/stimuli.py` kinds + new NOTICING, PERSON_SEEN,
   OWNER_TURN, BATTERY, IDLE_TIME); `propose(drives, digest, policy) ->
   InitiativeProposal | None` with the bounded kinds above, each with a
   budget (time, distance) and a reason row; deterministic given seed.
2. **Goal admission**: proposals go through the existing paths in the
   harness — `LOOK` → `AwarenessProposal`-shaped yaw; `REMARK` →
   `_curiosity_admitted_names`-gated whisperer event; `APPROACH`/`GO_CHECK`
   → `_accept_plan`/validator with `initiative.travel_radius_m`; `REST` →
   nothing. Refusals are counted, never retried within the cooldown.
3. **Harness**: `simulation/headless_city.py` `HeadlessCityQualityHarness`
   with `DynamicCity` agents; fixed seeds; 3 × 60-simulated-minute runs per
   arm; arms: baseline (today), +LOOK/REMARK only (radius 0), +travel
   radius 6 m, +travel radius 10 m. Simulated owner speech events every
   6–10 min; one e-stop injection per run.
4. **ROAM-2 H2 fix** applied to `coverage_candidates`/patrol policy as the
   `GO_CHECK` candidate source (pre-registered radius rows).
5. **Logging**: every tick logs (drive vector, stimuli, proposal, admission
   verdict, outcome) to a JSONL — the Stage-B training corpus format.

## Measurements (pre-registered)
| row | metric | criterion |
|---|---|---|
| D1 | initiations / simulated hour by kind | 3–8 total (radius-6 arm) |
| D2 | admitted fraction at the doors | ≥ 0.80 |
| D3 | max radius from home; per-block visit fraction | ≥ 6 m; reported |
| D4 | contacts / min clearance to agents | 0; ≥ profile stop distance |
| D5 | preemption latency on owner speech / e-stop | ≤ 1 tick (0.1 s) |
| D6 | initiations inside quiet_s=90 or night band | 0 |
| D7 | radius-0 arm changes navigation commands | 0 (byte-identical motion) |
| D8 | every initiation attributable to one drive row | 100 % |

## What would refute it
D2 < 0.5 ⇒ the proposer fights the gates (E2-D2's lesson) — report which
door refuses and why; D3 < 4 m with the H2 fix ⇒ the coverage objective is
still anti-exploratory (report candidates per sample); D5 > 1 tick ⇒ an
initiated behavior holds the arbiter (name the channel).

## Evidence tier / does not prove
`desktop-sim`. Proves the proposal economy and safety yield in sim; does not
prove lifelikeness to a human (a rating study is a later card) or physical
motion.

## OWNS
`research/20260823/drives-and-initiative/**`, new leaf
`attention/drives.py`, the ROAM-2 H2 fix in `patrol/` (flag
`coverage.min_candidate_distance_m`, default = today's behavior), one
capability test `tests/test_h3_drives.py` (decay/rise determinism; quiet
window refusal; radius-0 emits no travel). Must not touch: `runtime.py`,
`core/`, the proactive-motion allowlist, `configs/robot.yaml`.
