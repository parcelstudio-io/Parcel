# S-A STATUS — P0 boundary (Fable SPLIT, additive core)

**Executor:** Sol stand-in (prior `fe683adf…` API-limited after modules)  
**Arbitration:** `AUDIT_WAVE1.md` § S-A early arbitration — verdict **SPLIT** (binding)  
**Verdict:** **LANDED (boundary only)** — pure `core/` modules + property tests + frozen contracts for S-A2.  
**P0-A / P0-B on the product path:** **remain OPEN.** Only S-A2 may claim them closed.

## Delivered (additive; MUST-NOT-TOUCH held)

| Path | Role |
|---|---|
| `src/parcel_robot/core/hard_stop.py` | Pure final-stop monitor (`finalize_command`) |
| `src/parcel_robot/core/input_health.py` | Pure fail-closed required-input join (`evaluate_input_health`) |
| `tests/test_core_hard_stop.py` | Interrupt-at-every-stage exact-zero + reset obligations |
| `tests/test_core_input_health.py` | Missing/stale/malformed/frame combinations → HOLD/STOP |

**Not edited:** `runtime.py`, `navigation/**`, `scripts/mutation_panel.py`, frozen eval rows.

## Frozen contracts for S-A2 wiring

### `parcel_robot.core.hard_stop`

Call site (mechanical): after every velocity shaper / gate stage and **immediately before** `control_manager.set_target` (or equivalent dispatch boundary).

```text
decision = finalize_command(
    candidate,                 # VelocityCommand after shaping
    severity,                  # InterventionSeverity
    downstream_stages=(...),   # ResetObligation(name, reset) per stateful stage
)
# honor decision.command exactly
# if decision.reset_required: resets already attempted inside finalize_command
# if decision.reset_failures: must not resume motion (decision.dispatch_allowed false only if
#   command were nonzero — HARD_STOP always returns exact zero)
```

| Severity | Emitted command | Reset obligations |
|---|---|---|
| `CLEAR` | candidate unchanged | none (callbacks not invoked) |
| `PROXIMITY_STOP` | `VelocityCommand(vyaw=candidate.vyaw)` — translation zeroed, yaw preserved | none |
| `HARD_STOP` | exact `(vx=0, vy=0, vyaw=0)` (`ZERO_COMMAND`) | every `ResetObligation` attempted once; one failure does not skip later stages |
| unknown severity / non-finite candidate | treated as `HARD_STOP` | same as `HARD_STOP` |

**Property already proven in unit suite:** smoother→gate→shaper model interrupted at every stage; next finalized command is exact zero and all stage caches reset.

### `parcel_robot.core.input_health`

Call site (mechanical): before translation-authorizing reactive/collision gates; missing-scan must route through this join (not “clear”).

```text
verdict = evaluate_input_health(
    evidence,   # Mapping[RequiredInput, InputEvidence | None]
    now=...,    # decision timestamp (finite)
    requirements=DEFAULT_REQUIRED_INPUTS,  # optional override
)
# if not verdict.translation_allowed: forbid translation command
# if verdict.stop_latched: latch STOP (HealthAction.LATCHED_STOP)
```

**Default required inputs**

| Input | Frame | max_age_s | sim fixture |
|---|---|---|---|
| `POSE` | `odom` | 0.25 | forbidden |
| `SCAN` | `base_link` | 0.25 | allowed **only** with non-empty `fixture_label` and `origin=SIM_FIXTURE` |
| `CONTROLLER_FEEDBACK` | `base_link` | 0.25 | forbidden |

**HOLD / STOP table (most severe fault wins; all faults retained)**

| Fault class | Action | `translation_allowed` |
|---|---|---|
| missing / absent key | `HOLD` | False |
| stale (`age > max_age_s`) | `HOLD` | False |
| malformed type / timestamp / payload | `LATCHED_STOP` | False |
| timestamp in future | `LATCHED_STOP` | False |
| frame inconsistent | `LATCHED_STOP` | False |
| origin malformed / unlabeled sim fixture / sim on non-scan / physical+fixture_label | `LATCHED_STOP` | False |
| malformed `now` / evidence table | `LATCHED_STOP` (all inputs) | False |
| all inputs healthy | `ALLOW` | True |

## Mutation panel

**Deferred to S-A2** with provenance:

- Original card asked for mutation-panel additions + killed mutants.
- Under SPLIT these modules are **not on the product path**; nav_instruct never calls them.
- Seeding `hard_stop` / `input_health` mutants in `scripts/mutation_panel.py` now would create **equivalent / surviving** mutants and redden the panel dishonestly.
- Unit-level seeded-defect oracles live in `tests/test_core_hard_stop.py` and `tests/test_core_input_health.py` (residual-nonzero and stale-as-ALLOW classes killed by the property oracles).
- S-A2 GATE (transferred): live-pipeline property tests + mutation-panel new mutants killed after wiring.

## P0-A / P0-B remain OPEN (explicit)

| Blocker | Why still open after S-A |
|---|---|
| **P0-A** | Live residual nonzero after emergency shaping is in `runtime.py` / `navigation/velocity_shaping.py` — S-A2 OWNS |
| **P0-B** | Missing-scan pass-through is in `navigation/reactive_safety.py` — S-A2 OWNS |

S-A landing is a **boundary**, not a product-path fix. See `S-A2_CARD.md`.

## Evidence

- `.parcel/bin/python -m pytest -q tests/test_core_hard_stop.py tests/test_core_input_health.py`
  - **43 passed** in 0.25s
- `.parcel/bin/python -m ruff check --fix` on the four S-A Python files
  - 2 autofixes (sorted `__all__` / imports); clean after
- Frozen rows: **UNMOVED** (no eval/result edits; no `mutation_panel.py` / results edits)
- Ownership: S-A did not edit `runtime.py` or `navigation/**` (pre-existing `runtime.py` dirty tree belongs to C-A)
- `.parcel/bin/python scripts/ci_gate.py --tier commit`
  - first attempt (sandbox): FAIL — default-suite 2 failed
    (`test_habitat2020_contract_smoke…` PermissionError; `test_walk_with_me_k8::test_cli_smoke` KeyError) — both out of S-A OWNS; habitat was already noted pre-existing red in `DISPATCH_WAVE1.md`
  - isolated `test_cli_smoke` outside sandbox: **1 passed**
  - **authoritative retry** (full perms, 2026-08-09T22:33:09Z): **PASS — every hard gate green**
    - ruff: `7 violation(s), baseline 7, new 0`
    - hard-safety / frozen-digest-* / model-off / mutation-panel-freshness / latency-tail: PASS
    - default-suite: `3210 passed, 9 skipped, 34 deselected`
    - elapsed 105.4s

## does_not_prove

- Does **not** prove P0-A or P0-B closed on the live dispatch path.
- Does **not** prove `set_target` receives exact zero after a stop decision today.
- Does **not** prove reactive_safety fails closed on missing scan today.
- Unit interrupt model is a pipeline stand-in; live wiring + live property tests belong to S-A2.
