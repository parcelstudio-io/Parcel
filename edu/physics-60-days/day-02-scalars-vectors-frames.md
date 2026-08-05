# Day 02: Scalars, Vectors, and Frames

## Mental model

A scalar has magnitude. A vector has magnitude and direction. Temperature, elapsed time, mass, and speed are scalars. Position, velocity, acceleration, and force are vectors. Saying “the dog moves at 0.4 m/s” gives speed; saying “0.4 m/s forward in the body frame” gives velocity.

A vector is incomplete without a reference frame. The same physical motion has different numeric components when expressed relative to the dog, the map, or a moving owner. Frame errors are especially treacherous because the values remain plausible.

Choose axes explicitly. A common planar robotics convention is body x forward, body y left, and positive yaw counterclockwise, but every interface must declare its own convention.

## Quantities, units, and assumptions

For a planar vector:

~~~text
v = (v_x, v_y)          components in m/s
|v| = speed             magnitude in m/s
~~~

Components depend on the frame; magnitude does not under a pure rotation. Position needs an origin as well as axis directions. A camera pixel frame, LiDAR frame, base_link body frame, odom frame, and map frame are distinct even when all have x and y fields.

Assume frames are right-handed unless an interface says otherwise. Record the transform timestamp: a body-to-map rotation from half a second ago may be wrong while the dog is turning.

## Core equations

Vector magnitude and addition:

~~~text
|v| = √(v_x² + v_y²)
r = a + b = (a_x + b_x, a_y + b_y)
~~~

A two-dimensional rotation by yaw angle θ is:

~~~text
[v_map_x]   [ cosθ  -sinθ ] [v_body_x]
[v_map_y] = [ sinθ   cosθ ] [v_body_y]
~~~

Check dimensions: sine and cosine are dimensionless, so the output remains m/s.

## ASCII diagram

~~~text
 map y (north)
      ^
      |       body x (forward)
      |      /
      |   dog ----> v_body
      |    /
      +--------------------> map x (east)

 same arrow, different numeric components
~~~

## Worked Parcel / Go2 example

Assume the body axes are x forward and y left. Parcel requests an illustrative body velocity:

~~~text
v_body = (0.40, 0.10) m/s
~~~

Its speed is:

~~~text
|v| = √(0.40² + 0.10²) ≈ 0.412 m/s
~~~

If the dog’s yaw is +90 degrees, or π/2 rad, relative to the map:

~~~text
v_map_x = 0(0.40) - 1(0.10) = -0.10 m/s
v_map_y = 1(0.40) + 0(0.10) =  0.40 m/s
~~~

The lateral component is allowed, but a goal-directed companion should normally turn toward a distant target and prefer forward travel rather than slide sideways for the whole route. These values and conventions are illustrative, not commissioned hardware limits.

## Software-engineering analogy

A vector without a frame is like a database row without a tenant ID: structurally valid and semantically unsafe. A transform is a versioned conversion function. Applying an old transform resembles joining against a stale snapshot.

Treat frame names as types. Converting body velocity to map velocity should happen through a reviewed transform provider, not by copying component arithmetic into every planner.

## Parcel / Go2 bridge

Parcel’s locomotion boundary uses body-frame velocity commands, while semantic goals and maps may live in odom or map frames. Owner-relative behavior introduces another moving frame. Typed goals need frame, timestamp, confidence, and validity duration so the arbiter can reject stale or incompatible proposals.

Companion reading: [Robotics Day 13 — Coordinate Frames and Planar Transforms](../robotics-60-days/day-13-coordinate-frames-planar.md).

## Failure and safety note

Never validate a frame conversion by sending a full-speed command. Inspect transforms, replay logs, visualize axes, and commission at very low energy with clear space and an E-stop operator. A sign error can turn “away from obstacle” into “toward obstacle.”

## Retrieval questions

1. What information distinguishes velocity from speed?
2. Why can a frame bug pass range checks while still directing unsafe motion?
3. If a vector is only rotated, what changes and what stays constant?

## Optional 10-minute exercise

On paper, rotate body vector (0.30, 0.00) m/s into the map frame for yaw angles 0, π/2, π, and -π/2. Draw each answer before calculating it, then check the magnitude.
