# RRV-1 · ROBOT_READY_PLAN (Claude/Fable review) · 2026-08-24

**1 · Reviewed boundary.** `main` = `origin/main` = `61f97af` (clean tree);
the only task-3 overlay reviewed is Sol's `README.md`. My own later commits
(this file, the label fix below, and owner-directed dispatches) are recorded
in git and are NOT part of the reviewed state.

## 2 · Disposition: **ACCEPT_WITH_CORRECTIONS**

`DEPLOYABLE-MOTION-SEAM` is the right BUILD_NEXT — accepted. The corrections
are to the evidence matrix and sequencing context, not the selection.

## 3 · Evidence-ceiling matrix — corrections, with my own eyes on the code

Sol's A1–A9 table is substantially CORRECT. Three corrections/confirmations:

- **A1 (CONFIRMED, against my own verdict's wording):**
  `gateway/core.py::_stop_and_witness_locked` calls `_safe_stop_move` /
  `_safe_sample` SYNCHRONOUSLY in a retry/settle loop bounded only by
  `stop_timeout_s`, under the core-`RLock` naming convention; the M1-0 fault
  corpus seeds `stop_move_failure` (returns False) and `stop_move_raised`
  (raises) but has NO never-returns seed. A HUNG vendor `stop_move()`/`state()`
  therefore can hold the core lock; only `Move` has the isolated one-thread
  writer (`gateway/writer.py`). My A1 acceptance said "watchdog provably
  non-blocking" — that was proven against raising/failing vendors, not
  hanging ones. Sol's tranche item 4 is the fix and I own the over-credit.
  Also confirmed: `--sport vendor` refuses (`process.py:127`), the ONLY
  client is `bench_client.py` (nothing under `src/` imports `gateway.*`),
  and no packaging exists (no pyproject/setup anywhere in `gateway/`).
- **A2 (UPDATE, post-dates Sol's table):** the four A2-attributed reds now
  carry strict xfail markers with bisected cause and re-visit triggers
  (`LANE_A_CLOSE.md`, commit `61f97af`); the ≥0.80 shipped-profile corpus
  re-measure remains the gate and is dispatched TODAY as an eval (owner
  directive; see SOFTWARE_NOW-2).
- **Status drift (CONFIRMED):** `IMPLEMENTATION_PLAN.md` rows A1 "(running)"
  and A2 "(next)" are stale labels from the plan's creation; the close record
  is the delivery truth. Fixed as integrator bookkeeping in its own commit,
  outside this file, as the card requires.

## 4 · BUILD_NEXT: `DEPLOYABLE-MOTION-SEAM` (fake Sport only)

**Objective.** Close the installable process/production-client seam so the
real `UnitreeSportPort` joins a stable boundary at Gate 4, and close the
hung-vendor-I/O containment gap.

**Prerequisites.** None beyond `61f97af`. No robot, SDK, credential, Orin.

**OWNS.** `gateway/**` (new: packaging metadata, console entry point,
`client.py` — the production `MotionGatewayClient`; core changes ONLY for
hung-call containment), `tests/test_motion_seam.py` (new),
`deploy/orin/services/parcel-gateway.service` (parity edits only),
`scrum/20260824/task_3/SEAM_STATUS.md`.

**MUST NOT TOUCH.** `src/parcel_robot/**` (no runtime composition this
tranche), safety floors, A-card records, HLD, BOX_DAY, frozen evidence,
configs, the owner's stack/store.

**Work items.** (1) `pyproject.toml` for a `parcel-gateway` distribution,
console script matching the service file; CPython 3.10 floor. (2) The
production Unix `SOCK_SEQPACKET` client: connect/hello, acquire,
time-bounded command refresh, explicit stop, state/stop-report reads, close;
reconnect-DISARMED; typed results; NO raw-packet escape hatch. (3) Clean-env
install proof: build → fresh venv (no repo import) → service-style start /
kill / restart against fake Sport. (4) Hung-I/O containment: vendor
`state()`/`stop_move()` moved behind a bounded seam (the `writer.py`
one-thread pattern or equivalent) such that a NEVER-RETURNING call cannot
hold the core lock, freeze the watchdog, or delay an independent bounded
stop; `Move`'s existing isolation preserved. (5) Restart/reconnect stay
disarmed: new boot epoch, no auto-reacquire ever.

**Tests / seeded reds.** The acceptance contract in Sol's README §"Required
acceptance contract" items 1–9 is adopted VERBATIM as the definition of done,
including: hung-state and hung-stop seeds with anti-vacuity witnesses (the
fake call still blocked while the supervisor answers); seeded reds proving
the suite fails if reconnect auto-rearmed, a boot epoch were reused, the
client bypassed the gateway, or a hung vendor call wedged the watchdog; A1's
existing 135-test suite green unchanged (no weaker limit, no re-pin); three
consecutive guarded runs of the focused suite; evidence label `desktop/bench`.

**Rollback.** The tranche is additive (new files + bounded core seam); revert
= drop the new modules and the containment hunks; A1's suite pins the
pre-tranche behavior.

## 5 · Promotion crosswalk (Gates 2→6/M1)

Sol's crosswalk table is adopted UNCHANGED, with one addition per row:
evidence tier stays `desktop/bench` until the row's own physical witness
exists, and the accountable residual-risk owner is the human owner (Jae) at
every gate — software verdicts are necessary, never sufficient. No later row
may be declared from an earlier row's evidence.

## 6 · Classification

- **SOFTWARE_NOW:** (1) `DEPLOYABLE-MOTION-SEAM` as specified above.
  (2) **NAV-ACCEPT eval** (owner-directed this session): the SHIPPED
  commissioned configuration measured on the frozen NAV-CORE corpus, bar
  ≥0.80, harness-side wiring only, plus the `require_relocalization_margin`
  ON/OFF corpus rows — the recorded M1 gate and the four xfail STOPs'
  revisit trigger.
- **VENDOR_BLOCKER:** written JetPack/SDK2 entitlement, ports, power, mount,
  harness, firmware, support answers (unchanged from Sol's list).
- **BOX_DAY_ACCEPTANCE:** unchanged from Sol's list (inventory, clock
  map/extrinsics, real bags, mounted acoustics, stop envelope, soak, Follow
  identity trials).
- **OWNER_ACTION:** PO-1 independent E-stop decision; signed box-day runbook;
  robot delivery; owner + second-person scheduling; decision (b) compound
  instructions (gates CONNECTED-PLANNER only).
- **DEFER:** connected compound planner (unless (b) says binding), semantic
  ladder, self-initiated translation, UWB (measured reopen bar), custom
  gait/joints, outdoor/public, generalized autonomy.

**7 · Runbook/status drift to correct:** the two stale plan labels (fixed in
a separate commit this session); no other operator-facing drift found.

**8 · 0.25 vs 0.3 m/s:** 0.3 is the HLD's ODD CEILING; the commissioned
restricted regime stays 0.25. Compatible; no new regime is created and no
owner question is manufactured — raised only if 0.3 becomes a required
capability.

**9 · Risk/rollback.** Main risks: (a) the hung-I/O containment touches the
stop path — mitigated by adopting the proven `writer.py` isolation pattern,
by A1's untouched 135-test pin set, and by my verification re-running the
whole gateway suite; (b) packaging drift vs the service file — closed by the
parity test (contract item 2); (c) scope creep toward runtime composition —
excluded by MUST-NOT-TOUCH.

**10 · Does not prove.** Everything in Sol's closing list, verbatim: no
clean-target/Orin/vendor/physical/stop-distance/localization/Follow/
acoustic/thermal/autonomy claim. This plan selects and bounds the seam;
fake-Sport evidence never becomes robot-readiness.
