"""The situational whisperer: which robot facts reach the hosted model (card R11).

WHY THERE IS NO MODEL IN THIS FILE
----------------------------------
The drafted design had a small local judge (Gemma) decide the middle band. It
was benched against four alternatives on a 287-event / 597-second gold-labelled
stream (``<scratchpad>/csbench/reports/bench_whisperer.md``) and it **lost**:

======================  =========  =========  =========  =========
metric                  A (judge)  B2 (this)  C (judge)  D (raw)
======================  =========  =========  =========  =========
gold facts caught /12   8-10       **11**     8          8
noise forwarded /10min  1          **0**      2-3        25
e-stop forward lag      0 s        0 s        **+9.8 s** 0 s
same answer twice?      **no**     yes        no         yes
======================  =========  =========  =========  =========

Judge-everything (C) delayed an emergency stop by 9.8 seconds and lost the
resume-clear outright; the judge band (A) declined the real pace-mismatch fact
and forwarded the jitter noise instead, and did so *differently on identical
input between runs* because its own latency moved the windows. Roughly forty
lines of deterministic state machine beat it on every axis that matters.

So v1 forwards on **two bands plus three deterministic mechanisms**, and every
decision is a named rule a reader can look up. "Why did the dog say that" always
has an exact answer, which is a property no judge band had.

THE SHAPE, IN ONE PARAGRAPH
---------------------------
:class:`StateDigest` is a versioned snapshot of the robot. Two consecutive
digests are differenced into typed :class:`StateEvent`s carrying a semantic
*kind* — ``pace_mismatch``, ``battery_state``, ``nav_tick`` — computed
**upstream** of every gate, so that nothing downstream ever parses a raw
navigation note (parsing raw notes is what made policy D forward 25 noise items
per ten minutes). Each kind sits in exactly one band: :data:`ALWAYS_BAND`
forwards, :data:`NEVER_BAND` never does, and the middle band is decided by three
state machines (block-entry debounce, clear-only-after-a-forwarded-block, and
upstream semantic classes). Outside all of that sit the owner's cost knob, the
minimum gap and the dedup window. Everything — forward *and* suppression — is
written to :attr:`Whisperer.decisions` with the rule that fired.

WHAT THE OWNER CONTROLS
-----------------------
``whisperer.max_updates_per_minute`` in the realtime yaml is a hard cap on
billed non-voice queries: the bench showed ``gpt-realtime-2.1-mini`` speaks on
essentially every injected item (0-2 silences out of ~20), so **forward implies
utterance implies a billed response**, and the cap is the politeness control as
much as the cost control. Suppressed-by-budget items are not discarded — they
are *folded* into the next item that does go out as "+N more", so the owner can
always tell that the knob is what kept the robot quiet.

THE PACE WATCHER'S BLIND SPOT, AND WHY IT IS GONE (card R13)
------------------------------------------------------------
E1's ``run-with-me-flex`` scenario failed (``evals/20260819/run_1``) and the
diagnosis was in this file. ``owner_speed_mps`` comes from the follow
controller's best-effort owner-heading estimator, which is ``None`` whenever it
has not accumulated enough fresh passive updates — measured at a continuous
**10 seconds** across a run→walk transition in E1's offline probe, and for the
**whole 58.8 s window** in the recorded run. The old watcher's gate read
``owner_speed_mps is not None``, so an unmeasurable owner was treated exactly
like a running one: the ask never fired **and not one row was written**. A
decision log that exists to answer *"why did the dog stay quiet"* had a hole in
it precisely where the answer was.

Three things changed, and they are the invariant this module now carries:

1. ``None`` is its own state — :data:`KIND_PACE_UNKNOWN` — not a silent
   synonym for "still running". Entering it writes a row naming the follow
   controller's own last word on the owner track; leaving it writes another.
2. **The mismatch window PAUSES while the pace is unknown, it does not reset.**
   Seconds of a genuine walk already banked are not thrown away because the
   estimator blinked; ten blind seconds in the middle of a walk no longer buy
   the robot a fresh six-second silence.
3. **Every tick of the watcher is accounted for: a row, or a counted skip with
   a named reason** (:data:`PACE_SKIP_REASONS`, published in
   :meth:`Whisperer.snapshot`). ``pace_watch_ticks == pace_watch_logged +
   sum(pace_watch_skips.values())`` is an invariant with a test on it. Silence
   in the log is now always a number somewhere, which is the whole difference
   between an audit trail and a hopeful one.
"""

from __future__ import annotations

import random
import threading
import time
from collections import deque
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field, replace
from typing import Any

# Card C4. The reroute class is fed from the navigator's own social-progress
# vocabulary, and the binding is an IMPORT rather than a copied string: if that
# enum is renamed or re-valued, this module follows it instead of quietly
# speaking for a state that no longer exists. Nothing else in ``realtime``
# reaches into ``navigation``; this is a two-name, no-cycle dependency on a
# contracts module that imports only ``contracts`` and the standard library.
from parcel_robot.navigation.social_progress_contracts import (
    SocialBlockCauseV1,
    SocialProgressStateV1,
)

from .config import (
    DEFAULT_WHISPERER_WINDOW_S,
    CuriosityConfig,
    OwnerEventsConfig,
    WhispererConfig,
)

#: Bumped whenever :class:`StateDigest`'s field set changes meaning. It rides on
#: every digest and on every decision row, so a recorded whisperer log can never
#: be silently re-interpreted against a later schema.
#:
#: * **1** — R11's shipping field set.
#: * **2** — R13 adds :attr:`StateDigest.owner_speed_status`. Bumped rather than
#:   slipped in, because ``evals/20260819/run_1`` and the owner-session capture
#:   both hold logs recorded under 1, and a reader that finds
#:   ``owner_speed_status`` missing must know it is reading an older schema
#:   rather than conclude the follow controller said nothing.
#: * **3** — R21 adds :attr:`StateDigest.emergency_stop_source`. The same rule
#:   applies twice over here: ``evals/20260820/voice_corpus_v1/live_run_1`` was
#:   recorded under 2 and it is the run where a latch could not be attributed,
#:   so a reader that finds the field missing must conclude "this recording
#:   could not name the door", never "the latch had no door".
STATE_DIGEST_VERSION = 3

# --------------------------------------------------------------- event kinds
#: Safety.
KIND_EMERGENCY_STOP = "emergency_stop"
KIND_EMERGENCY_CLEAR = "emergency_clear"
#: Mission terminals and the mini-terminal.
KIND_MISSION_ARRIVED = "mission_arrived"
KIND_MISSION_ENDED = "mission_ended"
KIND_REROUTE = "reroute"
#: A refusal of something the OWNER asked for. Must be audible.
KIND_REFUSAL = "refusal"
#: Middle band: the block episode and its closure.
KIND_MISSION_BLOCKED = "mission_blocked"
KIND_MISSION_BLOCK_CLEAR = "mission_block_clear"
#: Always band, non-critical.
KIND_BATTERY_STATE = "battery_state"
KIND_PACE_MISMATCH = "pace_mismatch"
#: Card F1-SI. A turn the speaker-identity gate refused to arm — someone who is
#: not the enrolled owner told the robot to do something. Always band, because a
#: security refusal the owner never hears is a robot that looks broken; NOT
#: critical, because the critical set exists to bypass the owner's own cost
#: budget for facts about the owner's own requests, and this is by construction a
#: fact about somebody else's. The rate limiting that keeps a talkative
#: television from becoming a talkative robot lives in
#: ``voice_identity.VoiceIdentityGate.note_rejection`` (once per minute), and the
#: COUNT and the panel event are unconditional either way.
KIND_VOICE_REJECTED = "voice_rejected"

# ------------------------------------------- card P2-B: the owner-event classes
#
# Every class above this line is a fact about the ROBOT — it arrived, it is
# blocked, its battery is low, someone it did not recognise spoke to it. That is
# the whole reason the dog never initiates toward the person it lives with: there
# was no class of fact whose subject was the owner.
#
# These four are that class. They ride the SAME band table, the SAME dedup, the
# SAME min-gap and the SAME per-window cap as everything else — deliberately, and
# it is the answer to "will the companion become a nuisance": the owner's cost
# knob is also the politeness knob, and nothing here is exempt from it. None of
# them is CRITICAL: the critical set buys the right to spend past the owner's own
# ceiling, and no greeting is worth that.
#
#: The owner came into view after being away. Fired once per appearance episode,
#: by :class:`OwnerEventWatcher`, and never on a blink of the tracker.
KIND_OWNER_APPEARED = "owner_appeared"
#: The card's ``owner_returned_after_Nh``: the same rising edge as
#: :data:`KIND_OWNER_APPEARED` after a LONG absence, which is different news and
#: gets a different sentence. The N lives in the fact and in the dedup key —
#: ``owner_returned:3h`` — rather than in the class name, because a class name
#: that carries a number is a class table that grows without bound. Exactly one
#: of appeared/returned fires per appearance; never both.
KIND_OWNER_RETURNED = "owner_returned"
#: The owner is here and nothing has been said for a long time. This is the
#: companion's own initiative, not a state change.
KIND_GREETING_DUE = "greeting_due"
#: Once a day, while the owner is present: the robot asks one thing about the
#: owner's day. It is the only class in this module whose purpose is to LEARN
#: rather than to report, and it is the flywheel's first turn.
KIND_QUESTION_OF_THE_DAY = "question_of_the_day"

#: The four, as a set, so a caller can ask "is this an owner event" without
#: re-listing them (the F1-SI lesson: a set with three copies of itself is a set
#: that will disagree with itself).
OWNER_EVENT_KINDS: frozenset[str] = frozenset(
    {
        KIND_OWNER_APPEARED,
        KIND_OWNER_RETURNED,
        KIND_GREETING_DUE,
        KIND_QUESTION_OF_THE_DAY,
    }
)

# ============================================ card CURIO-1: the world classes
#
# P2-B's four classes above are closed and are not touched by this card. They
# gave the dog a subject it never had — YOU. These five give it the other one:
# the WORLD, and one more fact about you that P2-B's rising edge left without a
# partner.
#
# Everything before this block is a fact the robot has about ITSELF or about the
# owner's presence. None of it is a fact about what the robot SAW. The learned
# map (card P1-B) and the ASK outcome (card P1-D) produce exactly those facts
# all day and nothing narrated them, which is why the dog could greet you and
# could not say "there is a new plant by the window".
#
# THE BAND, AND WHY IT IS THE MIDDLE ONE
# --------------------------------------
# The four curiosity classes are MIDDLE band, which in this module has a
# specific meaning: "decided by a deterministic mechanism, never by a band and
# never by a classifier". Their mechanism is :class:`ChatterScheduler`, and the
# door it calls is :meth:`Whisperer.offer_curiosity`. A curiosity event handed
# to bare :meth:`Whisperer.offer` has skipped the scheduler and is REFUSED with
# :data:`RULE_MIDDLE_BAND_NEEDS_MECHANISM`, exactly as a mission-block event is.
#
# That is deliberate and it is the whole safety argument for this card. An
# always-band curiosity class would mean "the map grew, therefore the robot
# speaks" — and the map grows on a camera frame, at 2 Hz, forever. The band
# table cannot bound that; only a scheduler with a clock can.
#
#: A NAME entered the map's vocabulary — ``known_places()`` grew. This is the
#: dog learning what a thing is CALLED, and it is the only class here whose
#: subject is the robot's own understanding rather than the world.
KIND_PLACE_LEARNED = "place_learned"
#: A thing the robot had not seen in this scene before now has a map entry.
#: "There is a new plant by the window."
KIND_NOVEL_OBJECT = "novel_object"
#: Something the robot knew about is no longer there (it decayed out of the
#: active set), or has come back after being gone. The world moved.
KIND_SCENE_CHANGE = "scene_change"
#: Card P1-D's ASK outcome, spoken. The map has a candidate and the abstention
#: gate would not ADMIT it, so the honest move is to ask the owner rather than
#: to name it confidently or to say nothing. The one class here that wants an
#: answer.
KIND_ASK_ABOUT = "ask_about"
#: **Idle chatter.** Not fed by an event at all: this is what the dog says when
#: NOTHING has happened, about something it already knows, coloured by the time
#: of day. It exists because the card asked for two cadences and they turned out
#: to be two different KINDS of remark (see :data:`STIMULUS_KINDS`) — a fast
#: floor for "I just saw something" and a slow Poisson mean for "it has been
#: quiet a while". A class that fires when nothing happened cannot be
#: event-triggered, so it needs its own class and its own clock.
KIND_IDLE_REMARK = "idle_remark"

#: The five, as a set. Same reason P2-B's set exists: a caller asks "is this
#: curiosity" once, in one place.
CURIOSITY_KINDS: frozenset[str] = frozenset(
    {
        KIND_PLACE_LEARNED,
        KIND_NOVEL_OBJECT,
        KIND_SCENE_CHANGE,
        KIND_ASK_ABOUT,
        KIND_IDLE_REMARK,
    }
)

#: THE FOUR THAT NEED SOMETHING TO HAVE HAPPENED. Correction pass, 2026-08-22:
#: the card's "Poisson gaps, mean 4-8 min" and its "3-6 utterances in a 120 s
#: roam" were never one number, and reading them as one was the first pass's
#: mistake. They are two cadences over two kinds of remark:
#:
#:   * a STIMULUS remark answers "something just happened" — it is paced by a
#:     fixed floor (``curiosity.stimulus_min_gap_s``, 25 s) because the thing it
#:     is about is already in the past and a six-minute wait would have the dog
#:     narrating a lamppost it walked past four corners ago;
#:   * an IDLE remark answers "nothing is happening" — it is paced by a Poisson
#:     mean (``curiosity.mean_gap_s``, 4-8 min) because that is a companion's
#:     rhythm in a quiet room and anything faster is a talkative appliance.
#:
#: Both are still banded, deduped, min-gapped and capped identically. The two
#: knobs decide when a remark is DUE; the cap decides whether it is affordable,
#: and the cap wins.
STIMULUS_KINDS: frozenset[str] = frozenset(CURIOSITY_KINDS - {KIND_IDLE_REMARK})

#: The owner went away. **The falling edge P2-B's watcher does not carry.**
#:
#: P2-B's :class:`OwnerEventWatcher` is closed, so this card does not add a
#: fifth class to it; :class:`FarewellWatcher` below observes the SAME
#: :class:`OwnerPresence` samples and fires on the other edge. ALWAYS band and
#: NOT critical, for P2-B's reasons exactly: a farewell is news about the owner,
#: it is banded/deduped/min-gapped/capped like everything else, and no goodbye
#: is worth spending past the owner's own ceiling.
KIND_OWNER_LEFT = "owner_left"
# ======================================== END card CURIO-1 (the world classes)

# ============================================ card C4: the plan-acceptance class
#
# WHY THIS CLASS EXISTS
# ---------------------
# MB-1 (``research/20260829/model-b-narration-1``) drove the shipped whisperer
# over a 40-scenario receipt corpus and found that this robot cannot say "Sure,
# I'll check the sofa". There was no class for a plan ACCEPTANCE at all: the
# differ turns a ``nav_state`` change into :data:`KIND_NAV_TICK`, which is in the
# never band (55 ``never_band`` suppressions over the corpus, and they are
# exactly those events), and a ``nav_goal`` change produced nothing whatsoever.
# Arm D's acknowledgements were ARRIVALS' ``critical_bypass`` forwards standing
# in for an acknowledgement the product had never been given a way to make.
#
# WHY IT IS NOT A ``nav_goal`` BRANCH IN THE DIFFER
# -------------------------------------------------
# Because a string diff fires on the label, and the label changes for reasons
# that are not an admission: a re-issue of the same goal, a re-grounding of the
# same words, a navigator re-stating what it was already doing. That is the
# ``nav_tick`` mistake with a longer period, and it is the shape MB-1's verdict
# names. The only component that knows a plan was ADMITTED is the executive, and
# it already says so in a typed answer (``brain.executive.ExecutiveSubmission``).
# So this class has no differ branch and no detector of its own: it has a DOOR,
# :meth:`Whisperer.note_plan_accepted`, which takes a
# :class:`PlanAcceptedReceipt` — the executive's own fields, mirrored here so
# this module keeps importing nothing from ``brain`` — and the runtime hands it
# that answer at the one place the answer exists.
#
# ALWAYS BAND, NOT CRITICAL, OWN MIN-GAP
# --------------------------------------
# The critical set buys the right to spend past the owner's per-minute cap AND
# past the month's ceiling. An acknowledgement is not worth that: if the cap is
# already spent the owner has heard this robot twice inside the minute, and the
# plan runs either way — the sentence is a courtesy, not a fact the owner cannot
# do without. What it does get is its own spacing
# (:data:`PLAN_ACCEPTED_MIN_GAP_S`), because it is the only class in this module
# that ANSWERS something the owner said a moment ago, and the 15 s gap that
# keeps unsolicited status quiet would hold that answer until it read as a robot
# that had ignored them.
KIND_PLAN_ACCEPTED = "plan_accepted"
# ==================================== END card C4 (the plan-acceptance class) ==

#: Never band — the telemetry the bench proved must never reach the session.
KIND_NAV_TICK = "nav_tick"
KIND_FOLLOW_TICK = "follow_tick"
KIND_BATTERY_PCT = "battery_pct"
KIND_PROXIMITY_CHURN = "proximity_churn"
KIND_OWNER_PACE_CHANGE = "owner_pace_change"
KIND_POSITION = "position"
#: Card R13. The pace watcher cannot see the owner's speed. Never band, and it
#: is banded rather than left undeclared for two reasons: the class must have a
#: home so :func:`band_of` stays total, and forwarding it would be the exact
#: chattiness this module exists to prevent (a flaky estimator would have the
#: robot announcing its own instrumentation once per hole). It is written to the
#: decision log, and the decision log alone.
KIND_PACE_UNKNOWN = "pace_unknown"

#: Card R21. How each latch door reads inside the emergency-stop FACT. Keyed on
#: :attr:`StateDigest.emergency_stop_source`; an unknown or empty class falls
#: through to no clause at all, which is the R11 discipline — a digest that
#: cannot name the door says nothing about the door rather than guessing one.
#: The panel entry names both of its controls because the runtime cannot
#: separate them (``runtime.SAFETY_SOURCE_PANEL`` says why).
ESTOP_SOURCE_PHRASES = {
    "voice": " because the owner said the emergency stop phrase out loud",
    "typed": " because the owner typed the stop command",
    "panel": " from the control panel (the Space bar or the emergency-stop button)",
    "simulator": " adopted from the simulator",
    "runtime_close": " while the robot software was shutting down",
}

BAND_ALWAYS = "always"
BAND_NEVER = "never"
BAND_MIDDLE = "middle"

#: Forwarded the moment they happen. Card design point 1: safety facts, mission
#: terminals, refusals, arrivals. C's disqualifying counterexample was a judge
#: that delayed an e-stop by 9.8 s, so nothing in this set may be gated by a
#: classifier of any kind.
ALWAYS_BAND: frozenset[str] = frozenset(
    {
        KIND_EMERGENCY_STOP,
        KIND_EMERGENCY_CLEAR,
        KIND_MISSION_ARRIVED,
        KIND_MISSION_ENDED,
        KIND_REROUTE,
        KIND_REFUSAL,
        KIND_BATTERY_STATE,
        KIND_PACE_MISMATCH,
        KIND_VOICE_REJECTED,
        # Card P2-B. Always band, never critical: the owner-event watcher has
        # already decided that this greeting is due (once per appearance, once
        # per day), so a second classifier here would only add a way for it to be
        # late. The cap and the min-gap still apply, and they are what bound a
        # storm.
        *OWNER_EVENT_KINDS,
        # Card CURIO-1. The falling edge of the same presence track. Banded
        # here rather than in the middle band because it is an EDGE — it happens
        # once, when it happens, and there is nothing for a scheduler to pace.
        # Not critical (see KIND_OWNER_LEFT).
        KIND_OWNER_LEFT,
        # Card C4. An admission is an EDGE too — the executive said yes, once,
        # to a plan — so it is banded here and not in the middle band, which is
        # for classes that need a mechanism with a clock. It is deliberately not
        # in CRITICAL_KINDS; see the class comment.
        KIND_PLAN_ACCEPTED,
    }
)

#: Never forwarded, under any circumstances, by any rule. ``realtime-mini``
#: babbled about injected navigation state in 4/4 forced responses
#: (``bench_navmodel.md`` §6) — the only defence that works is that the item
#: never arrives. There is deliberately no override, no config key and no
#: escape hatch for this set.
NEVER_BAND: frozenset[str] = frozenset(
    {
        KIND_NAV_TICK,
        KIND_FOLLOW_TICK,
        KIND_BATTERY_PCT,
        KIND_PROXIMITY_CHURN,
        KIND_OWNER_PACE_CHANGE,
        KIND_POSITION,
        KIND_PACE_UNKNOWN,
    }
)

#: Decided by the deterministic mechanisms rather than by a band.
#:
#: Card CURIO-1 adds a fourth mechanism — :class:`ChatterScheduler`, whose door
#: is :meth:`Whisperer.offer_curiosity`. Handing a curiosity class to bare
#: :meth:`Whisperer.offer` refuses with
#: :data:`RULE_MIDDLE_BAND_NEEDS_MECHANISM`, which is the guard that keeps a 2 Hz
#: map from becoming a 2 Hz robot.
MIDDLE_BAND: frozenset[str] = frozenset(
    {KIND_MISSION_BLOCKED, KIND_MISSION_BLOCK_CLEAR, *CURIOSITY_KINDS}
)

#: **Critical.** These bypass the owner's per-minute budget: the emergency
#: latch, a refusal of the owner's own command, and a mission terminal (card
#: design point 8). Delaying any of them failed the bench disqualifyingly, and
#: each costs tenths of a cent at observed rates. They are still COUNTED against
#: the minute so the panel's number stays honest — they are just never the item
#: the counter suppresses.
CRITICAL_KINDS: frozenset[str] = frozenset(
    {
        KIND_EMERGENCY_STOP,
        KIND_EMERGENCY_CLEAR,
        KIND_MISSION_ARRIVED,
        KIND_MISSION_ENDED,
        KIND_REROUTE,
        KIND_REFUSAL,
    }
)

#: **The bench's min-gap bug, fixed.** Both deterministic arms (B and B2) missed
#: gold fact G3 because a reroute at t=96 s landed inside the 15 s min-gap held
#: by a mission_clear forwarded at t=90 s. Terminal-like events — every critical
#: kind, plus the closure of a block that was already announced — are therefore
#: exempt from the min-gap. A closure is not exempt from the BUDGET, because the
#: budget is the owner's cost knob and only the critical set may spend past it.
MIN_GAP_EXEMPT_KINDS: frozenset[str] = CRITICAL_KINDS | {KIND_MISSION_BLOCK_CLEAR}

#: **Card C4.** Per-class overrides of ``whisperer.min_gap_s``. A class named
#: here is spaced by ITS OWN number; every class not named here — which is the
#: whole table above this card — reads the owner's config exactly as it always
#: did, so this table is additive by construction.
#:
#: There is one entry, and the reason it is not a config key is that
#: ``realtime/config.py`` is at its DEC-0 ceiling and this is not a knob an
#: owner should have to find. ``min_gap_s`` (15 s shipped, 4 s in the prototype
#: config) paces UNSOLICITED status so that a walking robot is not a talking
#: appliance. :data:`KIND_PLAN_ACCEPTED` is the one class that answers something
#: the owner just said, and MB-1's corpus prices the shared number exactly: an
#: acceptance lands 2.8 s after the completion before it in the ``queued``
#: family and 3.1 s after it in ``clean``, so the shared gap swallows every
#: second acknowledgement in a two-goal trip. Two seconds is one conversational
#: beat — long enough that a double-tap is still one sentence, short enough that
#: the answer arrives while the question is still in the air.
#:
#: A class in here is spaced against ITS OWN last forward and does not advance
#: the shared spacing clock the other classes read. That second half is not a
#: detail — it is measured. MB-1's corpus, replayed with the acknowledgement
#: holding the shared clock, loses **10/10 block reports and 10/10 clears**: the
#: acknowledgement lands at t=0.3 and the 8 s block debounce elapses at t=13.5,
#: inside the owner's 15 s, so "someone is standing in the way" is suppressed and
#: the clear that follows can no longer prove its block was ever spoken. Trading
#: a block report for a courtesy sentence is a strictly worse robot, and the
#: shared clock is the owner's spacing for the robot's UNSOLICITED status —
#: which an answer to something they just said is not.
#:
#: This is spacing only. ``max_updates_per_minute`` still decides
#: affordability, and an acceptance obeys it like everything non-critical.
PLAN_ACCEPTED_MIN_GAP_S = 2.0
KIND_MIN_GAP_S: Mapping[str, float] = {KIND_PLAN_ACCEPTED: PLAN_ACCEPTED_MIN_GAP_S}

# --------------------------------------------------------- rules (log values)
RULE_ALWAYS_BAND = "always_band"
RULE_CRITICAL_BYPASS = "critical_bypass"
RULE_BLOCK_DEBOUNCE_ELAPSED = "block_debounce_elapsed"
RULE_CLEAR_AFTER_FORWARDED_BLOCK = "clear_after_forwarded_block"
RULE_PACE_MISMATCH_SUSTAINED = "pace_mismatch_sustained"

RULE_NEVER_BAND = "never_band"
RULE_DISABLED = "whisperer_disabled"
RULE_UNKNOWN_KIND = "unknown_kind_fails_closed"
RULE_DEDUP = "duplicate_within_dedup_window"
RULE_MIN_GAP = "min_gap"
RULE_BUDGET = "budget_exhausted"
RULE_BLOCK_DEBOUNCE_HOLDING = "block_debounce_holding"
RULE_CLEAR_WITHOUT_FORWARDED_BLOCK = "clear_without_forwarded_block"
#: A middle-band class handed straight to :meth:`Whisperer.offer` has skipped
#: its own state machine. Fails closed, exactly like an unknown class.
RULE_MIDDLE_BAND_NEEDS_MECHANISM = "middle_band_requires_a_mechanism"
#: **Card R13.** The pace watcher declined because the owner's speed could not
#: be measured at all. This is the row E1 went looking for and did not find.
RULE_PACE_UNKNOWN = "pace_unknown"
#: **Card R13.** The measurement came back. Paired with the
#: :data:`RULE_PACE_UNKNOWN` row that opened the hole, this is what makes the
#: blind interval a number an auditor can read off the log rather than infer.
RULE_PACE_KNOWN_RESUMED = "pace_known_resumed"
#: The whisperer said forward and the LANE's floor gate said no (the model has
#: the mouth, the session is being replaced, the owner is owed an answer). The
#: budget slot and the dedup entry are given back, because nothing was billed
#: and nothing was said — and the row stays, because "we tried" is a fact.
RULE_NARRATION_FLOOR_REFUSED = "narration_floor_refused"
#: **Card CURIO-1.** The middle band's fourth mechanism said yes: the chatter
#: scheduler's gap had elapsed, the owner was there, the conversation was quiet
#: and the class named a place the map has admitted. The forward is still
#: subject to the dedup window, the min-gap and the owner's cap below it.
RULE_CHATTER_SCHEDULED = "chatter_scheduled"
#: **Card CURIO-1.** A class that is not curiosity was handed to
#: :meth:`Whisperer.offer_curiosity`. The mirror image of
#: :data:`RULE_MIDDLE_BAND_NEEDS_MECHANISM`: a mechanism may only speak for the
#: classes it is the mechanism FOR, or "the middle band has a mechanism" stops
#: being a statement about anything.
RULE_CURIOSITY_DOOR_WRONG_CLASS = "curiosity_door_wrong_class"

# ------------------------------------------------- card C4: the receipt rules
#: The executive admitted a plan and this module said the sentence. The
#: counterpart of :data:`RULE_ALWAYS_BAND` for the receipt door, named
#: separately so a reader of the ledger can tell an ADMISSION apart from a state
#: change that happened to land in the same band.
RULE_PLAN_ADMITTED = "plan_admitted"
#: The same task, admitted again with the same plan. This is the row that stops
#: :data:`KIND_PLAN_ACCEPTED` from becoming ``nav_tick``: a re-issue is not
#: news, it is the owner (or a retry) saying the same thing twice, and the robot
#: acknowledging it twice is the chattiness this module exists to prevent. Keyed
#: on the executive's own plan identity — the validated plan's SHA — and never
#: on the goal LABEL, because two different plans can wear one label and one
#: plan can be re-grounded into two.
RULE_PLAN_REISSUE = "plan_reissue"
#: The receipt says the executive did NOT accept (a rejected re-issue, a
#: capacity refusal). Recorded rather than dropped, because "the robot said
#: nothing when I asked" and "the executive turned my plan away" are different
#: answers and the log is where they get told apart.
RULE_PLAN_NOT_ADMITTED = "plan_not_admitted"
#: A receipt with no task id or a lineage this module does not know. Fails
#: closed, exactly like :data:`RULE_UNKNOWN_KIND` — and it fails closed by
#: LOGGING rather than by raising, because this door is called from the
#: executive's own admission path and narration is a nicety that must never take
#: down a plan the owner asked for.
RULE_PLAN_RECEIPT_INVALID = "plan_receipt_invalid"
#: This mission has already spent its reroute allowance
#: (:data:`REROUTE_PER_MISSION_CAP`). The bound on a CRITICAL class that would
#: otherwise be able to spend past the owner's ceiling once per social-policy
#: flap; see the constant for the arithmetic.
RULE_REROUTE_MISSION_CAP = "reroute_mission_cap"
#: A social-progress state that is not ``reroute`` was handed to the reroute
#: door. The mirror of :data:`RULE_CURIOSITY_DOOR_WRONG_CLASS`: a door that will
#: speak for any state it is handed is not a door.
RULE_REROUTE_DOOR_WRONG_STATE = "reroute_door_wrong_state"
#: :data:`KIND_PLAN_ACCEPTED` was handed to bare :meth:`Whisperer.offer` instead
#: of to :meth:`Whisperer.note_plan_accepted`. Refused, for the reason
#: :data:`RULE_MIDDLE_BAND_NEEDS_MECHANISM` refuses a block: the door is where
#: the re-issue guard lives, and a class that can be spoken around its own guard
#: does not have one.
RULE_PLAN_ACCEPTED_NEEDS_RECEIPT = "plan_acceptance_requires_a_receipt"

# ------------------------------------------------------------ tuning constants
#: Card design point 2 / bench B2. A mission block must persist this long before
#: it is worth a sentence; the flap rhythm in the real artifacts
#: (``planned|person_stop``) is far faster than this.
BLOCK_DEBOUNCE_S = 8.0

#: Fact-key dedup, matching the bench's shared outer machinery (60 s general,
#: 20 s for safety so a genuine re-stop is never swallowed).
DEDUP_TTL_S = 60.0
CRITICAL_DEDUP_TTL_S = 20.0

#: The pace watcher's sustained window. Shorter than this and ordinary
#: stop-and-start walking would trip it; the bench's G12 window was 25 s wide.
PACE_MISMATCH_WINDOW_S = 6.0

#: Above this measured owner speed the owner is not walking. Chosen above a
#: brisk walk and below a jog, and deliberately NOT any value from the retired
#: embodiment families.
WALK_CEILING_MPS = 1.9

#: How many decision rows are kept for the panel and for the eval pack. The
#: never band is offered on every digest tick, so this is a ring, not a journal.
DECISION_LOG_MAX = 400

# ---------------------------------- card C4: the KIND_REROUTE band, DECIDED
#: **How many reroutes one mission may announce.**
#:
#: THE DECISION. :data:`KIND_REROUTE` was declared, banded ALWAYS, listed
#: CRITICAL, given a HINT and exported — and never constructed by any product
#: code (MB-1's verdict; parcel-6c verified it line by line at HEAD). Its first
#: constructor therefore had to answer a band question before it wrote a line,
#: because a CRITICAL class spends past the owner's per-minute cap AND past the
#: month's ``monthly_budget_usd`` ceiling. It stays CRITICAL, and it is CAPPED.
#:
#: WHY IT STAYS CRITICAL. The bench's disqualifying counterexample is a reroute:
#: "reroute at t=96 was silently dropped because a mission_clear forwarded at
#: t=90 held the 15 s min-gap — G3 missed by both deterministic arms". The
#: min-gap exemption that fixes that IS the critical set in this module
#: (:data:`MIN_GAP_EXEMPT_KINDS`), and ``runtime._narrate_mission`` reads the
#: same set for the monthly ceiling on purpose, so that "which facts outrank the
#: owner's cost knob" has one answer here and not two lists that drift. Taking
#: reroute out of the set to make it ordinary would re-open G3 and split that
#: answer in two.
#:
#: WHY IT IS CAPPED, AND WHAT THE CAP COSTS. Every other critical class is an
#: EDGE that happens at most a handful of times per trip. A reroute is not: it
#: is fed from :attr:`SocialProgressStateV1.REROUTE`, which is a policy STATE
#: the navigator can re-enter every time an alternate route becomes available,
#: and the only thing between a flapping policy and the session is the 20 s
#: critical dedup. Unbounded, that is a 10-minute trip announcing up to 30
#: reroutes past the ceiling — at MB-1's measured ~$0.0024 per forwarded
#: narration ($1.33 / 550 ledger rows), ~$0.07 a mission, or ~$43/month at 20
#: missions a day: a quarter of ``hosted_budget.DEFAULT_ENVELOPE_USD``, spent
#: entirely by the one path that is allowed to ignore the envelope. Three
#: reroutes per mission bound that at ~$0.007 a mission (~$4.3/month at the same
#: rate) while still admitting a real re-plan sequence — the first alternate
#: route, one revision of it, and a last one — which is more than the one
#: reroute per mission the bench corpus actually contains.
#:
#: The cap is per MISSION and resets when the mission does; over the cap the
#: item is dropped with :data:`RULE_REROUTE_MISSION_CAP` and still logged. A
#: reroute the lane's floor gate refuses gives its allowance back
#: (:meth:`Whisperer.undeliver`), because a sentence nobody heard must not spend
#: a mission's budget any more than it spends the owner's minute.
REROUTE_PER_MISSION_CAP = 3

#: How many tasks' plan identities the re-issue guard remembers. A bound, not a
#: policy: the guard only ever needs the task the owner is talking about now and
#: the handful behind it, and an unbounded dict on a process that runs for weeks
#: is a leak with a good excuse.
PLAN_ADMISSION_MEMORY = 32

# ------------------------------------------- card R13: the watcher's own ledger
#: Why a pace-watcher tick wrote no row. Every tick lands in exactly one of
#: these buckets or writes a row — never neither, which was the whole defect.
#: They are counters rather than rows because the watcher runs at 1 Hz for the
#: length of a walk: a row per tick would evict the decision ring (400 rows,
#: ~6 minutes) and bury the rows that mean something. A counter says the same
#: thing in one integer and cannot be evicted.
#:
#: The first digest of a session, which is a baseline and produces no diff at
#: all (see :meth:`Whisperer.observe`).
PACE_SKIP_SESSION_BASELINE = "session_baseline"
#: The robot is not following anyone, so there is no pace to have opinions on.
PACE_SKIP_NOT_FOLLOWING = "not_following"
#: Following, but the owner never asked for a run. R10 records the declaration;
#: with no declaration there is no mismatch to notice.
PACE_SKIP_NO_RUN_INTENT = "no_run_intent"
#: The owner is measurably running. The request and the world agree.
PACE_SKIP_OWNER_RUNNING = "owner_running"
#: Still blind, and the hole was already announced by a row.
PACE_SKIP_UNKNOWN_HOLDING = "pace_unknown_holding"
#: A real mismatch, banking seconds towards :data:`PACE_MISMATCH_WINDOW_S`.
PACE_SKIP_WINDOW_ACCUMULATING = "window_accumulating"
#: Asked already this episode. The latch, doing its job.
PACE_SKIP_ALREADY_ASKED = "already_asked"

PACE_SKIP_REASONS: frozenset[str] = frozenset(
    {
        PACE_SKIP_SESSION_BASELINE,
        PACE_SKIP_NOT_FOLLOWING,
        PACE_SKIP_NO_RUN_INTENT,
        PACE_SKIP_OWNER_RUNNING,
        PACE_SKIP_UNKNOWN_HOLDING,
        PACE_SKIP_WINDOW_ACCUMULATING,
        PACE_SKIP_ALREADY_ASKED,
    }
)

#: Speech-act hints, per class, from deterministic templates (card design 4).
#: Fact-only injections produced inert telegram relays and **0/12** of the
#: owner-required follow-up questions across both bench cells; naming the speech
#: act with the fact is the cheapest thing that targets that directly, and it
#: needs no model to compose.
HINTS: Mapping[str, str] = {
    KIND_EMERGENCY_STOP: "Say plainly that you have stopped, and why.",
    KIND_EMERGENCY_CLEAR: "Tell the owner it is clear now and that you are moving again.",
    KIND_MISSION_ARRIVED: "Now ask the owner what they would like to do next.",
    KIND_MISSION_ENDED: (
        "Tell the owner you stopped and why, then ask what they want to do instead."
    ),
    KIND_REROUTE: "Tell the owner you are taking a different way, and why.",
    # Card C4. The whole point of the class is the FIRST four words of the
    # answer, so the hint spends its second clause forbidding the three things
    # the bench watched models do with an acceptance: repeat the owner's own
    # sentence back at them, recite the plan as a list of steps, and slide from
    # "I will go" into "I have gone".
    KIND_PLAN_ACCEPTED: (
        "Tell the owner you are getting on with what they just asked for, in one "
        "short sentence. Do NOT read their own words back to them, do NOT list "
        "the steps, and do NOT say or imply that you have arrived, looked at "
        "anything or found anything."
    ),
    KIND_REFUSAL: "Say the refusal out loud in your own words, with the reason.",
    KIND_MISSION_BLOCKED: (
        "Tell the owner what is in the way and that you are waiting for it to clear."
    ),
    KIND_MISSION_BLOCK_CLEAR: "Tell the owner the way is clear and that you are carrying on.",
    KIND_BATTERY_STATE: (
        "Tell the owner the battery figure and suggest heading back to charge."
    ),
    KIND_PACE_MISMATCH: (
        "Say what gait you are actually in right now, then ask the owner whether "
        "they would rather just walk."
    ),
    KIND_VOICE_REJECTED: (
        "Tell the owner, plainly and without alarm, that someone who is not them "
        "asked you to do something and you did not do it. Do NOT claim you cannot "
        "be stopped by other people — anyone may still stop you."
    ),
    # Card P2-B. Each of these is one short sentence, and each says what NOT to
    # do, because the failure mode is the same one the bench found everywhere
    # else in this table: handed a fact with no speech act, the model narrates
    # the instrument ("my owner tracking reports…") instead of speaking to the
    # person standing in front of it.
    KIND_OWNER_APPEARED: (
        "Greet the owner, warmly and in one short sentence, as a dog would when "
        "someone it likes walks in. Do NOT describe your sensors or say how long "
        "they were away in seconds."
    ),
    KIND_OWNER_RETURNED: (
        "Welcome the owner back in one or two short sentences and say you noticed "
        "they were gone a while. Do NOT recite the exact number of hours back at "
        "them, and do NOT ask where they were."
    ),
    KIND_GREETING_DUE: (
        "Say one short, friendly thing to the owner — you have both been quiet "
        "for a while and you noticed. Do NOT ask them for a task and do NOT list "
        "your status."
    ),
    KIND_QUESTION_OF_THE_DAY: (
        "Ask the owner exactly ONE short question about their day or about "
        "something they like, then stop and listen. Do NOT ask more than one "
        "question, and do NOT explain why you are asking."
    ),
    # Card CURIO-1. The card writes one HINT for the whole family — "mention one
    # thing you noticed, one sentence, no status, no sensors" — and these four
    # are that sentence, per class, with the class's own verb. Every one of them
    # spends its second clause on a prohibition for the reason the rest of this
    # table does: the bench's failure mode is not silence, it is the model
    # narrating the INSTRUMENT ("my online semantic map has admitted a new
    # label") when it was handed a fact with no speech act.
    KIND_NOVEL_OBJECT: (
        "Mention the one thing you just noticed, in one short sentence, the way "
        "you would point something out to a friend. Do NOT list your sensors, do "
        "NOT give coordinates or distances, and do NOT report your status."
    ),
    KIND_PLACE_LEARNED: (
        "Say, in one short sentence, that you have worked out what this thing is "
        "called. Do NOT explain how you learned it, do NOT mention a map, a "
        "detector or a confidence, and do NOT ask for a task."
    ),
    KIND_SCENE_CHANGE: (
        "Remark on the one thing that has changed since you last looked, in one "
        "short sentence. Do NOT speculate about why, and do NOT describe your "
        "sensors or your memory."
    ),
    KIND_ASK_ABOUT: (
        "Ask the owner ONE short question about the thing you are unsure of, and "
        "say plainly that you are not sure. Do NOT name it as if you knew, do NOT "
        "ask more than one question, and do NOT explain your uncertainty in "
        "numbers."
    ),
    KIND_IDLE_REMARK: (
        "Make one short, easy remark — you are filling a quiet moment, not "
        "reporting anything. Do NOT ask for a task, do NOT list your status, and "
        "do NOT pretend something has just happened."
    ),
    KIND_OWNER_LEFT: (
        "Say a short, easy goodbye — one sentence, the way a dog watches someone "
        "go. Do NOT ask where they are going, do NOT ask them to stay, and do NOT "
        "say how long they were here."
    ),
}


class WhispererError(RuntimeError):
    """A whisperer that cannot be trusted. Never downgraded to a default."""


@dataclass(frozen=True)
class StateDigest:
    """One versioned snapshot of the robot, as the companion layer sees it.

    Every field is TYPED. There is no free-text note in here on purpose: the
    differ below is the only thing that turns robot state into a class name, and
    a class name is the only thing any gate downstream is allowed to look at.
    """

    schema_version: int = STATE_DIGEST_VERSION
    at_s: float = 0.0

    # safety
    emergency_stopped: bool = False
    #: WHICH DOOR latched it — card R21. A CLASS name from the runtime's closed
    #: source vocabulary (``voice``, ``typed``, ``panel``, ``api``,
    #: ``simulator``, ``runtime_close``), never the owner's words: the verbatim
    #: utterance is free text and this dataclass deliberately holds none, so it
    #: lives on the safety-log row and stays out of the differ. Empty whenever
    #: the robot is not latched.
    #:
    #: It exists because ``emergency_stopped`` alone cannot tell the owner what
    #: they most need to hear. 2026-08-20 live_run_1 latched the robot from an
    #: unknown door and the fact reached the owner once, sixty-six seconds late,
    #: inside an answer about the robot's mood.
    emergency_stop_source: str = ""
    proximity_state: str = "clear"

    # mission
    navigating: bool = False
    #: The navigator's own status word. It flaps (``planned`` /
    #: ``person_stop``) at the motion cadence — that flap IS the ``nav_tick``
    #: telemetry the never band exists to swallow.
    nav_state: str = "idle"
    nav_goal: str = ""
    mission_blocked: bool = False
    mission_block_class: str = ""
    mission_block_episode: int = 0

    # body
    position_dm: tuple[int, int] = (0, 0)

    # power
    battery_percent: float = 100.0
    battery_state: str = "normal"

    # follow / run-with-me
    following: bool = False
    follow_pace_intent: str = ""
    follow_distance_dm: int = 0
    #: ``None`` means the owner's pace is UNMEASURABLE right now, not that the
    #: owner is fast, slow or still. R13 exists because those were once the same
    #: thing to the code below.
    owner_speed_mps: float | None = None
    #: The follow controller's own last word on the owner track
    #: (``insufficient_motion``, ``history_gap``, ``outlier``, ``updated``, …),
    #: carried so a ``pace_unknown`` row can name what the estimator was doing
    #: instead of leaving an auditor to guess. It is a HINT and not a cause: the
    #: estimate is also ``None`` when too few updates have accumulated or when
    #: the last good one went stale, and the status still reads ``updated``
    #: through both. Never spoken; the never band sees to that.
    owner_speed_status: str = ""
    #: The gait the BODY is actually in. R10/R11 never apply a requested pace to
    #: the follow controller, so this is always the controller's own pace — and
    #: saying so explicitly is the honesty guard (see :func:`_pace_mismatch_fact`).
    robot_pace: str = ""
    robot_speed_cap_mps: float = 0.0

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "at_s": self.at_s,
            "emergency_stopped": self.emergency_stopped,
            "emergency_stop_source": self.emergency_stop_source,
            "proximity_state": self.proximity_state,
            "navigating": self.navigating,
            "nav_state": self.nav_state,
            "nav_goal": self.nav_goal,
            "mission_blocked": self.mission_blocked,
            "mission_block_class": self.mission_block_class,
            "mission_block_episode": self.mission_block_episode,
            "position_dm": list(self.position_dm),
            "battery_percent": self.battery_percent,
            "battery_state": self.battery_state,
            "following": self.following,
            "follow_pace_intent": self.follow_pace_intent,
            "follow_distance_dm": self.follow_distance_dm,
            "owner_speed_mps": self.owner_speed_mps,
            "owner_speed_status": self.owner_speed_status,
            "robot_pace": self.robot_pace,
            "robot_speed_cap_mps": self.robot_speed_cap_mps,
        }


@dataclass(frozen=True)
class StateEvent:
    """One thing that happened, already classified. Never a raw note."""

    kind: str
    #: The sentence of FACT. Never carries a speech act; that is :data:`HINTS`.
    fact: str = ""
    #: Dedup identity. Defaults to the kind, which is right for the state-derived
    #: classes; producers that can repeat a class with a different subject (a
    #: mission terminal, a refusal) pass their own.
    key: str = ""
    #: Pairs a block with its closure so a clear can prove its block was spoken.
    episode: int = 0
    #: The fact already contains its own speech act, so the hint template must
    #: not be appended. Used by R10's arrival table, which composes the ask from
    #: the SAME row the planner used to choose the terminal.
    hint_carried: bool = False
    detail: Mapping[str, object] = field(default_factory=dict)

    def dedup_key(self) -> str:
        return self.key or self.kind


# ================================== card C4: the two receipts, and their facts
#: How an admission is RELATED to what the robot was already doing. ``new`` and
#: ``revise`` are what today's executive can distinguish — ``submit`` versus
#: ``replace`` at the runtime's own call site — and ``queue`` is declared now,
#: unused, because C6's plan queue is the card that produces it and a vocabulary
#: that grows a value later is a vocabulary two components can disagree about in
#: the meantime.
LINEAGE_NEW = "new"
LINEAGE_REVISE = "revise"
LINEAGE_QUEUE = "queue"
PLAN_LINEAGES: frozenset[str] = frozenset({LINEAGE_NEW, LINEAGE_REVISE, LINEAGE_QUEUE})

#: One sentence of FACT per lineage. Templates, not a model: MB-2 measured a
#: receipt-typed contract passing every fact gate the hosted model failed, and
#: the reading it published is "the facts belong in the contract, not in the
#: voice". The speech act is in :data:`HINTS`, outside the fact, as everywhere
#: else in this module.
PLAN_ACCEPTED_FACTS: Mapping[str, str] = {
    LINEAGE_NEW: (
        "The robot's task executive reports it has accepted a new goal from the "
        "owner and will go to {goal}."
    ),
    LINEAGE_REVISE: (
        "The robot's task executive reports it has accepted the owner's "
        "correction and will go to {goal} instead of what it was doing."
    ),
    LINEAGE_QUEUE: (
        "The robot's task executive reports it has queued {goal} to do after the "
        "goal it is already carrying out."
    ),
}

#: Why the route changed, as a clause. Keyed on
#: :class:`SocialBlockCauseV1` VALUES rather than on strings of this module's
#: own invention, and an unknown or absent cause falls through to no clause at
#: all — the R21 discipline: a receipt that cannot name the reason says nothing
#: about the reason rather than guessing one.
REROUTE_CAUSE_PHRASES: Mapping[str, str] = {
    SocialBlockCauseV1.TRUE_DYNAMIC_BLOCK.value: " because something is blocking the way it was going",
    SocialBlockCauseV1.UNCERTAIN_OCCLUSION.value: " because it cannot see far enough along the way it was going",
    SocialBlockCauseV1.RECIPROCAL_OSCILLATION.value: (
        " because it and someone coming the other way kept stepping into each other"
    ),
}

#: The one social-progress state this module's reroute door will speak for.
SOCIAL_STATE_REROUTE = SocialProgressStateV1.REROUTE.value

#: A goal label is grounded owner text, so it is bounded before it is composed
#: into a sentence. Long enough for any place name the grounder admits, short
#: enough that a pathological label cannot become the whole item.
MAX_GOAL_LABEL_CHARS = 80


@dataclass(frozen=True)
class PlanAcceptedReceipt:
    """The executive's admission answer, in this module's own vocabulary.

    The fields MIRROR ``brain.executive.ExecutiveSubmission`` (``accepted``,
    ``disposition``, ``task_id``, ``plan_revision``) and add the three things
    that answer alone cannot carry: what the owner asked for
    (:attr:`goal_label`), how it relates to what was already running
    (:attr:`lineage`), and WHICH PLAN was admitted (:attr:`plan_digest`, the
    validator's ``plan_sha256``). Mirrored rather than imported so that a leaf
    of ``realtime`` does not take a dependency on ``brain``; the runtime builds
    this at the one place both halves are in scope.

    Nothing here raises. This object is constructed on the executive's own
    admission path, and narration is a nicety that must never be able to take
    down a plan the owner asked for — a malformed receipt is a LOGGED refusal at
    the door (:data:`RULE_PLAN_RECEIPT_INVALID`), not an exception.
    """

    task_id: str
    goal_label: str
    plan_revision: int = 1
    lineage: str = LINEAGE_NEW
    accepted: bool = True
    disposition: str = ""
    #: The validated plan's SHA (``brain.validator.ValidatedPlan.plan_sha256``).
    #: THE re-issue guard's identity: two admissions of the same task carrying
    #: the same plan are one piece of news, whatever their revision numbers say.
    plan_digest: str = ""
    #: The executive's own id for this admission, when it has one. Defaults to
    #: ``<task>:r<revision>``, which is what the transition ledger keys on.
    receipt_id: str = ""

    def plan_identity(self) -> str:
        """What "the same plan" means. The SHA when there is one."""

        return self.plan_digest or f"r{int(self.plan_revision)}"

    def receipt_ref(self) -> str:
        return self.receipt_id or f"{self.task_id}:r{int(self.plan_revision)}"


@dataclass(frozen=True)
class RerouteReceipt:
    """One social-progress reroute, as the navigator's contract reports it.

    :attr:`state` is passed rather than assumed: the door refuses anything that
    is not :data:`SOCIAL_STATE_REROUTE`, which is only a guard worth having if
    the caller has to say what it actually got.
    """

    #: What the trip is FOR — the goal label the reroute is a reroute of. Also
    #: the identity the per-mission cap counts against.
    mission: str
    #: ``SocialProgressDecisionV1.state.value``.
    state: str
    #: ``SocialProgressDecisionV1.cause.value``; optional.
    cause: str = ""
    #: ``SocialProgressDecisionV1.blocker_id``; carried into the decision log's
    #: detail and never into the sentence — a track id is not something to say
    #: out loud.
    blocker_id: str = ""


def _goal_phrase(label: str) -> str:
    clean = " ".join(str(label).split())[:MAX_GOAL_LABEL_CHARS]
    # An empty label would leave a hole in the sentence, and a hole in the
    # sentence is what the model fills in (``curiosity_event``'s lesson).
    return _definite_phrase(clean) if clean else "the place the owner asked for"


def plan_accepted_event(receipt: PlanAcceptedReceipt) -> StateEvent:
    """One :data:`KIND_PLAN_ACCEPTED` event. Total: never raises."""

    lineage = str(receipt.lineage)
    template = PLAN_ACCEPTED_FACTS.get(lineage, PLAN_ACCEPTED_FACTS[LINEAGE_NEW])
    return StateEvent(
        kind=KIND_PLAN_ACCEPTED,
        # The dedup identity is the PLAN, not the label: two different plans
        # that ground to one label are two pieces of news, and one plan
        # re-admitted under two labels is one.
        key=f"plan_accepted:{receipt.task_id}:{receipt.plan_identity()}",
        fact=template.format(goal=_goal_phrase(receipt.goal_label)),
        detail={
            "task_id": str(receipt.task_id),
            "plan_revision": int(receipt.plan_revision),
            "lineage": lineage,
            "receipt_id": receipt.receipt_ref(),
            "disposition": str(receipt.disposition),
        },
    )


def reroute_event(receipt: RerouteReceipt) -> StateEvent:
    """One :data:`KIND_REROUTE` event. Total: never raises."""

    goal = _goal_phrase(receipt.mission)
    cause = REROUTE_CAUSE_PHRASES.get(str(receipt.cause), "")
    return StateEvent(
        kind=KIND_REROUTE,
        # Keyed on the MISSION: a second reroute on the same trip is the same
        # news, and the 20 s critical dedup is what makes it one sentence.
        key=f"reroute:{goal}",
        fact=(
            f"The robot's navigation system reports it is taking a different way "
            f"to {goal}{cause}."
        ),
        detail={
            "mission": goal,
            "state": str(receipt.state),
            "cause": str(receipt.cause),
            "blocker_id": str(receipt.blocker_id),
        },
    )


# ================================= END card C4 (the receipts and their facts) ==


@dataclass(frozen=True)
class WhispererDecision:
    """One forward or one suppression, with the rule that produced it.

    This is the audit record the card asks for, and it is strictly better than
    the judge design's would have been: the rule is a name in this module, not a
    sampled token, so the answer to "why did the dog say that" is reproducible.
    """

    seq: int
    at_s: float
    kind: str
    #: The dedup identity this decision was scored against. Recorded because it
    #: is the difference between "the same fact twice" and "two different waits",
    #: and because :meth:`Whisperer.undeliver` needs to give back exactly the one
    #: entry it took.
    key: str
    band: str
    forwarded: bool
    rule: str
    text: str = ""
    folded: int = 0
    updates_this_minute: int = 0
    schema_version: int = STATE_DIGEST_VERSION

    def as_dict(self) -> dict[str, object]:
        return {
            "seq": self.seq,
            "at_s": self.at_s,
            "kind": self.kind,
            "key": self.key,
            "band": self.band,
            "forwarded": self.forwarded,
            "rule": self.rule,
            "text": self.text,
            "folded": self.folded,
            "updates_this_minute": self.updates_this_minute,
            "schema_version": self.schema_version,
        }


def band_of(kind: str) -> str:
    """Which band a class sits in. Keyed on the CLASS and nothing else.

    An unknown class has no band, and :meth:`Whisperer.offer` fails closed on
    it: a class nobody declared is a programming error, and speaking on one
    would mean the band table is not the authority it claims to be. The
    suppression is written to the decision log, so the mistake is loud.
    """

    if kind in ALWAYS_BAND:
        return BAND_ALWAYS
    if kind in NEVER_BAND:
        return BAND_NEVER
    if kind in MIDDLE_BAND:
        return BAND_MIDDLE
    return ""


def _pace_mismatch_fact(digest: StateDigest, *, window_s: float) -> str:
    """The pace-mismatch item, with the honesty guard welded in.

    The bench measured the same defect in both cells: told only that the owner
    had slowed, the model announced an adaptation that had not happened — *"I'm
    matching your slower pace"* while the injected gait was still RUN (0/6 chat,
    1/3 realtime). The defence is to leave no room for it: the item states the
    gait the body is ACTUALLY in, states that nothing changed, and gives the
    number. A model cannot confabulate an adaptation over a sentence that
    already denies one.

    **R13:** an unmeasurable pace refuses outright rather than composing. The
    old wording rendered ``None`` as *"below a walking pace, which is a walk"* —
    a measurement claim about an owner nobody could measure, in the one item
    whose entire job is not overstating what the robot knows. It was unreachable
    then and it is refused now, so it cannot become reachable by accident.
    """

    speed = digest.owner_speed_mps
    if speed is None:
        raise WhispererError(
            "refusing to compose a pace-mismatch item with no measured owner "
            "speed: the watcher records pace_unknown instead of guessing"
        )
    measured = f"{speed:.1f} m/s"
    return (
        "The robot's follow controller reports: you asked it to "
        f"{digest.follow_pace_intent} with you, but its current gait is "
        f"{digest.robot_pace} and it has NOT changed speed for that request "
        f"(its follow speed is capped at {digest.robot_speed_cap_mps:.2f} m/s). "
        f"Your own measured pace over the last {window_s:.0f} seconds is "
        f"{measured}, which is a walk."
    )


class Whisperer:
    """Decides which robot facts reach the hosted session. Owns no lane.

    Deliberately a pure decision object: it takes digests and events and returns
    decisions. The runtime is the only thing that touches
    :meth:`~parcel_robot.realtime.lane.RealtimeLane.narrate_event`. That keeps
    every rule in here testable against a frozen clock with no provider, no
    socket and no threads.
    """

    def __init__(
        self,
        *,
        config: WhispererConfig,
        clock: Callable[[], float] = time.monotonic,
        decision_log_max: int = DECISION_LOG_MAX,
    ) -> None:
        self.config = config
        self._clock = clock
        # Mission terminals arrive on whatever thread ended the mission; the
        # digest tick arrives on the control loop. Re-entrant because the middle
        # -band machines call through ``_forward`` into ``_record``.
        self._lock = threading.RLock()
        self._seq = 0
        self.decisions: deque[WhispererDecision] = deque(maxlen=int(decision_log_max))
        self.forwarded = 0
        self.suppressed = 0
        self.suppressed_by_rule: dict[str, int] = {}
        self.forwarded_by_rule: dict[str, int] = {}

        self._previous: StateDigest | None = None
        # Card C4 follow-up A1. Each entry is ``(at, kind)``. The timestamp is
        # the budget (``_spent`` counts entries and evicts by age, exactly as
        # before); the KIND is what lets ``undeliver`` rewind the SHARED spacing
        # clock to the last forward that actually advanced it. Before C4 every
        # entry advanced it and ``_forwards[-1]`` was always the right answer;
        # an own-gap class breaks that assumption, so the assumption is now
        # written into the deque instead of being inferred from it.
        self._forwards: deque[tuple[float, str]] = deque()
        self._last_forward_at: float | None = None
        self._dedup: dict[str, float] = {}
        # Card C4. The own-gap classes' spacing clocks (KIND_MIN_GAP_S). Kept
        # apart from ``_last_forward_at`` so that a class with its own number
        # neither reads nor writes the owner's shared one.
        self._last_forward_by_kind: dict[str, float] = {}
        self._folded = 0

        # middle-band state machines. ``_block_open`` is THIS object's own view
        # of whether the robot is stuck — not the runtime's edge counter, which
        # moves at the motion cadence (see ``_block_debounce``).
        self._block_open = False
        self._block_episode = 0
        self._block_pending_since: float | None = None
        self._block_spoken = False

        # pace watcher. ``_pace_mismatch_banked_s`` is what card R13 added: the
        # window ACCUMULATES seconds of measured mismatch and pauses when the
        # measurement goes away, instead of restarting from zero every time the
        # estimator blinks.
        self._pace_mismatch_since: float | None = None
        self._pace_mismatch_banked_s = 0.0
        self._pace_mismatch_open = False
        self._pace_unknown = False
        self._pace_unknown_since: float | None = None

        # card C4. The re-issue guard's memory: task id -> the identity of the
        # plan this object has already spoken for. Bounded (see
        # PLAN_ADMISSION_MEMORY) and deliberately NOT keyed on the goal label.
        self._plan_admitted: dict[str, str] = {}

        # card C4. The reroute allowance, per mission. ``_reroute_mission`` is
        # the trip the count belongs to; a different mission resets the count,
        # which is what makes the cap per-mission rather than per-session.
        self._reroute_mission = ""
        self._reroute_spoken = 0

        # the watcher's own ledger (card R13). Cumulative for the session and
        # published in ``snapshot()``: a counter cannot be evicted by the ring,
        # so "the watcher was blind for ninety seconds" survives a long walk.
        self.pace_watch_ticks = 0
        self.pace_watch_logged = 0
        self.pace_watch_skips: dict[str, int] = {}
        self.pace_unknown_episodes = 0
        self.pace_unknown_seconds = 0.0

    # ------------------------------------------------------------- the doors
    def observe(self, digest: StateDigest) -> tuple[WhispererDecision, ...]:
        """Diff one digest against the last and band everything it produced.

        This is the ONLY place robot state becomes a class name. Called on the
        runtime's control loop; safe to call at any cadence, because every rule
        below is edge-triggered or clock-driven rather than per-call.
        """

        if int(digest.schema_version) != STATE_DIGEST_VERSION:
            raise WhispererError(
                f"state digest schema {digest.schema_version} is not "
                f"{STATE_DIGEST_VERSION}; refusing to forward state this "
                "component cannot read"
            )
        with self._lock:
            previous = self._previous
            self._previous = digest
            if previous is None:
                # The first digest of a session is a baseline, not a change.
                # Diffing against defaults would announce the battery and the
                # pose of a robot that has done nothing yet.
                #
                # It is still a TICK, and R13's invariant is about ticks: it is
                # counted here rather than quietly skipped, so that "ticks =
                # rows + skips" holds over ``observe`` calls and not merely over
                # the calls that happened to reach the watcher.
                self._pace_skip(PACE_SKIP_SESSION_BASELINE)
                return ()
            decisions: list[WhispererDecision] = []
            for event in self._diff(previous, digest):
                decisions.append(self._offer_locked(event, at=digest.at_s))
            decisions.extend(self._block_debounce(digest))
            decisions.extend(self._pace_watch(digest))
            return tuple(decisions)

    def offer(self, event: StateEvent, *, now: float | None = None) -> WhispererDecision:
        """Band and gate ONE already-classified event. Always logs."""

        at = self._clock() if now is None else float(now)
        with self._lock:
            return self._offer_locked(event, at=at)

    # ================================== card CURIO-1: the fourth mechanism's door
    def offer_curiosity(
        self, event: StateEvent, *, now: float | None = None
    ) -> WhispererDecision:
        """The MIDDLE band's fourth mechanism, calling in. Always logs.

        The block debounce and the pace watcher are middle-band mechanisms that
        live inside this class because their inputs are digests. The chatter
        scheduler's inputs are a clock, the owner's presence and the lane's
        busy state — none of which is in a :class:`StateDigest` — so it lives
        outside and this is the door it calls through. Structurally it is the
        same arrangement: the mechanism decides, ``_forward`` prices.

        What this door does NOT do is decide. It has no clock of its own, no
        cadence and no view of the owner: by the time an event reaches here the
        scheduler has already said yes, and everything below is the pricing that
        every other class pays — the dedup window, ``min_gap_s`` and the owner's
        ``max_updates_per_minute``. No curiosity class is in
        :data:`CRITICAL_KINDS`, so none of them can spend past that cap; the
        card's "the cap exceeded" seed is red because of that sentence.

        A class that is not curiosity is refused here and logged, rather than
        priced. A mechanism that will speak for any class it is handed is not a
        mechanism, and the middle band's whole claim is that each of its classes
        has exactly one way in.
        """

        at = self._clock() if now is None else float(now)
        with self._lock:
            if str(event.kind) not in CURIOSITY_KINDS:
                return self._record(
                    event,
                    band=band_of(str(event.kind)),
                    forwarded=False,
                    rule=RULE_CURIOSITY_DOOR_WRONG_CLASS,
                    at=at,
                )
            return self._forward(
                event, band=BAND_MIDDLE, rule=RULE_CHATTER_SCHEDULED, at=at
            )

    # ============================== END card CURIO-1 (Whisperer door) ==========

    # ==================================== card C4: the two receipt doors ======
    def note_plan_accepted(
        self, receipt: PlanAcceptedReceipt, *, now: float | None = None
    ) -> WhispererDecision:
        """The executive admitted a plan. Always logs; never raises.

        THE ONLY way :data:`KIND_PLAN_ACCEPTED` is produced. There is no differ
        branch and no detector, for the reason the class comment gives: the
        executive is the only component that knows an admission happened, and a
        ``nav_goal`` string diff would fire on re-issues, re-groundings and
        restatements — ``nav_tick`` with a longer period.

        Three refusals, all logged rather than raised, because this door is
        called from the plan-admission path and a narration fault must never be
        able to take down a plan the owner asked for:

        * the receipt is malformed (no task, unknown lineage) —
          :data:`RULE_PLAN_RECEIPT_INVALID`;
        * the executive did not accept it — :data:`RULE_PLAN_NOT_ADMITTED`;
        * it is the SAME plan for the SAME task as the last one admitted —
          :data:`RULE_PLAN_REISSUE`, the acceptance bar this card is named for.

        Past those it is priced exactly like every other always-band class: the
        dedup window, its own :data:`PLAN_ACCEPTED_MIN_GAP_S`, and the owner's
        ``max_updates_per_minute``. It is NOT in :data:`CRITICAL_KINDS`, so it
        can neither spend past that cap nor past the month's ceiling.
        """

        at = self._clock() if now is None else float(now)
        event = plan_accepted_event(receipt)
        band = band_of(KIND_PLAN_ACCEPTED)
        with self._lock:
            task = str(receipt.task_id)
            if not task or str(receipt.lineage) not in PLAN_LINEAGES:
                return self._record(
                    event, band=band, forwarded=False, rule=RULE_PLAN_RECEIPT_INVALID, at=at
                )
            if not receipt.accepted:
                return self._record(
                    event, band=band, forwarded=False, rule=RULE_PLAN_NOT_ADMITTED, at=at
                )
            identity = receipt.plan_identity()
            if self._plan_admitted.get(task) == identity:
                return self._record(
                    event, band=band, forwarded=False, rule=RULE_PLAN_REISSUE, at=at
                )
            # Remembered BEFORE the pricing, and deliberately: the admission
            # happened whether or not the owner's budget could afford the
            # sentence, so a later identical receipt is still a re-issue.
            self._plan_admitted[task] = identity
            while len(self._plan_admitted) > PLAN_ADMISSION_MEMORY:
                self._plan_admitted.pop(next(iter(self._plan_admitted)))
            return self._forward(event, band=band, rule=RULE_PLAN_ADMITTED, at=at)

    def note_reroute(
        self, receipt: RerouteReceipt, *, now: float | None = None
    ) -> WhispererDecision:
        """The navigator is taking another way. Always logs; never raises.

        :data:`KIND_REROUTE`'s first constructor, and the enforcement point for
        the band decision recorded at :data:`REROUTE_PER_MISSION_CAP`: the class
        stays CRITICAL — so the bench's G3 min-gap bug cannot come back and the
        monthly-ceiling answer stays one list — and each mission may announce at
        most :data:`REROUTE_PER_MISSION_CAP` of them. Over the cap, the item is
        dropped and logged; it is never billed.
        """

        at = self._clock() if now is None else float(now)
        event = reroute_event(receipt)
        band = band_of(KIND_REROUTE)
        with self._lock:
            if str(receipt.state) != SOCIAL_STATE_REROUTE:
                return self._record(
                    event, band=band, forwarded=False, rule=RULE_REROUTE_DOOR_WRONG_STATE, at=at
                )
            mission = str(event.detail.get("mission", ""))
            if mission != self._reroute_mission:
                self._reroute_mission = mission
                self._reroute_spoken = 0
            if self._reroute_spoken >= REROUTE_PER_MISSION_CAP:
                return self._record(
                    event, band=band, forwarded=False, rule=RULE_REROUTE_MISSION_CAP, at=at
                )
            decision = self._forward(event, band=band, rule=RULE_ALWAYS_BAND, at=at)
            if decision.forwarded:
                self._reroute_spoken += 1
            return decision

    # ================================= END card C4 (the two receipt doors) ====

    def undeliver(self, decision: WhispererDecision) -> WhispererDecision | None:
        """The lane's floor gate refused something this object said to forward.

        Nothing was spoken and nothing was billed, so the budget slot and the
        dedup entry are handed back — otherwise the owner's per-minute knob
        would be spent on silence, and a fact the model never heard would be
        deduplicated away the next time it mattered. The attempt itself stays in
        the log under :data:`RULE_NARRATION_FLOOR_REFUSED`, because a decision
        log that only records what worked is not an audit trail.
        """

        if not decision.forwarded:
            return None
        with self._lock:
            # A LATE undeliver — something else forwarded after this decision —
            # matches nothing here and pops nothing, deliberately: the later
            # forward has already taken the budget slot and advanced the clock,
            # and there is no slot of this decision's to give back. Only the
            # decision log records the refusal in that case. This is pre-C4
            # behaviour and A1 does not change it; it is asserted by test now
            # because it is the case the rewind below must not be reasoned about
            # in isolation from.
            if self._forwards and self._forwards[-1][0] == decision.at_s:
                self._forwards.pop()
                if decision.kind in KIND_MIN_GAP_S:
                    # Card C4. An own-gap class never advanced the shared clock,
                    # so there is nothing to rewind there; what it did take was
                    # its own spacing, and that is what comes back.
                    self._last_forward_by_kind.pop(decision.kind, None)
                else:
                    self._last_forward_at = self._last_shared_forward_at()
            self._folded += int(decision.folded)
            if self._dedup.get(decision.key) == decision.at_s:
                del self._dedup[decision.key]
            self.forwarded = max(0, self.forwarded - 1)
            if decision.kind == KIND_REROUTE and self._reroute_spoken > 0:
                # Card C4. The mission's reroute allowance is spent by a
                # sentence the owner HEARS. This one was refused at the lane's
                # floor, so it goes back with the budget slot and the dedup
                # entry — otherwise a mission could be talked out of its whole
                # allowance by a session that was never listening.
                self._reroute_spoken -= 1
            rule = decision.rule
            self.forwarded_by_rule[rule] = max(0, self.forwarded_by_rule.get(rule, 1) - 1)
            return self._record(
                StateEvent(kind=decision.kind, key=decision.key),
                band=decision.band,
                forwarded=False,
                rule=RULE_NARRATION_FLOOR_REFUSED,
                at=decision.at_s,
            )

    def _offer_locked(self, event: StateEvent, *, at: float) -> WhispererDecision:
        kind = str(event.kind)
        band = band_of(kind)
        if not band:
            return self._record(event, band="", forwarded=False, rule=RULE_UNKNOWN_KIND, at=at)
        if not self.config.enabled:
            # The owner's off switch. Voice-command traffic is unaffected: this
            # object is only ever consulted for robot-initiated state updates.
            return self._record(event, band=band, forwarded=False, rule=RULE_DISABLED, at=at)
        if band == BAND_NEVER:
            return self._record(event, band=band, forwarded=False, rule=RULE_NEVER_BAND, at=at)
        if kind == KIND_PLAN_ACCEPTED:
            # Card C4. The always band's only class with a door of its own. The
            # guard that makes an acceptance different from a nav_goal string
            # diff is in ``note_plan_accepted``; reaching the band table around
            # it would put the string diff back, one caller at a time.
            return self._record(
                event, band=band, forwarded=False, rule=RULE_PLAN_ACCEPTED_NEEDS_RECEIPT, at=at
            )
        if band == BAND_MIDDLE:
            # The middle band's own machines call ``_forward`` directly once they
            # have decided; an event that arrives here has not been through them,
            # so it has not been debounced and cannot prove its block was spoken.
            return self._record(
                event, band=band, forwarded=False, rule=RULE_MIDDLE_BAND_NEEDS_MECHANISM, at=at
            )
        return self._forward(event, band=band, rule=RULE_ALWAYS_BAND, at=at)

    # ------------------------------------------------------------- the differ
    def _diff(self, before: StateDigest, after: StateDigest) -> tuple[StateEvent, ...]:
        """Two digests in, semantic classes out. No raw note is ever read."""

        events: list[StateEvent] = []

        if after.emergency_stopped and not before.emergency_stopped:
            # Card R21. The class carries its door. A latch the owner caused
            # with their own voice and a latch the simulator raised on its own
            # are the same boolean and completely different news, and the fact
            # is the only thing the model is allowed to build a sentence from.
            origin = ESTOP_SOURCE_PHRASES.get(after.emergency_stop_source, "")
            events.append(
                StateEvent(
                    kind=KIND_EMERGENCY_STOP,
                    fact=(
                        "The robot's safety system reports it has latched an emergency "
                        f"stop{origin} and is not moving. It cannot move again until "
                        "the emergency stop is released."
                    ),
                    detail={"source": after.emergency_stop_source},
                )
            )
        elif before.emergency_stopped and not after.emergency_stopped:
            events.append(
                StateEvent(
                    kind=KIND_EMERGENCY_CLEAR,
                    fact=(
                        "The robot's safety system reports the emergency stop has been "
                        "released and motion is available again."
                    ),
                )
            )

        if after.battery_state != before.battery_state:
            events.append(
                StateEvent(
                    kind=KIND_BATTERY_STATE,
                    key=f"battery_state:{after.battery_state}",
                    fact=(
                        "The robot's power system reports the battery has gone from "
                        f"{before.battery_state} to {after.battery_state} and now reads "
                        f"{after.battery_percent:.0f} percent."
                    ),
                )
            )
        elif abs(after.battery_percent - before.battery_percent) >= 1.0:
            events.append(StateEvent(kind=KIND_BATTERY_PCT))

        if after.proximity_state != before.proximity_state:
            events.append(StateEvent(kind=KIND_PROXIMITY_CHURN))

        if after.navigating and after.nav_state != before.nav_state:
            events.append(StateEvent(kind=KIND_NAV_TICK))

        if after.position_dm != before.position_dm:
            events.append(StateEvent(kind=KIND_POSITION))

        if after.following and after.follow_distance_dm != before.follow_distance_dm:
            events.append(StateEvent(kind=KIND_FOLLOW_TICK))

        if _speed_band(after.owner_speed_mps) != _speed_band(before.owner_speed_mps):
            # The RAW pace change, which policy B forwarded and which made the
            # model assert wrong pacing ("Switching up to jog speed to keep up
            # with you." while the owner was jittering). It is noise; the
            # SEMANTIC class the pace watcher computes is what may be spoken.
            events.append(StateEvent(kind=KIND_OWNER_PACE_CHANGE))

        return tuple(events)

    # ------------------------------------------- mechanism 1 + 2: block/clear
    def _block_debounce(self, digest: StateDigest) -> tuple[WhispererDecision, ...]:
        """Block-entry debounce, and a clear that must earn its way out.

        Mechanism 1: a block is not spoken until it has held for
        :data:`BLOCK_DEBOUNCE_S`. Mechanism 2: a clear is spoken ONLY if its own
        block was forwarded — the bug the bench found in the drafted rules, where
        a closure announced a block the owner had never been told about ("the way
        is clear again" for a wait nobody mentioned).

        WHAT THE FIRST LIVE RUN CHANGED HERE (2026-08-20)
        -------------------------------------------------
        The first version timed the debounce against the runtime's block EPISODE
        number, which is bumped on every blocked-entry edge at the 10 Hz
        navigation cadence. On the live sim the navigator flapped
        ``blocked -> clear -> blocked`` between two digest ticks, the episode
        number changed under a robot that had not moved, and the debounce
        restarted — so "the robot has been stuck here for eight seconds" could
        never accumulate while the flap continued. The timer now runs on THIS
        object's own observation of blockedness, which is the fact the owner
        cares about; the episode number is captured when the block opens and is
        used only as the dedup identity, so two genuinely different waits are
        still two different sentences.
        """

        decisions: list[WhispererDecision] = []
        at = digest.at_s

        if digest.mission_blocked:
            if not self._block_open:
                self._block_open = True
                self._block_episode = int(digest.mission_block_episode)
                self._block_pending_since = at
                self._block_spoken = False
                decisions.append(
                    self._record(
                        StateEvent(kind=KIND_MISSION_BLOCKED, episode=self._block_episode),
                        band=BAND_MIDDLE,
                        forwarded=False,
                        rule=RULE_BLOCK_DEBOUNCE_HOLDING,
                        at=at,
                    )
                )
                return tuple(decisions)
            since = self._block_pending_since
            if self._block_spoken or since is None or (at - since) < BLOCK_DEBOUNCE_S:
                return ()
            self._block_pending_since = None
            event = StateEvent(
                kind=KIND_MISSION_BLOCKED,
                key=f"mission_blocked:{self._block_episode}",
                episode=self._block_episode,
                fact=_block_fact(digest),
            )
            decision = self._forward(
                event, band=BAND_MIDDLE, rule=RULE_BLOCK_DEBOUNCE_ELAPSED, at=at
            )
            self._block_spoken = decision.forwarded
            decisions.append(decision)
            return tuple(decisions)

        if self._block_open:
            closing = self._block_episode
            spoken = self._block_spoken
            self._block_open = False
            self._block_spoken = False
            self._block_pending_since = None
            self._block_episode = 0
            event = StateEvent(
                kind=KIND_MISSION_BLOCK_CLEAR,
                key=f"mission_block_clear:{closing}",
                episode=closing,
                fact=_clear_fact(digest),
            )
            if spoken:
                decisions.append(
                    self._forward(
                        event, band=BAND_MIDDLE, rule=RULE_CLEAR_AFTER_FORWARDED_BLOCK, at=at
                    )
                )
            else:
                decisions.append(
                    self._record(
                        event,
                        band=BAND_MIDDLE,
                        forwarded=False,
                        rule=RULE_CLEAR_WITHOUT_FORWARDED_BLOCK,
                        at=at,
                    )
                )
        return tuple(decisions)

    # ------------------------------- mechanism 3: upstream semantic pace class
    def _pace_watch(self, digest: StateDigest) -> tuple[WhispererDecision, ...]:
        """``pace_mismatch``, computed here so no downstream gate has to guess.

        The bench's decisive middle-band finding: reasoning-ON Gemma (33-49 s a
        call) still declined the real pace-mismatch fact and forwarded the
        jitter. Making the UPSTREAM emit the class deterministically was the
        cheaper and better answer, and it is what this is.

        Sustained, edge-triggered and latched: it fires once per mismatch
        episode and re-arms only when the mismatch actually resolves.

        WHAT CARD R13 CHANGED, AND WHY EACH PIECE IS HERE
        -------------------------------------------------
        The R11 version asked one question — *"is the owner measurably walking
        while a run was requested?"* — and answered "no" to everything else,
        including *"the owner cannot be measured at all"*, silently. E1's
        ``run-with-me-flex`` failed on exactly that: 58.8 seconds of a follow
        with ``pace_intent="run"``, a verifiable 2.2 m/s → 1.0 m/s owner in the
        path file, and **24 decision rows, none of them about pace**.

        So this now runs as a three-state machine over the owner's speed —
        *measured-running*, *measured-walking*, *unmeasurable* — and:

        * the unmeasurable state is announced to the log once when it opens and
          once when it closes (:data:`RULE_PACE_UNKNOWN` /
          :data:`RULE_PACE_KNOWN_RESUMED`), carrying the follow controller's own
          track status;
        * the sustained window **pauses** across the hole rather than resetting,
          because a walk interrupted by ten blind seconds is still the same
          walk, and resetting handed the robot a fresh silence every time the
          estimator flickered. The window now reads as *"one window's worth of
          MEASURED walking inside one follow episode, contiguous or not"* —
          blind time banks nothing on its own, and a measurably running owner
          still empties the bank;
        * every tick that writes no row increments a NAMED counter, so the
          decision log's silences are all accounted for somewhere.

        It still fires once per episode, still re-arms only on a real
        resolution, and still cannot compose an item without a measurement —
        :func:`_pace_mismatch_fact` refuses.
        """

        at = digest.at_s
        if not digest.following or digest.follow_pace_intent != "run":
            # The subject is gone. Whatever the watcher was in the middle of
            # goes with it, including an open hole: a follow that ended is not a
            # measurement that came back, and closing the hole with a
            # ``pace_known_resumed`` row would say it was.
            self._close_pace_unknown(at)
            self._pace_mismatch_since = None
            self._pace_mismatch_banked_s = 0.0
            self._pace_mismatch_open = False
            self._pace_skip(
                PACE_SKIP_NOT_FOLLOWING if not digest.following else PACE_SKIP_NO_RUN_INTENT
            )
            return ()

        speed = digest.owner_speed_mps
        if speed is None:
            if self._pace_unknown:
                self._pace_skip(PACE_SKIP_UNKNOWN_HOLDING)
                return ()
            # The hole opens. Bank whatever mismatch time has accrued so far and
            # stop the clock on it — do NOT throw it away.
            self._pace_unknown = True
            self._pace_unknown_since = at
            self.pace_unknown_episodes += 1
            if self._pace_mismatch_since is not None:
                self._pace_mismatch_banked_s += max(0.0, at - self._pace_mismatch_since)
                self._pace_mismatch_since = None
            return self._pace_logged(
                self._record(
                    StateEvent(
                        kind=KIND_PACE_UNKNOWN,
                        key=self._pace_unknown_key(digest),
                    ),
                    band=BAND_NEVER,
                    forwarded=False,
                    rule=RULE_PACE_UNKNOWN,
                    at=at,
                )
            )

        decisions: list[WhispererDecision] = []
        if self._pace_unknown:
            self._close_pace_unknown(at)
            decisions.append(
                self._record(
                    StateEvent(kind=KIND_PACE_UNKNOWN, key=self._pace_unknown_key(digest)),
                    band=BAND_NEVER,
                    forwarded=False,
                    rule=RULE_PACE_KNOWN_RESUMED,
                    at=at,
                )
            )

        if speed > WALK_CEILING_MPS:
            # Measured running: the request and the world agree, so the episode
            # resolves and the watcher re-arms for the next one.
            self._pace_mismatch_since = None
            self._pace_mismatch_banked_s = 0.0
            self._pace_mismatch_open = False
            return self._pace_settled(decisions, PACE_SKIP_OWNER_RUNNING)
        if self._pace_mismatch_open:
            return self._pace_settled(decisions, PACE_SKIP_ALREADY_ASKED)
        if self._pace_mismatch_since is None:
            self._pace_mismatch_since = at
        held = self._pace_mismatch_banked_s + max(0.0, at - self._pace_mismatch_since)
        if held < PACE_MISMATCH_WINDOW_S:
            return self._pace_settled(decisions, PACE_SKIP_WINDOW_ACCUMULATING)
        self._pace_mismatch_open = True
        event = StateEvent(
            kind=KIND_PACE_MISMATCH,
            key="pace_mismatch",
            fact=_pace_mismatch_fact(digest, window_s=PACE_MISMATCH_WINDOW_S),
        )
        decisions.append(
            self._forward(event, band=BAND_ALWAYS, rule=RULE_PACE_MISMATCH_SUSTAINED, at=at)
        )
        return self._pace_logged(*decisions)

    def _pace_unknown_key(self, digest: StateDigest) -> str:
        """Dedup identity for a blindness row, naming the estimator's own word.

        The status is the follow controller's, verbatim, so the row an auditor
        reads says ``pace_unknown:insufficient_motion`` rather than making them
        open the follow snapshot to find out what the robot thought was wrong.
        """

        status = " ".join(str(digest.owner_speed_status).split())
        return f"{KIND_PACE_UNKNOWN}:{status}" if status else KIND_PACE_UNKNOWN

    def _close_pace_unknown(self, at: float) -> float:
        """End an open hole and bank its length. Returns the seconds it held."""

        if not self._pace_unknown:
            return 0.0
        since = self._pace_unknown_since
        held = 0.0 if since is None else max(0.0, at - since)
        self.pace_unknown_seconds += held
        self._pace_unknown = False
        self._pace_unknown_since = None
        return held

    def _pace_skip(self, reason: str) -> None:
        """One tick of the watcher that wrote no row, with the reason why.

        Counting the tick HERE rather than at the top of :meth:`_pace_watch` is
        what makes the invariant structural: every exit from the watcher runs
        through this or through :meth:`_pace_logged`, so a future branch that
        forgets to account for itself does not increment ``ticks`` either, and
        the identity still holds instead of quietly drifting.
        """

        self.pace_watch_ticks += 1
        self.pace_watch_skips[reason] = self.pace_watch_skips.get(reason, 0) + 1

    def _pace_logged(self, *decisions: WhispererDecision) -> tuple[WhispererDecision, ...]:
        """One tick of the watcher that DID write. Counted per tick, not per row.

        A single tick can write twice — the measurement returns and the banked
        window is already past its ceiling — so the invariant is over ticks:
        ``ticks == logged + sum(skips)``.
        """

        self.pace_watch_ticks += 1
        self.pace_watch_logged += 1
        return decisions

    def _pace_settled(
        self, decisions: list[WhispererDecision], reason: str
    ) -> tuple[WhispererDecision, ...]:
        """Nothing more to say this tick: count it, unless the tick already wrote."""

        if decisions:
            return self._pace_logged(*decisions)
        self._pace_skip(reason)
        return ()

    # --------------------------------------------------- caps, dedup, folding
    def _forward(
        self, event: StateEvent, *, band: str, rule: str, at: float
    ) -> WhispererDecision:
        """Everything OUTSIDE the bands: dedup, min-gap, the owner's budget."""

        if not self.config.enabled:
            return self._record(event, band=band, forwarded=False, rule=RULE_DISABLED, at=at)

        kind = event.kind
        critical = kind in CRITICAL_KINDS
        key = event.dedup_key()
        ttl = CRITICAL_DEDUP_TTL_S if critical else DEDUP_TTL_S
        last_seen = self._dedup.get(key)
        if last_seen is not None and (at - last_seen) < ttl:
            return self._record(event, band=band, forwarded=False, rule=RULE_DEDUP, at=at)

        own_gap = kind in KIND_MIN_GAP_S
        if not critical:
            # Card C4. A class with its own spacing reads its own clock; every
            # other class reads the owner's knob against the shared one,
            # exactly as before.
            gap = float(KIND_MIN_GAP_S[kind]) if own_gap else float(self.config.min_gap_s)
            last = self._last_forward_by_kind.get(kind) if own_gap else self._last_forward_at
            if (
                kind not in MIN_GAP_EXEMPT_KINDS
                and gap > 0.0
                and last is not None
                and (at - last) < gap
            ):
                self._folded += 1
                return self._record(event, band=band, forwarded=False, rule=RULE_MIN_GAP, at=at)
            if self._spent(at) >= int(self.config.max_updates_per_minute):
                self._folded += 1
                return self._record(event, band=band, forwarded=False, rule=RULE_BUDGET, at=at)

        folded = self._folded
        self._folded = 0
        self._dedup[key] = at
        self._forwards.append((at, kind))
        # Card C4. The budget is shared by every class (the owner's cost knob
        # holds everything); the SPACING clock is not, for an own-gap class.
        if own_gap:
            self._last_forward_by_kind[kind] = at
        else:
            self._last_forward_at = at
        return self._record(
            event,
            band=band,
            forwarded=True,
            rule=RULE_CRITICAL_BYPASS if critical and rule == RULE_ALWAYS_BAND else rule,
            at=at,
            folded=folded,
        )

    def _last_shared_forward_at(self) -> float | None:
        """The most recent forward that advanced the SHARED spacing clock.

        Card C4 follow-up A1 (parcel-6c's second lens). ``undeliver`` used to
        rewind to ``_forwards[-1]``, which was right while every forward
        advanced the shared clock and became a DRIFT the moment one class
        stopped: for ``[status@t1, plan_accepted@t2, status@t3]``, undelivering
        the last one rewound the owner's spacing to t2 — a moment at which the
        owner had been told nothing that the shared clock is about. The
        direction was safe (more spacing, never less) and it was still wrong,
        because the clock has to mean one thing.

        Bounded by the budget window, exactly as the old expression was: a
        shared forward that has already aged out of ``_forwards`` cannot be
        rewound to, and ``None`` then means "no spacing is being held" — which
        is what the pre-C4 code answered in the same situation.
        """

        for at, kind in reversed(self._forwards):
            if kind not in KIND_MIN_GAP_S:
                return at
        return None

    def _spent(self, at: float) -> int:
        """Forwards inside the trailing window. Criticals are counted here too.

        Card P0-B, deliverable 4. The window was a literal ``60.0`` here, which
        made the owner's narration rate half a knob: ``max_updates_per_minute``
        could be set and the minute could not, so the only rates purchasable
        were whole multiples of one-per-minute. It is now
        ``whisperer.window_s``, validated, defaulting to the same 60.0 — a
        config that does not mention it counts exactly the minute it always did.
        """

        window = float(getattr(self.config, "window_s", DEFAULT_WHISPERER_WINDOW_S))
        if not window > 0.0:
            # Belt and braces: the loader refuses this, and a hand-built
            # WhispererConfig must not be able to divide the cap by nothing.
            window = DEFAULT_WHISPERER_WINDOW_S
        while self._forwards and (at - self._forwards[0][0]) >= window:
            self._forwards.popleft()
        return len(self._forwards)

    def _record(
        self,
        event: StateEvent,
        *,
        band: str,
        forwarded: bool,
        rule: str,
        at: float,
        folded: int = 0,
    ) -> WhispererDecision:
        self._seq += 1
        text = compose(event, folded=folded) if forwarded else ""
        decision = WhispererDecision(
            seq=self._seq,
            at_s=at,
            kind=event.kind,
            key=event.dedup_key(),
            band=band,
            forwarded=forwarded,
            rule=rule,
            text=text,
            folded=folded,
            updates_this_minute=self._spent(at),
        )
        self.decisions.append(decision)
        if forwarded:
            self.forwarded += 1
            self.forwarded_by_rule[rule] = self.forwarded_by_rule.get(rule, 0) + 1
        else:
            self.suppressed += 1
            self.suppressed_by_rule[rule] = self.suppressed_by_rule.get(rule, 0) + 1
        return decision

    # ---------------------------------------------------------------- reading
    def decision_rows(self, limit: int = 0) -> list[dict[str, object]]:
        with self._lock:
            rows = [decision.as_dict() for decision in self.decisions]
        return rows[-limit:] if limit > 0 else rows

    def snapshot(self, now: float | None = None) -> dict[str, object]:
        """What ``/api/state`` publishes, including what the knob suppressed."""

        at = self._clock() if now is None else float(now)
        with self._lock:
            last = self.decisions[-1].as_dict() if self.decisions else None
            return {
                "enabled": self.config.enabled,
                "max_updates_per_minute": self.config.max_updates_per_minute,
                "min_gap_s": self.config.min_gap_s,
                # Card P0-B. ``updates_this_minute`` is only readable next to the
                # window it was counted over, now that the window is a knob.
                "window_s": getattr(self.config, "window_s", DEFAULT_WHISPERER_WINDOW_S),
                "updates_this_minute": self._spent(at),
                "folded": self._folded,
                "forwarded": self.forwarded,
                "suppressed": self.suppressed,
                "suppressed_by_rule": dict(self.suppressed_by_rule),
                "forwarded_by_rule": dict(self.forwarded_by_rule),
                "schema_version": STATE_DIGEST_VERSION,
                "pace_watch": self._pace_watch_snapshot(at),
                "last": last,
            }

    def _pace_watch_snapshot(self, at: float) -> dict[str, object]:
        """The watcher's ledger, for ``/api/state`` and for the eval packs.

        Card R13. The decision ring holds ~6 minutes; a walk is longer than
        that, and the owner-session capture that motivated this card had
        aggregates and one ``last`` row and nothing else. These counters are
        cumulative and un-evictable, so a session artifact can answer "was the
        pace watcher blind, and for how long" without a live process.
        """

        return {
            "ticks": self.pace_watch_ticks,
            "logged": self.pace_watch_logged,
            "skips": dict(self.pace_watch_skips),
            "accounted": (
                self.pace_watch_logged + sum(self.pace_watch_skips.values())
                == self.pace_watch_ticks
            ),
            "pace_unknown": self._pace_unknown,
            "pace_unknown_for_s": (
                0.0
                if not self._pace_unknown or self._pace_unknown_since is None
                else max(0.0, at - self._pace_unknown_since)
            ),
            "pace_unknown_episodes": self.pace_unknown_episodes,
            "pace_unknown_seconds": round(self.pace_unknown_seconds, 3),
            "mismatch_banked_s": round(self._pace_mismatch_banked_s, 3),
            "mismatch_open": self._pace_mismatch_open,
        }


# ================================================ card P2-B: the owner watcher
#: Where an owner sighting came from. A LABEL on the sample, carried into the
#: decision log's detail — never a gate, and never a threshold of its own: the
#: confidence is the number that decides, and the source is what lets an auditor
#: tell "the mocap said so" from "the camera thinks so" after the fact.
OWNER_SOURCE_MOCAP = "mocap"
OWNER_SOURCE_UWB = "uwb"
OWNER_SOURCE_PIXELS = "pixels"


@dataclass(frozen=True)
class OwnerPresence:
    """One sighting (or one non-sighting) of the owner. The watcher's only input.

    Deliberately the smallest thing that can carry the question: is the owner
    here, how sure are we, and who says so. It is NOT ``OwnerTrackV1`` — card
    P1-C is building the pixel track that will produce one — because this module
    must not learn the shape of a perception contract to decide whether to say
    hello. The runtime adapts whatever track exists into this, which is what
    makes P1-C's track a drop-in: a better ``confidence`` and a different
    ``source``, and not one line of this file changes.
    """

    present: bool
    at_s: float
    confidence: float = 1.0
    source: str = OWNER_SOURCE_MOCAP

    def credible(self, minimum: float) -> bool:
        """Present AND sure enough. The two halves of "the owner is here"."""

        return bool(self.present) and float(self.confidence) >= float(minimum)


def _away_phrase(seconds: float) -> str:
    """How long the owner was gone, in the unit a person would actually use."""

    if seconds < 90.0:
        return "a minute or so"
    if seconds < 3600.0:
        return f"about {round(seconds / 60.0)} minutes"
    hours = seconds / 3600.0
    if hours < 1.5:
        return "about an hour"
    if hours < 24.0:
        return f"about {round(hours)} hours"
    days = round(hours / 24.0)
    return "about a day" if days <= 1 else f"about {days} days"


class OwnerEventWatcher:
    """When the dog should say something to the OWNER. Owns no lane, no model.

    THE DEFECT THIS CLOSES
    ----------------------
    Every class in this module before card P2-B has the robot as its subject: it
    arrived, it is blocked, its battery is low. So the whisperer could tell you
    everything about the robot and had no vocabulary at all for the fact that you
    had just walked in — and the idle lane hung up after ten minutes, so by the
    time you came back there was often nothing there to notice you with. P0-B
    made the lane stay live (``idle_close_after_s: 0``); this makes something
    happen when it does.

    THE SHAPE
    ---------
    A state machine over presence samples, exactly like the block debounce and
    the pace watcher, and it obeys the same three house rules:

    1. **At most ONE event per observe call.** Not a policy — a return type. An
       appearance, a greeting and a question-of-the-day that all came due on the
       same tick cannot become three sentences in one breath, whatever the cap
       says, and the appearance wins because it is the news.
    2. **Every event is latched per episode.** One appearance, one greeting; one
       question per calendar day. The whisperer's cap is the SECOND line of
       defence against a storm and this is the first, because a cap that is
       constantly saturated by greetings has stopped being a cost knob.
    3. **It decides nothing about affordability.** It produces
       :class:`StateEvent`s and hands them to :meth:`Whisperer.offer`, which
       applies the band, the dedup, the min-gap and the owner's per-window cap.
       Nothing here is critical and nothing here bypasses anything.

    The clock is monotonic and injectable; ``day_key`` is a SEPARATE wall-clock
    callable, because "once a day" is a question about calendars and every other
    number in this class is a question about durations. Mixing the two is how you
    get a robot that asks its question of the day twice at midnight.
    """

    def __init__(
        self,
        *,
        config: OwnerEventsConfig,
        clock: Callable[[], float] = time.monotonic,
        day_key: Callable[[], str] | None = None,
    ) -> None:
        self.config = config
        self._clock = clock
        self._day_key = day_key or (lambda: time.strftime("%Y-%m-%d"))
        self._lock = threading.RLock()

        self._present = False
        self._present_since: float | None = None
        self._absent_since: float | None = None
        self._episode = 0
        self._announced_episode = 0
        self._last_greeting_at: float | None = None
        self._last_turn_at: float | None = None
        self._question_day = ""

        # counters, for ``/api/state`` and for the status doc's numbers
        self.samples = 0
        self.appearances = 0
        self.events_by_kind: dict[str, int] = {}
        self.last_confidence = 0.0
        self.last_source = ""

    # ------------------------------------------------------------- the doors
    def note_turn(self, at: float | None = None) -> None:
        """Somebody said something. The session ledger's half of the input.

        Called for BOTH sides of the conversation on purpose: a greeting is due
        after silence, and a robot that had just answered a question has not been
        silent. This is what keeps ``greeting_due`` from interrupting a
        conversation that is already happening.
        """

        with self._lock:
            self._last_turn_at = self._at(at)

    def observe(self, sample: OwnerPresence) -> tuple[StateEvent, ...]:
        """One presence sample in, at most one classified event out."""

        with self._lock:
            self.samples += 1
            self.last_confidence = float(sample.confidence)
            self.last_source = str(sample.source)
            at = float(sample.at_s)
            here = sample.credible(self.config.min_confidence)
            if here:
                self._enter_locked(at)
            else:
                self._leave_locked(at)
            if not self.config.enabled or not here:
                return ()
            event = (
                self._appearance_locked(at, sample)
                or self._question_locked(at)
                or self._greeting_locked(at)
            )
            if event is None:
                return ()
            self.events_by_kind[event.kind] = self.events_by_kind.get(event.kind, 0) + 1
            return (event,)

    def snapshot(self) -> dict[str, object]:
        """What ``/api/state`` publishes about the owner-event watcher."""

        with self._lock:
            return {
                "config": self.config.as_dict(),
                "present": self._present,
                "episode": self._episode,
                "announced_episode": self._announced_episode,
                "appearances": self.appearances,
                "samples": self.samples,
                "events_by_kind": dict(self.events_by_kind),
                "last_confidence": round(self.last_confidence, 4),
                "last_source": self.last_source,
                "question_day": self._question_day,
            }

    # ------------------------------------------------------------- internals
    def _at(self, at: float | None) -> float:
        return self._clock() if at is None else float(at)

    def _enter_locked(self, at: float) -> None:
        if self._present:
            return
        self._present = True
        self._present_since = at
        self._episode += 1
        self.appearances += 1

    def _leave_locked(self, at: float) -> None:
        if not self._present:
            return
        self._present = False
        self._present_since = None
        self._absent_since = at

    def _away_seconds(self, at: float) -> float | None:
        """How long the owner was away before this visit. ``None`` = first ever."""

        if self._absent_since is None:
            return None
        return max(0.0, at - self._absent_since)

    def _appearance_locked(self, at: float, sample: OwnerPresence) -> StateEvent | None:
        since = self._present_since
        if since is None or self._announced_episode == self._episode:
            return None
        if (at - since) < self.config.appear_debounce_s:
            return None
        away = self._away_seconds(at)
        if away is not None and away < self.config.absence_s:
            # The same visit. The tracker blinked, or the owner stepped behind a
            # chair; a dog does not greet you twice for walking past a doorway.
            # The episode is still marked announced so the debounce does not
            # re-arm on every sample of the same blink.
            self._announced_episode = self._episode
            return None
        self._announced_episode = self._episode
        # An appearance IS a greeting. Recording it here is what stops
        # ``greeting_due`` from firing a second hello ten seconds later.
        self._last_greeting_at = at
        detail = {
            "episode": self._episode,
            "away_s": None if away is None else round(away, 1),
            "confidence": round(float(sample.confidence), 4),
            "source": str(sample.source),
        }
        long_absence_s = self.config.long_absence_h * 3600.0
        if away is not None and away >= long_absence_s:
            hours = max(1, round(away / 3600.0))
            return StateEvent(
                kind=KIND_OWNER_RETURNED,
                key=f"owner_returned:{hours}h",
                fact=(
                    "The robot's owner tracking reports the owner has just come back "
                    f"into view after being away for {_away_phrase(away)}."
                ),
                detail=detail,
            )
        seen_before = "" if away is None else f" after {_away_phrase(away)} away"
        return StateEvent(
            kind=KIND_OWNER_APPEARED,
            key=f"owner_appeared:{self._episode}",
            fact=(
                "The robot's owner tracking reports the owner has just come into "
                f"view{seen_before}, and the robot has not greeted them yet."
            ),
            detail=detail,
        )

    def _question_locked(self, at: float) -> StateEvent | None:
        if not self.config.question_of_the_day:
            return None
        since = self._present_since
        if since is None or (at - since) < self.config.appear_debounce_s:
            return None
        today = str(self._day_key())
        if today == self._question_day:
            return None
        self._question_day = today
        return StateEvent(
            kind=KIND_QUESTION_OF_THE_DAY,
            key=f"question_of_the_day:{today}",
            fact=(
                "The robot has not yet asked the owner its one question of the day, "
                "and the owner is here now."
            ),
            detail={"day": today, "episode": self._episode},
        )

    def _greeting_locked(self, at: float) -> StateEvent | None:
        interval = float(self.config.greeting_interval_s)
        if interval <= 0.0:
            return None
        since = self._present_since
        if since is None or (at - since) < self.config.appear_debounce_s:
            return None
        marks = [value for value in (self._last_greeting_at, self._last_turn_at) if value is not None]
        # No conversation and no greeting yet this session: the owner has been
        # present since ``since``, and that is the silence being measured.
        quiet_since = max(marks) if marks else since
        quiet_for = at - quiet_since
        if quiet_for < interval:
            return None
        self._last_greeting_at = at
        return StateEvent(
            kind=KIND_GREETING_DUE,
            key=f"greeting_due:{self._episode}:{int(quiet_since)}",
            fact=(
                "The robot's owner tracking reports the owner has been nearby for a "
                f"while and neither of them has said anything for {_away_phrase(quiet_for)}."
            ),
            detail={"quiet_for_s": round(quiet_for, 1), "episode": self._episode},
        )


# ============================================ card CURIO-1: the chatter layer
#
# WHY THERE IS A SCHEDULER AND NOT A THRESHOLD
# --------------------------------------------
# The learned map grows on a camera frame — 2 Hz, for the length of a walk. Every
# other producer in this module is edge-triggered on something rare (a latch, an
# arrival, a person stepping into the path); this one is edge-triggered on
# something CONSTANT. So "the map grew, therefore say something" is not a
# cadence, it is a firehose with a band table in front of it, and the band table
# would spend the owner's whole minute on the first six lampposts of the walk.
#
# What a companion needs instead is a rate: something like a remark every few
# minutes, arriving at irregular times rather than on a metronome, and never
# while you are talking. That is a Poisson process with an admission gate, and
# it is what this class is.
#
# THE THREE CLOCKS, DELIBERATELY SEPARATE
# ---------------------------------------
# 1. ``clock`` — monotonic. Durations: the gap, the quiet window. Injectable, so
#    every test below runs on a frozen clock with no sleeping.
# 2. ``time_band`` — WALL clock, and a separate callable for exactly P2-B's
#    ``day_key`` reason: "is it the middle of the night" is a question about
#    calendars and time zones, and mixing it into a monotonic duration is how you
#    get a dog that goes quiet at 3 a.m. UTC in a house on the US west coast.
# 3. ``rng`` — the gap draw. Injectable and seeded in every measurement, because
#    "3 to 6 remarks in 120 seconds" is a claim about a distribution and a claim
#    about a distribution that cannot be re-run is an anecdote.
#
# WHAT "QUIET" MEANS HERE, AND WHY IT IS NOT P2-B's MEANING
# ---------------------------------------------------------
# ``OwnerEventWatcher.note_turn`` counts BOTH sides of the conversation, because
# a greeting is due after silence and a robot that just answered you has not been
# silent. This class's ``note_turn`` counts the owner's exchanges ONLY — an owner
# turn, and the robot's answer to one — and deliberately NOT the robot's own
# unprompted remarks. The two jobs are different:
#
#   * ``quiet_s`` protects a CONVERSATION. It exists so the dog does not talk
#     over you, or into the three-second gap where you are thinking.
#   * the Poisson gap paces a MONOLOGUE. It is what stops five remarks in a row.
#
# Feeding the monologue back into the conversation clock would collapse the two
# and make the faster of them meaningless. With no exchange at all — a session
# nobody has spoken on — there is no conversation to protect, so the quiet
# condition is satisfied and the gap is the only thing pacing the dog. That is
# the case the 120 s roam measures.

#: Why a scheduler tick produced no remark. R13's discipline, applied to a
#: second watcher: every tick lands in exactly one of these or is admitted —
#: never neither — so ``ticks == admitted + sum(skips)`` is an invariant with a
#: test on it, and "the dog was quiet for two minutes" is a number rather than an
#: absence in a log.
CHATTER_SKIP_DISABLED = "curiosity_disabled"
CHATTER_SKIP_NO_OWNER = "owner_not_present"
CHATTER_SKIP_LANE_BUSY = "lane_busy"
CHATTER_SKIP_ACTIVITY_BUSY = "activity_running"
CHATTER_SKIP_QUIET_HOURS = "quiet_hours"
CHATTER_SKIP_CONVERSATION = "conversation_not_quiet"
#: The IDLE gap: the Poisson draw around ``mean_gap_s`` has not elapsed.
CHATTER_SKIP_GAP_HOLDING = "gap_holding"
#: The STIMULUS gap: something HAS happened, and the fixed
#: ``stimulus_min_gap_s`` floor since the last remark has not elapsed. Separate
#: from the reason above because they are different clocks over different kinds
#: of remark, and a log that called both "gap_holding" could not tell an
#: operator which knob to turn.
CHATTER_SKIP_STIMULUS_GAP = "stimulus_gap_holding"

CHATTER_SKIP_REASONS: frozenset[str] = frozenset(
    {
        CHATTER_SKIP_DISABLED,
        CHATTER_SKIP_NO_OWNER,
        CHATTER_SKIP_LANE_BUSY,
        CHATTER_SKIP_ACTIVITY_BUSY,
        CHATTER_SKIP_QUIET_HOURS,
        CHATTER_SKIP_CONVERSATION,
        CHATTER_SKIP_GAP_HOLDING,
        CHATTER_SKIP_STIMULUS_GAP,
    }
)

#: The time-of-day bands. Four, because a companion needs to know the difference
#: between "good morning" and "still up?" and does not need more resolution than
#: that. Boundaries are local wall-clock hours.
TIME_BAND_MORNING = "morning"
TIME_BAND_AFTERNOON = "afternoon"
TIME_BAND_EVENING = "evening"
TIME_BAND_NIGHT = "night"

TIME_BANDS: frozenset[str] = frozenset(
    {TIME_BAND_MORNING, TIME_BAND_AFTERNOON, TIME_BAND_EVENING, TIME_BAND_NIGHT}
)

#: How each band reads inside a FACT. One short clause, never a timestamp: the
#: R21 lesson about the e-stop door applies here too — the class is the thing
#: that is spoken, and the raw number stays in ``detail``.
TIME_BAND_PHRASES: Mapping[str, str] = {
    TIME_BAND_MORNING: "It is the morning.",
    TIME_BAND_AFTERNOON: "It is the afternoon.",
    TIME_BAND_EVENING: "It is the evening.",
    TIME_BAND_NIGHT: "It is the middle of the night.",
}


def time_band_of(hour: int) -> str:
    """Local hour -> band. Total, and deliberately not configurable.

    A band table an operator can re-cut is a band table that disagrees with the
    sentence in :data:`TIME_BAND_PHRASES` that renders it. The knob the owner
    gets is ``curiosity.night_quiet``, which decides whether the NIGHT band
    silences the dog — not where night begins.
    """

    value = int(hour) % 24
    if 5 <= value < 12:
        return TIME_BAND_MORNING
    if 12 <= value < 17:
        return TIME_BAND_AFTERNOON
    if 17 <= value < 22:
        return TIME_BAND_EVENING
    return TIME_BAND_NIGHT


def _local_time_band() -> str:
    return time_band_of(time.localtime().tm_hour)


@dataclass(frozen=True)
class ChatterState:
    """Everything outside this module that can veto a remark, as one value.

    Deliberately three booleans and a clock reading rather than a lane, a
    coordinator and a track: this class must not learn the shape of the lane to
    decide whether now is a good moment, or the lane's next refactor becomes a
    change to the cadence. The runtime adapts what it has into this — the same
    move :class:`OwnerPresence` makes for P2-B.
    """

    at_s: float
    #: Is the owner here at all. From the same presence sample P2-B's watcher
    #: reads, so the two cannot disagree about whether anybody is listening.
    owner_present: bool = False
    #: The lane cannot take a narration right now: a hosted response is playing,
    #: a response is outstanding, or the OWNER has spoken and has not been
    #: answered. The lane's floor gate refuses all three anyway — this is the
    #: same rule read one layer earlier, so that a remark the lane would drop is
    #: never drawn from the budget in the first place.
    lane_busy: bool = True
    #: A physical activity is running. ``prompts/functions/patrol.yaml``: *social
    #: actions can wait until an idle checkpoint*. This is that sentence, read
    #: against the coordinator that already owns checkpoint semantics.
    activity_running: bool = False


class ChatterScheduler:
    """WHEN the dog may remark on the world. Owns no lane, no map and no model.

    Same shape as every other decision object in this file: it takes a state and
    returns an answer, it counts every tick, and it has no thread. It does not
    know what the remark will be about — the runtime picks that — because "is now
    a good moment" and "is there anything worth saying" are different questions
    and folding them together is how a scheduler quietly becomes a content
    filter.
    """

    def __init__(
        self,
        *,
        config: CuriosityConfig,
        clock: Callable[[], float] = time.monotonic,
        rng: random.Random | None = None,
        time_band: Callable[[], str] | None = None,
    ) -> None:
        self.config = config
        self._clock = clock
        self._rng = rng if rng is not None else random.Random()
        self._time_band = time_band or _local_time_band
        self._lock = threading.RLock()

        self._anchor_at: float | None = None
        self._next_gap_s: float = self._draw_gap()
        self._last_remark_at: float | None = None
        self._last_turn_at: float | None = None

        # counters, for ``/api/state`` and for the status doc's numbers
        self.ticks = 0
        self.admitted = 0
        self.remarks = 0
        self.refusals = 0
        self.skips: dict[str, int] = {}
        self.last_band = ""

    # ------------------------------------------------------------- the doors
    def note_turn(self, at: float | None = None) -> None:
        """An OWNER exchange happened. Starts the quiet window over.

        See the module note above: the robot's own unprompted remarks
        deliberately do NOT come through here. ``note_remark`` is their door.
        """

        with self._lock:
            self._last_turn_at = self._clock() if at is None else float(at)

    def note_remark(self, at: float | None = None) -> None:
        """A remark was EXPRESSED. Re-arms both clocks.

        Called when the owner actually got something: a narrated sentence, or —
        when the per-minute cap was already spent — the free gesture that
        replaced it. **The gesture IS the remark** for the fact it stood in for;
        one noticing produces one expression, billed or free, and the fact is
        not also queued for a sentence later (see
        ``RobotRuntime._curiosity_free_gesture``). That is a deliberate reading
        of the card's work item 3 and it is written down here because the
        alternative — gesture now, sentence later — gives the owner two of
        everything and was the other live option.

        NOT called on an offer the whisperer or the lane refused: nothing was
        heard, so paying a silence for it would make the owner's cost knob buy
        quiet twice. ``note_refusal`` is that path.
        """

        with self._lock:
            now = self._clock() if at is None else float(at)
            self._last_remark_at = now
            self._anchor_at = now
            self._next_gap_s = self._draw_gap()
            self.remarks += 1

    def due(self, state: ChatterState, *, stimulus: bool = False) -> bool:
        """Is now a moment to say something. Counts the tick either way.

        ``stimulus=True`` means the caller HAS something that just happened and
        is asking whether it may say it; ``stimulus=False`` means nothing has
        happened and it is asking whether the quiet is long enough to be worth
        filling. Everything above the gap is identical for the two — the owner
        has to be there, the lane has to be free, the coordinator has to be at a
        checkpoint, the night has to be over and the conversation has to be
        quiet. Only the LAST test differs, and it is the whole of the correction
        pass's ruling 6 (see :data:`STIMULUS_KINDS`).
        """

        with self._lock:
            self.ticks += 1
            at = float(state.at_s)
            band = str(self._time_band())
            self.last_band = band
            if self._anchor_at is None:
                # The first tick is the anchor. Measuring the first gap from
                # process start would have the dog owe a remark the instant a
                # session opens on a runtime that had been up for an hour.
                self._anchor_at = at
            if not self.config.enabled:
                return self._skip(CHATTER_SKIP_DISABLED)
            if self.config.require_owner_present and not state.owner_present:
                return self._skip(CHATTER_SKIP_NO_OWNER)
            if state.lane_busy:
                return self._skip(CHATTER_SKIP_LANE_BUSY)
            if state.activity_running:
                return self._skip(CHATTER_SKIP_ACTIVITY_BUSY)
            if self.config.night_quiet and band == TIME_BAND_NIGHT:
                return self._skip(CHATTER_SKIP_QUIET_HOURS)
            quiet_for = self._quiet_for(at)
            if quiet_for is not None and quiet_for < float(self.config.quiet_s):
                return self._skip(CHATTER_SKIP_CONVERSATION)
            since = at - float(self._anchor_at)
            if stimulus:
                if since < float(self.config.stimulus_min_gap_s):
                    return self._skip(CHATTER_SKIP_STIMULUS_GAP)
            elif since < self._next_gap_s:
                return self._skip(CHATTER_SKIP_GAP_HOLDING)
            self.admitted += 1
            return True

    def note_refusal(self, at: float | None = None) -> None:
        """The offer was made and refused downstream. Stop retrying every second.

        Correction-pass note. Without this the feed re-offered a refused
        candidate on every 1 Hz tick — the dedup window, the min-gap or the
        monthly ceiling would refuse it again and again, and the decision log
        filled with a suppression row a second. The anchor moves so the
        stimulus floor restarts; the Poisson draw is deliberately NOT redrawn,
        because a remark nobody heard must not buy the owner a fresh
        four-minute silence (which is the same reasoning ``undeliver`` uses to
        hand the budget slot back).
        """

        with self._lock:
            self._anchor_at = self._clock() if at is None else float(at)
            self.refusals += 1

    def band(self) -> str:
        """The current time-of-day band, for the FACT's own clause."""

        with self._lock:
            return str(self._time_band())

    def snapshot(self) -> dict[str, object]:
        """Everything the chatter layer did, as a JSON-safe dict.

        A public accessor, and not yet on the wire: publishing it belongs in
        ``runtime.realtime_snapshot``, which is another card's region and which
        this card therefore did not touch. ``RobotRuntime.curiosity_snapshot()``
        is the door; wiring it into ``/api/state`` is one key, and the status
        doc records it as a handoff rather than pretending it is done.
        """

        with self._lock:
            return {
                "config": self.config.as_dict(),
                "ticks": self.ticks,
                "admitted": self.admitted,
                "remarks": self.remarks,
                "refusals": self.refusals,
                "skips": dict(self.skips),
                "next_gap_s": round(self._next_gap_s, 3),
                "last_band": self.last_band,
                "last_remark_at_s": self._last_remark_at,
            }

    # ------------------------------------------------------------- internals
    def _skip(self, reason: str) -> bool:
        self.skips[reason] = self.skips.get(reason, 0) + 1
        return False

    def _quiet_for(self, at: float) -> float | None:
        """Seconds since the last OWNER exchange. ``None`` = there has been none.

        ``None`` is not "zero seconds of quiet". A session nobody has spoken on
        has no conversation to interrupt, so the quiet condition is satisfied
        rather than blocking — which is the difference between a companion that
        goes first and one that waits to be talked to before it will talk.
        """

        if self._last_turn_at is None:
            return None
        return max(0.0, at - float(self._last_turn_at))

    def _draw_gap(self) -> float:
        """One exponential inter-arrival time. Poisson gaps, by definition.

        Clamped below at ``min_gap_floor_s`` because an exponential draw can come
        back at 0.2 s and a remark that lands 0.2 s after the last one is a
        stutter, not a cadence. The whisperer's own ``min_gap_s`` would refuse it
        anyway — this is the same bound one layer earlier, so the budget is not
        spent on something that was always going to be dropped.
        """

        mean = float(self.config.mean_gap_s)
        if not mean > 0.0:
            return float(self.config.min_gap_floor_s)
        return max(float(self.config.min_gap_floor_s), self._rng.expovariate(1.0 / mean))


class FarewellWatcher:
    """The falling edge of the owner's presence. Card CURIO-1's fifth class.

    P2-B's :class:`OwnerEventWatcher` is a closed block and this card does not
    edit it, so the goodbye is a SECOND watcher over the SAME
    :class:`OwnerPresence` samples rather than a fifth branch inside the first
    one. The runtime feeds both from one ``owner_presence_sample()`` call, which
    is what keeps them from disagreeing about whether you are in the room.

    It is deliberately not symmetric with the appearance classes. An appearance
    is announced after a DEBOUNCE (the tracker must hold you for a moment before
    the dog says hello); a departure is announced after an ABSENCE (the tracker
    must fail to find you for a while before the dog decides you have gone), and
    the second number is much larger than the first because the cost of the two
    mistakes is not the same: a greeting fired at a passing shadow is charming,
    and a goodbye fired at one is the robot saying farewell to your back while
    you stand in front of it.
    """

    def __init__(
        self,
        *,
        config: CuriosityConfig,
        min_confidence: float = 0.3,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.config = config
        self._min_confidence = float(min_confidence)
        self._clock = clock
        self._lock = threading.RLock()

        self._present = False
        self._ever_seen = False
        self._gone_since: float | None = None
        self._episode = 0
        self._announced_episode = 0

        self.samples = 0
        self.farewells = 0

    def observe(self, sample: OwnerPresence) -> tuple[StateEvent, ...]:
        """One presence sample in, at most one farewell out."""

        with self._lock:
            self.samples += 1
            at = float(sample.at_s)
            here = sample.credible(self._min_confidence)
            if here:
                if not self._present:
                    self._present = True
                    self._episode += 1
                self._ever_seen = True
                self._gone_since = None
                return ()
            if self._present:
                self._present = False
                self._gone_since = at
                return ()
            if not self._ever_seen or self._gone_since is None:
                # Never seen at all. A robot that boots in an empty room has not
                # been left, and saying goodbye to nobody is the single most
                # obviously broken thing this class could do.
                return ()
            if not self.config.farewell or self._announced_episode == self._episode:
                return ()
            gone_for = at - float(self._gone_since)
            if gone_for < float(self.config.farewell_after_s):
                return ()
            self._announced_episode = self._episode
            self.farewells += 1
            return (
                StateEvent(
                    kind=KIND_OWNER_LEFT,
                    key=f"owner_left:{self._episode}",
                    fact=(
                        "The robot's owner tracking reports the owner has gone out "
                        "of view and has not come back."
                    ),
                    detail={
                        "episode": self._episode,
                        "gone_for_s": round(gone_for, 1),
                        "source": str(sample.source),
                    },
                ),
            )

    def snapshot(self) -> dict[str, object]:
        with self._lock:
            return {
                "present": self._present,
                "ever_seen": self._ever_seen,
                "episode": self._episode,
                "announced_episode": self._announced_episode,
                "samples": self.samples,
                "farewells": self.farewells,
            }


#: The FACT sentence for each curiosity class, as a template over one place name.
#: Templates rather than free text for R11's founding reason: the differ is the
#: only thing that turns state into a class, and the class is the only thing a
#: gate downstream may read. A producer that could hand this module a sentence
#: could hand it a hallucination, and no band table would notice.
CURIOSITY_FACTS: Mapping[str, str] = {
    KIND_NOVEL_OBJECT: (
        "The robot has just seen something in this place it had not seen here "
        "before, and its own map now has a row for it: {indefinite}."
    ),
    KIND_PLACE_LEARNED: (
        "The robot's map has just accepted a name for a place it already knew "
        "about: it can be called {definite} from now on."
    ),
    KIND_SCENE_CHANGE: (
        "Something the robot had learned about — {definite} — is not where its "
        "map last saw it."
    ),
    KIND_ASK_ABOUT: (
        "The robot is looking at something it cannot confirm. The closest thing "
        "in its own map is {definite}, and it is NOT sure that is what this is."
    ),
    KIND_IDLE_REMARK: (
        "Nothing new has happened for a while. Something the robot has already "
        "learned about in this place is {definite}."
    ),
}

#: Words that already ARE an article. Correction pass, 2026-08-22: the templates
#: used to hard-code ``the {place}`` and the map's vocabulary is free to contain
#: a name that starts with one — ``the front step`` rendered as *"the the front
#: step"*. The article is decided per NAME rather than per template, because the
#: template cannot know what the map learned.
_ARTICLES = ("the ", "a ", "an ")


def _definite_phrase(place: str) -> str:
    """``bench`` -> ``the bench``; ``the front step`` -> ``the front step``."""

    return place if place.lower().startswith(_ARTICLES) else f"the {place}"


def _indefinite_phrase(place: str) -> str:
    """``bench`` -> ``a bench``; ``awning`` -> ``an awning``; articles kept."""

    if place.lower().startswith(_ARTICLES):
        return place
    article = "an" if place[:1].lower() in "aeiou" else "a"
    return f"{article} {place}"


def curiosity_event(
    kind: str,
    place: str,
    *,
    time_band: str = "",
    detail: Mapping[str, object] | None = None,
) -> StateEvent:
    """Build one curiosity :class:`StateEvent` for an ADMITTED place name.

    This function does NOT check admission. It cannot: the vocabulary lives in
    the learned map and this module has no business importing perception. The
    admission gate is the runtime's ``_curiosity_admitted_names`` and it runs
    before this is called — which is exactly the arrangement the card's "0
    hallucinated places" row is scored against, and the reason the seeded RED for
    it is seeded THERE and not here.

    What this does refuse is an empty name and an unknown class, because both
    would produce a sentence with a hole in it and a sentence with a hole in it
    is what the model fills in.
    """

    template = CURIOSITY_FACTS.get(str(kind))
    if template is None:
        raise WhispererError(
            f"{kind!r} is not a curiosity class; known classes are "
            f"{sorted(CURIOSITY_FACTS)}"
        )
    clean = " ".join(str(place).split())
    if not clean:
        raise WhispererError(
            f"refusing to compose a {kind} remark with no place name: an empty "
            "name is a sentence the model would finish"
        )
    fact = template.format(
        place=clean,
        definite=_definite_phrase(clean),
        indefinite=_indefinite_phrase(clean),
    )
    band = str(time_band)
    phrase = TIME_BAND_PHRASES.get(band, "")
    if phrase:
        fact = f"{fact} {phrase}"
    rows: dict[str, object] = {"place": clean, "time_band": band}
    if detail:
        rows.update(dict(detail))
    return StateEvent(kind=str(kind), key=f"{kind}:{clean}", fact=fact, detail=rows)


# ========================================== END card CURIO-1 (chatter layer) ==


def compose(event: StateEvent, *, folded: int = 0) -> str:
    """Fact + speech-act hint + what the budget held back. Deterministic.

    ``hint_carried`` exists for R10's arrival table, which already composes the
    ask from the same row the planner used to choose the terminal — appending a
    second ask there would have the robot ask twice in one breath.
    """

    parts = [" ".join(str(event.fact).split())]
    if not event.hint_carried:
        hint = HINTS.get(event.kind, "")
        if hint:
            parts.append(hint)
    if folded > 0:
        parts.append(
            f"({folded} more robot status update"
            f"{'s' if folded != 1 else ''} were held back by the owner's "
            "update budget and are not worth repeating.)"
        )
    return " ".join(part for part in parts if part)


def _block_fact(digest: StateDigest) -> str:
    goal = digest.nav_goal or "its goal"
    if digest.mission_block_class == "person":
        return (
            f"The robot's navigation system reports someone is in the way near {goal}, "
            "so it has stopped and is waiting for them to pass. It is still waiting."
        )
    return (
        f"The robot's navigation system reports something is blocking the way to {goal}, "
        "so it has stopped and is waiting. It is still waiting."
    )


def _clear_fact(digest: StateDigest) -> str:
    goal = digest.nav_goal or "its goal"
    return f"The robot's navigation system reports the way to {goal} is clear again."


def _speed_band(speed: float | None) -> str:
    """The RAW pace bucket. Deliberately coarse and deliberately never spoken."""

    if speed is None:
        return "unknown"
    if speed < 0.3:
        return "still"
    if speed <= WALK_CEILING_MPS:
        return "walk"
    return "run"


def digest_from_mapping(raw: Mapping[str, Any]) -> StateDigest:
    """Build a digest from a plain mapping, refusing unknown keys.

    Used by the offline harnesses and the eval pack so a recorded digest can be
    replayed without importing the runtime.
    """

    allowed = set(StateDigest().as_dict())
    unknown = sorted(str(key) for key in raw if str(key) not in allowed)
    if unknown:
        raise WhispererError(f"unknown state digest key(s): {', '.join(unknown)}")
    values = dict(raw)
    if "position_dm" in values:
        pair = tuple(int(part) for part in values["position_dm"])
        if len(pair) != 2:
            raise WhispererError("position_dm must be a pair")
        values["position_dm"] = pair
    return replace(StateDigest(), **values)


__all__ = [
    "ALWAYS_BAND",
    "BAND_ALWAYS",
    "BAND_MIDDLE",
    "BAND_NEVER",
    "BLOCK_DEBOUNCE_S",
    "CRITICAL_DEDUP_TTL_S",
    "CRITICAL_KINDS",
    "DECISION_LOG_MAX",
    "DEDUP_TTL_S",
    "ESTOP_SOURCE_PHRASES",
    "HINTS",
    "KIND_BATTERY_PCT",
    "KIND_BATTERY_STATE",
    "KIND_EMERGENCY_CLEAR",
    "KIND_EMERGENCY_STOP",
    "KIND_FOLLOW_TICK",
    "KIND_GREETING_DUE",
    "KIND_MIN_GAP_S",
    "KIND_MISSION_ARRIVED",
    "KIND_MISSION_BLOCKED",
    "KIND_MISSION_BLOCK_CLEAR",
    "KIND_MISSION_ENDED",
    "KIND_NAV_TICK",
    "KIND_OWNER_APPEARED",
    "KIND_OWNER_PACE_CHANGE",
    "KIND_OWNER_RETURNED",
    "KIND_PACE_MISMATCH",
    "KIND_PACE_UNKNOWN",
    "KIND_PLAN_ACCEPTED",
    "KIND_POSITION",
    "KIND_PROXIMITY_CHURN",
    "KIND_QUESTION_OF_THE_DAY",
    "KIND_REFUSAL",
    "KIND_REROUTE",
    "KIND_VOICE_REJECTED",
    "LINEAGE_NEW",
    "LINEAGE_QUEUE",
    "LINEAGE_REVISE",
    "MAX_GOAL_LABEL_CHARS",
    "MIDDLE_BAND",
    "MIN_GAP_EXEMPT_KINDS",
    "NEVER_BAND",
    "OWNER_EVENT_KINDS",
    "OWNER_SOURCE_MOCAP",
    "OWNER_SOURCE_PIXELS",
    "OWNER_SOURCE_UWB",
    "PACE_MISMATCH_WINDOW_S",
    "PACE_SKIP_ALREADY_ASKED",
    "PACE_SKIP_NOT_FOLLOWING",
    "PACE_SKIP_NO_RUN_INTENT",
    "PACE_SKIP_OWNER_RUNNING",
    "PACE_SKIP_REASONS",
    "PACE_SKIP_SESSION_BASELINE",
    "PACE_SKIP_UNKNOWN_HOLDING",
    "PACE_SKIP_WINDOW_ACCUMULATING",
    "PLAN_ACCEPTED_FACTS",
    "PLAN_ACCEPTED_MIN_GAP_S",
    "PLAN_ADMISSION_MEMORY",
    "PLAN_LINEAGES",
    "REROUTE_CAUSE_PHRASES",
    "REROUTE_PER_MISSION_CAP",
    "RULE_ALWAYS_BAND",
    "RULE_BLOCK_DEBOUNCE_ELAPSED",
    "RULE_BLOCK_DEBOUNCE_HOLDING",
    "RULE_BUDGET",
    "RULE_CLEAR_AFTER_FORWARDED_BLOCK",
    "RULE_CLEAR_WITHOUT_FORWARDED_BLOCK",
    "RULE_CRITICAL_BYPASS",
    "RULE_DEDUP",
    "RULE_DISABLED",
    "RULE_MIDDLE_BAND_NEEDS_MECHANISM",
    "RULE_MIN_GAP",
    "RULE_NARRATION_FLOOR_REFUSED",
    "RULE_NEVER_BAND",
    "RULE_PACE_KNOWN_RESUMED",
    "RULE_PACE_MISMATCH_SUSTAINED",
    "RULE_PACE_UNKNOWN",
    "RULE_PLAN_ACCEPTED_NEEDS_RECEIPT",
    "RULE_PLAN_ADMITTED",
    "RULE_PLAN_NOT_ADMITTED",
    "RULE_PLAN_RECEIPT_INVALID",
    "RULE_PLAN_REISSUE",
    "RULE_REROUTE_DOOR_WRONG_STATE",
    "RULE_REROUTE_MISSION_CAP",
    "RULE_UNKNOWN_KIND",
    "SOCIAL_STATE_REROUTE",
    "STATE_DIGEST_VERSION",
    "WALK_CEILING_MPS",
    "OwnerEventWatcher",
    "OwnerPresence",
    "PlanAcceptedReceipt",
    "RerouteReceipt",
    "StateDigest",
    "StateEvent",
    "Whisperer",
    "WhispererDecision",
    "WhispererError",
    "band_of",
    "compose",
    "digest_from_mapping",
    "plan_accepted_event",
    "reroute_event",
]
