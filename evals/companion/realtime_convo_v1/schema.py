"""Corpus schema: scenarios in, fixtures out, fixtures back into the lane.

THE ONE THING THIS FILE EXISTS FOR
----------------------------------
A round trip that closes:

    scenarios.json  --(scraper, live)-->  fixtures/*.json
    fixtures/*.json --(fixture_to_script)-->  FakeRealtimeServer steps
    steps           --(RealtimeLane)-->  ledger rows + usage rows

The middle arrow is the load-bearing one. If a scraped conversation cannot be
turned back into a script the *real* lane will drive, the corpus is a pile of
transcripts rather than a regression suite. Three hand-authored seed fixtures
first proved that arrow without a credential; the 2026-08-18 live scrape then
overwrote those thread ids with 25 captured conversations read by the same
loader.

FAIL CLOSED, LIKE EVERY OTHER BOUNDARY HERE
-------------------------------------------
``protocol.py`` refuses an unknown event type; ``config.py`` refuses an unknown
config key; this refuses an unknown scenario family, an unknown fixture key, a
thread id that does not match its filename, and a turn count outside the
authored band. A corpus that silently accepted a malformed fixture would let a
half-captured scrape masquerade as evidence.

NO AUDIO IS EVER INVENTED
-------------------------
The scrape runs in the **text** modality: there are no captured PCM bytes to
store, so fixtures carry none and :func:`fixture_to_script` emits none by
default. ``synthetic_audio_ms`` exists so one test can drive the playback
bridge, and what it emits is ``fake_server.pcm_tone`` — a deterministic tone
that is obviously not speech. It is never written into a fixture.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from parcel_robot.prompting.loader import PromptLibrary
from parcel_robot.realtime.fake_server import (
    Step,
    audio_delta,
    audio_done,
    function_call,
    input_transcript,
    pcm_tone,
    response_done,
    session_created,
    speech_started,
    speech_stopped,
    transcript_delta,
    transcript_done,
)
from parcel_robot.realtime.prompting import (
    DI_VERSION,
    SI_VERSION,
    DeveloperFlags,
    render_developer_instruction,
    render_system_instruction,
    si_pin,
)

PACK_ROOT = Path(__file__).resolve().parent
REPO_ROOT = PACK_ROOT.parents[2]
SCENARIOS_PATH = PACK_ROOT / "scenarios.json"
FIXTURES_DIR = PACK_ROOT / "fixtures"
MANIFEST_PATH = PACK_ROOT / "corpus.manifest.json"

SCHEMA_VERSION = 1
SUITE_ID = "parcel-realtime-convo-v1"

#: The model the scrape targets. Recorded in every fixture: a transcript from a
#: different model is a different corpus, not a longer one.
SCRAPE_MODEL = "gpt-realtime-2.1-mini"

#: Scenario families. ``navigation`` and ``perception`` are the two
#: navigation-flavoured halves (going somewhere / looking at something);
#: ``conversation`` is the companion half; ``punt`` is the set that should end
#: in an honest "I can't".
FAMILIES = frozenset({"navigation", "perception", "conversation", "punt"})

#: Probe tags. Free-form would rot; this set is the vocabulary.
PROBES = frozenset(
    {
        "ambiguous_target",
        "correction",
        "distance_limit",
        "emotional_support",
        "memory_callback",
        "owner_verbatim",
        "perception_limit",
        "persona_consistency",
        "physical_limit",
        "privacy_refusal",
        "route_confirmation",
        "safety_deferral",
        "small_talk",
        "unreachable",
    }
)

#: Owner turns per thread, inclusive. Fewer than six is not a conversation;
#: more than twelve stops being one owner sitting down with a robot dog.
MIN_TURNS = 6
MAX_TURNS = 12

#: The two owner utterances the card names verbatim. Pinned here so that an
#: edit to ``scenarios.json`` that loses them reddens rather than drifts.
OWNER_VERBATIM = (
    "I am hungry, let's go to mcdonald's",
    "Can you see the closest lamppost?",
)

#: Tool names declared to the model during the scrape. R1's broker refuses all
#: of them; capturing the PROPOSAL is the point (tools land in R3).
DECLARED_TOOLS = ("navigate_to", "get_status", "play_gesture")

FIXTURE_SOURCE_SEED = "hand_authored"
FIXTURE_SOURCE_SCRAPE = "live_scrape"
FIXTURE_SOURCES = frozenset({FIXTURE_SOURCE_SEED, FIXTURE_SOURCE_SCRAPE})


class CorpusError(ValueError):
    """A scenario or fixture this pack refuses to treat as evidence."""


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(Path(path).read_bytes())


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise CorpusError(message)


def _mapping(value: Any, what: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise CorpusError(f"{what} must be a mapping, got {type(value).__name__}")
    return value


def _known_keys(payload: Mapping[str, Any], allowed: frozenset[str], what: str) -> None:
    unknown = sorted(str(key) for key in payload if str(key) not in allowed)
    _require(
        not unknown,
        f"{what} carries unknown key(s): {', '.join(unknown)}; "
        f"allowed: {', '.join(sorted(allowed))}",
    )


def _text_list(value: Any, what: str) -> tuple[str, ...]:
    if value is None:
        return ()
    _require(isinstance(value, list), f"{what} must be a list of strings")
    out: list[str] = []
    for item in value:
        _require(isinstance(item, str) and item.strip(), f"{what} must be non-empty strings")
        out.append(item)
    return tuple(out)


# ----------------------------------------------------------------- scenarios
SCENARIO_KEYS = frozenset(
    {"thread_id", "title", "family", "probes", "si_profile", "di", "owner_turns", "expect"}
)


@dataclass(frozen=True)
class Scenario:
    """One authored thread. The owner side is FIXED text, deliberately.

    A model-generated owner side would make every re-scrape a different
    experiment. These 25 owner scripts are the constant the corpus varies the
    *model* against, so a 2027 re-scrape is comparable to the 2026 one.
    """

    thread_id: str
    title: str
    family: str
    probes: tuple[str, ...]
    si_profile: str
    flags: DeveloperFlags
    owner_turns: tuple[str, ...]
    expect: tuple[str, ...]

    @property
    def turn_count(self) -> int:
        return len(self.owner_turns)


def scenario_from_mapping(payload: Mapping[str, Any]) -> Scenario:
    body = _mapping(payload, "scenario")
    _known_keys(body, SCENARIO_KEYS, "scenario")
    thread_id = str(body.get("thread_id", "")).strip()
    _require(bool(thread_id), "scenario needs a thread_id")
    family = str(body.get("family", "")).strip()
    _require(family in FAMILIES, f"{thread_id}: unknown family {family!r}")
    probes = _text_list(body.get("probes"), f"{thread_id}: probes")
    unknown_probes = sorted(set(probes) - PROBES)
    _require(not unknown_probes, f"{thread_id}: unknown probe(s) {', '.join(unknown_probes)}")
    owner_turns = _text_list(body.get("owner_turns"), f"{thread_id}: owner_turns")
    _require(
        MIN_TURNS <= len(owner_turns) <= MAX_TURNS,
        f"{thread_id}: {len(owner_turns)} owner turns is outside {MIN_TURNS}-{MAX_TURNS}",
    )
    return Scenario(
        thread_id=thread_id,
        title=str(body.get("title", "")).strip(),
        family=family,
        probes=probes,
        si_profile=str(body.get("si_profile", "")).strip(),
        flags=DeveloperFlags.from_mapping(_mapping(body.get("di"), f"{thread_id}: di")),
        owner_turns=owner_turns,
        expect=_text_list(body.get("expect"), f"{thread_id}: expect"),
    )


def load_scenarios(path: Path = SCENARIOS_PATH) -> tuple[Scenario, ...]:
    """Read, validate and refuse duplicates. Order is the file's order."""

    body = _mapping(json.loads(Path(path).read_text(encoding="utf-8")), "scenarios file")
    _require(
        int(body.get("schema_version", 0)) == SCHEMA_VERSION,
        f"scenarios schema_version must be {SCHEMA_VERSION}",
    )
    raw = body.get("scenarios")
    _require(isinstance(raw, list) and bool(raw), "scenarios must be a non-empty list")
    scenarios = tuple(scenario_from_mapping(item) for item in raw)
    ids = [scenario.thread_id for scenario in scenarios]
    _require(len(set(ids)) == len(ids), "duplicate thread_id in scenarios.json")
    return scenarios


# ------------------------------------------------------------------ fixtures
TOOL_CALL_KEYS = frozenset({"call_id", "name", "arguments"})
TURN_KEYS = frozenset(
    {
        "index",
        "owner_item_id",
        "owner_text",
        "response_id",
        "robot_item_id",
        "robot_text",
        "tool_calls",
        "usage",
    }
)
FIXTURE_KEYS = frozenset(
    {
        "schema_version",
        "thread_id",
        "title",
        "family",
        "probes",
        "source",
        "model",
        "captured_at",
        "si_profile",
        "si_version",
        "si_digest",
        "di_version",
        "di_digest",
        "di_flags",
        "declared_tools",
        "turns",
        "usage_totals",
        "notes",
    }
)
USAGE_KEYS = (
    "input_tokens",
    "output_tokens",
    "input_audio_tokens",
    "output_audio_tokens",
    "cached_tokens",
)


@dataclass(frozen=True)
class ToolCall:
    """A function-call PROPOSAL the model made. R1 answers every one with a refusal."""

    call_id: str
    name: str
    arguments: str


@dataclass(frozen=True)
class Turn:
    """One owner utterance and everything the provider said back to it."""

    index: int
    owner_item_id: str
    owner_text: str
    response_id: str
    robot_item_id: str
    robot_text: str
    tool_calls: tuple[ToolCall, ...]
    usage: Mapping[str, int]


@dataclass(frozen=True)
class Fixture:
    """One captured (or hand-authored) thread, replayable offline forever."""

    thread_id: str
    title: str
    family: str
    probes: tuple[str, ...]
    source: str
    model: str
    captured_at: str | None
    si_profile: str
    si_version: str
    si_digest: str
    di_version: str
    di_digest: str
    flags: DeveloperFlags
    declared_tools: tuple[str, ...]
    turns: tuple[Turn, ...]
    usage_totals: Mapping[str, int]
    notes: str = ""

    @property
    def tool_names(self) -> tuple[str, ...]:
        return tuple(call.name for turn in self.turns for call in turn.tool_calls)


def _usage_from(payload: Any, what: str) -> dict[str, int]:
    body = _mapping(payload or {}, what)
    unknown = sorted(str(key) for key in body if str(key) not in USAGE_KEYS)
    _require(not unknown, f"{what} carries unknown usage key(s): {', '.join(unknown)}")
    out: dict[str, int] = {}
    for key in USAGE_KEYS:
        value = body.get(key, 0)
        _require(
            isinstance(value, int) and not isinstance(value, bool) and value >= 0,
            f"{what}.{key} must be a non-negative integer",
        )
        out[key] = int(value)
    return out


def _tool_call_from(payload: Any, what: str) -> ToolCall:
    body = _mapping(payload, what)
    _known_keys(body, TOOL_CALL_KEYS, what)
    name = str(body.get("name", "")).strip()
    _require(bool(body.get("call_id")), f"{what} needs a call_id")
    _require(bool(name), f"{what} needs a name")
    arguments = body.get("arguments", "{}")
    _require(isinstance(arguments, str), f"{what}.arguments must be a JSON string")
    try:
        json.loads(arguments)
    except json.JSONDecodeError as error:
        raise CorpusError(f"{what}.arguments is not valid JSON: {error}") from error
    return ToolCall(call_id=str(body["call_id"]), name=name, arguments=arguments)


def _turn_from(payload: Any, what: str) -> Turn:
    body = _mapping(payload, what)
    _known_keys(body, TURN_KEYS, what)
    for key in ("owner_item_id", "owner_text", "response_id", "robot_item_id"):
        _require(bool(str(body.get(key, "")).strip()), f"{what} needs a non-empty {key}")
    robot_text = body.get("robot_text", "")
    _require(isinstance(robot_text, str), f"{what}.robot_text must be a string")
    raw_calls = body.get("tool_calls") or []
    _require(isinstance(raw_calls, list), f"{what}.tool_calls must be a list")
    return Turn(
        index=int(body.get("index", 0)),
        owner_item_id=str(body["owner_item_id"]),
        owner_text=str(body["owner_text"]),
        response_id=str(body["response_id"]),
        robot_item_id=str(body["robot_item_id"]),
        robot_text=robot_text,
        tool_calls=tuple(
            _tool_call_from(item, f"{what}.tool_calls[{n}]") for n, item in enumerate(raw_calls)
        ),
        usage=_usage_from(body.get("usage"), f"{what}.usage"),
    )


def fixture_from_mapping(payload: Mapping[str, Any]) -> Fixture:
    body = _mapping(payload, "fixture")
    _known_keys(body, FIXTURE_KEYS, "fixture")
    _require(
        int(body.get("schema_version", 0)) == SCHEMA_VERSION,
        f"fixture schema_version must be {SCHEMA_VERSION}",
    )
    thread_id = str(body.get("thread_id", "")).strip()
    _require(bool(thread_id), "fixture needs a thread_id")
    source = str(body.get("source", "")).strip()
    _require(source in FIXTURE_SOURCES, f"{thread_id}: unknown fixture source {source!r}")
    family = str(body.get("family", "")).strip()
    _require(family in FAMILIES, f"{thread_id}: unknown family {family!r}")
    raw_turns = body.get("turns")
    _require(isinstance(raw_turns, list) and bool(raw_turns), f"{thread_id}: turns must be a list")
    turns = tuple(_turn_from(item, f"{thread_id}.turns[{n}]") for n, item in enumerate(raw_turns))
    for position, turn in enumerate(turns):
        _require(
            turn.index == position,
            f"{thread_id}: turn index {turn.index} is out of order at position {position}",
        )
    captured = body.get("captured_at")
    _require(captured is None or isinstance(captured, str), f"{thread_id}: captured_at")
    return Fixture(
        thread_id=thread_id,
        title=str(body.get("title", "")).strip(),
        family=family,
        probes=_text_list(body.get("probes"), f"{thread_id}: probes"),
        source=source,
        model=str(body.get("model", "")).strip(),
        captured_at=captured,
        si_profile=str(body.get("si_profile", "")).strip(),
        si_version=str(body.get("si_version", "")).strip(),
        si_digest=str(body.get("si_digest", "")).strip(),
        di_version=str(body.get("di_version", "")).strip(),
        di_digest=str(body.get("di_digest", "")).strip(),
        flags=DeveloperFlags.from_mapping(_mapping(body.get("di_flags"), f"{thread_id}: di_flags")),
        declared_tools=_text_list(body.get("declared_tools"), f"{thread_id}: declared_tools"),
        turns=turns,
        usage_totals=_usage_from(body.get("usage_totals"), f"{thread_id}: usage_totals"),
        notes=str(body.get("notes", "")),
    )


def load_fixture(path: Path) -> Fixture:
    """One fixture. The filename must equal the thread id — no orphan files."""

    resolved = Path(path)
    fixture = fixture_from_mapping(json.loads(resolved.read_text(encoding="utf-8")))
    _require(
        resolved.stem == fixture.thread_id,
        f"fixture filename {resolved.name} does not match thread_id {fixture.thread_id!r}",
    )
    return fixture


def load_fixtures(directory: Path = FIXTURES_DIR) -> tuple[Fixture, ...]:
    return tuple(load_fixture(path) for path in sorted(Path(directory).glob("*.json")))


def verify_prompt_plane(fixture: Fixture, *, library: PromptLibrary | None = None) -> None:
    """Tie one fixture to the exact words that produced it. Three checks.

    1. The fixture's ``si_digest`` equals the digest pinned for its own
       ``si_version``. This one survives an SI bump: a transcript captured under
       v1 keeps agreeing with v1 forever, which is what makes an old fixture
       still readable evidence after the prompt legitimately moves on.
    2. If the fixture was captured under the *current* ``SI_VERSION``, the SI
       rendered from today's tree must still hash to that same pin. This is the
       check that reddens when the SI text is edited without a version bump.
    3. The DI re-rendered from the fixture's own stored flags must hash to its
       stored ``di_digest`` — i.e. the renderer is still a pure function of the
       snapshot, with no clock, environment or filesystem leaking into it.
    """

    pinned = si_pin(fixture.si_profile, version=fixture.si_version)
    _require(
        fixture.si_digest == pinned,
        f"{fixture.thread_id}: fixture si_digest {fixture.si_digest[:12]}… does not match "
        f"the digest pinned for {fixture.si_profile}@{fixture.si_version} ({pinned[:12]}…)",
    )
    if fixture.si_version == SI_VERSION:
        si = render_system_instruction(
            profile_id=fixture.si_profile, library=library, version=fixture.si_version
        )
        _require(
            si.digest == pinned,
            f"{fixture.thread_id}: SI text drift — {fixture.si_profile}@{fixture.si_version} "
            f"is pinned at {pinned[:12]}… but the tree now renders {si.digest[:12]}…. "
            f"An SI edit needs an SI_VERSION bump and a new SI_DIGESTS entry.",
        )
    di = render_developer_instruction(fixture.flags, version=fixture.di_version)
    _require(
        di.digest == fixture.di_digest,
        f"{fixture.thread_id}: DI digest drift — fixture pinned {fixture.di_digest[:12]}…, "
        f"the stored flags now render {di.digest[:12]}…. The DI renderer must be a pure "
        f"function of the stored snapshot.",
    )


# -------------------------------------------------------------- replay steps
def fixture_to_script(
    fixture: Fixture,
    *,
    session_id: str = "sess_replay",
    synthetic_audio_ms: int = 0,
) -> list[Step]:
    """A fixture, mechanically, as a ``FakeRealtimeServer`` script.

    One :class:`Step` per owner turn, each triggered by the
    ``input_audio_buffer.append`` the lane emits from ``send_audio``. The frame
    order inside a turn is the provider's own: VAD markers, the owner's
    transcript, any function-call proposals, then the reply transcript and
    ``response.done`` with that turn's usage.

    Tool-call turns carry NO reply transcript frames when the model proposed a
    call and said nothing — reproducing that faithfully is how the R1 refusal
    stub gets exercised by real captured shapes rather than by an invented one.
    """

    script: list[Step] = [Step("session.update", (session_created(session_id),), label="handshake")]
    for turn in fixture.turns:
        frames: list[Mapping[str, Any]] = [
            speech_started(0),
            speech_stopped(max(1, len(turn.owner_text)) * 40),
            input_transcript(turn.owner_item_id, turn.owner_text),
        ]
        for call in turn.tool_calls:
            frames.append(function_call(call.call_id, call.name, call.arguments))
        if turn.robot_text:
            if synthetic_audio_ms > 0:
                frames.append(
                    audio_delta(
                        turn.response_id,
                        turn.robot_item_id,
                        pcm_tone(synthetic_audio_ms, seed=turn.index + 1),
                    )
                )
            frames.append(transcript_delta(turn.response_id, turn.robot_item_id, turn.robot_text))
            frames.append(transcript_done(turn.response_id, turn.robot_item_id, turn.robot_text))
            if synthetic_audio_ms > 0:
                frames.append(audio_done(turn.response_id, turn.robot_item_id))
        frames.append(
            response_done(
                turn.response_id,
                input_tokens=turn.usage["input_tokens"],
                output_tokens=turn.usage["output_tokens"],
                input_audio_tokens=turn.usage["input_audio_tokens"],
                output_audio_tokens=turn.usage["output_audio_tokens"],
                cached_tokens=turn.usage["cached_tokens"],
            )
        )
        script.append(
            Step(
                "input_audio_buffer.append",
                tuple(frames),
                label=f"{fixture.thread_id}:turn{turn.index}",
            )
        )
    return script


def sum_usage(fixtures: Sequence[Fixture]) -> dict[str, int]:
    """Corpus-wide billed units. Zero everywhere while the scrape is blocked."""

    totals = dict.fromkeys(USAGE_KEYS, 0)
    for fixture in fixtures:
        for key in USAGE_KEYS:
            totals[key] += int(fixture.usage_totals.get(key, 0))
    return totals


__all__ = [
    "DECLARED_TOOLS",
    "DI_VERSION",
    "FAMILIES",
    "FIXTURES_DIR",
    "FIXTURE_SOURCES",
    "FIXTURE_SOURCE_SCRAPE",
    "FIXTURE_SOURCE_SEED",
    "MANIFEST_PATH",
    "MAX_TURNS",
    "MIN_TURNS",
    "OWNER_VERBATIM",
    "PACK_ROOT",
    "PROBES",
    "REPO_ROOT",
    "SCENARIOS_PATH",
    "SCHEMA_VERSION",
    "SCRAPE_MODEL",
    "SI_VERSION",
    "SUITE_ID",
    "USAGE_KEYS",
    "CorpusError",
    "Fixture",
    "Scenario",
    "ToolCall",
    "Turn",
    "fixture_from_mapping",
    "fixture_to_script",
    "load_fixture",
    "load_fixtures",
    "load_scenarios",
    "scenario_from_mapping",
    "sha256_bytes",
    "sha256_file",
    "sum_usage",
    "verify_prompt_plane",
]
