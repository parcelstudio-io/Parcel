#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
out_dir="$repo_root/research/20260826/system-readiness"
cd "$repo_root"
export PYTHONPATH="$repo_root/src:$repo_root"

.parcel/bin/python -m evals.companion.realtime_convo_v1.score_corpus \
  --review evals/companion/realtime_convo_v1/reviews/20260824-unblinded-ai-review.json \
  --require-review \
  --output "$out_dir/realtime_convo_v1_offline_score.json"

.parcel/bin/python -m evals.companion.run_brain_v1 \
  --output "$out_dir/brain_v1.json" \
  --compact

.parcel/bin/python evals/companion/run_embodied_plan_v1.py \
  --output "$out_dir/embodied_plan_v1.json" \
  --description "2026-08-28 owner-facing arrival closeout remeasurement" \
  --run-id "embodied-plan-v1-20260828-code-design-closeout" \
  --compact

.parcel/bin/python -m evals.companion.personal_convo_v1.run_personal_convo_v1 \
  --output "$out_dir/personal_convo_v1_fixture.json" \
  --provider fixture \
  --description "2026-08-26 deterministic Tier-T continuity remeasurement" \
  --run-id "personal-convo-v1-20260826-fixture"
