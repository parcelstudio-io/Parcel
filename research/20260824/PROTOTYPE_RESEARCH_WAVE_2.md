# Prototype capability research wave 2 — synthesis · 2026-08-24

Status: **Codex-authored evidence; independent Fable cross-review pending.**
This is a surgical amendment to the portable HLD, not a replacement for it.

## Decision summary

Four pre-registered mini-studies tested the smallest mechanisms that could
materially change the mountable prototype design. The wave produced one
conditional confirmation, one mechanism-level confirmation, and two useful
refutations:

| capability | experiment | result | prototype decision |
|---|---|---|---|
| proactive conversation | local opportunity gate on the frozen H2 replay | numerical rows pass, but **14/17** false-owner cases and **9/9** malformed-input cases speak | keep event-driven local admission; require commissioned owner/consent evidence and a typed fail-closed contract before enabling speech |
| generalized noticing | visual + place + track + age fusion over regenerated H6 observations | appearance AUC **0.719**; fused median about **0.99**, but same-label map matching hides **17.0%** of new probes and false-rate evidence is too short | preserve separate identity/place/change/social evidence; `GAZE_VERIFY` before memory or speech; collect a synchronized physical log |
| continuous learning | safety-shielded decaying contextual bandit over 320 seeded runs | expected regret improves **40.26%**, but feedback, quiet-user talk, and drift bars fail; **14/40** drift runs are right-censored | explicit owner preferences in M1; implicit learning shadow-only; never learn authority, travel, or safety bounds |
| continuous autonomous motion | terminal-aware return + all-track TTC over six simulated robot-hours | **refuted**: contacts 319→323 and contact time 89.1→244.6 s | proactive translation remains off; replace stop-and-return with a safe-hold invariant and static-plus-dynamic receding-horizon planning |

In audit terms, this wave produced **one promising architecture seam, one
conditional perception direction, and two decisive negative results**. None
promotes proactive speech, generalized perception, preference learning, or
autonomous translation to a physical robot.

The work advances the design because it removes four tempting shortcuts:
timer-driven chatter, one novelty scalar, enacted implicit preference learning,
and stop-only social navigation. It does **not** establish physical prototype
readiness. No new study used a real microphone, camera/LiDAR rig, person
tracker, LIO provider, Unitree body, or human longitudinal cohort.

## Research discipline and verification

Each `DESIGN.md` was frozen before its harness was implemented. The experiments
use isolated research code and do not mutate product state. Canonical evidence
is in each folder's `results.json` plus `RESULTS.md` and `VERDICT.md`.
SAFE-ADAPT and terminal-aware action bind their designs by SHA-256. Conversation
and perception have timestamp history and explicit post-run amendment records,
but do not bind every original preregistration/code/model artifact comparably;
their provenance is therefore weaker.

- Conversation and SAFE-ADAPT were independently rerun by Codex; their
  decision artifacts were byte-identical after removing only measured timing.
- The perception JSON acceptance arithmetic was independently recomputed. Its
  short 0.35-minute causal exposure is explicitly inadequate for a false-rate
  claim even though the pre-registered median arithmetic is under the bar.
- The motion harness reproduced all six H3 baseline integrity fields for all
  three seeds, including full and translation command-stream hashes.
- Ruff passes on all four experiment harnesses. No hosted API was invoked;
  hosted spend for this wave was **$0.00**.

Post-run audits are reported rather than hidden. They do not move frozen bars:
they narrow what a clean simulation result is allowed to mean.

## Finding 1 — conversation is an opportunity door, not a periodic thought

The proposed local gate admitted all 15 useful unarguable H2 opportunities and
none of the 39 negatives, reducing hosted-call candidates by **65.91%** versus
naive novelty. The exact score is not trustworthy outside that authored,
strongly separable corpus. What survives is the mechanism:

```text
grounded world event
  -> typed/freshness validation
  -> identity + consent + privacy + interruption hard gates
  -> relevance/cooldown/dedup score
  -> SPEAK | SILENT_GESTURE | DROP
  -> optional hosted phrasing only after SPEAK
```

The strongest refuters were upstream. Falsely declaring an absent person to be
the owner admitted 14/17 negatives. Removing required fields, passing a string
instead of a boolean, or using NaN ages admitted 9/9 malformed candidates in
the research dictionary interface. Therefore:

1. the research script is **not** prototype code;
2. `OpportunityCandidateV1` must reject unknown schema versions, absent fields,
   wrong types, non-finite values, mixed epochs, and stale evidence;
3. owner identity is a belief with confidence, ambiguity, consent, and source
   epoch—not an `owner_present` boolean; and
4. proactive speech defaults off until mounted multi-person, TV, self-TTS,
   quiet-hour, and overlapping-speech refuters pass.

Silent gaze/posture remains available when speech is refused. This preserves
continuous visible responsiveness without creating an API call or social
interruption.

## Finding 2 — noticing must produce a structured world delta

The H11 study regenerated 42 H6 scene frames and ran the repository's real
OWLv2/SigLIP inference path. It then simulated map, track, and age association
because H6 did not preserve synchronized pose/track rows. Spatial-temporal
evidence can rescue weak appearance matching in principle, but the near-perfect
fusion AUC is oracle-seeded mechanism evidence, not a measured tracker result.

A single fused novelty number loses the distinction the dog needs. Introduce:

```text
WorldDeltaV1
  identity_novelty     # probably a new entity, class-conditioned
  place_novelty        # unusual entity/class at this place
  change_surprise      # known entity moved, missing, or materially changed
  social_opportunity   # appropriateness of looking/remembering/speaking now
  evidence             # pose/covariance, track generation/confidence,
                       # depth, timestamps, calibration/source epochs
```

The response ladder is asymmetric:

```text
uncertain delta -> GAZE_VERIFY -> second view/depth association
  -> governed memory candidate
  -> optional ConversationOpportunityGate
```

A world delta cannot directly command translation or call a hosted model. The
next decisive test is a 30–60 minute synchronized mounted/sensor-rig log with
same-class neighbors, owner/non-owner crossings, track swaps, moved objects,
occlusion, stale pose, and SLAM relocalization. The arithmetic fusion benchmark
covers scoring only; real association/map lookup and target-Orin latency remain
unmeasured.

## Finding 3 — learning may personalize proposals, never permissions

SAFE-ADAPT reproduces the **simulation invariants** of placing a learner behind
immutable action/capability gates and a same-process JSON persistence round
trip. That does not validate a product shield: translation is structurally
absent, hard gates receive complete simulated data, and cadence is largely
imposed. It refutes the tested decayed bandit as an enacted preference policy:

- final negative-feedback reduction misses for social (**15.77%**) and mixed
  (**12.19%**) profiles against a 20% bar;
- quiet-user talk fraction is **0.2173** against a 0.20 ceiling; and
- drift recovery median is **464** eligible opportunities, while the p95 is
  not estimable because 14/40 runs remain right-censored after 710–762
  post-shift opportunities.

M1 should store explicit likes, dislikes, quiet periods, and cooldowns in a
versioned `PreferencePolicyStateV1`. An implicit learner may log proposals and
counterfactuals in shadow mode, but its output cannot enact behavior until a
held-out longitudinal human study passes. Negative feedback or preference
drift falls back to the last explicit profile; it does not trigger more
exploration. No learner can grant a skill, travel radius, authority, or safety
threshold.

## Finding 4 — continuous command emission is not continuous planning

The motion study preserved 16/16 initiatives and zero-tick preemption, and the
combined arm observed zero moving contacts. It nevertheless increased total
contacts and nearly tripled contact time. TTC braking correctly detects an
approaching person, but an exact-zero command leaves the robot on that person's
path. A return that begins after a 240-second outbound budget cannot repair an
unsafe active phase.

The proposed arm bundled all-track TTC and the terminal, so the experiment does
not isolate their individual causal effects. `STAND_ASIDE` was never exercised,
only one preemption occurred during a terminal, and the recorded zero release
is policy/harness evidence rather than an independently witnessed gateway/body
stop. These limits strengthen the no-promotion decision.

Replace the refuted controller with this hypothesis:

```text
admission requires:
  reachable safe-hold region
  + outbound success predicate
  + reserved return/yield time and energy

execution:
  receding-horizon static + predicted-dynamic trajectory
  -> objective OR mapped safe-hold region
  -> HOLD | RETURN | YIELD_ASIDE | FOLLOW_OWNER | RELEASE
```

The local controller may continuously refresh a trajectory or exact `HOLD` at
20–50 Hz. The task/global planner runs only on a new goal or material world
change. Breathing, posture, and gaze are independent non-translating body
channels. This is how the robot can remain visibly alive without an LLM or a
global planner running every tick.

## Integrated mountable mini-design

```text
camera / LiDAR / IMU / audio / body feedback
                 |
        synchronized evidence spine
                 |
   tracks + owner belief + pose/map health
                 |
       WorldDeltaV1 + WorldEventV1
                 |
     deterministic drives/action auction
           /                 \
 non-travel proposal       operator mission
           |                    |
 preference state/shadow   ActionContractV1
           |                    |
 conversation opportunity  task/local trajectory
     /           \              |
 gesture/drop   hosted phrase   safety + sole-writer gateway
     \           /              |
      outcome/event log <--- body witness
                 |
 governed memory candidates + explicit preference updates
```

The key ownership rules are:

- sensing and safety run continuously and locally;
- deterministic code owns timing, authority, privacy, cost, freshness, and
  action terminals;
- hosted models converse, phrase an admitted grounded event, or propose a
  typed compound plan, but never control the body;
- memory records provenance/correction/revocation and does not silently become
  permission; and
- exactly one gateway writes to Unitree now and a body-neutral port supports a
  future custom robot.

## Build consequences and next evidence

Proceed in this order:

1. implement versioned fail-closed validators for evidence, world delta,
   opportunity, preference state, and action contracts;
2. commission the synchronized observation spine and collect the physical
   noticing/identity log before tuning any score;
3. enable only non-travel `LOOK`, posture, breathing, and silent verification;
4. run the mounted voice/opportunity corpus and keep proactive speech off until
   privacy/interruption bars pass;
5. prove supervised known-point navigation with localization, clearance, and
   safe-hold invariants before Follow or self-authored translation;
6. add explicit preference controls and shadow logging, then run a held-out
   longitudinal human pilot; and
7. evaluate “alive, purposeful, natural, not annoying” in ten supervised
   sessions while counting every intervention, false noticing, interruption,
   contact, hosted call, and action terminal.

Do not begin another broad model comparison. The critical unknowns are now
physical evidence quality, owner/voice identity, localization/clearance,
safe-hold trajectory behavior, and human social tolerance. Those are prototype
integration tests, not questions another desktop LLM study can settle.

## Canonical study artifacts

- [`conversation-opportunity/`](conversation-opportunity/)
- [`spatiotemporal-noticing/`](spatiotemporal-noticing/)
- [`safe-preference-adaptation/`](safe-preference-adaptation/)
- [`terminal-aware-continuous-action/`](terminal-aware-continuous-action/)

Fable should independently review each design/result/verdict pair and rerun the
cheap deterministic rows before any finding is promoted into an implementation
acceptance test.
