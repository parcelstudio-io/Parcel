# MB-1 amendments — PRE-RUN (written 15:41 08-29 from parcel-6c's code-verified lens, before any MB-1 row)

## M1 — the plan-queue whisper rides the UNBILLED tail seam, not narrate_event
`lane.narrate_event` (≈ lane.py:1832) = `_send_item(NARRATION)` +
`ResponseCreate`: every forwarded narration is a BILLED response and is
throttled by the whisperer/config bands (`max_updates_per_minute` default 2,
prototype 6; `min_gap_s` 15 / 4; curiosity 25 s) — the rest are
`narrations_skipped`. "Every event, ≤ 2 s" is therefore impossible on that
path and would be dishonest. Use the existing unbilled seam instead:
`_inject_tail` (≈ lane.py:1690–1707) sends conversation items with
`ITEM_PURPOSE_TAIL` and NO `response.create` (deduped, `MAX_TAIL_ITEMS`
capped, R8-tagged through `_send_item`). Design the plan-queue whisper as a
conversation item with ITS OWN purpose tag and no response.create (or a
`SessionUpdate` instructions refresh at rollover, ≈ :1577); **REPLACE** the
previous plan-queue item rather than append. Cost = input tokens on the
next owner turn; report **input-token growth per event** as a row.

## M2 — never CRITICAL; research calls are CLASS_ROUTINE
`CRITICAL_KINDS` (whisperer.py:375) bypass both caps AND the monthly
ceiling; the governor admits `CLASS_CRITICAL` before it reads the ledger.
Every research call is `CLASS_ROUTINE`; `refuse_when_unknown` stays True.
Before the first hosted row, prove the wave-local ledger path is readable
by the governor (a scratch path that reads as "unknown" refuses everything —
record the governor snapshot showing month-to-date and the $5 ceiling).

## M3 — timing rows redefined for the tail seam
H-MB1b's "first response after the event" is scored on the owner's NEXT turn
(the tail item is consumed when the owner next speaks or when a scripted
response.create is issued by the scenario). Report both: (i) acknowledgement
on the next owner turn; (ii) a separate row where the scenario issues one
response.create per event on the narrate_event path within its band (the
billed, throttled product path) so the two paths are compared.

## M4 — name-scan and VLM rule
Whisper text naming places passes `_curiosity_admitted_names`; no VLM call
from any runtime callback (P1-D tripwire, runtime.py ≈ :11673); never the
held-out scene name.

## Appendix — seam facts verified at HEAD (15:45 08-29, for the executor)
- `realtime/lane.py`: `MAX_TAIL_ITEMS = 120` (:494); item purposes
  `ITEM_PURPOSE_TAIL = "memory tail"` (:499), `_OWNER_TURN` (:500),
  `_ACTION_REPORT` (:501), `_NARRATION` (:502); `_inject_tail(self)` (:1600,
  dedup + cap, `_send_item(role, text, purpose=ITEM_PURPOSE_TAIL)` at :1705);
  `narrate_event(self, text, *, critical=False)` (:1832) → `_send_item(...,
  purpose=ITEM_PURPOSE_NARRATION)` (:1946) + response.create; action reports
  at :1815 / :3134 use `ITEM_PURPOSE_ACTION_REPORT` (also unbilled items).
  The plan-queue whisper should be a new purpose string (e.g. "plan queue")
  sent through `_send_item` with NO response.create, replacing the previous
  plan-queue item (track the last item id; delete/replace as the protocol
  allows, else send the full current queue each time and count tokens).
- `realtime/protocol.py`: `SessionUpdate(ClientEvent)` (:266) for an
  instructions refresh at rollover.
- Governor: constructed by the product at `runtime.py:9582`
  (`HostedCallGovernor(config=GovernorConfig, month_to_date=<callable>,
  day_to_date=<callable>, on_event=..., now=...)`); ledger classes
  `MonthToDateSpend` / `DayToDateSpend` in `realtime/spend_ledger.py`
  (:192 / :166); `resolve_spend_ledger_path(root)` names the file. Build the
  governor exactly as the runtime does, pointing the ledger root at
  `~/.cache/parcel-0e/mb1/`, and print `governor.snapshot()` before the
  first hosted call to prove month-to-date reads as a number (not unknown)
  and the ceiling is 5.0.
- Bands: `realtime/config.py` `max_updates_per_minute` (:125),
  `min_gap_s` (:126), `stimulus_min_gap_s` (:162); `CRITICAL_KINDS` in
  `whisperer.py` (:375) — never used by research rows.

## M5 — the $5 cap, enforced by the product's real knobs (PRE-RUN, BLOCKING)
`HostedCallGovernor` is built only inside `_build_ear_gate` from robot.yaml's
`audio.ear.governor` block (default envelope $160 / reserve $40;
runtime.py ≈ 9575–9605) and consulted by `_require_hosted_budget` on typed
turns; `realtime.monthly_budget_usd` is enforced only by
`decide_realtime_arming` (refuses to OPEN a session once month-to-date ≥
budget). Therefore: (a) `PARCEL_REALTIME_SPEND_LEDGER=~/.cache/parcel-0e/wave20260829/spend.jsonl`,
ONE file shared by MB-1 and LIT-1; (b) a wave-local robot config with
`audio: ear: governor: {envelope_usd: 5.0, reserve_usd: 0.0, warn_usd: 4.0,
daily_cap_usd: 5.0, refuse_when_unknown: true}` AND `monthly_budget_usd: 5.0`
in the wave realtime.yaml (`PARCEL_REALTIME_CONFIG`); (c) every hosted turn
through `runtime.submit_realtime_text` (which calls `_require_hosted_budget`),
never `lane.send_text`; (d) short sessions (close the lane after each
scenario) so the arming gate re-reads the ledger; (e) assert at start that
`runtime._realtime_spend_note` names the wave ledger; print
`governor.snapshot()` before the first hosted call. Sub-caps and order:
MB-1 arm Q then D, $3.00; LIT-1 3 live runs, $2.00.

## M6 — ONE injection door for both arms; arm D redefined (PRE-RUN, BLOCKING)
The developer note reaches the provider only at `session.update`
(open/rollover/reconnect); mid-session facts reach it through
`narrate_event` (system item + billed `response.create`, floor-gated and
band-capped) or through conversation items. Pre-register ONE door: arm Q's
plan-queue whisper is a `conversation.item.create` (own purpose string,
wrapped in the v2 `UNTRUSTED_DATA_BEGIN/END` delimiters, replace-not-append,
no `response.create`); robot-initiated speech follows a pre-registered
TRIGGER TABLE reusing the whisperer's band/dedup/min-gap discipline:
arrived / blocked / failed / clarify → one `response.create`; progress /
queued → context-only. Arm D = the product whisperer's forwarded events AS
SHIPPED (`mission_arrived` with its "offer to resume" hint, `mission_ended`,
`reroute`, `mission_blocked`, `refusal`, composed sentences at the product
cadence) — measured fresh; the "≤ 0.6" figure is dropped (QEV-1's 2/10 came
from a pinned LOCAL model). Both arms: harness-side injection; product
wiring is DUPLEX-1 work item 2. Report injected tokens per refresh and
whisperer decision rows (forward/suppress + rule) beside every turn; measure
"unprompted turns per scenario" and "speech collisions with scripted owner
speech"; run the premature-claim check on the transcript delta stream.

## M7 — Model B narrates RECEIPTS; A has no terminal authority (PRE-RUN)
Narrate's input is executive/mission-log receipts only (task states,
`MISSION_LOG_STARTED`, mission terminals); A's tokens may contribute only
`attend.*` / intent / acknowledgement classes. Any narrated arrival or
completion with no receipt is a premature claim regardless of A. Adopt
DMC-1's fact set {accepted, running, blocked, completed, failed, cancelled,
resumed} as the shared vocabulary so H-MB1a/b read on the same axes as
DMC-1 H3.

## M8 — scorer made non-gameable; sample size (PRE-RUN, BLOCKING)
Coverage term: every narratable gold event must be mentioned in the first
response after it (a zero-claim turn after a narratable event is a
failure); report claims-per-turn and hedge rate per arm; require Q coverage
≥ D coverage. n ≥ 120 turns per hosted arm (k = 3 samples per scenario turn),
per-scenario majority + seed-bootstrap CI; criterion a passes only if the
lower 95 % bound of Q − D exceeds 0. Invented-action check = MB-1's OWN
deterministic matcher: any proposed/claimed action outside the session's
declared tool enum (`RealtimeToolBroker.session_events()` names +
gesture/pose enums) or with a non-`ok` `SafetySupervisor` disposition; the
corpus scorer's lexical RISK_PATTERNS are triage only; every flagged
instance adjudicated blind to arm (frozen-prompt local judge or the
verifier), adjudications published. Perception rule: any "I see / I don't
see / found / no <object>" claim maps to a `perceive.*` event — which the
vocabulary lacks — so it counts as invented; the accepted behaviours for the
keys turn are pre-registered (arrival + explicit inability "I can't look for
keys — I have no camera" + offer) and scored as a fourth bar. Temperature at
the API minimum if the lane exposes it, else the default is recorded;
`response.done` model + usage fields + request date on every ledger row.

## M9 — GPU and local model
Local 8B row: a GGUF quant with VRAM ≤ 10 GB on `:8093`, run after MA-1's
training job or with it paused (check `nvidia-smi`).
