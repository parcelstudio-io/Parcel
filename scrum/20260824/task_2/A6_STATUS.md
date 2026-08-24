# A6 STOP-LOCAL — executor register (Opus) · 2026-08-24

**Card**: `IMPLEMENTATION_PLAN.md` lane A row A6, bound to Addendum **A2** (the
gate exists because spoken STOP is cloud-only today — `realtime/lane.py:47-53`)
and Addendum **A9** (tail bars p95 ≤ 800 ms AND n ≥ 60 all ≤ 1.0 s; ≤ 1 false
STOP / 24 h; "STOP bypasses every gate"), built on VOICE-GATE v2's measured
evidence. **Not committed. Git read-only throughout.**

## What shipped

| file | what |
|---|---|
| `src/parcel_robot/audio/stop_hotword.py` (new, 621 lines) | the whole path as a leaf: the grammar (`spot_stop`), the knob (`StopHotwordConfig`), the streaming spotter (`StopHotwordSpotter`), the dedicated thread (`StopHotwordWatch`), the capture-rail tee (`StopTappedVoiceLoop`) |
| `src/parcel_robot/runtime.py` (5 hunks, +140/-1) | `_build_stop_hotword` / `_stop_hotword_bare_window` / `_stop_hotword_latched` / `_stop_hotword_failed`; construction beside the mic rail; start; close; one constant (`STOP_HOTWORD_STT_TIMEOUT_S`) |
| `src/parcel_robot/config.py` (+4 lines) | `"stop_hotword"` on `OVERLAY_INTRODUCIBLE_KEYS`; without it the SHA-locked base makes the knob unreachable (ROAM-1 finding 6) |
| `tests/test_a6_stop_local.py` (new, 52 rows) + `tests/data/a6_stop_local.json` (150 KB) | the proof; the fixture is every ASR window the real spotter asked for on the VOICE-GATE tapes, each with the wall time its transcription actually took |

`core/hard_stop.py`, `finalize_command`, `safety.py`, `core/arbiter.py`,
`control/`, `web_panel.py` and every safety floor: **untouched** — this card
CALLS the latch, it does not change it. **No new lock** (the watch owns a
`queue.Queue`; r24's lock graph and `PINNED_LOCK_ORDER` are unchanged). **Zero
`noqa`. Zero new `# ---- CARD` markers. Zero new ruff fingerprints.**

`audio/voice_loop.py` is deliberately **byte-unchanged**: the tee is a subclass
(`StopTappedVoiceLoop`, overriding `_handle_frame`) rather than an edit, because
that module sits one line under DEC-0's 1 000-line ceiling. The seam is asserted
by test (`test_the_tapped_loop_still_has_the_seam_it_overrides`) so a rename
cannot silently deafen it.

## The knob

`stop_hotword:` — defaults live in code, an absent section is the shipped
default, and unknown keys / unknown modes are refused **by name** at the read
site (`StopHotwordConfig.from_mapping`), which is `roam`'s pattern exactly.

| key | default | note |
|---|---|---|
| `mode` | **`name_prefixed`** | the owner-flagged default. `hybrid`, `bare`, `off` all implemented |
| `name` | `parcel` | no product surface carried the dog's name (grepped: personality files name a POLICY). Non-empty is **validated** for `name_prefixed`/`hybrid` |
| `window_s` / `cadence_s` / `close_frames` | 1.6 s / 0.30 s / 3 | window holds "<name>, stop"; the cadence is a FLOOR — the spotter paces sweeps by what its transcriber costs; `close_frames` is the speech-offset trigger |
| `name_gap_words` | 3 | how far the name may sit from the stop word, either side |
| `relatch_holdoff_s` | 2.0 s | one utterance latches once |

Stop words are **not copied**: `STOP_PHRASES` is derived from
`closed_intent_phrases(ClosedIntent.STOP)` (U33's lesson). `freeze` is PAUSE in
this product and is therefore *not* a stop, unlike the research harness.
`off` builds **no matcher, no VAD, no thread**, and the rail is constructed as
the plain `MicrophoneVoiceLoop` — both branches proven.

## Tail bars — utterance end → latch engaged

Tier `replay`: the REAL matcher over the REAL ASR windows the REAL spotter
produced streaming the VOICE-GATE tapes (whisper.cpp `base.en` resident on
loopback; median ASR **369 ms**, mean 394 ms). A9 bar: **p95 ≤ 800 ms AND
n ≥ 60, all ≤ 1.0 s.**

| grammar | tape | n | latched | recall | p50 | **p95** | max | >1.0 s |
|---|---|---|---|---|---|---|---|---|
| **`name_prefixed` (SHIPS)** | synthetic name tape (piper, 4 rates × 4 phrasings × 4 cells) | 64 | 60 | 0.938 | 446 ms | **608 ms** | 633 ms | **0** |
| `bare` | same synthetic tape | 64 | 63 | 0.984 | 436 ms | 608 ms | 649 ms | 0 |
| `bare` | **recorded VOICE-GATE stop tape** | 64 | 55 | 0.859 | 566 ms | **785 ms** | 1 937 ms | 2 |
| `name_prefixed` | recorded espeak tape (F3b proxy) | 64 | 4 | 0.062 | 617 ms | 668 ms | 674 ms | 0 |
| *research reference (harness)* | *recorded stop tape* | *64* | *56* | *0.875* | *349 ms* | *935 ms* | *979 ms* | *0* |

* **The shipped configuration meets both A9 tail bars.** The gain over the
  research reference (935 → 608/785 ms p95) is one design change: the reference
  swept on a free-running 300 ms cadence; this path also checks at the **VAD
  speech-offset edge**, which is where a hotword actually ends.
* **The two > 1.0 s trials are the transcriber, not the path**, and the test
  asserts that mechanism rather than waiving it: both winning windows are ones
  `whisper.cpp` itself took **1.54–2.32 s** on (median 369 ms). The product's
  own `STOP_HOTWORD_STT_TIMEOUT_S = 2.0 s` would have abandoned them.
* **Recall is not a bar this card claims.** 55/64 vs the reference's 56/64 on
  the bare tape is the deliberate cost of self-pacing (which bought the tail and
  makes it impossible for the spotter to fall behind a talker). The A6 row in
  RESULTS' table wanted ≥ 0.99; nothing here reaches it, and every recorded miss
  is at 3 m, 30–60° off axis — the geometry box-day owns.
* **The `name_prefixed` row on the espeak tape (0.062) is the PROXY's failure,
  not the design's** — VOICE-GATE F3b. `base.en` writes espeak's "Parcel" as
  *Potter soul*, *POSSEL*, *Fossil*, *Basel*, *puzzle*. The same phrases in a
  neural voice transcribe correctly, which is why the shipped row is measured on
  the piper tape and this row is reported beside it. A real human owner saying
  the name is **unmeasured** (box-day); constrained/boosted decoding over the
  known vocabulary is already an A7 build item.

## False STOPs

| tape | `name_prefixed` | `hybrid` (window closed) | `hybrid` (window open) | `bare` |
|---|---|---|---|---|
| television, 600 s, 976 ASR windows | **0 → 0.0/24 h** | **0 → 0.0/24 h** | 6 → 864/24 h | **6 → 864.0/24 h** |
| real room, 2 978 s (49.6 min), 0 ASR windows | 0 | 0 | 0 | 0 |

* `bare` **reproduces the research number exactly** — 6 in 10 minutes of
  ordinary television, 864/24 h against a bar of 1. Its own transcripts are the
  argument: *"Police say the drivers stop."*, *"The drivers stop at the
  intersection."*, *"I will stop that mid-intersection."*
* `name_prefixed` scores **0**, and the load-bearing VOICE-GATE observation is
  re-verified over all 976 windows: **the dog's name appears in none of them.**
* `hybrid`'s window is unit-proven at both ends: closed ⇒ identical to
  `name_prefixed`; open ⇒ identical to `bare`. The runtime opens it while the
  dog is **speaking** or **moving** (moving counts as owner-commanded because
  the freeze list says no self-initiated translation ships). Its through-air
  false rate is **not measured**.
* The quiet room produced **0 Silero spans**, so the transcriber was never even
  reached. That is the desired behaviour and it proves less than it looks:
  0 events in 49.6 min bounds the rate at ≈ **87/24 h** (3/T), not at 1. The
  ≤ 1/24 h bar needs ~72 h of tape and the test says so out loud.

## Bypass, latch identity, additivity

| property | how | measured |
|---|---|---|
| a hung conversation does not delay STOP | real runtime, `agent.handle_text` wedged (holding `_agent_lock`), the thread tier driven in real time, conversation asserted **still hung** at the end | idle p50/p95/max **776/776/776 ms**; wedged **775/776/776 ms** → the hung conversation costs **≈ 1 ms** |
| the capture thread is never blocked | 1 200 frames handed over while the transcriber is wedged | **< 0.5 s** total (`put_nowait`), 0 dropped |
| the panel STOP is never behind this path | panel latch taken while the hotword thread is wedged mid-transcription | **0.2 ms** |
| the latch is the panel's latch | `action("emergency_stop")` → arbiter latched; hotword → the SAME `arbiter.emergency_stopped` and the same agent-side state as the existing spoken door (`submit_voice_text`), verbatim phrase on the safety ring with `source="voice"`; both routes pinned to the ONE method `RobotRuntime.emergency_stop` by a call spy | identical state; sources `panel` and `voice` both on the ring |
| additive under failure | a refused `stop_hotword` config → no watch, loud detail, and the panel button still latches | proven |

The thread tier's 776 ms is a deliberate **worst case**: its stub transcriber
answers only for a window whose speech has already ENDED, so the close-edge
check always costs one transcription more than a real one would. A9's p95 bar is
carried by the replay tier, over real transcripts. What the thread tier proves
is that even then the latch lands inside 1.0 s and the thread + queue + runtime
callback add nothing measurable.

`_stop_hotword_latched` is three lines and deliberately does **not** call
`voice_session.barge_in()` the way the typed and hosted doors do: that would put
the conversational stack on the safety thread, which is the one thing A2 forbids.
Consequence, stated: a spoken local STOP latches motion but does not cut the
dog's own sentence short. Filed as a follow-up, not a defect of the latch.

## Suites

Every run through `env -u TMPDIR ~/.cache/parcel-guard/pytest_guard.sh --label
a6-stop …`; never `-n auto`; `ci_gate --tier` not run (integrator's).

* `tests/test_a6_stop_local.py` — **52 passed**
* r24 + nominal-stop + closed-intents + endpointing ×2 + voice_audio +
  acoustic_defects + core_hard_stop + owner_estop + realtime_ingress +
  **both DEC ratchets**, together with A6: **534 passed, 1 skipped**
* DEC-0 pins named: `test_no_new_oversized_module` (green — `voice_loop.py`
  untouched, `config.py` at exactly 1 000, `runtime.py` already in the
  baseline), `test_no_new_long_function` (every new method < 100 lines),
  `test_no_new_card_markers` (none added), `test_no_new_import_cycle`
  (`audio.stop_hotword → voice.closed_intents` + `→ audio.voice_loop`, no
  cycle); DEC-IG-2 green (no barrel re-export, no forbidden reverse edge)
* Ruff: my files contribute **0** fingerprints. One PRE-EXISTING fingerprint not
  in the baseline was observed and not touched:
  `research/20260823/search-before-refuse/runtime_probe.py::F401` (from commit
  98023fb) — flagged for the integrator.

**Seeded red, 8 cells, each sha256-restored, all RED**: name rule removed ·
whole-word rule → substring · speech-offset trigger removed · hold-off removed ·
the tee moved after the canceller · the latch replaced by a parallel flag · the
stop path made to take the conversation's lock · `off` made to build a matcher.
Plus in-suite anti-vacuity: the tail assertion proven able to fail, the
positive control for `off`, the "conversation still hung" control, the
"substring is present" control on every whole-word refusal.

## Undone, and why

1. **Everything through air stays box-day.** Every row is VOICE-GATE's `replay`
   tier: real recorded room floor, synthetic stimuli through the harness channel
   model. No loudspeaker, no mounted acoustics, no AEC, no gait/fan noise, no
   real human owner, no real geometry. The mounted-array bars (recall at 3 m
   off-axis, barge-in, AEC ≥ 20 dB) are the box-day packet's.
2. **≤ 1 false STOP/24 h is not PROVEN, only unfalsified** for the shipped
   grammar: 0 on 10 min of television and 49.6 min of room bounds the rate at
   ≈ 87/24 h. ~72 h of event-free tape is what the bar costs.
3. **The transcriber is shared.** The stop path builds its OWN client but points
   at the same resident `whisper.cpp` the conversation uses, so a busy server is
   a tail risk (the two > 1 s trials are what that looks like).
   `PARCEL_STOP_HOTWORD_STT_URL` points it at a second server today; a dedicated
   small keyword spotter is the real fix and is a box-day/A7 decision.
4. **Hybrid's bare window is unmeasured through air**, and its riskiest case —
   bare "stop" live *while the dog is speaking* — is exactly the self-echo case
   this desk cannot measure (no verified loudspeaker). It is not the default.
5. **Recall ≥ 0.99 is not met** (0.938 shipped-grammar synthetic, 0.859 bare
   recorded). Named, not hidden.
6. **The name is a config default, not a persona fact.** If a persona/name
   surface is ever added, `stop_hotword.name` should read from it rather than
   grow a second spelling.
7. **`config.py` is now at exactly 1 000 lines** — the DEC-0 ceiling. The next
   card that touches it reddens the ratchet. Flagged for the decomposition
   program, not worked around.
8. `CODEBASE_INDEX.md` is **not** regenerated (new files added; git is
   read-only for this card). The integrator runs
   `.parcel/bin/python tools/codebase_index.py` at close.
