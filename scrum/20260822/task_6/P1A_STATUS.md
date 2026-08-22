# P1-A — real eyes: a physical camera backend and the GPU detector daemon · STATUS

**Card:** `README.md` · **Board:** `../TASK_BOARD.md` · **Pre-registration:** `PREREGISTRATION.md`
**Executor:** Claude Opus · **Verifier:** Fable · **Date:** 2026-08-22

---

## Headline

Three physical `CameraBackend`s exist (`uvc`, `realsense`, `recorded`), every
frame they produce carries a **declared** `EvidenceOrigin` and a **strictly
increasing** capture stamp, and the GPU detector now runs **in its own process**
behind an AF_UNIX socket with a typed contract and a health probe. The runtime
side is a `DaemonDetector` that satisfies the existing `Detector` protocol
exactly — so **`camera_channel/ingress.py` was not touched at all** (P1-B owns
it): the daemon plugs into the seam that already existed.

**Measured on this host, real GPU, real socket, real recorded frames:**

| | value | note |
|---|---|---|
| daemon provider | `cuda_fp16`, `CUDAExecutionProvider` | P0-C's resolution, honoured |
| client-observed round trip, run 1 | **p50 100.6 ms**, p95 123.9 ms | load avg 4.09, GPU 48 % |
| client-observed round trip, run 2 | **p50 113.7 ms**, p95 160.8 ms | load avg 3.59, GPU 22 %→84 % |
| daemon-side detect only | p50 99.9 / 111.9 ms | matches P0-C's 98 ms and Fable row C-1's 132–139 ms band |
| **process-boundary overhead** | **p50 0.6 ms / 1.8 ms** | the entire cost of the process split |
| vs `DEFAULT_DETECTION_TTL_NS` (300 ms) | **34 % / 38 %** | |
| SigLIP-2 `embed_image` over the socket | 768-d, ‖v‖=1.0, warm **p50 3.4 ms** (cold 2081 ms) | P0-C measured 4.17 ms in-process |
| stub-detector round trip, 640×480×3, 100 samples | p50 **0.75–1.07 ms**, p95 0.91–1.25 ms | pre-registered ≤ 15 / ≤ 40 ms |

**The live rows are NOT RUN and are OWNER-GATED**: this host has no camera
(`ls /dev/video*` → none; `rs.context().query_devices()` → 0 devices, re-checked
after installing `pyrealsense2`). Their exact commands are in §6 and in the
runnable `live_camera_proof.py` beside this file.

**One deliverable is NOT delivered and is a declared HALT:** nothing yet makes
the *runtime* build a physical backend. `--camera` exports the venue and starts
the daemon, and every piece behind it is built and tested, but
`RobotRuntime._attach_configured_camera_ingress` (`runtime.py:10208-10324`)
still constructs the MuJoCo/EGL ingress unconditionally, and `runtime.py` is not
in this card's OWNS. The exact 20-line change is written out in §8 handoff 1.

---

## 1. What changed

New files (nothing pre-existing was rewritten):

| File | lines | what |
|---|---:|---|
| `src/parcel_robot/camera_channel/backends/physical.py` | 714 | shared base: origin guard, monotonic stamp, config→spec, `--camera` resolution — **declared deviation, §7** |
| `src/parcel_robot/camera_channel/backends/uvc.py` | 281 | V4L2/UVC via OpenCV, RGB only, negotiated-raster rescale |
| `src/parcel_robot/camera_channel/backends/realsense.py` | 384 | D455 RGB + color-aligned depth, device calibration |
| `src/parcel_robot/camera_channel/backends/recorded.py` | 426 | clip format, replay backend, `record_clip` |
| `src/parcel_robot/perception_daemon/protocol.py` | 413 | framing, typed ops, the 16-phrase ceiling |
| `src/parcel_robot/perception_daemon/server.py` | 548 | the daemon |
| `src/parcel_robot/perception_daemon/client.py` | 482 | `DaemonClient`, `DaemonDetector`, `DaemonEmbedder` |
| `src/parcel_robot/perception_daemon/__init__.py` | 57 | public surface |
| `src/parcel_robot/perception_daemon/__main__.py` | 128 | `--probe` / `--shutdown` / serve |
| `scripts/launch_detector_daemon.sh` | 123 | start / reuse / probe / stop |
| `tests/test_p1a_camera_backends.py` | 632 | 58 cells |
| `tests/test_p1a_perception_daemon.py` | 532 | 30 cells |
| `tests/data/p1a_desk_clip.npz` | 20 224 B | the CI clip, sha256 `ee4a86a8a587d1c5…` |
| `scrum/20260822/task_6/{PREREGISTRATION.md,live_camera_proof.py,P1A_STATUS.md}` | — | this register |

Edited existing files — `git diff --numstat`, both are my regions only:

```
$ git diff --numstat -- pyproject.toml scripts/launch_stack.sh
31      0       pyproject.toml
80      0       scripts/launch_stack.sh
```

* `pyproject.toml` — **insertions only**, one contiguous block between the
  `perception` extra (P0-C's) and `voice`: the new `camera` and
  `camera-realsense` optional extras. P0-C's and P0-E's blocks are
  byte-unchanged.
* `scripts/launch_stack.sh` — **insertions only**, five hunks, all in the P0-A
  region and all inert when `--camera` is absent: two usage blocks, the
  `CAMERA=` variable next to `PROFILE=`, the two `--camera` arg cases, the
  validation/export block after the profile resolution (plus three `--dry-run`
  lines), and the daemon start before `launch_sim.sh`.

Nothing else was written. No `git add/commit/stash/checkout/reset/restore` was
run. `camera_channel/ingress.py`, `online_map/`, `perception_abstention.py`,
`runtime.py`, `configs/**`, `scripts/ci_gate.py`, `docs/`, `backlog/`,
`README.md`, `scrum/20260821/` — all untouched.

### Venv delta (owner's standing download grant)

```
$ .parcel/bin/pip install 'opencv-python-headless>=4.10,<6' 'pyrealsense2>=2.55,<3'
+ opencv-python-headless==5.0.0.93
+ pyrealsense2==2.58.3.10794
$ .parcel/bin/pip check
No broken requirements found.
```

That is the whole diff of `pip freeze` before → after. Both import cleanly.

---

## 2. The design, in three decisions

**1. Provenance is declared at the buffer, and a replay can never mint
`PHYSICAL`.** `PhysicalCaptureBuffers` refuses to exist without an
`EvidenceOrigin` **member** (a bare `"physical"` string is refused — the enum is
a `str` subclass, so this distinction had to be made explicitly), refuses
`UNKNOWN`, and `PhysicalCameraBackendBase.__init__` refuses a subclass that
declared no origin *at construction*, in the launcher, not fifty frames into a
mission. The recorded backend is `REPLAY` unconditionally; its manifest carries
`captured_origin` for history, and `RecordedCameraBackend(clip, origin=…)` is a
`TypeError`. A clip recorded from a real webcam therefore reports
`captured_origin=physical` **and replays as `REPLAY`** — pinned by
`test_a_clip_recorded_from_a_camera_still_replays_as_replay`.

**2. The capture stamp is enforced in the base, not per backend.**
`CameraDetectionFrame.expired_at_publish` computes age from capture *start*, so
a stamp that can repeat or regress makes a stale frame look fresh. Two frames
may never share a monotonic instant; a regressing clock is a `ValueError`. A
*failed* read does not consume the stamp, so a dropped frame cannot make the
next good frame look non-monotonic.

**3. A webcam cannot claim the simulator's calibration.** With no config,
intrinsics are a pinhole guess from a stated horizontal FOV, stamped
`uvc-uncalibrated-hfov60` — `assert_nominal_d455_contract` still refuses it. A
config that tries to write `d455-intrinsics-nominal` is refused by name. A
RealSense adopts its **device's** factory calibration as `d455-device-<serial>`.
When a V4L2 device negotiates a different raster than it was asked for, the
intrinsics are rescaled and the id gains `-scaled` rather than every frame being
dropped against a size nothing produces.

**The daemon.** `[4-byte header length][JSON header][raw payload]` — base64 in
JSON would cost a copy and 33 % inflation on every 2.7 MB frame. Header names
every payload part (dtype, shape, nbytes) from a closed dtype set; a declared
size that disagrees with its shape is a refusal. Models load lazily behind one
lock; inference is serialized (one GPU) while connections stay concurrent, so a
health probe never queues behind a detect (**measured**: probe returned in
< 200 ms while a 400 ms detect was in flight). Socket is mode 0600 and refuses
to replace a path that is not already a socket.

**The 16-phrase ceiling is enforced at the daemon boundary** (Fable's wave row
D-R2): `CameraDetectionFrame` refuses more than 16 query phrases, and crossing
that downstream makes every poll raise while only `stats.errors` moves — silent
blindness. `normalize_query` refuses a 17-phrase batch with the count and the
reason in the message, and `DaemonDetector.detect` **raises** it rather than
degrading, because it is the caller's bug, not the daemon being away.

---

## 3. How verified — exact commands, exact results

### 3.1 The card's gates

```
$ .parcel/bin/python -m pytest -q --no-header \
      tests/test_p1a_camera_backends.py tests/test_p1a_perception_daemon.py
[P1-A C5] round-trip overhead 640x480x3: p50=0.75 ms p95=1.12 ms
88 passed in 3.73s

$ .parcel/bin/ruff check src/parcel_robot/camera_channel/backends/{physical,uvc,realsense,recorded}.py \
      src/parcel_robot/perception_daemon/ tests/test_p1a_*.py \
      scrum/20260822/task_6/live_camera_proof.py
All checks passed!

$ bash -n scripts/launch_detector_daemon.sh scripts/launch_stack.sh   # both clean
```

`scripts/ci_gate.py` was **not** run (board rule 4). The two pre-existing ruff
fingerprints in `camera_channel/backends/factory.py` (`ISC004`, `S110`) are in
`scripts/ci_ruff_baseline.json` and were not touched; my files add **zero** new
fingerprints.

### 3.2 Suites that read the surfaces I edited

```
$ .parcel/bin/python -m pytest -q --no-header tests/test_prototype_profile.py \
      tests/test_prod_default_path.py tests/test_owner_store_isolation.py \
      tests/test_backends.py tests/test_c1_camera_stream.py \
      tests/test_k5_camera_detection_gates.py tests/test_realtime_ingress.py \
      tests/test_perception_providers_p0c.py tests/test_release_parity.py \
      tests/test_release_parity_wheel.py tests/test_scene_assets.py
1 failed, 449 passed, 4 skipped
FAILED tests/test_prototype_profile.py::test_realtime_prototype_example_validates_and_carries_its_departures
```

**That failure is not mine and I did not touch it.** It is P0-A's test against
`configs/realtime*.yaml.example`, and it reddened because another card in flight
(P2-B, `task_11`) added `whisperer.owner_events.enabled` and
`whisperer.owner_events.greeting_interval_s` to `configs/realtime.yaml.example`
without the prototype example following. Neither file is in my OWNS; reported
here and handed off (§8, handoff 4) rather than "quickly fixed".

### 3.3 The launcher, exercised

```
$ ./scripts/launch_stack.sh --dry-run                       # unchanged rows + 3 new
camera=-   camera_config=-   perception_socket=-
$ ./scripts/launch_stack.sh --prototype --camera uvc --dry-run
Camera venue: uvc (PARCEL_CAMERA_BACKEND=uvc)
camera=uvc
$ ./scripts/launch_stack.sh --camera webcam --dry-run
launch_stack: invalid --camera value: webcam (expected uvc, realsense or recorded)   # exit 1

$ ./scripts/launch_detector_daemon.sh --background --socket ~/.cache/parcel-p1a/p1a_launcher.sock
perception daemon ready (pid …)  {"reachable": true, "protocol_version": 1, …}
$ ./scripts/launch_detector_daemon.sh --background --socket …          # again
Reusing the healthy perception daemon already on …                      # never restarts
$ ./scripts/launch_detector_daemon.sh --stop --socket …
perception daemon stopping                                              # socket file removed
```

Only sockets under `/home/jaewoo-jang/.cache/parcel-p1a/` were bound. **No port
was opened, `/tmp/parcel_sim.sock` and `:8765` were never touched, and no
process I did not start was signalled.** Every daemon this card started was
stopped; `pgrep -f parcel_robot.perception_daemon` is empty as of this write-up.

### 3.4 Seeded RED — one per new guard, restored byte-identically

Harness: seed the product file, purge every `__pycache__`, run, restore from the
original bytes, re-verify the sha256, purge again, re-run.

**R1 — origin stamp missing** (`physical.py`, both origin guards → `pass`).
sha256 `64d91d525c8a…` before and after:

```
FAILED tests/test_p1a_camera_backends.py::test_capture_buffers_refuse_a_string_that_merely_spells_an_origin
FAILED tests/test_p1a_camera_backends.py::test_capture_buffers_refuse_the_fail_closed_unknown_origin
FAILED tests/test_p1a_camera_backends.py::test_a_backend_that_declares_no_origin_cannot_be_constructed
3 failed, 55 passed in 0.24s
```

**R2 — capture stamp not monotonic** (`physical.py`, the strictly-increasing
check → `pass`). Same file, sha256 `64d91d525c8a…` before and after:

```
FAILED tests/test_p1a_camera_backends.py::test_a_repeated_capture_stamp_is_refused_not_warned
FAILED tests/test_p1a_camera_backends.py::test_a_regressing_clock_is_refused
2 failed, 56 passed in 0.24s
```

**R3 — daemon unreachable must degrade, not crash** (`client.py`, the
degrade arm re-raises). sha256 `2a93743fb927…` before and after:

```
FAILED tests/test_p1a_perception_daemon.py::test_an_unreachable_daemon_returns_nothing_and_says_it_is_stale
FAILED tests/test_p1a_perception_daemon.py::test_the_ingress_survives_an_unreachable_daemon
FAILED tests/test_p1a_perception_daemon.py::test_a_dead_daemon_is_not_reconnected_to_on_every_single_frame
FAILED tests/test_p1a_perception_daemon.py::test_the_same_client_survives_a_daemon_restart
4 failed, 26 passed in 3.55s
```

R3's RED output contains the exact failure mode the degrade exists to prevent:

```
WARNING parcel_robot.camera_channel.ingress: camera ingress poll failed:
        cannot reach the perception daemon at …/absent.sock
```

— i.e. `poll_once` returns `None`, **no frame is published**, the last good
candidate buffer stays in place, and only `stats.errors` moves. That is the
robot navigating on stale candidates with nothing above it able to tell.

**GREEN after restore:** `88 passed in 3.78s`. Full outputs:
`/home/jaewoo-jang/.cache/parcel-p1a/RED_R{1,2,3}-*.txt`,
`GREEN_after_restore.txt`.

---

## 4. Pre-registered rows: met / missed

Registered in `PREREGISTRATION.md` **before** the first line of the backends or
the daemon was written.

| # | Row | Bound | Result |
|---|---|---|---|
| C1 | clip replays end to end | N frames, 0 drops, every envelope validates | **MET** — 100 captures over an 8-frame looping clip, 0 drops |
| C2 | replay provenance | 100 % `REPLAY` | **MET** — 100/100 |
| C3 | physical provenance | 100 % `PHYSICAL` on both live backends | **MET** — 100/100 each (injected device doubles) |
| C4 | stamps monotonic | strictly increasing over ≥ 100 captures, all three | **MET** — `len(set(stamps)) == 100` on all three |
| C5 | daemon round-trip overhead | p50 ≤ 15 ms, p95 ≤ 40 ms @ 640×480×3 | **MET** — p50 **0.75–1.07 ms**, p95 0.91–1.25 ms |
| C6 | unreachable degrades | `[]` + `stale`, no raise, `poll_once` completes | **MET**, seeded RED |
| C7 | daemon restart survives | same client answers again, 0 client restarts | **MET** |
| C8 | gates | targeted pytest green, ruff clean on OWNS | **MET** — 88 passed, ruff clean |
| R1–R3 | the three seeded-RED guards | seed → fail → restore byte-identical | **MET**, §3.4 |
| L1–L3 | the live rows | see §6 | **NOT RUN — owner-gated on hardware** |

Nothing was moved after measuring. C5's bound was set generously and beat by
~15×, which is worth saying plainly rather than presenting as a triumph: the
pre-registered number was a guess at an unfamiliar quantity, and the honest
reading is that an AF_UNIX round trip for 900 KB is cheap, not that the design
is 15× better than needed.

---

## 5. What this does NOT prove

* **No pixels from a real camera have ever entered this code.** Every
  `PHYSICAL`-origin frame in these tests came from an injected device double.
  The `cv2.VideoCapture` and `pyrealsense2` call sequences in `_open`/`read` are
  written from the documented APIs and are `# pragma: no cover`. **The first
  real webcam frame may well need a fix**, and the most likely place is the
  UVC property negotiation or the D455 profile read.
* **Recognition on real optics is untouched.** The recorded fixture is
  synthetic; the real GPU run over it returned **0 detections for
  `person/chair/table`**, which is exactly the audit's §1 finding (0/69 in sim)
  reproduced one more time, not a regression. This card moves the venue; it
  does not make the venue see.
* **The runtime does not use any of this yet** — §8 handoff 1. The `--camera`
  flag exports the venue and starts the daemon; nothing downstream reads the
  venue back.
* **UVC has no depth, so it cannot localize.** `localize_detection` needs metric
  depth; a webcam frame reaches the detector and the boxes come back, and then
  the ingress counts a poll error rather than inventing a range. That is the
  intended failure and it is stated in `uvc.py`'s docstring — but it means the
  cheap venue proves *detection*, not *mapping*. The D455 is the venue that maps.
* **The latency numbers are load-conditional**, exactly as Fable's row C-1 says.
  Two runs 20 minutes apart on the same host gave p50 100.6 ms and 113.7 ms with
  the GPU at 48 % and 22 % baseline and six other cards executing. Re-measure on
  the desk with `live_camera_proof.py`, which prints the load beside the number.
* **The 100-frame origin/monotonic runs are in-process and fast** (0.24 s), so
  they do not exercise thermal behaviour, USB bandwidth contention, or a
  multi-hour stream.
* **No concurrency test drives the daemon from more than two clients**; the
  connection ceiling refuses politely but has not been measured under a real
  fan-out.

---

## 6. Owner-gated rows — the exact commands

Nothing below has been run. Plug in a USB webcam (day one) or the D455 (adds
depth), then:

```bash
cd /home/jaewoo-jang/Desktop/Projects/Parcel

# 0. confirm the host actually sees it (today both are empty)
ls /dev/video*
.parcel/bin/python -c "from parcel_robot.camera_channel.backends.realsense import connected_devices; print(connected_devices())"

# 1. the detector daemon, warm, on its own socket
scripts/launch_detector_daemon.sh --background --preload \
    --socket /run/user/$(id -u)/parcel_perception.sock

# 2. rows L1 + L2 — 100 frames, latency and origin
.parcel/bin/python scrum/20260822/task_6/live_camera_proof.py \
    --camera uvc --device 0 --frames 100 \
    --socket /run/user/$(id -u)/parcel_perception.sock

# 3. row L3 — restart the daemon mid-stream, no restart of the capture loop
.parcel/bin/python scrum/20260822/task_6/live_camera_proof.py \
    --camera uvc --frames 100 --restart-at 50 \
    --socket /run/user/$(id -u)/parcel_perception.sock

# 4. (D455) the same with real aligned depth
.parcel/bin/python scrum/20260822/task_6/live_camera_proof.py \
    --camera realsense --frames 100 \
    --socket /run/user/$(id -u)/parcel_perception.sock

# 5. turn one desk session into a real CI fixture, replacing the synthetic clip
.parcel/bin/python scrum/20260822/task_6/live_camera_proof.py \
    --camera realsense --frames 60 --record tests/data/p1a_desk_clip.npz \
    --socket /run/user/$(id -u)/parcel_perception.sock
.parcel/bin/python -m pytest -q tests/test_p1a_camera_backends.py   # must stay green

# 6. stop it
scripts/launch_detector_daemon.sh --stop --socket /run/user/$(id -u)/parcel_perception.sock
```

Pre-registered bounds, restated so they cannot drift: **L1** capture→publish
p50 < 300 ms; **L2** 100/100 `PHYSICAL`, 0 drops; **L3** the loop continues
across a daemon restart with 0 restarts of the consuming process. The script
prints `MET`/`MISS` against each.

Step 5 is worth doing *before* trusting any perception number in this repo: the
committed clip is synthetic and says so, and a real desk clip is the smallest
thing that makes the CI contract test run on pixels that mean something.

---

## 7. Deviations from OWNS and from the card, each with its reason

1. **`camera_channel/backends/physical.py` is a fourth new file.** OWNS names
   `{uvc,realsense,recorded}.py`. All three need the identical origin guard,
   stamp guard and config→spec construction, and copying the origin guard into
   three files is how one of the three quietly loses it. It sits inside the same
   package, is imported only by those three modules and the P1-A daemon, and
   touches nothing else. 714 lines.
2. **There is no Python-3.11 RealSense sidecar.** The card specified one. Measured
   2026-08-22: `pyrealsense2` ships
   `2.58.3.10794-cp314-cp314-manylinux1_x86_64`, it installs into `.parcel`
   (CPython 3.14.4) and `import pyrealsense2` works. A sidecar would buy nothing
   and cost a process boundary plus a serialization of every depth frame, for an
   ABI problem that no longer exists. The seam is preserved:
   `RealSenseCameraBackend(session_factory=…)` takes any object with
   `start()/read()/stop()`, which is exactly what an out-of-process session would
   implement. Recorded in `realsense.py`'s docstring and in `pyproject.toml`.
3. **Two camera extras, not one.** The card says "`opencv-python-headless`,
   `pyrealsense2` as an optional extra". `camera` and `camera-realsense` split
   them so a laptop with a webcam does not carry librealsense — and, more
   importantly, so the **recorded** backend CI actually runs needs neither, and
   the contract tests cannot be silently skipped for a missing optional wheel.
4. **`scrum/20260822/task_6/live_camera_proof.py` is a script in a docs folder.**
   OWNS says "`task_6/` docs". A runnable script is far more likely to actually
   be run by the owner than a block of shell in a markdown file, and the rows
   were pre-registered before they could be run.
5. **`ingress.py` was not touched at all**, including the "adapter import seam"
   the card allows. It was not needed: `CameraIngress.detector` is already
   `Any`, so `DaemonDetector` drops in. Less is better here — P1-B owns the file.
6. **The daemon opts its own process into `PARCEL_SIGLIP2_ONNX`.**
   `load_onnx_embedder` has no `require_env=False` (the detector's loader does),
   so with the switch unset it returns `None` and the daemon serves no
   embeddings even with weights on disk — reproduced during verification.
   `_load_gpu_embedder` now does `os.environ.setdefault(ONNX_ENABLE_ENV, "1")`:
   an operator who typed `launch_detector_daemon.sh` has already made that
   choice explicitly, the daemon is a dedicated process so the write cannot
   leak, and an explicit `PARCEL_SIGLIP2_ONNX=0` still wins. The alternative was
   adding a parameter to `instructnav/siglip2_onnx.py`, which is P0-C's file.

Two behaviours were **changed during verification** because testing found them
wrong, and both are improvements rather than deviations, but they are worth
naming:

* **`stop()` now shuts down established client connections.** Closing only the
  listening socket left already-connected peers being served indefinitely — an
  operator who ran `--stop` would still have had a GPU answering detects.
  Found by `test_the_same_client_survives_a_daemon_restart`.
* **`--preload` is best-effort per model.** A host with OWLv2 weights but no
  SigLIP-2 used to fail to start at all. Detect and embed are independent
  capabilities; a preload failure is now logged and recorded in `health()`
  (`detector_error` / `embedder_error`), while the lazy path still raises to the
  client that actually asked for the missing model.

---

## 8. Handoffs

1. **HALT: nothing wires the venue into the runtime.** `runtime.py:10208`
   `_attach_configured_camera_ingress` resolves a MuJoCo scene
   (`:10274`) and calls `CameraIngress.from_model_data` (`:10292`)
   unconditionally. `runtime.py` is not in P1-A's OWNS and P1-B owns the camera
   region. The change, in that one method, before the `resolve_scene` call:

   ```python
   from parcel_robot.camera_channel.backends.physical import (
       camera_ingress_kwargs, open_physical_backend, resolve_backend_kind,
   )
   kind = resolve_backend_kind()          # PARCEL_CAMERA_BACKEND, set by --camera
   if kind is not None:
       backend, _ = open_physical_backend(kind)
       from parcel_robot.perception_daemon import DaemonDetector
       ingress = CameraIngress(
           # camera_ingress_kwargs supplies backend, intrinsics, mount, the
           # depth band AND origin=backend.origin.value. Do not hand-roll these:
           # see the hazard below.
           **camera_ingress_kwargs(backend),
           detector=DaemonDetector(os.environ.get("PARCEL_PERCEPTION_SOCKET") or None),
           min_poll_interval_s=1.0 / config.rate_hz,
       )
       # …then the SAME six lines the MuJoCo path already runs (on_frame,
       # contention_guard, pose_source, max_detections_per_frame, set_query,
       # attach) — and skip the MUJOCO_GL / resolve_scene block entirely.
   ```

   **HAZARD — this is the defect Fable caught in the first version of this
   snippet, and it is silent.** `CameraIngress` carries its own `origin` field,
   defaulting to `"unknown"` (`ingress.py:1067`), and the published
   `CameraDetectionFrame` is stamped from `self.origin` (`ingress.py:1659`) —
   **the ingress never reads `PhysicalCaptureBuffers.origin`.** An ingress built
   over a real webcam without `origin=` therefore publishes every frame as
   `unknown` while the buffers behind it correctly say `physical`: honest
   buffers, and every derived record downstream dishonest. The default is
   deliberate in P1-B's file (a renderer that could mint `physical` by default
   is the W0-A defect), so the fix belongs at the composition root — hence
   `camera_ingress_kwargs`, which derives the declaration from the backend
   producing the pixels. P1-B's MuJoCo path does the same thing by hand
   (`origin=EvidenceOrigin.SIMULATION.value` via
   `CameraIngress.from_model_data(origin="simulation")`); this matches it.

   Pinned three ways in `tests/test_p1a_perception_daemon.py`:
   `test_a_physical_backend_publishes_frames_that_say_physical` (the guard,
   seeded RED as R4), `test_an_ingress_built_without_a_declared_origin_must_not_publish_unknown`
   (a **strict xfail** — the hazard asserted as what must become true, so
   VENUE-1 inherits a red it must turn green) and
   `test_the_hazard_is_real_today_and_this_is_what_it_looks_like` (the same
   construction asserted as it behaves now, so the pin cannot rot).

   Note the MuJoCo/EGL preamble at `:10238-10250` must be skipped on this path:
   a physical camera needs no GL binding, and refusing to start because
   `MUJOCO_GL` is wrong would be a nonsense refusal for a USB webcam.
2. **P1-B: the daemon also serves SigLIP-2.** `DaemonEmbedder(socket).embed_image`
   is a drop-in for `CameraIngress.embed_fn` and measures **3.4 ms warm** over
   the socket (768-d, L2-normalised) versus P0-C's 4.17 ms in-process. Using it
   avoids a second copy of SigLIP-2 next to the detector on one GPU. Unlike
   `DaemonDetector` it **raises** when the daemon is away rather than degrading:
   an embedding that silently came back as zeros would poison a persistent map.
3. **~~P1-B, blocking my live rows~~ — OVERTAKEN, see §11.** Fable's row D-R2 — `_with_pinned` can push
   the union past 16 phrases and make every poll fail silently. The daemon now
   refuses a 17-phrase batch loudly at the boundary, so the failure becomes
   visible rather than invisible, but the ingress-side cap is still P1-B's to
   land before any camera run.
4. **~~P0-A / P2-B~~ — RESOLVED, see §11.** `tests/test_prototype_profile.py::test_realtime_prototype_example_validates_and_carries_its_departures`
   is RED in the shared tree because `configs/realtime.yaml.example` grew
   `whisperer.owner_events.{enabled,greeting_interval_s}` without
   `configs/realtime.prototype.yaml.example` following. Neither file is mine.
5. **The committed clip is synthetic and should be replaced.** §6 step 5 turns a
   real desk session into `tests/data/p1a_desk_clip.npz` with one command; the
   contract tests are written to stay green across that swap (they assert the
   manifest agrees with the pixels, not specific pixel values — the one
   exception, `test_the_committed_clip_loads_and_agrees_with_its_own_pixels`,
   pins `clip_id` and the `SYNTHETIC` note and will need those two lines updated).
6. **`camera_channel/backends/__init__.py` does not export the new backends.**
   It is not in my OWNS and re-exporting would have meant editing a file the
   sim-backend factory owns. Import paths are
   `parcel_robot.camera_channel.backends.{uvc,realsense,recorded,physical}`.
   Whoever owns that `__init__` next may want to add them.

---

## 9. Scratch and cleanup

Scratch: `/home/jaewoo-jang/.cache/parcel-p1a/` (RED/GREEN transcripts, the seed
harness, the clip generator, the live-GPU measurement scripts, pip freezes).
Nothing was written to `/tmp`. Every daemon started by this card was stopped;
its sockets are removed. The MOVE-1 patrol sim, `:8765` and `/tmp/parcel_sim.sock`
were never contacted. The owner's `parcel_memory.sqlite3` was never opened.

---

## 10. Appendix — how the committed clip was generated

`tests/data/p1a_desk_clip.npz` (sha256 `ee4a86a8a587d1c58885757c31062c5718e9a4e3191e643af1e0590a3f3b4021`,
20 224 bytes) is reproducible from this, so a verifier never has to take the
fixture on trust. It is **synthetic** and says so in its own manifest; §6 step 5
replaces it with real desk pixels.

```python
import numpy as np
from parcel_robot.evidence_origin import EvidenceOrigin
from parcel_robot.camera_channel.backends.recorded import write_clip

W, H, N = 128, 96, 8
yy, xx = np.mgrid[0:H, 0:W]
colors = np.zeros((N, H, W, 3), dtype=np.uint8)
depths = np.zeros((N, H, W), dtype=np.float32)
for i in range(N):
    frame = np.zeros((H, W, 3), dtype=np.uint8)
    frame[..., 0] = (60 + yy * 0.6).astype(np.uint8)
    frame[..., 1] = (70 + yy * 0.5).astype(np.uint8)
    frame[..., 2] = (110 + xx * 0.2).astype(np.uint8)
    floor = yy > int(H * 0.72)
    frame[floor] = np.array([120, 105, 90], dtype=np.uint8)
    depth = np.full((H, W), 3.2, dtype=np.float32)
    depth[floor] = 1.4 + (H - yy[floor]) * 0.02
    cx = int(18 + i * (W - 44) / max(1, N - 1))          # a column that walks
    x0, x1, y0, y1 = cx, cx + 16, int(H * 0.30), int(H * 0.80)
    frame[y0:y1, x0:x1] = np.array([210, 180, 160], dtype=np.uint8)
    frame[y0:y0 + 8, x0 + 4:x1 - 4] = np.array([235, 205, 185], dtype=np.uint8)
    depth[y0:y1, x0:x1] = 1.85
    colors[i], depths[i] = frame, depth

write_clip(
    "tests/data/p1a_desk_clip.npz", colors,
    clip_id="p1a-desk-synth-v1",
    captured_origin=EvidenceOrigin.SIMULATION,
    captured_label="synthesized (no camera was attached); generator in P1A_STATUS.md",
    depths=depths, fps=15,
    notes=(
        "Card P1-A CI fixture. SYNTHETIC pixels, generated on 2026-08-22 on a host "
        "with no /dev/video* and no RealSense on the bus. It exercises the physical "
        "backend CONTRACT (stamps, origin, envelope validation, daemon round-trip); "
        "it proves nothing about recognition on real optics. Replace it with a real "
        "desk clip via camera_channel.backends.recorded.record_clip once a camera is "
        "attached — the manifest's captured_origin will then read 'physical' while "
        "the replay origin stays REPLAY."
    ),
    intrinsics={"fx": 110.85, "fy": 110.85, "cx": 64.0, "cy": 48.0,
                "calibration_id": "p1a-fixture-synthetic"},
    mount={"height_m": 0.35, "forward_m": 0.18, "pitch_up_deg": 12.0},
    depth_band={"min_m": 0.4, "max_m": 6.0},
)
```

The real GPU detector run over these frames returned **0 detections** for
`person/chair/table` — the audit's §1 finding, one more time. That is the reason
the card exists, not a defect in it.

---

## 11. Post-verification corrections

Fable's P1-A verdict was **CLAIMS_HOLD** — the daemon contract, the 16-phrase
refusal (reproduced server-side with a bypassed client), the live numbers
(99–103 ms p50, boundary 0.5–2.4 ms, embed 3.2 ms / 768-d / unit norm,
`cuda_fp16` honoured), the fixture's byte-identical regeneration, the three
seeds and the hygiene all reproduced independently — with **one substantive
defect**. It is fixed here, plus two doc corrections and two handoff updates.

### 11.1 The defect: a published frame that says `unknown`

**What was wrong.** §8 handoff 1's snippet constructed `CameraIngress(...)`
without `origin=`. `CameraIngress.origin` defaults to `"unknown"`
(`ingress.py:1067`) and the published `CameraDetectionFrame` is stamped from
`self.origin` (`ingress.py:1659`); **the ingress never reads
`PhysicalCaptureBuffers.origin`.** Applied verbatim, real camera frames would
have published as `unknown` — buffers honest, every derived record downstream
not — defeating the one property this card exists to deliver. My two
ingress-level cells asserted the *buffers'* origin and never the *published
frame's*, so nothing caught it. That is the more important half of the finding:
the test looked like coverage and was checking the wrong object.

**What changed.**

* **`camera_ingress_kwargs(backend)`** — new, in
  `camera_channel/backends/physical.py` (my OWNS, +41 lines). Returns the
  `CameraIngress` kwargs a physical backend implies — `backend`, `intrinsics`,
  `mount`, the depth band **and `origin=backend.origin.value`**. The fix is not
  "remember the keyword"; it is to derive the declaration from the backend
  producing the pixels so a composition root cannot forget it. It refuses a
  non-physical backend by type, and it deliberately does **not** apply
  `from_model_data`'s 1 cm `depth_max_m` trim: that trim is a MuJoCo
  background-clip workaround, and a D455 reports 0 for invalid depth rather than
  clipping to the band edge, so trimming would discard real far returns.
* **§8 handoff 1's snippet now uses it**, and the hazard is spelled out in the
  handoff with both `ingress.py` line numbers, the reason P1-B's `"unknown"`
  default is correct in *its* file, and the note that P1-B's MuJoCo path makes
  the same declaration by hand (`from_model_data(origin="simulation")`).
* **The two cells now assert the published frame.**
  `test_the_ingress_survives_an_unreachable_daemon` and
  `test_a_recorded_clip_reaches_the_daemon_and_comes_back_localized` build
  through `camera_ingress_kwargs` and assert `frame.origin == "replay"`
  alongside the buffers' origin — an honest *empty* frame still has to say where
  it came from.
* **Four new cells**, three of them the hazard pin Fable asked for:

  | cell | what it does |
  |---|---|
  | `test_a_physical_backend_publishes_frames_that_say_physical` | the guard: a PHYSICAL venue through the helper publishes `origin == "physical"` on every frame — **seeded RED as R4** |
  | `test_an_ingress_built_without_a_declared_origin_must_not_publish_unknown` | **strict `xfail`** — asserts what must become TRUE. The ingress cannot refuse this today (`ingress.py` is P1-B's and the default is deliberate), so this is the red **VENUE-1 inherits and must turn green** |
  | `test_the_hazard_is_real_today_and_this_is_what_it_looks_like` | the same construction asserted as it BEHAVES now, so the pin cannot rot: if P1-B changes the default, this goes red and both are revisited together |
  | `test_camera_ingress_kwargs_*` (2) | the helper carries `origin`, keeps the untrimmed depth band, and refuses a backend it cannot vouch for |

  The xfail is red for the right reason, verified with `--runxfail`:

  ```
  assert published[0].origin != "unknown"
  E  AssertionError: physical pixels published as 'unknown' — the buffers are
     honest and every derived record is not
  E  assert 'unknown' != 'unknown'
  ```

**Seeded RED R4** — `"origin": backend.origin.value` deleted from the helper.
`physical.py` sha256 `439056c7a113…` before and after, restored byte-identically,
`__pycache__` purged either side:

```
FAILED tests/test_p1a_perception_daemon.py::test_the_ingress_survives_an_unreachable_daemon
FAILED tests/test_p1a_perception_daemon.py::test_a_recorded_clip_reaches_the_daemon_and_comes_back_localized
FAILED tests/test_p1a_perception_daemon.py::test_a_physical_backend_publishes_frames_that_say_physical
FAILED tests/test_p1a_perception_daemon.py::test_camera_ingress_kwargs_carries_the_declaration_the_ingress_cannot_infer
4 failed, 89 passed, 1 xfailed in 4.67s
```

GREEN after restore: `93 passed, 1 xfailed in 4.61s`. Transcript:
`~/.cache/parcel-p1a/RED_R4-ingress-origin-declaration.txt`.

### 11.2 A second thing the fix surfaced: RGB-only cannot feed the ingress

Writing the PHYSICAL cell against a UVC double failed with *"camera backend
produced no RGB/depth buffers"*. §5 predicted this from reading the code; it is
now measured at the seam and pinned by
`test_an_rgb_only_venue_cannot_feed_the_ingress_and_says_so`: a webcam reaches
the **detector** fine, but `CameraIngress` needs metric depth to place a box, so
a depth-less capture is a counted poll error and **no frame is published**
(`stats.errors == 1`, `published == []`). That is the intended failure — a
constant assumed-depth plane would produce world coordinates that look like
measurements and are not — but it sharpens §5: **on day one a USB webcam proves
the detector and the daemon end to end, and proves nothing about the map.** The
PHYSICAL-origin cells therefore run against the RealSense double, which carries
aligned depth.

### 11.3 Doc accuracy: what `--preload` actually warms

Measured on this host after the correction, with a warm text session:

```
--preload start: 2.08 s
after preload: detector_loaded=True embedder_loaded=True
  text session built: True | vision session built: False
first embed_image AFTER --preload: 418.5 ms | warm p50 3.3 ms
first embed_text  AFTER --preload:  22.5 ms
```

`--preload` warms the **OWLv2 session and the SigLIP-2 TEXT session only**.
`_OnnxSigLIP2Embedder` resolves text and vision independently and builds vision
lazily in `_ensure_vision` on the first `embed_image`, so that call still pays a
cold session: **418.5 ms here, 188 ms in Fable's run** — it moves with load like
every other number on this box. `health()["embedder_loaded"]` is true about the
embedder *object*, not about the vision session behind it, and now says so.
Corrected in `perception_daemon/__main__.py`'s docstring **and** its `--preload`
help text, in `server.py`'s preload comment, and in
`scripts/launch_detector_daemon.sh --help`.

**Not changed, deliberately:** `--preload` does not warm the vision session.
One throwaway `embed_image` after start would fix the 418 ms stall, but that is
a behaviour change after verification and it adds a failure mode (a warm-up call
raising on a host whose vision weights are missing). Offered as handoff 8 below
instead.

### 11.4 Handoff updates

* **Handoff 3 is OVERTAKEN.** P1-B landed `ingress.MAX_QUERY_PHRASES = 16` with
  the cap applied in `_with_pinned` before a frame is built, plus
  `IngressStats.queries_dropped`; the `CameraDetectionFrame` refusal is now
  documented there as a backstop. The daemon-side refusal in
  `perception_daemon/protocol.py` remains as the boundary check and still
  refuses a 17-phrase batch by count. **No longer blocking the live rows.**
* **Handoff 4 is RESOLVED.** P2-B added `whisperer.owner_events.*` to
  `configs/realtime.prototype.yaml.example`;
  `test_realtime_prototype_example_validates_and_carries_its_departures` now
  passes (`1 passed` on a targeted re-run).
* **Handoff 7 (new) — VENUE-1 inherits a red.** The strict xfail in §11.1 must
  turn green when the runtime composition root lands: either by routing every
  physical attach through `camera_ingress_kwargs`, or by P1-B making
  `CameraIngress` read the backend's declared origin when one is available.
  Deleting the xfail is not a fix.
* **Handoff 8 (new) — warm the SigLIP-2 vision session.** If P1-B's map writer
  calls `embed_fn` on the reactive-ish path, a 0.2–0.4 s first-call stall is
  worth removing with one throwaway `embed_image` on a 16×16 array after
  `--preload`, guarded so a failure only logs.

### 11.5 Re-verification of the whole card after these changes

```
$ .parcel/bin/python -m pytest -q --no-header tests/test_p1a_camera_backends.py \
      tests/test_p1a_perception_daemon.py
93 passed, 1 xfailed in 4.61s          # was 88 passed; +5 cells, +1 hazard xfail

$ .parcel/bin/ruff check src/parcel_robot/camera_channel/backends/{physical,uvc,realsense,recorded}.py \
      src/parcel_robot/perception_daemon/ tests/test_p1a_*.py \
      scrum/20260822/task_6/live_camera_proof.py
All checks passed!

$ bash -n scripts/launch_detector_daemon.sh scripts/launch_stack.sh     # clean
$ .parcel/bin/python -m parcel_robot.perception_daemon --help           # new --preload text
$ .parcel/bin/python -m pytest -q tests/test_prototype_profile.py::test_realtime_prototype_example_validates_and_carries_its_departures
1 passed
```

Files touched in this pass, all inside OWNS:
`camera_channel/backends/physical.py` (+41),
`perception_daemon/{server.py,__main__.py}` (comments/docstring/help only),
`scripts/launch_detector_daemon.sh` (help text only),
`tests/test_p1a_perception_daemon.py` (+5 cells, 2 cells corrected),
`scrum/20260822/task_6/P1A_STATUS.md`. No product behaviour changed except the
new helper; `runtime.py` and `ingress.py` remain untouched by this card. No
daemon is left running and no socket is left behind.
