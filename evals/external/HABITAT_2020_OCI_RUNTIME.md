# Habitat 2020 archived OCI runtime

This is a fail-closed path for materializing and smoke-testing the exact archived
Habitat Challenge 2020 base image. It is not a navigation evaluation. As of
2026-08-03, the 23 exact layers have been verified and the rootfs has been
assembled and inventoried: 87,944 entries, including 72,482 regular files
totaling 7,925,803,803 bytes. The immutable baseline01 initialized CUDA with one
device, then failed before EGL or the Habitat import because the injected host
GLVND client required GLIBC 2.33 while the image provides GLIBC 2.27. The
corrected baseline02 initialized one CUDA device and one EGL 1.5 device and
imported Habitat-Sim 0.1.4 under Python 3.6.10 in 561.432697 ms. Its report
SHA-256 is
`be4a6acba149bee47661936ee5a90947b39e22313a411f02d17eeff839c49424`,
its runner SHA-256 is
`4526fdcc3a66864a5792a188a387c7ef27ebe4c3258f92472113cf945e60607c`,
and it is ledgered as
`habitat20-oci-gpu-import-smoke-20260803T145414Z`. Neither attempt constructed
a simulator, loaded a scene, rendered, executed a GPU kernel or navigation
episode, ran an evaluator, or emitted a navigation metric or rank.

A separate, explicitly non-Habitat-2020 baseline then advanced one bounded tier
with public test assets: it constructed Habitat-Sim, loaded the Skokloster scene
and navmesh, rendered four RGB-D frames, and executed forward/left/right with no
collisions. That follow-on is documented in
[`HABITAT_TEST_ASSET_SMOKE.md`](HABITAT_TEST_ASSET_SMOKE.md); it still ran no
Parcel policy, navigation episode, evaluator, metric, or rank protocol.

## Frozen image and storage boundary

- Image: `fairembodied/habitat-challenge@sha256:761ca2230667add6ab241a0eaff16984dc271486ec659984ae13ccab57a9c52b`
- Registry manifest: 23 unique compressed layers totaling exactly
  `3,210,119,745` bytes.
- Materialized inventory: 87,944 entries (8,996 directories, 72,482 regular
  files, and 6,466 symlinks), with 7,925,803,803 regular-file bytes and
  canonical tree SHA-256
  `65caf2c814dd7d26b2430d65fcae97dc6ddd2cad279e79d5b085180f3b7be9ba`.
- Managed cache: `.cache/external-evals/runtime/habitat2020-oci/<manifest-hex>/`.
  It is already covered by Parcel's `.gitignore`.
- Preparation enforces at least `34,359,738,368` free bytes (32 GiB) before it
  starts. The registry does not publish total expanded size, so 32 GiB is an
  explicit conservative floor, not a claim about the eventual exact rootfs
  size. The exact compressed requirement is known; expanded usage can only be
  measured after verified decompression.

The materializer accepts only the digest endpoint. It verifies the manifest and
config digests, every layer's declared size and SHA-256, and every uncompressed
OCI diff ID. Layers are applied in order to a new staging directory with OCI
whiteout handling and path/link traversal checks, then atomically renamed. It
does not invoke the image entrypoint, build history, hooks, shell, package
manager, Docker, or Proot.

After assembly, Parcel inventories the entire rootfs in deterministic raw-name
depth-first order. Every directory, symlink, and regular file contributes its
type and mode; symlinks contribute their raw target; regular files contribute
their size and SHA-256. The resulting canonical-stream digest and counts are
stored in both read-only provenance copies. Only the internal provenance marker
itself is excluded to avoid self-reference. The full inventory is recomputed
before a smoke, so changing even a noncritical cached file fails closed.

Inspection is local and performs no network request:

```bash
PYTHONPATH=. .parcel/bin/python -m evals.external.habitat2020_oci_runtime
```

The exact preparation command used to establish an empty managed cache was:

```bash
PYTHONPATH=. .parcel/bin/python -m evals.external.habitat2020_oci_runtime \
  --prepare \
  --confirm-image-digest sha256:761ca2230667add6ab241a0eaff16984dc271486ec659984ae13ccab57a9c52b
```

Preparation is already complete in the default managed cache. Do not repeat it
against the published rootfs; the materializer deliberately refuses to replace
an existing runtime.

## No-dataset GPU/import smoke

The smoke requires:

- the fully assembled rootfs, a fresh verification of all 23 compressed layer
  hashes, and an exact recomputation of the full rootfs inventory digest;
- Bubblewrap (`/usr/bin/bwrap`) with unprivileged namespace support;
- `/dev/nvidiactl`, `/dev/nvidia0`, `/dev/nvidia-uvm`, and the available NVIDIA
  and DRI character devices;
- x86-64 host `libcuda.so.1`, `libEGL_nvidia.so.0`, and their allowlisted
  NVIDIA-only driver/vendor dependencies;
- the image's own GLIBC-2.27-compatible `libEGL.so.1`, `libGLdispatch.so.0`,
  and NVIDIA EGL vendor JSON;
- the archived named-environment Python at
  `/opt/conda/envs/habitat/bin/python` and the exact
  `habitat_sim-0.1.4-py3.6-linux-x86_64.egg` binding. The base
  `/opt/conda/bin/python` is Python 3.7 and is deliberately not used.

This host currently exposes the required RTX 5000 Ada devices/libraries and
Bubblewrap. `nvidia-container-cli` and Proot are absent; neither is required by
this implementation. Baseline01 preserved the failed CUDA-pass/EGL-GLIBC
diagnostic. Baseline02 then verified the narrow CUDA/EGL/Habitat-Sim import
boundary with driver 595.84: CUDA exposed one device, EGL 1.5 initialized one
device, and Habitat-Sim 0.1.4 imported successfully.

To reproduce the smoke, use a unique write-once output:

```bash
PYTHONPATH=. .parcel/bin/python -m evals.external.habitat2020_oci_runtime \
  --smoke \
  --confirm-image-digest sha256:761ca2230667add6ab241a0eaff16984dc271486ec659984ae13ccab57a9c52b \
  --output evals/external/results/habitat2020/my-unique-oci-gpu-import-smoke.json
```

Bubblewrap mounts the rootfs read-only, creates fresh `/proc`, `/dev`, and
`/tmp`, disables networking, injects only explicit GPU devices and allowlisted
NVIDIA driver/vendor files, and runs Parcel's fixed
`habitat2020_gpu_smoke_py36.py`—not the image command. The probe initializes the
CUDA driver, initializes an EGL device display, and imports `habitat_sim`. It
does not construct `habitat_sim.Simulator`, load a dataset or scene, execute a
render or CUDA kernel, run an episode/evaluator, or emit SPL or another
navigation metric.

### GLVND ABI boundary

Baseline01 injected the host's generic `libEGL.so.1`. That loader requires
GLIBC 2.33–2.38, while the archived image provides GLIBC 2.27. The corrected
contract keeps the immutable image clients:

- `/usr/lib/x86_64-linux-gnu/libEGL.so.1 -> libEGL.so.1.0.0`, SHA-256
  `12f84b62738df3a799d85e8b49a0a990526fb2ee86e08fc9e5a8109c73c9c6e1`,
  maximum required GLIBC 2.14;
- `/usr/lib/x86_64-linux-gnu/libGLdispatch.so.0 -> libGLdispatch.so.0.0.0`,
  SHA-256
  `2ac91fdda3fd504f2368855bb15d9f5a14ed66a3966774c3eb8965bb8e6af7ba`,
  maximum required GLIBC 2.14;
- `/usr/share/glvnd/egl_vendor.d/10_nvidia.json`, which selects
  `libEGL_nvidia.so.0`.

Only NVIDIA host libraries are injected. On this host, `libEGL_nvidia` requires
at most GLIBC 2.7, `libnvidia-eglcore` 2.10, and `libcuda` 2.9, all within the
image's GLIBC 2.27 ABI. Discovery now rejects generic host `libEGL` and
`libGLdispatch` explicitly and fails closed if any selected NVIDIA library
requires a glibc newer than 2.27. The corrected contract was then rerun as
baseline02; the failed baseline remains immutable.

Baseline02 reran this corrected contract and passed in 561.432697 ms. The
baseline01 failure remains immutable under report SHA-256
`8c764f0aaeb532c4fac4391313f6c11774a8755893daaa8a83c7d77eae53b7f0`
and ledger ID `habitat20-oci-gpu-import-smoke-20260803T144820Z`.

The passing baseline02 supports only the claim “exact archived image
CUDA/EGL/Habitat-Sim import smoke.” It is not an official Habitat 2020 result,
is not leaderboard-comparable or rank-eligible, and says nothing about Parcel's
SPL. A real score still requires the frozen Gibson `val_mini` scene/episodes and
the unchanged official evaluator contract.

## Follow-on public-test-asset boundary

The non-gated test-asset runner keeps baseline02 immutable and performs a
separate full rootfs verification before mounting the asset bundle read-only in
the same network-disabled Bubblewrap boundary. Baseline01 of that distinct gate
passed in 1,318.900083 ms with CUDA one device, EGL 1.5 one device,
Habitat-Sim 0.1.4, a loaded scene/navmesh, four 128×128 RGB-D renders, and three
collision-free discrete actions. Its report SHA-256 is
`aed6afcb2e9af98f4f6ed8c3a3f636845e70a34b14057b1904493f8530330137`
and ledger ID is
`habitat-test-assets-gpu-scene-smoke-20260803T152317Z`.

The scene repository is public and ungated but licensed CC-BY-NC-4.0; “public
test asset” does not mean unlicensed. The PointNav ZIP is independently hashed
and used only for episode 0's start transform; its goal is not read. This smoke
is not the Gibson `Pablo.glb` protocol and emits no Habitat navigation score.
