# Board — tranche PS-1: pre-physical-session capture stack

**Date:** 2026-08-13 · **Base:** `406f9d6` · **Author:** Fable
**Plan + verdict:** [PHYSICAL_SESSION_PLAN.md](PHYSICAL_SESSION_PLAN.md)
**Channel matrix:** [CHANNEL_MATRIX.md](CHANNEL_MATRIX.md)

**Confirmed hardware:** Go2 **EDU** · add-on Unitree **L2** LiDAR · RealSense
**D455** · Jetson **Orin NX**, recording **onboard**.

**The one sentence:** when the dog powers down, we hold a dataset that is still
trustworthy six months from now.

---

## Global rules (all cards)

1. **Nothing arms anything.** No card may create a publisher, a
   `ControlManager`, a lease, or a motion client. No card installs a vendor SDK
   into `.parcel/`. The absence of `unitree_sdk2py` from the Parcel venv is
   today's strongest motion guarantee — preserve it.
2. **MUST-NOT-TOUCH:** `src/parcel_robot/runtime.py`, `pose.py`,
   `navigation/**`, `route_memory/**`, `evals/**`, the B5/B6 owner-gated
   surfaces (K0 arrival predicate, `apply_collision_brake`, `collision.py`),
   frozen episode definitions and success rules, and the existing
   `src/parcel_robot/bags/` recorder/replayer **implementation**. You may
   *import and call* `bags/schema.py`; you may not edit it.
3. **Fail closed, always.** Unknown = absent. A channel that cannot be probed is
   `ABSENT`, never `ASSUMED_PRESENT`. A malformed timestamp is a refusal, never
   a default. Defaults must never be the permissive value.
4. **Two Pythons.** Everything under `src/parcel_robot/capture/` must be
   **stdlib-only and import-clean on Python 3.10 and 3.14** (Orin runs 3.10 via
   JetPack 6.2.x/Humble; the dev venv is 3.14.4). Everything under
   `scripts/parcel_capture/` may assume 3.10 + Humble but **must degrade to a
   clear refusal**, never a traceback, when a dependency is missing — it is
   developed on a box that has none of them.
5. **No unexecuted gates.** Every claim in a status doc is measured, with the
   command and its output. Estimates are labelled as estimates. `does_not_prove`
   is mandatory and non-empty.
6. **ci_gate green to close:** `.parcel/bin/python scripts/ci_gate.py --tier commit`.
7. **Do not** run `git commit`, `git stash`, or `git checkout`. Landing is the
   owner's call.
8. Write a status doc per card: `PS<letter>_STATUS.md` in this folder, with
   measured claims, a seeded-failure table, and `does_not_prove`.

---

## PS-A [opus] — channel matrix + `CaptureEnvelope`

**OWNS:** `src/parcel_robot/capture/` (new package: `__init__.py`,
`channels.py`, `envelope.py`), `tests/test_capture_envelope.py`.

The canonical, machine-readable enumeration of **every** channel in
[CHANNEL_MATRIX.md](CHANNEL_MATRIX.md) — **25 channel rows expanding to 28
channels, plus 11 payload-field rows** (count reconciled by PS-H; this line
previously said 15) — each channel carrying: stable channel id, human name,
source device, transport, address (ROS **and** raw-DDS `rt/` names for DDS
channels), message type, nominal rate, payload-clock kind, `frame_id`,
criticality, confidence marker, and presence status (`LIVE` /
`VERIFY_IN_SESSION` / `CONFIRM_ON_HAND` / `AWAITING_HARDWARE`).

`CaptureEnvelope` carries, per message: `channel_id`, **per-channel**
`sequence` (a counter *per channel*, never global — the `bags/recorder.py:94-98`
global-counter defect is the thing we are fixing), `source_timestamp_ns`
(nullable, from the device), `host_monotonic_ns`, `host_realtime_ns`,
`frame_id`, `origin: EvidenceOrigin` (reuse
`src/parcel_robot/evidence_origin.py` — do not redefine), `calibration_ref`,
and `health`.

**Gates**
- Stdlib-only leaf: an AST import-walk test **and** a subprocess `sys.modules`
  probe prove the package imports nothing outside stdlib +
  `parcel_robot.evidence_origin`. Precedent: that module's own leaf pin, and
  RM-1's `test_place_graph_imports_no_onnx_torch_or_navigation`.
- **Read-only pin:** a test asserting no symbol in the package references a
  publisher, `ControlManager`, `Move`, `set_target`, or any `control` module.
- Per-channel sequence: seeded test where channel A drops 3 messages while
  channel B is continuous ⇒ the gap is attributed **to A only**. Include the
  refutation case: the same interleaving under a *global* counter is provably
  undetectable (assert the old scheme misses it).
- Every envelope field round-trips to a JSON-safe dict and back, byte-stable.
- `origin` defaults to `UNKNOWN` and `UNKNOWN` is never accepted by a
  physical-channel constructor (fail closed).
- Import-clean under **both** 3.10 and 3.14 (state how you verified 3.10 —
  `ast`/`compile` check is acceptable; say so honestly).

---

## PS-B [opus] — MCAP recorder + `parcel.bag.v1` sidecar

**OWNS:** `scripts/parcel_capture/record.py`, `scripts/parcel_capture/sidecar.py`,
`tests/test_capture_sidecar.py`.

Record every live channel to **MCAP** (crash-safe, append-only, per-message
indexed), then emit a `parcel.bag.v1` **sidecar manifest** binding it into
Parcel's evidence world. Use the *existing* schema API —
`bags/schema.py:make_manifest` already accepts `source="hardware"`
(`schema.py:254`), `source_clock` of `"sensor"`/`"ros"` (`schema.py:130`), an
`extra` mapping (`schema.py:293,311-313`), and `default_frames()`
(`schema.py:113-127`). **Call it; do not edit it.**

`extra` must carry: `mcap_sha256`, per-channel message counts and observed
rates, the attestation digest from PS-D, the clock-map digest from PS-C, mount
geometry, and a non-empty `does_not_prove`.

**Gates**
- Digest binding: mutate one byte of the MCAP ⇒ sidecar verification **fails**
  (seeded test).
- Per-channel expected-count assertion: a channel delivering 90% of its nominal
  rate is reported as **degraded**, with the deficit quantified — not silently
  accepted.
- Crash safety: kill the recorder mid-write (SIGKILL) ⇒ the MCAP is still
  readable up to the last complete message, and the sidecar records the
  truncation **as truncation**, distinguishable from a sensor dropout. This is
  the single most important test on the card.
- Disk-full (`ENOSPC`/`EDQUOT`) mid-record ⇒ latched failure, record survives,
  degradation fails closed. Precedent: W0-B's `JOURNAL_WRITE_FAILED` lane.
- Refuses to start if free space < the PS-E budget for the requested duration.
- Runs, and refuses cleanly with an actionable message, when `mcap`/`rclpy` are
  absent (i.e. on this dev box).

---

## PS-C [opus] — clock discipline

**OWNS:** `scripts/parcel_capture/clockmap.py`, `tests/test_clockmap.py`.

**The highest-value card on the board.** `grep chrony|ntp|ptp|phc2sys|time.?sync`
across `src/ configs/ deploy/ scripts/` returns **zero hits**, and
`received_monotonic_ns` has a per-machine arbitrary epoch. Cross-device
timestamps are **permanently unrecoverable** unless offset triples are recorded
live. Every other defect today is fixable next week; this one is not.

Emit `ClockMapV1`: `(host_monotonic_ns, host_realtime_ns, device_source_ns,
round_trip_ns)` samples at ~1 Hz for the whole session, plus dense bursts at
start and end, per device (dog, D455, L2, Orin). Fit and report offset + drift
rate **with an uncertainty**, never a bare number.

**Gates**
- Seeded clock step (device jumps 500 ms mid-session) ⇒ detected and reported
  as a step, not smoothed into the drift fit.
- Seeded drift (40 ppm) ⇒ recovered within a stated tolerance; the report
  states residual uncertainty.
- NaN/inf/None in any clock field ⇒ refusal, never a default (fail-closed).
- Asymmetric round-trip ⇒ offset uncertainty **widens**; assert it does.
- Round-trips through the PS-B sidecar `extra` by digest.

---

## PS-D [opus] — preflight, discovery, attestation

**OWNS:** `scripts/parcel_capture/preflight.py`,
`scripts/parcel_capture/attest.py`, `tests/test_capture_preflight.py`.

Probe every channel in the PS-A matrix; emit `HardwareAttestationV1`: robot
edition, **firmware version read from the unit** (pin ≥ 1.1.13 per
`adr/0002-firmware-pin.md:11-13` — pre-pin firmware is treated as RCE-capable
on the LAN), **built-in LiDAR model read off the unit** (the repo is
self-contradictory: Unitree says L2, `P5_PROCUREMENT_BOM.md:35` says L1 —
resolve empirically), serials, NIC + DDS domain, D455 firmware + serial, L2
firmware, Orin JetPack version, free disk, and a per-channel
`PRESENT`/`ABSENT`/`DEGRADED` with the evidence for each.

**Gates**
- Fail-closed: a channel that times out is `ABSENT`. A probe that raises is
  `ABSENT`. There is no path to `PRESENT` without a received message.
- Firmware below pin ⇒ **hard refusal to proceed**, with the CVE citation in
  the message (seeded test with a spoofed low version).
- The attestation is digest-stable: same inputs ⇒ same digest; any field change
  ⇒ different digest.
- Runs to a useful, honest report on this dev box with **no hardware attached**
  (every channel `ABSENT`, exit non-zero, no traceback).
- Refuses to emit an attestation claiming `PHYSICAL` origin for any channel it
  did not actually receive a message from.

---

## PS-E [opus] — budget + synthetic-publisher rehearsal

**OWNS:** `scripts/parcel_capture/rehearse.py`, `scripts/parcel_capture/budget.py`,
`scrum/20260813/task_1/BANDWIDTH_BUDGET.md`, `tests/test_capture_rehearsal.py`.

**Nobody has done this arithmetic.** Produce the real numbers for the full
28-channel matrix and a decision table over D455 resolution/rate/format
(1280×720/30 RGB8+Z16 ≈132 MiB/s ≈464 GiB/h; 848×480 ≈58 MiB/s ≈205 GiB/h;
LiDAR <1 MiB/s), each row stating GiB/hour, whether the Orin's NVMe sustains
it (**measured**, not assumed), and the session-length bound. State the
power/thermal bound as an explicit **unknown to be measured**, not a guess.

Then the **rehearsal**: synthetic publishers for all 28 channels at nominal
rates, driving the real PS-A/B/C/D stack end-to-end on this dev box, with
injected faults — channel drop, rate degradation, clock step, disk full, mid-run
SIGKILL. **The first time this stack runs must not be on the dog.**

**Gates**
- Rehearsal runs green end-to-end on this host with no hardware and no ROS.
- Each injected fault is **detected and correctly classified** in the sidecar
  (a drop is not reported as a truncation; a truncation is not reported as a
  drop).
- Sustained-write measurement is real (state the command and the number); if
  the Orin is not reachable from here, measure on this host and label the
  number as **dev-host, to be re-measured on the Orin** — do not extrapolate
  silently.
- The budget doc names what it does not know.

---

## PS-F [opus] — Stage 0 run-sheet, mount geometry, safety brief

**OWNS:** `scrum/20260813/task_1/session/` (new), and the banner//pointer
updates in `scrum/20260805/task_1/P5_COMMISSIONING_CHECKLIST.md` and
`P5_PROCUREMENT_BOM.md`.

**Instantiate** `P5_COMMISSIONING_CHECKLIST.md:51-61` Stage 0 — do **not**
author a new checklist. Produce a run-sheet with the run-header template
pre-filled (`P5-DRY-20260813-…`), a named second/safety observer, and the
dual-e-stop + comms-loss re-verification the checklist requires at *every*
stage entry including Stage 0 (`:46-48`).

Add what Sol omitted and the checklist assumes: a **mount-geometry measurement
sheet** (tape-measured D455 and both LiDAR offsets + orientation to
`base_link`, to be filled *while the rig is assembled* — this is the one
quantity that is unrecoverable once the bracket is unbolted), a photograph
list, cable strain-relief and pinch-point checks, and the payload-security
check before the dog is allowed to stand.

Update the two P5 banners: they currently read "⛔ DO NOT PURCHASE YET" and
"DO NOT EXECUTE" (`BOM:8`, `CHECKLIST:7-9`). Hardware is on hand and the owner
has reversed the "hardware last" sequencing (`backlog/NEXT.md:28-39`). Replace
the banners with a pointer to [PHYSICAL_SESSION_PLAN.md](PHYSICAL_SESSION_PLAN.md)
as the superseding record. **Do not delete the history** — supersede it visibly.

**Gates**
- Every Stage-0 checkbox maps to either a PS-A..E artifact that produces its
  evidence, or an explicit operator action. No orphan checkboxes.
- The go/no-go has a **named failure branch**: if attestation or budget fails,
  the session degrades to *mount, measure, photograph, record nothing* — a
  legitimate outcome that costs nothing a later session must redo.
- No claim that anything was executed. This is a sheet to be filled **at** the
  session, and it must say so.

---

## Fable audit (me, after the cards)

Fresh `ci_gate --tier commit`; full diff-vs-OWNS attribution; adversarial
verification that (a) the capture package cannot publish, cannot import motion,
and cannot reach a vendor SDK; (b) per-channel drop detection actually
distinguishes drop / truncation / degradation under interleaving; (c) clock
recovery holds under step + drift + asymmetry; (d) every attestation path fails
closed; (e) no MUST-NOT-TOUCH surface moved. Refutation panels on any
blocking/major finding.
