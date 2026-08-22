# Task 19 — SI-v3: the prompt catches up to the body

**Executor:** Claude Opus (agent) · **Auditor:** Fable
**Authority:** carried since AUDIT_R16_R3 (over-claim wording — fixed in v2;
remaining items accumulated since): the SI still does not NAME
circle_owner/follow_owner (E1 observed 0 fabrications anyway, but the
model denies abilities it has when asked); scene answerability, memory
provenance, latch-status, and pace-negotiation behaviors all landed after
v2's wording froze. Real owner transcripts exist as evidence.
**DISPATCH GATE: after C-3 closes** (the tool surface must be final first).

## Work
1. v3 wording: name the full tool surface honestly; the "describe, never
   decide" rule extended to map-derived facts ("my map says", "I think
   that's a bench — I've only seen it once"); counts only with map
   corroboration; latched-status language.
2. Version-selection discipline (R5's machinery): v1/v2 stay renderable and
   pinned; corpus provenance untouched; digests registered.
3. Live A/B: ≥6 paired turns v2 vs v3 on the scenarios the owner actually
   hit (ability questions, scene questions, deferred gestures), judged by
   the local autorater with per-pair gold written at authoring time (the
   R5-era lesson).
OWNS: `realtime/prompting.py` (version-selected text), tests,
`SIV3_STATUS.md`. MUST NOT TOUCH: lane/broker, corpus fixtures. Spend cap
$2. DoD: gate green; ≥6 seeds RED (v1/v2 render drift; digest unregistered;
corpus conflation); the A/B table; standard register.
