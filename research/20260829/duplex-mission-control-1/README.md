# DMC-1 — duplex mission control and truthful narration

DMC-1 is an isolated, procedural semantic-stream experiment for a split-rate
Model A / Model B architecture. It ran 1,500 frozen/adversarial episodes across
five arms, plus 5,000 obstacle-liveness cases and two reproducibility runs.

Read in this order:

1. `DESIGN.md` — frozen hypotheses, systems, splits, gates, and evidence limit;
2. `AMENDMENTS.md` — pre-result shakeout changes;
3. `RESULTS.md` / `results.json` — raw measurements and automated gate output;
4. `REVIEW_TEST_PLAN.md` / `adversarial-review-results.json` — post-run validity
   counterexamples;
5. `VERDICT.md` — controlling interpretation after independent Sol Ultra
   review; and
6. `POSTRUN_NOTES.md` / `verification.json` — reproducibility details.

The automated `results.json` says H1–H5 passed and H6 failed. The controlling
independent verdict is stricter: receipt/narration-oracle counterexamples make
H3/H4 unverified; H1/H2/H5 are narrower than worded; H6 is refuted. The
strongest system in mission reliability was the deterministic L0 baseline, not
the learned history policy. Nothing here authorizes motion or changes the
physical-mount **NO-GO**.

