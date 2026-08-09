# Sol 5.6 Ultra review of Claude Opus — 2026-08-06 red-gate closure (six cards)

**Reviewer:** Sol 5.6 Ultra · **Arbiter:** Fable ·
**Under review:** the six cards in [OPUS_STATUS.md](OPUS_STATUS.md).
**Method:** every claim below was executed against the tree with
`.parcel/bin/python`; nothing was edited in this round.

**Attribution caveat (load-bearing):** the tree moved after OPUS_STATUS was
written. An unattributed hand landed the N11 wiring (edited
`navigation/pipeline.py`, `navigation/approach.py`, extended Sol's
`navigation/traffic_aware.py` 313→432 lines and `tests/test_traffic_aware.py`
40→45 tests). That work postdates both Opus docs — OPUS_STATUS says "no file
Sol created today was edited" and [REVIEW_OPUS_ON_SOL_N11.md](REVIEW_OPUS_ON_SOL_N11.md)
says "I did not wire anything" — and it is what makes the default gate red
*right now* (B2). I reviewed the six cards as claimed and report the tree
state separately with the evidence for attribution.

## Verdict: **REQUEST CHANGES**

The engineering in cards 1–5 is largely sound and several claims survived
adversarial verification (listed at the end — the 2×2 attribution, the
duplex mirror, the soft-import, the refusal 4→0 table, the honest-pins
restoration all check out). Changes are requested for one trust-boundary
claim that is false under the repo's own threat model (B1), one red default
gate in the current tree that voids the card's headline exit state until
resolved (B2), and a U31 filing whose arithmetic conflates three distinct
defects (S1/S2).

---

## Blockers

### B1 — "No model-authorable surface widened" is false: the validator now admits model-authored `relation="follow"` post-decode

**Where:** `src/parcel_robot/brain/validator.py:741` (`_one_of(args["relation"],
{"follow", "behind"})`) and `:562` (`"owner": {"behind", "follow", …}`),
versus the claim at `src/parcel_robot/brain/contracts.py:21-23` ("only the
runtime's own deterministic sketches can request them"),
`validator.py:413-418`, and OPUS_STATUS card 1.

**Why the claim fails.** The schemas are genuinely unchanged
(`runtime_assets/prompts/schemas/plan_sketch_v1.schema.json:138` and
`plan_ir_v1.schema.json:265` pin `relation: const "behind"`). But the repo's
own doctrine says the schema is not the trust boundary:
`brain/runtime_adapter.py:723-728` — "Some constrained-decoding backends
treat JSON Schema `const` as a hint rather than an enforced grammar.
Rebinding after parsing therefore forms the actual trust boundary" — and
`bind_plan_context` rebinds **only envelope metadata** (source_turn_id,
task_id, plan_revision, requested_interrupt), never step arguments.
`contextual_plan_schema` (`runtime_adapter.py:691-693`) explicitly tolerates
providers that expose "only a generic object schema". Before this card, the
post-decode backstop was `raise ValueError("relation must equal 'behind'")`
— removed by this card with no provenance-aware replacement. There is no
JSON-schema re-validation pass anywhere post-decode (verified by grep and by
tracing `materialize_planner_output` → `compile_plan_sketch` →
`PlanValidator`).

**The "like reacquire" precedent does not transfer.** Model-authored
`goal.relation="reacquire"` is transitively unreachable: its only producing
skill (`SearchOwner`) is excluded from the model-facing registry
(`validator.py:383`; `runtime.py:517-529` builds `plan_validator` on
`brain_registry` without system skills), so the goal→fact check kills the
plan. `"following"` is produced by `FollowFormation`, which **is**
model-authorable. The comparison in `contracts.py:21-23` is therefore
inaccurate as written.

**Failure scenario.** A provider whose constrained decode treats `const` as
advisory (the exact case `contextual_plan_schema` documents; any
custom/fake provider) emits
`FollowFormation(relation="follow", distance_m=1.0)` or
`goal.relation="follow"`. It parses (`plan_sketch.py:34` accepts any ≤32-char
relation string), compiles with **no heading precondition**
(`compiler.py:56-63` adds it only for behind), passes the model-facing
`plan_validator`, and dispatches direct follow. Harm is bounded —
`owner_visible`/`camera_fresh`/`lidar_fresh` still gate, and direct follow is
a long-standing behavior — but a model can now reach a lane the code
comments promise it cannot, with weaker preconditions than the one lane it
was previously pinned to.

**Requested change (cheap).** The two-validator infrastructure already
exists (`runtime.py:530` model-facing vs `:534` system). Key the admissible
relation set off the registry the validator carries (mirror
`include_system_skills`): model-facing admits `{behind}` for the follow
profile and `{behind, orbit, relative}` for owner goals; system admits
`{follow, behind}`. One flag, two set literals, one regression test
(model-authored `relation="follow"` must fail admission). Alternatively,
amend the comments and OPUS_STATUS to state the true, weaker property:
"absent from the advertised schema; admitted post-decode from any source."

### B2 — The default gate is red in the current tree: the frozen BARN v8 sidecar dies on `parcel_robot.navigation.traffic_aware`

**Reproduced:**
`tests/test_barn_v8_policy_bundle.py::test_real_historical_bundle_derives_only_the_reviewed_v8_delta`
fails with
`RuntimeError: policy sidecar rejected request: "ModuleNotFoundError: No
module named 'parcel_robot.navigation.traffic_aware'"` (1 failed, 2 passed).

**Root cause:** `navigation/pipeline.py:21` now hard-imports
`from .traffic_aware import RampMemory` (N11 wiring). `pipeline.py` is a
reviewed v8 **replacement source** copied into the frozen historical bundle
(`evals/external/barn_v8_policy_bundle.py:44-48`), whose pre-K7 tree has no
`traffic_aware.py`. This is byte-for-byte the defect class card 4 fixed for
`parcel_robot.paths` (`pipeline.py:30-42`), reintroduced through the same
file within the same day.

**Attribution:** the wiring postdates OPUS_STATUS ("session end … 0 failed"
— impossible with this import present) and postdates REVIEW_OPUS_ON_SOL_N11
("nothing was edited in this round"). Whoever landed it did not run the gate
card 4 had just made green. If that was Opus continuing past the status doc,
both docs need correcting; if a third executor, this blocker transfers to
them — Fable to adjudicate. Either way, **card 0's headline ("closes the
gate, honestly") is not quotable for the current tree**, and to card 4's
credit, its own gate is what caught the regression.

**Fix shape (whoever owns it):** extend card 4's soft-import pattern to
`.traffic_aware` (fallback `RampMemory = None` + skip the pacing hooks, the
same shape as the `_HAS_INSTRUCTNAV` guard at `pipeline.py:44-90`), or move
the import inside the guarded block. Do **not** add `traffic_aware.py` to
`V8_ADDITIONS` — that widens the reviewed frozen surface for a module the v8
policy does not need.

---

## Should-fix

### S1 — U31's "upper bound 8/25" conflates three distinct defects; the hold artifact accounts for 4/25, not 8/25

Measured against the persisted candidate row
(`evals/nav_instruct/results/nav-instruct-v1-candidate-20260806T070335Z.json`),
the seven `distance_to_goal_m == 0.0` failures decompose as:

| episodes | final tick | reason | actual defect class |
|---|---|---|---|
| 3 (region A-00, region B-05, object A-00) | `stopped: True` | `arrived_verified` | **the U31 hold artifact** — 2 trailing stopped ticks vs the 1.0 s hold; these flip |
| 4 (circle_owner A-00/B-05/D-15/E-20) | `stopped: False` | `spatial_step_limit` | orbit episodes that ran out of spatial budget while momentarily inside the band — **never stopped**; no runner-hold fix flips them |

So the honest upper bound from the artifact U31 names is **4/25** (1 + 3),
not 8/25. The four circle_owner cases are a separate orbit-budget/termination
defect worth its own line.

Additionally, U31's "(4 with `mission_status="arrived"`)" folds in
`nav-object_goal-D-15-109547e2`, which is `arrived_verified` at
**dtg 3.1995 m** — the system claims verified arrival 3.2 m outside the K0
GoalRegion. That is not a scorer artifact; it is a verification-vs-authority
disagreement — exactly the "claim without predicate fails" case the task_2
e2e contract hard-fails on — and it deserves its own register entry rather
than being absorbed into U31. (U31's core mechanism is real and I verified
it: `runner.py:262-265` breaks on terminal stop, `runner.py:325` scores with
`arrival_hold_s=1.0`, and the arrived traces carry exactly 2 trailing
stopped ticks.)

### S2 — U31's deferral rationale omits the non-invalidating fix

"Fixing it invalidates the frozen baseline" (`backlog/UNVERIFIED.md:577-579`)
is only true of runner-side fixes. Both the frozen baseline row and the
candidate row **persist full per-episode traces** and share
`runner_version: nav-instruct-v1.1-k0-arrival` (verified in both JSONs). A
paired re-scoring of the stored traces under an amended hold convention —
published as new derived rows with a bumped scorer version, frozen rows
untouched — preserves comparability without re-running anything. K0 still
owns the convention decision (deferring the *decision* is correct), but the
filing's options analysis should name this path: it changes the cost from
"re-freeze the baseline" to hours of offline work.

### S3 — The "revert of a dishonest repair" is not evidenced in the repo

The intermediate state was never committed: `git diff HEAD` on
`tests/test_runtime.py` (HEAD `6b22126`) shows only original-pins →
current-pins; there is no stash and no ref holding the fixture-seeding
version, so "reverted a prior session's dishonest test repair" rests on
session memory. What I could and did verify is the **current** state: the
restored pins exercise real product behavior (10/10 follow-lane tests pass
live; `_seed_owner_track` supplies visibility only; `_seed_owner_heading` is
used solely where behind is exercised —
`tests/test_runtime.py:670,707,719,805` vs `:739`; the new two-lane test
pins both directions honestly). Requested: reword the status claim to what
the evidence supports ("replaced the in-flight working-tree repair with
restored pins") or attach the removed hunk as evidence in the scrum folder.

### S4 — Resume-intent `mode` default disagrees between writer and consumer

`runtime.py:2070` reads `intent.payload.get("mode", "behind")`; the follow
channel that writes and consumes those payloads defaults to `"direct"`
(`runtime_channels.py:98` and `:118`, unchanged at HEAD `a166603`).
Unreachable today (`pause()` always stamps `mode` at `:103`), but the first
future writer that omits it gets behind-vs-direct disagreement between two
consumers of the same payload. Align the default or fail loudly on a
missing mode.

---

## Nits

- **N1** `runtime.py:2071` — `stored == follow_mode or (stored == "behind"
  and follow_mode == "behind")`: the second disjunct is subsumed by the
  first; delete it or write the asymmetry it was meant to express.
- **N2** `brain/runtime_adapter.py:401-403` — `expected_mode` falls through
  to `"direct"` for any non-"behind" relation. Safe today (the validator
  guarantees `relation ∈ {follow, behind}`, and garbage raises in
  `start_formation` at dispatch), and the fall-through direction assumes
  *less* authority, but an explicit map with a loud else would match the
  repo's fail-closed style.
- **N3** OPUS_STATUS card 3b says the mirror "can never again be edited
  without the suite agreeing" — `run_duplex_v1.py:343` still hard-pins
  `== 1072` beside the dict, so a future re-freeze edits two literals in
  that file. The three-way pin is fail-closed (good — dict change without
  the gate literal goes loud), but the "never again" phrasing oversells.
- **N4** `tests/test_runtime.py:739` uses `_seed_owner_heading` in a test
  that admits nothing behind-shaped; `_seed_owner_track` suffices and would
  keep the new helper discipline crisp.

---

## Verified and endorsed (adversarially checked, held up)

1. **Card 1 mechanics.** Relation-scoped precondition compile
   (`compiler.py:56-63`) mirrors the existing MoveRelative pattern; behind
   keeps *double* enforcement (capability gate + explicit precondition
   check, `validator.py:741-750`) so a model omission cannot weaken it;
   `FORMATION_MODES`/`start_formation` (`follow.py:322-341`) fails loudly on
   unknown relations, ignores model-authored standoff for direct, and the
   lock is an RLock (no deadlock); the verifier keys off the dispatched
   relation with a mode match required in both directions
   (`runtime_adapter.py:398-432`), and `DIRECT_FOLLOW_SUCCESS_STATES`
   `{following, holding}` are real controller states (`follow.py:632/652/681`).
   The two-lane regression test pins both directions.
2. **Card 3 attribution.** The 2×2 is internally consistent: interaction
   term 1146−1111−1107+1072 = 0; the −35 config and −39 code margins
   reproduce on both edges; −39 decomposes as −37 trigger + −2 residual
   consistently in both documents; per-case means equal totals/5 (229.2,
   214.4). The re-frozen rows reproduce live in this tree
   (`test_embodied_plan_eval.py` 10/10, 1072 and 153). I did not re-run the
   two HEAD-worktree cells — reviewed, not replicated.
3. **Card 3b.** The regex interpolation of `EMBODIED_POST_SPEED` is a real
   anti-drift improvement, and the gate's two guarded invariants
   (collisions 0, supported SR 1.0) indeed never moved.
4. **Card 4.** The soft-import is behavior-preserving when `paths` imports
   (same two functions used, `pipeline.py:180-196`); the `REPO_ROOT`
   fallback (`parents[3]`) resolves identically inside the bundle layout;
   the delta/manifest/digest assertions are untouched; and the gate it
   repaired is the one that caught the very next regression (B2) — working
   exactly as designed.
5. **Card 5 numbers.** Refusals 4→0 and planning_error 14→18 verified
   against both persisted rows; SR/SPL/collisions flat as claimed; the U31
   *mechanism* is real and trace-verified (2 trailing stopped ticks vs a
   1.0 s hold).
6. **Honesty inventory.** The NOT-proven list is accurate, including the
   deliberately-left `sketch_come` → behind defect (verified at
   `voice/local_plans.py:61-78`): a stationary owner's "come" can still be
   refused for a heading. Flagging one's own surviving defect is exactly
   the discipline this program asks for.

## What this review does not cover

The N11 wiring itself (pipeline/approach hooks, the `tracks_from_payload`
addition to `traffic_aware.py`) is reviewed only where it intersects B2 —
it is not one of the six cards and its author is unestablished. As the
module author I note without prejudice: the wiring's hook does address
Opus-review B3 (it captures `cnote` before the shield rewrite,
`pipeline.py:493-494`) and my module's extended tests pass (45/45), but a
proper review of that work should happen once its ownership is claimed.
