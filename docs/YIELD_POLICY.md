# The yield policy: what the dog does when a person is in its way

**Date:** 2026-08-08 · **Status:** implemented, wired, and unit/integration
verified at the runtime seam; the traffic e2e measurement is in
[../scrum/20260808/task_4/YIELD_POLICY_STATUS.md](../scrum/20260808/task_4/YIELD_POLICY_STATUS.md).
**Owner directive (verbatim):** "When the robot determines there is a person in
scene, that should be a personality decision. By default let the robot ask for
help but make sure that this personality is configurable."

## The gap this closes

On 2026-08-07 the traffic case
(`test_go_to_the_sidewalk_with_pedestrian_traffic`) was measured with the robot
**inside** the scored sidewalk polygon — K0 distance 0.000 m — holding
`grid_track err=0.0 goal=0.2 route=2 status=planned|person_stop` for ~200 ticks
because a pedestrian was parked on the last 0.2 m of the approach. Two
behaviours kept it there and **both are correct in isolation**:

* `_progress_watchdog` deliberately does not count person-stop ticks as
  no-progress, so yielding cannot false-fail a mission and nothing replans;
* `_inside_arrival_goal_region` returns `False` for the `inside` relation,
  because region arrival requires terminal clearance (0.32 m) and the robot had
  0.285 m — so standing in the polygon is not arrival.

Net: the robot was in the right place, correctly refusing to claim arrival and
correctly refusing to push past a person — **with no clock**. It burned the
240 s `NavigateTo` budget and failed as `step_timeout`, a reason that names
nothing. The residual was never final-approach geometry. It was a product
decision nobody had made:

> How long may a mission spend yielding, and what does the dog do about it?

That decision is a **temperament** decision, so it lives with personality.

**One correction to the 2026-08-07 diagnosis.** Instrumenting the gate rather
than the pose shows it is not *a* pedestrian parked on the last 0.2 m — it is a
**stream**. `person_stop` closes and re-opens with roughly one-second gaps for
the whole run (first closure at 11.5 s; ~75% of the 240 s spent inside the
gate, in fragments). The outcome the earlier record describes is right; the
mechanism is chatter, not a statue, and that distinction is what makes
`release_grace_s` necessary below.

## The policy

```yaml
personality.yield_policy:
  patience_s:        <float>   # how long an episode must persist before acting
  on_blocked:        ask_for_help | wait | give_up_honestly
  reask_interval_s:  <float>   # between asks, and between last ask and give-up
  max_asks:          <int>     # PER MISSION; 0 ⇒ behaves as give_up_honestly
  release_grace_s:   <float>   # gate must stay open this long to end an episode
```

### Two scopes, and the difference was measured

* **Episode scope** (`patience_s`) — an episode starts at the first
  `person_stop` tick and ends only after the gate has been continuously *open*
  for `release_grace_s`.
* **Mission scope** (`max_asks`, `reask_interval_s`) — the ask budget is not
  refunded when the gate flickers, and is cleared only when a mission starts or
  stops (or the personality changes).

Both scopes exist because of a live measurement, not a design instinct. The
first instrumented run of the traffic case under this policy asked **13 times
in 240 s and never gave up**: the person gate *chatters* in a pedestrian
stream, and with both scopes per-episode every brief release reset patience
*and* refunded the ask budget, so the ask re-armed forever and `max_asks` was
unreachable. `release_grace_s: 0.0` restores the strict continuous-blockage
rule, and on a gate whose individual blockages are shorter than `patience_s` it
is provably inert — the dog stands there for four minutes and never speaks
(`test_release_grace_is_what_makes_patience_mean_something_in_traffic`).

| `on_blocked` | behaviour |
|---|---|
| **`ask_for_help`** (default, owner-mandated) | at `patience_s`, speak once; re-ask no sooner than `reask_interval_s`, at most `max_asks` times; one full interval after the last ask, end the mission with `blocked_by_person_unanswered` |
| `wait` | hold indefinitely — **exactly** the 2026-08-07 behaviour; the outer step budget is the only thing that ends the mission. Says nothing, abandons nothing |
| `give_up_honestly` | at `patience_s`, end the mission with `blocked_by_person` and say so. No request for help |

### Shipped values

| personality | `patience_s` | `on_blocked` | `reask_interval_s` | `max_asks` | `release_grace_s` |
|---|---|---|---|---|---|
| `gentle_companion` (shipped default) | 8.0 | `ask_for_help` | 12.0 | 2 | 3.0 |
| `calm_guardian` | 12.0 | `ask_for_help` | 20.0 | 1 | 4.0 |
| `playful_companion` | 5.0 | `ask_for_help` | 8.0 | 3 | 2.0 |

The timings are **choices, not measurements** — the same status as
`GATE_BLOCKED_ROUTE_STEPS = 60`. They are bounded on both sides by measured
things (8 s outlasts every transient pass observed in the dynamic city;
`8 + 12 + 12 = 32 s` is far inside the 240 s contract ceiling, so the honest
reason always beats `step_timeout` to the finish — measured end-to-end at
54.0–54.2 s across three traffic seeds against a 240.2 s ceiling), but no
experiment placed patience at 8 s rather than 6 s or 12 s.

`release_grace_s = 3.0` is the exception: it is the one value derived from an
observation — the gaps in the dynamic city's `person_stop` stream are of order
one second, and 3 s coalesces them into a single episode while still letting a
genuinely cleared path end one.

## What it may never do

The policy is **downstream of every safety gate**. It never sees a velocity,
never proposes one, and never reads or alters `person_stop_m`,
`obstacle_stop_m`, TTC, or the collision brake. It decides *how long to wait
and what to say* — nothing else. A gate-blocked tick still commands
`vx == 0.0` under every value in the config, and
`tests/test_yield_policy.py::test_a_gated_tick_still_commands_zero_under_every_policy`
asserts that for all three `on_blocked` values against the recorded velocities.
If that test ever fails, the policy has become a command source and must be
reverted, not tuned.

## Person-blocked, and nothing else

`obstacle_stop` is a **different case with different machinery**:
`DirectiveNavigator._gate_blocked_route_recovery` releases a route commitment
after 60 consecutive `obstacle_stop` ticks with zero goal progress, and it
deliberately excludes `person_stop` (yielding to a person is the gate doing its
job; releasing on it would abandon the goal every time somebody walked past).
This policy is the mirror image and is equally exclusive.

`MidLevelCommand.note` is a `|`-joined composition
(`f"{cmd.note}|{cnote}"` in `navigation/pipeline.py`), so
`person_blocked_from_note` matches the `person_stop` **segment exactly**. A
substring test would also match `no_person_stop`; more importantly, exact
segments are what keep `obstacle_stop`, `obstacle_slow`, `person_slow`,
`obstacle_projected_speed_cap` and every shield note out of this path. Ten of
those notes are pinned as non-triggers.

## The words, and what they may claim

The runtime holds **no yield vocabulary at all**. Templates live per
personality in `configs/personality.yaml` under `yield_speech:` (`ask`,
`reask`, `give_up`), with `{place}` — the mission's goal label — as the only
substitution.

Every template is checked against the DialogueAct truthfulness rules **at
config load time**, so a bad string is a startup error and never an utterance.
What a person-gate tick actually proves is exactly two things:

1. a person is inside the stop envelope, and
2. translation was zeroed.

Both are carried as `DialogueClaimV1(veracity="verified",
evidence_ref="navigation:person_stop")` — which `DialogueClaimV1.__post_init__`
requires for a verified claim. Nothing else is asserted: not arrival, not the
person's intent, not that help is coming. `FORBIDDEN_ARRIVAL_PHRASES` refuses
any authored line containing an arrival or completion claim, and the check is
**re-run after `{place}` substitution**, because a goal label is scene data
rather than authored text.

This is the first production path in the repo that puts a *backed* claim on a
`DialogueActV1` — `agent.py`'s conversation act ships with an empty `claims`
tuple, so the veracity/evidence machinery had never been exercised live.

## Where it runs

| piece | file |
|---|---|
| policy, tracker, templates, config loader (pure) | `src/parcel_robot/core/yield_policy.py` |
| DialogueAct binding | `src/parcel_robot/voice/yield_speech.py` |
| per-personality values | `configs/personality.yaml` (+ packaged copy under `runtime_assets/`) |
| the seam | `RobotRuntime._step_navigation` → `_act_on_yield_decision` |
| tests | `tests/test_yield_policy.py` |

The tracker is fed one `(person_blocked, now_s)` pair per control tick and
returns `clear` / `hold` / `ask` / `give_up`. `ask` is returned on **exactly
one tick per ask**, so the utterance is edge-triggered — the same discipline as
`_announce_pose_health`, which exists because a per-tick sentence at 10 Hz is
noise, not honesty. 300 blocked ticks produce 2 asks, not 300; a gate that
chatters for 240 s produces 2 asks and one honest end, not 13 asks and no end
(which is what the first live run did before the two scopes were separated).

Speech goes through `_brain_vocalize`, the same utterance door the `Vocalize`
skill uses — no second announcement channel. **Updated 2026-08-09 (card U35,
[../scrum/20260808/task_5/VOCALIZE_AUDIBLE_STATUS.md](../scrum/20260808/task_5/VOCALIZE_AUDIBLE_STATUS.md)).**
That door used to write chat + the event log and stop there, so the ask was
visible and never audible. It now also calls
`DuplexVoiceSession.speak_system`, which synthesizes and plays through the
ordinary reply path, and the ask has been measured on the virtual acoustic
rig: 5.3–5.6 s of speech on the sink-monitor recording, against total silence
on the pre-fix door. Two properties are worth knowing here:

* **The utterance is skipped, never queued, if the speaker is busy** with a
  reply, a filler, or an earlier ask. The re-ask timer is the retry. So under
  a live conversation an ask can be inaudible even on a machine with audio —
  which is why `yield_policy_snapshot()["last_utterance_audible"]` exists and
  why the chat item is still written unconditionally.
* **Audible still means "handed to the sink"**, the same bar
  `audio_first_playback` sets for a reply. Whether a person *heard* it, and
  whether anybody responds, remains U35's second half and is unmeasured.

## The honest end

`_act_on_yield_decision` ends the mission through `_stop_navigation_channel`
with an **attributable** reason (`blocked_by_person` or
`blocked_by_person_unanswered`) instead of letting the 240 s ceiling produce a
blunt `step_timeout` four minutes later. The reason reaches the plan record
because `SemanticTaskRuntimeAdapter._result_for` reads `navigation_state` +
`navigation_reason` straight into the failed step's `detail_code`.

`_stop_navigation_channel` gained `reason=` / `state=` keywords for this. They
matter: without them the give-up would have to stop first and correct the
detail afterwards, and the executive polls between those two writes — it would
read `navigation_disabled` and attribute the failure to nothing.

### Collateral defect fixed with it

`TaskExecutive.report` recorded `result.feedback_code` as the failed step's
`last_detail`. For a failed result that code is the constant `"failed"`
(`runtime_adapter._failed_result`), so the field wrote the state down twice and
discarded the adapter's attribution — `last_detail` is the **only** attribution
field the task snapshot carries. It now prefers `detail_code`, which is where
the verifier put the reason. The cancellation arm one line above already did
this; the failure arm now agrees. Every honest navigation reason
(`semantic_target_unreachable`, `navigation_no_progress`,
`blocked_by_person_unanswered`, …) is visible to a caller reading the task
record as a result.

## Configuration surface

`configs/robot.yaml` is **hash-locked** by
`evals/companion/embodied_plan_v1/manifest.json`
(`locked_inputs.robot_config`, sha256 `f6468887…`), so the policy could not be
added there without moving a frozen eval input. It lives in a sibling file,
`configs/personality.yaml`, resolved through `paths.resolve_asset`. The active
personality id still comes from `configs/robot.yaml agent.personality`; a
derived config may point elsewhere with `agent.personality_policy: <path>`.

Absence and corruption are answered differently on purpose. A checkout or wheel
that does not ship the file gets the documented built-in defaults — the policy
only decides how long to wait and what to say, so a missing file must not take
the runtime down. A file that *is* present but malformed **raises**: unknown
keys at every level, unknown `on_blocked` values, non-finite or negative
timings, a float `max_asks`, an invalid personality id, and unsupported
`{placeholders}` are all startup errors.

`set_personality` re-installs the policy and its words, so temperament is part
of "who this dog is" rather than global runtime state. A new mission never
inherits the previous one's blocked time or spent asks, and patience restarts
whenever the gate releases — somebody walking past can never spend it.

Inspect the live state with `RobotRuntime.yield_policy_snapshot()` (a method,
not a `snapshot()` key: the panel snapshot shape is pinned by tests and this is
diagnostic state, not a channel detail).

## Deliberately not done

* **Nothing tells the pedestrian.** The ask is addressed to whoever is
  listening; the dog has no way to know the person heard it, and it does not
  claim they did. Real-world efficacy is unmeasured.
* **The sim's scripted pedestrians cannot respond.** They walk a script, so
  every measured run ends in the honest failure rather than in a person
  stepping aside. The policy's *social* value is therefore untested;
  what is tested is that the robot stops burning four minutes to say nothing.
* **No re-plan on give-up.** A blocked approach pose might have an alternative;
  finding one is the navigation executor's `_release_unreachable_candidate`
  machinery, and hooking the yield give-up into it is a hand-off, not this
  card's edit.
* **The timings are unmeasured choices.** See "Shipped values" above.
* **The honest end costs distance.** Measured on the traffic case: waiting the
  full 240 s left the robot 0.000 m from the scored polygon (inside it, still
  not arrived); giving up at ~54 s leaves it 0.29 m outside. Neither is
  arrival, and the card chose the attributable, spoken, 4.4×-faster failure —
  but the K0 predicate did move the wrong way and nothing here pretends
  otherwise. `on_blocked: wait` restores the old behaviour in one config line.
