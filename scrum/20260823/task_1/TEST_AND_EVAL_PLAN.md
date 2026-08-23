# ARCH-1 unit, integration, and quality-evaluation plan

Status: preregistered proposal for Fable review. No test, marker, threshold, or
gate is changed by this document.

## Test strategy

Every extraction has two independent lanes:

1. **Equivalence lane:** proves accepted product behavior and interfaces did
   not change during a structural refactor.
2. **Refutation lane:** independently proves unsafe, stale, malformed,
   unauthorized, duplicate, or physically impossible behavior is still caught.

A golden trace is never the sole oracle because it can freeze an existing
defect. Known defects are labeled in the baseline and must either remain an
honest known red or move only under a separately approved behavior-change card.

## Proposed scope and cadence markers

The current suite is divided mostly by `slow`, with `load_sensitive` and
`no_future_clock` exceptions. ARCH-TEST should add two orthogonal axes without
narrowing the current commit tier until every test is classified:

**Scope:** `scope_unit`, `scope_contract`, `scope_integration`, `scope_replay`,
`scope_sil`, `scope_hil`, `scope_physical`, `scope_quality`.

**Cadence:** `cadence_commit`, `cadence_nightly`, `cadence_target`,
`cadence_manual`.

Rules:

- exactly one scope and at least one cadence per test after migration;
- integration tests that are fast and hermetic remain commit tests;
- target/HIL/physical tests never enter offline CI or receive product
  credentials accidentally;
- a tier-coverage gate rejects unclassified, orphaned, or silently overlapping
  tests;
- stable node IDs are preserved or an explicit old→new node-ID map is checked
  in for named hard gates;
- all pytest execution uses a repo-owned bounded launcher; the mandatory guard
  must not live only under an operator's `~/.cache`.

## Verification pyramid

### 1. Static and architecture checks — every implementation commit

- forbidden dependency/import edges and no-new-cycle graph;
- contract/config schema compatibility and public import/API census;
- strict type check for new contracts and critical boundary packages;
- changed-code line/branch coverage ratchet;
- secret, license, dependency, wheel, and packaged-asset checks;
- exactly one physical actuation client and no vendor import in the application
  contract layer;
- safety loop cannot import model/audio/UI/storage/HTTP modules;
- no new file/class/function/constructor debt beyond the accepted ratchet.

### 2. Unit, property, and mutation tests — largest layer, every commit

- pure reducers, state transitions, clocks, freshness, frames, provenance,
  sequence/epoch handling, DTO validation, geometry, shaping, and stops;
- generated cases immediately below/on/above every threshold, including
  NaN/Inf, negative/future ages, wrap/reset, duplicate/reordered messages;
- new safety-decision code: every true/false safety branch exercised and every
  registered safety mutant killed;
- proposed initial changed-code ratchet: at least 90% changed-line and 85%
  changed-branch coverage; stricter 100% decision coverage for final authority,
  protocol admission, and physical evidence validation;
- coverage is evidence, not an oracle: semantic assertions and mutants remain
  mandatory.

### 3. Component and process contracts — targeted commit, full nightly

- real AF_UNIX/SOCK_SEQPACKET or WebSocket boundary, not an in-process mock;
- fake vendor/device behind the real client/server process topology;
- malformed/fuzzed frames, bounded queues, partial reads/writes, backpressure,
  restart, shutdown, timeout, credential, and compatibility behavior;
- model/GPU/audio/capture subprocess lifecycle and resource ownership;
- endpoint HTTP status/body/auth behavior through the real handler.

### 4. Recorded replay and old/new differential — nightly

- immutable MCAP/pcap/DDS/audio/session fixtures with manifests and hashes;
- canonicalize only nondeterministic IDs/times; compare exact command/wire
  bytes, dispositions, authority changes, terminal events, ledger rows, and
  stable JSON fields;
- planner/estimator floats use preregistered physical tolerances plus an
  independent safety oracle;
- inject delay, loss, duplicates, reorder, clock reset, frame mismatch,
  calibration revision, process death, and disk/logger backpressure.

### 5. SIL/physics — nightly and release candidate

- production contracts/process topology around MuJoCo;
- scenario and metamorphic campaigns for normal, stale, loss, collision,
  unknown space, recovery, cancellation, and false arrival;
- no simulation result is described as stopping-distance, localization, sensor,
  or physical-world proof.

### 6. Target/HIL — candidate builds

- clean aarch64/Orin install from locks and a built wheel;
- declared process/venv topology, native gateway against fake Sport, real
  sensors read-only, then commissioned one-axis HIL;
- timings that gate Orin deployment are measured on the Orin under declared
  load. Desktop timing is report-only.

### 7. Supervised physical and human quality — milestone gates

- physical progression follows the signed box-day and B16/B30/B17/B31/B26–B28
  order below;
- conversational quality is evaluated stationary before being combined with
  motion;
- safety/parser/provider hard failures are non-compensable and cannot be
  averaged into an attractive quality score.

## Invariants every extraction must preserve

1. Learned/provider output is an untrusted proposal: it cannot mint authority,
   emit gateway bytes, or claim physical completion.
2. Exactly one physical writer/client exists; commissioning and product
   credentials cannot coexist.
3. Latched STOP finalizes every axis to bit-exact zero after every shaper and
   bypasses comfort smoothing. Recoverable translation HOLD permits no
   translation but may retain explicitly bounded sensing yaw only where the
   preregistered input-class × axis table allows it. The native final governor
   never originates/increases motion or changes direction outside its formal
   admissible-set rule.
4. Source loss causes sample/snapshot expiry, no positive refresh, and gateway
   TTL/watchdog stop. The software/gateway E-stop latch has explicit clear,
   restart is disarmed, and no auto-resume exists. The operator-owned physical
   stop is separately tested as an out-of-band failure domain independent of
   Python, native processes, the robot LAN, credentials, and shared power to
   the extent the chosen hardware permits.
5. Admission acknowledgement is not stationary confirmation. Fresh, ordered
   physical feedback is required; an in-flight move crossing a stop epoch gets
   a compensating stop.
6. Old epoch/revision, duplicate/out-of-order sequence, wrong writer/hash,
   expired TTL, and incompatible envelope/calibration are rejected.
7. Host monotonic receipt owns freshness. Device time is retained/mapped and
   never silently re-stamped.
8. Unknown/simulator origin in a physical profile and future/stale/wrong-frame/
   NaN/missing evidence fail closed.
9. A snapshot is atomic across evidence, transform, calibration, task, config,
   and capability revisions; cached evidence is not counted repeatedly as
   independent support.
10. Unknown space is not free. Translation/recovery targets cite fresh observed
    reachable space; no blind reverse or point-goal bypass exists.
11. Arrival requires compatible independent evidence and settled feedback.
    Semantic/route memory may propose but cannot authorize geometry or truth.
12. One task/utterance authority exists. ASK, partial transcripts, untrusted
    speakers, and read-only tools grant no motion. Cancellation invalidates old
    work.
13. Logger/UI/model/storage/network failure or backpressure cannot change
    control bytes or delay the stop chain; queues are bounded and drops visible.
14. The signed stopping envelope includes candidate age, scan age, IPC,
    watchdog/scheduling, vendor stop-to-standstill, and localization uncertainty.

## Per-boundary breakdown

| Boundary/card | Unit/property plan | Integration/replay plan | Quality/eval plan and acceptance |
|---|---|---|---|
| `ARCH-IG` imports/contracts | forbidden edges, import order, optional dependency absence, public-import compatibility | clean interpreter imports each capability set; wheel import with vendor/model/sim modules hidden | leaf import does not pull runtime; no new SCC/cycle; startup-fatal required capability remains explicit |
| `ARCH-TEST` harness | plugin hook/order and isolation; seed leaked process/write/resource overrun | run representative suite through repo launcher; nested/failing pytest remains contained and failure-complete | stable node IDs/map; no orphan processes/writes; bounded workers/memory; gate JSON still emitted on failures |
| `ARCH-OBS` evidence/snapshots | DTO strictness, clocks, sequence/drop, origin lattice, frame/TF/calibration revision, covariance, linked high-rate `NavigationSnapshotV2` and slower `WorldSnapshotV2` | simulator/replay/Go2/D455/Mid-360 recorded traces; slow-modality loss; delay/drop/reorder/reset/TF-jump differential | every invalid class gets the axis-table disposition; slow world input never blocks final admission; healthy old/new parity; target age/drop distributions reported; no localization claim |
| native final governor/gateway + `ARCH-CONTROL` decision | protocol, TTL/epoch/credential, single clamp owner, admissible set, stop dominance, stationary witness, interleavings; characterize Python manager before keep/retire/decompose | native process + fake Sport; client/gateway kill/SIGSTOP, dual writer, restart, socket flood/backpressure, logger failure | zero positive-after-expiry/wrong-writer/old-epoch; gateway never originates/increases; stop within derived bound; 1,000 automated repetitions per cheap fault class before p99 claim |
| `ARCH-LOOP` | Python supervisory reducers, proposal arbitration, shaping/pre-gate refusal, health join, bounded observer handoff | shadow uncredentialed candidates on frozen ticks; full process/SIL under model/audio/storage/UI failure | exact candidate/disposition parity and independent safety oracle; supervisory deadline measured; zero blocking I/O imports/calls and no final/vendor credential |
| `ARCH-NAV-*` | lock-on, semantic resolution, observed-space geometry, costmap, recovery, route memory, arrival witnesses; property transforms | frozen nav episodes and real bags with drift/gaps/changed objects; old/new differential; SIL metamorphic obstacles/people/unknown space | zero hard collision, false arrival, keepout/unknown-space admission, stale action; path/success metrics non-inferior within preregistered tolerance |
| `ARCH-MISSION` | admit/cancel/preempt/retry/deadline/resource/revision reducers; ASK/no-motion; late-result rejection | identical frozen transcripts/snapshots through old/new executives; provider/planner/storage death | exact task/disposition/terminal-event parity; zero old-revision effects; safety remains live when executive is dead |
| `ARCH-REALTIME`/tools | session, response, barge-in, reconnect, tool grammar/authority, consent, spend, memory transitions | fake/recorded provider events including 429/5xx, disconnect, duplicate/reorder; product HTTP/WS/tool path | zero duplicate/stale/unauthorized tool admissions or fabricated success; one terminal event; spend/accounting parity |
| `ARCH-AUDIO`/voice | PCM/frame contracts, resampling, playback ACK, device state, duplex reducer, cancellation, AEC/VAD | browser WS, fake PortAudio, real XVF3800 through-air while hosted provider is stubbed; teardown/device loss | retain acoustic latency/barge-in/false-cancel thresholds; zero self-talk motion; target/device evidence names what it does not prove |
| `ARCH-CAMERA`/perception/map | frame DTO, depth/transform localization, query state, admission, map ingest/resolve/store failures | daemon subprocess, camera replay, stale/empty/model-down, persistence restart/corruption | no false positive promoted without evidence; stale frame cannot refresh map; daemon/storage failure never blocks control |
| `ARCH-CONFIG`/package | typed sections, defaults, overlays, unknown keys, migrations, cross-section capability rules | source vs packaged assets; absent-profile and every physical/sim composition; clean wheel installs | byte/effective-config parity unless separately approved; physical profile rejects unsupported/sim combinations; no MuJoCo import on dog path |
| `ARCH-CI`/capture | evaluator/result DTOs, report renderers, decoder/clock math, failure containment | old/new gate JSON/stage order/exit code; immutable capture/replay reports byte-compatible | no false-green, every evaluator exception named ERROR while later rows emit; evidence carries hashes/origin/denominator/`does_not_prove` |
| `ARCH-WEB`/UI | typed endpoint DTOs, auth/origin, route selection, state reducer | real HTTP handler/WS; browser automation for critical controls; server restart | endpoint status/body parity; UI cannot create authority; safety control remains usable and truthful under stale/disconnected UI |
| `ARCH-SIM`/providers | simulation reducers and provider parsers/transport errors | old/new frozen scenes; provider-swap and credential-free recorded streams | sim scores remain comparable; provider quality may regress the score but can never bypass hard parser/authority gates |

## Exact commit hard gates proposed

1. `architecture-boundary`: zero forbidden imports/cycles; contract layer has
   no runtime/vendor imports; exactly one actuation client.
2. `contract-schema`: supported fixtures round-trip byte-identically; unknown
   fields/types/ranges reject; version behavior explicit.
3. `authority-invariants`: property suite for the invariants above; exact-zero,
   clamp monotonicity, and all registered seed mutants.
4. `snapshot-unit`: every timestamp/origin/frame/epoch/independence invalid
   class produces the expected typed HOLD/STOP.
5. `baseline-differential-smoke`: small accepted traces match old/new output;
   intentional changes require another approved card and stronger oracle.
6. `typing-new-boundaries` and changed-code coverage ratchet.
7. clean wheel/release parity, Ruff no-new-debt, and gate self-test.

No commit hard gate may skip. Evaluator exceptions are named errors and do not
prevent valid JSON or later stage rows from being emitted.

## Exact nightly hard gates proposed

1. `contract-fuzz`: at least 100,000 malformed/valid messages per protocol
   corpus, no crash/hang, zero unauthorized positive command.
2. `authority-mutation`: stale-as-fresh, unknown-as-clear, residual stop,
   wrong epoch/revision/writer, second writer, logger backpressure,
   restart-armed, fake terminal witness, and test-credential mutants killed.
3. `fault-containment`: kill/SIGSTOP/restart/drop/reorder/duplicate/clock-reset/
   disk-full/logger-block/GPU/UI/provider/ROS-loss through real subprocesses.
4. `recorded-replay` and `old-new-differential-full` with frozen manifests plus
   independent safety oracle.
5. `sil-safety`: zero hard collision, false arrival, unknown-space/keepout
   admission, or stale action in the preregistered matrix.
6. `performance-envelope`: target-independent budget derivation; host timing
   report-only until target run.
7. `quality-machine`: deterministic tool/parser/memory/truth suites with zero
   duplicate/stale/unauthorized admission and fabricated completion.
8. `evidence-integrity`: release/config/model/calibration/capability hashes,
   origin, exact denominator, and `does_not_prove`; seeded evaluator failure
   must make the gate nonzero.

## Target, HIL, and physical sequence

Any hard red stops progression.

0. Earlier host/CI no-credential native bench against fake Sport; this proves
   protocol/process behavior only and does not satisfy the later Orin rung.
1. Clean software/fuzz/SIL, signed capability manifest, independent stop plan.
2. Box-day firmware/network/read-only inspection; robot on stand, remote
   present, no product writer credential.
3. B25 sensor-only capture/calibration and timestamp/TF/extrinsic evidence.
4. Native gateway on Orin against fake Sport.
5. Before B16 credentials, two people verify the operator stop functionally in
   a dry/no-writer setup and establish stand, leash/tether, exclusion zone, and
   abort roles. Then commissioning-only credential and packet inspection; one
   reviewed pulse on one axis at the lowest signed speed; then 3–5 individually
   inspected stops/abort reviews before any automated repeat. Cover arm/disarm,
   stop, kill/SIGSTOP, lease loss, restart, writer conflict, physical operator
   stop, and independent stationary witness.
6. B30 product credential only; repeat source/snapshot/TTL stop chain and kill
   Python/model/UI/logger/storage. Zero simultaneous writers or auto-resume.
7. B17 localization real-bag exit, then B31 surveyed static observed-space
   course with obstacle, unknown boundary, malformed/stale/wrong-frame scan,
   localizer loss/jump, transform mismatch, and unavailable planner.
8. B26 translation-off perception/identity, B27 low-speed local navigation,
   then B28 terminal/geofence/negative-terrain evidence.
9. Stationary through-air conversation; only then bounded interaction during
   motion.
10. B24 first-ODD campaign. No stairs, hills, crowds, public space, or nominal
    speed is promoted by implication.

Only after the inspected B16 ladder is understood may an owner-approved
capability milestone run at least 30 repetitions per scenario/regime and report
median, p95, and maximum. Thirty-repeat physical/human campaigns are not run per
structural Tier-M/B card; those reuse frozen traces and one relevant tranche
integration result. Every stop must fit the signed envelope; an outlier is not
hidden behind p95. Do not claim p99 from 30 trials. Require at least 1,000
automated bench/HIL events in the same topology before a p99 claim, and report
the rule-of-three upper bound when failures are zero.

## Quality-evaluation breakdown

### Architecture quality

- facade lines/methods/mutable attributes/internal imports decrease;
- no new dependency cycle, lock, thread, callback edge, or unbounded queue;
- new boundaries strict-type clean;
- no increase in C901/size debt; ratchet lowers after accepted extraction;
- source-shape tests replaced by observable contract/product-path tests where
  possible; mutation score does not decline.

### Navigation and embodied behavior

Retain current frozen InstructNav, BARN, follow, doorway, arrival, route-memory,
held-out scene, and mutation panels. Report success, collision, false-arrival,
abstention, unknown-space admission, path/travel cost, jerk, intervention,
terminal evidence, and latency separately. Safety metrics are zero-tolerance;
do not combine them into a mean quality score.

### Conversation and companion quality

Reuse `conversation_quality_v1`, `personal_convo_v1`, `duplex_v1`,
`acoustic_loop_v1`, assertion fixtures, realtime corpus replay, and provider
swap harnesses. Preserve existing preregistered thresholds rather than
re-tuning after the refactor. At minimum report:

- end-of-speech to meaningful audio latency distribution;
- deliberate barge-in detection and playback suppression latency;
- false cancel, side-speech response, ambient/motor false wake;
- navigation-intent and critical-slot accuracy;
- duplicate/stale/unauthorized admission, fabricated tool completion,
  consent/memory/forgetting correctness, and spend per accepted turn.

At a conversation/provider/audio milestone—not per structural refactor—run at
least 30 paired repeats per scenario/config. Automated judge results are
report-only until calibrated against held-out humans. Human release criteria,
sample size, consent, blinding, and dimension-specific non-inferiority or
preference rules must be preregistered before ratings are viewed; safety/parser
failures remain non-compensable.

### Operational quality

- startup, shutdown, rollback, restart-disarmed, readiness and upgrade path;
- bounded CPU/GPU/RAM/threads/FDs/queues/disk/log growth under an 8–24 hour
  target soak;
- trace correlation snapshot→decision→gateway→feedback;
- logger/disk/network/model/UI loss leaves control bytes unchanged and drops
  observable;
- installed wheel, locks, manifests, capabilities, config/model/calibration
  hashes reproduce the verdict from a clean target.

## Required `does_not_prove` labels

- unit/property: proves local logic for generated inputs, not process wiring;
- mock component: proves adapter contract, not vendor/device behavior;
- recorded replay: proves behavior for frozen traces, not current sensor timing;
- SIL: proves logic in the simulator, not physical stopping/localization;
- x86 timing: informs engineering, not Orin deadline admission;
- read-only target: proves sensors/install, not motion authority;
- stand HIL: proves a bounded commissioned axis, not autonomous navigation;
- small human pilot: estimates variance/usability, not population preference or
  long-term companionship.
