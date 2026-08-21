# R20 — Narnia is not on the map (unknown-place honesty)

**Executor:** Claude Opus (agent) · **Auditor:** Fable · **Date:** 2026-08-20
**Card:** `scrum/20260820/task_9/README.md`
**Dispatch gate:** "after R18 closes" — `scrum/20260820/task_7/R18_STATUS.md` exists
and is complete through its §10/§11 close-out. Verified before the first edit.

---

## §0 — ROOT CAUSE, written before a line was changed

### 0.1 The measurement, from the run's own artifacts

`evals/20260820/voice_corpus_v1/live_run_1/results.json`, rows 10 / 12 / 13,
and `README.md` §d:

| id | Spoken | What the stack did |
| --- | --- | --- |
| 10 | "Go to Narnia." | directive `go to Narnia` (ledger id=2769) → ack **"Okay—I'll go wait near narnia safely."** (id=2770) → mission id=16 `started goal=narnia state=searching reason=scan_behavior_rotate`, **4.25 s**, ended `task_no_longer_active` |
| 12 | "Take me to the moon." | directive `go to moon` (id=2774) → ack **"Okay—I'll go wait near moon safely."** (id=2775) → mission id=18, **10.7 s** of rotate-scan, the longest mission of the run |
| 13 | "Let's go back home." | **no directive row, no mission** — reply in 306 ms: *"…I don't know where home is yet. Just tell me the address or a familiar name…"* |
| 06 | "…take me somewhere I can get food." | directive `go to restaurant` → ack "Okay—I'll go wait near restaurant safely." → mission id=11, same `scan_behavior_rotate` signature (scored PARTIAL, same class) |

### 0.2 The fork, mapped to exact files

The fork is **not** where the card's trigger note guessed ("known-place list vs
open semantic search"), and it is worth stating plainly because it changes the
fix:

**"home" was never admitted at all, and not by policy.** `let's go home` carries
no `to`/`onto`/`into`, so it matches none of `_DESTINATION_PATTERNS`
(`src/parcel_robot/navigation/goals.py:192`); `navigation_directive_from_text`
returns `None`, no `navigate_to` tool call is ever produced, and the utterance
falls through to the conversation lane, where the **hosted model** wrote that
excellent ask itself. There is no deterministic ask-path for unresolvable
places anywhere in the tree. q13 did not take a refusal path — it missed the
admission grammar by a preposition. That is why the card's "the ask/refusal
path exists; the unknown-place class never reaches it" is only half true, and
the honest version is: **the ask had to be built, not re-routed.**

**"narnia" was admitted twice over, by two layers that each deferred to the
other:**

1. `src/parcel_robot/realtime/tool_broker.py:1358` `validate_place` — R10's
   junk-place gate. It refuses **argument shapes** ("with owner", "run route")
   and, in its own words, *deliberately* admits an unheard-of noun:
   `return PlaceVerdict(True, REASON_UNKNOWN_PLACE, …)` (line 1395). The
   docstring names the reason: `test_navigate_to_grants_exactly_what_a_typed
   _sentence_grants` pins authority parity with the typed panel, and "a broker
   stricter than the typed path would be the hosted lane growing its own
   private grammar."
2. `src/parcel_robot/runtime.py::_realtime_navigate` → the deterministic router.
   The router returned `route=direct_skill rule=navigation_directive` for
   "go to Narnia" and it was **right to**: the grammar is about SHAPE, and
   `go to <noun>` is a navigation directive whatever the noun is.

So the noun was never asked about. It went straight to
`agent._admit_local_sketch` → `runtime._accept_plan` → `_plan_acknowledgement`
(`runtime.py:2231`), whose `relation == "near"` arm is verbatim the string the
ledger recorded:

```python
return f"Okay—I'll go wait near {target or 'that landmark'} safely."
```

and then to the semantic resolution ladder, which has no way to say "there is
no such place" before scanning, so it scans: `reason=scan_behavior_rotate`.

### 0.3 The bench_eval_designs finding is the SAME defect, and it is in my fork

`scrum/20260820/research/bench_eval_designs.md` §Prototype C / §Ranked 4:

> the whisperer ack "Okay—I'll go wait near narnia safely." is itself a
> refusal-on-invalid-place defect this surfaced … the whisperer template acks
> confidently accept nonexistent places ("Narnia", "moon"), same overclaim
> family as F2, one layer lower.

That sentence is produced by `RobotRuntime._plan_acknowledgement`
(`runtime.py:2231`), which runs **after** `_accept_plan` has admitted the plan.
It is one layer lower than the tool result, and it is reached on **both** lanes
— the typed panel and the hosted `navigate_to` — because both go through
`agent._admit_local_sketch(…, plan_publisher=runtime._accept_plan)`.

It is therefore inside this card's fork, and it is fixed by construction rather
than by editing the template: **an unresolvable place never reaches plan
admission, so the ack is never written.** Editing the template itself would
have been the wrong fix — the template is not lying about the relation, it is
faithfully acknowledging a plan that should never have been admitted. Proved by
`test_the_refused_goal_never_becomes_a_mission_or_an_ack` (seeded RED by S4) and
by the live proof (§7.5, `ack_template_spoken: false` on both fabricated-mission
rows) — both assert the ack string is **absent**, not merely reworded.

### 0.35 The signal that was already in the log, unused

`mission_log.reason` already told the truth at mission-start, in live_run_1's own
data: unresolved goals show `state=searching reason=scan_behavior_rotate`
(narnia, moon, restaurant); resolved goals show `state=running` with a route
(`coffee shop at 42nd street` route=31, `crosswalk` route=3). The run's §d says
it plainly — *"The system already knows the difference at mission-start; it just
does not act on it."*

R20 does **not** act on that signal, deliberately, and the reason matters: by the
time `scan_behavior_rotate` is written the plan is admitted, the ack is spoken
and the body has been committed. Refusing there would mean taking back a promise
already made out loud. The gate belongs before the promise, which is where it
went.

That turned out to be doubly right: **the signal is not actually a
resolved/unresolved discriminator.** This card's own live session B shows a
*bench* mission — a real place that then planned `route=2` — opening with
`state=searching reason=scan_behavior_rotate` (§7.5 note 2). A card that had
keyed on it would have refused real places.

### 0.4 Where the fix had to go, and why not in the broker

The card's MUST-NOT-TOUCH list includes the broker, and that constraint is the
same conclusion the code forces anyway: refusing "narnia" in `validate_place`
alone would give the hosted lane a private grammar stricter than the panel's —
exactly what R10 forbade and what its two parity tests pin. The only way to fix
this without breaking parity is to put the policy in the layer **both** lanes
compile through (`navigation/goals.py`) and wire **both** admission paths to it.
`tool_broker.py` is untouched by this card.

---

## §1 — The policy, and the exact files

### 1.1 Frozen contract surface

New in `src/parcel_robot/navigation/goals.py` — pure, table-driven, no I/O:

| Name | What it is |
| --- | --- |
| `admit_navigation_place(directive, known, *, offer=())` | the verdict function. Both lanes call it. |
| `PlaceAdmission` | frozen dataclass: `admitted`, `query`, `reason`, `alternatives`, plus `.fact()` and `.reply()` |
| `place_query_from_directive(directive)` | the noun the compiler will hand the grounder |
| `PLACE_ADMITTED` `PLACE_EXPLICIT_SEARCH` `PLACE_OWNER_REFERENT` `PLACE_NO_VOCABULARY` `PLACE_NOT_A_DIRECTIVE` `PLACE_UNKNOWN` | reason codes — every admission reports WHY, not only refusals |
| `PLACE_OFFER_LIMIT = 3` | how many real places a refusal names |
| `_EXPLICIT_SEARCH_PATTERN` | the grammar's own locate-and-approach regex, now named and reused |
| `_destination_noun(text)` | lifted verbatim out of `semantic_goal_from_directive`; the gate and the compiler now share it |

New in `src/parcel_robot/runtime.py`:

| Name | What it is |
| --- | --- |
| `RobotRuntime._place_admission(directive)` | assembles both vocabularies once and answers for **both** lanes |

New in `src/parcel_robot/agent.py`:

| Name | What it is |
| --- | --- |
| `VoiceAgent(place_admission=…)` | optional provider; `None` (the default) is the pre-R20 path exactly |
| `VoiceAgent._unknown_place_reply(directive)` | the ask, or `None` |

### 1.2 The rule, in one paragraph

A directive the destination grammar calls a directive, whose noun is not an
owner referent, whose verb is not the explicit-search verb, and whose noun
matches nothing in the resolution vocabulary ⇒ **refused, with up to three real
places named, nearest first**. Everything else is admitted exactly as before,
and the verdict says which of the five admission reasons applied.

### 1.3 Two vocabularies, deliberately not one

`_place_admission` reads two different lists because the question has two halves:

* **resolution set** — `_realtime_scene_vocabulary()`: live region/object labels
  **plus scene class names plus their ALIASES**. Aliases are load-bearing: "the
  pavement" and "street light" are groundable requests, and a gate built on
  class names alone calls them fiction (seed S6).
* **offer list** — `_realtime_places()`: R10's nearest-first instance list. This
  is what the refusal names. A refusal that offers a place the owner cannot see
  is worse than one that offers nothing.

Using R10's offer list for both roles was the first thing tried and it is the
over-correction the card warned about; the split is the fix, and S6 is the seed
that keeps it.

### 1.4 Three deliberate non-refusals, each with a reason

1. **Empty vocabulary ⇒ admit** (`no_vocabulary`). A robot whose map has not
   loaded knows no places at all; a gate that refused everything then would
   take the whole navigation surface down over a missing sidecar. R10's
   `_realtime_places` docstring made the same call for the same reason. Visible
   in the verdict rather than disguised as an admission. **This is a real hole
   and it is listed as an open risk, not sold as a feature** (§9).
2. **Owner referents ⇒ admit** (`owner_referent`). N12: the owner is a tracked
   entity on the owner channel and never a semantic-map label, so "go to me" is
   resolvable *because* it is absent from the place vocabulary. Refusing it here
   would break the approach lane over a list it was never meant to appear on.
3. **Strings the grammar already refuses ⇒ decline jurisdiction**
   (`not_a_navigation_directive`). "go to here" / "go to forward" are excluded
   destinations the router refuses by rule name. "I don't know a place called
   'here'" is a worse sentence, and two layers refusing one string for two
   different reasons is how a refusal stops meaning anything. This was found by
   the suite, not by inspection: the first implementation swallowed
   `test_navigate_to_refuses_what_the_router_does_not_call_a_navigation[here]`.

### 1.5 The boundary the card asked to be documented

**This is a gate on goal admission, not a ban on exploration.**

| Phrasing | Lane | Outcome |
| --- | --- | --- |
| "go to a mailbox" / "take me to a mailbox" | either | refused, alternatives named |
| "look for a mailbox" / "find a mailbox" / "search for a mailbox" / "locate a mailbox" | typed / local | **admitted, scans** — the owner asked the robot to look |
| any explicit-search phrasing | **hosted** | **not expressible at all** — see §9 open risk 2 |

The boundary is `_EXPLICIT_SEARCH_PATTERN`, which is *the same regex object*
that sits in `_DESTINATION_PATTERNS`. Widening the locate-and-approach grammar
widens the exploration boundary in the same commit; it cannot be edited in one
place and forgotten in the other. Pinned by
`test_the_search_boundary_is_the_grammars_own_pattern` and seeded by S12.

### 1.6 Two renderings of one verdict

`.fact()` is third person, for the hosted `detail` field the model reads and
paraphrases; `.reply()` is first person, for the typed panel that speaks as
itself. This is R15's `admitted` / `detail` split applied to a refusal: a
first-person sentence handed to the model gets re-voiced as something the robot
*decided*, and the whole point is that it is something the robot's *map* says.
`.fact()` is checked against R15's own executable predicate —
`detail_tense_violation(result["detail"]) == ""` — in
`test_the_hosted_tool_rejects_narnia_and_hands_the_model_real_alternatives`.

---

## §2 — Derived constants, with provenance

Two numbers and one list. None of them was tuned against a gate.

| Constant | Value | Where it comes from |
| --- | --- | --- |
| `PLACE_OFFER_LIMIT` | 3 | the card's own example sentence — *"nearest I know are the coffee shop and the bench"* — is two; three is the most a **spoken** refusal carries before it becomes a list the owner stops listening to. live_run_1's own methodology finding is that the owner reads at one query every 4–6 s; a longer offer would be talked over. Not fitted to anything. |
| resolution match | whole phrase · head noun · either string containing the other as a whole-word phrase | derived from the two live examples that must not break: `coffee shop` ⊂ `coffee shop at 42nd street` (the run's route=31 goal) and `bench` ⊂ `the big oak bench` (R10's own multi-word-place test). |
| explicit-search verbs | `find` `locate` `look for` `search for` | **not authored here.** They are `_EXPLICIT_SEARCH_PATTERN`, which already existed in the grammar as the locate-and-approach destination pattern. R20 named it and reused the object. |

The asymmetry that sets the matching policy is stated once and is the reason
the match is permissive: admitting a place the grounder then cannot find costs
the owner one honest *"I couldn't find or safely reach it"* — behaviour that
already existed and that live_run_1 shows working. Refusing a place the robot
can actually reach costs them the robot.

---

## §3 — OWNS compliance

**Card OWNS:** the admission-path fork (navigation/goals or router glue — map
exact files in the doc first), `runtime.py` glue, tests, `R20_STATUS.md`.
**MUST NOT TOUCH:** lane / broker / protocol / ingress, prompting, yield,
arrival semantics table (R10's classes stand).

| File | +/− | In OWNS? |
| --- | --- | --- |
| `src/parcel_robot/navigation/goals.py` | +245 / −16 | yes — "navigation/goals", named in the card |
| `src/parcel_robot/runtime.py` | +58 / −1 | yes — "`runtime.py` glue" |
| `src/parcel_robot/agent.py` | +56 / −1 | **scope extension, argued below** |
| `tests/test_unknown_place_admission.py` | new (untracked), 604 lines, 54 tests | yes — tests |
| `tests/test_realtime_tool_broker.py` | +35 / −13 | yes — tests |
| `tests/test_voice_nav_e2e.py` | +48 / −55 | yes — tests (the §6 boundary pair) |
| `scrum/20260820/task_9/R20_STATUS.md` | new (untracked) | yes |

`git diff --numstat` over the whole tree returns exactly these five tracked
files. Nothing was committed, staged or stashed.

**Untouched, verified by `git diff --numstat`:** `realtime/lane.py`,
`realtime/tool_broker.py`, `realtime/protocol.py`, `realtime/ingress.py`,
`realtime/prompting.py`, `navigation/arrival_semantics.py`,
`navigation/yield_aside.py`, every config and every eval artifact. R10's
arrival-semantics classes and `validate_place` are byte-identical.

### The `agent.py` extension, and why it is not optional

`agent.py` is where the typed lane admits a navigation goal
(`_parse_navigate` → `sketch_navigate` → `_admit_local_sketch`), so it is the
panel half of "the admission-path fork" the card told me to map. Three
independent reasons it had to be in scope:

1. **The card's own DoD requires it.** "known place refused — the
   over-correction" and the parity seeds cannot be satisfied by a hosted-only
   gate.
2. **R10's parity invariant forbids the alternative.** Gating only the hosted
   lane is precisely "the hosted lane growing its own private grammar", which
   `test_navigate_to_grants_exactly_what_a_typed_sentence_grants` exists to
   forbid. Fixing one lane would have broken a live invariant to fix a defect.
3. **The whisperer ack (§0.3) is reached from both lanes.** A typed "go to
   narnia" produces the same *"Okay—I'll go wait near narnia safely."* the
   bench_eval note flagged. Half a fix leaves half the defect.

The extension is 56 lines: one optional keyword argument, one attribute, one
helper, and two call sites. Its default (`place_admission=None`) is the
pre-R20 behaviour exactly, pinned by
`test_an_agent_with_no_place_provider_is_unchanged`, so every `VoiceAgent`
constructed without a runtime — which is most of the suite — is untouched.

---

## §4 — The corpus rows, before and after

Card item 3. `tests/test_unknown_place_admission.py` reads
`evals/20260820/voice_corpus_v1/queries.tsv` directly — the rows are not
retyped — and runs them against a **fake resolver** (`KNOWN` / `OFFER`) shaped
after the vocabulary the live run was actually holding: the city sidecar's
classes and aliases plus the two named instances its mission log resolved routes
to (`coffee shop at 42nd street` route=31, `crosswalk` route=3).

| id | Query | live_run_1 | now, offline |
| --- | --- | --- | --- |
| 10 | "Go to Narnia." | **FAIL** — ack + 4.25 s rotate-scan | refused, `unknown_place`, three real places named |
| 11 | "Go to my office." | NOT ATTEMPTED (the run's "most costly miss") | refused, `unknown_place` |
| 12 | "Take me to the moon." | **FAIL** — ack + 10.7 s rotate-scan | refused, `unknown_place` |
| 13 | "Let's go back home." | PASS (model-authored ask) | still not a directive at all — and `go to home`, if a tool call ever renders it, is refused |
| 06 | "…somewhere I can get food." | PARTIAL — `go to restaurant`, same rotate-scan | refused, and the refusal names the coffee shop |
| 01–05, 08, 09 | the mapped places | PARTIAL/PASS | **all still admitted** — the over-correction guard |

## §5 — What the tests pin

`tests/test_unknown_place_admission.py`, 54 tests in six sections:

1. **the corpus rows that failed** — 10/11/12 refused with real alternatives;
   q13's real reason; q06 as the same defect in a plausible noun.
2. **the over-correction, guarded** — every mapped corpus place still admits, in
   both the panel's phrasing and the tool's `go to <place>` rendering; aliases;
   phrase-containment in both directions; owner referents; empty vocabulary;
   negation; and the jurisdiction the gate declines.
3. **exploration is not banned** — four explicit-search phrasings still search,
   the goal phrasing of the same noun is still refused, and the boundary is
   asserted to BE `_DESTINATION_PATTERNS`' own object.
4. **no drift** — ten directives where the gate's noun must equal
   `semantic_goal_from_directive(...).query`.
5. **the two lanes** — hosted rejection (tensed, R15-clean, alternatives in the
   `detail` the model reads); no mission, no plan, no router call, no ack; a
   real place still admits; an alias still admits.
6. **the typed lane and parity** — the panel refuses what the tool refuses, the
   ask names real places and is not an acknowledgement, a mid-mission retarget
   gets the same ask, and an agent with no provider is byte-for-byte the old
   path.

Rewritten in `tests/test_realtime_tool_broker.py`: R10's two parity tests (§10
deviation 2). Rewritten in `tests/test_voice_nav_e2e.py`: the fountain pair
(§6).

**One offline cross-check worth recording, because it is what made the slow-suite
risk small before it was measured.** Every navigation directive any nav-e2e case
issues was extracted from the test file and run through the policy against the
REAL city vocabulary (`scene_semantics().detector_query_set()`), not the fake
resolver:

```
'can you walk towards the lamppost'   known_place
'come here'                           not_a_navigation_directive
'find the fountain'                   explicit_search
'find the nearest lamppost'           explicit_search
'go to the lamppost'                  known_place
'go to the owner'                     owner_referent
'go to the sidewalk'                  known_place
'head towards the lamppost'           known_place
'please move onto the sidewalk'       known_place
'run to the nearest lamppost'         known_place
'sit next to the bench'               known_place
'sit next to the lamppost'            known_place
"don't go to the sidewalk"            not_a_navigation_directive
'stay'                                not_a_navigation_directive
'go to the fountain'                  unknown_place   <-- the one intended change
```

Exactly one directive in the entire live nav-e2e surface changes verdict, and it
is the one §6 is about.

---

## §6 — The nightly test the commit gate could not see

**The most important thing this card found about its own blast radius, and the
commit gate did not report it.**

An exhaustive `pytest tests/` (all 7038 tests, including the 42 marked `slow`
that the commit tier deselects) showed one failure the gate is structurally
blind to:

```
tests/test_voice_nav_e2e.py::test_go_to_the_fountain_searches_then_reports_honestly
```

There is no fountain in the city, and that test asserted — in a docstring that
argued the point explicitly — that "go to the fountain" is **admitted**, runs a
bounded search, and fails honestly:

> "Admission still succeeds by design — NavigateTo deliberately does not require
> `target_grounded`, because **refusing every unknown label would make the robot
> unable to go looking for anything**."

That is the strongest form of the objection to this card, written down a sprint
early, by someone who had thought about it. It deserves an answer rather than a
deleted assertion, and R20's answer is the test that sits immediately below it:
**`test_paraphrase_find_the_fountain_still_reports_honestly` is unchanged and
still passes.** The robot can still go looking for anything. What changed is
that it will not *commit to a destination* it cannot resolve — which is exactly
the difference between "find the fountain" and "go to the fountain", and exactly
the difference live_run_1 measured the cost of when the noun was "narnia".

So the pair was rewritten as a pair:

| Test | Before | After |
| --- | --- | --- |
| `test_go_to_the_fountain_is_asked_about_rather_than_searched_for` (renamed from `…_searches_then_reports_honestly`) | admitted → bounded search → `semantic_target_not_found` | **the ask**, naming real places; no plan, no task, no mission, no rotate-scan |
| `test_paraphrase_find_the_fountain_still_reports_honestly` | search → honest not-found | **unchanged**, and its docstring now says why it is load-bearing: if it ever has to be weakened, the gate has become a ban on exploration |

**Register point worth carrying forward:** a card that changes an admission
contract cannot be scored by the commit tier alone. The 42 `slow` tests contain
the entire live nav-e2e surface, and it is exactly where an admission change
lands. Running `pytest tests/` unfiltered — not just the gate — belongs in the
standard for any card touching admission.

### 6.1 The full `slow` sweep, and two failures that are NOT this card

```
2 failed, 20 passed, 18 skipped, 6996 deselected, 2 xfailed, 3 warnings in 704.32s
FAILED tests/test_runtime_activation.py::test_camera_ingress_live_owlv2_localizes_object
FAILED tests/test_voice_nav_e2e.py::test_go_to_the_lamppost_grounds_plans_and_arrives
```

Both were attributed rather than waved away.

**1. The camera test is environmental.** Its own exception says so:

```
RuntimeError: camera ingress requested but the OWLv2 detector is unavailable
(set PARCEL_OWLV2_ONNX=1 and run scripts/fetch_owlv2.sh)
```

No detector weights on this machine. Nothing to do with navigation.

**2. The lamppost test is RED ON `main` — and this is an inherited finding worth
its own line.** It fails with `semantic_arrival_verification_failed`, an
ARRIVAL failure: the goal was admitted, the mission ran, the route was planned,
and arrival verification failed at the end. R20 touches no part of the arrival
path (`navigation/arrival_semantics.py` is MUST-NOT-TOUCH and is byte-identical).

It was proved pre-existing rather than argued: `scratchpad/r20/
attribute_lamppost.py` snapshots the three R20 source files, swaps in their
**HEAD** contents, purges every `src/__pycache__`, verifies with a
**fresh-interpreter canary** that `admit_navigation_place` is genuinely absent
from the loaded module, runs the single test, and restores in a `finally` with a
sha256 byte-identity assert:

```
fresh-interpreter canary: R20-ABSENT
PRISTINE-TREE RESULT: 1 failed, 3 warnings in 59.46s
   E  AssertionError: the near-band arrival defect recurred: states=['failed']
      details=['semantic_arrival_verification_failed'] … 'goal': 'lamppost'
restore: all three source files byte-identical
```

Identical failure, identical reason, with R20 not in the interpreter. Nothing
was committed, staged or stashed to obtain this.

**The finding to hand on:** the test's own comment calls this
*"semantic_arrival_verification_failed 3/3 — the audit's #2 blocker"*, and it is
currently RED on the tree that the commit gate calls green. The near-band
arrival card that pinned it has regressed, and no commit-tier gate can see it.
That is a card, and it is not this one (§11 handoff 6).

---

## §7 — Gate

Opening gate on this tree, **before any edit** (the card's stated entering
baseline of 6732 is stale by three cards — see §10 deviation 5):

```
[  PASS] HARD  default-suite              6933 passed, 9 skipped, 42 deselected, 5 warnings in 268.58s (0:04:28)
RESULT: PASS — every hard gate green.
```

Closing gate — **run after the final edit** (the last change was the §6 boundary
pair in `tests/test_voice_nav_e2e.py`), read then pasted verbatim:

```
CI GATE — tier=commit  (2026-08-20T22:51:35Z)
==============================================================================
[  PASS] HARD  ruff                       7 violation(s), baseline 7, new 0
[  PASS] HARD  hard-safety                nav frozen baseline nav-instruct-v1-baseline-v4-20260811T070536Z: collisions=0 false_arrival=0 | mutation panel clean: collisions=0 no_false_arrival=True | mutation panel freshness: committed fields reproduce live = True | follow-bench: 7 row(s), hard_collision_total all 0 = True | walk_with_me: 1/2 row(s) with hard_collision_total, all 0 = True
[  PASS] HARD  frozen-digest-sentinels    4 immutable manifest(s) byte-identical to pin
[  PASS] HARD  release-parity             91 packaged asset(s) byte-identical to canonical source
[  PASS] HARD  latency-tail-ledger        latest row latency-20260810T082415Z-4d83035f: 6 metric series within 1.2x tail ceiling (rows=5, window=5)
[  PASS] HARD  follow-bench-jerk-ratchet  latest shipped row follow-bench-v1-20260811023618Z-93eba090.json: 1.2187 <= 1.46244 (baseline 1.2187 x 1.2)
[  PASS] HARD  model-off-non-inferiority  23 passed in 0.45s
[  PASS] HARD  frozen-digest-integrity    6 passed, 1 warning in 0.34s
[  PASS] HARD  release-parity-integrity   10 passed in 0.74s
[  PASS] HARD  mutation-panel-freshness   2 passed, 3 warnings in 4.25s
[  PASS] HARD  latency-tail               6 passed, 2 warnings in 0.31s
[  PASS] HARD  default-suite              6987 passed, 9 skipped, 42 deselected, 6 warnings in 269.89s (0:04:29)
==============================================================================
RESULT: PASS — every hard gate green.
  elapsed 282.7s
```

An earlier gate, before the fountain pair was rewritten, was identical in every
row (`6987 passed`, `ruff new 0`) — kept here because it is the run the seed
sweep and the live proof were taken against:

```
CI GATE — tier=commit  (2026-08-20T22:25:44Z)
==============================================================================
[  PASS] HARD  ruff                       7 violation(s), baseline 7, new 0
[  PASS] HARD  hard-safety                nav frozen baseline nav-instruct-v1-baseline-v4-20260811T070536Z: collisions=0 false_arrival=0 | mutation panel clean: collisions=0 no_false_arrival=True | mutation panel freshness: committed fields reproduce live = True | follow-bench: 7 row(s), hard_collision_total all 0 = True | walk_with_me: 1/2 row(s) with hard_collision_total, all 0 = True
[  PASS] HARD  frozen-digest-sentinels    4 immutable manifest(s) byte-identical to pin
[  PASS] HARD  release-parity             91 packaged asset(s) byte-identical to canonical source
[  PASS] HARD  latency-tail-ledger        latest row latency-20260810T082415Z-4d83035f: 6 metric series within 1.2x tail ceiling (rows=5, window=5)
[  PASS] HARD  follow-bench-jerk-ratchet  latest shipped row follow-bench-v1-20260811023618Z-93eba090.json: 1.2187 <= 1.46244 (baseline 1.2187 x 1.2)
[  PASS] HARD  model-off-non-inferiority  23 passed in 0.46s
[  PASS] HARD  frozen-digest-integrity    6 passed, 1 warning in 0.33s
[  PASS] HARD  release-parity-integrity   10 passed in 0.74s
[  PASS] HARD  mutation-panel-freshness   2 passed, 3 warnings in 4.30s
[  PASS] HARD  latency-tail               6 passed, 2 warnings in 0.31s
[  PASS] HARD  default-suite              6987 passed, 9 skipped, 42 deselected, 5 warnings in 269.48s (0:04:29)
==============================================================================
RESULT: PASS — every hard gate green.
  elapsed 282.2s
```

**6933 → 6987 = +54, exactly the new file's 54 tests. 0 removed.** `ruff new 0`.
The frozen nav baseline, the digest sentinels and release parity are unmoved —
this card wrote no config, no asset and no eval artifact.

Beyond the gate, because the gate cannot see it (§6): the 42 `slow` tests were
run separately — see the slow-suite result recorded in §6/§8.

---

## §7.5 — Live proof

`scratchpad/r20/live_r20.py`. ONE process, ONE monotonic clock, everything real:
the MuJoCo city **with pedestrians running** (as live_run_1 had), the real
`RobotRuntime`, the real deterministic router, the real `RealtimeToolBroker`, and
the real hosted provider `gpt-realtime-2.1-mini` on a live WebSocket. Nothing is
stubbed. The owner's stack was not running on :8765 (checked read-only, socket
refused); this ran on its own stack, its own scratch lane config, and a
`mode=ro` sqlite copy of the owner store. **`~/.config/parcel/realtime.yaml` was
neither read nor written; the owner DB sha256 is identical before and after in
both sessions.**

The scorer is independent of the fix: it reads the runtime's own `mission_log()`
and the broker's `calls`, and asks *"does a mission for this noun exist?"* — not
*"did the gate say it refused one?"*

### Session A — the two fabricated missions, re-asked (`r20_live_A_20260820T224508Z.json`)

Offer list the runtime actually held: `crosswalk, planter, tree, building, bench, door`.

**q10 "Go to Narnia."**

```
22:45:xx  robot: "Got it, I'll try to handle the request to reach Narnia."
22:45:xx  robot: "It didn't start, because there's no place called Narnia on the
                  map—only nearby spots like the crosswalk, planter, and tree."
broker:   navigate_to -> rejected
          "not started: the robot's map has no place called 'narnia'; the places
           it does know nearby are the crosswalk, the planter and the tree; ask
           the owner which of those they mean, or which real place they want"
mission_log for 'narnia': []        fabricated_mission: false   rotate_scan: false
ack_template_spoken: false          verdict: PASS
```

**q12 "Take me to the moon."**

```
22:45:xx  robot: "It didn't start, because the map doesn't have a place called
                  "moon." It only knows nearby spots like the crosswalk, the
                  planter, and the tree."
broker:   navigate_to -> rejected      mission_log for 'moon': []
ack_template_spoken: false             verdict: PASS
```

Compare live_run_1, 4.25 s and 10.7 s of rotate-scan behind *"Okay—I'll go wait
near narnia safely."* The model **narrated the fact it was given**, including
the alternatives — which is R4-lite's Defect C mechanism working in the
direction it was built for.

### Session A, local lane — the boundary, live

```
"look for a mailbox"  -> "Okay—I'll go wait near mailbox safely."     (admitted: it looks)
"go to narnia"        -> "I don't know a place called "narnia" — the ones I do
                          know nearby are the crosswalk, the planter and the
                          tree. Which would you like?"                (the ask)
"go to the bench"     -> "Okay—I'll go wait near bench safely."       (admitted)
```

Same unmapped-noun class, two phrasings, two different and correct outcomes.

### Session B — a real place still admits and still runs (`r20_live_B_20260820T224608Z.json`)

```
22:46:xx  robot: "A-a-I started walking toward the bench, but it hasn't finished yet."
broker:   navigate_to -> ok   "started: the robot is walking to bench"
mission:  started goal=bench ... then
          blocked "Waiting: someone is in the way near bench."
          reason=grid_track err=-0.3 goal=0.9 route=2 status=planned|person_stop
verdict:  PASS
```

A real route (`route=2`), a real person-block, narrated. The over-correction did
not happen.

**Cost: $0.0502 + $0.0351 = $0.0853**, against the ≤$1.50 card budget.

### Two honest notes about this proof

1. **The scorer's `fabricated_mission` field is a misnomer in session B.** It
   means "a mission for this noun exists", which is the *expected* result there;
   the `verdict` compares it against `expect_mission`. Reading the raw JSON
   without that context would mislead.
2. **`reason=scan_behavior_rotate` is NOT a reliable resolved/unresolved
   discriminator.** live_run_1 §d suggested it was. Session B's *bench* mission —
   a real, resolvable place that then planned `route=2` — also opens with
   `state=searching reason=scan_behavior_rotate`. This is direct evidence for
   §0.35's decision not to gate on that signal, and it is a small correction to
   the run's own reading of its data.

---

## §8 — Seeds

Harness: `scratchpad/r20/seed_r20.py`, R9 session-B standard **plus**
`AUDIT_R12_R16_FABLE.md` §register 1 — every seed purges every `src`
`__pycache__` after the mutation *and* after the restore, and a **fresh
interpreter** is asked what the module's source actually says before the target
runs. A seed whose canary does not fire is reported UNANCHORED, never passed off
as RED. All 15 anchors were verified present-and-unique before the sweep.

Fifteen seeds across the three touched source files, covering all four defect
classes the card's DoD names, plus three the work itself exposed. **15/15 RED,
every restore byte-identical, whole-tree repair check 3/3.**

Startup snapshot (`scratchpad/r20/seeds_1.txt`):

```
src/parcel_robot/navigation/goals.py  1323aeded5d5291e
src/parcel_robot/runtime.py           bf0341d31d31e05c
src/parcel_robot/agent.py             619917e066926aed
```

| # | File | Seeded defect | DoD class | Result | First failing test |
| --- | --- | --- | --- | --- | --- |
| S1 | goals | the unknown-place verdict admits again — narnia is a goal once more | *unknown place scans again* | **RED** | `test_the_nav_invalid_corpus_rows_are_refused_with_real_alternatives[10-narnia]` (+2) |
| S2 | runtime | the hosted gate is bypassed: live_run_1 q10 runs as a mission again | *unknown place scans again* | **RED** | `test_the_hosted_tool_rejects_narnia_and_hands_the_model_real_alternatives` |
| S3 | agent | the typed gate is bypassed: the panel fabricates while the tool refuses | *parity* | **RED** | `test_the_typed_panel_refuses_exactly_what_the_hosted_tool_refuses` |
| S4 | runtime | the vocabulary the gate judges against is thrown away (fail-open forever) | *unknown place scans again* + **the ack** | **RED** | `test_the_refused_goal_never_becomes_a_mission_or_an_ack` |
| S5 | goals | phrase matching dropped: "the coffee shop", "the big oak bench" refused | *known place refused* | **RED** | `test_a_place_matches_by_phrase_in_either_direction[…]` (2 of 4) |
| S6 | runtime | the resolution set loses class ALIASES: "the pavement" becomes fiction | *known place refused* | **RED** | `test_an_alias_still_admits_through_the_hosted_tool` |
| S7 | goals | the owner stops being an owner referent and is refused as a place (N12) | *known place refused* | **RED** | `test_the_owner_is_not_a_place_and_is_never_refused_as_one` |
| S8 | goals | fail-open removed: a robot whose map has not loaded refuses everything | *known place refused* | **RED** | `test_an_empty_vocabulary_admits_everything_and_says_which` |
| S9 | goals | the refusal stops naming real places — a structured refusal becomes a bare no | *alternatives dropped* | **RED** | `test_the_refusal_offers_places_the_robot_can_actually_reach` |
| S10 | goals | the offer list is unbounded: the spoken refusal becomes a catalogue | *alternatives dropped* | **RED** | `test_the_refusal_offers_places_the_robot_can_actually_reach` |
| S11 | goals | explicit search blocked: "look for a mailbox" becomes a refusal | *explicit-search blocked* | **RED** | `test_an_explicit_search_still_searches_for_something_unmapped[…]` (4 of 4) |
| S12 | goals | the search boundary stops being the grammar's own pattern (two regexes drift) | *explicit-search blocked* | **RED** | `test_the_search_boundary_is_the_grammars_own_pattern` |
| S13 | goals | the gate swallows the router's own refusals ("go to here" gets a place answer) | jurisdiction | **RED** | `test_navigate_to_refuses_what_the_router_does_not_call_a_navigation[here]` (+`[forward]`) |
| S14 | goals | the gate reads a different noun than the compiler will search for | drift | **RED** | `test_the_gate_and_the_compiler_read_the_same_noun[…]` (10 of 10) |
| S15 | agent | a mid-mission retarget to an unmapped place skips the ask and stalls instead | *parity* | **RED** | `test_a_goal_amendment_to_an_unmapped_place_is_asked_about_too` |

### S12 came back GREEN the first time, and the reason is worth keeping

S12's first mutation replaced `_EXPLICIT_SEARCH_PATTERN` inside
`_DESTINATION_PATTERNS` with a `re.compile()` of the **identical** source — and
the seed was GREEN. That is correct behaviour, not a weak test: `re.compile`
caches, so an identical source returns the *identical object*, and there is no
drift to detect. The defect the test exists for is the two regexes DIVERGING, so
the seed was rewritten to diverge them (`locate` dropped from the copy while the
exported constant keeps it) — the exact shape a future widening would take — and
it is RED. Reported here rather than quietly re-run, because "a seed that did not
fire" and "a seed that fired and the test caught nothing" look identical in a
table and are completely different facts.

The corrected S12 was re-run solo against the same tree; the other fourteen are
from the single sweep in `seeds_1.txt`.

**Post-sweep drift check.** After the sweep, after the corrected S12, and after
the pristine-HEAD attribution experiment of §6.1, the three source files still
hash to the sweep's startup snapshot:

```
src/parcel_robot/navigation/goals.py  1323aeded5d5291e
src/parcel_robot/runtime.py           bf0341d31d31e05c
src/parcel_robot/agent.py             619917e066926aed
```

This is the tree the closing gate scored and the tree the live proof ran on.

---

## §9 — does_not_prove, and open risks

### What this card does NOT prove

1. **It does not prove the robot knows what a place IS.** The gate asks whether
   any label in the current vocabulary could match a noun. It has no model of
   fiction, geography or scale: "narnia" and "moon" are refused for exactly the
   same reason a real-but-unmapped café down the street would be refused —
   *this map does not have it*. That is the honest claim and it is the one the
   refusal sentence makes.
2. **It does not close q06's class in the sense the eval note wanted.**
   "restaurant" now gets an ask that names the coffee shop, which is better than
   a rotate-scan; it is not the food-class *reasoning* the run's note wished for
   ("the robot had a real, resolved food place in hand"). That would be a
   semantic-class card, not this one.
3. **It does not prove anything about a place the robot cannot currently see
   but could find.** A class in the scene vocabulary is admitted whether or not
   an instance is visible, deliberately (R10's rule: "a place the robot knows
   how to look for but cannot see yet is admitted and then fails honestly at
   grounding"). This card did not re-litigate that.
4. **The place graph and taught names are NOT part of the vocabulary.** The card
   named three sources — semantic map, place graph, taught name. Only the
   semantic map is reachable: `route_memory/place_graph.py` and
   `route_memory/teach_repeat.py` are not wired into `runtime.py` at all
   (`grep -n "route_memory" src/parcel_robot/runtime.py` returns nothing). So a
   taught route name would be refused today. The vocabulary assembly is one
   method (`_place_admission`) precisely so a fourth source is one line when
   teaching is wired; it is not wired now, and this doc does not pretend it is.
5. **live_run_1's rows are re-run offline against a FAKE resolver, not
   re-spoken.** The corpus rows are pinned as a regression suite (card item 3);
   the spoken-audio half of live_run_1 cannot be re-run because the run's audio
   was never persisted (that run's own §fixture-value finding).

### Open risks

1. **Fail-open on an empty vocabulary re-opens the whole defect.** If
   `_realtime_scene_vocabulary()` returns nothing — a scene with no sidecar, a
   loader failure, a backend that never observed — every place is admitted and
   narnia becomes a mission again. This is deliberate (§1.4) and it is the one
   place a future card could reasonably disagree. The verdict reason
   (`no_vocabulary`) is the flag to alarm on.
2. **The hosted lane has no way to ask for a search.** `navigate_to` renders
   only `go to <place>` (`NAVIGATE_DIRECTIVE_TEMPLATE`), so a spoken "look for a
   mailbox" reaches the runtime as a GOAL and is now refused. Before this card
   it became a rotate-scan the owner never asked for, so the refusal is an
   improvement, but the capability is genuinely absent on that lane: exploration
   survives only where it can be phrased, which is the typed/local lane. The fix
   is a `search_for` tool on the broker — **explicitly MUST-NOT-TOUCH for this
   card**, so it is handed off (§handoffs) rather than smuggled in.
3. **The refusal's machine-readable half is thinner on this path.** R10's
   junk-place refusal carries `valid_places` and `reason` keys in the tool
   result; R20's refusal arrives as a `ValueError` through the navigate door, so
   it carries the alternatives *in the sentence* and not as a field. A
   transcript auditor can read it; a program has to parse prose. Adding the keys
   means editing `tool_broker.py`. Handed off.
4. **Multi-word over-admission.** Because the match is permissive in both
   directions, "go to narnia near the bench" contains a mapped noun and is
   admitted. The compiler will search for the literal phrase and fail honestly,
   which is the pre-R20 outcome for that string; no regression, but not a win
   either.
5. **`_realtime_places()` is called on every refusal.** It walks the current
   observation's regions and objects. It is already called per `navigate_to` for
   R10's junk gate, so the cost is unchanged in the common case, but the typed
   lane now calls it too.

---

## §10 — Deviations, with reasons

1. **`agent.py` was edited although the card's OWNS list names only
   navigation/goals, runtime glue and tests.** Argued at length in §3: the card
   told me to map the fork's exact files first, and the typed panel is half of
   it. Gating one lane would have broken R10's parity invariant to fix R10's
   permissiveness. 56 lines, default-off shape.
2. **Two existing tests were rewritten rather than left green.**
   `test_navigate_to_grants_exactly_what_a_typed_sentence_grants` asserted
   `STATUS_OK` for narnia; it now asserts that BOTH lanes refuse, which is the
   same rule (parity) with the outcome the card asked for. The docstring of
   `test_an_unheard_of_but_well_formed_place_keeps_authority_parity` was
   corrected — its assertions are unchanged, because they pin the half R20
   deliberately did not touch (the broker still has no place grammar).
3. **The card's suggested root cause was not the one found.** "Likely the
   known-place list vs open semantic search" — the actual fork is that "home"
   never became a directive at all (§0.2). The policy the card asked for is
   implemented as written; the *narrative* in the card's trigger note is
   corrected here rather than repeated.
4. **The card says "narrated"; on the hosted lane that is the model reading
   `detail`.** No new narration channel was added, and the whisperer/lane path
   was not touched (MUST NOT TOUCH). `.fact()` is delivered through the existing
   R4-lite mechanism — the fact the model reads and paraphrases — and the live
   proof is what shows it actually gets spoken.
5. **The baseline test count in the card (6732) is stale.** My own opening gate
   on this tree measured **6933 passed** before any edit (R17–R19 landed in
   between). Recorded rather than silently reconciled.
6. **The corpus rows are re-run offline, not re-spoken.** Card item 3 asks for
   exactly that; item 4's live proof is a separate hosted session (§7.5).

---

## §11 — Handoffs

1. **`search_for` on the broker.** The hosted lane cannot express exploration
   (§9 open risk 2). A read-only-ish `search_for(thing)` tool routed through the
   same locate-and-approach grammar would restore it, and would let the model
   answer "look for a mailbox" with a search instead of an ask. Broker file —
   needs its own card.
2. **`valid_places` / `reason` keys on the R20 refusal** (§9 open risk 3), same
   file, same card.
3. **Taught names and the place graph** (§9 does_not_prove 4). When
   `route_memory` is wired into the runtime, its named routes join the
   resolution set in `_place_admission`; one line, one seed.
4. **The eval corpus rows 10–12 should flip from expected-FAIL to expected-PASS
   in the next live run's scoring**, and q11 ("Go to my office.") should be
   spoken this time — the scoring called it the most costly miss of the block.
5. **`no_vocabulary` deserves an alarm.** It is the one verdict that means the
   gate is not protecting anything (§9 open risk 1) and nothing currently
   watches for it.
6. **`test_go_to_the_lamppost_grounds_plans_and_arrives` is RED on `main`**
   (§6.1), proved pre-existing against pristine HEAD sources. Its own comment
   calls the failure *"the audit's #2 blocker"*. Someone owns that; this card
   does not, and it must not be discovered a third time.
7. **`mission_log.reason` is not the resolved/unresolved signal live_run_1 §d
   took it for** (§7.5 note 2). Any future card planning to key on
   `scan_behavior_rotate` should read that note first.
6. **Register addition proposed:** any card that changes an *admission* contract
   must run `pytest tests/` unfiltered, not only `--tier commit`. §6 is the
   worked example — the commit tier deselects the 42 `slow` tests, and those are
   the entire live nav-e2e surface.

---

## §12 — Restart required

`navigation/goals.py`, `runtime.py` and `agent.py` are not hot-reloadable. The
owner's stack must be relaunched to pick up the ask:

```
./scripts/launch_stack.sh
```

No config change is needed; the behaviour is on by default (there is no flag —
this is a correction to an admission rule, and a flag would mean shipping a
robot that fabricates missions when the flag is off).

**Owner-visible outcome after that restart:** "Go to Narnia", "Take me to the
moon", "Go to my office" and "Go to the restaurant" get *"I don't know a place
called … — the ones I do know nearby are the bench, the crosswalk and the
sidewalk. Which would you like?"* instead of a confident acknowledgement and a
few seconds of turning on the spot. Real places behave exactly as before, and
"look for a mailbox" still makes the robot look.

---

## §13 — Evidence artifacts (scratchpad, outside the repo)

`…/799cb356-4cb4-445b-a784-306b6c6fd4a6/scratchpad/r20/`

| File | What |
| --- | --- |
| `seed_r20.py` | the 15-seed harness (snapshot → mutate one source file → purge `__pycache__` → fresh-interpreter canary → named pytest target → restore → purge → byte-identity assert) |
| `seeds_1.txt` | the seed sweep against the tree the closing gate scored |
| `gate_baseline.txt` (in `scratchpad/`) / `r20/gate_1.txt` | the opening and closing gates |
| `slow_suite.txt` | the 42 nightly `slow` tests, which the commit tier deselects (§6) |
| `fountain.txt` | the rewritten boundary pair, run on its own |
| `live_r20.py` | the live harness (in-process runtime, MuJoCo city with pedestrians, real hosted provider, independent mission-log scorer) |
| `live_A.txt` / `live_B.txt` | the two live session transcripts as they streamed |
| `r20_live_A_20260820T224508Z.json` / `r20_live_B_20260820T224608Z.json` | machine-readable session reports: turns, verdicts, mission log, broker calls, lane snapshot, owner-DB sha256 before/after, spend |
| `attribute_lamppost.py` | the pristine-HEAD attribution experiment of §6.1 (swap → canary → run → restore → byte-identity assert) |
| `lamppost_solo.txt` | the same test run solo on the R20 tree, to rule out CPU contention before attributing it |
| `amend_probe.py` | the goal-amend probe that established the retarget arm was reachable before a test was written for it |

---

## §14 — Card DoD, line by line

| DoD item | Status |
| --- | --- |
| gate green | **yes** — §7, closing gate after the final edit, 6987 passed, ruff new 0 |
| ≥6 seeds RED | **15/15 RED**, §8, all four named classes covered plus three more |
| …unknown place scans again | S1, S2, S4 |
| …known place refused (the over-correction) | S5, S6, S7, S8 |
| …alternatives dropped | S9, S10 |
| …explicit-search phrasing blocked | S11, S12 |
| live proof | **yes** — §7.5, two hosted sessions, $0.0853, owner DB untouched |
| …Narnia refused with alternatives | session A, narrated by the model with the real offer list |
| …a real place still admits | session B, `route=2`, person-block narrated |
| …an explicit search phrasing still searches | session A local lane, "look for a mailbox" admitted |
| corpus queries 10–12 flip to expected-PASS, offline, fake resolver | §4, §5 — `tests/test_unknown_place_admission.py` reads `queries.tsv` directly |
| document the exploration boundary | §1.5, and pinned twice (unit + the nav-e2e pair, §6) |
| map the exact files before editing | §0.2, written before the first edit |
| standard register | §0–§14; deviations §10, does_not_prove and open risks §9, handoffs §11 |
