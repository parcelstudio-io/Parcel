# Review — Sol (5.6 stand-in) on Opus Phase-1

**Date:** 2026-08-05  
**Reviewer:** Sol 5.6 stand-in (cross-review)  
**Scope:** Opus deliverables for K3, K4 wiring, K5 wiring, K6, K7, K8
runner — against [ADJUDICATION.md](ADJUDICATION.md) kickoff board and the
binding criteria below. Status inputs: `K3_STATUS.md` … `K8_STATUS.md`.  
**Method:** read adjudication + status; inspected resume (`runtime.py`,
`core/resume.py`), `instructnav_recovery` / `pipeline`, camera backends,
agent/voice wiring, `deploy/compose`, `evals/walk_with_me/runner.py`; ran
`tests/test_resume_transaction.py`, `test_k4_opus_wiring.py`,
`test_k5_opus_sim_wiring.py`, `test_k6_voice_lanes.py`,
`test_runtime_assets.py`, `test_cpu_budget_proxy.py`,
`test_walk_with_me_k8.py` (**50 passed, 1 skipped**).  
**Constraint:** review only — no fixes implemented.

## Criteria checklist

| Criterion | Result |
|---|---|
| Fail-closed | **Mixed** — K3 resume gate is solid; K6 closed-intent pause/resume is not |
| No Nav2 | **Pass** — no Nav2/ROS authority in Opus P1 seams |
| One motion writer | **Pass** — pace caps scale at `submit_motion`; arbiter remains sole writer |
| No oracle on agent path | **Mixed** — K5 isolates privileged GT in helpers/tests; live nav extras still lift sim GT tracks |
| Resume freshness | **Pass (K3)** / **Fail (K6 join)** — coordinator enforces; closed-intent pause never stores an intent |
| UNSEEN → recovery (not hard refuse) | **Pass** — ScanBehavior → SearchEntity → honest report; baseline remains frustum-only |
| Voice: no model-authored velocity | **Pass** — schema strip + residual call strip + `MODEL_FORBIDDEN_TOOLS` |
| Hardware-last honesty | **Pass** — compose/proxy/camera non-claims + HR ledger stay unvalidated |

## Verdict

**REQUEST CHANGES**

K3, K4 wiring, K5 packaging, K7, and the K8 freeze/runner skeleton are largely
in good shape and meet their card-level non-claims. The Phase-1 join that
matters for voice — **closed-intent pause/resume on the K3 resume
transaction** — is wired to the wrong preemption action (`voice` → **STOP**),
so “pause” destroys navigation/follow instead of recording a `ResumeIntent`,
and “resume” can acknowledge success with nothing to resume. Fix the blocker
(and ideally S1) before calling the Opus P1 voice↔resume seam done.

---

## Findings

### Blockers

#### B1 — Closed-intent `pause` uses `preempt("voice")` → STOP, not pause

**Cards:** K6 (primary), K3 join  
**Criterion:** fail-closed; resume freshness / suspend→resume transaction.

`RobotRuntime._apply_closed_intent` on `directive.suspend` calls:

```python
self.preempt(
    "voice",
    reason="closed_intent_pause",
    targets=("follow", "navigation", "spatial", "search", "activities"),
)
```

`PreemptionTable.default()` declares `voice → {follow,navigation,search,…}` as
**STOP**. `BehaviorChannelRegistry.preempt` only records a `ResumeIntent` on
**PAUSE**. Net effect:

1. Spoken/closed `pause` **destroys** the navigation/follow mission.
2. No `ResumeIntent` is stored.
3. Spoken `resume` finds an empty store and cannot restore progress.
4. This contradicts `pause_navigation`’s own docstring (“does **not** use
   `preempt("voice")` — voice→nav is STOP”) and `docs/PAUSE_SEMANTICS.md`.

K6 unit tests never exercise runtime pause→resume via closed intents, so the
suite stays green while the product seam is broken.

**Must-fix:** closed-intent pause must suspend pausable channels via
`_pause_channel` / true `PAUSE` (same path as `pause_navigation` /
search→follow), not `preempt("voice")`. Add a runtime test: arm nav or follow →
closed `pause` → intent present + mission paused → fresh obs → closed
`resume` restores progress; stale obs rejects.

---

### Should-fix

#### S1 — Closed-intent `resume` always returns the success reply

**Card:** K6  
**Criterion:** fail-closed / conversation truthfulness.

On `directive.resume`, `_apply_closed_intent` loops channels, swallows
`RuntimeError` as a warning emit, and **always** returns
`directive.reply` (“Okay—resuming with a fresh observation.”) even when every
channel is missing/expired/stale.

**Must-fix (with B1):** if no channel resumes successfully, return an honest
failure (or clarification) — do not claim resume completed.

#### S2 — Live navigator still consumes privileged sim semantic tracks

**Cards:** K5 wiring (primary), K4 consumer  
**Criterion:** no oracle on agent path.

K5 correctly isolates `privileged_gt_from_tracks` and routes
`detections_for_agent` through `DetectionNoiseAdapter`, with tests locking
that split. But `RobotRuntime._navigation_extras` (and headless) still publish
`semantic_candidates_from_observation(...)` — direct lifts of sim
`semantic_objects` / regions — and `ingest_observation_memory` prefers those
candidates whenever `detections` extras are absent. Status already lists
“not yet hard-wired into every headless tick”; that means the **default agent
nav path** can still ground on oracle-perfect labels.

**Should-fix:** feed noisy `DetectionMsg` (or equivalently noise-adapted
candidates) on the runtime/headless navigation extras path used by the agent;
keep privileged GT scorer/test-only. Extend a wiring test that the live extras
builder does not pass raw GT confidence/labels without the adapter.

#### S3 — K8 pause/resume stub does not exercise observation freshness

**Card:** K8 runner  
**Criterion:** resume freshness (integration honesty).

`WalkWithMeRunner._stub_pause_resume` uses `ResumeStore.take` and checks that
`requires_fresh_observation` is **flagged**, plus expiry drop. It never calls
`resume_rejection_reason(..., observation_fresh=False/True)` and never
simulates a stale observation blocking resume. Smoke can report
`resume_fresh_ok` without proving the freshness gate.

**Should-fix:** stub (or a dedicated harness hook) should assert
`stale_observation` rejection and successful resume only when
`observation_fresh is True`, matching K3’s coordinator contract.

---

### Nits

#### N1 — K4 SearchEntity geodesic is Euclidean

Documented in `K4_STATUS.md`; injected seam exists. Fine for MVP; do not quote
as grid_v1 path cost.

#### N2 — Walk / catalog grammars still bypass PlanSketch

K6 status is honest. Deterministic walk can still emit `set_velocity` when
`dog is None`; conversation model cannot. Residual debt, not a criterion miss
for model-authored velocity.

#### N3 — Social reaction bridge ticks but does not actuate

Recorded in K6 gaps; veto-on-base-busy is correct. Not a P1 fail.

#### N4 — K8 geometric stubs teleport into the goal

`harness_used=stub_placeholder` + manifest `does_not_prove` make this
acceptable CI scaffolding; do not promote stub SR as capability evidence.

#### N5 — Compose healthcheck is import-only

`deploy/compose.yaml` healthcheck imports the smoke module rather than proving
the 10 Hz loop is alive. Acceptable for skeleton; tighten later.

---

## By card

| Card | Verdict | Notes |
|---|---|---|
| **K3** | Approve | Central `_resume_from_store` + `resume_rejection_reason`; NavigateTo consume; search→follow via store; tests cover stale/expiry/progress |
| **K4 wiring** | Approve | UNSEEN→Scan→SearchEntity→report; baseline hard-refuse preserved; no Nav2/oracle teleports; PlanIR system skills |
| **K5 wiring** | Approve w/ S2 | Backends + factory + noise bridge + HR-4 honesty good; live nav extras still GT-shaped |
| **K6** | **Request changes (B1, S1)** | Conversation strip + pace caps + reaction veto OK; pause/resume closed intents break K3 |
| **K7** | Approve | `network_mode: none` safety island; packaging/`paths.py`; CPU proxy + non-claims; no dock flash |
| **K8 runner** | Approve w/ S3 | Freeze digest + attribution + stub honesty mostly good; freshness contract under-tested |

---

## Must-fixes before re-review

1. **B1** — Closed-intent pause must PAUSE pausable channels and record
   `ResumeIntent` (not `preempt("voice")` STOP); integration test
   pause→fresh-resume and pause→stale-reject.
2. **S1** — Closed-intent resume reply must reflect actual resume outcome
   (fail closed / honest when nothing resumes).

Recommended in the same pass (not strictly blocking alone, but cheap and
on-criteria): **S2** (DetectionMsg on live nav extras), **S3** (K8 freshness
stub).

---

## What looks solid (do not re-litigate)

- K3 fail-closed resume coordinator and `tests/test_resume_transaction.py`.
- K4 UNSEEN recovery ladder vs baseline frustum-only refusal.
- K5 `DOES_NOT_PROVE` / privileged-GT helper isolation in the bridge module.
- K6 conversation-lane physical schema + call stripping; pace scale at
  `submit_motion` (not model velocity).
- K7 safety-control network isolation and hardware-last non-claims.
- K8 freeze digest discipline and explicit stub vs headless evidence split.
