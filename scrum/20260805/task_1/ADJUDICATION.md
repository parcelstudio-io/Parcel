# Adjudication — Fable research vs Sol 5.6 program, and the final plan

**Date:** 2026-08-05 · **Adjudicator:** Fable. Inputs: Sol's
[README](README.md) + [A](A-navigation-perception.md) / [B](B-voice-behavior.md)
/ [C](C-evaluation-delivery.md), and the independent
[Fable research plan](fable-research-plan.md) (workflow `wf_44b643ea-490`,
prompts locked before Sol's docs were read).

> **OWNER AMENDMENT (2026-08-05, supersedes D4 below):** hardware is
> purchased **last**; the simulator is the test substrate throughout. See
> [§ Owner amendment — hardware last, sim throughout](#owner-amendment--hardware-last-sim-throughout)
> for the revised phase structure. This partially vindicates Sol's original
> P8 sequencing. Binding corrections D1 (no Nav2 migration), D2 (voice on
> its own gates), and D5 (calibration first) are unaffected.

## Verdict in one paragraph

The two plans converge on ~80% of the architecture — independently, which is
strong evidence the shared core is right. The final plan is **Sol's contract,
truthfulness, and statistical machinery on Fable's timeline, scope, and
deployment path**. Four binding corrections to Sol's program: (1) no ROS 2/
Nav2 authority migration in v1 — it is a challenger with a named decision
gate, not the backbone; (2) the voice differentiator enters the default
runtime when *its own* gates pass (Phase 2), not behind four navigation gates
(Sol's P5); (3) hardware is procured in Phase 0 and commissioned in Phase 2 —
Sol's plan never buys the robot and defers physical work to P8; (4) the first
implementation card is the goal-calibration fix, because the 0/25 row that
motivates Sol's "not a credible capability" framing is partly a measurement
artifact (verified: episodes ending 6–26 cm from goal scored `planning_error`
via `navigation_step_limit`).

## Fact-check of Sol's premises (verified against the repo today)

| Sol's claim | Verdict |
|---|---|
| `StimulusBus`/`ReactionArbiter` pure but unwired in runtime | **Confirmed** — no references in `runtime.py`/`agent.py` |
| Latest nav-instruct candidate rows 0/25 and 0/8 | **Confirmed, but overstated** — several failures are near-misses (dtg 0.06–0.26 m) killed by step limits + three disagreeing "arrived" definitions (navigator 1.5 m / semantics 1.32–1.38 m / eval disc 1.46 m). The grounding column resolves; termination/calibration is a distinct, cheap fix Sol's plan never names |
| `agent.py::_handle_text` direct-dispatches follow/stay/spatial/walk around PlanIR | **Confirmed** — `set_behavior`/`set_velocity` tool calls bypass the lifecycle |
| Follow benchmark 8/9, reacquisition corner case | Consistent with the pinned ledger row |
| Starting commit `4cc2585` | HEAD is `854ee8e` (doc-only commit on top) — immaterial |

Sol's code diagnosis is accurate and its debt list (B-doc §"Repair these
debts") is adopted wholesale.

## Where the plans independently converge (adopt without debate)

- Layered stack; learned components are bounded, removable proposers behind
  freshness/feasibility/collision gates; **one motion writer**; no
  model-authored velocity or priority.
- Owner identity fail-closed: confirmed → ambiguous → lost → bounded
  search/stop; never attach to the nearest person.
- Semantics never make space safe; goal regions need geometry, free-space
  support, and a collision-free approach.
- Scene-text (PaddleOCR) + storefront geometry + logo similarity is the
  brand-store cascade; open-vocab detector + SAM-class masks + metric fusion
  for objects; a compact closed-set segmenter (not an open-vocab giant) for
  road/sidewalk safety classes.
- ByteTrack/BoT-SORT + enrolled ReID for tracking; elevation-mapping-class
  2.5-D terrain; deterministic CV/IMM prediction first, learned predictors
  shadow-only; street crossing is a distinct safety-critical mode.
- Eval as architecture: frozen baselines, paired seeds, McNemar/Wilson,
  failure attribution with oracle counterfactuals, immutable ledgers,
  `does_not_prove`, hidden promotion sets; staged commissioning
  (dry-run → bench → leashed → free) with dual e-stop.
- Contract-first parallelization with versioned DTOs and single-owner rules
  for safety-critical seams.

Convergence here was reached from different sources — treat these as settled.

## Divergences, adjudicated

### D1 — Nav2/ROS 2 backbone (Sol) vs additive in-house authority (Fable) → **BINDING: no authority migration in v1**

Sol makes ROS 2/Nav2 the production planning/control backbone at P1 (MPPI,
BT navigator, collision monitor, TF tree, ROS actions for skills). The final
plan rejects this for v1 on evidence:

1. **Our failure data doesn't indict the planner.** Attribution shows
   grounding/termination/calibration failures; grid A* + reactive gate is not
   the failing layer. Migrating the healthy layer is scope without a symptom.
2. **The classical budget is already met in-process.** The cited 176 ms
   Spot-stack median is a CPU-classical stack of exactly our shape; the
   sidewalk industry (Serve/Starship/Coco) ships global-prior + local
   costmap + conservative gate — Parcel's existing authority shape — not
   Nav2-on-a-quadruped.
3. **Cost lands on the differentiator's critical path.** A second runtime
   (ROS 2 env on dock + bridges from the Python app), TF discipline, MPPI
   tuning, and new failure modes consume the exact weeks that close the
   voice→behavior loop — the thing no competitor has.
4. **Sol's own rules decide this.** "Technology decisions to validate, not
   assume" + grid_v1 kept as deterministic CI reference. A backbone you must
   keep a fallback for is a challenger by definition.

**What survives from Sol's Nav2 case (adopted additively into grid_v1):**
keepout polygons (roads), speed zones with lookahead (curbs, doorways,
crossings, crowds), forward-preference with lateral-distance-ratio reporting,
and an independent collision-monitor stage ordered after smoothing — all
implementable in the existing navigator/config without ROS.

**Decision gate (named now):** if Phase-3 leashed field attribution shows
L5/L6 (local control / gate-deadlock) as the dominant failure layer — 
oscillation, dynamic-scene freezing, curb-approach quality — stand up Sol's
N0–N2 Nav2 spike as an exclusive challenger backend behind the `Navigator`
contract and A/B it on the frozen course. Until that data exists, Nav2 is a
parked card, not a dependency.

### D2 — When voice-behavior integration ships → **BINDING: Sol's architecture, Fable's timeline**

Sol's four-lane split (reflex / conversation / planner / social) with the
conversation-lane truthfulness rules and the resource×event interruption
table is the best-written part of either plan — **adopted as the target
architecture**, including `DialogueActV1`, `SocialCueV1`,
`ReactionProposalV1`, `SceneQueryV1`, `SkillFeedbackV1`, and the
`expression_audio`/`perception_scan` track vocabulary.

But Sol gates "companion behavior integration" at P5, behind geometric nav
(P1), owner ReID (P2), social nav (P3), and semantics (P4). For a companion
product whose moat is voice, that sequences the differentiator last. The
DAG says it needn't be: the closed intent enum needs only the existing
pause/resume + CommandArbiter; amendment needs only the completed resume
transaction; dialogue-state × gaze needs only the bus and wired T2 — none of
it waits on ReID, social costmaps, or OCR. **Final: voice tracks run from
day one (Sol's own workstream table already allows this) and enter the
default sim runtime when voice's own gates pass — Phase 2 — with hardware
voice following the bench schedule.** Sol's B0→B1→B2 cards are kept intact
as the implementation sequence.

### D3 — UWB → **BINDING: UWB is a first-class owner channel until data says otherwise**

Sol's owner-tracking design is vision-only (detector + ByteTrack + ReID +
LiDAR association) and **never mentions `rt/uwbstate`** — the owner-fob
bearing/range sensor the Go2 ships with. Fable's plan treats UWB-primary +
ReID-confirmation as a day-one-validated hypothesis with fusion designed so
either channel can become primary without contract change. Final: build the
DDS adapter for `rt/uwbstate` in Phase 2 bench work, run the characterization
protocol (bearing/range vs vision truth, indoor/outdoor, occlusion,
multipath), and let the data pick the primary. Sol's fail-closed identity
state machine governs either way.

### D4 — Hardware procurement and sequencing → ~~BINDING: procure in Phase 0~~ **SUPERSEDED by owner decision 2026-08-05: hardware last**

*Original ruling (kept for the record):* Fable argued procurement in Phase 0
so bench commissioning, day-one bags, and UWB characterization could overlap
the sim sprints; Sol deferred physical work to P8 with no purchasing step.

*Owner decision:* buy the hardware **last** and use the simulator for testing
throughout — closer to Sol's original sequencing. The revised phase structure
is in the Owner-amendment section below. The two-dock rule, the golden-image/
firmware ADRs (drafted now, validated at the hardware phase), and Sol's
commissioning content (H0 checklist, staged protocol, evidence templates,
L6–L8 ladder) all survive — they simply all execute in the final phase.

### D5 — First card → **BINDING: unify the three "arrived" definitions before any new capability work**

Neither adding Nav2 (Sol) nor adding memory (Fable) is the first move. The
first card is the goal-calibration fix: one arrival authority shared by
navigator, semantics, and scorer (predicate/polygon per the standing rule,
never three radii), plus a step-limit audit. It is hours of work, it moves
the headline SR immediately, and every later baseline/candidate delta is
uninterpretable until it lands. Then re-freeze the baseline row honestly.

### D6 — Simulation portfolio → **BINDING: cut to three rungs for v1**

Sol proposes MetaUrban + Habitat 3 + iGibson + URBAN-SIM/Isaac + BARN/
DynaBARN/SocNavBench + HuNavSim. That is a research lab's portfolio; for
this team it is adapter engineering that eats capability work. Final v1
evidence stack: **(1) Parcel MuJoCo/headless** (extended per Sol's E0:
semantic polygons, pedestrian scripts, fault schedules, DTO-only
observations — adopted), **(2) recorded-bag replay on the Orin NX** (the
missing sim-to-real rung both plans want), **(3) bench + staged live
protocol**. MetaUrban is the single approved external backend, deferred
until after Phase 3, behind Sol's adapter/oracle-isolation rules. Habitat/
iGibson/URBAN-SIM/SocNavBench are struck from v1 (revisit only if a specific
promotion decision needs them). BARN stays what it already is — a frozen
regression lane, per the standing effort-reallocation verdict.

### D7 — Learned-model ordering → **BINDING: Fable's ordering (fresher evidence)**

Sol orders NoMaD/ViNT → LeLaN → VLFM-pattern → NaVILA. Fable's research
found facts Sol's plan predates: **GuideNav is now MIT-released on exactly
Go2 + D435i** (teach-and-repeat, 5 Hz, km-scale, user-study-validated), and
**CityWalker is already vendored in `third_party/CityWalker`** with its
registry YAML waiting on one inference adapter. A companion dog walks the
same routes daily — teach-and-repeat is the product-shaped win, not
exploration-oriented NoMaD. Final order: GuideNav-adapted route memory +
CityWalker A/B (P4) → VLFM value-map scorer into SearchEntity (P4, rung 6)
→ NaVILA remote tier (P5, rung 7, ladder promotion rule ≥+5pp with no added
gate interventions). NoMaD/LeLaN: optional exploration proposers, parked.
Sol's promotion staging (replay → sim shadow → sim active → hardware shadow
→ fenced active, no skips) governs all of them.

### D8 — Latency budgets → merge

The tables agree within rounding everywhere they overlap (ack ≤150/300 ms
text, ≤350/700 ms audible, admitted plan ≤900 ms, e-stop ≤300 ms hardware,
obstacle→zero ≤100 ms). Adopt Sol's table as the dashboard series set, plus
Fable's two systemic rules: hold the integrated onboard hot path ≤176 ms
median, and **cap commanded speed as a function of measured pipeline
staleness** (v·τ: at 1.5 m/s, 100 ms = 15 cm) so degradation is graceful by
construction. Sol's GPU co-residency protocol (Gemma ~15 GB + Fish ~11 GB on
32 GB) is adopted for the desktop era and reused on the Orin.

## What each plan uniquely contributes to the final

**From Sol (adopted):** four-lane voice architecture + truthfulness rules;
resource×event interruption table; `EvidenceEnvelopeV1` and the V1 DTO
family (merged with Fable's DetectionMsg + dialogue-state channel into one
contract RFC); SceneQuery broker seam (skills request evidence, never
instantiate detectors); statistical protocol (predeclared metrics, hidden
promotion split, non-inferiority margins); L0–L8 evidence-ladder naming;
run-manifest schema with `does_not_prove`; low-obstacle suite (curb, cable,
glass, negative obstacle); the "explicit limits" honesty section; oracle
isolation as a tested property; A-doc's active-inspection framing (a scan
owns `base + attention` — no neck).

**From Fable (adopted):** goal-calibration first card; UWB channel +
characterization; low-viewpoint (35 cm) gates before field trust; dialogue-
state as a 10 Hz bus channel driving gaze/gait/pace (the white-space
differentiator); crossing-as-companion-moment (curb-stop + owner voice
initiation through T1); hazard narration with decay TTLs; the complete
install path (golden image + one-way-door discipline, compose OTA,
commissioning wizard, firmware pin ≥1.1.13, DDS firewall, tailnet, Tier
0/1/2 degradation ladder with tier-kill CI); procurement now; GuideNav/
CityWalker/PP-OCRv6/Overture/MegaLoc evidence updates; minutes-per-
intervention headline metric; WoZ from week one.

## The final plan (binding)

Phases and exit gates as in [fable-research-plan.md §2](fable-research-plan.md)
with these substitutions: Phase-0 contract RFC = Sol's V1 DTO family merged
with Fable's two additions; Phase-1 Track C implements Sol's B0/B1/B2 card
sequence; Phase-2 commissioning uses Sol's H0/L6 content; the eval program
runs Fable's six layers carrying Sol's metric families and statistical
protocol; D1's Nav2 decision gate is evaluated at Phase-3 exit.

**Kickoff board (first wave):**

| Card | Content | Owner lane | Phase |
|---|---|---|---|
| K0 | Goal-calibration fix: one arrival authority (predicate/polygon), step-limit audit, honest baseline re-freeze | Opus (existing files) | 0 |
| K1 | Contract RFC: EvidenceEnvelopeV1 + OwnerTrack/DynamicTrack/SemanticRegion/GoalRegion/DialogueAct/SocialCue/ReactionProposal/SceneQuery/SkillFeedback + DetectionMsg + dialogue-state channel; contract tests in CI | Sol (pure) + Fable review | 0 |
| K2′ | Sim-bag recorder/replayer + bag schema (real-sensor-shaped) + hardware-readiness ledger; golden-image/firmware ADRs drafted (validation at P5) *(K2 procurement moved to P5 by owner amendment)* | Opus | 0–1 |
| K3 | Resume-transaction completion (single owner): ResumeIntent consumption, `requires_fresh_observation` enforcement, search→follow via stored intent | Opus | 1 |
| K4 | SemanticMemory2D + Grounder v2 + ScanBehavior + SearchEntity (rungs 1–5) | Sol (pure) + Opus (wiring) | 1 |
| K5 | MuJoCo CameraChannel @ D455 intrinsics/35 cm + DetectionMsg noise adapter + low-viewpoint gate pack | Sol (pure) + Opus (sim) | 1 |
| K6 | Voice lanes B0→B1→B2 (Sol's cards) + closed intent enum → executive; desktop audio operational (needs backlog B1 apt install) | Opus + Sol | 1 |
| K7 | Compose skeleton (network-independent safety+control container) run on desktop/CI; asset-packaging fix; CPU-budget proxy profile of the 10 Hz hot path *(dock flash moved to P5 by owner amendment)* | Opus/infra | 1 |
| K8 | Frozen integration scenario pack (8–12 walk-with-me scripts) + nightly attribution | Sol (generator) + Opus (runner) | 1 |

## Owner amendment — hardware last, sim throughout

**Decision (owner, 2026-08-05):** purchase hardware last; the simulator is
the test substrate for the whole development arc. Revised structure:

| P | Name (revised) | What changes vs the original table |
|---|---|---|
| 0 | Contract freeze + calibration + eval | Unchanged **minus procurement**. Golden-image and firmware-pin ADRs are still *written* now (the research is done); their validation moves to P5. |
| 1 | Four-track sim sprint | Tracks A/B/C unchanged. Track D becomes sim-shaped: asset-packaging fix; **bag schema defined now + sim-bag recorder/replayer built and CI'd** (real bags drop into an existing harness later); compose skeleton built and run on desktop/CI (aarch64 build deferred); CPU-budget proxy profiling in place of Orin timing. |
| 2 | Voice-behavior joins, all in sim | Amendment, clarification, dialogue-state × T2 — unchanged (they were sim-side already). WoZ sessions run on **desktop audio** (backlog B1 apt install is still required — it is not a hardware purchase). **UWB noise model** (bearing/range error + multipath dropouts) added to the sim so the owner-fusion code path exists and is tested before characterization. Commissioning wizard deferred to P5. |
| 3 | City layer, in sim | GNSS becomes a **simulated sensor with a covariance/dropout model**; the OSM footway/crossing graph is built against a real neighborhood fixture (actual osmnx pull, cached) and exercised over the sim city; Overture tile client runs against cached fixtures; curb/crossing semantics authored into sim scenes; **storefront signage rendered as textures in the MuJoCo CameraChannel so the real PP-OCRv6 model runs on synthetic renders** — real perception models, synthetic pixels, which tests the whole cascade except pixel-domain realism. Crossing mode (curb-stop + voice initiation) fully testable in sim. |
| 4 | Route memory + learned proposers, in sim | Teach-and-repeat prototyped on rendered frames (VPR on renders); CityWalker adapter tested on recorded sim walks + the repo's public sample data; VLFM scorer headless as planned. |
| 5 | Hardware, all of it, last | Procure (Go2 EDU ≥1.1.13, 2× Orin NX dock, D455, ZED-F9P, XVF3800) → sacrificial-dock golden image → bench commissioning per the staged protocol → day-one real bags into the **pre-built** replay harness → UWB characterization vs the P2 noise model → on-device timing vs the CPU proxy → low-viewpoint real-world gates vs the sim gates → leashed course → the original P5 productization (OTA, wizard v1, tailnet, long-horizon study). |

**Sim-substitution rules (what keeps this honest):**

1. **Every sim stand-in gets a named re-run gate.** A `hardware-readiness`
   ledger lists each place sim substitutes for hardware (motion dynamics,
   UWB model, GNSS model, rendered-pixel perception, CPU proxy timing,
   desktop audio) and the exact test that must re-run in P5. Nothing on that
   ledger may be quoted as validated — this extends the U1/U2 register
   discipline that already exists.
2. **Contracts stay hardware-shaped.** The bag schema, DetectionMsg, and DDS
   adapter surfaces are defined against the real sensor specs now, so P5 is
   commissioning work, not redesign work.
3. **Model selection stays Jetson-constrained even without a Jetson.** Only
   components with published Orin-class numbers (NanoOWL, BoT-SORT ports,
   PP-OCRv6 ONNX, MegaLoc) enter the stack, so the P5 timing pass is
   confirmation, not discovery.
4. **The cost is stated plainly:** this concentrates all sim-to-real risk at
   the end. Motion realism (kinematic MuJoCo base), UWB behavior, real-world
   low-viewpoint perception, Orin budgets, and acoustic UX stay unknown
   until P5 — the classic risk profile staged hardware access avoids. The
   mitigations above bound it; they do not remove it.

**Kickoff board deltas:** K2 (procurement) moves to P5 and is replaced in
the first wave by **K2′ — sim-bag recorder/replayer + bag schema + the
hardware-readiness ledger** (Opus). K7 loses the dock flash and keeps the
compose skeleton + packaging fix + CPU-budget proxy. Everything else stands.

## Install-on-Unitree gate assessment (the owner's question)

**Can this plan end with software you actually install on a Go2? Yes, and
the path is fully specified — but three honesty statements bound it:**

1. **The install artifact is concrete:** golden JetPack 6.2.x dock image +
   compose bundle + commissioning wizard, on a customer-owned Go2 EDU with
   firmware pinned ≥1.1.13 and the DDS network firewalled behind the dock.
   Existence proof on identical hardware: the MiniCPM Go2 deployment.
   Nothing in the plan touches Unitree firmware — consistent with the FCC
   accessory-plus-software posture already adjudicated.
2. **The demonstrable gates split under the owner amendment:** the full
   capability stack (city layer, voice joins, route memory) is proven *in
   sim* through Phases 1–4; the physical prototype gate — the leashed
   20-minute mixed course with curb-stops, storefront confirmation, and
   Tier-0 survival — lands in Phase 5 after commissioning, as the first
   hardware milestone rather than a mid-program one.
3. **What no plan can claim yet:** sim-to-real on motion (MuJoCo base is
   kinematic; Sport-mode tracking under the 10 Hz stream is uncommissioned),
   UWB behavior, low-viewpoint perception in the wild, and audio UX (never
   yet heard acoustically even on the desktop). All four have named Phase-1/2
   de-risking steps; none has evidence today. "Seamless around cities"
   remains a program goal — v1 city scope is mapped/topological routes +
   bounded local exploration + hard-geofenced crossings, per both plans'
   explicit-limits sections.

**Bottom line:** adopt the merged plan above as amended. First three
actions: K0 goal-calibration fix (hours), K1 contract RFC (days), K2′
sim-bag harness + hardware-readiness ledger (days). Hardware purchase is
deliberately the program's final act (owner decision); the readiness ledger
is what keeps that honest.
