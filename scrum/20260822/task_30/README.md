# Task 30 — GATE-0b: the clean clone's remaining 51, and a ledger that only appends on purpose

**Executor:** Claude Opus · **Verifier:** Fable · **Board:** `../TASK_BOARD.md`
(P0 standing rules apply). **Evidence:** `task_20/GATE0_STATUS.md` (the
clean-clone runs and the corrected "51 remaining failures" table),
`AUDIT_WEEK1_FABLE.md` §GATE-0 and §ROAM-1 (finding 4), `WAVE2_DESIGN_FABLE.md`.

## Why
GATE-0 made a fresh clone print a verdict; the verdict is still red for 51
pre-existing reasons, none of them a product defect, and the hosted job (B20)
will inherit them. Separately, `evals/nav_instruct/run_nav_instruct_v1.py`
appends a row to append-only provenance on every run — ROAM-1's two minival
runs wrote two rows (one from a seeded tree) before the verifier restored the
file.

## Work
1. **Attribute every one of the 51 by root** (the verifier's count, re-measured
   in a clean clone): ~5 under `evals/external/results/{barn_ros2,threewe}`
   (ignored by `evals/external/.gitignore:1` while siblings are tracked);
   ~17 needing `.cache/external-evals/runtime/barn-parcel-bundles` (root
   `.gitignore:12`, 19 MB); ~7 failing the V9 training-manifest mode-bit check
   (`split.json` is tracked `100644`, 444 in the dev tree, 664 in every clone);
   3 habitat provenance; 1 BARN generator checkout; 1 under
   `evals/external/development/barn_frontier_detour_v4/results/.gitignore`;
   the non-external 16 (capture/clockmap 6 — ENV-1b branches now, re-check;
   owner-store 1; prototype_profile 5; future_clock_guard 4).
2. **Fix by class, not by vendoring:** the results carve-out + manifest for
   the ~5; `skip-with-reason` (a named marker, listed in the gate summary) or
   the nightly selection for tests that need a generated/external root — never
   21 GB into git; a decision on the V9 mode-bit premise (drop it, or `chmod`
   in test setup with a reason); habitat 3 diagnosed and either fixed or
   skip-with-reason; the non-external 16 fixed or declared.
3. **`--no-ledger` / `--ledger PATH`** on `run_nav_instruct_v1.py` (default
   unchanged) and a guard that a verification/seeded run cannot append to
   `evals/nav_instruct/results/ledger.jsonl`; the README's append-only rule
   restated with the annotation requirement.
4. **Pre-register:** a fresh tracked-only clone + `pip install -e '.[dev,voice]'`
   + `ci_gate.py --tier commit --json` → **RESULT: PASS** with the skip list
   printed; the hosted workflow file passes `act`-style dry validation; B20
   remains the owner's click. Seeds RED: a test that needs an external root and
   is not marked goes red in the clone; a minival run with `--no-ledger` that
   still appends.

OWNS: `evals/external/.gitignore` and the two nested ignore files, the external
eval test files' markers (`tests/test_barn_*`, `tests/test_run_barn_*`,
`tests/test_habitat2020_*`, `tests/test_threewe_*`), `scripts/ci_gate.py`
skip-list reporting (re-read: XD-1 may be editing the tier runner — marked
regions), `evals/nav_instruct/run_nav_instruct_v1.py` + its README,
`tests/test_nav_instruct_ledger_guard.py` (new), `task_30/` docs. MUST NOT
TOUCH: frozen manifests, the pack, `docs/`, `README.md`.

## Definition of done
Clean-clone PASS with an honest skip list; the ledger guard seeded RED;
`GATE0B_STATUS.md` in the lightweight register with the per-root table and the
V9 decision recorded.
