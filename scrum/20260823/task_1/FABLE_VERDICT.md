# ARCH-1 Fable verdict

Disposition: **ACCEPT_WITH_REQUIRED_CHANGES**

Reviewed tree: committed base `0ce1c5f8bb4a` + the wave-3 overlay the packet
measured, which this reviewer integrated during the review as `c1b8405` (gate
green: 9,813 passed, third run; two reds dispositioned — the R26 governor perf
pin, and an hw7 meta-path determinism defect fixed at close) and `be86b78`
(index). Every disposition below is against the clean integrated tree.

Review scope: all eight packet files read in full; 9 read-only verification
agents (workflow `wf_39e2697d-958`, 556k tokens) regenerated the census and
probed the design — census of the three god objects + mid-tier classes +
repo totals; debt metrics (Any/noqa/excepts/markers/ruff/C901/source-shape
and mock test counts); import-graph SCC analysis; `ros_node.py` reachability
and motion-risk trace; product composition (X13/X14/X15/X04/R21) through
`web_panel.build_runtime`; sim capability limits; DAG order/OWNS collisions;
goal fit against the owner's 2026-08-23 direction; and one counterexample
attempt per non-negotiable rule. Plus this session's own wave-2/3
verification history over the same seams (HW-1…HW-MIC).

## Verified-facts summary

The packet is **accurate**. All headline metrics reproduce exactly on the
integrated tree: RobotRuntime 14,942 lines / 345 methods / 1,333-line
`__init__` (which assigns **269** mutable attributes — the packet gave no
count); DirectiveNavigator 5,764/116/113; RealtimeLane 3,146/81/133;
ControlManager 1,177/27; VoiceAgent 1,476/35; broad excepts 245 (exact); ruff
format 437/318 (exact); source-shape test modules 186 (exact); zero
hardware/integration markers (exact). Line-total drift vs the packet ≤0.2%
(the final HW-2/HW-MIC corrections). X16's regeneration requirement is
satisfied by this review; the delta is immaterial.

One census refinement matters: the "large multi-domain SCC" (62 modules, 15
domains) exists **only through the 39 re-exporting subpackage barrels**;
barrel-bypassed, the largest true SCC is 4 modules. Thinning barrels is
therefore cheaper and higher-leverage than the packet implies. The single
biggest extraction obstacle is `runtime.py`'s fan-out: it imports 99 of 317
intra-package modules.

## Blocking findings

1. **Rule 3 is presented as a preserved invariant but is violated today.**
   Owner: ARCH-LOOP. Invariant: 10 Hz path free of model/audio/persistence
   work. Boundary: `runtime.py:10490 _step_whisperer` →
   `RealtimeLane.narrate_event` → blocking `websockets.sync` send to the
   hosted provider (`ws_transport.py:372-385`) plus an on-disk spend-ledger
   read on cache-TTL lapse (`spend_ledger.py:328-380`), and duplex filler
   dispatch on the tick thread. Falsifiable regression: a hung provider
   socket stalls the control tick. Blocks: the refactor's honesty only —
   rephrase rule 3 as a **target** ARCH-LOOP must achieve, and put moving
   these three off-thread in ARCH-LOOP's explicit scope.
2. **B30 as a one-shot HIL gate.** Owner: board rows 5–9. Invariant: product-
   path evidence matches the shipped path. Boundary: rows 6C/7/8/9 refactor
   the exact proposal path B30 validated, with no named re-HIL; the Python
   SportClient writer (`control/unitree_sport.py`, plus the commissioning
   call site `commissioning/session.py:763`) stays in-tree until the order-10
   ARCH-CONTROL decision — a double-writer window after native cutover.
   Falsifiable regression: post-refactor tick emits a candidate B30 never
   saw. Blocks: physical prototype. Required: the rail's integration gate
   credential-strips the Python writer at cutover, and either the product
   credential holds at commissioning-only until the runtime cutovers land or
   a named B30-class regression HIL re-runs after each of 6C/7/8/9.
3. **The "parallel P0 rail" has unenumerated dependencies and OWNS
   collisions.** Owner: rail definition. Boundary: rail steps 3–4 need
   minimum ARCH-OBS/PKG/CONFIG slices whose contents the packet never
   enumerates, and rail composition edits `web_panel.py`/`config.py` — the
   same files ARCH-CONFIG (order 3) owns. Falsifiable regression: two cards
   claim the same region. Blocks: refactor only. Required: enumerate the
   minimum slices (most of the CONFIG slice already shipped as HW-5/CAP-1/
   TRUTH-1 — pin those semantics as characterization, bit-for-bit), and name
   ARCH-DEPLOY the single process-topology owner.
4. **The pose channel has no physical-authority seam at all** (sharper than
   X15). Owner: ARCH-OBS-MIN. Boundary: `CommissionedScanSource` covers only
   SCAN; pose rides `evidence_origin()`'s unconditional SIMULATION stamp
   (`input_health.py:276-297`), and `CommissionedStateSource` has **zero**
   product call sites. Under `go2_edu_plus`'s `require_physical_inputs:
   true`, a live dog's pose latches `sim_fixture_forbidden`. Fail direction
   is closed (refusal, not acceptance) — but the profile cannot ever run
   live without this seam. Blocks: physical prototype (sensing rung).
   Required: pose provenance lands in the same OBS-MIN slice as the snapshot
   contract, together with per-source receipt clocks (X04: one `received_at`
   still stamps pose+scan at `go2.py:821`).
5. **X14 topology contradiction confirmed and surviving.** Owner: ARCH-OBS.
   Boundary: `web_panel._build_backend` constructs `LiveGo2Sources`
   in-process while the documented four-venv topology gives the product venv
   no vendor SDK — the product process can never construct the live source.
   Blocks: physical prototype (sensing rung). Required: OBS-MIN decides the
   read-only sensing sidecar IPC (vendor venv publishes typed snapshots;
   product consumes) — or amends the topology doc; one of the two, in the
   card, before box-day.

## Required sequence changes

1. **Re-weight for the owner's 2026-08-23 direction** (conversational
   companion dog; features + hardware-mount sensor capture first; reduced
   testing). Cut or defer entirely for now: Stage 4 navigation leaves,
   ARCH-ROS/ARCH-LOCALIZATION (decide when map-relative navigation is
   actually needed), Stage 5 ARCH-MISSION/ARCH-RUNTIME, ARCH-CONTROL, Stage
   7 tooling cleanup, ARCH-CONFIG beyond the shipped physical-composition
   slice, broad ARCH-IG/ARCH-TEST debt ratchets, and full ARCH-AUDIO/
   REALTIME decomposition — do not decompose what works; decompose on first
   forced change. RobotRuntime's size is a maintenance risk, not a prototype
   blocker.
2. **The near-term spine is the read-only hardware rail + the two owner
   features**, not the god-object splits: box-day sensor capture readiness
   (D455/Mid-360/XVF3800 through real capture paths), the pose seam +
   snapshot slice (blocking findings 4–5), the R28 input-class × axis table
   (a one-page preregistration, now pulled forward because sensing yaw is an
   owner headline feature), head-turn, and proxemics.
3. **Lane rule (replaces the WIP=2 claim):** at most one Python-product card
   at a time, plus one genuinely disjoint lane (native bench / capture
   tooling / CI). The 6A∥6B∥6C "independent branches" are independent in
   prerequisites, not in files. Cards touching `runtime.py` are strictly
   sequential. Two concurrent cards must not share a pinned symbol, a
   marked-region file, or a structural-oracle test module.
4. **OBS-MIN is navigation-only** (matching the rail); WorldSnapshotV2 gets
   its own later row; the SimObservation carrier + scan side channel become
   typed refusals in the same card that cuts over — no dual-carrier steady
   state.
5. **Oracle-porting rule:** every extraction that moves code out of a
   path-scoped structural oracle (`test_r24_lock_discipline`'s literal
   lock-in-`__init__` roster, the 17 reentry-callback pins, digest pins,
   veto import bans, NM-1 tripwires) ports that oracle to the new owner in
   the same card. Classify supported-vs-incidental pins (A19) before any
   runtime extraction, not during.
6. **Facade rule sharpened (rule 9):** the current "snapshot aggregation" is
   per-tick mirror dicts under `runtime._lock` — extractions must replace
   the mirror-dict pattern with immutable snapshot handoff or delegated
   reads, and report attribute/lock/callback counts before/after.
7. **Stage 0 reduced:** conftest/guard work already shipped (XD-1/HY-1);
   fold ARCH-TEST's residual (repo-owned bounded launcher, debt pins) into
   ARCH-F0-MIN. The rule-4 refinement joins the contract: adapters stamp
   host receipt time from their own clock — never copy a payload field
   (today `MujocoSocketBackend` trusts the sender's timestamp).
8. **X12 decision (rendered here):** for the prototype, native final
   governor and sole-writer gateway are **co-located in one process** — one
   clamp owner (the governor), the writer module veto-only (may reject/zero,
   never originate/increase), split later only with measured cause. The
   bench records this as its assumption. L13's ADR is accepted as
   recommended: Python 3.12 product logic, isolated 3.10 vendor venvs,
   C++20 for the smallest governor/gateway only, wrap mature vendor/ROS
   drivers, no Rust absent an owned FFI case.

## Accepted preserve boundaries

As proposed: A17/A18 (hard_stop, bridge DTOs, provenance models, monotonic
discipline, GPU isolation are reference patterns), A20 single-lifecycle state
machines, N01–N08 in full, the census's PRESERVE_FIRST families, `_astar` and
the final safety gates, D07's default-preserve for ControlManager. Rules 1,
2, 5, 6, 7 verified HOLDING today (single writer = ControlManager; motion
refusals; physical-table latching; exact-zero digests; no sim→physical
authority leak), with the named migration risks recorded above.

## Test/eval findings

The plan predates the owner's reduced-testing directive and is
disproportionate outside safety authority. Required proportionality cut —
**keep** (hardware-integral): stop chain (exact-zero latch after every
shaper, TTL/watchdog, restart-disarmed, no auto-resume), single-writer/
epoch/credential rejection, out-of-band e-stop as a **gate condition on
B25/B16** (not a present-tense invariant — unfalsifiable with no hardware),
input-health fail-closed dispositions, T15's real-product-caller +
disconnected-component-mutant rule for P0 seams, the T16 inspected physical
ladder, commit gates 1/3/4 and a slimmed 2/5, and a repo-owned bounded
pytest launcher (T10/P08). **Defer/drop**: the 100k-fuzz nightly (run once
at protocol freeze, then manual), the eight-gate nightly battery (fold to
one small nightly: stop-chain fault-containment + evidence-integrity),
changed-code coverage ratchets and commit gate 6, the full-suite
scope/cadence marker migration, mutation-score-non-decline, 1,000-rep p99
(simply do not claim p99), 30-repeat campaigns stay milestone-only (T21
already says so). New-feature cards carry capability-proof tests + wiring
checks only.

## Evidence not reproduced

Cycle SCC membership beyond the top-20 list; T03's exact 197 (my patterns
give 151–183; direction confirmed); A12's exact 993 (773–1,157 by pattern;
phenomenon real); the packet's lock-graph prose (I reused
`test_r24_lock_discipline`'s roster); any target/hardware fact (none
exists); the sim-perception measured numbers were taken from the cited
status docs, not re-run.

## Concern dispositions

- **X01–X07, X09–X10, X13–X15: CONFIRM_OPEN** (X13/X14 verified; X15
  verified with the sharper pose finding above; each gates its named
  physical milestone).
- **A01–A16, A19, A21–A23: CONFIRM_OPEN** (A06 refined: barrel-mediated;
  A09 Any=1,278 now; A10/A11/A12 confirmed).
- **R01–R24, R26–R35: CONFIRM_OPEN** (R28 pulled forward as a required
  change; R03/R04/R16 are now *integrated* at `c1b8405` but remain open at
  the target-evidence rung — integration is not closure, per N08).
- **T02–T04, T07–T13, T15–T19, T21: CONFIRM_OPEN** (T02=186 exact,
  T04=0 exact; T15/T16 are the tests the owner's directive keeps).
- **L02–L03, L05–L10, L12–L13: CONFIRM_OPEN** (L13's ADR accepted as
  recommended; L07 integrated but the aarch64 job has still never run).
- **O01–O06, O08–O13: CONFIRM_OPEN** (O10's ARCH-DEPLOY owner accepted into
  the rail).
- **P01–P08, P10–P17: CONFIRM_OPEN**, with the owner's directive adopting
  the responses of P02/P11/P12/P13 (batching, budgets, risk-tiered review,
  follow-up admission rule + two-correction limit).
- **N01–N08: PRESERVE** (the reduced-testing directive is forward-looking;
  N04 still forbids deleting existing protections without replacement).

Exceptions (each removed from its family):
- **X08: REFUTE_WITH_EVIDENCE** — closed by this review: quiescent
  integrated commit `c1b8405`, commit-tier gate green (record in
  `WAVE3_DISPATCH_FABLE_6c.md`), index regenerated, census re-verified.
- **X11: REFUTE_WITH_EVIDENCE** — the packet's own revised board already
  moved the bench parallel; accepted as revised.
- **X12: decision rendered** (co-location; see required change 8).
- **X16: REFUTE_WITH_EVIDENCE** — census regenerated at the integrated
  commit by this review; delta ≤0.2%, structural numbers exact.
- **A17, A18, A20: PRESERVE.**
- **A24: DEFER_ACCEPTED_RISK** — owner: Fable; trigger: the first
  map-relative/custom-navigation card; the buy/build decision runs before
  Stage-4 work resumes, which is itself deferred.
- **R25: CONFIRM_OPEN, severity narrowed with evidence** — motion risk
  *as composed today* is REFUTED (rclpy absent, `run()` raises, zero
  subscribers to `/parcel/*_request`, no Python hardware writer); the
  governance gap is real and forward-looking. **Scope addition:** the same
  disposition card must cover `parcel-agent --text --sim` (`cli.py`'s
  non-ROS branch) — a live, installed, uncensused bypass that composes
  VoiceAgent+Dog outside RobotRuntime into a running sim's SkillExecutor.
- **T01: REFUTE_WITH_EVIDENCE** — the full commit-tier gate has now run
  green on this exact tree (9,813 passed at `c1b8405`).
- **T05, T06, T20: DEFER_ACCEPTED_RISK** — owner testing directive; typing
  stays report-only on new boundary modules; revisit at the first
  post-prototype hardening pass.
- **T14, L01, L04, P09: PRESERVE.**
- **O07: CONFIRM_OPEN, integrated** — firewall artifacts are committed;
  target application/reboot proof still missing.

Coverage: X01–X16, A01–A24, R01–R35, T01–T21, L01–L13, O01–O13, P01–P17,
N01–N08 — all 147 IDs accounted for above; none omitted; no ID appears in
both a family and its exceptions.

## Concern batching and spend controls

Accepted batches (each = one owner-visible tranche, several bounded cards,
one integration gate): (1) **Feature + sensing tranche** (now): R28 table,
head-turn, proxemics, pose seam + OBS-MIN slice, capture readiness — Tier B
cards, Opus executor + one Fable verifier each, capability tests only.
(2) **No-credential native bench** (next): bridge freeze + fake-Sport
governor/gateway — Tier S, full treatment. (3) **Deploy/commissioning**
(hardware-gated): O-family + B16. Rejected for now: Stage 4/5/7 batches,
coverage/typing ratchets, whole-suite marker migration. Review tier: S =
full three-lens verification; B = capability + wiring + no-authority-
regression; M = automated checks + sampled review. Follow-up admission per
P13 (two correction passes, then redesign/escalation). Tranche budget: the
feature tranche is 4 cards + 4 light verifications; stop/continue is the
owner's review of the tranche result. Token/$ per card: `unknown`
(not exposed); elapsed/retries/model/diff/outcome recorded per card.

## Explicit answers to the brief's 20 questions

1. Yes for the reduced Stage 0 (freeze + launcher); broad IG/TEST ratchets
   need not precede the feature tranche — barrels are the one exception
   worth doing early (verified cheap, high leverage). 2. Yes; the bench may
start at protocol freeze. 3. Yes — D01–D25 cover every system; R25 adds
`cli.py` (see exception). 4. Yes, with the barrel refinement. 5. Yes on
state boundaries; ARCH-LOOP's scope must include the rule-3 violations; the
facade rule-9 sharpening applies. 6. Keep through characterization; default
preserve; never a second writer. 7. Under the new goal: capture/deploy rise,
CONFIG/PKG shrink to slices, UI/CI defer. 8. Yes — T15's disconnected-
component mutants are the antidote and are kept. 9. Yes, with the rule-4
receipt-clock refinement. 10. Defensible but disproportionate now — see the
test/eval cut. 11. Not as drawn — see the lane rule. 12. See Does not
prove. 13. Yes. 14. Yes — co-located, governor clamps, gateway veto-only.
15. Yes — that is X13's required product-entrypoint test. 16. Retire/refuse
`ros_node.py` for physical use; ROS/Nav2/localization decisions deferred to
the navigation tranche (A24 exception). 17. Yes in the contract sketch; the
one-`received_at` defect and frozen-scene sim camera are the two named
gaps. 18. Dry no-writer stop check, one reviewed pulse, 3–5 inspected
stops, gateway kill/hang — unchanged from T16/R30. 19. Yes — evaluate
before decomposing (A24); differentiators stay custom. 20. Yes with the
spend controls above.

## Does not prove

This verdict proves the packet's claims against the integrated desktop tree
and the coherence of the revised sequence. It proves **no** behavior on
hardware: no sensor timing, no stop distance, no DDS/Livox reality, no Orin
install, no acoustic performance on the body, no companion quality with a
real user, and no timing of any native component (none exists). It does not
prove the extraction cards will meet their ratchets — only that their order
and oracles are sound. Acceptance authorizes no spend, dispatch, credential,
or motion; the owner's direction of 2026-08-23 (decompose, build features,
prepare hardware mount) is the standing authorization this verdict's
tranche-1 recommendation operates under.

## Authorization

Architecturally eligible now (dependency-safe, reversible, no motion): the
**feature + sensing tranche** — R28 axis-table preregistration; AWARE-1
head-turn through the existing patrol/scan proposer machinery; PROX-1
context proxemics as a pure profile selector over `person_stop_m`/
`person_slow_m` with the P1-E physics floor untouched and any reasoning
model proposal-only; SENSE-1 pose-seam + per-source receipt clocks +
capture-path readiness for D455/Mid-360/XVF3800; IG-1 thin barrels +
forbidden-edge ratchet (mechanical). The native bench tranche is eligible
next after the bridge freeze. X08 and X16 are closed; no other blocker
gates these cards. Fable does not authorize spend; the owner already has.

---

## Addendum — post-landing register update (reviewed 2026-08-23 ~16:4x EDT)

After this verdict's main body was drafted, the packet author updated the
register and test plan against the integrated delta (`c1b8405`, delta doc
`CLAUDE_WAVE3_DECOMPOSITION.md`) and revised X06/X08/X16/A08/A23/R03/R04/
R09/R14/R16/T01/T12/O07/P14/P15/N08. Dispositions updated where the update
is material; everything else in the main body stands.

- **X06 / A08 / R14 (resolved-profile inheritance) — CONFIRM_OPEN,
  reproduced by this reviewer.** `deep_merge(robot.yaml,
  robot.go2_edu_plus.yaml)` inherits `battery.simulated_percent: 90.0`,
  `control.controller: simulator`, and desktop `enp3s0` under both
  `unitree_sport.interface` and `robot.interface`. The overlay's
  commented-out keys do not delete base values. This is a hardware-integral
  defect under the owner's own testing policy and is assigned to the
  **SENSE-1** card (tranche 1): resolved-profile validation refusing
  simulated battery / desktop NIC / simulator controller when
  `safety.require_physical_inputs` is true, with explicit required/delete
  semantics for box-day keys.
- **T12 (hard-skip false-green) — CONFIRM_OPEN, reproduced.**
  `GateResult.is_red` is `status in {fail, error}`; a typed hard SKIP exits
  **0** while the summary truthfully names the skips (HW-7 fixed the
  sentence, not the code). A CI consumer keying on the exit code reads a
  skipping host as green. Assigned to **GATE-1** (tranche 1): distinct exit
  status for hard-skips-present (incomplete ≠ pass ≠ fail) as a small,
  separately-committed behavior-change card.
- **R09 sharpened (V1 gate while V2 exists) — CONFIRM_OPEN**; this is the
  HW-6b debt already carried in the wave-3 record. Assigned to **GATE-1**:
  wire `derive_envelope_rows_v2`/`load_stopping_envelope_record_v2` so the
  stopping row names `scan_age_s` (UNMEASURED) instead of silently reading
  five terms.
- **A23 sharpened (drain under observation lock; `_ARRAY_MIC_ROUTE_LOCK`
  serializes HTTP only) — CONFIRM_OPEN.** The drain-bound enforcement half
  goes to SENSE-1 (bounded drain under injected blocking/corrupt-flood
  socket); the mic direct-vs-HTTP lifecycle race is accepted risk until the
  audio stack is next touched (no direct/runtime caller exists in product
  today; the route is the only arm path).
- **X08 — now PARTIAL per the register; answered.** The gate result was not
  inherited: this reviewer ran the commit tier three times through the
  bounded wrapper, diagnosed both reds (R26 governor noise; the hw7
  meta-path determinism defect, fixed and recorded), and committed only on
  a green third run. The bounded evidence level before dispatch is: commit
  tier green at `c1b8405` — nothing stronger is claimed; nightly/target
  tiers remain unrun (see Does not prove).
- **X16 — the narrow re-review is this verdict.** The census was
  regenerated by 9 independent agents on the byte-identical integrated
  tree (delta ≤0.2%, structural numbers exact); the high-severity refuters
  reproduced are listed in Verified-facts and this addendum. X16 is closed
  for dispatch purposes; `CLAUDE_WAVE3_DECOMPOSITION.md` is accepted as the
  delta record.
- **The test-plan addendum's five required reds are accepted and assigned:**
  V2-scan-age-omitted → GATE-1; hard-skip-zero-exit → GATE-1;
  blocking/corrupt-flood drain bound → SENSE-1; resolved-profile
  inheritance → SENSE-1; mic direct/HTTP race → deferred accepted risk
  (owner: Fable; trigger: first audio-stack card). Per the owner's testing
  directive these land as capability/error-check tests with the product
  fix, not as new suites.

Tranche 1 (final): **PROX-1** + **SENSE-1** (wave A, parallel, disjoint
OWNS), then **AWARE-1** (+ R28 axis-table preregistration) + **GATE-1**
(wave B). Opus executes; Fable verifies at Tier B (capability + wiring +
no-authority-regression). This supersedes the four-card list in
Authorization only by adding GATE-1.
