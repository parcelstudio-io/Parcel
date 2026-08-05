# Day 46: Light and Radio

## Mental model

Light, infrared, and radio are all electromagnetic waves: coupled electric and magnetic fields that carry energy through space. Frequency and wavelength place them in different parts of one spectrum. Their interaction with matter differs dramatically, however. A wall that blocks visible light may weaken rather than completely block 2.4 GHz radio; dark fabric may absorb one optical band and reflect another.

Cameras measure reflected or emitted light. LiDAR actively sends light and measures its return. Bluetooth uses radio to transport data between devices. In Parcel's current design, Bluetooth is a communications/audio route—not a navigation sensor. Signal strength is too dependent on body blockage, multipath, antenna orientation, interference, and device power to treat an earphone as a trustworthy owner position.

## Quantities, units, and assumptions

- electromagnetic frequency `f`: hertz (`Hz`)
- wavelength `lambda`: metre (`m`)
- propagation speed in vacuum `c`: approximately `3.00e8 m/s`
- Planck constant `h`: approximately `6.626e-34 J s`
- photon energy `E_gamma`: joule (`J`)
- irradiance: watt per square metre (`W/m^2`)
- antenna gain: dimensionless ratio or decibels relative to a reference
- received signal strength indication: vendor-defined power estimate, commonly reported in `dBm`

The inverse-square model assumes unobstructed far-field spreading. Antennas are directional, the near field differs, and indoor reflections create constructive and destructive multipath. Device RSSI is not a calibrated range measurement.

## Core equations

~~~text
c = f lambda
photon energy: E_gamma = h f = h c/lambda
ideal point-source irradiance proportional to 1/r^2
power level: dBm = 10 log10(P / 1 mW)
~~~

For propagation in material, speed is below `c` and depends on the medium. Optical reflection and absorption depend on wavelength, surface, angle, and polarization.

## ASCII diagram

~~~text
 electromagnetic spectrum (not to scale)

 radio -------- infrared -- visible -- ultraviolet -------->
  Bluetooth       LiDAR       camera
  data link       ranging     passive image
      |               |           |
      +-- different physics roles-+

 Parcel navigation evidence: camera semantics + LiDAR geometry
 Bluetooth: transport only, not owner-location truth
~~~

## Worked Parcel / Go2 example

Bluetooth commonly operates near 2.4 GHz. Its free-space wavelength is approximately:

~~~text
lambda = c/f = (3.00e8 m/s)/(2.40e9 1/s) = 0.125 m
~~~

That 12.5 cm scale is comparable to parts of a robot body, antenna spacing, and nearby objects, so orientation and reflections can strongly affect reception. If an owner's body moves between AirPods and the robot, packets or latency may change even when distance barely changes. Parcel may use the link for microphone/speaker streaming when the operating system exposes it, but should not turn an RSSI change into “owner moved left.”

For visible green light near 550 nm, `f` is roughly `5.45e14 Hz`. Camera pixels respond to photon arrivals over an exposure; they do not directly measure object identity or metric distance. All numbers are illustrative physical scales, not device specifications or guaranteed radio range.

## Software-engineering analogy

The electromagnetic spectrum resembles one transport family with radically different physical layers. Sharing “packets” or “waves” does not make a camera interchangeable with Bluetooth. RSSI is like queue depth from a remote service: useful for link diagnostics, but an unreliable proxy for physical distance unless a much stronger calibrated model exists.

## Parcel / Go2 bridge

Keep RF below the sensor-trust boundary. Bluetooth can feed audio into Parcel's duplex pipeline, while camera and LiDAR remain the environmental sensors used for navigation, owner tracking, objects, and free space. Review [Day 09: Exteroception](../robotics-60-days/day-09-exteroception.md) and [`docs/AUDIO_LATENCY_AND_SPATIAL_INTELLIGENCE.md`](../../docs/AUDIO_LATENCY_AND_SPATIAL_INTELLIGENCE.md).

## Failure and safety note

Radio links can disconnect, change profiles, buffer, or add unpredictable latency. Loss of an earphone route must not leave a motion command alive; leased commands and local safety remain mandatory. Avoid claiming Bluetooth direction or distance without dedicated calibrated hardware and validation. Never aim high-power optical sources at eyes; use only commissioned camera/LiDAR hardware and vendor-safe enclosures.

## Retrieval questions

1. What relationship connects electromagnetic frequency and wavelength?
2. Why is Bluetooth RSSI not a reliable owner-range measurement on a moving robot?
3. What distinct physical roles do Parcel's camera, LiDAR, and Bluetooth link play?

## Optional 10-minute exercise

Calculate wavelengths for 2.4 GHz and 5 GHz radio, 850 nm infrared, and 550 nm visible light. Then draw a trust-boundary diagram labeling Bluetooth “transport” and camera/LiDAR “navigation observations.” No radio transmission is required.
