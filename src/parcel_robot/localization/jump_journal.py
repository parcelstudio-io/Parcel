"""``localization_jump_m``, journalled — the term no host record has measured.

``bridge/timing.py`` has carried this term since HW-6 with the provenance "no
host has measured it": it is the one DISTANCE term in the stopping envelope
(ISO/TS-15066 ``Zr``), it is not multiplied by the regime speed, and a
loop-closure or relocalization jump displaces the world whether the body is
moving or not.  ``LocalizationUpdate.jump_m`` has published the per-update
value since H7 and nothing has ever written it down.

This module is the writer.  It watches updates, keeps the samples, and emits
the exactly-shaped ``measurements`` entry ``load_stopping_envelope_record``
demands — ``{"value": <float>, "provenance": <str>}`` — so an envelope record
can consume a measured value instead of the sentinel.

**Deliberately not importing ``bridge/timing.py``.**  The term name is one
string and the entry is one mapping; importing the envelope module to learn
them would drag ``yaml``, ``socket`` and the whole HW-6 record surface into the
localization package for no benefit, and would put a leaf under a module whose
regions belong to two closed cards.  The bond is proved by a test that feeds
this writer's output through the REAL ``load_stopping_envelope_record``, which
is a stronger check than a shared constant would be.

**What the numbers look like, so a wrong one is obvious.**  NAV-CORE measured
the largest single-update MAP discontinuity over 120 room-scale episodes at
**0.029 m** (median 0.009 m); the H7 delegation bench measured **7.15 m** on a
kidnap and **10.47 m** on the relocalization that followed it.  A record that
says 0.2 m is a record whose provenance needs reading.
"""

from __future__ import annotations

import math
import statistics
from collections import deque
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

__all__ = [
    "ENVELOPE_JUMP_TERM",
    "JumpSample",
    "LocalizationJumpJournal",
]

#: The term's name in ``bridge/timing.py``'s ``ENVELOPE_DISTANCE_TERMS_V1`` and
#: in every ``configs/envelope/*.yaml`` record.  Restated, not imported — see
#: the module docstring.
ENVELOPE_JUMP_TERM = "localization_jump_m"

#: How many samples the journal keeps for the distribution rows.  The count and
#: the maximum are exact regardless; only the median and the retained rows are
#: windowed, because a soak run must not grow a list without bound.
DEFAULT_WINDOW = 4096


@dataclass(frozen=True)
class JumpSample:
    """One update's jump, with enough context to attribute it."""

    t_s: float
    jump_m: float
    health: str
    source: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "t_s": float(self.t_s),
            "jump_m": float(self.jump_m),
            "health": str(self.health),
            "source": str(self.source),
        }


class LocalizationJumpJournal:
    """Every published jump, the maximum, and the envelope entry it becomes."""

    def __init__(self, *, window: int = DEFAULT_WINDOW, host: str = "") -> None:
        if int(window) < 1:
            raise ValueError("window must keep at least one sample")
        self._window: deque[JumpSample] = deque(maxlen=int(window))
        self._count = 0
        self._max = 0.0
        self._max_sample: JumpSample | None = None
        self._host = str(host)

    # -- ingestion ---------------------------------------------------------

    def observe(self, update: Any, *, t_s: float) -> JumpSample:
        """Record one :class:`~parcel_robot.localization.contract.LocalizationUpdate`."""

        jump = float(getattr(update, "jump_m", 0.0) or 0.0)
        if not math.isfinite(jump) or jump < 0.0:
            raise ValueError("jump_m must be a finite non-negative magnitude")
        health = getattr(getattr(update, "health", None), "value", "unknown")
        sample = JumpSample(
            t_s=float(t_s),
            jump_m=jump,
            health=str(health),
            source=str(getattr(update, "source", "") or "unknown"),
        )
        self._window.append(sample)
        self._count += 1
        if jump > self._max:
            self._max = jump
            self._max_sample = sample
        return sample

    def extend(self, updates: Iterable[Any], *, t0_s: float = 0.0, dt_s: float = 0.1) -> None:
        """Convenience for replaying a recorded run at a fixed cadence."""

        for index, update in enumerate(updates):
            self.observe(update, t_s=t0_s + index * float(dt_s))

    # -- evidence ----------------------------------------------------------

    @property
    def count(self) -> int:
        return self._count

    @property
    def max_m(self) -> float:
        """Largest single-update jump seen — exact over every sample."""

        return self._max

    @property
    def max_sample(self) -> JumpSample | None:
        return self._max_sample

    @property
    def median_m(self) -> float:
        """Median over the RETAINED window (see :data:`DEFAULT_WINDOW`)."""

        if not self._window:
            return 0.0
        return float(statistics.median(sample.jump_m for sample in self._window))

    def samples(self) -> tuple[JumpSample, ...]:
        return tuple(self._window)

    def rows(self) -> tuple[dict[str, Any], ...]:
        return tuple(sample.as_dict() for sample in self._window)

    def over(self, bound_m: float) -> tuple[JumpSample, ...]:
        """Every retained sample above a bound — the latch's own trigger rows."""

        return tuple(sample for sample in self._window if sample.jump_m > float(bound_m))

    # -- publication -------------------------------------------------------

    def envelope_measurement(self, *, provenance: str = "") -> dict[str, Any]:
        """The ``measurements`` entry for ``localization_jump_m``.

        The shape is fixed by ``bridge/timing.load_stopping_envelope_record``:
        a mapping with EXACTLY ``value`` and ``provenance``, and an unmeasured
        term has to say what will measure it.  A journal that saw no updates
        therefore publishes the sentinel rather than a confident 0.0 — zero
        jumps observed is not the same claim as "the jump is zero".
        """

        if self._count == 0:
            return {
                "value": "UNMEASURED",
                "provenance": provenance
                or "no localization update observed on this host yet",
            }
        return {
            "value": self._max,
            "provenance": provenance or self._default_provenance(),
        }

    def _default_provenance(self) -> str:
        sample = self._max_sample
        where = "" if sample is None else f" ({sample.source}, health {sample.health})"
        host = f" on {self._host}" if self._host else ""
        return (
            f"largest single-update T_map_odom body displacement over "
            f"{self._count} updates{where}{host}"
        )

    def merge_into_envelope_record(
        self,
        document: Mapping[str, Any],
        *,
        provenance: str = "",
    ) -> dict[str, Any]:
        """A copy of an envelope record with this term's entry replaced.

        Pure: the input mapping is never mutated, and every other term keeps
        the value and provenance the record already carried, so a writer cannot
        quietly re-measure four terms while publishing one.
        """

        out = dict(document)
        measurements = dict(out.get("measurements") or {})
        measurements[ENVELOPE_JUMP_TERM] = self.envelope_measurement(
            provenance=provenance
        )
        out["measurements"] = measurements
        return out

    def write_envelope_record(
        self,
        path: Any,
        document: Mapping[str, Any],
        *,
        provenance: str = "",
    ) -> dict[str, Any]:
        """Merge and write one YAML record; returns the document written.

        ``yaml`` is imported here rather than at module scope for the same
        reason ``bridge/timing.py`` does it: this package must stay importable
        by a consumer that has no YAML dependency and only wants the numbers.
        """

        import yaml

        merged = self.merge_into_envelope_record(document, provenance=provenance)
        Path(path).write_text(
            yaml.safe_dump(merged, sort_keys=True), encoding="utf-8"
        )
        return merged
