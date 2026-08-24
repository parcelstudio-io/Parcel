"""The observation spine: adapters, the snapshot assembler and the carrier view.

HLD ``research/20260824/PORTABLE_LIVING_DOG_HLD.md`` §2 names two replaceable
body boundaries.  This package is the second one: device, localization and
perception adapters converge here and publish exactly one immutable
``NavigationSnapshotV2`` per tick.  Nothing in this package imports a backend,
a vendor SDK, the runtime or the UI — that is the property that makes the
boundary replaceable, and ``tests/test_a4_spine.py`` asserts it.

This ``__init__`` deliberately re-exports nothing (DEC-IG-2): import the leaf.
"""
