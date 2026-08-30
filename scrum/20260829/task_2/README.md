# Task 2 · FIX-SUBSTRATE-1 — fix the issues the fluidity verdict found, before any model work

**Date:** 2026-08-29 (America/New_York), opened 21:5x EDT · **Integrator / verifier:** Fable (parcel-0e) · **Executors:** Opus, one per card · **Second lens:** parcel-fb (C0–C3), parcel-6c (C4–C5)

**Owner instruction (verbatim):** "let's commit and fix the issues first. And flesh out the implementation plan that we need to do. Opus should implement while fable reviews."

**Physical-motion status:** **NO-GO** (unchanged; nothing on this board authorizes motion).

**Source of the issues:** `research/20260829/VERDICT_RESEARCH_QUESTION.md` §5 (the decision), `nav-gen-attribution-1/VERDICT.md`, `model-b-contract-2/VERDICT.md`, `nav-interrupt-1/VERDICT_FABLE.md`, `sim-loop-1/VERDICT_FABLE.md`, `model-b-narration-1/VERDICT_FABLE.md`, plus parcel-fb's hard-safety bisection (card C0).

## Why this order

The verdict's finding is that every fluidity experiment was refuted by the *substrate* — arrival/stall/grounding mechanics in the navigator and a voice with no fact contract — not by the Model A/B idea. So the substrate is fixed first, with instruments that already exist (NAV-GEN-1's 530-episode harness, NAV-INT-1's tier, MB-1/MB-2's scorer, LIT-1's loop) as the acceptance rows. No card on this board trains a model or touches a safety floor.

## Board

| card | file | wave | executor touches | acceptance instrument | status |
|---|---|---|---|---|---|
| **C0** hard-safety red on `main` (`region_goal-D-15` scorer-true / system-false freshness row) | `C0_C2_ARRIVAL_SETTLE.md` | A | evals/nav_instruct (bridge_v3_v4 rows), tests/test_mutation_panel_freshness.py — owner's choice: fix-product vs recorded re-run | `tests/test_mutation_panel_freshness.py` green in a clean worktree | OPEN |
| **C1** POI second oracle answers scene-relative place names on any scene | `C1_POI_ORACLE.md` | A | `navigation/grounder.py`, `navigation/pipeline.py:1136-1150` (leaf helper), `configs/navigation/default.yaml` | NAV-GEN-1 A0: crosswalk false arrivals 42 → 0, `target_id == 'crosswalk'` 90/90; frozen digests unchanged (E3) | OPEN |
| **C2** settle-observing arrival + one arrival authority | `C0_C2_ARRIVAL_SETTLE.md` | A | `simulation/headless_city.py:118-121, 722-732`; arrival authority seam (K0/N45 successor) | NAV-INT-1 authority disagreements 17/80 → ≤ 2/80; NAV-GEN-1 A0 strict re-scored under the settle predicate | OPEN |
| **C3** stall class: `navigation_no_progress` with the route still planned | `C3_STALL_CLASS.md` | A | `navigation/pipeline.py:4634-4656` → leaf module (pipeline.py is over the DEC-0 ceiling: net-negative only) | NAV-GEN-1 A0: 68 stalls attributed; non-POI stall rate halves at 0 collisions | OPEN |
| **C4** whisperer: plan-acceptance kind + `KIND_REROUTE` band decision | `C4_WHISPER_ACCEPT.md` | A (leaf) / B (install hook) | `realtime/whisperer.py` (leaf), `runtime.py` hook (wave B — owner's dirty diff) | MB-1 corpus: b1 "new goal acknowledged" produced from an executive receipt; reroute band test | OPEN |
| **C5** receipt-typed speech acts as a product leaf, flag OFF | `C5_SPEECH_ACTS.md` | A (leaf) / B (install) | new `realtime/speech_acts.py` + `realtime/narration_matcher.py`; `realtime/lane.py` install (wave B) | MB-2 arm T numbers reproduced through the product module; off-path byte-identical | OPEN |
| **C6** executive plan queue with lineage (queue / revise / keep; DMC-1 facts) | `C6_PLAN_QUEUE.md` | B | `brain/executive.py` (owner's dirty diff), `runtime.py` `_apply_goal_amend` | NAV-INT-1 tier: admission ≥ 0.9, "queue" no longer a re-issue, resume path ratio ≤ 1.1× | OPEN (after owner lands/discards the diff) |
| **C7** harness truth: LIT-1 false "reached", NAV-INT-1's two defects, results-schema hygiene | `C7_HARNESS_TRUTH.md` | A | `research/20260829/sim-loop-1/sim_loop.py`, `nav-interrupt-1/harness.py`, `nav-gen-attribution-1/analyze.py` (research only) | LIT-1 r1–r5 narrate the receipt's kind; NI-1 re-issue with cue stripped admits | OPEN |

Not cards (already in flight or notes): the acoustic runner negative-offset crash is fixed in the owner's uncommitted diff (`evals/companion/acoustic_loop_v1/run_acoustic_loop_v1.py` +8, lines 241-250) — verify when it lands; NAV-CORE's "planner 0.42 m" is pre-A2 (documentation note in C3).

## Standing constraints (verbatim from the integrator; on every card)

- Safety floors untouchable: `obstacle_stop_m 0.65`, `apply_reactive_safety`, `finalize_command`, `core/hard_stop.py`, the A3 latch, the A6 stop path.
- `config.py` is at the 1000-line DEC-0 ceiling — zero growth. `pipeline.py` is far over the ceiling and on the debt baseline — net-negative or leaf module only; the DEC-0 ratchet counts it.
- Zero `noqa` except a documented never-raises boundary in the module's idiom, grep-counted before the number is written.
- Frozen evidence E3: no frozen digest moves; any safety-relevant value change follows the attribution/re-freeze policy.
- $0 hosted unless the card states a cap through `hosted_budget.py`.
- Every pytest through `~/.cache/parcel-guard/pytest_guard.sh --label <card> …`; never `-n auto`; no `--pdb`; executors never run `ci_gate.py`; `TMPDIR` unset for unix-socket tests.
- Same-length source seeding needs the `__pycache__` drop.
- Owner facts: no robot hardware; `parcel_memory.sqlite3` never opened read-write (`PARCEL_MEMORY_PATH` → scratch); the owner's `:8080` / `:8765` / `/tmp/parcel_sim.sock` never touched; sims on unique sockets under `systemd-run --user --scope -p MemoryMax=12G`, killed by the card that started them.
- Shared tree: edit only your card's OWNS; git is read-only for executors (the integrator commits); foreign research folders (Sol's, DMC) never edited.
- Files in the OWNER's uncommitted diff (`runtime.py`, `brain/executive.py`, `gateway/*`, `bridge/*`, `control/*`, `navigation/grid_planner.py`, docs/, configs/robot.go2_edu_plus.yaml, prompts/) are NOT touched in wave A; a card that needs them ships a leaf module + a one-line install hook and says so.

## Working agreement

1. Executor reads the card, then the cited verdict sections, then the code lines named — in that order — and writes `<CARD>_STATUS.md` in this folder *incrementally* (pre-flight → each acceptance row → close), quoting the acceptance bar verbatim beside the number.
2. Reproduce the defect first with the named instrument (the RED row), fix, re-run the same instrument (the GREEN row), and run the named regression subset through the guard. Report exact commands.
3. No criterion on a card moves. If an acceptance row is impossible, record why and do the closest faithful thing — the verifier decides.
4. Verifier (Fable) re-runs headline rows through the product caller, writes `AUDIT_<CARD>.md`; second lens as listed. Integrator runs `ci_gate.py --tier commit` once at close, in a clean worktree, and commits.

## Definition of done (wave A)

C1, C2 (+C0 decision recorded), C3, C7 landed with their GREEN rows reproduced by the verifier; C4/C5 leaf modules landed flag-OFF with byte-identical off-path tests; gate green except rows attributed to the owner's diff; `CODEBASE_INDEX.md` regenerated; unfinished items moved to `backlog/`.
