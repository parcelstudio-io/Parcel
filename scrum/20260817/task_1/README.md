# Task 1 — Realtime R1.5: live WebSocket transport

**Date:** 2026-08-17 · **Executor:** Claude Opus (agent) · **Auditor:** Fable
**Depends on:** R1 (`scrum/20260816/task_7`, ACCEPT_CLOSE) — the `Transport`
seam, typed protocol, `FakeRealtimeServer`, and `RealtimeLane` all exist and are
audited. R1.5 is a NEW IMPLEMENTATION OF THAT PROTOCOL, not an edit to the lane.

## Environment facts established 2026-08-17 (do not re-derive)

- `websockets==17.0.1` is installed in `.parcel`; `websockets.sync.client.connect`
  works. Add it to `requirements-lock.txt` only if that file already pins
  optional extras — check first; do NOT touch `pyproject.toml`.
- Credentials live at `~/.config/parcel/realtime.env` (mode 600, OUTSIDE the
  repo). Load with `set -a; . ~/.config/parcel/realtime.env; set +a`.
  **Never hardcode, echo, log, or commit the key. Never write it into the repo.**
- **Verified working:** URL `wss://api.openai.com/v1/realtime?model=<model>`,
  header `Authorization: Bearer $OPENAI_API_KEY`, no beta header needed. The
  socket OPENS and AUTHENTICATES.
- **Verified blocker:** the account has no billing quota. The first server frame
  is `error{type: insufficient_quota}` and the socket closes 1013. `GET /v1/models`
  (200, 122 models incl. `gpt-realtime-2.1` and `gpt-realtime-2.1-mini`) and
  `POST /v1/realtime/client_secrets` (200) both succeed — permissions are fine,
  credit is not. **This is an owner billing action; do not chase it as a bug.**

## Objective

Land `WebSocketTransport` so that the moment billing is added, the lane talks —
with the quota failure surfaced as a first-class, testable outcome rather than a
crash.

## Scope — OWNS

- `src/parcel_robot/realtime/ws_transport.py` (NEW). `transport.py` is R1's
  audited surface: import from it, do not edit it.
  - Implements the `Transport` Protocol exactly: `send`, non-blocking
    `receive() -> Mapping | None`, `close`, `closed`.
  - A reader thread drains the socket into a bounded deque so `receive()` never
    blocks (the lane's whole design assumes this). Bound it and drop-with-count
    on overflow rather than growing without limit.
  - Credential by REFERENCE: takes an env var NAME (default `OPENAI_API_KEY`),
    reads it at connect time, and must never place the value in an exception
    message, `repr`, or log line. Add a test that asserts the key value appears
    in no string the class produces.
  - Connect failures and server-side `error` frames become typed outcomes:
    at minimum `RealtimeAuthError`, `RealtimeQuotaError` (insufficient_quota —
    the state this account is in today), `TransportClosed` for a normal hang-up.
    Close code 1013 with an `insufficient_quota` error frame must raise
    `RealtimeQuotaError`, not a bare `ConnectionClosedError`.
  - Reconnect is the LANE's job (it already has watchdog + tail reinjection).
    The transport reports; it does not retry silently.
- `tests/test_realtime_ws_transport.py` (NEW): offline only. Drive the class
  against a local `websockets.sync.server` echo/scripted server on 127.0.0.1 —
  this exercises real framing, real threading, real close codes with no
  network and no credentials. Cover: send/receive round-trip, non-blocking
  receive returns None when idle, backlog drain-then-raise ordering (match
  `InProcessTransport`'s documented semantics), close idempotence, overflow
  drop-count, a scripted `error{insufficient_quota}` + 1013 close raising
  `RealtimeQuotaError`, a 401-shaped rejection raising `RealtimeAuthError`,
  and the key-never-leaks test.
- `tests/test_realtime_live.py` (NEW): the live lane, `pytest.mark.slow` AND
  skip-gated on `PARCEL_REALTIME_LIVE=1` plus a present key — so it never runs
  in the commit tier and never needs credentials in CI. One test: open a
  session against `gpt-realtime-2.1-mini` with `output_modalities: ["text"]`
  (cheapest possible), send one user item, assert a reply arrives and the
  ledger holds both sides. **Expected to fail today with `RealtimeQuotaError`;
  write it so that failure is legible, and record in the status doc that it has
  never passed.**
- `scrum/20260817/task_1/R1_5_STATUS.md` — the register: frozen contract
  surface, gate table, seeded-failure table (≥4 seeds), OWNS compliance with
  numstat, does_not_prove, handoffs.

## MUST NOT TOUCH

`configs/robot.yaml` (hash-locked), `pyproject.toml`, `scripts/ci_gate.py`,
`evals/**`, `tools/`, `src/parcel_robot/realtime/transport.py`,
`lane.py`/`protocol.py`/`ingress.py` (R1, audited — if you believe one needs a
change, STOP and report it instead), anything another session has uncommitted
(re-run `git status` first). Never commit, stage, or stash.

## Definition of done

`ci_gate --tier commit` fully green (ruff `new 0`; the live test must be
DESELECTED or skipped, never red-by-skip in a way that hides it); seeds RED then
restored; status doc complete and honest that no conversation has occurred.
