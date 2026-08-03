# Habitat test-asset exact-runtime smoke

This gate advances the archived Habitat runtime exactly one tier beyond import:
simulator construction, a real scene/navmesh load, RGB-D rendering, and three
discrete simulator actions. It is deliberately **not Habitat Challenge 2020**,
does not use Gibson `Pablo.glb`, and cannot emit SR, SPL, soft-SPL, a rank, or
top-decile evidence.

## Public access and provenance decision

The decision to materialize these assets is bound to primary, frozen sources:

- Habitat-Sim's official data utility at commit
  [`57ee4941dc4765240f0f91f70b2c97a919bf9038`](https://github.com/facebookresearch/habitat-sim/blob/57ee4941dc4765240f0f91f70b2c97a919bf9038/src_python/habitat_sim/utils/datasets_download.py)
  defines both `habitat_test_scenes` and `habitat_test_pointnav_dataset`. Neither
  entry sets `requires_auth`; the source file SHA-256 is
  `54bef3d4fbc3a38898cb02ac62897fc47d4b677af15bd80e5aab0c33cabb4cf1`.
- The matching frozen
  [`DATASETS.md`](https://github.com/facebookresearch/habitat-sim/blob/57ee4941dc4765240f0f91f70b2c97a919bf9038/DATASETS.md)
  calls both downloads unit-test assets. Its SHA-256 is
  `86b46339f61dbff6cf7bb0b5ad22693d68412cb0607a207fe835e22c9112d5ed`.
- The selected scene comes from AI Habitat's public, ungated
  [`habitat_test_scenes`](https://huggingface.co/datasets/ai-habitat/habitat_test_scenes/tree/910c783fb954da8497ea5f811b843a76590ddddc)
  repository at commit `910c783fb954da8497ea5f811b843a76590ddddc`.
  Its frozen dataset card identifies the license as **CC-BY-NC-4.0**. These
  assets are therefore non-gated, not unlicensed or public-domain.
- `skokloster-castle.glb` is bound to its Git-LFS SHA-256
  `b14e29e17f5e31d86a1002eefd77b7d345b265006481739ae480a847e6623f56`
  and exact 38,295,764-byte size. Its navmesh SHA-256 is
  `1a9a5bd123af8001f0ea2c5c8d326cb3fd39808ca771fc766856af8f0772391d`.
- The official PointNav test archive is anonymously readable from
  [`dl.fbaipublicfiles.com`](https://dl.fbaipublicfiles.com/habitat/habitat-test-pointnav-dataset_v1.0.zip).
  Parcel freezes its 894,623-byte size, SHA-256
  `4ddf3403507c6ea44add9e375134d3564219f4376d11b16ed3efe16245a167d7`,
  ETag `84fca7fb97f795edb6359da2a70b7df5`, and S3 version ID
  `QCCAJG7xsyn5iPGhQYpa0aGeBkrsZl2g`. The ZIP carries no separate license
  file, so Parcel makes no broader redistribution or public-domain claim for
  it; it remains ignored local test-fixture metadata.

The complete machine-readable contract is
`habitat2020_test_assets_manifest.json`, SHA-256
`3912404b7a170754a737cc2b257f6cadbd0b40e0f14f7d32e7f4454c41a969bc`.
Changing any URL, source commit, path, size, hash, license/access flag, fixture
selection, action, or eligibility boundary creates a different cache identity.

## Fail-closed preparation

The default command is offline inspection. Preparation requires the exact
bundle ID:

```bash
PYTHONPATH=. .parcel/bin/python -m evals.external.habitat2020_test_assets

PYTHONPATH=. .parcel/bin/python -m evals.external.habitat2020_test_assets \
  --prepare \
  --confirm-bundle-id habitat-test-assets-compat-v1
```

The downloader accepts only HTTPS retrieval, constrains redirect hosts, bounds
every response by its frozen size, verifies every SHA-256 before publishing,
checks the PointNav object ETag/version ID, rejects ZIP traversal, duplicate
members, and symlinks, and extracts only the three declared gzip members. It
then verifies the exact file set and the selected `(scene_id, episode_id)` pair.
It refuses to replace an invalid or changed cache.

Episode IDs repeat across test scenes, so the fixture is selected by the exact
pair `("data/scene_datasets/habitat-test-scenes/skokloster-castle.glb", "0")`.
The smoke reads only its start transform. It does not read the goal or recorded
geodesic distance.

## Isolated smoke contract

```bash
PYTHONPATH=. .parcel/bin/python -m evals.external.habitat2020_test_assets \
  --smoke \
  --confirm-bundle-id habitat-test-assets-compat-v1 \
  --confirm-image-digest sha256:761ca2230667add6ab241a0eaff16984dc271486ec659984ae13ccab57a9c52b \
  --output evals/external/results/habitat2020/my-unique-test-asset-smoke.json
```

Before execution, the runner rehashes all 23 compressed image layers, the full
87,944-entry rootfs inventory, every asset, and the fixture archive. Bubblewrap
then mounts the rootfs and asset tree read-only, exposes only allowlisted GPU
devices and ABI-audited NVIDIA vendor libraries, creates fresh `/proc`, `/dev`,
and `/tmp`, and disables networking. It executes the fixed Python 3.6 probe,
not an image entrypoint, shell, package manager, Habitat-Lab task, evaluator, or
Parcel policy.

The probe initializes CUDA and EGL first, constructs Habitat-Sim 0.1.4, loads
the Skokloster scene and navmesh, renders 128×128 color and depth frames, and
executes `move_forward`, `turn_left`, and `turn_right`. `STOP` is a Habitat-Lab
task action rather than one of these Habitat-Sim locomotion actions and is not
executed. No goal-directed navigation episode occurs.

## Measured baseline01

The first immutable run passed:

- Report: `habitat-test-assets-gpu-scene-smoke-20260803-baseline01.json`
- Report SHA-256:
  `aed6afcb2e9af98f4f6ed8c3a3f636845e70a34b14057b1904493f8530330137`
- Ledger ID: `habitat-test-assets-gpu-scene-smoke-20260803T152317Z`
- Ledger record SHA-256:
  `eabe69ab5249ed253b63d1c611e08b8f61ec12b4d27bc2b31c3f70cb6c9b5f0b`
- Runner SHA-256:
  `54d3c8567530da1ca055c1343acc9aa88ba5c45149733fcbd076b65b041cc1aa`
- Probe SHA-256:
  `60c953db9f7e9848669dd8846f1147561a24eb27f1e817ee7421785cfdc2743f`
- Isolated-process elapsed time: 1,318.900083 ms
- CUDA: initialization passed, one device
- EGL: initialization passed, one device, version 1.5
- Habitat-Sim: version 0.1.4 under Python 3.6.10
- Scene/navmesh: both loaded
- Rendering: four distinct 128×128 RGB-D frames; every depth frame had 16,384
  positive pixels
- Actions: forward, left, right; zero collisions; 0.2500881936561302 m final
  displacement

This result proves only the exact archived-image, public-test-asset
simulator/render/discrete-action boundary. It did not execute Parcel's policy,
read a PointNav goal, run a navigation episode or evaluator, calculate a metric,
use Gibson data, or establish Habitat 2020 score or rank compatibility.
