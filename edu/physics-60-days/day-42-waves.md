# Day 42: Waves

## Mental model

A traveling wave propagates a disturbance and can transport energy and information through space without carrying the material medium along over long distances. Air molecules oscillate locally while sound travels across a room; an electromagnetic field oscillates while light or radio propagates; bending disturbances travel through a bracket. A standing wave, formed by superposed opposite-going waves, can instead have zero average net energy flow while energy oscillates locally. The same vocabulary—amplitude, frequency, wavelength, phase, propagation speed, reflection, and superposition—applies to all of them, but the speeds and physical mechanisms differ.

Phase is where a cycle is at a chosen position and time. When waves overlap, their instantaneous values add. They may reinforce or cancel, so two individually strong paths can create a weak measurement at one point and a strong one a few centimetres away.

## Quantities, units, and assumptions

- amplitude `A`: units of the waving quantity, such as pascals for acoustic pressure
- frequency `f`: hertz (`Hz`)
- period `T`: second (`s`)
- wavelength `lambda`: metre (`m`)
- propagation speed `v_wave`: metre per second (`m/s`)
- phase `phi`: radian (`rad`)
- wave number `k = 2 pi/lambda`: radians per metre (`rad/m`)

A sinusoid is a useful basis, not a claim that real speech or impacts are single tones. The simple equations below assume a uniform, linear medium. Boundaries, temperature, geometry, absorption, and dispersion can change propagation.

## Core equations

~~~text
T = 1/f
v_wave = f lambda
y(x,t) = A cos(k x - omega t + phi)
k = 2 pi/lambda
omega = 2 pi f
superposition: y_total = y_1 + y_2 + ...
~~~

For two equal sinusoids, zero phase difference reinforces them; a phase difference of `pi` radians cancels them ideally. Cancellation of a field value at one point does not destroy energy everywhere—it redistributes the pattern.

## ASCII diagram

~~~text
 amplitude
    ^       crest             crest
  A |      /\                /\
  0 +-----/--\--------------/--\----> distance
           <---- lambda ---->

 direct path ---------> sensor
 reflected path ----/  -> sensor   (different delay => phase shift)
~~~

## Worked Parcel / Go2 example

At an illustrative air temperature near room conditions, use a sound speed of 343 m/s. A 1,000 Hz tone has wavelength:

~~~text
lambda = v/f = (343 m/s)/(1000 1/s) = 0.343 m
~~~

A 4,000 Hz component has wavelength about 0.0858 m. That is why centimetre-scale microphone spacing can create useful phase differences at speech frequencies. It is also why reflections from the body and nearby walls matter: path differences that look small mechanically can be a substantial fraction of a wavelength. Do not reuse 343 m/s for vibration in aluminum, light in air, or radio; each wave's medium and mechanism determine its speed.

## Software-engineering analogy

A wave resembles a replicated event seen through paths with different latency. Amplitude is not merely payload size: when delayed copies combine, timing changes the result. Two logs containing the same event can double-count or cancel in a differencing pipeline depending on alignment. Phase is the physical counterpart of that alignment.

## Parcel / Go2 bridge

Parcel's microphone array exploits spatially different arrivals; its speaker creates direct and reflected acoustic paths; camera and LiDAR use electromagnetic waves at far higher frequencies. Vibration also couples locomotion into sensors. The corresponding software pipeline begins in [Day 42: Digital Audio and Speech Pipelines](../robotics-60-days/day-42-digital-audio-speech-pipelines.md), while this lesson supplies the propagation model underneath it.

## Failure and safety note

“Noise cancellation” is not a universal subtraction knob. Cancellation requires correlated signals, suitable phase and amplitude, and a region where the model applies. A filter that cancels one microphone position may amplify another. Likewise, a structural resonance cannot be diagnosed from an audio spectrum alone without checking sensor mounting and aliases. Keep playback at hearing-safe levels and perform structural excitation at low energy.

## Retrieval questions

1. If frequency doubles while propagation speed stays constant, what happens to wavelength?
2. What determines whether two equal sinusoidal waves reinforce or cancel at a sensor?
3. Why can the same physical source have different measured amplitudes at microphones only centimetres apart?

## Optional 10-minute exercise

Calculate acoustic wavelengths at 200 Hz, 1 kHz, and 4 kHz using 343 m/s. Draw two microphones 70 mm apart and mark whether that separation is small or large relative to each wavelength. No powered hardware is required.
