# R27_STATUS — the owner's memory is not a scratch file

**Card:** `scrum/20260821/task_9/README.md` · **Executor:** Claude Opus ·
**Auditor:** Fable (deferred — written to be audited cold) · **Date:** 2026-08-21

---

## 0. Headline

The owner's store was reachable because `configs/robot.yaml` names it with a
**relative** path and `sqlite3.connect` resolves relative paths against the
process CWD. That is now a **refusal**, not a convention: a process that has not
declared itself the owner's stack cannot open
`/home/jaewoo-jang/Desktop/Projects/Parcel/parcel_memory.sqlite3` for writing,
and **a pytest process cannot make that declaration at all**, however it
configures itself.

Four things this card found that the card itself did not know:

> **1. The pollution vector shipped in the repo, and the gate ran it.**
> A `sqlite3.connect` interceptor over the whole 7,686-test commit tier found
> **exactly one** test opening the owner's real database:
> `tests/test_fail_closed_limits.py::test_shipped_config_still_launches`. It
> calls `web_panel.build_runtime(SHIPPED_CONFIG, …)`, it is inside
> `default-suite`, and it therefore ran on **every `ci_gate.py --tier commit`
> invocation by every executor** — including the runs pasted in R24 §2 and
> R26 §10. This was never anybody's live proof. It was the house rule.

> **2. "Opened" and "wrote rows" are different, and the difference exonerates
> the gate for the 256 rows while convicting it of the access.** Measured on a
> byte-copy: constructing the runtime from the shipped config moves the row
> count `3138 -> 3138` — zero rows — but *does* open the file read-write and run
> the additive `ALTER TABLE` migration against it. Handling **one** typed
> command moves it `3138 -> 3141`. The 256 rows came from processes that
> actually handled turns; the gate was a standing unauthorised write handle that
> happened not to append.

> **3. The synthetic rows are not separable by content, only by time — and the
> time boundary is triple-confirmed.** Row id **2882** is the last genuine row.
> R18's docstring independently counted the store at **2,882 rows** on
> 2026-08-20 and **2,618** NULL-speaker/NULL-origin rows at that moment;
> `id <= 2882` yields exactly 2,618 such rows today, and there is a 42-minute
> gap between id 2882 (20:30:12) and id 2883 (21:12:29) where the burst starts.
> Three measurements taken for three different reasons agree.

> **4. THE IRONY CLAUSE FIRED ON MY OWN WORK, and the finding is in §9.** The
> owner's store sha256 **changed during this card**: `7da58192…` -> `40506fd9…`.
> It was my seed harness, not the shipped code. Zero rows were added, removed or
> altered — the delta is one nullable `writer` column — and the whole thing is
> measured, attributed and left owner-gated rather than quietly restored.

---

## 1. What changed

| File | What |
| --- | --- |
| `src/parcel_robot/memory_path.py` | **new.** The resolver and the refusal. Three rules, all fail-closed. |
| `src/parcel_robot/memory.py` | `ConversationMemory.__init__` resolves through it; `writer` column added to `PROVENANCE_COLUMNS`/`MIGRATED_COLUMNS`; `add()` and `write_realtime_turn()` stamp it |
| `src/parcel_robot/conversation_store.py` | `SqliteConversationStore.__init__` and `open_store()` obey the same rules |
| `scripts/launch_stack.sh`, `scripts/launch_sim.sh` | `export PARCEL_MEMORY_PURPOSE="${PARCEL_MEMORY_PURPOSE:-owner}"` — the owner declaration, and the only one in the tree |
| `tests/test_owner_store_isolation.py` | **new.** 25 tests; the guard, as a property |
| `tests/test_fail_closed_limits.py` | the offender fixed: it now sets `PARCEL_MEMORY_PATH` at `tmp_path` |
| `scripts/ci_gate.py`, `tests/test_ci_gate.py` | new hard gate `owner-store-isolation` in **both** tiers; the required-entry list gains it |
| `tools/quarantine_synthetic_memory.py` | **new.** Dry-run default, side table, never deletes |
| `scrum/20260821/task_3/R24_STATUS.md` §11, `scrum/20260821/task_5/R26_STATUS.md` §13 | dated corrections, appended, nothing rewritten |

### 1.1 The three rules, and why each has that shape

Full reasoning is in the module docstring; the short version:

1. **`PARCEL_MEMORY_PATH` wins over any config**, and must be absolute or
   `:memory:`. This is R5 open risk 5's own ask. It is also what makes the guard
   *usable* — a live proof needs one exported variable, not a copied config.
   A **relative** override is refused: it would be the CWD bug wearing a new name.
2. **A relative path is refused for writing** unless the purpose is `owner`.
   A relative store path is a question ("relative to where?") whose answer moves.
   The owner's stack keeps its relative config path, but it is now anchored at
   the **repo root** rather than the CWD, so the same config names the same file
   from anywhere. That single line retires R5 open risk 5's mechanism.
3. **The owner's store requires an owner declaration, and a test can never make
   one.** `PARCEL_MEMORY_PURPOSE=owner` is set by the two launchers and by
   nothing inside `src/`. Under pytest it is **ignored outright**.

### 1.2 Why the declaration lives in a shell script

This is the load-bearing asymmetry and it is worth stating plainly. All four
polluting card-chains ran **in-process** runtimes — `python -c`, a pytest test, a
harness — because booting the whole sim is expensive. If the declaration lived
anywhere in `src/`, importing the runtime would confer it, and an in-process
runtime from the repo root would be back where it started. Keeping it in
`launch_stack.sh` / `launch_sim.sh` means *the act of being the owner's stack* is
what grants access, and that act is not importable.
`test_the_library_never_declares_itself_the_owner` pins it.

### 1.3 Why the constructor and not the config read

`runtime.py:1769` reads `memory_cfg.get("path")` and would have been the obvious
place. It is the wrong one: it protects the runtime and leaves
`ConversationMemory("parcel_memory.sqlite3")` — one line in any test — wide open.
`ConversationMemory.__init__` is the chokepoint every path goes through, so that
is where the refusal is.

### 1.4 What was deliberately NOT changed

* **`read_only=True` bypasses every refusal.** A `mode=ro` connection is the one
  configuration in which the defect cannot occur (SQLite itself raises on a
  write), and two consumers need it: R18's recall proof, and this card's own
  quarantine dry run. Refusing it would have cost real evidence and bought
  nothing. `test_reads_of_the_owner_store_are_still_permitted` pins both halves —
  the read works, and an `INSERT` through the same handle raises
  `sqlite3.OperationalError`.
* **No backfill of `writer`.** Every pre-R27 row would have to be guessed at, and
  a guessed provenance column is worse than an honest NULL: it would make the
  *next* pollution audit trust a fabrication. NULL means "written before this
  column existed", which is true of all 3,138 of them.
* **No config edits.** The card's MUST-NOT list includes configs;
  `memory.path: parcel_memory.sqlite3` is untouched in all three `robot.yaml`
  copies, which is also what keeps `test_authority_config_drift` and the release
  parity gates quiet.

---

## 2. The gate — verbatim, run after the final edit

`.parcel/bin/python scripts/ci_gate.py --tier commit` — **run last, on the final
tree**, after the last source edit, after the final seed sweep, and after the
stray-file cleanup in §9.5. Exit status `0`.

```
CI GATE — tier=commit  (2026-08-21T14:56:26Z)
==============================================================================
[  PASS] HARD  ruff                       7 violation(s), baseline 7, new 0
[  PASS] HARD  hard-safety                nav frozen baseline nav-instruct-v1-baseline-v4-20260811T070536Z: collisions=0 false_arrival=0 | mutation panel clean: collisions=0 no_false_arrival=True | mutation panel freshness: committed fields reproduce live = True | follow-bench: 7 row(s), hard_collision_total all 0 = True | walk_with_me: 1/2 row(s) with hard_collision_total, all 0 = True
[  PASS] HARD  frozen-digest-sentinels    4 immutable manifest(s) byte-identical to pin
[  PASS] HARD  release-parity             91 packaged asset(s) byte-identical to canonical source
[  PASS] HARD  latency-tail-ledger        latest row latency-20260810T082415Z-4d83035f: 6 metric series within 1.2x tail ceiling (rows=5, window=5)
[  PASS] HARD  follow-bench-jerk-ratchet  latest shipped row follow-bench-v1-20260811023618Z-93eba090.json: 1.2187 <= 1.46244 (baseline 1.2187 x 1.2)
[  PASS] HARD  assertion-evals            5 frozen fixture(s) reproduce 20 pinned finding(s) byte-identically; harness self-test 4/4 (3 broken agents failed, clean control passed); pass^1 green on f03_estop_pass_k; 3/3 committed run folder(s) present
[  PASS] HARD  tier-coverage              7762 collected = 7720 commit (-m 'not slow') + 42 nightly (-m 'slow'), no orphans, no overlap
[  PASS] HARD  model-off-non-inferiority  23 passed in 0.48s
[  PASS] HARD  frozen-digest-integrity    6 passed, 1 warning in 0.33s
[  PASS] HARD  release-parity-integrity   10 passed in 0.75s
[  PASS] HARD  mutation-panel-freshness   2 passed, 3 warnings in 4.23s
[  PASS] HARD  latency-tail               6 passed, 2 warnings in 0.31s
[  PASS] HARD  owner-store-isolation      6 passed in 1.57s
[  PASS] HARD  default-suite              7711 passed, 9 skipped, 42 deselected, 5 warnings in 306.28s (0:05:06)
==============================================================================
RESULT: PASS — every hard gate green.
  elapsed 335.5s
```

**Coverage moved in one direction only.** `tier-coverage` reads
`7762 collected = 7720 commit + 42 nightly`, against `7728 = 7686 + 42` before
this card: **+34**, of which 25 are `tests/test_owner_store_isolation.py` and 9
are the deselected-count arithmetic settling around them. The 42 nightly-selected
are unchanged. `assertion-evals` and `tier-coverage` both still run in both tiers
and neither lost an entry — the hard-gate list **gained** one,
`owner-store-isolation`, and `tests/test_ci_gate.py`'s literal required-entry
list went from 14 names to 15 so the addition cannot be silently removed either
(seed S11).

`ruff` reports `7 violation(s), baseline 7, new 0` — the pre-existing baseline,
untouched; every file this card added or edited is independently clean.

**The gate no longer opens the owner's store.** That is the difference this
section cannot show by itself and §3 measures: the same command, before this
card, held a read-write handle on `parcel_memory.sqlite3` for the duration of
`default-suite`.

---

## 3. The measurement that found the offender

The card asserts the pollution and names no mechanism. Before writing any code I
ran the whole commit tier under a `sqlite3.connect` interceptor that **refuses
and records** any attempt on the owner's file, so the survey itself could not add
a row. (`scratchpad/r27/ownerstoreprobe.py`, loaded with `-p`.)

```
7686 tests collected (-m "not slow")
1 failed, 7685 passed, 9 skipped, 42 deselected, 5 warnings in 301.68s

FAILED tests/test_fail_closed_limits.py::test_shipped_config_still_launches
```

One offender, and its stack is unambiguous:

```
  File "tests/test_fail_closed_limits.py", line 335, in test_shipped_config_still_launches
    runtime = web_panel.build_runtime(SHIPPED_CONFIG, tmp_path / "sim.sock", use_llm=False)
  File "src/parcel_robot/web_panel.py", line 651, in build_runtime
    return RobotRuntime(
  File "src/parcel_robot/runtime.py", line 1769, in __init__
    memory=ConversationMemory(memory_cfg.get("path", ":memory:")),
  File "src/parcel_robot/memory.py", line 288, in __init__
    self.connection = sqlite3.connect(path, check_same_thread=False)
```

The owner's store sha256 was unchanged across that run — the probe blocked the
open rather than observing it.

### 3.1 Open versus append, measured

On a byte-copy of the owner's store, with `PARCEL_MEMORY_PATH` pointed at it:

```
construct-only:              rows 3138 -> 3138
cols now: [... 'provider_item_id', 'writer']      <- the ALTER TABLE ran
after ONE typed command:     rows 3138 -> 3141
  ('assistant', "My camera feed is stale right now, ...", 'unknown')
  ('user', 'go to the lamppost', 'unknown')
```

Two things at once: the gate's vector is a real write handle that appends
nothing, **and** work item 2 is demonstrated end-to-end — a process that declared
no purpose is stamped `unknown`, not silently filed as something it is not.

### 3.2 The card's demonstration, executed

A default-config in-process runtime, started from the repo root, with no
environment — the exact thing four card-chains did:

```
$ env -u PARCEL_MEMORY_PATH -u PARCEL_MEMORY_PURPOSE .parcel/bin/python -c \
    "from parcel_robot import web_panel;
     web_panel.build_runtime('configs/robot.yaml', '/tmp/r27_demo.sock', use_llm=False)"

parcel_robot.memory_path.MemoryPathRefused: card R27: refusing to open the OWNER'S
conversation memory for writing.
    store   : /home/jaewoo-jang/Desktop/Projects/Parcel/parcel_memory.sqlite3
    from    : memory.path='parcel_memory.sqlite3'
    purpose : test  (none declared)

That file is the owner's real conversation history. A synthetic turn
written into it is one the robot can later recall out loud as something
the owner said — 256 such rows were measured on 2026-08-21.

Pick one:
  * a scratch file : export PARCEL_MEMORY_PATH=/tmp/parcel_scratch_memory.sqlite3
  * no file at all : export PARCEL_MEMORY_PATH=:memory:
  * the real stack : scripts/launch_stack.sh   (it declares PARCEL_MEMORY_PURPOSE=owner)
```

And the escape hatch, same command with one variable set:

```
store = ResolvedStore(path='/tmp/.../scratch_live.sqlite3', purpose='test',
                      writer='unknown', is_owner_store=False, read_only=False)
```

Both are kept executable as
`test_a_repo_root_in_process_runtime_cannot_reach_the_owner_store` and
`test_the_documented_escape_hatch_actually_works`. **A refusal with no way out is
a broken product**, so the way out is tested, not just documented.

---

## 4. The quarantine dry run, over the real store, read-only

`--dry-run` is the default and it opens the database `mode=ro` through the
audited R18 opener, so the report below could not have written even if the tool
had a bug. Verbatim (contents list truncated to the top rows):

```
quarantine_synthetic_memory — card R27 work item 4
==========================================================================
store      : /home/jaewoo-jang/Desktop/Projects/Parcel/parcel_memory.sqlite3
mode       : DRY RUN — nothing was changed
total rows : 3138
candidates : 256   (ids 2883–3138)
retained   : 2882   <- everything else is untouched

Windows searched
--------------------------------------------------------------------------
  2026-08-20 21:12:00 .. 2026-08-21 11:05:59 UTC
    matched : 182 rows   (ids 2883–3064)
    source  : card R27 README: the 182 rows measured when the card was written;
              R24_STATUS §4.5 and R26_STATUS §11 both claimed this window was clean
  2026-08-21 13:31:00 .. 2026-08-21 13:48:59 UTC
    matched : 74 rows   (ids 3065–3138)
    source  : the 74 rows added while card R27 itself sat unexecuted; PG3_STATUS
              §8.1 says 'Nothing was run live' and its own window wrote at 13:48:52 UTC

Distinct contents among candidates: 25
--------------------------------------------------------------------------
    35x  Okay—I'll go wait near lamppost safely.
    20x  Okay—I'll move onto sidewalk and verify it.
    16x  Okay—I'll make the requested local circle around you safely.
    14x  Okay—I'll follow you safely.
    14x  go to the sidewalk
    13x  Okay—I'll head over to lamppost and sit down.
    13x  sit next to the lamppost
     9x  go to the lamppost
     8x  I don't know a place called "fountain" — the ones I do know nearby are the crossw...
     8x  Okay—I'll go wait near fountain safely.
     8x  circle the owner once
     8x  find the fountain
     8x  go to the fountain
     8x  walk around the owner
     7x  Okay—I'll head over to bench and sit down.
     7x  Okay—I'll stay here.
     7x  can you walk towards the lamppost
     7x  come here
     7x  go to the owner
     7x  run to the nearest lamppost
     7x  sit next to the bench
     7x  stay
     6x  find the nearest lamppost
     6x  head towards the lamppost
     6x  please move onto the sidewalk

Nothing was changed. To act on this, the OWNER runs:
    PARCEL_MEMORY_PURPOSE=owner .parcel/bin/python \
        tools/quarantine_synthetic_memory.py --apply

which MOVES these rows to `quarantined_messages` (it never deletes).
```

**`182 + 74 = 256` and `3138 - 256 = 2882`** — the retained count lands exactly on
R18's independently measured pre-incident total. `find the nearest lamppost`, the
row the card cites as user-visible through `recall("lamppost")`, is in the list
(6 copies).

### 4.1 Why windows and not `id > 2882`

An id cutoff is simpler and wrong: it would swallow every genuine turn the owner
takes from now on. A window cannot. The predicate is
`speaker IS NULL AND origin IS NULL AND session_id IS NULL AND
provider_item_id IS NULL AND (writer IS NULL OR writer <> 'owner_stack')` inside
a named window — every clause **narrows**, none widens, and the `writer` clause
means the tool keeps working after this card: a future stray row is stamped
`test` or `unknown` and is caught by the same predicate.

### 4.2 The destructive mode was NOT run against the owner's store, and cannot be by accident

`--apply` is gated by **this card's own mechanism** rather than by a
confirmation prompt (which a non-interactive executor pipes `yes` into):

```
$ .parcel/bin/python tools/quarantine_synthetic_memory.py --apply
card R27: refusing to open the OWNER'S conversation memory for writing.
    ...
--apply on the owner's store is the owner's decision to make, and it is spelled:
    PARCEL_MEMORY_PURPOSE=owner .../python quarantine_synthetic_memory.py --apply
exit status 3
```

Proved working on a **copy** of the owner's store: `messages` 3138 -> 2882,
`quarantined_messages` 0 -> 256, every moved row carrying `quarantine_reason`.
`test_quarantine_apply_is_refused_against_the_owner_store` asserts the refusal
and the file's size+mtime afterwards.

---

## 5. The record corrections (card work item 5)

Both are **appended**, dated, and rewrite nothing.

| Doc | Section | The false claim | Corrected to |
| --- | --- | --- | --- |
| `scrum/20260821/task_3/R24_STATUS.md` | new §11, correcting §4.5 | "the owner's `parcel_memory.sqlite3` was never opened — every fixture uses `memory: path: \":memory:\"`" | the fixtures were isolated; the **gate** was not. Opened read-write once per commit-gate run, ALTER TABLE run, **0 rows appended** |
| `scrum/20260821/task_5/R26_STATUS.md` | new §13, correcting §11 | "No POST, no restart, **no read of `parcel_memory.sqlite3`**" | six opens (four `not slow` sweeps + two commit gates), same open-not-append distinction |

Both corrections state explicitly what is **not** being corrected — R24's spend
and `:8765` claims, R26's OWLv2 run, credential handling and tree-changes list
all stand. R26's §11 is worth quoting on the lesson: the `:8765` port check
beside the false claim was *measured* and is correct; the file claim was
*inferred* from it.

---

## 6. Seeds — twelve, every one RED for the right reason, every one restored byte-identically

Protocol (house rule R9), applied identically to all twelve: snapshot bytes +
sha256 -> apply ONE textual mutation (or delete one file) -> **purge every
`__pycache__` under `src/ scripts/ tests/ tools/ evals/`** -> **fresh-interpreter
canary proving the mutation is genuinely loaded** (`PYTHONDONTWRITEBYTECODE=1`; a
stale `.pyc` compiled from mutated source passes byte-identity checks and has
poisoned a run before) -> run the named guard(s), require RED -> restore in a
`finally` -> purge again -> assert sha256 identity -> second canary proving the
mutation is GONE -> re-run, require GREEN. **Plus, this card only:** the owner's
store's sha256 is recorded before and after *each individual seed*, and the file
is `chmod 0444` for the mutated run (§9).

**The sweep below ran AFTER the last source write** — the last edit was
strengthening `test_a_relative_override_is_refused` (§7.1), and this sweep
followed it. Harness: `scratchpad/r27/seed_harness.py`; raw output
`scratchpad/r27/seeds_final.txt`, `seeds.json`. Mutations are reproduced in full
so the table survives the scratchpad.

| # | What is broken | File | Mutation | Guard that must redden | RED | GREEN after restore | sha identical | owner store safe |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| **S1** | a relative `memory.path` is silently accepted | `src/parcel_robot/memory_path.py` | `if not candidate.is_absolute() and effective != PURPOSE_OWNER:` -> `if False:` | `test_a_relative_path_is_refused_even_when_it_is_harmless`, `test_the_conversation_store_obeys_the_same_rules` | `2 failed` | `2 passed` | yes | yes |
| **S2** | **fail-OPEN on a missing explicit path** — the owner's store is handed out | `src/parcel_robot/memory_path.py` | `if is_owner and effective != PURPOSE_OWNER:` -> `if False:` | `test_conversation_memory_refuses_the_owner_store_by_absolute_path`, `test_no_shipped_config_can_be_launched_onto_the_owner_store`, `test_a_repo_root_in_process_runtime_cannot_reach_the_owner_store`, `test_a_test_process_cannot_declare_itself_the_owner` | `2 failed, 2 passed` | `4 passed` | yes | yes |
| **S3** | the per-row **provenance column is dropped** | `src/parcel_robot/memory.py` | `PROVENANCE_COLUMNS = (("writer", "TEXT"),)` -> `()` | `test_the_provenance_column_exists_and_is_migrated_additively` | `1 failed` | `1 passed` | yes | yes |
| **S4** | the writer stamp is never written to a row | `src/parcel_robot/memory.py` | `(role, content, self.writer)` -> `(role, content, None)` | `test_every_new_row_records_which_process_class_wrote_it` | `1 failed` | `1 passed` | yes | yes |
| **S5** | **THE GUARD TEST FILE IS DELETED** | `tests/test_owner_store_isolation.py` | `unlink()` | the gate's own `OWNER_STORE_NODE_IDS` selection | `no tests ran` (pytest exit 4) | `6 passed` | yes | yes |
| **S6** | the **quarantine tool defaults to DESTRUCTIVE** | `tools/quarantine_synthetic_memory.py` | `if not args.apply:` -> `if False:` | `test_quarantine_defaults_to_dry_run_and_never_deletes` | `1 failed` | `1 passed` | yes | yes |
| **S7** | a pytest process can declare itself the owner | `src/parcel_robot/memory_path.py` | drop `if under_pytest(environ): return PURPOSE_TEST` | `test_a_test_process_cannot_declare_itself_the_owner` | `1 failed` | `1 passed` | yes | yes |
| **S8** | a **relative** `PARCEL_MEMORY_PATH` override is accepted (the bug, renamed) | `src/parcel_robot/memory_path.py` | `if override and not candidate.is_absolute():` -> `if False:` | `test_a_relative_override_is_refused` | `1 failed` | `1 passed` | yes | yes |
| **S9** | `MemoryPathRefused` becomes a `ValueError` and is swallowed by a never-kill-a-turn guard | `src/parcel_robot/memory_path.py` | `class MemoryPathRefused(RuntimeError):` -> `(ValueError)` | `test_the_refusal_is_not_swallowed_by_a_never_kill_a_turn_guard` | `1 failed` | `1 passed` | yes | yes |
| **S10** | the owner's launcher stops declaring its purpose (**the owner's own stack breaks**) | `scripts/launch_stack.sh` | delete `export PARCEL_MEMORY_PURPOSE="${PARCEL_MEMORY_PURPOSE:-owner}"` | `test_the_owner_launchers_declare_the_owner_purpose` | `1 failed` | `1 passed` | yes | yes |
| **S11** | the commit gate loses its owner-store entry | `scripts/ci_gate.py` | delete `_pytest_gate("owner-store-isolation", tier, OWNER_STORE_NODE_IDS, timeout=900)` from `run_commit_tier` | `test_ci_gate.py::test_both_tiers_carry_the_tier_coverage_gate_and_the_commit_tier_keeps_every_hard_entry` | `1 failed` | `1 passed` | yes | yes |
| **S12** | `conversation_store.py` bypasses the resolver | `src/parcel_robot/conversation_store.py` | `sqlite3.connect(self.store.path, …)` -> `sqlite3.connect(path, …)`, `self.path = str(path)` | `test_the_conversation_store_obeys_the_same_rules` | `1 failed` | `1 passed` | yes | yes |

`12/12 seeds OK.` Owner store sha256 identical before and after the whole sweep:
`40506fd9…` -> `40506fd9…`, mode restored to `644`.

**All five seeds the card names by name are present:** S1 (relative path silently
accepted), S2 (fail-open on a missing explicit path), S3 (provenance column
dropped), S5 (the guard test deleted), S6 (quarantine defaults to destructive).

### 6.1 Two canaries worth quoting

S2's proves the mutation was genuinely live and that the danger is not
theoretical — with the refusal removed, a fresh interpreter is handed the
owner's real file by name:

```
canary (fresh interpreter, PYTHONDONTWRITEBYTECODE=1):
  ACCEPTED /home/jaewoo-jang/Desktop/Projects/Parcel/parcel_memory.sqlite3
after restore:
  REFUSED owner store
```

S5's is the one that shows why the gate entry had to exist. With the guard file
deleted, the named selection does not fail an assertion — it finds nothing at
all, which is the failure mode a marker-based suite cannot see:

```
canary: guard file exists: False
RED   : no tests ran in 0.06s        (pytest exit 4 -> hard gate red)
```

---

## 7. Deviations from the card, each with its reason

1. **The card's option list was not chosen from; three of the four options were
   combined.** The card offers an env override, a relative-path refusal, a
   `purpose` declaration, or a lock file, "for the executor to weigh and
   justify". Any one alone has a hole: the override alone protects only runs
   that remember it (that is R5's recipe, and it failed four times); the
   relative refusal alone is defeated by an absolute path to the same file; the
   purpose declaration alone is defeated by a fixture exporting it. Rules 1-3
   in §1.1 are all three, plus the pytest override that makes the third
   un-defeatable. The lock/marker-file option was **rejected**: it needs a file
   written next to the owner's store, and this card should not be creating files
   beside their data to protect their data.

2. **`scripts/ci_gate.py` and `tests/test_ci_gate.py` were edited, and they are
   not in the card's OWNS list.** The card's DoD requires a seed for "the guard
   test deleted" to redden, and nothing in the tree could detect a deleted test
   file: `default-suite` just collects fewer tests and stays green. A named
   node-id selection **errors**. Coverage is **gained, not lost** — the required
   hard-entry list in `test_ci_gate.py` goes from 14 to 15 entries, and both
   tiers carry the new one. `assertion-evals` and `tier-coverage` are untouched.

3. **`scripts/launch_sim.sh` was edited as well as `launch_stack.sh`.** The card
   names neither. `README.md:246` and `:292` document `./scripts/launch_sim.sh`
   as a standalone owner command, and it is the script that starts
   `parcel_robot.web_panel` — the process that opens the store. Declaring only
   in `launch_stack.sh` would have made a documented owner launch fail closed on
   the owner. Both use `${PARCEL_MEMORY_PURPOSE:-owner}` so an executor's
   explicit override still wins.

4. **`tests/test_fail_closed_limits.py` was edited and is not in the OWNS list.**
   It is the offender §3 found. Leaving it would have left the gate red.

5. **A twelfth seed and a redesign.** The card asks for ≥8. Twelve were run
   because the guard has more independent failure modes than eight, and one of
   them (S8) came back GREEN on its first attempt and had to be redesigned —
   §7.1.

6. **The owner's store was made read-only (`chmod 0444`) for the duration of each
   seed's mutated test run, and restored immediately.** This changes no bytes and
   is not a content edit; it exists because the first seed sweep proved it
   necessary (§9). No stack was running (`ss -ltnp`: no listener on `:8765`).

7. **The owner-store name sweep was widened to `src/` after the first gate, and
   `memory.py` was dropped from its allowlist.** The first version scanned
   `tests/ scripts/ tools/ evals/` only, which left two dead entries in the
   allowlist and — more to the point — would not have caught a *library* module
   hardcoding the filename. Measured before changing it: of everything under
   `src/`, exactly one file names the store in a code string literal, and it is
   `memory_path.py`, whose job is to know it. `memory.py` mentions it only in
   comments and docstrings, which the AST walk already ignores. The guard got
   strictly stronger; §2's gate is the re-run that certifies it.

8. **An empty `turns.sqlite3` was deleted from the repo root.** My own seed
   created it (§9.5). It was untracked, contained an empty table, and is gone.

### 7.1 One seed came back GREEN, and that is evidence

S8's first attempt deleted the relative-**override** refusal
(`if override and not candidate.is_absolute()`) and
`test_a_relative_override_is_refused` **stayed green**. The reason is a second,
independent guard: under a `test` purpose the general relative-path rule (rule 2)
catches a relative override too. So the mutation was real, the store was still
protected, and the test was proving the wrong thing.

The test was strengthened rather than the seed weakened: it now also asserts the
refusal under an **owner** purpose, which is the only configuration in which the
override rule is the sole guard — and it asserts that the same owner purpose
*without* an override still resolves, so the new assertion is about the override
and not about the purpose. S8 then reddened for the right reason.

---

## 8. `does_not_prove`

* **It does not prove the 256 rows are synthetic.** It proves they are inside two
  windows in which executors were running, that they carry no annotation columns,
  and that 25 distinct strings account for all 256. The owner may have typed
  "go to the lamppost" themselves in that window. **This is exactly why the tool
  defaults to dry-run and moves rather than deletes, and why the owner decides.**
* **It does not attribute rows to specific cards.** No `writer` column existed
  when they were written, so R24-vs-R26-vs-PG1/2/3 attribution is not available
  from the data. The corrections in §5 therefore state what is measurable (the
  gate's open, six times for R26) and do **not** claim which card appended which
  rows. That is what work item 2 fixes going forward, not backwards.
* **It does not prove the guard holds against a determined caller.** Anyone can
  `export PARCEL_MEMORY_PURPOSE=owner` in a shell and write to the file. The
  claim is about *accidents* — the CWD trap, the imported runtime, the forgotten
  fixture — not about a sandbox.
* **The `sqlite3.connect` sweep in the guard test covers four modules, not 7,686
  tests.** The full sweep is a five-minute job and was run twice by hand (§3, and
  again as the final suite run); the committed one is the part that fits a commit
  gate. A new offender in an uncovered module is caught by the *resolver* (loudly,
  at construction) rather than by the sweep.
* **No live model, no hosted spend, no `:8765` contact.** `$0.00`. The owner's
  stack was not running at any point (`ss -ltnp` showed no listener); nothing was
  POSTed and nothing was restarted.
* **`--apply` has never run against the owner's store.** It ran against two
  byte-copies. The real store's `messages` table still holds all 3,138 rows.

---

## 9. THE IRONY CLAUSE — my own proof changed the owner's store

**Recorded before I started:**
`7da58192b0442e095d6d1912716a6263443f5d228516269f6fea940d9b16b374`
**Recorded after I finished:**
`40506fd96fc61c341d64d44cb607ec206fd547c03b223fbe91134ab5c2db4aa8`

**They differ. Reporting it, per the card.**

### 9.1 What happened

Seed **S2** removes the owner-store refusal from `memory_path.py` and then runs
the guard tests. Those tests prove unreachability *by attempting to reach* — one
of them spawns a subprocess that builds a real runtime from `configs/robot.yaml`.
With the refusal mutated away, the attempt **succeeded**, and R27's own additive
migration ran against the owner's real database.

The shipped code is not implicated. The harness was.

### 9.2 Exactly what changed, measured against my byte-exact snapshot

```
snapshot cols: [id, role, content, created_at, session_id, speaker, origin, provider_item_id]
live     cols: [id, role, content, created_at, session_id, speaker, origin, provider_item_id, writer]
snapshot rows: 3138
live     rows: 3138
live max id  : (3138, '2026-08-21 13:48:52')
live tables  : [('messages',)]
row-for-row identical on all pre-R27 columns: True
writer values present: [(None, 3138)]
file size: 253952 bytes, unchanged
```

**Zero rows added, zero removed, zero altered.** The entire delta is one nullable
column, `writer TEXT`, NULL on all 3,138 rows — the same `ALTER TABLE` the
owner's own stack performs on its next launch. No `quarantined_messages` table
was created; the store still has exactly one table.

### 9.3 What I did about it, and what I deliberately did not

**Fixed:** the harness now `chmod 0444`s the owner's store for the duration of
each seed's mutated run and restores the mode in the same `finally` as the source
file. `chmod` changes no bytes, so the sha256 identity checks still mean what
they say. The final sweep in §6 ran under that protection.

**Deliberately not done: I did not overwrite the owner's database to make the
hash match.** A byte-exact snapshot exists and the restore is one `cp`. I did not
run it, for two reasons. First, the card's MUST-NOT list is precisely "the
owner's `parcel_memory.sqlite3` in destructive mode", and a full-file overwrite
of a live conversation database is a strictly larger action than the additive
column it would undo. Second, restoring a cosmetic hash while carrying a real
risk to their data is the *same instinct* that produced this incident — making
the record look clean rather than making it true.

**Owner-gated:** if you want the byte-exact original back, it is
`scratchpad/r27/owner_store_snapshot.sqlite3`, sha256 `7da58192…`, and it is
session-scoped scratch that will be cleaned. The column is harmless and your next
launch would add it anyway; my recommendation is to leave it.

### 9.4 The check that would have caught the earlier chains

Every seed now records the owner store's sha256 before and after **itself**, so
the harness reports `owner store safe: False` inline instead of the executor
discovering it from a total at the end. That is how S2 was caught — the first
sweep printed it on the seed that caused it, and the seed that caused it is the
one named above.

---

### 9.5 A second artifact my own seeds left in the owner's repo, also self-caught

`turns.sqlite3`, 24,576 bytes, **0 rows**, at the repo root, timestamped 10:31 —
inside my first seed sweep. Seed **S12** makes
`SqliteConversationStore.__init__` connect to the raw `path` instead of the
resolved one, and the guard test then calls
`SqliteConversationStore("turns.sqlite3")` expecting a refusal. With the
resolver bypassed the call succeeds and SQLite creates the file where the
relative name points — the repo root. That is the defect this card is about,
reproduced in miniature by the seed that proves the defect is fixed.

It contains an empty `conversation_turns` table and nothing else.

It came back **twice** — once per seed sweep — which is the part worth recording,
because deleting it and moving on would have left a trap that re-arms every time
anybody runs the harness. The harness now sweeps repo-root `*.sqlite3*` files
after every seed and deletes anything that is not `parcel_memory.sqlite3`
(the owner's store is excluded by name: the sweep removes strays, never data).
Verified by re-running S12 alone — `1/1 seeds OK`, no stray left behind.

The commit gate in §2 was then re-run on the cleaned tree, which is why there
are three gate runs in this card's scratch and only the last one is pasted. The
`chmod` protection in §9.3 covers `parcel_memory.sqlite3` only; this sweep is
the general form of the same idea, and a future harness should keep both.

---

## 10. Open risks and handoffs

1. **The 256 rows are still in the store, and `recall` still reads them.** This
   card built the tool and refused to pull the trigger. Until the owner runs
   `--apply`, `recall("lamppost")` still returns *"find the nearest lamppost"* as
   something they said. **Owner decision, highest.**
2. **`PARCEL_MEMORY_PURPOSE=owner` is a shell variable and it is inheritable.** A
   terminal in which the owner once launched the stack, and from which an
   executor later runs a script, confers owner rights. Under pytest that is
   nullified; outside pytest it is not. A stronger form (a marker file the
   launcher writes and removes, or a pid check) was rejected as out of scope but
   is the obvious next hardening.
3. **`writer` is stamped, but nothing reads it yet.** `recall`, `recent` and
   `realtime_turns` all ignore it. A follow-up should let `recall` prefer
   `writer IS NULL OR writer = 'owner_stack'` so a stray row cannot be spoken
   even before it is quarantined — that is a product change and wants its own card.
4. **The owner must relaunch to pick this up.** Not hot-reloadable. The next
   `scripts/launch_stack.sh` will add the `writer` column (already added, §9.2)
   and start stamping `owner_stack`.
5. **`evals/companion/personal_convo_v1/build_memory_fixture.py` takes a path
   argument** and is now subject to the resolver. It is not in the commit tier
   and was not exercised live; if it is ever run with a relative path it will
   refuse with the standard message. Named here so it is not a surprise.
6. **The `sqlite3.connect` sweep is module-scoped** (§8). Widening it to the whole
   suite costs five minutes and belongs in the nightly, not the commit tier.

---

## 11. Definition of done

| DoD clause | Status | Evidence |
| --- | --- | --- |
| Gate green | **met** | §2 — every hard gate PASS, exit 0, run last |
| ≥8 seeds RED | **met** | §6 — twelve, including all five the card names |
| relative path silently accepted | **met** | S1 |
| fail-open on a missing explicit path | **met** | S2 |
| provenance column dropped | **met** | S3 (and S4, the stamp) |
| the guard test deleted | **met** | S5 |
| quarantine defaults to destructive | **met** | S6 |
| demonstration that a default-config in-process runtime from the repo root cannot reach the store | **met** | §3.2, kept executable as a test |
| dry-run quarantine report over the real store (read-only) | **met** | §4 |
| `R27_STATUS.md` standard register | **met** | this document |
