"""The deployable motion seam: bounded vendor I/O, the production client, the CLI.

Card ``DEPLOYABLE-MOTION-SEAM`` (``scrum/20260824/task_3/ROBOT_READY_PLAN.md``
§4).  Three things live here and nothing else:

* :mod:`gateway.seam.vendor_io` — the bounded call lane that makes a vendor
  ``state()`` / ``stop_move()`` that **never returns** a contained fault
  instead of a wedged process.  ``gateway/core.py`` reaches the vendor's
  synchronous surface only through it; ``gateway/writer.py`` already owned
  ``Move``.
* :mod:`gateway.seam.client` — ``MotionGatewayClientV1``, the *production*
  Unix client.  It owns no vendor object, opens exactly one
  ``AF_UNIX``/``SOCK_SEQPACKET`` connection, and has no raw-packet or
  malformed-message escape hatch (that stays ``gateway/bench_client.py``'s
  job, and that module is bench-only).
* :mod:`gateway.seam.notify` and :mod:`gateway.seam.cli` — the ``sd_notify``
  client and the ``parcel-gateway`` console entry point named by
  ``deploy/orin/services/parcel-gateway.service``.

**Why a subpackage and not four more top-level modules.**
``tests/test_m1_0_gateway.py::test_the_gateway_tree_holds_the_expected_modules``
pins ``gateway/*.py`` — the *top level* — to exactly the twelve modules card A1
delivered, and that suite is required to stay byte-unchanged and green.  A new
top-level module would re-pin an accepted A1 invariant.  The pin's intent is
not evaded: ``tests/test_motion_seam.py`` re-applies every one of its rules
**recursively** over ``gateway/**/*.py`` (expected module set, no vendor SDK,
the deployable surface reaches exactly ``parcel_robot.bridge.protocol``, no
product runtime/control/backends, CPython 3.10 clean), so this subpackage is
held to a stricter version of the same contract rather than a weaker one.

**What is deployable here.** ``vendor_io``, ``client``, ``notify`` and ``cli``
all ship in the vendor venv.  ``cli`` is the one module in this subpackage that
may name the bench vendor, and it does so exactly the way ``gateway/process.py``
does: by refusing to start at all unless a sport backend was named, and by
importing ``parcel_robot.bridge.fake_sport`` lazily and only for ``fake``.
"""
