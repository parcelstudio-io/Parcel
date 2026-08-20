# AUDIT — R8 "the whole conversation on the wire" · Fable

**Date:** 2026-08-20 · **Card:** `scrum/20260819/task_1` · **Executors:** two
(see provenance) · **Verdict:** **ACCEPT_CLOSE.**

## The collision, first — a register lesson before any technical claim

Through an orchestration failure of MINE, two executors held this card (and
R9) concurrently: the original overnight executor was presumed dead after a
session interruption and a finisher was dispatched — while the original was
in fact alive and completing. Both sides detected it and disclosed it; the
damage was to EVIDENCE, not code: seed harnesses corrupted each other
(false-GREEN seeds when one harness's restore overwrote the other's
mutation; one stale mutation transiently promoted into the working tree,
caught by inspection). **Register lesson: one card, one tree.** Process
adopted from today forward: (1) never dispatch a finisher without proving
the prior executor dead (fresh-mtime sweep over its OWNS + task state);
(2) FIX-A harnesses restore from a single startup snapshot and END with a
whole-tree repair check (R9's session-B harness pioneered this — now the
standard); (3) the auditor's solo re-run of every seed is the only seed
evidence that counts toward close. Items (below) are that solo re-run.

## Independently verified (all post-collision, sole tree owner)

1. **Fresh full gate, auditor's own run: PASS, 6396 passed** (R7 6242 + R8's
   27 + R9's 127), ruff `new 0`, all hard gates green.
2. **All 26 R8 seeds re-run solo: 26/26 RED, tree byte-restored** (git
   status hash identical before/after). This supersedes every seed number
   produced during the overlap window.
3. **The wire fix is exactly R6's prediction, proven the right way:** a bare
   socket probe (no lane, no response.create, zero billing) over all nine
   role×type pairs — user/system → `input_text`, assistant → `output_text`,
   and the old `"text"` accepted for NO role (the historical failure was
   total). Bonus discovery with real value: the provider echoes the client
   `event_id` inside `error.event_id`, so per-item refusal attribution is a
   field read, not protocol surgery.
4. **Live: the narration channel is HEARD for the first time** — a planted
   fact ("blue umbrella on the bench") surfaced in the model's reply;
   reconnect replayed BOTH conversation halves with zero `invalid_value`
   (R6's same event: six refusals); a mission terminal was narrated
   truthfully as a failure (the guardrail holding on a fact the model could
   only know from the narration).
5. **The voice-turn owed signal works end-to-end:** piper speech →
   `send_audio` → `voice_turn_owed=True, responses_pending=0` (the pair R6
   could not represent) → forced deafness → `[turn repaid …SPOKEN]` →
   correct answer. Kept as a SEPARATE flag beside `_responses_pending`,
   preserving R6's transport-accepted invariant — pinned by seed S21.
6. **Stall exoneration data:** zero unforced stalls across both sessions
   including a 90 s quiet gap (small sample, stated as such) — consistent
   with R6's phantom-stall diagnosis; the provider was largely innocent.
7. **Three GREEN-seed disclosures handled to standard:** S22's test was
   wrong and was rewritten to the observable case; S23/S24 were behavior-
   equivalent mutations whose unreachability is itself a documented
   structural result — none deleted.
8. **Read-only verifier: CLEAN** (two cosmetic date/warnings-line drifts).
   Provenance split (§Orphaned work assessment): all four work items
   authored by executor 1; audited, gap-filled, and registered by the
   finisher. Consistent with file md5s and mtimes.

## Deviations accepted

`narrate_event` gained a fourth floor-gate refusal (never talk over a spoken
turn awaiting its answer — seed S26): outside the card's letter, inside its
spirit, and mode:audio made it necessary. `event_id` on two protocol
dataclasses: the minimal honest carrier for attribution.

## Open risks endorsed (executor's own list)

Noisy server-VAD can arm repeated repays (bounded by the backoff ladder and
budget — watch in audio sessions); **the narration channel now costs money
for the first time** — every historical spend figure predates a working
channel; the R11 whisperer knob (`max_updates_per_minute`) is the control,
and the owner has already specified it. One environmental flake documented
causally (a wall-clock CPU-budget test reddened by the owner's llama-server
at 1469% CPU — passes in isolation and in the green gate).
