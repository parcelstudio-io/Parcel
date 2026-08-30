"""Fail-closed loader for the optional ``configs/realtime.yaml`` (card R1).

WHY A SEPARATE FILE AND NOT A ``robot.yaml`` SECTION
----------------------------------------------------
``configs/robot.yaml`` is hash-locked: the embodied-plan eval manifest and the
gate's ``DIGEST_SENTINELS`` both pin its bytes, so one added key moves two
frozen digests and reddens a hard gate. The lane's config is therefore a NEW,
OPTIONAL file. Its absence is not an error — it is the shipped default, and it
means the lane does not construct at all. Flag-off is *file-absent*, which is
the strongest form of "off" available: there is nothing to misread.

FAIL-CLOSED, THE SAME WAY EVERY OTHER CONFIG SURFACE HERE DOES
--------------------------------------------------------------
``providers.py`` refuses unknown ``speech:`` keys; ``resolve_allow_monitor_capture``
raises on a non-boolean. A typo'd ``enabled: ture`` that silently read as false
would be a bad day; a typo'd ``monthly_budget_usd`` that silently read as
"unlimited" would be a worse one. Unknown keys raise, wrong types raise, and
negative budgets raise.

``+inf`` USED TO READ AS "UNLIMITED" (card R25, closing R23's registered gap)
----------------------------------------------------------------------------
The paragraph above was aspirational for one value. :func:`_positive` tested
``not number > 0.0``, which refuses NaN (``nan > 0`` is False) but ACCEPTS
``float("inf")`` — and YAML spells that ``.inf``. In this file ``+inf`` meant an
infinite stall timeout, an unbounded session, a microphone that never
idle-closes and *precisely* the "unlimited budget" this docstring says must not
be possible. Card R23 measured it, could not fix it (the realtime package was
outside its OWNS list) and pinned it as a registered gap
(``scrum/20260821/task_2/R23_STATUS.md`` §7.2). Card R25 owns this file's
validation and owns the budget, so the gap is closed here: every positive and
non-negative number in this file must now be FINITE.
"""

from __future__ import annotations

import math
import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from parcel_robot.paths import parcel_roots, resolve_asset

# Card TURN-1. The endpointing object lives in ``protocol.py`` because it is a
# WIRE object — it has to render the exact ``session.audio.input.turn_detection``
# mapping the provider reads, and a second copy of that shape in this file is a
# second place for it to drift. ``protocol`` imports nothing from this package,
# so this direction is the acyclic one; it is also a pure codec, no I/O.
from .protocol import (
    TURN_DETECTION_EAGERNESS,
    TURN_DETECTION_TYPES,
    RealtimeProtocolError,
    TurnDetection,
)

#: Repo-relative location the runtime looks for. Deliberately NOT created by
#: this card and deliberately NOT in the packaged ship set for R1.
REALTIME_CONFIG_RELATIVE = ("configs", "realtime.yaml")

#: Test / operator override, so a tmp_path config can be exercised without ever
#: writing a file into the repo.
REALTIME_CONFIG_ENV = "PARCEL_REALTIME_CONFIG"

#: How the owner talks to the lane. ``text`` is the manual-testing path — the
#: panel's text box, no microphone, no speaker, no audio gateway — and is the
#: default because it is the only mode that works on a host with no PortAudio.
#: ``audio`` adds the browser mic/speaker gateway. An unknown value refuses.
MODE_TEXT = "text"
MODE_AUDIO = "audio"
ALLOWED_MODES = frozenset({MODE_TEXT, MODE_AUDIO})

#: The whole schema. Anything else is a typo, and a typo is a refusal.
ALLOWED_KEYS = frozenset(
    {
        "enabled",
        "mode",
        "persona",
        "si_profile",
        "model",
        "voice",
        "stall_timeout_s",
        "session_max_s",
        "idle_close_after_s",
        "monthly_budget_usd",
        "whisperer",
        "capture",
        "voice_identity",
        # Card P0-B — the four companion unlocks. Every one of them is OFF in
        # the value it takes when the key is absent, so a config written before
        # this card loads to byte-identical behaviour.
        "proactive_motion_tools",
        "unknown_place",
        "hosted_affect",
        # Card TURN-1 — endpointing. Absent means the block is not written at
        # all, which renders the identical ``session.update`` this repo has sent
        # since 2026-08-18 (pre-registered row T1/T2, seeded).
        "turn_detection",
        # Card C5 (SPEECH-ACTS-1) — the receipt-typed utterance contract.
        # Absent means OFF, and OFF is byte-identical narration: the lane keeps
        # sending whatever text its caller composed.
        "speech_acts",
    }
)

#: Card TURN-1. The nested ``turn_detection:`` block. The keys are the provider's
#: own, spelled exactly as they go on the wire, so a reader of the yaml and a
#: reader of a wire trace are looking at the same words. Same refusal discipline
#: as every other block here.
TURN_DETECTION_ALLOWED_KEYS = frozenset(
    {
        "type",
        "threshold",
        "prefix_padding_ms",
        "silence_duration_ms",
        "eagerness",
        "interrupt_response",
        "create_response",
    }
)

#: Card C5 (SPEECH-ACTS-1). The nested ``speech_acts:`` block. One key today
#: and the same refusal discipline as every other block here — a typo'd
#: ``enabled: ture`` that silently read as false would hide the switch that
#: decides whether the robot's own sentences come from a contract or from a
#: model, which is exactly the thing an operator must be able to see.
SPEECH_ACTS_ALLOWED_KEYS = frozenset({"enabled"})

#: The nested ``whisperer:`` block — the owner's cost knob (card R11, owner
#: directive 2026-08-20). Same refusal discipline as the outer schema.
WHISPERER_ALLOWED_KEYS = frozenset(
    {
        "enabled",
        "max_updates_per_minute",
        "min_gap_s",
        "window_s",
        "owner_events",
        # Card CURIO-1 — the chatter layer. Nested here for P2-B's reason
        # exactly: a curiosity remark is whisperer traffic, banded and capped by
        # the block it sits in, and an owner who turns the cap down has to see
        # everything the cap holds in one place.
        "curiosity",
    }
)

#: Card P2-B. The nested ``whisperer.owner_events:`` block. Same fail-closed
#: discipline as every other block in this file: an unknown key is a typo, and a
#: typo that silently read as a default would be a companion that greets on a
#: schedule nobody wrote down.
OWNER_EVENTS_ALLOWED_KEYS = frozenset(
    {
        "enabled",
        "min_confidence",
        "appear_debounce_s",
        "absence_s",
        "long_absence_h",
        "greeting_interval_s",
        "question_of_the_day",
    }
)

# ================================= card CURIO-1: the chatter block's schema ==
#: The nested ``whisperer.curiosity:`` block — WHEN the dog may remark on what
#: it has seen. Same fail-closed discipline as every other block in this file: a
#: key nothing reads looks exactly like a switch that was never flipped, and the
#: switch this block holds is "does the robot start talking on its own".
CURIOSITY_ALLOWED_KEYS = frozenset(
    {
        "enabled",
        "mean_gap_s",
        "stimulus_min_gap_s",
        "min_gap_floor_s",
        "quiet_s",
        "require_owner_present",
        "night_quiet",
        "farewell",
        "farewell_after_s",
        "gesture_when_capped",
    }
)
# ============================= END card CURIO-1 (chatter block's schema) =====

#: Card P0-B, deliverable 1 — WHICH MOTION TOOLS A SYSTEM-INITIATED REPLY MAY RUN.
#:
#: ``tool_broker`` refuses every :data:`~parcel_robot.realtime.tool_broker.MOTION_TOOLS`
#: proposal when the response the model is answering was started by the ROBOT
#: (card R11, bench finding C1: one injected telemetry item fired a spurious
#: ``navigate_to`` in 2 of 3 forced-response trials). That gate is why the dog
#: cannot drive off because it told itself something — and it is also why the
#: companion may never so much as tilt its head unless spoken to first.
#:
#: The unlock is deliberately not "trust the provenance tag". It is a NAMED,
#: closed list of tools whose worst case is a body that moved in place:
#:
#: * ``play_gesture`` and ``set_pose`` are bounded pose/trajectory skills that
#:   run through the activity coordinator's cooldown, ttl and arbitration, and
#:   they carry no navigation goal, no owner-relative tracking and no distance.
#: * ``navigate_to``, ``circle_owner`` and ``follow_owner`` COMMIT THE ROBOT TO
#:   TRAVEL. A proactive one is the C1 defect exactly, so naming one of them
#:   here is a load refusal rather than a permission — see
#:   :data:`PROACTIVE_MOTION_REFUSED`.
#:
#: Empty is the default and empty is the pre-card behaviour.
PROACTIVE_MOTION_ALLOWED: tuple[str, ...] = ("play_gesture", "set_pose")

#: The travel tools. Listing one in ``proactive_motion_tools`` is a refusal at
#: load, with the reason, rather than a silent drop at dispatch: an operator who
#: wrote it meant it, and the honest answer is to say why it cannot be had.
#: Card ROAM-1 appends ``roam`` — the fourth travel tool and the only one with
#: no destination in it. A proactive roam is bench finding C1 with a longer
#: fuse: no place noun to check, no arrival to fail, just a dog that decided to
#: leave. The card's own test asserts this tuple plus
#: :data:`PROACTIVE_MOTION_ALLOWED` still covers ``MOTION_TOOLS`` exactly, so a
#: tenth tool cannot join the surface without a verdict being written here.
PROACTIVE_MOTION_REFUSED: tuple[str, ...] = (
    "navigate_to",
    "circle_owner",
    "follow_owner",
    "roam",
)

#: Card P0-B, deliverable 2 — WHAT ``navigate_to`` DOES WITH A PLACE NOBODY NAMED.
#:
#: ``refuse`` is the shipped behaviour and the default: a plain noun the robot
#: has never heard of ("narnia") is admitted, rendered into the router as
#: ``go to narnia`` and allowed to fail honestly at grounding, exactly as a
#: TYPED sentence does (``test_navigate_to_grants_exactly_what_a_typed_sentence
#: _grants`` pins that parity). The refusal, when it comes, comes from the map.
#:
#: ``ask`` answers the model instead: a structured ``unknown_place`` result that
#: names the places the robot DOES know, touches no door and starts no motion,
#: so the companion asks the owner where that is (or offers to go look) rather
#: than setting off toward a name it cannot ground. Prototype directive
#: 2026-08-22: ask over refuse.
UNKNOWN_PLACE_REFUSE = "refuse"
UNKNOWN_PLACE_ASK = "ask"
ALLOWED_UNKNOWN_PLACE_MODES = frozenset({UNKNOWN_PLACE_REFUSE, UNKNOWN_PLACE_ASK})

#: Card P0-B, deliverable 3. The one value of ``idle_close_after_s`` that is not
#: a number of seconds: keep the session open for as long as it stays healthy.
IDLE_CLOSE_NEVER = 0.0

#: Card P0-B, deliverable 4. The rolling window ``whisperer.max_updates_per_minute``
#: is counted over, in seconds. Sixty is what the cap has always meant and is
#: the default; the key exists so the narration rate is one knob and not "a
#: number you may set and a minute you may not".
DEFAULT_WHISPERER_WINDOW_S = 60.0

#: The nested ``capture:`` block — session audio capture (card R17, owner
#: directive 2026-08-20 "store these valuable audio as test cases"). Same
#: refusal discipline as ``whisperer:``: an unknown key is a typo and a typo is
#: a refusal, because a mistyped ``max_minutes`` silently reading as the default
#: would let a session that meant to record for two minutes record for thirty.
CAPTURE_ALLOWED_KEYS = frozenset({"enabled", "dir", "max_minutes", "owner_gap_s"})

#: The nested ``voice_identity:`` block — speaker verification for command
#: arming (card F1-SI). Same refusal discipline again, and here it matters more
#: than anywhere else in this file: a mistyped ``treshold`` silently reading as
#: the default would make a config that meant to be strict merely look strict,
#: and the only symptom would be a robot that obeys a television.
VOICE_IDENTITY_ALLOWED_KEYS = frozenset(
    {
        "enabled",
        "threshold",
        "profile",
        "model",
        "min_utterance_s",
        "budget_ms",
        "narration_interval_s",
        "doa",
        "rejected_sector",
    }
)

#: Decision 1's starting threshold: the midpoint of the worst-case gap measured
#: on THIS host's own microphone array (``bench_doa.md`` Bench B — max impostor
#: pair 0.431, min genuine pair 0.640, zero overlap on 378 pairs).
DEFAULT_VOICE_THRESHOLD = 0.55

#: Where recordings land when the config does not say. Repo-relative, created
#: lazily, and deliberately NOT under ``evals/``: an eval corpus is a reviewed,
#: frozen fixture and a capture directory is an append-only firehose. Mixing
#: them would let a live session silently rewrite the record it is scored
#: against. :func:`resolve_capture_dir` enforces that as a refusal.
DEFAULT_CAPTURE_DIR = "recordings"

#: Bound on ONE session's recording, in minutes. Capture stops itself at the
#: cap and says so; the session keeps running (an audio tee is a convenience,
#: never a reason to end a conversation). 30 minutes of 24 kHz mono PCM16 is
#: ~86 MB per stream, which is the size of "left it on by accident" rather than
#: the size of "filled the disk".
DEFAULT_CAPTURE_MAX_MINUTES = 30.0

#: Silence between owner microphone frames that starts a NEW owner segment in
#: the per-utterance index. The robot half is delimited by the lane's own
#: ``begin_utterance``; the owner half has no such marker, so the index cuts on
#: a gap. 0.75 s is longer than any capture buffer and shorter than any pause
#: between two spoken corpus queries.
DEFAULT_CAPTURE_OWNER_GAP_S = 0.75

#: The directory name a capture root may never resolve inside.
_FORBIDDEN_CAPTURE_PARENT = "evals"

#: Longest free-text persona accepted. A persona is prose, not a document: the
#: SI is re-sent on every reconnect and every byte of it is billed as input on
#: every session, so an unbounded key would be an unbounded bill.
MAX_PERSONA_CHARS = 2000


class RealtimeConfigError(ValueError):
    """A realtime config that cannot be trusted. Never downgraded to a default."""


@dataclass(frozen=True)
class OwnerEventsConfig:
    """Card P2-B. When the robot may start a conversation ABOUT THE OWNER.

    THE ONE THING TO UNDERSTAND ABOUT THIS BLOCK
    --------------------------------------------
    It buys nothing. Every owner event still passes through the whisperer's
    band table, its dedup window, its ``min_gap_s`` and its
    ``max_updates_per_minute`` cap, and none of them is in ``CRITICAL_KINDS`` —
    so this block can only ever make the robot *eligible* to greet you, never
    entitled to. The knobs here decide when a greeting is DUE; the knobs above
    decide whether a due greeting is affordable, and they win.

    **Default off.** A companion that greets you is the point of card P2-B, and
    default-off is still right for the shipped file: every forward is a billed
    hosted response, and a config written before this card must keep costing
    exactly what it cost. ``configs/realtime.prototype.yaml.example`` is where
    ``enabled: true`` belongs (see P2B_STATUS.md §2 for the block to paste).
    """

    #: The opt-in. Nothing else in this block has any effect while it is false,
    #: and with it false the owner-event classes are never produced at all —
    #: not produced-and-suppressed, not produced-and-deduped: never produced.
    enabled: bool = False
    #: How sure the owner track has to be before a sighting counts. The mocap /
    #: UWB track reports 1.0; P1-C's pixel track reports a measured similarity,
    #: and this is the number that keeps a 0.2-confidence stranger from being
    #: greeted as the owner.
    min_confidence: float = 0.3
    #: How long the owner must stay in view before an appearance is announced.
    #: This is the anti-flicker guard: a tracker that drops one frame must not
    #: buy a greeting.
    appear_debounce_s: float = 2.0
    #: How long the owner must have been AWAY for a new sighting to count as an
    #: appearance at all. Below this it is the same visit and the dog has
    #: already said hello — the single most important number in this block for
    #: anybody who has met a real dog.
    absence_s: float = 60.0
    #: Above this, an appearance is a RETURN and gets the other sentence. In
    #: hours because that is the unit the owner thinks in.
    long_absence_h: float = 3.0
    #: Silence, in seconds, after which a present owner is owed a greeting.
    #: ``0`` disables that class alone (the appearance classes keep working).
    greeting_interval_s: float = 900.0
    #: The one question a day. False disables that class alone.
    question_of_the_day: bool = True

    def as_dict(self) -> dict[str, object]:
        return {
            "enabled": self.enabled,
            "min_confidence": self.min_confidence,
            "appear_debounce_s": self.appear_debounce_s,
            "absence_s": self.absence_s,
            "long_absence_h": self.long_absence_h,
            "greeting_interval_s": self.greeting_interval_s,
            "question_of_the_day": self.question_of_the_day,
        }


# ==================================== card CURIO-1: the chatter block ========
@dataclass(frozen=True)
class CuriosityConfig:
    """Card CURIO-1. When the robot may remark on what it has SEEN.

    THE ONE THING TO UNDERSTAND ABOUT THIS BLOCK
    --------------------------------------------
    Like P2-B's next door, it buys nothing. Every remark still passes the
    whisperer's band table, its dedup window, its ``min_gap_s`` and its
    ``max_updates_per_minute``, and no curiosity class is in ``CRITICAL_KINDS``.
    These knobs decide when a remark is DUE; the knobs above decide whether a
    due remark is affordable, and they win.

    THE ONE THING THAT IS DIFFERENT FROM P2-B
    -----------------------------------------
    P2-B's classes are edge-triggered on something rare — you walked in. These
    are fed by a map that grows on a camera frame, at 2 Hz, for the length of a
    walk. So this block carries a RATE where P2-B's carries thresholds, and the
    rate is the load-bearing part: with ``mean_gap_s`` removed the band table
    alone would spend the owner's whole minute on the first six lampposts.

    **Default off**, for P2-B's reason exactly: every forward is a billed hosted
    response, and a config written before this card must keep costing what it
    cost. ``configs/realtime.prototype.yaml.example`` is where ``enabled: true``
    belongs.
    """

    #: The opt-in. With it false the curiosity classes are never produced at
    #: all — not produced-and-suppressed, not produced-and-deduped: never
    #: produced, and the farewell class with them.
    enabled: bool = False
    #: The MEAN of the Poisson gap between IDLE remarks, in seconds. 360 s =
    #: six minutes, the middle of the card's 4–8 minute band. Gaps are
    #: exponential draws around this, so the dog is irregular rather than
    #: metronomic — which is the difference between a companion and a
    #: notification.
    #:
    #: **This paces ``idle_remark`` only.** Correction pass, 2026-08-22: the
    #: card's two numbers were two cadences over two kinds of remark, not one
    #: number written twice. See ``stimulus_min_gap_s`` below and
    #: ``whisperer.STIMULUS_KINDS``.
    mean_gap_s: float = 360.0
    #: The FLOOR between remarks that answer something that just happened —
    #: ``novel_object``, ``scene_change``, ``place_learned``, ``ask_about``. A
    #: fixed gap and not a mean, because the subject is already in the past: a
    #: six-minute wait would have the dog narrating a lamppost it walked past
    #: four corners ago. 25 s is the value the card's own "3-6 utterances in a
    #: 120 s roam" row implies, and it is now the shipped default rather than a
    #: harness override.
    stimulus_min_gap_s: float = 25.0
    #: The floor an exponential draw is clamped to. An exponential can come back
    #: at 0.2 s, and a remark 0.2 s after the last one is a stutter. The
    #: whisperer's own ``min_gap_s`` would refuse it anyway; this is the same
    #: bound one layer earlier, so the budget is not spent on something that was
    #: always going to be dropped.
    min_gap_floor_s: float = 20.0
    #: Silence, in seconds, that an OWNER exchange must be in the past before a
    #: remark may go out. This is the "do not talk over me" knob. A session
    #: nobody has spoken on has no conversation to protect and this does not
    #: block it — see ``ChatterScheduler._quiet_for``.
    quiet_s: float = 90.0
    #: Remark only when the owner is there to hear it. False makes the dog talk
    #: to an empty room, which is a legitimate thing to want in a sim run and a
    #: strange thing to want in a living room.
    require_owner_present: bool = True
    #: Go quiet in the NIGHT band (22:00–05:00 local). The band boundaries are
    #: not configurable on purpose (``whisperer.time_band_of`` says why); this is
    #: the knob.
    night_quiet: bool = True
    #: Say goodbye on the falling edge of the owner's presence.
    farewell: bool = True
    #: How long the owner must be out of view before that goodbye. Much larger
    #: than P2-B's ``appear_debounce_s`` and deliberately so: a hello fired at a
    #: passing shadow is charming and a goodbye fired at one is the robot
    #: farewelling your back while you stand in front of it.
    farewell_after_s: float = 45.0
    #: THE FREE VARIANT. When the owner's per-minute cap has already been spent,
    #: a remark that would have been billed becomes this gesture instead —
    #: nothing goes on the wire, nothing is billed, and the dog still visibly
    #: noticed something. Empty string disables it. The name must be in the
    #: runtime's emote catalog or the gesture is skipped and counted.
    gesture_when_capped: str = "curious_look"

    def as_dict(self) -> dict[str, object]:
        return {
            "enabled": self.enabled,
            "mean_gap_s": self.mean_gap_s,
            "stimulus_min_gap_s": self.stimulus_min_gap_s,
            "min_gap_floor_s": self.min_gap_floor_s,
            "quiet_s": self.quiet_s,
            "require_owner_present": self.require_owner_present,
            "night_quiet": self.night_quiet,
            "farewell": self.farewell,
            "farewell_after_s": self.farewell_after_s,
            "gesture_when_capped": self.gesture_when_capped,
        }


# ================================ END card CURIO-1 (the chatter block) =======


@dataclass(frozen=True)
class WhispererConfig:
    """How often the robot may talk to the owner about ITSELF.

    THE KNOB, AND WHY IT IS THE ONE THE OWNER ASKED FOR
    ---------------------------------------------------
    Every whisperer forward becomes a ``response.create`` on the hosted session,
    and the bench measured ``gpt-realtime-2.1-mini`` speaking on essentially
    every injected state item (0-2 silences in ~20). So one forward is one
    spoken line and one billed response, and ``max_updates_per_minute`` is
    therefore simultaneously the cost control and the politeness control.

    ``enabled: false`` stops state updates entirely and does NOT touch
    voice-command traffic — the owner talking to the robot is a different door
    (``send_text`` / the audio gateway) and never passes through the whisperer.

    DEFAULTS, AND WHY DEFAULT-ON IS THE CONSERVATIVE CHOICE HERE
    -----------------------------------------------------------
    An absent ``whisperer:`` block means these defaults. That is default-ON,
    which normally deserves suspicion — but the thing it replaces (R8's
    ``narrate_event`` wired straight to every mission terminal and every block
    edge) is already on and already billed, with no cap of any kind. Booting an
    existing config into ``max_updates_per_minute: 2`` strictly REDUCES both the
    spend and the chatter of that config. Defaulting to off would silently
    remove narration an owner already has.
    """

    enabled: bool = True
    #: Hard cap on billed non-voice queries per rolling minute. Excess folds
    #: into the next forwarded item as "+N more".
    max_updates_per_minute: int = 2
    #: Spacing inside the budget. Terminal-like events are exempt — the bench
    #: found a reroute silently swallowed by a min-gap a mission_clear was
    #: holding (``bench_whisperer.md``, "shared min-gap bug").
    min_gap_s: float = 15.0
    #: Card P0-B. The window :attr:`max_updates_per_minute` is counted over, in
    #: seconds. The cap was always "per rolling minute" and the minute was a
    #: literal ``60.0`` inside ``whisperer._spent`` — so half the narration rate
    #: was configurable and half of it was not, and an owner who wanted a
    #: chattier prototype could only buy it in whole units of two-per-minute.
    #: Default 60.0: the same minute, now written down.
    window_s: float = DEFAULT_WHISPERER_WINDOW_S
    #: Card P2-B. The owner-event bands. Nested here rather than at the top
    #: level because they ARE whisperer traffic: they are banded, deduped,
    #: min-gapped and capped by the block they sit in, and a reader who turns
    #: the cap down has to be able to see in one place everything the cap holds.
    owner_events: OwnerEventsConfig = OwnerEventsConfig()
    #: Card CURIO-1. The chatter layer — when the robot may remark on what it
    #: has SEEN. Nested here for the same reason ``owner_events`` is: it is
    #: whisperer traffic, it is capped by the block it sits in, and the two
    #: initiative families being one nesting apart is what lets an owner turn
    #: down "the dog goes first" with one number.
    curiosity: CuriosityConfig = CuriosityConfig()

    def as_dict(self) -> dict[str, object]:
        return {
            "enabled": self.enabled,
            "max_updates_per_minute": self.max_updates_per_minute,
            "min_gap_s": self.min_gap_s,
            "window_s": self.window_s,
            "owner_events": self.owner_events.as_dict(),
            "curiosity": self.curiosity.as_dict(),
        }


@dataclass(frozen=True)
class CaptureConfig:
    """Whether this session's audio is written to disk, and how much of it.

    THE DEFECT THIS EXISTS BECAUSE OF
    ---------------------------------
    On 2026-08-20 the owner spoke the whole 52-query voice corpus to the live
    robot. The gateway moved 3605 microphone frames up and 296 speech frames
    down and **wrote none of it anywhere**: the transcripts survived in the
    ledger, the audio did not. Every ASR failure in that run — a Korean TV
    sign-off attributed to the owner, the spoken emergency phrase transcribed
    as "Dice out!" and never matched, a code-switched sentence normalised away
    — is now unreproducible, because the only copy of the sound that produced
    it was a buffer that got freed.

    (The phrase itself is deliberately not written out here. It has exactly one
    literal in this source tree, in ``realtime/ingress.py``, and
    ``test_the_spoken_phrase_exists_exactly_once_in_the_source_tree`` keeps it
    that way — U33 cost a stop that stopped nothing because a grammar had three
    copies of it.)

    DEFAULT OFF, AND WHY THAT IS NOT COWARDICE
    ------------------------------------------
    Recording a household microphone to disk is the kind of thing that must be
    asked for in writing, once, by the person whose voice it is. ``enabled:
    false`` is the shipped default and the absence of the whole block means the
    same. Turning it on is one line in a config only the owner edits.
    """

    enabled: bool = False
    #: Where per-session folders are created. Relative paths resolve against the
    #: repo root; ``evals/`` is refused (see :func:`resolve_capture_dir`).
    dir: str = DEFAULT_CAPTURE_DIR
    #: Hard bound on one session's recording. Reaching it stops CAPTURE, never
    #: the session.
    max_minutes: float = DEFAULT_CAPTURE_MAX_MINUTES
    #: Gap between owner frames that cuts a new segment in the index.
    owner_gap_s: float = DEFAULT_CAPTURE_OWNER_GAP_S

    def as_dict(self) -> dict[str, object]:
        return {
            "enabled": self.enabled,
            "dir": self.dir,
            "max_minutes": self.max_minutes,
            "owner_gap_s": self.owner_gap_s,
        }


@dataclass(frozen=True)
class VoiceIdentityConfig:
    """Whether an unrecognised voice may COMMAND the robot (card F1-SI).

    THE DEFECT THIS EXISTS BECAUSE OF
    ---------------------------------
    A television commanded the robot twice, across two owner sessions, on
    2026-08-20. Acoustic echo cancellation does not defend against that — it
    cancels the robot's own loudspeaker, and a TV is an independent source in
    the room — and the transcript-level Unicode-script check only catches the
    cross-language case. The defence has to be about who is speaking.

    THE ONE THING THIS BLOCK CANNOT DO
    ----------------------------------
    It cannot gate the emergency latch. There is no key here that reaches it,
    because ``realtime/voice_identity.gates_kind`` answers the emergency class
    before it looks at any configuration at all. Anyone in the room may stop the
    dog; only commands need the owner's voice.

    DEFAULT ON, FAIL CLOSED
    -----------------------
    ``enabled: true`` is the default. With no enrolled profile the gate reports
    ``verify_disabled`` and refuses non-emergency authority; missing identity
    evidence never promotes an arbitrary speaker to owner. The switch that
    enables owner commands is the existence of a valid enrolled profile. The
    emergency latch remains outside this block and available to anyone.
    """

    enabled: bool = True
    #: Cosine at or above which a turn is the owner. Config, per decision 1.
    threshold: float = DEFAULT_VOICE_THRESHOLD
    #: Absolute path to the enrolled profile. Empty ⇒ beside the realtime config
    #: (``voice_identity.default_profile_path``), which is outside the repo.
    profile: str = ""
    #: Absolute path to the embedding model. Empty ⇒ the vendored
    #: ``models/speaker_id/`` copy named by the provenance lock.
    model: str = ""
    #: Buffered speech that triggers the PROVISIONAL verify of a turn. Raised
    #: from 0.6 s by measurement: at 0.6 s the FAR/FRR run over this host's own
    #: gold set returned FRR 38.5 % (FAR 0 %), because a fragment of a sentence
    #: is not the sentence. See ``voice_identity.DEFAULT_MIN_UTTERANCE_S``.
    min_utterance_s: float = 1.2
    #: Added-latency budget in milliseconds. Measured and counted, not enforced
    #: as a timeout: half an embedding is worse than a slow one.
    budget_ms: float = 50.0
    #: How often a refusal may become a SPOKEN sentence. Every refusal is
    #: counted and logged regardless; this rate-limits only the narration.
    narration_interval_s: float = 60.0
    #: Open the XVF3800 vendor control interface and read ``DOA_VALUE``.
    #: Default OFF: on this host the read path is blocked by a udev permission
    #: only the owner can grant, and a feature that logs an Errno 13 on every
    #: turn is worse than one that is off and says so.
    doa: bool = False
    #: ``[start_deg, end_deg]`` the television sits in, or ``None``. A turn from
    #: inside this sector is refused UNLESS the embedding verify passes.
    rejected_sector: tuple[float, float] | None = None

    def as_dict(self) -> dict[str, object]:
        return {
            "enabled": self.enabled,
            "threshold": self.threshold,
            # A path, not a secret — and knowing WHERE the profile is expected
            # is exactly what an operator debugging "why is verify off" needs.
            "profile": self.profile,
            "model": self.model,
            "min_utterance_s": self.min_utterance_s,
            "budget_ms": self.budget_ms,
            "narration_interval_s": self.narration_interval_s,
            "doa": self.doa,
            "rejected_sector": (
                None if self.rejected_sector is None else list(self.rejected_sector)
            ),
        }


@dataclass(frozen=True)
class SpeechActsConfig:
    """Does the lane narrate from the receipt-typed contract? (card C5).

    WHAT THE SWITCH ACTUALLY SWITCHES
    ---------------------------------
    OFF (the default, and the meaning of an absent block): nothing changes.
    ``narrate_event`` sends the sentence its caller composed, exactly as it has
    since card R4-lite, and :mod:`parcel_robot.realtime.speech_acts` is inert
    product code with tests and no callers.

    ON: a receipt is mapped to a typed speech act, the act is rendered by its
    one template, and THAT is the sentence that goes up — the facts come from
    the contract instead of from a model's reading of a prompt.

    DEFAULT OFF, AND WHY THAT IS NOT TIMIDITY
    -----------------------------------------
    MB-2 measured the contract at grounding 1.000 / coverage 0.9688 / 0 invented
    actions against a hosted model's 0.61-0.73 with 45 invented-action flags, so
    the evidence points one way. What it did NOT measure is a human preferring
    the result: its naturalness row is UNMEASURED (the judge picked whichever
    option was shown first, p = 0.002). A switch that changes every sentence the
    robot says about itself, on evidence that is decisive about facts and silent
    about whether it is pleasant to live with, is a switch the owner flips.
    """

    enabled: bool = False

    def as_dict(self) -> dict[str, object]:
        return {"enabled": self.enabled}


@dataclass(frozen=True)
class RealtimeConfig:
    """The lane's entire configuration surface."""

    enabled: bool = False
    mode: str = MODE_TEXT
    #: Free-text personality, told to the model verbatim. Empty means "use the
    #: preset profile in :attr:`si_profile`", which is the pre-2026-08-18
    #: behaviour and renders byte-identically.
    persona: str = ""
    #: Preset personality id, used only when :attr:`persona` is empty.
    si_profile: str = ""
    model: str = "gpt-realtime-2.1"
    voice: str = "cedar"
    stall_timeout_s: float = 8.0
    session_max_s: float = 3600.0
    #: Card R16. Seconds of CONVERSATIONAL silence after which the lane hangs up
    #: rather than keeping a paid session (and its hourly rollovers) alive for
    #: nobody. Owner session 1 left a session open all night — seven
    #: ``[session rollover]`` rows between 06:23 and 12:23 with not one turn
    #: between them — because nothing in the product had an opinion about a lane
    #: that is not being talked to. Negatives and non-finite values are still
    #: refused, and the default is unchanged.
    #:
    #: CARD P0-B CHANGED ONE VALUE'S MEANING. ``0`` used to be a refusal, on the
    #: reasoning that a silent off switch on a billing session is worse than a
    #: loud number. Zero is now accepted and means NEVER IDLE-CLOSE — because it
    #: is not silent: it is a value an operator wrote down, it is echoed in
    #: ``/api/state`` and in the example config, and the two bounds that make an
    #: unattended session finite (``session_max_s`` and ``monthly_budget_usd``)
    #: are untouched and still refuse zero. What it buys is the prototype
    #: directive: a companion lane that stays live while the owner is around
    #: instead of hanging up mid-afternoon and needing to be spoken to twice.
    idle_close_after_s: float = 600.0
    monthly_budget_usd: float = 25.0
    #: Card P0-B. Motion tools a SYSTEM-initiated response may still run — the
    #: proactive-companion unlock. Empty (the default) is card R11's behaviour:
    #: no motion at all unless the owner asked. See
    #: :data:`PROACTIVE_MOTION_ALLOWED` for what may go in it and why the travel
    #: tools may not.
    proactive_motion_tools: tuple[str, ...] = ()
    #: Card P0-B. ``refuse`` (default, unchanged behaviour) or ``ask``.
    unknown_place: str = UNKNOWN_PLACE_REFUSE
    #: Card P0-B. Run the deterministic explicit-affect grammar on hosted
    #: transcripts the ingress did not claim, so "I'm feeling sad" reaches the
    #: persona's ``affect_actions`` gesture on the HOSTED lane too and not only
    #: on the legacy one. Default off: it proposes a body movement from a
    #: sentence, which is exactly the class of thing that gets a switch.
    hosted_affect: bool = False
    #: Card R11. The owner's control over robot-initiated hosted queries.
    whisperer: WhispererConfig = WhispererConfig()
    #: Card R17. Session audio capture. Default OFF; the owner opts in.
    capture: CaptureConfig = CaptureConfig()
    #: Card F1-SI. Speaker verification for command arming. Inert until an
    #: owner profile is enrolled; never reaches the emergency latch.
    voice_identity: VoiceIdentityConfig = VoiceIdentityConfig()
    #: Card TURN-1. WHEN THE OWNER'S TURN ENDS. The default renders the exact
    #: ``{"type": "server_vad"}`` the lane sent before this key existed, so a
    #: config that never mentions endpointing is byte-identical on the wire.
    #: ``default_factory`` rather than a bare call: :class:`TurnDetection` lives
    #: in ``protocol.py``, so from here ruff cannot see that it is frozen and
    #: reads the call as a mutable default (RUF009). Same shape of fix, and the
    #: same reason, as the one card GATE-0 applies at ``protocol.py:415``.
    turn_detection: TurnDetection = field(default_factory=TurnDetection)
    #: Card C5. Narrate from the receipt-typed contract rather than from
    #: whatever text the caller composed. Default OFF; see
    #: :class:`SpeechActsConfig` for what OFF means on the wire (nothing).
    speech_acts: SpeechActsConfig = SpeechActsConfig()
    source: str = "absent"

    @property
    def audio(self) -> bool:
        """True when the browser mic/speaker gateway should be constructed."""

        return self.mode == MODE_AUDIO

    @property
    def persona_text(self) -> str | None:
        """What to hand ``render_system_instruction``. ``None`` ⇒ preset profile."""

        return self.persona or None

    @property
    def present(self) -> bool:
        """Did a config file actually exist? (``enabled`` can still be false.)"""

        return self.source != "absent"

    @property
    def idle_close_enabled(self) -> bool:
        """Card P0-B. False when ``idle_close_after_s: 0`` said never hang up.

        A property rather than a comparison spelled out at the one call site, so
        the meaning of the sentinel lives beside the key it belongs to and a
        second reader cannot invent a different one.
        """

        return self.idle_close_after_s > IDLE_CLOSE_NEVER

    def as_dict(self) -> dict[str, object]:
        return {
            "enabled": self.enabled,
            "mode": self.mode,
            # The persona is prose an operator wrote; it is not a credential and
            # it is exactly what a reader of /api/state needs in order to know
            # which personality produced a transcript.
            "persona": self.persona,
            "si_profile": self.si_profile,
            "model": self.model,
            "voice": self.voice,
            "stall_timeout_s": self.stall_timeout_s,
            "session_max_s": self.session_max_s,
            "idle_close_after_s": self.idle_close_after_s,
            "monthly_budget_usd": self.monthly_budget_usd,
            # Card P0-B. A list, not a tuple: this dict is JSON-serialized into
            # /api/state, and an operator reading it must be able to see that
            # the proactive unlock is on without going to the yaml.
            "proactive_motion_tools": list(self.proactive_motion_tools),
            "unknown_place": self.unknown_place,
            "hosted_affect": self.hosted_affect,
            "whisperer": self.whisperer.as_dict(),
            "capture": self.capture.as_dict(),
            "voice_identity": self.voice_identity.as_dict(),
            # Card TURN-1. Exactly the object that goes on the wire, so an
            # operator reading /api/state can see the endpointing the session is
            # actually running under rather than inferring it from the yaml.
            "turn_detection": self.turn_detection.as_dict(),
            # Card C5 DELIBERATELY DOES NOT RENDER ``speech_acts`` HERE.
            # ``/api/state``'s key set is a pre-registered row of card TURN-1
            # ("+1 key, 0 changed", tests/test_turn1_endpointing.py:302) which
            # this card does not own and may not re-pin. Nothing reads the flag
            # in wave A, so a key in the panel's JSON would report a switch that
            # cannot be flipped while churning a frozen row to say it. The
            # WAVE-B install — the one that makes the flag mean something — adds
            # the row here and re-pins TURN-1's assertion with its reviewer,
            # because an operator must be able to see a live switch.
            "source": self.source,
        }


def _boolean(mapping: Mapping[str, Any], key: str, default: bool) -> bool:
    value = mapping.get(key, default)
    if isinstance(value, bool):
        return value
    raise RealtimeConfigError(f"realtime.{key} must be a boolean, got {value!r}")


def _text(mapping: Mapping[str, Any], key: str, default: str) -> str:
    value = mapping.get(key, default)
    if isinstance(value, str) and value.strip():
        return value.strip()
    raise RealtimeConfigError(f"realtime.{key} must be a non-empty string, got {value!r}")


def _mode(mapping: Mapping[str, Any]) -> str:
    """``text`` or ``audio``. A typo is a refusal, exactly like every other key.

    Fail-closed in the direction that matters: an unreadable mode does NOT fall
    back to ``audio`` (which would open a websocket listener and ask for a
    microphone), and it does not fall back silently to ``text`` either. It
    raises, because a config nobody can read is not a config.
    """

    value = _text(mapping, "mode", MODE_TEXT).lower()
    if value not in ALLOWED_MODES:
        raise RealtimeConfigError(
            f"realtime.mode must be one of {', '.join(sorted(ALLOWED_MODES))}, got {value!r}"
        )
    return value


def _optional_text(mapping: Mapping[str, Any], key: str, *, max_chars: int = 0) -> str:
    """An absent key is ``""``. A PRESENT key must say something real.

    The asymmetry is the point (owner directive, 2026-08-18): absent means "use
    the default", which is a decision; present-but-blank means the operator
    tried to say something and it did not land, which is a mistake. Silently
    treating the second as the first is how a robot ends up running a
    personality nobody chose.
    """

    if key not in mapping:
        return ""
    value = mapping.get(key)
    if not isinstance(value, str) or not value.strip():
        raise RealtimeConfigError(
            f"realtime.{key} is present but not a non-empty string, got {value!r}. "
            f"Remove the key to use the default; do not leave it blank."
        )
    text = " ".join(value.split())
    if max_chars and len(text) > max_chars:
        raise RealtimeConfigError(
            f"realtime.{key} is {len(text)} characters; the limit is {max_chars}. "
            f"It is re-sent on every reconnect and billed as input every session."
        )
    return text


def _positive(mapping: Mapping[str, Any], key: str, default: float) -> float:
    """A finite number greater than zero. ``.inf`` is a refusal, not a licence.

    Card R25, closing card R23's registered gap. ``not number > 0.0`` refused
    NaN by accident of IEEE comparison and accepted ``+inf`` by the same
    accident; ``math.isfinite`` refuses both on purpose, and says which.
    """

    value = mapping.get(key, default)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise RealtimeConfigError(f"realtime.{key} must be a number, got {value!r}")
    number = float(value)
    if not math.isfinite(number):
        raise RealtimeConfigError(
            f"realtime.{key} must be a finite number, got {number}. A non-finite "
            f"value here is not 'no limit' — it is a limit that permits every "
            f"finite value, which for monthly_budget_usd is an unlimited bill "
            f"and for session_max_s is a session that never rolls over."
        )
    if not number > 0.0:
        raise RealtimeConfigError(f"realtime.{key} must be greater than zero, got {number}")
    return number


def _idle_close_after_s(mapping: Mapping[str, Any], default: float) -> float:
    """Card P0-B, deliverable 3. Seconds, or ``0`` meaning NEVER hang up.

    Everything :func:`_positive` refuses is still refused here — a non-number, a
    boolean, a negative, ``.inf``, ``nan`` — and for the same reasons. The one
    admitted addition is exact zero, which no longer reads as "a cap of nothing"
    (that would close the session on the first idle tick, which is what the old
    comparison in ``lane._idle_due`` would literally have done) but as the
    documented sentinel :data:`IDLE_CLOSE_NEVER`.

    Why this is not the silent off switch R16 refused: it is not silent. The
    value is written by hand, echoed by ``as_dict`` into ``/api/state``, and
    named in the shipped example. And it removes only ONE of the three bounds on
    an unattended session — ``session_max_s`` still rolls the socket over and
    ``monthly_budget_usd`` still stops the robot starting billed exchanges, and
    both of them still refuse zero.
    """

    key = "idle_close_after_s"
    value = mapping.get(key, default)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise RealtimeConfigError(f"realtime.{key} must be a number, got {value!r}")
    number = float(value)
    if not math.isfinite(number):
        raise RealtimeConfigError(
            f"realtime.{key} must be a finite number, got {number}. Write 0 for "
            f"'never hang up' — a sentinel that is visible in /api/state — "
            f"rather than a non-finite value that also permits every finite one."
        )
    if number < 0.0:
        raise RealtimeConfigError(
            f"realtime.{key} must not be negative, got {number}. Zero means "
            f"never idle-close; a negative is a typo for it."
        )
    return number


def _proactive_motion_tools(mapping: Mapping[str, Any]) -> tuple[str, ...]:
    """Card P0-B, deliverable 1. A closed list of low-risk tools, or nothing.

    Three refusals, each of them a thing an operator could plausibly write:

    * a **travel tool** (:data:`PROACTIVE_MOTION_REFUSED`). This is the one that
      matters. ``navigate_to`` from a reply the robot started IS bench finding
      C1 — the dog driving off because a telemetry item made it talk to itself —
      and no amount of config may buy it back. Refused by name, with the reason.
    * an **unknown name**, because a mistyped ``play_guesture`` that silently did
      nothing would look exactly like the feature being broken.
    * a **non-list, or a list holding something that is not a string**.

    Duplicates are collapsed and order is not significant: this is a membership
    test at dispatch, not a sequence.
    """

    key = "proactive_motion_tools"
    if key not in mapping:
        return ()
    value = mapping.get(key)
    if value is None:
        return ()
    if isinstance(value, (str, bytes)) or not isinstance(value, (list, tuple)):
        raise RealtimeConfigError(
            f"realtime.{key} must be a list of tool names, got {value!r}. "
            f"Allowed entries: {', '.join(PROACTIVE_MOTION_ALLOWED)}."
        )
    names: list[str] = []
    for item in value:
        if not isinstance(item, str) or not item.strip():
            raise RealtimeConfigError(
                f"realtime.{key} holds a non-name: {item!r}"
            )
        name = item.strip()
        if name in PROACTIVE_MOTION_REFUSED:
            raise RealtimeConfigError(
                f"realtime.{key} may not contain {name!r}: it commits the robot "
                f"to travel, and a trip the owner never asked for is the defect "
                f"the system-initiated gate exists to prevent (bench_navmodel.md "
                f"§4, finding C1). Allowed entries: "
                f"{', '.join(PROACTIVE_MOTION_ALLOWED)}."
            )
        if name not in PROACTIVE_MOTION_ALLOWED:
            raise RealtimeConfigError(
                f"realtime.{key} names {name!r}, which is not a tool this robot "
                f"will run proactively. Allowed entries: "
                f"{', '.join(PROACTIVE_MOTION_ALLOWED)}."
            )
        if name not in names:
            names.append(name)
    return tuple(names)


def _unknown_place(mapping: Mapping[str, Any]) -> str:
    """Card P0-B, deliverable 2. ``refuse`` (default) or ``ask``."""

    key = "unknown_place"
    value = mapping.get(key, UNKNOWN_PLACE_REFUSE)
    if not isinstance(value, str) or not value.strip():
        raise RealtimeConfigError(
            f"realtime.{key} must be one of "
            f"{', '.join(sorted(ALLOWED_UNKNOWN_PLACE_MODES))}, got {value!r}"
        )
    clean = value.strip().lower()
    if clean not in ALLOWED_UNKNOWN_PLACE_MODES:
        raise RealtimeConfigError(
            f"realtime.{key} must be one of "
            f"{', '.join(sorted(ALLOWED_UNKNOWN_PLACE_MODES))}, got {value!r}"
        )
    return clean


def _whole_number(mapping: Mapping[str, Any], key: str, default: int) -> int:
    """A positive integer. ``True`` is not 1 here, and 2.5 updates is not a cap."""

    value = mapping.get(key, default)
    if isinstance(value, bool) or not isinstance(value, int):
        raise RealtimeConfigError(
            f"realtime.whisperer.{key} must be a whole number, got {value!r}"
        )
    if value < 1:
        raise RealtimeConfigError(
            f"realtime.whisperer.{key} must be at least 1, got {value}. "
            f"Use 'enabled: false' to turn state updates off; a cap of zero "
            f"would be a silent off switch."
        )
    return int(value)


def _non_negative(mapping: Mapping[str, Any], key: str, default: float) -> float:
    """Seconds. Zero is meaningful ("no extra spacing"); negative is a typo.

    Card R25: non-finite is a typo too. An infinite ``min_gap_s`` is a
    whisperer that forwards its first fact and then never speaks again — a
    silent off switch, which this block already refuses to have.
    """

    value = mapping.get(key, default)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise RealtimeConfigError(
            f"realtime.whisperer.{key} must be a number, got {value!r}"
        )
    number = float(value)
    if not math.isfinite(number):
        raise RealtimeConfigError(
            f"realtime.whisperer.{key} must be a finite number, got {number}"
        )
    if number < 0.0:
        raise RealtimeConfigError(
            f"realtime.whisperer.{key} must not be negative, got {number}"
        )
    return number


def whisperer_config_from_mapping(mapping: Mapping[str, Any] | None) -> WhispererConfig:
    """Validate the nested ``whisperer:`` block. Absent ⇒ documented defaults.

    Fail-closed in the same shape as the outer loader: an unknown key is a typo
    and a typo is a refusal, because a mistyped ``max_updates_per_minuet`` that
    silently read as the default would let a config that meant to be quiet bill
    at the default rate forever.
    """

    if mapping is None:
        return WhispererConfig()
    if not isinstance(mapping, Mapping):
        raise RealtimeConfigError(
            f"realtime.whisperer must be a mapping, got {type(mapping).__name__}"
        )
    unknown = sorted(str(key) for key in mapping if str(key) not in WHISPERER_ALLOWED_KEYS)
    if unknown:
        raise RealtimeConfigError(
            f"unknown realtime.whisperer key(s): {', '.join(unknown)}; "
            f"allowed: {', '.join(sorted(WHISPERER_ALLOWED_KEYS))}"
        )
    enabled = mapping.get("enabled", True)
    if not isinstance(enabled, bool):
        raise RealtimeConfigError(
            f"realtime.whisperer.enabled must be a boolean, got {enabled!r}"
        )
    return WhispererConfig(
        enabled=enabled,
        max_updates_per_minute=_whole_number(mapping, "max_updates_per_minute", 2),
        min_gap_s=_non_negative(mapping, "min_gap_s", 15.0),
        window_s=_whisperer_window(mapping),
        owner_events=owner_events_config_from_mapping(mapping.get("owner_events")),
        # Card CURIO-1.
        curiosity=curiosity_config_from_mapping(mapping.get("curiosity")),
    )


def owner_events_config_from_mapping(
    mapping: Mapping[str, Any] | None,
) -> OwnerEventsConfig:
    """Validate ``whisperer.owner_events:``. Absent ⇒ the documented defaults (off).

    Card P2-B. Every number here is a duration or a probability and every one of
    them is refused when it is non-finite, exactly as card R25 taught the rest of
    this file: an infinite ``absence_s`` is a dog that never greets you again,
    which is a silent off switch wearing a tuning value's clothes.
    """

    if mapping is None:
        return OwnerEventsConfig()
    if not isinstance(mapping, Mapping):
        raise RealtimeConfigError(
            "realtime.whisperer.owner_events must be a mapping, got "
            f"{type(mapping).__name__}"
        )
    unknown = sorted(str(key) for key in mapping if str(key) not in OWNER_EVENTS_ALLOWED_KEYS)
    if unknown:
        raise RealtimeConfigError(
            f"unknown realtime.whisperer.owner_events key(s): {', '.join(unknown)}; "
            f"allowed: {', '.join(sorted(OWNER_EVENTS_ALLOWED_KEYS))}"
        )
    return OwnerEventsConfig(
        enabled=_owner_events_flag(mapping, "enabled", False),
        min_confidence=_owner_events_probability(mapping, "min_confidence", 0.3),
        appear_debounce_s=_owner_events_seconds(
            mapping, "appear_debounce_s", 2.0, positive=True
        ),
        absence_s=_owner_events_seconds(mapping, "absence_s", 60.0, positive=False),
        long_absence_h=_owner_events_seconds(
            mapping, "long_absence_h", 3.0, positive=True
        ),
        greeting_interval_s=_owner_events_seconds(
            mapping, "greeting_interval_s", 900.0, positive=False
        ),
        question_of_the_day=_owner_events_flag(mapping, "question_of_the_day", True),
    )


def _owner_events_flag(mapping: Mapping[str, Any], key: str, default: bool) -> bool:
    value = mapping.get(key, default)
    if not isinstance(value, bool):
        raise RealtimeConfigError(
            f"realtime.whisperer.owner_events.{key} must be a boolean, got {value!r}"
        )
    return value


def _owner_events_number(mapping: Mapping[str, Any], key: str, default: float) -> float:
    value = mapping.get(key, default)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise RealtimeConfigError(
            f"realtime.whisperer.owner_events.{key} must be a number, got {value!r}"
        )
    number = float(value)
    if not math.isfinite(number):
        raise RealtimeConfigError(
            f"realtime.whisperer.owner_events.{key} must be a finite number, got {number}"
        )
    return number


def _owner_events_seconds(
    mapping: Mapping[str, Any], key: str, default: float, *, positive: bool
) -> float:
    number = _owner_events_number(mapping, key, default)
    if positive and not number > 0.0:
        raise RealtimeConfigError(
            f"realtime.whisperer.owner_events.{key} must be greater than zero, got "
            f"{number}. Use 'enabled: false' to turn owner events off, which is "
            f"visible in the config."
        )
    if not positive and number < 0.0:
        raise RealtimeConfigError(
            f"realtime.whisperer.owner_events.{key} must not be negative, got {number}"
        )
    return number


def _owner_events_probability(
    mapping: Mapping[str, Any], key: str, default: float
) -> float:
    number = _owner_events_number(mapping, key, default)
    if not 0.0 <= number <= 1.0:
        raise RealtimeConfigError(
            f"realtime.whisperer.owner_events.{key} is a track confidence and must "
            f"be between 0.0 and 1.0, got {number}"
        )
    return number


# ============================ card CURIO-1: the chatter block's validator ====
def curiosity_config_from_mapping(
    mapping: Mapping[str, Any] | None,
) -> CuriosityConfig:
    """Validate ``whisperer.curiosity:``. Absent ⇒ the documented defaults (off).

    Every number here is refused when it is non-finite, for card R25's reason
    applied to a new block: an infinite ``mean_gap_s`` is a dog that never
    remarks on anything again — a silent off switch wearing a tuning value's
    clothes — and ``enabled: false`` is the off switch that is visible in the
    config.
    """

    if mapping is None:
        return CuriosityConfig()
    if not isinstance(mapping, Mapping):
        raise RealtimeConfigError(
            "realtime.whisperer.curiosity must be a mapping, got "
            f"{type(mapping).__name__}"
        )
    unknown = sorted(str(key) for key in mapping if str(key) not in CURIOSITY_ALLOWED_KEYS)
    if unknown:
        raise RealtimeConfigError(
            f"unknown realtime.whisperer.curiosity key(s): {', '.join(unknown)}; "
            f"allowed: {', '.join(sorted(CURIOSITY_ALLOWED_KEYS))}"
        )
    gesture = mapping.get("gesture_when_capped", "curious_look")
    if not isinstance(gesture, str):
        raise RealtimeConfigError(
            "realtime.whisperer.curiosity.gesture_when_capped must be a string "
            f"(an emote name, or '' for none), got {gesture!r}"
        )
    return CuriosityConfig(
        enabled=_curiosity_flag(mapping, "enabled", False),
        mean_gap_s=_curiosity_seconds(mapping, "mean_gap_s", 360.0, positive=True),
        stimulus_min_gap_s=_curiosity_seconds(
            mapping, "stimulus_min_gap_s", 25.0, positive=False
        ),
        min_gap_floor_s=_curiosity_seconds(
            mapping, "min_gap_floor_s", 20.0, positive=False
        ),
        quiet_s=_curiosity_seconds(mapping, "quiet_s", 90.0, positive=False),
        require_owner_present=_curiosity_flag(mapping, "require_owner_present", True),
        night_quiet=_curiosity_flag(mapping, "night_quiet", True),
        farewell=_curiosity_flag(mapping, "farewell", True),
        farewell_after_s=_curiosity_seconds(
            mapping, "farewell_after_s", 45.0, positive=True
        ),
        gesture_when_capped=gesture.strip(),
    )


def _curiosity_flag(mapping: Mapping[str, Any], key: str, default: bool) -> bool:
    value = mapping.get(key, default)
    if not isinstance(value, bool):
        raise RealtimeConfigError(
            f"realtime.whisperer.curiosity.{key} must be a boolean, got {value!r}"
        )
    return value


def _curiosity_seconds(
    mapping: Mapping[str, Any], key: str, default: float, *, positive: bool
) -> float:
    value = mapping.get(key, default)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise RealtimeConfigError(
            f"realtime.whisperer.curiosity.{key} must be a number, got {value!r}"
        )
    number = float(value)
    if not math.isfinite(number):
        raise RealtimeConfigError(
            f"realtime.whisperer.curiosity.{key} must be a finite number, got {number}"
        )
    if positive and not number > 0.0:
        raise RealtimeConfigError(
            f"realtime.whisperer.curiosity.{key} must be greater than zero, got "
            f"{number}. Use 'enabled: false' to turn curiosity off, which is "
            f"visible in the config."
        )
    if not positive and number < 0.0:
        raise RealtimeConfigError(
            f"realtime.whisperer.curiosity.{key} must not be negative, got {number}"
        )
    return number


# ======================== END card CURIO-1 (the chatter block's validator) ===


def _whisperer_window(mapping: Mapping[str, Any]) -> float:
    """Card P0-B, deliverable 4. The cap's rolling window, in seconds.

    Strictly positive, unlike ``min_gap_s``. A window of zero would make
    ``_spent`` count nothing at all and the cap would never bite again — the
    silent removal of the owner's cost control, wearing the costume of a tuning
    value. ``enabled: false`` is the off switch for narration and it is visible.
    """

    key = "window_s"
    value = mapping.get(key, DEFAULT_WHISPERER_WINDOW_S)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise RealtimeConfigError(
            f"realtime.whisperer.{key} must be a number, got {value!r}"
        )
    number = float(value)
    if not math.isfinite(number):
        raise RealtimeConfigError(
            f"realtime.whisperer.{key} must be a finite number, got {number}"
        )
    if not number > 0.0:
        raise RealtimeConfigError(
            f"realtime.whisperer.{key} must be greater than zero, got {number}. "
            f"A window of zero counts nothing and would remove the cap silently; "
            f"use 'enabled: false' to stop narration, which is visible."
        )
    return number


def resolve_capture_dir(directory: str) -> Path:
    """Absolute recording root for a configured ``capture.dir``. Refuses ``evals/``.

    Relative paths resolve against the repo root (``parcel_roots()[0]``), which
    is the same base every other repo-relative asset uses, so ``recordings``
    means one place and not "wherever the process happened to be started".
    That matters more than it looks: the voice-corpus scoring run of
    2026-08-20 deposited its artifacts at a DOUBLED repo-relative prefix
    because a collector resolved a repo-relative path against a cwd that was
    already inside the repo. A capture root is chosen once, at config load, by
    a function that does not consult the cwd.

    The refusal is the other half. ``evals/`` holds reviewed, frozen fixtures
    that runs are scored *against*; a live microphone tee appending into that
    tree could rewrite the record while it is being graded. Nothing about that
    is recoverable after the fact, so it is a load-time refusal rather than a
    runtime warning.
    """

    text = str(directory).strip()
    if not text:
        raise RealtimeConfigError("realtime.capture.dir must be a non-empty string")
    candidate = Path(text).expanduser()
    if not candidate.is_absolute():
        roots = parcel_roots()
        base = roots[0] if roots else Path.cwd()
        candidate = base / candidate
    resolved = Path(os.path.normpath(str(candidate)))
    for root in (*parcel_roots(), Path.cwd()):
        forbidden = Path(os.path.normpath(str(root / _FORBIDDEN_CAPTURE_PARENT)))
        if resolved == forbidden or forbidden in resolved.parents:
            raise RealtimeConfigError(
                f"realtime.capture.dir resolves to {resolved}, which is inside "
                f"{forbidden}. Recordings must never be written into the eval "
                f"tree: those fixtures are the record a run is scored against."
            )
    return resolved


def turn_detection_from_mapping(mapping: Mapping[str, Any] | None) -> TurnDetection:
    """Validate the nested ``turn_detection:`` block. Card TURN-1.

    ABSENT ⇒ ``TurnDetection()`` ⇒ ``{"type": "server_vad"}`` on the wire, which
    is byte-for-byte what this lane sent before the key existed. That is the
    contract the card names first and the one that is seeded RED: a knob whose
    default changes anything is not a knob, it is a behaviour change wearing one.

    Type checking happens HERE and range/enum/cross-key checking happens in
    :class:`~parcel_robot.realtime.protocol.TurnDetection`. The split is not
    arbitrary: YAML can hand this function a list where a number belongs, and a
    ``TypeError`` from ``int()`` inside a frozen dataclass is not a sentence an
    operator can act on. Everything the wire object refuses is re-raised as a
    :class:`RealtimeConfigError` so one ``except`` in the loader still catches
    every way a config file can be wrong.
    """

    if mapping is None:
        return TurnDetection()
    if not isinstance(mapping, Mapping):
        raise RealtimeConfigError(
            f"realtime.turn_detection must be a mapping, got {type(mapping).__name__}"
        )
    unknown = sorted(str(key) for key in mapping if str(key) not in TURN_DETECTION_ALLOWED_KEYS)
    if unknown:
        raise RealtimeConfigError(
            f"unknown realtime.turn_detection key(s): {', '.join(unknown)}; "
            f"allowed: {', '.join(sorted(TURN_DETECTION_ALLOWED_KEYS))}"
        )
    kind = mapping.get("type", TURN_DETECTION_TYPES[0])
    if not isinstance(kind, str) or kind not in TURN_DETECTION_TYPES:
        raise RealtimeConfigError(
            f"realtime.turn_detection.type must be one of "
            f"{', '.join(TURN_DETECTION_TYPES)}; got {kind!r}"
        )
    eagerness = mapping.get("eagerness")
    if eagerness is not None and (
        not isinstance(eagerness, str) or eagerness not in TURN_DETECTION_EAGERNESS
    ):
        raise RealtimeConfigError(
            f"realtime.turn_detection.eagerness must be one of "
            f"{', '.join(TURN_DETECTION_EAGERNESS)}; got {eagerness!r}"
        )
    try:
        return TurnDetection(
            type=kind,
            threshold=_turn_number(mapping, "threshold", whole=False),
            prefix_padding_ms=_turn_number(mapping, "prefix_padding_ms", whole=True),
            silence_duration_ms=_turn_number(mapping, "silence_duration_ms", whole=True),
            eagerness=eagerness,
            interrupt_response=_turn_flag(mapping, "interrupt_response"),
            create_response=_turn_flag(mapping, "create_response"),
        )
    except RealtimeProtocolError as error:
        raise RealtimeConfigError(f"realtime.{error}") from error


def _turn_number(mapping: Mapping[str, Any], key: str, *, whole: bool) -> Any:
    """One optional number from the ``turn_detection:`` block. Card TURN-1.

    ``None`` (the key is absent) is returned unchanged and is what keeps the
    payload identical. Booleans are refused before the ``isinstance(..., int)``
    test can accept them, and non-finite values are refused for the same reason
    card R25 refuses them everywhere else in this file: ``.inf`` spelled in YAML
    is a bound that permits everything.
    """

    if key not in mapping:
        return None
    value = mapping[key]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise RealtimeConfigError(
            f"realtime.turn_detection.{key} must be a number, got {value!r}"
        )
    number = float(value)
    if not math.isfinite(number):
        raise RealtimeConfigError(
            f"realtime.turn_detection.{key} must be a finite number, got {number}"
        )
    if not whole:
        return number
    if number != int(number):
        raise RealtimeConfigError(
            f"realtime.turn_detection.{key} is a whole number of milliseconds, got {number}"
        )
    return int(number)


def _turn_flag(mapping: Mapping[str, Any], key: str) -> bool | None:
    """One optional boolean from the ``turn_detection:`` block. Card TURN-1."""

    if key not in mapping:
        return None
    value = mapping[key]
    if not isinstance(value, bool):
        raise RealtimeConfigError(
            f"realtime.turn_detection.{key} must be a boolean, got {value!r}"
        )
    return value


def capture_config_from_mapping(mapping: Mapping[str, Any] | None) -> CaptureConfig:
    """Validate the nested ``capture:`` block. Absent ⇒ capture is OFF."""

    if mapping is None:
        return CaptureConfig()
    if not isinstance(mapping, Mapping):
        raise RealtimeConfigError(
            f"realtime.capture must be a mapping, got {type(mapping).__name__}"
        )
    unknown = sorted(str(key) for key in mapping if str(key) not in CAPTURE_ALLOWED_KEYS)
    if unknown:
        raise RealtimeConfigError(
            f"unknown realtime.capture key(s): {', '.join(unknown)}; "
            f"allowed: {', '.join(sorted(CAPTURE_ALLOWED_KEYS))}"
        )
    enabled = mapping.get("enabled", False)
    if not isinstance(enabled, bool):
        raise RealtimeConfigError(
            f"realtime.capture.enabled must be a boolean, got {enabled!r}"
        )
    directory = mapping.get("dir", DEFAULT_CAPTURE_DIR)
    if not isinstance(directory, str) or not directory.strip():
        raise RealtimeConfigError(
            f"realtime.capture.dir must be a non-empty string, got {directory!r}"
        )
    # Resolve NOW, at load, so an evals/ target is a refusal the operator reads
    # before a microphone ever opens rather than an exception mid-conversation.
    resolve_capture_dir(directory)
    max_minutes = mapping.get("max_minutes", DEFAULT_CAPTURE_MAX_MINUTES)
    if isinstance(max_minutes, bool) or not isinstance(max_minutes, (int, float)):
        raise RealtimeConfigError(
            f"realtime.capture.max_minutes must be a number, got {max_minutes!r}"
        )
    if not float(max_minutes) > 0.0:
        raise RealtimeConfigError(
            f"realtime.capture.max_minutes must be greater than zero, got "
            f"{float(max_minutes)}. Use 'enabled: false' to turn capture off; a "
            f"cap of zero would be a silent off switch on a feature that writes "
            f"a household microphone to disk."
        )
    gap = mapping.get("owner_gap_s", DEFAULT_CAPTURE_OWNER_GAP_S)
    if isinstance(gap, bool) or not isinstance(gap, (int, float)):
        raise RealtimeConfigError(
            f"realtime.capture.owner_gap_s must be a number, got {gap!r}"
        )
    if float(gap) < 0.0:
        raise RealtimeConfigError(
            f"realtime.capture.owner_gap_s must not be negative, got {float(gap)}"
        )
    return CaptureConfig(
        enabled=enabled,
        dir=directory.strip(),
        max_minutes=float(max_minutes),
        owner_gap_s=float(gap),
    )


def _sector(value: Any) -> tuple[float, float] | None:
    """Validate ``rejected_sector: [start, end]``. Absent / null ⇒ ``None``.

    Degrees, azimuth, wrap allowed: ``[350, 10]`` is the twenty degrees around
    due north. Both ends are required — a one-element sector is a half-written
    thought, and guessing which half was meant would point the prefilter at a
    direction the owner never named.
    """

    if value is None:
        return None
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        raise RealtimeConfigError(
            "realtime.voice_identity.rejected_sector must be a two-element "
            f"[start_deg, end_deg] list, got {value!r}"
        )
    numbers: list[float] = []
    for item in value:
        if isinstance(item, bool) or not isinstance(item, (int, float)):
            raise RealtimeConfigError(
                f"realtime.voice_identity.rejected_sector holds a non-number: {item!r}"
            )
        angle = float(item)
        if not 0.0 <= angle <= 360.0:
            raise RealtimeConfigError(
                "realtime.voice_identity.rejected_sector angles must be degrees in "
                f"[0, 360], got {angle}"
            )
        numbers.append(angle)
    return (numbers[0], numbers[1])


def voice_identity_config_from_mapping(
    mapping: Mapping[str, Any] | None,
) -> VoiceIdentityConfig:
    """Validate the nested ``voice_identity:`` block. Absent ⇒ documented defaults.

    Two refusals here are not shared with the other blocks and are worth naming:

    * a **threshold outside (0, 1]** is refused rather than clamped. Cosine
      similarity lives in [-1, 1] and every admissible operating point measured
      on this host lives in (0, 1]; a ``threshold: 0`` would arm on any sound at
      all while every surface still reported a threshold, and a ``threshold:
      55`` (the percentage somebody meant) would refuse the owner forever.
    * a **rejected sector with no DoA reader** is refused. It is the one
      combination that silently does nothing: the operator has named the
      television's azimuth and nothing will ever read an azimuth to compare it
      against.
    """

    if mapping is None:
        return VoiceIdentityConfig()
    if not isinstance(mapping, Mapping):
        raise RealtimeConfigError(
            f"realtime.voice_identity must be a mapping, got {type(mapping).__name__}"
        )
    unknown = sorted(str(key) for key in mapping if str(key) not in VOICE_IDENTITY_ALLOWED_KEYS)
    if unknown:
        raise RealtimeConfigError(
            f"unknown realtime.voice_identity key(s): {', '.join(unknown)}; "
            f"allowed: {', '.join(sorted(VOICE_IDENTITY_ALLOWED_KEYS))}"
        )
    enabled = mapping.get("enabled", True)
    if not isinstance(enabled, bool):
        raise RealtimeConfigError(
            f"realtime.voice_identity.enabled must be a boolean, got {enabled!r}"
        )
    doa = mapping.get("doa", False)
    if not isinstance(doa, bool):
        raise RealtimeConfigError(f"realtime.voice_identity.doa must be a boolean, got {doa!r}")
    threshold = mapping.get("threshold", DEFAULT_VOICE_THRESHOLD)
    if isinstance(threshold, bool) or not isinstance(threshold, (int, float)):
        raise RealtimeConfigError(
            f"realtime.voice_identity.threshold must be a number, got {threshold!r}"
        )
    threshold = float(threshold)
    if not 0.0 < threshold <= 1.0:
        raise RealtimeConfigError(
            "realtime.voice_identity.threshold is a cosine similarity and must be "
            f"in (0, 1]; got {threshold}. The measured operating point on this "
            f"host is {DEFAULT_VOICE_THRESHOLD} (impostor max 0.431, genuine min 0.640)."
        )
    sector = _sector(mapping.get("rejected_sector"))
    if sector is not None and not doa:
        raise RealtimeConfigError(
            "realtime.voice_identity.rejected_sector names a direction and "
            "realtime.voice_identity.doa is false, so nothing will ever read one. "
            "Set doa: true (it needs the udev rule from bench_doa.md) or remove "
            "the sector."
        )
    for key in ("profile", "model"):
        value = mapping.get(key, "")
        if not isinstance(value, str):
            raise RealtimeConfigError(
                f"realtime.voice_identity.{key} must be a string path, got {value!r}"
            )
    return VoiceIdentityConfig(
        enabled=enabled,
        threshold=threshold,
        profile=str(mapping.get("profile", "")).strip(),
        model=str(mapping.get("model", "")).strip(),
        min_utterance_s=_voice_positive(mapping, "min_utterance_s", 1.2),
        budget_ms=_voice_positive(mapping, "budget_ms", 50.0),
        narration_interval_s=_voice_non_negative(mapping, "narration_interval_s", 60.0),
        doa=doa,
        rejected_sector=sector,
    )


def _voice_positive(mapping: Mapping[str, Any], key: str, default: float) -> float:
    """Card R25: finite, then positive — the same rule as :func:`_positive`.

    Fixed alongside its sibling rather than left for a later card: an
    ``+inf`` speaker-identity ``budget_ms`` is a latency ceiling that permits
    every delay, and a partial fix in one file is how a doctrine becomes folklore.
    """

    value = mapping.get(key, default)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise RealtimeConfigError(
            f"realtime.voice_identity.{key} must be a number, got {value!r}"
        )
    number = float(value)
    if not math.isfinite(number):
        raise RealtimeConfigError(
            f"realtime.voice_identity.{key} must be a finite number, got {number}"
        )
    if not number > 0.0:
        raise RealtimeConfigError(
            f"realtime.voice_identity.{key} must be greater than zero, got {number}"
        )
    return number


def _voice_non_negative(mapping: Mapping[str, Any], key: str, default: float) -> float:
    value = mapping.get(key, default)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise RealtimeConfigError(
            f"realtime.voice_identity.{key} must be a number, got {value!r}"
        )
    number = float(value)
    if not math.isfinite(number):
        raise RealtimeConfigError(
            f"realtime.voice_identity.{key} must be a finite number, got {number}"
        )
    if number < 0.0:
        raise RealtimeConfigError(
            f"realtime.voice_identity.{key} must not be negative, got {number}"
        )
    return number


def speech_acts_config_from_mapping(
    mapping: Mapping[str, Any] | None,
) -> SpeechActsConfig:
    """Validate the nested ``speech_acts:`` block. Absent ⇒ the contract is OFF."""

    if mapping is None:
        return SpeechActsConfig()
    if not isinstance(mapping, Mapping):
        raise RealtimeConfigError(
            f"realtime.speech_acts must be a mapping, got {type(mapping).__name__}"
        )
    unknown = sorted(str(key) for key in mapping if str(key) not in SPEECH_ACTS_ALLOWED_KEYS)
    if unknown:
        raise RealtimeConfigError(
            f"unknown realtime.speech_acts key(s): {', '.join(unknown)}; "
            f"allowed: {', '.join(sorted(SPEECH_ACTS_ALLOWED_KEYS))}"
        )
    enabled = mapping.get("enabled", False)
    if not isinstance(enabled, bool):
        raise RealtimeConfigError(
            f"realtime.speech_acts.enabled must be a boolean, got {enabled!r}"
        )
    return SpeechActsConfig(enabled=enabled)


def realtime_config_from_mapping(
    mapping: Mapping[str, Any] | None,
    *,
    source: str = "mapping",
) -> RealtimeConfig:
    """Validate one already-parsed config body. Unknown keys refuse."""

    if mapping is None:
        return RealtimeConfig(source=source)
    if not isinstance(mapping, Mapping):
        raise RealtimeConfigError(
            f"realtime config must be a mapping, got {type(mapping).__name__}"
        )
    unknown = sorted(str(key) for key in mapping if str(key) not in ALLOWED_KEYS)
    if unknown:
        raise RealtimeConfigError(
            f"unknown realtime config key(s): {', '.join(unknown)}; "
            f"allowed: {', '.join(sorted(ALLOWED_KEYS))}"
        )
    return RealtimeConfig(
        enabled=_boolean(mapping, "enabled", False),
        mode=_mode(mapping),
        persona=_optional_text(mapping, "persona", max_chars=MAX_PERSONA_CHARS),
        si_profile=_optional_text(mapping, "si_profile"),
        model=_text(mapping, "model", "gpt-realtime-2.1"),
        voice=_text(mapping, "voice", "cedar"),
        stall_timeout_s=_positive(mapping, "stall_timeout_s", 8.0),
        session_max_s=_positive(mapping, "session_max_s", 3600.0),
        idle_close_after_s=_idle_close_after_s(mapping, 600.0),
        monthly_budget_usd=_positive(mapping, "monthly_budget_usd", 25.0),
        proactive_motion_tools=_proactive_motion_tools(mapping),
        unknown_place=_unknown_place(mapping),
        hosted_affect=_boolean(mapping, "hosted_affect", False),
        whisperer=whisperer_config_from_mapping(mapping.get("whisperer")),
        capture=capture_config_from_mapping(mapping.get("capture")),
        voice_identity=voice_identity_config_from_mapping(mapping.get("voice_identity")),
        turn_detection=turn_detection_from_mapping(mapping.get("turn_detection")),
        speech_acts=speech_acts_config_from_mapping(mapping.get("speech_acts")),
        source=source,
    )


def load_realtime_config(path: str | Path | None) -> RealtimeConfig:
    """Read one config file. A missing path is a DISABLED config, not an error."""

    if path is None:
        return RealtimeConfig(source="absent")
    resolved = Path(path).expanduser()
    if not resolved.is_file():
        return RealtimeConfig(source="absent")
    try:
        body = yaml.safe_load(resolved.read_text(encoding="utf-8"))
    except yaml.YAMLError as error:
        raise RealtimeConfigError(f"realtime config is not valid YAML: {resolved}") from error
    if body is None:
        return RealtimeConfig(source=str(resolved))
    return realtime_config_from_mapping(body, source=str(resolved))


def resolve_realtime_config_path() -> Path | None:
    """Where the runtime looks. ``None`` when no config file exists anywhere.

    The environment override exists so tests (and an operator running two
    profiles) can point at a file without one ever being added to the repo —
    R1's shipped default is *no file*.
    """

    override = os.environ.get(REALTIME_CONFIG_ENV, "").strip()
    if override:
        candidate = Path(override).expanduser()
        return candidate if candidate.is_file() else None
    try:
        return resolve_asset(*REALTIME_CONFIG_RELATIVE, kind="file")
    except FileNotFoundError:
        return None


def default_realtime_config() -> RealtimeConfig:
    """The config the runtime boots with. Absent file ⇒ the lane never builds."""

    return load_realtime_config(resolve_realtime_config_path())


__all__ = [
    "ALLOWED_KEYS",
    "ALLOWED_MODES",
    "ALLOWED_UNKNOWN_PLACE_MODES",
    "CAPTURE_ALLOWED_KEYS",
    "CURIOSITY_ALLOWED_KEYS",
    "DEFAULT_CAPTURE_DIR",
    "DEFAULT_CAPTURE_MAX_MINUTES",
    "DEFAULT_CAPTURE_OWNER_GAP_S",
    "DEFAULT_VOICE_THRESHOLD",
    "DEFAULT_WHISPERER_WINDOW_S",
    "IDLE_CLOSE_NEVER",
    "MAX_PERSONA_CHARS",
    "MODE_AUDIO",
    "MODE_TEXT",
    "PROACTIVE_MOTION_ALLOWED",
    "PROACTIVE_MOTION_REFUSED",
    "REALTIME_CONFIG_ENV",
    "REALTIME_CONFIG_RELATIVE",
    "SPEECH_ACTS_ALLOWED_KEYS",
    "TURN_DETECTION_ALLOWED_KEYS",
    "UNKNOWN_PLACE_ASK",
    "UNKNOWN_PLACE_REFUSE",
    "VOICE_IDENTITY_ALLOWED_KEYS",
    "WHISPERER_ALLOWED_KEYS",
    "CaptureConfig",
    "CuriosityConfig",
    "OwnerEventsConfig",
    "RealtimeConfig",
    "RealtimeConfigError",
    "SpeechActsConfig",
    "TurnDetection",
    "VoiceIdentityConfig",
    "WhispererConfig",
    "capture_config_from_mapping",
    "curiosity_config_from_mapping",
    "default_realtime_config",
    "load_realtime_config",
    "owner_events_config_from_mapping",
    "realtime_config_from_mapping",
    "resolve_capture_dir",
    "resolve_realtime_config_path",
    "speech_acts_config_from_mapping",
    "turn_detection_from_mapping",
    "voice_identity_config_from_mapping",
    "whisperer_config_from_mapping",
]
