# Task 29 — FINISH-1: the week-1 close — every unfinished item, one card

**Executor:** Claude Opus · **Verifier:** Fable · **Board:** `../TASK_BOARD.md`
(P0 standing rules apply: prototype not production; Edit-only; git read-only
for executors; targeted tests + ruff on OWNS with `TMPDIR` unset; seeded RED
per new guard; only the verifier runs `scripts/ci_gate.py`). **Evidence:**
`../AUDIT_WEEK1_FABLE.md` (verdicts per card, findings, rulings) and each
card's status doc. **Why this card exists:** at 12:00 EDT the account's
monthly spend limit killed four agents mid-flight — the ROAM-1, CURIO-1 and
GATE-0 correction passes and the AIR-1 re-verification. The tree is
consistent (every changed module compiles; 366 targeted tests across the three
cards green; ruff ratchet back at exactly 7 after the verifier removed two
lines of lint debris), but the passes are incomplete and three status docs do
not describe the tree. This card finishes them. Baseline: `8862220` + the
uncommitted week-1 tree.

## State at dispatch (verified by Fable, 12:05 EDT)

| Card | Code | Doc | Verification |
|---|---|---|---|
| TURN-1 | corrected | corrected | **ACCEPT** (re-verified) |
| MARK-1 | corrected | corrected (3 doc notes below) | **ACCEPT** (re-verified) |
| ENV-1b | done | done | **ACCEPT** |
| AIR-1 | corrected (6 items + the mux path) | corrected | **re-verification died** — pending |
| CURIO-1 | corrected (§9.1–9.11 written) | §9.7 table half-filled (`<!--SB*-->` cells: the seed-777 shipped run never completed) | pending |
| ROAM-1 | items 1, 2, tether mechanism, prototype `roam:` keys landed | **no Correction pass section**; headline still quotes 20.67 m | pending |
| GATE-0 | ACCEPTED; 6-item correction pass **never started** | — | pending |

## Work — per card, in this order

### A. ROAM-1 (task_23) — finish the correction pass
Landed already (read them, do not redo): `safety.py` `BEHAVIOR_MODES` +
`roam`/`roam_stop` with the four product-door guards
(`test_the_roam_tool_is_admitted_by_the_PRODUCT_supervisor`, `…refuses_roam_under_a_latch`,
`…refuses_a_system_initiated_roam`, `…allowlist_is_names_only_no_new_permission`);
the yield fix (`stop_roam("owner_command")` no longer calls `stop_motion()`)
with `test_yielding_to_an_owner_command_does_not_cancel_that_command`;
`PatrolLimits.tether_m` (+186 lines in `patrol/mission.py`) with
`test_the_tether_turns_a_patrol_back_toward_home`; the `roam:` block in
`configs/robot.prototype.yaml` + the overlay exemption + the typo guard.
1. **Pre-register, then re-measure three consecutive 120 s `--static-city`
   runs through the product runner with the tether ON** (the value
   `limits_from_safety` sets — state it): each ≥ 5.0 m path, **≥ 1.0 m net
   displacement IN-BLOCK**, 0 contacts, 0.7 m zone respected. Add the
   in-bounds qualifier to the harness metric (net displacement while
   |x|,|y| ≤ 12) and report both numbers per run. Seed: tether off → a run
   that exits the plane is flagged by the qualifier (RED).
2. Restate the Go2-purchase input everywhere (headline, R2b, the PO-1
   handoff): "two in-block runs ≥ 1.0 m (3.37, 2.05) + one run that exited
   the scene (20.67); with the tether: <the three new numbers>".
3. Race fix if not yet done: re-check `self._roam_policy is policy` under
   `_command_lock` immediately before `submit_motion`, and
   `arbiter.cancel('voice')` in the post-check (seeded).
4. Declare the ledger write in Deviations: the two minival rows appended to
   `evals/nav_instruct/results/ledger.jsonl` (restored to HEAD by Fable);
   never run a minival without `LEDGER` redirected.
5. Doc hygiene: seed-driver invocation/stdout under `task_23/evidence`; which
   tests post-date the seed runs; remove test-file names that do not exist;
   `stop_latency_s` is the harness's sleep; the owner-gated PASS criterion
   points at `/api/state`'s roam key, not a panel block.
6. Append the **Correction pass** section to `ROAM1_STATUS.md` (what landed,
   what the verifier confirmed, the new numbers, seeds RED).

### B. CURIO-1 (task_24) — complete §9.7 and close
1. Run the second shipped-default arm (seed 777, `--shipped`) and fill every
   `<!--SB*-->` cell in §9.7; if any row misses, say so.
2. Confirm `_curiosity_activity_busy` reads `roam_idle_checkpoint()` (ROAM-1
   has landed) and that `test_curio1_chatter.py` is green on the final tree
   (60 passed at last count) with ruff clean on OWNS; refresh
   `SEEDED_RED.json` if any file moved since §9.10.

### C. GATE-0 (task_20) — the six-item correction pass (never started)
1. `tests/test_unitree_asset_pack.py::test_an_unmanifested_file_smuggled_through_the_carve_out_reddens`
   writes a probe `.obj` into the REAL pack directory (spurious reds at
   one-worker-per-test xdist, reproduced at `-n 26`/`-n auto`; a SIGKILL
   leaves a stray the gate blames on the pack). Redesign through a tmp copy of
   the pack + monkeypatched `_git_paths`, as the gitlink seed does; keep the
   seeded RED.
2. The "51 remaining clean-clone failures" table: capture/clockmap 6 (not 5),
   owner-store 1 (not 2). Rewrite the GATE-0b handoff honestly: `results/*`
   explains ~5; ~17 need `.cache/external-evals/runtime/barn-parcel-bundles`
   (root `.gitignore:12`); ~7 fail the V9 training-manifest mode-bit premise
   (`split.json` is tracked 100644, 444 in the dev tree, 664 in every clone —
   no carve-out fixes it); 3 habitat provenance; 1 BARN generator checkout;
   1 under `evals/external/development/barn_frontier_detour_v4/results/.gitignore`.
   Recommendation: skip-with-reason or nightly selection for the ~25 that
   need a generated/external root (do not vendor 21 GB); a decision on the V9
   mode-bit check.
3. Seeds E/F counts were measured with the pack untracked — quote the
   post-integration counts (8/32 and 1/2); optionally `git ls-files --deleted`
   in the ship test.
4. `scripts/ci_ruff_baseline.json`'s hand-written `ruff_version_stamped_at`
   is not produced by `update_ruff_baseline()` — drop it or emit it.
5. Annotate run B's `[FAIL] ruff` as an A/B-method artefact; note the hosted
   job will be RED for pre-existing reasons and its 20-minute timeout is at
   risk.
6. **Seat `CODEBASE_INDEX.md`** (and `tools/codebase_index.py` if the scan
   reaches it) in `tests/test_held_out_scene.py`'s allowlist with the reason
   "generated file index; lists paths only, never scene content; regenerated
   per commit by `tools/codebase_index.py`" — the nightly held-out prose scan
   is red on it today. One seat, grown deliberately.
7. If one line: `test_one_exploding_evaluator_costs_exactly_one_row` should
   assert the row count its name promises.

### D. MARK-1 (task_22) — three doc corrections (code is ACCEPTED)
1. `MARK1_STATUS.md` §2 and the `lane.py:~2728` docstring say "unknown status
   ⇒ False, so the hold falls through to the floor" — false: an unknown or
   `incomplete` status settles as *finished* (counted as a survived
   backchannel, no `sink.interrupt`), exactly like `completed`. Describe the
   behaviour as it is (it is defensible) or change it — say which.
2. The "What changed in this pass" table credits TURN-1 with +73/−0 in
   `lane.py`; TURN-1-marked hunks sum to ~159 added lines.
3. Cross-card: `tools/bargein_through_air.py` (AIR-1) neither reads
   `interrupted_at`/`interrupted_byte`/`interrupted_t_s` nor knows they exist;
   its docstrings and `unmeasured_reason` text assert the opposite and
   `test_air1_scorecard.py:566-575` pins that text. **Do it in section E.**

### E. AIR-1 (task_25) — the cross-card seam + what the re-verification must see
1. `tools/bargein_through_air.py`: read `segment["interrupted_at"]` (and
   `interrupted_byte`/`interrupted_t_s`) for `interrupt_p50_s`; update the
   docstrings, the `unmeasured_reason` text and the pinned test; the row is
   now measurable from the tee. Seeded: a capture with `interrupted_at`
   present yields a number; absent → `unmeasured`.
2. Leave the rest for the verifier: the mux write discipline (`XvfControl`,
   `mux_session`, no `SAVE_CONFIGURATION`, restore-with-read-back — what
   happens if the read-back fails), the stream fix (`_ProbePlayer` /
   `_StreamRecorder`), the downgrade-only override invariant, the spend join,
   the owner-silence split, the turn rows' RT-TURNS-1 handoff, and the runbook
   walked step by step.

### F. Integrator steps (Fable, at the close — not the executor's)
`git add third_party/unitree_mujoco` (20 files, 0 gitlinks); regenerate
`CODEBASE_INDEX.md`; full gate with `TMPDIR` unset; commit by explicit path
list; push; notify parcel-1e / parcel-74 (parcel-1e offered a read-only
attribution pass — baseline `8862220`); update the board rows.

## OWNS
Everything the six cards own (`task_20..25` READMEs + their status docs'
post-verification regions) — the executor of this card inherits them all
because no other card is executing; re-read every file before each edit
regardless. MUST NOT TOUCH: `reactive_safety`, `core/hard_stop`, `docs/`,
`backlog/`, `README.md`, `scrum/20260821/`, the venv.

## Definition of done
Every row above done or declared as a miss with its reason; each card's
status doc describes the tree as it is; `FINISH1_STATUS.md` in the lightweight
register listing, per card, what was finished, what was measured (the three
tethered roam runs are a Go2-purchase input — report them plainly), and what
the verifier must look at first; ruff ratchet at exactly 7; targeted tests
green on every touched file. Then Fable's re-verification of AIR-1 and of
this card's changes, the integrator steps, and the wave-2 design.
