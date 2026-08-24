"""Read-only multi-channel sensor capture: the channel matrix and the envelope.

Card PS-A of tranche PS-1 (``scrum/20260813/task_1/README.md``), serving one
sentence from ``PHYSICAL_SESSION_PLAN.md``: *when the dog powers down, we hold
a dataset that is still trustworthy six months from now.*

Two properties define this package, and both are pinned by
``tests/test_capture_envelope.py`` rather than asserted in prose:

**It is a stdlib leaf.** It imports the standard library and
:mod:`parcel_robot.evidence_origin`, and nothing else — not the runtime, not
navigation, not a vendor SDK. That is a deployment constraint, not tidiness:
this code runs on the Orin under JetPack 6.2.x (Python 3.10, Ubuntu 22.04)
while the dev venv is Python 3.14.4 on Ubuntu 26.04, and the two share no
third-party wheel. An AST import walk plus a subprocess ``sys.modules`` probe
measure it; the precedent is ``evidence_origin``'s own leaf pin.

**It cannot speak to the robot.** No symbol in this package names a publisher,
a control manager, a motion client, or a lease, and a test asserts that over
the package's own AST. Read-only by construction and by import graph, which is
where the property actually holds — not by a mode flag, which
``PHYSICAL_SESSION_PLAN.md`` rejects (a Python enum is weaker than an absent
SDK, and a health-join mode would have inherited finding F-1's surviving yaw).

:mod:`~parcel_robot.capture.channels` is the machine-readable transcription of
``CHANNEL_MATRIX.md``. :mod:`~parcel_robot.capture.envelope` carries each
message's provenance with a sequence counter that is **per channel**, which is
the defect ``bags/recorder.py`` has and this package does not.
"""
