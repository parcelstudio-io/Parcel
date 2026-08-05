# Physics Course References

The daily lessons are self-contained. These sources are for a second explanation, derivations, or deeper practice. Prefer the free texts and official documentation before short-form summaries.

## General physics and mechanics

- [OpenStax University Physics, Volume 1](https://openstax.org/details/books/university-physics-volume-1): units, vectors, kinematics, forces, energy, rotation, statics, fluids, oscillations, waves, and sound.
- [MIT OpenCourseWare 8.01SC: Classical Mechanics](https://ocw.mit.edu/courses/8-01sc-classical-mechanics-fall-2016/): lectures and problems for mechanics.
- [BIPM SI Brochure](https://www.bipm.org/en/publications/si-brochure): authoritative SI units and definitions.

## Electricity, magnetism, optics, and thermodynamics

- [OpenStax University Physics, Volume 2](https://openstax.org/details/books/university-physics-volume-2): thermodynamics, electric charge, circuits, magnetism, and electromagnetic induction.
- [OpenStax University Physics, Volume 3](https://openstax.org/details/books/university-physics-volume-3): electromagnetic waves, optics, and modern-physics context.
- [MIT OpenCourseWare 8.02: Electricity and Magnetism](https://ocw.mit.edu/courses/8-02-physics-ii-electricity-and-magnetism-spring-2019/): field and circuit intuition with worked problems.

## Robotics bridge

- Kevin Lynch and Frank Park, [Modern Robotics](https://modernrobotics.northwestern.edu/): free text and videos connecting rigid-body physics, kinematics, dynamics, and control.
- Russ Tedrake, [Underactuated Robotics](https://underactuated.csail.mit.edu/): dynamics, locomotion, planning, and control. Read after Days 20–30; it is intentionally more advanced.
- Steve Brunton, [Control Bootcamp](https://www.youtube.com/playlist?list=PLMrJAkhIeNNSVjnsviglFoY2nXildDCcv): linear systems and feedback intuition for engineers.

## Audio, sensing, and simulation

- Julius O. Smith III, [Physical Audio Signal Processing](https://ccrma.stanford.edu/~jos/pasp/): free reference for waves, resonators, microphones, speakers, and acoustic systems.
- [MuJoCo computation documentation](https://mujoco.readthedocs.io/en/stable/computation/): primary documentation for the equations, contacts, constraints, and numerical integration used by Parcel's main simulator.
- [ROS 2 coordinate-frame conventions](https://www.ros.org/reps/rep-0103.html): SI units and axis conventions used at software interfaces.

## Parcel-specific companion reading

- [Robotics course](../robotics-60-days/README.md)
- [Parcel introduction](../INTRO.md)
- [Official Unitree SDK2 Python Go2 Sport example](https://github.com/unitreerobotics/unitree_sdk2_python/blob/master/example/go2/high_level/go2_sport_client.py): primary example for the high-level body-motion API used at Parcel's current hardware boundary.
- [`docs/MOTION.md`](../../docs/MOTION.md): the actual nested control and motion-authority design.
- [`docs/NAVIGATION_CITY.md`](../../docs/NAVIGATION_CITY.md): how geometry, perception, and planning meet in city navigation.
- [`docs/AUDIO_LATENCY_AND_SPATIAL_INTELLIGENCE.md`](../../docs/AUDIO_LATENCY_AND_SPATIAL_INTELLIGENCE.md): audio and interaction timing in the product stack.

## Reading rule

Sources can teach a model; they cannot commission your robot. When a textbook uses a rigid body, point contact, constant friction coefficient, ideal voltage source, or noiseless sensor, write that assumption in your notebook and identify the Parcel measurement or simulator sweep that would test it.
