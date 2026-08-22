# CURIO-1 — the dog talks about what it sees · STATUS

**Executor:** Claude Opus · **Verifier:** Fable · **Date:** 2026-08-22
**Card:** `README.md` · **Board:** `../TASK_BOARD.md` · **Pre-registration:**
`CURIO1_PREREGISTRATION.md` (written before the first line of source was edited)
**HEAD:** `8862220`

## Headline

The dog now remarks on what it has seen, and in a 120 s sim roam of `city_block`
with the real lane open it said **six things, all of them true**: six places
named, six of them in `known_places()` at the moment of speaking, **zero
hallucinated**, **zero** while the owner was owed an answer, worst minute **4
against a cap of 6**, and **no provider was contacted at any point**.

The absolute is structural rather than intentional. A curiosity class is MIDDLE
band, which in this module means "a deterministic mechanism decides" — so a
curiosity event handed to bare `Whisperer.offer` is refused with
`middle_band_requires_a_mechanism`, and the only door is
`offer_curiosity`, which the `ChatterScheduler` calls and nothing else does.
Every name that reaches it has passed one function,
`_curiosity_admitted_names`, which requires the name to be in `known_places()`
**and** not carried by a `vlm_proposed` guess — and re-checks that at the moment
of speaking rather than at the moment of noticing.

**Five seeded mutations turn nine of the fifty-one new tests RED** on the exact
guards, run against a COPY of the tree so that six concurrent cards never see a
red that is not theirs — and the product tree's sha256s are recorded identical
before and after (`/home/jaewoo-jang/.cache/parcel-curio1/SEEDED_RED.json`).

**All seven pre-registered rows are MET.** One thing in the CARD is
self-contradictory and is named here rather than quietly resolved: "Poisson gaps,
mean 4–8 min" and "3–6 utterances in a 120 s roam" describe two different
configurations and cannot both hold. The pre-registration named both operating
points before any measurement and scored row 1 at the roam arm, which is the
point the card wrote a bound for; the shipping cadence is measured beside it (0
remarks in 120 s, which is the arithmetic working). **The shipped default is the
card's 4–8 minute cadence, not the roam arm's.**

**The most important limitation, up front:** only ONE of the four curiosity
classes fired end-to-end. Every remark in every roam was `novel_object`; the
other three are structurally unreachable in a 120 s sim roam and are proven at
unit level only. §6 says exactly why for each.

---

## 1. What changed

`git diff --stat` against `8862220`. **`runtime.py`, `config.py` and the
prototype example are being edited by other cards RIGHT NOW** (ROAM-1 in
`runtime.py`, TURN-1 in `config.py` and the prototype example), so every row
below carries CURIO-1's share, attributed hunk by hunk from `git diff -U0`
(`/home/jaewoo-jang/.cache/parcel-curio1/attribute.py`).

| file | whole-file | **CURIO-1's share** | what |
|---|---|---|---|
| `src/parcel_robot/realtime/whisperer.py` | +644 / −3 | **+644 / −3** | 5 classes, their bands + HINTS, `offer_curiosity`, `ChatterScheduler`, `FarewellWatcher`, `curiosity_event`, time bands |
| `src/parcel_robot/realtime/config.py` | +379 / −3 | **+216 / −1** | `CuriosityConfig`, `CURIOSITY_ALLOWED_KEYS`, `curiosity_config_from_mapping` + validators, `whisperer.curiosity` |
| `src/parcel_robot/runtime.py` | +931 / −0 | **+831 / −0** | one marked feed region + one call line in `_step_whisperer` + 6 names on the whisperer import |
| `configs/realtime.prototype.yaml.example` | +133 / −0 | **+61 / −0** | the `curiosity:` block, on |
| **new** `tests/test_curio1_chatter.py` | +1148 | +1148 | 51 tests |
| **new** `task_24/CURIO1_PREREGISTRATION.md`, `CURIO1_STATUS.md` | — | — | the register |

The −3 in `whisperer.py` is one comment line and the one-line `MIDDLE_BAND`
literal, rewritten to add the curiosity classes. The −1 in `config.py` is the
one-line `WHISPERER_ALLOWED_KEYS` literal. **Nothing else was deleted anywhere.**

Not touched: `online_map/` (consumed through `known_places()`, `active_entries()`
and `resolve()` only), `vlm_veto/`, `realtime/tool_broker.py` (ROAM-1),
`realtime/lane.py`, `prompts/**` (including `prompts/functions/patrol.yaml`),
`configs/realtime.yaml.example`, `tests/test_prototype_profile.py`,
`scripts/ci_gate.py`, `pyproject.toml`, `docs/`, `backlog/`, `scrum/20260821/`,
the safety core, the owner's store.

---

## 2. The shape, and the four things it is built to make impossible

### 2.1 A remark can only name a place the map has ADMITTED

One function, `RobotRuntime._curiosity_admitted_names`, and two tests in it:

1. the name is in `known_places()` — the map's own vocabulary, which already
   drops decayed entries and inadmissible names;
2. no active entry carries that name with `vlm_proposed` provenance.

Test 2 is belt-and-braces today and load-bearing tomorrow. `known_places()`
already filters on `ProposedName.admissible`, so on today's `entries.py` an
un-promoted guess cannot pass test 1 either. It is written out anyway because
this is the card's hard row: the day somebody makes a hypothesis admissible for
a good reason of their own, the dog must go quiet about it rather than start
naming it. `test_an_admissible_vlm_name_is_still_refused_by_this_card`
constructs exactly that case — a name that IS in `known_places()` — and pins the
refusal.

Admission is re-checked **at the moment of speaking**, not at the moment of
queueing: a name that decayed out of the vocabulary in the four minutes since it
was noticed is a name the robot may no longer say, and "it was true when we
queued it" is the reasoning the row exists to refuse.

**NM-1 handoff.** When NM-1's detector-agreement judge lands, the provenance test
is the ONE line that changes: `promoted` stops being sufficient and NM-1's
admission flag becomes the test. Nothing else in the region knows how a name is
judged. Until then `promoted` is the strongest signal this system has, and P1-D
measured that it is not a strong one (45 % naming accuracy; 2 of 2 false
promotions at full resolution) — see §6.

### 2.2 A remark can never land on top of the owner

Two gates, one layer apart, and neither is a copy of the other's rule:

* `_curiosity_lane_busy()` reads the LANE's own answer — `snapshot()["idle_seconds"]
  is None`, which is true for exactly the four states `narrate_event` refuses
  (no session, a response playing, a response outstanding, the owner owed an
  answer). Reading it before the offer means a remark the floor gate would drop
  is never drawn from the owner's budget.
* the floor gate itself, unchanged and untouched, refuses again.

This card does not edit `lane.py`, so the rule cannot drift: the rule is read,
never restated.

### 2.3 A remark can never spend past the owner's cap

No curiosity class is in `CRITICAL_KINDS`, so `offer_curiosity` → `_forward`
prices every remark against the dedup window, `min_gap_s` and
`max_updates_per_minute` exactly like a battery fact. When the cap IS spent the
remark becomes a **free gesture** (`curious_look` through `_brain_gesture`, the
activity coordinator's own proposal path) — nothing on the wire, nothing billed,
and the dog still visibly noticed something. That is deliverable 3, and it is why
the budget is a knob and not a mute button.

### 2.4 A remark can only reach the model through the scheduler

`CURIOSITY_KINDS ⊂ MIDDLE_BAND`. The middle band's meaning in this module is
"decided by a deterministic mechanism"; the mechanism here is
`ChatterScheduler` and its door is `Whisperer.offer_curiosity`. An event that
arrives at bare `offer` has skipped the scheduler and is refused and logged.

This is the whole safety argument for the card. An ALWAYS-band curiosity class
would mean "the map grew, therefore the robot speaks" — and the map grows on a
camera frame, at 2 Hz, for the length of a walk. The band table cannot bound
that; only a scheduler with a clock can. `offer_curiosity` also refuses a class
it is not the mechanism for: a mechanism that speaks for anything it is handed
is not a mechanism.

### 2.5 The cadence, and the three clocks it keeps apart

`ChatterScheduler` draws exponential inter-arrival gaps (a Poisson process)
around `mean_gap_s`, clamped below by `min_gap_floor_s`. It keeps three clocks
separate on purpose:

| clock | measures | why separate |
|---|---|---|
| `clock` (monotonic) | the gap, the quiet window | injectable; every test runs frozen |
| `time_band` (WALL) | morning / afternoon / evening / **night** | P2-B's `day_key` reason: "is it 3 a.m." is a calendar question, and mixing it into a duration is how a dog goes quiet at 3 a.m. UTC in a house on the US west coast |
| `rng` | the gap draw | seeded (`PARCEL_CURIOSITY_SEED`) so a claim about a rate can be re-run |

**"Quiet" here is not P2-B's "quiet".** P2-B's `note_turn` counts BOTH sides
because a greeting is due after silence. This scheduler's counts the OWNER's
exchanges only, and deliberately not the robot's own unprompted remarks, because
`quiet_s` protects a CONVERSATION while the Poisson gap paces a MONOLOGUE.
Feeding the monologue into the conversation clock collapses the two into the
slower one — and that is exactly the arithmetic that makes the card's "quiet ≥
90 s" and "3–6 remarks per 120 s" contradict each other (§5). A session nobody
has spoken on has no conversation to protect, so the quiet condition is
satisfied rather than blocking; that is the difference between a companion that
goes first and one that waits to be spoken to.

Every tick lands in exactly one of seven named skip reasons or is admitted —
R13's invariant, applied to a third watcher, with `ticks == admitted +
sum(skips)` asserted.

### 2.6 The farewell

`KIND_OWNER_LEFT`, ALWAYS band, not critical. P2-B's `OwnerEventWatcher` is a
closed block and this card does not edit it, so `FarewellWatcher` observes the
SAME `OwnerPresence` samples on the other edge; the runtime feeds both from one
`owner_presence_sample()` call, so they cannot disagree about whether you are in
the room. It is deliberately not symmetric with the hello: an appearance is
announced after a 2 s DEBOUNCE, a departure after a 45 s ABSENCE, because a hello
fired at a passing shadow is charming and a goodbye fired at one is the robot
farewelling your back while you stand in front of it. A robot that has never seen
anybody never says goodbye to nobody (`_ever_seen`, pinned).

### 2.7 Remarks ride patrol's idle checkpoints

`prompts/functions/patrol.yaml` (not edited): *social actions can wait until an
idle checkpoint*. Implemented as `ChatterState.activity_running =
self.activities.running() is not None` — read against the coordinator that
already owns checkpoint semantics rather than re-deriving them. It is a proxy;
§6 says so.

---

## 3. The pre-registered rows, measured

Harness: `/home/jaewoo-jang/.cache/parcel-curio1/run_curio1_roam.py`, scored by
`score_curio1.py`. ROAM-1 had not landed when the arm was designed, so the roam
is **MOVE-1's harness** (`scrum/20260821/task_20/evidence`, read-only) driving
`PatrolRunner`, in the shape P1-B's dev-scene harness already used it. Real
MuJoCo sim on a unique socket, real `RobotRuntime`, real camera ingress, the
RUNTIME's own `OnlineSemanticMap`, the real `RealtimeLane` — opened against the
repo's own shipped `realtime.fake_server.FakeRealtimeServer`, so the floor gate,
the response-pending arithmetic and the idle clock are all the product's.

### 3.1 The scored arm — `roamB`, and `roamC` as a second seed

| # | row | bound | `roamB` (seed 20260822) | `roamC` (seed 777) | verdict |
|---|---|---|---|---|---|
| **1** | unprompted remarks in 120 s, roam cadence (`mean_gap_s: 25`) | **3 ≤ n ≤ 6** | **6** | **6** | **MET** |
| **2** | **hallucinated places** — a name not in `known_places()` at utterance time, or `vlm_proposed` | **0** (HARD) | **0** | **0** | **MET** |
| **3** | remarks while the owner is owed an answer (29.9 s window) | **0** | **0** | **0** | **MET** |
| **4** | worst rolling 60 s against the cap | **≤ 6** | **4** | **4** | **MET** |
| **5** | hosted spend | **≤ $0.10/run**, and no provider contacted | **$0.00** | **$0.00** | **MET** |
| **6** | a config written before this card | unchanged | `curiosity.enabled: False`, all defaults | same | **MET** |
| **7** | seeds RED | each ≥ 1 named test | 5 seeds, 9 tests | — | **MET** |

Row 2's scoring is deliberately independent of the guard it scores: the harness
samples `known_places()` once a second into a timeline, the scorer takes the
place name out of the decision row's own `key`, and checks it against the newest
sample at or before the utterance. It never asks the runtime whether it
hallucinated.

Row 5, exactly: **no provider client was constructed and no socket left the
process.** `recordings/spend.jsonl` is sha256-identical before and after all four
runs; the owner's store likewise. Each run directory holds its OWN
`spend.jsonl`, written by the real ledger from the FAKE server's constant token
counts ($0.008376 for six responses) — **that is not a cost measurement.** The
honest projection is from the 08-20 recorded baseline, $0.274 / 44 turns =
$0.00623 per turn: six remarks ≈ **$0.037 per 120 s run**, inside the $0.10
bound with room.

`roamB`'s six remarks, in order, with the elapsed gaps: `building` (t+8.2 s from
the previous), `lamppost` (+8.2), `window` (+47.4, the owner-owed window sits
inside it), `storefront` (+8.1), `tree` (+8.3), `door` (+11.4). Every one is a
detector label the map held at that second. The composed line is the FACT plus
the class's HINT, e.g.

```
The robot has just seen something in this place it had not seen here before, and
its own map now has a row for it: a tree. It is the morning. Mention the one
thing you just noticed, in one short sentence, the way you would point something
out to a friend. Do NOT list your sensors, do NOT give coordinates or distances,
and do NOT report your status.
```

### 3.2 The shipping cadence, for contrast — `roamS`

Same code, same scene, `mean_gap_s: 360.0` (the shipped default and the card's
own 4–8 minute band): **0 remarks in 120 s**, 87 ticks held by the gap. That is
the arithmetic working, and it is the number that shows the roam arm is a demo
cadence and not what a `--prototype` launch ships. A shipped dog remarking every
six minutes cannot produce three remarks in two minutes, and this is what the
pre-registration said in advance (§5.1).

### 3.3 The run that found a harness defect — `roamA`

The first 120 s arm produced **1** remark and skipped 96 of 115 ticks on
`lane_busy`. Diagnosis: the harness opened the lane's session directly and never
started `RobotRuntime.realtime_driver` (the product starts it from
`submit_realtime_transcript`, and nothing in a roam types), so every
`response.done` sat unread in the transport and the lane was permanently
mid-answer. Fixed in the harness — the product's own driver, started on its own
cadence, unmodified.

It is reported rather than deleted because it is an accidental proof of §2.2:
with the lane genuinely unable to take a narration for 96 seconds, the dog said
one thing and then nothing, and **zero** narrations were attempted into the busy
lane.

### 3.4 The gates

```
$ .parcel/bin/python -m pytest -q tests/test_curio1_chatter.py
51 passed

$ .parcel/bin/python -m pytest -q tests/test_curio1_chatter.py \
      tests/test_realtime_whisperer.py tests/test_runtime_whisperer_wiring.py \
      tests/test_p2b_owner_awareness.py tests/test_prototype_profile.py \
      tests/test_p0b_companion_unlocks.py tests/test_r24_lock_discipline.py \
      tests/test_realtime_lane.py
479 passed, 2 warnings in 10.87s

$ .parcel/bin/python -m pytest -q tests/test_curio1_chatter.py \
      tests/test_realtime_tool_broker.py tests/test_c2_online_map.py \
      tests/test_realtime_ingress.py tests/test_perception_abstention.py
436 passed, 1 warning in 2.60s        # the APIs this card consumes, unmoved

$ .parcel/bin/ruff check src/parcel_robot/realtime/whisperer.py \
      src/parcel_robot/realtime/config.py src/parcel_robot/runtime.py \
      tests/test_curio1_chatter.py
All checks passed!
```

Run with `TMPDIR` unset, per the wave rule. `scripts/ci_gate.py` was NOT run and
neither was the full suite. **The ruff ratchet is untouched**:
`scripts/ci_ruff_baseline.json` holds exactly 7 fingerprints, none in any file
this card edits, and this card adds none.

## 4. Seeded RED

Five mutations, each the plausible defect written the way somebody would
actually write it, applied to a **COPY** of `src/` at
`/home/jaewoo-jang/.cache/parcel-curio1/seed/src` and run with `PYTHONPATH`.

**Why a copy.** Six other week-1 cards are executing in this working tree right
now. Seeding a defect into `src/` — even for the ninety seconds it takes to watch
a test fail — would make every one of their targeted runs red for reasons that
are not theirs, and the restore would race their edits. This is mutation-seeding,
not HEAD-seeding, and it is declared as such: at `8862220` these symbols do not
exist at all, so a HEAD run fails at import and proves nothing about behaviour.
The product tree's sha256s are recorded before and after and are **identical**,
so "the tree was not touched" is a measurement.

Baseline (unseeded copy): `51 passed`.

| seed | the mutation | tests that go RED |
|---|---|---|
| **A** provenance test dropped | `_curiosity_admitted_names` returns `known_places()` and stops asking about provenance | `test_an_admissible_vlm_name_is_still_refused_by_this_card` |
| **A2** speaking-time re-check dropped | the ASK path takes `verdict.ask_place` without re-checking admission | `test_an_ask_verdict_naming_an_unadmitted_place_is_dropped` |
| **B** lane-busy check dropped | `ChatterState(lane_busy=False)` — the scheduler stops reading the lane | `test_a_remark_never_lands_while_the_owner_is_owed_an_answer` |
| **C** curiosity becomes critical | `CURIOSITY_KINDS` folded into `CRITICAL_KINDS` | `test_no_curiosity_class_is_critical`, `test_remarks_can_never_spend_past_the_owners_cap`, `test_a_remark_obeys_the_min_gap_like_every_other_fact`, `test_a_remark_the_cap_refused_becomes_a_free_gesture` |
| **D** curiosity promoted to the always band | `CURIOSITY_KINDS` added to `ALWAYS_BAND` | `test_a_curiosity_event_handed_to_bare_offer_is_refused`, `test_the_four_curiosity_classes_are_middle_band` |

Nine distinct tests over five seeds; every seed reddens the guard it attacks and
nothing else. Seed C reddening the min-gap test as well is not noise — a critical
class is exempt from `MIN_GAP_EXEMPT_KINDS` by construction, which is precisely
the second thing that seed breaks.

`"tree_unchanged": true` in the JSON is the sha256 pair over
`whisperer.py`, `config.py`, `runtime.py`, the prototype example and the test
file, taken before the first mutation and after the last.

Full record: `/home/jaewoo-jang/.cache/parcel-curio1/SEEDED_RED.json`.

---

## 5. Deviations and interpretations (declared)

### 5.1 The card's two cadences cannot both hold — both were measured

"Poisson gaps, mean 4–8 min" gives 0.25–0.5 remarks per 120 s. "3–6 unprompted
utterances" in a 120 s roam needs a mean near 25 s. The pre-registration named
both operating points BEFORE any measurement (`CURIO1_PREREGISTRATION.md` §0)
and scored row 1 at the roam arm, which is the point the card wrote a bound for.
**The shipped default is the card's cadence (360 s), not the roam arm's**; 25 s
lives only in the harness and is not committed to any config.

### 5.2 `configs/realtime.yaml.example` was NOT edited — it is out of OWNS

The card's OWNS names `configs/realtime.prototype.yaml.example` and not the
production example, so the `curiosity:` block is an ADDITION the prototype
carries and the shipped example does not have at all. Two consequences, both
deliberate:

* P0-A's completeness gate stays green untouched.
  `test_realtime_prototype_example_validates_and_carries_its_departures`
  compares the paths BOTH files carry, so a prototype-only key is not a
  "departure" and the header's "TEN values changed" is still exactly true. The
  prototype file's own comment says the block is an addition rather than a
  departure. `tests/test_prototype_profile.py` — P0-A's, edited by P1-E and P2-B
  before me — is **not** in this diff.
* the shipped example therefore does not document the keys. **Handoff:** adding
  the documented, default-off block to `configs/realtime.yaml.example` is a
  one-block follow-up for whoever owns that file next.

### 5.3 The conversation clock is polled, not wired into P2-B's door

`note_realtime_turn` is P2-B's region and counts both sides of the conversation.
This card needs the owner's half only (§2.5), so `_curiosity_note_owner_turn`
polls `lane.snapshot()["text_turns"] + ["voice_turns_owed"]` on the same 1 Hz
tick — both count owner turns, neither counts a narration. **No other card's
region was touched to get this.**

### 5.4 The chatter layer is built lazily, not in `__init__`

`RobotRuntime.__init__` is edited by several cards at once. `_curiosity_layer()`
builds the scheduler and the farewell watcher on first use instead — construction
is deterministic, takes no lock, and happens on the control loop's thread only
(`_step_curiosity` is the sole caller and the control loop is the sole caller of
that). **R24's lock roster and `PINNED_LOCK_ORDER` are unchanged by this card**:
no new lock, and the existing `_p1b_map_lock` is taken bare, never nested inside
another lock. `tests/test_r24_lock_discipline.py` is green.

### 5.5 One 19 KB insertion into `whisperer.py` was a read-modify-write

The chatter layer went into `whisperer.py` as a single programmatic
read-modify-write rather than through the editor's exact-string path. It is
declared because the wave rule says Edit-only. Mitigations, in order: the file
has no concurrent writer in this dispatch; the read and the write were one
process, milliseconds apart; and the result was verified purely additive
immediately afterwards — `git diff --numstat` showed `630 2`, and both deletions
are the `MIDDLE_BAND` literal this card intentionally rewrites. Every other edit
to every other file in this card went through exact-string edits with a re-read
first, and `config.py` reported "modified on disk since you last read it" twice
during that sequence — i.e. TURN-1 was writing to it concurrently and the
discipline caught it.

### 5.6 `owner_left` is a second watcher, not a fifth branch

The card says "`owner_left` farewell as the falling edge of P2-B's watcher".
P2-B's `OwnerEventWatcher` is closed, so the falling edge is a separate
`FarewellWatcher` over the same samples (§2.6). A grep for a fifth class inside
`OwnerEventWatcher` finds nothing; a grep for `KIND_OWNER_LEFT` finds it.

### 5.7 `curiosity` is default-OFF in code

P2-B's precedent, for P2-B's reason: every forward is a billed hosted response
and a config written before this card must keep costing what it cost. The
prototype overlay — the thing a `--prototype` launch loads — has it on. If the
verifier reads the card as requiring default-on, that is one line.

---

## 6. What this does not prove

* **No hosted session was opened, by me or by the harness.** The
  `FakeRealtimeServer` answers `response.create` with `response.done` and has no
  model in it. Whether `gpt-realtime` renders `novel_object` as *"oh — there's a
  tree over here"* or as *"my online semantic map has admitted a new entry"* is a
  question about the model's taste, and the HINT is the only defence this card
  has. **Watch the first live remark.** The `spend.jsonl` inside each run
  directory holds the FAKE server's constant token counts and is **not** a cost
  measurement; the real `recordings/spend.jsonl` is sha256-identical before and
  after every run.
* **Only ONE of the four curiosity classes fired end-to-end.** Every remark in
  every roam was `novel_object`. The other three are structurally out of reach in
  a 120 s sim roam and this is why, not an excuse: `place_learned` needs the
  idle-time VLM naming pass (not running); `scene_change` needs an entry to decay
  (three missed expected-visible visits); `ask_about` needs the abstention gate to
  return ASK and this scene's policy returned `refuse` for every admitted label.
  All three are proven at unit level, including `ask_about` against a stub that
  supplies the verdict `assess_place_query` would have produced — but **a verifier
  should treat "the dog can say all four kinds of thing" as unproven in a live
  loop.**
* **No promoted name existed in any run.** All seven admitted labels were
  detector labels, so the `promoted`-is-admissible arm of the admission gate was
  exercised only in unit tests. Combined with P1-D's 45 % naming accuracy, the
  honest statement is: **this card has never yet had to decide about a name a VLM
  invented**, and NM-1 is what makes that decision defensible when it does.
* **The owner is the simulator's mocap owner at confidence 1.0** — audit §1's
  defect, inherited exactly as P2-B inherited it. Staleness is checked (a frozen
  observation is not a sighting) but "the owner is here" is a simulator's opinion
  until P1-C's track is wired by OT-2.
* **The owner-speaking window is imposed by the harness**, by setting the real
  lane's own `_voice_turn_owed` flag for 30 s. That is the exact flag the floor
  gate and the idle clock read, and nothing landed inside the window in any run —
  but it is a harness intervention and not an owner actually talking.
* **`night_quiet` was off in the roam** (the runs are in the morning band) and
  the quiet-hours branch is proven only on a hand-set band callable.
* **`_curio_said` is bounded at 512 and `set.pop()` evicts arbitrarily.**
  Overflowing it can only make the dog repeat itself, never make it hallucinate —
  every candidate is re-checked against admission at speaking time.
* **The "idle checkpoint" is `activities.running() is None`,** not the brain
  layer's `at_checkpoint` flag. Under a roam driven by velocity commands no
  activity is running, so the proxy never bit in the measurement.
* **Nothing publishes `curiosity_snapshot()` yet.** `realtime_snapshot` is
  P2-B's/R3's region and this card's OWNS is one feed region, so the accessor
  exists, the harness reads it, and `/api/state` does not. One key,
  `"curiosity": self.curiosity_snapshot()` beside `"owner_events"`, is the whole
  follow-up — see §8.
* **The 45 s farewell has never run for a real forty-five seconds** against a
  human walking out of a room; it is exercised on a hand-advanced clock and,
  in the roam, on a simulated owner who never leaves.

---

## 7. OWNER-GATED rows (listed, never claimed)

| row | what the owner does | why it cannot be measured here |
|---|---|---|
| **taste, ≥ 4/5 over a week** | `scripts/launch_stack.sh --prototype`, then live with it. Score each felt session 1–5 on "did the thing it said make me glad it is there" | Taste. There is no rig for it and inventing a proxy would be worse than the gap |
| **the first live remark's wording** | the same session; read the first `novel_object` line the model produces | needs a hosted turn; the HINT is untested against a real model |
| **the cadence in a room with a person in it** | leave the shipped `mean_gap_s: 360.0` alone for a day and say whether six minutes feels like a companion or like furniture | 120 s of sim cannot answer a question about six-minute gaps |

Exact command for all three:

```
cp configs/realtime.prototype.yaml.example configs/realtime.prototype.yaml
scripts/launch_stack.sh --prototype
```

---

## 8. Handoffs

* **NM-1 (`task_18`)** — your judge replaces ONE test, in
  `RobotRuntime._curiosity_admitted_names`: the `provenance == vlm_proposed`
  check becomes your admission flag. Nothing else in the region knows how a name
  is judged, and `test_an_admissible_vlm_name_is_still_refused_by_this_card` is
  the test that will tell you if the seam moved.
* **ROAM-1 (`task_23`)** — this card touched none of your regions
  (`_navigation_extras`, the roam region, `tool_broker.py`, `ingress.py`'s closed
  intents). Once roam is a behavior, re-run
  `/home/jaewoo-jang/.cache/parcel-curio1/run_curio1_roam.py` with your roam
  driving instead of `PatrolRunner`: the harness only needs a different motion
  producer, and row 1 should hold or improve because a roaming dog sees more.
* **P2-B (`task_11`)** — your owner-event block is untouched. `FarewellWatcher`
  is the falling edge; if you ever want it inside `OwnerEventWatcher`, the class,
  the hint and the band are all already declared and the move is mechanical.
* **OT-2 (`task_17`)** — when `OwnerTrackV1` lands on `owner_presence_sample()`,
  both the greeting and the farewell get pixels for free. Nothing in this card
  changes.
* **The verifier** — start at §5 (the deviations are the diff-vs-OWNS mismatches
  you will find), then §3 (the rows, with `roamB`'s `summary.json` still on disk),
  then §4 (`SEEDED_RED.json`, and the sha256 pair proving the tree was never
  seeded in place). The single most load-bearing sentence in the card is §6's
  "only one of the four classes fired end-to-end".
* **Whoever owns `configs/realtime.yaml.example` next** — §5.2: the documented,
  default-off `curiosity:` block belongs there and this card was not allowed to
  put it there.
* **Whoever owns `runtime.realtime_snapshot` next** — one key,
  `"curiosity": self.curiosity_snapshot()` beside `"owner_events"` in the
  CONSTRUCTED branch (the flag-off branch is pinned by an exact-equality
  assertion in `tests/test_realtime_tool_broker.py`, which is why P2-B did the
  same and why this card did not reach across). The accessor returns `None` when
  the feature is off, so the flag-off wire stays byte-identical either way.
* **The evidence** is all under `/home/jaewoo-jang/.cache/parcel-curio1/`:
  `run_curio1_roam.py` (the arm), `score_curio1.py` (the scorer),
  `seed_curio1.py` + `SEEDED_RED.json` (the seeds), `attribute.py` (the hunk
  attribution), and `roamA/roamB/roamC/roamS_*/summary.json` (the four runs, with
  their vocabulary timelines).

---

# 9. Correction pass (2026-08-22, after Fable's ACCEPT + one correction pass)

Verdict on the first pass: **ACCEPT the headline, one correction pass.** Six
confirmed items and two notes, all addressed below. Pre-registered first, in
`CURIO1_PREREGISTRATION.md`'s addendum, before anything was re-measured.
Nothing in §§1–8 above is deleted; where a number or a claim moved, this section
says so and supersedes it.

## 9.1 The ASK path read a field that does not exist — the one real bug

`runtime.py` read `getattr(result.verdict, "ask_place", "") or label`.
**`AbstentionVerdict` has no `ask_place`.** Card P1-D's field is `candidate`
("the place an ASK is asking ABOUT — the best candidate's label",
`perception_abstention.py`). Consequences, all of which the verifier named:

* `place` always fell back to the queried label, so the verdict's own candidate
  was never spoken;
* the admission re-check under it was therefore **unreachable** on the product
  path — the queried label is admitted by construction, having come out of the
  admitted set;
* and both tests stubbed `ask_place`, so the stub agreed with the code and the
  pair agreed about a field the product does not have. A textbook stub artefact.

Fixed: the feed reads `result.verdict.candidate`, falling back to the queried
label only when the verdict named nothing. The re-check is now reachable and
load-bearing — the candidate is the MAP's best guess, which is exactly the kind
of name this card may not say. Both stubs now carry `candidate`, and the
positive test's candidate deliberately DIFFERS from the queried label ("bench"
sorts first, the candidate is "lamppost") so a build that speaks the query
instead of the candidate is visible rather than hidden behind two matching
strings.

Seed **A2′** replaces the first pass's A2 and attacks the product contract:
`place = label`. It reddens **both** ask tests.

## 9.2 Two feed branches had no product-path test

`place_learned` and `scene_change` were reachable, correct (the verifier drove
both by hand) and **untested**, so §6's "all three are proven at unit level" was
false for two of the three. Four new product-path tests through
`_step_curiosity` on the real `OnlineSemanticMap`:

| test | what it drives |
|---|---|
| `test_a_place_that_decays_out_of_the_map_is_a_scene_change` | two entries share a label; one is marked decayed; the label survives ⇒ exactly one `scene_change:lamppost` |
| `test_a_place_whose_label_leaves_the_vocabulary_is_dropped_not_guessed_at` | the LAST entry with that label decays ⇒ the label leaves `known_places()` ⇒ **silence**, and `dropped_unadmitted` counted |
| `test_a_promoted_name_entering_the_vocabulary_is_a_place_learned` | a `NAME_PROMOTED` name added to a known entry ⇒ exactly one `place_learned:the front step` |
| `test_a_vlm_proposed_name_is_never_a_place_learned` | the same, with `NAME_VLM_PROPOSED` ⇒ nothing, ever |

**§6 is corrected accordingly**: `place_learned` and `scene_change` now have
product-path coverage on the real map; what remains unfired in a LIVE 120 s roam
is a separate and smaller claim, restated in §9.8.

**The article bug the third test caught.** `the front step` rendered as *"the the
front step"*: the templates hard-coded `the {place}` and the map's vocabulary is
free to contain a name that already starts with an article. The article is now
decided per NAME (`_definite_phrase` / `_indefinite_phrase`, which also gets
*"an awning"* right), and the test asserts the doubling is gone.

## 9.3 The polled conversation clock had no test

`_curiosity_note_owner_turn` is the deviation in §5.3 and **no roam exercised
it** — the owner-owed window exercised the lane's floor gate, which is a
different guard. `test_an_owner_turn_starts_the_quiet_window_over_on_the_product_path`
increments the fake lane's `text_turns` between two ticks (what an owner typing
looks like from here), asserts `CHATTER_SKIP_CONVERSATION`, and then asserts the
dog waits the window out and speaks after it rather than forgetting. Seed **G**
(the clock stops calling `note_turn`) reddens it.

## 9.4 The cap-spent free gesture: THE GESTURE IS THE REMARK — decided, documented

The verifier's option 1. Returning `True` from `_curiosity_free_gesture` means
the fact was EXPRESSED: it is marked said and both cadence clocks re-arm, exactly
as a spoken sentence would. **One noticing produces one expression, billed or
free.** The rejected alternative was "gesture now, sentence when the cap frees
up", which hands the owner two of everything for one lamppost and turns the
gesture into a trailer for a sentence rather than a substitute for it. Written
down in three places that can disagree if anybody changes one: §2.3 above,
`_curiosity_free_gesture`'s docstring, and `ChatterScheduler.note_remark`'s
docstring — which is the method whose contract it settles.

**Which door, also documented.** `_brain_gesture("curious_look")`: the emote
catalog plus the activity coordinator's proposal path. **Not**
`realtime.proactive_motion_tools`, which is P0-B's allowlist for motion the
hosted MODEL proposes on a system-initiated response. Nothing here is a model
proposal — no model is consulted and nothing is billed — and the card's own
wording ("a yip/whine sound effect **or** a `play_gesture`") left the door open.

## 9.5 The §1 attribution was wrong, and the method that produced it was wrong

The first pass classified whole `-U0` hunks by whether any line in them mentioned
the card. ROAM-1's region opens with prose naming CURIO-1 (it published
`roam_idle_checkpoint()` for this card), so that whole region was credited here.
**The heuristic is retired.** The share is now measured directly from the file by
banner region — `/home/jaewoo-jang/.cache/parcel-curio1/attribute6.py` prints
every added line that falls outside one, so the residue is a printed list a
reader judges rather than a guess.

| file | whole-file | **CURIO-1's share, measured** | how it is made up |
|---|---|---|---|
| `src/parcel_robot/runtime.py` | +1161 / −0 | **+590 / −0** | one marked region, lines 12881–13452 (**572**) + **10** individually marked import lines + **8** at the `_step_whisperer` call site. Everything else in that diff is ROAM-1's |
| `src/parcel_robot/realtime/whisperer.py` | +757 / −3 | **+757 / −3** | no other card writes this file in this wave — `git diff` contains no other card's marker |
| `src/parcel_robot/realtime/config.py` | +398 / −3 | **+218 / −1** | three banner regions (**207**) + **11** lines threading `curiosity` through `WHISPERER_ALLOWED_KEYS`, `WhispererConfig`, `as_dict`, the loader and `__all__`. The other +180 is TURN-1's |
| `configs/realtime.prototype.yaml.example` | +155 / −0 | **+73 / −0** | the `curiosity:` block, lines 371–443. The rest is TURN-1's `turn_detection` block |
| `tests/test_curio1_chatter.py` | +1483 | +1483 | **60 tests** (51 + 9 from this pass) |

The verifier's independently measured +478 was for runtime.py **before** this
correction pass; the +112 difference is this pass's additions (the idle class,
the two-cadence branch, `_curiosity_activity_busy`, `_curiosity_idle_candidate`
and the documentation the corrections required).

`SEEDED_RED.json`'s sha256 pair has been regenerated against the FINAL tree.

## 9.6 Ruling 6 — the cadence was ONE card, TWO cadences

The card's author ruled it, and the ruling is right: "mean 4–8 min" and "3–6 per
120 s" were never one number. They are two kinds of remark:

| | governs | knob | shipped default |
|---|---|---|---|
| **stimulus** | `novel_object`, `scene_change`, `place_learned`, `ask_about` — something HAPPENED | `whisperer.curiosity.stimulus_min_gap_s` | **25.0 s**, a fixed floor |
| **idle** | `idle_remark` — NOTHING happened; time-of-day coloured | `whisperer.curiosity.mean_gap_s` | **360.0 s**, a Poisson mean |

A fixed floor and not a mean for the stimulus half, because its subject is
already in the past: a six-minute wait would have the dog narrating a lamppost it
walked past four corners ago. `whisperer.STIMULUS_KINDS` is the split, and
`ChatterScheduler.due(state, stimulus=...)` is the one place it is read —
everything above the gap (owner present, lane free, coordinator at a checkpoint,
night over, conversation quiet) is identical for the two, and one `due` call per
tick keeps `ticks == admitted + sum(skips)` intact.

**A fifth class, `idle_remark`,** because a class that fires when nothing happened
cannot be event-triggered. It still names an ADMITTED place — the dog thinking out
loud about something it already knows — so **the hard row is unchanged and this
adds no new way for a name to reach the model.** It round-robins the vocabulary
rather than returning to the first lamppost every six minutes.

**The idle-checkpoint proxy is retired.** ROAM-1 has landed and published
`roam_idle_checkpoint()` *for this card* ("CURIO-1's remarks ride this predicate
— it is published for that card and this region does not call it").
`_curiosity_activity_busy` now reads it beside `activities.running()`, defensively
so this card still works on a tree without ROAM-1. §2.7 and §6's proxy caveat are
superseded. ROAM-1's regions were not edited; `tests/test_roam1_behavior.py` is
green (82 passed with `test_move1_patrol.py`).

## 9.7 The re-measured roam — SHIPPED DEFAULTS, nothing overridden

The arm now points `PARCEL_REALTIME_CONFIG` at
`configs/realtime.prototype.yaml.example` **byte for byte** — the file the owner
copies — instead of a config the harness wrote. `--shipped`.

| # | row | bound | `shippedA` | `shippedB` (seed 777) | verdict |
|---|---|---|---|---|---|
| **1′** | unprompted remarks, 120 s roam, shipped cadence | **3 ≤ n ≤ 6** | **3** | **3** | **MET** |
| **1i** | idle-chatter remarks in the same 120 s | **0** | **0** | **0** | **MET** |
| **2′** | hallucinated places | **0** (HARD) | **0** | **0** | **MET** |
| **3′** | remarks while the owner is owed an answer (29.9 s) | **0** | **0** | **0** | **MET** |
| **4′** | worst rolling 60 s vs the cap | **≤ 6** | **2** | **2** | **MET** |
| **5′** | hosted spend | **$0.00** | **$0.00** | **$0.00** | **MET** |

**`shippedB` filled in by FINISH-1 (`../task_29` §B), and it was never a
missing run — it was a missing SCORE.** The run completed at
`2026-08-22T11:31:48Z` and its artifacts were on disk the whole time
(`/home/jaewoo-jang/.cache/parcel-curio1/shippedB_20260822T112946Z/`:
`summary.json` 419 KB, `spend.jsonl`, `simulator.log`, the byte-copied
`realtime.yaml`); the pass that was going to score it was killed first. FINISH-1
ran the same scorer with nothing re-run and nothing re-simulated:

```
$ unset TMPDIR; .parcel/bin/python /home/jaewoo-jang/.cache/parcel-curio1/score_curio1.py       /home/jaewoo-jang/.cache/parcel-curio1/shippedB_20260822T112946Z/summary.json
row1_remarks 3 (bound 3..6, MET) · row1i_idle_remarks 0 · row2_hallucinated 0 ·
row3_remarks_while_owner_owed 0 (busy window 29.86 s) · row4_worst_60s_window 2
(cap 6) · row5 repo spend ledger unchanged True · owner store unchanged True ·
kinds ['novel_object'] · scheduler_ticks 116
```

**Every row MET; no row missed.** The three remarks, in order, are
`novel_object:storefront`, `novel_object:building`, `novel_object:bench` — a
different set from `shippedA`'s, on the same scene with a different seed, which
is the point of a second arm. Skips: `stimulus_gap_holding 81 · lane_busy 30 ·
gap_holding 2` over 116 ticks (`shippedA`: 82 / 29 / 2 over 116) — the same
shape twice. `lane_narrations` is 4 against 3 curiosity remarks on both arms,
i.e. P2-B's `owner_appeared` spoke once on each.

**Row 5, said precisely.** `$0.00` means what it means on `shippedA`: **no
provider client was constructed and no socket left the process**; the repo's
`recordings/spend.jsonl` and the owner store are sha256-identical before and
after. The run directory holds its own `spend.jsonl` written by the real ledger
from the FAKE server's constant token counts (4 rows × $0.001396 = $0.005584) —
**that is not a cost measurement** and is not this row.

The scorer was re-run on `shippedA` first as a control and reproduced the
column already in this table exactly (3 / 0 / 0 / 2, skips 82 / 29 / 2, 116
ticks), so the `shippedB` column is not the scorer being asked a new question.

Cadence actually loaded, read back off the runtime:
`mean_gap_s 360.0 · stimulus_min_gap_s 25.0 · min_gap_s 4.0 · cap 6/60 s`.
Skips: `stimulus_gap_holding 82 · lane_busy 29 · gap_holding 2` over 116 ticks —
i.e. the fast clock did the pacing, the slow clock never came due, and the
owner-owed window accounted for every remaining silence. **The shipped default no
longer yields 0 remarks in a roam**, which was the point of the ruling.

**A cross-check nobody asked for.** Loading the real overlay also switched on
P2-B's `owner_events`, so `shippedA` is the first run in which both initiative
families spoke on one session: `owner_appeared` at t+0 and three `novel_object`
remarks after it, four narrations total, worst minute 2 against a cap of 6, no
interference in either direction.

## 9.8 §6 corrections

* "all three are proven at unit level only" → **`place_learned` and
  `scene_change` are now proven on the product path against the real
  `OnlineSemanticMap`** (§9.2). What is still true, and smaller: in a live 120 s
  roam only `novel_object` fires, because the naming pass is not running, nothing
  decays in two minutes, and this scene's abstention policy returns `refuse`
  rather than ASK for every admitted label.
* "the idle checkpoint is a proxy" → **retired**, ROAM-1's predicate is read
  (§9.6).
* "the polled conversation clock is untested" → **tested** (§9.3).
* **New, and it belongs here:** `idle_remark` has never fired in a roam either,
  by design — a six-minute mean cannot fire in two minutes, which is row 1i and
  is why row 1i exists. It is proven on a hand-advanced clock and on the product
  path with the mean pinned to 40 s.

## 9.9 The two notes

* **`curiosity_snapshot()` from a foreign thread.** It is read from the panel
  thread while the control loop writes. `_curio_counts` is now **copy-on-write** —
  `_curio_count` rebinds a new dict rather than mutating in place — so
  `dict(...)` in the snapshot can no longer catch a dict mid-mutation; the other
  three reads are `len()`, which is atomic. **No new lock and therefore no new
  edge in `PINNED_LOCK_ORDER`**; `tests/test_r24_lock_discipline.py` is green.
  The lazy builder now binds `_curio_scheduler` **last**, so the `is None` test
  the snapshot uses as "the layer does not exist yet" can never see a half-built
  one.
* **A refused candidate was re-offered every 1 Hz tick.**
  `ChatterScheduler.note_refusal` moves the ANCHOR without redrawing the Poisson
  gap: the stimulus floor restarts (so the retry storm stops) and the owner does
  not buy a fresh four-minute silence for a sentence nobody heard — the same
  reasoning `undeliver` uses to hand the budget slot back.
  `test_a_refused_offer_is_not_retried_every_second` closes the monthly ceiling
  and asserts ≤ 12 offers in 40 ticks.

## 9.10 Seeded RED, re-run against the FINAL tree

Ten seeds, same copy-based method and the same sha256 pair (`"tree_unchanged":
true`). Baseline on the unseeded copy: `60 passed`.

| seed | mutation | RED |
|---|---|---|
| **A** | the provenance test is dropped from the admission gate | 1 |
| **A2′** | the ASK path speaks the QUERY, not `verdict.candidate` | 2 |
| **A3** | the ASK path drops the speaking-time re-check | 1 |
| **B** | the scheduler stops reading the lane's busy state | 1 |
| **C** | `CURIOSITY_KINDS` folded into `CRITICAL_KINDS` | 4 |
| **D** | `CURIOSITY_KINDS` promoted into `ALWAYS_BAND` | 2 |
| **E** | the decayed-place admission gate is removed (both halves) | 1 |
| **F** | every name the map holds becomes vocabulary | 3 |
| **G** | the polled conversation clock stops calling `note_turn` | 1 |
| **H** | the stimulus gate reads `mean_gap_s` instead of `stimulus_min_gap_s` | 11 |

**Re-run against the FINAL tree by FINISH-1 (`../task_29` §B2), because two of
the five watched files had moved since this table was written**
(`whisperer.py` `4cee9fac…` → `d8dcf475…`, `runtime.py` `0e648f02…` →
`0ba366ae…`; ROAM-1's correction pass is in that delta). Same driver, same
copy-based method: baseline `60 passed`, `"tree_unchanged": true`, and **all
ten seeds reproduce with the identical RED counts** (1/2/1/1/4/2/1/3/1/11).
The refreshed report is `../task_29/evidence/curio1_SEEDED_RED_refreshed.json`
and it supersedes the sha pair quoted above.

Seed H is broad on purpose and it is not noise: swapping the fast clock for the
slow one starves every product-path test that expects the dog to say anything,
which is exactly what the ruling-6 change buys and exactly what would break if
somebody collapsed the two knobs back into one.

## 9.11 Gates, after the correction pass

```
$ .parcel/bin/python -m pytest -q tests/test_curio1_chatter.py
60 passed

$ .parcel/bin/python -m pytest -q tests/test_curio1_chatter.py \
      tests/test_realtime_whisperer.py tests/test_runtime_whisperer_wiring.py \
      tests/test_p2b_owner_awareness.py tests/test_prototype_profile.py \
      tests/test_p0b_companion_unlocks.py tests/test_r24_lock_discipline.py \
      tests/test_realtime_lane.py tests/test_perception_abstention.py
543 passed, 2 warnings in 14.45s

$ .parcel/bin/python -m pytest -q tests/test_roam1_behavior.py tests/test_move1_patrol.py
82 passed          # ROAM-1's regions were read, never edited

$ .parcel/bin/ruff check src/parcel_robot/realtime/whisperer.py \
      src/parcel_robot/realtime/config.py src/parcel_robot/runtime.py \
      tests/test_curio1_chatter.py
All checks passed!
```

`TMPDIR` unset. `scripts/ci_gate.py` and the full suite not run, per the card.
The ruff ratchet is still exactly 7 fingerprints and this card adds none.
Untouched, as declared: `configs/realtime.yaml.example`, `lane.py`,
`online_map/`, `vlm_veto/`, ROAM-1's regions, `prompts/functions/patrol.yaml`.

## 9.12 Close — FINISH-1 (`../task_29` §B), 2026-08-22

Three things, and then this card is done:

1. **§9.7's `shippedB` column is filled** from the run that was already on disk
   (above). Every row MET; nothing was re-simulated and no row missed.
2. **`_curiosity_activity_busy` really does read ROAM-1's predicate.** Re-read
   on the final tree at `runtime.py:13179`: `activities.running()` first, then
   `getattr(self, "roam_idle_checkpoint", None)` and `not bool(checkpoint())`,
   with the defensive `getattr` kept so this card still works on a tree without
   ROAM-1. `tests/test_roam1_behavior.py` is green at 56 tests and CURIO-1
   never edits ROAM-1's regions.
3. **Gates on the final tree** (`TMPDIR` unset):

```
$ .parcel/bin/python -m pytest -q tests/test_curio1_chatter.py     -> 60 passed
$ .parcel/bin/ruff check src/parcel_robot/realtime/whisperer.py \
      src/parcel_robot/realtime/config.py src/parcel_robot/runtime.py \
      tests/test_curio1_chatter.py                                 -> All checks passed!
$ (ten seeds re-run, see §9.10)                                    -> 10/10 RED reproduce
```

The ruff ratchet is still exactly 7 fingerprints tree-wide and this card adds
none.
