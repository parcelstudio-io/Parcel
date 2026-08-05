# Day 39: Stress, Strain, Stiffness, and Fatigue

## Mental model

External loads travel through a structure along **load paths**. Inside a material, force distributed over area creates **stress**; the resulting relative deformation is **strain**. In an initial elastic region, removing the load approximately restores the shape. Beyond that region, a part may yield, crack, buckle, or break.

Robot structures rarely fail only from one static load. Walking adds repeated cycles, vibration, impact, fastener preload, and stress concentration around holes and corners. **Fatigue** can grow damage under loads below a one-time failure value. Stiffness and strength are different: a strong part can flex too much for camera calibration, and a stiff brittle part can fail under impact.

## Quantities, units, and assumptions

- Force `F`: newtons (`N`).
- Cross-sectional area `A`: square metres (`m²`).
- Normal stress `sigma`: pascals (`Pa = N/m²`).
- Normal strain `epsilon`: dimensionless.
- Young’s modulus `E`: pascals (`Pa`).
- Load cycles `N_cycles`: count.

We use uniform axial stress and linear elasticity. Brackets usually see bending, shear, torsion, fastener contact, anisotropic printing, and stress concentrations, so this is only a first check.

## Core equations

```text
average axial stress:       sigma = F/A
normal strain:              epsilon = Delta L/L
linear elastic relation:    sigma = E epsilon
simple safety factor:       n = reference strength / working stress
bending-moment magnitude:   M = F d_perpendicular
```

A safety factor is not a substitute for choosing the correct failure mode, material data, environment, and load spectrum.

## ASCII diagram

```text
payload force F
      v
    [box]---- d ----| bracket root / fasteners
                    |
                 high bending moment M = F d_perpendicular
                 stress concentrates at holes/corners

shorter lever + wider load path -> usually lower stress/deflection
```

## Worked Parcel / Go2 example

**These are illustrative values, not a bracket design or Go2 shock specification.** Suppose a `1.0 kg` payload has an equivalent vertical load factor of `3 g`, meaning this teaching load is defined as three times its weight:

```text
F = m a = 1.0 kg * (3 * 9.81 m/s²) = 29.4 N
```

If an imagined member carries this as uniform axial load over `20 mm² = 20e-6 m²`:

```text
sigma = 29.4 / (20e-6) = 1.47e6 Pa = 1.47 MPa
```

But if the force's line of action has a perpendicular moment arm of `0.08 m` from the bracket root, it also creates illustrative bending moment:

```text
M = 29.4 N * 0.08 m = 2.35 N m
```

The axial result alone therefore misses the likely dominant load. Material orientation, fasteners, vibration, notches, enclosure openings, and fatigue still require proper mechanical design and test.

## Software-engineering analogy

Average stress is like average traffic; stress concentration is a hot shard. Total capacity can look adequate while one corner fails. Fatigue resembles cumulative write wear: individually valid operations consume finite lifetime through repetition.

## Parcel / Go2 bridge

Camera, LiDAR, compute, and audio mounts must preserve calibration while surviving gait vibration and handling. Mechanical changes belong in a versioned payload definition with mass, CoM, inertia, fasteners, material/process, expected load cases, inspection plan, and test evidence. The simulator can vary payload mass but cannot certify printed-layer adhesion or screw retention.

Companion reading: [The physical chain](../robotics-60-days/day-10-synthesis-physical-chain.md), [Reality gap](../robotics-60-days/day-37-reality-gap.md), and [Testing and evaluation](../robotics-60-days/day-38-testing-evaluation.md).

## Failure and safety note

A 3D-printed microphone bracket survives a bench pull but cracks after thousands of gait cycles at a sharp screw hole. Static strength was not fatigue life, and print direction made the material anisotropic. Use qualified mechanical review, secondary retention where appropriate, inspection intervals, and approved vibration and environmental testing. Do not mount an unreviewed payload on a moving robot.

## Retrieval questions

1. How do stress and strain differ?
2. Why can an apparently low average stress hide failure near a hole?
3. Why does a one-time static load test not establish robot-service life?

## Optional 10-minute exercise

Repeat the axial teaching calculation for areas `10`, `20`, and `40 mm²` and equivalent load factors of `1 g`, `3 g`, and `5 g`. Then sketch two bracket shapes and mark likely load paths and stress concentrations. Keep the Go2 unpowered and unchanged.
