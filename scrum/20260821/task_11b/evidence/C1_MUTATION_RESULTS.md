# C-1 mutation evidence — 2026-08-21

**Result: 10/10 meaningful source seeds RED; every inverse restored the exact
pre-window SHA-256; every named post-restore test GREEN.**

The mutation window began only after both live processes stopped.  Parent and
the two read-only auditors were warned not to inspect the shared tree until the
byte-restore signal.  Every test used `-B`, `-p no:cacheprovider`,
`PYTHONDONTWRITEBYTECODE=1`, and a seed-specific
`PYTHONPYCACHEPREFIX=/tmp/parcel-c1-m<id>-{red,green}`.  No test result could be
served by another seed's bytecode or pytest cache.

## Frozen hashes

| File | Before mutation window | After M10 and final sweep |
|---|---|---|
| `runtime.py` | `024a363224cb67ca9c6d538a1827a95b993b355213b633d497a96fab52f08398` | exact match |
| `realtime/evidence_log.py` | `0b5a52be8e05f6c2b1ab7f5139dae32c2709a3aebf5fdce38338a5196e63fdda` | exact match |
| `camera_channel/ingress.py` | `5d9f3405ba559216471122ae4fb11356ef8057fef19f0842e1b6de01604bec07` | exact match |
| `camera_channel/backends/mujoco_egl.py` | `4cb4b2f4d56e89e71e5f0589892ce1063c474d490393f6b433e3a5a71d28b136` | exact match |
| `web_panel.py` | `fc423fcf163822eb50b5cb0d2b7d3b6fff767141f4c8752c67e827863c2fcc9a` | exact match |
| `tests/test_c1_camera_ingress.py` | `b9318755478fab4bdc668ad3f216c6d7ccf18e8970cd634060a7c23b61cb3cdc` | exact match |

## Seed register

| Seed | One source mutation | Mutant SHA-256 | RED observation | Exact inverse / GREEN |
|---|---|---|---|---|
| M1 | `perception.camera_ingress` missing-key default `False -> True` | runtime `23f35b94fb889eab2e9b1456b69fac32ffa24664f60c04f1d28d63cb02d85afc` | `test_c1_config_is_strict_default_off...`: **1 failed**; `default.enabled` was True | runtime restored `024a...`; **1 passed** |
| M2 | queue eviction increments dropped frames by zero | runtime `d1f005daf8422c0d969336f81d75188d2c4c158c3192fa9c6215e7bdeb472916` | `test_runtime_keep_newest_queue_counts...`: **1 failed**; expected 1 drop, observed 0 | runtime restored `024a...`; **1 passed** |
| M3 | add `schema` to every v1 writer snapshot | evidence `bd61c2bc8588a5636ebdd1bab8d9bbc3ae4059339208da758af03330f2433d8a` | `test_default_v1_writer_snapshot...`: **1 failed**; extra v1 key | evidence restored `0b5a...`; **1 passed** |
| M4 | offer typed camera rows to `STREAM_EVENT` instead of `STREAM_PERCEPTION` | runtime `b8bd6ad2a9aa1be4d3293ccc911b8cffb05948e89925af13a1e7d3d3c0f6c119` | `test_real_ev1_v2_persists...`: **1 failed**; zero perception rows | runtime restored `024a...`; **1 passed** |
| M5 | let worker reuse the last pose when its pose source returns `None` | ingress `1f45b3159f3a82b5edec3d7246fc03af33c09b60d0a6e40ba17537487c177bca` | `test_pose_source_requires_a_new_sample...`: **1 failed**; five captures from one pose | ingress restored `5d9f...`; **1 passed** |
| M6 | remove request/envelope sequence correlation check | ingress `f1fa9c0d74160f70f88cc2723391be1b94621f935eb51f2b038edaf9cd8850e4` | envelope mutation matrix: **1 failed, 8 passed**; sequence mismatch escaped | ingress restored `5d9f...`; **9 passed** |
| M7 | panel parser `allow_abbrev=False -> True` | panel `cbea9e4e3abcdfbf81934ac9100ce9ac1cbcaaa11b50301585ba1d98cdf746dc` | direct CLI matrix: **2 failed, 2 passed**; panel accepted `--sc`/`--conf` | panel restored `fc42...`; **4 passed** |
| M8 | retain stale EGL buffer refs across captures | backend `34c86158b98ac6d843d511efc5cf00503b0a3289b5807d78da92ccdf59dbfc58` | `test_mujoco_backend_replaces_ephemeral_buffers...`: **1 failed**; 5 refs vs bounded 3 | backend restored `4cb4...`; **1 passed** |
| M9 | remove refusal for simultaneous C-1 producer and legacy B4 authority | runtime `664fde3e35c59d782cd873e1ca27c6b53bb58c46e26f79334f7a1becb4f985a2` | `test_c1_refuses_both_legacy_authority_arms`: **1 failed**; config arm did not raise | runtime restored `024a...`; **1 passed** |
| M10 | compute current expiry from publish time instead of snapshot clock | runtime `3b86c91780c3eec1f41e0a7ec7084dfe31d4f795ce85cf0ed7372187fc450f1a` | exact-boundary snapshot test: **1 failed**; expired-now stayed false | runtime restored `024a...`; **1 passed** |

These are source-level fault insertions, not a count of ordinary invalid-input
parameters.  The seeds exercise the card's required failure classes: default-OFF
parity, bounded/drop-counted queueing, typed evidence, stale-pose refusal,
capture identity, composition parity, bounded renderer memory, C-3 authority
isolation, and current freshness.

## Post-restore sweep

```text
PYTHONDONTWRITEBYTECODE=1
PYTHONPYCACHEPREFIX=/tmp/parcel-c1-postmut-dedicated
.parcel/bin/python -B -m pytest -q -p no:cacheprovider
tests/test_c1_camera_ingress.py

86 passed, 3 warnings in 16.65s
```

```text
PYTHONDONTWRITEBYTECODE=1
PYTHONPYCACHEPREFIX=/tmp/parcel-c1-postmut-cross
.parcel/bin/python -B -m pytest -q -p no:cacheprovider
tests/test_c1_camera_ingress.py tests/test_runtime_activation.py
tests/test_web_panel.py tests/test_k5_opus_sim_wiring.py
tests/test_eval_assertions.py

192 passed, 3 warnings in 21.46s
```

Changed-path Ruff: `All checks passed!`.  C-1 `git diff --check`: no output.

