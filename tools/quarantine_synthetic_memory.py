#!/usr/bin/env python
"""Identify — and, only when told twice, set aside — executor-written rows.

CARD R27 WORK ITEM 4. THE OWNER'S DATA IS THEIRS.
=================================================

Between 2026-08-20 21:12 and 2026-08-21 13:48 (UTC, the stamps the store itself
carries) **256 synthetic rows** were written into ``parcel_memory.sqlite3`` by
four consecutive card-chains running proofs from the repo root with the shipped
config. ``src/parcel_robot/memory_path.py`` stops the next one. This tool is
about the rows already there, and it deliberately does **less** than it could:

* **It never deletes.** ``--apply`` moves rows into a side table,
  ``quarantined_messages``, which keeps every original column plus when and why.
  Putting a row back is one INSERT … SELECT, and the tool prints it.
* **Dry-run is the default**, and the dry run opens the database ``mode=ro``,
  so the read path cannot write even if this file has a bug in it.
* **The owner decides.** This tool was written by the executor who built the
  guard; it was NOT run in destructive mode against the owner's store, and it
  cannot be by accident — ``--apply`` against the owner's file has to satisfy
  the very refusal this card added (``PARCEL_MEMORY_PURPOSE=owner``), which no
  executor sets.

WHY THE ROWS CANNOT BE PICKED OUT BY CONTENT ALONE
--------------------------------------------------

They look exactly like the genuine ones. Measured on the real store:

* 2,618 genuine legacy rows carry ``speaker IS NULL AND origin IS NULL``. So do
  all 256 synthetic ones. The R1 annotation columns were added later, and the
  legacy panel/voice path never set them.
* The synthetic contents are 25 distinct strings — "go to the lamppost", "find
  the fountain", "circle the owner once" — and the owner has typed most of them
  for real on other days.

The one discriminator that survives is **when**, which is why the windows below
are data with sources attached rather than a heuristic. Everything else in the
predicate is a *narrowing* safety check, never a widening one.

THE BOUNDARY IS INDEPENDENTLY CORROBORATED
------------------------------------------

Row id 2882 is the last genuine row, and three separate measurements agree:

1. ``created_at`` gaps: id 2882 at 2026-08-20 20:30:12, then a 42-minute gap to
   id 2883 at 21:12:29, where the synthetic burst starts.
2. R18's docstring counted the store at **2,882 rows** on 2026-08-20, before any
   of this began.
3. R18 also counted **2,618** NULL-speaker/NULL-origin rows at that moment,
   which is exactly what ``id <= 2882`` yields today.

The windows still bound the predicate by time rather than by ``id > 2882``: an
id cutoff would silently swallow any genuine turn the owner takes from now on,
and a window cannot.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
if str(REPO / "src") not in sys.path:
    sys.path.insert(0, str(REPO / "src"))

from parcel_robot.memory import ConversationMemory
from parcel_robot.memory_path import (
    ENV_PURPOSE,
    PURPOSE_OWNER,
    WRITER_OWNER_STACK,
    MemoryPathRefused,
    owner_store_paths,
)

#: The side table. Same columns as ``messages`` plus two of our own. Named in
#: full rather than generated so a worried owner can grep for it.
QUARANTINE_TABLE = "quarantined_messages"


@dataclass(frozen=True)
class Window:
    """One measured burst of executor writes, with where the claim comes from."""

    start: str
    end: str
    source: str


#: The default suspect windows. UTC, inclusive both ends, matching the format
#: SQLite's ``CURRENT_TIMESTAMP`` writes into ``created_at``.
#:
#: Two entries and not eight, although the writes arrive in eight contiguous
#: bursts, because the two correspond to *claims somebody made* — which is what
#: an owner reviewing this needs to check — rather than to clusters this tool
#: found in the data and then declared suspicious.
SUSPECT_WINDOWS: tuple[Window, ...] = (
    Window(
        "2026-08-20 21:12:00",
        "2026-08-21 11:05:59",
        "card R27 README: the 182 rows measured when the card was written; "
        "R24_STATUS §4.5 and R26_STATUS §11 both claimed this window was clean",
    ),
    Window(
        "2026-08-21 13:31:00",
        "2026-08-21 13:48:59",
        "the 74 rows added while card R27 itself sat unexecuted; PG3_STATUS §8.1 "
        "says 'Nothing was run live' and its own window wrote at 13:48:52 UTC",
    ),
)

#: The predicate, as one place. A row is a candidate when it is inside a window
#: AND carries no evidence that the owner's own stack wrote it.
#:
#: ``writer <> 'owner_stack'`` rather than ``writer IS NULL`` so the tool keeps
#: working after R27: from now on the owner's stack stamps every row it writes,
#: so a future stray row shows up as ``writer='test'`` or ``'unknown'`` and is
#: caught by the same predicate that catches today's un-stamped ones.
_CANDIDATE_PREDICATE = (
    "speaker IS NULL AND origin IS NULL AND session_id IS NULL "
    "AND provider_item_id IS NULL "
    f"AND (writer IS NULL OR writer <> '{WRITER_OWNER_STACK}') "
    "AND created_at >= ? AND created_at <= ?"
)


def _columns(connection: sqlite3.Connection) -> list[str]:
    return [str(row[1]) for row in connection.execute("PRAGMA table_info(messages)")]


def candidates(connection: sqlite3.Connection, windows: tuple[Window, ...]) -> list[dict]:
    """Every row the tool would move, newest column set included, oldest first."""

    available = _columns(connection)
    # ``writer`` only exists after R27's migration, and the dry run must work on
    # a store that has never been opened by a post-R27 writer — which is exactly
    # the owner's store today. Substituting NULL keeps one predicate string.
    writer_expr = "writer" if "writer" in available else "NULL AS writer"
    found: list[dict] = []
    for window in windows:
        sql = (
            f"SELECT id, role, content, created_at, session_id, speaker, origin, "
            f"provider_item_id, {writer_expr} FROM messages WHERE "
            f"{_CANDIDATE_PREDICATE} ORDER BY id"
        )
        for row in connection.execute(sql, (window.start, window.end)):
            found.append(
                {
                    "id": int(row[0]),
                    "role": row[1],
                    "content": row[2],
                    "created_at": row[3],
                    "writer": row[8],
                    "window": f"{window.start}..{window.end}",
                    "window_source": window.source,
                }
            )
    found.sort(key=lambda item: item["id"])
    return found


def survey(connection: sqlite3.Connection, windows: tuple[Window, ...]) -> dict:
    """Counts an owner needs to judge the proposal, including what is NOT moved."""

    total = int(connection.execute("SELECT COUNT(*) FROM messages").fetchone()[0])
    rows = candidates(connection, windows)
    ids = [row["id"] for row in rows]
    per_window: list[dict] = []
    for window in windows:
        subset = [r for r in rows if r["window"] == f"{window.start}..{window.end}"]
        per_window.append(
            {
                "start": window.start,
                "end": window.end,
                "source": window.source,
                "rows": len(subset),
                "id_range": [min(r["id"] for r in subset), max(r["id"] for r in subset)]
                if subset
                else None,
            }
        )
    contents: dict[str, int] = {}
    for row in rows:
        text = " ".join(str(row["content"] or "").split())
        contents[text] = contents.get(text, 0) + 1
    return {
        "total_rows": total,
        "candidates": len(rows),
        "retained": total - len(rows),
        "id_min": min(ids) if ids else None,
        "id_max": max(ids) if ids else None,
        "windows": per_window,
        "distinct_contents": len(contents),
        "contents": sorted(contents.items(), key=lambda kv: (-kv[1], kv[0])),
        "rows": rows,
    }


def render(report: dict, store: Path, applied: bool) -> str:
    """The human report. Written to be read by the owner, not by a script."""

    mode = "APPLIED — rows moved" if applied else "DRY RUN — nothing was changed"
    lines = [
        "quarantine_synthetic_memory — card R27 work item 4",
        "=" * 74,
        f"store      : {store}",
        f"mode       : {mode}",
        f"total rows : {report['total_rows']}",
        f"candidates : {report['candidates']}"
        + (
            f"   (ids {report['id_min']}–{report['id_max']})"
            if report["id_min"] is not None
            else ""
        ),
        f"retained   : {report['retained']}   <- everything else is untouched",
        "",
        "Windows searched",
        "-" * 74,
    ]
    for window in report["windows"]:
        span = (
            f"ids {window['id_range'][0]}–{window['id_range'][1]}"
            if window["id_range"]
            else "no rows"
        )
        lines.append(f"  {window['start']} .. {window['end']} UTC")
        lines.append(f"    matched : {window['rows']} rows   ({span})")
        lines.append(f"    source  : {window['source']}")
    lines += [
        "",
        f"Distinct contents among candidates: {report['distinct_contents']}",
        "-" * 74,
    ]
    for text, count in report["contents"]:
        shown = text if len(text) <= 84 else text[:81] + "..."
        lines.append(f"  {count:4d}x  {shown}")
    if not applied:
        lines += [
            "",
            "Nothing was changed. To act on this, the OWNER runs:",
            f"    {ENV_PURPOSE}={PURPOSE_OWNER} .parcel/bin/python \\",
            "        tools/quarantine_synthetic_memory.py --apply",
            "",
            f"which MOVES these rows to `{QUARANTINE_TABLE}` (it never deletes).",
            "To undo, in sqlite3:",
            (
                f"    INSERT INTO messages SELECT {', '.join(_MESSAGE_COLS)} "
                f"FROM {QUARANTINE_TABLE};"
            ),
            f"    DELETE FROM {QUARANTINE_TABLE};",
        ]
    return "\n".join(lines)


_MESSAGE_COLS = (
    "id",
    "role",
    "content",
    "created_at",
    "session_id",
    "speaker",
    "origin",
    "provider_item_id",
    "writer",
)


def apply_quarantine(memory: ConversationMemory, rows: list[dict], reason: str) -> int:
    """Copy the candidates into the side table, then remove them. One transaction.

    Order matters and is not stylistic: the copy is verified with a COUNT before
    a single DELETE runs, so a failure anywhere leaves the store exactly as it
    was rather than half-quarantined.
    """

    if not rows:
        return 0
    connection = memory.connection
    available = _columns(connection)
    cols = [c for c in _MESSAGE_COLS if c in available]
    ids = [row["id"] for row in rows]
    placeholders = ",".join("?" for _ in ids)
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    with connection:
        connection.execute(
            f"CREATE TABLE IF NOT EXISTS {QUARANTINE_TABLE} ("
            + ", ".join(f"{c} TEXT" for c in cols)
            + ", quarantined_at TEXT NOT NULL, quarantine_reason TEXT NOT NULL)"
        )
        connection.execute(
            f"INSERT INTO {QUARANTINE_TABLE} ({', '.join(cols)}, quarantined_at, "
            f"quarantine_reason) SELECT {', '.join(cols)}, ?, ? FROM messages "
            f"WHERE id IN ({placeholders})",
            (stamp, reason, *ids),
        )
        moved = int(
            connection.execute(
                f"SELECT COUNT(*) FROM {QUARANTINE_TABLE} WHERE quarantined_at = ?", (stamp,)
            ).fetchone()[0]
        )
        if moved != len(ids):
            raise RuntimeError(
                f"refusing to delete: copied {moved} of {len(ids)} rows into "
                f"{QUARANTINE_TABLE}; the store is unchanged"
            )
        connection.execute(f"DELETE FROM messages WHERE id IN ({placeholders})", tuple(ids))
    return moved


def parse_window(text: str) -> Window:
    if ".." not in text:
        raise argparse.ArgumentTypeError(
            f"--window wants 'START..END' in UTC, got {text!r} "
            "(e.g. '2026-08-20 21:12:00..2026-08-21 11:05:59')"
        )
    start, end = (part.strip() for part in text.split("..", 1))
    if start > end:
        raise argparse.ArgumentTypeError(f"--window runs backwards: {start!r} > {end!r}")
    return Window(start, end, "supplied on the command line")


def default_store() -> Path:
    paths = owner_store_paths()
    return paths[0] if paths else REPO / "parcel_memory.sqlite3"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--store", type=Path, default=None, help="database (default: the owner's)")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="MOVE the candidates to the side table. Without this the tool only reports.",
    )
    parser.add_argument(
        "--window",
        type=parse_window,
        action="append",
        default=None,
        metavar="'START..END'",
        help="override the built-in suspect windows (UTC, repeatable)",
    )
    parser.add_argument("--json", action="store_true", help="emit the report as JSON too")
    parser.add_argument(
        "--reason",
        default="card R27: executor-written synthetic rows, quarantined by owner request",
        help="stored on every moved row",
    )
    args = parser.parse_args(argv)

    store = (args.store or default_store()).expanduser().resolve()
    windows = tuple(args.window) if args.window else SUSPECT_WINDOWS
    if not store.exists():
        print(f"no such store: {store}", file=sys.stderr)
        return 2

    if not args.apply:
        # mode=ro through the audited R18 opener: the engine refuses writes, so
        # the dry run is safe over the owner's real file by construction and not
        # by this file being careful.
        memory = ConversationMemory(store, read_only=True)
        report = survey(memory.connection, windows)
        print(render(report, store, applied=False))
        if args.json:
            print(json.dumps({k: v for k, v in report.items() if k != "rows"}, indent=2))
        memory.connection.close()
        return 0

    print("=" * 74)
    print(f"  --apply: rows will MOVE out of `messages` into `{QUARANTINE_TABLE}`.")
    print("  Nothing is deleted, and the report above tells you how to undo it.")
    print("=" * 74)
    try:
        # purpose is NOT forced here. Against the owner's store this raises
        # unless the caller exported PARCEL_MEMORY_PURPOSE=owner — the same
        # gate this card built, applied to this card's own tool.
        memory = ConversationMemory(store)
    except MemoryPathRefused as refusal:
        print(str(refusal), file=sys.stderr)
        print(
            "\n--apply on the owner's store is the owner's decision to make, "
            f"and it is spelled:\n    {ENV_PURPOSE}={PURPOSE_OWNER} "
            f"{sys.executable} {Path(__file__).name} --apply",
            file=sys.stderr,
        )
        return 3
    report = survey(memory.connection, windows)
    moved = apply_quarantine(memory, report["rows"], args.reason)
    print(render(report, store, applied=True))
    print(f"\nmoved {moved} rows into {QUARANTINE_TABLE}.")
    if args.json:
        print(json.dumps({k: v for k, v in report.items() if k != "rows"}, indent=2))
    memory.connection.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
