# W2 · INSTALLS-1 — executor status (Opus)

Card: `W2_INSTALLS.md` · Board: `README.md` (task_1, 2026-08-30) · Verifier: Fable · Lens: parcel-6c
**Spend:** $0.00 hosted. No network. No git writes (no `add`/`commit`/`stash`). No `ci_gate.py`.
No `-n auto`. No `--pdb`. Every pytest through `~/.cache/parcel-guard/pytest_guard.sh --label W2*`.

---

## 0 · Pre-flight (rule 1)

| fact | value |
|---|---|
| worktree | `/home/jaewoo-jang/.cache/parcel-0e/wb/w2` (`git worktree add --detach … HEAD`) |
| worktree HEAD | **`c96ac345358ec2786748fc3a885c35d32710c5e2`** |
| `python -c "import parcel_robot; print(parcel_robot.__file__)"` | `/home/jaewoo-jang/.cache/parcel-0e/wb/w2/src/parcel_robot/__init__.py` — **the worktree**, not the root |
| env in every shell | `PYTHONPATH=$PWD/src:$PWD`, `MUJOCO_GL=egl`, `OPENBLAS_NUM_THREADS=32`, `TMPDIR` unset |
| `.parcel` | symlink to the root venv; shows as `??` in the worktree and is **not** a deliverable |
| main repo | **never edited** except this one file |

### The two frozen digests, re-derived AT HEAD BEFORE the first edit

Run at 07:5x, in the clean worktree, before any file was touched:

```
pytest_guard.sh --label W2-preflight … \
  tests/test_whisperer_plan_accepted.py::test_the_off_path_output_over_the_mb1_corpus_is_byte_identical \
  tests/test_speech_acts.py::test_the_off_path_narration_is_byte_identical_with_the_flag_off
→ 2 passed in 1.07s
```

| pin | value | pre-edit | post-card |
|---|---|---|---|
| C4 off-path (whisperer over MB-1's 40 scenarios, no receipts) | `4e5e2e47d43d3f182260ec9e435a4701861cbf2953f226cea8309f2f9fe03663` | **GREEN** | **GREEN** |
| C5 off-path (`narrate_event` over arm T's 180 turns, flag OFF) | `edaa32ed66fca69be4fce66afb5e2a04f0c55487f3c357f41ffcd1ba698dcecb` | **GREEN** | **GREEN** |
| arm-T text digest `7e54e3c7…` | (inside the same test) | GREEN | GREEN |

---

## 1 · Acceptance rows (bars quoted verbatim)

> **"MB-1's 40-scenario corpus replayed through the PRODUCT path (fake executive → receipts →
> `_accept_plan` hook → whisperer → lane with the flag ON, fake voice): b1 'new goal
> acknowledged' 75/75 from `KIND_PLAN_ACCEPTED`; narration grounding ≥ 0.98, invented 0,
> keys bar 15/15 — scored with `narration_matcher`."**

`tests/test_realtime_speech_act_install.py::test_the_mb1_corpus_through_the_product_path`.
The path is the product's, end to end: a real `RobotRuntime` (commissioned fixture), a real
`RealtimeLane` over `FakeRealtimeServer` (the "fake voice"), `speech_acts.enabled: true`, one
fresh lane + whisperer per scenario, and the corpus's own three places fed in as
`SemanticObjectTrack`s so `_realtime_places()` — the SAME vocabulary `navigate_to` is admitted
against — returns them. Measured:

| row | bar | measured | result |
|---|---|---|---|
| b1 opportunities | 75 | **75** | **GREEN** |
| every opportunity lands on a `KIND_PLAN_ACCEPTED` rule | 75/75 | **75/75** (`forward:plan_admitted` 65, `suppress:plan_not_admitted` 5, `suppress:plan_reissue` 5) | **GREEN** |
| narration grounding | ≥ 0.98 | **1.000** over 80 narrated turns (65 acks + 15 keys refusals) | **GREEN** |
| invented actions | 0 | **0** | **GREEN** |
| keys bar | 15/15 | **15/15** | **GREEN** |
| `response.create` on the contract path | (row 5) 0 | **0** | **GREEN** |

The 10 non-forwarded rows are wave A's, unchanged and for wave A's reasons: five `resumed`
receipts resume T2 at the SAME revision (`replace` refuses — `plan_not_admitted`) and five
resume T1 with the plan it already ran (the re-issue guard holds — `plan_reissue`). W1's queue
is what turns those into their own `queue`-lineage receipts.

> **"Flags OFF: C4's off-path digest `4e5e2e47…` and C5's `edaa32ed…` unchanged."** — §0 table.
> **GREEN**, both, re-run after the lane hunk and again at close.

> **"Poisoned-slot and claim-bearing-clarification tests REJECT; swapped destination refused;
> empty `places` errors."**

| row | test | result |
|---|---|---|
| poisoned `goal` slot (the lens's own string, and one carrying an arrival claim) | `test_a_poisoned_goal_slot_is_refused_and_the_template_is_narrated` | **GREEN** — REJECT, template narrated, nothing voiced |
| claim-bearing `ask_clarify` question | `test_a_claim_bearing_clarification_question_is_refused` | **GREEN** — `unsupported_claim`, template fallback |
| render→check inseparable | `test_render_and_check_cannot_be_separated` | **GREEN** — `voiced_sentence` returns `""` on REJECT |
| swapped destination | `test_a_swapped_destination_is_refused` | **GREEN** — `foreign_place_name:bench` |
| empty `places` errors at the install point | `test_an_empty_place_vocabulary_is_an_error_at_the_install_point` | **GREEN** — `error` event + template; never `places=()` |
| second layer | `test_voiced_sentence_refuses_to_check_against_nothing` | **GREEN** — `SpeechActInstallError` |

> **"`tests/test_realtime_*.py`, `tests/test_runtime_whisperer_wiring.py`,
> `tests/test_turn1_endpointing.py` (re-pinned) green through the guard."**

```
pytest_guard.sh --label W2-full … tests/test_realtime_*.py tests/test_runtime_whisperer_wiring.py \
  tests/test_turn1_endpointing.py tests/test_speech_acts.py tests/test_whisperer_plan_accepted.py \
  tests/test_narration_matcher.py tests/test_curio1_chatter.py tests/test_dec0_debt_ratchet.py \
  tests/test_mission_log.py tests/test_p0b_companion_unlocks.py tests/test_p2_dialogue.py \
  tests/test_r24_lock_discipline.py tests/test_nominal_stop_wiring.py tests/test_stop_ramp.py -q
→ 1636 passed, 2 skipped in 58.76s
```

```
pytest_guard.sh --label W2-brain … tests/test_runtime_brain_integration.py \
  tests/test_brain_runtime_adapter.py tests/test_preempt_runtime.py tests/test_k4_opus_wiring.py \
  tests/test_brain_executive.py tests/test_p0c_flush_product_path.py -q
→ 46 passed
```

> **"no `noqa`; `config.py` unchanged; $0 hosted; no network."**
> **GREEN**: `git diff | grep -c '^+.*noqa'` = **0**; `src/parcel_robot/config.py` = **1000 lines,
> not in the diff**; ruff over `src/ tests/` finds **9 findings, all pre-existing, all in files
> this card did not touch** (`camera_channel/backends/factory.py`, `detection_adapter/sim_bridge.py`)
> — **zero added to the ratchet**; `ruff check` on every touched file: *All checks passed*.

---

## 2 · README rule 4's W2 rows

| row | where | result |
|---|---|---|
| "tested at candidate sha X in worktree Y" | HEAD `c96ac34`, `/home/jaewoo-jang/.cache/parcel-0e/wb/w2` | recorded (§0) |
| "adjacent to `<function>`; the dirty root's hunks in this file are at `<headers>`, none overlap" | §3 | **GREEN**, zero overlap |
| R24 lock roster / nominal-stop digests green with **zero re-pins** | `tests/test_r24_lock_discipline.py`, `tests/test_nominal_stop_wiring.py`, `tests/test_stop_ramp.py` | **GREEN**; neither file is in the diff — no assertion moved |
| `narrate_event`'s OFF-path byte-identity survives the lane hunk | `edaa32ed…` re-run after the hunk | **GREEN**; and the local statement `test_act_none_leaves_the_lanes_narration_path_exactly_as_it_was` |
| queue-policy re-issue (new task, same digest → fires) beside the same-task re-issue (does not) | `test_the_queue_policys_reissue_is_a_new_task_and_does_fire`, `test_a_reissue_of_the_same_task_and_plan_says_nothing` | **GREEN** (fake queue lineage; W1's symbols are not depended on) |
| activation-time firing for deferred replacements + dropped-before-activation | `test_a_deferred_replacement_says_nothing_until_it_activates`, `test_a_replacement_dropped_before_activation_says_nothing_at_all` | **GREEN** |
| `mission` = executive `task_id`, never a goal label | `test_the_hook_keys_on_the_executive_task_id_and_never_on_a_goal_label` | **GREEN** — two tasks, one label, two sentences; keys are `plan_accepted:<task>:<sha>` |
| hourly reroute ceiling with N and its $ denominator stated | `REROUTE_PER_HOUR_CEILING = 6`, `whisperer.py`; §4 | **GREEN** |
| render→check as ONE unit, poisoned `goal` AND `question` | §1 | **GREEN** |
| non-empty learned-map `places`; swapped destination refused; empty ⇒ error | §1 | **GREEN** |
| claim-free clarifications from `voice/amendment.py` (or measured noise) | §5 | **GREEN + measured** |
| `as_dict` renders `speech_acts`; TURN-1's `HEAD_CONFIG_KEYS` re-pinned with the cause in the same diff | `realtime/config.py`, `tests/test_turn1_endpointing.py` | **GREEN** — "+2 keys, 0 changed", cause written in the test's docstring and at the config line |
| item-only + local-TTS voicing; NO fact produces a `response.create` | `test_no_fact_on_the_contract_path_ever_asks_for_a_hosted_response` | **GREEN** — 0 over the corpus; §6 states the boundary |
| the `narration_matcher` docstring line | `default_registry` | **GREEN** |

---

## 3 · Hunk adjacency (rule 4, verbatim shape)

**The main repo's dirty `runtime.py` hunks are NOT in my worktree** — I developed in a detached
worktree at HEAD `c96ac34`, so `git diff` here is the pure patch and applies to HEAD by
construction. The dirty root's hunk headers were read once (`git diff HEAD -- src/parcel_robot/runtime.py`
in the root, read-only) purely to prove non-overlap.

| my hunk | adjacent to | HEAD lines |
|---|---|---|
| the `realtime.narration_matcher` / `realtime.speech_acts` / `realtime.whisperer` import rows | adjacent to the module import block | 352-357, 360-365, 393-398, 401-406 |
| `DEFERRED_ADMISSION_DISPOSITIONS` | adjacent to `EMERGENCY_STOP_TERMINAL_REASONS` | 596-601 |
| `plan_lineage = LINEAGE_REVISE` / `= LINEAGE_NEW` | adjacent to `_accept_plan` (the two executive branches) | 3536-3541, 3546-3551 |
| `self._whisper_plan_accepted(...)` | adjacent to `_accept_plan` (after the "Accepted plan" emit, before `return self._plan_acknowledgement(plan)`) | 3604-3609 |
| `_narration_act_at_call_site` + `_narrate_mission` signature | adjacent to `_narrate_mission` | 16469-16475, 16485-16490, 16503-16518, 16538-16544 |
| `_whisper` passes `decision.act` | adjacent to `_whisper` | 16588-16594 |
| the `"fact"` / `"klass"` rider on the mission-ended event | adjacent to `_narrate_mission_terminal` | 17222-17227 (region), 17248-17254 |
| `_whisper_plan_accepted` (the 95-line sibling) | adjacent to `_whisper_curiosity` | 17375-17381 (insert point) |
| `_whisper_curiosity` passes `decision.act`; `_whisper_refusal` gains `capability` | adjacent to `_whisper_curiosity` / `_whisper_refusal` | 17404-17410 |

**Dirty root hunks in `runtime.py` (HEAD line ranges), all avoided:**
`38-43, 422-427, 2196-2201, 2254-2259, 2508-2513, 2658-2663, 2670-2676, 2685-2691, 3193-3199,
3777-3782, 3803-3817, 3819-3825, 3833-3841, 4950-4955, 5106-5111, 5331-5336, 5356-5361,
9428-9433, 9545-9561, 9574-9579, 11481-11486, 11855-11860, 17968-17987`.

**Mine (HEAD line ranges):**
`352-357, 360-365, 393-398, 401-406, 596-601, 3536-3541, 3546-3551, 3604-3609, 16469-16475,
16485-16490, 16503-16518, 16538-16544, 16588-16594, 17222-17227, 17248-17254, 17375-17381,
17404-17410`.

**Intersection: EMPTY.** The nearest approach is 401-406 against the dirty 422-427 (16 lines of
clearance) and 3604-3609 against the dirty 3777-3782.

No other owner-diff file is touched: `brain/executive.py`, `gateway/*`, `bridge/*`, `control/*`,
`navigation/grid_planner.py`, `docs/`, `prompts/`, `configs/robot.go2_edu_plus.yaml` are all
absent from the diff. `voice/amendment.py`, `realtime/*` are clean at HEAD in the root too.

---

## 4 · The mission-independent reroute ceiling — N, and its denominator

**N = 6 forwarded reroutes per ROLLING hour** (`REROUTE_PER_HOUR_CEILING`,
`REROUTE_CEILING_WINDOW_S = 3600.0`, `RULE_REROUTE_HOUR_CEILING`).

Why the per-mission cap is not enough (parcel-6c's wave-B row 3): `REROUTE_PER_MISSION_CAP` keys
on `RerouteReceipt.mission`, which W2 fixes as the executive's `task_id` — so a re-issue is a
genuinely new mission with a genuinely fresh three, and three-times-unbounded is unbounded.

| | forwards | $ | $/month |
|---|---|---|---|
| priced workload (C4's denominator) | 20 missions/day × ≤ 3 = **60/day** | $0.0024 each (MB-1 ledger: $1.33 / 550 rows) | **~$4.3** |
| the ceiling's worst case | 6/h × 24 = **144/day** | ″ | **~$10.4** (6.5% of `DEFAULT_ENVELOPE_USD` $160) |
| uncapped CRITICAL (what C4 refused) | ≤ 30/mission | ″ | **~$43** (25% of the envelope) |

6/hour never binds on the priced workload (60/day over a 16-hour waking day = **3.75/hour**) and
still admits **two fully rerouted missions inside one hour**. Over the ceiling the item is
dropped, logged and never billed; `undeliver` hands the hour's slot back with the mission's, for
`undeliver`'s own stated reason. Tests: `test_the_hourly_ceiling_bounds_a_reissue_chain_the_mission_cap_cannot`,
`test_the_per_mission_cap_still_binds_inside_the_hour`,
`test_a_reroute_the_floor_refused_gives_back_both_allowances`.

**Not built, and why:** no `runtime.py` install for `KIND_REROUTE`. It is not on the card's build
list (items 1-6), the social-progress observer's shadow-sample path publishes no decision object
at the point a hook would need one, and inventing a call site inside an owner-diff file for a row
the card did not ask for is exactly what rule 2 of the standing constraints forbids. The band, the
per-mission cap and the hourly ceiling are all live and tested at the whisperer's door; the caller
is one line whenever the reroute install is carded.

---

## 5 · The clarification composer — claim-free, and the residual measured

`voice/amendment.py` `clarification_from_grounding` opened every question with a PERCEPTION claim
("I can see more than one bench", "I don't see a red mailbox yet", "(I also see …)") and offered
to "look around (scan)" — which is the same claim in the future tense and is MB-1's
pre-registered FORBIDDEN behaviour on the keys turn. `CLAIM_PERCEPTION` maps to the empty
support set by construction, so no receipt in this vocabulary can ever license one.

Rewritten claim-free (the scan OFFER is kept — the capability is real and
`test_clarification_unseen_offers_scan` still passes; only the perceptual claim is gone):

| outcome | now |
|---|---|
| AMBIGUOUS, ≥ 2 labels | `Do you mean the {a}, or the {b}?` (+ `Or one of these: …?`) |
| AMBIGUOUS, 1 label | `Which one do you mean: the {a}, or another one?` |
| AMBIGUOUS, 0 labels | `Which {query} do you mean?` |
| UNSEEN | `I don't have a {label} to go to yet. Would you like me to run a scan for one?` |

**Measured through the product matcher** (`test_every_clarification_the_composer_produces_is_claim_free`):
**0 claims, 0 invented actions, 0 unsupported** across the whole corpus. **GREEN.**

**The residual, measured and reported rather than papered over**
(`test_the_clarification_refusal_noise_is_measured_and_named`): a clarification NAMES candidate
places, and `ACT_ASK_CLARIFY` carries no `goal` slot in MB-2's frozen contract, so the checker's
slot-fidelity rule reads every named place as foreign. **4 of the 5 questions REJECT, on
`foreign_place_name` and on nothing else**; the one that names nothing PASSES. That is a
CONTRACT SHAPE, not a claim — widening MB-2's frozen slot enum is a change to its evidence and
belongs to the card that re-measures it. Recorded here as the card's "or the refusal noise is
measured and reported" branch, taken deliberately.

---

## 6 · The voicing decision, and its exact boundary

Adopted verbatim from AUDIT_C5 note 2: **item-only + local TTS for terminal facts; never a
`response.create` on a fact.**

Implemented as: when the lane takes the CONTRACT path (an act is present, the flag is on, and
`check` PASSED) it sends the `system` item and **no `ResponseCreate`**, does not set
`_response_provenance` (no response of ours is coming, and a stale `system` tag would
mis-attribute the owner's next one), records `last_narration` / `last_narration_from_contract`,
and `RobotRuntime._narrate_mission` voices **that exact string** through
`_speak_system_utterance` → `DuplexVoiceSession.speak_system`. Read back rather than re-composed:
a second composition is a second chance to differ from what `check` passed
(`test_the_sentence_voiced_is_the_sentence_that_passed_the_checker`).

**The boundary, stated rather than glossed.** A class MB-2's contract has no act for — the block
clear (the named cause of arm T's 0.9688 coverage), battery, pace, the curiosity band — narrates
its TEMPLATE, and a template is written for a model to reword and carries the speech-act HINT
that tells it how. Speaking one through local TTS would read the instruction out to the owner.
So the template path keeps the model path exactly as it was, and the "no `response.create`"
claim is: **no fact the contract speaks for ever asks for a hosted response** — 0 over the whole
MB-1 corpus, because every fact the replay drives is contract-bearing. Pinned both ways
(`test_no_fact_on_the_contract_path_ever_asks_for_a_hosted_response`,
`test_a_refusal_that_does_not_name_its_capability_takes_the_template_path`,
`test_with_the_flag_off_the_acknowledgement_takes_the_model_path`).

---

## 7 · Three consequences of the install, written down rather than absorbed

1. **`_accept_plan` now narrates.** Four rows in `tests/test_runtime_whisperer_wiring.py` asserted
   `lane.narrated == []` after `_realtime_follow("run")`, which ADMITS A PLAN. Their subject is the
   PACE WATCHER's silence, so they now read `_paced(lane)` — the same list with the
   acknowledgement rows dropped — with the cause in the helper's docstring. No pace number moved;
   the alternative (re-pinning the counts to 1) would have hidden a future pace regression behind
   an acknowledgement.
2. **Two signatures widened, the R25 lesson applied.** `narrate_event` and `_narrate_mission` both
   gained `act`. `_narrate_mission` calls the lane **with the old arity whenever the switch is
   off**, so no pre-W2 lane double ever sees the new keyword; the one door DOUBLE that needed it
   (`test_realtime_spend_budget.py`) takes it and ignores it, and the R25 signature-agreement test
   in that file now pins `act` beside `critical`.
3. **`tests/test_speech_acts.py`'s "not in `as_dict()`" assertion is superseded**, by the card:
   wave A left the key out because nothing read the flag; W2 is the install that makes it live.
   The assertion now reads `as_dict()["speech_acts"] == {"enabled": False}` with the cause written
   at the line, and TURN-1's row is re-pinned to "+2 keys, 0 changed" in the same diff.

---

## 8 · Files touched · `git -C <worktree> diff --stat`

Worktree `/home/jaewoo-jang/.cache/parcel-0e/wb/w2`, HEAD `c96ac345358ec2786748fc3a885c35d32710c5e2`
(new file shown via `git add -N`, then unstaged — the index is untouched):

```
 src/parcel_robot/realtime/config.py            |   20 +-
 src/parcel_robot/realtime/lane.py              |  140 ++-
 src/parcel_robot/realtime/narration_matcher.py |    9 +
 src/parcel_robot/realtime/speech_acts.py       |  102 ++
 src/parcel_robot/realtime/whisperer.py         |  230 +++++
 src/parcel_robot/runtime.py                    |  262 ++++-
 src/parcel_robot/voice/amendment.py            |   38 +-
 tests/test_realtime_speech_act_install.py      | 1241 ++++++++++++++++++++++++
 tests/test_realtime_spend_budget.py            |   19 +-
 tests/test_runtime_whisperer_wiring.py         |   36 +-
 tests/test_speech_acts.py                      |   14 +-
 tests/test_turn1_endpointing.py                |   21 +-
 12 files changed, 2085 insertions(+), 47 deletions(-)
```

`?? .parcel` is the venv symlink, not a deliverable.

## 9 · Does not prove

- **Hosted behaviour.** $0 spent, no network; the lane runs against `FakeRealtimeServer`.
- **Naturalness.** MB-2's judge was position-biased and its own verdict marks the row UNMEASURED.
  Nothing here claims the contract's sentences sound good — only that they are true.
- **The block clear, the telemetry band and the curiosity band on the contract path.** MB-2 has no
  act for them; they narrate templates through the model path, unchanged.
- **W1's queue.** The `queue` lineage is exercised with a fake at the hook's own parameter; no W1
  symbol is imported or depended on.
- **A `KIND_REROUTE` install in `runtime.py`** (§4): the door, the cap and the ceiling are proven;
  the caller is not carded.

---

# Follow-up F1 (parcel-6c's lens, 2026-08-30) — the guessed lineage and the read-back

Same rules: worktree `/home/jaewoo-jang/.cache/parcel-0e/wb/w2` at HEAD
`c96ac345358ec2786748fc3a885c35d32710c5e2`, `PYTHONPATH` pinned, `TMPDIR` unset, every pytest
through the guard (`--label W2-F1*`). No other change. $0 hosted.

## F1(1) — `lineage` is required and non-empty; the string guess is gone

**Removed:** `lineage = LINEAGE_REVISE if frame.speech_act == "correction" else LINEAGE_NEW`.
The lens is right and the guess was also *wrong*: a correction with **nothing active** comes down
`_accept_plan`'s `submit` branch and is a NEW goal, so the fallback would have labelled it
`revise`.

**Now:**

| | |
|---|---|
| signature | `_whisper_plan_accepted(plan, validated, submission, frame, *, lineage: str)` — **keyword-only, no default**. Omitting it is a `TypeError` at the call; no future caller can inherit a guess. |
| empty / blank `lineage` | **`ValueError`**, before the whisperer is touched. Unreachable from the product: both `_accept_plan` branches pass a module constant (`plan_lineage = LINEAGE_REVISE` at the `replace()` branch, `= LINEAGE_NEW` at the `submit()` branch) and the call reads `lineage=plan_lineage`. |
| `frame` | kept in the signature (the card pins the call shape) and now explicitly `del`-ed — the lineage was the only thing read off it. |
| non-empty but UNKNOWN lineage | unchanged: C4's **logged** refusal at the whisperer's door (`RULE_PLAN_RECEIPT_INVALID`), which never raises. |

**Deviation recorded, with the reason.** F1 said "assert or raise on empty … of
`_whisper_plan_accepted` / **the receipt**". The hook raises, as asked. `PlanAcceptedReceipt` does
**not**: C4's register makes its totality load-bearing ("Nothing here raises … a malformed receipt
is a LOGGED refusal at the door, not an exception"), it is constructed on the plan-admission path,
and making the field required would force a field reorder that breaks three frozen C4 rows
(`test_whisperer_plan_accepted.py:335, 338, 351` construct it without a lineage precisely to test
the door's refusal). Required-ness is therefore enforced at the hook, where raising cannot be
reached from the product, and totality is preserved at the receipt, where it protects an admission.

**Test:** `test_an_empty_lineage_is_refused_rather_than_guessed` — `TypeError` when omitted,
`ValueError` for `""` and `"   "`, **nothing voiced**; and `"sideways"` → one logged
`plan_receipt_invalid` suppression, no raise. **GREEN.**

## F1(2) — the voicing sentence comes off the RETURN, not off an attribute

**The defect the lens named:** `_narrate_mission` said "yes", then read `lane.last_narration` /
`lane.last_narration_from_contract` back **after** `narrate_event` returned, **outside the lane's
lock** — so a narration from another thread landing in between would be the sentence the robot
spoke aloud.

**Now:** `RealtimeLane.narrate_event_outcome(...) -> NarrationOutcome` is the door; everything is
decided **inside the lock** and handed back with the answer:

```python
@dataclass(frozen=True, slots=True)
class NarrationOutcome:
    narrated: bool = False        # the historical bool
    text: str = ""                # the exact sentence on the wire
    from_contract: bool = False   # ...and who wrote it
    def __bool__(self): return self.narrated
    @property
    def voice_locally(self) -> str | None: ...   # the sentence the CALLER must speak, or None
```

`_narrate_mission` now reads `voice = outcome.voice_locally` and speaks **that**;
`last_narration_from_contract` is **deleted** (its only purpose was the read-back) and
`last_narration` is documented as **audit only, with no control path hanging off it**.

**Deviation recorded, with the count.** F1 said "return the spoken sentence (or None) from
`narrate_event`". Changing *that* method's return type moves frozen rows this card does not own:
**24 `narrate_event(...) is True` / `is False` assertions across 6 files** (cards R16/R25:
`test_realtime_idle_hangup.py`, `test_realtime_reconnect.py`, `test_realtime_spend_budget.py`,
`test_realtime_system_initiated_motion.py`, plus two of W2's own) — `"a sentence" is True` is
`False` — **and C5's off-path digest recipe itself**, which records `bool(narrate_event(text))`.
So `narrate_event` keeps its `bool` contract as a one-line facade
(`return bool(self.narrate_event_outcome(...))`) and the sentence comes back from the outcome door.
The **substance** of F1(2) is delivered in full: no attribute is read back, and the value used for
voicing is computed under the lock and returned with the answer.

Also, because the ratchet keys on leaf names: the 92-line historical docstring (R8's "what `True`
means", R16, R25's ceiling asymmetry, C5's `act`) moved to **`narrate_event`** — the name already
in the DEC-0 baseline and the door the prose is about — and `narrate_event_outcome` carries a
6-line docstring naming only what it adds. Nothing was deleted. Lengths: `narrate_event` 107,
`narrate_event_outcome` **100**, `_narrate_mission` **100**, `_whisper_plan_accepted` **99** — all
new names under the 100-line ceiling, `test_no_new_long_function` **GREEN**.

**Tests:** `test_the_lane_hands_the_voicing_back_with_its_answer` (the outcome is a
`NarrationOutcome`, truthy, `from_contract` True, `text` == the checked sentence,
`voice_locally` == `text`; the bool facade still returns `is True`; a refusal is the falsy
`NARRATION_REFUSED` singleton and voices nothing) and
`test_a_template_narration_is_never_voiced_locally` (`voice_locally is None` for a model-facing
template, and it still asks for its `response.create`). **GREEN.**

## F1 results — re-run through the guard, from the worktree

| row | result |
|---|---|
| `tests/test_realtime_speech_act_install.py` | **28 passed** (was 25; +3 F1 rows) |
| the card's full acceptance + regression set (20 files: all `test_realtime_*`, wiring, TURN-1, speech_acts, whisperer, matcher, curio, DEC-0 ratchet, mission log, p0b, p2 dialogue, R24 lock roster, nominal-stop, stop-ramp, brain integration/adapter/executive, preempt, k4, p0c) | **1685 passed, 2 skipped in 59.88s** |
| C4 off-path digest `4e5e2e47d43d3f182260ec9e435a4701861cbf2953f226cea8309f2f9fe03663` | **unchanged / GREEN** |
| C5 off-path digest `edaa32ed66fca69be4fce66afb5e2a04f0c55487f3c357f41ffcd1ba698dcecb` | **unchanged / GREEN** |
| TURN-1 `/api/state` key set ("+2 keys, 0 changed") | **GREEN** |
| MB-1 corpus through the product path, re-measured after F1 | opportunities **75**, acceptance **75/75** (`plan_admitted` 65 / `plan_not_admitted` 5 / `plan_reissue` 5), grounding **1.000**, invented **0**, keys **15/15**, `response.create` **0**, narrated **80** — **identical to §1** |
| R24 lock roster / nominal-stop | **GREEN, zero re-pins** (neither file in the diff) |
| ruff `src/ tests/` | **9 findings, all pre-existing, all in files this card never touched**; every touched file *All checks passed* |
| `noqa` added | **0** |
| `src/parcel_robot/config.py` | **1000 lines, not in the diff** |

## F1 diff stat (whole card, after F1)

```
 src/parcel_robot/realtime/config.py            |   20 +-
 src/parcel_robot/realtime/lane.py              |  223 +++-
 src/parcel_robot/realtime/narration_matcher.py |    9 +
 src/parcel_robot/realtime/speech_acts.py       |  102 ++
 src/parcel_robot/realtime/whisperer.py         |  230 ++++
 src/parcel_robot/runtime.py                    |  289 ++++-
 src/parcel_robot/voice/amendment.py            |   38 +-
 tests/test_realtime_speech_act_install.py      | 1338 ++++++++++++++++++++++++
 tests/test_realtime_spend_budget.py            |   19 +-
 tests/test_runtime_whisperer_wiring.py         |   36 +-
 tests/test_speech_acts.py                      |   14 +-
 tests/test_turn1_endpointing.py                |   21 +-
 12 files changed, 2277 insertions(+), 62 deletions(-)
```

F1 moved `lane.py` +83 / `runtime.py` +27 / the install test file +97 against §8's numbers. The
runtime hunk set is unchanged in SHAPE — same functions, same adjacency, still zero overlap with
the dirty root's hunks (§3).
