# Day 60: Parcel Physical Design Review

## Mental model

A production robot is one physical evidence chain. Voice does not end at text, navigation does not end at a path, and control does not end at an acknowledged RPC. A design review traces energy, information, uncertainty, latency, authority, and failure recovery from the owner through the environment to foot-ground contact and back to measured task completion.

The capstone question is: **which stated measurement could falsify every important assumption?** If an assumption has no measurement, bounded model, or safety fallback, it is not ready for hardware. Parcel's reasoning model may propose semantic skills; camera and LiDAR ground the environment; deterministic planning and safety admit motion; `ControlManager` remains the single writer; Unitree Sport closes fast balance and gait.

## Quantities, units, and assumptions

The review must inventory at least:

- audio sample/frame rate, render route, echo-path delay, clipping, and device clocks
- camera exposure/intrinsics/extrinsics and LiDAR range, scan time, invalid returns
- calibration version, observation age, bias, covariance, and frame
- body mass/payload/center of mass, speed, reaction delay, deceleration, clearance
- command, application-control, Sport, sensor, and simulator timescales
- average/peak electrical power, stored energy, temperature and thermal time constants
- surface/contact assumptions, weather envelope, material loads and fastening
- simulator timestep/contact model and the parameter distribution used in evaluation

Every number needs SI units, source, uncertainty, operating condition, and status: measured, vendor-specified, estimated, or illustrative.

## Core equations

~~~text
acoustic propagation:   t_acoustic = distance / speed_of_sound
camera projection:      image_size_px approximately f_px size/distance
LiDAR range:            R = c Delta_t/2
frame transform:        p_base = R p_sensor + t
stopping lower model:   d = v t_r + v^2/(2 a_b)
energy:                 E = integral(P dt)
thermal first order:    C_th T_dot = P_loss - (T-T_ambient)/R_th
feedback error:         e = reference - measured_output
~~~

These models answer different questions. Do not collapse them into one opaque “confidence” or safety score.

## ASCII diagram

~~~text
 owner speech -> mic/AEC -> ASR -> semantic PlanIR -> task executive
      ^                                                |
      |                                                v
 spoken response <- TTS/render reference        camera semantics + LiDAR geometry
                                                       |
                                                       v
 world predicate <- estimation <- physical Go2 <- Sport <- ControlManager
                         ^         foot contact          ^
                         +------ measured feedback ------+

 veto stack: validation -> feasibility -> collision/reactive -> leases/E-stop
~~~

## Worked Parcel / Go2 example

Review the command: “Please get off the road and wait by that lamppost.” Suppose, only for illustration:

1. Audio arrives at 16 kHz in 20 ms frames, with the speaker driven through the microphone array's referenced DAC/amp path. One frame contains 320 samples; query-end and AEC state are timestamped.
2. Camera calibration has `f_x = 500 px`. A 0.30 m visual feature at 6.0 m projects to about `25 px`; semantics alone do not establish depth.
3. LiDAR supplies compatible range/clearance. A 1-degree extrinsic yaw error at 6 m would cause about `0.105 m` lateral error, so calibration uncertainty enters goal clearance.
4. The planner selects a sidewalk-supported stand-off region, not a point on the road. It prefers turning toward the path and smooth forward travel; bounded lateral motion remains available locally.
5. At `v = 0.50 m/s`, `t_r = 0.18 s`, and characterized illustrative `a_b = 1.0 m/s^2`, the ideal stopping model is `0.090 + 0.125 = 0.215 m`. Perception/body uncertainty and a tested buffer are added separately.
6. `ControlManager` leases the body command to Sport. Sport—not the LLM or Python navigation loop—balances the Go2. Completion requires fresh sidewalk membership, safe lamppost vicinity, and settled measured speed.
7. If an illustrative 10 s maneuver averages 180 W for the chosen system boundary, energy is `1800 J = 0.50 Wh`; that says nothing about peak current or temperature without their own evidence.

None of these values commission hardware. The design review replaces each with measured distributions and records which subsystem can veto or degrade gracefully when evidence expires.

## Software-engineering analogy

This is an architecture review, threat model, capacity plan, and distributed trace combined. Physical energy is the irreversible side effect; uncertainty is consistency debt; the authority graph is access control; stopping distance is a deadline budget. A green unit test at one layer cannot certify the transaction across all of them.

## Parcel / Go2 bridge

The review artifact should contain an authority diagram, assumption register, power/thermal budget, latency trace, calibration manifest, stopping envelope, simulator sensitivity report, and eval log with run IDs. Google Maps remains a placeholder external hint, not a current safety sensor. Compare the full systems classification in [Day 60: Final Architecture and Research Review](../robotics-60-days/day-60-final-architecture-research-review.md), plus [`docs/MOTION.md`](../../docs/MOTION.md) and [`docs/NAVIGATION_CITY.md`](../../docs/NAVIGATION_CITY.md).

## Failure and safety note

The most dangerous review outcome is an unqualified “looks good.” Open risks must have an owner, evidence plan, safe default, and promotion gate. Simulation, textbook equations, and vendor API success do not commission outdoor operation. Begin physical validation at low energy with local E-stop authority and stop on stale sensing, loss of route, collision uncertainty, tilt, thermal, power, or communications fault.

## Retrieval questions

1. Name the environmental sensors, motion writer, and fast balance owner in Parcel's intended stack.
2. What separate uncertainty/latency terms turn ideal braking distance into a stopping envelope?
3. Which artifacts would let another engineer reproduce and challenge the physical design review?

## Optional 10-minute exercise

Choose one command—sidewalk, lamppost, owner orbit, or follow-behind—and make a ten-row assumption register. For each row record value/unit, evidence source, uncertainty, falsifying measurement, owner, and fail-safe. Mark every illustrative value “not commissioned.”
