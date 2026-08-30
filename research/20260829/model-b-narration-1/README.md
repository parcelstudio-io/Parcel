# MB-1 — Model B: steering injection and grounded narration

`DESIGN.md` is Fable's, frozen. `AMENDMENTS.md` is PRE-RUN and BINDING; where it
conflicts with `DESIGN.md` it wins. `RESULTS.md` is what ran. `VERDICT.md` is
the promotion decision. Hosted status is **PARTIAL_QUOTA**: Q is complete
(120/120 scenarios), D is incomplete (2/120), so Q's absolute hypotheses are
scored but Q-minus-D is unmeasured. See `RECOVERY.md`.

## What is in this folder

| file | what |
|---|---|
| `events.py` | the 40-scenario receipt corpus (door → sofa → keys and 7 variants), the wave's shared fact set `{accepted, running, blocked, completed, failed, cancelled, resumed}`, the one queue-record schema, the gold *narratable* list per scenario, and the pre-registered keys-turn behaviours |
| `steer.py` | `steer(utterance, queue) → {revise, keep, queue, clarify}` plus the executive call it would realize; reuses `voice/closed_intents.py` and `voice/amendment.py` read-only. LIT-1 imports it by path |
| `narrate.py` | arm Q's plan-queue whisper renderer (untrusted-data delimiters, replace-not-append) + the trigger table + the whisperer's band/dedup/min-gap discipline; arm D drives the shipped `realtime/whisperer.py` at the runtime's own call sites |
| `scorer.py` | grounding (turn-level, with the coverage term), claims-per-turn, hedge rate, the four timing bars, the premature-claim check on the transcript delta stream, MB-1's own invented-action matcher, the perception rule, blind adjudication hooks, and CONV-1's JSONL emitter |
| `run.py` | the orchestrator and the three backends: scripted (`fake_server` frames over a real lane), local (`llama-server` on `:8093`), hosted (the product runtime + `submit_realtime_text`) |
| `recover_interrupted.py` | one-purpose, fail-closed recovery of the interrupted Q wave from its isolated research database; enumerates ambiguous response-time assignments and chooses the pessimistic score without inventing replies or latency |
| `verify_hosted_checkpoint.py` | independently validates entry/config/ledger/database hashes, schedule prefix, and a full deterministic re-score against the published JSON |
| `RECOVERY.md` | failure, recovery, quota, cost, provenance, and stable artifact hashes |
| `VERDICT.md` | hypothesis decisions and the recommended deterministic speech-act design |
| `results.json` | the merged roll-up |
| `results/` | per-stage artifacts, atomic hosted checkpoint, the blind adjudication queue and its key |
| `transcripts/mb1-turns.jsonl` | CONV-1's transcript shape, ready for `conv-bench-1/bridge.py --transcripts` |
| `logs/` | stdout per stage, and the local model server's log |

## Reproduce

The hosted evidence must **not** be rerun just to reproduce a summary. Verify
it with `verify_hosted_checkpoint.py` and rerun only the free stages:

```bash
cd /home/jaewoo-jang/Desktop/Projects/Parcel
unset TMPDIR
.parcel/bin/python research/20260829/model-b-narration-1/verify_hosted_checkpoint.py
.parcel/bin/python research/20260829/model-b-narration-1/run.py \
  --only fake --seed 20260829 --output /tmp/mb1-fake-reproduction.json
```

The original run used the pre-registered order `fake → local → hosted`: the
scripted rows proved the harness on a real lane before a cent was spent, the
local rows answered H-MB1d for free, and only then did anything reach the
provider.

### Stage by stage (what this session actually ran)

```bash
# 1. scripted — a REAL RealtimeLane over the product's fake_server frames.  $0.00
.parcel/bin/python research/20260829/model-b-narration-1/run.py \
  --only fake --seed 20260829 --output research/20260829/model-b-narration-1/results/fake.json

# 2. local — Qwen2.5-7B-Instruct Q4_K_M on a llama-server this card owns.  $0.00
#    run.py starts it on :8093 and kills its process GROUP on every exit path.
.parcel/bin/python research/20260829/model-b-narration-1/run.py \
  --only local --seed 20260829 --output research/20260829/model-b-narration-1/results/local.json

# 3. hosted — frozen Q-then-D schedule, one atomic checkpoint.
.parcel/bin/python research/20260829/model-b-narration-1/run.py \
  --only hosted --hosted-arms Q,D --hosted-scenarios 40 --hosted-samples 3 \
  --hosted-cap-usd 4.50 --seed 20260829 \
  --hosted-checkpoint research/20260829/model-b-narration-1/results/hosted-QD-full.checkpoint.json \
  --hosted-resume \
  --output research/20260829/model-b-narration-1/results/hosted-QD-full.json

# 4. merge the stage files into one results.json (no re-spend)
.parcel/bin/python research/20260829/model-b-narration-1/run.py \
  --merge research/20260829/model-b-narration-1/results/{fake,local,hosted-QD-full}.json \
  --seed 20260829 --output research/20260829/model-b-narration-1/results.json
```

The stages were run separately for two reasons, and both are recorded rather
than tidied away: the free stages were re-run after each harness fix, and the
hosted stage is metered — a re-run costs money, so it is never repeated to make
a JSON file neater.

### Score the transcripts on CONV-1's instrument

```bash
.parcel/bin/python research/20260829/conv-bench-1/bridge.py \
  --transcripts research/20260829/model-b-narration-1/transcripts/mb1-turns.jsonl \
  --output research/20260829/model-b-narration-1/results/cv1c-over-mb1.json
```

### Component self-tests (no model, no money)

```bash
.parcel/bin/python research/20260829/model-b-narration-1/events.py   # corpus summary
.parcel/bin/python research/20260829/model-b-narration-1/steer.py    # steer vs the gold labels
```

## The $5 cap, and how it is enforced

Amendment M5, clause by clause:

* `PARCEL_REALTIME_CONFIG` → `~/.cache/parcel-0e/mb1/realtime.yaml`
  (`monthly_budget_usd: 5.0`, `gpt-realtime-2.1-mini`, `mode: text`);
* `PARCEL_REALTIME_SPEND_LEDGER` → `~/.cache/parcel-0e/wave20260829/spend.jsonl`,
  **one** file, shared with LIT-1;
* `~/.cache/parcel-0e/mb1/robot.yaml` carries the `audio.ear.governor` block
  (`envelope_usd 5.0`, `reserve_usd 0.0`, `warn_usd 4.0`, `daily_cap_usd 5.0`,
  `refuse_when_unknown true`);
* every hosted turn goes through `runtime.submit_realtime_text`, which calls
  `_require_hosted_budget`; every trigger-table response asks
  `governor.require(..., call_class=CLASS_ROUTINE)` first. `CLASS_CRITICAL` is
  never used — it is admitted before the governor reads the ledger;
* one session per scenario, closed at the end of it, so the arming gate
  (`decide_realtime_arming`) re-reads the ledger between scenarios;
* `run.py` asserts `runtime._realtime_spend_note` names the wave ledger and
  refuses to start otherwise; `governor.snapshot()` is printed before the first
  call and after the last, and both are in `results.json`;
* a local `--hosted-cap-usd` stop reads month-to-date from the ledger before
  every scenario. A refusal is recorded and the row is UNMEASURED; it is never
  worked around.

**The gap this found, and its current status.** The first pilot found that
text mode did not construct `HostedCallGovernor`. The product runtime was fixed
during this wave. `run.py` keeps a defensive fallback for historical
reproduction and records whether it was needed; every current paid row still
requires a readable governor snapshot before a provider call.

**Crash/quota recovery.** The hosted stage writes a lossless entry after each
scenario using fsync + atomic replace. `--hosted-resume` validates the frozen
schedule/config and per-entry SHA-256 before skipping completed scenarios. A
quota error is written as an incomplete entry and exits successfully with
`PARTIAL_QUOTA`. An incomplete scenario is never retried implicitly; the
operator must inspect ledger-before/after and pass
`--hosted-retry-incomplete`. This prevents an interrupted run from silently
duplicating paid calls.

## Constraints honoured

`TMPDIR` unset; no pytest (so no guard wrapper needed); no git writes; nothing
written outside this folder and `~/.cache/parcel-0e/mb1/` except the shared wave
ledger; the owner's `:8080`, `:8765`, `/tmp/parcel_sim.sock`,
`parcel_memory.sqlite3` and `~/.config/parcel/realtime.yaml` untouched
(`PARCEL_MEMORY_PATH` → `~/.cache/parcel-0e/mb1/scratch/`,
`PARCEL_MEMORY_PURPOSE=research`); the credential is read by the product's own
loader from `~/.config/parcel/realtime.env` and is never printed, copied or
logged; `/dev/bus/usb` never opened; no VLM call from any runtime callback; the
`llama-server` this card starts is killed by process group on every exit path;
place names are demo-city landmarks checked against the NAV held-out scene id by
importing the constant (`events.assert_places_admissible`), never by naming it;
this folder re-pins no frozen corpus or digest — the corpus, the scorer and the
transcripts are a new tier.
