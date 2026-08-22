# VENUE-1 — pre-registration

**Card:** `README.md` · **Board:** `../TASK_BOARD.md` · **Exits:**
`../WAVE2_DESIGN_FABLE.md` §1 (DW-1), adopted verbatim.
**Written BEFORE any measurement.** Executor: Claude Opus · 2026-08-22.

Environment for every row: `.parcel/bin/python`, `TMPDIR` unset, scratch under
`/home/jaewoo-jang/.cache/parcel-venue1/`. No hosted spend. The owner's live
stack (`:8765`, `/tmp/parcel_sim.sock`) and `parcel_memory.sqlite3` are never
contacted. **No robot hardware is on hand** (owner, authoritative): every row
below runs on the committed clip `tests/data/p1a_desk_clip.npz`, on in-process
doubles that subclass P1-A's `PhysicalCameraBackendBase`, or on a real
`PerceptionDaemon` over a real AF_UNIX socket with an injected stub detector.
Rows that need a lens are listed in §3 as OWNER-GATED and are never claimed.

"Through the product path" below means: the frames are produced by the object
that `RobotRuntime._attach_configured_camera_ingress()` built and handed to
`RobotRuntime.attach_camera_ingress()`, and every frame counted is one that
arrived at `RobotRuntime._publish_camera_frame`. Where a row drives
`poll_once()` by hand instead of letting the worker thread's clock drive it,
that is stated in the row.

---

## 1. Acceptance rows (met / missed is decided by these numbers)

| # | Row | Threshold |
|---|---|---|
| **R1** | `PARCEL_CAMERA_BACKEND=recorded` reaches `_attach_configured_camera_ingress` and attaches a `CameraIngress` whose `backend` is a `RecordedCameraBackend`. The same for `uvc` and `realsense` through doubles. An unknown value refuses by name. | attach succeeds; `resolve_scene` / `MjModel` never called |
| **R2** | **A physical venue never imports or initializes MuJoCo/EGL.** With a `sys.meta_path` finder that raises on `import mujoco`, the attach completes and frames publish on `recorded` and on a PHYSICAL double. `MUJOCO_GL` is not written. | `"mujoco" not in sys.modules` after attach; `os.environ` unchanged for `MUJOCO_GL` |
| **R3** | **Origin derives from the frame.** 100 consecutive published frames from a PHYSICAL double carry `frame.origin == "physical"`; the recorded venue publishes `"replay"`. | 100/100 published, **0 dropped**, 0 frames stamped `unknown` |
| **R4** | **capture → publish p50 < 300 ms through the runtime with the daemon.** Recorded venue, real `PerceptionDaemon` on a real AF_UNIX socket, `DaemonDetector` selected by the runtime, 100 frames; the statistic is `frame.publish_latency_ns` (capture start → publish) read off frames queued by `_publish_camera_frame`. | p50 < 300 ms **and** p50 + 113.7 ms < 300 ms (113.7 ms = P1-A's slower measured GPU round trip, since this row's daemon runs a stub detector; the GPU cost is additive) |
| **R5** | **A physical-frame / simulation-map mismatch is REFUSED on the exact runtime path.** Off-oracle (`semantic_source: learned_map`), a store holding `simulation`-stamped entries + a PHYSICAL venue ⇒ the attach raises, naming both origins and the store path. Inverse: a store holding `physical` entries + a `replay` (recorded) venue ⇒ raises. Replay/unknown: a `replay` venue + an empty or `unknown` store ⇒ **allowed**. | 2 refusals, 2 admissions, each with the origin pair in the message |
| **R6** | **The map writer's origin is never inferred from "camera streaming enabled".** After a physical attach off-oracle, `runtime._p1b_learned_map.provenance.origin == "physical"` (today: `"simulation"`, guessed from `_camera_stream_enabled`); after a recorded attach, `"replay"`. | exact string match, both venues |
| **R7** | **The daemon runs through the existing bounded `Detector` contract and its degraded states are typed and never block motion.** Five states measured with the ingress attached by the product path: (a) absence, (b) restart, (c) stale/backoff window, (d) undecodable schema, (e) backpressure (a 200 ms detect in flight while a health probe answers). In every state the runtime's control-loop read `_semantic_candidates()` returns without raising. | no state raises; `_semantic_candidates()` p95 **≤ 5.0 ms** in all five states; each state visible as a typed field in `DaemonDetector.snapshot()` (`stale`, `degraded_requests`, `consecutive_failures`, `last_error`) |
| **R8** | **Flag-off is byte-identical.** With no `PARCEL_CAMERA_BACKEND` and no `perception.camera_backend`, the MuJoCo venue behaves exactly as HEAD. | `tests/test_c1_camera_stream.py`, `tests/test_p1b_map_learns.py`, `tests/test_p0d_navigation_unblocks.py`, `tests/test_prototype_profile.py` all green; a flag-off `camera_stream_snapshot()` has the identical key set **and** an identical `composition` sub-dict to HEAD's literal |
| **R9** | **RGB-only is named, never a silent pass.** A UVC (RGB-only) double attaches; the operator surface says depth is unavailable and no depth-dependent gate reports a pass. | 10 polls ⇒ **0** frames published, 10 counted `stats.errors`, `camera_stream_snapshot()["composition"]` carries `depth_available: false` with a reason string; the learned map receives 0 observations |
| **R10** | Targeted gates on OWNS. | `ruff check` clean on every file this card touched; `scripts/ci_ruff_baseline.json` unchanged at exactly **7** fingerprints; the new `tests/test_venue1_*.py` green |

## 2. Seeded RED — one per new guard

Each seed edits the **product** (a scratch copy of `src/` where another card
may be writing the live tree), watches the **named** test fail, restores
byte-identically by `sha256`, purges `__pycache__`, and re-runs green.

| Seed | What is broken | Test that must go RED |
|---|---|---|
| **S1** | the VENUE-1 seam's early `return` is deleted ⇒ the physical path falls through into the MuJoCo preamble | R2's `test_a_physical_venue_never_imports_mujoco` |
| **S2** | `origin=` removed from the kwargs the seam hands `CameraIngress` | R3's `test_a_physical_venue_publishes_frames_that_say_physical` |
| **S3** | the origin-mixing refusal deleted from the reconcile | R5's `test_a_physical_venue_refuses_a_simulation_map` |
| **S4** | the writer re-derivation deleted ⇒ the writer keeps the `_camera_stream_enabled` guess | R6's `test_the_map_writer_origin_comes_from_the_frame` |
| **S5** | the RGB-only declaration deleted from the composition block | R9's `test_an_rgb_only_venue_says_depth_is_unavailable` |

## 3. OWNER-GATED (listed, never claimed)

No camera exists on this host. Presence is read through the **two existing**
checks only — ENV-1's `RealSenseIngestAdapter.device_report()` and
`camera_channel.backends.realsense.connected_devices()`; this card adds no
third probe. The live arms and their exact commands go in §"Owner-gated rows"
of `VENUE1_STATUS.md`.

## 4. What these rows will NOT prove

* Nothing here proves recognition quality on real pixels: the CI detector is a
  stub over a real socket, and the clip is P1-A's synthetic desk clip.
* R4 measures the pipeline and the process boundary, not OWLv2 on a GPU.
* A PHYSICAL double is a contract double. It proves the composition root, the
  provenance and the refusals; it does not prove a D455 streams.
* Nothing here proves the map is *correct*, only that it is honest about which
  world it was built from.
