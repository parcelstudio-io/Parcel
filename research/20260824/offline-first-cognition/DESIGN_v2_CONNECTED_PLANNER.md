# CONNECTED-PLANNER (H9 v2 — supersedes DESIGN.md's grammar/8B arms) · Fable · 2026-08-24

Owner re-scope: the offline floor is a canned line + follow + STOP; compound
planning is a **connected** capability. RTP-1 C6's ladder applies with its
arms re-ordered for the connected case; early-exit at the first arm that
meets the bar.

## The one decision
When connected, who compiles a compound instruction into a PlanSketch that
Parcel's local compiler+validator accept: **(1) the deterministic grammar**
(paraphrase-normalized by nothing), **(2) a hosted structured-output
planner** through an explicit provider adapter, or **(3) grammar-first with
hosted fallback**? And what is the measured false-physical-plan rate of the
intent gate in front of whichever wins (RTP-1 C7)?

## Arms (early-exit ladder, $ capped)
**[AMENDED 2026-08-24 per CLAUDE_RESPONSE Addendum F6 + Codex cross-review:
arms 1 and 3 (grammar / grammar-first) are REMOVED — the deterministic
compound grammar was never built and the owner's floor no longer needs it.
The live probe is arm 2 only (hosted structured PlanSketch through an
explicit adapter), plus the intent gate on the frozen corpus + adversarial
set. The probe is CONDITIONAL: it runs only if compound physical commands
are binding for M1 (HLD §15) — otherwise deferred, and one-step
clarification ships.]**
1. Grammar only (from DESIGN.md §1, unchanged) on the frozen 60-item corpus.
   Exit here if O1 ≥ 0.90 / O2 ≥ 0.85 / O3 ≥ 0.95 — hosted becomes fallback
   for the misses only.
2. Hosted mini structured-output PlanSketch via a new `providers` adapter
   (an adapter/factory — the launcher is llama.cpp-shaped; NOT a YAML
   change), JSON-schema constrained, compiled/validated locally. Cap $1.50.
3. Grammar-first + hosted fallback (composition of 1+2), reported if both
   individual arms partially miss.
The 26B desk reference (arm d of C6) runs only if 1–3 all miss — not
expected, budgeted at $0.

## The intent gate (C7)
parcel-6c authors an independent adversarial set (~40 items: narratives,
questions, corrections containing physical words — "I walked to the store",
"why did you sit?", "no, I don't think so"). Frozen corpus stays frozen.
Report **false physical plan rate** separately from PlanIR validity for the
winning arm's full pipeline (gate → normalizer/planner → compiler →
validator). Bar: ≤ 2 % false physical plans, 0 on the explicit-negation
items.

## Rows
P1 O1/O2/O3 per arm (bars as DESIGN.md); P2 hosted $ per 100 compound
instructions + p95 latency; P3 false-physical rate on the adversarial set;
P4 the adapter's failure behavior on timeout/malformed JSON (typed refusal,
never a partial plan); P5 which early-stop condition ended the study.

## OWNS
this folder, `voice/compound_grammar.py` (as DESIGN.md), the hosted-planner
adapter as a research-scoped module `research/.../hosted_planner.py` (the
PRODUCT adapter lands in M1 only after the decision), `tests/test_h9v2_planner.py`.
Must not touch the realtime lane, `runtime.py`, `providers.py` product code.
Hosted cap $1.50 total, ledgered. Guard label `h9v2`.

## Codex cross-review for Fable · 2026-08-24

**UNFINISHED and internally stale.** The program addendum drops the offline
grammar/8B arms, but this v2 design still carries the grammar-first comparison
from the superseded scope. There are no canonical results or verdict.

If compound motion is in M1, reduce the probe to one hosted structured
`PlanSketch` adapter plus local compiler/validator/authority checks. Test
timeouts, duplicates, delayed replies, malformed fields, explicit negation
and stories containing motion words; no proposal may directly emit velocity.
If voice-to-compound motion is not required for the first point-goal slice,
defer this study. It is not a prerequisite for mounting, STOP or manual
commissioning.
