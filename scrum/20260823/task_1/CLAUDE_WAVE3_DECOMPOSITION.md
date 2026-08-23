# Claude Wave 3 exact-delta decomposition audit

**Review status:** ARCH-1 addendum · review-only · not dispatched

**Compared:** `0ce1c5f8bb4a..c1b84055bd57`

**Post-landing head at freeze:** `be86b7861322` (`CODEBASE_INDEX.md` refresh
only), equal to `origin/main` at 2026-08-23 16:32 EDT

**Review chronology:** an externally authored `FABLE_VERDICT.md` appeared after
this addendum was drafted, then its reviewer appended a narrow post-landing
register update. It reproduces the resolved-profile inheritance and hard-skip
findings and assigns several corrections, but the supplement is incomplete:
L11 is omitted from concern coverage and questions 21–26 lack all required
explicit answers/schema/truth-table/dispositions. Post-verdict QA then added
the injected-origin, static-vs-live capability, odometry/MAP, reactive person/
terrain, installer, and physical-ladder refinements in the current worktree;
those bytes were not in the accepted committed version. Preserve the verdict
verbatim and request only the missing narrow correction, not another nine-agent
review.

## Decision in one page

Claude's Wave 3 implementation is directionally useful and should not be
discarded. It creates conservative observe-only Go2 behavior, strict overlay
validation with an unsafe resolved-config inheritance gap, a pure LiDAR band,
a working array-audio seam, explicit target artifacts, and unusually broad
adversarial tests. It also landed several first-version components at monolith
size and left six original cross-cutting integration hazards, plus additional
physical-promotion gaps enumerated in the findings table below:

1. the six-term stopping-envelope model exists as V2, but the gate deliberately
   still evaluates V1, so stale scan age cannot make the printed verdict red;
2. the live Go2 source imports the vendor SDK inside the product process even
   though the documented process/venv plan says that SDK is isolated;
3. the observation path can drain and decode UDP under the same lock used by
   other `observe()` callers, and an injected blocking socket defeats the
   stated clock bound;
4. the Go2 overlay's comments prohibit simulated battery/NIC truth, but the
   effective deep-merged profile still inherits those values from `robot.yaml`;
5. absent hard-gate capabilities can become skipped rows while the gate still
   exits zero and says `PASS`;
6. `ArrayAudioGateway` is a 965-line lifecycle owner, while the HTTP mic route
   adds a process-global lock whose relationship to the gateway lock is not
   yet characterized by a failing interleaving.

The right response is **retain, characterize, then decompose behind the landed
facades**. Do not split every long object. In particular, preserve the sticky
commissioning latch, replay cursor, resampler, pure LiDAR math, refusal methods,
and duplex open/close atomicity until equivalence and interleaving tests exist.

This addendum proposes no automatic follow-up cards. Its work folds into the
already proposed `ARCH-OBS`, `ARCH-AUDIO`, `ARCH-CONFIG`, `ARCH-CI`,
`ARCH-TEST`, `ARCH-PKG`, and `ARCH-DEPLOY` boundaries. Fable must decide the
smallest accepted tranche; the owner alone may dispatch it.

## Exact scope and attribution

The implementation commit contains 150 changed paths and 32,082 added lines.
Of those, 91 are scrum records: 83 prior-day task/design/evidence paths and
eight paths in this ARCH-1 packet. The code-bearing audit therefore uses the
exact 59-path non-scrum delta, not the commit's total size.

| Area | Paths | Delta | Audit treatment |
|---|---:|---:|---|
| Product under `src/parcel_robot` | 24 | +5,355 / -20 | full symbol and boundary review |
| Tests and replay data | 11 | +8,974 / -0 | suite decomposition and oracle review |
| Scripts/capture tooling | 6 | +1,394 / -13 | function and process review |
| Config records | 4 | +712 / -0 | schema/authority review |
| Orin deployment | 7 | +696 / -0 | policy/topology/target-evidence review |
| CI workflow | 1 | +137 / -0 | capability, cost, and false-green review |
| Packaging/locks | 3 | +179 / -0 | interpreter/artifact review |
| Box-day documentation | 1 | +195 / -0 | no code decomposition |
| Process/index files | 2 | +227 / -148 | index/process review only |

Across product Python, the commit adds 170 class/function/method definition
nodes and modifies 11. Operational Python adds 21 and modifies six more nodes.
Nine new hardware test modules contribute 8,863 lines, 244 tests, 72 top-level
helpers, 20 fake/parser classes, and 69 class methods. These counts are
mechanical AST/file measurements; they are not correctness or coverage claims.

## Disposition vocabulary

| Disposition | Meaning |
|---|---|
| `EXTRACT_FACADE` | keep the public object/import while moving bounded owners behind it |
| `EXTRACT_PURE` | move deterministic parsing, policy, math, or rendering with differential tests |
| `MOVE_COMPOSITION` | move construction/schema decisions out of runtime or web handlers |
| `CONSOLIDATE_VERSIONED` | retain compatibility readers while making one current domain model |
| `PRESERVE_STATE_MACHINE` | characterize and keep one lock/lifecycle/latch owner cohesive |
| `MOVE_TEST_SUPPORT` | remove fixture builders/parsers from product or giant card tests |
| `RATCHET_ONLY` | retain a small compatibility change; prevent renewed duplication |
| `TARGET_PROVE` | structure is acceptable; promotion depends on target/physical evidence, not file splitting |

## Immediate findings Fable must disposition

| Finding | Evidence in `c1b8405` | Required response | Existing concern owner |
|---|---|---|---|
| Scan age is disconnected from the gate | `bridge/timing.py` adds V2 and `scan_age`; `scripts/ci_gate.py:evaluate_stopping_envelope` still loads/derives V1; `test_hw2_go2_backend.py::test_e7_*` pins that omission | first add a red refuter, then wire the current six-term model; only afterward consolidate V1/V2 | R09, T12 |
| A hard gate can exit zero with required capabilities absent | HW-7 converts absent ruff/pytest/xdist/MuJoCo rows to `skip`; summary can print `PASS` with hard skipped rows | distinguish unsupported/report-only from required-hard; a required hard row may not be green or exit zero | T12, P15 |
| Product composition contradicts venv topology | `web_panel._build_backend` constructs `LiveGo2Sources`, whose state source probes `unitree_sdk2py`; product Python 3.12 is documented without the vendor SDK | isolate the read-side vendor source behind a bounded process contract and product-path test | X14, L05, O13 |
| Socket deadline is not enforceable for injected blocking transports | `_read_until_empty` relies on an outer clock but a blocking `recv()` cannot be pre-empted; good-frame count does not cap corrupt datagrams | reject blocking sockets; cap attempts/bytes/time; dedicated ingest publishes a bounded immutable latest snapshot | R21, R35, T07 |
| Physical truth still rides through `SimObservation` plus an identity side channel | `Go2Backend.observe` returns simulator-shaped data; runtime later asks `scan_datum_for(observation)` | neutral stamped navigation evidence assembled once; no restamping or N+1 scan attached to N state | X03, X04, R20 |
| Physical pose provenance cannot satisfy the strict profile | initial Fable trace reports `evidence_origin()` still stamps the pose SIMULATION and `CommissionedStateSource` has no product caller | put commissioned pose/state provenance and per-source receipt clocks in `ARCH-OBS-MIN`; raw state remains UNKNOWN/HOLD | X15, R05, R19 |
| Injected transports can counterfeit PHYSICAL origin | `LiveGo2Sources.origin` is PHYSICAL even when arbitrary injected `state_source`/socket doubles are supplied | only a production factory with commissioned device/transport identity may mint PHYSICAL; dependency-injected transports remain TEST/UNKNOWN | X15, T15 |
| The resolved physical profile inherits simulator truth | the overlay comments out battery/NIC values, but deep merge retains `battery.simulated_percent: 90.0`, `control.unitree_sport.interface: enp3s0`, and base safety/controller values from `robot.yaml` | validate the fully resolved profile; support explicit deletion/required physical fields; refuse synthetic battery, placeholder NIC/extrinsics, and uncommissioned thresholds | X06, A08, R14 |
| Product admission covers modules, not the separate safety authorities | the eight `required_capabilities` are static semantic/navigation-module checks; they cannot establish fresh pose/scan/person/terrain, stopping fit, sole-writer credentials, or an independent physical E-stop | keep four owners separate: typed static factory identity; continuous input-health × axis/mode table; deployment/credential attestation; independent operator/physical evidence. No YAML may mint live authority | X06, X13, R04, R13 |
| Raw Unitree odometry can masquerade as navigation pose | `state_from_sport_mode_state` maps vendor position/yaw into `RobotPose` without commissioned odom reset/jump/frame/clock semantics or state/scan alignment; MAP has no TF/covariance/localizer | origin stays UNKNOWN until the ODOM producer is commissioned; local reactive ODOM need not wait for localization, but MAP remains forbidden until a localizer owns TF/covariance/loss | R05, R08, R19 |
| No bounded reactive person/dropoff safety channel exists | Go2 observation leaves person/dynamic-agent fields empty; D455 paths serve mapping/owner tracking, and the Mid-360 cannot establish negative terrain | independent bounded-latency person/terrain inputs with stale/unplug/degraded dispositions and onboard-avoidance interaction tests | X10, R11, R13, R33 |
| Mic lock ownership needs characterization | HTTP adds `_ARRAY_MIC_ROUTE_LOCK`, while runtime directly calls `close_mic`; however `set_mic`, `close_mic`, and `stop` already share the gateway's `_mic_lock`, so a race is not yet demonstrated | seed HTTP/direct/runtime interleavings; remove or relocate the web lock only after a failing ownership/deadlock/redundancy case is proved | A23 |
| Active stopping regime is record-selected, not visibly tied to commanded speed | V1/V2 records carry `active_regime`; no product coupling proves the selected speed regime | bind regime selection to commissioned command limits/config revision and refute mismatch | R09 |
| Orin evidence remains structural | nftables/systemd files, Jetson locks/installers, and the aarch64 job have not executed on the target; the QEMU job is 300 minutes and `continue-on-error` | target apply/reboot/rollback and clean-install matrix; redesign the job into bounded high-signal stages before hardening | L07, O07, P15 |
| Perception installer can false-succeed and is not artifact-pinned | it declares expected wheel metadata but installs from an extra index without verifying the resolved wheel; import/CUDA-provider failures only warn before “done” | immutable direct wheel URL/hash/no-index or equivalent locked artifact; verify installed dist/interpreter and make import/CUDA/session smoke nonzero for target admission | L08, L09, O07 |
| The present 10 Hz path already violates the proposed clean-loop target | initial Fable trace names synchronous hosted WebSocket send, spend-ledger disk read, and duplex filler work reachable from `_step_whisperer` | word the rule as an unmet `ARCH-LOOP` target and characterize/handoff those operations; do not claim it holds today | A04, T07 |
| Native cutover can leave the Python Sport writer live | commissioning/product Python writer remains in-tree after the proposed early native rail unless credentials are explicitly stripped | atomic credential cutover and post-change B30-class product-path regression; never two live writers | X02, R01, O02 |

## System decomposition map

| ID | Landed system | Current responsibilities | Proposed bounded owners | Disposition / order |
|---|---|---|---|---|
| W3-01 | Python 3.10 compatibility and package locks | syntax/source scanner, guarded imports, two Jetson records, shell architecture branches, CI jobs | package compatibility matrix; reusable capability probe; artifact manifest | `RATCHET_ONLY`; fold into `ARCH-PKG`/`ARCH-CI` |
| W3-02 | Go2 observation backend | replay parsing/cursor, DDS state, UDP transport, state decoding, origin labeling, scan projection, snapshot join, lifecycle, config parsing, motion refusals | `Go2StateCodec`; `Stage0Replay`; read-only vendor sidecar client; commissioned origin factory; `LivoxIngest`; `Go2ObservationAssembler`; typed config; facade | P0 `EXTRACT_FACADE` under `ARCH-OBS` |
| W3-03 | Commissioned scan evidence | origin declaration, identity binding, epoch/sequence/receipt ordering, sticky latch | neutral `ScanDatum` contract plus the existing single latch owner | P0 contract migration, but `PRESERVE_STATE_MACHINE` internally |
| W3-04 | Mid-360 codec, band, and venue declaration | wire enums/parser, sequence report, UDP receive, fixture encoder, calibration, extrinsic, banding, obstacle selection; venue rows are not yet part of canonical record/preflight/attestation paths | codec/DTO; transport ingest; test fixture encoder; calibration; shared geometry policy; one recordable channel registry | P1 `EXTRACT_PURE`; target benchmark before choosing Python vs official native/ROS driver |
| W3-05 | XVF3800 array audio | device discovery, capture/output streams, duplex lifecycle, queue/thread, resampling, session gesture, playback, duck/interrupt, metrics/events | `ArrayDeviceResolver`; one `Xvf3800DuplexLifecycle`; `CapturePump`; `PlaybackScheduler`; state/metrics DTO; facade | P1 `EXTRACT_FACADE`; keep duplex lifecycle atomic |
| W3-06 | Stopping envelope | schema, validation, provenance, arithmetic, resolution/I/O, row rendering, two model versions, CI stage | current six-term domain model; legacy V1 reader; record repository; gate renderer | P0 correctness first, then `CONSOLIDATE_VERSIONED` |
| W3-07 | Physical config and application composition | loose key admission, deep-merge inheritance, backend/band parsing, audio selection, runtime/web construction, venue lookup | typed `BackendConfig`, `BandCalibration`, `AudioConfig`, complete resolved `RobotProfile` with deletion/required semantics; backend/audio factories | P0 resolved-config refusal, then `MOVE_COMPOSITION` under `ARCH-CONFIG` |
| W3-08 | Array mic HTTP/UI route | authorization, request decoding, device transition, additional process-global route lock, HTTP status/body mapping, UI debounce | gateway `_mic_lock` already owns stop/set/close transitions; preserve it. Treat the web lock as only candidate-redundant until seeded interleavings prove removal equivalence; separately characterize output-open concurrency | preserve-first; no split-serialization defect |
| W3-09 | Host gate/installers | capability discovery, skip transformation, stages, runner, summary, shell downloads, provenance | `quality.capabilities`; `quality.stages`; runner/renderer facade; process/artifact manifest | P1/P2 `EXTRACT_FACADE`; correct hard-skip semantics first |
| W3-10 | Orin firewall/deployment | static policy, interface variables, services, rollback hooks, optional container rules, prose procedure | policy templates; target inventory; install/validate/rollback tool; complete systemd process topology | `TARGET_PROVE` under first-class `ARCH-DEPLOY` |
| W3-11 | Hardware-card test suite | fakes, fixture encoders, source-shape checks, behavior tests, process tests, deployment parser, product wiring | seam-owned unit/contract suites; shared protocol fakes; product-path integration; target/HIL evidence suites | P1 `MOVE_TEST_SUPPORT` under `ARCH-TEST`; preserve old node-ID map |

The intended dependency direction is:

```text
typed contracts + pure domain
             ^
             |
sim/replay adapters    target sidecars/drivers
             \          /
        snapshot assemblers
                 ^
                 |
     application factories/facades
                 ^
                 |
       runtime / CLI / web routes
```

No vendor SDK, socket drain, PortAudio callback, HTTP handler, model, storage,
or UI operation belongs below the bounded snapshot/final-admission deadlines.

## Complete product declaration coverage

The following grouped rows account for every new or definition-body-modified
product symbol. A grouped method list is exhaustive; trivial DTO accessors are
still named even when the disposition is preserve.

### Go2 backend and evidence

| Symbol group | Members | Disposition and destination |
|---|---|---|
| Errors/DTO helpers | `Go2BackendError`, `Go2MotionRefused`, `Go2SdkUnavailable`, `Go2StateUnavailable`, `Go2ReplayError`, `_StateSample`, `_finite`, `_floats` | keep dependency-light; errors/contracts module only if facade split lands |
| State codec | `state_from_sport_mode_state` | `EXTRACT_PURE` to one replay/live Unitree state codec; golden differential |
| `RecordedStage0Source` | `__init__`, `_load`, `header`, `start`, `close`, `_elapsed`, `latest`, `drain` | preserve cursor/clock state; extract only pure JSONL validation from `_load` |
| `LiveGo2Sources` | `__init__`, `_checked_socket`, `open_livox_socket`, `_probe_sdk`, `start`, `close`, `latest`, `_count_refusal`, `_read_until_empty`, `drain` | split vendor state adapter behind its read-only sidecar from a separate bounded LiDAR ingest owner; do not combine clocks/lifecycles by default |
| `Go2Backend` | `__init__`, `start`, `close`, `latest_scan`, `scan_datum_for`, `latest_scan_age_s`, `observe`, `_observation`, `_refuse`, `move`, `pose`, `trajectory`, `move_owner`, `set_owner_visible`, `stop`, `emergency_stop`, `clear_emergency_stop`, `expression` | keep facade and typed positive-motion refusals; extract assembler; never reuse no-op stops after writer cutover |
| Config parser | `band_profile_from_config` | move to typed band/backend config; preserve strict unknown-key behavior |
| Scan evidence | `ScanDatum`, `ScanEvidenceSource.evidence`, `CommissionedScanSource.__init__`, `.latched_reason`, `.evidence`, `._ordering_fault` | neutral contract plus `PRESERVE_STATE_MACHINE`; audit/read-lock property |

### Stopping, capture, LiDAR, and audio

| Symbol group | Members | Disposition and destination |
|---|---|---|
| Envelope V1 domain | `Unmeasured.__str__`, `StoppingRegimeV1.modelled_travel_m`, `envelope_regime`, `_envelope_term`, `StoppingEnvelopeInputsV1.__post_init__/value/provenance_of/missing/fully_measured`, `EnvelopeVerdictV1.fits/line`, `derive_envelope`, `derive_envelope_rows` | current arithmetic/policy module after V2 correctness fix; renderer separate |
| Envelope repositories | `resolve_stopping_envelope_record`, `load_stopping_envelope_record` | legacy-compatible repository adapter; no arithmetic or gate policy |
| Envelope V2 | `StoppingEnvelopeInputsV2.__post_init__/active_regime/host/source/value/provenance_of/missing/fully_measured`, `derive_envelope_v2`, `derive_envelope_rows_v2`, `load_stopping_envelope_record_v2` | make the one current six-term model; retain V1 compatibility reader, remove duplicated policy only after migration |
| Venue declarations | modified `SourceDevice`; `VenueChannel.__post_init__`, `.bag_topic`, `.is_spatial`, `.carries_a_time_anchor`; `venue_channel`, `venue_channels_for` | keep immutable row; move registry/lookups when capture schema is extracted |
| Band DTO/policy | `BandProfile.__post_init__/_check_extrinsic/angle_increment_rad/footprint_radius_m/bin_bearing_rad`; `BandScan`; `ObstacleFix`; `band_scan`; `scan_from_frames` including `_points`; `travel_bearing_rad`; `nearest_obstacle_from_scan`; `_wrap` | pure/calibration split only; share obstacle geometry with sim via differential tests |
| Livox codec | `LivoxDecodeError`, `LivoxDataType`, `LivoxTimeType`, `LivoxPointFrame.synchronised/timestamp_ns/points_m/xyz_m`, `parse_point_frame`, `_undecodable_reason`, `FrameSequenceReport.contiguous`, `sequence_report` | cohesive codec module; add official-driver/pcap/CRC differential evidence |
| Livox transport/test support | `receive_frames`, `build_point_frame` | transport moves to ingest owner; encoder moves to test support |
| Audio selection/error | `ArrayDeviceError`, `_portaudio_errors`, `resolve_audio_gateway_selection` | resolver/config boundary; error translation remains facade-visible |
| `RationalResampler` | `__init__`, `ratio`, `output_length`, `reset`, `process`, `process_pcm16` | `PRESERVE_STATE_MACHINE` as a deterministic, stateful streaming primitive |
| `ArrayAudioGateway` | `__init__`, `_audio_module`, `_teardown_errors`, `_absent_text`, `resolve_device`, `probe`, `bind_token`, `start`, `stop`, `running`, `mic_open`, `device_index`, `set_mic`, `_set_mic_locked`, `close_mic`, `_open_capture`, `_close_capture`, `_on_block`, `_reader_loop`, `_check_deaf`, `_offer_block`, `begin_utterance`, `send_audio`, `_ensure_output`, `_close_output`, `_on_playback`, `duck`, `interrupt`, `played_started_monotonic`, `voice_identity`, `_note`, `snapshot` | facade over resolver, one duplex lifecycle, capture pump, playback scheduler, and state/metrics; callbacks remain bounded and lifecycle lock order explicit |

### Existing facades modified by Wave 3

| Symbol group | Change | Disposition |
|---|---|---|
| `RobotRuntime` | class body; `input_health_latch`; new `_scan_source_record`; `_build_realtime_sink`; `_evaluate_dispatch_input_health` | move evidence join to snapshot assembler and audio construction to factory; retain public facade |
| `unitree_control` | `_run_observe`; new `_positive_seconds`; `_build_parser` | preserve CLI compatibility; pure duration/window runner only if another observe mode arrives |
| `RuntimeRequestHandler` | class body; `do_POST`; `_serve_realtime_audio` | split route/service dispatch only when valuable; gateway `_mic_lock` stays lifecycle owner; remove web lock only if characterization proves redundancy |
| web composition | new `_build_backend`; modified `build_runtime` | `MOVE_COMPOSITION` to typed application factory |
| compatibility-only modules | `bridge/client.py`, physical camera, context models/builder, observability, map store, owner gallery, perception client/server, providers, backend/lidar barrels | `RATCHET_ONLY`; no decomposition card |

## Complete operational-function coverage

| Area | New/changed declarations | Disposition |
|---|---|---|
| `scripts/ci_gate.py` stopping stage | `evaluate_stopping_envelope` | move stage/rendering behind CLI facade after six-term correction |
| host capabilities | `_HW7Recorded` and `__init__/__exit__`; `_hw7_find_spec`; `_hw7_spec_present`; `_hw7_spec_evidence`; `_hw7_portaudio`; `_hw7_cuda`; `host_capabilities` with nested `measured`/`module`/`fact`; `hw7_skip_result`; `hw7_apply_host_skips`; `evaluate_host_capabilities` | capability probes must be total and side-effect-free; skip policy separate and hard-row semantics fail-closed |
| gate runner/output | modified `run_commit_tier`, `summarize` | preserve stage order, JSON, exit code, and failure-complete rendering behind facade |
| capture venue selection | `_venue_for_profile`, `active_venue`, `_accepts_venue`, `_venue_bound`, modified `adapter_for`, `coverage` | venue registry/config adapter; no profile reads hidden in device adapter constructors |
| L2 retirement gate | `refuse_retired_venue`, modified `L2Ingest.__init__`/class | keep explicit refusal; share typed venue identity later |
| new Jetson perception installer | `log`, `die`, `usage`, `refuse_unless_aarch64`, `resolve_index`, `print_plan`, `write_provenance`, `check_provider`, `main` | pre-target correction: immutable hash-verified artifact/no-index install, verify venv interpreter/dist, and hard-fail target import/CUDA/session smoke; then keep a thin manifest-driven installer |
| audio/speech shell changes | module-level architecture selection; modified `env_audio_verify_shas`; new `env_audio_dry_run` and CLI dispatch; modified speech `usage`/`main`; new `print_plan` and Piper asset selection | preserve dry-run/refusal; unknown-architecture checksum/asset guesses stay visibly non-promotional; extract shared shell library only with proven duplication and shell contract tests |

## Non-Python artifacts

| Artifacts | Decomposition decision | Required evidence |
|---|---|---|
| `configs/robot.go2_edu_plus.yaml`, venue config, envelope records | data remains separate; centralize typed static schema/factory identity and explicit delete/required semantics, not live authority or the records themselves | inspect the fully resolved profile; reject inherited simulated battery/NIC/threshold truth; continuous health, credentials, stopping evidence, and physical E-stop remain separate authorities |
| `deploy/orin/nftables*.conf`, services, `containers.conf` | separate static least-privilege policy from box-specific interfaces and install/rollback procedure | `nft -c`, apply, required/forbidden flows, SSH recovery, reboot, idempotence on Orin |
| Jetson requirement records and `pyproject.toml` | one signed process/interpreter/artifact matrix; do not merge incompatible venvs | clean aarch64 wheel install/import/inference; hashes/providers/SBOM/license |
| CI jobs | reusable bounded capability/install/gate stages only if they reduce duplication | first recorded aarch64 run; remove `continue-on-error` only in evidence-bearing change; explicit compute SLA |
| UI mic controls | keep UI state small; route client may be isolated if more hardware actions arrive | authorization, debounce, simultaneous calls, restart and failure rendering |
| `CODEBASE_INDEX.md` | index is navigation metadata, not an architecture boundary | hash/staleness check; source-first retrieval benchmark; exclude historical/evidence noise |

## Test-suite decomposition plan

Do not split by card number or optimize for fewer tests. Preserve every hard
node ID until a checked old-to-new mapping lands, and move only stable protocol
fakes into shared support.

| Current module | Size / shape | Proposed suites | Preserve before moving |
|---|---:|---|---|
| `test_hw1_py310_clean.py` | 576 lines; 11 tests; 7 helpers | package-compat scanner unit tests; clean-import/grammar contract | seeded newer-syntax and guard mutants |
| `test_hw2_go2_backend.py` | 1,829; 49; 13 helpers/5 fakes | state codec, replay, live transport, refusal, scan-evidence unit suites; product factory/runtime integration; envelope-V2 integration | replay-origin HOLD, identity N/N+1, corrupt datagram, disconnected source, refusal semantics |
| `test_hw3_mid360_band.py` | 1,112; 41; 2 helpers/1 fake | Livox codec/property/fuzz; band geometry; transport; capture retirement contract | absent-vs-empty scan, NaN bins, transforms, simulator differential, corrupt/unsupported types |
| `test_hw4_array_gateway.py` | 1,337; 32; 11 helpers/3 fakes | resampler, resolver, duplex lifecycle, capture pump, playback, config/product route, concurrency | through-air ordering, billed-session refusal, unplug/open rollback, thread/stream leak refuters |
| `test_hw5_physical_profile.py` | 969; 16; 9 helpers/1 fake | typed resolved-profile/schema unit; application-factory integration; physical-origin admission | typo mutants, no-oracle fields after deep merge, inherited synthetic battery/NIC refusal, real launcher refusal, replay cannot become physical |
| `test_hw6_stopping_envelope.py` | 748; 22; 7 helpers | current domain arithmetic; legacy record migration; repository; gate stage | ULP edge, missing provenance/term, active-regime mismatch, added scan-age mutant |
| `test_hw7_gate_aarch64.py` | 691; 33; 3 helpers | total capability probes; pure skip policy; runner/summary integration; installer dry-run; workflow structure | absent hard capability must not PASS; hostile import finder; failure-complete JSON |
| `test_hwfw_nftables.py` | 849; 24; 12 helpers/5 parser classes | static policy unit; parser support module or real `nft -c` container; target network integration | required/forbidden flows, no flush, rollback/SSH recovery; custom parser is not target proof |
| `test_hwmic_arm_route.py` | 752; 16; 8 helpers/4 fakes | route adapter integration plus existing gateway lifecycle concurrency | auth-before-touch, strict bool, browser/array/none mapping; replace stale route-lock source claim/ineffective S8 with behavior proving all real gateway entry points remain serialized without leaks |
| `test_prototype_profile.py` Wave 3 delta | +74 lines | existing config regression suite | default/prototype behavior remains byte/behavior compatible |

Shared test support should contain only protocol-level `FakeClock`, fake
datagram/socket, fake PortAudio streams, config builders, and replay encoders.
The five-class nftables parser belongs in test support if retained.
`build_point_frame` should leave product code once no public caller needs it.
Card fences, literal source regions, and hash pins may be retired only after a
stronger behavioral/boundary oracle and its seeded mutant are green.

## Unit, integration, and quality/eval matrix

| Boundary | Unit/contract | Integration/product-path | Quality/target/physical | Required refuter |
|---|---|---|---|---|
| Neutral observation | frozen origin/frame/epoch/receipt/device DTO; absent stays absent; order properties | actual `build_runtime` through runtime health with replay/live adapters; loop plus HTTP reader | recorded DDS/Mid-360 trace, Orin age/drop/jitter; no localization claim | disconnect commissioned source; injected fake remains TEST/UNKNOWN; attach scan N+1 to observation N; restamp stale evidence |
| Go2/Livox ingest | socket mode, attempt/byte/time caps, parser fuzz, CRC/type/sequence/reset | vendor-state sidecar crash/restart plus independent LiDAR-ingest malformed flood; facade bounded snapshot read | official-driver/pcap differential; sustained 12k-point sweeps under Orin load | first `recv()` never returns; unlimited corrupt datagrams must fail the test |
| Band/geometry | transform/metamorphic rotation, bin/NaN/absent semantics, footprint/corridor policy | simulator/physical differential on identical points | real extrinsic calibration and obstacle fixture | behind/out-of-band point must not mask travel-corridor obstacle |
| Scan latch | identity reread, distinct duplicate, epoch/sequence/receipt regression, sticky latch | real product factory and concurrent reader | replay/SIL now; real loss/reorder later | origin string, replay origin, or raw uncommissioned source must HOLD |
| Stopping envelope | all six terms, provenance, ULP arithmetic, regime binding, migration | shipped record through actual CI stage and command-limit config | dev bench only for its topology; Orin/robot terms replace, never scale, desktop numbers | remove/zero scan age or select faster regime than command limit; gate must red/unmeasured |
| Array audio | resampler properties; lifecycle transition model; queue/deaf/error counters | repeated arm/disarm, callback errors, unplug, direct+HTTP+runtime concurrency | target device soak, latency/drop/echo/through-air capture; human audio milestone only | fail every open/close step; randomized stop/arm/close leaves zero leaks/sessions |
| Config/factories | strict unknown/type/range/schema versions, explicit deletion/required fields, static factory/device identity | fully resolved physical profile selects exact sidecar/backend/audio; continuous health and credential/physical attestations enter through separate owners | clean installed target launcher, not direct class construction | inherit synthetic battery/NIC, inject fake as PHYSICAL, or mutate physical source to replay/array to browser; each must redden |
| CI/package | total probes, hard/soft/report-only truth table, renderer/exit code | clean venv, real subprocess boundary, valid failure-complete JSON | bounded native aarch64 then target install/provider smoke; compute/time report | remove pytest/ruff/xdist/MuJoCo and require nonzero unsupported/fail, never PASS |
| Deploy/firewall | policy/template parsing and identity validation | ephemeral namespace/container required/forbidden flows; service restart-disarmed | Orin apply/reboot/rollback; real `CYCLONEDDS_URI` interface/peer binding, adversarial robot-LAN DDS injection, clock sync, product/gateway/sensor service order, resource/soak evidence | wrong NIC/locked-out SSH/foreign DDS/old epoch/second writer all prevent promotion |

No aggregate quality score can compensate for a red authority, stale evidence,
blocking deadline, false-arrival, one-writer, exact-zero stop, or restart-disarmed
invariant.

## Safe extraction sequence

1. **Correction/characterization only:** Fable reproduces the immediate
   hazards; add refuters for hard-capability skips, scan-age omission, blocking
   socket, resolved-profile simulator inheritance, and cross-entry mic
   interleavings. No file movement yet.
2. **`ARCH-OBS-MIN`:** introduce neutral stamped evidence and a bounded ingest/
   read-side sidecar contract. Migrate the runtime health join and product
   factory while the `Go2Backend` import/API remains compatible.
3. **`ARCH-CI` + envelope correction:** make hard-skip truth fail-closed and
   make the six-term model the current gate. Consolidate model/repository/
   renderer only after behavior is pinned.
4. **`ARCH-AUDIO`:** extract resolver and metrics first, pumps second, duplex
   lifecycle last. Preserve the gateway `_mic_lock`; characterize every
   lifecycle entry point and output-open concurrency, then remove the
   candidate-redundant web lock only with behavioral equivalence. Audio
   callbacks remain nonblocking and use the bounded callback/queue handoff.
5. **`ARCH-CONFIG`/`ARCH-PKG`/`ARCH-DEPLOY`:** typed factories and the signed
   process/artifact/service matrix; prove clean target install and rollback.
6. **`ARCH-TEST`:** relocate shared fakes and split card modules by seam after
   node mapping and mutant parity. Low-value chronology/source fencing is
   consolidated rather than generating more cards.

The accepted lane rule is stricter than generic WIP two: at most one Python-
product card plus one genuinely disjoint native/capture/CI lane. Work sharing
runtime, web composition, CI registry, pinned symbols, structural-oracle tests,
or a lifecycle lock is sequential. The physical gateway bench must not wait
for audio/test cleanup; product credentials still wait for accepted observation,
deployment, independent-stop, and commissioning evidence.

## Separate physical-promotion sequence

The extraction order above is not permission to move hardware. Promotion has
its own monotonic ladder:

1. Prove the operator-held independent E-stop first. Start Parcel observe-only
   under an owner/manufacturer-approved quadruped stand/restraint and clear-zone
   procedure, with no product writer credential.
2. Capture real Go2, Mid-360, D455, XVF3800, and Orin evidence, including
   clocks, queues, loss, freshness, transforms, device identity, and resolved
   physical configuration.
3. Introduce exactly one native writer on the restrained robot. Reject a second
   writer; test gateway/client kill, SIGSTOP, restart, stale input, NIC/session
   loss, old epoch, and watchdog decay. Every motion-capable path has real stop/
   emergency-stop semantics; it never inherits `Go2Backend`'s observe-only
   no-ops.
4. Run one manufacturer-approved unloaded/stand command-path proof, which says
   nothing about ground stopping distance, then 3–5 inspected ground-contact
   stops at the lowest admitted speed with independent motion truth and aborts.
5. Permit leashed crawl in a people/dropoff-excluded ODD only after independent
   E-stop, sole writer/real stop/TTL, the six-term stopping envelope, and
   commissioned pose/scan freshness fit their limits.
6. Before enabling the corresponding ODD or autonomy, repeat obstacle/person/
   stairs/dropoff/occlusion, detector/localizer loss, onboard-avoidance, load,
   temperature, network, and restart trials.

Desktop, fake-process, QEMU, source-shape, and structural firewall results
cannot skip a rung.

## Fable acceptance questions for this delta

1. Does every definition group above have one explicit extract/preserve/target-
   prove disposition, with no safety state machine split merely for length?
2. Must the scan-age and hard-skip findings be corrected before the unchanged
   Wave 3 gate can support any integration claim?
3. Is a read-only Unitree vendor-state sidecar plus a separate bounded
   Mid-360/LiDAR ingest owner the accepted resolution, and what exact IPC
   schemas/deadlines apply to each? Co-location requires explicit independent
   clock/lifecycle/failure-domain evidence.
4. Does the neutral observation design delete the identity/re-stamping side
   channel after migration and prevent scan N+1 from grading observation N?
5. Do the gateway's existing `_mic_lock` transitions already cover HTTP,
   runtime, and direct lifecycle callers; is the process-global web lock
   redundant or protecting a distinct invariant; and which seeded
   interleaving demonstrates the answer? Do PortAudio callbacks remain
   nonblocking on their bounded callback/queue path while output-open
   concurrency is characterized?
6. Which source-shape tests remain legitimate architecture/package policy, and
   which are replaced by observable contracts and mutants?
7. Does the resolved physical configuration fail closed on inherited simulator
   truth, and are the Mid-360 venue rows reachable from actual record,
   preflight, budget, and attestation paths?
8. Which proposed work is required for the next physical milestone, which is
   safely deferred, and what tranche budget/stop gate applies?

The partial supplement was bounded to this file's high-severity seams. It still
owes L11 and the explicit truth-table/schema/disposition answers identified in
`README.md`. The initial verdict reports 556k tokens and nine review agents;
the correction must be one narrow attributed pass. Any later implementation
re-review is limited to the exact correction diff and its named refuters.

## What this addendum does not prove

This is static analysis of an integrated commit plus its committed test/evidence
records. It does not independently reproduce the claimed commit-tier gate. It
does not prove a full suite, aarch64 execution, Orin installation, nftables
reachability, vendor DDS compatibility, Mid-360 protocol/CRC correctness,
deadline performance, physical sensing, stopping, localization, audio quality,
one-writer authority, or autonomous motion. The implementation remains
desktop/synthetic/replay evidence until each matching rung is executed.

## Post-freeze Claude worktree decomposition — provisional

This appendix answers the follow-up request to decompose code Claude began
after the fixed Wave 3 audit. It is deliberately not folded into the
`0ce1c5f..c1b8405` counts or Fable disposition. The snapshot was frozen at
2026-08-23 17:00 EDT with both `HEAD` and `origin/main` at `3792288`; the six
paths were dirty/untracked and can still change before integration.
The frozen scope totals +1,240/-11 lines; `go2.py` alone reaches 1,229 lines.

| Live card | Frozen paths and size | Frozen blob IDs | Evidence status |
|---|---|---|---|
| SENSE-1, partial | `backends/go2.py` +239/-11; `core/input_health.py` +200; `lidar/livox_udp.py` +30 | `e89ff78b7444`; `a811bc4149da`; `567da1833157` | 469 added product lines and no SENSE-specific test path in the snapshot; not runtime-complete |
| PROX-1, partial | new `navigation/proximity_profiles.py` 394 lines; new test 230 lines; status 147 lines | `c5d3a4282b15`; `9caf64fa912b`; `fb435647b133` | status reports 7 focused +197 neighbor +67 ratchet passes, not independently rerun; product and base-config wiring explicitly absent |

Claude subsequently began editing physical config, gate, and existing hardware
test paths, including `src/parcel_robot/config.py`, the Go2 overlay,
`scripts/ci_gate.py`, and HW2/HW6 tests. Those moving bytes are outside this
frozen six-path appendix and need their own post-integration delta review.
Nothing in this appendix modifies Claude's product, test, config, or status
files.

### Exhaustive new/modified declaration groups in the frozen live snapshot

| ID | Declaration group | Added/modified behavior | Decomposition disposition |
|---|---|---|---|
| LIVE-S01 | modified `RecordedStage0Source.__init__` and `drain`; new `last_frame_received_at` state | records host delivery time for the last replay frame | preserve replay cursor; carry receipt in each returned datum instead of mutable source-wide side state when the neutral contract lands |
| LIVE-S02 | `LiveGo2Sources.DEFAULT_DATAGRAM_BUDGET_FACTOR`; modified `__init__`, `_read_until_empty`, and `drain`; new `_socket_reports_blocking` | caps total datagrams, checks an expiry callback, refuses a socket reporting blocking, counts bounded/refused drains, and records a last-frame receipt | retain the corrupt-flood cap; split Unitree state from an owned LiDAR ingest worker; the control/HTTP observation lock reads an immutable mailbox only |
| LIVE-S03 | modified `receive_frames(max_datagrams, expired)` | checks attempt/time budgets before each `recv` while preserving corrupt-datagram refusal | keep a pure bounded transport primitive only for demonstrably nonblocking transports; timestamp immediately after receive and return typed receipt with the frame |
| LIVE-S04 | `PoseDatum`; `PoseEvidenceSource`; `CommissionedPoseSource.__init__`, `latched_reason`, `evidence`, `_ordering_fault` | mirrors scan provenance/order latching for pose | keep the typed pose contract, but include producer epoch and pose identity/fingerprint; first pin scan/pose differences, then share a small validated ordering-latch core rather than maintaining two near-copies; export the accepted public symbols |
| LIVE-S05 | modified `Go2Backend.__init__` and `observe`; new `_graded_pose`, `pose_evidence_source`, `pose_datum_for`, `_scan_receipt` | identity-binds pose evidence to an observation and separates assembly, pose-receipt, and scan-receipt clocks | move to `NavigationSnapshotV2` assembler; do not extend the simulator carrier/identity side channel or the already-large Go2 facade |
| LIVE-P01 | `PROXIMITY_PROFILES_CONFIG_KEY`; `_NARROW_PROFILE`, `_INDOOR_PROFILE`, `_DEFAULT_PROFILE`; `PREREGISTERED_PROXIMITY_PROFILES`; `VENUE_PROXIMITY_CONTEXT` | declares three static distance pairs and a venue-to-context default | retain a typed immutable registry, but put accepted values and venue mapping in fully resolved commissioned config; absence must preserve the base policy for every supported body/envelope |
| LIVE-P02 | `ProximityContext` and `parse` | restricts callers to `default`, `indoor`, or `narrow` instead of raw distance | preserve; use the same enum in the tool schema and reject bool/non-real config values strictly |
| LIVE-P03 | `ProximityProfile`, `apply_to`, `from_mapping` | applies a pair through `ReactiveSafetyPolicy` and parses a mapping | preserve the validator reuse; make parsing strict/finite and validate exact typed table shape before constructing a profile |
| LIVE-P04 | `proximity_context_for_venue`; `resolve_proximity_profile`; `load_proximity_profiles` | selects/loads profiles and validates each against one base policy | keep pure resolution; separate config loading from the registry; scope profiles to the commissioned robot/envelope rather than silently installing Go2 constants for every body |
| LIVE-P05 | `ProximityContextOwner.__init__`; `base_policy`, `profiles`, `context`, `policy`, `last_source`; `set_proximity_context` | stores active policy/context/source and immediately swaps to the requested profile | refactor before wiring: a model produces a `ContextProposal`; a deterministic safety owner accepts/rejects, expires, and atomically publishes one immutable `(policy, context, source, revision, time)` snapshot |
| LIVE-P06 | `shipped_safety_section`; `proposed_safety_section`; `shipped_policy`; seven `test_*` functions and nested `up_to_5cm` | proves the pure ladder/floor/default/enum behavior against a proposed YAML block | retain behavior tests; remove test-owned configuration as an authority once an owner-approved typed config lands; add the refuters below |

LIVE-P06's seven exact test functions are
`test_the_shipped_ladder_shortens_and_every_rung_clears_the_existing_floor`,
`test_a_context_switch_swaps_the_active_pair_on_the_real_gate`,
`test_a_below_floor_profile_is_refused_by_the_unchanged_validator`,
`test_no_new_config_keys_leaves_todays_behaviour_byte_identical`,
`test_a_reasoning_model_may_propose_a_context_but_never_mint_a_distance`,
`test_an_unknown_venue_gets_the_widest_profile`, and
`test_the_ladder_literals_still_match_their_stated_derivation`.

### Provisional correctness verdict

The useful pieces are the typed context enum, immutable profiles, reuse of the
existing safety-floor validator, identity-keyed pose evidence, intent to carry
per-channel receipt time, and the all-corrupt datagram cap. They are seams to
retain, not completed physical capabilities.

| Blocker | Concrete frozen-snapshot evidence | Required correction before integration |
|---|---|---|
| Pose seam is dead at the product boundary | the new Go2 comment explicitly says there is no product read site; runtime still derives POSE from simulator-shaped observation evidence and only has a commissioned SCAN override | runtime/product entrypoint consumes keyed pose evidence; live passes while replay, injected fake, absence, and malformed evidence HOLD/LATCH as specified |
| Dependency injection can still counterfeit PHYSICAL | `LiveGo2Sources.origin` remains PHYSICAL when an arbitrary injected `state_source`/socket bypasses the SDK; the new pose wrapper commissions that inherited origin | only an attested production factory/device identity mints PHYSICAL; injected transports are TEST/UNKNOWN regardless of wrapper class |
| Drain deadline is not hard | an opaque injected `recv` without `gettimeout` is accepted, and `expired` is checked only before the uninterruptible call; a read-only probe remained blocked beyond 80 ms | owned nonblocking OS transport or isolated ingest worker, hard wall-time refuter, attempt/byte bounds, and no device I/O on the control/HTTP lock |
| Receipt handling can fail fresh | `_scan_receipt` substitutes assembly time for missing/non-finite receipt; receipt is sampled after decode, and the last frame can be newer than other points contributing to the sweep | PHYSICAL missing/invalid receipt is invalid evidence; timestamp at receive, carry per-frame clock domain/epoch, and grade the oldest relevant contributing measurement/accumulation bound |
| Pose boundary is weakly typed and epoch check is circular | `PoseDatum` validates no field; a probe accepted a string sequence as valid. Datum and wrapper both use the backend epoch while producer `state.session_epoch` is ignored | strict finite/type/frame/sequence/epoch validation; producer restart, reset, regression, clock-domain, and malformed-first-sample refuters |
| Pose equality omits the pose | reread exemption compares `PoseDatum`, but it carries metadata only; different positions with colliding sequence/time/epoch compare equal | carry a producer datum identity or pose fingerprint and refute different-payload/same-metadata samples |
| Raw Unitree coordinates are still called `odom` | the seam adds provenance but no commissioned reset/jump/TF/covariance semantics | ODOM producer commissioning before local use; MAP remains forbidden until localization owns TF/covariance/jump/loss |
| The advertised 20 ms is not end-to-end | parse, tuple creation, band construction, and observation assembly occur afterward under the shared lock; concurrent runtime/HTTP callers can consume or delay the single drain | sole ingest owner; maximum-valid-frame p99/max benchmark under load; concurrent callers only read the same immutable keyed snapshot |
| Proximity “proposal” is an immediate safety relaxation | `set_proximity_context` directly assigns a policy as tight as 0.70 m; `source` is logging-only, with no acceptance, TTL, confidence, hysteresis, or fallback | separate proposal from authority decision; stale/unknown/conflicting context returns to widest commissioned profile, and switch publication occurs at a tick/revision boundary |
| No-key compatibility is not general | fixed Go2 indoor/narrow profiles are installed and validated even with no config key; a read-only wide-body-policy probe failed construction | absent key creates only the base/default behavior, or the module is explicitly type-scoped to a commissioned Go2 body and rejects other use clearly |
| Config typing admits surprising values | `float(...)` converts YAML `true` to `1.0`; a read-only probe passed that value through validation | reject bool/string/non-real/NaN/Inf, normalized duplicate context names, missing/extra contexts, and unrecognized keys |
| Active context state is not atomic as a record | `_policy`, `_context`, and `_last_source` are assigned separately despite the GIL claim | construct one frozen revision record and publish it with one reference assignment; readers never assemble state from separate properties |
| The selected rig forbids this relaxation today | committed `robot.go2_edu_plus.yaml` says no person/obstacle band is relaxed before an instrumented stop, while `VENUE_PROXIMITY_CONTEXT` automatically maps that rig to the tighter indoor pair | keep default behavior only; enable a tighter context for that robot solely through an owner-approved commissioning revision after measured stopping/person-sensing uncertainty fits |
| Person-distance usefulness remains unproved | current Go2 observation has no bounded reactive person channel, and software floor validation is not a measured stopping envelope | do not enable a people ODD until person-channel freshness/loss/occlusion plus six-term stop evidence and physical trials are green |

### Required unit, integration, and quality/eval additions

| System | Unit/contract refuters | Integration refuters | Quality/target/physical refuters |
|---|---|---|---|
| Pose datum/latch | wrong sequence types, bool/NaN/Inf receipt, empty/wrong frame, epoch mismatch/reboot, distinct duplicate, same metadata/different pose, reread exemption, receipt regression, malformed first sample | product runtime consumes observation N's pose datum only; live vs replay/injected/absent truth table; disconnected reader mutant | real DDS stop/restart/reset/clock jump and ODOM frame validation; localization loss before any MAP claim |
| Livox ingest/receipt | all-corrupt cap, valid-frame cap, frozen/advancing clock, missing/lying/no `gettimeout`, blocked first recv, expiry callback failure, per-frame receipt before decode | adversarial concurrent control/HTTP reads see one snapshot; sensor quiet/flood/restart cannot block the tick; state and scan fail independently | max-size valid/corrupt mixed stream on Orin with p99/max CPU, age, drops, temperature; official driver/pcap/CRC differential |
| Proximity config/registry | absent-key compatibility across body/envelope scales; strict scalar/table types; completeness/unknown/duplicate names; immutable maps; monotone profile order and unchanged floor owner | resolved product and headless factories load the same table; missing/invalid config refuses predictably; follower/owner bands consume the same policy revision | config/revision/robot identity attestation; no physical-distance claim from a test-owned proposed YAML block |
| Context authority | proposal cannot commit; accept/reject/expiry/default transitions; immutable atomic snapshot under deterministic barriers; audit source/revision/time bounds | model tool enum → deterministic arbiter → tick-boundary policy; rapid/flapping/conflicting proposals; stale context and restart revert widest; no direct distance path | false indoor/narrow classification, crowds/occlusion/person-detector stale/unplug, onboard-avoidance interaction, restrained then leashed low-speed trials with independent distance/stop truth |

The external PROX status honestly says the feature is unreachable from the
product and its required base config did not land. Its “two files/clean tree”
statement is only a card-local historical snapshot and is no longer global
worktree truth. Accordingly, accept PROX-1 only as an unwired library seam;
do not call it dynamic physical person safety. SENSE-1 is unfinished in this
snapshot and cannot close X04/X15/A23/R05/R19/R21/T15 without the product-path
and target refuters above.

One independent bounded check reported Ruff clean on the applicable frozen
Python paths and nine targeted passes: the seven PROX tests plus one existing
Go2 drain and one existing Livox refusal test. It did not reproduce the status
file's wider 197/67 totals, test the new pose seam, establish a hard blocking-
recv deadline, or change the desktop/physical evidence ceiling.
