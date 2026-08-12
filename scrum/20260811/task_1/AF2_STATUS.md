# AF-2 status — closing the Wave-2 audit findings (2026-08-11, task_1)

Mini-lane AF-2, executor Claude Opus. Spec:
`scrum/20260811/task_1/AUDIT_WAVE2_FABLE.md` — one BLOCKING defect and four
should-fixes dispatched to this lane. No commit made.

**Verdict: all five items CLOSED.** The BLOCKING revision-ledger usurpation is
reproduced, fixed and shown healed with the audit's own sequence plus the
pause/resume and mission-end interleavings; the verify-bypass shell is closed for
every relation with a K0 region by one derivation; FP-memory keying now fires on
the dominant refutation class; the verify reference travels with its landmark;
and the VS-5 methodology corrections are measured, not asserted — including the
independent flag-off-keyed control partition, which the claim survives.

`scripts/ci_gate.py --tier commit` **PASS — 3668 passed** (3594 lane-open baseline
+ this lane's 28 + 46 Wave-3's, attributed in §6.1), every hard gate green,
ruff `new 0`, all four frozen digest sentinels byte-identical, and the flag-off
byte-identity re-proved after the pipeline edits.

---

## 0. Contract amendments made (all with provenance, all recorded at the API)

| Contract | Amendment | Where the provenance line lives |
|---|---|---|
| **P0-C** (`instructnav/arbiter.py`) | `ProposerBus.flush_task(task_id)` — revision-NEUTRAL purge of a task's buffered proposals; `GoalArbiter.flush_task(task_id)` — its documented no-op counterpart | both docstrings cite `AUDIT_WAVE2_FABLE.md`, BLOCKING finding |
| **VS-1** (`navigation/lock_on_verify.py`) | `checkpoint_radii_m(..., relation=, arrival_band_m=)` + new `arrival_band_outer_m()`; `GroundedReference.relation` / `.arrival_band_m` | module docstring "What is verified" section + both function docstrings cite should-fix 1 |
| **VS-1** (`navigation/lock_on_verify.py`) | `GroundedReference.translated(dx, dy)` + `LockOnVerifySession.reanchor(dx, dy)` | both docstrings cite should-fix 3 |
| **VS-2** (`detection_adapter/false_positive_memory.py`) | **none — untouched.** The both-cells keying is two ordinary `record_refutation` calls from the wiring | `pipeline._lock_on_refuse` docstring cites should-fix 2 |

Nothing frozen moved: `revision.py`, `brain/executive.py`, `runtime.py`,
`instructnav/scoring.py`, `multi_view_confirm.py`, every episode set and every
`DIGEST_SENTINELS`-pinned file are byte-untouched.

---

## 1. ITEM 1 (BLOCKING) — the refusal flush usurped the revision authority

### 1.1 Reproduced first, at the contract level

`pipeline.py::_flush_lock_on_proposal` self-committed `plan_revision + 1` into
the ProposerBus and GoalArbiter ledgers. The audit's sequence, run before any
edit:

```
pre-refusal resolve:      SE2Goal(source='grounder', ..., plan_revision=1)
after refusal flush:      bus committed = 2   arbiter committed = 2   navigator stamp = 2
after runtime restamp:    navigator stamp = 1      <- runtime._apply_active_nav_revision
post-restamp buffered:    ()
post-restamp resolve:     None                     <- DEFECT REPRODUCED
```

The restamp is not hypothetical: `runtime._start_or_resume_navigation_locked`
calls `_apply_active_nav_revision(navigator)` on **every** nav start and resume
(`runtime.py:3136`) and `_accept_plan` does the same on every plan accept
(`runtime.py:1316`), both from `self._active_nav_revision` — the EXECUTIVE's
number. `CommittedRevisions.commit` takes a `max`, so the ledger never lowers:
from the first refutation onward every goal the pipeline published was stale,
`GoalArbiter.resolve` returned `None`, and the pipeline's own veto branch set
`resolution_state = "arbiter_veto"` and failed the mission — permanently.

### 1.2 The fix — revision-neutral purge

`ProposerBus.flush_task(task_id)` drops that task's buffered proposals and
leaves `CommittedRevisions` untouched; `GoalArbiter.flush_task(task_id)` is its
uniform counterpart (the arbiter holds no buffer, so it returns 0 — stated
honestly at the API rather than faked). `_flush_lock_on_proposal` calls both and
no longer touches `_active_plan_revision`. A refusal is a statement about ONE
proposal, not about the plan.

Backward compatibility: both calls are `getattr`-guarded, so a historical bundle
without the amendment withdraws nothing rather than bumping a revision — safe,
because the refusal path already releases the mission goal and resumes search.

### 1.3 Healed, same sequence

```
pre-refusal resolve:      True
after refusal purge:      dropped=1  bus committed=0  arbiter committed=0  navigator stamp=1
  refuted proposal still buffered:  False
post-restamp resolve:     (3.0, 4.0, 0.0)                       <- HEALED
stale straggler after a REAL executive correction resolves to:  None
```

The last line is the property that must not weaken: a real `plan_revision` bump
still drops a corrected-away straggler.

### 1.4 Tests pinning it (6 new, `tests/test_ve_detection_lock_on.py`)

| Test | Pins |
|---|---|
| `test_refusal_purge_is_revision_neutral_and_the_task_is_not_vetoed` | the audit's exact sequence on a REAL `DirectiveNavigator`: ledger untouched (0/0), stamp still 1, the refuted grounder proposal gone from the buffer, and a post-restamp publish resolves |
| `test_refused_mission_can_commit_again_on_the_product_path` | end to end — after a refutation the mission commits again and never sees `resolution_state == "arbiter_veto"` |
| `test_refusal_survives_pause_resume_restamp` | the pause/resume interleaving (`_start_or_resume_navigation_locked` restamps on resume) |
| `test_refusal_then_new_directive_on_the_same_task_is_not_vetoed` | mission-end → new directive under the same task and revision |
| `test_a_real_executive_revision_still_drops_stale_proposals_after_a_refusal` | P0-C is not weakened: rev-1 straggler `None`, rev-2 wins |
| `test_flush_task_clears_the_buffer_without_moving_the_ledger` | the amended API itself, including "the same revision may buffer and win again immediately" and "a stale one still cannot" |

One existing assertion was corrected in place:
`test_verify_on_approach_refutes_a_detection_with_nothing_behind_it` asserted
`_active_plan_revision == revision_before + 1` — i.e. it *pinned the defect*. It
now asserts `== revision_before` and that both sinks' committed revision is
still 0, with a comment naming the audit.

`tests/test_p0c_proposal_flush.py`, `tests/test_p0c_flush_product_path.py`,
`tests/test_instructnav_arbiter.py`, `tests/test_brain_executive.py`,
`tests/test_resume_transaction.py`: **32 passed**, unchanged.

---

## 2. ITEM 2 — the verify-bypass shell (VS-1 contract amendment)

### 2.1 The defect, measured per operating point

The checkpoint schedule was the near-object envelope — which is the **near**
relation's arrival band, not every relation's. Measured shell widths (K0's outer
band edge minus the envelope's outermost radius):

| anchor | envelope outermost | `next_to` outer (R+1.5) | shell | `towards` outer (2.5) | shell |
|---|---|---|---|---|---|
| bare object R=0 | 1.32 | 1.50 | **+0.18** | 2.50 | **+1.18** |
| lamppost R=0.06 | 1.32 | 1.50 | **+0.18** | 2.50 | **+1.18** |
| tree R=0.25 | 1.57 | 1.75 | **+0.18** | 2.50 | **+0.93** |
| building R=1.2 | 2.82 | 2.70 | −0.12 | 2.50 | −0.32 |

The `next_to` shell is exactly the audit's 0.18 m and is **anchor-independent**
(the band is surface-anchored, so R cancels) — which is why it never showed up
at scale. A big anchor's near envelope already reaches past both bands, so the
bypass is anchor-size dependent.

### 2.2 The amendment

`checkpoint_radii_m` gains `relation=` and `arrival_band_m=` and prepends the
active relation's K0 outer band edge **when, and only when, it lies outside the
envelope's outermost radius**. Strictly additive: the envelope's own three
values stay bit-identical and stay in order, an omitted `relation` reproduces the
pre-amendment schedule exactly, and an outer edge inside the envelope inserts
nothing. One derivation closes `towards`, `next_to` and the metadata
`relative_band` `near` override together.

No literal is restated: `arrival_band_outer_m` reads `TOWARDS_BAND_M`,
`next_to_band_from_centre` and `object_near_envelope_m` from
`instructnav.scoring` by reference, and
`test_arrival_band_outer_is_k0s_own_band_by_reference` pins it `struct.pack`-
equal to `arrival_goal_region_for_relation`'s own `band_m[1]` at every operating
point. The AST no-literal audit
(`test_module_states_no_geometry_constant_of_its_own`) stays green.

The wiring passes the relation AND, when K0 built a band-shaped arrival region
for that very commit, that region's band verbatim —
`pipeline._arrival_band_for_commit` reads it off `_build_arrival_goal_region`,
the single place the pipeline builds the region K0 verifies arrival against, so
the two cannot disagree.

### 2.3 GATE — no K0 arrival point has zero checkpoints due, for EVERY relation

`test_property_no_k0_arrival_point_has_zero_checkpoints_due`: for each of
`near`, `towards`, `next_to`, `inside` × each of the four operating points, a
radial sweep (2 401 probe points per case, two bearings, out to 6 m) finds
**zero** points that `GoalRegion.contains` accepts and for which no checkpoint is
due. Region (`inside`) is checked on the polygon itself.

Non-vacuity — `test_seeded_violation_kills_the_no_dead_zone_property` runs the
same oracle against the PRE-amendment schedule and requires a non-empty dead
zone at every operating point whose shell is positive (6 of 8) and an empty one
where the envelope already covers (2 of 8, the building anchor).

The audit's exact repro is pinned by name:
`test_the_audit_next_to_shell_now_fails_closed` asserts `contains(R+1.45)` is
True, that the envelope-only schedule has **no** checkpoint at that range, that
the shell is `0.18` to 1e-9, and that the amended schedule leads with `R+1.5` and
has a checkpoint due. `test_the_towards_bypass_that_produced_ph31_is_closed`
does the same at PH-31's measured 2.4699 m.

### 2.4 GATE — PH-31 flag-ON now runs the identity re-check

`nav-object_goal-PH-31-2dab201e` ("walk towards the tree"), v4s, `--mode
candidate`, `scaled-path-v1`, `max_steps 200`, seed 20260811,
`hold-or-trace-end-v1`, flags `detection_lock_on` + `lock_on_verify_on_approach`,
**one fresh world per arm**. Both arms on the SAME tree; the pre-AF-2 arm is the
envelope-only schedule restored by monkeypatch, so the two differ by exactly this
amendment.

| | pre-AF-2 | AF-2 |
|---|---|---|
| grounded reference | `lamp_post_1`, label `lamppost`, for the query `tree` | identical |
| terminal relation / K0 band | `towards`, `[0.6, 2.5]` | identical |
| **checkpoint schedule** | `[1.32, 1.12]` | **`[2.5, 1.32, 1.12]`** |
| verify verdicts observed | `baseline_view`, `view_not_independent`, `approaching` — **`approach` only, no checkpoint ever due** | the same three, then **`identity_recheck_failed_at_checkpoint` → REJECTED** |
| refutations / suppressions | 0 / 0 | **1 / 2** |
| `system_arrival` | **True** | **False** |
| authority category | **`false_arrival`** | **`agreement`** |
| terminal reason | `arrived_verified` | `semantic_target_not_found` |
| final dtg | 4.140305462818843 | 4.140305462818843 |

**Reported honestly, because the outcome is better than the gate asked for.**
The gate was "verify ENGAGES", and it does: the K0 outer band edge (2.5 m) leads
the schedule, becomes due at exactly the range W2_WIRE1_STATUS.md §7 measured the
robot stopping at, and the identity re-check runs for the first time. It then
FAILS — the alias fallback's own score for `tree` against a `lamppost` label is
below the operating point, which is precisely what §7 predicted would happen if
the check ever ran ("it would have scored 'tree' vs 'lamppost' at 0.0 … and
refuted"). The mission then re-encounters the same hypothesis twice and VS-2's
memory suppresses it both times: commit → refute → re-encounter → suppress, on an
episode that previously ended in a phantom arrival.

The robot ends in the same place (dtg identical to 13 significant figures). What
changed is that it no longer CLAIMS to have arrived. **This does not fix
grounding** — a lamppost is still admitted for a "tree" query, which is upstream
of everything this lane owns and is owner decision-queue item 4 (SigLIP
default-on). And this is one episode in isolation: it is not a re-run of VS-4's
gate (4).

---

## 3. ITEM 3 — FP-memory keying at BOTH cells

### 3.1 The defect

Refinement refusals recorded at the ESTIMATE's cell
(`_lock_on_admission_guard` passed `estimate.position`) while the admission
guard CONSULTS at the CANDIDATE's cell (`(result.x, result.y)`). The FP cell is
1 m and `consult` checks the 3×3 neighbourhood, so a wrong reference more than
~1–2 m from its estimate was re-committed and re-refuted until the replan ladder
was spent. Live corroboration in W2_WIRE1_STATUS.md §7: **24 refutations, 1
suppression** across 180 episodes, 23 of the 24 being exactly this class.

### 3.2 The fix — the wiring, not the pure module

`_lock_on_refuse` gains `reference_xy=` and writes the refutation at both the
estimate's cell and the grounded candidate's cell. VS-2's contract is untouched:
these are two ordinary `record_refutation` calls, and the second is **skipped
when both points fall in the same key**, so one refutation can never reinforce
(and so double the TTL horizon of) a single entry. A new counter
`lock_on_refutation_cells` makes the difference observable.

`_lock_on_reference_xy` supplies the candidate cell at the verify site: an
object's centre, a region's polygon centroid — the same point the semantic map
hands the grounder as a region candidate's `(x, y)`.

### 3.3 GATE

`test_a_refuted_wrong_reference_is_not_immediately_recommitted` builds the
audit's scenario exactly — estimate on `lamp_post_2` at (2, 0), grounding hands
`lamp_post_1` at (6, 0), 4 m apart and provably in different keys — refutes, and
then re-grounds the SAME wrong reference: `lock_on_suppressions == 1`,
`mission.goal is None`. Pre-AF-2 that second call re-committed.
`test_one_refutation_never_reinforces_a_single_cell_twice` is the co-located
control: `refutation_cells == 1`, one entry, `refutations == 1`.

`tests/test_false_positive_memory.py` (VS-2's own suite, including the
never-resurrects property): **8 passed**, unchanged.

### 3.4 GATE — the live counter imbalance, measured before and after

Protocol: v4s, `--per-axis 20` (n = **60**), `--mode candidate`,
`scaled-path-v1`, `max_steps 200`, seed 20260811, `hold-or-trace-end-v1`, flags
`detection_lock_on` + `lock_on_verify_on_approach`, **one fresh world per episode
per arm**. Both arms on the SAME tree; `pre_af2` restores the pre-audit behaviour
of all three code items by monkeypatch, so the arms differ by exactly items 2+3+4
and nothing else.

| axis | n | arm | refutations | refutation CELLS | **suppressions** | authority `false_arrival` | `system_arrival` claims |
|---|---|---|---|---|---|---|---|
| `LA` | 20 | pre-AF-2 | 5 | 5 | **0** | 3 | 3 |
| `LA` | 20 | AF-2 | 5 | 9 | **4** | **2** | **2** |
| `BB` | 20 | pre-AF-2 | 3 | 3 | **0** | 1 | 1 |
| `BB` | 20 | AF-2 | 3 | 5 | **4** | **0** | **0** |
| `PH` | 20 | pre-AF-2 | 7 | 7 | **0** | 6 | 6 |
| `PH` | 20 | AF-2 | 7 | 11 | **10** | **3** | **3** |
| **all** | **60** | **pre-AF-2** | **15** | **15** | **0** | **10** | **10** |
| **all** | **60** | **AF-2** | **15** | **25** | **18** | **5** | **5** |

**The gate: the imbalance direction the audit measured (24 refutations, 1
suppression) improves decisively — 15 : 0 becomes 15 : 18** on the same cells,
with the same 15 refutations. 10 of the 15 refutations now write TWO cells
instead of one (25 cells vs 15), which is the estimate/candidate separation the
audit named, and every one of the 18 suppressions is a commit the pre-AF-2 arm
made and then had to refute again.

Secondary, not pre-registered: authority `false_arrival` **10 → 5** and
`system_arrival` claims **10 → 5**. Five episodes change outcome, all with the
same signature — `false_arrival`/`True` → `agreement`/`False`, refutations 0 → 1,
suppressions 0 → 2: `LA-16`, `BB-13`, `PH-11`, `PH-16`, `PH-17`, i.e. PH-31's
mechanism (§2.4) reproducing at axis scale. SR is 0.000 in both arms on all three
axes, as it is for every arm ever run on these cells; **no SR claim is made**.

### 3.5 Which item did what — a third arm, so the attribution is measured

The two arms above differ by items 2+3+4 together, which cannot separate them. A
third arm restores ONLY item 3's pre-audit keying (schedule amendment and
re-anchor still on), same 60 cells, same isolation:

| arm | refutations | refutation CELLS | suppressions | authority `false_arrival` |
|---|---|---|---|---|
| pre-AF-2 (none) | 15 | 15 | 0 | 10 |
| AF-2 **minus item 3** (schedule + re-anchor only) | **20** | 20 | 10 | **5** |
| AF-2 (all three) | **15** | **25** | **18** | **5** |

Read straight off:

* **Item 2 owns the false arrivals.** The checkpoint-schedule amendment alone
  takes `false_arrival` 10 → 5 and adds 5 refutations (15 → 20) — the K0 outer
  band edge becoming due where nothing was due before. Item 3 adds none of that.
* **Item 3 owns the memory economics, and it works in both directions.** It adds
  10 cells beyond the refutation count (25 cells for 15 refutations), raises
  suppressions 10 → **18**, and *lowers* refutations 20 → **15**: five
  commit → refute cycles never happen at all, because the candidate's own cell
  was already suppressed when it was re-grounded. That is precisely the "burning
  the replan ladder" the audit described, measured being un-burnt.
* **Item 4 contributes nothing here, as expected** — `lock_on_reanchors` is 0 on
  every episode of every arm. The static sim never drifts (§4.3).

---

## 4. ITEM 4 — the verify reference travels with its landmark

### 4.1 The defect

`_reanchor_landmark_goal` re-derived the goal, the arrival region and
`candidate_position` from a fresh sighting of the same landmark, but left the
verify session's `GroundedReference` at its pre-drift geometry. Under real frame
drift the object gate would then measure a healthy estimate against a stale
centre, refute a good commitment, and — because of item 3 — write negative
evidence AT THE TRUE TARGET, self-suppressing it for the whole TTL horizon.

### 4.2 The fix

`GroundedReference.translated(dx, dy)` (pure, frozen dataclass, geometry only —
`landmark_id`, `label`, `radius_m`, `relation`, `arrival_band_m` carried
verbatim) and `LockOnVerifySession.reanchor(dx, dy)`, which swaps the reference
and **keeps every verdict**: cleared checkpoints stay cleared, the covariance
baseline and the admitted/fresh history stay as they are. A frame correction is
not evidence about the target. The pipeline calls it inside
`_reanchor_landmark_goal`, in the same transaction as the goal, the region and
the candidate; flag-off the session is `None`, so the branch cannot run.

### 4.3 GATE — the drift test, paired

`test_reanchor_translates_the_verify_reference_in_the_same_transaction`. Commit
a lamppost at (4, 0); drift the frame by **2.0 m** (≫ `REGION_DILATION_M` =
0.05, and outside the 1.38 m vicinity band); re-anchor; one verify tick.

| | reference TRANSLATED (AF-2) | reference LEFT BEHIND (pre-AF-2 control) |
|---|---|---|
| refutations | **0** | **1** (`fused_point_outside_vicinity_band`) |
| mission goal | retained, moved to the drifted anchor | **released** |
| FP-memory entries | **0** | 2 |
| true target suppressed | **False** | **True** |

The control is the audit's self-suppression scenario, and it is now pinned dead.
Also asserted: goal, `arrival_goal_region.center` and `candidate_position` all
moved to the drifted anchor, the session survived, the landmark id and the
checkpoint schedule are unchanged.

**Honest scope note.** Real frame drift moves the MAP, so a fresh sighting and
the estimate perception rebuilds from it are both in the drifted frame; the test
models that by re-acquiring the D2 estimate at the drift instant. Without that,
the Kalman prior lags a 2 m jump and BOTH arms refute on the transient — a
property of this static harness's estimator (its post-commit covariance is tight
enough that any landmark movement fails the Mahalanobis clause), not of the
defect. Measured and recorded rather than hidden: the static sim never drifts, so
this fix is hardware-relevant and its live-arm footprint is zero.
`test_translated_moves_geometry_and_nothing_else` and
`test_reanchor_keeps_every_verdict_the_session_has_reached` pin the pure half.

---

## 5. ITEM 5 — VS-5 methodology + docs (no behaviour change)

### 5.1 (a) The independent control partition — measured

**The circularity, stated.** W2_WIRE2_STATUS.md §4.3 partitions the episodes by
`evidence_count == 0` read from the FLAG-ON arm's own note telemetry — the arm
under test naming its own control group.

**The control the auditor specified.** A FLAG-OFF replay carrying a shadow
`ValueEvidencePolicy`, evaluated on the same grounding ingress the paint would
read, writing into no map and read by no decision. The partition is therefore
derived from the flag-off arm alone.

Protocol: v4s, `--per-axis 20` (n = **60**, above the ≥20 the audit asked for),
`--mode candidate`, `scaled-path-v1`, `max_steps 200`, seed 20260811,
`hold-or-trace-end-v1`, **one fresh `NavInstructRunner` — hence one fresh world
and one fresh scan RNG — per episode per arm**.

| measurement | result |
|---|---|
| flag-off-derived partition | 33 zero-evidence / 27 evidence-carrying |
| zero-evidence episodes whose DECISIONS are identical to flag-off | **33 / 33** |
| zero-evidence episodes whose RAW persisted rows are identical | **0 / 33** — see the exclusion below |
| evidence-carrying episodes whose decisions moved | 4 / 27 |
| flag-off-derived partition vs the flag-on telemetry partition | **0 disagreements** across all 60 |

Three findings, all recorded into `W2_WIRE2_STATUS.md` §4.3:

1. **The note-channel exclusion must be stated in the claim.** "Bit-identical"
   reads as row-level byte equality and is not: under the flag every non-terminal
   searching command carries this card's own `|value_map=evidence=…` telemetry
   suffix, so 0 of 33 rows are byte-equal as persisted and 33 of 33 are identical
   once the suffix is stripped. The claim that holds is *decisions* — every trace
   field except the note-channel suffix the card itself appends.
2. **The circular partition was not wrong, only circular.** The two partitions
   are the same set, episode for episode, on all 60.
3. **A whole-arm partition cannot attribute a per-episode difference.** Run as
   two single-process 60-episode arms, the same comparison shows **4 apparent
   violations** (`BB-06`, `BB-07`, `BB-13`, `PH-16`) — all four decision-identical
   under isolation. They are VS-4 §5's shared `HeadlessCityWorld._scan_rng`
   carried over from the 4 earlier episodes that legitimately moved.

**The scan-viewpoint side channel, documented and verified inert.** Under the
flag the scan path does two things flag-off does not, neither gated by
`evidence_count`: `_publish_scan_viewpoint` publishes an `SE2Goal`
(`SCAN_PROPOSER_SOURCE`) into the shared `ProposerBus` and latches the
`GoalArbiter`'s active plan step; and `choose_next_look` may enqueue a value look
that moves the body. Both are inert while the map holds no evidence, structurally
and empirically —
`test_the_scan_viewpoint_side_channel_cannot_steer_an_evidence_free_episode`
pins that C2 returns COMMIT (so `LOOK` is never requested), that the published
goal IS in the shared buffer (so the guard is not vacuous), and that it cannot
reach a decision: every `goal_arbiter.resolve` site in `pipeline.py` sets its own
plan step immediately before resolving over a single-element tuple it has just
built, and the pipeline never calls `proposer_bus.poll()`. The 33/33 above is the
empirical half. **Not a delegation bug**, therefore no fix was needed — but it is
recorded as a latent seam: a future caller that polls the shared bus would put
the scan viewpoint inside arbitration, where the empty-map delegation does not
reach it.

### 5.2 (b) Digest hygiene — the actual reproducing recipes

The audit is right on both counts, and both are now fixed at the source and
pinned by `tests/test_nav_instruct_digest_recipe.py` (6 cells).

1. **The documented exclusion set is INCOMPLETE.** `{report_id, elapsed_s,
   scene, navigator_flags}` is four fields; the recipe that produces
   `ee234c63…` drops a fifth, **`refreeze_provenance`**. With the four
   documented fields the digest is `200f5653706c4aea…`.
2. **`aggregate.scene` is a second, ABSOLUTE copy of the scene path** that the
   top-level `scene` exclusion does not reach, so the `ee234c63…` form is
   path-dependent by construction (VS-4 §4 got this right).
3. **The serializer was never stated, and it is the whole difference between the
   two lanes' published numbers.** `json.dumps(..., sort_keys=True)` at DEFAULT
   separators gives VS-4's `897d6ce7…`; compact separators give VS-5's
   `c172da37…`. Same content, same exclusion set. Neither lane was wrong.
4. **Both episodes-payload shas reproduce** — VS-4 sorted the rows by
   `episode_id` first (`bfb21cd2…`, default separators); VS-5 kept report order
   (`440fd884…`, compact). The report's own order is grouped by family, not
   sorted, which is why the two differ before the separators do.

All five values plus the in-report `episode_digest` `4113607b…` were re-derived
from the committed frozen row and are now regression-pinned. Corrections written
into `W1_D15_STATUS.md` (gate row 1) and `W2_WIRE1_STATUS.md` §4 (full recipe
block), with the completing note in `W2_WIRE2_STATUS.md` §4.1.

### 5.3 (c) The matcher arm is pinned next to the cells

New `evals/nav_instruct/episodes/V4S_MATCHER_ARM.md` (a new file — no manifest,
no frozen artifact touched) states: the "unfindable flag-off" property holds in the
**default (string/alias fallback)** arm; with `PARCEL_SIGLIP2_ONNX=1` the **LA
flag-off baseline is SR 0.100 (6/60) with 0 false arrivals**, against 0.000 with
10 in the default arm; `BB`/`PH` are 0.000 in both. It also records the two
harness facts every per-episode claim on these cells depends on (the shared scan
RNG, and ~8 m planner reach vs ~12 m sensing). The same correction is inserted
into `W2_EVAL_STATUS.md` §3's "What this does and does not say".

It lives BESIDE `episodes/v4s/` rather than inside it, and that is a measured
constraint, not a preference: `test_checked_in_v4s_files_equal_a_fresh_generation`
pins the directory's file LIST byte-for-byte against a fresh generation, so a
`README.md` inside `v4s/` turns that gate red (observed, then moved). The
manifest is the other in-directory option the brief offered and it is
content-pinned by the same suite, so neither was available.

### 5.4 (d) The loud construction warning

`DirectiveNavigator.__init__` now logs a WARNING when `detection_lock_on` is on
and `lock_on_verify_on_approach` is off. It names the V-E defect (wrong-instance
commit against a silently rewritten goal, the measured dtg 4.7785 m false
arrival on `nav-region_goal-B-05`, v4 minival SR 0.32 → 0.24 with 2 episodes
lost), names the fix, and names **owner decision-queue item 6** as the place the
hard-refusal question belongs. It does **not** refuse:
`test_lock_on_without_verify_warns_loudly_but_is_not_refused` pins that the arm
still constructs, that the message carries the defect name and the audit
reference, and that neither the correct combination nor the flag-off default
warns.

---

## 6. Verification

### 6.1 `scripts/ci_gate.py --tier commit`, 2026-08-11T18:11:49Z (final)

```
[  PASS] HARD  ruff                       7 violation(s), baseline 7, new 0
[  PASS] HARD  hard-safety                nav frozen baseline …v4-20260811T070536Z: collisions=0
                                          false_arrival=0 | mutation panel clean | freshness ok |
                                          follow-bench 7 rows hard_collision_total all 0 | walk_with_me ok
[  PASS] HARD  frozen-digest-sentinels    4 immutable manifest(s) byte-identical to pin
[  PASS] HARD  latency-tail-ledger        6 metric series within 1.2x tail ceiling
[  PASS] HARD  follow-bench-jerk-ratchet  1.2187 <= 1.46244
[  PASS] HARD  model-off-non-inferiority  23 passed
[  PASS] HARD  frozen-digest-integrity    6 passed
[  PASS] HARD  mutation-panel-freshness   2 passed
[  PASS] HARD  latency-tail               6 passed
[  PASS] HARD  default-suite              3668 passed, 9 skipped, 36 deselected
RESULT: PASS — every hard gate green.   elapsed 133.9s
```

**Suite delta, attributed.** Lane-open baseline (Wave-2's landed state) **3594**.
This lane adds exactly **28**:

| file | before | after | + |
|---|---|---|---|
| `tests/test_ve_detection_lock_on.py` | 21 | 32 | +11 |
| `tests/test_lock_on_verify.py` | 29 | 38 | +9 |
| `tests/test_nav_instruct_digest_recipe.py` | — | 6 | +6 (new file) |
| `tests/test_value_directed_search.py` | 28 | 30 | +2 |

3594 + 28 = **3622**. The remaining **46** are **Wave-3's**, which runs
concurrently on this tree and has `src/parcel_robot/navigation/follow.py`,
`evals/companion_nav/scenarios.py`, `evals/companion_nav/runner.py`,
`evals/companion_nav/metrics.py` and `evals/companion/duplex_v1/` open. **This
lane touched none of them**, and every one of AF-2's own 28 cells passes in
isolation (`188 passed` over the lock-on / P0-C / arbiter / value-map / digest /
FP-memory selection). `ruff check` over the five touched source and test files:
**All checks passed**; the tree ratchet stays `new 0`.

**One red, found and fixed, recorded because it happened.** The first ci_gate run
of this lane failed `tests/test_v4s_search_cells.py::test_checked_in_v4s_files_equal_a_fresh_generation`
— AF-2's item 5(c) README had been written INSIDE `evals/nav_instruct/episodes/v4s/`,
whose file list is pinned byte-for-byte against a fresh generation. The file was
moved to `episodes/V4S_MATCHER_ARM.md` (beside the directory, not in it) and the
gate is green. Attributed to this lane, not to Wave-3.

### 6.2 Flag-off byte-identity, re-proved after the pipeline edits

Protocol: v4 minival, `scaled-path-v1`, `max_steps 200`, seed 20260804, in a
scratch rsync outside the tree, no in-tree ledger row, at this lane's FINAL
source state.

```
--mode candidate (the arm the brief names):
  report digest (VS-5 recipe)  58aa1aa1643fca94879d4178568662d45c9edacf976689e3c7173ab4dd91358c
                               == W2_WIRE2_STATUS.md §4.1's pre- and post-VS-5 value, exactly

--mode baseline (the frozen row):
  episode rows byte-equal      25 / 25
  episode_digest               4113607b92c734dfdd46004b6e77baf6575fc2a1c493e5d9dc5a12c6c5490222  (unmoved)
  report digest ee234c63…      reproduced exactly (aggregate.scene substituted, §5.2)
  path-independent 897d6ce7…   fresh == frozen
  path-independent c172da37…   fresh == frozen
  episodes payload bfb21cd2…   reproduced   (rows sorted by episode_id, default separators)
  episodes payload 440fd884…   reproduced   (report order, compact separators)
```

Every branch AF-2 touches is behind `lock_on_verify_on_approach` (which cannot be
True unless `detection_lock_on` is) except `_flush_lock_on_proposal`'s call
sites, which are themselves only reachable from that flag's refusal path. The
`_reanchor_landmark_goal` addition is guarded by `self._lock_on_verify is not
None`, which is `None` flag-off. Frozen digests: 4/4 sentinels byte-identical, and
no episode set, manifest or ledger row was written.

### 6.3 Files touched

**Edited (in OWNS):** `src/parcel_robot/navigation/pipeline.py`,
`src/parcel_robot/navigation/lock_on_verify.py`,
`src/parcel_robot/instructnav/arbiter.py`,
`tests/test_ve_detection_lock_on.py`, `tests/test_lock_on_verify.py`,
`tests/test_value_directed_search.py`.

**New (in OWNS):** `tests/test_nav_instruct_digest_recipe.py`,
`evals/nav_instruct/episodes/V4S_MATCHER_ARM.md`,
`scrum/20260811/task_1/AF2_STATUS.md`.

**Status docs corrected (named by the brief's item 5):**
`scrum/20260811/task_1/W1_D15_STATUS.md`,
`scrum/20260811/task_1/W2_WIRE1_STATUS.md`,
`scrum/20260811/task_1/W2_WIRE2_STATUS.md`,
`scrum/20260811/task_1/W2_EVAL_STATUS.md`.

**In OWNS, NOT edited:**
`src/parcel_robot/detection_adapter/false_positive_memory.py` (VS-2's contract
was sufficient — §3.2), `src/parcel_robot/navigation/detection_lock_on.py`
(nothing the fixes need lives there).

**Untouched, as required:** `runtime.py`, `navigation/follow.py`,
`navigation/reactive_safety.py`, `evals/companion_nav/**` (Wave-3's lane),
`core/**`, `brain/executive.py`, `revision.py`, `instructnav/scoring.py`,
`multi_view_confirm.py`, `configs/**`, every episode set and manifest, every
`DIGEST_SENTINELS`-pinned file, `evals/nav_instruct/results/ledger.jsonl`.

**No commit made.** Every eval arm ran in a scratch rsync outside the tree.

### 6.4 Handoffs / notes for the next card

1. **The failed-mission session lifecycle** (audit Notes) is still open:
   ladder-spent branches leave the verify session alive on a failed mission.
   Harmless under current callers (`start()` clears it), untouched here.
2. **`GoalArbiter.flush_task` is a uniform no-op today.** If the arbiter ever
   buffers, that is the seam that must clear it.
3. **The scan viewpoint sits in the shared ProposerBus** and is only inert
   because the pipeline never polls it (§5.1). A future caller that polls would
   put it inside arbitration, outside the empty-map delegation.
4. **The estimator lags a landmark re-anchor** (§4.3): the post-commit D2
   covariance is tight enough that any landmark movement fails the Mahalanobis
   clause on the transient. Invisible in a static sim; on hardware the re-anchor
   and the estimate would want to move in one transaction. Filed, not fixed —
   `detection_lock_on.py`'s estimator is the right owner and no measurement here
   justifies touching it.
5. **Owner decision-queue item 6** now has its warning (§5.4). The hard-refusal
   question is unchanged and still owner-gated.

---

## 7. `does_not_prove`

* **No SR claim.** Nothing in this lane is offered as a success-rate
  improvement. The one live conversion measured (PH-31's false arrival becoming
  an honest not-found) is a change of failure CLASS.
* **No real-camera evidence.** Persistence is still depth support against a
  simulator whose distractors have no body; the identity re-check still runs
  against the alias fallback unless `PARCEL_SIGLIP2_ONNX=1`. Item 2's gate is
  that verify ENGAGES, and that is what is claimed.
* **Item 4 has no live footprint.** The static sim never drifts, so the
  re-anchor translation changes nothing measurable on any eval arm; its evidence
  is the paired unit control in §4.3 and it is hardware-relevant, not
  sim-demonstrated.
* **The dead-zone property is about the SCHEDULE, not about arrivals.** It
  proves a checkpoint becomes due inside every K0 arrival region. It does not
  prove the checkpoint refutes anything — that depends on the evidence the tick
  carries, and in a T0 arm that evidence is the oracle frustum.
* **The control partition is n = 60 on v4s**, one axis-slice of the 180-cell
  set, and it establishes the delegation contract, not an effect. VS-5's effect
  gate remains FAILED and its STOP stands untouched.
* **`GoalArbiter.flush_task` does nothing today.** It is a uniform seam, and
  says so. The whole of item 1's purge is the ProposerBus half.
* **The digest pins are hygiene, not navigation.** A legitimate re-freeze moves
  every one of them; the test skips when the frozen row is absent.
