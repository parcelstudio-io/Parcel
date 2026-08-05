# Day 51: Sampling, Aliasing, and Quantization

## Mental model

The physical world is continuous; robot software receives discrete values. Sampling chooses moments in time or directions in space. Quantization rounds amplitudes into representable levels. If a physical change occurs too quickly for the sampling process, it can masquerade as a slower change called an alias. Once aliased, the samples alone generally cannot reveal the original frequency.

Sampling faster helps only when the analog sensor and its anti-alias filtering support it. Repeating an old sample at a higher software rate creates no information. Different streams also sample different intervals: a camera exposure, a rotating LiDAR scan, an audio frame, and a controller tick do not describe one exact instant.

## Quantities, units, and assumptions

- sampling frequency `f_s`: samples per second (`Hz`)
- sampling period `T_s = 1/f_s`: second (`s`)
- physical signal frequency `f`: hertz (`Hz`)
- quantization step `Delta`: units of the measured value
- bit depth `N`: bit
- full-scale range: volts, pascals, metres, or other sensor units
- frame length `M`: samples

The Nyquist statement assumes a truly band-limited signal and uniform sampling. Real filters need a transition band, clocks jitter, samples drop, and sensors have their own bandwidth.

## Core equations

~~~text
T_s = 1/f_s
ideal no-alias condition: f_s > 2 f_max
frame duration = M/f_s
levels for N bits = 2^N
ideal uniform quantization step Delta = full_scale_range / 2^N
ideal quantization-noise RMS approximately Delta/sqrt(12)
~~~

An analog low-pass filter before the converter removes energy that would fold above `f_s/2`. A digital filter after aliasing cannot reliably separate a false low frequency from a real one.

## ASCII diagram

~~~text
 continuous signal:  /\/\/\/\/\/\/\
 slow samples:       *     *     *     *  -> appears slowly varying

 physics -> analog sensor/filter -> ADC -> timestamped samples -> software
                       anti-alias       quantization
~~~

## Worked Parcel / Go2 example

At an illustrative 16 kHz audio sample rate, the Nyquist frequency is 8 kHz. A 20 ms frame contains:

~~~text
M = (16000 samples/s)(0.020 s) = 320 samples
~~~

That frame alone contributes 20 ms of accumulation if processing waits for it to fill. Smaller frames can reduce first-result latency but increase scheduling overhead and may weaken models that need context.

Parcel's application control near 10 Hz has a 100 ms period. It cannot observe or stabilize leg/body modes requiring hundreds of updates per second. Unitree Sport samples proprioception and closes balance/gait loops at its own fast vendor-controlled rate; Parcel publishes leased body-level setpoints and monitors slower outcomes. These rates are conceptual and illustrative unless verified against the configured runtime and vendor documentation.

## Software-engineering analogy

Sampling is polling a service. A one-second poll cannot faithfully reconstruct a 20 Hz state transition, and polling a cached endpoint at 1 kHz does not help. Quantization is lossy serialization. Anti-alias filtering is upstream admission control: discard unrepresentable content before it is misidentified downstream.

## Parcel / Go2 bridge

Every observation should carry source timestamp, acquisition duration, sequence, and freshness. Audio frame size belongs in latency budgets; camera exposure belongs in geometry; scan timing belongs in motion compensation; application command rate must remain outside Sport's balance authority. Read [Day 11: Clocks, Sampling, Timescales, and Deadlines](../robotics-60-days/day-11-clocks-sampling-deadlines.md).

## Failure and safety note

A simulator may publish exact state at every physics step while production uses slower, delayed sensors. Training or testing on that oracle creates impossible software. Inject realistic sampling, quantization, jitter, and drops in evaluation. Never increase hardware control rates past a vendor boundary or disable filters merely to make a graph look more responsive.

## Retrieval questions

1. What condition must hold for ideal sampling without aliasing, and what assumption hides inside it?
2. Why can a post-ADC digital filter not generally repair aliasing?
3. Why is Parcel's application loop the wrong place to stabilize Go2 feet and body attitude?

## Optional 10-minute exercise

Calculate sample periods at 10, 30, 100, and 16,000 Hz. Compute sample counts for 10, 20, and 40 ms at 16 kHz. Then sketch which Parcel phenomena belong at each rate; do not alter live control configuration.
