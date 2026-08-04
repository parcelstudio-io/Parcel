#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../../../.." && pwd)"
cmp -s "$ROOT/scrum/20260804/task_4/freeze/follow-bench-ledger.jsonl" "$ROOT/evals/companion_nav/results/ledger.jsonl"
cmp -s "$ROOT/scrum/20260804/task_4/freeze/embodied-plan-ledger-README.md" "$ROOT/evals/companion/embodied_plan_v1/results/README.md"
cmp -s "$ROOT/scrum/20260804/task_4/freeze/embodied-plan-v1-20260803-baseline01.json" "$ROOT/evals/companion/embodied_plan_v1/results/embodied-plan-v1-20260803-baseline01.json"
echo "ledger freeze: byte-identical"
