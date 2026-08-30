# SOS-1 current-source maintenance verdict

**Narrow source/fake-gateway decision: PASS. Physical motion decision: NO-GO.**

Adopt the handler-before-connect/READY repair and the bounded lifecycle oracle.
The separately credentialed software principal has no positive motion API,
dominates the fake gateway with a latched exact-zero STOP, stays alive after
SIGUSR1 with fresh watchdog evidence, and exits cleanly only after STOP on
SIGINT/SIGTERM in two concurrent and two sequential current-source runs.

This closes one software startup race and restores credible current-source
evidence. It does not make the STOP path independent of the Orin, gateway,
Python runtime, shared power, or Unitree transport, and it does not authorize
energizing the robot.

Before tethered powered motion, wire and fault-inject the real stop-only
inputs, commission the distinct target UIDs and unit files, retain a physically
independent E-stop/Unitree remote, and measure worst-case STOP latency and
distance under target load, terrain, payload, battery, and communication
faults. Until those gates pass, use this service only in motors-disabled HIL or
closely controlled tethered commissioning.
