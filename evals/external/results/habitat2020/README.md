# Habitat 2020 compatibility evidence

These reports are immutable, rank-ineligible compatibility artifacts. They do
not contain Habitat navigation metrics. The latest artifact loads only a public
test scene for rendering/action compatibility—not Gibson `Pablo.glb` or a
Habitat navigation evaluator.

The public-test-asset source, license/access boundary, downloader contract, and
measured scene smoke are documented in
[`HABITAT_TEST_ASSET_SMOKE.md`](../../HABITAT_TEST_ASSET_SMOKE.md).

| Report | Status | Scope | Report SHA-256 | Note |
| --- | --- | --- | --- | --- |
| `habitat20-contract-smoke-20260803-baseline01.json` | pass | 30/30 public episode IDs | `84d6acab1ace6b75e60c61fdb8d77116801e1b786b795c99e15a8e875552aaf7` | First write-once run; retained as history. |
| `habitat20-contract-smoke-20260803-baseline02.json` | pass | 30/30 public episode IDs | `12d361fcb5e1d210ce4a86efe6763cd4af875ce7f27a75a13d8088260496a6a2` | Canonical baseline; additionally records the runner hash and validates unique episode IDs. |
| `habitat20-image-registry-gpu-preflight-20260803.json` | pass | exact archived image descriptor + host GPU prerequisites | `950879126fbe635bec3ace0454278bbefe16face4c7e90d84861f8ff49cd6bdf` | First registry/GPU preflight; retained as immutable history. |
| `habitat20-image-registry-gpu-preflight-20260803-baseline02.json` | pass | exact archived image descriptor + host GPU prerequisites | `ad8b46967f43215377468ce967bfbd3f15fd7dc6199600983229bf79dd592cee` | Canonical run after freezing the official non-terms-gated test-asset distinction in the manifest. It verified the image/config digests, 23-layer/3,210,119,745-byte contract, CUDA 10.1/Python 3.6 build history, RTX 5000 Ada, NVIDIA device nodes, and CUDA/EGL libraries. It downloaded no layers and ran no container, kernel, scene, or evaluator. |
| `habitat20-oci-gpu-import-smoke-20260803-baseline01.json` | fail | exact archived rootfs + isolated CUDA/EGL/import smoke | `8c764f0aaeb532c4fac4391313f6c11774a8755893daaa8a83c7d77eae53b7f0` | Preserved diagnostic: CUDA initialized one device; EGL failed before initialization/import because the injected host GLVND client required GLIBC 2.33. |
| `habitat20-oci-gpu-import-smoke-20260803-baseline02.json` | pass | corrected exact archived rootfs + isolated CUDA/EGL/import smoke | `be4a6acba149bee47661936ee5a90947b39e22313a411f02d17eeff839c49424` | Canonical OCI smoke: one CUDA device, one EGL 1.5 device, and Habitat-Sim 0.1.4 import under Python 3.6.10 passed in 561.432697 ms. Runner SHA-256: `4526fdcc3a66864a5792a188a387c7ef27ebe4c3258f92472113cf945e60607c`. |
| `habitat-test-assets-gpu-scene-smoke-20260803-baseline01.json` | pass | non-Habitat-2020 public-test-asset simulator/render/discrete-action smoke | `aed6afcb2e9af98f4f6ed8c3a3f636845e70a34b14057b1904493f8530330137` | Exact rootfs plus read-only Skokloster/PointNav fixtures: CUDA/EGL, Habitat-Sim 0.1.4 construction, scene/navmesh load, four RGB-D frames, and forward/left/right passed in 1,318.900083 ms with zero collisions. No goal, policy, evaluator, navigation episode, metric, or rank. |

The canonical contract smoke emitted ten actions of each non-terminal official action:
`MOVE_FORWARD`, `TURN_LEFT`, and `TURN_RIGHT`. Its median start-plus-action
JSONL latency was 0.123 ms, p95 was 0.233 ms, and the 99.395 ms maximum was the
cold subprocess start. These timings are contract-boundary diagnostics, not
robot end-to-end response latency.

The registry/GPU preflight removed uncertainty about whether the exact image is
still retrievable: its manifest digest is
`sha256:761ca223...c52b`, its config digest is
`sha256:75e366...db5e`, and the host exposes compute capability 8.9 through
driver 595.84. Follow-on materialization verified all 23 layers and inventoried
87,944 rootfs entries, including 7,925,803,803 regular-file bytes. Baseline01
then preserved the host-GLVND/GLIBC failure, while corrected baseline02 proved
the narrow archived CUDA/EGL/Habitat-Sim import boundary on this Ada GPU.

A real public-validation run remains blocked by the terms-gated `Pablo.glb` and
the still-unrun Gibson navigation/evaluator path. The passing import and public
test-scene smokes used Bubblewrap and did not require locally absent
Docker/NVIDIA Container Toolkit. The test-scene artifact did construct a
simulator, load a navmesh, render, and execute three deterministic actions; it
did not use Parcel's policy, read the PointNav goal, execute a navigation
episode/evaluator, or report SR, SPL, soft-SPL, official rank, or top-decile
standing.

The append-only external-evaluation ledger records the canonical image preflight
as `habitat20-image-preflight-20260803T141555Z`, failed baseline01 as
`habitat20-oci-gpu-import-smoke-20260803T144820Z`, and passing baseline02 as
`habitat20-oci-gpu-import-smoke-20260803T145414Z`. It records the public-test
scene baseline as `habitat-test-assets-gpu-scene-smoke-20260803T152317Z`.
Their execution and rank fields preserve the exact boundaries above; earlier
artifacts remain immutable history.
