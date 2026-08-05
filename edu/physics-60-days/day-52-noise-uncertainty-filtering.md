# Day 52: Noise, Uncertainty, and Filtering

## Mental model

Noise is variation in measurements or processes. Uncertainty is what you do not know about the physical quantity after considering noise, bias, calibration, model error, and stale time. A smooth number is not automatically an accurate number. Filtering can reduce random variation, but it spends bandwidth and delay; it cannot manufacture observations of an occluded owner or correct an unknown frame transform.

State estimates should carry a scale of uncertainty and freshness. Those values affect behavior: slow down, seek another view, ask for clarification, enlarge clearance, or refuse completion. Hiding uncertainty behind one “confidence” float makes different failure sources impossible to reason about.

## Quantities, units, and assumptions

- mean `mu`: same unit as measurement
- error standard deviation `sigma`: same unit as measurement
- variance `sigma^2`: squared unit
- covariance matrix `Sigma`: entry `(i,j)` has the product of state-component units; diagonal entries have squared units
- signal-to-noise ratio: dimensionless or decibel (`dB`)
- low-pass time constant `tau`: second (`s`)
- cutoff frequency `f_c`: hertz (`Hz`)
- measurement age: second (`s`)

Gaussian, independent, zero-mean noise is a useful starting model, not a universal truth. Outliers, multipath, model bias, motion, and shared calibration error violate it.

## Core equations

~~~text
error e = measurement - reference
variance sigma^2 = E[(e - E[e])^2]
covariance Sigma_ij = E[(x_i-mu_i)(x_j-mu_j)]
independent average standard deviation = sigma/sqrt(N)
first-order low-pass: tau y_dot + y = x
cutoff f_c = 1/(2 pi tau)
SNR_power = 10 log10(P_signal/P_noise)
~~~

Independent averaging reduces random noise, but a moving target changes during the window. Filtering trades variance for lag and does not reduce constant bias.

Bandwidth must be stated for every quoted noise number. A sensor can look quieter simply because its output filter removed fast variation, including real events Parcel needed to observe.

## ASCII diagram

~~~text
 true range ----------- changing owner position -------->
 raw samples:       * *  *   ** * *
 filtered:          -----smooth but delayed----->
                                        ^
                              low noise is not freshness
~~~

## Worked Parcel / Go2 example

Assume a stationary range measurement has illustrative independent zero-mean noise `sigma = 0.06 m`. Averaging four samples gives:

~~~text
sigma_average = 0.06 m / sqrt(4) = 0.03 m
~~~

But if the owner walks at 1.0 m/s and those samples span 0.20 s, the physical range can change by 0.20 m—much larger than the random-noise improvement. A filter tuned on a static desktop can make owner following laggy and reduce stopping margin. Parcel should predict a moving track, retain age/covariance, and let reactive LiDAR safety use fresher geometry rather than wait for a smooth semantic estimate.

The noise and motion values are illustrative. Real distributions must come from timestamped logs on relevant surfaces, lighting, ranges, and gaits.

## Software-engineering analogy

Filtering resembles caching and batching. Both reduce variance or load but return older state. A cache hit is not correctness if the freshness requirement has expired. Covariance resembles a typed error budget propagated through a pipeline rather than one global health boolean.

## Parcel / Go2 bridge

Camera confidence, LiDAR range quality, owner-track covariance, odometry freshness, and controller feedback age belong in separate fields. Navigation can then use soft costs for uncertain dynamics while collision gates remain conservative. Read [Day 12: Signals, Noise, Filtering, and Delay](../robotics-60-days/day-12-signals-noise-filtering-delay.md) and [`docs/COMPANION_NAVIGATION_ARCHITECTURE.md`](../../docs/COMPANION_NAVIGATION_ARCHITECTURE.md).

## Failure and safety note

Do not tune a filter only for a visually pleasing dashboard. Too much smoothing hides impacts and approaching obstacles; too little can chatter commands. Never report lower covariance merely because the filter has not received a contradictory measurement. Missing, stale, and invalid are observations about availability, not evidence of certainty.

## Retrieval questions

1. How do noise and uncertainty differ?
2. Under what assumptions does averaging `N` samples reduce standard deviation by `sqrt(N)`?
3. Why can a smoother owner track produce worse following or stopping behavior?

## Optional 10-minute exercise

For `sigma = 0.08 m`, calculate the ideal standard deviation after averaging 1, 4, 16, and 64 independent stationary samples. At 20 Hz, compute each window duration and how far a person moving 1 m/s travels. Explain which error dominates.
