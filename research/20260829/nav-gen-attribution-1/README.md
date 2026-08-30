# NAV-GEN-1 — why does the shipped navigator fail on generated geometry?

`DESIGN.md` is Fable's, FROZEN, and pre-registers H-NG1a / H-NG1b / H-NG1c.
`RESULTS.md` is this executor's record; `results.json` carries every number in
it. **No verdict is drawn here** — `VERDICT.md` is Fable's.

Evidence tier: **`desktop-sim`** (headless city on real generated MJCF variants
from `evals.nav_instruct.scene_gen.build_scene`, plus the frozen demo block as
a control). Physical motion: **NO-GO**, unchanged. CPU only; no GPU, no
sockets, no subprocess simulator, no hosted call, **$0**.

## Files

| file | what it is |
|---|---|
| `episodes.py` | the episode set, MA-1's scene recipe (imported by path, read-only), goal geometry, DTG / band predicates, per-scene obstacle density |
| `run.py` | the arms (the clearance sweep), the per-arm navigation config trees, the episode driver, determinism check |
| `analyze.py` | every table in `RESULTS.md`, written to `results.json` |
| `plumbing_check.py` | reads the inflation off the LIVE `DirectiveNavigator` per arm — the evidence behind `RESULTS.md` 2.1 |
| `RESULTS.md` | what was run, the numbers, each DESIGN bar quoted and met / not met |
| `results.json` | machine-readable rows behind `RESULTS.md` |
| `tables.md` | the RESULTS tables as `analyze.py` renders them — no number in `RESULTS.md` is typed by hand (re-established under card C7: the false-arrival DTG distribution, the frozen-block aggregate and the host/worker provenance are rendered in 5.4 / 6.2 / 8.1) |

Raw per-episode rows and the scene manifest live in this executor's scratch
(`~/.cache/parcel-0e/ng1/raw/`), not in the repo.

## Reproduce

```bash
cd /home/jaewoo-jang/Desktop/Projects/Parcel

# 1. build + hash the 30 generated scenes and their generator params
env -u TMPDIR OPENBLAS_NUM_THREADS=32 .parcel/bin/python \
  research/20260829/nav-gen-attribution-1/run.py --stage prepare

# 2. the headline run: sweep A (6 arms x 530 episodes) + sweep B (4 arms x 450)
#    + the A0 repeat that proves determinism. Wall on this host: 530.4 s
#    (sweep A) + 236.6 s (sweep B); pick --workers for the free thread budget
#    (the recorded run's count was never written down -- see RESULTS.md 0).
env -u TMPDIR OPENBLAS_NUM_THREADS=32 .parcel/bin/python \
  research/20260829/nav-gen-attribution-1/run.py --all --seed 20260829 \
  --workers 40 --determinism

#    (the two sweeps can also be run separately: --sweep A / --sweep B; that is
#     how they were run here, so index.json for sweep A is kept as
#     raw/index_sweepA.json and analyze.py merges the two)

# 3. the tables
env -u TMPDIR .parcel/bin/python \
  research/20260829/nav-gen-attribution-1/analyze.py
```

`--stage facts` alone prints the exact planner inflation each arm resolves to
without running an episode — both the config-only reading and the LIVE one the
`DirectiveNavigator` actually commissions (they differ; see `RESULTS.md` 2.1).

## Arms

| sweep | key moved | arms | live planner inflation |
|---|---|---|---|
| A | `configs/navigation/models/grid.yaml` `controller.map_safety_margin_m` | A0 (commissioned, repo file), A0c (scratch copy, plumbing control), A1 0.07, A2 0.05, A3 0.02, A4 0.00 | 1.0223 m throughout — this key is swallowed by the gate term |
| B | `configs/navigation/default.yaml` `safety.stop_distance_m` | B1 0.65, B2 0.50, B3 0.40, B4 0.32 | 0.8854 / 0.7485 / 0.6572 / 0.5842 m |

`configs/robot.yaml` `safety.obstacle_stop_m` 0.65 and `obstacle_slow_m` 1.2 —
the reactive-safety stop/slow bands — are held fixed in every arm and asserted
inside each work unit.

## Host discipline

`TMPDIR` unset; workers pinned to one BLAS thread each (`--workers N` costs N
threads; keep N under the 48-thread ceiling when a peer session shares the
host); `run.py` records the count it ran with in `raw/index.json` ->
`run_provenance` and `analyze.py` renders it, because the recorded sweeps left
it unrecorded and three different values were typed into the prose (card C7);
a foreign session shares this host, so
`uptime` and `nvidia-smi` are recorded at start and end of the run in
`results.json`. Nothing under `src/`, `evals/`, `configs/`, `tests/` or any
other research folder is written; `git` is read-only; the owner's `:8080` /
`:8765` / `/tmp/parcel_sim.sock` and `parcel_memory.sqlite3` are never touched
(`PARCEL_MEMORY_PATH` points into this scratch). The NAV evals' held-out scene
is never loaded and never named; no frozen episode set is touched.
