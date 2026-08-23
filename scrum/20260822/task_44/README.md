# Task 44 — HW-MIC: `array-arm-route` — the product can open the array's ear

**Executor:** Claude Opus · **Verifier:** Fable · **Board:** `../TASK_BOARD.md`
(P0 rules + anti-crash rules; wave-3 COMMON brief). **Design:**
`../WAVE3_HW_DESIGN_FABLE.md` §5.6 (+ the HW-4 amendment), §9.
**Evidence:** HW-4's `task_37/HW4_STATUS.md` (H-1; the gateway streams in
duplex; `set_mic` opens the device before the session after F5),
`~/.cache/parcel-verify/hw4/VERDICT.md` (the minimal change: `POST
/api/realtime/mic {"open": bool}` behind `_authorize_post()` → `set_mic`;
fix the 404 text; `startMic()` branches on `realtime.gateway.kind`),
`web_panel.py:494` (`isinstance(gateway, BrowserAudioGateway)` gate),
`:558 _authorize_post`, `ui/index.html` `startMic()`.

## Why
Nothing in the product calls `ArrayAudioGateway.set_mic(True)`: the panel
arms only the browser gateway. Without this route the array ear is
harness-only.

## Work
1. `DESIGN.md` first: the endpoint (`POST /api/realtime/mic` body
   `{"open": bool}`; authorised like every other POST; returns the
   gateway's `set_mic` result + `kind`), the `startMic()` branch in the UI
   (browser kind → today's websocket path, unchanged; array kind → the
   POST, the UI shows "ear: array" and no browser capture), the 404/409
   texts, what an unauthorised or wrong-kind call does (typed refusal,
   no session opened — HW-4's F5 ordering must hold through this route).
2. `web_panel.py` marked `CARD HW-MIC` region (the route + the gate's
   message); `ui/index.html` marked region (`startMic()` branch + the
   status line); no change to the browser path (byte-identical: pin it).
3. Tests `tests/test_hwmic_arm_route.py`: through the real panel handler
   (the way `tests/test_web_panel*.py` drive it): unauthorised → refused;
   browser kind → 409 with the text; array kind with a FAKE device layer
   (the `audio=` proxy HW-4 used) → `set_mic(True)` called once, device
   opened before any session, `open: false` closes; flag-off: with
   `audio.gateway` absent the handler table is byte-identical to HEAD
   (pin the route list); seeds RED per guard on an import-verified
   scratch. With the REAL array (on hand): one 10 s arm through the route
   → frames reach `on_audio` (duplex; silence only to the DAC; the hosted
   lane NEVER opened — `PARCEL_REALTIME_KEY_ENV` unset; the session
   opener must be stubbed at the lane boundary, not the gateway).

OWNS: `web_panel.py` `CARD HW-MIC` region, `ui/index.html` marked region,
`tests/test_hwmic_*.py`, `task_44/` docs. MUST NOT TOUCH:
`realtime/audio_gateway.py` (HW-4's), `lane.py`, the broker, HW-2's region
in `web_panel.py` (mkdir-lock `~/.cache/parcel-batchb/lock-web_panel.py`).

## Definition of done
Route armed through the real handler with the fake device; real-array 10 s
arm delivers frames; browser path byte-identical; seeds RED;
`HWMIC_STATUS.md` with pre-registered rows.

## Hardware-compat (§e)
Class NEW (S11's arm route). Desktop proves it with the array on hand; the
Orin proves nothing new here.
