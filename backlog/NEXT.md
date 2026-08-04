# Next up

**Opened:** 2026-08-04 · Conventions in [README.md](README.md).

Unblocked work, ranked by impact per effort. Nothing here waits on hardware,
an install, or a decision — it can start now. Roadmap rationale lives in
[../docs/RESEARCH_2026_ROADMAPS.md](../docs/RESEARCH_2026_ROADMAPS.md).

> **Landed 2026-08-04:** N1 (W8, closed U6), N6 (W7, opened U11),
> N2/N3/N4 (W1–W6), and N8 (W9).
>
> W9 measured N2–N4 rather than assuming them, and the answers are mixed. N4
> (the shaper) is **proven**: RMS commanded jerk fell 42% across all eleven
> bench episodes, which closes most of U14. N2 (anticipation) is **not shown**
> and U12 now carries the measurement that says so. N3's gate **engages but
> does not reduce gate interventions** (new U15), while its planner half buys
> an 11% clearance margin. N6's search sequences and gives up cleanly but never
> reacquires (new U16). N8 also turned up U17: the expression stack is gated
> off for 47–84% of a follow because the owner trips the proximity gate.
>
> The four open follow-ups are U15, U16, U17, and the calm-profile remainder
> of U14. None is scheduled.

---

## N5 — Extend the BARN harness to all 300 public worlds · **days**

Today's honest 2%→44% figure is from a 50-world proxy subset. Running the full
public set produces an externally comparable score distribution with zero ROS
work — the cheapest step toward the primary external benchmark.

## N7 — Emote YAML schema upgrade · **week** · reduces U10 risk · absorbs the intensity no-op

Note (2026-08-04 sprint review): Gesture `intensity` is validated end-to-end
(0.5–1.5) and travels with the dispatch, but nothing scales the clip yet —
execution runs the YAML as authored. The prompt policy no longer advertises
the knob. Wiring intensity → duration/amplitude scaling lands here with the
per-clip schema, not before.

Before authoring more clips: per-clip entry/exit stance declarations, a
pose-transition graph enforced by the validator, interruptible/truncatable
flags, and feasibility gates in the kinematic preview (joint limits, per-joint
velocity/acceleration bounds, support-polygon static stability). Laban
parameterization (valence→amplitude, arousal→tempo) then turns the existing
clips into many perceptibly distinct expressions with zero ML.

Doing this *before* growing the catalog avoids re-authoring later.

## N9 — Self-run Follow-Bench comparison · **1–2 weeks**

Port `FollowOwnerController` into the MIT-licensed, pure-Python, no-ROS
Follow-Bench harness and report success/jerk/personal-zone against its
published planners. The planner I/O is nearly isomorphic to Parcel's HAL. Pin
the evaluated commit — the paper is under review and the repo is young.

Pays three times: an external comparison number, the recipe donor for N2, and
metric alignment for the in-house eval.
