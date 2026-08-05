# Day 43: Sound and Decibels

## Mental model

Sound in air is a changing pressure field around the ambient atmospheric pressure. A microphone senses tiny pressure variations; it does not receive “words.” Distance, source direction, wind, the robot body, and reflecting surfaces reshape those variations before software sees them.

Human hearing and acoustic powers span enormous ratios, so levels are commonly expressed in decibels. A decibel is a logarithmic ratio, not an absolute unit by itself. For sound-pressure level, the reference in air is usually 20 micropascals. Adding decibel values as ordinary linear numbers is a category error.

## Quantities, units, and assumptions

- acoustic pressure `p`: pascal (`Pa`), often represented by an RMS value
- reference pressure `p_ref`: `20 uPa` for airborne sound
- sound-pressure level `L_p`: decibel (`dB re 20 uPa`)
- acoustic intensity `I`: watt per square metre (`W/m^2`)
- distance `r`: metre (`m`)
- speed of sound `c`: metre per second (`m/s`), about 343 m/s in a simple room-temperature estimate

The free-field distance rule assumes a compact source radiating into unobstructed space. Rooms, the ground, directionality, near-field behavior, and automatic gain control violate it.

## Core equations

~~~text
L_p = 20 log10(p_rms / p_ref)
pressure ratio from level difference: p_2/p_1 = 10^(Delta L/20)
ideal spherical spreading: I proportional to 1/r^2
free-field pressure change: Delta L = -20 log10(r_2/r_1)
propagation delay: t = d/c
~~~

Doubling distance gives approximately `-6 dB` in the free field. Doubling acoustic intensity is about `+3 dB`; doubling pressure amplitude is about `+6 dB` when impedance is unchanged.

## ASCII diagram

~~~text
 owner voice ))) ))) )))      robot microphone
      *--------- r ---------> [mic]
       \                       ^
        \---- reflection -----|

 pressure waveform -> preamp -> ADC -> samples
 distance/body/room alter it before the ADC
~~~

## Worked Parcel / Go2 example

Suppose an owner's speech measures an illustrative 66 dB SPL at 1 m in a quiet test. Under ideal free-field spreading, at 2 m:

~~~text
Delta L = -20 log10(2/1) = -6.02 dB
predicted level = about 60 dB SPL
~~~

Now add a city background near 60 dB SPL. If speech and background are measured over compatible bandwidth, weighting, and time windows, that is a nominal `0 dB` signal-to-background ratio. The speech has not disappeared, but separation has become difficult. Beamforming, source direction, and language context may help; simply turning up microphone gain amplifies both speech and background and may clip louder events. The values are illustrative, not a guaranteed owner-detection range. Do not add the two dB values arithmetically; convert compatible uncorrelated levels to linear power before combining them.

As another scale check, 60 dB SPL corresponds to:

~~~text
p_rms = (20 uPa) 10^(60/20) = 0.020 Pa
~~~

That tiny variation rides on atmospheric pressure near 100,000 Pa, which explains why microphone electronics and mechanical isolation matter.

## Software-engineering analogy

Decibels resemble logarithmic latency histograms: a compact representation of a huge range. You must know the reference and whether the log represents amplitude or power before converting. Microphone gain is like increasing log verbosity after a service has saturated—it cannot restore information already clipped or buried below noise.

## Parcel / Go2 bridge

Parcel should retain physical context with audio metrics: input level, clipping rate, noise estimate, device and route, frame time, and speech endpoint. Those metrics explain why identical ASR code behaves differently in a hallway and on a sidewalk. Pair this lesson with [Day 42: Digital Audio and Speech Pipelines](../robotics-60-days/day-42-digital-audio-speech-pipelines.md) and [`docs/AUDIO_LATENCY_AND_SPATIAL_INTELLIGENCE.md`](../../docs/AUDIO_LATENCY_AND_SPATIAL_INTELLIGENCE.md).

## Failure and safety note

Do not infer hearing safety from a digital volume percentage or an uncalibrated microphone's dBFS reading. dBFS is relative to digital full scale, not directly dB SPL. A clipped waveform cannot be recovered by downstream reasoning. Avoid loud test signals near people or animals; use a calibrated meter and applicable exposure guidance for hardware commissioning.

## Retrieval questions

1. Why must a decibel value include or imply a reference?
2. Under an ideal free-field model, how much does pressure level change when distance doubles?
3. Why does increasing microphone gain not improve the acoustic signal-to-noise ratio before the microphone?

## Optional 10-minute exercise

Compute predicted free-field changes from 1 m to 0.5 m, 2 m, and 4 m. Then list three reasons a hallway measurement may disagree. Keep all playback off; this is a desk calculation.
