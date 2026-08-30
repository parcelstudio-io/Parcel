# NAV-INT-1 — RESULTS

Executor: Opus, 2026-08-29. Pre-registration: `DESIGN.md` (frozen, Fable).

**`AMENDMENTS.md` existed and every amendment in it is applied.** It appeared
POST-START (N1–N4 at 15:41, N5–N11 at ~16:05), after the harness was begun and
before any headline row was measured; the file was re-read before each stage.
Applied: **N1** (re-issue, not resume), **N2** (admission-at-any-poll),
**N3** (sim hygiene + `pgrep` proof), **N4** (name scan), **N5** (two admission
paths split ≥ 12 each + a HOLD row), **N6** (switch-window instrumentation +
detectability bound), **N7** (H-NI1c scored on the verifier's blind set),
**N8** (Wilson CIs + oracle path reference), **N9** (queue policy is
PRE-runtime), **N10** (additive tier record, `frozen_baseline: false`),
**N11** (own socket, HY-1 guard verbatim, own spend ledger). The one part of
N10 **not** done is the optional "≥ 10 dynamic-city episodes if time allows" —
there was no time; every row here is static-city.

Evidence tier: **`desktop-sim`**. Every row comes from the live
`RobotRuntime.handle_text` product path against the MuJoCo static city — the
same chain as `tests/test_voice_nav_e2e.py::_LiveRuntime`, copied into
`harness.py` rather than imported. `use_llm=False`; reasoner **"none (the
local sketch lane)"** — `agent.last_reasoning_source == "local_plan_sketch"`
on every admitted utterance, no LLM planner. **No hosted call, $0.00.** Proof:
`PARCEL_REALTIME_SPEND_LEDGER` was pointed at
`~/.cache/parcel-0e/wave20260829/spend.jsonl` (N11) and the owner's
`recordings/spend.jsonl` mtime is unchanged at 2026-08-26 21:31.
Physical motion: **NO-GO**.

> A missed criterion is a finding, written down. Nothing here moves a bar
> `DESIGN.md` set.

---

## Stage 0 — the harness, and the mechanism the first live episode exposed

`harness.py` copies the e2e `_LiveRuntime` (sim subprocess on a unique short
socket, `PARCEL_MEMORY_PATH` → scratch, commissioned config, `build_runtime`,
`runtime.start()`, `tasks()`/`pose()` polling, HY-1's teardown guard verbatim
— `start_new_session`, `killpg` only after confirming the group leads itself,
`try/except BaseException` around `build_runtime`). It adds three things:

1. **A 50 Hz sampler thread.** `TaskExecutive.snapshot()` rows carry no
   timestamps, so the only way to time a suspend/replace receipt is to observe
   the transition. The sampler is also the source of the pose track, the pace
   track, the simulator's `collision` flag, `nearest_obstacle_m`, and the
   receipt timeline. (N6 asks for ≥ 10 Hz in the switch window; the sampler
   runs at 50 Hz for the whole episode.)
2. **The interruption scheduler** (`wait_for_trigger`): fire the second
   utterance when displacement from the start pose reaches a fraction of the
   straight-line distance to goal 1's reference point, or after a wall clock.
3. **The differential arrival authority**, copied from the e2e: the system's
   claim and the independent K0 predicate on the final pose, both recorded
   unconditionally, with their `AuthorityCategory`.

**Mechanism finding (corroborates N1).** The shipped stack answers a mid-task
navigation amendment with `TaskExecutive.replace()`: the task id does not
change, the *plan revision* is bumped, and the suspended state exists only
inside `runtime._apply_goal_amend`'s transaction — it is never observable from
outside. `_close_amendment_window("committed")` then CONSUMES the parked
`ResumeIntent`. Receipt timeline of the first live episode ("go to the
sidewalk", then at 50 % progress "actually, go to the lamppost"):

```
   0.10  parcel-task-0f7f3844d501 r1       None -> running    NavigateTo :: dispatched
  13.63  parcel-task-0f7f3844d501 r2       None -> running    NavigateTo :: dispatched
  27.55  parcel-task-0f7f3844d501 r2    running -> succeeded  None :: navigation_goal_verified
```

Admission receipt at **43 ms**. Nothing returned to the sidewalk. So the
harness accepts three observable receipt shapes — `replace` (higher plan
revision on a known task), `suspend`, `new_task` — and the plan queue is
precisely the thing the stack does not have. A second, unrelated observation
of the same kind: **task ids are not unique per plan** on this stack (the same
`parcel-task-0f7f38…` id appears in unrelated episodes), so a harness that
identifies "the new goal's task" by a new id sees nothing. The plan revision
is the discriminator.

`sample_episode.txt` carries one full episode in this form.

---

## Stage 1 — from-rest controls (the paired baseline)

`controls.jsonl`, 2 reps per distinct goal, fresh sim per run.

| goal | from-rest success (system ∧ scorer) | authority category | DTG | mean SPL |
|---|---|---|---|---|
| `go to the sidewalk` | 2/2 | `agreement` | 0.00 m | 0.766 |
| `go to the lamppost` | 2/2 | `agreement` | 0.00 m | 0.464 |
| `walk towards the lamppost` | 2/2 | `agreement` | 0.00 m | 0.956 |
| `come here` (owner) | 2/2 | `agreement` | 0.23 m (K0 disc) | 1.000 |
| `go to the bench` | **0/2** | `authority_disagreement` | 0.00 m | 0.000 |

**Finding — `go to the bench` does not verify, 2/2, from rest.** Both reps
ended `failed` with `last_detail = semantic_arrival_verification_failed` after
~37–39 s, at (−0.679, 2.278) — a pose the independent K0 near-band predicate
scores as **arrived, DTG 0.000 m**. That is an `authority_disagreement`: the
robot is where the scorer says the goal is and the system will not certify it.
This is the same defect class the e2e pins as "must never recur" for the
**lamppost** near band (`test_go_to_the_lamppost_grounds_plans_and_arrives`);
the e2e has no plain "go to the bench" case, so it has never been exercised
there. It is not an interruption defect — it reproduces from rest — but it
sets the paired baseline for every bench episode in the tier to 0, which is
exactly why DESIGN pre-registered a **paired** comparison.

**The authority-disagreement class is tallied as its own row (Fable, 16:2x).**
"System failed but the K0 predicate says arrived" and "system succeeded but
the predicate says not arrived" are the NAV-QUALITY authority-disagreement
class (22 rows in the frozen matrix) — a product terminal-verification
behaviour, not an interruption or queue-policy effect: it reproduces from
rest. `results.json → authority_disagreement` counts it per goal over EVERY
scored leg this experiment ran (from-rest controls, the leg after the
interruption, the re-issue leg), so nothing under test is charged for it. The
differential-authority category is kept on every goal regardless.

**Instrument correction, made before the tier ran.** The first pass scored the
owner-approach goals against the frozen K0 `owner_anchored_goal_region` disc
alone and got `false_arrival` twice (DTG 0.219 / 0.228 m). That is the
instrument, not the robot: the e2e's **hard** gate for an approach is
`evaluate_owner_arrival` with the band taken from the follow controller's own
declared formation distance (`0.4 … desired + 0.6`), and it records the K0 disc
verdict softly alongside. `harness.owner_arrival` now copies that, the owner
rows are scored on the e2e's gate with the disc verdict kept beside them, and
the owner controls were re-measured after the tier under the corrected
instrument. Scoring an approach on the disc alone reports a false arrival on a
correct approach — worth stating plainly, because it would have put two
spurious false arrivals into an H-NI1a criterion whose bar is zero.

---

## Stage 2 — the from-rest sequence controls

`sequence_controls.jsonl`. This stage was **cut short at 5 of 10** so the
40-episode tier could start inside the time budget, once amendment N8 made the
**oracle** path (start → interruption pose → goal 2 → goal 1, straight line
from the actual interruption pose) the primary H-NI1b reference. The five
measured rows are reported as a secondary, weaker reference and are labelled
as such in `results.json` (`path_ratio_vs_measured_sequence_mean`,
`n_path_ratio_measured`). All five ended `both_reached = False`, every one of
them because a bench leg did not verify — the Stage 1 finding again.

---

## Stage 3 — the 40-episode interrupt tier

*(numbers below are read from `results.json`; see `episodes.jsonl` for every
episode's 1 Hz track, full receipt timeline and queue log)*

---

## Stage 4 — H-NI1c, the steering classifier

**The bar is read on the verifier's blind set only (amendment N7).**
`gold_blind.json`, 110 cases (40 adversarial), sha256
`c253df2f707b158c4f6aaab42ce9fae77e98aae9502ef4bea987e2bae1fc1e65`, verified
byte-identical to `gold_blind.sha256` at scoring time. The classifier
(`queue_policy.classify`) was written before that file was opened.

### Result — criterion MISSED on two of four classes

| class | n | accuracy | Wilson 95 % | bar 0.90 |
|---|---|---|---|---|
| revise | 30 | **0.900** | [0.744, 0.965] | met (exactly) |
| keep | 30 | **0.933** | [0.787, 0.982] | met |
| queue | 30 | **0.667** | [0.488, 0.808] | **MISSED** |
| clarify | 20 | **0.800** | [0.584, 0.919] | **MISSED** |
| overall | 110 | **0.827** | [0.746, 0.887] | — |

Adversarial subset 0.675 (40 cases); non-adversarial 0.914 (70 cases).

Confusion (rows = gold, columns = predicted):

```
           revise     keep    queue  clarify
  revise       27        3        0        0
    keep        0       28        0        2
   queue        0        9       20        1
 clarify        0        4        0       16
```

**Every error is one shape: the classifier under-fires and falls back to
`keep`** (16 of 19 misses). It has no false `revise`, which is the safe
direction — it never invents a goal change nobody asked for. The named gaps:

* **queue paraphrases the cue set never had** — "once you get there, head to
  the bench", "after the lamppost, the bench", "next, the planter", "later, go
  to the bench", "do the tree after", "when you reach it, come back". 9 of the
  10 queue misses.
* **amendment cues the shipped `_GOAL_AMEND` regex does not carry** —
  "scratch that, sidewalk", "forget the sidewalk, go to the bench", "hold on,
  go to the planter". All 3 revise misses. Note these are the *product's* own
  grammar: the runtime would not admit them as amendments either, so this is a
  finding about the shipped cue set as much as about the classifier.
* **deictic targets read as non-commands** — "go back", "go there", "go over
  there", "go back to the sofa and check if I left my keys" should ask; the
  classifier said `keep`. 4 clarify misses.
* **"no worries, continue" / "no, keep going"** — the shipped `no[, ]` amend
  regex fires on "no worries", and the classifier then looked for a goal in
  the residual instead of noticing the residual asks for no change. 2 keep
  misses.

### The dev set, and why its 100 % means nothing

`gold.json` is the executor's own 60-case set (20 revise / 20 keep / 20 queue
under DESIGN's definitions) plus 20 supplementary `clarify` and 10
supplementary context cases. The frozen classifier scores **60/60, 20/20,
10/10** on it. That is a *specification-consistency* check, not evidence: the
same author wrote the rules and the cases. It is reported for transparency and
**no bar reads on it**. The gap between 100 % on the author's own set and
82.7 % on the verifier's is the honest measure of that difference, and is the
strongest single argument in this file for amendment N7.

### `classify_v2` — POST-HOC, reported separately

Written after the blind run's error analysis, fixing the four named gaps
(extra queue cue paraphrases, an "after the ⟨landmark⟩" cue, extra amendment
cues, a residual-is-a-non-goal-intent rule, and a deictic-target → clarify
rule). On the same 110 cases: **overall 0.973**, revise 1.000, keep 0.933,
queue 0.967, clarify 1.000; adversarial subset 0.925.

**This is not a blind measurement and the H-NI1c criterion is not read on it.**
Three errors remain: "and after that come here" (the leading "and" survives
cue-stripping), and "go on" / "go go go" (encouragement shaped like a motion
imperative). They are left unfixed deliberately — a fourth iteration against a
set I have now seen four times would be fitting, not generalisation.

### What the context features do, and do not, do

`conflict` (does the new goal differ from the running one) and `progress`
(distance already travelled) are recorded on every decision but reach the
label in only two narrow, pre-declared places: a bare directive that restates
the running goal → `keep`, and a bare directive at `progress ≥ 0.9` → `queue`.
DESIGN's class definitions are functions of the utterance alone, so neither
feature can move a pre-registered label — a real limitation of the
pre-registration, not of the classifier. The 10 supplementary context cases in
`gold.json` are the only place they are exercised (10/10, and 7/10 with the
progress rule ablated: the three `queue`-at-high-progress cases flip to
`revise`).

---

## Stage 3 (written by the verifier from `results.json`, 19:5x 08-29 — the executor was killed by the account spend limit before writing this section; every number below is machine-copied)

### H-NI1a — single spoken interruption on the shipped stack

Tier: 40 episodes, 0 harness errors; 32 rows where the runtime was actually interrupted (8 `queue` utterances are HELD pre-runtime by design, N9; 4 bare-"actually" HOLD rows).

| measure | value | bar (DESIGN + amendments) | met? |
|---|---|---|---|
| admission (any receipt) | 24/32 = 0.750 [0.58, 0.87] | ≥ 0.8 | **no** (point 0.75; CI includes 0.8) |
| admission within 1.0 s (admitted rows; admission-at-any-poll, N2) | 26/26 = 1.000 [0.87, 1.00] | 1.0 s | yes |
| admission latency p50 / p95 / max (ms) | 12.4 / 22.4 / 28.5 | — | — |
| receipt kinds | {'None': 6, 'new_task': 5, 'replace': 5, 'suspend': 16} | — | — |
| amended-goal success, system AND scorer | 11/28 = 0.393 [0.24, 0.58] | Δ vs from-rest ≥ −0.10 | **no**: from-rest (weighted) 0.75, Δ = -0.3571 |
| amended-goal success, system only / scorer only | 14/28 = 0.500 [0.33, 0.67] / 14/28 = 0.500 [0.33, 0.67] | — | — |
| interruptions refused, goal 1 continued | 7 / 32 | — | — |
| switch window: sim collision flag / clearance ≤ 0 / false arrivals | 0 / 0 / 0 (min clearance 0.83 m) | 0 (n = 40 detects only ≥ 7.5 %) | yes |
| amended-goal final authority categories | {'agreement': 15, 'authority_disagreement': 3, 'false_arrival': 3} | — | 3 false-arrival categories on final scoring |
| mean SPL / DTG of amended goals | 0.254 / 1.26 m | — | — |

Per sub-family (N5):

| family | n | admission | median latency (ms) | amended success (both) |
|---|---|---|---|---|
| amend_cue | 14 | 7/14 = 0.500 [0.27, 0.73] | 8.6 | 4/14 = 0.286 [0.12, 0.55] |
| explicit_directive | 14 | 14/14 = 1.000 [0.78, 1.00] | 13.9 | 7/14 = 0.500 [0.27, 0.73] |
| hold | 4 | 3/4 = 0.750 [0.30, 0.95] | 15.9 | {} |

Per trigger fraction:

| fraction | n | admission | amended success |
|---|---|---|---|
| 0.25 | 8 | 7/8 = 0.875 [0.53, 0.98] | 4/8 = 0.500 [0.22, 0.78] |
| 0.5 | 8 | 5/8 = 0.625 [0.31, 0.86] | 1/8 = 0.125 [0.02, 0.47] |
| 0.75 | 9 | 5/9 = 0.556 [0.27, 0.81] | 2/7 = 0.286 [0.08, 0.64] |
| None | 7 | 7/7 = 1.000 [0.65, 1.00] | 4/5 = 0.800 [0.38, 0.96] |

HOLD rows (bare "actually"): [{"episode_id": "ni1-23-sidewalk-bench", "goal_amend_ok": true, "goal_amend_replan": "waiting_for_goal", "receipt_kind": "suspend", "states_after_hold": ["suspended"], "details_after_hold": ["suspended:goal_amend"], "path_during_hold_m": 0.0}, {"episode_id": "ni1-26-sidewalk-come_here", "goal_amend_ok": true, "goal_amend_replan": "waiting_for_goal", "receipt_kind": "suspend", "states_after_hold": ["suspended"], "details_after_hold": ["suspended:goal_amend"], "path_during_hold_m": 0.043}, {"episode_id": "ni1-30-towards_lamppost-bench", "goal_amend_ok": false, "goal_amend_replan": null, "receipt

### H-NI1b — restoring the original goal (re-issue, N1/N9)

| measure | value | bar | met? |
|---|---|---|---|
| re-issued | 34 | — | — |
| return rate where BOTH goals reachable from rest (system AND scorer) | 8/9 = 0.889 [0.56, 0.98] | ≥ 0.9 | **no** (point 0.889; CI includes 0.9) |
| return rate, all re-issued (system AND scorer / scorer only) | 13/34 = 0.382 [0.24, 0.55] / 15/34 = 0.441 [0.29, 0.61] | — | — |
| re-issue trigger terminal state | {'failed': 10, 'succeeded': 19, 'suspended': 5} (false `failed` triggers: 6) | — | — |
| path ratio vs oracle (N8: start → interruption pose → goal 2 → goal 1) mean / p50 / p95 (n = 8) | 1.490 / 1.305 / 2.253 | ≤ 1.15 | **no** |
| path ratio by trigger fraction | {'0.25': {'n': 2, 'mean': 1.6448}, '0.5': {'n': 2, 'mean': 1.4065}, '0.75': {'n': 1, 'mean': 1.2225}, 'None': {'n': 4, 'mean': 1.533}} | — | — |
| queue-policy actions | {'hold_pre_runtime': 8, 'no_displacement': 9, 'no_reissue': 6, 'reissue': 34, 'revise_observed': 23, 'start_goal': 40} | — | — |
| from-rest sequence controls both reached | 0.0 of 5 | — | the two-goal sequence from rest never completed both legs |

### Authority disagreement (tallied as its own row, per the verifier's instruction)

80 scored legs: agreement 63, system-failed-but-arrived **11**, system-succeeded-but-not-arrived **6**. By goal: bench: failed-but-arrived 11/29; lamppost: failed-but-arrived 0/10; sidewalk: failed-but-arrived 0/17; towards_lamppost: failed-but-arrived 0/17; come_here: failed-but-arrived 0/7. Not an interruption effect — it reproduces from rest (bench 0/2 system, 2/2 scorer).

### H-NI1c on the verifier's blind set (N7) — summary row

Blind (n = 110): 0.827 [0.75, 0.89]; non-adversarial 0.914; adversarial 0.675; per class: revise 27/30, keep 28/30, queue 20/30, clarify 16/20. Post-hoc `classify_v2` 0.973 — reported separately, not the pre-registered number. sha256 of the blind set matches the frozen hash.

---

## Card C7 — the queue-cued re-issue, reproduced at the door and recorded honestly

Written 2026-08-29 22:0x by the C7 executor (`scrum/20260829/task_2/C7_HARNESS_TRUTH.md`).
Nothing above this line is re-measured: `episodes.jsonl`, `results.json`,
`controls.jsonl`, `sequence_controls.jsonl` and `gold_blind.json` are untouched,
and the H-NI1a/b/c numbers stand exactly as recorded. This section adds the
reproduction of the **second live defect** named in `VERDICT_FABLE.md` item 2 —
*"a held queue utterance re-issued verbatim is refused (the cue must be
stripped)"* — and records where the workaround now lives.

### What the product does with a queue cue (RED)

One sim, the same `LiveSession.issue` door every leg of the tier uses, robot at
rest:

| | text that reached `handle_text` | reply | tasks admitted |
|---|---|---|---|
| **RED**, verbatim | `'after that, go to the owner'` | `'I did not understand that command'` | **0** |
| **GREEN**, `strip_cue=True` | `'go to the owner'` | `"Okay—I'll follow you safely."` | **1** |

`navigation_directive_from_text` does not strip a queue cue, so the router never
reaches PlanIR admission at all and answers with the generic parse failure. The
GREEN row carries `raw_text = 'after that, go to the owner'` and `cue_stripped = true`,
so the record shows both the sentence the owner made and the sentence the
product was given.

**A recording gap this exposed, and closed.** `Utterance.metrics["refused"]`
tests for `"couldn't admit"`, the *admission* refusal — so the RED row above
reads `refused: false` on an utterance the product plainly refused. A second
flag `not_understood` was ADDED (never widened, so no recorded number changes
meaning): it reads **true** on the RED row and
**false** on the GREEN one. Tier rows recorded
before this section do not carry the field.

### Where the workaround lives now

The strip was previously inside `PlanQueue.hold_for_later` only — so the one
push path that did *not* strip (`on_interrupt`'s `queue` branch) was a latent
repeat of the same defect, and no leg record carried the spoken form. Now:

* `harness.QUEUE_CUE_RE` / `harness.strip_queue_cue()` own the cue vocabulary,
  at the ISSUE DOOR where the refusal happens. `queue_policy` imports them, so
  the classifier and the door cannot disagree — the H-NI1c blind-set numbers are
  byte-identical after the move (0.8273 overall; revise 0.900 / keep 0.9333 /
  queue 0.6667 / clarify 0.800; non-adversarial 0.9143, adversarial 0.6750) and
  `gold_blind.json`'s sha256 is unchanged (`c253df2f…`).
* `LiveSession.issue(text, *, strip_cue=False)` strips only when asked, records
  `raw_text` and `cue_stripped` on the `Utterance`, and is asked **only by the
  re-issue leg**. A first utterance is never stripped: that would work around
  the admission defect this tier exists to measure.
* Every `Leg` now carries `raw_text` (what was held) and `cue_stripped` beside
  `text` (what reached `handle_text`).
* The re-issue leg issues the queue entry's **spoken** form and lets the door
  strip it, so the pair is visible in the row rather than implied.

### The re-issue row, re-run (`ni1-00-bench-come_here`, family `queue`, 138.7 s)

Queue log:

```
hold_pre_runtime  spoken='after that, go to the owner'  will_issue='go to the owner'
reissue           spoken='after that, go to the owner'  text='go to the owner'  terminal_state='failed'
```

Re-issue leg:

| field | value |
|---|---|
| `raw_text` (held) | `'after that, go to the owner'` |
| `text` (issued) | `'go to the owner'` |
| `cue_stripped` | **true** |
| reply | `"Okay—I'll follow you safely."` |
| `admitted_work` | **true** |
| task states | `['succeeded']` / `['owner_follow_verified']` |
| `system_arrival` / `scorer_arrival` | **false** / **false** (agreement) |
| DTG | 4.515 m |
| SPL | 0.0 |

**The re-issue ADMITS**, which is the bar this card carries: the cue-stripped
directive reaches `handle_text`, a task is created, it goes `succeeded` with
`owner_follow_verified`, and the record shows both the held and the issued form.

**Arrival is not this card's bar and did not reproduce across reps.** The
episode was run twice while the leg record was being completed (`ni1-00-bench-come_here`,
seed 20260829): **2/2 admitted**, but the owner-follow band was held in one rep
(`system_arrival`/`scorer_arrival` both true, DTG 0.228 m, SPL 1.0, 69.6 s) and
not in the other (both false, DTG 4.515 m, follow state `following`, 138.7 s —
the table above). `come_here` is an owner-anchored approach whose terminal is the
formation band HELD, and H-NI1b already records the re-issue return rate as
13/34 = 0.382 across the tier. Nothing here re-measures that: this is one episode
of the queue family at one seed, run to check the door, and the 40-episode tier
was **not** re-run (2–2.5 h with five peer executors on the host). Every rate
above stays as recorded. Raw rows for this check are in the C7 executor's scratch
(`~/.cache/parcel-0e/c7/ni1_door_red_green.json`,
`~/.cache/parcel-0e/c7/ni1_reissue_rows.jsonl`).

### What is still C6's, not this card's

The FIRST live defect — an owner-referring amendment suspends goal 1 and cannot
admit the replacement, parking the robot — is untouched here. The harness
records it; it is not worked around.

---

## Card C7-F1 — the scorer follows the executive's committed instance

Written 2026-08-29 23:4x by the C7 executor, after C2's executor found that
sidewalk legs scored `false_arrival` at DTG ~4.98 m while the executive had
committed and verified a **real second instance**. Nothing above this line is
re-measured except where this section says so; `episodes.jsonl`,
`controls.jsonl`, `sequence_controls.jsonl`, `results.json` and
`gold_blind.json` are untouched (sha256 `c253df2f…` re-printed and unchanged).

### The defect

The static city holds two polygons labelled `sidewalk`:

| instance | polygon (frozen eval table) |
|---|---|
| `sidewalk` (north, the generator's tier-A default) | y ∈ [2.4, 3.6] |
| `sidewalk_south` | y ∈ [−3.6, −2.4] |

`GoalSpec.region()` took a `committed` argument and **used it only for
`object_near` goals**. The `region` branch called
`_region_goal(self.plain, tier="A")`, which is hardcoded to the north polygon,
and the `object_towards` branch was hardcoded to `lamp_post_1`. So a leg whose
executive committed `sidewalk_south`, drove there and verified arrival was
scored against a polygon ~4.98 m away and came out `false_arrival` —
**the harness inventing a disagreement the robot did not have.**

### The fix

`GoalSpec.region_with_provenance(committed=…)` replaces the hardcoded lookup for
**every** non-owner kind, under the same-label tie-break documented in
`README.md` (`committed_instance` / `default_instance` /
`default_instance_label_mismatch`). Two properties keep it honest:

* **a committed instance is scored only if it carries the goal's own label** —
  otherwise the default is scored and the mismatch is flagged, because scoring a
  wrong-instance arrival against its own choice would let every such arrival
  pass;
* **the landmark table is pinned per goal kind** — region and `towards` goals
  keep the generator's frozen `_LANDMARKS`, `near` goals keep
  `derived_landmark_table()`, exactly as the recorded tier scored them. The two
  tables disagree (north sidewalk [2.4, 3.6] vs [2.2, 4.2]; bench radius 0.700
  vs 0.734), and unifying them would move recorded numbers for a reason that has
  nothing to do with this defect.

Every leg now records `region_provenance`: the raw committed id, the instance
scored, the table it came from, the sibling same-label instances, and the rule
that fired.

### Re-scored offline — every recorded leg, old scorer vs new

The fix is a pure function of (goal, end pose, `system_arrival`, committed id),
all of which the recorded rows already carry, so all **82 non-owner legs** in
`controls.jsonl` + `sequence_controls.jsonl` + `episodes.jsonl` were re-scored
without a simulator:

| authority category | before | after |
|---|---|---|
| `agreement` | 63 | **69** |
| `false_arrival` | **6** | **0** |
| `authority_disagreement` | 13 | 13 |

Sidewalk legs only (n = 18): `false_arrival` **6 → 0**,
`agreement` 12 → 18.

All six flips are the same shape — the executive committed `sidewalk_south`,
the body stood in it, and the new scorer agrees:

| leg | committed | old | new |
|---|---|---|---|
| `ni1-09-bench-sidewalk`:`amended_goal` | `sidewalk_south` | false_arrival (DTG 4.981 m) | **agreement** (DTG 0.0 m) |
| `ni1-10-bench-sidewalk`:`amended_goal` | `sidewalk_south` | false_arrival (DTG 4.982 m) | **agreement** (DTG 0.0 m) |
| `ni1-11-bench-sidewalk`:`reissue` | `sidewalk_south` | false_arrival (DTG 4.981 m) | **agreement** (DTG 0.0 m) |
| `ni1-20-sidewalk-bench`:`reissue` | `sidewalk_south` | false_arrival (DTG 4.984 m) | **agreement** (DTG 0.0 m) |
| `ni1-36-towards_lamppost-sidewalk`:`amended_goal` | `sidewalk_south` | false_arrival (DTG 4.978 m) | **agreement** (DTG 0.0 m) |
| `ni1-37-towards_lamppost-sidewalk`:`reissue` | `sidewalk_south` | false_arrival (DTG 4.975 m) | **agreement** (DTG 0.0 m) |

**One further leg moves, and it is not a sidewalk leg.**
`ni1-29-towards_lamppost-bench`'s re-issue committed `lamp_post_2` while the
`object_towards` branch was hardcoded to `lamp_post_1`: its DTG goes 0.310 →
8.261 m. The category is `agreement` before and after (the system said not
arrived and so does the scorer), so no rate moves — but the old 0.310 m was
distance to a lamppost the robot had not been sent to, and it is corrected here
rather than left standing.

Three further legs differ by ≤ 0.001 m. That is **not** the fix: the recorded
rows store `end` rounded to 3 dp while their DTG was computed from the
full-precision pose, so an offline re-score from the stored pose lands a
millimetre away. No category and no bar is affected.

### Re-run live — the six legs that commit `sidewalk_south`

The from-rest sidewalk controls only ever commit the **default** (north)
instance, so they cannot exercise the fix at all; the faithful subset is the six
tier episodes whose sidewalk leg commits `sidewalk_south` (tier offsets 9, 10,
11, 20, 36, 37). Run from a pinned scratch export of the tier
(sha256 `23466d5f…`, byte-identical to `interrupt_tier_v1.json`), on this card's
own socket root `~/.cache/parcel-0e/c7/ni1f1/`, `PARCEL_MEMORY_PATH` into the
same scratch, each sim under `systemd-run --user --scope -p MemoryMax=12G -p
MemorySwapMax=0` and torn down by `run.Sessions`; output to
`~/.cache/parcel-0e/c7/f1_sidewalk_legs.jsonl`, never the recorded
`episodes.jsonl`.

| episode | leg | committed | scored | rule | system / scorer | category | DTG (m) |
|---|---|---|---|---|---|---|---|
| `ni1-09-bench-sidewalk` | `amended_goal` | `sidewalk_south` | `sidewalk_south` | `committed_instance` | true / true | **agreement** | 0.0 |
| `ni1-10-bench-sidewalk` | `amended_goal` | `sidewalk_south` | `sidewalk_south` | `committed_instance` | true / true | **agreement** | 0.0 |
| `ni1-11-bench-sidewalk` | `reissue` | `sidewalk_south` | `sidewalk_south` | `committed_instance` | true / true | **agreement** | 0.0 |
| `ni1-20-sidewalk-bench` | `reissue` | `sidewalk_south` | `sidewalk_south` | `committed_instance` | true / true | **agreement** | 0.0 |
| `ni1-36-towards_lamppost-sidewalk` | `amended_goal` | `sidewalk_south` | `sidewalk_south` | `committed_instance` | true / true | **agreement** | 0.0 |
| `ni1-37-towards_lamppost-sidewalk` | `reissue` | `sidewalk_south` | `sidewalk_south` | `committed_instance` | true / true | **agreement** | 0.0 |

Live result on the sidewalk legs: {'agreement': 6} — **`false_arrival` on these
legs goes 6 → 0**, and every row names the polygon it was scored
against.

### What this does NOT change

H-NI1a (admission), H-NI1b (return rate, path ratio) and H-NI1c (the blind
classifier) are all unchanged: the classifier was not touched
(`gold_blind.json` sha256 `c253df2f…`), and admission/return are counted from
task receipts, not from the arrival region. What moves is the
**authority-disagreement tally**, and only its `false_arrival` half — the
13 `authority_disagreement` legs (11 bench system-failed-but-arrived, plus
others) are untouched by this fix and remain a product finding.
