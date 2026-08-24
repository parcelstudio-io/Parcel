"""The product's hard cap on hosted spend — card A7 (``scrum/20260824/task_2``).

WHY A SECOND CEILING EXISTS AT ALL
----------------------------------
``realtime.monthly_budget_usd`` already refuses to ARM a session past a figure
(card R25, :func:`parcel_robot.realtime.lane.decide_realtime_arming`). That is a
per-lane knob with a $25 default, and EVENT-BUDGET
(``research/20260824/event-driven-companion-budget/VERDICT.md``) says plainly
what it is not:

    The present ledger and rate card are not yet a trustworthy hard ceiling.
    [...] The product therefore needs one fail-closed ``HostedCallGovernor`` in
    front of every provider lane.

The measured reason is the spread, not the price. On the frozen workload the
same product costs **$30.72/month p95** nominal, **$572.36/month** with an
ungated ear in a room with a television, and **$777.60/month** deterministic if
anything ever puts a hosted model on a 1 Hz tick. The governor is what makes the
difference between those numbers a refusal instead of an invoice.

THE ENVELOPE, AND WHY IT IS $160 AND NOT $200
---------------------------------------------
``PORTABLE_LIVING_DOG_HLD.md`` §10: a **$160 application envelope plus a $40
uncertainty/billing reserve** inside the owner's $200 ceiling, and "no lane
borrows from the reserve automatically". So the number this object refuses at is
the ENVELOPE. The reserve is headroom for the gap between an estimate and an
invoice — this repo's ledger is a documented LOWER bound (a response whose
``response.done`` never arrived is money it never saw) — and a governor that
spent the reserve would be a governor that had already been wrong once.

WHAT IT DOES NOT GOVERN, AND WHY THAT IS STRUCTURAL
---------------------------------------------------
Nothing on a safety path passes through here. The spoken STOP is local by card
A6 (``parcel_robot.audio.stop_hotword``), the panel STOP, the operator remote,
``core/hard_stop.py`` and every watchdog are local by construction, and none of
them imports this module — which is asserted by test rather than promised in
prose (``tests/test_a7_ear_governor.py``). :data:`CLASS_CRITICAL` exists as the
belt to that braces: a critical call is admitted *before the ledger is read at
all*, the same shape as ``voice_identity.gate_decision`` answering the emergency
class before it looks at a verdict. A budget that can silence a stop is not a
budget; it is a hazard with an accountant.

FAIL DIRECTION, STATED OUT LOUD
-------------------------------
:mod:`parcel_robot.realtime.spend_ledger` fails **open** on purpose — a
read-only disk must not ground the robot — and this module does not change that
gate. This one is different in kind, and takes the HLD's direction instead:
"refuses new nonessential calls if ledger/rate/billing state is unknown". The
consequence of refusing here is not a grounded robot; it is a robot that stays
LOCAL, which is the architecture's own degradation policy (HLD principle 1).
``refuse_when_unknown: false`` restores the older direction for an operator who
would rather keep talking than keep counting.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone

#: The application envelope, USD/month. HLD §10. This is the figure a routine
#: hosted call is refused at — not the owner's $200 ceiling.
DEFAULT_ENVELOPE_USD = 160.0

#: Uncertainty/billing reserve between the envelope and the owner's ceiling.
#: Carried so the snapshot can say what the headroom is; never automatically
#: spent (HLD §10: "no lane borrows from the reserve automatically").
DEFAULT_RESERVE_USD = 40.0

#: Where the HLD asks for a warning rather than a refusal.
DEFAULT_WARN_USD = 150.0

#: Call classes. ``critical`` is answered before any ledger is read.
CLASS_CRITICAL = "critical"
CLASS_ROUTINE = "routine"
CALL_CLASSES: tuple[str, ...] = (CLASS_CRITICAL, CLASS_ROUTINE)

#: Decision codes. Anything not ``admitted``/``never_governed`` is a refusal.
CODE_ADMITTED = "admitted"
CODE_NEVER_GOVERNED = "never_governed"
CODE_DISABLED = "governor_disabled"
CODE_ENVELOPE_REACHED = "envelope_reached"
CODE_DAY_CAP_REACHED = "day_cap_reached"
CODE_LEDGER_UNKNOWN = "ledger_unknown"

DECISION_CODES: frozenset[str] = frozenset(
    {
        CODE_ADMITTED,
        CODE_NEVER_GOVERNED,
        CODE_DISABLED,
        CODE_ENVELOPE_REACHED,
        CODE_DAY_CAP_REACHED,
        CODE_LEDGER_UNKNOWN,
    }
)

#: The whole schema of the ``audio.ear.governor:`` block. A typo is a refusal,
#: by name, at the read site — the ``roam`` / ``stop_hotword`` pattern.
GOVERNOR_CONFIG_KEYS = frozenset(
    {
        "enabled",
        "envelope_usd",
        "reserve_usd",
        "warn_usd",
        "daily_cap_usd",
        "refuse_when_unknown",
    }
)


class HostedCallRefused(RuntimeError):
    """The typed refusal. Carries the decision that produced it.

    Typed because a caller has to be able to tell "the budget said no" from
    "the socket died": the first degrades to a local behaviour and the second
    is an incident.
    """

    def __init__(self, decision: GovernorDecision) -> None:
        super().__init__(decision.reason)
        self.decision = decision
        self.code = decision.code
        self.reason = decision.reason


@dataclass(frozen=True)
class GovernorConfig:
    """The envelope, as an operator may write it. Defaults are the measured ones."""

    enabled: bool = True
    envelope_usd: float = DEFAULT_ENVELOPE_USD
    reserve_usd: float = DEFAULT_RESERVE_USD
    warn_usd: float = DEFAULT_WARN_USD
    #: 0.0 = OFF. There is no measured daily bar — EVENT-BUDGET's numbers are
    #: monthly — so the default tracks the day's burn and reports it without
    #: refusing on it. An operator who wants pacing writes a number.
    daily_cap_usd: float = 0.0
    #: HLD §10's direction. See the module docstring's fail-direction note.
    refuse_when_unknown: bool = True

    @property
    def ceiling_usd(self) -> float:
        """Envelope + reserve — the owner's ceiling, never the refusal line."""

        return self.envelope_usd + self.reserve_usd

    @classmethod
    def from_mapping(cls, section: object) -> GovernorConfig:
        """Validate the ``governor:`` sub-block. Unknown key ⇒ refusal by name."""

        if section is None:
            return cls()
        if not isinstance(section, Mapping):
            raise TypeError(
                f"the governor config section must be a mapping, got {type(section).__name__}"
            )
        unknown = sorted(str(key) for key in section if str(key) not in GOVERNOR_CONFIG_KEYS)
        if unknown:
            raise ValueError(
                f"unknown governor config key(s): {', '.join(unknown)}; "
                f"allowed: {', '.join(sorted(GOVERNOR_CONFIG_KEYS))}"
            )
        envelope = _money(section, "envelope_usd", DEFAULT_ENVELOPE_USD)
        reserve = _money(section, "reserve_usd", DEFAULT_RESERVE_USD)
        warn = _money(section, "warn_usd", min(DEFAULT_WARN_USD, envelope))
        return cls(
            enabled=_flag(section, "enabled", True),
            envelope_usd=envelope,
            reserve_usd=reserve,
            warn_usd=warn,
            daily_cap_usd=_money(section, "daily_cap_usd", 0.0),
            refuse_when_unknown=_flag(section, "refuse_when_unknown", True),
        )

    def as_dict(self) -> dict[str, object]:
        return {
            "enabled": self.enabled,
            "envelope_usd": self.envelope_usd,
            "reserve_usd": self.reserve_usd,
            "warn_usd": self.warn_usd,
            "daily_cap_usd": self.daily_cap_usd,
            "refuse_when_unknown": self.refuse_when_unknown,
            "ceiling_usd": self.ceiling_usd,
        }


@dataclass(frozen=True)
class GovernorDecision:
    """One admission answer, with the numbers it stands on."""

    admitted: bool
    code: str
    reason: str
    purpose: str = ""
    call_class: str = CLASS_ROUTINE
    month: str = ""
    month_usd: float = 0.0
    envelope_usd: float = 0.0
    day: str = ""
    day_usd: float = 0.0
    warning: str = ""

    def as_dict(self) -> dict[str, object]:
        return {
            "admitted": self.admitted,
            "code": self.code,
            "reason": self.reason,
            "purpose": self.purpose,
            "call_class": self.call_class,
            "month": self.month,
            "month_usd": round(self.month_usd, 6),
            "envelope_usd": self.envelope_usd,
            "day": self.day,
            "day_usd": round(self.day_usd, 6),
            "warning": self.warning,
        }


class HostedCallGovernor:
    """One entry point in front of every hosted call the product may open.

    It owns no socket and no ledger: it is handed two readers (this month's
    durable total and today's) and a config, and it answers one question. That
    keeps it testable with a seeded-red total and keeps the ledger's own
    never-raises contract where it already is.
    """

    def __init__(
        self,
        *,
        config: GovernorConfig | None = None,
        month_to_date: Callable[[], object] | None = None,
        day_to_date: Callable[[], object] | None = None,
        on_event: Callable[[str], None] | None = None,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self.config = config or GovernorConfig()
        self._month_to_date = month_to_date
        self._day_to_date = day_to_date
        self._on_event = on_event
        self._now = now or (lambda: datetime.now(timezone.utc))
        self.admitted = 0
        self.refused = 0
        self.read_failures = 0
        self.last_decision: GovernorDecision | None = None
        #: Warnings whose sink threw. Counted rather than swallowed, for the
        #: spend ledger's reason: the warning IS the mitigation, so a sink that
        #: eats them is itself a fact worth having.
        self.notes_dropped = 0
        #: Messages already announced, deduplicated by TEXT. An owner pressing a
        #: refused button five times is one refusal to say out loud, not five —
        #: the same choice ``SpendLedger`` makes about a read-only disk.
        self._announced: set[str] = set()

    # ------------------------------------------------------------ the answer
    def admit(self, purpose: str, *, call_class: str = CLASS_ROUTINE) -> GovernorDecision:
        """May this hosted call happen? Never raises; see :meth:`require`."""

        name = str(purpose or "hosted call")
        klass = str(call_class)
        if klass == CLASS_CRITICAL:
            # BEFORE any ledger read, deliberately: nothing about money may
            # delay or fail a critical path. Safety does not even reach here
            # (it is local by A6/A2); this is the belt to that braces.
            return self._settle(
                GovernorDecision(
                    admitted=True,
                    code=CODE_NEVER_GOVERNED,
                    reason=f"{name} is a critical call and is never governed by a budget.",
                    purpose=name,
                    call_class=klass,
                )
            )
        if not self.config.enabled:
            return self._settle(
                GovernorDecision(
                    admitted=True,
                    code=CODE_DISABLED,
                    reason=f"{name} admitted: the hosted-call governor is disabled.",
                    purpose=name,
                    call_class=klass,
                )
            )
        month, month_usd, readable = self._read_month()
        day, day_usd = self._read_day()
        if not readable:
            return self._settle(self._unknown(name, klass, month, day))
        envelope = self.config.envelope_usd
        if month_usd >= envelope:
            return self._settle(
                GovernorDecision(
                    admitted=False,
                    code=CODE_ENVELOPE_REACHED,
                    reason=(
                        f"{name} refused: an estimated ${month_usd:.2f} of hosted spend "
                        f"in {month or 'this month'} has reached the ${envelope:.2f} "
                        f"application envelope (a ${self.config.reserve_usd:.2f} reserve "
                        "is held back and is never spent automatically). Local "
                        "behaviour, STOP and the safety floors are unaffected."
                    ),
                    purpose=name,
                    call_class=klass,
                    month=month,
                    month_usd=month_usd,
                    envelope_usd=envelope,
                    day=day,
                    day_usd=day_usd,
                )
            )
        cap = self.config.daily_cap_usd
        if cap > 0.0 and day_usd >= cap:
            return self._settle(
                GovernorDecision(
                    admitted=False,
                    code=CODE_DAY_CAP_REACHED,
                    reason=(
                        f"{name} refused: an estimated ${day_usd:.2f} spent on {day} has "
                        f"reached the ${cap:.2f} daily pacing cap. The month's envelope "
                        f"(${month_usd:.2f} of ${envelope:.2f}) is not exhausted; this is "
                        "pacing, and it lifts at the next UTC day."
                    ),
                    purpose=name,
                    call_class=klass,
                    month=month,
                    month_usd=month_usd,
                    envelope_usd=envelope,
                    day=day,
                    day_usd=day_usd,
                )
            )
        return self._settle(
            GovernorDecision(
                admitted=True,
                code=CODE_ADMITTED,
                reason=(
                    f"{name} admitted: ${month_usd:.2f} of the ${envelope:.2f} envelope "
                    f"is spent in {month or 'this month'}."
                ),
                purpose=name,
                call_class=klass,
                month=month,
                month_usd=month_usd,
                envelope_usd=envelope,
                day=day,
                day_usd=day_usd,
                warning=self._warning_for(month_usd, month),
            )
        )

    def require(self, purpose: str, *, call_class: str = CLASS_ROUTINE) -> GovernorDecision:
        """:meth:`admit`, raising :class:`HostedCallRefused` on a refusal."""

        decision = self.admit(purpose, call_class=call_class)
        if not decision.admitted:
            raise HostedCallRefused(decision)
        return decision

    # ------------------------------------------------------------- plumbing
    def _unknown(self, name: str, klass: str, month: str, day: str) -> GovernorDecision:
        refuse = self.config.refuse_when_unknown
        return GovernorDecision(
            admitted=not refuse,
            code=CODE_LEDGER_UNKNOWN,
            reason=(
                f"{name} refused: this month's hosted spend cannot be read, so the "
                f"${self.config.envelope_usd:.2f} envelope cannot be enforced. The dog "
                "stays local until the ledger is readable again (set "
                "governor.refuse_when_unknown: false to keep talking instead)."
                if refuse
                else (
                    f"{name} admitted with the envelope NOT enforced: this month's "
                    "hosted spend could not be read."
                )
            ),
            purpose=name,
            call_class=klass,
            month=month,
            envelope_usd=self.config.envelope_usd,
            day=day,
        )

    def _warning_for(self, month_usd: float, month: str) -> str:
        warn = self.config.warn_usd
        if warn <= 0.0 or month_usd < warn:
            return ""
        return (
            f"hosted spend in {month or 'this month'} has reached ${month_usd:.2f}, past "
            f"the ${warn:.2f} warning line; the ${self.config.envelope_usd:.2f} envelope "
            "refuses non-critical calls."
        )

    def _settle(self, decision: GovernorDecision) -> GovernorDecision:
        self.last_decision = decision
        if decision.admitted:
            self.admitted += 1
        else:
            self.refused += 1
        if decision.warning:
            self._announce(decision.warning)
        if not decision.admitted:
            self._announce(decision.reason)
        return decision

    def _announce(self, message: str) -> None:
        if self._on_event is None or message in self._announced:
            return
        self._announced.add(message)
        try:
            self._on_event(message)
        except Exception:  # noqa: BLE001 - a warning may never break a turn
            self.notes_dropped += 1

    def _read_month(self) -> tuple[str, float, bool]:
        reader = self._month_to_date
        if reader is None:
            # Nobody wired a ledger. That is not "unknown spend" — it is a
            # product nobody asked to meter, and it behaves as it did before.
            return ("", 0.0, True)
        try:
            total = reader()
        except Exception:  # noqa: BLE001 - a ceiling may never break a turn
            self.read_failures += 1
            return ("", 0.0, False)
        if total is None:
            return ("", 0.0, True)
        readable = bool(getattr(total, "readable", True))
        return (str(getattr(total, "month", "")), float(getattr(total, "usd", 0.0)), readable)

    def _read_day(self) -> tuple[str, float]:
        reader = self._day_to_date
        today = self._now().astimezone(timezone.utc).strftime("%Y-%m-%d")
        if reader is None:
            return (today, 0.0)
        try:
            total = reader()
        except Exception:  # noqa: BLE001 - the day burn is a report, not a gate
            self.read_failures += 1
            return (today, 0.0)
        if total is None:
            return (today, 0.0)
        return (str(getattr(total, "day", today)), float(getattr(total, "usd", 0.0)))

    def snapshot(self) -> dict[str, object]:
        """What ``/api/state`` says about the envelope."""

        month, month_usd, readable = self._read_month()
        day, day_usd = self._read_day()
        return {
            "config": self.config.as_dict(),
            "month": month,
            "month_usd": round(month_usd, 6),
            "month_readable": readable,
            "remaining_usd": round(self.config.envelope_usd - month_usd, 6),
            "day": day,
            "day_usd": round(day_usd, 6),
            "admitted": self.admitted,
            "refused": self.refused,
            "read_failures": self.read_failures,
            "notes_dropped": self.notes_dropped,
            "last": None if self.last_decision is None else self.last_decision.as_dict(),
        }


def _flag(section: Mapping[str, object], key: str, default: bool) -> bool:
    value = section.get(key, default)
    if not isinstance(value, bool):
        raise TypeError(f"governor.{key} must be true or false, got {value!r}")
    return value


def _money(section: Mapping[str, object], key: str, default: float) -> float:
    value = section.get(key, default)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"governor.{key} must be a number of dollars, got {value!r}")
    number = float(value)
    if not math.isfinite(number) or number < 0.0:
        raise ValueError(f"governor.{key} must be a finite, non-negative number, got {value!r}")
    return number


__all__ = [
    "CALL_CLASSES",
    "CLASS_CRITICAL",
    "CLASS_ROUTINE",
    "CODE_ADMITTED",
    "CODE_DAY_CAP_REACHED",
    "CODE_DISABLED",
    "CODE_ENVELOPE_REACHED",
    "CODE_LEDGER_UNKNOWN",
    "CODE_NEVER_GOVERNED",
    "DECISION_CODES",
    "DEFAULT_ENVELOPE_USD",
    "DEFAULT_RESERVE_USD",
    "DEFAULT_WARN_USD",
    "GOVERNOR_CONFIG_KEYS",
    "GovernorConfig",
    "GovernorDecision",
    "HostedCallGovernor",
    "HostedCallRefused",
]
