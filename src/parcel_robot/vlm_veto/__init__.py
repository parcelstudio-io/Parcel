"""The VLM veto seat — Qwen3-VL-2B as PG-3's subtractive signal (card P1-D).

Two modules and one rule:

* :mod:`~parcel_robot.vlm_veto.verifier` — the seat itself. Answers *is the main
  object in this crop a ``<noun>``* and *what is the main object called*.
* :mod:`~parcel_robot.vlm_veto.runner` — where it is allowed to run: never on
  the 10 Hz loop, always under the contention guard.

**Importing this package imports no tensor library.** ``torch`` and
``transformers`` are pulled in by :meth:`~verifier.Qwen3VLVerifier.load` and
nowhere else, so a shipping install without the perception extra loses the veto
and gains nothing worse than a robot that asks more often.
"""
