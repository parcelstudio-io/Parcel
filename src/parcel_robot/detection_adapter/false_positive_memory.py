"""Mission-scoped NEGATIVE evidence with TTL/decay (card VS-2).

Why this module exists
----------------------
V-B was measured as a *view-consistent phantom that never fails M-of-N*
(``scrum/20260811/task_1/FOLLOWUP_DESIGNS.md`` §2.1(3)):
:class:`~parcel_robot.detection_adapter.multi_view_confirm.MultiViewConfirm`
consults its rejected memory on every update, but entries arise ONLY from
in-window M-of-N failure — flicker. A phantom that is *consistently* visible
never flickers (the measured commit landed on view 2), and once a lock-on
session commits it returns ``None`` forever, so nothing ever re-verified it
and no negative evidence was ever written. The system could be tricked by the
same place in the same mission without limit.

Two memories, deliberately distinct
-----------------------------------
* ``MultiViewConfirm``'s memory answers **"did this hypothesis flicker inside
  its confirmation window?"** — a within-window, hypothesis-id-keyed fact. It
  is untouched by this card.
* This memory answers **"was a claim about this CLASS at this PLACE refuted
  after the fact?"** — refuted by verify-on-approach (card VS-1's refinement
  gate, covariance-shrink or persistence checkpoint failure), which is
  knowledge that only exists after the confirmation window has closed.

Keying is by ``(class, world-cell)``, never by candidate id, because an id is
exactly what a detector does not reliably provide — a rejection has to survive
the same phantom being re-detected under a fresh id. The cell grid and the
label normalisation are not restated here: they are taken from
:class:`~parcel_robot.instructnav.scoring.FalsePositiveMemory`, the in-tree
authority for "the same place", so the two memories cannot disagree about what
a place is.

Clock, TTL and decay
--------------------
The clock is a VIEW COUNTER — the same unit
``MultiViewConfig.rejected_memory_views`` already expresses its horizon in,
and the only clock a pure module can be handed without inventing one. The
default TTL is that field, consumed by reference.

Decay is linear in age and REINFORCED by repetition: an entry refuted ``k``
times survives ``k · ttl_views`` views, and its strength falls from 1 to 0
across that horizon. A place that lies once is forgiven quickly; a place that
lies repeatedly is remembered for proportionally longer. Suppression holds
while strength is positive, so "suppressed within the TTL, released after the
decay" is one statement, not two mechanisms.

This module decides nothing. It records refutations and answers questions
about them; the caller (card VS-4) chooses what to do with a suppression.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from parcel_robot.detection_adapter.multi_view_confirm import MultiViewConfig
from parcel_robot.instructnav.scoring import FALSE_POSITIVE_CELL_M, FalsePositiveMemory

__all__ = [
    "DEFAULT_TTL_VIEWS",
    "DOES_NOT_PROVE",
    "FalsePositiveEntry",
    "FalsePositiveMemoryConfig",
    "NegativeEvidenceMemory",
    "Suppression",
]

#: TTL horizon of a single refutation, in views — the confirmer's own
#: rejected-memory horizon, consumed by reference (never restated).
DEFAULT_TTL_VIEWS: int = MultiViewConfig().rejected_memory_views

DOES_NOT_PROVE = (
    (
        "These cells prove bookkeeping: a refutation suppresses re-acceptance at "
        "the same class/place until it decays. They do not prove that a real "
        "camera would produce the refutation in the first place — in the T0 eval "
        "arms the oracle frustum never hallucinates (record §2.4)."
    ),
    (
        "The clock is a caller-advanced view counter, not wall time. Nothing here "
        "claims a seconds-valued TTL, and nothing here expires on its own."
    ),
    (
        "This memory PROPOSES suppression. It never vetoes a safety decision and "
        "is not consulted by any gate; MultiViewConfirm's window-failure memory "
        "is a separate mechanism and is untouched."
    ),
)


@dataclass(frozen=True, slots=True)
class FalsePositiveMemoryConfig:
    """Frozen policy. Every default is an in-tree authority."""

    cell_m: float = FALSE_POSITIVE_CELL_M
    ttl_views: int = DEFAULT_TTL_VIEWS
    max_entries: int = MultiViewConfig().max_hypotheses

    def __post_init__(self) -> None:
        cell = float(self.cell_m)
        if not math.isfinite(cell) or cell <= 0.0:
            raise ValueError("cell_m must be finite and positive")
        if int(self.ttl_views) < 1:
            raise ValueError("ttl_views must be >= 1")
        if int(self.max_entries) < 1:
            raise ValueError("max_entries must be >= 1")


@dataclass(frozen=True, slots=True)
class FalsePositiveEntry:
    """One remembered refutation, keyed by ``(cell_x, cell_y, normalised label)``."""

    key: tuple[int, int, str]
    label: str
    world_xy: tuple[float, float]
    reason: str
    refutations: int
    first_view: int
    last_view: int


@dataclass(frozen=True, slots=True)
class Suppression:
    """Answer to "may I accept this hypothesis here?"."""

    suppressed: bool
    strength: float
    refutations: int
    reason: str
    entry: FalsePositiveEntry | None = None


class NegativeEvidenceMemory:
    """Mission-scoped refutation memory with a reinforced linear decay."""

    def __init__(self, config: FalsePositiveMemoryConfig | None = None) -> None:
        self.config = config if config is not None else FalsePositiveMemoryConfig()
        # Composition, not duplication: the cell grid and label normalisation
        # come from the scorer's own false-positive memory.
        self._keys = FalsePositiveMemory(cell_m=self.config.cell_m)
        self._entries: dict[tuple[int, int, str], FalsePositiveEntry] = {}

    def __len__(self) -> int:
        return len(self._entries)

    def reset(self) -> None:
        """Mission scope: a new mission starts with no refutations."""

        self._entries.clear()

    def key(self, label: str, world_xy: tuple[float, float]) -> tuple[int, int, str]:
        """``(cell_x, cell_y, normalised_label)`` — the scorer's own keying."""

        return self._keys.key(float(world_xy[0]), float(world_xy[1]), str(label))

    def record_refutation(
        self,
        label: str,
        world_xy: tuple[float, float],
        *,
        view_index: int,
        reason: str = "",
    ) -> FalsePositiveEntry:
        """Write negative evidence for ``(class, world-cell)``.

        A repeat refutation at the same key REINFORCES the entry: the count
        rises and the horizon extends with it, rather than merely restarting a
        fixed TTL.
        """

        now = _view_index(view_index)
        key = self.key(label, world_xy)
        point = (float(world_xy[0]), float(world_xy[1]))
        previous = self._entries.get(key)
        if previous is None:
            self._evict_if_full(now)
            entry = FalsePositiveEntry(
                key=key,
                label=str(label),
                world_xy=point,
                reason=str(reason),
                refutations=1,
                first_view=now,
                last_view=now,
            )
        else:
            entry = FalsePositiveEntry(
                key=key,
                label=previous.label,
                world_xy=point,
                reason=str(reason) or previous.reason,
                refutations=previous.refutations + 1,
                first_view=previous.first_view,
                last_view=now,
            )
        self._entries[key] = entry
        return entry

    def horizon_views(self, entry: FalsePositiveEntry) -> int:
        """How long this entry is remembered: ``refutations · ttl_views``."""

        return int(entry.refutations) * int(self.config.ttl_views)

    def strength(self, label: str, world_xy: tuple[float, float], *, view_index: int) -> float:
        """Remaining negative-evidence weight in ``[0, 1]`` (0 == forgotten)."""

        return self.consult(label, world_xy, view_index=view_index).strength

    def suppressed(self, label: str, world_xy: tuple[float, float], *, view_index: int) -> bool:
        """Has this class at this place already been refuted, and not yet decayed?"""

        return self.consult(label, world_xy, view_index=view_index).suppressed

    def consult(
        self, label: str, world_xy: tuple[float, float], *, view_index: int
    ) -> Suppression:
        """Full answer: strength, refutation count, and the entry that fired.

        The containing cell AND its eight neighbours are checked, matching the
        scorer's own rule — a phantom re-detected 20 cm across a cell boundary
        is the same refuted place. The strongest neighbour decides.
        """

        now = _view_index(view_index)
        cell_x, cell_y, normalised = self.key(label, world_xy)
        best: tuple[float, FalsePositiveEntry] | None = None
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                entry = self._entries.get((cell_x + dx, cell_y + dy, normalised))
                if entry is None:
                    continue
                value = self._strength(entry, now)
                if value <= 0.0:
                    continue
                if best is None or value > best[0]:
                    best = (value, entry)
        if best is None:
            return Suppression(
                suppressed=False, strength=0.0, refutations=0, reason="no_negative_evidence"
            )
        value, entry = best
        return Suppression(
            suppressed=True,
            strength=value,
            refutations=entry.refutations,
            reason=entry.reason or "refuted_here",
            entry=entry,
        )

    def entries(self, *, view_index: int | None = None) -> tuple[FalsePositiveEntry, ...]:
        """Stored entries; with ``view_index`` only those still active."""

        if view_index is None:
            return tuple(self._entries.values())
        now = _view_index(view_index)
        return tuple(e for e in self._entries.values() if self._strength(e, now) > 0.0)

    def prune(self, *, view_index: int) -> int:
        """Drop fully decayed entries; returns how many were dropped."""

        now = _view_index(view_index)
        stale = [key for key, entry in self._entries.items() if self._strength(entry, now) <= 0.0]
        for key in stale:
            del self._entries[key]
        return len(stale)

    def _strength(self, entry: FalsePositiveEntry, now: int) -> float:
        age = now - entry.last_view
        if age < 0:
            # A query from before the refutation was written: not yet knowledge.
            return 0.0
        horizon = self.horizon_views(entry)
        if age >= horizon:
            return 0.0
        return 1.0 - float(age) / float(horizon)

    def _evict_if_full(self, now: int) -> None:
        if len(self._entries) < int(self.config.max_entries):
            return
        self.prune(view_index=now)
        if len(self._entries) < int(self.config.max_entries):
            return
        # Bounded memory: the weakest (oldest, least reinforced) entry goes.
        weakest = min(self._entries.values(), key=lambda e: (self._strength(e, now), e.last_view))
        del self._entries[weakest.key]


def _view_index(value: int) -> int:
    index = int(value)
    if index < 0:
        raise ValueError("view_index must be >= 0")
    return index
