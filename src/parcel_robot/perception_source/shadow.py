"""Shadow mode — the migration instrument, with a taxonomy instead of a feeling.

Card C-3, REVISION §3. Under ``semantic_source: shadow`` the oracle drives the
robot and C-2's learned map answers the same question beside it. Every
disagreement is classified, counted against a stated denominator, and logged
with the frames that produced it.

**Why a bare agreement rate is not a result.** The adversarial review (F4)
names four ways a single number lies:

* *coverage bias* — the oracle drives, so the learned map is never scored in
  the states its own behaviour would create. Shadow agreement structurally
  cannot see them; that is why the card demands ≥3 closed-loop missions driven
  by the learned map alone, and why nothing in this module claims to replace
  them.
* *structural mismatch inflation* — the oracle sees 12 m through walls with a
  closed 9-class label set; the map sees a ~6 m depth band with open labels and
  facade-derived positions. Most raw disagreements are frustum, range or
  convention mismatches. Counting those as divergence drowns the real signal,
  so this module reports **two denominators**: every comparison, and the
  *comparable* subset where the oracle's answer was inside the map's sensing
  envelope.
* *no severity taxonomy* — "the robot walked to the wrong navigable place" and
  "a distant thing was not in the map yet" are not the same event. They are
  :data:`ADMISSION_FLIP` and :data:`BENIGN_MISS` here, and only one of them is
  a gate.
* *no pre-registered bar* — fixed in
  ``scrum/20260821/task_13/evidence/C3_PREREGISTRATION.md`` §2C, before any run.

**The denominator is not optional.** :class:`AgreementRow` cannot be built
without both counts and :meth:`AgreementRow.as_dict` always emits them. A
reporting path that drops them does not compile into a row; there is a seeded
defect for exactly that.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

#: The learned map produced nothing where the oracle did, and the oracle's
#: answer was OUTSIDE the map's sensing envelope — too far, out of frustum, or
#: occluded. Not a disagreement about the world; a disagreement about what was
#: visible. Excluded from the comparable denominator, never from the total.
BENIGN_MISS = "benign_miss"

#: Both arms named the same place class and admitted it; the centroids differ.
#: Reported as a distribution against the PG-2 surface tolerance, not as a
#: pass/fail per row — a 4 cm delta and a 4 m delta are the same class and very
#: different facts.
LOCALIZATION_DELTA = "localization_delta"

#: The learned map admitted where the oracle refused, or admitted a DIFFERENT
#: place than the oracle admitted. This is the class that walks the robot
#: somewhere wrong. **HARD gate.**
ADMISSION_FLIP = "admission_flip"

#: The learned map refused where the oracle admitted, on a query the oracle
#: could see AND the map's envelope covered. A refusal outside the envelope is
#: :data:`BENIGN_MISS`, not this. **HARD gate** in the direction that matters:
#: a query that must refuse must refuse under both arms.
REFUSAL_FLIP = "refusal_flip"

#: Exactly the four classes. A fifth would be a design change, not a label, and
#: a classifier that returns something outside this set is a bug the ledger
#: refuses rather than records.
DIVERGENCE_CLASSES: tuple[str, ...] = (
    BENIGN_MISS,
    LOCALIZATION_DELTA,
    ADMISSION_FLIP,
    REFUSAL_FLIP,
)

#: The two classes the pre-registration gates on.
HARD_GATE_CLASSES: tuple[str, ...] = (ADMISSION_FLIP, REFUSAL_FLIP)

#: Agreement (same admission decision, same place) needs no class at all.
AGREED = "agreed"


class ShadowRefused(ValueError):
    """A shadow record that cannot be trusted. Never silently dropped."""


@dataclass(frozen=True)
class SensingEnvelope:
    """What the learned map could possibly have seen.

    This is the separator F4(b) asks for. Without it, "the map does not contain
    the building 30 m away" counts as a divergence and the whole table is noise.

    ``max_range_m`` is the depth band the detections were localized in;
    ``half_fov_rad`` is the camera's horizontal half-angle. Both are properties
    of the sensor, supplied by the caller that owns it — this module does not
    invent them, because an envelope guessed here would silently decide which
    divergences count.
    """

    max_range_m: float
    half_fov_rad: float

    def __post_init__(self) -> None:
        for name in ("max_range_m", "half_fov_rad"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ShadowRefused(f"SensingEnvelope.{name} must be a number")
            if not math.isfinite(float(value)) or float(value) <= 0.0:
                raise ShadowRefused(f"SensingEnvelope.{name} must be finite and positive")

    def covers(
        self,
        *,
        target_x: float,
        target_y: float,
        robot_x: float,
        robot_y: float,
        robot_yaw_rad: float,
    ) -> bool:
        """Whether a world point was inside the envelope at this pose."""

        dx = float(target_x) - float(robot_x)
        dy = float(target_y) - float(robot_y)
        distance = math.hypot(dx, dy)
        if distance > float(self.max_range_m):
            return False
        bearing = math.atan2(dy, dx) - float(robot_yaw_rad)
        bearing = (bearing + math.pi) % (2.0 * math.pi) - math.pi
        return abs(bearing) <= float(self.half_fov_rad)


@dataclass(frozen=True)
class ArmVerdict:
    """One arm's answer to one query.

    ``place_id`` / ``x`` / ``y`` are meaningful only when ``admitted``. A
    refusal carries its ``reason`` so a flip can be attributed rather than
    guessed at.
    """

    admitted: bool
    place_id: str | None = None
    label: str | None = None
    x: float | None = None
    y: float | None = None
    reason: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.admitted, bool):
            raise ShadowRefused("ArmVerdict.admitted must be a boolean")
        if self.admitted and self.place_id is None:
            raise ShadowRefused("an admitted ArmVerdict must name a place_id")
        for name in ("x", "y"):
            value = getattr(self, name)
            if value is None:
                continue
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ShadowRefused(f"ArmVerdict.{name} must be a number")
            if not math.isfinite(float(value)):
                raise ShadowRefused(f"ArmVerdict.{name} must be finite")

    def as_dict(self) -> dict[str, Any]:
        return {
            "admitted": self.admitted,
            "place_id": self.place_id,
            "label": self.label,
            "x": self.x,
            "y": self.y,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class Divergence:
    """One classified disagreement, WITH the frames that produced it.

    ``frames`` is required and must be non-empty for any class other than a
    pure refusal-on-both, because REVISION §3's "logged to the evidence stream
    with the frames that produced it" is the difference between a divergence
    report and a divergence anecdote.
    """

    query: str
    query_class: str
    divergence_class: str
    oracle: ArmVerdict
    learned: ArmVerdict
    comparable: bool
    frames: tuple[str, ...]
    frame_times_ns: tuple[int, ...] = ()
    delta_m: float | None = None
    note: str = ""

    def __post_init__(self) -> None:
        if self.divergence_class not in DIVERGENCE_CLASSES:
            raise ShadowRefused(
                f"unknown divergence class {self.divergence_class!r}; the taxonomy is "
                f"exactly {list(DIVERGENCE_CLASSES)}"
            )
        if not isinstance(self.comparable, bool):
            raise ShadowRefused("Divergence.comparable must be a boolean")
        if not self.frames:
            raise ShadowRefused(
                "a Divergence must carry the frames that produced it: a divergence "
                "without its frames cannot be re-examined and is not evidence"
            )
        if self.frame_times_ns and len(self.frame_times_ns) != len(self.frames):
            raise ShadowRefused("frame_times_ns, when given, must align with frames")

    @property
    def is_hard_gate(self) -> bool:
        return self.divergence_class in HARD_GATE_CLASSES

    def as_dict(self) -> dict[str, Any]:
        return {
            "query": self.query,
            "query_class": self.query_class,
            "divergence_class": self.divergence_class,
            "comparable": self.comparable,
            "hard_gate": self.is_hard_gate,
            "oracle": self.oracle.as_dict(),
            "learned": self.learned.as_dict(),
            "frames": list(self.frames),
            "frame_times_ns": list(self.frame_times_ns),
            "delta_m": self.delta_m,
            "note": self.note,
        }


def classify(
    *,
    query: str,
    query_class: str,
    oracle: ArmVerdict,
    learned: ArmVerdict,
    comparable: bool,
    frames: Sequence[str],
    frame_times_ns: Sequence[int] = (),
    localization_tolerance_m: float = 1.0,
) -> Divergence | None:
    """Classify one paired answer. ``None`` means the arms agreed.

    The order of the tests is the severity order, and it is deliberate:

    1. **Admission flip first.** Any admission the oracle did not make is the
       most expensive event in the taxonomy, including "admitted a different
       place" — a robot sent confidently to the wrong navigable target is
       exactly the failure shadow mode exists to catch before it drives.
    2. **Refusal flip**, but only where the map could have seen the answer.
       Outside the envelope a refusal is honest, and calling it a flip would
       make the envelope irrelevant.
    3. **Benign miss** — refused, outside the envelope.
    4. **Localization delta** — both admitted the same place; only the metres
       differ.
    """

    oracle_place = (oracle.place_id or "").strip()
    learned_place = (learned.place_id or "").strip()

    if learned.admitted and not oracle.admitted:
        return Divergence(
            query=query,
            query_class=query_class,
            divergence_class=ADMISSION_FLIP,
            oracle=oracle,
            learned=learned,
            comparable=comparable,
            frames=tuple(frames),
            frame_times_ns=tuple(frame_times_ns),
            note="learned map admitted a place the oracle refused",
        )
    if learned.admitted and oracle.admitted and learned_place != oracle_place:
        return Divergence(
            query=query,
            query_class=query_class,
            divergence_class=ADMISSION_FLIP,
            oracle=oracle,
            learned=learned,
            comparable=comparable,
            frames=tuple(frames),
            frame_times_ns=tuple(frame_times_ns),
            delta_m=_delta(oracle, learned),
            note="both admitted, different places",
        )
    if oracle.admitted and not learned.admitted:
        if comparable:
            return Divergence(
                query=query,
                query_class=query_class,
                divergence_class=REFUSAL_FLIP,
                oracle=oracle,
                learned=learned,
                comparable=True,
                frames=tuple(frames),
                frame_times_ns=tuple(frame_times_ns),
                note=f"learned map refused inside its own envelope: {learned.reason}",
            )
        return Divergence(
            query=query,
            query_class=query_class,
            divergence_class=BENIGN_MISS,
            oracle=oracle,
            learned=learned,
            comparable=False,
            frames=tuple(frames),
            frame_times_ns=tuple(frame_times_ns),
            note="oracle answer lay outside the learned map's sensing envelope",
        )
    if oracle.admitted and learned.admitted:
        delta = _delta(oracle, learned)
        if delta is None or delta <= float(localization_tolerance_m):
            return None
        return Divergence(
            query=query,
            query_class=query_class,
            divergence_class=LOCALIZATION_DELTA,
            oracle=oracle,
            learned=learned,
            comparable=comparable,
            frames=tuple(frames),
            frame_times_ns=tuple(frame_times_ns),
            delta_m=delta,
            note="same place, different metres",
        )
    # Both refused. That is agreement, and for the Narnia family it is the
    # whole point of the card.
    return None


def _delta(oracle: ArmVerdict, learned: ArmVerdict) -> float | None:
    values = (oracle.x, oracle.y, learned.x, learned.y)
    if any(value is None for value in values):
        return None
    return math.hypot(float(learned.x) - float(oracle.x), float(learned.y) - float(oracle.y))  # type: ignore[arg-type]


@dataclass(frozen=True)
class AgreementRow:
    """One query class's agreement, with BOTH denominators. Always both.

    There is no constructor path that yields a rate without the counts it came
    from, and :meth:`as_dict` emits every field. This is the structural answer
    to "the cutover metric is the shadow agreement rate, reported per query
    class with denominators — not a feeling".
    """

    query_class: str
    total_comparisons: int
    comparable_comparisons: int
    agreements_total: int
    agreements_comparable: int
    counts: Mapping[str, int]

    def __post_init__(self) -> None:
        for name in (
            "total_comparisons",
            "comparable_comparisons",
            "agreements_total",
            "agreements_comparable",
        ):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ShadowRefused(f"AgreementRow.{name} must be a non-negative int")
        if self.comparable_comparisons > self.total_comparisons:
            raise ShadowRefused("comparable comparisons cannot exceed total comparisons")
        if self.agreements_total > self.total_comparisons:
            raise ShadowRefused("agreements cannot exceed comparisons")
        if self.agreements_comparable > self.comparable_comparisons:
            raise ShadowRefused("comparable agreements cannot exceed comparable comparisons")
        unknown = sorted(set(self.counts) - set(DIVERGENCE_CLASSES))
        if unknown:
            raise ShadowRefused(f"unknown divergence class(es) in counts: {unknown}")

    @property
    def rate_total(self) -> float | None:
        """Agreement over EVERY comparison. ``None`` at n=0 — never 0.0 or 1.0.

        A rate with no observations behind it is not a small rate, it is an
        absent one, and returning a float there is how an empty run reports a
        perfect score.
        """

        if self.total_comparisons == 0:
            return None
        return self.agreements_total / self.total_comparisons

    @property
    def rate_comparable(self) -> float | None:
        if self.comparable_comparisons == 0:
            return None
        return self.agreements_comparable / self.comparable_comparisons

    def as_dict(self) -> dict[str, Any]:
        return {
            "query_class": self.query_class,
            "agreement_total": self.rate_total,
            "n_total": self.total_comparisons,
            "agreement_comparable": self.rate_comparable,
            "n_comparable": self.comparable_comparisons,
            "counts": {name: int(self.counts.get(name, 0)) for name in DIVERGENCE_CLASSES},
        }


@dataclass
class ShadowLedger:
    """Accumulates paired answers and produces the table.

    The ledger owns the counting so that no harness has to, which is what makes
    "reported with denominators" a property of the code rather than a habit of
    whoever wrote the report.
    """

    localization_tolerance_m: float = 1.0
    divergences: list[Divergence] = field(default_factory=list)
    _totals: dict[str, int] = field(default_factory=dict, repr=False)
    _comparables: dict[str, int] = field(default_factory=dict, repr=False)
    _agreed_total: dict[str, int] = field(default_factory=dict, repr=False)
    _agreed_comparable: dict[str, int] = field(default_factory=dict, repr=False)
    _counts: dict[str, dict[str, int]] = field(default_factory=dict, repr=False)

    def record(
        self,
        *,
        query: str,
        query_class: str,
        oracle: ArmVerdict,
        learned: ArmVerdict,
        comparable: bool,
        frames: Sequence[str],
        frame_times_ns: Sequence[int] = (),
    ) -> Divergence | None:
        """Compare one query under both arms and file the result."""

        if not frames:
            raise ShadowRefused(
                "a shadow comparison must name the frames it was taken from"
            )
        self._totals[query_class] = self._totals.get(query_class, 0) + 1
        if comparable:
            self._comparables[query_class] = self._comparables.get(query_class, 0) + 1
        divergence = classify(
            query=query,
            query_class=query_class,
            oracle=oracle,
            learned=learned,
            comparable=comparable,
            frames=frames,
            frame_times_ns=frame_times_ns,
            localization_tolerance_m=self.localization_tolerance_m,
        )
        if divergence is None:
            self._agreed_total[query_class] = self._agreed_total.get(query_class, 0) + 1
            if comparable:
                self._agreed_comparable[query_class] = (
                    self._agreed_comparable.get(query_class, 0) + 1
                )
            return None
        self.divergences.append(divergence)
        row = self._counts.setdefault(query_class, {})
        row[divergence.divergence_class] = row.get(divergence.divergence_class, 0) + 1
        return divergence

    def agreement_table(self) -> list[AgreementRow]:
        """Per-class rows, sorted, each carrying both denominators."""

        return [
            AgreementRow(
                query_class=name,
                total_comparisons=self._totals.get(name, 0),
                comparable_comparisons=self._comparables.get(name, 0),
                agreements_total=self._agreed_total.get(name, 0),
                agreements_comparable=self._agreed_comparable.get(name, 0),
                counts=dict(self._counts.get(name, {})),
            )
            for name in sorted(self._totals)
        ]

    def hard_gate_divergences(self) -> list[Divergence]:
        """Every admission or refusal flip. The pre-registered bar is zero."""

        return [item for item in self.divergences if item.is_hard_gate]

    def summary(self) -> dict[str, Any]:
        """The whole result, denominators included, ready for the record."""

        table = self.agreement_table()
        totals = sum(row.total_comparisons for row in table)
        comparables = sum(row.comparable_comparisons for row in table)
        agreed_total = sum(row.agreements_total for row in table)
        agreed_comparable = sum(row.agreements_comparable for row in table)
        return {
            "rows": [row.as_dict() for row in table],
            "overall": {
                "agreement_total": (agreed_total / totals) if totals else None,
                "n_total": totals,
                "agreement_comparable": (
                    (agreed_comparable / comparables) if comparables else None
                ),
                "n_comparable": comparables,
            },
            "counts": {
                name: sum(row.counts.get(name, 0) for row in table)
                for name in DIVERGENCE_CLASSES
            },
            "hard_gate_divergences": [d.as_dict() for d in self.hard_gate_divergences()],
            "divergences": [d.as_dict() for d in self.divergences],
        }


def envelope_comparability(
    envelope: SensingEnvelope | None,
    *,
    oracle: ArmVerdict,
    robot_x: float,
    robot_y: float,
    robot_yaw_rad: float,
) -> bool:
    """Was the oracle's answer inside the learned map's envelope at this pose?

    ``None`` envelope means "not established", and the honest answer there is
    **False** — an unestablished envelope must shrink the comparable
    denominator, never inflate it. Defaulting the other way would let a harness
    that forgot to supply an envelope report every divergence as comparable.
    """

    if envelope is None or not oracle.admitted:
        return False
    if oracle.x is None or oracle.y is None:
        return False
    return envelope.covers(
        target_x=oracle.x,
        target_y=oracle.y,
        robot_x=robot_x,
        robot_y=robot_y,
        robot_yaw_rad=robot_yaw_rad,
    )


def divergence_events(divergences: Iterable[Divergence]) -> list[dict[str, Any]]:
    """Evidence-stream rows for a batch of divergences."""

    return [
        {"kind": "shadow_divergence", **divergence.as_dict()} for divergence in divergences
    ]
