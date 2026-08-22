# ROAM-1 — "go explore" is a behavior, a tool and a closed intent · STATUS

**Card:** `README.md` · **Board:** `../TASK_BOARD.md` · **Build order:**
`../PLAN_ASSESSMENT_FABLE.md` (week 1, "roam on command" REFUTED as a capability)
**Executor:** Claude Opus · **Verifier:** Fable · **Date:** 2026-08-22
**HEAD at start:** `8862220`
**Pre-registration:** `evidence/ROAM1_PREREGISTRATION.md`
(sha256 `b4fc8e0d41fee01ca1d4c633fe9cb9e56e46566dcbb719d8dfdca536308bf3bb`,
written `2026-08-22T06:17:25-04:00` — **before** the first measurement and
before any source edit).

---

## Headline

**COMPLETE.** The dog can be told to go explore, it goes, it comes back when
told, and it does it through the product path — the hosted ingress, the
runtime's own control loop, the shipped broker. `PatrolPolicy` is constructed
in `runtime.py` for the first time; `TOOL_ROAM` is the ninth broker tool and
is structurally incapable of being proactive; `roam` / `go explore` /
`stop roaming` execute locally before the model speaks. The navigator's frozen
clock is fixed in the two places it was missing.

> **READ THE CORRECTION PASSES FIRST (bottom of this file).** Two things below
> are superseded. The verifier found that one of the three arm-B runs quoted
> here — the 20.67 m one — left the rendered map at t = 85 s; and the three
> tethered runs that replaced it are one trajectory sampled three times, so
> quoting three near-identical numbers overstated how repeatable the behaviour
> is. **The Go2-purchase input, as it stands after correction pass 2:**
>
> > **Seven product-path tethered runs: 1.30 / 3.10 / 6.48 / 6.54 / 6.47 /
> > 6.56 / 6.57 m net displacement in-block, 0 contacts each, `in_bounds` 7/7.**
> > The tether engaged on **5 of 7** (the escape branch: out to ~10 m, turned
> > back at ~78 s). The other 2 are the **boxed branch** — the wander stays
> > within ~3.4 m of home and never reaches the tether at all — and which
> > branch a run takes is timing- and load-sensitive, not a setting. **Every
> > one of the seven clears the ≥ 1.0 m tell**, and the pre-tether record is:
> > two in-block runs ≥ 1.0 m (3.37, 2.05) plus one run that exited the scene
> > (20.67 raw, 12.02 at the last in-plane sample, 8.66 m of it banked off the
> > rendered map).
>
> Every number in the section below is the pre-tether measurement and is kept
> for the record.

**THE PURCHASE NUMBER, reported exactly, both arms.** The card's
`≥ 1.0 m net displacement` row was measured twice, because the first
measurement failed and told me why:

| arm | 3 × 120 s `--static-city` runs | net displacement (m) | path (m) | contacts |
|---|---|---|---|---|
| **A — shipped patrol policy** | as MOVE-1 left it | **0.144176 · 0.222416 · 0.284751** | 21.85 · 21.85 · 21.84 | 0 · 0 · 0 |
| **B — as delivered** | one policy line, this card | **3.366806 · 2.048318 · 20.674462** | 17.83 · 21.22 · 27.61 | 0 · 0 · 0 |

**Arm A MISSED the row 3/3.** The cause is measured, not guessed:
the patrol's turn sign only ever flips *mid-turn*, so every one of the 18
avoidance turns in a run went the same way and the path closed into a circle —
**1404 degrees of heading change, 3.90 full turns, inside a 1.8 × 2.2 m box**,
while walking 21.85 m. It was not exploring; it was doing donuts. Arm B flips
the sign when a turn *releases* (`PatrolLimits.alternate_turns`, **default OFF**
so MOVE-1's baseline is untouched; `limits_from_safety` — the only thing the
roam behavior calls — turns it on).

**Arm B is what ships and it meets the row 3/3.** Read against MOVE-1's
0.134 m, the delivered behavior is **15× to 154×** further from where it
started. Variance is high (2.05 → 20.67 m) and that is reported, not smoothed:
this is a bounded wander, not a coverage planner.

Every other pre-registered row was met. No row was re-defined after measuring.

---

## What changed

`git diff --stat` on OWNS (against `8862220`):

```
 src/parcel_robot/patrol/__init__.py            |   6 +          all mine
 src/parcel_robot/patrol/mission.py             |  93 +          all mine
 src/parcel_robot/realtime/ingress.py           |  88 +, 2 -     all mine
 src/parcel_robot/realtime/tool_broker.py       | 234 +          all mine
 src/parcel_robot/headless_city.py              |   8 +          all mine
 tests/test_roam1_behavior.py                   | 694 +   (new)  all mine
 tests/test_p0b_companion_unlocks.py            |  11 +          all mine
 tests/test_realtime_completion_tense.py        |  19 +          all mine
 tests/test_realtime_system_initiated_motion.py |  11 +          all mine
 src/parcel_robot/runtime.py                    | 931 +          453 mine
 src/parcel_robot/realtime/config.py            | 382 +           11 mine
```

**Two of those files are shared with a concurrent card and the whole-file
numbers are misleading. Diff by the `Card ROAM-1` marker, not by file.**

* `runtime.py`: 17 added hunks, **10 of them mine (453 lines)**; the other 7
  (478 lines) are CURIO-1's chatter feed, landed in the same tree while this
  card was executing. My ten: the patrol import, the two ingress kinds, the
  state block, the `roam=` door, the 353-line roam region, the two ingress
  branches, the snapshot key, the loop call, the clock line, the voice phrase.
* `realtime/config.py`: **11 lines mine** (a 6-line comment and
  `PROACTIVE_MOTION_REFUSED` reflowed from one line to five); the other ~371
  are TURN-1's `turn_detection` work at ~line 563, a different region.

**The five pieces, and where each lives:**

1. **The behavior** — one NEW marked region in `runtime.py`
   (`CARD ROAM-1 — "GO EXPLORE" IS A RUNTIME BEHAVIOR`, after `set_behavior`):
   `start_roam` / `stop_roam` / `_step_roam` / `roam_snapshot` /
   `roam_idle_checkpoint` / `_roam_limits` / `_roam_sense` /
   `_submit_roam_command` / `_realtime_roam`. Plus four one-to-few-line
   insertions elsewhere, each marked: state in `__init__`, the `roam=` door in
   the `ToolDoors` construction, the `_step_roam` call in the control loop, the
   `"roam"` key in `snapshot()`, `VOICE_TOOL_PHRASES["roam"]`, and two
   `elif` branches appended to `submit_realtime_transcript`'s ladder.
   P1-B's, P2-A's, P2-B's and CURIO-1's regions are untouched.
2. **The tool** — a NEW region in `tool_broker.py` beside P0-B's and P2-A's:
   `TOOL_ROAM`, the action/budget enums, `_roam`, `_roam_minutes`, the spec
   appended LAST to `build_tool_specs` (P2-A's precedent), and membership in
   `MOTION_TOOLS`, `ACTIVITY_TOOLS`, `BROKER_TOOLS`.
3. **The closed intents** — `ROAM_START_PHRASES` (12) and `ROAM_STOP_PHRASES`
   (9) in `realtime/ingress.py`, with `KIND_ROAM` / `KIND_ROAM_STOP`
   **appended** to `INGRESS_KINDS` and read **after** the existing ladder.
   Nothing above them moved and no existing phrase set was edited.
4. **The clock** — `"time_s": float(observation.timestamp)` in
   `runtime._navigation_extras` and in `headless_city._nav_observation`.
5. **The policy** — `limits_from_safety`, `PERSON_CLEARANCE_MARGIN_M`,
   `FORWARD_CLEARANCE_MARGIN_M` and `alternate_turns` in `patrol/mission.py`.

---

## How verified

Environment: `.parcel/bin/python`, `.parcel/bin/ruff 0.16.1`, `TMPDIR` unset
for every pytest invocation. Scratch under
`/home/jaewoo-jang/.cache/parcel-roam1/`. The sim ran on
`/tmp/parcel-roam1-<pid>.sock`, a pid-unique socket, never the owner's
`/tmp/parcel_sim.sock`. `~/.parcel/parcel_memory.sqlite3` does not exist on this
host and was never opened; every run records `owner_store.unchanged: true`.
Hosted spend: **$0.00** — no live turn was needed.

### Pre-registered rows

| Row | Pre-registered | Measured | Verdict |
|---|---|---|---|
| **R1** | "go explore" → patrol ticking ≤ 2.0 s | ingress returns in **0.0003–0.0005 s**; first roam tick at **0.081–0.102 s** | **MET** (20× margin) |
| **R2a** | 3 × 120 s static, path ≥ 5.0 m | 17.83 / 21.22 / 27.61 m | **MET 3/3** |
| **R2b** | 3 × 120 s static, net ≥ 1.0 m | **3.366806 / 2.048318 / 20.674462 m** — but the third run **left the 24 × 24 m road plane at t = 85 s**, so as a claim about this scene it is **3.366806 / 2.048318 / 12.015434** (the last in-plane sample). With the tether ON, **seven** product-path runs (three mine, four the verifier's): **1.30 / 3.10 / 6.48 / 6.54 / 6.47 / 6.56 / 6.57 m in-block, `in_bounds` 7/7, 0 contacts** — bimodal, 5 escape-branch and 2 boxed-branch | **MET 7/7** in-block with the tether · MET 2/3 in-block without it · **MISSED 3/3** on the shipped policy (arm A) |
| **R2c** | 0 robot-initiated contacts | `collision_ticks` 0 / 0 / 0 | **MET 3/3** |
| **R2d** | prototype social zone (0.7 m) respected | min person clearance **1.099 / 1.058 / 1.161 m** | **MET 3/3** |
| **R3** | "stop roaming" latches in one tick | `roam.active` is **False on return of the ingress call** (0 ticks, not 1) | **MET** |
| **R4** | dynamic city is a second arm, not the gate | reported below | **MET** |
| **R5** | paired `nav_instruct` unchanged at 10 Hz; seeded 20 Hz shows dt moving | byte-identical report; dt 0.1 → 0.05 | **MET** |
| **R6** | four seeded-RED proofs | all four | **MET** |
| **R7** | targeted pytest + ruff green; ratchet still 7 | 742 passed; ratchet 7, new 0 | **MET** |

### The three static runs (the gate), exact

Harness: `evidence/run_roam1.py`. It is **not** a copy of MOVE-1's. MOVE-1's
harness drove `PatrolRunner` itself — it owned the clock, the sensing and the
submit call — so what it measured was the policy. This card's claim is about
the product, so this harness says `submit_realtime_transcript("Go explore.")`
and then only **watches** `runtime.snapshot()` at 4 Hz. It never constructs a
policy, a runner or a sense. (Verifier's standing lesson: find the product
caller and re-run the headline rows through it.)

Conditions: scene `city_block`, `--static-city`, `safety.person_stop_m: 0.7`
(P1-E's prototype value), camera ingress on with MOVE-1's own 8-query batch,
`memory.path: ":memory:"`, 120 s budget, 479–480 samples per run.

```
evidence/roam_static_20260822T103929Z_armB_alternating/summary.json
   net 3.366806  path 17.825594  contacts 0  min_clearance 1.099032
evidence/roam_static_20260822T104145Z_armB_alternating/summary.json
   net 2.048318  path 21.216462  contacts 0  min_clearance 1.058052
evidence/roam_static_20260822T104354Z_armB_alternating/summary.json
   net 20.674462 path 27.611322  contacts 0  min_clearance 1.160547
```

Arm A (shipped policy, the same harness, the same conditions) is kept in full
at `evidence/roam_static_2026082?T10{3043,3310,3522}Z_armA_fixed_turn_sign/`.
Its diagnosis — max excursion 2.16 m at t = 11.3 s then home again, bounding
box 1.80 × 2.19 m, 1404° of heading change, 18 avoidance turns all one way —
is what the fix is derived from and is reproducible from the stored traces.

### The second arm: dynamic city (MOVE-1's D3 — reported, not a gate)

`evidence/roam_dynamic_20260822T104612Z/summary.json`: net **1.576195 m**,
path 6.613 m, **24 collision ticks in 4 episodes**, min person clearance
**0.0 m**.

Stated plainly, because it is the row most easily mis-read: **the robot was
stationary through every contact.** Its x/y are identical to 4 dp across each
episode and the policy's reason was `turn_contact` — the contact branch, which
turns and never translates. These are pedestrians walking into a robot that is
turning in place, not a robot driving into anyone. It is exactly why MOVE-1's
D3 ruled the dynamic city out as a controllable denominator, and it is why the
gate is the static arm.

### The navigator's clock (card item 4)

`evidence/nav_instruct_minival_with_time_s.json` vs
`evidence/nav_instruct_minival_time_s_seeded_out.json` — the 25-episode
minival, `--mode candidate`, run twice: once as delivered, once with the
`time_s` line seeded out of `headless_city` (restored byte-identically after,
`__pycache__` purged between).

```
sha256 of the report, excluding report_id and elapsed_s:
  with time_s : f64dedd25720ddeb07144f426b79548f98616ea0106aca599c90156218e0ccfe
  seeded out  : f64dedd25720ddeb07144f426b79548f98616ea0106aca599c90156218e0ccfe
  IDENTICAL
```

The only differing fields are `report_id` (a timestamp) and `elapsed_s`. At the
eval's 10 Hz control period the supplied dt **is** 0.1, so the frozen rows
cannot move — which is the point: the fix is a no-op at the one rate the old
literal happened to be right for.

`evidence/navigator_clock.json` is the other half, `pipeline.py:1949-1955`'s
own arithmetic applied to the clock the shipped builder now supplies:

```
control_dt 0.10 (loop_hz 10)  ->  tracker dt after the first tick: [0.1]
control_dt 0.05 (loop_hz 20)  ->  tracker dt after the first tick: [0.05]
```

Before this card no product or eval path supplied `time_s` at all, so **both
rows would read 0.1** and every `float(extras.get("time_s") or 0.0)` read zero.

### Seeded-RED, four guards

Protocol per guard: seed, run and watch it fail, restore, verify the restored
file's sha256 equals the pre-seed sha256, purge every `__pycache__` in the
tree, re-run green. Harness:
`/home/jaewoo-jang/.cache/parcel-roam1/seed.py`.

| Seed | What was disabled | Seeded | Restored |
|---|---|---|---|
| **S1** | the runtime's budget branch in `_step_roam` | `1 failed, 43 passed` | `44 passed` |
| **S2** | the e-stop branch in `_step_roam` | `1 failed, 42 passed` | `43 passed` |
| **S3** | `TOOL_ROAM` removed from `MOTION_TOOLS` | `3 failed, 40 passed` | `43 passed` |
| **S4** | the `time_s` line in `_navigation_extras` | `1 failed, 42 passed` | `43 passed` |

sha256 identical before/after in every case (`runtime.py` `8ec62893…`,
`tool_broker.py` `45037135…`).

**S1's first attempt came back GREEN and that is recorded here rather than
tidied away.** The first budget test could not tell the runtime's guard from
the policy's: `PatrolPolicy` carries the same `budget_s` and returns
`budget_exhausted` from its own ladder, so seeding the runtime's branch alone
still ended the roam. The test was re-cut to the case that separates them — a
roam whose eye has gone quiet, where the policy is never asked anything and
only the runtime's own check can end it — and then it reddened. A roam that
outlives its budget because the camera stopped talking is a dog that never
comes back, so the isolated case is also the one worth guarding.

### Suites and lint

```
.parcel/bin/python -m pytest \
  tests/test_roam1_behavior.py tests/test_move1_patrol.py \
  tests/test_realtime_ingress.py tests/test_realtime_tool_broker.py \
  tests/test_realtime_completion_tense.py tests/test_realtime_answer_beat.py \
  tests/test_realtime_system_initiated_motion.py \
  tests/test_p0b_companion_unlocks.py tests/test_p2a_owner_model.py \
  tests/test_safety_log.py tests/test_prototype_profile.py \
  tests/test_p1e_social_zone_is_config.py tests/test_k6_voice_lanes.py -q
  ->  742 passed
```

The `time_s` change is the wide one, so the nav surface was swept separately:
`-k "headless or nav_instruct or navigation or instructnav or semantic or
tracker"` → **598 passed, 8127 deselected**.

Cross-check against the concurrent cards that share `runtime.py`:
`tests/test_roam1_behavior.py tests/test_curio1_chatter.py
tests/test_turn1_endpointing.py` → **164 passed**.

```
.parcel/bin/ruff check <every path in OWNS>   ->  All checks passed!
ruff ratchet (whole tree vs scripts/ci_ruff_baseline.json):
  baseline 7 · current 7 · NEW beyond baseline: []
```

**Not mine, flagged so it is not misattributed:** a later whole-tree sweep,
after TURN-1 landed more work, showed one new fingerprint —
`tools/replay_turn_detection.py::RUF046`. That file is TURN-1's (`task_21`) and
did not exist when this card started. Every path in this card's OWNS is clean
and the ratchet was at exactly 7 with ROAM-1's changes in the tree and TURN-1's
tool absent.

`scripts/ci_gate.py` was NOT run (P0-E owns it; standing rule 4).

---

## What this does not prove

* **It does not prove the dog explores.** It proves the dog *wanders* under a
  budget without hitting anything. There is no coverage objective, no frontier,
  no memory of where it has been: `net_displacement` between 2.05 m and 20.67 m
  on identical inputs is the honest signature of a random-ish walk. Arm B fixed
  a *circling* defect; it did not add exploration.
* **It does not prove any of this on a robot.** No Go2, no D455, no Orin exist
  on this host. Every number is MuJoCo through the sim socket.
* **The `≥ 1.0 m` row is scene-specific.** `city_block` static, from the
  origin, 120 s. A smaller room, a different start pose, or a longer budget
  will produce a different number, and the metric itself (`|last − first|`) is
  phase-sensitive — a wander that has just looped home scores near zero however
  far it went. Arm A's stored `max_excursion` (2.16 m against a net of 0.14 m)
  is the demonstration of that.
* **The map-growth half of work item 1 is inherited, not demonstrated.** The
  runs had camera ingress on and P1-B's camera→map seams are unconditional in
  `runtime.py`, so the roam's frames reach the learned map by construction —
  but this card measured no map entries and makes no claim about them.
  MOVE-1's map-growth arm is the reference; NM-1 owns what may become a name.
* **`stop roaming` is voice-identity gated.** `gates_kind` returns True for
  every non-emergency class, so an unverified voice cannot *stop* a roam by
  saying "stop roaming" — it must say "stop", which latches the e-stop and is
  strictly stronger. Correct, but worth a decision (below).
* **No hosted model was in the loop.** `TOOL_ROAM` is proven by its shape, its
  gates and its doors, not by a live gpt-realtime session choosing to call it.
  Whether the model *reaches for* the tool is a live-session question.

---

## Deviations from OWNS (declared)

1. **`src/parcel_robot/realtime/config.py` — 11 lines, outside OWNS.**
   `PROACTIVE_MOTION_REFUSED` gained `"roam"`. Required: a committed test
   asserts `set(PROACTIVE_MOTION_ALLOWED) | set(PROACTIVE_MOTION_REFUSED) ==
   set(MOTION_TOOLS)`, which is precisely the "write the verdict down"
   mechanism, and the ninth motion tool has to have a verdict. The file is
   P0-B's (landed) and TURN-1's (concurrent, different region ~line 563); my
   hunk is at ~line 199 and was re-read immediately before the edit. Verified
   present after TURN-1's later writes.
2. **Three foreign test files — 41 lines total.**
   `tests/test_realtime_completion_tense.py` (`ACTIVITY_TOOLS` is pinned to an
   exact set, with the comment *"adding an eighth is a decision somebody has to
   write down"*), `tests/test_p0b_companion_unlocks.py` and
   `tests/test_realtime_system_initiated_motion.py` (`GOOD_ARGUMENTS` tables and
   `_Doors` fixtures parametrized over `MOTION_TOOLS`). Each got a roam row and
   a roam door and nothing else. These pins exist to force exactly this edit.
   No concurrent card's OWNS covers them.
3. **No roam keys were added to `configs/realtime.prototype.yaml.example`**,
   which the card's OWNS names. Reason: that file is the hosted **lane's**
   config and its loader refuses unknown keys, so adding a `roam:` block there
   would have meant editing `realtime/config.py`'s validator — a much larger
   deviation than the one above, for keys that are not lane keys. Roam's
   thresholds are **derived** instead, from `safety.person_stop_m` and
   `safety.obstacle_stop_m` (which the prototype profile already carries), and
   the budget is a clamped argument. `runtime._roam_limits` additionally reads
   an optional `roam:` section from the robot config store for `cruise_vx` /
   `turn_vyaw`; absent, both fall to the patrol package's own defaults, so no
   config file needs to change for the behavior to work.
4. **`prompts/functions/patrol.yaml` was NOT edited** — see the next section.
5. **The card's work item 5 was measured twice.** The pre-registration is
   unchanged and arm A's miss is reported as a miss. Arm B is a fix to a defect
   arm A exposed, inside this card's own OWNS (`patrol/mission.py`), measured
   under identical conditions, and both arms are on the record.

---

## Reconciling with the existing patrol function prompt

`prompts/functions/patrol.yaml` (`id: patrol`, *"Patrol behavior"*) was
**not modified**, and that is the outcome the card's own instruction prefers
("prefer config keys over prompt edits where the behaviour allows").

* **Why not.** The file is digest-pinned as a mirror in
  `runtime_assets/MANIFEST.json` (`3f2ec292854d19ed…`, 205 bytes). A text change
  means a `tools/sync_runtime_assets.py` re-sync plus a manifest edit — a shared
  file, outside OWNS — and per `OWNER_PROMPT_EDIT_PINS_FABLE.md` any prompt-plane
  text change that reaches the SI must bump `SI_VERSION` and register digests.
  None of that buys behaviour this card cannot express otherwise.
* **What carries the lineage instead.** Roam is patrol on a bounded budget, so
  `TOOL_ROAM`'s description carries the prompt's three rules in meaning, in the
  words the model actually reads, via one shared constant
  `ROAM_ONGOING_WORK_NOTE`: *ongoing work with a time budget* · *social things
  can wait for an idle checkpoint between legs* · *a blocker is something to
  report rather than a reason to invent a new route*. A committed test asserts
  "idle checkpoint" and "report"/"blocker" are in the shipped description.
* **The blocker rule is mechanised, not just described.** When the policy
  returns `boxed_in` the runtime ends the roam with reason `boxed_in` rather
  than spinning out the budget or improvising — the prompt's third rule as
  behaviour.
* **The checkpoint rule is published for CURIO-1.**
  `RobotRuntime.roam_idle_checkpoint()` is True when the roam is cruising or
  idle and False while it is turning (negotiating a blocked lane). It is also
  in `snapshot()["roam"]["idle_checkpoint"]`. This region never calls it — it
  exists for CURIO-1's remarks to ride.
* **No parallel function profile was added.** `patrol` remains the one
  behavioural prompt for this class of work, and it is still selected by no
  shipped `agent.functions` list — unchanged by this card.

---

## Owner-gated rows

None of this card's rows needed the owner or hardware, and none is claimed
against either. Two rows the owner *may* want, with their exact commands:

1. **Does the hosted model reach for the tool?** Needs one live gpt-realtime
   session (≈ $0.20). Not run — this card's budget was $0.
   ```bash
   set -a; . ~/.config/parcel/realtime.env; set +a
   scripts/launch_stack.sh --prototype
   # then, into the panel's voice lane: "go explore for two minutes"
   # PASS: /api/state's roam key shows active:true and the model says it is
   #       heading off — and never that it has explored anything:
   #   curl -s localhost:8765/api/state | .parcel/bin/python -c \
   #       'import json,sys; print(json.load(sys.stdin)["roam"])'
   # NOT the panel: corrected by FINISH-1 (task_29 §A5). `snapshot()["roam"]`
   # reaches /api/state (runtime.py's snapshot key) but `ui/index.html`
   # contains the string "roam" ZERO times — there is no roam block to read,
   # and an owner-gated PASS criterion that names a panel widget nobody
   # rendered is a row that cannot be scored.
   ```
2. **Does it feel like a dog going off on its own?** Taste, not a metric; the
   build order puts this in week 2's felt session with the sim viewer visible.
   ```bash
   unset TMPDIR
   .parcel/bin/python scrum/20260822/task_23/evidence/run_roam1.py \
       --budget 120 --static-city
   ```

---

## Handoffs

* **PO-1 / the Go2 gate (`task_27`).** The purchase input, restated after the
  verification and the correction pass — this is the sentence PO-1 should
  quote:

  > **Seven product-path tethered runs, 120 s static-city, three by the
  > executor and four by the verifier: 1.30 / 3.10 / 6.48 / 6.54 / 6.47 / 6.56
  > / 6.57 m net displacement in-block, 0 contacts each, `in_bounds` 7/7,
  > person clearance ≥ 1.08 m each. The tether engaged on 5 of 7 (escape
  > branch: ~10 m out, turned back at ~78 s); the other 2 are the boxed branch
  > (≤ 3.4 m from home, tether never reached), which is the same wander in its
  > other mode and is timing/load-sensitive. Every one of the seven clears the
  > ≥ 1.0 m tell. Pre-tether, for the record: two in-block runs ≥ 1.0 m (3.37,
  > 2.05) plus one that exited the scene (20.67 raw, 12.02 in-block).**

  The tell the build order named — *"ROAM-1 missing 1.0 m
  twice ⇒ the nav stack, not hardware, is the bottleneck"* — **fired on the
  shipped policy and was closed by a one-line policy change inside this card.**
  Read it that way: the bottleneck was real and it was one line deep, which is
  evidence *for* the ordering (software first), not against it.
* **CURIO-1 (`task_24`).** `roam_idle_checkpoint()` and
  `snapshot()["roam"]` are yours to consume. The checkpoint is True while
  cruising and False while turning; `reason` is the policy's own word
  (`advance`, `turn_blocked`, `turn_person`, `turn_hold`, `turn_contact`,
  `boxed_in`, `budget_exhausted`). I did not touch `whisperer.py` or the
  `_step_whisperer` feed region.
* **A follow-up card: roam should explore, not wander.** The 2.05 → 20.67 m
  spread is the metric telling you there is no coverage objective. The pieces
  to join already exist: P1-B's learned map knows which places have been seen,
  and `PatrolPolicy` is a pure function that could take a "least-recently-seen
  bearing" the way it already takes a person bearing. That is a real card, and
  it is the one that would turn this number from "far enough" into "covers the
  room".
* **DOOR-1 (`task_19`).** Roam derives `min_forward_clearance_m` from
  `safety.obstacle_stop_m` + a named margin. If DOOR-1 lands a planner
  inflation envelope with its own setter, `patrol.limits_from_safety` is the
  single place roam reads that number and should be pointed at it.
* **A decision for the owner.** Should an *unverified* voice be able to stop a
  roam? Today it cannot ("stop roaming" is a gated command class); it can only
  latch the e-stop with "stop", which is stronger but also blunter. One line in
  `voice_identity.gates_kind`'s caller would change it. Left as shipped
  (fail-closed) because loosening an identity gate is not a change this card
  should make unasked.
* **Verifier, look here first:** (1) arm A vs arm B and whether you accept a
  measured-then-fixed row reported as two arms; (2) the four seeded-RED
  restores, including S1's first green attempt; (3) the `realtime/config.py`
  deviation, diffed by the `Card ROAM-1` marker rather than by file, since
  TURN-1 owns ~371 of that file's 382 changed lines; (4) whether
  `submit_motion("voice", …)` is the right arbiter channel for a behavior that
  yields by stopping rather than by losing a bid — the alternative was a new
  `SOURCE_PRIORITIES` row in `core/commands.py`, which is outside OWNS and
  changes the arbitration contract for every subsystem.

---

# Correction pass — FINISH-1 (`../task_29`), 2026-08-22 · Claude Opus

Written against `AUDIT_WEEK1_FABLE.md` §ROAM-1 (11 confirmed findings, 1
refuted). Items 1, 2, the tether mechanism and the prototype `roam:` keys
landed in the first, interrupted pass; this pass measured the tethered runs,
put the qualifier on the metric, re-ran every seed on the final tree and fixed
the doc. **Pre-registration for the new measurement:**
`../task_29/PREREGISTRATION.md`, sha256
`d7511531dcb05c230a247370cb945908134c2ea823f08ea39e6201cee4660838`, written
`2026-08-22T12:08:50-04:00` — before the harness was run and after the only
edit that preceded it (the qualifier, which is a metric and not a threshold).

## 1. The three tethered runs — the Go2-purchase input

> **Superseded as the headline number by correction pass 2 §1:** these three
> runs are one trajectory sampled three times, and four further runs (the
> verifier's) show the wander has a second mode. The seven-run statement is the
> one PO-1 reads. The three runs below stand as measured.

**The tether that was ON, and where the number comes from.** The harness config
carries no `roam:` section, so `RobotRuntime.roam_config` is `{}` and
`_roam_limits` passes `tether_m=DEFAULT_ROAM_TETHER_M` into
`patrol.limits_from_safety`: **10.0 m**, with `alternate_turns=True`. That is
the value `limits_from_safety` sets, and `configs/robot.prototype.yaml` carries
the same 10.0 m explicitly. Everything else is identical to the arm-B runs
above: `city_block`, `--static-city`, 120 s, `person_stop_m 0.7`, camera
ingress on with MOVE-1's 8-query batch, `memory.path: ":memory:"`, 4 Hz
sampling, 479 samples each, started through
`submit_realtime_transcript("Go explore.")` and watched through `snapshot()`.

```
unset TMPDIR
.parcel/bin/python scrum/20260822/task_23/evidence/run_roam1.py \
    --budget 120 --static-city --person-stop 0.7 \
    --socket-dir /home/jaewoo-jang/.cache/parcel-finish1 \
    --out scrum/20260822/task_23/evidence/roam_static_tethered_<n>
```

| run | path (m) | net, raw (m) | **net, IN-BLOCK (m)** | `in_bounds` | contacts | min person clearance (m) | `turn_tether` samples |
|---|---|---|---|---|---|---|---|
| **tethered 1** | 26.137395 | 6.540060 | **6.540060** | **true** | 0 | 1.156364 | 11 |
| **tethered 2** | 26.133556 | 6.474798 | **6.474798** | **true** | 0 | 1.164318 | 10 |
| **tethered 3** | 25.990399 | 6.558471 | **6.558471** | **true** | 0 | 1.127456 | 11 |

Both numbers are reported per run, as the card required. They are **equal on
every run** because no run left the plane — which is what `in_bounds: true`
means, and it is the whole point: on a run that stays inside, the qualifier
costs nothing; on a run that does not, it is the difference between 20.67 and
12.02.

| pre-registered row | bound | measured | verdict |
|---|---|---|---|
| **T1** path | ≥ 5.0 m each | 26.14 / 26.13 / 25.99 | **MET 3/3** |
| **T2** net displacement IN-BLOCK | ≥ 1.0 m each | **6.540 / 6.475 / 6.559** | **MET 3/3** |
| **T3** contacts | 0 each | 0 / 0 / 0 | **MET 3/3** |
| **T4** social zone | ≥ 0.7 m each | 1.156 / 1.164 / 1.127 | **MET 3/3** |
| **T5** the qualifier | `in_bounds: true` 3/3, 0 out-of-block samples | true / true / true, 0 / 0 / 0 | **MET 3/3** |

**The tether is not decorative: it fired on every run.** `turn_tether` is the
policy's reason on 10–11 of 479 samples per run, and the furthest each run got
from home on the y axis is 10.01 / 9.97 / 9.96 m — the 10 m radius, found and
turned back from. Before the tether, run 3 of arm B was at |y| = 20.56 m.

**What this bought, plainly.** The untethered spread was 2.05 → 20.67 m over
three runs of identical inputs; the tethered spread is 6.475 → 6.559 m. That is
not a better explorer — there is still no coverage objective and the roam is
still a random-ish wander — it is a wander with a leash, and the leash makes the
metric mean something about *this scene*. A dog that walks off the map is not
producing a bigger number; it is producing a number about somewhere else.

### The in-bounds qualifier, and its seed

`run_roam1.py` grew `in_block_metrics(samples, half_extent_m)` (default 12.0 m
= half of the 24 × 24 m road plane the scene renders). It reports
`net_displacement_m` (raw, unchanged), `net_displacement_in_block_m` (the same
distance evaluated at the last sample before the FIRST exit), `in_bounds`,
`out_of_block_samples`, `left_block_at_s` and the max |x|,|y|.

**Seed (RED), exactly as pre-registered:** the stored untethered runs replayed
through the same function —
`evidence/in_bounds_qualifier_replay.json`:

```
UNTETHERED armB run 3 (the 20.67 m run)  in_bounds=False  raw=20.674462
    in_block=12.015434  out_of_block_samples=138  left_block_at_s=85.4365
    max|x|=2.196  max|y|=20.558
UNTETHERED armB run 1                    in_bounds=True   raw=in_block=3.366806
UNTETHERED armB run 2                    in_bounds=True   raw=in_block=2.048318
TETHERED 1 / 2 / 3                       in_bounds=True   raw=in_block 6.540/6.475/6.559
```

The qualifier flags the run that exited and only that run, and the 12.015434 m
it reports at the last in-plane sample independently reproduces the verifier's
"12.0 m even at the last in-plane sample". A metric that could not tell those
six runs apart is the metric that produced the wrong purchase number.

## 2. The purchase number, restated in all three places

> **SUPERSEDED BY CORRECTION PASS 2 §1 — do not read this section as current.**
> What the headline block, row R2b and the PO-1 handoff say **today** is the
> seven-run, two-mode statement:
>
> > **Seven product-path tethered runs: 1.30 / 3.10 / 6.48 / 6.54 / 6.47 / 6.56
> > / 6.57 m in-block, 0 contacts, `in_bounds` 7/7; the tether engaged on 5/7
> > (escape branch, ~10 m out, turned back at ~78 s); the boxed branch
> > (1.3–3.4 m, tether never reached) is the other mode of the same wander and
> > is timing/load-sensitive; every run clears the ≥ 1.0 m tell.**
>
> The paragraph below is kept as the record of what pass 1 wrote into those
> three places, and it is what pass 2 replaced.

Headline (quote block at the top), row R2b, and the PO-1 handoff ~~now all
read~~ *(pass 1)*: **two in-block runs ≥ 1.0 m (3.37, 2.05) + one run that
exited the scene (20.67 raw, 12.02 at the last in-plane sample); with the
tether: 6.540, 6.475, 6.559 m in-block, 3/3, 0 contacts.**

## 3. The race fix, and the seed that finally reddened

The code landed in the first pass (`_step_roam` re-reads
`self._roam_policy is policy` **inside** `_command_lock` before
`submit_motion`, and cancels `arbiter.cancel("voice")` in the post-check). The
first pass recorded seed **S7 as NOT PROVEN** — it seeded the lock out and the
suite stayed green. This pass found out why, by seeding each half and then
both (`../task_29/evidence/seed_s7.py.txt`,
`../task_29/evidence/seeds_roam1.txt`):

| variant | mutation | result |
|---|---|---|
| control | — | 56 passed |
| **S7a** | the `_command_lock` dropped around the tick | **56 passed (GREEN)** |
| **S7b** | the post-check `if self._roam_policy is not policy: cancel` removed | **56 passed (GREEN)** |
| **S7c** | both halves | **1 failed** — `test_a_stop_racing_an_in_flight_tick_leaves_no_stale_roam_command` |

`runtime.py` sha256 `0ba366aef198a2f0…` identical before and after every
variant, `__pycache__` purged between.

**Read it as it is: the guard is a redundant PAIR.** Belt and braces really are
belt and braces here — the lock closes the window, and the post-check catches
the one command that could get through it — so *this* test, which asks the
arbiter what it holds, is **correctly** green when either half is seeded out
alone.

> **Superseded by correction pass 2 (below).** This section originally called
> that "a real gap … a future edit that removes either half will not be
> caught", and the verifier was right that the framing was wrong: redundancy is
> not a coverage gap. What was actually missing was a test for each half's own
> distinct property — the post-check owns the snapshot after a stop, the lock
> owns the ordering — and both now exist and redden on their own half. See
> correction pass 2 §2.

## 4. Seed S8 — the roam knobs — now PROVEN

Also recorded NOT PROVEN in the first pass. Re-cut to the mutation the test's
own docstring names — `"roam"` commented out of
`config.OVERLAY_INTRODUCIBLE_KEYS` — it reddens 2 tests
(`test_the_owners_roam_knobs_reach_the_behavior`,
`test_a_misspelled_roam_key_is_refused_by_name`); `config.py` sha256
`3f41bbbe2790e516…` identical after; 56 passed restored.

## 5. Seed S9 — the tether — two mutations, both RED

| seed | mutation | seeded | restored |
|---|---|---|---|
| **S9a** | `limits_from_safety` stops passing `tether_m` (always `None`) | **2 failed**, 54 passed | 56 passed |
| **S9b** | the `_tether_blocks` branch removed from `PatrolPolicy.step`'s ladder | **1 failed**, 55 passed (`test_the_tether_turns_a_patrol_back_toward_home`) | 56 passed |

`patrol/mission.py` sha256 `0e962c7b398e8af3…` identical before and after both.

## 6. The ledger write, declared (audit finding 4)

**Deviation, declared here because the first pass did not declare it.** The two
`nav_instruct` minival runs behind row R5 **appended two rows to
`evals/nav_instruct/results/ledger.jsonl`**, which is append-only provenance
owned by the eval, outside this card's OWNS — and one of the two rows came from
a tree with `time_s` deliberately seeded out, i.e. a row describing a build
that never existed. The verifier restored that one file to HEAD
(`git checkout`) and confirmed both rows were ROAM-1's by `report_id`. **No
minival may be run without `LEDGER` redirected to a scratch path**, and this
card ran none. Follow-up for the eval owner, unchanged: a `--no-ledger` switch
on `run_nav_instruct_v1.py`.

## 7. Doc hygiene (audit finding 8)

* **The seed driver and its stdout are now in the evidence**, verbatim:
  `evidence/seed_roam1_driver.py.txt` (the first pass's
  `~/.cache/parcel-roam1/seed.py`, byte-identical, stored as `.txt` **because
  it has three ruff findings** and the tree-wide ratchet is pinned at exactly 7
  fingerprints — a copy under `scrum/` would be linted and would add three) and
  `evidence/seed_roam1_correction_stdout.txt`. This pass's own drivers and
  transcripts are `../task_29/evidence/seed_s7.py.txt`, `seed_s8.sh`,
  `seed_s9a.sh`, `seed_s9b.sh`, `seeds_roam1.txt`.
* **Which tests post-date the seed runs.** The first pass's S1–S4 transcripts
  (43–44 tests) predate the correction pass's four product-door guards, the
  yield test, the race test, the two knob tests and the three tether tests;
  `tests/test_roam1_behavior.py` is **56 tests** today and every seed quoted in
  this section was re-run against that file on the final tree. The counts in
  the older seed table are therefore not comparable with the ones here, and
  that is why both are printed with their totals.
* **Test-file names that do not exist:** re-checked mechanically on this
  document — every `tests/*.py` path it names exists, and every `test_*`
  identifier it names is a real test function. Nothing to remove; if the
  finding referred to an earlier revision, it is already gone.
* **`stop_latency_s` is the harness's sleep, and now there is proof.** In
  tethered runs 1 and 2 it reads **0.5006 s** and **0.5008 s**; in run 3,
  **0.0009 s**. The 0.5 s is `time.sleep(0.5)` in `run_roam1.py`: by the time
  the harness asks for the stop, the 120 s budget has already ended the roam,
  so the harness starts a fresh one, sleeps 0.5 s and only then says "stop
  roaming". **It is not a latency measurement of anything.** The real R3 claim
  is the one in the row above it — `roam.active` is False on RETURN of the
  ingress call — and run 3 (which caught the roam still running) shows what
  that costs: 0.9 ms.
* **The owner-gated PASS criterion** now names `/api/state`'s `roam` key with
  the exact command, because `ui/index.html` contains the string `roam` zero
  times and there is no panel block to look at.

## 8. Gates after this pass

```
$ unset TMPDIR; .parcel/bin/python -m pytest -q tests/test_roam1_behavior.py \
      tests/test_move1_patrol.py tests/test_realtime_ingress.py \
      tests/test_realtime_tool_broker.py tests/test_realtime_completion_tense.py \
      tests/test_realtime_system_initiated_motion.py \
      tests/test_p0b_companion_unlocks.py tests/test_prototype_profile.py
   -> see ../task_29/FINISH1_STATUS.md for the run and its count

$ .parcel/bin/ruff check src/parcel_robot/patrol/mission.py \
      src/parcel_robot/runtime.py src/parcel_robot/config.py \
      scrum/20260822/task_23/evidence/run_roam1.py     -> All checks passed!
```

**Still not proven, unchanged by this pass:** that the dog *explores* (there is
no coverage objective), anything on a robot (no Go2, no D455, no Orin exist on
this host — every number is MuJoCo through a sim socket), that a hosted model
reaches for `TOOL_ROAM`, and whether it feels like a dog going off on its own.

---

# Correction pass 2 — FINISH-1, after Fable's verification of it · 2026-08-22

The verification **accepted** the pass above and then found that its headline
number said more than the data supports. Three corrections, one of them the
purchase number itself.

## 1. The roam is BIMODAL, and three runs could not show it

**What the three tethered runs actually were: one trajectory, sampled three
times.** Measured here from the stored traces — pairwise maximum separation
between the five escape-branch runs (my three plus the verifier's two) over the
whole 120 s:

```
mine1 vs mine2 0.180 m   mine1 vs mine3 0.227 m   mine1 vs ppi 0.101 m
mine2 vs mine3 0.336 m   mine2 vs tsw2 0.114 m    mine3 vs tsw2 0.336 m
```

Over a 26 m path, five runs that never separate by more than 0.34 m are one
trajectory. And that trajectory is the **untethered 20.67 m run's own**: my
tethered run 1 tracks it to within **0.17 m for the first 77 s**, the tether
fires at ~78 s (|y| = 10.01 m), and from there they separate — 9.3 m apart by
t = 100 s, 14.2 m by t = 119 s. First `turn_tether` sample across the five:
**77.4 / 77.4 / 77.9 / 77.9 / 78.4 s**.

**The verifier's other two runs are the second mode.** Same harness, same
config, same product path — one taken under load, one on a quiet machine:

| run | net in-block (m) | path (m) | `turn_tether` | reasons |
|---|---|---|---|---|
| `tests-seeds-weakening/…verify` | **1.303764** | 17.75 | **never** | advance 289 · turn_blocked 92 · turn_hold 98 |
| `product-correctness-owns/roam/run1` | **3.096841** | 20.23 | **never** | advance 329 · turn_blocked 89 · turn_hold 61 |

These two never get near the 10 m radius; they spend the budget negotiating
blocked lanes close to home (`turn_hold` 61–98 samples against 7–12 on the
escape branch) and end 1.3–3.1 m out. They are the same shape as the
**untethered** arm-B runs 1 and 2 (3.37 m, 2.05 m, max |y| ≈ 2.7 m). So the
2.05 → 20.67 m spread was never noise around one behaviour: **the wander has
two modes**, and which one a run takes depends on timing and machine load, not
on a setting.

**The restated purchase input, everywhere it appears** (headline, R2b, the PO-1
handoff, and `../task_29/FINISH1_STATUS.md`):

> **Seven product-path tethered runs: 1.30 / 3.10 / 6.48 / 6.54 / 6.47 / 6.56 /
> 6.57 m in-block, 0 contacts, `in_bounds` 7/7; the tether engaged on 5/7
> (escape branch, ~10 m out, turned back at ~78 s); the boxed branch
> (1.3–3.4 m, tether never reached) is the other mode of the same wander and is
> timing/load-sensitive; every run clears the ≥ 1.0 m tell.**

**Evidence, read-only, the verifier's own runs:**
`~/.cache/parcel-fable-verify-task_29/ppi/roam_static_tethered_verify/`,
`…/tests-seeds-weakening/roam_run/roam_static_tethered_verify{,2}/`,
`…/product-correctness-owns/roam/run1/` — each with its `summary.json` and
full 4 Hz trace. Mine: `evidence/roam_static_tethered_{1,2,3}/`.

**No more roams were run to "improve" the spread.** The honest statement is the
fix; a fourth escape-branch run would only have deepened the sampling error.
Coverage is **ROAM-2 (`../task_33`)**, and the tell it should carry is not a
bigger number but a smaller spread.

## 2. The race guard: a redundant pair, not a coverage gap

§3 of the first correction pass called the pair "a real gap … a future edit
that removes either half will not be caught". **That framing was wrong and the
verifier is right:** the lock and the post-check are each *independently
sufficient* to keep a stale command off the arbiter, so a test that asks the
arbiter what it holds is *correctly* green when either half is seeded out
alone. Redundancy is not a gap. What was missing was a test for each half's
**own** distinct property, and there are two:

| new test | property | seeded RED (on a COPY of `src/`) |
|---|---|---|
| `test_a_stop_that_wins_the_race_owns_the_snapshot` | after a stop wins the race, `roam_snapshot()["reason"]` is `owner_stopped` and `ticks` has not moved — only the **post-check** provides this; without it the in-flight tick writes `advance` and `ticks + 1` over the stop | **post-check removed → 1 failed**, 57 passed |
| `test_no_roam_command_is_submitted_after_the_stop_returns` | no `voice` command is submitted after `stop_roam` has returned to its caller — only the **lock** provides this ordering; the post-check cancels the stale command microseconds later and leaves no trace in `arbiter.snapshot()` | **lock removed → 1 failed**, 57 passed |

Control on the unseeded copy: **58 passed**. Seeded on a **copy** of `src/`
(`../task_29/evidence/seeds_correction2_race.txt`), not in the tree, because
Batch-A executors are editing `runtime.py` right now and a seed in place would
put a defect into somebody else's targeted run; the child process asserts it
imported `parcel_robot` from the copy before any test runs, and the product
`runtime.py` sha256 (`998f67939dc26739…`) is identical before and after.

## 3. The harness hashed a store the product does not use

`run_roam1.py` hashed `~/.parcel/parcel_memory.sqlite3`, which **does not exist
on this host** — so `owner_store.unchanged: true` in all three run summaries was
a sentence about nothing. It now reads `memory_path.owner_store_paths()[0]`,
the product's own authority, exactly as `run_curio1_roam.py` does, and records
`path`, `exists`, both sha256s **and both mtimes**.

**The claim the old check could not make, made properly.** The product's owner
store is `<repo>/parcel_memory.sqlite3`; it exists; its mtime is
**2026-08-22 02:19:01**, hours before the 12:09–12:16 measurement window, with
no `-wal`/`-shm` beside it. The three tethered runs did not open it. A
15-second smoke run of the corrected harness reports
`sha256 0373297f8187…` unchanged, `mtime` unchanged, `unchanged: true` — about
the right file this time.

## 4. The harness was writing into the repository's `logs/`

`duplex.log_dir` defaults to the relative path `logs/duplex`, so every
measurement run left a session log inside the repository (gitignored, but the
directory already holds ~13 000 files and 305 MB and none of it is this
harness's to grow). The harness now writes a `duplex:` section pointing at
`<--socket-dir>/duplex-logs`, with `--log-dir` to override. Verified on the
smoke run: the session log `ad1324146b5b.jsonl` landed in the scratch directory.
The three files the measurement runs left behind are **not** deleted — other
sessions were writing into that directory in the same minutes (61 files in the
seven minutes before the smoke run alone) and deleting somebody else's log to
tidy up mine is the worse trade.

## 5. The pre-registration ordering, stated

`PREREGISTRATION.md` was written at **12:08:50** and `run_roam1.py` was saved
again **14 s later**. What changed in those fourteen seconds was the
`--socket-dir` argument and nothing else — the metric
(`in_block_metrics`, named in the pre-registration itself) and every threshold
were already in the file when the pre-registration was hashed. The
`--log-dir`/`owner_store_paths` changes above are correction pass 2's and are
declared here rather than folded into that file.
