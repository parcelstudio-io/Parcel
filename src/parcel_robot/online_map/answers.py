"""Turning what the map remembers into a sentence the dog may say.

WORLD-1 (``scrum/20260823/TRANCHE2_MIND_DESIGN_FABLE.md``), built here as
research H5's answer path.

THE ONE RULE
------------
**Never a present-tense presence claim.** ``OnlineSemanticMap`` records that a
bench was seen at a place at a time; it does not and cannot know that the bench
is there now. "There's a bench four metres to your left" is a claim about the
present made from evidence about the past, and the moment the bench is moved the
robot is confidently wrong about the room it is standing in. Every sentence this
module produces is past tense with its provenance attached — *"I last saw a
bench about 4 m to my left, a couple of minutes ago"* — so the listener can tell
how much to trust it without being told.

Two consequences that look like details and are not:

* **The label leads; a proposed name follows.** ``label`` is what the detector
  fired on and is the evidence; the k=3 admissible names are what a VLM
  proposed, and a VLM name is revisable. "a bench — the one I've been calling
  the reading corner" keeps both, in the order of their evidence. A sentence
  that led with the name would be asserting the robot's own guess as the thing
  it saw.
* **A refusal is an answer.** When the map has nothing for a query the sentence
  says so plainly and, when the gate supplied them, offers what the robot *does*
  know. Silence and a hedge ("I'm not sure...") are the two ways this goes
  wrong; both read as evasion, and neither tells the owner the map is empty.

PURITY
------
No clock, no store, no I/O, no model, and no import of the map itself: the
caller passes ``now_wall_s`` and assembles :class:`PlaceSighting` rows from
whatever it queried. That is what makes this module testable with three
literals and reusable by the broker tool, the whisperer and a harness alike.
Types from the map are imported under ``TYPE_CHECKING`` only, so the annotations
read honestly without dragging the detector stack into a renderer.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover - annotations only; no runtime import
    from .online_map import MapCandidate

#: Bearing bands, in radians from straight ahead, and what the dog calls them.
#: Coarse on purpose: a robot that says "27 degrees to port" is reporting a
#: number nobody can act on, and the map's own position error is larger than the
#: difference between "left" and "ahead and slightly left".
_BEARING_BANDS: tuple[tuple[float, str], ...] = (
    (math.pi / 8, "straight ahead"),
    (3 * math.pi / 8, "ahead and to my {side}"),
    (5 * math.pi / 8, "to my {side}"),
    (7 * math.pi / 8, "behind me and to my {side}"),
)
_BEHIND = "behind me"

#: Age bands for the provenance phrase. The boundaries are the ones a listener
#: hears as different: seconds ago, minutes ago, this session, another day.
_AGE_BANDS: tuple[tuple[float, str], ...] = (
    (20.0, "just now"),
    (120.0, "a moment ago"),
    (900.0, "a few minutes ago"),
    (3600.0, "about an hour ago"),
    (21600.0, "earlier today"),
)
_OLDER = "a while back"


@dataclass(frozen=True, slots=True)
class PlaceSighting:
    """One remembered place, as much as a sentence needs to know about it.

    Assembled by the caller from a :class:`~.online_map.MapCandidate` plus the
    entry's ``last_seen_wall_s`` — the one field the candidate does not carry
    and the whole reason these answers can be honest about age.
    """

    entry_id: str
    label: str
    distance_m: float
    bearing_rad: float
    last_seen_wall_s: float
    visits: int = 1
    evidence_frames: int = 0
    names: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "entry_id": self.entry_id,
            "label": self.label,
            "distance_m": round(float(self.distance_m), 3),
            "bearing_rad": round(float(self.bearing_rad), 4),
            "last_seen_wall_s": float(self.last_seen_wall_s),
            "visits": int(self.visits),
            "evidence_frames": int(self.evidence_frames),
            "names": list(self.names),
        }


@dataclass(frozen=True, slots=True)
class WorldAnswer:
    """What the dog says about the world, and what it was derived from.

    ``answered`` is the gate's verdict carried through, not a second opinion:
    this module never decides that an ungrounded query is grounded. It only
    decides the words.
    """

    query: str
    answered: bool
    text: str
    reason: str = ""
    place: PlaceSighting | None = None
    alternatives: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "query": self.query,
            "answered": self.answered,
            "text": self.text,
            "reason": self.reason,
            "place": self.place.as_dict() if self.place is not None else None,
            "alternatives": list(self.alternatives),
        }


def bearing_to(
    x: float, y: float, *, robot_xy: tuple[float, float] = (0.0, 0.0), robot_yaw_rad: float = 0.0
) -> float:
    """Signed bearing to a point in the robot's own frame, wrapped to ±π."""

    angle = math.atan2(float(y) - float(robot_xy[1]), float(x) - float(robot_xy[0]))
    angle -= float(robot_yaw_rad)
    return (angle + math.pi) % (2.0 * math.pi) - math.pi


def sighting_from_candidate(
    candidate: MapCandidate,
    *,
    last_seen_wall_s: float,
    robot_xy: tuple[float, float] = (0.0, 0.0),
    robot_yaw_rad: float = 0.0,
) -> PlaceSighting:
    """Adapt one query candidate into the row a sentence is written from."""

    return PlaceSighting(
        entry_id=candidate.entry_id,
        label=candidate.label,
        distance_m=float(candidate.distance_m),
        bearing_rad=bearing_to(
            candidate.x, candidate.y, robot_xy=robot_xy, robot_yaw_rad=robot_yaw_rad
        ),
        last_seen_wall_s=float(last_seen_wall_s),
        visits=int(candidate.visits),
        evidence_frames=int(candidate.evidence_frames),
        names=tuple(candidate.names),
    )


def describe_bearing(bearing_rad: float) -> str:
    """"to my left", "straight ahead", "behind me and to my right"."""

    bearing = (float(bearing_rad) + math.pi) % (2.0 * math.pi) - math.pi
    side = "left" if bearing > 0 else "right"
    magnitude = abs(bearing)
    for limit, phrase in _BEARING_BANDS:
        if magnitude <= limit:
            return phrase.format(side=side)
    return _BEHIND


def describe_distance(distance_m: float) -> str:
    """"about 4 m" — one significant step, never false precision.

    Under a metre the map's own fusion radius dominates, so "right next to me"
    is the honest reading of any number that small.
    """

    metres = abs(float(distance_m))
    if metres < 1.0:
        return "right next to me"
    if metres < 10.0:
        return f"about {metres:.0f} m away"
    return f"about {round(metres / 5.0) * 5:.0f} m away"


def describe_age(age_s: float) -> str:
    """The provenance half of every sentence: when it was last seen."""

    age = max(0.0, float(age_s))
    for limit, phrase in _AGE_BANDS:
        if age < limit:
            return phrase
    days = age / 86_400.0
    if days < 1.0:
        return _OLDER
    if days < 2.0:
        return "yesterday"
    return f"about {days:.0f} days ago"


def describe_visits(visits: int) -> str:
    """"" for one visit; "on two separate visits" for corroboration.

    Only said when it is worth saying: a place seen on several visits is a place
    the robot has real evidence for, and that is the one number a listener can
    use to decide how much to believe it.
    """

    count = int(visits)
    if count <= 1:
        return ""
    if count == 2:
        return ", on two separate visits"
    return f", on {count} separate visits"


def describe_place(place: PlaceSighting, *, now_wall_s: float) -> str:
    """The full label-primary, past-tense sentence for one remembered place."""

    noun = _with_article(place.label)
    # A proposed name that is just the detector's own label is not a name: the
    # map admits the label as vocabulary, so ``names`` routinely repeats it, and
    # "a bench — the one I've been calling the bench" is the sentence that gets
    # this feature switched off.
    name = next(
        (n for n in place.names if n.strip().casefold() != place.label.strip().casefold()),
        "",
    )
    named = f" — the one I've been calling the {name}" if name else ""
    return (
        f"I last saw {noun} {describe_distance(place.distance_m)} "
        f"{describe_bearing(place.bearing_rad)}{named}, "
        f"{describe_age(float(now_wall_s) - place.last_seen_wall_s)}"
        f"{describe_visits(place.visits)}."
    )


def where_is(
    query: str,
    sightings: Sequence[PlaceSighting],
    *,
    now_wall_s: float,
    answered: bool = True,
    reason: str = "",
    alternatives: Iterable[str] = (),
) -> WorldAnswer:
    """"Where is X?" — the top sighting, rendered; or a plain refusal.

    ``answered`` is the caller's gate verdict (``MapQueryResult.admitted``). An
    admitted query with no sightings is still a refusal: this module will not
    write a sentence about a place it was handed no evidence for.
    """

    clean = " ".join(str(query).split())
    others = tuple(str(a) for a in alternatives if str(a).strip())
    if not answered or not sightings:
        return WorldAnswer(
            query=clean,
            answered=False,
            text=_refusal_text(clean, others),
            reason=reason or "no grounded place for this query",
            alternatives=others,
        )
    best = sightings[0]
    return WorldAnswer(
        query=clean,
        answered=True,
        text=describe_place(best, now_wall_s=now_wall_s),
        reason=reason or "grounded",
        place=best,
        alternatives=others,
    )


def what_is_around(
    sightings: Sequence[PlaceSighting], *, now_wall_s: float, limit: int = 3
) -> WorldAnswer:
    """"What's around me?" — the nearest few, in one sentence, still past tense."""

    rows = list(sightings)[: max(0, int(limit))]
    if not rows:
        return WorldAnswer(
            query="around me",
            answered=False,
            text="I have not mapped anything around here yet.",
            reason="the map has no active entries in range",
        )
    parts = [
        f"{_with_article(row.label)} {describe_distance(row.distance_m)} "
        f"{describe_bearing(row.bearing_rad)}"
        for row in rows
    ]
    joined = parts[0] if len(parts) == 1 else ", ".join(parts[:-1]) + f", and {parts[-1]}"
    freshest = min(float(now_wall_s) - row.last_seen_wall_s for row in rows)
    return WorldAnswer(
        query="around me",
        answered=True,
        text=f"Last time I looked, {describe_age(freshest)}, there was {joined}.",
        reason="grounded",
        place=rows[0],
    )


def _refusal_text(query: str, alternatives: Sequence[str]) -> str:
    # Quoted rather than given an article: the query may be a whole sentence
    # ("where is the fountain"), and "I have not seen a where is the fountain"
    # is the kind of sentence that makes a listener stop trusting the robot.
    subject = f'"{query}"' if query else "that"
    base = f"I have not seen anything like {subject} anywhere I have been."
    if not alternatives:
        return base
    known = ", ".join(alternatives[:3])
    return f"{base} What I do know about round here: {known}."


def _with_article(label: str) -> str:
    clean = " ".join(str(label).split()) or "it"
    first = clean[0].lower()
    article = "an" if first in "aeiou" else "a"
    return f"{article} {clean}"


__all__ = [
    "PlaceSighting",
    "WorldAnswer",
    "bearing_to",
    "describe_age",
    "describe_bearing",
    "describe_distance",
    "describe_place",
    "describe_visits",
    "sighting_from_candidate",
    "what_is_around",
    "where_is",
]
