# FIX-A — fail-safe mic arming, speech-stack observability, transcript persistence

**Date:** 2026-08-15 · **Card:** FIX-A · **Host:** jaewoo-jang-parcel (the incident machine)
**Venv:** `/home/jaewoo-jang/Desktop/Projects/Parcel/.parcel/bin/python`

## What was broken, in one paragraph

The desktop has no physical audio endpoints. PipeWire offers a single `Dummy
Output` sink and **zero** sources, so a default capture stream is wired to the
**monitor of the robot's own speaker sink** — a unity-gain digital loopback.
`web_panel` launched without `--config` used `configs/robot.yaml` (energy
endpointing, no AEC, none of B2's semantic models). The microphone loop armed
anyway, because arming was gated on exactly one condition: *is STT reachable?*
(`runtime.py`, `if self.speech_stack.recognizer is not None:`). The runtime's
own audio probe was simultaneously reporting `connected_input: false` and
nothing read it. Every TTS filler fed back at full amplitude, defeated the
acoustic RMS echo guard, triggered barge-in, closed ~0.5 s utterances, and each
junk transcript ("him.", "Just", "[BLANK_AUDIO]") was answered as a command —
669 turns of self-talk. The owner's three typed "go to the sidewalk" commands
were understood and acknowledged; their missions were killed by a separate,
owner-gated path.

## What changed

| Fix | File | Change |
| --- | --- | --- |
| F1 | `src/parcel_robot/audio_arming.py` (new, 279 lines) | `decide_microphone_arming()` — pure, fail-closed arming gate + `CaptureIdentity` (what the capture endpoint IS and *which metadata key says so*). |
| F1 | `src/parcel_robot/audio_io.py` | PipeWire probe now classifies the default capture endpoint: `AudioDeviceStatus.input_is_monitor` / `.input_identity`, decided by `_monitor_signal()` from object metadata. Additive fields with defaults. |
| F1 | `src/parcel_robot/runtime.py` | Mic-loop construction is gated on `self._mic_arming.armed` instead of `recognizer is not None`. |
| F1 | `src/parcel_robot/providers.py` | `speech.allow_monitor_capture` added to `_ALLOWED_SPEECH_KEYS` (unknown speech keys still fail closed). |
| F2 | `src/parcel_robot/runtime.py` | `_report_speech_stack()` — one startup summary + `/api/state → speech.stack`, plus the missing-semantic-stack WARNING. |
| F3 | `src/parcel_robot/runtime.py` | `submit_voice_text(..., origin=)`, `_submit_microphone_text()`, per-turn transcript hold, two new `turn_outcome` fields. |
| F3 | `docs/DUPLEX_DUAL_STREAM_DESIGN.md` | Log example + the now-false claim "does not currently include the user transcript" corrected. |

Tests added: `tests/test_fixa_mic_arming.py` (20), `tests/test_fixa_transcript_persistence.py` (8).

**Nothing arms anything physical.** The gate only ever *refuses* to open a
capture stream; the single path that can newly open one is the explicit
`speech.allow_monitor_capture: true` opt-in, which defaults to `false` and logs
a WARNING when used.

---

## F1 — fail-safe mic arming

The gate answers one question with one line of justification, in this order:

1. **no recognizer** → not armed (unchanged historical behaviour, now stated).
2. **capture endpoint is a sink monitor** → not armed, unless overridden.
3. **probe reports no connected input endpoint** → not armed, unless overridden.
4. otherwise → armed, exactly as before.

`speech.allow_monitor_capture` (default `false`) bypasses **both** (2) and (3).
It has to bypass (3) as well: on a sink-only host like this one a loopback rig
has *no* default source at all, so a monitor-only override could never be
exercised. Every override is a `logger.warning` plus a `warning`-level runtime
event; there is no silent path.

### Measured: the live host, the incident config, STT faked reachable

```
$ .parcel/bin/python scratchpad/live_demo.py     # real detect_audio_devices(),
                                                 # configs/robot.yaml, recognizer injected
LIVE AUDIO PROBE:  ... "connected_input": false, "input_is_monitor": false,
                       "input_identity": "no default node", "transport": "none"

recognizer present: True
microphone loop constructed: False

/api/state speech.mic_arming: {
  "armed": false,
  "code": "no_input_endpoint",
  "reason": "Microphone not armed: the audio probe reports no connected input endpoint
             (ALSA hardware and drivers are installed, but no microphone/speaker endpoint
             is connected; using streaming text.). A capture stream opened now would be
             routed to whatever the host substitutes — on a sink-only host that is the
             speaker's own monitor. Using streaming text.",
  "override": false,
  "capture_device": {"name": "system default", "index": null, "is_monitor": false,
                     "signal": "no default node", "source": "pipewire", "confidence": "none"}
}
```

The precondition is the storm's precondition — reachable STT on this exact
machine — and the loop is not constructed.

### The identity signal, stated honestly

Monitor-ness is decided by **PipeWire object metadata**, read through
`wpctl inspect`, in decreasing order of trust:

| Signal | Meaning | Trust |
| --- | --- | --- |
| `device.class = "monitor"` | WirePlumber says the node is a monitor | metadata |
| `media.class` ending in `/sink` | reached as the *default source*, but the object is a sink → its capture side is the sink's monitor ports | metadata |
| `stream.monitor` / `port.monitor` true | explicit monitor booleans | metadata |
| `node.name` ending in `.monitor` | consulted **last**, suffix only | metadata-ish |
| PortAudio device *name* contains "Monitor of …" / `.monitor` | only available signal for an explicitly configured `speech.input_device` | `confidence="name_only"` |

The `confidence` field travels with the verdict into `/api/state`, so a
name-only refusal is never presented as a metadata fact.

**What this cannot detect** (also written into the test module's docstring):

* an ALSA loopback (`snd-aloop`) card wired to a playback stream — it presents
  as genuine capture hardware behind a genuine `Audio/Source` node;
* a filter-chain / virtual source that mixes sink audio yet declares
  `media.class = Audio/Source` with no monitor markers;
* a **physical** loopback: a line-out→line-in cable, or a real microphone next
  to a real speaker. That is acoustic echo — a different problem, owned by B10;
* anything when PipeWire tooling is absent. `wpctl` missing yields
  `input_identity="unknown"` *and* `connected_input=False`, so such a host
  fails closed through the no-endpoint gate, not through the monitor gate.

A second honesty note: the probe classifies the **system default** endpoint. If
`speech.input_device` names a device explicitly, that device — not the default
— is what PortAudio opens, so the probe's verdict is deliberately **not**
carried over onto it (`test_probe_verdict_does_not_leak_onto_an_explicitly_configured_device`).
This host cannot even enumerate PortAudio devices (`OSError: PortAudio library
not found`), which is precisely why the gate cannot rest on PortAudio metadata.

---

## F2 — startup speech-stack observability

`/api/state → speech.stack` and one startup event now carry: the resolved
config path, `speech.mode`, the endpointing stack that actually loaded (with
model paths **and** whether those files exist on disk), whether AEC was
constructed, and the capture-device identity. Measured on the incident config:

```
"config_path": "/home/jaewoo-jang/Desktop/Projects/Parcel/configs/robot.yaml",
"mode": "auto",
"endpointing": {"requested": "energy", "resolved": "energy (VAD hangover)",
                "semantic_loaded": false,
                "models": {"vad_model": "models/endpointing/silero_vad_v6.onnx",
                           "turn_model": "models/endpointing/smart_turn_v3.onnx"},
                "models_present": {"vad_model": true, "turn_model": true}},
"aec": {"constructed": false,
        "detail": "no AEC stage is wired into the capture loop on any config path"}
```

Every fact that was invisible on 2026-08-11 is now one field. The AEC line is
**stated, not inferred**: `RobotRuntime` never passes an `aec=` argument to
`MicrophoneVoiceLoop`, on any config, so the capture path is the raw frame path
everywhere today.

**Warning condition, and its one deliberate widening.** The card asks for a
WARNING when the semantic weights are present on disk but not loaded *while
`speech.mode` is audio*. Implemented as `speech.mode == "audio"` **or the mic
actually armed** — because the storm ran under `mode: auto`, where the literal
condition would have stayed silent. On this host with the fix in place the
warning does *not* fire, and correctly so: the microphone is not armed, so the
turn-taking stack is moot and the operator gets the arming refusal instead. Plug
in a headset and restart under `robot.yaml` and the warning fires.

---

## F3 — transcript persistence

`turn_outcome` records gain exactly two fields:

```json
{"type":"turn_outcome","turn_id":7,"ttft_s":0.31,"filler_used":null,"filler_reason":null,
 "filler_audible":false,"barge_in":false,
 "transcript":"go to the sidewalk","transcript_origin":"panel_text","wall_s":...}
```

`transcript_origin` ∈ {`mic`, `panel_text`}; an unknown origin is a `ValueError`
at `submit_voice_text`. The mic loop is wired to `_submit_microphone_text`,
a thin wrapper, so the label comes from *which door the text came through*
rather than a mutable "who called last" flag.

**Kill switch.** Both fields are produced only when `self.duplex.log.enabled`
(i.e. `duplex.logging and duplex.enabled`, the existing switch in
`src/parcel_robot/duplex/config.py`). With logging off they reach neither the
JSONL nor the `/api/state` duplex snapshot — the snapshot is not a side door
(`test_transcript_fields_obey_the_existing_duplex_logging_kill_switch`). The
per-turn hold is released on **every** turn regardless of the switch, so the
buffer cannot become a retention store (`test_held_transcripts_are_released_after_every_turn`).

### Every consumer of the duplex JSONL, and its proof

| Consumer | Kind | Proof |
| --- | --- | --- |
| `src/parcel_robot/duplex/coordinator.py` `record_turn_outcome` / `snapshot` | producer + in-memory mirror | `tests/test_duplex_integration.py` 15 passed |
| `tests/test_duplex_integration.py:163-173` | the only JSONL reader in the tree (`row.get("type") == "turn_outcome"`) | 15 passed; shape re-pinned in `test_legacy_consumers_tolerate_the_new_fields` |
| `evals/companion/duplex_v1/run_duplex_v1.py:483` | producer (`duplex.record_turn_outcome`); its own reader at :535 reads `evals/companion_nav/results/ledger.jsonl`, a **different** file | `tests/test_duplex_v1.py` 3 passed |
| `docs/DUPLEX_DUAL_STREAM_DESIGN.md:218` | documentation | updated in this card |

Search used: `grep -rn "turn_outcome" --include=*` over the tree (excluding
`.parcel/`, `.git/`) and `grep -rn "logs/duplex|DuplexSessionLog|\.jsonl"` over
`src/ tests/ evals/ scripts/`. No other reader exists.

**Frozen-manifest check (the STOP condition): none applies.** `ci_gate`'s
`FROZEN_DIGEST_NODE_IDS` / manifest sentinels cover nav_instruct v3+v4, the
embodied plan pack, `conversation_quality_v1` and `personal_convo_v1`. The only
`manifest.yaml` in the tree is `fixtures/storefronts/`. Nothing hash-locks the
duplex session-log format, so the additive change proceeded.

---

## Seeded-failure table

Each seed reintroduces one defect into the shipped source, runs the owning test
file, and is reverted in a `finally` block
(`scratchpad/seed.py`; working tree verified clean afterwards, `git status`
shows only intended files).

| # | Seeded defect | Gate | Result | First failing test |
| --- | --- | --- | --- | --- |
| S1 | F1 gate removed — arm on STT reachability alone (**the shipped defect, verbatim**) | mic arming | **RED** 2 failed, 18 passed | `test_runtime_does_not_arm_the_microphone_without_an_input_endpoint`, `test_runtime_does_not_arm_onto_a_sink_monitor` |
| S2 | `_monitor_signal()` blinded (always "not a monitor") | monitor identity | **RED** 3 failed, 17 passed | `test_probe_flags_a_sink_default_source_as_a_monitor`, `test_probe_flags_device_class_monitor`, `test_probe_leaves_a_real_microphone_alone` |
| S3 | `allow_monitor_capture` ignored — a loopback rig can never opt in | override | **RED** 1 failed, 19 passed | `test_override_arms_both_gates_and_is_never_silent[True-True-device.class=monitor]` |
| S4 | F2 semantic-stack WARNING removed | observability | **RED** 1 failed, 19 passed | `test_warns_once_when_the_tuned_semantic_stack_is_present_but_not_loaded` |
| S5 | F3 transcript fields never written | persistence | **RED** 3 failed, 5 passed | `test_typed_command_round_trips_transcript_and_origin`, `test_microphone_transcripts_are_labelled_as_microphone`, `test_schema_change_is_purely_additive` |
| S6 | F3 fields escape the `duplex.logging` kill switch | kill switch | **RED** 1 failed, 7 passed | `test_transcript_fields_obey_the_existing_duplex_logging_kill_switch` |
| S7 | non-additive schema change (`filler_used` renamed to `filler`) | consumer tolerance | **RED** 1 failed, 7 passed | `test_schema_change_is_purely_additive` |

7 seeds, 7 RED.

---

## Full run

**1. This card's tests + every duplex / voice / runtime file found in the tree**

```
$ .parcel/bin/python -m pytest tests/test_fixa_mic_arming.py \
    tests/test_fixa_transcript_persistence.py tests/test_audio_io.py \
    tests/test_voice_audio.py tests/test_voice_streaming.py \
    tests/test_voice_aec_ducking.py tests/test_duplex_frames.py \
    tests/test_duplex_integration.py tests/test_duplex_v1.py \
    tests/test_acoustic_defects.py tests/test_k6_voice_lanes.py \
    tests/test_eval_panel_voice_mode.py tests/test_runtime.py \
    tests/test_closed_intent_product_path.py -q
267 passed, 3 warnings in 18.62s
```

**2. The `slow`-marked voice/nav end-to-end file, run separately** (excluded
from the commit tier by `pytestmark = pytest.mark.slow`; it drives live sim
missions, ~11.5 min):

```
$ .parcel/bin/python -m pytest tests/test_voice_nav_e2e.py -q
17 passed, 1 xfailed, 3 warnings in 694.45s (0:11:34)
```

The 1 xfail is the pre-existing, documented P-1/P-3 yield-policy pin; it did not
flip.

**3. The gate**

```
$ .parcel/bin/python scripts/ci_gate.py --tier commit
CI GATE — tier=commit  (2026-08-15T08:32:55Z)
==============================================================================
[  PASS] HARD  ruff                       7 violation(s), baseline 7, new 0
[  PASS] HARD  hard-safety                nav frozen baseline nav-instruct-v1-baseline-v4-20260811T070536Z: collisions=0 false_arrival=0 | mutation panel clean: collisions=0 no_false_arrival=True | mutation panel freshness: committed fields reproduce live = True | follow-bench: 7 row(s), hard_collision_total all 0 = True | walk_with_me: 1/2 row(s) with hard_collision_total, all 0 = True
[  PASS] HARD  frozen-digest-sentinels    4 immutable manifest(s) byte-identical to pin
[  PASS] HARD  latency-tail-ledger        latest row latency-20260810T082415Z-4d83035f: 6 metric series within 1.2x tail ceiling (rows=5, window=5)
[  PASS] HARD  follow-bench-jerk-ratchet  latest shipped row follow-bench-v1-20260811023618Z-93eba090.json: 1.2187 <= 1.46244 (baseline 1.2187 x 1.2)
[  PASS] HARD  model-off-non-inferiority  23 passed in 0.55s
[  PASS] HARD  frozen-digest-integrity    6 passed, 1 warning in 0.38s
[  PASS] HARD  mutation-panel-freshness   2 passed, 3 warnings in 4.83s
[  PASS] HARD  latency-tail               6 passed, 2 warnings in 0.35s
[  PASS] HARD  default-suite              5375 passed, 9 skipped, 36 deselected, 5 warnings in 239.77s (0:03:59)
==============================================================================
RESULT: PASS — every hard gate green.
  elapsed 252.4s
```

`ruff` reports `new 0` against the pinned baseline; `ruff check` on the six
touched/added files passes outright, and the two new test files are
`ruff format`-clean.

**Working tree.** `git status --short` after every run shows only this card's
files plus `backlog/BLOCKED.md`, which was **not** touched here — it is another
session's concurrent edit in the same checkout. No git commit / stash / checkout
was performed.

---

## does_not_prove

* **Nothing here fixes echo handling for a REAL microphone rig.** The gate stops
  the degenerate case where the capture stream *is* the output stream. A real
  microphone in a real room next to a real speaker still bleeds the robot's own
  voice into capture, still leans on the RMS echo guard, and still has no AEC.
  That is **B10**, owner-gated, untouched here. F1 gates ARMING; it does not
  retune the guard, the barge-in policy, or the endpointer (N16/N17/B2 remain
  byte-unchanged).
* **No claim about real hardware.** Every measurement is either a pure-function
  test, a fixture-driven `wpctl` parse, or a `RobotRuntime` built on this
  sink-only host. No microphone was opened, because none exists here; PortAudio
  is not even loadable (`OSError: PortAudio library not found`). The "arms
  exactly as before" case is proven by *construction of the loop*, not by a
  capture stream that produced audio.
* **The monitor detector's blind spots are real** (enumerated above): ALSA
  loopback cards, sink-mixing filter chains that declare `Audio/Source`, and any
  physical loopback are all invisible to it, and a host without `wpctl` is
  classified `unknown` (and fails closed for the *other* reason).
* **F2 does not prove the semantic stack works** — only that it is or is not
  loaded, and that its weights are or are not on disk. B2's tuning is not
  re-measured here. The on-disk check uses CWD-relative paths
  (`models/endpointing/...`), matching how `SileroVad` / `TurnEndpointer`
  already resolve their weights; started from another directory it reports
  "absent" and the warning stays quiet — a false negative, never a false alarm.
* **F3 does not recover the 2026-08-11 transcripts.** They are gone. It makes the
  next storm reconstructable, and only while `duplex.logging` is on.
* **The three killed "go to the sidewalk" missions are untouched.** They died on
  a window-blur manual stop, which is owner-gated and outside this card.
* **Privacy posture changed by F3**: the duplex JSONL now contains the user's
  words. It was already unencrypted, unredacted, and un-expired (see
  `docs/DUPLEX_DUAL_STREAM_DESIGN.md`), and `/api/state` already exposed the same
  text via the `chat` block, so this is a wider surface for an existing exposure
  rather than a new class of one. `duplex.logging: false` turns it off entirely.
