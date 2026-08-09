# Review — Sol (5.6 Ultra stand-in) on Opus K0 + K2′

**Date:** 2026-08-05  
**Reviewer:** Sol 5.6 Ultra stand-in (API-limited)  
**Scope:** Opus deliverables for K0 (goal-calibration) and K2′ (sim-bag +
hardware-readiness), against [ADJUDICATION.md](ADJUDICATION.md) and the binding
criteria below.  
**Method:** read status + touched sources/tests; ran
`tests/test_k0_arrival_authority.py`, `tests/test_instructnav_scoring.py`,
`tests/test_city_semantics.py`, `tests/test_bags_roundtrip.py` (23 passed).  
**Constraint:** review only — no fixes implemented.

## Criteria checklist

| Criterion | Result |
|---|---|
| One arrival authority (navigator / semantics / scorer) | **Fail** on `next_to` (see B1) |
| Step-limit-inside-goal → L6, not planning | **Pass** for the clean path; residual precedence gap (S1) |
| No Nav2 authority migration | **Pass** — K0/K2′ code stays on `grid_v1` / in-house navigator |
| Hardware last | **Pass** — ADRs draft-only; ledger unvalidated; no procurement |
| Bag oracle rejection | **Pass** — record + replay fail-closed; tested |
| Ledger P5 gates | **Pass** — HR-1…HR-9 with named re-run gates |

## Verdict

**REQUEST CHANGES**

K2′ meets the card. K0 correctly retires the near/lamppost radius quarrel and
routes clean step-limit-inside-goal traces to L6, but **`object_relative` /
`next_to` still has two GoalRegion footprints** — eval vs pipeline — so the
card’s “one arrival authority” claim is not true for the full NAV_INSTRUCT
relation set. Fix B1 (and ideally S1) before re-freeze.

---

## Findings

### Blockers

#### B1 — `next_to` footprint disagrees between scorer and navigator

**Criterion:** one arrival authority.

- **Eval / scorer authority:**
  `evals/nav_instruct/generator.py::_relative_goal` builds
  `object_next_to_goal_region(..., footprint=landmark["radius_m"] * 0.5)`.
- **Navigator / verification authority:**
  `instructnav/scoring.py::arrival_goal_region_for_relation` (`relation == "next_to"`)
  and `navigation/approach.py::safe_approach_pose` (`terminal_relation == "next_to"`)
  use full `metadata["radius_m"]` / `candidate.metadata["radius_m"]`.

For `bench_1` (`radius_m=0.7`), eval footprint is **0.35** and pipeline
footprint is **0.7**, with the same band `NEXT_TO_BAND_M=(0.4, 1.5)`.

Concrete disagreement (center-distance 0.50 m):

| Consumer | `GoalRegion.contains` |
|---|---|
| Episode goal from `_relative_goal` | **True** (`0.4≤0.50≤1.5` and `≥0.35`) |
| Mission `arrival_goal_region` from `arrival_goal_region_for_relation` | **False** (`≥0.7` fails) |

Effects:

- `evals/nav_instruct/runner.py` step-limit audit uses `episode.goal` → can
  stamp `navigation_step_limit_inside_goal` / L6 while the robot is **outside**
  the navigator’s arrival region.
- Hold/success scoring can accept poses the pipeline will never verify.
- `tests/test_k0_arrival_authority.py` only locks **near**/lamppost agreement;
  no `next_to` cross-check.

**Must-fix:** one shared next_to footprint builder used by
`_relative_goal`, `arrival_goal_region_for_relation`, and
`safe_approach_pose` (or generate the episode goal from the same helper the
pipeline calls). Extend `test_k0_arrival_authority` to assert bench/planter
eval ↔ pipeline ↔ approach footprint equality.

---

### Should-fix

#### S1 — `_classify_failure` lets earlier `planning_error` beat terminal step-limit-inside-goal

**File:** `instructnav/scoring.py::_classify_failure`

Precedence is documented as
refusal → grounding → search → **planning** → control → termination.
`flags["planning_error"]` / `"no_route"` return **before** the
`termination_error` / `navigation_step_limit_inside_goal` / ever-inside+step-limit
branch.

A trace that once marked `unreachable` / `planning_error`, then expires inside
the GoalRegion with `termination_error=True`, still attributes **L4
`planning_error`**, not L6 — the exact mislabel K0 was meant to kill for
near-miss timeouts.

**Must-fix (with B1):** when the terminal note/flags indicate
`navigation_step_limit_inside_goal` (or `termination_error` + inside/ever-inside
+ step_limit), prefer `FailureClass.TERMINATION` over planning/attempted.

#### S2 — K0 re-freeze not executed

Card text and D5 require an honest baseline re-freeze. Delivered:

- Procedure: `scrum/20260805/task_1/freeze/README.md`
- Hook: `evals/nav_instruct/run_nav_instruct_v1.py` (`--freeze` →
  `nav-instruct-baseline-k0.json`)
- Runner bump: `evals/nav_instruct/runner.py::RUNNER_VERSION = "nav-instruct-v1.1-k0-arrival"`

Missing: any `nav-instruct-baseline-k0*.json` artifact. Do not freeze until B1
(and preferably S1) land; then append the new row without rewriting
`20260804/task_6` freezes.

#### S3 — Headless step-limit path only rewrites `reason`

**File:** `headless_city.py::_run_navigation` (else branch ~665–684)

Sets `reason = "navigation_step_limit_inside_goal"` from
`mission.metadata["arrival_goal_region"]`, but does not stamp structured
`termination_error` / `step_limit` on trace samples the way
`evals/nav_instruct/runner.py` does. Fine if headless never feeds
`score_episode`; brittle if anything later attributes from headless traces.

---

### Nits

#### N1 — Region `goal_region` built inline

`city_semantics.py::_region_metadata` inlines a polygon dict instead of
`region_inside_goal_region(...)`. Behavior matches; consistency only.

#### N2 — Oracle key denylist is name-based, not exhaustive

`bags/schema.py::is_privileged_key` / `_PRIVILEGED_*` cover the stated
oracle/privileged/ground_truth/scorer prefixes. Aliases like `gt_*` are not
blocked. Acceptable for MVP; extend when real bags appear (HR-8).

#### N3 — `--freeze` auto-sets `frozen_baseline: True`

`run_nav_instruct_v1.py` freeze row sets `frozen_baseline: True` immediately;
`freeze/README.md` says that flag is for owner acceptance. Prefer writing the
artifact with `false` until accepted.

#### N4 — `arrive_radius_m=1.5` default retained

`pipeline.py` / navigator still default `arrive_radius_m=1.5`. K0_STATUS
correctly demotes this to controller approach-pose tolerance for semantic
missions. No action if that contract stays documented and tests keep rejecting
the legacy eval disc (`test_near_envelope_rejects_legacy_radius_plus_1_4`).

---

## K2′ assessment (passes criteria)

| Deliverable | Judgment |
|---|---|
| `bags/schema.py` `parcel.bag.v1` | Hardware-shaped topics/clocks/frames; non-empty `does_not_prove`; envelope required |
| `BagRecorder` / `BagReplayer` | Roundtrip + digest; undeclared topic rejected |
| Oracle isolation | `reject_privileged_fields` on record; replayer validates poisoned JSONL (`test_rejects_*`, `test_replayer_rejects_bag_with_oracle_payload`) |
| `hardware-readiness.md` | HR-1…HR-9, each with exact P5 re-run gate; all unvalidated / draft |
| `adr/0001-golden-image.md`, `adr/0002-firmware-pin.md` | Draft; validation deferred to P5; no flash/procure |
| Explicit non-claims in `K2_STATUS.md` | Aligns with owner amendment (hardware last) |

No Nav2 introduction. Scorer/oracle counterfactuals correctly kept off the agent
bag path.

---

## K0 assessment (what works)

- Shared near envelope: `object_near_envelope_m` /
  `object_near_goal_region` wired through `city_semantics`,
  `arrival_goal_region_for_relation`, generator `_object_goal`, approach stand-off
  / vicinity metadata.
- Semantic terminal check requires `arrival_goal_region.contains` before
  relation success (`pipeline.py::_semantic_arrival_verified`).
- Step-limit audit in `runner.py` + clean-path scoring →
  `FailureClass.TERMINATION` / `AttributionLayer.L6_TERMINATION`
  (`test_step_limit_inside_goal_is_termination_not_planning`).
- Legacy ~1.46 m disc rejected in tests.
- No Nav2 migration in the touched stack.

---

## Must-fixes before APPROVE

1. **B1** — Unify `next_to` `anchor_footprint_m` across
   `generator.py::_relative_goal`,
   `scoring.py::arrival_goal_region_for_relation`, and
   `approach.py::safe_approach_pose`; add a K0 agreement test for bench/planter.
2. **S1** (strongly recommended with B1) — Terminal
   `navigation_step_limit_inside_goal` / termination+inside+step_limit must not
   lose to earlier `planning_error` flags in `_classify_failure`.
3. After 1–2: run the documented minival re-freeze (S2); do not rewrite old
   ledger rows.

K2′ needs no must-fixes for this review gate.
