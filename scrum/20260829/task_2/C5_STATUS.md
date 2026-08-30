# C5 · SPEECH-ACTS-1 — STATUS (executor: Opus)

Card: `C5_SPEECH_ACTS.md` · Board: `README.md` (task_2, 2026-08-29) · Wave **A**
(leaf modules + tests). The `realtime/lane.py` / `runtime.py` install is **wave B
and is NOT written on this card**; §6 names the exact install point.

## 0. Pre-flight (before any edit)

| fact | value |
|---|---|
| HEAD | `704ba5c` |
| `src/parcel_robot/realtime/lane.py` | clean at HEAD (`git status --porcelain` empty) |
| `src/parcel_robot/realtime/config.py` | clean at HEAD |
| MB-1 pins re-verified | `events.py` / `narrate.py` / `scorer.py` / `steer.py` all match `model-b-contract-2/mb1_pins.sha256` |
| MB-2 pins re-verified | `contract.py` / `arms.py` / `mb1.py` / `run.py` all match |
| arm T re-run with the RESEARCH code | grounding 1.0, coverage 0.9688, invented 0, 180 robot turns, claims/turn 1.444, zero-claim 5 — identical to `results.json` `arm_T` |

### 0.1 The off-path digest, computed BEFORE any edit

`narrate_event`'s output over MB-1's corpus, flag OFF, measured against the
**unedited** `lane.py`/`config.py` at `704ba5c`:

```
off-path digest (pre-edit)   edaa32ed66fca69be4fce66afb5e2a04f0c55487f3c357f41ffcd1ba698dcecb
arm-T narration text digest  7e54e3c742bc576935d928dcadab92a15b9f9eece6105bf84395ac9b4891ba8a
```

The digest covers, for each of arm T's 180 robot turns in corpus order: a FRESH
flag-OFF lane over the scripted fake server, `narrate_event(text)`'s return, the
`role`/`text` of every `conversation.item.create` frame that left the process,
the frame-type sequence, and `narrations` / `narrations_skipped`. A fresh lane
per turn because `narrate_event` refuses while a response is outstanding — one
lane would have narrated once and skipped 179 times, which is not a digest of
anything.

The 180 texts for the pre-edit measurement came from the RESEARCH contract
(`contract.py` + `arms.py`); the test regenerates them from the PRODUCT modules,
so a one-character drift in the port moves the digest and reddens the row.

## 1. What landed (wave A only)

| file | state | lines |
|---|---|---|
| `src/parcel_robot/realtime/speech_acts.py` | NEW — 9 acts + `ask_clarify`, slots, one template each, `check` | 705 |
| `src/parcel_robot/realtime/narration_matcher.py` | NEW — MB-1's scorer ported (claims, support, invented actions, `INABILITY`/`OFFER`/`HEDGES`, `normalise`) | 687 |
| `src/parcel_robot/realtime/config.py` | `speech_acts:` block, `SpeechActsConfig`, `speech_acts_config_from_mapping`, one `ALLOWED_KEYS` entry (additive, default OFF) | +85 / -0 |
| `tests/test_speech_acts.py` | NEW — 16 tests | 425 |
| `tests/test_narration_matcher.py` | NEW — 9 tests | 543 |

Nothing else is touched. `lane.py`, `runtime.py`, `whisperer.py`, `config.py`
(the 1000-line one, unchanged at exactly 1000), every safety floor, every
owner-diff file and every research folder are untouched — `git status` shows
only the five paths above.

Both new modules are under the DEC-0 1000-line ceiling (687 / 705) and add no
function over 100 lines; they are above M6's ≤ 600 target, which is docstring
and verbatim-regex bulk from the port — recorded here rather than hidden.

## 2. Acceptance rows

### Row 1 — the arm-T reproduction through the PRODUCT modules

> "the arm-T reproduction row in the test equals MB-2's `results.json` `arm_T`
> (grounding 1.0, coverage 0.9688, invented 0, 180 turns)."

`tests/test_narration_matcher.py::test_mb2_arm_t_reproduces_through_the_product_modules`

| row | `results.json` `arm_T` | measured through `speech_acts` + `narration_matcher` | verdict |
|---|---|---|---|
| robot turns | 180 | **180** | MET |
| grounding_turn_rate | 1.0 | **1.0** | MET |
| coverage_rate | 0.9688 | **0.9688** | MET |
| invented_actions | 0 | **0** | MET |
| claims_per_turn | 1.444 | **1.444** | MET (beyond the bar) |
| zero_claim_turns | 5 | **5** | MET (beyond the bar) |
| hedge_rate | 0.0 | **0.0** | MET (beyond the bar) |
| b5 keys turn | 15/15 | **15/15** | MET (beyond the bar) |
| template_self_check_pass | 180 | **180** | MET (beyond the bar) |
| template_words_max | 21 | **21** (≤ `MAX_WORDS` 25) | MET (beyond the bar) |

Every sentence is rendered by the product `speech_acts` (`acts_for_receipt` /
`acts_for_owner_turn` / `render` / `compose`), checked by the product `check`,
and scored by the product `narration_matcher`. The research tree supplies only
WHEN a turn happens — the corpus (`events.py`), the trigger table
(`narrate.py:PlanQueueWhisperer` at the published bands {2, 15.0}) and the
steering policy (`steer.py`) — which is exactly what MB-2's arm T inherited
unchanged from MB-1 and did not vary.

**Three rows hold the port, not one.** The card asks for the file pin; the
reproduction is only worth its numbers if the vocabulary is the scored one, so
there are two stronger rows beside it:

- `test_the_matcher_is_pinned_to_mb1s_frozen_scorer` — `sha256(scorer.py)` ==
  `e5044a90…9bab5` from `mb1_pins.sha256`, plus `narrate.py`, `events.py` and
  `steer.py` (a changed corpus moves the reproduction as far as a changed
  matcher). `pytest.skip` with a named reason when the research tree is absent.
- `test_the_ported_vocabulary_is_the_scorers_vocabulary` — every `CLAIM_PATTERNS`
  pattern string and flag, `SUPPORTED_BY`, `COVERAGE_CLAIMS`, `HEDGES`, `OFFER`,
  `INABILITY`, all 14 `ACTION_VERBS`, `_PUNCT` and `MATCHER_ID` compared to the
  research scorer's, object by object. The file pin says MB-1 did not move;
  this says the PORT did not.
- `test_the_product_scorer_agrees_with_the_research_one_turn_by_turn` — all 180
  arm-T sentences scored by BOTH implementations, comparing claims, unsupported
  claims, invented-action reasons, grounded, hedged and premature per turn. An
  aggregate can match through compensating errors; 180 paired verdicts cannot.

### Row 2 — off-path byte-identical, and the flag

> "Off-path digest unchanged with the flag OFF; the flag exists and defaults OFF (test)."

| | value |
|---|---|
| digest BEFORE any edit (HEAD `704ba5c`, clean `lane.py`/`realtime/config.py`) | `edaa32ed66fca69be4fce66afb5e2a04f0c55487f3c357f41ffcd1ba698dcecb` |
| digest AFTER the card, flag OFF | `edaa32ed66fca69be4fce66afb5e2a04f0c55487f3c357f41ffcd1ba698dcecb` |
| verdict | **UNCHANGED** |

`tests/test_speech_acts.py::test_the_off_path_narration_is_byte_identical_with_the_flag_off`
also pins the 180 arm-T sentences separately
(`7e54e3c742bc576935d928dcadab92a15b9f9eece6105bf84395ac9b4891ba8a`) so a
failure says WHICH half moved — the templates or the lane.

The flag: `test_the_speech_acts_flag_exists_and_defaults_off` (absent file,
absent block, empty block and `SpeechActsConfig()` all mean OFF) and
`test_the_flag_block_refuses_a_typo_rather_than_reading_it_as_off`
(`enabled: ture`, an unknown key and a non-mapping each raise
`RealtimeConfigError`). `test_the_flag_being_off_is_what_the_lane_actually_sees`
asserts the lane the digest was taken through reports `speech_acts.enabled` False
and sends the caller's own text unrewritten.

### Row 3 — hygiene

> "No `noqa`; `config.py` unchanged; no hosted calls; no research import from `src/`."

- **`noqa`: 0** in all four owned files (`grep -c noqa` → 0/0/0/0). The one place
  the port wanted one — MB-1's blind `except Exception` in `default_registry` —
  is written as `contextlib.suppress(Exception)` instead, the idiom card HW-4's
  verifier blessed; the cost (the swallowed exception's type is no longer named
  in `source`) is on a branch MB-2 never took and is documented at the line.
- **`src/parcel_robot/config.py` unchanged** — still exactly 1000 lines, no diff.
- **hosted calls: 0, $0.00** — no network in any module or test; the whole suite
  is in-process against the scripted fake server.
- **no research import from `src/`** —
  `test_the_product_modules_import_no_research_code_at_runtime` proves it by
  RUNNING: a subprocess imports both modules with only `src` on the path and
  reports `sorted(set(sys.modules) & {events, scorer, narrate, steer, contract,
  arms, mb1})` → `[]`; and neither module contains the string `sys.path`.
- **ruff**: `All checks passed` on all four owned files plus `realtime/config.py`;
  the ratchet gains **zero** new fingerprints from this card (the 72 new
  fingerprints in the tree are all other cards' `research/20260829/*` folders and
  `tests/test_duplex_transaction_v*.py`).

## 3. Commands and results

```
~/.cache/parcel-guard/pytest_guard.sh --label C5 .parcel/bin/python -m pytest \
  tests/test_speech_acts.py tests/test_narration_matcher.py tests/test_realtime_lane*.py -q
→ 91 passed in 3.87s          (the card's acceptance command, verbatim)

… tests/test_speech_acts.py tests/test_narration_matcher.py \
  tests/test_realtime_lane*.py tests/test_turn1_endpointing.py -q
→ 164 passed in 4.51s

… -k "realtime or web_panel or state or config or whisperer or prototype or turn1"
→ 1976 passed, 3 skipped, 9309 deselected in 50.49s

.parcel/bin/ruff check <the five touched files> → All checks passed
```

`TMPDIR` unset on every run; every run through the guard with `--label C5`;
no `-n auto`, no `--pdb`, no `ci_gate.py`.

### The one red row, attributed

`tests/test_dec0_debt_ratchet.py::test_no_new_oversized_module` and
`::test_no_new_long_function` are RED, naming
`audio/voice_loop.py`, `brain/executive.py`, `bridge/protocol.py`,
`control/motion_gateway.py` and eight function names. **Not this card.** All four
are ` M` in the working tree (the owner's / other cards' uncommitted diffs).
Measured, not assumed: with `speech_acts.py` and `narration_matcher.py` moved
out of the tree the two tests fail with the byte-identical message, so this
card's modules contribute nothing to either row.

## 4. What the card built, in one paragraph

`speech_acts.py` is MB-2's `contract.py` with the research imports removed: the
nine acts and `ask_clarify`, their slots (validated at construction — an unknown
slot raises), one deterministic template each plus the two boolean-slot second
renderings, the closing questions, and `check` — the post-condition checker with
its twelve closed-enum reasons. `narration_matcher.py` is MB-1's `scorer.py`
minus its research plumbing: `normalise`, the ten claim classes and their
patterns, `SUPPORTED_BY`, the coverage map, `HEDGES`/`OFFER`/`INABILITY`, the
fourteen `ACTION_VERBS`, `CapabilityRegistry`/`default_registry`, the three-door
`find_invented_actions` (including the `SafetySupervisor` disposition), the
premature-arrival rule and `score_turn`. Receipts are duck-typed on both sides
(`t`, `fact`, `goal`, `event_id`, `detail`, `queue`) so the executive's receipts,
MB-1's corpus and any future shape all fit without the product importing one.

Two deliberate departures from the research code, both recorded in the module
docstrings:

1. **`_lexical_flags` is NOT ported.** It imports `evals.companion.realtime_convo_v1`
   `RISK_PATTERNS`, which would put an `evals/` import inside `src/`; MB-1 calls
   it "TRIAGE ONLY, never the verdict" and `arm_T`'s
   `lexical_flags_triage_only` is `{}`. No published row depends on it.
2. **`check` takes `places` as a required keyword** where MB-2 read the corpus's
   own place list. An empty vocabulary silently disables the foreign-place
   rule — the rule that catches a swapped destination — so a caller with no
   vocabulary has to say so at the call site, in writing.

`acts_for_receipt` / `acts_for_owner_turn` (MB-2's `arms.py`) are in the product
module, not the test, because they ARE the receipt→act mapping wave B installs;
they were rewritten to take primitives (`keys_turn`, `clarify_question`, folded
and prior receipts) so no research type crosses into `src/`. The corpus walk,
the band ledger and the steering policy stay in the test: they are the
instrument, not the subject.

## 5. One decision the card did not anticipate

`RealtimeConfig.as_dict()` does **not** render the new block. `/api/state`'s key
set is a pre-registered row of card TURN-1
(`tests/test_turn1_endpointing.py:302` — "+1 key, 0 changed"), which C5 does not
own and may not re-pin, and adding `speech_acts` to the dict reddens it. In
wave A nothing reads the flag, so a key in the panel's JSON would advertise a
switch that cannot be flipped while churning a frozen row to say so. It also
makes the off path *more* byte-identical: the panel's JSON is untouched too.

**The wave-B install must add the row and re-pin TURN-1's assertion with its
reviewer** — an operator has to be able to see a live switch. This is written at
the line in `realtime/config.py` as well as here, so it cannot be forgotten.

## 6. The wave-B install point, exactly

Nothing below is written on this card. Line numbers are at HEAD `704ba5c`.

**a. The lane seam — `src/parcel_robot/realtime/lane.py:1832`,
`RealtimeLane.narrate_event`.** Add one optional keyword:

```
def narrate_event(self, text: str, *, critical: bool = False,
                  act: speech_acts.SpeechAct | None = None) -> bool:
```

`act=None` (every caller today) keeps line 1899 — `clean = " ".join(str(text).split())`
— exactly as it is, which is why the flag-OFF digest above is the whole proof of
the off path. When `act is not None and self.config.speech_acts.enabled`, line
1899 becomes the contract's sentence instead:
`clean = speech_acts.compose((act,), closing=…)`. That is the one-line change;
the four noes, the budget asymmetry, the item tagging and the counters at
1946-1953 are untouched.

The card's "unbilled tail item" is the second half of the same change and is a
DESIGN QUESTION wave B must answer out loud, not a detail: the sentence the
contract renders is already final, so paying for a `response.create` (line 1953)
to have the model re-say it is exactly the step MB-1 measured at grounding
0.61-0.73. Sending it as a `purpose=ITEM_PURPOSE_TAIL` item with no
`ResponseCreate` makes it free and ungarbled but leaves nothing voiced — the
lane's mouth is hosted audio. Wave B must pick: (i) item + `response.create`
with the sentence as a quote-verbatim instruction, (ii) item only, and route the
sentence to the local TTS path, or (iii) both, with the contract's sentence as
the tail and the model free to add nothing. The MB-2 evidence constrains the
FACTS, not the voicing, and nothing on this card decides it.

**b. The caller — `src/parcel_robot/runtime.py:16630`, `RobotRuntime._whisper`**
(and the second call at `:17340`). Today it passes `decision.text`, a sentence
the whisperer composed for a model to reword. Wave B passes the act beside it:
`self._narrate_mission(decision.text, critical=…, act=decision.act)`, threaded
through `_narrate_mission` (`:16561`, one parameter) to `lane.narrate_event`
(`:16599`). Both files are in the owner's uncommitted diff, which is why this
card writes neither.

**c. The vocabulary bridge — the whisperer's `KIND_*` to the matcher's `FACT_*`.**
`speech_acts.acts_for_receipt` speaks MB-1's fact vocabulary
(`accepted / running / blocked / completed / failed / cancelled / resumed`); the
whisperer speaks `KIND_*` (`whisperer.py:118-292`). One map, and it belongs in
the whisperer or the executive, not in `speech_acts`:

| whisperer kind | fact | act |
|---|---|---|
| `KIND_MISSION_ARRIVED` | `completed` | `completed(goal)` (+ `resume_offer(goal)` when the queue has a pending record, else the closing question) |
| `KIND_MISSION_BLOCKED` | `blocked` | `blocked(class)` — class from the block detail |
| `KIND_MISSION_BLOCK_CLEAR` | `running` w/ "the way is clear…" detail | context band; MB-1's trigger table never speaks it — the named cause of arm T's coverage cap at 0.9688 |
| `KIND_MISSION_ENDED`, person-blocked / gave-up reason | `failed` | `failed(goal, class)` + `CLOSING_QUESTION_FAILED` |
| `KIND_MISSION_ENDED`, e-stop / cancellation reason | `cancelled` | `cancelled(goal)` + `CLOSING_QUESTION` |
| C4's plan-acceptance kind | `accepted` | `ack(goal, queued)` — `queued` from the queue record's status |
| `KIND_REROUTE` | `resumed` / progress | `resumed(goal)` or `progress(goal)`; the band decision is C4's, not this map's |
| `KIND_REFUSAL` of a perception request | — | `capability_refusal(vision)` |

**d. `check`'s `places`.** The install passes the runtime's own place vocabulary
(the navigator's known places / the grounder's names) so the foreign-place rule
is live in product; passing `()` disables the one rule that catches a swapped
destination and must be a written decision, not a default.

## 7. Does not prove

- **Naturalness.** Untouched and unmeasurable from here: MB-2's judge was
  position-biased (first-shown won 30/40, p = 0.002) and its own verdict marks
  the row UNMEASURED. Nothing on this card claims the templates sound good.
- **The paraphrase layer.** Deliberately absent — no local model, no hosted
  call, no paraphrase path in `src/`. MB-2 measured an ungated paraphraser
  deleting the "I have no camera" refusal 15/15.
- **The install.** Wave B. The flag is OFF, nothing reads it, and the byte-
  identical digest is the proof that nothing does.
- **That the contract's numbers survive the product's own receipts.** The
  reproduction runs over MB-1's authored corpus in MB-1's fact vocabulary. The
  `KIND_*` bridge in §6c is untested by anything on this card, and the first
  wave-B row should be that bridge over real executive receipts.
- **Grounding is still blind to omission.** MB-2's decisive finding, carried
  intact: the checker's required-statement rules (`REASON_MISSING_INABILITY`,
  `REASON_MISSING_OFFER`, `REASON_MISSING_GOAL`) are the only thing that catches
  a dropped sentence, and they are only exercised here on templates that never
  drop one.

## 8. Housekeeping for the integrator

`CODEBASE_INDEX.md` needs regenerating at close: two new product modules and two
new test files. Not done here — the index is a shared file this card does not own
(`.parcel/bin/python tools/codebase_index.py`).
