# `evals/nightly/` — the nightly's recorded runs

Written by [`scripts/run_nightly.py`](../../scripts/run_nightly.py) (card R26,
`scrum/20260821/task_5`). One dated folder per run, plus one append-only ledger.

```
evals/nightly/
  ledger.jsonl              one row per run: stamp, verdict, exit code, red stages, git head + dirty flag
  <YYYYMMDD>T<HHMMSS>Z/
    results.json            every stage with status/detail/extras, the verdict, the environment
    README.md               the same for a human, INCLUDING what went red
    gate.txt                ci_gate's own summarize() output, verbatim
```

## Why this directory exists

The nightly tier has existed in `scripts/ci_gate.py` since 2026-08-09 and
`.github/workflows/ci.yml` has declared an 08:00 UTC cron for it since. The
2026-08-20 full audit (`scrum/20260820/AUDIT_FULL_FABLE.md` §Tests) established
that **it had never produced a recorded run anywhere** — which meant the 42 tests
the commit tier deselects, the entire voice-to-nav end-to-end tier among them,
had never been executed by any gate in this project's history.

The gate was not broken. It printed to a terminal and exited, and terminal
scrollback is not evidence. `ledger.jsonl` is the file that answers "has the
nightly ever run, and when, and what did it say" without asking a human.

## Reading a run

`verdict` is `PASS` only when every **hard** stage is green. Report-only stages
(EV-1's judge and review queue, the metamorphic differential) are printed and
never change the exit code — that is EV-1's measured decision, not laziness: the
judge produced 2 hard false positives per run on human-PASSED behaviours.

**A red run still writes its folder.** That is deliberate and seeded
(`tests/test_nightly_runner.py::test_a_red_run_still_leaves_its_evidence_behind`):
a nightly that only publishes its greens is a press release.

## Running it

```bash
.parcel/bin/python scripts/run_nightly.py               # no hosted spend
.parcel/bin/python scripts/run_nightly.py --judge       # + EV-1's judge (capped)
```

Exit code is the gate's. `--allow-red` exists solely so a test can prove the
default does **not** swallow a failure; CI never passes it, and
`tests/test_nightly_runner.py` asserts that.

Tier map and what each tier covers: [`docs/CI.md`](../../docs/CI.md).
