# HW-MIC `array-arm-route` (task_44) — executor status

**Executor:** Claude Opus (session 31fcc2a0, wave 3b) · **Verifier:** Fable
**Run window:** 2026-08-23 14:40–15:10 local (the host clock reads EDT−3 of the
dispatch's wall time; every timestamp below is `date` on this host, matching
`~/.cache/parcel-guard/guard.log`).
**Design:** `DESIGN.md` (152 lines; 2 over the 150 target — the HTTP contract is
quoted verbatim rather than summarised).
**Pre-registration:** `PREREGISTRATION.md`, sha256
`0747c9fb22f04ea09240ccd43b5d9dd593d8869a26050d4e538854c94c28ff59`, written
before the first line of code and unedited since.

## Headline

**COMPLETE. 15/15 rows MET.** The array ear has a door: `POST
/api/realtime/mic {"open": bool}` behind `_authorize_post()`, and `startMic()`
uses it when `/api/state` says the fitted ear is the array. On the REAL
XVF3800, one POST through the real panel handler delivered **250 frames ×
1,920 B = 10.000 s of 24 kHz audio to `on_audio` in 10.003 s** (24.99 fps, 0
capture errors, 0 overflows, 0 dropped-unarmed, 0 deaf warnings), with
`frames_out`/`bytes_out` **0** — only `_on_playback`'s digital silence reached
the amplifier — and `lane.ensure_session` called **exactly once, after the
input stream was already open** (HW-4's F5 ordering, now proved on hardware
through the product route). The browser path is untouched and pinned by
sha256: strip this card's fenced blocks from `ui/index.html` and `startMic`,
`renderRealtime` and `stopMic` hash to what HEAD had. HW-4's O1 (the
through-air session) is unblocked; it stays owner-gated.

## What changed

`git diff --stat` (index → tree) on my OWNS:

```
 src/parcel_robot/ui/index.html |  52 +++++++++
 src/parcel_robot/web_panel.py  | 210 ++++++++++++++++++++++++++++++-  (108 +/1 - are mine)
```

Attribution by hunk (`git diff -U0`), because HW-2 is editing the same file:

| file | hunk | owner |
|---|---|---|
| `web_panel.py` | `@@ -347,0 +348,90 @@` — the route, one fenced region inside `do_POST` | **HW-MIC** |
| `web_panel.py` | `@@ -494,0 +585,8 @@`, `@@ -496 +594,9 @@`, `@@ -498,0 +605 @@` — the `_serve_realtime_audio` 404 TEXT (its condition untouched) | **HW-MIC** |
| `web_panel.py` | `@@ -698,0 +806,97 @@`, `@@ -728 +932,3 @@` — `_build_backend` + its call site | HW-2 (task_40) |
| `index.html` | `@@ -1569,0 +1570,5 @@` (status line), `@@ -2487,0 +2493,7 @@` (the label constant), `@@ -2709,0 +2722,40 @@` (the `startMic` branch) | **HW-MIC** |

New file: `tests/test_hwmic_arm_route.py` (679 lines, 15 tests).
Docs: `scrum/20260822/task_44/{DESIGN,PREREGISTRATION,HWMIC_STATUS}.md`.

Final shas: `web_panel.py` `b330c612…`, `ui/index.html` `f6e4c9fd…`,
`tests/test_hwmic_arm_route.py` `1cb8272a…`.

**MUST NOT TOUCH, verified:** `git diff -- <file> | grep -c 'HW-MIC'` is **0**
for `realtime/audio_gateway.py`, `runtime.py` and `config.py` (all three are
dirty from HW-4/HW-5, none of it mine), and `grep -rln 'CARD HW-MIC'` over
`src/` + `tests/` returns exactly the three files above. HW-2's fenced region
and TRUTH-1's are byte-identical to what they were when I took the lock.

**The contract, exactly as shipped:**

```
POST /api/realtime/mic   Content-Type: application/json + X-Parcel-CSRF + loopback Host + same origin
body  {"open": <bool>}           REQUIRED and strictly boolean
200   {"open": <bool>, "kind": "array"}                        the state that NOW HOLDS
400   {"detail": "open must be a boolean"}                     missing / "yes" / 0 / 1 / null
403   {"detail": "<_authorize_post text>"}                     no token, wrong token, cross-origin
404   {"detail": "no realtime audio gateway is constructed, so there is no ear to arm
                  (realtime mode is 'text')", "kind": null}
409   {"detail": "the fitted ear is browser_audio, not the array: a browser microphone is
                  armed over the WebSocket at /api/realtime/audio, not through this route",
       "kind": "browser_audio"}
409   {"detail": "the array audio gateway is not running"}     GatewayNotRunningError, via do_POST's
                                                               existing RuntimeError arm
503   {"detail": "<ArrayDeviceError, verbatim: lsusb 2886:001a / scripts/env-audio.sh /
                  /etc/udev/rules.d/99-respeaker-xvf3800.rules>", "kind": "array"}
```

A runtime that REFUSES the mic gesture is a 200 `{"open": false}`, not an
error: `set_mic` closes what it opened and returns `False`, and that is the
state the owner is in.

## How verified

Every pytest through `~/.cache/parcel-guard/pytest_guard.sh` with `env -u
TMPDIR`, foreground, never `-n auto`, never a `ci_gate.py` tier. `guard.log`:
**15 runs, 15 START / 15 END, 0 × rc=137, 0 refusals** (`label=hwmic` 5,
`label=hwmic-seed` 10) — corrected from "14" in the first draft (verifier N3;
the uncounted run is 14:49:54 rc=1, the D2 own-comment failure). Pre-flight before each: 230 GB available, ≤ 1 pytest.
No simulator was started; `tests/test_voice_nav_e2e.py` was never run.

| row | result |
|---|---|
| R1 | **MET.** No token / wrong token / `Origin: https://attacker.example` → 403, 403, 403; `mic_opens 0`, zero streams opened |
| R2 | **MET.** Browser gateway → 409, detail contains `/api/realtime/audio`, `kind == "browser_audio"` |
| R3 | **MET.** Array gateway → 200, body exactly `{"open": true, "kind": "array"}`, one `on_mic(True)`, one input + one output stream; a second arm is idempotent (still one stream, still one gesture) |
| R4 | **MET.** One shared event log records `["output", "input", "on_mic"]` — the playback clock, then the ear, then the runtime gesture |
| R5 | **MET.** Device list with no XVF3800 → 503, detail names `99-respeaker-xvf3800.rules` and `lsusb`, `on_mic` calls `[]`, no input stream |
| R6 | **MET.** `{"open": false}` → 200 `{"open": false, "kind": "array"}`, input and output streams `closed`, and the session gesture is NOT called again (closing is not hanging up) |
| R7 | **MET.** `{}`, `"yes"`, `"no"`, `1`, `0`, `null` → 400 each with "open must be a boolean"; `mic_opens 0` |
| R8 | **MET.** No `realtime_gateway` attribute → 404 `kind: null`; `mode: text` → 404 naming `'text'` |
| R9 | **MET.** `do_POST` route literals = HEAD's 13 in HEAD's order + `/api/realtime/mic` exactly once (14); `do_GET` still 8. Through the real `web_panel.build_runtime` with no `audio:` key: `type(gateway) is BrowserAudioGateway`, `kind == "browser_audio"`, `store.section("audio") == {}` |
| R10 | **MET.** With every `CARD HW-MIC` block stripped, `startMic` → `06bf8086…`, `renderRealtime` → `3f80f97b…`, `stopMic` → `ca299601…` — HEAD's shas |
| R11 | **MET.** Three fenced UI blocks; the branch text carries `/api/realtime/mic`, `=== "array"`, `state.arrayMic`, `ear: array`, `state.realtime.gateway.kind`; zero occurrences of `getUserMedia` / `openAudioSocket` / `AudioContext` in its CODE (comment lines dropped first — see D2) |
| R12 | **MET, REAL ARRAY.** Below |
| R13 | **MET.** `ruff check` clean on `web_panel.py` and the new test; `ruff format --check` clean on the new test; **zero `noqa` directives added** (`grep -c noqa` on the new file = 0, and none in either fenced region). Repo-wide fingerprints **8 = the 7 baseline + `src/parcel_robot/backends/go2.py::I001`**, which is HW-2's in-flight file — **0 new from this card**. `ruff format --diff` puts the file's four remaining hunks at 452, 520, 694 and 863 — none inside 348:437 or 585:605; the first three are HEAD's own (`ruff format --diff` on `git show HEAD:…web_panel.py` gives the same three at 362/430/587) and 863 is inside HW-2's region |
| R14 | **MET.** `test_hwmic_arm_route.py` + `test_web_panel.py` + `test_hw4_array_gateway.py` + `test_realtime_audio_gateway.py` + `test_duplex1_panel_duck.py` + `test_mark1_browser_ear.py` → **139 passed** (16.6 s). Nothing that passed before this card fails after it |
| R15 | **MET.** OWNS diffstat above; HW-MIC markers in exactly three files; `list_parcel_procs.py` clean; 0 pytest processes; no lock held |

### R12 — the real array, through the real route

```bash
source scripts/env-audio.sh
env -u TMPDIR timeout -k 5 90 .parcel/bin/python ~/.cache/parcel-hwmic/arm_10s.py
```

Result (`~/.cache/parcel-hwmic/arm_10s.json`):

| what | value |
|---|---|
| built by | `web_panel.build_runtime` with a REAL profile overlay `robot.hwmicarray.yaml` = `{audio: {gateway: array}}`, `$PARCEL_PROFILE=hwmicarray`, `mode: audio` |
| gateway | `ArrayAudioGateway`, `kind` `"array"`, PortAudio device **4** = `reSpeaker XVF3800 4-Mic Array: USB Audio (hw:1,0)` |
| arm | `POST /api/realtime/mic {"open": true}` → **200 `{"open": true, "kind": "array"}` in 19.9 ms** |
| ear | **250 frames, every one 1,920 B**, 480,000 B = **10.000 s @ 24 kHz** in 10.003 s wall = **24.99 fps** |
| errors | `capture_errors 0`, `frames_dropped_capture_overflow 0`, `frames_dropped_unarmed 0`, `deaf_warnings 0`, `playback_underruns 0`, sink errors `[]` |
| the amplifier | `frames_out 0`, `bytes_out 0`, `silence_clock_frames 250` — the playback stream ran as the capture clock (HW-4 F1) and played nothing but zeros |
| **F5 on hardware** | `ensure_session` called **once**, `mic_gesture=True`, with a handshake token, and `input_stream_open` was already **true** at the call |
| disarm | `POST {"open": false}` → **200 `{"open": false, "kind": "array"}`**; after teardown `running false`, `connected false`, `mic_open false` |
| cost | **$0.** `PARCEL_REALTIME_KEY_ENV` unset; the runtime logged "no realtime credential in $OPENAI_API_KEY; the lane will not arm"; `ensure_session` was stubbed at the lane boundary and returned `"hwmic-stub-session"` |

The ONLY stub in that run is `RealtimeLane.ensure_session`. Everything between
the socket and it is the product: `do_POST`, `_authorize_post`, the panel token
handshake (`RuntimeHTTPServer.__init__` → `runtime.bind_panel_token`),
`ArrayAudioGateway.set_mic`, `_open_capture`, the reader thread,
`RobotRuntime._realtime_mic_gesture`. `on_audio` is TAPPED, not replaced: the
counter calls `runtime._realtime_owner_audio` and records what it raises (it
raised nothing).

### Seeds — one per guard, on an import-verified scratch

Scratch `~/.cache/parcel-hwmic/scratch` = `rsync -a --exclude .cache --exclude
.parcel --exclude .git src scripts tools tests configs prompts` (six
directories, 75 MB, never the whole repo); run with
`PYTHONPATH=<scratch>:<scratch>/src`;
`python -c "import parcel_robot; print(parcel_robot.__file__)"` →
`…/parcel-hwmic/scratch/src/parcel_robot/__init__.py`, i.e. inside the
scratch. Control run before seeding: 15 passed. Every file restored by sha256
and re-verified `SAME` against the working tree afterwards; `__pycache__`
purged before and after each. The scratch was deleted at close; the harness
that builds and drives it (`~/.cache/parcel-hwmic/seed.sh`, six lines of
rsync in the paragraph above) and the real-array script
(`~/.cache/parcel-hwmic/arm_10s.py` + `arm_10s.json`) are kept.

| seed | mutation | row | result |
|---|---|---|---|
| S1 | route arm answers before `_authorize_post()` | R1 | **RED** (1 failed) |
| S2 | browser gateway falls through to `set_mic` instead of 409 | R2 | **RED** |
| S3 | HW-4's `set_mic` order inverted (`on_mic` before `_open_capture`) | R4 | **RED** — see D1 |
| S4 | `want_open = bool(payload.get("open"))` | R7 | **RED** |
| S5 | the `CARD HW-MIC` branch deleted from `startMic()` | R11 | **RED** |
| S6 | a second new route literal added to `do_POST` | R9 | **RED** |
| S7 | `let stream;` → `let stream = null;` in the browser branch (one token) | R10 | **RED** |

S7 is beyond the six pre-registered seeds: R10 is a guard and the six did not
include one that reddens it. Declared as an addition, not a substitution.

## What this does not prove

* **No browser ran.** R10/R11 are text and hash pins; no JS engine executed the
  new branch (MARK-1's `gjs` harness exists and is deliberately not claimed).
  A verifier who wants the UI half proved by execution should lift `startMic`
  into `gjs` with a stubbed `fetch`, the way `test_mark1_browser_ear.py` does.
* **No hosted session was ever opened**, so nothing here shows the lane doing
  anything useful with array PCM — only that the PCM reaches `on_audio` at the
  right rate and size. HW-4's O1 is still the row that proves the round trip.
* **Nothing was measured on the Orin** (class NEW; DESIGN §e). The route is
  venue-independent by construction, but the array's duplex clocking behaviour
  on aarch64/PipeWire is untested and unclaimed.
* **No sustained run.** 10 s, once. No drift, no thermal, no unplug-mid-session
  (HW-4's own N-new about teardown errors escaping `set_mic(False)` is
  untouched by this card and would surface through this route as a 500).
* The 409 for `GatewayNotRunningError` comes from `do_POST`'s pre-existing
  exception ladder, not from code this card wrote; if that ladder changes, the
  route's status code changes with it. The test pins the status, not the
  mechanism.

## Deviations, declared

**D1 — my own R4 was self-satisfying, and the seed caught it.** The first
version kept the gesture in its own list and asserted `audio.events + order ==
["output", "input", "on_mic"]`, which is true no matter what order things
happened in. Seed S3 (F5 inverted) **passed** against it. Fixed by writing the
gesture into the device's own event log so the sequence is a real sequence;
S3 then went RED. The defective version never left this session, but it is
exactly the "a test that passes against a stub door" failure the wave-2 audit
names, and it is recorded rather than quietly repaired.

**D2 — R11 reads code, not comments.** The first version asserted
`"getUserMedia" not in <the fenced region>` and failed on my own comment
explaining that `getUserMedia` is not called. The assertion now drops `//`
lines first. A verifier should know the guard is weaker by exactly that much:
a `getUserMedia` call hidden on a line that starts with `//` would pass, which
is not a call.

**D3 — two fenced regions in `web_panel.py`, not one.** The dispatch says "ONE
marked `CARD HW-MIC` region". The route is one contiguous region
(348–437); the 404-text correction lives in a different method
(`_serve_realtime_audio`, 585–605) and cannot be contiguous with it. Both are
fenced and both are named `CARD HW-MIC`. The same is true of the UI: three
fenced blocks (`startMic` branch, the label constant beside the other
`MIC_LABEL_*`, the status-line entry) rather than one.

**D4 — `state.arrayMic` is not declared in the `state` object literal.** It is
set inside the fenced branch instead, because touching the literal would break
R10's byte-identity pin on the browser half for no behavioural gain (an absent
property is already falsy).

**D5 — the real-array runs wrote session directories** under the repo's
gitignored `recordings/`: the runtime arms its EV-1 evidence log at
construction and that path is not env-overridable. `git status` stays clean.
All of mine (identified by my run path inside their `events.jsonl`) were
removed at the close of the correction pass, matching the verifier's N6.
The owner's `parcel_memory.sqlite3` and spend ledger were redirected into
`~/.cache/parcel-hwmic/run/` and never opened where they live.

**D6 — this status doc was written at the end**, not incrementally. The
command ledger is reconstructed from `~/.cache/parcel-guard/guard.log`
(14 runs, quoted above) and from `~/.cache/parcel-hwmic/arm_10s.json`, both of
which are on disk and auditable; nothing is reconstructed from memory.

**D7 — DESIGN.md is 152 lines** against a 150-line target.

## Owner-gated rows

None new. **HW-4's O1 is now unblocked** — the through-air TV-on session
(1.3 h, AIR-1's ≤ 2 % false-barge-in row) can be run with the array as the ear,
because the panel can finally arm it. The owner's route, once a credential is
in place:

```bash
# 1. the profile that fits the array ear (HW-5 owns the physical profile file)
printf 'audio:\n  gateway: array\n' > configs/robot.<profile>.yaml
# 2. the duplex check that this device actually needs (arecord ALONE is not one)
timeout -k 3 15 bash -c 'aplay -q -D hw:1,0 -f S16_LE -c 2 -r 16000 /dev/zero & AP=$!; \
  sleep 0.3; arecord -D hw:1,0 -f S16_LE -c 2 -r 16000 -d 3 /tmp/duplex.wav; kill $AP'
# 3. start the stack, open the panel, click the microphone button — it now says
#    "🔴 Listening · mic array · click to stop" and the status line says "ear: array"
```

## Handoffs

* **HO-1 (HW-4, or whoever owns `audio_gateway.py`):** the two gateways
  disagree about their own name — `BrowserAudioGateway.snapshot()["kind"]` is
  `"browser_audio"` while `ArrayAudioGateway`'s is `"array"` (=
  `AUDIO_GATEWAY_ARRAY`, the config value). This route and the UI branch on
  `"array"` and treat everything else as the browser, which is the fail-safe
  direction, but a third gateway would need this settled. There is no
  `gateway.kind` attribute; `snapshot()["kind"]` is the only source.
* **HO-2 (UI owner):** the array ear has no "the runtime closed my microphone"
  path. `close_mic` (an idle hang-up) shuts the device without telling the tab,
  so the button can read "Listening" while the ear is shut. The browser ear
  learns this from a `mic` frame on its socket; the array ear would learn it
  from `/api/state`'s `realtime.gateway.mic_open` on the next poll. Two lines
  in `renderRealtime`, and out of this card's scope because it changes the
  browser half's function body.
* **HO-3 (HW-5):** the physical profile should carry `audio: {gateway: array}`
  so the Orin boots with the ear fitted; the key is HW-4's and introducible.
* **HO-4 (integrator):** this card's `web_panel.py` hunks are disjoint from
  HW-2's in the same file but they are in the same file — land them together
  or rebase carefully; `ui/index.html` is otherwise untouched by wave 3.

## Resumed from

Nothing. First dispatch of this card; no prior executor's work existed in the
tree (`scrum/20260822/task_44/` contained only `README.md`).

---

# Correction pass — 2026-08-23 15:21–15:35 local (19:2x EDT dispatch clock)

Against `~/.cache/parcel-verify/hwmic/VERDICT.md` (**ACCEPT-WITH-NOTES**, one
FIX). **F1 closed on the real array; N1 applied; N3 recorded; N2/N4/N7 carried
as notes. 17/17 rows MET** (the 15 pre-registered + R16, the new concurrency
row, + the R12 re-run).

## F1 — concurrent arms corrupt the ear. Closed at the route and in the tab.

The verifier reproduced, on the XVF3800, what one double-click does: two
simultaneous `{"open": true}` POSTs → first **200**, second **503** (PortAudio
`-9985` on the second playback open), and the second's `except
ArrayDeviceError` arm wrote `_mic_open = False` over the first's armed state.
For two seconds: both endpoints `Running`, the session gesture fired, the panel
told `open: true`, and **0 frames reached `on_audio`** — every one dropped as
unarmed. A billed, "Listening", deaf ear.

Two changes, both inside OWNS:

1. **`web_panel.py`, a third fenced `CARD HW-MIC` region at 41–69**: a
   module-level `_ARRAY_MIC_ROUTE_LOCK = threading.Lock()`, taken in the route
   around the whole `set_mic` call (`with _ARRAY_MIC_ROUTE_LOCK:` at 419–422) —
   the close as well as the open, because a close racing an open is the same
   corruption with the operands swapped. The second caller waits, then finds
   `_mic_open` true and is answered **200 with the state that holds**, never a
   503 over a live ear. Process-wide rather than per-server: there is one array
   on a machine, and two panels sharing one lock is strictly safer than two
   panels racing one sound card. It is held only around `set_mic` — never while
   the handler touches a socket — and nothing under `set_mic` calls back into
   the panel, so it cannot deadlock.
2. **`ui/index.html`, inside the existing `startMic` fence**: a re-entry guard.
   `state.arrayMicBusy` plus `micButton.disabled`, released in a `finally` so a
   thrown POST does not need a reload to retry. The old code set the label to
   "Connecting…" and left the button live while `state.arrayMic` was still
   false, which is exactly how the second click got sent.

**The in-gateway fix is HW-4's and is handed over, not copied here** (HO-5
below): `ArrayAudioGateway.set_mic` should carry an "opening" state under its
own lock so `set_mic`/`close_mic` cannot interleave from any caller. The route
lock closes the only product-reachable trigger; it does not make the gateway
re-entrant.

## The race on the REAL array, after the fix

```bash
source scripts/env-audio.sh
env -u TMPDIR timeout -k 5 150 .parcel/bin/python ~/.cache/parcel-hwmic/arm_and_race_10s.py
```
(`~/.cache/parcel-hwmic/arm_and_race_10s.json`; `PARCEL_REALTIME_KEY_ENV` and
`OPENAI_API_KEY` both asserted absent in-script, `lane._transport_factory is
None`, `ensure_session` stubbed at the lane boundary, `lane.session_id` still
`None` at the end. $0. Only zeros to the DAC.)

**Phase 1 — R12 re-run through the changed route (10 s):** arm **200
`{"open": true, "kind": "array"}` in 14.0 ms**; **249 frames, every one
1,920 B = 9.96 s @ 24 kHz in 10.0 s (24.9 fps)**; `capture_errors 0`,
`frames_dropped_unarmed 0`, overflow 0, `deaf_warnings 0`; `frames_out 0`,
`bytes_out 0`, `silence_clock_frames 250`; disarm **200 `{"open": false}`** in
15.3 ms; `mic_open false`, `connected false`, `mic_opens 1`.

**Phase 2 — the two simultaneous POSTs (barrier-released threads):**

| | before the fix (verifier) | after the fix (this run) |
|---|---|---|
| responses | `200 {"open": true}` + **`503` PortAudio −9985** | **`200 {"open": true, "kind": "array"}` ×2** (19.4 ms / 19.7 ms; both arms done in 20.4 ms) |
| `mic_open` after both | **`False`** (the 503 clobbered the live ear) | **`true`** |
| device opens | second refused, first's clock closed | **`mic_opens` +1, one gesture, `device_refusals 0`** |
| frames to `on_audio` in the next 2 s | **0** (all dropped unarmed) | **49 × 1,920 B**, `frames_dropped_unarmed 0` |
| after `{"open": false}` | — | 200, `mic_open false`, `connected false`, both streams closed |

Final gateway snapshot: `running false`, `connected false`, `mic_open false`,
`frames_in 300`, **`frames_out 0`, `bytes_out 0`**, `capture_errors 0`,
`device_refusals 0`, `silence_clock_frames 300`; `sink_errors []`; both
`ensure_session` calls (one per phase) recorded `input_stream_open: true`, so
F5's ordering held on every arm.

## Rows added / re-run

| row | result |
|---|---|
| **R16 (new)** | **MET.** Two barrier-released threads POST `{"open": true}` through the real handler with the fake device and a 300 ms `on_mic`: **both 200 `{"open": true, "kind": "array"}`**, `len(input_streams) == 1`, `len(output_streams) == 1`, `mic_opens == 1`, one gesture, `mic_open is True`; then `{"open": false}` → 200 and both streams `closed` — nothing leaked |
| R11 | **MET, extended.** 4 fenced UI regions (was 3); the text now also pins `state.arrayMicBusy`, `micButton.disabled = true/false` and `realtime.gateway.mic_open === false` |
| R10 | **MET, unchanged pins.** `startMic` `06bf8086…`, `renderRealtime` `3f80f97b…`, `stopMic` `ca299601…` — the N1 block and the re-entry guard are both inside fences, which the pin strips, so the browser half is still HEAD's to the byte |
| R12 | **MET, re-run** — phase 1 above (249 frames / 9.96 s vs the first pass's 250 / 10.000 s) |
| R13 | **MET.** `ruff check` clean; `ruff format --check` "1 file already formatted"; **0 `noqa`** in the test and in all three `web_panel.py` fences. Repo-wide fingerprints **9 = the 7 baseline + 2 in `tests/test_hw7_gate_aarch64.py`** (`PLR1711`, `RET501` — HW-7's in-flight file; HW-2's `go2.py::I001` has cleared). **0 new from this card.** `ruff format --diff` hunks at 485/553/727/896 — none inside 41–69, 378–470 or 618–638 |
| R14 | **MET.** The same six suites: **140 passed** (17.3 s) — 139 + R16 |
| R15 | **MET.** `git status --porcelain` for my files, before and after this pass, is unchanged in shape: ` M src/parcel_robot/ui/index.html`, ` M src/parcel_robot/web_panel.py`, `?? scrum/20260822/task_44/`, `?? tests/test_hwmic_arm_route.py`. `git diff --stat`: `web_panel.py` +241/−2 (HW-MIC 141/1 at hunks 41/378/618/627/638, HW-2 100/1 at 839/965), `index.html` +89 (four hunks, all mine). `grep -c 'HW-MIC'` on the diffs of `audio_gateway.py` / `runtime.py` / `config.py` / `lane.py` = **0** each |

## Seeds for the new guards (same import-verified scratch discipline)

Scratch rebuilt (`rsync` of the six directories, 76 MB), `parcel_robot.__file__`
inside it, control run **16 passed**, every file restored by sha256 and
re-verified `SAME` against the working tree, `__pycache__` purged.

| seed | mutation | row | result |
|---|---|---|---|
| **S8** | the `with _ARRAY_MIC_ROUTE_LOCK:` line dropped from the route | R16 | **RED** — `AssertionError: one ear, one device open / assert 2 == 1` (two input streams, i.e. F1's shape (a) verbatim) |
| **S9** | the `state.arrayMicBusy` / `disabled` guard deleted from `startMic` | R11 | **RED** |
| **S10** | the N1 poll-correction block deleted from `renderRealtime` | R11 | **RED** |
| S7 (re-run) | `let stream;` → `let stream = null;` in the browser branch | R10 | **RED** — the byte-identity pin still bites after a fence was added inside `renderRealtime` |

## N1 — a runtime-closed ear now shows

Two lines (plus their comment) in a new fence inside `renderRealtime`: when the
snapshot says `kind === "array"` and `gateway.mic_open === false` while the tab
still thinks it is armed, `state.arrayMic` is cleared and the button returns to
"🎙 Enable microphone". `RobotRuntime.close_mic` (the idle hang-up) is the case
that motivated it; the same line is also the self-correction for N2 (a POST
that the tab's 4,500 ms `api()` timeout abandoned while the server finished
arming) and for anything else that leaves the label and the device disagreeing.
R10 stays green **by construction**: the pin strips fenced lines before hashing.

## N3 — the lock ledger

`~/.cache/parcel-hwmic/lock_ledger.txt`, from this pass on:

```
2026-08-23 15:21:45 TAKE    lock-web_panel.py  HW-MIC correction pass F1 (route lock)
2026-08-23 15:28:37 RELEASE lock-web_panel.py  (route lock landed; ruff + 140 tests green)
```

The first pass's take/release (14:44:52 / 14:55:xx, one Edit pass covering both
`web_panel.py` regions) was not logged at the time and is reconstructed from
the `owner` file's mtime — recorded as such, not as a measurement. First-pass
guard count corrected to **15**; this pass added **10** more (all paired, 0 ×
rc=137), **25** total.

## Notes carried, and handoffs added

* **N2 (carried, not fixed):** with a real credential the arm POST holds the
  hosted handshake synchronously and `api()` aborts at `API_TIMEOUT_MS = 4500`.
  The tab would then show "Enable microphone" over an ear that armed. Not
  reproducible here (no key; my arms take 14–20 ms). N1's poll repairs the
  label within one `/api/state` cycle; making the route itself asynchronous
  would be a design change, not a correction.
* **N4 (carried):** `ArrayAudioGateway.set_mic(False)` never calls
  `on_mic(False)` while the browser gateway's does. R6 pins the asymmetry.
  HW-4's file — **HO-6**.
* **N7 (carried):** the verifier confirmed the route cannot reach the network
  without a credential even unstubbed (`transport_factory None` →
  `CODE_NO_TRANSPORT` → `RealtimeLaneError` → `set_mic` closes and returns
  False → 200 `{"open": false}`). The lane stub exists to count calls and
  record order, not to prevent spend.
* **HO-5 (new, to HW-4's owner):** give `ArrayAudioGateway` an "opening" state
  under its own lock. `set_mic` reads `_mic_open` under the lock, opens the
  duplex pair and calls `on_mic` outside it, and writes `_mic_open = True` only
  at the end; `_ensure_output`'s "already open" check has the same unlocked
  window. The route lock closes the only product-reachable trigger, but any
  future caller — a CLI, a second panel process, a test harness — walks back
  into it. The verifier's `verify_negatives.py` cases 4/5 are the reproduction.

## Close of the correction pass

Final shas after the pass: `web_panel.py` `371c043c…`, `ui/index.html`
`de0a89f3…`, `tests/test_hwmic_arm_route.py` `78daf1e2…` (the first pass's
`b330c612…` / `f6e4c9fd…` / `1cb8272a…` are superseded; the verifier's
`scratch_sha.txt` records the pre-correction trio). Nothing of mine is running
or open at close: 0 pytest processes of mine (HW-5's peer run was live and was
never touched), no lock directory, no sim, `/proc/asound/card1/pcm0c/sub0/
status` → `closed`, no PCM holders, scratch deleted, `recordings/` clean. The
owner's `parcel_memory.sqlite3`, `:8765` and `/tmp/parcel_sim.sock` were never
opened.
