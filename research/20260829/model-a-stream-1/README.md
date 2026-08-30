# MA-1 — a trainable streaming Model A cloned from the real navigation stack

Pre-registration: `DESIGN.md` (FROZEN, Fable) + `AMENDMENTS.md` (POST-START,
binding). Results: `RESULTS.md` + `results.json`. Verdict: `VERDICT.md`,
written by Fable — **nothing in this folder draws one**.

Evidence tier: **`desktop-sim`** (headless city, kinematic base, no audio, no
real LiDAR noise beyond the venue's own profile). Physical motion: **NO-GO**.

## What this is

A ~5 M-parameter causal transformer ("Model A v0") that reads one
state-of-the-world frame every 100 ms and emits two tokens:

* an **act token** from the shipped codec (`duplex/act_codec.ActTokenCodec`) —
  `<twist:i:j>`, `<gaze_*>`, `<idle>` — which is decoded to a body twist and
  put through the product's `apply_reactive_safety` gate before the world
  sees it;
* a **narration event token** from a closed vocabulary — the representation a
  hosted voice could narrate from. **These tokens are PREDICTIONS and carry no
  authority** (amendment A10): no consumer may narrate a terminal from them.

It is trained by behaviour cloning on rollouts of the **real** navigation stack
(`DirectiveNavigator` + grid planner + semantic resolution ladder +
`apply_reactive_safety`) driven in `HeadlessCityWorld` by a scripted owner, and
then evaluated **closed-loop**: the model, not the navigator, drives the robot.

## Files

| file | what it is |
|---|---|
| `teacher.py` | frame schema, narration vocabulary, layout generation (A2), the scripted owner, the truth-oracle gold deriver, and the parallel corpus generator |
| `closed_loop_core.py` | **the one episode runner** — the teacher and every policy arm go through `run_core`, so the world, the cues, the gold timeline and the safety filter cannot drift between arms |
| `closed_loop.py` | scoring: navigation, A4 event-conditional narration F1, A3 switch/queue, sound attend, A8 safety |
| `arms.py` | T / A'n / C / C-h0 / ALWAYS-IDLE / STRAIGHT-TO-GOAL, training with pre-registered early stopping, latency |
| `run.py`, `run_stages.py` | the runner; writes `RESULTS.md` incrementally, stage by stage |
| `sample_episodes.txt` | 30-frame excerpts of one plain / revise / queue episode, written FIRST as the timing sanity check |

## Reproduce

```bash
cd /home/jaewoo-jang/Desktop/Projects/Parcel/research/20260829/model-a-stream-1
unset TMPDIR
export OPENBLAS_NUM_THREADS=32
export PARCEL_MEMORY_PATH="$HOME/.cache/parcel-0e/ma1/scratch_memory.sqlite3"
~/.cache/parcel-0e/venv/bin/python run.py --all --seed 20260829
```

Stages can be run separately with `--stages header,samples,generate,train,closed,latency`
(`report_generate` re-reads an existing corpus instead of regenerating it).
Scratch (corpus, generated scenes, checkpoints, logs) lives under
`~/.cache/parcel-0e/ma1/`; nothing is written outside that and this folder.

Corpus generation alone:

```bash
~/.cache/parcel-0e/venv/bin/python teacher.py --seed 20260829 \
    --train 3000 --dev 300 --held 600 --workers 24
~/.cache/parcel-0e/venv/bin/python teacher.py --sample-only --seed 20260829
```

## Host discipline

* No sim subprocess: the headless city runs **in-process**. The only children
  are the rollout `multiprocessing` Pool workers; they are joined and `run.py`
  proves its process group is empty at exit (RESULTS.md §7).
* A foreign executor shares this GPU, so **every** GPU job is gated on
  `nvidia-smi` reporting >= 14 GB free (our own cap is 12 GB), polled every
  60 s; each gate reading is recorded beside the job it gated.
* `PARCEL_MEMORY_PATH` points at a scratch file and `PARCEL_MEMORY_PURPOSE` is
  unset — the owner's memory store is never opened. No sockets, no
  `/dev/bus/usb`, no hosted API call, no VLM call, no git write.
* Generated scenes are written to MA-1's scratch tree, never to
  `configs/scenes/generated/`. Scene seeds are disjoint from the NAV
  `val_unseen` manifests, and the NAV evals' held-out scene is never loaded
  and never named. No frozen digest is read or moved.
* Nothing under `src/`, `tests/`, `evals/` or `configs/` is modified;
  `evals.nav_instruct.scene_gen.build_scene` and BM-1's
  `research/20260828/behavior-model-1/arms.py` are imported read-only.
