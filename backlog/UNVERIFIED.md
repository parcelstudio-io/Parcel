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
- **To verify:** keep unit pins green; add/run full scripted integration when
  feasible; confirm ledger rows stay byte-identical afterward.
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
