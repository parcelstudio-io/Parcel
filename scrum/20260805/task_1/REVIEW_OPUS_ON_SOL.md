# REVIEW — Opus on Sol K1

**Reviewer:** Opus stand-in (cross-review) · **Date:** 2026-08-05 ·
**Subject:** Sol K1 contract freeze (`contracts/`, `tests/test_contracts_v1.py`,
`K1_CONTRACT_RFC.md`, `K1_STATUS.md`) · **Criteria:** pure-only; full DTO
family incl. DetectionMsg + dialogue-state; fail-closed freshness; RFC
honesty; CI tests.

## Verdict

**APPROVE**

K1 meets the Phase-0 card: pure dataclasses only, the full adjudicated DTO
family (incl. Fable's DetectionMsg + dialogue-state channel), fail-closed
freshness helpers, an honest RFC/status pair, and green CI under
`tests/test_contracts_v1.py` (`10 passed`).

## Criteria checklist

| Criterion | Result |
|---|---|
| Pure-only (no runtime wiring) | Pass — no `runtime`/`agent`/ROS/numpy imports; package is self-contained; STATUS/RFC correctly defer wiring to Opus |
| Full DTO family + DetectionMsg + dialogue-state | Pass — all twelve checklist types present with exact-field `from_mapping` / `as_dict` |
| Fail-closed freshness | Pass — TTL/age/expiry/stale/`require_fresh`, clock-jump reject, v·τ speed cap; expiry is `now >= expires` |
| RFC honesty | Pass — non-goals explicit; field catalog matches code; default TTLs match `freshness.py`; no claim of bus wiring |
| CI tests | Pass — discovered via `testpaths = ["tests"]`; covers round-trip, unknown fields, schema mismatch, NaN, expiry, stale, clock jump, verified-claim, geometry, resource tracks, dialogue-state channel |

## Findings

### Strengths

1. **Complete merged catalog.** EvidenceEnvelope + Owner/Dynamic/Semantic/Goal
   + DialogueAct/Claim + SocialCue + ReactionProposal + SceneQuery +
   SkillFeedback + DetectionMsg + DialogueStateMsg — matches ADJUDICATION K1.
2. **Authority-safe shapes.** No `cmd_vel`/priority/goal-coordinate fields on
   voice DTOs; ReactionProposal tracks allowlisted to
   `{base, posture, voice, attention, perception_scan, expression_audio}`;
   verified claims require `evidence_ref`.
3. **Clock discipline is binding and coded.** Dual stamps, monotonic-only age,
   reject on source/monotonic backward and source-ahead-of-mono jump; speed
   cap fails closed on non-finite age.
4. **RFC/STATUS honesty.** Out-of-scope (StimulusBus wiring, ROS IDL, bag
   schema, brain PlanIR) is explicit; remaining work correctly named as Fable
   review + later Opus cards.

### Non-blocking issues (fix before bus wiring; not K1 blockers)

1. **`SemanticRegionV1.concept_scores` is mutable under a frozen dataclass.**
   Construction stores a plain `dict`; callers can mutate scores in place
   (`region.concept_scores[k] = …` succeeds). Prefer `MappingProxyType` (or
   frozenset-of-pairs) so “frozen evidence” is actually immutable.
2. **Malformed geometry parse can raise `IndexError`.**
   `GeometryV1.from_mapping` with a short vertex (e.g. `polygon: [[1.0]]`)
   indexes `[1]` after `_sequence(..., maximum=2)` and raises `IndexError`
   instead of `ValueError`. Contract parsers should reject malformed payloads
   with `ValueError`/`TypeError` only. Same pattern exists on predicted-
   occupancy polygon vertices.
3. **Clock-jump CI coverage is partial.** Tests cover `source_clock_backward`
   and `source_clock_jump`; `monotonic_clock_backward` and
   `source_advanced_without_monotonic` paths in `detect_clock_jump` lack
   dedicated cases (monotonic inversion is only exercised via `age_ns`).
4. **`test_envelope_require_fresh_and_wrong_frame_policy` overnames.** The
   “wrong frame” half is a documentary assert, not a contract API. Do not
   treat frame gating as frozen by this test.

### Not in scope / correctly deferred

- StimulusBus / `runtime.py` / `agent.py` wiring
- Bag schema (K2′), DetectionMsg noise adapter (K5), dialogue-state publisher (K6)
- Nav2 / ROS IDL
- SE2Goal ↔ PlanIR pause-resume surface (not on the ADJUDICATION K1 card)

## Must-fixes

None — verdict is APPROVE.
