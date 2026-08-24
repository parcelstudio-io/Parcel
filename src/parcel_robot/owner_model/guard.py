"""The distiller will not learn that the owner loves lampposts.

CARD P2-A, WORK ITEM 5. THE 256 ROWS ARE STILL THERE.
=====================================================

Between 2026-08-20 21:12:29 and 2026-08-21 13:48:52 UTC, four consecutive
card-chains wrote **256 synthetic rows** into the owner's real conversation
store — ids 2883–3138, measured and triple-corroborated by card R27
(``scrum/20260821/task_9/R27_STATUS.md`` §0). They are sentences like *"go to
the lamppost"* and *"find the fountain"*, typed by executors running proofs
from the repo root.

R27 built two things: ``memory_path.py``, which stops the *next* one, and
``tools/quarantine_synthetic_memory.py``, which offers to move the existing
ones into a side table. It deliberately did **not** run the second one: the
rows are the owner's data and moving them is the owner's decision.

So as of this card they are still in ``messages``. And this card is the one
that teaches the robot to derive durable facts about its owner from that table.
Without this module, the first distillation run produces a permanent
``owner_facts`` row saying the owner is interested in lampposts — a fabricated
belief about a person, laundered through an audit-clean pipeline, indexed by
key, rendered into every future session's developer instruction, and spoken
aloud with confidence. That is materially worse than the original pollution,
because a raw row is at least visibly a raw row.

Hence: **the distiller refuses to run on a store whose synthetic range is
un-quarantined.** Not a warning, not a filter, not a skip — a refusal that
names the count, the id range and the exact command the owner runs.

WHY REFUSE INSTEAD OF JUST EXCLUDING THE ROWS
---------------------------------------------

Filtering would work, and it is the wrong shape. The synthetic rows are not
separable by content (R27 measured this: the owner has genuinely typed most of
those sentences on other days), so any filter is a filter *by id range*, which
means a hardcoded id range silently deciding what the robot may believe about
its owner. If that range is ever wrong — off by one, or applied to a restored
backup with different ids — the failure is silent and the wrong facts are
durable. A refusal fails loudly and puts the decision back where R27 left it:
with the owner.

This is the one refusal path this card adds, and the wave's "prefer ask over
refuse" rule is why it is scoped as narrowly as it is: it gates exactly one
operation (distillation), on exactly one store shape, and it is satisfied by a
command that already exists and takes one second.

THE PREDICATE IS R27'S, NARROWED
--------------------------------

A row is synthetic-suspect when **all** of these hold:

* its id is inside :data:`SYNTHETIC_ID_RANGE`, **and**
* its ``created_at`` is inside one of R27's two measured windows, **and**
* it carries no evidence the owner's own stack wrote it — the R1 annotation
  columns are all NULL and ``writer`` is not ``owner_stack``.

All three, so a fresh scratch store cannot trip it by accident: a scratch store
that happens to reach id 2883 carries today's timestamps, not August 20th's.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from ..memory.path import WRITER_OWNER_STACK

#: The ids R27 measured. Inclusive both ends.
SYNTHETIC_ID_RANGE: tuple[int, int] = (2883, 3138)

#: R27's two suspect windows, verbatim from
#: ``tools/quarantine_synthetic_memory.py``. Kept as literals rather than
#: imported so this guard has no import dependency on a ``tools/`` script that
#: is not part of the installed package.
SYNTHETIC_WINDOWS: tuple[tuple[str, str], ...] = (
    ("2026-08-20 21:12:00", "2026-08-21 11:05:59"),
    ("2026-08-21 13:31:00", "2026-08-21 13:48:59"),
)

#: The side table ``tools/quarantine_synthetic_memory.py --apply`` moves rows
#: into. Its existence is not the signal — the ABSENCE of the rows from
#: ``messages`` is — but it is reported so the owner can see the undo is there.
QUARANTINE_TABLE = "quarantined_messages"

#: The command the refusal names. One place, so the message and the docs cannot
#: drift apart.
QUARANTINE_COMMAND = (
    "PARCEL_MEMORY_PURPOSE=owner .parcel/bin/python "
    "tools/quarantine_synthetic_memory.py --apply"
)

#: The dry run, which is safe for anybody to run and reads the store ``mode=ro``.
QUARANTINE_DRY_RUN = ".parcel/bin/python tools/quarantine_synthetic_memory.py"


class SyntheticRowsUnquarantined(RuntimeError):
    """This store still holds executor-written rows; nothing may be distilled.

    ``RuntimeError`` for the same reason
    :class:`~parcel_robot.memory.path.MemoryPathRefused` is one: several call
    sites catch ``ValueError`` broadly to keep a turn alive, and this refusal
    must not be swallowed by a never-break-a-turn guard. A distillation pass is
    a background write, not a turn; stopping it costs nothing and letting it
    through costs a permanent false belief.
    """


@dataclass(frozen=True)
class SyntheticSurvey:
    """What the guard found. Reported whether or not it refused."""

    #: Rows matching the full predicate that are still in ``messages``.
    suspect_rows: int
    #: Their id bounds, or ``None`` when there are none.
    id_min: int | None
    id_max: int | None
    #: Rows sitting in the side table, i.e. already dealt with.
    quarantined_rows: int
    #: True when the table exists at all.
    quarantine_table_present: bool
    #: Total rows in ``messages``, for context in a status doc.
    total_rows: int

    @property
    def clean(self) -> bool:
        return self.suspect_rows == 0

    def as_dict(self) -> dict[str, object]:
        return {
            "suspect_rows": self.suspect_rows,
            "id_min": self.id_min,
            "id_max": self.id_max,
            "quarantined_rows": self.quarantined_rows,
            "quarantine_table_present": self.quarantine_table_present,
            "total_rows": self.total_rows,
            "clean": self.clean,
        }


def _columns(connection: sqlite3.Connection, table: str) -> set[str]:
    try:
        return {str(row[1]) for row in connection.execute(f"PRAGMA table_info({table})")}
    except sqlite3.DatabaseError:  # pragma: no cover - defensive
        return set()


def _predicate(available: set[str]) -> str:
    """The three-part predicate, degrading gracefully on an older schema.

    A store predating card R1 has none of the annotation columns. Their absence
    is not evidence of innocence and not evidence of guilt — it is the shape
    every row had before R1 — so a missing column contributes ``1=1`` and the
    id-range and window halves carry the decision on their own.
    """

    parts = [
        "id >= ? AND id <= ?",
        "created_at >= ? AND created_at <= ?",
    ]
    for column in ("speaker", "origin", "session_id", "provider_item_id"):
        if column in available:
            parts.append(f"{column} IS NULL")
    if "writer" in available:
        parts.append(f"(writer IS NULL OR writer <> '{WRITER_OWNER_STACK}')")
    return " AND ".join(parts)


def survey(connection: sqlite3.Connection) -> SyntheticSurvey:
    """Count the un-quarantined synthetic rows. Read-only; never writes.

    Safe against a ``mode=ro`` connection and against a store that has no
    ``messages`` table at all (a brand-new scratch file), which reports zero.
    """

    available = _columns(connection, "messages")
    if not available:
        return SyntheticSurvey(0, None, None, 0, False, 0)

    total = int(connection.execute("SELECT COUNT(*) FROM messages").fetchone()[0])
    predicate = _predicate(available)
    low, high = SYNTHETIC_ID_RANGE
    found = 0
    bounds: list[int] = []
    for start, end in SYNTHETIC_WINDOWS:
        row = connection.execute(
            f"SELECT COUNT(*), MIN(id), MAX(id) FROM messages WHERE {predicate}",
            (low, high, start, end),
        ).fetchone()
        count = int(row[0] or 0)
        if count:
            found += count
            bounds.extend([int(row[1]), int(row[2])])

    table_present = bool(
        connection.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name=?",
            (QUARANTINE_TABLE,),
        ).fetchone()[0]
    )
    quarantined = 0
    if table_present:
        quarantined = int(
            connection.execute(f"SELECT COUNT(*) FROM {QUARANTINE_TABLE}").fetchone()[0]
        )

    return SyntheticSurvey(
        suspect_rows=found,
        id_min=min(bounds) if bounds else None,
        id_max=max(bounds) if bounds else None,
        quarantined_rows=quarantined,
        quarantine_table_present=table_present,
        total_rows=total,
    )


def refusal_text(found: SyntheticSurvey, *, store_label: str = "") -> str:
    """The message. Written for the owner, and it names the way out."""

    where = f"    store   : {store_label}\n" if store_label else ""
    span = (
        f" (ids {found.id_min}–{found.id_max})"
        if found.id_min is not None
        else ""
    )
    return (
        "card P2-A: refusing to distil owner facts from a store whose synthetic\n"
        "range has not been quarantined.\n"
        f"{where}"
        f"    suspect : {found.suspect_rows} row(s){span}\n"
        f"    of      : {found.total_rows} row(s) total\n"
        "\n"
        "Those rows were typed by executors running proofs, not by the owner\n"
        "(card R27, 2026-08-21). Distilling them would turn 'go to the lamppost'\n"
        "into a durable, indexed, spoken-aloud belief that the owner likes\n"
        "lampposts — a fabricated fact about a person, which is worse than the\n"
        "raw rows, because a raw row is visibly a raw row.\n"
        "\n"
        "This is the OWNER'S decision and this code will not make it. Look first:\n"
        f"    {QUARANTINE_DRY_RUN}\n"
        "then, if the report is right:\n"
        f"    {QUARANTINE_COMMAND}\n"
        "\n"
        f"It MOVES the rows into `{QUARANTINE_TABLE}` and never deletes them; the\n"
        "dry run prints the one-line undo."
    )


def assert_store_is_distillable(
    connection: sqlite3.Connection, *, store_label: str = ""
) -> SyntheticSurvey:
    """Raise :class:`SyntheticRowsUnquarantined` unless the range is dealt with.

    Returns the survey on success so a caller can report "0 suspect rows, 256
    quarantined" rather than merely "did not raise".
    """

    found = survey(connection)
    if not found.clean:
        raise SyntheticRowsUnquarantined(refusal_text(found, store_label=store_label))
    return found


__all__ = [
    "QUARANTINE_COMMAND",
    "QUARANTINE_DRY_RUN",
    "QUARANTINE_TABLE",
    "SYNTHETIC_ID_RANGE",
    "SYNTHETIC_WINDOWS",
    "SyntheticRowsUnquarantined",
    "SyntheticSurvey",
    "assert_store_is_distillable",
    "refusal_text",
    "survey",
]
