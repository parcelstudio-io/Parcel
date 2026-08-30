# C7 · HARNESS-TRUTH-1 — executor status (Opus)

**Card:** `C7_HARNESS_TRUTH.md` (bars frozen) · **Verifier:** Fable · **Wave:** A
· **Started:** 2026-08-29 21:4x EDT

Research files only. No product code, no other author's research folder, no git
writes, no hosted calls, no `ci_gate.py`.

## Pre-flight

```
$ uptime
 21:41:58 up 7 days,  3:39,  1 user,  load average: 4.50, 4.10, 4.86
$ pgrep -af parcel_robot.sim
807004 .../python -m parcel_robot.sim --socket /tmp/parcel_sim.sock   # THE OWNER'S — never touched
```

Host load 4–5 with five peer executors sharing it, so the LIT-1 tier (5 × ~2 min,
one sim at a time under `systemd-run --user --scope -p MemoryMax=12G`) is
affordable; the NAV-INT-1 full tier (2–2.5 h) is not, and is re-run at the
re-issue rows only, as the card allows.

## Row 1 — LIT-1: no arrival phrase without an accepted terminal receipt

**Bar (verbatim):** "r1–r5 re-run (fake voice tier, `PARCEL_MEMORY_PATH` →
scratch, unique socket) narrate the receipt's kind on every failed receipt
(`failed` → the failed act; never an arrival phrase); the 5/5 receipt-kind
sequence unchanged; RESULTS.md §2–§8 PENDING stubs filled from the artifacts."

### RED — the defect, read out of the recorded artifacts

`artifacts/door_sofa_keys-fake-s20260829-r{1..5}-*.jsonl`, hop `voice_offer`:

```
71.29 receipt  kind=task_failed action=task_failed detail='semantic_target_unreachable'
71.29 VOICE_OFFER text="I've reached the bench. I can't check whether your keys are
      there — I have no camera, so I can't look for objects. Do you want me to head
      back to the lamppost?"  grounded_in='the accepted terminal receipt (MB-1 M7)'
```

5/5 base runs: an arrival claim, labelled as grounded in an accepted terminal,
emitted on a `task_failed` receipt. The narration path (`_flush_narration` →
`_fact_for`) was already honest ("Okay — bench is failed."); the *scripted offer*
was emitted unconditionally.

### Fix (`research/20260829/sim-loop-1/sim_loop.py`)

* `ACCEPTED_TERMINAL_KIND` / `TERMINAL_KINDS` — the receipt kinds that end a task,
  and the one kind an arrival phrase may be grounded in.
* `offer_for_terminal(scripted, receipt, *, goal)` — pure, unit-testable. On
  `task_succeeded` the scripted line stands. On failed / blocked / cancelled / no
  terminal receipt, the line OPENS with the receipt's own kind and detail and
  every scripted sentence carrying an arrival claim is dropped; the scenario's
  capability refusal and offer question are kept verbatim (both true whatever the
  terminal was), so the L7 confirm→re-issue rule keeps its referent and the
  receipt-KIND sequence cannot change.
* `_TimelineState._last_terminal_receipt()` / `_goal_label()`; the `after_terminal`
  branch now logs `text`, `scripted_text`, `receipt_kind`, `receipt_status`,
  `receipt_detail`, `arrival_phrase_allowed`, `rewritten`, `dropped_sentences`.

(status continues — rows filled as they land)

### GREEN — the re-run, 5 episodes, fake voice tier

```
$ unset TMPDIR
$ PARCEL_MEMORY_PATH=/home/jaewoo-jang/.cache/parcel-0e/c7/memory-c7.sqlite3 \
    .parcel/bin/python research/20260829/sim-loop-1/run.py \
      --scenario door_sofa_keys --voice fake --seed 20260829 --runs 5 --index 101 \
      --outdir research/20260829/sim-loop-1/artifacts \
      --results research/20260829/sim-loop-1/results_c7_postfix.json
```

(`run.py` re-pins `PARCEL_MEMORY_PATH` to `~/.cache/parcel-0e/lit1/memory-lit1.sqlite3`
itself, before a runtime exists — still scratch, never the owner's store; recorded
in the results file's `environment` block. Sockets `~/.cache/parcel-0e/lit1/s101..s105.sock`
under `systemd-run --user --scope -p MemoryMax=12G -p MemorySwapMax=0`; the owner's
`/tmp/parcel_sim.sock` (pid 807004) was listed by the teardown proof and never touched.)

Artifacts: `artifacts/door_sofa_keys-fake-s20260829-r10{1..5}-20260829T21*.jsonl`,
`results_c7_postfix.json` (the recorded `results.json` is left untouched).

| bar (verbatim from the card) | measured |
|---|---|
| "narrate the receipt's kind on every failed receipt (`failed` → the failed act; **never an arrival phrase**)" | 5/5 runs: `voice_offer` `receipt_kind=task_failed`, `receipt_status=failed`, `arrival_phrase_allowed=false`, `rewritten=true`, `dropped_sentences=["I've reached the bench."]`. **Arrival-phrase lines per run: RED 2 (10/10 across r1–r5) → GREEN 0 (0/10 across r101–r105).** |
| "the 5/5 receipt-kind sequence unchanged" | `submit, task_suspended, replacement_activated, task_failed, re_issue, submit, task_failed` — `identical_receipt_kinds: true`, `identical_n_of_m: 5/5`, one distinct sequence, **byte-identical to the recorded r1–r5 sequence** |
| — | `ok 5/5`, `teardown_clean true`, `lit1_sims_alive []`, `name_scan_leaks []`, `spend $0.00` |

What is now spoken on a failed terminal (r101, hop `voice_offer`, t = 67.88):

> My task executive reports the task for the bench as failed (receipt:
> task_failed, detail: semantic_target_unreachable), so the trip did not finish.
> I can't check whether your keys are there — I have no camera, so I can't look
> for objects. Do you want me to head back to the lamppost?

Latency rows reproduce: switch p50 309.4 ms (306.7–338.8) against the recorded
324.6 ms (239.5–339.6); `handle_text` p50 11.1 ms against 12.2 ms.

### Deterministic guard (no simulator)

```
$ env -u TMPDIR .parcel/bin/python research/20260829/sim-loop-1/selfcheck.py
all checks held        # 42 PASS / 0 FAIL  (26 before; C7 added 16)
```

Sixteen new rows: an accepted terminal keeps the scripted line verbatim; each of
`task_failed` / `task_cancelled` / `cancelled_at_checkpoint` drops every arrival
sentence, speaks the receipt's kind + status + detail, keeps the capability
refusal and the offer, and records the dropped sentence; a missing terminal
receipt says so; every terminal kind maps into the wave's fact set and exactly
one may say arrived.

### RESULTS.md §2–§8

`research/20260829/sim-loop-1/RESULTS.md` §2–§8 written from `results.json`,
`results_c7_postfix.json` and the JSONL artifacts. Every number is read out of a
file. §1's "26/26 checks held" updated to 42/42 with the added rows listed, and
the status blockquote now says the sections were completed under C7 rather than
"runs in flight". Section 7.4 records a record-hygiene defect found while
reading: `grounding_check` reports `passes: false` on every base run because
`must_not_contain_any: "your keys are"` matches as a **substring** of the honest
sentence "I can't check whether *your keys are* there". The scorer is
pre-registered and is left exactly as it was; the artefact is recorded, not
patched.

**Files touched (LIT-1):** `research/20260829/sim-loop-1/sim_loop.py`,
`selfcheck.py`, `RESULTS.md`; new `results_c7_postfix.json` and five artifacts.

## Row 3 — NAV-GEN-1: `analyze.py` renders every number RESULTS.md quotes

**Bar (verbatim):** "`analyze.py` renders every prose number; `results.json`
schema corrected; README 'no number typed by hand' true again."

Per the integrator's dispatch, **only the rendering functions were touched** —
`arm_config_facts` is card C3's line and is untouched (verified byte-for-byte in
`results.json`). The sweep was **not** re-run; the raw rows under
`~/.cache/parcel-0e/ng1/raw/` are read as they stand.

### RED — the four record defects (`VERDICT.md` §5.3)

| defect | RESULTS.md said | the artifacts say |
|---|---|---|
| false-arrival median DTG | "median 3.25 m" (in no file) | `statistics.median` over the 42 rows = **3.1722**; `dtg[n//2]` = **3.2492** — two conventions, neither named |
| false-arrival worst DTG | "worst 7.17 m" (in no file) | **7.169** |
| frozen-block strict rate | "0.2750 on 80 frozen-block episodes" (only per-target rows were in `results.json`) | **22/80 = 0.2750** |
| sweep A start host load | "3.06 / 2.97 / 2.72, GPU 2145 MiB" | **12.94 / 23.51 / 16.13, GPU 2058 MiB** (`raw/index_sweepA.json → host_start`). The quoted snapshot is in **no** artifact. |
| worker count | "cut from 32 to 24" (§0), "40 workers" (§8), "`--workers 40`" (README) | **not recorded anywhere** — `run.py` never wrote it |

### GREEN

```
$ env -u TMPDIR .parcel/bin/python research/20260829/nav-gen-attribution-1/analyze.py
```

Three new rendering functions, wired into `main()` and into `markdown()`:

* `false_arrival_dtg(data)` → `results.json` `false_arrival_dtg_A0` and
  `tables.md` **5.4**: n 42, min 0.6287, **median_interpolated_m 3.1722**,
  **median_upper_order_statistic_m 3.2492**, **max_m 7.169**, per target
  `crosswalk` ×42, plus a `convention_note` naming which is which.
* `frozen_block_summary(data)` → `frozen_block_summary_A0` and `tables.md`
  **6.2**: frozen 22/80 = **0.2750** [0.1892, 0.3814]; generated 293/450 =
  **0.6511** [0.6060, 0.6937]; **+37.61 points**.
* `run_provenance(index, idx_a)` → `run_provenance` and `tables.md` **8.1**: all
  four host snapshots under names that say which sweep they belong to
  (`sweepA_start` 12.94/23.51/16.13 → `sweepA_end` 3.95/12.86/17.14;
  `sweepB_start` 2.91/10.08/15.73 → `sweepB_end` 15.04/23.44/21.07), wall 530.4 s
  / 236.6 s, and `workers: null` with a `workers_note` saying it was never
  recorded. `run.py` now writes `run_provenance {workers, blas_threads_per_worker,
  cpus, argv}` into `raw/index.json`, so the next run renders a real number.

**No existing number moved.** `results.json` before/after diff is three added
top-level keys and nothing else; `tables.md` diff is three added sections and
nothing else (both diffs taken and kept in this card's scratch).

`RESULTS.md` prose corrected at all six sites (headline, §0 host table, §0
worker note, §5 false arrivals, §6 + §6-conclusion frozen-vs-generated, §8 scale
and host), each now pointing at the `results.json` key it comes from. `README.md`
updated: the `tables.md` row, the host-discipline paragraph, and the reproduce
block's "~13 min on 40 workers" (replaced by the recorded wall times).

**Files touched (NAV-GEN-1):** `analyze.py` (rendering functions + `markdown()` +
`main()` only), `run.py` (the `index = {...}` line only), `RESULTS.md`,
`README.md`, and the regenerated `results.json` / `tables.md`.

## Row 4 — MB-2: a per-run llama-server log path

**Bar (verbatim):** "MB-2: the llama-server log of the 180-turn run was
overwritten by a smoke run — add a per-run log path."

`research/20260829/model-b-contract-2/run.py` opened
`~/.cache/parcel-0e/mb2/llama-server-8093.log` in mode `"w"` on every T+P run, so
the 2-scenario smoke run clobbered the 180-turn run's server log
(`VERDICT.md` §6 item 2). Now:

```python
log = CACHE / (
    f"llama-server-{LOCAL_PORT}-{time.strftime('%Y%m%dT%H%M%S')}"
    f"-seed{args.seed}-n{len(corpus)}.log"
)
```

plus `print(f"[mb2] llama-server log: {log}")` and
`tp_aggregate["server_log"] = str(log)` so the log a number came from is findable
from `results.json` alone. The scenario count in the name makes a `--limit N`
smoke run structurally unable to land on the headline run's file.

**No server was started** (the card forbids it): the change is verified by
`ast.parse` and by reading the call site — `corpus` is bound at line 531, the log
line is 578, both inside `main()`.

**Files touched (MB-2):** `research/20260829/model-b-contract-2/run.py` (two
hunks).

## Row 2 — NAV-INT-1: a queued re-issue must strip the cue and record both forms

**Bar (verbatim):** "the re-issue row admits after cue-stripping; `gold_blind.json`
sha256 `c253df2f…` unchanged (the blind set is frozen)."

### Frozen-evidence check (E3), printed

```
$ sha256sum research/20260829/nav-interrupt-1/gold_blind.json
c253df2f707b158c4f6aaab42ce9fae77e98aae9502ef4bea987e2bae1fc1e65  gold_blind.json
$ cat research/20260829/nav-interrupt-1/gold_blind.sha256
c253df2f707b158c4f6aaab42ce9fae77e98aae9502ef4bea987e2bae1fc1e65  gold_blind.json
```

Equal to the card's `c253df2f707b158c4f6aaab42ce9fae77e98aae9502ef4bea987e2bae1fc1e65`.
**UNCHANGED.** The file was never opened for writing.

The cue regex moved from `queue_policy._QUEUE_CUE` to `harness.QUEUE_CUE_RE`
(one definition, imported back), so the classifier had to be proved byte-equal.
Re-scored on the frozen blind set, no simulator:

| | recorded `results.json` `h_ni1c.blind` | after the move |
|---|---|---|
| overall | 0.8273 (91/110) | **0.8273 (91/110)** |
| revise / keep / queue / clarify | 0.900 / 0.9333 / 0.6667 / 0.800 | **0.900 / 0.9333 / 0.6667 / 0.800** |
| non-adversarial / adversarial | 0.9143 / 0.6750 | **0.9143 / 0.6750** |

`QP._QUEUE_CUE is H.QUEUE_CUE_RE` → `True`. No H-NI1c number moves.

### RED — the defect, reproduced live at the product door

The full 40-episode tier is 2–2.5 h and five other executors share the host
(`uptime` 4–11), so the card's "re-issue rows only" option was taken: one sim,
the same `LiveSession.issue` door the tier uses, then one full queue-family
episode. Evidence in this card's scratch
(`~/.cache/parcel-0e/c7/ni1_door_red_green.json`, `ni1_reissue_rows.jsonl`);
`episodes.jsonl` and `results.json` in the research folder are **not** touched.

| | issued to `handle_text` | reply | tasks admitted |
|---|---|---|---|
| **RED** — verbatim | `"after that, go to the owner"` | `"I did not understand that command"` (`not_understood: true`) | **0** |
| **GREEN** — `strip_cue=True` | `"go to the owner"` (`raw_text` = `"after that, go to the owner"`, `cue_stripped: true`) | `"Okay—I'll follow you safely."` | **1** (`parcel-task-4c7a45ee…`) |

### GREEN — one queue-family episode with the re-issue leg through the door

```
$ unset TMPDIR
$ .parcel/bin/python <scratch>/ni1_reissue_proof.py     # LiveSession door test,
                                                        # then NI.stage_tier(tier, <scratch>/ni1_reissue_rows.jsonl, limit=1, offset=0)
```

`stage_tier` takes its output path as an argument, so the recorded
`episodes.jsonl` / `results.json` in the research folder were never opened for
writing.

| bar (verbatim) | measured |
|---|---|
| "the re-issue row admits after cue-stripping" | `ni1-00-bench-come_here` (family `queue`): queue log `hold_pre_runtime spoken='after that, go to the owner' will_issue='go to the owner'` → `reissue`. Leg record: `raw_text='after that, go to the owner'`, `text='go to the owner'`, `cue_stripped=true`, reply `"Okay—I'll follow you safely."`, **`admitted_work=true`**, task `succeeded` / `owner_follow_verified`. Run twice while the leg fields were completed: **2/2 admitted**. |
| "`gold_blind.json` sha256 `c253df2f…` unchanged" | `c253df2f707b158c4f6aaab42ce9fae77e98aae9502ef4bea987e2bae1fc1e65` — **unchanged**, and the classifier's blind numbers are byte-identical after the regex move |

**Arrival did not reproduce across the two reps** and is *not* this card's bar:
rep 1 held the owner-follow band (`system`/`scorer` both true, DTG 0.228 m, SPL
1.0, 69.6 s), rep 2 did not (both false, DTG 4.515 m, follow state `following`,
138.7 s under host load ~11). `come_here` is an owner-anchored approach whose
terminal is the formation band HELD; H-NI1b already records the all-re-issued
return rate as 13/34 = 0.382. The 40-episode tier was **not** re-run and no
H-NI1a/b/c number moves.

**Bonus record fix found while reproducing:** `Utterance.metrics["refused"]`
tests only for `"couldn't admit"` (the PlanIR admission refusal), so the RED row
reads `refused: false` on an utterance the product plainly refused with *"I did
not understand that command"*. A second flag `not_understood` was **added** (not
widened — no recorded number changes meaning): `true` on RED, `false` on GREEN.

**Files touched (NAV-INT-1):** `harness.py` (cue vocabulary + stripper +
`issue(strip_cue=)` + `Utterance.raw_text/cue_stripped` + `NOT_UNDERSTOOD`),
`queue_policy.py` (imports the cue from `harness`; the `queue` push branch now
strips and keeps `spoken`), `run.py` (`Leg.raw_text`/`cue_stripped`,
`run_leg(strip_cue=)`, the re-issue leg issues the spoken form), `README.md`,
`RESULTS.md` (a new "Card C7" section appended; nothing above it re-measured).

## Notes for the verifier

1. **`nav-gen-attribution-1/run.py` now has two cards' hunks.** C2's block in
   `run_unit` carries the comment "the ONLY change to this file"; that was true
   when written. C7's hunk is the `index = {...}` provenance dict in `main()`,
   nowhere near it. `arm_config_facts` was not touched by C7 — verified
   byte-for-byte in the regenerated `results.json`.
2. **Frozen evidence.** No frozen digest, episode set or gold file was written.
   `gold_blind.json` sha256 printed above and unchanged. NAV-GEN-1's raw rows in
   `~/.cache/parcel-0e/ng1/raw/` were read only; the sweep was not re-run.
3. **Ruff.** `.parcel/bin/ruff check` on all four folders: **All checks passed.**
   Zero `noqa` added (counts unchanged: `sim_loop.py` 4, `harness.py` 1,
   `queue_policy.py` 0, `analyze.py` 0).
4. **Host discipline.** Every sim on a unique short socket under
   `~/.cache/parcel-0e/{lit1,ni1}/` inside `systemd-run --user --scope -p
   MemoryMax=12G -p MemorySwapMax=0`, torn down by the harness that started it;
   `results_c7_postfix.json → teardown_proof.clean = true`, `lit1_sims_alive =
   []`. The owner's `/tmp/parcel_sim.sock` sim (pid 807004) was listed by the
   teardown proofs and never signalled. A peer's `c2nir/s7.sock` sim was seen and
   left alone. No pytest was run (no research folder here has tests), no
   `ci_gate.py`, no git write, no hosted call, **$0.00**.
5. **What a verifier can re-run cheaply.** `selfcheck.py` (2 s, 42/42) and
   `analyze.py` (seconds, byte-identical output) settle rows 1 and 3 without a
   simulator; the blind-set equivalence for row 2 is one import and 110
   `classify()` calls.

## Close

| row | bar | result |
|---|---|---|
| **LIT-1** | r1–r5 narrate the receipt's kind, never an arrival phrase; 5/5 sequence unchanged; RESULTS §2–§8 filled | **MET** — arrival-phrase lines 10/10 → **0/10**; sequence `submit, task_suspended, replacement_activated, task_failed, re_issue, submit, task_failed` identical 5/5 in both sets; §2–§8 written from the artifacts |
| **NAV-INT-1** | the re-issue row admits after cue-stripping; `gold_blind.json` sha256 unchanged | **MET** — RED 0 tasks / *"I did not understand that command"*; GREEN 1 task admitted, both forms recorded; sha256 `c253df2f…` unchanged and the blind classifier byte-identical |
| **NAV-GEN-1 / MB-2** | `analyze.py` renders every prose number; README "no number typed by hand" true again; MB-2 per-run log path | **MET** — 3.1722 / 3.2492 (convention named), 7.169, 0.2750 = 22/80, four host snapshots by sweep, worker count rendered as *not recorded* with `run.py` fixed to record it; MB-2 log now `llama-server-8093-<ts>-seed<N>-n<scenarios>.log` and recorded in `results.json` |
| **scope** | no product files touched; other authors' research folders untouched | **MET** — `git status` shows changes only under the four named folders plus `C7_STATUS.md` |


---

# Follow-up F1 — the scorer must follow the executive's committed instance

**Raised by:** C2's executor · **Scope:** research files only, same constraints
as card C7 · **Run:** 2026-08-29 23:3x–23:5x EDT

**The defect.** `research/20260829/nav-interrupt-1/harness.py`
`GoalSpec.region()` accepted a `committed` argument and used it **only** for
`object_near` goals. The `region` branch called `_region_goal(self.plain,
tier="A")`, hardcoded to the north `sidewalk` polygon, and `object_towards` was
hardcoded to `lamp_post_1`. The static city carries a real second instance,
`sidewalk_south`, ~4.98 m away and carrying the same label. So a leg whose
executive committed `sidewalk_south`, drove there and verified arrival was
scored against a polygon it was never sent to.

**The fix.** `GoalSpec.region_with_provenance(committed=…)` — used by every
non-owner kind — under a same-label tie-break stated once in `harness.py` and
documented in `README.md`:

| `region_source` | when | scored |
|---|---|---|
| `committed_instance` | the executive committed an instance the scene knows, carrying this goal's label | that instance |
| `default_instance` | nothing committed, or an id the scene table does not know | the generator's tier-A default |
| `default_instance_label_mismatch` | an instance was committed but carries a **different** label | the default — a wrong-instance arrival must not be scored against its own choice |
| `owner_anchored` / `not_scored` | an approach / a HOLD row | — |

Two deliberate guards: (a) the same-label requirement, so the fix cannot turn a
wrong-instance arrival into a pass; (b) **the landmark table is pinned per goal
kind** — region and `towards` keep the generator's frozen `_LANDMARKS`, `near`
keeps `derived_landmark_table()`, exactly as the recorded tier scored them. The
two tables disagree (north sidewalk y ∈ [2.4, 3.6] vs [2.2, 4.2]; bench radius
0.700 vs 0.734); unifying them would move recorded numbers for a reason
unrelated to this defect.

**Recorded, per leg:** `region_provenance` now rides on every `Leg` and every
`score_arrival` verdict — the raw committed id, the instance actually scored,
the table it came from, the sibling same-label instances, and the rule that
fired. Before F1 no row said which polygon a number came from.

## BEFORE / AFTER — offline re-score of every recorded leg

The verdict is a pure function of (goal, end pose, `system_arrival`, committed
id), all already in the recorded rows, so all **82 non-owner legs** across
`controls.jsonl` + `sequence_controls.jsonl` + `episodes.jsonl` were re-scored
with no simulator (`~/.cache/parcel-0e/c7/f1_rescore.json`):

| authority category | before | after |
|---|---|---|
| `agreement` | 63 | **69** |
| `false_arrival` | **6** | **0** |
| `authority_disagreement` | 13 | 13 |

**Sidewalk legs only (n = 18): `false_arrival` 6 → 0**, `agreement`
12 → 18. All 6 flips are the same shape:

| leg | committed | before | after |
|---|---|---|---|
| `ni1-09-bench-sidewalk`:`amended_goal` | `sidewalk_south` | false_arrival, DTG 4.981 m | **agreement**, DTG 0.0 m |
| `ni1-10-bench-sidewalk`:`amended_goal` | `sidewalk_south` | false_arrival, DTG 4.982 m | **agreement**, DTG 0.0 m |
| `ni1-11-bench-sidewalk`:`reissue` | `sidewalk_south` | false_arrival, DTG 4.981 m | **agreement**, DTG 0.0 m |
| `ni1-20-sidewalk-bench`:`reissue` | `sidewalk_south` | false_arrival, DTG 4.984 m | **agreement**, DTG 0.0 m |
| `ni1-36-towards_lamppost-sidewalk`:`amended_goal` | `sidewalk_south` | false_arrival, DTG 4.978 m | **agreement**, DTG 0.0 m |
| `ni1-37-towards_lamppost-sidewalk`:`reissue` | `sidewalk_south` | false_arrival, DTG 4.975 m | **agreement**, DTG 0.0 m |

Two disclosures, both non-sidewalk:

1. `ni1-29-towards_lamppost-bench`:`reissue` committed `lamp_post_2` while the
   `object_towards` branch was hardcoded to `lamp_post_1`; its DTG moves
   0.310 → 8.261 m. Category `agreement` before and after, so no rate moves —
   but 0.310 m was distance to a lamppost the robot had not been sent to.
2. Three legs differ by ≤ 0.001 m. That is the offline re-score, not the fix:
   the rows store `end` rounded to 3 dp while their DTG came from the
   full-precision pose. No category, no bar.

## Live re-run — the six legs that commit `sidewalk_south`

The from-rest sidewalk **controls only ever commit the default (north)
instance**, so per the README they cannot exercise the fix; the cheapest
faithful subset is the six tier episodes whose sidewalk leg commits
`sidewalk_south` (tier offsets 9, 10, 11, 20, 36, 37).

```
$ sha256sum research/20260829/nav-interrupt-1/interrupt_tier_v1.json \
            ~/.cache/parcel-0e/c7/tier_export.json
23466d5ff9e4452e38f0da7f82fcc53019f16efed55208faf191845c33dce541  interrupt_tier_v1.json
23466d5ff9e4452e38f0da7f82fcc53019f16efed55208faf191845c33dce541  tier_export.json   # pinned scratch export

$ unset TMPDIR
$ .parcel/bin/python <scratch>/f1_rerun_sidewalk.py
[f1] WORKDIR=/home/jaewoo-jang/.cache/parcel-0e/c7/ni1f1 \
     PARCEL_MEMORY_PATH=/home/jaewoo-jang/.cache/parcel-0e/c7/ni1f1/memory-f1.sqlite3
```

Own socket root (`~/.cache/parcel-0e/c7/ni1f1/`) so a peer running the same
harness on the shared `~/.cache/parcel-0e/ni1/` cannot collide — C2's executor
was running `--stage controls --only bench` on `c2nif/` at the time. Every sim
launched by `harness.LiveSession` under `systemd-run --user --scope -p
MemoryMax=12G -p MemorySwapMax=0` and torn down by `run.Sessions`. Output to
`~/.cache/parcel-0e/c7/f1_sidewalk_legs.jsonl`; the recorded `episodes.jsonl`,
`controls.jsonl`, `sequence_controls.jsonl` and `results.json` were never opened
for writing.

| episode | leg | committed | scored | rule | system / scorer | category | DTG (m) |
|---|---|---|---|---|---|---|---|
| `ni1-09-bench-sidewalk` | `amended_goal` | `sidewalk_south` | `sidewalk_south` | `committed_instance` | true / true | **agreement** | 0.0 |
| `ni1-10-bench-sidewalk` | `amended_goal` | `sidewalk_south` | `sidewalk_south` | `committed_instance` | true / true | **agreement** | 0.0 |
| `ni1-11-bench-sidewalk` | `reissue` | `sidewalk_south` | `sidewalk_south` | `committed_instance` | true / true | **agreement** | 0.0 |
| `ni1-20-sidewalk-bench` | `reissue` | `sidewalk_south` | `sidewalk_south` | `committed_instance` | true / true | **agreement** | 0.0 |
| `ni1-36-towards_lamppost-sidewalk` | `amended_goal` | `sidewalk_south` | `sidewalk_south` | `committed_instance` | true / true | **agreement** | 0.0 |
| `ni1-37-towards_lamppost-sidewalk` | `reissue` | `sidewalk_south` | `sidewalk_south` | `committed_instance` | true / true | **agreement** | 0.0 |

**Live: `false_arrival` on these sidewalk legs 6 → 0** ({'agreement': 6}), and every
row now names the polygon it was scored against.

## Frozen evidence and regressions

```
$ sha256sum research/20260829/nav-interrupt-1/gold_blind.json
c253df2f707b158c4f6aaab42ce9fae77e98aae9502ef4bea987e2bae1fc1e65  gold_blind.json   # UNCHANGED
```

* H-NI1c blind set re-scored after the change: 91/110 = **0.8273**; revise
  0.900 / keep 0.9333 / queue 0.6667 / clarify 0.800; non-adversarial 0.9143,
  adversarial 0.6750 — byte-identical to the recorded numbers.
* LIT-1 regression (it imports this harness by path and calls `score_arrival`
  with **no** committed id → `default_instance`): `selfcheck.py` 42/42 holds and
  the recorded bench / lamppost DTGs reproduce (3.336 / 1.386 against the
  recorded 3.335 / 1.385 — the millimetre is the rounded end pose).
* H-NI1a (admission) and H-NI1b (return rate, path ratio) are counted from task
  receipts, not from the arrival region: unchanged. What moves is the
  `false_arrival` half of the authority tally; the 13 `authority_disagreement`
  legs are untouched and remain a product finding.
* `.parcel/bin/ruff check` on the folder: **All checks passed**; zero `noqa`
  added; no pytest, no `ci_gate.py`, no git write, no hosted call, **$0.00**.

## Files touched (F1)

| file | change |
|---|---|
| `research/20260829/nav-interrupt-1/harness.py` | `_LANDMARK_TABLE_BY_KIND`, `label_of(kind=…)`, `REGION_FROM_*`, `GoalSpec.table` / `.label` / `.default_entity_id` / `._region_for` / `.region_with_provenance`; `region()` delegates; `score_arrival` returns `region_provenance` |
| `research/20260829/nav-interrupt-1/run.py` | `Leg.region_provenance` + populated in `finish_leg`, the owner branch and the HOLD row |
| `research/20260829/nav-interrupt-1/README.md` | the same-label tie-break table |
| `research/20260829/nav-interrupt-1/RESULTS.md` | new "Card C7-F1" section (nothing above it re-measured) |
| `scrum/20260829/task_2/C7_STATUS.md` | this section |

Scratch (not in the repo): `~/.cache/parcel-0e/c7/{tier_export.json,
f1_rescore.json, f1_sidewalk_legs.jsonl, f1_sidewalk_summary.json, f1_rerun.log}`.
