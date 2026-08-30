# MA-1 independent validity verdict

Date: 2026-08-29  
Controlling verdict: **PROMOTION REFUTED / MODEL A NOT ESTABLISHED / PHYSICAL NO-GO**

The completed run is useful negative evidence, but it is not a valid basis for
promoting the trained policy. Even if the aggregate tables are read at face
value, Model A loses to the frozen reflex and straight-to-goal references on
held-out navigation, switching, and narration. More importantly, an
independent post-run code audit found violations of the amended causal and
transactional protocol. The tables in `RESULTS.md` remain a record of what the
harness printed; they are not promotion-quality estimates.

## Results before the validity audit

- The teacher's strict held-out success was only **4.5%**. Model A reached
  **3.67%**, versus **19.83%** for the frozen reflex table and **21.67%** for
  straight-to-goal.
- Model A's masked-cue switch rate was **17.75%**, versus **91.75%** for the
  reflex table and the preregistered **90%** requirement.
- Model A narration macro-F1 was **0.5023**, below the reflex table's **0.696**;
  every predicted terminal lacked a backing receipt.
- The full-history input did not earn its place: nulling the history channels
  improved switching from **0.1506** to **0.5301** on the stated 250-episode
  slice.
- Raw motion while the owner was speaking was **1.07%**, above the 1% gate.
  The deterministic safety filter reduced all scored post-filter violations to
  zero, so this policy could only ever be considered behind that filter.
- Forward latency fit the 10 Hz research budget (2.18 ms on the test GPU,
  15.138 ms on one host CPU thread). This is a shape/host measurement, not an
  AGX Orin or end-to-end control-loop result.

## Blocking validity findings

1. **Oracle-derived state leaks into policy inputs.** `derive_event()` updates
   `f_blocked`, `f_replan`, block/replan counts, and history from gold events
   derived using simulator truth; `build_frame()` then exposes those values.
   The separate `update_own_state()` function is never called. These are not
   Model A's independently computed state as the report claims.
2. **The interruption scorer can observe the answer.** Goal channels are
   masked only for frames 0--4 after a cue, while the switch search accepts a
   response through frame 10. A bearing follower can therefore receive the new
   goal inside the scoring window.
3. **Queue/resume is scripted rather than decided.** The harness changes or
   reissues goals itself, and may resume after arrival, navigator termination,
   or timeout. Model A has no executive/global-plan proposal head and no
   admitted task transaction. This does not test the proposed Model A/Model B
   interruption architecture.
4. **Action labels are not guaranteed to be the applied action.** On teacher
   frames the discrete token can represent a gaze/hold action while the
   continuous navigation velocity is still passed to the world. The stored
   target and the actual transition can therefore disagree.
5. **The gold definition changed after prevalence was observed.** The frozen
   amendment specified the 0.65 m stop band. The run switched to the 1.2 m slow
   band after finding too few stop-band events, while the generated report
   still describes the 0.65 m definition in several places.
6. **Exact task success is not enforced.** Intermediate ordering can be
   skipped, the resumed parent can be credited after a timeout/dead navigator,
   and queue SPL does not account for the inserted child mission. Target
   identity is semantic-class level rather than an exact entity instance.
7. **Support and reporting are incomplete.** Zero-support families are absent
   from the narration macro; the report prints class supports for the teacher
   only; the required proposal head, live-executive cross-check, ASR timing
   arms, and separately trained history ablation were not run.
8. **Split/provenance controls are insufficient.** Task-kind cycles are aligned
   with scene cycles, the requested dev count differs from the cached count,
   same-seed generation is not proven deterministic, full traces are not
   persisted, and the run reports two remaining child processes at close.

Any one of findings 1--4 invalidates a promotion claim. They cannot be repaired
by reinterpreting the aggregate output; the corpus, transaction harness, and
scorer must be rebuilt and rerun.

## Decision and next experiment

Do not export `arm_C.pt` into the product, shadow controller, or robot image.
Do not use its narration candidates as completion authority. Keep the
checkpoint only as a reproducibility artifact for this failed experiment.

The corrective design is [`../model-a-stream-2/DESIGN.md`](../model-a-stream-2/DESIGN.md).
Its first step is a 300-episode teacher/causality probe, before any training:
prove a useful teacher ceiling, oracle isolation, exact applied-action labels,
real executive admission and receipt-gated queue/resume, complete trace replay,
and deterministic provenance. A failure at that probe should stop the run and
trigger a substrate fix rather than another model fit.

This verdict changes no physical readiness conclusion: MA-1 used a headless,
kinematic desktop simulator with scripted cues, no audio, no Unitree dynamics,
and no hardware. Autonomous physical motion remains **NO-GO**.
