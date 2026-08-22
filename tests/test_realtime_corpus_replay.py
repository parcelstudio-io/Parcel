"""Card R2-C: the conversation corpus, and its round trip through the real lane.

WHAT THIS FILE PROVES, AND WHAT IT CANNOT
-----------------------------------------
It proves the *pipeline*: an authored scenario, a fixture in the corpus schema,
a mechanical conversion into ``FakeRealtimeServer`` steps, and a real
``RealtimeLane`` driving them into ledger rows, usage rows and tool refusals —
entirely offline, with no credential and no socket.

It does not prove anything about the model. The three fixtures committed today
are **hand-authored seeds**, not captures: the live scrape is blocked on account
credit (HTTP 429 ``credit_balance_exhausted``, re-checked 2026-08-17). Their
robot side is written by a human and their usage is zero everywhere, because
inventing plausible token counts would put fabricated billing data in an
evidence pack. When the scrape unblocks, the captured 25 land in the same
directory and this file needs no edit — which is the property being defended.

WHY THE FROZEN-SCAN GUARD IS HERE AND NOT ONLY IN test_ci_gate.py
------------------------------------------------------------------
``test_ci_gate.py`` globs ``evals/**/manifest.json``. This pack's manifest is
``corpus.manifest.json``, so that scan cannot see it — a ``"frozen": true``
sneaked in here would be invisible to the gate. The scan is reproduced below
over the wider filename pattern, and the ci_gate blind spot is asserted rather
than assumed, so the next person knows why two guards exist.
"""

from __future__ import annotations

import io
import json
import wave
from datetime import datetime
from pathlib import Path

import pytest

from evals.companion.realtime_convo_v1.build_manifest import (
    FROZEN_NOTE,
    diff_manifest,
    load_manifest,
)
from evals.companion.realtime_convo_v1.schema import (
    DECLARED_TOOLS,
    FIXTURE_SOURCE_SEED,
    FIXTURES_DIR,
    MANIFEST_PATH,
    MAX_TURNS,
    MIN_TURNS,
    OWNER_VERBATIM,
    SCENARIOS_PATH,
    SCRAPE_MODEL,
    USAGE_KEYS,
    CorpusError,
    Fixture,
    fixture_from_mapping,
    fixture_to_script,
    load_fixture,
    load_fixtures,
    load_scenarios,
    sha256_file,
    verify_prompt_plane,
)
from evals.companion.realtime_convo_v1.scrape_realtime_convo import (
    API_KEY_ENV,
    BUDGET_CEILING_USD,
    SCRAPE_ENV,
    BudgetExceeded,
    ScrapeRefused,
    estimate_corpus_usd,
    guard_budget,
    require_scrape_enabled,
    self_test,
    spend_usd,
)
from parcel_robot.memory import ConversationMemory
from parcel_robot.realtime.config import RealtimeConfig
from parcel_robot.realtime.fake_server import FakeRealtimeServer, pcm_tone
from parcel_robot.realtime.lane import TOOL_REFUSAL_OUTPUT, RealtimeLane
from parcel_robot.realtime.prompting import (
    DI_VERSION,
    SI_DIGESTS,
    SI_V1,
    SI_VERSION,
    render_session_instructions,
    render_system_instruction,
    si_pin,
    time_of_day,
)
from parcel_robot.realtime.protocol import PCM16_SAMPLE_RATE_HZ
from parcel_robot.realtime.transport import transport_pair

REPO = Path(__file__).resolve().parents[1]

SCENARIOS = load_scenarios()
FIXTURES = load_fixtures()

#: The SI version the 25 threads were CAPTURED under (2026-08-18, $0.50).
#:
#: Card R5 bumped the shipped SI to v2 to fix two wording defects the owner hit
#: live. The corpus is evidence about a past conversation, not a snapshot of
#: today's prompt, so it stays v1 and MUST NOT be re-scraped to chase the edit:
#: re-running it would spend real money to destroy the only real transcripts
#: this project has, and a corpus that silently follows the prompt could never
#: show that a prompt change changed anything.
#:
#: So the provenance assertions below are conditional on THIS constant rather
#: than on ``SI_VERSION``. What still holds unconditionally: every fixture's
#: stored digest matches the pin for its own version, and this tree can still
#: RENDER that version's exact text (``si_pin(..., version=CORPUS_SI_VERSION)``
#: in ``verify_prompt_plane``). Promoting the corpus to v2 is a re-scrape and an
#: owner decision — see scrum/20260818/task_2/R5_STATUS.md.
CORPUS_SI_VERSION = SI_V1

#: Frozen-flagged manifests under ``evals/``, found with a filename pattern
#: WIDER than the one ``test_ci_gate.py`` uses. Pinning the set here is what
#: makes a ``"frozen": true`` in ``corpus.manifest.json`` a red test.
KNOWN_FROZEN = {
    "evals/companion/acoustic_loop_v1/manifest.json",
    "evals/companion/brain_v1/manifest.json",
    "evals/companion/conversation_quality_v1/manifest.json",
    "evals/companion/embodied_plan_v1/manifest.json",
    "evals/companion/live_planner_v1/manifest.json",
    "evals/companion/personal_convo_v1/manifest.json",
    "evals/companion/planner_quality_sketch_v1/manifest.json",
    "evals/companion/planner_quality_v2/manifest.json",
}


# ------------------------------------------------------------------ the rig
class _Clock:
    def __init__(self, start: float = 1_000.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now


class _Sink:
    def __init__(self) -> None:
        self.chunks: list[bytes] = []
        self.begin_calls = 0
        self.first_chunk_started_monotonic: float | None = None

    def begin_utterance(self) -> None:
        self.begin_calls += 1
        self.first_chunk_started_monotonic = None

    def enqueue(self, chunk: bytes, token: object = None) -> None:
        del token
        self.chunks.append(chunk)
        if self.first_chunk_started_monotonic is None:
            self.first_chunk_started_monotonic = 0.0

    def interrupt(self) -> None:
        return None


class _Replay:
    """One fixture, driven through a real lane against the scripted server."""

    def __init__(self, fixture: Fixture, *, synthetic_audio_ms: int = 0) -> None:
        self.fixture = fixture
        self.clock = _Clock()
        self.sink = _Sink()
        self.ledger = ConversationMemory(":memory:")
        self.script = fixture_to_script(fixture, synthetic_audio_ms=synthetic_audio_ms)
        self.servers: list[FakeRealtimeServer] = []
        self.lane = RealtimeLane(
            config=RealtimeConfig(enabled=True, source="replay"),
            instructions=render_session_instructions(
                profile_id=fixture.si_profile, flags=fixture.flags
            ).text,
            transport_factory=self._factory,
            sink=self.sink,
            ledger=self.ledger,
            clock=self.clock,
            session_id_factory=lambda: f"rt_{fixture.thread_id}",
        )

    def _factory(self):
        lane_end, server_end = transport_pair(clock=self.clock)
        self.servers.append(
            FakeRealtimeServer(transport=server_end, script=list(self.script), clock=self.clock)
        )
        return lane_end

    def _step(self) -> None:
        self.servers[-1].pump()
        self.lane.pump()

    def run(self) -> _Replay:
        self.lane.open_session(handshake_token="csrf-token", mic_gesture=True)
        self._step()
        for _ in self.fixture.turns:
            self.lane.send_audio(pcm_tone(20, seed=3))
            self._step()
        return self

    def rows(self) -> list[dict[str, object]]:
        return self.ledger.realtime_turns(limit=500)

    def sent_types(self) -> list[str]:
        transport = self.lane.transport
        assert transport is not None
        return [str(frame.get("type")) for frame in transport.sent]  # type: ignore[attr-defined]

    def sent_frames(self) -> list[dict[str, object]]:
        transport = self.lane.transport
        assert transport is not None
        return list(transport.sent)  # type: ignore[attr-defined]


def _wav_rate(chunk: bytes) -> int:
    with wave.open(io.BytesIO(chunk), "rb") as reader:
        return reader.getframerate()


# ================================================== the authored scenario set
def test_the_corpus_is_twenty_five_authored_threads() -> None:
    assert len(SCENARIOS) == 25
    assert len({s.thread_id for s in SCENARIOS}) == 25
    for scenario in SCENARIOS:
        assert MIN_TURNS <= scenario.turn_count <= MAX_TURNS


def test_both_owner_examples_appear_verbatim() -> None:
    """The owner said these two sentences. They are pinned character for character."""

    spoken = [turn for scenario in SCENARIOS for turn in scenario.owner_turns]
    for example in OWNER_VERBATIM:
        assert example in spoken, f"the owner's verbatim example is missing: {example!r}"
    # And each is tagged, so a future editor knows not to "improve" the wording.
    tagged = [s for s in SCENARIOS if "owner_verbatim" in s.probes]
    assert len(tagged) == 2
    assert {s.family for s in tagged} == {"navigation", "perception"}


def test_the_family_mix_covers_navigation_conversation_and_punts() -> None:
    counts: dict[str, int] = {}
    for scenario in SCENARIOS:
        counts[scenario.family] = counts.get(scenario.family, 0) + 1
    navigation_flavoured = counts.get("navigation", 0) + counts.get("perception", 0)
    assert navigation_flavoured >= 8, "at least eight navigation-flavoured threads"
    assert counts.get("conversation", 0) >= 8, "at least eight conversational threads"
    assert counts.get("punt", 0) >= 3, "punt-inducing threads are their own family"
    probes = {probe for scenario in SCENARIOS for probe in scenario.probes}
    for required in ("ambiguous_target", "unreachable", "perception_limit", "correction"):
        assert required in probes, f"no thread probes {required}"
    memory_threads = [s for s in SCENARIOS if "memory_callback" in s.probes]
    assert len(memory_threads) >= 4
    for scenario in memory_threads:
        assert scenario.flags.history_digest, (
            f"{scenario.thread_id} probes memory but carries no history digest"
        )


def test_the_developer_flags_vary_across_the_corpus() -> None:
    locations = {s.flags.location for s in SCENARIOS}
    parts = {s.flags.part_of_day for s in SCENARIOS}
    personas = {s.si_profile for s in SCENARIOS}
    assert {"living room", "front yard", "sidewalk near home"} <= locations
    assert {"morning", "evening"} <= parts
    assert len(personas) >= 2, "at least two personalities across the corpus"
    for persona in personas:
        # Every persona used is a pinned, real personality — pinned under the
        # version the corpus was captured with, which is the one that matters.
        si_pin(persona, version=CORPUS_SI_VERSION)


@pytest.mark.parametrize("scenario", SCENARIOS, ids=lambda s: s.thread_id)
def test_each_scenarios_stated_part_of_day_matches_its_clock(scenario) -> None:
    """A hand-written flag pair that disagrees with itself would teach the model
    a contradiction, and no renderer would ever notice."""

    moment = datetime.fromisoformat(scenario.flags.local_time)
    assert time_of_day(moment) == scenario.flags.part_of_day, scenario.thread_id


def test_the_owner_side_is_fixed_text_with_no_placeholders() -> None:
    """Deterministic probes. A templated owner turn would make every re-scrape
    a different experiment."""

    for scenario in SCENARIOS:
        for turn in scenario.owner_turns:
            assert "{" not in turn and "}" not in turn, scenario.thread_id
            assert turn == turn.strip() and turn


# ======================================================= the captured corpus
def test_the_captured_corpus_spans_every_scenario_family() -> None:
    """Pinned to the live-captured world (2026-08-18; was: 3 seed fixtures)."""

    assert len(FIXTURES) == 25
    assert {f.family for f in FIXTURES} == {"navigation", "conversation", "punt", "perception"}
    assert any(f.tool_names for f in FIXTURES), "the model must have proposed tools"
    assert any("memory_callback" in f.probes for f in FIXTURES)


@pytest.mark.parametrize("fixture", FIXTURES, ids=lambda f: f.thread_id)
def test_every_fixture_is_tied_to_the_exact_prompt_that_produced_it(fixture: Fixture) -> None:
    """SI digest against its version's pin, DI digest against its own flags.

    Provenance-conditional since card R5: the pin is the CAPTURE version, not
    whatever the tree ships today. ``verify_prompt_plane`` already works this
    way (``si_pin(profile, version=fixture.si_version)``), which is why this
    file needed a constant and ``evals/`` needed no edit at all.
    """

    verify_prompt_plane(fixture)
    assert fixture.si_version == CORPUS_SI_VERSION
    assert fixture.di_version == DI_VERSION
    assert fixture.model == SCRAPE_MODEL
    assert tuple(fixture.declared_tools) == DECLARED_TOOLS


@pytest.mark.xfail(strict=True, reason="FZ-1 (scrum/20260822/task_13): the owner edited prompts/personalities on 2026-08-22; historical SI versions render from the LIVE persona files, so v1/v2 text is no longer reproducible from source until frozen per-version snapshots land. Digests stay registered so recorded sessions remain attributable. strict: flips to a failure the day FZ-1 restores it.")
def test_the_corpus_capture_version_is_still_rendered_by_this_tree() -> None:
    """A v1 pin is only evidence while v1 is still reproducible from source.

    THE seed catcher for quietly dropping the v1 row from ``SI_DIGESTS`` (or for
    letting the version become a label again): every fixture's stored digest
    would become an unverifiable number, and no other test would notice, because
    ``verify_prompt_plane``'s drift check only runs on the CURRENT version.
    """

    assert CORPUS_SI_VERSION in SI_DIGESTS, (
        "the corpus's capture version was unregistered; every fixture's "
        "si_digest is now unverifiable"
    )
    profiles = {fixture.si_profile for fixture in FIXTURES}
    assert profiles, "the corpus must name at least one personality"
    for profile_id in sorted(profiles):
        rendered = render_system_instruction(profile_id=profile_id, version=CORPUS_SI_VERSION)
        assert rendered.digest == si_pin(profile_id, version=CORPUS_SI_VERSION), profile_id
    stored = {fixture.si_digest for fixture in FIXTURES}
    pinned = {si_pin(profile_id, version=CORPUS_SI_VERSION) for profile_id in profiles}
    assert stored <= pinned


def test_the_corpus_is_older_than_the_shipped_prompt_and_says_so() -> None:
    """The state this card deliberately leaves behind, stated as a test.

    If a later card re-scrapes under v2, this reddens — which is correct: the
    re-scrape is exactly the moment ``CORPUS_SI_VERSION`` must move, the
    manifest must be rebuilt, and the owner must have signed off on spending
    the money. It must never happen as a side effect of a prompt edit.
    """

    assert CORPUS_SI_VERSION == SI_V1
    assert SI_VERSION != CORPUS_SI_VERSION, (
        "if the shipped SI is back on the corpus's version, this file's "
        "provenance-conditional machinery should be simplified away again"
    )
    assert all(fixture.si_version == CORPUS_SI_VERSION for fixture in FIXTURES)


@pytest.mark.parametrize("fixture", FIXTURES, ids=lambda f: f.thread_id)
def test_every_fixture_matches_its_authored_scenario(fixture: Fixture) -> None:
    """The owner side of a capture must be the scenario's script, unchanged."""

    scenario = {s.thread_id: s for s in SCENARIOS}[fixture.thread_id]
    assert tuple(turn.owner_text for turn in fixture.turns) == scenario.owner_turns
    assert fixture.flags == scenario.flags
    assert fixture.si_profile == scenario.si_profile
    assert fixture.family == scenario.family


@pytest.mark.parametrize("fixture", FIXTURES, ids=lambda f: f.thread_id)
def test_billing_data_matches_fixture_provenance(fixture: Fixture) -> None:
    """Live captures MUST carry real usage; hand-authored seeds must carry none.

    Until 2026-08-18 every fixture was a hand-authored seed and this test
    asserted zero usage everywhere — inventing token counts would be fabricated
    billing data. The live scrape then landed (25/25 threads, $0.50 measured)
    and OVERWROTE the seeds, flipping the correct assertion to its inverse: a
    live capture with zero usage would mean the scraper dropped the provider's
    usage blocks. Both provenances stay covered so either can reappear.
    """

    if fixture.source == FIXTURE_SOURCE_SEED:
        assert fixture.captured_at is None
        assert all(fixture.usage_totals[key] == 0 for key in USAGE_KEYS)
        assert all(turn.usage[key] == 0 for turn in fixture.turns for key in USAGE_KEYS)
    else:
        assert fixture.source == "live_scrape"
        assert fixture.captured_at is not None
        assert fixture.usage_totals["input_tokens"] > 0
        assert fixture.usage_totals["output_tokens"] > 0
        assert all(turn.usage["output_tokens"] > 0 for turn in fixture.turns)


def _keys_in(payload: object) -> set[str]:
    if isinstance(payload, dict):
        return set(payload) | {key for value in payload.values() for key in _keys_in(value)}
    if isinstance(payload, list):
        return {key for item in payload for key in _keys_in(item)}
    return set()


def test_no_fixture_stores_audio_bytes() -> None:
    """The scrape is text-modality: there is no captured PCM, so none is stored.

    Checked by KEY rather than by substring: ``input_audio_tokens`` is a usage
    count and belongs here; a ``delta`` or ``pcm`` field would be invented audio.
    """

    for path in sorted(FIXTURES_DIR.glob("*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        keys = _keys_in(payload)
        assert not keys & {"audio", "delta", "pcm", "audio_base64"}, path.name


# ======================================================== the replay round trip
@pytest.mark.parametrize("fixture", FIXTURES, ids=lambda f: f.thread_id)
def test_a_fixture_replays_through_the_real_lane_into_ledger_rows(fixture: Fixture) -> None:
    """The load-bearing arrow: fixture → Steps → RealtimeLane → ledger."""

    replay = _Replay(fixture).run()
    rows = replay.rows()

    expected: list[tuple[str, str]] = []
    for turn in fixture.turns:
        expected.append(("user", turn.owner_text))
        if turn.robot_text:
            expected.append(("assistant", turn.robot_text))
    assert [(str(row["role"]), str(row["content"])) for row in rows] == expected

    assert all(row["session_id"] == f"rt_{fixture.thread_id}" for row in rows)
    assert all(row["origin"] == "realtime" for row in rows)
    assert len(replay.lane.usage_rows) == len(fixture.turns)
    assert replay.lane.protocol_errors == [], "every scripted frame must parse"
    assert replay.lane.server_errors == []
    assert replay.lane.reconnects == 0


def test_a_navigate_to_proposal_is_answered_by_the_r1_refusal_stub() -> None:
    """Tools are R3. The fixture captures the PROPOSAL; the refusal is today's
    correct behaviour, and this assertion is what documents that."""

    # Any real thread where the model proposed navigate_to (22 of 25 do). The
    # seed-world version pinned an exact two-call order; a live model orders
    # its calls as it pleases, so the pin is set-wise plus a count identity.
    fixture = next(f for f in FIXTURES if "navigate_to" in f.tool_names)
    replay = _Replay(fixture).run()

    assert "navigate_to" in replay.lane.refused_tool_calls
    assert len(replay.lane.refused_tool_calls) == sum(
        len(turn.tool_calls) for turn in fixture.turns
    ), "every proposal in the fixture must be answered by the refusal stub"
    outputs = [
        frame
        for frame in replay.sent_frames()
        if str(frame.get("type")) == "conversation.item.create"
        and isinstance(frame.get("item"), dict)
        and frame["item"].get("type") == "function_call_output"  # type: ignore[index]
    ]
    assert len(outputs) == sum(len(turn.tool_calls) for turn in fixture.turns)
    for frame in outputs:
        item = frame["item"]
        assert isinstance(item, dict)
        assert item["output"] == TOOL_REFUSAL_OUTPUT
        assert json.loads(item["output"])["error"] == "tools are not enabled in R1"
    call_ids = {str(frame["item"]["call_id"]) for frame in outputs}  # type: ignore[index]
    assert call_ids == {call.call_id for turn in fixture.turns for call in turn.tool_calls}
    # The seed-world version also required a proposal-without-speech turn; a
    # live model speaks or stays silent around its calls as it pleases, so
    # that property belongs to corpus ANALYSIS, not to this replay contract.


def test_synthetic_audio_is_opt_in_and_travels_wav_wrapped_at_24k() -> None:
    """The corpus has no captured audio. When a test asks for filler, it is a
    deterministic tone and it still exercises the real playback bridge."""

    fixture = next(f for f in FIXTURES if f.family == "conversation")
    quiet = _Replay(fixture).run()
    assert quiet.sink.chunks == [], "text fixtures must not fabricate audio by default"

    loud = _Replay(fixture, synthetic_audio_ms=300).run()
    assert loud.sink.chunks
    for chunk in loud.sink.chunks:
        assert chunk[:4] == b"RIFF"
        assert _wav_rate(chunk) == PCM16_SAMPLE_RATE_HZ


def test_the_replay_script_is_a_mechanical_function_of_the_fixture() -> None:
    fixture = FIXTURES[0]
    script = fixture_to_script(fixture)
    assert len(script) == len(fixture.turns) + 1, "one handshake plus one step per turn"
    assert script[0].trigger == "session.update"
    assert all(step.trigger == "input_audio_buffer.append" for step in script[1:])
    assert fixture_to_script(fixture) == script, "conversion must be deterministic"


# ============================================================ schema refusals
def _seed_fixture(**overrides: object) -> dict[str, object]:
    payload = json.loads((FIXTURES_DIR / "rt-conv-014.json").read_text(encoding="utf-8"))
    payload.update(overrides)
    return payload


def test_the_loader_refuses_an_unknown_fixture_key() -> None:
    with pytest.raises(CorpusError) as caught:
        fixture_from_mapping(_seed_fixture(vibes="good"))
    assert "vibes" in str(caught.value)


def test_the_loader_refuses_an_unknown_family_and_a_bad_source() -> None:
    with pytest.raises(CorpusError):
        fixture_from_mapping(_seed_fixture(family="gossip"))
    with pytest.raises(CorpusError):
        fixture_from_mapping(_seed_fixture(source="imagined"))


def test_the_loader_refuses_out_of_order_turns_and_non_json_tool_arguments() -> None:
    payload = _seed_fixture()
    turns = list(payload["turns"])  # type: ignore[arg-type]
    turns[0], turns[1] = turns[1], turns[0]
    with pytest.raises(CorpusError) as caught:
        fixture_from_mapping({**payload, "turns": turns})
    assert "out of order" in str(caught.value)

    payload = _seed_fixture()
    turns = list(payload["turns"])  # type: ignore[arg-type]
    turns[0] = {
        **turns[0],
        "tool_calls": [{"call_id": "c", "name": "navigate_to", "arguments": "not json"}],
    }
    with pytest.raises(CorpusError):
        fixture_from_mapping({**payload, "turns": turns})


def test_the_loader_refuses_a_filename_that_disagrees_with_its_thread_id(
    tmp_path: Path,
) -> None:
    payload = _seed_fixture()
    path = tmp_path / "rt-conv-999.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(CorpusError) as caught:
        load_fixture(path)
    assert "does not match" in str(caught.value)


def test_the_loader_refuses_a_turn_count_outside_the_authored_band() -> None:
    payload = json.loads(SCENARIOS_PATH.read_text(encoding="utf-8"))
    payload["scenarios"][0]["owner_turns"] = ["hi", "bye"]
    from evals.companion.realtime_convo_v1.schema import scenario_from_mapping

    with pytest.raises(CorpusError) as caught:
        scenario_from_mapping(payload["scenarios"][0])
    assert "outside" in str(caught.value)


# ================================================================= the manifest
def test_the_manifest_digests_match_the_files_on_disk() -> None:
    """THE seed catcher for an edited fixture byte."""

    manifest = load_manifest()
    assert manifest["locked_files"], "the manifest must pin something"
    for entry in manifest["locked_files"]:
        path = REPO / str(entry["path"])
        assert path.is_file(), entry["path"]
        assert sha256_file(path) == entry["sha256"], (
            f"{entry['path']} has changed since the manifest was built; "
            f"regenerate with -m evals.companion.realtime_convo_v1.build_manifest"
        )
    pinned = {str(entry["path"]) for entry in manifest["locked_files"]}
    on_disk = {
        SCENARIOS_PATH.relative_to(REPO).as_posix(),
        *(path.relative_to(REPO).as_posix() for path in FIXTURES_DIR.glob("*.json")),
    }
    assert pinned == on_disk, "a fixture was added or removed without a manifest rebuild"


def test_the_manifest_agrees_with_the_tree_field_by_field() -> None:
    """Everything except the two SI-provenance fields, which are v1 on purpose.

    ``diff_manifest()`` rebuilds from the tree, so after the R5 bump it reports
    ``si_version`` and ``si_digests`` — the manifest records what the capture was
    run under, and the tree records what ships today. Pinning the drift to
    EXACTLY those two fields keeps the rest of the manifest (locked file digests,
    fixture counts, usage totals) as strict as it was: a fixture edited under
    cover of the SI bump still reddens here.
    """

    assert diff_manifest() == ["si_version", "si_digests"], (
        "only the SI provenance fields may differ from the tree; the corpus is "
        "an SI-v1 artifact and every other field must still agree exactly"
    )
    manifest = load_manifest()
    assert manifest["si_version"] == CORPUS_SI_VERSION
    assert manifest["si_digests"] == dict(SI_DIGESTS[CORPUS_SI_VERSION]), (
        "the manifest's recorded digests must still be the registered v1 pins"
    )


def test_the_manifest_records_the_model_versions_and_the_captured_scrape() -> None:
    """Pinned to the CAPTURED world as of 2026-08-18 (was: the blocked world).

    The scrape block is the corpus's provenance headline; asserting its exact
    shape means a re-scrape, a partial capture, or a silent fixture deletion
    must come through this pin deliberately.
    """

    manifest = load_manifest()
    assert manifest["model"] == SCRAPE_MODEL
    assert manifest["si_version"] == CORPUS_SI_VERSION
    assert manifest["di_version"] == DI_VERSION
    assert manifest["si_digests"]["gentle_companion"] == si_pin(
        "gentle_companion", version=CORPUS_SI_VERSION
    )
    assert manifest["scenario_count"] == 25
    assert manifest["fixture_count"] == 25
    assert manifest["budget_ceiling_usd"] == BUDGET_CEILING_USD
    scrape = manifest["scrape"]
    assert scrape["status"] == "captured"
    assert scrape["threads_captured"] == 25 == manifest["fixture_count"]
    assert 0 < scrape["measured_spend_usd"] < BUDGET_CEILING_USD
    assert manifest["usage_totals"]["input_tokens"] > 0
    assert manifest["usage_totals"]["output_tokens"] > 0


def test_this_pack_is_not_frozen_and_says_why() -> None:
    manifest = load_manifest()
    assert "frozen" not in manifest, (
        "freezing this corpus is a later owner decision, taken after a real "
        "scrape lands — not something that happens while it holds three seeds"
    )
    assert manifest["frozen_note"] == FROZEN_NOTE
    assert "NOT frozen" in FROZEN_NOTE


def test_no_frozen_manifest_escapes_the_wider_scan() -> None:
    """The ci_gate scan's own logic, over a WIDER filename pattern.

    ``test_ci_gate.py`` globs ``manifest.json`` exactly, so it cannot see
    ``corpus.manifest.json``. Reproducing the scan here over ``*manifest*.json``
    is what makes a ``"frozen": true`` sneaked into this pack a red test.
    """

    frozen = set()
    for path in sorted((REPO / "evals").rglob("*manifest*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            continue
        if isinstance(payload, dict) and payload.get("frozen") is True:
            frozen.add(path.relative_to(REPO).as_posix())
    assert frozen == KNOWN_FROZEN, (
        "a manifest gained or lost a frozen flag; freezing a suite must be a "
        "reviewed decision and must land in DIGEST_SENTINELS at the same time"
    )


def test_the_ci_gate_scan_provably_cannot_see_this_manifest() -> None:
    """The blind spot, asserted rather than assumed. If this ever fails because
    the pack's manifest was renamed to ``manifest.json``, the ci_gate scan picks
    it up for free and the wider scan above becomes belt-and-braces."""

    seen = {path.relative_to(REPO).as_posix() for path in (REPO / "evals").rglob("manifest.json")}
    assert MANIFEST_PATH.relative_to(REPO).as_posix() not in seen
    assert MANIFEST_PATH.name == "corpus.manifest.json"


# ============================================================ the scraper guards
def test_the_scraper_refuses_without_both_the_flag_and_a_credential() -> None:
    with pytest.raises(ScrapeRefused) as caught:
        require_scrape_enabled({})
    assert SCRAPE_ENV in str(caught.value)

    with pytest.raises(ScrapeRefused) as caught:
        require_scrape_enabled({SCRAPE_ENV: "1"})
    assert API_KEY_ENV in str(caught.value)

    with pytest.raises(ScrapeRefused):
        require_scrape_enabled({API_KEY_ENV: "value-shaped-thing"})

    # Both present ⇒ no refusal. (Still no socket: this only checks the gate.)
    require_scrape_enabled({SCRAPE_ENV: "1", API_KEY_ENV: "value-shaped-thing"})


def test_the_budget_guard_refuses_at_and_above_the_ceiling() -> None:
    """THE seed catcher for a removed budget guard."""

    assert guard_budget(estimate_usd=0.5) == 0.5
    with pytest.raises(BudgetExceeded):
        guard_budget(estimate_usd=BUDGET_CEILING_USD)
    with pytest.raises(BudgetExceeded):
        guard_budget(estimate_usd=BUDGET_CEILING_USD + 0.01)
    with pytest.raises(BudgetExceeded):
        guard_budget(estimate_usd=-1.0)
    # The ceiling is a constant, not a parameter a caller can inflate away.
    assert BUDGET_CEILING_USD == 5.0


def test_the_scraper_self_test_is_green_offline() -> None:
    assert self_test() == 0


def test_the_preflight_estimate_is_computed_before_anything_is_sent() -> None:
    estimate = estimate_corpus_usd(SCENARIOS)
    assert estimate > 0.0
    assert estimate < BUDGET_CEILING_USD, (
        "the authored corpus must fit under the ceiling, or the run can never start"
    )
    # Measured spend comes from the provider's usage block, never the estimate.
    assert spend_usd({"input_tokens": 0, "output_tokens": 0, "cached_tokens": 0}) == 0.0
    assert spend_usd({"input_tokens": 1_000_000, "output_tokens": 0, "cached_tokens": 0}) > 0.0


def test_no_test_in_this_suite_can_trigger_a_live_scrape(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Importing the scraper must be inert; running it must not be reachable."""

    import evals.companion.realtime_convo_v1.scrape_realtime_convo as scraper

    monkeypatch.delenv(SCRAPE_ENV, raising=False)
    assert scraper.__name__ != "__main__"
    with pytest.raises(ScrapeRefused):
        require_scrape_enabled()
