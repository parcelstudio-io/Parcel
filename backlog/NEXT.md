# Next up

**Opened:** 2026-08-04 · Conventions in [README.md](README.md).

Unblocked work, ranked by impact per effort. Nothing here waits on hardware,
an install, or a decision — it can start now. Roadmap rationale lives in
[../docs/RESEARCH_2026_ROADMAPS.md](../docs/RESEARCH_2026_ROADMAPS.md).

> **Scheduled:** N1 (→W8), N2 (→W1/W2), N3 (→W3/W4), N4 (→W5/W6), N6 (→W7),
> and N8 (→W9) are cards in [../scrum/20260805/](../scrum/20260805/). They
> leave this list when their sprint acceptance lands, not when assigned.

---

## N1 — Move emote triggers onto the playback clock · **days** · closes U6

A4 built the anchor (`SpeakerSink` playback-start tokens) and `BeatLayer` uses
it; the emote path still fires at sentence-synthesis time. Move the trigger
into `_audio_chunk_started`, epoch-tag it so barge-in cancels pending
gestures, and test that a superseded sentence fires nothing.

Small, self-contained, and it removes the last place where speech and body are
scheduled on different clocks.

## N2 — Owner-trajectory prediction for following · **days**

Kalman CV/CA filter over the owner track producing a 2–3 s prediction behind a
swappable interface; `FollowOwnerController` servos the *predicted* path; an
NIS-based uncertainty brake compiled as a system-owned validator rule.

This is Follow-Bench's benchmark-winning recipe at Parcel's exact 0.1 s
timestep, and the evidence is decisive that plain Kalman suffices for a
single-owner home. Highest-leverage navigation change available.

## N3 — Dynamic agent cost layer + TTC gate on `grid_v1` · **days**

Time-decayed, forward-projected Gaussian cost lobes along each tracked agent's
predicted path, merged over the static grid each tick, plus a 1–2 s
constant-command rollout time-to-collision check compiled into validator
safety. Fixes A*'s classic failure: planning through where a person is about
to be. Skip D* Lite — repeated A* at 10 Hz is fine at this grid size.

## N4 — Jerk-limited velocity shaping · **days**

An S-curve filter between controller output and the SE2 HAL, with the existing
affect layer modulating the profile (calmer motion at low arousal). The
companion-nav eval already measures jerk, so the win is directly observable.

## N5 — Extend the BARN harness to all 300 public worlds · **days**

Today's honest 2%→44% figure is from a 50-world proxy subset. Running the full
public set produces an externally comparable score distribution with zero ROS
work — the cheapest step toward the primary external benchmark.

## N6 — `SearchOwner` reacquisition skill · **week**

Parcel currently has **no** behaviour for losing the owner, which is a
guaranteed real-world failure for a follower. Three-state machine: tracking →
go to last observed position → search (cheap in-place yaw sweep first, then
frontier search on the existing grid, pruned by a max-owner-velocity
reachability disk). Published full version reaches 97–100% reacquisition
against 51% for the best baseline.

## N7 — Emote YAML schema upgrade · **week** · reduces U10 risk

Before authoring more clips: per-clip entry/exit stance declarations, a
pose-transition graph enforced by the validator, interruptible/truncatable
flags, and feasibility gates in the kinematic preview (joint limits, per-joint
velocity/acceleration bounds, support-polygon static stability). Laban
parameterization (valence→amplitude, arousal→tempo) then turns the existing
clips into many perceptibly distinct expressions with zero ML.

Doing this *before* growing the catalog avoids re-authoring later.

## N8 — Expression metrics in the integration eval · **days**

Latency-to-acknowledgment (VAD onset → head orient), blend-continuity jerk at
layer transitions, interruption correctness (an emote firing mid-navigation
must never produce a hard collision), and emote duty-cycle caps.
Over-triggering is the documented HRI annoyance failure mode and nothing
currently measures it.

## N9 — Self-run Follow-Bench comparison · **1–2 weeks**

Port `FollowOwnerController` into the MIT-licensed, pure-Python, no-ROS
Follow-Bench harness and report success/jerk/personal-zone against its
published planners. The planner I/O is nearly isomorphic to Parcel's HAL. Pin
the evaluated commit — the paper is under review and the repo is young.

Pays three times: an external comparison number, the recipe donor for N2, and
metric alignment for the in-house eval.
