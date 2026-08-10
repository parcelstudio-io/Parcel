# Card M-A status — PC-4 judge + calibration + live summarizer quality

**Executor:** inherit stand-in (Opus `ac848f85` hit API limit at turn 0).  
**OWNS:** `evals/companion/personal_convo_v1/**` + judge/calibration/tests.  
**MUST NOT:** `runtime.py`, `navigation/**`, `core/**`, `camera_channel/**`,
`detection_adapter/**`, `instructnav/**`.

## Verdict

**DELIVERED** — report-only PC-4 judge with frozen known-good/known-bad
calibration (drift ⇒ disqualified); provenanced `--provider live` PERSONAL_CONVO
run measured live Tier-2 summarizer quality; offline tests green; ci_gate
recorded below.

## Delivered

| Artifact | Role |
|---|---|
| `evals/companion/personal_convo_v1/judge.py` | Local heuristic judge; report-only dimensions |
| `evals/companion/personal_convo_v1/calibration/**` | Frozen 3 known-good + 3 known-bad cases + pack |
| `evals/companion/personal_convo_v1/live_provider.py` | llama.cpp companion + freeform live summarizer |
| `evals/companion/personal_convo_v1/run_personal_convo_v1.py` | Wires calibrate→judge every run; `--provider live` |
| `tests/test_personal_convo_pc4.py` | Offline PC-4 gate (qualify / drift / pins) |
| `results/personal-convo-t-20260809-live-summarizer-run03.json` | Immutable live measurement |

Suite `manifest.json` sha-pins judge + calibration (23 locked files).  
New `pack_digest` = `fc1af2f76f2b491451558ef51c375723f070b9ed9fa94ea40344a3e194006b04`  
(additive pins only; no pre-existing locked file content rewritten).

## Gate evidence

### 1) PC-4 calibration (offline)

- `calibrate()` → `status=qualified`, `mismatch_count=0`, `scores_valid=true`
- Drift monkeypatch → `status=disqualified`; probe scores omitted
  (`omitted_reason=calibration_drift`) — never silently shifted
- Judge never writes `family_status` / `case_verdicts`

```
PYTHONPATH=src:. .parcel/bin/python -m pytest -q \
  tests/test_personal_convo_v1.py tests/test_personal_convo_pc4.py
→ 26 passed
```

### 2) Live summarizer quality (`--provider live`)

```
--base-url http://127.0.0.1:8080
--model gemma-4-26b-a4b
--model-artifact models/gemma-4-26b-a4b/gemma-4-26B_q4_0-it.gguf
--model-sha256 3eca3b8f6d7baf218a7dd6bba5fb59a56ee25fe2d567b6f5f589b4f697eca51d
--run-id personal-convo-t-20260809-live-summarizer-run03
```

Measured (`summarizer_quality`, report-only):

| Field | Value |
|---|---|
| `contains_offer` | **true** |
| `durable_fact_coverage` | 0.25 (offer only among offer/interview/monday/friday) |
| `summarizer_calls` | 8 |
| `used_fallback` | true (at least one fold used ConcatSummarizer) |
| `summary_words` | 44 |
| PC-4 `judge_status` | **qualified** |

Cross-session turn under live summarizer: Tier-D **fail on `word_budget` only**;
reply text recalls the offer from the live summary (not a fact-recall miss).

Live companion Tier-D aggregate: **3/13 turns pass**, 1 family pass
(`asr_robustness`), 1 `recency_window_blocked`, 6 fail — live-model quality,
not fixture regression.

### 3) ci_gate

```
.parcel/bin/python scripts/ci_gate.py --tier commit
@ 2026-08-09T22:56:34Z → RESULT: PASS — every hard gate green
  default-suite: 3256 passed, 9 skipped, 34 deselected, 0 failed (107.98s)
  elapsed 110.8s
```

## does_not_prove

- Heuristic judge ≠ human preference / full conversational quality.
- Live companion DialogueAct is eval-local conservative derivation, not the
  production voice-lane extractor.
- `used_fallback=true` means summarizer quality is a mixed live+fallback trace
  for this run, not a pure-LLM summary proof.
- Single live seed is not a swap non-inferiority claim (PC-7).
- No human-recorded audio; Tier A still owner-gated.

## Files touched (OWNS only)

- `evals/companion/personal_convo_v1/judge.py` (NEW)
- `evals/companion/personal_convo_v1/calibration/**` (NEW)
- `evals/companion/personal_convo_v1/live_provider.py` (NEW)
- `evals/companion/personal_convo_v1/run_personal_convo_v1.py`
- `evals/companion/personal_convo_v1/manifest.json` (additive locks)
- `evals/companion/personal_convo_v1/README.md`, `__init__.py`, `results/README.md`
- `evals/companion/personal_convo_v1/results/personal-convo-t-20260809-live-summarizer-run03.json` (NEW)
- `tests/test_personal_convo_pc4.py` (NEW)
- `scrum/20260809/task_15/M-A_STATUS.md` (this file)
