"""``parcel-capture`` deploy artifact: the Orin-side capture tools.

Package skeleton created by card PS-A so PS-B/C/D/E can add modules without
racing on the directory. **PS-A owns this file and nothing else in here.**

Scope rules for everything added beside this file
-------------------------------------------------
* This tree may assume Python 3.10 + ROS 2 Humble, because it runs on the Orin
  (JetPack 6.2.x). It must NOT be imported by anything under ``src/``.
* It must **degrade to a clear, actionable refusal — never a traceback** — when
  a dependency is missing. It is developed on a box that has none of ``rclpy``,
  ``cyclonedds``, ``unitree_sdk2py``, ``pyrealsense2``, ``cv2``, ``mcap`` or
  ``zstandard``, and it is expected to run there, refuse, and say why.
* Nothing here arms anything: no publisher, no control manager, no lease, no
  motion client, and no vendor SDK installed into ``.parcel/``. The absence of
  ``unitree_sdk2py`` from that venv is the strongest motion guarantee the
  project currently has (``PHYSICAL_SESSION_PLAN.md``); preserve it.

The importable, dependency-free half of the stack lives in
:mod:`parcel_robot.capture` — the channel matrix and ``CaptureEnvelope`` — and
is stdlib-only on both Python 3.10 and 3.14 precisely so this tree can rely on
it without a wheel.

This file is deliberately empty of code.
"""
