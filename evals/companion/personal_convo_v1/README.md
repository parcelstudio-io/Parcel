# PERSONAL_CONVO_V1 — text tier (Tier T)

A multi-turn personal-conversation probe family on the conversation_quality_v1
rails. This directory is the **text-transcript tier only** — per-commit,
offline, deterministic CI. Tier A (audio e2e on the acoustic rig), the
human-recorded corpus, and the local judge + calibration pack (PC-4) are
separate, owner-gated cards and are intentionally absent here.

## Layout

- `manifest.json` — sha-pins every fixture and scorer; the runner refuses to
  run on any edit (mirrors conversation_quality_v1).
- `run_personal_convo_v1.py` — drives frozen session scripts through the text
  path and writes an immutable result. Default provider is the offline,
  deterministic fixture companion (`--provider fixture`); `--provider live`
  is a provenanced seam for a real llama.cpp run (out of CI).
- `session_schema.py` — the session-script schema (PC-1).
- `scorers.py` — the deterministic Tier-D scorer bank (PC-2).
- `fixture_provider.py` — the honest reference companion used for CI.
- `build_memory_fixture.py` — replays an event-graph YAML into a fresh sqlite
  `ConversationMemory` (PC-2).
- `probes/` — the eight probe families as sha-pinned session scripts (PC-3).
- `memory_graphs/` — LoCoMo-style authored event graphs.
- `human_recording/SCRIPT.md` — the ~30-minute read-aloud utterance list for
  the owner-gated human corpus (committed, not required by this tier).
- `result.schema.json`, `results/` — result schema and immutable ledger.

## Run (offline CI)

```bash
PYTHONPATH=src:. .parcel/bin/python -m evals.companion.personal_convo_v1.run_personal_convo_v1 \
  --output evals/companion/personal_convo_v1/results/personal-convo-t-run01.json \
  --provider fixture \
  --description "Frozen Tier-T reference-companion baseline"
```

## What the Tier-D bank checks (deterministic, CI-gating)

Per turn: tool-invocation correctness from the trace; the DialogueAct
truthfulness contract (no verified claim without `evidence_ref`; a `max_veracity`
ceiling; no arrival/found-it/tool-result claim before a verified state); fact
recall / confabulation as casefolded `facts_must_appear` groups and
`facts_must_not_appear` substrings; the `asks_clarification` bit; the emote tag
budget; the reply word budget; and DialogueAct contract-parse validity.

A family is `recency_window_blocked` (not `fail`) when the only failing category
is `fact_recall` while every truthfulness check holds — an honest limitation,
not a regression. See `results/README.md` for the honest headline.

## Determinism

Under the fixture provider the run is a pure function of the frozen pack: two
runs produce identical `case_verdicts` and identical `pack_digest`. There is no
clock, RNG, or network on the scoring path.
