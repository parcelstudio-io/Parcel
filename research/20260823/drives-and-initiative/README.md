# H3 — drives and initiative

`DESIGN.md` is the contract (Fable). `RESULTS.md` is the measurement (Opus).

```
arena.py       the venue: HeadlessCityWorld + DynamicCity agents, the drive
               model, the existing admission doors, the executors, the
               per-tick JSONL
run_h3.py      four arms x 3 seeds x 60 simulated minutes + the night and
               D5-probe configurations; writes results/{runs,rows}.json
verify_log.py  re-derives D5/D6/D8 from the per-tick log
results/       raw run summaries and the pre-registered table
logs/          one full per-tick log, gzipped: the Stage-B corpus shape
```

Reproduce:

```
env -u TMPDIR .parcel/bin/python research/20260823/drives-and-initiative/run_h3.py \
    --duration-s 3600 --workers 6
```

Product seams this experiment added (both flag-off / default-preserving):
`src/parcel_robot/attention/drives.py`, `src/parcel_robot/patrol/coverage.py`.
Capability test: `tests/test_h3_drives.py`.
