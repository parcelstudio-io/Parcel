# FINISH-1 — the week-1 close · STATUS

**Card:** `README.md` · **Board:** `../TASK_BOARD.md` · **Evidence:**
`../AUDIT_WEEK1_FABLE.md` · **Executor:** Claude Opus · **Verifier:** Fable
**Date:** 2026-08-22 · **Baseline:** `8862220` + the uncommitted week-1 tree
**Pre-registration:** `PREREGISTRATION.md`, sha256
`d7511531dcb05c230a247370cb945908134c2ea823f08ea39e6201cee4660838`, written
`2026-08-22T12:08:50-04:00` — before the first measurement.
**Scratch:** `/home/jaewoo-jang/.cache/parcel-finish1/` (sims on
`parcel-roam1-<pid>.sock` under it; never the owner's `/tmp/parcel_sim.sock`,
never `:8765`). **Hosted spend: $0.00.** No audio was played on the XVF3800 and
no control byte was written to it. The owner's `parcel_memory.sqlite3` was never
opened (it does not exist on this host; every run records
`owner_store.unchanged: true`).

---

## Headline

**COMPLETE — five sections, one declared miss inside a delivered item.**
The purchase number the Go2 decision reads is now a number about the scene the
robot was in: **6.540 / 6.475 / 6.559 m in-block, three consecutive 120 s
tethered runs, 0 contacts, `in_bounds: true` 3/3.** CURIO-1's §9.7 is complete
(the seed-777 run was never missing — its *score* was). GATE-0's six-item pass
is done, including a probe test that no longer writes into the vendored pack and
a seat for `CODEBASE_INDEX.md`. MARK-1's two doc claims are corrected as they
are, not as they were wished. AIR-1's `interrupt_p50_s` reads MARK-1's
`interrupted_at` and the row is half measured — the honest half is stated in
both directions.

**The declared miss, up front:** the ROAM-1 stop/tick race guard has **no seed
that reddens on either half alone**. Seeding the lock: green. Seeding the
post-check: green. Seeding both: red. The guard is a pair, neither half is
independently covered, and that is a real gap, named (§A3).

---

## Per card

### A. ROAM-1 (`../task_23`) — DONE (1 miss declared)

| item | state |
|---|---|
| 1 · three tethered runs + the in-bounds qualifier + its seed | **done** |
| 2 · restate the purchase number (headline, R2b, PO-1 handoff) | **done** |
| 3 · race fix + seed | code was already in; **seed MISSED on either half alone**, red only on both — declared |
| 4 · declare the ledger write | **done** (ROAM1 §6 of the correction pass) |
| 5 · doc hygiene (5 sub-items) | **done**, one of them "nothing to remove" with the check shown |
| 6 · append the Correction pass section | **done** |

**THE GO2-PURCHASE INPUT, reported plainly, in this block.**

> Three consecutive 120 s `--static-city` runs through the product runner
> (`submit_realtime_transcript("Go explore.")`, watched via `snapshot()`), with
> the tether ON at **10.0 m** — the value `patrol.limits_from_safety` sets from
> `DEFAULT_ROAM_TETHER_M`, which is also what `configs/robot.prototype.yaml`
> carries:
>
> | run | path (m) | net raw (m) | **net IN-BLOCK (m)** | in-bounds | contacts | min person clearance (m) |
> |---|---|---|---|---|---|---|
> | 1 | 26.137395 | 6.540060 | **6.540060** | **true** | 0 | 1.156364 |
> | 2 | 26.133556 | 6.474798 | **6.474798** | **true** | 0 | 1.164318 |
> | 3 | 25.990399 | 6.558471 | **6.558471** | **true** | 0 | 1.127456 |
>
> **In-bounds qualifier:** net displacement counted only while |x|,|y| ≤ 12 m
> (half of the 24 × 24 m road plane `city_block` renders). All three runs never
> left it, so the raw and in-block numbers are identical — which is what
> "in-bounds" buys: on a run that stays inside it costs nothing.
>
> **The number this replaces:** two in-block runs ≥ 1.0 m (3.37, 2.05) plus one
> run that exited the scene (20.67 raw; **12.02** at the last in-plane sample;
> 138 of 479 samples outside; left at t = 85.44 s).
>
> **The tether fired** on every run: `turn_tether` is the policy's reason on
> 10–11 samples per run and the furthest each run reached on the y axis is
> 10.01 / 9.97 / 9.96 m. Untethered spread over three runs: 2.05 → 20.67 m.
> Tethered: 6.475 → 6.559 m.
>
> **What it is not.** A wander with a leash, not an explorer: no coverage
> objective, no frontier, no memory of where it has been. And no robot — no
> Go2, no D455, no Orin exist on this host; every number is MuJoCo through a
> sim socket.

Exact command (all three runs, one per line in
`evidence/three_runs.sh`, stdout in `evidence/three_runs_stdout.txt`):

```
unset TMPDIR
.parcel/bin/python scrum/20260822/task_23/evidence/run_roam1.py \
    --budget 120 --static-city --person-stop 0.7 \
    --socket-dir /home/jaewoo-jang/.cache/parcel-finish1 \
    --out scrum/20260822/task_23/evidence/roam_static_tethered_<n>
```

Every pre-registered row met: T1 path ≥ 5.0 m **3/3**, T2 in-block net ≥ 1.0 m
**3/3**, T3 contacts 0 **3/3**, T4 clearance ≥ 0.7 m **3/3**, T5 `in_bounds`
**3/3**. No row was re-cut after measuring and every run that started is
reported.

### B. CURIO-1 (`../task_24`) — DONE

`shippedB` (seed 777, `--shipped`) **had completed at 11:31:48Z**; its
`summary.json` was on disk the whole time. What was missing was the score. Same
scorer, nothing re-simulated:

```
$ unset TMPDIR; .parcel/bin/python ~/.cache/parcel-curio1/score_curio1.py \
      ~/.cache/parcel-curio1/shippedB_20260822T112946Z/summary.json
```

| §9.7 row | bound | `shippedA` | **`shippedB`** | verdict |
|---|---|---|---|---|
| 1′ remarks in 120 s, shipped cadence | 3 ≤ n ≤ 6 | 3 | **3** | MET |
| 1i idle-chatter remarks | 0 | 0 | **0** | MET |
| 2′ hallucinated places | 0 (HARD) | 0 | **0** | MET |
| 3′ remarks while the owner is owed | 0 | 0 | **0** | MET |
| 4′ worst rolling 60 s vs cap 6 | ≤ 6 | 2 | **2** | MET |
| 5′ hosted spend | $0.00 | $0.00 | **$0.00** | MET |

**No row missed.** Skips `stimulus_gap_holding 81 · lane_busy 30 · gap_holding 2`
over 116 ticks (A: 82 / 29 / 2 over 116). The scorer was run on `shippedA`
first as a control and reproduced the column already in the doc exactly.

`_curiosity_activity_busy` (`runtime.py:13179`) reads
`roam_idle_checkpoint()` — re-read on the final tree.
`tests/test_curio1_chatter.py` **60 passed**, ruff clean on OWNS.
**`SEEDED_RED.json` refreshed** because two watched files had moved
(`whisperer.py` `4cee9fac…`→`d8dcf475…`, `runtime.py` `0e648f02…`→`0ba366ae…`):
all ten seeds reproduce with identical RED counts, baseline 60 passed,
`"tree_unchanged": true` → `evidence/curio1_SEEDED_RED_refreshed.json`.

### C. GATE-0 (`../task_20`) — DONE (all seven)

1. **The carve-out probe no longer writes into the real pack.** Redesigned
   through a monkeypatched `_git_paths` (the gitlink seed's pattern); the
   premise moved to a new test that asks real git inside a throwaway
   `git init` under `tmp_path`. **27 passed** serially, at `-n 26`, and at
   `-n auto` three times running.
2. **The 51-failure table** corrected (capture/clockmap **6**, owner-store
   **1**) and the GATE-0b handoff re-sized: ~5 explained by `results/*`, ~17
   need the generated `.cache/external-evals/runtime/barn-parcel-bundles`
   (root `.gitignore:12`; three bundle scripts name it — verified), ~7 fail the
   V9 mode-bit premise (`split.json` tracked `100644`, `444` here, `664` in
   every clone — verified), 3 habitat provenance, 1 generator checkout, 1 under
   `evals/external/development/barn_frontier_detour_v4/results/.gitignore`
   (verified present, contents `runs/`). Recommendation: skip-with-reason or a
   nightly selection for the ~25, and a decision on the mode-bit check. **The
   two count corrections are the verifier's re-count, quoted with provenance —
   no clean clone was built by this card.**
3. **Seeds E/F re-measured post-integration: E 9 failed / 32 passed, F 3 failed
   / 1 passed** (not the projected 8/32 and 1/2 — C1 added a test to that file
   and both new tests are selected by F's `-k`). All nine of E's failures are
   named in the doc, including the three in `test_sim.py` that prove the
   `skipif` removal was load-bearing. `git ls-files --deleted` added to the ship
   test.
4. **`ruff_version_stamped_at` dropped** from `scripts/ci_ruff_baseline.json`;
   the file now holds exactly the keys `update_ruff_baseline()` emits.
5. **Run B's `[FAIL] ruff` annotated** as an A/B artefact, with the B20 warning
   (hosted job red for the pre-existing 51; the 20-minute timeout is at risk
   against a local 307.6 s tier plus a hosted install).
6. **`CODEBASE_INDEX.md` seated** in `tests/test_held_out_scene.py` with the
   card's reason. One seat: `tools/codebase_index.py` does not name the scene
   and gets none; the entry does not join `LOAD_ALLOWED`. The nightly scan goes
   **1 failed, 6 passed → 7 passed**.
7. **`test_one_exploding_evaluator_costs_exactly_one_row` asserts its count**
   per victim (1 / 1 / 4).

### D. MARK-1 (`../task_22`) — DONE (docs only; code was ACCEPTED)

1. **The "unknown ⇒ falls through to the floor" claim was false and is now
   described as it is**, in `MARK1_STATUS.md` §2 **and** in `lane.py`'s
   `_response_was_cancelled` docstring: the branch is only entered after the
   reply has ended and the hold is dropped *before* the status is consulted, so
   unknown / missing / mis-shaped / `incomplete` all settle exactly like
   `completed` — survived backchannel, no `sink.interrupt()`, no truncate.
   **Kept, not changed** (the alternative is a new fail-closed path in a
   prototype wave), with the residual named: a provider that cancels under a
   different status word would read as having finished. → DUPLEX-1.
2. **The `+73 / −0` credit to TURN-1 in `lane.py` is wrong.** Re-attributed
   from `git diff -U0 8862220` (522 added lines in 29 hunks): TURN-1-only hunks
   sum to **151**; a line-level pass carrying the last marker forward gives
   **187**; three hunks are genuinely shared (above all the `+189` barge-in-hold
   block, MARK-1's region citing TURN-1's rows). The table now reads
   **151–187** and names the method.
3. The cross-card seam is section E.

### E. AIR-1 (`../task_25`) — DONE (§E1; §E2 is the verifier's)

`tools/bargein_through_air.py` reads `interrupted_at` (+ `interrupted_byte` /
`interrupted_t_s`) off the R17 index and pairs it with an onset. Module
docstring, `score_interrupt_latency`'s docstring, the row's `unmeasured_reason`
and the pinned test all updated; `AIR1_STATUS.md`'s MARK-1-STAMP handoff marked
**CLOSED**.

**The honest half.** The interrupt instant is *stamped*; the onset instant is
*estimated* from the tee's owner-burst boundary (first mic frame after
`owner_gap_s`), because `input_audio_buffer.speech_started` is still not a
retained type. A median built on it is a **bound**, and the scorecard says so
(`sources.latency.onset_is_an_estimate` + a CLI NOTE). It is deliberately not
in the row's `mechanism`: `verify_scorecard` refuses a mechanism on a
non-failing row. **TURN-1-ONSET stands as the one remaining half.**

---

## Seeded RED — every new or changed guard

Protocol throughout: seed, run, watch it fail, restore, **verify sha256 equals
the pre-seed sha256**, purge every `__pycache__`, re-run green. Drivers and
verbatim transcripts in `evidence/`.

| # | seed (product mutation) | seeded | restored | file sha256 |
|---|---|---|---|---|
| **A · S9a** | `limits_from_safety` stops passing `tether_m` | 2 failed, 54 passed | 56 passed | `mission.py 0e962c7b…` ✓ |
| **A · S9b** | the `_tether_blocks` branch removed from the policy ladder | 1 failed, 55 passed | 56 passed | `mission.py 0e962c7b…` ✓ |
| **A · S8** | `"roam"` removed from `OVERLAY_INTRODUCIBLE_KEYS` | 2 failed, 54 passed | 56 passed | `config.py 3f41bbbe…` ✓ |
| **A · S7a** | the `_command_lock` dropped around the tick's submit | **56 passed (GREEN)** | — | `runtime.py 0ba366ae…` ✓ |
| **A · S7b** | the post-check `is not policy → cancel` removed | **56 passed (GREEN)** | — | `runtime.py 0ba366ae…` ✓ |
| **A · S7c** | both halves | 1 failed, 55 passed | 56 passed | `runtime.py 0ba366ae…` ✓ |
| **A · qualifier** | the six stored traces replayed through `in_block_metrics` | the 20.67 m run flagged `in_bounds: false`, 138 samples out, exit at 85.44 s, in-block 12.015434 | the other five `in_bounds: true` | replay JSON in `task_23/evidence` |
| **B** | ten CURIO-1 seeds re-run on the final tree | 1/2/1/1/4/2/1/3/1/11 RED, identical to §9.10 | baseline 60 passed | `"tree_unchanged": true` |
| **C1** | `extra = sorted(shipped - expected)` → `extra = []` | 1 failed, 26 passed | 27 passed | `ci_gate.py b73ccf1f…` ✓ |
| **C6** | the `CODEBASE_INDEX.md` seat deleted from `ALLOWED` | 1 failed, 6 passed | 7 passed | `test_held_out_scene.py 3b403244…` ✓ |
| **C7** | `hard-safety` re-pointed at `evaluate_ruff` in `run_commit_tier` | 3 failed | 3 passed | `ci_gate.py b73ccf1f…` ✓ |
| **C7′** | the same, with the new count assertion ALSO seeded out | **the `evaluate_ruff` arm passes** — the old body could not see it | both files restored ✓ | |
| **C3 · E** | `assets/foot.obj` deleted (post-integration) | 9 failed, 32 passed | 41 passed | `foot.obj df9e78a7…` ✓ |
| **C3 · F** | the blanket `third_party/` ignore restored | 3 failed, 1 passed | 4 passed | `.gitignore 2c56ef10…` ✓ |
| **E1** | `capture_latency_events` stops reading `interrupted_at` | 1 failed, 39 passed | 40 passed | `bargein_through_air.py cd8edb3e…` ✓ |
| **E1′** | the field stripped from the index instead | `p50_s None`, row `unmeasured`, card still valid | — | in-suite |

---

## Gates (`TMPDIR` unset, `.parcel/bin/python`, `.parcel/bin/ruff 0.16.1`)

```
$ pytest -q tests/test_air1_scorecard.py tests/test_air1_rate_pin.py \
    tests/test_air1_mux.py tests/test_air1_streams.py \
    tests/test_mark1_barge_in_mark.py tests/test_mark1_browser_ear.py \
    tests/test_realtime_lane.py tests/test_realtime_audio_gateway.py \
    tests/test_turn1_endpointing.py            -> 299 passed, 1 skipped

$ pytest -q tests/test_unitree_asset_pack.py tests/test_ci_gate.py \
    tests/test_held_out_scene.py tests/test_sim.py tests/test_dynamic_city.py \
    tests/test_scene_assets.py tests/test_realtime_protocol.py \
    tests/test_eval_assertions.py              -> 255 passed

$ pytest -q tests/test_roam1_behavior.py tests/test_move1_patrol.py \
    tests/test_curio1_chatter.py tests/test_prototype_profile.py \
    tests/test_realtime_ingress.py tests/test_realtime_tool_broker.py \
    tests/test_realtime_completion_tense.py \
    tests/test_realtime_system_initiated_motion.py \
    tests/test_p0b_companion_unlocks.py tests/test_r24_lock_discipline.py
                                               -> 613 passed

$ pytest -q tests/test_unitree_asset_pack.py -n 26                 -> 27 passed
$ pytest -q tests/test_unitree_asset_pack.py -n auto  (×3)         -> 27 passed ×3

$ .parcel/bin/ruff check .                     -> the same 12 findings as before
$ ci_gate._ruff_fingerprints() vs the baseline -> current 7, baseline 7, NEW []
```

**1 167 targeted tests green** across the three sweeps. `scripts/ci_gate.py`
was **not** run — the board reserves the full gate for the verifier.

---

## Files this card changed

| file | what |
|---|---|
| `scrum/20260822/task_23/evidence/run_roam1.py` | `in_block_metrics()` + the qualifier in the payload/headline + `--socket-dir` |
| `src/parcel_robot/realtime/lane.py` | one docstring (`_response_was_cancelled`), no behaviour |
| `tools/bargein_through_air.py` | `capture_latency_events`, the two capture kinds, de-dup, provenance fields, the row's reason, module docstring, CLI note |
| `tests/test_air1_scorecard.py` | pinned text updated; 4 new tests + a product-tee session helper |
| `tests/test_unitree_asset_pack.py` | probe test redesigned; new real-git carve-out test; `--deleted` in the ship test |
| `tests/test_held_out_scene.py` | the `CODEBASE_INDEX.md` seat; staleness skips absent files |
| `tests/test_ci_gate.py` | per-victim row-count assertion |
| `scripts/ci_ruff_baseline.json` | `ruff_version_stamped_at` dropped |
| `ROAM1_STATUS.md` · `CURIO1_STATUS.md` · `GATE0_STATUS.md` · `MARK1_STATUS.md` · `AIR1_STATUS.md` | the correction-pass sections and the corrections above |
| `task_29/PREREGISTRATION.md`, `task_29/FINISH1_STATUS.md`, `task_29/evidence/*`, `task_23/evidence/*` | new paperwork and evidence |

**Untouched, as required:** `reactive_safety`, `core/hard_stop`, `docs/`,
`backlog/`, `README.md`, `scrum/20260821/`, the venv, `pyproject.toml`, the
owner's store, the owner's stack on `:8765` / `/tmp/parcel_sim.sock`. Git was
read-only: no `add`, `commit`, `stash`, `checkout`, `reset` or `restore` — every
seed restore was a byte copy from the scratch directory, verified by sha256.

---

## Deviations (declared)

1. **`tests/test_held_out_scene.py`'s staleness half now skips entries whose
   file is absent from the checkout** (§C6). Needed by the seat itself: a tree
   that has not generated `CODEBASE_INDEX.md` would otherwise fail this test
   with "stale allowlist entry". A file that does not exist cannot mention the
   scene, so nothing is weakened — but it is a change to a W-1 guard and it is
   named here rather than left in a diff.
2. **`src/parcel_robot/realtime/lane.py` is MARK-1's file and this card edited a
   docstring in it** (§D1). Inherited OWNS, no behaviour, re-read immediately
   before the edit; 299 realtime tests green after.
3. **The seed driver from ROAM-1's first pass is stored as
   `seed_roam1_driver.py.txt`, not `.py`** — it carries three ruff findings and
   the ratchet is pinned at exactly 7 fingerprints tree-wide. Byte-identical to
   what ran.
4. **The GATE-0b count corrections are quoted from the verifier's re-count**,
   not re-measured (§C2). No clean clone was built by this card.
5. **`../task_23/evidence/` gained files** (three run directories, the qualifier
   replay, two seed records) — task_23's OWNS, inherited.

---

## What this card does not prove

* **Nothing on a robot.** No Go2, no D455, no Orin. Every roam number is MuJoCo
  through a sim socket, and the tethered runs say the dog wanders 6.5 m from
  home without hitting anything — not that it explores, and not that any of it
  survives contact with a real floor.
* **No live provider session, no owner session, no acoustics.** AIR-1's seven
  measurement rows remain owner-gated; the `interrupt_p50_s` plumbing is proved
  against a capture the test wrote, not against a room.
* **The clean-clone numbers are the verifier's**, including the 51-failure
  split this card re-sized.
* **The stop/tick race guard is covered only as a pair** (§A3). A future edit
  that removes either half alone passes the suite.
* **`scripts/ci_gate.py` has not been run on this tree by an executor**, so
  "the gate is green" is still the verifier's sentence to say.

---

## What the verifier must look at first

1. **§A1, the three tethered runs** — the tether value (10.0 m via
   `DEFAULT_ROAM_TETHER_M`, harness config carries no `roam:` section), the
   pre-registration timestamp against the run directories' mtimes, and whether
   `in_block_metrics`'s "last sample before the FIRST exit" is the definition
   you wanted. The replay of the six stored traces is the cheapest check:
   `task_23/evidence/in_bounds_qualifier_replay.json`.
2. **§A3, the race seed that only reddens as a pair** — the declared miss. If
   you want each half covered, it is two tests, and DUPLEX-1 is next in that
   code.
3. **§C1's redesign** — the monkeypatched `--others` set is a *fake* listing of
   a file that never exists; satisfy yourself the closure check really is a set
   comparison (it is: `extra = sorted(shipped - expected)`, never opened), and
   that the new real-git test carries the premise the old write proved.
4. **§C6's two changes to `tests/test_held_out_scene.py`** — one seat, and the
   staleness clause (deviation 1). The seat file is GATE-0's this wave and the
   scan is a W-1 guard.
5. **§E's onset estimate** — the load-bearing judgement of this card. The
   interrupt half is a real stamp; the onset half is the tee's owner-burst
   boundary and the median is a bound. If you would rather the row stayed
   `unmeasured` until `speech_started` is retained, that is a one-line revert of
   `CAPTURE_ONSET_KIND` from `ONSET_KINDS` and the seam still closes
   MARK-1-STAMP.
6. **§D1** — whether "describe it as it is" was the right call over changing the
   behaviour, since the residual is a real (if schema-shaped) way for the D-2
   failure to return.
