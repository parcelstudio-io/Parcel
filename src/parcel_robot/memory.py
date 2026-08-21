from __future__ import annotations

import logging
import re
import sqlite3
import threading
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path

from .conversation_store import ConversationStore, mirror_realtime_turn, parse_sqlite_utc
from .memory_path import ResolvedStore, resolve_memory_path

logger = logging.getLogger(__name__)

#: Columns added for the Realtime lane's both-sides turn ledger (card R1).
#: Every one is NULLABLE with no default, so the ALTER TABLE below is purely
#: additive: rows written before this card keep reading exactly as they did,
#: and ``recent()`` — the only pre-existing reader, consumed at agent.py:498 —
#: still selects just ``role, content``.
REALTIME_COLUMNS: tuple[tuple[str, str], ...] = (
    ("session_id", "TEXT"),
    ("speaker", "TEXT"),
    ("origin", "TEXT"),
    ("provider_item_id", "TEXT"),
)

#: Card R27 work item 2 — WHO WROTE THIS ROW, as a class of process.
#:
#: Kept as its own tuple rather than appended to ``REALTIME_COLUMNS`` because
#: that constant is the *Realtime lane's* annotation set and a test asserts its
#: membership (``tests/test_realtime_lane.py``); this column is about the
#: writing process, not about the lane, and conflating them would make a future
#: reader think ``writer`` is a hosted-turn field.
#:
#: Nullable with no default, exactly like R1's four, so the migration stays
#: purely additive over the owner's 3,138 existing rows. **Backfill is not
#: attempted and must not be**: every pre-R27 row would have to be *guessed* at,
#: and a guessed provenance column is worse than an honest NULL — it would make
#: the next pollution audit trust a fabricated answer. NULL here means "written
#: before this column existed", which is a true statement about every one of
#: them.
PROVENANCE_COLUMNS: tuple[tuple[str, str], ...] = (("writer", "TEXT"),)

#: Every column this class migrates in, in application order.
MIGRATED_COLUMNS: tuple[tuple[str, str], ...] = REALTIME_COLUMNS + PROVENANCE_COLUMNS

#: Who said it → the role the existing schema already understands. The lane
#: needs the distinction (a hosted reply is not a local one), but inventing a
#: new ``role`` value would break ``add()``'s Python-side whitelist and every
#: consumer that switches on role.
_SPEAKER_ROLES = {"owner": "user", "robot": "assistant", "system": "tool"}

# ===================================================================== card R18
# RECALL — the READ path that answers "what do you remember about me".
#
# THE DEFECT THIS REPLACES, measured against the owner's own store on
# 2026-08-20 (2,882 rows, 2026-08-02 → 2026-08-20):
#
#   role/origin/speaker            rows   visible to the old recall?
#   user   / NULL     / NULL       1306   NO
#   assistant / NULL  / NULL       1299   NO
#   assistant / realtime / robot    125   yes
#   user   / realtime / owner        82   yes
#   tool   / realtime / system       57   yes  (session bookkeeping!)
#   tool   / NULL     / NULL         13   NO
#
# ``runtime._realtime_recall`` read ``realtime_turns()``, whose
# ``speaker IS NOT NULL`` filter exists to stop a typed panel command being
# replayed to the provider as if the hosted agent had said it. That filter is
# right where it is and wrong here: it hid **2,618 of 2,882 rows** — every
# conversation the owner has ever had through the local voice/panel path — while
# admitting the 57 ``[session rollover]`` markers, which are not conversation at
# all. Card R18 work item 2, "queries the FULL conversation store (both
# origins)", is exactly that arithmetic.
#
# The rows are the same rows. This is a READ, and only a read: nothing here
# writes, migrates, or changes what ``realtime_turns`` returns to its own caller.

#: ``role`` → who was speaking, for the rows that predate the R1 annotation
#: columns. The legacy path (``add()``) never set ``speaker``, so the role IS
#: the provenance for 2,618 of the owner's rows and dropping them for want of a
#: column would be discarding the conversation to preserve a schema.
_ROLE_SPEAKERS = {"user": "owner", "assistant": "robot", "tool": "system"}

#: Never recalled. ``system`` rows are session bookkeeping the lane writes —
#: ``[session rollover]``, summaries, stall notes. They are real rows and they
#: are not something the owner said or the robot said back, so surfacing one as
#: a memory would be the robot quoting its own plumbing at its owner.
RECALL_SPEAKERS: frozenset[str] = frozenset({"owner", "robot"})

#: Words that carry no retrieval signal in a question addressed TO the robot.
#: Deliberately small and deliberately closed: this is not a linguistic stopword
#: list, it is the set of words that appear in "what do you remember about me"
#: and its neighbours. Anything not in here is treated as a real search term,
#: which is the failure direction that costs a slightly worse match rather than
#: a silent miss.
#:
#: ``owner`` and ``user`` are in here because of the live proof, and they earn
#: their place. THE MODEL CHOOSES THE QUERY STRING, and asked "What do you
#: remember about me?" ``gpt-realtime-2.1-mini`` called
#: ``recall_memory({"query": "owner"})`` — inventing a topic where the question
#: had none. Against the owner's real store that keyword-matched five typed test
#: commands ("go to the owner", "walk around the owner", "circle the owner
#: once") and, worse, matched the robot's OWN owner_session_1 sentence *"there's
#: no memory of what I know about you yet"* and had it read back out loud. There
#: is exactly one owner in this system and they are the person asking, so
#: "owner" as a search term is self-reference — which is the recency mode's
#: question, not the keyword mode's.
RECALL_STOPWORDS: frozenset[str] = frozenset(
    {
        "a", "about", "all", "am", "an", "and", "any", "anything", "are", "as", "at",
        "be", "been", "can", "could", "did", "do", "does", "for", "from", "get",
        "had", "has", "have", "he", "her", "him", "his", "how", "i", "if", "in",
        "is", "it", "its", "know", "me", "mine", "my", "of", "on", "or", "our",
        "owner", "recall", "remember", "said", "say", "she", "so", "some",
        "something", "talk", "talked", "tell", "that", "the", "their", "them",
        "then", "there", "these", "they", "this", "those", "to", "told", "up",
        "us", "user", "was", "we", "were", "what", "when", "where", "which",
        "who", "why", "will", "with", "would", "you", "your", "yours",
    }
)

#: How many memories one recall may return. A spoken answer, not a transcript.
RECALL_LIMIT = 5

#: How many rows the ranker reads. The whole store would be correct and is not
#: needed: 4,000 rows is a fortnight of heavy use at the owner's measured rate
#: (2,882 rows in 19 days) and the scan is a single indexed-by-rowid read.
RECALL_SCAN_ROWS = 4000

#: A row shorter than this is an interjection ("Thank you.", "Corner"), not a
#: memory worth quoting back. Applied ONLY to the recency fallback: an explicit
#: keyword hit on a short row is still a hit, because the owner asked for it.
RECALL_MIN_CHARS = 12

#: First-person singular markers. In the RECENCY mode — the one that answers
#: "what do you remember about me" — a turn in which the owner talked about
#: themselves outranks a turn in which they gave an order.
#:
#: This is not a heuristic bolted on for taste; it is the question being answered
#: literally. Measured on the owner's own store: plain recency returns the five
#: most recent rows, which on 2026-08-20 are "find the fountain", "head towards
#: the lamppost", "run to the nearest lamppost" — true, dated, checkable, and not
#: about the owner at all. The self-referential rows in the same store are "I'm
#: hungry. Take me somewhere I can get food.", "Uh, I'm a little bored. Can you
#: just circle around me for a bit?", "Ugh, I'm tired. Let's go home." — which is
#: what someone asking "what do you remember about me" means.
#:
#: It is a PREFERENCE and not a filter: if there are fewer than ``limit``
#: self-referential turns, plain recent turns still fill the answer. Nothing is
#: hidden from the owner; the ordering just puts them second.
#:
#: ``me`` is deliberately NOT here. It is an object pronoun and the owner's own
#: store is full of it as an ORDER — "order me a pizza", "take me somewhere
#: nice", "wave at me and then go to the bench". Including it promoted three
#: commands into the answer to "what do you remember about me"; excluding it
#: leaves the turns where the owner is the SUBJECT, which is the question.
RECALL_SELF_MARKERS: frozenset[str] = frozenset(
    {"i", "i'd", "i'll", "i'm", "i've", "im", "mine", "my", "myself"}
)

#: Words that name WHEN rather than WHAT. A query made only of these is not a
#: search — "what did we talk about yesterday" (corpus query 31) has exactly one
#: content word and it is a date. Searching the ledger for the literal string
#: "yesterday" returns nothing, which is how that query failed before this card:
#: not a false answer, an empty one, for a day with 38 rows in it.
#:
#: The seven weekday names are in here for the same reason: "what did we do on
#: Sunday" names a DAY, and searching that day's rows for the literal string
#: "sunday" is the identical bug one word further along.
RECALL_TIME_WORDS: frozenset[str] = frozenset(
    {
        "afternoon", "ago", "before", "day", "days", "earlier", "evening",
        "friday", "just", "last", "lately", "later", "monday", "morning",
        "night", "now", "once", "past", "previously", "recently", "saturday",
        "since", "sunday", "thursday", "today", "tonight", "tuesday",
        "wednesday", "week", "weekend", "yesterday",
    }
)

#: The two day words this module will turn into a calendar day, as an offset
#: from ``now``. Weekday names are handled separately (:func:`recall_named_day`)
#: because they need a search backwards rather than a subtraction.
RECALL_DAY_OFFSETS: dict[str, int] = {"today": 0, "tonight": 0, "yesterday": 1}

_WORD = re.compile(r"[0-9a-z]+(?:'[a-z]+)?")


def recall_tokens(text: str) -> tuple[str, ...]:
    """Lowercase content words. Apostrophes kept so ``don't`` stays one token."""

    return tuple(
        token
        for token in _WORD.findall(str(text).lower())
        if token not in RECALL_STOPWORDS and len(token) > 1
    )


def recall_named_day(terms: Iterable[str], now: datetime) -> date | None:
    """Which calendar day, if any, this query is asking about.

    ``today``/``tonight``/``yesterday`` are offsets; a weekday name is the most
    recent day with that name, counting back up to a week and never landing on
    today (someone saying "on Tuesday" on a Tuesday means last Tuesday). Returns
    ``None`` when the query names no day, which is the overwhelmingly common
    case and the one that leaves the search unrestricted.
    """

    words = {str(term).lower() for term in terms}
    for word, offset in RECALL_DAY_OFFSETS.items():
        if word in words:
            return (now - timedelta(days=offset)).date()
    for back in range(1, 8):
        moment = now - timedelta(days=back)
        if moment.strftime("%A").lower() in words:
            return moment.date()
    return None


def provenance_phrase(when: datetime | None, now: datetime) -> str:
    """Card R18 — "from our chat on Tuesday…", and never a fabricated one.

    Returns ``""`` for a row with no usable timestamp, and the caller says the
    memory WITHOUT a date rather than guessing at one. A recalled fact with an
    invented instant is worse than a recalled fact with no instant: the owner
    can check the second kind.

    Both instants are compared as the calendar days they fall on, so "yesterday"
    means the previous calendar day and not "some time in the last 24 hours" —
    which is what a person means by it, and the only reading that stays true at
    ten past midnight.
    """

    if when is None:
        return ""
    days = (now.date() - when.date()).days
    if days < 0:
        # A row stamped in the future. Say nothing rather than "in 3 days".
        return ""
    if days == 0:
        return "earlier today"
    if days == 1:
        return "yesterday"
    if days < 7:
        return f"on {when.strftime('%A')}"
    return f"on {when.strftime('%-d %B')}"


@dataclass(frozen=True)
class RecalledTurn:
    """One remembered turn, with the provenance needed to say it out loud."""

    speaker: str
    text: str
    when: datetime | None
    when_phrase: str
    score: float

    def as_sentence(self) -> str:
        """The one line the model reads. Provenance first, then the words.

        Provenance leads because that is the half live_run_1 never had: the
        model was handed ``"owner: I'm hungry"`` and could only say the robot
        remembered *something*. "on Tuesday you said …" is a claim the owner can
        check, which is the whole difference between memory and assertion.
        """

        who = "you said" if self.speaker == "owner" else "I said"
        lead = f"{self.when_phrase} {who}" if self.when_phrase else who
        return f"{lead}: {self.text}"


class ConversationMemory:
    """Small local audit/conversation store; no raw audio is retained."""

    def __init__(
        self,
        path: str | Path = ":memory:",
        *,
        read_only: bool = False,
        purpose: str | None = None,
    ):
        """``read_only=True`` opens the file so that SQLite itself refuses writes.

        CARD R27 — THE PATH IS NO LONGER TAKEN ON TRUST
        -----------------------------------------------
        ``path`` used to go straight to ``sqlite3.connect``, which resolves a
        relative name against the **process CWD**. The shipped config's
        ``memory.path: parcel_memory.sqlite3`` therefore meant "the owner's real
        conversation memory" for every process started from the repo root —
        tests, harnesses and in-process runtimes included — and 256 synthetic
        rows are the measured cost. It is now resolved by
        :func:`~parcel_robot.memory_path.resolve_memory_path`, which refuses
        rather than guesses; see that module for the three rules and the reason
        each one is shaped the way it is.

        This constructor is the chokepoint deliberately. Putting the guard in
        ``runtime.py`` beside the config read would have protected the runtime
        and left ``ConversationMemory("parcel_memory.sqlite3")`` — one line in
        any test — wide open, which is precisely the class of hole this card
        exists to close.

        ``purpose`` lets a deliberate maintenance tool name itself (``"tool"``).
        It cannot promote a pytest process to the owner.

        CARD R18 — WHY ``read_only`` EXISTS, AND WHY R27 LEAVES IT ALONE
        ---------------------------------------------------------------
        R18's live proof has to read the OWNER's conversation database, and
        "never open it for writing" is a promise a script can break silently —
        this constructor creates a table and runs an ``ALTER TABLE`` migration
        on the way in. ``read_only=True`` makes the promise executable: the
        connection is opened ``mode=ro`` through SQLite's URI form, so a write
        raises ``sqlite3.OperationalError`` from the engine rather than
        depending on the caller's discipline, and the schema statements are
        skipped because they are writes.

        R27's refusals do not apply to that mode, and the reason is that it is
        the one mode in which the defect cannot happen. Two live consumers need
        it — R18's recall proof and
        ``tools/quarantine_synthetic_memory.py --dry-run`` — and routing them
        through a copy of the store would weaken the evidence without making
        the file any safer.

        Reads are unaffected: every query in this class is a ``SELECT``.
        """

        self._lock = threading.RLock()
        self.read_only = bool(read_only)
        #: Card R27. The resolved decision — which file, and what class of
        #: process is writing to it. Kept as an attribute so a caller (and the
        #: guard test) can ask a live store what it decided, instead of
        #: re-deriving it and hoping the two agree.
        self.store: ResolvedStore = resolve_memory_path(
            path, purpose=purpose, read_only=self.read_only
        )
        #: The ``messages.writer`` stamp for every row THIS connection writes.
        self.writer: str = self.store.writer
        #: Card R22, work item 4. Realtime ledger writes the sqlite engine
        #: refused, by exception type, and the most recent reason. Set before
        #: the connection is opened so a read-only store answers the health
        #: question too — a ``mode=ro`` connection is the one configuration in
        #: which every hosted write is GUARANTEED to fail, and the pump must
        #: survive that as calmly as it survives a full disk.
        self.realtime_write_failures = 0
        self.realtime_write_failure_types: dict[str, int] = {}
        self.last_realtime_write_error: str | None = None
        if self.read_only:
            self.connection = sqlite3.connect(
                f"file:{self.store.path}?mode=ro", uri=True, check_same_thread=False
            )
            return
        self.connection = sqlite3.connect(self.store.path, check_same_thread=False)
        with self._lock:
            self.connection.execute(
                "CREATE TABLE IF NOT EXISTS messages "
                "(id INTEGER PRIMARY KEY, role TEXT NOT NULL, content TEXT NOT NULL, "
                "created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)"
            )
            self._migrate_columns()

    def _migrate_columns(self) -> None:
        """Add the annotation columns to an EXISTING database, once.

        Guarded by ``PRAGMA table_info`` rather than a version counter: the live
        ``parcel_memory.sqlite3`` predates any schema versioning and contains
        only the ``messages`` table, so the table's own shape is the only honest
        source of truth about what has already been applied.
        """

        existing = {
            str(row[1]) for row in self.connection.execute("PRAGMA table_info(messages)").fetchall()
        }
        for column, sql_type in MIGRATED_COLUMNS:
            if column in existing:
                continue
            self.connection.execute(f"ALTER TABLE messages ADD COLUMN {column} {sql_type}")
        self.connection.commit()

    def add(self, role: str, content: str) -> None:
        """The LEGACY write path — the panel/voice one that wrote all 2,618.

        Card R27 work item 2: this now stamps ``writer``. It is the path that
        produced every polluted row (all 256 arrived through a runtime built on
        the shipped config), so leaving it unstamped while annotating only the
        Realtime lane would have instrumented the one writer that was never the
        problem.
        """

        if role not in {"user", "assistant", "tool"}:
            raise ValueError(f"unsupported memory role: {role}")
        with self._lock:
            self.connection.execute(
                "INSERT INTO messages(role, content, writer) VALUES (?, ?, ?)",
                (role, content, self.writer),
            )
            self.connection.commit()

    def recent(self, limit: int = 8) -> list[dict[str, str]]:
        with self._lock:
            rows = self.connection.execute(
                "SELECT role, content FROM messages ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
        return [{"role": role, "content": content} for role, content in reversed(rows)]

    def write_realtime_turn(
        self,
        *,
        session_id: str | None,
        speaker: str,
        text: str,
        origin: str,
        provider_item_id: str | None = None,
        store: ConversationStore | None = None,
    ) -> int:
        """Write ONE side of a hosted turn, annotated with its provenance.

        The Realtime lane's dedicated writer. FIX-A/F3's transcript fields cover
        only the owner side of a LOCAL voice turn and obey the duplex-logging
        kill switch; hosted replies never create those turns at all. This is the
        conversation ledger — the product's memory — and it is deliberately not
        behind the diagnostics switch.

        Returns the new row id so a caller can correlate without re-querying.

        ``store`` (card R2-D) is an optional
        :class:`~parcel_robot.conversation_store.ConversationStore` to dual-write
        the same turn into. **Default ``None`` means byte-identical behaviour**:
        no store, no extra statement, no extra commit. This is the wiring point
        rather than ``runtime.py`` because the raw-conversation store must be
        able to arrive without an audited call site moving.

        A store failure NEVER propagates. The ledger row is committed before the
        mirror is attempted, and losing a mirror costs a logged warning — the
        same never-kill-a-turn rule ``lane._write_ledger`` already applies to
        this method.

        CARD R22 — THE PRIMARY WRITE IS NOW FIREWALLED TOO
        --------------------------------------------------
        The paragraph above was half true and the missing half is
        AUDIT_FULL_FABLE §Safety-1. The *mirror* half caught ``Exception``
        (``conversation_store.mirror_realtime_turn``); the *primary* half — the
        ``INSERT`` and ``commit()`` below — caught nothing at all, and it runs
        on the realtime pump thread. ``sqlite3.Error`` subclasses ``Exception``
        and none of the types the two callers were catching, so a disk-full, a
        locked database, a read-only file or a corrupted page raised through
        every guard between here and the thread and killed the pump — taking
        the spoken e-stop relay, the stall watchdog, the rollover and the idle
        close with it, with the microphone still open.

        So the engine's own failures are now caught HERE, at the source:

        * ``ValueError`` for a bad speaker or empty text still raises. That is
          argument validation, it is deterministic, three callers depend on it,
          and a caller that passes garbage has a bug rather than a full disk.
        * ``sqlite3.Error`` — the whole family, by base class rather than by a
          list of subclasses, which is the entire lesson of the finding —
          degrades to a counted note and **returns row id 0**. The counters
          (:attr:`realtime_write_failures`, :attr:`realtime_write_failure_types`,
          :attr:`last_realtime_write_error`) are the record; ``0`` is the
          documented "no row was written", and no caller in the tree treats the
          return value as anything but an opaque correlation id.

        A caller that must know can read the counter or compare the row id to
        zero. A caller that must merely not die — which is every caller on the
        pump thread — now cannot.
        """

        role = _SPEAKER_ROLES.get(speaker)
        if role is None:
            raise ValueError(f"unsupported realtime speaker: {speaker!r}")
        if not isinstance(text, str) or not text.strip():
            raise ValueError("realtime turn text must be non-empty")
        try:
            with self._lock:
                cursor = self.connection.execute(
                    "INSERT INTO messages(role, content, session_id, speaker, origin, "
                    "provider_item_id, writer) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (
                        role,
                        text,
                        None if session_id is None else str(session_id),
                        speaker,
                        str(origin),
                        None if provider_item_id is None else str(provider_item_id),
                        self.writer,
                    ),
                )
                self.connection.commit()
                row_id = int(cursor.lastrowid or 0)
        except sqlite3.Error as error:
            # THE blindspot. Caught on the base class deliberately: the finding
            # was a type list that a real subclass fell through, and naming
            # subclasses here would rebuild it one layer down.
            name = type(error).__name__
            self.realtime_write_failures += 1
            self.realtime_write_failure_types[name] = (
                self.realtime_write_failure_types.get(name, 0) + 1
            )
            self.last_realtime_write_error = f"{name}: {error}"
            logger.warning(
                "realtime ledger write failed for speaker=%s origin=%s item=%s: %s: %s",
                speaker,
                origin,
                provider_item_id,
                name,
                error,
            )
            return 0
        # Outside the lock: the ledger row is durable, and a slow or wedged
        # store must not hold the writer that every hosted turn queues behind.
        if store is not None:
            mirror_realtime_turn(
                store,
                session_id=None if session_id is None else str(session_id),
                speaker=speaker,
                text=text,
                origin=str(origin),
                provider_item_id=None if provider_item_id is None else str(provider_item_id),
                ledger_row_id=row_id,
            )
        return row_id

    def realtime_turns(
        self,
        *,
        session_id: str | None = None,
        limit: int = 20,
    ) -> list[dict[str, object]]:
        """Oldest-first tail of hosted turns, for memory injection at reconnect.

        Only rows this writer produced (``speaker IS NOT NULL``) are returned,
        so a local typed turn can never be replayed to the provider as if the
        hosted agent had said it.
        """

        query = (
            "SELECT id, role, content, session_id, speaker, origin, provider_item_id "
            "FROM messages WHERE speaker IS NOT NULL"
        )
        params: list[object] = []
        if session_id is not None:
            query += " AND session_id = ?"
            params.append(session_id)
        query += " ORDER BY id DESC LIMIT ?"
        params.append(int(limit))
        with self._lock:
            rows = self.connection.execute(query, tuple(params)).fetchall()
        return [
            {
                "id": row[0],
                "role": row[1],
                "content": row[2],
                "session_id": row[3],
                "speaker": row[4],
                "origin": row[5],
                "provider_item_id": row[6],
            }
            for row in reversed(rows)
        ]

    # ------------------------------------------------------- card R18: recall
    def conversation_turns(self, *, limit: int = RECALL_SCAN_ROWS) -> list[dict[str, object]]:
        """Newest-first tail of EVERY conversational turn, whatever wrote it.

        The deliberate opposite of :meth:`realtime_turns`: no ``speaker IS NOT
        NULL`` filter, because that column only exists on rows written after
        card R1 and the owner's store is mostly older than that. ``speaker`` is
        recovered from ``role`` where the column is null (:data:`_ROLE_SPEAKERS`)
        and ``origin`` is reported as ``local`` for the same rows, which is what
        they are — the on-device voice/panel path is the only thing that ever
        called :meth:`add`.

        ``system`` rows are dropped here rather than by the caller: they are
        session bookkeeping in every origin, and a reader that has to remember
        to exclude them is a reader that will one day forget.
        """

        with self._lock:
            rows = self.connection.execute(
                "SELECT id, role, content, created_at, speaker, origin FROM messages "
                "ORDER BY id DESC LIMIT ?",
                (int(limit),),
            ).fetchall()
        turns: list[dict[str, object]] = []
        for row_id, role, content, created_at, speaker, origin in rows:
            who = str(speaker or _ROLE_SPEAKERS.get(str(role), "")).strip().lower()
            if who not in RECALL_SPEAKERS:
                continue
            text = " ".join(str(content or "").split())
            if not text:
                continue
            turns.append(
                {
                    "id": int(row_id),
                    "speaker": who,
                    "content": text,
                    "created_at": created_at,
                    "origin": str(origin) if origin else "local",
                }
            )
        return turns

    def recall(
        self,
        query: str,
        *,
        now: datetime,
        limit: int = RECALL_LIMIT,
        scan: int = RECALL_SCAN_ROWS,
    ) -> list[RecalledTurn]:
        """What this store actually remembers about ``query``, oldest-first.

        THREE MODES, and which one runs is decided by the query, not by a flag.
        Each of the three is one of the corpus questions this card has to answer:

        * **Keyword** — the query has topic words left after
          :data:`RECALL_STOPWORDS` and :data:`RECALL_TIME_WORDS`. Every turn is
          scored by how many DISTINCT query terms it carries, and both sides of
          the conversation are searched. ("What do you remember about the
          willow?", R19's live scene C.)
        * **A named day** — the only content word is a date word
          (:func:`recall_named_day`). The answer is that day's conversation,
          both sides, most substantial first. Searching for the literal string
          "yesterday" is what returned nothing for corpus query 31 while the
          day itself held 38 rows.
        * **The owner themselves** — no topic words and no day. "What do you
          remember about me" is not a search; it is a request for the things
          the owner has told the robot, so the robot's own sentences are not
          offered back and the turns where the owner is the SUBJECT
          (:data:`RECALL_SELF_MARKERS`) are preferred over the ones where they
          gave an order. (Corpus query 30, F4.)

        All three de-duplicate by normalized text, keeping the most recent
        instance — the owner's real store has "go to the lamppost" in it
        fourteen times, and reading it back fourteen times is not recall.

        ``now`` is INJECTED. This method dates every memory it returns, and a
        dating function that read the wall clock could not be tested; it is also
        how the runtime's one clock stays the runtime's one clock.
        """

        raw_terms = set(recall_tokens(query))
        day = recall_named_day(raw_terms, now)
        terms = raw_terms - RECALL_TIME_WORDS
        rows = self.conversation_turns(limit=scan)
        seen: set[str] = set()
        scored: list[tuple[float, int, dict[str, object]]] = []
        for position, row in enumerate(rows):
            text = str(row["content"])
            if day is not None:
                # A day was named. It BOUNDS every mode: "what did we talk
                # about yesterday" must not answer with something said today,
                # however well it matches.
                #
                # THE ORDER HERE IS LOAD-BEARING and cost one debugging round.
                # De-duplicating first lets the NEWEST copy of a repeated
                # sentence claim the text, and the day filter then throws that
                # copy away while the in-window copy stays suppressed as a
                # duplicate. Against the owner's real store — which contains
                # "go to the lamppost" fourteen times across three weeks — that
                # emptied whole days. The window is applied first; dedupe then
                # runs inside it.
                instant = _row_instant(row.get("created_at"))
                if instant is None or instant.date() != day:
                    continue
            key = text.lower()
            if key in seen:
                continue
            seen.add(key)
            if terms:
                present = set(_WORD.findall(text.lower()))
                hits = sum(1 for term in terms if term in present)
                if not hits:
                    continue
                score = float(hits)
            elif day is not None:
                if len(text) < RECALL_MIN_CHARS:
                    continue
                # Inside one named day both sides count, but the OWNER's turns
                # are what the day was about: the robot's half of the owner's
                # 2026-08-19 conversation is five near-identical sentences about
                # a deferred wave, and answering "what did we talk about
                # yesterday" with the robot quoting itself five times is a
                # transcript, not a memory.
                score = 2.0 if row["speaker"] == "owner" else 1.0
            else:
                if row["speaker"] != "owner" or len(text) < RECALL_MIN_CHARS:
                    continue
                spoken = set(_WORD.findall(text.lower()))
                score = 2.0 if spoken & RECALL_SELF_MARKERS else 1.0
            # ``position`` is the store's own newest-first order, so a smaller
            # position is more recent; it breaks score ties by recency without
            # needing a parsed timestamp, which not every row has.
            scored.append((score, -position, row))
        if terms and scored:
            # A PARTIAL MATCH IS ONLY OFFERED WHEN NOTHING MATCHED BETTER.
            # "New York" against the owner's store otherwise returns the row
            # "Emergency stop is latched, so I can't take NEW movement
            # commands…" alongside the two rows that are actually about New
            # York — one shared word dressed as a memory. When some row carries
            # every term the owner used, the ones carrying a fraction of them
            # are not offered at all.
            best = max(item[0] for item in scored)
            floor = best if best >= 2.0 else 1.0
            scored = [item for item in scored if item[0] >= floor]
        scored.sort(key=lambda item: (item[0], item[1]), reverse=True)
        out: list[RecalledTurn] = []
        for score, _recency, row in scored[: max(0, int(limit))]:
            when = _row_instant(row.get("created_at"))
            out.append(
                RecalledTurn(
                    speaker=str(row["speaker"]),
                    text=str(row["content"]),
                    when=when,
                    when_phrase=provenance_phrase(when, now),
                    score=score,
                )
            )
        # Oldest first: an answer that walks forwards through time reads as a
        # memory, and one that walks backwards reads as a database.
        out.sort(key=lambda item: (item.when is None, item.when or now))
        return out


def _row_instant(created_at: object) -> datetime | None:
    """``messages.created_at`` → a local-time ``datetime``, or ``None``.

    SQLite stamps ``CURRENT_TIMESTAMP`` in UTC with no suffix;
    :func:`~parcel_robot.conversation_store.parse_sqlite_utc` is the one place
    in this repo that knows it, so this reuses it rather than re-deciding.

    The result is converted to the MACHINE's local time on purpose: the words
    this feeds are "yesterday" and "on Tuesday", and those are claims about the
    owner's day, not about UTC's. A row written at 23:30 local on Monday is a
    Monday memory even though UTC had already rolled over. The conversion is
    the only ambient thing in this module and it is stated here rather than
    hidden — see R18_STATUS §8.
    """

    stamp = parse_sqlite_utc(created_at)
    if stamp is None:
        return None
    try:
        # Naive LOCAL time is the point here, not an oversight: the words this
        # feeds are "yesterday" and "on Tuesday" — claims about the owner's day.
        return datetime.fromtimestamp(stamp)  # noqa: DTZ006
    except (OSError, OverflowError, ValueError):
        return None
