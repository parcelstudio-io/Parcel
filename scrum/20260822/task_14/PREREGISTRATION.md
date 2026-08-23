# XD-1 — PRE-REGISTRATION (written before any measurement)

**Card:** `README.md` (this folder) · **Executor:** Claude Opus · **Verifier:** Fable
**Written:** 2026-08-22T19:24:50Z · **HEAD:** `e15e466`
**Measurement rig:** a scratch `git clone` of the working tree at `e15e466`, at
`/home/jaewoo-jang/.cache/parcel-xd1/tree`, with the git-ignored asset trees
(`models/*` weights, `third_party/{CityWalker,fish-speech,llama.cpp-*,piper}`)
symlinked and the writable ones (`evals/external/**/results`,
`evals/20260820/voice_corpus_v1`, `recordings`) **copied**, so nothing this card
runs can write into the live tree. `parcel_memory.sqlite3` (the owner store) is
deliberately NOT present. The venv is the repo's `.parcel`; import isolation is
forced with `PYTHONPATH=<clone>/src` (verified: `parcel_robot.__file__` resolves
under the clone). Every run has `TMPDIR` unset. **The gate is never run in the
live working tree** — five other batch-B cards are editing it.

Nothing below has been measured at the time of writing. The load average at
writing is `13.44 / 192` (busy fraction 0.070).

---

## 1. The headline claim being tested

> `scripts/ci_gate.py --tier commit` runs the default suite under `pytest -n auto`
> and is **fast without divergence**: the same set of admitted node IDs, the same
> verdict, no test made order-dependent, no test silenced.

## 2. Rows (numbers fixed now; met/missed reported as measured)

| # | Row | Target |
|---|---|---|
| **W1** | `default-suite` stage wall-clock, **serial baseline**, on the scratch clone | recorded, no target (the "before"; the live tree's last recorded figure is 407 s) |
| **W2** | `default-suite` stage wall-clock, **two-phase xdist** | **≤ 90 s** |
| **W3** | Speed-up W1/W2 | **≥ 4.5×** |
| **W4** | Full `--tier commit` end-to-end wall-clock (card §3's number, kept verbatim) | **≤ 90 s** |
| **D1** | Admitted node IDs: `collect(phase A) ∪ collect(phase B)` vs `collect(-m "not slow")` | **0 added, 0 removed** (exact set equality; counts published) |
| **D2** | Verdict identity: the set of failed/errored node IDs, parallel vs serial baseline | **identical**, on **each** of three consecutive runs |
| **D3** | Nothing silenced: skipped/xfailed node IDs, parallel vs serial | parallel set ⊆ serial set ∪ {load-guard skips, each carrying its measured reason}; **no new `skip`/`xfail`/deselect introduced by this card** |
| **D4** | Flake bar: three consecutive two-phase runs | **zero divergence** between the three, and vs W1's baseline |
| **D5** | Order-independence census (**channel: module-import order**): a serial run with the test-file order shuffled by `random.Random(20260822).shuffle` | same verdict set as W1; every divergence named and classified |
| **D6** | Process-state census (**channel: process-environment mutation**, plus `sys.modules` deletion/replacement and cwd change): per-test snapshot/diff | published as a named table; any test that leaks is named with its channel |
| **D7** | Repo-write census: every test that writes a path **git would notice** (tracked file modified, or an untracked non-ignored file created) under the repo root during the run | published; target **0 offenders** after fixes |
| **L1** | ruff on this card's files and repo-wide fingerprint census | **exactly 7** baseline fingerprints, **new 0**; no `noqa` added, baseline never re-pinned |

### Decision rule fixed in advance for D7's guard

The repo-write guard ships **ON by default** if and only if the census (D7) is
empty after my fixes. If it names an offender that is not mine to fix, the guard
ships **opt-in** (`PARCEL_REPO_WRITE_GUARD=on`) and the offender is listed for its
owner — because the board's standing rule 1 forbids adding a new allowlist, and a
per-test exemption table is exactly that. The definition of an offense is
delegated to `.gitignore` (via `git check-ignore`), so the guard carries **no
allowlist of its own**.

## 3. Design being registered (so the verifier can check I did not move it)

* `default-suite` becomes **two phases whose union is a partition of
  `COMMIT_MARKERS` by construction**: phase A `-n auto -m "<COMMIT_MARKERS> and
  not load_sensitive"`, phase B serial `-m "<COMMIT_MARKERS> and
  load_sensitive"`. Written as `f"{COMMIT_MARKERS} and (not) load_sensitive"`
  from the same constant, so the two phases cannot drift apart and
  `tier-coverage` cannot disagree with them.
* Divergences that are **not** wall-clock assertions are **fixed at the source**,
  not marked. Marking a behaviour test `load_sensitive` would make it skippable
  under contention, which is a silencing.
* No hard gate other than `default-suite` is touched. The safety core is not
  touched.

## 4. Seeded-RED proofs registered in advance (one per new guard)

| Seed | Product change seeded | Guard that must go RED |
|---|---|---|
| **S1** | a deliberate test that writes a git-visible file under the repo root | the repo-write guard names **that test** and **that path** |
| **S2** | `scripts/ci_gate.py`'s phase-A marker expression loses `and not load_sensitive` | the marker-coverage/partition test in `tests/test_ci_gate.py` |
| **S3** | phase B deleted (or its marker made non-complementary) so some `not slow` test is admitted by neither phase | the partition test in `tests/test_ci_gate.py` |
| **S4** | `runtime.py`: `_p1b_install_learned_map()` moved **after** `_attach_configured_camera_ingress()` | `tests/test_p1b_map_learns.py::test_the_runtime_region_wires_all_three_seams` |
| **S5** | `runtime.py`: an **unrelated statement inserted between** the attach and the first `self._thread` assignment | the same test stays **GREEN** (this is the over-specification being removed) |

Every seed is applied to the **product**, the named test is watched failing (or
passing, for S5), the file is restored and verified byte-identical by `sha256sum
-c`, `__pycache__` is purged, and the test re-run green.

## 5. What this card will NOT claim

* Nothing about the live working tree's gate verdict — every number here is from
  the scratch clone at `e15e466`, which lacks the owner store and any
  uncommitted batch-B work.
* Nothing about wall-clock on an idle machine: five cards are executing
  concurrently. The load average is recorded next to every timing row, and a
  miss caused by load is reported as a miss, not explained away.
* Nothing about the nightly tier's wall-clock.
