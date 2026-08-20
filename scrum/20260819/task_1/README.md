# Task 1 — R8: the whole conversation on the wire

**Date:** 2026-08-19 · **Executor:** Claude Opus (agent) · **Auditor:** Fable
**Trigger:** R6's decisive live finding (R6_STATUS.md "two live findings"),
proven with wire traces: the provider REFUSES every `assistant` and `system`
conversation item this lane has ever sent — `invalid_value: 'text'`, wants
`output_text` (assistant) / `input_text` (system). Since R1, every session
open and reconnect has replayed only the owner's half of the conversation,
and `narrate_event` — the entire delivery channel for R4L's mission narration
— has been a no-op on the wire while still counting `narrations`.

## Work

1. **Content types per role** in `ConversationItemCreate.to_payload`
   (`protocol.py`, currently `input_text` for user and `text` for everything
   else): user → `input_text`, system → `input_text`, assistant →
   `output_text`. Wire-verify all three live before trusting any of it —
   R6's evidence names the expected values, but the API is the authority.
2. **A refused item must be visible.** `narrate_event` currently returns True
   and counts a narration the provider dropped. Surface `server_errors` in
   the lane snapshot (count + most recent few, the way `dropped_sends`
   already is), so a counted-but-refused narration is diagnosable from
   `/api/state`. If per-item attribution is feasible without deep protocol
   surgery, take it; if not, say so and surface the aggregate.
3. **Voice-turn repay signal** (R6 carry-forward 3, live-relevant now that
   audio landed): a server-VAD turn has no `send_text` to arm the owed-turn
   accounting. Derive "a response is owed" from the lane's own events
   (input transcription completed / speech stopped with no response created
   since), so R6's repay covers spoken turns too. Keep the accounting
   consistent with `_responses_pending` — the watchdog and repay both read it.
4. **Live proof:** (a) a session open injects tail items for BOTH halves with
   zero `invalid_value` errors on the wire trace; (b) `narrate_event` posts a
   fact and the model's next reply actually reflects it — the first time
   R4L's narration will ever have been HEARD; (c) a mission terminal narrated
   in text mode end-to-end; (d) report observed stall counts across your
   sessions — post-R6-phantom-fix, this is the first honest measurement of
   real provider stall rates (R6 audit carry-forward: exonerate or indict).

## OWNS / MUST NOT TOUCH

OWNS: `src/parcel_robot/realtime/protocol.py` (content types + any pin the
change needs), `src/parcel_robot/realtime/lane.py` (server_errors surfacing,
voice-turn owed signal), tests (extend protocol/reconnect/lane suites),
`scrum/20260819/task_1/R8_STATUS.md`.
MUST NOT TOUCH: `ingress.py` (R9 owns it TODAY — coordinate by not
touching), `tool_broker.py`, `prompting.py` (SI v2 stays; if the narration
now being heard makes an SI sentence wrong, REPORT it, don't edit),
`runtime.py`, `web_panel.py`, `ui/index.html`, `config.py`, `transport*.py`,
`fake_server.py` (additive script steps only), `agent.py`, `configs/**`,
`evals/**` (the corpus stays SI-v1; its fixtures ALSO carry the old content
types — that is capture-time truth, not drift; if a test conflates them,
adjust the TEST provenance-conditionally, never the corpus), yield policy.
Owner's stack: read-only probes at most; own stack/in-process runtime for
live proofs; R5 scratch-memory recipe; never commit/stage/stash.

## Definition of done

Full `ci_gate --tier commit` green; ≥8 seeds RED/restored, including at
least: content type regressed per role (all three), refused-item visibility
removed, voice-turn owed signal removed (spoken turn swallowed again), owed
signal double-counts (repay fires on an answered voice turn). Live proof as
above, transcripts + wire traces + costs pasted (target well under $1,
`gpt-realtime-2.1-mini`). R8_STATUS.md carries the standard register.
