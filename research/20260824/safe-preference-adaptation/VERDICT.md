# SAFE-ADAPT — VERDICT · 2026-08-24

## Verdict: REFUTED as an enacting learner; safety/persistence mechanism confirmed

A1, A2, A5, A7 and A8 pass. A3, A4 and A6 fail, so the preregistered
hypothesis is refuted. In particular, strong stable-profile expected-regret
reduction does **not** justify enactment when negative feedback, quiet-owner
talk rate and preference-drift recovery miss their independent bars.
The recovery p95 is not estimable: 14/40 runs remained right-censored after
710--762 eligible post-shift opportunities, which is itself decisive evidence
against the 144-opportunity bar.

## Prototype decision

Retain the architecture boundary, not this policy:

- immutable safety, ODD, dialogue, health, privacy, capability and
  translation gates sit outside any learner;
- a versioned `PreferencePolicyStateV1` may record explicit per-owner likes,
  dislikes, cooldowns and evidence, with deterministic persist/replay;
- M1 may learn only from explicit approve/dislike/configuration events and
  should run any implicit learner in shadow mode;
- a preference shift or sustained negative feedback falls back to the last
  explicit profile and asks the owner to re-enroll—it must not silently
  explore more talking;
- no preference learner can grant travel, a skill, authority, wider radius or
  a safety-bound change.

Do not tune the same bandit against these same simulated profiles. The next
meaningful evidence is a small longitudinal human pilot with held-out people,
explicit feedback and annoyance/interruptibility ratings, after the mounted
non-travel expression path exists.

**Independent Fable cross-review: pending.**
