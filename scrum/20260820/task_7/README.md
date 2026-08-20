# Task 7 — R18: a dog that knows what it knows (scene answerability + memory surfacing)

**Executor:** Claude Opus (agent) · **Auditor:** Fable
**Trigger:** owner-session failures F3 and F4 (evals/20260820/owner_session_1)
— "I can't actually see anything around me" spoken by a robot with LiDAR,
semantic regions, and person tracks; "there's no memory of what I know about
you yet" from a store holding days of conversation. Both are the same shape:
the model cannot say what the robot knows.
**DISPATCH GATE: after R19 (task_8) closes** (sequential, one card one tree).
**RE-CUT 2026-08-20 after live_run_1 scoring** (voice_corpus_v1/live_run_1/
README.md): both failures recurred by NEW mechanisms — F3 produced no
false-blindness claim this time, just two fillers and silence, root cause:
the broker's 7 tools contain NO scene-capable tool at all (work item 1
stands exactly as written); F4's `recall_memory` actually FIRED and the
answer was eaten downstream — the narration/beat path, which is R19's
defect. Work item 2's diagnosis half is therefore DONE (root cause moved);
its fix half is: verify recall's answer SURVIVES to speech after R19 lands,
and make the recall result carry honest provenance as specified.

## Work

1. **Scene answerability.** A deterministic scene summary from EXISTING
   perception state (nearest semantic regions with bearings/distances,
   person tracks count + nearest, obstacle clearance) rendered as a compact
   fact block: (a) into `get_status`'s result so "what do you see" has a
   tool answer, and (b) available to the DI at session boundaries. Honesty
   rule both ways: name only what perception actually holds (no invented
   visuals — this is LiDAR + semantics, not a camera; the phrasing must not
   claim vision, e.g. "my sensors show…"). The SI is NOT touched; if the
   model still claims blindness WITH the tool available, report it as an
   SI-v3 input, don't edit prompting.
2. **Memory surfacing.** Diagnose WHY recall came back empty in the session
   (recall_memory not called? called and returned nothing? store query
   wrong?) — the ledger's tool rows answer this; state the root cause
   before fixing. Then: recall_memory queries the FULL conversation store
   (both origins) with recency+relevance, and returns honest provenance
   ("from our chat on Tuesday…"). "What do you remember about me" must
   yield real remembered facts against the real store (live proof on a
   scratch COPY of the owner's DB — read the original read-only, never
   open it for writing).
3. **Regression targets:** corpus categories `scene` (27–29) and `memory`
   (30–31) flip from expected-FAIL to expected-PASS; wire both into the
   offline suite with fake stores so the gate pins them forever.

OWNS: `runtime.py` (scene summary + status wiring), `tool_broker.py`
(get_status/recall result plumbing), `memory.py` and/or
`conversation_store.py` READ paths (smallest honest touch, justified),
`realtime/prompting.py` ONLY the DI fact-block render if needed (SI text
untouched, version-selection preserved), tests, `R18_STATUS.md`.
MUST NOT TOUCH: lane, protocol, ingress, whisperer bands, yield policy,
SI wording, owner's live DB (scratch copies only). DoD: gate green; ≥8
seeds RED (scene block invents an object class; blindness claim returns
with tool present ⇒ at minimum the tool-answer path pinned; recall ignores
one origin; provenance dropped; store opened read-write in the proof);
live proof of both questions answered truthfully; standard register.
