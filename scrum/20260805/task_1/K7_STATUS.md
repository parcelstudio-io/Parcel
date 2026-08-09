# K7 status — Compose skeleton + packaging + CPU-budget proxy

**Date:** 2026-08-05 · **Owner lane:** Opus/infra · **Binding:** ADJUDICATION K7
(dock flash moved to P5 by owner amendment).

## Delivered

| Item | Path | Notes |
|---|---|---|
| Compose skeleton | [`deploy/compose.yaml`](../../../deploy/compose.yaml), [`deploy/README.md`](../../../deploy/README.md) | `safety-control` uses `network_mode: none`; perception/voice are `--profile stubs` placeholders |
| Safety+control smoke | `src/parcel_robot/safety_control_smoke.py` | Synthetic 10 Hz `DirectiveNavigator` ticks; no outbound network |
| Asset path helper | `src/parcel_robot/paths.py` | Resolves via `PARCEL_ROOT` → checkout → packaged `runtime_assets/` |
| Packaged runtime assets | `src/parcel_robot/runtime_assets/` + `tools/sync_runtime_assets.py` | skills + nav defaults + prompts; re-sync after asset edits |
| Fallback config sync | `src/parcel_robot/config/robot.yaml` | Aligned with canonical `configs/robot.yaml` (removes legacy `fish_streaming` / `barge_in`) |
| package-data | `pyproject.toml` | Includes `runtime_assets/**/*` |
| CPU-budget proxy | `evals/cpu_budget_proxy.py` | Desktop/CI 10 Hz hot-path JSON reporter (HR-6) |
| Tests | `tests/test_runtime_assets.py`, `tests/test_cpu_budget_proxy.py` | |

## How to run

```bash
# Asset packaging checks
.parcel/bin/python -m pytest tests/test_runtime_assets.py tests/test_cpu_budget_proxy.py -q

# CPU-budget proxy → scrum report (desktop HR-6 stand-in)
PYTHONPATH=src .parcel/bin/python -m evals.cpu_budget_proxy \
  --output scrum/20260805/task_1/cpu-budget-proxy-k7.json

# Host safety-control smoke (no Docker)
PYTHONPATH=src PARCEL_ROOT=. .parcel/bin/python -m parcel_robot.safety_control_smoke --max-ticks 30

# Compose safety island (desktop/CI; requires Docker)
docker compose -f deploy/compose.yaml up --build --abort-on-container-exit safety-control
```

Sample proxy report committed at
[`cpu-budget-proxy-k7.json`](cpu-budget-proxy-k7.json) (median within 176 ms
budget on this desktop; **does not prove** Orin timing).

See [`deploy/README.md`](../../../deploy/README.md) for stub profile usage.

## Explicit non-claims (honesty)

- **No Orin NX flash / golden-image bake** — dock flash remains P5 (ADR 0001).
- **No aarch64 Jetson image** — desktop/CI `python:3.12-slim` only.
- **CPU-budget proxy ≠ on-device timing** — HR-6 stays unvalidated until P5 replay.
- Packaged assets do **not** include MuJoCo `third_party/` meshes; full visual
  sim still needs a source checkout bind-mount / third_party present.
- Stub perception/voice containers prove compose layout only, not audio or
  camera pipelines.

## ADR / ledger touchpoints

- [adr/0001-golden-image.md](adr/0001-golden-image.md) — compose skeleton may
  run on desktop/CI; flash validation still P5.
- [adr/0002-firmware-pin.md](adr/0002-firmware-pin.md) — unchanged; no firmware
  action in K7.
- [hardware-readiness.md](hardware-readiness.md) HR-6 — proxy script exists;
  status remains **unvalidated** (desktop proxy).

## Next (out of K7 MVP)

- Wire compose health to a real shared-memory / Unix-socket control bus.
- aarch64 multi-arch build once a Jetson base is chosen at P5.
- Expand packaged nav models beyond `grid`/`stub` if wheel installs need them.
