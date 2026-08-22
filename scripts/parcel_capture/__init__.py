"""``parcel-capture`` deploy artifact: the Orin-side capture tools.

Package skeleton created by card PS-A so PS-B/C/D/E can add modules without
racing on the directory. **PS-A owns this file and nothing else in here.**

Scope rules for everything added beside this file
-------------------------------------------------
* This tree may assume Python 3.10 + ROS 2 Humble, because it runs on the Orin
  (JetPack 6.2.x). It must NOT be imported by anything under ``src/``.
* It must **degrade to a clear, actionable refusal — never a traceback** — when
  a dependency is missing, and the refusal must name **which of two facts** is
  missing (cards ENV-1/ENV-1b): the *module* is not on the import path, or the
  *device* is not attached to this host. They take different remedies —
  ``pip install`` versus a cable — and an operator handed the wrong one loses a
  session morning. Presence is answered with :func:`importlib.util.find_spec`
  for the module and a ``/dev`` glob census for the device; neither imports a
  vendor SDK. The dev box this tree is written on has **no device of any kind
  attached**, and it may or may not carry a camera SDK: ``pyrealsense2`` was
  installed into ``.parcel`` on 2026-08-22 for the desk-camera venue, while a
  venv built from ``pip install .[dev]`` has no such wheel (there is no aarch64
  build, so the ``dev`` extra must not declare it or the Orin install breaks).
  Either way this tree is expected to run there, refuse, and say why.
* Nothing here arms anything: no publisher, no control manager, no lease, no
  motion client, and no **motion** SDK installed into ``.parcel/``. The absence
  of ``unitree_sdk2py`` from that venv is the strongest motion guarantee the
  project currently has (``PHYSICAL_SESSION_PLAN.md``); preserve it. The split
  is by what a module can DO: a camera SDK reads pixels and is allowed in; the
  SDKs that can command or decode the dog are not.

The importable, dependency-free half of the stack lives in
:mod:`parcel_robot.capture` — the channel matrix and ``CaptureEnvelope`` — and
is stdlib-only on both Python 3.10 and 3.14 precisely so this tree can rely on
it without a wheel.

This file is deliberately empty of code.
"""
