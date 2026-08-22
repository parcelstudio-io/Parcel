# C-1 evidence preregistration — 2026-08-21

This register was initially written after the product source froze and before
the first C-1 normal-composition live cell or any C-1 source mutation was run.
It received the explicitly dated protocol amendment below after the first live
cell exposed a measurement confound.  The repository is a shared dirty worktree;
every result is therefore attributable only to the named command and exact
source hashes, not to a clean commit.

## Protocol history (do not read the amendment retroactively)

- **18:10–18:17 EDT, original preregistration:** the CPU cell, five-frame/25 s
  limit, latency metrics, 100 ms deadline, +5 ms delta bound, system-wide GPU
  headroom, store hash, teardown, and mutation table were written before the
  first live process started.
- **18:17 EDT, first cell:** `live_cpu_20260821T221731Z`.  It created the HTTP
  server only for ON and generically verified EV-1 without strict-decoding every
  camera payload.  It is retained unchanged as exploratory frame-flow evidence,
  but is non-authoritative for the ON/OFF timing comparison because the arms
  were asymmetric.
- **18:19 EDT, audit amendment:** the symmetric HTTP-server requirement and
  strict `DetectionFrame.from_mapping` requirement were added after the first
  cell and before the replication.  They are audit corrections, **not** original
  preregistration.
- **18:20 EDT, corrected replication:**
  `live_cpu_replication_20260821T222002Z` is the only authoritative live pair.
  It preserved the original numeric thresholds without retuning.

## Frozen source boundary

- `camera_channel/ingress.py`: `5d9f3405...`
- `runtime.py`: `024a3632...`
- `tests/test_c1_camera_ingress.py`: `b9318755...`
- Dedicated pre-live sweep: 86 passed, 3 warnings in 16.97 s.
- Cross pre-live sweep: 192 passed, 3 warnings in 21.71 s.
- Changed-path Ruff and `git diff --check`: pass.
- The named default-suite classifier is expected to stop before its test body on
  the independently owned W-1 `city_scene` frozen SHA mismatch.  C-1 will not
  change that scene or manifest.

The live and mutation manifests must record full SHA-256 values rather than the
abbreviations above.

## Normal-product live cell

The normal project/runtime `.parcel` environment is the primary cell.  It
exposes only `AzureExecutionProvider` and `CPUExecutionProvider`, and its normal
cache has the int8 artifact.  Therefore this is explicitly a **CPU-int8 product
composition** cell, not GPU-path proof or a claim about a released package.

1. Start the real `parcel_robot.sim` in a separate process on a unique Unix
   socket and the exact `city_block.xml` scene.  Run the simulator with its
   normal window backend and the panel/harness process with `MUJOCO_GL=egl`.
2. Build an explicit-OFF runtime, using the non-test
   `web_panel.build_runtime(...)` composition root; bind and serve the same real
   ephemeral `RuntimeHTTPServer` used by ON, GET the same panel/state/latency
   endpoints, start it for at least 8 s, and retain at least 40
   `ControlLoopWork` samples.  Keeping the otherwise-idle HTTP thread symmetric
   avoids confounding the ON/OFF timing comparison.
3. Build the ON runtime through the same composition root and socket.  This must
   construct/start the real `MujocoEglCameraBackend` and normal project OWLv2
   detector.  Bind a real ephemeral `RuntimeHTTPServer`, GET `/api/state`, and
   run a short API-submitted motion request script by refreshing
   `runtime.submit_motion("voice", VelocityCommand(...))`.  Acceptance here is
   only by the runtime submission API; it is not actuator acknowledgement and
   is not called a patrol or navigation mission.
4. Continue until at least five typed successful frames or 25 s, whichever
   occurs first.  Drain only through the runtime's public bounded consumer.
5. Record configured/observed rate, per-frame render/detect/total p50/p95/max,
   raw/localized/empty counts, current producer/backend buffer cardinality,
   runtime queue/evidence drops, errors, process peak RSS, and GPU
   before/peak/after.  GPU headroom must remain at least 6 GiB; no claim of GPU
   detector residency follows from this CPU cell.
6. Record `ControlLoopWork` p50/p95/p99/max for OFF and ON.  Preregistered
   safety-isolation bounds are ON p99 < 100 ms (10 Hz deadline) and
   `ON p99 - OFF p99 <= 5 ms`.  This measures the full runtime loop's work
   interval, not actuator presentation time.
7. Close server/runtime before terminating the exact simulator PID.  Verify the
   v2 session JSONL with `verify_event_log`, decode every persisted perception
   payload through `DetectionFrame.from_mapping`, require at least one valid
   typed `perception/camera_detection_frame` row and zero decode errors, and
   prove owner-store SHA-256 is unchanged.  Keep full `/api/state` and the
   machine-readable summary.

The ON/OFF pair is a sequential, descriptive timing comparison, not a
statistical safety study.  Motion counts mean accepted by the runtime submission
API, not confirmed actuator presentation or a patrol.  `nvidia-smi` readings are
system-wide occupancy/headroom, not process-attributed C-1 VRAM.

Failure, timeout, provider fallback, expired-at-publish frames, low achieved
rate, or threshold miss is recorded as a result; it is not re-tuned after the
fact.

## Optional scratch CUDA compatibility cell

If time permits, a separate process may put
`~/.cache/parcel-pg1/gpuvenv` ahead of the repo `.parcel` site packages and pin
`PARCEL_PERCEPTION_PROVIDER=cuda_fp16` plus the PG-1 scratch fp16 artifact.
It must be labelled **non-shipped scratch compatibility evidence**.  It cannot
close the normal-launch GPU dependency/artifact promotion gate.

## Mutation campaign

Each seed is a real one-change source mutation made only after the live process
has stopped.  Each mutation gets an isolated bytecode cache, must make its named
test RED, is immediately restored byte-for-byte, then the same test must be
GREEN.  The manifest records pre/mutant/restored SHA-256 and output.  No seed may
touch W-1 scenes/manifests, C-2 files, detector internals, or realtime voice
lane/broker/ingress.

| Seed | Mutated invariant | Expected detecting test |
|---|---|---|
| C1-M1 | default producer flag flips ON | `test_c1_config_is_strict_default_off_and_keeps_unrelated_perception_keys` |
| C1-M2 | bounded runtime queue stops counting an evicted frame | `test_runtime_keep_newest_queue_counts_truncation_eviction_and_duplicates` |
| C1-M3 | v1 EV-1 snapshot gains the v2 `schema` field | `test_default_v1_writer_snapshot_keeps_exact_legacy_shape_and_v2_is_additive` |
| C1-M4 | perception evidence is offered to the legacy event stream | `test_real_ev1_v2_persists_and_verifies_a_typed_perception_slice` |
| C1-M5 | camera producer reuses a stale pose after mailbox drain | `test_pose_source_requires_a_new_sample_for_every_capture` |
| C1-M6 | capture sequence correlation check is removed | `test_capture_envelope_mismatch_fails_before_detector_or_evidence` |
| C1-M7 | CLI abbreviation is re-enabled in the panel parser | `test_sim_and_panel_clis_refuse_abbreviated_composition_overrides` |
| C1-M8 | renderer buffer history is retained instead of replaced | `test_mujoco_backend_replaces_ephemeral_buffers_instead_of_leaking_history` |
| C1-M9 | C-1 stream flag is permitted to share legacy B4 authority | `test_c1_refuses_both_legacy_authority_arms` |
| C1-M10 | current-time TTL state uses publish-time expiry only | `test_snapshot_current_expiry_flips_at_the_exact_ttl_boundary` |

At least eight of these ten seeds must complete RED / byte-restore / GREEN.  A
final dedicated and cross sweep must run after the last restore.  Mutation REDs
are deliberately induced evidence and are never counted as repository test
failures.
