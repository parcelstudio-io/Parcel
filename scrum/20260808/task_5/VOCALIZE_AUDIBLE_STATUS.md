# U35 — the dog asks for help, and now a recording can prove somebody could hear it

**Date:** 2026-08-09 · **Card:** close U35 (the `Vocalize` path is silent).
**Entry state:** `RobotRuntime._brain_vocalize` wrote a chat item and an event
and returned. Every planned `Vocalize` step, every honest not-found reply, the
localization-health announcements, the search give-up, and all three of the
yield policy's utterances (ask / re-ask / give-up,
[task_4/YIELD_POLICY_STATUS.md](../task_4/YIELD_POLICY_STATUS.md)) were
**visible in the panel and inaudible in the room**.

**The one-line claim, with its evidence.** System-initiated speech now goes
through the ordinary TTS/playback path, and it was measured on the virtual
acoustic rig: the `gentle_companion` ask produced **5.27 s and 5.58 s of audio
(n=2) on the sink-monitor recording**, peak sample 32729/32767, against
**peak 0, RMS 0.0, no onset** on the pre-fix door running the identical script
in the same rig. The chat item and the event are byte-identical in both — which
is exactly why nothing before today could tell the two apart.

---

## The API as landed

```python
DuplexVoiceSession.speak_system(text, *, turn_id=0, kind="system") -> bool
```

Synthesis and playback are `_run_output`, unchanged. The system utterance
therefore gets the same audio sink, the same chunk tokens, the same
`audio_turn_start` re-arm, the same playback clock, the same prosody tap, and
the same `cancel_event` a reply gets. Nothing about barge-in, epoch
cancellation, or `close()` needed a special case, because there is no second
path to special-case.

`True` means an output worker was started — the same bar `audio_first_playback`
sets for a reply, a confirmed handoff to the sink. It is not an acoustic
guarantee; that is what the rig measurement below is for.

`False`, and never an exception, for: empty text, text-only mode (no
synthesizer/player), a closed session, and the busy case.

### It is not a filler, and that is enforced

`speak_system` touches **none** of the filler bookkeeping — not
`_filler_active`, not `_pending_reply_after_filler`, not `on_filler_audible`,
not any `filler_*` stage. A request for help is not an acknowledgement token
and must not become a data point in the ≤2 s filler ceiling or in
`FillerLatency`. It emits `system_utterance_start` / `system_utterance_complete`
instead, and it does **not** emit `turn_complete` (which would finalize a
latency trace and flip the dialogue phase for a turn nobody started).

### The stage vocabulary

`VoiceStage` gained one field, `kind: str = ""`. Every stage a system utterance
emits — including the ones it shares with a reply (`tts_start`,
`tts_first_chunk`, `audio_first_playback`, `tts_complete`, `superseded`,
`error`) — carries `kind="system"`. Replies and fillers are unchanged at `""`,
so no existing observer sees a different object.

`observability.STAGES` is the repo's one closed stage vocabulary and
`LatencyTracker.mark` **raises** `ValueError` on an unknown name *before* it
looks up the trace, so an unregistered stage would have surfaced the first live
ask as a voice-session error instead of audio. Both new names were added there.
I searched for other registries that validate stage names —
`duplex/coordinator.py`, `duplex/filler_policy.py`,
`evals/companion/duplex_v1/`, the panel, the session-log schema — and there is
no second closed list; every other consumer matches specific names and ignores
the rest. `tests/test_system_utterance_audible.py` pins this by *collecting*
the names from real runs (including the sink-failure arm) and asserting the set
is a subset of `STAGES`, rather than listing them by hand.

---

## The concurrency policy, and why this one

**If any output is already live — a reply, a filler, or an earlier system
utterance — the system utterance is SKIPPED and `speak_system` returns
`False`.** It is not overlapped and it is not queued.

Three reasons, in order of how much they cost if ignored:

1. **Two output workers enqueue into one ordered `SpeakerSink`.** The sink
   preserves the order it receives chunks in, not the order of the sentences
   they belong to, so two concurrent streams interleave into a sentence that
   was never authored. This is a corruption, not a latency problem.
2. **A dog that talks over itself is worse than a dog that says it once.** The
   yield policy already owns a retry — `reask_interval_s`, 12 s by default —
   and the P-3 measurement shows the second ask lands ~18 s after the first.
   Skipping costs at most one ask; overlapping costs the sentence.
3. **A queue would need a lifetime policy nobody has.** A queued ask fired
   after the person moved on is a lie about the present, and dropping it later
   needs a staleness rule that does not exist. Skipping *is* that rule,
   evaluated at the only moment when the information is current.

The skip is deliberately silent in the stage stream: no `system_utterance_start`
is emitted, because that stage promises a worker. The caller still learns about
it through the return value, and `_brain_vocalize` records it
(`audio_path: "suppressed_output_busy"`).

Epoch and lifecycle: `speech_epoch` is captured under the session lock at
install time, so a barge-in that lands between the decision and the thread
start cancels the utterance like any other speech; `_closed` refuses outright.
`_active_output` is installed under `_idle` (the same condition `play_filler`
and `_start_output` use), which is what makes "is anything speaking?" a single
atomic check rather than a race.

---

## What now speaks that did not before

Everything that leaves through `_brain_vocalize`, which is every
system-initiated utterance in the runtime:

| caller | what it says |
|---|---|
| `Vocalize` skill (`SemanticTaskRuntimeAdapter._dispatch`) | every planned utterance step in every mission, including the honest not-found replies |
| `AskClarification` skill | the same door, `question` argument |
| `_act_on_yield_decision` | the ask, the re-ask, and the give-up line — all three |
| `_announce_pose_health` | `POSE_LOST_UTTERANCE` / `POSE_REGAINED_UTTERANCE` |
| search give-up (`_finish_search`) | "I lost you — I'll wait here." |

There is no second call site: I checked every `_chat_item("assistant", …)` in
the runtime and the only system-initiated one is `_brain_vocalize`; the other
four are ordinary turn replies, which already spoke.

### The record no longer implies audio it did not produce

`_brain_vocalize` still writes the chat item and the `brain` event first-class
and unconditionally — they are the record, and they must not depend on whether
the host has a synthesizer. What changed is that the event now carries a
structured rider:

```json
{"role":"brain","text":"Could you help me get through to sidewalk?",
 "detail":{"audible":true,"audio_path":"voice_tts"}}
```

`audio_path` is one of `voice_tts`, `text_only` (no synthesizer on this host),
`suppressed_output_busy` (the skip). `_emit` gained an optional `detail=`
keyword; the key is absent unless a caller supplies one, so every existing
event is byte-identical to what it was.

`yield_policy_snapshot()` gained `last_utterance_audible` (`None` before
anything is said) beside the existing `last_utterance`, because a snapshot that
shows the sentence without it reads like a spoken ask.

`_brain_vocalize` now returns `bool`. The `Vocalize` adapter result is
unchanged (`detail="utterance_sent"`, `source="runtime_voice_log"`) — it types
the callback as `Callable[[str], object]` and ignores the return, and those two
strings are contract values pinned by `test_brain_runtime_adapter.py` and
`test_brain_executive.py`.

### Duplex metrics are deliberately not touched

`_voice_stage` short-circuits on **any non-empty `kind`**: it marks the stage in
the latency vocabulary and returns, driving neither the dialogue phase machine
nor `_duplex_on_voice_stage`. Without this guard a system utterance's
`tts_first_chunk` would call `duplex.on_first_token`, **cancelling the filler
watchdog of whatever turn was in flight** and writing a `ttft_s` for turn 0.

The test is "is it marked at all" rather than an equality on `"system"` on
purpose: a future system-initiated stream that named itself something else
would otherwise fall silently back into the turn machinery, which is the
failure this guard exists to prevent. An unrecognized kind logs a warning and
is still treated as not-a-turn — it never raises, because a stage callback that
raises is how a voice path breaks a mission.

The honest cost, stated: the D0 TEXT frame stream shows `<silence>` while the
robot is speaking a system utterance. That is a corpus-fidelity gap of the same
class as the ones already listed in `docs/DUPLEX_DUAL_STREAM_DESIGN.md` ("ACT is
last-write-wins", "frames can lead that sentence's audio"), and it is the right
trade today: a system utterance has no query to attribute tokens to, so folding
it into a turn's frames would misattribute them.

---

## Acoustic evidence

Measured on the `acoustic_loop_v1` **rig module** (`evals/.../rig.py`, a
library) — a per-run PipeWire null sink, `object.linger`, destroyed in
teardown — **without editing the frozen pack**. See "the pack case" below.

Path exercised end to end, nothing mocked: `_brain_vocalize` →
`speak_system` → `_run_output` → real Piper subprocess →
`SentenceChunkedSynthesizer` → `SpeakerSink` → `sounddevice` → the rig's null
sink → its `.monitor`, recorded by `pw-record` at 16 kHz mono s16. The sink was
selected through the **production** seam (`speech.output_device: <rig sink>` →
`resolve_audio_device`), resolving to `u35_…_sink (index 10)`.

Utterance: the shipped `gentle_companion` ask, verbatim from the P-3 run —
*"Someone is standing right where I need to go, so I've stopped. Could you help
me get through to sidewalk?"*

| run | `speak_system` | first sink chunk | acoustic onset | acoustic offset | **audio duration** | peak |sample RMS |
|---|---|---|---|---|---|---|---|
| 1 | `True` in 0.6 ms | 0.383 s | 1.30 s | 6.57 s | **5.27 s** | 32729 | 3594 |
| 2 | `True` in 0.6 ms | 0.374 s | 1.29 s | 6.87 s | **5.58 s** | 32767 | 3888 |
| **control** (pre-fix door) | `False` | never | **none** | — | **0 s** | **0** | **0.0** |

The control is not a re-checkout: it is the same script with
`_speak_system_utterance` stubbed to `False`, which is exactly what the old
door did (chat + event, no audio attempt). Its chat item and `brain` event are
identical to run 1's. `orphan_nodes_after_teardown: []` on all three — the rig
left nothing behind.

Enqueue finished at 0.65–0.67 s while acoustic onset is at 1.29–1.30 s of the
recording (~0.5 s of which is the deliberate pre-roll before the utterance):
the ~0.54–0.64 s enqueue-to-audible gap the pack's baseline measured is
present here too, and unchanged by this card.

**What this does not prove.** No room, no air, no transducer, no listener; the
speech is Piper, not a person; and nobody has ever *responded* to the ask —
that is U35's second half and it is still open (see below). "Audible" here
means sound existed on a recording, which is strictly more than the software
tier could say yesterday and strictly less than a person hearing it.

### The pack case — filed, not landed

Adding a permanent case to `evals/companion/acoustic_loop_v1` is **not cheap**,
for two reasons that are both integrity properties rather than effort:

1. A new `family` value is refused by `result.schema.json`'s `family` enum, and
   that schema is **hash-locked** in `manifest.json`
   (`2551939a24f5ab67…`). Editing it means editing the frozen manifest.
2. Filing the case under the existing `duplex` family avoids the schema, but
   still changes `metrics.duplex.cases`/`responded` and the `case_verdicts`
   determinism object **under an unchanged `runner_version`**, so the two
   retained baseline rows would no longer describe the same suite.

Both are exactly what "frozen" is for, and the card's instruction was to say so
rather than force it. Filed as **`backlog/NEXT.md` N22** with the runner
version bump it needs and the probe (which already works) as its body.

---

## Tests

`tests/test_system_utterance_audible.py`, **25 cases**:

| layer | what it pins |
|---|---|
| audible path | chunks reach the sink; the sink is re-armed once; `system_utterance_start` first and `system_utterance_complete` last; `tts_start`/`tts_first_chunk`/`audio_first_playback`/`tts_complete` all present |
| not-a-filler | no `filler_*` stage, no `on_filler_audible`, `_filler_active` untouched, no `turn_complete` |
| the `kind` marker | every system stage carries it; every reply stage does not |
| skip-when-busy | skipped under a live reply, a live filler, and a live system utterance — each asserting the *other* stream's chunks are the only ones played and that no `system_*` stage was emitted; `_output_jobs == 1` |
| skip does not latch | a later ask is spoken; a reply after a system utterance is spoken |
| barge-in | cancels it, epoch bumps, `superseded` emitted, `audio_interrupt` fires, and no token leakage (`_active_output is None`, `_output_jobs == 0`, `_output_threads == set()`); a final transcript supersedes it the same way |
| text-only / closed / empty | returns `False`, raises nothing, emits **no** stages (an unpaired start would be a lie) |
| stage vocabulary | both names in `STAGES`; `LatencyTracker.mark` accepts them and still raises on an invented one; the set collected from real runs (incl. the sink-failure arm) ⊆ `STAGES` |
| runtime seam | chat + event written with `detail.audible` / `detail.audio_path` for all three outcomes; a `Vocalize` planned step and an `AskClarification` step both reach `speak_system` through the runtime's own adapter; an exploding session never breaks the caller; empty text still raises; **end-to-end through the real session and the real `SpeakerSink` to a player** |
| duplex isolation | system stages move neither `duplex.snapshot()` nor `_duplex_turn_meta` |

One deliberate detail in the test file: `wait_until_idle` releases inside
`_run_output`'s cleanup, one frame *before* `system_utterance_complete` is
emitted, so the ordering assertions poll for that stage (`_await_stage`) rather
than being nearly-always-true.

`tests/test_yield_policy.py` gained **3 cases** (81 → 84): all three yield
utterances attempt the speaker; an inaudible ask is recorded as inaudible while
the chat item is still written; the snapshot reports `None` audibility before
anything is said.

---

## Verification

| check | result |
|---|---|
| `tests/test_system_utterance_audible.py` | **25 passed** |
| `tests/test_yield_policy.py` | **84 passed** (was 81) |
| full default suite `MUJOCO_GL=egl .parcel/bin/python -m pytest tests/ -q` (includes the live `-m slow` e2e block) | **2896 passed, 14 skipped, 3 xfailed, 0 failed**, 3 errors, 543.1 s |
| targeted battery on every surface this card touches (system utterance, yield, pose health, observability, duplex ×3, voice streaming/audio/AEC, K6 voice lanes, runtime, brain adapter + executive, beat sync, panel voice mode, spatial observability) | **368 passed** |
| `-m "not slow"` sweep on the final tree | **2849 passed**, plus 7 failures and 2 collection errors, all attributed below |
| `ruff check` on every touched file | **clean** |
| `evals/` | nothing under `evals/companion/**` written today. `find evals -newermt 2026-08-09` returns only the navigation lane's `evals/nav_instruct/generator.py` and a BARN scratch challenger, neither of which this card can reach. `acoustic_loop_v1/` and `embodied_plan_v1/` are untouched: no runner, schema, manifest, fixture, or result row moved. |
| `configs/robot.yaml` | sha256 `f64688874525f20d…` — **matches** `embodied_plan_v1/manifest.json`'s `locked_inputs.robot_config`. Neither read nor written here. |

The acoustic probe lives in the session scratchpad, not in the repo: it is
evidence for this record, and its permanent home is N22.

### Attributing every red — all of it is the navigation lane, mid-flight

A navigation executor is landing `instructnav/**` changes into the same tree.
Mtimes put `instructnav/{__init__,relations,scoring}.py` and
`navigation/approach.py` inside the same minutes as these runs.

**The 3 errors in the full-suite run** are all `tests/test_voice_nav_e2e.py`
(`test_go_to_the_owner_arrives…`, `test_come_here_closes_on_the_owner…`,
`test_orbit_the_owner_completes_one_revolution`) and all have the identical
cause, which is not a test failure at all — the simulator subprocess would not
start:

```
sim died during startup: … src/parcel_robot/sim.py:12
  from .city_semantics import …  →  instructnav/__init__.py:31
  ImportError: cannot import name 'next_to_achievable_anchor_radius_m'
               from 'parcel_robot.instructnav.scoring'
```

`instructnav/__init__.py` was exporting a symbol `scoring.py` did not yet
define. That window closed on its own — the export is gone from `__init__.py`
as of this writing — and the file is one this card is forbidden to touch and
does not import.

**The 7 failures + 2 collection errors in the later `-m "not slow"` sweep** are
the same lane, one edit further along: `scoring.py` still does not define
`next_to_achievable_anchor_radius_m` (it survives only in a docstring at
`scoring.py:735`), so `tests/test_next_to_band_achievability.py` and
`tests/test_scene_semantics.py` fail to import it, and five
`test_instructnav_compound_predicates.py` cases now return
`SitNextToOutcome(detail='outside_next_to_band', distance_to_band_m=0.25)` —
the band radius being actively changed. `test_walk_with_me_k8::
test_committed_freeze_matches_generator` is a generator freeze-hash mismatch
(`d9487ce7…` → `fc24837c…`), and `test_owner_and_settle_plans::
test_the_offer_names_only_relations_the_class_actually_affords` is the same
bench-affordance case another lane already broke and fixed on 2026-08-08.

Attribution is structural, not circumstantial:
`tests/test_instructnav_compound_predicates.py` imports **only**
`parcel_robot.instructnav.scoring`, and `tests/test_walk_with_me_k8.py` imports
only `evals.walk_with_me.*` plus that same module. Neither imports
`runtime.py`, `voice_pipeline.py`, or `observability.py`, so no edit in this
card is on their import graph at all. The 368-case battery above covers every
module this card did touch and is green on the same tree.

---

## Non-claims

1. **Nobody has heard it.** A null sink is not a person, and `True` from
   `speak_system` means "handed to the sink", not "presented as sound in a
   room". The rig recording is the strongest available statement and it stops
   at the monitor.
2. **No pedestrian has responded.** U35's second half is untouched — the
   dynamic city's agents walk a script and cannot hear anything. The card was
   about audibility, not about the social loop.
3. **The skip can silence a real ask.** If the robot is mid-reply when patience
   expires, that ask is never spoken and only the re-ask ~12 s later is. This
   is the chosen behaviour, it is recorded in the event detail, and it has
   never been measured against a live conversation.
4. **The D0 frame stream does not observe system speech**, by the deliberate
   decision above.
5. **Nothing here is hardware.** The whole path still runs on a virtual sink;
   U5 (no audio device has ever been opened for real) is unchanged.
6. **The 0.54–0.64 s enqueue-to-audible gap is not addressed.** It is present
   in this measurement, it belongs to the sink/PipeWire boundary, and it is
   N19's problem.

---

## Files touched

| file | change |
|---|---|
| `src/parcel_robot/voice_pipeline.py` | `SYSTEM_UTTERANCE_KIND`; `VoiceStage.kind`; `speak_system`; `_run_system_output`; `_run_output(..., system=, stage_kind=)` threading the marker through every stage it emits |
| `src/parcel_robot/observability.py` | `system_utterance_start` / `system_utterance_complete` added to the closed `STAGES` vocabulary |
| `src/parcel_robot/runtime.py` | `_speak_system_utterance`; `_brain_vocalize` speaks and returns `bool`; `_emit(detail=)`; `_voice_stage` system short-circuit; `_last_yield_act_audible` + `yield_policy_snapshot()["last_utterance_audible"]` |
| `tests/test_system_utterance_audible.py` | **new**, 25 cases |
| `tests/test_yield_policy.py` | +3 cases (U35 audibility at the yield seam) |
| `docs/YIELD_POLICY.md` | the inaudibility limitation replaced by what is now true, including the skip |
| `backlog/UNVERIFIED.md` | U35 rewritten: half closed with evidence, half still open |
| `backlog/NEXT.md` | **N22** — land the system-utterance case in the acoustic pack behind a `runner_version` bump |

**Not touched:** `navigation/**`, `instructnav/**`, `tests/test_voice_nav_e2e.py`,
`evals/**` (code *or* data), `configs/robot.yaml`, `configs/personality.yaml`,
`src/parcel_robot/core/yield_policy.py` (read only).
