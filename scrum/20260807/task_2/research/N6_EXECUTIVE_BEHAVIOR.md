# N6 — Executive / behavior / PlanIR

**Workstream:** Opus research wave N6 (`OPUS_RESEARCH_WAVE.md`)  
**Scope:** PlanIR contracts, pause/resume atomicity, Hold vs ResumeIntent,
come vs follow, relation success witnesses  
**Method:** code audit of the product executive path plus primary literature
on plan executives, async goal lifecycles, and verified language→skill
pipelines  
**Status:** complete  
**Confidence:** high for defects with product-path tests; medium for
literature→Parcel mapping until P0-C/P1-D land

This report is independent of the prior synthesis in
[`CURRENT_STACK_AUDIT.md`](../CURRENT_STACK_AUDIT.md). Where they agree, that
is convergent evidence, not citation authority.

---

## Verdict

Parcel already has the right *shape*: untrusted language → typed
`PlanSketch`/`PlanIR` → system-owned compiler fields → validator →
`TaskExecutive` → channel adapters → independent witnesses. Keep that
boundary.

What breaks ordinary instructions is not missing model capacity. It is that
**authorizing task state and motion-channel state can diverge**, that
**terminating approach and persistent follow share one skill**, and that
**relation predicates are not yet one closed registry from grammar through
terminal success**. Fix those before comparing planners or VLAs.

---

## Architecture under audit

```text
closed intents / router
        │
        ▼
 local PlanSketch  OR  deliberative PlanIR (model)
        │
        ▼
 compile_plan_contracts / compile_plan_sketch   ← system owns success, timeout,
        │                                           resources, interruptibility,
        │                                           (currently) max_attempts=1
        ▼
 PlanValidator → ValidatedPlan
        │
        ▼
 TaskExecutive  (queue / wait / run / recover / suspend / cancel)
        │
        ▼
 SemanticTaskRuntimeAdapter → NavigateTo | FollowFormation | Hold | …
        │
        ▼
 channels (navigation / follow / search / spatial / activities)
        │
        ├── ResumeStore + ResumeIntent   (pause reconstruction)
        └── controller-state witnesses   (adapter poll)
```

Key files:

| Layer | Path |
| --- | --- |
| Contracts | `src/parcel_robot/brain/contracts.py` |
| Sketch / local plans | `brain/plan_sketch.py`, `voice/local_plans.py` |
| Compiler | `brain/compiler.py` |
| Validator / skill table | `brain/validator.py` |
| Executive | `brain/executive.py` |
| Adapter / witnesses | `brain/runtime_adapter.py` |
| Resume primitives | `core/resume.py`, `core/channels.py`, `runtime_channels.py` |
| Pause convention | `docs/PAUSE_SEMANTICS.md` |
| Product composition | `runtime.py` (`_apply_closed_intent`, `_brain_hold`, pause/resume) |
| Relation registry | `navigation/relation_registry.py`, `navigation/goals.py` |

---

## Ranked defects

### D1 — Resume restores the channel without the authorizing task (P0-C)

**Evidence.** Pause and resume are correctly *designed* as a two-layer
transaction in `docs/PAUSE_SEMANTICS.md` and `TaskExecutive.resume_task`:

1. Suspend releases leases, pauses the channel, records a bounded
   `ResumeIntent`, marks the task `suspended` (non-outcome).
2. Resume requeues the task (`resume_task` → `queued`) and redispatches so the
   adapter consumes the channel intent.

The product closed-intent path breaks step 2. In
`RobotRuntime._apply_closed_intent`:

- **pause** pauses `navigation`/`follow`/`search` *and* issues voice
  `InterruptRequest`s that suspend matching executive tasks;
- **resume** only walks channels via `_resume_from_store` and never calls
  `task_executive.resume_task`.

Pinned product-path measurement:
`tests/test_closed_intent_product_path.py::test_resume_also_restores_the_executive_task_record`
(xfail; backlog **N14**). After `go to the sidewalk` → `pause` → `resume`, the
navigation channel advances (`navigation_resumed`) while the task record stays
`suspended:closed_intent_pause`. Motion runs without that step’s timeout,
verification, or recovery.

**Why it matters.** This is the same class of bug as “safety stop with residual
velocity”: a lower layer looks healthy while the authorizing layer is offline.
Any later model A/B on interrupted missions is uninterpretable until this
closes.

**Fix contract (atomic task-revision transaction).**

```text
suspend/resume/cancel/transfer must be one transaction over
  {task_id, plan_revision, step_id, channel, resources, ResumeIntent}
```

A channel may not reacquire `base` unless its authorizing task revision is
active. Exit: remove the xfail; add a strict pairing test that asserts
`task.state ∉ {suspended}` whenever a resumed channel is enabled.

**Literature alignment.** PLEXIL separates *application* suspend/resume from
node *outcomes* (success/failure/skipped): suspend freezes execution without
declaring the plan finished
([PLEXIL application framework](https://plexil-group.github.io/plexil_docs/Interfacing/TheApplicationFramework.html);
[node semantics](https://plexil-group.github.io/plexil_docs/PLEXILLanguage/PLEXILSemantics.html)).
ROS 2 actions keep goal identity continuous across feedback until a terminal
result or cancel
([ROS 2 actions](https://docs.ros.org/en/humble/Concepts/Basic/About-Actions.html)).
Parcel’s `ResumeIntent` is the right local analogue of “goal still exists”;
the missing piece is binding it back to the executive goal ID on resume.

---

### D2 — `come here` is persistent follow, not terminating approach (P0.5)

**Evidence.** `sketch_come` and plain `sketch_follow` both compile to
`FollowFormation` with `relation="follow"` (`voice/local_plans.py`). The
relation registry even aliases `come` onto the `follow` relation
(`relation_registry.py`), with `terminal_behavior="hold"` and offer phrase
“come to you”.

The adapter then treats direct follow as **terminal success while the
controller remains enabled**:

```text
DIRECT_FOLLOW_SUCCESS_STATES = {"following", "holding"}
```

(`runtime_adapter.py`). Product e2e tests document the consequence explicitly:
the plan task succeeds about a second after dispatch; the formation keeps
running until `stay`/`Hold` releases it
(`tests/test_voice_nav_e2e.py`).

So “come here” currently means:

1. engage persistent direct follow;
2. mark the PlanIR step succeeded when the band is held;
3. keep owning locomotion until a separate Hold/stop.

That is the wrong speech act for a summons. A stationary owner calling the dog
expects **approach → settle → release**. Persistent follow is correct for
“follow me” / “heel”.

**Required split.**

| Speech act | Skill | Terminal witness | Controller after success |
| --- | --- | --- | --- |
| come / go to me / go to the owner | `ApproachOwner` (new) | owner-relative band + settled stop + optional hold duration | **disabled** |
| follow me | `FollowFormation(relation=follow)` | never auto-succeeds on band alone; persistent until cancel/Hold/lease transfer | **enabled** |
| follow behind me | `FollowFormation(relation=behind)` | `holding_behind` is a formation checkpoint, not task completion unless policy says otherwise | **enabled** |
| stay / hold | `Hold` | `motion_stopped` + fresh stop feedback | clears ResumeIntents (already) |

Adapters must not delete a dispatch while its controller remains authoritative
*unless* the skill is explicitly persistent and the executive treats the step
as nonterminal (running lease). Today’s “succeed while follow_enabled” is the
false-success shape.

**Note.** The 2026-08-06 behind-vs-follow admission fix (do not require
`owner_heading_available` for plain follow/come) is correct and must be
preserved when splitting skills. The defect is lifecycle/termination, not
heading admission.

---

### D3 — Hold and ResumeIntent are correctly opposed, but composition still leaks

**Hold (destructive settle).** `_brain_hold` preempts follow/navigation/search/
spatial/activities, stops the arbiter/control path, and **clears** follow,
navigation, and search ResumeIntents so a prior pause cannot resurrect motion
after “I’ll stay”. Hold verification requires
`stop_confirmed ∧ control_feedback_fresh ∧ ¬robot_moving`. This matches the
pause-semantics rule that settle ≠ pause.

**ResumeIntent (non-destructive reconstruct).** `core/resume.py` is solid:

- TTL expiry;
- `requires_fresh_observation` fail-closed via `resume_rejection_reason`;
- one intent per channel (replace-on-suspend, take-on-resume);
- generation tokens bump on pause to invalidate late work.

Channel asymmetry remains intentional and documented:

| Channel | Pause quality |
| --- | --- |
| navigation | true pause (mission + tick counters frozen) |
| search | true pause (wall-clock budgets rewound) |
| follow | reconstruction from intent payload (not frozen controller) |
| spatial / activities | not pausable; STOP |

**Residual risks.**

1. D1 means Hold’s opposite (resume) is incomplete at composition time.
2. Goal-amend pauses channels and may defer replan (`deferred_no_planner`) —
   good fail-closed voice UX, but amendment still needs a verified
   suspend→replan→resume transaction (called out in `PAUSE_SEMANTICS.md`).
3. Follow reconstruction after pause is weaker than navigation pause; a
   post-pause owner track change can resume the wrong formation without an
   identity/freshness gate stronger than telemetry TTL.

---

### D4 — Relation success still forks between grammar, sketch, and witness (P1.5)

**What is good.** `navigation/relation_registry.py` is the right stratum-3
design: one `RelationSpec` owns aliases, FoR, terminal behavior, and a
goal-region builder that delegates to the same K0 `GoalRegion.contains`
predicate InstructNav scoring uses. Planning “would this pose satisfy X?” and
verification “did it?” cannot disagree *when both go through the registry*.

**What still forks.**

1. **PlanSketch grounding collapses relations.** `sketch_navigate` maps any
   terminal relation other than `inside` to grounding `near`
   (`local_plans.py`). `towards` / `next_to` survive in `SemanticGoal` /
   registry space but lose fidelity at the sketch goal surface
   (`NavigationGrounding` only admits `inside|near`).
2. **PlanIR goal relations ≠ spatial grammar relations.** Contracts use
   `{inside, near, behind, follow, orbit, hold, …}` while the registry has
   `{next_to, near, towards, inside, follow, behind, orbit}`. `next_to` and
   `towards` are first-class for navigation goals but not first-class PlanIR
   goal relations.
3. **Follow/come share registry identity.** Alias `come` → relation `follow`
   encodes the D2 conflation at the vocabulary layer.
4. **Known-POI / adapter shortcuts.** Stack audits still report geometric
   arrival or reason-string completion paths that can bypass the contextual
   relation witness (see P1.5 in `CURRENT_STACK_AUDIT.md`). N6 confirms the
   registry exists but is not yet the sole success authority for every product
   path.
5. **InstructNav recovery verifier.** `ScanBehavior`/`SearchEntity` can
   complete `skill_completed` on navigation terminal states including failure
   reasons (`instructnav_recovery_complete`). Recovery completion ≠ relation
   success; attribution must stay distinct in evals.

**Required relation package (P1-D).** For each relation the product claims:

```text
RelationSpec =
  controller | valid goal region | approach sampler |
  final predicate | hold duration | explanation |
  persistent? | success_releases_channel?
```

Drive grammar aliases, PlanSketch grounding, compiler success facts, and
adapter witnesses from that one table. No second “near means everything else.”

---

### D5 — Recovery and invariants are declared richer than they execute (P0.6)

**Compiler.** `compile_plan_contracts` always sets `max_attempts=1` and
reduces recovery to `("safe_stop",)` or `("wait",)` even when the skill
contract advertises `replan` / `rescan` / `alternate_candidate` /
`reacquire_owner` (`compiler.py`, `validator.py`).

**Executive.** `_fail_or_retry` can schedule `pending_recovery`, and the
adapter implements `safe_stop`/`wait` by calling Hold, and “replan-like”
actions by restarting local controllers — but with `max_attempts=1` the
retry path is effectively dead for compiled plans.

**Invariants.** Runtime keeps a single `_active_invariants` /
`_active_invariants_owner` slot. Concurrent or overlapping task submission can
overwrite another plan’s constraints. PLEXIL-style *per-node* invariants and
PlanSys2-style overall requirements both argue for **immutable invariants per
task revision**, with arbitration enforcing the union.

**Deadlines.** Step timeouts exist; admission/queue/precondition/total-task
deadline hierarchy is incomplete. Resource waits can park without a full
budget story (companion to pause-budget rules in `PAUSE_SEMANTICS.md`).

---

### D6 — Persistent vs terminating success facts are underspecified in PlanIR

Compiler success facts for FollowFormation are `following` or `behind` with
target `owner`. The adapter maps those to controller mode states and may emit
`ExecutionResult(status=succeeded)` while `follow_enabled` remains true.

PlanIR needs an explicit persistence bit (or distinct skills) so that:

- terminating skills require `controller_disabled ∧ witness`;
- persistent skills report `in_progress` with formation checkpoints, and only
  terminate on cancel, Hold, lease transfer, or explicit “mission complete”
  policy.

Without that, evals that score `task.state == succeeded` over-count come/follow
and under-test release.

---

## Literature → Parcel decisions

| Source | Lesson | Parcel decision |
| --- | --- | --- |
| [PLEXIL semantics / app suspend](https://plexil-group.github.io/plexil_docs/PLEXILLanguage/PLEXILSemantics.html) | Suspend ≠ outcome; invariants/failure are explicit node conditions | Keep `suspended` non-outcome; finish D1 so suspend/resume bracket the same goal |
| [ROS 2 actions](https://design.ros2.org/articles/actions.html) | Goal ID + feedback + terminal result/cancel; no silent half-resume | Treat `{task_id, revision, step_id}` like a goal UUID across channel pause |
| [BehaviorTree.CPP](https://github.com/BehaviorTree/BehaviorTree.CPP) / [PlanSys2 executor](https://plansys2.github.io/design/index.html) | Reactive recovery as typed subtrees with timeouts; plan→BT for execution | Keep Parcel executive; implement declared recovery as bounded subtrees (P2-C), not LLM retries |
| [SayCan](https://research.google/blog/towards-helpful-robots-grounding-language-in-robotic-affordances/) | Language proposes; affordance/feasibility gates | Preserve compiler/validator admission; models never own leases |
| [Inner Monologue](https://innermonologue.github.io/) | Close loop with environment feedback | Feed typed `ExecutionResult` / observation snapshots only |
| [PlanBench](https://papers.neurips.cc/paper_files/paper/2023/hash/efb2072a358cefb75886a315a6fcf880-Abstract-Conference.html) | LLM plans need external verification | Do not weaken PlanIR validation for model fluency |
| [KnowNo](https://github.com/google-research/google-research/tree/master/language_model_uncertainty) | Calibrated abstention/clarification | Clarification as persistent task state (P1.6), not generic refusal text |
| QSRlib / Sr3D-style FoR (via registry notes) | Relations are data with FoR policy | Extend `RelationSpec`; do not encode come/follow as one alias forever |

**Non-goals from literature.** Full PDDL/PlanSys2 for companion dog commands is
premature (N7 appendix agrees). Parcel’s common lane is a small skill catalog
with deterministic sketches; deliberative PlanIR stays bounded (≤12 steps) and
validated.

---

## What to keep

1. **Typed PlanIR + FrozenDict arguments** at the probabilistic/trusted
   boundary.
2. **System-owned compiler fields** (resources, preconditions, interruptibility,
   canonical success facts) so models cannot omit safety bookkeeping.
3. **`suspended` as non-outcome** in `NON_OUTCOME_TASK_STATES` / executive tick
   skip — PLEXIL-correct.
4. **ResumeIntent store + freshness rejection** — right primitive; finish the
   composition transaction.
5. **Hold clears intents** — correct destructive settle.
6. **Relation registry stratum** — right abstraction; make it total.
7. **Behind vs plain follow admission split** (heading only for behind) —
   preserve under ApproachOwner introduction.
8. **Owner referent → approach lane** (`sketch_navigate` → `sketch_come`) —
   correct anti-D5 (one authority for “the owner”); change *termination*, not
   the routing bridge.

---

## Recommended implementation order

Aligned with board cards; N6 does not invent a parallel roadmap.

| Priority | Card | N6 exit |
| --- | --- | --- |
| 1 | **P0-C** Atomic executive/channel lifecycle | Resume calls `resume_task` for every task suspended by the matching pause; strict xfail removed; channel enable ⇒ authorizing task active |
| 2 | **P0-D** Recovery, invariants, deadlines | Per-revision invariants; compile real bounded recovery (`max_attempts` > 1 only with executable subtree); deadline hierarchy |
| 3 | **P0.5 / skill split** | Introduce `ApproachOwner`; make `FollowFormation` explicitly persistent; adapter cannot succeed-and-forget while controller owns `base` |
| 4 | **P1-D** Relation-aware terminal witnesses | One registry drives grammar, sketch grounding, success facts, hold duration |
| 5 | **P1-A / P2-C** | `TaskRequestV1` + reactive clarification/rescan/replan subtrees consuming the fixed lifecycle |

Do **not** gate these on Nav2, MiniCPM, or InternVLA. They are substrate bugs.

---

## Evaluation claims N6 will accept

A behavior claim is only admissible if:

1. It runs through the **product** router → sketch/PlanIR → executive → adapter
   path (not a direct controller harness alone).
2. Pause/resume/cancel cases assert **paired** task and channel state.
3. Come and follow are **separate** episodes with independent predicates
   (approach settles and releases; follow remains engaged until Hold/cancel).
4. Relation success cites the **registry predicate** (and sensor-grounded
   evidence), not “task succeeded” or a failure reason string.
5. Persistent skills report checkpoint metrics without counting as terminal
   success in suite SR unless the suite explicitly scores persistence.

NAV_INSTRUCT’s measured 1/25 SR is consistent with substrate failure
(lifecycle, grounding, relation, termination) dominating model choice; N6
does not re-litigate that number.

---

## Disagreements with prior docs

| Claim | N6 position |
| --- | --- |
| README matrix N6 = social/owner-follow | That numbering is the *synthesis* matrix. This Opus wave assigns **N6 = executive/PlanIR** (`OPUS_RESEARCH_WAVE.md`). Social follow depth belongs to Opus N3 / synthesis N6. |
| “K3 closed the resume transaction” | Channel+intent path is largely closed; **product closed-intent resume is not** (N14 xfail). Docs must not say the transaction is complete end-to-end. |
| Come/follow aliasing is fine if bands match | Band geometry can match while **speech-act lifecycle** differs; aliasing `come`→`follow` is a defect at the registry layer. |
| Stronger VLM fixes instruction SR | Rejected for D1–D5; models propose, executive authorizes. |

---

## Appendix — concrete code anchors

| Finding | Anchor |
| --- | --- |
| Resume omits executive | `runtime.py` `_apply_closed_intent` resume branch (~1453–1485) |
| Executive resume API exists | `executive.py` `resume_task` |
| Come sketch = FollowFormation | `local_plans.py` `sketch_come` |
| Direct follow success while enabled | `runtime_adapter.py` `DIRECT_FOLLOW_SUCCESS_STATES` + follow branch |
| Compiler kills multi-attempt recovery | `compiler.py` `max_attempts=1` |
| Hold clears ResumeIntent | `runtime.py` `_brain_hold` |
| ResumeIntent freshness | `core/resume.py` `resume_rejection_reason` |
| Come alias → follow | `relation_registry.py` relation `follow` aliases |
| Sketch collapses to near | `local_plans.py` `sketch_navigate` |
| Product xfail | `tests/test_closed_intent_product_path.py` |
| Backlog | `backlog/NEXT.md` N14 |

---

## Bottom line

Ship **P0-C first**, then split **ApproachOwner** from **FollowFormation**, then
make the **relation registry total**. Literature (PLEXIL, ROS 2 actions, BT
recovery, SayCan/PlanBench) endorses the architecture Parcel already sketched;
the gaps are composition atomicity and success-predicate honesty, not a missing
end-to-end policy network.
