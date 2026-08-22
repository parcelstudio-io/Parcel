"""The tool broker: hosted proposals in, deterministic admission out (card R3).

WHAT CHANGED, AND WHAT DID NOT
------------------------------
R1 answered every ``response.function_call_arguments.done`` with a refusal
string. This module is the thing that replaces that stub — and it replaces it
by *adding a seam*, not by moving authority. The voice model still decides
nothing. It proposes a name and arguments; every proposal is turned into a
:class:`~parcel_robot.models.ToolCall` and put through
``SafetySupervisor.validate`` BEFORE any runtime door is touched, and only then
handed to the same doors a typed command reaches (``ToolResult.accepted``):

===============  ==========================  ==================================
broker tool      validated as                door
===============  ==========================  ==================================
``get_status``   ``get_status``              the runtime's own snapshot digest
``recall_memory````recall_memory`` (info)    a deterministic ledger read
``play_gesture`` ``run_skill``               ``_brain_gesture`` → coordinator
``set_pose``     ``run_pose``                ``propose_action`` (never recovery)
``navigate_to``  ``navigate``                router → the local-sketch admission
===============  ==========================  ==================================

That table is the R1 audit's carry-forward made structural: *"R3's tool broker
must route through ``ToolCall`` + ``SafetySupervisor.validate`` rather than
inheriting the ingress's direct-call style — uniformity matters more once the
MODEL proposes the action."* There is no path through :meth:`RealtimeToolBroker.handle`
that reaches a door without an accepted ``ToolResult`` first, and the
emergency-stop refusals live inside the supervisor, so a latched e-stop refuses
a hosted pose for exactly the reason it refuses a typed one.

ONE AUTHORITY PER UTTERANCE
---------------------------
The deterministic ingress (``runtime.submit_realtime_transcript``) already acts
on a closed set of phrases: emergency, closed intents, follow, hold. If the
owner says "follow me" the robot is ALREADY following by the time the model
gets a chance to propose anything. A broker that then also admitted a
``navigate_to`` would execute one sentence twice through two authorities. So
the runtime reports each ingress outcome here (:meth:`note_ingress`) and the
broker drops motion proposals for the rest of that utterance, with a reason the
model can say out loud. Read-only tools are unaffected: answering "what is your
status" is never a second authority.

WHY A DICT OF CALLABLES AND NOT THE RUNTIME OBJECT
--------------------------------------------------
:class:`ToolDoors` is the entire surface this module may touch. It is built by
``runtime.py`` from bound methods, which means (a) this module imports nothing
from the runtime and stays unit-testable against fakes, and (b) an auditor can
read the door list and know that nothing else is reachable — there is no
``self._runtime`` here to reach through.

WHAT THE MODEL IS TOLD AFTERWARDS
---------------------------------
Every result is JSON with a ``status`` of ``ok`` / ``deferred`` / ``dropped`` /
``rejected`` and a human sentence. The lane sends it back as a
``function_call_output`` and then a ``response.create``, so the model NARRATES
what the robot actually did instead of predicting it. A dropped gesture
("cooling down") is a fact the companion can answer gracefully; a rejected pose
("motion is disabled by emergency stop") is a fact it must not paper over.

AND IT NARRATES IT IN A TENSE (card R15)
----------------------------------------
Narrating what the robot did turns out to need one more thing than the fact: it
needs to say WHEN. Owner session 1 (2026-08-20, F2) is the proof. The broker
answered ``circle_owner`` with the runtime's own acknowledgement — "Okay—I'll
make the requested local circle around you safely." — and one second later, with
the dog barely a quarter of the way round, the model said **"Done—I made a small
circle around you, and it was okay."** A promise, read as a receipt.

So every :data:`ACTIVITY_TOOLS` result now opens with its tense: ``started:``,
``waiting:`` or ``not started:``, carries ``finished: False``, and never carries
a word from :data:`COMPLETION_LANGUAGE`. Completion is not this module's to
report at all: it belongs to the runtime's terminal events (orbit complete,
gesture done, aborted), which reach the model through the whisperer's
floor-gated narration channel exactly as navigation terminals already do. The
broker's job is to say the body has STARTED; the body's job is to say it stopped.
"""

from __future__ import annotations

import json
import math
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, ClassVar

from parcel_robot.models import ToolCall, ToolResult

# Card P2-A. The privacy policy is imported, not reimplemented: HLD §8.4 says a
# deterministic policy decides what may be kept, and a second copy of the rules
# living in the broker would be a second answer to the same question.
from parcel_robot.owner_model import policy as owner_policy

from .ingress import RealtimeTranscriptOutcome
from .protocol import SESSION_OBJECT_TYPE, ClientEvent

#: Broker-side clamp for ``play_gesture``. ``_brain_gesture`` raises outside
#: this range; the broker clamps first so a model that says "intensity 3" gets a
#: strong wave rather than a refusal, and says so in the result detail.
MIN_INTENSITY = 0.5
MAX_INTENSITY = 1.5
DEFAULT_INTENSITY = 1.0

#: Result vocabulary. ``ok``/``deferred`` mean the robot took the request;
#: ``dropped`` means arbitration declined a well-formed request; ``rejected``
#: means the request never became admissible in the first place.
STATUS_OK = "ok"
STATUS_DEFERRED = "deferred"
STATUS_DROPPED = "dropped"
STATUS_REJECTED = "rejected"

TOOL_GET_STATUS = "get_status"
TOOL_RECALL_MEMORY = "recall_memory"
TOOL_PLAY_GESTURE = "play_gesture"
TOOL_SET_POSE = "set_pose"
TOOL_NAVIGATE_TO = "navigate_to"
#: Card R10. The two tools that close the surface hole. ``OrbitOwner`` and
#: ``FollowFormation`` have always been admitted skills the ingress can run —
#: they simply had no hosted surface, and the 2026-08-19 bench measured what a
#: model does with that gap: the mini tier fabricated
#: ``navigate_to({"place": "with owner"})`` / ``("run route")`` / ``("run path")``
#: 5/6, and realtime-mini instead DENIED the ability outright ("I can't do a
#: full circle around you with the controls I have right now") — a false
#: statement about its own body. The surface must match the body.
TOOL_CIRCLE_OWNER = "circle_owner"
TOOL_FOLLOW_OWNER = "follow_owner"

#: Card P2-A. The eighth tool, and the first one that WRITES something durable
#: about the owner rather than about the robot.
#:
#: Until this card, "my sister's name is Hana" became row N of ``messages`` and
#: nothing else: there was no ``remember`` tool, so the model's only way to keep
#: a fact was to hope it was still inside the twenty-row tail next session. The
#: audit's §5 measurement of what the hosted model knows about its owner per
#: turn — an "unknown" name, an "unknown" location and six lines of digest — is
#: the shape of that gap.
#:
#: It is an ANSWER tool (:data:`ANSWER_TOOLS`) and NOT an activity tool: nothing
#: moves, and the result is the sentence the owner needs to hear. A robot that
#: silently stores a fact about a person is the failure mode this whole card is
#: arranged against, so the beat that carries this result must speak.
TOOL_REMEMBER_FACT = "remember_fact"

#: The three things the model may ask this tool to do. ``remember`` is a
#: proposal, not a command — the policy decides. ``forget`` is the owner's
#: "don't remember that" and is always honoured. ``list`` is
#: "what do you know about me", answered from the table rather than from the
#: model's impression of the conversation.
FACT_ACTION_REMEMBER = "remember"
FACT_ACTION_FORGET = "forget"
FACT_ACTION_LIST = "list"
FACT_ACTIONS = (FACT_ACTION_REMEMBER, FACT_ACTION_FORGET, FACT_ACTION_LIST)

#: The tools that commit the body. These are the ones the utterance-scoped
#: dedupe drops when the deterministic ingress already acted, and the ones the
#: system-initiated gate below refuses outright.
MOTION_TOOLS = frozenset(
    {
        TOOL_PLAY_GESTURE,
        TOOL_SET_POSE,
        TOOL_NAVIGATE_TO,
        TOOL_CIRCLE_OWNER,
        TOOL_FOLLOW_OWNER,
    }
)

#: Card R11, design point 5 — WHO ASKED FOR THE RESPONSE THIS CALL CAME IN.
#:
#: ``owner`` means the owner typed or spoke and the provider is answering them.
#: ``system`` means the ROBOT started the exchange by posting one of its own
#: state facts (``lane.narrate_event``) and asking for a reply.
#:
#: The distinction exists because the bench measured what happens without it:
#: a single telemetry item injected into ``gpt-5-mini`` fired a spurious
#: ``navigate_to("picnic spot by the big oak")`` in **2 of 3** forced-response
#: trials (``bench_navmodel.md`` §4, finding C1). No utterance existed, so the
#: utterance-scoped dedupe two dozen lines above could not see it — the robot
#: would have driven off because it told itself something. Only owner utterances
#: may start motion.
RESPONSE_FROM_OWNER = "owner"
RESPONSE_FROM_SYSTEM = "system"

#: The machine-readable half of the refusal, so a transcript auditor (and the
#: eval pack) can count these without matching prose.
REFUSAL_SYSTEM_INITIATED_MOTION = "system_initiated_motion"

#: The sentence the model reads back. It states the RULE, not just the no: the
#: bench's whole downstream finding is that the model narrates whatever it is
#: given, so giving it the reason is what makes the refusal say something true.
SYSTEM_INITIATED_MOTION_DETAIL = (
    "this reply was triggered by the robot's own status update, not by anything the "
    "owner said, and the robot only starts moving when its owner asks it to"
)

#: Card P0-B, deliverable 1 — THE PROACTIVE UNLOCK, AND ITS CEILING.
#:
#: The gate above is what stops the dog driving off because a telemetry item
#: made it talk to itself. It is also, unmodified, what stops the companion
#: tilting its head at the owner walking in. The unlock is a config list of
#: tools that may still run from a system-initiated reply — and this frozenset
#: is the ceiling on that list, enforced HERE as well as at config load, so a
#: broker constructed by hand (a test, a future caller) cannot be handed
#: ``navigate_to`` either.
#:
#: Only tools whose worst case is a body that moved IN PLACE are in it. The
#: travel tools are not, and cannot be: a proactive ``navigate_to`` is bench
#: finding C1 verbatim. Everything admitted here still goes through
#: ``SafetySupervisor.validate`` and still reaches the same door a typed request
#: reaches — the gate decides WHETHER the proposal is considered, never what
#: happens to it afterwards.
PROACTIVE_MOTION_CEILING: frozenset[str] = frozenset({TOOL_PLAY_GESTURE, TOOL_SET_POSE})

#: The machine-readable stamp on a proactive motion result, so an auditor can
#: count what the robot started on its own without matching prose.
PROVENANCE_RESULT_KEY = "provenance"

#: Card P0-B, deliverable 2 — ``navigate_to`` MODES.
#:
#: ``refuse`` is the shipped behaviour: an unknown but well-formed place noun is
#: handed to the router exactly as a typed sentence is, and the honest refusal
#: comes from grounding (``test_navigate_to_grants_exactly_what_a_typed_sentence
#: _grants``). ``ask`` answers the model with :data:`STATUS_UNKNOWN_PLACE`
#: instead, touching no door.
UNKNOWN_PLACE_REFUSE = "refuse"
UNKNOWN_PLACE_ASK = "ask"

#: A fifth result status, and the only one that is not a verdict on a request.
#: ``rejected`` would have been a lie in the direction that matters: the request
#: was fine, the robot simply does not know where that is, and the difference is
#: precisely what makes the model ASK rather than apologise. Nothing moved, so
#: it tenses as ``not started`` like every other non-``ok`` activity result.
STATUS_UNKNOWN_PLACE = "unknown_place"

#: What the model reads on the ask path. It states the gap and the two ways out
#: — the owner naming the place, or the robot being sent to look — because the
#: standing bench finding is that the model narrates what it is handed.
UNKNOWN_PLACE_DETAIL = (
    "the robot has no place by that name on its map, so it has not moved; ask the "
    "owner where it is or offer to go and look for it"
)

#: Card P2-A. A sixth status, and the second one that is not a verdict on a
#: request. The owner said something the privacy policy will not keep WITHOUT
#: BEING ASKED — health, money, somebody else's secret. ``rejected`` would tell
#: the model it did something wrong and it would apologise; this tells it the
#: truth, which is that the robot needs permission and is waiting for it.
#:
#: The row is already on disk as ``consent='pending'`` when this comes back. The
#: ask is a RECORD, not a discard — otherwise "yes, remember that" would have
#: nothing to point at.
STATUS_CONSENT_REQUIRED = "consent_required"

#: Every tool this broker will answer. Anything else is refused by name.
BROKER_TOOLS = (
    TOOL_GET_STATUS,
    TOOL_RECALL_MEMORY,
    TOOL_PLAY_GESTURE,
    TOOL_SET_POSE,
    TOOL_NAVIGATE_TO,
    TOOL_CIRCLE_OWNER,
    TOOL_FOLLOW_OWNER,
    # Card P2-A. Appended LAST because ``build_tool_specs`` emits in this order
    # and two committed tests pin the emitted names against this tuple
    # element-for-element; inserting in the middle would move six specs for no
    # reason.
    TOOL_REMEMBER_FACT,
)

#: Card R15 — "done" MEANS DONE.
#:
#: The tools whose ``ok`` answer means *the robot has begun something that takes
#: real seconds*. Owner session 1 (2026-08-20, F2) is why this set exists: the
#: model was handed ``"Okay—I'll make the requested local circle around you
#: safely."`` and said **"Done—I made a small circle around you, and it was
#: okay"** ONE SECOND later — a completion claim for a lap that had barely
#: started. R8's audit had already flagged the mild form of the same thing
#: ("Accepted paw_wave for the next control tick" → "I waved. My paw moved").
#:
#: Identical to :data:`MOTION_TOOLS` today and deliberately NOT an alias of it:
#: the two sets answer different questions. ``MOTION_TOOLS`` asks *may this
#: proposal commit the body* (authority); this one asks *does this result
#: describe work that is still happening* (tense). A future read-only tool that
#: nevertheless starts something — or a motion tool that is genuinely
#: instantaneous — would belong to one and not the other.
ACTIVITY_TOOLS = frozenset(
    {
        TOOL_PLAY_GESTURE,
        TOOL_SET_POSE,
        TOOL_NAVIGATE_TO,
        TOOL_CIRCLE_OWNER,
        TOOL_FOLLOW_OWNER,
    }
)

#: Card R19 — THE SILENT COMPANION.
#:
#: The tools whose result IS the answer to a question the owner just asked.
#: There is no mission log, no terminal event and no ``narrate_event`` coming
#: later to say a battery percentage or a recalled memory: if the beat that
#: carries this result does not speak, nothing ever does.
#:
#: The exact complement of :data:`ACTIVITY_TOOLS` today, and — like that set —
#: deliberately not expressed as one. "Does this describe work still happening"
#: and "is this result the answer" are different questions, and a future
#: perception tool (live_run_1 re-cut F3 as exactly that missing tool) would be
#: an ANSWER tool that is not an activity, while a hypothetical
#: ``stop_and_report`` would be both.
#:
#: Card P2-A adds the third. ``remember_fact`` is exactly R19's shape: there is
#: no mission log, no terminal event and no later narration that will tell the
#: owner what the robot decided to keep about them. If the beat carrying this
#: result does not speak, the robot stored a fact about a person in silence —
#: which is the one outcome the consent design exists to prevent.
#:
#: ``realtime.lane.DEFAULT_ANSWER_TOOLS`` carries the same name; a committed
#: test asserts the two sets are equal, which is the coupling being kept honest
#: rather than the coupling being avoided.
ANSWER_TOOLS = frozenset({TOOL_GET_STATUS, TOOL_RECALL_MEMORY, TOOL_REMEMBER_FACT})

#: The key :data:`ANSWER_TOOLS` results carry so the LANE never has to know the
#: tool surface. ``parcel_robot.realtime.lane.ANSWER_RESULT_KEY`` is the reader;
#: the two modules do not import each other (the lane holds this one behind a
#: Protocol), and a classification that travels inside the result is the one
#: coupling that cannot go stale when a tool is added.
ANSWER_RESULT_KEY = "answer"

#: The three tenses an activity result may be in. There is no fourth, and in
#: particular there is no "finished": no broker answer can ever report a
#: completed physical action, because the broker returns while the body is still
#: moving. Completion has exactly one reporter — the runtime's own terminal
#: event, narrated through the whisperer/lane channel.
TENSE_STARTED = "started"
TENSE_WAITING = "waiting"
TENSE_NOT_STARTED = "not started"

TENSE_BY_STATUS: Mapping[str, str] = {
    STATUS_OK: TENSE_STARTED,
    STATUS_DEFERRED: TENSE_WAITING,
    STATUS_DROPPED: TENSE_NOT_STARTED,
    STATUS_REJECTED: TENSE_NOT_STARTED,
    # Card P0-B. Spelled out rather than left to the ``.get`` default: an ask is
    # the one status whose NAME does not say the body stayed still, so the one
    # that most needs the tense saying it.
    STATUS_UNKNOWN_PLACE: TENSE_NOT_STARTED,
    # Card P2-A, post-verification. Same argument as P0-B's line above, and
    # harmless today because ``remember_fact`` is not an ACTIVITY tool so
    # ``_tensed`` never runs on it. It is here for SHAPE PARITY: if a future
    # tool ever returns ``consent_required`` from an activity, the tense must
    # already be right rather than falling to a ``.get`` default nobody checked.
    STATUS_CONSENT_REQUIRED: TENSE_NOT_STARTED,
}

#: Said alongside every ``started``/``waiting`` result, because the bench's
#: standing finding is that the model narrates whatever it is given: telling it
#: who WILL report the ending is what stops it inventing the ending itself.
COMPLETION_NOTE = (
    "this has NOT finished; the robot's own systems report the ending "
    "separately, and only then may you say it is done"
)

#: Words that assert a physical action ALREADY HAPPENED. An activity detail
#: containing one of these is the F2 defect, in the one place the model reads.
#: Word-boundary tokens, not substrings: "finishes" (a promise about the future)
#: is not "finished" (a claim about the past).
COMPLETION_LANGUAGE: frozenset[str] = frozenset(
    {
        "arrived",
        "bowed",
        "circled",
        "complete",
        "completed",
        "danced",
        "did",
        "done",
        "finished",
        "made",
        "nodded",
        "performed",
        "sat",
        "successfully",
        "walked",
        "waved",
    }
)

#: The other half of the same rule (card R4-lite, Defect C, kept honest here).
#: The detail is a FACT the model reads, never a script it recites. A sentence
#: in the robot's own first person — "Okay—I'll walk a circle around you." — is
#: a promise, and a promise one second old is what the model turned into "Done".
SCRIPT_LANGUAGE: frozenset[str] = frozenset({"i'll", "i've", "i'm", "let", "okay"})

#: Closed enums for the new tools. Every value is checked here AND again by the
#: supervisor's existing ``run_spatial_behavior`` / ``set_behavior`` arms, which
#: is where the authority actually lives.
ORBIT_DIRECTIONS = ("clockwise", "counterclockwise")
ORBIT_SIZES = ("small", "normal", "wide")
DEFAULT_ORBIT_DIRECTION = "counterclockwise"
DEFAULT_ORBIT_SIZE = "normal"
DEFAULT_ORBIT_REVOLUTIONS = 1.0
MIN_ORBIT_REVOLUTIONS = 0.25
MAX_ORBIT_REVOLUTIONS = 1.0

#: ``pace`` exists so "run with me" stops becoming a fabricated ``navigate_to``.
#: R11's pace_intent is what will consume it; until then the broker records it
#: and the door reports it, and NOTHING here changes a commanded speed — an
#: accepted pace the body did not act on would be the over-claim class the bench
#: found in B2 ("I'm matching your slower pace" while the gait was still RUN).
FOLLOW_PACES = ("walk", "run")
DEFAULT_FOLLOW_PACE = "walk"

#: How many valid places a place refusal names back to the model. Enough to be
#: useful, few enough to stay one short spoken sentence.
REFUSAL_PLACE_LIMIT = 5

#: How a hosted place name becomes a directive the deterministic router can
#: recognize. Deliberately the plainest phrasing in the router's navigation
#: grammar — the broker renders text for the router, it never fabricates a
#: route, an ``IntentFrame`` or a plan.
NAVIGATE_DIRECTIVE_TEMPLATE = "go to {place}"

#: Maximum characters accepted for any free-text argument.
MAX_ARGUMENT_CHARS = 200


class ToolBrokerError(RuntimeError):
    """A broker refusal that is not a door's fault. Never silent."""


@dataclass(frozen=True)
class SessionToolsUpdate(ClientEvent):
    """Declare the tool surface on an open session.

    A separate event from R1's :class:`~parcel_robot.realtime.protocol.SessionUpdate`
    rather than a new field on it: ``protocol.py`` is audited and frozen for this
    card, and ``session.update`` is defined by the provider to replace only the
    fields it carries. Sending instructions first and tools second therefore ends
    in exactly the session state one combined event would have produced, with a
    zero-line diff to the audited codec.
    """

    TYPE: ClassVar[str] = "session.update"

    tools: tuple[Mapping[str, Any], ...] = ()
    tool_choice: str = "auto"

    def to_payload(self) -> dict[str, Any]:
        return {
            "type": self.TYPE,
            "session": {
                # Same provider requirement the instructions frame hit: a
                # session object without its discriminator is refused whole,
                # and a refused tools frame means the model never learns the
                # robot has a body. Read from protocol.py so there is one copy.
                "type": SESSION_OBJECT_TYPE,
                "tools": [dict(tool) for tool in self.tools],
                "tool_choice": self.tool_choice,
            },
        }


def build_tool_specs(
    *,
    gestures: Sequence[str] = (),
    poses: Sequence[str] = (),
) -> tuple[dict[str, Any], ...]:
    """The provider-facing schemas, with the catalog inlined as enums.

    Inlining the real names is what keeps the model from inventing
    ``play_gesture("do a backflip")``: the enum is the robot's actual emote
    allowlist and pose catalog, read from the runtime at session open. It is a
    hint, not the gate — every name is still validated by the supervisor.
    """

    gesture_names = [str(name) for name in gestures if str(name).strip()]
    pose_names = [str(name) for name in poses if str(name).strip()]
    gesture_schema: dict[str, Any] = {"type": "string", "description": "Gesture name."}
    if gesture_names:
        gesture_schema = {"type": "string", "enum": sorted(set(gesture_names))}
    pose_schema: dict[str, Any] = {"type": "string", "description": "Pose name."}
    if pose_names:
        pose_schema = {"type": "string", "enum": sorted(set(pose_names))}
    return (
        {
            "type": "function",
            "name": TOOL_GET_STATUS,
            # Card R18. live_run_1 root-caused F3 as a MISSING TOOL: asked "what
            # do you see around you", the model emitted two filler beats 3 ms
            # apart and then gave up, because none of the seven tools it had
            # could answer a question about the world. The answer exists —
            # ``_realtime_status_digest`` now carries a ``scene`` block built
            # from the LiDAR, the semantic map and the person tracks — and this
            # description is what routes the question to it. Both halves of the
            # honesty rule are here, because this text is what the model reads
            # when it decides whether it is able to answer at all: the robot
            # DOES sense its surroundings (owner_session_1's "I can't actually
            # see anything around me" is false), and it senses them without eyes
            # (so nothing visual may be described).
            "description": (
                "Read the robot's own current state AND what its sensors detect "
                "around it right now: battery, emergency stop, what it is doing, "
                "plus the nearby labelled places with their distance and "
                "direction, how many people are tracked and how far the nearest "
                "one is, and the clearance to the nearest obstacle. CALL THIS "
                "whenever the owner asks what is around you, what you can "
                "detect, whether anyone is nearby, what the closest thing is, or "
                "how you are doing — you are never blind and must never say you "
                "cannot sense anything. The readings come from LiDAR and a "
                "semantic map: the robot has NO camera, so report what it "
                "detects and never describe colours, faces, text or how "
                "anything looks. Never guess any of it."
            ),
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
        {
            "type": "function",
            "name": TOOL_RECALL_MEMORY,
            # Card R18. The result now carries WHEN each memory was said, so the
            # description has to ask for it back: a remembered fact the owner
            # cannot place is a fact they cannot check.
            "description": (
                "Search everything ever said between you and the owner — every "
                "conversation, from every device, going back as far as the "
                "record goes. CALL THIS whenever the owner asks what you "
                "remember, what you know about them, or what you talked about "
                "before; you have a real memory and must never say you have "
                "none without looking. Each memory comes back with when it was "
                "said — say that too ('yesterday you told me…'). If it comes "
                "back empty, say plainly that you have nothing recorded."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        # Card R18, from the live proof: asked "What do you
                        # remember about me?" the mini tier sent
                        # {"query": "owner"} — inventing a topic for a question
                        # that had none, and matching five typed test commands.
                        # The instruction is therefore about what NOT to invent.
                        "description": (
                            "The topic to look for, in the owner's own words. "
                            "If they asked a general question about themselves "
                            "or about a past day, pass their question through "
                            "as they said it — do NOT invent a topic word like "
                            "'owner' or 'user', which searches for the wrong "
                            "thing."
                        ),
                    }
                },
                "required": ["query"],
            },
        },
        {
            "type": "function",
            "name": TOOL_PLAY_GESTURE,
            "description": (
                "Perform one expressive gesture with your real body. You HAVE a "
                "body: when the owner asks you to wave, nod, bow or dance, CALL "
                "this tool — describing the movement in words instead of calling "
                "it means nothing actually moved. The robot decides whether it is "
                "safe and may decline; read the result before saying it happened. "
                "The result says the movement has STARTED, never that it is over: "
                "never say you have waved, bowed or danced. The robot tells you "
                "when the movement actually ends."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "name": gesture_schema,
                    "intensity": {
                        "type": "number",
                        "description": "0.5 (subtle) to 1.5 (big).",
                    },
                },
                "required": ["name"],
            },
        },
        {
            "type": "function",
            "name": TOOL_SET_POSE,
            "description": (
                "Settle your real body into one bounded pose (for example "
                "sitting). Asked to sit, lie down or stand? CALL this tool. The "
                "robot may decline while it is busy; read the result. The result "
                "says the robot has STARTED settling, never that it is settled — "
                "the robot tells you when it has finished moving."
            ),
            "parameters": {
                "type": "object",
                "properties": {"name": pose_schema},
                "required": ["name"],
            },
        },
        {
            "type": "function",
            "name": TOOL_NAVIGATE_TO,
            "description": (
                "Walk to a named place nearby. Whenever the owner asks you to go "
                "somewhere, to head over to something, or to come along to a "
                "place, CALL this tool with that place — agreeing in words alone "
                "leaves the robot standing still. Only places the robot's own "
                "navigation understands are accepted; a refusal comes back with "
                "the reason, which you should say plainly. Never say you have "
                "arrived: this only starts the trip."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "place": {"type": "string", "description": "A place name."},
                    # Card R10, the HYBRID half. The bench measured relation
                    # hints at 36/36 on both tiers, so reading one is cheap and
                    # good; the local arrival table still validates it and still
                    # wins every conflict. Note what is NOT here: no "face", no
                    # standoff, no stopping rule. Those are owner policy the
                    # model answered wrong 6/6, and a parameter it cannot send
                    # is a parameter it cannot get wrong.
                    "relation": {
                        "type": "string",
                        "enum": ["inside", "near", "social"],
                        "description": (
                            "Optional: how the owner means you to end up — ON it "
                            "(inside, e.g. a sidewalk or a rug), BESIDE it (near, "
                            "e.g. a door or a bench), or a polite distance from a "
                            "person (social). A guess is fine; the robot checks it "
                            "and uses its own answer if they disagree."
                        ),
                    },
                },
                "required": ["place"],
            },
        },
        {
            "type": "function",
            "name": TOOL_CIRCLE_OWNER,
            "description": (
                "Walk a circle around the owner with your real body. You CAN do "
                "this — when the owner asks you to circle them, walk around them "
                "or do a lap, CALL this tool. Saying you are unable to is false. "
                "The robot checks there is room and may refuse with the reason; "
                "read the result and say that reason plainly. A lap takes tens "
                "of seconds: the result only ever says the circle has STARTED, "
                "so say you are walking it now and NEVER that you have made it. "
                "The robot tells you when the lap is actually finished."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "direction": {"type": "string", "enum": list(ORBIT_DIRECTIONS)},
                    "size": {"type": "string", "enum": list(ORBIT_SIZES)},
                    "revolutions": {
                        "type": "number",
                        "description": "0.25 to 1.0 laps.",
                    },
                },
                "required": [],
            },
        },
        {
            "type": "function",
            "name": TOOL_FOLLOW_OWNER,
            "description": (
                "Walk along WITH the owner, keeping station on them. Asked to "
                "come along, follow, heel, or run with them? CALL this tool — do "
                "NOT call navigate_to with a place like 'with owner' or 'run "
                "route'; those are not places and will be refused. Use pace to "
                "say whether they asked to walk or to run. Following has no "
                "ending of its own: say you are walking with them now, never "
                "that you have followed them."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "pace": {
                        "type": "string",
                        "enum": list(FOLLOW_PACES),
                        "description": "The pace the owner asked for.",
                    }
                },
                "required": [],
            },
        },
        {
            "type": "function",
            "name": TOOL_REMEMBER_FACT,
            # Card P2-A. Three things this description has to do, and each one
            # is a failure the audit measured or the design forbids:
            #
            # 1. Get the tool CALLED at all. A model with a memory tool it never
            #    reaches for is the same as a model with no memory tool, and the
            #    hosted lane's standing habit is to answer from the tail rather
            #    than to act. Hence the explicit trigger list.
            # 2. Stop it PROMISING. The policy decides, not the model, so the
            #    description must not let it say "I'll remember that" before the
            #    result comes back — a robot that promises to remember and then
            #    does not is worse than one that never offered.
            # 3. Stop it INVENTING. Only what the owner actually said. A fact
            #    distilled from the robot's own guesses is a belief about a
            #    person with no evidence behind it, and it is durable.
            "description": (
                "Keep, drop, or list durable facts about the OWNER — their name "
                "and the names of people and pets in their life, what they like "
                "and dislike, their routines, and the places that matter to "
                "them. CALL THIS with action='remember' the moment the owner "
                "tells you something about themselves worth keeping ('my "
                "sister's name is Hana', 'I hate being told to cheer up'). CALL "
                "IT with action='forget' when they say to forget something, and "
                "with action='list' when they ask what you know or remember "
                "about them — answer from what comes back, never from your own "
                "impression. Record ONLY what the owner actually said; never "
                "guess, never infer, and never store anything about yourself. "
                "The robot's own privacy rules decide what is kept, so do NOT "
                "say you have remembered anything until the result says so: if "
                "it comes back needing permission, say plainly what it is and "
                "ask whether they want you to keep it."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": list(FACT_ACTIONS),
                        "description": (
                            "remember a new fact, forget one, or list what you "
                            "already know. Defaults to remember."
                        ),
                    },
                    "fact": {
                        "type": "string",
                        "description": (
                            "The fact, written as the sentence you would say "
                            "back to them, in the third person: 'their sister "
                            "is called Hana'. Required for remember."
                        ),
                    },
                    "key": {
                        "type": "string",
                        "description": (
                            "A short slug naming WHAT this is a fact about — "
                            "'sister_name', 'coffee_preference'. Reusing a key "
                            "replaces the old fact rather than adding a second "
                            "one. Required for forget."
                        ),
                    },
                },
                "required": [],
            },
        },
    )


def _no_op() -> None:
    return None


def _no_note(message: str) -> None:
    del message


def _unwired(*_args: object, **_kwargs: object) -> str:
    """Default for a door the host did not wire. Refuses; never pretends."""

    raise ValueError("this robot has not wired that ability up")


@dataclass(frozen=True)
class ToolDoors:
    """Every runtime affordance the broker is allowed to touch. Nothing else.

    ``validate`` is first in the list because it runs first in every path; the
    rest are the doors a typed command already uses. The R10 additions default
    to :func:`_unwired`, so a host that has not connected them gets an honest
    refusal rather than a broker that silently drops the call.
    """

    validate: Callable[[ToolCall], ToolResult]
    status: Callable[[], Mapping[str, object]]
    recall: Callable[[str], str]
    gesture: Callable[[str, float], str]
    pose: Callable[[str], str]
    navigate: Callable[[str, str], str]
    gesture_names: Callable[[], Sequence[str]] = tuple
    pose_names: Callable[[], Sequence[str]] = tuple
    on_dispatch: Callable[[], None] = _no_op
    note: Callable[[str], None] = _no_note
    #: Card R10. ``places`` is the ordered, nearest-first place vocabulary the
    #: navigation stack will actually accept; it is what makes a junk-place
    #: refusal name real alternatives instead of just saying no.
    places: Callable[[], Sequence[str]] = tuple
    orbit: Callable[[str, str, float], str] = _unwired
    follow: Callable[[str], str] = _unwired
    #: Card P2-A. The owner-model doors. Three rather than one because they
    #: have three different consequences — a write, a delete and a read — and a
    #: single ``facts(action, ...)`` door would make "did this call change
    #: anything" a question about a string argument.
    #:
    #: ``remember_fact`` receives the fact text, the key and the POLICY'S
    #: DECISION, already made. It does not re-decide: the broker owns the policy
    #: call so that the verdict is visible in the tool result the model reads,
    #: and the runtime owns the store. A door that decided for itself would put
    #: the consent rule somewhere the model's answer cannot see it.
    #:
    #: ``known_facts`` returns rendered LINES, not rows. The broker never sees
    #: the ``owner_facts`` schema — same discipline as ``places``, and it means
    #: the consent filter cannot be forgotten on the way out of the store,
    #: because what crosses this boundary is already the answer.
    remember_fact: Callable[[str, str, object], Mapping[str, object]] = _unwired
    forget_fact: Callable[[str], Mapping[str, object]] = _unwired
    known_facts: Callable[[], Sequence[str]] = tuple


@dataclass
class _Utterance:
    """What the deterministic ingress already did for the utterance in flight."""

    sequence: int = 0
    executed: str = ""

    def claim(self) -> str:
        return self.executed


class RealtimeToolBroker:
    """Answers hosted function calls. One admission chain, no shortcuts."""

    def __init__(
        self,
        doors: ToolDoors,
        *,
        tool_choice: str = "auto",
        proactive_motion_tools: Sequence[str] = (),
        unknown_place: str = UNKNOWN_PLACE_REFUSE,
    ) -> None:
        self._doors = doors
        self._tool_choice = tool_choice
        self._utterance = _Utterance()
        #: Card R11. Who asked for the response the current call belongs to. The
        #: lane sets this before every dispatch; it defaults to the owner because
        #: that is what every call was before this card and because a response
        #: nobody tagged is, on the wire, one the owner's voice produced.
        self._provenance = RESPONSE_FROM_OWNER
        #: Card P0-B. The proactive allowlist, intersected with the ceiling on
        #: the way in. Two gates rather than one because the config loader and
        #: this constructor have different callers: the loader answers for
        #: ``configs/realtime.yaml`` and this answers for every other way a
        #: broker can come into existence. A travel tool named here is dropped
        #: silently BECAUSE the loader already refuses it loudly — this arm only
        #: ever sees a caller that bypassed the loader.
        self._proactive: frozenset[str] = frozenset(
            str(name).strip() for name in proactive_motion_tools
        ) & PROACTIVE_MOTION_CEILING
        #: Card P0-B. ``refuse`` (shipped) or ``ask``. An unrecognised value is
        #: the shipped behaviour, which is the fail-closed direction: it can only
        #: ever mean "route it exactly as a typed sentence" and never "invent an
        #: answer the owner did not configure".
        self._unknown_place = (
            UNKNOWN_PLACE_ASK
            if str(unknown_place or "").strip().lower() == UNKNOWN_PLACE_ASK
            else UNKNOWN_PLACE_REFUSE
        )
        self.calls: list[dict[str, object]] = []
        self.dropped = 0
        self.rejected = 0
        self.executed = 0
        #: Motion proposals refused because the robot, not the owner, started
        #: the exchange. This is the C1 defect being caught, counted.
        self.system_initiated_motion_refusals = 0
        #: Card P0-B. The other side of that number: motion the robot started on
        #: its own and was ALLOWED to. Counted separately and published in the
        #: snapshot, because "the dog moved and nobody asked it to" is a fact an
        #: owner reading the panel is entitled to see the size of.
        self.proactive_motion_admissions = 0
        #: Card P0-B. Places the model asked about that the map does not hold.
        #: A queue of these is the flywheel's shopping list: it is exactly the
        #: set of nouns the owner uses and the robot cannot ground.
        self.unknown_place_asks = 0
        #: Card P2-A. The owner model's four numbers, published in the snapshot
        #: because "what has this robot decided to keep about me, and what did
        #: it decline to" is a question an owner must be able to answer from the
        #: panel without opening a database. The three write outcomes are
        #: counted separately on purpose: a rising ``facts_consent_asks`` with a
        #: flat ``facts_remembered`` means the policy is asking about everything,
        #: which is a tuning problem, and it is invisible in a single total.
        self.facts_remembered = 0
        self.facts_consent_asks = 0
        self.facts_refused = 0
        self.facts_forgotten = 0

    # ----------------------------------------------------------- lane surface
    def session_events(self) -> tuple[ClientEvent, ...]:
        """Sent by the lane right after ``session.update``, every session."""

        specs = build_tool_specs(
            gestures=self._doors.gesture_names(),
            poses=self._doors.pose_names(),
        )
        return (SessionToolsUpdate(tools=specs, tool_choice=self._tool_choice),)

    def handle(self, *, name: str, call_id: str, arguments: str) -> str:
        """Answer exactly one function call. Always returns JSON, never raises.

        The lane sends this string back as the call's ``function_call_output``.
        A broker that raised would leave a call unanswered, and an unanswered
        call wedges the provider's turn — so every failure mode here is a
        ``rejected`` result with the reason in it.
        """

        result = self._dispatch(name=str(name), arguments=str(arguments))
        # Card R15. The LAST thing that happens to an activity answer, so there
        # is no return path in this class that can hand the model an untensed
        # one — including the refusals raised before any argument is read.
        if str(name) in ACTIVITY_TOOLS:
            result = _tensed(result)
        # Card R19, and the same "one stamp, one place" rule R15 established
        # above it: every return path in this class — including the refusals
        # raised before an argument is read — hands the lane a result that says
        # for itself whether it is an ANSWER. Stamped regardless of status,
        # because a ``get_status`` that FAILED is still the owner's question
        # going unanswered and still the one thing that must never go quiet.
        if str(name) in ANSWER_TOOLS:
            result[ANSWER_RESULT_KEY] = True
        row = {
            "call_id": str(call_id),
            "tool": str(name),
            "status": str(result.get("status", STATUS_REJECTED)),
            "detail": str(result.get("detail", "")),
        }
        self.calls.append(row)
        status = row["status"]
        if status in {STATUS_OK, STATUS_DEFERRED}:
            self.executed += 1
        elif status == STATUS_DROPPED:
            self.dropped += 1
        else:
            # Card P0-B. An ``unknown_place`` ask lands here with the refusals,
            # and that is the honest bucket: nothing was executed and no door
            # was touched. It carries its own counter as well, because the
            # QUESTION it represents is a different thing from a rejection.
            self.rejected += 1
        self._doors.note(f"tool {name}: {status} — {row['detail']}")
        return json.dumps(result, sort_keys=True)

    # ------------------------------------------------------- runtime surface
    def note_ingress(self, outcome: RealtimeTranscriptOutcome) -> None:
        """Record what the deterministic ingress did with this utterance."""

        self._utterance = _Utterance(
            sequence=self._utterance.sequence + 1,
            executed=(outcome.name if outcome.executed else ""),
        )

    # ------------------------------------------------------------ lane surface
    def note_response_provenance(self, provenance: str) -> None:
        """Card R11. The lane says who asked for the response now being answered.

        Unrecognised values fail CLOSED — anything that is not literally
        ``owner`` is treated as system-initiated, so a future lane that grows a
        third provenance cannot accidentally hand the model the body.
        """

        clean = str(provenance or "").strip().lower()
        self._provenance = RESPONSE_FROM_OWNER if clean == RESPONSE_FROM_OWNER else (
            RESPONSE_FROM_SYSTEM
        )

    def snapshot(self) -> dict[str, object]:
        return {
            "tools": list(BROKER_TOOLS),
            "calls": len(self.calls),
            "executed": self.executed,
            "dropped": self.dropped,
            "rejected": self.rejected,
            "utterance_sequence": self._utterance.sequence,
            "utterance_claim": self._utterance.claim(),
            # Card R11. The gate, from outside.
            "response_provenance": self._provenance,
            "system_initiated_motion_refusals": self.system_initiated_motion_refusals,
            # Card P0-B. The unlock, from outside: what the gate was told to let
            # through, how often it did, and which mode navigate_to is in. An
            # operator must be able to answer "why did it move on its own" from
            # the panel alone.
            "proactive_motion_tools": sorted(self._proactive),
            "proactive_motion_admissions": self.proactive_motion_admissions,
            "unknown_place_mode": self._unknown_place,
            "unknown_place_asks": self.unknown_place_asks,
            # Card P2-A. The owner model, from outside.
            "facts_remembered": self.facts_remembered,
            "facts_consent_asks": self.facts_consent_asks,
            "facts_refused": self.facts_refused,
            "facts_forgotten": self.facts_forgotten,
            "last": dict(self.calls[-1]) if self.calls else None,
        }

    # --------------------------------------------------------------- routing
    def _dispatch(self, *, name: str, arguments: str) -> dict[str, object]:
        if name not in BROKER_TOOLS:
            return _refused(name, f"{name!r} is not a tool this robot has")

        # Card R11, design point 5. FIRST, before the arguments are even read:
        # a response the robot started may not move the body, whatever it asks
        # for and however well-formed the request is. Placed ahead of every
        # other check so there is no ordering in which a motion proposal from a
        # system-initiated response reaches a door — including ahead of the
        # utterance-scoped drop, which cannot see this case at all because there
        # is no utterance in flight (bench_navmodel.md §4, C1).
        # Card P0-B, deliverable 1. The unlock is a HOLE IN THIS GATE and
        # nowhere else: a tool the owner put on the proactive list skips the
        # refusal above and then travels the identical path an owner-initiated
        # call travels — the same argument parse, the same
        # ``SafetySupervisor.validate``, the same activity coordinator with its
        # cooldown and its e-stop, the same door. Nothing downstream learns that
        # this call was proactive; it only learns that it happened.
        proactive = name in self._proactive and name in PROACTIVE_MOTION_CEILING
        if name in MOTION_TOOLS and self._provenance != RESPONSE_FROM_OWNER and not proactive:
            self.system_initiated_motion_refusals += 1
            body = _refused(name, SYSTEM_INITIATED_MOTION_DETAIL)
            body["refusal"] = REFUSAL_SYSTEM_INITIATED_MOTION
            body["provenance"] = self._provenance
            return body
        admitted_proactively = (
            proactive and name in MOTION_TOOLS and self._provenance != RESPONSE_FROM_OWNER
        )

        try:
            payload = _arguments(arguments)
        except (TypeError, ValueError) as error:
            return _refused(name, str(error))

        if name in MOTION_TOOLS:
            claim = self._utterance.claim()
            if claim:
                # One utterance, one authority. The robot already moved for this
                # sentence through the deterministic ingress.
                return _dropped(
                    name,
                    f"the robot already acted on this request as {claim!r}; "
                    "a second authority for one sentence is refused",
                )

        if name == TOOL_GET_STATUS:
            return self._get_status()
        if name == TOOL_RECALL_MEMORY:
            return self._recall(payload)
        # Card P2-A. Beside the other two read-only tools and above every motion
        # branch, because it is one: nothing here reaches a door that can move
        # the body, and the R11 provenance gate above has already let it past on
        # the same grounds it lets ``get_status`` past. A robot that may not
        # answer a question while it is stopped is a worse robot, and the same
        # argument applies to a robot that may not be told to forget something.
        if name == TOOL_REMEMBER_FACT:
            return self._remember_fact(payload)
        if name == TOOL_PLAY_GESTURE:
            result = self._play_gesture(payload)
        elif name == TOOL_SET_POSE:
            result = self._set_pose(payload)
        elif name == TOOL_CIRCLE_OWNER:
            result = self._circle_owner(payload)
        elif name == TOOL_FOLLOW_OWNER:
            result = self._follow_owner(payload)
        else:
            result = self._navigate_to(payload)
        if admitted_proactively:
            # Card P0-B. Counted here rather than at the gate so the number
            # means "a proactive proposal reached a door", not "a proactive
            # proposal arrived with unreadable arguments". The stamp is the
            # transcript half of the same fact: a reader of the tool result can
            # tell that the robot, not the owner, started this movement — which
            # is the one thing the R11 refusal used to guarantee for free.
            self.proactive_motion_admissions += 1
            result[PROVENANCE_RESULT_KEY] = self._provenance
        return result

    # ----------------------------------------------------------------- tools
    def _get_status(self) -> dict[str, object]:
        allowed = self._validated(ToolCall(TOOL_GET_STATUS, {}), TOOL_GET_STATUS)
        if allowed is not None:
            return allowed
        try:
            digest = dict(self._doors.status())
        except (KeyError, RuntimeError, TypeError, ValueError) as error:
            return _refused(TOOL_GET_STATUS, f"status is unavailable: {error}")
        return {
            "status": STATUS_OK,
            "tool": TOOL_GET_STATUS,
            "detail": "current robot state",
            "state": digest,
        }

    def _recall(self, payload: Mapping[str, Any]) -> dict[str, object]:
        try:
            query = _text(payload, "query")
        except ValueError as error:
            return _refused(TOOL_RECALL_MEMORY, str(error))
        allowed = self._validated(
            ToolCall(TOOL_RECALL_MEMORY, {"query": query}), TOOL_RECALL_MEMORY
        )
        if allowed is not None:
            return allowed
        try:
            found = self._doors.recall(query)
        except (KeyError, RuntimeError, TypeError, ValueError) as error:
            return _refused(TOOL_RECALL_MEMORY, f"memory is unavailable: {error}")
        return {
            "status": STATUS_OK,
            "tool": TOOL_RECALL_MEMORY,
            "detail": found or "nothing recorded about that yet",
            "query": query,
        }

    # ------------------------------------------------- card P2-A: owner facts
    def _remember_fact(self, payload: Mapping[str, Any]) -> dict[str, object]:
        """The model PROPOSES; :mod:`parcel_robot.owner_model.policy` DECIDES.

        HLD §8.4's rule, as code rather than as a prompt line. The order below
        is the guarantee and it is worth reading in order:

        1. the argument is parsed,
        2. the supervisor is asked (this is a tool like any other),
        3. **the policy rules on the text**, and only then
        4. a door is touched, with the verdict passed to it rather than
           re-derived.

        Nothing between 3 and 4 can turn a ``refuse`` into a write, because 4
        never runs on a refusal. And the detail the model reads always contains
        the policy's own reason, so the sentence the owner hears is the sentence
        the rule actually says — the model is not left to invent an explanation
        for a decision it did not make.
        """

        action = _enum(payload.get("action"), FACT_ACTIONS, default=FACT_ACTION_REMEMBER)
        allowed = self._validated(
            ToolCall(TOOL_REMEMBER_FACT, {"action": action}), TOOL_REMEMBER_FACT
        )
        if allowed is not None:
            return allowed

        if action == FACT_ACTION_LIST:
            return self._list_facts()
        if action == FACT_ACTION_FORGET:
            return self._forget_fact(payload)

        try:
            fact = _text(payload, "fact")
        except ValueError as error:
            return _refused(TOOL_REMEMBER_FACT, str(error))

        decision = owner_policy.decide(fact)
        key = " ".join(str(payload.get("key") or "").split()) or _fact_key(fact)

        if decision.disposition == owner_policy.DISPOSITION_REFUSE:
            # Card P2-A, post-verification. THE KEY IS PART OF THE PAYLOAD.
            #
            # ``_fact_key`` derives a slug from the fact text, so
            # "their wifi password is hunter2" became ``wifi_password_hunter2``
            # — and that string was then echoed back to the model inside the
            # refusal, which is the model reading the credential out loud in the
            # course of being told the credential may not be stored. A key the
            # model supplied can carry it too. So on a REFUSE the derived and
            # supplied keys are both discarded and the key is rebuilt from the
            # policy's ``matched`` terms alone, which are drawn from the closed
            # :data:`~parcel_robot.owner_model.policy.SECRET_TERMS` list and
            # therefore cannot contain anything the owner said.
            key = _redacted_key(decision)
            self.facts_refused += 1
            body = _refused(TOOL_REMEMBER_FACT, f"not storing that: {decision.reason}")
            body.update(
                {
                    "action": action,
                    # ``fact`` is NOT echoed on this arm, and the omission is the
                    # point. Every other arm returns it so the model can confirm
                    # exactly what was stored; here there is nothing to confirm,
                    # and repeating the value would put the credential back into
                    # the one surface this arm exists to keep it out of. The
                    # model sent the text and still has it — what it needs back
                    # is the verdict and the reason, which are both here.
                    "fact_chars": len(fact),
                    "key": key,
                    "stored": False,
                    **decision.as_dict(),
                }
            )
            return body

        try:
            written = dict(self._doors.remember_fact(key, fact, decision))
        except (KeyError, RuntimeError, TypeError, ValueError) as error:
            return _refused(TOOL_REMEMBER_FACT, f"the fact store is unavailable: {error}")

        if decision.disposition == owner_policy.DISPOSITION_ASK:
            self.facts_consent_asks += 1
            return {
                "status": STATUS_CONSENT_REQUIRED,
                "tool": TOOL_REMEMBER_FACT,
                "detail": (
                    f"not keeping that yet — {decision.reason}. Say back what it is "
                    "and ask the owner whether they want it remembered"
                ),
                "action": action,
                "fact": fact,
                "key": key,
                # False is the honest answer to the question the model is asking.
                # A row EXISTS (pending), which is why "yes" has something to
                # point at, but nothing about the owner has been kept: it will
                # never render, never be listed, and never be spoken.
                "stored": False,
                "row_id": written.get("id"),
                **decision.as_dict(),
            }

        self.facts_remembered += 1
        return {
            "status": STATUS_OK,
            "tool": TOOL_REMEMBER_FACT,
            # The stored VALUE is in the detail on purpose. R15's lesson applied
            # to a write: the model narrates what it is handed, so handing it the
            # exact text that went into the table is what makes "I've remembered
            # that your sister is called Hana" a true sentence rather than a
            # plausible one.
            "detail": f"remembered: {fact}",
            "action": action,
            "fact": fact,
            "key": key,
            "stored": True,
            "row_id": written.get("id"),
            **decision.as_dict(),
        }

    def _forget_fact(self, payload: Mapping[str, Any]) -> dict[str, object]:
        """"Don't remember that." Always honoured; never asks the policy.

        There is no rule under which the robot keeps a fact the owner told it to
        drop, so there is nothing here for a policy to decide. A key it does not
        hold is ``ok`` with ``forgotten: 0`` rather than a refusal — the owner
        asked for a state, the state now holds, and making them argue with a
        robot about whether it ever had the fact is not a product.
        """

        key = " ".join(str(payload.get("key") or "").split())
        if not key:
            # The model may have sent the fact text instead of the slug; deriving
            # the key from it is the same derivation the remember path uses, so
            # a round trip through both without an explicit key still lines up.
            key = _fact_key(str(payload.get("fact") or ""))
        if not key:
            return _refused(
                TOOL_REMEMBER_FACT, "say which fact to forget (its key, or the fact itself)"
            )
        try:
            result = dict(self._doors.forget_fact(key))
        except (KeyError, RuntimeError, TypeError, ValueError) as error:
            return _refused(TOOL_REMEMBER_FACT, f"the fact store is unavailable: {error}")
        forgotten = int(result.get("forgotten", 0) or 0)
        self.facts_forgotten += forgotten
        return {
            "status": STATUS_OK,
            "tool": TOOL_REMEMBER_FACT,
            "detail": (
                f"forgotten: {key}"
                if forgotten
                else f"nothing stored under {key!r}, so there was nothing to forget"
            ),
            "action": FACT_ACTION_FORGET,
            "key": key,
            "forgotten": forgotten,
        }

    def _list_facts(self) -> dict[str, object]:
        """"What do you know about me" — answered from the table.

        The door returns ONLY consented, live rows (the runtime filters, and
        :func:`~parcel_robot.owner_model.notes.owner_notes_from_facts` filters
        again inside the renderer). Pending and denied facts are not mentioned,
        not counted, and not hinted at: "I know three things and I'm not
        allowed to tell you one of them" is a disclosure of the thing itself.
        """

        try:
            rows = [str(item) for item in self._doors.known_facts()]
        except (KeyError, RuntimeError, TypeError, ValueError) as error:
            return _refused(TOOL_REMEMBER_FACT, f"the fact store is unavailable: {error}")
        clean = [" ".join(row.split()) for row in rows if str(row).strip()]
        return {
            "status": STATUS_OK,
            "tool": TOOL_REMEMBER_FACT,
            "detail": (
                "; ".join(clean)
                if clean
                else "nothing kept about the owner yet — say so plainly"
            ),
            "action": FACT_ACTION_LIST,
            "facts": clean,
            "count": len(clean),
        }

    def _play_gesture(self, payload: Mapping[str, Any]) -> dict[str, object]:
        try:
            name = _text(payload, "name")
        except ValueError as error:
            return _refused(TOOL_PLAY_GESTURE, str(error))
        intensity, clamped = _intensity(payload.get("intensity"))
        # ``run_skill`` is the supervisor's name for a catalog skill; the emote
        # allowlist is narrower still and is checked behind the door.
        allowed = self._validated(ToolCall("run_skill", {"name": name}), TOOL_PLAY_GESTURE)
        if allowed is not None:
            return allowed
        self._doors.on_dispatch()
        try:
            detail = self._doors.gesture(name, intensity)
        except ValueError as error:
            return _refused(TOOL_PLAY_GESTURE, str(error))
        except RuntimeError as error:
            # The activity coordinator declined a well-formed request: cooldown,
            # already running, queue full, or a busier channel owns the body.
            return _dropped(TOOL_PLAY_GESTURE, _reason(str(error)))
        return _from_disposition(
            TOOL_PLAY_GESTURE,
            detail,
            # Card R15. On the ``ok`` arm the runtime's own sentence is
            # "Accepted paw_wave for the next control tick" — an ACCEPTANCE the
            # model read as an accomplishment ("I waved. My paw moved", R5
            # session 1, endorsed as a defect by that card's audit). The fact
            # replaces it in ``detail``; the acceptance sentence is kept beside
            # it so the record loses nothing. The non-ok arms keep the runtime's
            # reason, which is the only thing that says WHY.
            started=f"the {name} gesture is running on the robot's body",
            extra={
                "name": name,
                "intensity": round(intensity, 3),
                "intensity_clamped": clamped,
            },
        )

    def _set_pose(self, payload: Mapping[str, Any]) -> dict[str, object]:
        try:
            name = _text(payload, "name")
        except ValueError as error:
            return _refused(TOOL_SET_POSE, str(error))
        allowed = self._validated(ToolCall("run_pose", {"name": name}), TOOL_SET_POSE)
        if allowed is not None:
            return allowed
        self._doors.on_dispatch()
        try:
            detail = self._doors.pose(name)
        except ValueError as error:
            return _refused(TOOL_SET_POSE, str(error))
        except RuntimeError as error:
            return _dropped(TOOL_SET_POSE, _reason(str(error)))
        return _from_disposition(
            TOOL_SET_POSE,
            detail,
            started=f"the robot is settling into the {name} pose",
            extra={"name": name},
        )

    def _navigate_to(self, payload: Mapping[str, Any]) -> dict[str, object]:
        try:
            place = _text(payload, "place")
        except ValueError as error:
            return _refused(TOOL_NAVIGATE_TO, str(error))
        # Card R10 — the place-noun gate. ``place`` must be a NAME, not a
        # directive fragment. The bench's three verbatim fabrications
        # ("with owner", "run route", "run path") each carry a function word or
        # an unknown head noun, and each would otherwise have rendered the junk
        # directive "go to with owner" straight into the router. Refused HERE,
        # before the router, with the reason and real alternatives in the result
        # so the model can say something true instead of guessing.
        try:
            known = tuple(str(name) for name in self._doors.places())
        except (KeyError, RuntimeError, TypeError, ValueError):
            known = ()
        verdict = validate_place(place, known)
        if not verdict.valid:
            nearest = verdict.nearest or tuple(known[:REFUSAL_PLACE_LIMIT])
            detail = (
                f"{place!r} describes an action, not a place; if the owner wants "
                "you to come along use follow_owner, and if they want a lap "
                "around them use circle_owner"
            )
            if nearest:
                detail = f"{detail}. Places the robot does know: {', '.join(nearest)}"
            refusal = _refused(TOOL_NAVIGATE_TO, detail)
            refusal.update(
                {
                    "place": place,
                    "valid_places": list(nearest),
                    "reason": verdict.reason,
                }
            )
            return refusal
        # Card P0-B, deliverable 2 — ASK, DO NOT GUESS.
        #
        # ``validate_place`` already separates the two failures a place noun can
        # have. "with owner" is not a place NAME and is refused above. "narnia"
        # is a perfectly good name the map has never heard of, and until now it
        # was admitted, rendered into the router and allowed to fail at
        # grounding — which is right for authority parity with a typed sentence
        # (R20's ``test_navigate_to_grants_exactly_what_a_typed_sentence_grants``)
        # and wrong for a companion, because what the owner hears is a robot
        # that set off and then gave up rather than one that asked.
        #
        # In ``ask`` mode this returns the question instead: the place the model
        # named, the places the robot does know, and no door touched. The map is
        # never consulted twice and no motion is started on a name the robot
        # cannot ground — the only thing that changes is who is asked next.
        if (
            verdict.reason == REASON_UNKNOWN_PLACE
            and self._unknown_place == UNKNOWN_PLACE_ASK
        ):
            self.unknown_place_asks += 1
            nearest = verdict.nearest or tuple(known[:REFUSAL_PLACE_LIMIT])
            detail = UNKNOWN_PLACE_DETAIL
            if nearest:
                detail = f"{detail}. Places the robot does know: {', '.join(nearest)}"
            return {
                "status": STATUS_UNKNOWN_PLACE,
                "tool": TOOL_NAVIGATE_TO,
                "detail": detail,
                "place": place,
                "valid_places": list(nearest),
                "reason": REASON_UNKNOWN_PLACE,
            }
        relation = _enum(payload.get("relation"), RELATION_HINTS_TUPLE, default="")
        directive = NAVIGATE_DIRECTIVE_TEMPLATE.format(place=place)
        allowed = self._validated(ToolCall("navigate", {"directive": directive}), TOOL_NAVIGATE_TO)
        if allowed is not None:
            return allowed
        self._doors.on_dispatch()
        try:
            detail = self._doors.navigate(place, relation)
        except ValueError as error:
            return _refused(TOOL_NAVIGATE_TO, str(error))
        except RuntimeError as error:
            return _dropped(TOOL_NAVIGATE_TO, _reason(str(error)))
        # Card R4-lite, task_1 — Defect C. ``detail`` is what the MODEL reads and
        # then says out loud, and until now it was whatever sentence the local
        # admission path happened to return ("Okay—I'll navigate toward … safely."),
        # the last survival of the legacy reply template on the realtime path.
        # The model does not need the robot's script; it needs the fact. The
        # admission reply is kept alongside so nothing is lost from the record.
        # Card R15 sharpens the same sentence. "mission accepted: the sidewalk"
        # was tense-NEUTRAL: accepted by whom, and is the robot walking yet? The
        # fact the model needs is that the trip is happening right now and has
        # not ended, in the one field it reads.
        return {
            "status": STATUS_OK,
            "tool": TOOL_NAVIGATE_TO,
            "detail": f"the robot is walking to {place}",
            "admitted": detail,
            "place": place,
            "directive": directive,
            "relation_hint": relation,
        }

    def _circle_owner(self, payload: Mapping[str, Any]) -> dict[str, object]:
        """``circle_owner`` — card R10 item 3, half of the surface hole.

        Routed through the supervisor's EXISTING ``run_spatial_behavior`` arm,
        which already knows ``orbit_owner`` and already enforces the direction /
        size / revolutions enums and the e-stop. No new authority is created
        here: the broker validates the shape, the supervisor validates the
        request, and the runtime door is the same one a typed "walk in a circle
        around me" reaches.
        """

        direction = _enum(
            payload.get("direction"), ORBIT_DIRECTIONS, default=DEFAULT_ORBIT_DIRECTION
        )
        size = _enum(payload.get("size"), ORBIT_SIZES, default=DEFAULT_ORBIT_SIZE)
        revolutions = _revolutions(payload.get("revolutions"))
        allowed = self._validated(
            ToolCall(
                "run_spatial_behavior",
                {
                    "behavior": "orbit_owner",
                    "direction": direction,
                    "size": size,
                    "revolutions": revolutions,
                },
            ),
            TOOL_CIRCLE_OWNER,
        )
        if allowed is not None:
            return allowed
        self._doors.on_dispatch()
        try:
            detail = self._doors.orbit(direction, size, revolutions)
        except ValueError as error:
            # The feasibility validator's refusal arrives here. It is a REJECT,
            # not a drop: the request was well-formed and the robot genuinely
            # cannot do it right now, and the sentence explains why so the model
            # narrates a true reason instead of inventing one.
            return _refused(TOOL_CIRCLE_OWNER, str(error))
        except RuntimeError as error:
            return _dropped(TOOL_CIRCLE_OWNER, _reason(str(error)))
        # Card R15 — THE F2 LINE. Until this card ``detail`` was the runtime's
        # own acknowledgement, verbatim: "Okay—I'll make the requested local
        # circle around you safely." Owner session 1 has the model answering
        # that with "Done—I made a small circle around you, and it was okay"
        # ONE SECOND later, while the dog was still on its first quarter. The
        # promise is kept on the record as ``admitted``; what the model reads is
        # the fact, and the fact is in the present progressive.
        return {
            "status": STATUS_OK,
            "tool": TOOL_CIRCLE_OWNER,
            "detail": (
                f"the robot is walking a {direction} circle around you, "
                f"{revolutions:g} of a lap"
            ),
            "admitted": _reason(str(detail)),
            "direction": direction,
            "size": size,
            "revolutions": revolutions,
        }

    def _follow_owner(self, payload: Mapping[str, Any]) -> dict[str, object]:
        """``follow_owner(pace)`` — the other half of the surface hole.

        Routed through the supervisor's existing ``set_behavior`` arm with mode
        ``follow``, i.e. the same validation "follow me" already takes.

        ``pace`` is CARRIED, not acted on: R11 owns pace_intent. The result says
        so explicitly, because the bench's B2 finding was the model announcing
        an adaptation that had not happened ("I'm matching your slower pace"
        while the injected gait was still RUN). A pace the body did not change
        must never come back as though it had.
        """

        pace = _enum(payload.get("pace"), FOLLOW_PACES, default=DEFAULT_FOLLOW_PACE)
        allowed = self._validated(
            ToolCall("set_behavior", {"mode": "follow"}), TOOL_FOLLOW_OWNER
        )
        if allowed is not None:
            return allowed
        self._doors.on_dispatch()
        try:
            detail = self._doors.follow(pace)
        except ValueError as error:
            return _refused(TOOL_FOLLOW_OWNER, str(error))
        except RuntimeError as error:
            return _dropped(TOOL_FOLLOW_OWNER, _reason(str(error)))
        return {
            "status": STATUS_OK,
            "tool": TOOL_FOLLOW_OWNER,
            # Card R15. Follow is the one activity with no ending of its own —
            # it runs until something stops it — so its tense is the whole of
            # its truth: the robot is doing this NOW, and there is no moment at
            # which "I followed you" becomes a true thing to volunteer.
            "detail": "the robot is keeping station on you and walking with you",
            "admitted": _reason(str(detail)),
            "pace": pace,
            "pace_applied": False,
            "pace_note": (
                "the robot is keeping station on you at its own safe pace; it has "
                "not changed speed for this request"
            ),
        }

    # ------------------------------------------------------------- plumbing
    def _validated(self, call: ToolCall, tool: str) -> dict[str, object] | None:
        """``None`` means the supervisor allowed it. Anything else is the answer."""

        try:
            result = self._doors.validate(call)
        except (RuntimeError, TypeError, ValueError) as error:  # pragma: no cover
            return _refused(tool, f"safety validation failed: {error}")
        if not getattr(result, "accepted", False):
            return _refused(tool, str(getattr(result, "message", "refused")))
        return None


def _reason(text: str) -> str:
    """Strip the runtime's disposition prefix; the status field carries it."""

    clean = str(text).strip()
    for prefix in ("Rejected:", "Skipped:", "Deferred:", "Accepted:"):
        if clean.startswith(prefix):
            return clean[len(prefix) :].strip()
    return clean


def _from_disposition(
    tool: str,
    detail: str,
    *,
    started: str = "",
    extra: Mapping[str, object] | None = None,
) -> dict[str, object]:
    """Map ``propose_action``'s status prefix onto the result vocabulary.

    ``started`` (card R15) is the FACT to hand the model when the coordinator
    took the request — the activity is now under way, and the runtime's
    acceptance sentence goes to ``admitted`` instead of into the model's mouth.
    Only the ``ok`` arm is replaced: a deferral or a drop is carried by the
    runtime's own reason, which is the half that explains itself.
    """

    clean = str(detail).strip()
    reason = _reason(clean) or clean
    body: dict[str, object] = {"tool": tool, "detail": reason}
    body.update(dict(extra or {}))
    if clean.startswith("Deferred:"):
        body["status"] = STATUS_DEFERRED
        return body
    if clean.startswith(("Rejected:", "Skipped:")):
        body["status"] = STATUS_DROPPED
        return body
    body["status"] = STATUS_OK
    if started:
        body["detail"] = started
        body["admitted"] = reason
    return body


def _detail_words(detail: str) -> tuple[str, ...]:
    """Lowercase word tokens, apostrophes kept so ``I'll`` survives as one word."""

    word: list[str] = []
    words: list[str] = []
    for char in str(detail).lower():
        if char.isalnum() or char == "'":
            word.append(char)
        elif word:
            words.append("".join(word))
            word = []
    if word:
        words.append("".join(word))
    return tuple(words)


def detail_tense_violation(detail: str) -> str:
    """Card R15. Why this activity detail may not be shown to the model, or ``""``.

    THE RULE, EXECUTABLE. Three things are checked, in the order they cost the
    owner something:

    1. it must open with a tense marker, so the model cannot be in any doubt
       about whether the body is moving;
    2. it must contain no completion word, because a broker answer is returned
       while the movement is still happening and there is nothing it could
       truthfully be reporting the end of;
    3. it must not speak in the robot's first person, because a promise
       ("Okay—I'll walk a circle around you") is what the model compressed into
       "Done—I made a small circle around you" one second later.

    DELIBERATELY A PREDICATE AND NOT A SANITISER. A broker that quietly rewrote
    a bad detail would make the regression invisible: the seed that puts
    completion language back would come back GREEN and the tests would be
    pinning the scrubber instead of the wording. The rule is enforced by tests
    over every tool × every disposition, which is where a wording rule belongs.
    """

    clean = " ".join(str(detail).split())
    if not clean:
        return "empty detail"
    tense = next(
        (name for name in (TENSE_NOT_STARTED, TENSE_STARTED, TENSE_WAITING)
         if clean.startswith(f"{name}: ")),
        "",
    )
    if not tense:
        return "missing tense marker"
    body = clean[len(tense) + 2 :]
    for word in _detail_words(body):
        if word in COMPLETION_LANGUAGE:
            return f"completion language: {word!r}"
        if word in SCRIPT_LANGUAGE:
            return f"speaks in the robot's own voice: {word!r}"
    return ""


def _tensed(body: dict[str, object]) -> dict[str, object]:
    """Stamp an activity-class result with the tense the model must narrate in.

    Applied in ONE place — :meth:`RealtimeToolBroker.handle` — rather than at
    each tool's return, so a tool added to :data:`ACTIVITY_TOOLS` tomorrow
    cannot be the one that forgets. ``finished`` is unconditionally ``False``
    because it is unconditionally true that it is: see :data:`TENSE_BY_STATUS`.
    """

    status = str(body.get("status", STATUS_REJECTED))
    tense = TENSE_BY_STATUS.get(status, TENSE_NOT_STARTED)
    detail = " ".join(str(body.get("detail", "")).split())
    body["detail"] = f"{tense}: {detail}" if detail else tense
    body["tense"] = tense
    body["finished"] = False
    if status in {STATUS_OK, STATUS_DEFERRED}:
        body["completion_note"] = COMPLETION_NOTE
    return body


def _refused(tool: str, reason: str) -> dict[str, object]:
    return {"status": STATUS_REJECTED, "tool": tool, "detail": str(reason)}


def _dropped(tool: str, reason: str) -> dict[str, object]:
    return {"status": STATUS_DROPPED, "tool": tool, "detail": str(reason)}


def _arguments(raw: str) -> Mapping[str, Any]:
    text = str(raw).strip()
    if not text:
        return {}
    try:
        parsed = json.loads(text)
    except (TypeError, ValueError) as error:
        raise ValueError(f"tool arguments are not valid JSON: {error}") from None
    if not isinstance(parsed, Mapping):
        raise TypeError("tool arguments must be a JSON object")
    return parsed


def _text(payload: Mapping[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{key} must be a non-empty string")
    clean = " ".join(value.split())
    if len(clean) > MAX_ARGUMENT_CHARS:
        raise ValueError(f"{key} is too long")
    return clean


def _enum(value: object, allowed: Sequence[str], *, default: str) -> str:
    """Coerce an enum argument, falling back to ``default`` rather than failing.

    A model that sends ``size="medium"`` gets a normal circle and a robot that
    moves; the supervisor still sees only a value from the closed set. Junk
    never reaches a door, and a near-miss never costs the owner their request.
    """

    if not isinstance(value, str):
        return default
    clean = " ".join(value.split()).lower()
    return clean if clean in tuple(allowed) else default


#: Card P2-A. Words that carry no identity, dropped when a key is derived from
#: the fact text. Short and closed rather than a general stopword list: the key
#: only has to be STABLE (so a second statement about the same subject replaces
#: the first) and READABLE in a panel, not linguistically principled.
_FACT_KEY_SKIP: frozenset[str] = frozenset(
    {
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "in",
        "is",
        "it",
        "of",
        "on",
        "or",
        "that",
        "the",
        "their",
        "they",
        "them",
        "to",
        "with",
    }
)

#: How many content words a derived key keeps. Three is enough to separate
#: "sister called" from "brother called" and short enough to read.
_FACT_KEY_WORDS = 3


def _fact_key(fact: str) -> str:
    """A stable slug for a fact the model did not name.

    The model is ASKED for a key and often will not send one. Deriving it here
    rather than storing an anonymous row is what makes the upsert work at all:
    without a key, "their sister is called Hana" and a later correction to
    "their sister is called Hanna" are two facts, and the robot believes both.
    """

    words = [
        word
        for word in "".join(
            ch if ch.isalnum() else " " for ch in str(fact or "").lower()
        ).split()
        if word not in _FACT_KEY_SKIP
    ]
    return "_".join(words[:_FACT_KEY_WORDS])


def _redacted_key(decision: object) -> str:
    """A key for a refused fact, built ONLY from the policy's own vocabulary.

    Never from the owner's text. ``matched`` is a subset of the policy's closed
    term lists, so the worst this can return is the name of the category of
    thing that was refused — ``password``, ``pin`` — which is exactly what the
    model needs to say and contains none of what it must not.
    """

    matched = tuple(str(word) for word in getattr(decision, "matched", ()) if str(word).strip())
    return "_".join(sorted(set(matched))[:_FACT_KEY_WORDS]) or "redacted"


def _revolutions(value: object) -> float:
    """Clamp laps into the supervisor's own [0.25, 1.0] window."""

    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return DEFAULT_ORBIT_REVOLUTIONS
    number = float(value)
    if not math.isfinite(number):
        return DEFAULT_ORBIT_REVOLUTIONS
    return min(MAX_ORBIT_REVOLUTIONS, max(MIN_ORBIT_REVOLUTIONS, number))


#: Why a place was refused.
REASON_NOT_A_PLACE_NAME = "not_a_place_name"
REASON_UNKNOWN_PLACE = "unknown_place"

#: Function words that never appear in a place NAME. A place is a noun phrase;
#: a directive fragment carries one of these. This closed set is what separates
#: the bench's fabrications ("**with** owner", "**run** path") from a real
#: multi-word place ("the big oak tree"), WITHOUT refusing ordinary adjectives —
#: refusing those would be a capability regression against today's grammar,
#: which happily peels "big" and grounds "oak tree".
PLACE_FUNCTION_WORDS: frozenset[str] = frozenset(
    {
        "about",
        "across",
        "after",
        "along",
        "alongside",
        "around",
        "at",
        "before",
        "behind",
        "beside",
        "between",
        "beyond",
        "by",
        "down",
        "during",
        "for",
        "from",
        "into",
        "of",
        "off",
        "onto",
        "or",
        "over",
        "past",
        "through",
        "toward",
        "towards",
        "under",
        "until",
        "up",
        "upon",
        "via",
        "while",
        "with",
        "without",
        # NOT conjunctions. "the sidewalk and then sit" is a compound, and the
        # ROUTER has always been the thing that refuses compounds — pinned by
        # ``test_navigate_to_refuses_what_the_router_does_not_call_a_navigation``.
        # Catching it here would move that refusal into a second grammar and
        # change the reason the owner hears for no reason at all.
        # Motion verbs. "run path" and "run route" are directives wearing a
        # noun's clothes; a place is never named after the gait used to get to it.
        "chase",
        "come",
        "follow",
        "go",
        "head",
        "jog",
        "move",
        "run",
        "running",
        "sprint",
        "trot",
        "walk",
        "walking",
    }
)

#: Article/positional/size modifiers that may decorate a place name.
PLACE_MODIFIERS: frozenset[str] = frozenset(
    {
        "a",
        "ahead",
        "an",
        "big",
        "closest",
        "east",
        "far",
        "front",
        "large",
        "left",
        "little",
        "main",
        "my",
        "nearby",
        "nearest",
        "next",
        "north",
        "other",
        "right",
        "safe",
        "safer",
        "small",
        "south",
        "tall",
        "that",
        "the",
        "this",
        "west",
        "your",
    }
)

RELATION_HINTS_TUPLE = ("inside", "near", "social")


@dataclass(frozen=True)
class PlaceVerdict:
    valid: bool
    reason: str = ""
    #: Real places to offer back when the answer is no, nearest first.
    nearest: tuple[str, ...] = ()


def validate_place(place: str, known: Sequence[str]) -> PlaceVerdict:
    """Is ``place`` a place NAME at all? — card R10's junk-place gate.

    THE SCOPE IS DELIBERATELY NARROW, and the narrowness is the design.

    Only one thing is refused here: a string that is not a place name — a
    directive fragment carrying a preposition or a motion verb. That is exactly
    the class the bench measured the mini tier fabricating, verbatim:
    ``{"place": "with owner"}`` (preposition), ``{"place": "run route"}`` and
    ``{"place": "run path"}`` (motion verb). Each would otherwise have rendered
    "go to with owner" into the router as a real directive.

    A perfectly good noun the robot has never heard of — "narnia" — is NOT
    refused. It is admitted, routed, and allowed to fail honestly at grounding,
    because that is precisely what a typed "go to narnia" does, and
    ``test_navigate_to_grants_exactly_what_a_typed_sentence_grants`` pins that
    authority parity for a good reason: a broker stricter than the typed path
    would be the hosted lane growing its own private grammar. The verdict still
    reports ``unknown_place`` so the difference is visible, but it stays valid.
    """

    phrase = " ".join(str(place).split()).lower()
    if not phrase:
        return PlaceVerdict(False, REASON_NOT_A_PLACE_NAME)
    vocabulary = {" ".join(str(name).split()).lower(): str(name) for name in known}
    if phrase in vocabulary:
        return PlaceVerdict(True)
    words = phrase.replace(",", " ").split()
    if any(word in PLACE_FUNCTION_WORDS for word in words):
        return PlaceVerdict(False, REASON_NOT_A_PLACE_NAME, _nearest_places(vocabulary))
    nouns = [word for word in words if word not in PLACE_MODIFIERS]
    if not nouns:
        # Modifiers only ("the nearest") names nothing at all.
        return PlaceVerdict(False, REASON_NOT_A_PLACE_NAME, _nearest_places(vocabulary))
    if " ".join(nouns) in vocabulary or nouns[-1] in vocabulary:
        # Whole phrase or head noun: "the big oak tree" is the tree it knows.
        return PlaceVerdict(True)
    return PlaceVerdict(True, REASON_UNKNOWN_PLACE, _nearest_places(vocabulary))


def _nearest_places(vocabulary: Mapping[str, str]) -> tuple[str, ...]:
    """The places to offer back. Order preserved — the door sorts by distance."""

    return tuple(vocabulary.values())[:REFUSAL_PLACE_LIMIT]


def _intensity(value: object) -> tuple[float, bool]:
    """Clamp into [0.5, 1.5]. Returns the value and whether it was clamped."""

    if value is None:
        return DEFAULT_INTENSITY, False
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return DEFAULT_INTENSITY, True
    number = float(value)
    if not math.isfinite(number):
        return DEFAULT_INTENSITY, True
    clamped = min(MAX_INTENSITY, max(MIN_INTENSITY, number))
    return clamped, clamped != number


__all__ = [
    "ACTIVITY_TOOLS",
    "ANSWER_RESULT_KEY",
    "ANSWER_TOOLS",
    "BROKER_TOOLS",
    "COMPLETION_LANGUAGE",
    "COMPLETION_NOTE",
    "FOLLOW_PACES",
    "MAX_INTENSITY",
    "MIN_INTENSITY",
    "MOTION_TOOLS",
    "NAVIGATE_DIRECTIVE_TEMPLATE",
    "ORBIT_DIRECTIONS",
    "ORBIT_SIZES",
    "PLACE_FUNCTION_WORDS",
    "PROACTIVE_MOTION_CEILING",
    "PROVENANCE_RESULT_KEY",
    "REASON_NOT_A_PLACE_NAME",
    "REASON_UNKNOWN_PLACE",
    "REFUSAL_PLACE_LIMIT",
    "REFUSAL_SYSTEM_INITIATED_MOTION",
    "RESPONSE_FROM_OWNER",
    "RESPONSE_FROM_SYSTEM",
    "SCRIPT_LANGUAGE",
    "STATUS_DEFERRED",
    "STATUS_DROPPED",
    "STATUS_OK",
    "STATUS_REJECTED",
    "STATUS_UNKNOWN_PLACE",
    "SYSTEM_INITIATED_MOTION_DETAIL",
    "TENSE_BY_STATUS",
    "TENSE_NOT_STARTED",
    "TENSE_STARTED",
    "TENSE_WAITING",
    "TOOL_CIRCLE_OWNER",
    "TOOL_FOLLOW_OWNER",
    "TOOL_GET_STATUS",
    "TOOL_NAVIGATE_TO",
    "TOOL_PLAY_GESTURE",
    "TOOL_RECALL_MEMORY",
    "TOOL_SET_POSE",
    "UNKNOWN_PLACE_ASK",
    "UNKNOWN_PLACE_DETAIL",
    "UNKNOWN_PLACE_REFUSE",
    "PlaceVerdict",
    "RealtimeToolBroker",
    "SessionToolsUpdate",
    "ToolBrokerError",
    "ToolDoors",
    "build_tool_specs",
    "detail_tense_violation",
    "validate_place",
]
