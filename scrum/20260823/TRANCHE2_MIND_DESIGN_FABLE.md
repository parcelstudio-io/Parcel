# Tranche 2 — the continuous mind · design (Fable) · 2026-08-23

Owner directive: improve **continuous conversationality**, **generalized
intelligence**, and **autonomous navigation**. Opus implements, Fable
verifies, reduced-testing policy, prototype-first. Governing frame:
docs/CONVERSATIONAL_AUTONOMY_HIGH_LEVEL_DESIGN.md (§2 hybrid deterministic
stack; §6 target architecture; §11 lanes; the north-star scenario). Grounded
by four read-only subsystem audits at HEAD c9229ab (workflow wf_093028e5;
full seam maps in the workflow record).

## Grounded facts the design stands on

1. **The dog already listens wake-free** — the LOCAL lane
   (MicrophoneVoiceLoop → Silero VAD/semantic endpointing → whisper.cpp →
   VoiceAgent → piper) arms automatically when whisper.cpp + a real mic
   exist, no wake word, answers every committed utterance. The hosted lane
   is a separate, spend-governed, click-armed ear (the XVF3800 beam feeds
   ONLY it, dropped when inactive). `configs/realtime.yaml` does not exist
   ⇒ hosted is off by default. $0 continuous desk listening is a config
   away — on the weaker capture path (mono ch-0, no beam, AEC unwired).
2. **Narration blocks the motion loop** (verdict blocking finding 1,
   re-confirmed at line level): control thread → `_step_whisperer` →
   `narrate_event` → blocking `websockets.sync` send + spend-ledger disk
   read. The destination pump thread (`RealtimeDriver.step`, ~20 Hz,
   exception-firewalled) and a thread-safe `whisperer.undeliver` already
   exist — the fix is a bounded FIFO handoff, not a redesign.
3. **The map learns continuously but dialogue cannot ask it anything.**
   OnlineSemanticMap ingests at 2 Hz with full per-entry provenance,
   naming k-gates, absence evidence; measured 5× GPU headroom. But
   `recall_memory` reads conversation rows only; the scene block is
   15 m-proximity-cropped; `resolve()` is reachable only through
   navigate_to validation and ask_place. "Where is the bench?" has no
   answer path. The whisperer narrates ROBOT state only — zero world
   fields.
4. **The per-turn record is one typed IntentFrame, then strings.** Every
   outcome (heard/clarify/unsupported/rejected/admitted/stopped) is a bare
   reply string; the hosted broker has its own 4-word vocabulary.
   Admission itself is strong.
5. **The typed navigation goal is compiled then thrown away, three times**
   — hosted navigate_to renders back to TEXT via a template; PlanIR
   carries text; DirectiveNavigator REPARSES. Sketch-time relation
   refinement can diverge from the navigator's interpretation.
6. **Exploration is anti-exploratory** (ROAM-2, measured): max radius from
   home 2.87–3.16 m vs baseline 10.06 m; `coverage_candidates` returned
   zero rows in 351/468 samples (`exclude_visible=True` + an 8 m
   visibility ring covering the whole map). T1 was a pre-registered
   ceiling. H1/H2 fix options are already written in ROAM2_STATUS §7.
7. **R19 is real:** `_location_context` stamps `frame: "map"`
   unconditionally — a live Go2 would sell raw leg odometry as map pose.
8. Recovery is compiled dead (`max_attempts=1` literal) while the
   machinery (`_fail_or_retry`, `pending_recovery`) exists and works.

## The tranche (8 cards, 4 waves; one runtime.py toucher per wave)

### Axis A — continuous conversationality
- **NARR-1 (task_6, wave A, runtime-toucher).** Off-thread narration:
  `RealtimeLane.enqueue_narration` bounded FIFO (maxlen ~8, overflow drops
  oldest NON-critical with a counter, critical never dropped, session-id
  stamped), drained by `RealtimeDriver.step()` between pump and tick;
  stale-session/inactive drains call `undeliver`; inbox cleared on
  hang-up (a paid session can never be re-opened by the whisperer).
  `_narrate_mission` becomes enqueue-only. Kills the tick-stall class.
- **EAR-1 (task_7, wave A).** Constant desk listening today, $0:
  `configs/robot.desk.yaml` overlay pinning `speech.input_device` to the
  XVF3800, beam-channel selection in MicrophoneVoiceLoop where the device
  exposes it (ARRAY_ASR_CHANNEL semantics), `speech.aec` knob wiring the
  existing AecStage (default off), `scripts/launch_desk_voice.sh`. Hosted
  stays off; proven through the injectable `frames=` seam.
- **ENG-1 (task_9, wave B).** Ambient engagement tier: pure
  `voice/engagement.py` classifying committed transcripts into
  answer / acknowledge / hear-only; hear-only is REMEMBERED (memory
  ledger) and may offer a StateEvent to the existing curiosity door,
  never reaches VoiceAgent, never produces TTS. Call site in the voice
  pipeline (NOT runtime.py). The dog stops answering everything it
  overhears and starts listening to the world.

### Axis B — generalized intelligence
- **WORLD-1 (task_8, wave B, runtime-toucher).** The dog answers from its
  own map and remarks on world change. (a) `online_map/answers.py` pure
  rendering (label-primary, VLM names secondary/revisable, last-seen
  provenance phrasing — NEVER present-tense presence claims); new
  info-class `query_world` tool in BOTH lanes (broker spec + ToolDoors +
  `_realtime_query_world` beside recall; legacy `info_tools` registry);
  (b) whisperer world events beside `curiosity_event`: `reseen_place`,
  `expected_missing`, `name_promoted` — all through the ONE admission
  function (`_curiosity_admitted_names`, 0-hallucinated-places row
  preserved) and existing chatter caps.
- **MIND-1 (task_11, wave C).** `TurnDispositionV1` (frozen, in
  brain/contracts.py): turn, route, outcome ∈ {heard, clarify,
  unsupported, rejected, admitted, stopped}, typed reason_code, optional
  task_ref. Assembled at every `_handle_text` return site; hosted broker
  STATUS_* maps onto the same enum. Replies byte-unchanged; no task event
  for pre-admission outcomes. The truthful-dialogue substrate.
- **SUP-1 (deferred to tranche 3).** Reachable recovery (system-owned
  per-skill `max_attempts`, opt-in, ≤3) + bounded deterministic
  MissionSupervisor (one budgeted retry with a FRESH snapshot through the
  existing `_accept_plan`, else grounded explanation + honest
  termination; terminal-states only — no checkpoint preemption until
  ControllerCheckpointV1 exists).

### Axis C — autonomous navigation
- **NAV-T1 (task_10, wave C, runtime-toucher).** The typed goal travels
  end-to-end: `SemanticGoal` compiled at sketch time rides PlanIR;
  `start_navigation` accepts goal-or-text; `DirectiveNavigator.parse`
  consumes the typed goal (text kept for audit); the deterministic router
  still owns routes; the hosted template render dies. NAV_INSTRUCT v4
  candidate row must be unchanged.
- **ROAM-3 (task_12, wave D, runtime-toucher).** The dog leaves the
  doorstep: H2 fix per ROAM2_STATUS §7 (minimum candidate distance +
  forward-bearing preference, or frontier-over-unexplored term) in
  `coverage_candidates`/patrol policy; H1 measurability (recency-scored
  C1 or a venue whose map outruns the 8 m ring). Still a proposal below
  the same gates, still default OFF. **Carries the T1/H2 owner decision
  as a written re-registration** under the owner's "improve autonomous
  navigation" directive; headline rows (max-radius-from-home, per-room
  visit fraction) pre-registered BEFORE the two-arm run.
- **LOC-1 (task_13, wave D).** The localization ADR + bench spec (docs +
  harness skeleton only, no product code): recommend DELEGATING metric
  SLAM to an established Mid-360 LIO provider (FAST-LIO2/Point-LIO
  class) behind `pose.py`'s existing PoseProvider MAP role — Parcel owns
  the `T_map_odom`/covariance/health/jump CONTRACT, not the filter; ATE/
  RPE/dropout bench spec to run on box-day bags. Answers handbook open
  decision 12. The R19 `_location_context` fix and the
  NavigationSnapshotV2 assembler join SUP-1 in tranche 3 (both need a
  runtime slot).

## Rules binding every card
Marked regions; one runtime.py toucher per wave; frozen baselines
byte-unchanged (MOVE-1/ROAM-1 unit baselines; NAV_INSTRUCT v4 digest — an
arrival/clearance change is a formal re-freeze, never a quiet edit; no
re-cutting a pre-registered row after seeing its number); no new lock
edges (R24 PINNED_LOCK_ORDER; map reads under `_p1b_map_lock`, never
nested); every learned/model output stays a proposal; info-class tools
can never reach a motion door; `set_proximity_context` stays unwired to
any model tool; capability tests only; guard wrapper for every pytest;
executors never run gate tiers; sims one-at-a-time under the 12 GB scope;
the owner's store and live stack untouched.

## What this tranche does not do
No physical claims (everything sim/desk); no runtime/audio decomposition
(deferred per the verdict); no hosted-lane spend by default (EAR-1 is
local-only; NARR-1 changes threading, not spend policy); no new
navigation authority (ROAM-3 remains a gated proposal, OFF); no SLAM
implementation (an ADR + bench spec).
