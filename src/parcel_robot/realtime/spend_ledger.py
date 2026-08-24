"""Month-to-date hosted spend, on disk, so a ceiling can survive a restart.

Card R25 (``scrum/20260821/task_4``), from the full audit's §Ops-2:

    ``monthly_budget_usd`` is a documented control that does not exist: the
    arming gate never reads it. False documented safety = must fix or
    un-document.

The gate function :func:`~parcel_robot.realtime.lane.decide_realtime_arming`
had the comparison all along; what it never had was a NUMBER. Its ``spend_usd``
parameter defaulted to ``0.0`` and the only caller — ``RealtimeLane.arm`` — did
not pass one, so ``0.0 >= 25.0`` was the whole of the owner's monthly ceiling.
Feeding it ``realtime_spend_usd(lane.usage_rows)`` would have been worse than
nothing: that list is emptied by every process restart, so the ceiling would
have reset every time the robot rebooted, which is exactly the moment a runaway
loop restarts too.

WHAT THIS FILE IS
-----------------
One append-only JSON-lines file, one row per hosted response, beside the R17
recordings and the EV-1 evidence log:

    <capture root>/spend.jsonl

It is a SIBLING of the per-session folders rather than a file inside one,
because "this month" spans sessions by construction and a per-session artifact
can only ever answer "this session". It is deliberately NOT in ``evals/`` (the
resolver refuses that tree outright) and deliberately not a table in the
conversation sqlite: a cost write must never be able to take a lock the turn
needs, which is the same reasoning that put ``lane._append_cost_row`` in a
JSONL in the first place.

    {"schema":"parcel.realtime_spend.v1","wall":"2026-08-21T09:14:02Z",
     "month":"2026-08","session_id":"rt_ab12cd34ef56","response_id":"resp_7",
     "input_tokens":812,"cached_tokens":640,"output_tokens":96,
     "estimated_usd":0.002432,"rates_are_assumed":true}

``rates_are_assumed`` is carried on EVERY row, not stated once in a header,
because a reader that greps one line must not be able to mistake this for an
invoice. The rates are :mod:`parcel_robot.realtime.cost`'s assumed constants;
they are not fetched and they are not billed figures.

FAIL-**OPEN**, ON PURPOSE, AND STATED OUT LOUD
----------------------------------------------
Every other loader in this package fails CLOSED, and this one deliberately does
not. The repo's doctrine (``realtime/config.py``) is about the CONFIG — a typo'd
budget that reads as "unlimited" must refuse — and it still holds: an unreadable
``realtime.yaml`` refuses to arm. This file is different in kind. It is a
*measurement*, and the failure mode of fail-closed measurement is a robot that
will not open its mouth because a disk went read-only.

So: if the ledger cannot be read, :meth:`SpendLedger.month_to_date` returns
``readable=False`` with ``usd=0.0``, the arming gate does NOT refuse, and the
decision carries a WARNING that reaches ``/api/state`` and the panel. A broken
spend file must not brick the robot; it must be loud. That choice is pinned by
``tests/test_realtime_spend_budget.py`` in both directions — the unreadable
ledger arms, and the *readable* over-budget ledger refuses — so a future edit
that "hardens" this into a fail-closed gate turns a test red rather than
silently grounding the dog.

The three degradations are graded, not lumped together:

* **absent file** — ``readable=True``, ``usd=0.0``, no note. A ledger that has
  never been written is not a broken ledger; it is a robot that has not spoken
  yet. Treating it as unreadable would put a warning on every fresh install.
* **corrupt lines** — skipped and COUNTED (``skipped_rows``), ``readable``
  stays True, and the note names the count. The total is understated and the
  note says so; that is fail-open too, and it is the same direction as the
  unreadable case rather than a second, contradictory policy.
* **unreadable file** — ``readable=False`` and a note naming the OSError.

WHAT A RESTART FORGETS (the honest statement the card asks for)
--------------------------------------------------------------
Nothing this file wrote. Everything it did not. Rows are appended on
``response.done``, so a response that was billed by the provider and whose
``response.done`` never arrived (a socket death mid-response) is money spent
that this ledger does not know about. The ledger is therefore a LOWER BOUND on
month-to-date spend, and the ceiling it feeds is a lower-bound ceiling. Also:
rows are written by whichever process observed them, so a month spent across
two machines with two capture roots is two ledgers and two ceilings.
"""

from __future__ import annotations

import json
import math
import os
import threading
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from parcel_robot.realtime.cost import (
    RateCard,
    rate_card_for,
    realtime_spend_usd,
)

#: File name inside the capture/evidence root. A sibling of the per-session
#: folders, never a file inside one: "this month" spans sessions.
SPEND_LEDGER_NAME = "spend.jsonl"

#: Schema id on every row. Versioned for the same reason the evidence log's is:
#: a silently-changed shape is a silently-wrong ceiling.
#:
#: v1 rows are priced at :mod:`parcel_robot.realtime.cost`'s ASSUMED rates and
#: carry no audio/text split. v2 rows are priced from a :class:`RateCard` and
#: carry the six token counts the price was computed from. Both are summed by
#: :meth:`SpendLedger.month_to_date` — the reader keys on ``estimated_usd`` and
#: has never keyed on the schema string, so a ledger holding both is one total.
SPEND_LEDGER_SCHEMA = "parcel.realtime_spend.v1"
SPEND_LEDGER_SCHEMA_V2 = "parcel.realtime_spend.v2"

#: Opt-in, and OFF unless set: the model id whose :class:`RateCard` prices new
#: rows. A ledger constructed with no ``rate_card`` and no such variable writes
#: exactly the v1 rows it wrote yesterday. This exists so the owner's live stack
#: can be moved onto split pricing without an edit to ``runtime.py``.
RATE_CARD_ENV = "PARCEL_REALTIME_RATE_CARD"

#: How long a computed month-to-date total may be reused before the file is
#: re-read. Arming happens once per session and would not need a cache; the
#: NARRATION gate consults the same number and runs on control loops, so the
#: bound that matters is "never touch the disk per narration". Writes update
#: the cached total in place, so within one process the number is exact
#: between re-reads rather than merely fresh.
DEFAULT_CACHE_TTL_S = 5.0

#: A single row's JSON must not be able to eat memory if the file is not what
#: we think it is (a binary blob with no newlines, say). Rows this file writes
#: are ~200 bytes.
MAX_ROW_BYTES = 64 * 1024


def month_key(when: datetime | None = None) -> str:
    """``"YYYY-MM"`` in UTC. The period the ceiling is measured over.

    UTC and not local time, deliberately: the ledger is compared against rows
    written by whatever process was running, and a DST-shifting local month
    boundary would make "this month" ambiguous for an hour twice a year. The
    refusal message names the period so the owner never has to infer it.
    """

    moment = when or datetime.now(timezone.utc)
    if moment.tzinfo is None:  # pragma: no cover - defensive
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc).strftime("%Y-%m")


@dataclass(frozen=True)
class MonthToDateSpend:
    """What the ledger knows about this month. Never a bill.

    ``readable`` is the whole fail-open contract in one field: False means the
    number below is a floor of zero produced by a broken file, NOT a measured
    zero, and the arming gate must let the session open anyway.
    """

    month: str
    usd: float
    rows: int
    readable: bool = True
    note: str = ""
    skipped_rows: int = 0
    #: Always True. Present on the object for the same reason it is on every
    #: row: a reader must not have to remember that these are assumed rates.
    rates_are_assumed: bool = True
    path: str = ""

    @property
    def measured(self) -> bool:
        """True when this total came from a file we could actually read."""

        return self.readable

    def remaining(self, budget_usd: float) -> float:
        """Dollars left before the ceiling. Negative once it is past."""

        return float(budget_usd) - self.usd

    def fraction_of(self, budget_usd: float) -> float | None:
        """How close to the ceiling, 0.0-1.0+. ``None`` when there is no ceiling."""

        budget = float(budget_usd)
        if not budget > 0.0:
            return None
        return self.usd / budget

    def as_dict(self) -> dict[str, object]:
        return {
            "month": self.month,
            "usd": round(self.usd, 6),
            "rows": self.rows,
            "readable": self.readable,
            "note": self.note,
            "skipped_rows": self.skipped_rows,
            "rates_are_assumed": self.rates_are_assumed,
            "path": self.path,
        }


def spend_row(
    row: Mapping[str, object],
    *,
    session_id: str | None = None,
    when: datetime | None = None,
    rate_card: RateCard | None = None,
) -> dict[str, object]:
    """One lane usage row, priced, shaped for the ledger. Pure; no I/O.

    Split out from :meth:`SpendLedger.record` so the arithmetic and the schema
    can be asserted without a filesystem, and so the same shape can be produced
    by anything that later needs to backfill.

    With no ``rate_card`` this is byte-for-byte the v1 row it has always been.
    With one, the row is priced from the published per-modality rates, gains the
    six token counts the price stands on, and says ``rates_are_assumed: false``
    — which is only true when the row actually carried a split. A row without
    one (the three-key shape) keeps the ASSUMED path and says so, rate card or
    not: the card cannot invent an audio/text division that was never reported.
    """

    moment = when or datetime.now(timezone.utc)
    if moment.tzinfo is None:  # pragma: no cover - defensive
        moment = moment.replace(tzinfo=timezone.utc)
    moment = moment.astimezone(timezone.utc)
    entry: dict[str, object] = {
        "schema": SPEND_LEDGER_SCHEMA,
        "wall": moment.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "month": month_key(moment),
        "session_id": str(session_id or row.get("session_id") or ""),
        "response_id": str(row.get("response_id") or ""),
        "input_tokens": _whole(row, "input_tokens"),
        "cached_tokens": _whole(row, "cached_tokens"),
        "output_tokens": _whole(row, "output_tokens"),
        "estimated_usd": round(realtime_spend_usd([row]), 9),
        # On EVERY row. See the module docstring: a grep of one line must not
        # be mistakable for an invoice.
        "rates_are_assumed": True,
    }
    if rate_card is None:
        return entry
    price = rate_card.price(row)
    entry["schema"] = SPEND_LEDGER_SCHEMA_V2
    entry["estimated_usd"] = round(price.usd, 9)
    entry["rates_are_assumed"] = price.rates_are_assumed
    entry["pricing_basis"] = price.basis
    entry["rate_card_model"] = price.model
    entry["rate_card_as_of"] = price.as_of
    entry["split_tokens"] = dict(price.tokens or {})
    return entry


def _whole(row: Mapping[str, object], key: str) -> int:
    value = row.get(key, 0)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return 0
    return max(0, int(value))


@dataclass
class _Cache:
    month: str = ""
    total: MonthToDateSpend | None = None
    at_monotonic: float = 0.0
    #: Notes already announced, so a read-only disk warns once rather than
    #: twenty times a minute.
    announced: set[str] = field(default_factory=set)


class SpendLedger:
    """Append-only month-to-date spend. Never raises at either entry point.

    Both public methods are total: :meth:`record` returns a bool and
    :meth:`month_to_date` always returns a :class:`MonthToDateSpend`. The lane
    calls ``record`` from the pump thread (card R22's whole subject was an
    exception on that thread killing the crank) and ``month_to_date`` from the
    panel thread and the narration path, so "never raises" is a hard
    requirement rather than defensive style.
    """

    def __init__(
        self,
        path: Path | str,
        *,
        on_note: Callable[[str], None] | None = None,
        monotonic: Callable[[], float] = time.monotonic,
        now: Callable[[], datetime] | None = None,
        cache_ttl_s: float = DEFAULT_CACHE_TTL_S,
        rate_card: RateCard | None = None,
    ) -> None:
        self.path = Path(path)
        #: OFF unless asked for. ``None`` keeps the v1 ASSUMED pricing this
        #: ledger has always written; a card switches new rows to v2 split
        #: pricing. Resolved once, at construction, so a mid-month environment
        #: change cannot make two halves of one file disagree silently.
        self.rate_card = rate_card if rate_card is not None else _rate_card_from_env()
        self._on_note = on_note
        self._monotonic = monotonic
        self._now = now or (lambda: datetime.now(timezone.utc))
        self._cache_ttl_s = max(0.0, float(cache_ttl_s))
        self._lock = threading.Lock()
        self._cache = _Cache()
        #: Rows this process appended, and the appends that failed. Both are in
        #: the snapshot: a ledger that is silently not being written is the
        #: failure mode that would make the ceiling drift back to fiction.
        self.rows_written = 0
        self.write_failures = 0
        self.last_write_failure: str | None = None
        #: Warnings this object tried to announce and whose sink threw. Counted
        #: rather than swallowed silently: the warning IS the fail-open
        #: mitigation, so a sink that eats them is itself a fact worth having.
        self.notes_dropped = 0

    # --------------------------------------------------------------- writing
    def record(
        self,
        row: Mapping[str, object],
        *,
        session_id: str | None = None,
    ) -> bool:
        """Append one priced usage row. Returns False instead of raising.

        The in-process cached total is updated in the same lock, so a session
        that spends past the ceiling is refused on its NEXT arming even if the
        file is re-read only every :data:`DEFAULT_CACHE_TTL_S` seconds.
        """

        try:
            entry = spend_row(
                row,
                session_id=session_id,
                when=self._now(),
                rate_card=self.rate_card,
            )
            text = json.dumps(entry, sort_keys=True) + "\n"
        except Exception as error:  # noqa: BLE001 - a cost row may never end a turn
            self._fail_write(error)
            return False
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(text)
        except Exception as error:  # noqa: BLE001 - disk boundary, incl. OSError
            self._fail_write(error)
            return False
        with self._lock:
            self.rows_written += 1
            cached = self._cache.total
            if cached is not None and cached.month == entry["month"] and cached.readable:
                self._cache.total = MonthToDateSpend(
                    month=cached.month,
                    usd=cached.usd + float(entry["estimated_usd"]),
                    rows=cached.rows + 1,
                    readable=True,
                    note=cached.note,
                    skipped_rows=cached.skipped_rows,
                    rates_are_assumed=(
                        cached.rates_are_assumed or entry["rates_are_assumed"] is not False
                    ),
                    path=cached.path,
                )
        return True

    def _fail_write(self, error: BaseException) -> None:
        with self._lock:
            self.write_failures += 1
            self.last_write_failure = f"{type(error).__name__}: {error}"
        self._announce(
            f"realtime spend row not written to {self.path} "
            f"({type(error).__name__}: {error}); this month's ceiling is now "
            "an UNDERCOUNT until the next successful write"
        )

    # --------------------------------------------------------------- reading
    def month_to_date(self, *, month: str | None = None, force: bool = False) -> MonthToDateSpend:
        """Estimated spend for the current UTC month. Total; never raises."""

        wanted = month or month_key(self._now())
        with self._lock:
            cached = self._cache.total
            fresh = (
                cached is not None
                and cached.month == wanted
                and (self._monotonic() - self._cache.at_monotonic) < self._cache_ttl_s
            )
            if fresh and not force and cached is not None:
                return cached
        total = self._read_month(wanted)
        with self._lock:
            self._cache.month = wanted
            self._cache.total = total
            self._cache.at_monotonic = self._monotonic()
        if total.note:
            self._announce(total.note)
        return total

    def _read_month(self, wanted: str) -> MonthToDateSpend:
        path_text = str(self.path)
        try:
            exists = self.path.exists()
        except OSError as error:
            return MonthToDateSpend(
                month=wanted,
                usd=0.0,
                rows=0,
                readable=False,
                note=(
                    f"realtime spend ledger at {path_text} could not be stat'd "
                    f"({type(error).__name__}: {error}); the monthly ceiling is "
                    "NOT being enforced this session (fail-open)"
                ),
                path=path_text,
            )
        if not exists:
            # A ledger that has never been written is not a broken one.
            return MonthToDateSpend(month=wanted, usd=0.0, rows=0, readable=True, path=path_text)
        total = 0.0
        rows = 0
        skipped = 0
        #: A month is "assumed" if ANY row in it was. Mixed months are the
        #: normal case while a ledger is migrating, and calling such a month
        #: measured would launder the assumed half of it.
        assumed_rows = 0
        try:
            with self.path.open("r", encoding="utf-8") as handle:
                for line in handle:
                    if len(line) > MAX_ROW_BYTES:
                        skipped += 1
                        continue
                    stripped = line.strip()
                    if not stripped:
                        continue
                    try:
                        entry = json.loads(stripped)
                    except ValueError:
                        skipped += 1
                        continue
                    if not isinstance(entry, dict):
                        skipped += 1
                        continue
                    row_month = entry.get("month")
                    if not isinstance(row_month, str) or not row_month:
                        wall = entry.get("wall")
                        row_month = wall[:7] if isinstance(wall, str) and len(wall) >= 7 else ""
                    if row_month != wanted:
                        if not row_month:
                            skipped += 1
                        continue
                    usd = entry.get("estimated_usd")
                    if isinstance(usd, bool) or not isinstance(usd, (int, float)):
                        skipped += 1
                        continue
                    value = float(usd)
                    # NaN and +/-inf: a row that says "infinity dollars" is a
                    # corrupt row, not a ceiling breach, and must not be able to
                    # ground the robot by poisoning the sum.
                    if not math.isfinite(value):
                        skipped += 1
                        continue
                    total += max(0.0, value)
                    rows += 1
                    if entry.get("rates_are_assumed") is not False:
                        assumed_rows += 1
        except Exception as error:  # noqa: BLE001 - OSError, UnicodeDecodeError, ...
            return MonthToDateSpend(
                month=wanted,
                usd=0.0,
                rows=0,
                readable=False,
                note=(
                    f"realtime spend ledger at {path_text} is unreadable "
                    f"({type(error).__name__}: {error}); the monthly ceiling is "
                    "NOT being enforced this session (fail-open — a broken spend "
                    "file must never ground the robot). Fix or delete the file to "
                    "restore the ceiling."
                ),
                path=path_text,
            )
        note = ""
        if skipped:
            note = (
                f"realtime spend ledger at {path_text} has {skipped} unreadable "
                f"row(s); this month's total is an UNDERCOUNT of the true spend"
            )
        return MonthToDateSpend(
            month=wanted,
            usd=total,
            rows=rows,
            readable=True,
            note=note,
            skipped_rows=skipped,
            rates_are_assumed=bool(assumed_rows) or rows == 0,
            path=path_text,
        )

    # -------------------------------------------------------------- plumbing
    def _announce(self, message: str) -> None:
        if self._on_note is None:
            return
        with self._lock:
            if message in self._cache.announced:
                return
            self._cache.announced.add(message)
        try:
            self._on_note(message)
        except Exception:  # noqa: BLE001 - a warning may never break a turn
            self.notes_dropped += 1

    def snapshot(self, *, budget_usd: float | None = None) -> dict[str, object]:
        """What ``/api/state`` says about the ledger itself."""

        total = self.month_to_date()
        data: dict[str, object] = {
            **total.as_dict(),
            "rows_written": self.rows_written,
            "write_failures": self.write_failures,
            "last_write_failure": self.last_write_failure,
        }
        if budget_usd is not None:
            data["budget_usd"] = float(budget_usd)
            data["remaining_usd"] = round(total.remaining(budget_usd), 6)
            fraction = total.fraction_of(budget_usd)
            data["fraction_of_budget"] = None if fraction is None else round(fraction, 4)
            data["over_budget"] = bool(total.readable and total.usd >= float(budget_usd))
        return data


def _rate_card_from_env() -> RateCard | None:
    """The opt-in switch. Unset or unknown means the legacy ASSUMED path.

    An UNKNOWN model id deliberately returns ``None`` rather than falling back
    to the dearer card: this variable is how an operator asks for split pricing,
    and silently pricing a typo'd model at full-model rates would look like the
    request worked while inflating the ceiling by 5x.
    """

    return rate_card_for(os.environ.get(RATE_CARD_ENV))


def resolve_spend_ledger_path(root: Path | str) -> Path:
    """``<capture root>/spend.jsonl``. The root is resolved by the caller.

    Kept as a function rather than inlined so that "where does the spend ledger
    live" has exactly one answer that a test can import, and so a status doc can
    quote a path that the code actually computes.
    """

    return Path(os.path.normpath(str(Path(root) / SPEND_LEDGER_NAME)))


__all__ = [
    "DEFAULT_CACHE_TTL_S",
    "MAX_ROW_BYTES",
    "RATE_CARD_ENV",
    "SPEND_LEDGER_NAME",
    "SPEND_LEDGER_SCHEMA",
    "SPEND_LEDGER_SCHEMA_V2",
    "MonthToDateSpend",
    "SpendLedger",
    "month_key",
    "resolve_spend_ledger_path",
    "spend_row",
]
