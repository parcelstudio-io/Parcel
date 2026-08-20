# Parcel Full Audit · Fable · 2026-08-20

Six independent read-only auditors (safety paths, architecture, test-suite
quality, evals integrity, robot quality, security/ops), instructed to treat
every status doc and prior audit as a CLAIM and verify against code and
data. All 33 critical/major findings then went through adversarial
refutation by fresh agents reading the same files: **25 CONFIRMED,
5 PARTIAL, 3 REFUTED.** R17–R21 files were mid-execution and excluded from
blame. Full structured findings with evidence rows: the workflow output
(w85fhexwx); this document is the synthesis.

## The two confirmed CRITICALs — both already in the pipeline, now with harder evidence

1. **Any ambient voice commands the robot.** The Korean TV was ledgered as
   `speaker: owner` with full command authority in BOTH human sessions.
   → F1-SI (task_12, armed) is the fix; the audit confirms nothing else
   defends this (AEC is structurally irrelevant to third-party audio).
2. **A latched robot has no voice.** 84 seconds / 18 owner turns over an
   engaged e-stop with one accidental disclosure. → R19 (rejection
   narration) + R21 (status-under-latch, safety ring) are mid-flight.

## Confirmed findings NOT previously known or carded

### Safety
* **The realtime pump thread dies permanently and silently on any
  exception outside a four-type catch list** — and the conversation-ledger
  write (raw sqlite, no wrapper) sits on that thread. A disk-full or
  locked-DB error mid-turn kills the pump, and with it the SPOKEN E-STOP,
  the stall watchdog, rollover, and idle-close, while the mic stays open
  and nothing alarms. The driver docstring's "records the failure and
  keeps going" is untrue outside the caught types. (driver.py:136,217;
  lane.py:1389; memory.py:114) — the refuter verified the full exception
  MRO chain and strengthened the finding.
* **robot.yaml velocity limits are not fail-closed:** NaN silently
  disables the clamp in BOTH the arbiter and the SafetySupervisor
  (`abs(v) > NaN` is always False); inf/zero/negative accepted. PARTIAL
  only because the shipped config is digest-pinned — any operator
  `--config` path is exposed. (config.py:73; safety.py:9,138)
* Minor but doctrine-relevant: a panel-origin e-stop latches the arbiter
  but NOT the SafetySupervisor (no actuation hole today — every path was
  traced — but the broker's documented invariant is false for that
  origin); and a typed "Stop." with punctuation misses the legacy lane's
  fast path (the hosted lane strips punctuation; the typed lane does not).

### Architecture
* **The realtime motion doors mutate VoiceAgent state without
  `_agent_lock`** — cross-thread, the exact class the lock exists for.
* **The sqlite3.Error blindspot repeats across three stacked catch-lists**
  on the transcript path (same family as the pump finding).
* **docs/CONVERSATIONAL_AUTONOMY_HIGH_LEVEL_DESIGN.md is materially stale**
  — accurate at its 2026-08-15 audit stamp, never re-audited across
  R1–R16; the owner reads this file.
* **runtime.py is a fully-formed god object:** 8,926 lines, 226 methods,
  ~968-line `__init__`, 6 locks, 4+ threads. The lock ORDERING is a
  verified DAG (healthy), but the growth rate is the risk.

### Tests
* **The entire voice-to-nav e2e tier (42 deselected tests) has never run**
  — the nightly that should run it has no recorded run anywhere.
* **Three load-sensitive wall-clock tests sit inside the HARD commit gate**
  with no owning card, having reddened ≥6 gate runs across four cards.
* **ui/index.html — 2,365 lines carrying the browser half of the Space
  e-stop, mic capture, and playback — is executed by zero tests**; every
  pin is a string assertion.
* **FakeRealtimeServer never validates payload shapes** and never emits
  two server events every real audio session produces — a lane-level green
  can lie about wire behavior the R8 probes proved.

### Evals
* **The E1 and shadow-run verdict code exists ONLY in session-scoped /tmp
  scratchpad** — the certificates are in the repo, the certifier is not.
  (EV-1's card fixes exactly this; the audit raises its priority.)
* **The frozen nav-safety baseline (2026-08-11) predates the entire R10/
  R14/R20 arrival stack** — it still gates, but it exercises pre-arrival
  code paths; follow-bench rows predate person-aware yield.
* **The latency-tail ratchet is vacuous for 4 of its 6 pinned metrics**
  and its pass message overstates its check.
* **acoustic_loop_v1 is flagged frozen with no digest enforcement**;
  the E1 pack's manifest no longer covers its own R14 addendum files.
* Coverage nothing-list (PARTIAL — some items landed mid-audit): compound
  commands, ambiguous-goal asks, capability-honesty class, barge-in mark
  truth, multilingual policy — no offline test, no recorded eval, or both.

### Robot quality (beyond the criticals)
* **Verified arrival works for 1 of 5 shipped object classes** (lamppost
  yes; planter/door and others fail semantic arrival in R14's own control
  data) — arrival semantics exist; arrival RELIABILITY does not.
* **Spoken e-stop evidence is one-sided:** canonical "Die stop" is 7/7
  live; the ASR-variant positives remain untested (q34 still open).
* **"Executed" ≠ performed:** nothing anywhere reaches a real joint; the
  kinematic rig means every gesture proof is a dispatch record (known,
  now formally on the record).
* Cost/latency are budgeted, never verified (rates_are_assumed on every
  ledger row; N19 still unlanded).

### Ops
* **THE UNCOMMITTED WAVE — the project's single largest operational risk,
  named independently by three lenses:** ~3.5 days of closed, audited
  work — the entire hosted voice lane, its tests, its audit trail, and
  irreplaceable live evidence — exists only in one working tree. A disk
  failure erases the arc. Landing is a 5-minute owner decision.
* **monthly_budget_usd is a documented control that does not exist:** the
  arming gate never reads it. False documented safety = must fix or
  un-document.
* requirements-lock drift (16 packages absent); the 14.4 GB Gemma weight
  has no provenance lock (the judge does); status docs cite /tmp evidence
  paths that will evaporate.

## Refuted (dropped, on the record)
Junk-place seam-coverage gap (refuted with code evidence); both
recording-privacy majors (refuted — existing ignore rules and R17's
card constraints already cover the claimed exposure; a privacy note
remains worthwhile, the LEAK claim was wrong).

## What is genuinely healthy — verified, not assumed
The hosted-model→actuation boundary is closed on every constructible path;
the motion gate is fail-closed in all three directions; emergency-latch
engagement is synchronous and correctly ordered at every origin; B22 is
diff-verified unweakened across the whole wave; lock ordering is a
verified DAG; the realtime package is cleanly dependency-inverted; median
assertion depth across 5,114 test functions is high with seeded-violation
companions; all sampled frozen digests (corpus, E1, judge model 19.7 GB)
verify byte-for-byte; credential handling is clean end-to-end; the spend
ledger is honest about its own assumptions; whisperer discipline holds in
the field (1 forwarded / 74 suppressed).

## Remediation plan

**P0 — owner (5 min): LAND THE WAVE.** Everything else is secondary to
not losing the arc.
**P0.5 — already armed:** EV-1 (moves the verdict code into the repo +
gate), F1-SI (critical 1), R19/R21 (critical 2) — in flight or queued.
**New cards, queued after the current pipeline (R22+):**
R22 pump/thread resilience (broad catch + death alarm + revival; the
sqlite blindspot family fixed everywhere) · R23 fail-closed SafetyLimits ·
R24 realtime-door lock discipline + cross-thread compound state · R25
budget arming refusal made real · R26 the nightly stood up (deselected
tier runs; load-sensitive tests relocated with load guards) · R27
baseline re-freeze v5 over the current nav stack + follow-bench re-run ·
R28 arrival reliability across all object classes · R29 owner-doc
re-audit · R30 evals hygiene (latency ratchet, acoustic sentinel, E1
addendum seal, lock-file refresh, Gemma provenance).
**Debt registered, not scheduled:** runtime.py decomposition; panel JS
test harness; embodiment beyond the kinematic rig.
