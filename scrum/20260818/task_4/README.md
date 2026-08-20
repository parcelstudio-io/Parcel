# Task 4 — R7: ears and mouth — the browser audio gateway (§A, carried since R1.6)

**Date:** 2026-08-18 · **Executor:** Claude Opus (agent) · **Auditor:** Fable
**Trigger:** owner directive "implement both"; §A is the only gap between the
owner and SPEAKING to the dog. Carried from `20260817/task_6` (its §A clause),
where `mode: audio` was left failing loudly at construction.

## Goal

`mode: audio` in the owner's realtime config produces a working spoken
conversation through the browser: microphone PCM up (browser → panel gateway →
`lane.send_audio`), hosted audio down (lane → `browser_sink` → panel gateway →
browser playback). Everything else — ingress, broker, admission, SI/DI,
ledger — is the SAME pipeline text mode already proved; this card builds the
audio transport ends and wires the construction path, nothing else.

## Constraints and design guardrails

1. **This host has NO audio hardware and NO human in the loop.** The live
   proof is synthetic-but-real: synthesize a spoken sentence with the local
   piper TTS (`models/piper/voice.onnx` — the runtime already uses it),
   resample to the wire format the session negotiates, pump it through the
   REAL gateway path from a headless client, and prove: the provider
   transcribes it, a spoken "go to the sidewalk" yields a `navigate_to`
   proposal through the same broker/admission chain, audio deltas come back
   and reach the sink, and both sides land in the ledger. A human-witnessed
   spoken session is explicitly owner-gated and stays in does_not_prove.
2. **Gateway transport:** the panel server is loopback-only stdlib
   `http.server`; the `websockets` library is installed. Executor's choice of
   WS vs chunked-HTTP, but: loopback-only, handshake bound to the panel CSRF
   token (arming gesture = the owner clicking the mic affordance — fail-closed
   like everything else), bounded buffers with a drop-and-count policy (never
   unbounded growth), and clean teardown when either end hangs up.
3. **Sink ownership is already law** (`assert_sink_free`, R1.5): the gateway
   claims the speaker through the existing bridge; the pre-existing
   `DuplexVoiceSession output is live` pump assertion (R4L open risk 6) is the
   known hazard here — if it fires, diagnose it as part of this card rather
   than working around it.
4. **Barge-in, minimal honest version:** on provider `SpeechStarted` the lane
   already reacts; the gateway must additionally tell the browser to stop
   local playback (a control frame), and mic frames keep flowing during
   playback. Full mark/truncate integrity stays future work — say so.
5. **Emergency latch stays transcript-side** (ingress, unchanged): a spoken
   "stop" latches when its transcript arrives. The always-local wake-word/
   e-stop (the ChatGPT-rec constraint) is NOT this card; name it owner-gated.
6. **Construction:** `mode: audio` stops failing at construction and instead
   constructs the lane with the gateway armed-but-idle; the mic only opens on
   the owner's explicit browser gesture per session. Text mode must remain
   byte-identically unaffected — every existing test stays green untouched.

## OWNS / MUST NOT TOUCH

OWNS: `src/parcel_robot/realtime/browser_sink.py`, `driver.py`,
`src/parcel_robot/web_panel.py` (gateway endpoints), `src/parcel_robot/ui/
index.html` (mic capture, playback, affordance — do NOT disturb the fresh
renderLogs dedupe, clearMotionInputs gating, or toggle-label work),
`runtime.py` (realtime construction block + gateway wiring ONLY), tests (new
gateway suites; extend driver/panel suites), `scrum/20260818/task_4/
R7_STATUS.md`.
MUST NOT TOUCH: `lane.py` and `protocol.py` (R6 just landed there — if the
lane's audio seam is genuinely insufficient, STOP and report the gap in the
status doc instead of editing), `ingress.py`, `tool_broker.py`,
`prompting.py`, `config.py` (mode:audio already parses), `conversation_store.
py`, `memory.py`, `agent.py`, `configs/**`, `evals/**`, yield/person-stop
policy. Owner's stack may be live on :8765 — read-only probes at most; your
own stack on your own port/socket; R5 scratch-config recipe for memory
isolation (never touch the owner's `parcel_memory.sqlite3`). Never
commit/stage/stash.

## Definition of done

Full `ci_gate --tier commit` green (CI has no audio hardware and no key —
everything fake-first; the gateway gets real-client tests against a
FakeRealtimeServer-backed lane). ≥8 seeds RED/restored, including at least:
gateway accepts frames without the arming gesture (fail-closed broken),
unbounded buffer restored, sink claimed without ownership, barge-in stop
frame dropped, mode:audio regresses to refusing construction, text mode
disturbed. ONE live audio proof as in constraint 1, with transcript, ledger
rows, sink capture evidence, and costs (audio tokens are pricier — target
under $2 on `gpt-realtime-2.1-mini`). R7_STATUS.md carries the standard
register including an explicit does_not_prove: no human has spoken to it or
heard it; barge-in mark integrity unproven; wake-word/e-stop locality
owner-gated.
