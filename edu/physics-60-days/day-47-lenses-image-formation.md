# Day 47: Lenses and Image Formation

## Mental model

A camera compresses rays from a three-dimensional scene onto a two-dimensional sensor. An ideal pinhole maps direction to pixel location. A real lens gathers more light than a pinhole and focuses rays, but introduces distortion, finite depth of field, flare, and focus limits. A pixel is therefore evidence about a ray through space, not a ready-made 3D point.

Object size in an image depends on physical size, distance, focal length, and orientation. That projective ambiguity is fundamental: a small nearby object can occupy the same pixels as a large distant one. Parcel needs calibration and another source of geometry—such as LiDAR, motion, known scale, or a ground-plane assumption—to turn a semantic camera detection into a safe metric goal.

## Quantities, units, and assumptions

- focal length `f`: metre (`m`) on the sensor, or pixels after calibration
- object distance `d_o` and image distance `d_i`: metre (`m`)
- world coordinates `(X,Y,Z)`: metre (`m`) in a camera frame
- image coordinates `(u,v)`: pixel
- sensor width `w_s`: metre (`m`)
- horizontal field of view: radian or degree

The pinhole equations assume a calibrated ideal camera and positive depth. Real systems require principal point, unequal pixel scales, lens-distortion coefficients, and a timestamped transform from camera to robot body.

## Core equations

Thin lens and ideal projection:

~~~text
1/f = 1/d_o + 1/d_i
u - c_x = f_x X/Z
v - c_y = f_y Y/Z
horizontal FOV = 2 atan(sensor_width / (2 f))
projected size in pixels approximately f_pixels × object_size / distance
~~~

The projection loses absolute scale: multiplying `X`, `Y`, and `Z` by the same factor leaves `X/Z` and `Y/Z` unchanged.

## ASCII diagram

~~~text
 world point P       lens/pinhole       sensor
       * ------------------O-------------| pixel
        \                 /              |
         \ field of view /               |

 one pixel -> one ray O-----> scene
 not one metric 3D point until another constraint is added
~~~

## Worked Parcel / Go2 example

Assume an illustrative calibrated focal length `f_x = 600 pixels`. A lamppost segment 0.50 m wide, facing the camera at 5.0 m, has approximate projected width:

~~~text
width_px = (600 px)(0.50 m)/(5.0 m) = 60 px
~~~

At 10 m it would be about 30 pixels, all else equal. A detector's lower confidence at range can be a physics consequence, not merely a model defect. Yet 60 pixels alone cannot prove 5 m distance unless the physical width and pose are known. Parcel should bind the camera's “lamppost” semantics to LiDAR geometry or another calibrated depth estimate, then compute a collision-cleared stand-off pose.

These values are illustrative; camera intrinsics, resolution, distortion, and the object geometry must be measured for the installed Go2 payload.

## Software-engineering analogy

Projection is a lossy serialization. Many 3D states hash to the same 2D record, so inversion without extra information is underdetermined. Camera calibration is the schema and codec version. Mixing pixels from one calibration with intrinsics from another is decoding bytes under the wrong protocol.

## Parcel / Go2 bridge

Parcel's camera should propose classes, tracks, masks, and rays; calibrated geometry should turn those proposals into candidate goals. LiDAR provides obstacle and range evidence, while navigation verifies support and clearance. Read [Day 22: Camera Fundamentals](../robotics-60-days/day-22-camera-fundamentals.md) and the semantic-goal pipeline in [`docs/NAVIGATION_CITY.md`](../../docs/NAVIGATION_CITY.md).

## Failure and safety note

A high-confidence bounding box is not a safe waypoint. Using its bottom-center pixel as ground contact can fail on occlusion, hills, reflections, or a detector box that includes background. Calibration changes when a mount bends or the camera is replaced. Verify extrinsics after impacts, reject impossible depth, and preserve a collision gate independent of semantic vision.

## Retrieval questions

1. Why does one image pixel define a ray rather than a unique 3D point?
2. How does projected object size change when distance doubles under the pinhole model?
3. What additional evidence can Parcel use to ground a camera semantic detection metrically?

## Optional 10-minute exercise

Using `f_x = 600 px`, calculate the projected width of a 0.4 m object at 2, 5, and 10 m. Then list two assumptions that make the estimate wrong. This is a desk exercise; do not treat the result as a detector range requirement.
