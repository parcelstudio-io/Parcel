# MOVE-1 — why doesn't the dog move? · status

**Card:** `scrum/20260821/task_20/README.md` · **Executor:** Claude Opus ·
**Auditor:** Fable · **Date:** 2026-08-22
**Pre-registration:** `evidence/MOVE1_PREREGISTRATION.md`, written before the
first diagnostic arm ran and before the patrol module existed.

**Result: COMPLETE. E2-D2 has a measured answer that closes arithmetically to
2 mm. The patrol driver exists, runs in the dev scene inside its budget, and
met 4 of its 5 pre-registered targets — the fifth (`collision count 0`) is
recorded as a MISS with its mechanism measured. Two defects in my own module
were found by running it and are reported here rather than quietly fixed.**

---

## 0. Entry conditions (chain contract v2)

| Check | Result |
|---|---|
| Tree quiescence, on CONTENT not mtime | **PASS** — `git status --porcelain` (17 modified + untracked) and the SHA-256 of all 28 existing files recorded at `02:55:31Z` and **byte-identically re-read** at `02:56:05Z`, `02:56:33Z`, `02:56:52Z` and `02:57:15Z` (**104 s** span, > the required 90 s). No waiver was needed: nothing moved, so no positive attribution was required |
| Modified set attributes to predecessors | **PASS** — exactly E-2's certified set: W-1's 7 + C-1's 4 + C-3's 5 + C-3's `runtime_assets/MANIFEST.json`. HEAD `71b39a1`, nothing staged or stashed |
| Entry gate `scripts/ci_gate.py` | **PASS** — every hard gate green, default-suite **7,934 passed / 9 skipped**, elapsed 332.8 s. Exactly the count the chain audit certified |
| Predecessor deliverables present | **PASS** — `task_11b/evidence/rerun_live_20260821T235718Z/` present with its harness; no HALT condition |
| Held-out scene | **UNTOUCHED and UNNAMED.** `city_block_b` appears in no file this card wrote, so **no allowlist seat was needed or taken** (contract v2 rule 4 considered and found not to apply). The scene was never loaded, rendered or referenced |
| Owner store | **UNCHANGED — SHA-16 `40506fd96fc61c34`, exactly the value the chain audit recorded**, mtime 12 h older than this session. See §0.1: the harnesses' own check was vacuous and is corrected here rather than quoted |

One live process was noted and attributed rather than waved through: pid
2892479, `kill_probe.py`, 31 h old, running from an **earlier session's
scratchpad** (card R-17), writing nothing inside the repo.

### 0.1 A guard of mine that did not guard — corrected, not quoted

Every harness this card wrote checks the owner store at
`~/.parcel/parcel_memory.sqlite3`. **That file does not exist.** The real store
is `<repo>/parcel_memory.sqlite3` (`.gitignore:15`, and
`memory_path.owner_store_paths()` names it first). So the
`"owner_store": {"unchanged": true}` line in all six run summaries is comparing
`None` to `None` — it is **vacuous, and it would have reported success no matter
what happened to the real store.**

The store is in fact untouched, verified directly and independently of that
broken check:

| | |
|---|---|
| `sha256(<repo>/parcel_memory.sqlite3)` SHA-16 | **`40506fd96fc61c34`** |
| Value recorded by the chain audit and by C-2 | `40506fd96fc61c34` |
| mtime | `Aug 21 10:31` — **12 h before this session began** |

Mechanism, not luck: every arm ran with `memory.path: ":memory:"`, and the
online map was constructed with no store declaration, which C-2's refusal gate
turns into a refusal rather than a default file.

I am recording this because a guard that cannot fail is worse than no guard —
it is the shape of reasoning this register exists to catch, and it was mine.

---

## 1. E2-D2 — the answer

> **The robot did not move because it was told, 160 times, to walk straight
> into its own owner, and the reactive safety gate correctly refused.**

Not a dropped command. Not a broken actuator. Not the harness's zero-velocity
interleave. **A blocked heading, refused by a gate that was working exactly as
designed** — and an arbiter that accepts *intent* while a different authority
owns the *body*.

### 1.1 The measurement

Four arms, 40 s each, fresh simulator per arm, real `build_runtime`, C-1's
configuration changed in exactly one axis per arm. Per-tick trace of the real
dispatch chain (`evidence/run_move1_diagnosis.py`; three runs, the reported one
is `evidence/diagnosis_20260822T031233Z/`).

| Arm | Change from C-1's cell | Path length / 40 s |
|---|---|---|
| `replicate` | none (C-1's alternating 0.25 / zero drive) | **0.2259 m** |
| `held` | never commands zero | 0.3186 m |
| `held_static` | never commands zero, `--static-city` | 0.3133 m |
| **`steered`** | **may TURN when the lane ahead is short** | **3.7768 m** |

### 1.2 The pre-registered discriminators, as they fell

| id | Rule | Outcome |
|---|---|---|
| **D0** | `replicate` ≤ 0.40 m ⇒ valid | **PASS, 0.2259 m.** C-1's cell reproduces (C-1 measured 0.2314 m OFF / 0.1705 m ON) |
| **D1** | H-A (harness zero-interleave) iff `held` ≥ 3× `replicate` | **REFUTED — ratio 1.41.** Removing every zero command buys 41 %, not 300 % |
| **D2** | H-B (dynamic agents) iff ≥30 % named-cause ticks **and** `held_static` ≥ 2× `held` | **REFUTED — ratio 0.98.** Freezing every pedestrian and cyclist changes displacement by −2 % |
| **D3** | H-C (locomotion drop) iff `held_static` < 1.0 m **and** ≥0.15 m/s delivered on ≥20 % of ticks | **REFUTED.** The locomotion path delivered the full **0.25 m/s** whenever the gate allowed it, and the `steered` arm drove 3.78 m through that same path |
| **D5** (addendum) | blocked-heading confirmed iff `steered` ≥ 3.0 m | **CONFIRMED — 3.7768 m, 11.9× `held`.** One change: permission to turn |
| **D6** (addendum) | compounding claim withdrawn unless <0.9× single application on ≥50 % of slowing ticks | **CONFIRMED — 100 % of 255 slowing ticks** in `held` |

### 1.3 The branch, named by the running product

94 % of the static arm's ticks first landed in a bucket I could only call
"other". "Other" is not an attribution, so I measured it: a probe
(`evidence/probe_stop_branch.py`) wraps `reactive_safety._stop_translation` and
reads `sys._getframe(1).f_lineno`, so the **line number is the reason**, read
out of the running product rather than inferred from it.

```
"stop_translation_call_sites": [{"line": 243, "count": 374,
  "source": "return _stop_translation(command)",
  "context": ["if toward_person and person_distance <= predictive_person_stop:", ...]}]
"scan_health_calls": {"allowed": 398, "refused": 0}
```

**374 of 374 stops, one branch: the person predictive stop.** Scan health never
refused. The time-to-collision gate never intervened (`min_ttc_s` null on all
398 ticks; `ttc_gate_zeroed` 0 in every arm).

And the person is the **owner**: `nearest_person_m` is `None` on all 374 stopped
ticks, so the entry that stopped the robot can only be the owner track. C-1's
own artifact records it — `on_api_state.json`: `owner {x: 2.0, y: -0.5,
visible: true}`, and `city_block.xml:254` places `<body name="owner"
pos="2.0 -0.5 0">`.

### 1.4 The arithmetic closes

Stop condition: owner centre distance ≤ `person_stop_m` (1.2) +
`owner_collision_envelope_m` (0.55) + `v·reaction_time_s` (0.12).

Solving `hypot(2.0 − x, 0.5) = 1.75 + 0.09 × 0.12` gives **x = 0.3117 m**.
Measured final x: **0.3135 m** (probe) and **0.3134 m** (`held_static` arm).
**Agreement to 1.8 mm.** The robot stopped precisely at its owner-safety
standoff and stayed there.

### 1.5 Why "accepted" and "moved" are different numbers

`160/160 accepted` and `0.23 m moved` were never in tension. `submit_motion`
consults the **arbiter**, which arbitrates *intent* between sources; the
**reactive gate** in `_dispatch_active` decides what reaches the body. The
arbiter had no reason to refuse: the request was well-formed and voice held the
lane. The gate refused every tick, correctly. Reading acceptance as a promise of
motion is the error — and it is C-1's harness that made it, by never steering.

### 1.6 A real defect found on the way: compounding gate attenuation

`runtime.py:8448` calls `velocity_smoother.force(command, now=now)` with the
**post-gate** command. The acceleration ramp therefore restarts from the value
the gate already scaled, and the gate scales it again next tick — a geometric
series converging on `s·a·dt/(1−s)` instead of the intended `s·v_target`.

Measured in `held`: the gate's own slow-scale is `s ≈ 0.2397`; one application
to the commanded 0.25 m/s would deliver **0.0599 m/s**; the actuator actually
received **0.0216–0.0277 m/s** — **100 % of 255 slowing ticks below 0.9× a
single application**. This is a **~2.2× unintended speed loss inside the slow
band**, in the safe direction, and it is not this card's to fix
(`runtime.py` is outside OWNS). Filed as **MOVE1-D1** in §5.

---

## 2. The patrol driver

`src/parcel_robot/patrol/` — a pure `PatrolPolicy` (decidable in a unit test
with no simulator, socket or clock) plus a thin I/O `PatrolRunner`. The policy
is a **proposer** that keeps the body out of situations the reactive gate would
have to veto. No safety gate is re-implemented, weakened, or touched.

The priority ladder is the contract: budget → contact → people → geometry →
hysteresis → cruise.

### 2.1 Pre-registered acceptance

Dev scene `city_block` (sha `e89f4f12…`, unchanged), 120 s budget,
`evidence/patrol_city_block_20260822T035126Z/summary.json`.

| id | Target | Result |
|---|---|---|
| **P1** | path length ≥ **5.0 m** | **PASS — 5.0137 m** (and ≥ 20× C-1's 0.171 m, which was the secondary form). Met by 1.4 cm: reported as the narrow pass it is |
| **P2** | ≥ **3** map entries, each with writer provenance | **PASS — 57 entries**, all four provenance fields populated on all 57 (`seat=patrol`, `detector_name=camera_ingress`, `scene_id=city_block`, session id) |
| **P3** | hard-safety violations: **collision count exactly 0** | **MISS — 10 collision ticks.** Mechanism in §2.2 |
| **P4** | ≤ 120 s + 20 s teardown, runner stops itself | **PASS — 120.12 s**, `stopped_reason: budget_exhausted` |
| **P5** | per-scene runner, path trace + map-growth record | **PASS** — `--scene` argument; 472 path samples and 472 map-growth samples with per-entry provenance |
| **V1** | ≥ **2** distinct non-volatile classes observed | **PASS — 5** (`building`, `door`, `lamppost`, `storefront`, `window`) |
| **V2** | person/volatile observations persisted: **exactly 0** | **PASS — 0.** 76 of 267 observations refused by C-2's hygiene gate |

### 2.2 P3, the miss, measured rather than explained away

10 of 472 ticks carried `observation.collision`. The pre-registered target said
zero, so this is a **MISS**. What the number is, measured:

* The diagnosis arms recorded **50 collision ticks with the robot commanded
  into a wall and moving 0.23 m**, and **0 collision ticks with
  `--static-city`** and the same commands.
* So contact in this scene is dominated by the dynamic city's agents reaching
  the robot, not by the robot driving into geometry — a robot that barely moves
  still accumulates 50.
* The patrol's 10 is **5× fewer than a near-stationary robot in the same city**,
  while covering 22× the distance.

That is an explanation of the number, **not** a re-interpretation of the
target. The target was "collision count exactly 0" and it was not met. Whether
`observation.collision` is the right hard-safety denominator when a simulated
cyclist rides into a stationary robot is a question for the board, filed as
**MOVE1-D3**, not something to settle inside the card that missed it.

### 2.3 Two defects in my own module, found by running it

Both were found because the patrol was run for real, and both are recorded with
the run that exposed them rather than silently folded into a final version.

1. **Distance-only person standoff deadlocked the patrol.**
   First run (`patrol_city_block_20260822T034036Z`): **0.0149 m** of path,
   `turn_hold` on 303 of 470 ticks. A robot turning in place never changes its
   distance to a stationary owner, so a distance-only release can never fire.
   Fixed by asking about **direction**, exactly as the product gate does
   (`reactive_safety._toward`). Seeds S20–S22 pin it.
2. **`snapshot()["robot"]["heading"]` is DEGREES; I read it as radians.**
   Second run (`patrol_city_block_20260822T034638Z`): **0.0060 m**, `turn_hold`
   369/471, with a live probe reporting a "bearing" of **−81.9 rad**.
   `runtime.py:8000` is `"heading": math.degrees(observation.robot.yaw)`.
   Fixed; seed S24 pins it, and the test asserts against the runtime's own
   conversion rather than restating the constant.

Three live patrol runs are kept — `…034036Z`, `…034638Z`, `…035126Z` — so the
0.0149 → 0.0060 → 5.0137 m progression is auditable, not just its endpoint.

---

## 3. E2-D3 — the T1 query vocabulary, answered by running it

The pre-registered design was "open-vocab place nouns for map building,
owner-corpus nouns in-loop, no sidecar". Running it produced a **correction the
research could not have supplied**:

```
ValueError: camera-ingress queries must include the whole word 'person' so the
PG-1 safety lease is actually taken; a camera that never asks about people must
not claim the person-relevant admission path
```

So the answer is **two sets, not one**:

* **`ingress_queries()`** — what the detector is asked. **Must** contain
  `person`, or `CameraStreamConfig.from_section` refuses to build the runtime.
* **`DEFAULT_MAP_SWEEP_VOCABULARY`** — what may become a place. Must **not**
  contain `person`; C-2's `is_volatile_label` refuses it, and the patrol relies
  on that refusal rather than on not asking.

Conflating them is a safety bug in one direction and a hygiene bug in the
other. Measured live: batch `[person, building, storefront, door, window,
lamppost, bench, tree]`, 267 observations, **76 refused**, **0 person entries**,
5 place classes learned. Seeds S18, S19 pin both directions; one test drives the
product's real validator rather than a restatement of it.

**No sidecar was read.** A test walks the module's AST and fails on any string
literal or import naming `scene_truth`, `scenes/`, `demo_pois` or
`semantic_map` (S16 pins it).

---

## 4. Register — tests, seeds, gate

| Item | Result |
|---|---|
| New tests | **37**, all in `tests/test_move1_patrol.py` |
| Seeds | **24/24 RED** (`evidence/MOVE1_SEEDS.json`). Zero GREEN, zero SEED_BROKEN in the reported run |
| `__pycache__` purge per restore | yes, `src/` and `tests/`, before and after every mutation |
| Restore verification | `restored_hashes_match: true` — SHA-256 re-checked after every one of the 24 restores |
| Fresh-interpreter canary | **PASS** — new process, cold imports, after the last restore: `turn_person 0.0` |
| Final sweep postdating the last source write | the **exit `scripts/ci_gate.py`** run in §4.1 — see the declared deviation D3 below |
| Repo-root stray sweep | clean; every file this card created is under `src/parcel_robot/patrol/`, `tests/test_move1_patrol.py`, or `scrum/20260821/task_20/` |
| Owner store | unchanged across all six live runs |
| git | no commit, no stage, no stash |

### 4.1 Exit gate

Recorded in `evidence/MOVE1_EXIT_GATE.txt`.

### 4.2 Declared deviations

* **D1 (pre-registered, §A.4).** The diagnosis wraps three runtime **instance**
  attributes plus two module attributes. There is no public per-tick trace, and
  editing `runtime.py` is outside OWNS. Every wrapper observes and forwards; none
  alters a value the dispatch path then consumes.
* **D2 (pre-registered, addendum A1).** The `steered` arm and the two extra
  discriminators D5/D6 were added after M1's first run. Their predictions were
  fixed in the pre-registration **before** the confirmatory arm ran, and the
  reason (my classifier read the omnidirectional nearest obstacle where the gate
  reads the directional minimum) is recorded there.
* **D3 (declared here).** The seed harness's baseline and final sweeps run the
  **targeted** test file, not the whole suite. The first version ran the full
  suite twice — including the nightly `slow` tier, which the gate deselects —
  costing 13 minutes and reporting **17 errors that also appear without any of
  this card's mutations applied**. Those errors are in the `slow` tier, outside
  the gate's `-m 'not slow'` scope, and are **not** this card's; they are noted
  here because they were observed, and filed as **MOVE1-D2**. The final
  full-suite sweep postdating the last source write is the exit gate itself.
* **D4 (declared here).** The patrol module was edited **after** the first seed
  run, twice (§2.3). Seeds were re-run in full each time; the reported
  `MOVE1_SEEDS.json` is the run against the final source, and three seed anchors
  that went stale in the refactor were repaired and re-run rather than left
  `SEED_BROKEN`.

---

## 5. Defects filed (for the board — placing them there is the auditor's act)

* **MOVE1-D1 — compounding gate attenuation.** `runtime.py:8448` force-syncs the
  velocity smoother to the **post-gate** command, so the reactive gate's slow
  scale is re-applied every tick to an already-scaled value. Measured: 100 % of
  255 slowing ticks deliver below 0.9× a single application; steady state
  0.0216–0.0277 m/s where one application gives 0.0599 m/s. Safe direction, but
  it means the "slow band" is ~2.2× slower than its own policy intends, and any
  future latency or throughput number taken inside that band is measuring the
  compounding, not the policy. Needs a card that OWNS `runtime.py`.
* **MOVE1-D2 — 17 errors in the nightly `slow` tier.** Observed in two
  full-suite runs (`-m` unset) with and without this card's mutations, so not
  this card's. The gate deselects the tier, so they are invisible to every
  executor who only runs `ci_gate.py`. Someone should look before the tier is
  trusted.
* **MOVE1-D3 — `observation.collision` may be the wrong hard-safety
  denominator.** A stationary robot in `city_block` accrues 50 collision ticks
  in 40 s from dynamic agents riding into it; the same robot with
  `--static-city` accrues 0. Any card pre-registering "collision count 0" in the
  dynamic city is pre-registering a target the robot cannot control. Needs an
  owner ruling on whether agent-initiated contact counts against the robot.
* **MOVE1-D5 — the same vacuous owner-store guard is in C-1's re-dispatch
  harness, and I inherited it by copying the pattern.**
  `task_11b/evidence/run_c1_rerun_live.py:385` reads
  `Path.home() / ".parcel" / "parcel_memory.sqlite3"`, which **does not exist**;
  the real store is `<repo>/parcel_memory.sqlite3`. So the
  `owner_store.unchanged: true` field in
  `rerun_live_20260821T235718Z/summary.json` — the summary whose SHA the chain
  audit hash-verified — is `None == None`, and would read `true` however the
  store had been treated. C-1's *other* harness (`run_c1_cpu_live.py`) uses the
  real path, as do C-2's and C-3's, so this is one harness, not a pattern
  across the chain. **No harm done in either card** (both ran `:memory:`, and
  the store's SHA-16 is still `40506fd96fc61c34`), but two cards have now
  reported a guard that cannot fail. Worth a one-line fix in the harness and a
  note to future executors not to copy that line. Reported here rather than
  edited into C-1's evidence, which is its executor's record.
* **MOVE1-D4 — the patrol's P1 margin is thin.** 5.0137 m against a 5.0 m
  target is a 0.3 % margin on a single run; it should not be read as a stable
  capability number until it is repeated. The card that consumes this (E-2's
  Phase 1) should re-measure rather than inherit it.

---

## 6. What this card does NOT claim

* **Not** that the patrol is tuned. It met its floor by 1.4 cm on one run, with
  `net_displacement` only 0.134 m — it explores locally rather than covering
  ground, and §5 MOVE1-D4 says so.
* **Not** that C-1's stream is fit for grounding. All 37 frames were
  `expired_at_publish`; C-1's disclaimer stands untouched and the stream was
  consumed as the diagnostic stream it is.
* **Not** that the map entries are correct places. 57 entries with provenance is
  a *growth* record; correctness against scene truth was not measured here and
  C-2's own 0/5 live-corpus miss is unaddressed by this card.
* **Not** anything about generalization. The held-out scene was never named,
  loaded or referenced, and its exposure remains **UNSPENT**.
* **Not** that `min_ranking_margin`, PG-3 thresholds, or the C-3 tail moved.
  Untouched.

## 7. What a re-dispatch of E-2 now has

E-2 §6 item 1 — "a patrol that moves the robot through a scene while the
camera→detector→map loop runs" — **exists and has run**: 5.01 m of path, 57
provenanced map entries, 5 place classes, inside a 120 s budget, in the dev
scene, with the runner invocable per scene. E2-D2 is answered. E2-D3 is
answered. Items 2–5 of that list (C-3's G2, C-3's G1, the decoys, the allowlist
seat) are untouched and still gate E-2.
