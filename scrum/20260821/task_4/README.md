# Task 4 — R25: the budget that actually refuses

**Executor:** Claude Opus (agent) · **Auditor:** Fable (deferred)
**Trigger:** full-audit CONFIRMED major (§Ops-2): `monthly_budget_usd` is
documented — in the owner's own config file — as an arming refusal ("the
arming gate refuses to open a session once this month's estimated spend
reaches this number") and **the arming gate never reads it**. A documented
safety control that does not exist is worse than an absent one: the owner
has been operating for weeks believing a ceiling exists.

## Work

1. **Make it real:** the arming decision refuses when month-to-date
   estimated spend ≥ `monthly_budget_usd`, with the refusal reason naming
   the figure, the period, and how to raise it. Fail-closed on an
   unreadable ledger? NO — fail-OPEN with a loud warning is correct here
   (a broken spend file must not brick the robot), and that choice must be
   stated in the doc and pinned by test.
2. **Month-to-date accounting must persist across restarts** — today's
   spend lives in per-session snapshots. A small durable spend ledger
   (beside the evidence log / recordings, not in `evals/`), append-only,
   with the honest `rates_are_assumed` flag carried through. If a durable
   ledger is out of scope for one card, the refusal must still work within
   the process AND the doc must state plainly what a restart forgets.
3. **Surface it:** snapshot + panel show month-to-date spend against the
   budget, so "how close am I?" is answerable without reading files.
4. **The whisperer/narration interaction** (F1-SI open risk 10.2 is
   adjacent): decide and pin whether SAFETY-class narrations (refusals,
   e-stop facts) may exceed the budget. Recommendation to evaluate: yes,
   safety facts bypass the cost ceiling exactly as they bypass the
   whisperer's rate cap — the same asymmetry, for the same reason.

OWNS: `realtime/config.py` (validation only — the key already exists),
`realtime/lane.py` arming path, `realtime/cost.py`, a durable spend ledger
module, `runtime.py`/`ui/index.html` surfacing, tests, `R25_STATUS.md`.
MUST NOT TOUCH: ingress, prompting, broker tool set, yield, evals
fixtures, the owner's `~/.config/parcel/realtime.yaml`. Standard house
rules.

## Definition of done

Gate green; ≥8 seeds RED (budget ignored again; refusal reason silent;
safety narration blocked by the budget — the over-correction; ledger
non-durable if durability shipped; fail-closed-on-unreadable restored).
Live proof: a scratch config with a $0.001 budget refuses to open a
session with the documented message, and the same stack with a real budget
opens normally. `R25_STATUS.md` standard register, including the honest
statement of what month-to-date means today.
