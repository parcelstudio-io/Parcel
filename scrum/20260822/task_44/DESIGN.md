# HW-MIC `array-arm-route` — DESIGN (task_44, wave 3b)

## (a) Purpose

HW-4 built an ear the product cannot open. `ArrayAudioGateway.set_mic(True)`
is called by nothing on the product path: the only arming door the panel has
is `web_panel.py:_serve_realtime_audio`, which refuses anything that is not a
`BrowserAudioGateway` with a 404 whose text ("mode is not audio") is false in
array mode. So `audio: {gateway: array}` today gives a runtime that builds the
array gateway, probes it, logs what it found — and then never listens, never
opens a session, and never speaks. This card adds the one missing door: a
`POST /api/realtime/mic {"open": bool}` behind the panel's existing POST
authorisation, and the `startMic()` branch that uses it, so the owner's click
opens the array's ear exactly as it opens the browser's. Nothing else moves.

## (b) Architecture fit — the seams, and who calls them

* `parcel_robot.web_panel:RuntimeHTTPRequestHandler.do_POST` — the seam. One
  new `path == "/api/realtime/mic"` arm, inside the existing
  `self._authorize_post()` / `self._read_json()` prologue and the existing
  `except` ladder (`PermissionError`→403, `(KeyError, TypeError, ValueError)`
  →400, `(ConnectionError, FileNotFoundError, OSError, RuntimeError)`→409).
  Modelled on `/api/realtime/text` (`web_panel.py:339`), the other route that
  speaks to the hosted lane.
* `parcel_robot.realtime.audio_gateway:ArrayAudioGateway.set_mic` — the callee
  (`audio_gateway.py:2619`). HW-4's F5 order is a property of THAT method
  (device first, `on_mic` second); this card must not add a second ordering.
* `RobotRuntime._realtime_mic_gesture` (`runtime.py:8414`) is `on_mic`, and it
  is what calls `RealtimeLane.ensure_session(...)` — the billed hosted session.
  The route never touches the lane; it reaches the lane only THROUGH `set_mic`,
  which is what keeps F5 true through the route.
* `RobotRuntime.realtime_gateway` (`runtime.py:2399`, built at
  `runtime.py:8288`) is the object the route reads — the same attribute
  `_serve_realtime_audio` reads at `web_panel.py:493`.
* `/api/state` → `runtime.realtime_snapshot()["gateway"]` = `gateway.snapshot()`
  (`runtime.py:9922`), which carries `kind` (`"array"` / `"browser_audio"`).
  That is where the UI already learns the kind: `renderRealtime()` stores the
  block in `state.realtime` (`ui/index.html:1543`).
* Composition: HW-2's fenced region here is the backend construction
  (`web_panel.py:699`, `:825`), TRUTH-1's is the planner section (`:632`,
  `:804`); this card's fences sit inside the handler class, disjoint from both.
  Nothing in the safety core, the lane, the broker or `audio_gateway.py` moves.

## (c) Interfaces / contracts

```
POST /api/realtime/mic          Content-Type: application/json
                                X-Parcel-CSRF: <panel token>   (same-origin, loopback Host)
body    {"open": true}          "open" REQUIRED and strictly boolean
200     {"open": <bool>, "kind": "array"}          the state that now holds
400     {"detail": "open must be a boolean"}       missing/typed wrong (TypeError)
403     {"detail": "..."}                          _authorize_post() refusal (unchanged)
404     {"detail": "no realtime audio gateway is constructed (realtime mode is <mode>)",
         "kind": null}                             mode: text, or no lane
409     {"detail": "the fitted ear is the browser microphone: arm it over the
          WebSocket at /api/realtime/audio, not this route", "kind": "browser_audio"}
409     {"detail": "the array audio gateway is not running"}   GatewayNotRunningError
503     {"detail": "<ArrayDeviceError text: names 2886:001a, env-audio.sh, the udev rule>",
         "kind": "array"}                          no array on this host
```

`200 {"open": false}` is also what a runtime REFUSAL of the gesture returns —
`set_mic` closes the streams and returns `False` (`audio_gateway.py:2666`);
the route reports the state that holds rather than inventing an error.

Two refusals are deliberately distinct: 409 = "you are asking the wrong door"
(a browser ear is fitted; the socket is that ear's door), 503 = "the right door,
no device behind it". `kind` is read from `gateway.snapshot()["kind"]`, not from
an attribute — there is no `gateway.kind` in the product (handoff HO-1).

Second, smaller contract: `_serve_realtime_audio`'s 404 text
(`web_panel.py:496`) becomes true — it names the fitted kind and says which
kind uses which door. Its LOGIC does not change: the socket still serves only
`BrowserAudioGateway`.

UI: `startMic()` gains one branch at its head. `state.realtime.gateway.kind`
=== `"array"` → POST the route, no `getUserMedia`, no `openAudioSocket()`, no
`AudioContext`; the button becomes the arm/disarm toggle through
`state.arrayMic`; the realtime detail line grows a leading `ear: array`.
Anything else (including `"browser_audio"`, an absent gateway block, an
unknown future kind) → the existing browser path, unchanged and unreached by
new code. No new config key, no new default: the switch is HW-4's
`audio.gateway`, still `browser`.

## (d) Data flow and lifecycle

Click → `startMic()` → `postJson("/api/realtime/mic", {open:true})` → panel
thread → `_authorize_post` → `gateway.set_mic(True)` → (HW-4) playback stream,
then input stream, then reader thread, then `on_mic(True)` =
`_realtime_mic_gesture` → `lane.ensure_session(...)`. Capture blocks arrive on
PortAudio's thread → the gateway's reader thread → `_offer_block` → `on_audio`
= `runtime._realtime_owner_audio` → the lane. Click again →
`{"open": false}` → `set_mic(False)` → both streams closed; the SESSION stays
open, which is `_realtime_mic_gesture`'s documented rule and not this card's
to change. No new thread, no new lock, no new file, no new process: the route
runs on the `ThreadingHTTPServer` worker thread that already serves every POST,
and every lock it stands behind is `ArrayAudioGateway._lock`.

Failure lifecycle: an `ArrayDeviceError` inside `set_mic` has already closed
whatever it opened (HW-4 F1/F5 re-verify), so the route only has to name it.

## (e) Hardware compatibility — class NEW

The route is venue-independent by construction: it is HTTP on the panel's own
loopback port, and everything venue-specific is behind `set_mic`. On the Go2
EDU+ the same panel process runs on the Orin (design §3) with the array on the
Orin's USB; the owner reaches the panel through the tailnet hop, so the
loopback `Host` rule is unchanged by this card (a non-loopback panel is a
separate decision, design §5.7). What must be configured: `audio: {gateway:
array}` in the physical profile (HW-5's file). What is UNKNOWN until the box: whether the Orin's PortAudio
enumerates the array the same way (HW-4's `prefer hw:` rule is the mitigation),
and whether the duplex clocking fact holds there — this card asserts neither,
because it only calls `set_mic` and reports what it returns. The desktop with
the array on hand proves everything the route does; the Orin proves nothing new.

## (f) Test strategy → the pre-registered rows

`tests/test_hwmic_arm_route.py`, all through the real handler over a real
loopback socket (`RuntimeHTTPServer`, the shape `tests/test_web_panel.py`
uses), with HW-4's `audio=` proxy as the device layer:
R1 unauthorised (no token / wrong origin) → 403 and `set_mic` never called;
R2 browser kind → 409, the text names `/api/realtime/audio`;
R3 array kind → 200 `{"open": true, "kind": "array"}`, `set_mic` called once;
R4 F5 through the route: the input stream exists BEFORE `on_mic` fires;
R5 a refusing device → 503, `on_mic` never called, no session;
R6 `{"open": false}` → 200 `{"open": false}` and both streams closed;
R7 a bad/missing `open` → 400, `set_mic` never called;
R8 no gateway → 404;
R9 flag-off: the POST route list = HEAD's 13 + exactly `/api/realtime/mic`, the
GET list unchanged, and `build_runtime` with no `audio:` key still builds the
browser gateway;
R10 the UI's browser branch is byte-identical (sha256 of `startMic` with the
fenced region removed = HEAD's `06bf8086…`; `renderRealtime` likewise);
R11 real array, through the route, 10 s.
Seeds (one per guard, on an import-verified scratch): drop `_authorize_post`
from the route; return the browser gateway's kind for both; call `on_mic`
before the device (F5 inversion, in a copy of the gateway); delete the UI
branch.

## (g) Risks / not covered

* The route can arm the ear on a host whose owner is not in the room — as the
  websocket can today, behind the same token and the same loopback rule. It is
  still a deliberate POST; no new authority.
* Nothing here proves the hosted lane ends up with usable audio: the real row
  stubs `ensure_session` at the lane boundary ($0, `PARCEL_REALTIME_KEY_ENV`
  unset). HW-4's through-air O1 stays owner-gated.
* The UI branch is not exercised by a browser in this card (no JS engine row);
  it is pinned by text and by the route's own tests. A `gjs` row is available
  (MARK-1's precedent) and is NOT claimed here.
* `kind` asymmetry (`"browser_audio"` vs `"array"`) is HW-4's to keep or fix;
  this card branches on `"array"` and reads every other value as the browser.
