# GATE-0 — the gate tells the truth on a clean clone · status

**Card:** `README.md` · **Executor:** Claude Opus (session 799cb356) ·
**Verifier:** Fable · **Board:** `../TASK_BOARD.md` · **Base:** HEAD `8862220`
**Pre-registration:** `PREREGISTRATION.md` (fixed before any number below).

## Headline

**A fresh clone now reaches every gate and prints a complete report — measured,
both ways, in the same scratch clone.** With the Unitree pack absent, the
runner at HEAD `8862220` produced **zero bytes of stdout** and an unhandled
`ValueError: XML Error: Error opening file
'../../../third_party/unitree_mujoco/unitree_robots/go2/go2.xml'`; the GATE-0
runner on the identical tree produced the full summary **and** a complete
`--json` naming **all ten** stages, with `unitree-assets` FAIL saying exactly
what is missing, `hard-safety` contained as ERROR, and six later stages still
reporting their verdicts. The Go2 MJCF is now a **tracked, manifest-pinned
20-file / 27.1 MiB subset** at its upstream path (so no scene byte and no frozen
scene digest moves), the ruff verdict is pinned to a named linter, and
`protocol.py`'s mutable dataclass default — the thing that made
`requires-python >= 3.10` false on exactly CPython 3.11 — is gone and proven
green on a real 3.11.

**All eleven pre-registered rows MET**, with two qualifications stated on their
own rows and not smuggled: R9's "tracked-only clone" was made tracked by a
commit **inside the cache directory only** (git is read-only for executors in
the project tree), and R8's osmesa change is correct-by-construction but
**unexecuted** — Actions has never run. Six product-file seeded REDs, every one restored byte-identically, plus
eighteen permanent in-suite seeds. One regression this card caused was found by
its own clean-clone row and repaired (deviation 10).

## What changed

`git diff --stat` on OWNS (against HEAD `8862220`), plus the untracked files
this card creates:

```
 .github/workflows/ci.yml              |  28 ++-
 .gitignore                            |  31 ++-
 pyproject.toml                        |   9 +-
 scripts/ci_gate.py                    | 410 ++++++++++++++++++++++++++++++++--
 scripts/ci_ruff_baseline.json         |   4 +-
 src/parcel_robot/realtime/protocol.py | 184 ++++++++++++++-   <- see NOTE
 tests/test_ci_gate.py                 | 275 ++++++++++++++++++++++-
 tests/test_dynamic_city.py            |   3 +-
 tests/test_eval_assertions.py         |  10 +-   <- repair, see deviation 10
 tests/test_held_out_scene.py          |  52 ++++-
 tests/test_realtime_protocol.py       |  67 ++++++
 tests/test_sim.py                     |  10 +-
 12 files changed, 1040 insertions(+), 43 deletions(-)

 new: tests/test_unitree_asset_pack.py                    452 lines, 26 tests
 new: third_party/unitree_mujoco/PROVENANCE.json          117 lines
 new: third_party/unitree_mujoco/{LICENSE, unitree_robots/go2/**}
      19 payload files, 28,427,057 bytes (27.11 MiB), newly un-ignored
 new: scrum/20260822/task_20/{PREREGISTRATION.md, GATE0_STATUS.md}
 new: scrum/20260822/task_20/evidence/
      clean_clone_run_A_head_no_pack.log      (HEAD's runner: empty stdout + traceback)
      clean_clone_run_B_gate0_no_pack.log     (GATE-0's runner, same tree: 10 named gates)
      clean_clone_run_D_gate0_with_pack.log   (the pre-registered row, 8/10 green)
      seed_harness.py                         (the seed/restore/verify harness)
```

The live scratch clone is left in place for the verifier at
`/home/jaewoo-jang/.cache/parcel-gate0/clean` (its own CPython 3.12.13 venv at
`.venv/`); `.../stage` is the intermediate that made the pack tracked. Nothing
runs there now.

**NOTE on `protocol.py`.** That file is shared with **TURN-1** (`task_21`),
which is executing right now and landed `TurnDetection` + `SessionUpdate.turn_detection`
(~174 of those 184 lines) while this card was open. **GATE-0's contribution to
that file is 11 lines in two hunks**: `from dataclasses import dataclass, field`
and the `RetainedEvent.fields` factory with its comment. Nothing of TURN-1's was
read, reverted, or reformatted. Same caveat, smaller, for
`tests/test_realtime_protocol.py` (all 67 insertions are GATE-0's; TURN-1's
tests live in `tests/test_turn1_*.py`).

Substantively:

1. **Vendored Go2 MJCF subset**, at its current path. `.gitignore`'s blanket
   `third_party/` becomes an intentional carve-out that exposes exactly the
   manifest and nothing else (`git check-ignore -v` confirms `Go2.png`,
   `readme.md`, `scene_terrain.xml`, and all four unrelated nested clones stay
   ignored). `PROVENANCE.json` pins upstream
   `ae6a8403e272733e9996ef59990880330496177f`, the URL, the BSD-3 licence and
   per-file size + sha256, and records what was deliberately excluded.
2. **`unitree-assets`** — a new hard stage, ordered **before** `hard-safety`,
   which is the gate that used to die on the missing pack. It checks the pinned
   revision against a constant `ci_gate.py` holds *independently of the
   manifest*, refuses unsafe manifest paths before joining them to disk,
   verifies size + sha256, closes the set against what git would actually ship,
   refuses a tracked gitlink, and compiles every product scene that includes the
   pack — **geometry only** (`MjModel.from_xml_path`, no renderer, no step, no
   model over pixels).
3. **Per-stage containment.** `run_commit_tier` is a deferred stage table run
   under `run_stage(...)`: `except Exception` (never `BaseException`) →
   `GateResult(name, tier, hard, "error", …)` with a bounded traceback tail in
   `extra`. `COMMIT_TIER_STAGE_NAMES` is the literal contract the tests hold it
   to. `KeyboardInterrupt` and `SystemExit` still propagate; a contained ERROR
   still exits non-zero.
4. **The ruff verdict is pinned.** Dev extra `ruff==0.16.1` (was `>=0.12,<1`);
   `scripts/ci_ruff_baseline.json` stamps `ruff_version: "0.16.1"`;
   `evaluate_ruff` returns ERROR — never a verdict — when the running ruff, the
   stamp, or either one's readability disagrees. **The 7 fingerprints were not
   regenerated**: the file was edited to add the stamp, so no concurrent card's
   in-flight debt could be absorbed into the baseline.
5. **`protocol.py` `RetainedEvent.fields`** → `field(default_factory=lambda: MappingProxyType({}))`.
6. **`ci.yml`**: `MUJOCO_GL: osmesa` on both hosted jobs, plus the apt step that
   makes osmesa mean something (`libosmesa6`) and the native library
   `sounddevice` dlopens (`libportaudio2`) — `pip check` cannot see a missing
   `.so`.
7. **Four asset-absence `skipif` guards removed** (3 × `test_sim.py`,
   1 × `test_dynamic_city.py`). Their reason — "scene not checked out" — is now
   unreachable, and while they existed a clean clone reported three SKIPs
   instead of "the simulator is absent".

## How verified

Environment: `.parcel/bin/python` 3.14.4, `.parcel/bin/ruff` 0.16.1, `TMPDIR`
unset for every pytest invocation. Scratch under
`/home/jaewoo-jang/.cache/parcel-gate0/`. No hosted spend; no credential read.

### Pre-registered rows

| Row | Verdict | Measurement |
|---|---|---|
| **R1** pack closure + budget | **MET** | `git ls-files --others --exclude-standard third_party/ \| wc -l` → **20**; `git check-ignore -v` on `Go2.png` / `readme.md` / `third_party/CityWalker` → still ignored; **27.11 MiB** (28,427,057 B) ≤ 30 MB; zero `.git` paths and zero gitlinks in the tracked-only clone |
| **R2** provenance pins the revision | **MET** | `upstream_revision == ae6a8403e272733e9996ef59990880330496177f`; 19/19 payload sha256 + size reproduce from disk (`evaluate_unitree_assets` re-derives every hash on each run) |
| **R3** hard stage before hard-safety | **MET** | `COMMIT_TIER_STAGE_NAMES.index("unitree-assets") = 1 < index("hard-safety") = 2` (executable: `test_the_asset_stage_runs_before_the_gate_that_used_to_die_on_it`); `status=pass` on this tree; compiles `city_block.xml` (139 geom / 26 mesh) **and** `city_block_b.xml` (132 geom / 24 mesh) |
| **R4** seeded RED, asset pack | **MET (9 of 5 asked)** | deleted payload, tampered byte, size-only change, wrong revision, 4 × unsafe manifest path, missing manifest, unparseable manifest, uncompilable scene, no-including-scene, tracked gitlink, unmanifested file smuggled through the carve-out — **every one a named hard-red `unitree-assets` GateResult, no traceback** |
| **R5** containment | **MET** | with `evaluate_ruff` raising, `--json` emits **10/10 named stages**, gate[0] `status="error"` carrying `RuntimeError` in `extra.traceback_tail`, exit code 1, no traceback in the human summary; `KeyboardInterrupt` and `SystemExit` propagate |
| **R6** ruff pinned + stamped | **MET** | `ruff==0.16.1` in the dev extra; baseline stamped `0.16.1`; mismatch/unstamped/unreadable → `error`; **7 fingerprints, 0 new** measured in the clean clone (`ruff 0.16.1: 7 violation(s), baseline 7, new 0`); `scrum/20260822/task_9/evidence/*.py` → `All checks passed!` |
| **R7** CPython 3.11 imports the protocol | **MET** | before: `ValueError: mutable default <class 'mappingproxy'> for field fields is not allowed: use default_factory` on CPython **3.11.15**; after: `3.11 import OK mappingproxy False` (distinct, immutable, empty) |
| **R8** hosted runner GL | **MET (unexecuted)** | both jobs `MUJOCO_GL: osmesa`; YAML parses; **no hosted run exists** — see "what this does not prove" |
| **R9** clean clone | **MET, with a declared deviation** | see below |
| **R10** held-out seat | **MET** | `tests/test_unitree_asset_pack.py` seated in `ALLOWED` with a reason; `LOAD_ALLOWED` grown from a pair to three, named, with the reason in the constant's docstring; commit-tier selection of `test_held_out_scene.py` + `test_unitree_asset_pack.py` → **32 passed, 1 deselected** |
| **R11** OWNS hygiene | **MET** | `ruff check` on every owned `.py` → `All checks passed!`; targeted pytest green (below) |

### The clean-clone A/B (R9)

Built in `/home/jaewoo-jang/.cache/parcel-gate0/`: `git clone` of HEAD `8862220`
→ GATE-0's 13 files + the 20-file pack copied on → committed **in the cache
directory only** → re-cloned, so the pack is genuinely *tracked* in the clone
under test. Then a fresh CPython **3.12.13** venv (the interpreter `ci.yml`
pins) and `pip install -e ".[dev,voice]"` (rc=0; resolved `ruff-0.16.1`,
`mujoco-3.12.0`, `numpy-2.5.2`, `websockets-17.0.1`).

```
git -C clean ls-files third_party | wc -l            -> 20
test -e clean/third_party/unitree_mujoco/.git        -> absent
git -C clean ls-files -s third_party | grep ^160000  -> 0 gitlinks
```

**A — the historical clean clone** (HEAD's runner, pack hidden):

```
$ ./.venv/bin/python scripts/_head_ci_gate.py --tier commit --json
rc=1
--- stdout ---                       (empty: no summary, no JSON)
--- stderr ---
ValueError: XML Error: Error opening file
  '../../../third_party/unitree_mujoco/unitree_robots/go2/go2.xml'
Element 'include', line 17
```

**B — the same tree, GATE-0's runner, pack still hidden** (4 m 07 s, exit 1):

```
[  FAIL] HARD  ruff
[  FAIL] HARD  unitree-assets   third_party/unitree_mujoco/PROVENANCE.json is MISSING
                                — the vendored Go2 MJCF pack is not in this checkout;
                                  both product scenes are uncompilable
[ ERROR] HARD  hard-safety      ValueError: XML Error: Error opening file '...go2.xml'
                                [stage contained by the GATE-0 wrapper; later gates still ran]
[  PASS] HARD  release-parity            91 packaged asset(s) byte-identical
[  PASS] HARD  assertion-evals           5 fixtures reproduce 20 pinned findings
[  PASS] HARD  tier-coverage             8729 = 8648 commit + 81 nightly, no orphans
[  PASS] HARD  model-off-non-inferiority 23 passed
[  PASS] HARD  release-parity-integrity  10 passed
[  FAIL] HARD  owner-store-isolation     1 failed, 4 passed, 1 skipped
[  FAIL] HARD  default-suite             138 failed, 8432 passed, 45 errors
```

JSON: 10 gates named, valid, `elapsed_s` recorded, **no traceback in the
summary**. That is the row: a fresh clone that is missing its simulator now
*says so, by name, first*, and still delivers every other verdict.

**C/D — pack present, the pre-registered row** (C: 319.6 s; D: **307.6 s**;
exit 1, valid JSON, 10 named gates, **no traceback anywhere**). D is C re-run
after the one regression C found was repaired (deviation 10); D's numbers are
quoted:

```
[  PASS] HARD  ruff             ruff 0.16.1: 7 violation(s), baseline 7, new 0
[  PASS] HARD  unitree-assets   upstream_revision ae6a8403e272 == pin: True | payload: 19
                                manifest file(s), 27.1 MiB on disk | shipping closure: 20
                                path(s), unmanifested=0 hidden=0 | gitlinks: 0 |
                                city_block.xml: 139 geom / 26 mesh in 0.26s |
                                city_block_b.xml: 132 geom / 24 mesh in 0.09s
[  PASS] HARD  hard-safety      nav frozen baseline ...v4-20260811T070536Z: collisions=0
                                false_arrival=0 | mutation panel clean: collisions=0
                                no_false_arrival=True | freshness: reproduces live = True |
                                follow-bench 7 rows all 0 | walk_with_me 1/2 rows all 0
[  PASS] HARD  release-parity            91 packaged asset(s) byte-identical
[  PASS] HARD  assertion-evals           5 fixtures reproduce 20 pinned findings
[  PASS] HARD  tier-coverage             8729 = 8648 commit + 81 nightly, no orphans
[  PASS] HARD  model-off-non-inferiority 23 passed
[  PASS] HARD  release-parity-integrity  10 passed
[  FAIL] HARD  owner-store-isolation     1 failed, 4 passed, 1 skipped
[  FAIL] HARD  default-suite             51 failed, 8564 passed, 31 skipped,
                                          81 deselected, 3 xfailed, 0 errors, 4m53s
```

**Eight of ten gates are green on a fresh clone, and `hard-safety` is one of
them** — that is the whole card in one row. It is the gate that used to raise,
and its mutation-panel freshness check now re-derives a live clean run from the
tracked pack. Run B's **45 errors became zero** once the pack was present, and
138 default-suite failures became **51**.

Scene compiles in the clean clone with **no developer cache**:

```
city_block.xml  : 0.171 s  ngeom=139 nmesh=26
city_block_b.xml: 0.094 s  ngeom=132 nmesh=24      (< 1 s, pre-registered)
```

**What the 51 remaining failures are** (measured by splitting the clean clone's
selection; every one of these families is **green on the project tree** — the
five non-external families alone are `304 passed` there — so none is a GATE-0
regression. They are artifacts and optional wheels a clean clone does not
have):

| Family | n | Cause |
|---|---|---|
| `test_barn_*` | 29 | `evals/external/.gitignore:1` ignores `results/*` while **55 sibling files are tracked**. `evals/external/results/barn_ros2/upstream-mppi-world0-20260803.json` is on disk here and absent from every clone. **Structurally the same defect this card just fixed for the Unitree pack, one directory over.** |
| `test_habitat2020_*`, `test_threewe_contract_audit` | 6 | same ignored-evidence directory |
| `test_prototype_profile` | 5 | P0-A's launcher: gitignored local config |
| `test_capture_*`, `test_clockmap` | 5 | ENV-1's premise inverted — the dev venv has `cv2`/`pyrealsense2` installed (P1-A's sanctioned install); a clean `[dev,voice]` clone has neither |
| `test_future_clock_guard` | 4 | nightly-environment sweep |
| `test_owner_store_isolation` | 2 (one of them is also its own gate row) | pre-existing at HEAD |
| **total** | **51** | |
| `test_eval_assertions` (run C only, +1 → 52) | 1 | **a GATE-0 regression**, found by this row and repaired — deviation 10; run D is green on it |

### Seeded RED — one per new guard

Each: seed the **product** file, run the selection, restore, verify sha256
identical, purge `__pycache__`, re-run green.
(`/home/jaewoo-jang/.cache/parcel-gate0/seed.py`)

| Seed | Selection | Seeded | Restored + re-run |
|---|---|---|---|
| A `run_stage` wrapper removed (straight-line list build) | `test_ci_gate.py -k "explod or json_summary or keyboard or system_exit"` | **4 failed**, 2 passed | sha `2d02c329a345` identical → **6 passed** |
| B ruff version refusal short-circuited (`if False:`) | `-k "ratchet_refuses or pyproject_pin"` | **1 failed**, 3 passed | identical → **4 passed** |
| C `pyproject` pin loosened back to `ruff>=0.12,<1` | `-k pyproject_pin` | **1 failed** | sha `73595b7f9f43` identical → **1 passed** |
| D `protocol.py` mutable default restored | `test_realtime_protocol.py -k "retained_event_defaults or python_floor"` | **2 failed** | sha `37bf81e854af` identical → **2 passed** |
| E one vendored OBJ deleted (`assets/foot.obj`) | `test_unitree_asset_pack.py test_sim.py` | **9 failed**, 31 passed | sha `df9e78a7c011` identical → **40 passed** |
| F blanket `third_party/` ignore restored in `.gitignore` | `test_unitree_asset_pack.py -k "carve or ship"` | **2 failed**, 1 passed | sha `2c56ef101b38` identical → **3 passed** |

Seed E is the one that proves the `skipif` removal was load-bearing: with the
mesh gone, three `test_sim.py` tests **FAIL** where they used to report SKIP.

The remaining seeds are permanent, in-suite, and never touch a committed file:
the synthetic-pack fixture in `tests/test_unitree_asset_pack.py` (delete /
tamper / resize / wrong revision / 4 unsafe paths / missing / unparseable /
uncompilable / no-scene / gitlink) and the containment monkeypatches in
`tests/test_ci_gate.py`. Every one has a green control beside it
(`test_the_synthetic_control_is_green`,
`test_the_clean_commit_tier_reports_exactly_the_declared_stages`) so a seed
cannot be red for the wrong reason.

### Targeted gates (project tree, `TMPDIR` unset)

```
# every owned module together, after every edit and after the repair:
.parcel/bin/python -m pytest tests/test_unitree_asset_pack.py tests/test_ci_gate.py \
  tests/test_realtime_protocol.py tests/test_held_out_scene.py tests/test_sim.py \
  tests/test_dynamic_city.py tests/test_scene_assets.py tests/test_eval_assertions.py \
  -q -m "not slow"                                                     -> 253 passed, 1 deselected

.parcel/bin/python -m pytest tests/test_unitree_asset_pack.py -q       -> 26 passed
.parcel/bin/python -m pytest tests/test_ci_gate.py -q                  -> 59 passed
.parcel/bin/python -m pytest tests/test_realtime_protocol.py -q        -> 42 passed
.parcel/bin/python -m pytest tests/test_sim.py tests/test_dynamic_city.py \
                            tests/test_scene_assets.py -q              -> 50 passed, 0 skipped
.parcel/bin/python -m pytest tests/test_held_out_scene.py \
                            tests/test_unitree_asset_pack.py -m "not slow" -q
                                                                       -> 32 passed, 1 deselected
.parcel/bin/ruff check <every owned .py> --output-format=concise       -> All checks passed!
.parcel/bin/python -m ruff check scrum/20260822/task_9/evidence/       -> All checks passed!
.parcel/bin/python scripts/ci_gate.py --help                           -> parses, 4 options
```

`scripts/ci_gate.py --tier commit` was **not** run on the project tree (the
board reserves the full commit tier for the verifier); the new stage was run in
isolation and the `--json` plumbing was exercised end to end in the clean clone.

## What this does not prove

* **Nothing is committed.** Git is read-only for executors, so the 20-file pack
  is *un-ignored and shippable* in the project tree but not yet in the index.
  The clean-clone rows were measured on a clone that was committed inside
  `~/.cache/parcel-gate0/`. **The integrator's `git add third_party/unitree_mujoco`
  is the step that makes this real**, and until it happens a fresh clone of
  `main` still dies exactly as run A did.
* **No hosted run.** `ci.yml` has never executed (Actions is off — owner action
  B20). `MUJOCO_GL: osmesa`, `libosmesa6` and `libportaudio2` are correct by
  construction and by the local osmesa-free evidence that nothing in the commit
  tier constructs a renderer; **none of it is measured on a GitHub runner.**
* **Only two interpreters were exercised.** CPython 3.14.4 (dev) and 3.12.13
  (clean clone), plus a 3.11.15 venv for the one import row. `requires-python`
  still says `>= 3.10` with no upper bound; **3.10 and 3.13 are unproven and the
  claim remains false-until-tested for them.** Narrowing that string is outside
  this card's OWNS (`pyproject.toml` *dev extra*) — carded as a handoff below.
* **The clean clone is red**, and this card does not claim otherwise. Run B's
  138 default-suite failures / 45 errors and the `owner-store-isolation` failure
  are HEAD's own clean-clone state, not GATE-0 regressions — GATE-0's claim is
  only that they are now *reported* instead of skipped by a traceback. Nobody
  has yet triaged them; that is the next card, not this one.
* **The pack is a source-checkout claim, not a wheel claim.** Nothing here
  packages the MJCF into a built distribution; `pip install parcel-robot-dog`
  from a wheel still has no Go2 assets.
* **`unitree-assets` compiles geometry.** It says the scenes are structurally
  loadable. It says nothing about physics, rendering, or whether the Go2 model
  is the right one.
* **No hardware.** Nothing in this card touched or needed a robot; see the
  owner-gated row.

## Deviations from OWNS (declared)

1. **`third_party/unitree_mujoco/.git` was renamed to `.git.upstream-clone`.**
   *Required, and outside OWNS.* Git refuses to descend into a directory holding
   a nested repository: with `.git` present, `git status -uall third_party/`
   collapsed the entire pack to a single `?? third_party/unitree_mujoco/` entry
   and `git add` would have written a **gitlink**, which IG-1 forbids. Renaming
   is a filesystem move of a 76 MB *developer* artifact that nothing in this
   repository references (grepped: no `.gitmodules`, no consumer in `scripts/`,
   `tools/`, `.github/`, or any `.py`); the directory is still ignored by the
   new carve-out, the upstream is public, and the exact revision is pinned in
   `PROVENANCE.json`. **Undo:** `mv third_party/unitree_mujoco/.git.upstream-clone third_party/unitree_mujoco/.git`
   (and re-hide the pack if that is wanted).
2. **Git writes inside the scratch clone.** `git add` / `git commit` were run in
   `/home/jaewoo-jang/.cache/parcel-gate0/stage` so that R9's "tracked-only
   clone" is literally true rather than simulated. **No git write of any kind
   touched the project tree**; `git rev-parse HEAD` is still `8862220` and no
   file was staged, stashed, checked out, reset, or restored.
3. **`tests/test_sim.py` and `tests/test_dynamic_city.py` edited** (4 lines
   removed, 8 comment lines added). The card's Work §1 requires the four
   `skipif` removals but its OWNS list omits the two files. Neither is in any
   concurrent card's OWNS (XD-1's `test_dynamic_costs` is `tests/test_dynamic_costs.py`,
   a different module). The edits are the decorator deletions and a comment
   saying why.
4. **`evaluate_ruff` / `update_ruff_baseline` edited** in `ci_gate.py`. OWNS
   names two regions of that file (the `run_commit_tier` wrapper and the new
   stage) but Work §3 requires the version refusal, whose only sane home is the
   ruff evaluator. Both edits are inside a marked `=== GATE-0 region ===` block.
   **XD-1's region (the `default-suite` runner block) is untouched** — it is now
   one line of the stage table, which should make XD-1's edit easier, not
   harder.
5. **`evaluate_unitree_assets` added to `run_nightly_tier`** (one line). The
   pre-existing `test_both_tiers_carry_the_tier_coverage_gate_and_the_commit_tier_keeps_every_hard_entry`
   asserts the nightly is a superset of the commit tier; a commit-only stage
   would have reddened it.
6. **Four extra allowlist seats in `tests/test_held_out_scene.py`**, not one.
   One is the card's (`tests/test_unitree_asset_pack.py`). The other three are
   this card's own paperwork (`README.md`, `PREREGISTRATION.md`, this file).
   `scrum/20260822/task_20/README.md` is tracked at HEAD and names the scene, so
   the nightly prose scan **was already red at HEAD before this executor opened
   a file** — the doc catch-22 `AUDIT_CHAIN_FABLE.md` names, for the fourth time.
7. **`.gitattributes` was not created.** IG-1 asks for OBJ files marked binary.
   A new root-level `.gitattributes` is not in OWNS and is one line the
   integrator can add; handed off below.
8. **`--update-ruff-baseline` was deliberately NOT run.** Six cards are editing
   this tree; regenerating would have silently absorbed their in-flight debt into
   the baseline. The stamp was added by editing the JSON, leaving the 7
   fingerprints byte-identical.
9. **`main()`'s top-level fallback serializer** (IG-1's "emit a valid
   `gate-runner` error if rendering itself fails") was **not** built. It is
   outside the two `ci_gate.py` regions this card owns and outside the card's
   Work list. Handed off.
10. **`tests/test_eval_assertions.py` repaired** (one assertion, +10/−3). Not in
    OWNS, and **a regression this card caused**: that test asserts on the literal
    string `results.append(evaluate_assertion_evals(tier=tier, k=1))` in
    `ci_gate.py`'s source, which the stage-table refactor deleted. Found by the
    clean-clone run C, not by a targeted selection — the exact reason the
    clean-clone row was pre-registered. The assertion now pins the stage-table
    form *and* the declared stage name, so EV-1's `k` is still literal on both
    sides. Every other source-literal coupling to `ci_gate.py` was then swept
    (`test_ci_gate_jerk_ratchet.py`, `test_nightly_runner.py`,
    `test_dr2_pose_drift_arm.py`, `test_eval_assertions.py`) — **116 + 70
    passed**, no other break.

## Owner-gated rows

Nothing in this card needs the owner's voice or a camera. Two rows need a
person with an account, and one needs hardware that does not exist:

| Row | Who | Exact command / action |
|---|---|---|
| **The pack becomes real** | integrator (or owner) | `git -C /home/jaewoo-jang/Desktop/Projects/Parcel add third_party/unitree_mujoco && git status --porcelain third_party \| wc -l` → expect **20** `A ` rows, zero `160000` gitlinks. Until this runs, `main` still dies as run A did. |
| **B20 — enable Actions** | **owner, admin click** | GitHub → repo → Settings → Actions → *Allow all actions*, then `gh workflow run ci --ref main -f tier=commit` and record the run URL. Everything in R8 is unexecuted until then. |
| **Physical commissioning** | **purchase-gated** | No Go2 exists (owner, authoritative 2026-08-22). The corrected snippet below cannot be executed by anyone today; it is a documentation-correctness handoff only. |

## Handoffs

### 1. The commissioning snippet in `README.md:152` and `docs/MOTION.md:374` — corrected

Both files belong to another session tonight and were **not** edited. The
documented command does not parse; measured:

```
$ .parcel/bin/python -m parcel_robot.unitree_control --vx 0.05 --duration 1 --arm
python -m parcel_robot.unitree_control: error: argument command:
  invalid choice: '0.05' (choose from observe, run, review, apply)
```

`unitree_control` is a **four-phase, two-person** commissioning tool, not a
one-liner. There is no `--vx`; the axis is `--axis {vx,vy,vyaw}` with `--speed`,
and `run` additionally requires `--operator`, `--robot-serial`, `--journal`
(fresh path, used once) and `--record-out`. Correct sequence:

````markdown
```bash
# 1. observe — read-only, claims no lease; writes the evidence `run` requires.
#    Without it the record can never authorize configuration, because nothing
#    witnessed the robot at rest.
.parcel/bin/python -m parcel_robot.unitree_control observe \
  --config configs/robot.yaml \
  --min-samples 20 --timeout 5.0 \
  --out commissioning/observe_<serial>.json

# 2. run — armed, ONE axis at a time, bounded. --speed is capped at
#    0.05 m/s (yaw 0.15625 rad/s) and --duration at 1.0 s; both default to
#    the middle of the permitted band (0.035 m/s, 0.109375 rad/s, 1.0 s).
.parcel/bin/python -m parcel_robot.unitree_control run \
  --config configs/robot.yaml \
  --operator "<your name>" \
  --robot-serial "<serial>" \
  --ack estop_operator --ack fenced_area --ack support_rig \
  --mode "<a mode the observe phase saw>" \
  --axis vx --speed 0.05 --duration 1.0 \
  --observation commissioning/observe_<serial>.json \
  --journal   commissioning/journal_<serial>_vx.jsonl \
  --record-out commissioning/record_<serial>_vx.json \
  --observed-direction vx=forward \
  --arm

# 3. review — a SECOND person; the reviewer must not be the operator.
.parcel/bin/python -m parcel_robot.unitree_control review \
  --record   commissioning/record_<serial>_vx.json \
  --reviewer "<second person>" --accept \
  --out      commissioning/record_<serial>_vx.reviewed.json

# 4. apply — print the configuration the reviewed record authorizes.
.parcel/bin/python -m parcel_robot.unitree_control apply \
  --record commissioning/record_<serial>_vx.reviewed.json \
  --config configs/robot.yaml
```
````

Surrounding prose in both files should also stop saying "limits each run to two
seconds": `DEFAULT_MAX_DURATION_S` is **1.0 s**. And both files should say
plainly that no robot exists to run this on.

### 2. Left for other cards / the integrator

| Item | Where | Why not here |
|---|---|---|
| `git add` the pack (+ optional `.gitattributes` marking `*.obj` binary) | repo root | git is read-only for executors |
| `main()`'s last-ditch `gate-runner` error serializer | `ci_gate.py` `main` | outside this card's two `ci_gate.py` regions (IG-1's item) |
| `requires-python` narrowed / the 3.10–3.14 matrix | `pyproject.toml`, `ci.yml` | OWNS is the *dev extra*; this is IG-2's scope, and 3.10/3.13 are genuinely untested |
| Triage the clean clone's 138 default-suite failures + 45 errors + `owner-store-isolation` | new card | pre-existing at HEAD; GATE-0 only made them visible |
| **The same defect, one directory over**: `evals/external/.gitignore:1` ignores `results/*` while 55 sibling files under it are tracked. A clean clone therefore lacks `evals/external/results/barn_ros2/*` and `.../habitat2020/*`, and **35 of the 51 remaining default-suite failures are that**. It wants the identical treatment: an intentional carve-out + a manifest + a stage | a follow-up card (GATE-0b) | outside OWNS; found by this card's clean-clone row |
| `CODEBASE_INDEX.md` (untracked, written 06:25 today by the docs session) names `city_block_b` and reddens the **nightly** held-out prose scan | that session | not GATE-0's file; needs a seat or a redaction |
| Two ruff fingerprints appeared mid-card in other cards' files — `src/parcel_robot/realtime/config.py::RUF009` (TURN-1's `TurnDetection` dataclass default) and `src/parcel_robot/runtime.py::F401` (ROAM-1's unused `KIND_ROAM` / `KIND_ROAM_STOP`) | TURN-1 / ROAM-1 | in-flight work, not baseline debt. **Do not re-pin the baseline to absorb them.** The clean clone measures **7, new 0** |
| `tests/test_dynamic_city.py:189`'s `skipif(not CITY_SCENE.exists())` can also never fire (the product scene is tracked) | XD-1 or a cleanup card | outside the card's "four guards" |
| `tests/test_scene_assets.py:396`'s `unitree_mujoco` escape could now be manifest-backed | a follow-up | IG-1 item, outside OWNS |

---

# Correction pass — FINISH-1 (`../task_29` §C), 2026-08-22 · Claude Opus

Seven items from `AUDIT_WEEK1_FABLE.md` §GATE-0 (verdict **ACCEPT**; all seven
minor or doc). The card was accepted before this pass and nothing here changes
a verdict; what changes is one test that could redden somebody else's run, one
handoff that was mis-sized, two counts, a key, an annotation and a seat.

## C1 — the carve-out probe no longer writes into the real pack

`tests/test_unitree_asset_pack.py::test_an_unmanifested_file_smuggled_through_the_carve_out_reddens`
used to write a probe `.obj` **into**
`third_party/unitree_mujoco/unitree_robots/go2/assets/` and remove it in a
`finally`. Two hazards, both reproduced by the verifier: at one-worker-per-test
xdist any concurrent test that evaluates the pack sees the probe and reddens for
a defect that is not there (`-n 26`, `-n auto`), and a SIGKILL between the write
and the `finally` leaves a stray in a vendored directory that every later run
blames on the pack.

**Redesigned exactly as the card asked — through the gitlink seed's pattern.**
The closure check is a set comparison (`shipped - expected`) and never opens the
extra path, so the seed does not need the file to exist: `_git_paths` is
monkeypatched so the `--others` call reports one additional path, and everything
else is the product's. **Nothing is written anywhere.**

The premise the old write really did prove — that `.gitignore`'s carve-out would
ship a stray `.obj` — is not dropped. It moved into a new test,
`test_the_gitignore_carve_out_really_would_ship_a_stray_obj`, which copies the
repository's own `.gitignore` into a throwaway `git init` under `tmp_path`,
drops `_stray.obj` and `_stray.txt` beside the meshes, and asks **real git**:
the `.obj` is listed by `ls-files --others --exclude-standard`, the `.txt` is
not. The real pack is never touched and nothing is ever staged.

```
$ unset TMPDIR
$ .parcel/bin/python -m pytest -q tests/test_unitree_asset_pack.py       -> 27 passed
$ .parcel/bin/python -m pytest -q tests/test_unitree_asset_pack.py -n 26 -> 27 passed
$ (three consecutive runs) -n auto                                       -> 27 passed ×3
```

**Seeded RED (C1):** `extra = sorted(shipped - expected)` replaced by
`extra = []` in `evaluate_unitree_assets` → **1 failed** (the redesigned test),
26 passed; `scripts/ci_gate.py` sha256 `b73ccf1feb65dcdc…` identical after,
`__pycache__` purged, **27 passed** restored.
(`../task_29/evidence/seed_gate0.sh`, transcript `seeds_gate0_air1.txt`.)

## C2 — the 51-failure table and the GATE-0b handoff, honestly

**Provenance first: the two count corrections are the verifier's re-count of
the same clean-clone run (`AUDIT_WEEK1_FABLE.md` §GATE-0), not a re-measurement
by this pass.** No clean clone was built here — that is the verifier's
instrument — and inventing a second number for the same run would be worse than
quoting theirs.

| Family | n (corrected) | was | Cause |
|---|---|---|---|
| `test_barn_*` | 29 | 29 | `evals/external/.gitignore:1` ignores `results/*` while 55 sibling files are tracked |
| `test_habitat2020_*`, `test_threewe_contract_audit` | 6 | 6 | the same ignored-evidence directory |
| `test_prototype_profile` | 5 | 5 | P0-A's launcher: gitignored local config |
| `test_capture_*`, `test_clockmap` | **6** | 5 | ENV-1's premise inverted: the dev venv has `cv2`/`pyrealsense2`, a clean `[dev,voice]` clone has neither |
| `test_future_clock_guard` | 4 | 4 | nightly-environment sweep |
| `test_owner_store_isolation` | **1** | 2 | pre-existing at HEAD; it is also its own gate row, which is how it got counted twice |
| **total** | **51** | 51 | |

**The GATE-0b handoff, re-sized.** The old sentence — "`results/*` is the same
defect one directory over, un-ignore it and ~35 failures go away" — is wrong by
a factor of seven. What the 35 `test_barn_*`/`test_habitat*` failures actually
need, checked against this tree:

* **~5** are explained by `results/*` being ignored while siblings are tracked
  (`evals/external/.gitignore:1`) — the Unitree-shaped defect, and the only part
  a carve-out fixes;
* **~17** need `.cache/external-evals/runtime/barn-parcel-bundles`, which is
  under the root `.gitignore:12` (`.cache/external-evals/`) and is *generated*
  by `evals/external/barn_v8_policy_bundle.py`, `barn_v9_policy_bundle.py` and
  `barn_profile_candidate_bundle.py` — verified on this tree: all three name
  that path as `DEFAULT_DESTINATION_ROOT`. **Vendoring it is 21 GB and is not
  an option;**
* **~7** fail a premise no carve-out can fix: the V9 training manifest's
  mode-bit check. `evals/external/training/barn_sampled_predictive_tracker_v9/split.json`
  is **tracked `100644`**, is **`444` in this dev tree**, and git checks out
  `664` in every clone. A mode bit that differs between the index, the dev tree
  and every clone is a check about the developer's umask, not about the data;
* **3** are habitat provenance;
* **1** is a BARN generator checkout;
* **1** sits under a *third* ignore file,
  `evals/external/development/barn_frontier_detour_v4/results/.gitignore`
  (contents: `runs/`) — verified present on this tree.

**Recommendation to GATE-0b, in the prototype spirit (ask, don't refuse):**
skip-with-reason or a nightly selection for the ~25 that need a generated or
external root — a test that cannot run without 21 GB of generated bundles should
say "this needs `barn_v9_policy_bundle.py` to have been run" and skip, not fail
— and a **decision** on the V9 mode-bit check: either stop asserting a mode bit,
or assert the one git actually reproduces. Neither is a carve-out.

## C3 — seeds E and F, re-measured POST-INTEGRATION

The counts in the seed table above were taken while the pack was still
untracked. Re-run on the final tree, with the pack un-ignored and present
(`../task_29/evidence/seed_EF.sh`):

| seed | mutation | seeded | restored |
|---|---|---|---|
| **E** | `assets/foot.obj` deleted | **9 failed, 32 passed** | 41 passed |
| **F** | the blanket `third_party/` ignore restored in `.gitignore` | **3 failed, 1 passed**, 23 deselected | 4 passed |

sha256 identical after both (`foot.obj` `df9e78a7c011…`, `.gitignore`
`2c56ef101b38…`).

**These are not the 8/32 and 1/2 the card projected, and the difference is this
card's own doing.** C1 added a test to `tests/test_unitree_asset_pack.py` (26 →
27), and both new tests are selected by seed F's `-k "carve or ship"`. Seed E's
nine, named: `test_the_pack_is_green_on_this_tree`,
`test_git_would_ship_the_pack_and_nothing_else_under_third_party`,
`test_each_product_scene_compiles_from_the_tracked_pack[city_block.xml]`,
`[city_block_b.xml]`, `test_an_unmanifested_file_smuggled_through_the_carve_out_reddens`,
`test_the_developer_checkout_is_not_what_ships`, and **three in `test_sim.py`**
(`test_bind_actuators_uses_joint_names`, `test_pose_controller_moves_toward_targets`,
`test_expression_overlay_is_additive_and_never_disturbs_targets`) — which is the
row that proves the `skipif` removal was load-bearing: with the mesh gone those
three FAIL where they used to report SKIP.

**`git ls-files --deleted` is now in the ship test** (the card's optional half).
`test_git_would_ship_the_pack_and_nothing_else_under_third_party` asserts that
nothing under `third_party/` is in the index and missing from the working tree.
It is empty today — the pack is not staged yet, git is read-only for executors —
and becomes load-bearing the moment the integrator's `git add` lands, because a
tracked-then-deleted mesh is exactly seed E and `ls-files` alone still reports
it as present.

## C4 — `ruff_version_stamped_at` dropped

`scripts/ci_ruff_baseline.json` carried a hand-written `ruff_version_stamped_at`
that `update_ruff_baseline()` does not emit, so the next
`--update-ruff-baseline` would silently delete it. Dropped, because
`generated_at` already records when the file was written and one timestamp is
enough. The file now holds exactly the keys the regenerator writes — `count`,
`fingerprints`, `generated_at`, `note`, `ruff_version` — in the same
`sort_keys=True` order, and the ratchet is unchanged: **7 fingerprints,
0 new**, re-derived through `ci_gate._ruff_fingerprints()` on the final tree.

## C5 — run B's `[FAIL] ruff` is an A/B artefact

Annotated where it appears above and repeated here so it is not read as a
finding: in **run B** the pack was hidden by moving it aside in a tree whose
`.gitignore` had already been re-cut, which changes what `ruff check .`
traverses. The FAIL is a property of that A/B construction, not of the tree
GATE-0 delivers — runs C and D, on the same code with the pack present, report
`ruff 0.16.1: 7 violation(s), baseline 7, new 0`.

**And the hosted job (B20) will be RED, for reasons that predate this card.**
The 51 clean-clone failures above are all in the default suite, so the GitHub
Actions run the owner clicks will end red whatever this card does; and its
**20-minute timeout is at risk** — the local clean-clone commit tier took
307.6 s with a warm venv and no network, while the hosted job additionally
resolves and installs `[dev,voice]`. Read the JSON, not the badge: the row this
card claims is "ten named stages, valid JSON, no traceback", and that is what
B20 should be scored on.

## C6 — the seat for `CODEBASE_INDEX.md`

The nightly held-out prose scan was red on the generated repo index — it lists
every tracked path, and one of those paths is the held-out scene's. Seated in
`tests/test_held_out_scene.py`'s `ALLOWED` with the card's reason ("generated
file index; lists paths only, never scene content; regenerated per commit by
`tools/codebase_index.py`"), plus the specifics: the single mention is one line
of a directory census (``src/parcel_robot/scenes/ — 2 .xml (city_block.xml;
city_block_b.xml)``), which is the scene's **name** and not one pixel, geometry
row or label of it.

**One seat, grown deliberately.** `tools/codebase_index.py` does **not** name
the scene (it globs), so it gets no seat; the entry does **not** join
`LOAD_ALLOWED`, because an index never opens what it lists.

**One small change to the scan itself, declared:** the staleness half now skips
allowlist entries whose file is not present in the checkout. Without it, a tree
that has not run `tools/codebase_index.py` would fail this test with "stale
allowlist entry" — turning "the index has not been generated yet" into a red
build about the held-out scene. A file that does not exist cannot mention the
scene, so nothing is weakened.

```
$ .parcel/bin/python -m pytest -q tests/test_held_out_scene.py  -> 7 passed   (was 1 failed, 6 passed)
```

**Seeded RED (C6):** the `CODEBASE_INDEX.md` entry deleted from `ALLOWED` →
`test_only_the_allowlist_names_the_held_out_scene` **fails** naming
`['CODEBASE_INDEX.md']`; restored byte-identically (sha256
`3b40324427d23da1…`) → 7 passed.

## C7 — the exploding-evaluator test now asserts its own name

`test_one_exploding_evaluator_costs_exactly_one_row` asserted only that *some*
row errored, so "exactly one row" was in its name and nowhere in its body. It
now asserts the count, per victim, from a written-down table:
`evaluate_ruff` → 1, `evaluate_hard_safety` → 1, `_pytest_gate` → **4**
(it is the shared helper behind `model-off-non-inferiority`,
`release-parity-integrity`, `owner-store-isolation` and `default-suite`; the
number is a literal on purpose, so a fifth pytest stage reddens this test).

**Seeded RED (C7), and it is worth reading twice.** The seed is a copy-paste
defect of the kind this guards: the `hard-safety` stage re-pointed at
`evaluate_ruff` in `run_commit_tier`. With the new assertion, all three
parametrisations fail. **With the assertion seeded out as well — i.e. the test
exactly as it was — the `evaluate_ruff` arm PASSES**, because two error rows
still satisfy "some row errored". Measured both ways; `scripts/ci_gate.py` and
`tests/test_ci_gate.py` restored byte-identically.

## Gates after this pass

```
$ unset TMPDIR
$ .parcel/bin/python -m pytest -q tests/test_unitree_asset_pack.py   -> 27 passed
$ .parcel/bin/python -m pytest -q tests/test_ci_gate.py              -> 59 passed
$ .parcel/bin/python -m pytest -q tests/test_held_out_scene.py       -> 7 passed
$ .parcel/bin/ruff check tests/test_unitree_asset_pack.py tests/test_ci_gate.py \
      tests/test_held_out_scene.py scripts/ci_gate.py                -> All checks passed!
$ ruff ratchet, tree-wide, via ci_gate._ruff_fingerprints()          -> 7 current, 0 new
```

`scripts/ci_gate.py --tier commit` was **not** run: the board reserves the full
gate for the verifier, and that has not changed.
