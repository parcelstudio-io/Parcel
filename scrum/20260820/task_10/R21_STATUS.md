# R21 — safety events don't evaporate

**Date:** 2026-08-20 · **Card:** `scrum/20260820/task_10/README.md`
**Executor:** Claude Opus (agent) · **Auditor:** Fable
**Tree:** sole executor, one card, one tree. Nothing committed, staged or stashed.

**Dispatch gate honoured.** The card runs "after R20 closes". Verified before the
first edit: `scrum/20260820/task_9/R20_STATUS.md` exists and is complete through
its §14 DoD close-out (its own gate: 6987 passed). Same standard R20 itself used
for its R18 gate. No concurrent mutating agent was spawned at any point; the one
background job that overlapped this session's work (a redundant full-suite run)
was stopped before the seed harness touched a source file, precisely because a
concurrent reader is the hazard the R9 session-B harness exists to detect.

---

## §0 — One-paragraph answer

live_run_1 could not prove which utterance stopped the robot because the latch
event lived in `_events`, a 100-slot deque shared with every chatty source in the
runtime, and perception flushed it fourteen seconds later. The fix is the one
R4-lite already proved for mission terminals: safety lifecycle gets its **own
eviction-proof ring**, with the door that latched it (`voice` / `typed` / `panel`
/ `api` / `simulator` / `runtime_close`) and, for a spoken latch, the owner's
utterance **verbatim** — the same string the ledger keeps, so a ring row and a
conversation row line up word for word. Refusals under the latch are recorded
too, coalesced by door, and capped at half the ring so the consequences can never
evict the cause. The other half of the run — 84 seconds of an owner commanding a
latched robot — is answered by making the latch a **standing** fact rather than
an edge: `get_status` now carries the door, the age and the release condition,
and the whisperer digest carries the door so the spoken e-stop fact can name it.
And while writing the seeds I found that the live_run_1 artifacts **already**
excluded a Space-key latch, by a layer signature nobody had read (§5.4).

---

## §1 — What changed, and where

| File | Change | Card item |
| --- | --- | --- |
| `src/parcel_robot/runtime.py` | `SAFETY_LOG_*` / `SAFETY_SOURCE_*` / `SAFETY_RULE_*` / `MOTION_DISABLED_BY_LATCH` constants; the `_safety_log` ring + `_log_safety` / `_log_safety_latch` / `_log_safety_release` / `_note_safety_rejection` / `_newest_locked` / `safety_log` / `_safety_latch_state`; `emergency_stop(source=, phrase=, rule=)` and `clear_emergency_stop(source=)`; six doors declare their origin; `_refuse_under_latch` replacing ten copies of one `raise`; `_realtime_validate` and `_watch_under_latch` on the five hosted motion doors; `submit_motion`'s arbiter refusal; two snapshot keys; the `emergency_stop` block in `_realtime_status_digest`; `emergency_stop_source` into `_whisperer_digest` | 1, 2 |
| `src/parcel_robot/realtime/whisperer.py` | `StateDigest.emergency_stop_source` + `as_dict`; `ESTOP_SOURCE_PHRASES`; the `KIND_EMERGENCY_STOP` fact names the door and the way out; `STATE_DIGEST_VERSION` 2 → 3 | 2 |
| `src/parcel_robot/ui/index.html` | Safety-log list, count, CSS and `renderSafetyLog`; `estop-banner-source` + `renderEstopSource`; `visibilitychange` re-poll | 1, 2 |
| `tests/test_safety_log.py` **(NEW, 837 lines)** | 31 tests | DoD |

**`realtime/ingress.py` was NOT edited — see §7 deviation 1.** The card allowed
one edit there ("ONLY to attach the verbatim phrase to the latch it already
fires") and it turned out to be unnecessary: `IngressScan.original` already
carries the raw text into the runtime, and *which* rule fired is read through the
module's own exported `matches_spoken_emergency` predicate. The matcher, its
phrase set, its variants and its bounded-gap regex are byte-identical — and the
strongest available form of that claim: `ingress.py` **does not appear in
`git status` at all**, so it is byte-identical to the committed baseline, not
merely to this session's opening snapshot. **q34 "Dye. Stop." remains untested
and the widening remains owner-gated.**

Also untouched, by the same test — absent from `git status`: `safety.py`,
`core/arbiter.py`, `core/activities.py`, `runtime_channels.py`, `web_panel.py`,
`realtime/lane.py`, `realtime/protocol.py`, `realtime/tool_broker.py`,
`realtime/prompting.py`, the yield policy, `configs/**` and `evals/**`. The
working tree's other dirty paths (`agent.py`, `navigation/goals.py`,
`tests/test_realtime_tool_broker.py`, `tests/test_voice_nav_e2e.py`,
`tests/test_unknown_place_admission.py`) are **R20's uncommitted work and were
not touched, reverted or restaged by this card.** Nothing was committed, staged
or stashed; `git stash list` is empty and `git diff --cached` is empty.

**No `+`/`−` split is given, and that is deliberate.** All three source files were
already dirty with other cards' uncommitted work when this session opened
(`runtime.py` from R8–R20, `whisperer.py` from R13, `index.html` from R4-lite and
R9), so `git diff HEAD --numstat` cannot separate this card's share and any number
claiming to would be invented — R19 set this precedent for the same reason. The
honest measures are the gate arithmetic (§2), the file sizes as this card leaves
them (`runtime.py` 9897, `whisperer.py` 1339, `index.html` 2502) and the seed
harness's GOLD hashes, which are the same bytes the closing gate scored.

### 1.1 The ring, and why its shape is the mission log's

`_log_mission` is the proven pattern and this is deliberately the same one:

* **Its own deque, its own id counter, its own monotonic seam.** `_safety_clock`
  is separate from `_mission_clock` so a test that drives one cannot move the
  other.
* **A chatty kind that evicts itself first.** `MISSION_LOG_BLOCKED_MAX` keeps
  half the mission ring for lifecycle rows; `SAFETY_LOG_REJECTED_MAX` does the
  same here. The two constants are independent on purpose — R4-lite's open risk
  7 flagged that a future resize of one silently resizing the other is a
  coupling worth not having.
* **Coalesce, never drop.** A repeat inside `SAFETY_REJECT_MIN_INTERVAL_S`
  increments a count on the row already there and rewrites its sentence; a
  *different door* always writes its own row immediately, because live_run_1 had
  `play_gesture` and `navigate_to` refused in the same millisecond and an auditor
  needs both.
* **Copies out, not rows.** `safety_log` and the snapshot hand out `dict(row)`;
  the record goes to a browser, an eval harness and a status doc and none of them
  may edit it for the others.

One thing is NOT the mission log's: a repeated **latch** from the same source
while already latched folds into the existing row rather than appending. The
first row is the one carrying the words that actually latched the robot, and it
is never overwritten. live_run_1's owner said the phrase four times in one breath
(corpus queries 32 and 33 merged); that is one latch.

### 1.2 Two refusal observation points, because one is not enough

The first version watched only `SafetyLimits.validate`. The smoke probe killed
it: **`action("emergency_stop")` does not set `agent.safety.emergency_stopped`.**
Only four call sites do (`close`, `submit_voice_text`'s fast path,
`submit_realtime_transcript`, the simulator adopt); the panel/Space door engages
the arbiter and the control manager and leaves the local validator's flag clear.
So under a keyed latch `validate` *admits*, and the refusal happens deeper — in
`core/activities.py` ("Rejected during emergency stop") or in `agent.py`'s
admission reply ("Emergency stop is latched, so I can't take new movement
commands"), both outside this card's OWNS.

Watching the **door** rather than the validator covers every latch origin and
every refusing layer with one rule, and records the refusing layer's own words:

| Seam | Covers | Where |
| --- | --- | --- |
| `_refuse_under_latch(door)` | follow, owner search, navigation ×2, spatial ×2, pose ×2, trajectory ×2 | the runtime's own guard, ten sites, now one helper |
| `submit_motion`'s arbiter refusal | manual/panel/arrow-key motion | the layer the OWNER hits |
| `_watch_under_latch(door, call)` | `play_gesture`, `set_pose`, `navigate_to`, `circle_owner`, `follow_owner` | the hosted tool surface, whatever layer refuses |
| `_realtime_validate` | the validator's own refusals, with its own reason | the seam live_run_1 measured |

`get_status` and `recall_memory` are deliberately **not** wrapped: they are the
two tools an owner needs most while the robot is stopped, and a latch that made
them fail would be this card's own defect. Pinned by
`test_the_two_answering_tools_are_never_watched_and_never_refused`.

`_note_safety_rejection` returns immediately unless `self.arbiter.emergency_stopped`,
so an unknown pose or a malformed argument never lands in this ring —
`test_a_refusal_with_no_latch_up_is_never_recorded` is the over-correction guard.

### 1.3 The latch as a standing fact, not an edge

The whisperer's `_diff` fires `KIND_EMERGENCY_STOP` on the **rising edge** only.
That is right for unprompted speech and it is exactly why live_run_1's owner
heard nothing for 84 seconds: after the edge there is no more news. So the fix is
in two places, each doing what it is for:

* **`_realtime_status_digest`** gains an `emergency_stop` block —
  `{latched, source, seconds_latched, release}`. This is what a *status question*
  reaches. It is stated as facts about the world, not as an instruction to the
  model; the release sentence says what has to happen, not what to say.
* **`StateDigest.emergency_stop_source`** carries the door as a CLASS name, so
  the edge fact can name it: *"…has latched an emergency stop because the owner
  said the emergency stop phrase out loud and is not moving. It cannot move again
  until the emergency stop is released."*

The verbatim utterance deliberately does **not** enter the digest. That dataclass
says of itself "there is no free-text note in here on purpose", and the differ is
the only thing allowed to turn state into a class name. The words live on the
ring row, where a person reads them.

`STATE_DIGEST_VERSION` goes 2 → 3 by the module's own rule. It matters more here
than usual: `evals/20260820/voice_corpus_v1/live_run_1` was recorded under 2, and
it is *the run where a latch could not be attributed*. A reader that finds the
field missing must conclude "this recording could not name the door", never "the
latch had no door".

### 1.4 One constant replacing ten copies

Ten sites in `runtime.py` raised the literal `"motion is disabled by emergency
stop"` under an identical guard. They now call one helper that records and
raises, and the message is named once (`MOTION_DISABLED_BY_LATCH`). It is
deliberately **not** shared with `safety.py` or `core/arbiter.py`: those are
different layers with their own wording and importing one into the other would
couple two failure vocabularies that are allowed to disagree. The exception text
is byte-identical to what those sites raised before.

---

## §2 — Gate (verbatim, run after the final edit)

Opening baseline for this session, run before the first edit and read in full:

```
CI GATE — tier=commit  (2026-08-20T23:00:37Z)
[  PASS] HARD  default-suite             6987 passed, 9 skipped, 42 deselected, 5 warnings in 269.91s (0:04:29)
RESULT: PASS — every hard gate green.
```

**A correction to the card's stated baseline.** The dispatch note says "Baseline
entering this chain: 6732 passed". That is `AUDIT_R12_R16_FABLE`'s audited number
and it is four cards stale — R17–R20 have landed since (R19 reported 6861, R20
reported 6987). The measured baseline for THIS card is **6987**, and it is the
number the arithmetic below is against.

Closing gate, verbatim, saved at `<scratchpad>/r21/gate_final.txt`:

```
CI GATE — tier=commit  (2026-08-20T23:48:26Z)
==============================================================================
[  PASS] HARD  ruff                       7 violation(s), baseline 7, new 0
[  PASS] HARD  hard-safety                nav frozen baseline nav-instruct-v1-baseline-v4-20260811T070536Z: collisions=0 false_arrival=0 | mutation panel clean: collisions=0 no_false_arrival=True | mutation panel freshness: committed fields reproduce live = True | follow-bench: 7 row(s), hard_collision_total all 0 = True | walk_with_me: 1/2 row(s) with hard_collision_total, all 0 = True
[  PASS] HARD  frozen-digest-sentinels    4 immutable manifest(s) byte-identical to pin
[  PASS] HARD  release-parity             91 packaged asset(s) byte-identical to canonical source
[  PASS] HARD  latency-tail-ledger        latest row latency-20260810T082415Z-4d83035f: 6 metric series within 1.2x tail ceiling (rows=5, window=5)
[  PASS] HARD  follow-bench-jerk-ratchet  latest shipped row follow-bench-v1-20260811023618Z-93eba090.json: 1.2187 <= 1.46244 (baseline 1.2187 x 1.2)
[  PASS] HARD  model-off-non-inferiority  23 passed in 0.44s
[  PASS] HARD  frozen-digest-integrity    6 passed, 1 warning in 0.34s
[  PASS] HARD  release-parity-integrity   10 passed in 0.72s
[  PASS] HARD  mutation-panel-freshness   2 passed, 3 warnings in 4.21s
[  PASS] HARD  latency-tail               6 passed, 2 warnings in 0.30s
[  PASS] HARD  default-suite              7018 passed, 9 skipped, 42 deselected, 5 warnings in 268.84s (0:04:28)
==============================================================================
RESULT: PASS — every hard gate green.
  elapsed 281.5s
```

**6987 → 7018, +31, 0 removed** — exactly the new test file's 31 collected cases,
so this card added tests and broke none. `ruff` **new 0**: no violation was
baselined, and all four touched files are clean under `ruff check` on their own.

**One source, three kinds of evidence.** The closing gate, the seed harness's
GOLD snapshot and the live proofs all ran against the same bytes —
`runtime.py b814d80338c5185a`, `whisperer.py e92138a8531348d2`,
`index.html 89afbc87f0bde934`, `ingress.py 636ea47c3889dc61` (sha256, first 16),
still the tree's hashes at teardown. The full 20-seed sweep was re-run **after**
the last test edit, against these same bytes.

---

## §3 — Seeds: 20 seeded defects, 20/20 RED, 20/20 restored byte-identical

Harness `<scratchpad>/r21/r21_seeds.py`, results `<scratchpad>/r21/seeds.json`.
**R9 session-B, plus AUDIT_R12_R16 §register 1 in full:** every touched file is
snapshotted ONCE into GOLD at startup, repaired from GOLD before each seed if it
has drifted, restored from GOLD (never from "whatever was there") in `finally`,
and re-verified at teardown. After **every** write in either direction
`src/**/__pycache__` is purged, and a **fresh-interpreter canary** must see the
mutation on disk before the test target is allowed to run — a seed whose canary
fails is reported BROKEN, never RED. The harness asserts at import time that
every mutable path is under `src/parcel_robot/`. **No test, config or eval was
mutated at any point.**

GOLD hashes (sha256, first 16), which are also the bytes the closing gate scored:

```
src/parcel_robot/runtime.py             b814d80338c5185a
src/parcel_robot/realtime/whisperer.py  e92138a8531348d2
src/parcel_robot/realtime/ingress.py    636ea47c3889dc61
src/parcel_robot/ui/index.html          89afbc87f0bde934
```

| # | Seeded defect | File | Result |
| --- | --- | --- | --- |
| S1 | the safety ring is folded to one slot (the live_run_1 eviction, restored) | runtime | **RED** (7 failed) |
| S2 | refusal rows may fill the whole ring, so they evict the latch | runtime | **RED** |
| S3 | the latch SOURCE is dropped — every door records the same word | runtime | **RED** |
| S4 | the owner's VERBATIM utterance is dropped from the spoken latch | runtime | **RED** (7 failed) |
| S5 | the whisperer digest field is removed (always empty) | runtime | **RED** |
| S6 | a status question under a latch is silent again (the bare boolean) | runtime | **RED** |
| S7 | the substring match is ANCHORED to the start of the utterance | **ingress** | **RED** (14 failed) |
| S8 | motion refused under the latch is raised but never recorded | runtime | **RED** ¹ |
| S9 | refusals stop coalescing: one held key floods the ring | runtime | **RED** |
| S10 | the release is never recorded (latch-only ring) | runtime | **RED** |
| S11 | a repeat latch OVERWRITES the first row, losing the words that latched | runtime | **RED** |
| S12 | the panel stops rendering the ring | panel | **RED** ¹ |
| S13 | the spoken e-stop FACT loses the door it came through | whisperer | **RED** |
| S14 | the digest schema version is not bumped with the field | whisperer | **RED** |
| S15 | over-correction: ordinary refusals recorded as latch refusals | runtime | **RED** |
| S16 | the hosted motion doors are unwatched (a panel latch refuses silently) | runtime | **RED** |
| S17 | the ring hands out its own rows, so a reader can corrupt the record | runtime | **RED** |
| S18 | R9's banner is dropped while the source line stays (a half-edit) | panel | **RED** |
| S19 | the panel injects the owner utterance as markup | panel | **RED** |
| S20 | the e-stop doors stop reaching the ring at all (latch invisible again) | runtime | **RED** (13 failed) |

Teardown: `0 file(s) needed a final repair`; all four files match GOLD by sha256.

### ¹ Two seeds came back GREEN first, and both found a real hole in the tests

This is the harness earning its cost, so it is reported rather than smoothed over.

* **S8 — the test suite did not exercise `_refuse_under_latch` at all.** Every
  refusal test entered through `manual_motion`, which is refused by the *arbiter*
  inside `submit_motion` — a different layer with its own recording call. Deleting
  the recording from the runtime's own guard changed nothing any test could see.
  Fixed by `test_every_behaviour_door_that_refuses_under_the_latch_records_it_too`,
  which enters through `set_behavior("follow")`. The two refusal layers were a
  distinction I had written into the source and not into the tests.
* **S12 — a substring pin that a comment satisfied.** The panel test asserted
  `"renderSafetyLog(snapshot.safety_log);" in source`, and
  `// renderSafetyLog(snapshot.safety_log);` still contains that substring. Fixed
  by pinning the three render calls as one indented BLOCK, the way R9's
  `_SPACE_BRANCH` is pinned, so a comment-out or a reorder cannot pass.

Both were re-run after the fix: **S8 RED, S12 RED.** A third, smaller instance of
the same class was caught by a test failing on its own explanation — the
"never innerHTML" pin tripped over the comment saying *never innerHTML*; the pin
now strips `//` lines before asserting.

### The five the card's DoD names by hand, mapped

| DoD seed | Here |
| --- | --- |
| safety ring evicted / 1-slot | S1, S2, S20 |
| source dropped | S3, S4, S11 |
| digest field removed | S5, S13, S14 |
| status-under-latch silent | S6, S20 |
| substring match anchored | S7 |

---

## §4 — Tests added (31, `tests/test_safety_log.py`)

Organised as the five properties the incident demands, not as a tour of the code.

| Section | Tests | What they pin |
| --- | --- | --- |
| 1. the record survives | 4 | the latch is still attributable after 140 events have rolled the deque — **and the test asserts the deque lost it**, so it cannot pass by the deque quietly having grown; a flood of refusals cannot evict its own cause; the ring reaches the snapshot and survives `json.dumps`; readers get copies |
| 2. the record is attributable | 6 | verbatim words with whitespace collapsed exactly as the ledger collapses them; a keyed latch and a spoken latch are different rows; an adopted simulator latch is not reported as the owner's; one breath of repeats is one latch with its FIRST words kept; a latch after a release is its own row; the release names its door and how long the robot was stopped |
| 3. every refusal under the latch | 6 | the arbiter layer and the runtime-guard layer both record; repeats coalesce into a count; a different door always gets its own row; a refusal with no latch up is never recorded; a hosted tool refused under a PANEL latch is still recorded (§1.2); the two answering tools are never refused |
| 4. audible while it lasts | 6 | a status question 84 s in is answered with door, age and release condition; a robot that is fine never claims to be stopped; a released latch clears its door everywhere; the whisperer digest carries the door; the spoken FACT names the door and the way out; an UNKNOWN door produces no clause rather than a guessed one |
| 5. the substring property | 3 | the phrase latches from head, middle and tail — and the fixture asserts its own preamble is ≥ 8 words, so it cannot rot into a shallow case; bare "stop" stays whole-utterance exact through the real runtime; the deep match is visible as `rule: spoken_phrase` in the row it produces |
| 6. the panel | 4 | the ring is rendered on every poll (block pin); no `innerHTML` on an owner utterance; the banner names the door; the poll gate and the visibility re-read |

**The stop phrase is never re-typed in this file.** `LIVE_RUN_1_UTTERANCE` splices
it in from `ingress.SPOKEN_EMERGENCY_PHRASE`, because a test file is as good a
place as any to grow the fourth copy of a stop grammar and U33 is what that
costs. The repo's own pin agrees — see §7 deviation 3.

---

## §5 — Live proof

Own runtime, own sim backend, own scratch memory DB and own scratch
`realtime.yaml` under `<scratchpad>/r21/live/`. **The owner's stack was already
down** (`ss -ltnp` showed nothing on `:8765`), so nothing of theirs was disturbed
and nothing was posted to, started or restarted. `~/.config/parcel/realtime.yaml`
was never opened. The owner's `parcel_memory.sqlite3` is byte-identical before and
after (`sha256sum -c` → `OK`).

### 5.1 In-process — `<scratchpad>/r21/r21_live_report_20260820T233554Z.json` · $0.00

The live_run_1 utterance, verbatim from `ledger.json` id=2803, through the real
restricted ingress:

```
ingress outcome   {"kind": "emergency", "name": "stop",
                   "transcript": "Alright, let's go home and find the oh die stop …",
                   "reply": "Stopping.", "executed": true}
emergency_stopped True

safety ring
  [latched ] src=voice  count=1  Emergency stop latched by voice.
             Owner said: "Alright, let's go home and find the oh die stop die stop die stop die stop"
  [rejected] src=voice  count=3  Refused manual motion while emergency-stopped (x3):
                                 motion is disabled by emergency stop
  [released] src=panel  count=1  Emergency stop released by the panel
                                 (Space bar or the emergency-stop button) after 2.5 s.
  [latched ] src=panel  count=1  Emergency stop latched by the panel
                                 (Space bar or the emergency-stop button).

status under latch          {"latched": true, "source": "voice", "seconds_latched": 0.0,
                             "release": "the emergency stop must be released before …"}
status after 2.5 s          {"latched": true, "source": "voice", "seconds_latched": 2.5, …}
status after release        {"latched": false}
whisperer digest            emergency_stopped=True source='panel' schema=3

attributed latch left in events   []          <-- the incident, reproduced
```

That last line is the card's whole premise, measured: after 140 perception events
— the chatty afternoon live_run_1 actually had — R9's attributed
`Emergency stop latched by voice: …` panel event **is gone from `_events`**, and
the ring still holds the utterance. Every one of the card's four live-proof items
is in this block: source verbatim, status answered with the latched fact, release
logged with its duration, and a panel latch sitting next to a voice latch as two
distinguishable rows.

### 5.2 Scenario B — a PANEL latch and the hosted tool surface

A separate runtime on purpose: in scenario A the spoken stop leaves R3's
one-authority-per-utterance note set, so the model's follow-up tool calls are
dropped as *a second authority for one sentence* rather than by the latch. That
is correct behaviour and it is not the thing being measured.

```
tool calls   {"play_gesture": "dropped", "navigate_to": "dropped", "get_status": "ok"}

[latched ] src=panel  door=                  Emergency stop latched by the panel …
[rejected] src=panel  door=tool play_gesture Refused tool play_gesture while emergency-stopped:
                                             Rejected: Rejected during emergency stop
[rejected] src=panel  door=tool navigate_to  Refused tool navigate_to while emergency-stopped:
                                             Emergency stop is latched, so I can't take new …
```

Two different refusing layers, neither of them `SafetyLimits`, both recorded with
their own words — and `get_status` still answers. This is §1.2's hole, closed and
demonstrated.

### 5.3 Hosted — the real provider, and a confound I had to remove

Four sessions on `gpt-realtime-2.1-mini` through a real `RealtimeLane` (real
floor gate, real system-item tagging, real ledger). Total **$0.039462**.

The first comparison session was **invalid and is reported as such**: my own
instruction block said *"If the robot cannot move, say so in your first
sentence"* — which is the behaviour being measured — so all three variants passed
and the experiment proved nothing about the digest. Re-run with a plain companion
persona and no disclosure rule (the condition live_run_1 actually ran under), and
**one variant per session**, because three items in one session let the model
carry its own earlier sentence forward.

| Session | Handed up | What the companion said |
| --- | --- | --- |
| `rt_ba4ca614ca8b` | **A** — before the card: `emergency_stopped: true` and the ordinary status fields | "Right now, I'm in an emergency-stopped state. My battery is at 90%, the battery is normal, and I'm not navigating or following anything. **I'm staying safe and ready when you want me to move again.**" |
| `rt_7da9c37b391b` | **C** — this card: the `emergency_stop` block | "**Oof—big update, I can't move because the emergency stop is latched. It was activated by voice and has been held for about 84 seconds.** My battery is at 88 percent and normal, and I'm not navigating or following anything right now." |

A is a status recital that happens to include the latch, and its closing clause
is **actively wrong**: "ready when you want me to move again" tells the owner the
robot will move on request, which is false while latched — the same shape of
error as live_run_1's mood report. C leads with the consequence, names the door,
names the duration. **The honest limit: A did mention the latch**, because a
five-field status blob makes it hard to miss; live_run_1's real digest carried
scene, personality and more, and the fact was buried in it. This is a condition
that favours A, and C still wins on the three things an owner needs.

| Session | Purpose | Cost |
| --- | --- | --- |
| (aborted) | opened before a speaker sink was wired; raised at first audio | not sampled, small |
| `rt_aafe3daf3145` | first comparison, invalid (ledger read the wrong speaker label; floor gate skipped 2 of 3 narrations) | $0.0142592 |
| `rt_d618c3dd7d49` | the confounded three-item comparison, reported above | $0.0111224 |
| `rt_ba4ca614ca8b` | variant A, neutral persona, own session | $0.0066440 |
| `rt_7da9c37b391b` | variant C, neutral persona, own session | $0.0074360 |

**Total card spend: $0.039462** (plus one unsampled aborted session). Well under
the $1.50 cap.

### 5.4 A finding: live_run_1's artifacts ALREADY excluded a Space-key latch

Written up because it is evidence, not because the card asked for it.

Section (a) closed with *"the one hypothesis these artifacts cannot exclude is an
accidental Space-key latch."* They can. The four motion refusals in that run read
`Motion is disabled by emergency stop` — capital M, which is **`safety.py`'s**
wording and nothing else's in the tree. Every one of those six `safety.py`
branches is guarded by `self.emergency_stopped` on `SafetyLimits`, i.e.
`agent.safety.emergency_stopped`. Exactly four call sites set that flag, and
`action("emergency_stop")` — the Space bar and the red button — **is not one of
them** (verified in the committed baseline `HEAD:runtime.py` as well as the
working tree, so this predates the whole wave). A keyed latch produces the
*other* layers' wordings instead. Counting them in the run's own JSON:

| String | Layer it can only come from | Occurrences in live_run_1 |
| --- | --- | --- |
| `Motion is disabled by emergency stop` | `safety.py`, needs `agent.safety` latched | **15** |
| `Rejected during emergency stop` | `core/activities.py` — what a keyed latch gives | 0 |
| `Emergency stop is latched, so I` | `agent.py` admission — what a keyed latch gives | 0 |
| `Simulator emergency stop adopted` | the observe loop's adopt door | 0 |
| `legacy voice path handled a turn` | the legacy typed/mic door's own R5 warning | 0 |
| `Emergency stop latched by voice` | R9's attributed event — **evicted**, the card's premise | 0 |

Of the four doors that set `agent.safety`, teardown is excluded (the runtime ran
another 350 s), the simulator adopt and the legacy path are excluded by the
absence of their own signatures. **The remaining door is `submit_realtime_transcript`
— the hosted spoken phrase. The 14:28:19 attribution was right, and it was not a
Space latch.**

Two honest qualifications. First, this is a *fifth inference*, not the one-line
proof; it is stronger than the scorer's four because it rests on a layer
signature rather than on silence, but it is still an argument. Second, it depends
on an asymmetry that is arguably a defect (§8, owner-gated 1) — the day someone
unifies the latch doors, this signature disappears. That is exactly why the fix
is the ring and not this paragraph.

---

## §6 — Card item 2, answered: does the banner render in audio mode?

**Verified, and the answer is yes with one real caveat.** Nothing in the panel
branches on realtime mode for the banner: `renderSnapshot` reads
`snapshot.emergency_stopped` — the same field the badge reads, so a latch the
panel did not request raises it just the same — and it is called from `pollState`,
which is mode-independent. The banner therefore renders in an audio-mode session
exactly as it does in a text-mode one.

The caveat is not about the mode, it is about the **owner**. The poll interval is
gated on `!document.hidden`, deliberately, so a backgrounded tab does not spin.
In an audio-mode session the owner is talking, not looking, and very plausibly on
another tab — and a hidden tab's banner is frozen at whatever it last saw. So
visibility returning now triggers an immediate re-read instead of leaving a stale
safety state up until the next interval tick. R9's dead-man `clearMotionInputs()`
still runs first on the hidden edge; the ordering is pinned.

**What this does not fix, and cannot:** an owner who is not looking at the panel
at all. That is the whole of live_run_1 §b, and it is why the digest half of this
card (§1.3) is the substantive answer and the banner work is the smaller half.

---

## §7 — Deviations, each with its reason

1. **`realtime/ingress.py` was not edited at all**, though the card allowed one
   narrow edit. It proved unnecessary: `IngressScan.original` already carries the
   verbatim text into the runtime and the runtime records `ledger_text` (the same
   string the ledger keeps, so ring and ledger align word for word), while *which
   rule fired* comes from the module's own exported `matches_spoken_emergency`.
   Not touching a matcher is strictly better than touching it carefully. The file
   is byte-identical.

2. **Space and the panel button are ONE source (`panel`), not two.** The card
   lists them separately. The runtime cannot separate them: both post the
   identical `{"action": "emergency_stop"}` body from the same page, and
   `web_panel.py` — outside this card's OWNS — forwards only the action string.
   The tempting fix (a second action name, e.g. `emergency_stop_key`, posted by
   the Space branch) was **considered and rejected on safety grounds**:
   `index.html` is read at request time, so a panel reloaded from a
   *running older runtime* would post an action that runtime does not know, get a
   400, and **the Space bar would silently stop being an e-stop** — on the single
   most safety-critical control in the product, during exactly the deploy window
   this wave is heading into. It would also have required weakening R9's
   `test_space_latches_the_emergency_stop_and_not_the_nominal_stop`. What
   live_run_1 actually needed — telling a keyed latch from a spoken one — is what
   `panel` vs `voice` gives. Filed owner-gated (§8, 2).

3. **`tests/test_realtime_ingress.py::test_the_spoken_phrase_exists_exactly_once_in_the_source_tree`
   caught me, exactly as it caught R12.** A docstring I wrote in `runtime.py`
   spelled the owner's phrase while explaining the repeat-folding rule — a fourth
   copy of the stop grammar, in a card about the e-stop. The docstring now
   describes the case without spelling it and points at `ingress.py`. The pin
   was not touched; it worked.

4. **`emergency_stop()` and `clear_emergency_stop()` gained keyword arguments.**
   Additive and defaulted (`SAFETY_SOURCE_API`), so every existing caller —
   including the ~dozen tests that call them directly — is unchanged and passes.
   This is the R12 pattern (`stop_reason=`) applied to the door instead of the
   terminal.

5. **`submit_motion` gained a recording call on its refusal path.** That method
   is not obviously "the safety ring"; it is in scope because it is the layer the
   OWNER's own arrow key hits, and a ring that recorded every hosted tool but not
   the owner's own refused command would be answering the wrong half of §b.

6. **Two seeds came back GREEN and two tests were strengthened** before the final
   sweep (§3 ¹). Reported rather than quietly fixed.

7. **The first hosted comparison session was invalid** and is reported with its
   cost rather than dropped (§5.3).

8. **A redundant background full-suite run was stopped mid-flight.** It had been
   launched before the seed harness existed and would have been a concurrent
   reader of files the harness mutates — the precise hazard R9's session-B design
   exists to detect. The gate in §2 supersedes it.

---

## §8 — Owner-gated candidates (decisions, not defects)

1. **`action("emergency_stop")` does not engage `agent.safety`.** Long-standing
   (present in the committed baseline), and NOT a hole in the stop: motion is
   still blocked by the arbiter, the control manager and the runtime's own
   guards, and every path was demonstrated refused in §5.2. But it means one
   defence-in-depth layer sits idle under a keyed latch while it engages under a
   spoken one, and the *release* side is already unified
   (`clear_emergency_stop` clears `agent.safety`). Unifying the latch side is one
   line in `emergency_stop()`. It is a behaviour change on the e-stop path that
   this card was not asked to make, and it would erase the §5.4 signature, so it
   is filed, not done.
2. **Space vs the panel button as separate sources** (§7 deviation 2). Wants an
   origin field on `/api/action` in `web_panel.py` plus a panel edit, deployed
   together. Say the word and it is a small change plus its seeds.
3. **The refusal coalescing window is 10 s, chosen to match
   `MISSION_BLOCK_MIN_INTERVAL_S`** rather than measured. A model that hammers a
   motion tool for minutes produces a log that folds honestly (the count is
   always right) but coarsely.
4. **`SAFETY_LOG_MAX = 24` holds six complete latch/release cycles** with the
   refusal half full. A session with more incidents than that scrolls, and the
   oldest latch goes. Bigger is cheap if the owner wants it.

---

## §9 — does_not_prove

1. **It does not prove the panel renders correctly in a browser.** The panel has
   no JS test harness in this repo; §4's four panel tests are SOURCE pins in the
   style `test_prod_default_path.py` established for R9, and they are honestly
   weaker than driving a browser. They catch the defect class that actually
   occurs — a silent edit — and S12/S18/S19 show they catch it.
2. **It does not prove the model SPEAKS the latch unprompted.** §5.3 proves what
   the model says when a status question is asked and the answer is handed to it.
   The unprompted path is the whisperer's, its fact now names the door, and its
   forwarding is pinned offline — but no hosted session in this card heard the
   robot volunteer a latch it was not asked about.
3. **It does not prove anything about a spoken e-stop's latency.** The words still
   cross the network to become text before `submit_realtime_transcript` sees them.
   R9 said so, R12 repeated it, and this card does not change it.
4. **The hosted comparison is two sessions of one item each on one model.** It
   shows what the digest block does to a companion's sentence; it is not a
   measurement of how often the model gets it right.
5. **§5.4 is an inference, not a proof** (stated inline, and qualified twice).
6. **The `runtime_close` latch row is recorded but never observed by anyone** in
   practice, since the snapshot it would appear in is being torn down. It is
   there for completeness of "every latch", and no test claims it is useful.
7. **`seconds_latched` is wall-clock-free**: it is measured on the ring's
   monotonic seam, so it is a duration, not a timestamp. A latch that survives a
   process restart reports nothing, because the ring does not survive one either
   — this is an in-memory record like the mission log, not a persisted one.
8. **No `+`/`−` line attribution is claimed** (§1).

---

## §10 — Handoffs

* **The safety row schema is now a contract**: `kind` ∈ {latched, released,
  rejected}, plus `source`, `phrase`, `rule`, `door`, `level`, `text`, `count`,
  `timestamp`, `id`, and an optional `detail`. The panel switches on `kind` and
  `source`; a new source class must be added to `SAFETY_SOURCES`,
  `SAFETY_LATCH_SOURCE_WORDS`, `whisperer.ESTOP_SOURCE_PHRASES` and the panel's
  `SAFETY_SOURCE_LABELS`, or it degrades to the raw class name — deliberately,
  and pinned by `test_an_unknown_door_produces_no_clause_rather_than_a_guessed_one`.
* **`evals/.../voice_corpus_v1` session slices do not capture the new ring.**
  `test_voice_corpus_runner.py` asserts `set(slices) == {"mission_log", "events",
  "chat"}`; the runner is outside this card's OWNS. **Adding `safety_log` to that
  capture is the single highest-value follow-up for run 2** — it is the artifact
  whose absence produced this card.
* **`STATE_DIGEST_VERSION` is 3.** Anything replaying a recorded whisperer log
  must branch on it rather than assume the field.
* **Anyone adding a hosted motion tool** must wrap its door in
  `_watch_under_latch` at the `ToolDoors` construction, or its refusals under a
  latch will be invisible. Answering tools must NOT be wrapped. S16 is the seed
  that says so.

---

## §11 — Restart required

The changes are in `runtime.py`, `realtime/whisperer.py` and `ui/index.html`.
None of it is hot-reloadable — `index.html` is read at request time, but the
snapshot keys it renders come from the running runtime, so a panel reloaded
against an old runtime will simply show an empty safety log until the stack is
relaunched:

```
./scripts/launch_stack.sh
```

**Owner-visible outcome after that restart:** the panel gains a Safety log beside
the Mission log, and the e-stop banner says which door latched it and how long
ago. Ask a latched robot how it is doing and it leads with *"I can't move because
the emergency stop is latched — it was activated by voice and has been held for
about 84 seconds"* instead of listing it among its battery readings. Nothing
about what latches, or when, changed.

---

## §12 — Evidence artifacts (scratchpad, outside the repo)

`…/799cb356-4cb4-445b-a784-306b6c6fd4a6/scratchpad/r21/`

| File | What |
| --- | --- |
| `gate_baseline.txt` / `gate_final.txt` | the opening (6987) and closing gates |
| `r21_seeds.py` / `seeds.json` | the 20-seed harness and its results |
| `gold/` | the GOLD snapshots every seed restored from |
| `probe_ring.py` | the smoke probe that found §1.2 (the panel door not engaging `agent.safety`) |
| `r21_live_proof.py` | the in-process live harness, scenarios A and B |
| `r21_live_report_20260820T233554Z.json` | the live report quoted in §5.1/§5.2 |
| `r21_hosted_proof.py` | the hosted comparison harness |
| `r21_hosted_transcript_*.json` | four hosted sessions with their spend |
| `owner_db_before.txt` | the owner DB hash, verified `OK` after every run |

---

## §13 — Card DoD, line by line

| DoD item | Status |
| --- | --- |
| gate green | §2 — closing gate after the final edit |
| ≥ 6 seeds RED | **20/20 RED**, §3, all five named classes plus fifteen more |
| …safety ring evicted / 1-slot | S1, S2, S20 |
| …source dropped | S3, S4, S11 |
| …digest field removed | S5, S13, S14 |
| …status-under-latch silent | S6, S20 |
| …substring match anchored | S7 |
| item 1 — safety log ring, source, release, coalesced refusals, snapshot, panel | §1.1, §1.2, §4 §6, live §5.1 |
| item 2 — banner verified in audio mode; latched state in the digest | §6, §1.3 |
| item 3 — the substring property pinned as a test | §4 section 5, seed S7 |
| item 4 — live: verbatim source, status answered, release logged, Space ≠ spoken | §5.1, all four in one report |
| no matcher change; q34 stays owner-gated | §1 — `ingress.py` byte-identical |
| standard register | §0–§13; deviations §7, does_not_prove §9, owner-gated §8, handoffs §10 |
