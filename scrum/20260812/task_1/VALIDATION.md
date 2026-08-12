# Validation record

Run date: 2026-08-12  
Workspace: `/home/jaewoo-jang/Desktop/Projects/Parcel`  
Scope: design artifacts plus the repository's current dirty worktree

## Design-contract spike

```bash
.parcel/bin/ruff check scrum/20260812/task_1/design_spike
.parcel/bin/python -m pytest -q scrum/20260812/task_1/design_spike/test_contracts.py
```

Result:

```text
All checks passed!
43 passed in 0.10s
```

The 43 cases include a seeded 200-corruption boundary campaign. See the spike README
for its narrow proof and non-claims.

## Repository commit gate

```bash
.parcel/bin/python scripts/ci_gate.py --tier commit --json
```

Result:

```text
PASS — every hard gate green
ruff: 7 baseline violations, 0 new
hard-safety: pass
frozen-digest-sentinels: pass
latency-tail-ledger: pass
follow-bench-jerk-ratchet: pass
model-off-non-inferiority: 23 passed
frozen-digest-integrity: 6 passed
mutation-panel-freshness: 2 passed
latency-tail: 6 passed
default-suite: 3,889 passed, 9 skipped, 36 deselected
elapsed: 149.8 s
```

## Formatting/whitespace

```bash
git diff --check -- scrum/20260812/task_1
```

Result: pass, no output.

## What this establishes

- the isolated reference contracts express and pass the proposed authority rules;
- the new task files introduce no new repository lint violation;
- the current code and frozen simulator/eval gates still pass in this worktree.

## What this does not establish

- that current product code implements the spike contracts;
- process-level gateway deadlines or fault containment;
- DDS/Unitree Sport lease, command, feedback, or physical stop behavior;
- real camera/LiDAR localization, owner identity, terrain, or collision performance;
- actual USB audio capture/playback, AEC, through-air duplex, or audible latency;
- safety, reliability, cybersecurity, privacy, certification, or readiness for public
  streets.

Those claims require the cumulative evaluation ladder in
`PRODUCTION_COMPANION_PLAN.md`.
