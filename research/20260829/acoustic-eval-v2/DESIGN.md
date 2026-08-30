# Acoustic evaluator validity rerun — design

Date: 2026-08-29 (America/New_York)

## Question

Can the existing virtual PipeWire rig make valid, non-gameable claims about
endpoint commits, acknowledgement transport, barge-in STOP, and speech/motion
prosody after the independent audit found clock and channel confounds?

## Hypotheses

- **H1 — endpoint validity:** recording every commit on the microphone loop's
  captured-sample clock will expose premature and multiple commits that a
  post-playback clock snapshot hid. A complete or pause-heavy case is valid
  only with exactly one commit after final speech. An incomplete case may have
  no commit, but no commit may precede its full incomplete hold.
- **H2 — acknowledgement clocks:** preserving the WAV sample rate and labeling
  enqueue attempt, first output-buffer write attempt, and virtual monitor onset
  separately will prevent queue time from being reported as audible time.
- **H3 — STOP validity:** mixed-minus-owner power subtraction cannot establish
  robot cessation. Unless every case has an isolated robot-output channel on a
  shared clock, the acoustic-stop gate must be `not_measured`; its old residual
  may remain diagnostic only.
- **H4 — prosody validity:** common audible origins and monotonic one-to-one
  accent matching can test virtual audio transport. With no `BeatLayer`, motion
  command, encoder, or video observation, physical motion sync must be a
  separate `not_measured` gate.

## Method

The frozen fixture and model manifest is unchanged. The revised
`virtual-pipewire-rig-v2-measurement-validity` runner executes all four
families through uniquely named PipeWire null nodes and retains one JSON
report in this directory. Existing numeric thresholds are not relaxed.
Measurement-validity failures and required-but-unmeasured capabilities make
the process exit nonzero. Teardown must leave no owned node or child process.

Before the full run, focused tests cover exact/multiple/premature endpoint
commits, incomplete early commits, ordered one-to-one matching, the prohibition
on using mixed-channel STOP diagnostics as a gate, separation of virtual audio
transport from physical motion, and rig cleanup failure paths.

The production `SpeakerSink` is exercised, including its real callback-mode
PortAudio path. Any infrastructure or callback failure invalidates the run and
is diagnosed before a retry; it is not converted into a capability score.

## Evidence boundary

This is Tier 1: no air, room, human voice, physical microphone or loudspeaker,
acoustic echo, XVF3800 AEC, spoken-STOP recognition, actuator, Go2, or Orin.
Even a procedurally clean run cannot authorize mounted audio or motion.
