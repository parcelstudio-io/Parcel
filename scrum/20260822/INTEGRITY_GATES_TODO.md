# Integrity gates — today’s corrective TODO · 2026-08-22

**Priority:** P0 release integrity. This work preempts new feature, autonomy,
hardware-motion, and god-object-refactor work until the exit gate at the end of
this document is green.

**Starting point, reassessed 2026-08-22:** `main` / `origin/main` at
`c9251d2e9bdef30393046f96d7ed7b9e4ed6bb27`. That commit is documentation-only;
the executable baseline remains the earlier committed Wave-P0 code plus the local
dirty P1/P2 wave. The active `main` worktree currently has 41 modified tracked
files (`+5,748/-171`) and 138 untracked paths, including 23 untracked product
modules (about 8,792 lines) and 14 untracked test modules (about 8,900 lines).
Preserve it. Run implementation lanes in isolated branches/worktrees or serialize
them through one integrator; do not revert, overwrite, stash, broadly stage, or
commit another lane’s files.

## Baseline being closed

Do not convert these failures into skips or silently move the denominator:

| Integrity break | Current evidence | Closure signal |
|---|---|---|
| Unitree assets are ignored and not fetched | A tracked-only archive raises from `hard-safety` while opening `third_party/unitree_mujoco/.../go2.xml`; no summary or JSON is emitted. The earlier 118-of-170 reproduction identified a shared cause but is not a trustworthy current denominator. | Clean checkout contains and validates the exact minimal asset pack; every stage still reports when the pack is deliberately damaged |
| Python support claim is false on 3.11 | `RetainedEvent.fields` is rejected during import; the fresh 3.11 audit collected 6,067 nodes with 69 errors, 2,634 current nodes absent relative to the 8,701-node 3.14 tree | Every claimed minor installs, imports, collects the same node IDs, and runs its required behavioral lane |
| Eager package barrels amplify cycles | Cold core/navigation leaf imports load 118 Parcel modules and reach `navigation.pipeline`, simulator environments, MetaUrban, and InstructNav | Leaf imports have forbidden-edge tests; production code consumes leaves, not barrels |
| Semantic navigation admission remains structurally fragile | The narrow mitigation currently holds (`_HAS_INSTRUCTNAV=True`; 10 import-order tests pass), but eager barrels and product soft-capability branches remain | Required capability admission is explicit and startup-fatal; a real semantic mission is exercised |

## Current assessment, including dirty `main`

**Verdict:** promising R&D platform, **release-red**, integrated maturity **L2
simulator/development**, and physical companion maturity **L0-L1**. The dirty wave
improves isolated mechanisms; it does not create a synchronized physical
sense-localize-plan-act loop or raise procurement readiness for immediate autonomy.

### Evidence recorded in this reassessment

| Check | Current result | What it proves |
|---|---|---|
| CPython 3.14 collection | 8,701 nodes in 2.51 s | Current inventory only; not a suite verdict |
| Dirty P1/P2 focused suite | 528 passed, 8 skipped, 1 expected failure in 7.20 s | Strong component-level software evidence; live camera/owner/hardware rows remain absent |
| CI-runner and import-order tests | 55 passed, 1 warning | Narrow runner/import regressions hold; they do not make the aggregate hermetic |
| Ruff ratchet | PASS: 7 grandfathered findings, 0 new | Current lint ratchet is not adding debt |
| RealSense-dependent committed probes | 3 failed, 4 passed | Tests are coupled to the old assumption that the sanctioned optional SDK is absent |
| Clean tracked-only archive | Unhandled missing-Go2 `ValueError`; no final report/JSON | Release truth remains unavailable |
| Full current default suite | Not completed green | No full-suite claim is admitted |

### Executive recommendation

1. **Freeze feature promotion, not feature preservation.** Keep the dirty work and
   its evidence intact, but do not merge it wholesale or call any card a product
   capability merely because its local mechanism is complete.
2. **Close GATE-0 / IG-1 and IG-2 first.** Hermetic assets, per-stage exception
   containment, the Python contract, deterministic dependency identity, and the
   optional-SDK test correction are the prerequisites for every later denominator.
3. **Fix package boundaries before splitting the god objects.** Thin the eager
   barrels and make required capability admission explicit before decomposing the
   13,132-line runtime or 6,604-line navigation coordinator.
4. **Integrate the dirty wave as vertical, atomic slices.** Tracked files already
   import untracked `owner_model` modules; a partial commit can create an
   unimportable repository. Each slice must contain producer, composition,
   configuration, tests, rollback, and its exact evidence boundary.
5. **Promote physical truth in order:** physical camera and provenance; synchronized
   observation; localization/SLAM and transforms; owner identity; native sole-writer
   Unitree gateway; measured stopping; then bounded companion missions.
6. **Do not spend simulator margins as physical margins.** The prototype 0.70 m
   person band is simulator policy, not a commissioned Go2 stopping result. No
   source/config/status text may describe it as physical proof until body trials
   measure the complete sensor-to-stop tail.

## Today’s consolidated priority checklist

### P0 — must close or remain explicitly red today

- [ ] Capture an immutable inventory: HEAD/origin SHA, complete dirty path list,
  tracked/untracked dependency edges, Python/dependency identities, asset revision,
  and the exact commands/results in the table above.
- [ ] Execute GATE-0 / IG-1: tracked manifest-pinned Go2 MJCF closure, independent
  stage containment, valid JSON on red, and clean-archive proof.
- [ ] Execute the protocol/Python part of IG-2: fix the dataclass default, settle
  the supported range and voice dependency split, and make every claimed minor
  import/collect the same node IDs.
- [ ] Execute ENV-1: rewrite the seven capture probes around device absence and
  import discipline instead of assuming `pyrealsense2`/`cv2` are not installed.
  Seed the old assumption red; retain the three currently reproduced failures as
  evidence until the corrected tests pass.
- [ ] Execute IG-3: thin package initializers, leaf imports, forbidden-edge tests,
  and startup-fatal admission for required navigation capabilities.
- [ ] Run IG-4 from a truly fresh checkout and hosted Actions. If that cannot
  complete today, record the unchecked rows and leave release/procurement red.

### P1 — prepare today; implement only after the P0 denominator is trustworthy

- [ ] Produce an atomic commit graph for P1-A through P2-B. For every tracked file
  that imports an untracked package, put both in the same slice or remove the
  dependency. Never use `git add .` on this worktree.
- [ ] Add regression specifications for the two newly confirmed composition bugs:

  - a physical `CameraDetectionFrame` must remain `physical` through
    `observations_from_frame` and must be refused by a simulation-stamped map;
  - navigation may never construct, warm, or invoke a VLM on the 10 Hz control
    thread, and an ASK verdict must reach the interaction layer without granting
    motion.

- [ ] Mark all task-16 through task-27 cards as **planned specifications**, not
  implemented capability, until code, default wiring, and exit evidence exist.
- [ ] Correct dirty source/config/status wording that calls the 0.68/0.70 m
  simulator derivation a physically measured Go2 stop. Preserve the calculation as
  a provisional software bound and name all unmeasured terms.

## Today’s execution model

- [ ] Run IG-1, IG-2, and IG-3 concurrently in isolated worktrees with one owner
  each; keep one integrator responsible for workflow conflicts and merge order.
- [ ] Timebox baseline/preregistration to 30 minutes, implementation lanes to four
  hours, integration/focused regression to one hour, and clean/hosted evidence to
  two hours.
- [ ] If staffing or hosted CI cannot finish the whole sequence today, leave the
  release/procurement gate explicitly red and carry the unchecked exit row forward.
  Do not manufacture same-day closure by narrowing tests, support, or evidence.

## End-of-day outcome

Close the integrity wave only when all of these statements are evidenced:

- [ ] A fresh clone already contains the manifest-pinned Unitree Go2 asset subset
  required by the tracked scenes and runs
  `scripts/ci_gate.py --tier commit --json` without an unhandled traceback.
- [ ] Every gate produces a named result and the final text/JSON report is emitted
  even when an earlier gate is deliberately faulted.
- [ ] Every supported Python version imports the product, collects the same test
  node set, and completes its assigned CI lane without collection errors.
- [ ] Importing a navigation or core leaf does not eagerly import
  `navigation.pipeline`, simulator environments, or the InstructNav package.
- [ ] Product startup refuses semantic-navigation admission if required modules are
  unhealthy; it cannot start green with `_HAS_INSTRUCTNAV=False`.
- [ ] A clean-clone local run and a hosted GitHub Actions run are green, with logs
  and exact dependency/Python identities retained.

## IG-0 — Protect the evidence base · 30 minutes · integrator

- [ ] Record `git rev-parse HEAD`, `git status --short`, active processes, Python
  version, and the ignored Unitree checkout revision before editing.
- [ ] Preserve the current owner work. Do not use `reset`, `restore`, `checkout --`,
  stash, or broad cleanup against the shared worktree.
- [ ] Freeze lane ownership before dispatch:

  | Lane | Owns |
  |---|---|
  | IG-1 / integrator | Minimal tracked `third_party/unitree_mujoco` Go2 pack and provenance, `.gitignore`, `.gitattributes`, `unitree-assets`, `scripts/ci_gate.py`, CI/scene tests, `.github/workflows/ci.yml`, `README.md:365–405`, `docs/CI.md`, and `docs/DEPENDENCIES.md` |
  | IG-2 | `src/parcel_robot/realtime/protocol.py`, `pyproject.toml`, Python/realtime compatibility tests, support/dependency text handed to the IG-1 docs/workflow integrator |
  | IG-3 | Package initializers, `navigation/pipeline.py`, the relevant `runtime.py`, `skills/api.py`, and `voice/amendment.py` boundaries, capability admission, and import-graph tests; no unrelated navigation behavior changes |
  | IG-4 | Read-only independent clean-clone/hosted verification and evidence returned to the integrator; the integrator alone pushes and writes final status |

- [ ] Pause merges from active feature lanes into the integrity branch until IG-4
  records the exact tree it verified.

**IG-0 exit:** every changed path has one owner, the starting tree is recorded, and
the owner’s in-flight changes are recoverable.

## IG-1 — Make CI hermetic and failure-complete · 2–3 hours

### Provision the simulator dependency

- [ ] Use one deterministic strategy at the path already referenced by the scenes:
  `third_party/unitree_mujoco`.
- [ ] Vendor only the Go2 MJCF payload Parcel consumes: upstream `LICENSE`,
  `go2.xml`, `scene.xml`, and the 16 referenced OBJ assets, plus one tracked
  `PROVENANCE.json`—20 files (about 28 MB), not the 296 MB checked-out worktree
  (372 MB with its nested `.git`). Keep the existing paths so scene bytes and
  frozen hashes do not move.
- [ ] Pin provenance to reviewed upstream commit
  `ae6a8403e272733e9996ef59990880330496177f`. The manifest records upstream URL,
  revision, relative path, byte size, and SHA-256 for every payload. Retain the
  BSD-3 license. Never track the nested clone’s `.git` metadata or a gitlink.
- [ ] Validate `PROVENANCE.json.upstream_revision` against an independently pinned
  expected-revision constant. A self-consistent replacement manifest and asset set
  at another revision must still fail.
- [ ] Do not use a submodule or CI download for this pack: checkout must contain
  every runtime asset and the gate must remain independent of network/upstream
  availability. Treat packaging the assets inside an installed wheel as a separate
  follow-up; this lane proves source-checkout and hosted-CI hermeticity.
- [ ] Replace the broad/misleading `third_party/` ignore rule with intentional rules
  that expose exactly the manifest-pinned pack while all unrelated third-party files
  remain ignored. Mark OBJ files as binary in `.gitattributes`.
- [ ] Make both workflow jobs consume the tracked pack without a Unitree fetch or
  bootstrap step.
- [ ] Add `tests/test_unitree_asset_pack.py` and a hard `unitree-assets` stage before
  `hard-safety`. It verifies parent-repository tracking, exact manifest closure,
  safe relative paths, no `.git`, sizes/hashes/license, and real MuJoCo compilation
  of all eight relevant scenes: flat, both product cities, and five generated
  validation scenes. At minimum the tracked product scenes include:

  - `src/parcel_robot/scenes/city_block.xml`
  - `src/parcel_robot/scenes/city_block_b.xml`

### Make the runner report every failure

- [ ] Make `unitree-assets` a named hard `GateResult` before live simulation and
  before `hard-safety`; do not maintain a second overlapping preflight name.
- [ ] Wrap each gate stage independently. Convert unexpected exceptions into an
  `ERROR` result containing the exception type and bounded diagnostic; do not let
  one stage bypass summary/JSON generation or all later independent checks.
- [ ] Catch `Exception`, never `BaseException`, so `KeyboardInterrupt` and operator
  cancellation still propagate. Retain a top-level fallback that emits a valid
  `gate-runner` error through a separately tested minimal serializer if assembly or
  normal rendering fails; the fallback must not reuse the failed reporting path.
- [ ] Preserve a nonzero process exit whenever any hard gate is `FAIL` or `ERROR`.
- [ ] Add seeded tests proving:

  - missing Go2 assets produce a named hard-red `unitree-assets` result, not a
    traceback;
  - malformed scene XML produces a named hard-red result;
  - a deliberately exploding first evaluator does not prevent later
    `release-parity` and `default-suite` stages from reporting;
  - JSON is valid and complete on both green and red runs;
  - the wrong Unitree revision is rejected before simulation;
  - a removed/tampered OBJ, unmanifested file, absolute/`..` manifest path, and
    same-named ignored-but-untracked asset each produce a specific hard failure;
  - `KeyboardInterrupt` is not swallowed.
- [ ] Remove the four asset-absence skips in the simulator/dynamic-city tests and
  replace the scene-assets escape with manifest-backed validation. Preserve all
  frozen collision, inertia, obstacle, evaluator, and scene hashes—zero re-pins and
  zero scene XML edits.
- [ ] Update the README and `docs/CI.md` to distinguish this tracked minimal MJCF
  pack from the full developer simulator checkout and document the new hard stage.

### IG-1 verification

```bash
test "$(git ls-files 'third_party/unitree_mujoco/**' | wc -l)" -eq 20
test ! -e third_party/unitree_mujoco/.git
.parcel/bin/python -m pytest -q tests/test_unitree_asset_pack.py tests/test_ci_gate.py tests/test_sim.py tests/test_dynamic_city.py tests/test_scene_assets.py
.parcel/bin/python scripts/ci_gate.py --tier commit --json
```

**IG-1 exit:** exactly 20 asset-pack files and zero nested repository metadata are
parent-tracked; a tracked-only fresh checkout compiles all eight scenes and reaches
the test-suite stage; former asset skips are required passes; and deleting/tampering
with the pack in a scratch clone yields a complete hard-red report rather than an
unhandled exception. This does not claim wheel or hardware qualification.

## IG-2 — Make the Python contract true · 4–8 hours, parallel with IG-1

- [ ] Replace the shared dataclass default in `RetainedEvent.fields` with a factory,
  for example a named function returning `MappingProxyType({})` via
  `dataclasses.field(default_factory=...)`.
- [ ] Add a regression test that imports `parcel_robot.realtime.protocol`, creates
  two default `RetainedEvent` instances, and proves the defaults are distinct,
  immutable empty mappings.
- [ ] Preserve Python 3.10 because Ubuntu 22.04 / ROS 2 Humble is the documented
  hardware path. Make the upper support boundary explicit rather than leaving an
  untested open-ended claim: set `requires-python = ">=3.10,<3.15"` and describe
  the tested claim specifically as CPython 3.10–3.14.
- [ ] Scope today’s claim to base/dev plus voice dependency resolution and offline
  WebSocket/gateway contracts. Exclude the `perception` extra: its current
  `onnxruntime-gpu>=1.28` floor requires Python 3.11+, the only measured proof is
  the present x86_64 Python-3.14/CUDA host, and the 1.28 PyPI release has no Linux
  aarch64 wheel. This is not currently a declared Jetson/Orin install path on any
  Python minor.
- [ ] Split the voice dependency by interpreter using PEP 508 markers:
  `websockets>=16.1.1,<17` on Python `<3.11` and `websockets>=17,<18` on Python
  `>=3.11`. Update the pin-contract test and run the real loopback transport/audio
  gateway tests against both dependency branches.
- [ ] Do not use `requirements-lock.txt` as cross-Python evidence; it is a Python
  3.14 snapshot and is incomplete. Its NumPy 2.5.1 pin requires Python 3.12 and
  rejects 3.10/3.11; its websockets 17.0.1 pin rejects 3.10.
- [ ] Provision the native PortAudio runtime in compatibility jobs and explicitly
  import `sounddevice`, `msgpack`, and `websockets`; `pip check` alone cannot detect
  a missing native library. Hosted CI still does not qualify microphone/speaker
  hardware or opt-in live-provider behavior.
- [ ] Keep the canonical commit/nightly gate on 3.12 and add a required,
  `fail-fast: false` compatibility matrix for 3.10, 3.11, 3.13, and 3.14. Every
  claimed minor must:

  1. perform a non-editable `python -m pip install ".[dev,voice]"` from a fresh
     checkout, or build and install the wheel;
  2. run `pip check`, record the resolved NumPy/websockets versions, and assert
     CPython 3.10 resolved `16.1.1 <= websockets < 17` while 3.11–3.14 resolved
     `17 <= websockets < 18`;
  3. import `parcel_robot.runtime`, `parcel_robot.realtime.protocol`, the CLI, and
     the web panel;
  4. run `pytest --collect-only` with zero collection errors;
  5. publish the sorted collected node IDs;
  6. run the full default non-slow behavioral suite. The artifact/digest/evaluation
     wrapper may remain once on the canonical 3.12 lane to control CI cost.

- [ ] Diff node-ID artifacts across versions. Any missing node is hard-red. A
  reviewed version-specific skip must preserve its node ID and be reported
  separately; it does not justify a lower collected set.
- [ ] Do not use `--continue-on-collection-errors` and do not turn import errors into
  skips.
- [ ] Make every compatibility lane a required branch-protection check, not an
  advisory job. Create one stable aggregate status dependent on every matrix child;
  a repo admin must add it to the ruleset/branch protection and retain an API record
  or screenshot as closeout evidence. Hand the IG-1 integrator text for
  `docs/CI.md` covering the support matrix/cadence and
  `docs/DEPENDENCIES.md` with the websockets split, lock-file scope, and perception
  exception.

### IG-2 verification

```bash
python -c "import parcel_robot.runtime; import parcel_robot.realtime.protocol"
python -m pytest --collect-only -q
python -m pytest -q tests/test_realtime_protocol.py tests/test_realtime_ws_transport.py tests/test_realtime_audio_gateway.py tests/test_realtime_pump_survival.py
```

**IG-2 exit:** base/dev plus offline voice contracts install with `pip check`, native
imports, identical node-ID sets, and the default suite on CPython 3.10–3.14; the
protocol/loopback tests pass on both asserted websockets branches; the 3.12 commit
gate stays green; hosted URLs prove every required check; and branch protection
requires the aggregate. A failing minor leaves IG-2 red. Lowering the 3.10 floor
requires a separate approved ROS/Humble deployment decision, not an IG-2 fallback.
Perception and physical audio remain explicitly separate hardware qualifications.

## IG-3 — Remove the eager barrel cycle amplifier · 3–4 hours

### Thin package initialization

- [ ] Make these initializers side-effect-light:

  - `src/parcel_robot/navigation/__init__.py`
  - `src/parcel_robot/navigation/envs/__init__.py`
  - `src/parcel_robot/core/__init__.py`
  - `src/parcel_robot/instructnav/__init__.py`

- [ ] Internal production code imports symbols from their leaf modules. Preserve
  necessary public compatibility with a small lazy `__getattr__` export map only if
  callers cannot migrate today; retain the prior `__all__`, add `__dir__`, and put
  static-analysis-only imports behind `TYPE_CHECKING`. Do not eagerly rebuild the
  barrel.
- [ ] Migrate every production `src/` barrel consumer to a leaf import, including
  the runtime composition imports and the `skills/api.py` navigator import. Tests
  may use a barrel only to verify the supported public API.
- [ ] Do not import environments, MuJoCo, `navigation.pipeline`, realtime, or the
  entire InstructNav ladder merely to import a leaf safety/type module.
- [ ] Move the historical frozen-bundle compatibility path out of the product
  composition. A missing required product module is startup-fatal, not an optional
  semantic-navigation mode.

### Make capability admission executable

- [ ] Replace the product’s `_HAS_INSTRUCTNAV` soft-degrade decision with explicit
  composition/admission. If the flag must remain for legacy tools, confine it to
  those tools and keep it unreachable from the product launcher.
- [ ] Make the composition root assert all required semantic-navigation health
  fields before accepting navigation configuration.
- [ ] Split optional dialogue clarification (`voice.amendment`) out of the giant
  InstructNav import guard. If it is absent, use the deterministic clarification
  fallback; its absence must not disable grounding, memory, arbitration, scan, or
  search.
- [ ] A missing required grounding, arbitration, or memory capability produces a
  typed startup refusal naming the capability and original exception. Optional
  lock-on, verification, and route-memory capabilities are required exactly when
  their configuration enables them.
- [ ] Remove the incoherent path where `GroundingOutcome` becomes `None` and later
  code dereferences `GroundingOutcome.AMBIGUOUS`.

### Add structural regression tests

- [ ] Fresh-process leaf-import probes assert:

  ```text
  import parcel_robot.navigation.reactive_safety
    => navigation.pipeline NOT in sys.modules
    => navigation.envs NOT in sys.modules
    => parcel_robot.instructnav NOT in sys.modules

  import parcel_robot.core.input_health
    => parcel_robot.navigation NOT in sys.modules
    => navigation.pipeline NOT in sys.modules
  ```

- [ ] Keep the existing import-order matrix, extend it to every production
  first-mover, and assert all capability-health fields—not only
  `_HAS_INSTRUCTNAV`.
- [ ] Add an AST boundary gate that rejects production imports from the three
  barrels and rejects wildcard imports. Add compatibility probes proving each
  prior public `__all__` symbol still resolves to the same defining object.
- [ ] Record before/after fresh-process module counts. Current cold-import baseline
  is 118 Parcel modules for either `parcel_robot.core` or
  `parcel_robot.navigation`; enforce forbidden dependency edges as the durable
  contract rather than host-sensitive wall-clock timing.
- [ ] Seed a missing required module and prove startup fails loudly before a mission
  can be submitted.
- [ ] Seed a new cross-package cycle and prove the structural import tests fail.
- [ ] Run one semantic mission through the normal composition to prove the ladder
  executes rather than merely importing successfully.

### IG-3 verification

```bash
.parcel/bin/python -m pytest -q tests/test_import_order_no_cycle.py
.parcel/bin/python -c "import sys; import parcel_robot.navigation.reactive_safety; assert 'parcel_robot.navigation.pipeline' not in sys.modules"
.parcel/bin/python -c "import sys; import parcel_robot.core.input_health; assert 'parcel_robot.navigation' not in sys.modules"
```

**IG-3 exit:** critical leaf imports have no barrel fan-out, no production source
consumes a barrel, prior public exports remain compatible, optional clarification
cannot disable navigation, product startup cannot admit a disabled required
semantic ladder, and healthy semantic behavior is unchanged while a normal mission
demonstrably enters the real grounding/navigation path.

## IG-4 — Independent proof and closeout · 2 hours · after IG-1/2/3

- [ ] Create a genuinely fresh clone outside this workspace. Do not symlink or copy
  this workstation’s ignored `third_party`, caches, editable-install path, or pytest
  basetemp.
- [ ] Provision only through the tracked checkout/workflow mechanism.
- [ ] Install from scratch and record `pip freeze`, Python version, repository SHA,
  scene hashes, test node count, `PROVENANCE.json`’s pinned upstream revision, and
  the manifest’s own SHA-256.
- [ ] Run the full artifact/digest/evaluation commit gate in the clean clone once on
  canonical CPython 3.12. Run the assigned install/import/collection/default-suite
  compatibility lane on every claimed minor. Retain complete reports and node-ID
  artifacts.
- [ ] Run these adversarial controls in disposable clones/environments:

  - tracked asset pack absent;
  - manifest revision changed;
  - first hard evaluator raises;
  - Python 3.11 imports `RetainedEvent`;
  - required semantic module absent;
  - leaf imports tested before any package barrel is cached.

- [ ] Return signed/read-only verification evidence to the integrator. The
  integrator pushes the integrity branch and obtains an actual hosted GitHub
  Actions result; a local green run does not close hosted CI.
- [ ] Verify the hosted CPython-3.12 commit job emitted every commit-tier named gate.
  Verify each compatibility job published a sorted node-ID artifact matching the
  clean local collection; do not imply a compatibility job ran the full wrapper or
  that a commit job ran nightly-only gates.
- [ ] The integrator writes
  `scrum/20260822/INTEGRITY_GATES_STATUS.md` containing exact commands, pass/fail
  counts, workflow URL/run ID, ruleset evidence, revisions, seeded-RED evidence,
  deviations, and remaining limitations.

**IG-4 exit:** clean local and hosted evidence are green on the same commit. No
result depends on untracked/ignored assets or import order.

## Merge order and stop conditions

1. IG-1 dependency provisioning and runner containment.
2. IG-2 Python fix and matrix, integrated by the IG-1 workflow owner.
3. IG-3 barrel/admission refactor.
4. IG-4 clean-clone and hosted verification.

Stop and keep the integrity gate red if any of the following occurs:

- a required asset remains untracked, unpinned, or supplied from a developer cache;
- a supported Python lane has a different test set or collection error;
- a gate exception prevents final reporting or later independent checks;
- a product process can start with semantic navigation disabled;
- a leaf import loads `navigation.pipeline` through package initialization;
- evidence comes only from this dirty workstation;
- closing the gate would require weakening, deleting, skipping, or re-pinning a
  failing test without an independently reviewed behavioral reason.

## Dirty-wave integration queue — after IG-4

These rows are ordered promotion gates, not parallel claims that all dirty code is
ready. A row remains unchecked until its normal product path, failure path, and
evidence path all pass on a committed clean checkout.

### DW-0 — Make the dirty wave reviewable and recoverable

- [ ] Partition the wave into dependency-closed slices: P1-A camera/daemon, P1-B
  map writer, P1-C owner tracking, P1-D abstention/VLM, P1-E envelope, P2-A owner
  facts, and P2-B labels/affect/initiative.
- [ ] Record each slice's tracked and untracked files, imports, configuration,
  fixtures, test selection, feature default, rollback, and `does_not_prove` boundary.
- [ ] Rebase/reconcile only after the integrator proves no slice silently consumes
  another slice's uncommitted symbol. Tracked-only and slice-only archive imports
  must pass.
- [ ] Keep status records subordinate to executable evidence: “COMPLETE” means the
  named mechanism, not runtime composition, physical verification, or release.

**DW-0 exit:** every proposed commit imports and collects independently; no tracked
file relies on an omitted untracked package; rollback removes one capability without
breaking unrelated imports.

### DW-1 — VENUE-1 plus provenance-safe learned mapping

- [ ] Make `PARCEL_CAMERA_BACKEND=uvc|realsense|recorded` reach
  `RobotRuntime._attach_configured_camera_ingress`; physical venues must not import
  or initialize MuJoCo/EGL.
- [ ] Connect the detector daemon through the existing bounded `Detector` contract;
  daemon absence, restart, stale response, schema mismatch, and backpressure must be
  typed degraded states and must never block motion deadlines.
- [ ] Build the learned map only after the selected ingress declares its origin, or
  make map origin an explicit composition input. Never infer `simulation` merely
  because camera streaming is enabled.
- [ ] Derive every `MapObservation`'s origin from the frame and compare it against
  the map/store writer origin. Do not overwrite `frame.origin` with
  `learned.provenance` before the mixed-world guard.
- [ ] Seed a physical-frame/simulation-map mismatch and prove it is refused on the
  exact runtime product path. Add the inverse mismatch and replay/unknown cases.
- [ ] Run recorded replay first, then an attached D455/UVC live row with capture
  time, receipt time, calibration, drops, p50/p95/p99 age, and origin retained.

**DW-1 exit:** a selected physical camera drives the runtime without MuJoCo, frame
origin survives into the map, mixed venues cannot fuse, and loss/staleness yields an
observable HOLD/ASK rather than oracle fallback.

### DW-2 — Move VLM work out of the control loop and deliver ASK

- [ ] Mark the real control thread and add a fatal test if any VLM constructor,
  warm-up, inference, image encode, model load, disk read, or network call is reached
  from it.
- [ ] Run veto/naming in a bounded worker or daemon. Publish immutable verdicts with
  query/place/revision identity, model identity, capture time, result time, expiry,
  and contention outcome.
- [ ] Navigation consumes only a ready, matching, fresh verdict. Missing, stale,
  mismatched, or budget-declined verdicts produce ASK/HOLD according to policy and
  never synchronous inference or implicit admission.
- [ ] Wire `AbstentionVerdict.as_ask()` through the broker/conversation path; prove
  the question grants no resource lease or motion until the owner explicitly
  confirms a newly compiled task revision.
- [ ] Replace the naming k-consistency claim with an independent correctness judge.
  The current 18/40 naming result and two-of-two consistently wrong promotions stay
  hard evidence until the new gate rejects them.

**DW-2 exit:** worst-case VLM latency cannot delay the control tick; ASK is audible,
revision-safe, and non-actuating; a consistently wrong name cannot promote merely
by repeating.

### DW-3 — Close owner identity and durable-memory principal authority

- [ ] Construct `OwnerTracker` in the runtime from physical detections and an
  enrolled, calibrated gallery. Simulator mocap remains a simulator-only provider
  and must be unavailable in physical profiles.
- [ ] Replace raw confidence-only owner trust with typed identity state, calibrated
  similarity/margin, freshness, continuity, provenance, and ambiguity. Ambiguous,
  stale, uncalibrated, or absent identity yields HOLD and bounded give-up.
- [ ] Collect held-out owner/household-negative evidence across clothing, lighting,
  pose, occlusion, crossing, and days; report false-owner rate and ID switches, not
  only average recall.
- [ ] Decide and encode who may write durable owner facts. Until speaker/principal
  attribution is commissioned, unverified audio may request STOP and conversation
  but must not silently create consent-granted owner memory.
- [ ] Add an explicit confirmation path for pending consent and a production caller
  for `set_owner_fact_consent`; repeating `remember_fact` is not confirmation.
- [ ] Prove forget/export/delete across source rows, prompt notes, summaries,
  embeddings, indexes, caches, and derived artifacts. Label soft deletion honestly.

**DW-3 exit:** the running physical profile follows only a calibrated enrolled owner,
identity ambiguity stops motion, and durable memory has a verified human principal,
consent transition, and complete deletion story.

### DW-4 — Make indoor navigation geometrically executable

- [ ] Wire the authoritative obstacle/gate envelope into both production
  `GridPlannerConfig` construction sites; do not leave `gate_clearance_m=None`.
- [ ] Derive planner inflation and final safety from one immutable commissioned
  profile while retaining independent final recomputation and monotone restriction.
- [ ] Remove import-time follow/arrival standoff constants from profile-dependent
  behavior. Configuration changes must affect planning, following, arrival, and
  narration coherently.
- [ ] Add doorway/corridor scenarios at the proposed first-ODD widths and prove the
  planner neither proposes paths the final gate will always refuse nor relaxes the
  final gate to force progress.
- [ ] Keep the 0.70 m prototype band non-default and simulator-only until physical
  stopping trials measure velocity, latency, deceleration, pose/perception error,
  footprint, surface, battery, payload, controller state, and margin.

**DW-4 exit:** the robot can plan and execute representative first-ODD doorways in
simulation/replay with planner/gate agreement, and every physical clearance remains
uncommissioned until measured on the body.

### DW-5 — Build the physical estimation-control spine

- [ ] Define a backend-neutral synchronized observation containing sensor capture
  times, clock mapping, calibration/extrinsics, `map->odom->base_link` transforms,
  covariance/health, controller feedback, range/local map, dynamic tracks, owner
  belief, and evidence origin.
- [ ] Benchmark established odometry/localization/SLAM providers on identical bags;
  measure trajectory error, drift, transform age, loss, false relocalization,
  recovery, loop-closure jumps, compute, and restart behavior.
- [ ] Implement the native restart-disarmed sole-writer Unitree gateway with boot
  epoch, lease, sequence, TTL, local limits, watchdog, `Move`/`StopMove`, feedback,
  and stationary witness. Revoke robot-network write credentials elsewhere.
- [ ] Prepare the independent stop, tether/clearance area, trained operator,
  acceptance checklist, data capture, and hazard review before first motion.
- [ ] Commission read-only state, then axes/frame/modes, then minimum-speed one-axis
  motion, then stopping/fault campaigns. No semantic autonomy precedes these rows.

**DW-5 exit:** a physical profile cannot arm without healthy synchronized evidence
and a commissioned gateway; client death, expired authority, invalid state, and
operator stop independently produce verified zero motion.

## Procurement consequence

The Go2 EDU quote/vendor-compatibility work may continue in parallel. A D455/UVC
camera, capture compute, network equipment, and independent-stop hardware may be
procured as evidence-generating lab infrastructure. The Go2 purchase order remains
**HOLD for autonomy justification** until IG-4 closes on a clean, reproducible
commit and the lab/operator/acceptance plan is approved. If purchased earlier for a
commercial reason, it must be budgeted and labeled as supervised R&D equipment; no
Parcel-driven physical motion begins before the DW-5 commissioning prerequisites.
