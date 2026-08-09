# Sprint 2026-08-06 · task_2 — NAV_E2E_V1: comprehensive e2e navigation suite

> **SUPERSEDED BY SELF-EVALUATION + OWNER APPROVAL (2026-08-06).** On the
> owner's challenge ("is this necessary, or too cluttered/repetitive?") the
> original design below was evaluated as ~80% redundant: NAV_INSTRUCT
> already owns the instruction matrix/ledger for nearly the same families;
> the clickable `/evals` UI with pre-run goal overlay already exists
> (task_6 N-O4); `walk_with_me` already owns integration scenarios; and the
> parallel runner was premature at ~10 realtime cases (~30 min sequential
> is nightly-fine). A third navigation harness would create a second source
> of truth for the same instructions (U32 disagreement class) and deepen
> the 82-vs-13 nav/behavior test imbalance.
>
> **APPROVED SLIM PLAN (owner, 2026-08-06) — all cards delegated to Opus,
> Fable evaluates on completion:**
>
> | Card | Content |
> |---|---|
> | SLIM-1 | 4–6 new product-path cases in the EXISTING `tests/test_voice_nav_e2e.py`: "go to the owner"/"come here", "walk around the owner"/"circle the owner once", "sit next to the bench", "sit next to the lamppost", + absent-target honesty case. No new harness. |
> | SLIM-2 | Pure predicates in existing scoring: `SitNextTo` (next-to band + Sit posture + settle; facing rule: face owner if visible) and owner-anchored (moving-anchor) arrival. |
> | SLIM-3 | `/evals` "voice mode" toggle: clicked instruction routes through `handle_text` on the live runtime (product path) instead of the navigator; sequential by construction. |
> | — | Genuine capability gaps found by the new cases get honest xfail pins with attribution (the N11 precedent), never silent skips. Dynamic-traffic lane stays known-failure. |
>
> The original (rejected) design is preserved below for the record.

**Type:** design for approval. Implementation board at the end dispatches
only after the owner signs off on this shape. *(Superseded — see banner.)*

**Owner ask:** a comprehensive end-to-end navigation eval on the current
MuJoCo setup that can also *launch the UI of the dog navigating*. Tests
include "go to the sidewalk", "go to the owner", "walk around the owner",
"sit next to the bench", "sit next to the lamppost", … Parallel when
headless/automated; **sequential UI launches for debugging**.

## 1. Position in the eval stack (reuse, don't rebuild)

Three things already exist and this design composes them rather than
duplicating any:

- **The product-path e2e pattern** (`tests/test_voice_nav_e2e.py`): sim
  subprocess + full `RobotRuntime` + `handle_text`, with the 4-stage gate
  (admission → task → terminal → arrival by the K0 GoalRegion authority
  AND the system's own verified success). Proven necessary — it caught the
  admission regression the navigator-level evals could not see.
- **NAV_INSTRUCT** (`evals/nav_instruct/`): seeded generator, GoalRegion
  authority, SR/OSR/SPL/failure-attribution scoring, append-only ledger,
  frozen-baseline discipline. It drives `DirectiveNavigator` directly —
  faster-than-realtime, stays as the hillclimb inner loop.
- **The UI**: web panel `/evals` page (scenario list, run/batch/select
  APIs, goal-region thumbnails), `/viewer` GoalRegion overlay
  (`payload["eval"]`), native MuJoCo viewer window, `launch_stack.sh`.

**NAV_E2E_V1 = the product-path pattern, generalized to a scenario matrix,
with a parallel headless runner and a sequential UI debug mode.** It is the
outer acceptance loop; NAV_INSTRUCT remains the inner hillclimb loop. Both
score with the same GoalRegion authority so a disagreement between loops is
itself a defect (U32 class).

## 2. Scenario matrix

| Family | Instructions (product bar) | Arrival predicate (all also require: agent-issued stop + system verified success + zero hard collisions) |
|---|---|---|
| region goal | "go to the sidewalk", "go to the crosswalk" | inside region polygon (K0), settled |
| owner approach | "go to the owner", "come here" | inside disc anchored at the **owner's final position** (moving anchor), settled, facing owner |
| owner orbit | "walk around the owner", "circle the owner once" | swept angle ≥ 2π·revolutions within radius band around owner track, then settled (existing orbit verification reused) |
| object towards/near | "walk towards the lamppost" | towards/near band (K0), settled |
| **placement + posture** | "sit next to the bench", "sit next to the lamppost" | inside `next_to` band (K0 relations) AND `Sit` posture active AND settled — a **new compound predicate** `SitNextTo` joining the task_3 settle grammar with the K0 band; default facing rule: face the owner if visible, else face open space |
| follow regression | "follow me" (short scripted owner walk) | formation band held ≥ N s, zero false-follow (regression lane — must not break) |
| honesty | "go to the fountain" (absent) | bounded search then honest report; **no motion claim, no arrival claim** |

**Variants per scenario:** `static` city (tier A/B start poses: goal
visible / out-of-frustum, forcing the scan ladder) and `dynamic` city
(scripted pedestrians — the traffic lane; sidewalk-dynamic stays a known
failure until the final-approach card lands, and the runner records it as
such rather than hiding it). Seeded start poses/owner placement per episode;
the matrix is generated, frozen, and versioned like NAV_INSTRUCT episodes
(add, never mutate).

Initial size: 7 families × ~2 instructions × 2 tiers × 2 city modes ≈ **40
episodes** + 8-case PR minival subset.

## 3. Execution architecture

One abstraction, three front-ends:

```
EpisodeHost (per episode, fully isolated)
  ├─ sim subprocess: python -m parcel_robot.sim --socket <tmp>/sim.sock
  │    [--static-city] [--ui → viewer window on display | headless → EGL]
  ├─ RobotRuntime via web_panel.build_runtime(use_llm=False)
  ├─ inject instruction via runtime.handle_text(...)
  ├─ poll executive → terminal state (budget chain: inner < 240 s step < 270 s case)
  └─ score: 4-stage gate + family predicate; emit episode JSON + trace
```

**Front-end A — headless parallel runner** (`evals/nav_e2e/runner.py`):
worker pool of EpisodeHosts (default `min(4, cpu//3)` — each episode is a
sim process + runtime thread pair; realtime sim means wall-clock ≈ slowest
episode per wave, ~40 episodes / 4 workers × ~2 min ≈ **~20 min full
matrix**). Results: per-episode JSON + one append-only ledger row
(`nav-e2e-v1-<utc>-<nonce>`), baseline/candidate modes, paired seeds,
McNemar for promotion — the NAV_INSTRUCT discipline verbatim.

**Front-end B — sequential UI debug mode** (`evals/nav_e2e/runner.py
--ui`): one episode at a time, on the real display —
1. launches the sim **with the native MuJoCo viewer window** (no EGL) and
   the web panel (`/viewer` + `/evals`), opens the browser once;
2. **shows the goal region overlay before the run starts** (existing
   `payload["eval"]` overlay — the task_6 hard gate: region visibly marked
   pre-run, verdict shown at end);
3. injects the instruction, streams live status (existing `/api/evals/status`);
4. at episode end shows the verdict + failure attribution, then **waits**
   (Enter in terminal or Continue button on `/evals`) before the next
   episode — sequential by construction;
5. `--ui --only <episode-id>` replays a single failing episode from a
   headless run's ledger row (the debugging loop: fail in CI → replay in UI).

**Front-end C — pytest gate** (`tests/test_nav_e2e_gate.py`, `-m slow`):
the frozen 8-episode minival subset, sequential, deterministic — the CI
gate. The existing `test_voice_nav_e2e.py` cases fold into this file as the
first minival members (no duplicate harness).

## 4. UI wiring details (all existing seams)

- `/evals` page gains the `nav_e2e` family via `/api/evals/scenarios`
  (list + thumbnails from the frozen matrix), `run` (single), `batch`
  (headless parallel trigger), `select` (UI-mode queue).
- Viewer overlay renders exactly the scorer's GoalRegion (polygon/band/
  disc) — for owner-anchored predicates the overlay tracks the live owner.
- One gap to close: the sim's UI/headless split is currently implicit
  (EGL env vs display). Add an explicit `--headless` flag to
  `parcel_robot.sim` so mode selection is intentional, not environmental.

## 5. New verification pieces (the only genuinely new logic)

1. **`SitNextTo` predicate** (pure, instructnav/scoring): inside `next_to`
   band + `Sit` posture active (from runtime activity state) + settle hold
   + facing rule. Provenance: task_3 settle grammar + K0 relations.
2. **Owner-anchored arrival** (pure): disc/band predicates re-anchored to
   the owner's final/live position (the generator's `circle_owner` disc
   already does this statically; make the anchor dynamic).
3. **Directive coverage check**: "go to the owner"/"come here" must route
   to the approach lane (COME closed intent — relation `follow`, fixed
   this morning), "sit next to X" must compile navigate + relation + Sit
   through PlanIR (compound plan — exercises the task_6 parser work).
   Any instruction on the product bar that fails to route is an episode
   failure attributed `L0_route`, not a skipped test.

## 6. What this suite will honestly show on day one

Expected reds, recorded not hidden: sidewalk-dynamic (known, N11 residual
final-approach card), possibly "sit next to the bench" end-to-end (the
compound navigate+settle path has unit coverage but has never run
product-path e2e), and U31-class termination artifacts if the hold/step
interaction reappears at this layer. That is the point of the suite —
baseline first, every later claim a delta.

## 7. Delegation board (dispatches on owner approval)

| Card | Content | Owner lane |
|---|---|---|
| E2E-S1 | Scenario matrix generator + frozen episode set (seeded, versioned) + `SitNextTo` / owner-anchored predicates (pure) + unit tests | Sol (new pure modules) |
| E2E-O1 | `evals/nav_e2e/runner.py`: EpisodeHost extraction from `test_voice_nav_e2e.py`, worker-pool parallel mode, ledger writer | Opus (existing files + new eval runner) |
| E2E-O2 | UI mode: `--ui` sequential flow, `--only` replay, sim `--headless` flag, `/evals` family wiring + owner-anchored overlay | Opus |
| E2E-O3 | `tests/test_nav_e2e_gate.py` minival (folds `test_voice_nav_e2e.py` in) + baseline freeze row | Opus |
| E2E-R | Cross-review (Opus↔Sol) + Fable arbitration, per this sprint's precedent | both + Fable |

Estimated: Sol ~1 session, Opus ~1–2 sessions, review round ~1.

## 8. Open questions for the owner (defaults chosen, flag if wrong)

1. Facing rule for "sit next to X": default *face the owner if visible*.
2. Parallelism cap: default 4 concurrent sims (realtime each; laptop-safe).
3. Should the dynamic-traffic lane block the gate now, or stay
   known-failure until the final-approach card? Default: known-failure
   (same xfail discipline as today).

---

# Implementation — SLIM-1/2/3 (Opus, 2026-08-06)

All three approved cards landed. Everything below is measured on this
machine, on the product path, on the dates given. Where a case fails it is
pinned `xfail` with the measurement in the reason string (the N11
precedent); nothing is skipped and nothing is claimed that a run did not
show.

## Cards

| Card | Landed | Where |
|---|---|---|
| SLIM-2 | `SitNextTo` compound predicate, owner-anchored (moving-anchor) arrival, orbit sweep scoring — all pure, in the existing scoring module | `src/parcel_robot/instructnav/scoring.py`, unit tests `tests/test_instructnav_compound_predicates.py` (38 tests) |
| SLIM-1 | 7 new product-path cases in the existing file, same `_LiveRuntime` / `_run_command_to_terminal` harness (extended, not replaced) | `tests/test_voice_nav_e2e.py` |
| SLIM-3 | `/evals` **voice mode**: the selected scenario's instruction goes through `runtime.handle_text` on the live runtime; goal overlay pre-run, verdict at end; sequential by construction | `src/parcel_robot/eval_panel.py`, `src/parcel_robot/web_panel.py`, `src/parcel_robot/ui/evals.html`, API tests `tests/test_eval_panel_voice_mode.py` (8 tests) |
| (in-lane fix) | Router rule `come_to_owner` — the COME closed intent was unreachable from the product bar | `src/parcel_robot/brain/router.py`, tests in `tests/test_brain_router.py` + `tests/test_runtime.py` |

## SLIM-2 — the pure predicates

`evaluate_sit_next_to(...) -> SitNextToOutcome` joins three gates and
reports **each one separately**, so a failure names itself: `in_next_to_band`
(the K0 `object_next_to_goal_region` band — no second set of radii),
`sit_posture` (`is_sit_posture`, normalising `Sit`/`sit_down`/`SITTING` onto
the lowercase skill id the runtime actually records), and `settled`.

**Facing decision (task_2 §8 open question 1): measured, report-only in v1.**
`facing_owner` is `True`/`False` when the owner is visible and a heading is
supplied, and `None` — *unknown*, never a silent `False` — otherwise.
`require_facing=True` gates on it for callers that want that. Rationale, in
the function docstring: the rule is a chosen default, the yaw is a body yaw
rather than a gaze vector, and **no product-path run had ever measured what
the settle heading is** — gating on an unmeasured convention manufactures
failures that say nothing about capability. Flip the default when the
measured distribution justifies a threshold.

`owner_anchored_goal_region(owner_xy, ...)` / `evaluate_owner_arrival(...)`
take the anchor as an argument. The NAV_INSTRUCT `follow_owner`/`circle_owner`
discs are frozen at the commissioning pose (2.0, −0.5) so the episode set
stays byte-reproducible; that is right for the seeded matrix and wrong for a
live run where the owner moves. In the "come here" case below the owner is
3 m from that frozen centre, and the static disc would have scored the run
wrong by 3 m.

`swept_angle_rad` / `orbit_revolutions` score an orbit from a pose polyline:
signed wrapped bearing deltas (so back-and-forth cancels) plus the fraction
of samples inside the radius corridor, reported **separately** — a full sweep
at 8 m is a sweep, not an orbit.

## SLIM-1 — per-case e2e outcomes

Run 2026-08-06, `-m slow`, static city (default fixture), split into three
pytest invocations by node id (total wall time ~9.5 min exceeds the ~9 min
single-invocation rule). `CASE_DEADLINE_S` unchanged at 270 s — no budget
bump was needed; the slowest new case terminates at 85 s.

| # | Case | Outcome | Time | Attribution / evidence |
|---|---|---|---|---|
| 1 | `go to the sidewalk` (existing) | **pass** | 24.0 s | unchanged |
| 2 | `can you walk towards the lamppost` (existing) | **pass** | 6.0 s | unchanged |
| 3 | `go to the sidewalk` + pedestrian traffic (existing) | **xfail** | 240.1 s | N11 residual, reason string unchanged; still `step_timeout` against the 240 s NavigateTo budget |
| 4 | `go to the owner` | **xfail** | 38.0 s | **N12.** Routes and admits cleanly, then compiles to `NavigateTo` asking the *semantic map* for an object labelled "owner". The owner is a tracked entity, not a map object. Ladder runs `scan_behavior_rotate` → `search_entity_frontier` → `search_entity_align`, task ends `failed` / `semantic_target_not_found` at (0.59, −1.31) — 1.4 m *away* from an owner that was visible at 2.06 m. L2a vocabulary/grounding. |
| 5 | `come here` (+ `stay`) | **pass** | 28.0 s | Approach lane works: admits `local_plan_sketch`, `FollowFormation(relation="follow")` succeeds, follow enabled in `direct` mode, closes **5.03 m → 1.78 m** on the owner's final observed position, holds, and `stay` releases it. Only reachable because of the router fix below. |
| 6 | `walk around the owner` | **pass** | 51.0 s | `spatial.state=completed`, `reason=orbit_complete`, `progress=1.0`; independent sweep from the polled track **0.986 revolutions**, 100 % of samples inside the 1.0–2.2 m corridor. |
| 7 | `circle the owner once` | **pass** | 50.0 s | same |
| 8 | `sit next to the bench` | **xfail** | 85.0 s | **N13 + N11 family.** *Posture:* plan is one step, `NavigateTo(directive="sit next to the bench")`; no Sit step exists, `runtime._last_posture == "unknown"` at the end — the posture gate cannot pass by construction. *Placement:* also fails — `navigation_no_progress` at (−0.84, 2.58), **1.71 m** from the bench centre, 0.21 m outside the K0 `next_to` band, after repeated `Proximity stop: obstacle too close` events **in static city with no traffic**. |
| 9 | `sit next to the lamppost` | **xfail** | 15.0 s | **N13 + N11 family.** Same posture gap. Placement is a 7 cm near-miss: `semantic_arrival_verification_failed` at (0.19, 1.58) — **1.572 m** from the lamppost, 0.072 m outside the 1.5 m band edge, after travelling 1.6 m straight at the target. |
| 10 | `go to the fountain` (absent) | **pass** | 38.0 s | Admits (by design — `NavigateTo` does not require `target_grounded`), runs a bounded search, ends **failed** with `semantic_target_not_found`, leaves the navigation lane disabled, makes **no arrival claim** in chat or events, and emits the honest error event `Navigation failed for fountain: semantic_target_not_found`. |

Batch results as run: `4 passed, 1 xfailed in 214.8 s`;
`2 passed, 2 xfailed in 137.9 s`; `1 xfailed in 242.2 s`.
**Slow suite total: 6 passed, 4 xfailed, 0 failed, 0 skipped — 595 s across
three invocations.**

### Notes on two case designs (both deliberate, both documented in-test)

**"come here" termination condition.** COME dispatches
`FollowFormation`, a *persistent* behaviour whose task record is verified on
`follow.state` and therefore reports `succeeded` about **one second** after
dispatch — long before the robot is anywhere near the owner. Gating on task
state alone would have passed with no approach at all. The case gates on
admission + task success + **formation band held** + owner-anchored predicate
+ settle, then issues `stay` (which is what actually releases a persistent
follow) and asserts the release.

**"come here" scene setup.** The owner is walked 3 m up the block first,
through the same `move_owner` control the web panel exposes. This is scene
setup, not behaviour seeding: from the commissioning pose the robot already
stands 2.06 m from the owner while the formation distance is 1.6 m, so *any*
band containing the final pose also contains the start pose and the case
would be scored vacuously. Moving the owner is what makes the closing motion
real (5.03 → 1.78 m) and what makes the moving-anchor predicate meaningful.
The test asserts the starting gap is > 3 m and that the robot closed > 1 m,
so a regression cannot make it vacuous again silently.

## Gap found and fixed in-lane: "come here" never worked (U33)

Not on the card, found by verifying routing before writing the case, as
instructed. **Every `"come here"` on the product path dead-ended** with the
generic refusal:

```
last_reasoning_source = "local_plan_fallback"
last_reasoning_error  = "invalid_argument_value at $.steps[0].arguments:
                         value must be one of ['behind']"
reply = "I couldn't admit that command as a safe plan yet. ..."
```

Cause: a **route/registry mismatch**. The COME cap is a *system-authored*
PlanSketch (`sketch_come` → `FollowFormation(relation="follow")`), and only
`direct_skill` frames select the system registry — the one registry that
admits `relation="follow"` (arbitration OB-2, `validator.py`
`system_authored` gate). The deterministic router had no COME grammar, so
these phrases fell through to `_PHYSICAL_CUE` → `deliberative_plan` and were
validated against the *model-facing* registry. This morning's OB-7 fix
(compile COME to `follow`, not `behind`) was real and correct; it was simply
unreachable from the product bar.

**Fix (deliberately narrow):** a `come_to_owner` rule in the router,
adjacent to the existing `follow_owner` / `hold_position` rules, whose phrase
membership is read from `parse_closed_intent` so there is no second copy of
the grammar to drift. The route stays the deterministic router's decision —
the alternative (rewriting `frame.route` inside the agent) would have moved
authority selection *below* the router, which is the thing the OB-2 design
forbids.

**Why it was invisible:** nothing anywhere had ever called
`handle_text("come here")`. The existing tests proved the parser, the cap and
the sketch *compiler* in isolation and never ran the sketch through
`PlanValidator`. That is the general defect, and it is filed as **U33**, not
as a one-line enum bug: the other closed intents (`PAUSE`, `RESUME`,
`FASTER`, `SLOWER`, `GOAL_AMEND`) have exactly the same shape of coverage.

Regression pins added: router route + the negation/compound cases that must
*not* widen (`tests/test_brain_router.py`), and
`tests/test_runtime.py::test_come_here_admits_the_system_approach_sketch`.

## SLIM-3 — /evals voice mode

`EvalPanelState.start_voice(episode_id, runtime)` runs one scenario through
`runtime.handle_text`, polls the executive to a terminal state (budget 270 s,
the same inner < step < eval ordering as the e2e gate), samples poses from
the panel's own `/api/state` payload into a scorer-shaped trace (speed
differentiated from consecutive poses rather than read from a telemetry
field), and scores with `score_episode` against **the same GoalRegion the
overlay already published pre-run** via `select()`.

The verdict reports `system_verified` and `predicate_success` separately and
requires **both** for `success` — the U32 rule ("a claim without the
predicate is a failure, and vice versa") applied at panel level.

**Sequential by construction, no new queueing:** `start_voice` reuses the
existing `status == "running"` guard that headless and batch runs already
share. A second request is refused with HTTP 409, not queued
(`test_voice_mode_is_sequential_by_construction`). Verified rather than
assumed.

Surface: `POST /api/evals/run` accepts `mode="voice"` or `voice_mode=true`;
the `/evals` page gains a "Voice mode (product path)" checkbox that changes
what the existing **Run** button does. **Defaults are unchanged** — unchecked
is `headless`, and `mode="live"` still uses the voice-session path
(`test_default_run_mode_is_unchanged_and_never_touches_handle_text`,
`test_live_mode_still_uses_the_voice_session_path`).

Tested at API level with the runtime-injection seam the panel tests already
use (`RuntimeHTTPServer(addr, fake_runtime)`), plus a monkeypatched fresh
`EvalPanelState` because `EVAL_PANEL` is a module singleton.

## Suite state

| Run | Result |
|---|---|
| `pytest tests/ -q -m "not slow"` | **2016 passed, 2 skipped, 0 failed** (15 deselected), 59.8 s |
| selected-count delta vs the 2026-08-06 baseline | 1963 → 2018 = **+55**, exactly the 55 new non-slow tests (38 predicate + 8 voice-mode + 8 router + 1 runtime). No pre-existing test changed state. |
| `pytest tests/test_voice_nav_e2e.py -m slow` | **6 passed, 4 xfailed, 0 failed** across three invocations by node id (595 s total; a single invocation would exceed the ~9 min rule) |
| `pytest tests/test_follow_bench_v1.py -m slow` | 5 skipped (opt-in behind `PARCEL_FOLLOW_BENCH_SLOW=1`) — unchanged, and the source of 5 of the 7 skips in the recorded baseline |
| **whole tree, every test executed** | **2022 passed, 7 skipped, 4 xfailed, 0 failed** (2033 collected) vs the 2026-08-06 baseline of 1963 / 7 / 1 (1971 collected) |
| ruff | clean on all touched files |

## Backlog filed

| Item | Content |
|---|---|
| **N12** | `"go to the owner"` cannot reach the owner — bridge owner-referring targets to the owner track (or route them to the approach cap). Flips case 4. |
| **N13** | `"sit next to X"` never sits — compile it as navigate **+ settle** so a posture step exists. The predicate and its unit tests are already in place, so the fix has a scoreboard on day one. Flips the posture half of cases 8–9; the placement half belongs to the N11 final-approach card. |
| **U33** | Closed intents were counted as shipped without ever being spoken. COME instance fixed and pinned; the *class* stays open for the other five closed intents. |

## Files touched

Source: `src/parcel_robot/instructnav/scoring.py` (new pure predicates; also
one pre-existing `PLR1730` ruff error in `object_near_envelope_m`, from
another lane's uncommitted change, fixed to keep the file lint-clean),
`src/parcel_robot/brain/router.py`, `src/parcel_robot/eval_panel.py`,
`src/parcel_robot/web_panel.py`, `src/parcel_robot/ui/evals.html`.

Tests: `tests/test_voice_nav_e2e.py` (extended harness + 7 cases),
`tests/test_instructnav_compound_predicates.py` (new),
`tests/test_eval_panel_voice_mode.py` (new), `tests/test_brain_router.py`,
`tests/test_runtime.py`.

Records: `backlog/NEXT.md` (N12, N13), `backlog/UNVERIFIED.md` (U33), this
file.

## Deliberately not done

- **No new harness, no runner, no episode matrix.** The rejected design's
  `evals/nav_e2e/` package, parallel worker pool, UI replay mode and
  `--headless` sim flag are all out of scope for the slim plan and stay
  unbuilt.
- **Facing does not gate success** (see SLIM-2 above).
- **Dynamic-traffic lane stays known-failure**, per the approved plan.
- The other closed intents named in U33 were **not** swept — that is the U33
  card, and doing it here would have been unreviewed scope.
