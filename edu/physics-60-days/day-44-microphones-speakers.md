# Day 44: Microphones and Speakers

## Mental model

A microphone and a speaker are transducers at opposite ends of an energy chain. A microphone turns acoustic pressure and diaphragm motion into an electrical signal. A speaker turns current, magnetic force, and cone motion into acoustic pressure. Neither is transparent: each has directionality, frequency response, distortion, self-noise, mechanical resonance, and an operating limit.

The enclosure, mounting surface, ports, cable, amplifier, and robot body are part of the transducer system. Buying a good component does not guarantee good captured or radiated sound after it is bolted to a vibrating platform.

## Quantities, units, and assumptions

- microphone sensitivity: commonly volts per pascal (`V/Pa`) or decibels relative to a reference
- speaker impedance `R` or frequency-dependent `Z`: ohm (`ohm`)
- RMS voltage `V_rms`: volt (`V`)
- RMS current `I_rms`: ampere (`A`)
- electrical power `P_e`: watt (`W`)
- acoustic sensitivity: often dB SPL at a stated power and distance
- total harmonic distortion: percent or decibels

Treating a speaker as a pure resistor is only a first calculation. Its impedance changes with frequency, and the amplifier has voltage, current, thermal, and stability limits. A watt rating is usually a limit under stated conditions, not power the speaker always consumes.

## Core equations

For a resistive first approximation:

~~~text
P_e = V_rms I_rms
P_e = V_rms^2 / R
I_rms = V_rms / R
efficiency = acoustic output power / electrical input power
~~~

Microphone capture can be sketched as:

~~~text
digital_sample = ADC(gain × sensitivity × acoustic_pressure + circuit_noise)
~~~

Gain rescales signal and electronic noise; it does not undo acoustic masking, mechanical vibration, or clipping earlier in the chain.

## ASCII diagram

~~~text
 owner -> air pressure -> mic diaphragm -> preamp -> ADC -> USB samples

 USB samples -> DAC -> amplifier -> speaker coil -> cone -> air pressure
                             |             |
                         current/heat   enclosure/body
~~~

## Worked Parcel / Go2 example

Parcel's planned audio assembly pairs a microphone-array board with a nominal 4-ohm, 3-watt speaker. If a 4-ohm load actually received 3.0 W of a sinusoid under a resistive approximation:

~~~text
V_rms = sqrt(P R) = sqrt((3.0 W)(4 ohm)) = 3.46 V
I_rms = V_rms/R = 3.46 V / 4 ohm = 0.866 A
~~~

Those are illustrative electrical requirements at that operating point, not confirmation that a particular board may continuously deliver them. Peak voltage, program material, impedance variation, connector pinout, polarity, amplifier rating, enclosure, and cooling still need official verification. A lower playback level draws less average power.

Mount the microphone so the chassis does not directly inject leg and fan vibration. Mount the speaker so its cone and any port remain unobstructed. Cable strain relief matters because repeated gait motion can turn a working bench connection into an intermittent field fault.

## Software-engineering analogy

A transducer is a lossy serializer across physical domains. Its frequency response is a schema that favors some fields and attenuates others; saturation is truncation; self-noise is irreducible transport noise. An enclosure is not packaging around the service—it changes the protocol itself.

## Parcel / Go2 bridge

The desktop can validate device enumeration and the streaming voice loop, but the retrofit adds vibration, power, thermal, and acoustic coupling. Parcel should expose the selected input/output devices and clipping or underrun metrics rather than assume “default audio” is stable. Continue with [Day 42: Digital Audio and Speech Pipelines](../robotics-60-days/day-42-digital-audio-speech-pipelines.md) and [`docs/AUDIO_LATENCY_AND_SPATIAL_INTELLIGENCE.md`](../../docs/AUDIO_LATENCY_AND_SPATIAL_INTELLIGENCE.md).

## Failure and safety note

Never connect a low-impedance speaker to an unverified output merely because the connector fits. Wrong pinout, excessive current, or bridged-amplifier wiring can damage hardware. Disconnect power before rewiring, use the vendor schematic, begin at low volume, and check amplifier and speaker temperature. Avoid mounting choices that compromise weather sealing or block microphone ports.

## Retrieval questions

1. Why is a speaker's nominal impedance not a complete electrical model?
2. For a fixed resistance, how do RMS voltage and current relate to electrical power?
3. Name two ways the Go2 installation can degrade audio even if the same devices work on a desktop.

## Optional 10-minute exercise

Compute `V_rms` and `I_rms` for 0.25 W, 1 W, and 3 W into an ideal 4-ohm load. Then draw an unpowered wiring block diagram from USB host through DAC/amplifier to speaker, marking every connector whose pinout must be verified.
