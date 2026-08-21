# CI / eval-runner gate

Parcel has a large test surface and rich eval harnesses (nav_instruct + mutation
panel, follow-bench, acoustic loop, planner/conversation packs, metamorphic
suite). The executable runner and versioned workflow definition below close the
historical gap where every promotion gate was manual. The latest recorded local
commit-tier run, independently rerun on 2026-08-21, passed 7,715 tests with 9
skipped and 42 deselected; all hard gates were green. The first RECORDED nightly ran the
same day — `evals/nightly/20260821T102132Z` — and is the first time the 42
deselected tests have been executed by any gate. The workflow declares push, pull-request,
scheduled, and manual triggers, but hosted GitHub Actions execution/enabling
remains unverified until a GitHub run is recorded.

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

`ci.yml` is the canonical, versioned record of what must run and when; the gate
logic lives in `ci_gate.py` so a hosted runner and a laptop invoke the same
gate. Local execution is verified; hosted execution remains unverified.

## What the commit tier enforces (all hard, all offline)

| Gate | Wraps | Reddens when |
| --- | --- | --- |
| `default-suite` | `pytest -m "not slow"` (latest recorded: 7,715 passed) | any default-gate test fails |
| `ruff` | `ruff check` ratcheted vs baseline | a **new** `(file, rule)` violation appears |
| `release-parity` | generated runtime-asset manifest | a canonical/deployable asset differs or disappears |
| `assertion-evals` | frozen EV-1 fixtures + seeded harness self-test | findings drift or a deliberately broken evaluator passes |
| `tier-coverage` | independent commit/nightly collection | a test becomes orphaned, overlaps tiers, or a required hard gate disappears |
| `owner-store-isolation` | explicit owner-memory isolation nodes | a test or in-process runtime can reach the owner's writable store |
| `frozen-digest-integrity` | nav_instruct v3, embodied plan, conversation_quality, personal_convo manifest-sha tests | a byte drifts in any frozen pack |
| `frozen-digest-sentinels` | independent sha over the immutable frozen manifests | a pinned manifest's bytes move |
| `release-parity-integrity` | source/package behavior tests | source and installed/package roots resolve differently |
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
- **Latency-tail:** no P95/P99 regression on the committed percentile pins or
  the persisted append-only latency ledger. The ledger is wired into the gate,
  but its current rows do not cover every real acoustic/device stage; see the
  handoff below.
- **Hard-safety:** zero hard collisions on every product artifact (the
  frozen-baseline nav row, the mutation-panel clean run, every follow-bench row)
  and no new false_arrival on the frozen baseline (pinned at 0).

## What the nightly tier adds

Everything in the commit tier (re-run), plus:

| Gate | Wraps | Gating? |
| --- | --- | --- |
| `mutation-panel` | `scripts/mutation_panel.py` run in-process | hard — fails if any mutant survives (**7/7 killed** in the 2026-08-21 nightly; this line said 6/6 until a nightly actually printed the number) |
| `nav-instruct-candidate:collisions` | candidate v4 minival run | hard — collisions must be 0 |
| `nav-instruct-candidate:differential` | same run | report — SR, authority histogram, false_arrival |
| `slow-suite` | `pytest -m slow` (`PARCEL_NIGHTLY=1`, live-sim e2e + acoustic rig + nightly metamorphic) | hard |
| `metamorphic` | `pytest -m slow tests/test_nav_metamorphic.py` | report (already inside slow-suite; carries measured xfails) |

Per the verdict, nightly numeric outputs are **reported** unless their row is
explicitly hard. Candidate collisions and mutation survivors gate; the
candidate differential row—including candidate `false_arrival`—is report-only.
The frozen baseline's no-new-false-arrival invariant remains a separate hard
commit-tier safety check.

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
| a narrowed nightly selection that orphans a tier | `tier-coverage` (R26) | an injected collector whose nightly markers no longer cover the e2e file |
| a commit-tier hard gate deleted | `tier-coverage`'s companion (R26) | the gate list is asserted entry by entry against `run_commit_tier`'s source |
| a credential leaking into an offline tier | `_base_env` scrub (R26) | seeded keys in the environment must not survive into a subprocess |

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
  the runner. The gate is identical locally and in CI. (The nightly job calls
  `scripts/run_nightly.py`, which wraps `ci_gate.py --tier nightly` and adds the
  evidence folder — see the tier map below.)
- **Hermetic against the operator's shell (card R26):** every subprocess the gate
  launches has `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `PARCEL_REALTIME_KEY_ENV`
  and whatever that indirection names removed, unless `PARCEL_REALTIME_LIVE=1`
  opts in explicitly. Found the hard way: with a credential exported, a hard-gated
  realtime test flipped from green to red because the runtime built a live
  transport, and the only thing on this machine that had ever run the suite with
  a credential loaded was the nightly's judge stage.
- **Runner picks:** a plain Python runner + shell wrapper (not nox/tox/make)
  because the repo has no such tool and its convention is `scripts/*.py` run with
  `.parcel/bin/python` (e.g. `scripts/mutation_panel.py`). No new dependency.

## The tier map — what runs where, and what never runs (card R26)

The full audit could not answer this from the repo, and the answer turned out to
matter: the nightly tier existed, the cron declared it, and **no nightly had ever
produced a recorded run**, so the 42 deselected tests — the entire voice-to-nav
end-to-end tier — had never been executed by any gate. Card R26
(`scrum/20260821/task_5/R26_STATUS.md`) stood it up. This section is the map.

| Tier | Command | Selection | Cadence | Evidence it leaves |
| --- | --- | --- | --- | --- |
| **commit** | `ci_gate.py --tier commit` | `pytest -m "not slow"` + the targeted hard-gate node-id selections | every push / PR, and before every card's close | terminal only |
| **nightly** | `scripts/run_nightly.py` | everything in commit, **plus `pytest -m slow`**, mutation panel, candidate minival, DR-2 drift arms, the future-clock sweep, EV-1's judge/review queue | 08:00 UTC cron + manual | `evals/nightly/<stamp>/` + a row in `evals/nightly/ledger.jsonl` |
| **per-release** | `pytest -m slow tests/test_release_parity_wheel.py` (inside the nightly slow tier) | builds a wheel into a throwaway venv | whenever the packaged tree changes | the nightly folder |
| **opt-in live** | `PARCEL_REALTIME_LIVE=1 pytest -m slow tests/test_realtime_live*.py` | two `skipif`s: the env switch **and** a credential | by hand, when someone is watching the spend | the session's own evidence folder |
| **never runs, and why** | — | see below | — | — |

`ci_gate.py` defines the two selections as `COMMIT_MARKERS` / `NIGHTLY_SLOW_MARKERS`
and a hard **`tier-coverage`** gate (both tiers) re-derives all three collections
and reddens if any collected test is selected by neither tier — or by both. That
is the executable form of "a tier went dark".

**What never runs, and why — the honest list:**

- `tests/test_realtime_live.py` / `tests/test_realtime_live_smoke.py` — opt-in
  live provider calls. They **skip by default**, need `PARCEL_REALTIME_LIVE=1`
  plus a credential, and cost money. They are in the nightly's selection and
  skip there; that skip is visible in the run folder.
- `tests/test_release_parity_wheel.py` — needs `ensurepip`
  (`apt install python3.14-venv`). Absent on this host, so it **errors at setup**
  in the nightly rather than skipping. Recorded as an environmental red.
- The browser half of `src/parcel_robot/ui/index.html` — 2,365 lines, executed by
  zero tests in any tier. Registered debt (audit §Tests), not R26's.
- Anything under `evals/` that is not reachable from `testpaths = ["tests"]` —
  eval harnesses are run by their own runners, not by pytest.

### The load-sensitive tests, and who owns them

Three wall-clock assertions sat inside the hard commit gate with no owning card,
having reddened at least six recorded gate runs across four cards. **Card R26
owns them now.** They are marked `load_sensitive` (`scripts/load_guard.py`):

| Test | Guard | Runs in nightly? |
| --- | --- | --- |
| `test_cpu_budget_proxy.py::test_build_report_includes_budget_and_does_not_prove` | skip-with-measurement above a 0.30 busy fraction | yes — `PARCEL_LOAD_GUARD=off` |
| `test_cpu_budget_proxy.py::test_cli_writes_json` | same (found by R26, not on the audit's list) | yes |
| `test_dynamic_costs.py::test_cost_field_vectorization_performance` | same | yes |
| `test_runtime.py::test_runtime_streaming_text_executes_only_final_transcript` | contention-scaled thread deadline, never skipped | yes |

The busy-fraction pin is derived from the four load readings recorded in
`R8_STATUS.md` and `R13_STATUS.md`, and `tests/test_load_guard.py` re-asserts
that the pin still separates every recorded red from every recorded green. Each
guarded test gained an **unconditional companion** covering everything in it that
does not depend on the clock, so the commit tier's behavioural coverage is
unchanged.

### The time-bomb sweep

`scripts/future_clock.py` runs the fast suite with the calendar moved forward
(400 days by default) so that a test mixing the real clock with a pinned clock
fires in the nightly instead of in an unrelated card's gate a month later. It is
a HARD nightly stage, it is fail-closed (loading it unarmed aborts the run rather
than running unshifted), and `tests/test_future_clock_guard.py` seeds a bomb of
the exact shape the auditor fixed on 2026-08-21 and asserts the sweep detonates
it while an ordinary run does not.

## Handoffs (things the runner needs but could not add without touching owned code)

These are real gaps surfaced while wiring the gate. The runner works today
without them; closing them strengthens the named gate.

1. **Acoustic latency coverage is incomplete.** The product now appends
   turn-bearing rows to `evals/latency/ledger.jsonl`, and
   `evaluate_latency_ledger` ratchets the latest row against the pinned
   baseline. Current duplex rows are text-path measurements, however, so a
   latest row can omit microphone, endpointing, and playback-device stages.
   Keep the percentile-pin checks and add a real capture/playback writer before
   treating a green ledger gate as hardware acoustic evidence.
2. **Ruff debt (7 fingerprints)** remains in `camera_channel` and
   `detection_adapter`. The gate ratchets against
   `scripts/ci_ruff_baseline.json` so this inherited debt does not block
   commits, but it should be burned down to zero; re-pin with
   `ci_gate.py --update-ruff-baseline` after each cleanup.
3. **One legacy walk_with_me row lacks a collision field.** The current
   field-bearing row participates in hard-safety and is green, while the older
   stub cannot. Require `hard_collision_total` on every future row and retire
   or migrate the legacy record before claiming complete ledger coverage.
4. **Acoustic loop needs a host PipeWire rig** (`pw-cli`/`pw-play`/…); it is
   offline but not drop-in headless, so it is not in the commit tier. It runs in
   the nightly `slow-suite` only where the rig is present.
