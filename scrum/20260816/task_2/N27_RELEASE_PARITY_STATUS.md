# N27 — source/package release parity

**Date:** 2026-08-16 · **Card:** [NEXT.md](../../../backlog/NEXT.md) N27 (HLD P0, rank 1B)
**Executor:** Claude Opus (wiring/integration lane) · **Baseline:** `8473a51` on `main`
**Venv:** `/home/jaewoo-jang/Desktop/Projects/Parcel/.parcel/bin/python`
**Parallel sprint:** [task_1](../task_1/README.md) is Sol's N24 gateway slice in the same
checkout. Nothing here touches `src/parcel_robot/bridge/`, the gateway tests, or
`pyproject.toml`; their uncommitted work was left staged exactly as found.

## What was broken, in one paragraph

`src/parcel_robot/paths.py` resolves assets source-first and packaged-last, so a
source checkout **never reads the packaged tree** and a wheel **always does**. The
packaged tree was a hand-maintained 2026-08-10 snapshot, and nothing enforced that
`tools/sync_runtime_assets.py` had ever been run. A wheel therefore shipped
`safety.max_vx: 0.45` against source `0.9`, `progress_watchdog.timeout_steps: 400`
against `200`, `align_enter_deg: 28.0` against `55.0`, and omitted the `perception:`
and `route_memory:` blocks entirely — while `tests/test_runtime_assets.py` was green,
because it asserted only that those files *exist*. Three further assets
(`configs/navigation/pose.yaml`, `configs/scenes/city_block.semantics.yaml`, and 12 of
14 `configs/navigation/models/*.yaml`) were never packaged at all.

## Frozen contract surface

One direction, no exceptions: repo-root `configs/`, `prompts/`, `maps/`, `fixtures/`
are canonical; `src/parcel_robot/runtime_assets/` is a build product. Two files inside
it are generated rather than mirrored (`README.md`, `MANIFEST.json`).
`src/parcel_robot/config/robot.yaml` is a declared **side mirror** — all five console
scripts read that third copy in a wheel without importing `parcel_robot.paths`, so it
is written by the same run and covered by the same manifest.

`MANIFEST.json` carries no timestamp. A clock-derived field would make the generator
non-idempotent and make the zero-diff gate flap, destroying the card's own exit
criterion.

## What changed

| Fix | File | Change |
| --- | --- | --- |
| C1 | `src/parcel_robot/runtime_assets/configs/navigation/{default,models/grid}.yaml` | Regenerated from source. Exactly the two files the analysis predicted moved. |
| C2 | `maps/`, `configs/perception/` (new) | `git mv` of three assets that existed **only** inside `runtime_assets/`. A naive mirror would have deleted the only copy. |
| C2 | `src/parcel_robot/low_viewpoint/samples.py` | `packaged_assets_root() / REL` → `resolve_asset(...)`. Required, or the relocation breaks a source checkout too. |
| C2 | `fixtures/storefronts/{manifest.yaml,README.md}` | Source declared the *packaged* copy canonical — the direction was inverted. Merged the packaged provenance header in; parsed YAML was already equal, so this is a comment-only, zero-behaviour change. |
| C3 | `tools/sync_runtime_assets.py` (278 lines, rewritten) | Explicit `INCLUDE`/`EXCLUDE` ship set, `--check`/`--write`/`--dest`, in-memory render, writes only what differs, emits `MANIFEST.json`. |
| C3 | `src/parcel_robot/paths.py` | `packaged_manifest_path()` / `load_packaged_manifest()`. Added to the existing module deliberately: `evals/external/barn_policy_specs.py` hashes the `src/parcel_robot/**/*.py` **membership tuple**, so a new module there would move a frozen external-eval digest. |
| C4 | `tests/test_release_parity.py` (188 lines, new) | 10 commit-tier tests. |
| C4 | `tests/test_release_parity_wheel.py` (167 lines, new) | 4 nightly tests: build a wheel, install into an empty venv, compare effective config. |
| C4 | `tools/release_parity_probe.py` (123 lines, new) | Effective-config digest over resolved **values**, with per-component sub-hashes. |
| C4 | `tests/test_runtime_assets.py` | Replaced the vacuous fallback "speech contract" test with byte-equality (see below). |
| C5 | `scripts/ci_gate.py` | `evaluate_release_parity()` + `RELEASE_PARITY_NODE_IDS`, wired HARD into commit **and** nightly. |
| C5 | `tests/test_ci_gate.py` | 5 seeded self-tests, into tmp copies only. |

## Derived constants, with provenance

* **90 packaged assets + 1 side mirror = 91 checked.** Derived from the ship set, not
  tuned to a gate. Pinned as a literal in `test_manifest_asset_count_is_the_pinned_literal`
  and in `test_release_parity_is_green_on_the_committed_tree`, per the
  `DIGEST_SENTINELS` convention — deriving it from `len()` would let the ship set
  shrink silently.
* **76 → 90 packaged files.** +1 `configs/navigation/pose.yaml`, +1
  `configs/scenes/city_block.semantics.yaml`, +12 `configs/navigation/models/*.yaml`.

## Four effective moves in the released artifact

The two-file C1 diff understates the change: two of the four moves are invisible in
the diff because the packaged file *omitted* the key and the wheel silently took a
code default.

| key | stale wheel | now | source of the stale value |
| --- | --- | --- | --- |
| `safety.max_vx` | 0.45 | 0.9 | packaged file, line 37 |
| `progress_watchdog.timeout_steps` | 400 | 200 | packaged file, line 28 |
| `safety.predictive_mode` | `stop` | `projected_speed_cap` | key ABSENT → `pipeline.py` default |
| `safety.person_slow_m` | 2.5 | 2.0 | key ABSENT → `pipeline.py` default |

**Flagged, not resolved:** `person_slow_m` 2.5 → 2.0 moves the released artifact the
**less** conservative way. It is not a regression against source — source has always
said 2.0, and `configs/navigation/default.yaml` marks it `DIVERGENCE, DOCUMENTED
(2026-08-11, DOC-1)`, tracked as OPEN QUESTION 6 in
`scrum/20260811/task_1/FOLLOWUP_DESIGNS.md` §8. This card does **not** silently settle
that question by side effect; no source value was changed. `route_memory: false` and
the `perception:` block are behaviourally inert (both loaders default to the same
values), so only the four above are real.

## Gate table — seeded-failure proofs

Positive control first: unmodified tree ⇒ `pytest` GREEN (10 passed) and
`--check` GREEN (`release parity OK: 91 packaged file(s) match source`). Without it a
red-only proof cannot distinguish a working gate from one red for another reason.

| # | Seeded defect | Test verdict | Gate detail |
| --- | --- | --- | --- |
| S1 | packaged `timeout_steps` 200→400 (**the exact HEAD drift**) | **RED** | `configs/navigation/default.yaml: packaged bytes != source` |
| S2 | packaged `align_enter_deg` 55.0→28.0 | **RED** | `configs/navigation/models/grid.yaml: packaged bytes != source` |
| S3 | delete the whole `perception:` block (key-ABSENCE class) | **RED** | `configs/navigation/default.yaml: packaged bytes != source` |
| S4 | unlisted packaged file `models/rogue.yaml` | **RED** | `rogue.yaml: packaged file is not in the ship set` |
| S5 | drop one `assets` entry from `MANIFEST.json` | **RED** | `MANIFEST.json: packaged bytes != source` |
| S6 | side-mirror `config/robot.yaml` drifts | **RED** | `side mirror != configs/robot.yaml` |
| S7 | seed `low_viewpoint_samples.yaml` (packaged-canonical before C2) | **RED** | `configs/perception/...: packaged bytes != source` |
| S8 | drop `pose.yaml` from the packaged tree | **RED** | `configs/navigation/pose.yaml: missing from the packaged tree` |

8 seeds, 8 RED, restored in a `finally` block; post-restore `pytest` GREEN.
`tests/test_ci_gate.py` carries 5 further seeds against the gate evaluator itself,
injected into tmp copies only (the mutation-panel rule).

S3 is the one that matters most: the class of defect that shipped was a **missing
key**, which produced no diagnostics at runtime and could not be caught by key-by-key
assertions. It is caught by bytes.

## Why `test_every_default_asset_resolves_under_the_packaged_root` asserts `is_relative_to`

`paths.parcel_roots` appends the inferred repo root **after** `PARCEL_ROOT`. An asset
missing from the packaged tree therefore still resolves — against the checkout. A bare
"it resolved" assertion passes while the wheel is broken. Asserting the resolved path
is *inside* the packaged root is what makes the test load-bearing; S8 proves it.

## Full run

```
$ .parcel/bin/python scripts/ci_gate.py --tier commit
[  PASS] HARD  release-parity             91 packaged asset(s) byte-identical to canonical source
[  PASS] HARD  release-parity-integrity   10 passed in 0.74s
[  PASS] HARD  default-suite              5431 passed, 9 skipped, 40 deselected in 234.91s
RESULT: PASS — every hard gate green.   elapsed 247.6s
```

`ruff` reports `new 0` against the pinned baseline of 7; every added file is
lint-clean outright, and `scripts/ci_ruff_baseline.json` was **not** regenerated.

**Working tree.** Left uncommitted, per the land-whole-waves convention. `git status`
also shows the concurrent sessions' `backlog/*`, `docs/*`, `pyproject.toml`,
`capture/channels.py`, `src/parcel_robot/bridge/` and three gateway test files — none
touched here. The index was reset after a diff-stat measurement so nothing of theirs
is staged.

## does_not_prove

* **Parity is not correctness.** This proves source and wheel are the *same*, not that
  either is right. `max_vx 0.9`, `align_enter_deg 55.0` and `person_slow_m 2.0` remain
  unproven on hardware; the card's own line stands.
* **No wheel was built or installed on this host.** `tests/test_release_parity_wheel.py`
  is written and lint-clean but is `PARCEL_NIGHTLY`-gated and has **never been
  executed**: `.parcel` has no `setuptools`/`wheel`, and the package is installed
  editable, so no wheel has ever been exercised here. The exit criterion is currently
  proven only *in-process* — `tools/release_parity_probe.py` returns an identical
  five-component digest under the source root and under `PARCEL_ROOT` pinned to the
  packaged tree. **The wheel half is UNVERIFIED until a nightly runs it.**
* **The two confirmed wheel crashes are fixed by construction, not by observation.**
  `configs/scenes/city_block.semantics.yaml` (module-scope resolve in
  `city_semantics.py`, reached by `parcel-sim` and `parcel-panel`) and
  `configs/navigation/pose.yaml` (silent fallback in `navigation/pipeline.py`) are now
  packaged, and a test asserts they resolve inside the packaged root — but neither
  crash was reproduced in a real wheel here.
* **Adding 12 model YAMLs changes `registry.ids()` in a wheel from 2 to 14.** No eval
  depends on it (every eval resolves from source), but it is a behaviour change in the
  released artifact, not a pure packaging fix.
* **The five console scripts still bypass `paths.py`.** They compute
  `REPO_ROOT = parents[2]` and read the third `robot.yaml` copy directly. N27 keeps
  that correct by placing it under the manifest as a declared side mirror; converting
  them and deleting the third copy is a separate card.
* **The BARN external-eval source digests were already stale** before this card and
  were deliberately not re-pinned — that would be an unauthorized re-freeze.

## Handoffs

1. **Run the nightly.** `PARCEL_NIGHTLY=1` plus `pip install "setuptools>=77" wheel`
   into `.parcel` is all `tests/test_release_parity_wheel.py` needs. Until it runs, the
   card's headline exit criterion is proven in-process only. This is the one open item.
2. **N29 (rank 1C) is unblocked.** Its exit was waiting on this manifest;
   `paths.load_packaged_manifest()` is the surface to admit against.
3. **New UNVERIFIED entry** suggested: "the wheel resolves every default asset" —
   claim is now tested, reality is that the test has never executed.
4. **Convention note for future asset edits:** editing `configs/**` now requires
   `tools/sync_runtime_assets.py --write` before commit, or `release-parity` reddens.
   The generated `runtime_assets/README.md` says so in-tree.
