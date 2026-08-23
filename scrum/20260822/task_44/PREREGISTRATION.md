# HW-MIC `array-arm-route` (task_44) — PREREGISTRATION

Written BEFORE any code or measurement, 2026-08-23 ~17:3x EDT, against
`DESIGN.md` (same folder). Rows are measured exactly as written; a row that
cannot be run as written is MISSED with the reason, never rewritten.

Standing constraints for every row: every `pytest` goes through
`~/.cache/parcel-guard/pytest_guard.sh --label hwmic` with `env -u TMPDIR`,
foreground, never `-n auto`, never `scripts/ci_gate.py --tier`; pre-flight
`free -g` available ≥ 120 and `ps -eo args | grep -c '^[^ ]*python[^ ]* -m
pytest'` ≤ 1; no sim; `tests/test_voice_nav_e2e.py` is never run; git stays
read-only; `PARCEL_REALTIME_KEY_ENV` unset for every row (hosted spend $0).

## Pins taken before the first edit (so "byte-identical" has a referent)

| pin | value |
|---|---|
| P1 | `src/parcel_robot/ui/index.html` sha256 `aa70ea860fe0c23915477b96a432e6f88bb93a5ced81ebb8c99b865955ed80ac` — identical at HEAD, in the index, and in the working tree |
| P2 | `src/parcel_robot/web_panel.py` HEAD == index sha256 `2e9e0182d09f71b9c2d186c7b11ad81fddd234467fe9ea9e70cdedf34aa3c339`; working tree `c01af42b…` (HW-2's in-flight region) |
| P3 | `startMic()` body sha256 `06bf808620d951a2e0226f79cded2a314f57e1620459df895ddb39fc6cc5d560` (4,630 bytes) |
| P4 | `renderRealtime(realtime)` body sha256 `3f80f97b82ec3f9e8371c34762857d2b6b810574565976442cb6f236b8d5ca8d` (1,944 bytes) |
| P5 | `stopMic(reason)` body sha256 `ca299601266160133f66b638c7f4f02654ae22cc70df7aed2dcaba633bdfe410` (1,067 bytes) |
| P6 | `do_POST` route literals at HEAD, in order: `/api/command`, `/api/voice/text`, `/api/realtime/text`, `/api/voice/barge-in`, `/api/motion`, `/api/action`, `/api/pose-review/run`, `/api/owner`, `/api/personality`, `/api/prompt/fact`, `/api/evals/run`, `/api/evals/batch`, `/api/evals/select` (13); `do_GET` route literals: 8 |

## Rows

Unless a row says otherwise the command is

```
env -u TMPDIR ~/.cache/parcel-guard/pytest_guard.sh --label hwmic \
  .parcel/bin/python -m pytest tests/test_hwmic_arm_route.py -q
```

and the threshold is "the named test passes; the whole file passes".

| row | claim | command | threshold |
|---|---|---|---|
| **R1** | An unauthorised POST is refused and reaches nothing. No token, wrong token, and a cross-origin `Origin` each → **403**; `set_mic` recorded **0** calls; no stream opened | the file's `test_an_unauthorised_arm_is_refused_before_the_gateway` | 3 × 403, `set_mic` calls == 0, `audio.input_streams == []` |
| **R2** | A browser ear refuses this door **409** and the text names the socket | `test_a_browser_ear_refuses_this_route_and_names_the_socket` | status 409; `detail` contains `/api/realtime/audio`; `kind == "browser_audio"`; the browser gateway's `set_mic` never called |
| **R3** | An array ear arms: **200**, body exactly `{"open": true, "kind": "array"}`, `set_mic(True)` called **once** | `test_the_array_ear_arms_through_the_route` | body == `{"open": True, "kind": "array"}`; one `set_mic` call with `True`; `gateway.mic_open is True`; one input stream and one output stream open |
| **R4** | HW-4's **F5 ordering holds through the route**: the device is open before the session gesture | `test_the_device_is_open_before_the_session_gesture` | at the moment `on_mic(True)` fires, `len(audio.input_streams) == 1` and that stream `.started is True` and `len(audio.output_streams) == 1`; recorded order == `["output", "input", "on_mic"]` |
| **R5** | A refusing device → **503**, `on_mic` **never** called, no session | `test_a_refused_device_answers_503_and_opens_no_session` | status 503; `detail` names the udev rule (`99-respeaker-xvf3800.rules`); `on_mic` calls == `[]`; `mic_open is False` |
| **R6** | `{"open": false}` closes: **200** `{"open": false, "kind": "array"}`, both streams closed | `test_the_route_closes_the_ear_again` | body `open` is False; input stream `.closed is True`; output stream `.closed is True`; `mic_open is False` |
| **R7** | A missing or non-boolean `open` is a **400** and reaches nothing | `test_a_missing_or_wrong_typed_open_is_a_400` | `{}`, `{"open": "yes"}`, `{"open": 1}` → 400 each; `set_mic` calls == 0 |
| **R8** | No gateway (mode: text) → **404** naming the mode | `test_a_runtime_with_no_gateway_answers_404` | status 404; `kind` is `null` |
| **R9** | **Flag-off identity.** With `audio.gateway` absent the panel's route table is HEAD's plus exactly one entry, and the runtime still builds the browser gateway | `test_the_route_table_is_heads_plus_exactly_this_one_route` and `test_with_no_audio_key_the_panel_still_builds_the_browser_ear` | POST literals == P6's 13 with `/api/realtime/mic` inserted once (14 total, the other 13 in P6's order); GET literals == 8, unchanged; `type(runtime.realtime_gateway) is BrowserAudioGateway` through the real `web_panel.build_runtime` |
| **R10** | **The browser UI path is byte-identical.** Strip every `CARD HW-MIC` fenced block from `ui/index.html` and the three functions hash to their pins | `test_the_browser_half_of_the_panel_is_byte_identical` | sha256 of `startMic` == P3, `renderRealtime` == P4, `stopMic` == P5, after removing lines from each `---- CARD HW-MIC` marker through its `---- END CARD HW-MIC` marker inclusive |
| **R11** | **The UI branch exists and is array-only**: the fenced region posts `/api/realtime/mic`, and the browser branch is unreachable for `kind === "array"` | `test_the_panel_arms_the_array_over_the_route_not_the_socket` | the region's text contains `"/api/realtime/mic"`, `state.arrayMic`, `ear: array`; `getUserMedia`/`openAudioSocket` appear **0** times inside the fenced region |
| **R12** | **REAL ARRAY, through the route.** One 10 s arm: panel handler in-process, real `ArrayAudioGateway`, real XVF3800, hosted session stubbed at the lane boundary; frames counted at `on_audio` | `env -u TMPDIR timeout -k 5 60 .parcel/bin/python ~/.cache/parcel-hwmic/arm_10s.py` (script written before the run; its source goes in the status doc) | POST 200 `{"open": true, "kind": "array"}`; **≥ 200** frames at `on_audio` in 10 s (HW-4 measured 25 fps ⇒ ~250 at 40 ms); every payload 1,920 B; `capture_errors == 0`; `bytes_out == 0` and `frames_out == 0` (only silence to the DAC); `lane.ensure_session` called exactly once **after** the streams opened; POST `{"open": false}` → 200, both streams closed, `tools/list_parcel_procs.py` clean afterwards |
| **R13** | **Lint.** `ruff check` clean on the three OWNS files; the repo-wide fingerprint ratchet gains none; `ruff format --check` clean on the new test file | `.parcel/bin/ruff check src/parcel_robot/web_panel.py src/parcel_robot/ui/index.html tests/test_hwmic_arm_route.py` (html skipped by ruff) and `.parcel/bin/ruff format --check tests/test_hwmic_arm_route.py` and `.parcel/bin/python scripts/ci_gate.py --ruff-ratchet` if that flag exists, else the in-process fingerprint compare against `scripts/ci_ruff_baseline.json` | 0 errors; **0** `noqa` directives added; new fingerprints == 0 |
| **R14** | **Neighbours stay green.** The panel's own suite and the realtime gateway suites | `env -u TMPDIR ~/.cache/parcel-guard/pytest_guard.sh --label hwmic .parcel/bin/python -m pytest tests/test_web_panel.py tests/test_hw4_array_gateway.py tests/test_realtime_audio_gateway.py tests/test_duplex1_panel_duck.py tests/test_mark1_browser_ear.py -q` | no test that passed before this card fails after it; any pre-existing failure is quoted and attributed |
| **R15** | **OWNS discipline.** `git diff --stat` (index→tree) touches only this card's files beyond what was already dirty | `git diff --stat -- src/parcel_robot/web_panel.py src/parcel_robot/ui/index.html` and `git status --porcelain` | `web_panel.py` diff = HW-2's existing hunks + this card's fenced hunks only; `audio_gateway.py`, `lane.py`, `runtime.py`, `config.py` untouched by me |

## Seeds — one per guard, on an import-verified scratch copy

The scratch is built with
`rsync -a --exclude .cache --exclude .parcel --exclude .git src/ scripts/ tools/ tests/ configs/ prompts/`
into `~/.cache/parcel-hwmic/scratch/`, run with
`PYTHONPATH=<scratch>:<scratch>/src`, verified by
`python -c "import parcel_robot; print(parcel_robot.__file__)"` printing a path
INSIDE the scratch, restored by sha256 after each seed, `__pycache__` purged.

| seed | mutation | must redden |
|---|---|---|
| **S1** | delete the `self._authorize_post()` guard's effect for this route (move the route arm above the prologue) | R1 |
| **S2** | answer the browser gateway with 200 + `set_mic` instead of 409 | R2 |
| **S3** | invert HW-4's F5 order in the scratch's `set_mic` (call `on_mic` before `_open_capture`) | R4 |
| **S4** | accept a truthy `open` (`bool(payload.get("open"))`) instead of the strict boolean | R7 |
| **S5** | delete the `CARD HW-MIC` branch from `startMic()` in the scratch's `index.html` | R11 |
| **S6** | add a second new route literal to `do_POST` | R9 |

## Owner-gated / not claimed

* HW-4's O1 (the 1.3 h through-air TV-on session) is NOT this card's row and is
  not claimed; R12 unblocks it, nothing more.
* No browser/JS-engine execution row (`gjs`) is claimed: R10/R11 are text pins.
* The Orin is not measured (class NEW; §e).
