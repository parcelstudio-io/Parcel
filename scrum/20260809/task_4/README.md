# Sprint 2026-08-09 · task_4 — GENERALIZED VISUAL SEARCH arc (design, pending owner approval)

**Owner ask:** the search must be fully generalized — the dog uses its CAMERA to LOOK AROUND, an AI to DETERMINE WHERE the object is, and LOCKS ON to that destination.

**Research:** workflow `wf_b85944e7-e5a` (3 researchers + synthesis, repo-grounded, licenses verified). Full synthesis committed here as VSEARCH_SYNTHESIS.json.

## Where search is today (audited, live-verified)

The mission "camera" is an **oracle**: a geometric frustum reads ground-truth entity
positions (confidence 0.98, source `simulator_semantic_camera`); grounding is a **stub**
(the SigLIP "available" branch is a char-hash with meaningless cosine; the real path is
substring match over a closed 7-class/19-alias vocabulary); ScanBehavior is a fixed 2pi/8
spin. **The camera path already half-exists but is unwired:** `camera_channel/backends/
mujoco_egl.py` renders RGB+depth+segmentation via `mujoco.Renderer`, but nothing attaches
it on-mission, no open-vocab detector exists in `src` (grep-confirmed), and the EGL camera's
field-of-view is not set to the D455 intrinsics it advertises (a silent back-projection bug).

## The arc — four layers, all behind existing seams

 makes the owner's ask real behind seams that already land: (L1 LOOK) attach the EGL backend + run an open-vocab detector on rendered pixels and emit contracts.DetectionMsg from box+depth, so the mission's information source becomes what a detector SEES, not the GT list — the frustum GT is retired to an eval ruler only; (L2 DECIDE-WHAT) unstub SigLIP-2 (Apache-2.0 siglip2-base-patch16) so query<->crop cosine, not hash/substring, decides identity — deleting the substring FP path; (L3 DECIDE-WHERE) a VLFM-style SemanticValueMap2D co-registered with the occupancy grid turns the scripted spin into value-directed looking and turns SearchEntity's placeholder prior into an open-vocab value map + target-existence/belief-inheritance terms, seeded by a PLAN-TIME (never in-loop) commonsense prior; (L4 LOCK-ON) a detection-triggered, multi-view + M-of-N + false-positive-memory confirmation with a mo

## Card sequence (sol = new pure modules; opus = existing-file wiring)

| card | owner | depends on | gate (existing harness) |
|---|---|---|---|
| P0 render-real scope + honesty line (governs ev | owner_decision | none | Written ruling recorded in docs/ (extend STRATA_GENERALIZATION_PLAN.md anti-goals); no har |
| A1 SigLIP-2 text+image embedder (pure module, r | sol | none | tests/test_instructnav_grounding.py + nav_instruct Tier D (synonyms/ambiguity): synonym qu |
| A2 wire real embeddings into GrounderV2 + seman | opus | A1 | nav_instruct Tier D synonym/ambiguity SR up vs baseline; frozen v3 T0 baseline byte-equal  |
| B1 fix MuJoCo-EGL camera intrinsics to the D455 | sol | none | tests/test_k5_camera_detection_gates.py (existing K5 camera gate) + nav_instruct metamorph |
| B2 pixels->DetectionMsg adapter (classical loca | sol | B1,A1 | nav_instruct T-cam tier (E1): localization-error distribution (detected world point vs MuJ |
| E1 T-cam eval tier: splits, four metrics, froze | sol+opus | B2 | Mutation-of-evals panel: every detector mutant reddens >=1 harness; T0/T1 GT-source baseli |
| B3 open-vocab detector backend behind a Detecto | owner_decision | P0 | nav_instruct Tier A (visible <5m) SR parity vs oracle within a pre-registered margin at T- |
| B4 attach the camera on the mission path; T-cam | opus | B2,B3,E1 | nav_instruct T-cam runs end-to-end headless on the frozen render pack; T0/T1 (GT-source) f |
| C1 SemanticValueMap2D (VLFM value map, pure mod | sol | A1 | Unit tests on the cone/fusion math (VLFM formulas exact); nav_instruct Tier B (in-range ou |
| C2 value-directed ScanBehavior (replace the scr | opus | C1,B4 | nav_instruct Tier B SR >= fixed-spin baseline on paired seeds; attention/base-lease conten |
| C3 SearchEntity FrontierScorer reads the value  | opus | C1 | nav_instruct Tier C (beyond the block) SR >= +10pp over the nearest-frontier baseline, pai |
| D1 multi-view + M-of-N confirmation + false-pos | sol | B2 | nav_instruct T-cam absent-target (Tier E) + a from-day-one FP tier: false-positive-arrival |
| D2 monocular metric localizer + covariance fuse | sol | B2 | nav_instruct T-cam localization-error distribution vs seg-truth centroid; metamorphic rigi |
| D3 SEARCH->NAVIGATE lock-on: detection-triggere | opus | D1,D2,B4 | nav_instruct Tier A/B/C SR at T-cam >= the oracle path within the pre-registered margin; d |
| D4 chance-constrained K0 membership under detec | opus | D2 | nav_instruct T0 byte-equal (zero-covariance path unchanged); T-cam boundary-fuzz near the  |

### Card details

**P0 — render-real scope + honesty line (governs every downstream claim)** [owner_decision] (dep: none):
Rule ONE thing before code: is any learned RECOGNITION trained/tuned in sim (then it needs domain randomization and a real re-earn), or is the sim camera strictly a proof of the pixels->bearing/range->grounding->lock-in MACHINERY + geometry + latency + FP-handling, with recognition accuracy deferred entirely to hardware? The literature is explicit that 'high performance on synthetic validation data alone is not a sufficient indicator of performance on real-world data' (2404.08778). Recommended stance: sim proves the pipeline against MuJoCo seg-truth as the ruler; recognition is hardware-last. This choice sets the exact does_not_prove strings (runner.py:86-90 already carries them) and whether MM-GDINO recall on non-photoreal frames is even in scope.

*Gate:* Written ruling recorded in docs/ (extend STRATA_GENERALIZATION_PLAN.md anti-goals); no harness — this is the honesty contract the E1 metrics and every T-cam does_not_prove annotation inherit.

**A1 — SigLIP-2 text+image embedder (pure module, real weights)** [sol] (dep: none):
New pure module (unstub instructnav/siglip.py or add instructnav/siglip2_embed.py) loading google/siglip2-base-patch16 (Apache-2.0, 86M, 768-dim) via transformers/open_clip: embed_text(str)->L2-normed vec and embed_image(crop)->L2-normed vec, cosine + threshold. Replaces _hash_embed (deterministic char-hash) with a real neural embedding whose cosine generalizes ('streetlight'~='lamppost' for free). Frozen contract: keep the EmbeddingMatch shape and the LOUD string_fallback branch for offline CI (weights absent => same bytes as today). Recalibrate the 0.24 threshold on known-absent trials since the cosine distribution changes.

*Gate:* tests/test_instructnav_grounding.py + nav_instruct Tier D (synonyms/ambiguity): synonym queries ground WITHOUT an alias-table entry; with weights absent the string-fallback path stays byte-identical (frozen v3 baseline unmoved).

**A2 — wire real embeddings into GrounderV2 + semantic_map._matches; delete the substring FP path** [opus] (dep: A1):
Existing-file wiring: route A1's text/image embeddings through grounding._rank_candidates and semantic_map._matches. DELETE the cross-class substring acceptance at grounding.py:190-193 ('_norm_token(label) in _norm_token(query)') and replace the _hash_embed(query) cosine at grounding.py:204 with the real text embedding, gated behind 'weights present' so CI on the fallback is unchanged. This is the concrete step that makes the AI 'determine what the object is' instead of a hash/substring coincidence.

*Gate:* nav_instruct Tier D synonym/ambiguity SR up vs baseline; frozen v3 T0 baseline byte-equal on the fallback path; differential-authority logging (runner scorer_arrival/system_arrival) shows zero new false_arrival from looser matching.

**B1 — fix MuJoCo-EGL camera intrinsics to the D455 contract + seg-truth self-check** [sol] (dep: none):
mujoco_egl.py renders via mjv_defaultFreeCamera whose fovy is NOT the advertised fx=fy=644 — depth back-projection is currently geometry-inconsistent and validate_envelope only checks metadata, not pixels. Fix: drive the render from an explicit intrinsic (fovy = 2*atan(H/(2*fy)), or a fixed MJCF camera with focal/principal/sensorsize/resolution per MuJoCo issue #1183) so the rendered projection matches fx=fy=644/cx=640/cy=360; keep offwidth/offheight>=1280x720 (already handled). Add a pure seg-buffer self-check: back-project a rendered box+depth and assert the world point lands on the true geom-id centroid from enable_segmentation_rendering().

*Gate:* tests/test_k5_camera_detection_gates.py (existing K5 camera gate) + nav_instruct metamorphic rigid-transform equivariance: a rotated/translated scene yields the same back-projected world point within tolerance; seg-truth centroid error < a pinned bound.

**B2 — pixels->DetectionMsg adapter (classical localizer, +covariance)** [sol] (dep: B1,A1):
New pure module detection_adapter/pixel_detections.py implementing OpenNav's recipe: for each detector box, segment->erode 3x3->Z-score(tau=2) depth-outlier reject->back-project X=(u-cx)*D/fx, Y=(v-cy)*D/fy->camera extrinsic->world; bearing_rad=atan2(u_center-cx, fx), range_m=metric depth at the eroded-mask centroid, score=detector conf, class_id=label, embedding=A1 crop embedding. Emit contracts.DetectionMsg (contracts/v1.py:1451, fields already exact). Attach a per-detection position covariance (sigma_range from the D455 quadratic model already in perception_chain.py:63, sigma_bearing from box-center pixel error) for D4. Optionally chain the existing DetectionNoiseAdapter as a stress post-stage only, never the clean path.

*Gate:* nav_instruct T-cam tier (E1): localization-error distribution (detected world point vs MuJoCo seg-truth centroid) under a frozen render pack; right-object rate from geom-id match.

**E1 — T-cam eval tier: splits, four metrics, frozen render packs, detector mutants (extend nav_instruct only)** [sol+opus] (dep: B2):
Add T-cam as a NoiseTier value in perception_chain.from_tier (sol) and install it via use_perception_chain in runtime.py:4740-4770 (opus) — same seam as T0/T1, no new harness. Add three split axes to unseen_split.py: novel-noun (HM3D-OVON Val-Unseen/Seen-Synonyms discipline), novel-scene (scene_gen.py procedural layouts), look-around-required (target in-range but outside the initial frustum). Emit four metrics as DERIVED rows via rescore.py (frozen traces untouched): (1) lock-on accuracy = committed instance == queried instance, (2) localization error vs seg-truth, (3) false-positive-arrival count via the existing differential-authority scorer-arrival=>navigator-arrival implication, (4) absent-target honesty (VLN-NF: pass = bounded search then honest_not_found_reply). Freeze seeded MuJoCo render packs so the tier is reproducible; add detector mutants to scripts/mutation_panel.py (drop a true detection, inject a phantom box, offset depth) — each must redden >=1 harness.

*Gate:* Mutation-of-evals panel: every detector mutant reddens >=1 harness; T0/T1 GT-source baselines byte-equal (T-cam is additive/opt-in); each metric carries a P0 does_not_prove string.

**B3 — open-vocab detector backend behind a Detector protocol + deterministic seg-truth CI stub** [owner_decision] (dep: P0):
Commit the sim-loop detector: MM-Grounding-DINO (Apache-2.0, LVIS-minival AP 41.4, plain PyTorch on the RTX 5000, reproducible) is the recommended pick; do NOT ship YOLO-World/YOLOE (GPL-3.0/AGPL-3.0). Reserve Grounding DINO 1.5 Edge (Apache, 75.2 FPS TensorRT, 36.2 AP, >10 FPS Orin NX) / NanoOWL (predict(image,text=[...],threshold), 9.81ms patch32 on AGX Orin, TensorRT) as the hardware-era swap behind the identical DetectionMsg contract. Owner call = the model dependency + GPU budget + whether MM-GDINO recall on non-photoreal MuJoCo frames is in scope (per P0). Ship a deterministic offline stub detector that reads MuJoCo seg-truth to emit boxes so CI + the whole pipeline stay exercisable with no model download and no GL.

*Gate:* nav_instruct Tier A (visible <5m) SR parity vs oracle within a pre-registered margin at T-cam using the real detector; CI green on the seg-truth stub detector (no model, no EGL).

**B4 — attach the camera on the mission path; T-cam becomes the semantic ingress** [opus] (dep: B2,B3,E1):
Existing-file wiring in runtime.py (~4800) and headless_city.py (~931): build the EGL backend via camera_channel.backends.factory.open_camera_backend(model,data), CameraChannel.attach_backend(), capture per tick, run B3 detector -> B2 pixel_detections -> DetectionMsg, and feed those through the SAME perception chain so extras['semantic_candidates'] now derive from RENDERED PIXELS instead of observation.semantic_objects. Nothing downstream (GrounderV2, arbiter, K0) knows the source changed (semantic_map.semantic_candidates_from_observation stays the one ingress). Keep visible_city_semantics available ONLY as the eval ruler, never as mission input under T-cam. MUJOCO_GL=egl must be set before the first mujoco import (factory.probe_mujoco_offscreen enforces).

*Gate:* nav_instruct T-cam runs end-to-end headless on the frozen render pack; T0/T1 (GT-source) frozen baselines byte-equal (additive tier); differential authority holds scorer-arrival=>navigator-arrival.

**C1 — SemanticValueMap2D (VLFM value map, pure module)** [sol] (dep: A1):
New pure module co-registered with the RollingGrid occupancy grid (INSTRUCTION_NAV_HILLCLIMB component #1). Each look paints the FOV cone with a value in [0,1] = SigLIP-2 cosine(query, frame/crop) and a per-pixel confidence cos^2((theta/(theta_fov/2))*(pi/2)) (1 on the optical axis, ~0 at the edge), fused across overlapping looks by confidence-weighted average v_new=(c_cur*v_cur+c_prev*v_prev)/(c_cur+c_prev). Frozen contract: write(cone,value,conf), read(cell)->(value,conf), unknown_fraction(region). This is the belief that makes 'I have not looked there yet' a queryable fact and generalizes search to any noun/layout.

*Gate:* Unit tests on the cone/fusion math (VLFM formulas exact); nav_instruct Tier B (in-range outside initial frustum) — a value-directed look finds in-range targets the fixed spin missed.

**C2 — value-directed ScanBehavior (replace the scripted 2pi/8 spin)** [opus] (dep: C1,B4):
Keep scan.full_turn_scan_spec ONLY as the VLFM-style initialization on first UNSEEN; after that choose the next dwell yaw/viewpoint by expected value gain over SemanticValueMap2D with a GP-UCB look-again-vs-commit rule (mu+sqrt(beta)*sigma; 2506.13367). Plan scan stops as SE2 viewpoints so base rotation (the Go2's only 'neck') is arbitrated through the same base-lease/ProposerBus as travel, and a glance (ATTENTION_STEERING_DESIGN) and a target scan share ONE belief map instead of fighting for the base.

*Gate:* nav_instruct Tier B SR >= fixed-spin baseline on paired seeds; attention/base-lease contention check (no glance trips SearchOwner); acoustic/attention loop shows summons SUSPENDS not cancels an in-flight scan.

**C3 — SearchEntity FrontierScorer reads the value map + target-existence/inheritance terms; plan-time prior** [opus] (dep: C1):
Swap search_entity.SIDEWALK_BORDERS_ROAD_PRIORS for prior_fn = value-map lookup for the queried noun and coverage_fn = map unknown-fraction (reuse SearchOwner._information_gain / _reachable_radius / _already_covered verbatim). Add RPF-Search's two missing frontier terms: V_e (target-existence belief — a Gaussian/particle prior over where the noun likely is) and V_p (belief inheritance across scans). Source the semantic prior at PLAN TIME only (LGR pattern: cache an LLM/SigLIP relevance score per queried-noun x region-class), never a model in the 10Hz loop — learned proposes at plan time, A* disposes.

*Gate:* nav_instruct Tier C (beyond the block) SR >= +10pp over the nearest-frontier baseline, paired-seed McNemar p<0.05 (hillclimb rung-3 gate); zero runtime model calls in the control tick.

**D1 — multi-view + M-of-N confirmation + false-positive memory (pure module)** [sol] (dep: B2):
New pure module: M-of-N (3-of-5, reuse SearchOwner.reacquire pattern) + SG-Nav-style multi-view re-observation accumulating a credibility score before commit, PLUS a false-positive memory so a rejected box is not re-committed next scan. This is gap-filling the DOMINANT error once the oracle is removed — VLFM states it 'does not yet filter its detections ... and is thus still sensitive to false positives'; Perception-Matters shows temporal + uncertainty gating cuts FPR dramatically (e.g. 81.8%->15.6%, SR 15.8%->56.4%). Frozen contract: update(detection)->(confirmed, credibility, rejected_ids). Do NOT build IPDA — leave it as the documented existence-probability seam (perception_chain NoiseTier.existence_probability_source).

*Gate:* nav_instruct T-cam absent-target (Tier E) + a from-day-one FP tier: false-positive-arrival count held near zero; single-frame commits demonstrably rejected.

**D2 — monocular metric localizer + covariance fuse (pure module)** [sol] (dep: B2):
Reuse B2's depth back-projection to estimate the target's metric (x,y) from the confirmed box; fuse over the M confirming frames with a 1-2 state Kalman (STRATA Stratum-2) and emit position + covariance. This is PBVS-style metric commit — the correct choice for a STATIC landmark (calibration is exact in sim); do NOT build image-based visual servoing. Motion parallax across scan stops is the fallback only if depth is unreliable at range (the 0.35m mount looking up at trees/signs is the worst case — erosion+Z-score from B2 mitigates edge bleed).

*Gate:* nav_instruct T-cam localization-error distribution vs seg-truth centroid; metamorphic rigid-transform equivariance of the fused point; low_viewpoint gate on high-elevation targets.

**D3 — SEARCH->NAVIGATE lock-on: detection-triggered single SE2Goal via the arbiter** [opus] (dep: D1,D2,B4):
Replace near_arrival's frustum-hit-to-commit trigger with a DETECTION trigger: when D1 confirms and SigLIP similarity >= the recalibrated threshold, commit ONE SE2Goal{source, pose=(x,y,yaw-facing-target), confidence, TTL, plan_step_id} through the existing ProposerBus/GoalArbiter (route_memory/proposer.py, gate_enabled default off for learned proposers); grid_v1 A*+reactive gate disposes to the K0 1.0m band (object_near_goal_region). Mirrors VLFM's two-phase explore->approach switch and Parcel's scan->search->navigate ladder (recovery_for_outcome). The learned components PROPOSE the waypoint; classical authority DISPOSES.

*Gate:* nav_instruct Tier A/B/C SR at T-cam >= the oracle path within the pre-registered margin; differential authority scorer-arrival=>navigator-arrival holds (zero false_arrival) on the FP + absent tiers.

**D4 — chance-constrained K0 membership under detection covariance** [opus] (dep: D2):
Upgrade the single K0 predicate (instructnav.scoring.object_near_goal_region) from a boolean point-in-GoalRegion test to P(inside)>=0.9 under D2's position covariance (STRATA Stratum-1: reduces to today's boolean at zero covariance). This is the honest lock-in rule — the dog commits only when the localized point is confidently inside the band — and it keeps K0 the SINGLE arrival authority (no second predicate). No new arrival authority is created.

*Gate:* nav_instruct T0 byte-equal (zero-covariance path unchanged); T-cam boundary-fuzz near the arrival radius shows no false_arrival; noisy far detections no longer commit like crisp near ones.

## What sim proves vs what hardware must re-earn (the honesty line)

PROVABLE IN MUJOCO SIM NOW (legitimate evidence): the entire generalized-search MACHINERY end-to-end — attach EGL backend -> open-vocab detector on rendered RGB -> box+depth back-projection -> DetectionMsg -> SigLIP-2 embedding grounding -> value-map look-around -> multi-view/M-of-N confirmation -> single SE2Goal -> K0 arrival. Specifically sim proves: (1) GEOMETRY correctness — intrinsics/fovy consistency and depth-unprojection accuracy, measured against MuJoCo's ground-truth segmentation buffer (enable_segmentation_rendering gives per-pixel geom-id/type), which is the sim-legitimate ruler: 'given a frame whose true labels we know, does box->world-point->grounder->commit point at the right entity?' — right-object rate, IoU, localization error; (2) FALSE-POSITIVE HANDLING logic — that M-of-N + multi-view + FP-memory + chance-constrained K0 actually suppress hallucinated arrivals (the FP-arrival count is the honest headline once the oracle is gone); (3) the PROPOSE/DISPOSE contract, K0 single-authority, arbiter routing, and TTL/staleness discipline; (4) relative CADENCE/latency budget of a detector-in-the-loop (edge study: NanoOWL patch32 9.81ms, YOLO-World-S 26.07ms, best detect+seg pipeline 47.51 FPS on AGX Orin — use to keep the detector OFF the 10Hz path, async-propose). NOT PROVEN IN SIM (must be re-earned on hardware, per P0): photoreal RECOGNITION accuracy — MuJoCo textures are non-photoreal, so an open-vocab detector's recall/precision on rendered frames is NOT evidence of D455 field recognition ('high performance on synthetic validation data alone is not a sufficient indicator of performance on real-world data due to the inherent domain gap'); real D455 optics + depth noise at the 0.35m Go2 mount; MM-GDINO recall on real street objects. Honest mitigations if any recognition is trained in sim: domain-randomize textures/lighting/pose (DR reaches 86-99% mAP@50 on real held-out sets in the literature) and report a SEPARATE real held-out number — never fold the s

## The eval tier (T-cam, inside nav_instruct — no new harness)

Camera/detection tier = 'T-cam', a NEW NoiseTier value inside the EXISTING nav_instruct harness (no new harness): registered in perception_chain.from_tier (sol) and installed via use_perception_chain in runtime.py:4740-4770 (opus), exactly where T0/T1 already live. SPLITS (extend unseen_split.py, whose val_seen-vs-val_unseen GAP is already 'the headline number', regenerated against derived tables, never tuned against): (a) novel-noun — HM3D-OVON discipline with Val-Seen / Seen-Synonyms (SentenceBERT-similar) / Val-Unseen category sets; the seen->unseen SR gap is the generalization headline and the direct test that real SigLIP-2 embeddings (not string aliases) closed it; (b) novel-scene — scene_gen.py procedural layouts (ProcTHOR-style navigability rejection); (c) look-around-required — target in-range but outside the initial frustum, forcing the value-directed scan (Tier B) and, one block out, the frontier search (Tier C, >=+10pp over nearest-frontier, paired-seed McNemar). FOUR METRICS emitted as DERIVED rows via rescore.py (frozen traces untouched, no re-freeze): (1) lock-on accuracy = committed instance == queried instance; (2) localization error = detected world point vs MuJoCo seg-truth centroid (sim GT is the honest ruler); (3) false-positive-arrival count via the EXISTING differential-authority instrument (log scorer_arrival + system_arrival + authority_category every episode; assert scorer-arrival => navigator-arrival; any confident arrival on an absent-target episode is a scored failure); (4) absent-target honesty (VLN-NF: PASS = bounded evidence-grounded search then honest_not_found_reply(scanned,searched); Tier E). FROZEN PACKS: seeded MuJoCo render packs so T-cam is reproducible; T0/T1 GT-source baselines must stay byte-equal (T-cam is additive/opt-in). FALS

## Risks

- EGL free-camera intrinsics mismatch (B1): mujoco_egl uses mjv_defaultFreeCamera whose fovy != the advertised fx=fy=644, so depth back-projection is silently wrong today and validate_envelope only checks metadata, not pixel geometry — the seg-truth self-check is the only catch. Must land B1 before any DetectionMsg is trusted.
- False-positive-arrival becomes the DOMINANT error the instant the oracle is removed (VLFM's stated weakness). If D1 (multi-view/M-of-N/FP-memory) does not land WITH B4, T-cam SR regresses vs the oracle — the substring FP path (grounding.py:190-193) must also be deleted in A2 or it compounds.
- Render-real overclaim: MM-GDINO recall on non-photoreal MuJoCo frames may be poor, making the seg-truth stub detector the only reliable CI detector and any sim recognition number misleading. Enforce P0's does_not_prove; keep recognition accuracy a hardware-last claim.
- Latency: MM-Grounding-DINO in plain PyTorch may not hit the look-loop cadence on the RTX 5000 alongside sim (edge budget: heavy grounding models are the slow lane). Keep the detector OFF the 10Hz control tick — async propose into the arbiter — or the reactive gate starves.
- SigLIP-2 threshold recalibration: the 0.24 match_threshold was tuned for hash embeddings; real cosine distributions differ. Recalibrate on known-absent trials (STRATA) and re-gate Tier D, or grounding either over- or under-commits.
- Depth bleed at object edges from the 0.35m mount looking UP at trees/signs/lampposts is the worst case for the monocular localizer; OpenNav erosion(3x3)+Z-score(tau=2) mitigates but the low_viewpoint gate must stay binding.
- Frozen-baseline discipline: T-cam MUST be additive (T0/T1 byte-equal) or it dirties the frozen v3 packs and every later delta becomes uninterpretable (STRATA Wave-0 rule).
- Scope creep toward a runtime model in the loop: the value map + LGR priors are tempting to compute online. Keep priors PLAN-TIME cached (C3) and the value map a lightweight SigLIP cosine, or the 10Hz loop and the propose/dispose contract break.
- GL/headless fragility: MUJOCO_GL=egl must be set before the first mujoco import (factory enforces); CI has no GL, so the seg-truth stub detector + SyntheticCameraBackend path must stay green independent of the EGL path.
- Attention-vs-search base contention (C2): glance and scan share the Go2's only 'neck'. Without a single viewpoint arbiter over one belief map, a social glance can trip SearchOwner (ATTENTION_STEERING_DESIGN already warns of this).

## Anti-goals (binding)

- No new eval harness — T-cam is a NoiseTier + split axes inside nav_instruct; reuse runner.py differential-authority, unseen_split.py, scene_gen.py, metamorphic.py, rescore.py, mutation_panel.py, and the K5/low_viewpoint tests.
- No learned component in a DISPOSITIVE position — detector/SigLIP/value-map/frontier-scorer PROPOSE; grid_v1 A* + reactive gate remain the sole motion/safety disposers.
- K0 stays the SINGLE arrival authority — chance-constrained membership upgrades object_near_goal_region in place; do NOT add a second arrival predicate or a per-detector arrival rule.
- No IPDA yet — leave existence-probability as the documented seam (perception_chain NoiseTier.existence_probability_source); classical M-of-N + credibility is the confirmation.
- No image-based visual servoing / pixel-servo controller for static landmarks — commit a metric SE2Goal (PBVS-style); reserve servoing for a moving target or optional terminal fine-alignment only.
- No GPL/AGPL detector in the shippable path — MM-Grounding-DINO/NanoOWL/Grounding-DINO-1.5-Edge are Apache/permissive; NOT YOLO-World/YOLOE.
- No photorealistic sim and no claiming sim recognition == real recognition — seg-truth is the sim ruler; recognition accuracy is re-earned on hardware.
- Do NOT delete the GT frustum (city_semantics.visible_city_semantics) — demote it to the eval ruler; it is the counterfactual that attributes failures to vocabulary vs visibility vs exploration.
- No runtime LLM/VLM in the 10Hz loop — commonsense priors are cached at PLAN time (LGR); the value map is a lightweight cosine.
- No hardware before the sim proof, and no tuning against the stress (T2/T3) or unseen splits — frozen packs, paired seeds, never tuned against.

## Owner decisions required before dispatch

1. **P0 honesty ruling** — is any learned *recognition* tuned in sim (needs domain
   randomization + a hardware re-earn), or is the sim camera strictly a proof of the
   pixels->localize->ground->lock-on *machinery* with recognition accuracy deferred to
   hardware? Recommended: the latter (sim proves the pipeline against MuJoCo
   segmentation-truth as the ruler; recognition is hardware-last).
2. **B3 detector choice** — the open-vocab detector brings a model + license dependency
   (YOLO-World / NanoOWL / Grounding-DINO family). This is the only heavyweight external
   dependency in the arc; A1's SigLIP-2 is Apache-2.0/86M and low-risk.

**Independent of both decisions and immediately dispatchable on approval** (they close the
audit's SigLIP-stub gap directly, no detector/render dependency): **A1** (real SigLIP-2
embeddings) + **A2** (wire them in, delete the substring false-positive path) + **B1** (fix
the camera intrinsics). Everything else chains behind P0/B3.

**Status: awaiting owner approval + the two rulings.**