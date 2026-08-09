# P — the yield policy: what the dog does when a person is in its way · status

**Date:** 2026-08-08 · **Cards:** P-1 (design + implement), P-2 (tests),
P-3 (measure the traffic case end-to-end), P-4 (docs + backlog).
**Owner directive, verbatim:** "When the robot determines there is a person in
scene, that should be a personality decision. By default let the robot ask for
help but make sure that this personality is configurable."
**Entry state:** default suite 2777 passed / 0 failed (2026-08-07 F-1 record);
the traffic case xfail with the person-on-the-approach-pose measurement.

**The one-line claim:** the yield decision now exists, it is per-personality
config with fail-closed validation, it never touches a gate — and the **first
live run of it found a defect no unit test would have**: the person gate
*chatters* in a pedestrian stream, so a per-episode ask budget re-armed
forever. Measured: **13 asks in 240 s and no honest end.** The two scopes were
separated and re-measured, and the traffic case now ends at **54.0–54.2 s (n=3)
with `last_detail='blocked_by_person_unanswered'` after exactly two spoken
asks**, instead of 240 s of `step_timeout`. It still does not pass, and the K0
predicate moved the *wrong* way — both stated below.

---

## P-1 — the policy, as landed

### Shape

```yaml
personality.yield_policy:
  patience_s:        <float>   # how long an EPISODE must persist before acting
  on_blocked:        ask_for_help | wait | give_up_honestly
  reask_interval_s:  <float>   # between asks, and between last ask and give-up
  max_asks:          <int>     # PER MISSION; 0 ⇒ behaves as give_up_honestly
  release_grace_s:   <float>   # gate must stay open this long to end an episode
personality.yield_speech:
  ask / reask / give_up:       # templates, {place} is the only substitution
```

`release_grace_s` is the one knob the card did not name. It is not a design
instinct — it is the measured fix for P-3's first result, and `0.0` restores
the strict continuous-blockage rule the card described. See "the chattering
gate" below.

### Defaults

| personality | `patience_s` | `on_blocked` | `reask_interval_s` | `max_asks` | `release_grace_s` |
|---|---|---|---|---|---|
| `gentle_companion` (shipped) | 8.0 | **`ask_for_help`** | 12.0 | 2 | 3.0 |
| `calm_guardian` | 12.0 | `ask_for_help` | 20.0 | 1 | 4.0 |
| `playful_companion` | 5.0 | `ask_for_help` | 8.0 | 3 | 2.0 |

`on_blocked = ask_for_help` everywhere, by the owner's explicit instruction,
pinned by `test_the_shipped_config_keeps_ask_for_help_as_every_personality_default`.

### The signal already existed; nothing was invented and nothing navigation-side was edited

`apply_collision_brake` returns `"person_stop"` (`navigation/collision.py:107`)
and `DirectiveNavigator.step` composes it into `MidLevelCommand.note` as
`f"{cmd.note}|{cnote}"` (`navigation/pipeline.py:745`), producing exactly the
string the 2026-08-07 record measured:

```
grid_track err=0.0 goal=0.2 route=2 status=planned|person_stop
```

The runtime already sees it once per control tick at
`_step_navigation`'s non-terminal branch, where it is written to
`_navigation_detail["reason"]`. That is where the policy attaches. **A gated
tick is `stop=False`** (`pipeline.py:748-749`), which is why it lands in that
branch at all.

`person_blocked_from_note` matches the `person_stop` **segment** exactly.
Ten other notes in the live vocabulary — including `obstacle_stop`,
`obstacle_slow`, `person_slow`, `obstacle_projected_speed_cap`,
`pose_lost_hold`, `navigation_no_progress` — are pinned as non-triggers.
`obstacle_stop` is the other executor's `_gate_blocked_route_recovery` case and
must never route here; that recovery already excludes `person_stop`, and this
policy is its mirror image.

### Where it lives

| piece | file |
|---|---|
| policy / tracker / templates / loader (pure, no clock, no I/O) | `src/parcel_robot/core/yield_policy.py` (new) |
| DialogueAct binding | `src/parcel_robot/voice/yield_speech.py` (new) |
| per-personality values | `configs/personality.yaml` (new) + packaged copy |
| the seam | `runtime._step_navigation` → `runtime._act_on_yield_decision` |

The decision is taken **under** `_lock` and acted on **outside** it — the exact
shape `_announce_pose_health` uses, and for the same reason (`_brain_vocalize`
takes the lock).

### Why the config is a new file

`configs/robot.yaml` is hash-locked by
`evals/companion/embodied_plan_v1/manifest.json`
(`locked_inputs.robot_config`, sha256 `f64688874525f20d…`). **Verified before
editing anything**: the working tree's `configs/robot.yaml` still hashes to
that value, and it is untouched by this card. The policy therefore lives in a
sibling `configs/personality.yaml`, resolved through `paths.resolve_asset`,
with `agent.personality_policy: <path>` available to derived configs. The
active personality id still comes from `configs/robot.yaml agent.personality`.

Absence and corruption are answered differently on purpose: a tree without the
file gets the documented built-in defaults (the policy only decides how long to
wait and what to say, so a missing file must not take the runtime down), while
a file that exists and is malformed **raises**.

### What it never does

The policy is downstream of every gate. It never sees, proposes, or relaxes a
velocity, and never reads `person_stop_m` / `obstacle_stop_m` / TTC / the
collision brake. `test_a_gated_tick_still_commands_zero_under_every_policy`
runs the whole runtime under all three `on_blocked` values and asserts every
recorded backend command is `vx == vy == 0.0` while the gate is closed.

---

## The chattering gate — the defect the first live run found

The unit tests all passed. The first instrumented traffic run did this:

| seed | asks spoken | terminal | elapsed |
|---|---|---|---|
| 1 | **13** | `failed` / `step_timeout` | 240.2 s |
| 2 | **13** | `failed` / `step_timeout` | 240.2 s |
| 3 | (aborted at startup, see the P-3 table) | — | — |

Thirteen identical sentences and no honest end — a direct violation of the
card's requirement (b) ("edge-triggered and rate-limited, no repeat spam") and
of "after `max_asks` it fails honestly".

**Root cause.** The traffic case is not one parked pedestrian; it is a
*stream*. `person_stop` closes and re-opens with roughly one-second gaps for
the whole run (first person-stop at 11.5 s; ~180 s of the 240 s spent inside
the gate, in fragments). Both the patience clock and the ask budget were
per-episode, so every brief release refunded both — the ask re-armed
indefinitely and `max_asks` was never reached. It also explains why the first
ask arrived at 56.6 s rather than at 11.5 + 8 = 19.5 s: 45 s of that delay was
the gate resetting the patience clock, not the situation changing.

**Fix — two scopes, not one.**

* the **episode** (`patience_s`) survives gate releases shorter than
  `release_grace_s`, so patience measures how long the situation has persisted
  rather than how chatty the gate is;
* the **ask budget** (`max_asks`, `reask_interval_s`) is per **mission** and is
  not refunded by a flicker.

Either half alone is insufficient and both are pinned:
`test_a_chattering_gate_still_produces_exactly_max_asks_and_one_give_up`,
`test_the_ask_budget_is_per_mission_and_is_never_refunded`, and the negative
control `test_release_grace_is_what_makes_patience_mean_something_in_traffic`
— which shows that on a gate whose individual blockages are shorter than
`patience_s`, the strict rule (`release_grace_s: 0.0`) is completely **inert**:
the dog stands still for four minutes and never says a word.

---

## The words, and the truthfulness contract

The runtime holds **no yield vocabulary**. Templates are per personality in
`configs/personality.yaml`; `{place}` is the only substitution and any other
placeholder is a startup error.

What a person-gate tick proves is exactly two things, and the act carries
exactly those two, each as `DialogueClaimV1(veracity="verified",
evidence_ref="navigation:person_stop")`:

```
"A person is inside my stop distance."
"I stopped and did not move past them."
```

`FORBIDDEN_ARRIVAL_PHRASES` refuses any authored line containing an arrival or
completion claim, **at config load time**, and the check is re-run after
`{place}` substitution because a goal label is scene data rather than authored
text. Every shipped line × every personality × all three kinds is asserted
clean.

**This is the first production path in the repo that puts a backed claim on a
`DialogueActV1`.** `agent.py`'s conversation act — the only other builder —
ships an empty `claims` tuple, so the veracity/evidence rules at
`contracts/v1.py:958-960` had never been exercised on a live path.

---

## The honest end, and one collateral defect

`_act_on_yield_decision` ends the mission through `_stop_navigation_channel`
with `state="failed"` and an attributable `reason` (`blocked_by_person` or
`blocked_by_person_unanswered`). `_stop_navigation_channel` gained
`reason=` / `state=` keywords: without them the give-up would have to stop
first and correct the detail afterwards, and the executive polls between those
two writes — it would read `navigation_disabled` and attribute the failure to
nothing.

**Collateral defect, found while proving the reason reached the plan record.**
`TaskExecutive.report` recorded `result.feedback_code` as the failed step's
`last_detail`. For a failed result that code is the constant `"failed"`
(`runtime_adapter._failed_result:864`), so the field wrote the state down twice
and discarded the adapter's attribution — and `last_detail` is the **only**
attribution field the task snapshot carries. It now prefers `detail_code`,
which is where the verifier put the reason. The cancellation arm one line above
already did exactly this. Effect: every honest navigation reason
(`semantic_target_unreachable`, `navigation_no_progress`,
`blocked_by_person_unanswered`, …) is now visible to anything reading a task
record; before, they were all `"failed"`.

---

## P-2 — tests

`tests/test_yield_policy.py`, **81 cases**, four layers:

| layer | what it pins |
|---|---|
| the signal | the measured traffic note fires; 10 other live notes do not; exact-segment not substring matching |
| the policy object | `ask_for_help` is the default; every knob validated; unknown keys, wrong types, bad enums all fail closed |
| the tracker | patience expiry fires exactly one ask; 300 blocked ticks → 2 asks; re-ask honours the interval; `max_asks` then honest failure one interval later; `wait` holds for 300 s (> the 240 s ceiling); `give_up_honestly` fails fast; `max_asks: 0` degenerates; the chattering-gate cases above |
| the words | every `FORBIDDEN_ARRIVAL_PHRASES` entry is unauthorable; a goal label cannot smuggle one through substitution; every shipped utterance builds a valid act with backed claims; unknown kinds refused |
| the runtime seam | one ask at patience; the act is recorded and backed; after `max_asks` the mission fails with the attributable reason; the **failed step inherits it**; a person who moves on costs nothing; an obstacle block never speaks and never abandons; **`vx == 0.0` under all three policies**; `wait` holds the mission open for 300 s; `give_up_honestly` ends fast; `set_personality` swaps both the numbers and the words; a new mission does not inherit patience |

The runtime-seam cases use the `test_pose_health_announcement.py` harness (one
`RobotRuntime`, a deterministic backend, `_step_navigation` driven by hand)
with an injected `_yield_clock`, so timing is exact and no test sleeps.

---

## P-3 — the traffic case, measured end-to-end

Instrumented scratch runner (sim subprocess + `build_runtime` + `handle_text`,
dynamic city, `configs/robot.yaml`), n=3 seeds per configuration. **The e2e
file was not edited.**

### Before this card (2026-08-07 record, for reference)

3/3 fail at 242.4 / 243.4 / 240.3 s, `step_timeout`, robot inside the polygon
at K0 distance 0.000 m, ~200 ticks of `planned|person_stop`.

### First run under the new default (the defect)

| seed | ask fired | first ask | asks | terminal | detail | end pose | K0 | inside |
|---|---|---|---|---|---|---|---|---|
| 1 | yes | 56.60 s | **13** | `failed` | `step_timeout` | (1.594, 2.474) | 0.000 m | yes |
| 2 | yes | 56.6 s | **13** | `failed` | `step_timeout` | (1.592, 2.471) | 0.000 m | yes |
| 3 | — | — | — | — | — | — | — | — |

Seed 3 of this run aborted at startup, not on the robot: the fix's new
`release_grace_s` key had already landed in `configs/personality.yaml` while
the probe process still held the pre-fix module, and the loader did exactly
what it is supposed to — `ValueError: unknown keys in yield_policy:
['release_grace_s']`. A sequencing mistake on my part, and an unplanned live
demonstration that the config validation is fail-closed rather than
best-effort. Seeds 1 and 2 are the "before" evidence and they agree to 0.1 s.

Spoken (identical every time, `gentle_companion`):

> "Someone is standing right where I need to go, so I've stopped. Could you
> help me get through to sidewalk?"

The `DialogueActV1` recorded on every one:
`acknowledgement_kind="request"`, `asks_clarification=true`, two claims, both
`veracity="verified"` with `evidence_ref="navigation:person_stop"`,
`social_cues=["yield_to_person"]`.

### After the two-scope fix — n=3, and remarkably tight

| seed | ask 1 | re-ask | honest end | asks | terminal | `last_detail` | end pose | K0 | inside |
|---|---|---|---|---|---|---|---|---|---|
| 1 | 24.10 s | 42.15 s | 54.19 s | 2 | `failed` | `blocked_by_person_unanswered` | (1.324, 2.113) | 0.287 m | **no** |
| 2 | 24.09 s | 41.94 s | 53.98 s | 2 | `failed` | `blocked_by_person_unanswered` | (1.325, 2.111) | 0.289 m | **no** |
| 3 | 24.09 s | 42.16 s | 54.20 s | 2 | `failed` | `blocked_by_person_unanswered` | (1.323, 2.109) | 0.291 m | **no** |

Elapsed **54.0 / 54.2 / 54.2 s** against 240.2 s before — a 4.4× reduction, and
the reason now names the cause in **both** the navigation detail and the plan
record's `last_detail` (the latter only because of the executive fix above).

What was said, in order, all three seeds (`gentle_companion`):

> 24.1 s — "Someone is standing right where I need to go, so I've stopped.
> Could you help me get through to sidewalk?"
> 42.1 s — "I'm still waiting — there's someone in my way and I won't push
> past. Could someone help me reach sidewalk?"
> 54.2 s — "I couldn't get to sidewalk. Someone stayed in my way and I stopped
> rather than push past, so I've stopped trying for now."

Ask 1 lands at 24.1 s rather than the arithmetic 11.5 + 8 = 19.5 s because one
gate release early in the run *did* outlast the 3 s grace window and legitimately
restarted the episode. That is the mechanism working, not slipping.

### The trade this makes, stated plainly

**The K0 predicate moved the wrong way.** Under `wait`/before, the robot spent
the full 240 s inching and finished *inside* the scored polygon (K0 0.000 m)
while refusing to claim arrival. Under `ask_for_help` it gives up at ~54 s
**0.29 m short** of the polygon, so `goal.contains(x, y)` is now `False` where
it used to be `True`.

Neither outcome passes the case: arrival was never claimed in either, because
`inside` arrival needs 0.32 m of terminal clearance the robot does not have.
What changed is *which* honest failure you get — an unattributed dead clock at
240 s and 0.000 m, or an attributed, spoken failure at 54 s and 0.291 m. The
card asked for the second. Whether 8 s is the right patience for this scene is
exactly the unswept question in U36; `wait` remains one config line away.

---

## P-3 verdict — the pin

**(b) remain xfail, with a rewritten reason.** Not (a): the robot does not
arrive and does not claim to — `_inside_arrival_goal_region` correctly refuses
`inside` arrival at 0.285 m of terminal clearance against 0.32 m required, and
under the new default the robot now ends 0.29 m outside the polygon as well, so
both of the case's assertions fail. Not (c) either, as a *change to this case*:
the case scores "did you get to the sidewalk", the answer is still no, and
rewriting it to accept an honest refusal would delete the only test that asks
the original question.

What (c) *would* be worth, and is the coordinator's call, is a **new sibling
case** rather than an edit to this one — the honest-yield contract now has
something to assert that it did not have yesterday (a spoken, backed,
non-arrival-claiming request for help, and an attributable terminal reason
within ~60 s). The exact assertions are ready in `tests/test_yield_policy.py`
at the runtime seam; lifting them to the live dynamic city is a coordinator
decision about e2e budget, not a capability gap.

### Exact pin text (drop-in replacement for the `reason=` string)

```
"known failure, RE-MEASURED 2026-08-08 (card P-1/P-3, the blocked-by-a-person "
"yield policy; scrum/20260808/task_4/YIELD_POLICY_STATUS.md) on the product "
"path, n=3 live runs, dynamic city, under the shipped default "
"personality.yield_policy = {patience_s 8.0, on_blocked ask_for_help, "
"reask_interval_s 12.0, max_asks 2, release_grace_s 3.0}. The 2026-08-07 "
"diagnosis is confirmed and the residual it named — 'a yield-vs-deadline "
"product decision, not final-approach geometry' — is now DECIDED, so the "
"failure has changed shape again. Before (n=2 fresh runs on this tree, "
"agreeing with 2026-08-07's n=3): the robot reached (1.59,2.47), INSIDE the "
"scored sidewalk polygon (K0 distance 0.000 m), then held "
"'grid_track err=0.0 goal=0.2 route=2 status=planned|person_stop' until the "
"240 s NavigateTo budget expired at 240.2/240.2 s with "
"last_detail='step_timeout' — a reason that names nothing. Now: the dog says "
"it is blocked and then fails honestly. n=3 at 54.2/54.0/54.2 s, "
"last_detail='blocked_by_person_unanswered' (navigation reason identical), "
"after exactly two spoken asks at ~24.1 s and ~42.1 s and one give-up line at "
"~54.2 s, each carrying a DialogueActV1 whose only claims are 'A person is "
"inside my stop distance' and 'I stopped and did not move past them', both "
"veracity=verified with evidence_ref='navigation:person_stop', and none of "
"which claims arrival. The pin does NOT flip, and the K0 predicate got WORSE, "
"not better: giving up at ~54 s leaves the robot at (1.32,2.11), 0.29 m "
"OUTSIDE the polygon, where waiting out the clock had left it 0.000 m inside. "
"Neither outcome is arrival — 'inside' arrival requires 0.32 m of terminal "
"clearance and the live sidewalk edge affords 0.285 m — so the case scores the "
"same verdict for a better-explained reason and 4.4x less clock. Person-stop "
"is untouched by all of this: every gated tick still commands vx == 0.0 under "
"every policy value (tests/test_yield_policy.py::"
"test_a_gated_tick_still_commands_zero_under_every_policy). Two things would "
"flip it, and neither is a runtime edit: (1) a navigation-side release/"
"re-approach when a person will not clear the committed approach pose "
"(backlog/NEXT.md N20, filed as a hand-off with the exact entry point), or "
"(2) a dynamic-city pedestrian that can actually respond to the ask "
"(backlog/UNVERIFIED.md U35). Setting personality.yield_policy.on_blocked to "
"'wait' reproduces the pre-2026-08-08 behaviour exactly, in one config line."
```

---

## P-4 — docs and backlog

| record | content |
|---|---|
| `docs/YIELD_POLICY.md` (new, indexed in `docs/README.md`) | the policy, the defaults and their provenance, the two scopes and why, the truthfulness rules, the seam, the collateral fix, and what was deliberately not done |
| `backlog/UNVERIFIED.md` U35 | the ask has never been *heard* (`_brain_vocalize` does not reach TTS) and no pedestrian has ever responded to it |
| `backlog/UNVERIFIED.md` U36 | the timings are choices; the sweep that would close them needs no code change |
| `backlog/NEXT.md` N20 | re-plan after a yield give-up — **a hand-off to the navigation executor**, with the two candidate entry points and the reason to prefer one |
| `backlog/NEXT.md` N21 | give every personality a numeric temperament block; `configs/personality.yaml` is now the place for it |

---

## Verification

| check | result |
|---|---|
| `tests/test_yield_policy.py` | **81 passed** |
| targeted regression battery (executive, runtime-brain, runtime, closed intents, pose health, nav admission, contracts, K6 voice lanes, prompting, runtime assets) | **156 passed** |
| **full default suite** `MUJOCO_GL=egl .parcel/bin/python -m pytest tests/ -q` (includes the live `-m slow` e2e block) | **1 failed, 2870 passed, 14 skipped, 3 xfailed, 0 xpassed**, 699.1 s |
| the one red, attributed | `tests/test_owner_and_settle_plans.py::test_the_offer_names_only_relations_the_class_actually_affords` — **another lane's in-flight edit, proven below** |
| re-run of that file after the other lane landed its fix | **49 passed** |
| final `-m "not slow"` sweep on the current tree | **2855 passed, 0 failed** |
| `ruff check` on every file this card touched | **clean** |
| `configs/robot.yaml` sha256 vs `embodied_plan_v1` lock | `f64688874525f20d…` — **unchanged**, verified before and after |
| `git status` on `evals/companion/embodied_plan_v1/`, `evals/companion_nav/` | **empty** — no frozen row moved, nothing under `evals/` written by this card |
| packaged asset parity | `configs/personality.yaml` and `runtime_assets/configs/personality.yaml` byte-identical |

### Attributing the one red — it is not this card's

The assertion is `"sit next to it" in clarification_for("befriend the bench")`,
and it fails because **`bench` no longer affords `next_to`**:
`configs/scenes/city_block.semantics.yaml` (mtime 23:52) now reads
`affordances: [near, towards]` with an in-file comment naming
`scrum/20260808/task_3/BENCH_PLACEMENT_STATUS.md` card B-2 — that is the
scene/K0 decision the 2026-08-07 F-1 record left open, taken by another lane
today. The code path is `voice/scene_reference.py` (mtime **08-07 20:21** —
untouched by this card; the only file this card added to `voice/` is
`yield_speech.py`) reading scene affordances. Nothing in it touches the yield
policy, the runtime navigation seam, or the executive.

Confirming rather than arguing: `tests/test_owner_and_settle_plans.py` was
itself rewritten at **00:13**, *after* this suite run began, and re-running the
file on the current tree gives **49 passed**. The red was a mid-flight window
in another lane, and it has already closed.

---

## Non-claims

1. **Nothing has ever heard the ask.** `_brain_vocalize` writes chat + the
   event log and does not reach TTS. That is a pre-existing property of the
   `Vocalize` path, recorded as U35, not something this card introduced.
2. **No pedestrian has ever responded.** The dynamic city's agents walk a
   script. Every measured run therefore ends in the honest failure; the
   *social* value of asking is entirely unmeasured. What is measured is that
   the robot stops burning four minutes to say nothing.
3. **The timings are choices, not measurements**, with one exception:
   `release_grace_s = 3.0` is derived from the observed ~1 s gaps in the
   dynamic city's `person_stop` stream. Everything else is bounded by measured
   things but unswept (U36).
4. **The policy does not find another way.** It ends the mission; it does not
   release the candidate and re-approach. That is a navigation-side release
   authority and a hand-off (N20), not an edit this card owns.
5. **The `release_grace_s` window is a heuristic about which silence means
   "the way is open".** It is right when the gate is chattering around a
   stationary obstruction and merely conservative when the robot really did
   get through — in the latter case the mission ends by arriving anyway.
6. **`obstacle_stop` exclusion is proved by construction and by ten pinned
   non-triggers**, not by a live obstacle run under this policy.

---

## Files touched

| file | change |
|---|---|
| `src/parcel_robot/core/yield_policy.py` | **new** — `YieldPolicy`, `YieldSpeech`, `YieldTracker`, `PersonalityPolicyConfig`, `person_blocked_from_note`, `assert_truthful_yield_text` |
| `src/parcel_robot/voice/yield_speech.py` | **new** — `yield_dialogue_act`, `yield_claims` |
| `configs/personality.yaml` | **new** — per-personality yield policy + speech |
| `src/parcel_robot/runtime_assets/configs/personality.yaml` | **new** — packaged copy, byte-identical |
| `src/parcel_robot/runtime.py` | tracker + profile state; `_load_personality_policy`, `_install_yield_profile`, `yield_policy_snapshot`, `_act_on_yield_decision`; the `_step_navigation` observation; `_stop_navigation_channel(reason=, state=)`; per-mission reset; `set_personality` re-install |
| `src/parcel_robot/brain/executive.py` | failed steps record `detail_code`, not the constant `feedback_code` |
| `tests/test_yield_policy.py` | **new**, 81 cases (4 layers: the signal, the policy object, the tracker, the words, the runtime seam) |
| `docs/YIELD_POLICY.md`, `docs/README.md` | the record and its index row |
| `docs/CURRENT_STATUS.md` | one paragraph: `configs/personality.yaml` is a bound, not inert, surface |
| `backlog/UNVERIFIED.md`, `backlog/NEXT.md` | U35, U36, N20, N21 |

**Not touched:** `navigation/**`, `instructnav/**`, `approach`/`pipeline`/
`scoring`, `tests/test_voice_nav_e2e.py`, `evals/**` (code *or* data),
`configs/robot.yaml` (hash-locked; verified unchanged),
`prompts/personalities/**`.

---

## Hand-offs

1. **To the navigation executor — N20.** A fourth release authority for
   "a person will not clear this approach pose". Preferred shape:
   `DirectiveNavigator.release_current_candidate(reason: str) -> bool`,
   returning whether an alternative exists. The alternative (a `person_stop`
   dwell counter inside `pipeline.py` mirroring `_gate_blocked_route_recovery`)
   puts a second dwell counter in a second tree deciding about the same tick,
   which is the D5 defect class the single `_release_unreachable_candidate`
   door exists to prevent. Until one exists the runtime's only honest options
   are the three shipped ones.
2. **To the coordinator — the traffic pin.** Exact text below in the P-3
   verdict. This card did not edit `tests/test_voice_nav_e2e.py`.
3. **To whoever owns the Vocalize path — U35.** The ask is not audible.
