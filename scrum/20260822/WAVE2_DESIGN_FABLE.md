# Wave 2 — design and the TODO review behind it · Fable · 2026-08-22

**Owner's ask:** review the TODOs (the Opus suggestion included) against the
codebase as it actually is, design the next TODOs, have Opus implement and
Fable review. **Inputs read:** `INTEGRITY_GATES_TODO.md` (the Opus/integrator
corrective plan: IG-0…IG-4, DW-0…DW-5), `backlog/NEXT.md` (the 08-16 HLD
roadmap N23…N46 and the 08-22 worktree delta), `backlog/BLOCKED.md`
(B3…B28), `docs/ROBOT_ENGINEERING_EXECUTIVE_SUMMARY.md` §10–11 (gates A–G),
`PLAN_ASSESSMENT_FABLE.md` (the build order), and every week-1 status doc and
verification (`AUDIT_WEEK1_FABLE.md`). **Standing directive** (owner, 08-22):
a prototype companion that roams on command and talks full-duplex; prototype
not production; ask-over-refuse; prepare the codebase for a physical mount.

## 1. The Opus TODO, judged against the tree

| Suggestion | Verdict | Why |
|---|---|---|
| IG-1/IG-2 hermetic gate, containment, ruff pin, dataclass default | **done** — GATE-0 landed and verified; a fresh clone prints a 10-stage verdict | |
| ENV-1 capture-probe premise | **done** — ENV-1 + ENV-1b | |
| IG-3 thin eager barrels + startup-fatal admission of required capabilities | **adopt, narrowed → CAP-1** | the concrete defect is real (the 08-22 backlog delta: a YAML can disable the POI oracle while the process-global candidate source stays the oracle — "a startup defect, not a shadow mode"); week-1 added the same class twice (the supervisor allowlist rejected `TOOL_ROAM`; the overlay loader refused the `roam:` block). One card owns "what the product actually admits"; god-object decomposition is not prototype work |
| IG-4 hosted Actions proof | **owner-gated (B20)** — one click; the job will be red for the pre-existing 51 (GATE-0b sizes them) | |
| "Freeze feature promotion; Go2 HOLD until IG-4" | **reject as written** | the build order already gates the Go2 on three prototype tells at week 3; GATE-0 is green; add "clean clone green" as a fourth tell (PO-1) — costs nothing |
| "Mark task-16…27 as planned specifications" | no action — cards are specs until their status docs land; the board says so | |
| DW-0 atomic slices, never `git add .` | **already practice** — explicit path lists, audited commits | |
| DW-1 camera venue without MuJoCo; origin from the frame; mixed-venue refusal on the product path; recorded replay then live | **adopt → VENUE-1 exits** (sharper than the card's) | |
| DW-2 no VLM on the control thread (fatal test); published verdicts with identity/expiry; ASK through the broker without motion; replace k-consistency with a correctness judge | **adopt → NM-1 + ASK-1 slice** | the P1-D veto runs synchronously today; CURIO-1's `ask_about` feed now reads `verdict.candidate` and wants a real ASK |
| DW-3 typed owner identity; who may write durable facts; a production caller for consent; delete-derived proof | **adopt the memory-principal slice → OT-2** ; the calibrated-identity campaign is hardware-gated | |
| DW-4 envelope into both `GridPlannerConfig` sites; no import-time standoff constants; doorway scenarios; 0.70 m band non-default | **adopt → DOOR-1 exits** | |
| DW-5 physical estimation-control spine; SLAM benchmark; native gateway; commissioning | **defer** — hardware-gated and production-shaped; the pre-hardware slices worth doing are N23 (SensorFrameV2 + rosbag2 replay — gives VENUE-1 a recorded arm) and the gateway fake→substrate (N28), **after** the voice/roam loop feels alive | |
| N-roadmap (N29…N44) | serve only where a slice unblocks the prototype or the mount: N23, N28-substrate, N29 (= CAP-1), N37 (= TURN-1/MARK-1/DUPLEX-1), N45 (semantic arrival across classes — feeds ROAM/CURIO truthfulness) | |

## 2. What week 1 taught the design

* The dog now has the three verbs the owner asked for — roam on command,
  full-duplex with truthful interruption, unprompted remarks — each measured on
  the product path and each with a known next step (coverage, a duplex turn
  controller, a real ASK). Wave 2 finishes the loop rather than widening it.
* Four defects were in the "what does the product admit" class (supervisor
  allowlist, overlay keys, proactive-motion sets, the oracle default). That is
  CAP-1.
* The acoustic unknown is retired by tools, not by hardware: AIR-1's session
  (~1.3 h of owner time) decides the barge-in floor, the ch1 pin and the
  interrupt latency row; DUPLEX-1's defaults wait for it, its mechanism does
  not.
* The Go2 purchase input is now honest — and bimodal: seven product-path
  tethered 120 s runs give 1.30 / 3.10 / 6.48 / 6.54 / 6.47 / 6.56 / 6.57 m
  net in-block with 0 contacts (a 6.5 m out-and-back when the 10 m tether
  engages, a 1.3–3.4 m boxed wander when it does not); every run clears the
  ≥ 1.0 m tell. The next number that matters is *coverage* (ROAM-2), not
  distance.

## 3. Wave 2 — the cards (parallel, disjoint OWNS; Opus executes, Fable verifies)

| Card | Folder | Scope (one line) | Depends on |
|---|---|---|---|
| **VENUE-1** | `task_16/` | the runtime opens the physical eye without MuJoCo; origin from the frame; mixed-venue refusal seeded on the product path; recorded-bag arm (N23-lite) first, D455 live arm owner-gated | — |
| **OT-2** | `task_17/` | the running robot stops believing the owner at 1.0; typed identity state; **memory principal**: who may write durable owner facts, a production caller for consent, repeat ≠ confirm | — |
| **NM-1 + ASK-1** | `task_18/` | a correctness judge replaces k-consistency; **no VLM on the 10 Hz control thread** (fatal test); verdicts published with identity/expiry; `as_ask()` through the broker/conversation path granting no motion | — |
| **DOOR-1** | `task_19/` | the authoritative envelope into both `GridPlannerConfig` sites; no import-time standoffs; doorway scenarios at first-ODD widths; the 0.70 m band stays non-default | OT-2's envelope seam (read-only) |
| **DUPLEX-1** | `task_26/` | local turn controller (LISTEN/THINK/SPEAK/OVERLAP/YIELD); prerequisites now known: `interrupt_response: false` + tuned `silence_duration_ms`; seams: `note_owner_speech_stopped`, `interrupted_at`, the missing onset stamp (`browser_sink.py`), a browser-side duck (GainNode + `duck` control frame); RT-TURNS-1 export for AIR-1's two rows | MARK-1 + TURN-1 (landed) |
| **XD-1** | `task_14/` | the 52-second commit tier (xdist without divergence) — with GATE-0's lesson: no test writes under the repo | GATE-0 (landed) |
| **FZ-1** | `task_13/` | historical prompts render from frozen snapshots | — |
| **HY-1** | `task_15/` | no test leaks a simulator | — |
| **GATE-0b** | `task_30/` (new) | the clean clone's remaining 51: `results/*` carve-out (~5); skip-with-reason or nightly for the ~25 that need external roots; the V9 mode-bit decision; habitat 3; `--no-ledger` on `run_nav_instruct_v1.py`; B20 readiness | GATE-0 (landed) |
| **CAP-1** | `task_31/` (new) | what the product admits, in one place: supervisor allowlist ↔ broker tools cross-check; `OVERLAY_INTRODUCIBLE_KEYS`; proactive-motion sets; startup-fatal required capabilities; the POI-oracle/candidate-source startup defect | — |
| **TRUTH-1** | `task_32/` (new) | remedies and reports tell the truth: per-device SDK remedies (camera SDK is pip-installable here); `record --check` census; stale wheel claims; TURN-1's replay report `settle_s`/wall time; AIR-1 naming follow-through | — |
| **ROAM-2** | `task_33/` (new) | "explore" covers the room: a least-recently-seen bearing from P1-B's learned map feeds `PatrolPolicy`; coverage metric pre-registered; CURIO-1's remarks ride the idle checkpoints | ROAM-1 (landed) |

Not dispatched (hardware-gated, listed so nobody forgets): the mount-prep
wave when the D455 arrives (VENUE-1 live rows, P1-A/P1-C live rows, ENV-1's
ATTACHED arm, AIR-1's session), N23 full, N28 substrate.

## 4. Owner-gated queue (surface; never claim)

Raise the monthly spend limit (it killed four agents at 12:00); order the
D455; udev rule + `pyusb` + `doa: true`; enroll voice; quarantine synthetic
rows; the TURN-1 recordings (20 utterances, 10 min) and AIR-1's session
(~1.3 h; the mux path is its first hardware run); JST speaker; the Go2 EDU
Standard quote; B20 (enable Actions); the two one-line rulings (blur/mission;
retention); PO-1's fourth tell (clean clone green) acknowledged.

## 5. Method (unchanged, and it earned its cost today)

Executor per card on Opus with pre-registered rows and seeded RED; a
read-only three-lens workflow per card (seeds/weakening · product correctness
+ OWNS · product-path integration), every non-note finding attacked by a
skeptic who must reproduce it; one correction pass per card, re-verified; the
integrator gates, commits by explicit path list, pushes. Lesson written into
the verifier brief: **for every "cannot be tested here" claim, find the
engine or library that CAN model it** (gjs, fake streams, `transport_pair()`,
a patched `find_spec`) before accepting it.
