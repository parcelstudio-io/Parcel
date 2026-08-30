# C0 + C2 · ARRIVAL-SETTLE-1 — executor STATUS (Opus, parcel session)

Card: `scrum/20260829/task_2/C0_C2_ARRIVAL_SETTLE.md` · Verifier: Fable · Wave A
Written incrementally. Every number is quoted beside the bar it answers.

## Pre-flight (2026-08-29 21:4x EDT)

- Tree: `main` @ `a9b85a1` at start; the integrator committed `704ba5c` (research + this board) mid-card. `git diff a9b85a1 704ba5c -- src evals scripts tests configs prompts` is EMPTY, so every clean-worktree number here is a HEAD number. The owner's uncommitted diff is present in the working tree and is not touched.
- Host: `uptime` load 1.66 / 3.59 / 4.78 at start — heavy runs allowed, ≤ 16 workers.
- Scratch: `/home/jaewoo-jang/.cache/parcel-0e/c2/` (`PARCEL_MEMORY_PATH`, `NG1_SCRATCH`).
- Every pytest through `~/.cache/parcel-guard/pytest_guard.sh --label C0|C2`, `TMPDIR` unset.

## C0 — decision, recorded BEFORE any edit

**Owner's answer to the (a)/(b) question: NONE — the owner is silent.**
Card default applied verbatim: *"(a) attempted for ≤ 2 h; else (b) with the
attribution written."*

- **Decision: attempt (a) fix-product, wall clock ≤ 2 h from the first RED run.**
  If the honest system verdict is not achieved inside that budget, fall back to
  (b): the recorded re-run under the repository attribution/re-freeze policy with
  the diff attributed to `a379bf4` (the owner's hard-safety change, per
  parcel-fb's clean-worktree bisection).
- Untouchable during (a), per the standing constraints: `obstacle_stop_m 0.65`,
  `apply_reactive_safety`, `finalize_command`, `core/hard_stop.py`, the A3 latch,
  the A6 stop path. Grep-proof at close.

(sections below are appended as each row completes)

## C0 · RED reproduction (verbatim), in a CLEAN worktree

Amendment A1 (parcel-fb, 21:5x) read and binding. Its C0 direction constraint,
its C0(b) cost clause, and its C2 clauses are answered below.

`main` at the start of this card was `a9b85a1`; the integrator committed
`704ba5c` (research + this board) mid-card. `git diff a9b85a1 704ba5c --
src evals scripts tests configs prompts` is **empty**, so every clean-worktree
number below is a HEAD number.

Clean worktree = `git archive HEAD | tar -x -C ~/.cache/parcel-0e/c2/clean`
(git read-only), run with the repo venv and
`PYTHONPATH=<clean>/src:<clean>` so the editable install cannot leak the dirty
tree in. Command and verbatim tail:

```
cd ~/.cache/parcel-0e/c2/clean && env -u TMPDIR \
  PYTHONPATH=~/.cache/parcel-0e/c2/clean/src:~/.cache/parcel-0e/c2/clean \
  ~/.cache/parcel-guard/pytest_guard.sh --label C0clean \
  /home/jaewoo-jang/Desktop/Projects/Parcel/.parcel/bin/python -m pytest \
  tests/test_mutation_panel_freshness.py -q
```
```
E       AssertionError: the committed mutation panel no longer reproduces its own safety-relevant fields on this tree: committed={'collisions': 0, 'authority': {'agreement': 4, 'tolerated_boundary': 1}, 'clean_checks': {'zero_collisions': True, 'no_authority_disagreement': True, 'no_false_arrival': True, 'path_length_plausible': True}} live={'collisions': 0, 'authority': {'agreement': 4, 'authority_disagreement': 1}, 'clean_checks': {'zero_collisions': True, 'no_authority_disagreement': False, 'no_false_arrival': True, 'path_length_plausible': True}} — the hard-safety gate must not certify from it until the divergence is diagnosed
tests/test_mutation_panel_freshness.py:111: AssertionError
FAILED tests/test_mutation_panel_freshness.py::test_committed_panel_safety_fields_still_reproduce
1 failed, 2 passed, 2 warnings in 46.69s
```

Exactly **one** of the three tests is red in a clean worktree. The other two —
including the live whole-panel run — are green there (`passed: True`, 7/7
mutants killed). For the record, the same command in the **dirty** working tree
(owner's uncommitted diff present) fails differently (`live={'agreement': 5}`,
2 failed) — the dirty tree is not the acceptance surface and is not used below.

## C0 · attribution, reproduced independently at single-commit resolution

Per-episode arrival-authority verdict on `PANEL_EPISODE_IDS`, one clean export
per revision (script `~/.cache/parcel-0e/c2/diag_panel.py`, scratch only):

| revision | `nav-region_goal-D-15-1b8b2361` | final pose | dtg (scorer) | reason |
|---|---|---|---|---|
| `f3ecb5c` (parent) | `agreement` | (0.2815, 0.1603) | 2.0685 | `navigation_step_limit` |
| **`a379bf4`** | **`authority_disagreement`** | (2.8113, 0.7495) | 0.0000 | `navigation_step_limit_inside_goal` |
| `HEAD` (704ba5c) | `authority_disagreement` | (2.8113, 0.7495) | 0.0000 | `navigation_step_limit_inside_goal` |
| HEAD + owner's uncommitted `grid_planner.py` **only** | `agreement`, **succeeds** | (2.8410, 0.7470) | 0.0000 | `arrived` |

The other four panel episodes are `agreement` on every revision. At `f3ecb5c`
all five final poses are byte-identical to the committed artifact's
`clean_run.episodes`. **parcel-fb's bisection to `a379bf4` is confirmed**, and
the single-file transplant shows the product fix already exists, unlanded, in
the owner's working-tree `src/parcel_robot/navigation/grid_planner.py`.

## C0 · Amendment A1's first job: WHICH refusal fires on D-15

**None of them.** Not owner-loss, not co-visibility with the stationary human,
not a blocked target-facing pose. The mission never reaches the hardened
two-phase terminal contract at all. Instrumented run (`diag_d15b.py`,
`apply_reactive_safety` wrapped to log requested-vs-returned):

- The episode is **`go to the crosswalk`**. Scorer goal = polygon
  `[[2.35,-0.4],[3.85,-0.4],[3.85,2.0],[2.35,2.0]]`. The system grounds
  "crosswalk" through `PlaceGrounder` to the POI **point** `crosswalk_a`
  at **(3.5, −0.6)** — which is **outside that polygon** (y = −0.6 < −0.4).
  This is NAV-GEN-1 `VERDICT.md` §5.2's crosswalk-POI second oracle, i.e.
  **C1's defect**, surfacing on the panel.
- Frames 0–78 the robot drives 3.0 m toward the POI point. From frame 79 to
  199 it is **motionless at (2.8113, 0.7495)** while the navigator keeps
  requesting `vx = 0.102 m/s`, and **`apply_reactive_safety` returns
  `(0, 0, ~0)` with `meta = 'stopped'` on 105/200 ticks** — the reactive
  obstacle gate (the A6 stop path / `obstacle_stop_m 0.65` floor) is what
  holds it. Notes read `track_goal err=-0.0 dist=1.5|clear`, never
  `person_stop`, never a refusal token.
- The step limit then expires: `navigation_step_limit_inside_goal`.

**The margin is 0.4 mm.** Distance from the final pose to the POI point is
**1.5151 m** against the POI path's **1.50 m** point-goal arrive radius (the
looser radius NAV-GEN-1 §5.2 names). The owner's unlanded `grid_planner.py`
diff moves the same stall 3 cm further along — final pose (2.8410, 0.7470),
distance **1.4996 m** — i.e. it crosses the same threshold by **0.4 mm** and
`arrived` fires. Neither pose is a semantic arrival at the crosswalk; both are
the same reactive-gate stall on either side of one hard radius.

**Verdict on (a).** The system verdict on D-15 is *already honest*: "the
obstacle gate stopped me 15 mm short of my goal point and I ran out of time."
The divergence is not an arrival-authority defect — it is the scorer's polygon
and the system's POI point being **different goals**. Making the system claim
arrival here would require one of exactly three things, and all three are
forbidden by a standing constraint, not by the clock:

1. weakening/bypassing `apply_reactive_safety`, which is holding the robot —
   an untouchable safety floor, and the card's own "without weakening the
   reactive gate";
2. moving the navigator's arrival predicate onto the scorer's polygon — that
   moves the NAV_INSTRUCT frozen digests (**E3**), and it is C1's grounding
   fix, not C2's seam;
3. landing the owner's uncommitted `grid_planner.py` — a wave-A prohibition,
   and in substance a 0.4 mm nudge, not a fix.

Per Amendment A1 — *"'Make the system verdict honest' is never implemented as
'claim arrival past a refusal designed to fire'"* — and a fortiori never as
"claim arrival past a stop the obstacle gate is issuing". **(a) is off the
table. C0 proceeds as (b).** Elapsed at decision: ~35 min of the ≤ 2 h budget.

## C0 · (b) executed — the recorded re-run

Bar (verbatim): *"`~/.cache/parcel-guard/pytest_guard.sh --label C0
.parcel/bin/python -m pytest tests/test_mutation_panel_freshness.py -q` green in
a clean worktree, with the (a)/(b) decision and the owner's answer (or 'owner
silent, default applied') on the STATUS file."*

**Owner silent, default applied; (a) attempted and refused on constraint (not
on the clock) at ~35 min; (b) executed.**

Three edits, all inside C0's OWNS:

1. `scripts/mutation_panel.py` — `PANEL_REGENERATION_PROVENANCE` gains the
   2026-08-29 entry: the attribution to **a379bf4**, the measured mechanism
   (0.102 m/s requested, `apply_reactive_safety` → zero with `meta='stopped'`
   on 105/200 ticks, 1.5151 m vs the 1.50 m POI arrive radius, the POI point
   outside the polygon it names), why (a) was refused, and — verbatim as
   Amendment A1 requires — *"no_authority_disagreement disabled as a kill
   channel from this re-run; re-armed when D-15 agrees again"*, plus the
   statement that `zero_collisions` / `no_false_arrival` /
   `path_length_plausible` may never be disabled this way.
2. `evals/nav_instruct/results/mutation_panel.json` — regenerated **in a clean
   worktree** (`git archive HEAD` + only these edits), `MUJOCO_GL=egl
   .parcel/bin/python scripts/mutation_panel.py`. `20260828T084754Z` →
   `20260830T015339Z`.
3. `tests/test_mutation_panel_freshness.py` — new
   `test_red_clean_checks_are_declared_disabled_kill_channels`, Amendment A1's
   "freshness assertion that records that disable explicitly".

### Full accounting of the re-freeze (nothing hidden)

| field | superseded (0828T0847Z) | re-frozen (0830T0153Z) |
|---|---|---|
| `passed` / survivors / equivalent | True / [] / [] | **True / [] / []** (7/7 killed) |
| `clean_run.collisions` | 0 | **0** |
| `clean_checks.zero_collisions` | True | **True** |
| `clean_checks.no_false_arrival` | True | **True** (still a live kill channel — `phantom_view_consistent` kills through it) |
| `clean_checks.path_length_plausible` | True | **True** |
| `clean_checks.no_authority_disagreement` | True | **False** ← the declared disable |
| `clean_run.authority` | {agreement 4, tolerated_boundary 1} | {agreement 4, **authority_disagreement 1**} |
| clean successes | 3 (unchanged ids) | 3 (unchanged ids) |
| failure histogram | {grounding_error 2, none 3} | identical |
| mean dtg | 0.7754 m | 0.3617 m |

Two clean rows moved, both attributable to a379bf4 and both recorded:
`nav-region_goal-D-15` final (0.2815, 0.1603) → (2.8113, 0.7495), path
0.324 → 3.295 m, dtg 2.0685 → 0.0; `nav-region_goal-A-00` final
(1.6343, 2.5285) → (1.4075, 2.5245), min clearance 1.145 → **0.888 m**
(still well above the 0.65 m stop floor; collisions stay 0). The other three
rows are byte-identical.

Kill-channel cost, itemised: `arrival_radius_x2` and `inverted_relation` each
lose `no_authority_disagreement` (still killed on four paired checks each);
`reactive_gate_disabled` loses `mean_dtg_within_tolerance` and
`final_poses_within_tolerance` — **not** a disable but a consequence of the
clean run's own D-15 trajectory moving 3 m (it still kills on
`success_set_identical` + `failure_histogram_identical`). No mutant is killed
only through a channel that went away.

### GREEN

```
cd ~/.cache/parcel-0e/c2/refreeze && env -u TMPDIR \
  PYTHONPATH=<clean>/src:<clean> ~/.cache/parcel-guard/pytest_guard.sh --label C0 \
  .../.parcel/bin/python -m pytest tests/test_mutation_panel_freshness.py -q
→ 4 passed, 2 warnings in 46.32s
```

Negative control on the new ratchet: with the phrase
`no_authority_disagreement disabled as a kill channel` removed from the
artifact's provenance and nothing else changed, the new test fails with the
intended message (`1 failed in 0.17s`). It is a live guard, not a tautology.

**Two notes for the integrator.** (i) The freshness test is red in the *dirty*
working tree, because the owner's uncommitted `grid_planner.py` makes D-15
agree again — that is the re-arm condition arriving, and when that diff lands
the panel should be re-run and the disable withdrawn. (ii) The new node id is
not added to `ci_gate.py`'s `MUTATION_FRESHNESS_NODE_IDS` (`ci_gate.py:196`) —
that file is not this card's OWNS; adding it is a one-line integrator call.

---

# C2 — settle-observing arrival + one arrival authority

## What landed (product)

`src/parcel_robot/simulation/headless_city.py` — the only product file this
card changes. Named arrival-authority seam files consulted but **not** edited:
`src/parcel_robot/instructnav/scoring.py` (the K0 predicate `GoalRegion` and
`system_arrival_claim` are imported, unchanged), `navigation/pipeline.py`
(read only — `_step_terminal_verification`, `_semantic_arrival_verified`),
`brain/runtime_adapter.py` (read only). `pipeline.py`: **unchanged** (0 lines).
`config.py`: **unchanged**.

1. **Settle-observing terminal.** `DEFAULT_SETTLE_FRAMES = 5` (0.5 s at the
   10 Hz control tick — MA-1's `ORACLE_SETTLE_FRAMES`). After the mission's
   terminal frame the harness keeps stepping the world and watching:
   `settled = the standing command is zero AND the pose is inside the committed
   K0 arrival region on EVERY settle frame`. `HeadlessTaskResult` gains
   `settled` and `settle_frames_observed`.
   **Observation only, exactly as Amendment A1 requires:** the window issues no
   command, never calls `navigator.step`, and never calls
   `apply_reactive_safety` — so it cannot reach the A3 latch or the A6 stop
   path. If the standing command is not zero it steps nothing and reports
   `settled=False`, rather than driving the robot after the mission ended.
2. **The terminal frame is frozen before the window runs.** A new
   `_WorldSnapshot` captures `final_observation` / `path` / `collision_count` /
   `minimum_clearance_m` at the terminal frame, so **every field
   `HeadlessTaskResult` already carried is bit-for-bit what it was** and the
   strict one-frame predicate stays comparable to its own history. This is what
   makes "strict vs settled" a delta rather than two unrelated measurements.
   `status`/`reason` are untouched (E3).
3. **One arrival authority, no fourth opinion.** `arrived_verified =
   system_arrival_claim(status, reason) ∧ inside_arrival_region ∧ settled`.
   The system's own terminal claim comes FIRST (Amendment A1: *"missing
   receipt = not arrived"*), the region is the one the navigator itself
   committed (`mission.metadata['arrival_goal_region']`, the K0/N45 seam — the
   harness builds no region of its own), and the settle is the new
   observation. Nothing in this composition can manufacture an arrival.
4. **Attribution logged.** `goal_source`, `poi_refused`,
   `arrival_not_verified_reason` and `inside_arrival_region` are carried on the
   result, so a re-scored row can say WHICH oracle answered and WHY a claim was
   refused. This closes NAV-GEN-1 `VERDICT.md` §5.2's own caveat that "raw rows
   do not log `goal_source`".

`research/20260829/nav-gen-attribution-1/run.py` — the single documented
addition the parent authorised: seven new row keys (`settled`,
`settle_frames_observed`, `inside_arrival_region`, `arrived_verified`,
`goal_source`, `poi_refused`, `arrival_not_verified_reason`) plus
`settled_success = inside_strict AND settled` beside the untouched
`strict_success`. No other change to that folder; `analyze.py` not edited (C7
owns it).

## C2 · acceptance rows

### Row: no safety floor touched · `config.py` unchanged · `pipeline.py` unchanged

Bar (verbatim): *"No safety floor touched (grep-proof in STATUS); `config.py`
unchanged; `pipeline.py` net-negative or unchanged."*

My files, `git diff --numstat` (a shared tree — other executors' files are
excluded from every count below):

| file | +/- |
|---|---|
| `src/parcel_robot/simulation/headless_city.py` | +185 / −7 |
| `tests/test_arrival_settle.py` | new, 232 lines |
| `tests/test_mutation_panel_freshness.py` | +66 / −0 |
| `scripts/mutation_panel.py` | +40 / −1 |
| `evals/nav_instruct/results/mutation_panel.json` | +92 / −97 (regenerated) |
| `research/20260829/nav-gen-attribution-1/run.py` | +34 / −1 |

- `src/parcel_robot/config.py` — **not touched** (0 lines).
- `src/parcel_robot/navigation/pipeline.py` — **not touched by this card**
  (0 lines). It carries another executor's working-tree diff; that is C3's,
  not mine.
- Safety-floor grep over my code diff: **0** added lines and **0** removed
  lines matching
  `obstacle_stop_m|apply_reactive_safety\(|finalize_command|hard_stop|person_stop_m|stop_distance_m|obstacle_slow_m`.
  The only occurrences of `apply_reactive_safety` / "A3 latch" / "A6 stop path"
  anywhere in my diff are **prose in comments** saying the settle window does
  not reach them.
- `noqa` added: **0** (grep-counted over the added lines; the 2 in
  `mutation_panel.py` and `nav-gen-attribution-1/run.py` are pre-existing
  `BLE001` boundaries I did not touch).
- Note for the verifier: `headless_city.py` grows by a net 178 lines. No
  DEC-0 line ceiling names that file (the ceiling clauses name `config.py` and
  `pipeline.py`); flagging it rather than assuming.

### Row: named regression subset green through the guard

Bar (verbatim): *"`test_k0_arrival_authority.py`,
`test_authority_half_scale_smoke.py`, `test_embodied_plan_eval.py` green
through the guard."*

```
env -u TMPDIR MUJOCO_GL=egl ~/.cache/parcel-guard/pytest_guard.sh --label C2reg \
  .parcel/bin/python -m pytest tests/test_k0_arrival_authority.py \
  tests/test_authority_half_scale_smoke.py tests/test_embodied_plan_eval.py \
  tests/test_headless_city_tasks.py tests/test_person_cell.py \
  tests/test_search_reground_bench.py tests/test_dr2_pose_drift_arm.py \
  tests/test_arrival_settle.py -q
→ 1 failed, 146 passed, 3 xfailed, 1 xpassed in 84.46s
```

The three named files are **green**. I widened the subset to every
`HeadlessCityQualityHarness` consumer in `tests/`, and one of those is red:

- `tests/test_person_cell.py::test_deadlock_signature_reproduces_with_an_undeclared_bystander`
  — `assert outcome.veto_fraction >= 0.9` measured **0.875**.
  **Pre-existing and not C2's.** Bisected the same way as C0, one clean export
  per revision: red with `veto_fraction 0.875` at **`f3ecb5c`** (`steps=40`),
  at **`a379bf4`** (`steps=50`), and on clean `HEAD` (`steps=50`). My tree
  reports 0.875 / `steps=50`, identical to clean HEAD — **C2 moves it by
  exactly zero**. It is older than a379bf4, so it is not C0's row either.

`tests/test_arrival_settle.py` (new, this card): **11 passed in 12.66 s**.

### Row: NAV_INSTRUCT frozen digest unchanged

Bar (verbatim): *"NAV_INSTRUCT frozen digest `e7c302dd…` unchanged."*

```
v4 full-matrix digest = e7c302ddf19a…      ← the pinned value, UNCHANGED
v1 da245f6fa64a  v2 2f8c0153422c  v3 a1d432988d53
v1..v4 minival    cf4d5384d178 / a17c04dbec43 / 919a0fea8363 / 4113607b92c7
```
and the digest suites through the guard:
`tests/test_nav_instruct_episodes_v2.py`, `_v3`, `_v4`,
`test_nav_instruct_digest_recipe.py`, `test_v4s_search_cells.py`,
`test_nav_instruct_rescoring.py`, `test_nav_instruct_scene_truth.py`
→ **115 passed in 6.60s**. Nothing in `evals/nav_instruct/generator.py` was
touched; E3 holds.

### Row: NAV-GEN-1 `--arms A0` re-run with `settled` logged — strict vs settled on 450 generated episodes

Bar (verbatim): *"NAV-GEN-1 `--arms A0` re-run with `settled` logged: report
strict (one-frame) vs settled success on 450 generated episodes (expected
within 10 points of 0.65; if settled < 0.40 the navigator does not hold still
after arrival — record, do not tune)."*

The run in the **live working tree** is not interpretable — it gives strict
0.7378, +8.7 points over the recorded A0 baseline, because the tree carries the
owner's uncommitted `grid_planner.py` and another executor's in-flight
`pipeline.py`. So the row is measured on a **pinned tree**: `git archive HEAD`
plus exactly two files, my `headless_city.py` and my `run.py` columns. Scene
manifest sha256 `b698e0594a7d…4ab43` — identical to the reproduction in
`VERDICT.md` §5. Wall 332.6 s on 16 workers (the recorded run: 329 s / 16).

```
cd <pinned HEAD + C2> && env -u TMPDIR MUJOCO_GL=egl OPENBLAS_NUM_THREADS=32 \
  NG1_SCRATCH=~/.cache/parcel-0e/c2/ng1pinout .../.parcel/bin/python \
  research/20260829/nav-gen-attribution-1/run.py --stage prepare
  ... --arms A0 --seed 20260829 --workers 16
```

**C2 moves NAV-GEN-1 by exactly zero — measured, not argued.** The same arm was
run twice on the same pinned HEAD, once WITH the settle window and once
WITHOUT (`headless_city.py` at HEAD, the row schema unchanged):
**530/530 rows are byte-identical on every pre-C2 column**, `strict_success`
316/530 in both. `settled` is a pure addition.

#### The two predicates, side by side (450 generated episodes, arm A0)

| predicate | n/450 | rate | 95 % Wilson |
|---|---|---|---|
| `terminal_stopped` (command zero on ONE frame) | 450 | 1.0000 | [0.9915, 1.0000] |
| `inside_strict_band` (truth band, final pose) | 294 | 0.6533 | [0.6082, 0.6958] |
| **`strict_success`** = band ∧ one-frame stop | **294** | **0.6533** | [0.6082, 0.6958] |
| **`settled_success`** = band ∧ settled over 5 frames | **284** | **0.6311** | [0.5856, 0.6744] |
| `settled` (K0 committed region ∧ 5 still frames) | 286 | 0.6356 | [0.5901, 0.6787] |
| `nav_claimed_success` (status only) | 283 | 0.6289 | [0.5833, 0.6723] |
| **`arrived_verified`** = system claim ∧ K0 region ∧ settle | **242** | **0.5378** | [0.4916, 0.5833] |

**Δ (settled − strict) = −10 episodes = −2.22 points.** Both bars met:
strict 0.6533 is **0.3 points** from the card's 0.65 (the recorded A0 baseline
is 293/450 = 0.6511 — one episode apart, and that episode is HEAD-vs-the-
recorded-tree, not C2, because the with/without control is byte-identical), and
settled 0.6311 is far above the 0.40 floor. **The navigator does hold still
after it arrives**; MA-1's 4.5 % was a gold-predicate artefact, and this is the
number that says so on the product harness.

#### Where the 10 episodes go — all of them, by name

Every one is strict-TRUE / settled-FALSE, and every one is a case where the
truth band says "inside" while the navigator's OWN committed K0 region says
otherwise or was never committed:

| episodes | target | reason | `inside_arrival_region` |
|---|---|---|---|
| 6 (`gen:8800{03,06,07,14,19,22}`) | crosswalk | `navigation_no_progress` | **None** — no K0 region committed at all |
| 4 (`gen:8800{00,05,12,26}`) | sidewalk | `semantic_target_unreachable` | **False** — committed region excludes the pose |

#### Per target — and the crosswalk row is the whole C1 story in one line

| target | n | strict | settled | Δ | `arrived_verified` | no committed K0 region | `goal_source` |
|---|---|---|---|---|---|---|---|
| bench | 90 | 65 | 65 | 0 | 63 | 0 | `semantic_search` 90 |
| **crosswalk** | 90 | 6 | **0** | −6 | **0** | **90/90** | **`known_poi` 90/90** |
| lamppost | 90 | 75 | 75 | 0 | 75 | 0 | `semantic_search` 90 |
| planter | 90 | 64 | 64 | 0 | **25** | 1 | `semantic_search` 90 |
| sidewalk | 90 | 84 | 80 | −4 | 79 | 0 | `semantic_search` 90 |

This closes `VERDICT.md` §5.2's own caveat — *"raw rows do not log
`goal_source`, so the attribution rests on `headless_city.py:757-760` + the
parse reproduction"*. Every crosswalk episode now says it in the row:
**90/90 `known_poi`, 90/90 with no committed K0 arrival region, 0/90
`arrived_verified`.** The POI second oracle produces terminal claims that no
arrival authority can confirm. That is **C1's** defect, now instrumented rather
than inferred.

The planter column is a second, unasked-for finding: strict 64 but
`arrived_verified` 25. The navigator's own typed refusal is logged per episode —
`arrival_not_verified_reason` over the 450: **44 `outside_support_polygon`**,
1 `surface_clearance_out_of_band`, 405 none. Recorded for C3/N45, not touched.

Safety on this run: **0 collisions**; **1** episode below the 0.65 m stop band
(the same single episode `VERDICT.md` §5.2 records for A0); `settle_frames_observed`
is 5 on 359 episodes and 0 on the 91 with no committed region.

### Row: NAV-INT-1 tier RED

Bar (verbatim): *"NAV-INT-1 tier `research/20260829/nav-interrupt-1/run.py`
(see its README; `PARCEL_MEMORY_PATH` → scratch, unique socket, `systemd-run
--user --scope -p MemoryMax=12G`) reproduces authority disagreements 17/80."*

Run on a **pinned HEAD export** (`git archive HEAD`), never in the live tree —
another executor (C7) is editing `nav-interrupt-1/harness.py` and its README
right now, and the recorded artifacts in `research/20260829/nav-interrupt-1/`
are left untouched. `WORKDIR` repointed to `~/.cache/parcel-0e/c2nir`
(46-byte socket path), so `PARCEL_MEMORY_PATH` and every sim land in my
scratch; each sim under `systemd-run --user --scope -p MemoryMax=12G
-p MemorySwapMax=0`, one at a time; `TMPDIR` unset. Amendment N3 orphan check
at the end: **`clean=True ours=[] other_processes=[]`** — every sim I started
is gone, and the owner's `/tmp/parcel_sim.sock` and the other executor's
`lit1` sim were never touched.

```
cd <pinned HEAD> && env -u TMPDIR .../.parcel/bin/python \
  research/20260829/nav-interrupt-1/run.py --stage controls --stage tier --stage aggregate --seed 20260829
```

Tallied with the folder's own `_authority_tally` over **only this run's** rows
(the run appends to the committed JSONL, so the in-file `results.json` totals
160 legs = 80 recorded + 80 mine; the 80 below are mine):

| goal | n | agreement | tolerated_boundary | system-failed-but-arrived | system-succeeded-but-not-arrived |
|---|---|---|---|---|---|
| **bench** | 29 | 17 | 2 | **10** | 0 |
| sidewalk | 17 | 11 | 0 | 0 | **6** |
| lamppost | 10 | 10 | 0 | 0 | 0 |
| towards_lamppost | 17 | 17 | 0 | 0 | 0 |
| come_here | 7 | 7 | 0 | 0 | 0 |
| **total** | **80** | 62 | 2 | 10 | 6 |

**Disagreements 16/80** against the bar's 17/80, with every per-goal
denominator identical to the record (29 / 17 / 10 / 17 / 7) and the class
reproducing in the same place. The one-leg difference is a bench leg that
landed in `tolerated_boundary` (differ, but within the K0 boundary epsilon)
instead of `authority_disagreement`; this is a live-sim tier with wall-clock
deadlines, so leg-level determinism is not claimed by its own README. **The
RED reproduces.**

### Row: NAV-INT-1 tier GREEN ≤ 2/80 and bench 0/29 — NOT REACHED, and why

Bar (verbatim): *"same tier ≤ **2/80** disagreements; bench legs
'system-failed-but-arrived' **0/29**."*

**This bar cannot be moved from C2's OWNS, and moving it would violate
Amendment A1.** Working agreement 3 applies: recorded, with the closest
faithful thing done instead. Three measurements, not opinions:

1. **C2's change is not even in the tier's import graph.** The tier drives
   `RobotRuntime.handle_text` against a `parcel_robot.sim` subprocess. Import
   proof, run on the pinned export:
   `import harness, queue_policy` → modules matching `headless_city|simulation`
   are `['parcel_robot.simulation', 'parcel_robot.simulation.ipc']`;
   `'parcel_robot.simulation.headless_city' in sys.modules` is **False**.
   Same for `import parcel_robot.sim, parcel_robot.runtime` → **False**.
   C2 therefore moves this tier by construction: **zero**.
   Measured too, not only argued: the controls stage re-run on **HEAD + C2**
   gives the same 10 legs with the same categories and the same **2/10**
   disagreements (both bench) as the RED. (One `come_here` control leg differs
   between the two runs — 100.7 s vs 24.1 s wall, it hit its deadline — and
   stays `agreement` in both; that is the tier's own live-sim variance.)

2. **The 10 bench legs are a typed refusal that is designed to fire.** Every
   one is `states=['failed']`,
   `details=['semantic_arrival_verification_failed']`, `committed='bench_1'`,
   scorer dtg **0.0**. That receipt comes from
   `pipeline.py::_step_terminal_verification` after
   `_semantic_arrival_verified()` returns False and the semantic replans are
   spent — the a379bf4 two-phase terminal contract, which records WHY in
   `mission.metadata['arrival_not_verified_reason']` (`pose_unhealthy`,
   `perception_stale`, `terminal_environment_not_clear`, `target_not_resighted`,
   `outside_arrival_region`). It is not a *false* `failed` receipt; it is the
   contract refusing. Amendment A1: *"'Make the system verdict honest' is never
   implemented as 'claim arrival past a refusal designed to fire'."* Making
   bench 0/29 means weakening that refusal, which this card may not do. The
   bench `near`-band-vs-terminal-relation reconciliation is **N45/K0** and
   owner-gated (`backlog/NEXT.md` N45; N11 already records that the bench band
   has zero admissible poses at the shipping envelopes with `pedestrian_5`
   standing in it).

3. **The 6 sidewalk legs are a harness wrong-instance defect, not a product
   false arrival.** Every one is `states=['succeeded']`,
   `details=['navigation_goal_verified']`, end `(0.511, −2.572)`, and
   **`committed: 'sidewalk_south'`** — the robot went to a real sidewalk and
   verified it. The harness's `GoalSpec("sidewalk", "region", …)` scores
   against one hardcoded polygon, `x ∈ [−8, 8], y ∈ [2.4, 3.6]` (the *north*
   sidewalk), 4.97 m away. This is NAV-GEN-1's "any-instance" column in a
   different harness, and `nav-interrupt-1/harness.py` is **C7's** OWNS — a
   card whose stated job is exactly "NI-1's two defects" and harness truth.
   Fixing it from here would be editing another card's file.

**What C2 did instead**, for the same defect class, inside its OWNS: the
product harness now carries ONE arrival authority
(`arrived_verified = system claim ∧ committed K0 region ∧ settle`) and reports
both predicates side by side on 530 episodes, and the run above gives the
attribution per episode (`goal_source`, `inside_arrival_region`,
`arrival_not_verified_reason`). On the NAV-GEN-1 harness the same class is
therefore now *countable*: `nav_claimed_success` 283/450 vs `arrived_verified`
242/450 — 41 episodes where the system claims and the one authority declines to
confirm, each with its reason in the row.

## Close

### Amendment A1's C2 clauses, answered
- *"`arrived_verified` authority stays with the system side"* — it does:
  `system_arrival_claim(status, reason)` is the first conjunct, and the two
  parametrised cases `('failed', 'semantic_arrival_verification_failed')` and
  `('timed_out', 'navigation_step_limit_inside_goal')` are pinned to
  `arrived_verified is False` **with the geometry perfect** in
  `tests/test_arrival_settle.py`.
- *"missing receipt = not arrived"* — pinned by the same test, and by
  `inside_arrival_region=None` (no committed region) never reading as inside.
- *"the settle window is observation only: it must not touch the A3 latch or
  A6 stop semantics and never issues a hold command"* — the window calls
  `self.world.step()` and reads the pose. It never calls `navigator.step`,
  never calls `apply_reactive_safety`, and never calls `world.apply`. If the
  standing command is non-zero it steps nothing at all rather than driving the
  robot after the mission ended. `world.command == result.terminal_command`
  after a run is asserted in the test.

### Final test record (all through `~/.cache/parcel-guard/pytest_guard.sh`, `TMPDIR` unset)

| command | result |
|---|---|
| `--label C0` `tests/test_mutation_panel_freshness.py` in a clean worktree, BEFORE | 1 failed, 2 passed (46.69 s) |
| `--label C0` same, AFTER the recorded re-run | **4 passed** (46.32 s) |
| `--label C0` FINAL re-verification: fresh `git archive HEAD` + the exact three committed files | **4 passed** (44.61 s) |
| `--label C0neg` new ratchet with the provenance phrase stripped | 1 failed (0.17 s) — the guard is live |
| `--label C2` `tests/test_arrival_settle.py` | **11 passed** (12.66 s) |
| `--label C2reg` the 3 named files + every other `HeadlessCityQualityHarness` consumer | 1 failed, 146 passed, 3 xfailed, 1 xpassed (84.46 s) — the 1 is pre-existing, bisected to before `a379bf4` |
| `--label C2final` the same minus `test_person_cell.py` | **140 passed, 3 xfailed, 1 xpassed** (74.96 s) |
| `--label C2dig` the 7 NAV_INSTRUCT digest suites | **115 passed** (6.60 s) |
| `--label C2clean` / `C2bisect` the person-cell row at `f3ecb5c` / `a379bf4` / clean HEAD | red, `veto_fraction 0.875`, at every one |

`ruff check` clean on all five files I touched; **0** `noqa` added.
Executors never ran `ci_gate.py`; no `-n auto`; no `--pdb`; no git writes; no
hosted calls ($0.00).

### Files touched (my OWNS only)
- `src/parcel_robot/simulation/headless_city.py` (+185/−7)
- `tests/test_arrival_settle.py` (new, 232 lines)
- `tests/test_mutation_panel_freshness.py` (+66/−0)
- `scripts/mutation_panel.py` (+40/−1, provenance only)
- `evals/nav_instruct/results/mutation_panel.json` (regenerated in a clean worktree)
- `research/20260829/nav-gen-attribution-1/run.py` (+34/−1, the authorised `settled` columns)
- `scrum/20260829/task_2/C0_C2_STATUS.md` (this file)

Not touched: `config.py`, `pipeline.py`, `runtime.py`, `brain/executive.py`,
`gateway/*`, `bridge/*`, `control/*`, `navigation/grid_planner.py`, `docs/`,
`configs/*`, `prompts/`, any foreign research folder, and the recorded
artifacts in `research/20260829/nav-interrupt-1/` (every NAV-INT-1 run of mine
was executed from a pinned scratch export).

### Handover
1. `CODEBASE_INDEX.md` is not regenerated here — `tests/test_arrival_settle.py`
   is new, so the integrator's close should run
   `.parcel/bin/python tools/codebase_index.py`. Regenerating a shared file
   mid-wave would collide with the other executors.
2. `ci_gate.py`'s `MUTATION_FRESHNESS_NODE_IDS` (`ci_gate.py:196`) does not
   list the new declared-disable ratchet. Adding it is a one-line integrator
   call; `ci_gate.py` is not this card's OWNS.
3. **The re-arm condition.** When the owner's `grid_planner.py` diff lands,
   `nav-region_goal-D-15` agrees again (proved by single-file transplant), and
   the panel must be re-run so `no_authority_disagreement` comes back as a kill
   channel — the provenance says exactly this, and the new test will keep
   failing until the provenance is updated with it.
   **SUPERSEDED IN PART by Follow-up F1's addendum below: a re-run alone is NOT
   enough.** That same diff makes `reactive_gate_disabled` a SURVIVOR (the gate
   never binds on these five episodes), so landing it requires BOTH withdrawing
   the disable AND re-choosing panel episodes on which the gate binds — an owner
   E3 decision, filed as `backlog/BLOCKED.md` B32. The committed panel is valid
   only on trees WITHOUT that diff.
4. Two findings handed to other cards rather than acted on: **C1** owns the
   crosswalk POI (90/90 `known_poi`, 90/90 with no committed K0 region, 0/90
   `arrived_verified`); **C7** owns the NAV-INT-1 sidewalk wrong-instance
   scoring (`committed: sidewalk_south` vs a single hardcoded north polygon);
   **N45/K0** owns the bench terminal-relation refusal.

### Artifacts left in scratch for the verifier
`~/.cache/parcel-0e/c2/` — `clean/`, `clean_gp/`, `at_f3ecb5c/`, `at_a379bf4/`
(the C0 bisection trees), `refreeze/` + `c0final/` (the panel re-freeze and its
final re-verification), `negctl/` (the ratchet's negative control),
`ng1pinout/raw/rows_A0.json` (HEAD + C2) and `ng1baseout/raw/rows_A0.json`
(HEAD, no C2 — the byte-identity control), `ng1/raw/` (the dirty-tree run, kept
only to show why it was discarded), `ni1red/` (the pinned NAV-INT-1 RED tier)
and `ni1green/` (the HEAD + C2 controls re-run), plus `diag_panel.py`,
`diag_d15.py`, `diag_d15b.py` — the three diagnostics that produced the C0
mechanism. No sim of mine survives (`pgrep` clean); the owner's
`/tmp/parcel_sim.sock` sim (pid 807004) was never touched.

---

# Follow-up F1 (integrator rulings adopted, + the AUDIT_C0_C2 §4 addendum)

## F1(1) — the freshness test now computes DIRECTION

No "re-arm pending" marker was added: the equality is what forces the re-run,
and it already does. What was missing was direction, so
`test_committed_panel_safety_fields_still_reproduce` now routes through a pure
helper, `freshness_failure_message(committed, live, provenance, *,
live_survivors=None)`, in `tests/test_mutation_panel_freshness.py`. It returns
`None` when the artifact still reproduces, and otherwise the message the
situation actually calls for. Priority order: **survivor → green-direction →
red-direction.**

Pure by construction (the live run is passed *in*), so both texts are pinned
with fixture payloads and no simulator. The slow whole-panel test now feeds it
`live_survivors=payload["survivors"]`, replacing `assert False is True`.

### The three message texts, verbatim

**(a) live GREENER than committed on a declared-disabled channel** — the
declaration has come due:

```
the committed mutation panel is STALE IN THE GREEN DIRECTION on
['no_authority_disagreement']: the live clean run now PASSES a check the
committed artifact records red and its own provenance declares disabled, so the
declaration has come due — re-run the panel and withdraw the
'no_authority_disagreement disabled as a kill channel' declaration
(committed={...} live={...})
```
(rendered on one line at runtime; the integrator's required phrase —
`re-run the panel and withdraw the '<name> disabled as a kill channel'
declaration` — is asserted verbatim, and the red-direction wording is asserted
*absent*.)

**(b) live REDDER than committed** — unchanged, byte for byte:

```
the committed mutation panel no longer reproduces its own safety-relevant
fields on this tree: committed={...} live={...} — the hard-safety gate must not
certify from it until the divergence is diagnosed
```

**(c) F1 addendum — a mutant SURVIVED the live run**, which outranks both:

```
the mutation panel did not PASS on this tree: ['reactive_gate_disabled']
survived — the panel episodes no longer exercise reactive_gate_disabled's
channel; re-choose panel episodes on which the gate binds (owner E3 decision)
```

### Guard-rails pinned with it

- A green drift on a channel the provenance **never declared** still gets the
  red-direction "diagnose it" wording — the green branch is not a blanket
  licence to regenerate
  (`test_a_green_drift_on_an_UNDECLARED_channel_is_still_a_diagnose_first_red`).
- A survivor is reported **even when the clean fields reproduce perfectly** —
  a panel can be byte-fresh and have stopped being a panel
  (`test_survivors_are_reported_even_when_the_clean_fields_still_reproduce`).
- A survivor **outranks** a green-direction drift on the very fixture that is
  both, which is exactly the post-`grid_planner.py` state
  (`test_freshness_message_when_a_mutant_SURVIVES_says_re_choose_the_episodes`).
- `live_survivors` of `None` / `[]` / `()` leaves the direction logic untouched.

Seven pure fixture tests, `7 passed, 4 deselected in 0.19s` (`-m "not slow"`).

## F1(2) — the C0 ROOT CAUSE, recorded

**No terminal-contract refusal fires on D-15.** The system targets the POI
**POINT** `crosswalk_a` `(3.5, −0.6)`, which lies **0.2 m OUTSIDE the polygon
the scorer certifies** (`y = −0.6` against the polygon's `y ≥ −0.4`), and
`apply_reactive_safety` holds the body **15 mm short of the 1.5 m point
radius** (1.5151 m) while it is **already inside that polygon** at
`(2.8113, 0.7495)`. That is a goal-**REPRESENTATION** mismatch — point-goal
system vs region scorer — the **C1 family on the demo block**.

**Scene-identity C1 keeps D-15 on `known_poi`, so the knife-edge survives.**
The durable fix is C2's "one arrival authority" carried to its conclusion: **a
`known_poi` whose class is a region must be judged by the region band, not by
the 1.5 m point radius.** That moves frozen demo rows, so **it is the OWNER's
E3 decision, not a wave-A edit.**

Filed as **`backlog/BLOCKED.md` B32** — "One arrival authority: the K0 region
must be the region the terminal contract will accept · **OWNER E3 DECISION**" —
**one** append-only entry (`85 insertions, 0 deletions`; `git diff` against HEAD
shows no line of pre-existing backlog content touched), no other backlog file
edited. B32 carries BOTH measured pairs, because F1(3) proved they are one
decision: pair 1 is D-15's point-vs-polygon, pair 2 is the bench's
band-vs-support-polygon.

### F1 addendum, adopted into the C0 close

**The re-run panel committed by C0(b) is valid ONLY on trees WITHOUT the
owner's uncommitted `grid_planner.py`.** The integrator measured (AUDIT_C0_C2
§4) that with that diff the reactive gate is called **101/88/51/62/0** times
across the five panel episodes and zeroes a non-zero request **0** times, so
`reactive_gate_disabled` never binds and becomes a **SURVIVOR** — an equivalent
mutant. "D-15 agrees again" and "the gate never fires" are therefore **the same
event**, and my re-arm condition as originally written was incomplete.

**Landing that diff requires BOTH:** withdrawing the
`no_authority_disagreement disabled as a kill channel` declaration **AND**
re-choosing panel episodes on which the gate binds. The second half changes the
frozen episode **selection**, so it is an owner E3 decision as well; both halves
are recorded in B32. The freshness helper now emits the correct message for
each half, and the survivor message wins when both apply — which is precisely
the state that diff produces.

## F1(3) — the 10 bench legs, attributed by REFUSAL BRANCH (not by label)

Method, the same one that produced the D-15 mechanism: a scratch-only probe
(`f1_probe.py`, written into a pinned `git archive HEAD` export, never into the
repo) wraps `DirectiveNavigator.start`, `_semantic_arrival_verified` and
`_step_terminal_verification`, and writes one record per mission carrying the
typed `mission.metadata['arrival_not_verified_reason']` that DECIDED the
receipt plus the histogram of every reason seen in that mission's verification
window. Re-run of `--stage controls --stage tier --seed 20260829` on
`~/.cache/parcel-0e/c2nif` (own socket, `systemd-run … MemoryMax=12G`,
`TMPDIR` unset). Legs joined to probe records by terminal pose.

### The branch, and it is ONE branch

Every refusing bench leg decides on **`outside_support_polygon`** — the LAST
check in the `near` arm of `_semantic_arrival_verified`
(`pipeline.py:6205-6209` → `_on_support_surface`). Not co-visibility
(`terminal_environment_not_clear` never fires, 0 ticks), not
`target_not_resighted`, not `outside_arrival_region`, not
`surface_clearance_out_of_band`, not `perception_stale`, not `pose_unhealthy`.
The refusal histogram is a single key repeated for the whole replan budget.

So the leg passes the K0 region check and then fails on standable ground:

| quantity | value |
|---|---|
| `bench_1` anchor | (−2.5, 3.045), radius 0.7338 m |
| K0 `near` band (what the SCORER certifies) | `relative_band`, r ∈ [1.8538, 2.0538] m |
| `support_polygon` (what the terminal contract requires) | the north sidewalk, `[[−8,2.2],[8,2.2],[8,4.2],[−8,4.2]]` |
| `terminal_support_clearance_m` | 0.32 m → standable strip `y ∈ [2.520, 3.880]` |
| the legs' terminal pose | (−0.677, 2.276) |
| distance to bench | **1.9786 m → INSIDE the band** (scorer: arrived, dtg 0.0) |
| distance to standable ground | **0.244 m short of `y ≥ 2.520`** (system: `outside_support_polygon`) |
| **fraction of the certified K0 band that is NOT standable** | **77.26 %** (400 000 samples over the annulus) |

### Is it the same point-vs-region mismatch? — precisely: same FAMILY, different PAIR

It is **not** the point-vs-region pair. It is **band-vs-support-polygon**:

- **D-15:** the scorer certifies a **polygon**; the system aims at a **point**
  0.2 m outside it.
- **bench:** the scorer certifies a **bare annulus**; the system's own terminal
  predicate is that annulus **∧ the support polygon**, and the annulus is never
  intersected with it — so **77.26 %** of the region the scorer certifies is
  ground the system will never stand on. The body stops 0.244 m into that
  77.26 %.

Both are the **same root cause in one sentence**: *the K0 arrival authority
certifies regions the system's own terminal predicate does not accept.* Both
therefore need the **same owner E3 ruling** (B32), which is why they are filed
as one entry and not two.

### Does that make ≤ 2/80 reachable in wave A? — No, and here is the proof

The honest fix is to make the two agree, and there are exactly two ways:

1. **Intersect the K0 `near` band with the support polygon** in
   `arrival_goal_region_for_relation` / `object_near_goal_region` — the "one
   arrival authority" fix. **This moves the frozen NAV_INSTRUCT digests.**
   Proof, not assertion: `_matrix_digest` hashes `ep.as_dict()`, and **45 of
   the 125** v4 matrix episodes embed a `relative_band` goal carrying `band_m`
   verbatim (e.g. `{'kind': 'relative_band', 'center': [0.2, 3.15], 'band_m':
   [0.6, 2.5], …}`); `tests/test_k0_arrival_authority.py::
   test_semantics_and_eval_object_goal_regions_agree` pins generator ≡
   city-semantics ≡ pipeline builder, so they move together. `e7c302dd…` moves
   → **E3 → owner**.
2. **Drop the support-surface check** from the terminal contract — weakening a
   designed refusal, which Amendment A1 forbids and which would let the dog
   announce "I'm at the bench" while standing in the road.

So the class is **not** owner-gated *because it is a perception refusal* — my
earlier reading — it is owner-gated because **fixing it correctly moves frozen
evidence**, exactly like D-15. That is a sharper and more actionable finding
than the one it replaces, and it collapses C0's and C2's root causes into a
single owner decision. **≤ 2/80 is reachable only through B32, not in wave A.**

### The per-leg table (instrumented re-run, `--stage controls --stage tier --seed 20260829`)

This run: **80 scored legs, 18 disagreements**, **bench 11/29
`system_failed_but_arrived`** — the record's headline reproduced exactly
(11/29). Orphan check `clean=True ours=[] other_processes=[]`.

Every refusing bench leg, joined to the probe record by terminal pose. `dtg` is
the SCORER's distance to the K0 band; `0.0` means the scorer says arrived.

| # | episode | leg | category | end pose | dtg | receipt | **deciding refusal branch** | refusal ticks |
|---|---|---|---|---|---|---|---|---|
| 1 | control | `leg` | authority_disagreement | (−0.677, 2.276) | 0.0 | `semantic_arrival_verification_failed` | **`outside_support_polygon`** | 7 |
| 2 | control | `leg` | authority_disagreement | (−0.678, 2.277) | 0.0 | `semantic_arrival_verification_failed` | **`outside_support_polygon`** | 7 |
| 3 | `ni1-00-bench-come_here` | `amended_goal` | authority_disagreement | (−0.678, 2.274) | 0.0 | `semantic_arrival_verification_failed` | **`outside_support_polygon`** | 7 |
| 4 | `ni1-01-bench-come_here` | `reissue` | authority_disagreement | (−0.678, 2.277) | 0.0 | `semantic_arrival_verification_failed` | **`outside_support_polygon`** | 7 |
| 5 | `ni1-02-bench-come_here` | `amended_goal` | authority_disagreement | (−0.679, 2.275) | 0.0 | `semantic_arrival_verification_failed` | **`outside_support_polygon`** | 7 |
| 6 | `ni1-03-bench-come_here` | `reissue` | authority_disagreement | (−0.707, 2.274) | 0.0 | `semantic_arrival_verification_failed` | **`outside_support_polygon`** | 7 |
| 7 | `ni1-05-bench-lamppost` | `amended_goal` | authority_disagreement | (−0.678, 2.278) | 0.0 | `semantic_arrival_verification_failed` | **`outside_support_polygon`** | 7 |
| 8 | `ni1-11-bench-sidewalk` | `amended_goal` | authority_disagreement | (−0.677, 2.278) | 0.0 | `semantic_arrival_verification_failed` | **`outside_support_polygon`** | 7 |
| 9 | `ni1-16-lamppost-bench` | `amended_goal` | authority_disagreement | (−0.674, 2.281) | 0.0 | `semantic_arrival_verification_failed` | **`outside_support_polygon`** | 6 |
| 10 | `ni1-19-lamppost-bench` | `amended_goal` | authority_disagreement | (−0.678, 2.274) | 0.0 | `semantic_arrival_verification_failed` | **`outside_support_polygon`** | 7 |
| 11 | `ni1-20-sidewalk-bench` | `amended_goal` | authority_disagreement | (−0.712, 2.264) | 0.0 | `semantic_arrival_verification_failed` | **`outside_support_polygon`** | 7 |
| — | `ni1-13-bench-towards_lamppost` | `reissue` | *tolerated_boundary* | (−0.546, 2.426) | 0.0 | `semantic_target_unreachable` | *n/a — never reached terminal verification* | — |

**Deciding-branch tally: `outside_support_polygon` 11/11.** Not one leg decides
on anything else. Across the whole 50-run tier the probe saw
`outside_support_polygon` **14** times and `terminal_environment_not_clear`
**once** — so co-visibility is not the cause of this class, and neither is
`target_not_resighted`, `outside_arrival_region`,
`surface_clearance_out_of_band`, `perception_stale` or `pose_unhealthy`
(**0 ticks each on every bench leg**). The 12th non-agreement leg is a
`tolerated_boundary` whose mission died earlier at
`semantic_target_unreachable` and never reached the terminal contract; it is
correctly unmatched rather than force-fitted.

Every terminal pose is the same point to within 4 cm — (−0.68, 2.28) — which is
what a *geometric* mismatch looks like: the body is parked at the boundary of
two regions that were never intersected, on every leg, from every approach.

## Follow-up F1 — close

| ruling | done |
|---|---|
| F1(1) no new marker; add DIRECTION to the freshness failure | `freshness_failure_message(...)`, 3 texts, priority survivor → greener → redder |
| F1(1) greener-on-a-declared-disabled-channel wording | asserted verbatim, red wording asserted absent |
| F1(1) redder keeps current wording | asserted byte-for-byte equal to the original string |
| F1(1) test both messages with fixture panels | 7 pure fixture tests, no simulator |
| F1 addendum (a) `passed is False` with survivors | 4th branch, outranks both directions; fixture-tested; wired into the live whole-panel test in place of `assert False is True` |
| F1(2) root cause on the C0 close | recorded above; handover item 3 marked SUPERSEDED IN PART |
| F1(2) backlog entry under an owner-named E3 decision | `backlog/BLOCKED.md` **B32**, append-only, one entry |
| F1 addendum (b) panel valid only without `grid_planner.py`; both halves needed | stated in F1's addendum section, in handover item 3, and in B32 |
| F1(3) attribute the 10 bench legs by refusal branch | 11/11 `outside_support_polygon`, per-leg table above |
| pinned scratch export + own socket | `~/.cache/parcel-0e/c2nif`, orphan check `clean=True ours=[]` |
| no other files | `git status` below |
| no watcher loops left behind | verified below |

**Test record for F1** (all through the guard, `TMPDIR` unset):

```
--label C0f1       tests/test_mutation_panel_freshness.py -m "not slow"   → 7 passed, 4 deselected in 0.19s
--label C0f1clean  tests/test_mutation_panel_freshness.py (clean worktree) → 11 passed in 46.37s
```

The clean-worktree row is C0's acceptance bar re-verified with the
direction-aware messages in place: it was `4 passed` before F1 and is
`11 passed` now (3 pre-existing slow + 1 declared-disable ratchet + 7 fixtures).

**Files after F1** — unchanged set plus one backlog entry:
`src/parcel_robot/simulation/headless_city.py`, `tests/test_arrival_settle.py`,
`tests/test_mutation_panel_freshness.py`, `scripts/mutation_panel.py`,
`evals/nav_instruct/results/mutation_panel.json`,
`research/20260829/nav-gen-attribution-1/run.py`, **`backlog/BLOCKED.md`**,
`scrum/20260829/task_2/C0_C2_STATUS.md`. The F1 probe (`f1_probe.py`) exists
only inside the pinned scratch export and is not in the repo.

## F1 — concurrent-edit notice (read this before auditing `scripts/mutation_panel.py`)

While F1 was being written, **another session began the B32 second half in this
same tree**: guard log `2026-08-30 00:23:15 START label=c0-panel-remediation ::
.parcel/bin/python scripts/mutation_panel.py --out ~/.cache/parcel-c0-remediation/panel.json`.
Its working-tree diff to `scripts/mutation_panel.py` adds full-matrix
**"intervention witnesses"** to `PANEL_EPISODE_IDS`, a `reactive_gate_coverage`
block, a fifth safety-relevant check `reactive_gate_exercised`
(`changed_nonzero > 0`), and `PANEL_MATRIX_SEED` / `PANEL_MATRIX_DIGEST`. That
is exactly "re-choose panel episodes on which the gate binds", and it is the
right response to the addendum.

**I did not touch `scripts/mutation_panel.py` again after that started**, and my
C0(b) artifact will be superseded by theirs — which is the correct outcome, not
a regression. Two consequences for the verifier:

- My C0 acceptance row (`11 passed`, clean worktree) was measured on the file
  state **before** that session's edits; it is not a claim about the tree as it
  stands now, and `artifact == source constant` is currently `False` because
  they extended `PANEL_REGENERATION_PROVENANCE` without having regenerated yet.
  The artifact still carries the mandated `no_authority_disagreement disabled as
  a kill channel` phrase, so my declared-disable ratchet still holds.
- **My F1 helper is forward-compatible with their schema, verified:** with their
  `SAFETY_RELEVANT_CLEAN_CHECKS = (…, 'reactive_gate_exercised')` and the new
  `reactive_gate_coverage` key in `clean_safety_fields`, a green-direction drift
  on a declared-disabled channel still routes to the **withdraw** message. The
  helper reads `clean_checks` generically and never enumerates check names, so
  their fifth check needs no change here. Fixture tests: `7 passed, 4 deselected
  in 0.19s` against the current tree.

`tests/test_mutation_panel_freshness.py` is **entirely this card's work** — all
eight added test functions are mine; no foreign edit is present in it.
