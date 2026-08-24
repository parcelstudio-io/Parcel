"""Honest clarification for utterances that name something but no known action.

The deterministic grammar is deliberately narrow: it recognizes reviewed verb
patterns and refuses everything else. That is right for *motion authority* and
wrong for *conversation* — "befriend the bench" matched no rule, carried no
physical-cue verb, and fell all the way through to the flat
``"I did not understand that command"``, which tells the owner nothing about
what the robot did understand.

This module supplies the missing half of the verb gate (stratum 3, language
lanes): when an utterance names a scene class the robot knows, or a spatial
relation it can achieve, say so and offer the relations that class actually
affords. **It never proposes motion** — it returns a sentence, and the caller
is in the conversation lane by construction.

Both halves are data, not literals: class names/aliases come from the per-scene
semantics sidecar and the offers come from each relation's own
``offer_phrase``, so a class whose affordances change cannot be advertised
wrongly here.
"""

from __future__ import annotations

import re
from functools import lru_cache

from parcel_robot.navigation.relation_registry import RELATIONS, RelationSpec
from parcel_robot.perception.scene_semantics import (
    SceneSemantics,
    SceneSemanticsError,
    scene_semantics,
)

#: Relations that are never offered about a *scene object* because they are
#: owner-anchored: "I can come to you" is not an answer to "the bench".
_OWNER_ANCHORED = frozenset({"follow", "behind", "orbit"})

#: Bare referring expressions a clarification answer may use, longest first.
#: Narrow on purpose: these are the words the clarification's *own offers* put
#: in the owner's mouth ("I can go to it, sit next to it, or walk towards it"),
#: not a general anaphora model. Anything wider would start rewriting "it" in
#: sentences the robot was never asked to resolve.
_PRONOUNS = ("that one", "that", "it")


@lru_cache(maxsize=1)
def _semantics() -> SceneSemantics | None:
    """Load the sidecar once; ``None`` when it is unavailable.

    Deliberately soft **here only**. The loader itself is fail-closed on a
    malformed sidecar; what this catches is a deployment with no sidecar at
    all, where the right behaviour is to fall back to today's flat reply rather
    than to make the agent unusable over a clarification helper.
    """

    try:
        return scene_semantics()
    except (SceneSemanticsError, FileNotFoundError, OSError):
        return None


def known_scene_words() -> tuple[str, ...]:
    """Every class name and alias the sidecar declares, longest first."""

    semantics = _semantics()
    if semantics is None:
        return ()
    return tuple(sorted(semantics.detector_query_set(), key=len, reverse=True))


def scene_class_mentioned(text: str) -> str | None:
    """Return the class a transcript names (via name or alias), else ``None``.

    Longest surface form wins, so "street light" resolves to ``lamppost``
    rather than stopping at "street".
    """

    semantics = _semantics()
    if semantics is None:
        return None
    clean = " ".join(str(text).strip().lower().split())
    if not clean:
        return None
    for word in known_scene_words():
        if re.search(rf"\b{re.escape(word)}\b", clean):
            found = semantics.resolve_class_word(word)
            if found is not None:
                return found.name
    return None


def relation_mentioned(text: str) -> RelationSpec | None:
    """Return the relation a transcript names by alias, else ``None``."""

    clean = " ".join(str(text).strip().lower().split())
    if not clean:
        return None
    for alias, name in sorted(RELATIONS.aliases().items(), key=lambda kv: -len(kv[0])):
        if re.search(rf"\b{re.escape(alias)}\b", clean):
            return RELATIONS.get(name)
    return None


def _offers(class_name: str) -> tuple[str, ...]:
    semantics = _semantics()
    if semantics is None:
        return ()
    scene_class = semantics.get(class_name)
    phrases: list[str] = []
    for relation in scene_class.affordances:
        if relation in _OWNER_ANCHORED:
            continue
        spec = RELATIONS.get(relation)
        if spec.offer_phrase and spec.offer_phrase not in phrases:
            phrases.append(spec.offer_phrase)
    return tuple(phrases)


def _join(phrases: tuple[str, ...]) -> str:
    if len(phrases) == 1:
        return phrases[0]
    if len(phrases) == 2:
        return f"{phrases[0]} or {phrases[1]}"
    return f"{', '.join(phrases[:-1])}, or {phrases[-1]}"


def clarification_for(text: str) -> str | None:
    """An honest clarification, or ``None`` when nothing is recognized.

    ``None`` is the important half: this must not manufacture a helpful-sounding
    reply for an utterance in which the robot recognized nothing at all.
    """

    class_name = scene_class_mentioned(text)
    if class_name is not None:
        offers = _offers(class_name)
        if offers:
            return (
                f"I'm not sure what you want me to do with the {class_name} — "
                f"I can {_join(offers)}. Which would you like?"
            )
        return (
            f"I know the {class_name}, but I don't have an action for it yet. "
            f"Could you say it another way?"
        )

    relation = relation_mentioned(text)
    if relation is not None and relation.offer_phrase:
        return (
            f"I can {relation.offer_phrase}, but I didn't catch what you meant "
            f"by that. Could you name the place or say it another way?"
        )
    return None


def resolve_pending_reference(text: str, referent: str | None) -> str | None:
    """Bind a bare pronoun to the class the last clarification asked about.

    Returns the rewritten utterance, or ``None`` when there is nothing to bind
    — no pending referent, no pronoun, or an utterance that already names a
    scene class of its own (in which case there is no ambiguity to resolve and
    silently overwriting it would be a lie about what was heard).

    This exists because the clarification is not free: offering *"I can go to
    it, sit next to it, or walk towards it"* and then compiling the owner's
    "go to it" into a mission whose target is the literal word ``it`` is worse
    than not asking. Measured before this landed: ``befriend the bench`` →
    clarification → ``go to it`` published a plan and answered *"Okay—I'll go
    wait near it safely."*
    """

    if not referent:
        return None
    clean = " ".join(str(text).strip().split())
    if not clean or scene_class_mentioned(clean) is not None:
        return None
    for pronoun in _PRONOUNS:
        pattern = rf"\b{re.escape(pronoun)}\b"
        if re.search(pattern, clean, flags=re.IGNORECASE):
            return re.sub(pattern, f"the {referent}", clean, count=1, flags=re.IGNORECASE)
    return None


#: A destination that is only a referring expression. Matched at the end of a
#: parsed navigation directive, so a real label that merely contains the
#: letters ("summit") is untouched.
_DANGLING_DESTINATION = re.compile(r"\b(?:it|that|that one|them|those)\s*$", re.IGNORECASE)


def dangling_reference(directive: str) -> str | None:
    """The bare pronoun a directive leans on, when nothing established it.

    ``"go to it"`` with no pending referent parses as a destination and used to
    compile a mission whose target was the word ``it`` — a landmark that cannot
    exist. Answering the pronoun is honest; accepting the command and failing
    to ground it later is not.
    """

    clean = " ".join(str(directive).strip().split())
    if not clean or scene_class_mentioned(clean) is not None:
        return None
    match = _DANGLING_DESTINATION.search(clean)
    return match.group(0).strip().lower() if match is not None else None


__all__ = [
    "clarification_for",
    "dangling_reference",
    "known_scene_words",
    "relation_mentioned",
    "resolve_pending_reference",
    "scene_class_mentioned",
]
