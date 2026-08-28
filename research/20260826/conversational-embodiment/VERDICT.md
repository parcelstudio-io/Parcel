# Conversational embodiment · verdict · 2026-08-26

## Verdict

**Implement the architecture; do not promote physical readiness.**

The repository has good safety seams—closed realtime tool schemas, local broker
validation, response-initiator authority, action start/terminal separation, a
versioned prompt plane, and provenance-bearing memory components. Concurrent
work also added SI v4, which now describes Parcel as a continuing companion
friend without equating companionship with surveillance, dependence, or
unrequested travel.

The companion is still not conversationally or physically release-ready. The
effective Go2 capability surface disagrees with 8/9 personality affect-action
mappings, the realtime DI has no typed action/dialogue/body envelope, prior live
conversation quality is red, four acoustic gates are red, and no mounted audio,
Orin, owner-identity, stopping, or physical motion evidence exists. Prompt
wording cannot close those mechanisms.

All four research hypotheses passed, but only on authored pre-parsed frames.
That is sufficient to recommend the interfaces below. It is not sufficient to
enable proactive speech, automatic following/approach/search, or physical
motion.

The user-linked Claude artifact was not accessible as reviewable content, so no
artifact-specific mount claim is possible. The committed Claude/QEV record
supports preserving the motion-gateway seam while retaining the existing
motion no-go.

## What to implement next, in order

### 1. Make the capability manifest the single source of truth

Create a versioned `CapabilityManifestV1` from the *effective* profile and
runtime adapters, not from personality prose:

```text
manifest_digest
tools[{name, schema_digest, commissioned}]
gestures[{name, semantic_tags, trajectory_digest, commissioned}]
poses[{name, semantic_tags, trajectory_digest, commissioned}]
navigation_modes[{name, commissioned, required_evidence}]
```

At boot, fail closed or explicitly drop any personality affect mapping absent
from the commissioned gesture set. Generate local prompt context, realtime tool
enums, UI capability displays, eval manifests, and conversation-reaction
allowlists from this same object. Never silently substitute `play_bow` for
`comfort_bow` or another similar-looking motion.

Immediate acceptance bar: **100% personality-to-effective-manifest closure**,
zero unavailable names in every prompt/eval fixture, and one manifest digest in
every conversational action record.

### 2. Put a typed envelope and state graph around the realtime model

Add two read models; neither receives actuator authority.

`EmbodimentEnvelopeV1` should carry:

- manifest digest and monotonic snapshot time;
- response initiator and verified-owner evidence/confidence;
- body mode, E-stop, locomotion commissioning/health, affordance/space state;
- exact pending action ID/status, last matching terminal receipt ID, and busy
  reason; and
- consent for proactive speech, stationary expression, following, and other
  separately scoped behavior.

`DialogueStateV1` should carry:

- current topic/referent and unresolved clarification;
- last *completed* repeatable action, pending action, correction/cancel state;
- owner-fact records with source turn/session/time, validity interval, consent,
  revocation, and supersession; and
- retrieval result IDs plus `no_match`, never a model-written assertion that a
  lookup succeeded.

Keep stable persona/tool/capability content at session open so prompt caching is
preserved. Send compact state changes as typed conversation/tool events. Every
model proposal still passes the broker and supervisor, and only a terminal
receipt may license completion language.

### 3. Replace raw proactive dictionaries; keep proactive speech off

Implement `OpportunityCandidateV1` validation before scoring. Unknown version,
key, missing field, wrong type, NaN/Inf, stale evidence, mixed epoch, or
unverified identity must return `DROP_INVALID` with an auditable reason.

The local gate owns identity, consent, privacy, owner-speaking, output-lane
state, quiet hours, E-stop, staleness, cooldown, subject dedup, and budget. The
hosted model may phrase an admitted fact/question or abstain; it may not reverse
a refusal or create motion.

Default proactive speech remains **off** until a consented mounted/shadow study
achieves:

- zero admissions for non-owner, private-zone, owner-speaking, self-TTS, and
  malformed/stale cases;
- separately reported owner identity false-accept/dropout rates;
- at least 0.80 precision and recall against blinded `speak / gesture / drop`
  labels, with owner veto dominant; and
- acceptable per-hour interruption/repetition ratings over multi-hour sessions.

Stationary silent reactions may be tested earlier only if they use a physically
commissioned gesture and the same gate.

### 4. Use a three-lane cognition router

Keep the routing contract simple initially:

1. **Local deterministic:** emergency stop/hold, action admission, malformed
   input, backchannel, terminal/rejection acknowledgement, opportunity drop,
   budget enforcement, and other closed acts.
2. **Realtime voice:** greetings, support, ordinary multi-turn conversation,
   clarification, playful dialogue, and short tool-grounded turns where natural
   interruption and first audio matter.
3. **Deliberative tier:** novel multi-constraint plans, long-memory comparison,
   research, and slow diagnosis. Invoke it as a bounded tool after a local or
   realtime acknowledgement; it never writes motion directly.

AGX Orin 64 GB should host deterministic gates, retrieval, ASR/TTS candidates,
perception, and a small bounded semantic-frame/fallback model before it is asked
to replace open-ended realtime voice. NVIDIA publishes ample platform capacity,
but its older 6B GPT-J benchmark also demonstrates that parameter fit does not
imply conversational latency. Run an exact-device bakeoff under concurrent
camera/LiDAR/audio load and each intended power mode.

Minimum edge-model bakeoff metrics:

- semantic-frame exactness and abstention on the raw version of this fixture;
- unavailable-action, hypothetical/negation, identity, and completion false
  positives—all must be zero after the local gate;
- p50/p95 time to first *usable* semantic frame and first audio;
- tokens/s, peak RAM/VRAM, sustained power, thermals, and throttling;
- barge-in cancellation and stale-output suppression; and
- quality/cost fallback behavior under Starlink loss, jitter, and quota.

Do not choose a model by a desktop benchmark or quantized file size alone.

### 5. Repeat the actual model and acoustic evals

Convert the authored semantic cases into raw multi-turn transcripts with
paraphrase, disfluency, correction, interruption, negation, quotation,
code-switching, TV/non-owner speech, stale receipt, and memory-update variants.
Evaluate the exact candidate local model and exact hosted realtime snapshot.
Store tool calls, receipts, audio timestamps, route choice, token usage, and
human labels.

Release bars should include:

- 100% parse/contract validity **and** zero unavailable/unauthorized actions;
- zero premature completion and unsupported perception/memory assertions;
- >=95% exact intent/action decision on a frozen high-risk set, reported per
  family rather than only overall;
- strong personal-conversation and long-memory update/abstention results on
  independently authored sessions; and
- all frozen virtual-acoustic gates green, followed by mounted through-air AEC,
  endpointing, barge-in, self-TTS rejection, and speaker/microphone tests.

## Simulator feasibility

Simulation is a strong capability-development engine if each claim is assigned
to the right simulator and stopped at its evidence boundary.

| simulator/eval layer | feasibility now | what it can improve | what it cannot prove |
|---|---|---|---|
| dialogue/world-event replay | **high** | multi-turn state, receipts, correction, memory update/abstention, initiative, routing, fault injection | natural owner preference, real ASR/VAD, physical motion |
| audio timeline + virtual acoustics | **high** | overlap, endpointing logic, barge-in cancellation, self-TTS loops, route timing | real room impulse response, array placement, mounted AEC |
| MuJoCo/vendor sim behavior replay | **high for orchestration** | action preemption, navigation/gesture scheduling, busy/defer logic, collision refuters | actuator dynamics and physical stopping without system identification |
| Isaac-style expressive-motion training | **medium-high** | diverse stationary gestures, balance recovery, curriculum and domain randomization | safe Go2 transfer from simulation success alone |
| sim-to-sim + hardware-in-loop | **medium** | command units/signs/rates, timing, adapter and receipt semantics | human safety, payload/thermal/mount integrity, final balance/stopping |
| human social acceptance in simulation | **low-medium** | early preference comparisons and counterfactual video/audio review | household acceptance over time |

For expressive motion, train and evaluate a gesture as a named skill with
entry/exit conditions and terminal detectors—not as a raw animation attached to
an emotion word. Randomize payload/mount mass and inertia, center of mass,
friction, actuator strength, latency, joint compliance/damping, sensor noise,
terrain, and perturbations. Require stability margin, foot slip/contact force,
tracking error, energy, recovery, preemption-to-safe-pose, and collision metrics.
Then perform sim-to-sim replay in a second engine before a separately authorized,
tethered/spottered physical commissioning ladder. The Unitree gesture study in
`SOURCES.json` is a useful warning: >95% simulated success did not erase
joint-compliance, load-distribution, and balance transfer issues.

For conversational motion synchrony, build a deterministic timeline simulator:

```text
owner speech -> VAD/transcript -> semantic frame -> route/tool proposal
             -> local admission -> started receipt -> gesture/nav timeline
             -> interruption/correction -> terminal/abort receipt -> speech
```

Randomize endpoint delay, provider latency, packet loss, tool rejection,
action duration, person-track dropout, identity confidence, body busy state,
and terminal-event reordering. Score duplicated acknowledgements, speech before
admission, motion during owner speech, stale terminals, cancellation latency,
semantic gesture fit, and total turn-to-motion synchrony. This can improve
fluidity before a robot exists while remaining honest about acoustics and
physics.

## Long-term learning and database design

Use an off-robot, append-only research store; keep only an encrypted bounded
cache on the dog. A practical initial deployment is PostgreSQL for structured
events plus S3-compatible object storage for audio/video/maps/model artifacts.
Every derived example must point back to immutable source events.

Minimum records:

- `sessions` and `turns` with owner/device consent, monotonic and wall clocks;
- encrypted media blobs and ASR alternatives;
- semantic frames, capability/envelope digest, route decision, model/snapshot,
  prompt/schema digest, tokens, latency, and cost;
- action proposals, local admission/refusal, runtime receipts, terminal/abort,
  and synchronized body/perception summaries;
- owner facts with source span, consent, valid interval, supersession, and
  revocation/tombstone;
- simulator seed/config/domain parameters, policy/trajectory digest, scenario,
  metrics, and source dataset snapshot;
- human labels, owner veto/correction, privacy deletion lineage, and evaluator
  identity/blinding; and
- immutable eval releases with train/dev/test split and contamination lineage.

The learning loop should be:

```text
log -> privacy/quality validation -> failure clustering -> hypothesis
    -> frozen counterfactual replay -> simulator training/eval
    -> independent held-out eval -> shadow deployment -> supervised physical gate
```

Never let online self-learning alter E-stop, owner identity, motion authority,
collision policy, or physical limits. Learned models can propose semantic
frames, dialogue, retrieval ranks, routes among model tiers, and candidate
skills; versioned deterministic gates stay outside learning. Promote only by an
eval manifest and rollbackable version, not by an in-place model update on the
dog.

## Budget recommendation

Treat the stated monthly budgets as independent envelopes:

- reserve the $300 realtime budget for owner-initiated open conversation and
  short tool-grounded narration;
- reserve the $100 text budget for deliberation, offline failure analysis, and
  dataset labeling/augmentation;
- stop proactive hosted phrasing first when spend rises;
- run closed acts, safety, retrieval filters, admission, and budget enforcement
  locally at all times; and
- account from provider usage events, not the synthetic $59/$80 projection in
  this study.

Build a rolling 7-day forecast and hard daily/session caps with a small reserved
owner-conversation pool. Log cache hits and instruction/tool changes because
later realtime turns resend more context and unstable prefixes raise cost.

## Readiness statement

**Conversational architecture readiness:** conditional prototype design, worth
implementing.
**Simulation-learning feasibility:** high for dialogue/action orchestration and
fault generalization; medium-high for expressive skills with domain
randomization and sim-to-sim; physical transfer still unproven.
**Stationary mounted conversation readiness:** unmeasured; existing QEV permits
only a separately authorized, supervised Stage-0 data-capture interpretation.
**Autonomous conversational motion on the physical Go2:** **NO-GO**.

The shortest responsible path is capability closure -> typed state/envelope ->
strict proactive contract -> real-model raw-transcript eval -> through-air
acoustics -> simulator/HIL refuters -> separately authorized physical
commissioning. Passing this authored replay removes architectural ambiguity; it
does not remove any physical gate.
