# Day 40: Pressure, Fluids, and Weather

## Mental model

Air and water are fluids: they exert pressure, flow through openings, create drag, carry heat, and transport contaminants. Outdoor integration is not achieved by putting electronics “inside a case.” Seams, microphone ports, speaker openings, cable entries, buttons, membranes, drainage, condensation, pressure equalization, corrosion, and material aging determine environmental behavior.

An enclosure can protect against casual handling while having **no verified ingress-protection rating**. In particular, a desktop audio-array enclosure or future XVF3800-based payload is not weather-rated merely because it is enclosed. Microphones must couple to air and speakers must move air, so acoustic paths and environmental sealing must be co-designed and tested.

## Quantities, units, and assumptions

- Pressure `p`: pascals (`Pa = N/m²`).
- Fluid density `rho`: kilograms per cubic metre (`kg/m³`).
- Relative flow speed `v`: metres per second (`m/s`).
- Drag coefficient `C_D`: dimensionless and geometry-dependent.
- Projected area `A`: square metres (`m²`).
- Drag force `F_D`: newtons (`N`).

We use steady, incompressible flow and a single drag coefficient. Gusts, turbulence around legs, water droplets, capillary flow, seals, and moving geometry require richer tests.

## Core equations

```text
pressure:                 p = F/A
hydrostatic pressure:     Delta p = rho g h
dynamic pressure:         q = (1/2) rho v²
drag estimate:            F_D = (1/2) rho C_D A v²
drag-moment magnitude:    tau = F_D d_perpendicular
```

Drag grows with speed squared in this model. Doubling relative wind produces about four times the force.

## ASCII diagram

```text
wind/rain --->  [ microphone ports ]
                [ audio enclosure  ]---- cable entry
                       |
                       +---- mount on dog

air path needed for sound       water/dust path may follow it
speaker opening needed for output
"has a case" != tested seal, drain, membrane, or IP rating
```

## Worked Parcel / Go2 example

**These are illustrative environmental values, not a qualified payload load case.** Model an audio enclosure with projected area `A = 0.030 m²`, `C_D = 1.0`, air density `rho = 1.2 kg/m³`, and relative wind `v = 10 m/s`:

```text
F_D = 0.5 * 1.2 * 1.0 * 0.030 * 10² = 1.8 N
```

If the force line has a perpendicular moment arm of `0.20 m` from the mount reference:

```text
tau = 1.8 N * 0.20 m = 0.36 N m
```

At `20 m/s`, the ideal drag becomes `7.2 N`, four times larger. These numbers do not establish wind safety: gusts, robot motion, bracket dynamics, cable loads, and altered balance matter. They also say nothing about rain ingress or microphone acoustic performance behind a membrane.

## Software-engineering analogy

An enclosure is a trust boundary with physical attack surfaces. Every port is an API: it enables required exchange but also admits unwanted inputs. A chassis labeled “enclosed” without an ingress test is like an endpoint labeled “secure” because it sits behind a router.

## Parcel / Go2 bridge

A desktop bench setup can validate software streaming, duplex turn-taking, generic capture/playback, echo-guard behavior, and latency once supported devices are actually connected. It cannot validate the XVF3800 hardware-AEC reference path until that array is present and the speaker is tested through the array's own referenced DAC/amplifier path. A robot retrofit is a separate mechanical, electrical, acoustic, thermal, and environmental project. Keep the audio payload modular and declare `desktop/lab only` until its enclosure, connectors, mounts, temperature, vibration, and ingress behavior are qualified. Do not claim the purchased or future enclosure is weather-rated without a manufacturer rating and system-level test after every modification.

Companion reading: [Exteroception](../robotics-60-days/day-09-exteroception.md), [Digital audio and speech pipelines](../robotics-60-days/day-42-digital-audio-speech-pipelines.md), [Full-duplex conversation](../robotics-60-days/day-43-full-duplex-barge-in.md), and [`docs/AUDIO_LATENCY_AND_SPATIAL_INTELLIGENCE.md`](../../docs/AUDIO_LATENCY_AND_SPATIAL_INTELLIGENCE.md).

## Failure and safety note

An enclosed desktop microphone array is mounted for an outdoor demo. Rain follows a cable into the case, a speaker aperture holds water, and condensation later corrodes the board. No single software metric detects the latent damage. Until qualified, operate the audio payload only in its rated environment, keep it dry, inspect connectors, and stop operation if moisture is possible. Never spray-test powered or unrated electronics.

## Retrieval questions

1. Why does an enclosure alone not establish weather resistance?
2. How does ideal drag change when relative wind speed doubles?
3. Why do microphone and speaker apertures make environmental design harder?

## Optional 10-minute exercise

Calculate illustrative drag at `5`, `10`, and `20 m/s` for areas `0.01` and `0.03 m²`. Then draw an audio enclosure cross-section and label every possible air, water, dust, heat, cable, and force path. Do not expose any device to water.
