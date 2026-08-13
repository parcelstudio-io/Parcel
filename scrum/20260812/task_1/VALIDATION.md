# Validation record

Revision: **r2** — re-run per `FABLE_VERDICT.md` RC-6. The r1 record is superseded, not
amended: its figures are reproduced below only where they are needed to show what moved.

- **Run date:** 2026-08-12 (local, UTC−4); the host `date -u` stamps recorded below
  read 2026-08-13 UTC.
- **Workspace:** `/home/jaewoo-jang/Desktop/Projects/Parcel`
- **Baseline:** commit `7242660` — "Land route-memory arms, person-aware yield/keepout,
  and 20260811–12 scrum closes." (RC-6). r1's scope line said "the repository's current
  dirty worktree"; that worktree is this commit.

## What r1 recorded and why it was re-run (RC-6)

r1 reported `default-suite: 3,889 passed` and an elapsed of 149.8 s. The Fable review
established that this figure was **an unrepeatable mid-batch transient**: it was measured
while the 20260811–12 batch was landing, so no commit reproduces it. Publishing an
unreproducible gate figure without disclosing it is exactly the class of claim the
research ledger polices elsewhere, so the disclosure — not just the corrected number —
is the required change. The corrected figure is **3,943**, and it is now anchored to a
commit that can be checked out.

## Repository commit gate — executed

```bash
.parcel/bin/python scripts/ci_gate.py --tier commit
```

Executed fresh for this revision. Start `2026-08-13T00:59:04Z`, finish
`2026-08-13T01:02:15Z`; the gate's own banner stamp is `2026-08-13T01:02:15Z`. Exit
code 0. Verbatim result:

```text
CI GATE — tier=commit  (2026-08-13T01:02:15Z)
==============================================================================
[  PASS] HARD  ruff                       7 violation(s), baseline 7, new 0
[  PASS] HARD  hard-safety                nav frozen baseline nav-instruct-v1-baseline-v4-20260811T070536Z: collisions=0 false_arrival=0 | mutation panel clean: collisions=0 no_false_arrival=True | mutation panel freshness: committed fields reproduce live = True | follow-bench: 7 row(s), hard_collision_total all 0 = True | walk_with_me: 1/2 row(s) with hard_collision_total, all 0 = True
[  PASS] HARD  frozen-digest-sentinels    4 immutable manifest(s) byte-identical to pin
[  PASS] HARD  latency-tail-ledger        latest row latency-20260810T082415Z-4d83035f: 6 metric series within 1.2x tail ceiling (rows=5, window=5)
[  PASS] HARD  follow-bench-jerk-ratchet  latest shipped row follow-bench-v1-20260811023618Z-93eba090.json: 1.2187 <= 1.46244 (baseline 1.2187 x 1.2)
[  PASS] HARD  model-off-non-inferiority  23 passed in 0.50s
[  PASS] HARD  frozen-digest-integrity    6 passed, 1 warning in 0.33s
[  PASS] HARD  mutation-panel-freshness   2 passed, 3 warnings in 4.36s
[  PASS] HARD  latency-tail               6 passed, 2 warnings in 0.28s
[  PASS] HARD  default-suite              3943 passed, 9 skipped, 36 deselected, 5 warnings in 178.90s (0:02:58)
==============================================================================
RESULT: PASS — every hard gate green.
  elapsed 190.8s
```

Reconciliation with r1:

| Field | r1 | r2 (executed) | Note |
|---|---|---|---|
| default-suite | 3,889 passed | **3,943 passed** | r1 was a mid-batch transient (RC-6); +54 tests landed with the batch |
| skipped / deselected | 9 / 36 | 9 / 36 | unmoved |
| ruff | 7 baseline, 0 new | 7 baseline, 0 new | unmoved |
| elapsed | 149.8 s | 190.8 s | wall-clock only; this run shared the host with three concurrent cards |
| result | PASS | PASS | every hard gate green |

The 3,943 figure matches the number the Fable review independently recorded at
`7242660`, which is the agreement that makes it a baseline rather than another
transient.

### Worktree state during this run — disclosed

`HEAD` was `7242660`, but the worktree was **not clean**. Three other tranche-1 cards
(S-1, W0-A, W0-B) were executing concurrently, and at this session's opening snapshot
the tree carried at least 38 modified tracked files under `configs/`, `evals/`,
`scripts/`, `src/`, and `tests/`, plus untracked eval artifacts — all outside this
card's OWNS set, none of it authored here. So the honest description of this measurement
is **"commit gate at `7242660` plus concurrent in-flight tranche-1 edits"**, not "commit
gate at a pristine `7242660`". The gate returned PASS with the same suite count the
review recorded on the clean tree, which is evidence that the in-flight edits had not
moved the gate at the time of the run — it is not evidence that they never will. The
tranche's closing audit should re-run this gate on a clean tree at whatever commit the
tranche lands, and that run, not this one, is the Wave-0 exit figure.

## Design-contract spike

```bash
.parcel/bin/ruff check scrum/20260812/task_1/design_spike
.parcel/bin/python -m pytest -q scrum/20260812/task_1/design_spike/test_contracts.py
```

**Not executed for r2.** This was sequenced last on purpose — card S-1 is concurrently
rewriting `design_spike/**` under RC-1, so any count taken mid-edit would be a fiction
whichever way it came out. The shell became unavailable in this session before that
final run could be taken (see Limitations), so no r2 spike number is recorded here.

The r1 figures were `All checks passed!` and `43 passed in 0.10s`. Those are **stale by
construction** and must not be cited as current: RC-1 established that the 43-test suite
lets 12 of 20 invariant-killing mutants survive, and S-1's hardening changes both the
test count and the enforcement. The authoritative post-hardening numbers — new test
count, ruff status, and the 20/20 mutant kill count — are recorded in
`../task_2/S1_STATUS.md`. Cite that file, not this section, for spike status.

One r1 claim in this file is corrected regardless of the re-run: r1 said the 43 cases
"include a seeded 200-corruption boundary campaign". The accurate statement is **a
seeded campaign of 200 draws over 12 single-fault evidence-corruption classes**,
evidence-stream-only. The draw count was never the class count.

## Formatting/whitespace

```bash
git diff --check -- scrum/20260812/task_1
```

Not re-executed at close for the same reason as above — the shell became unavailable.
The r2 edits to these three files are Markdown prose with no trailing whitespace and no
conflict markers introduced; the check must be re-run by the tranche audit before this
card is accepted, and this line replaced with its executed output.

## What this establishes

- the repository's hard commit gate is green at `7242660` (with the caveat about the
  concurrent worktree above), and the reproducible suite figure is 3,943;
- the r1 3,889 figure is disclosed as a transient rather than silently replaced;
- the new task files introduce no new repository lint violation (`ruff`: 7 baseline,
  0 new).

## What this does not establish

- that current product code implements the spike contracts;
- anything at all about the spike's current state — see `../task_2/S1_STATUS.md`;
- that a pristine checkout of `7242660` produces this result (the run carried concurrent
  in-flight edits; see the disclosure above);
- process-level gateway deadlines or fault containment;
- DDS/Unitree Sport lease, command, feedback, or physical stop behavior;
- real camera/LiDAR localization, owner identity, terrain, or collision performance;
- actual USB audio capture/playback, AEC, through-air duplex, or audible latency;
- that the B5 arrival-honesty defect or the B6 collision-brake defect is closed — both
  are open, owner-gated, and the `pose-drift-arms:safety` nightly red stands;
- safety, reliability, cybersecurity, privacy, certification, or readiness for public
  streets.

Those claims require the cumulative evaluation ladder in
`PRODUCTION_COMPANION_PLAN.md`.

## Limitations of this record

After the commit-gate run completed at `01:02:15Z`, the shell stopped starting
processes: every command, down to the builtin `true`, returned exit 1 with empty stdout
and stderr, in foreground and background alike. An independent agent in a separate
session reproduced the same failure on the same commands, so it is a tool/shell-layer
outage rather than anything about this workspace. That blocked the spike run and the
final `git diff --check`.

The commit-gate result above is a real executed run captured before the outage, quoted
verbatim with its start/finish stamps. The unexecuted checks are marked unexecuted
rather than carried over from r1 — nothing in this file was hand-written into a result
block as though it had been run. The one fact recoverable without a shell:
`.git/refs/heads/main` reads `724266096f07dedb85e889bb0d8687062566e349`, consistent with
the `git rev-parse HEAD` taken before the outage, so the baseline had not moved. That is
a file read, not command output, and is labelled as such.
