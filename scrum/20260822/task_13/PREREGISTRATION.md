# FZ-1 pre-registration — written BEFORE any acceptance measurement

**Card:** `scrum/20260822/task_13/README.md` · **Executor:** Claude Opus ·
**Verifier:** Fable · **Written:** 2026-08-22, before a line of product code
was edited and before any acceptance number was taken.

## What was already known when this was written (declared, not an acceptance row)

A feasibility probe ran first, to establish the card is buildable at all:
the three `prompts/personalities/*.yaml` files as of commit `e63be08` were
extracted to `/home/jaewoo-jang/.cache/parcel-fz1/probe/personalities/` and
rendered through `render_system_instruction(library=<probe>, version=…)`.
Result: `SI_V1` 3/3 and `SI_V2` 3/3 digests equal to their `SI_DIGESTS` rows;
`SI_V3` 3/3 unequal (v3 is the post-edit text). That probe is the reason the
snapshot bytes below are "e63be08 for v1/v2, live for v3". It is a *premise*,
not an acceptance row, and it is listed here so it cannot be re-sold later as
a result.

## The property under test

A HISTORICAL SI version must render from a frozen per-version snapshot, never
from the live persona files. Today an owner edit to `prompts/personalities/*.yaml`
changes what `render_system_instruction(version="si-companion-v1")` renders —
which is why two reproducibility tests are carried as `xfail(strict=True)`
(`OWNER_PROMPT_EDIT_PINS_FABLE.md` §Decision 2).

Every row below renders through the PRODUCT path — `render_system_instruction`
— and compares **bytes/digests**. No row greps source text, and no row asserts
a tautology (e.g. "the frozen library's dir is the frozen dir").

## Acceptance rows (thresholds fixed now; a miss is a miss)

| # | Row | Threshold |
|---|---|---|
| 1 | **Current renders from LIVE.** In a sandbox prompts tree (`PARCEL_ROOT` → a copy of `prompts/`), the current version renders byte-identically to today: 3/3 personalities equal `SI_DIGESTS[SI_VERSION]`. Then seed one live persona YAML; that personality's current-version digest MOVES and no longer equals its pin. | 3/3 equal unseeded · 1/1 moved seeded |
| 2 | **THE row — a historical version does not move when the live file is edited.** Same sandbox, same seed applied to the live persona YAML: `render_system_instruction(profile_id=p, version=v).digest == SI_DIGESTS[v][p]` for v ∈ {v1, v2} × 3 personalities. | 6/6 |
| 3 | **Reproducible from the snapshots ALONE.** Sandbox with every live `prompts/personalities/*.yaml` DELETED: v1 and v2 still render to their 6 pins; the current version raises (it genuinely needed the live files). | 6/6 + 1 raise |
| 4 | **The current version is already frozen for the next bump.** `prompts/personalities/_frozen/<SI_VERSION>/<p>.yaml` bytes == the live `prompts/personalities/<p>.yaml` bytes. | 3/3 byte-identical |
| 5 | **Both xfail(strict=True) markers removed and both tests pass unmarked.** `test_the_v1_si_still_renders_to_its_v1_pins` (tests/test_realtime_prompting.py) and `test_the_corpus_capture_version_is_still_rendered_by_this_tree` (tests/test_realtime_corpus_replay.py); zero `xfail` markers left in either file. | 2 passed · 0 xfailed · 0 xpassed |
| 6 | **Refusals stay honest.** A registered historical version with no snapshot refuses by name (the message names `tools/freeze_si_version.py`), and an UNregistered version still refuses at the guardrails (message contains "no guardrails text") rather than at the snapshot — i.e. the pre-existing refusal ordering is preserved. | 2/2 |
| 7 | **`tools/freeze_si_version.py --check` on this tree.** Exit 0; every registered version's pins re-derived from its snapshot alone. | exit 0 · 9/9 digests (3 versions × 3 personalities) |
| 8 | **The freezer actually freezes.** `tools/freeze_si_version.py --version <SI_VERSION> --force --prompts-root <sandbox>` writes 3 snapshot files byte-identical to the sandbox's live persona files and prints the 3 registered current pins; without `--force` it refuses to overwrite an existing snapshot. | 3/3 files · 3/3 digests · 1 refusal |
| 9 | **Targeted suite green.** `.parcel/bin/python -m pytest tests/test_fz1_frozen_si_snapshots.py tests/test_realtime_prompting.py tests/test_realtime_corpus_replay.py tests/test_realtime_driver.py tests/test_release_parity.py tests/test_emotion_gesture_library.py tests/test_yield_policy.py -m "slow or not slow"` | 0 failed · 0 error · 0 xfailed |
| 10 | **ruff clean on OWNS, ratchet untouched.** `.parcel/bin/ruff check` on the edited files → 0 findings; `scripts/ci_ruff_baseline.json` unmodified; ratchet stays exactly 7. | 0 new findings · baseline byte-identical |
| 11 | **Release parity.** `tools/sync_runtime_assets.py --check` exits 0 after `--write`; packaged file count 91 → 100 (9 new frozen persona YAMLs). | exit 0 · count 100 |

## Seeded-RED proofs (one per new guard; product seeded, not the test)

Every seed edits the **product** (`prompting.py`, a snapshot YAML, or the
tool), runs the NAMED test, records the red, then restores the file
byte-identically verified by `sha256sum`, purges `__pycache__`, and re-runs to
green.

| Seed | What is seeded (in the product) | Named test that MUST go red |
|---|---|---|
| S1 | `personality_source()` returns the live library for every version (the pre-FZ-1 behaviour) | `test_a_historical_version_ignores_an_edit_to_the_live_persona_file`, `test_the_v1_si_still_renders_to_its_v1_pins`, `test_the_corpus_capture_version_is_still_rendered_by_this_tree` |
| S2 | one byte appended to `prompts/personalities/_frozen/si-companion-v1/gentle_companion.yaml` | `test_every_registered_version_is_reproducible_from_its_snapshot_alone` |
| S3 | one byte appended to `prompts/personalities/_frozen/si-companion-v3/calm_guardian.yaml` | `test_the_current_version_is_already_frozen_for_the_next_bump` |
| S4 | the missing-snapshot `raise` in `frozen_prompt_library()` replaced by a silent fall-back to the live library | `test_a_historical_version_without_a_snapshot_refuses_by_name` |
| S5 | `render_system_instruction` resolves the CURRENT version from its snapshot too | `test_the_current_version_still_renders_from_the_live_persona_files` |

## What this pre-registration does NOT claim

- Nothing about hosted-model behaviour: no session is opened, no token spent.
  These rows are about which **bytes** the prompt plane renders, not about how
  a model responds to them.
- Nothing about the 25-thread corpus being *correct* — only that its stored
  `si_digest` values are re-derivable from this tree, which is what makes them
  evidence rather than remembered numbers.
- Nothing about the v3 digests themselves: those were registered by the owner's
  verifier this morning and are taken as given.

## Files this card may write (OWNS)

`src/parcel_robot/realtime/prompting.py` (version→source resolution only),
`prompts/personalities/_frozen/**`, `tools/freeze_si_version.py`,
`tests/test_fz1_frozen_si_snapshots.py`, the two xfail-marker lines in
`tests/test_realtime_prompting.py` and `tests/test_realtime_corpus_replay.py`,
`scrum/20260822/task_13/**`, and the generated
`src/parcel_robot/runtime_assets/**` mirror entries for the frozen dir.
MUST NOT TOUCH: the live persona files, `evals/**` fixtures, the broker.
