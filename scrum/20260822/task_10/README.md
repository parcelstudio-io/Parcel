# Task 10 — P2-A: an owner model — facts the dog keeps, with consent

**Executor:** Claude Opus · **Verifier:** Fable · **Board:** `../TASK_BOARD.md`
(Wave P1/P2; P0 standing rules apply). **Roadmap:** audit §10 Phase 2 item 1,
§5 "What to do" items 1, 2, 6; HLD §8.4 (the four-store split that was
designed and never built).

## Why
What the hosted model knows about the owner per turn: "unknown" location,
"unknown" name, a 6-line digest, and a 20-row hosted-only tail at session
open (audit §5). "My sister's name is…" becomes a raw row; there is no
`remember` tool, no fact store, no privacy policy; `null_distiller`
(`tiered_memory.py`, `dynamic_prompting.py:737`) never derives a fact;
`owner_notes` (`realtime/prompting.py`) is rendered but never provided. The
2,618 legacy-lane rows are never replayed. Pure software — no hardware gate.

## Work
1. **`owner_facts` table** beside `messages` in the memory store (`memory.py`),
   with provenance (session, turn, `model_proposed | owner_stated`), consent
   state, and soft-delete. R27's writer-provenance and owner-store isolation
   guards apply unchanged — tests use their own store, never the owner's.
2. **A real `Distiller`** (`tiered_memory.py` protocol) over the hosted/local
   LM that proposes facts from a session's turns; a deterministic privacy
   policy decides what may be kept (names, preferences, routines, places —
   yes; health, finances, third-party secrets — ask first). Facts render into
   `owner_notes` (renders only when non-empty so the pinned DI digest survives).
3. **`remember_fact` tool** in the broker (`realtime/tool_broker.py`, re-read
   P0-B's edits first; add a new region): model proposes, policy decides,
   the dog CONFIRMS aloud what it stored; `forget`/`edit` paths; "what do you
   know about me" answers from the table.
4. **Full-ledger replay at session open** (`realtime/lane.py`): deduped,
   capped, both lanes — not the 20-row hosted tail.
5. **Owner action, surfaced not performed:** the 256 synthetic rows
   (2883–3138) must be quarantined BEFORE any distillation runs on the owner's
   real store (`tools/quarantine_synthetic_memory.py --apply`). The card's
   distiller refuses to run on a store with an un-quarantined synthetic range
   (seed it), so the dog cannot learn that the owner loves lampposts.
6. Pre-register the memory-probe family for owner session 3: sister's name
   across a restart; a stated preference recalled unprompted next session;
   "don't remember that" honored; what-do-you-know lists only consented facts.

## Proves
A memory-probe family passes pass^3 on a scratch store through the real
lane: it remembers a fact across a restart, says what it stored, and says
what it will not store.

OWNS: `memory.py` (owner_facts), `tiered_memory.py` (distiller
implementation), new `owner_model/` package if needed, `realtime/prompting.py`
(owner_notes), `realtime/tool_broker.py` NEW `remember_fact` region,
`realtime/lane.py` session-open replay region, `tests/test_p2a_*.py`,
`task_10/` docs.
MUST NOT TOUCH: `whisperer.py`, affect/identity (P2-B), the broker's P0-B
regions, safety core, the owner's live `parcel_memory.sqlite3`.

## Definition of done
Probe family measured on a scratch store; synthetic-range refusal + consent
bypass seeds RED; `P2A_STATUS.md`; the owner's store byte-unchanged (sha in
the status doc, computed read-only).

## Build on P0 (binding — read the P0 status docs first)

* **Prototype-only keys go in the overlays, never in the shipped files:**
  `configs/robot.prototype.yaml` (P0-A, selected by `PARCEL_PROFILE` /
  `launch_stack.sh --prototype`), `configs/navigation/prototype.yaml` (P0-D),
  `configs/realtime.prototype.yaml.example`. The shipped `robot.yaml` stays
  byte-identical to its locked digest.
* **GPU is a given:** `.parcel` carries onnxruntime-gpu 1.29 with CUDA honoured
  (P0-C) — assume `cuda_fp16` for OWLv2 and SigLIP-2; never reintroduce a CPU
  fallback as the default.
* Extend P0-B's validated realtime keys rather than adding parallel ones; the
  `remember_fact` tool joins the broker beside P0-B's `navigate_to`
  ask-not-refuse result shape (structured result, not prose).
