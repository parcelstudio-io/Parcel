# AUDIT — R9 "the owner's e-stop" · Fable

**Date:** 2026-08-20 · **Card:** `scrum/20260819/task_2` · **Executors:** two
(same collision as R8 — see AUDIT_R8_FABLE §collision; both sessions
disclosed it and reconciled rather than overwriting each other)
· **Verdict:** **ACCEPT_CLOSE.** The owner's ruling — Space is THE e-stop,
"Die Stop" is the spoken phrase — is implemented, live-proven, and pinned.

## Independently verified (post-collision, sole tree owner)

1. **Fresh full gate, auditor's own run: PASS, 6396 passed**, ruff `new 0`.
2. **All 16 R9 seeds re-run solo with the hardened snapshot-restore
   harness: 16/16 RED, `0 file(s) needed a final repair`,** tree
   byte-restored. Supersedes the overlap-window seed evidence on both
   sessions' sides.
3. **The ruling, in code where claimed:** `SPOKEN_EMERGENCY_PHRASE =
   "die stop"` with ASR variants (die/dye/dai/di + bounded gap + "stop"),
   evaluated in the SAME first-position branch as the typed phrases —
   local-first ordering preserved on both origins; bare "stop" stays
   whole-utterance exact so "let's stop by the store" cannot latch (pinned,
   spoken AND typed). Space posts `emergency_stop` (was: nominal stop),
   `isTypingTarget` guard byte-identical, latched banner with
   release affordance driven by the snapshot's `emergencyStopped`.
4. **Live proof (6 sessions, $0.127):** spoken "Die stop." latched a
   RUNNING mission 4/4; "Die stop! Die stop!" latched (exact-match could
   not have); typed latch; negative sentence latched nothing in either
   modality; release exercised 4× with the full cycle proven
   (409 while latched → cleared → motion accepted).
5. **Read-only verifier: minor-only.** Line-number drift; an unverifiable
   starting test-count; and one real evidence defect — the session-B
   addendum shipped a literal `GATE_OUTPUT_PLACEHOLDER`. **Second
   occurrence of the R5 register lesson** (an evidence section written
   before its evidence): the claim is struck and superseded by the
   auditor's own green gate; the lesson is now two-for-two and every
   future status doc gets its gate block checked for placeholders at audit.

## Owner-gated findings (decisions on file, not defects)

1. **The transcriber drops the leading /s/ of "stop" after /aɪ/ words** —
   "Dye stop." → "Dice top", three measurements across two cards. Your own
   phrase survived 4/4 spoken. The one-character widening (`s?top`) would
   also latch "tie-dye top"-class phrases: a real false-latch trade the
   ruling did not authorize, so it ships UNCHANGED and the live transcripts
   are pinned red-on-change. Say the word to widen it.
2. **Mission log records an e-stop terminal as `navigation_disabled`, not
   `emergency_stop`** — `runtime_channels.py` throws the reason away
   (`del reason`) on every preempt path. Legibility gap, not a safety gap;
   outside R9's OWNS; filed as a one-line candidate card.

## Deviations accepted

A 6-line `runtime.py` emit (channel/level/wording of the voice-latch event)
that R9's own Deviation 1 admits the wiring did not strictly require —
accepted as visibility polish, noted as scope drift. Transient seed
mutations of frozen files during harness runs (disclosed): inherent to the
FIX-A style; the snapshot-restore harness plus the auditor's solo re-run is
the containment. HEAD's movement during the window is the owner's own
commit; executors staged nothing (verified: nothing staged, stash empty).
