# C0 + C2 · ARRIVAL-SETTLE-1 — one arrival authority that observes the settle; clear the hard-safety red on `main`

**Executor:** Opus (one executor for both, C0 first) · **Verifier:** Fable · **Second lens:** parcel-fb (who bisected C0) · **Wave:** A

## C0 — the red row

`tests/test_mutation_panel_freshness.py` is red on `main` (a379bf4) on the `nav-region_goal-D-15-1b8b2361` row: scorer-true / system-false (`evals/nav_instruct/bridge_v3_v4.py:320, :376, :640`). parcel-fb's clean-worktree bisection attributes it to the owner's a379bf4 hard-safety change, not to research. **Owner's choice, recorded on the STATUS file before any edit:** (a) fix-product — find the seam where the system verdict and the scorer verdict diverge on D-15 (a stationary human on the route; `tests/test_person_cell.py:3-7`, `tests/test_v4s_search_cells.py:258-283` describe the class) and make the system verdict honest without weakening the reactive gate; or (b) recorded re-run — re-freeze the panel row under the attribution/re-freeze policy with the diff attributed to a379bf4. Default if the owner is silent: **(a) attempted for ≤ 2 h; else (b) with the attribution written.** The freshness test green in a clean worktree is C0's acceptance row.

## C2 — the defect

Three harnesses disagree about "arrived": the executive says `failed` where the robot arrived (NAV-INT-1: 11/29 bench legs; 17/80 authority disagreements; QEV-1: 25/125), a deterministic harness said "reached" where it failed (LIT-1 5/5), and MA-1's gold required 5 stopped frames inside the band that its loop could never observe (breaks one frame after `done()`, 133/133). The product harness has the same shape: `HeadlessCityQualityHarness` breaks on `command.stop`/`navigator.done()` (`simulation/headless_city.py:722-732`) and its `stopped` is "terminal command zero on one frame" (`:118-121`). Evidence: `nav-gen-attribution-1/VERDICT.md §5.1`, `nav-interrupt-1/VERDICT_FABLE.md` item 3, `sim-loop-1/VERDICT_FABLE.md`, `backlog/NEXT.md` N45/K0.

## Build

1. **Settle-observing terminal in the product harness:** after `navigator.done()` or a stop command, keep stepping the world for `settle_frames` (default 5 at 10 Hz) and record `settled = inside band for all settle frames AND zero command for all settle frames`. `HeadlessTaskResult` gains `settled: bool` and `settle_frames_observed: int`; `status`/`reason` semantics unchanged (E3 — the frozen NAV_INSTRUCT rows read `status`, not `settled`).
2. **One arrival authority:** the executive's terminal fact for a navigation step comes from the same predicate the harness reports (`arrived_verified` ⇔ inside band ∧ settled), through the existing K0/N45 arrival-authority seam — do not add a fourth opinion. If the executive's `failed` on an arrived leg comes from a false `failed` receipt (NAV-INT-1: six re-issues were triggered by one), fix the receipt, not the scorer.
3. Log `mission.metadata['goal_source']` (and `poi_refused` when C1 lands) in `HeadlessTaskResult` so NAV-GEN-1's rows can attribute per episode (C2 owns `headless_city.py`; C1 must not edit it).
4. Report both predicates side by side on every re-scored row (one-frame vs settle) so the delta is a number, never an interpretation.

## Acceptance (verbatim bars)

- C0: `~/.cache/parcel-guard/pytest_guard.sh --label C0 .parcel/bin/python -m pytest tests/test_mutation_panel_freshness.py -q` green in a clean worktree, with the (a)/(b) decision and the owner's answer (or "owner silent, default applied") on the STATUS file.
- C2 RED: NAV-INT-1 tier `research/20260829/nav-interrupt-1/run.py` (see its README; `PARCEL_MEMORY_PATH` → scratch, unique socket, `systemd-run --user --scope -p MemoryMax=12G`) reproduces authority disagreements 17/80.
- C2 GREEN: same tier ≤ **2/80** disagreements; bench legs "system-failed-but-arrived" **0/29**; `test_k0_arrival_authority.py`, `test_authority_half_scale_smoke.py`, `test_embodied_plan_eval.py` green through the guard; NAV_INSTRUCT frozen digest `e7c302dd…` unchanged (`evals/nav_instruct` `--check`); NAV-GEN-1 `--arms A0` re-run with `settled` logged: report strict (one-frame) vs settled success on 450 generated episodes (expected within 10 points of 0.65; if settled < 0.40 the navigator does not hold still after arrival — record, do not tune).
- No safety floor touched (grep-proof in STATUS); `config.py` unchanged; `pipeline.py` net-negative or unchanged.

## Does not prove
Physical arrival, camera/LiDAR perception, or the N45 lamppost class matrix beyond the rows named.
