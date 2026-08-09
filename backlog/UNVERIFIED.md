# Unverified claims register

**Opened:** 2026-08-04 · Conventions in [README.md](README.md).

Everything here is code that exists and passes tests, but whose behaviour
nobody has confirmed against the thing it models. Ordered by how badly a wrong
assumption would hurt.

---

## U1 — Nothing has ever moved a real motor · **critical**

- **Claim:** Parcel navigates, follows, poses, and gestures.
- **Reality:** every number in this repository comes from simulation. The
  Unitree Sport supervisor has never run against hardware: SDK absent, NIC
  unconfigured, axes and frames uncommissioned, `allowed_modes` deliberately
  empty.
- **To verify:** velocity + E-stop bring-up on a physical Go2 through
  `ControlManager` only — never the joint path first. Confirm commanded vs
  measured SE2 velocity, and that a latched E-stop is feedback-confirmed.
- **Risk:** every latency, clearance, and success rate in the docs is a
  simulation result. Treat all of them as unvalidated until this closes.

## U2 — The simulator is kinematic, not dynamic · **critical**

- **Claim:** gait, pose, and expression previews show what the robot will do.
- **Reality:** `sim_control.PoseController` writes joint angles kinematically.
  There is no contact, slip, or balance model. Expression offsets are applied
  as an additive overlay on `qpos` — a real robot must absorb them through a
  balance controller that does not exist here.
- **To verify:** replay the same commands on hardware and compare foot
  placement and body attitude; specifically confirm the ±2 cm body-height and
  ±6° pitch expression clamps do not disturb stance.
- **Risk:** an expression amplitude that looks fine in sim could perturb
  balance on hardware. The clamps are argued, not measured.

## U3 — Prosody has never seen real speech · **major**

- **Claim:** `prosody.analyze_wav_chunk` finds the beats in the dog's voice.
- **Reality:** exercised only on synthetic acoustics — click trains, steady
  tones, and amplitude-modulated carriers. No Piper output, no human speech,
  no scored prosody corpus. Recall measured 50–75% on synthetic speech-like
  signals with varying F0, ~25% when F0 is constant (the acceptance rule is
  relative: "F0 above median **or** onset in top quartile").
- **To verify:** install Piper (blocked, see [BLOCKED.md](BLOCKED.md) B1),
  synthesize ~20 varied sentences, and check accent times against hand-marked
  stressed syllables. Target: accents land on perceptually stressed syllables
  at 1–3/s.
- **Risk:** nod timing could be systematically wrong on real TTS while every
  test stays green. The 3.46 ms `ApexToAccentError` is *scheduler* accuracy —
  it says nothing about whether the accents themselves are right.

## U4 — Semantic endpointing has never run a real model · **major**

- **Claim:** `speech.endpointing: semantic` gives ~200 ms turn commits.
- **Reality:** `onnxruntime` is not installed and neither model file exists.
  Every test drives `TurnEndpointer` through an injected `_infer`. Real
  Silero v6 / Smart Turn v3 accuracy and on-device latency are unknown. The
  config therefore ships defaulted to `energy`.
- **To verify:** `pip install onnxruntime`, fetch both weights, set
  `speech.endpointing: semantic`, and measure `TurnCommitLatency` over ~30
  real turns; compare false-commit rate against the energy path.
- **Risk:** the headline "~200 ms commit vs 500–800 ms fixed tail" win is
  projected from the model's published behaviour, not measured here.

## U5 — No audio device has ever been opened · **major**

- **Claim:** device selection by name/index works (`speech.input_device`).
- **Reality:** `libportaudio2` is absent, so `sounddevice` cannot import.
  Resolution logic is unit-tested against a stubbed device table only; the
  *unset* path and the loud-failure path are confirmed on this desktop, but no
  `InputStream` or `OutputStream` has ever been constructed.
- **To verify:** after the apt install (B1), run
  `.parcel/bin/python -c "import sounddevice; print(sounddevice.query_devices())"`,
  then start the panel in `speech.mode: audio` and confirm
  `/api/state → speech.input_device_detail` names the intended device.
- **Risk:** frame size, dtype, and blocksize negotiation with a real PortAudio
  backend is untested; a mismatch would surface only at first capture.

## U11 — Owner reacquisition has only ever searched a kinematic sim · **major**

- **Claim:** `SearchOwner` walks to the loss point, sweeps, and explores
  frontiers until the owner is back in view.
- **Reality:** the three states, the give-up budget, the confidence gate, and
  the deterministic trigger are unit- and loop-tested
  (`tests/test_search_owner.py`), but no run has ever *found* anyone: every
  reacquisition in the suite is a synthesized `OwnerTrack`. Two specific gaps.
  (a) The frontier stage scores information gain against a `RollingOccupancyGrid`
  this controller builds from the observation's own LiDAR scan — it is *not*
  the navigator's map, so the two can disagree about the same world, and with
  no calibrated scan the ranking degrades to coverage novelty (announced
  through `SearchDecision.degraded`, never silently). (b) `owner_max_speed_mps`
  (1.6) and the 45 s budget are argued from walking speed, not measured against
  a real owner walking out of frame.
- **To verify:** in a moving-owner scenario, occlude the owner behind a corner
  and log reacquisition rate and time-to-reacquire over ~20 trials; compare
  frontier candidates chosen against the navigator's grid at the same instants.
- **Risk:** the search can look correct in every test and still explore the
  wrong side of an obstacle, because its map is its own.

## U12 — Anticipatory following is inert in the shipped direct-follow mode · **major**

- **Claim:** card W2 makes the follower aim at where the owner is going, so
  band error on turns falls.
- **Reality:** the lead point is clamped so it never comes closer to the
  *measured* owner than `owner_keepout_m` (1.55 m = `person_stop_m` +
  `owner_collision_envelope_m`). Direct follow's `desired_distance_m` is
  1.60 m, so the lead budget is **0.05 m** — about 40 ms of lookahead at
  walking speed, i.e. nothing. Behind formation (1.90 m) gets 0.35 m, roughly
  0.29 s. The follow-bench rerun after this card is byte-identical to the
  baseline (6/6, 0 collisions, mean band fraction 0.85475) because every bench
  follow episode runs `direct`, and `follow_turn_corner` — the scenario W2
  exists for — is still at 0.4625. The clamp is deliberate: buying
  anticipation with owner clearance is not a trade this card is allowed to
  make. The mechanism, the lead-point geometry, and the clamp are all unit
  tested (`tests/test_follow_prediction.py`); the *product benefit* is not
  demonstrated anywhere.
- **Measured 2026-08-04 (card W9), and it confirms the above.** The
  `owner_turn_90` scenario was built specifically to give this claim its best
  chance: an obstacle-free apron, a clean 90° corner, and a turn window that
  cannot be diluted by the straight legs. Baseline → shipped is mean band
  error 0.0114 → 0.0120 m and time outside band 2.5 → 2.6 s, i.e. a hair
  *worse* and inside noise. There is no anticipation benefit to report.
- **To verify:** run the turn scenario in behind formation, where the lead
  budget is 0.35 m rather than 0.05 m, or revisit
  `owner_follow.desired_distance_m` with provenance and re-measure. Adding a
  behind-formation variant of `owner_turn_90` is the cheapest of the three and
  is the recommended next step. Do not report W2 as a following improvement
  until one of those exists.
- **Risk:** the snapshot says `prediction.enabled: true` on a robot whose
  direct-follow behaviour is unchanged, so the feature reads as landed when it
  is only wired.

## U13 — The dynamic-cost detour picks a side for the wrong reason · **major**

- **Claim:** card W4's planner routes around where a pedestrian is going to
  be, preferring to pass behind them.
- **Reality (corrected 2026-08-04 arbitration):** it does leave the predicted
  corridor — a straight-line route through a crossing pedestrian's rollout
  drops from peak cost 1.0 to under 0.25 (`tests/test_dynamic_layer.py`). But
  *which* side it takes is an artifact of geometry, not of lookahead decay.
  Measured on the default field, cost *behind* a +x pedestrian is lower than
  cost *in front* at equal range (≈0.94/0.30 vs 1.0/1.0 at 1.0/1.5 m); a
  stationary pedestrian with no rollout still produces the same northward
  detour when they sit south of the goal line. The earlier register text that
  blamed decay for making front-passing cheaper was **wrong** and is
  withdrawn. Two real defects remain: (1) default `agent_cost_at` saturates
  (weight sum ≈5.35 clipped to 1.0 → a multi-metre flat mesa, so A* falls
  back to path length inside the plateau), and (2) expressing a social
  "pass behind" preference needs the robot's arrival time in the query
  (`query_t`), which the frozen W3 contract does not expose. Route smoothing
  that ignores `_dynamic_cost` can also erase an A* detour after the fact.
- **To verify:** normalize lobe weights before clipping (restores gradient);
  keep dynamic exposure through smoothing; then add arrival-time-aware
  sampling and re-check the chosen side against the pedestrian's heading on
  the W9 cut-in scenario.
- **Risk:** a cut-in scenario could show fewer gate interventions while the
  robot is still cutting across paths for geometric rather than social
  reasons — better than the false decay story, still not companion-correct.

## U14 — The shaper's jerk reduction is a unit-level number · **minor**

- **Claim:** card W6 makes the robot move like an animal instead of a step
  function.
- **Reality:** the reduction is measured on a synthetic square-wave target
  through the configured limits — 16.64 → 1.69 m/s³ RMS jerk nominal (−89.8%)
  and 1.02 m/s³ in the calm profile (−93.8%). That is the shaper doing its
  job, not the robot moving better: `evals/companion_nav/` models the follow
  controller and the reactive gate, not the arbiter/`_dispatch_active` layer
  the shaper lives in, so no end-to-end jerk delta exists. The bench was rerun
  to confirm no regression (unchanged), which is the only half of the W6
  ledger row that is real evidence.
- **Largely resolved 2026-08-04 (card W9).** The bench runner grew the
  dispatch replica this entry asked for (pre-gate smoother → collision gate →
  predictive brake → shaper), and the end-to-end delta is now on the ledger:
  RMS commanded jerk fell in **all eleven** episodes, suite mean 0.9592 →
  0.5530 m/s³ (−42%), with hard collisions at zero and band membership
  unchanged. The largest single drop is `pedestrian_group` at −69%. As
  predicted, the frozen numbers moved: `pedestrian_group`'s
  `min_band_fraction` was re-calibrated 0.8 → 0.75 with provenance, because
  the newly-added production smoother costs it ~2.5 points.
- **Still open, and why this stays on the register:** the replica stops short
  of the arbiter, the control manager, and the SE2 HAL, so −42% is the
  shaper's contribution inside a partial dispatch path, not the robot's. The
  affect-modulated calm profile is also still unit-level only — no bench
  episode drives vocal arousal, so `calm_scale` has never been exercised
  closed-loop.
- **To verify the remainder:** script a speaking turn with low measured
  arousal into a follow episode and record the calm-profile jerk delta
  separately from the nominal one.
- **Risk:** quoting −90% jerk (the unit-level square-wave figure) as a product
  result still overstates it; −42% is the defensible number.

## U15 — The predictive brake does not reduce gate interventions · **major**

- **Claim:** card W4's time-to-collision gate makes the robot yield earlier, so
  the geometric proximity gate has less to catch — the acceptance criterion
  W9 was told to test was "reactive-gate interventions must *decrease* vs
  baseline".
- **Reality (refined 2026-08-04 arbitration):** on `pedestrian_cut_in_predictive`
  the *composed* post-TTC proximity state is 4 → 4 interventions / 2 → 2
  stops. The predictive gate does engage — min TTC goes from none to 1.688 s
  inside the 2.0 s brake band — and hard collisions stay at zero. But the W9
  metric counted the combined post-TTC state, so it cannot yet prove that
  *reactive* interventions fell (TTC interventions may replace them). Separately,
  `reactive_safety.py` already brakes on `nearest_person_ttc_s` (stop ≤0.8 s,
  slow below 1.8 s), so for a single tracked pedestrian the two brakes cover
  the same encounter and the new gate may still be shadowed even after the
  metric is split.
- **Where the new gate should still matter:** it scans *every* entry in
  `dynamic_agents`, whereas the geometric path brakes only for the one
  candidate `select_social_collision_candidate` nominates. A scene with two
  simultaneous threats is the case that would separate them — but the
  selector picks by earliest TTC, so constructing a decoy that wins nomination
  while being less urgent is not straightforward, and no such scenario exists.
- **To verify:** split pre-TTC vs post-TTC intervention counts in the bench;
  then either build a multi-threat scenario where the nominated candidate is
  not the binding one, or measure the two brakes' engagement times separately
  (the gate leads by roughly 0.8 s here on paper). Until then W4's gate is
  "engages, causes no harm", not "yields earlier".
- **Risk:** the ledger could be read as W4's gate being redundant. It is not
  redundant in the runtime — it covers tracks the social selector never
  nominates — but that coverage is unmeasured.

## U16 — The owner search terminates cleanly but never finds anybody · **major**

- **Claim:** card W7 makes the robot go and look for an owner it has lost
  instead of standing still.
- **Reality:** half of that is now proven and half is refuted.
  `owner_corner_loss` (card W9) reproduces the baseline exactly — the robot
  freezes at the instant of occlusion and stays frozen for the remaining 48 s
  of the episode, never reacquiring. With the search enabled the trigger
  fires on the lost timeout, all three phases run in order
  (`go_to_last_observed` → `sweep` → `frontier_search`), the 45 s budget is
  honoured, and the episode ends with `search_gave_up = true` — a clean
  terminal give-up rather than a hang. What it does **not** do is find the
  owner: total distance travelled while searching is 1.39 m. Both the goto and
  frontier phases were proportional controllers with no planner, so both drove
  straight at their target, met the building corner, and were throttled to a
  crawl by the obstacle gate (`approaching_last_observed_slowed`, then
  `frontier_proximity_stop`) until their timeouts expire.
- **Updated 2026-08-04 arbitration:** mobile phases now route through
  `RollingGridPlanner` (same A* stack as `grid_v1`) when a calibrated scan is
  available, falling back to proportional only when mapless. Re-run
  `owner_corner_loss` before treating U16 as closed — the machinery change is
  landed; the reacquire claim is not yet re-measured.
- **To verify:** re-run `owner_corner_loss` with the planner-backed search and
  require a finite time-to-reacquire. A search that cannot get round a wall is
  a search that only works in open rooms.
- **Risk:** "the search gave up" is currently indistinguishable in the
  telemetry from "the search looked properly and the owner was really gone".

## U17 — A closely following robot cannot visibly acknowledge you · **major**

- **Claim (backlog N8):** the expression stack orients the head to the owner
  when they start speaking, so the robot visibly acknowledges being addressed.
- **Reality:** it does, when it is allowed to — the W9 acknowledgment latency
  on `owner_turn_90` is 0.2 s, which is the orient reaction's 0.3 s ease
  arriving on schedule. But `ExpressionGate.mode` returns `MODE_OFF` whenever
  the proximity state is not clear, and during a follow the *owner themselves*
  sits inside the gate's `person_slow_m` radius, so the state is `slowing` for
  most of an episode. Measured `expression_gated_fraction` is 47% on
  `owner_turn_90` and 84% on `pedestrian_cut_in_predictive`. On the latter the
  acknowledgment latency is `null` outright: the robot was never permitted to
  react. This is shipped behaviour reproduced by the bench, not a bench
  artifact.
- **Nuance:** the rule is not obviously wrong — full-body expression while
  something is close deserves suppression. What looks wrong is applying it to
  the *head-only* channels, and applying it to the owner, who is the one being
  followed and the one doing the talking.
- **To verify:** decide whether owner proximity should gate expression at all
  (the gate already distinguishes an owner orbit elsewhere), then re-measure
  `expression_gated_fraction` and the latency on both scenarios.
- **Risk:** the Expression HUD will show a stack that looks healthy while the
  robot is, in practice, expressionless for most of every walk.

## U7 — The web viewer's JavaScript has never executed · **minor**

- **Claim:** `/viewer` renders gaze direction and the Expression HUD card.
- **Reality:** no JS runtime exists on this desktop (`node`, `deno`, `bun` all
  absent), so the edits were verified only by serving the page (HTTP 200,
  44,887 bytes, 8 `hudExpr` references) and re-reading the diff. Nobody has
  looked at the rendered page.
- **To verify:** open `/viewer` in a browser with the panel running; confirm
  the head/ear glyph swings with `head_yaw_rad` and the Expression card shows
  mode/producer/gaze/breath.
- **Risk:** a syntax error would blank the whole canvas, and the served-bytes
  check would still pass.

## U8 — Body breathing has never been seen in the MuJoCo viewer · **minor**

- **Claim:** the dog visibly breathes and shifts weight.
- **Reality:** confirmed numerically (±4 mm oscillation sampled live off
  `/api/state`, joint deltas unit-tested against the profile IK) but the
  MuJoCo viewer — the only place body height and pitch are actually visible —
  has not been opened since the expression overlay landed. The 2.5D web viewer
  deliberately shows numbers instead, because ±4 mm is sub-pixel there.
- **To verify:** run `parcel-sim`, stand the robot idle, and watch the torso.
- **Risk:** the sim-side `set_expression` overlay could be applying to the
  wrong joints in a way the unit tests' profile round-trip does not catch.

## U9 — B2 installer downloads were never fetched · **minor**

- **Claim:** `scripts/install_speech_services.sh` installs pinned, checksummed
  artifacts.
- **Reality:** pins and sizes come from GitHub/HuggingFace *metadata* APIs; no
  URL was actually retrieved. The one exception is `ggml-base.en.bin`, whose
  SHA256 was confirmed against the copy already in this repo. The Piper
  tarball layout is from documentation, not inspection, and its checksum is
  reported rather than enforced (rhasspy publishes none). The whisper.cpp
  build was never compiled. `shellcheck` is not installed, so the scripts were
  hand-checked against its rules.
- **To verify:** run the installer end to end once the toolchain exists (B1)
  and confirm every checksum gate passes.
- **Risk:** a moved URL or changed archive layout fails at first real use.

## U10 — Gestures have never executed on hardware · **minor**

- **Claim:** the curated emote catalog is safe to run.
- **Reality:** the allowlist excludes gaits, velocity skills, and postural
  settling, and dispatch is gated on `robot_stopped` — but every clip has only
  ever played in the kinematic sim. Joint velocity and acceleration limits are
  unchecked; the card's planned per-clip feasibility gates (joint limits,
  support-polygon stability) were deferred with the YAML schema upgrade.
- **To verify:** replay each admitted emote on hardware at intensity 1.0 and
  1.5 with a spotter, logging measured joint velocity against limits.
- **Risk:** an authored keyframe could demand a velocity the real actuators
  cannot deliver safely.

---

## Closed

### U6 — Emote tags fire at synthesis time, not playback time · closed 2026-08-04

Emotes no longer fire from `SentenceChunkedSynthesizer`. The synthesizer yields
`SpeechChunk` — audio that carries the emotes authored in its own sentence —
and `RobotRuntime._enqueue_speech_chunk` puts them on the `SpeakerSink`
playback-start token as `(track, epoch, emotes)`, the same anchor `BeatLayer`
already used. `_audio_chunk_started` fires them only when the token's epoch is
still current, so barge-in cancels pending gestures with the audio they belong
to. Text mode has no playback clock, so `_fire_text_mode_emotes` keeps firing
on reply.

Evidence (`tests/test_emote_skill.py`):

- `test_emote_fires_at_playback_start_not_at_synthesis` — enqueue fires
  nothing; the gesture appears only when `_audio_chunk_started` runs.
- `test_superseded_sentence_fires_no_emote` — a queued sentence whose epoch was
  superseded fires no emote at all.
- `test_text_only_path_fires_emotes_immediately` and
  `test_a_superseded_text_reply_fires_no_emote` — the no-audio path still lands
  on reply, and still respects supersession.
- `test_playback_start_survives_an_inadmissible_emote` — a rejected gesture
  costs the sentence neither its speech nor its nods.
- `test_streaming_attaches_each_emote_to_its_own_chunk` and
  `test_blocking_synthesize_strips_tags_and_keeps_their_emotes` — the tags
  travel with their sentence rather than firing at synthesis.

Still unverified: the *perceptual* claim that a gesture now looks synchronized
with the words. That needs real audio output, which U5 blocks.

## U18 — Go2 Euler/BodyHeight composition is unmeasured · **major**

- **Claim (task_4 O1):** HAL Option A (capability-gated expressive posture via
  SportClient `Euler`/`BodyHeight` while `Move` is active) is viable.
- **Reality:** only the spike *procedure* is written
  (`scrum/20260804/task_3/A-foundations.md`). No SportClient call has run on
  hardware; achieved-vs-commanded posture is unknown (Spot silently saturates).
- **To verify:** execute the spike after U1 velocity+E-stop bring-up; record
  achieved IMU/body pose at ≥50 Hz; apply the pass/fail table; write the
  Option A vs B decision.
- **Risk:** shipping Option A without the spike reproduces Spot-style silent
  saturation — glance/chuckle posture that never appears while walking.

## U19 — Attention foundations are not in the control loop · **major**

- **Claim (task_4 S4/S5):** stimulus bus + ReactionArbiter decide glances and
  chuckles with temperament-conditioned rates.
- **Reality:** pure modules + unit tests only. Nothing feeds the bus from the
  mic/prosody path; the arbiter is not ticked at 10 Hz; `/api/social` and
  episode logging are V4.
- **To verify:** land V4 wiring; run seeded ambient-talk-during-walk scenarios
  and confirm glance rate bands + zero collision increase (V7 gate).
- **Risk:** the frozen contracts can pass forever while the dog never glances.

## U20 — NavigateTo suspend→resume has proven unit defects · **blocker**

- **Claim (task_4 O4 exit):** suspending a running NavigateTo via the voice
  source, ticking, and resuming completes the mission with no duplicate
  dispatch.
- **Proven unit defects (arbitration 2026-08-04):** (1) executive `tick()`
  re-dispatched `suspended` tasks; (2) `pause_navigation` used
  `preempt("voice")` → STOP; (3) `_step_navigation` cleared the directive on
  `mission_paused`; (4) reconcile treated suspend as STOP without
  `ResumeIntent`. Must-fixes landed with unit pins for 1–4; full live-mission
  E2E (voice summons → arrive) still not run as one integration.
- **Fifth defect, found and fixed 2026-08-07 (N14).** The four above were all
  found by *unit* pins, and the composition-level one survived them: a spoken
  RESUME restored the channel and left the executive task `suspended`, so the
  next `_step_brain()` tick re-paused the channel (`reason="task_suspended"`)
  and the mission stayed parked. Fixed by joining the two halves —
  `TaskExecutive.resume_task_running` + `SemanticTaskRuntimeAdapter.adopt`,
  keyed on the suspend reason. Pinned at the product-path layer in
  `tests/test_closed_intent_product_path.py` (5 cases), not by unit mocks —
  which is the point: this item's own history says the unit layer does not
  see this class of defect.
- **To verify:** keep unit pins green; add/run full scripted integration when
  feasible; confirm ledger rows stay byte-identical afterward. **Still not
  run** as of 2026-08-07 — the product-path pins are a real `RobotRuntime`
  over a fake backend, so they compose route → registry → admission →
  executive → channel, but no physics and no live mission.
- **Risk:** lease re-acquire or double-dispatch bugs only show up when all
  three layers compose on a live mission.

## U21 — Duplex fillers have never been heard on real TTS · **major**

- **Claim (task_5 D-O1):** predictive + 700 ms watchdog fillers keep every
  slow turn under the 2 s audible ceiling with clause-boundary handoff.
  Watchdog/ceiling now key off TTS-queue / audible path (not LLM text alone);
  `FillerLatency` samples audible time; mid-filler handoff covered by a fake
  synthesizer unit test.
- **Reality:** still no Piper/hardware timing from end-of-turn to first
  audible filler sample on the robot. Text-mode and scripted clocks remain
  the primary green path.
- **To verify:** with Piper up, force a deliberative_plan turn and a stalled
  TTS turn; measure `FillerLatency` and confirm zero
  `ResponseCeilingBreach` while a human hears the filler before 2 s.
- **Risk:** the metric can stay green while fillers are late or clipped on
  real audio queues.

## U22 — D0 duplex frames never drove actuators · **major**

- **Claim (task_5 D-O2):** ACT stream continuity and shadow decode prove the
  frame contract is D1-ready. D0 producer now also logs gaze/skill/emote
  tokens alongside post-gate twists + fillers.
- **Reality:** D0 still derives frames FROM commanded events; the shadow
  consumer does not execute. Continuity is the producer clock, not a model
  that chose the acts.
- **To verify:** land D1 dual-head behind the same contract; A/B against D0
  on DUPLEX_V1; promote only when continuity + atomicity + nav gates hold
  with the consumer in live (non-shadow) mode.
- **Risk:** treating D0 logs as proof the robot "already streams acts" oversells
  readiness for a trained decoder.

## U23 — Duplex session logs are unreviewed for privacy/size · **minor**

- **Claim (task_5 D-O3):** `logs/duplex/*.jsonl` is a safe local D1 corpus
  under 2 MB/hour with a kill switch. Per-turn outcomes (TTFT, filler,
  barge-in) are now written from runtime when logging is on.
- **Reality:** writer + gitignore + design privacy note + turn outcomes exist;
  no hour-long session has been sized, and no operator review of retained
  transcripts. Rotate cap is still a file-size limit, not an hourly rate.
- **To verify:** run a 30–60 min companion session with logging on; confirm
  rotate triggers, disk budget, and that `duplex.logging: false` stops writes.
- **Risk:** unexpected PII retention or log growth on long demos.

## U24 — NAV_INSTRUCT_V1 SR still zero on minival · **major**

- **Claim (task_6 / K4):** grounding rewire (SemanticMemory2D + GrounderV2 +
  ScanBehavior + SearchEntity) fixes "go to the sidewalk" / bench / towards
  instructions.
- **Reality:** historical freeze minival SR = 0.0 (refusals + planning stalls).
  K4 Opus wired candidate recovery into `DirectiveNavigator` (unit/wiring tests
  green); baseline mode remains frustum-only. No family yet shows a measured
  SR win on the frozen split after this wiring.
- **To verify:** re-run paired baseline/candidate minival; promote only on
  seeded deltas with failure attribution (Tier B ≥90%, Tier C ≥70% & +10pp).
- **Risk:** treating "typed outcomes + recovery ladder wired" as navigation
  success.

## U28 — K4 PlanIR ScanBehavior/SearchEntity not bound in RobotRuntime · **major**

- **Claim (K4 Opus):** ScanBehavior / SearchEntity are PlanIR system skills
  with runtime-adapter dispatch + instructnav verifier.
- **Reality:** contracts, compiler, and adapter callbacks exist; navigator
  recovery inside `DirectiveNavigator` is the live path. `RobotRuntime` does
  not yet construct the adapter with navigator-bound `scan_behavior` /
  `search_entity` callbacks, so executive-authored recovery plans cannot
  dispatch those skills end-to-end in the default runtime.
- **Re-measured 2026-08-07 (runtime lane): unchanged.** The
  `SemanticTaskRuntimeAdapter(...)` construction in `runtime.py` passes
  `navigate`, `follow_formation`, `spatial_behavior`, `hold`, `vocalize`,
  `return_to_safe_pose`, `gesture`, `search_owner` — and no
  `scan_behavior` / `search_entity`. Not fixed this round; it is a card, not
  a hygiene edit.
- **To verify:** wire callbacks like SearchOwner; tick a system-authored
  ScanBehavior→SearchEntity→NavigateTo plan in headless sim to terminal.
- **Risk:** PlanIR admission looks complete while only navigator-internal
  recovery actually moves the base.

## U25 — SigLIP-2 weights missing; matcher degrades in grounder · **major** · closed 2026-08-09 (real ONNX weights landed)

- **Claim (task_6 N-C1):** SigLIP-2 B/16 is Grounder v2 embedding glue.
- **Reality:** `SigLIP2Matcher` is wired into `ObservationSemanticMap` and
  `GrounderV2`, but weights are not downloaded. Missing weights log a loud
  warning and the matcher falls back to string/alias match — not true cosine
  class matching. Do not treat synonym cells as embedding-solved.
- **To verify:** place Apache-2.0 SigLIP-2 B/16 under
  `~/.cache/parcel/siglip2-b16/` and re-run synonym / Tier D cells.
- **Risk:** synonym grounding looks solved in design while still string-only.
- **REAL PATH LANDED, WEIGHTS STILL ABSENT 2026-08-09 (card `siglip-real-embeddings`,
  A1+A2; `scrum/20260809/task_5/SIGLIP_REAL_STATUS.md`).** `siglip.py` no longer
  stubs the "available" branch with a char-hash: `SigLIP2Matcher` now does real
  `embed_text`/`embed_image` + neural cosine when `google/siglip2-base-patch16`
  (Apache-2.0, 768-dim) loads, and `available` means *a real embedder actually
  loaded*, not that a file exists. A2 routed it through
  `grounding._rank_candidates` and `semantic_map._matches` and **deleted the
  cross-class substring accept path** — but every real-path branch is gated
  behind `matcher.available`, so with weights absent the fallback is
  byte-identical to the old stub (proven: same-budget candidate-v3 minival A/B =
  0/25 per-episode trace mismatches, `episode_digest 919a0fea…` unchanged, 82
  frozen pins + the 997 embodied row green, ratchet green). **Still absent on
  this machine** (no cache, and `torch`/`transformers`/`PIL` not installed —
  offline, cannot fetch), so the neural path is exercised only through a
  synthetic embedding fixture. On that fixture: the two Wave-2 cross-class
  `false_arrival`s (`object_goal-B-05` streetlight→tree, `object_goal-D-15`
  tree→lamppost) are rejected and `streetlamp`→lamppost grounds **without an
  alias row**; provisional real-path threshold `SIGLIP2_MATCH_THRESHOLD = 0.30`
  (the `0.24` hash-era gate is retired), with `calibrate_threshold` as the
  FAR/TAR harness.
- **RESOLVED 2026-08-09 — real ONNX weights landed on THIS machine (card
  `siglip-real-embeddings` follow-up; `scrum/20260809/task_5/SIGLIP_REAL_STATUS.md`
  §"ONNX real-weight run").** The prior deferral targeted torch/transformers
  (absent); the real fix runs the SigLIP-2 int8 ONNX encoders under
  **onnxruntime** (already in `.parcel`), exactly how the audio stack runs
  Silero/smart-turn — no torch, no sudo. `scripts/fetch_siglip2.sh` (sha-pinned)
  landed `text_model_int8.onnx` (283 MB) + `vision_model_int8.onnx` (94 MB) +
  tokenizer under `~/.cache/parcel/siglip2-b16`; new module
  `instructnav/siglip2_onnx.py` tokenizes with the `tokenizers` rust wheel
  (pip-installed, no torch) and preprocesses images in numpy (no PIL). The real
  path is **opt-in behind `PARCEL_SIGLIP2_ONNX`** so merely landing weights never
  flips the suite/mission onto a ~28 ms/query model.
  - **Real calibration (scene vocab, int8):** SigLIP text↔text cosines cluster
    HIGH & overlapping (present [0.844, 0.991] vs cross-class [0.759, 0.927]) — the
    old `0.30` provisional would accept everything. Recalibrated
    `SIGLIP2_MATCH_THRESHOLD = 0.90` (sits above streetlight/tree 0.869 &
    tree/lamppost 0.872 → both refused, below streetlight/lamppost 0.962 → kept).
    FAR/TAR curve in the status doc.
  - **Deferred gate RAN with weights (candidate v3 minival, real ONNX):**
    **false_arrival 2 → 0** (both `object_goal-B-05` & `object_goal-D-15`);
    overall **SR 0.20 → 0.28**, SPL 0.160 → 0.240, **no regressions, no new
    false_arrivals**; differential-authority instrument shows verification NOT
    weakened (agreement 17→20, authority_disagreement 6→5, false_arrival 2→0).
    Tier-D headline SR flat 0.20→0.20 (D-15's wrong-object commitment becomes an
    honest `planning_error`, not a success — grounding fixed; its planning miss is
    a separate concern).
  - **Weights-absent / opt-out path byte-identical:** env-off candidate-v3 minival
    reproduces the frozen baseline exactly (`episode_digest 919a0fea…`, sr 0.20,
    spl 0.16016, false_arrival 2, authority histogram) and the frozen v2/v3 + 997
    embodied pins stay green.
  - **Honest boundary:** onnxruntime is CPU-only here (no CUDA provider);
    ~28 ms/query warm (label embeddings cached), ~990 s for the 25-episode minival
    vs ~25 s string — so grounding stays OFF the 10 Hz hot path (discrete
    grounding decision, async), never in-loop. Weak generic synonyms (seat≡bench
    0.873) are below 0.90 and rely on the curated alias table upstream, not the
    neural gate.

## U26 — Eval panel live mode does not re-place entities · **minor**

- **Claim (task_6 N-O4):** live mode adopts the episode (places entities, injects
  instruction) with goal region pre-drawn in `/viewer`.
- **Reality:** select/run APIs mark the GoalRegion and inject voice text; start
  pose / distractor placement hooks are not yet wired into the live sim.
  Headless mode applies `placement_overrides` / distractors / removals.
  `/api/evals/batch` runs the full minival (not scenario[0] only).
- **To verify:** click Live on a Tier B episode and confirm robot spawn + goal
  overlay + instruction dispatch match the episode spec.
- **Risk:** operators judge live UI runs as harness-equivalent.

## U27 — GuideNav/Reloc3r performance on Orin NX 16GB is extrapolated · **major**

- **Claim:** the 2026-08-05 final plan (scrum/20260805/task_1) adopts
  GuideNav-style teach-and-repeat for Phase-4 route memory at 5 Hz.
- **Reality:** GuideNav's published numbers (5 Hz, 1.67 km routes, 100%
  user-study success) were measured on an AGX Orin; our dock is Orin NX
  16GB. Reloc3r's license and NX-class fps are unchecked. P4 ships a **sim**
  route-memory / teach-and-repeat MVP (`parcel_robot.route_memory`) with
  StubVPREmbedder + gated SE2Goal proposers — not CosPlace/Reloc3r, not
  field-validated (HR-12).
- **To verify:** profile Reloc3r + CosPlace (or MegaLoc) on the actual dock
  before quoting 5 Hz; audit checkpoint licenses. Fallback recorded in
  plan: VPR + odometry servoing.
- **Risk:** route-memory latency budget could double, or a license could
  block product use.

## U28 — UWB owner channel is an uncharacterized hypothesis · **major**

- **Claim:** the final plan treats `rt/uwbstate` as the primary owner channel
  with ReID confirmation.
- **Reality:** Go2 UWB accuracy, multipath behavior, and indoor performance
  are publicly uncharacterized; no DDS adapter exists in the repo; Sol's
  independent plan omitted UWB entirely.
- **To verify:** Phase-2 characterization protocol (bearing/range vs vision
  ground truth, indoor/outdoor, occlusion, multipath). Fusion is designed so
  vision-ReID can become primary without contract change.
- **Risk:** if UWB is poor indoors, owner-following quality rests entirely on
  the unproven low-viewpoint ReID column.

## U29 — PP-OCRv6 edge numbers are vendor-reported · **minor**

- **Claim:** the plan budgets PP-OCRv6 tiny/small via official ONNX at 1–2 Hz
  keyframes on the Orin NX for storefront text.
- **Reality:** accuracy/latency figures come from the PaddlePaddle release
  blog; nothing has been run locally, and low-viewpoint (35 cm, upward-angle)
  recall is unmeasured on real pixels. K5 ships authored sim gate samples only.
  P3 adds storefront placard textures + fake OCR (CI) and an optional
  paddleocr path marked UNVERIFIED (`parcel_robot.storefront`); that still
  does not validate wild storefront precision or Orin timing (HR-4).
- **To verify:** Phase-1 low-viewpoint gate pack on MuJoCo renders, then
  on-device / day-one D455 bag replay (HR-4); optional local paddleocr on
  synthetic placards is sim evidence only.
- **Risk:** storefront recognition rate could miss the ≥90% Phase-3 gate,
  pushing brand features to the remote tier.

## U30 — MuJoCo EGL CameraChannel is sim plumbing only · **major**

- **Claim:** Parcel can capture D455-shaped RGB/depth/seg from the sim camera.
- **Reality:** Opus K5 adds `MujocoEglCameraBackend` (needs `MUJOCO_GL=egl`
  before first `import mujoco`) and a CI `SyntheticCameraBackend`. Neither is
  a commissioned RealSense; free-camera mount placement is approximate; CI
  defaults to synthetic patterned pixels.
- **To verify:** HR-4 — re-run the low-viewpoint gate pack on day-one D455
  bags; compare against sim gates; do not promote EGL greens as hardware.
- **Risk:** treating green CameraChannel tests as field perception readiness.

## U31 — NAV_INSTRUCT success is gated by a scorer/runner hold mismatch · **major**

- **Claim:** the NAV_INSTRUCT minival candidate row (SR 0.04, 1/25) measures
  instruction-following capability.
- **Reality:** it does not. `score_episode` requires an arrival **hold**
  (inside the GoalRegion, stopped, for `arrival_hold_s = 1.0 s`), but the
  headless runner terminates the episode on the mission's own
  `arrived_verified` — one 0.1 s tick after the first `stopped=True` sample.
  The hold window can therefore never accumulate. In the 2026-08-06 candidate
  run, **7 of 25 episodes finish at `distance_to_goal_m == 0.0`** and are still
  scored `success=False`. This is the same class of defect as D5's "three
  disagreeing arrived definitions", one layer down — the scorer and the runner
  disagree about when an episode *ends*.
- **Corrected bound (arbitration OB-6, 2026-08-06).** The first version of this
  entry claimed an upper bound of 8/25. That was wrong: it counted every
  `dtg == 0.0` row as hold-fixable. Only **4/25** are:

  | rows | state | hold-fixable? |
  |---|---|---|
  | 3 × `arrived_verified`, stopped in the last 2 samples (`region_goal-A`, `region_goal-B`, `object_goal-A`) | mission `arrived` | **yes** |
  | 1 × `follow_owner-D-15` | already `success=True` | already counted |
  | 4 × `circle_owner …` `spatial_step_limit` | mission `timed_out`, **zero** stopped samples in the last 15 | **no** — they are still moving at the step limit; a hold rule cannot rescue a trace that never stops. Correctly attributed `termination`. |

  So the honest statement is: 1/25 today, **at most 4/25** if the hold
  mismatch is fixed, and the other four are real termination failures.
- **To verify — two options, and the cheaper one invalidates nothing:**
  1. *Paired re-scoring (preferred).* The traces are persisted in the report
     JSON. Re-score the existing baseline and candidate traces under a
     corrected hold rule at the **same `runner_version`**, and write the
     results as **new derived rows**. The frozen rows are never touched, the
     comparison stays paired, and no re-freeze decision is needed.
  2. *Runner change.* Keep stepping (or emit synthetic stopped samples) for at
     least `arrival_hold_s` after a terminal stop, then re-freeze the baseline
     — because `nav-instruct-v1-baseline-20260805T070524Z` carries the same
     artifact, and the two rows are only comparable while both do.
- **Risk:** every NAV_INSTRUCT delta read today measures termination
  bookkeeping as well as navigation. Quoting 1/25 as a capability number
  understates the stack and mis-attributes up to 3 rows to L4 planning.
- **MEASURED 2026-08-06 (Wave 0, W0-A) — option 1 executed; the bound holds.**
  `evals/nav_instruct/rescore.py` re-scores the persisted traces of both runs
  (same `runner_version` `nav-instruct-v1.1-k0-arrival`, same
  `episode_digest cf4d5384…`) under a documented derived rule,
  **`hold-or-trace-end-v1`**: arrived iff *(a)* the frozen 1.0 s inside-and-
  stopped hold accumulates, **or** *(b)* the trace **ends** inside-and-stopped
  and was **not** cut off by the step limit (no `step_limit` flag / no
  `navigation_step_limit` note on the final sample). Branch (b) is the
  correction — the hold is unobservable, not unmet — and the step-limit
  exclusion is what stops it crediting a trace that merely ran out of budget.

  | run | frozen rule | derived rule | flips |
  |---|---|---|---|
  | baseline `…20260805T070524Z` | 0.04 (1/25) | **0.12 (3/25)** | `region_goal-A-00`, `object_goal-A-00` |
  | candidate `…20260806T070335Z` | 0.04 (1/25) | **0.16 (4/25)** | `region_goal-A-00`, `region_goal-B-05`, `object_goal-A-00` |

  The candidate lands exactly on the corrected 4/25 bound; the retracted 8/25
  is unreachable. Every flip has `mission_status="arrived"`,
  `reason="arrived_verified"`, and a **0.1 s** observed trailing hold against
  the 1.0 s the frozen rule demands — that 0.9 s gap *is* U31. The four
  `circle_owner … spatial_step_limit` rows are confirmed **not** hold-fixable
  (inside the goal disc, `trailing_hold_s = 0.0`, still moving at the budget);
  they stay `termination` and are separately logged as
  `authority_disagreement` (scorer-arrival without system-arrival).
- **Frozen rows untouched.** The derived results are appended to
  `evals/nav_instruct/results/ledger.jsonl` as new
  `kind="derived_rescoring"` rows carrying `parent_run_id`; the seven
  pre-existing rows are byte-identical (sha256 of the prefix pinned in
  `tests/test_nav_instruct_rescoring.py`). No re-freeze was needed or made.
- **Status: measurement closed, defect open.** What is now known is the honest
  size of the mismatch (2 rows baseline, 3 rows candidate, ≤4/25 ceiling) and
  that the numbers are paired. What is *not* fixed is the runner: it still
  terminates one tick after `arrived_verified`, so the next measured run
  reproduces the same understatement. Derived rows are diagnostics — they
  assume a robot stopped in the goal would have stayed there — and can never
  replace a frozen baseline.
- **Owner:** K0 arrival-authority card, for option 2 (keep stepping for
  `arrival_hold_s` after a terminal stop, then re-freeze **both** rows
  together). That is a behaviour change and was out of scope for Wave 0.
- **CLOSED WITH EVIDENCE 2026-08-07 (bundled re-freeze, episode set v2).**
  Owner-approved. `hold-or-trace-end-v1` is now the NAV_INSTRUCT runner's
  default arrival rule (`evals/nav_instruct/runner.py`,
  `DEFAULT_ARRIVAL_RULE`), and a **new** baseline version carries it:
  episode set **v2**, digest
  `a17c04dbec43a1749386c304060fb479a71f27d4b51b8c1b0fbb949753fc563d`, files in
  `evals/nav_instruct/episodes/v2/`, two new ledger rows marked
  `baseline_version: "v2"`. **v1 is untouched** — digest still `cf4d5384…`,
  the two frozen reports byte-identical, the first nine ledger lines
  byte-identical (`dab60242…`, pinned in
  `tests/test_nav_instruct_episodes_v2.py`).
  Measured on today's tree, correction (c) alone: **baseline SR 0.04 → 0.16**
  (3 flips: `region_goal-A-00`, `object_goal-A-00`, `object_goal-D-15`),
  **candidate SR 0.04 → 0.08** (1 flip: `object_goal-A-00`). Every v2 episode
  still records `frozen_rule_success`, so the superseded rule can never be
  hidden by the new one.
- **What is still not fixed, and is now the whole of U31's residue:** the
  runner still terminates one tick after `arrived_verified`, so branch (b) of
  the rule still *assumes* the unobserved 0.9 s rather than measuring it. The
  re-freeze made that assumption the labelled default; it did not make it a
  measurement. Option 2 (keep stepping after a terminal stop) remains the real
  fix and now costs a v3, not a v2.
  Continuity record: `evals/nav_instruct/EPISODES_V2_CONTINUITY.md`.

## U32 — A mission claimed arrival 3.2 m from the goal · **major**

- **Claim:** `mission_status="arrived"` with `reason="arrived_verified"` means
  the robot is at the goal.
- **Reality:** in the 2026-08-06 candidate run, episode
  `nav-object_goal-D-15-109547e2` ("walk towards the tree") reports
  `mission_status="arrived"`, `reason="arrived_verified"`, `grounding_outcome
  RESOLVED` — and the independent K0 GoalRegion predicate measures
  **`distance_to_goal_m = 3.19954703210991`**. `oracle_success` is `false` too,
  so the trace never entered the region at any point; this is not a hold
  artifact and is **not** covered by U31. The navigator's own terminal
  verification and the K0 arrival authority disagree by 3.2 m, and the
  navigator is the one that is wrong.
- **Why it is separate and worse than U31:** U31 is a *missed* success (the
  system is at the goal and the scorer says no). This is a *false* success —
  the claim-without-predicate class the voice→nav e2e gate exists to catch
  ("claim without predicate fails, and vice versa",
  `tests/test_voice_nav_e2e.py`). NAV_INSTRUCT currently scores it as a
  `planning_error`, which hides it: the row looks like a navigation shortfall
  rather than a verification defect.
- **To verify:** replay this episode and dump, per tick, the terminal-
  verification inputs against the `arrival_goal_region` in mission metadata;
  determine whether the `near`/`towards` relation predicate, the committed
  polygon authority, or the band anchor is the disagreeing party. Then add a
  scorer check that flags *any* episode with `mission_status == "arrived"` and
  `dtg` outside the goal region as a distinct failure class, so a false
  arrival can never again be counted as a planning error.
- **Risk:** a robot that says "I've arrived" 3.2 m away is the failure mode the
  whole arrival-authority card (D5/K0) was created to eliminate, and today it
  is invisible in the headline SR because it is bucketed with genuine planning
  failures.
- **HALF CLOSED 2026-08-06 (Wave 0, W0-B/W0-C) — it is now visible and named.**
  `FailureClass.FALSE_ARRIVAL` exists (`instructnav/scoring.py`, scorer version
  `instructnav-scoring-v1.2-differential-authority`). Precedence is
  refusal → grounding → search → control → **false_arrival** → termination →
  planning, so a claim contradicted by the K0 predicate can never fall through
  to `planning_error` again; attribution is L6 (terminal verification is the
  disagreeing party). Epsilon: **`ARRIVAL_BOUNDARY_EPSILON_M = 0.05 m`**, a
  symmetric boundary tolerance — a claim inside it is quantisation
  (`tolerated_boundary`), not a false arrival. It is ~20× smaller than the
  narrowest arrival band in the system, so it cannot swallow a real split.
  Measured on the persisted traces, `nav-object_goal-D-15-109547e2` lands in
  `false_arrival` in **both** runs (candidate dtg 3.1995 m, baseline dtg
  3.206 m) — so it is not a candidate-only regression. It was the only
  reclassified row: the success set is byte-identical before and after
  (property test over both persisted reports).
- **Differential logging (instrument 5) is live in all three harnesses.**
  Every episode of `evals/nav_instruct`, `evals/walk_with_me`, and
  `tests/test_voice_nav_e2e.py` records BOTH verdicts — `scorer_arrival` (K0
  predicate on the final pose, no hold) and `system_arrival` (the mission's own
  claim) — plus an `AuthorityCategory`, into episode records and ledger rows.
  A missing system verdict is `unknown`, never a fabricated agreement. The e2e
  helper `_assert_authorities_agree` hard-gates only the cases that already
  assert success, so no case's pass/xfail status moved.
- **REPLAYED 2026-08-07 (Lane D). The navigator is not the disagreeing party —
  the goal is.** The tick-by-tick replay W0-B asked for was run
  (`scrum/20260806/task_3/LANE_D_STATUS.md`, "Two findings"). At the episode's
  start pose, `HeadlessCityWorld.observe()` returns `bldg_2`, `bldg_3`,
  `bldg_4`, `lamp_post_1`, `planter_2` and **`tree_2` at (5.0, 3.1)**.
  `tree_1` — the entity the episode's `GoalRegion` is anchored to, at
  **(−5.0, 3.15)** — is **not visible at all**. The instruction is "walk
  towards *the* tree"; the scene has two; the navigator grounds the only one it
  can see, walks towards it, and verifies `towards tree_2` correctly. It emits
  `arrived_verified` because it *has* arrived, at the tree it was shown.
  So the disagreeing party is none of the three candidates named above (band
  predicate / committed polygon / band anchor): it is the **episode
  specification**, which anchors a definite-article goal to an unobservable
  instance while an equally valid one is in frustum. **No amount of perception
  work removes this row.** The fix is in `evals/nav_instruct/generator.py`
  (anchor to a visible instance, or make the instruction disambiguate) and it
  is a re-freeze card — sequence it with U31 option 2 and W0-D's scene-truth
  adoption so the baseline is re-frozen once.
  **Consequence for the plan:** the stratum-2 gate "zero `false_arrival` rows
  at T0/T1" is **not achievable by Lane D** and should be re-owned. (Lane D's
  T1 run does show 0 — but only because detector noise prevented the claim,
  which is not a fix.)
- **A SECOND mis-specified episode, found the same way and unambiguous.**
  `nav-object_goal-B-05-0ee314d5` reads, in full: instruction **"walk towards
  the streetlight"**, goal region `relative_band` with
  **`anchor_entity='tree_1'`** at (−5.0, 3.15). The episode asks for a
  streetlight and scores against a *tree* — and against an instance that is not
  visible from its start pose (−0.4, −0.25), whose frame contains `bldg_3`,
  `bldg_4`, `bldg_6`, `planter_2` and `tree_2`. It scored
  `navigation_step_limit` at dtg 5.284 m before Lane D and `arrived_verified`
  at 5.353 m after; both are ~5.3 m from a tree nobody asked about. **So the
  `false_arrival` count is 2 and both rows are eval-specification defects.**
  The count is not currently a measurement of arrival honesty.
- **Found in the same replay, unrelated but recorded:** `planter_2` and
  `tree_2` occupy the **identical** position (5.0, 3.1). Belongs with W0-D's
  scene-truth transcription deltas.
- **CLOSED WITH EVIDENCE 2026-08-07 (bundled re-freeze, episode set v2) — the
  class is now a real measurement.** Both mis-specified rows are fixed in v2,
  by *rules* rather than row overrides:
  word-boundary class matching (`"tree" in "walk towards the streetlight"` was
  `True` — "s\[tree\]tlight"; that substring test is the entire B-05 defect)
  and visible-instance anchoring for definite references (D-15's "*the* tree"
  now anchors to the tree in frame, using the world's own 70°/12 m visibility
  predicate, pinned equal to it by test).
  Measured on today's tree, v1 → v2, same code:

  | run | `false_arrival` rows | what they are |
  |---|---|---|
  | baseline v1 | 2 (`object_goal-B-05`, `object_goal-D-15`) | both eval-spec defects |
  | baseline **v2** | **1** (`object_goal-B-05`) | **genuine** — asks for a lamppost, scored against a lamppost, mission still claims `arrived_verified` at **dtg 0.3164 m** outside the band |
  | candidate v1 | 1 | eval-spec defect |
  | candidate **v2** | **1** (`object_goal-D-15`) | **genuine** — claims `arrived_verified` at **dtg 2.9178 m**; it walked to the other tree and verified against that |

  `object_goal-D-15` under the **baseline** flips the other way: anchored to
  the tree it can see, it arrives at **dtg 0.0** and is a success. So the row
  that opened U32 was, in the end, a correct navigator and a wrong question.
- **What is still open.** Two genuine `false_arrival` rows remain (one per
  mode) and neither has been diagnosed. The plan's stratum-2 gate ("zero
  `false_arrival` at T0/T1") is now a **gate that can be read** — it reads 1 —
  where before v2 it was un-interpretable. Owner: Lane D / terminal
  verification.
- **The same defect class survives at `planter_1`/`planter_2`, deliberately
  unfixed.** `nav-object_relative-D-15` ("go next to the planter") is as
  definite and as plural as "the tree", and `planter_1` is equally not in frame
  from its start pose. It was left alone because `planter_2` is not in the v2
  landmark id set: the re-freeze carried the three approved corrections and no
  fourth. It costs one line (`V2_LANDMARK_IDS`) plus a v3 whenever it is
  wanted.

## U33 — Closed intents were counted as shipped without ever being spoken · **major**

- **Claim:** the closed-intent lane works. `COME` was explicitly re-fixed on
  2026-08-06 (arbitration OB-7: compile it to `relation="follow"`, not
  `behind`, so a stationary owner's summons stops being refused), and the
  sprint record lists it as landed alongside plain follow.
- **Reality:** until 2026-08-06 **nothing anywhere called
  `handle_text("come here")`** — not a unit test, not an integration test, not
  an eval. The tests that existed proved the *parser* (`parse_closed_intent`),
  the *cap* (`resolve_cap`) and the *sketch compiler* (`compile_plan_sketch`)
  in isolation, and never once ran the sketch through `PlanValidator`. On the
  live product path every "come here" dead-ended:
  `last_reasoning_source="local_plan_fallback"`,
  `last_reasoning_error="invalid_argument_value at $.steps[0].arguments: value
  must be one of ['behind']"`, reply "I couldn't admit that command as a safe
  plan yet." The cause was a **route/registry mismatch**: the deterministic
  router had no COME grammar, so these phrases fell through to `_PHYSICAL_CUE`
  → `deliberative_plan`, which selects the *model-facing* registry — and only
  the system registry admits the system-authored `relation="follow"`
  (`validator.py` `system_authored` gate, arbitration OB-2). The OB-7 fix was
  real and correct; it was simply unreachable from the product bar.
- **Fixed and pinned (2026-08-06, NAV_E2E SLIM-1):** router rule
  `come_to_owner` routes the exact closed-intent phrases to `direct_skill`
  (membership read from `parse_closed_intent`, so there is no second copy of
  the grammar); regression tests in `tests/test_brain_router.py` (including
  the negation/compound cases that must *not* widen) and
  `tests/test_runtime.py::test_come_here_admits_the_system_approach_sketch`;
  product-path case
  `tests/test_voice_nav_e2e.py::test_come_here_closes_on_the_owner_and_stay_releases_the_hold`.
- **What stays unverified — the general claim, not this instance:** the other
  closed intents (`PAUSE`, `RESUME`, `FASTER`, `SLOWER`, `GOAL_AMEND`) have
  the same shape of coverage that hid this one: parser + cap tested, the
  route→registry→admission composition not. `GOAL_AMEND` is the highest risk
  because it is the only other one that touches plan authority.
- **To verify:** for every `ClosedIntent`, assert the router's route for its
  exact phrases and drive `handle_text` end to end through admission, then
  freeze the route in `evals/companion/brain_v1/router_cases.jsonl` (which
  today contains **no** `come` case at all).
- **Risk:** the general defect is not "one bad enum" — it is that a
  component-tested lane can be reported as landed while being unreachable in
  the product. Anything whose acceptance evidence stops below `handle_text`
  should be assumed to have this failure mode until a product-path case says
  otherwise.
- **SWEPT 2026-08-07 (Lane C).** Every `ClosedIntent` now has a product-path
  `handle_text` case at the runtime seam:
  `tests/test_closed_intent_product_path.py` (35 passed, 1 xfail), asserting
  route → registry → admission → executive effect, plus a guard that a new
  enum member fails the file until it is covered. **Two more defects of the
  predicted shape were found by writing it:**
  1. **`handle_text("halt")` stopped nothing.** `parse_closed_intent` mapped
     it to `STOP`, but `EMERGENCY_STOP_PHRASES` was a *separate literal* that
     omitted it and the agent deliberately skips `STOP` inside the
     closed-intent handler — so the reply was
     "I did not understand that command" and the robot kept moving. **Fixed:**
     `EMERGENCY_STOP_PHRASES` and the router's `_EMERGENCY_STOP` are now both
     derived from `closed_intent_phrases(ClosedIntent.STOP)`. One stop
     grammar, pinned by
     `test_the_stop_grammar_has_exactly_one_source`.
  2. **`pause` / `resume` / `faster` / `slower` routed `conversation_only`.**
     The agent handled them correctly (it parses closed intents before
     consulting the route), so nothing misbehaved — but every consumer of
     `IntentFrame.route` saw an executive command labelled as chat, which is
     the same route/registry split that hid COME. **Fixed:** router rule
     `closed_intent:<name>` → `direct_skill`, membership read from
     `parse_closed_intent`. The amendment grammar was unified the same way
     (`_CORRECTION` ∪ the closed-intent GOAL_AMEND regex), so "the other one"
     no longer routes as conversation while the agent replans.
  - **N14 is closed (2026-08-07).** RESUME now restores the executive task
    record together with the channel; the xfail was flipped on measured
    behaviour and four more product-path cases were added around it. See
    [backlog/NEXT.md](NEXT.md) N14 — including a correction to the original
    measurement: the channel did **not** keep advancing, the next control tick
    re-paused it.
  - **Still open from this item:** freezing the eight routes in
    `evals/companion/brain_v1/router_cases.jsonl` (`evals/**` was off-limits
    to Lane C and to the runtime lane after it; the rows are written out in
    [scrum/20260806/task_3/LANE_C_HANDOFFS.md](../scrum/20260806/task_3/LANE_C_HANDOFFS.md)
    H4). Owner: whoever owns `evals/**`.
  - **Same shape, found 2026-08-07 one layer out — the clarify fallback wrote
    a cheque it could not cash.** `befriend the bench` offers *"I can go to it,
    sit next to it, or walk towards it"*; answering `go to it` compiled a
    mission whose navigation target was the literal word `it` and replied
    *"Okay—I'll go wait near it safely."* Components fine, composition wrong —
    exactly U33's pattern. Fixed: the clarification's referent binds the next
    turn's pronoun (one turn only), and a pronoun destination with no referent
    is asked about instead of admitted. Pinned by 8 cases in
    `tests/test_owner_and_settle_plans.py`.

---

## U34 — The pose seam models drift; nothing models localization · **major**

- **Opened:** 2026-08-07 (Lane B, stratum 1). Record:
  [scrum/20260806/task_3/LANE_B_STATUS.md](../scrum/20260806/task_3/LANE_B_STATUS.md).
- **Claim now in the tree:** `parcel_robot.pose` gives navigation a
  `PoseProvider` with REP-105 `MAP` / `ODOM` roles, covariance, and
  `HEALTHY / DEGRADED / LOST` health, and every migrated consumer names the
  frame it reads. `DriftingOdomProvider` injects Probabilistic-Robotics alpha
  odometry noise calibrated to the published DogLegs Go2 **yaw** band.
- **What is NOT claimed — this is a seam, not a localizer.** There is no SLAM,
  no EKF, no filter (a binding plan anti-goal). Under the drift provider,
  `MAP` is sim truth passed straight through: a *perfect global reference*
  standing in for a localizer so the frame binding can be measured. Nothing in
  the system estimates pose from sensors, and the shipping default
  (`TruthPoseProvider`) is ground truth on both frames. Stratum 1's real gap —
  "no localization exists" — is **unchanged**; what changed is that it now has
  one door instead of eleven.
- **The drift model is a stand-in for leg odometry, not a model of one.** No
  terrain dependence, no slip, no gait coupling, no IMU. It is calibrated on
  one canned 20 m trajectory against one published band.
- **Lane B hand-off 2 closed 2026-08-07 (runtime lane), and it uncovered a
  worse defect on the way.** The navigator's LOST hold leaves the mission
  *running* on purpose, but `RobotRuntime._step_navigation` had no branch for
  it: `MidLevelCommand(stop=True, note="pose_lost_hold")` fell into the
  generic stop arm, which cleared `_navigation_directive`, published
  `enabled=False`, restored the directive pace and emitted *"Navigation failed
  for sidewalk: pose_lost_hold"*. Measured on the product path. So the runtime
  destroyed a mission the navigator was holding open, and the mission could
  never resume. The hold is now a hold (`state="waiting"`, directive kept,
  plan step stays `running`), and the owner is told once per transition
  through the same utterance door the `Vocalize` skill uses. Pinned by
  `tests/test_pose_health_announcement.py` (6 cases).
- **Still true of that fix:** it is exercised by injecting the exact command
  `_pose_lost_hold` returns, not by a drift provider that actually reaches
  `LOST` in a live run. The announcement has never been spoken by real TTS.
- **Where the published bands could not both be met, and why.** DogLegs quotes
  0.5–1 %/distance translational *and* 0.2–0.5 deg/m yaw. Those cannot both
  describe end-of-path drift on one 20 m run: accumulated position error is
  heading-dominated (a mid-band 0.35 deg/m alone contributes ≈ 3 % over 20 m).
  The calibrated profile therefore hits the yaw band at every length and
  **pins the accumulated translational figure as measured** (2.3 %/20 m),
  explicitly above the published band. Full derivation in
  `configs/navigation/pose.yaml`.
- **Never exercised in a real run:** the chance-constrained membership branch
  (every measured run had zero covariance) and landmark re-anchoring (a sim
  landmark's observed position is truth and does not move). Both are proven
  against synthetic drift only.
- **Out of the seam's reach:** `follow_owner` / `circle_owner` never build a
  `NavObservation`, so no pose profile reaches them; the `stub_v0` degraded
  controller still reads truth directly (allowlisted). Nine direct pose reads
  remain in four files, held by a shrinking allowlist in
  `tests/test_pose_authority_archon.py`.
- **Defect named but deliberately not fixed (Lane B) — ~~FIXED 2026-08-07 by
  Lane D card D-4~~:** `NavObservation.position[2]` is the robot's standing
  height (0.27 m on the Go2), and `pipeline.py` had always read it as yaw in
  radians — a phantom 15.5° heading error in scan and frontier geometry. Lane B
  preserved it bit-for-bit so the T0 equality was real and collapsed it into one
  named function, `pose.legacy_position_yaw`.
  **Lane D deleted the consumption**, which is the fix as Lane B specified it:
  the three `pipeline.py` sites (`_step_semantic_resolution` grounding yaw,
  `_step_scan_behavior` scan start heading, `_step_search_entity_frontier`
  frontier bearings) now read `_pose_in(observation, MAP_FRAME).yaw`, and both
  the `legacy_yaw` import and the in-file bundle fallback are gone from
  `pipeline.py`. `pose.legacy_position_yaw` itself is untouched (Lane B's file)
  and now has no caller on the mission path.
  **Measured, paired, isolated from Lane C** (NAV_INSTRUCT candidate minival,
  25 episodes): SR flat at 0.0400, SPL flat, 0 collisions, **mean dtg
  8.6404 → 8.5167 m (−0.1237 m)**, 9/25 episodes changed. Largest single
  improvement `object_relative-A-00` dtg 2.508 → 0.449 m (the frontier align
  now turns to the frontier it chose). One cost: `region_goal-B-05` scans 14
  steps instead of 1 and runs out of budget, moving `arrived_verified` →
  `navigation_step_limit_inside_goal` (`planning_error` → `termination`,
  `agreement` → `authority_disagreement`); it was `success=False` under the
  frozen hold rule before and after. Full table:
  [scrum/20260806/task_3/LANE_D_STATUS.md](../scrum/20260806/task_3/LANE_D_STATUS.md)
  card D-4.
  **Still live in this row:** the other six allowlisted direct pose reads,
  including `instructnav_recovery.py`'s three (which carry the same defect and
  are not Lane D's file this round).
- **To verify:** HR — a real localizer in the `MAP` role on hardware, and
  measured Go2 leg-odometry drift on the actual robot to replace the
  literature calibration. Until then `Z_r` (`PoseEstimate.position_sigma_m`) is
  exactly 0.0 and every `SafetyEnvelope` is as narrow as it was.
- **Risk:** the seam makes the system *look* localization-aware. It is not.
  Anything that reads a pose still receives ground truth in sim, and a green
  T0/T1 says nothing about behaviour under a real localizer's failure modes.

## U35 — The dog asks for help; half of this is now closed · **minor**

**Updated 2026-08-09** — gap (a) is closed with acoustic evidence; gap (b) is
untouched and is the whole of what remains. Record:
[../scrum/20260808/task_5/VOCALIZE_AUDIBLE_STATUS.md](../scrum/20260808/task_5/VOCALIZE_AUDIBLE_STATUS.md).

- **Claim:** the blocked-by-a-person yield policy (2026-08-08, card P-1,
  [../docs/YIELD_POLICY.md](../docs/YIELD_POLICY.md)) makes the robot ask a
  person to move instead of standing there until the step budget expires.
- **(a) The ask is not audible — CLOSED 2026-08-09.** `_brain_vocalize` now
  calls `DuplexVoiceSession.speak_system`, which synthesizes and plays through
  the ordinary reply path (`_run_output`: same sink, chunk tokens, playback
  clock, prosody tap, barge-in). Measured on the `acoustic_loop_v1` rig
  module, real Piper, real `SpeakerSink`, sink selected through
  `speech.output_device` → `resolve_audio_device`: **5.27 s / 5.58 s of audio
  on the sink-monitor recording (n=2), peak sample 32729 / 32767**, against
  **peak 0, RMS 0.0, no onset** for the pre-fix door running the identical
  script in the same rig. Everything that leaves through that door now speaks:
  the `Vocalize` and `AskClarification` skills, pose-health, the search
  give-up, and all three yield lines.
  Two residuals, both recorded rather than assumed:
  *"audible" still means handed to the sink* (the 0.54–0.64 s
  enqueue-to-presentation gap is unchanged, N19), and *a system utterance is
  SKIPPED, never queued, if the speaker is already busy* — so an ask that
  collides with a reply is silent by design and says so
  (`brain` event `detail.audio_path = "suppressed_output_busy"`,
  `yield_policy_snapshot()["last_utterance_audible"]`).
- **(b) No person has ever responded to it — OPEN.** The dynamic city's
  pedestrians walk a script and cannot hear anything, so every measured run
  still ends in the honest failure rather than in somebody stepping aside.
  What is verified is that the robot stops burning ~4 minutes to say nothing;
  the *social* value of asking is entirely unmeasured.
- **To verify:** script one dynamic-city pedestrian to yield on an utterance
  event and measure the mission-completion delta against the same seeds as the
  P-3 table. Nothing about the audio path blocks this any more.
- **Risk:** "the dog asks for help" reads as a social capability. It is now an
  honest failure path with a *spoken* sentence attached — better than
  `step_timeout`, better than a silent transcript, and still not a
  conversation.

## U36 — The yield timings are choices, not measurements · **minor**

- **Claim:** `patience_s` 8 s / `reask_interval_s` 12 s / `max_asks` 2
  (`configs/personality.yaml`) are the right amount of patience.
- **Reality:** they are bounded on both sides by measured things — 8 s
  outlasts every transient pass observed in the dynamic city, and
  `8 + 12 + 12 = 32 s` is far inside the 240 s `NavigateTo` ceiling, so the
  attributable reason always beats `step_timeout` — but no experiment placed
  patience at 8 s rather than 6 s or 12 s. Same status as
  `GATE_BLOCKED_ROUTE_STEPS = 60`.
- **To verify:** sweep `patience_s` over the traffic case at n≥5 seeds per
  value and report completion rate vs. time-to-honest-failure. The knob is
  config, so the sweep needs no code change.
- **Risk:** an impatient default abandons goals a person was about to clear; a
  patient one wastes the owner's time. Nothing currently says which.
