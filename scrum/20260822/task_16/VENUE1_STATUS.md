# VENUE-1 — the runtime opens the physical eye · STATUS

**Card:** `README.md` · **Board:** `../TASK_BOARD.md` · **Exits:**
`../WAVE2_DESIGN_FABLE.md` §1 (DW-1), adopted verbatim ·
**Pre-registration:** `PREREGISTRATION.md`, sha256
`6a329f74db4e110febb009339d1f21a9fb059b64629f0f71664780ec268768cb`, written
before any measurement.
**Executor:** Claude Opus · **Verifier:** Fable · **Date:** 2026-08-22 ·
**Baseline:** `21ea2fb`

---

## Headline

`PARCEL_CAMERA_BACKEND=uvc|realsense|recorded` now reaches
`RobotRuntime._attach_configured_camera_ingress` and selects the venue there.
P1-A's declared HALT is closed: the attach site no longer builds the MuJoCo/EGL
ingress unconditionally, **a physical venue never imports MuJoCo at all**, every
published frame's `origin` is derived from the backend that made the pixels, and
a physical-frame / simulation-map mismatch is **refused on the exact runtime
path, before one frame flows**.

Two defects were found and closed on the way, both of them the "looks wired,
is dishonest" shape this card exists to remove:

1. **The learned map's writer origin was inferred from
   `_camera_stream_enabled`.** `_p1b_install_learned_map` stamps the map
   `simulation` whenever the camera stream is on, and prefers
   `self._camera_ingress.origin` when an ingress exists — but `start()` installs
   the map one line *before* the attach, so the ingress never existed yet and
   **the guess always won**. On a physical venue that means every place the dog
   saw with its own eyes would have persisted stamped `simulation`. Measured
   (`~/.cache/parcel-venue1/probe_mujoco.py`): `writer origin: simulation`,
   `scene_id: city_block` — the name of a street, on what would be a desk.
2. **The in-process origin-mixing refusal could never fire.**
   `OnlineSemanticMap._refuse_foreign_origin` compares the writer's origin with
   the *observation's*, and `_p1b_feed_learned_map` passes
   `provenance=learned.provenance` into `observations_from_frame` — so both
   sides of that comparison are the same object. The mixing that actually
   happens (a store of one world reopened by a run whose frames are another's)
   was left to be discovered by whoever reloaded the file tomorrow, by which
   time it is unloadable.

**Measured, through the product path, on this host (no hardware):**

| row | value |
|---|---|
| full `RobotRuntime.start()` on the recorded venue | starts, publishes, **0 dropped**, map learns 1 place, reloads it next run |
| 100 consecutive frames, PHYSICAL double | **100 published, 0 dropped, 0 stream errors, 100/100 stamped `physical`** |
| capture → publish p50 through the runtime **with a real daemon on a real AF_UNIX socket** (P1-A's 128×96 clip) | **0.39–0.55 ms** p50 across 6 runs (p95 0.49–1.06) |
| the same at **640×480** (the D455 raster) | **4.59–7.34 ms** p50 across 6 runs (p95 4.98–10.66) — it moves with host load like every number on this box |
| worst of those composed with P1-A's slower measured GPU round trip (113.7 ms) | **121.0 ms** ≪ 300 ms |
| `_semantic_candidates()` (the 10 Hz read) with the daemon absent / restarting / backed-off / returning garbage / 250 ms detect in flight | p95 **≤ 5.0 ms** in all five, no state raises |
| new cells | **35 passed**, `tests/test_venue1_physical_venue.py` |
| seeded RED | **5 of 5**, each on a byte-identical scratch copy, restored by sha256 |

**No robot hardware is on hand** (owner, authoritative). Both presence probes
say so right now, and this card added no third one:
`RealSenseIngest.device_report()` → `DevicePresence.ABSENT`,
`connected_devices()` → `[]`. The live `uvc` / `realsense` arms are
**OWNER-GATED** with their exact commands in §6 and are not claimed anywhere in
this document.

---

## 1. What changed

`git diff --stat` on this card's OWNS, and — because five other wave-2 cards are
writing the same files right now — **my share by reconstruction** beside it.
Every edit was an exact-match single-occurrence replacement, so reverse-applying
them rebuilds the pre-VENUE-1 text; script and reconstructions in
`~/.cache/parcel-venue1/share/` (`reconstruct.py`).

| File | VENUE-1's share | file total | what |
|---|---:|---:|---|
| `src/parcel_robot/runtime.py` | **+597 / −1** | +1456 / −3 | ONE region + two marked seams (below) |
| `src/parcel_robot/config.py` | **+16 / −0** | +16 / −0 | two `OVERLAY_INTRODUCIBLE_KEYS` entries |
| `configs/robot.prototype.yaml` | **+40 / −0** | +89 / −7 | the camera-venue block, shipped COMMENTED OUT |
| `tests/test_prototype_profile.py` | **+29 / −1** | +58 / −16 | the introducible-key ratchet moved (declared deviation, §5) |
| `tests/test_venue1_physical_venue.py` | **new, 1419 lines, 35 cells** | — | this card's pins |
| `scrum/20260822/task_16/` | new | — | `PREREGISTRATION.md`, this doc |

Where the two columns differ, the gap is another executor's concurrent work in
the same file, visible rather than assumed. No `git add/commit/stash/checkout/
reset/restore` was run. Nothing under `docs/`, `backlog/`, `README.md`,
`scrum/20260821/`, `reactive_safety`, `core/hard_stop` or the venv was touched.
`evals/nav_instruct/results/ledger.jsonl` was never opened — no minival was run.

### The region and the two seams

Everything this card put in `runtime.py` carries the string `VENUE-1`, so one
grep finds all of it.

| Block | size | why there |
|---|---:|---|
| **the region** (`CARD VENUE-1 — the runtime opens the PHYSICAL eye` … `END CARD VENUE-1 region`) | 575 | eight methods: venue resolution, the physical attach, the origin guard, the depth declaration, detector selection, the map reconcile, the refusal cleanup, the operator surface |
| **seam 1 of 2** — inside `_attach_configured_camera_ingress`, immediately after the flag-off return | 15 | it must run **before** `MUJOCO_GL` is written and before `import mujoco`, both of which are a dozen lines further down |
| **seam 2 of 2** — inside `camera_stream_snapshot` | 6 + 1 changed line | `"composition": self._venue1_composition() or { …C-1's literal… }` — see §5, this is a declared deviation |

P1-B's three seams, P0-A's camera-flag regions, P0-D's dispatch regions and
CAP-1's admission region were not touched. `camera_channel/ingress.py` (P1-B),
the backends and the daemon (P1-A) and the safety core carry **zero** diff
lines from this card.

### What the composition root now does

```
_attach_configured_camera_ingress
  └─ VENUE-1 seam 1: venue = PARCEL_CAMERA_BACKEND | perception.camera_backend
       ├─ None  → C-1's MuJoCo path, byte-identical to HEAD
       └─ kind  → _venue1_attach_physical_ingress(kind)   [returns; no GL, no mujoco]
             1. open_physical_backend(kind); backend.open()      ← eagerly, §2.1
             2. camera_ingress_kwargs(backend)  →  origin= from the BACKEND
             3. _venue1_declared_origin(...)    →  refuse an undeclared venue
             4. _venue1_detector(kind)          →  DaemonDetector | in-process OWLv2
             5. CameraIngress(**kwargs, detector=…, min_poll_interval_s=…)
             6. the same six wiring lines the MuJoCo path runs
             7. _venue1_reconcile_map_origin(...)  ← re-derive, then REFUSE a mix
             8. attach_camera_ingress(ingress)
```

**2.1 — `backend.open()` is called at attach, not lazily.** Constructing a
`RealSenseCameraBackend` succeeds on a host with no camera (the base class opens
on first `capture()`), so without it an absent D455 becomes a counted poll error
minutes into a mission instead of a refusal at startup with the device census in
the message. It also means the intrinsics handed to the ingress are the
**device's own** (`_adopt_profile` rebuilds the spec during `_open`), and that a
missing camera refuses *before* 200 MB of onnxruntime is loaded for it. This was
found by a pre-registered row failing, not by reading: `test_a_venue_that_cannot_
open_names_the_presence_check_not_a_new_one` DID NOT RAISE on the first run.

---

## 2. Pre-registered rows: met / missed

| # | Row | Result |
|---|---|---|
| **R1** | the venue is selectable and reaches the attach site; unknown value refuses by name | **MET** — `recorded` attaches a `RecordedCameraBackend`; `uvc`/`realsense` attach through doubles; `relasense` refuses with `unknown camera backend 'relasense'`; `--camera` outranks the profile key |
| **R2** | a physical venue never imports/initializes MuJoCo/EGL | **MET at the attach site**, **PARTIAL for `start()` off-oracle** — see the declared miss in §4.1 |
| **R3** | 100 consecutive PHYSICAL frames, 0 drops, 0 `unknown` | **MET** — 100 published / 0 dropped / 0 stream errors / 100 stamped `physical`; the recorded venue publishes `replay` and can never mint `physical` |
| **R4** | capture→publish p50 < 300 ms through the runtime with the daemon, and p50 + 113.7 < 300 | **MET** — 0.39–0.55 ms (128×96 clip) and **4.59–7.34 ms at 640×480** over six runs; worst composed 121.0 ms |
| **R5** | physical-frame/simulation-map mismatch REFUSED on the runtime path; inverse; replay/unknown admitted | **MET** — 3 refusals (simulation store + physical venue; physical store + replay venue; an *empty* store that declared `simulation`), 2 admissions (`unknown` store, same-world store) |
| **R6** | the writer's origin derives from the frame, never from "camera streaming enabled" | **MET** — `simulation` → `physical` on a physical venue, `replay` on a recorded one; and the same re-derivation replaces `scene_id: city_block` with `venue:<kind>` |
| **R7** | five daemon degraded states typed, none raising, `_semantic_candidates()` p95 ≤ 5.0 ms | **MET** — absence, restart, backoff window, undecodable schema, 250 ms backpressure; each visible in `DaemonDetector.snapshot()` (`stale`, `degraded_requests`, `consecutive_failures`, `last_error`) |
| **R8** | flag-off byte-identical | **MET** — `composition` compared field-for-field against C-1's literal; 464 passed / 1 xfailed across the eleven suites nearest this change |
| **R9** | RGB-only is named, never a silent pass | **MET** — 10 polls, **0 frames published**, 10 counted `stats.errors`, `depth_available: false` + a `depth_unavailable` reason on the operator's surface, 0 observations into the map |
| **R10** | ruff clean on OWNS; the ratchet stays at exactly 7 | **MET** — `All checks passed!`; `scripts/ci_ruff_baseline.json` unmodified at 7 fingerprints; the three ruff findings this card created (`RET501`, `PLR1711`, `UP031`, all in the new test file) were **fixed at the source**, none suppressed. See the `noqa` accounting below |

**Rows not on the list that matter:** the whole runtime `start()`s on the
recorded venue, learns a place from replayed desk pixels with `replay`
provenance and `venue:recorded` as its scene, persists it, and a **second**
runtime reloads it — which is the only way to tell a map from a log.

---

## 3. How verified

Environment: `.parcel/bin/python`, `.parcel/bin/ruff` 0.16.1, `TMPDIR` **unset**,
scratch under `/home/jaewoo-jang/.cache/parcel-venue1/`. No hosted spend. The
owner's live stack (`:8765`, `/tmp/parcel_sim.sock`) and `parcel_memory.sqlite3`
were never contacted. No process this card did not start was signalled.

### 3.1 The card's gates

```
$ .parcel/bin/python -m pytest -q --no-header -s tests/test_venue1_physical_venue.py
VENUE-1 R4  capture->publish p50=0.52 ms p95=1.06 ms
VENUE-1 R4b 640x480 capture->publish p50=7.34 ms p95=10.66 ms
35 passed, 1 warning in 20.61s

# the last of six runs; the spread is in the headline table. `runtime.py`
# sha256 34969c847382c9e39aba89aba3b2acbcd90a55077072ca241b7a5dd31f34a197 —
# the same file the seed harness recorded as its before/after baseline.

$ .parcel/bin/ruff check src/parcel_robot/runtime.py src/parcel_robot/config.py \
      tests/test_venue1_physical_venue.py tests/test_prototype_profile.py
All checks passed!
```

**`noqa` accounting, because the rule is "never `noqa`".** No finding this card
produced was suppressed — the three ruff raised were fixed in the code. The
region does carry **four** inline `# noqa: BLE001` (two of them `, S110`), each
on a boundary that must not raise and each with its reason on the line: the
attach's backend-close on a refused venue, the map release on a refused venue,
the store's `get_meta` on a pre-meta file, and the operator surface's read of a
foreign detector's `snapshot()`. That is `runtime.py`'s established convention
for a deliberate broad except — the file carries 62 of them and
`attach_camera_ingress`, two hundred lines above, uses the identical
`# noqa: BLE001, S110 - teardown best-effort` phrasing. A fifth was written and
then **narrowed away**: the RealSense remedy now catches `ImportError` only,
because `connected_devices()` already answers `[]` for a missing bus. None of
the four touches the ratchet, which is a fingerprint baseline and is unchanged.

### 3.2 The suites nearest this change (the flag-off proof)

```
$ .parcel/bin/python -m pytest -q --no-header \
    tests/test_venue1_physical_venue.py tests/test_c1_camera_stream.py \
    tests/test_p1b_map_learns.py tests/test_p0d_navigation_unblocks.py \
    tests/test_prototype_profile.py tests/test_p1a_camera_backends.py \
    tests/test_p1a_perception_daemon.py tests/test_cap1_admission.py \
    tests/test_c2_online_map.py tests/test_c3_cutover.py \
    tests/test_r24_lock_discipline.py
464 passed, 1 xfailed, 2 warnings in 37.68s
```

`tests/test_cap1_admission.py` is CAP-1's, executing concurrently; it is in this
list on purpose, because its G1 cell cross-checks the config sections a runtime
region reads against `OVERLAY_INTRODUCIBLE_KEYS` and this card adds two entries
to that set. It is green with them.

The one `xfailed` is P1-A's inherited hazard pin — see §4.2.

### 3.3 The product path, named exactly

* **The composition root** is exercised by calling
  `RobotRuntime._attach_configured_camera_ingress()`, which is the method
  `start()` calls — the same convention `tests/test_c1_camera_stream.py` uses.
* **Frames** are counted only where they arrive at
  `RobotRuntime._publish_camera_frame`, i.e. through the `on_frame` callback the
  composition root wired, not through a harness.
* **The worker's own cadence** has its own cell
  (`test_the_worker_thread_publishes_on_its_own_cadence`): the attach starts a
  real thread and nothing in that cell is hand-driven. The 100-frame rows stop
  the worker first and drive `poll_once()` so the count is exact; the frames
  still travel the product seam. **Stated because it is the one place a number
  is not on the worker's clock.**
* **`RobotRuntime.start()` itself** — control manager, seam 1's map install one
  line before the attach, the worker thread, the map feed, `close()`'s persist —
  has its own cell,
  `test_the_whole_runtime_starts_on_a_recorded_venue_and_learns_a_place`.
* **The daemon** is a real `PerceptionDaemon` on a real AF_UNIX socket with a
  stub detector injected through its existing `detector_factory` seam: real
  framing, real client, real `DaemonDetector`. Sockets live on a short path of
  this card's own (`~/.cache/parcel-venue1/sock/`), never under `tmp_path` — the
  108-byte AF_UNIX limit is what breaks P1-A's daemon tests under a long
  `TMPDIR`. No subprocess is started; every daemon is stopped in teardown and
  none is left behind.
* **The launcher** was exercised end to end without starting anything:

```
$ PARCEL_CAMERA_CONFIG=~/.cache/parcel-venue1/camera.json \
    bash scripts/launch_stack.sh --camera recorded --dry-run
Camera venue: recorded (PARCEL_CAMERA_BACKEND=recorded)
Camera config: /home/jaewoo-jang/.cache/parcel-venue1/camera.json
camera=recorded
dry run: nothing started, no credential read
```

### 3.4 Seeded RED — five guards, five seeds, restored byte-identically

Seeds edit the **product** on a byte-identical scratch copy of `src/`
(`~/.cache/parcel-venue1/seedsrc`, driven by `PYTHONPATH`, verified to be the
module the tests actually import) because five other cards are writing the live
tree. Harness: `~/.cache/parcel-venue1/seeds/run_seeds.py`; transcripts
`RED_S1..S5.txt`.

| Seed | what is broken in the product | named test that went RED | restored |
|---|---|---|---|
| **S1** | the seam's early `return` deleted ⇒ the physical path falls through into the MuJoCo preamble | `test_a_physical_venue_never_imports_mujoco`, `test_a_physical_double_never_imports_mujoco` | sha equal |
| **S2** | `origin=` dropped from the kwargs handed to `CameraIngress` (P1-A's handoff snippet **as first written**) | `test_a_physical_venue_publishes_frames_that_say_physical` + 2 | sha equal |
| **S3** | the origin-mixing refusal deleted | `test_a_physical_venue_refuses_a_simulation_map` + 2 | sha equal |
| **S4** | the writer re-derivation deleted ⇒ the map keeps the `_camera_stream_enabled` guess | `test_the_map_writer_origin_comes_from_the_frame` (`assert 'simulation' == 'replay'`), `test_a_recorded_venue_stamps_its_map_replay` | sha equal |
| **S5** | the RGB-only declaration deleted from the composition block | `test_an_rgb_only_venue_says_depth_is_unavailable` | sha equal |

Every seed: RED for the right reason, `runtime.py` sha256 identical before and
after, `__pycache__` purged either side, GREEN on the re-run.

`S4` also proves the one guard I marked `# pragma: no cover` is not dead: the
writer/frame post-condition inside the reconcile is unreachable while the
re-derivation works **and fires the moment it is removed**. It is labelled a
post-condition in the code rather than advertised as a guard.

### 3.5 A vacuity I found in my own test and fixed

`test_a_physical_venue_never_imports_mujoco` blocks `mujoco` with a
`sys.meta_path` finder. That is not enough: `parcel_robot.sim`'s first
statements are `import mujoco` / `import mujoco.viewer`, so once **any** earlier
cell in the session has imported `parcel_robot.sim`, a later
`from parcel_robot.sim import resolve_scene` is a dict lookup that imports
nothing and the finder never fires. Measured in both directions — a cell that
passed in isolation and failed in the full file, and vice versa. The fixtures
now forget `parcel_robot.sim` as well as `mujoco`, and the reason is written
next to `_MUJOCO_ROOTS`. The S1 seed was re-run after the fix and is still RED.

---

## 4. Misses and declared findings

### 4.1 MISS (partial R2) — `start()` off-oracle still imports MuJoCo, via P1-B

The **attach site** is clean, and S1 proves it. But `start()` installs P1-B's map
one line *before* the attach, and `_p1b_scene_id()` does
`from parcel_robot.sim import resolve_scene` — a module whose first statement is
`import mujoco`. So a physical venue running off-oracle (`semantic_source:
learned_map` / `shadow`) still drags MuJoCo into the process.

**Measured, not inferred:** `~/.cache/parcel-venue1/probe_mujoco.py` prints
`mujoco in sys.modules before install: False` → `AFTER install: True`.

* **Imported is not initialized.** No `MjModel`, no `MjData`, no
  `mj_forward`, no EGL context, and `MUJOCO_GL` is never written — asserted in
  the pinning cell. The cost is import time and RSS, not a GL binding.
* Under the shipping `oracle` source the installer returns before that line and
  nothing is imported at all.
* `_p1b_scene_id` is inside **card P1-B's marked region**, outside this card's
  OWNS. **HALT on the fix, handed off** (§7 handoff 1) with the one-line remedy.
* Pinned as today's behaviour by
  `test_the_map_installer_still_imports_mujoco_and_that_is_a_handoff`, so it
  cannot rot: when the handoff is taken, that cell goes red and both are
  revisited together. (P1-A's `test_the_hazard_is_real_today_and_this_is_what_it
  _looks_like` is the same pattern.)

### 4.2 P1-A's inherited strict `xfail` is still `xfail`, and deleting it is not a fix

P1-A left `test_an_ingress_built_without_a_declared_origin_must_not_publish_
unknown` as a strict xfail for VENUE-1 to turn green. It asserts that a
`CameraIngress` constructed **without** `origin=` must not publish `unknown`.
That can only become true by changing `CameraIngress` itself to read the
backend's declared origin — and `camera_channel/ingress.py` is P1-B's and is on
this card's MUST-NOT-TOUCH list.

What this card did instead is the other half of P1-A's own handoff 7: *route
every physical attach through `camera_ingress_kwargs`*. The **product** property
is now held and seeded (S2): no composition root in this tree can publish a
physical frame stamped `unknown`, because the only path that builds one derives
the declaration from the backend and refuses if it is absent. The xfail remains
red because the *class default* is unchanged, which is P1-B's deliberate design
(a renderer that could mint `physical` by default is the W0-A defect). **Handed
off (§7 handoff 2), not deleted.**

### 4.3 An RGB-only ingress mode was NOT added; the D455 is the day-one device

The card offered two options. Adding an explicit RGB-only ingress mode means
editing `camera_channel/ingress.py` (P1-B, MUST NOT TOUCH), so this card takes
the second: **it states plainly that the D455 is the day-one device**, and makes
the state legible instead of silent. A `uvc` venue attaches (the detector and
the daemon *do* run end to end on a webcam — that is real day-one value P1-A
measured), publishes **nothing**, counts every poll as an error, and says
`depth_available: false` with a `depth_unavailable` reason on `/api/state`. **No
synthetic depth is substituted** — a constant assumed plane would produce world
coordinates that look like measurements and are not.

### 4.4 A red in the shared tree that is NOT this card's

`tests/test_runtime.py::test_runtime_executes_bounded_owner_relative_steps_and_
manual_preempts` fails in the current worktree
(`"My LiDAR feed is stale right now…"` instead of `bounded move`). Reproduced
three ways:

```
worktree as it is                                   → FAILED
worktree with VENUE-1 reverse-applied (share/pre)   → FAILED     ← not mine
git archive HEAD src, PYTHONPATH at it              → 1 passed   ← a wave-2 regression
```

Reverting `authority.py` or `navigation/reactive_safety.py` to HEAD in isolation
raises an ImportError (other in-flight files already depend on their new API), so
I could not bisect it further without touching another card's work. **Reported,
not fixed** — it is in no part of this card's OWNS. Reproduction commands above;
`~/.cache/parcel-venue1/headsrc` and `.../pre` are the two trees.

---

## 5. Deviations from OWNS, declared

The card's OWNS is *`runtime.py` attach-site region only, `config.py` venue keys,
`configs/robot.prototype.yaml` camera block, `tests/test_venue1_*.py`,
`task_16/` docs*. Three deviations, each minimal and each inert on the
simulator path:

1. **`camera_stream_snapshot()` — one changed line plus a 6-line marked comment
   (VENUE-1 seam 2 of 2).** C-1's `composition` literal describes the MuJoCo
   tile: `mode: static_scene_copy_pose_synced`, `real_camera: False`,
   `dynamic_actors_synced: False`. On a physical venue every line of that is
   false, and an operator surface saying `real_camera: false` while a D455
   streams is the same class of lie as a frame stamped `unknown` — which is the
   defect this card exists to remove. The edit is
   `"composition": self._venue1_composition() or { …C-1's literal, untouched… }`;
   `_venue1_composition()` returns `None` on every simulator run, so the flag-off
   snapshot is byte-identical and is asserted field-for-field
   (`test_no_venue_means_the_simulator_and_this_card_is_absent`). It is also how
   the venue reaches `/api/state` at all, since `state["camera_ingress"]` is the
   only camera key on the wire.
2. **`tests/test_prototype_profile.py` (P0-A's) — the introducible-key ratchet.**
   `test_introducible_keys_are_exactly_the_three_documented_families` asserts
   every key in `OVERLAY_INTRODUCIBLE_KEYS` starts with one of three prefixes,
   so it goes red the moment a real fourth family lands. That is the ratchet
   working, exactly as R24's lock roster worked for P1-B. It now names the
   fourth family with the reason, and I added the other half — that the two new
   keys are loadable by the overlay **and** that their VALUES are refused by
   name where they are read. +29 / −1.
3. **`RobotRuntime._venue1_state` is a class-level default**, not an `__init__`
   attribute, because `__init__` belongs to another region. It is never mutated
   in place; the attach rebinds it on the instance.

Two things the card names that were deliberately **not** done:

* The venue key is `perception.camera_backend`, not `perception.camera.backend`.
  A nested `perception.camera:` block would need a subtree exemption in
  `OVERLAY_INTRODUCIBLE_KEYS`, and a subtree exemption stops the loader
  descending — the "looks like a spelling guard and is inert" failure ROAM-1's
  comment in that file warns about. Two scalars keep the typo check real.
  Borrowing the `camera_ingress*` prefix was worse: that prefix belongs to
  `CameraStreamConfig.from_section`, which **refuses** any `camera_ingress*` key
  it does not know, so both keys would have been a startup error.
* `configs/robot.prototype.yaml` ships the block **commented out**. No camera is
  attached to this host, and a profile naming a venue nobody has would turn
  every prototype start into a refusal. `--camera` outranks the key, so the D455
  can be tried the day it arrives without editing a file.

---

## 6. Owner-gated rows — the exact commands, never claimed

No camera exists on this host. Both existing probes agree, and this card added
no third:

```
$ ls /dev/video*
ls: cannot access '/dev/video*': No such file or directory
$ .parcel/bin/python -c "from parcel_robot.camera_channel.backends.realsense import connected_devices; print(connected_devices())"
[]
$ .parcel/bin/python -c "import sys; sys.path.insert(0,'scripts'); from parcel_capture.ingest.realsense import RealSenseIngest as A; r=A.device_report(); print(r.presence, r.detail)"
DevicePresence.ABSENT realsense: nothing matches /dev/video* — no device of this kind is attached to this host
```

**OG-1 — the D455 venue, live.** Plug the D455 into a USB-3 (blue) port, direct,
no hub, then:

```
$ scripts/launch_detector_daemon.sh --background --preload
$ PARCEL_PROFILE=prototype PARCEL_CAMERA_BACKEND=realsense \
  PARCEL_PERCEPTION_SOCKET="$(.parcel/bin/python -c 'from parcel_robot.perception_daemon import default_socket_path; print(default_socket_path())')" \
  .parcel/bin/python -m parcel_robot.web_panel
```
Expected on `/api/state` → `camera_ingress.composition`:
`mode: physical_camera`, `venue: realsense`, `real_camera: true`,
`evidence_origin: physical`, `depth_available: true`,
`origin_label: d455-device-<serial>`, `detector.kind: daemon`.
What to measure: capture→publish p50 with the **real** OWLv2 (this card's 6.14 ms
plus P1-A's ~100–114 ms), 100 consecutive frames with zero drops, and whether
the map's places land where the objects are.

**OG-2 — a plain USB webcam.** Same command with
`PARCEL_CAMERA_BACKEND=uvc`. Expected: the detector and the daemon run end to
end and **no frame is published** — `depth_available: false`,
`depth_note: depth_unavailable…`, `producer.errors` climbing. That is the
correct outcome, and it is the row that decides whether an RGB-only ingress mode
is worth building (§7 handoff 5).

**OG-3 — the recorded arm on real pixels.** P1-A's committed clip is synthetic.
Record a real desk clip (`camera_channel.backends.recorded.write_clip`, or
P1-A's §6 step 5), point `PARCEL_CAMERA_CONFIG` at it, and re-run OG-1's command
with `PARCEL_CAMERA_BACKEND=recorded`. Frames stay `replay` by construction —
a file may not mint live authority — so this measures recognition, not
provenance.

---

## 7. Handoffs

1. **P1-B's region — the map installer imports MuJoCo and names the wrong
   world.** `_p1b_scene_id()` reaches for `parcel_robot.sim` (which imports
   `mujoco` at module scope) *before* consulting `_camera_scene_path`, and on a
   physical venue it stamps `scene_id: city_block`. One line fixes both:
   resolve the venue's own name first, and only fall back to `resolve_scene`
   when there is no venue — the import then never happens on a physical run.
   VENUE-1 already repairs the *name* by re-running the installer after the
   venue is known (`scene_id: venue:realsense`), but the first install's import
   is unavoidable from outside that region. Pinned by
   `test_the_map_installer_still_imports_mujoco_and_that_is_a_handoff`; §4.1.
2. **P1-B's region — `CameraIngress.origin` and P1-A's strict xfail.** The
   product property is held at the composition root; the *class default* still
   publishes `unknown` for an ingress built without `origin=`, so P1-A's strict
   xfail stays red. If `CameraIngress` grows "read the backend's declared origin
   when the backend has one", the xfail turns green and P1-A's companion cell
   `test_the_hazard_is_real_today…` goes red — revisit both together. §4.2.
3. **`DaemonEmbedder` for the physical path.** The venue currently loads
   `load_siglip2_embed_fn()` exactly as the MuJoCo path does, which means a
   second in-process copy of SigLIP-2 next to the daemon's on one GPU. P1-A's
   `DaemonEmbedder` avoids that (3.4 ms warm over the socket) but **raises**
   when the daemon is away, and `CameraIngress._capturing_embed` catches an
   encoder failure, falls back to the label hash, and still stamps the SigLIP
   space — so a vector that is an 8-dim word fingerprint would enter the map
   labelled `siglip2-base-patch16-224`. Switching needs that stamp path looked
   at first. Not guessed.
4. **CAP-1 / `/api/state`.** The venue reaches the wire through
   `camera_ingress.composition`. `RobotRuntime.venue_snapshot()` is the richer
   read — it merges the daemon's **live** `snapshot()` rather than the attach-time
   answer, because "the daemon answered at startup" and "the daemon is answering
   now" are different facts. If CAP-1's admission table wants a capability row
   for the eye, that method is the seam.
5. **An RGB-only ingress mode** is unbuilt and gated on OG-2. If a plain webcam
   turns out to be worth mapping from, the shape is: `CameraIngress` publishes
   frames with `depth_m=None` and every depth-dependent gate reports
   `depth_unavailable` rather than passing. Do not ship a synthetic-depth
   fallback.
6. **`configs/robot.prototype.yaml` is one uncomment away from the D455.** Two
   lines, both documented in place.

---

## 8. What this does NOT prove

* **Nothing here proves a camera works.** No hardware was in the loop. The
  physical arms run against doubles that subclass P1-A's
  `PhysicalCameraBackendBase`; they prove the composition root, the provenance
  and the refusals, and they prove nothing about a D455 streaming.
* **R4 does not measure OWLv2.** The daemon's detector is a stub over a real
  socket; the row is the pipeline, the copy and the process boundary. The GPU
  cost is P1-A's 100.6 / 113.7 ms p50 and is additive.
* **Recognition quality is untouched.** P1-A's committed clip is synthetic and
  says so in its own manifest; the one map entry the `start()` cell learns is a
  stub detector's box on a drawn rectangle.
* **The map is proved honest, not correct.** This card makes the store say which
  world it came from and refuses to mix two. Whether the places are in the right
  place is P1-B's question and needs OG-1.
* **The 100-frame rows are not on the worker's clock.** They drive `poll_once()`
  so the count is exact; the worker's own cadence has a separate, smaller cell.
* **Off-oracle only** for everything about the map: under the shipping `oracle`
  source there is no learned map and §4.1, R5 and R6 have no subject.

---

## 9. Scratch and cleanup

`/home/jaewoo-jang/.cache/parcel-venue1/` — seed harness and five RED/GREEN
transcripts (`seeds/`), the byte-identical `src/` copy the seeds ran against
(`seedsrc/`), the share reconstructions and their script (`share/`), the
pre-VENUE-1 and HEAD trees used for §4.4 (`pre/`, `headsrc/`), the two probes,
and the daemon socket directory (`sock/`, empty). Nothing was written to `/tmp`.

Every daemon this card started ran **in-process** on threads and was stopped in
teardown; no socket is left behind and no subprocess was spawned. No process I
did not start was signalled. The MOVE-1 patrol sim, `:8765` and
`/tmp/parcel_sim.sock` were never contacted. The owner's
`parcel_memory.sqlite3` was never opened. `evals/nav_instruct/results/ledger.jsonl`
was never written.

---

# Correction pass — 2026-08-22, after Fable's 15-agent verification (ACCEPT with corrections)

Seven items, all taken. Two of them are handoffs the verifier **routed into**
this card from CAP-1 and OT-2; both were taken and both are seeded. Same rules:
Edit-only, git read-only, `TMPDIR` unset, a seeded RED per new guard on a
byte-identical scratch copy of `src/`.

**Gates after the pass**

```
$ .parcel/bin/python -m pytest -q --no-header -s tests/test_venue1_physical_venue.py
VENUE-1 R4  capture->publish p50=0.45 ms p95=0.58 ms
VENUE-1 R4b 640x480 capture->publish p50=7.12 ms p95=8.53 ms
VENUE-1 R4c 640x480 + 100 ms detect: capture->publish p50=108.13 ms
46 passed, 1 warning in 24.15s              # was 35

$ .parcel/bin/python -m pytest -q --no-header <the eleven suites of §3.2>
479 passed, 1 xfailed, 2 warnings in 40.38s  # was 464

$ .parcel/bin/python -m pytest -q --no-header tests/test_runtime*.py \
    tests/test_move1_patrol.py tests/test_roam1_behavior.py tests/test_ot2_*.py \
    tests/test_p1c_owner_tracker.py tests/test_door1_doorway.py \
    tests/test_nm1_promotion_and_asks.py tests/test_import_order_no_cycle.py
368 passed, 1 skipped, 2 warnings in 28.08s

$ .parcel/bin/ruff check <every file this card touched>
All checks passed!                           # ratchet still 7, no new noqa

$ .parcel/bin/python ~/.cache/parcel-venue1/seeds/run_seeds.py
S1..S12: RED=True restored=True GREEN=True   # was S1..S5
```

`runtime.py` sha256 `89f4c43b77a8eaa8313a34fc72585292846be00d1c3a643673fe397e05cf1383`
— the same file the seed harness recorded as its before/after baseline.

**Share, re-measured by reconstruction** (`~/.cache/parcel-venue1/share/reconstruct.py`):

| File | VENUE-1's share | file total |
|---|---:|---:|
| `src/parcel_robot/runtime.py` | **+769 / −1** | +1756 / −3 |
| `src/parcel_robot/config.py` | +16 / −0 | +16 / −0 |
| `configs/robot.prototype.yaml` | +40 / −0 | +96 / −7 |
| `tests/test_prototype_profile.py` | +29 / −1 | +58 / −16 |
| `tests/test_venue1_physical_venue.py` | new, 1856 lines, **46 cells** | — |
| `tests/test_cap1_admission.py` | one cell rewritten (§C7) | CAP-1's, still untracked |

The verifier's `+599 / −1` and my earlier `+597 / −1` were both taken before
this pass; the number above supersedes them and is what the reconstruction says
now. (The earlier gap was one edit — narrowing a `noqa` to `except ImportError`
— landing between the two measurements.)

## C1 — the venue's LIVE detector state now reaches the wire  *(the real one)*

`venue_snapshot()` had **zero product callers**: seam 2 called
`_venue1_composition()`, which is frozen at attach time, so `/api/state` would
have kept reporting `reachable_at_attach: true` while the socket was long dead.
The whole reason the detector is out of process is that its failures are
survivable **and visible**; half of that was missing.

Seam 2 now calls `self.venue_snapshot()`, which merges the detector's live
`snapshot()` over the attach-time block and falls back to it unchanged when the
detector exposes no `snapshot()`. Both facts are on the wire, because they
answer different questions: `reachable_at_attach` (did it come up?) and `stale`
/ `consecutive_failures` / `last_error` (is it answering now?).

Pinned by `test_the_operator_wire_carries_the_daemons_LIVE_state_not_the_attach_note`:
a real daemon on a real socket, two polls, `stale is False` on the wire; the
daemon is then stopped, two more polls, and `/api/state` moves to `stale: True`
with a `last_error` while `reachable_at_attach` stays `True`.
**Seed S6** reverts seam 2 to `_venue1_composition()` → RED.

## C2 — the reconcile's raise window

If the second install raised, the runtime kept a map whose store was **closed**
while `_p1b_store_closed` still read `False`; teardown would then persist
through a shut connection and report a store it had not written. The
close/re-install pair is now wrapped: on failure the flag is set to the truth,
`_venue1_drop_learned_map()` releases the map, and the venue refuses.

Pinned by `test_a_failed_re_install_never_leaves_a_closed_map_installed`, which
also asserts the quiet teardown (`_p1b_persist_learned_map() == 0`).
**Seed S7** narrows the `except` so the window is unguarded → RED.

## C3 — `perception.detector` is validated on BOTH venues, and the simulator says it ignores it

The key was read inside the physical attach, so on the shipped simulator venue a
typo — or a deliberate `daemon` — was read by nothing and refused nowhere. It is
now validated in **seam 1a**, above C-1's early return, so it refuses on every
venue including a camera-off runtime. And C-1's composition literal gained one
key, `detector`, reporting `{kind: in_process, configured: <what you wrote>,
honoured: false}` when the operator asked for something the simulator does not
do. That is a knob made visible, not a behaviour change: the simulator still
always loads in-process OWLv2.

Pinned by `test_the_simulator_venue_says_it_does_not_honour_the_detector_key`
and `test_a_detector_typo_refuses_on_the_simulator_venue_too`.
**Seed S12** makes the honoured flag constant-true → RED.

## C4 — the one host-conditional cell is marked as such

`test_a_venue_that_cannot_open_names_the_presence_check_not_a_new_one` is the
only cell that drives the real `open_physical_backend` with no double; it passes
here because `connected_devices()` is empty, and the verifier reproduced its
failure against a D455-shaped double. It now carries
`@pytest.mark.skipif(bool(_attached_realsense()), …)` naming **OG-1** as the
attached arm, and its docstring says what it pins (the refusal MESSAGE on a host
with no camera) and what it does not.

## C5 — the mixing guard's ROW census was pinned by nothing

The verifier's mutation was right: deleting `*foreign` left all 35 cells green,
because `_seed_store` goes through `persist()`, which rewrites the `origin`
meta — so `declared` alone always made `mixed` non-empty. Added
`_save_rows_directly()`, which writes rows through `store.save()` and asserts
`get_meta("origin") is None`, and two cells on it:

* `test_the_row_census_refuses_a_store_whose_META_says_nothing` — `simulation`
  rows, no meta, physical venue ⇒ refused, naming the origin and the count.
* `test_a_compatible_foreign_origin_is_reported_and_not_refused` — `unknown`
  rows under a `replay` venue ⇒ admitted, and `foreign_but_compatible` is
  asserted, which nothing read before.

**Seed S8** deletes only `*foreign`: the row-census cell goes RED
(`DID NOT RAISE`) **while the meta-covered cell stays green** — which is exactly
the gap, now closed.

## C6 — the six notes

* **`_venue1_state` outliving its ingress: FIXED, not declared.**
  `_venue1_composition()` now compares `self._camera_ingress` **by identity**
  against the ingress the state describes and reports `attached`; `real_camera`
  requires it. After `detach_camera_ingress()` the wire still names the venue
  this run selected — that is a fact about the run — and no longer claims a
  camera. `test_the_surface_stops_claiming_a_camera_once_the_eye_is_detached`;
  **seed S11**.
* **R4 restated.** R4/R4b are the pipeline with a detector that returns
  instantly; composing them with P1-A's GPU number is a MODEL. **R4c measures
  the arithmetic**: a daemon whose stub sleeps 100 ms inside `detect`, at
  640×480, yields **108.13 ms** p50 against a 7.12 ms pipeline — the model holds
  to about a millisecond on this path. It is still quoted as a **floor**, not a
  prediction: OWLv2 on a real GPU contends with the SigLIP encoder in the same
  daemon process and with whatever else holds the card, which is why P1-A's own
  round trip moved between 100.6 and 113.7 ms across two runs on an idle box.
  The end-to-end number with real weights is **OG-1**, and this card does not
  claim it.
* **A `simulation`-rows store opened by a `replay` venue is admitted** —
  deliberately, since both are synthetic and refusing would make a clip recorded
  from the simulator unusable against the map it came from — **and `persist()`
  then rewrites the store's `origin` meta to `replay` while the older rows still
  say `simulation`.** The ROWS are the authority (`load_all` and this card's
  reconcile both read them); the meta describes only the newest writer. Measured
  and pinned by
  `test_a_replay_venue_over_simulation_rows_is_admitted_and_rewrites_the_meta`
  rather than left as prose. Handoff 8 below.
* **The whole-runtime cell publishes frames because its detector is stubbed.**
  `test_the_whole_runtime_starts_on_a_recorded_venue_and_learns_a_place` swaps
  `load_owlv2_detector` for `_StubDetector`, so the one place it learns is a
  stub's box on a drawn rectangle. It proves the ORDERING and the provenance —
  install-before-attach, re-derive, feed, persist, reload — and nothing about
  recognition.
* **Share corrected** to `+769 / −1` (table above).
* **The vacuous `_refuse_foreign_origin` is now numbered** — handoff 7.

## C7 — the two routed handoffs, both taken

**CAP-1's one-directional source binding.** `_p1b_install_learned_map` binds the
process-global source only when the policy READS the learned map; under `oracle`
it returns first, so a process that had already bound `learned_map` handed the
next runtime a source its YAML did not describe. **Taken:**
`_venue1_bind_semantic_source()` in seam 1a asserts the configured policy on
every started runtime — camera on or off, which is why seam 1a sits above C-1's
early return. Binding the SOURCE is the whole fix (`oracle` means
`reads_learned_map` is False, so a stale map object is never consulted); the map
object is deliberately left alone, because clearing it would tear down a map
another runtime in the same process may still own.
`test_the_semantic_source_binding_now_follows_the_config_in_both_directions`;
**seed S9**.

As instructed, `tests/test_cap1_admission.py::test_the_view_reports_a_source_binding_that_is_only_one_directional`
was **updated in the same change** rather than routed around — renamed
`test_the_source_binding_now_follows_the_config_in_both_directions`. It now pins
that the row is **True** after `start()`, and keeps CAP-1's guard live by
rebinding the source underneath a running runtime and asserting the row goes
False with its reason. **One thing did not move, and it is pinned as today's
behaviour with a handoff back to CAP-1** (handoff 9): a profile that *declares*
`semantic_source_matches_config` still refuses, because
`check_required_capabilities(self)` runs one line **before**
`_attach_configured_camera_ingress()` — so the gate reads the stale global that
the very next line corrects. The remedy is one line in CAP-1's own region.

**OT-2 §9.1 — pixels reach the owner tracker on a live camera.** OT-2's
`_ot2_latest_rgb` duck-types `latest_rgb()` on the attached ingress and degrades
to `no_pixels` without it, so on the one venue where identity from real pixels
is the point the tracker kept position tracks and asserted nothing.
`CameraIngress` is P1-B's file, but a PHYSICAL backend already holds the buffers
it just produced, so the composition root supplies the accessor:
`ingress.latest_rgb = lambda: backend.last_buffers.color_rgb8`. The synchrony
argument is OT-2's own and is a property of the caller — `last_buffers` is
written inside `backend.capture()`, in the same `poll_once` that publishes the
frame, and `_ot2_note_camera_frame` runs synchronously inside that publish, so
no later capture can have swapped the buffer. **This is the stop-gap, not the
shape OT-2 asks for**: any consumer that moves behind a queue desynchronizes
silently, which is why the pixels should eventually be carried WITH the frame.
`test_a_physical_venue_hands_the_owner_tracker_its_pixels` asserts the handed
pixels are byte-equal to the backend's own buffer; **seed S10**.

## Correction-pass seeds (each on the byte-identical scratch copy)

| Seed | product mutation | test that went RED |
|---|---|---|
| **S6** | seam 2 reverts to the attach-time composition | the live-wire cell |
| **S7** | the re-install raise window is unguarded | the closed-map cell |
| **S8** | the ROW half of the mixing census is deleted | the meta-less-store cell (the meta-covered one stays green) |
| **S9** | CAP-1's binding fix removed | the both-directions cell |
| **S10** | OT-2's accessor removed | the owner-tracker-pixels cell |
| **S11** | the attached-identity check removed | the detach cell |
| **S12** | the simulator stops reporting the key it does not honour | the honoured cell |

## The foreign red, restated

`tests/test_runtime.py::test_runtime_executes_bounded_owner_relative_steps_and_manual_preempts`
is **order-dependent**: it FAILS run alone, PASSES inside the thirteen-suite
batch above. It still reproduces with VENUE-1 reverse-applied
(`PYTHONPATH=~/.cache/parcel-venue1/pre`) and still passes against
`git archive HEAD src`, so it remains another wave-2 card's regression and not
this one's. Not fixed — it is in no part of this card's OWNS.

## Handoffs added by this pass

7. **P1-B — `OnlineSemanticMap._refuse_foreign_origin` is still labelled a guard
   and is still vacuous.** `_p1b_feed_learned_map` passes
   `provenance=learned.provenance` into `observations_from_frame`, so the writer
   origin is compared against itself on every observation. VENUE-1 replaced the
   *effect* at the composition root, but the method in P1-B's file still reads
   as a live per-observation guard and will be trusted as one. Either derive the
   observation's origin from the frame in `observations_from_frame`, or say in
   that docstring that the check is a type-safety net and the venue check is the
   real one.
8. **The store's `origin` meta describes only its newest writer.** See C6. If
   anything ever reads `map_meta.origin` as the store's identity rather than as
   a hint, it needs the row census instead.
9. **CAP-1 — one line of ordering.** Call `self._venue1_bind_semantic_source()`
   immediately before `check_required_capabilities(self)`, or move the check
   after the attach, and the declaring-profile false alarm goes away. Pinned in
   CAP-1's own cell so taking it turns that assertion red and both cards are
   revisited together.
10. **P1-B / OT-2 — carry the pixels WITH the frame.** `ingress.latest_rgb` is a
    side channel that is sound only because its one caller is synchronous inside
    the publish. `on_frame(frame, rgb=…)` or a `frame_id`-keyed accessor makes
    the pairing a type instead of a timing coincidence.

## Cleanup after the pass

No process was left running; the socket directory is empty; no `/tmp` writes; the
owner's store and live stack were never touched; the ledger was never written.
