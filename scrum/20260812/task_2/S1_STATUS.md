# S-1 status — hardening the design spike to its own invariant list

Card: [SPIKE_AND_PLAN_CARDS.md](SPIKE_AND_PLAN_CARDS.md) §"Card S-1".
Executor: Claude Opus 5. Date: 2026-08-12. **Not committed.**
Base: commit `7242660` (clean tree at start).
Owned and touched: `../task_1/design_spike/**` and this file — nothing else.

Closing [../task_1/FABLE_VERDICT.md](../task_1/FABLE_VERDICT.md) **RC-1 (a–d)**,
the spike half of **RC-2**, and **N-1 … N-4**. The verdict's charge was that the
spike's enforcement was weaker than its claims. It was, at every point the audit
named, and each is now enforced by code and pinned by a test that fails when the
enforcement is removed.

> ## Gate result
>
> | Gate | Required | Measured |
> |---|---|---|
> | Spike suite | 100 % green, count stated | **194 passed, 0 failed** in 0.26 s (was 43) |
> | `ruff check .../design_spike` | clean | **All checks passed!** |
> | Mutation campaign | 20/20 killed, each named | **46/46 killed, 0 survived** (the audit's 20, all killed, + 26 new) |
> | `git diff --check` | clean | **clean** (exit 0, no output) |
> | `does_not_prove` | preserved and extended | extended from 4 items to 8, plus a new 5-item product-obligation list |

Reproduce:

```bash
.parcel/bin/python -m pytest -q scrum/20260812/task_1/design_spike/test_contracts.py
.parcel/bin/ruff check scrum/20260812/task_1/design_spike
```

**`ci_gate --tier commit` was deliberately NOT run for this card, and that is a
statement, not an omission.** This card touches no file under `src/`, `configs/`,
`evals/`, `tests/` or `scripts/`, while W0-A and W0-B were editing product code
in the same worktree throughout. A gate run here would measure their in-flight
edits and attribute the result to S-1. The fresh ci_gate belongs to the tranche
audit at a stated commit, per this board's own orchestration note.

---

## 1. What was wrong, and what now enforces it

Each row: the audit's finding, the mechanism that now enforces it, and the test
that fails if that mechanism is deleted.

| Verdict item | Enforcement added | Pinned by |
|---|---|---|
| **RC-1a** prior-epoch lease authorizes | `RobotGatewayV1` is stateful: `phase`/`lease` are `init=False`, so a fresh instance (= a process boot) is `DISARMED` and cannot be constructed armed. `arm()` refuses a lease whose `epoch != boot_epoch` (STOP, stays disarmed); `candidate_verdict(current_epoch=…)` latches on an epoch mismatch. | `test_fresh_gateway_starts_disarmed`, `test_prior_epoch_lease_cannot_arm_the_gateway`, `test_lease_from_another_epoch_cannot_authorize_motion` |
| **RC-1b** NaN fails open | `_finite()` (false for `None`, `NaN`, `±inf`, non-numerics) guards every clock/timestamp/TTL/reserve **twice**: in the constructor and again in the verdict function, because a decoded payload need not have re-run `__post_init__`. Malformed time ⇒ `LATCHED_STOP`, never `PASS`. | `test_malformed_decision_clock_never_authorizes_a_candidate`, `…_latches_evidence_join`, `test_malformed_terminal_time_never_completes_a_task`, `test_malformed_behavior_deadline_never_passes` (+ 9 more) |
| **RC-1c** latch is a label | `RobotGatewayV1.observe()` folds `LATCHED_STOP` into persistent state; every later tick returns it regardless of input. `clear_latch()` needs an explicit operator ack **and** a fresh **physical** `StationaryWitnessV1` under caller-supplied thresholds, and returns the gateway to `DISARMED` — clearing is not re-arming. | `test_latched_stop_persists_across_a_subsequent_clean_tick` (5 clean ticks), `test_latch_does_not_clear_without_an_operator_event`, `test_latch_does_not_clear_without_fresh_stationary_feedback` (6 cases), `test_operator_clear_with_stationary_feedback_returns_to_disarmed_not_armed` |
| **RC-1d** 12/20 mutants survive | §3 below. | 46/46 killed |
| **RC-2** no pose reserve | `TerminalWitnessV2` gains **required** `arrival_margin_m` and `pose_uncertainty_m` (no defaults — a witness cannot omit the reserve). `terminal_verdict` refuses when `margin < uncertainty × pose_reserve_multiplier`. | `test_b5_episode_margin_below_pose_error_is_not_an_arrival`, `test_b5_true_outside_arrival_is_not_an_arrival`, `test_pose_reserve_rule_is_not_vacuous`, `test_terminal_witness_requires_the_pose_reserve_fields` |
| **N-1** in-place search has no surrounding-evidence contract | New `in_place_search_verdict`: a yaw-only candidate needs fresh, physical, valid surrounding collision evidence. Kept separate from `owner_motion_verdict` so the identity gate's scope (which the panel split 1-1 on, by design) is unchanged. | `test_in_place_search_requires_surrounding_collision_evidence`, `…_rejects_stale_…`, `…_rejects_non_physical_…` |
| **N-2** composition unenforced | New `authorize_motion()` composes join + admission + owner + in-place + envelope and hands the result to the gateway. The scoping is now stated and tested rather than assumed. | `test_candidate_verdict_alone_is_not_authorization` (shows the gate alone still PASSes and the composition refuses), `test_composed_pipeline_refuses_lab_origin_at_every_stage` (4 stages × 3 origins) |
| **N-3** zero gates PASS; CLAMP never produced | `dominant_verdict()` with no gates ⇒ `HOLD("no_gates_evaluated")`; `join_evidence` with an empty requirement set ⇒ `HOLD("no_required_evidence")`; new `speed_envelope_verdict` emits `CLAMP`. | `test_zero_gate_composition_is_not_authorization`, `test_empty_required_evidence_set_is_not_authorization`, `test_speed_envelope_produces_clamp`, `test_composed_pipeline_clamps_an_over_envelope_candidate` |
| **N-4** 4-value Resource enum | `Resource` is the canonical six (`base`, `posture`, `voice`, `attention`, `perception_scan`, `expression_audio`). | `test_resource_enum_is_the_canonical_six`, `test_perception_scan_behavior_is_expressible` |
| **Honesty fix** "200-case campaign" | README and the campaign docstring now state **200 draws over 54 single-fault classes**, and the class inventory is asserted in the suite rather than described in prose. | `test_campaign_class_inventory_is_what_the_docs_claim` |

Two defects of my own, found while writing this and fixed before the gate:
`dominant_verdict()`'s new zero-gate `HOLD` initially made `join_evidence`
return `HOLD` on a *clean* tick (it composed an empty fault list), and
`field(init=False, default=…)` under `slots=True` is not assigned by
`__init__` on every supported Python — both are now explicit (`if not faults:
return PASS`, `default_factory`). The first is exactly why the suite carries the
`test_clean_baseline_still_authorizes` negative control.

---

## 2. Seeded-failure proofs — the audit's own probes, re-run

The audit executed six probes that returned `PASS` against revision 1. Each is
now a test. The "before" column is the audit's recorded result, not my
re-measurement of revision 1.

| Probe (audit) | Revision 1 | Revision 2 | Test |
|---|---|---|---|
| P1 `TerminalWitnessV2(observed_at=NaN)`, predicate true, settled | `PASS` | `LATCHED_STOP` `terminal_time_malformed` | `test_malformed_terminal_time_never_completes_a_task` |
| P2 `settled_samples=-5`, `required=-10` | `PASS` | `ValueError` at construction; `LATCHED_STOP` at the gate for both the corrupted witness and the malformed requirement | `test_negative_settled_samples_are_rejected_at_construction`, `test_corrupted_settled_samples_never_completes_a_task`, `test_negative_required_settled_samples_never_completes_a_task` |
| P3 `BehaviorProposalV2(valid_until=NaN)` | `PASS` | `ValueError` at construction; `LATCHED_STOP` at the gate | `test_malformed_behavior_deadline_is_rejected_at_construction`, `test_malformed_behavior_deadline_never_passes` |
| P7 `candidate_verdict(now=NaN)` — all gates silently skipped | `PASS`, reasons empty | `LATCHED_STOP` `decision_clock_malformed` | `test_malformed_decision_clock_never_authorizes_a_candidate` |
| Epoch probe: `LeaseV1(writer, epoch=1, …)` against boot epoch 4 | `PASS` | `LATCHED_STOP` `lease_epoch_mismatch`; `arm()` refuses with STOP and stays disarmed | `test_lease_from_another_epoch_cannot_authorize_motion`, `test_prior_epoch_lease_cannot_arm_the_gateway` |
| Latch probe: frame-mismatch latch, then a clean call | `PASS` | `LATCHED_STOP` on 5 consecutive clean ticks, with the original reason preserved | `test_latched_stop_persists_across_a_subsequent_clean_tick` |

**Negative control.** `test_clean_baseline_still_authorizes` runs the same
composed pipeline and the same terminal witness with no fault injected and
requires `PASS` on both. Without it the whole campaign would be satisfiable by a
model that refuses everything.

**Campaign, stated honestly.** Revision 1: 200 draws over 12 evidence-stream
classes (3 streams × 4 modes), with the candidate rebuilt from the corrupted
scene so its revision gate could never fire. Revision 2: **54** named classes
across 12 families (evidence, clock, task, lease, gateway, capability, owner,
search, envelope, candidate, terminal, behavior); every class is run once
deterministically by name (`test_every_corruption_class_refuses_authorization`)
and then sampled 200 times with seed `0xD06`
(`test_seeded_fault_campaign_never_authorizes_a_corrupted_boundary`), which
draws ≥ 40 distinct classes. Each class carries its own minimum disposition, so
the CLAMP class is not silently satisfied by a HOLD floor, and the candidate is
now built from the **pre**-corruption scene so the evidence-revision gate does
fire.

---

## 3. Mutation campaign — 46 mutants, 46 killed

Method: scratch copies only. The driver reads
`scrum/20260812/task_1/design_spike/{contracts,test_contracts}.py`, copies them
to a scratch directory, string-patches the **scratch** `contracts.py` per
mutant, runs the full suite, and restores. The repo copy is never written by the
driver — it only ever holds the fixed code. Baseline in the scratch copy:
`194 passed`. Driver: `mutate.py` (see §6 for its location and the reason it is
not under the usual scratchpad path).

`M01`–`M20` are the audit's original 20, reconstructed from the audit workflow
record (patterns re-anchored to revision 2's text). The audit's **12 survivors
were `M02`, `M09`–`M17`, `M19`, `M20`** — every one is killed below.
`M21`–`M46` attack revision 2's new enforcement, so the additions cannot rot
silently either.

| # | Mutation | Invariant attacked | Result | Killing test |
|---|---|---|---|---|
| M01 | `age_s` uses the source clock, not the receipt clock | host-monotonic freshness | KILLED (20 failing) | `test_source_clock_jump_does_not_corrupt_watchdog` |
| M02 | default `allowed_origins` widened to admit `UNKNOWN` | un-provenanced evidence never authorizes | KILLED (collection) | `RequiredEvidenceV1` raises `ValueError: UNKNOWN origin can never be commissioned` while the module-level `REQUIRED` specs are built, so the mutation cannot even load; behavioural pin `test_default_required_evidence_admits_physical_origin_only` |
| M03 | `dominant_verdict` `max` → `min` | composition cannot relax | KILLED (40) | `test_dominant_safety_verdict_cannot_be_relaxed` |
| M04 | terminal settled-feedback leg dropped | stop ≠ completion | KILLED (2) | `test_stop_is_not_completion_until_feedback_settles` |
| M05 | writer-id check dropped | single writer | KILLED (3) | `test_second_writer_latches_stop` |
| M06 | candidate TTL from sender time | TTL on the receiver's clock | KILLED (3) | `test_expired_candidate_holds` |
| M07 | `AMBIGUOUS` authorizes follow translation | identity gate | KILLED (4) | `test_only_locked_owner_authorizes_follow_translation` |
| M08 | origin admission dropped | sim/replay cannot authorize | KILLED (15) | `test_lab_evidence_cannot_authorize_physical_motion` |
| M09 | owner-authorization leg dropped | motion needs an authorized task | KILLED (3) | `test_unauthorized_task_cannot_move_the_base` |
| M10 | vx capability limit dropped | platform limits | KILLED (2) | `test_vx_beyond_platform_capability_holds` |
| M11 | yaw capability limit dropped | platform limits | KILLED (3) | `test_yaw_beyond_platform_capability_holds` |
| M12 | task expiry dropped | task TTL | KILLED (3) | `test_expired_task_holds` |
| M13 | non-emergency behavior expiry dropped | behavior TTL | KILLED (3) | `test_expired_behavior_holds` |
| M14 | terminal task/revision binding dropped | arrival binds to its task | KILLED (3) | `test_terminal_witness_for_another_task_revision_holds` |
| M15 | terminal staleness dropped | arrival needs fresh evidence | KILLED (3) | `test_stale_terminal_witness_holds` |
| M16 | terminal evidence-revision binding dropped | arrival binds to its scene | KILLED (3) | `test_terminal_evidence_revision_change_holds` |
| M17 | `base_link` frame requirement dropped | commands are body-frame | KILLED (1) | `test_candidate_outside_base_link_is_rejected` |
| M18 | lease expiry demoted STOP → CLAMP | lease loss stops | KILLED (2) | `test_lease_loss_requires_stop` |
| M19 | terminal future-time tolerance widened | no arrival from the future | KILLED (3) | `test_terminal_witness_from_the_future_holds` |
| M20 | `calibration_epoch` requirement dropped | calibrated evidence only | KILLED (1) | `test_evidence_without_calibration_epoch_is_rejected` |
| M21 | `UNKNOWN`-origin commissioning guard dropped | unknown is never commissionable | KILLED (1) | `test_unknown_origin_can_never_be_commissioned` |
| M22 | lease-epoch check dropped in `candidate_verdict` | **RC-1a** | KILLED (6) | `test_lease_from_another_epoch_cannot_authorize_motion` |
| M23 | `arm()` ignores the epoch | **RC-1a** | KILLED (1) | `test_prior_epoch_lease_cannot_arm_the_gateway` |
| M24 | gateway born `ARMED` | **RC-1a** restart-disarm | KILLED (5) | `test_fresh_gateway_starts_disarmed` |
| M25 | latch not persisted to state | **RC-1c** | KILLED (30) | `test_latched_stop_persists_across_a_subsequent_clean_tick` |
| M26 | clear ignores the operator ack | **RC-1c** | KILLED (1) | `test_latch_does_not_clear_without_an_operator_event` |
| M27 | clear ignores residual translation | **RC-1c** | KILLED (1) | `test_latch_does_not_clear_without_fresh_stationary_feedback` |
| M28 | clear ignores stale stationary feedback | **RC-1c** | KILLED (1) | `test_latch_does_not_clear_without_fresh_stationary_feedback` |
| M29 | clear accepts simulated stillness | **RC-1c** | KILLED (1) | `test_latch_does_not_clear_without_fresh_stationary_feedback` |
| M30 | `candidate_verdict` clock guard removed | **RC-1b** (probe P7) | KILLED (4) | `test_malformed_decision_clock_never_authorizes_a_candidate` |
| M31 | `join_evidence` clock guard removed | **RC-1b** | KILLED (4) | `test_malformed_decision_clock_latches_evidence_join` |
| M32 | `terminal_verdict` clock guard removed | **RC-1b** | KILLED (3) | `test_malformed_terminal_clock_never_completes_a_task` |
| M33 | terminal observation-time guard removed | **RC-1b** (probe P1) | KILLED (5) | `test_malformed_terminal_time_never_completes_a_task` |
| M34 | behavior deadline guard removed | **RC-1b** (probe P3) | KILLED (5) | `test_malformed_behavior_deadline_never_passes` |
| M35 | zero-gate composition returns PASS | **N-3** | KILLED (1) | `test_zero_gate_composition_is_not_authorization` |
| M36 | CLAMP demoted to PASS | **N-3** | KILLED (4) | `test_speed_envelope_produces_clamp` |
| M37 | pose-reserve check dropped | **RC-2** | KILLED (5) | `test_b5_episode_margin_below_pose_error_is_not_an_arrival` |
| M38 | in-place search admitted without surrounding evidence | **N-1** | KILLED (3) | `test_in_place_search_requires_surrounding_collision_evidence` |
| M39 | `release()` does not disarm | second-writer-after-release | KILLED (3) | `test_released_writer_must_re_arm_before_commanding` |
| M40 | disarmed gateway authorizes | restart-disarm | KILLED (5) | `test_fresh_gateway_starts_disarmed` |
| M41 | `Resource` truncated to 4 values | **N-4** | KILLED (2) | `test_resource_enum_is_the_canonical_six` |
| M42 | composition drops `join_evidence` | **N-2** | KILLED (32) | `test_composed_pipeline_refuses_lab_origin_at_every_stage` |
| M43 | terminal predicate ignored | false arrival | KILLED (3) | `test_false_arrival_is_not_accepted` |
| M44 | terminal settled-sample bounds dropped | **RC-1b** (probe P2) | KILLED (1) | `test_negative_settled_samples_are_rejected_at_construction` |
| M45 | `required_settled_samples` bounds dropped | **RC-1b** (probe P2) | KILLED (1) | `test_negative_required_settled_samples_never_completes_a_task` |
| M46 | empty requirement set returns PASS | **N-3** sibling | KILLED (1) | `test_empty_required_evidence_set_is_not_authorization` |

Every "killing test" above was verified to be present in that mutant's actual
failure list, not inferred from intent (45 checked mechanically, 0 mismatches;
M02 is the collection-time kill described in its row).

**A measurement defect found and corrected in this campaign, disclosed.** The
first campaign run reported M12's killers as M11's. Cause: CPython validates a
cached `.pyc` on `(mtime, size)`, and two mutants written inside the same
coarse mtime tick can collide, so the second run silently executed the first
mutant's bytecode. The driver now runs `python -B` and wipes `__pycache__`
before every run; the table above is from that re-run. Both runs report 46/46
killed — the defect corrupted killer *names*, not kill counts — and M12 was
additionally re-run in isolation (`3 failed`, including `test_expired_task_holds`).

---

## 4. The RC-2 fixture, on B5's measured episode

Source: [../../../backlog/BLOCKED.md](../../../backlog/BLOCKED.md) §B5 (read
only; not modified). On the `calibrated_go2_reanchoring` arm the controller
stops 0.002–0.040 m inside the 2.5 m outer band edge *in its own MAP frame*
while claim-tick MAP error runs 0.007–0.239 m, and 3 of 7 arrivals stopped
TRUE-outside the band (−0.153 / −0.043 / −0.024 m).

| Fixture | `arrival_margin_m` | `pose_uncertainty_m` | Result |
|---|---|---|---|
| B5 named episode | 0.007 | 0.239 | `HOLD` `arrival_margin_below_pose_reserve` — **does not pass** |
| B5 TRUE-outside arrival | −0.153 | 0.239 | `HOLD` `arrival_margin_below_pose_reserve` |
| Reserve actually covered | 0.30 | 0.239 | `PASS` (the rule is not vacuous) |
| Same, at multiplier 3.6 | 0.30 | 0.239 | `HOLD` (a multiplier only tightens) |

`pose_reserve_multiplier` defaults to **1.0** — the weakest defensible rule,
"the margin must at least cover the claimed uncertainty". B5's finding that the
shipped covariance is 3.6× optimistic is an argument for a derived multiplier
above 1.0; it is deliberately **not** hard-coded here, because this spike
derives no safety constants (global rule 6). **No product behaviour changed:**
this is a contract fixture. The product arrival predicate stays owner-gated
under B5's 2×2, and nothing in `src/`, `configs/`, `evals/`, `tests/` or
`scripts/` was touched.

---

## 5. does_not_prove

Preserved from revision 1 and extended (README §"What this does not prove", 8
items, plus a 5-item list of product obligations this spike does **not**
discharge). In particular this card does not prove:

1. that Parcel's runtime implements any of these invariants;
2. that DDS, ROS, or a vendor controller stops a physical robot;
3. that perception is correct or the system is safe for public-space autonomy;
4. **that the latch survives a process restart** — it is in-process state on one
   object, cleared by an in-process call. A product latch must persist across
   restarts and be operator-observable;
5. **that the boot epoch is unforgeable** — `epoch` is an integer counter, not a
   signed or attested boot token, and epoch distribution is unmodelled;
6. **anything about B6's wedge class** — `speed_envelope_verdict` is
   magnitude-only and deliberately models no directional or closing relevance.
   A CLAMP here is not evidence about the product brake;
7. **that arrival is fixed** — the reserve is a contract rule with a
   caller-supplied multiplier and no hazard derivation;
8. that any threshold in the tests is a product constant — every threshold is a
   required argument precisely so none is inherited by accident, and the test
   values are illustrative;
9. that 46/46 says anything about the product. It measures this suite against
   this model. A mutant set I wrote cannot falsify invariants I failed to think
   of; the campaign's value is that the audit's set is included whole.

---

## 6. Files touched, deviations, handoffs

| File | + | − |
|---|---|---|
| `../task_1/design_spike/contracts.py` | 589 | 24 |
| `../task_1/design_spike/test_contracts.py` | 1703 | 199 |
| `../task_1/design_spike/README.md` | 75 | 11 |
| `S1_STATUS.md` (this file) | new | — |
| **Total** | **2367** | **234** |

`git status` at close shows edits from the concurrent cards (P-1's three task_1
root docs; W0-B's `control/factory.py` and `unitree_control.py`) — none of them
mine. No file under `src/`, `configs/`, `evals/`, `tests/` or `scripts/` was
touched by this card, and no frozen artifact moved.

**Deviation, disclosed.** The card specifies mutation scratch copies under
`/tmp/claude-1000/…/scratchpad/`. That filesystem hit its quota mid-card
(`EDQUOT` on every write; `/tmp/claude-1000` at ~95 GB, 92 GB of it a stale
2026-08-03 session tree from a different project). A cleanup was correctly
refused by the sandbox's destructive-action guard, so the scratch copies live in
`/home/jaewoo-jang/.cache/parcel-s1-scratch/` instead — still outside the repo,
still never writing the repo copy, which is the constraint that mattered. The
same quota broke the shell tool's own output file, so the commands above were
executed through the streaming monitor channel; all results quoted here are that
channel's stdout.

**Handoffs (not scope creep — none of these are fixed here).**

1. W0-F inherits the five product obligations listed in the spike README:
   restart-disarm on the real gateway, latch persistence across a process
   restart with an operator-facing clear, `authorize_motion` as the only path to
   a physical command, fresh 360° collision evidence for in-place search on the
   real sensor set, and the B5/B6 regressions.
2. `pose_reserve_multiplier` needs a derivation before any product port; B5's
   3.6× is evidence, not a value.
3. RC-3's directional/closing-relevance semantics are P-1's text and W0-F's
   test; the spike's envelope gate is explicitly magnitude-only so that nobody
   reads it as B6 coverage.
