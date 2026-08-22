# Task 5 — P0-E: gate tiers re-cut for the prototype

**Executor:** Claude Opus · **Verifier:** Fable · **Board:** `../TASK_BOARD.md`
(read its standing rules first — concurrent writers, Edit-only, git read-only).

## Why

The commit tier takes 5–6 minutes and reddens on doc edits (tonight's only red:
`tests/test_held_out_scene.py::test_only_the_allowlist_names_the_held_out_scene`
on `scrum/20260821/task_20/MOVE1_STATUS.md`). ~90 % of gate mass is
byte-identity and evidence ratchets. The owner directive is to loosen
production fail-safe *process* for a prototype while keeping the safety core.
Audit §8–§9.

## Deliverables

1. **Re-cut the commit tier** in `scripts/ci_gate.py` so it is the safety core
   plus the cheap truth checks:
   * **keep in commit:** `ruff`, `hard-safety`, `release-parity` +
     `release-parity-integrity`, `owner-store-isolation`, `tier-coverage`,
     `model-off-non-inferiority`, `assertion-evals` (it carries the e-stop
     pass^k), `default-suite`.
   * **move to nightly:** `frozen-digest-sentinels`, `frozen-digest-integrity`,
     `mutation-panel-freshness`, `latency-tail-ledger` + `latency-tail`,
     `follow-bench-jerk-ratchet`.
   Update the docstring at the top of `ci_gate.py` (it is the tier definition
   of record) and `tests/test_ci_gate.py` (which pins evaluator names via
   `inspect.getsource`, ~line 677). The tier-coverage gate must still prove
   no orphans/no overlap. **Do not** touch the evaluators' logic — only which
   tier runs them.
2. **Mark the anti-rot / drift tests nightly** with the existing `slow` marker:
   `tests/test_held_out_scene.py::test_only_the_allowlist_names_the_held_out_scene`
   (and its sibling bidirectional check), `tests/test_authority_no_literal_drift.py`.
   Also grant `scrum/20260821/task_20/MOVE1_STATUS.md` its allowlist seat with
   a reason (the doc catch-22 the 20260821 audit described) so the nightly
   stays green too.
3. **`pytest -n auto`** for `default-suite`: add `pytest-xdist` to the `dev`
   extra in `pyproject.toml` (P0-C edits another extra concurrently —
   Edit-only, your lines only), install it, and run the default suite under
   `-n auto` **once**. If it is xdist-clean (same pass/fail set as serial),
   switch the gate; if not, list the failing tests, keep serial, and say so.
   Tests that bind fixed sockets/ports (`/tmp/parcel_sim.sock`, :8765) are the
   likely culprits — note them for a follow-up, do not fix them here.
4. **Measure** the commit-tier wall-clock before and after
   (`scripts/ci_gate.py --tier commit`, once each; the "before" number can be
   tonight's 320 s default-suite / ~6 min total from the audit, cite it).
5. **Tests:** `tests/test_ci_gate.py` updated to the new tier split; a
   seeded-RED proof that moving a *kept* gate out of the commit tier reddens
   `tier-coverage` (the existing anti-deletion guard must survive your edit).

## OWNS

`scripts/ci_gate.py`, `scripts/ci_gate.sh`, `tests/test_ci_gate.py`,
`tests/test_held_out_scene.py`, `tests/test_authority_no_literal_drift.py`,
`pyproject.toml` (the `dev` extra only), `scripts/run_nightly.py` (only if the
nightly tier needs to list the moved gates), this folder.

## MUST NOT TOUCH

The gate evaluators' internals (`hard-safety`, `release-parity`,
`owner-store-isolation` logic), `evals/**`, `docs/CI.md` (another session is
editing `docs/**` right now — put the tier-of-record change in your status doc;
Fable reconciles docs after), `backlog/**`, `README.md`, `scrum/20260821/**`
other than reading, any `src/parcel_robot/**` file, the running sim/panel
processes. Never `git add`/`commit`.

## Gates

* `.parcel/bin/python -m pytest -q tests/test_ci_gate.py -x` green.
* `.parcel/bin/python scripts/ci_gate.py --tier commit` — run **once at the
  end**, after P0-A/B/C/D are likely done (check
  `ls scrum/20260822/task_*/P0*_STATUS.md`; if fewer than four exist, wait up
  to 30 minutes polling every 5, then run anyway and say which were present).
  Record the full table and wall-clock. A red caused by another card's
  in-flight edit is reported, not fixed.
* `.parcel/bin/ruff check scripts/ci_gate.py tests/test_ci_gate.py tests/test_held_out_scene.py` no new violations.

## Status doc

`P0E_STATUS.md`, per the board's register, with the before/after tier tables,
the xdist verdict, and the wall-clock numbers.
