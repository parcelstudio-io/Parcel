# Executor preamble — research/20260823 (read before your DESIGN.md)

You are an Opus executor for ONE hypothesis folder under
`research/20260823/<hypothesis>/`. Read, in order: `research/README.md`,
`research/20260823/README.md`, your folder's `DESIGN.md` (the contract —
its pre-registered criteria may not be moved), `CLAUDE.md`, and
`CODEBASE_INDEX.md` selectively (`grep -n '^## \|^### '`, then `sed -n`).
The tree is at the DEC-FS-1 commit: feature packages `audio/ memory/
perception/ simulation/ motion/ voice/ prompting/` exist; all package
`__init__.py` files are import-free and `tests/test_decig2_import_ratchet.py`
enforces leaf imports — import from the defining module, never a package.

## Host rules (safety-critical; violations end the card)
- Every pytest through `env -u TMPDIR ~/.cache/parcel-guard/pytest_guard.sh
  --label <hypothesis> .parcel/bin/python -m pytest …`; NEVER `-n auto`;
  NEVER `scripts/ci_gate.py --tier`; targeted tests only (no full suite).
- Git is READ-ONLY (no add/commit/stash/checkout/restore/reset).
- Never touch the owner's live stack: `:8765`, `/tmp/parcel_sim.sock`, the
  `:8080` gemma CPU server, `parcel_memory.sqlite3`, `~/.config/parcel/*`
  (H1 may *read* `realtime.yaml` and use the launcher's env sourcing).
- Model servers: H2 owns `:8081` (gemma-26B CUDA via
  `scripts/launch_reasoner_gpu.sh`) and `:8082` (Ministral-8B CUDA via the
  same launcher with `PARCEL_REASONER_MODEL_PATH`/`PARCEL_REASONER_PORT`).
  H1/H5 use `:8081` if `/health` answers; otherwise start it yourself with
  the launcher and say so in RESULTS. Perception daemons: start your own
  on a private socket path under your folder. Sims: your own
  `parcel_robot.sim` on a private `--socket` under your folder; stop it
  when done. GPU is shared by H2/H6 (and H1/H5 via :8081): record
  `nvidia-smi` at each headline measurement and re-measure headline rows
  in isolation at the end if contention was present.
- Python `.parcel/bin/python`; ruff `.parcel/bin/ruff`; zero `noqa`; no
  `ruff format` on files failing it at HEAD; new modules ≤ 600 lines, one
  concept each, never `utils/`; product seams only where your DESIGN.md
  OWNS names them, flag-off by default; both DEC ratchets must stay green
  (`tests/test_dec0_debt_ratchet.py`, `tests/test_decig2_import_ratchet.py`).
- Hosted spend: H1 only, ≤ $2.00, itemized; everyone else $0.
- Scratch: `/tmp/claude-1000/-home-jaewoo-jang-Desktop-Projects-Parcel/0b505906-665b-45ea-a2b7-686b3aecb89d/scratchpad/<hypothesis>/`.
  Durable artifacts (scripts, results JSON/CSV, small plots) go in your
  research folder; keep them < 5 MB total; no model weights, no audio > 1 MB.

## Method
1. Re-read the DESIGN's measurement table; write the harness so every row
   is produced by code, with raw rows saved (`results/*.json`).
2. Capture any "before" baseline the DESIGN names BEFORE changing code.
3. Build the smallest product seam the DESIGN allows; keep the harness in
   your folder. One capability test if the DESIGN names one.
4. Run the pre-registered rows. A missed criterion is a finding — write it
   down with the number; never move the bar, never tune to the bar.
5. Write `RESULTS.md`: what was run (commands), environment (GPU load,
   servers up), the table with measured values next to criteria, raw-file
   pointers, surprises, cost, and "does not prove". Keep it ≤ 250 lines.

## Final message (read by the verifier, not the owner)
Compact: the measurement table (criterion | measured | met?), files added
or changed (product vs research), tests run with counts, servers/daemons
started and whether they are stopped, hosted $ if any, and what is left
undone with the reason. Do NOT commit.
