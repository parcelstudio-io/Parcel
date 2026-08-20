# R7 — ears and mouth: the browser audio gateway (§A) — EXECUTOR STATUS

**Date:** 2026-08-18/19 · **Executor:** Claude Opus (agent) · **Auditor:** Fable
**Card:** `scrum/20260818/task_4/README.md`

## Verdict in one paragraph

`mode: audio` works. The owner's browser is now the robot's ears and mouth: a
loopback WebSocket on the panel's own port and origin carries microphone PCM up
into `lane.send_audio` and hosted speech down through `BrowserSink`, and the
whole pipeline behind it — ingress, broker, admission, SI/DI, ledger — is the
one text mode already proved. Proven live end to end on my own stack (`:8822`,
socket `/tmp/parcel_r7.sock`, `gpt-realtime-2.1-mini`) with piper-synthesized
speech: the provider transcribed it, `navigate_to` went through the normal
broker/admission chain, 45 WAV chunks of hosted audio came back and reached the
headless client (215 across all four sessions), and both sides landed in the
ledger. Total spend **$0.102282**.
Twenty-one seeds RED, all files restored byte-identically. **R4L open risk 6 is
diagnosed and fixed** — the `DuplexVoiceSession output is live` pump failure was
a false positive, and the live audio sessions ran with `driver.failures == []`.
**Two things did NOT go the way the card hoped and are reported as such**: the
spoken emergency latch never fired in three live attempts, and barge-in
truncated at 0 ms because the headless client sends no playback acks.

## The gate — FULLY GREEN, verbatim

Run after the final edit:

```
CI GATE — tier=commit  (2026-08-19T03:17:38Z)
==============================================================================
[  PASS] HARD  ruff                       7 violation(s), baseline 7, new 0
[  PASS] HARD  hard-safety                nav frozen baseline nav-instruct-v1-baseline-v4-20260811T070536Z: collisions=0 false_arrival=0 | mutation panel clean: collisions=0 no_false_arrival=True | mutation panel freshness: committed fields reproduce live = True | follow-bench: 7 row(s), hard_collision_total all 0 = True | walk_with_me: 1/2 row(s) with hard_collision_total, all 0 = True
[  PASS] HARD  frozen-digest-sentinels    4 immutable manifest(s) byte-identical to pin
[  PASS] HARD  release-parity             91 packaged asset(s) byte-identical to canonical source
[  PASS] HARD  latency-tail-ledger        latest row latency-20260810T082415Z-4d83035f: 6 metric series within 1.2x tail ceiling (rows=5, window=5)
[  PASS] HARD  follow-bench-jerk-ratchet  latest shipped row follow-bench-v1-20260811023618Z-93eba090.json: 1.2187 <= 1.46244 (baseline 1.2187 x 1.2)
[  PASS] HARD  model-off-non-inferiority  23 passed in 0.45s
[  PASS] HARD  frozen-digest-integrity    6 passed, 1 warning in 0.32s
[  PASS] HARD  release-parity-integrity   10 passed in 0.73s
[  PASS] HARD  mutation-panel-freshness   2 passed, 3 warnings in 4.23s
[  PASS] HARD  latency-tail               6 passed, 2 warnings in 0.30s
[  PASS] HARD  default-suite              6242 passed, 9 skipped, 42 deselected, 5 warnings in 242.44s (0:04:02)
==============================================================================
RESULT: PASS — every hard gate green.
  elapsed 254.9s
```

## What changed, by file

### `src/parcel_robot/realtime/audio_gateway.py` — NEW (940 lines)

The module `runtime._build_realtime_sink` has been importing-and-failing on
since R1.6. It is deliberately **not** a transport: it is policy, buffers and
counters that a test can drive with no socket at all, plus one `serve_websocket`
function that runs a real socket to completion.

* `BrowserAudioGateway` satisfies `browser_sink.PlaybackGateway` exactly
  (`begin_utterance` / `send_audio` / `interrupt` / `played_started_monotonic`)
  and owns the inbound half through `accept_audio` / `set_mic` /
  `handle_control`. Constructor takes `on_audio`, `on_mic`, `on_event`, an
  injected `clock`, and all three bounds.
* **Fail-closed handshake** (`authorize`, L303): no bound token ⇒ every
  connection refused; wrong token ⇒ refused, `hmac.compare_digest`. Both counted
  in `connections_refused`.
* **Connected is not listening** (`attach` L319, `accept_audio` L396): attaching
  gets a mouth only. Inbound audio is refused and counted
  (`frames_refused_unarmed`) until `{"type":"mic","on":true}` arrives, and the
  browser is told once rather than silently ignored. `set_mic` asks the runtime
  first (`on_mic`); a refusal keeps the microphone shut and reports the reason
  verbatim.
* **Bounded both ways.** Outbound: `_Connection.push` (L155) evicts OLDEST on
  either a frame bound (256) or a byte bound (8 MiB) and returns the drop count,
  which the gateway adds to `frames_dropped_backpressure`. Inbound: **no queue
  at all** — `accept_audio` calls the lane on the socket reader's own thread, so
  a busy lane backpressures TCP — plus a 32 KiB per-frame cap
  (`frames_oversize`). A second, larger bound (`DEFAULT_MAX_SOCKET_FRAME_BYTES`,
  1 MiB) is the codec's allocation bound, so "your capture buffer is too big"
  and "you are attacking me" stay different events.
* **The played clock is clamped here** (`ack_played`, L586), because this module
  owns bytes-sent and the lane hands that number to the provider as "what the
  owner heard". Three clamps: an ack for anything but the current utterance is
  dropped (`stale_acks`); the reported position is clamped to the audio actually
  handed to the socket; the derived anchor is never earlier than the moment the
  first byte of this utterance left.
* **`send_audio` never raises** (L527). It runs inside `lane.pump()`; an
  exception there is `pump failed` and takes the conversation down because a tab
  closed. A hosted reply with nobody listening is `frames_dropped_no_client`.
* **Barge-in** (`interrupt`): discards the queue and pushes
  `{"type":"stop","utterance":N}`. Inbound is never gated on playback state.
  The discarded frames go to their OWN counter, `frames_discarded_interrupt`,
  and deliberately not into `frames_dropped_backpressure`: the latter means
  "the browser stopped reading", which is a defect, and the former means "the
  owner interrupted", which is the product working. One number for both would
  make a panel with a stalled socket look exactly like a chatty owner. It counts
  playback frames only — the pending `utterance` marker is dropped with them but
  not counted, so "four chunks were cut off" does not read as five.
* `serve_websocket` (L711) drives `websockets`' Sans-I/O `ServerProtocol` over
  the panel's raw socket: caller thread reads, one writer thread drains the
  outbound queue, one lock covers "advance the protocol and put its bytes on the
  wire". `_Reassembler` (L855) turns frames into whole messages with its own
  bound, because Sans-I/O `max_size` bounds a FRAME and ten thousand one-byte
  continuations are a message.

Two bugs found and fixed while building it, both now seeded:

1. **The socket was stone deaf.** `ServerProtocol`'s parser is a generator that
   starts life suspended inside `Request.parse`. Calling `accept()` on an
   already-parsed request leaves it parked there, and the first websocket frame
   the browser sends is swallowed by an HTTP parser that will never finish — a
   socket that handshakes perfectly, plays audio perfectly, and hears nothing.
   Fixed by re-serializing the request into `receive_data` first (L767). Seed
   S11.
2. **TEXT frames were being fed to the microphone.** `Frame.data` is `bytes` for
   TEXT as well as BINARY, so a first cut keyed on `isinstance(data, str)`
   appended every JSON control frame to the input audio buffer. The opcode is
   the only thing that tells them apart (`_dispatch`, L898). Seed S10.

### `src/parcel_robot/web_panel.py` — the endpoint

* `REALTIME_AUDIO_PATH = "/api/realtime/audio"` (L39), routed in `do_GET` (L254).
* `_serve_realtime_audio` (L459): loopback `_valid_host`, then a **mandatory**
  same-origin check, then hand-off. The origin check is mandatory here in a way
  it is not for POST — a WebSocket handshake is exempt from CORS, so any page on
  the machine could otherwise open this socket. A runtime with no gateway
  answers **404** (the endpoint does not exist rather than existing and idling);
  a plain GET answers **426**.
* The panel token rides as a second offered subprotocol (`parcel-csrf.<token>`),
  never a query parameter: `BaseHTTPRequestHandler.log_message` prints the
  request line, and a token in the URL is a token in the terminal scrollback.
* `_same_origin` (L525) was factored out of `_authorize_post`, which now calls
  it — same logic, one definition, no behaviour change.
* `websockets` is imported lazily inside the handler: it is an optional
  dependency and a build without it must still serve the whole panel.

### `src/parcel_robot/runtime.py` — construction and gateway wiring only

* `_build_realtime_sink` (L4833) no longer raises for `mode: audio`. It builds
  the gateway **armed but idle** — no paid session, no driver thread, no audio
  hardware — and wires `on_mic` and `on_event`. The loud `ImportError` arm is
  kept and is still reachable for a build without `websockets`.
* `_realtime_mic_gesture` (L4899): the owner's browser gesture is what opens the
  hosted session in audio mode, exactly as typing into the live box opens it in
  text mode (`ensure_session(handshake_token=..., mic_gesture=True)`, then start
  the driver). Nothing succeeds quietly — a refusal propagates back through the
  gateway and the browser is told. Closing the microphone deliberately does NOT
  close the session: the session is the conversation, and hanging up on a
  released button throws away the context the next sentence needs.
* `duplex_output_active=self._realtime_shares_local_speaker` (L1333, method at
  L4876) — see the next section.

### `src/parcel_robot/ui/index.html` — the browser half (L2032–2261)

`getUserMedia` → `AudioContext` → `ScriptProcessorNode` (2048 frames) →
linear-interpolating resample to the rate the gateway's hello frame names →
Int16LE → `ws.send`. Playback parses each WAV chunk by hand (rate from the RIFF
header) and schedules it on a second `AudioContext` in arrival order, acking the
played position from the audio clock. `stop` frames call `stopPlayback`; the
capture callback is never gated on playback state, which is what makes barge-in
possible at all. The mic affordance existed since R1.6 and did nothing; it is
now wired. **The fresh `renderLogs` dedupe, `clearMotionInputs` gating and
toggle-label work were not touched** — all additions are appended after the
`[data-command]` wiring, and seed S21 proves R5's typed-turn path still reddens
if disturbed.

### `tests/` — one new suite, one replaced test

* `tests/test_realtime_audio_gateway.py` — NEW, 886 lines, 40 tests. Every
  socket is a REAL websocket to a REAL `RuntimeHTTPServer`; the only fakes are
  the provider (`FakeRealtimeServer`) and the robot backend. Sections A–H:
  handshake, arming, bounds, played-clock clamping, barge-in, the real socket,
  the browser source, and one whole-pipe test that drives mic PCM up through a
  real runtime to a fake provider and asserts audio down, ledger rows and
  counters.
* `tests/test_realtime_driver.py::test_audio_mode_fails_loudly_rather_than_downgrading_to_text`
  — **replaced, not deleted.** It pinned "R1.6 §A is not in this build", which
  is the exact clause this card closes. It now pins the arm still worth pinning:
  a build without the optional `websockets` dependency parses `mode: audio`
  happily and must refuse at construction rather than hand the operator a text
  box. Rewritten with a `builtins.__import__` monkeypatch. This is a **card
  deviation** (see below).

## R4L open risk 6 — diagnosed and fixed

The three `pump failed: … DuplexVoiceSession output is live` lines in R4-lite's
live session 1 were a **false positive**, and the diagnosis is one sentence:

> `assert_sink_free` exists because two writers to ONE ordered PortAudio queue
> interleave. The lane's sink is never that queue.

`_build_realtime_sink` returns a `DiscardSink` (text) or a `BrowserSink` (audio)
and deliberately never a local `SpeakerSink`; the lane's audio goes to /dev/null
or to the browser while local speech goes to PortAudio. Reporting the local
duplex session's state unconditionally therefore raised `SinkOwnershipError` out
of `_on_audio` into `pump()` whenever the robot happened to be speaking locally
— in TEXT mode, where there is no contention at all. In audio mode the same
false positive would have dropped hosted speech mid-utterance.

**`lane.py` was not edited.** The fix is at the injection point, which is mine:
`duplex_output_active` now evaluates the law instead of assuming it. It is
fail-closed in the direction the law points — anything this method does not
RECOGNISE as a non-speaker sink falls through to the pre-R7 behaviour, so a new
sink has to be added deliberately rather than inheriting a free pass. Both
directions are pinned by one test and two seeds (S15 restores the false
positive; S16 claims the sink without ownership).

Live confirmation: across four live audio sessions and 4 695 driver steps,
`driver.failures == []`.

## Seed table — 21/21 RED, all restored byte-identically

Harness: `<scratchpad>/seeds_r7.py` (FIX-A shape: mutate one source file, run one
named pytest target, restore in `finally`, assert the sha256 matches). No test,
config or eval file was ever mutated.

| # | Seed | File | Test | Verdict |
| --- | --- | --- | --- | --- |
| S1 | handshake open without a bound token | `realtime/audio_gateway.py` | `test_a_gateway_with_no_bound_token_refuses_every_connection` | RED |
| S2 | **gateway accepts frames without the arming gesture** | `realtime/audio_gateway.py` | `test_attaching_gets_a_mouth_and_no_ear_until_the_owner_gestures` | RED |
| S3 | **unbounded outbound buffer (frames)** | `realtime/audio_gateway.py` | `test_the_outbound_queue_is_bounded_and_drops_the_oldest_with_a_counter` | RED |
| S4 | unbounded outbound buffer (bytes) | `realtime/audio_gateway.py` | `test_the_outbound_queue_is_also_bounded_in_bytes` | RED |
| S5 | **barge-in stop frame dropped** | `realtime/audio_gateway.py` | `test_barge_in_clears_the_queue_and_tells_the_browser_to_stop` | RED |
| S6 | played ack not clamped to bytes sent | `realtime/audio_gateway.py` | `test_a_played_ack_is_clamped_to_what_was_actually_transmitted` | RED |
| S7 | played ack may predate the first byte | `realtime/audio_gateway.py` | `test_a_played_ack_can_never_predate_the_first_byte_of_its_utterance` | RED |
| S8 | stale-utterance ack accepted | `realtime/audio_gateway.py` | `test_an_ack_for_a_previous_utterance_is_dropped_and_counted` | RED |
| S9 | oversize microphone frame accepted | `realtime/audio_gateway.py` | `test_an_oversized_microphone_frame_is_refused_rather_than_allocated` | RED |
| S10 | TEXT control frames fed to the microphone | `realtime/audio_gateway.py` | `test_a_text_control_frame_is_never_mistaken_for_microphone_audio` | RED |
| S11 | Sans-I/O parser never primed (deaf socket) | `realtime/audio_gateway.py` | `test_a_real_socket_refuses_audio_until_the_real_gesture_frame_arrives` | RED |
| S12 | cross-origin audio socket allowed | `web_panel.py` | `test_a_cross_origin_audio_socket_is_forbidden` | RED |
| S13 | **mode:audio regresses to refusing construction** | `runtime.py` | `test_mode_audio_constructs_a_gateway_that_is_armed_but_idle` | RED |
| S14 | **text mode disturbed by the audio path** | `runtime.py` | `test_text_mode_still_builds_a_discard_sink_and_no_gateway` | RED |
| S15 | sink-ownership false positive restored (R4L risk 6) | `runtime.py` | `test_a_non_speaker_sink_is_never_a_sink_ownership_conflict` | RED |
| S16 | **sink claimed without ownership** | `runtime.py` | `test_a_non_speaker_sink_is_never_a_sink_ownership_conflict` | RED |
| S17 | panel token never reaches the gateway | `runtime.py` | `test_the_panel_token_reaches_the_gateway_that_guards_the_socket` | RED |
| S18 | mic affordance unwired in the panel | `ui/index.html` | `test_the_mic_affordance_is_actually_wired_to_the_gateway` | RED |
| S19 | browser ignores the barge-in stop frame | `ui/index.html` | `test_the_browser_stops_local_playback_on_the_barge_in_frame` | RED |
| S20 | panel token moved into the gateway URL | `ui/index.html` | `test_the_panel_token_never_reaches_the_gateway_url` | RED |
| S21 | **text mode disturbed** — live typed turn no longer reaches the hosted lane | `ui/index.html` | `test_prod_default_path.py::test_typed_commands_go_to_the_hosted_lane_whenever_it_exists` | RED |

**S18 came back GREEN on the first run and the test was strengthened, not the
seed deleted.** The original assertion was a substring check on the
`addEventListener` line, which survives `if (false) {` wrapped around it — a
button that is present, visible and dead. The test now pins the whole wiring
block including its guard. Re-run: RED.

## Live proof

Owner's stack on **:8765 was down** for the whole card (nothing listening at
start or at teardown; `ss -ltn` verified both times). Nothing of theirs was
started, stopped, POSTed to or read. Four sessions on **my own stack, :8822,
socket `/tmp/parcel_r7.sock`**, model `gpt-realtime-2.1-mini`, `mode: audio`.

**Memory isolation (R5 recipe).** `configs/robot.yaml` was COPIED to the
scratchpad with `memory.path` repointed at a scratch sqlite and passed via
`--config`; the owner's `parcel_memory.sqlite3` was never opened. Verified after
teardown: `configs/robot.yaml` sha256 `f7b57dcd…90d6f1` **byte-identical**
before and after, and the owner's db mtime is unchanged (21:16:56, before this
session started). The realtime config was a scratch `realtime_r7.yaml` with
`mode: audio` handed over via `PARCEL_REALTIME_CONFIG`; the owner's
`~/.config/parcel/realtime.yaml` (which says `mode: text`) was read once and
never written. The credential was sourced with
`set -a; . ~/.config/parcel/realtime.env; set +a` and its value was never
printed, asserted against or written anywhere.

**No microphone was involved.** Every "spoken" sentence was synthesized with the
local piper the runtime already uses
(`third_party/piper/piper --model models/piper/voice.onnx --output-raw`,
22 050 Hz), linearly resampled to the 24 000 Hz the session negotiates, and
pumped through the REAL gateway path in real-time 20 ms frames (960 bytes) by a
headless client that does exactly what `index.html` does minus the DOM
(`<scratchpad>/live/proof_client.py`).

| Session | Spoken | Outcome | Running spend |
| --- | --- | --- | --- |
| 1 | "Hey, could you go to the sidewalk please?" | **full pipe PROVEN** — transcription, `navigate_to`, audio back, both sides ledgered | `$0.019341` |
| 2 | "Could you please walk over to the crosswalk for me?" then "Stop." over the reply | **barge-in PROVEN**; spoken stop **not latched** (mis-transcribed) | `$0.045826` |
| 3 | "Stop. Stop right now, please stop." | transcript correct, **latch still did not fire** (phrase not in the exact-match set) | `$0.082554` |
| 4 | "Stop." with 0.6 s silence padding | transcribed as **"Top"** — latch did not fire | `$0.102282` |
| | | **total** | **`$0.102282`** |

### Session 1 — the whole pipe, verbatim

Client side (`t` is seconds from connect):

```
{"t": 0.002, "kind": "hello", "body": {"type": "hello", "input": {"format": "pcm16", "rate": 24000,
                                       "channels": 1, "max_frame_bytes": 32768},
                                       "output": {"format": "wav", "rate": 24000, "channels": 1},
                                       "mic_open": false}}
{"t": 0.968, "kind": "mic", "body": {"type": "mic", "on": true, "reason": "armed"}}
{"t": 0.982, "kind": "resampled", "src_hz": 22050, "dst_hz": 24000, "bytes": 118268, "duration_s": 2.464}
{"t": 0.983, "kind": "mic_stream_start", "frame_bytes": 960, "frames": 123}
{"t": 4.943, "kind": "mic_stream_end"}
{"t": 5.187, "kind": "control", "body": {"type": "utterance", "utterance": 1}}
{"t": 5.187, "kind": "audio_chunk", "index": 1, "bytes": 11564}
...
{"audio_chunks_back": 45, "audio_bytes_back": 496380, "first_chunk_riff": true}
```

Note `hello` states the negotiated wire format and `mic_open: false` — the
socket was open and the ear was shut until the client's own gesture frame.
11 564 bytes per chunk is 44 bytes of RIFF header plus exactly 240 ms of 24 kHz
PCM16, which is the lane's `DEFAULT_COALESCE_MS`.

Runtime side:

```
03:00:45 realtime | audio gateway armed (idle; no microphone until the owner asks)
03:01:02 realtime | audio gateway: panel connected (microphone still closed)
03:01:03 realtime | hosted session opened: rt_1cd689e2b491
03:01:03 realtime | realtime driver started at 20 Hz
03:01:03 realtime | audio gateway: microphone opened by owner gesture
03:01:07 realtime | tool navigate_to: ok — mission accepted: sidewalk
```

The ordering is the card's constraint 6, live: *armed idle → connected, ear shut
→ gesture → session*. The paid session did not exist until the gesture.

Broker and router:

```
broker: calls 1, executed 1, rejected 0,
        last {"tool":"navigate_to","status":"ok","detail":"mission accepted: sidewalk"}
last_route: {"turn_id":"turn-realtime-1","route":"direct_skill",
             "rule":"navigation_directive","directive":"go to sidewalk",
             "router_version":"deterministic-v1.2"}
```

Ledger (`messages` in the scratch sqlite) — **both sides landed**:

```
1 user      owner realtime 03:01:07 | Hey, could you go to the sidewalk, please?
2 assistant robot realtime 03:01:07 | Okay, let's head toward the sidewalk.
3 user      (router)       03:01:07 | go to sidewalk
4 assistant (router)       03:01:07 | Okay—I'll move onto sidewalk and verify it.
5 assistant robot realtime 03:01:21 | I got the go ahead, the mission was accepted and we're on our way to the sidewalk.
```

Row 1 is the provider's transcription of piper's speech. Rows 3–4 are the
deterministic router's own mission rows, i.e. the same admission chain text mode
uses.

### Session 2 — barge-in, live

```
{"t": 3.800, "kind": "control", "body": {"type": "utterance", "utterance": 7}}
{"t": 4.699, "kind": "barge_in_start", "chunks_heard": 13}
{"t": 4.710, "kind": "control", "body": {"type": "utterance", "utterance": 8}}
{"t": 4.920, "kind": "control", "body": {"type": "stop", "utterance": 8}}
```

The `stop` control frame reached the client 210 ms after the second utterance
started — the browser half of barge-in, which is constraint 4. The ledger row
for the truncated reply:

```
14 assistant robot realtime 03:02:54 |  and we're on the way to it. [interrupted after 0 ms]
```

**`0 ms` is honest, not a bug, and it is also a limitation** — see below.

### Final gateway counters (all four sessions)

```
connections 4 · connections_refused 0 · connections_displaced 0
mic_opens 4 · mic_refusals 0 · frames_refused_unarmed 0
frames_in 872 · bytes_in 837120        (owner microphone, 24 kHz PCM16)
frames_out 215 · bytes_out 2406580     (hosted speech, WAV-wrapped)
utterances 19 · interrupts 1
played_acks 116 · stale_acks 0 · control_errors 0
frames_dropped_backpressure 3 · frames_dropped_no_client 136
driver: steps 4695, frames 895, failures []          <-- open risk 6, gone
lane: reconnects 1 (one stall), dropped_sends 0, usage_rows 19
```

`frames_dropped_no_client 136` is the drop-and-count policy working: the model
kept talking after each client disconnected and the gateway counted the audio
instead of raising into `pump`.

**One caveat on the number above.** These counters were read from the live stack
BEFORE the final refinement that split `frames_discarded_interrupt` out of
`frames_dropped_backpressure`, so the `3` shown there is the barge-in discard,
not a browser that stopped reading. On the shipped code the same run would
report `frames_dropped_backpressure 0 · frames_discarded_interrupt 3`. The split
is pinned by test rather than re-proven live — re-running four paid sessions to
move one integer between two counters was not worth the spend, and this is the
honest note instead.

## does_not_prove

1. **No human has spoken to it or heard it.** Every utterance was piper output
   fed through a headless client. The `getUserMedia` capture path, the
   `ScriptProcessorNode` resampler, and browser playback in `index.html` have
   **never been executed** — they are pinned only as source assertions. A
   human-witnessed spoken session is owner-gated.
2. **Barge-in mark integrity is unproven, and worse than the card assumed.** The
   live truncation was `[interrupted after 0 ms]` because the headless client
   sends `played` acks only when a chunk arrives, and after `interrupt()` clears
   the anchor there are no more chunks. That is the honest answer the design
   documents ("nothing has been heard yet ⇒ truncate at zero"), but it means the
   provider was told the owner heard NONE of a reply they heard 13 chunks of.
   Full `conversation.item.truncate` integrity needs the browser to ack
   continuously from its audio clock, not per arriving chunk. Future work.
3. **The always-local wake-word / e-stop is owner-gated** and is NOT this card.
   See open risk 1 for why that now looks more urgent than it did.
4. **Two panels fighting** is handled (newest wins, `connections_displaced`) but
   was only exercised in test, never live.
5. **No load or long-session evidence.** The longest live session was ~5 minutes
   with one watchdog-driven reconnect. Nothing here says anything about an hour
   of continuous audio or about the 60-minute rollover under audio load.
6. **Cost model is estimated.** `spend_usd` uses `realtime/cost.py`'s assumed
   rates; audio tokens are priced higher than the text runs in R5, and
   `$0.102282` is an estimate, not an invoice.

## Open risks

1. **The spoken emergency latch did not fire, in three live attempts, and the
   reason is structural.** `ingress.scan` matches `EMERGENCY_STOP_PHRASES` by
   EXACT normalized phrase — the whole set is `{stop, stop now, halt, emergency
   stop}`. Live results:
   * "Stop." → whisper returned **"Soap"** → no match.
   * "Stop. Stop right now, please stop." → transcribed correctly → **no match**,
     because the whole utterance is not one of the four phrases.
   * "Stop." padded with silence → whisper returned **"Top"** → no match.

   The wiring is proven correct (`submit_realtime_transcript` ledgered every one
   of those transcripts, and `scan("stop")` returns `kind='emergency'` when
   asked directly), so this is not a plumbing defect — it is that an exact-phrase
   latch is a reasonable design for a TEXT BOX and a fragile one for a free-form
   ASR transcript. With a microphone, "stop" is whatever whisper decides it
   heard. `ingress.py` is MUST NOT TOUCH for this card so nothing was changed;
   this is the strongest available argument for the card's own owner-gated item,
   the always-local wake-word/e-stop, and it should be the next card's first
   line. **The panel STOP button and the local watchdogs are unaffected and
   remain the cloud-independent guarantees.**
2. **`ScriptProcessorNode` is deprecated** and is used because `AudioWorklet`
   needs a `blob:` module URL that the panel's
   `Content-Security-Policy: default-src 'self' 'unsafe-inline'` forbids. It
   works in every current browser but is on a removal track. The honest fix is a
   worklet served from its own same-origin URL; that is a panel-routing change
   this card did not take.
3. **Echo cancellation is the browser's.** `getUserMedia` is asked for
   `echoCancellation: true`, but hosted speech is played through a SECOND
   `AudioContext` that the browser's AEC does not know about, so the robot may
   hear itself. Untested (no speakers here). A real spoken session may need
   headphones or a mark-based mute.
4. **Two pre-existing unknown server events still log every session**:
   `input_audio_buffer.committed` and
   `conversation.item.input_audio_transcription.delta` (plus
   `conversation.item.truncated` after a barge-in) land in
   `lane.protocol_errors`. They are harmless — the lane ignores what it cannot
   parse — but `protocol.py` is frozen for this card so they were left. They are
   noise that will hide a real protocol error one day.
5. **`played_acks` is per-chunk, so a long silent gap in playback goes
   unacked.** The anchor is only refreshed when audio arrives. Combined with
   risk 2 in `does_not_prove`, the played clock is the least-proven part of this
   card.
6. **The gateway allows one connection and displaces on the second.** That is
   deliberate (a reloaded tab must not lock the owner out behind a TCP timeout)
   but it also means any page that can pass the CSRF token can steal the
   microphone from another tab. Both are the owner on loopback, so the exposure
   is a UX surprise rather than a security one — but it is a surprise.

## Deviations from the card

1. **A new file outside the OWNS list: `src/parcel_robot/realtime/audio_gateway.py`.**
   The card lists `web_panel.py` as where "your gateway endpoints live", and they
   do — the route, the three gates and the socket hand-off are all in
   `web_panel.py`. But `runtime.py` has been importing
   `parcel_robot.realtime.audio_gateway.BrowserAudioGateway` since R1.6 as its
   designed seam, and putting ~900 lines of policy, buffers and websocket codec
   into `web_panel.py` would have made the gateway untestable without an HTTP
   server. Policy lives in the new module; the endpoint lives in `web_panel.py`.
2. **One existing test was rewritten, not left untouched:**
   `test_realtime_driver.py::test_audio_mode_fails_loudly_rather_than_downgrading_to_text`.
   The card says "every existing test stays green untouched", but this one
   asserts `mode: audio` RAISES at construction — literally the clause this card
   was written to close, and it cannot be both green and correct. It was
   rewritten to pin the arm that survives (a build without the optional
   `websockets` dependency must still refuse loudly) rather than deleted. Its
   replacement is covered by seed S13 through the new suite.
3. **`_authorize_post`'s inline origin check was factored into `_same_origin`.**
   Same logic, one definition, called from both places. Not strictly "gateway
   endpoints", but duplicating a security check to avoid touching six lines
   would have been the worse choice.
4. **The card suggested socket `/tmp/parcel_r7.sock` and port :8822 — both used
   as suggested.** No deviation; recorded so the auditor can find the artifacts.
5. **Four live sessions, not one.** The card asks for "ONE live audio proof".
   Session 1 is that proof. Sessions 2–4 exist because session 2 revealed the
   emergency-latch problem and sessions 3–4 were spent establishing whether it
   was a transcription artifact or structural (it is structural). Total spend is
   still an order of magnitude under the $2 target.
6. **A `TMPDIR` override reddened my own baseline gate run** (`test_sim.py::
   test_socket_publish_and_poll`, `OSError: AF_UNIX path too long`). That was my
   environment, not the tree — the test passes with the default `TMPDIR`, `/tmp`
   had 123 GB free, and every gate run reported here uses the default.

## Frozen files — confirmed untouched

`lane.py`, `protocol.py`, `ingress.py`, `tool_broker.py`, `prompting.py`,
`realtime/config.py`, `conversation_store.py`, `memory.py`, `agent.py`,
`configs/**`, `evals/**` and the yield/person-stop policy carry **no edits from
this card**. `lane.py`'s audio seam (`send_audio`, the playback bridge,
`assert_sink_free`, the `SinkLike` protocol) was sufficient exactly as R6 left
it — the one hazard it contained, open risk 6, was fixable at the injection
point in `runtime.py` and needed no lane change. Nothing was committed, staged
or stashed; other cards' uncommitted work in the tree was not touched.

## Artifacts

* Seed harness: `<scratchpad>/seeds_r7.py`
* Live clients: `<scratchpad>/live/proof_client.py`, `<scratchpad>/live/proof_bargein.py`
* Live transcripts: `<scratchpad>/live/proof_session{1,2,3,4}.json`
* Scratch configs: `<scratchpad>/live/robot_r7.yaml`, `<scratchpad>/live/realtime_r7.yaml`
* Scratch ledger: `<scratchpad>/live/parcel_memory_r7.sqlite3`
* Stack log: `<scratchpad>/live/stack.log`

(`<scratchpad>` =
`/tmp/claude-1000/-home-jaewoo-jang-Desktop-Projects-Parcel/799cb356-4cb4-445b-a784-306b6c6fd4a6/scratchpad`)
