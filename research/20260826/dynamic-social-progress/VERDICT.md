# Dynamic social progress · independent verdict

## Decision

**REJECT every tested arm for product promotion.** Carry forward the
architecture questions and failure refuters, not these policies or thresholds.
Physical Follow, sidewalk co-walk, crosswalk entry, and elevator entry remain
**NO-GO**.

The narrow mechanism finding is confirmed: explicit free-space evidence can
prevent a missing detection from reopening motion, and venue state machines
can prevent prohibited transitions. The broader claim that these mechanisms
already produce fast, collision-free social progress is refuted.

## Independent check

I independently ran `verify_results.py --rerun` through the repository process
guard. It checked source/fixture hashes, the exact 475-case key set, unique
episode rows, hypothesis vocabulary, the stored episode digest, and a complete
fresh replay. The replay was byte-identical:

```text
932167875fd16bbd67256f60ef8b555b074bfb23fb2eb4b3695aa5051578c1ad
```

Independent extraction from the JSON confirms:

| Claim | Remeasurement | Verdict |
|---|---:|---|
| H1 visible-clear median A2 vs A0 | 1.85 s vs 0.80 s; target ≤0.60 s and ≥50% reduction | **REFUTED** |
| H1 missing-only release / occluded-survivor safety | 0 releases; 0 contacts | subcondition confirmed |
| H2 A2 false-block reduction | 6.0%; target ≥40% | **REFUTED** |
| H2 A2 completion change | −5.3 points; target ≥+15 | **REFUTED** |
| H3 crosswalk/elevator completion change | +18.2 points | performance subcondition confirmed |
| H3 semantic/moving-floor violations | 0 | semantic subcondition confirmed |
| H3 contact episodes | 20; target 0 | **REFUTED** |
| H4 critic AUROC / held-out FNR | 0.945 / 4.12%; FNR target ≤1% | **REFUTED** |
| H4 false-block change vs A3 | +3.5%; target ≥10% reduction | **REFUTED** |

All 20 A1–A4 contact episodes were independently tagged as a scripted actor
advancing into a stationary robot. That does not make the contacts acceptable;
it establishes a different failure mode. A `HOLD` command avoids the robot
driving into a person but is not necessarily a collision-free terminal action
when an oncoming person is nonreactive. The next planner needs proactive
staging/evasive candidates and enough horizon to select them before all escape
options become unsafe.

## Product-path verdict

This experiment is harness-only. It does not import the product navigation
pipeline, replay its log-odds grid, use its final reactive gate, cross the ROS/
gateway boundary, model Go2 legs/braking, run camera/LiDAR association, or
profile AGX Orin. The present physical backend supplies neither the person/
owner track contract nor motion authority. Therefore even a passing aggregate
would not have been mount evidence.

The product audit nevertheless identifies a reachable first seam:

1. extend the existing tracker/runtime serialization with time, covariance,
   existence, visibility/free-space evidence, identity and provenance;
2. keep dynamic people out of persistent geometry and reconcile hard-grid
   clearing with track lifecycle;
3. add a proposal-only typed social-progress decision before the unchanged
   final reactive disposer; and
4. extend the existing companion-nav actor rig and metrics before integrating
   a deep predictor.

## What is confirmed, refuted, and still unknown

### Confirmed in this desktop harness

- Paired deterministic replay is possible across five policy/model families.
- Requiring observed corridor evidence eliminates the tested missing-only
  resume bug.
- Semantic resource gates eliminate the tested unauthorized crossing,
  elevator capacity, and entry-before-egress motions.
- Offline AUROC can look strong while a dev-selected threshold misses its
  held-out false-negative gate and worsens closed-loop false blocking.
- A stationary hold does not resolve a nonreciprocal collision trajectory.

### Refuted

- That a conservative visibility/uncertainty mixture by itself resumes faster
  than a radial proxy.
- That CV plus stop/turn mixture alone meets the false-stall/completion/contact
  bars.
- That the tested semantic time-lattice is safe enough to carry into product.
- That the tested logistic critic improves the semantic planner on held-out
  closed-loop metrics.

### Unknown

- Natural camera/LiDAR free-space and track-existence calibration;
- identity association among an owner and a close group;
- IMM, ORCA, Trajectron++, chance-constrained MPPI, or conformal calibration on
  Parcel's product observations—the small harness only tested algorithm-family
  proxies;
- reactive-human transfer across HuNavSim/SocialGym/SocNavBench;
- crosswalk signals/vehicles and elevator doors/threshold foot placement;
- AGX p99 timing under concurrent perception, audio and local language models;
  and
- any physically safe or socially comfortable Go2 proximity.

## Verification health

- Research runner/verifier Ruff and all JSON parsing: **PASS**.
- Independent deterministic replay/integrity: **PASS**.
- Focused navigation/tracking/yield/follow/safety tests excluding the declared
  load-sensitive marker: **337 passed**.
- `test_cost_field_vectorization_performance`: **FAILED twice**, measuring
  3.03 ms in the suite and 3.67 ms isolated against a 2.00 ms threshold. Its
  source explicitly documents CPU-frequency dependence and prior unchanged-
  tree failures on this host. No related product source was changed; the red
  timing observation is preserved and not presented as an algorithm
  regression or a pass.

## Required next gate

Proceed with the default-off `SOCIAL-PROGRESS-1` research/shadow task in
`scrum/20260826/task_2/README.md`. Its next frozen test must add direct ray-level
clear evidence, safe staging/evasion, responsive and adversarial pedestrians,
association faults, product-grid replay, braking dynamics and the 1,200 + 240
qualification matrix. A learned model is only a challenger behind the same
hard envelope; no result here authorizes a physical trial around people.
