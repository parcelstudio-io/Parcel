# Common-sense companion: research + bench synthesis · Fable

**Date:** 2026-08-20 · **Inputs:** the seven reports in this folder — four
literature sweeps (grounding, semnav, context-injection, cascades) and three
empirical benches (whisperer A/B/C/D, hosted-model navigation, significance
judge). All benches used pre-committed gold labels; total OpenAI spend across
the wave ≈ $0.16.

## The decisions, each with its evidence

1. **Whisperer v1 is deterministic (policy B2): two bands + debounce + caps,
   NO LLM in the forwarding path.**
   Evidence: B2 caught 11/12 gold facts with 0 spam vs the Gemma-judge
   variant's 8-10/12 (non-deterministic across identical runs);
   judge-everything delayed an e-stop forward 9.8 s and lost the clear.
   Literature agrees: Inner Monologue proves event-anchored terse language
   feedback works and its unfiltered firehose is exactly the failure Parcel
   hit live (69 narrations, R4L); SayCan says feasibility vetoes are local;
   Statler says injected items must be delta-phrased and version-stamped
   because an append-only session cannot retract.
2. **The evidence-backed FUTURE middle-band judge is Ministral-3-8B (already
   vendored), not Gemma — added only when reality shows class-rule misses.**
   Evidence: judge bench — Ministral 40/44 gold agreement, 2.8 s p50, zero
   malformed; Gemma 18 s p50 / 38 s p95 with 7% reasoning-overrun losses
   (and in-situ, the A/B bench's Gemma judge declined a real pace-mismatch
   even with reasoning ON at 33 s). The two benches reconcile cleanly: the
   A/B stream's gold facts were all class-identifiable (tables win there);
   the judge bench's gold set included signature-less cases (progress
   stalls, social situations) where rules run out and a fast local judge
   beat the cheap-frontier reference. Sequencing: ship B2, measure its real
   misses in E1 and owner sessions, occupy the config seam with Ministral
   only against demonstrated misses. Classic Mistral-7B v0.3: not tested
   (the vendored Ministral is the same family, newer and better; a 7B run
   is one command if ever wanted).
3. **Composition belongs to the hosted model.** Both local models invented
   pragmatics when composing prose (Ministral cast the OWNER as the
   obstacle; asserted an adaptation instead of asking). Forward structured
   facts + speech-act hints; let the frontier voice phrase them — phrasing
   was its one unambiguous comparative strength.
4. **Arrival semantics: hybrid.** Model-supplied RELATION hints are
   reliable (100% on firm golds, both tiers, self-consistent) → accept as
   validated hints. FACE and terminal etiquette are owner policy the models
   reliably get wrong (face=goal 6/6 at the door where the owner wants
   turn-back) → local table only. "Arrived" becomes a typed geometric
   predicate (contains/near+facing/social-standoff), per Code-as-Policies'
   lesson that this is predicate composition, not language.
5. **The tool surface must match the body.** With no orbit/follow tools the
   mini fabricated junk (`navigate_to("with owner")`) and realtime-mini
   falsely denied abilities it has. R10 declares circle_owner +
   follow_owner(pace) through the existing validate→door chain, plus place
   validation on navigate_to.
6. **State injections must never start motion.** Bench C1: telemetry
   injection triggered spurious navigate_to in 2/3 forced-response trials —
   utterance-scoped dedup does not cover it. R11 adds the lane/broker
   tag-and-refuse gate: only owner utterances may start motion.
7. **Ask-hints are load-bearing.** The owner-required questions ("should we
   just walk?", "what next at the door?") appeared 0/12 chat and 0-2/3
   realtime from facts alone; KnowNo-style asking must be requested by the
   injected item, deterministically templated per class.
8. **Chat-proxy benching is invalid for cadence/verbosity claims** on this
   model family (realtime-mini violated cadence 2/2 where the proxy showed
   0/12). Anything cadence-sensitive gets validated on the realtime API.

## Where this landed

R10/R11 cards revised 2026-08-20 (see their READMEs, "What the evidence
changed"); implementation chain R8fin → R9 → R10 → R11 → E1 dispatched the
same morning. E1's misses-ledger becomes the trigger condition for decision
2's Ministral occupancy.
