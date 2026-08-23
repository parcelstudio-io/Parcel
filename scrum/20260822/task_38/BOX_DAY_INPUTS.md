# HW-6 — box-day inputs: how the three unmeasured terms get measured

Card `scrum/20260822/task_38`. Companion to `DESIGN.md` and to the record
files under `configs/envelope/`. Every row here fills exactly one term of
`configs/envelope/<hostname>.yaml`, and the `stopping-envelope` gate row stays
soft (`UNMEASURED — …`) until all five are filled. Nothing on this page has
been done: no robot hardware is on hand (only the reSpeaker XVF3800).

**Order.** These come AFTER design §7's B9 identity / B-fw firewall / S20
firmware / S19 Stage-0 rows and BEFORE HW-12's first armed step. B2 and Q-stop
are the same stand session; B1 needs HW-11's native gateway; B3 needs HW-10's
B17 recording. Until they are done the commissioned regime is `one_axis`
(`configs/envelope/*.yaml` `active_regime`), which is what the shipped records
declare.

---

## I1 / I2 — the two terms already measured, and why the Orin re-measures both

`configs/envelope/jaewoo-jang-parcel.yaml` carries `candidate_age_s` and
`ipc_delay_s` from the N24 fake-gateway path on the owner's desktop. **Neither
number survives the move to the dog**, and the Orin's record must carry its
own. They are rows, not footnotes, because a host that silently inherits
another host's latency is exactly the failure this card exists to prevent.

**I1 — `candidate_age_s` on the dog.** Age of the freshest robot state the
writer consults. On the desktop it measured 1.8 µs, which is an artefact of
the fake sport service refreshing its state on every command. On the Go2 the
producer is the 50 Hz `rt/sportmodestate` publisher, so the floor is one
publish period (~20 ms) and the number to record is the **p99 of
`GatewayStateV1.state_age_ms` observed by the command writer while the
perception daemon and the recorder are running** — the same three load
conditions as B1. Expect four orders of magnitude larger than the desktop's.

**I2 — `ipc_delay_s` on the dog.** Command submit → ack over the Orin's local
socket to the native gateway (HW-11), p99 over ≥ 2000 commands, worst of three
runs, under the same three load conditions. The desktop's 329 µs is a
different kernel on a different CPU with a Python gateway on the far end.

**Procedure for both.** The desktop's harness is
`tests/test_hw6_stopping_envelope.py:measure_n24_envelope_inputs`
(`PARCEL_HW6_SAMPLES=2000`); on the Orin it points at the native gateway's
socket instead of the fake one. Record p99 **and** max; if max > 3× p99, the
max is the number to use and the reason goes in the provenance.

---

## B1 — `gateway_period_s`: the watchdog wake period under load

**What it is.** The worst interval between two consecutive watchdog wakes of
the native sole-writer gateway (HW-11, N28/N43) — not the nominal 50 Hz.
A command that arrives just after a wake waits a whole period before the
gateway can act on it, so this term is the gateway's own contribution to the
delay chain.

**Rig.** Dog on the stand, sport mode OFF, gateway running on the Orin,
nothing else needed. Run it three ways and record the worst: (a) idle;
(b) with the perception daemon at its Q-ort power mode and the capture
recorder writing; (c) with (b) plus a `stress-ng --cpu 4` load, which is the
honest proxy for "the Orin is also thinking".

**Procedure.**
1. The gateway already stamps every wake in its bounded local audit ring
   (HLD §8.8 "bounded local audit ring and health output"); dump it after a
   10-minute run in each of the three conditions.
2. `gateway_period_s` = **p99 of the wake-to-wake interval in the worst of
   the three**, in seconds, to four significant figures.
3. Also record the maximum, separately, in the provenance string. If max is
   more than 3× p99, say so — it means a scheduling tail nobody has
   characterised, and the number to use is then the max.

**What would invalidate it.** A `SCHED_OTHER` gateway. If the process is not
running at a real-time priority the tail is a property of the desktop
scheduler, not the design, and the row must be re-measured after HW-11 sets
the priority.

---

## B2 — `stop_command_to_standstill_s`: stop command issued → standstill

**What it is.** The elapsed time from **the gateway ISSUING** `StopMove`/Damp
to the robot being stationary — the same instant the procedure below stamps as
`t_stop`, which is a conservative superset of "the vendor accepted it" (it
includes the vendor's own receipt path, and nothing between the two is
observable from outside the dog). **To stationary, not to "stop initiated"** — the
RC-4 table's E-stop row is explicitly "stop initiated, not motion-ended"
(`bridge/timing.py:PROPOSED_LATENCY_GATES_V1`, `docs/GATEWAY_TTL_LATENCY_
DERIVATION.md`), and this card's formula multiplies this term by the regime
speed, so an initiation-only number would understate the travel by the whole
braking phase.

**Rig (design §7, the Q-stop session).** Dog on the stand, sport mode ON, feet
clear of the ground, remote in hand, an operator on the L2+B key at all times,
the head board's NIC unplugged for the Q-stop half. Foot-force sensor
(`rt/lowstate` foot force, the same channel Stage 0 records) as the clock.

**Procedure.**
1. Command a one-axis step at 0.05 m/s (`commissioning/limits.py:78`) via
   `parcel-commission`, armed, 1 s duration.
2. At a random point inside the step, issue `StopMove` from the gateway and
   stamp `t_stop` on the gateway's monotonic clock.
3. `t_still` = the first sample where the commanded-axis body velocity from
   `rt/sportmodestate` stays under `commissioning/limits.py:SETTLED_LINEAR_MPS`
   (0.01 m/s) for `stop_settled_samples` (2, `configs/robot.yaml:122`)
   consecutive samples AND the foot-force trace shows the swing leg planted.
   Both, because either alone can be fooled — the state topic by a stale
   sample, the foot force by a stance phase that happens to look planted.
4. `stop_command_to_standstill_s` = **max of 20 repeats**, not p99: 20 samples cannot
   support a p99, and the sentence asks for the worst case.
5. Repeat at 0.15 m/s only after the row is green at 0.05 m/s.

**Q-stop (design §7, PO-1's decision cites it).** Same stand, head board /
dock NIC unplugged: does L2+B on the remote still damp the robot? Record
YES/NO and the observed damp time in `hw/Q_stop.txt`. **If NO**, the
independent stop is not the remote, `stop_command_to_standstill_s` is not the whole
story, and PO-1 decides what the independent stop is before any `--arm`
(design §5.5, §6; `docs/MOTION.md:441-442,491-492` — Parcel's software stops
are behavioural and are never a substitute).

**What would invalidate it.** Measuring with the feet on the ground (the
stand is the point), measuring at a battery state of charge outside 40-80 %,
or measuring on a surface other than the one the ODD declares. Record all
three in the provenance.

---

## B3 — `localization_jump_m`: the worst LIO `T_map_odom` jump

**What it is.** The largest single-update discontinuity of the MAP-frame
transform the LIO provider publishes — ISO/TS-15066's `Zr`, which
`authority.py:620` pins at 0.0 today because pose is sim truth. It enters the
formula as metres and is NOT multiplied by the speed: a loop-closure jump
displaces the world under the robot whether it is moving or not.

**Rig.** No stand needed. The B17 bake-off recording (design §7, HW-10): one
10-minute drive of the real venue with a loop closure in it, replayed offline
through both candidate providers (FAST-LIO2, Point-LIO).

**Procedure.**
1. Replay the recording; log `T_map_odom` at every publish.
2. For each consecutive pair, compute the planar translation delta.
3. `localization_jump_m` = **max delta of the provider that is actually
   configured**, in metres. Record both providers' numbers; the choice of
   provider is then visibly a safety choice, not only an accuracy one.
4. Record the 99th percentile beside it. If max/p99 > 10 the distribution is
   two populations (drift vs closure) and both belong in the provenance.

**What would invalidate it.** A recording with no loop closure in it (the
jump is the closure), or one taken in a venue geometrically unlike the ODD.

---

## Q-avoid — the one that is not a term, and is the reason the row exists

**Question (design §8 register, decider: this card's design).** Does the Go2's
own sport-mode obstacle avoidance intervene under `SportClient.Move`, and does
it fight Parcel's yield / doorway behaviour?

**Why it belongs here.** Every number above assumes ONE thing decides to
stop. If the vendor's avoidance also steers or brakes, the measured chain is
not the chain that acted, and a green `stopping-envelope` row would be
measuring the wrong system.

**Procedure (design §9 HW-12's first armed step, extended by one arm).**
1. Stand, sport mode on, a cardboard box at 1.5 m, one axis, 0.05 m/s.
2. **Arm A** — avoidance ON (factory default): command a step toward the box.
   Record whether the body deviates or slows before Parcel's own gate fires
   (`reactive_safety` stops at `obstacle_stop_m` 0.65 m base-center-to-surface,
   `configs/robot.yaml:313`), the distance at which it happens, and whether
   `rt/sportmodestate` shows a velocity Parcel never commanded.
3. **Arm B** — avoidance OFF, if the firmware exposes the toggle: same step,
   same box. If it cannot be turned off, record that: it is then a permanent
   second actor and the design owes it a paragraph.
4. **Verdict for this card.** If Arm A shows vendor intervention, the record's
   `stop_command_to_standstill_s` provenance must say which system stopped the dog, and
   HW-12 may not treat a green row as evidence about Parcel's chain.

**Result files** (design §7 shape): `hw/Q_stop.txt`, `hw/Q_avoid.txt`,
`hw/B17_lio.md`, `hw/gateway_period.txt` — and then one edit to
`configs/envelope/<orin-hostname>.yaml`, which is the only code change any of
this produces.
