# AU-F close — 2026-08-14 board, terminal record

**Auditor:** Fable · **Base:** `5fe0619` · **Board:**
[REVISED_BOARD.md](REVISED_BOARD.md) (ruling in
[AU-H_FABLE_REVIEW.md](AU-H_FABLE_REVIEW.md))
**Closing gate (my run, 2026-08-14T23:0xZ): `RESULT: PASS — every hard gate
green`, 5,347 passed** — fifth consecutive green central gate today across
five concurrent writers (S-1, S-2 ×2 executors, OR-1, FX-1/2) plus board docs.
`hard-safety collisions=0 false_arrival=0`; `frozen-digest-sentinels`
byte-identical; all of `scrum/20260813/**` byte-untouched.

## Readiness verdict (the one decision the board requires)

### `NOT_READY` for stationary Stage-0 capture — **`DEGRADE_MMP_ONLY` is authorized and open today.**

Not-ready is not a software statement — the software side closed green and
audited. It is an evidence statement, exactly as the board's hard-stop rules
define it: **zero commands have ever executed on the Orin** (distro unknown),
the Go2 firmware version is unread against the security pin, no topic has
been observed on our unit, and no sustained-write number exists for the real
record target. Plans and desktop fixtures cannot produce
`READY_FOR_STATIONARY_STAGE0`, and nothing here pretends otherwise.

**What is authorized now, per the revised board:**
- **H-3 — mount + measure — today.** Depends on nothing above: dog off or
  lying, no LAN, no ROS. Deliverables: filled MOUNT_GEOMETRY_SHEET, photo set,
  pre-torque LiDAR-FOV geometric check. Durable value on every branch.
- **H-1 — the five-minute Orin identity dump** — the single highest
  information-per-second action available; flips `NOT_READY` analysis from
  assumption to measurement and finalizes which S-2 sheet is operative.
- **H-2 — the rehearsal** — one command:
  `python3 -m scripts.parcel_capture.orin_rehearsal --evidence-dir <dir>`.
  A green bundle from the real Orin is the evidence `READY_FOR_STATIONARY_STAGE0`
  requires; the verdict authority stays here.

## What closed today, end to end

| Card | Result |
|---|---|
| S-1 | The CameraInfo/TF P0 negated: 31 recorded topics, GO-RECORD refusals proven on real writer bytes, sync fit bound into the real finalize, generated DISK_LEDGER (256 GiB ⇒ **41.4 min**, not 45) |
| S-2 (both executors) | Both-distro operator sheets, 22 rows each, one renderer; collision resolved — combined sheet demoted to a command-free index |
| OR-1 | The on-Orin test: 6 fail-closed phases, P5 executed end-to-end against real ROS 2 (help→argv→record→read-back→sidecar refusal), honest failing bundle on this desktop with zero tracebacks |
| AU-F inspection | 18 agents; **7/7 blocking-major upheld 2/2**, 13 minors; clean areas verified by execution |
| FX-1 / FX-2 | All upheld findings fixed with regressions proven to redden on the old code; one finding (F2) **partially refuted honestly** — its stated root cause was already fixed in-tree; the two take-losing defects that did reproduce (reusable `--output` with no folder-absent row; storage-config-onto-the-record-target prose) are fixed and proven against real `ros2` |

## Fixes verified at the auditor's own hand (not from reports)

- P4 zero-delivery + P5 exception-swallow regressions: **7 passed** (targeted run).
- One-source-of-argv-truth: **105 passed** across both addendum suites; the
  combined sheet contains **zero** command rows (ruled resolution implemented).
- Recursive no-arm pin: **76 passed** over the full capture stack.
- Central gate: **5,347 / 0** (line above).

## Inspection findings adjudication — permanent record

Upheld (all fixed in FX): sibling T10 order take-loss (worse than filed — the
committed argv was unusable as ordered); two contradictory argv truths
(WA-7); the self-healing byte-identity pin (the no-arm harness rewrote the
sheet mid-suite, healing hand-edits before the pin read the file); the
MANDATORY-first `--verify-help` traceback on a bare checkout (missing
`sys.path` bootstrap); P4 scoring only delivered streams (total sensor loss =
"PASS 100.0%"); P5 swallowing reconciliation exceptions into PASS; short-bag
GO-RECORD leniency (2 img/1 CI certified; downgraded MAJOR→MINOR 2/2).
Notable minors fixed alongside: calibration digest bound only the first
CameraInfo per topic (docstring corrected + drift finding added; the full-hash
branch measured and declined with reasons — a fourth full parse of a ~108 GiB
bag); bench-source guard now refuses command-shaped **message types**, not
just topic names; `classify_distro` fail-closed (`UNKNOWN` on failed read,
`NONE` only on a successful empty one).

Refuted at inspection (recorded so nobody re-litigates them): none this round —
7/7 upheld. The refutation work happened where it should: both refuters
independently re-executed every finding, and FX-1 refuted one finding's *root
cause* while confirming its *symptom*.

## Standing items out of today

- **Operator queue:** H-1 → H-2 on the Orin; H-3 mount today; firmware read
  from the app **before anything joins the robot LAN**.
- **Backlog:** PE-D / SG-E / IS-F deferred with unblock steps (see
  REVISED_BOARD); B5–B8 owner 2×2s unchanged; the two-dock rule still unmet
  (the single Orin must not be flashed).
- **Landing:** nothing committed today; the tree is gate-green on top of
  `5fe0619` — landing is the owner's call.

## What this close does not prove

Everything executed today ran on this desktop or in the Jazzy sandbox — Jazzy
is not Humble, and the Orin's distro is an assumption until H-1. The D455
launch-argument spellings, `camera_info` publication under the derived names,
every topic name and rate, and all fio/frame-count parsers meet reality for
the first time via OR-1 on the Orin. The no-arm guarantee remains defence in
depth (absent SDK + config refusal + recursive static/dynamic pin), stated as
such. Nothing today armed anything, stood the dog, or touched the robot LAN.
