# Task 13 — FZ-1: historical prompts render from frozen snapshots, not live files

**Executor:** Claude Opus · **Verifier:** Fable · **Board:** `../TASK_BOARD.md`
(P0 standing rules apply). **Evidence:** the owner's 2026-08-22 02:10 edit to
`prompts/personalities/*.yaml` reddened ten tests; eight were the current
pin (resolved: `SI_V3` registered per `prompting.py`'s own rule), two were
HISTORICAL reproducibility pins now carried as `xfail(strict=True)`:
`test_the_v1_si_still_renders_to_its_v1_pins` and
`test_the_corpus_capture_version_is_still_rendered_by_this_tree`. Audit §4:
"the hash-lock discipline is fatal to a learning loop as designed" — this is
the concrete instance: a one-line persona tweak broke the provenance of a
52-query voice corpus captured under v1.

## Why
`render_system_instruction(version=SI_V1)` composes v1's preamble/guardrails
with the LIVE persona files, so any persona edit silently changes what "v1"
renders to. The corpus fixtures store v1 digests that must stay verifiable
from source, or they become unverifiable numbers. Prompts will keep changing
(P2-A/P2-B add owner-model content; the owner tunes personas by hand) — the
fix is structural, not another re-pin.

## Work
1. **Per-version frozen snapshots:** `prompts/personalities/_frozen/<si_version>/*.yaml`
   for `si-companion-v1` and `si-companion-v2`, byte-identical to the files
   as of commit `e63be08` (pre-edit; `git show e63be08:prompts/personalities/<f>`).
   `PromptLibrary`/`render_system_instruction(version=...)` read the snapshot
   when `version != SI_VERSION`; the live files render only the current
   version. New versions snapshot the live files at bump time (a tiny
   `tools/freeze_si_version.py` that also registers the digests).
2. **Remove the two xfails** — both tests must go green through the real
   code path, and `strict=True` means leaving the marker is itself a red.
3. Seeds RED: editing a frozen snapshot (its digest is pinned by the existing
   `SI_DIGESTS` row); rendering a historical version from live files.
4. `runtime_assets` mirror: the frozen dir ships (release-parity) —
   `tools/sync_runtime_assets.py --write` after adding it.

OWNS: `realtime/prompting.py` (version→source resolution only; coordinate
with P2-A's `owner_notes` region if still in flight), `prompts/personalities/_frozen/`,
`tools/freeze_si_version.py`, the two test files' xfail removal,
`tests/test_fz1_*.py`, `task_13/` docs. MUST NOT TOUCH: the live persona
files, `evals/**` fixtures, the broker.

## Definition of done
Both historical tests green without markers; v1/v2/v3 all render to their
pins from a tree whose live persona files differ from v1/v2; seeds RED;
`FZ1_STATUS.md`.
