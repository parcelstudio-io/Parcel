# P2-B — the dog notices you: identity, affect, and initiative · STATUS

**Executor:** Claude Opus · **Verifier:** Fable · **Date:** 2026-08-22
**Card:** `README.md` · **Board:** `../TASK_BOARD.md` · **Pre-registration:**
`PREREG.md` (written 02:27, before any measurement)

## Headline

All five deliverables landed and **all five pre-registered rows are met**. The
dog now greets the owner unprompted (once per appearance, measured at 2.0 s),
answers "I'm feeling sad" on the lane that ships with one ledger row and exactly
one gesture proposal, and stamps a speaker label on **100 % of realtime ledger
rows (7/7 over the mixed-traffic scenario)** — with **zero** whispers about the
unenrolled gate and **zero** new refusal paths anywhere.

**The absolute holds, and it is structure rather than intention.** Identity is a
label: `speaker_label()` is a pure function that mirrors `gate_decision()`'s
order and cannot reach it; `SpeakerLabel(blocking=True)` is a construction
error; and 56 parametrised combinations of class × verdict × enrolment assert
that the arming decision is byte-identical before and after a label is computed.
The emergency class labels `ungated` and arms in every one of them.

Four seeded mutations — identity gating the emergency class, a blocking label,
affect back on the legacy lane only, and greetings promoted into `CRITICAL_KINDS`
— turn **26 of the 125 new tests RED** on the exact guards
(`/home/jaewoo-jang/.cache/parcel-p2b/RED_p2b.txt`).

Two declared deviations, both named in §6. **No hosted session was opened and no
hosted money was spent** — the voice-tier A/B is a script plus a probe list, and
it has no provider client in it at all.

---

## 1. What changed

`git diff --numstat` against `5c7a2aa` (the commit that landed Wave P0 while
this card was in flight). `runtime.py` is edited by several cards concurrently,
so its row is **P2-B's share**, measured by attributing each `-U0` hunk.

| file | + / − | what |
|---|---|---|
| `src/parcel_robot/realtime/voice_identity.py` | +240 / −0 | the label layer: 5 labels, `SpeakerLabel`, `speaker_label()`, `unenrolled_label()`, `VoiceIdentityGate.label()`, the unenrolled-narration guard, `VOICE_LABEL_KIND` |
| `src/parcel_robot/realtime/whisperer.py` | +376 / −1 | 4 owner-event classes, their band membership + hints, `OwnerPresence`, `OwnerEventWatcher` |
| `src/parcel_robot/realtime/config.py` | +178 / −1 | `OwnerEventsConfig`, `whisperer.owner_events` + its validators (**deviation 1**) |
| `src/parcel_robot/realtime/__init__.py` | +4 / −0 | re-export `SpeakerLabel` / `speaker_label` |
| `src/parcel_robot/brain/router.py` | +89 / −0 | `affect_for_lane` / `lane_affect_from_evidence` + the verdict vocabulary |
| `src/parcel_robot/runtime.py` | **+367 / −2 (mine)** | see below |
| `configs/realtime.yaml.example` | +57 / −0 | the `owner_events` block, documented, **off** |
| `configs/realtime.prototype.yaml.example` | +53 / −2 | the same block, **on**, + two header departures (**deviation 2**) |
| `tests/test_prototype_profile.py` | **+68 / −19 whole-file; +6 / −0 mine** | the two new departures added to P0-A's completeness set (**deviation 2**); the other +62 / −19 are P1-E's concurrent edit — see §9.3 |
| **new** `tools/voice_tier_ab.py` | +488 | the A/B script, 12 probes, the protocol, the comparison |
| **new** `tests/test_p2b_owner_awareness.py` | +1054 | 125 tests |
| **new** `task_11/PREREG.md`, `task_11/P2B_STATUS.md` | — | the register |

`runtime.py`, my hunks only:

* the three import edits (`lane_affect_from_evidence`; `VOICE_LABEL_KIND` /
  `SpeakerLabel` / `speaker_label` / `unenrolled_label`; `OwnerEventWatcher` /
  `OwnerPresence` / `OWNER_SOURCE_*`);
* four module constants: `AFFECT_HISTORY_MAX`, `SPEAKER_LABEL_HISTORY_MAX`,
  `REALTIME_CONVERSATIONAL_SPEAKERS`;
* `__init__`: `realtime_owner_events`, `_affect_history`, `_speaker_labels`,
  the two coverage counters — built beside P0-B's `Whisperer`, and
  unconditionally, for the same reason it is;
* `_hosted_affect`: **extended, not duplicated** (the card's binding "Build on
  P0") — the reading now comes back through `lane_affect_from_evidence`, the row
  carries `speaker=<label>`, and the admitted reading is appended to the history;
* the **one new contiguous region** immediately after it:
  `_speaker_label_for`, `_stamp_speaker_label`, `speaker_label_rows`,
  `identity_label_coverage`, `_record_affect`, `affect_history`,
  `note_realtime_turn`, `owner_presence_sample`, `_step_owner_events`;
* `_write_realtime_ledger`: a `kind` kwarg, the stamp, the turn note;
* `_RealtimeLedgerMirror.write_realtime_turn`: the same stamp for the ROBOT's
  half of the conversation;
* `_step_whisperer`: one call to `_step_owner_events` on the same 1 Hz beat;
* `realtime_snapshot`: `owner_events` + `identity_labels`, constructed branch;
* two `kind=` kwargs at the existing ledger call sites.

Nothing else in `runtime.py` is mine. Not touched: `memory.py`,
`tiered_memory.py`, `realtime/prompting.py`, `realtime/lane.py`,
`realtime/tool_broker.py` (P2-A/P0-B), the safety core, `prompts/**`,
`pyproject.toml`, `scripts/ci_gate.py`, `docs/`, `backlog/`, `scrum/20260821/`,
the owner's live store.

---

## 2. The four deliverables, and the shape of each

### 1. Identity is a LABEL, not a gate

`voice_identity.py` gains a section that is deliberately *below* the arming
section and cannot reach it. Five labels, and the distinction that matters most
is the one between two of them:

| label | means | when |
|---|---|---|
| `owner` | verified against the enrolled profile | `armed` |
| `not_owner` | verified, and it was somebody else | `not_owner`, `rejected_sector` |
| `unverified` | the check RAN and abstained | `too_short`, `pending`, `verify_error` |
| `unenrolled` | there IS no check | no profile / no embedder / no gate object |
| `ungated` | identity had no say | the emergency class, always |

`unverified` and `unenrolled` are different facts and are never conflated:
before `tools/enroll_owner_voice.py` is run every row is `unenrolled`, which is
the truth, and it is stamped rather than left blank.

The stamp goes on the row's **record**, not inside the row's **text**. The
memory tail replays the owner's words to the model verbatim on every reconnect;
a verdict spliced into them would be the product editing the owner. The one
exception is the affect row, which is the product's own sentence
(`[affect sad] … speaker=unenrolled`).

Two doors write realtime ledger rows and **both** stamp:
`RobotRuntime._write_realtime_ledger` (owner + system) and
`_RealtimeLedgerMirror.write_realtime_turn` (robot). "Every row" is not a claim
about half a conversation.

`identity_label_coverage()` publishes `rows_written` / `rows_labelled` /
`coverage` / `blocking: False` as **cumulative** counters, so the row survives
the 400-entry ring rolling over on a long session.

**"The gate is silent about itself"** is implemented structurally rather than at
each call site: `note_rejection()` returns `False` on an unenrolled gate, so
there is no path from a build with no profile to a spoken sentence. The count
still moves (a refusal that happened, happened). With no profile the gate arms
everything anyway, so this is defence in depth — which is exactly what makes it
survive a future caller that forgets to check.

### 2. Affect on the hosted lane

`brain/router.py` gains the entry the card asked for, with a closed verdict
vocabulary — `no_explicit_affect` / `below_minimum_confidence` / `admitted` —
so a lane can log a below-bar reading honestly instead of dropping it silently.
It is split into two entries on purpose: `affect_for_lane(text, …)` for callers
that want the whole question, and `lane_affect_from_evidence(evidence, …)` for
`runtime._hosted_affect`, which must keep the GRAMMAR call at its own module
boundary because that is the seam P0-B's tests reach through. One bar, two
entries, no second copy of the comparison.

`affect_history(limit=0)` is the public API P2-A's distiller may consume: a list
of plain JSON-safe dicts, **copied on the way out**, holding label, confidence,
action, transcript, the speaker label and its code, session/item ids and the
lane. The rows are an INDEX; the durable copy is the `[affect …]` ledger row,
and if the two ever disagree the ledger is right.

Identity says WHO, never WHETHER: an `unenrolled` or `not_owner` speaker still
gets the comfort gesture. Pinned by
`test_an_unenrolled_speaker_still_gets_the_comfort_gesture`.

### 3. Owner-event classes in the whisperer

Four new classes, all in `ALWAYS_BAND`, **none** in `CRITICAL_KINDS`:

| class | fires | dedup key |
|---|---|---|
| `owner_appeared` | rising edge, after ≥ `absence_s` away | `owner_appeared:<episode>` |
| `owner_returned` | the same edge after ≥ `long_absence_h` | `owner_returned:<N>h` |
| `greeting_due` | present, and both sides quiet ≥ `greeting_interval_s` | `greeting_due:<episode>:<t>` |
| `question_of_the_day` | present, once per calendar day | `question_of_the_day:<day>` |

The card names the second one `owner_returned_after_Nh`; the **N lives in the
key and in the fact**, not in the class name, because a class table that grows a
row per hour is a class table that stops being a closed vocabulary. Exactly one
of appeared/returned fires per appearance — never both.

`OwnerEventWatcher` obeys three house rules, and the first is a return type
rather than a policy: **at most one event per `observe()` call**. An appearance,
a greeting and a question that all come due on the same tick cannot become three
sentences in one breath, whatever the cap says. Every class is additionally
latched per episode / per day. The whisperer's cap is the second line of
defence, not the first — a cap permanently saturated by greetings has stopped
being a cost knob.

**The digest schema was NOT touched.** `STATE_DIGEST_VERSION` is still 3 and
`StateDigest` still has exactly its R21 field set, so every frozen whisperer
fixture and every recorded decision log is unmoved. The watcher is fed from the
runtime and offers through `Whisperer.offer` — the same door `_whisper` already
used — which is why owner events ride the existing band, dedup, min-gap and cap
machinery without a single new mechanism.

**The P1-C drop-in.** `RobotRuntime.owner_presence_sample()` adapts whatever
owner track the build has into one `OwnerPresence` (present, confidence,
source). Today that is the mocap/UWB track (`observation.owner`, and a **stale
observation is not a sighting** — the confidence-1.0 defect of audit §1 must not
reappear as a greeting). When P1-C lands `OwnerTrackV1`, the seam reads
`identity_score` and `state` and stamps `source: pixels`; the watcher takes a
boolean, a number and a name and has no opinion about where they came from,
which is why its tests need no camera.

### 4. The voice-tier experiment (owner action, packaged)

`tools/voice_tier_ab.py`, and the first thing to say about it is what it cannot
do: **there is no provider client in the file** and a test asserts the absence
of `openai` / `websocket` / `RealtimeLane` / `api_key` / `Authorization` in its
source. The owner runs the session.

* `--plan` writes `probes.tsv` and a `scoresheet.md` and prints the run order.
* `--capture --tier {mini,full} --port N` walks the 12 probes, taking READ-ONLY
  `GET /api/state` snapshots either side of each one, and refuses port 8765
  outright. It also refuses to record an arm whose running `model:` does not
  match the tier — a mislabelled file is worse than no file.
* `--compare A.json B.json` prints and writes the mechanical table (elapsed,
  usage rows, spend, tool calls, narrations, stalls) and says plainly that
  warmth and taste are on the scoresheet and not in it.

**The one config line** is `model:` — `gpt-realtime-2.1-mini` vs
`gpt-realtime-2.1`. Note for the owner: `configs/realtime.prototype.yaml.example`
already ships arm B (`gpt-realtime-2.1`, P0-A's choice), so the **mini arm is
the one that needs the edit**.

---

## 3. The five pre-registered rows, measured

Pre-registered in `PREREG.md` before any measurement. Scripts:
`/home/jaewoo-jang/.cache/parcel-p2b/measure_rows.py` and `measure_rows2.py`.

| # | row | bound | measured | verdict |
|---|---|---|---|---|
| 1 | greet-on-appearance | once per appearance, ≤ 5.0 s | **1 greeting, 2.0 s** | **MET** |
| 2 | "I'm sad" | 1 affect row + 1 gesture, one turn | **1 row, 1 proposal** | **MET** |
| 3 | identity verdict on every row | 100 % | **7/7 = 1.0000**, labels `{unenrolled: 6, ungated: 1}` | **MET** |
| 4 | whispers about the unenrolled gate | 0 | **0** identity rows in the decision log; `note_rejection` = `False`×5 with 5 counted, 0 narrated | **MET** |
| 5 | greeting storms | ≤ the configured cap, and ≤ 6/min | see below | **MET** |

Row 5, a track flapping every two seconds for 600 s — the worst input the
watcher can be given — offered through the real `Whisperer`:

| cap / window | events produced | worst inside one window | worst per minute |
|---|---|---|---|
| 2 per 60 s (shipped default) | 20 | **2** (bound 2) | **2** |
| 2 per 30 s | 38 | **2** (bound 2) | **4** |
| 6 per 60 s (**the prototype overlay**) | 60 | **6** (bound 6) | **6** (bound 6) |

Row 2's actual artifact:

```
[affect sad] confidence=1.00 action=comfort_bow transcript="I'm feeling sad today" speaker=unenrolled
```

---

## 4. Seeded RED

Four mutations applied to a **copy** of the current source tree at
`/home/jaewoo-jang/.cache/parcel-p2b/seed/src`, run with
`PYTHONPATH=<seed>/src`. This is mutation-seeding, not HEAD-seeding, and it is
declared as such: at `5c7a2aa` these symbols do not exist at all, so a HEAD run
would fail at import and prove nothing about behaviour. Each mutation is the
plausible defect, written the way somebody would actually write it.

| seed | mutation | tests that go RED |
|---|---|---|
| **1a gate-becomes-blocking** | `gates_kind` returns `True` for the emergency class too | `test_no_state_of_the_gate_can_make_the_emergency_class_blocking` (14), `test_an_unenrolled_build_labels_every_row_and_arms_everything`, `test_the_emergency_row_is_labelled_ungated_and_not_guessed` |
| **1b blocking label** | `SpeakerLabel.__post_init__` permits `blocking=True` | `test_a_blocking_label_is_a_refusal_to_construct` |
| **2 affect-on-legacy-only** | `_hosted_affect` returns `""` immediately | `test_i_am_sad_yields_one_row_and_one_gesture`, `test_the_affect_history_is_a_public_api_p2a_can_read`, `test_an_unenrolled_speaker_still_gets_the_comfort_gesture` |
| **3 greeting storms past the cap** | `OWNER_EVENT_KINDS` folded into `CRITICAL_KINDS` | `test_no_owner_event_is_critical`, `test_a_flapping_track_can_never_spend_past_the_owners_cap` (3), `test_an_owner_event_obeys_the_min_gap_like_every_other_fact` |
| **4 unlabelled rows** | the ledger counts a row and never labels it | `test_every_ledger_row_carries_an_identity_label` |

```
$ PYTHONPATH=<seed>/src .parcel/bin/python -m pytest -q tests/test_p2b_owner_awareness.py
26 failed, 99 passed, 1 warning in 1.42s
```

Full output: `/home/jaewoo-jang/.cache/parcel-p2b/RED_p2b.txt`.

Honest note: `test_a_label_can_never_change_an_arming_decision` stays GREEN
under seed 1a — it compares `gate_decision` to itself, which the mutation moves
consistently. The emergency arm of that seed is caught by its sibling above,
which is why both tests exist.

---

## 5. How it was verified (GREEN)

```
$ .parcel/bin/python -m pytest -q tests/test_p2b_owner_awareness.py
125 passed, 1 warning in 1.00s

$ .parcel/bin/python -m pytest -q tests/test_p2b_owner_awareness.py tests/test_realtime_*.py \
      tests/test_runtime_whisperer_wiring.py tests/test_p0b_companion_unlocks.py \
      tests/test_prototype_profile.py tests/test_brain_router.py
1459 passed, 2 skipped, 2 xfailed, 1 warning in 23.73s

$ .parcel/bin/python -m pytest -q tests/test_scene_and_memory_answers.py tests/test_mission_log.py \
      tests/test_arrival_semantics.py tests/test_owner_estop.py tests/test_safety_log.py \
      tests/test_fail_closed_limits.py tests/test_closed_intent_product_path.py \
      tests/test_brain_contracts.py
414 passed, 2 warnings in 7.83s

$ .parcel/bin/ruff check src/parcel_robot/realtime/voice_identity.py \
      src/parcel_robot/realtime/whisperer.py src/parcel_robot/realtime/config.py \
      src/parcel_robot/realtime/__init__.py src/parcel_robot/brain/router.py \
      src/parcel_robot/runtime.py tools/voice_tier_ab.py \
      tests/test_p2b_owner_awareness.py tests/test_prototype_profile.py
All checks passed!
```

Both example configs still load through the real validator, and a config written
before this card is unchanged by it (`owner_events` absent ⇒ `enabled: False`,
every other value at its documented default) — pinned by
`test_a_config_written_before_this_card_is_unchanged_by_it`.

**Two reds in the tree are not mine and were not touched:**

* `tests/test_r24_lock_discipline.py::test_the_lock_roster_is_complete` —
  `RobotRuntime.__init__` constructs `_p1b_map_lock`, card **P1-B**'s. This card
  deliberately took **no new lock** (everything reuses `self._lock` for a short
  ring/counter section), which is why nothing of mine appears in that diff.
* Mid-run, `realtime/lane.py` referenced `MAX_TAIL_ITEMS` before P2-A had
  defined it, and `tool_broker.py` referenced `_fact_key` likewise. Both cleared
  on their own while this card was running; the final runs above are green.

Neither `scripts/ci_gate.py` nor the full suite was run, per the card.

---

## 6. Deviations from OWNS (declared)

1. **`src/parcel_robot/realtime/config.py` (+178 / −1).** P0-B's file, and P0-B
   has closed — so it is open under the wave's Edit-only + re-read rule, which is
   what I used. Deliverable 3 says the owner-event bands ride "the existing
   cap/cost/band machinery"; the knobs therefore belong **inside** the
   `whisperer:` block, next to the cap that bounds them, and that block's
   validator lives here. The alternative — a top-level `owner_events:` key — would
   have put the greeting schedule in one place and the budget that governs it in
   another, which is precisely the drift this file's fail-closed discipline
   exists to prevent. The edit is additive: one new key in
   `WHISPERER_ALLOWED_KEYS`, one frozen dataclass, one validator and four small
   helpers. Every existing key, message and default is untouched.

2. **`configs/realtime.prototype.yaml.example` (+53 / −2) and
   `tests/test_prototype_profile.py` (+6 / −0 of a +68 / −19 whole-file diff —
   the rest is P1-E's, see §9.3).** P0-A's, also closed, also open
   under the same rule. The card's "Build on P0" says prototype-only values go in
   the overlay — so `owner_events.enabled: true` (and a 600 s greeting interval)
   belongs there rather than in the shipped example. P0-A's
   `test_realtime_prototype_example_validates_and_carries_its_departures` asserts
   the departure list is **complete**, in the file header *and* in a literal set,
   which is a re-sync gate working exactly as designed: it went red the moment I
   added the block, and the fix is to name the two new departures in both places.
   That is a two-line addition to a literal set and two lines in the file header
   ("EIGHT values" → "TEN values"); no existing departure was altered and no
   assertion was weakened.

### Corrections to the pre-registration, declared

`PREREG.md` says row 5's prototype cap is "4/min (2 per 30 s), stricter than the
card's 6/min", taken from **P0-B's recommended** whisperer block. The **landed**
`configs/realtime.prototype.yaml.example` (P0-A's merge) carries
`max_updates_per_minute: 6, window_s: 60.0` — i.e. exactly the card's 6/min.
Row 5 is scored against the configured cap either way and is reported at all
three operating points in §3, so the correction moves no verdict; it is recorded
because the pre-registration said something that turned out to be about a file
that was never shipped.

### Interpretations worth a verifier's eye

* **`owner_returned_after_Nh`** is the class `owner_returned` with N in the
  dedup key and in the fact (§2.3). A grep for the card's literal string finds
  nothing; a grep for `owner_returned` finds it.
* **`owner_events` is default-OFF in the shipped example.** The card's whole
  point is a companion that greets you, and I still shipped the default off,
  following P0-B's precedent exactly: every forward is a billed hosted response
  and a config written before this card must keep costing what it cost. The
  prototype overlay — the thing a `--prototype` launch actually loads — has it
  on. If the verifier reads the card as requiring default-on, this is the line
  to change and it is one line.
* **`realtime_snapshot()` publishes the two new blobs in the CONSTRUCTED branch
  only.** The flag-off branch is pinned by an exact-equality assertion in
  `tests/test_realtime_tool_broker.py` (R3's, not mine); rather than edit a third
  card's test I kept the per-session counters out of a snapshot that has no
  session. Nothing is hidden: the owner-event *configuration* is visible
  flag-off through `config.whisperer.owner_events`.
* **System rows do not reset the greeting timer.** Only `owner` and `robot` rows
  count as company (`REALTIME_CONVERSATIONAL_SPEAKERS`), so a `[session
  rollover]` note cannot postpone a greeting by the product talking to itself.

---

## 7. What this does not prove

* **No hosted session was opened, by me or by the tooling.** Every measurement
  above is the unit rigs and a scripted track on a frozen clock. Whether
  `gpt-realtime` turns `owner_appeared` into a warm hello or into "my owner
  tracking reports you have come into view" is a question about the model's
  taste, and the HINT is the only defence this card has against the second
  answer. **Watch the first live greeting.** The A/B probe list (P11/P12) is
  aimed straight at it.
* **The owner track is still mocap.** `owner_presence_sample` reads
  `observation.owner`, whose confidence is 1.0 by construction — the audit §1
  defect. Staleness is checked, so a frozen observation is not a sighting, but
  "the owner is here" is still a simulator's opinion until P1-C lands. The
  `min_confidence` knob has therefore been *validated* and never *exercised
  against a real similarity*.
* **`question_of_the_day` uses `time.strftime("%Y-%m-%d")`** — local wall time,
  no timezone reasoning, no handling of a machine that sleeps across midnight.
  Once per calendar day as the host sees it, and that is all it claims.
* **`explicit_affect_from_text` still always returns confidence 1.0.** The
  below-bar arm of the new verdict vocabulary is reachable only by raising
  `minimum_confidence` above 1.0 or by injecting evidence; no real transcript is
  below the prototype's 0.5.
* **The affect history is per-process.** It is an index over the ledger and dies
  with the runtime; a distiller that needs history across restarts must read the
  `[affect …]` rows, which is why the row format is machine-readable and why the
  history says so in its docstring.
* **`greeting_due` has never run for a real fifteen minutes.** It is exercised
  on a hand-advanced clock.
* **The identity labels are `unenrolled` everywhere in every measurement**,
  because no owner profile is enrolled on this host. The `owner` / `not_owner`
  arms are proven against a `FakeSpeakerEmbedder` and against constructed
  verdicts, not against the owner's actual voice. `tools/enroll_owner_voice.py`
  is still the owner action that turns them on, and the card's promise is that
  the system is correct on both sides of it.

---

## 8. Handoffs

* **The owner** — three things, in this order: (1) run
  `tools/enroll_owner_voice.py` (1 min) and the labels stop reading
  `unenrolled`; (2) launch `--prototype` and let the dog see you leave and come
  back — that is the first live test of §2.3; (3) the voice-tier A/B, one
  session per arm, starting with `.parcel/bin/python tools/voice_tier_ab.py
  --plan --out ~/.cache/parcel-p2b/tier_ab`. Remember the prototype example
  already carries the **full-size** model, so the mini arm is the edit.
* **P2-A (task_10)** — `RobotRuntime.affect_history(limit=0)` is the public API
  the card promised your distiller: JSON-safe dicts, copied out, newest last,
  each carrying `label`, `confidence`, `action`, `transcript`, `speaker`,
  `speaker_code`, `session_id`, `lane`. `speaker_label_rows()` and
  `identity_label_coverage()` are the identity equivalents. I touched none of
  your files.
* **P1-C (task_8)** — the drop-in point is
  `RobotRuntime.owner_presence_sample()`. Set `self.owner_track` to your
  `OwnerTrackV1` and it reads `state` ∈ {`confirmed`, `tracking`} and
  `identity_score`, stamping `source: pixels`; nothing in `whisperer.py` changes.
  `whisperer.owner_events.min_confidence` is the knob your measured similarity
  meets — 0.3 is a prototype value chosen with no pixel track to calibrate
  against, so it is yours to move.
* **P1-D (task_9)** — the identity label is now on every row and is deliberately
  *not* an input to any ADMIT/ASK/REFUSE decision. If your roster ever wants to
  read it, that is a new decision and it needs its own card: this one is bound to
  "a label, not a gate".
* **Fable** — start at §6 (the two deviations are the diff-vs-OWNS mismatches
  you will find), then §3 (the five rows) and §4 (the RED artifact and the seed
  tree, both still on disk under `/home/jaewoo-jang/.cache/parcel-p2b/`). The
  `_p1b_map_lock` red in `test_r24_lock_discipline.py` is P1-B's, not mine.
* **Phase 3 (flywheel)** — this card leaves three new machine-readable streams:
  the `[affect …]` rows (now with a speaker), the whisperer decision log's
  owner-event rows (why the dog spoke, or why it stayed quiet), and
  `question_of_the_day` — the first input to the owner model that the robot
  asked for rather than overheard.

---

## 9. Post-verification corrections

Verdict **CLAIMS_HOLD** (Fable, 2026-08-22): every pre-registered row, the
identity-as-label proof, the `_hosted_affect` extension, the cap arithmetic, the
seeds (26/125 reproduced from the seed tree) and the zero-hosted-spend claim all
reproduced. The 02:06–02:09 hosted rows in `recordings/spend.jsonl` are the
**owner's own desk session** on the live panel against pre-P2-B code — attributed
there, not to this card. Three doc-accuracy corrections were requested before
close; all three are made below, and **no source behaviour changed**.

### 9.1 The parametrised matrix is 56, not 28

`test_a_label_can_never_change_an_arming_decision` collects **56** cases —
7 verdicts × 2 enrolment states × 4 classes — not the 28 the headline and the
test docstring claimed. Corrected in both places. The test was always stronger
than the claim about it, which is the right direction for the error to have gone
but not a reason to leave it standing.

### 9.2 `VoiceIdentityGate.label()` is not pure — `speaker_label()` is

The §2.1 sentence "a pure function that … takes no lock, starts no verification"
is true of the **module-level `speaker_label()`** and only of it. The gate
METHOD `VoiceIdentityGate.label()` calls `current()`, which may settle an
open-but-silent turn under the gate's lock and run the embedder for that turn's
final verify. It is therefore observable and can cost an embedding.

What still holds, and is what the card's absolute actually needs:

* `label()` never calls `gate_decision()` and returns a `SpeakerLabel`, which no
  caller can arm or refuse anything with;
* on the product path the ORDER settles it — `submit_realtime_transcript` takes
  its arming decision at `runtime.py` ~L6346, and the ledger write that stamps
  the label happens at ~L6407. The arming outcome for a turn is already fixed
  before a label for that turn is ever computed, so a settle triggered by
  labelling cannot change it.

The honest one-line version: **labelling can read the gate; it cannot gate.**

### 9.3 `tests/test_prototype_profile.py`'s numstat is not all mine

Against `904edd2` the whole-file diff is **+68 / −19**. **P2-B's share is the
6-line addition to the `differing` literal set** (the two new departure paths
plus their explanatory comment). The remaining +62 / −19 is **P1-E**'s concurrent
edit to the same file, landed while this card was running. A reader diffing that
file against `904edd2` and attributing all of it to P2-B would be misled; §1 and
§6 now say so at both mentions.
