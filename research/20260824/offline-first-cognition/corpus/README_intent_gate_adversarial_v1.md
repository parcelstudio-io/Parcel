# intent_gate_adversarial_v1 — adversarial intent-gate set

Author: **parcel-6c (Fable), 2026-08-24**, per RTP-1 C7's independent-author
requirement. **Authored independently of the frozen compound corpus and its
grammar: neither was opened during authorship** (nothing inside `corpus/` was
read; the items come from category reasoning alone, listed below). Requested
by parcel-fb (integrator), delivered in-session.

## What this set is
43 utterances containing physical-action words (walk, go, sit, stand, run,
follow, fetch, turn, climb, jump, move, bring, take, push, stop, roll, come)
in contexts where the PLANNER intent gate must produce **no physical plan** —
or, for 4 genuinely ambiguous items, a **clarify**. Gold field:
`no_physical_plan` (39) | `clarify` (4: ig_adv_028, _029, _039, _043).

## Categories covered
speaker's own past/future actions (001, 007, 023); third-party and animal
narratives (006, 016, 024, 033, 035); questions about the ROBOT's past
actions or capabilities (002, 015, 037); requests for explanation or verbal
reports — including world/memory queries that are ANSWERS, not motion (003,
008, 025, 034, 041, 042); topic switches and plain negations (004, 005, 040);
reported speech and quoted commands (012); definitions/teaching (019);
idioms and phrasal verbs (009, 010, 014, 020, 021, 022, 027, 030, 031, 038);
fiction/media (011); hypotheticals and knowledge questions shaped like
conditionals (013, 032, 036, 037); measurement/distance talk (017); dreams
(018); narrative "stop" (026); self-cancelled or antecedent-less fragments
(028, 029, 039); ambiguous possible-request (043).

## Safety scoping — read before using item 026
This set tests the PLANNER/intent gate only. Nothing here licenses weakening
the emergency-STOP hotword or barge-in fast paths: a product that
over-triggers STOP on the word "stop" in narrative (026) is failing SOCIALLY,
not unsafely, and any fix must change the plan gate, never the stop path's
sensitivity. Items 016 and 043 likewise must not justify loosening
owner-addressed gating: the correct behaviors are "not addressed to me" and
"ask", respectively.

## Provenance
Names used: Jae (owner), Minho (fictional third party). No item was derived
from, checked against, or deduplicated against the frozen compound corpus;
if an item collides with it verbatim, that is coincidence and the collision
should be recorded rather than the item silently removed (removal would leak
grammar information into this set's distribution).
