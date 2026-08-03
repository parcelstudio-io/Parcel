# Habitat 2020 PointNav public-validation gate

This gate is the closest faithful Habitat evaluation Parcel can implement next
without changing production navigation behavior. It uses the archived Habitat
Challenge 2020 code and task contract, with all translation isolated under
`evals/external/`.

It is deliberately **not an official or leaderboard-comparable result**. The
[official results page](https://aihabitat.org/challenge/2020/) reports hidden
test-challenge rankings, while the historical EvalAI challenge is frozen and
inactive. Public `val_mini` or `val` results may be described only as
"official-code public-validation" results. They cannot satisfy the portfolio's
official rank-1 / SPL 0.21 PointNav target.

## Frozen contract

- Challenge source: `ddf1575532aecc4df2f4cd4c5db173b8eada3e1e`
- Archived base image:
  `fairembodied/habitat-challenge@sha256:761ca2230667add6ab241a0eaff16984dc271486ec659984ae13ccab57a9c52b`
- Public smoke split: 30 `val_mini` episodes in `Pablo.glb`
- Sensors: noisy 640×360 RGB-D, 70-degree HFOV, and a static polar PointGoal
  in the episode-start frame; no GPS/compass
- Embodiment: 0.18 m radius, 0.88 m height, noisy LoCoBot actions, no collision
  sliding, 500-step limit
- Actions: STOP, 0.25 m nominal forward, 30-degree left/right turns
- Success: explicit STOP within 0.36 m
- Metrics: distance-to-goal, success, SPL, and soft-SPL

The complete machine-readable contract, hashes, eligibility, and forbidden
inputs live in `habitat2020_manifest.json`.

## Archived image and GPU preflight

The image manifest and small image-config blob can be verified directly from
Docker Registry without Docker, image-layer downloads, a scene license, or a
simulator run:

```bash
.parcel/bin/python -m evals.external.habitat2020_image_preflight \
  --output evals/external/results/habitat2020/my-unique-image-preflight.json
```

The verifier accepts only the frozen digest endpoint. It checks the HTTP
content digest, raw manifest/config SHA-256 values, media types, platform,
ordered layer contract and compressed size, rootfs chain, archived CUDA 10.1
and Python 3.6 declarations, the challenge-2020 Habitat-Sim build marker, and
the host's NVIDIA GPU/device/CUDA/EGL prerequisites. The destination is
write-once and descriptor drift fails closed.

The measured 2026-08-03 run passed all 15 checks. It confirmed that the exact
23-layer, 3,210,119,745-byte compressed image remains retrievable and that the
RTX 5000 Ada (compute capability 8.9, driver 595.84) exposes the required host
device nodes and libraries. It intentionally downloaded zero image-layer
bytes and executed no container, GPU kernel, render, scene, policy, or
evaluator. By itself, that preflight established no archived-runtime
compatibility and no navigation metric or rank. Its canonical evidence SHA-256 is
`ad8b46967f43215377468ce967bfbd3f15fd7dc6199600983229bf79dd592cee`.

The follow-on cache-only runtime work materialized all 23 layers and inventoried
87,944 entries, including 7,925,803,803 regular-file bytes. Baseline01 preserved
a useful failure: CUDA initialized one device, but EGL could not load because a
host GLVND client required GLIBC 2.33. Corrected baseline02 used the image's
GLIBC-2.27-compatible GLVND clients, initialized one CUDA device and one EGL 1.5
device, and imported Habitat-Sim 0.1.4 under Python 3.6.10 in 561.432697 ms. The
passing report SHA-256 is
`be4a6acba149bee47661936ee5a90947b39e22313a411f02d17eeff839c49424`,
its runner SHA-256 is
`4526fdcc3a66864a5792a188a387c7ef27ebe4c3258f92472113cf945e60607c`,
and its ledger ID is
`habitat20-oci-gpu-import-smoke-20260803T145414Z`. This is a no-dataset import
smoke only: it constructed no simulator, loaded no scene, rendered nothing,
executed no GPU kernel or navigation episode, ran no evaluator, and emitted no
metric or rank.

The next bounded tier has also completed using the separate public test-asset
contract. A network-disabled, read-only Bubblewrap run constructed Habitat-Sim,
loaded the Skokloster scene and navmesh, rendered four distinct 128×128 RGB-D
frames, and executed `move_forward`, `turn_left`, and `turn_right` with zero
collisions and 0.2500881936561302 m displacement. It passed in 1,318.900083 ms;
the report SHA-256 is
`aed6afcb2e9af98f4f6ed8c3a3f636845e70a34b14057b1904493f8530330137`
and ledger ID is
`habitat-test-assets-gpu-scene-smoke-20260803T152317Z`. It used only episode
0's start transform and did not read its goal, execute Parcel's policy, run a
navigation episode/evaluator, or emit a metric.

Habitat-Sim separately publishes the `habitat_test_scenes` and
`habitat_test_pointnav_dataset` download targets without a credential or
click-through dataset-acceptance step. They are the only appropriate real
scene assets for this non-gated renderer/action compatibility smoke. They are
**not** the frozen challenge's Gibson `Pablo.glb` `val_mini` scene/episodes and
must never be substituted to report Habitat 2020 SR, SPL, soft-SPL, rank, or
top-decile evidence. This distinction is frozen in
`habitat2020_manifest.json`.

The selected scene repository is public and ungated but explicitly
CC-BY-NC-4.0; it is not unlicensed or public-domain. The exact source, hashes,
preparation rules, and measured result live in
[`HABITAT_TEST_ASSET_SMOKE.md`](HABITAT_TEST_ASSET_SMOKE.md).

## Readiness doctor

The doctor performs no install, pull, or dataset download:

```bash
.parcel/bin/python -m evals.external.habitat2020_doctor
```

It exits with status 2 until every required item is present. Use
`--allow-blocked` only for inventory jobs that intentionally collect a blocked
report. Checks include the immutable source commit, official config/episode
hashes, episode shape, licensed scene, NVIDIA GPU, Docker, NVIDIA Container
Toolkit, exact image digest, Python 3.6 bridge grammar, and modern Parcel
sidecar availability. Nothing silently falls back to a different image,
dataset, device, or simulator.

The Gibson scene is user-gated. Accept the
[Gibson research terms](https://github.com/StanfordVL/GibsonEnv/blob/master/gibson/data/README.md)
and place the Habitat-format scene at:

```text
.cache/external-evals/repos/habitat_challenge_2020/
  habitat-challenge-data/data/scene_datasets/gibson/Pablo.glb
```

Do not automate acceptance, commit the asset, or copy it into container layers.
Mount licensed datasets read-only.

## Public artifact contract smoke

The public smoke requires neither the licensed scene nor a container runtime.
It reads and verifies all 30 episode identifiers from the pinned `val_mini`
archive, starts the unchanged Parcel navigation config through the real JSONL
subprocess boundary, and sends one deterministic synthetic RGB-D/PointGoal
contract frame per episode:

```bash
.parcel/bin/python -m evals.external.run_habitat2020_contract_smoke \
  --output evals/external/results/habitat2020/my-unique-run.json
```

The destination is write-once: the command fails if it already exists. The
report hashes the archived source/config/episodes, bridge, sidecar, Parcel
Python tree, navigation config, and selected model declaration. It also records
the full-evaluator GPU/runtime blockers. Synthetic frames are clearly labeled,
and the runner emits no success, SPL, soft-SPL, or collision metric. A passing
result proves adapter/provenance compatibility only; it is not a simulator run.

The 2026-08-03 baseline exercised all 30 public episode identifiers through the
real subprocess boundary with ten `MOVE_FORWARD`, ten `TURN_LEFT`, and ten
`TURN_RIGHT` outputs. Its report SHA-256 is
`12d361fcb5e1d210ce4a86efe6763cd4af875ce7f27a75a13d8088260496a6a2`;
the report also pins the runner itself as
`f626b6d6bca04c622c832f27693b5149c92f7792f2b6d76265d95059fc0bfb3d`.

## Adapter boundary

The archived process runs Python 3.6, while Parcel requires modern Python. The
bridge therefore uses a strict versioned JSON-lines sidecar contract:

1. `habitat2020_py36_bridge.py` runs inside the archived evaluator.
2. It converts the static PointGoal to a local metric goal.
3. It projects the calibrated depth-camera horizon to a uniform planar scan.
   Saturated depth becomes a no-return ray rather than a phantom obstacle.
4. Pose is estimated only from the bridge's history of issued discrete actions.
   Official actuation noise intentionally causes drift; no simulator pose is
   queried to correct it.
5. `habitat2020_sidecar.py` supplies those observations to the unchanged Parcel
   `DirectiveNavigator` and returns its mid-level command.
6. The bridge maps forward/yaw commands to the official discrete actions. It
   fails if Parcel requests reverse or lateral motion because hiding an
   unsupported command would change controller behavior.

The adapter never receives simulator agent state, navmesh, geodesic distance,
shortest path, collision truth, episode world goal, or evaluation metrics.
RGB presence is recorded but the current geometric controller consumes the
depth-derived scan; a future visual-localization model must be a separately
provenanced policy change.

## Container path

The exact 23-layer rootfs is now materialized and fully inventoried. A
cache-only Bubblewrap route recomputed that inventory, injected only ABI-audited
NVIDIA vendor libraries, and passed the corrected no-dataset CUDA/EGL/import
smoke. Docker Engine and NVIDIA Container Toolkit were not required for this
narrow result. It proves that the archived CUDA/EGL/Habitat-Sim userspace can
reach its import boundary on this Ada GPU; it does not prove simulator
construction, scene loading, rendering, action execution, or evaluator
compatibility.

That public-test-asset simulator/render/action smoke is now complete and remains
separate from Habitat 2020 scoring. For a frozen public-validation run, keep the
archived Habitat Python 3.6 evaluator and modern Parcel sidecar boundary,
disable networking, mount only the user-supplied licensed challenge data
read-only, and never mount a container socket. The missing `Pablo.glb`
asset—not runtime, EGL, scene construction, or basic rendering/action
compatibility—is now the immediate gate to the 30-episode `val_mini` protocol.

Before any scene run, the public artifact smoke uses synthetic NumPy
RGB-D/PointGoal frames and the actual configured Parcel controller. Unit tests
also isolate malformed frames with a fake controller. After the asset is
supplied:

1. Run all 30 `val_mini` episodes as an integration smoke test.
2. Download and hash the public PointNav Gibson-v2 episode archive and run the
   complete public `val` split.
3. Record challenge/image/config/dataset/adapter/Parcel hashes, ordered episode
   IDs and seeds, GPU/driver, action counts, SR/SPL/soft-SPL/distance, and
   adapter/controller latency.
4. Keep `official_rank_eligible=false` in every report and ledger record.

ObjectNav comes later: it additionally requires the licensed Matterport3D
scene set and a real RGB-D category-perception policy. Simulator semantic truth
must not be substituted for perception.
