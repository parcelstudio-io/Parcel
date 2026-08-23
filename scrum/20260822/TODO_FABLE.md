# TODO — the running log for 2026-08-22 · Fable (799cb356)

The owner asked that progress be logged here so a crash loses nothing. Newest
entry first. Every item names the file that is the evidence.

## 2026-08-23 · parcel-6c (session 31fcc2a0) — fifth resume, with the crash cause found

**06:1x EDT.** parcel-81 died at 05:38:42 with its five executors. Root
cause of ALL four deaths found in `journalctl -k`: kernel OOM kills from
`pytest -n auto` (192 workers on this host) × concurrent suites × a
recursion in XD-1's uncommitted `ci_gate.py` (`evaluate_default_suite` not
stubbed by `test_ci_gate.py::fast_commit_tier`). Full analysis, guards and
binding rules: `BATCHB_DISPATCH_FABLE_4a.md` § "parcel-6c take-over".
Guards: `~/.cache/parcel-guard/pytest_guard.sh` (cgroup 40 GB, `-n` ≤ 8,
flock) + a log-only memory monitor. Re-dispatching the five executors on
Opus under those rules; verifying each with a `claude` subagent; the
hardware design resumes at §4 after the executors are running.

**06:4x EDT.** `WAVE3_HW_DESIGN_FABLE.md` finished (§4 seam table ×27,
§5 nine decisions, §6 safety envelope, §7 box-day protocol + JetPack-5
branch, §8 unknowns register ×16, §9 wave-3 cards HW-1…HW-12 in two rails,
§10 nine falsified statements + the critic pass, 472 lines). Five Opus
executors running since 06:22 under the guard wrapper (guard.log shows
HY-1's first runs inside the 40 GB scope, rc=0). Verifier brief template
for the `claude` subagents at this session's scratchpad
`verifier_template.md`; verdicts will be appended to the record file's
"Verdicts (parcel-6c)" section.

**07:5x EDT — batch B verified, no crash.** All five executors
returned COMPLETE (06:44–07:20); five `claude` verifiers ran three lenses
each; every card is **ACCEPT-WITH-NOTES**, no HOLD anywhere; correction
passes applied and (for TRUTH-1) re-verified. Closed: FZ-1 (11/11), HY-1
(12/12), TRUTH-1 (8/9 — **R3 is an honest MISS, owner decision pending:
accept-the-miss recommended**), XD-1 (recursion closed by construction,
A1–A3; gate default capped at 16, measured at 8). ROAM-2 (T1 MISSED at a
genuine pre-registered ceiling; **owner must read** the travel-cost
finding: with coverage on the dog never leaves ~3 m of home) is in its
correction pass (3 × dynamic-city runs; one `noqa` removed). GATE-0b
dispatched 07:5x (gate runs only in its clean clone through the wrapper,
≤ 3 times). Host never below 228 GB available; every pytest run of every
agent is in `~/.cache/parcel-guard/guard.log`; zero exit-137. Verdict
records: `~/.cache/parcel-verify/<slug>/VERDICT.md`. Integrator close
(ruff census → one gate run in the tree through the wrapper → commit by
explicit path list → index regen → push) waits for GATE-0b and the
owner's word.

**09:15 EDT — batch B + GATE-0b closed; commit tier GREEN; awaiting
"commit and upload".** Six cards, six ACCEPT-WITH-NOTES, zero HOLD; gate
10/10 hard PASS in 92 s at 8 workers (`task_30/evidence_integrator_gate_
20260823T0912.json`). Commit path list (116) + message drafted; index
regen after the commit. Nothing crashed: ~14 agent runs, every pytest
through the cgroup wrapper, zero exit-137, host ≥ 228 GB free throughout.

**12:5x EDT — wave 3a dispatched (owner: "start executing on the
implementation now using opus and verify with fable").** Batch B + GATE-0b
+ the CLAUDE.md anti-crash rule are STAGED (118 paths), not committed —
"commit and upload" still owed. Cards cut from `WAVE3_HW_DESIGN_FABLE.md`
§9: HW-1 `task_35` py310-clean, HW-3 `task_36` mid360-band, HW-4 `task_37`
array-gateway, HW-6 `task_38` stopping-envelope, HW-8 `task_39`
box-day-runbook (board: wave-3 section). Record file:
`WAVE3_DISPATCH_FABLE_6c.md`. Wave 3b (HW-2, HW-5, HW-7) after 3a verifies.

**16:3x EDT — wave 3a: HW-1/HW-3/HW-6/HW-8 CLOSED (ACCEPT-WITH-NOTES
after HOLD→correction→re-verify for HW-3 and HW-8), HW-4 in its
correction pass (HOLD: the gateway must open DUPLEX — the XVF3800 works,
its capture is clocked off playback; `arecord` alone is not a valid
check). Design amended from the verdicts: §5.1 Orin product venv = uv
CPython 3.12 (py312 aarch64 lock delivered, 17 packages, zero missing);
§4 S1/§5.4 physical scan authority needs a typed scan-evidence source;
§5.6 duplex + the arm route; §7 every command re-spelled from the tree
(no `parcel-capture` console script; firmware is read in the app;
`observe` has no duration mode); one-axis = the 0.02–0.05 m/s band (the
0.10 triple was the retired 08-03 cap). Wave 3b dispatched: HW-2 go2-
backend, HW-5 physical-profile, HW-7 gate-on-aarch64, HW-FW orin-firewall;
HW-MIC after HW-4. Batch B still staged, uncommitted — "commit and
upload" owed. Host never below 228 GB; zero crashes.**

## 2026-08-23 · parcel-81 (session 23d56828) takes the whole close

**05:3x EDT.** Fresh session; `ListAgents` shows ZERO peers — parcel-8a
(799cb356) and parcel-dd (1cc5a3) are gone, so parcel-81 inherits BOTH roles:
batch-B re-dispatch + verification AND the integrator (gate, commit by path
list, push) AND `WAVE3_HW_DESIGN_FABLE.md`. Owner's instruction this morning:
finish the unfinished tasks, keep the record as I go.

**What the fourth crash was:** a full MACHINE REBOOT at 18:02:52 on 08-22
(system daemons' start times prove it). Everything died with it. The
runtime.py/config.py mtimes of 05:27 TODAY are Cursor restoring its editor
buffers on reopen (this session's own process started 05:27:40); content
attributes cleanly by markers — `config.py` carries TRUTH-1's pre-registered
R9 region (`planner_model` in `OVERLAY_INTRODUCIBLE_KEYS`), `runtime.py`
carries ROAM-2's coverage hunks. No orphan agent processes; zero
`parcel_robot` procs; owner stack still DOWN (hands-off);
`~/.cache/parcel-batchb/` has no stale locks.

**Census of batch B at takeover** (55 dirty paths on `e15e466`):

| Card | State found | Missing |
|---|---|---|
| XD-1 | DESIGN 17:51; STATUS through **D1 MET** (partition 9297+10=9307, no new markers) | D2–D7 rows |
| HY-1 | DESIGN; STATUS through **R10 (zero orphans — reaped by the reboot; census_resume3.txt)** | R1–R9 rows |
| FZ-1 | DESIGN; STATUS = header stub only | all 11 rows |
| TRUTH-1 | DESIGN 17:54; STATUS = header stub; R9 config.py region landed | all rows measured |
| ROAM-2 | DESIGN 17:56 only | PREREGISTRATION (baseline first!), all runs, STATUS |
| GATE-0b | nothing (HELD) | dispatch after XD-1 ACCEPT |

**Design study state:** research DONE (`~/.cache/parcel-fable-design/`:
`research.json` 112 KB + 3 lens `result.json`); `propose-mount-first/` is
EMPTY — the proposal phase died before writing anything. Proposals →
synthesis → doc are mine today.

**Today's order:** (1) log + record-file section (this entry); (2) re-dispatch
the five executors on Opus (fourth resume, from the tree as-is, same COMMON
brief + EXTRAS + today's census); (3) write the Wave-3 hardware design while
they run; (4) verify per card as status docs land (Fable, product-path
method); (5) GATE-0b after XD-1 ACCEPT; (6) integrator close: ruff census →
full gate (TMPDIR unset, tree quiescent) → commit by explicit path list →
regenerate CODEBASE_INDEX.md → push.

## State at 16:25 EDT (after the third crash)

**Landed and pushed today:** `21ea2fb` (week 1: GATE-0, TURN-1, MARK-1,
ROAM-1, CURIO-1, AIR-1 tools, ENV-1/1b, FINISH-1), `e15e466` (wave 2 batch A:
VENUE-1, OT-2, NM-1+ASK-1, DOOR-1, DUPLEX-1, CAP-1, GREEN-1). Records:
`AUDIT_WEEK1_FABLE.md`, `AUDIT_WAVE2_FABLE.md`, `WAVE2_DESIGN_FABLE.md`.

**Decision (owner, afternoon):** the target is the **Go2 EDU Plus with
Mid-360** (Orin NX 16 GB onboard). Recorded in `task_27/README.md` (banner)
and the board's Wave 3 row. Design goes BEFORE any hardware-facing
implementation, in `WAVE3_HW_DESIGN_FABLE.md` (not yet written — the design
study died three times before its research phase finished; being re-run in
smaller, journaled pieces so a crash keeps what finished).

**Batch B (XD-1, HY-1, FZ-1, TRUTH-1, ROAM-2; GATE-0b held until XD-1's
`ci_gate.py` lands):** executors died three times; partial work is in the
tree (59 dirty paths at `e15e466`; compiles; ruff 7 + debris). No status doc
exists for any of them yet. A second Fable (parcel-4a) had taken the
re-dispatch and also died. **16:28 — parcel-dd (a fresh Fable, session
1cc5a3) has taken batch B**: re-dispatch from the tree as-is with
`DESIGN.md` first, verify per card, report status-doc paths + verdicts to
799cb356, who gates and commits. Its record: `BATCHB_DISPATCH_FABLE_4a.md`
(parcel-dd appends its own section). Brief paths and per-card crash state
were handed over by message at 16:28.

**Host census 17:42 (parcel-dd, read-only):** ZERO `parcel_robot.sim`
processes alive — the five orphans from the morning sweep were reaped by a
crash, so HY-1's reap row becomes "none to reap, census recorded". **The
owner's live stack is DOWN** (`/tmp/parcel_sim.sock` absent, nothing on
`:8765`); hands-off stands regardless — no executor creates that socket.
`runtime.py` carries ROAM-2 hunks outside marked regions (mtime 17:38); the
ROAM-2 executor wraps them, and unmarked hunks are a HOLD at verification.
Shared files `tests/conftest.py` (XD-1 + HY-1) and `runtime.py` (TRUTH-1 +
ROAM-2) are serialized by a mkdir-lock under `~/.cache/parcel-batchb/`.

**Batch B dispatched by parcel-dd (17:58 XD-1/HY-1/FZ-1/TRUTH-1; 18:02
ROAM-2), all Opus**, each briefed from `BATCHB_DISPATCH_FABLE_4a.md` (parcel-dd's
take-over section at the bottom: census, lock rule, dispatch log) and writing
status docs incrementally. ROAM-2's arms differ by exactly one config line
(`roam: {coverage: false}` = baseline; policy input default-OFF so the
ROAM-1/MOVE-1 unit baselines are unmodified; baseline three runs first,
numbers appended to PREREGISTRATION.md before any coverage run).

**18:10 — research phase DONE** (3 lenses, 13 min; persisted at
`~/.cache/parcel-fable-design/research.json` + raw fetches in `hw-facts/`;
copy in the session scratch). Assumptions it overturned — the design must
carry these, not the earlier plan's: (1) the EDU dock is reported to ship
**JetPack 5.1.1 / Ubuntu 20.04 / Python 3.8**, with a community JetPack 6.2.1
update — "the Orin" is two possible targets, and our preflight's L4T table
fails closed on JetPack 5; (2) **no public Jetson wheel of onnxruntime-gpu at
the pinned ≥ 1.28** (known: 1.20/1.23 cp310 from Ultralytics / jetson-ai-lab);
(3) the **Mid-360 mounts on the Jetson dock's M8 air plug** (Ethernet +
power), not the head board; Livox's SDK is C++ only; (4) the head LiDAR is
probably the **L2** (360°×96°, 64k pts/s, 5.55 Hz, ENET UDP) but is reached
only via DDS `rt/utlidar/*` from the head board at 192.168.123.161; which
unit feeds `voxel_map` once a Mid-360 is fitted is unknown; (5) the
"wireless vector positioning tracking module" is probably the UWB owner fob
(`rt/uwbstate`) — unconfirmed; (6) dock ports: 1× USB 3.0 A, USB-C ×1–2, 2×
GbE, M8; payload power output unknown; (7) firmware on a 2026 unit unknown
(ADR 0002 needs ≥ 1.1.13; CVE-2026-27509 patch status unknown). Phase 2–3
(three proposals → judges) launched 18:12 against the file.

**Design study restarted in journaled pieces (16:26):** research phase
running as its own workflow (three lenses; each result persisted to
`~/.cache/parcel-fable-design/<lens>/result.json` and the workflow journal on
completion). Proposals → judges → synthesis → critic follow as separate
workflows so a crash keeps finished phases.

## Integrator checklist for the batch-B close (799cb356 runs this, nobody else)

1. parcel-dd's verdict per card, with the status-doc path; any HOLD → its
   correction pass, re-verified, before the gate.
2. `scripts/ci_gate.py` hunk attribution: XD-1's runner block and GATE-0b's
   marked region each resolve to exactly one card, no interleaved hunk.
3. `tests/conftest.py`: XD-1's and HY-1's regions disjoint; imports sane.
4. Tree-wide `ruff check .` collapses to exactly the 7 baseline fingerprints.
5. `git status` census vs the batch-B OWNS: nothing outside (the owner's
   `docs/`, `backlog/`, `README.md` never staged).
6. Full gate, `TMPDIR` unset, tree quiescent (no executor alive). The frozen
   nav baseline and follow-bench rows are the first thing to read.
7. Commit by explicit path list; regenerate `CODEBASE_INDEX.md` against the
   staged tree; push; post the close to every live peer.

## Remaining, in order

1. **Design study → `WAVE3_HW_DESIGN_FABLE.md`** — research (hardware facts
   with sources · codebase seams · prior intent) → three proposals → judges →
   synthesis → critic → my final doc + the wave-3 cards (`task_35+`). Then
   dispatch wave 3 on Opus, verify with Fable.
2. **Batch B close** — re-dispatch (resume from tree, `DESIGN.md` first),
   verify per card, GATE-0b after XD-1, full gate, commit by explicit list,
   push.
3. **Owner-gated queue (unchanged):** D455 or D435i; udev + `pyusb` +
   `doa: true`; voice enrollment; the TURN-1 recordings; AIR-1's ~1.3 h
   session; JST speaker; e-stop remote; B20 (Actions click); the spend limit.

## Crash log

* ~15:40 — process exit; five batch-B executors + the FINISH-1 re-check lost.
* ~16:10 — process exit; the five resumed executors + the design workflow lost.
* ~16:20 — process exit; the resumed design workflow lost (journal empty —
  no agent had finished); parcel-4a and parcel-bc gone.

## 2026-08-23 late — program pivot + ARCH-1 + tranche 1
- [x] Wave 3 integrated close: gate green run 3, committed c1b8405 + be86b78, pushed.
- [x] ARCH-1 reviewed: FABLE_VERDICT.md = ACCEPT_WITH_REQUIRED_CHANGES (+ post-landing addendum; X08/X16 closed, X12 decided co-located, X06/T12 reproduced).
- [x] Sim-vs-hardware answered for the owner: hardware is the path (see verdict/memory).
- [ ] Tranche 1 wave A: PROX-1 (task_2) + SENSE-1 (task_3) — Opus executing, Fable verify on landing.
- [ ] Tranche 1 wave B after A: AWARE-1 (task_4, runtime.py toucher) + GATE-1 (task_5).
- [ ] Owner decisions still open: HW-4 O1 through-air session, HW-8 runbook sign + Unitree ticket send, TRUTH-1 R3, ROAM-2 T1/H2.
