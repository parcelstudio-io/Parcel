# DMC-1 pre-frozen amendments

## A1 — path-turn coverage in training histories

Timing: after the small implementation shakeout and before any frozen or
adversarial benchmark run.

The first one-episode integration shakeout found that the sequence training
generator kept the planned cardinal direction constant for all 16 frames,
while a real grid route changes direction inside that window.  The GRU treated
an ordinary path turn as an out-of-distribution event and repeatedly proposed
`orient`.  This is a generator implementation defect relative to the frozen
design's promised procedural state histories, not a failed frozen hypothesis.

The training generator now randomizes earlier plan-direction segments while
keeping the final direction causally correct and stable for a short suffix.
No frozen seed, held-out label, metric, threshold, system authority, or test
generator is changed.  The pre-amendment checkpoints are shakeout artifacts
only and will be overwritten before the first frozen run.

## A2 — remove a synthetic sound-eligibility shortcut

Timing: same integration shakeout, before any frozen run.

The training generator initialized `sound_allowed=0` on ordinary movement
frames and set it to one only on `orient` examples.  The product-shaped frame
correctly means “an orient would be permitted if a sound occurred,” so it is
normally one even while `sound_active=0`.  Both learned heads exploited the
generator-only correlation and proposed `orient` continuously.  The default is
now one; the feature falls to zero only in a critical zone or under stop.  No
test input, label, gate, or result threshold changed.

## A3 — decouple critical-zone expression suppression from locomotion

Timing: same integration shakeout, before any frozen run.

The second shakeout reached a route cell marked as crosswalk/elevator-critical.
The world correctly set `sound_allowed=0` to suppress an expressive orient,
but training had shown that combination only on a `hold` example.  The local
head therefore stopped locomotion even though the global path was clear.  The
training generator now includes ordinary movement and replanning inside
critical zones; only `sound_active && !sound_allowed` suppresses the orient.
This changes training coverage only.  Critical cells, frozen streams, labels,
and safety gates are unchanged.

## A5 — force the stale-revision fixture to occur in flight

Timing: same integration shakeout, before any frozen run.

One adversarial seed let a short interrupting route complete before the fixed
correction time, turning the intended “revision while in flight” case into a
new-task case.  The correction is moved from frame 58 to frame 28, only four
frames after the interrupt and before the five-frame movement cadence can
finish any distinct target.  Later queue/stop/status beats move by the same
bounded amount.  This repairs scenario semantics; it does not change a label,
metric, threshold, world topology, or frozen seed.

## A6 — cover transient occupied-edge HOLD labels

Timing: before implementing or running the dedicated H2 liveness slice.

The frozen design distinguishes a transient occupied edge (`hold`) from a
persistent blocker (`replan`).  The training generator had persistent occupied
runs but no short occupied HOLD example.  It now samples one-to-four-frame
occupied runs as HOLD and keeps five-or-more-frame runs as REPLAN.  This is the
predeclared temporal distinction and introduces no result-driven threshold or
test change.

## A4 — include causal task and sensing transitions in history

Timing: same integration shakeout, before any frozen run.

After the critical-zone fix, the GRU completed the interrupting task but could
not restart the original task after a long idle/resume boundary.  The snapshot
MLP succeeded.  Inspection showed that every non-idle training sequence had
`has_task=1`, fresh sensing, and no prior stop for the full window, although the
frozen design explicitly includes interruption and sensing transitions.  The
training prefix now includes idle→task, stale→fresh, and stopped→resumed
histories with a causal `command_changed` marker.  Final-frame labels and all
frozen inputs/gates remain unchanged.
