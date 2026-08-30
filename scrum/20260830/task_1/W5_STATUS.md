# W5 · REFREEZE-1 — executor status (Opus)

**Card:** `scrum/20260830/task_1/W5_REFREEZE.md` (+ **Amendment A1**, 07:0x — binding, re-sequences the card) ·
**Rules:** `scrum/20260830/task_1/README.md` integrator rules 1–5 (rule 2 re-freeze conditions, rule 3 Sol's four checks) ·
**Verifier:** Fable (parcel-0e) · **Lens:** parcel-fb

## 0 · Pre-flight (integrator rule 1)

| row | value |
|---|---|
| worktree | `/home/jaewoo-jang/.cache/parcel-0e/wb/w5` (`git worktree add --detach … HEAD`) |
| HEAD | `c96ac345358ec2786748fc3a885c35d32710c5e2` ("index: regenerate CODEBASE_INDEX.md in a clean worktree at 05a5cb9…") |
| venv | `ln -s /home/jaewoo-jang/Desktop/Projects/Parcel/.parcel` → `<wt>/.parcel` |
| env | `PYTHONPATH=<wt>/src:<wt>`, `MUJOCO_GL=egl`, `OPENBLAS_NUM_THREADS=32`, `TMPDIR` unset |
| **`parcel_robot.__file__`** | **`/home/jaewoo-jang/.cache/parcel-0e/wb/w5/src/parcel_robot/__init__.py`** ✅ resolves inside the worktree |
| main repo | READ-ONLY. No `git add` / `commit` / `stash` anywhere. The only main-repo path written by this card is **this file**. |
| scratch | `/tmp/claude-1000/…/scratchpad/w5` |

Worktree `git status` before any work: clean except the three Sol files copied in for Part B (below) and the `.parcel` symlink (untracked, not part of any patch).

---
## 1 · Part A (PREPARATION ONLY — no artifact regenerated, no re-freeze performed)

Amendment A1 re-sequences Part A onto **v5** (W4's episode-set version). Everything below is the
**v4 story**, measured at HEAD `c96ac34` in the clean worktree, which the v5 bridge must carry as
the superseded-row narrative. **Nothing here is a re-freeze**: the committed
`nav-instruct-v1-baseline-v4-20260811T070536Z.json` and the ledger are untouched, and the runs went
to scratch with `--no-ledger`.

### 1.1 Digest confirmation (the card's required number)

```
cd <wt>; PYTHONPATH=<wt>/src:<wt> MUJOCO_GL=egl
.parcel/bin/python -m evals.nav_instruct.run_nav_instruct_v1 \
    --minival --mode baseline --episode-version v4 --no-ledger --out <scratch>/minival-v4-head
```
→ `nav-instruct-v1-baseline-v4-20260830T103915Z.json`, recipe
`report_digest(drop_aggregate_scene=True, compact=True)` from `tests/test_nav_instruct_digest_recipe.py:80`:

| row | value |
|---|---|
| **required (card / C1 / C3)** | `021b67ab73c4e7be…` |
| **measured at HEAD in <wt>** | **`021b67ab73c4e7be647aba1a17e20a193ebf23b826a18d5b0990e296e5708496`** ✅ **equal** |
| committed frozen row | `c172da375ff23987cb6414fe8899fa263f7ec00ef363659306a38c7719f7553a` |
| `episode_digest` | `4113607b92c734dfdd46004b6e77baf6575fc2a1c493e5d9dc5a12c6c5490222` — **identical** to the committed row (condition (iii): the episode SET never moved) |
| SR / SPL | 0.24 → **0.20** · 0.19325925214230982 → **0.15325925214230984** |
| **collisions** | **0 = 0** (condition (i)) |
| **false arrivals** | **0 = 0** (condition (i)) |
| authority | `{agreement 21, authority_disagreement 4}` → `{agreement 20, authority_disagreement 5}` |
| refusals | 6 = 6 |

### 1.2 FINDING (new, not in the card): `021b67ab…` also flips the BUDGET POLICY

The committed frozen row carries `"budget_policy": "scaled-path-v1"`; the CLI's default is
`fixed`, so the `021b67ab…` run every card cites (mine, C1's, C3's) is a **different runner
invocation**, not only a different tree. Consequence: **all 25 rows** differ in `max_steps`
(e.g. `437 → 200`, `1200 → 200`), which is why a naive row diff reports 15 moved rows.

I therefore re-ran the same tree under the committed row's own budget policy to isolate the CODE axis:

```
… --minival --mode baseline --episode-version v4 --budget-policy scaled-path-v1 --no-ledger …
```
→ `nav-instruct-v1-baseline-v4-20260830T104457Z.json`, digest **`a47b27bfafddbc797d213823b58352b06ea683a5b6ae1d632391fe40eecd58b1`**,
same SR 0.20 / SPL 0.15325925…, same collisions 0 / false arrivals 0, same `episode_digest`.
**7 rows carry any field delta; 5 are outcome moves, 2 are trace-length-only.**

**For the re-freeze this is a decision the card must make explicitly:** regenerate under
`scaled-path-v1` (comparable to the superseded row, digest `a47b27bf…`) or under `fixed`
(comparable to every wave-A/B measurement, digest `021b67ab…`). They are not the same artifact and
one of the five attributed rows changes its terminal reason between them (below).

### 1.3 Attribution bridge DRAFT — `nav-instruct-v1-baseline-v4-20260811T070536Z` → HEAD `c96ac34`

Measured under the committed row's own budget policy (`scaled-path-v1`), so every delta below is
the CODE axis. Cause column per rule 2 (ii).

| # | episode | before (committed `c172da37…`) | after (HEAD) | cause |
|---|---|---|---|---|
| 1 | `nav-object_relative-A-00-3efbba45` *"sit next to the bench"* | `arrived_verified`, **success**, SPL **1.0**, dtg 0.0, `system_arrival`/`scorer_arrival` True, `arrival_branch trace_end_hold`, trace 87 | `semantic_target_unreachable`, **failed**, SPL 0.0, dtg **1.8084 m**, both arrivals False, `arrival_branch none`, trace 62 | **card A2's clearance cost, since ≤ 08-24** — `research/20260824/nav-quality/RESULTS.md` §1.4 **lines 242-246** (the row) + **258-290** (the mechanism: `semantic_target_resolved` fires, then the goal cell is blocked at the commissioned inflation → `_release_unreachable_candidate` `pipeline.py:5552` → `_target_missing_command` `pipeline.py:5588`). **A LOST SUCCESS — recorded as a LOSS, never as a fix.** |
| 2 | `nav-object_goal-B-05-0ee314d5` | `navigation_step_limit`, `timed_out`, L4_planning / planning_error, dtg 0.3955, trace 237 | `semantic_target_unreachable`, `failed`, **L2a_vocabulary** / grounding_error, dtg 0.9525, trace 63 | A2 clearance (same mechanism); the L4→L2a relabel is the **misattribution** NAV-QUALITY §1.4 names — grounding succeeded, routing did not |
| 3 | `nav-object_goal-D-15-109547e2` | `navigation_step_limit`, `timed_out`, L4_planning, dtg 3.0283, trace 354 | `semantic_target_unreachable`, `failed`, L2a_vocabulary, dtg 3.3252, trace 62 | A2 clearance (same) |
| 4 | `nav-object_relative-D-15-61f68ad6` | `navigation_step_limit`, `timed_out`, L4_planning, dtg 4.1822, trace 370 | **budget-dependent** — under `scaled-path-v1`: `semantic_target_not_found`, **L1_parse / refusal**, dtg 4.1607, trace 219; under `fixed` (the `021b67ab…` arm): `semantic_target_unreachable`, L2a_vocabulary, dtg 4.1591, trace 83 | A2 clearance; **the terminal reason is not budget-invariant — the bridge must name the regeneration command** (the card's stated `→ semantic_target_unreachable` holds only on the `fixed` arm) |
| 5 | `nav-region_goal-D-15-1b8b2361` *"go to the crosswalk"* | `navigation_step_limit`, `scorer_arrival` **False**, **agreement**, dtg 2.1020, trace 204 | **`navigation_step_limit_inside_goal`**, `scorer_arrival` **True**, **`authority_disagreement`**, dtg **0.0**, trace 200/204 | **a379bf4** (*feat: integrate companion contracts and document robotics design*) — the same single-commit attribution C0 recorded in the panel provenance: on `f3ecb5c` D-15 stalls at the start; on a379bf4/HEAD it drives 3.0 m, ends INSIDE the scorer's crosswalk polygon and the SYSTEM refuses the claim |
| — | `nav-region_goal-A-00-1c735162` | trace 103, `time_to_goal_s` 10.2 | trace 101, 10.0 | trace-length only; success/authority/dtg unchanged. Cause not separately attributed (tick-level, same direction as A2's clearance) |
| — | `nav-object_goal-A-00-4caa923b` | trace 17, `time_to_goal_s` 1.6 | trace 51, 5.0 | trace-length only; success/authority/dtg unchanged. Same note |

**The cost, stated as a cost:** SR **0.24 → 0.20** and SPL **0.19326 → 0.15326** — the whole −0.04 is
episode 1's lost 1.0. This is a **regression priced on the frozen corpus**, not an improvement.
Rows 2–4 finish in 62–219 ticks instead of grinding 237–370 into a step-limit timeout, which *looks*
better; the score nevertheless moved them L4_planning → L2a_vocabulary, and NAV-QUALITY §1.4 is
explicit that the cause is clearance, not vocabulary. Neither fact may be presented as a gain.

**Condition (i) — not a re-baseline of a red safety result:** collisions **0 = 0**, false arrivals
**0 = 0**, refusals 6 = 6, on both arms. **Condition (iii) — the episode SET never moves:** v4's
`episode_digest` `4113607b…` is byte-identical on every arm; v4's episodes/manifest are untouched.

**Why no gate saw any of this:** `scripts/ci_gate.py:2049-2063` (`evaluate_hard_safety`) reads only
`collision_total` and `authority_histogram.false_arrival` out of the committed **ledger row** — it
never re-derives the baseline. Both pinned numbers are unmoved, so the whole SR/SPL regression is
invisible to the hard gate by construction. (`research/20260824/nav-quality/RESULTS.md` §1 lines 44-50.)

### 1.4 How the runner writes a full-matrix baseline row

`evals/nav_instruct/run_nav_instruct_v1.py` — one CLI, matrix vs minival by flag:

* **full matrix** = omit `--minival`: `--seed 20260804 --per-family 25` → 125 rows (5 families × 5 tiers × 5); `--minival` takes the 25-row CI slice.
* the **frozen-baseline** ledger row is the one written with `--mode baseline` **without** `--no-ledger`; `_latest_frozen_baseline_row` in `ci_gate.py` picks the last row with `frozen_baseline: true`.
* `--freeze` (opt-in) additionally overwrites the `scrum/.../freeze/` baseline pointer.
* `--refreeze-provenance TEXT` stamps the re-freeze reason onto **both** the report and the ledger row (added by E8 for exactly this purpose) — the re-freeze must use it.
* `--episode-version {v1,v1a-scene-truth-only,v2,v3,v4,v4s}` selects the frozen set **and with it the arrival rule** (`ARRIVAL_RULE_FOR_VERSION`, `evals/nav_instruct/runner.py`); W4 adds `v5` there.
* `--budget-policy {fixed,scaled-path-v1}` — see §1.2; the committed v4 row used `scaled-path-v1`.

### 1.5 What a re-freeze must touch (the complete list, from the E8 precedent + this tree)

| # | path | what must change | notes |
|---|---|---|---|
| 1 | `evals/nav_instruct/results/nav-instruct-v1-baseline-v5-<ts>.json` | **new** frozen-baseline report | the superseded `…-v4-20260811T070536Z.json` is **KEPT** (rule 2, E8 precedent) |
| 2 | `evals/nav_instruct/results/ledger.jsonl` | **one appended row**, `frozen_baseline: true`, carrying `refreeze_provenance` | append-only; the prefix must stay byte-identical (`tests/test_nav_instruct_episodes_v3.py::test_frozen_ledger_prefix_is_byte_identical_after_the_v3_append` is a **gate node id**, `ci_gate.py:135`). ⚠️ the dirty root already appended a **candidate** row (`nav-instruct-v1-candidate-v4-20260830T071509Z`, `frozen_baseline: false`, `false_arrival: 1`) — harmless to the gate, but the integrator must know the file is dirty |
| 3 | `evals/nav_instruct/bridge_v4_v5.py` (+ `results/bridge_v4_v5.json`) | **new**, in `bridge_v3_v4.py`'s shape: spec bridge, derivation, 2×2 with the required signature, per-episode before/after | rule 2 (iii): B32 moves 45/125 episode definitions ⇒ episode-SET change ⇒ **v5**, never a v4 rewrite |
| 4 | `evals/nav_instruct/episodes/v5/**` | 125 episode JSONs + `manifest.json` | W4's; v1–v4 stay byte-identical |
| 5 | `scripts/ci_gate.py:327-328` `DIGEST_SENTINELS` | **add** `evals/nav_instruct/episodes/v5/manifest.json: <sha>` + the re-pin log comment above it (`:186-205` style) | **no overlap** with the dirty root's `ci_gate.py` hunks — those are at `@@ +69,8`, `+100`, `+498,224`, `+2612`, `+2699`, `+3384`, `+3388`, `+3392`, `+3404`; the pins live at 190-205 / 309-333 / 400-407 |
| 6 | `scripts/ci_gate.py:2737` `evaluate_nav_instruct_candidate` | `--episode-version v4` → `v5` | E8 moved this in the same commit |
| 7 | `scripts/ci_gate.py:407` `PINNED_FROZEN_FALSE_ARRIVAL = 0` | **stays 0 or tightens** — never loosens (rule 2 (i)) | the new row must carry `collision_total 0`, `false_arrival 0` |
| 8 | `tests/test_ci_gate.py:317-323` | sentinel-count literal `4 → 5`, with the reason inline (the literal is deliberate) | |
| 9 | `tests/test_nav_instruct_digest_recipe.py` | `FROZEN_ROW` → the v5 report; the five published digests + `EPISODE_DIGEST` re-derived **for v5 only** | v4's numbers stay published as the superseded row's (A1: "digest-recipe test updated for v5 only") |
| 10 | `tests/test_nav_instruct_episodes_v5.py` | **new** (the `…_v4.py` shape: fresh-generation equality, manifest correction record, id stability, ledger-prefix) | W4's |
| 11 | `evals/nav_instruct/README.md` | episode-set table row (`:24`), the "why v5" paragraph, the current-baseline command block (`:6-8`), `bridge_v4_v5.py` in the file list (`:139`) | |
| 12 | `evals/nav_instruct/results/mutation_panel.json` + `scripts/mutation_panel.py` | regenerated **LAST**, on v5 (E8 ordering) — Part B | `_CURRENT_FROZEN_EPISODE_SET = max(vN)` (`tests/test_mutation_panel_freshness.py:44-45`) reddens any panel left on v4 |
| 13 | `scrum/20260830/task_1/W5_STATUS.md` | this record | |
| 14 | `CODEBASE_INDEX.md` | regenerated in a clean worktree at HEAD **after** the wave list is committed | integrator's, not the executor's |

Not in the list on purpose: `evals/nav_instruct/episodes/v1|v2|v3|v4/**`, the v4 report, and every
historical STATUS quoting `c172da37…`/`4113607b…` — a superseded artifact keeps its numbers.

---
## 2 · Part B — Sol's panel remediation, verified under integrator rule 3

Sol's files are **NOT** in HEAD. They were copied **READ-ONLY** from the main repo's working tree
into the worktree at 06:3x EDT and **never modified**.

### 2.0 Hashes (check (d))

| file | at copy (06:3x) | after verification (07:2x) | main repo now |
|---|---|---|---|
| `scripts/mutation_panel.py` | `7a2192b98de8d127ea0bda9f3af5b66e5b5cefa3` | **same** | **same** |
| `evals/nav_instruct/results/mutation_panel.json` | `f07de66db026adc32b6031edb86b2fcf83265906` | **same** | **same** |
| `tests/test_mutation_panel_freshness.py` | `fd8725fe172252e773564c266efeed4005bcf960` | **same** | **same** |

(Three reads: copy 06:3x → after the live panel 07:0x → after the freshness suite 07:2x, worktree and
main repo, all six values identical.)

HEAD blobs for the same paths, for the diff record: `cfaa9bbe…`, `3cc797f2…`, `e7019ef9…`.
Sol has stopped editing (three consecutive reads identical). ✅ **check (d) PASS.**

**A FOURTH file belongs to this remediation:** `scrum/20260829/task_2/C0_SOL_REMEDIATION.md`
(`0dfe268dc0f1e4c26d3ff3c19147f24611e77ad6`, tracked, `+37` lines vs HEAD) — Sol's panel provenance
ends *"See scrum/20260829/task_2/C0_SOL_REMEDIATION.md."* Rule 3 says "exactly its three files"; if
only three land, the gated artifact's provenance cites a record that is not in the commit.

### 2.1 Check (a) — provenance verbatim + each new row justified · **PASS (with two notes)**

*Verbatim retention.* HEAD's `PANEL_REGENERATION_PROVENANCE` (5092 chars) is a **strict prefix** of
Sol's (6185 chars) — proven by parsing both constants and `str.startswith`. Sol's change is purely
**additive** (1093 appended chars). Therefore all of C0's sentences survive **byte-for-byte**:

* `"COST, written rather than hidden: no_authority_disagreement disabled as a kill channel from this re-run; re-armed when D-15 agrees again."` ✅
* the a379bf4 attribution — `"The DIFF IS ATTRIBUTED TO a379bf4 (feat: integrate companion contracts and document robotics design, the owner's hard-safety / terminal-arrival change), reproduced independently at single-commit resolution…"` ✅
* the re-run reason — `"RE-RUN 2026-08-29 (card C0, FIX-SUBSTRATE-1) as the RECORDED RE-RUN half of the card's (a)-fix-product / (b)-recorded-re-run choice… WHY (b): the superseded artifact was written at 20260828T084754Z from a working tree that reproduces on NO commit…"` ✅
* the declared-disable clause and its `test_red_clean_checks_are_declared_disabled_kill_channels` reference ✅

The JSON's `episode_set_provenance` is **equal to the script constant** and is likewise a superset of HEAD's.

*Each new row justified with per-episode intervention counts.* The counts are **not** at the payload
top level — Sol put them at **`clean_run.reactive_gate_coverage`** with a nested **`per_episode`**
map (and per mutant at `mutants[i].run.reactive_gate_coverage`); `clean_safety_fields()` surfaces an
aggregate-only copy into the gated field set. In Sol's committed JSON:

| new row | calls | requested_nonzero | **changed_nonzero** | translation_zeroed |
|---|---|---|---|---|
| `nav-region_goal-C-11-25d4e602` | 200 | 138 | **78** | 0 |
| `nav-region_goal-D-17-448696db` | 111 | 95 | **18** | 0 |
| `nav-object_goal-D-18-19a95961` | 184 | 110 | **14** | 0 |
| `nav-object_relative-C-11-3bf174e9` | 165 | 106 | **31** | 0 |

All four `changed_nonzero > 0` → the gate binds on each **as recorded**. ✅ Clean authority
`{agreement: 9}` and collisions 0 in the same payload satisfy the "agreement/zero-collision" selection rule.

**Note (a-1):** the provenance's claim that these are *"every additional intervention row whose clean
run has agreement authority and zero collisions"* out of 125 rows is a scan result recorded only in
`C0_SOL_REMEDIATION.md`; I did not re-run the 125-row scan. Not required by rule 3(a).
**Note (a-2):** all five clean checks are GREEN in Sol's payload, so the declared disable
`no_authority_disagreement` is no longer in force — yet the appended text never **withdraws** the
declaration, it only adds the repair note. The card's acceptance line ("no declared disable left that
D-15 has satisfied") is therefore not met by the text either. Moot given (b)/(c) below, and A1 is
right that the withdrawal must come **from a regeneration**, not a hand edit.

### 2.2 Check (b) — live reproduction in a clean worktree at HEAD · **FAIL**

`python scripts/mutation_panel.py --out <scratch>/sol-panel.json` (19 m 03 s, worktree, HEAD `c96ac34`
+ exactly Sol's three files):

* `passed` **True**, survivors `[]`, equivalent `[]`
* `reactive_gate_disabled` **killed**, and killed **through** `reactive_gate_exercised` (plus `success_set_identical`, `mean_dtg_within_tolerance`, `failure_histogram_identical`, `final_poses_within_tolerance`) — **the fifth check works exactly as designed** ✅
* **but the clean fields are NOT equal to the copied JSON** ❌ — the rule's actual bar:

| clean field | Sol's committed JSON | **LIVE at HEAD in <wt>** |
|---|---|---|
| `authority` | `{agreement: 9}` | **`{agreement: 8, authority_disagreement: 1}`** |
| `clean_checks.no_authority_disagreement` | **True** | **False** |
| `reactive_gate_coverage.calls` | 962 | **1074** |
| `reactive_gate_coverage.requested_nonzero` | 638 | **630** |
| `reactive_gate_coverage.changed_nonzero` | 162 | **188** |
| `reactive_gate_coverage.translation_zeroed` | **0** | **105** |
| clean successes | 6 | **5** |
| `collisions` / `no_false_arrival` / `path_length_plausible` / `reactive_gate_exercised` | 0 / T / T / T | 0 / T / T / T (unchanged) |

**The whole divergence is one episode, and its mechanism is named.** Per-episode clean coverage,
LIVE-at-HEAD vs Sol's:

| episode | calls | requested_nonzero | changed_nonzero | translation_zeroed |
|---|---|---|---|---|
| `nav-region_goal-D-15-1b8b2361` | **200** / 88 | **180** / 77 | **105** / 0 | **105** / 0 |
| `nav-region_goal-C-11-25d4e602` *(new)* | 200 / 200 | **28** / 138 | **0** / 78 | 0 / 0 |
| `nav-region_goal-D-17-448696db` *(new)* | 110 / 111 | 94 / 95 | 17 / 18 | 0 / 0 |
| `nav-object_goal-D-18-19a95961` *(new)* | 185 / 184 | 110 / 110 | **14** / 14 | 0 / 0 |
| `nav-object_relative-C-11-3bf174e9` *(new)* | 165 / 165 | 106 / 106 | **31** / 31 | 0 / 0 |
| the other four historical rows | identical | identical | identical | identical |

**`translation_zeroed` 0 → 105 is the signature.** C0's own provenance says, of D-15 at HEAD:
*"the navigator keeps requesting vx=0.102 m/s and apply_reactive_safety returns zero with
meta='stopped' on **105/200 ticks**"*. My live run at HEAD measures exactly **105 zeroed translations
over 200 calls on that episode**. Sol's artifact records **0 of 88**. So **Sol's panel was generated
on a tree where the reactive gate does not bind on D-15 — the owner's uncommitted
`grid_planner.py`**, i.e. precisely `scrum/20260829/task_2` close-out **item 2** and the LIVE
COLLISION warning. On that tree D-15 finishes in 88 ticks and *arrives* (`agreement`); at HEAD it runs
the full 200, the gate hard-stops it 105 times, and the row records `authority_disagreement`.

**Consequences that matter beyond a stale artifact:**
1. **Sol's premise does not hold at HEAD.** The stated reason for the repair — *"reactive_gate_disabled had become equivalent … the clean gate changed 21 nonzero requests, but the disabled-gate final pose moved only 0.002611 m"* — is a property of the dirty tree. At HEAD the mutant is **not** equivalent: it is killed through five checks on the five *original* rows' behaviour plus D-15's 105 hard stops.
2. **Sol's strongest witness evaporates at HEAD.** `nav-region_goal-C-11-25d4e602`, the row contributing 78 of the 162 changed requests, has **`changed_nonzero = 0`** at HEAD (28 nonzero requests, none altered). Three of the four new rows still bind at HEAD (14 / 17 / 31); that one does not.
3. **The "no hard-stop witness" caveat is also dirty-tree-only.** Sol writes *"all observed v4 interventions are slowing and hard-stop coverage remains unproven"*. At HEAD there are **105 hard translation stops** on D-15 — the designed nonzero→zero case Sol asks for already exists in the frozen five.

### 2.3 Check (c) — the freshness test green through the guard · **FAIL**

`~/.cache/parcel-guard/pytest_guard.sh --label W5 <wt>/.parcel/bin/python -m pytest tests/test_mutation_panel_freshness.py -q -p no:cacheprovider` (from the worktree; guard log `START label=W5 … 06:58:19`).

| node | verdict | why |
|---|---|---|
| `test_committed_mutation_panel_is_on_the_current_frozen_set` | PASS | payload is on `v4` = `_CURRENT_FROZEN_EPISODE_SET`; 7/7 killed; the widened `episode_ids`/matrix-pin assertions hold |
| **`test_committed_panel_safety_fields_still_reproduce`** | **FAIL** | `AssertionError: the committed mutation panel no longer reproduces its own safety-relevant fields on this tree: committed={'collisions': 0, 'authority': {'agreement': 9}, 'clean_checks': {…'no_authority_disagreement': True…}, 'reactive_gate_coverage': {'calls': 962, 'requested_nonzero': 638, 'changed_nonzero': 162, 'translation_zeroed': 0}} live={…'no_authority_disagreement': False…, 'calls': 1074, 'requested_nonzero': 630, 'changed_nonzero': 188, 'translation_zeroed': 105}} — the hard-safety gate must not certify from it until the divergence is diagnosed` |
| **`test_mutation_panel_runs_on_the_current_frozen_set_live`** | **FAIL** | **byte-identical assertion text** — the same divergence reached through the whole-panel path (`clean_safety_fields(committed) != clean_safety_fields(live)`), i.e. it is one defect seen twice, not two |
| `test_red_clean_checks_are_declared_disabled_kill_channels` | PASS | vacuous on the committed payload (no red clean check); the widened `_UNDISABLEABLE_CLEAN_CHECKS` now includes `reactive_gate_exercised` and nothing red overlaps it |
| the 6 pure fixture cells (both directions, survivors, undisableable list) | PASS | pure functions, no simulator |

**Result: `2 failed, 9 passed, 2 warnings in 1235.67s (0:20:35)`** — independently matching the
integrator's run in `~/.cache/parcel-0e/sol-panel-wt` (2 failed / 9 passed in 1254 s). Two
independent worktrees, same two nodes, same message. The direction is the **RED** one (live redder than
committed), *not* the green-direction "withdraw the declaration" message — so this is **not** a
declaration coming due; it is a gated artifact that a live tree contradicts, which the file's own
docstring says is *"NOT a licence to regenerate"*.

### 2.4 Verdict — **Part B: NOT LANDED**

| check | rule 3 wording | verdict |
|---|---|---|
| **(a)** | provenance keeps C0's sentences verbatim; each new row justified with per-episode intervention counts, `changed_nonzero > 0` per row | ✅ **PASS** (notes a-1, a-2) |
| **(b)** | panel reproduces LIVE there: `run_panel` passed True, **clean fields equal**, `reactive_gate_disabled` killed through the new check | ❌ **FAIL** — `passed True` ✅ and killed-through-`reactive_gate_exercised` ✅, but **clean fields differ on 6 of 9 gated values** |
| **(c)** | the freshness test green incl. the widened undisableable list and the declared-disable ratchet | ❌ **FAIL** — 2 failed / 9 passed; the two live nodes red |
| **(d)** | `git hash-object` of the three files at verification time equals what is staged | ✅ **PASS** — unchanged across copy → verification → now |

Sol's files are **untouched** by this card. Nothing of Sol's is proposed for landing.

**What is Sol's and worth keeping (the design, not the artifact):** the `reactive_gate_exercised`
undisableable check, the per-episode gate-coverage counters, `passed = not survivors and not
equivalent`, the Markdown that cannot print PANEL PASSED over a red payload, and the pinned
full-matrix substrate (`PANEL_MATRIX_SEED/PER_FAMILY/DIGEST` +
`test…episode_ids == list(PANEL_EPISODE_IDS)`). All of it verified to work at HEAD by my live run.
What cannot ride is **the artifact and the row selection**, both measured on the owner's dirty tree.

**Hygiene:** 0 new `noqa` (the single `BLE001` at `mutation_panel.py:843` is HEAD's, at HEAD's `:725`);
`ruff check` clean; `ruff format --diff` reports the same two pre-existing deltas at HEAD.

**Board line for Sol (either way, per rule 3):** *"W5 verified your remediation in a clean worktree
at c96ac34 + exactly your three files: (a) PASS, (d) PASS, (b) and (c) FAIL — the panel was generated
on a tree where the reactive gate does not bind on `nav-region_goal-D-15` (0 zeroed translations vs
105 at HEAD), i.e. the owner's uncommitted `grid_planner.py`. Your design lands; the artifact and the
four-row selection are being re-derived on v5 by measurement. Do not re-land; further changes are a new card."*

---
## 3 · Amendments on the record

### Amendment A1 (integrator, 07:0x) — re-sequences the card
W4 first (v5 episode set), then W5 on top of W4's patch. Part A becomes the **v5** baseline row with
v4 kept superseded and its five moved rows recorded as the v4 story (§1.3 above). Part B becomes
**"Sol's design, re-run on v5"**. Reason, verified in this tree:
`tests/test_mutation_panel_freshness.py:44-45` computes
`_CURRENT_FROZEN_EPISODE_SET = max(v for v in EPISODE_SETS if re.fullmatch(r"v\d+", v))`;
`EPISODE_SETS` currently reads `['v1', 'v1a-scene-truth-only', 'v2', 'v3', 'v4', 'v4s']` → `v4`.
The moment W4 adds `v5`, **any panel left on v4 reddens**
`test_committed_mutation_panel_is_on_the_current_frozen_set` — so Sol's three files cannot land
unchanged even if (b) and (c) had passed.

### Amendment A2 (integrator, 07:2x) — the v5 witness rows are re-selected BY MEASUREMENT
Binding: do **not** inherit Sol's four ids. Run the clean pass over the **v5 full matrix** with the
gate-coverage counter, choose rows with per-episode `changed_nonzero > 0` on the clean run, then
confirm `reactive_gate_disabled` reddens `reactive_gate_exercised` on each chosen row. Keep Sol's
four only if they survive the measurement (attributing the design either way); otherwise the list
changes and the provenance says why. Store the counts **per row** in the panel JSON under a named
field and make the freshness assertion read the **per-row** field, not the aggregate, so a row that
stops binding is visible **by name**.

**A2 is already vindicated on v4:** at HEAD, `nav-region_goal-C-11-25d4e602` — Sol's largest witness
(78 of 162 changed requests) — measures **`changed_nonzero = 0`**. An aggregate-only assertion
(`clean_coverage["changed_nonzero"] > 0`, `tests/test_mutation_panel_freshness.py:100`) stays green
while that row silently stops binding, which is the exact rot this file exists to make loud.

### v5 plan (Part A + Part B, to execute on the integrator's go)

**Order (E8's, and A1's):** v5 episodes → v5 baseline row + bridge → `ci_gate` pins → digest-recipe
test → README → **panel LAST**.

**Panel code sites to move to v5** (`scripts/mutation_panel.py`): `EPISODE_SET_V4` import `:75` and
uses `:701` (`_episodes`), `:733` (`ARRIVAL_RULE_FOR_VERSION[…]`), `:881` (payload
`episode_set_version`); `PANEL_MATRIX_SEED/PER_FAMILY/DIGEST` `:94-98` (the digest must be
**re-derived on v5** — `matrix_digest(generate_episode_matrix(seed=20260804, per_family=25,
version=v5))`); `PANEL_EPISODE_IDS` `:229-248` (re-selected per A2 — note B32 moves 45/125 episode
definitions, so affected ids' hashes change and Sol's four may not even **exist** in v5);
`PANEL_REGENERATION_PROVENANCE` `:180-224` (C0's lineage carried forward verbatim, the v4→v5 reason
appended, Sol attributed for the design and the `reactive_gate_exercised` check).
`evals/nav_instruct/runner.py:471` `ARRIVAL_RULE_FOR_VERSION` needs a `"v5"` entry (W4's).

**The declared disable.** If D-15 agrees on v5 (B32's band ∩ support polygon is exactly the change
that could make the crosswalk row agree), the withdrawal is produced **by the regeneration**: the
committed-red → live-green direction makes `freshness_failure_message` emit
*"STALE IN THE GREEN DIRECTION … re-run the panel and withdraw the 'no_authority_disagreement
disabled as a kill channel' declaration"* — that message is the proof, and only then does the new
provenance drop the clause. **Never a hand edit** (A1).

**Check (v), added by A1:** the new panel's `episode_set_version` must equal
`_CURRENT_FROZEN_EPISODE_SET`, verified by **running** `tests/test_mutation_panel_freshness.py` in
this worktree, not by reading the constant.

**Cost note for planning:** one full panel campaign at HEAD is **19 minutes** in a clean worktree
(nine episodes × eight runs); the freshness file is ~21 minutes. Budget ~45 minutes per v5 panel
iteration, and the A2 selection scan (125 v5 rows, clean pass with the counter) on top.

---

## 4 · Standing-constraint compliance

| constraint | row |
|---|---|
| worktree only, never the dirty root | ✅ every command from `/home/jaewoo-jang/.cache/parcel-0e/wb/w5`; `parcel_robot.__file__` verified inside it |
| git read-only | ✅ no `add` / `commit` / `stash`; the worktree's only diff is Sol's three copied files |
| main-repo writes | ✅ exactly one path: `scrum/20260830/task_1/W5_STATUS.md` |
| Sol's files unmodified | ✅ hashes identical across copy → verification → now |
| every pytest through the guard | ✅ `pytest_guard.sh --label W5`; no `-n auto`; no `--pdb` |
| `ci_gate.py --tier` never run by this executor | ✅ |
| `TMPDIR` unset | ✅ |
| ledger / frozen artifacts untouched | ✅ all runs `--no-ledger`, output to scratch |
| owner's live stack (`:8765`, `/tmp/parcel_sim.sock`) | ✅ untouched (PIDs 807004 / 807140 still up) |
| 0 `noqa`, ruff clean on anything this card would land | ✅ (nothing to land yet) |

## 5 · Register rows (integrator rule 4) and open questions

| row | value |
|---|---|
| tested at candidate sha | `c96ac345358ec2786748fc3a885c35d32710c5e2` (HEAD) in `/home/jaewoo-jang/.cache/parcel-0e/wb/w5` |
| runtime.py / executive.py hooks | **none** — this card writes no product code |
| the only main-repo path written | `scrum/20260830/task_1/W5_STATUS.md` |
| artifacts (scratch, kept for the verifier) | `…/scratchpad/w5/minival-v4-head/nav-instruct-v1-baseline-v4-20260830T103915Z.json` (`021b67ab…`), `…/minival-v4-head-scaled/nav-instruct-v1-baseline-v4-20260830T104457Z.json` (`a47b27bf…`), `…/sol-panel.json` (**the live-at-HEAD panel**, `passed True`, `{agreement 8, authority_disagreement 1}`, `translation_zeroed 105`), `…/freshness.log`, `…/clean-fields.log` |

**Open questions for the integrator (each blocks a decision, none is mine to make):**

1. **Which budget policy does the v5 re-freeze run under?** (§1.2) `scaled-path-v1` matches the
   superseded v4 row; `fixed` matches every wave-A/B measurement. They give different artifacts, and
   `object_relative-D-15`'s terminal reason differs between them.
2. **One frozen row, not two.** `run_nav_instruct_v1.py:514` sets `frozen_baseline: True` for **any**
   `--mode baseline` run, and `ci_gate._latest_frozen_baseline_row` takes the **last** such row. If
   the v5 re-freeze appends both a minival and a full-matrix baseline row, the hard gate silently
   retargets onto whichever was written second. Every prior re-freeze appended exactly one (minival).
3. **Sol's fourth file.** `scrum/20260829/task_2/C0_SOL_REMEDIATION.md` (`0dfe268d…`) is cited by the
   panel provenance. Rule 3 names three files.
4. **The tracked ledger is dirty in the root.** A **candidate** row
   (`nav-instruct-v1-candidate-v4-20260830T071509Z`, `frozen_baseline: false`, `sr 0.28`,
   `false_arrival: 1`) was appended to `evals/nav_instruct/results/ledger.jsonl` from the main repo at
   03:15 EDT. Harmless to `evaluate_hard_safety` (it is not frozen), but the append-only prefix rule
   and the W5 append both have to be reconciled against it.
5. **The hard-stop witness Sol asks for already exists at HEAD.** D-15's 105 zeroed translations are
   a real nonzero→zero case in the frozen five. Whether B32 removes it on v5 is a W4/W5 measurement,
   not an assumption.

---

## 6 · Integrator rulings on Part A (07:4x) — recorded, and one conflict raised

Part B accepted as written: **NOT LANDED**; Sol attributed for `reactive_gate_exercised`, the
per-episode counters and `passed = not survivors and not equivalent`; artifact + row selection not
adopted; `C0_SOL_REMEDIATION.md` noted as the fourth file.

| # | ruling | status |
|---|---|---|
| 1 | every comparison and the v5 baseline run use the committed budget policy — CLI flag **`--budget-policy scaled-path-v1`**, stated in the register; `a47b27bf…` is the code-axis v4 reference at HEAD | ✅ adopted (§1.2 answered) |
| 2 | the re-freeze appends **exactly ONE** baseline row — the **full matrix v5** (`--seed 20260804 --per-family 25 --refreeze-provenance TEXT`); minival digests reported in bridge/STATUS only, `--no-ledger` | ⚠️ adopted **with the conflict below** |
| 3 | the bridge carries the v4 story as drafted (A2 ×4 incl. A-00 as a LOSS citing NAV-QUALITY §1.4; a379bf4 ×1; `object_relative-D-15` flagged budget-dependent) **and** the v4→v5 band moves from W4's `bridge_v4_v5` | ✅ adopted |
| 4 | the v5 panel per A2 — witness rows chosen **by measurement** over the v5 full matrix, per-row coverage field asserted **by name** — regenerated LAST | ✅ adopted |
| 5 | the 14 artifacts as listed in §1.5 | ✅ adopted |
| 6 | `PINNED_FROZEN_FALSE_ARRIVAL` stays **0** | ⚠️ see the conflict |

### 6.1 CONFLICT: ruling 2 inverts 8/8 of the precedent, and rulings 2 + 6 may be jointly unsatisfiable

**Every `frozen_baseline` row ever appended to `evals/nav_instruct/results/ledger.jsonl` is a
MINIVAL.** Measured, not remembered:

| report_id | minival | n | budget_policy | false_arrival |
|---|---|---|---|---|
| `nav-instruct-v1-baseline-20260805T004302Z` | True | 25 | — | — |
| `nav-instruct-v1-baseline-20260805T010146Z` | True | 8 | — | — |
| `nav-instruct-v1-baseline-20260805T070505Z` | True | 2 | — | — |
| `nav-instruct-v1-baseline-20260805T070524Z` | True | 25 | — | — |
| `nav-instruct-v1-baseline-v2-20260808T001810Z` | True | 25 | — | 1 |
| `nav-instruct-v1-baseline-v3-20260809T045455Z` | True | 25 | — | 1 |
| `nav-instruct-v1-baseline-v3-20260809T161252Z` | True | 25 | `scaled-path-v1` | 0 |
| **`nav-instruct-v1-baseline-v4-20260811T070536Z`** (the current gate input) | **True** | **25** | `scaled-path-v1` | **0** |

The committed v4 **report** likewise carries `"minival": true`, `aggregate.n = 25`.

**Why this is not pedantry — four consequences of switching the gated row to 125 episodes:**

1. **`PINNED_FROZEN_FALSE_ARRIVAL = 0` becomes a bar on 5× the exposure.** `evaluate_hard_safety`
   (`ci_gate.py:2049-2063`) reads `collision_total` and `authority_histogram.false_arrival` off
   whichever row is last-and-frozen. 0 false arrivals over 25 episodes is measured; over 125 it is
   **not**. If the v5 matrix carries even one, rulings 2 and 6 are jointly unsatisfiable and the
   re-freeze reddens the hard gate. **Measuring this at HEAD on v4 now** (§6.2) so the answer exists
   before W4's patch lands.
2. **`bridge_v3_v4.py`'s falsifiable cell breaks.** `verify_recorded_baseline_cell()` checks the
   recorded old-code cell against **the committed frozen-baseline ledger row** on every pinned
   quantity. A 125-row successor is not comparable to a 25-row predecessor on `sr`/`spl`/`mean_dtg`,
   so `bridge_v4_v5` cannot reuse that shape without saying which row it means.
3. **`tests/test_nav_instruct_digest_recipe.py`'s `FROZEN_ROW` is a minival report.** Its five
   published digests and `EPISODE_DIGEST` are computed over 25 rows. Re-pinning them onto a 125-row
   report is fine, but it silently changes what "the frozen row" denotes for every future reader.
4. **Runtime.** A 125-row matrix at `scaled-path-v1` is ~5× the minival; the frozen row stops being
   reproducible inside a commit-tier budget.

**Not my call — flagging, not deciding.** Three ways out, in the order I would rank them:
**(a)** keep the frozen row a **minival v5** (precedent-preserving; the full matrix is measured and
reported in the bridge/STATUS with `--no-ledger`, which is what NAV-GEN-1 already does);
**(b)** append the full-matrix v5 row **and** re-pin `PINNED_FROZEN_FALSE_ARRIVAL` to whatever the
matrix honestly measures, declared as a widened bar — this is a **value change**, which the task_1
reading explicitly excludes;
**(c)** append the full-matrix row and hold the pin at 0 — only if §6.2 measures 0.

### 6.2 Measurement in flight: the v4 FULL MATRIX at HEAD

```
… --mode baseline --episode-version v4 --seed 20260804 --per-family 25 \
  --budget-policy scaled-path-v1 --no-ledger --out <scratch>/matrix-v4-head
```
Reports `collision_total`, `authority_histogram.false_arrival` and `n` over 125 rows at HEAD — i.e.
whether ruling 2 + ruling 6 can both hold on v4's geometry, before W4's band change moves it.
Result below when it lands.

---

## 7 · Amendment A3 (integrator, 07:5x) — executed

### 7.1 A3(1) — the recipe of record
**`--budget-policy scaled-path-v1 --max-steps 200 --seed 20260804`**, cited to
`research/20260824/nav-quality/RESULTS.md`'s reproduction section. Every command in this STATUS
states the policy explicitly on the CLI; `a47b27bf…` is the code-axis v4 reference at HEAD.

### 7.2 A3(2) — `tests/test_nav_instruct_digest_recipe.py`: the defect, and the fix · **DONE, 9 passed**

**Before — the precise diagnosis (it is not what it looked like).** The recipe *could already*
distinguish the two policies: `budget_policy` is a top-level report field and is **not** in
`REPORT_EXCLUSIONS` (`{report_id, elapsed_s, scene, navigator_flags, refreeze_provenance}`), so it
sits inside the hashed body; flipping only that label moves the digest under all four
drop-scene × compact variants. Under `scaled-path-v1` each episode row *also* carries its own scaled
`max_steps` (437, 454, 1200, …), so the two arms differ in the body twice over. The two arms could
never have hashed alike.

**The actual defect is IDENTITY, not discrimination:** the word `budget` appeared **0 times** in the
file. Nothing named which policy the five published numbers belong to, nothing asserted the frozen
row's policy, and no cell proved the digest is policy-sensitive. So (i) a reader of
`PATH_INDEPENDENT_REPORT_DIGEST_COMPACT = c172da37…` could not reproduce it from the documented
command — the CLI defaults to `fixed`, this row is `scaled-path-v1` — which is exactly what produced
two v4-at-HEAD digests tonight; and (ii) if a future refactor moved `budget_policy` into
`REPORT_EXCLUSIONS`, `fixed` and `scaled-path-v1` would silently collapse to one number and **nothing
would go red**.

**After — purely additive, `+78 / -0`, every published digest row byte-identical:**

* `FROZEN_ROW_BUDGET_POLICY = "scaled-path-v1"`, `FROZEN_ROW_MAX_STEPS = 200`, `FROZEN_ROW_SEED = 20260804`, with the two-digest incident written into the comment block;
* `test_the_published_digests_name_the_budget_policy_that_produced_them` — the frozen row must carry that policy/budget/seed, so the numbers are stamped with the recipe that produced them;
* `test_the_budget_policy_is_part_of_the_recipe_identity` — flipping only the label must move the digest in all four variants, and `budget_policy` must stay out of `REPORT_EXCLUSIONS`. This is the cell that goes red on the silent-collapse refactor;
* `test_the_per_episode_budgets_are_inside_the_hashed_body_too` — the frozen row's rows must carry **differing** per-episode budgets (proving it really is a scaled row), and flattening them to 200 must move the published compact digest.

| row | before | after |
|---|---|---|
| test cells | 6 | **9** |
| guarded result | 6 passed | **`9 passed in 0.33s`** (`pytest_guard.sh --label W5`) |
| published digest constants | 5 + `EPISODE_DIGEST` | **unchanged, byte-identical** (`git diff` shows 0 deletions) |
| `noqa` | 0 | **0** |
| `ruff check` | clean | **clean** |
| `ruff format --diff` hunks | 3 (pre-existing at HEAD) | **3 — zero new format debt** |

### 7.3 A3(3), (4), (5) — recorded
(3) the bridge records **both** v4-at-HEAD digests — `021b67ab…` under `fixed`, `a47b27bf…` under
`scaled-path-v1` — with the 7-row table of §1.3, and `object_relative-D-15`'s terminal is recorded as
**budget-dependent, not attributed to a commit**. (4) every wave-B run is `--no-ledger` except the
**one** v5 full-matrix re-freeze run; at commit the ledger diff must show exactly one appended row
whose digest equals the bridge's v5 digest, and this STATUS names that run. (5) the fourth Sol file
(`C0_SOL_REMEDIATION.md`) stays **unlanded**.

### 7.4 §6.2 RESULT — **the v4 full matrix at HEAD carries a FALSE ARRIVAL**

```
… --mode baseline --episode-version v4 --seed 20260804 --per-family 25 \
  --budget-policy scaled-path-v1 --no-ledger --out <scratch>/matrix-v4-head
```
→ `nav-instruct-v1-baseline-v4-20260830T112620Z.json`, 125 rows, 237.8 s.

| field | value |
|---|---|
| `collision_total` | **0** ✅ |
| **`authority_histogram.false_arrival`** | **1** ❌ |
| authority | `{agreement 99, authority_disagreement 24, false_arrival 1, tolerated_boundary 1}` |
| sr / spl / mean dtg | 0.208 / 0.141858 / 8.4027 |
| `episode_digest` (125 rows) | `e7c302ddf19a3964…` — **the same digest Sol pinned as `PANEL_MATRIX_DIGEST`**, an independent confirmation that the panel's substrate pin is correct |
| report digest | `a3cd12b7c6570627…` |

**The row:** `nav-region_goal-B-09-3ee156e4`, *"walk onto the sidewalk"* —
`reason: arrived_verified`, `mission_status: arrived`, `system_arrival True` / `scorer_arrival False`,
`detail: false_arrival:claim_without_predicate:dtg=4.7739m`, `L6_termination`, trace 101.
**It is NOT in the 25-row minival** — which is precisely why the frozen slice reads 0 and no gate has
ever seen it. A `claim_without_predicate` at **4.77 m** is the E7/v2 class of defect, alive inside
the frozen v4 *set* but outside the frozen *slice*.

**Consequences, stated plainly:**

1. **Rulings 2 and 6 are jointly unsatisfiable on v4's geometry.** Append the full-matrix row and hold
   `PINNED_FROZEN_FALSE_ARRIVAL = 0`, and `evaluate_hard_safety` reddens at the moment of commit:
   `nav_instruct frozen baseline false_arrival=1 > pin 0`. Whether v5 changes it is W4's measurement
   — `region_goal` is exactly the family B32 touches, so this row is a **candidate beneficiary** of
   W4 and should be read off W4's arm by name.
2. **A minival→matrix switch also moves the frozen `episode_digest`**, `4113607b…` → `e7c302dd…`,
   with **no episode definition changing**. That is a re-scoping of what the gate watches, not a
   re-freeze — and rule 2 (iii) says the frozen `episode_digest` never moves.
3. Every `frozen_baseline` row ever appended is a minival (§6.1, 8/8). The switch is a first.

**Recommendation (mine; the call is the integrator's):** keep the gated frozen row a **minival v5**,
and land the **full-matrix v5 run as a reported artifact** (`--no-ledger`) in the bridge/STATUS —
which preserves rulings 1, 3, 4, 5, 6 and the whole precedent, while putting the B-09 false arrival
on the record as a **named finding** rather than as a gate failure discovered at commit time. If the
matrix row is still wanted as the gated one, then ruling 6 has to move, and moving it is a value
change — which the task_1 reading excludes.

---

## 8 · Integrator decision on §7.4 (08:0x) — adopted, and the finding pinned

**The gated frozen row stays a MINIVAL v5.** Exactly one appended ledger row: minival,
`--budget-policy scaled-path-v1 --max-steps 200 --seed 20260804`. Rulings 1, 3, 4, 5, 6 hold
unchanged and the frozen `episode_digest` is not re-scoped. The **v5 full matrix** is run
`--no-ledger` and landed as a reported artifact in the bridge/STATUS with its digest, SR/SPL,
collisions, false arrivals and the per-family table. The digest-recipe fix is accepted as written.

### 8.1 The named finding, pinned for the v4→v5 comparison

`nav-region_goal-B-09-3ee156e4` — recorded in the bridge and on the board as the **E7/v2 class alive
in the frozen SET but outside the frozen SLICE**. W4 reports it under v5 by name. Its complete v4
state at HEAD, so the comparison needs no re-run:

| field | v4 @ HEAD (`c96ac34`, `scaled-path-v1`) |
|---|---|
| instruction | **"walk onto the sidewalk"** |
| family / tier | `region_goal` / B · notes `in_range_outside_frustum\|region_goal` |
| start pose | `(0.15, -0.075, -1.5708)` · `shortest_path_m` 10.5 · episode seed 1054955236 |
| goal | **polygon**, `anchor_entity: sidewalk`, `[[-8.0, 2.2], [8.0, 2.2], [8.0, 4.2], [-8.0, 4.2]]`, `band_m: null`, `radius_m: null` |
| `reason` / `mission_status` | `arrived_verified` / `arrived` |
| `system_arrival` / `scorer_arrival` | **True / False** |
| `detail` | `false_arrival:claim_without_predicate:dtg=4.7739m` |
| `attribution_layer` / `failure` | `L6_termination` / `false_arrival` |
| `distance_to_goal_m` | **4.77391552924085** |
| trace | **101 ticks of a 470-step budget** — `grid_track err=0.0 goal=0.4 route=2 status=planned\|clear` … then `semantic_stop_requested` (t=9.9 s) → `arrived_verified` (t=10.0 s) |
| `spl` / `success` / `oracle_success` | 0.0 / False / False |

**Reading of the mechanism.** The body is tracking cleanly (`status=planned|clear`, `err=0.0`) and
then *chooses* to stop at 4.77 m and the terminal contract *verifies* the claim — it is not a
navigation failure, it is an **arrival-authority** failure. The goal is a **polygon** with
`band_m: null`, i.e. exactly the region-vs-point mismatch named in `scrum/20260829/task_2` close-out
**item 3** ("a `known_poi` whose class is a region must be judged by the region band, not the 1.5 m
point radius"). **W4's B32 is the `near` band ∩ the support polygon on `object_near_goal_region` —
so this row sits squarely in B32's blast radius and is the single best test of it.** Three outcomes
are possible under v5 and all three are reportable: the claim is refused (the defect is fixed and
that is B32's headline), the row keeps its false arrival (B32 does not reach `region_goal` polygons —
a scoped negative worth knowing), or the episode id changes because B32 moved this definition (then
it is a v4→v5 bridge row, not a comparison).

**Not to be lost:** the minival v5 frozen row will read `false_arrival: 0` again, because B-09 is not
in the slice. That is exactly why it is a named finding rather than a gate row — the gate cannot see
it by construction, and `PINNED_FROZEN_FALSE_ARRIVAL = 0` stays honest only because the slice is
narrower than the set.

### 8.2 Ready to execute the moment W4's patch lands

Recipe of record, stated once (every run below uses it verbatim):
`--seed 20260804 --budget-policy scaled-path-v1 --max-steps 200`.

| # | run | ledger | purpose |
|---|---|---|---|
| 1 | `--minival --mode baseline --episode-version v5 --no-ledger --out <scratch>` | **no** | dry run: read the v5 minival digest, confirm collisions 0 / false arrivals 0 **before** anything is appended |
| 2 | `--mode baseline --episode-version v5 --per-family 25 --no-ledger --out <scratch>` | **no** | the **reported artifact**: digest, SR/SPL, collisions, false arrivals, per-family table, **and B-09 by name** |
| 3 | `--minival --mode baseline --episode-version v5 --refreeze-provenance "<text>"` | **YES — the one row** | the gated re-freeze. `git diff` on `ledger.jsonl` must show exactly `+1` line |
| 4 | `scripts/mutation_panel.py --out …` on v5, witness rows chosen from run 2's coverage scan (A2) | n/a | **LAST**, per E8 ordering and ruling 4 |

Pre-conditions I will assert before run 3: `EPISODE_SETS` contains `v5`;
`ARRIVAL_RULE_FOR_VERSION["v5"]` exists; runs 1 and 2 are green on collisions; the v4 artifacts are
untouched on disk. Post-conditions: exactly one appended frozen row whose report digest equals the
bridge's; `episode_digest` for v4 still `4113607b…`; `tests/test_nav_instruct_digest_recipe.py`
re-pinned to the v5 minival report **under the same recipe constants** (`FROZEN_ROW_BUDGET_POLICY`
etc. carry over unchanged — the v5 run uses the identical recipe, which is the point of §7.2).

**Timing:** minival ≈ 30 s, full matrix ≈ 4 min, panel campaign ≈ 19 min, freshness file ≈ 21 min —
so ~50 min of measurement after W4's patch, plus the A2 selection scan over the v5 matrix.

---

## 9 · Amendment A4 (integrator, 08:2x) — the matrix becomes a SECOND pinned artifact, by addition

**Ruling.** Alongside the minival gated row (unchanged pin, unchanged slice), add a second,
matrix-scoped pinned artifact = the v5 full-matrix `--no-ledger` result (runbook run 2), with its own
entry in `tests/test_nav_instruct_digest_recipe.py` and its own `PINNED_MATRIX_FALSE_ARRIVAL` in
`scripts/ci_gate.py`, read by `evaluate_hard_safety` **beside** the minival row. Value **0** if W4
clears B-09 (a tightening, allowed); otherwise **1** with the C0 DECLARED mechanism — provenance
names the row and the check, and a test asserts the declaration exists. Never silent.

### 9.1 The citation, verified — and B-09 reproduces six days and several commits later

`research/20260824/nav-quality/RESULTS.md` **§5.1** (line 695, *"The full 125-episode matrix has
never been run, and it contains a false arrival"*) is the same row, first dated **2026-08-24**:
`nav-region_goal-B-09-3ee156e4`, *"walk onto the sidewalk"*, `arrived_verified`, `system_arrival
True` / `scorer_arrival False`, and the register's own sentence — **"The robot declared verified
arrival on the sidewalk while standing 4.78 m outside it, and the independent K0 geometric predicate
says no."** §5.1 also already made the §6.1/§7.4 argument verbatim: *"the gate's false-arrival pin is
being computed on one-fifth of the available evidence, and the four-fifths nobody runs contains a
false arrival."*

**Two independent instruments, six days apart, agree on the row and disagree only on the aggregate:**

| | RESULTS.md §5.1 (08-24) | **W5 @ HEAD `c96ac34` (08-30)** |
|---|---|---|
| **false_arrival** | **1** | **1** |
| **the row** | `nav-region_goal-B-09-3ee156e4` | **the same** |
| dtg | 4.782 m | **4.7739 m** (Δ 8 mm) |
| `collision_total` | 0 | 0 |
| `tolerated_boundary` | 1 | 1 |
| refusal | 33 | 33 |
| sr | 0.20 | 0.208 |
| spl | 0.1348 | 0.141858 |
| authority_disagreement | 20 | **24** |
| runtime | 113.7 s | 237.8 s |

The false arrival is **stable across the intervening commits** (a379bf4 and wave A); the aggregate
moved, as §1.3's five rows predict. §5.1's *"connection worth recording"* stands and sharpens:
the one false arrival is a `region_goal` on *"walk onto the sidewalk"* and the metamorphic suite's
two standing xfails are a `region_goal` on *"go to the sidewalk"* — same family, same landmark, the
open **region-instance selection** question, now with a false arrival attached. That is B32's
question, which is why W4 is the right instrument.

### 9.2 A4 executes an item already on the owner's list

`scrum/20260824/task_4/CLAUDE_RESPONSE.md:79-83` — **PRE-MOUNT-CLOSE-1 item 7(b)**, verbatim:
*"the false-arrival pin covers the full matrix (114 s — it is affordable) **or names its
subsample**."* A4 takes the first branch; §8's minival decision keeps the second honest as well.
Item **7(a)** — *"the hard-safety nav row re-derives its pinned numbers from a LIVE run — or the
pin's provenance says 'ledger, not live' out loud"* — is what §9.4 below is about.

### 9.3 Design (proposed; the shape I will build unless corrected)

| piece | shape |
|---|---|
| artifact | `evals/nav_instruct/results/nav-instruct-v1-**matrix**-v5-<ts>.json` — baseline-row naming with `matrix` in it, **tracked**, produced by runbook run 2 (`--no-ledger`) |
| safety property | it carries **no** `frozen_baseline` key — that flag exists only on the *ledger row*, and run 2 writes none. So a tracked matrix report can never be mistaken for the gated frozen row by `_latest_frozen_baseline_row` |
| `ci_gate.py` | `MATRIX_REPORT_JSON` path constant + `PINNED_MATRIX_FALSE_ARRIVAL` beside `PINNED_FROZEN_FALSE_ARRIVAL` (`:407`); `evaluate_hard_safety` (`:2015-2105`) gains a matrix block asserting `collision_total == 0` and the false-arrival rule, printing its own `checks.append` line |
| digest recipe | `MATRIX_ROW`, its `report_digest(drop_aggregate_scene=True, compact=True)`, and its `episode_digest` (the 125-row set digest — **`e7c302dd…` on v4**, which is also Sol's `PANEL_MATRIX_DIGEST`, so one pin serves both) — under the same `FROZEN_ROW_BUDGET_POLICY` recipe constants added in §7.2 |
| declaration | if the pin is > 0, the artifact's `refreeze_provenance` must name the row **and** the check, in the C0 phrasing, with a re-arm condition; a test asserts it exists |
| ratchet | `tests/test_ci_gate.py` sentinel literal — **4 → 6** if the matrix manifest/report joins `DIGEST_SENTINELS` (v5 manifest + matrix report), not 4 → 5 |

**One strengthening I recommend, and would otherwise flag as a hole in the ruling.** A bare
`false_arrival <= 1` pin is satisfied by *any* single false arrival. If W4 fixes B-09 and a
**different** row starts claiming falsely, the count stays 1 and the gate stays green while the
declaration names an episode that is no longer the offender. So the declared mechanism should be
**row-identified, not count-identified**: the gate compares the *set* of false-arrival episode ids in
the artifact against the *set* named in the provenance, and reddens on any id not declared — the
same shape as C0's `_declared_disabled(provenance, name)`, which is keyed on the check's **name**,
not on a tally. `PINNED_MATRIX_FALSE_ARRIVAL` then becomes a belt-and-braces upper bound rather than
the whole test.

### 9.4 HOLE IN A4 AS WRITTEN — it reintroduces the E7 class, and the fix is cheap

`evaluate_hard_safety` has exactly two kinds of input today: **run ledgers** (append-only) and **one
derived artifact**, `mutation_panel.json`. The panel is re-derived **LIVE** on every commit-tier run,
and the gate's own docstring says why (lane E7, 2026-08-10): *"the committed payload was written at
19c9226 and a live run on the current tree contradicted it (`no_false_arrival` true → false) while
the gate kept printing `no_false_arrival=True` … A gate may read a stale artifact; it may not
**certify a safety property** from one."* Tonight's Part B is that same lesson firing again.

**A pinned matrix artifact read from disk is a derived artifact with no freshness check** — the third
of its kind and the second unguarded one. A tree could grow a second false arrival in the matrix and
the gate would keep printing the committed number indefinitely. Live re-derivation is not an option
at commit tier: **237.8 s measured** (§7.4), against the panel's ~4 s clean run that made E7's fix
affordable.

**Proposed resolution, matching what the repo already does for the panel:**

1. **Commit tier — read, and say so out loud.** Read the committed artifact for the pin, and add a
   `DIGEST_SENTINELS` entry over it so it cannot be edited silently. The gate detail line must read
   `matrix: committed artifact, NOT re-derived (238 s; nightly)` — which is literally
   PRE-MOUNT-CLOSE-1 item **7(a)**'s *"or the pin's provenance says 'ledger, not live' out loud"*
   applied to this input.
2. **Nightly tier — re-derive and compare.** A new `MATRIX_FRESHNESS_NODE_IDS` beside
   `MUTATION_FRESHNESS_NODE_IDS` (`ci_gate.py:196`), pointing at a new
   `tests/test_nav_instruct_matrix_freshness.py::test_committed_matrix_safety_fields_still_reproduce`
   that re-runs the matrix and compares `collision_total`, the false-arrival **id set** and the
   authority histogram. 238 s is affordable nightly; it is not affordable per commit.

Without (2) the artifact is evidence, not certification, and the gate must not word it as
certification. With (2) the matrix gets exactly the guarantee the panel has had since E7.

### 9.5 Artifact list: 14 → **19**

Additions to §1.5: **(15)** the tracked matrix report; **(16)** `ci_gate.py`
`PINNED_MATRIX_FALSE_ARRIVAL` + `MATRIX_REPORT_JSON` + the `evaluate_hard_safety` block (`:2015-2105`
— **no overlap** with the dirty root's hunks at `+69`, `+100`, `+498,224`, `+2612`, `+2699`,
`+3384…+3404`); **(17)** the matrix entry + declaration test in
`tests/test_nav_instruct_digest_recipe.py`; **(18)** `tests/test_nav_instruct_matrix_freshness.py`
(new, nightly — §9.4(2)); **(19)** `ci_gate.py` `MATRIX_FRESHNESS_NODE_IDS` (§9.4(2)).
Item **(8)** changes: `tests/test_ci_gate.py` sentinel literal **4 → 6**, not 4 → 5.

### 9.6 Refinements adopted + the integrator's two commit-tier checks — **both pre-verified**

Adopted: (1) the declared mechanism is **row-identified** (id-SET compared against the provenance's
named set; undeclared id ⇒ red; `PINNED_MATRIX_FALSE_ARRIVAL` demoted to an upper bound; a test
asserts both directions). (2) the **freshness split** (commit reads the pinned artifact + a
`DIGEST_SENTINELS` entry and prints `matrix: committed artifact, NOT re-derived (238 s; nightly)`;
nightly re-runs the matrix and compares collisions, the false-arrival id set and the authority
histogram, marked `slow`). Plus the integrator's two commit-tier additions, **(a)** live re-run of
the declared rows only and **(b)** artifact-vs-tree episode-digest identity.

**I measured both before agreeing they are cheap. They are, and (a)'s known hazard does not bite.**

**Check (b) — artifact cannot drift from the episode set it certifies.** `matrix_digest(
generate_episode_matrix(seed=20260804, per_family=25, version=…))` computed from the tree's episode
definitions equals the artifact's `episode_digest`:
`e7c302ddf19a39646aff77f01832be56b14fae6c7d4bd28e39cd5045c3c8b3f2` — **equal, in 0.001 s, no run.**
(The same value is Sol's `PANEL_MATRIX_DIGEST`, so one pin serves the panel substrate and the matrix
artifact.)

**Check (a) — the declared row re-run alone reproduces BIT-IDENTICALLY, in 1.30 s.** The hazard I
wanted ruled out first: Sol's `C0_SOL_REMEDIATION.md` records that `HeadlessCityWorld` *"seeds its
scan RNG once at construction and does not reset that stream per episode, so row-level noise depends
on preceding episode order"* — B-09 is the 34th row of a 125-episode campaign, so a solo re-run could
in principle land somewhere else and manufacture false reds. Measured, solo vs in-matrix, all twelve
`EpisodeScore` fields:

| field | in-matrix (125-ep campaign) | solo | same |
|---|---|---|---|
| `attribution_layer` | `L6_termination` | `L6_TERMINATION` | ✅ |
| `authority_category` | `false_arrival` | `FALSE_ARRIVAL` | ✅ |
| `detail` | `false_arrival:claim_without_predicate:dtg=4.7739m` | identical | ✅ |
| **`distance_to_goal_m`** | **4.77391552924085** | **4.77391552924085** | ✅ **to the last digit** |
| `failure` / `success` / `oracle_success` | `false_arrival` / False / False | identical | ✅ |
| `system_arrival` / `scorer_arrival` | True / False | identical | ✅ |
| `spl` / `oracle_sr_gap` / `time_to_goal_s` | 0.0 / 0.0 / None | identical | ✅ |

**`BIT-IDENTICAL score: True`**, wall clock **1.30 s** at `max_steps=470` (B-09's own scaled budget).
**Scope, stated honestly:** verified *for this row*. Sol's order-dependence was on reactive-gate
*call counts*, not on episode outcome, and this row's outcome and dtg are stable — but any future
declared row must be re-verified the same way before it is trusted at commit tier, because the
hazard is real for other quantities. Recorded as a build pre-condition.

**Commit-tier cost of the whole matrix block: ≈ 1.3 s** (declared rows) **+ 0.001 s** (digest
identity), against 238 s for the full re-derivation that stays nightly.

### 9.7 Where the wiring goes — verified, including one trap

`ci_gate.py` has two tier entry points: `run_commit_tier()` (`:2860`, a deferred `stages` tuple) and
`run_nightly_tier()` (`:2971`, a flat `results.append` list). **`MUTATION_FRESHNESS_NODE_IDS` is
called in exactly one place — `:2991`, inside `run_nightly_tier()`** — and it is *not* in the commit
stages. Commit-tier panel freshness is not that node-id gate at all: it is
`evaluate_hard_safety` → `_panel_safety_fields_live()` (`:1796-1801`, the ~4 s live clean run). So the
matrix mirrors it exactly:

| tier | where | what |
|---|---|---|
| **commit** | inside `evaluate_hard_safety` (`:2015-2105`) | read the pinned artifact; check (b) digest identity; check (a) live re-run of the declared id set; the row-identified false-arrival rule; `PINNED_MATRIX_FALSE_ARRIVAL` upper bound; print `matrix: committed artifact, NOT re-derived (238 s; nightly)` |
| **nightly** | `run_nightly_tier()`, a new `_pytest_gate("nav-matrix-freshness", tier, MATRIX_FRESHNESS_NODE_IDS, timeout=1200)` appended beside `:2991` | full live re-run; compare collisions, false-arrival id set, authority histogram |

**The trap, stated so nobody falls in it:** `_pytest_gate` takes `tier` only as a *label* for the
`GateResult` — it does not gate execution, and node-id selections run with **no `-m` filter**, so a
`slow`-marked test named there runs regardless of tier. Putting `MATRIX_FRESHNESS_NODE_IDS` into
`run_commit_tier()`'s `stages` tuple would therefore add **238 s to every commit** while looking
correct. It goes in `run_nightly_tier()` only. (I also recommend **`timeout=1200`**, not the 600 s
used for the panel: my matrix run took 237.8 s against the 08-24 register's 113.7 s, so 600 s has
little headroom on a loaded host.)

### 9.8 Tier-coverage rule — verified in shape; the count is the gate's to compute

`evaluate_tier_coverage` (`:2505`) compares three `--collect-only` runs and reddens on **orphans**
(in neither tier) **and** on **double-counting** (in both — "the tier boundary is not a partition").
The markers are `COMMIT_MARKERS = "not slow"` and `NIGHTLY_SLOW_MARKERS = "slow"` (`:167-168`) — a
**strict binary partition on one marker**, so for a new file:

* an **orphan is structurally impossible** — every test is either `slow` or not;
* **double-counting is equally impossible** for the same reason;
* the real and only risk is the inverse: **an unmarked slow test silently joining the commit tier**.
  Every cell in `tests/test_nav_instruct_matrix_freshness.py` that re-runs the matrix must carry
  `@pytest.mark.slow`; any pure/fixture cells stay unmarked and run at commit — exactly the layout
  `tests/test_mutation_panel_freshness.py` already uses (four `slow` cells, seven pure ones).

I did **not** run the three whole-tree collections to confirm a total of 11095 — that is
`evaluate_tier_coverage`'s own job, it takes minutes, and executors do not run `ci_gate.py --tier`
(standing constraint). What the gate asserts is the identity `collected = commit + nightly` with
both fault sets empty; the new file cannot break it, and the integrator's close-gate run prints the
actual number.

### 9.9 Build order when W4's patch lands
Runbook §8.2 unchanged (dry minival → matrix → the one gated minival row → panel last), with the A4
pieces built against the matrix artifact from run 2: artifact tracked → `DIGEST_SENTINELS` entry →
`PINNED_MATRIX_FALSE_ARRIVAL` + the row-identified rule + checks (a)/(b) in `evaluate_hard_safety` →
digest-recipe matrix entry + declaration test → `tests/test_nav_instruct_matrix_freshness.py`
(`slow`) → `MATRIX_FRESHNESS_NODE_IDS` in `run_nightly_tier()` → `test_ci_gate.py` sentinel literal
**4 → 6**. Artifact list **19** (§9.5).

---

## 10 · W4 landed — read-only verification, A5, and the A2/A4 build

**Not layered yet** (integrator: W4-F2 lands in ~1 h and moves eval-side files; one layering pass
after it). Everything below is either read-only against `~/.cache/parcel-0e/wb/w4` or built in my own
worktree at HEAD, where it does not depend on W4's patch textually.

### 10.1 W4 read-only — verified, not taken on trust

`EPISODE_SETS` → `['v1','v1a-scene-truth-only','v2','v3','v4','v5','v4s']`;
`ARRIVAL_RULE_FOR_VERSION['v5'] = hold-or-trace-end-v1` (v2's rule, unchanged — so a v4→v5 delta
cannot contain a rule change, the E8 discipline); `_CURRENT_FROZEN_EPISODE_SET` would compute **v5**,
confirming §3's prediction that any panel left on v4 reddens the moment W4 lands.

| quantity | value (from `results/bridge_v4_v5.json`) |
|---|---|
| minival episode digest | v4 `4113607b…` **unmoved** · v5 **`2822ebfd…`** |
| matrix episode digest | v4 `e7c302dd…` **unmoved** · v5 **`5ea2cd93…`** |
| minival moved | **1/25** — `nav-object_goal-C-10-68aa2ab8`, `shortest_path_m` 2.5 → 3.0, `band_unchanged: true` |
| matrix moved | **5/125**, all `object_goal`: A-02, B-06, **D-18**, C-10, C-14 |
| `episodes_embedding_a_band_m` | 45/125 — the figure behind rule 2 (iii)'s "episode-SET change ⇒ v5" |
| fields moved | `goal.support_polygon`, `goal.support_clearance_m`, and the derived `shortest_path_m` — `no_band_moved: true`, `id_mapping_is_total: true` |

**Episode ids are STABLE across v4→v5** (`id_mapping_is_total`), which retires the §3 worry that
Sol's four witness ids might not exist in v5. They exist — and **`nav-object_goal-D-18-19a95961`, one
of them, is one of the five rows whose goal definition moved.**

**B-09 under v5 — unmoved, and now root-caused.** `moved_by_correction_f: false`; dtg 4.7739 → 4.7739;
authority `false_arrival` → `false_arrival`. W4's own diagnosis: the navigator **committed
`sidewalk_south`** (polygon y ∈ [−3.75, −2.25]) and ended at (−0.0563, −2.5739) **genuinely inside
it**, while the answer key names the north `sidewalk` (y ∈ [2.2, 4.2]) — a **wrong-INSTANCE**
grounding defect, precisely the region-instance selection question `RESULTS.md` §5.1 flagged as *"the
first place to look"*. Correction (f) intersects a `near` **band** with a support surface and reaches
no **polygon** goal, so v4 and v5 are byte-identical here. The receipt already refuses it —
`receipt_says_arrived(…, region_id='sidewalk')` is **False** against a receipt carrying
`region_id='sidewalk_south'` — while the eval runner still derives `system_arrival` from a status
string. **That is W4-F2.** So A4's `PINNED_MATRIX_FALSE_ARRIVAL` starts at **1, declared**, and the
declaration's withdrawal condition is F2's landing.

### 10.2 Amendment A5 (binding for the bridge and the v5 provenance) — the three-axis decomposition

W4 moves **two more frozen-v4 rows on the CODE axis** vs clean HEAD:
`nav-region_goal-D-15-1b8b2361` `navigation_step_limit_inside_goal` / `authority_disagreement` →
**agreement** (system True, scorer True) — the +1 success and the **entire** SPL rise; and
`nav-object_relative-D-15-61f68ad6` `semantic_target_not_found` → `semantic_target_unreachable`
(reason only). Therefore:

| arm | SR | SPL |
|---|---|---|
| v4 × clean HEAD | 0.20 | 0.15326 |
| v4 × HEAD + W4 | **0.24** | **0.18509** |
| v5 × HEAD + W4 | **0.24** | **0.18509** |

**The v4→v5 band change moves SR and SPL by ZERO.** The rise is **W4's arrival authority on one
episode (D-15)** and must be written that way — **never** as "improved by the re-freeze". At matrix
scale the same holds: SR, `sr_frozen_rule`, collisions, the failure histogram and the authority
histogram are all bit-identical v4→v5, and SPL rises 0.161913 → 0.164864 only because four of the
five moved episodes route to a standable band point.

**The frozen v4 row's complete history at freeze time is 5 distinct episodes and 7 attributed
movements across 3 causes** — two rows moved twice:

| episode | A2 (≤ 08-24) | a379bf4 | W4 |
|---|---|---|---|
| `object_relative-A-00` (**LOSS**, NAV-QUALITY §1.4) | ✔ | | |
| `object_goal-B-05` | ✔ | | |
| `object_goal-D-15` | ✔ | | |
| `object_relative-D-15` | ✔ | | ✔ (reason only) |
| `region_goal-D-15` | | ✔ (`_inside_goal` suffix) | ✔ (**→ agreement**) |

**The loop-closing sentence, for the provenance:** *the same product change that makes D-15 agree is
what lets the declared `no_authority_disagreement` disable be withdrawn — by regeneration, never by
hand — and is also what blinds the gate mutant on the old five panel rows, which is why the v5 panel
rows are selected by measurement (A2) rather than inherited.*

Integrator reproduced `bridge_v4_v5 --run` byte-for-byte except `generated_at`.

### 10.3 A2 tooling — built and **validated against a known answer**

`<scratch>/w5/a2/scan_gate_coverage.py` (ruff clean). Two stages, because the counters are
order-sensitive (`HeadlessCityWorld` seeds its scan RNG once per runner):
**scan** one clean campaign over the whole matrix → candidates (`changed_nonzero > 0`, clean
authority `agreement`, zero collisions); **confirm** re-runs the chosen row set *in the order the
panel will use* — only confirm-stage numbers may be published.

**Validation (the point of building it before W4-F2):** the confirm stage on Sol's nine v4 ids
reproduces my live-at-HEAD panel per-episode counters **exactly** —
`object_relative-C-11` 31, `region_goal-A-00` 21, `region_goal-D-17` 17 (calls 110),
`object_goal-D-18` 14 (calls 185), and `region_goal-C-11` **0** (correctly excluded). The tool is
faithful to Sol's counter.

**A structural finding it surfaced immediately.** On v4 at HEAD the candidate filter yields **4 rows
and ZERO hard-stop witnesses** — because the only row with `translation_zeroed > 0` is
`region_goal-D-15` (105 of 200), and the `agreement` filter **excludes it**, since at HEAD it records
`authority_disagreement`. That is the mechanical reason behind Sol's caveat *"hard-stop coverage
remains unproven"*: **the selection rule itself excluded the one row that provides it.**
**Under v5 + W4, D-15 AGREES** — so it becomes eligible and would bring its hard-stop witness into
the panel with it. Whether it still hard-stops once it arrives is the first thing the v5 scan must
answer, and it is exactly the "designed nonzero→zero obstacle case" Sol asked for.

### 10.4 A4 code — written at HEAD, ruff clean, zero new debt

In `scripts/ci_gate.py` (all regions **clear** of both the dirty root's hunks and W4's `:323-333`
sentinel hunk): `MATRIX_FRESHNESS_NODE_IDS` (with the comment recording *why* it is nightly-only and
the `_pytest_gate`-label trap); `MATRIX_REPORT_JSON` + `PINNED_MATRIX_FALSE_ARRIVAL = 1` +
`DECLARED_FALSE_ARRIVAL_PHRASE`; the pure helpers `declared_false_arrival_ids()` and
`matrix_false_arrival_ids()` (which reads both `"false_arrival"` and the enum repr
`"AuthorityCategory.FALSE_ARRIVAL"`); `_matrix_declared_rows_live()`; and the matrix block in
`evaluate_hard_safety`, which enforces **collisions 0**, **undeclared id ⇒ red**, **stale
declaration ⇒ red**, **count > pin ⇒ red**, **check (b)** episode-set digest recomputed from the
tree, **check (a)** live re-run of declared rows, and prints
`— committed artifact, NOT re-derived (238 s; nightly)`. `rerun_declared` is the seam, mirroring
`reproduce_panel`. Ten self-tests appended to `tests/test_ci_gate.py`, including the two the ruling
asked for (undeclared ⇒ red; declared within bound ⇒ green) plus fail-closed parsing, the stale
declaration, the over-bound case, and missing-evidence.

**Hygiene:** `ruff check` clean on both files; `noqa` **9 → 9** in `ci_gate.py` (the two I first wrote
were replaced with specific exception tuples); `ruff format` hunks **47 → 47** — zero new debt.

### 10.5 COLLISION with W4 — `tests/test_nav_instruct_digest_recipe.py`

**W4 appends 29 lines to the same file I append 78 to, at the same anchor** (after
`test_the_in_report_episode_digest_is_unmoved`). W4 adds
`test_the_v5_refreeze_did_not_move_the_v4_row`; I add the recipe-identity constants and three cells.
The two are semantically independent and both purely additive, so they **merge by concatenation** —
but a blind `git apply` of both patches will conflict. I will re-apply my hunk on top of W4's file
when I layer. Flagged so nobody resolves it by dropping one.

### 10.6 A4 build result, and a NEW Part-B finding the panel verification could not see

**Built and green in my worktree at HEAD** (all through the guard, `--label W5`):

```
tests/test_nav_instruct_matrix_freshness.py  tests/test_ci_gate.py  tests/test_nav_instruct_digest_recipe.py
1 failed, 116 passed, 2 skipped
```

The 2 skipped are the two `slow` cells that require the v5 matrix artifact, which does not exist
until the re-freeze — `pytest.skip` by design, not a hole. The 1 failure is **not mine** (below).

**Tier partition verified by collection**, which is what A4 asked me to check:
`-m "not slow"` → **4 passed, 2 deselected**; `-m slow` → **2 collected, 4 deselected**. Six cells,
no orphan, no overlap. The two nightly cells are the ones that re-run the matrix; the four pure
direction-pinning cells run at commit.

`tests/test_nav_instruct_matrix_freshness.py` carries both freshness DIRECTIONS as pure fixtures, on
C0's F1 precedent: a **new** false-arrival id ⇒ *"diagnose the tree; do not regenerate over a live
regression"*; a **declared one that stopped occurring** ⇒ *"STALE IN THE GREEN DIRECTION … regenerate
and withdraw it"* — which is precisely the message **W4-F2's landing is expected to produce for
B-09**. The re-run reads its recipe **off the artifact** rather than hardcoding it, so a run under a
different budget policy is a different measurement, not a false red (§7.2).

**Hygiene across all four touched files:** `ruff check` clean; **0 `noqa`** added
(`ci_gate.py` 9 → 9); `ruff format` hunks `ci_gate.py` **47 → 47**, digest-recipe **3 → 3**,
matrix-freshness **0** — zero new debt anywhere.

#### The new finding: Sol's three files ALSO break a commit-tier hard-gate self-test

`tests/test_ci_gate.py::test_hard_safety_is_green_when_the_panel_reproduces` fails in my worktree,
and it is **Sol's files, not my changes** — my edits to that file add the matrix fixture and ten new
cells and touch neither `_panel_fields` nor this test, and the failure text mentions no matrix field.
The mechanism is exact and is readable straight off the assertion:

```
mutation panel is STALE: … on ['clean_checks', 'reactive_gate_coverage']
committed={… 'reactive_gate_exercised': False, 'reactive_gate_coverage': {'calls': -1, …}}
live     ={… four clean_checks, no coverage key …}
```

`reactive_gate_exercised` and `reactive_gate_coverage` **can only be produced by Sol's
`clean_safety_fields`**; HEAD's cannot emit them. The test's own fixture `_panel_fields`
(`tests/test_ci_gate.py`, **not** one of Sol's three files) still builds HEAD's four-key shape, so
committed ≠ live by construction. **Sol widened a function's output contract without updating its
other consumer.**

Why this matters beyond one red cell: Part B's verification ran
`tests/test_mutation_panel_freshness.py` only, because that is what rule 3(c) names. This is a
**fourth** file Sol's remediation needed (after `C0_SOL_REMEDIATION.md`), and it is a **commit-tier
hard-gate self-test** — so had the three files landed, `ci_gate --tier commit` would have carried a
red row from `test_ci_gate.py` as well as the two freshness nodes. Part B's **NOT LANDED** verdict is
unchanged and now rests on three independent failures rather than two.

**Consequence for the v5 panel build (Part B on v5):** when Sol's *design* is re-implemented on top of
HEAD's `mutation_panel.py`, `tests/test_ci_gate.py::_panel_fields` must move in the same commit as
`clean_safety_fields`. Added to the §9.9 build order as a fifth artifact touched by the panel work.

---

## 11 · v5 execution — **PREVIEW** in the W5 worktree (integrator's sequencing rule)

Everything in this section is a **PREVIEW @ w5 worktree = HEAD `c96ac34` + W4's patch (incl. F1–F3) +
W5's code**. The committed numbers come from the merged gate worktree
(HEAD + W1 + W2 + W3 + W4-incl-F4 + W5), which is a different tree, so these are
reproducible evidence for the code — not the numbers that get committed.
**The ledger row was NOT appended** (`ledger.jsonl` still 24 lines, `git status` clean); step 3 ran
with `--no-ledger`. `refreeze_provenance` is in `REPORT_EXCLUSIONS`, so the published report digest
is **provenance-independent** — proven by a cell — which is why a preview digest can be pinned before
the prose is final.

### 11.1 Layering W4 — one conflict, exactly as predicted

`git apply --check` on W4's full diff → **fail, one file only**:
`error: patch failed: tests/test_nav_instruct_digest_recipe.py:151`. Everything else applies clean
(`--exclude=tests/test_nav_instruct_digest_recipe.py` → rc 0, 20 files). The collision is the one
flagged in §10.5: W4 appends 29 lines and W5 appends 78 at the same anchor. **Resolved by
concatenation, nothing dropped** — my recipe-identity constants and three cells, then W4's
`test_the_v5_refreeze_did_not_move_the_v4_row`; the merged file has **10 cells** and is ruff-clean.
Then 31 untracked files copied (v5 episodes + manifest, `bridge_v4_v5.py`/`.json`,
`arrival_receipt.py`, its two test files) plus `research/20260829/nav-interrupt-1/{harness,run}.py`.
`w4-b32-*` tier artifacts and scratch ignored as instructed.

### 11.2 The four digests (preview)

| artifact | report digest — `report_digest(drop_aggregate_scene=True, compact=True)` | episode digest |
|---|---|---|
| **v5 MINIVAL** — the gated row's report `nav-instruct-v1-baseline-v5-20260830T122614Z.json` | **`53eec205950ceb1749ae33d226d5a7f54f26cc486089cdc2dcec556c3397b989`** | **`2822ebfdc0ebbb179d92b25775e5e6e17bf9e28135756c8b7100d7501aa30301`** |
| **v5 MATRIX** — the A4 artifact `nav-instruct-v1-matrix-v5-20260830T122035Z.json` | **`041d9bdd82e56ff76c887f59821d4cd9b7caa4b5c3b64c63505ab7cf3449f1d0`** | **`5ea2cd93d365dbf7ad2ca5e91a894baea37e9e37d2ecdcabb9a4a9c0e190a4f3`** |

Matrix artifact `sha256` (the `DIGEST_SENTINELS` entry): `05f8a824ddb685b29db3b14277e72591d7c3b3ba63ff0fdbb813f65a956bc40e`.
Also published for the minival: path-independent `e070a8a7…`, path-dependent `2b01d699…`,
episodes sorted-by-id `67670451…`, episodes report-order compact `a6d85016…`.

### 11.3 The numbers, and A5 confirmed by measurement

| arm | SR | SPL | collisions | false_arrival |
|---|---|---|---|---|
| v5 **minival** (gated row) | **0.24** | **0.18509069363202812** | **0** | **0** |
| v5 **matrix** (125 rows) | **0.232** | **0.1648644951026271** | **0** | **0** |

Minival authority `{agreement 21, authority_disagreement 4}`; matrix authority
`{agreement 103, authority_disagreement 21, false_arrival 0, tolerated_boundary 1}`.
**A5 holds exactly as written:** v4 × this tree = SR 0.24 / SPL 0.185091 and v5 × this tree = SR 0.24
/ SPL 0.185091 — **the band change moves SR and SPL by zero**; the rise from clean HEAD's 0.20 /
0.153259 is **W4's arrival authority on `nav-region_goal-D-15`**, one episode, and is written that way
in the provenance. The integrator's independent matrix runs agree to the digit
(v5 SR 0.232 / SPL 0.164864, collisions 0, false-arrival rows `[]`).

**B-09 is fixed:** the matrix false-arrival total is **0**, so
`PINNED_MATRIX_FALSE_ARRIVAL = 0` ships with an **empty declared set** — a tightening on a measured
result. The row-identified declaration machinery ships anyway and is tested both ways.

### 11.4 The ledger line that will be appended on the gate tree

Not appended here. Under `--preview` the runner writes the report and prints `ledger: not appended`;
without it, exactly one line is added, shaped like every prior frozen row and carrying
`frozen_baseline: true`, `baseline_version: "v5"`, `budget_policy: "scaled-path-v1"`,
`max_steps: 200`, `seed: 20260804`, `minival: true`, `n: 25`, `sr: 0.24`,
`spl: 0.18509069363202812`, `collision_total: 0`,
`authority_histogram: {agreement: 21, authority_disagreement: 4, false_arrival: 0, …}`,
`episode_digest: 2822ebfd…`, plus the 3,289-character `refreeze_provenance` carrying A5's full
history. Acceptance at commit: `git diff` on `ledger.jsonl` shows **exactly `+1` line**, the
append-only prefix byte-identical.

### 11.5 The v5 panel — **PASSED**, rows chosen by measurement (A2)

`episode_set_version: v5`, `passed: True`, `survivors: []`, `equivalent_mutants: []`, **7/7 killed**,
clean authority **`{agreement: 9}`**, collisions 0, and all five clean checks green.

| episode | calls | requested_nonzero | **changed_nonzero** | translation_zeroed | role |
|---|---|---|---|---|---|
| `nav-region_goal-A-00-1c735162` | 101 | 98 | **21** | 0 | historical |
| `nav-region_goal-D-15-1b8b2361` | 68 | 62 | 0 | 0 | historical |
| `nav-object_goal-A-00-4caa923b` | 51 | 14 | 0 | 0 | historical |
| `nav-object_relative-A-00-3efbba45` | 62 | 0 | 0 | 0 | historical |
| `nav-follow_owner-D-15-74a535dd` | 0 | 0 | 0 | 0 | historical |
| **`nav-region_goal-C-11-25d4e602`** | 200 | 151 | **96** | 0 | **WITNESS (A2)** |
| **`nav-object_relative-C-11-3bf174e9`** | 165 | 106 | **31** | 0 | **WITNESS (A2)** |
| **`nav-region_goal-B-09-3ee156e4`** | 101 | 81 | **20** | 0 | **WITNESS (A2)** |
| **`nav-region_goal-D-17-448696db`** | 110 | 94 | **17** | 0 | **WITNESS (A2)** |

Selection rule, applied mechanically and reproducibly: from the pinned 125-row v5 matrix scan, every
row with clean authority `agreement`, zero collisions and `changed_nonzero > 0` that is not already
historical, ranked by `changed_nonzero`, **top four**; then **confirmed in panel order** (the counts
above are the confirm-stage numbers, which is the only stage whose numbers may be published — the
scan's C-11 read 82 and the panel's reads 96, because the world's scan RNG is seeded once per runner
and not reset per episode). The next two candidates, not taken, were `object_goal-D-18` (14) and
`object_goal-C-14` (10).

**Sol's check is load-bearing, and the panel proves it:** `reactive_gate_disabled` is killed through
**`reactive_gate_exercised` and nothing else** (`checks_reddened: ['reactive_gate_exercised']`).
Strip that one check and the mutant reddens **zero** checks — a **SURVIVOR**. Adopting Sol's design
is what keeps the panel from going blind on v5, and it is attributed in the provenance.

**The declared disable is WITHDRAWN, by regeneration:** clean authority is `{agreement: 9}` with no
disagreement, `no_authority_disagreement` is green, and `inverted_relation` now kills **through** it —
the channel is live again for every mutant. C0's condition ("re-armed when D-15 agrees again") was met
by **a product change** (W4's arrival authority), never by weakening the check, and C0's sentences are
kept **verbatim** in the provenance (HEAD's 5092-char lineage is still a strict prefix; now 8075).

**Honest negative, and it corrects my own §10.3 prediction.** I predicted D-15 would bring its
hard-stop witness into the panel once it agreed. **Measurement says no:** `translation_zeroed` is
**0 on every one of the 125 v5 matrix rows**, and D-15's v4-era 105/200 stopped ticks are gone
*precisely because* it now arrives instead of grinding into the gate. Every observed intervention is
**slowing**; **hard-stop coverage remains unproven** and is stated in the artifact's provenance rather
than claimed. A designed nonzero→zero obstacle case is still owed.

### 11.6 Code landed in the worktree, and the suites

| file | change |
|---|---|
| `scripts/ci_gate.py` | +277 — `MATRIX_FRESHNESS_NODE_IDS` (nightly-only, with the `_pytest_gate`-label trap documented), `MATRIX_REPORT_JSON`, `PINNED_MATRIX_FALSE_ARRIVAL = 0`, `DECLARED_FALSE_ARRIVAL_PHRASE`, `declared_false_arrival_ids()`, `matrix_false_arrival_ids()`, `_matrix_episode_digest_from_tree()`, `_matrix_declared_rows_live()`, the `evaluate_hard_safety` matrix block, the matrix `DIGEST_SENTINELS` entry, and the nightly `nav-matrix-freshness` gate |
| `scripts/mutation_panel.py` | +263 — v5 substrate + digest, `PANEL_EPISODE_IDS` re-selected by measurement, `PANEL_INTERVENTION_WITNESSES`, A2's per-episode field in `clean_safety_fields`, provenance rewritten (C0 verbatim + Sol attributed + withdrawal + the hard-stop negative) |
| `tests/test_ci_gate.py` | +327 — 16 new cells; `_panel_fields` and `_panel_artifact` moved with the widened `clean_safety_fields` contract; sentinel literal **4 → 6** with the dated E8-idiom comment |
| `tests/test_nav_instruct_digest_recipe.py` | +215 — the recipe-identity work, the v5 minival + matrix entries, and W4's v4-immutability cell merged in |
| `tests/test_mutation_panel_freshness.py` | +67 — A2's **per-row, by-name** witness assertion |
| `evals/nav_instruct/README.md` | +98 — the two-artifact results section, the recipe of record, why the gated row stays a minival, why the matrix is pinned |
| `tests/test_nav_instruct_matrix_freshness.py` | **new**, 202 lines — nightly re-run + both freshness directions as pure commit-tier cells |

`tests/test_ci_gate.py` alone: **109 passed**. Tier partition re-verified: `-m "not slow"` → 4 passed
/ 2 deselected, `-m slow` → 2 collected / 4 deselected.

**Hygiene, stated precisely rather than rounded.** `ruff check` is **clean on every file**, so the
gated ruff ratchet (`scripts/ci_ruff_baseline.json`, a fingerprint baseline) gains **no entry** —
that is the check `ci_gate.evaluate_ruff` actually runs. **0 `noqa` added** anywhere
(`ci_gate.py` 9 → 9, `mutation_panel.py` 1 → 1, every test file 0 → 0). `ruff format` is **not**
gated in this repo and HEAD is already far from it (`ci_gate.py` alone: 47 hunks); my files move it
`ci_gate.py` 47 → 47, `mutation_panel.py` 3 → 6, `test_ci_gate.py` 19 → 21,
`test_mutation_panel_freshness.py` 4 → 5, `test_nav_instruct_digest_recipe.py` 3 → 5, new
matrix-freshness file 0. Some of those added hunks sit inside **Sol's** adopted blocks and **W4's**
appended block, which I left byte-identical to what they wrote rather than reformatting another
card's code; the rest are mine and match the surrounding file's existing style.

### 11.7 The gate-tree pass is one command

`<scratch>/w5/w5_refreeze_run.sh <worktree> [--preview]` (128 lines) does the whole runbook:
preflight (v5 registered, arrival rule unchanged, ledger clean — it **refuses** to run on a dirty
ledger) → minival dry run with a collisions/false-arrival assertion → matrix → the one gated row →
re-pins `MATRIX_REPORT_JSON`, the sentinel sha and all four digest constants **from the artifacts it
just produced** → panel LAST → the four suites through the guard. Recipe of record is baked in;
`--preview` is the only difference between this pass and the committed one.
Companion tool: `<scratch>/w5/a2/scan_gate_coverage.py` (scan → confirm), validated on v4 against
known-answer numbers before it was trusted on v5.

### 11.8 The panel's own guard caught a blind spot W4 opened — and it is closed

The first four-suite run read **2 failed, 139 passed (24 m 22 s)**, both failures the same assertion
in `_assert_panel_payload_is_current_and_sensitive`:

> `AssertionError: no_false_arrival is green on the clean run but no mutant exercises it`

**This is not a fixture problem. It is a real evidence gap, and the freshness file exists to find
exactly it.** On v4, `doubled_envelope` and `phantom_view_consistent` reddened `no_false_arrival`;
on v5 **no mutant does**. A check that is green but that nothing can turn red certifies nothing —
the v2 rot, in a new place.

**Root-caused by controlled experiment, not inference.** Two axes could explain it: the new row
selection (data) or W4's ArrivalReceipt (code). I re-ran the three candidate mutants on the **OLD
five rows** — the exact v4 selection — under v5 code:

| mutant, on the old five rows | reddens `no_false_arrival`? |
|---|---|
| `doubled_envelope` | **no** |
| `phantom_view_consistent` | **no** |
| `arrival_radius_x2` | **no** |

So it is **the code axis**: `receipt_says_arrived` is now the single consumer predicate for a
terminal navigation fact, and none of the seven mutants can make the system claim an arrival through
it. W4's receipt is **safety-critical code that no mutant touches** — the panel had gone blind on the
newest arrival authority in the tree.

**Closed with an eighth mutant, additive in card VS-6's documented style:**
`arrival_receipt_bypassed` keeps `receipt.arrived` and drops `receipt.is_for(...)`, so a receipt cut
for another place, another goal or an earlier leg is accepted for this one — **precisely the B-09
defect F2 fixed** (`sidewalk_south` committed and stood in, `sidewalk` claimed), seeded by
monkeypatch and never as a source edit. Measured:

| | result |
|---|---|
| verdict | **killed** |
| checks reddened | **`no_false_arrival`**, `failure_histogram_identical` |
| clean authority | `{agreement: 9}` |
| mutant authority | **`{agreement: 8, false_arrival: 1}`** — one manufactured false arrival, the B-09 class |

`no_false_arrival` is a live kill channel again. The seven pre-existing mutants keep their verdicts
and their order; the artifact gains one row at the end. The reasoning, the controlled experiment and
the result are written into the artifact's own `episode_set_provenance`.

**Scope note, honestly:** adding a mutant is a panel-design change and the card did not ask for one.
I judged it in scope because the alternative is shipping a re-freeze whose panel cannot redden on
the arrival authority the same wave introduced, and because the E3/LIVE-COLLISION rule's principle —
a new check ships in the commit that ships its panel — is satisfied by doing both here. Drop it and
the two freshness nodes stay red; that is the trade, stated rather than hidden.

---

## 12 · FINAL PASS on the merged gate worktree — `~/.cache/parcel-0e/wb/gate`

HEAD `c96ac34` + W1 + W2 + W3 + W4 (incl. F4/F5) + W6 + **W5**. `parcel_robot.__file__` resolves
inside the gate worktree. Work done there, not in my own.

### 12.1 Transfer — my delta only, verified byte-for-byte

All six of my shared files were **byte-identical to W4's versions** in the gate tree before I
touched it, so `diff W4 → W5` per file is exactly my delta. `git apply --check` → **rc 0**; applied;
plus `tests/test_nav_instruct_matrix_freshness.py` copied. Then verified: **all seven files
`cmp`-identical to the versions proven in my own worktree.** One follow-up: `ruff` reported `EXE001`
because the patch format does not carry the mode bit and `mutation_panel.py` gained a shebang-executable
mode in Sol's adopted diff — `chmod 755`, and ruff is clean. **No `src/` file was edited by W5**
(the 17 `src/` files in the gate diff are W1/W3/W4's), and **T1's `research/20260829/nav-interrupt-1/`
was not touched** — its `m1-merged-*` outputs are untouched and theirs.

### 12.2 The four digests — **identical to the preview**, on a different tree

| artifact | report digest | episode digest |
|---|---|---|
| **v5 MINIVAL** `nav-instruct-v1-baseline-v5-20260830T135548Z.json` | **`53eec205950ceb1749ae33d226d5a7f54f26cc486089cdc2dcec556c3397b989`** | **`2822ebfdc0ebbb179d92b25775e5e6e17bf9e28135756c8b7100d7501aa30301`** |
| **v5 MATRIX** `nav-instruct-v1-matrix-v5-20260830T135527Z.json` | **`041d9bdd82e56ff76c887f59821d4cd9b7caa4b5c3b64c63505ab7cf3449f1d0`** | **`5ea2cd93d365dbf7ad2ca5e91a894baea37e9e37d2ecdcabb9a4a9c0e190a4f3`** |

**All four match §11.2 exactly** — W1+W2+W3+W6 move the nav evidence by **zero**, which is worth
stating as a result rather than an assumption. Matrix `sha256` (the `DIGEST_SENTINELS` entry) is
`5979b8e895ceccce2d70134a42e66ab756b629db9f4ebcee3f0cb801c93261a7`; it differs from the preview's
because `report_id`, `elapsed_s` and `scene` are file bytes even though the digest recipe excludes
them — which is exactly why the runbook re-pins the sentinel from the artifact it just produced.

### 12.3 The ledger `+1`

`git diff --numstat` on `evals/nav_instruct/results/ledger.jsonl` → **`1  0`** — one line added,
none removed. The first 24 lines are **byte-identical** to HEAD (`cmp` clean), so the append-only
prefix rule holds. The appended row:

`report_id nav-instruct-v1-baseline-v5-20260830T135548Z` · `baseline_version v5` ·
`arrival_rule hold-or-trace-end-v1` · **`frozen_baseline true`** · `minival true` · `n 25` ·
`budget_policy scaled-path-v1` · `max_steps 200` · `seed 20260804` · **`sr 0.24`** ·
**`spl 0.18509069363202812`** · `sr_frozen_rule 0.12` · **`collision_total 0`** ·
`authority_histogram {agreement 21, authority_disagreement 4, false_arrival 0, tolerated_boundary 0}` ·
`episode_digest 2822ebfd…` · `refreeze_provenance` **3,288 chars** carrying A5's full history
(A2 ×4 incl. `object_relative-A-00` as a LOSS with the NAV-QUALITY §1.4 citation, a379bf4 ×1, W4 ×2,
SR 0.24 = W4's D-15, and "the band change moves SR and SPL by zero").

### 12.4 The v5 panel on the gate tree — PASSED, 8/8

`episode_set_version v5` · `passed True` · `survivors []` · `equivalent_mutants []` · **8 mutants,
8 killed** · clean authority **`{agreement: 9}`** · collisions 0 · all five clean checks green ·
`coverage_matrix_digest 5ea2cd93…`. Aggregate coverage `{calls 858, requested_nonzero 606,
changed_nonzero 185, translation_zeroed 0}` — **identical to the preview, row for row:**

| episode | calls | req_nz | **chg_nz** | zeroed | role |
|---|---|---|---|---|---|
| `nav-region_goal-A-00-1c735162` | 101 | 98 | **21** | 0 | historical |
| `nav-region_goal-D-15-1b8b2361` | 68 | 62 | 0 | 0 | historical |
| `nav-object_goal-A-00-4caa923b` | 51 | 14 | 0 | 0 | historical |
| `nav-object_relative-A-00-3efbba45` | 62 | 0 | 0 | 0 | historical |
| `nav-follow_owner-D-15-74a535dd` | 0 | 0 | 0 | 0 | historical |
| **`nav-region_goal-C-11-25d4e602`** | 200 | 151 | **96** | 0 | **WITNESS (A2)** |
| **`nav-object_relative-C-11-3bf174e9`** | 165 | 106 | **31** | 0 | **WITNESS (A2)** |
| **`nav-region_goal-B-09-3ee156e4`** | 101 | 81 | **20** | 0 | **WITNESS (A2)** |
| **`nav-region_goal-D-17-448696db`** | 110 | 94 | **17** | 0 | **WITNESS (A2)** |

Mutant verdicts: `arrival_radius_x2`, `reactive_gate_disabled` (**through `reactive_gate_exercised`
alone** — Sol's check is what keeps it from surviving), `pose_offset_0m5`, `inverted_relation`
(**through `no_authority_disagreement`** — the withdrawn declaration's channel, live again),
`dropped_detections`, `doubled_envelope`, `phantom_view_consistent`, and
**`arrival_receipt_bypassed`** (**through `no_false_arrival`** — §11.8's eighth mutant, restoring the
channel W4's receipt had made unexercisable). No source change was needed for any of it.

### 12.5 Proof

| suite | result |
|---|---|
| `test_mutation_panel_freshness.py` + `test_ci_gate.py` + `test_nav_instruct_digest_recipe.py` + `test_nav_instruct_matrix_freshness.py` | **141 passed, 0 failed** (26 m 44 s, through the guard, `--label W5`) |
| `test_nav_instruct_receipt_authority.py` + `test_arrival_receipt.py` | **14 passed** |
| M1's one expected red — `test_ci_gate.py:327` sentinel literal | **CLOSED**: 4 → 6, green |
| `ruff check` on all six W5 files | **clean** |
| tier partition of the new file | `-m "not slow"` **4/6**, `-m slow` **2/6** — no orphan, no overlap |

### 12.6 Diff stat — W5 on top of M1

```
 evals/nav_instruct/README.md                   |   98 +-
 evals/nav_instruct/results/ledger.jsonl        |    1 +
 evals/nav_instruct/results/mutation_panel.json | 1302 ++++++++++++++++++++--
 scripts/ci_gate.py                             |  277 ++++-
 scripts/mutation_panel.py                      |  326 +++++-
 tests/test_ci_gate.py                          |  327 +++++-
 tests/test_mutation_panel_freshness.py         |   67 +-
 tests/test_nav_instruct_digest_recipe.py       |  215 ++++
 8 files changed, 2456 insertions(+), 157 deletions(-)
```
plus three new untracked paths of mine: `tests/test_nav_instruct_matrix_freshness.py`,
`results/nav-instruct-v1-baseline-v5-20260830T135548Z.json`,
`results/nav-instruct-v1-matrix-v5-20260830T135527Z.json`.
Whole gate tree vs HEAD: **48 files, +5686 / −431**.

---

## 13 · W5-F1 — the eighth mutant conditioned, and the DEC-0 reds closed

Worked on the gate worktree after the integrator's "gate reported". The close gate read
**hard-safety PASS** (v5 baseline `…135548Z`, panel fresh), release-parity PASS, tier-coverage PASS
(11261 = 11172 + 89), owner-store PASS, default-suite **11,077 passed / 8 failed**. Five of the eight
are other cards'. **Five were mine** — three panel rows plus two DEC-0 ratchet rows — and all five are
closed below.

### 13.1 Condition (a) — patch the PRODUCT predicate at its definition · **FAILED as built, now FIXED**

Read and confirmed the finding rather than defended the code: the mutant patched
`runner_module.receipt_says_arrived`, i.e. **the eval runner's own imported binding**. Every consumer
binds the name directly at import (`from … import receipt_says_arrived`), so that mutation exercised
**one call site of four** and proved nothing about the product.

Moved to the **definition site**: `ArrivalReceipt.is_for` — the identity half of
`receipt_says_arrived` (`receipt is not None and receipt.arrived and receipt.is_for(...)`), resolved
on the instance at call time. `receipt.arrived` is deliberately left intact: what is seeded is the
loss of **identity**, not of the arrival fact. Proven against a real receipt for `sidewalk_south`
read by a leg that asked for `sidewalk`:

| consumer | clean | under the mutant | restored |
|---|---|---|---|
| `arrival_receipt.receipt_says_arrived` (definition) | False | **True** | False |
| `evals/nav_instruct/runner.py` | False | **True** | False |
| `parcel_robot/brain/runtime_adapter.py` | False | **True** | False |
| `parcel_robot/runtime.py` | False | **True** | False |

**All four flip; the old patch flipped only the runner.** The kill survives the move unchanged:
verdict `killed`, `checks_reddened ['no_false_arrival', 'failure_histogram_identical']`,
mutant authority `{agreement 8, false_arrival 1}`.

### 13.2 Condition (b) — killed on the row where the receipt refuses BY IDENTITY · **VERIFIED**

The false arrival is **`nav-region_goal-B-09-3ee156e4`**, and it is the only row that moves:
`failure planning_error → false_arrival`, at an **unchanged pose** — final `(-0.0563, -2.5739)`,
dtg **4.7739 in both arms**. Only the *claim* moves, which is exactly `wrong_instance`: the navigator
commits `sidewalk_south` and stands genuinely inside it while the leg asked for the north `sidewalk`.
The controlled experiment ("code axis, not row selection") and the row are both named in the panel's
`episode_set_provenance`.

### 13.3 Condition (c) — the floor stays a floor · **VERIFIED, unchanged**

`_MINIMUM_KILLED = 6` at HEAD and now — I never touched it. The assertion is
`len(killed) == len(payload["mutants"]) >= _MINIMUM_KILLED` → **8 == 8 >= 6**: the count grows, the
floor does not chase it. The new mutant's `checks_reddened` is recorded exactly like the others
(`['no_false_arrival', 'failure_histogram_identical']`), and the freshness assertion reads that
**recorded list**, not the mutant's name — so a later selection that drops B-09 makes the mutant stop
producing a false arrival, its `checks_reddened` loses the channel, and
`"no_false_arrival is green on the clean run but no mutant exercises it"` **reddens** instead of
passing on the name. Stated in the provenance too.

### 13.4 Condition (d) + the hard-stop sentence · **WRITTEN INTO THE PROVENANCE**

The provenance now says plainly that **`phantom_view_consistent` no longer reddens `no_false_arrival`
BECAUSE the receipt refuses phantom arrivals — a product improvement, not a weakened panel** — and
lists the channels it is still killed through (`success_set_identical`,
`mean_dtg_within_tolerance`, `failure_histogram_identical`, `final_poses_within_tolerance`).

The hard-stop sentence now names **where the hard stop IS certified**, so the fifth check reads as
certifying the gate's **SLOWING** branch only: it alters a non-zero translating request **185** times,
carried by the four witness rows at **96, 31, 20 and 17**; `translation_zeroed` is **0** on all 125
v5 rows, so within this instrument hard-stop coverage is unproven — and the hard stop is certified
elsewhere by name: `parcel_robot/core/hard_stop.py` through **`tests/test_core_hard_stop.py`**
(`finalize_command`, `ZERO_COMMAND`, `InterventionSeverity`, `ResetObligation`), the discontinuity
latch through **`tests/test_a3_discontinuity_latch.py`**, and the local stop path through
**`tests/test_a6_stop_local.py`**. C0's lineage is still a **verbatim prefix** (5,092 chars of the
11,615).

### 13.5 The three panel test reds — read first, then closed

| test | what its assertion actually required | how it is closed |
|---|---|---|
| `test_the_panel_seeds_exactly_the_defects_its_cards_declare` | `set(MUTATIONS) == PLAN_SIX_DEFECTS \| set(ADDED_DEFECTS)` — a mutant may not exist undeclared | **declared**: `"arrival_receipt_bypassed": "W5"` added to `ADDED_DEFECTS` with the reason. Test not relaxed |
| `test_phantom_mutant_is_registered_last` | `tuple(MUTATIONS) == PRE_EXISTING + (PHANTOM,)` | the rule's **intent is append-only** — `mutation_panel.py` says so at the registration site: *"a new defect adds a row at the end and moves no existing verdict."* Inserting mine **before** phantom would have moved phantom's index, which is what the rule exists to prevent. Renamed to **`test_mutants_are_registered_append_only`** against `EXPECTED_MUTANT_ORDER = PRE_EXISTING + ADDED_MUTANTS_IN_ORDER`, with the dated reason |
| `test_committed_panel_gained_exactly_one_row_and_kills_through_false_arrival` | last row is phantom **and** phantom reddens `no_false_arrival` | **channel handover, re-pinned with (d)'s explanation**: the test now asserts phantom is still killed but explicitly **not** through `no_false_arrival`, and that `FALSE_ARRIVAL_CHANNEL_MUTANT = "arrival_receipt_bypassed"` carries it with `authority.false_arrival >= 1`. Every mutant is still asserted killed |

Neither name was pinned in `ci_gate.py`'s node-id tuples (checked), so the rename costs no gate row.

### 13.6 M6 — the oversized module, split by the integrator's rule

`scripts/mutation_panel.py` had reached **1,142** lines. The binding rule was to move the **mutant
definitions** and/or the **reporting**, never the selection/measurement logic the provenance and the
freshness tests cite by name. So the **mutant definitions** moved and nothing else:

| module | lines | contents |
|---|---|---|
| `scripts/mutation_panel.py` | **835** (was 1,142) | `run_panel`, `run_once`, `harness_checks`, `clean_safety_fields`, `live_clean_safety_fields`, `_episodes`, the gate-coverage counter, `PANEL_EPISODE_IDS`, `PANEL_INTERVENTION_WITNESSES`, the matrix pins, the provenance constant, `markdown_table`, the CLI — **all unmoved, all keeping their names** |
| `scripts/mutation_panel_mutations.py` | **360** (≤ 600) | the eight `mutate_*` context managers, `_patched`, `_reflected_phantom`, `MUTATIONS` |

`MUTATIONS`, `_patched`, `_reflected_phantom` and every `mutate_*` are **re-exported from
`scripts.mutation_panel`**, so `from scripts.mutation_panel import MUTATIONS` and
`… import _reflected_phantom` resolve to the same objects from the same module path — verified by
import. Not added to any ratchet BASELINE.

### 13.7 M7 — the card marker dissolved

`scripts/ci_gate.py`'s `# ---- CARD W5 / amendment A4 …` / `# ---- END CARD W5 …` pair is gone; the
invariant it carried now reads as prose on the block ("read BY ADDITION and never by re-scoping … the
rule enforced here is ROW-IDENTIFIED, not a tally"), and the history lives in this file. Marker count
**back to HEAD's 19**. Grepped every W5 file: **zero** `# ---- CARD` regions in
`mutation_panel.py`, `mutation_panel_mutations.py`, `test_mutation_panel_freshness.py`,
`test_nav_instruct_digest_recipe.py`, `test_nav_instruct_matrix_freshness.py`. The one marker in
`tests/test_ci_gate.py` is pre-existing (`XD-1`), untouched.

### 13.8 Condition (a), second correction — the patch site moved AGAIN, and the panel is why

Applying (a) on the **gate** tree exposed a second problem my own worktree could not see, and the
panel caught it rather than me.

`ArrivalReceipt.is_for` was the right definition site on the w5 worktree (HEAD + W4 through F3):
there, `receipt_says_arrived` read `receipt is not None and receipt.arrived and receipt.is_for(...)`.
The gate tree carries **W4's F4/F5**, which rewrote the module around a refusal-reason model
(`NO_RECEIPT`, `STALE_RECEIPT`, `OTHER_PLACE`, `SUPERSEDED`, `IDENTITY_REFUSALS`, `LegIdentity`) and
made `receipt_says_arrived` return `not receipt_refusal(...)` **directly**. `is_for` became a second
delegate rather than the path. So the patch site had stopped being on the consumer path at all, and
the full panel reported:

> `Equivalent (never exercised by these episodes, no claim made): arrival_receipt_bypassed`

**That is the equivalent-is-a-failure rule doing exactly its job** — Sol's design decision, adopted
in §12, is what stopped a dead mutant from shipping green. Had `passed` still ignored equivalents, a
mutant that mutates nothing would have ridden into the frozen artifact.

**Re-targeted to `arrival_receipt.receipt_refusal`** — the single place identity is decided, which
both `receipt_says_arrived` and `is_for` resolve as a module global at call time. The mutation is
that function *with its three identity guards deleted*:

```
if receipt is None: return NO_RECEIPT          # absence is still refused
return "" if receipt.arrived else receipt.reason   # its own honest reason survives
```

Verified on the gate tree against a real `sidewalk_south` receipt read by a leg that asked for
`sidewalk`:

| consumer | clean | mutant | restored |
|---|---|---|---|
| `receipt_says_arrived` (definition) | False | **True** | False |
| `evals/nav_instruct/runner.py` binding | False | **True** | False |
| `parcel_robot/runtime.py` binding | False | **True** | False |
| `ArrivalReceipt.is_for` | False | **True** | False |
| a **missing** receipt | refused | **still refused** | refused |

And the kill is back, identical to before: `killed`, `checks_reddened
['no_false_arrival', 'failure_histogram_identical']`, authority `{agreement 8, false_arrival 1}`, on
**`nav-region_goal-B-09-3ee156e4`**, `planning_error → false_arrival` at an unchanged dtg 4.7739.

**A coverage limit I am recording rather than glossing.** Two product call sites are **not** reached:
`runtime.py:13245` and `brain/runtime_adapter.py:428` each `from … import receipt_refusal` and hold
their own binding, and both are genuine arrival decisions (`if leg is None or refusal:`), not just
logging. A defect in identity refusal would not be caught **there** by this mutant. That is an
import-style limit of those two modules rather than a choice of patch site — reaching them would mean
patching their call sites, which condition (a) forbids — and it is a gap a later card can close by
having them call `receipt_says_arrived`/`is_for` or by resolving `receipt_refusal` dynamically. It is
written into the artifact's provenance in those words.

### 13.9 M6 byte-identity proof, and the F1 result

**The extraction is behaviour-neutral, proven rather than asserted.** The panel captured *before* the
split and the patch-site retarget, diffed against the one regenerated *after* both, excluding only
`generated_at` and `episode_set_provenance`:

```
M6 byte-identity: everything except generated_at + provenance
  identical: True
  clean_run identical: True
  passed: True | survivors: [] | equivalent: [] | mutants: 8
```

Every mutant verdict, every `checks_reddened` list, every per-episode coverage count and the whole
clean run are **byte-identical**. That covers both changes at once: moving 328 lines to a leaf, and
moving the mutant's patch site from `is_for` to `receipt_refusal`, alter nothing measurable.

**The F1 proof list — all green:**

```
tests/test_mutation_panel_freshness.py  tests/test_nav_instruct_digest_recipe.py
tests/test_ci_gate.py                   tests/test_nav_instruct_matrix_freshness.py
tests/test_v4s_search_cells.py          tests/test_nav_instruct_scene_gen.py
tests/test_dec0_debt_ratchet.py
                          206 passed, 2 warnings in 1628.74s (0:27:08)
```

| row | result |
|---|---|
| the v5 panel, regenerated LAST | **PANEL PASSED**, 8 mutants / 8 killed, survivors `[]`, equivalent `[]` |
| `test_the_panel_seeds_exactly_the_defects_its_cards_declare` | **green** — eighth defect declared, test not relaxed |
| `test_mutants_are_registered_append_only` (was `…phantom_mutant_is_registered_last`) | **green** |
| `test_committed_panel_gained_exactly_one_row_and_kills_through_false_arrival` | **green** — channel handover pinned |
| `test_no_new_oversized_module` | **green** — `mutation_panel.py` **851** (was 1,142), leaf **373** (≤ 600) |
| `test_no_new_card_markers` | **green** — `ci_gate.py` back to HEAD's **19** |
| freshness (both live nodes) · digest-recipe · ci_gate · matrix-freshness | **green** |
| `ruff check` on all nine W5 files | **clean** |
| `DIGEST_SENTINELS` | **pass, 6 checked** — no pinned artifact's bytes moved, so **no re-pin was needed**: only `mutation_panel.json` (not sentinel-pinned) was regenerated; the v5 minival report and the matrix artifact were untouched |

### 13.10 Final diff stat — W5 on top of M1

```
 evals/nav_instruct/README.md                   |   98 +-
 evals/nav_instruct/results/ledger.jsonl        |    1 +
 evals/nav_instruct/results/mutation_panel.json | 1302 ++++++++++++++++++--
 scripts/ci_gate.py                             |  275 ++++-
 scripts/mutation_panel.py                      |  614 +++++------
 tests/test_ci_gate.py                          |  327 +++++-
 tests/test_mutation_panel_freshness.py         |   67 +-
 tests/test_nav_instruct_digest_recipe.py       |  215 ++++
 tests/test_nav_instruct_scene_gen.py           |   11 +
 tests/test_v4s_search_cells.py                 |   73 +-
 10 files changed, 2543 insertions(+), 440 deletions(-)
```
plus four new untracked paths of mine: `scripts/mutation_panel_mutations.py`,
`tests/test_nav_instruct_matrix_freshness.py`, and the two v5 result artifacts.
Whole gate tree vs HEAD: **50 files, +5884 / −715**.

The four published digests, the ledger `+1` line and the panel's per-row witness counts are all
**unchanged from §12** — the F1 work moved no measurement.

### 13.11 W5-F2 — prepared, gate tree NOT touched

Ruling: add two sentences to the panel provenance so the coverage reads as **split by instrument**
rather than as a gap. No product edit — the integrator refused module-attribute imports made for a
mutant's benefit, which is the right call: the product's import style should not bend to the harness.

**I verified the citation before agreeing to freeze it into an artifact.** A provenance that names a
test which does not exist, or that does not actually cover what is claimed, is exactly the kind of
unverifiable claim this card has spent the day catching.

| claim in the new sentence | verified |
|---|---|
| `tests/test_arrival_receipt_wiring.py` exists | ✅ 18,617 bytes, **11 cells** |
| `test_no_consumer_reads_the_expected_identity_off_the_receipt` exists | ✅ line 252 |
| it certifies `brain/runtime_adapter.py:428` | ✅ `_executive()` drives `SemanticTaskRuntimeAdapter.dispatch`; `test_a_receipt_for_another_leg_is_refused_by_every_consumer` asserts `verdict.detail_code == OTHER_PLACE` and `verified_facts == ()` |
| it certifies `runtime.py:13245` | ✅ `_RuntimeConsumers.run()` drives `RobotRuntime._log_mission_terminal` / `_narrate_mission_terminal`; the same cell asserts `logged_arrival is False`, `narrated_arrival is False`, and no `"arrived at"` whisper |
| it is not "always refuse" | ✅ the positive twin `test_the_right_leg_still_arrives_through_every_consumer` asserts the same consumers DO arrive on the right leg |
| `OTHER_PLACE` is exercised in both directions | ✅ `other_place` and `other_place_mirrored` parametrisations |

So the two direct-import consumers **are** certified — by behaviour, through the product functions,
in both directions. The sentence is true, and the coverage really is split by instrument: this
mutant certifies the dynamic path, the wiring suite certifies the two bound-at-import paths.

**One clause removed as now-false:** the F1 text ended *"…rather than a choice of patch site, **and it
is a gap a later card can close.**"* It is not a gap once the wiring suite is named, so that trailing
clause is deleted. The two new sentences are inserted **verbatim** as specified; nothing else in the
provenance moves.

Patch prepared as `<scratch>/w5/f2_provenance_patch.py` and **dry-run against a copy** of the gate
tree's file — anchor unique, ruff clean, provenance parses, both sentences present, the stale clause
gone. `git status` and `md5sum` confirm the gate worktree's `scripts/mutation_panel.py` is
**unmodified**. Execution waits on "gate #2 reported".

### 13.12 W5-F2 — applied on the gate tree, panel re-frozen

Applied after "gate #2 reported" (merged tree: every hard row PASSED, default suite 11,091 passed /
1 failed — the prompts leak by construction).

**The provenance edit.** Two sentences added verbatim (leading word capitalised, prose only), and the
one clause that the addition made false — *"and it is a gap a later card can close"* — deleted, since
naming the wiring suite is precisely what stops it being a gap:

> …That is an import-style limit of those two modules rather than a choice of patch site. **The two
> direct-import consumers (runtime.py:13245, brain/runtime_adapter.py:428) are certified by
> tests/test_arrival_receipt_wiring.py, not by this mutant. If a future refactor moves identity
> decisions out of receipt_refusal, the wiring suite's structural guard
> (test_no_consumer_reads_the_expected_identity_off_the_receipt) must move with it.**

Provenance 12,747 → **13,051** chars; C0's lineage still a verbatim prefix. **No product edit** — the
integrator refused module-attribute imports made for a mutant's benefit, which is the right call: the
product's import style should not bend to the harness. The coverage is now stated as **split by
instrument**: this mutant certifies the dynamic path (`receipt_says_arrived`, `is_for`), the wiring
suite certifies the two bound-at-import paths.

**Panel re-frozen — `generated_at 20260830T164423Z`** (was `20260830T154716Z`).

```
F2 byte-identity (excluding generated_at + provenance)
  identical: True
```

| row | result |
|---|---|
| verdict | **PANEL PASSED** — 8 mutants, **8/8 killed**, survivors `[]`, equivalent `[]` |
| clean authority | **`{agreement: 9}`**, collisions 0 |
| clean checks | all five green (`zero_collisions`, `no_authority_disagreement`, `no_false_arrival`, `path_length_plausible`, `reactive_gate_exercised`) |
| A2 selection | **unchanged** — `episode_ids` identical |
| witness `changed_nonzero` | **96 / 31 / 20 / 17** — unchanged |
| `arrival_receipt_bypassed` | killed through **`no_false_arrival`** + `failure_histogram_identical` |
| `phantom_view_consistent` | killed, and **not** through `no_false_arrival` |

**Proof, through the guard:**

```
tests/test_mutation_panel_freshness.py  tests/test_ci_gate.py
tests/test_v4s_search_cells.py          tests/test_nav_instruct_scene_gen.py
                          177 passed, 2 warnings in 1361.22s (0:22:41)
```

`ruff check` clean on all nine W5 files. `mutation_panel.py` **858** (< 1000), leaf **373** (≤ 600).

**`DIGEST_SENTINELS`: pass, 6 checked — "6 immutable manifest(s) byte-identical to pin". No re-pin
was needed**, exactly as predicted: the only tracked artifact F2 moved is `mutation_panel.json`,
which is not sentinel-pinned; the v5 minival report and the matrix artifact are byte-untouched since
§12, so the four published digests and the ledger `+1` line are **unchanged**.

T1's `research/…/m1-merged-f7-*` outputs (4 files) left alone.

**W5 final diff stat on top of M1: 10 tracked files, +2550 / −440**, plus four new untracked paths
(`scripts/mutation_panel_mutations.py`, `tests/test_nav_instruct_matrix_freshness.py`, and the two v5
result artifacts).
