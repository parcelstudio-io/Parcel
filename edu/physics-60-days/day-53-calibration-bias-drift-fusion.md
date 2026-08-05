# Day 53: Calibration, Bias, Drift, and Fusion

## Mental model

Calibration maps a sensor's output into physical units and frames. Bias is a persistent offset. Drift is calibration or estimated state changing over time. Fusion combines complementary evidence while preserving uncertainty. Fusion is not averaging everything: measurements must refer to compatible quantities, frames, and times, and shared errors must not be counted as independent evidence.

For Parcel, spatial calibration includes camera intrinsics and the rigid transforms among camera, LiDAR, and body. A perfect object detector with a wrong extrinsic transform produces precisely wrong goals.

## Quantities, units, and assumptions

- raw sensor value `z_raw`: device unit
- scale `s`: physical unit per device unit
- bias `b`: physical unit
- rigid transform `T_base_sensor`: rotation plus translation
- covariance `Sigma`: diagonal entries have squared component units; off-diagonal entries have products such as `m rad`
- time offset `Delta t`: second (`s`)
- drift rate: quantity per second or per degree Celsius

A fixed affine calibration assumes scale and bias do not depend on range, temperature, or time. A rigid extrinsic assumes the mount does not flex. Simple weighted fusion assumes unbiased, independent, approximately Gaussian errors.

## Core equations

~~~text
calibrated scalar: z = s z_raw + b
point transform: p_base = R_base_sensor p_sensor + t_base_sensor
first-order covariance propagation: Sigma_y approximately J Sigma_x J^T

two independent scalar estimates:
x_fused = (x_1/sigma_1^2 + x_2/sigma_2^2) /
          (1/sigma_1^2 + 1/sigma_2^2)
sigma_fused^2 = 1/(1/sigma_1^2 + 1/sigma_2^2)
~~~

If errors are correlated, the independent formula becomes overconfident. Time alignment must occur before geometric comparison.

Calibration uncertainty is part of the estimate, not metadata to discard after installation.

## ASCII diagram

~~~text
 camera detection ray ----\
                           > time/frame alignment -> fused belief + covariance
 LiDAR range/points -------/
       ^            ^
 intrinsics      T_base_lidar

 wrong calibration -> consistent residual direction -> biased goal
~~~

## Worked Parcel / Go2 example

Suppose the installed LiDAR yaw extrinsic is wrong by an illustrative 1 degree. At 10 m, the lateral error is approximately:

~~~text
error = R tan(1 degree) = (10 m)(0.01745) = 0.175 m
~~~

That is enough to move an obstacle boundary or lamppost approach point materially. Averaging more points does not remove it; their random scatter shrinks around the wrong direction. A calibration check should examine residuals across angle and range, and the runtime should version calibration with the hardware assembly.

In owner tracking, camera semantics and LiDAR geometry can complement each other. They must be associated at compatible timestamps and transformed into one frame. If both depend on the same stale body pose, that shared uncertainty cannot be counted twice as independent confidence. Values are illustrative, not installed-sensor tolerances.

## Software-engineering analogy

Calibration is schema plus migration metadata. Extrinsics are joins between coordinate-frame tables. A hard-coded transform after a mount change is like reading a database with an obsolete schema: every query succeeds and every answer is systematically wrong. Fusion is a replicated read only if correlated dependencies are modeled.

## Parcel / Go2 bridge

Camera proposes “owner,” “sidewalk,” or “lamppost”; LiDAR contributes range and clearance; body state supplies time-varying transforms. Store calibration identity in eval artifacts and reject observations with incompatible frame epochs. Read [Day 25: State Estimation and Sensor Fusion](../robotics-60-days/day-25-state-estimation-sensor-fusion.md) and [`docs/NAVIGATION_CITY.md`](../../docs/NAVIGATION_CITY.md).

## Failure and safety note

Do not calibrate a powered walking robot by placing a person in its path. Begin with static targets and unpowered or restrained geometry checks. Recalibrate after mount movement or impact. A fusion filter must increase uncertainty or reject data when timestamps, transforms, or residuals are inconsistent; it must not smooth away evidence of a broken mount.

## Retrieval questions

1. Why does averaging fail to remove a fixed extrinsic bias?
2. What compatibility conditions must hold before fusing a camera detection with LiDAR range?
3. Why does shared body-pose error make the independent-weighting formula overconfident?

## Optional 10-minute exercise

Compute lateral error at 2, 5, and 10 m for yaw errors of 0.5 and 2 degrees. Then design a static calibration scene that could expose yaw error without moving powered hardware.
