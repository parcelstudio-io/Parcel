# Day 45: Echo and Full-Duplex Acoustics

## Mental model

In full duplex, the robot listens while it speaks. The microphone therefore receives the owner plus a usually much stronger, delayed, filtered copy of the robot's own playback. Acoustic echo cancellation (AEC) estimates that playback-to-microphone path and subtracts its predicted echo. It can do this only when it receives a time-aligned **render reference** representing the samples that actually drive the relevant speaker path.

The reference is not “whatever audio the application intended to play,” and it is not a second microphone. It is the render stream from the same playback/DAC clock and routing whose output passes through amplifier, speaker, robot body, air, reflections, and finally the microphones. An adaptive filter learns those downstream effects.

## Quantities, units, and assumptions

- discrete sample index `n`: dimensionless
- sample rate `f_s`: samples per second (`Hz`)
- acoustic path delay `tau`: second (`s`)
- impulse response `h[k]`: path gain over delayed samples
- microphone signal `y[n]`: digital amplitude
- near-end owner speech `s[n]`, render reference `x[n]`, noise `w[n]`
- echo-return loss enhancement (ERLE): decibel (`dB`)

Linear convolution is an approximation. Real speakers clip, enclosures vibrate, people move, automatic gain changes, and clocks drift. AEC usually works with delay estimation, nonlinear processing, and double-talk detection as well as an adaptive linear filter.

## Core equations

~~~text
microphone: y[n] = s[n] + sum_k h[k] x[n-k] + w[n]
predicted echo: e_hat[n] = sum_k h_hat[k] x[n-k]
AEC output: s_hat[n] = y[n] - e_hat[n]
acoustic propagation: tau_acoustic = distance / speed_of_sound
total reference alignment: tau_total = tau_device + tau_buffer + tau_acoustic
ERLE = 10 log10(P_echo / P_residual_echo)
~~~

If `x[n]` is absent, unrelated, or on an uncontrolled clock, correlation cannot reliably identify `h[k]`. Subtracting the outgoing text, TTS tokens, or a different speaker's stream is not equivalent.

## ASCII diagram

~~~text
 far-end/TTS x[n] -> board DAC -> amp -> wired speaker -> room/body -> mic y[n]
           |                                                      |
           +---------- exact render reference -------------------+
                                                                  v
 owner s[n] ------------------------------------------------> [ AEC ] -> ASR

 separate USB speaker: playback bypasses board DAC/reference  X
~~~

## Worked Parcel / Go2 example

Assume an illustrative dominant acoustic playback path length of 2.0 m after including a reflection. At 343 m/s, the acoustic portion is:

~~~text
tau = 2.0 m / 343 m/s = 5.83 ms
samples at 16 kHz = 0.00583 s × 16000 1/s = about 93 samples
~~~

That `93`-sample result is **not** the complete render-to-microphone alignment. Playback buffers, USB scheduling, DAC/amplifier and speaker delay, microphone/ADC buffering, and any sample-rate conversion add delay that distance alone cannot predict. Many reflected paths also extend farther, so the adaptive filter needs a longer window than the first arrival. If Parcel uses the array board's onboard AEC, wiring the speaker to that board's supported amplifier/output path lets the board observe the render samples on its own DAC clock. A separate USB-first speaker follows another device, buffer, mixer, and clock; the board's onboard AEC has no guaranteed reference for what that speaker emitted, so cancellation can collapse.

This is an architecture fact, not a claim that AEC is impossible with every separate speaker. Host-based AEC can support separate devices **if** the host captures the exact render stream, estimates routing delay and clock drift, and is designed for that topology. It does not make the array board's internal, unreferenced AEC work magically.

## Software-engineering analogy

AEC is change-data capture for a side effect. To predict the replica state, you need the exact committed write stream, ordered on the relevant clock—not the request object before retries, mixing, gain, and routing. The acoustic impulse response is the learned downstream transformation; double-talk is concurrent legitimate writing by the owner.

## Parcel / Go2 bridge

Reliable barge-in depends on this physical topology before ASR or reasoning quality matters. Parcel should log input/output device identity, route changes, playback timestamps, overruns, AEC state, double-talk decisions, and query-end latency. Pair this with [Day 43: Full-Duplex Conversation and Barge-In](../robotics-60-days/day-43-full-duplex-barge-in.md) and [`docs/DUPLEX_DUAL_STREAM_DESIGN.md`](../../docs/DUPLEX_DUAL_STREAM_DESIGN.md).

## Failure and safety note

AEC is not a safety shield against acoustic feedback, clipping, or excessive level. Moving the speaker, changing gain, touching the enclosure, or switching routes changes the echo path. Playback should start quietly; route changes should reset or reconverge the canceller; the robot should fail to half-duplex or pause speech when echo confidence is poor rather than interpret its own voice as an owner command.

## Retrieval questions

1. What exactly must the AEC render reference represent?
2. Why does a separate USB speaker usually defeat an array board's onboard AEC even though both connect to the same computer?
3. Under what additional architecture could AEC still work across separate input and output devices?

## Optional 10-minute exercise

Draw Parcel's actual intended audio route, including USB host, render buffer, DAC, amplifier, speaker, room, microphones, and AEC reference tap. For path lengths of 0.5 m, 2 m, and 5 m, calculate delay and sample count at 16 kHz. Do this unpowered.
