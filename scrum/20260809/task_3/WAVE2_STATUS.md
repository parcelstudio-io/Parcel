# Wave 2 · NAV+EVAL lane — status (2026-08-09)

Executor: Claude Opus. Four cards from the approved gap-closure plan
(`scrum/20260809/task_1/README.md`), landed on top of Wave-1 (be20471). Ran
concurrently with an emotion/gesture + agent/runtime/prompts lane (owns
`runtime.py`, `brain/**`, prompts, `configs/skills/**`) — none of its files
touched here. Did NOT touch the Wave-1 near-arrival methods (`pipeline.py`
~2600–3100, `instructnav/near_arrival.py`); my edits are the scan/pacing/control
path + the eval harness.

**Full default suite after all four cards: `pytest -m 'not slow'` →
2972 passed / 0 failed / 2 skipped / 33 deselected.** Ruff clean. Frozen v2/v3
minival digests byte-identical (`a17c04db…` / `919a0fea…`). Wave-1 e2e green
(`test_voice_nav_e2e.py` 17 passed / 1 xfailed).

---

## CARD embodied-refreeze-FIRST — DONE (green, honest provenance)

HEAD be20471 shipped 3 committed RED tests. Diagnosed with the 2×2 attribution
discipline (throwaway surgical revert of the Wave-1 nav code to the b75ed05
freeze point, gesture library + configs kept at HEAD):

- **`test_embodied_plan_eval::test_full_gate` + `::test_correction_waits_for_checkpoint`**
  (aggregate `simulator_step_count` 1250→1219, correction 153→124). Reverting
  ONLY `approach.py` + `pipeline.py` + `instructnav` to b75ed05 restored 1250 /
  153 / 362 and min-clearance 0.883147 **bit-for-bit**, proving: gesture library
  = **0 steps** (the 5 nav cases invoke no gesture/pose/emote skill),
  configs/navigation + authority.py = **0** (unchanged in be20471), and the whole
  move = **card near-band-inset** (the lamppost `near` pose insets 1.32→1.28 m,
  terminal approach stops ~4 cm sooner). A faster, still-verifying arrival, not a
  regression (still passed, near_surface_le_1m + off_road True, collision 0,
  plan_revision 2). **Re-frozen with that provenance.** Then my own seams moved
  it further (see seamless-pacing); final re-freeze **1219→997** with per-seam
  attribution in the test comments.
- **`test_dynamic_layer::…collision_gate_untouched`**. Root cause: Lane A
  (2026-08-07) derives the six `CollisionPolicy` thresholds from the single
  `SafetyEnvelope`, so `_annotated_defaults` (literal-only) can no longer see
  them and the old `set(head_defaults) >= {…}` guard was **committed RED at
  b75ed05** demanding literal defaults the refactor removed. The gate BEHAVIOUR
  is provably untouched (the two AST comparisons pass; values derive bit-for-bit
  per `test_authority_family_equality`). **Re-pinned honestly and STRONGER**: the
  live `CollisionPolicy()` is now asserted against the exact Go2 thresholds
  (person_stop 1.2, person_slow 2.5, obstacle_stop 0.6, obstacle_slow 1.2,
  slow_scale 0.35, reaction 0.12), so any re-tune — literal or hidden in the
  envelope — reddens. (The D5 two-authorities gap, runtime 0.65 vs navigator 0.8,
  is a separate key set tracked by `safety-margin-derivation`, not this gate.)

No behaviour weakened to make any test pass.

## CARD seamless-pacing — DONE (3 seams, files I own, no new modules)

- **Seam 3 — region "inside" convergence** (`pipeline.py::_inside_arrival_goal_region`):
  region goals ("go to the sidewalk") returned False here unconditionally and
  left arrival to the geometric approach pose, which spun `align_goal` in place
  (no meaningful heading inside a polygon) to the step limit while already inside
  — the `navigation_step_limit_inside_goal` rows. Now converges the instant the
  robot stands inside the committed polygon with the **same** terminal clearance
  the verification re-checks (trigger ⊆ verify → no invented arrival).
- **Seam 2 — terminal creep floor** (`grid_navigator.py`): near the goal the
  multiplicative slowdown bottomed to ~0.032 m/s so the last ~0.5 m crawled >15 s.
  Floored the *approaching* forward request at the same 0.12 m/s recovery creep
  the yield policy already trusts (one value, both paths), gated off while
  turning hard, applied only while `goal_distance > arrival_radius`, still bounded
  by every downstream reactive gate. **Not a stop override.**
- **Seam 1 — scan-while-translating** (`pipeline.py` RESOLVED confirmation):
  during multi-view confirmation of a single non-interchangeable RESOLVED target
  already faced, creep toward it instead of rotating-then-translating. Hard-gated
  (never a region/"nearest" ranking sweep, target within the half-angle ahead,
  past 1.5 m, omnidirectional clearance > 1.0 m, fail-safe when clearance is
  unknown). Small measured effect (confirmation for centred targets is already
  fast); left the region look-around (~8 s) and full-turn ScanBehavior untouched
  on purpose — they carry the region-instance selection the embodied freeze
  depends on and the anti-false-positive scan gate.

**GATE — v3 minival candidate, scaled budget (see budget-honest):**
`navigation_step_limit_inside_goal` **3 → 0**; candidate SR **0.12 → 0.24**,
**above** baseline 0.20; collisions **0**. false_arrival = 2 — see the honest
stop-and-report below.

**Translation duty-cycle before/after (passing cases, seams 2+1 toggled, live):**
the duty *ratio* is roughly flat (~71.9% → 71.1%) because the seams remove slow
terminal-crawl translation and terminal-align rotation *together*; the real
seamlessness win is **wall-time**: passing-case mean ticks **127 → 99 (−22%)**,
the near approach `object_relative-A-00` **141 → 88 (−38%)**, region
`region_goal-A-00` **210 → 152 (−28%)**; embodied suite **1219 → 997 (−18%)**;
the lamppost `near` correction case **124 → 84 (−32%)**.

**Attribution safety:** the one hard collision that appears at a 400-step flat
budget is `region_goal-C-10` in the SearchEntity **frontier** recovery (vx 0.220
at tick 389) — **identical with the terminal floor at 0.12 and disabled at 0.0**,
so it is a pre-existing far-start frontier/routing defect, not my pacing. It does
NOT occur under the scaled budget (Tier C's scaled budget 270 < tick 389).

## CARD budget-honest-minival — DONE

New **`scaled-path-v1`** budget policy in `runner.py` (default stays `fixed`, so
every frozen row + existing test is byte-identical): per-episode budget =
120 overhead + shortest_path_m / (0.30 m/s · 0.1 s), floored at `--max-steps`,
capped at 1200; point-goal families only (spatial keep the flat base). `--budget-policy`
added to the CLI; **`max_steps` added to the ledger row schema** and to every
report episode row (`EpisodeRunResult.max_steps`). Two scaled ledger rows written
(`…161252Z` baseline, `…161335Z` candidate) both carrying `budget_policy` +
`max_steps`. Annotated the two audit diagnostic rows in `results/README.md`
(`…054157Z` duplicate-of-repo-run, `…054430Z` long-budget = the 0.12→0.48-by-raising-max-steps
artifact). **Honest SR under scaled budgets: baseline 0.20, candidate 0.24; Tier E
absent targets now report `semantic_target_not_found` / `…_unreachable` at their
1200 budgets, not `navigation_step_limit`** — starvation removed.

## CARD panel-v3-repin — DONE

Bumped `mutation_panel.py` `EPISODE_SET_V2 → V3` (import + 3 use sites +
docstring). Re-audited `PANEL_EPISODE_IDS` coverage on v3: `region_goal-D-15`
still binds the reactive gate **184/200** (the key coverage episode is
preserved); updated the coverage comment with the v3 binding set (now 4 episodes)
honestly. Re-ran and **re-committed `mutation_panel.json`: `episode_set_version`
v3, 6/6 killed, and `no_false_arrival` LIVE** — green on the clean run (restored
from v2's silently-disabled False) AND actively reddened by the
`reactive_gate_disabled` mutant. Added anti-rot slow-tier guard
`tests/test_mutation_panel_freshness.py` (fast: committed payload on the newest
frozen `vN`; slow: live re-run), so a panel left on a retired set reddens
automatically when a v4 freezes.

---

## Stopped-and-reported (out of my three-seam lane)

- **candidate false_arrival = 2** (v3 minival, all budgets). Both are **cross-class
  commits**, not pacing: `object_goal-D-15` "walk towards the **tree**" committed a
  **lamppost** (arrived_verified at DTG 2.9 m — the audit's "big tree → lamppost");
  `object_goal-B-05` "walk towards the **streetlight**" committed a **tree**. These
  are the grounding/commit path (stubbed-SigLIP hash-embedding), owned by the
  **`class-consistent-commit`** and **`siglip-real-embeddings`** cards. Pre-existing
  (2 before my changes, 2 after — my seams add **zero**). The seamless-pacing
  gate's `false_arrival 0` clause is gated on `class-consistent-commit` landing,
  which is not in this Wave-2 lane. Did NOT weaken any verification to force it.
- **panel-v3-repin extras** (`unseen_split.py` v2→v3, `test_nav_metamorphic.py:243/294`,
  scene_split regeneration + split-gap test) — deferred: `test_nav_metamorphic.py`
  is outside my owned files and overlaps the separate `mirror-xfail-chase` card;
  `test_nav_instruct_scene_gen.py` couples to `unseen_split`'s pack version, so a
  bump belongs to a coordinated pass. My binding panel gate (the mutation panel)
  is fully met.

## Verify

- Full default suite `pytest -m 'not slow'`: **2972 passed, 0 failed, 2 skipped**.
- Ruff clean on all touched files.
- Frozen v2/v3 minival digests **byte-identical** (`a17c04db…` / `919a0fea…`);
  frozen-episode tests + ledger-prefix sha256 green; ledger append-only (2 new
  scaled rows only).
- Wave-1 near-arrival green: e2e 17 passed / 1 xfailed; `test_search_reground_bench`
  green; the embodied lamppost `near` correction case still verifies (at 84 steps).
- New retired-family literals I introduced were **derived away, not cap-bumped**:
  the seam-3 `0.32` now reads `ROBOT_FOOTPRINT_RADIUS_M`; the seam-1 min-range
  moved off the retired `1.2` to `1.5`.

## Files touched (mine)

`src/parcel_robot/navigation/pipeline.py`, `.../grid_navigator.py`,
`evals/nav_instruct/runner.py`, `.../run_nav_instruct_v1.py`,
`.../results/README.md` (+ 2 appended ledger rows & 2 report jsons),
`scripts/mutation_panel.py`, `evals/nav_instruct/results/mutation_panel.json`,
`tests/test_embodied_plan_eval.py`, `tests/test_dynamic_layer.py`,
`tests/test_mutation_panel_freshness.py` (new),
`evals/companion/duplex_v1/run_duplex_v1.py` (embodied mirror pin 1250→997,
mirroring Wave-1's follow-bench pin — the only thing my embodied re-freeze broke
in the full suite).
