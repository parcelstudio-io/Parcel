# Task 9 — R27: the owner's memory is not a scratch file (SAFETY OF THE RECORD)

**Executor:** Claude Opus (agent) · **Auditor:** Fable (deferred)
**Trigger:** measured, not suspected. **182 synthetic rows** written into the
owner's live `parcel_memory.sqlite3` between 2026-08-20 21:12 and 2026-08-21
11:05 by executor test runs — against only **264 genuine owner rows** in the
whole store. Two status docs (R24 §4.5, R26 §11) assert the store was
untouched; the verifier caught it and the auditor confirmed it directly.
**It is user-visible:** R18 made `recall` read both origins, so
`recall("lamppost")` now returns *"find the nearest lamppost"* — the robot can
"remember" a conversation the owner never had.

**Root cause is a KNOWN, PREVIOUSLY-FLAGGED risk that was never built:** R5
open risk 5 — "`memory.path` is resolved relative to the process CWD, so any
two stacks launched from the repo share one conversation memory... a
`PARCEL_MEMORY_PATH` override would make live proofs repeatable." Every
executor that started an in-process runtime from the repo root with a default
config silently adopted the owner's store, then reported isolation in good
faith because it never checked.

## Work

1. **Make it structurally impossible, not a convention.** A process that is
   not the owner's stack must not be able to open the owner's store for
   writing by accident. Options for the executor to weigh and justify:
   an explicit `PARCEL_MEMORY_PATH` env override; refusing a relative
   `memory.path` unless a flag says the caller means it; a required
   `purpose: owner|test` declaration on the store; or a lock/marker file the
   owner's stack owns. Whatever is chosen must fail CLOSED — a test run with
   no explicit path gets a temp store or an error, never the owner's file.
2. **Make it self-reporting:** the store records, per row, which process
   class wrote it, so pollution is detectable after the fact rather than
   inferred from NULL speakers. Backfill is not required; new rows must
   carry it.
3. **A guard test that reddens** if any test or harness can reach the
   repo-root store — the property, not the instance.
4. **Quarantine tooling, NOT deletion.** The owner's data is theirs: provide
   `tools/quarantine_synthetic_memory.py --dry-run` that identifies the
   suspect rows (NULL speaker AND NULL origin AND inside the named windows),
   reports exactly what it would move, and — only with an explicit flag —
   moves them to a side table rather than deleting. **The executor must NOT
   run the destructive mode against the owner's store.** The owner decides.
5. **Correct the record:** append a dated correction to R24_STATUS.md §4.5
   and R26_STATUS.md §11 stating the isolation claim was false and why.
   Do not rewrite history; append.

OWNS: `memory.py` / `conversation_store.py` path resolution and provenance,
the guard test, `tools/quarantine_synthetic_memory.py`, the two status-doc
corrections, `R27_STATUS.md`.
MUST NOT TOUCH: the owner's `parcel_memory.sqlite3` in destructive mode (read
and dry-run only), `realtime/*` behaviour, yield policy, configs.
Standard house rules — and note the irony: **your own live proof must not
write to the owner's store.** Prove your isolation before you claim it.

## Definition of done

Gate green; ≥8 seeds RED (relative path silently accepted; fail-open on a
missing explicit path; provenance column dropped; the guard test deleted;
quarantine defaults to destructive). Evidence: a demonstration that a
default-config in-process runtime started from the repo root now CANNOT
reach the owner's store, plus the dry-run quarantine report over the real
store (read-only). `R27_STATUS.md` standard register.
