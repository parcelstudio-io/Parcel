# NAV-INT-1 verdict

Date: 2026-08-29  
Evidence tier: desktop static-city simulation with text-injected commands  
Physical-motion relevance: **NO-GO**

All three preregistered hypotheses are **REFUTED**. The runner completed all
40/40 tier episodes with no harness errors, but process completion is not
capability success.

## H-NI1a — single interruption: refuted

- Admission: 24/32 = 0.750, below the 0.80 bar.
- Commands using an explicit directive admitted 14/14; amendment-cue phrasing
  admitted only 7/14.
- Amended-goal success under both system and scorer authority: 11/28 = 0.3929,
  versus a weighted from-rest rate of 0.750; delta -0.3571, below the allowed
  -0.10.
- The switch window had zero recorded collisions and zero false arrivals, with
  minimum clearance 0.829 m. Final amended-goal scoring nevertheless contained
  three false-arrival categories.

The latency of admitted transactions was acceptable in this local text harness
(p95 22.4 ms), but the runtime frequently failed to admit or finish the revised
task.

## H-NI1b — restore the original task: refuted

- Return among the nine episodes where both goals were reachable from rest:
  8/9 = 0.8889, below the 0.90 bar.
- Mean oracle path ratio: 1.4905 over eight scored successes, above the 1.15 bar.
- Across all reissues, return was only 13/34.

The queue/reissue behavior is harness-side policy, not a shipped production task
stack. The result therefore cannot establish production resume lineage even if the
numeric bars had passed.

## H-NI1c — decide keep/revise/queue/clarify: refuted

The independently frozen blind set scored 91/110 = 0.8273 overall:

| Class | Correct | Accuracy | Bar | Result |
|---|---:|---:|---:|---|
| revise | 27/30 | 0.9000 | 0.90 | met |
| keep | 28/30 | 0.9333 | 0.90 | met |
| queue | 20/30 | 0.6667 | 0.90 | missed |
| clarify | 16/20 | 0.8000 | 0.90 | missed |

The adversarial subset was 27/40 = 0.675. A later classifier scored 0.9727 on
the same cases only after inspecting their errors; that value is post-hoc and is
not promotion evidence.

## Authority and scope warning

System and independent arrival authorities disagreed on 17/80 scored legs: 11
system-failed/scorer-arrived and six system-succeeded/scorer-not-arrived. Until one
exact, independently verified arrival authority is carried through the execution
receipt, neither the controller nor the voice may infer completion from a terminal
callback.

This study used a static demo city, injected text, local deterministic components,
and no moving pedestrians, microphone, hosted voice, Go2 dynamics, or physical
sensing. It is a useful red baseline for interruption transactions; it does not
authorize navigation or speech on a physical robot.
