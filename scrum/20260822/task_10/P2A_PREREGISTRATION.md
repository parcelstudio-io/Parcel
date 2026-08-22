# P2-A — pre-registered memory-probe family (owner session 3)

**Written BEFORE any probe was executed.** Card: `README.md` work item 6.
Executor: Claude Opus · Verifier: Fable · Date: 2026-08-22.

Everything below is fixed before the first measurement. A row that does not
pass is reported as a MISS, not re-specified. Any change to a row after this
file is written is a **declared deviation** in `P2A_STATUS.md` with the reason
and the timestamp.

## Rules

* **Store.** Every probe runs on a **scratch** store created under
  `/home/jaewoo-jang/.cache/parcel-p2a/`, addressed by an absolute
  `PARCEL_MEMORY_PATH`. The owner's live `parcel_memory.sqlite3` is opened
  **read-only or not at all**; its sha256 is recorded before and after the card.
* **pass^k.** Rows marked `pass^3` must pass on **three independent runs** with
  three different scratch stores. One failure in three is a MISS for the row.
* **"Through the real lane"** means `RealtimeLane` driving a fake transport
  (the repo's existing realtime test rig), the real `RealtimeToolBroker`, the
  real `ConversationMemory`, and the real `DeveloperContext` render — not a
  hand-built dict.
* **Misses are misses.** A row that needs a live hosted session to be honest is
  declared OWNER-GATED up front (rows 10–11) and is NOT counted as passed.

## The family

| # | Probe | Measured how | Pass criterion | k |
|---|---|---|---|---|
| 1 | **The sister's name survives a restart.** Owner says "my sister's name is Hana" in session A; session B is a *fresh lane on the same store*. | Session A: `remember_fact` is called and the store gains one row. Session B: the row renders into the DI `owner_notes` block at session open, and `remember_fact(action=list)` returns it. | fact row present after re-open with `consent=granted`; the string `Hana` appears in the session-B DI text | pass^3 |
| 2 | **A stated preference is recalled unprompted next session.** "I like short answers before coffee." | The distiller (not the tool) proposes it from the session's turns; the policy admits it as `preference`; it renders in `owner_notes` at the next session open with nothing asked for. | a `preference` fact exists with provenance `model_proposed` and appears in the next session's DI | pass^3 |
| 3 | **"Don't remember that" is honored.** | `remember_fact(action=forget)` on a stored fact. | the row is **soft-deleted** (still on disk, `deleted_at` set), stops rendering in `owner_notes`, and stops appearing in the `list` answer | pass^3 |
| 4 | **What-do-you-know lists only consented facts.** | Store three facts: granted, pending, denied. Ask `remember_fact(action=list)`. | exactly the granted fact is returned; pending and denied never appear in the answer **or** in `owner_notes` | pass^3 |
| 5 | **The dog says what it will not store.** A health fact ("my blood pressure medication is …"). | `remember_fact(action=remember)` on a `health` category fact. | result status is `consent_required`, `stored` is False for the *rendered* set, the row is written with `consent=pending`, and the detail names the category so the model can say it aloud | pass^3 |
| 6 | **The dog confirms aloud what it stored.** | Any admitted `remember_fact`. | the result carries `answer: true` (so the lane must speak it) and a `detail` that contains the stored value | pass^3 |
| 7 | **The distiller refuses an un-quarantined synthetic range.** | A scratch store seeded with rows in ids 2883–3138 carrying the R27 window timestamps and no owner-stack writer stamp. | `distill_session` / `assert_store_is_distillable` raises `SyntheticRowsUnquarantined`, names the count and the id range, and writes **no** `owner_facts` row | pass^3 |
| 8 | **Quarantine clears the refusal.** Same store after the rows are moved to `quarantined_messages`. | the guard passes and distillation proceeds | pass^3 |
| 9 | **Full-ledger replay at session open.** A store with legacy (`add`) rows AND hosted (`write_realtime_turn`) rows, including one duplicate pair. | `_inject_tail` replays **both** lanes, deduped (the duplicate appears once), capped at the stated ceiling, oldest-first. Not the 20-row hosted-only tail. | injected item count and order match the expected list exactly; `tail_items_deduped >= 1` | pass^3 |
| 10 | **A real hosted session stores a fact the model chose to store.** | OWNER-GATED — needs one live `gpt-realtime` session. | — | **declared MISS unless run** |
| 11 | **The owner's real store distils real facts.** | OWNER-GATED — blocked on `tools/quarantine_synthetic_memory.py --apply`, which is the owner's action. | — | **declared MISS unless run** |
| 12 | **The owner's store is byte-unchanged.** | sha256 before the first edit and after the last command of the card. | identical | k=1 |

## Seeded-RED rows (guards that must fail before the code exists)

| Guard | Seed |
|---|---|
| synthetic-range refusal (row 7) | run the same probe against a tree where `assert_store_is_distillable` is a no-op; the distiller must then write facts derived from "go to the lamppost" — that is the RED |
| consent bypass (rows 4, 5) | run the same probes against a renderer/lister that ignores the `consent` column; pending/denied facts must then appear — that is the RED |

## What this family deliberately does not claim

* It does not prove a hosted model *chooses* to call `remember_fact` at the
  right moment. That is row 10 and it is owner-gated.
* It does not prove the LM distiller's *taste*. The deterministic policy is
  proven; the proposals come from an injected model and are only as good as it
  is. The offline default is a deterministic extractor, so the CI rows measure
  the mechanism, not the model.
* It does not prove anything about the owner's real 2,618 legacy rows. Nothing
  in this card reads them for distillation, by construction (row 7).
