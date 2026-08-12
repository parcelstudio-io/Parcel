# W2-WIRE1 status — card VS-4 (2026-08-11, task_1)

Lane W2-WIRE-1, executor Claude Opus. One card from the authoritative record
`scrum/20260811/task_1/FOLLOWUP_DESIGNS.md` (§0, §2, §6 card block "Card
VS-4"): **arrival-integrity + verify-on-approach wiring**, Wave-2 pipeline.py
slot 1. No commit made.

**Verdict: 4 of the 5 gate clauses PASS; gate (4) is a partial — its two
non-vacuity conjuncts PASS for the first time, its zero-phantom-arrivals
conjunct FAILS with the SAME two episodes as the flag-off arm.** Per the
pre-registered rule ("pass all three or report the honest numbers and STOP")
this lane STOPS on that conjunct and reports the measured root cause of each of
the two episodes (§7). No mechanism was invented to force the number.

---

## 1. Gate table (all measured)

| Card gate clause | Result |
|---|---|
| (1) flag-OFF control (both new nav flags absent) byte-reproduces the committed v4 frozen-baseline row | **PASS, bit-for-bit.** 25/25 episode rows byte-equal, `episode_digest` `4113607b…` unmoved, D15-B's report digest `ee234c6376d63dbfb9c1ffa1eb8d7333ac9fcfd57bc62495795cbe7010fa70f8` reproduced exactly (§4) |
| (2) `detection_lock_on`+`lock_on_verify_on_approach` arm on the frozen v4 minival: `false_arrival == 0` AND paired episodes lost == 0 AND per-tier \|SR_lock − SR_off\| ≤ 0.10 | **PASS.** false_arrival 1 → **0**; lost **0**; per-tier delta **0.000 on all five tiers**; SR 0.32 → 0.32. The pre-VS-4 lock-on arm on the same tree reproduces the card's "1 false arrival, 2 lost" (§5) |
| (3) structural pytest: arrival-region provenance == grounded reference; interchangeable commit == the flag-off ranking's instance | **PASS**, 7 new tests in `tests/test_ve_detection_lock_on.py`; plus the end-to-end B-05 measurement (§6) |
| (4) v4s phantom cells flag-on: zero phantom arrivals AND ≥1 commit-then-refutation AND ≥1 FP-memory suppression | **PARTIAL — STOP-and-report.** commit-then-refutation **1** (was 0), FP suppression **1** (was 0) — both conjuncts pass, both measured live from traces. Phantom arrivals **2**, the same two episodes as flag-off, neither caused by this wiring (§7) |
| (5) model-off-non-inferiority green; ci_gate green | **PASS** — `scripts/ci_gate.py --tier commit`: every hard gate green, 3575 passed (§10) |
| non-vacuity of the wiring itself (dispatch requirement) | **PASS** — 207 verify sessions, 26 671 approach views, states `approach`/`verify`/`verified`/`rejected` all observed on the v4s arm; 16 sessions / 1 120 views on the v4 minival (§8) |

Baseline at lane open, verified fresh before any edit: `scripts/ci_gate.py
--tier commit` **PASS**, 3568 passed, ruff 7 = baseline 7 / new 0.

---

## 2. What landed

| Deliverable | Where | What it is |
|---|---|---|
| the wiring | `src/parcel_robot/navigation/pipeline.py` (+490-line VS-4 block, plus 6 guarded call sites) | flag, deference, commit guard, verify-on-approach tick, refusal path, P0-C flush, telemetry |
| session integration seam | `src/parcel_robot/navigation/detection_lock_on.py` `+165 −30` | `LockOnEstimate`, `fuse_view(...)`, `_ingest_measurement(...)` (extracted from `observe`, called by both) |
| allowlist | `evals/nav_instruct/runner.py` `+13 −4` | one name, `lock_on_verify_on_approach` |
| pin move (declared) | `tests/test_e4_evidence_seams.py` `+15 −6` | the e4 closed-set pin, one name, comment naming the card — D15-B's precedent repeated verbatim |
| pin move (declared, out of OWNS) | `tests/test_person_aware_nav.py` `+3 −1` | `len(ALLOWED_NAVIGATOR_OVERRIDES) == 3` → `== 4`, count kept EXACT (§9) |
| tests | `tests/test_ve_detection_lock_on.py` `+342` | 7 new cases (existing 14 untouched and still green) |

`src/parcel_robot/navigation/instructnav_recovery.py` is in the card's OWNS and
was **not** edited: nothing the design needs lives there (the recovery ladder is
reached through `_begin_semantic_replan`, which is pipeline.py's).

---

## 3. The architecture, as wired

Everything below is conditional on `lock_on_verify_on_approach`, which can only
be True when `detection_lock_on` is (`pipeline.py` `__init__`). The
unconditional path is byte-identical — proved, §4.

**(a)(i) Deference.** With the flag on, the searching path no longer enters
`_try_detection_lock_on` at all. The lock-on session still observes every tick
(`_lock_on_observe_estimate`), fusing D2 and running its M-of-N, but the
INSTANCE is chosen by the same authority the flag-off arm uses: the grounder's
ranking, and for interchangeable (region / "nearest") queries the scan-complete
boundary-aware ranking. There is no longer a second commit door for perception
to walk through. This is what closes the measured B-05 wrong-instance commit
(§6), and it is why the flag-ON arm can never lose an episode to a lock-on
budget exhaustion the way the pre-VS-4 arm does (§5).

**(a)(ii) Reference/estimate separation.** Because the commit now always
carries the GROUNDED candidate, `arrival_goal_region`, `goal_landmark_id`,
`candidate_position` and `target_polygon` are the grounded instance's, by
construction rather than by inspection. The fused estimate moves nothing except
what the D3 session already proposes through the existing propose/dispose seam.
Pinned by `test_committed_arrival_region_provenance_is_the_grounded_reference`.

**(a)(iii) Refinement gate at every commit.** `_lock_on_admission_guard` runs at
the head of `_commit_semantic_candidate` — i.e. on EVERY commit door, not just
the lock-on one. It (1) consults VS-2's `NegativeEvidenceMemory` at the
candidate's place and refuses a suppressed hypothesis, then (2) runs VS-1's
per-kind `refinement_gate` on the current D2 estimate against the grounded
reference and treats a rejection as a REFUTATION: negative evidence written,
proposal flushed, search resumed.

**(b) Verify-on-approach.** `_begin_lock_on_verify` opens a
`LockOnVerifySession` on the committed reference; `step()` calls
`_verify_lock_on_on_approach` before anything acts on the goal — terminal
verification included, so a proposal refuted on the doorstep cannot claim an
arrival. One `ApproachView` per tick:

* `fused_xy` / `covariance` — the D2 estimate, refreshed through the new
  `DetectionLockOnSession.fuse_view` seam (the pre-existing `observe` returns
  `None` forever once committed, which is the "no re-verification on approach"
  half of the measured defect).
* M-of-N admission — VS-1's `admits_for_confirmation`, the record's
  independent-evidence rule consumed by reference. It gates the CONFIRMER only;
  D2 keeps fusing every view, because covariance shrink under closing range is
  what the checkpoints ask about.
* `identity_score` — the SigLIP re-check through the session's own matcher seam.
* `persistence` — **interpretation recorded, §11.1**: for an OBJECT reference,
  the pipeline's own stratum-2 association between the detection and the RANGE
  channel (`_target_clearance`, which returns `None` when no LiDAR return's ray
  geometry belongs to the tracked target). A REGION has no depth signature, so a
  region reference persists on the semantic channel alone.

**Refusal path** (`_lock_on_refuse`): write the `NegativeEvidence` VS-1 emits
into VS-2's memory → flush the proposal through the P0-C revision seam
(`commit_revision` on both the ProposerBus and the GoalArbiter, and the
navigator's own stamp moves with it) → reset the D3 hypothesis → resume search
through the existing `_begin_semantic_replan` funnel; when the replan ladder is
spent, fail through the existing not-found exit. **The refuted instance is NOT
added to `_unreachable_candidates`**: a refutation is evidence about a
hypothesis at a PLACE, and VS-2's memory is what carries it — excluding the id
would make the re-encounter unobservable, which is precisely the suppression the
design wants (and it is how the one measured suppression happened, §7).

**K0 untouched.** No epsilon widened, no arrival reason added, no goal
special-cased, no second arrival predicate. Every branch this card owns can only
WITHHOLD or RETRACT a proposal.

---

## 4. Gate (1) — flag-off byte-identity, proved

Protocol, D15-B's verbatim: minival, `--mode baseline`, v4, `scaled-path-v1`,
`max_steps 200`, seed 20260804, run in a scratch rsync of the tree (no in-tree
ledger row). Re-run at the FINAL source state of this lane:

```
episode rows byte-equal:      25 / 25   (moved: [])
episodes payload sha256:      bfb21cd25be4db9e02b3944479cfaf068d8f17f333743c32adc25c0b9d6ea8ca
                              == the frozen row's, byte for byte
episode_digest:               4113607b92c734dfdd46004b6e77baf6575fc2a1c493e5d9dc5a12c6c5490222  (unmoved)
report digest (D15-B rule):   ee234c6376d63dbfb9c1ffa1eb8d7333ac9fcfd57bc62495795cbe7010fa70f8  (exact)
```

**One correction to D15-B's methodology, measured.** The `ee234c63…` digest is
computed over the report minus `{report_id, elapsed_s, scene, navigator_flags}`
— but `aggregate.scene` carries a second, absolute copy of the scene path, so
the digest is **path-dependent**: a fresh run from any other directory cannot
reproduce it. Reproducing it therefore required substituting the in-tree scene
path back into `aggregate.scene` (the one field a scratch-rsync run cannot hold
fixed); with that single substitution the digest matches to the byte. A
path-independent form of the same claim, offered for future arms: drop
`refreeze_provenance` and `aggregate.scene` as well, giving
`897d6ce7ea709415eb11e498271f8292cd7b651042673928292d8a137df65bb9` for the
frozen row and for this lane's flag-off arm alike.

> **CORRECTION — card AF-2, 2026-08-11.** Provenance: `AUDIT_WAVE2_FABLE.md`
> should-fix 4, "the ee234c63 recipe as documented does not reproduce; the
> payload shas are serializer-unpinned". Both findings are upheld, and the exact
> recipes are below — every one of them re-derived from the committed frozen row
> and now pinned by `tests/test_nav_instruct_digest_recipe.py`.
>
> 1. **The exclusion set above is INCOMPLETE — it is FIVE fields, not four.**
>    `refreeze_provenance` must also be dropped. With the four documented fields
>    the digest is `200f5653706c4aea161b4aee1c5af6b9b2be2ef46aa808d4d163bafd6adead30`,
>    not `ee234c63…`. (The paragraph gets this right one sentence later, when it
>    describes the path-independent form as "drop `refreeze_provenance` **and**
>    `aggregate.scene` as well" — but that reads as two extra drops on top of
>    four, when `refreeze_provenance` was already required for `ee234c63…`.)
> 2. **The serializer is part of the recipe** and was never stated.
>    `json.dumps(..., sort_keys=True)` uses DEFAULT separators (`", "` / `": "`);
>    compact separators give different bytes for identical content. That, and
>    nothing else, is the difference between this lane's `897d6ce7…` and
>    VS-5's `c172da37…` (W2_WIRE2_STATUS.md §4.1 attributes it to "a different
>    serializer", which is right — but both values are correct and neither is
>    wrong). The reproducing recipes, verbatim:
>
> ```python
> EXCL = {"report_id", "elapsed_s", "scene", "navigator_flags", "refreeze_provenance"}
> body = {k: v for k, v in report.items() if k not in EXCL}
>
> # ee234c6376d63dbfb9c1ffa1eb8d7333ac9fcfd57bc62495795cbe7010fa70f8
> # PATH-DEPENDENT: aggregate.scene is kept and holds an absolute path.
> sha256(json.dumps(body, sort_keys=True).encode())
>
> body["aggregate"] = {k: v for k, v in body["aggregate"].items() if k != "scene"}
> # 897d6ce7ea709415eb11e498271f8292cd7b651042673928292d8a137df65bb9  (this lane)
> sha256(json.dumps(body, sort_keys=True).encode())
> # c172da375ff23987cb6414fe8899fa263f7ec00ef363659306a38c7719f7553a  (VS-5's)
> sha256(json.dumps(body, sort_keys=True, separators=(",", ":")).encode())
> ```
>
> 3. **The episodes payload sha of §4 below is reproducible after all** — the
>    lane sorted the rows by `episode_id` first (the report's own order is
>    grouped by family, not sorted), and used default separators:
>
> ```python
> rows = sorted(report["episodes"], key=lambda r: r["episode_id"])
> # bfb21cd25be4db9e02b3944479cfaf068d8f17f333743c32adc25c0b9d6ea8ca  (this lane)
> sha256(json.dumps(rows, sort_keys=True).encode())
> # 440fd8842854d446a0c5ffc6ccf625def708d4c9889cb4324a10f6a3ee41f8d6  (VS-5's)
> sha256(json.dumps(report["episodes"], sort_keys=True, separators=(",", ":")).encode())
> ```
>
> Two lanes, two row orders, two serializers, one identical set of episode rows.
> The in-report `episode_digest` (`4113607b…`) is the runner's own and is
> unaffected by any of this — it is the number to quote when only one is wanted.
> AF-2 re-ran this lane's protocol at its own landed state and reproduced all
> five values plus 25/25 byte-equal rows.

---

## 5. Gate (2) — v4 frozen minival, three paired arms

`--mode candidate`, v4 minival (n = 25), `scaled-path-v1`, `max_steps 200`, seed
20260804, scratch rsync, no ledger row.

| arm | SR | authority `false_arrival` | episodes lost vs flag-off | per-tier max \|ΔSR\| |
|---|---|---|---|---|
| flag-OFF (control) | 0.32 | 1 | — | — |
| `detection_lock_on` only (the pre-VS-4 path) | **0.24** | 1 | **2** (`nav-object_relative-B-05`, `nav-region_goal-B-05`) | 0.20 |
| `detection_lock_on` + `lock_on_verify_on_approach` | **0.32** | **0** | **0** | **0.000** |

Per-tier SR, flag-off → verify arm: A 0.800 → 0.800, B 0.600 → 0.600,
C 0.000 → 0.000, D 0.200 → 0.200, E 0.000 → 0.000. Success set identical
(unchanged 25/25, wins 0, losses 0).

The middle row is worth stating plainly: **the card's "v3 measured: 1 false
arrival, 2 lost" reproduces on v4 against the pre-VS-4 lock-on**, and this
card's arm takes both to zero while leaving every success in place.

The one authority change is `nav-object_goal-D-15-109547e2`:
`false_arrival` → `agreement`. Measured cause: the mission commits `lamp_post_1`
(label "lamppost") for a "tree" query, while the D2 estimate is on the actual
queried object 4.80 m away; the OBJECT refinement gate rejects
(`fused_point_outside_vicinity_band`, displacement 4.800260409602796 > the
lamppost vicinity), the commit is refused, and the episode ends `refusal`
instead of claiming an arrival 2.92 m from the true goal. SR is unchanged (the
episode was already a failure); the false arrival is gone.

**A confound that affects per-episode reading of any multi-episode arm** (found
here, reported for VS-5): `HeadlessCityWorld._scan_rng` is seeded once per world
construction and is never re-seeded by `reset()`, so within one runner process
an arm that shortens one episode shifts the scan RNG for every LATER episode.
Aggregates are unaffected; per-episode claims must be re-measured in isolation
(one runner per arm per episode). Every per-episode claim in §6 and §7 below is
an isolated measurement for that reason.

---

## 6. Gate (3) — the B-05 wrong-instance case, end to end

`nav-region_goal-B-05-586317e4` ("walk onto the sidewalk"), v3 minival,
`--mode candidate`, isolated runner per arm:

| arm | success | dtg | authority | final pose | steps |
|---|---|---|---|---|---|
| flag-OFF | True | 0.000000 | agreement | (1.6326, 2.5277) — the NORTH sidewalk | 205 |
| `detection_lock_on` (the defect) | **False** | **4.774509** | **false_arrival** | (1.3480, **−2.5745**) — the south sidewalk | 87 |
| + `lock_on_verify_on_approach` | **True** | **0.000000** | **agreement** | (1.6326, 2.5277) | 205 |

That middle row is the record's measured V-E defect reproduced on this tree
(record: dtg 4.778530810034543, final (1.3480, −2.5785); the 4 mm difference is
the Wave-1 tree, not a different failure). The verify arm's **trajectory is
byte-identical to the flag-off arm's** (every trace field except the note
string), i.e. the mission reference was retained and the lock-on refused to
rewrite it — while the verify machinery was demonstrably live on that episode:
session 1, 61 approach views, states `approach → verify → verified`.

Whole-arm v3 minival: SR 0.20 (off) → 0.12 (lock-on) → **0.20** (verify);
authority `false_arrival` 4 → 4 → **3**.

Structural pytest (`tests/test_ve_detection_lock_on.py`, 7 new cases, all green):

| Test | Pins |
|---|---|
| `test_verify_flag_defaults_off_and_cannot_run_without_the_lock_on_flag` | default OFF; inert without `detection_lock_on` |
| `test_committed_arrival_region_provenance_is_the_grounded_reference` | region centre, `goal_landmark_id`, `candidate_position`, `anchor_entity` are the GROUNDED instance's while the estimate differs; the session opens on that same reference |
| `test_b05_wrong_instance_fused_point_is_refused_and_remembered` | the 4.778530810034543 displacement ⇒ REFUTATION not commit; `mission.goal` stays None; negative evidence written at the estimate's place; the RE-ENCOUNTER is suppressed |
| `test_lock_on_defers_to_the_ranking_for_interchangeable_queries` | the lock-on commit door is never entered on a region query (monkeypatched to raise), while the deference counter proves the session still observed |
| `test_verify_on_approach_refutes_a_detection_with_nothing_behind_it` | commit → REJECTED at a checkpoint, P0-C revision bumped, FP entry written, goal released — with a same-geometry control that has a range return and does NOT refute |
| `test_visible_but_unroutable_window_keeps_the_proposal_pending` | 40 ticks across 12 m → 8 m: state stays APPROACH, pending checkpoints unchanged, zero refutations, reference retained |
| `test_telemetry_note_carries_the_conjuncts_without_a_runner_keyword` | the note channel never introduces a substring the frozen runner keys on |

---

## 7. Gate (4) — v4s phantom cells, flag-ON: two conjuncts pass, one STOPS

Protocol: v4s, all 180 episodes, `--mode candidate`, `scaled-path-v1`,
`max_steps 200`, seed 20260811, scratch rsync. Both arms run by this lane; the
flag-off arm reproduces W2_EVAL_STATUS.md §3 exactly (SR 0.000, mean dtg
10.874235676625897, collisions 0, failures grounding 74 / planning 73 /
false_arrival 28 / search 5, authority agreement 152 / false_arrival 28), which
is the cross-check that the harness here is the harness there.

| axis | n | SR off | SR on | authority `false_arrival` off → on |
|---|---|---|---|---|
| `LA` | 60 | 0.000 | 0.000 | 10 → 10 |
| `BB` | 60 | 0.000 | 0.000 | 1 → 1 |
| `PH` | 60 | 0.000 | 0.000 | 17 → 17 |
| whole arm | 180 | 0.000 | 0.000 | 28 → 28 |

Aggregate flag-ON: SR 0.0, SPL 0.0, mean dtg **10.780714489567655** (off:
10.874235676625897), collisions 0. Failure histogram moves
`planning_error` 73 → 47, `search_error` 5 → 16, `refusal` 0 → **18**,
`grounding_error` 74 → 71 — i.e. 18 episodes now end in an honest refusal where
they previously ended in a planning failure. **SR 0 on both arms is the
designed property of these cells** (VS-6: "built to be unfindable flag-off");
converting them is VS-5's measurement, not this card's.

### The three conjuncts, run through VS-6's own `phantom_cell_gate`

| conjunct | flag-OFF | flag-ON |
|---|---|---|
| zero phantom arrivals (vicinity predicate) | **FAIL** — 2 (`PH-10`, `PH-31`) | **FAIL** — 2, the *same two* |
| ≥1 lock-on COMMIT-then-REFUTATION | **FAIL** — 0 | **PASS — 1** |
| ≥1 FP-memory suppression on re-encounter | **FAIL** — 0 | **PASS — 1** |

Both non-vacuity conjuncts are satisfied by ONE episode and by the exact
sequence the design describes: `nav-object_relative-PH-37-76cea335` commits
(`approach`), is REFUTED on approach (`rejected`), the refutation is written to
the negative-evidence memory, the mission resumes search, re-encounters the same
hypothesis at the same place, and the memory SUPPRESSES it. That is
commit → refutation → re-encounter → suppression, measured live from the
persisted trace, not asserted.

Whole-arm telemetry (summed from the per-episode trace finals): **24
refutations** across 180 episodes (23 of them pre-commit refinement-gate
refusals, 1 a post-commit verify refutation), **1 suppression**, 207 sessions,
26 671 approach views.

### Why the first conjunct fails — measured, both episodes, in isolation

* **`nav-object_goal-PH-31-2dab201e`** — identical outcome in all three arms
  (flag-off, lock-on, verify), **trajectory byte-identical**: success False,
  dtg 4.152974, authority `false_arrival`, final (−1.3772, 1.2492). The
  instruction is *"walk towards the tree"*; the navigator commits **`lamp_post_1`
  (label "lamppost")** — a REAL lamppost admitted for a "tree" query by the
  substring/alias fallback, because `_siglip_matcher()` reports
  `available == False` on this tree. Terminal relation `towards` ⇒ K0 arrival
  band **[0.6, 2.5] m**; the robot stops **2.4699 m** from the committed
  instance, i.e. inside the band but OUTSIDE the outermost verify checkpoint
  (`[1.32, 1.12]` for that reference). **No checkpoint ever became due, so the
  identity re-check never ran** — it would have scored "tree" vs "lamppost" at
  0.0, below the 0.9 SigLIP operating point, and refuted. The final pose happens
  to be 0.4669 m from `tree_2_phantom`, so the gate's vicinity predicate counts
  it as a phantom arrival.
* **`nav-object_goal-PH-10-48835339`** — in ISOLATION this episode claims **no
  arrival at all** in any arm (`system_arrival` False, status failed, dtg
  4.863117, identical trajectory off vs verify). It is counted as a phantom
  arrival only inside the 180-episode run, where the shared scan RNG (§5) has
  been shifted by earlier episodes. Both arms count it.

**Two structural findings this produces** (neither closable inside this card's
OWNS; handed to the owner and to VS-5):

1. **The `towards` arrival band is wider than the verify schedule.** K0's band
   for `towards` reaches 2.5 m; the checkpoint schedule is the near-object
   envelope (≤ 1.38 m for a lamppost, ≤ 1.9 m for a tree). An arrival can
   therefore be claimed without a single checkpoint becoming due, which makes
   verify-on-approach structurally bypassable for that relation. Closing it means
   either extending VS-1's frozen checkpoint derivation (its contract) or
   conditioning an arrival on a verify verdict (a second arrival predicate,
   which record §2.3 rejects) — an owner decision, not a wiring change.
2. **PH-31's defect is a GROUNDING defect, and reference/estimate separation is
   blind to it by construction.** The lamppost IS the reference, so the estimate
   agrees with it and the refinement gate has nothing to reject. The class error
   is upstream of everything this card owns.

---

## 8. Non-vacuity of the wiring (dispatch requirement)

Not absence-of-failure — the machine is observed running:

* v4 minival verify arm: 16 sessions, 1 120 approach views, states observed
  `approach`, `verify`, `verified` (e.g. `nav-region_goal-A-00` and
  `nav-region_goal-B-05` both reach `verified`; `nav-object_relative-B-05`
  cycles `approach → verify → approach` across three sessions).
* v4s verify arm: 207 sessions, 26 671 views, plus the `rejected` state and the
  suppression of §7.
* Checkpoint schedules are published per commit
  (`mission.metadata["lock_on_verify_checkpoints_m"]`, e.g. `[1.32, 1.12]` for a
  lamppost, `[1.38, 1.32, 1.18]` for the bare-object envelope).
* The counters ride `MidLevelCommand.note`, the ONE navigator-side channel the
  frozen `evals/nav_instruct/runner.py` persists per step (verified: the runner
  copies `mission.metadata` only for `resolution_state` and `reply`; a navigator
  attribute has no path out at all). Suffix form:
  `…|lock_on_verify=<state>,sessions=N,views=V,commits=C,refutations=R,suppressions=S`,
  appended only to NON-terminal commands and only under the flag, after a `|`
  delimiter, introducing none of the substrings the runner keys on
  (`semantic_search_scan` prefix preserved, no `frontier`, no
  `semantic_target_not_found`, `reason` never touched). Pinned by a test.

---

## 9. The visible-but-unroutable window (8–12 m)

W2_EVAL_STATUS.md §3 measured that the grid planner's local costmap reaches
~8 m while the frustum reaches 12 m, so a locked target is visible but
unroutable in between. The wiring tolerates that window **without weakening
anything**, and for a structural reason rather than a tuned one: the checkpoint
schedule IS the near-object envelope — metres, not tens of metres — so no
checkpoint is due anywhere in 8–12 m. The session simply stays `APPROACH` and
keeps re-verifying while the planner closes range; the refinement gate still
runs on every one of those views, so the window is quiet but not blind.

Two mechanisms make that safe rather than accidental:

* `_begin_semantic_replan` — the single replan funnel, which every release
  authority already goes through, including `_unroutable_goal_recovery` — ends
  the verify session. A released commitment can never leave a session verifying
  against a reference the mission no longer holds.
* A refutation never adds the instance to `_unreachable_candidates`, so the
  window's own release path and the refutation path stay distinct.

Pinned by `test_visible_but_unroutable_window_keeps_the_proposal_pending`
(40 ticks, 12 m → 8 m, no range return at all: state stays APPROACH, pending
checkpoints unchanged, zero refutations, reference retained). Measured on the
live arms: 26 671 approach views produced only 1 post-commit refutation, so the
window is not generating spurious vetoes at scale.

---

## 10. Ownership, the allowlist pin move, and ci_gate

**Allowlist (in OWNS).** `ALLOWED_NAVIGATOR_OVERRIDES` gains exactly one name,
`lock_on_verify_on_approach`, with a comment naming the card — D15-B's declared
one-name move repeated the same way. `tests/test_e4_evidence_seams.py`'s closed-
set pin moves by that one name, comment naming the card (the file is in this
card's OWNS by the same precedent the Wave-1 audit accepted).

**One edit outside OWNS, declared.** `tests/test_person_aware_nav.py` (D15-B's
new, still-untracked test file) pins `len(ALLOWED_NAVIGATOR_OVERRIDES) == 3` — a
literal that this card's declared one-name deliverable necessarily moves.
Changed to `== 4` with a comment naming VS-4; the count stays EXACT, so no flag
can appear undeclared, and the guard's purpose is untouched. Same shape as
VS-6's two declared pin moves, which Fable adjudicated ACCEPTED
(AUDIT_WAVE1_FABLE.md, closing section). Nothing else in that file was opened.

**One unintended in-tree write, found and reverted.** A parallel shell launch
lost its `cd` into the scratch rsync, so one flag-ON v4s run appended a row to
`evals/nav_instruct/results/ledger.jsonl` in-tree. Reverted with `git checkout`;
the ledger is back to 22 rows with `nav-instruct-v1-baseline-v4-20260811T070536Z`
as its last row, and `git status` on `evals/nav_instruct/results/` shows only
VS-6's `mutation_panel.json`. Every other run in this lane wrote to the scratch
tree only. Recorded because it happened, not because it survived.

### `scripts/ci_gate.py --tier commit`, 2026-08-11T13:02:47Z (final)

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
[  PASS] HARD  default-suite              3575 passed, 9 skipped, 36 deselected
RESULT: PASS — every hard gate green.   elapsed 125.4s
```

Suite delta attributed: 3575 = the lane's own baseline 3568 + **7**, exactly the
7 new cases in `tests/test_ve_detection_lock_on.py` (14 → 21 in that file).
`ruff` stays `new 0`.

---

## 11. Interpretations recorded (the record wins; these fill gaps it leaves)

1. **Persistence is depth support, for OBJECT references only.** The record
   names persistence as one of three checkpoint demands but does not say how the
   WIRING computes it, and VS-1's own `does_not_prove` warns that in a T0 arm
   "persistence is the oracle frustum, which never hallucinates". Measured on
   this tree: the oracle applies a pure 12.0 m / ±70° range-and-bearing test with
   **no occlusion and no geometry test**, reports a phantom identically to a real
   object at every range from 12.0 m down to 0.0 m, at a constant 0.98
   confidence and a fixed position, and — because the world publishes no
   `sigma_range_m` — hands the phantom and a real object numerically IDENTICAL
   covariance at equal range. So neither persistence-as-oracle-presence nor
   covariance shrink can discriminate anything here; the one measured
   discriminator is that a LiDAR ray passes straight through a
   perception-spec-only distractor. The wiring therefore answers "was the target
   associated in THIS view?" with the pipeline's OWN stratum-2 association
   (`_target_clearance`), which is an existing in-tree authority, not a new
   threshold. Regions are exempt (a sidewalk is the ground plane).
2. **M-of-N admission gates the confirmer, not D2.** The record's
   independent-evidence rule is stated for M-of-N admission; the wiring applies
   `admits_for_confirmation` to what reaches `MultiViewConfirm` and keeps fusing
   every view into D2, because covariance shrink under closing range is what the
   checkpoints ask about. Measured consequence, reported as a finding: on these
   episodes the D1 lock-on hypothesis reaches M-of-N **zero** times (`commits=0`
   across both arms) — an in-place scan and a radial approach both leave the
   aspect angle unchanged, so a second admissible view never arrives. That is
   the record's own predicted cost ("slows legitimate commits by ~one scan arc")
   at its limit, and it is harmless HERE only because the instance choice was
   deferred to the ranking: with deference, a lock-on that never confirms costs
   nothing, whereas in the pre-VS-4 path it is exactly what loses 2 episodes.
3. **One hypothesis per instance.** `MetricLocalizer` fuses every measurement
   into one state with no association gate (record §2.1(1)). Left alone, the
   estimate becomes a mixture of two instances that sits between and outside
   both, and the refinement gate then refutes a perfectly good reference on the
   strength of our own contaminated fusion — **measured**: the first
   implementation lost `nav-region_goal-B-05` on the v4 minival exactly that
   way. The estimator therefore restarts when the instance under observation
   changes, and the searching path feeds the grounder's own pick. Strictly
   state hygiene; it cannot admit anything the flag-off path refuses.
4. **A refutation resumes the search, it does not banish the instance.** See §3.
5. **`instructnav_recovery.py` needed no edit** (§2).

---

## 12. `does_not_prove`

* **No phantom-arrival claim.** Gate (4)'s first conjunct FAILS flag-ON. This
  lane does not claim the wiring prevents arrival at a phantom on the v4s cells;
  it claims the two measured cases are unchanged from flag-off and names their
  causes (§7). Nothing here says a different wiring could not close them.
* **No real-camera evidence.** Persistence-as-depth-support is exercised against
  a simulator whose distractors are perception specs with no body. It says
  nothing about a real detector's false positives, and nothing about a real
  LiDAR's returns on a real object at a checkpoint. Hardware-deferred, as VS-1's
  own `does_not_prove` says.
* **No claim that the identity re-check works in the live arms.** It never ran
  once: no checkpoint became due on any episode that would have exercised it
  (§7). Its only evidence is unit-level, through VS-1's frozen tests.
* **No SR claim on v4s.** Both arms score 0.000 on all three axes. The 18
  additional `refusal` outcomes are a change of failure CLASS, not of capability.
* **The v4 minival is n = 5/tier.** Per-tier |ΔSR| = 0.000 is a regression
  tripwire at that power, not an estimate of the effect.
* **Determinism is proved for the flag-ON arm across processes** (three
  independent v4-minival runs produced a byte-identical episodes payload,
  `eea885595232ea8c…`), but NOT across episode ORDER: the shared scan RNG (§5)
  means a per-episode number from a multi-episode run is not portable.
* **`commits=0` is not evidence that the D1 lock-on is broken** — it is the
  admission rule biting on radial approaches (§11.2). No arm here measures a
  lock-on that does confirm under the rule.

---

## 13. Files touched

**Edited (in OWNS):** `src/parcel_robot/navigation/pipeline.py`,
`src/parcel_robot/navigation/detection_lock_on.py`,
`evals/nav_instruct/runner.py`, `tests/test_ve_detection_lock_on.py`,
`tests/test_e4_evidence_seams.py`.

**Edited (out of OWNS, declared §10):** `tests/test_person_aware_nav.py` (one
literal).

**Not edited, though in OWNS:** `src/parcel_robot/navigation/instructnav_recovery.py`.

**Untouched, as required:** `runtime.py`, `instructnav/arbiter.py` +
`scoring.py`, `reactive_safety.py`, `velocity_shaping.py`, `core/**`,
`camera_channel/**`, `configs/**`, `evals/nav_instruct/episodes/**`, every
`DIGEST_SENTINELS`-pinned file, `multi_view_confirm.py`, and the two Wave-2 pure
modules (`lock_on_verify.py`, `false_positive_memory.py`) — consumed frozen.

No commit made.

---

## 14. Handoff to VS-5 (pipeline.py slot 2)

1. **pipeline.py is yours now.** The VS-4 block is a contiguous region between
   `_try_detection_lock_on` and `_commit_semantic_candidate`, plus six guarded
   call sites: the flag in `__init__`/`from_config`/`start`, the deference
   branch in the searching path (`_lock_on_observe_estimate`), the guard at the
   head and `_begin_lock_on_verify` at the tail of `_commit_semantic_candidate`,
   the `_verify_lock_on_on_approach` hook in `step`, the session teardown in
   `_begin_semantic_replan`, and the note stamp in the `step` tail. All are
   `if self.lock_on_verify_on_approach:`-guarded; none is on your path.
2. **Your flag-off identity baseline is unmoved**: the frozen v4 row still
   reproduces bit-for-bit at this lane's landed state (§4), so re-baseline
   against it directly.
3. **The v4s empty-map/effect gate will hit two things measured here**: the
   ~8 m planner reach vs 12 m frustum (already in W2_EVAL §3, confirmed by the
   0.000 SR on both arms), and the shared scan-RNG confound (§5) — your paired
   McNemar counts are per-episode, so run each arm as a whole set (as here) and
   never mix an isolated run with an arm run.
4. **Telemetry channel**: `MidLevelCommand.note` is the only navigator-side
   channel the frozen runner persists (`mission.metadata` is dropped except
   `resolution_state`/`reply`). If VS-5 needs counters in the trace, append after
   a `|` and avoid the runner's keyed substrings — `_lock_on_telemetry_note` is
   the working example.
5. **Open for the owner, from §7**: the `towards` arrival band (2.5 m) sits
   outside the envelope-derived checkpoint schedule (≤1.38 m), and the
   substring/alias grounding fallback admits a lamppost for a "tree" query while
   `_siglip_matcher()` reports `available == False`. Both are upstream of the
   visual-search rework and neither is closable inside VS-4's OWNS.
