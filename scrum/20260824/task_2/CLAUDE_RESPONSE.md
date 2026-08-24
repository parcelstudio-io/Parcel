# RTP-2 · CLAUDE_RESPONSE — research exit and prototype freeze · Fable (parcel-fb) · 2026-08-24

Reviewed at: `main` = `origin/main` = `24378e6`; dirty overlay at read time =
untracked `scrum/20260824/task_1/README.md` and untracked
`scrum/20260824/task_2/` (this card and this response). No other tracked or
untracked changes. Verification for F2/F3/F4 was done by reading the exact
cited lines in this tree; nothing was executed, edited, dispatched,
committed or pushed in this task. Per the owner's standing instruction,
**no implementation is launched**; the corrected plan below is proposed for
approval, not started.

## Disposition: **ACCEPT_WITH_CORRECTIONS**

RTP-2 is an accurate basis for ending broad research and freezing the first
prototype design, subject to the corrections below — two of which are
corrections to **my own RTP-1**, which I verified and own.

## F1–F13

| F | disposition | evidence / correction |
|---|---|---|
| F1 | **CONFIRM** | All five retained conclusions stay binding (H2 closed; one-room supervised ODD; Sport owns gait; M1-0 next; the deferral list). No repository fact prevents research exit. |
| F2 | **CONFIRM — RTP-1's C8 refutation was wrong, and the error was mine.** | Receiver traced: `brain/executive.py:55-62` `VOICE_INTERRUPT_POLICY` has no `goal_amend` key and `"default": "overlap"`; `:902-911` `_voice_interrupt_action` maps an unknown reason to the default (no prefix of `goal_amend` matches `ambient/summons/recall/closed_intent_pause/explicit_directive`); `:571-585` resolves from that policy and the `requested` field never enters the branch — `InterruptDecision("overlap", (), reason)` is returned; `runtime.py:4072-4080` sends the request, ignores the returned decision, and sets `_amendment_pending = True` regardless. **An executive-only task keeps running during goal amendment.** RTP-1 traced the sender only — the exact "verifier must read the receiver" failure the project's own audit notes record. Fix shape (one focused change + regression, a BUILD_BLOCKER before any replanning card): add `AMEND_SUSPEND_REASON: "suspend"` to `VOICE_INTERRUPT_POLICY` (or an explicit mapping), and make `_apply_goal_amend` assert the returned decision affected the targeted tasks; regression = an executive-only running task + `goal_amend` ⇒ observe the task's state become `suspended` before the next step dispatch, and resume/cancel semantics on amendment commit/abandon. |
| F3 | **CONFIRM — RTP-1's "H7-proven" hazard row and my H7 VERDICT over-credited L4.** | `research/20260823/localization-delegation-bench/RESULTS.md:95-107`: the pre-registered teleport on `city_block` (6.3 m) never became DEGRADED or LOST; post-event ATE 8.66 m; `:109-127`: all three acceptance gates passed by 1–7 % margins, covariance moved 1.00→3.10 mm while the pose was 7 m wrong, and the local map absorbed the wrong place ("perfectly healthy tracking of the wrong place"); `teleport_far` was post-hoc and does not stand in for the verdict. Corrected conclusion: **localization can be confidently wrong; health + covariance + residual gates are insufficient after a discontinuity.** Fail-closed rule for the milestone: after any detected or *suspected* discontinuity (pickup, restart, power-cycle, correction near the gate margins), motion stays disarmed until localization is independently revalidated (e.g., re-observation of ≥ 2 known map landmarks at consistent bearings, or operator confirmation) — never on HEALTHY alone. NAV-CORE gains the wrong-place/false-healthy refuter (revision below). My H7 VERDICT.md gets the L4 correction in the post-approval reconciliation batch (research/** is out of this task's OWNS). |
| F4 | **CONFIRM.** | `scrum/20260822/task_44/HWMIC_STATUS.md:18-21,121-125`: the real-array run proved capture (250 × 1,920 B in 10.003 s) with **`frames_out 0`, `bytes_out 0`** — only digital silence reached the amplifier; the XVF3800 DAC → JST amp → CQRobot speaker path has never played audio, so live AEC through the intended echo-reference path is unproven. VOICE-GATE is corrected (revision below) to use that path, add a live second person, keep STOP always-local bypassing every gate, add barge-in/cancel latency, quantitative AEC attenuation, intent/critical-slot accuracy, first-word loss, endpoint latency, cost — and run arms sequentially with early stop. |
| F5 | **CONFIRM_WITH_CORRECTION.** | Correction of framing, not substance: the owner explicitly requires Follow in the offline floor ("all I can do is follow you"). Resolution: **the owner's floor is the target; the enable is gated.** Ship floor until the gate passes = local STOP + HOLD + the canned line. Follow ENABLE gate = the box-day identity/occlusion commissioning study (two-person crossing, occlusion/reacquisition, clothing/lighting, appearance vs appearance+UWB; ambiguity or identity loss ⇒ HOLD + the line). A failed appearance-only arm makes UWB a BOM decision — flagged as such. Loss-class policy adopted verbatim: cloud/Internet loss ⇒ only previously commissioned local behaviors, never partial compound plans; sensor/localizer/owner-track loss ⇒ HOLD; independent local STOP available in every rung. |
| F6 | **CONFIRM.** | The v2 design contradicted the re-scope; the grammar arms are **dropped entirely** (compound_grammar.py was never built — it is not zero-incremental-cost). Final topology: intent gate → hosted structured-output PlanSketch (explicit provider adapter) → local compile + fresh validation → governed execution \| typed refusal; offline/link-loss ⇒ one-step clarification ("tell me which step first") or the canned floor line. Early-stop condition: ONE full pass over the frozen corpus + the adversarial set meeting (schema+semantic validity ≥ 0.90, false physical plans ≤ 2 % and 0 on explicit negations, typed refusal on timeout/malformed, p95 ≤ 3 s, cost/100 instructions reported) — then stop, whatever the numbers show; a miss selects "clarify-fallback ships first", not another arm. No AGX/26B revival. |
| F7 | **CONFIRM.** | `24378e6` validated corpus *construction* (schema, uniqueness, 0 verbatim collisions). System evaluation — gate-only false opens AND end-to-end false physical plans through gate→planner→compiler→validator — remains, and is exactly the CONNECTED-PLANNER probe's job. Before the connected planner ships behind a flag: the probe's rows plus the F2 fix (replanning without executive suspension is the live race). |
| F8 | **CONFIRM.** | Surgical reconciliation list for `MILESTONE1_DESIGN_FABLE.md` (post-approval; does NOT block M1-0): §status line (H2/H9 closed, not pending); §2 delete the AGX-vs-grammar branch and the "decide on-body compute after H9" sentence (decision: Orin NX + hosted; AGX only if a box-day soak forces it); §2 ladder already carries the owner's floor — add the F5 loss-class split and the Follow enable gate; §4.5 add the false-healthy rule from F3; §5 reorder the card table to F12's lanes; §7 acceptance gains the C8 regression and the false-healthy refuter; add the deployment-boundary paragraph (product 3.12 / vendor 3.10 processes, typed IPC, systemd, boot-disarmed, credential isolation, restart-disarmed, rollback; final versions await the vendor's written JetPack/SDK answers). Nothing in the list contradicts an authority boundary, so M1-0's contract work is safe to start when the owner authorizes implementation. |
| F9 | **CONFIRM** — corrected table below. |
| F10 | **CONFIRM.** | Acknowledged: `b2fe05f` bundled the RTP-1 review with research/config/log changes — my program-owner and reviewer roles mixed in one commit; `edb78c0`/`24378e6` continued program work while task-scoped. Rule adopted: review outputs commit alone, program changes commit separately and say which role authored them; the untracked `task_1/README.md` (Sol's) stays untracked until Sol or the owner stages it. Canonical artifacts: per hypothesis exactly DESIGN.md, RESULTS.md (≤ 250 lines), VERDICT.md, one compact results JSON; everything else (raw rows, live logs) belongs in session scratch or an ignored `logs/` (the H2 ignore extends to `research/**/logs/` at reconciliation). WIP limit adopted: one physical-integration lane + one disjoint decision-blocking study; corrections batch at milestone boundaries. |
| F11 | **CONFIRM.** | VENDOR_BLOCKER (written replies pending; do not re-send): Orin module/storage/JetPack/SDK2 entitlement, Mid-360 mount/harness, battery/charger/controller, free ports/power, sensor/audio access, US cellular/external 5G, mounting CAD/warranty, packing list, lead time, returns. BOX_DAY_ACCEPTANCE packets exactly as F11 lists them (soak, clockmap/extrinsics, real LIO bags incl. feature-poor/restart/wrong-place, FOV/occlusion/CoG/vibration/cables/antennas, 5G behavior; stop envelope; mounted AEC/ego-noise/STOP; Follow identity gate if Follow stays). Neither list is desk research. |
| F12 | **CONFIRM.** | Parallel order accepted (below). No interface decision makes M1-0 unsafe to start: the gateway contract (`bridge/protocol.py` V1) is navigator-agnostic; NAV-CORE only decides what sits behind it. Per the owner's current instruction, **Lane A is written but NOT launched.** |
| F13 | **CONFIRM.** | Locomotion research stays out. If the owner re-declares low-level locomotion as a primary objective, written vendor low-level access/control-rate/warranty confirmation becomes a procurement decision blocker. |

## The only remaining pre-freeze studies (with early stops)

| study | decision | early stop |
|---|---|---|
| **NAV-CORE v2** | retain / simplify / delegate known-place navigation | stops at the decision. Revision over v1: add the **false-healthy refuter** — one wrong-place/relocalization episode per seed (kidnap into an ambiguous corridor): the bar is *no motion resumes on HEALTHY alone after a discontinuity*; independent revalidation (≥ 2 known-landmark re-observations or operator ack) must precede re-arm; a false arrival here fails the arm outright. If both Parcel arms fail: one small, measured Nav2-class interface/lifecycle spike (time-boxed), then decide. |
| **VOICE-GATE v2** | owner-ID / wake phrase / push-to-talk / restricted listening | sequential arms, stop at the first policy meeting V1–V5. Revision over v1: playback through the **XVF3800 DAC → JST amp → CQRobot speaker** (the echo-reference path; desk speaker only as a labeled control), live second person, STOP on an explicit always-local path bypassing identity/wake gates, plus barge-in/cancel latency, quantitative AEC attenuation, intent/critical-slot accuracy, first-word loss, endpoint latency, cost rows. On-robot motor/gait acoustics stay box-day. |
| **CONNECTED-PLANNER probe** | does the hosted structured PlanSketch path meet the F6 bars | one full pass over frozen corpus + adversarial set, ≤ $1.50, then stop. Blocks connected compound execution only — never M1-0. |

Removed from pre-freeze: everything else. The C8 fix + regression is a
**build item**, not a study.

## Blocker assignments
- **DESIGN_FREEZE_BLOCKER:** NAV-CORE v2; VOICE-GATE v2.
- **BUILD_BLOCKER:** the C8 executive-suspension fix + focused regression
  (before any replanning/connected-compound card); the false-healthy
  re-arm rule wired wherever motion re-arms after a localization
  discontinuity.
- **VENDOR_BLOCKER:** the written procurement answers (F11 list).
- **BOX_DAY_ACCEPTANCE:** compute/power/mount soak packet; real-bag LIO +
  wrong-place commissioning; stop envelope; mounted acoustics; Follow
  identity/UWB gate.
- **DEFER:** full H8 exploration/OCR; outdoor/crowds/stairs/weather;
  generalized perception; continual memory beyond the four H5 defect
  fixes; AGX/26B and offline grammar; trainable initiative; custom
  gait/joint/locomotion-RL.

## Offline / loss-class policy (explicit)
- **Cloud/Internet lost:** say the canned line; retain only previously
  commissioned local behaviors — STOP (always), HOLD, and Follow *only
  after its enable gate has passed*; never begin or continue a compound
  plan; one-step clarification is permitted where a hosted planner call
  would have been made.
- **Sensor / localizer / owner-track lost:** HOLD (and say so). A
  localization discontinuity additionally requires independent
  revalidation before re-arm (F3 rule).
- **Every rung:** independent local STOP (spoken hotword on the always-
  local path, panel, and the operator's physical remote).

## Stage / hazard closure (F9 — with residual-risk owners)

| stage / hazard | positive witness | refuter / fault injection | fail state | stop/continue bar | tier | residual owner | blocks |
|---|---|---|---|---|---|---|---|
| gateway/governor | fake-Sport bench suite green; exact-zero on kill/stale/epoch | seeded fault inventory (`bridge/fixtures`) | exact-zero, restart-disarmed | any non-zero on loss ⇒ stop | bench → Orin | Fable (design) / owner (arm) | first pulse |
| independent stop | measured latency + distance with remote | mid-motion stop injection | physical stop | latency/distance recorded ⇒ continue | on-robot | owner/operator | first pulse |
| stamped observation | join shows 3 clocks, provenance, health | stale/frozen stream per channel | LATCHED_STOP | staleness caught ≤ bound ⇒ continue | on-robot | Opus (build) / Fable (verify) | first translation |
| real LIO health | ATE/RPE on bags; DEGRADED/LOST on faults | dropout, restart, **wrong-place kidnap** | HOLD; re-arm only after independent revalidation | false-healthy reproduced ⇒ stop until rule wired | bags → on-robot | Fable | first translation |
| supervised NavigateTo | ≥ 10 leashed runs, 0 contacts, 0 false arrivals | moved obstacle; goal removed; dropout mid-leg | typed honest failure | any contact/false arrival ⇒ stop | on-robot | owner/operator | first autonomous mission |
| Follow identity | crossing/occlusion study rows | second person swap; occlusion | HOLD + canned line | any identity swap ⇒ Follow stays disabled | on-robot | owner (BOM: UWB) | Follow enable |
| transcript→task | intent gate + validator rows (probe) | adversarial set; malformed planner JSON | typed refusal | false physical plan > 2 % ⇒ gate stays restrictive | replay + live | Fable | connected compounds |
| voice activation | VOICE-GATE v2 winning arm rows | TV, second person, self-TTS | ignore + log | V1–V5 miss ⇒ push-to-talk ships | desk array → mounted | Fable | first translation |
| continuous body intent | H4 rows + per-primitive commissioning | e-stop mid-gesture; envelope push | HOLD | any balance disturbance ⇒ primitive stays off | sim → on-robot | Opus/owner | first autonomous mission |
| memory/learning | H5 fixes + governance suite + independent probes | revocation resurrection; distractor world queries | learning stays off | any revoked-fact leak ⇒ off | replay | Fable | post-M1 enable |
| battery/thermal/mount | soak packet rows | GPU/network pressure during soak | sit + announce | throttling/deadline misses ⇒ topology revisit | on-robot | owner | first translation |
| private data | store isolation + consent suites; no audio upload in silence | purpose-violation probes | refuse | any leak ⇒ stop | desktop | Fable | first pulse |

## Build order (accepted; NOT launched — owner's hold stands)
Lane A (build, when authorized): M1-0 gateway/governor → independent stop →
stamped observation → real LIO boundary → supervised STOP/HOLD/one
known-place NavigateTo. Lane B (bounded decisions, when authorized):
NAV-CORE v2; VOICE-GATE v2; CONNECTED-PLANNER probe. Box day: the F11
packets. The C8 fix rides the first Lane-A card that touches replanning or,
at latest, precedes the CONNECTED-PLANNER flag-ship.

## Milestone reconciliation (surgical, post-approval)
Exactly the F8 list above, plus: H7 VERDICT L4 correction; VOICE-GATE and
NAV-CORE design revisions (v2 deltas above); H9 folder gains a one-line
supersession note (grammar arms dropped); `research/**/logs/` ignore
extended. All documentation-only; none blocks M1-0.

## Does not prove
This response corrects the record and selects the shortest honest route; it
proves nothing physical. In particular it does NOT prove: that the executive
suspends on goal amendment (it provably does not, until the C8 fix lands and
its regression observes task state); that any localizer detects a kidnap
(one pre-registered case provably stayed HEALTHY while 7 m wrong); that the
XVF3800 speaker path plays audio (measured `frames_out 0` to date); that
Follow is safe around two people; or that any research seam is reachable
from `RobotRuntime` (none is). Every one of those is a gate above, owned and
scheduled — not an assumption.

---

## Addendum — consolidated corrections from Sol's RTP-2 follow-up (2026-08-24, ~03:2x)

All seven corrections are ACCEPTED; the four with new repository citations
were re-verified at the cited lines before acceptance. This addendum
supersedes the corresponding items in the body above.

**A1 · C8 fix respecified (supersedes the F2 fix shape).** A policy mapping
plus a Python assertion suspends a *record*, not a robot. The corrected fix:
`_apply_goal_amend` (runtime.py:4053-4085) must (i) capture and inspect every
returned `InterruptDecision`; (ii) **fail closed** — if any targeted task
does not report `suspend`/`cancel_now`, the amendment is refused and the
prior goal stands untouched; (iii) reconcile the active semantic dispatch:
after suspension, verify via the arbiter that no intent sourced from the
suspended task remains active, and emit an explicit HOLD for the amendment
window; (iv) the regression observes the **command/trajectory stream** (the
executor-side dispatch log and `ControlManager.set_target` calls), asserting
zero further commands from the suspended task after the amend — task-state
inspection alone is insufficient. Remains a BUILD_BLOCKER before any
replanning or connected-compound card.

**A2 · Always-local spoken STOP is a build gate, not a current capability.**
Verified: `realtime/lane.py:47-53` — "A spoken 'stop' during a hosted session
is transcribed in the cloud. It is supplemental." The body's loss-policy row
claiming spoken STOP "on the always-local path" in every rung described a
design intent, not the tree. Corrected: today's cloud-independent stops are
the panel STOP, the operator remote, and the local watchdogs — only those may
be claimed. **New build gate before first translation: STOP-LOCAL** — a
local hotword path (Silero + keyword spot on the always-on local lane, or the
XVF3800's on-device capability if the vendor confirms one) proven with the
mounted mic at ≥ 0.99 recall / measured false-trigger rate, wired to the same
latched stop as the panel. VOICE-GATE v2 measures it; the gate blocks
translation, not pulse.

**A3 · Follow needs build items before its commissioning gate is runnable.**
Verified: the OT-2 owner tracker is "built unconditionally and inert by
default" (runtime.py:2587-2596) and `install_owner_tracker` has **no product
caller** (grep: only a docstring mention and a comment at :13457); `uwb/` is
explicitly a sim stand-in ("No real UWB hardware", uwb/__init__.py:1-5).
Corrected: before the box-day Follow identity gate can even run, M1 needs a
FOLLOW-COMPOSE build card: production tracker installation on the camera
venue (encoder + gallery resolution → `install_owner_tracker`), synchronized
pixel/range association, the real `rt/uwbstate` driver decision (or UWB
explicitly out of BOM), and physical obstacle/person avoidance parameters for
follow at ODD speed. Until FOLLOW-COMPOSE lands and the gate passes, the
shipped offline floor remains STOP + HOLD + the canned line.

**A4 · Localization re-arm rule tightened (supersedes the F3 remedy).**
"Two landmarks" or a generic operator acknowledgment can both be satisfied
while tracking the wrong place (H7's aliased-corridor mechanism). Corrected
rule: after pickup, restart, power-cycle, or any suspected discontinuity,
motion **latches disarmed**; re-arm requires either (a) globally
discriminative geometric evidence — a relocalization match whose second-best
candidate is worse by a pre-registered margin across the whole map, not a
local residual gate — or (b) an explicit operator pose-reset-and-validation
transaction (operator states the pose, the system verifies scan agreement,
both are journaled). HEALTHY + covariance never re-arms anything.

**A5 · Safety table repairs.** (i) Independent stop bar becomes quantitative:
at ODD speed 0.3 m/s, measured stop ≤ **0.5 m and ≤ 500 ms** end-to-end
(provisional numbers, to be replaced by the derived envelope from
`bridge/timing.py` at commissioning — whichever is stricter; "recorded" alone
passes nothing). (ii) New rows: **initiative** (self-initiated behavior:
positive witness = attribution log + radius/quiet compliance; refuter =
initiation during quiet window/e-stop; fail = initiative disabled; blocks
first autonomous mission); **drop-off/glass** (witness = ODD survey +
taped-glass checklist per session; refuter = deliberate near-edge approach in
commissioning cage; fail = ODD amendment; blocks first translation);
**connectivity loss, split into three rows** — cloud loss (floor behaviors
only), LAN/desk loss (same + no deliberation), sensor loss (HOLD) — each with
its own witness and refuter. (iii) **Residual-risk owners are accountable
humans**: every row's residual owner becomes the project owner (Jae) as
operator/owner, with the engineering-lead role explicitly Jae until
delegated to a named person; Claude sessions (Fable/Opus) appear only as
*executors of verification work*, never as risk owners. The body's table is
read with these substitutions; the milestone patch carries the full corrected
table.

**A6 · VOICE-GATE v2 thresholds and missing arms.** Added bars: AEC
attenuation ≥ **20 dB** through the XVF3800→CQRobot path; barge-in acoustic
stop p50 ≤ **0.52 s** (measured baseline 0.72 s — the bar is the acoustic
plan's, restated); cancel p95 ≤ **700 ms** interim (the DUPLEX-1 floor
evidence) with 450 ms as the target bar; critical-slot accuracy ≥ **0.95**
(place names, STOP, owner name); cost ≤ **$0.50/day** at the corpus duty
cycle. Added stimuli/arms: **owner-recording replay** (spoof row — measured
acceptance rate reported; if TitaNet accepts replays, the policy decision
"accepted indoor risk vs wake-phrase-AND-identity" is made explicitly, not
silently); **limited wind** (fan-at-window proxy); and a defined
**restricted-listening arm** (mic open only during person-present windows
from the camera/proximity signal, as the fourth policy candidate).

**A7 · Wording and versions.** H9 is **dropped/superseded** (offline arms)
with the CONNECTED-PLANNER acceptance probe **pending** — not "closed"; the
research index will say exactly that in the reconciliation batch. Python
versions: `requires-python = ">=3.10"` with core Jetson operation on 3.10
already true and tested (pyproject.toml:9-12) — the deployment paragraph's
"product 3.12" is corrected to: **per-process interpreter chosen by its
dependency set; final pins wait for the vendor's written JetPack answer.**

**Recorded recommendation (Sol's, endorsed):** end broad research now;
authorize M1-0 gateway/governor contract work; run NAV-CORE v2 then
VOICE-GATE v2 sequentially; CONNECTED-PLANNER afterward; one consolidated
addendum (this document); surgical milestone update; then software
architecture freeze — with electrical/mechanical/physical-safety freeze
pending vendor answers and box-day commissioning. **Implementation remains
on the owner's explicit hold; nothing is dispatched by this addendum.**

---

## Addendum 2 — final corrections before freeze (Sol's third-round feedback, accepted)

**A8 · C8 is transactional (supersedes A1's acceptance set).** Goal
amendment accepts **suspend only** — `cancel_now` destroys the prior goal
and is excluded from the acceptable decision set. Multi-task semantics:
the suspension is **atomic or rolled back** — suspend all targeted tasks;
on any failure, resume every already-suspended task (journaled rollback,
each step written before taken), refuse the amendment, and remain in HOLD
until the rollback completes. `_amendment_pending` stays **False** until
every targeted controller is verified quiescent (no active intent sourced
from any targeted task, confirmed at the arbiter). Partial failure never
leaves the system half-amended: HOLD + refusal + rollback, in that order.
The regression drives the multi-task case (two executive tasks, second
suspension forced to fail) and asserts the rollback journal, the resumed
first task, and zero emitted commands during the window.

**A9 · Spoken-STOP and VOICE-GATE pass rule (supersedes A6's bars).**
STOP-LOCAL acceptance is a **tail** bar: end-to-end (end of the spoken
hotword → latched stop command) **p95 ≤ 800 ms AND a finite-sample upper
bound** — all of n ≥ 60 trials within 1.0 s (one-sided 95 % bound on the
tail), with the physical stop then bounded by the A5 envelope; plus a
false-trigger bar: ≤ 1 false STOP per 24 h of ambient/TV/self-speech tape
(false stops are safe but erode trust and mask real ones). p50 is reported,
never the bar. **One consolidated VOICE-GATE pass rule**: a policy arm
passes only if EVERY row in the unified table passes — V1–V5 (body),
AEC ≥ 20 dB, barge-in stop p50 ≤ 0.52 s with p95 reported against the
envelope, cancel p95 ≤ 700 ms, critical-slot ≥ 0.95, first-word loss ≤ 2 %,
endpoint p50 ≤ 0.8 s, STOP-LOCAL tail bar, cost ≤ $0.50/day — no partial
credit across arms. Honesty row added: **wake phrase + identity does not
defeat a replay that contains both** — the replay row therefore reports
acceptance under every arm, and the shipped policy documents replay as an
explicitly accepted indoor risk (or defers to a liveness mechanism as
post-M1 work); no arm may claim replay immunity.

**A10 · Discontinuity detection enumerated (completes A4).** Motion latches
disarmed on ANY of: boot-epoch change; power-cycle flag; IMU/foot-contact
inconsistency (carried/airborne signature while "standing"); global-match
ambiguity (relocalization second-best margin below the pre-registered
threshold); localization jump above the envelope's `localization_jump_m`
bound; or the operator pickup latch (physical/panel control). Each source
is journaled with its trigger value; re-arm only via A4's two paths.

**A11 · Consolidation and freeze semantics.** All addendum content folds
into the milestone document's hazard table and freeze record in the ONE
surgical reconciliation (no further review-card chain). The
CONNECTED-PLANNER probe gates **enabling connected compound instructions
only** — it does not gate the architecture freeze. Freeze sequence
(endorsed): research exit now → M1-0 contract work permitted → NAV-CORE v2
then VOICE-GATE v2 sequentially → reconciliation patch → **software
architecture frozen**; electrical/mechanical/physical freeze stays pending
vendor written answers and box-day commissioning.

**A12 · Follow's M1 scope — the one open OWNER decision.** Sol is correct
that the record held both positions. The two options, stated once:
- **(a) Follow in M1** (matches the owner's stated fallback wish twice):
  FOLLOW-COMPOSE (tracker install, synchronized pixel/range association,
  UWB driver-or-out-of-BOM, follow-speed obstacle/bystander avoidance),
  owner-loss HOLD, reacquisition, identity continuity, and the box-day
  identity gate all become **M1 blockers**; UWB is a live BOM risk if the
  appearance-only arm fails.
- **(b) Speed first**: M1's offline floor is **STOP + HOLD + the canned
  line** ("…all I can do is hold still until we're connected"), and Follow
  moves post-M1 with everything above intact as its enable path.
Recommendation: **(a)**, because the owner has twice specified follow as
the offline behavior — accepted knowingly as schedule/BOM risk. The choice
is the owner's; the milestone patch writes whichever is chosen and deletes
the other.
