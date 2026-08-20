# Task 5 — E1: the auditable common-sense eval pack (evals/20260819/run_1/)

**Date:** 2026-08-19 · **Executor:** Claude Opus (agent) · **Auditor:** Fable
**Depends on:** R10 (task_3) and R11 (task_4) — run this ONLY after both close.
**Trigger:** owner directive (verbatim): "Keep the conversation recording or
test trajectory (video or path) so that it is auditable in the future. The
test should be placed in a dedicated evals/YYYYMMDD/run_1/ folder where the
run folder has a readme of what was tested."

## What this is

A recorded, re-runnable eval pack proving the day's common-sense claims on
live sessions, laid out for a future auditor who has nothing but the folder.
Path recordings are the chosen trajectory medium (timestamped JSONL of base +
owner positions, plus a rendered top-down SVG per scenario — dependency-free
hand-rendered SVG, no new libraries). Video stays owner-gated (offscreen
MuJoCo rendering is heavy and adds no auditability over paths + transcripts).

## Layout (binding)

```
evals/20260819/run_1/
  README.md                 # what was tested, how to re-run, verdicts table
  manifest.json             # scenario list, model ids, SI version, digests,
                            # costs, clock provenance, file inventory + sha256
  scenario_<name>/
    transcript.json         # full ledger rows for the session
    path.jsonl              # t, base xy/heading, owner xy (10 Hz max)
    path.svg                # top-down render: region polygons, both tracks,
                            # start/end markers, block/refusal annotations
    events.json             # runtime events + mission_log for the window
    whisperer_log.jsonl     # R11 decision log slice: every forward AND
                            # suppression with the deterministic rule that
                            # fired (REVISED 2026-08-20: the judge band was
                            # rejected on bench evidence; the log is now
                            # rule firings, which is strictly more auditable)
    verdict.md              # pass/fail against the scenario's stated claim
```

## Scenarios (each states its claim in README before running)

1. **sidewalk-on-top** — "go to the sidewalk" terminates with the base
   INSIDE the region polygon; path.svg shows the track ending on the region.
2. **door-etiquette** — "go to the door" ends near the door WITHOUT crossing,
   dog faces the owner, transcript shows the model asking what to do next.
3. **orbit-feasible** — "circle around me" with the owner in open space:
   full orbit in the path record.
4. **orbit-refused** — same request with the owner boxed in (scripted
   obstacles): no orbit motion beyond approach, transcript shows the model
   SAYING it can't walk around, refusal in events.
5. **run-with-me-flex** — follow with run intent; scripted owner runs then
   walks a sustained window; transcript shows the model asking whether to
   walk; path shows both pace phases; follow safety caps provably never
   exceeded (max speed extracted from path deltas).
6. **whisperer-discipline** — a quiet 3-minute session with telemetry churn:
   forwarded-item count stays at the always-band events only;
   judge_decisions.jsonl accounts for every suppression.

## Rules

* Scenarios run on YOUR stack (in-process or own port), R5 scratch-memory
  recipe, real hosted model + real local judge. Every scenario's cost in the
  manifest; total target under $2.
* `evals/20260819/` is NEW and owned here. The frozen manifests, sentinels,
  and the SI-v1 corpus under `evals/companion/` are UNTOUCHED — verify the
  digest-sentinel and release-parity gates green after writing the pack.
* A scenario that FAILS is recorded as failed with its evidence — the pack
  is an audit record, not a brochure. Failures become tomorrow's cards.
* No source edits in this card. If a scenario exposes a defect, record it,
  fail the scenario, and report — the fix is a separate card.
* Determinism honesty: seeds/spawn scripts recorded in the manifest so a
  future re-run can reproduce the setup even though live-model replies vary.

## Definition of done

The folder exists exactly as specified; README's verdict table filled; full
`ci_gate --tier commit` green after the pack is written (sentinels/parity
prove the frozen surfaces survived); costs recorded;
`scrum/20260819/task_5/E1_STATUS.md` with the standard register (for this
card: no seeds — it edits no source; the register instead carries the
verdict table, spend, and any defects filed).
