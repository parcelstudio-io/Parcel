# Task 3 — R10: arrive like you mean it (REVISED 2026-08-20, evidence-backed)

**Date:** 2026-08-19, REVISED 2026-08-20 after the research+bench wave
· **Executor:** Claude Opus (agent) · **Auditor:** Fable
**Evidence (read BEFORE the card):**
`<scratchpad>/csbench/reports/bench_navmodel.md` (arrival-semantics probe,
tool-surface-hole failures, verbatim fabrications) and
`<scratchpad>/csbench/reports/res_semnav.md` + `res_grounding.md` (prior
art). Scratchpad root: `/tmp/claude-1000/-home-jaewoo-jang-Desktop-Projects-Parcel/799cb356-4cb4-445b-a784-306b6c6fd4a6/scratchpad`

**What the evidence changed (owner informed):**
* Model-supplied arrival RELATION hints are reliable (100% on 12 firm-gold
  phrasings, both tiers, perfectly self-consistent on the shipped mini) —
  so relation becomes a HYBRID: the model may hint, the local table
  validates and can override, and the table alone decides when no hint
  arrives. FACE and terminal etiquette stay purely local — both tiers
  answered `face=goal` for the door 6/6 where the owner wants turn-back.
* The TOOL-SURFACE HOLE is the top risk, not arrival math: with no
  orbit/follow tools, the mini fabricated `navigate_to("with owner")` /
  `("run route")` / `("run path")` 5/6 (junk directives straight at the
  router), and realtime-mini falsely DENIED the ability ("I can't do a full
  circle around you") — a lie, since `OrbitOwner` and `FollowFormation` are
  admitted skills. The surface must match the body.
* "Reach the door → turn back → ask what's next" will NOT emerge from the
  model (0/12 chat, 0/6 injected-arrival trials): it must be a local
  behavior plus an arrival event carrying an ask-hint (R11's mechanism).

## Work

1. **Root-cause the live `semantic_target_unreachable`** (unchanged from
   draft): why "inside sidewalk, tolerance 0.0" was unreachable live;
   in-region goal resampling with keepout-aware candidates; the give-up
   names the candidates tried.
2. **Arrival-semantics table, hybrid relation:** local table keyed by
   semantic class (region → inside; portal/door → near, DO NOT cross;
   object → near; person → social distance). Extend the `navigate_to` tool
   schema with an OPTIONAL `relation` hint (inside/near/social): accepted
   only when it agrees with or refines the table's class entry; a
   conflicting or nonsensical hint loses to the table, logged. Face and
   terminal etiquette come ONLY from the table (face=owner at portal/object
   terminals; social standoff for persons). Unknown class → near, never a
   guess.
3. **Close the tool-surface hole:** declare `circle_owner` and
   `follow_owner` (with a `pace` param for run/walk — R11's pace_intent
   consumes it) on the broker, routed through the EXISTING validate→door
   chain into `OrbitOwner`/`FollowFormation`. Plus `navigate_to` argument
   validation: a place must resolve against the semantic map/place list —
   junk like "with owner"/"run route" gets a structured refusal naming the
   nearest valid places, which the model can narrate honestly.
4. **Door etiquette as a local behavior:** portal arrival → orient to owner
   → emit the arrival fact WITH the ask-what's-next hint through the
   narration channel (R8's wire fix makes it heard; R11's hint mechanism
   makes the model actually ask — if R11 has not landed when you get here,
   emit the fact with the hint TEXT inline; the channel exists either way).
5. **Orbit feasibility with narrated refusal** (unchanged from draft):
   clearance annulus at admission AND abort-with-narration mid-orbit;
   refusal names the blocked arc; keepout/yield never weakened. This is now
   load-bearing for honesty: once `circle_owner` exists, "I can't walk
   around you here — there isn't room on your left" must come from the
   VALIDATOR, not from the model guessing at its own abilities.

## OWNS / MUST NOT TOUCH

OWNS: navigation/planner arrival layer (executor maps exact files in the
status doc before editing), orbit feasibility validator, `runtime.py` glue,
`tool_broker.py` (new tool declarations + navigate_to arg validation +
schema hint), scene semantics class tags if needed (additive; run the
release-parity sync if packaged), tests, `scrum/20260819/task_3/
R10_STATUS.md`.
MUST NOT TOUCH: `lane.py`, `protocol.py`, `ingress.py`, `prompting.py`
(if the new tools make an SI sentence stale, REPORT it — SI v3 is its own
card), `agent.py`, `configs/robot.yaml`, `evals/**`, yield/person-stop
policy B22, owner's processes. Never commit/stage/stash.
HARD CONSTRAINT: hard-safety gate stays green; frozen nav baseline moving is
a card-stopping finding.

## Definition of done

Full `ci_gate --tier commit` green; ≥12 seeds RED/restored (incl.: inside
regressed to near; resampling removed; door crossed; face hint accepted from
the model; conflicting relation hint beats the table; junk place accepted;
circle_owner bypasses the validator; orbit refusal silent; mid-orbit closure
keeps orbiting; unknown class guesses). Live proof: sidewalk ends inside the
region (path recorded); door ends near+facing with the ask heard
(transcript); "circle around me" WORKS via the new tool in open space
(path) and REFUSES with narration when boxed in; "run with me" routes to
follow_owner with pace instead of a fabricated navigate_to. Paths saved as
timestamped JSONL for task_5. Costs pasted (<$1.50). R10_STATUS.md standard
register.
