# AUDIT — R1.5 live WebSocket transport · Fable

**Date:** 2026-08-17 · **Card:** task_1 R1.5 · **Executor:** Claude Opus (agent)
**Verdict:** **ACCEPT with one BLOCKING defect found and fixed by the auditor.**
The defect is the reason this audit exists; details below.

## The headline

**Parcel held its first live conversation with OpenAI Realtime.** After a third
API key with actual credit arrived, `tests/test_realtime_live.py` — written
expecting to fail — passes:

```
$ PARCEL_REALTIME_LIVE=1 pytest tests/test_realtime_live.py -m slow
1 passed
```

Socket opens, authenticates, session runs, response arrives with billed usage,
both sides land in the ledger, zero protocol refusals. Two defects stood
between the first attempt and that pass; both are recorded below because both
were invisible to a green suite.

## BLOCKING defect 1 — the codec refused real traffic (predicted, found, fixed)

First live run reached the provider and then refused **10 frames across 8
types**: `conversation.item.added/done`, `response.created`,
`response.output_item.added/done`, `response.content_part.added/done`,
`rate_limits.updated`. R1's codec was written from documentation.

This is the fail-closed design working exactly as intended — the refusal was
loud, immediate, and in the record, not a silent degradation three turns later.
R1's own status doc predicted it verbatim.

**Fix:** captured the real stream from a live session
(`scratchpad/live_stream.json`: 14 event types, full lifecycle, 155 tokens),
added a `LifecycleEvent` no-op class registered for exactly the observed types,
each annotated with why it is ignorable. **The fail-closed rule is intact** —
an unrecognized type still raises `UnknownEventType`, pinned by an existing
test. The surface pin was split into consumed-vs-ignored with an assertion that
no event can be both.

## BLOCKING defect 2 — `receive()` did the opposite of its own docstring

`ws_transport.receive()` documented "Drain first, then report the hang-up …
so a mid-turn disconnect still delivers the turn" and then opened with
`if self._down is not None: raise`. **Every buffered frame was discarded the
moment the reader thread recorded a hang-up.** A server that emits three frames
and disconnects delivered none of them.

**Why 24/24 passed twice, for me and for the executor:** `_down` is set
*asynchronously* by the reader thread, so whether a frame or the close won the
race depended on machine load. It surfaced only when a concurrent R1.6 build
loaded the machine and flipped the race. The tests were timing-dependent and
did not pin the property they claimed to pin — which also means the
executor's "drain-then-raise ordering" seed result was unreliable.

**Fix:** removed the early raise (the correct post-drain check was already
there, dead behind it). Now 24/24 across three consecutive runs and stable in
combined-suite runs where it previously failed 7-8 tests.

**Lesson for the register:** a green suite over a racy property proves nothing.
Any test that depends on a background thread setting state must force the
ordering, not hope for it.

## Verified independently

- **Fresh full gate after both fixes: PASS** — 5,779 passed, ruff `new 0`,
  release-parity and frozen sentinels green.
- **Live test passes** (above); protocol refusals empty on real traffic.
- All five realtime suites green together (213 → 214 passing).
- `configs/robot.yaml`, `pyproject.toml`, `ci_gate.py`, `lane.py`, `ingress.py`:
  untouched. `requirements-lock.txt` correctly pins `websockets==17.0.1`.

## Executor's declared deviation — RULING

`RealtimeQuotaError`/`RealtimeAuthError` subclass `RealtimeTransportError`
(a `RuntimeError`) and deliberately **not** `TransportClosed`. **ACCEPT.** The
reasoning is right and now demonstrated: making a billing wall look like a
disconnect would drive `pump()` into one full reconnect per call, forever,
mislabelled. The distinction between "the peer hung up" and "the account cannot
pay" is real and belongs in the type system.

## Standing risks

- The live proof is **one text-shaped turn on `gpt-realtime-2.1-mini`**. No
  audio has played (no speaker on this host), no microphone exists, no
  barge-in, no tool call, no rollover has been exercised against the real
  server.
- Reconnect still has **no backoff** — inherited from R1, now reachable over a
  real socket. A flapping provider would hot-loop. This should be the next
  card's first item.
- The corpus scrape (R2-C, 25 threads) is now **unblocked** and has not run.
