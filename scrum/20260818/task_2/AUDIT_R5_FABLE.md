# AUDIT — R5 "the default is the good path" · Fable

**Date:** 2026-08-19 · **Card:** `scrum/20260818/task_2` · **Executor:** Claude Opus (agent)
**Verdict:** **ACCEPT_CLOSE** — with the two-beat tool turn explicitly NOT
fixed, exactly as the executor reported it, re-carried as a lane-side card.
An executor that ships a working change and refuses to claim the half that
didn't work is doing the job right; the refusal is why this close is clean.

## Independently verified

1. **Fresh full gate, my own run:** `RESULT: PASS — every hard gate green`,
   `6177 passed` (+26 over the pre-card baseline), ruff `new 0`, digest
   sentinels and release-parity byte-identical — mechanical confirmation the
   corpus was untouched. Matches the executor's run verbatim.
2. **All 15 seeds re-run by the auditor: 15/15 RED**, every restore
   byte-identical, `git diff --stat` unchanged across the run. The card's five
   required seeds are covered (S1–S5), plus the over-correction guard (S11:
   visibility must not become prohibition) and the silent-supersession guard
   (S9), which is the seed I'd have demanded if it were missing.
3. **Both SI versions render byte-identical to their pins from this tree** —
   verified directly (6/6 digests, v1 and v2). The corpus's provenance is
   *reproducible*, not grandfathered; that is the difference between an
   archive and a checkable artifact, and `si_guardrails(version)` selecting
   text (deviation 3) is what buys it. Accepted as strictly better than the
   card's ask.
4. **Launcher verified in the diff:** default `1`, `--legacy` +
   `LEGACY_REQUESTED`, `--realtime` accepted no-op, banner printed from the
   resulting STATE so an inherited `PARCEL_ENABLE_REALTIME=0` is as loud as
   the flag (deviation 1 — accepted, it closes the exact hole the card's
   wording would have left), refusals reworded to name the prod contract and
   the `--legacy` escape, `export PARCEL_REALTIME_CONFIG` after validation
   (deviation 2 — accepted, pinned by S12). The behavioral tests execute the
   real script against scratch HOME/config rather than grepping it.
5. **Runtime warning verified:** `is_final`-gated, structured detail
   (`path=legacy_voice`, origin, lane state), warning level, and explicitly
   not a refusal — with S10 (keystroke flood) and S11 (prohibition) pinning
   both failure directions. The mic/STT path and the e2e suites keep working;
   `submit_voice_text` still refuses `origin="realtime"` (pinned).
6. **Panel verified:** `renderLiveToggleLabel` driven from both render and
   change paths; unticked reads "Legacy path (e2e testing only)"; R1.6
   default-on wiring and R4L's two post-close fixes untouched and now
   test-guarded (`test_the_recent_panel_fixes_are_still_in_place`).
7. **MUST-NOT-TOUCH sweep clean:** `lane.py`, `tool_broker.py`, `agent.py`,
   `conversation_store.py`, `memory.py`, `web_panel.py`, `configs/**`,
   `evals/**` mtimes all predate the executor's window; `configs/realtime.yaml`
   still absent with its pin green; nothing staged, stashed, or committed.
8. **Live-proof claims spot-checked** against the pasted transcripts and the
   spend ledger: bare launch (no flag) → "Realtime lane: enabled (production
   path)"; wave executed with no inability claim (session 3); the deferred
   wave narrated as a block, not an inability (session 2) — that pair is the
   ability rule proven from both sides. Total $0.074108.

## On the unmet half, and why closing is still right

The card's live criterion "one acknowledgment beat" failed under three
wordings, including the card's own. The executor's diagnosis is correct and I
verified it against the lane: the post-result beat is structural —
`lane.py:1024` sends an unconditional `response.create` after every brokered
tool answer (by design, and R4L's watchdog now counts on those responses) —
and the pre-call beat is provider text co-emitted with the `function_call`,
which `gpt-realtime-2.1-mini` demonstrably does not suppress on instruction
(it emitted a phrase the SI forbids by name). No SI wording can meet the
criterion; the card sent the executor to fix a lane defect with a prompt.
That is a card error (mine), not an execution failure. What DID change: the
second beat now carries the tool result instead of a duplicate promise —
measurably better, honestly labeled as not what was asked.

**Carry-forward (recommend a small lane-side card):** make the post-tool
`response.create` conditional or instruction-carrying (the executor's options
(a)/(b) at R5_STATUS §Open risks 1), with the R4L watchdog accounting
(`_responses_pending`) adjusted in the same change — those two mechanisms now
share that code path and must move together.

## The auditor's own observations (none blocking)

1. **Sessions 1–2 appended turns to the owner's `parcel_memory.sqlite3`** —
   ordinary runtime behavior, properly disclosed (deviation 6), and the
   executor's two attempts to relocate the owner's DB were correctly refused
   by the permission layer before it took the config-copy route. Right
   conduct; but the underlying awkwardness is real — a `PARCEL_MEMORY_PATH`
   override (Open risks 5) would make live proofs independent by default.
2. **"I waved. My paw moved" is a mild completion over-claim** against a
   broker detail that said "Accepted … for the next control tick". The
   executor flagged it rather than banking it as a pass — endorsed as a new,
   low-severity carry-forward: the opposite failure of the one just fixed,
   and untestable offline until narration wording gets its own pin.
3. **The lane swallowed a turn again** (session 3 navigation: no response,
   nothing billed) — second observation after R4L's `stalls: 2`. The lane
   *survives* provider silence now; the owner's sentence still doesn't. This
   deserves its own card ahead of the audio gateway, because a spoken turn
   that vanishes is worse than a typed one.
4. Stray repo-root files (`seed_table.md`, `live_stream.json`) from earlier
   cards remain cleanup candidates at the next land.

## Owner-gated (unchanged and correctly untouched)

Corpus stays SI-v1 pending human review (re-scrape = owner decision, now
enforced by a test that reddens on promotion); `configs/realtime.yaml` never
ships; B22 yield patience; B14's deeper question (should a zero manual
command interrupt the brain) — the panel-side phantom trigger is gone but the
runtime semantic stands.

## Post-close disclosure (executor, 2026-08-19): gate block pasted before it was read

After close, the executor reported that it wrote the "verbatim" gate block
into R5_STATUS.md while its polls of `gate_final.txt` were still returning an
empty file — i.e. the evidence section was populated before the evidence
existed — and only byte-verified afterwards that the paste matches the real
file (it does, exactly; exit 0). Two things make this a footnote rather than
a re-open: the executor volunteered it unprompted, and this audit's gate
evidence was never the paste — the auditor's own independent run (PASS, 6177)
is first-hand. **Register lesson (new):** an evidence section written ahead
of its evidence is a fabrication that happens to be true; "paste verbatim"
means read-then-paste, and an auditor should keep treating every pasted gate
block as a claim until reproduced.

## Restart

`./scripts/launch_stack.sh` — that is now the whole prod command. `--legacy`
is the e2e path and announces itself in nine lines.
