"""Commissioning: the measurement path for supervised hardware bring-up.

Card W0-B (`scrum/20260812/task_2/W0_PRODUCT_CARDS.md`), grounding the
`CommissioningRecordV1` contract in
`scrum/20260812/task_1/PRODUCTION_COMPANION_PLAN.md`.

This package is deliberately a leaf. It imports `parcel_robot.control` (for the
`ControlManager` it drives) and `parcel_robot.robot_profile` / `parcel_robot.
models` (for morphology and the velocity type) and **nothing else** — in
particular it never imports `parcel_robot.runtime`, and nothing in the
autonomous stack imports it. `control/factory.py` reaches it through one lazy
import inside one function, so a commissioning session can only be created by
someone who asked for one by name.

What it is for: measuring the four facts `control/factory.py` refuses to
proceed without — axis signs, the state velocity frame, the allowed mode set,
and a stop that is actually confirmed by feedback — under an explicitly armed,
one-axis, 0.02-0.05 m/s, short-duration, journalled, fenced-and-supervised
procedure, and writing them down as a record a second human must review before
those flags may be set.

What it is not for: moving a robot to get anything done. There is no path from
here into `RobotRuntime`, and `tests/test_w0b_commissioning.py` proves it.
"""
