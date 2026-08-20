# Task 3 — R6: the answered turn (turn-retry + single-beat tool turns)

**Date:** 2026-08-18 · **Executor:** Claude Opus (agent) · **Auditor:** Fable
**Trigger:** two defects, both twice-observed live, both rooted in `lane.py`:
1. **A provider stall swallows the owner's turn.** R4L live proof and R5 live
   session 3: a navigation turn produced NO response and NO billing; the lane
   stall-reconnected and survived, but the sentence was never answered and
   never refused. The lane repays nothing after a reconnect.
2. **The two-beat tool turn** (R5's unmet half, AUDIT_R5_FABLE carry-forward):
   the pre-call beat is provider text co-emitted with the `function_call` and
   is NOT suppressible by SI on `gpt-realtime-2.1-mini` (proven, three
   wordings); the post-result beat is `lane.py:1024`'s unconditional
   `response.create` after every brokered tool answer.

## Defect 1 — reconnect must repay what was owed

When `_reconnect` (or `_rollover`) replaces a session while
`_responses_pending > 0`, the new session contains the owner's turn already —
the ledger wrote it and `_inject_tail` replays it — but nobody asks the new
session to ANSWER. Fix: after a successful reconnect's tail injection, if
responses were owed on the dead session, issue `response.create` (once) so the
first thing the new session does is answer the question it inherited.
Requirements:
* Bounded: ONE repay per reconnect; a repay that itself stalls is the next
  watchdog cycle's problem, not a loop.
* Counted: `turn_repays` in the snapshot, plus a ledger/system note so the
  transcript shows why an answer arrived after a reconnect.
* Never a double answer: a response that actually completed
  (`_on_response_done` decremented pending) owes nothing.
* Works for both `stall` and `rollover` paths.

## Defect 2 — one beat per tool turn, without lying by silence

Replace the unconditional post-tool `response.create` with:
* **Success path** (`status: ok` AND the model already spoke text in the same
  response that carried the `function_call`): send the
  `function_call_output` but do NOT request a response — the model's own
  announcement stands as the turn's single beat. The mission/terminal
  narration channel (`narrate_event`) is unaffected and still reports what
  happens later.
* **Every other path** (failure, refusal, deferral, `status != ok`, or the
  model emitted the call silently with no text): request the response — the
  truthful-narration channel is the reason this beat exists and it must
  survive. If the API supports per-response `instructions`, use them to ask
  for one short result-only sentence; `protocol.py` is OPENED narrowly for an
  optional additive `instructions` field on `ResponseCreate` if needed
  (precedent: R1.6's `session.type`).
* `_responses_pending` accounting must stay exactly consistent with what was
  actually sent — the R4L watchdog and Defect 1's repay logic both read it.

## OWNS / MUST NOT TOUCH

OWNS: `src/parcel_robot/realtime/lane.py`, `protocol.py` (ONLY an additive
optional `ResponseCreate.instructions` field, if used), tests (extend
`test_realtime_reconnect.py` / `test_realtime_lane.py`, new file fine),
`scrum/20260818/task_3/R6_STATUS.md`.
MUST NOT TOUCH: `runtime.py`, `tool_broker.py`, `prompting.py` (SI v2 stays
as shipped), `ingress.py`, `transport.py`, `ws_transport.py`, `config.py`,
`fake_server.py` (extend via new script steps only if its existing seam
allows without changing existing behavior — otherwise build scripts in
tests), `agent.py`, `web_panel.py`, `ui/index.html`, `configs/**`, `evals/**`,
yield/person-stop policy. The owner's stack may be live on :8765 — read-only
probes at most; live proof on your OWN port with the R5 scratch-config recipe
(copy `configs/robot.yaml` to scratch with `memory.path` pointed at a scratch
sqlite; never touch the owner's `parcel_memory.sqlite3`). Never
commit/stage/stash.

## Definition of done

Full `ci_gate --tier commit` green; ≥8 seeds RED/restored, including at
least: the swallowed turn restored (reconnect stops repaying), repay
unbounded (loops), repay double-answers a completed response, success-path
tool turn requests a response again (two beats return), failure-path tool
turn goes silent (the dangerous over-correction), pending-accounting drifts
from what was sent. ONE live proof on your own stack: (a) force a stall
mid-turn (drop the transport under a live session) and show the turn is
ANSWERED after the reconnect with zero owner action; (b) a navigation turn
produces ONE spoken beat; (c) a deferred/refused tool call still gets
narrated. If (b) still shows the provider misbehaving, report it honestly
with transcripts — R5 set that standard. Spend target well under $1 on
`gpt-realtime-2.1-mini`. R6_STATUS.md carries the standard register.
