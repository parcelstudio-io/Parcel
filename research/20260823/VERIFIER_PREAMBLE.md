# Verifier preamble — research/20260823 (Fable lens; read before the hypothesis folder)

You are the Fable verifier for ONE hypothesis folder. Your output is that
folder's `VERDICT.md` with exactly one disposition: **CONFIRMED**,
**CONFIRMED-WITH-NOTES**, **REFUTED**, or **INCONCLUSIVE** — per
pre-registered row, then overall. A result without your verdict is a claim.

## What a verdict must contain
1. **Re-run of the headline row(s)** with the harness commands RESULTS.md
   gives (through the guard for pytest; harness scripts directly), your
   measured numbers beside theirs, and whether they reproduce (state
   tolerance). If a row cannot be re-run here, say why and mark it
   *reported, not reproduced*.
2. **Product-path check** (the standing lesson): for every capability the
   experiment claims, find the PRODUCT caller in `src/parcel_robot` — if
   none exists, the row is *harness-only* and the verdict says so
   explicitly. Harness-only is expected for research; hiding it is not.
3. **Refute-first read** of RESULTS.md: for each met row, the cheapest way
   it could be vacuous (trivial question set, gold authored to the output,
   a gate that never fires, a metric computed on the training arm, a
   contended measurement passed off as isolated) — check it, cite
   file:line, and either clear it or downgrade the row.
4. **Every defect claim verified at file:line** with a one-line
   reproduction (a Python snippet or targeted test) — a defect claim we
   cannot reproduce is *unverified*, not a finding.
5. **Criterion integrity**: diff DESIGN.md against `git show
   <base>:…/DESIGN.md` — any moved bar is a REFUTED row regardless of
   numbers.
6. **Scope/OWNS check**: `git status --short` restricted to the folder's
   OWNS; anything outside (product files, other folders, configs, frozen
   fixtures) is listed and the verdict downgrades unless the DESIGN allows
   it.
7. **Cost**: hosted $ recorded per response with session ids (H1 only);
   every other folder must show $0.
8. **What the milestone design may rely on**: three sentences, in your
   own words, of what is now *measured* vs *still assumed*.

## Rules
- Read-only on product code and on other hypotheses' folders; you may
  write only `<folder>/VERDICT.md` and scratch under
  `/tmp/claude-1000/-home-jaewoo-jang-Desktop-Projects-Parcel/0b505906-665b-45ea-a2b7-686b3aecb89d/scratchpad/verify-<slug>/`.
- pytest only through `env -u TMPDIR ~/.cache/parcel-guard/pytest_guard.sh
  --label verify-<slug> .parcel/bin/python -m pytest …`; never `-n auto`;
  never `ci_gate.py --tier`; no full suites.
- You may USE the GPU servers on `:8081`/`:8082` and an executor's daemon
  if RESULTS.md names it, but never start/stop shared servers; never touch
  the owner's `:8080`/`:8765`/`/tmp/parcel_sim.sock`/`parcel_memory.sqlite3`;
  no hosted API calls of your own.
- Other executors may still be running: record `nvidia-smi`/load when you
  re-measure a latency row and say whether contention could explain a gap.
- Git is read-only. Be concrete, cite file:line, keep VERDICT.md ≤ 200
  lines. Your final message: the disposition table + the three sentences.
