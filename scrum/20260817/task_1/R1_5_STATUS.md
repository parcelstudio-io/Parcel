# R1.5 — Realtime live WebSocket transport

**Date:** 2026-08-17 · **Card:** `scrum/20260817/task_1` · **Executor:** Claude Opus
**Depends on:** R1 (`scrum/20260816/task_7`, ACCEPT_CLOSE)
**Baseline:** started at `8473a51` with a clean tree. Mid-card the owner
committed the 08-16 wave, so HEAD is now `877d9f4`; nothing of this card's was
touched by it, and the gate below was re-run from scratch on the current tree.
A parallel card (R2-C) has uncommitted work in the same package
(`realtime/prompting.py`, `evals/companion/realtime_convo_v1/`,
`tests/test_realtime_prompting.py`, `tests/test_realtime_corpus_replay.py`,
`runtime.py` +39/−5) which was **not** read-modified, staged, or reverted here.
**Venv:** `/home/jaewoo-jang/Desktop/Projects/Parcel/.parcel/bin/python`

## What landed, in one paragraph

A second implementation of R1's `Transport` Protocol — a real `wss://` socket —
so that `lane.py`, `protocol.py`, `ingress.py` and `transport.py` are byte-for-byte
untouched and the lane drives a live provider with zero edits. A daemon reader
thread owns `recv` and parks decoded frames in a **bounded** deque so `receive()`
never blocks and never grows without limit; the drain-then-raise ordering that
`InProcessTransport.receive` documents is reproduced exactly. Failures become
three typed outcomes instead of a `ConnectionClosedError`: `RealtimeAuthError`,
`RealtimeQuotaError`, and plain `TransportClosed` for an ordinary hang-up. The
credential is taken **by name** — the transport reads an environment variable at
connect time, never stores the value, and scrubs every string it composes.
24 offline tests drive a genuine loopback `websockets.sync.server` (real
handshake, real framing, real close codes, no mocks, no network, no key), and
one double-gated live test drives the whole product path against the real API.
**A live conversation has never happened: the account has no billing quota.**
That failure is now a typed, tested, legible outcome — and it was confirmed once
against the real server today.

## Files

| File | Lines | What |
| --- | --- | --- |
| `src/parcel_robot/realtime/ws_transport.py` | 660 | `WebSocketTransport`, typed errors, `redact`, `websocket_transport_factory` |
| `tests/test_realtime_ws_transport.py` | 751 | 24 tests against a real loopback WebSocket server |
| `tests/test_realtime_live.py` | 140 | 1 test, `slow` + double `skipif`; the only thing here that needs a key |
| `requirements-lock.txt` | +1 / −0 | `websockets==17.0.1` |
| `scrum/20260817/task_1/R1_5_STATUS.md` | this file | |

`git diff --numstat` reads `1 0 requirements-lock.txt` and nothing else. The
three code files are new and untracked. `configs/robot.yaml`, `pyproject.toml`,
`scripts/ci_gate.py`, and every R1 module gained **zero bytes**.

## Frozen contract surface

**Class.** `WebSocketTransport(*, model=None, url=None, api_key_env="OPENAI_API_KEY",
name="live", max_inbound=512, open_timeout_s=30.0, close_timeout_s=5.0,
poll_s=0.05, allow_insecure=False, extra_headers=None, clock=time.monotonic)`.
Either `model` or `url` is required; neither ⇒ `RealtimeTransportError`.
`.open()` connects and returns `self`. It satisfies R1's runtime-checkable
`Transport` Protocol — `send` / `receive` / `close` / `closed` — plus the
affordances `pending`, `wait(timeout)`, `down_kind`, `down_reason`,
`diagnostics()`, and the counters `sent_frames`, `received_frames`,
`dropped_frames`, `decode_errors`, `last_send_at`, `last_receive_at`,
`connected_at`.

**Errors.** `RealtimeTransportError(RuntimeError)` with three subclasses:
`RealtimeConnectError` (socket never opened), `RealtimeAuthError`
(missing/rejected credential, 401/403-shaped, close 3000/3003/4001/4003),
`RealtimeQuotaError` (`insufficient_quota` error frame and/or close 1013, HTTP
402/429). A normal hang-up is R1's own `TransportClosed`, unchanged.

**Semantics.** `receive()` drains the backlog **before** reporting the hang-up,
returns `None` when idle, never blocks, and is safe after `close()`. `closed` is
true once **either** end hung up. `close()` is idempotent and never raises.
Overflow drops the **oldest** frame and increments `dropped_frames`. A frame
that is not a JSON object increments `decode_errors` and is never delivered and
never invented.

**Factory.** `websocket_transport_factory(*, model=None, url=None,
api_key_env=..., **kwargs) -> Callable[[], WebSocketTransport]` — one fresh
socket per call, which is what `RealtimeLane(transport_factory=...)` wants on
every connect and every reconnect.

**URL.** `realtime_url(model)` → `wss://api.openai.com/v1/realtime?model=<model>`.
Verified live today. No beta header is required. The credential rides in an
`Authorization: Bearer` header, so the URL itself is safe to log.

## The five decisions worth naming

### 1. A quota refusal is deliberately NOT a `TransportClosed`

`RealtimeLane.pump()` answers `TransportClosed` with `_on_disconnect()` →
`_reconnect()`. If `RealtimeQuotaError` subclassed `TransportClosed`, an account
with no credit would produce one full reconnect — new socket, new
`session.update`, re-injected memory tail — **per `pump()` call**, forever, and
the lane's own record would say "transport disconnected mid-session" instead of
"you are out of money". So the typed refusals sit beside `TransportClosed` in
the `RuntimeError` family rather than under it: an ordinary hang-up still takes
R1's reconnect path unchanged, and a credential or billing wall propagates to
the caller as itself. Pinned by
`test_a_quota_refusal_reaches_the_caller_instead_of_starting_a_retry_storm`
(lane reconnects stay at 0, exactly one socket is opened) and by seed **S5**,
which restores the subclassing and reddens three tests.

This is a declared deviation from the card's "subclass sensibly … so the lane's
existing `except`-clauses still behave" — see *Deviations* below.

### 2. Overflow drops the OLDEST frame, and classification happens first

A hosted response is a burst of 24 kHz audio deltas; an unbounded backlog turns
a stalled caller into a memory leak. The buffer is bounded at 512 frames and
drops the oldest, because the frames that describe the current state
(`response.done`, `error`) are the newest ones. Crucially, `_note_error_frame`
reads a provider `error` frame's meaning **before** it is enqueued, so an
overflow that discards the error frame cannot also discard the diagnosis —
`test_the_quota_diagnosis_survives_an_overflow_that_drops_the_error_frame`
pins that, and seed **S8** reddens it.

### 3. The key is a name, not a value, and is never stored

`api_key_env` is a variable NAME. The value is read inside `open()`, lives in
one local and the header mapping handed to `connect()`, and is never assigned to
`self` — `test_the_instance_does_not_hold_the_key_at_all` walks `vars()` and
asserts it. Every message the module composes passes through `redact()`, which
scrubs an explicit secret plus two credential shapes (`Bearer …`, `sk-…`).
Library failures are re-raised `from None` so a chained exception can never
print an `Authorization` header into a traceback. The load-bearing test drives
two hostile shapes — a server whose 401 body echoes the received `Authorization`
header, and an accepted session whose `error` message embeds the key, which the
transport then quotes when it raises — and asserts the key appears in none of:
exception `str`, exception `repr`, transport `repr`, `diagnostics()`,
`down_reason`, or any captured log record. Seed **S3** reddens it.

### 4. A credential will not go onto a plaintext socket by accident

`open()` refuses a non-`wss://` URL unless the caller passes
`allow_insecure=True`. The loopback tests opt in explicitly and visibly; nothing
else can. Seed **S7** reddens it.

### 5. `receive()` is non-blocking by construction, and `wait()` is the honest alternative

The reader thread parks in `conn.recv(timeout=0.05)`; `receive()` only ever
touches the deque under a lock. `test_receive_returns_none_when_idle_and_never_blocks`
performs 500 idle receives and asserts they finish in under 1 s — a blocking
implementation would take ~25 s. `wait(timeout)` is offered for callers (and
tests) that would rather block than spin; it consumes nothing.

## Live evidence — the one thing that HAS been proven against the real server

The live test was executed once today with the credential loaded from
`~/.config/parcel/realtime.env`. It failed, as expected, and the failure is the
proof that the typed mapping is correct against the real provider rather than
only against a script:

```
E           Failed: The live Realtime session was refused for QUOTA, not for a code fault.
E             provider: realtime session refused for quota (close code 1013, reason
E             'insufficient_quota.insufficient_quota'); provider said: You exceeded your
E             current quota, please check your plan and billing details. For more information
E             on this error, read the docs: https://platform.openai.com/docs/guides/error-codes/api-errors..
E             This is an account billing state, not a transport fault and not something a
E             reconnect can fix.
E             model:    gpt-realtime-2.1-mini
E             credential: $OPENAI_API_KEY (present, accepted at the handshake)
E           This is an owner billing action: add credit to the account. As of
E           2026-08-17 this test has never passed, and R1_5_STATUS.md says so.
```

What that single run establishes, and nothing more:

* the TLS handshake, the `Authorization: Bearer` header and the model query
  parameter are right — the socket **opened and authenticated** (no 401, no
  handshake rejection);
* the provider's real first frame is `error{code: insufficient_quota}` and its
  real close code is **1013** with reason `insufficient_quota.insufficient_quota`;
* the transport turned that into `RealtimeQuotaError` with the provider's own
  sentence quoted, and the failure surfaced at `open_session()` — the earliest
  possible point — rather than three turns later;
* the captured output was checked programmatically for the key. **It does not
  appear anywhere in it**, including in the `repr` of the transport that pytest
  printed in the traceback.

No conversation occurred. No tokens were billed. **This test has never passed.**

## Gate table

```
$ .parcel/bin/python scripts/ci_gate.py --tier commit
CI GATE — tier=commit  (2026-08-18T02:46:49Z)
==============================================================================
[  PASS] HARD  ruff                       7 violation(s), baseline 7, new 0
[  PASS] HARD  hard-safety                nav frozen baseline nav-instruct-v1-baseline-v4-20260811T070536Z: collisions=0 false_arrival=0 | mutation panel clean: collisions=0 no_false_arrival=True | mutation panel freshness: committed fields reproduce live = True | follow-bench: 7 row(s), hard_collision_total all 0 = True | walk_with_me: 1/2 row(s) with hard_collision_total, all 0 = True
[  PASS] HARD  frozen-digest-sentinels    4 immutable manifest(s) byte-identical to pin
[  PASS] HARD  release-parity             91 packaged asset(s) byte-identical to canonical source
[  PASS] HARD  latency-tail-ledger        latest row latency-20260810T082415Z-4d83035f: 6 metric series within 1.2x tail ceiling (rows=5, window=5)
[  PASS] HARD  follow-bench-jerk-ratchet  latest shipped row follow-bench-v1-20260811023618Z-93eba090.json: 1.2187 <= 1.46244 (baseline 1.2187 x 1.2)
[  PASS] HARD  model-off-non-inferiority  23 passed in 0.45s
[  PASS] HARD  frozen-digest-integrity    6 passed, 1 warning in 0.33s
[  PASS] HARD  release-parity-integrity   10 passed in 0.73s
[  PASS] HARD  mutation-panel-freshness   2 passed, 3 warnings in 4.33s
[  PASS] HARD  latency-tail               6 passed, 2 warnings in 0.32s
[  PASS] HARD  default-suite              5778 passed, 9 skipped, 41 deselected, 5 warnings in 231.29s (0:03:51)
==============================================================================
RESULT: PASS — every hard gate green.
  elapsed 243.9s
```

`ruff` reports `new 0` against the pinned baseline of 7 fingerprints; the
baseline file was **not** regenerated (all three new files are clean outright).
`deselected` is **41**, one more than the 40 R1 recorded — that one is
`tests/test_realtime_live.py`, deselected by `-m "not slow"` rather than
skipped, which is the card's requirement that it never be red-by-skip. The
`default-suite` total of 5778 includes this card's 24 offline transport tests
and 96 tests belonging to the parallel R2-C card whose files were already on
disk. An identical run at 02:22:55Z on the pre-`877d9f4` tree produced the same
verdicts and the same counts; the table above is the re-run on the current tree,
as instructed.

## Seeded-failure table

`scratchpad/seed_r1_5.py` (session scratchpad, never the repo) mutates one
shipped source file per seed, runs the owning test file, and restores the file
in a `finally` block. `git status --short` before and after the whole run is
byte-identical, and the clean suite is re-run at the end.

All eight mutate `src/parcel_robot/realtime/ws_transport.py`; the owning test
file is `tests/test_realtime_ws_transport.py` (24 tests).

| # | Seeded defect | Result | Run summary and first failing test(s) |
| --- | --- | --- | --- |
| S1 | drain-before-raise ordering removed from `receive()` (report the hang-up before draining) | **RED** | 7 failed, 17 passed — `test_the_backlog_drains_before_the_hang_up_is_reported`, `test_close_is_idempotent_and_a_closed_transport_still_drains`, `test_overflow_drops_the_oldest_frames_and_counts_them` |
| S2 | quota close (1013 / `insufficient_quota`) demoted to a plain hang-up | **RED** | 7 failed, 17 passed — `test_insufficient_quota_then_1013_raises_a_typed_quota_error`, `test_a_bare_1013_without_an_error_frame_is_still_a_quota_refusal`, `test_the_quota_diagnosis_survives_an_overflow_that_drops_the_error_frame` |
| S3 | credential redaction removed (`redact` returns its input) | **RED** | 2 failed, 22 passed — `test_the_key_never_appears_in_anything_the_transport_produces`, `test_redact_scrubs_credential_shapes_it_was_never_told_about` |
| S4 | inbound deque unbounded (no drop, no count) | **RED** | 2 failed, 22 passed — `test_overflow_drops_the_oldest_frames_and_counts_them`, `test_the_quota_diagnosis_survives_an_overflow_that_drops_the_error_frame` |
| S5 | typed refusals made `TransportClosed` subclasses again (the lane retry storm) | **RED** | 3 failed, 21 passed — `test_insufficient_quota_then_1013_raises_a_typed_quota_error`, `test_a_401_handshake_rejection_raises_a_typed_auth_error`, `test_a_quota_refusal_reaches_the_caller_instead_of_starting_a_retry_storm` |
| S6 | `send()` reports a bare close instead of the typed reason | **RED** | 1 failed, 23 passed — `test_a_send_that_beats_the_reader_to_the_close_still_names_the_reason` |
| S7 | non-TLS credential guard removed | **RED** | 1 failed, 23 passed — `test_a_plaintext_url_will_not_carry_the_credential_without_an_opt_in` |
| S8 | provider `error`-frame classification removed | **RED** | 2 failed, 22 passed — `test_the_quota_diagnosis_survives_an_overflow_that_drops_the_error_frame`, `test_the_key_never_appears_in_anything_the_transport_produces` |

8 seeds, 8 RED. `=== tree restored: YES ===`, then
`clean: PASS :: 24 passed, 1 warning in 0.73s`.

**S6 was GREEN on the first pass** and that is worth recording rather than
hiding: the `except ConnectionClosed` arm of `send()` had no test — every
existing send-after-death test hit the earlier `if down is not None` return.
`test_a_send_that_beats_the_reader_to_the_close_still_names_the_reason` was
written to close that gap (it stops this class's own reader thread so the close
is discovered inside `conn.send`, which is white-box on `WebSocketTransport` and
still not a mock of `websockets`), and S6 has been RED since.

## Test runs

```
$ .parcel/bin/python -m pytest tests/test_realtime_protocol.py \
    tests/test_realtime_ingress.py tests/test_realtime_lane.py \
    tests/test_realtime_ws_transport.py tests/test_realtime_live.py -q
211 passed, 1 skipped, 2 warnings in 1.89s
```

Re-run on the current tree (post-`877d9f4`, with R2-C's uncommitted files
present) after the gate: same result, `211 passed, 1 skipped`, and this card's
two files alone read `24 passed, 1 skipped in 0.58s`.

The 1 skip is the live test (no `PARCEL_REALTIME_LIVE=1` in that shell). Under
the gate's own `-m "not slow"` selection it is **deselected**, not skipped:

```
$ .parcel/bin/python -m pytest tests/test_realtime_live.py -q -m "not slow"
1 deselected
```

`tests/test_realtime_ws_transport.py` was run three times back to back
(`24 passed` in 0.76 s / 0.84 s / 0.81 s) to check for thread-timing flake.

```
$ .parcel/bin/python -m ruff check src/parcel_robot/realtime/ws_transport.py \
    tests/test_realtime_ws_transport.py tests/test_realtime_live.py
All checks passed!
```

All three new files are also `ruff format`-clean.

## OWNS compliance

`git status --short` after the full run:

```
 M requirements-lock.txt                          <- this card (+1/-0)
 M src/parcel_robot/runtime.py                    <- R2-C, untouched here
?? evals/companion/realtime_convo_v1/             <- R2-C, untouched here
?? scrum/20260817/                                <- this card (README + this file)
?? src/parcel_robot/realtime/prompting.py         <- R2-C, untouched here
?? src/parcel_robot/realtime/ws_transport.py      <- this card
?? tests/test_realtime_corpus_replay.py           <- R2-C, untouched here
?? tests/test_realtime_live.py                    <- this card
?? tests/test_realtime_prompting.py               <- R2-C, untouched here
?? tests/test_realtime_ws_transport.py            <- this card
```

Four entries are this card's; the rest belong to the concurrent R2-C session and
were left exactly as found. `git diff --numstat` for this card is a single line,
`1 0 requirements-lock.txt`.

`requirements-lock.txt` is the card's own conditional instruction ("add it only
if that file already pins optional extras — check first"): it does — it is a
`pip freeze` of the whole `.parcel` venv and already carries `sounddevice`,
`msgpack`, `pytest` and `ruff`, none of which are core `dependencies`. One line
was added in sorted position. `pyproject.toml` was **not** touched, so
`websockets` is still not a declared dependency of the package.

Nothing was staged, committed, or stashed. `scrum/20260817/` is this card.

## Deviations from the card

| # | Deviation | Why |
| --- | --- | --- |
| 1 | Typed refusals are **not** subclasses of `TransportClosed` | The card asks for "subclass sensibly … so the lane's existing `except`-clauses still behave". A normal hang-up does behave exactly as before (`TransportClosed`, lane reconnects). Making a billing wall inherit that behaviour would produce a reconnect storm against a provider that is refusing on purpose, and would relabel "out of credit" as "disconnected". Decision 1 above; pinned by test and by seed S5. |
| 2 | The live test uses the lane's shipped `output_modalities: ["audio"]`, not `["text"]` | `SessionUpdate.to_payload()` hardcodes `["audio"]` and `protocol.py` is MUST-NOT-TOUCH. Worse, R1's codec only knows `response.output_audio_transcript.delta/.done`; a text-modality session emits `response.output_text.*`, which the fail-closed codec would refuse frame by frame, so a text-only live test would prove the transport works and the *lane* does not. The card's own objective is "the moment billing is added, the lane talks", so the test drives the real product path. Cost of one short spoken reply is a fraction of a cent, and it is behind an explicit opt-in env var. |
| 3 | The live test writes the owner ledger row itself | With no runtime ingress wired, the lane only writes an owner row on `conversation.item.input_audio_transcription.completed`, which needs real owner *audio*. The test therefore plays the part the runtime plays (R1_STATUS, "Who writes the owner row") and asserts the **robot** row came from the live provider. |
| 4 | `allow_insecure` flag added (not requested) | Six lines. Without it, the loopback tests would silently normalize "send the key over plaintext"; with it, that is an explicit, visible, single-purpose opt-in. Seed S7. |
| 5 | `wait()`, `pending`, `diagnostics()`, `down_kind`/`down_reason` added beyond the Protocol | `pending` mirrors `InProcessTransport`. `wait()` is what lets the tests be event-driven instead of sleeping. `diagnostics()` is the operator surface a `/api/state` block would read, and is asserted to be credential-free. |

## does_not_prove

* **No hosted conversation has ever occurred, on this card or any other.** The
  account has no billing quota. Every behavioural claim about a *working*
  session is a claim about a scripted loopback server. What has been proven
  against the real API is exactly one thing: the connect + authenticate +
  immediate `insufficient_quota` + close-1013 path, once, today.
* **The provider's real event ordering and timing are still unverified.**
  Whether `response.output_audio.delta` really precedes
  `response.output_audio_transcript.delta`, how a truncate lands after a cancel,
  what the real inter-frame cadence is, whether 512 frames is a sensible bound
  for real audio bursts — all of that remains documentation, not measurement.
* **The codec has never met a real server frame.** R1's `parse_server_event`
  fails closed on unknown types by design. If the live provider emits any event
  type outside R1's list — likely, since the list is a deliberate subset — the
  lane will record `protocol_errors` on the first turn. The live test asserts
  `lane.protocol_errors == []` precisely so that this shows up the moment
  billing exists, but today that assertion has never executed.
* **`output_modalities: ["text"]` is known-unsupported by R1's codec** (see
  deviation 2). If the owner wants a cheap text-only live probe, that is an R2
  change to `protocol.py`, not a transport change.
* **No audio has been played and no microphone has been read.** The live test
  uses a null sink; PortAudio is not loadable on this host. The lane's
  playback bridge is exercised only by R1's fake sink.
* **Nothing is wired into `runtime.py`.** The runtime still constructs the lane
  with no transport factory, so the arming gate still returns `no_transport`.
  Turning the live lane on end-to-end needs: `configs/realtime.yaml` with
  `enabled: true`, `transport_factory=websocket_transport_factory(model=...)`,
  `sink_factory=SpeakerSink`, and a loopback audio listener carrying the panel's
  CSRF token. None of that is in this card's OWNS set and none of it was done.
* **Reconnect backoff does not exist anywhere.** The lane reconnects
  immediately, once per `pump()` that sees a `TransportClosed`. Against a
  provider that is flapping rather than refusing, that is a hot loop. R1 had the
  same property; R1.5 makes it reachable over a real socket for the first time,
  which raises its priority. It is an explicit R2 handoff.
* **The reader thread is not resilient to a hung TLS socket.** `close()` joins
  it with a 5 s timeout and the thread is a daemon, so a wedged socket leaks one
  thread rather than blocking shutdown. Nothing tests that case.
* **The underlying `websockets` connection object retains the request headers**
  (`conn.request.headers` includes `Authorization`). The transport never exposes
  `_conn` and never reprs it, and no test could find the key in anything the
  class produces — but a caller that reached into the private attribute could
  still read it. The instance's own attributes are asserted clean; the library's
  are not the transport's to scrub.
* **No cost or latency measurement.** `usage_rows` are parsed by R1 and have
  never been compared against an invoice, because there is no invoice.
* **The 401 path is proven only against a loopback server.** The real provider
  has never rejected this credential — it authenticates fine and then refuses to
  bill. `RealtimeAuthError` is therefore verified in structure, not in the wild.

## Handoffs

* **Owner, before anything else: add billing credit.** Then run
  `set -a; . ~/.config/parcel/realtime.env; set +a; PARCEL_REALTIME_LIVE=1 \
  .parcel/bin/python -m pytest tests/test_realtime_live.py -m slow`. That single
  command is the whole acceptance test for "the lane talks", and its first
  failure will be informative either way.
* **R2 — wire the runtime.** `configs/realtime.yaml` in the ship set,
  `transport_factory` + `sink_factory` passed at construction, and a reconnect
  **backoff** (the transport deliberately does not retry; the lane currently
  retries with no delay).
* **R2 — the codec will need extending on first contact.** Expect
  `UnknownEventType` on real traffic; the fail-closed design means that is
  visible rather than silent, but someone has to add the events.
* **R3 — the tool broker** still refuses everything, unchanged by this card.
* **Carry-forward from the R1 audit, still open:** pin "follow via the ingress
  is refused while e-stopped", and route R3's tool broker through `ToolCall` +
  `SafetySupervisor.validate`. Neither is touched here.
