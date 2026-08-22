# P0-B — hosted-lane companion unlocks · STATUS

**Executor:** Claude Opus · **Verifier:** Fable · **Date:** 2026-08-22
**Card:** `README.md` · **Board:** `../TASK_BOARD.md`

## Headline

All seven deliverables landed. Five validated config keys now exist on the
hosted lane — a proactive-motion allowlist, a `navigate_to` ask mode, `0` meaning
never on the idle timer, the narration cap's rolling window, and hosted affect —
and **every one of them takes its pre-card value when the key is absent**. A
`configs/realtime.yaml` written before this card loads to byte-identical
behaviour, which is why the frozen realtime fixtures, the corpus replays and the
SI/DI prompt digests are untouched and green.

Two declared deviations from OWNS, both one-liners, both named in §5.

## 1. What changed

`git diff --numstat` on the OWNS surface:

| file | +/- | what |
|---|---|---|
| `src/parcel_robot/realtime/config.py` | +266 / −7 | 5 new validated keys, 4 new validators, `idle_close_enabled` |
| `src/parcel_robot/realtime/tool_broker.py` | +162 / −9 | proactive gate hole + ceiling, `unknown_place` ask path, counters, snapshot |
| `src/parcel_robot/realtime/whisperer.py` | +19 / −3 | the cap's window is `config.window_s`, not a literal `60.0` |
| `src/parcel_robot/realtime/lane.py` | +12 / −1 | **deviation** — `_idle_due` honours `idle_close_after_s: 0` |
| `configs/realtime.yaml.example` | +83 / −4 | every new key documented, defaults off |
| `src/parcel_robot/runtime.py` | +141 / −1 (mine) | see below |
| `tests/test_p0b_companion_unlocks.py` | +852 (new) | 56 tests |
| `tests/test_realtime_idle_hangup.py` | +49 / −6 | `0` moved out of the refusal list into its own end-to-end test |

`runtime.py` is edited by several cards concurrently; **my** hunks are only:

* `+62..66` — `from parcel_robot.brain.router import explicit_affect_from_text`
* `+253` — `KIND_NONE` added to the existing `realtime.ingress` import
* `~2478` — two kwargs on the existing `RealtimeToolBroker(...)` call (**deviation**)
* `~6269` — the 9-line `KIND_NONE` guard inside `submit_realtime_transcript`
* `~6308` — the 116-line `_hosted_affect` helper, immediately after it

Nothing else in `runtime.py` is mine.

## 2. The new keys, their defaults, and the prototype values

P0-A owns `configs/realtime.prototype.yaml.example`; Fable merges. These are the
values that card should carry.

| key | type | shipped default | **prototype value** | why |
|---|---|---|---|---|
| `proactive_motion_tools` | list | `[]` | `[play_gesture, set_pose]` | the companion may greet you, tilt its head, settle down beside you without being spoken to first. Both entries are in-place motion; the travel tools are refused at load. |
| `unknown_place` | enum | `refuse` | `ask` | "go to the coffee place" becomes a question with the real place names in it, not a walk that gives up at grounding. Prototype directive: ask over refuse. |
| `idle_close_after_s` | seconds, `0` = never | `600.0` | `0` | the desk prototype should still be awake when the owner comes back into the room. `session_max_s` and `monthly_budget_usd` still bound it. |
| `whisperer.window_s` | seconds, > 0 | `60.0` | `30.0` | with `max_updates_per_minute: 2` unchanged this is 4 facts/minute — chattier without touching the cap or the min-gap the bench tuned. |
| `hosted_affect` | bool | `false` | `true` | "I'm feeling sad" reaches the body on the lane that actually ships. Needs `agent.affect.minimum_confidence` ≤ 1.0 (P0-A's profile sets 0.5). |

Recommended prototype block, ready to paste:

```yaml
idle_close_after_s: 0            # stay live while the owner is around
proactive_motion_tools: [play_gesture, set_pose]
unknown_place: ask
hosted_affect: true
whisperer:
  max_updates_per_minute: 2
  min_gap_s: 15.0
  window_s: 30.0
```

### What each one actually does

1. **Proactive motion.** The R11 system-initiated gate in `tool_broker._dispatch`
   grows exactly one hole: a tool on the configured list, intersected with
   `PROACTIVE_MOTION_CEILING = {play_gesture, set_pose}`, skips the refusal and
   then travels the *identical* path an owner-initiated call travels — same
   argument parse, same `SafetySupervisor.validate`, same activity coordinator
   (cooldown, ttl, arbitration, e-stop), same door. Nothing downstream learns the
   call was proactive; it only learns that it happened. Admitted results carry
   `provenance: system` and the snapshot publishes
   `proactive_motion_tools` / `proactive_motion_admissions`.
2. **`navigate_to` asks.** `validate_place` already separated "not a place name"
   (`with owner` — still refused, untouched) from "a name the map has never
   heard of" (`narnia`). In `ask` mode the second class returns
   `status: unknown_place` with `place`, `valid_places` (nearest-first, capped
   at 5) and `reason`, touching **no door** — not `validate`, not `on_dispatch`,
   not `navigate`. In `refuse` mode (default) it routes exactly as a typed
   sentence does, so R20's authority-parity test is untouched.
3. **Idle `0`.** Accepted, finite-checked, negative-refused; `RealtimeConfig.
   idle_close_enabled` names the sentinel so the loader and the lane cannot
   drift. `.inf` is still a refusal and the message points at `0` instead.
4. **Narration window.** `whisperer._spent` counted a literal `60.0`, so the
   narration rate was half a knob: you could set the number and not the minute,
   and the only purchasable rates were whole multiples of one-per-minute. Now
   `whisperer.window_s`, validated **strictly positive** (a window of zero counts
   nothing and would remove the owner's cost cap silently), default `60.0`, and
   published in the whisperer snapshot next to `updates_this_minute`.
5. **Hosted affect.** On the `KIND_NONE` path only, `_hosted_affect` runs the
   *same* `explicit_affect_from_text` the legacy lane uses, checks the label
   against `agent.affect.minimum_confidence`, writes an
   `[affect <label>] confidence=… action=… transcript=…` row through
   `_write_realtime_ledger("system", …)`, and proposes the persona's
   `affect_actions` skill via `propose_action`. It never replies, never speaks,
   never sets `outcome.executed`, never touches `_brain_return_to_safe_pose`,
   and cannot raise (it runs on the pump thread).

## 3. How it was verified

### Seeded RED — behavioural, not just missing-symbol

`git archive HEAD` into `/home/jaewoo-jang/.cache/parcel-p0-b/head`, the new test
file copied in with the card's new constants shimmed as local literals so the
**behavioural** assertions execute instead of dying at import, then:

```
$ PYTHONPATH=<scratch>/src .parcel/bin/python -m pytest -q tests/test_p0b_companion_unlocks.py
29 failed, 27 passed, 2 warnings in 1.35s
```

Full output: `/home/jaewoo-jang/.cache/parcel-p0-b/RED_p0b.txt`. Every new guard
is in the failing set, including:

* `test_a_listed_tool_may_run_from_a_reply_the_robot_started[play_gesture|set_pose]`
* `test_a_travel_tool_smuggled_past_the_loader_is_still_refused[navigate_to|circle_owner|follow_owner]`
* `test_the_allowlist_is_a_validated_key_that_refuses_the_travel_tools`
* `test_ask_mode_returns_a_question_and_starts_no_motion`
* `test_the_unknown_place_mode_is_a_validated_key`
* `test_zero_is_accepted_and_means_never_hang_up`
* `test_the_window_is_a_validated_key_that_defaults_to_the_same_minute`
* `test_a_shorter_window_lets_the_narration_budget_refill_sooner`
* `test_hosted_affect_writes_the_row_and_proposes_the_persona_gesture`
* `test_hosted_affect_never_runs_on_an_utterance_the_ingress_claimed`

`test_zero_means_never_and_the_lane_stays_open` (in `test_realtime_idle_hangup.py`)
was RED at HEAD in the strongest possible way: at HEAD `idle_close_after_s: 0`
is a **load refusal**, and the parametrized case that made it one is the case
this card deleted.

### GREEN — the card's gates

```
$ .parcel/bin/python -m pytest -q tests/test_realtime_*.py tests/test_p0b_companion_unlocks.py
1241 passed, 2 skipped, 2 warnings in 20.56s

$ .parcel/bin/python -m pytest -q tests/test_p0b_companion_unlocks.py
56 passed, 2 warnings in 0.76s

$ .parcel/bin/python -m pytest -q tests/test_realtime_idle_hangup.py
38 passed, 2 warnings in 1.70s

$ .parcel/bin/python -m pytest -q tests/test_realtime_prompting.py     # SI/DI digest pins
39 passed, 2 warnings in 0.45s

$ .parcel/bin/ruff check src/parcel_robot/realtime tests/test_p0b_companion_unlocks.py \
      tests/test_realtime_idle_hangup.py src/parcel_robot/runtime.py
All checks passed!
```

`tests/test_tool_broker*.py` from the card's gate line does not exist; the broker
suite is `tests/test_realtime_tool_broker.py`, which is inside the
`test_realtime_*.py` glob above.

### GREEN — everything else that reads these surfaces

```
$ .parcel/bin/python -m pytest -q tests/test_runtime_whisperer_wiring.py \
      tests/test_scene_and_memory_answers.py tests/test_fail_closed_limits.py \
      tests/test_unknown_place_admission.py
300 passed

$ .parcel/bin/python -m pytest -q tests/test_arrival_semantics.py tests/test_owner_estop.py \
      tests/test_safety_log.py tests/test_r24_lock_discipline.py tests/test_mission_log.py \
      tests/test_prototype_profile.py
188 passed
```

`evals/companion/realtime_convo_v1` replays are exercised by
`tests/test_realtime_corpus_replay.py`, inside the 1241 above. No frozen fixture
was edited and no digest sentinel names `configs/realtime.yaml.example`.

## 4. What this does not prove

* **No hosted session was opened.** Everything is the fake server and the unit
  rigs, per the card. The proactive unlock has never been measured against a
  real `gpt-realtime` deciding *when* to call `play_gesture` from a telemetry
  beat — the gate is proven, the model's taste is not. That is the first thing
  to watch on the desk.
* **`explicit_affect_from_text` always returns confidence 1.0.** The
  below-threshold arm is therefore pinned with a monkeypatched evidence object,
  not with a real transcript. The threshold is real and read from
  `configs/robot.yaml`; no *reachable* transcript is currently below it.
* **The affect row joins the memory tail.** `[affect sad]` rows are `system`
  rows, and `memory_tail` replays the last 20 realtime turns into each new
  session — so the model will see them. This is the same treatment
  `[session rollover]` and `[idle hang-up …]` already get and reads as useful
  context, but it is a behaviour change nobody asked for explicitly. Flag-off by
  default; worth a look in the first live run.
* **`idle_close_after_s: 0` was tested against a hand-advanced clock**, 24
  simulated hours in one-hour ticks. It was not left running against a real
  provider for a day, and the interaction with a provider-side idle disconnect is
  unmeasured.
* **`window_s` is not wired into any cost projection.** Halving the window at the
  same cap doubles the ceiling on billed robot-initiated responses;
  `monthly_budget_usd` is what still bounds that, and it is untouched.

## 5. Deviations from OWNS (declared)

1. **`src/parcel_robot/realtime/lane.py`, `_idle_due` (+12 / −1).** Not in OWNS,
   not in MUST-NOT-TOUCH. Deliverable 3 is unimplementable without it: the
   existing comparison is `idle_for < config.idle_close_after_s`, and
   `idle_for < 0.0` is false for every duration there is, so a `0` that reached
   the arithmetic would hang the session up on its **first** idle tick — the exact
   opposite of what the operator wrote. The change is one guard,
   `if not self.config.idle_close_enabled: return None`, reading a property
   defined beside the key in `config.py`. Nothing else in the file was touched.
2. **`src/parcel_robot/runtime.py` line ~2478**, outside the
   `submit_realtime_transcript` region my OWNS names. Two kwargs on the existing
   `RealtimeToolBroker(...)` call, which is the only place the broker is
   constructed in the product; without them deliverables 1 and 2 are validated
   keys that nothing reads. The alternative — having the broker load
   `default_realtime_config()` itself — would have been a hidden ambient read,
   which is worse for an auditor than a declared two-line wiring. Neither P0-A
   (camera-flag regions) nor P0-D (8396–8460, 557–575) touches this line.

Also note, inside OWNS but worth flagging: **`tests/test_realtime_idle_hangup.py`
line 225 lost `0` and `0.0` from
`test_an_unreadable_idle_window_is_a_refusal_not_a_default`.** That test asserted
the policy deliverable 3 was sent to change. Its docstring now records what moved
and why, and `test_zero_means_never_and_the_lane_stays_open` replaces the
coverage. Everything else in that parametrization — negatives, non-numbers,
`.inf` — still refuses.

### Interpretations worth a verifier's eye

* The card says "propose … through `propose_action(kind="pose"|"gesture")`".
  `RobotRuntime.propose_action` accepts only `ActionProposal(kind="skill")` and
  then restricts the named skill to catalog kinds `pose`/`trajectory`. I read the
  card as naming the *skill* kind and used `kind="skill"`, which is what
  `agent.py`'s legacy affect path and `_brain_gesture` both do. `comfort_bow`
  (the default `gentle_companion` action for `sad`) is a `trajectory`.
* The card describes `tool_broker:882-948` as "gating on a known-place list".
  It does not: an unknown *noun* is admitted and routed today (R20 authority
  parity), and only a directive fragment is refused. `unknown_place: refuse` is
  therefore named for the outcome the owner sees, not for a broker refusal —
  documented as such in the example config and in `config.py`.

## 6. Handoffs

* **P0-A** — the prototype values in §2 are ready to paste into
  `configs/realtime.prototype.yaml.example`. `hosted_affect: true` is only useful
  if that profile's `agent.affect.minimum_confidence` is ≤ 1.0 (0.5 as planned).
* **Fable** — the RED artifact is at
  `/home/jaewoo-jang/.cache/parcel-p0-b/RED_p0b.txt`, and the shimmed HEAD tree it
  came from is at `/home/jaewoo-jang/.cache/parcel-p0-b/head` if you want to
  re-run it. The two deviations in §5 are the diff-vs-OWNS mismatches you will
  find.
* **Phase 3 (flywheel)** — `broker.unknown_place_asks` and the `[affect <label>]`
  ledger rows are the two new machine-readable streams this card leaves behind.
  The first is literally the list of place nouns the owner uses that the map
  cannot ground; the second is the owner-model's first real input.
* **Nobody has run this against a live session.** The proactive unlock in
  particular should be watched, not assumed, on the first desk run.
