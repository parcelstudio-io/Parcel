# Task 4 — R1.6 "Ears and Mouth": the browser audio path

**Date:** 2026-08-17 · **Executor:** Claude Opus (agent) · **Auditor:** Fable
**Board ref:** W2 on `scrum/20260817/task_2/README.md`.
**Depends on:** R1 (audited), R1.5 (landed, audit pending), R2-C (audited).

## Why this card exists

PortAudio does not load on this host, so `SpeakerSink` cannot play and there is
no microphone. The browser panel must be BOTH mic and speaker, or no live
conversation can ever happen on this machine. This card builds that path,
entirely offline-testable; the live session stays gated on billing (still 429
`credit_balance_exhausted` at card-cut time).

## Scope — OWNS

- `src/parcel_robot/realtime/audio_gateway.py` (NEW): a loopback-only
  `websockets.sync.server` listener owned by the runtime process.
  - Handshake: first client frame must carry the panel's per-process CSRF
    token + an explicit `mic_gesture: true` field (the arming user gesture).
    Wrong/missing token or gesture ⇒ close immediately with a coded reason.
    Single client; a second connection refuses (no silent takeover).
  - Inbound: binary frames = owner mic PCM16 @ 24 kHz → `lane.send_audio()`.
  - Outbound: binary frames = robot speech (WAV chunks as produced by the
    lane's playback bridge) for browser playback; JSON control frames for
    `begin_utterance` / `interrupt` / mark requests.
  - Playback marks: the browser acks each chunk with played-ms; the gateway
    exposes a monotonic played-clock the lane's truncate-to-heard consumes.
    Marks must be monotonic and bounded by bytes actually sent — a stale or
    inflated ack is CLAMPED and counted, never trusted (audit will attack
    this: a spoofed mark must not be able to shrink or grow the ledger's
    truncate point beyond what was actually transmitted).
- `src/parcel_robot/realtime/browser_sink.py` (NEW): implements the sink
  contract the lane already takes (`enqueue`/`begin_utterance`/`interrupt`,
  plus the played-clock read) by forwarding to the gateway. No `lane.py` edit:
  the lane accepts a sink object today.
- `src/parcel_robot/ui/` — panel page addition: mic button (arming gesture),
  `getUserMedia` capture, AudioWorklet capture+playback at 24 kHz PCM16,
  WebSocket client with the CSRF token, played-ms acks. Keep it dependency-free
  vanilla JS in the existing page style. NOTE: `ui/index.html` is a tracked,
  committed file — edits are in-scope but keep the diff tight and additive.
- Runtime wiring (minimal): construct gateway + `BrowserSink` and pass as the
  lane's sink when the lane is enabled; expose gateway/arming state in the
  existing snapshot surface. Only the existing R1/R2-C realtime construction
  block may grow.
- `tests/test_realtime_audio_gateway.py` (NEW): offline, real `websockets`
  client against the real listener on 127.0.0.1 (no mocks of the ws library):
  handshake refusals (no token / wrong token / no gesture / second client),
  full audio round trip (fake browser client: send PCM in, receive WAV out,
  ack marks), mark clamping (inflated ack clamped to bytes-sent; regressing
  ack refused), disconnect mid-response (lane keeps session, audio pauses,
  reconnect re-handshakes with a fresh gesture), truncate driven by acked
  marks end-to-end through the lane (fixture-driven via FakeRealtimeServer).
- `scrum/20260817/task_4/R1_6_STATUS.md` — full register.

## MUST NOT TOUCH

`configs/robot.yaml`, `pyproject.toml`, `scripts/ci_gate.py`, `evals/**`
except nothing, `tools/`, `realtime/{lane,transport,ws_transport,protocol,
ingress,fake_server,config,prompting}.py` (all audited or pending audit —
read-only; if a lane change seems required, STOP and report), `web_panel.py`
HTTP handler internals beyond serving the token to the page (it already does),
other sessions' uncommitted files. Never commit/stage/stash.

## Seeded failures (minimum 6)

| # | Defect | Expected RED |
| --- | --- | --- |
| S1 | handshake accepts a missing CSRF token | refusal test |
| S2 | mic_gesture not required | arming test |
| S3 | second client silently replaces the first | single-client test |
| S4 | inflated played-ms ack trusted | mark-clamp test |
| S5 | disconnect kills the provider session | disconnect test |
| S6 | marks not monotonic (regression accepted) | mark-order test |

## Definition of done

Full `ci_gate --tier commit` green; seeds RED then restored; status doc honest
that no human has spoken through this path (no mic hardware, no credit) — the
"live" proof remains W3. Handoff: the exact one-command procedure to run the
first conversation once credit lands.
