# NAV-INT-1 — instruction following with mid-task interruptions (shipped stack + a plan-queue policy)

Author: Fable (parcel-0e), 2026-08-29. Pre-registered before any run.
Evidence tier: `desktop-sim` (MuJoCo static city through the live runtime,
exactly the `tests/test_voice_nav_e2e.py::_LiveRuntime` path; the local
reasoner is whatever that fixture uses — record it). Physical: NO-GO.

## Hypotheses (falsifiable)

**H-NI1a (the shipped stack handles a single spoken interruption).** When a
second, owner-recognized navigation command arrives while a first task is
executing, the shipped runtime (i) admits it as a goal amendment (C8
transactional path) within 1.0 s, (ii) reaches the *amended* goal at least
as often as it reaches the same goal issued from rest (paired, same
start/goal geometry), and (iii) never produces a false arrival or a
collision during the switch. Refuted if amendment admission < 0.8 of
attempts, or amended-goal success is lower than from-rest success by
> 0.10 absolute, or any collision/false arrival appears in the switch
window.

**H-NI1b (a plan-queue policy restores the original goal).** The shipped
stack has suspend/resume but no queue policy: after the amended goal
completes, nothing returns to the first goal. A harness-side *plan-queue
policy* (Model B's queue half, ≈ 60 lines: push the suspended goal, on
terminal receipt of the amendment propose "resume" and re-issue it) returns
to the original goal in ≥ 0.9 of episodes where both goals are reachable,
with no more than +0.15 relative path length over the two goals done in
sequence from rest.

**H-NI1c (keep vs revise vs queue is decidable from the utterance + state).**
A deterministic classifier over (utterance intent class, whether the new
goal conflicts with the current one, distance already travelled) chooses
{revise, keep, queue} matching an authored gold label on ≥ 0.9 of a 60-case
authored set (20 per class), where "keep" = the utterance is not a
navigation command or is a confirmation, "queue" = "after that / when
you're done / then", "revise" = otherwise.

## Scenario tier (ADDITIVE; never touches v1–v4)

`interrupt_tier_v1.json`: 40 episodes on the static city, each = (start pose,
goal 1, goal 2, interruption trigger = fraction of goal-1 path {0.25, 0.5,
0.75} or a time), phrasing drawn from the e2e's accepted vocabulary
("go to the lamppost", "go to the sidewalk", "come here", …) plus a
"queue" phrasing family ("after that, …"). Goals chosen from the scene
landmarks already reachable in the e2e (lamppost, sidewalk, bench, owner),
never from the held-out scene. Paired from-rest controls for every goal.

## Measurements

- admission latency (utterance → executive suspend/replace receipt), ms;
- amended-goal success (system + scorer authority, both recorded as in the
  e2e's differential-authority instrument), SPL, DTG, collisions, false
  arrivals; from-rest control rows;
- queue return rate and path-length ratio (H-NI1b);
- classifier accuracy per class (H-NI1c);
- every episode's `track` (1 Hz polyline) and task-record timeline saved.

## Success criteria

a: admission ≥ 0.8, Δsuccess ≥ −0.10, 0 collisions / false arrivals in the
switch window. b: return ≥ 0.9, path ratio ≤ 1.15. c: ≥ 0.9 per class.

## What it does NOT prove

Nothing about spoken audio (commands are text through `handle_text`, as in
the e2e), the hosted voice, or a real robot; the scene is the demo city.

## OWNS / must not touch

OWNS `research/20260829/nav-interrupt-1/**`. Reads `tests/test_voice_nav_e2e.py`
(copy its `_LiveRuntime` pattern into the harness; do not import the test),
`src/parcel_robot/brain/executive.py`, `voice/amendment.py`, `runtime.py`
(read-only). Sims on a unique socket under `systemd-run … MemoryMax=12G`,
`TMPDIR` unset, `PARCEL_MEMORY_PATH` → scratch. No product edits; no
frozen-set edits.

## Reproduction

`.parcel/bin/python research/20260829/nav-interrupt-1/run.py --all --seed 20260829`
→ `results.json`; RESULTS.md from those numbers only.
