# R18 — a dog that knows what it knows (scene answerability + memory surfacing)

**Executor:** Claude Opus (agent) · **Auditor:** Fable · **Date:** 2026-08-20
**Card:** `scrum/20260820/task_7/README.md` (RE-CUT 2026-08-20 after live_run_1)
**Chain position:** after R19 (`scrum/20260820/task_8/R19_STATUS.md`). The memory
half depends on R19's answer beat, so the first thing this card did was verify
that dependency rather than assume it (§0.3).

---

## §0 — ROOT CAUSE, written before a line was changed

Both failures were re-cut by live_run_1's scoring
(`evals/20260820/voice_corpus_v1/live_run_1/README.md` §e). Neither is what
owner_session_1 said it was, and the card's re-cut note is right on both.

### 0.1 F3 — there is no scene-capable tool, and there never was

`state.realtime.broker.tools` in the run's own snapshot is exactly seven names:

```
get_status, recall_memory, play_gesture, set_pose, navigate_to,
circle_owner, follow_owner
```

Asked *"What do you see around you?"* at 14:27:57.736 the model produced two
filler beats **3 ms apart** and then nothing; asked *"Is anyone near you?"* at
14:28:01 it produced silence. In the same snapshot the robot was holding a
360-ray `lidar_scan`, eight `dynamic_agents`, `obstacle_distance_m: 1.4276`, and

```json
"nearest_person": {"id": "ped-6", "distance_m": 1.7268, "bearing_rad": 0.5547}
```

and had already told this owner three times that somebody was in the way
(mission log ids 4, 9, 14). **Person data reached the mission-log narrator and
never the conversation lane.** Work item 1 stands exactly as written: this is a
missing-answer-path defect, not a prompt defect, and the SI is not touched.

### 0.2 F4 — the diagnosis half was already done; the retrieval was still broken

The card says work item 2's diagnosis half is DONE because the root cause moved
(recall fired; R19's beat gate ate the answer). Confirmed, and R19 fixed it.
What R19's own live proof then exposed — its §5.3 scene C, and its Open risk 4,
handed to this card by name — is that the retrieval underneath was broken too.
**Three defects, measured against the owner's real store**, read read-only
through a scratch copy taken at 2026-08-20 17:03 EDT — 2,882 rows spanning
2026-08-02 → 2026-08-20. (The live store has since grown to 2,886 rows: four
turns were written at 21:12:52Z by something that is not this session. The table
below is therefore a snapshot at a named instant, not a claim about the store
now; the shape of the arithmetic is unaffected by four rows.)

| role | origin | speaker | rows | visible to the old recall? |
| --- | --- | --- | ---: | --- |
| user | NULL | NULL | 1306 | **NO** |
| assistant | NULL | NULL | 1299 | **NO** |
| assistant | realtime | robot | 125 | yes |
| user | realtime | owner | 82 | yes |
| tool | realtime | system | 57 | yes — *and these are `[session rollover]` markers* |
| tool | NULL | NULL | 13 | **NO** |

1. **One origin only.** `runtime._realtime_recall` read
   `agent.memory.realtime_turns(limit=200)`, whose `speaker IS NOT NULL` filter
   is load-bearing where it lives (it stops a typed panel command being replayed
   to the provider as if the hosted agent had said it) and catastrophic here: it
   hid **2,618 of 2,882 rows** — every conversation the owner has ever had
   through the local voice/panel path — while admitting the 57 session-bookkeeping
   markers, which are not conversation at all.
2. **Whole-query substring match.** `clean in row["content"].lower()` with
   `clean` = the entire query. "What do you remember about the willow?" cannot
   match the row containing "willow". R19 scene C is that failure, live.
3. **No provenance.** The result was `"speaker: content"` joined by `" | "`,
   with no instant attached — so even a hit could only be said as "I remember
   *something*", which the owner cannot check.

### 0.3 The dependency check the card asked for, before building on it

`tests/test_realtime_answer_beat.py` — R19's 27 test functions / **81 collected
cases — re-run solo on the tree as this card found it: 81 passed.** The
`{"answer": true}` in-band stamp is present in `tool_broker.handle` and
`lane._is_answer_result` reads it ahead of the receipt set. R18's scene block
rides `get_status`, which is already in `ANSWER_TOOLS`, so it inherits the
unsuppressible property; that inheritance is separately pinned by this card
(`test_the_scene_answer_is_stamped_unsuppressible_by_the_broker`,
`test_a_scene_answer_is_never_suppressed_even_named_as_a_receipt_tool`) rather
than assumed, and the live proof measured `tool_beats_requested 3,
tool_beats_suppressed 0, tool_beats_lost 0` (§5.1).

---

## §1 — What changed

| File | Change | Card item |
| --- | --- | --- |
| `src/parcel_robot/runtime.py` | `scene_report` + `scene_fact_lines` + `scene_bearing_words` + `_scene_closest` + `_is_person_track` + `_scene_thing` + `_scene_distance` and their constant block (`SCENE_BEARING_WORDS`, `SCENE_MAX_REGIONS`, `SCENE_SENSORS`, `SCENE_HONESTY_NOTE`, `SCENE_NO_OBSERVATION`, `SCENE_DISTANCE_DECIMALS`, `SCENE_UNLABELLED`, `SCENE_PERSON`); `_realtime_scene_report` / `_realtime_scene_lines`; `"scene"` added to `_realtime_status_digest`; `scene=` provider wired into `DeveloperContext`; `_realtime_recall` rewritten | 1(a), 1(b), 2 |
| `src/parcel_robot/realtime/tool_broker.py` | `get_status` and `recall_memory` tool DESCRIPTIONS (the routing half of item 1, and the "say when it was said" half of item 2) | 1, 2 |
| `src/parcel_robot/memory.py` | READ path: `conversation_turns`, `recall`, `recall_tokens`, `recall_named_day`, `provenance_phrase`, `RecalledTurn`, `_row_instant`, the recall constant block, and the `read_only=` constructor arm | 2 |
| `src/parcel_robot/realtime/prompting.py` | `DeveloperFlags.scene` (appended last, empty by default), `MAX_SCENE_LINES`, `SCENE_BLOCK_HEADER`, the render arm, `DeveloperContext(scene=…)` | 1(b) |
| `tests/test_scene_and_memory_answers.py` **(NEW)** | 1033 lines, 71 collected cases | 3, DoD |

**Untouched, and verified untouched:** the SI (`si_guardrails`,
`render_system_instruction`, `SI_DIGESTS`, every prompt file), `DI_VERSION` and
the DI version-selection machinery, `protocol.py`, `ingress.py`,
`whisperer.py`, `lane.py`, the yield policy, `configs/**`, `evals/**`, the
owner's `parcel_memory.sqlite3` and `~/.config/parcel/realtime.yaml`.

**No `+/−` diff split is given, deliberately.** `runtime.py` and `memory.py`
were already dirty with other cards' uncommitted work when this session opened
and `prompting.py`/`tool_broker.py` are untracked entirely, so `git diff` cannot
separate this card's share and any number claiming to would be invented (same
condition R19 documented). The honest measures are the gate's arithmetic
(**6862 → 6933, +71**, exactly the new file's collected cases) and the seed
harness's startup snapshot, which is the same tree the closing gate scored:

```
runtime.py b1f7bcd0092cdf0a   memory.py a5b4413cdcb048b5
prompting.py dcf85011cdc55154 tool_broker.py c82ace9a08b81694
```

---

## §2 — Work item 1: scene answerability

### 2.1 The answer rides `get_status`, and that is a decision

The card specifies the fact block goes *"into `get_status`'s result"* rather
than onto a new tool, and the reasoning holds up: "how are you doing" and "what
is around you" are the same read of the same runtime at the same instant, and
one tool answering both is one fewer thing for the model to choose wrong. It
also means the answer inherits R19's unsuppressible-answer property for free
instead of needing an eighth name added to two frozensets.

But a result nobody asks for is not an answer. **F3 is a routing failure before
it is anything else** — the model never called a tool because nothing in the
surface said a tool could answer — so the `get_status` DESCRIPTION is the other
half of the fix, and it carries both honesty directions in the one text the
model reads when deciding whether it is *able* to answer:

> "…CALL THIS whenever the owner asks what is around you, what you can detect,
> whether anyone is nearby, what the closest thing is, or how you are doing —
> you are never blind and must never say you cannot sense anything. The
> readings come from LiDAR and a semantic map: the robot has **NO camera**, so
> report what it detects and never describe colours, faces, text or how
> anything looks."

### 2.2 What the block may say, and what it may never say

`scene_report(observation)` is **pure** — observation in, JSON-shaped facts out;
no runtime, no lock, no clock, no catalog — which is what makes the whole scene
half testable against hand-built observations (card item 3). It reads
`semantic_regions`, `semantic_objects`, `dynamic_agents`, `nearest_person_*` and
`nearest_obstacle_*`, and **nothing else**.

In particular it must never do what `_realtime_places` deliberately does.
That function unions the visible instances with the scene's declared CLASS
vocabulary so "the door" is admitted as a navigation goal and allowed to fail
honestly at grounding. That union is right there and is a **fabrication** here:
"what is around you" answered from a class list names things that are not there.
Seeded (S1) and pinned.

Three honesty properties are in the result itself rather than only in a prompt,
because the bench's standing finding is that the model narrates whatever it is
given:

* `sensors: ["lidar", "semantic_map", "person_tracks"]` — what produced this;
* `note` — the no-camera rule, in the field beside the facts;
* `observed: false` + `"the robot's perception has no reading yet"` when there
  is no observation. **That is not a blindness claim**, and the difference is
  the whole of owner_session_1's F3. Seeded in both directions (S2, S3).

Bearings are the ROBOT's frame ("on my left"), never the owner's: the two
disagree whenever they are not facing the same way, and a companion that says
"on your left" while meaning its own has pointed the owner at the wrong thing
(S6). A person is `"a person"` — the tracks carry a position and a radius and
nothing about who anybody is.

### 2.3 Two things the LIVE proof changed, and would not have been found offline

1. **Distances are rounded to one decimal before the model sees them.** Handed
   `"distance_m": 0.48`, `gpt-realtime-2.1-mini` said **"zero meters straight
   ahead"** — a number the owner cannot act on, from a reading that was
   perfectly good. One decimal is also exactly what `scene_fact_lines` renders,
   so the structured field and the sentence can no longer disagree (S24).
2. **`closest` is a field, not an inference.** Corpus query 29 is literally
   "What's the closest thing to you?" Given `things`, `people` and `clearance_m`
   separately, the model answered it off the person track — *"the closest thing
   is zero meters behind me"* — while the LiDAR clearance was 1.1 m. Three
   numbers to choose between is a choice; one field is an answer. The unlabelled
   LiDAR return is named as unlabelled ("something my LiDAR ranged but the map
   has no label for") rather than given a class it does not have (S25, S26).

### 2.4 The DI half, and the `DI_VERSION` that was not bumped

`DeveloperFlags.scene` is appended **last**, after history, and renders nothing
at all when empty. Its header carries the staleness caveat, which is the price
of putting perception in a session-boundary artifact:

> "What your sensors reported when this session opened (LiDAR ranges and a
> semantic map — you have NO camera, so never describe colours, faces, text or
> anything else that would need eyes; call get_status for what is around you
> right now):"

**`DI_VERSION` is deliberately NOT bumped, and this is deviation 1.** Every flag
set that existed before this card has an empty `scene` (there was no provider to
fill it), so every one of them renders byte-identical text; `PINNED_DI_DIGEST`
still matches and the 25 sealed `evals/companion/realtime_convo_v1` fixtures
stay verifiable. A bump would have invalidated all 25 for a block none of them
contains, and `tests/test_realtime_corpus_replay.py` asserts
`manifest["di_version"] == DI_VERSION` and `diff_manifest() == ["si_version",
"si_digests"]` — i.e. a bump is a red gate in a pack this card does not own. The
claim is executable: `test_an_empty_scene_renders_the_di_exactly_as_it_rendered_
before_this_card`, plus seed **S11**, which turns `if flags.scene:` into
`if True:` and reddens the DI pin itself.

---

## §3 — Work item 2: memory surfacing

### 3.1 One read, three modes, and which one runs is decided by the query

`ConversationMemory.recall(query, now=…)` — beside the rows, unit-tested against
an in-memory store, `now` injected so the dating is testable and so the runtime's
one clock stays the runtime's one clock.

| mode | fires when | answers |
| --- | --- | --- |
| **keyword** | topic words survive the stopword and time-word sets | "what do you remember about the willow?" — R19's live scene C |
| **a named day** | the only content word is a date word | corpus **q31** |
| **the owner themselves** | no topic words and no day | corpus **q30**, F4 |

`conversation_turns()` is the read that replaces `realtime_turns()`: no
`speaker IS NOT NULL` filter (S13), `speaker` recovered from `role` for the
2,618 legacy rows, and `system` rows dropped at the reader rather than by every
caller (S18).

Four ranking rules, each of which exists because of something measured:

* **A partial match is only offered when nothing matched better.** "New York"
  against the owner's real store otherwise returns *"Emergency stop is latched,
  so I can't take NEW movement commands…"* — one shared word dressed as a
  memory (S19).
* **The same sentence said fourteen times is recalled once.** The owner's store
  has "go to the lamppost" in it fourteen times across three weeks.
* **In the owner-themselves mode, the turns where the owner is the SUBJECT
  outrank the ones where they gave an order** (S22). Plain recency returns
  "find the fountain", "head towards the lamppost", "run to the nearest
  lamppost" — true, dated, checkable, and not about the owner at all.
  `RECALL_SELF_MARKERS` excludes **"me"**: it is an object pronoun and the
  owner's store is full of it as an order ("order me a pizza", "take me
  somewhere nice", "wave at me") (S21).
* **A named day BOUNDS every mode, and is applied before de-duplication.** That
  ordering cost a debugging round and is now a seed (S17): de-duplicating first
  lets the newest copy of a repeated sentence claim the text, the window then
  discards that copy, and the in-window copy stays suppressed as a duplicate —
  which emptied whole days against the owner's real store.

### 3.2 Provenance, and the refusal to invent one

Every result carries `when` and a `when_phrase` from a stated table — "earlier
today" / "yesterday" / "on Tuesday" (inside a week) / "on 6 August" — and
`as_sentence()` leads with it: **"yesterday you said: …"**. A row whose
`created_at` will not parse comes back with **no** phrase and is said without a
date, because a recalled fact with an invented instant is worse than one with no
instant: the owner can check the second kind (S14, S15). A row stamped in the
future gets no phrase either, rather than "in 3 days".

### 3.3 The live proof changed one more thing: the model picks the query

Asked *"What do you remember about me?"* the mini tier called
`recall_memory({"query": "owner"})` — inventing a topic for a question that had
none. Against the owner's real store that keyword-matched five typed test
commands ("go to the owner", "walk around the owner", "circle the owner once")
and, worse, matched the robot's **own** owner_session_1 sentence — *"there's no
memory of what I know about you yet"* — and read it back out loud as a memory.
The full spoken artifact is in §5.2.

Fixed on both sides: `owner`/`user` are stopwords (there is exactly one owner
and they are the person asking, so that query is self-reference, which is the
recency mode's question), and the `query` parameter description now says what
*not* to invent. Seeded (S23).

---

## §4 — Work item 3: the corpus rows, pinned offline forever

`tests/test_scene_and_memory_answers.py` reads `queries.tsv` and asserts the
five rows verbatim, so a corpus edit cannot retire the question this file claims
to have fixed while every test below stays green:

| id | category | query | offline pin |
| --- | --- | --- | --- |
| 27 | scene | "What do you see around you?" | `test_q27_what_do_you_see_around_you_has_an_answer_at_all` |
| 28 | scene | "Is anyone near you?" | `test_q28_is_anyone_near_you_is_answered_from_the_person_tracks` |
| 29 | scene | "What's the closest thing to you?" | `test_q29_what_is_the_closest_thing_to_you_gets_one_field_not_three` |
| 30 | memory | "What do you remember about me?" | `test_q30_what_do_you_remember_about_me_returns_what_the_owner_said` |
| 31 | memory | "What did we talk about yesterday?" | `test_q31_what_did_we_talk_about_yesterday_reads_the_day_not_the_word` |

Both fixtures are fakes as the card asks: hand-built `SimObservation`s rebuilt
from live_run_1's own snapshot values (`nearest_person 1.7268 m @ 0.5547 rad`,
`obstacle 1.4276 m`), and in-memory `ConversationMemory` stores filled through
raw SQL so the LEGACY row shape (`speaker`/`origin` NULL) — which no writer in
this repo can still produce — is what the both-origins test actually exercises.

**`evals/` was not written.** It is not in this card's OWNS, the frozen-digest
gate watches it, and `results.json`/`live_run_1/README.md` remain the record of
what the run measured. Flipping those rows' recorded verdicts is owner-gated
(§9.1).

---

## §5 — Live proof

Five sessions, one process and one monotonic clock each. Everything real: the
MuJoCo city **with its pedestrians running** (no `--static-city`: a proof of "is
anyone near you" in an empty world proves nothing), the real `RobotRuntime`, the
real `DeterministicIntentRouter`, the real `RealtimeToolBroker`, the real
whisperer, and the real provider `gpt-realtime-2.1-mini` on a live WebSocket.
Nothing injected, nothing stubbed. Harness `<scratchpad>/r18/live_r18.py`;
reports `<scratchpad>/r18/r18_live_<scene>_<STAMP>.json`.

The scorer is **independent of the fix**: it reads the ledger and applies its own
blindness/eyes/filler regexes, and cross-checks the spoken words against the
scene report the DOOR actually returned — captured by an observing wrapper at the
instant it returned, because the city's pedestrians move and a capture taken a
second either side cannot verify a number.

### 5.1 Scene A — corpus 27/28/29, answered (`rt_dfd85de06b3a`)

```
owner  What do you see around you?
robot  "전방에 사람 한 명이 있고, … 교차로까지 약 3.2미터 앞쪽에 있습니다. 왼쪽에는
        식물통과 나무, 그리고 건물도 있고, 주변에 사람 7명이 추적되고 있습니다."
        (a person ahead; crosswalk ~3.2 m ahead; planter and tree to the left;
         a building; 7 people tracked)
owner  Is anyone near you?
robot  "네, 사람 7명이 추적되고 있고, 그 중에서 가장 가까운 건 바로 앞에 있는 사람이에요."
owner  What's the closest thing to you?
robot  "가장 가까운 건 라벨이 없는, 제 라이더가 감지한 물체입니다. 제 기준으로 약 0.9미터
        뒤에 있어요."  (the closest is an unlabelled thing my LiDAR detected,
        about 0.9 m behind me)
```

`broker: get_status ok ×3`. `tool_beats_requested 3, suppressed 0, refused 0,
lost 0, stalls 0`. Scorer: **blindness_claim False, claims_eyes False** on all
three; grounded tokens `3.2`, `7`, `0.9` all present in the door's own served
reports. **$0.074769.**

The English instance of the same scene, one run earlier (`rt_509c2116dbc0`,
**$0.069972**), for readability:

```
owner  What do you see around you?
robot  "Crosswalk 3.2 meters straight ahead. There are seven people tracked …
        There's a planter at 5.9 meters ahead on my left and a tree also 5.9
        meters ahead on my left. There's a building at 6.0 meters on my left."
owner  What's the closest thing to you?
robot  "The closest thing is something my LiDAR detected, but the map has no
        label for it, and it's 1.3 meters behind me."
```

**The Korean is not a defect of this card and is worth recording.** The scratch
store is a copy of the owner's real ledger, whose tail contains Korean rows
(`가까운 벤치로 가죠`, and F1's `MBC 뉴스 이덕영입니다`), and the lane replays
that tail as conversation history. The model mirrored the history's language.
live_run_1 §f recorded the opposite failure (Korean in, English out); this is the
same knob with no owner in the loop. Reported, not fixed — it is nobody's card
yet (§9.4).

### 5.2 Scene B — corpus 30/31 against the OWNER'S OWN store (`rt_63a1b0c2417c`)

```
owner  What do you remember about me?
robot  "Earlier today you said a few things, like you've forgotten your phone
        and want to go back home, that you're hungry and want somewhere to get
        food, that you're tired and want to go home, and that you're ready and
        want me to come walk with you. You also mentioned liking a tie-dye top."

  recall_memory ok, detail (verbatim):
    earlier today you said: Oh wait, wait, I forgot to bring my phone, wait,
      just give me a second. Let's go back home. |
    earlier today you said: I'm hungry. Take me somewhere I can get food. |
    earlier today you said: Ugh, I'm tired. Let's go home. |
    earlier today you said: Here, I'm here. Walk with me. … |
    earlier today you said: I love that tie-dye top.

owner  What did we talk about yesterday?
robot  "Yesterday, you said stuff like 'Go to the sidewalk,' and 'go to
        sidewalk,' and I said navigation was ready, though the wave was waiting
        while we moved."
```

Every one of those five memories is a real row of the owner's own ledger, dated
from its own `created_at`, and every one is checkable. Scorer:
**blindness_claim False** on both turns. **$0.047744.**

**The first attempt at this scene is kept and reported, because it is the
finding.** At `rt_82c7d3351024` (**$0.042462**), before the `owner`-as-stopword
fix, the same question produced:

> *"On Saturday you said, "come back to the owner." **Earlier today, I said I'm
> at 90 percent battery, and there's no memory of what I know about you yet.**
> Earlier today you also said: "go to the owner," "walk around the owner," and
> "circle the owner once.""*

The robot recalled **its own F4 lie from owner_session_1** and read it back out
loud. My scorer's `BLINDNESS` regex flagged it, which is how it was caught. That
run is the reason §3.3 exists and the reason S23 is a seed.

### 5.3 Cost, and the owner's stack

| scene | session | what | cost |
| --- | --- | --- | --- |
| A | `rt_9943d7430610` | 27/28/29, before the rounding + `closest` fixes | `$0.065325` |
| B | `rt_82c7d3351024` | 30/31, the `query: "owner"` finding | `$0.042462` |
| B | `rt_63a1b0c2417c` | 30/31, after the fix | `$0.047744` |
| A | `rt_509c2116dbc0` | 27/28/29 in English | `$0.069972` |
| A | `rt_dfd85de06b3a` | 27/28/29 with exact door captures | `$0.074769` |
| | | **total** | **`$0.300272`** |

**The owner's stack was not running** for the whole card — nothing listening on
8765 or anywhere in 87xx/88xx, checked at the start with `ss -ltnp`. No HTTP
request of any kind left this session, not even a read-only GET, because there
was nothing to GET. `~/.config/parcel/realtime.yaml` was never read or written;
each session used a scratch lane config of its own. The credential was loaded
with `set -a; . ~/.config/parcel/realtime.env; set +a` and never printed,
asserted against or written anywhere.

### 5.4 The owner's database: read-only, and proved so

The card's rule is *"read the original read-only, never open it for writing"*.
Three independent guarantees, in order of strength:

1. **The copy is taken through a `mode=ro` URI.** `live_r18.py` opens
   `file:…parcel_memory.sqlite3?mode=ro` and uses SQLite's own `backup()` API to
   fill the scratch copy — the source handle is one the engine itself refuses
   writes on.
2. **The runtime never sees the original.** `configs/robot.yaml` is COPIED with
   only `memory.path` redirected at the scratch copy (R5 deviation 6).
3. **Measured before and after, every run.** `sha256` **and** `mtime_ns` of
   `parcel_memory.sqlite3` are recorded at the top of each report and re-read
   after the stack closes. All five runs: `untouched: true`, sha256
   `a79aebbf820251b9…` unchanged.

And the promise is now executable rather than a discipline:
`ConversationMemory(path, read_only=True)` opens `mode=ro` and skips the
`CREATE TABLE`/`ALTER TABLE` the constructor otherwise runs, so a write raises
`sqlite3.OperationalError` from the engine. Seeded (S20) — delete the branch and
the write succeeds.

### 5.5 What the live proof does NOT show

* **No human has heard any of this.** Every session was `mode: text`. The
  defects were found by a human speaking to the robot; the fix is proven in
  typing.
* **Only the mini tier was exercised.** `gpt-realtime-2.1` may narrate the same
  results differently. The mini tier is the one the owner's runs use.
* **The numbers the model spoke about MOVING pedestrians cannot be pinned to a
  single instant.** The door was read 322 times during a 16-second turn (the DI
  provider re-renders every driver tick) and the nearest-person distance swept
  the whole range 0.0 → 6.3 m inside each turn, because the city's pedestrians
  walk through the robot's footprint. What IS verified exactly: a `get_status`
  call happened, the labels and directions spoken match the door's own reports,
  the closest-thing wording survived verbatim (including through translation),
  and no blindness or eyesight claim was made. What is NOT verified is that "0.9
  m behind me" was the reading at that exact millisecond.
* **The pre-call filler is still there** in three of six answer turns ("Let me
  check my surroundings for a moment"). That is R19's Open risk 5 exactly — the
  provider co-emits an announcement before the call and R5 proved it is not
  suppressible under three SI wordings on this tier. The ANSWER now follows it
  every time, which is the property that matters and the one live_run_1 lacked.
  Reported as SI-v3 / model-tier input, as R19 already did.
* **Corpus 29 was answered from the LiDAR return, not from a labelled place,**
  because in the city block the nearest thing genuinely was an unlabelled
  return. The labelled-nearest and person-nearest arms of `_scene_closest` are
  proven offline only.

---

## §6 — Gate and seeds

### Gate, verbatim, after the final edit

```
CI GATE — tier=commit  (2026-08-20T21:49:41Z)
==============================================================================
[  PASS] HARD  ruff                       7 violation(s), baseline 7, new 0
[  PASS] HARD  hard-safety                nav frozen baseline nav-instruct-v1-baseline-v4-20260811T070536Z: collisions=0 false_arrival=0 | mutation panel clean: collisions=0 no_false_arrival=True | mutation panel freshness: committed fields reproduce live = True | follow-bench: 7 row(s), hard_collision_total all 0 = True | walk_with_me: 1/2 row(s) with hard_collision_total, all 0 = True
[  PASS] HARD  frozen-digest-sentinels    4 immutable manifest(s) byte-identical to pin
[  PASS] HARD  release-parity             91 packaged asset(s) byte-identical to canonical source
[  PASS] HARD  latency-tail-ledger        latest row latency-20260810T082415Z-4d83035f: 6 metric series within 1.2x tail ceiling (rows=5, window=5)
[  PASS] HARD  follow-bench-jerk-ratchet  latest shipped row follow-bench-v1-20260811023618Z-93eba090.json: 1.2187 <= 1.46244 (baseline 1.2187 x 1.2)
[  PASS] HARD  model-off-non-inferiority  23 passed in 0.47s
[  PASS] HARD  frozen-digest-integrity    6 passed, 1 warning in 0.34s
[  PASS] HARD  release-parity-integrity   10 passed in 0.74s
[  PASS] HARD  mutation-panel-freshness   2 passed, 3 warnings in 4.29s
[  PASS] HARD  latency-tail               6 passed, 2 warnings in 0.40s
[  PASS] HARD  default-suite              6933 passed, 9 skipped, 42 deselected, 6 warnings in 267.76s (0:04:27)
==============================================================================
RESULT: PASS — every hard gate green.
  elapsed 280.8s
```

### Seeds — 26, all RED, R9 session-B + AUDIT_R12_R16 §register 1

Harness `<scratchpad>/r18/seed_r18.py`. One startup snapshot of all four source
files; per seed: repair drift, mutate exactly one source file, purge every
`src/**/__pycache__`, **verify a fresh-interpreter canary actually sees the
mutation**, run the named pytest target, restore in a `finally`, purge again,
assert byte-identity. No test file, config or eval artifact is ever mutated.

| # | Seeded defect | Result | The test that reddened (each run alone, 1 failed) |
| --- | --- | --- | --- |
| S1 | the scene block invents an object class (the _realtime_places fallback) | **RED** | test_the_scene_block_names_only_labels_perception_is_holding |
| S2 | no reading becomes a blindness claim again (owner_session_1's F3, verbatim) | **RED** | test_no_observation_at_all_is_no_reading_and_never_a_blindness_claim |
| S3 | the fact lines start claiming eyesight | **RED** | test_no_part_of_the_scene_answer_claims_eyesight |
| S4 | the scene never reaches get_status: F3's missing-tool defect, restored | **RED** | test_the_runtime_status_digest_carries_the_scene |
| S5 | every dynamic track counts as a person (the car is a bystander) | **RED** | test_only_a_track_perception_calls_a_person_is_counted_as_one |
| S6 | bearings are spoken in the OWNER's frame, which points them the wrong way | **RED** | test_the_bearing_words_are_the_robots_frame_and_not_the_owners |
| S7 | a repeated label is named once per instance instead of once per label | **RED** | test_a_repeated_label_is_named_once_at_its_nearest_instance |
| S8 | the DI block and the tool answer are rendered by two different writers | **RED** | test_the_di_lines_and_the_tool_answer_describe_one_world |
| S9 | get_status's description reverts, so no scene question ever routes to it | **RED** | test_the_get_status_description_is_what_routes_a_scene_question_to_it |
| S10 | the answer stamp is dropped: the scene answer becomes suppressible again | **RED** | test_the_scene_answer_is_stamped_unsuppressible_by_the_broker |
| S11 | the DI renders a scene header with nothing under it (the DI_VERSION pin) | **RED** | test_the_di_render_is_pinned_for_a_fixed_injected_instant |
| S12 | the DI scene header stops admitting it is a session-boundary snapshot | **RED** | test_the_di_scene_header_admits_that_it_is_a_snapshot |
| S13 | recall ignores one origin: the speaker IS NOT NULL filter, restored (F4) | **RED** | test_recall_reads_both_origins_and_not_just_the_hosted_one |
| S14 | provenance dropped: a memory comes back with no instant attached | **RED** | test_every_recalled_memory_carries_when_it_was_said |
| S15 | an undated row is given an invented instant instead of none | **RED** | test_a_row_with_no_usable_instant_is_said_without_a_date_not_with_a_guess |
| S16 | a time word is searched for as a topic: corpus q31 goes empty again | **RED** | test_q31_what_did_we_talk_about_yesterday_reads_the_day_not_the_word |
| S17 | the day window is applied AFTER de-duplication, which empties whole days | **RED** | test_a_named_day_bounds_a_keyword_search_too |
| S18 | session bookkeeping is recalled as conversation | **RED** | test_session_bookkeeping_is_never_offered_as_a_memory |
| S19 | a one-word partial match is offered as a memory alongside the real hits | **RED** | test_a_partial_match_is_only_offered_when_nothing_matched_better |
| S20 | the read-only open is ignored: the owner's own database is opened for writing | **RED** | test_a_read_only_store_refuses_every_write_at_the_engine |
| S21 | "me" becomes a self-marker again and orders crowd out what the owner told you | **RED** | test_me_is_not_a_self_marker_because_it_is_how_orders_are_given |
| S23 | "owner" becomes a topic word again: the model's invented query matches orders | **RED** | test_the_query_the_model_invents_for_a_question_about_the_owner |
| S24 | distances go back to two decimals, which the live tier speaks as 'zero meters' | **RED** | test_a_distance_is_rounded_before_the_model_ever_sees_it |
| S25 | the closest-thing field is dropped and q29 goes back to being an inference | **RED** | test_q29_what_is_the_closest_thing_to_you_gets_one_field_not_three |
| S26 | an unlabelled LiDAR return is given a class it does not have | **RED** | test_the_closest_thing_is_named_by_its_kind_and_never_given_a_class |
| S22 | the owner's own turns stop outranking their orders in the recency answer | **RED** | test_q30_what_do_you_remember_about_me_returns_what_the_owner_said |

**Whole-tree repair check: 4/4 files byte-identical. 26/26 RED**, against the
startup snapshot the closing gate scored (`runtime.py b1f7bcd0092cdf0a`,
`memory.py a5b4413cdcb048b5`, `prompting.py dcf85011cdc55154`,
`tool_broker.py c82ace9a08b81694`).

Three sweeps ran and all three are kept. **`seeds_1.txt` found S9 GREEN** — my
first `get_status`-description test was loose enough that replacing the
description's opening sentence left the assertions satisfied by the surviving
fragments. The test was tightened to assert the three routing clauses and the
two honesty clauses by name, the seed re-aimed at the routing clause itself, and
both went RED in `seeds_2.txt`. A seed that fails to redden is the harness doing
its job. `seeds_3.txt` is the final sweep, re-run after the last source edit
(the no-observation arm gaining `"closest": None`) so that the seed table and
the pasted gate describe the same bytes.

**Two gates are on the record and both are green.** `gate_final.txt`
(6932 passed) preceded that last edit; `gate_final2.txt` above (6933 passed) is
after it. The register's rule is a gate after the final edit, and that is the
one pasted.

---

## §7 — Deviations, each with its reason

1. **`DI_VERSION` was not bumped for a new DI flag**, against
   `render_developer_instruction`'s own docstring rule. Reason and evidence in
   §2.4: the block is appended last and absent by default, so every pre-R18
   input renders byte-identically; a bump would redden
   `test_the_manifest_agrees_with_the_tree_field_by_field` and invalidate 25
   sealed corpus fixtures in a pack this card does not own. The docstring now
   carries the exception and its reason, and S11 pins the claim.
2. **`memory.py` gained a constructor argument**, where the card says READ paths
   (smallest honest touch). `read_only=` is about how the store is OPENED for
   reading, and it exists because the card requires reading the owner's live
   database — a promise a script can break silently, since this class's own
   constructor creates a table and runs a migration. Six lines, one branch,
   seeded.
3. **`recall_memory`'s tool description was rewritten**, which is surface, not
   plumbing. Justified by the live finding in §3.3: the model chooses the query
   string, and the description is the only place that choice can be steered
   without touching the SI. `get_status`'s description is changed for the same
   reason and is explicitly the card's item-1 routing half.
4. **`_scene_closest` and one-decimal rounding are not in the card's wording.**
   Both came out of the live proof (§2.3) and both serve corpus 29 directly.
   Reported here rather than folded in silently.
5. **The scene block was added to the DI without a whisperer/lane path.** The
   card offers "available to the DI at session boundaries" and that is all this
   does; nothing mid-session pushes scene facts at the model, and `get_status`
   remains the only thing that answers "right now".
6. **Two live scenes were re-run after mid-card fixes** (A twice more, B once
   more). The superseded runs are kept, reported and costed rather than deleted
   — the first B run is the evidence for §3.3.

---

## §8 — What this does NOT prove (does_not_prove)

* **The SI was not touched, and the model can still say something false.** The
  card's rule is that a blindness claim WITH the tool available is an SI-v3
  input, not an edit here. In five live sessions no blindness claim was made
  once the tool could answer — but five sessions on one tier is not a
  guarantee, and the offline pins cover the tool-answer path, not the model's
  mouth.
* **The scene block is a snapshot in the DI and can be stale.** The header says
  so and `get_status` is the live read, but nothing prevents a model from
  reporting a session-boundary block as the present. Not measured.
* **`_row_instant` converts UTC to the MACHINE's local time**, which is the one
  ambient thing in the memory module. It is deliberate — "yesterday" and "on
  Tuesday" are claims about the owner's day, not UTC's — and it means the same
  database read on a machine in another timezone would date some rows
  differently. Stated, not solved.
* **The recall ranking is a judgement, not a measurement.** The 3-word floor's
  cousin: `RECALL_MIN_CHARS = 12`, `RECALL_LIMIT = 5`, `RECALL_SCAN_ROWS = 4000`
  and the 2.0/1.0 self-marker weighting were all chosen against the owner's real
  store and this file's fixtures. Nobody has A/B'd them.
* **The stopword and time-word lists are word lists, and word lists are never
  complete.** Every entry is a word that appears in the corpus questions or that
  the model actually produced; the next session can invent a query these read
  wrong. The failure direction is the defence — an unrecognised word is treated
  as a real search term, which costs a worse match rather than a silent miss.
* **The recall can quote the robot's own past false statements back.** The
  keyword and named-day modes search both speakers, so a sentence like
  owner_session_1's *"there's no memory of what I know about you yet"* is a real
  ledger row and can be recalled. The self-referential mode no longer reaches it
  (§3.3), and the provenance framing makes it a quotation ("earlier today I
  said…") rather than a claim, but nothing filters the robot's own errors out of
  its own memory. Open risk 2.
* **The person count counts TRACKS, not people.** Two tracks of one person
  behind a pillar is "2 people tracked", and that is what it says — "tracked" is
  doing honest work in that sentence.
* **No `mode: audio` run.** R19's Open risk 1 stands unchanged: the beat-refusal
  race cannot be reproduced in text mode, and the answer beats measured here
  (`refused 0, lost 0`) are text-mode numbers.
* **The scoring artifacts were not corrected.** `live_run_1/results.json` and its
  README still record scene and memory as FAIL, which is what the run measured.
  `evals/` is not this card's to write.

---

## §9 — Open risks and owner-gated items

1. **The corpus verdicts are owner-gated.** Card item 3 says categories `scene`
   (27–29) and `memory` (30–31) "flip from expected-FAIL to expected-PASS". They
   are now pinned as PASS in the offline suite, forever, on every commit. What is
   NOT done is editing `evals/20260820/voice_corpus_v1/**` to re-record the live
   verdicts — that pack is outside OWNS and its digests are gate-watched. The
   honest flip is **re-running those five queries live** in run 2 and letting the
   scorer record what happens. Recommend it as run 2's first block.
2. **Nothing filters the robot's own past errors out of its own memory** (§8).
   A card that marks a ledger row as retracted — or that prefers owner turns
   whenever both sides match equally — would close it. Not this card's.
3. **The DI provider re-renders every driver tick**, so `scene_report` now runs
   at tick rate (322 times in a 16-second turn, measured). It is O(regions +
   objects + agents) with one lock acquisition and it is strictly cheaper than
   the `realtime_turns` SQL query the same provider block already runs every
   tick — but if the DI is ever throttled, both should be throttled together.
4. **Language mirroring is unowned** (§5.1). The lane replays a Korean-bearing
   history tail and the model answers in Korean; live_run_1 measured the
   opposite (Korean in, English out). Neither behaviour is anybody's card and
   both are owner-visible.
5. **`conversation_store.py` is still not read by anything.** Its own docstring
   says so, and this card did not change that: `recall` reads the `messages`
   ledger because that is where the owner's 2,882 rows actually are. Re-pointing
   recall at the Protocol store is the follow-up that card R2-D named, and doing
   it here would have been a migration wearing a read's clothes.
6. **A concurrent session is writing in this tree.** At 17:05:34 today
   `evals/companion/realtime_convo_v1/corpus.manifest.json` was regenerated
   under SI **v2** while the corpus is an SI-v1 artifact, reddening
   `test_the_manifest_agrees_with_the_tree_field_by_field` and
   `test_the_manifest_records_the_model_versions_and_the_captured_scrape` in my
   baseline gate. I did not touch it (it is outside OWNS and belongs to another
   session's work); by 17:16:32 it had been restored to `si-companion-v1` and
   both tests are green in the closing gate. Recorded because the baseline gate
   output is on the record as RED for two tests that were never mine, and
   because it is live evidence for the register's concurrency warning. The same
   actor also wrote **four rows into the owner's `parcel_memory.sqlite3` at
   21:12:52Z** — before my first live run and before my only read of the
   original. Every one of my five runs recorded the file's sha256 **and**
   `mtime_ns` unchanged across the run, and both still match now
   (`a79aebbf820251b9…`, `mtime_ns 1787260372025889983`), which is also the
   proof that `ConversationMemory(path, read_only=True)` left the real file
   alone when §3.1's smoke test read it.
7. **THIS SESSION committed, staged and stashed nothing** — no `git add`, no
   `git commit`, no `git stash` was run at any point, and `git stash list` is
   empty. **But the tree is no longer in the state that sentence usually
   describes, and the auditor must know why before running their own checks.**
   Between this session's start and its end, a concurrent actor:

   * moved `HEAD` from `8473a51` to **`877d9f4 "Implemented voice agent"`**
     (author date 2026-08-17 06:04:20, landed today). Verified: that commit
     does **not** contain this card's work — `git show 877d9f4:src/parcel_robot/
     runtime.py | grep -c scene_report` is `0`, and neither
     `tests/test_scene_and_memory_answers.py` nor this status doc is in its
     tree;
   * then staged **237 files** on top of it, which sweeps up all six of R18's
     files (`git diff --cached --stat` shows `runtime.py`, `memory.py`,
     `prompting.py`, `tool_broker.py`, `test_scene_and_memory_answers.py`,
     `R18_STATUS.md`).

   **I did not unstage them.** The register's rule is never to revert or
   re-stage another session's work, and `git reset` here would discard 231
   other files' staging that is not mine to judge. The working tree — which is
   what the gate, the seeds and the live proof all scored — is untouched by
   any of it. Flagged rather than tidied.

---

## §10 — Restart required

`runtime.py`, `memory.py`, `prompting.py` and `tool_broker.py` are not
hot-reloadable. The owner's stack must be relaunched to pick up the scene
answer, the DI block and the new recall:

```
./scripts/launch_stack.sh
```

No config change is needed — every new behaviour is on by default, and the DI
block appears only when perception has a reading.

**Owner-visible outcome after that restart:** "what do you see around you", "is
anyone near you" and "what's the closest thing to you" get real answers from
LiDAR and the semantic map, with distances and directions and no invented
eyesight; and "what do you remember about me" answers with things the owner
actually said, dated, from every conversation they have ever had with this
robot rather than only the hosted ones.

---

## §11 — Evidence artifacts (scratchpad, outside the repo)

`…/799cb356-4cb4-445b-a784-306b6c6fd4a6/scratchpad/r18/`

| File | What |
| --- | --- |
| `seed_r18.py` | the 26-seed harness (snapshot → mutate one source file → purge `__pycache__` → fresh-interpreter canary → named pytest target → restore → purge → byte-identity assert) |
| `seeds_1.txt` / `seeds_2.txt` / `seeds_3.txt` | all three sweeps; `seeds_3.txt` is the final one, against the tree the gate scored |
| `gate_baseline.txt` / `gate_final.txt` / `gate_final2.txt` | the opening gate and the two closing gates; `gate_final2.txt` is the one pasted in §6 |
| `live_r18.py` | the live harness (in-process runtime, MuJoCo city with pedestrians, `mode=ro` copy of the owner's store, independent blindness/eyes/filler scorer, door-level scene capture) |
| `r18_live_{A,B}_<STAMP>.json` | the five machine-readable session reports: turns, per-turn verdicts, the scene reports the door actually served, broker calls, lane snapshot, owner-DB sha256 before/after, spend |
| `owner_memory_copy.sqlite3` | the read-only diagnostic copy §0.2's table was measured from |
