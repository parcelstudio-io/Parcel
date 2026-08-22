# P2-A — an owner model: facts the dog keeps, with consent · STATUS

**Card:** `README.md` · **Board:** `../TASK_BOARD.md` · **Executor:** Claude Opus
· **Verifier:** Fable · **Date:** 2026-08-22
**Pre-registration:** `P2A_PREREGISTRATION.md` (written before the first probe ran)

---

## 0. Headline

All six work items landed. The hosted model now arrives at a session knowing
what the owner has told it it may keep — `owner_facts` beside `messages`, a
`remember_fact` tool whose verdict is made by a **deterministic privacy policy**
and not by the model, an `owner_notes` block that has been rendered since the
prompt plane was built and **never once provided until now**, a real `Distiller`
where `null_distiller` was, and a session-open replay that carries the **whole
ledger, both lanes** instead of twenty hosted rows.

**The owner's store is byte-unchanged.** sha256
`0373297f818727cde96c8bf2254bd128e7bc2f829e49493d3229eb7c4e13da0d` before the
first edit and after the last command. It was opened exactly once, `mode=ro`,
to confirm the fact below. Its **mtime is still `2026-08-22 02:19`** — earlier
than this card's first command at 02:23 — so the file was never opened for
writing at all, which is the stronger statement and the one R27's register entry
asks for.

**The 256 synthetic rows are still there, and the distiller refuses to run.**
Measured read-only at 02:23 today: 3,163 rows total, **256 matching the R27
synthetic predicate in ids 2883–3138**, `created_at` 2026-08-20 21:12:29 →
2026-08-21 13:48:52, and **no `quarantined_messages` table**. The distiller
raises `SyntheticRowsUnquarantined` on that store and writes nothing. Clearing
it is the owner's action and is surfaced in §7, never performed.

**Pre-registered rows: 10 of 12 met, 2 declared MISS** (both owner-gated up
front). Three seeded REDs, one per new guard. Four declared deviations, §6.

---

## 1. What changed

| File | +/− | What |
|---|---:|---|
| **new** `src/parcel_robot/owner_model/policy.py` | 570 | the deterministic privacy policy |
| **new** `src/parcel_robot/owner_model/guard.py` | 275 | the synthetic-range refusal |
| **new** `src/parcel_robot/owner_model/distiller.py` | 563 | proposers + the guard→propose→decide→write pipeline |
| **new** `src/parcel_robot/owner_model/notes.py` | 115 | rows → `owner_notes` lines, consent filter inside the renderer |
| **new** `src/parcel_robot/owner_model/__init__.py` | 87 | the package surface |
| `src/parcel_robot/memory.py` | **+299 / −0** | `owner_facts` table, 5 methods, `ledger_tail` |
| `src/parcel_robot/realtime/tool_broker.py` | **+384 / −1** | the `remember_fact` region |
| `src/parcel_robot/realtime/lane.py` | **+80 / −1** | full-ledger replay: dedupe, cap, counters |
| `src/parcel_robot/runtime.py` | **+131 / −4** | **P2-A's share only** — 4 doors + 5 wiring hunks (§6) |
| **new** `tests/test_p2a_owner_model.py` | 65 tests | policy, table, consent, guard, distiller, broker |
| **new** `tests/test_p2a_memory_probes.py` | 27 tests | the probe family + the product-path wiring |
| `tests/test_conversation_store.py` | +16 / −3 | one baseline moved, **declared deviation** (§6.4) |

`memory.py` and `tests/test_conversation_store.py` were clean at `HEAD`, so
those numbers are `git diff --numstat` and are wholly P2-A's.
`lane.py`, `tool_broker.py` and `runtime.py` carry other cards' uncommitted work,
so **P2-A's share was measured by reconstructing each file's pre-P2-A text** —
reversing exactly the edits this card made and diffing:

```
$ git diff --no-index --numstat <reconstructed>/runtime.py src/parcel_robot/runtime.py
131     4       runtime.py
$ git diff --no-index --numstat <reconstructed>/lane.py src/parcel_robot/realtime/lane.py
80      1       lane.py
```

(`lane.py`'s whole working-tree delta vs `HEAD` is `+79/−1`: P0-B's `_idle_due`
guard is already committed, so the file's delta is essentially all P2-A's. The
reconstruction differs from `HEAD` by one blank line.) `runtime.py`'s whole
working-tree delta is `+965/−11`; the other 834 lines belong to P0-A, P0-D, P1-B
and P2-B and were not touched.

Every edit to an existing file was an exact-match, single-occurrence replacement
applied against the file **as re-read at that moment**; the patch scripts refuse
on 0 or >1 matches. No `git add/commit/stash/checkout/reset/restore` was run.
`realtime/prompting.py` is in OWNS and was **not edited** — see §6.1.

### 1.1 `realtime/prompting.py`: zero lines, on purpose

The card lists it for `owner_notes`. On reading it, the block was already
correct: `DeveloperFlags.owner_notes` exists, `render_developer_instruction`
renders it, it renders **nothing at all** when empty (so `PINNED_DI_DIGEST` and
the 25 sealed corpus fixtures survive), `_clean_lines` caps it at
`MAX_OWNER_NOTES`, and `DeveloperContext._call_lines` already swallows a
provider that raises. The defect was never in this file — it was that
`runtime.py` never passed a provider. Editing it to look busy would have risked
a collision with Fable's concurrent SI_V3 edit for no gain.

---

## 2. The six work items

### 1. `owner_facts` beside `messages`
Same file, because **card R27's owner-store isolation guard is on
`ConversationMemory.__init__`**. A separate `owner_facts.sqlite3` would be a
second path resolved by a second set of rules, and R27's whole lesson is that
the second set is the one nobody applies. `CREATE TABLE IF NOT EXISTS` only — no
`ALTER`, no backfill, nothing touched in `messages`. Columns: `key`, `value`,
`category`, `provenance` (`owner_stated | model_proposed`), `consent`
(`granted | pending | denied`), `confidence`, `reason`, `session_id`,
`source_turn_ids`, `writer` (R27's stamp), `created_at`, `updated_at`,
`deleted_at`.

**Upsert by key, not append.** A profile is not an event log: when the owner
moves house they do not live in two places. The event that changed it is still
in `messages`, which is where history belongs.

**Soft delete, and it is arguable.** A hard delete is the stronger *privacy*
promise; a soft delete is the stronger *audit* promise, and this table's failure
mode is a fact appearing that nobody can account for. Every read in the class
filters `deleted_at IS NULL`, so the belief is gone the instant it is forgotten;
what survives is the record that the robot once held it and was told to stop. A
hard-delete path is one `DELETE` away and is the owner's to ask for.

### 2. A real `Distiller` and a deterministic policy
`null_distiller` (wired at `dynamic_prompting.py:737`) returns `()` for every
summary it has ever been handed. `owner_model.distiller` replaces it with three
separable pieces:

* **a proposer** — `DeterministicFactProposer` (regex, offline, reproducible;
  the default, so a stack with no model server still learns something and every
  CI row measures a mechanism rather than a model's mood) or
  `LanguageModelFactProposer` over the existing `LanguageModel.decide` seam,
  degrading to the deterministic one on any failure, the same contract
  `runtime.LLMSummarizer` already holds next door;
* **the policy** — `owner_model.policy.decide`, which the proposer never calls
  and cannot influence. `FactCandidate` has **no consent field**, so a proposal
  has nowhere to put a verdict. That is HLD §8.4 as a shape rather than as a
  convention;
* **the guard** — work item 5, run first, before a single turn is read.

`OwnerFactDistiller` also satisfies the `tiered_memory.Distiller` protocol, so
it drops in where `null_distiller` sits today and emits **only `keep` verdicts**:
Tier 3 is rendered into prompts unconditionally by `dynamic_prompting`, so a
`pending` row reaching it would be a consent bypass through the side door.

The proposer reads **only the owner's side**. A robot that distils facts from
its own replies builds a profile of itself and calls it the owner, and every
hallucinated "you mentioned your sister Hana" would become durable on the next
pass.

**The policy's categories,** with the card's own list first:

| category | disposition | source |
|---|---|---|
| name, preference, routine, place | **keep** (`granted`) | the card |
| health, finance, third-party secret | **ask** (`pending`) | the card |
| *other* (unclassified) | **ask** (`pending`) | **declared addition**, §6.2 |
| secret (credentials) | **refuse** (never stored) | **declared addition**, §6.3 |

Order is the policy: sensitive lists are checked first, so "my sister's blood
pressure medication" is `health`, not `name`. `PolicyDecision.matched` reports
which words fired, so a surprising verdict is one grep from an explanation.

### 3. `remember_fact` in the broker
A NEW region beside P0-B's, following P0-B's result shape exactly (structured
result, not prose; a new named status rather than an overloaded `rejected`).
`action` ∈ `remember | forget | list`.

The order inside `_remember_fact` is the guarantee: parse → **supervisor** →
**policy** → door. Nothing between the policy and the door can turn a `refuse`
into a write, because the door never runs on a refusal. The policy's own
`reason` travels in the result, so the model is not left inventing an
explanation for a decision it did not make.

* admitted → `status: ok`, `stored: true`, and **the stored sentence in
  `detail`** so "I've remembered that your sister is called Hana" is true rather
  than plausible;
* sensitive → `status: consent_required` (new constant), `stored: false`, and a
  `pending` row on disk so "yes, remember that" has something to point at;
* credential → `rejected`, and **the door is not called at all**;
* `forget` never consults the policy — there is no rule under which the robot
  keeps a fact it was told to drop. A key it does not hold is `ok` with
  `forgotten: 0`, because making the owner argue about whether it ever had the
  fact is not a product;
* `list` answers from the table, and pending/denied facts are not mentioned, not
  counted and not hinted at — "I know three things and I can't tell you one" is
  a disclosure of the thing itself.

It joins `ANSWER_TOOLS` **and** `lane.DEFAULT_ANSWER_TOOLS` (a committed test
asserts the two sets are equal) so the beat carrying the result **cannot be
suppressed**. A robot that stores a fact about a person in silence is the
outcome this card exists to prevent. It joins `information_tools` for the
documented reason (`safety.py:40-42`): it touches no door that can move the
body, so it validates instead of falling into the fail-closed arm. It is **not**
wrapped in `_gate_by_voice`/`_watch_under_latch`, for R21's own stated reason —
a robot that cannot say what it knows, or be told to forget something, while it
is stopped is a different and worse product.

### 4. Full-ledger replay at session open
`realtime_turns(limit=20)` filters `speaker IS NOT NULL`, which is right for its
own job (a local typed turn must never be replayed as if the *hosted* agent had
said it) and wrong for this one. The consequence, measured: **the owner's 2,618
legacy panel/voice rows have never once been replayed into a hosted session.**

`memory.ledger_tail()` is the new source (both lanes, oldest last, via
`conversation_turns`, which recovers `speaker` from `role` for pre-R1 rows).
Dedupe and cap live **in the lane**, because that is the last point before the
wire and a future row source cannot route around it:

* deduped on `(role, casefolded text)` — the two write paths overlap, and
  replaying the owner's sentence twice teaches the model they said it twice;
* capped at `MAX_TAIL_ITEMS = 120`, newest kept. Twenty was too few to feel like
  memory; three thousand is a novel at every session open **and at every
  rollover**, paid again each time. The DI's six-line history digest still
  summarises what falls off the front;
* `tail_items_deduped` / `tail_items_dropped` published beside
  `tail_items_injected`, so "why only 60" has an answer.

### 5. The synthetic-range refusal (owner action surfaced, not performed)
`owner_model.guard`. A row is synthetic-suspect when **all three** hold: id in
2883–3138, `created_at` inside one of R27's two measured windows, and no
evidence the owner's stack wrote it. All three, so a fresh scratch store cannot
trip it — a scratch store that reaches id 2883 carries today's timestamps.

**Why refuse rather than filter.** Filtering would work and is the wrong shape.
The rows are not separable by content (R27 measured this: the owner has
genuinely typed most of those sentences on other days), so any filter is a
filter by id range — a hardcoded range silently deciding what the robot may
believe about its owner. If it is ever wrong, the failure is silent and the
wrong facts are durable. A refusal fails loudly and puts the decision back where
R27 left it. It is scoped as narrowly as the wave's "ask over refuse" rule
allows: one operation, one store shape, satisfied by a one-second command.

There is no `force` argument, no environment override and no keyword that skips
it.

### 6. The probe family
Pre-registered before measurement in `P2A_PREREGISTRATION.md`. Results in §4.

---

## 3. Seeded RED — behavioural, not missing-symbol

Each mutation is applied to a full copy of `src/` in
`/home/jaewoo-jang/.cache/parcel-p2a/`, with the *current* test files copied in,
so the assertions execute rather than dying at import.

### RED 1 — the synthetic-range refusal removed (`red/`)
`assert_store_is_distillable` returns the survey instead of raising.

```
4 failed, 86 passed, 2 errors in 0.83s
FAILED test_the_distiller_refuses_an_unquarantined_synthetic_range[1|2|3]
FAILED test_the_refusal_is_not_swallowed_by_a_value_error_guard
```

(The 2 errors are the scratch harness only: the two product-path tests resolve
`REPO` from `__file__`, and the scratch tree has no `configs/` or `prompts/`.)

**And the behavioural half** — the same mutated tree, on a store seeded with two
executor-shaped rows inside the R27 range:

```
guard: 2 suspect rows, clean = False
WROTE: 2
   durable belief about the owner -> preference | they like the fountain | granted
   durable belief about the owner -> routine   | they usually go to the lamppost | granted
```

On the real tree, the identical store: **REFUSED, facts written: 0**, and the
refusal names 2 rows, ids 2883–2884, the dry run and the `--apply` command.

### RED 2 — the consent boundary removed (`red2/`)
Three mutations, applied in two stages, because the boundary is deliberately
enforced **twice**.

*Stage 1* — the renderer's filter and the broker's credential-refusal arm:

```
5 failed, 81 passed
FAILED test_only_consented_facts_render_into_the_developer_instruction
FAILED test_only_consented_facts_appear_in_the_what_do_you_know_answer
FAILED test_the_renderer_filters_even_when_the_query_did_not
FAILED test_a_sensitive_proposal_is_parked_pending_not_kept
FAILED test_a_credential_never_reaches_the_store_at_all
```

with the concrete leak:

```
DI would carry: ('their sister is called Hana',
                 'their medication is amlodipine',
                 'their password is hunter2')
```

*Stage 2* — the store-level filter removed as well, i.e. **both layers gone**.
Only now do the end-to-end probe rows fall:

```
12 failed, 74 passed
FAILED test_row4_only_consented_facts_are_listed_or_rendered[1|2|3]
FAILED test_row5_a_health_fact_asks_first_and_never_renders[1|2|3]
+ the six above
```

That two-stage result is reported rather than smoothed over: it is the defence
in depth working, and it is also the honest statement that **the probe rows
alone would not have caught a single-layer regression.** The unit rows would
have.

### RED 3 — the full-ledger replay reverted (`red3/`)
`ledger_tail` delegates to `realtime_turns(limit=20)` and the dedupe/cap are
removed.

```
6 failed, 19 passed
FAILED test_row9_session_open_replays_both_lanes_deduped_and_capped[1|2|3]
FAILED test_row9_the_replay_is_capped_at_the_stated_ceiling[1|2|3]
```

---

## 4. The pre-registered family — measured

| # | Probe | k | Result |
|---|---|---|---|
| 1 | sister's name survives a restart | pass^3 | **MET** |
| 2 | stated preference recalled unprompted next session | pass^3 | **MET** |
| 3 | "don't remember that" honored | pass^3 | **MET** |
| 4 | what-do-you-know lists only consented facts | pass^3 | **MET** |
| 5 | the dog says what it will not store | pass^3 | **MET** |
| 6 | the dog confirms aloud what it stored | pass^3 | **MET** |
| 7 | distiller refuses an un-quarantined synthetic range | pass^3 | **MET** |
| 8 | quarantine clears the refusal | pass^3 | **MET** |
| 9 | full-ledger replay, deduped and capped | pass^3 | **MET** |
| 10 | a real hosted session stores a fact the model chose to store | — | **MISS — owner-gated** (declared in the pre-registration; needs one live `gpt-realtime` session) |
| 11 | the owner's real store distils real facts | — | **MISS — owner-gated** (blocked on the quarantine, §7) |
| 12 | the owner's store byte-unchanged | k=1 | **MET** — `0373297f…` before and after |

Rows 1–6 and 9 run **through the real lane**: a real `RealtimeLane` over the
repo's scripted `FakeRealtimeServer` and a real transport pair, the real
`RealtimeToolBroker` with the real policy inside it, a real `ConversationMemory`
on a scratch file, and the real `render_developer_instruction`. The only fakes
are the socket, the clock and the speaker. Rows 7 and 8 are store-level and were
**parametrized to three runs after the family was written but before it was
measured** — they were specified pass^3 and initially written as single runs;
the fix brought the code to the pre-registration, not the other way round.

**The product path is proven separately.** Everything above builds the lane and
broker by hand, which proves the mechanism and nothing about whether
`runtime.py` connects it. Two tests build a real `RobotRuntime` with the hosted
lane on and assert the four seams are live — the three doors, the `owner_notes`
provider (DI block absent → fact stored → block present, in the same test), and
the ledger row source (`realtime_turns` sees 1 row, `ledger_tail` sees 2).

---

## 5. Gates

```
$ .parcel/bin/python -m pytest -q tests/test_p2a_owner_model.py tests/test_p2a_memory_probes.py
92 passed

$ .parcel/bin/python -m pytest -q tests/test_realtime_*.py
1192 passed, 2 skipped, 2 xfailed

$ .parcel/bin/python -m pytest -q tests/test_owner_store_isolation.py tests/test_conversation_store.py \
      tests/test_tiered_memory.py tests/test_dynamic_prompting.py \
      tests/test_scene_and_memory_answers.py tests/test_false_positive_memory.py
309 passed

$ .parcel/bin/python -m pytest -q tests/test_p0b_companion_unlocks.py tests/test_fail_closed_limits.py \
      tests/test_arrival_semantics.py tests/test_owner_estop.py tests/test_unknown_place_admission.py \
      tests/test_mission_log.py tests/test_safety_log.py tests/test_held_out_scene.py -m ""
400 passed

$ .parcel/bin/ruff check src/parcel_robot/owner_model/ src/parcel_robot/memory.py \
      src/parcel_robot/tiered_memory.py src/parcel_robot/realtime/prompting.py \
      src/parcel_robot/realtime/tool_broker.py src/parcel_robot/realtime/lane.py \
      src/parcel_robot/runtime.py tests/test_p2a_*.py tests/test_conversation_store.py
All checks passed!
```

**The RED trees carry OLDER test files than the tree they are compared against.**
`red/` was refreshed with the current tests; `red2/` and `red3/` were run against
the **86-test** version of `test_p2a_owner_model.py`, before rows 7 and 8 were
parametrized to pass^3 (§4) — so their "81 passed" / "74 passed" / "19 passed"
denominators are smaller than today's 99. **The failure counts and the failing
node ids stand**; only the passing denominator moved, and no mutation's verdict
depends on it. Re-running `red2`/`red3` with the current files would change the
totals and not the conclusion.

`scripts/ci_gate.py` was **not** run (P0-E owns it; the card says targeted only).
New tests carry no `slow` marker, so they land in the commit tier — P0-E's
`tier-coverage` identity should absorb 92 more commit-tier tests with no
orphans.

### Two failures in the tree that are NOT P2-A's

Both were checked and attributed before being left alone, per the standing rule
about other executors' work:

* `tests/test_r24_lock_discipline.py::test_the_lock_roster_is_complete` —
  `RobotRuntime.__init__ constructs a lock this file does not order:
  ['_p1b_map_lock']`. That is **P1-B** (task_7).
* `tests/test_prototype_profile.py::test_realtime_prototype_example_validates_and_carries_its_departures`
  — extra keys `whisperer.owner_events.enabled` /
  `whisperer.owner_events.greeting_interval_s`. That is **P2-B** (task_11).

`tests/test_realtime_tool_broker.py::test_the_runtime_builds_a_broker_only_when_the_lane_is_enabled`
was red mid-card on P2-B's `identity_labels`/`owner_events` snapshot keys and is
green again as of the final sweep; P2-B fixed it concurrently. Nothing was
reverted.

---

## 6. Deviations from OWNS (declared)

### 6.1 `realtime/prompting.py`: **0 lines**, inside OWNS
Not a change but a non-change, declared because the card names the file.
Reasoning in §1.1. Also avoided a collision with the auditor's concurrent
SI_V1/SI_V2/SI_V3 + `SI_DIGESTS` edit, which was announced mid-card.

### 6.2 The policy's `other` category asks rather than keeping
Not in the card's list. The wave's rule is *ask over refuse*, and for a store
the owner cannot see the fail-safe direction is to ask before keeping, never to
keep silently. Costs one question; cannot cost a surprise.

### 6.3 A credential is REFUSED, not asked about
The one refusal path this card adds beyond the guard, and the standing rule says
not to add refusal paths — so it is declared rather than smuggled. It is not a
behavioural fail-closed of the kind the wave loosened; it is a property of the
storage medium. `owner_facts` is plaintext, it is rendered into a hosted model's
developer instruction at every session open, and the robot is built to say what
it knows out loud. "Ask first" is not a meaningful protection for a value whose
entire risk is that it exists in that file at all. Narrow: a 15-word list, and
`PolicyDecision.matched` names which word fired. **If the verifier disagrees,
moving `CATEGORY_SECRET` from `REFUSE_CATEGORIES` to `ASK_CATEGORIES` is a
one-line change** and two tests state the current behaviour explicitly.

### 6.4 `tests/test_conversation_store.py` (+16 / −3) — outside OWNS
`test_the_default_store_is_none_and_behaviour_is_byte_identical` (card R22)
asserted `tables == {"messages"}`, i.e. that the conversation store grows **no**
table. P2-A adds `owner_facts` to that file by design (work item 1), so the
assertion is now false and the card is unimplementable without moving it.

Moved the **baseline only**: it is still an exact set,
`{"messages", OWNER_FACTS_TABLE}`, so a third table appearing — from the
dual-write seam or anywhere else — still reddens it, and the two ledgers must
still agree with each other. The docstring records what moved and why. This also
un-redded
`test_owner_store_isolation.py::test_the_commit_suite_opens_no_connection_to_the_owner_store`,
which runs the commit suite in a subprocess and was failing on the same
assertion.

### 6.5 `runtime.py` (+131 / −4) — outside OWNS
`runtime.py` is not in P2-A's OWNS, but the card's deliverables 2, 3 and 4 are
validated code that nothing calls without it — the same argument P0-B made for
its own two-line broker wiring, and the alternative (having the broker or the
prompt plane reach into the store ambiently) is worse for an auditor. Five
wiring hunks and four methods, all disjoint from every other card's regions:

| where | what |
|---|---|
| imports ×5 | `FACT_OWNER_STATED`, `owner_model` (4 names), `MAX_TAIL_ITEMS`, `MAX_OWNER_NOTES`, `TOOL_REMEMBER_FACT` |
| `DeveloperContext(...)` | `owner_notes=self._realtime_owner_notes` |
| `information_tools` | `\| {TOOL_RECALL_MEMORY, TOOL_REMEMBER_FACT}` |
| `ToolDoors(...)` | `remember_fact` / `forget_fact` / `known_facts` |
| `RealtimeLane(...)` | `memory_tail=` → `ledger_tail` |
| after `_realtime_recall` | `_realtime_remember_fact`, `_realtime_forget_fact`, `_realtime_known_facts`, `_realtime_owner_notes` |

Not P0-A's camera-flag regions, not P0-B's `submit_realtime_transcript` region
or its `RealtimeToolBroker(...)` kwargs, not P0-D's 8396–8460 / 557–575, not
P2-B's affect region. Nothing in `runtime.py` outside that table is P2-A's.

### 6.6 `lane.py`'s `DEFAULT_ANSWER_TOOLS`, outside the replay region
OWNS names "`realtime/lane.py` session-open replay region". `DEFAULT_ANSWER_TOOLS`
is elsewhere in the same file. A committed test asserts
`ANSWER_TOOLS == DEFAULT_ANSWER_TOOLS`, so adding `remember_fact` to one without
the other is a red test rather than a choice.

---

## 7. Owner action — surfaced, NOT performed

**Quarantine the 256 synthetic rows before the distiller ever touches the real
store.** Measured read-only today at 02:23:

```
total rows          : 3163
ids 2883–3138       : 256   (all 256 match the R27 synthetic predicate)
created_at          : 2026-08-20 21:12:29 .. 2026-08-21 13:48:52
quarantined_messages: table does not exist
```

Look first (safe, `mode=ro`, changes nothing):

```
.parcel/bin/python tools/quarantine_synthetic_memory.py
```

then, if the report is right:

```
PARCEL_MEMORY_PURPOSE=owner .parcel/bin/python tools/quarantine_synthetic_memory.py --apply
```

It **moves** the rows into `quarantined_messages` and never deletes them; the
dry run prints the one-line undo. **This card did not run either command.** Until
`--apply` runs, `distil_session` on the owner's store raises and writes nothing —
which is the intended state, not a bug.

---

## 8. What this does not prove

* **No hosted session was opened. No model chose to call `remember_fact`.**
  Every provider function call in the probe family is scripted. What is proven
  is that the machinery answers correctly when the tool is called; whether the
  model reaches for it at the right moment is pre-registered row 10 and is
  unmeasured. The tool description was written against that risk (an explicit
  trigger list, an instruction not to promise before the result comes back) and
  the description is untested prose.
* **The distiller's taste is unmeasured.** Every CI row runs the deterministic
  regex proposer, so what is proven is the *mechanism* — guard, policy, write,
  render — and not that a language model proposes good facts.
  `LanguageModelFactProposer` has unit coverage for its degrade paths and has
  never been run against a real model.
* **The policy is a narrow keyword classifier and will miss paraphrase.** It
  fails toward `other`, which asks, so a miss costs a question rather than a
  silent keep — but "it will catch every health fact" is not a claim being made.
* **`MAX_TAIL_ITEMS = 120` is a judgement, not a measurement.** Nobody has
  measured the token cost of a 120-item replay at a rollover against the owner's
  real store, or how a 120-item session behaves in practice. It is 6× the old
  ceiling and the number to watch on the first desk run.
* **The soft delete is not a hard delete.** §2 item 1 states the trade
  explicitly. A `deleted_at` row is unreachable through this class but is still
  bytes in the file.
* **Nothing was measured on the owner's real data.** By construction (§7). The
  first real distillation run is unobserved, and the first thing to check after
  the quarantine is what it proposes — the offline proposer's broad "my X is Y"
  pattern is deliberately permissive and will produce `pending` rows for things
  that are not facts.
* **`prompting.memory` is still disabled in `configs/robot.yaml`,** so
  `OwnerFactDistiller`'s tiered-memory path is dormant in the product. The live
  path is `distil_session` over the conversation store, and **nothing calls it
  on a schedule yet** — see the handoff below.

---

## 9. Handoffs

* **Fable (verifier).** Look first at §6.3 (the credential refusal — the one
  place this card added a refusal path the wave's rules discourage) and §6.4
  (the moved baseline in another card's test file). The RED trees are at
  `/home/jaewoo-jang/.cache/parcel-p2a/{red,red2,red3}` and re-run with
  `PYTHONPATH=<tree>/src .parcel/bin/python -m pytest -q tests/`. The diff-vs-OWNS
  mismatches you will find are `runtime.py`, `tests/test_conversation_store.py`,
  and `lane.py`'s `DEFAULT_ANSWER_TOOLS`.
* **Nothing schedules distillation.** `distil_session` is wired, tested and
  callable, and no code path invokes it — not at session close, not on a timer.
  That is deliberate: the guard refuses the owner's store today, so an automatic
  pass would be a scheduled exception. It should be hooked to session close in
  the card that follows the quarantine.
* **P2-B (task_11).** `remember_fact` is the eighth broker tool and the broker
  snapshot grew `facts_remembered` / `facts_consent_asks` / `facts_refused` /
  `facts_forgotten`. If the identity work labels rows by speaker,
  `owner_facts.provenance` is the natural join: an `owner_stated` fact from a
  turn that identity could not attribute to the owner is a fact about a
  *visitor*, and neither card handles that today.
* **P1-D (task_9).** `unknown_place_asks` (P0-B) and `owner_facts` rows of
  category `place` are the same flywheel from two ends — the nouns the owner
  uses that the map cannot ground, and the places they have told the robot
  matter.
* **The panel.** Four new broker counters and two new lane counters
  (`tail_items_deduped`, `tail_items_dropped`) are published in the snapshots
  and nothing renders them. "What has this robot decided to keep about me" is a
  question the owner should be able to answer from the panel without opening a
  database, and right now they cannot.

---

## 10. Post-verification corrections

Verdict received: **CLAIMS_HOLD** — owner-store attribution (the 02:19 write was
the owner's own hosted session, `writer='owner_stack'`), isolation, the
synthetic-range guard on a fresh store, consent and the spoken credential
refusal driven through the real lane, the broker region, the replay, the
`runtime.py` share at exactly `+131/−4`, and pass^3 all reproduced. The
credential refusal (§6.3) is accepted as the one reasonable refusal under
ask-over-refuse. One product gap and three doc corrections follow.

**Owner store, re-checked read-only after every change below:** sha256
`0373297f818727cde96c8bf2254bd128e7bc2f829e49493d3229eb7c4e13da0d` — unchanged
from the start of the card. mtime still `2026-08-22 02:19:01`. Attribution
accepted and corrected here: §0's "never opened for writing at all" was true of
*this card* but the mtime is not evidence of that — it is the owner's own hosted
session, stamped `writer='owner_stack'`, and the verifier established that
independently.

### 10.1 GAP (closed) — the replay tail carried the credential

The finding, and it is a real one. `remember_fact` refuses to put "my password
is hunter2" into `owner_facts`, citing plaintext-read-aloud-to-the-hosted-model
as the harm. But the hosted lane still writes the raw **turn** to `messages`,
and P2-A's own full-ledger replay then reads up to 120 recent turns back to the
model at every session open — **the same exposure, arriving through a door this
card opened.** The refusal was load-bearing and the replay walked around it.

Closed **at replay**, with the **same** policy — one definition of "credential",
not two. `messages` is untouched: the ledger write is R22's surface and the
owner's record, and redacting the owner's own history is not this card's call.

| change | where | what |
|---|---|---|
| replay redaction | `lane._inject_tail` | a turn whose text `owner_policy.classify` calls `CATEGORY_SECRET` is skipped before dedupe and cap |
| counter | `lane` + snapshot | `tail_items_redacted`, published — a silent redaction is indistinguishable from a short history |
| event note | `lane._note` | names the role and the character count, **never the text**: a redaction that writes the secret into the event ring has moved it, not removed it |
| key redaction | `tool_broker._remember_fact` | on a `refuse`, the derived **and** model-supplied keys are discarded and the key is rebuilt from `decision.matched` alone — a subset of the closed `SECRET_TERMS` list, so it cannot contain anything the owner said. `wifi_password_hunter2` → `password` |
| the fact is not echoed | `tool_broker._remember_fact` | **beyond what was asked, declared here.** The refusal arm returned `"fact": "their wifi password is hunter2"`. Every other arm echoes the fact so the model can confirm what was stored; on this arm there is nothing to confirm, and repeating the value puts the credential straight back into the surface the arm exists to keep it out of. Replaced by `fact_chars`. The model sent the text and still has it; what it needs back is the verdict and the reason |

`_redacted_key` caps at `_FACT_KEY_WORDS`, so a fact matching several secret
terms still yields a short readable slug.

**Seeded RED** (`/home/jaewoo-jang/.cache/parcel-p2a/red4`, current test files),
both mutations at once — the replay filter removed and the key/fact redaction
reverted:

```
7 failed, 90 passed, 2 errors in 1.02s
FAILED test_a_credential_turn_is_never_replayed_into_a_session[1|2|3]
FAILED test_the_redaction_is_counted_and_noted_without_the_secret
FAILED test_the_refusal_the_model_reads_never_contains_the_credential[1|2|3]
```

(The 2 errors are the scratch harness only — the two product-path tests resolve
`REPO` from `__file__` and the scratch tree has no `configs/` or `prompts/`.)

GREEN, and note what the ordinary turns around the credential do: they are
replayed untouched, in order, so the redaction costs one item and not the
conversation.

```
replayed == [("user", "how was your day"),
             ("assistant", "warm and quiet"),
             ("user", "anyway, remind me to buy milk")]
tail_items_redacted == 1   tail_items_injected == 3
"hunter2" not in the replay, not in the event note, not in the lane snapshot
refused["key"] == "password"   "hunter2" not in the whole refusal result
```

### 10.2 Doc — dedupe keeps the OLDEST copy, and the source is bounded

Both now stated in `_inject_tail`'s docstring, because both are easy to assume
wrongly from the code:

* **Dedupe keeps the first occurrence.** A repeated sentence holds its original
  position in the conversation rather than jumping forward to its most recent
  restatement.
* **"The whole ledger" is bounded before the lane sees it.** The runtime's row
  source reads the newest `MAX_TAIL_ITEMS * 4` rows, so the replay is drawn from
  the newest **~480** turns — *not* literally the first row the owner ever
  typed. §2 item 4 and §0's "the whole ledger, both lanes" should be read with
  that bound: what changed is *both lanes* and *120 instead of 20*, not
  *unbounded*.

### 10.3 Doc — the tiered-protocol distiller path is unguarded, and dormant

`README`'s "the card's distiller refuses to run on a store with an
un-quarantined synthetic range" holds for **`distil_session`** — the product
path, which calls `assert_store_is_distillable` first and has no way to skip it.

It does **not** hold for `OwnerFactDistiller.__call__`, the
`tiered_memory.Distiller` protocol implementation: it receives a `SummaryRecord`
(prose that `TieredMemory` already folded) and never sees a store, so there is
nothing there for the guard to inspect. That path is **dormant** —
`prompting.memory` is absent from `configs/robot.yaml`, so `_build_tiered_memory`
returns `None` and nothing constructs a `TieredMemory` in the product (§8).

Two things follow, and they are the handoff: whoever enables `prompting.memory`
must run the guard **at the point the tiered store is built**, not inside the
distiller, and until then the honest claim is *"`distil_session` refuses"* rather
than *"the distiller refuses"*.

### 10.4 Minor — `STATUS_CONSENT_REQUIRED` joins `TENSE_BY_STATUS`

Shape parity with P0-B's `STATUS_UNKNOWN_PLACE` line. Harmless today —
`remember_fact` is not in `ACTIVITY_TOOLS`, so `_tensed` never runs on it — and
it is there so that a future activity tool returning `consent_required` gets the
right tense instead of a `.get` default nobody checked.

### 10.5 Gates after the corrections

```
$ .parcel/bin/python -m pytest -q tests/test_p2a_owner_model.py tests/test_p2a_memory_probes.py
99 passed                      (was 92; +7 credential rows)

$ .parcel/bin/python -m pytest -q tests/test_realtime_*.py
1192 passed, 2 skipped, 2 xfailed

$ .parcel/bin/python -m pytest -q tests/test_owner_store_isolation.py tests/test_conversation_store.py \
      tests/test_tiered_memory.py tests/test_dynamic_prompting.py tests/test_scene_and_memory_answers.py \
      tests/test_p0b_companion_unlocks.py tests/test_fail_closed_limits.py tests/test_unknown_place_admission.py
562 passed

$ .parcel/bin/ruff check src/parcel_robot/owner_model/ src/parcel_robot/memory.py \
      src/parcel_robot/realtime/tool_broker.py src/parcel_robot/realtime/lane.py \
      src/parcel_robot/runtime.py tests/test_p2a_*.py tests/test_conversation_store.py
All checks passed!
```

Revised shares. `runtime.py` was **not touched** in this round and re-measures at
exactly **+131/−4** against a reconstruction rebuilt from the current file, so
the verifier's number stands unchanged.

| file | §1 said | now | this round |
|---|---|---|---|
| `realtime/tool_broker.py` | +384 / −1 | **+423 / −1** | +39 |
| `realtime/lane.py` | +80 / −1 | **+126 / −1** | +46 |
| `runtime.py` | +131 / −4 | **+131 / −4** | unchanged |
| `memory.py` | +299 / −0 | +299 / −0 | unchanged |
| `tests/test_p2a_memory_probes.py` | 27 tests | **34 tests** | +7 |

### 10.6 What 10.1 still does not prove

* **The policy is the same narrow keyword classifier** (§8). It will skip
  "my password is hunter2" and will not recognise a credential the owner spells
  out without a trigger word ("the code is 4417"). The replay filter inherits
  every limitation of the classifier and is a reduction of exposure, not a
  guarantee of none.
* **The row is still in `messages`,** deliberately. `recall_memory` searches that
  table and is **not** filtered by this change — a direct "what did I tell you
  about the wifi" can still surface the turn. Filtering recall is a larger
  decision about the owner's own record and belongs to the owner, not to this
  card; it is named here so it is not mistaken for covered.
* **No hosted session ran.** As everywhere else in this card, the provider is
  the scripted fake.
