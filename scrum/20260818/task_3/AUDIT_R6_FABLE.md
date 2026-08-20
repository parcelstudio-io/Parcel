# AUDIT — R6 "the answered turn" · Fable

**Date:** 2026-08-19 · **Card:** `scrum/20260818/task_3` · **Executor:** Claude Opus (agent, via workflow)
**Verdict:** **ACCEPT_CLOSE.**

## Independently verified

1. **Fresh full gate, auditor's own run: PASS, 6242 passed** (tree includes
   R7; R6's own final gate at 6202 + R7's 40 = consistent), ruff `new 0`.
2. **All 16 seeds re-run by the auditor: 16/16 RED**, byte-identical restores.
   This also closes the one evidential gap the read-only verifier found — the
   executor's final seed sweep (22:24) predated a docstring-only lane edit
   (22:27); my sweep ran against the current bytes.
3. **Read-only verifier (workflow, structured):** every mechanism confirmed at
   code level — repay captures owed-before-connect, fires once per reconnect,
   never on a completed response, bounded at 3-with-reset, ledgered and
   counted; the beat gate's three conditions with speech as the fail
   direction; `_responses_pending` exactly tracking delivered frames; all 19
   R4L reconnect tests present (19 → 44, two genuinely strengthened);
   evidence artifacts match the doc's transcripts and costs verbatim. Its
   three findings are cosmetic (line citations stale by +14 from that late
   docstring; an artifact-table row says three gate runs where four exist,
   with the fourth matching the pasted block byte-for-byte; a 708-vs-731
   baseline discrepancy between two status docs on an untracked file).
4. **`protocol.py` untouched** — `ResponseCreate.instructions` already existed
   at `877d9f4`; confirmed against the committed blob.

## The two catches that improve on the card

* **Deviation 3 corrected a card error of mine:** the card's two-condition
  skip would have silenced `get_status`/`recall_memory`, whose ok result IS
  the answer. The receipt-tools third condition (unknown tool ⇒ speak) has
  the right failure direction: one beat too many, never silence.
* **Deviation 6 dodged a wire trap:** `response.instructions` REPLACES the
  session prompt, so the beat rule is composed with the session instructions
  — bare-rule substitution would have stripped persona and guardrails from
  exactly the beat that reports what the robot did.

## The two discoveries beyond the card

1. **The phantom stall (fixed, seeded S16, proven live both directions).** The
   watchdog measured silence from the provider's last frame, not from our
   request — any turn typed after a quiet gap longer than `stall_timeout_s`
   was declared stalled ~2 s after it went up. This manufactured the
   swallowed-turn incident this card exists to fix and almost certainly
   explains R4L's and R5's "high and unexplained" stall counts — that open
   risk is now CLOSED with a mechanism.
2. **The provider refuses every `assistant` and `system` conversation item
   this lane has ever sent** (`invalid_value: 'text'` → wants
   `output_text`/`input_text`). Consequences, now proven rather than
   suspected: every session open and reconnect replays only the owner's half
   of history, and `narrate_event` — R4L Defect B.3's whole delivery channel —
   is a no-op on the wire (probe 3: item refused, `narrations: 1` still
   counted, reply mentioned nothing). Correctly NOT fixed here
   (`protocol.py` frozen beyond the one field); the status doc carries the
   two-line remedy. **This is the top carry-forward and should be the next
   card (R8):** content types per role in `ConversationItemCreate.to_payload`,
   pins on the content type, `server_errors` surfaced in the snapshot (so a
   counted narration that never landed is visible), and one live turn proving
   a narrated fact reaches the model's reply. R7's audio landing makes the
   third R6 carry-forward (an owed-turn signal for server-VAD voice turns)
   part of the same follow-up.

## Live-proof standing

Single-beat navigation turns (twice, `suppressed=1 requested=0`), deferral
narrated on both the announced and silent-call paths, forced mid-turn
deafness repaid with zero owner action, plus one unforced instance caught and
recovered. ≈$0.072, in-process runtime, no port bound, owner's DB never
opened (sweep corroborates: its mtime predates both cards by ~32 minutes).

## Carried forward

R8 (protocol content types + server_errors surfacing + voice-turn repay
signal); the repay answering a STALE turn when history replay is half-blind
(session 2's degraded repay — fixed as a side effect of R8); stalls
themselves now survivable, explained, and mostly self-inflicted — re-measure
provider stall rates after R8 before blaming the provider again.
