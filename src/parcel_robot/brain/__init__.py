"""Typed, deterministic contracts between Parcel's language and control planes.

The package deliberately contains no simulator, controller, or model I/O.  A
language model may propose a :class:`PlanIR`, but only the validator and task
executive can admit it for later dispatch through runtime-owned adapters.
"""
