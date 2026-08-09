# P2 Dialogue Status — Voice-behavior joins in sim

**Phase:** 2 (owner amendment: hardware last, all sim) · **Date:** 2026-08-05 ·
**State:** DONE (sim slice) · **Binding:** [ADJUDICATION.md](ADJUDICATION.md)
Owner amendment Phase 2 — amendment, clarification, dialogue-state × T2;
WoZ desktop audio documented as blocked on backlog B1.

## Plan sources

- [ADJUDICATION.md](ADJUDICATION.md) § Owner amendment Phase 2
- [fable-research-plan.md](fable-research-plan.md) §4 voice→behavior (points 2–4)
- [B-voice-behavior.md](B-voice-behavior.md) B1/B2 join surfaces
- Prior: [K6_STATUS.md](K6_STATUS.md), [K3_STATUS.md](K3_STATUS.md), [K1_CONTRACT_RFC.md](K1_CONTRACT_RFC.md)

## Delivered

| Item | Path | Notes |
|---|---|---|
| DialogueState 10 Hz channel | `src/parcel_robot/voice/dialogue_state.py` | Publish/consume `DialogueStateMsg`; TTL 500 ms (K1) |
| T2 mapper | same | phase×engagement → gaze mode / gait hint / **bounded slowdown** (≤1.0) |
| Runtime publish + consume | `src/parcel_robot/runtime.py` | `_step_dialogue_state` on 10 Hz loop; phase from voice stages / mic |
| Stimulus feed | `attention/stimuli.py` + `reaction_bridge.py` | `StimulusKind.DIALOGUE_STATE`; mutual/aversion T2 specs |
| Mid-task amendment | `src/parcel_robot/voice/amendment.py` + runtime/agent | pause → ResumeIntent (`goal_amend`) → replan remainder; fail-closed |
| Grounded clarification | `amendment.clarification_from_grounding` + nav pipeline | AMBIGUOUS → attribute question; UNSEEN → offer scan |
| Tests | `tests/test_p2_dialogue.py` | channel/TTL/T2, amend fail-closed+pause, clarification, runtime pace overlay |
| Status | this file | Honest gaps below |

## Safety invariants (claimed)

- Dialogue-state / T2 **never** changes E-stop, reactive gate, or safety priority.
- Dialogue pace factor is a **slowdown overlay only** (≤ PaceCap); never authors model velocity; `manual` / `safety` / `emergency` sources bypass it.
- Social / dialogue reactions still cannot claim `base` / `posture`.
- Goal-amend with nothing active/paused **fails closed** (honest reply, no fake replan).
- No Nav2 / ROS 2 authority migration.

## Gates exercised in sim

- Publish → consume unexpired `DialogueStateMsg`; expired → idle influence (fail-closed).
- Listening → mutual gaze; thinking → aversion; speaking → soft; idle → release.
- Closed `goal-amend` while navigating records ResumeIntent with `suspend_reason=goal_amend`.
- Clarification text prefers stored candidate labels when AMBIGUOUS.

## Explicit gaps (honest)

1. **Desktop audio / WoZ (HR-7 / backlog B1):** still blocked on apt
   (`libportaudio2`, cmake, … — see [BLOCKED.md](../../../backlog/BLOCKED.md) B1).
   Code paths + tests use text/fakes; **acoustic UX is not validated**.
2. **Gait cadence actuator:** T2 emits `gait_hint` in influence/snapshot only;
   no Sport-mode cadence writer yet (sim kinematic base).
3. **Full concurrent conversation + planner GPU QoS** still sequential (K6 gap).
4. **UWB noise model** is listed in Phase 2 owner amendment but is **out of
   scope for this dialogue slice** (separate card).
5. **ExpressionEngine / duplex gaze** conditioned from dialogue-state; live
   acoustic barge-in × dialogue-state timing not measured without B1 audio.

## Test command

```bash
.parcel/bin/pytest tests/test_p2_dialogue.py tests/test_k6_voice_lanes.py -q
```

## Non-claims

- No hardware commissioning, UWB characterization, or Orin timing.
- No claim that mic/Piper duplex works on this desktop (B1).
- No Nav2. E-stop path unchanged.
