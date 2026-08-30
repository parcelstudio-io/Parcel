# Product evaluation results — 2026-08-29

## Executive summary

| Evaluation | Exact result | Controlling interpretation |
|---|---:|---|
| NAV_INSTRUCT v4 | 34/125 success = **0.272 SR**; SPL 0.205777; mean DTG 8.193 m | Generalized instruction navigation is red |
| NAV_INSTRUCT repeat | Same episode digest and exact aggregate metrics | Failure is reproducible, not a transient run |
| Follow bench | **7/9** follow, 2/2 navigate; 0 contacts in this script set | Two follow scenarios fail; scripted/oracle sensing only |
| Embodied plan v1 | 4/4 supported cases pass; 1 unsupported; 0 collisions | Product-path integration evidence, not generalization |
| Brain v1 | 15/15 cases; 7/7 expected fail-closed | Typed authority boundary works on frozen cases |
| Duplex v1 | 7/7 scripted hard gates | Text-injected timing only; no audio or production model |
| Corrected acoustic v2 | 25 cases / 223.4 s; **6 pass, 3 fail, 2 not measured**; 4/13 endpoint cases invalid; virtual-audible ack p50 0.790 s | Measurement is repaired on the virtual rig; endpoint semantics and acknowledgement remain red, isolated acoustic STOP and physical motion sync are unmeasured |
| Endpoint-policy sensitivity | Two identical 1,560-cell runs; 0/30 declared points pass; corrected-rig parity fails | No production endpoint setting or provisional motion admission is supported |
| Historical Realtime corpus | 0 machine hard failures; 66 review flags | Machine checks pass but semantic quality is poor/mixed |
| Personal conversation fixture | 13/13 contract turns | Reference ceiling only; provider is a deterministic fixture |
| DSP-2 dynamic social | 580 episodes; S2/S3 each contacted in 25/145; H1–H4 refuted | No sidewalk/crosswalk/elevator or safe-proximity promotion |
| MB-1 hosted Q | 120/120 scenarios; every absolute gate failed | Current hosted candidate is refuted; paired direct/human effects unmeasured |
| DMC-4 transaction | Two identical 1,824-mutation runs; 256/256 corruptions; post-review lineage/drain-expiry and valid-lifecycle regressions pass | Journal → process-local Model-B frames preserves and drain-revalidates available authority lineage; valid next-step waits and deferred replacement progress no longer false-latch narration, but commit-time timestamp/live session/provider/audio/persistence remains red |
| DSOAK-1 durability | Artifact self-reports 12.050004 h, 66,434 episodes, and 664 sampled replays / 0 recorded mismatches; 17/17 predicates pass post-run aggregate checks | Partially corroborated desktop procedural durability only; strict temporal/process provenance is absent, monitor is late, narration oracle is refuted, safety counters are coupled, and there is no learned promotion |
| Repository gates | Latest commit tier green over 11,330 selected non-slow tests (11,417 total; 87 slow); extended nightly red on degraded-pose floors. Post-remediation slow rerun: 1 failed / 74 passed / 8 skipped / 3 xfailed / 1 xpassed; sole failure is a retained 0.875-vs-0.90 person-cell pin | Software/evaluation evidence only. A quiet repeat matched start/end checkout identity; nightly remains a release-readiness blocker and says nothing physical is safe |

## Navigation and instruction following

### NAV_INSTRUCT v4

Both invocations selected the identical frozen episode set, digest
`e7c302ddf19a39646aff77f01832be56b14fae6c7d4bd28e39cd5045c3c8b3f2`,
and returned the same aggregate measurements:

- episodes: 125
- success: 34/125 = 0.272
- frozen-rule baseline success: 0.136
- SPL: 0.2057774523279327
- mean distance-to-goal: 8.19327867142933 m
- simulator collision count: 0
- failures: 36 planning, 24 termination, 13 grounding, 11 search, 7 false
  arrival, 0 control, 0 refusal, and 34 successful (`none`)
- authority labels: 91 agreement, 25 disagreement, 7 false arrival, 2
  tolerated boundary

The exact aggregate repeat is strong reproducibility evidence.  It is not evidence
of sufficient capability: 91/125 episodes did not succeed.  Simulator ground-truth
semantics also bypass camera/perception generalization.

### Follow bench

Two invocations reproduced exactly:

- 11 total cases: 9 follow and 2 navigation
- 7/9 follow success; 2/2 navigation success
- zero hard collisions and zero pedestrian contacts in this scripted corpus
- minimum pedestrian surface distance 0.53 m
- 2.3 s total personal-space intrusion; zero intimate-space time
- mean desired-band occupancy 0.7092453494
- mean shaped commanded jerk 1.1928 m/s^3, compared with 0.5135 m/s^3 on
  nominal-jerk episodes
- two reactive-gate stops

The failed follow scenarios are `pedestrian_group` and `pedestrian_cut_in` under the
bench's success contract.  The bench uses an identity-perfect scripted owner track,
fixed non-reactive pedestrian trajectories, kinematic base motion, and no camera
re-identification.  It therefore cannot certify sidewalk or crosswalk behavior.

The controlling same-day DSP-2 study used 29 held-out families × 5 seeds × 4
arms: **580 episodes, 145 per arm**. Contact episodes for S0/S1/S2/S3 were
57/37/25/25. Every S2/S3 contact was a scripted actor moving into a stationary
dog; both arms had zero contacts in the narrower 45-case non-responsive stratum
but failed on responsive actors and tight elevator/sidewalk families. S3 also
increased false-block time from S2's 805.6 s to 966.5 s (**+19.97%**) and
reduced completion. All four frozen hypotheses were refuted. Attribution does
not make contact acceptable, and this authored 2-D result supplies neither a
physical contact rate nor permission to learn a universally smaller distance.

### Embodied plan v1

The five-case frozen production-path run reported:

- four supported cases, all four passed
- one unsupported case (`FollowFormation` with a moving owner)
- six supported physical-skill episodes and 1,051 simulator steps
- zero collisions, zero timeouts, and 0.865683 m minimum clearance
- checkpoint-gated replacement activated correctly in the frozen correction case

This run exercises accepted `PlanIR` dispatch through `TaskExecutive` and
`SemanticTaskRuntimeAdapter`, followed by deterministic kinematic semantic
controllers.  It does not exercise Unitree contact dynamics, gait stability,
actuator limits, real sensing, moving-owner formation control, or unseen plans.

### Navigation interruption and resume

The same-day NAV-INT-1 static-city experiment completed 40/40 runs without runner
errors, but all three registered hypotheses are refuted:

- an instruction was admitted in 24/32 interrupted rows (0.750), while the bar was
  0.80; only 7/14 amend-cue instructions were admitted;
- amended-goal success agreed between system and independent scorer in 11/28 cases
  (0.3929), compared with a weighted 0.750 from-rest control;
- return succeeded in 8/9 jointly reachable cases (0.8889), below the 0.90 bar, and
  mean oracle path ratio was 1.4905 versus a 1.15 bar;
- the frozen blind steering set scored 91/110 (0.8273): revise 0.9000, keep 0.9333,
  queue 0.6667, clarify 0.8000; the adversarial slice was 27/40 (0.6750); and
- system/scorer arrival authority disagreed on 17/80 scored legs.

The post-hoc classifier scored 0.9727 but was written after the blind set was opened
and does not change the result. The queue policy is harness-side; inputs are text and
the planner is a local sketch, not an LLM. There is no product plan stack/resume proof.

## Conversation, authority, and acoustic behavior

### Typed brain boundary

`brain-v1` passed 15/15 frozen cases, including all 7 expected fail-closed cases.
It parsed 16 plan contracts, admitted 12, rejected 4, dispatched 12 semantic skills,
accepted 14 reports, ignored one stale report, and accepted nine verified facts.
There were zero physical navigation episodes.  This is good evidence for typed
admission/executive/result semantics, not for planner language quality.

### Scripted duplex

`duplex-v1` passed all seven hard gates with 216 emitted 10 Hz frames, zero missing
frames, barge-in atomicity, and a synthetic TTFT p50 of 35.53 ms.  The inputs are
text-injected and the slow path is injected; there is no microphone, speaker,
acoustic echo, ASR, current hosted model, or production network path.

The suite's navigation regression gate is stale by construction: it reports its
checked-in latest-shipped 7/9 follow ledger as "unchanged".  A passing duplex gate
must not be read as a current 9/9 navigation claim.

### Null-sink acoustic loop

After fixing the evaluator's negative-offset slicing failure, the 25-case full suite
completed three times with clean teardown.  The gate vector was identical on all
three runs: five pass, four fail.

| Gate | Run 1 | Run 2 | Run 3 | Limit |
|---|---:|---:|---:|---:|
| Endpoint p50 | 0.790 s | 0.792 s | 0.792 s | <= 0.500 s |
| Barge-in detection p50 | 0.0005 s | 0.1278 s | 0.0004 s | <= 0.400 s |
| Acoustic stop p50 | 1.080 s | 0.890 s | 1.080 s | <= 0.520 s |
| Duplex acoustic acknowledgment p50 | 0.840 s | 0.840 s | 0.850 s | <= 0.700 s |
| Prosody apex in window | 0.5714 | 0.5714 | 0.5714 | >= 0.8000 |

Endpoint cutoff, endpoint p90, detection p50, flush maximum, and false-barge-in
gates passed.  One case (`interrupt_02@6s`) was detected in runs 1 and 3 but not in
run 2, so case-level determinism also failed even though the aggregate gate vector
was stable.  These tests use synthesized speech and null sinks, with no room,
physical microphone/speaker, AEC, or hosted-response generation.

An additive source and measurement audit keeps that historical 5/9 score but
changes its interpretation: **none of the four red values validly measures its
named capability**. Endpoint is sampled after full synchronous WAV playback and
hides premature commits in all three 750 ms pause cases plus `incomplete_04`;
STOP power subtraction leaves owner speech in the inferred robot channel;
acknowledgment feeds 22.05 kHz raw fixture PCM to a 16 kHz default and includes
stretched leading silence; prosody mixes clocks/rates, permits reused matches,
and observes no motion. The production sink now directly aborts a live PortAudio
stream even while its worker is draining and moves its worker-write timestamp
after stream open; a guarded **86-test** selection passed with two expected
warnings. This is source hardening, not an acoustic pass. See the
[acoustic-loop v1 audit](../ACOUSTIC_LOOP_V1_AUDIT.md).

### Corrected acoustic v2 and endpoint sensitivity

The additive v2 runner supersedes interpretation of those historical metrics.
It records every commit on the sample clock, requires exactly one post-final
commit, uses rate-correct audio, separates write-attempt from virtual audibility,
and uses monotonic one-to-one prosody matching. Its 11 gates are 6 pass, 3 fail,
and 2 not measured. `incomplete_02`, `incomplete_04`, `pause_01`, and `pause_03`
are invalid; valid-only ep50/ep90 are 0.274/0.2916 s, while semantic invalidity
is 30.77%. Virtual-audible acknowledgement p50/p90 is 0.790/2.633 s. Isolated
robot-output acoustic STOP and physical motion/audio synchronization remain
unmeasured; 13/14 prosody covers audio transport only.

A follow-up declared exploratory grid ran twice over 30 confidence/silence
settings × 52 phase variants. Both 1,560-cell JSON results are byte-identical;
no setting passes. Direct replay also fails corrected-v2 parity. The closest
semantic row is only 49/52 valid and has valid-only ep90 2.577 s. These results
support no production threshold change and no provisional motion admission.
Two source-pinned repeats through the actual `MicrophoneVoiceLoop` match the
duplicate runner at all 52 default 30 ms sample-frame indices, ruling out a
state-machine transcription mismatch without establishing device/room parity.
See [corrected v2](../acoustic-eval-v2/RESULTS.md) and the
[endpoint-policy verdict](../endpoint-policy-1/VERDICT.md).

### Conversation quality

The historical Realtime corpus contains 25 threads and 174 turns captured from
`gpt-realtime-2.1-mini`.  Machine checks found zero hard failures and 66 report-only
review flags.  An unblinded, uncalibrated, non-human semantic review rated six
threads pass, eight mixed, and eleven fail; expectation-level judgments were 43 pass
and 33 fail.  Common failures included invented memory or perception, repetitive
refusals, verbosity, unsupported embodiment claims, and dialogue not following the
task state closely enough.  Because these are historical captures, they do not
measure the current deployed prompt/model.

The personal-conversation fixture passed 13/13 turns across eight families, but the
provider is explicitly `fixture-honest-companion-v1`.  It demonstrates harness and
contract behavior only and must not be reported as model quality.

### Model B narration stage results

The same-day MB-1 hosted-Q arm completed, while provider quota stopped hosted D
at 2/120 scenarios. Q-minus-D is therefore unmeasured, and the blind local audit
is not calibrated human gold. The available stages are still useful negative
evidence:

- the scripted Q fixture reached 1.000 grounding and 0.9688 coverage versus the
  scripted direct digest's 0.8854/0.7688; this establishes harness sensitivity only;
- local Qwen2.5-7B Q4 on CPU reached 0.9637 grounding but 0.5225 coverage, made six
  machine-flagged invented actions, acknowledged only 18/75 new goals, offered resume
  on 2/10, handled the keys constraint on 0/15, and had 633 ms TTFT / 1.612 s total
  p50; and
- hosted Q completed 120/120 scenarios and produced 164 robot turns. Recovered
  timing ambiguity yields a grounding range of **0.6120–0.7274** and coverage
  **0.2283–0.2883**. New-goal acknowledgment was 99/225, completion 11–27/165,
  resume 10–11/30, and the keys constraint 1/25. There were 45 machine action
  flags in 39 turns. Only five exact turns support latency: TTFT p50/p95
  1,271/1,990 ms and total p50/p95 3,337/3,967 ms. Every absolute Q gate failed.

The completed hosted wave added **$1.32843624**, moving the shared research
ledger from $0.87959880 to $2.20803504. Because calibrated human adjudication
and the matched hosted baseline do not exist, machine flags are not a calibrated
model failure rate and no Q-minus-D effect may be claimed. The negative absolute
gates do refute the candidate. The independently confirmed LIT-1 counterexample,
rather than those uncalibrated flags, refutes the stronger structural claim that
the old path excludes invention.

## Transaction authority experiment

The adjacent `duplex-transaction-2` experiment ran 8,448 direct product-seam cases
twice.  An independent stdlib verifier accepted all cases and obtained identical
normalized trace and chain roots.  It establishes conformance of the existing
executive seam and the existing dialogue receipt/claim seam independently.

The later DMC-4 experiment closes a narrower source-level part of that red row.
`TaskExecutive` now owns a bounded journal of immutable transition records, and
a journal-only bridge maps contiguous records to authenticated, non-actuating
narration events. Two fresh runs each retained 1,824 accepted mutations; all
256 corruption cases, replay, 32-producer concurrency, and bounded-overflow
gates passed with identical normalized trace and chain roots. The resulting
`DMC4_COMPOSED_PASS` applies only to this source-level transaction.

The normal `RobotRuntime` now keeps its bare executive as task owner and polls
its journal through a process-local authenticated observer into bounded,
non-actuating Model-B frames. Post-review hardening carries exact plan, step,
attempt, mission, action, evidence, source epoch, speech generation, issue time,
and deadline into the compact frame and atomically revalidates queued frames at
drain. The frames are not sent to Realtime or audio. Persistent cursor/restart
recovery, independently authenticated live speech-generation epoch/cancellation,
provider acknowledgement/backpressure, and authoritative separate-child resume
lineage remain absent. The complete
live Model A -> Model B -> Realtime narration path therefore remains red.

Freshness is also not yet enforced from authoritative commit to speech: the
transition omits a commit timestamp and the bridge starts TTL when it polls.
Drain-time expiry is now enforced, but a late poll can still manufacture a new
TTL window. Restart replays or loses history without persisted executive/outbox/
read/consume/provider-ack cursors.

An independent post-hoc audit of the five retained LIT-1 fake-voice traces supplies
a concrete consequence. Every run ended the bench revision with `task_failed` /
`semantic_target_unreachable`; both arrival authorities said false at about 3.33 m
from the bench. The harness nevertheless emitted “I've reached the bench” in all
five runs. `ok_runs=5/5` meant process completion, not mission success. The frozen
hash verifier therefore records **5/5 false terminal arrival claims** and a
`REFUTED_GROUNDING` verdict. This is scripted research-harness evidence, not a
production failure-rate estimate, but it is a valid blocking counterexample.

## Bottom line

The codebase has credible typed authority primitives and useful deterministic
integration harnesses. DMC-4 advances source-level task-to-narration truth, but
generalized navigation, social safety, hosted wording quality, acoustic timing,
and live runtime/session composition remain red or unmeasured. Model A also has
no qualified learned artifact, commissioned launcher/arm path, or honest physical
observation product. Motion-enabled
physical readiness is **NO-GO**.
