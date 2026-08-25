# DEPLOYABLE-MOTION-SEAM · acceptance VERDICT (Fable) · 2026-08-24

Verification: my guard runs (label `fable-seam-verify`) — the full set
(motion-seam 62 incl. the three installed-artifact rows via the executor's
surviving clean venv, A1's byte-unchanged 134, fake-sport/protocol/process/
py310-clean neighbours, both DEC ratchets) = **290 passed, 1 deselected**;
one contended 650 s run red-flagged `test_out_of_order_feedback_stops_and_
latches`, and 3/3 isolated re-runs at 0.64 s prove it a load flake (two
overlapped guard runs + a live peer), not a regression — recorded, not
waived. Ruff clean on gateway/ + the test. Scope: exactly the card's OWNS
(git status carries three UNRELATED files attributed to Sol by timestamp/
transcript forensics with parcel-6c — left untouched, never staged). The
core.py containment diff, vendor_io.py, client.py, cli/notify, pyproject,
and all three service parity edits read line-by-line.

## Disposition: **ACCEPTED — evidence tier `desktop/bench`, and it says so**

- **The A1 hole is closed the right way**: `state()`/`stop_move()` now cross
  `BoundedCallLaneV1` — writer.py's proven one-thread pattern, two
  independent lanes so hung feedback cannot disable the stop; the vendor
  call runs with NO lock held; the lane never calls back into the core
  (non-vacuous against writer.py's callbacks); lock order stated in
  core.py's docstring and proven three ways. A hang classifies as the
  failure it deserves (`sport_state_unreadable` / `stop_rpc_completed=False`,
  latched) with distinct audit events, which is why A1's 135 pins hold
  byte-unchanged. Measured: hung state ⇒ bounded stop in 451 ms; hung stop
  ⇒ 201 ms; both hung ⇒ 451 ms; each with the still-blocked witness; lane
  overhead p99 0.033 ms; A1's soak re-run 3000/3000, 0 TTL violations.
- **The production client is the right shape**: 13 public names, no raw
  escape (anti-vacuity: the bench client HAS one); imports the wire contract
  and stdlib ONLY — structurally the socket is the only way out; disarmed is
  the resting state; `reconnect()` reports `armed=False` as a literal;
  `stop()` always ends authority; every transport error disarms and drops;
  the per-boot sequence fence is never rewound.
- **Packaging and parity are proven, not asserted**: the tests parse the
  unit file (ExecStart basename vs console script, args through the real
  parser, ExecStartPre path, Environment through the real resolver,
  WatchdogSec margin derived not restated); the clean-venv proof runs on
  real CPython 3.10.21 with repo non-importability asserted; readiness is
  EARNED (READY=1 after listening socket at 0600 + a bounded core probe;
  WATCHDOG=1 withheld when the probe fails — a wedged core silences pings
  instead of being papered over).
- **The three service edits are honest**: no default body (`vendor` named,
  refusing loudly today — nothing can ever start a fake body on the dog);
  the TODO replaced by the record of what produces the executable; the
  path-defaults comment. Sol's stop conditions all held; the four seeded
  reds fire through the same helpers the honest cases use.

Adjudications, mine: (1) the `gateway/seam/` SUBPACKAGE STANDS — the
non-recursive A1 module pin keeps its meaning for the core twelve, and
test_motion_seam re-applies every A1 rule recursively plus two stricter
ones; the pin's intent is extended, not routed around in substance; no
re-pin. (2) One design nuance recorded: a second `invoke()` caller waits
against the in-flight call's start with its OWN budget — benign at the two
fixed call sites, worth a comment if a third caller ever appears. (3) The
noqa count (0) verified by my ruff run.

Undone, correctly named: no runtime composition (nothing in the product
imports the client yet — the next tranche's work); `--sport vendor` still
refuses (no SDK); bench contract hashes (signed manifests are vendor/
box-day); sd_notify proven against a datagram socket, never systemd (Gate
2); the lane bounds the gateway and cannot cancel a hung vendor call; no
push-side stop report (A1 protocol question 4 — V2 wire work). Does not
prove: anything on-Orin, any physical stop, any robot-readiness — fake-Sport
evidence never becomes a robot claim.
