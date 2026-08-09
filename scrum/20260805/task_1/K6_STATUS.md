# K6 Status — Voice lanes B0→B1→B2 (MVP)

**Card:** K6 · **Owner lane:** Opus (wire) + Sol-style pure helpers ·
**Date:** 2026-08-05 · **State:** DONE (architecture landed; B1/S1 voice↔resume
seam fixed per [ARBITRATION_P1.md](ARBITRATION_P1.md))

## Plan sources

- [ADJUDICATION.md](ADJUDICATION.md) kickoff K6
- [B-voice-behavior.md](B-voice-behavior.md) B0→B1→B2

## Delivered

| Item | Path | Notes |
|---|---|---|
| Closed intent enum | `src/parcel_robot/voice/closed_intents.py` | `{pause, resume, faster, slower, stop, come, goal-amend}` |
| Executive / pace caps | `src/parcel_robot/voice/executive_caps.py` | `CapDirective`, `PaceCap` → runtime / CommandArbiter seam |
| Local PlanSketch builders | `src/parcel_robot/voice/local_plans.py` | follow / hold / come / spatial / navigate |
| Dialogue lane helpers | `src/parcel_robot/voice/dialogue_lane.py` | strip physical tools; `DialogueActV1` builder |
| Social reaction bridge | `src/parcel_robot/voice/reaction_bridge.py` | StimulusBus + ReactionArbiter; never claims `base` |
| Agent B1 wiring | `src/parcel_robot/agent.py` | local PlanSketch admission; conversation schema strip; E-stop fast path kept |
| Runtime B1/B2 wiring | `src/parcel_robot/runtime.py` | `direct_skill` PlanIR admit; pace scale on `submit_motion`; closed-intent handler; reaction tick |
| Closed pause → true PAUSE (B1) | `runtime._apply_closed_intent` + `VOICE_INTERRUPT_POLICY` | Pausable channels via `_pause_channel` / ResumeIntent; spatial/activities STOP only; executive suspend (not overlap) |
| Honest resume reply (S1) | `runtime._apply_closed_intent` resume branch | Fail-closed when store empty / freshness rejects; success reply only after a channel resumes |
| Tests | `tests/test_k6_voice_lanes.py` | unit + agent fakes + closed pause→fresh resume / stale reject / empty-store honesty; no mic hardware required |

## Gates claimed (MVP)

- Physical follow / hold / spatial / nav prefer PlanSketch → PlanIR admission when brain adapters are present; legacy tool bypass remains only when local-plan admission is unavailable.
- Conversation lane does not receive physical tool schemas; residual physical tool calls are stripped before execute.
- Emergency / spoken `stop` remains the immediate cancel path (does not wait on plan construction); does **not** use the true-PAUSE path.
- Closed companion `pause` true-PAUSEs navigation/follow/search (ResumeIntent + frozen budgets); does **not** use `preempt("voice")` STOP on those channels.
- Closed `resume` restores via `_resume_from_store` and fails closed (honest reply) when nothing resumes or freshness rejects.
- Social reaction path is stub-wired into the control loop and **vetoes** when base is busy / critical; proposals that require `base`/`posture` are rejected and counted.
- Desktop audio: **not** a K6 fail criterion — blocked on backlog [B1 apt install](../../../backlog/BLOCKED.md) (`libportaudio2`, etc.). Code paths + tests use fakes.

## Explicit gaps (honest)

1. **Full concurrent conversation + planner sessions** (GPU QoS, dual logical sessions) not implemented — conversation and deliberative plan remain sequential branches.
2. **Personality policy → ReactionProposalV1 → ExpressionEngine** is not end-to-end: bridge ticks and records decisions; it does not yet drive expression/audio actuators.
3. **Per-track activity leases** (B2 replace coarse busy gating) still pending; bridge uses `base_busy` / critical-phase veto only.
4. **Vocalize audio-lifecycle evidence** (onset/completion/cancel) not done.
5. **Walk / catalog / backend** grammars still use deterministic tool dispatch (not PlanSketch) — only follow/nav/spatial/hold/come were moved.
6. **Desktop audio UX** unverified until backlog B1 apt packages land (see hardware-readiness HR desktop-audio).

## Test command

```bash
pytest tests/test_k6_voice_lanes.py -q
```

## Non-claims

- No Nav2 / ROS 2 authority migration.
- No claim that mic/Piper acoustic duplex works on this desktop.
- False social preemption of base is gated to zero on the wired path; inferred affect quality is not hillclimbed (B3).
