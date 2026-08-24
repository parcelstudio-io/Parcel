# EMBODIMENT-KERNEL — RESULTS · 2026-08-24

## Static audit

```bash
.parcel/bin/python \
  research/20260824/embodiment-kernel-portability/audit.py \
  --repo . \
  --out research/20260824/embodiment-kernel-portability/results.json
```

| row | result | bar | outcome |
|---|---:|---:|---|
| K1 vendor SDK leaks | 0 | 0 | pass |
| K2 high-level vendor-name modules | 0 | 0 | pass |
| K3 simulator-observation modules | 9 | 0 | **refuted** |
| K4 `NavigationSnapshotV2` exists | no | yes | **refuted** |
| K6 explicit target service files | 2 firewall units only | five owned services | **refuted** |

The nine product modules coupled to `SimObservation` are:

```text
brain/observations.py
control/base.py
control/state.py
navigation/follow.py
navigation/reactive_safety.py
navigation/search_owner.py
navigation/semantic_map.py
navigation/spatial.py
runtime.py
```

The deployment README also explicitly disclaims an Orin/aarch64 artifact.
The two discovered `.service` files are firewall helpers, not gateway,
supervisor, sensing/localization, audio or perception services.

## Focused compatibility evidence

The mandated guard ran the existing controller and body portability suites:

```bash
env -u TMPDIR ~/.cache/parcel-guard/pytest_guard.sh \
  --label codex-portability \
  .parcel/bin/python -m pytest \
  tests/test_portability_proof.py \
  tests/test_h4_body_intent.py \
  tests/test_backends.py -q
```

Result: **30 passed in 3.68 s**. K5 passes for the current desktop/fake-body
evidence tier.

## Interpretation

Actuation concepts are reusable: vendor imports are contained, and the
controller/body-intent tests remain green. Whole-product portability is not
established. Navigation, safety and runtime assembly still receive a
simulator-shaped carrier, and there is neither a body-neutral synchronized
snapshot nor a deployable robot service topology.

This audit is static and can miss semantic coupling. It does not test a real
Go2, vendor SDK, Orin build, custom whole-body controller or physical sensor.
