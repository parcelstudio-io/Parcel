# FZ-1 design — a historical SI version reads a frozen snapshot

Card `task_13/README.md` · pre-registration `PREREGISTRATION.md` (sha256
`8f0e19ee…`). Written before the resumed implementation pass; later edits, if
any, are listed in `FZ1_STATUS.md`.

## a. Purpose

The SI has three ingredients: `prompting.COMPANION_PREAMBLE` (code),
`prompting.si_guardrails(version)` (code, version-selected since card R5) and one
personality YAML (`prompts/personalities/<p>.yaml`, from disk). Two are versioned;
the third was read LIVE for *every* version, so the owner's 2026-08-22 02:10 persona
edit changed what `render_system_instruction(version="si-companion-v1")` produced and
the v1 pins — the provenance of a 25-thread, 52-query voice corpus — stopped being
re-derivable from source. Re-pinning v1 would have relabelled which words those threads
were captured under, so two tests were carried as `xfail(strict=True)` naming this card.
FZ-1 supplies the missing third leg: one immutable persona snapshot per SI version,
read by every version but the current.

## b. Architecture fit (named seams)

- **Seam added:** `realtime/prompting.py:personality_source(version, *, library)`
  — version → the `PromptLibrary` that version's persona text comes from. The
  only new decision point; `render_system_instruction` calls it in one line.
- **Product path in:** `runtime.py:2546` builds
  `prompting.InstructionSource(si_version=SI_VERSION, …)` → `.current()` →
  `render_session_instructions` → `render_system_instruction` →
  `personality_source`. The live robot always passes `SI_VERSION`, so it always
  takes the live-files branch: **FZ-1 changes nothing about the text the robot
  ships today.**
- **Who reaches the historical branch** (corrected 2026-08-23, verifier F1: an
  earlier draft named the `evals/` pair, and neither renders a historical
  version). Only non-test caller: `tools/freeze_si_version.py --check` →
  `rendered_digests:114` → `frozen_prompt_library`. Everything else renders the
  CURRENT version and always did — `evals/…/schema.py:473` re-renders only
  inside `if fixture.si_version == SI_VERSION:` (`:472`); `build_manifest.py:109`
  passes no `version=`, so it defaults to `SI_VERSION`; `schema.py:466` is
  `si_pin`, a lookup that renders nothing. `schema.py:473` staying current-only
  is deliberate and remains a handoff, not a change (`FZ1_STATUS.md` handoff 4;
  `evals/**` is MUST-NOT-TOUCH here). Same fact as the status doc's "does not
  prove" bullet: the seeds prove the guards, and the runtime never takes the
  frozen branch by design.
- **Storage:** `prompts/personalities/_frozen/<si_version>/<p>.yaml`
  (`prompting.FROZEN_PERSONAS_DIRNAME`). Under `personalities/` so
  `paths.resolve_prompts_root`, the `prompts` dir asset and the `runtime_assets`
  mirror carry it with no new registration; the leading underscore keeps it out
  of `PromptLibrary._personality_ids()`, which globs `personalities/*.yaml` and
  never recurses — `list_personalities()` still returns exactly three.
- **Reader:** `prompting._FrozenPromptLibrary(PromptLibrary)` overrides `_dir` for
  the `"personalities"` section only; `system/`, `functions/`, `schemas/`, `dynamic/`
  still resolve against the live root, none being SI text. **Writer:**
  `tools/freeze_si_version.py` (`--version` snapshots at bump time, `--check`
  re-derives every registered pin from its snapshot alone).
- **Composition:** no batch-A card (VENUE-1 / CAP-1 / OT-2 / DOOR-1) touches
  `prompting.py`, and `CODEBASE_INDEX.md` §"Card markers" lists **zero** markers
  in it (P2-A's `owner_notes` is the DI dataclass field at `:590`, not a marked
  region, and is untouched). No `core/hard_stop`, `reactive_safety` or
  `SafetySupervisor` symbol is reachable: this is filesystem resolution only.

## c. Interfaces and contracts

```python
FROZEN_PERSONAS_DIRNAME = "_frozen"
frozen_personas_dir(version, *, prompts_root=None) -> Path
frozen_prompt_library(version, *, prompts_root=None) -> PromptLibrary  # missing ⇒ PromptPlaneError
personality_source(version=SI_VERSION, *, library=None) -> PromptLibrary
```

`personality_source` rule: `version == SI_VERSION` → `library` if given else
`default_prompt_library()`; otherwise → `frozen_prompt_library(version,
prompts_root=library.root if library else resolve_prompts_root())`. A caller's `library=`
therefore selects the prompts **root**, and never resurrects the live persona files for
history — `build_manifest.py` and the corpus tests all pass one.
`render_system_instruction` keeps its signature. One ordering contract is now explicit:
`si_guardrails(version)` is evaluated **before** the persona lookup, so an unregistered
version still refuses with "no guardrails text" and no path component is built from an
unregistered string. No new config key, env var or behaviour flag; the current
version's resolution is byte-identical to pre-FZ-1.

## d. Data flow and lifecycle

Read-only at runtime, single-threaded per render; `PromptLibrary`'s existing
`threading.RLock` cache is inherited unchanged, and `_FrozenPromptLibrary` is
built per call inside `frozen_prompt_library`, so no cross-version cache can
alias. No process, socket, file lock or thread is created. The only writes are by
`tools/freeze_si_version.py`, run by hand at bump time: `shutil.copyfile` (bytes,
no YAML round-trip), refusing to overwrite an existing snapshot without `--force`
— a rewritten snapshot silently re-attributes every session captured under it.

## e. Hardware compatibility (Go2 EDU+ / Jetson Orin NX, aarch64, CPython 3.10)

Invariant: **the frozen snapshots are shipped assets, so a packaged install
renders history exactly as a checkout does.** `paths.resolve_prompts_root` falls
through `parcel_roots()` to `packaged_assets_root()` when no repo tree is present
— the Orin case (a wheel, no `prompts/` beside it). The nine snapshot files are
mirrored into `runtime_assets/prompts/personalities/_frozen/` by
`tools/sync_runtime_assets.py` and recorded in `runtime_assets/MANIFEST.json`
with per-file sha256. Pinned by two tests: `tests/test_release_parity.py`
(`EXPECTED_ASSET_COUNT`, byte-parity of every packaged file, the generator's
`--check`) and `test_fz1_frozen_si_snapshots.py::test_a_wheel_can_still_render_every_historical_version`,
which points `PARCEL_ROOT` at `packaged_assets_root()` and re-renders all six
historical digests from there. Venue-independent by construction: pure-Python `pathlib`
+ `yaml` over text — no arch-specific wheel, CUDA or device, and no absolute or dev-box
path in the product or the tool (`freeze_si_version.py` derives its root from
`Path(__file__).parents[1]`; `prompting.py` uses only `resolve_prompts_root()` or a
caller's root). Digests are SHA-256 over UTF-8, byte-identical on aarch64; nothing to
configure on the Orin. **UNKNOWN:** nothing hardware-shaped; the open question is only
whether the Orin ships the repo tree beside the wheel — two identical roots either way.

## f. Test strategy → the pre-registered rows

`tests/test_fz1_frozen_si_snapshots.py` measures through
`render_system_instruction` and compares **digests of rendered text**; no row
greps source or asserts a path equals itself. Rows 1/2/3 use a `PARCEL_ROOT`
sandbox (byte-for-byte copy of `prompts/`) so the seed edits a *live persona file*
the way the owner did without touching the shared tree: row 1 the current version
moves, row 2 (THE row) v1/v2 do not, row 3 the live files are deleted and history
still renders while the current version raises. Row 4 current snapshot ≡ live
bytes; row 5 the two xfail removals passing unmarked; row 6 the two refusals in order;
rows 7–8 the tool; row 9 the targeted suite; row 10 ruff; row 11 release parity. Seeds
S1–S5 each edit the **product** on a byte-identical scratch copy of `src/`, watch the
named test redden, restore by sha256, re-run green.

## g. Risks / not covered

- `frozen_personas_dir` interpolates `version` into a path. Safe through
  `render_system_instruction` (guardrails refuse first), but `frozen_prompt_library`
  is public: attacker-shaped text could aim the snapshot dir elsewhere under the
  prompts root. No new refusal added (prototype rule: no fail-closed defaults).
- A snapshot is only as honest as the moment it was taken. `--check` and
  `test_the_current_version_is_already_frozen_for_the_next_bump` catch a bump
  that never ran the tool, but nothing forces a human to run either.
- Not covered: hosted-model behaviour (no session, no spend); whether the corpus
  is *correct* (only that its `si_digest` values are re-derivable);
  `evals/.../schema.py:473` still re-renders only when `si_version == SI_VERSION`
  — history is now reproducible so that guard could widen, but `evals/**` is
  MUST-NOT-TOUCH here: a handoff, not a change.
