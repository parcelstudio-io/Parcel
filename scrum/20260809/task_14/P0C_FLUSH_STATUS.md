# P0-C — atomic proposal-buffer flush on a plan_revision correction

Status: IMPLEMENTED + unit-gated green. Product-path wiring is a 2-part HANDOFF
(runtime.py is sibling-owned this wave; navigation/** is frozen for this card).
Sol 5.6 Ultra + Opus, 2026-08-09.

## The defect (recap)

When the owner corrects a mission ("no, the other lamppost") the executive
increments `plan_revision` and invalidates the old plan (`replace()` +
strictly-increasing revision + lease release). But `SE2Goal` proposals already
buffered in `ProposerBus`/`GoalArbiter` from the OLD revision were never flushed,
so a superseded-revision proposal could still win `GoalArbiter.resolve` and
briefly steer the body toward the abandoned target before the new plan's
proposals arrive. Safety-relevant (wrong-target motion after a correction),
bounded by the collision gate (never a collision — transient wrong-place pursuit
only). `instructnav/arbiter.py` carried NO revision/epoch key; the executive's
atomic lifecycle did not extend to the learned buffers. This card closes that.

## Mechanism (where it lives)

Revision-key + flush, all inside the brain/arbiter layer, no runtime.py edit:

1. **`src/parcel_robot/revision.py` (NEW pure leaf module).** Defines the
   revision/epoch key type: `PlanRevision` alias, the `RevisionSink` Protocol
   (a proposer buffer the executive can flush), and `CommittedRevisions` — a
   monotonic, per-`task_id` ledger with the single `is_stale(...)` rule
   ("older than committed == stale"). Pure (stdlib+typing). Lives at the top
   level ON PURPOSE: `brain` and `core` both transitively import `navigation`,
   which imports `instructnav.arbiter`, so importing either from the arbiter
   would cycle. `parcel_robot/__init__.py` is trivial, so this leaf is importable
   by both the executive (brain) and the arbiter (instructnav) with no cycle
   (verified by importing pipeline + executive + arbiter together).

2. **`src/parcel_robot/instructnav/arbiter.py`.**
   - `SE2Goal` gains `task_id: str = ""` and `plan_revision: int = 0` (defaults
     keep every existing caller and the navigation pipeline byte-for-byte
     backward-compatible; added to `as_dict()`; `plan_revision < 0` rejected).
   - `ProposerBus` owns a `CommittedRevisions`. **The FLUSH** is
     `commit_revision(task_id, plan_revision)`: monotonic-commit, then atomically
     drop every buffered goal now older than the committed revision. `publish()`
     and `poll()` refuse to (re-)buffer a stale proposal (fail-closed — closes
     the re-publish-after-flush window). Adds `committed_revision()` and a
     `committed_revisions` key to `snapshot()`.
   - `GoalArbiter` owns a `CommittedRevisions`. **The REJECT gate** is one
     additive `continue` at the top of the `resolve()` viable-filter loop:
     a proposal older than the committed revision can never win. Adds
     `commit_revision()` / `committed_revision()`. Both `ProposerBus` and
     `GoalArbiter` structurally satisfy `RevisionSink` (no import of the module
     needed).

3. **`src/parcel_robot/brain/executive.py`.** `TaskExecutive.__init__` gains
   `revision_sinks=`; `register_revision_sink(sink)` (idempotent by identity;
   rejects a sink without a callable `commit_revision`). `_activate_replacement`
   — the single choke point every replacement activation flows through
   (`replace()` immediate + `report()` at-checkpoint + `report()` after-step) —
   ends by calling `_notify_revision_committed(record)`, which fires
   `sink.commit_revision(task_id=record.task_id, plan_revision=record.plan_revision)`
   for every sink **inside the executive lock**, i.e. in the SAME transaction as
   the record's revision bump. No sinks registered ⇒ zero behavior change.

The trigger is from WITHIN the executive/arbiter layer (executive holds the sinks
and self-fires on replacement activation) — no runtime.py trigger needed for the
flush itself. Timing is exact: the buffer is flushed the instant the replacement
becomes the committed steering plan, and NOT during the `defer` window (while the
old plan is still legitimately active, old proposals still legitimately win).

## Gate results (tests/test_p0c_proposal_flush.py — 9 tests, all green)

- (a) STALE PROPOSAL REJECTED: after `commit_revision(nav, 2)`,
  `GoalArbiter.resolve` returns `None` for a revision-1 proposal, and picks the
  fresh one head-to-head. (`test_goal_arbiter_rejects_stale_revision_and_accepts_fresh`)
- (b) BUFFER FLUSHED ON replace(): with `ProposerBus`+`GoalArbiter` registered as
  sinks, a queued nav task at rev 1 holds a buffered stale grounder proposal;
  `executive.replace(rev 2)` activates immediately and the bus buffer is `{}` the
  instant it returns; committed==2 on both sinks; the stale proposal resolves to
  `None`. Also proven via the deferred running→checkpoint path
  (`test_executive_replace_flushes_proposer_buffers_immediately`,
  `test_executive_checkpoint_replacement_flushes_buffers`).
- (c) FRESH PROPOSAL WINS: a revision-2 proposal buffers and wins normally after
  the commit (covered in the same tests + `..._commit_flushes_stale_and_blocks_restale`).
- Ledger monotonicity + fail-closed + per-task keying
  (`test_committed_revisions_is_monotonic_and_fail_closed`).
- Fail-closed re-publish and stale `poll()` emission dropped
  (`..._commit_flushes_stale_and_blocks_restale`, `..._poll_drops_stale_emissions`).

## Proof: veto/collision + pause/resume semantics UNCHANGED

- **GoalArbiter veto/lethal/TTL unchanged (asserted).**
  `test_stale_rejection_is_additive_to_ttl_and_lethal_vetoes` re-runs the shipped
  veto scenario verbatim on a default (uncommitted) arbiter → still picks "b";
  then proves committing a revision does NOT relax a lethal veto (a fresh-revision
  lethal goal is still `None`) and the mixed-waypoint `all()`-lethal rule
  (arbiter.py `:141` original) is intact. The new gate is a pure additive
  `continue` before the untouched TTL/lethal checks — it can only reject more, never
  admit a previously-vetoed goal. Collision gate untouched (arbiter never authors
  velocity; grid_v1/collision path not modified).
- **Pause/resume (ResumeIntent) unchanged.**
  `test_suspend_resume_does_not_flush_or_bump_revision`: with sinks registered, a
  suspend→resume cycle does NOT flush the buffer and does NOT bump the committed
  revision (the flush fires ONLY on replacement activation). `test_resume_transaction.py`
  green. Existing `test_brain_executive.py` (incl. correction/defer/checkpoint,
  suspend, replace) all green — no plan_revision/lease/resume regression.

## HANDOFF (product-path wiring — for the coordinator; do NOT let me edit these)

The unit gate fully proves the mechanism at the arbiter+executive boundary using
the REAL `ProposerBus`/`GoalArbiter`. To make it live on the product path, TWO
wirings are needed in files outside this card's ownership. Until both land, the
flush is a correct no-op on the product path (backward-compatible): the pipeline
publishes proposals under the default key `("", 0)`, which never matches a
committed real-task key, so nothing is wrongly rejected.

### Handoff 1 — register the nav channel's buffers as executive sinks (runtime.py)

Insertion point: `runtime.py`, `_start_or_resume_navigation_locked`, immediately
after `navigator = self.dog.navigator` (currently line ~2836). Idempotent by
identity, so calling on every nav start is safe:

```python
        navigator = self.dog.navigator
        # P0-C: bind the executive's committed plan_revision to this channel's
        # learned-goal buffers so a correction atomically flushes stale proposals.
        for _sink in (navigator.proposer_bus, navigator.goal_arbiter):
            if _sink is not None:
                self.task_executive.register_revision_sink(_sink)
```

(`proposer_bus`/`goal_arbiter` are `None` when instructnav is absent — the guard
keeps historical BARN bundles loading. If the navigator is ever rebuilt, its
fresh bus/arbiter are re-registered; the stale ones simply stop receiving
proposals — harmless, but the coordinator may prefer to reset the sink list on
navigator teardown.)

### Handoff 2 — stamp published proposals with (task_id, plan_revision) (navigation/pipeline.py)

The committed side is keyed by the executive's real `(task_id, plan_revision)`.
The two `SE2Goal(...)` constructions in `navigation/pipeline.py` (`:1522` grounder
"align_then_translate", `:2353` "search_entity" frontier) currently omit
`task_id`/`plan_revision`, so they default to `("", 0)` and never match the
committed key — the flush/reject is inert on the product path without this.

Thread the active nav mission's `(task_id, plan_revision)` into the navigator and
stamp both constructions, e.g. add `task_id=self._active_task_id,
plan_revision=self._active_plan_revision` to those two `SE2Goal(...)` calls, where
`_active_task_id/_active_plan_revision` are set by a small
`navigator.set_active_revision(task_id, plan_revision)` called from runtime's
plan-accept/replace path (`runtime.py` ~line 1080, where `plan.task_id` /
`plan.plan_revision` are in hand) or from the semantic nav dispatch adapter (the
`DispatchRequest` carries both). Same `task_id` string on both the executive
(record.task_id) and the pipeline proposals is what makes the key match.

### Product-path validation (handoff)

Closest faithful repro achievable without touching frozen files is
`test_executive_replace_flushes_proposer_buffers_immediately` — it drives the
"no, the other lamppost" correction through the REAL `ProposerBus`+`GoalArbiter`
registered as executive sinks and proves the stale proposal is flushed+rejected
and the fresh one wins. Full sim product-path validation ("the correction not
transiently steering to the old target") should be run by the coordinator after
Handoffs 1+2 land.

## Verify summary

- Files touched (owned): `src/parcel_robot/revision.py` (new),
  `src/parcel_robot/instructnav/arbiter.py`, `src/parcel_robot/brain/executive.py`,
  `tests/test_p0c_proposal_flush.py` (new). No edits to runtime.py, navigation/**,
  camera_channel/**, detection_adapter/**, tiered_memory.py, dynamic_prompting.py,
  .github/scripts/ci*, frozen packs.
- ruff: my 4 files clean (`All checks passed!`). The 51 repo-wide ruff errors are
  all in untouched files (storefront/detection_adapter/uwb/voice/camera_channel/
  bags/route_memory/…, several in the do-not-touch set) and pre-exist this card.
- No frozen digest moved (no frozen pack / digest file touched; `SE2Goal.as_dict`
  gains keys but no frozen digest consumes the proposer snapshot — checked).
- Full default suite: `3125 passed, 21 skipped, 2 xfailed, 5 warnings` (exit 0,
  814s). Run before the two siblings landed; the coordinator will run the
  consolidated verify once the runtime.py sibling + the gesture-session lane land.
  The 5 warnings are pre-existing/unrelated (geometry ROBOT_FOOTPRINT_RADIUS_M
  deprecation; an endpointing Smart-Turn onnx fallback RuntimeWarning) — none from
  this card's files.

## Product-path activation

The two handoffs above are now LIVE on the product path. The flush is no longer a
dormant no-op keyed by `("", 0)`: a real correction now flushes the proposer
buffer atomically AND rejects any straggler proposal authored under the
corrected-away revision. Wiring only — consumed the frozen revision.py / arbiter.py
/ executive.py contracts unchanged; no contract gap forced a stop.

### Edits, by site

**`src/parcel_robot/navigation/pipeline.py` (DirectiveNavigator revision plumbing):**
- `__init__` (after `self.goal_arbiter = ...`, ~:261): initialize the active-stamp
  fields `self._active_task_id = ""`, `self._active_plan_revision = 0` (default
  `("", 0)` = the backward-compatible unwired key).
- New method `set_active_revision(task_id, plan_revision)` (before the `paused`
  property, ~:607): stores `(_active_task_id, _active_plan_revision)`.
- Grounder `SE2Goal(source="grounder", ...)` (align_then_translate, ~:1522→now
  ~:1550): added `task_id=self._active_task_id, plan_revision=self._active_plan_revision`.
- Frontier `SE2Goal(source="search_entity", ...)` (~:2353→now ~:2382): same two
  kwargs added.
  The navigator exposes `proposer_bus` / `goal_arbiter` as named attributes exactly
  as the handoff assumed — no adaptation needed.

**`src/parcel_robot/runtime.py` (the two handoffs + backward-compat plumbing):**
- `__init__` (~:505): `self._active_nav_revision: tuple[str, int] = ("", 0)`.
- New helper `_apply_active_nav_revision(navigator)` (before
  `_start_or_resume_navigation_locked`): stamps a navigator with
  `_active_nav_revision` iff it exposes a callable `set_active_revision` (historical
  BARN bundles without it stay compatible).
- **Handoff 1** — `_start_or_resume_navigation_locked`, right after
  `navigator = self.dog.navigator`: registers `navigator.proposer_bus` and
  `navigator.goal_arbiter` as executive revision sinks (guarded `is not None`), then
  `self._apply_active_nav_revision(navigator)` so a nav that cold-starts AFTER the
  plan was accepted still picks up the committed key (the navigator is lazily built
  at first nav start, after `_accept_plan`).
- **Handoff 2** — `_accept_plan`, right after the `if not submission.accepted`
  guard (the `plan_revision` commit point, ~:1080 region): records
  `self._active_nav_revision = (plan.task_id, plan.plan_revision)` and stamps the
  navigator if one is already built (`getattr(self.dog, "_navigator", None)` — avoids
  force-constructing the navigator on a voice-only, nav-config-less runtime). A
  correction reaches this after `executive.replace()` has already fired the
  sink flush in its locked transaction, so the flush (old proposals dropped) and
  the new stamp (next proposals carry the new revision) compose in the right order.
  `record.plan_revision == validated.plan.plan_revision`, so the navigator's stamp
  is byte-identical to the key the executive flushes the sinks with — the match is
  exact.

### The honest proof (new test, own file)

`tests/test_p0c_flush_product_path.py` (2 tests, both green) drives a **real**
`RobotRuntime` + real `Dog`/`DirectiveNavigator` + real `ProposerBus`/`GoalArbiter`
/`TaskExecutive`, with **real revision stamping (never the `("", 0)` default)**:

- `test_correction_flushes_stale_and_never_reapproaches_old_target`: "go to the
  lamppost" accepted at rev 1 → nav start registers the live navigator's real sinks
  (asserted `is`-identity on the executive's sink list) and stamps the navigator
  `(nav-mission, 1)`; a grounder proposal toward the OLD target (10,0) — built the
  way the pipeline's publish sites build it, stamp read FROM the navigator so
  `plan_revision == 1`, not `0` — wins pre-correction (the body would head to OLD,
  correct then). Then the correction commits rev 2 via `executive.replace` on the
  real runtime executive: **(a)** the navigator's proposer buffer holds no
  old-revision goal and both sinks report `committed_revision == 2`; **(b)** six
  traced post-correction ticks — with an old-revision straggler re-firing each tick
  — never command the OLD pose (`OLD_TARGET not in commanded_poses`; the straggler
  is fail-closed out of the buffer and `resolve` returns `None` for it every tick);
  **(c)** the NEW target (-8,3) published under rev 2 is pursued (`resolve` returns
  it). Old target is never re-approached.
- `test_unstamped_navigator_default_key_is_a_safe_no_op`: an unstamped navigator
  keeps `("", 0)`; committing a real task's rev 1→2 on the sinks does NOT touch its
  default-key proposal — the flush is a correct no-op without stamping (this is the
  exact property that kept the dormant version safe, now proven as the flag-off
  floor).

Sim-e2e handoff (noted, as the card allows): the pipeline's OWN `SE2Goal` publish
sites fire only inside the semantic-grounding / frontier paths, which need a full
grounder scene (the POI/stub `dog.navigate` path takes a POI goal directly and
publishes nothing — verified). A `handle_text`-through-sim repro that reaches those
sites with rendered detections is left as a follow-up; the integration test above
exercises the identical stamp value the pipeline reads (`navigator._active_task_id`
/`_active_plan_revision`) and the identical real executive→sink flush transaction.

### Verify (authoritative gate)

`.parcel/bin/python scripts/ci_gate.py --tier commit` → **RESULT: PASS — every hard
gate green** (exit 0, 99.9s):
- ruff HARD: 38 violations, baseline 39, **new 0** (touched files clean).
- hard-safety HARD: nav frozen baseline collisions=0 false_arrival=0; mutation panel
  clean; follow-bench hard_collision_total all 0.
- frozen-digest-sentinels HARD: 2 immutable manifests byte-identical to pin.
- model-off-non-inferiority HARD: 23 passed.
- **frozen-digest-integrity HARD: 6 passed** — nav_instruct v3 digest UNMOVED (this
  is wiring, not a scored-episode behavior change: eval episodes never stamp a real
  revision, so proposals stay at the default `("", 0)` key exactly as before; also
  cross-checked directly: `test_nav_instruct_episodes_v3.py` +
  `test_nav_instruct_episodes_v2.py` = 32 passed).
- mutation-panel-freshness HARD: passed. latency-tail HARD: passed.
- default-suite HARD: **3140 passed, 9 skipped, 34 deselected, 5 warnings** in 97.26s
  (includes the 2 new product-path tests). Existing arbiter/executive/pause-resume/
  nav suites re-run green out of band (`test_p0c_proposal_flush` +
  `test_brain_executive` + `test_instructnav_arbiter` + `test_resume_transaction` +
  `test_navigator_pause` + `test_navigation` = 70 passed).

### Files touched (owned only)

- `src/parcel_robot/navigation/pipeline.py` (DirectiveNavigator revision plumbing).
- `src/parcel_robot/runtime.py` (the two handoffs + `_apply_active_nav_revision`).
- `tests/test_p0c_flush_product_path.py` (new).
No edits to revision.py / arbiter.py / executive.py (contracts consumed as frozen),
camera_channel/detection_adapter, tiered_memory/dynamic_prompting, frozen packs, or
.github/scripts/ci*. (runtime.py already carried the sibling runtime-activation wave's
edits — camera ingress B4, LLM summarizer — untouched by this card; the P0-C blocks
interleave cleanly.)

### One safety note (not a stop)

`_accept_plan` records `_active_nav_revision` for EVERY accepted plan, including a
voice-only plan, then stamps the navigator. In the realistic flow a nav mission IS a
brain task whose `_accept_plan` is the last accept before nav publishes, so the stamp
is the nav task's — exact. The only degenerate interleaving (a voice plan's key
stamped onto a direct-voice-nav that never went through `_accept_plan`, then that
voice task corrected) drops nav proposals for a single tick and self-heals next tick
(the navigator re-proposes under the bumped key) — a brief safe stop, never
wrong-target motion, and the collision gate is untouched. A nav-plan filter could
tighten this later; left as-is to match the handoff's literal `set_active_revision`
call at the plan-accept site.
