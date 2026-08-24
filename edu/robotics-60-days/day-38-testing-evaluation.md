# Day 38: Testing and Evaluation

## Mental model

Robotics testing is a pyramid with honesty labels. Unit tests lock contracts. Property tests stress invariants (TTLs, clamps, preemption). Headless scenarios catch task regressions. Monte Carlo / fault injection explores nuisance regimes. External benchmarks are proxies. HIL and fenced hardware are scarce and expensive—so software must earn the right to touch them.

```text
prove a claim  ⇒  name the harness, seed, embodiment, and does_not_prove
```

Parcel’s culture (D11): product companion scenarios are the admission gate; BARN and friends are frozen proxies that must not silently rewrite behavior.

A useful test names four things up front: **claim**, **harness**, **embodiment**, **non-claim**. “Follow succeeds in sim seed 7 with perfect tracks” is a claim; “safe around strangers on wet tile” is not implied. Property tests (leases always expire; E-stop dominates priority; forbidden PlanIR keys reject) catch classes of bugs scenario lists will miss.

Fenced-hardware tests are scarce: script them like incident drills—preconditions, abort criteria, data to capture (ages, shield reasons, stop latency)—not like feature demos. One clean stand measurement of lease→stop beats ten sidewalk anecdotes.

## Software-engineering analogy

This is staging + SLOs + chaos engineering, not “we have pytest.” A green microservice CI does not prove multi-region failover; a green headless orbit does not prove wet-tile Sport tracking. Contract tests are cheap; production canaries are not. Write `does_not_prove` the way mature teams write incident “non-goals.”

**Tradeoffs:**

- Over-mocking → fast tests that cannot fail the real bug.
- Full-stack every PR → flaky, slow, avoided.
- Optimizing proxy benchmarks → Goodhart; keep adapters from changing product semantics (D11).

## Light equations (eval accounting)

```text
claim_valid ⇔ evidence_covers(claim)
            ∧ embodiment_match
            ∧ ¬contradicted(does_not_prove)
```

If the bench drives a controller directly while production routes through PlanIR + executive, say so—as `FollowBenchRunner` comments do.

## ASCII diagram

```text
  pytest contracts (arbiter, executive, ControlLimits)
            |
            v
  headless_city / companion scenarios (seeded)
            |
            v
  Monte Carlo + fault (drop scan, delay cmd, swap ID)
            |
            v
  external proxy (BARN, …) ---- adapter ---- frozen protocol
            |
            v
  HIL / stand / fenced hardware  (rare; gated)
```

## Map to Parcel / Go2

From `DESIGN_DECISIONS.md` D11, `evals/`, and runtime harnesses:

- Brain/executive tests encode interrupt and lease fights without motors.
- `HeadlessCityQualityHarness` exercises city tasks on observation contracts.
- Companion nav benches measure follow/search/interruption with explicit feature flags and `does_not_prove` lists in JSON reports.
- External BARN corpora track provenance; improving a proxy must not weaken reactive shields.
- Physical gates remain ahead: Sport lease/axes/frame commissioning before any “works on dog” claim.

**Design choice:** append-only eval ledgers with date, run id, change note, metrics, and non-claims. Cost: ceremony. Benefit: prevents demo amnesia.

Monte Carlo without fault injection only averages luck. Prefer a small matrix: drop LiDAR for N ticks, delay `MotionIntent` renewals, swap owner ID briefly, inflate command TTL, and assert shield/executive outcomes. HIL belongs after those are green: same `ControlManager` binary path, constrained plant, recorded stop latency.

Unit and property tests remain the cheapest place to lock Module 4 invariants: forbidden PlanIR keys, arbiter priority, lease expiry → stop, E-stop dominance, and `PreemptionTable` decisions. Scenarios then prove *tasks*; properties prove *walls*.

**Codebase anchors (tests / evals):**

- `tests/test_brain_executive.py` — `ResourceLocks`, preemption/voice policy.
- `tests/test_*` around control/arbiter/safety — contract walls for TTL/E-stop/clamps.
- `simulation/headless_city.py` → `HeadlessCityQualityHarness.run` — product-shaped city tasks.
- `evals/companion_nav/runner.py` → `FollowBenchRunner`, `_DispatchReplica`; comments + report `does_not_prove`.
- `evals/companion_nav/metrics.py` → `EpisodeMetrics` / `StepRecord`.
- `evals/companion/` / `evals/external/` — planner quality, duplex, BARN proxies; schemas require `proves` / `does_not_prove` in several report types.
- `evals/companion_nav/scenarios.py` — interruption-correctness scenarios tied to honesty boundaries.

Promotion rule of thumb: a change that improves a proxy but weakens `apply_reactive_safety`, lease expiry, or PlanIR validation is a regression—even if a leaderboard moves up. Keep adapters translating interfaces, not rewriting Parcel margins (D11). Record the rejected tradeoff in the eval ledger so the next pull request cannot rediscover it as “new.”

## Failure story

A PR “fixed” BARN scores by shrinking inflation until the proxy liked narrow gaps. Companion headless follow then clipped owner keepout more often; the reactive person brake masked it in one seed and failed in another. Because the BARN adapter had started tuning product margins, the proxy became the product. Rollback restored shields as authority and marked the BARN gain as non-admissible for companion release.

## Retrieval questions

1. What must an eval report state besides the headline success rate?
2. Why can a `_DispatchReplica` jerk metric not authorize a sidewalk speed raise?
3. (Week-back) How should Day 30’s sidewalk/lamppost synthesis tasks appear in the test pyramid vs a single demo video?

## Optional 10-minute exercise

Open one recent JSON under `evals/companion_nav/results/` and copy its `does_not_prove` list. For each bullet, write the next cheaper test that would shrink that gap—and the first hardware test that would still be required afterward.
