# QEV-1 · CLAUDE adjudication (Fable) · 2026-08-24/25

Basis: Sol's README + QUALITY_EVAL_REPORT (adopted at `d298842` with the
conversation layer, increments re-verified 13/13); my independent NAV-QUALITY
instrument (`research/20260824/nav-quality/RESULTS.md`, 875 lines, raw JSONs
beside it); and my own reproductions — the conversation overlay (179 tests
green under `fable-convo-verify`), the v4 minival (SR 0.20 / SPL 0.15326 /
frozen-rule 0.12 / 0 false arrivals / 0 collisions, episode digest identical
to the committed baseline), and the recovered voice→nav suite.

## Disposition: **ACCEPT — the NO-GO is right, and my instruments make it
stronger**

Sol's three decisions stand as written: **motion NO-GO**, **stationary
Stage-0 CONDITIONAL**, **PRE-MOUNT-CLOSE-1 next**. Nothing I measured
weakens any blocker; four findings below add to them.

## One reconciliation (recorded so the numbers stop fighting)

Sol's NAV_INSTRUCT rows (minival SR 0.24 with 1 false arrival; full 0.256
with 6) disagree with the committed-recipe instrument on both ends. The
committed recipe (`--budget-policy scaled-path-v1 --max-steps 200 --seed
20260804`, episode digest `4113607b…` = the frozen baseline's) measures
**minival SR 0.20, 0 false arrivals — twice: my executor and my own hands**
— and **full-matrix SR 0.20, exactly 1 false arrival**. Sol's flags are not
recorded in its report. Treatment: Sol's rows are directionally right (the
suite is red under every recipe tried); the committed-recipe numbers are the
instrument of record for baselines and gates.

## Four additions from the NAV-QUALITY instrument

1. **The frozen v4 baseline has REGRESSED and the gate cannot see it.**
   SR 0.24 → 0.20 (SPL −0.0400): one `object_relative` tier-A episode,
   *"sit next to the bench"* — grounded successfully, then the goal cell is
   blocked at the commissioned 1.0223 m inflation and released as
   unreachable. The fifth independent instrument to price A2's clearance
   on city geometry, and the first ON the frozen baseline corpus.
   `ci_gate.evaluate_hard_safety` reads only the pinned ledger fields
   (collisions / false arrivals), so SR regressions are invisible to the
   gate — a recorded gate blind spot, not anyone's cheat.
2. **The full 125-episode matrix had never been run, and it contains a
   false arrival the gate's pin cannot see**: *"walk onto the sidewalk"*,
   `arrived_verified` at **4.78 m outside the goal** (`system_arrival=True`,
   `scorer_arrival=False`). The false-arrival pin is computed on a
   25-episode subsample that lacks the episode. Same family/landmark as the
   two standing region-instance metamorphic xfails — that open question now
   has a false arrival attached. `object_relative` and `circle_owner` are
   **0/25 across the whole matrix**.
3. **`walk_with_me`'s committed provenance is a 2-episode scripted stub**
   (`n=2, smoke:true` — the only committed row carrying
   `hard_collision_total`, which the gate certifies from). Its first-ever
   headless run: 0/5 on nav-driven scripts, and the absent-target row goes
   silent rather than refusing — NAV-ACCEPT's R3 class again.
4. **A scoring misattribution**: `semantic_target_unreachable` after a
   successful `semantic_target_resolved` is counted `L2a_vocabulary` — the
   v4 histogram reports 7 vocabulary failures where 3 are real; the other 4
   are clearance. Anyone reading L2a as "the language model needs work"
   would be tuning the wrong subsystem.

## Voice→nav e2e — recovered, and what it now says

Root cause of the 17 standing setup errors: card R27's owner-store guard
(e5d4956) refusing the shipped config's relative `memory.path` under
pytest; commit-tier probes never covered this slow-marked file. The fix is
a tests-only monkeypatch pair (the sibling suites' exact idiom) — verified
by my own 12-minute run: the suite RUNS, both lamppost rows fail with A2's
clearance signature — and my two runs surface a THIRD consistent failure
the executor's did not: `test_go_to_the_sidewalk_grounds_plans_and_arrives`
fails 2/2 under pytest-randomly's shuffled order and passes under the
executor's `-p no:randomly` order. Order-sensitivity on exactly the
sidewalk/region-instance question the full-matrix false arrival names —
recorded as a fourth gate-integrity input for PRE-MOUNT-CLOSE-1 item 7,
not xfailed.
The two lamppost failures are behavioural findings, deliberately NOT
xfailed — they are PRE-MOUNT-CLOSE-1 inputs.

## PRE-MOUNT-CLOSE-1 — accepted with gate-integrity amendments

Sol's six items and ordering stand. Add, as item 7 (gate integrity, all
desktop-now): (a) the hard-safety nav row re-derives its pinned numbers
from a LIVE minival run — or the pin's provenance says "ledger, not live"
out loud; (b) the false-arrival pin covers the full matrix (114 s — it is
affordable) or names its subsample; (c) walk_with_me's stub row is labeled
`smoke` in the gate detail; (d) the L2a scoring fix; (e) the
`--scenes/--out` harness defect fix (my executor clobbered and byte-exactly
restored a tracked diagnostic — the trap is recorded in §5.2 of the
register). And per my NAV-ACCEPT verdict: driving the PRODUCT discontinuity
latch against the R4b scenario belongs on the same tranche's checklist —
Sol's item 2 says the same thing from the other side.

The 0.25/0.3 m/s treatment: agreed as Sol wrote it. Simulator sequence:
agreed; my sim-feasibility read for the owner rides the final report.
Does not prove: everything both documents already name; my reproductions
are desktop-sim and change nothing physical.
