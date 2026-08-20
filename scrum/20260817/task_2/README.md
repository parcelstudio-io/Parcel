# Sprint 2026-08-17 task 2 — day plan: first live conversation

**Convention:** Opus executes, Fable audits between waves. Nothing committed
until the wave is audited. Baseline `8473a51` + the uncommitted 08-16 wave.
**External validation:** an independent ChatGPT recommendation (2026-08-17,
owner-supplied) reaches the same architecture Parcel already built — Realtime
over WebSocket for a server-side Python process, tool calls as locally
validated proposals, no cloud velocities, always-local stop. Differences are
deliberate and noted in W-notes below.

## The one blocker only the owner can clear

**W0 — billing.** The OpenAI account has zero quota (verified 2026-08-17:
`/v1/models` 200, `/v1/realtime/client_secrets` 200, chat 429
`insufficient_quota`, Realtime socket closes 1013 after authenticating). Add a
payment method / credits. Until then W3 floats; everything else proceeds.
Recommended while in the console: **rotate the key** (it transited a chat
session) and drop the replacement into `~/.config/parcel/realtime.env`.

## Waves

| ID | Work | Owner | Depends | Exit |
| --- | --- | --- | --- | --- |
| W1 | Finish R1.5: run the full commit gate, paste into `R1_5_STATUS.md`, final `git status` — code + seeds already landed (8/8 RED recorded; S6 was green once, fixed, now RED) | Opus (resume) | — | gate green, status doc complete |
| A1 | Fable audit of R1.5: fresh gate, OWNS/numstat, independent seed re-runs, key-never-leaks test verified, drain-then-raise parity vs `InProcessTransport` | Fable | W1 | ACCEPT/REWORK ruling |
| W2 | **R1.6 "Ears and Mouth" — the browser audio path.** PortAudio is not loadable on this host, so the browser is mic AND speaker; `SpeakerSink` cannot play here. Build: `realtime/audio_gateway.py` (loopback `websockets` listener, CSRF-token handshake, single client) carrying mic PCM16 → `lane.send_audio()` and lane audio → browser playback; a `BrowserSink` implementing the sink contract the lane already takes (`enqueue`/`begin_utterance`/`interrupt`) with **playback marks reported by the browser** driving truncate-to-heard (the local sink clock does not exist on this host); panel mic button (the arming user-gesture) + getUserMedia + AudioWorklet capture/playback at 24 kHz PCM16; runtime passes the sink/gateway when the lane is enabled. Offline tests: a fake browser client against the real local listener proves the full audio round trip. Seeds: unarmed connection refused; CSRF mismatch closes; browser disconnect stops audio without killing the session; marks drive truncate. | Opus | — (parallel with W1) | offline round-trip proven, gate green |
| A2 | Fable audit of R1.6 — adversarial focus: arming gesture actually gates, marks cannot be spoofed into the ledger by a stale client, sink ownership rules hold | Fable | W2 | ruling |
| W3 | **First live contact.** Step 1 (cheap): `PARCEL_REALTIME_LIVE=1` text-only live test on `gpt-realtime-2.1-mini` — first ever pass expected only after W0. Step 2: browser conversation via W2 — the actual first talk. Evidence pack in `scrum/20260817/`: per-stage latency, cost rows from `response.done` usage, ledger rows for both sides, one barge-in attempt, one punctuated "Stop." | Opus exec, Fable witnesses | W0+A1 (step 1), +A2 (step 2) | recorded session evidence |
| W4 | R2 remainder, only if the day allows: summarize-and-restart wired to a real ledger marker; distilled-profile injection; `/api/state` realtime block (arming/session/cost) | Opus | A1 | deferred without guilt |

## W-notes — mapping the external recommendation onto Parcel

- "WebSocket for a Python process on the robot" → is R1.5. The Base64 audio
  chunk handling it warns about is already in `protocol.py`.
- "Model returns start_following(); validator checks; nav begins; model says
  okay" → is exactly the R1 ingress + R3 tool-broker design, with the audit's
  carry-forward that R3 must route through `SafetySupervisor.validate`.
- "Never let the cloud send velocities" → `MODEL_FORBIDDEN_TOOLS` + admission
  chain; structural since R1 (`submit_voice_text` refuses realtime origin).
- "Short-lived session credentials for production" → `/v1/realtime/client_secrets`
  verified working (200) — the production path exists when needed; prototype
  uses the on-box env file, as recommended.
- "Always local: wake word, e-stop, collision, low-level control" → e-stop,
  collision, and motion are local and untouched. Parcel deliberately has **no
  wake word**: fail-closed mic arming with an explicit user gesture instead
  (FIX-A lineage); an always-listening wake word is a B18 owner decision.
- "ROS 2 tool-call bridge" → no ROS 2 on this host by design; the admission
  chain is that bridge. ROS 2 sidecars arrive per the HLD, not per this lane.
- "Consider WebRTC when jitter matters" → agreed and priced: a WebRTC capture
  edge would be a new `Transport`/gateway implementation behind the same seams
  (assessed 2026-08-17: the lane touches the network at 4 call sites and audio
  at 2); playout stays in the runtime to keep the truncate/gesture clock.
