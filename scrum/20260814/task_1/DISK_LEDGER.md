# Disk ledger — run-specific operator figures (2026-08-14, card S-1)

> ## ⚠ GENERATED FILE — do not hand-edit
>
> Every number below is rendered by
> `tests/test_disk_ledger_doc.py::render_disk_ledger()` from
> `scripts/parcel_capture/budget.py`'s current model. Hand-editing is a
> defect: `tests/test_disk_ledger_doc.py` reddens until it is reverted.
>
> ```
> .parcel/bin/python -m tests.test_disk_ledger_doc --emit    # regenerate
> ```

**Plan of record:** `848x480@30 CDI` · **91.87 MiB/s** · 322.98 GiB/hour · 96.3 MB/s
**Recorder-ceiling verdict:** THIN (×1.14 against the low field-report reading) — a model, not a measurement of this Orin.

## 1. What one minute costs

| | rate |
|---|---:|
| per second | 91.87 MiB |
| per minute | 5.383 GiB |
| per hour | 322.98 GiB |

## 2. Reserve before a take (recorder margin ×1.15 included)

| take length | free space required |
|---|---:|
| 10 min | 62.0 GiB |
| 20 min | 123.9 GiB |
| 30 min | 185.8 GiB |
| 60 min | 371.5 GiB |

A take may start only when the record target's measured free space covers
the row for its planned length. The margin is the same 15% the recorder's
own `SpaceBudget` refuses under, so a take this table clears is a take the
recorder will agree to start.

## 3. What the free space you actually have buys

| free on record target | recording time |
|---|---:|
| 256 GiB | 41.4 min |
| 512 GiB | 82.7 min |
| 1024 GiB | 165.4 min |
| 2048 GiB | 330.8 min |

## 4. Supersession notice — the 84.60-era arithmetic is history

The 20260813 status pack derived operator figures from the superseded
**84.60 MiB/s** model (`PSK_STATUS.md` M9: 4.957 GiB/min, ≈425 GiB free for the whole script, ≈45 min at 256 GiB; `PSL_STATUS.md` repeats the same base rate).
Those figures are ~8.6% low: the free-space requirement is understated and a take sized by them
would truncate. **Nothing operator-facing may derive from them.** The
historical sheets stay as provenance (working agreement 3); THIS ledger is
the run-use replacement, and its pin fails if it drifts from the model.

## 5. What this ledger does not know

- The Orin's actual free space — unmeasured until H-1/H-2 (`df -h` on the
  record target is the day's first evidence).
- Whether the recorder sustains this rate on the Orin — the rate is a
  model; `TONIGHT_CHECKLIST.md` N3 (fio tail) and N4 (real `ros2 bag
  record` for ten minutes) are the measurements, and neither has run.
- Anything about a profile other than the plan of record; re-render after
  any budget-model change.

