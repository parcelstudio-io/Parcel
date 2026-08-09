# CI / eval-runner gate

Parcel has 220+ test files and rich eval harnesses (nav_instruct + mutation
panel, follow-bench, acoustic loop, planner/conversation packs, metamorphic
suite). Until now it had **no runner and no scheduler**: no `.github/workflows`,
an empty crontab. Every promotion gate was therefore manual, and Design A's
*model-off non-inferiority* guarantee was unfalsifiable — nothing enforced it,
so it could silently bit-rot. This document describes the runner that closes
that gap.

The runner does **not** add new evals. It wraps the harnesses that already
exist and turns the aspirational promotion gates into one exit-coded command.

- Runner: [`scripts/ci_gate.py`](../scripts/ci_gate.py) (+ [`scripts/ci_gate.sh`](../scripts/ci_gate.sh) wrapper)
- Workflow: [`.github/workflows/ci.yml`](../.github/workflows/ci.yml)
- Self-test: [`tests/test_ci_gate.py`](../tests/test_ci_gate.py)
- Seed plugin: [`scripts/ci_selftest_seed.py`](../scripts/ci_selftest_seed.py)
- Ruff debt baseline: [`scripts/ci_ruff_baseline.json`](../scripts/ci_ruff_baseline.json)

## Run it locally

```bash
# per-commit gate (fast, offline, deterministic — no model server, no network)
.parcel/bin/python scripts/ci_gate.py --tier commit

# nightly bundle (slow — live-sim e2e, acoustic rig, candidate minival, panel)
.parcel/bin/python scripts/ci_gate.py --tier nightly

# same via the wrapper (sets MUJOCO_GL=egl, pins the interpreter)
scripts/ci_gate.sh commit
scripts/ci_gate.sh commit --json      # also emit machine-readable JSON
```

Exit code is `0` iff every **hard** gate is green. Report-only (soft) gates are
printed but never change the exit code.

## Cadence

| Tier | When | Where |
| --- | --- | --- |
| `commit` | every push / PR | `commit-gate` job in `ci.yml` |
| `nightly` | 08:00 UTC daily (cron) + manual dispatch | `nightly-gate` job in `ci.yml` |

Even though the repo is not yet wired to GitHub Actions, `ci.yml` is the
canonical, versioned record of what must run and when; the gate logic lives in
`ci_gate.py` so CI and a laptop run the identical gate.

## What the commit tier enforces (all hard, all offline)

| Gate | Wraps | Reddens when |
| --- | --- | --- |
| `default-suite` | `pytest -m "not slow"` (3097-passing) | any default-gate test fails |
| `ruff` | `ruff check` ratcheted vs baseline | a **new** `(file, rule)` violation appears |
| `frozen-digest-integrity` | nav_instruct v3, embodied plan, conversation_quality, personal_convo manifest-sha tests | a byte drifts in any frozen pack |
| `frozen-digest-sentinels` | independent sha over the immutable frozen manifests | a pinned manifest's bytes move |
| `mutation-panel-freshness` | `test_mutation_panel_freshness.py` committed-panel guard | the panel rots off the current frozen episode set |
| **`model-off-non-inferiority`** | SigLIP / OWLv2(B3) / tiered-memory **flag-off byte-equal** cells | a model-off path stops being byte-identical to its deterministic fallback |
| **`latency-tail`** | committed p95/p99 percentile pins (observability + beat-sync) | a tail latency pin regresses |
| **`hard-safety`** | nav_instruct frozen-baseline row, mutation-panel clean run, follow-bench ledger | a hard collision appears on any product artifact, or the frozen baseline gains a false_arrival |

The three **bold** gates are the hard regression gates the independent verdict
demands. Any of them red fails the commit.

### The three hard regression gates, precisely

- **Model-off non-inferiority (Design A):** the SigLIP-2 (`PARCEL_SIGLIP2_ONNX`,
  default off), OWLv2/B3 detector (`PARCEL_OWLV2_ONNX`, default off) and tiered
  memory (`prompting.memory.enabled`, default off) lanes each already assert
  that with the model OFF the path is byte-identical to its deterministic
  string/oracle fallback. The gate collects all of those cells into one place so
  A cannot silently bit-rot.
- **Latency-tail:** no P95/P99 regression on the latency series that exist
  today. See the HANDOFF below — there is no persisted product latency ledger
  yet, so the authoritative pins are the committed percentile tests.
- **Hard-safety:** zero hard collisions on every product artifact (the
  frozen-baseline nav row, the mutation-panel clean run, every follow-bench row)
  and no new false_arrival on the frozen baseline (pinned at 0).

## What the nightly tier adds

Everything in the commit tier (re-run), plus:

| Gate | Wraps | Gating? |
| --- | --- | --- |
| `mutation-panel` | `scripts/mutation_panel.py` run in-process | hard — fails if any mutant survives (must be 6/6 killed) |
| `nav-instruct-candidate:collisions` | candidate v3 minival run | hard — collisions must be 0 |
| `nav-instruct-candidate:differential` | same run | report — SR, authority histogram, false_arrival |
| `slow-suite` | `pytest -m slow` (`PARCEL_NIGHTLY=1`, live-sim e2e + acoustic rig + nightly metamorphic) | hard |
| `metamorphic` | `pytest -m slow tests/test_nav_metamorphic.py` | report (already inside slow-suite; carries measured xfails) |

Per the verdict: nightly numeric outputs are **reported**; only the
pre-registered hard invariants (collisions, false_arrival, mutation survivors,
the slow suite's own assertions) gate.

## Self-test — proof the gate is not theatre

A green gate proves nothing unless it goes red for the right reason. Mirroring
`scripts/mutation_panel.py`, `tests/test_ci_gate.py` seeds each hard gate's exact
class of regression and asserts it reddens (and is green on a clean input):

| Seed | Gate that must catch it | How it is injected |
| --- | --- | --- |
| flag-off drift (SigLIP fallback perturbed) | `model-off-non-inferiority` | runtime monkeypatch via `scripts/ci_selftest_seed.py`, run as a pytest subprocess |
| injected collision | `hard-safety` | synthetic nav ledger with `collision_total=1` |
| new false_arrival | `hard-safety` | synthetic nav ledger with `false_arrival=1` |
| p99 spike | `latency-tail` (ratchet core) | synthetic series past the ratchet ceiling |
| byte-changed frozen digest | `frozen-digest-sentinels` | corrupted **copy** in a tmp dir |
| new ruff fingerprint | `ruff` | monkeypatched fingerprint set vs a tmp baseline |

No seed touches a committed source file or a frozen artifact — regressions are
injected into copies / synthetic inputs or via runtime monkeypatch, the same
rule the mutation panel follows.

## Design notes and constraints

- **Offline & deterministic:** the commit tier never depends on the network or a
  running model server. The real-weight SigLIP/OWLv2 cells self-skip when weights
  are absent; the flag-off cells they leave behind are exactly the model-off
  guarantee. MuJoCo runs headless (`MUJOCO_GL=egl`; use `osmesa` on a GPU-less
  runner).
- **No new gate logic in CI:** `ci.yml` only provisions an environment and calls
  `ci_gate.py`. The gate is identical locally and in CI.
- **Runner picks:** a plain Python runner + shell wrapper (not nox/tox/make)
  because the repo has no such tool and its convention is `scripts/*.py` run with
  `.parcel/bin/python` (e.g. `scripts/mutation_panel.py`). No new dependency.

## Handoffs (things the runner needs but could not add without touching owned code)

These are real gaps surfaced while wiring the gate. The runner works today
without them; closing them strengthens the named gate.

1. **No persisted product latency ledger.** The product path computes p50/p95/p99
   in-memory for the `/latency` dashboard (`observability.py::_aggregate`,
   `runtime.py::latency_snapshot`) but never writes a committed artifact. The
   latency-tail gate therefore rides the committed percentile *pins*
   (`test_beat_sync` p95, `test_observability_planning` p99). The runner already
   contains the ratchet (`evaluate_latency_ratchet`, self-tested) ready to read a
   real ledger. **Ask:** dump `latency_snapshot()` to an append-only
   `evals/latency/ledger.jsonl` so the tail can be ratcheted on real turn
   latency, not only the scheduling/component pins.
2. **Ruff debt (42 fingerprints / 53 raw violations)** in modules this card does
   not own (`storefront`, `uwb`, `route_memory`, `camera_channel`, `bags`,
   `detection_adapter/sim_bridge`, `low_viewpoint`, `voice`, and a few tests +
   `tools/`). The gate ratchets against `scripts/ci_ruff_baseline.json` so these
   do not block commits, but they should be **burned down to zero**; re-pin with
   `ci_gate.py --update-ruff-baseline` after each cleanup.
3. **walk_with_me records no collision field**, so it cannot join the hard-safety
   gate; its ledger row is a stub. **Ask:** have `run_walk_with_me` emit
   `hard_collision_total` like follow-bench does.
4. **Acoustic loop needs a host PipeWire rig** (`pw-cli`/`pw-play`/…); it is
   offline but not drop-in headless, so it is not in the commit tier. It runs in
   the nightly `slow-suite` only where the rig is present.
