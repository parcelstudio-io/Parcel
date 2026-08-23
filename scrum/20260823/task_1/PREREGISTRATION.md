# ARCH-1 preregistration — review claims and exits

Written before Fable's review and before any implementation. A result may not
be redefined after review evidence is seen. Required corrections are appended
with attribution; original rows remain readable.

## Review subject

The subject is the architecture packet in this folder, assessed against the
tree snapshots described in `README.md`. The original audit covered the moving
Wave 3 overlay; `CLAUDE_WAVE3_DECOMPOSITION.md` now freezes its implementation
subject at `0ce1c5f8bb4a..c1b84055bd57`, with `be86b7861322` as the subsequent
index-only head. This is not a request to run, repair, or refactor that work.

## Baseline claims

| ID | Claim | Reproduction / evidence | Pass condition |
|---|---|---|---|
| B1 | Correct calendar/task location | `scrum/README.md`; inspect `scrum/20260823/` | task is `20260823/task_1`, first task for the date |
| B2 | Collision isolation | `git status --short` before/after | this author changed only `scrum/20260823/task_1/**` |
| B3 | Committed reference named honestly | `git rev-parse HEAD` | committed base begins `0ce1c5f8bb4a`; dirty overlay is explicitly unreleased |
| B4 | Current collection scale | `.parcel/bin/python -m pytest --collect-only -q` | result is recorded as snapshot evidence, not a green test-suite claim |
| B5 | Product scale | count/read Python under `src/parcel_robot` | audit method and approximate totals are stated; small drift from active Wave 3 is noted |
| B6 | Threshold census | AST parse product plus `scripts/`/`tools/`; class ≥300 lines or ≥10 methods; function ≥100 lines or decision count ≥20 | all selected symbols receive action or preserve-family disposition; test/eval functions are classified by product seam under D23 |
| B7 | No product action | `git diff --name-only -- scrum/20260823/task_1` and overall status attribution | no product/test/tool/config/deploy/index/Git-index/process mutation by ARCH-1 |
| B8 | Concern coverage | inspect `CONCERNS_REGISTER.md` and prior progress/spend/language/robotics/structure findings | architecture, physical robotics, tests/evals, language/packaging, deployment/security, Claude spend/indexing/process, and preserve/no-churn risks have named IDs and required responses |
| B9 | Moving-tree honesty | compare the integrated Wave 3 commit with the packet snapshot before dispatch | census/import/API/lock/test and high-severity concern delta is regenerated and narrowly re-reviewed; dirty corrections are not silently treated as closed |
| B10 | Exact Claude landing coverage | compare `0ce1c5f..c1b8405`; inspect `CLAUDE_WAVE3_DECOMPOSITION.md` | all new or definition-body-modified product/tooling declarations are covered by exhaustive grouped rows; all 59 non-scrum paths are classified; tests/config/CI/package/deploy assets receive a split/preserve/target-proof decision |

`B4` is collection only. It does not establish that 9,918 tests pass.

## Design claims Fable must accept or refute

| ID | Claim | Falsifier | Required disposition |
|---|---|---|---|
| D1 | Boundary isolation is a better first move than arbitrary file splitting | a proposed extraction cannot name one state/clock/lifecycle/authority owner or retains the same coupling under a new filename | require change or reject that extraction |
| D2 | Thin imports and characterization precede runtime file movement | a safe runtime extraction demonstrably has no barrel/cycle/test-harness dependency | Fable may reorder with exact evidence |
| D3 | Minimal neutral navigation evidence precedes product credential/cutover, but not the no-credential fake-Sport gateway bench | physical freshness/origin/frame authority can be represented rigorously by current `SimObservation` without side channels | reject or amend ARCH-OBS/cutover order |
| D4 | Conversation/model/audio/storage/UI must be outside the deterministic safety loop | a named operation is bounded, nonblocking, safety-essential, and has an explicit deadline/failure contract | approve only that exception |
| D5 | `RobotRuntime`, `DirectiveNavigator`, `RealtimeLane`, and `ControlManager` remain compatibility facades during migration | a clean atomic public-API migration is independently safer and reversible | require a separate approved migration card |
| D6 | `ControlManager` receives a post-native-cutover keep/retire/decompose decision | production callers/traces show internal extraction removes more live risk than preserving or retiring it | default preserve; decompose only with named evidence |
| D7 | Behavior and structure remain separately attributable | a tiny same-boundary compatibility repair satisfies the follow-up admission rule and has separate commit/evidence inside the owner-approved tranche | owner may keep it in the tranche; do not manufacture a new card solely for bookkeeping |
| D8 | New process/native boundaries need timing, crash, credential, vendor, GPU, ROS, or throughput justification | a proposed process boundary cites only file size or stylistic modularity | reject that process boundary |
| D9 | Each cutover deletes/disables the legacy live path | accepted design needs two authorities or writers indefinitely | reject unless formal arbitration and safety proof exist |
| D10 | Maximum WIP two and shared-facade cards are sequential | dependency/ownership proof shows disjoint edits and no shared state/contract | Fable may approve narrow parallelism |
| D11 | Wave 3 is retained and decomposed behind landed facades rather than rewritten or split by file size | a facade cannot preserve required behavior/authority, or a cohesive state machine is demonstrably safer as multiple owners | require the exact alternative boundary and interleaving evidence |
| D12 | The six-term stopping model and hard-capability truth table are correctness prerequisites, not cleanup | the current V1/skip paths provably cannot produce a false promotion result | Fable may refute only with an end-to-end gate trace and seeded falsifier |
| D13 | Fully resolved physical configuration, not overlay source text, is the admission subject | deep merge demonstrably deletes or invalidates inherited simulated values before any consumer can read them | otherwise require explicit deletion/required semantics and product-launcher refusal |

## Concern-review claims

| ID | Claim | Falsifier | Required disposition |
|---|---|---|---|
| C1 | Every concern is reviewed explicitly but compactly | any ID in `CONCERNS_REGISTER.md` is absent or appears in both a family/range and its exception set | verdict incomplete; use the complete non-overlapping partition; never require one reviewer per ID |
| C2 | A concern is not a card by default | Claude creates a card without a distinct authority/OWNS boundary, independent milestone blocker, or materially different evidence/approval need | amend/batch/backlog/refute/accept risk instead |
| C3 | Dirty-tree corrections remain provisional | code presence or a structural test is used to close target/physical/product-path evidence | retain `PROVISIONALLY_CLOSED_IN_DIRTY_TREE` until integration and matching evidence rung |
| C4 | The physical evidence truth table is a promotion ceiling | synthetic/replay/source evidence is described as real robot, target, HIL, stopping, localization, or human-on-body evidence | reject the promotion claim |
| C5 | Physical blockers outrank broad cognitive decomposition | audio/realtime/mission/nav refactors consume the tranche while native gateway/deploy/commissioning blockers remain unowned | reorder or explicitly justify with owner, dependency, budget, and stop gate |
| C6 | Review effort is proportional to risk | mechanical/docs work receives Tier-S multi-agent review, or writer/safety authority receives only mechanical review | require risk-tier correction |
| C7 | Spend is governed by outcomes | a tranche lacks token/cost/time/review/docs/diff budget, integrator, physical/user-value outcome, or owner stop/continue decision | do not dispatch that tranche |
| C8 | Indexing is bounded and current | a whole-repo/stale index includes archive/model/cache/PII/secret noise or has no retrieval benchmark/context manifest | reject as spend optimization until corrected |

## Test-plan claims

| ID | Claim | Pass condition |
|---|---|---|
| T1 | Equivalence and refutation are independent lanes | every card identifies both a parity oracle and an unsafe/invalid oracle |
| T2 | Scope and cadence are orthogonal | every future test has one scope and at least one cadence; tier coverage rejects orphans and forbidden target tests |
| T3 | Mocks do not satisfy process integration | process-boundary cards exercise the real boundary/subprocess with fake vendor/device only behind it |
| T4 | Golden traces do not bless known defects | known reds are labeled; safety/terminal oracles independently judge traces |
| T5 | Safety invariants are non-compensable | no aggregate quality score can turn an authority, collision, stop, stale, or false-arrival red green |
| T6 | Target timing is measured on target | x86 timings are report-only for Orin admission |
| T7 | Physical statistics state denominator and maximum | dry/no-writer→one inspected pulse→3–5 inspected stops precedes repetition; milestone campaigns then use ≥30 repeats and median/p95/max; p99 requires ≥1,000 automated events in its own domain |
| T8 | Evidence strength is labeled | every artifact states scope, origin, hashes, denominator, and `does_not_prove` |
| T9 | Test restructuring preserves hard-gate addressability | existing named node IDs remain or an explicit checked old→new mapping lands first |
| T10 | Coverage/mutation ratchets are changed-code first | no blanket percentage creates fake urgency or rewards deleting difficult tests |
| T11 | Wave 3 test restructuring is seam-owned | the 8,863-line card suite receives a checked old-node→new-node map; protocol fakes are shared only after stable contracts; source-shape pins are removed only after stronger behavioral/boundary mutants exist |
| T12 | Target truth cannot be skipped into green | missing hard capabilities, native tooling, target artifacts, or required six-term evidence produce nonzero incomplete/fail in the applicable promotion mode; fake/QEMU/structural evidence remains explicitly below target proof |

## Proposed initial structural thresholds

These are no-new-debt gates, not a demand that the existing tree immediately
meet them:

| Threshold | Initial rule |
|---|---|
| new product class | no class over 1,000 lines |
| new function | no function over 100 lines |
| new constructor | no constructor over 150 lines |
| new complexity | no function above approximate/C901 20 |
| dependency graph | no new cycle or forbidden reverse edge |
| concurrency | no new lock/thread/callback edge without owner/order/deadline test |
| typing | new contract and critical-boundary modules strict clean; no new boundary `Any` |
| tests | no new source-shape/marker/card-history pin when behavior or interface is observable |

Each accepted extraction lowers the applicable existing facade's baseline. A
card does not pass by moving the same metrics into a sibling monolith.

## Risk-tiered implementation-card preregistration

Every card has one compact core row: exact `OWNS`/caller/boundary, before/after
owner, relevant oracle, rollback, `does_not_prove`, risk tier, integrator and
reviewer, tranche budget/stop gate, and concern IDs addressed. Additional
ceremony is proportional to risk:

| Tier | Required evidence before measuring |
|---|---|
| S — writer/safety/physical authority | Full characterization and known-red split; unit/property/mutation refuters; real process/product path; relevant replay/SIL/target/HIL/physical progression; deadline/resources/denominator; boot-disarmed rollback; legacy-writer deletion/disablement |
| B — state/contract/process boundary | Facade/callers and compatibility; one independent unsafe oracle; real boundary/product-path integration; simplification/forbidden-edge result; rollback and budget |
| M — mechanical/docs/import-only | One-page scope; automated compatibility/lint/structure check; sampled review; reversible commit and tranche budget |

Irrelevant mutation, process, replay, HIL, physical, performance, or human rows
use one `not applicable — <reason>` cell, not a bespoke essay. Physical/human
30-repeat campaigns occur only at capability/behavior/provider/audio milestone
gates, never per Tier-M/B structural card. Cost data is one generated row per
card and one owner summary per tranche; token/$ may be `unknown` when unavailable.

## Mandatory return conditions

Fable must not accept an implementation sequence if any of these applies:

- wiring is demonstrated only through source/AST inspection;
- fake-only evidence is promoted as hardware/physical evidence;
- an unsafe registered mutant survives or a hard row skips;
- timing is borrowed from x86 for an Orin gate;
- fixture/hash baselines are re-pinned without cause and attribution;
- test credentials or simulator origins appear in a physical profile;
- the cutover leaves a second writer or competing authority live;
- evaluator failure can truncate later rows or emit invalid/missing JSON;
- behavior change and structure change are mixed without owner authorization;
- rollback, exact denominator, or `does_not_prove` is missing;
- the change reduces line count but not state/coupling/authority complexity;
- any concern ID is omitted from family/exception coverage, or a provisional
  dirty-tree fix is treated as integrated/target/physical proof;
- follow-up cards are generated one-per-note without the admission rule;
- a tranche lacks explicit spend/compute/review/documentation limits and an
  owner stop/continue decision.

## Review completion condition

ARCH-1 remains `REVIEW-ONLY / NOT DISPATCHED`. Fable's initial
`ACCEPT_WITH_REQUIRED_CHANGES` verdict covers the original eight files and all
147 concern IDs, and it records X08/X16's integration/census requirements as
closed. The later `CLAUDE_WAVE3_DECOMPOSITION.md` adds B10, D11–D13, T11–T12,
six new review questions, and exact false-green/config/lifecycle evidence; it
requires a narrow supplement, not a repeated broad review. No verdict
vocabulary is execution authority. Each remaining blocker gates its affected
milestone. Only the owner may approve a dependency-safe tranche after every
required change has a named owner, boundary, falsifiable regression,
budget/stop gate, and re-review result. The accepted output is a small set of
boundary-owned tranches containing bounded cards, not one card per concern or
one mega-card.
