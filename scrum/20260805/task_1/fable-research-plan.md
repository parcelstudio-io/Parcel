# Fable independent research plan — phased path to the installable companion prototype

**Date:** 2026-08-05 · **Author:** Fable (independent of Sol's A/B/C docs — research
prompts were locked before those were read) · **Research run:** workflow
`wf_44b643ea-490`, 3 parallel researchers + max-effort synthesis, 38 primary
sources verified online.

> **Note (owner amendment, 2026-08-05):** this document is the historical
> independent-research record. Its Phase-0 "procure now" and Phase-2 bench
> items were superseded the same day by the owner's decision to **buy
> hardware last and test in the simulator throughout** — see the
> Owner-amendment section of [ADJUDICATION.md](ADJUDICATION.md), which is
> the binding plan.

**Goal being planned for (owner's words):** a companion AI dog that navigates
seamlessly around cities and indoors with the owner, reacts naturally to
statements, looks around and identifies objects and places (sidewalks,
lampposts, shops, brand stores), with best-in-class tracking and collision
avoidance, real-time and low latency — ending in software the owner can
**install on a real Unitree**.

---

## 1. Ranked gap analysis (current checkout → goal)

Ranking = how much of the goal each gap blocks × how much work waits on it.

- **G1 — No real perception column exists.** Every "semantic" input in the
  product path is simulator metadata behind a typed adapter. No pixel
  detector, depth model, ReID, OCR, VPR, or camera driver; the D455 is not
  purchased; the MuJoCo CameraChannel is unbuilt. **Amendment to the standing
  hillclimb doc:** pull CameraChannel forward from "gates the model era" to
  Phase 1 — it also gates *low-viewpoint validation*: the Go2 camera rides
  ~35 cm off the ground, so storefront signs are seen at extreme upward
  angles and pedestrians appear legs-first; every off-the-shelf OCR/ReID/VPR
  number degrades and must be re-measured at that viewpoint before field
  trust.
- **G2 — The voice→behavior loop is designed but not closed.**
  `StimulusBus`/`ReactionArbiter` are pure, unwired modules; the
  suspend→resume transaction is incomplete (NavigateTo redispatch does not
  consume its stored `ResumeIntent`; `requires_fresh_observation` is
  unenforced; search→follow resumes via a legacy tuple — see
  `docs/PAUSE_SEMANTICS.md`); and the audio stack has never been acoustically
  operational (libportaudio2/Piper still uninstalled — backlog B1). The
  resume transaction is Phase-1 critical path because mid-task voice
  amendment sits directly on it.
- **G3 — Hardware/embedded reality gap.** No Go2, dock, or golden image; the
  10 Hz loop has never been timed on an Orin; the Sport supervisor is
  implemented but uncommissioned; no DDS adapters for `rt/utlidar` height map
  or `rt/uwbstate` (IDL confirmed present in unitree_sdk2). UWB owner-channel
  accuracy is publicly uncharacterized → treat "UWB primary" as a
  day-one-validated hypothesis with fusion designed so vision-ReID can become
  primary without contract change.
- **G4 — Outdoor global layer absent.** No GNSS, no OSM footway/Overture
  priors, no curb/crossing semantics, no crossing safety mode, no route
  memory. This is the entire city-capability gap — and it is purely additive
  to the grid_v1 authority (the shipped sidewalk-robot pattern: Serve,
  Starship, Coco all layer a global prior + sidewalk semantics over exactly
  Parcel's authority shape; none navigates end-to-end learned).
- **G5 — Dynamic-scene quality is bounded-CV only.** The SOTA fix is small:
  per-track short-horizon forecasts feeding the existing TTC gate
  (predicted-closest-approach), passing-side selection — not ORCA (its
  reciprocity assumption is documented to fail on real sidewalks; no shipped
  sidewalk robot uses it).
- **G6 — SemanticMemory2D / instance store (rungs 1–2) not implemented.**
  GOAT's ablation (SPL 0.64 → 0.19 without lifelong memory) says memory gates
  both search success and repeat efficiency; brand/place identity, grounded
  clarification, and hazard narration all read/write this store. Highest-
  leverage pure-sim work in the repo.
- **G7 — Eval gaps.** No low-viewpoint gates, no field-bag replay harness, no
  bench rig, no long-horizon headline metric. **Plus the known goal-
  calibration artifact:** latest candidate rows (0/8, 0/25) include episodes
  ending 6–26 cm from goal scored `planning_error` via `navigation_step_limit`
  — three disagreeing "arrived" definitions still inflate the 0% headline.
  The failure-attribution harness itself is a real asset; extend, don't
  replace.
- **G8 — Packaging/install.** Editable-checkout only; `prompts/`,
  `configs/skills/`, `configs/navigation/` are not package data; a divergent
  packaged fallback config exists; no containers, OTA, or commissioning
  wizard.

### New component-level evidence (2026-08-05, changes standing conclusions)

- **GuideNav is now MIT-released** (github.com/guidedogrobot-navigation/GuideNav,
  HRI 2026): teach-and-repeat on **exactly Go2 + D435i** — CosPlace-512 VPR +
  Reloc3r pose regression, 5 Hz, ~24 MB/km route memory, no GPS/lidar at nav
  time, 1.67 km autonomous routes, 100% user-study success over 4.94 km.
  Teach-and-repeat moves from "pattern to reimplement" to "adopt and adapt."
  Caveat: their compute was AGX Orin; profile Reloc3r on Orin NX 16GB first
  (fallback: VPR + odometry servoing).
- **CityWalker is already vendored** at `third_party/CityWalker` with registry
  YAML present and `build_navigator` correctly failing closed — the gap is
  exactly one tested inference adapter. (Apache-2.0; 77.3% real-world SR vs
  ViNT 62.5%; consumes GPS-coordinate waypoints — exactly what the OSM graph
  emits.)
- **PP-OCRv6** (June 2026, PaddleOCR 3.7, Apache-2.0): tiny 1.5M / small 7.7M
  params, +4.6/+5.1 pp over v5-server, **official ONNX variants** — the ARM64
  port burden largely disappears; keep the 1–2 Hz keyframe budget.
- **Overture Places**: ~75M records, monthly refresh, CDLA-P-2.0/Apache-2.0,
  one-line bbox extract — the free brand/POI prior (names, categories,
  **brand** fields, geocoords). Give brand-candidate tiles a refresh TTL.
- **MegaLoc** (CVPR-W 2025, MIT, torch.hub one-liner): single VPR model, SOTA
  indoor *and* outdoor — one embedder can serve route memory, region
  identity, and GPS-denied fallback.
- **Firmware pin concretized: ≥ V1.1.13** (CVE-2026-27509/27510 DDS RCEs
  patched there). DDS Domain 0 remains unauthenticated by design → the dock
  must firewall 192.168.123.0/24. WebRTC keying changes at 1.1.15+.
- **Scene text is the brand signal.** TextPlace/TextInPlace demonstrate
  localization by reading signs; OCR + Overture candidate matching + SigLIP-2
  logo similarity is the storefront cascade. Florence-2 (~1 s/image on T4) is
  remote-GPU enrichment only, never a 10 Hz perceptor.

## 2. Phased plan

Full details per phase in the synthesis record; phases gate default-runtime
entry, tracks run in parallel (section 3).

| P | Name | Core content | Exit evidence | Effort |
|---|---|---|---|---|
| 0 | Contract freeze, eval-first, procurement | Freeze 3 cross-track contracts (StimulusBus channel schema incl. **dialogue-state channel**; SE2Goal→GoalArbiter/PlanIR/pause-resume surface; DetectionMsg). Contract tests in CI. Rung-0 minival frozen nightly. **Unify the three "arrived" definitions** (goal-calibration artifact). Define headline metric (minutes-per-intervention, fixed 20-min mixed course) + voice latency budgets on /latency. **Procure now:** Go2 EDU (firmware pinned ≥1.1.13), **two** Orin NX 16GB docks (one sacrificial), D455, ZED-F9P GNSS + NTRIP, XVF3800 mic kit. ADRs for golden image + firmware pin. | Contract tests fail on injected violations; minival nightly with attribution; POs placed; ADRs merged | days |
| 1 | Four-track sim sprint + dock bench bring-up | **A:** rungs 1–5 (ScanBehavior, SemanticMemory2D, Grounder v2, SearchEntity, relations, honest-noisy adapter) + **close the resume transaction** + wire ReactionArbiter at 10 Hz. **B:** MuJoCo CameraChannel (D455 intrinsics, 35 cm mount) + NanoOWL-class detector + SigLIP-2 + BoT-SORT + PP-OCRv6 ONNX + MegaLoc, low-viewpoint gates, start in-domain SigLIP-2 fine-tune set. **C:** audio operational; DRAGON closed intent enum {pause, resume, faster, slower, stop, come, goal-amend} → executive pause path + CommandArbiter caps; dialogue-state publisher. **D:** flash sacrificial dock to JetPack 6.2.x golden image; compose skeleton with network-independent safety+control container; 10 Hz hot path timed on Orin NX; fix asset packaging. | Hillclimb gates on frozen minival (tier B ≥90%, tier C ≥70% & +10pp over nearest-frontier, tier E ≥90% honest); voice pause/speed/stop influence in-flight sim nav, ack ≤700 ms, zero gate violations; low-viewpoint gates recorded; dock hot path ≤176 ms median | weeks |
| 2 | Voice-behavior joins in sim; Go2 bench commissioning | Joins: **mid-task amendment** (pause → snapshot → replan → verified resume), **grounded clarification** (Grounder v2 AMBIGUOUS → question from stored attributes; UNSEEN → offer scan), **dialogue-state × T2** (gaze/gait/pace conditioning). Hardware: bench commissioning (dry-run default, dual e-stop, vx≤0.15 first); DDS adapters for height map/UWB/SportModeState; D455+XVF3800 mounted; **teleop sidewalk bags from day one**; replay bags on Orin NX; **UWB characterization vs vision truth**; commissioning wizard v0; first WoZ voice-UX sessions (Riek guidelines). | Amendment correctness on frozen paired split; clarification cuts dialogue rounds vs baseline; gaze-only tier passes live; bags replay ≤176 ms on-device; UWB report + primary-channel decision in docs/ | weeks |
| 3 | Minimal city set outdoors, leashed | All additive to A*+gate: GNSS+NTRIP covariance-gated fusion; OSM footway/crossing graph (osmnx) as topological waypoint proposer; Overture brand tiles; elevation_mapping_cupy (ROS-free core) fusing D455 + height map, curb = height discontinuity; BoT-SORT-ReID at 10 Hz with frame-skip-under-load; owner = UWB primary + ReID confirm (or inverted per P2 data); predicted-closest-approach gate; PP-OCRv6 keyframes + Overture fuzzy match + logo similarity → SemanticMemory2D; proactive narration ~10 m ahead; look-up scan poses; **hard geofence: no autonomous street crossing** — curb-stop + announcement + owner voice initiation via T1 suspend. | 20-min mixed course leashed with minutes-per-intervention baseline; curb-stop on 100% of mapped crossings, zero autonomous entries; storefront confirmation ≥90% precision at Go2 camera height; predictive gate beats range-only on paired scenarios; Tier-0 (onboard-only) sustains a full walk | weeks |
| 4 | Route memory + learned proposers (A/B, removable) | GuideNav-adapted teach-and-repeat for the owner's habitual walks (2 routes incl. indoor/outdoor boundary); CityWalker inference adapter A/B vs OSM-graph-only; VLFM value-map scorer replaces prior table in SearchEntity (rung 6); unleashed walks where lawful. | Repeat-route ≥90% over 10 runs/route, ≤1 intervention/km; CityWalker admitted only at ≥+5pp with no added gate interventions; VLFM ≥ prior table on tier C | weeks |
| 5 | Remote-GPU tier, VLA arm, productized install, long-horizon eval | Tailnet mesh; degradation ladder as **tested contract** (Tier 0 onboard / Tier 1 LAN GPU / Tier 2 cloud, tier-kill CI); NaVILA service (rung 7) A/B; OTA = versioned compose pulls with A/B rollback; commissioning wizard v1 (runtime refuses to start without valid record); "Parcel Lite" (WebRTC, AIR/PRO, ~3 Hz, no authority loop) scoped or formally deferred; 4-week owner-in-the-loop study on the headline metric. | Clean-dock install demoed flash→wizard→walk; NaVILA earns a slot only per ladder rule; 4-week trend published; tier-kill CI green | month+ |

## 3. Parallelization: four tracks, three contracts, two join waves

**Tracks:** **A** behavior/nav authority · **B** perception column · **C**
voice/dialogue · **D** eval + deploy infra. The only cross-track interfaces,
frozen in P0 and versioned after: (1) the 10 Hz StimulusBus channel schema,
(2) the typed-goal/plan executive surface (SE2Goal → GoalArbiter, PlanIR,
pause/resume API), (3) DetectionMsg (sim-noise adapter and real detector
indistinguishable). Evidence this scales: Nav2's plugin-server model, and the
ROS 2 contract-testing result that **62% of integration bugs are recallable
from interface contracts** (QoS/rate, frame, ownership).

**Dependency DAG (sequential edges):** detector → SemanticMemory2D →
SearchEntity → relation behaviors (GOAT: memory gates search — don't judge
SearchEntity before memory lands); instance store + voice → grounded
clarification; resume transaction + voice intents → mid-task amendment;
dialogue-state channel + wired T2 → gaze/pace conditioning; OCR + Overture →
brand behaviors; GNSS + OSM → crossing mode and CityWalker.
**Explicit non-edges:** city sidewalk nav does **not** depend on semantic
memory; amendment does **not** depend on SearchEntity; VLFM/NaVILA are
terminal optional leaves that must never become load-bearing (real-world VLN:
monolithic 61%→22% collapse vs hierarchical holding — the standing reason).
The three voice differentiators all join in Phase 2 — a full phase before the
semantic-search ladder completes. **The differentiator ships early.**

**Never parallelized (single owner, serialized):** reactive_safety/TTC gate
semantics; the executive resume transaction; contract schema changes; the
golden dock image + firmware pin (one-way doors, sacrificial dock only);
frozen eval packs (add, never mutate); MuJoCo scene edits that alter seeds.

**Cadence:** contract tests per PR; nightly frozen packs with attribution;
weekly all-track sim integration on one commit; biweekly hardware integration
from P2, weekly during P3.

## 4. Voice→behavior integration (eight concrete points)

1. **Closed intent enum → executive (DRAGON pattern, ships first).** {pause,
   resume, faster, slower, stop, come, goal-amend} → existing
   pause/resume + CommandArbiter velocity caps (voice priority 60 already
   outranks navigation 30). DRAGON: NLU 85.3% on noisy ASR with one-turn
   confirmation on destructive intents. Weeks, not months — substrate exists.
2. **Mid-task amendment = a new pause reason + a plan diff.** "Actually, the
   other bench" → T1 pause → snapshot {PlanIR, memory state, history} → LLM
   re-proposal → PlanValidator → resume consuming the stored ResumeIntent.
   Blocked on the resume transaction, not on any new mechanism.
3. **Grounded clarification triggered by memory ambiguity, not dialogue
   heuristics.** AMBIGUOUS → question generated from stored attributes and
   spatial relations ("the store on the left, or the one by the crosswalk?");
   UNSEEN → abstain + offer ScanBehavior. DRAGON: grounded follow-ups cut
   dialogue rounds 3.7 → 2.4 and doubled success; its other lesson — zero-shot
   grounding insufficient until a 544-pair in-domain fine-tune — is why the
   SigLIP-2 low-viewpoint fine-tune set starts in Phase 1.
4. **Dialogue-state as a first-class 10 Hz stimulus channel (white-space
   differentiator).** {speaking|listening|thinking, engagement} on the bus;
   T2 maps it to gaze mode (mutual gaze listening, aversion thinking — half
   built as ReactionHooks), gait cadence, bounded walking-pace offset; planner
   sees conversation-engaged and defers non-urgent autonomy mid-sentence. No
   published companion product integrates duplex dialogue state into a
   quadruped's gaze/gait arbiter.
5. **The crossing interaction.** Curb-stop → "curb — say go when you're
   ready" → owner voice initiation resumes through T1. Guide-dog practice
   (handler owns crossing initiative) turns the hardest safety problem into
   the signature companion moment. Invariant: voice can initiate leaving the
   curb only when the unconditional gate concurs; voice can never release a
   proximity stop.
6. **Hazard/place narration from memory.** Instances carry hazard class + TTL
   (Coco's decay pattern: scooter hours, construction weeks); on repeat walks
   the voice narrates ~10 m ahead, each narration emits a T2 stimulus so the
   dog glances at what it names — speech and gaze agree because they share
   the bus.
7. **Latency choreography, not a faster planner.** Collision reflex in the
   10 Hz loop (≤100 ms); barge-in teardown ≤200 ms; T2 gaze ≤300 ms; verbal
   ack ≤700 ms (HRI: >700 ms reads as hesitation, >2 s as breakdown); the
   1–2 s LLM replan is masked by ack + gaze shift. The fast tiers buy the
   slow planner its time.
8. **The safety invariant.** Voice/dialogue may only: propose typed plans,
   pause/suspend, lower speed caps, select pre-authored reactions, and
   initiate resume where the gate concurs. The reactive gate, TTC brake, and
   E-stop latch are unreachable from any voice path.

## 5. Eval program (extends the existing attribution harness)

1. **Contract tests** (CI, every PR): schema/frame/rate/TTL/staleness at
   every boundary — the 62%-recallable bug class that breaks parallel work.
2. **Per-capability gates before each join** (the field's documented regret
   is success-rate-only eval): existing hillclimb spec kept verbatim (SR/OSR,
   SPL, gate-intervention count, tiers A–E, oracle counterfactual replay,
   paired McNemar, Wilson CIs). **New packs:** low-viewpoint (OCR at upward
   angles, legs-first ReID, VPR@35 cm, curb from height map with D455
   dropped); predictive-gate paired scenarios; voice packs (amendment
   correctness, clarification rounds, ack/barge-in latency); UWB
   characterization protocol.
3. **Frozen integration scenario packs** (nightly MuJoCo): 8–12 scripted
   walk-with-me scenarios spanning voice interjection, summons-suspend-
   resume, search, curb-stop, collision events, tier-kill. Versioned, never
   mutated.
4. **Replay harness (the missing sim-to-real middle rung):** teleop real
   bags (D455, height map, UWB, IMU, audio) from day one of hardware,
   replayed through the full stack **on the Orin NX**, asserting plan sanity
   + the ≤176 ms hot-path budget (cited Spot-stack median) + queue-never-
   builds headroom.
5. **Bench rig + staged live protocol** (MiniCPM Go2 template): stand tests →
   dry-run shadow → gaze-only → leashed low-speed (vx≤0.15 first) → free;
   dual e-stop and comms-loss auto-damp verified at every stage;
   commissioning record required to arm.
6. **Wizard-of-Oz + human-in-the-loop** (Riek guidelines): WoZ the unbuilt
   pieces inside otherwise-real sessions so the executive/arbiter/pause-
   resume machinery accumulates integrated hours from week one.

**Headline:** weekly fixed 20-minute mixed indoor/sidewalk course —
**minutes-per-intervention** — plus companion-nav and voice panels for
attribution. One number trends the product; panels explain movement.

## 6. Install-on-Unitree path

- **Target (decide now):** Go2 EDU + Orin NX 16GB dock is the only supported
  v1 platform. WebRTC ("Parcel Lite", AIR/PRO) is velocity+posture+video+
  lidar at ~3 Hz — explicitly no authority loop, demo tier only.
- **Golden image:** JetPack 6.2.x (TensorRT 10.x, current jetson-containers;
  MiniCPM Go2 deployment is the existence proof on exactly this hardware).
  The QSPI/UEFI flash is a **one-way door** — validate on the sacrificial
  dock, then freeze; installer restores, never mutates.
- **Packaging:** per-concern compose services on jetson-containers bases,
  systemd-launched. The **safety+control container (10 Hz loop, A*, gate,
  UWB follow) has zero network dependencies** and restarts independently.
  OTA = versioned image pulls with A/B rollback; dev iteration = rsync into
  bind-mounted source. Ship = golden image + compose bundle.
- **Compute placement (committed budgets):** onboard — reactive gate ≤50 ms
  sensor→command; NanoOWL-class detector + BoT-SORT at 10 Hz (frame-skip to
  5 Hz under load with motion-propagated tracks); SigLIP-2 embeddings
  ms-scale batched; PP-OCRv6 ONNX at 1–2 Hz keyframes. Offboard via tailnet
  WebSocket — VLFM scoring, NaVILA (~0.6 s/step, advisory + TTL),
  conversational VLM. On-device small VLMs (4–13 tok/s) are async annotation
  only, never in-loop.
- **Latency discipline:** hold the integrated onboard hot path under 176 ms;
  enforce v·τ by **capping commanded speed as a function of measured
  staleness** (at 1.5 m/s, every 100 ms = 15 cm); run every stage below max
  rate so queues never form.
- **Security/firmware:** pin ≥1.1.13; disable auto-update at commissioning;
  dock firewalls 192.168.123.0/24 (DDS is unauthenticated by design and
  pre-1.1.13 is RCE-able on home Wi-Fi); remote access tailnet-only.
- **Commissioning wizard (critical path, ours to build):** network join +
  tailnet enroll → firmware/SDK hard version gate → D455 extrinsics auto-cal
  + UWB pairing → interactive safety arming (dry-run default, per-tier
  consent, dual e-stop check) → comms-loss behavior demo. Runtime refuses to
  start without a valid machine-readable commissioning record.
- **FCC posture (standing conclusion honored):** accessory-plus-software on a
  customer-owned Go2; no firmware modification anywhere in the plan.

## 7. Top risks (full list in synthesis record)

1. JetPack one-way door bricks a dock → sacrificial dock first, frozen image.
2. Low-viewpoint degradation of every off-the-shelf model → sim gates before
   field trust; look-up scan poses; in-domain fine-tune.
3. UWB quality unknown → day-one characterization; fusion invertible.
4. Orin NX budget overrun via silent queuing → headroom scheduling,
   staleness-scaled speed cap, on-device replay asserts.
5. Audio stack unproven even on desktop → Phase-1 Track C; XVF3800 hardware
   AEC; WoZ validates UX before autonomy.
6. Street crossing is the liability concentrator → hard geofence v1;
   curb-stop + owner initiation; intelligent disobedience (voice never
   overrides the gate).
7. Learned proposers becoming load-bearing → ladder promotion rule (≥+5pp, no
   added gate interventions), removable by construction, Tier-0 walk must
   survive with all of them dead.
8. Firmware churn / DDS security → pin, compatibility matrix, dock firewall.

**Key sources:** GuideNav (MIT, HRI 2026) · CityWalker (CVPR 2025) · DRAGON
(RA-L 2024) · GOAT · VLFM · NaVILA · NanoOWL/Jetson benchmarks · MiniCPM Go2
deployment template · Falanga RA-L'19 latency physics · CMU-published Spot
stack 176 ms budget · ROS 2 contract-testing study (62%) · Riek WoZ
guidelines · Overture Places · OSM sidewalks · Unitree CVE-2026-27509/27510.
Full URL list in the synthesis record (`wf_44b643ea-490`).
