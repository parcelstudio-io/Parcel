# Deploy compose skeleton (K7)

Desktop/CI layout for Parcel's per-concern services. **No Orin flash, no
aarch64 bake, no dock golden-image validation** — those remain P5 under the
owner amendment (`scrum/20260805/task_1/ADJUDICATION.md`).

## Services

| Service | Role | Network |
|---|---|---|
| `safety-control` | 10 Hz authority-loop smoke (`DirectiveNavigator` synthetic ticks) | `network_mode: none` |
| `perception-stub` | Layout placeholder (`--profile stubs`) | `parcel_aux` bridge |
| `voice-stub` | Layout placeholder (`--profile stubs`) | `parcel_aux` bridge |

`safety-control` deliberately does **not** join `parcel_aux`. That encodes the
program rule: the safety+control container has zero network dependencies and
restarts independently.

## Run (desktop / CI)

From the repository root:

```bash
# Build + run the safety island smoke (50 ticks @ 10 Hz, then exit)
docker compose -f deploy/compose.yaml up --build --abort-on-container-exit safety-control

# Optional stub layout (perception + voice placeholders)
docker compose -f deploy/compose.yaml --profile stubs up --build

# One-shot CI-friendly run
docker compose -f deploy/compose.yaml run --rm --no-deps safety-control \
  python -m parcel_robot.safety_control_smoke --max-ticks 30
```

Without Docker (host editable install):

```bash
PYTHONPATH=src PARCEL_ROOT=. .parcel/bin/python -m parcel_robot.safety_control_smoke --max-ticks 30
```

## Related

- CPU-budget proxy (HR-6): `PYTHONPATH=src .parcel/bin/python -m evals.cpu_budget_proxy`
- Status: `scrum/20260805/task_1/K7_STATUS.md`
- ADR golden image (draft, validate P5): `scrum/20260805/task_1/adr/0001-golden-image.md`
