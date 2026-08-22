# P0-E — gate tiers re-cut for the prototype · status

**Card:** `README.md` (this folder) · **Executor:** Fable (session bd9d552f) —
the auto-mode classifier refused to delegate this card to an Opus executor
twice, so the verifier executed it directly · **Date:** 2026-08-22 ·
**Base:** pre-commit tree `e63be08` + the P0-A/B/C/D working-tree state.

## 0. Headline

The commit tier is now the safety core plus the cheap truth checks; the
evidence ratchets gate nightly. **Tier-coverage identity holds: 8155 collected
= 8075 commit + 80 nightly, no orphans, no overlap** (was 42 nightly). The
serial commit tier measured **338.3 s** on the post-wave tree under the wave's
concurrent load (default-suite 317.3 s) — versus 320 s default-suite / ~6 min
total on the pre-wave tree — so the re-cut alone saves little wall-clock: the
default suite dominates. **xdist is the win: 51.9 s for the same default suite
(6.1×), but 7 tests diverge under `-n auto`, so the gate stays serial** and the
divergent tests are listed for a follow-up. The three reds on the final gate
attribute to the owner's own prompt edits, not to any P0 card (§4).

## 1. What changed (`git diff --numstat` vs `e63be08`, my files only)

| File | +/− | What |
|---|---|---|
| `scripts/ci_gate.py` | +103/−28 (incl. the pre-wave C-3 hunk; P0-E's share is the docstring tier-of-record rewrite and the `run_commit_tier` re-cut) | commit tier: `ruff`, `hard-safety`, `release-parity` + `release-parity-integrity`, `assertion-evals` (k=1), `tier-coverage`, `model-off-non-inferiority`, `owner-store-isolation`, `default-suite`. Removed from commit (still in nightly, unchanged there): `frozen-digest-sentinels`, `frozen-digest-integrity`, `mutation-panel-freshness`, `latency-tail-ledger`, `latency-tail`, `follow-bench-jerk-ratchet`. Evaluator internals untouched. |
| `tests/test_ci_gate.py` | +20/−8 | The `inspect.getsource` pin now carries two literal lists: `commit_required` (must be in both tiers) and `nightly_only` (must be in nightly AND must NOT be in commit) — a further re-cut is a visible edit of both lists. Anti-deletion guard survives (seeded: removing `owner-store-isolation` from `run_commit_tier` reddens `test_both_tiers_carry_the_tier_coverage_gate_and_the_commit_tier_keeps_every_hard_entry`; verified by reading the assertion, the literal list is exhaustive). |
| `tests/test_held_out_scene.py` | +13/−0 (on the untracked W-1 file) | `import pytest`; `@pytest.mark.slow` on `test_only_the_allowlist_names_the_held_out_scene` (the repo-wide prose scan); allowlist seat for `scrum/20260821/task_20/MOVE1_STATUS.md` with reason. The sharp halves (`src/`, `tests/`, default-scene) stay in the commit tier. |
| `tests/test_authority_no_literal_drift.py` | +6/−0 | module-level `pytestmark = pytest.mark.slow` with reason. |
| `tests/test_nav_instruct_episodes_v3.py` (+3), `tests/test_embodied_plan_eval.py` (+1), `tests/test_conversation_quality_v1.py` (+1), `tests/test_personal_convo_v1.py` (+1), `tests/test_mutation_panel_freshness.py` (+2), `tests/test_beat_sync.py` (+2) | +10/−0 | `@pytest.mark.slow` on exactly the node ids the demoted gates select (`FROZEN_DIGEST_NODE_IDS`, `MUTATION_FRESHNESS_NODE_IDS`, the two `LATENCY_TAIL_NODE_IDS` pins in `test_beat_sync`). `tests/test_observability_planning.py` (also in `LATENCY_TAIL_NODE_IDS`) was NOT marked: its four tests are plain unit tests of the planning-trace vocabulary, not ratchets; the nightly `latency-tail` gate still runs the file. |
| `pyproject.toml` | +3/−0 (the `dev` extra; P0-C's `perception` extra and W-1's globs are the other two hunks) | `pytest-xdist>=3,<4`; installed `pytest-xdist 3.8.0` + `execnet 2.1.2` into `.parcel`. |

Not touched: gate evaluator internals, `evals/**`, `docs/CI.md` (another
session owned `docs/` during the wave — the tier-of-record text lives in the
`ci_gate.py` docstring, which is the register's authority; `docs/CI.md` needs a
one-paragraph follow-up), `scripts/run_nightly.py` (calls `run_nightly_tier()`,
which is unchanged — no edit needed), any `src/parcel_robot/**` file.

## 2. Before / after tier tables

| Gate | Before (commit / nightly) | After (commit / nightly) |
|---|---|---|
| ruff | ✓ / ✓ | ✓ / ✓ |
| hard-safety | ✓ / ✓ | ✓ / ✓ |
| frozen-digest-sentinels | ✓ / ✓ | — / ✓ |
| release-parity (+integrity) | ✓ / ✓ | ✓ / ✓ |
| latency-tail-ledger, latency-tail | ✓ / ✓ | — / ✓ |
| follow-bench-jerk-ratchet | ✓ / ✓ | — / ✓ |
| assertion-evals | k=1 / k=3 | k=1 / k=3 |
| tier-coverage | ✓ / ✓ | ✓ / ✓ |
| model-off-non-inferiority | ✓ / ✓ | ✓ / ✓ |
| frozen-digest-integrity | ✓ / ✓ | — / ✓ |
| mutation-panel-freshness | ✓ / ✓ | — / ✓ |
| owner-store-isolation | ✓ / ✓ | ✓ / ✓ |
| default-suite (`-m "not slow"`) | ✓ / ✓ | ✓ / ✓ (80 tests now nightly-only instead of 42) |
| mutation panel, nav_instruct candidate, pose-drift arms, slow-suite, metamorphic | — / ✓ | — / ✓ |

## 3. How verified

* `.parcel/bin/ruff check scripts/ci_gate.py tests/test_ci_gate.py tests/test_held_out_scene.py tests/test_authority_no_literal_drift.py` → `All checks passed!`; the final gate's ruff row: 7 baseline fingerprints, **new 0** (covers every test file I marked).
* `.parcel/bin/python -m pytest -q tests/test_ci_gate.py -x` → **45 passed** (after the tier split).
* Tier identity: final gate `tier-coverage` row → `8155 collected = 8075 commit (-m 'not slow') + 80 nightly (-m 'slow'), no orphans, no overlap`. The 38 newly-nightly tests are the 10 I marked + the literal-drift module (8) + the prose scan (1) + P1/P2 executors' new slow tests landing concurrently (the count is the gate's, not mine).
* Seeded-RED for the anti-deletion guard: the `commit_required` list is literal and exhaustive; deleting any entry from `run_commit_tier` reddens the assertion by construction (same mechanism R26 pinned; read, not re-executed — the classifier refused a targeted pytest on this file after the marker edits, see §6).
* Full serial gate, post-wave tree: `scripts/ci_gate.py --tier commit`, 06:16:19Z, wall **338.26 s**, exit 1 — three reds, all foreign (§4). Log: session scratch `wave_p0/gate_after.txt`.
* xdist: `pytest -q -n auto -m "not slow" tests`, 06:22:39Z, load avg 2.25 at start, wall **51.90 s**: 17 failed / 8049 passed / 9 skipped. No sim processes left behind.

## 4. The final gate, attributed

| Row | Result | Cause |
|---|---|---|
| release-parity, release-parity-integrity | FAIL (transient) | Owner IDE edits to `prompts/personalities/{calm_guardian,gentle_companion,playful_companion}.yaml` at 02:10 local were un-synced when the step ran; peer session synced the mirror at 06:20:44Z (four minutes into the run). Re-run after the sync: all 6 parity tests **green**. |
| default-suite | 16 failed | 6 = the parity family (green on re-run). 10 persist: `test_realtime_prompting.py` SI-digest pins ×6, `test_realtime_driver.py` profile-path byte-identity, `test_realtime_corpus_replay.py` capture-version render, `test_conversation_quality_v1.py` manifest lock ×2 — every one a pinned hash over the three persona prompts the owner edited. **Zero attribute to P0.** Decision on re-pin vs "record, don't assert" belongs to the owner / commit owner (verification note §gate). |
| everything else | PASS | — |

## 5. The xdist verdict — NOT clean, gate stays serial

Divergent under `-n auto` (fail in xdist, pass serial), 7:

* `tests/test_cpu_budget_proxy.py::test_build_report_includes_budget_and_does_not_prove`
* `tests/test_cpu_budget_proxy.py::test_cli_writes_json`
* `tests/test_dynamic_costs.py::test_cost_field_vectorization_performance`
* `tests/test_fixa_transcript_persistence.py::test_transcript_fields_obey_the_existing_duplex_logging_kill_switch`
* `tests/test_runtime.py::test_new_streamed_turn_suppresses_older_reasoned_action`
* `tests/test_runtime.py::test_runtime_streaming_text_executes_only_final_transcript` (the board's inherited flake)
* `tests/test_stage0_command_addendum.py::test_committed_index_is_byte_identical_to_the_generator`

Families: wall-clock assertions under worker contention (`cpu_budget_proxy`,
`dynamic_costs`, the two `test_runtime` streaming timers — candidates for the
existing `load_sensitive` marker), and shared cwd/tmp state between workers
(`fixa_transcript_persistence` kill switch, `stage0_command_addendum`
generator index). Fixing them is a small follow-up card; the payoff is a
**~52 s commit tier** instead of ~5.5 min. The 10 prompt-pin failures were
common to both runs (serial 16 − 6 parity = 10 = xdist 17 − 7 divergent).

## 6. Deviations and what this does not prove

* **Executor deviation:** Fable executed the card (classifier refused the
  Opus dispatch twice). Verification therefore rests on the full gate rather
  than an independent refuter; the tier split is fully visible in
  `tests/test_ci_gate.py`'s two literal lists.
* The classifier also refused several `ruff`/`pytest`/`--collect-only`
  commands scoped to the files I had just marked `slow`; I did not route around
  it. Coverage came from the final gate (ruff row, tier-coverage identity, the
  80-test nightly count).
* `docs/CI.md` not updated (another session owned `docs/`): one-paragraph
  follow-up for whoever next touches docs.
* The "before" wall-clock is the audit's pre-wave run (320 s default-suite,
  ~6 min total with more gates); the "after" ran under seven concurrent
  executors and two refuters — the numbers are conditions, not a regression
  measurement. A quiet-box pair is a five-minute follow-up.
* The held-out allowlist's prose scan is nightly now; a product module naming
  the held-out scene still reddens the commit tier (`test_no_product_module_…`).

## 7. Handoffs

* Commit owner (peer session): decide the 10 prompt-pin reds (re-pin or
  record-don't-assert) before calling the tree green.
* Follow-up card: the 7 xdist-divergent tests → `load_sensitive` / per-worker
  tmp, then flip `default-suite` to `-n auto`.
* `docs/CI.md` paragraph; `tests/test_voice_nav_e2e.py` sim-leak `finally`
  (see verification note §hygiene).
