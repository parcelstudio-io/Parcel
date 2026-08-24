"""What finally CALLS the distiller — the missing scheduler.

RESEARCH H5 (``research/20260823/governed-continual-memory/DESIGN.md``).

THE DEFECT THIS CLOSES
----------------------
``owner_model.distiller.distil_session`` is wired, tested and callable, and
**nothing invokes it** — not at session close, not on a timer. P2-A's own
handoff says so in prose (``scrum/20260822/task_10/P2A_STATUS.md`` §9: "Nothing
schedules distillation"). The consequence is that the owner's ask — a dog that
recursively learns about them — is impossible by construction: every turn is
written, no turn is ever read back into a durable belief.

This module is the two triggers and nothing else:

* :meth:`ContinualMemoryScheduler.on_session_close` — the conversation ended,
  so read the turns it produced and propose what they said.
* :meth:`ContinualMemoryScheduler.on_idle` — nobody has spoken for a while and
  turns have accumulated since the last pass, so do it now rather than waiting
  for a session boundary that may never come (the hosted lane rolls over; the
  local one has no session at all).

THE FLAG DEFAULTS OFF
---------------------
:attr:`ContinualMemoryConfig.enabled` is ``False`` and the config key is
``memory.continual.enabled``. A disabled scheduler is not a stub: it still
answers every call, still reports, and writes nothing. That is deliberate —
"the scheduler ran and was off" and "the scheduler was never called" must be
distinguishable in a report, because the first is a configuration and the
second is the defect this module exists to close.

THE GUARD IS PRESERVED, AND IT LATCHES
--------------------------------------
``distil_session`` runs
:func:`~parcel_robot.owner_model.guard.assert_store_is_distillable` first and
there is no way past it. This module does not weaken that and cannot: it calls
the same function with no extra arguments. What it adds is the behaviour a
*scheduled* caller needs — a refusal is caught, reported as
:data:`TRIGGER_REFUSED`, and **latched**, so a store the owner has not
quarantined is refused once rather than once every idle tick forever. The
refusal is never swallowed into silence: it is on the report, it carries the
guard's own sentence, and :attr:`ContinualMemoryScheduler.refusal` stays set.

WHAT THIS MODULE DOES NOT DECIDE
--------------------------------
Which facts may be kept (``owner_model.policy``), who may grant consent
(``owner_model.principal``), and what a good fact looks like (the proposer). It
decides *when* — and the one consequence of scheduling that nothing else can
own: a pass that re-reads old turns must not re-propose what the owner has since
revoked (:class:`RevocationAwareProposer`).
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from ..owner_model.distiller import (
    DEFAULT_TURN_WINDOW,
    DeterministicFactProposer,
    DistillationReport,
    FactCandidate,
    distil_session,
)
from ..owner_model.guard import SyntheticRowsUnquarantined
from .episodes import EPISODE_CONVERSATION, Episode, EpisodeLog

if TYPE_CHECKING:  # pragma: no cover - typing only, no runtime import cycle
    from ..owner_model.distiller import FactProposer
    from .conversation import ConversationMemory

logger = logging.getLogger(__name__)

#: The config key. Spelled once, here, so the flag and the docs cannot drift.
CONFIG_SECTION = "memory"
CONFIG_KEY = "continual"

#: Why a pass did or did not happen. A closed set so a caller can branch on it.
TRIGGER_SESSION_CLOSE = "session_close"
TRIGGER_IDLE = "idle"
TRIGGER_DISABLED = "disabled"
TRIGGER_TOO_SOON = "too_soon"
TRIGGER_NO_NEW_TURNS = "no_new_turns"
TRIGGER_REFUSED = "refused"
TRIGGER_FAILED = "failed"
TRIGGERS: frozenset[str] = frozenset(
    {
        TRIGGER_SESSION_CLOSE,
        TRIGGER_IDLE,
        TRIGGER_DISABLED,
        TRIGGER_TOO_SOON,
        TRIGGER_NO_NEW_TURNS,
        TRIGGER_REFUSED,
        TRIGGER_FAILED,
    }
)


@dataclass(frozen=True)
class ContinualMemoryConfig:
    """Frozen, validated knobs. Default OFF; invalid values fail at construction.

    ``idle_seconds`` is a gap, not a period: the idle tick fires when the store
    has been quiet for that long AND new turns have arrived, so a silent house
    costs nothing and a busy one is not distilled every minute.
    """

    enabled: bool = False
    idle_seconds: float = 300.0
    min_new_turns: int = 4
    turn_window: int = DEFAULT_TURN_WINDOW
    #: Drop candidates whose key the owner has already revoked. See
    #: :class:`RevocationAwareProposer` for why a scheduled caller needs this
    #: and a hand-driven one does not. ``False`` reproduces the pre-H5
    #: behaviour exactly and exists so the difference can be measured.
    respect_revocations: bool = True

    def __post_init__(self) -> None:
        if self.idle_seconds <= 0.0:
            raise ValueError("idle_seconds must be positive")
        if self.min_new_turns < 1:
            raise ValueError("min_new_turns must be at least 1")
        if not 1 <= self.turn_window <= 500:
            raise ValueError("turn_window must be between 1 and 500")

    @classmethod
    def from_settings(cls, settings: Mapping[str, Any] | None) -> ContinualMemoryConfig:
        """Read ``memory.continual`` out of a settings mapping. Absent ⇒ OFF.

        An unknown key is a hard error for the same reason the map's settings
        block makes one: ``enabld: true`` looks exactly like a switch that never
        flipped, and the failure of THIS switch is a robot that never learns.
        """

        block = ((settings or {}).get(CONFIG_SECTION) or {}).get(CONFIG_KEY)
        if block is None:
            return cls()
        if not isinstance(block, Mapping):
            raise TypeError(f"{CONFIG_SECTION}.{CONFIG_KEY} must be a mapping")
        known = {
            "enabled",
            "idle_seconds",
            "min_new_turns",
            "turn_window",
            "respect_revocations",
        }
        unknown = sorted(set(block) - known)
        if unknown:
            raise ValueError(
                f"unknown {CONFIG_SECTION}.{CONFIG_KEY} keys: {unknown} "
                f"(known: {sorted(known)})"
            )
        return cls(
            enabled=bool(block.get("enabled", False)),
            idle_seconds=float(block.get("idle_seconds", 300.0)),
            min_new_turns=int(block.get("min_new_turns", 4)),
            turn_window=int(block.get("turn_window", DEFAULT_TURN_WINDOW)),
            respect_revocations=bool(block.get("respect_revocations", True)),
        )


def revoked_fact_keys(memory: ConversationMemory) -> frozenset[str]:
    """Keys the owner soft-deleted and has not since restated. Read-only.

    ``forget_owner_fact`` sets ``deleted_at``; every read in
    ``ConversationMemory`` then filters the row out. A key that ALSO has a live
    row is not revoked — the owner told the robot again, and the newer statement
    is the one that counts.
    """

    # Card A9: the implementation moved to ``ConversationMemory`` (beside the
    # two writes it reads) so the distillation path can ask the same question
    # without importing this module. The name, signature and answer are
    # unchanged; the duck-typed fallback keeps the stub stores H5's harness
    # passes in working.
    reader = getattr(memory, "revoked_fact_keys", None)
    if callable(reader):
        return frozenset(reader())
    live: set[str] = set()
    dead: set[str] = set()
    for row in memory.owner_facts(include_deleted=True):
        key = _key_slug(row.get("key", ""))
        if not key:
            continue
        if row.get("deleted_at"):
            dead.add(key)
        else:
            live.add(key)
    return frozenset(dead - live)


def _key_slug(key: object) -> str:
    """The same normalization ``ConversationMemory.add_owner_fact`` applies."""

    return "_".join(str(key).strip().lower().split())


@dataclass
class RevocationAwareProposer:
    """A proposer that will not re-propose what the owner revoked.

    THE DEFECT IT CLOSES, measured in H5 and reproducible with
    ``respect_revocations=False``: ``add_owner_fact`` upserts on
    ``key = ? AND deleted_at IS NULL``, so a soft-deleted row is invisible to
    the upsert and a later pass over the SAME turns INSERTS the fact again,
    ``consent='granted'``, into the developer instruction. Nothing about that is
    wrong at the store — a hand-driven ``remember_fact`` after a ``forget`` is
    the owner asking again, and it must work. What is wrong is a *scheduled*
    pass re-reading the sentence the owner already told it to drop and calling
    that a new statement.

    So the tombstone check lives here, on the scheduled path, and not in the
    store: it costs one read per pass, it is inert for every hand-driven write,
    and it is one flag away from off so the difference stays measurable.
    """

    memory: ConversationMemory
    inner: FactProposer

    def __call__(self, turns: Sequence[Mapping[str, Any]]) -> Sequence[FactCandidate]:
        revoked = revoked_fact_keys(self.memory)
        if not revoked:
            return self.inner(turns)
        return tuple(
            candidate
            for candidate in self.inner(turns)
            if _key_slug(candidate.normalized().key) not in revoked
        )


@dataclass(frozen=True)
class SchedulerRun:
    """What one call to the scheduler did, in enough detail to answer "why not".

    A run that did nothing is still a run and still reports: ``ran=False`` with
    a trigger naming the reason is the difference between a disabled feature and
    a broken one.
    """

    ran: bool
    trigger: str
    session_id: str = ""
    report: DistillationReport | None = None
    episode: Episode | None = None
    duration_s: float = 0.0
    detail: str = ""

    @property
    def written(self) -> int:
        return int(self.report.written) if self.report is not None else 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "ran": self.ran,
            "trigger": self.trigger,
            "session_id": self.session_id,
            "written": self.written,
            "duration_s": round(self.duration_s, 6),
            "detail": self.detail,
            "report": self.report.as_dict() if self.report is not None else None,
            "episode": self.episode.as_dict() if self.episode is not None else None,
        }


@dataclass
class ContinualMemoryScheduler:
    """Calls ``distil_session`` at the two moments a companion has for it.

    ``memory`` is a :class:`~parcel_robot.memory.conversation.ConversationMemory`
    on whatever store the caller resolved; this class never resolves a path and
    never opens a store, so it cannot be the thing that reaches the owner's file.

    ``proposer`` is injected. ``None`` means ``distil_session``'s own default
    (the deterministic regex proposer), so a stack with no model server still
    distils something; a
    :class:`~parcel_robot.owner_model.distiller.LanguageModelFactProposer` bound
    to a local server is the live path H5 measures.
    """

    memory: ConversationMemory
    config: ContinualMemoryConfig = field(default_factory=ContinualMemoryConfig)
    proposer: FactProposer | None = None
    episodes: EpisodeLog | None = None
    clock: Callable[[], float] = time.monotonic
    wall_clock: Callable[[], float] = time.time
    #: Set when the guard refused this store. Latched: see the module docstring.
    refusal: str = ""
    _turns_since_pass: int = 0
    _last_activity: float = field(default=0.0)
    _last_pass: float = field(default=0.0)
    _passes: int = 0

    def __post_init__(self) -> None:
        now = float(self.clock())
        self._last_activity = now
        self._last_pass = now

    # -- what the runtime tells it -------------------------------------------

    def note_turn(self, count: int = 1) -> None:
        """One (or ``count``) turns were written. Cheap; safe on the hot path.

        Counting here rather than asking the store how many rows it has is the
        difference between an O(1) call on every turn and a COUNT(*) on a
        3,000-row table on every turn.
        """

        self._turns_since_pass += max(0, int(count))
        self._last_activity = float(self.clock())

    @property
    def turns_since_pass(self) -> int:
        return self._turns_since_pass

    @property
    def passes(self) -> int:
        return self._passes

    # -- the two triggers -----------------------------------------------------

    def on_session_close(
        self,
        session_id: str = "",
        *,
        summary: str = "",
        outcome: str = "closed",
    ) -> SchedulerRun:
        """The conversation ended: distil it, and record the episode.

        Runs even when no new turn was counted, because a session that closes
        having said nothing is exactly as interesting as one that did and the
        pass over an empty window is cheap (the proposer sees no owner turns and
        proposes nothing).
        """

        if not self.config.enabled:
            return SchedulerRun(False, TRIGGER_DISABLED, session_id=session_id)
        if self.refusal:
            return SchedulerRun(
                False, TRIGGER_REFUSED, session_id=session_id, detail=self.refusal
            )
        return self._pass(TRIGGER_SESSION_CLOSE, session_id, summary=summary, outcome=outcome)

    def on_idle(self, now: float | None = None) -> SchedulerRun:
        """Nobody has spoken for ``idle_seconds`` and turns have accumulated."""

        if not self.config.enabled:
            return SchedulerRun(False, TRIGGER_DISABLED)
        if self.refusal:
            return SchedulerRun(False, TRIGGER_REFUSED, detail=self.refusal)
        clock_now = float(self.clock() if now is None else now)
        if self._turns_since_pass < self.config.min_new_turns:
            return SchedulerRun(False, TRIGGER_NO_NEW_TURNS)
        if (clock_now - self._last_activity) < self.config.idle_seconds:
            return SchedulerRun(False, TRIGGER_TOO_SOON)
        return self._pass(TRIGGER_IDLE, "")

    def _active_proposer(self) -> FactProposer | None:
        """The injected proposer, wrapped in the tombstone check when configured.

        ``None`` still means "``distil_session``'s own default", and the wrapper
        is applied around that default too — otherwise the flag would silently
        do nothing on the configuration most stacks run.
        """

        if not self.config.respect_revocations:
            return self.proposer
        inner = self.proposer if self.proposer is not None else DeterministicFactProposer()
        return RevocationAwareProposer(memory=self.memory, inner=inner)

    # -- the pass -------------------------------------------------------------

    def _pass(
        self,
        trigger: str,
        session_id: str,
        *,
        summary: str = "",
        outcome: str = "closed",
    ) -> SchedulerRun:
        started_wall = float(self.wall_clock())
        started = float(self.clock())
        try:
            # ``session_id`` is deliberately NOT forwarded. Measured in H5:
            # ``distil_session``'s session filter tests
            # ``turn.get("session_id")`` against rows produced by
            # ``ConversationMemory.conversation_turns``, and that reader does not
            # emit a ``session_id`` key at all — so ANY session id makes the pass
            # read zero turns, silently, on every store. A scheduler that passed
            # one would be a scheduler that never distils anything, which is the
            # exact defect this module exists to close. The bound that matters is
            # ``turn_window``; the session id is recorded on the episode, where it
            # is a fact about the conversation rather than a filter that does not
            # work.
            report = distil_session(
                self.memory,
                session_id=None,
                proposer=self._active_proposer(),
                turn_window=self.config.turn_window,
                # Card A9: the same flag, now reaching BOTH layers. The wrapper
                # above keeps a revoked candidate away from the policy; this
                # keeps it away from the WRITE, which is the half that covers a
                # caller who supplied its own proposer. ``False`` still turns the
                # whole behaviour off, so the measured difference stays one flag.
                respect_revocations=self.config.respect_revocations,
            )
        except SyntheticRowsUnquarantined as refusal:
            # LATCHED, and loud. See the module docstring: a scheduled caller
            # that retried this every idle tick would turn one refusal into a
            # log flood, and a scheduled caller that swallowed it would turn a
            # governance decision into silence.
            self.refusal = str(refusal)
            logger.warning("continual memory refused this store: %s", refusal)
            return SchedulerRun(
                False,
                TRIGGER_REFUSED,
                session_id=session_id,
                duration_s=float(self.clock()) - started,
                detail=self.refusal,
            )
        except Exception as error:
            # A background pass never ends the turn that triggered it: the
            # proposer is injected and may raise anything, and a distillation
            # crash must cost a report rather than a conversation. Logged with
            # ``logger.exception`` so the traceback survives the swallow.
            logger.exception("continual memory pass failed")
            return SchedulerRun(
                False,
                TRIGGER_FAILED,
                session_id=session_id,
                duration_s=float(self.clock()) - started,
                detail=str(error),
            )

        duration = float(self.clock()) - started
        self._turns_since_pass = 0
        self._last_pass = float(self.clock())
        self._passes += 1
        episode = None
        if trigger == TRIGGER_SESSION_CLOSE and self.episodes is not None:
            episode = self._record_episode(
                session_id, report, started_wall, summary=summary, outcome=outcome
            )
        return SchedulerRun(
            True,
            trigger,
            session_id=session_id,
            report=report,
            episode=episode,
            duration_s=duration,
        )

    def _record_episode(
        self,
        session_id: str,
        report: DistillationReport,
        started_wall: float,
        *,
        summary: str,
        outcome: str,
    ) -> Episode | None:
        """One conversation episode, referencing the facts the pass wrote.

        The summary is the CALLER's — this module does not own a summarizer and
        will not invent one. Absent a summary it records the shape of the pass
        ("a conversation of 12 turns; 2 facts kept"), which is true, cheap and
        does not pretend to be a précis of what was said.
        """

        kept = tuple(row.candidate.key for row in report.kept)
        asked = tuple(row.candidate.key for row in report.asked)
        text = summary.strip() or (
            f"a conversation of {report.turns_read} turns; "
            f"{len(kept)} facts kept, {len(asked)} parked for consent"
        )
        try:
            episode = Episode(
                episode_id=f"conv-{session_id or 'unnamed'}-{self._passes}",
                kind=EPISODE_CONVERSATION,
                started_wall_s=started_wall,
                ended_wall_s=float(self.wall_clock()),
                summary=text,
                outcome=outcome,
                session_id=session_id,
                fact_keys=kept + asked,
            )
        except ValueError as error:  # pragma: no cover - defensive; summary is bounded
            logger.warning("episode not recorded: %s", error)
            return None
        if self.episodes is not None:
            self.episodes.append(episode)
        return episode


__all__ = [
    "CONFIG_KEY",
    "CONFIG_SECTION",
    "TRIGGERS",
    "TRIGGER_DISABLED",
    "TRIGGER_FAILED",
    "TRIGGER_IDLE",
    "TRIGGER_NO_NEW_TURNS",
    "TRIGGER_REFUSED",
    "TRIGGER_SESSION_CLOSE",
    "TRIGGER_TOO_SOON",
    "ContinualMemoryConfig",
    "ContinualMemoryScheduler",
    "RevocationAwareProposer",
    "SchedulerRun",
    "revoked_fact_keys",
]
