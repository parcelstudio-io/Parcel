# SENSE-1 — hardware-mount sensing readiness

**Wave A · Tier B (input-health region: Tier S care) · Executor: Opus ·
Verifier: Fable.** Owner directive: prepare the prototype for hardware mount
to capture real sensor data. Every item below is a verified defect or gap
from the ARCH-1 review (FABLE_VERDICT.md, addendum) — this card makes the
sensing stack honest before a real Go2/Mid-360/D455 is attached.

## What to build

1. **Per-source receipt clocks (X04).** `backends/go2.py:~821` stamps pose
   and scan with one `received_at`. Carry each source's own host-receipt
   time (state's DDS receipt, scan's socket receipt) into the observation;
   never restamp a buffered sample with observe()'s clock. Keep
   `SimObservation` compatibility (additive fields / the ScanDatum you
   already own).
2. **Pose provenance seam (verdict blocking finding 4).** Pose today rides
   `evidence_origin()`'s unconditional SIMULATION stamp
   (`core/input_health.py:276-297`), so under `require_physical_inputs` a
   LIVE dog's pose latches `sim_fixture_forbidden`. Give the Go2 pose
   channel the same typed-source treatment scan got (mirror
   `CommissionedScanSource` — a declared-PHYSICAL pose source constructed
   only by `LiveGo2Sources`; replay/fixture still latches). Fail-closed
   directions must be preserved: absence → HOLD, replay → LATCH.
3. **Resolved-profile validation (X06, reproduced).** `deep_merge(base,
   go2_edu_plus)` inherits `battery.simulated_percent: 90.0`,
   `control.controller: simulator`, and desktop `enp3s0` under
   `unitree_sport.interface` + `robot.interface`. When
   `safety.require_physical_inputs: true`, refuse at load any
   base-inherited simulated battery / simulator controller / NIC value the
   profile did not explicitly set — with a typed error naming the key and
   the fix. Add explicit required/absent semantics for box-day keys
   (`backend.interface` stays deliberately unset → typed refusal at USE,
   not a fabricated default).
4. **Drain bound (A23 half).** Enforce `drain_budget_s` in the Livox drain:
   bounded wall time and frames even under a blocking or all-corrupt-flood
   socket; corrupt datagrams keep costing one datagram (`on_refusal`), never
   the tick.
5. **Capture preflight for mount day.** Extend `scripts/parcel_capture`
   preflight so one command reports, with typed absence, readiness of the
   three mount-day channels: Mid-360 UDP (socket + decoder), D455 (realsense
   path), XVF3800 (array device). No new frameworks — a readiness row per
   channel.

## OWNS
`src/parcel_robot/backends/go2.py`, `src/parcel_robot/core/input_health.py`
(marked region `# ---- CARD SENSE-1`), `src/parcel_robot/config.py` (marked
region, resolved-profile validation), `src/parcel_robot/lidar/livox_udp.py`,
`scripts/parcel_capture/preflight.py`, `configs/robot.go2_edu_plus.yaml`
(explicit values/absence markers), `tests/test_sense1_mount_readiness.py`,
this folder. Additions to existing hw2/hw3 test files allowed ONLY as new
test functions.

## MUST NOT TOUCH
`runtime.py`, `web_panel.py`, `navigation/`, `authority.py`, the scan
latch/identity-exemption semantics HW-2 landed (extend, don't rewrite),
other cards' fences, git.

## Testing policy (owner — binding)
Capability + hardware-integral error checks only: one test per behavior
above (receipt clocks distinct; live pose passes / replay latches; resolved
profile refuses each inherited value; drain bounded under flood; preflight
reports the three channels). No suites-of-combinations. Short STATUS md.

## Execution rules
Same as all cards: guard wrapper (`--label sense1`), `env -u TMPDIR`, no
`-n auto`, no `--tier`, no `noqa`, ruff clean, owner's stack/store
untouched, no commit/push. `git diff` = your OWNS only.
