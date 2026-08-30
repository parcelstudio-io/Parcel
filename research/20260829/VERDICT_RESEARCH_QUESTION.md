# Verdict on the research question: can a trainable, fully duplex Model A + a Model B on top of it generalize the dog's navigational and conversational fluidity?

Author: Fable (parcel-0e), 2026-08-29 20:3x EDT. Status: **FINAL (21:3x EDT 2026-08-29).** Both probes (NAV-GEN-1, MB-2) ran,
were verified line-by-line, reproduced in scratch, and survived adversarial
panels (11 of 12 claims unrefuted; the one refutation — that MA-1's 4.5 %
was an episode-script effect — is adopted below). Physical motion:
**NO-GO**, unchanged.

This is the verifier's verdict over the whole study (`FLUIDITY_REPORT.md`
§1–§7, the five experiments' `VERDICT_FABLE.md`, the 08-28 wave's four
verdicts, the verified literature, and Sol's parallel assessment in this
folder, which reaches the same conclusions independently).

## 1. The question, decomposed into claims that can be true or false

The owner asked for (a) a generalized, trainable Model A that reads constant
streams (sensors, voice, user context, the world now and over the last
minute, global history) and emits local movements or global-plan updates
plus a representation the hosted voice narrates from; (b) a Model B that
turns an owner-recognized voice command into a steering injection
(revise / keep / queue) and turns A's stream into narration with the plan
history as memory; (c) tight speech↔movement coupling; (d) trainability in
simulation; (e) robust navigation, instruction-following-with-interruption
and conversation evaluations; (f) a well-instrumented sim-to-real harness.

## 2. Verdict, in one paragraph

**The architecture is right and the evidence for it is not yet
obtainable on this stack, because the substrate underneath it fails first.**
Every experiment that tried to demonstrate fluidity — a cloned streaming
controller (MA-1), spoken mid-task interruptions (NAV-INT-1), a narrating
voice over a plan queue (MB-1), the end-to-end door → sofa → keys loop
(LIT-1) — was refuted, and in every case the refutation was traced not to
the model idea but to the shipped navigation stack's terminal semantics,
re-targeting and grounding defects (NAV-GEN-1 showed the map geometry itself
is *not* the problem), or to the hosted voice's inability to follow a fact
contract. The design that survives is the dual-rate, receipt-grounded,
deterministic-authority version of Model A/B (§3), which the literature
also converges on; the trainable parts of it (a 10 Hz act policy, a
narration head, a steer classifier, an owner table) are all *measurable
with the instruments built this week* and none of them is *established*.
The next unit of work is not a bigger model; it is a navigator whose
arrival, stall and re-target mechanics are correct (and whose place grounding
never consults a demo lookup table), an executive with a plan queue, and a
voice that speaks only receipt-typed facts.

## 3. What is established (evidence grade in brackets; ✓ = independently reproduced)

| claim | evidence | grade |
|---|---|---|
| Nobody runs a language model at 10 Hz on a robot; deployed legged stacks are dual-rate (0.5–4 Hz language lane over a 10–50 Hz loop) and still stall until a committed-prefix/revisable-tail handoff is added | StreamVLN, DualVLN, NaVILA, TIC-VLA (Orin NX, 0.75 SR on a Go2), LiveVLN — all fetched and re-verified | literature [S/P] |
| On the AGX Orin a ≤ 2 B VLM is a ~2 Hz lane (1 Hz with an 8-frame memory); encoders cost 98–160 ms/frame; INT4 via bnb is slower, not faster | NVIDIA benchmarks, Jetson AI Lab, ETRI component study, EdgeReasoning | literature [S/P] |
| A native-duplex speech model runs on this desk at half its frame budget and takes an act stream for 0.56 M params, +0.9 ms p99 — and does not fit the Orin at bf16 | DS-1 (08-28), re-measured in isolation ✓ | desktop-sim ✓ |
| A small sequence model earns its place only where memory is required (look-back), and loses to a reflex table on reactive behaviours | BM-1 (08-28), reference rows reproduced ✓ | desktop-sim ✓ |
| Owner-specific taste is learnable as a per-owner table in ~25 clean jokes, not by a policy; the household reward is not clean and self-echo biases the learner against acting | FL-1, HS-1 (08-28), HS1c reproduced ✓ | desktop-sim / replay ✓ |
| The shipped navigator on procedurally generated held-out geometry: **0.65 strict / 0.69 band-entry on one plain directive (NAV-GEN-1, 450 episodes, reproduced 530/530 rows)**; MA-1's plain-episode band entry 0.775, and NAV-GEN-1's predicate on MA-1's own frames 0.750. **MA-1's "teacher SR 0.045" was a gold-predicate artefact** (5-frame settle never observable; erratum in `model-a-stream-1/VERDICT_FABLE.md`) — geometry is not the problem | NAV-GEN-1 + panel ✓ | desktop-sim ✓ |
| A mid-route re-target to the bench fails `semantic_target_unreachable` on every run and the robot does not move on re-issue | LIT-1 artifacts (6/6 runs), NAV-INT-1 (bench 0/2 from rest, 11/29 legs system-failed-but-arrived) ✓ | desktop-sim ✓ |
| Amend-cue admission is 7/14; explicit directives cancel goal 1; there is no plan queue (the parked resume intent is consumed on commit); resume = re-issue at 1.3–1.5× path | NAV-INT-1 tier, code-verified by parcel-6c | desktop-sim + code |
| A keyword steer classifier reaches 0.83 on a blind set (queue 0.67, clarify 0.80) | NAV-INT-1, blind set authored and hash-frozen by me | replay |
| The hosted voice (gpt-realtime-2.1-mini, text) grounds 0.61–0.73 with a plan-queue whisper and invents actions; a scripted responder scores 1.00 and a local 7B 0.96 on the same scorer | MB-1 (120 hosted scenarios, $1.33) | replay / hosted-live |
| Today's whisperer has no class for a plan acceptance and never constructs a reroute; the voice structurally cannot say "Sure, I'll check the sofa" from receipts | MB-1 executor + parcel-6c line-level verification | code ✓ |
| Deterministic harness code narrated "I've reached the bench" on failed receipts 5/5 — the false-terminal class is not an LLM-only failure | LIT-1 artifacts; Sol's audit; my re-read ✓ | desktop-sim ✓ |
| The loop itself works: sim + runtime + whisper + fake/hosted voice, every hop timestamped, local switch ≈ 0.32 s, replayable | LIT-1 (5/5 structurally identical receipt sequences) ✓ | desktop-sim ✓ |
| The conversation baselines are exact and pinned (25/174/0/66; duplex 7/7 at 35 ms); the acoustic gate crashes on a negative offset (fix recorded) | CONV-1 ✓ | replay ✓ |
| A Model A cloned from the failing teacher learns nothing usable (3.7 %); the run also had an oracle leak, a scorer window wider than its mask, and a post-hoc gold band | MA-1; Sol's audit; my code checks ✓ | desktop-sim (invalid as model evidence) |
| Independently (Sol, DMC-1): a learned duplex mission-control head reached 1,496/1,500 procedural missions where the deterministic L0 reached 1,500/1,500, emitted 3,781 raw-unsafe proposals and 296 wrong-route moves; the temporal GRU beat the snapshot MLP by 0.019 macro-F1 against a frozen 0.05 promotion margin, and the generator leaked authored cues → explicit temporal logic champion, learned heads shadow-only | `SOL_METHODICAL_ASSESSMENT_DRAFT.md` §"DMC-1", `duplex-mission-control-1/VERDICT.md` (not re-run by me) | desktop-sim [Sol] |

### Independent convergence

Sol's assessment (`SOL_METHODICAL_ASSESSMENT_DRAFT.md`, `DUPLEX_PRODUCTION_ARCHITECTURE.md`, `TRAINING_AND_DATA_PLAN.md`), written in parallel on separate experiments (DMC-1, DT-2/3, DSP-2, product-evals, LHO/LIT audits), reaches the same three conclusions by a different route: the A/B split is right only inside a typed multi-rate authority system (A proposes, never owns joints/STOP/completion; B is two separately scored jobs — owner-qualified steering and receipt-backed narration); the learned candidates have not earned execution scope (DMC-1 row above); autonomous physical motion is NO-GO with an observe-only / motors-disabled mount conditional on a reviewed checklist. Where we differ is emphasis, not direction: Sol's P0 leads with authority/measurement gaps and dynamic-human prediction; mine leads with navigator generalization and the voice fact contract. Both P0 lists are compatible and neither contains model training.

## 4. Verdict per element of the question

**(a) Model A — trainable, fully duplex, streams in, motion + narration out.**
*Design verdict: correct as a dual-rate object; not demonstrated.* The
literature and the Orin numbers fix the shape: a 10 Hz act-token loop
(BM-1's family or a LiDAR-ray policy in REASAN's shape) under a 0.5–2 Hz
plan lane, joined by a committed-prefix/revisable-tail contract, with the
narration representation a *closed witnessed vocabulary* whose terminal
tokens carry no authority. The one attempt to learn the 10 Hz loop from the
product (MA-1) was refuted and invalid — because the teacher succeeds 4.5 %
of the time on new geometry and because the harness leaked oracle state.
**Trainability in simulation is therefore unproven for navigation and
proven-in-shape only for social behaviour (BM-1).** NAV-GEN-1 then showed
the teacher's failure is neither geometry nor clearance: single directives
succeed 0.65–0.75 on generated scenes; MA-1's 4.5 % was its own gold
artefact; the real losses are stalls with the route still planned,
unattributed `semantic_target_unreachable`, and one second-oracle grounding
defect (§7).

**(b) Model B — steering injection and narration.** *Design verdict:
correct as two deterministic functions plus a gate; the steering half is
blocked by product mechanics, the narration half by the hosted model's
behaviour.* Steering: admission 0.75 (amend-cue 0.50), no queue, resume =
re-issue, classifier 0.83 blind. Narration: free-form hosted wording fails
the fact contract (0.61–0.73; 45 flags) while a scripted responder passes
(1.00) and a local 7B nearly does (0.96) — so the contract, not the
provider, should own the facts. MB-2 measured the receipt-typed
speech-act + constrained-paraphrase design on the same scorer: the contract
passes every fact gate the hosted model failed (§7).

**(c) Tight speech↔movement coupling.** *Measured, and it is a
product-mechanics problem before a model problem.* Local switch latency is
≈ 0.32 s and admission latency 12 ms; the coupling breaks at the terminal:
the executive says `failed` where the robot arrived (11/29 bench legs), the
harness says "reached" where it failed (5/5), and the voice has no receipt
kind for a new goal at all. Coupling is a *receipt-typing* problem.

**(d) Trainable in simulation.** *Yes for the pieces that were trained
(BM-1's social policy, FL-1's tables, MA-1's mechanics); no for the claim
that the sim teaches navigation fluidity, until the navigator generalizes
and the harness's causality defects (oracle leak, applied-action labels,
executive-in-the-loop resume) are fixed — which is exactly Sol's MA-2
probe.* The 08-28 `SIM_TRAINING_PLAN.md` stands, with S1 re-ordered behind a
navigator fix.

**(e) Robust evaluations.** *Delivered and reproducing:* NAV_INSTRUCT v4
(SR 0.20 / SPL 0.13 at QEV-1 on 08-25; Sol's two fresh 08-29 runs on the
same frozen recipe: 34/125 = 0.272 SR, SPL 0.206, identical episode digest —
the generalized-navigation profile is red either way) + an additive
interruption tier with a blind steering set;
MA-1's generated-geometry split (the first real held-out geometry the
product has been scored on); MB-1's receipt-grounded narration scorer with
a coverage term and blind adjudication; CONV-1's pinned corpus/duplex rows;
LIT-1's replayable loop. *Not comparable to any published number* — no
external benchmark scores spoken mid-task instruction changes on a moving
robot (InterruptBench/EchoChain/IHBench are the nearest, none embodied).

**(f) Well-lit sim-to-real harness.** *Built (LIT-1) and honest about its
tier:* every hop is sim/fake/hosted with a provenance column and a swap
table; the hosted narration tier did not deliver items on the live lane and
is unmeasured; a real hop (the XVF3800) needs the owner present. It is the
instrument every later claim should run through.

## 5. The decision I recommend

1. **Fix the substrate before training anything on it** (weeks 0–2):
   remove the demo POI table from place grounding on non-demo scenes
   (`configs/navigation/cities/demo_pois.yaml` answering "the crosswalk"
   → 42 false arrivals in NAV-GEN-1), fix the terminal stall class
   (`navigation_no_progress` with the route still planned, 68/157) and the
   arrival-authority disagreement, the two NAV-INT-1 defects, cue-robust
   amendment admission, and a plan-queue seam with lineage on the executive
   (one record schema, DMC-1's fact taxonomy). Do **not** spend the time on
   clearance tuning — NAV-GEN-1 showed the margin key is inert in effect and the
   brake sweep buys 2 points. None of these are model work.
2. **Give the voice a fact contract** (weeks 0–2): receipt-typed speech
   acts from the executive; a plan-acceptance whisper kind; a constructed
   reroute fact (decide `KIND_REROUTE`'s band first — it bypasses the spend
   ceiling as declared); a local paraphraser only behind a required-statement
   post-condition checker (MB-2: fallback 0.178, refusal deleted 15/15 when
   ungated, no naturalness win shown) — ship templates first; the owner/addressee gate as a local two-tier cascade.
3. **Then run the Model A causality probe** (Sol's MA-2: teacher ceiling,
   oracle isolation, exact applied-action labels, executive-in-the-loop
   resume, trace replay) and only then train a 10 Hz act policy — first on
   the social behaviours where BM-1 already showed the sequence model earns
   its place, then on navigation if the probe passes.
4. **Keep the hosted voice off every control path** (async tools, small
   text items, session rotation, Starlink-aware scheduling) and the duplex
   speech backbone as a desktop research track (DS-1).
5. **Evaluate with the wave's instruments, report pass^k with CIs, correct
   judges for chance, and never let a harness or a model say "arrived"
   without a receipt.** Physical motion stays NO-GO until the separate
   commissioning ladder, unchanged.

## 6. What would change this verdict

A navigator that succeeds ≥ 60 % on generated geometry under a *settle-
observing* strict gold (≥ 5 stopped frames inside the band, loop not
terminated on `done()`), with no POI second oracle and zero false arrivals —
it does 0.65–0.75 on single directives under a one-frame predicate, so this
is a terminal-stopping and grounding bar, not a geometry bar; a Model A that beats the reflex table by ≥ 0.10 on a valid
causality-clean run; a narration contract that holds ≥ 0.95 grounding with
a paraphraser at ≤ 1.5 s; and — for anything physical — hardware evidence
this program does not yet have.

## 7. Probe rows (filled at close)

**NAV-GEN-1 (verified; panel 4/5 unrefuted + one attribution refuted and
adopted; commissioned arm reproduced 530/530 rows in scratch;
`nav-gen-attribution-1/VERDICT.md`):** 5,510 headless episodes, 30 generated
scenes × 5 targets × 3 poses + an 80-episode frozen-block control, 6 arms, 0
collisions, byte-identical repeats. **The "4.5 % on unseen geometry" claim I
carried in §3 was wrong:** one plain directive on generated geometry
succeeds 0.651 strict / 0.689 band-entry; MA-1's plain-episode band entry is
0.775 and NAV-GEN-1's predicate on MA-1's frames gives 0.750. **MA-1's 0.045
is a harness artefact** — its 5-frame-settle gold can never be observed
because the loop breaks one frame after the navigator's `done()` (133/133
plain arrivals); the executor's alternative attribution to the interruption
script was refuted by the panel and is withdrawn. Generated scenes are *easier*
than the frozen block (0.651 vs 0.275). Failure histogram (157 strict
failures): 68 `navigation_no_progress` (stall watchdog, route still planned),
44 `semantic_target_unreachable`, 42 **false arrivals** — all 42 (and 42 of
the stalls) from one defect: "the crosswalk" resolves to the demo POI table's
hardcoded `crosswalk_a` [3.5, −0.6] (`configs/navigation/cities/demo_pois.yaml:38`)
on scenes where no such point exists, and the mission *announces arrival* a
median 3.25 m (worst 7.17 m) from any crosswalk. Clearance is not the lever:
`map_safety_margin_m` is inert in effect — read but unable to bind (the
planner is commissioned from the brake ring at `pipeline.py:1108-1120`, inflation 1.02 m, not NAV-CORE's 0.42 m),
and sweeping the brake 0.80 → 0.32 m buys +2 points because no goal band in
450 episodes is unstandable, while every sweep arm breaches the DESIGN's
stop-band clause (H-NG1a/b REFUTED, H-NG1c reproduced with its conclusion
inverted). 90/90 crosswalk episodes ground to the demo POI (six are
accidental successes).
**MB-2 (verified, `model-b-contract-2/VERDICT.md`):** templates-only
grounding 1.0000 / coverage 0.9688 / 0 invented / 0 premature / 15/15
capability refusals at 0.4 ms (H-MB2a MET; reproduced from a scratch copy);
template + local Qwen-7B paraphrase behind a post-condition checker: fallback
32/180 = 0.178 (honest range 0.150–0.178), coverage 0.9113, 0 invented after
the gate, TTFT p50 153 ms / total p50 0.72 s on CPU at load 52 (H-MB2b 5/6,
H-MB2c MET); naturalness preference 0.575 — UNMEASURED: the local judge picked the
first-shown option 30/40 times, so no preference for the paraphrase is shown. The
finding that matters: **the ungated paraphrase deleted the "I have no camera"
refusal on 15 of 15 keys turns while MB-1's grounding metric scored those
turns 1.0 — grounding is blind to omission.** The facts must live in a
receipt-typed contract; a paraphraser is an optional, checker-gated layer.
