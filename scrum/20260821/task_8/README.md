# Task 8 — PG-3: "I don't know" must survive the labeled world (SAFETY-CRITICAL)

**Executor:** Claude Opus (agent) · **Auditor:** Fable (deferred)
**Evidence:** `scrum/20260821/perception/bench_mapping.md`, the
safety-critical finding. Against a real map built from RGB-D, **no threshold
separates present from absent queries**: "the parking garage" scores 0.107 —
*above 5 of 8 correct answers*; corpus row 10 **"Narnia" scores 0.073 and
would send the robot to (−3.19, 4.10)**; row 11 "my office" to the same
point. Rejecting all absent queries costs 5 of 8 correct ones. SigLIP2's
calibrated probability for *correct* answers is 0.00014–0.163, so a p=0.5
gate rejects everything.

**Why this is the card that gates the whole cutover.** R20 made Parcel refuse
unknown places honestly — but it refuses *because the chain checks a closed
label set*. Delete the labeled world and that capability disappears with it.
Shipping perception without calibrated abstention would trade an honest
refusal for a confident hallucination, on the motion path. That is a
regression in the one property this project protects hardest.

**The lead, from the same bench:** the detector is innocent — OWLv2 **never
once fired "coffee shop"** in 120 frames, while embedding cosine happily
ranked it. The label head abstains where cosine cannot.

## Work

1. **Root-cause and characterize before building.** Reproduce the bench's
   separation failure from its saved artifacts; state in the doc exactly what
   cosine-ranked retrieval can and cannot express (it is a *ranking*, not a
   detection — there is no absolute scale).
2. **A calibrated abstention mechanism**, candidate per the bench:
   detector-label agreement (did an open-vocab detector ever fire a label
   compatible with the query?) **plus** evidence count (how many independent
   observations support this place) **plus** a margin test (top-vs-runner-up,
   not absolute cosine). Fit any threshold on a HELD-OUT split, never on the
   queries it is evaluated against — and say which split.
3. **Report the operating point honestly:** false-accept rate on the absent
   set and false-reject rate on the present set, with denominators and null
   controls. The bench's 8-present/8-absent set is the minimum; extend it.
   **Fail-closed is the required direction: an uncertain place is a refusal
   with alternatives (R20's existing honest path), never a guess.**
4. **Wire it as the perception-side replacement for the closed-label check**,
   behind config, defaulting OFF until the world work makes detector numbers
   meaningful — but fully tested offline with fixtures now, so the cutover
   flips a flag rather than writing new safety logic under time pressure.
5. **Regression pin:** corpus rows 10–13 (Narnia, moon, office, home) must
   refuse under the perception path exactly as they do today under the
   closed-label path. That equivalence is the acceptance test.

OWNS: a new abstention/confidence module, `instructnav/grounding.py` and
`navigation/semantic_map.py` where the verdict is consumed (smallest touch),
the perception config surface, tests + fixtures, `PG3_STATUS.md`.
MUST NOT TOUCH: R20's closed-label refusal path (it stays the live default —
this card builds the alternative beside it), `realtime/*`, yield policy, the
detector execution paths (PG-1). Standard house rules.

## Definition of done

Gate green; ≥10 seeds RED (abstention removed; threshold fitted on the eval
set; margin test dropped; detector-agreement signal ignored; fail-OPEN
direction restored; a corpus row 10–13 accepted). Evidence: an
operating-point table (FAR/FRR with denominators + null controls) and the
rows-10–13 equivalence demonstrated. Honest `does_not_prove`: any number
measured in the current untextured world is provisional and must be re-earned
after the world work. `PG3_STATUS.md` standard register.
