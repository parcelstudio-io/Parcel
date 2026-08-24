# A3 DISCONTINUITY-LATCH · acceptance VERDICT (Fable) · 2026-08-24

Verification: my guard run of the A3 suite + both DEC ratchets + the five
pose/localization suites = 140 passed; diff scope exactly the OWNS
(localization/ package + three new leaves + pipeline.py's three fix-5
hunks + one test file, +408/−23); the fix-5 hunks read line-by-line —
stricter-only ("a probability may REFUSE an arrival and may never
MANUFACTURE one"; detector confirmation required on inexact poses; exact
poses byte-equal); safety floors and `apply_reactive_safety` untouched;
no re-frozen number; no ported pin needed.

## Disposition: **ACCEPTED**, with the card's own acceptance criterion met

- All six A10 signals latch with journalled trigger values; the stub
  carried-signature source is typed `measured=False` and can never latch —
  honest, and its calibration is box-day work as declared.
- **The kidnap-ONSET row — the criterion NAV-CORE never exercised — now
  fires**: nominal max jump 0.0905 m, kidnap 2.6375 m journalled through
  the shipped `load_stopping_envelope_record` path (an empty journal
  publishes the sentinel, never a confident 0.0). `bridge/timing.py`
  untouched.
- The whole-map runner-up margin separates cleanly (61.07 normal vs 0.000
  aliased) and exposed a sharper fact than the card asked for: on the
  kidnap, the shipped localizer's committed winner had a WORSE residual
  than its rival (0.2932 vs 0.2532) — it commits and reports HEALTHY. The
  flag-gated path (`require_relocalization_margin`, default OFF) stays
  LOST. The flag's enablement is decided by a corpus run at the M1 nav
  acceptance row, as the executor proposed.
- Kidnap through the product path: gated 0.000 m post-kidnap; unlatched
  control 2.765 m on 109/110 HEALTHY ticks — the product now reproduces
  the harness result.
- The operator transaction is structurally one-shot (59-tick standing feed
  ⇒ exactly one re-arm; wrong pose refused AND spent; committed statements
  cannot re-arm later latches). The 4b failure mode is impossible.
- Fix-5 blast radius measured honestly: zero today (110/110 live calls
  exact-pose); the branch exists for the inexact-pose future.

Attributed reds accepted (voice_nav: two pre-existing/A2's, one flaky
fixture proven unrelated by instrumentation). Undone, correctly assigned:
the runtime installer for the latch/matcher/journal belongs to A4 SPINE
(nothing in the product installs a LocalizerProvider yet); margin flag OFF
pending corpus; carried-signature thresholds are box-day calibrations.
Does not prove: anything physical; the latch is exercised through
harness-driven product paths, not a robot.
