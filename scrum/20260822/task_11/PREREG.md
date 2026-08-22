# P2-B — PRE-REGISTRATION · written BEFORE any measurement

**Card:** `README.md` · **Executor:** Claude Opus · **Date:** 2026-08-22
Written at 02:27 local, before a single row was measured. Misses are recorded
as misses in `P2B_STATUS.md`; a row whose definition moves is declared there
with the reason.

| # | Row | Bound | How it will be measured |
|---|---|---|---|
| 1 | **greet-on-appearance** | fires exactly **once per appearance**, within **5.0 s** of the owner becoming present, on a scripted track | `OwnerEventWatcher` driven by a scripted presence track on a frozen clock; count `owner_appeared` / `owner_returned` forwards per appearance episode and measure the latency from the first present sample to the forwarded decision |
| 2 | **"I'm sad" on the hosted lane** | **1 affect ledger row + exactly 1 gesture proposal**, within one `submit_realtime_transcript` turn | drive `submit_realtime_transcript("I'm feeling sad")` on a rigged runtime with `hosted_affect: true`; count `[affect …]` ledger rows and `propose_action` calls |
| 3 | **identity verdict on every row** | **100 %** of realtime ledger rows carry a speaker label | every row written through `_write_realtime_ledger` (owner / robot / system) is stamped; measured as `labelled / written` over a mixed-traffic scenario, reported as a ratio, not a boolean |
| 4 | **zero whispers about the unenrolled gate** | **0** whisperer offers of any identity class while no owner profile is enrolled | run the unenrolled gate through the refusal and tool doors and count `KIND_VOICE_REJECTED` entries in `whisperer.decisions` |
| 5 | **greeting storms** | **≤ the configured cap** per rolling window, and ≤ 6/min under the prototype block | flood the watcher with appearance/greeting/question events on a frozen clock and count forwarded decisions inside one `window_s` |

Seeded-RED (each must fail on a tree without this card's change, for a
behavioural reason and not an import error):

* **gate-becomes-blocking** — computing an identity label must never change an
  arming decision, and the emergency class must stay ungated.
* **affect-on-legacy-only regression** — the hosted `KIND_NONE` path must keep
  producing an affect row; a tree where affect runs only on the legacy lane is
  RED.
* **greeting storms past the cap** — a watcher whose events bypassed the
  whisperer's cap/min-gap is RED.

Declared in advance: the prototype whisperer block P0-B recommends is
`max_updates_per_minute: 2` over `window_s: 30.0` — an effective **4/min**,
which is stricter than the card's "6/min". Row 5 is therefore scored against
the CONFIGURED cap, with 6/min as the ceiling it must not exceed.
