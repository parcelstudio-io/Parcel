# Local proactive-conversation opportunity gate · VERDICT · 2026-08-24

## Verdict

**CONDITIONALLY CONFIRMED on preserved authored replay; not yet validated for a
physical prototype.**

The experiment supports one architecture decision: proactive talking should be
an event-driven local admission problem, with hosted language generation behind
the door. It rejects timer-driven chatter and a continuously polled local or
hosted "inner mind."

It does **not** support shipping the exact threshold. Perfect precision/recall
came from an unusually separable authored corpus. The post-registered owner
identity refuter admitted 14/17 negatives when a false owner-presence assertion
was injected. A commissioned owner/engagement signal is therefore a prerequisite,
not a later quality improvement.

The raw research interface is also **refuted for product reuse**: a post-run
contract audit admitted 9/9 candidates when safety/turn fields were missing,
encoded with a wrong type, or represented by NaN ages. The architecture decision
survives; this Python dictionary gate does not.

## Prototype design consequence

Introduce a body-local `ConversationOpportunityGate` consuming a typed,
schema-validated `OpportunityCandidateV1`, not prose or a permissive dictionary.
Unknown versions, missing required state, non-boolean flags, non-finite ages,
mixed epochs, and stale evidence must return `DROP_INVALID` before scoring. The
candidate needs at least:

- event and stable subject/track IDs;
- monotonic event time and evidence age;
- event class, novelty, confidence and sensor provenance;
- enrolled-owner track confidence and explicit proactive-speech consent;
- multi-person/private-zone state;
- owner-speaking, endpoint tail, output-lane and activity/checkpoint state;
- quiet policy, last delivered utterance, subject dedup and budget state; and
- a truthful grounded fact or bounded question objective.

The gate should run locally on every candidate, complete in microseconds, write
an auditable reason, and output only `ADMIT_SPEECH`, `SILENT_GESTURE`, or
`DROP`. An admission can open a short hosted phrasing exchange. The response is
not allowed to create motion authority or contradict the candidate's fact.

Continuous local perception, memory, drives and body control still run.
Speech is sparse and event-triggered. When speech is unsafe or annoying, a
head turn, ear/posture gesture or memory-only update preserves lifelike
reactivity for no API call.

## What to implement now

Implement a fail-closed contract validator first, then the replay gate only
after these upstream fields exist:

1. synchronized owner-track confidence plus unknown/non-owner state;
2. local speech/endpoint/output-tail state independent of the hosted lane;
3. stable perception/world-event IDs with timestamps and provenance;
4. age-bearing utterance and subject history; and
5. one owner-facing proactive-speech consent/quiet policy.

Do not copy H2's natural-language `recent_actions`, assume every present person
is the owner, or tune further against this corpus.

## Required next refuter

Run a consented, mounted or hardware-in-loop opportunity study before enabling
speech by default:

- replay owner speech, non-owner speech, TV speech, robot self-TTS, overlapping
  conversation, silence, owner entry/exit, quiet hours and multi-person scenes;
- collect candidates from real synchronized audio/person/world tracks without
  calling the hosted model;
- have at least two people label `speak now`, `gesture only`, or `drop` blind to
  the gate, with owner veto taking precedence;
- require zero non-owner/private/owner-speaking admissions, report identity
  false-accept and dropout separately, and retain >=0.80 precision/recall on
  useful owner-approved opportunities;
- only then enable hosted phrasing under the existing spend governor and run a
  human annoyance/repetition study.

Until that refuter passes, proactive speech should default off on the robot;
silent local reactions may remain enabled.

**Independent Fable cross-review: pending.**
