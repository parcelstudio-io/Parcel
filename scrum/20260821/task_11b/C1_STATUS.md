# C-1 — attach the eye · status (re-dispatched executor)

**Card:** `scrum/20260821/task_11b/README.md`
**Executor:** Claude Opus (re-dispatch) · **Date:** 2026-08-21
**Result:** **COMPLETE, with two pre-registered deviations recorded as misses**

> **This document supersedes the C1_STATUS.md that occupied this path at 18:40.**
> That file described the collision-window implementation that was reverted out
> of the tree (verified empty-diff; see the CORRECTION section of
> `AUDIT_W1_INCIDENT_FABLE.md`). Its evidence directories
> `evidence/live_cpu_20260821T221731Z/` and
> `evidence/live_cpu_replication_20260821T222002Z/`, and
> `evidence/C1_PREREGISTRATION.md` / `C1_MUTATION_RESULTS.md` /
> `c1_mutation_results.json` / `run_c1_cpu_live.py` / `c1_cpu_live*.yaml`,
> describe code that **no longer exists**. They are preserved as the register's
> record of that run and are **not evidence for any claim below**. Everything
> this document claims is measured against `evidence/C1_RERUN_*` and
> `evidence/rerun_live_20260821T235718Z/`.

## 0. Entry conditions (the chain contract)

| Check | Result |
|---|---|
| Tree quiescence, measured twice | **PASS** — newest source mtime `2026-08-21 19:03:00.062` (`evals/companion/embodied_plan_v1/manifest.json`) at 19:21:52 (18m52s old) and **identical** at 19:23:22 after a 90 s wait |
| `git status --porcelain` matches predecessors' documented set | **PASS** — exactly the audit's certified set: 7 modified (W-1 keeps + the digest re-pin), 5 W-1 untracked deliverables, scrum docs. Nothing staged/stashed. HEAD `71b39a1` |
| Entry gate `scripts/ci_gate.py` | **PASS** — every hard gate green, default-suite 7,746 passed / 9 skipped, elapsed 336.4 s |
| Predecessor deliverables present | **PASS** — W-1 scene (`e89f4f12…`), PG-1 `perception_contention.py`, EV-1 `evidence_log.py`, `CameraIngress` + `MujocoEglCameraBackend`, OWLv2 int8 weights (163,173,570 B) all present. No HALT condition |

## 1. Headline

`runtime.attach_camera_ingress()` had **zero non-test call sites**. It now has
one, and the pixel path has run inside the live robot: the real
`web_panel.build_runtime` composition root, against a real simulator over a real
socket, with a real bound HTTP server, produced **69 typed detection frames**,
persisted **69/69 strictly-decodable perception rows** into EV-1, and served an
honest `/api/state` block plus a panel tile — while the runtime accepted
**160/160 motion requests** and the reactive-safety gate moved by **+0.735 ms
p99**.

The two things the CPU deployment cannot do, both pre-registered as expected
misses before measuring, are recorded as misses and not tuned away:

1. **Every frame is expired when it is published.** Capture-start→publish p50 is
   **562.6 ms** against the repo's 300 ms `DEFAULT_DETECTION_TTL_NS`; **16/16**
   retained frames carry `expired_at_publish=true` and the snapshot correctly
   reads `state=stale`. This is a diagnostic/proposal stream, **not** a
   usable-current authority stream for C-2.
2. **The whole control loop costs +28.2 ms p99 with the eye on.** That is above
   any +5 ms figure. It is *not* the card's safety claim — see §4.3, where the
   claim the card actually makes is measured separately and **closes**.

Neither is retuned after the fact, and the freshness indicator was not "fixed"
by moving the clock: measuring age from capture COMPLETION instead of capture
START would have made every frame look fresh, and that mutation is seed #3.

## 2. Definition-of-done register

| Requirement | Result | Exact claim |
|---|---|---|
| Config-gated attach, default OFF, fail-closed | **PASS** | Absent block ⇒ `None` ⇒ off; 18 malformed configs refused by type/range/unknown-key, including bool-as-number, NaN/inf rate, and the plausible typo `camera_ingress_rate` |
| Flag-off wire byte-identical | **PASS** | Same config PATH, rewritten: `/api/state` has no `camera_ingress` key at any depth, key list and normalized wire equal. Live OFF arm: `api_state_has_camera_key=False`, 0 frames, 0 perception rows |
| Frame flow at a configured rate | **PASS (target met, ceiling reported)** | configured 2.0 Hz, achieved **1.7522 Hz** ≥ the pre-registered 1.60 floor. The ceiling is the detector: 520.6 ms detect + 33.1 ms render |
| Bounded runtime-owned stream, drop-and-count | **PASS** | capacity 16; **68 published, 52 dropped, 16 retained** (68−52=16); detections **122 total / 82 dropped with evicted frames**; per-frame truncation counted separately |
| Snapshot surfacing + panel tile | **PASS** | `state` ∈ starting/fresh/stale/fault, separate frame vs last-detection age, achieved rate, queue depth/drops, class counts, evidence counters, composition caveat. Tile hidden unless the key is present |
| PG-1 admission registration | **PASS, and falsifiable** | **69/69** inferences ran under a `mission_lease` on the **process-wide** `default_guard()`; unit cell shows a 500 ms generation **refused** while held, and the lease released afterwards |
| Safety never queues behind a frame | **PASS** | `CollisionGate` p99 **0.117 ms OFF → 0.852 ms ON, delta +0.735 ms**, inside the pre-registered +5 ms bound. Structural half: the 10 Hz loop calls **no** producer method (AST-asserted) |
| EV-1 typed bounded persistence | **PASS** | 69 perception rows, **69/69** strictly decoded, `verify_event_log == []`, final row `log_closed`; OFF arm's log clean with **0** perception rows |
| Live proof on the real stack | **PASS** | Both arms symmetric: real sim, real socket, real `build_runtime`, real bound HTTP server, 160/160 motions accepted in each |
| No-CUDA path evidence | **PASS (measured, not assumed)** | ORT 1.28.0, EPs `['AzureExecutionProvider','CPUExecutionProvider']`, resolved `cpu_int8` / `CPUExecutionProvider`, `cuda_fp16` rejected with reason. §4.4 |
| Fresh frames post-dispatch | **PASS** | `frames_with_stale_provenance = []` in both arms; every frame's wall clock is after the run-start stamp |
| ≥8 seeds RED | **PASS** | 12/12 — §5 |
| Gate green | **PASS** | §6 |
| Freshness within TTL | **MISS (pre-registered deviation)** | 16/16 expired at publish; indicator honest |
| Whole-loop delta ≤ +5 ms | **MISS (pre-registered deviation)** | +28.211 ms p99; loop stays under the 10 Hz deadline (§4.3) |

## 3. What landed, and where the seams are

**OWNS, edited:** `src/parcel_robot/runtime.py`,
`src/parcel_robot/camera_channel/ingress.py`,
`src/parcel_robot/ui/index.html`, `tests/test_c1_camera_stream.py` (new, 66
cases), `tests/test_r24_lock_discipline.py` (one roster row — §3.4),
`scrum/20260821/task_11b/C1_STATUS.md` + `evidence/`.

**Deliberately NOT edited** — and this is the difference from the reverted run,
which declared four "necessary narrow deviations": `web_panel.py`,
`realtime/evidence_log.py`, `camera_channel/backends/mujoco_egl.py`,
`scripts/launch_sim.sh`, `sim.py`. **Zero out-of-OWNS product files were
touched.** Two design choices bought that:

* **The composition root lives in `runtime.py`, not the panel.** `start()` calls
  `_attach_configured_camera_ingress()`, which resolves the scene from the
  config the runtime already owns, binds `MUJOCO_GL=egl`, builds a static
  once-forwarded `MjModel`/`MjData`, loads the detector, and attaches. No panel
  edit is required for the eye to open.
* **EV-1 rows ride the existing `event` stream with a typed `kind`.** Adding a
  fifth stream would have meant re-versioning a record format `verify_event_log`
  pins and `evals/assertions` dispatches on — not C-1's to re-version. The row
  is fully typed (`kind="camera_detection_frame"`, exact-key decode) and bounded;
  the cost is that a reader filtering `stream=="event"` also sees perception
  rows, which is stated here rather than discovered later.

### 3.1 The typed frame

`CameraDetectionFrame` / `CameraDetectionRecord` are immutable, validated, and
exact-key decodable. Every field answers a question an auditor would otherwise
guess at: when the pixels were captured (not when the answer arrived), where the
camera was, what was asked, which provider answered, and how many detections
were dropped on the way. Construction refuses impossible values (score outside
[0,1], negative range, non-finite world point, publish-before-capture) and
refuses an inconsistent ledger: `retained + truncated == localized` and
`localized + rejected == raw`, or it is not a frame.

Serialization is a **stable fixed point**, not a float-exact round trip —
`as_dict` rounds for a compact JSONL row, so claiming encode→decode identity
would be false. What is asserted is that a stored row decodes and re-encodes
byte-equal, which is the property replay actually needs.

### 3.2 Freshness, measured from the pixels

`publish_latency_ns` runs from `capture_started_monotonic_ns`. This is the one
arithmetic choice that decides whether the indicator can lie, and it is the
reason the honest answer here is "16/16 expired" rather than "all fresh".

### 3.3 The pose mailbox — why safety cannot queue behind a frame

The control loop does **not** push into the producer. It writes a
single-overwrite slot under one leaf lock (`_offer_camera_pose`), strictly
**after** simulator emergency-stop adoption; the camera worker **pulls**
(`_take_camera_pose`). One fresh pose permits one capture; a stale or missing
pose yields no frame rather than re-rendering a pose the robot has left. So a
slow producer has no code path in front of the safety loop — asserted
structurally (AST) and measured (§4.3).

### 3.4 R24: one new lock, zero new ordering edges

`_camera_stream_lock` is the seventh runtime lock and guards the frame queue,
its counters, and the pose mailbox — one lock for all three deliberately.
`test_the_lock_roster_is_complete` went RED on it, exactly as designed, and it
is registered in `RUNTIME_LOCKS` with its owner and reason.
`test_the_lock_order_is_the_pinned_one` **passed unchanged**: C-1 adds
**zero** edges to `PINNED_LOCK_ORDER`. The lock is a leaf — never held across a
render, an inference, or an evidence-log offer, and the publish callback is
invoked outside the producer's lock (seed #8 proves the test would catch it).

### 3.5 Teardown ordering, corrected

Pre-C-1 `close()` stopped the camera *after* closing the evidence log — harmless
while nothing published, wrong the moment something did, because the last
in-flight frame's row would be dropped. The camera now stops first; the order
is asserted by AST rather than by comment.

### 3.6 A startup tail found by measurement, then fixed

The first clean cell showed `ControlLoopWork` **max 305.31 ms** on the ON arm —
one startup tick at three times the 10 Hz deadline. Cause: attaching after the
control-loop thread started, so MuJoCo scene compilation and ONNX session
creation contended with an already-turning loop. Moving the attach **before**
the loop thread removed it: ON max is now **41.619 ms**. Recorded because it was
a real defect that only a measurement would have found.

## 4. The live cell

Authoritative: `evidence/rerun_live_20260821T235718Z/summary.json`
SHA-256 `1dff417b790f1dbd7b47d09deb74b0f52d9a0211e4e38760676d31bff57a6db9`
Harness: `evidence/run_c1_rerun_live.py` · HEAD `71b39a1` · scene `e89f4f12…`

### 4.1 Method, and a confound found and removed

Both arms build a real runtime via the non-test `web_panel.build_runtime`, bind
a real ephemeral `RuntimeHTTPServer`, arm EV-1 through the runtime's own
`_arm_session_evidence()`, and are driven identically (a motion request every
250 ms for 40 s). Symmetry was adopted up front from the reverted run's own
post-mortem.

**A confound I introduced and then removed, on the record:** the first version
shared ONE simulator across both arms. The OFF arm's `close()` engages an
emergency stop, the simulator **latched** it, and the ON arm adopted a latched
E-stop — producing an ON arm with **0/160** motions accepted. Read naively that
says "the camera broke motion"; it is an arm-order artifact. The harness now
starts a **fresh simulator per arm**, and both arms accept 160/160. The earlier
run was discarded, not reported.

### 4.2 Flow

| Measurement | Value |
|---|---:|
| configured / achieved rate | 2.000 / **1.7522 Hz** |
| frames published / dropped / retained | 68 / 52 / **16** |
| detections retained total / dropped with frames | 122 / 82 |
| poses offered / consumed | 400 / 69 |
| render p50 / p95 / max (ms) | 35.402 / 39.336 / 40.809 |
| detect p50 / p95 / max (ms) | 520.590 / 528.622 / 532.985 |
| capture-start→publish p50 / p95 / max (ms) | **562.557** / 583.148 / 587.500 |
| expired at publish | **16 / 16** |
| stream errors / callback errors / truncations | 0 / 0 / 0 |
| frames with stale provenance | **0** |

Query was `[person, lamppost]`; persisted positives were **lamppost only**
(latest class counts `{"lamppost": 4}`). That is query-conditioned evidence, not
"everything the dog sees", and no detector-backed person claim is made — W-1
measured person recall at 0.014 on this world.

### 4.3 Latency — the card's bound, closed

| Metric | OFF p99 | ON p99 | Δ |
|---|---:|---:|---:|
| **`CollisionGate`** (reactive safety) | 0.117 ms | 0.852 ms | **+0.735 ms** |
| `MotionDispatch` | 0.496 ms* | — | +2.602 ms |
| `ControlLoopWork` | 11.072 ms | 39.283 ms | **+28.211 ms** |

\* dispatch OFF p99 from the same summary row.

**The card's claim is about the safety path** — "person-yield and reactive
safety never queue behind a frame". That path is `CollisionGate`, and its p99
delta is **+0.735 ms**, inside the pre-registered **+5 ms** bound. **Closed.**

`ControlLoopWork` is the whole 10 Hz tick including render/detect CPU
contention; its +28.211 ms was **pre-registered as an expected deviation with
its mechanism** before measuring. The acceptance for the loop is the deadline,
and ON p99 39.283 ms / max 41.619 ms are both **under 100 ms**. This is one
sequential descriptive pair, not a counterbalanced statistical study.

### 4.4 The no-CUDA path — a measured row, not an assumption

| Fact | Value |
|---|---|
| onnxruntime | 1.28.0 |
| available EPs | `['AzureExecutionProvider', 'CPUExecutionProvider']` |
| `CUDAExecutionProvider` | **absent from this build** |
| requested → selected | `auto` → **`cpu_int8`** |
| execution providers used | `['CPUExecutionProvider']` |
| precision / artifact | `int8` / `~/.cache/parcel/owlv2-b16/model_int8.onnx` |
| rejected | `('cuda_fp16', 'CUDAExecutionProvider not registered in this onnxruntime build')` |
| GPU used, before / after | 934 MiB / **934 MiB** (unchanged) |

The provider row is carried **per frame**, so no latency number in this document
can be read without knowing which provider produced it. GPU occupancy did not
move, which is what a pure-CPU detector should do; **no GPU residency is
claimed**, and PG-1's 86 ms/query CUDA figure does not describe this deployment.

### 4.5 Evidence, panel, isolation

* ON EV-1 `e4765644bb000f01…`: 100 rows, **69 perception**, **69/69** strictly
  decoded, `verify_event_log == []`, final row `log_closed`.
* OFF EV-1 `bda0836e7576d373…`: 31 rows, **0 perception**, verify clean.
* Panel HTML served 200 in both arms. **Precision:** `index.html` is a static
  asset that gained a hidden `#perception-tile` element, so the panel HTML is
  **not** byte-identical to pre-C-1; the tile is revealed only when the snapshot
  carries `camera_ingress`. The byte-identity claim in §2 is about the
  `/api/state` wire, which is where it was made.
* Owner store `parcel_memory.sqlite3` **unchanged** across the whole run.
* Both simulators exited on our signal; socket removed after stop.

**One number reconciled, so it does not read as a discrepancy:** the runtime
snapshot reports **68** frames published and 68 evidence rows offered, while the
EV-1 file contains **69** perception rows and the producer reports **69** leased
inferences. The snapshot is taken while the worker is still running; the 69th
frame completed during teardown and its row reached the log before it closed.
That is the ordering §3.5 exists to guarantee — camera stops, *then* the
evidence log closes — working as intended, not a lost or duplicated frame.

## 5. Seeded defects — 12/12 RED

Harness `evidence/run_c1_rerun_mutations.py`, results
`evidence/c1_rerun_mutation_results.json`. Protocol: pre-seed fresh-interpreter
canary; `__pycache__` purged before every cell; each restore verified by SHA
against pre-seed bytes; final sweep run after the last source write; repo-root
stray sweep.

**Final: 12/12 RED · 12/12 byte-restored · 12/12 green after restore · final
sweep 121 passed · repo-root strays none.**

| # | Seed | Property it breaks | RED by |
|---|---|---|---|
| 1 | explicit `false` silently enables | flag-off byte identity | assertion |
| 2 | queue eviction uncounted | a full queue and a blind camera render alike | assertion |
| 3 | freshness measured from the answer | a 0.5 s-old detection reports itself current | assertion |
| 4 | truncated rows not reconciled | a frame drops detections without counting them | assertion |
| 5 | stale pose is rendered | a stalled simulator yields confident fiction | assertion |
| 6 | worker reuses a missing pose | last good pose re-rendered forever | assertion |
| 7 | inference takes no PG-1 lease | camera inference stops registering for admission | assertion |
| 8 | publish runs inside the producer lock | a lock-order edge into the runtime | **deadlock** |
| 9 | two camera authorities coexist | observation stream and B4 authority silently both on | assertion |
| 10 | evidence rows silently skipped | perception becomes unauditable | assertion |
| 11 | non-frame payload accepted | untyped junk enters stream and evidence log | assertion |
| 12 | empty frames invent a detection age | "looked and saw nothing" fabricates an age | assertion |

### 5.1 The harness earned its keep twice, and both are on the record

**Seed 3 STAYED GREEN on the first full run.** The test
`test_frame_freshness_is_measured_from_capture_start` asserted the single most
important arithmetic property in this card — and could not detect its violation,
because the fixture set capture-completion **1 ns** after capture-start, making
the two candidate clocks numerically indistinguishable. The test's own comment
argued the opposite, and was wrong. **The test was fixed, not the seed:** the
fixture now renders for 250 ms and publishes at 400 ms, so measuring from the
answer yields 150 ms ("fresh") where measuring from the pixels yields 400 ms
(expired) — the clock choice now flips the verdict. Seed 3 then went RED. A
property asserted by a test that cannot fail is a property nobody is checking,
and this is exactly what the seeded-defect protocol exists to find.

**The first harness run left a mutation in the tree.** Seed 8 does not merely
fail — publishing inside the producer's non-reentrant lock **self-deadlocks**
the worker, so the cell hung, `subprocess.run` raised `TimeoutExpired`, and the
harness died *before its restore line*, leaving mutated bytes in
`ingress.py`. Caught immediately by re-running the anchor check; restored; then
the harness was hardened so the restore lives in a `finally` block and a hang is
recorded as RED-by-timeout rather than crashing the run. Verification that the
tree is clean is mechanical and was run after the final sweep: every one of the
12 seed anchors is present exactly once, i.e. **no seed remains applied**.
Reporting this rather than quietly fixing it is the point — a harness that can
leave uncertified bytes behind on an exception is the precise failure this
register keeps relearning.

## 6. Gate

**Exit gate: PASS — every hard gate green** (`2026-08-22T00:39:53Z`, elapsed
335.1 s).

* default-suite **7,812 passed / 9 skipped** / 42 deselected — exactly **+66**
  over the entry run's 7,746, which is this card's new test file and nothing else.
* tier-coverage 7,863 collected = 7,821 commit + 42 nightly, no orphans, no overlap.
* ruff 7 violations against baseline 7 — **new 0**.
* frozen-digest-sentinels: 4 immutable manifests byte-identical to pin.
* owner-store-isolation green; owner store SHA unchanged across every run.

Working tree at return: the inherited certified set (7 modified + 5 W-1
untracked + scrum docs) plus exactly this card's OWNS — `runtime.py`,
`camera_channel/ingress.py`, `ui/index.html`, `tests/test_r24_lock_discipline.py`
(one roster row), and the new `tests/test_c1_camera_stream.py`. Nothing staged,
nothing stashed, nothing committed — landing is the owner's act.

## 7. Residual risks and next owners

1. **This stream is not fit for C-2 authority as measured.** Every frame is
   expired at publish on CPU. The honest remedies are a real GPU provider in the
   normal environment or a pre-registered freshness policy — **not** moving the
   receive clock or widening the TTL, either of which corrupts causality (and
   the first is seed #3).
2. **`try_admit_generation` still has zero product call sites.** C-1 proves the
   lease is *published* (69/69) and that a declared 500 ms generation is refused
   while it is held; it cannot prove product generation admission or preemption,
   because the consumer half lives in `realtime/*` and is owner-gated. The live
   counters correctly read `admitted 0 / refused 0`.
3. **The detector already leases for person queries.** `OwlV2Detector` takes its
   own `mission_lease` on the same `default_guard()`, so a live snapshot shows
   **two** concurrent leases (C-1's outer, PG-1's inner) — verified not a leak
   (a controlled threaded run shows max 1 concurrent with the detector faked,
   and 0 after stop). C-1's outer lease adds coverage for the render/localize
   window and for non-person batches; it did not invent the registration.
4. **Static-copy fidelity.** The panel process does not own the simulator's
   `MjData`, so the render is a static scene copy posed from live telemetry:
   moving actors and robot joint state are **not** in the frame. Stated in the
   snapshot and the tile. Mirroring them needs a richer IPC contract, outside
   C-1.
5. **Panel JS is untested.** The repo's registered debt already names the
   missing panel JS harness; the tile is verified by served-HTML content and by
   the snapshot contract it reads, not by executing the renderer.
6. Long-duration RSS/VRAM stability is unproven — this cell is 40 s per arm.

## 8. Does not prove

Real D455 recognition · detector-backed person safety · GPU residency or any
CUDA claim for this deployment · a navigation/patrol mission (motion requests
were accepted and the pose changed; that is not an actuator or arrival claim) ·
statistical latency equivalence · multi-view fusion, absence decay, grounding
cutover · fitness of this stream for C-2/C-3 authority · long-duration
stability.

What it does prove: the eye opens on command and only on command, the pixels
reach the runtime as bounded typed observations that count what they lose and
admit how old they are, the safety path does not move when it does, the record
is auditable, and the whole thing is absent from the wire when it is off.
