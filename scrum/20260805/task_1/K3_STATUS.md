# K3 status — Resume-transaction completion

**Date:** 2026-08-05 · **Owner lane:** Opus (existing files) · **Binding:**
[ADJUDICATION.md](ADJUDICATION.md) kickoff board K3.

## Delivered

| Item | Path | Notes |
|---|---|---|
| Pure fail-closed resume gate | `src/parcel_robot/core/resume.py` (`resume_rejection_reason`) | Missing/expired intent; `requires_fresh_observation` without proven-fresh sample |
| Central coordinator | `RobotRuntime._resume_from_store` | Peek → freshness → take → reacquire authority → `channel.resume` → bookkeeping |
| NavigateTo consumes intent | `_start_or_resume_navigation_locked` | Matching paused mission resumes progress; different directive cold-starts; expired/missing while paused fails closed |
| `resume_navigation` fail-closed | `runtime.py` | No synthetic intent when store empty/expired |
| Search→follow via stored intent | `_finish_owner_search` + preempt PAUSE | Legacy `_resume_follow_after_search` tuple removed; registry fills `suspended_at_s` before record so peek(now) no longer drops sentinel-`0` intents as expired |
| Follow / search consumers | `_start_brain_follow_formation`, `_start_brain_owner_search` | Redispatch resumes from store when applicable |
| Tests | `tests/test_resume_transaction.py` | Progress retained; stale obs blocks; search→follow intent; expiry fail-closed; NavigateTo redispatch |
| Docs | `docs/PAUSE_SEMANTICS.md` | Reflects closed loop + remaining limits |

## Explicit non-claims

- Follow pause remains reconstruction (stop + payload), not a frozen controller.
- No Nav2; safety/E-stop authority unchanged.
- Voice plan amendment (re-proposal on resume) is out of scope for K3.
- Freshness gate uses runtime telemetry TTL, not full V1 EvidenceEnvelope ns wiring.

## K6 join note (2026-08-05 P1 arbitration)

Closed-intent `pause`/`resume` now consume this transaction (B1/S1 in
[ARBITRATION_P1.md](ARBITRATION_P1.md)): spoken pause uses `_pause_channel`
(not `preempt("voice")` STOP), and spoken resume fails closed when the store
is empty or freshness rejects. See `K6_STATUS.md` and
`tests/test_k6_voice_lanes.py::test_closed_intent_pause_resume_transaction`.

## Remaining gaps

1. Wire V1 evidence clocks into the resume freshness check when Perception bags
   feed `EvidenceEnvelopeV1` on the hot path.
2. Richer follow pause (retain internal formation state) if reconstruction
   proves insufficient in field attribution.
3. Voice plan amendment (re-proposal on resume) remains out of scope for K3.
