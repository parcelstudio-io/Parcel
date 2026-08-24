# DEC-0 status — oracle & API classification + debt ratchet

Executor: Opus (DEC-0). HEAD at authorship `92245a1`, 2026-08-23.
Card: `scrum/20260823/task_14/README.md`. Program §3.

## Deliverables

| artifact | state |
|---|---|
| `scrum/20260823/task_14/DEC0_REGISTRY.md` | 624 lines — pin classification for all 8 target files + public surface |
| `tests/test_dec0_debt_ratchet.py` | 8 tests, green, 4.87 s through the guard wrapper |
| this file | — |

**No product file was edited.** `git status` shows exactly two untracked
additions from this card (registry + test) plus this status doc. Git was
read-only throughout; the owner's stack, socket and memory store untouched.

## 1. Registry coverage

Method: an AST scanner over all 402 test modules found 189 matching the
verdict's source-shape patterns (the verdict measured 186; wave A added
three). Function-scoped co-occurrence narrowed this to 152 candidate
(test, target) pairs, which five parallel classifiers read and adjudicated.
**False-positive filtering was a large share of the work** — the scanner
over-matched heavily on tests that read `ui/index.html`, `configs/*.yaml`,
`models.lock.json` or another package's source.

Counts below are read back out of the registry mechanically, not tallied
by hand:

| target file | candidate modules | **classified pins** | S-C | TRANS | INCID | notes |
|---|---|---|---|---|---|---|
| `runtime.py` | 50 | **58** | 32 | 19 | 7 | 20 of them in `test_r24_lock_discipline.py` alone |
| `navigation/pipeline.py` | 15 | **14** | 8 | 5 | 1 | the whole barn digest family cleared as non-pins |
| `realtime/lane.py` | 13 | **2** | 2 | 0 | 0 | far less encumbered than its size suggests |
| `realtime/audio_gateway.py` | 12 | **1** | 1 | 0 | 0 | six "gateway source" blocks actually read `ui/index.html` |
| `web_panel.py` | 11 | **12** | 8 | 3 | 1 | only 1 reads `web_panel.py` text; 8 pin `ui/*.html` copy |
| `agent.py` | 2 | **1** | 1 | 0 | 0 | least oracle-encumbered target |
| `realtime/tool_broker.py` | 5 | **3** | 2 | 1 | 0 | + the product-side `admission._BROKER_SOURCE` scan |
| `scripts/ci_gate.py` | 20 | **23** | 13 | 5 | 5 | tier/stage roster is the decomposition blocker |
| **total** | 128 | **114** | **67** | **33** | **14** | one row carries a dual classification |

The three biggest surprises against the candidate set: `runtime.py` is
worse than the module count suggested (58 distinct pins, not 50 modules'
worth), while `lane.py` (2) and `audio_gateway.py` (1) are dramatically
*less* pinned than their size implies — the D06/D09 splits are constrained
by behavior tests, not structural oracles.

Every pin names its test file:line. **All 102 explicit `path.py:NNN`
citations in the registry were mechanically verified to resolve** to a
real file and an in-range line; a sample of the 168 section-scoped bare
`:NNN` citations was spot-checked by hand against the source.

Public surface enumerated per file: external/internal importer counts by
AST sweep, symbols with per-symbol counts, config keys and env vars owned,
HTTP routes and CLI flags, and the most-called public methods.

### Findings that change the program's shape

- **F1 — the dangerous pins go vacuously GREEN, not red.** ~9 oracles
  scan a hard-coded path list or walk only `class RobotRuntime`; when code
  moves out they stop seeing it and pass. Marked **VACUITY RISK** in the
  registry. The existing anti-vacuity floors (`test_r24…:701`, `:762`,
  `:1020`, `:1595-1603`; `test_nm1…:396`) are the program's real safety net
  and must be raised, never lowered.
- **F2 — nearly every extraction card must edit one product file.**
  `admission._PRODUCT_CONFIG_SOURCES` / `_RUNTIME_REGION_SOURCES`
  (`admission.py:389,400-410`) are hand-written filename rosters checked
  for completeness by `test_cap1_admission.py:267-276`. "No product edits"
  is achievable for DEC-0 only.
- **F3 — two stale labels found and recorded.** `RUNTIME_LOCKS` has **8**
  entries while its header prose says "seven" and the ARCH-1 packet and
  verdict both say 6 (authoritative: **8**, asserted at `:550`);
  `test_hw4_array_gateway.py:892` is named `..._four_methods_...` but
  asserts five.
- **M7 conflicts with two live ci_gate oracles.**
  `test_hw7_gate_aarch64.py:692-700` and
  `test_hw6_stopping_envelope.py:753-758` assert `opens == closes > 0` for
  `# ---- CARD` fences *inside* `ci_gate.py` — they forbid the marker
  dissolution M7 requires. D16 must retire both first.
- **The eight-target public-surface census finds one barrel with repository
  symbol consumers.** `parcel_robot.navigation` is used by **12 modules**
  (verified by AST; a line-grep undercounts parenthesized multi-line imports).
  The `realtime` barrel's 8 lane symbols have zero repository callers, but
  remain public compatibility surface unless a later card explicitly approves
  their removal. This census does not replace DEC-IG-1's broader package
  worklist.

## 2. Ratchet baseline (frozen, measured)

Scope `src/parcel_robot` + `scripts` + `tools`, `.py` only, 364 files.
Pure AST/text; imports no product code; scan wall-time **1.87 s**.

| quantity | baseline |
|---|---|
| modules > 1,000 lines | **45** (src 30 / scripts 12 / tools 3) |
| functions > 100 lines | **153** (140 distinct leaf names) |
| import cycles, package-edge model | **25**, largest **81** |
| import cycles, leaf-only model | **8**, largest **4** |
| `# ---- CARD` markers | **178** |

Keying choices, so the ratchet punishes new debt and not honest movement:
modules by repo-relative **path**; long functions by **leaf name** (M5
demotes `RobotRuntime.foo` to a module-level `foo` — that must not redden)
plus per-name and total occurrence counts to catch name reuse; cycles by both models, with SCC
membership identities pinned so an old cycle cannot be swapped for a new
same-sized one. Barrel-thinning progress and true cycles are each visible.

**Independent corroboration:** the leaf-only maximum SCC of **4** exactly
reproduces the verdict's central census refinement ("barrel-bypassed, the
largest true SCC is 4 modules") from a resolver written from scratch for
this card. The eight true cycles enumerated in the registry are precisely
the ones DEC-IG-2 must break or grandfather. The package-edge model gives
81 rather than the packet's 62 because this resolver charges every
*ancestor* package, not only the named barrel — mechanism identical,
magnitude model-dependent; both are ratcheted.

**Marker reconciliation:** the verdict's ~993 counts a broad card-history
idiom. The precise `# ---- CARD` string is **178** in `.py` files (the
broad idiom over `src/parcel_robot` is 340). 101 of the 178 live in the
eight targets — `runtime.py` 46, `ci_gate.py` 19, `tool_broker.py` 16,
`audio_gateway.py` 8, `web_panel.py` 7, `lane.py` 5, `pipeline.py` 0,
`agent.py` 0.

## 3. Seeded-red proof

Two-part, both run against the shipping measurement code (not a
reimplementation). Part A proves genuine regressions are *detected*
end-to-end; Part B proves the assertions fire against the **real repo's
own measurements**. Controls in both parts confirm green is not vacuous.

**Part A — synthetic tree** (7-file miniature product tree in the
scratchpad; `REPO` re-pointed, baseline re-frozen to that tree, then one
real regression injected per class — real file discovery, real AST, real
Tarjan SCC, real marker counting):

| seed | result |
|---|---|
| A1 — new 1,001-line module | **RED** `new module(s) above 1000 lines: ['src/parcel_robot/bloat.py']` |
| A2 — new 101-line function | **RED** `new function(s) above 100 lines: ['freshly_bloated']` |
| A3 — new import cycle (`beta` imports `alpha` back) | **RED** `largest import cycle (with_package_edges) grew from 2 to 3 modules` |
| A4 — one extra `# ---- CARD` marker | **RED** `marker count rose from 1 to 2` |
| A5 — control: tree restored | **GREEN** on all four |

**Part B — real tree, baseline loosened by one unit** (the true tree's
measurements trip a baseline weakened by exactly one):

| seed | result |
|---|---|
| B1 — `runtime.py` dropped from the oversized baseline | **RED**, names `src/parcel_robot/runtime.py` |
| B2 — `scene_report` dropped from the long-fn baseline | **RED**, names `scene_report` |
| B3 — long-fn count baseline −1 | **RED** `rose from 152 to 153` |
| B4 — leaf cycle-count baseline −1 | **RED** `rose from 7 to 8` |
| B5 — leaf max-SCC baseline −1 | **RED** `grew from 3 to 4 modules` |
| B6 — marker baseline −1 | **RED** `rose from 177 to 178` |
| B7 — stale baseline path injected | **RED** `baseline lists module(s) that no longer exist` |
| B8 — control: true baseline on the real tree | **GREEN** on all five |

Every regression class the ratchet claims to catch was demonstrated to
redden, with the correct message naming the offender.

## 4. Rules compliance

Guard wrapper (`--label dec0`) for every pytest; never `-n auto`; never
`ci_gate.py --tier`; no `noqa` (0 in the file); `ruff check` and
`ruff format --check` both clean; git read-only; `:8765`,
`/tmp/parcel_sim.sock` and `parcel_memory.sqlite3` untouched.

## 5. Notes for the verifier

- The ratchet's baseline was measured on a tree two wave-A executors were
  editing. Every quantity is set- or count-based over files already in the
  baseline, so wave-A churn inside `lane.py`/`runtime.py` cannot redden it.
  A wave-A card that creates a **new** >1,000-line module would redden
  `test_no_new_oversized_module` — correctly, and the failure message says
  how to proceed.
- `tests/` is out of ratchet scope by choice; test bulk is not the debt
  this program retires. If a later card wants it ratcheted, the same
  measurement functions take it by editing `SCOPED_DIRS`.
- Re-freezing the baseline: the command is in the module's header comment,
  and it must only ever move numbers **down**.
