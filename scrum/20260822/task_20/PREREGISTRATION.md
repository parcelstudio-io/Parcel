# GATE-0 — pre-registered acceptance rows (fixed 2026-08-22, BEFORE measuring)

Fixed before any number below was produced. Every row is met/missed in
`GATE0_STATUS.md`; a missed row is reported as a miss, not renegotiated.

| # | Row | Threshold |
|---|---|---|
| R1 | vendored pack size + closure | exactly **20** files exposed under `third_party/` by the `.gitignore` carve-out; **0** `.git` metadata paths; total **<= 30 MB** |
| R2 | provenance pins the revision | `PROVENANCE.json.upstream_revision == ae6a8403e272733e9996ef59990880330496177f`; every payload's recorded `sha256` + `size_bytes` matches the file on disk (20/20 incl. its own two non-payload entries excluded) |
| R3 | `unitree-assets` is a hard stage before `hard-safety` | present in `run_commit_tier` at index < the `hard-safety` index; `status == "pass"` on the intact tree; compiles `city_block.xml` **and** `city_block_b.xml` (geometry only) |
| R4 | seeded RED, asset pack (5 seeds) | each of {removed OBJ, tampered OBJ byte, wrong `upstream_revision`, unmanifested extra file, `..`/absolute manifest path} yields a **named hard-red `unitree-assets` GateResult**, never a traceback |
| R5 | containment | with the FIRST evaluator raising, `run_commit_tier()` still returns **one GateResult per declared stage** and `--json` emits valid JSON with every stage named; the raising stage is `status == "error"` with a bounded traceback tail; `KeyboardInterrupt` still propagates |
| R6 | ruff is pinned and stamped | dev extra pins `ruff==0.16.1`; `scripts/ci_ruff_baseline.json` carries `ruff_version == "0.16.1"`; `evaluate_ruff` returns `error` (not pass) when the running ruff's version differs from the stamp; fingerprint count stays **exactly 7**; `scrum/20260822/task_9/evidence/*.py` lints clean |
| R7 | CPython 3.11 imports the protocol | `RetainedEvent.fields` via `default_factory`; two default instances have **distinct**, immutable, empty mappings; `python3.11 -c "import parcel_robot.realtime.protocol"` exits **0** (it exits 1 with `ValueError: mutable default <class 'mappingproxy'>` today) |
| R8 | hosted runner GL | both `ci.yml` jobs set `MUJOCO_GL: osmesa` |
| R9 | clean clone | a **tracked-only** clone (20 asset files, no developer cache, fresh venv, `pip install -e ".[dev,voice]"`) runs `ci_gate.py --tier commit --json` to a **JSON summary (red or green) with no traceback**; both product scenes compile in **< 1 s** each |
| R10 | held-out seat | `tests/test_unitree_asset_pack.py` seated in `ALLOWED` with a reason and added to the load-pair; `tests/test_held_out_scene.py` green |
| R11 | OWNS hygiene | targeted `pytest` green on the owned test modules; `ruff check` clean on every owned path; ratchet still 7 |

Notes fixed in advance:
* R5's "one GateResult per declared stage" is **ten** after this card (nine
  today + `unitree-assets`). The card text says nine; that is the pre-`unitree-assets`
  count and is recorded here as the reconciliation.
* R9 is executed against a scratch clone under `/home/jaewoo-jang/.cache/parcel-gate0/`.
  Git is read-only in the project tree, so the pack cannot be `git add`ed here;
  the scratch clone is committed **inside the cache directory only** and then
  re-cloned, so "tracked-only" is real. Declared as a deviation.
