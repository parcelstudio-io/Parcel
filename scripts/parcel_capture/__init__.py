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
  installed into ``.parcel`` on 2026-08-22 for the desk-camera venue (it is
  declared by the ``camera-realsense`` extra, not by ``dev``, so a venv built
  from ``pip install .[dev]`` still has no such wheel). Either way this tree is
  expected to run there, refuse, and say why.
* **The wheel census, measured rather than remembered** (card TRUTH-1,
  2026-08-22). ``pip index versions pyrealsense2`` reports **2.58.3.10794** as
  both INSTALLED and LATEST here, and PyPI serves that release as 13 files:
  ``manylinux1_x86_64`` for cp310-cp314, ``manylinux2014_aarch64`` for
  cp39/cp310/cp312 **only**, ``win_amd64`` for cp310-cp314. This paragraph used
  to claim that aarch64 had no build at all. That was never measured and it is
  false — the sentence is not reproduced here, because the way a stale claim is
  kept dead is a grep for it, and a retraction that quotes the claim verbatim
  defeats its own guard. The true statement is narrower, and is why the extra is
  still optional: **aarch64 wheels are published for cp39/cp310/cp312 ONLY**, so
  an aarch64 host on 3.8, 3.11, 3.13 or 3.14 needs a source build. Which of those
  the Go2 EDU+ dock is, is UNCONFIRMED: reseller and NVIDIA-forum reports have
  Go2 EDU docks shipping **JetPack 5.1.1** (Ubuntu 20.04, CPython 3.8 — no wheel)
  and being flashed to **6.2.1** (Ubuntu 22.04, CPython 3.10 — wheel).
  Re-measure before quoting this; it is dated for that reason.
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
