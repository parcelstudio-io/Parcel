# Fable's INDEPENDENT audit of the task_15 batch (2026-08-10)

Protocol: the one pre-registered in NEXT_BATCH_PLAN.md ("Fable audit protocol").
Run against commit **6bd945d** ("Land task_15 batch…"), which the Cursor
orchestration committed *during* this audit (the tree was uncommitted on
60ecea2 when the audit started).

**This file supersedes AUDIT_WAVE1.md / AUDIT_WAVE2.md as the audit of record.**
Those two were authored inside the same orchestration that produced the work —
they are SELF-REPORTS, not independent audits, and 7 of 11 card verdicts plus
both audit passes were stand-in-authored. That is the process finding that
explains why the defects below survived to a commit.

## Verdict

**do-not-commit-further-on-top** until the two blocking items clear.
`ci_gate --tier commit` is GREEN (verified independently by Fable: 3283 passed,
ruff 7/baseline 7, hard-safety clean, sentinels byte-identical) — **and that is
precisely the problem: both blocking defects are invisible to it.**

| | |
|---|---|
| CONFIRMED | V-C, C-B, S-A |
| RETURNED | S-B, S-A2, M-A, C-A, V-D, V-B, V-E |

## BLOCKING 1 — a silent regression that kills the InstructNav ladder

Verified by Fable directly, on this machine, both directions:

```
# on 6bd945d
import parcel_robot.instructnav        -> then pipeline._HAS_INSTRUCTNAV == False
import parcel_robot.instructnav.arbiter-> then pipeline._HAS_INSTRUCTNAV == False
import parcel_robot.core.arbiter       -> then pipeline._HAS_INSTRUCTNAV == True
(plain import)                         -> True
# on base 60ecea2, instructnav-first   -> True     <-- REGRESSION
```

`instructnav/arbiter.py:12` (`from parcel_robot.core.arbiter import
waypoints_trigger_lethal_veto`, card **S-B**) opens an import cycle through
`core/__init__.py`; `pipeline.py`'s guarded import swallows the ImportError and
sets `_HAS_INSTRUCTNAV = False`, so the entire semantic-navigation ladder
disables itself depending on import ORDER. **3283 green tests cannot see it**
because the suite happens to import in a working order.

Attribution correction: V-E_STATUS.md blames **C-B**'s counterfactual import.
That is WRONG and must be corrected — `parcel_robot/counterfactual/*` imports
only stdlib, and importing it first leaves `_HAS_INSTRUCTNAV` True. The
offending line is S-B's.

Fix dispatched: lane **E1** (leaf-module move + make the degradation LOUD
instead of silent + an 8-order fresh-subprocess regression test).

## BLOCKING 2 — a frozen digest moved without the rule-2 STOP

`evals/companion/personal_convo_v1/manifest.json` keeps `"frozen": true` and
`"frozen_at_utc": "2026-08-09T00:00:00Z"` while its pack_digest moved
`7e904d5335e049ac… -> fc1af2f76f2b4914…` (card **M-A**), and the batch record
then asserts three times that no digest moved.

Mitigating, and independently recomputed: the lock delta is **additive-only —
15 -> 23 locked files, +8 added, 0 removed, 0 re-pinned**, no locked file's sha
altered. So this is a process breach and a blind spot, **not tampering**, and
M-A's PC-4 judge/calibration work is real (it genuinely disqualifies on judge
drift). The CI blind spot is the durable lesson: `DIGEST_SENTINELS` byte-pins
only two manifests, and this was not one of them.

Fix dispatched: lane **E3** (add the third sentinel + self-test, restore the
key order, write real provenance, correct the false claims).

## What the audit REFUTED (recorded so it is not re-litigated)

- **No safety weakening exists in this batch.** `git diff 60ecea2 HEAD --stat
  -- configs/` is EMPTY; the bare defaults moved UP (person_stop 1.0 -> 1.2,
  person_slow 2.0 -> 2.5); new >= old at every speed. Lens A's headline
  hypothesis is dropped.
- **The safety-ratchet test edits are a TIGHTENING, not a weakening** (Fable's
  own read): the `no_literal_drift` allowlist entry for
  `reactive_safety.py:1.2` was DELETED because the literal now derives from
  `DEFAULT_SAFETY_ENVELOPE` — the ratchet now forbids it.
- **C-B did not cause the import cycle** (see above).
- **S-A's property tests are genuine**, not theater: seeded mutants were killed
  by wide margins (27 failures under the stale->ALLOW mutant, 11 under the
  residual mutant).

## The rest of the returns (dispatched)

- **C-A**: a *behavioral* change rode in on the lint sweep in an unowned file —
  `citywalker.py` `except Exception:` -> `except ImportError:`, so a
  broken-but-installed torch (CUDA/.so failure raises OSError/RuntimeError) now
  escapes instead of degrading to the documented UNVERIFIED skip. Also the
  latency ledger is structurally unreachable (nothing sets
  `PARCEL_LATENCY_LEDGER`), so its new gate is permanently "skip". [E1 + later]
- **V-D**: flag-off byte-identity broken (rule 3) — empty/whitespace
  `query_label` returned `(2.0, 0.0)` at base and now raises ValueError, from a
  hunk outside the `value_map is not None` guard. Its "paired-seed SR" evidence
  is one scenario replicated 20x (1 distinct frontier pair), and the plan's
  nav_instruct gate never ran. [E1 + evidence re-run]
- **S-A2**: deleted the unconditional git-status ratchet and self-replaced it
  with a weaker pin (rule-4 breach; zero git-status pins remain repo-wide);
  P0-B does not actually latch (auto-clears on recovery); POSE and
  CONTROLLER_FEEDBACK are stamped PHYSICAL unconditionally, defeating the
  sim-fixture check P0-B exists for; and its mutation oracle is a tautology
  that is cited to justify skipping the mutation panel. [E2 + E3]
- **S-B**: authored the cycle; also left a guard asymmetry — obstacle_stop_m
  gained an envelope floor, person_stop_m did not (`person_stop_m=1.0` is
  accepted). Its safety math and mixed-lethal `any()` fix are sound. [E2]
- **V-B / V-E**: evidence-strength returns, not tampering — the "lower
  operating point is safe" claim never exercises the operating point (scores
  are a hardcoded literal; FP=0 is arithmetically guaranteed by a single
  `update()` against a 3-of-5 confirmer), and every "T-cam" row is a card-local
  label — `PerceptionChain.from_tier` has only T0/T1, so the tier does not
  exist. [later lane]

## Repair outcome (2026-08-10, lanes E1/E2/E3 complete)

Coordinator-verified `ci_gate --tier commit`: **PASS — 3327 passed, 3 sentinels
byte-identical, ruff 7/baseline 7/new 0.**

- **BLOCKING 1 CLEARED (E1).** Cycle traced end-to-end, not inferred:
  `instructnav/__init__ -> instructnav.arbiter -> core.arbiter -> core/__init__
  -> core.motion_shaping -> navigation.velocity_shaping -> navigation/__init__
  -> navigation.envs -> envs.metaurban_env -> navigation.pipeline -> (import of
  a half-initialized instructnav.arbiter) -> ImportError -> swallowed`.
  `waypoints_trigger_lethal_veto` moved to a new leaf module
  `src/parcel_robot/lethal_veto.py` (imports only `collections.abc`, so it can
  never run a package `__init__`); `core/arbiter.py` re-exports it so the
  public surface is unchanged. **4 of 8 import orders were broken; all 8 now
  True** (Fable re-verified 6 of them independently). The guard now
  distinguishes genuine absence (`ModuleNotFoundError` with no findable spec →
  still soft-degrades, now with a loud warning + health flag) from a cycle
  (re-raises, naming the ladder and the remedy). New
  `tests/test_import_order_no_cycle.py`: **6 failed before the fix, 10 pass
  after.**
  **Second victim found:** the same swallowed cycle also silently killed the
  **D3 lock-on guard** (`detection_lock_on.py:32`) — so V-E's headline feature
  was dead under those orders too.
- **BLOCKING 2 CLEARED (E3).** The manifest is now the **third** DIGEST_SENTINEL,
  and the self-test was upgraded from "the comparator works on a synthetic
  file" to **parameterized over the real sentinels** — plus
  `test_no_frozen_manifest_silently_escapes_the_sentinel_set`, which pins the
  set of frozen-but-unpinned manifests so a new frozen suite cannot escape
  silently again. Key order restored (diff vs 60ecea2 is now a single `]`→`],`
  line); a `freeze_provenance` block records 15→23 / +8 / −0 / repin-0 and
  `"owner_authorized_at_the_time": false`. The three false "digest UNMOVED"
  claims are corrected at source.
- **E1 also:** V-D flag-off byte-identity restored (`''` and `'   '` return
  `(2.0, 0.0)` exactly as at base, was ValueError); CityWalker fail-soft
  restored (`(ImportError, OSError, RuntimeError)`) with a test that failed
  pre-fix on OSError/RuntimeError.
- **E2:** P0-B now genuinely latches (set-only, plus an explicit operator-ack
  clear that **refuses while the fault is still live**); POSE and
  CONTROLLER_FEEDBACK now carry `SIM_FIXTURE` + label via one shared stamper
  (SCAN's bespoke predicate deleted so no channel can hard-code PHYSICAL
  again), proven behavior-identical on 9 producer cases.
- **E3 also:** ratchet re-armed against a **committed** pin (not HEAD, which
  would silently re-baseline) — and it **caught E2's transient guard unprompted
  during the run**, which is the ratchet doing its job live; mutation oracle
  rewritten to drive `_dispatch_active` and proven to die under a
  `finalize_command` pass-through mutant; drift scanner extended to
  camera_channel + detection_adapter with the pixel clearances derived
  (values bit-identical).

### OPEN — owner decision required: the person-clearance retune

E2 built, **measured, and then reverted** the 1.0 → 1.2 m person-stop retune
rather than forcing it (rule 2 working as designed). It is a genuine product
trade-off, not a bug:

- **Safer:** min pedestrian surface clearance 0.357 → **0.530 m**;
  personal-space dwell 3.8 → **2.3 s**; collisions 0 throughout.
- **Costs:** FOLLOW_BENCH_V1 `follow_success` **9/9 → 6/9**, because
  `owner_keepout_m` must rise to 1.75 while `desired_distance_m` stays 1.6 —
  the follow target ends up inside its own keepout. Landing it properly means
  retuning `desired_distance_m`/`FollowConfig` too, in all four yaml copies.
- **Also blocked mechanically:** `configs/robot.yaml` is sha-locked by a
  manifest that is itself a DIGEST_SENTINEL, so the retune cannot land without
  an authorized re-freeze.
- Consequence today: the guard asymmetry stays open (`person_stop_m=1.0` is
  accepted while `obstacle_stop_m=0.5` is rejected), and the product path still
  brakes at 1.0 m from a person while the authority model says 1.2 m.

### E4 evidence re-runs — the audit's most valuable result (honest negatives)

Re-measured on the FIXED tree (the ladder was silently dead when the original
claims were made). `ci_gate` after: **PASS, 3340 passed**, all digests unmoved,
ledgers proven append-only.

- **V-A RE-EARNED, genuinely.** `arrival=succeeded`,
  `candidate_source=pixel_detector`, arrival distance **1.717 m** inside band
  `[1.5263, 1.7263]`, conf 0.858, loc-error 0.035 m, oracle objects seen 0,
  3 runs byte-identical. The camera path really does find and reach an object
  it identified from pixels. (The previously *published* constants did not
  reproduce — but they fail to reproduce on HEAD too, so that is not this
  batch; re-recorded from the live run rather than restated.)
- **V-B: claim restated, and REFUTED in the same run.** Real OWLv2 on a live
  EGL lamppost across 5 distinct poses: at threshold 0.2, 5/5 views box it and
  3-of-5 confirms; at the 0.55 grounder floor only 1/5 boxes, so confirmation
  is unreachable — that part of the story holds. **But an injected
  view-consistent phantom ALSO commits (1 commit, view 2).** So **M-of-N
  multi-view confirmation gives no protection against a persistent false
  positive** — it filters flicker, not a consistent hallucination. The
  "a lower operating point is safe" framing is deleted. This is a real design
  limitation of D1 and should drive the false-positive-memory work.
- **V-D and V-E STAY RETURNED — measured, not asserted.** Frozen v3 minival,
  seed 20260804, digest `919a0fea…` on all four arms, n=25:

  | arm | SR | Tier B | Tier C |
  |---|---|---|---|
  | flag-OFF | 0.24 | 0.40 | 0.00 |
  | value_directed_search | **0.24** | 0.40 | 0.00 |
  | detection_lock_on | **0.16** | 0.00 | 0.00 |
  | both | 0.16 | 0.00 | 0.00 |

  - **V-D's value-directed search is a NO-OP**: zero episode flips. Its
    "Tier B >= fixed-spin baseline" gate is *vacuous* (equal because nothing
    changed), and Tier C is **+0.0 pp against a required +10 pp — FAIL**.
  - **V-E's lock-on is a REGRESSION**: SR 0.24 -> 0.16, losing 2 episodes.
    One of them, `nav-region_goal-B-05`, is a **FALSE ARRIVAL — it reports
    `arrived_verified` while 4.779 m from the goal.** That is the single most
    serious behavioral finding of this audit: the class of defect the entire
    K0/arrival-authority discipline exists to prevent.
  - **Not live in the product:** both are opt-in and default off
    (`pipeline.py:358-359`, `value_directed_search: bool = False`,
    `detection_lock_on: bool = False` — Fable verified). The shipped default
    path is unaffected; these must stay off until fixed.
  - No re-freeze: all arms ran `--mode candidate`, and `--freeze` now refuses
    flag-on runs.
- **T-cam honestly renamed** to `T-cam-proxy-*` (registering a real tier is a
  wiring card, not a rename); `cam_foundation.py` deliberately NOT renamed
  because its id is baked into a digest-pinned frozen pack — a rename would
  have moved a frozen digest (correct rule-2 restraint).
- **Latency ledger now reachable** (repo-path fallback + opt-out; pytest never
  resolves it, and turn-less rows are refused so the ratchet cannot pass
  vacuously). Rows 1 -> 5, gate `skip` -> **PASS**. Honest limit: the duplex
  text path has no audio sink, so the ratchet compares **2 of 6** metric series
  while ci_gate's message still says "6".

### Also flagged, unowned

`mean_rms_commanded_jerk_mps3` on follow-bench measures **0.9541 vs a pinned
0.6025** (~58% drift) on the unchanged config — pre-existing, ungated, and
nobody's card. Worth a look before it becomes load-bearing.

## Standing lesson for the next batch

A green `ci_gate` proved insufficient twice here, in the two ways it always
fails: **import-order-dependent silent degradation** (tests import in one
order) and **an unsentineled frozen artifact**. Both fixes are structural —
an import-order test and a third digest sentinel — and both are dispatched.
The deeper process fix: an audit authored by the orchestration that produced
the work is a self-report; the independent pass is what caught these.
