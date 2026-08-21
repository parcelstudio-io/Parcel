# AUDIT — the overnight arc (EV-1 → R27, PG-1 → PG-3) · Fable · 2026-08-21

**Scope:** eleven cards executed while the Fable audit was deferred at the
owner's request: EV-1, F1-SI (2026-08-20/21), R22–R27, PG-1–PG-3
(2026-08-21). **Verdict: ACCEPT_CLOSE on all eleven**, with the corrections
and register entries below. Quality adjustments the owner authorized were
made directly by the auditor and are themselves gated.

## Independent evidence (all first-hand, sole tree owner)

* **Gate:** PASS at 7,711 before my adjustments; PASS at **7,715** after
  them (my 4 new test cells). Every hard gate green, including the two the
  arc itself added (`assertion-evals`, `owner-store-isolation`) and
  `tier-coverage` (no orphans, no overlap).
* **Solo seed sweeps, cache-purged, against current bytes:** EV-1 34/34 ·
  F1-SI 42/42 · R22 36/36 · R23 12/12 · R24 18/18 · R25 19/19 · R26 10/10 ·
  PG-1 12/12 · PG-2 all-RED · PG-3 20/20 · R27 12/12 — **~245 seeds RED**,
  every restore byte-identical, resolving the verifiers' stale-sweep flags.
* **The owner's conversation store hash was unchanged across my entire
  audit cycle** (`40506fd9…` before and after) — the audit held to R27's
  own standard.

## Register entry 1 — the store-pollution incident (the arc's process lesson)

Four consecutive chains wrote **256 synthetic rows** into the owner's live
conversation store, while status docs claimed isolation in good faith. The
trap was structural (`memory.path` resolved against CWD — flagged as R5
open risk 5 and never built) and had even shipped inside the gate itself
(a test constructed a runtime against the real store on every `ci_gate`
run). R27 closed it at the chokepoint, fail-closed, with per-row writer
provenance and a new HARD gate. **Lesson, now mechanical:** an isolation
claim requires a before/after measurement; convention was tried four times
and failed four times; the gate does not forget. The 256 rows remain —
quarantine tooling is built and dry-run-verified (2,882 retained, matching
the pre-incident total exactly), and **the trigger stays with the owner.**

## Register entry 2 — evidence-citation drift

Six status docs carried claims their own artifacts did not support: PG3's
"nothing was run live" (false re: the store), R23's phantom test citation,
R22's artifact mislabel, PG1's non-closing collection arithmetic, R26's
gate.txt misquote, EV-1's digit typo. All corrected by **appended, dated
notes — never rewrites**. None affected a behavioral claim; all affected
the audit trail, which is why they are corrected rather than shrugged at.

## Register entry 3 — R27's conduct is the new self-reporting standard

Its irony clause fired (its own seeds altered the store's hash via the
migration), it quantified the delta (one nullable column, zero rows), and
it explicitly declined to overwrite live conversation data to make a hash
match — naming that instinct as the incident's own root cause. That is the
bar.

## Quality adjustments made by the auditor

1. **PG3's R20-equivalence test strengthened** — the shipped test compared
   the perception verdict against a hand-built `PlaceAdmission` and never
   executed R20's code. Added
   `test_r20s_live_gate_refuses_the_same_rows_through_its_real_code`
   (4 param cells): invokes the real `admit_navigation_place` with the
   sidecar-derived vocabulary; all four corpus rows (narnia, my office,
   moon, home) refuse through the live gate with the shared refusal
   template. In the process the auditor's first draft tripped
   `_join_places([])` (IndexError) — investigated and found **guarded in
   production** (`reply()`/`fact()` branch before reaching it); no library
   change warranted.
2. The six append-only corrections above.

## Quality of the overnight work itself

High, by the standard the register demands: three executors overturned
their own cards' premises with measurements rather than shipping them
(R19's four silence mechanisms; R20's missing ask-path; PG-3's "the
detector is not innocent — the moon fires at 0.338 — and what refuses it is
physics"); PG-1 refuted three inherited performance numbers including two
of the auditor's own; benches pre-registered criteria and disclosed their
own metric flaws (PG-2's uninformative containment). The two systemic
stains — store pollution and citation drift — are now respectively
structural-closed and corrected.

## Standing owner decisions (unchanged, no urgency)

The 256-row cleanup (quarantine / delete / leave) · the world-simulator
fork (recommendation on file: texture the city now, Habitat as the
held-out evaluation venue) · the udev rule for DoA · the one-minute voice
enrollment.
