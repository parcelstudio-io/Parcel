# Day 49: LiDAR Time of Flight

## Mental model

LiDAR estimates range by sending light and measuring a return. Because the pulse or modulation travels to a surface and back, range is half of propagation speed times round-trip delay. A scan is a set of rays with directions, ranges, return qualities, and times—not a solid wall map.

A missing return does not mean free space. The ray may have missed a thin object, struck glass, exceeded range, been absorbed by a dark surface, or been degraded by rain, sun, incidence angle, or another sensor. Occlusion also means a valid near return says nothing about what lies behind it.

## Quantities, units, and assumptions

- round-trip delay `Delta t`: second (`s`)
- range `R`: metre (`m`)
- light speed `c`: approximately `3.00e8 m/s` in air for this estimate
- angular spacing `Delta theta`: radian (`rad`)
- beam divergence: radian (`rad`)
- range uncertainty: metre (`m`)
- scan or point timestamp: second (`s`)

The simple formula assumes a direct path and known timing. Real devices may use pulsed, phase, or frequency-modulated techniques and proprietary filtering. Use the sensor's documented uncertainty and invalid-return semantics rather than inferring them from the equation alone.

## Core equations

~~~text
R = c Delta_t / 2
round-trip time = 2R/c
lateral spacing at range R approximately R Delta_theta
small-angle beam diameter growth approximately R × divergence
~~~

For angular quantities, convert degrees to radians before using the small-angle approximation.

## ASCII diagram

~~~text
 LiDAR * ---- outgoing light ----> surface
       * <--- reflected return ---/
             path length = 2R

 adjacent rays: \  Delta theta  /
                 \             /
 spacing grows with range; thin objects can fall between rays
~~~

## Worked Parcel / Go2 example

For an illustrative object at 10 m:

~~~text
Delta t = 2R/c = 20 m / (3.00e8 m/s) = 66.7 ns
~~~

That tiny interval explains why precise timing and calibration are hardware problems, not a Python timer call. If adjacent horizontal rays were 0.5 degrees apart, convert to `0.00873 rad`:

~~~text
spacing approximately (10 m)(0.00873) = 0.0873 m
~~~

A narrow pole can be sparsely sampled at that distance. These values are illustrative and are not specifications of the Go2's installed LiDAR. Parcel should use LiDAR for measured free-space and obstacle geometry, camera for “lamppost” or “sidewalk” semantics, and conservative unknown-space handling where returns are absent.

Return amplitude is also not a universal material label. It depends jointly on emitted power, range, incidence angle, surface reflectance at the sensor wavelength, receiver response, and device processing. The same curb can report differently when wet or viewed obliquely. Use quality fields according to the vendor contract and validate them on relevant surfaces; do not teach a semantic model that “weak return means glass” as a general rule.

## Software-engineering analogy

A LiDAR scan resembles a sparse index query, not a full table dump. Each ray reports the first eligible result under device rules; null may mean many different failure modes. Angular resolution is the index granularity, while motion during a scan is a consistency problem across timestamps.

## Parcel / Go2 bridge

The rolling grid and reactive safety layer need calibrated, fresh points in the body or odometry frame. Semantic navigation should never replace those ranges with a model's guessed depth. Read [Day 23: LiDAR Fundamentals](../robotics-60-days/day-23-lidar-fundamentals.md) and the obstacle pipeline in [`docs/NAVIGATION_CITY.md`](../../docs/NAVIGATION_CITY.md).

## Failure and safety note

Glass, mirrors, black materials, rain, dust, direct sun, occlusion, and multi-path can create missing or misleading returns. Simulator rays are often unrealistically clean. Treat invalid or stale sectors as unknown according to a tested policy, preserve an independent stop margin, and never demonstrate near eyes with uncommissioned optical emitters.

## Retrieval questions

1. Why is the factor of one-half present in the time-of-flight range equation?
2. How does fixed angular spacing translate into spatial spacing as range grows?
3. Why must “no LiDAR return” not automatically become “free space”?

## Optional 10-minute exercise

Calculate round-trip light times for 1, 5, 10, and 30 m. For angular steps of 0.25 and 1 degree, compute lateral spacing at 2 and 10 m. Then sketch a thin pole that falls between two rays.
