# Task 4 — R15: "done" means done (completion over-claim on activities)

**Executor:** Claude Opus (agent) · **Auditor:** Fable
**Trigger:** owner session 1, F2 (evals/20260820/owner_session_1): the model
said "Done—I made a small circle around you, and it was okay" ONE SECOND
after the orbit was admitted — a physically impossible completion claim.
Root suspicion: the circle/gesture tool results read as accomplishment
("Okay—I'll make the requested local circle around you safely" / R8's
"Accepted paw_wave for the next control tick"), and the post-tool beat
narrates acceptance as completion. R8's audit flagged the mild form
("I waved. My paw moved"); the session showed the full form.

## Work
1. Make every activity-class tool result state its TENSE explicitly:
   "started: …", never completion language, in the broker detail the model
   sees. Completion is narrated ONLY from terminal events (orbit complete /
   gesture done / aborted), through the existing floor-gated channel —
   symmetric with how navigation terminals already work.
2. Wire the orbit/gesture terminal events into that channel if they are not
   already (R10 built orbit abort narration; verify the SUCCESS terminal
   narrates too).
3. Add the completion-tense rule to the per-response beat instructions
   (R6's `RESULT_BEAT_RULE` — one sentence, present progressive for
   accepted-not-finished work). SI stays untouched.
4. Live proof: "circle around me" → the acknowledgment says it's STARTING,
   and "done" is only said when the orbit terminal fires (tens of seconds
   later); paste both timestamps.

OWNS: `realtime/tool_broker.py` (detail tense), `realtime/lane.py`
(RESULT_BEAT_RULE wording only), `runtime.py` (activity terminal →
narration wiring), tests, `R15_STATUS.md`. MUST NOT TOUCH:
`prompting.py`/SI, protocol, ingress, whisperer bands, yield. DoD: gate
green; ≥6 seeds RED incl. completion language restored in a detail, the
terminal narration dropped, and the beat rule tense regressed; live proof
with timestamps; standard register.
