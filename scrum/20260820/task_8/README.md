# Task 8 — R19: the silent companion (answers eaten by the beat gate)

**Executor:** Claude Opus (agent) · **Auditor:** Fable
**Trigger:** live_run_1 scoring — **the run's dominant defect is silence, not
error**: 9 consecutive owner turns produced 3 filler lines ("Okay, let me
think…") and ZERO answers; `tool_beats_suppressed = 8 of 10`, eating among
others the battery figure and the memory answer. The owner asked questions
and the dog said nothing. Evidence: evals/20260820/voice_corpus_v1/
live_run_1/{README.md,results.json}, the "silence" finding.
**DISPATCH GATE: after R17 closes.** (Priority: this outranks R18 — R18's
memory half depends on it.)

## Work

1. **Root-cause first, in the doc, before any fix.** R6's skip rule was:
   suppress the post-tool beat ONLY when (model spoke in the carrying
   response) AND (status ok) AND (tool ∈ receipt tools:
   navigate_to/play_gesture/set_pose). `get_status`/`recall_memory` were
   answer-shaped and must always beat. live_run_1 shows answer tools being
   eaten — determine exactly which condition drifted (R10 added
   circle_owner/follow_owner to the surface; did the receipt set or the
   spoke-in-response detection change? Did filler count as "spoke"?).
   The FILLER is the smoking gun: a content-free "let me think" counting as
   the turn's speech satisfies the suppression condition while carrying no
   answer — the exact failure R6's rule was designed against, inverted.
2. **Fix with the failure direction R6 pinned:** one beat too many, never
   silence. Candidate shape (executor validates against the wire): a beat is
   suppressible only if the in-call speech was SUBSTANTIVE (not a filler
   pattern / minimum content), and answer-shaped tools are NEVER
   suppressible regardless — restore and pin that property against the
   CURRENT tool surface, including the R10 additions.
3. **The filler habit itself:** fillers arrive before tool calls despite SI
   v2 and R6's beat instructions. Do not touch the SI; instead ensure the
   per-response instructions on the beat request explicitly demand the
   ANSWER content. If fillers persist, report as SI-v3/model-tier input.
4. **Also in the silence family (same fix window, from the scoring):**
   `set_pose` "executed" while the sit activity expired undelivered —
   surface activity-expiry as a narratable fact (coordinate with R15's
   terminal work, which precedes you in the chain); and the 4 motion
   rejections under the e-stop latch produced ONE narration — a rejected
   tool call is always narratable (it is R11 always-band material: a
   refusal). Verify with R11's decision log.
5. **Live proof:** the exact live_run_1 sequence class — battery question,
   memory question, status question in succession — every one audibly
   answered; plus a latched-e-stop rejection narrated.

OWNS: `realtime/lane.py` (beat gate + per-response instruction),
`realtime/tool_broker.py` (answer-tool classification), `runtime.py`
(rejection/expiry narration wiring), `realtime/whisperer.py` (always-band
refusal entry if missing), tests, `R19_STATUS.md`.
MUST NOT TOUCH: prompting/SI, protocol, ingress, yield. R6's and R11's
existing seeds MUST stay green — their invariants are the frame this fix
lives inside. DoD: gate green; ≥8 seeds RED (filler counts as substantive
again; answer tool suppressed; rejection unnarrated; expiry silent; R6's
two-beat regression — both directions pinned); live proof; standard
register.
