# K1 Status — Contract RFC + CI tests

**Card:** K1 · **Owner lane:** Sol (pure) · **Date:** 2026-08-05 ·
**State:** DONE (pure modules + CI; no runtime wiring)

## Delivered

| Artifact | Path |
|---|---|
| Contract package | `src/parcel_robot/contracts/` |
| V1 DTOs | `src/parcel_robot/contracts/v1.py` |
| Fail-closed freshness | `src/parcel_robot/contracts/freshness.py` |
| CI tests | `tests/test_contracts_v1.py` |
| RFC | `scrum/20260805/task_1/K1_CONTRACT_RFC.md` |

## DTO checklist

- [x] `EvidenceEnvelopeV1`
- [x] `OwnerTrackV1`
- [x] `DynamicTrackV1`
- [x] `SemanticRegionV1`
- [x] `GoalRegionV1`
- [x] `DialogueActV1` (+ `DialogueClaimV1`)
- [x] `SocialCueV1`
- [x] `ReactionProposalV1`
- [x] `SceneQueryV1`
- [x] `SkillFeedbackV1`
- [x] `DetectionMsg`
- [x] `DialogueStateMsg` (dialogue-state channel)

## Constraints honored

- Pure dataclasses only — no ROS, no I/O, no `runtime`/`agent` imports or wiring
- Instructnav / brain-contracts style (`frozen` + `slots`, exact-field parse)
- Fail-closed TTL / age / clock-jump / v·τ speed-cap helpers

## Remaining (out of Sol lane)

- Fable review of RFC field names / enums
- Opus wiring of bus publishers/consumers (later cards)
- K5 DetectionMsg noise adapter; K6 dialogue-state publisher

## Test command

```bash
pytest tests/test_contracts_v1.py -q
```
