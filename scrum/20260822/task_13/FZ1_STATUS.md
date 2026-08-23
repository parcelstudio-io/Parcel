# FZ-1 status — historical prompts render from frozen snapshots (task_13)

## COMPLETE — 11/11 pre-registered rows MET · 5/5 seeds RED then green

**Executor:** Claude Opus (FIFTH resume, dispatched by the parcel-6c Fable
session at ~06:20 EDT 2026-08-23; predecessors: 15:2x, 16:17, 17:55 on 08-22
and 05:35 on 08-23 — all four killed by kernel OOM kills, none by this card) ·
**Verifier:** Fable · **Card:** `README.md` · **Pre-registration:**
`PREREGISTRATION.md`, sha256
`8f0e19eee8acdd0a46f464c3f8f4edbce80eb1d4e8337cf9b252d27d1aa78da4`
(re-verified 2026-08-23 05:4x, VERBATIM, unmodified by this pass) ·
**Design:** `DESIGN.md` · **HEAD:** `e15e466` · **Evidence:**
`/home/jaewoo-jang/.cache/parcel-fz1/evidence/`.

Rows are appended below as they close. Nothing here is a claim until its
command and result are printed. Every number below was re-measured by this
pass on 2026-08-23; the predecessors' 17:5x evidence files are kept for the
verifier but nothing is claimed from them.

**How to read this file.** It was written incrementally, row by row, as
crash insurance — four predecessors were killed mid-card — so the evidence comes
first and the register summary follows it. Jump to: **Headline** · **What
changed** · **Rows at a glance** · **What this does NOT prove** · **Deviations**
(7) · **Owner-gated rows** (none) · **Handoffs** · **Resumed from** — all under
`## `-level headings in the second half. Rows appear in the order they were
measured (7, 8, 11, 10, 9), not in numeric order.

## Premise re-verified before measuring (not an acceptance row)

The pre-registration's premise is that the snapshots hold `e63be08` bytes for
v1/v2 and the LIVE bytes for v3. Re-checked byte-for-byte before any row ran:

```
$ for v in 1 2; do for p in calm_guardian gentle_companion playful_companion; do
    git show e63be08:prompts/personalities/$p.yaml | sha256sum   # vs
    sha256sum prompts/personalities/_frozen/si-companion-v$v/$p.yaml ; done; done
OK  v1/{calm_guardian,gentle_companion,playful_companion}   6/6 identical to e63be08
OK  v2/{calm_guardian,gentle_companion,playful_companion}
$ sha256sum prompts/personalities/<p>.yaml  vs  _frozen/si-companion-v3/<p>.yaml
OK  v3/{calm_guardian,gentle_companion,playful_companion}   3/3 identical to LIVE
$ ... vs src/parcel_robot/runtime_assets/prompts/personalities/_frozen/...
OK  9/9 mirror files byte-identical to their source
```

v1 and v2 hold the same bytes (the 08-22 edit was the first persona change
since v1), so the six historical digests differ only by `si_guardrails`.

## Rows

**Product path used by rows 1–4 and 6.** Every digest is taken from
`realtime/prompting.py:render_system_instruction` — the function the runtime
itself reaches through `runtime.py:2545 InstructionSource(...)` →
`InstructionSource.current()` (`prompting.py:905`) →
`render_session_instructions` (`:854`) → `render_system_instruction` (`:453`).
No row re-implements the composition, greps source text, or asserts a path
equals itself. Script: `~/.cache/parcel-fz1/measure_rows_20260823.py`; output
`~/.cache/parcel-fz1/evidence/20260823_rows_1_2_3_4_6.txt`.

```
$ unset TMPDIR; .parcel/bin/python ~/.cache/parcel-fz1/measure_rows_20260823.py
sandbox prompts root: /home/jaewoo-jang/.cache/parcel-fz1/tmp56y8h83w/r12/tree/prompts
ROW 1a current version unseeded: 3/3 equal SI_DIGESTS[si-companion-v3]
ROW 1b seeded gentle_companion: moved=1/1 · untouched still pinned 2/2
ROW 2 THE ROW — all three live personas seeded, v1+v2 unmoved: 6/6

deleted 3 live persona files from the sandbox
ROW 3 snapshots alone: 6/6 · current version raise: FileNotFoundError: [Errno 2]
  No such file or directory: '…/r3/tree/prompts/personalities/gentle_companion.yaml'

ROW 4 prompts/personalities/_frozen/si-companion-v3: 3/3 byte-identical to the live files

ROW 6a missing snapshot refuses by name: 1/1
  message: si_version 'si-companion-v1' is not the current version (si-companion-v3)
  and has no frozen persona snapshot at …/_frozen/si-companion-v1. A historical version
  must not be re-rendered from the LIVE persona files — … Create the snapshot with:
  tools/freeze_si_version.py --version si-companion-v1
ROW 6b unregistered version refuses at the guardrails first: 1/1
  message: si_version 'si-companion-v99' has no guardrails text. From v2 on the version
  SELECTS the SI wording, …
ROW 6 total: 2/2
  (control) v2 still renders its pin with v1's snapshot deleted: 1/1
```

| Row | Threshold | Measured | Verdict |
|---|---|---|---|
| 1 — current renders from LIVE | 3/3 unseeded · 1/1 moved seeded | 3/3 · moved 1/1 (and the two unseeded personas stayed pinned, 2/2) | **MET** |
| 2 — **THE row**: a historical version does not move when the live file is edited | 6/6 | 6/6 (all three live personas seeded, v1 and v2 × 3 personas all still equal to their `SI_DIGESTS` rows) | **MET** |
| 3 — reproducible from the snapshots ALONE | 6/6 + 1 raise | 6/6 with every live `personalities/*.yaml` deleted; the current version raised `FileNotFoundError` on the deleted live file | **MET** |
| 4 — current version already frozen for the next bump | 3/3 byte-identical | 3/3 | **MET** |
| 6 — refusals stay honest | 2/2 | 2/2 — missing snapshot names `si-companion-v1` **and** `tools/freeze_si_version.py`; `si-companion-v99` still refuses with "no guardrails text" and its message never mentions `_frozen` | **MET** |

Row 3's raise is the control that matters: with the live files gone the
current version cannot render at all, so row 2's pass is not an artefact of
live and frozen bytes agreeing.

### Row 5 — both `xfail(strict=True)` markers gone, both tests pass unmarked

```
$ grep -n "pytest.mark.xfail" tests/test_realtime_prompting.py tests/test_realtime_corpus_replay.py
(exit 1 — no matches; the two remaining "xfail" strings are prose INSIDE the
 restored tests' docstrings, recording why each was carried and what restored it)

$ .parcel/bin/python -m pytest \
    tests/test_realtime_prompting.py::test_the_v1_si_still_renders_to_its_v1_pins \
    tests/test_realtime_corpus_replay.py::test_the_corpus_capture_version_is_still_rendered_by_this_tree -q -rA
PASSED tests/test_realtime_prompting.py::test_the_v1_si_still_renders_to_its_v1_pins
PASSED tests/test_realtime_corpus_replay.py::test_the_corpus_capture_version_is_still_rendered_by_this_tree
2 passed, 1 warning in 0.54s

$ .parcel/bin/python -m pytest tests/test_realtime_prompting.py tests/test_realtime_corpus_replay.py -q
192 passed, 1 warning in 0.80s      # 0 failed · 0 xfailed · 0 xpassed
```

| Row | Threshold | Measured | Verdict |
|---|---|---|---|
| 5 — markers removed, both tests pass unmarked | 2 passed · 0 xfailed · 0 xpassed | 2 passed; whole files 192 passed, 0 xfailed, 0 xpassed | **MET** |

Neither test was re-pinned: v1's digests in `SI_DIGESTS` are the same numbers
they were before the owner's edit, and they pass because v1 now composes from
`prompts/personalities/_frozen/si-companion-v1/` (bytes verified above as
`e63be08`'s). Evidence: `~/.cache/parcel-fz1/evidence/20260823_row5_xfail.txt`.

### Row 6 — already closed by the fourth pass (05:37, evidence kept)

Row 6 was measured in the same script run as rows 1–4 and is in the table
above; the dispatch note that named row 6 as the resume point predates that
run. This pass did not re-measure it. Evidence:
`~/.cache/parcel-fz1/evidence/20260823_rows_1_2_3_4_6.txt`.

### Row 7 — `tools/freeze_si_version.py --check` on this tree

Re-measured by the fifth pass: the fourth pass's `20260823_row7_row8_tool.txt`
was written at 05:38, the minute it was OOM-killed, so it is not trusted.

```
$ unset TMPDIR; .parcel/bin/python tools/freeze_si_version.py --check
frozen SI snapshots OK: 9 pinned digest(s) across 3 version(s) re-rendered from their snapshots
exit=0

$ .parcel/bin/python -c "…SI_DIGESTS…"     # what "9/9" is made of
  si-companion-v1: 3 pins -> calm_guardian, gentle_companion, playful_companion
  si-companion-v2: 3 pins -> calm_guardian, gentle_companion, playful_companion
  si-companion-v3: 3 pins -> calm_guardian, gentle_companion, playful_companion
  TOTAL pinned digests = 9 across 3 versions
```

`check()` re-derives each version's digests through
`rendered_digests()` → `frozen_prompt_library(version)` →
`render_system_instruction` — i.e. from that version's SNAPSHOT alone, the
product renderer, never a local re-implementation.

| Row | Threshold | Measured | Verdict |
|---|---|---|---|
| 7 — `--check` on this tree | exit 0 · 9/9 digests (3 versions × 3 personalities) | exit 0 · 9/9 | **MET** |

Evidence: `~/.cache/parcel-fz1/evidence/20260823T062x_row7.txt`.

### Row 8 — the freezer actually freezes

Re-measured by the fifth pass on a fresh sandbox (`cp -a prompts/`), for the
same reason as row 7.

```
$ SB=~/.cache/parcel-fz1/row8_20260823T062x            # cp -a of prompts/, incl. _frozen/
$ .parcel/bin/python tools/freeze_si_version.py --version si-companion-v3 --prompts-root $SB/prompts
error: si-companion-v3 is already frozen at …/_frozen/si-companion-v3. A snapshot records the
text a version shipped with; rewriting it would silently re-attribute every session captured
under si-companion-v3. Pass --force only when the snapshot was written in error and nothing
has been captured under it yet.
exit=2                                                          # ← the 1 refusal

$ .parcel/bin/python tools/freeze_si_version.py --version si-companion-v3 --force --prompts-root $SB/prompts
froze prompts/personalities/_frozen/si-companion-v3/{calm_guardian,gentle_companion,playful_companion}.yaml
# paste into SI_DIGESTS … (si-companion-v3): 010afd82…, 7340c722…, 92d42939…
exit=0

  byte-identical (snapshot bytes == the sandbox's LIVE persona bytes): 3/3
  printed digests equal the registered SI_DIGESTS[si-companion-v3]:    3/3
```

**Control (not a row), because (a)+(b) alone would also pass if `freeze()` did
nothing:** a second sandbox with v3's snapshot dir DELETED and
`gentle_companion`'s *instruction* seeded (a line inserted into the instruction
block — the same shape of edit the owner made on 08-22), then the tool run with
no `--force`:

```
  snapshot bytes == the SEEDED live bytes: 3/3      (the copy carries the seed ⇒ a real copy)
  printed digests that MOVED off the registered pins: ['gentle_companion']
  untouched personalities still equal their pins: 2/2
  => the tool prints what it actually froze, not the registered numbers.
```

| Row | Threshold | Measured | Verdict |
|---|---|---|---|
| 8 — the freezer actually freezes | 3/3 files · 3/3 digests · 1 refusal | 3/3 byte-identical · 3/3 digests == `SI_DIGESTS[SI_VERSION]` · refusal exit 2 naming the version and the re-attribution risk | **MET** |

Incidental finding while building the control, recorded because it bounds what
the digest pins can catch: appending a YAML **comment** to a live persona file
moves the file's bytes but NOT its rendered digest (the digest is over rendered
text; `yaml` discards comments). So `SI_DIGESTS` alone would not notice a
comment-only persona edit — the thing that does is the byte comparison in
`freeze_si_version.check()` (`frozen <name> != the live persona file`) and row 4.
No code changed for this; it is a property of the pre-existing digest, stated so
the verifier does not have to rediscover it.

Evidence: `~/.cache/parcel-fz1/evidence/20260823T062x_row8.txt`.

### Row 11 — release parity

```
$ unset TMPDIR; .parcel/bin/python tools/sync_runtime_assets.py --check
release parity OK: 100 packaged file(s) match source
exit=0
```

The two counts the row can mean, reconciled so the verifier does not have to:

| Number | At `e15e466` | Now | Pre-registered |
|---|---|---|---|
| `tools/sync_runtime_assets.py` "packaged file(s)" (assets + `MANIFEST.json`) | 91 | **100** | 91 → 100 ✓ |
| `MANIFEST.json` `count` / `assets[]` entries | 90 | 99 | — |
| `tests/test_release_parity.py:EXPECTED_ASSET_COUNT` | 90 | 99 | — |
| on-disk files under `runtime_assets/`, excl. `MANIFEST.json` (`git ls-tree HEAD` vs `find`) | 90 | 99 | — |

The delta is +9 in every column and every one of the nine is a frozen persona
YAML — `prompts/personalities/_frozen/si-companion-v{1,2,3}/{calm_guardian,
gentle_companion,playful_companion}.yaml`, each with its `source` pointing at
the repo file it mirrors. `--check` re-hashes every packaged file against its
source, so exit 0 is byte-parity of all 100, not just a count.

`EXPECTED_ASSET_COUNT` was moved by hand from 90 to 99 with the reason in a
comment above it — that pin exists to make a *silent* change to the ship set
loud, and this change is deliberate: a wheel that does not carry the snapshots
cannot render any historical `si_version` at all (DESIGN.md §e).

`--write` was not re-run by this pass: the mirror was already written by a
predecessor and `--check` is exit 0, so a write would be a no-op; re-running a
generator over a tree four other cards are editing is the larger risk.

| Row | Threshold | Measured | Verdict |
|---|---|---|---|
| 11 — release parity | exit 0 · count 100 | exit 0 · 100 packaged files, +9 all under `personalities/_frozen/` | **MET** |

Evidence: `~/.cache/parcel-fz1/evidence/20260823T062x_row11_parity.txt`.

### Row 10 — ruff clean on OWNS, ratchet untouched

```
$ .parcel/bin/ruff --version
ruff 0.16.1                                   # the version GATE-0 pinned the 7-fingerprint verdict to

$ .parcel/bin/ruff check \
    src/parcel_robot/realtime/prompting.py tools/freeze_si_version.py \
    tests/test_fz1_frozen_si_snapshots.py tests/test_realtime_prompting.py \
    tests/test_realtime_corpus_replay.py tests/test_release_parity.py
All checks passed!
exit=0

$ git diff --stat HEAD -- scripts/ci_ruff_baseline.json
(empty — byte-identical to e15e466)
  sha256 d7b4c723ed2d2869c25396e8d1d6840a5dfd931d8efb91c863cf6022558991d9
  fingerprints in the baseline: 7
```

Tree-wide ruff is **18** findings across 7 files right now (`sim_bridge.py` 7,
`tests/test_ci_gate.py` 5, `camera_channel/backends/factory.py` 2, then one each
in `tests/test_xd1_repo_write_guard.py`, `detection_adapter/noise.py`,
`camera_channel/channel.py`, `camera_channel/__init__.py`). **Zero of them are
in FZ-1's OWNS** — they belong to other cards editing this tree concurrently and
are not mine to fix. The 06:1x census recorded 12; the growth is other cards'
in-flight debris, reported here as a handoff to the integrator, not touched.

| Row | Threshold | Measured | Verdict |
|---|---|---|---|
| 10 — ruff clean on OWNS, ratchet untouched | 0 new findings · baseline byte-identical | 0 findings on all 6 edited Python files · baseline unmodified · 7 fingerprints | **MET** |

**One cosmetic edit made during this row, declared.** `ruff format --check` is
NOT a gate in this repo (`scripts/ci_gate.py:evaluate_ruff` runs `ruff check`
against the fingerprint baseline and nothing else), and
`prompting.py` / `test_realtime_prompting.py` / `test_release_parity.py` are
already unformatted **at HEAD** — pre-existing style debt that is not mine to
churn. `tools/freeze_si_version.py` is a NEW file of mine, so its single finding
(one f-string concat in an error message that `ruff format` joins onto one line)
was fixed: no behaviour, message text unchanged. Rows 7 and 8 were then
**re-measured against the edited tool** so the evidence matches the tree the
verifier will see — both still MET, identical output; the re-runs are appended to
both evidence files under "RE-CONFIRMED". Tool sha256 now
`64126b53c41e1ec7bd6708238f9933cadaa35a5eb44c5759419a8495b2c9b17f`.

Evidence: `~/.cache/parcel-fz1/evidence/20260823T062x_row10_ruff.txt`.

### Row 9 — targeted suite green

Run through the mandatory guard wrapper (anti-crash rule 1). Pre-flight per
rule 4: 234 GB available, **0** real pytest roots (`ps -eo args | grep -E
'bin/python[0-9.]* -m pytest'` — note `pgrep -fc -- '-m pytest'` is unusable as
the rule-4 check on this host: the session's own memwatch monitor and the
checking shell both carry that literal in their command line, so it never reads
below 2; the `ps` form counts real interpreters).

```
$ env -u TMPDIR ~/.cache/parcel-guard/pytest_guard.sh --label fz1 \
    .parcel/bin/python -m pytest \
      tests/test_fz1_frozen_si_snapshots.py tests/test_realtime_prompting.py \
      tests/test_realtime_corpus_replay.py tests/test_realtime_driver.py \
      tests/test_release_parity.py tests/test_emotion_gesture_library.py \
      tests/test_yield_policy.py -m "slow or not slow" -q -rA

354 passed, 2 warnings in 8.59s
exit=0
```

Wall clock 06:25:57 → 06:26:06 (9 s), suite-scale so it took the guard's
flock (`guard.log`: `START label=fz1 mem=40G targeted=0` / `END … rc=0`). No
`-n` was passed, so this was a single-process run inside the 40 GB scope; no
137, no timeout. XD-1 was running targeted node-id runs in the same window and
correctly did not block on the lock.

| Row | Threshold | Measured | Verdict |
|---|---|---|---|
| 9 — targeted suite green | 0 failed · 0 error · 0 xfailed | 354 passed · 0 failed · 0 error · 0 xfailed · 0 xpassed · exit 0 | **MET** |

The suite is the pre-registered seven files verbatim, and it is the set that
covers both sides of the change: the FZ-1 guards, the two de-xfailed tests, the
corpus replay whose provenance this card restores, the driver that renders SI
on the product path, release parity for the shipped snapshots, and the two
unrelated prompt-plane consumers (`emotion_gesture_library`, `yield_policy`)
that would notice a `PromptLibrary` regression.

Evidence: `~/.cache/parcel-fz1/evidence/20260823T063x_row9_suite.txt`.

## Seeded-RED proofs (S1–S5)

All five seeds edit the **product** on a byte-identical scratch copy of the
tree at `~/.cache/parcel-fz1/seed_20260823T063x/` (`src/`, `prompts/`,
`tests/`, `tools/` copied with `cp -a`; `diff -r` against the working tree is
empty except `__pycache__`; `evals/`, `models/`, `configs/`, `fixtures/`,
`maps/` symlinked read-only). The working tree is never seeded — four other
cards are editing it right now. `PYTHONPATH=<scratch>/src` takes priority over
the editable `.pth`, verified in the evidence file by printing
`parcel_robot.__file__` and `resolve_prompts_root()`: both resolve **inside the
scratch**, so a seed genuinely changes the code under test.

Every pytest run below went through `~/.cache/parcel-guard/pytest_guard.sh
--label fz1` with node ids (targeted ⇒ no suite lock held), `env -u TMPDIR`.

Baseline, unseeded scratch, all seven named node ids: **8 passed** (two are
parametrised over v1/v2), exit 0.

### S1 — `personality_source()` returns the live library for every version

The seed replaces the whole resolution with the pre-FZ-1 behaviour:

```python
    # ---- FZ-1 SEED S1: pre-FZ-1 behaviour — every version reads the LIVE files
    return library if library is not None else default_prompt_library()
```

```
red:   4 failed, exit 1
  FAILED …test_a_historical_version_ignores_an_edit_to_the_live_persona_file[si-companion-v1]
  FAILED …test_a_historical_version_ignores_an_edit_to_the_live_persona_file[si-companion-v2]
  FAILED tests/test_realtime_prompting.py::test_the_v1_si_still_renders_to_its_v1_pins
  FAILED tests/test_realtime_corpus_replay.py::test_the_corpus_capture_version_is_still_rendered_by_this_tree
       AssertionError: gentle_companion
       assert '8d6a6f51f4b3…46d721d2eac01' == '418e6662efd6…257e8910e253d'
restore: sha256 f5bb7d1af2fd57ad6f22f2a1d94d9e812f31279042b1596e99cb37d6084c9278 — byte-identical
         __pycache__ purged
green: 4 passed, exit 0
```

All three pre-registered tests reddened, and the failure is the right shape: a
digest that MOVED, not an import error. This is the card's whole claim — with
the seed in, `si-companion-v1` renders `8d6a6f51…`; with it out, `418e6662…`,
the number `SI_DIGESTS` has held since v1.

### S2 — one byte appended to `_frozen/si-companion-v1/gentle_companion.yaml`

```
seed:  printf 'x' >> prompts/personalities/_frozen/si-companion-v1/gentle_companion.yaml
       sha256 4a428d83…833c32 → (size +1)
red:   FAILED …::test_every_registered_version_is_reproducible_from_its_snapshot_alone
       yaml.scanner.ScannerError: while scanning a simple key … "x" … could not find expected ':'
       exit 1
```

Measured as registered, and it is a red — but an honest one has to say *why*:
a bare `x` after a YAML mapping is a **parse error**, so this proves the guard
notices a corrupted snapshot, not that it notices a *changed* one. So the seed
was re-run in a stronger form on the same guard (S2b): a valid one-line change
to the instruction block, i.e. exactly the shape of the owner's 08-22 edit.

```
S2b:   sha256 5d109727…c1202a, valid YAML: yes
red:   FAILED …::test_every_registered_version_is_reproducible_from_its_snapshot_alone
       AssertionError: si-companion-v1/gentle_companion is not reproducible from its snapshot alone
       exit 1
restore: sha256 4a428d838573c1581f2e0a87019164c0732672e23ceefd2e1c6ae838ab833c32 — byte-identical
         __pycache__ purged
green: 1 passed, exit 0
```

S2b is the proof that matters: the failure is the **digest** assertion with the
version and personality named, so the pin catches a snapshot whose *text* moved,
not merely one that stopped parsing.

### S3 — one byte appended to `_frozen/si-companion-v3/calm_guardian.yaml`

```
seed:  printf 'x' >> …/_frozen/si-companion-v3/calm_guardian.yaml
       sha256 c607edbc…16c23b → b069ec5e…7b6adc   size 489 → 490
red:   FAILED …::test_the_current_version_is_already_frozen_for_the_next_bump
       AssertionError: calm_guardian.yaml
       assert b'id: calm_gu...d_paw_taps\nx' == b'id: calm_gu...ed_paw_taps\n'
       exit 1
restore: sha256 c607edbc5f25974c3f50a104bdc6c17e42e3994b325a4076db5d35f78816c23b — byte-identical
         __pycache__ purged
green: 1 passed, exit 0
```

Here the registered one-byte seed is exactly right, because this guard compares
**bytes**, not digests — which is also why it, and not `SI_DIGESTS`, is what
would catch the comment-only persona edit noted under row 8.

### S4 — the missing-snapshot `raise` replaced by a silent fall-back to the live library

The seed is the exact defect the card exists to prevent — `frozen_prompt_library`
quietly rendering today's personas under a historical label:

```python
    # ---- FZ-1 SEED S4: silent fall-back instead of the refusal
    if not snapshot.is_dir():
        return PromptLibrary(root)
```

```
seed:  src/parcel_robot/realtime/prompting.py  f5bb7d1a…84c9278 → eb7f89a8…f41c56
red:   FAILED …::test_a_historical_version_without_a_snapshot_refuses_by_name
       Failed: DID NOT RAISE <class 'parcel_robot.realtime.prompting.PromptPlaneError'>
       exit 1
restore: sha256 f5bb7d1af2fd57ad6f22f2a1d94d9e812f31279042b1596e99cb37d6084c9278 — byte-identical
         __pycache__ purged
green: 1 passed, exit 0
```

Note what the seed does NOT break: it still renders. That is the point — a
silent fall-back produces plausible text under the wrong version label, which is
why the guard has to assert on the refusal rather than on the output.

### S5 — `render_system_instruction` resolves the CURRENT version from its snapshot too

```python
    # ---- FZ-1 SEED S5: the CURRENT version reads its snapshot too
    root = library.root if library is not None else resolve_prompts_root()
    return frozen_prompt_library(version, prompts_root=root)
```

```
seed:  src/parcel_robot/realtime/prompting.py  f5bb7d1a…84c9278 → 84d731eb…f0f537
red:   FAILED …::test_the_current_version_still_renders_from_the_live_persona_files
       AssertionError: an edit to a live persona file did not move the CURRENT version's
       render; the current version is being served from something other than the live files
       assert '7340c722…9591644' != '7340c722…9591644'
       exit 1
restore: sha256 f5bb7d1af2fd57ad6f22f2a1d94d9e812f31279042b1596e99cb37d6084c9278 — byte-identical
         __pycache__ purged
green: 1 passed, exit 0
```

S5 is the over-correction guard, and it is the one that keeps this card from
breaking the pin test it was built to save: if history and *today* both came
from snapshots, `SI_DIGESTS[SI_VERSION]` would stop moving when a persona is
edited and the whole pin would go quiet. The seed is only reachable by deleting
the `version == SI_VERSION` branch, and the guard notices immediately.

### Seed hygiene

| | |
|---|---|
| Seeds applied to the working tree | **none** — every seed was on `~/.cache/parcel-fz1/seed_20260823T063x/` |
| `src/`, `prompts/`, `tools/` in the scratch after all five seeds | `diff -r` vs the working tree **empty** (except `__pycache__`) |
| FZ-1's four test files, scratch vs working tree | 4/4 sha256-identical |
| Working-tree sha256 of the three seeded paths | unchanged: `f5bb7d1a…`, `4a428d83…`, `c607edbc…` |
| `__pycache__` | purged before every red run and before every green re-run |
| pytest invocations | all through `pytest_guard.sh --label fz1` with `::` node ids (targeted ⇒ no suite lock), `env -u TMPDIR` |

Three files in the scratch `tests/` DID drift from the working tree during the
seeds — `_sim_guard.py`, `test_hy1_sim_guard.py` (HY-1), `test_roam2_coverage.py`
(ROAM-2), plus a new `test_truth1_texts.py` (TRUTH-1). Those are other cards
editing the shared tree while this card ran; none is FZ-1's and none was
touched. Recorded so the verifier does not read them as seed residue.

## Headline

A historical SI version now renders from its own immutable persona snapshot, so
an owner editing `prompts/personalities/*.yaml` can no longer change what
`render_system_instruction(version="si-companion-v1")` produces. The two
`xfail(strict=True)` markers the 2026-08-22 02:10 edit forced are gone and both
tests pass unmarked, **without re-pinning a single digest** — v1's numbers in
`SI_DIGESTS` are the ones it has held since v1, and the 25-thread / 52-query
voice corpus is evidence again rather than remembered numbers. The current
version still reads the LIVE files, which is what keeps the pin test able to
notice the next persona edit.

## What changed

```
$ git diff --stat HEAD -- <OWNS>
 src/parcel_robot/realtime/prompting.py        | 114 +++++++++++++++++++++++++-
 src/parcel_robot/runtime_assets/MANIFEST.json |  76 ++++++++++++++++-
 tests/test_realtime_corpus_replay.py          |   8 +-
 tests/test_realtime_prompting.py              |   9 +-
 tests/test_release_parity.py                  |   7 +-
 5 files changed, 207 insertions(+), 7 deletions(-)
```

Plus, added by the 07:1x correction pass and **outside the pre-registration's
OWNS** (declared deviation 8): `tests/test_ci_gate.py` — **two lines** at
`:648-649`, the companion literal to row 11. That file is XD-1's OWNS; the
integrator assigned this hunk to FZ-1 because the nine snapshots are what moved
the number, and XD-1's executor had finished. Nothing else in the file was
touched.

New files (untracked):

| Path | Size | What |
|---|---|---|
| `prompts/personalities/_frozen/si-companion-v{1,2,3}/*.yaml` | 9 files | the snapshots; v1/v2 byte-identical to `e63be08`, v3 to the live files |
| `src/parcel_robot/runtime_assets/prompts/personalities/_frozen/**` | 9 files | the release-parity mirror (generated) |
| `tools/freeze_si_version.py` | 265 lines | `--version` snapshots at bump time and prints the pins; `--check` re-derives every pin from its snapshot |
| `tests/test_fz1_frozen_si_snapshots.py` | 430 lines | 15 tests, the FZ-1 guards |
| `scrum/20260822/task_13/{DESIGN,PREREGISTRATION,FZ1_STATUS}.md` | — | card docs |

The product change is one decision point —
`prompting.personality_source(version, *, library)` — plus
`_FrozenPromptLibrary`, `frozen_personas_dir`, `frozen_prompt_library`, and one
reordering in `render_system_instruction` so `si_guardrails(version)` is
evaluated **before** the persona lookup (an unregistered version keeps refusing
by name instead of failing later on a snapshot it was never going to have).
No new config key, env var, or behaviour flag; nothing under `core/hard_stop`,
`reactive_safety` or `SafetySupervisor` is reachable from any of it.

**Nothing outside OWNS was touched.** Every dirty path attributable to this card
is in the pre-registration's OWNS list; the live persona files, `evals/**` and
the broker are untouched.

## Rows at a glance

| Row | Verdict | Row | Verdict |
|---|---|---|---|
| 1 current renders from LIVE | MET | 7 `--check` on this tree | MET |
| 2 **THE row** — history does not move | MET | 8 the freezer actually freezes | MET |
| 3 reproducible from snapshots alone | MET | 9 targeted suite green | MET |
| 4 current already frozen | MET | 10 ruff clean, ratchet untouched | MET |
| 5 both xfails gone, tests pass | MET | 11 release parity | MET |
| 6 refusals stay honest | MET | | |

Seeds: S1 MET · S2 MET (+ S2b) · S3 MET · S4 MET · S5 MET.

## What this does NOT prove

- **No hosted-model behaviour, no spend.** Every row is about which *bytes* the
  prompt plane renders. No session was opened; $0 spent. Whether a model
  responds better to v3 than v1 is not in evidence here.
- **Not that the corpus is correct** — only that its stored `si_digest` values
  are re-derivable from this tree, which is what makes them evidence.
- **Not the v3 digests themselves.** They were registered by the owner's
  verifier and are taken as given (pre-registration §What this does not claim).
- **Seeds prove guards, not integration.** S1–S5 show the *tests* notice each
  defect. They do not show the runtime exercises the frozen branch — and it
  never does: `runtime.py:2545` always passes `SI_VERSION`, so the live robot
  takes the live-files path exactly as before. That is the design (DESIGN.md §b),
  not an untested gap, but a verifier should not read S1 as product-path proof.
  The product-path claim is rows 1–4/6, which go through
  `render_system_instruction` itself.
- **§e hardware compatibility is an argument plus a same-arch test, not an
  aarch64 measurement.** `test_a_wheel_can_still_render_every_historical_version`
  points `PARCEL_ROOT` at `packaged_assets_root()` **on this x86-64 box** and
  re-renders all six historical digests from there; combined with
  `sync_runtime_assets.py --check` (100/100 byte-parity) that pins *the packaged
  tree carries the snapshots and renders history from them*. No Orin, no aarch64
  wheel, no JetPack CPython 3.10 was involved — there is no hardware on hand.
  The residual assumption is only that SHA-256 over UTF-8 and `pathlib`/`yaml`
  are arch-independent.
- **Row 9 is seven files, not the suite.** The commit tier is the integrator's.
- **`frozen_prompt_library` is public and interpolates `version` into a path.**
  Unreachable with attacker-shaped text through `render_system_instruction`
  (guardrails refuse first — row 6), but a direct caller could aim the snapshot
  dir elsewhere under the prompts root. No refusal added: the wave's rule 1
  forbids new fail-closed defaults. Recorded in DESIGN.md §g.
- **Nothing forces a human to run the freezer at bump time.** `--check` and
  `test_the_current_version_is_already_frozen_for_the_next_bump` catch a bump
  that skipped it — but only if someone runs them (see handoffs).
- **`SI_DIGESTS` cannot see a comment-only persona edit** (row 8 note): the
  digest is over rendered text, and `yaml` discards comments. The byte
  comparison in `check()` and row 4 is what covers that.

## Deviations from the pre-registration (declared)

1. **Row 6 was not re-measured by this pass.** It closed at 05:37 in the fourth
   pass's rows-1–4–6 script run, minutes before that session was OOM-killed;
   its evidence file is complete and is kept. The dispatch brief named row 6 as
   the resume point because the record file lagged that run. Rows 7 and 8, whose
   evidence file was written at 05:38 — the minute of the kill — WERE
   re-measured from scratch, as instructed.
2. **S2's registered seed ("one byte appended") reddens as a YAML parse error**,
   not as a digest mismatch. Measured as written and recorded as MET, then
   repeated as **S2b** with a valid one-line instruction change so the *digest*
   assertion is the thing that fires. The stronger proof is S2b; the registered
   one is reported honestly for what it is.
3. **One cosmetic edit outside any row:** `tools/freeze_si_version.py` — a new
   file of mine — was the only OWNS file failing `ruff format --check`, so its
   single f-string-concat finding was joined. `ruff format` is NOT a gate here
   (`evaluate_ruff` runs `ruff check` against the fingerprint baseline), and the
   three tracked files that also fail it already failed at HEAD, so those were
   left alone rather than churned. Rows 7 and 8 were re-measured against the
   edited tool.
4. **Anti-crash rule 4's pre-flight used a `ps` form,** not
   `pgrep -fc -- '-m pytest'`: on this host that literal appears in the
   session's own memwatch monitor command line and in the checking shell, so it
   never reads ≤ 1. `ps -eo args | grep -E 'bin/python[0-9.]* -m pytest'` counts
   real interpreters and read **0** before the one suite-scale run.
5. **`sync_runtime_assets.py --write` was not re-run** (row 11): a predecessor
   had already written the mirror and `--check` is exit 0, so a write is a no-op
   — and re-running a generator across a tree four other cards are editing is
   the larger risk.
6. **One control added that is not a registered row** (row 8 §d), because
   (a)+(b) as written would also pass if `freeze()` did nothing.

## Owner-gated rows

**None.** FZ-1 needs no hardware, no camera, no enrollment, no hosted session
and no owner decision. Every one of the 11 rows and 5 seeds ran to completion on
this box. The owner's `parcel_memory.sqlite3` was never opened; `:8765` and
`/tmp/parcel_sim.sock` were never touched; no process was signalled.

## Anti-crash compliance (auditable against `~/.cache/parcel-guard/guard.log`)

Every pytest invocation of this pass went through
`~/.cache/parcel-guard/pytest_guard.sh --label fz1`, prefixed `env -u TMPDIR`.
`guard.log` holds **14 `label=fz1` STARTs and 14 ENDs** — none left open, every
one `rc=0` or the intended red. **Two** were suite-scale (`targeted=0`) and both
took the flock: row 9 (06:25:57 → 06:26:06) and the final-state re-run
(06:36:59 → 06:37:01); the other twelve named `::` node ids and correctly did
not queue behind other executors.
No `-n` was ever passed, so no xdist worker was spawned by this card at all.
No exit 137, no timeout, no background pytest, no `ci_gate.py --tier`. Peak
availability never dropped below ~230 GB during this card's runs.

Suite-scale commands run by this pass (the complete list):

| When | Command | Result |
|---|---|---|
| 06:25:57 → 06:26:06 | `pytest_guard.sh --label fz1 .parcel/bin/python -m pytest <the 7 row-9 files> -m "slow or not slow" -q -rA` | 354 passed, exit 0 |
| 06:36:59 → 06:37:01 | `pytest_guard.sh --label fz1 .parcel/bin/python -m pytest tests/test_fz1_frozen_si_snapshots.py -q` | 16 passed, exit 0 |

The second row is the final-state re-run described under §"Final state of the
working tree" and deviation 7; it queued ~4½ min on the guard's flock behind
XD-1's suite before starting at 06:36:59. It was missing from this table in the
first draft (verifier F4) — an under-count in my own audit trail, corrected
here; `guard.log` was always the ground truth and shows both.

## Handoffs

1. **To the integrator (parcel-6c).** Commit path list for FZ-1:
   `src/parcel_robot/realtime/prompting.py`,
   `src/parcel_robot/runtime_assets/MANIFEST.json`,
   `src/parcel_robot/runtime_assets/prompts/personalities/_frozen/**` (9),
   `prompts/personalities/_frozen/**` (9),
   `tools/freeze_si_version.py`, `tests/test_fz1_frozen_si_snapshots.py`,
   `tests/test_realtime_prompting.py`, `tests/test_realtime_corpus_replay.py`,
   `tests/test_release_parity.py`, `scrum/20260822/task_13/**`.
   **Plus two lines inside XD-1's `tests/test_ci_gate.py`** (`:648-649`, the
   `extra["checked"]` literal 91 → 100) — that file carries XD-1's work too, so
   commit it with theirs; the FZ-1 hunk is only those two lines and is described
   under "Second correction item" above.
   `CODEBASE_INDEX.md` will be stale afterwards (new module + new test group +
   a new asset dir): `.parcel/bin/python tools/codebase_index.py`.
2. **Tree-wide ruff, re-measured 07:1x: 12 errors** — `sim_bridge.py` (7),
   `camera_channel/backends/factory.py` (2), `detection_adapter/noise.py`,
   `camera_channel/channel.py`, `camera_channel/__init__.py`. **Zero in FZ-1's
   OWNS.** (At 06:2x this read 18, including 5 in `tests/test_ci_gate.py` and 1
   in `tests/test_xd1_repo_write_guard.py`; XD-1's executor cleaned those in
   between — not my change, and `test_ci_gate.py` is clean as of my edit to it.)
   12 is the number the 06:1x census called "exactly the 7 baseline
   fingerprints"; the ratchet is fingerprint-based, so the integrator's ruff row
   should be green. Flagged so the commit tier's ruff row is not a surprise.
3. **Nobody is forced to freeze at bump time.** `tools/freeze_si_version.py
   --check` is not wired into any gate tier. Adding it as a row would make an
   unfrozen bump loud instead of silent — a natural GATE-0b / gate-tier item,
   deliberately NOT done here (`scripts/ci_gate.py` is XD-1's and then
   GATE-0b's, one writer at a time).
4. **`evals/companion/realtime_convo_v1/schema.py:473`** re-renders a thread's
   SI only when `si_version == SI_VERSION`. That narrowing existed *because*
   history was not reproducible; it now is, so the guard could widen to every
   version. `evals/**` is MUST-NOT-TOUCH for this card — a handoff, not a change.
5. **The bump procedure is documented in the tool's module docstring**
   (edit → register `SI_Vn`/`SI_VERSION` → `--version si-companion-vN` →
   paste the printed block into `SI_DIGESTS`). Freezing the version being
   *introduced* is what makes its later retirement free.

## Resumed from

This card has had five executors; nothing was ever reverted, and each pass
inherited the tree as-is.

- **Pass 1 (08-22 ~15:2x, died in a Cursor/OOM kill ~15:36)** wrote
  `PREREGISTRATION.md` (sha256 `8f0e19ee…`, still byte-identical today and
  unmodified by any later pass) and ran the feasibility probe that established
  the snapshot bytes must be `e63be08` for v1/v2 and live for v3.
- **Pass 2 (~16:17, died ~16:23)** wrote `DESIGN.md` (16:22).
- **Pass 3 (17:55, died in the 18:02 reboot/OOM)** landed essentially all the
  code: `prompting.py` +114, the nine snapshots, the `runtime_assets` mirror and
  `MANIFEST.json` +76, `tools/freeze_si_version.py`, the 402-line test file, the
  two xfail removals, `test_release_parity.py` +7. It left evidence files from a
  first measuring attempt (`row5_xfail_removal.txt`, `row9_targeted_suite.txt`,
  `row10_ruff.txt`, …) and a scratch seed tree at `~/.cache/parcel-fz1/seedtree`.
- **Pass 4 (08-23 05:35, OOM-killed at 05:38:42 by another executor's
  `pytest -n auto`)** re-verified the premise byte-for-byte, wrote the status
  doc's header and Rows section, and closed **rows 1, 2, 3, 4, 6** (05:37) and
  **row 5** (05:38:05). Its row 7/8 evidence file was written at 05:38 — the
  minute of the kill.
- **Pass 5 (this one, 06:2x).** Kept everything above; discarded nothing.
  Re-verified the pre-registration sha256, re-read rows 1–5 to match their
  evidence conventions, then **re-measured rows 7 and 8 from scratch** (per the
  dispatch, the 05:38 file is not trusted — both reproduce), and measured
  **rows 9, 10, 11** and **seeds S1–S5** for the first time. Changed exactly one
  line of inherited code: the `ruff format` nit in `tools/freeze_si_version.py`
  (deviation 3). The 17:5x evidence files from pass 3 are left in place for the
  verifier but **nothing in this document is claimed from them** — every number
  above carries a `20260823` evidence file.

Evidence files produced by this pass, all under
`~/.cache/parcel-fz1/evidence/`: `20260823T062x_row7.txt`,
`20260823T062x_row8.txt`, `20260823T062x_row10_ruff.txt`,
`20260823T062x_row11_parity.txt`, `20260823T063x_row9_suite.txt`,
`20260823T063x_seeds.txt`.

## Final state of the working tree, as the verifier will find it

Run last, after every seed was restored, so this is the tree being handed over:

```
$ env -u TMPDIR ~/.cache/parcel-guard/pytest_guard.sh --label fz1 \
    .parcel/bin/python -m pytest tests/test_fz1_frozen_si_snapshots.py -q
16 passed, 1 warning in 1.81s

$ .parcel/bin/ruff check <the 6 edited Python files>
All checks passed!

$ .parcel/bin/python tools/freeze_si_version.py --check
frozen SI snapshots OK: 9 pinned digest(s) across 3 version(s) re-rendered from their snapshots
exit=0

$ .parcel/bin/python tools/sync_runtime_assets.py --check
release parity OK: 100 packaged file(s) match source
exit=0
```

**Deviation 7 (declared).** This last run's rule-4 pre-flight printed
`avail=231G  real_pytest_roots=8` — XD-1's `-n`-parallel baseline suite was
running — and rule 4 says to `sleep 60` and re-check rather than proceed. The
check and the command were issued as one pipeline, so it did not gate. No harm
resulted and the reason is structural: the run was suite-scale, so
`pytest_guard.sh` put it on the flock and it **waited 4½ minutes for XD-1's
suite to finish** before starting — the serialization rule 4 approximates was
enforced by the guard itself, not bypassed. Availability never fell below
231 GB. Recorded rather than quietly omitted; the correct form is to gate on the
check, and rows 9's pre-flight (0 roots) did.

## Processes left behind: none

`guard.log` shows **14 `label=fz1` STARTs and 14 ENDs** — every run this card
started has exited. `pgrep -af parcel-fz1` is empty: nothing references this
card's scratch directory. FZ-1 started no simulator, opened no socket, and
signalled no process.

At the moment of writing, `tools/list_parcel_procs.py` reports one
`parcel_robot.sim` — pid 239716 on `~/.cache/parcel-roam2/r2-239652.sock`,
started 06:37:11. That is **ROAM-2's**, on ROAM-2's own scratch socket, and it
was left alone (standing rule: never kill a process you did not start). The
owner's `/tmp/parcel_sim.sock` and :8765 were never touched by this card.

## Correction pass (2026-08-23, 06:5x EDT)

Verifier verdict **ACCEPT-WITH-NOTES** (Fable; full record
`~/.cache/parcel-verify/fz1/VERDICT.md`): one FIX, documentation-only, and seven
NOTEs. The verifier re-measured every pre-registered row independently, re-ran
all five registered seeds plus S2b, and added three seeds of its own (V-a the
guardrails-before-persona ordering, V-b `library=` not resurrecting live files
for history, V-c the `runtime_assets` mirror stripped of `_frozen`) — all red on
the named test and green after restore. Nothing it found moved a row's verdict:
11/11 still MET, and no digest was re-pinned.

Applied by this pass, docs only — **no product code, no test, no measurement
re-run**:

- **F1 (FIX)** `DESIGN.md` §b. The old "Product path in" bullet ended by calling
  `evals/companion/realtime_convo_v1/{schema.py:466, build_manifest.py:109}` the
  historical branch's product path. That was wrong and I confirmed it before
  editing: `schema.py:473` re-renders only inside
  `if fixture.si_version == SI_VERSION:` (`:472`), `build_manifest.py:109`
  passes no `version=` so it defaults to `SI_VERSION`, and `schema.py:466` is
  `si_pin` — a registry lookup that renders nothing. `grep -rn` over `src tools
  evals` confirms the historical branch's only non-test caller is
  `tools/freeze_si_version.py --check` → `rendered_digests:114` →
  `frozen_prompt_library`. §b now says that, records that `schema.py:473` stays
  current-only deliberately (handoff 4, `evals/**` MUST-NOT-TOUCH), and is
  consistent with the "does not prove" bullet that already said the runtime
  never takes the frozen branch. `runtime.py:2545` → `2546` in the same bullet
  (the verifier's line number; re-checked — `InstructionSource(` is at 2546).
- **F4 (NOTE)** this document, §"Anti-crash compliance". "Exactly **one**"
  suite-scale run → **two**, and the "complete list" table gained the
  06:36:59 → 06:37:01 final-state re-run. `guard.log` has two
  `label=fz1 targeted=0` entries; the run was already described under deviation 7
  and §"Final state", but the audit table under-counted it. Also corrected
  "13 STARTs and 13 ENDs" → **14/14**, which is what `guard.log` shows and what
  §"Processes left behind" already said.

### Second correction item (07:1x) — row 11's companion pin in `test_ci_gate.py`

`tests/test_ci_gate.py::test_release_parity_is_green_on_the_committed_tree` was
**RED in the live tree** and my row 11 never noticed it: the row measured
`sync_runtime_assets.py --check` (100 packaged files) and
`test_release_parity.py`'s `EXPECTED_ASSET_COUNT` (90 → 99), but a *third*
literal pins the same fact from the gate's side — `evaluate_release_parity()`'s
`extra["checked"]`, which counts 99 assets + 1 side mirror. My nine snapshots
moved it 91 → 100. XD-1's executor found it and left it to the owner of the nine
files; the integrator assigned it to me.

Premise confirmed before editing anything in XD-1's file:

```
$ … pytest_guard.sh --label fz1 … tests/test_ci_gate.py::test_release_parity_is_green_on_the_committed_tree
>       assert result.extra["checked"] == 91
E       assert 100 == 91
tests/test_ci_gate.py:649: AssertionError          1 failed
```

The `result.status == "pass"` assertion above it was already green — parity
itself was fine; only the literal was stale. The edit, two lines and nothing
else (the comment wraps to two lines to stay inside the line-length limit):

```diff
-    # LITERAL, per the sentinel convention: 90 packaged assets + 1 side mirror.
-    assert result.extra["checked"] == 91
+    # LITERAL, per the sentinel convention: 99 packaged assets + 1 side mirror
+    # (FZ-1 added the nine frozen persona snapshots; see task_13).
+    assert result.extra["checked"] == 100
```

```
$ env -u TMPDIR ~/.cache/parcel-guard/pytest_guard.sh --label fz1     .parcel/bin/python -m pytest -q -p no:cacheprovider     "tests/test_ci_gate.py::test_release_parity_is_green_on_the_committed_tree"     tests/test_release_parity.py
11 passed in 0.99s
exit=0
```

Rule-4 pre-flight was **gated on this time** (the deviation-7 lesson): a loop
that re-checks and sleeps 60 s until `avail ≥ 120` and real pytest roots ≤ 1 —
passed first attempt, 233 GB / 0 roots. The guard classified the run
`targeted=1` (one argument carries a `::` node id) so it did not take the suite
flock; that is the wrapper's documented rule, and with 0 roots running there was
nothing to serialize against. `guard.log` 07:10:19 → 07:10:21, rc=0.

`ruff check tests/test_ci_gate.py` → **All checks passed**, and no finding on
lines 645-652, so the three lines added no debris. (That file carried 5 findings
in my 06:2x tree-wide census and now carries 0 — XD-1's executor cleaned their
own debris in between; not my change.) `scripts/ci_ruff_baseline.json` still
unmodified.

**Deviation 8 (declared).** `tests/test_ci_gate.py` is not in the
pre-registration's OWNS list and is XD-1's file. I edited it on the integrator's
explicit instruction, limited to the two lines named, after XD-1's executor had
finished — no lock was taken because there is no concurrent writer. The
pre-registration is unchanged; this is an OWNS deviation, not a threshold
change, and row 11's verdict is unaffected (its own three numbers were already
reconciled and still hold).

Evidence: `~/.cache/parcel-fz1/evidence/20260823T071x_ci_gate_parity_pin.txt`.

**Declined, with the integrator's agreement:** F2 (wrapping the `prompting.py`
hunks in `# ---- CARD FZ-1 …` delimiters). The repo reserves card markers for
*shared* product files; `prompting.py` has no concurrent writer, every hunk is
attributed in prose, and batch A landed solely-owned files unmarked. The
integrator declined it explicitly.

**Noted, no action** (all were already declared in this document before the
verifier saw it): F3 — S2-as-registered reddens the YAML loader, not the digest
guard, which is why S2b exists (deviation 2). F6 — deviation 7's rule-4 form
breach, serialized by the flock, no overlap. F7 — `frozen_personas_dir`
interpolates `version` into a path; unreachable through
`render_system_instruction` because guardrails refuse first, and the verifier's
V-a proves that ordering is load-bearing; no refusal added per wave rule 1
(DESIGN.md §g).

**Two NOTEs worth the integrator's eye, because they correct *this* document:**

- **F5** — row 10's evidence file `20260823T062x_row10_ruff.txt` (06:24:29)
  predates the 06:25:13 `ruff format` edit to `tools/freeze_si_version.py` by
  44 s, so it carries no post-edit `ruff check` for that one file. Everything
  downstream *is* post-edit (rows 7/8 re-confirmed 06:25:23, row 9 06:25:57,
  seeds 06:27+, final run 06:36), and both the verifier and my own final-state
  block re-ran `ruff check` on the current bytes → `All checks passed!`. The row
  is MET; the evidence file is stale by one file and is left as-is rather than
  back-dated.
- **F8** — §"Resumed from" credits pass 3 (17:55) with landing "essentially all
  the code". File mtimes say otherwise: `prompting.py` 15:27, the three test
  edits 15:30–15:34, `MANIFEST.json` and the mirror 15:30 — i.e. **pass 1**,
  two minutes after it wrote `PREREGISTRATION.md` at 15:25 — with only
  `tests/test_fz1_frozen_si_snapshots.py` at 17:52 (pass 3) and
  `tools/freeze_si_version.py` at 06:25 (this pass's cosmetic edit). Immaterial
  to correctness — the pre-registration still precedes every product edit, which
  is the property that matters — but the narrative is wrong and I am leaving
  this correction rather than rewriting the paragraph, so the record shows both
  what I believed and what the mtimes say.
