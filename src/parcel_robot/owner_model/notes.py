"""``owner_notes`` — the one block of the DI that has never had anything in it.

CARD P2-A, WORK ITEM 2 (LAST SENTENCE)
======================================

``realtime/prompting.py`` has rendered an ``owner_notes`` block since the prompt
plane was built. ``DeveloperContext`` takes an ``owner_notes`` provider.
``runtime.py`` has never passed one. Twenty-five sealed corpus fixtures carry
hand-written notes because the fixtures were the only thing that ever filled it.

This module is the provider. It is small on purpose: it turns rows into lines
and it drops everything the owner has not consented to.

THE RENDER IS THE CONSENT BOUNDARY
----------------------------------

There are two places a fact can leak: the answer to "what do you know about me"
and this block. The answer path is the one an owner would think to check. This
one is not — it is assembled at session open, sent once, and never displayed.
So the filter lives HERE, in the function that builds the lines, and not in the
caller: a future caller that forgets to filter gets filtered anyway.

``pending`` and ``denied`` rows are excluded, and so are soft-deleted ones. A
row the owner said "don't remember that" about stops appearing in the very next
session, which is probe row 3.

EMPTY MEANS EMPTY
-----------------

Returning ``()`` renders **nothing** — not a header, not "no notes". That is
what keeps ``PINNED_DI_DIGEST`` and the 25 sealed fixtures valid: a store with
no consented facts produces byte-identical DI text to the state before this
card. See ``render_developer_instruction``'s R18 note for the same argument
about the ``scene`` block.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from .policy import CONSENT_GRANTED

#: Matches ``realtime.prompting.MAX_OWNER_NOTES``. Not imported from there: this
#: module is the *producer* and the prompt plane re-caps its input anyway
#: (``_clean_lines``), so an import would buy a coupling and no guarantee.
DEFAULT_NOTE_LIMIT = 6

#: One note longer than this is a paragraph, and a paragraph in the developer
#: instruction is tokens the owner pays for at every session open.
MAX_NOTE_CHARS = 160


def _renderable(row: Mapping[str, Any]) -> bool:
    if row.get("deleted_at"):
        return False
    return str(row.get("consent") or "").strip().lower() == CONSENT_GRANTED


def owner_notes_from_facts(
    rows: Sequence[Mapping[str, Any]],
    *,
    limit: int = DEFAULT_NOTE_LIMIT,
) -> tuple[str, ...]:
    """Consented, live facts as DI lines — newest first, capped, deduped.

    Newest first because the cap bites: when the owner has told the robot more
    than ``limit`` things, the ones it should carry into the next conversation
    are the recent ones. Ties are broken by the store's own ordering, which is
    ``updated_at`` then ``id`` — total and reproducible.
    """

    out: list[str] = []
    seen: set[str] = set()
    for row in rows:
        if not _renderable(row):
            continue
        text = " ".join(str(row.get("value") or "").split())
        if not text:
            continue
        if len(text) > MAX_NOTE_CHARS:
            text = text[: MAX_NOTE_CHARS - 1].rstrip() + "…"
        fingerprint = text.lower()
        if fingerprint in seen:
            continue
        seen.add(fingerprint)
        out.append(text)
        if len(out) >= max(1, int(limit)):
            break
    return tuple(out)


def known_facts_answer(
    rows: Sequence[Mapping[str, Any]],
    *,
    limit: int = 12,
) -> tuple[str, ...]:
    """The "what do you know about me" answer. Same filter, longer leash.

    A separate function from :func:`owner_notes_from_facts` because the two have
    different budgets and one of them is a direct question from the owner: the
    DI block is a standing cost paid every session, and an answer is paid once.
    The consent filter is identical and that is the point — the owner must not
    be able to hear a fact the model was never allowed to see, or vice versa.
    """

    return owner_notes_from_facts(rows, limit=limit)


__all__ = [
    "DEFAULT_NOTE_LIMIT",
    "MAX_NOTE_CHARS",
    "known_facts_answer",
    "owner_notes_from_facts",
]
