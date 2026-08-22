# The owner's persona-prompt edit and the ten pins it reddened · Fable · 2026-08-22

**Event.** At 02:10:08–11 the owner added a one-line identity prelude to each
of `prompts/personalities/{calm_guardian,gentle_companion,playful_companion}.yaml`
("You are a calm guardian." …) from the IDE. Intentional, attributed (file
open in the IDE; no session claimed it). Committed in `5c7a2aa` with its
packaged mirror re-synced (06:20:44Z).

**Blast radius, measured by the P0 verifier's serial gate:** ten default-suite
failures, zero of them attributable to any P0 card — all pinned hashes over
the persona text: the per-personality SI digests (×3), the v1 re-render pin,
the session-text provenance pin, the runtime/driver prompt-plane pins (×3),
the corpus capture-version re-render, and the `conversation_quality_v1`
manifest's three persona `sha256` locks.

## Decision (under the owner's 2026-08-22 "loosen the fail-safes" ruling)

Two different things were red, and they get two different answers:

1. **The CURRENT pin is the repo's own intended mechanism for a deliberate
   prompt change — use it, don't demote it.** `prompting.py` states the rule
   in its own refusal text: "bump `SI_VERSION` and register the new digests."
   Done: `SI_V3 = "si-companion-v3"`, `SI_VERSION = SI_V3`, v3 guardrails
   registered as v2's wording (only the persona files moved), v3 digests
   derived under the v3 label and registered; v1 and v2 rows untouched so
   every recorded session stays attributable to the text that produced it.
   The session-text provenance pin and the `conversation_quality_v1`
   manifest's three persona shas moved mechanically with the edit (that
   manifest is on the gate's `known_unpinned` list — no sentinel moved).
   **The eval's frozen results row predates the prompt change and stays as the
   v2-era baseline; the next run is a new row, not a re-measurement** — the
   R14-style "nothing about the eval changed" claim is NOT made here, because
   the prompt is an input and did change.
2. **The HISTORICAL reproducibility pins cannot be re-pinned honestly.**
   `test_the_v1_si_still_renders_to_its_v1_pins` and
   `test_the_corpus_capture_version_is_still_rendered_by_this_tree` assert
   that v1 text is still reproducible from source — it is not, because
   historical versions render from the LIVE persona files. Re-pinning v1 to
   the new text would falsify the 25-thread corpus's provenance. Both are now
   `xfail(strict=True)` with the reason naming **FZ-1 (`task_13`)**: per-version
   frozen prompt snapshots. `strict` means the day FZ-1 restores
   reproducibility, leaving the marker is itself a red.

## Verification

`tests/test_realtime_prompting.py tests/test_realtime_driver.py
tests/test_realtime_corpus_replay.py tests/test_conversation_quality_v1.py
tests/test_ci_gate.py` (with `-m "slow or not slow"`): **278 passed, 2 xfailed**
(the two FZ-1 markers). `tools/sync_runtime_assets.py --check`: parity OK
91/91. One instructive stumble on the way: the first v3 registration used
digests rendered under the v2 label and the renderer refused v3 outright
(`si_guardrails` selects wording by version) — 51 red for two minutes; the
refusal is the mechanism working, and the digests were re-derived under v3
before registration (they matched).

## Files touched (all mine; staged separately from in-flight P1/P2 work)

`src/parcel_robot/realtime/prompting.py` (v3 constants, guardrails branch,
digests, `__all__`), `tests/test_realtime_prompting.py` (xfail, version-set,
session-digest pin, shipped-default assertion → v3),
`tests/test_realtime_corpus_replay.py` (xfail),
`evals/companion/conversation_quality_v1/manifest.json` (three persona shas),
this note, the board rows for FZ-1 / XD-1 / HY-1 and their cards
(`task_13..15`).
