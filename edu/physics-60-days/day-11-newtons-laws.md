# Day 11: Newton’s Laws

## Mental model

Newton’s laws connect motion to force. They explain why a velocity request cannot move a robot by itself: feet must push on the ground, the ground must push back, and the resulting external force must accelerate the body.

The three laws are:

1. A body keeps constant velocity unless a net external force changes it.
2. Net external force equals the rate of change of momentum; at constant mass this becomes ΣF = ma.
3. Forces arise in interaction pairs: if the foot pushes backward on the ground, the ground pushes forward on the foot with equal magnitude and opposite direction.

The two forces in the third law act on different bodies, so they do not cancel on one free-body diagram.

## Quantities, units, and assumptions

Force is a vector measured in newtons:

~~~text
1 N = 1 kg·m/s²
~~~

Mass in kg measures inertia: resistance to acceleration. Acceleration is in m/s². Net force is the vector sum of external forces on the chosen system.

Choosing the system matters. For the whole dog, joint and motor forces are mostly internal; gravity and ground contact are external. For one lower leg, joint torque and contact are both external interactions across that smaller boundary.

The simple ΣF = ma form assumes constant total mass and an inertial reference frame. For the whole articulated robot it is exact when `a` is the acceleration of the whole-system center of mass. The common approximation is using body-frame, IMU, or odometry acceleration as if it were that center-of-mass acceleration; moving limbs and estimation error can make those quantities differ.

## Core equations

~~~text
ΣF = ma
a = ΣF/m
momentum p = mv
general second law: ΣF = dp/dt
~~~

In components:

~~~text
ΣF_x = ma_x
ΣF_y = ma_y
ΣF_z = ma_z
~~~

Dimensional check:

~~~text
[kg][m/s²] = [N]
~~~

Zero net force means zero acceleration, not necessarily zero velocity.

## ASCII diagram

~~~text
 travel direction →

 ground ◄──────── foot     foot pushes ground backward
 ground ────────► foot     ground pushes foot forward

 external forward force → body acceleration
~~~

## Worked Parcel / Go2 example

Assume an illustrative dog-plus-payload mass of 16 kg and measured forward acceleration of 0.40 m/s². The whole-body horizontal net force estimate is:

~~~text
F_net = ma = (16 kg)(0.40 m/s²) = 6.4 N
~~~

This is net force, not the force from one foot and not a motor torque. Individual feet can exert larger forces in different directions that partly cancel. During gait, only stance feet transmit significant ground reaction, and load distribution changes rapidly.

If Parcel asks for forward velocity but measured acceleration remains near zero, possibilities include insufficient traction, a controller clamp, a mode error, an obstacle stop, or biased estimation. Increasing the request is not a diagnosis. The values are illustrative, not commissioned Go2 mass, force, or acceleration limits.

## Software-engineering analogy

Net force resembles the sum of concurrent writes to a state variable. Large opposing operations can produce a small net change. Observing near-zero acceleration does not imply no component is working hard.

Inertia resembles retained state: input must persist over time to change it. Newton’s third-law pair resembles a protocol interaction between two services; logging only one side hides the exchange.

## Parcel / Go2 bridge

Parcel sets bounded body-motion intentions. Unitree Sport selects gait, foot placement, and actuator behavior needed to create contact forces. Parcel supervises measured velocity, attitude, progress, and faults; it does not infer applied forces merely from a successful Move request.

Companion reading: [Robotics Day 03 — Linear Mechanics](../robotics-60-days/day-03-linear-mechanics.md).

## Failure and safety note

Do not estimate safe force by having a powered robot push a person, scale, wall, or hand. Vendor motor and contact limits, controlled test fixtures, qualified supervision, and force-rated instrumentation are required for force commissioning. A whole-body estimate cannot be used as a per-joint limit.

## Retrieval questions

1. What does zero net force imply about velocity?
2. Why do a foot’s action and reaction forces not cancel on the dog’s free-body diagram?
3. Why is ma for the whole dog not equal to the force produced by each stance foot?

## Optional 10-minute exercise

On paper, compute the net force needed to accelerate illustrative masses of 10 kg and 20 kg at 0.3 m/s². Then list three external forces and three internal forces for a whole-robot system boundary.
