# Sol review of Opus · task_2 (2026-08-06)

**Reviewer:** Sol 5.6 Ultra (cross-review stand-in)  
**Subject:** Opus lane — existing-test cleanup + PlanIR Hold / follow sketch honesty  
**Sources:** `OPUS_STATUS.md`, diffs in `runtime.py` (`_brain_hold` / hold ack),
`voice/local_plans.py`, `tests/test_runtime.py`, `tests/test_intelligence.py`,
`tests/test_runtime_brain_integration.py`  
**Out of scope for re-litigation:** Sol proxemic scorer / admission pin
(`proxemic_approach.py`, `navigate_admission.py`).

---

## Verdict: **APPROVE**

M1 BINDING: FIX is landed. Prior REQUEST CHANGES (incomplete Hold settle —
STOP without clearing `ResumeIntent`s) is resolved. Hold/stay remain
destructive settle, not PAUSE.

---

## Re-review — Fable M1 BINDING: FIX (2026-08-06)

**Inputs:** `FABLE_ARBITRATION.md` (M1 BINDING: FIX), `OPUS_STATUS.md` (claims
fixed), code + `test_brain_hold_clears_resume_intents_and_blocks_follow_resurrection`
/ `test_set_behavior_stay_clears_resume_intents`.

| Check | Result | Evidence |
| --- | --- | --- |
| `_brain_hold` clears follow/nav/search ResumeIntents after settle preempt | **Pass** | After `preempt("manual", …)`, clears `follow` / `navigation` / `search` |
| `set_behavior("stay")` sibling clear | **Pass** | Same three clears after stay preempt |
| Regression: store empty + resume does not resurrect follow | **Pass** | Seeds follow intent → Hold → peeks None; `_resume_from_store("follow")` raises `missing_intent`; stay sibling asserts empty store. Both tests green. |
| Hold remains STOP/settle, not PAUSE | **Pass** | Still `preempt("manual", …)`; table maps manual→follow/nav/search to **STOP**. Clear is the counterpart to STOP when prior pause intents exist — not a PAUSE rewrite. |

**Verdict on M1:** **APPROVE.** Binding remediation complete; no further must-fixes on this dispute.

---

## Prior review (historical) — REQUEST CHANGES

Opus’s fixture honesty and geometry alignment were mostly right, and the
pedestrian e2e xfail was left alone. The original Hold/settle claim was
incomplete: `_brain_hold` stopped channels but did not clear pending
`ResumeIntent`s. That gap is closed in the re-review above.

### Must-fix (satisfied)

1. **`_brain_hold` must clear settled-channel `ResumeIntent`s.** — **Done**
   (plus stay sibling + regressions).

---

## Criteria checklist

| Criterion | Result | Notes |
| --- | --- | --- |
| Fail-closed admission not weakened | **Pass** | Follow tests seed owner heading + `_step_brain` instead of dropping `owner_heading_available`. Honest admission replies untouched. |
| Honest replies / fixtures match product truth | **Pass w/ nits** | Acks updated to PlanIR strings (`bounded move`, behind formation, crosswalk inside, stay). Soft ORs remain (below). |
| No silent weakening of keepout / follow geometry | **Pass** | `sketch_follow` / `sketch_come` default `1.9` matches `FollowOwnerController.behind_distance_m` / `robot.yaml`; stays above keepout `1.55 + 0.05`. Raising from `1.5` fixes dispatch death; does not shrink keepout. |
| Pedestrian xfail not flipped | **Pass** | `test_go_to_the_sidewalk_with_pedestrian_traffic` still `@pytest.mark.xfail`. |
| Hold settle completeness (M1) | **Pass** | Resume-store clear on Hold + stay; regressions assert no resurrection. |
| Scope creep / correctness bugs | **Pass** | M1 must-fix closed; claimed Hold/sketch/test honesty path verified. |

---

## What looks good

- **Hold vs `stop_motion`:** Wiring PlanIR `Hold` to `_brain_hold` (preempt
  follow/nav/search/spatial/activities) matches “stay means settle,” and
  the hold ack `"Okay—I'll stay here."` is product-true.
- **M1 clear:** Explicit clear after STOP preempt matches abandoned-search
  settle family; spoken `pause` path unchanged.
- **Heading fixtures:** `_seed_owner_heading` is the right fix for
  fail-closed FollowFormation admission — evidence, not precondition
  removal.
- **Async dispatch:** `_step_brain()` after follow/stay text is honest about
  PlanIR executive timing.
- **Follow distance:** `1.9 m` aligns sketch args with controller geometry
  so admitted plans are dispatchable without relaxing keepout.
- **Scan note:** Accepting `scan_behavior_dwell` (with legacy
  `semantic_search_scan` still present in search/pipeline paths) is
  acceptable product truth for that fixture.

---

## Nits (not blocking)

- `test_runtime_brain_integration.py` hold-goal asserts use
  `"stay here" or "accepted the task"` — dead alternate now that hold
  goals always ack stay; pin to stay.
- `test_direct_semantic_navigation_reports_search_without_resolved_goal`
  ORs both recovery notes; prefer asserting the note this path actually
  emits once stable.
- Validator still admits FollowFormation `distance_m` down to `0.8` while
  the controller rejects below keepout+0.05 — pre-existing mismatch, not
  introduced here; optional follow-on so sketches cannot reintroduce `1.5`.

---

## Explicit non-issues

- Pedestrian traffic e2e xfail correctly left for proxemic wiring (Sol
  lane / later Opus compose).
- No evidence Opus weakened NavigateTo searchable≠visible admission or
  honest camera/heading refusal copy.
