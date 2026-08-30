# LIT-1 — the well-instrumented loop (sim + runtime + Model B + Realtime voice)

Read `DESIGN.md` (Fable's pre-registration) and `AMENDMENTS.md` (PRE-RUN and
BINDING; where they conflict with DESIGN.md they win) before this file.
`RESULTS.md` carries the measurements. There is no verdict here — Fable writes
`VERDICT.md`.

## What runs

One process per episode:

```
MuJoCo static city  ──sim, unique short socket, systemd-run --scope MemoryMax=12G
        │
        ▼
RobotRuntime        ──built the tests/test_voice_nav_e2e.py::_LiveRuntime way
        │                (PARCEL_MEMORY_PATH → scratch, commissioned config)
        ├── handle_text ............ THE ONLY MOTION AUTHORITY (amendment L6)
        ├── TaskExecutive .......... tapped per-instance for verbatim receipts
        └── _last_sent ............. body-lane velocity, sampled at 20 Hz
        │
        ▼
Model B (LIT-1's own, labelled)
        ├── plan queue ............. the wave's shared record schema
        └── PlanQueueWhisper ....... ONE tail conversation item, own purpose tag,
                                     replace-not-append, no response.create
        │
        ▼
RealtimeLane        ──the product's lane; transport is either
        ├── fake ................... FakeRealtimeServer, scripted turns
        └── hosted ................. the live lane via runtime.submit_realtime_text
        │
        ▼
one JSONL           ──every hop, monotonic t, provenance column
        │
        ▼
replay.py           ──self-contained HTML: speech and movement on one axis
```

**One authority per utterance.** Every hosted motion door is wrapped by
`runtime._gate_by_voice` and refuses without a voice-identity binding, so in
*every* tier the body is moved by `handle_text` and the voice lane receives the
same sentence for narration only. Any hosted `navigate_to` refusal is logged as
its own JSONL row rather than worked around.

## Files

| file | what it is |
|---|---|
| `sim_loop.py` | the loop: sim + runtime + receipt tap + motion instrument + Model B + a voice lane + the JSONL writer. `--smoke` runs the single-hop build step. |
| `run.py` | the runner: pins the environment once, runs N episodes, writes `results.json`, proves teardown with `pgrep`. |
| `replay.py` | JSONL → one self-contained HTML timeline (no external assets). |
| `scenarios/door_sofa_keys.json` | the scenario of record + 6 variants, the alias table, the pre-registered receipt-KIND sequences and the expected honest keys response. |
| `sample_run.txt` | the recorded first build step: sim + runtime + one `handle_text` hop with its receipt timeline. |
| `artifacts/` | the recorded JSONL and HTML for one fake run (and the hosted run, when the governor admits one). |
| `results.json` | machine-readable: every run, every receipt sequence, the latency percentiles, the ledger totals. |

## Reproduce

Environment: `TMPDIR` unset; everything else `run.py` pins for you.

```bash
cd /home/jaewoo-jang/Desktop/Projects/Parcel
unset TMPDIR

# build step 1 — sim + runtime + one handle_text hop, receipts printed
.parcel/bin/python research/20260829/sim-loop-1/sim_loop.py --smoke

# H-LIT1a — the deterministic tier, 5 seeded runs of the scenario of record
.parcel/bin/python research/20260829/sim-loop-1/run.py \
    --scenario door_sofa_keys --voice fake --seed 20260829 --runs 5

# one variant (blocked_route | unreachable_clarify | queue_phrasing |
#              sound_event | no_op | amend_clean)
.parcel/bin/python research/20260829/sim-loop-1/run.py \
    --scenario door_sofa_keys --variant amend_clean --voice fake \
    --seed 20260829 --runs 1 --index 20 --merge

# H-LIT1b — the hosted tier (refuses and records UNMEASURED with no credential)
.parcel/bin/python research/20260829/sim-loop-1/run.py \
    --scenario door_sofa_keys --voice hosted --runs 3 --merge

# the replay
.parcel/bin/python research/20260829/sim-loop-1/replay.py \
    research/20260829/sim-loop-1/artifacts/<file>.jsonl --html out.html
```

Each episode takes roughly 90–150 s of wall clock (two navigation legs plus the
scripted speech and the 10 s post-cue observation window).

## Host and safety rules this code keeps

* **Sockets.** Every sim gets its own short socket under
  `~/.cache/parcel-0e/lit1/`. `/tmp/parcel_sim.sock` is refused by name at
  preflight and the run aborts if it is ever seen.
* **Teardown (amendment L3).** The sim leads its own process group
  (`start_new_session=True`) under `systemd-run --user --scope -p MemoryMax=12G
  -p MemorySwapMax=0`; the group is signalled on every exit path and a `pgrep`
  proof is written into the JSONL (`teardown`) and into `results.json`
  (`teardown_proof`). Peers' sims are listed and never touched.
* **Memory.** `PARCEL_MEMORY_PATH` points at this experiment's own cache dir and
  `PARCEL_MEMORY_PURPOSE` is removed; `parcel_memory.sqlite3` is never opened.
* **Names (amendment L4).** The name scan is a POSITIVE allowlist — the
  scenario's stand-ins plus the demo city's own landmark vocabulary. A negative
  blocklist would have to contain the held-out scene's name in order to look for
  it, which is the leak it is meant to prevent. Anything place-shaped and not on
  the allowlist is redacted in place and counted in `name_scan_leaks`.
* **No hardware.** Nothing opens `/dev/bus/usb`; no VLM is called from a runtime
  callback; no audio device is opened (`mode: text`, a discard sink).
* **Money.** Hosted turns go only through `runtime.submit_realtime_text`
  (`CLASS_ROUTINE`), the governor snapshot is printed before any of them, and
  `run.py` refuses to start another hosted episode once the shared wave ledger
  reaches LIT-1's $2.00 sub-cap. A governor refusal is recorded as UNMEASURED
  and never worked around. Credentials are checked for PRESENCE only and never
  read, printed or passed on.
* **No product edits, no git writes.** The executive receipt tap rebinds methods
  on the runtime instance this process built and removes them on `detach`;
  nothing under `src/`, `tests/`, `evals/` or `configs/` is touched.

## Borrowed work

`sim_loop.py` imports two peer modules BY PATH and records which one actually
ran in every JSONL header (`providers`) and in `RESULTS.md`:

* `research/20260829/nav-interrupt-1/harness.py` — `LiveSession` (the
  `_LiveRuntime` pattern under `systemd-run`), `wait_for_trigger`,
  `wait_terminal`, `score_arrival`, `GOALS`, `DERIVED_LANDMARKS`. One sim
  launcher with one teardown is safer than two, so LIT-1 refuses to run if this
  module is absent rather than hand-rolling a second one.
* `research/20260829/model-b-narration-1/steer.py` — its `steer()` verdict is
  recorded beside LIT-1's own decision on every voice-only utterance. LIT-1's
  own minimal confirm→re-issue rule stays the AUTHORITY, because amendment L7 is
  binding on this experiment and fixes the semantics ("yes" resumes nothing by
  itself; the re-issue is a harness re-issue of the remembered directive text).

`tests/test_voice_nav_e2e.py` is read, never imported: the HY-1 teardown guard
and the fixture pattern are reproduced in the peer harness verbatim.
