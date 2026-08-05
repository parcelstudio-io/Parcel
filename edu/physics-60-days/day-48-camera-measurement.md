# Day 48: Camera Measurement Physics

## Mental model

A camera does not take an instantaneous, noiseless snapshot. During an exposure, each pixel accumulates photons and converts them into charge. Longer exposure collects more signal but also integrates motion. Higher gain brightens the digitized result but amplifies noise and reduces headroom. Many sensors expose different rows at different times, so a moving scene can be geometrically skewed by rolling shutter.

Navigation vision therefore has a time interval, not just a timestamp. On a walking Go2, body vibration and yaw can move rays substantially during that interval. The “best-looking” image for a person may not be the best measurement for low-latency geometry.

## Quantities, units, and assumptions

- exposure time `t_e`: second (`s`)
- frame period: second (`s`), inverse of frame rate
- irradiance at sensor: watt per square metre (`W/m^2`)
- photosensitive pixel area `A_px`: square metre (`m^2`)
- optical frequency `f_light`: hertz (`Hz`)
- Planck constant `h`: joule-second (`J s`)
- quantum efficiency `eta_q`: collected electrons per incident photon, dimensionless
- photon/electron count `N`: count
- focal length `f_px`: pixel
- transverse relative speed `v`: metre per second (`m/s`)
- object depth `Z`: metre (`m`)
- motion blur `b`: pixel
- row readout time: second per row (`s/row`)

The blur approximation below assumes small angles, mostly transverse motion, constant depth and speed, and ideal projection. The photon-count sketch assumes roughly fixed spectrum, irradiance, pixel area, and quantum efficiency during the exposure. Aperture affects the irradiance delivered by the lens; once sensor-plane irradiance is specified, multiply by photosensitive **pixel** area—not aperture area. Photon shot noise is only one noise source; read noise, dark current, compression, and image processing also matter.

## Core equations

~~~text
optical energy at one pixel: E_opt approximately irradiance × A_px × exposure_time
collected photoelectrons: N approximately eta_q E_opt/(h f_light)
shot-noise standard deviation approximately sqrt(N)
shot-limited SNR approximately N/sqrt(N) = sqrt(N)
transverse motion blur b_px approximately f_px v t_e / Z
rolling-shutter row time offset = row_index × time_per_row
~~~

Collecting four times as many photons improves shot-limited SNR by about two, not four. Digital gain after saturation cannot restore clipped highlights.

## ASCII diagram

~~~text
 exposure window: |---------------- t_e ----------------|
 object ray:      u_start ----------------------> u_end
 pixel receives an integrated streak, not one pose

 rolling shutter:
 row 0    [exposed first ]
 row 500          [exposed later]  -> moving pole appears tilted
~~~

## Worked Parcel / Go2 example

Assume `f_px = 500 px`, an owner 3.0 m away, transverse relative speed 0.50 m/s, and a 10 ms exposure:

~~~text
b_px = (500 px)(0.50 m/s)(0.010 s)/(3.0 m) = 0.83 px
~~~

At 50 ms, the estimate becomes 4.17 pixels. That can smear edges and shift a person box just when Parcel is turning to keep formation. Shortening exposure reduces blur but may raise gain and noise in a dim hallway. A practical system uses fresh timestamps, calibrated motion compensation where justified, and confidence that reflects illumination and blur. Values are illustrative, not specifications for the installed camera.

## Software-engineering analogy

Exposure is a database aggregation window. A longer window gives more samples but merges changing state. Rolling shutter resembles reading each shard at a different timestamp and presenting the result as one transaction. Frame timestamp policy is consistency metadata, not bookkeeping.

## Parcel / Go2 bridge

Owner following and sidewalk grounding should use the driver's documented timestamp convention and represent the exposure interval—often approximated by its midpoint—not UI arrival time. Rolling shutter may require per-row timing for precise motion compensation. LiDAR can constrain current geometry while camera semantics lag, and reactive collision safety must not wait for the next detector frame. Continue with [Day 22: Camera Fundamentals](../robotics-60-days/day-22-camera-fundamentals.md) and [`docs/COMPANION_NAVIGATION_ARCHITECTURE.md`](../../docs/COMPANION_NAVIGATION_ARCHITECTURE.md).

## Failure and safety note

Increasing exposure or temporal denoising can make demos prettier while silently adding motion error and latency. Auto-exposure can also change between tests, invalidating comparisons. Log exposure, gain, frame times, drops, and camera mode. Never allow a stale sharp frame to outrank a fresh collision measurement merely because its detector confidence is high.

## Retrieval questions

1. What tradeoff does longer exposure make between photon noise and motion blur?
2. Why can rolling shutter distort geometry even if every row is individually sharp?
3. Which timestamp should a navigation estimator associate with a frame, and why does the convention matter?

## Optional 10-minute exercise

For `f_px = 500 px`, `Z = 3 m`, and `v = 0.5 m/s`, calculate blur at 5, 10, 20, and 40 ms. Solve for the largest exposure under a 2-pixel illustrative budget. Do not change camera hardware settings.
