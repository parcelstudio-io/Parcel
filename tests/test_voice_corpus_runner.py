"""Card R17 §2/§3: the UI-mounted corpus runner, driven with no stack at all.

WHAT THIS FILE PINS
-------------------
* **The owner's stack is not reachable by accident.** Port 8765 refuses twice
  over — by ``--stack owner`` and by a bare ``--port 8765`` — and the refusal
  lands before a socket, a GET or a cent of spend.
* **E-stop hygiene is structural, not advisory.** An ``estop-pos`` query must
  latch (that is the assertion), the latch is released before the next query,
  and a latch that will not release ABORTS the run. live_run_1 scored fourteen
  queries against a robot that could not move; that cannot happen here.
* **The output path does not depend on the cwd.** The doubled repo-relative
  prefix that misplaced live_run_1's artifacts is a refusal.
* **Scoring is mechanical or it is deferred.** A fabricated mission fails a
  refusal cell; silence fails a prose cell; a judgement about wording returns
  NEEDS_REVIEW instead of an invented PASS.

The stack is a fake here on purpose: every one of those behaviours is the
runner's own logic, and pinning them against a real hosted session would cost
money to learn nothing extra.
"""

from __future__ import annotations

import importlib.util
import io
import json
import sys
import wave
from pathlib import Path
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[1]
MODULE_PATH = REPO / "tools" / "run_voice_corpus.py"


def _load():
    spec = importlib.util.spec_from_file_location("parcel_run_voice_corpus", MODULE_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


rvc = _load()


# ============================================================ fake stack + audio
class FakeAudio:
    """Stands in for the websocket. Records what was spoken, plays nothing back."""

    def __init__(self, client: Any) -> None:
        self.client = client
        self.sample_rate_hz = 24_000
        self.hello = {"type": "hello", "input": {"rate": 24_000}}
        self.spoken: list[int] = []
        self.armed = False
        self.audio_chunks_in = 0
        self.audio_bytes_in = 0
        self.control_frames: list[dict] = []

    def __enter__(self):
        return self

    def __exit__(self, *_exc: object) -> None:
        return None

    def arm_microphone(self, timeout: float = 10.0) -> dict:
        self.armed = True
        return {"type": "mic", "on": True}

    def close_microphone(self) -> None:
        self.armed = False

    def speak(self, pcm: bytes, *, pad_ms: int = 0, realtime: bool = True) -> int:
        assert self.armed, "audio was injected before the microphone gesture"
        self.spoken.append(len(pcm))
        self.client.deliver_turn()
        return len(pcm)

    def pump(self, seconds: float) -> None:
        return None


class FakeStack:
    """A panel whose ``/api/state`` is whatever the current script row says."""

    def __init__(self, script: list[dict[str, Any]]) -> None:
        self.target = rvc.Target(host="127.0.0.1", port=8823)
        self.csrf_token = "fake"
        self.script = script
        self.turn = -1
        self.chat: list[dict] = []
        self.events: list[dict] = []
        self.missions: list[dict] = []
        self.brokered: list[str] = []
        self.spend = 0.0
        self.latched = False
        self.release_works = True
        self.posts: list[tuple[str, dict]] = []
        self.injections = 0

    # ------------------------------------------------------------ StackClient
    def state(self) -> dict[str, Any]:
        return {
            "chat": list(self.chat),
            "events": list(self.events),
            "mission_log": list(self.missions),
            "emergency_stopped": self.latched,
            "realtime": {
                "mode": "audio",
                "spend_usd": self.spend,
                "lane": {"brokered_tool_calls": list(self.brokered)},
            },
        }

    def post(self, path: str, payload: dict) -> dict:
        self.posts.append((path, payload))
        if payload.get("action") == "clear_emergency_stop" and self.release_works:
            self.latched = False
        return {"message": "ok"}

    # ---------------------------------------------------------------- scripted
    def deliver_turn(self) -> None:
        self.injections += 1
        self.turn += 1
        row = self.script[min(self.turn, len(self.script) - 1)]
        for text in row.get("heard", []):
            self.chat.append({"role": "user", "text": text})
        for text in row.get("said", []):
            self.chat.append({"role": "assistant", "text": text})
        for tool in row.get("tools", []):
            self.events.append({"id": len(self.events), "role": "realtime", "text": tool})
        for mission in row.get("missions", []):
            self.missions.append(mission)
        self.brokered.extend(row.get("brokered", []))
        if row.get("latch"):
            self.latched = True
        self.spend += float(row.get("spend", 0.01))


def _wav(path: Path, seconds: float = 0.05, rate: int = 16_000) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        handle.writeframes(b"\x01\x00" * int(rate * seconds))
    return path


def _corpus(tmp_path: Path, rows: list[tuple[str, str, str, str]]) -> Path:
    directory = tmp_path / "corpus"
    directory.mkdir(parents=True, exist_ok=True)
    lines = ["id\tcategory\tquery\texpected"]
    for row in rows:
        lines.append("\t".join(row))
        _wav(directory / f"{row[0]}_{row[1]}.wav")
    (directory / "queries.tsv").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return directory


def _runner(tmp_path: Path, stack: FakeStack, corpus: Path, **options) -> Any:
    queries = rvc.attach_audio(rvc.load_corpus(corpus / "queries.tsv"), corpus)
    settings = rvc.RunnerOptions(
        pace_s=0.0, quiet_s=0.0, turn_timeout_s=2.0, mission_settle_s=0.2,
        poll_s=0.01, pad_ms=0, release_timeout_s=0.2, **options
    )
    return rvc.CorpusRunner(
        client=stack,
        queries=queries,
        options=settings,
        ink=rvc.Ink(enabled=False),
        out=tmp_path / "run_1",
        stream=io.StringIO(),
        audio_factory=FakeAudio,
    )


# ================================================== guard 1: the owner's stack
def test_the_owner_stack_is_refused_unless_asked_for_in_full() -> None:
    """SEED: the runner POSTs to the owner stack without the flag.

    Two doors to the same refusal, because they are different mistakes: naming
    the owner's stack, and typing their port while meaning your own.
    """

    with pytest.raises(rvc.RunnerRefusal, match="owner's stack"):
        rvc.resolve_target(stack="owner", host="127.0.0.1", port=None, i_am_the_owner=False)
    with pytest.raises(rvc.RunnerRefusal, match="owner's stack"):
        rvc.resolve_target(stack="own", host="127.0.0.1", port=8765, i_am_the_owner=False)
    with pytest.raises(rvc.RunnerRefusal, match="owner's stack"):
        rvc.resolve_target(stack="owner", host="127.0.0.1", port=9000, i_am_the_owner=False)

    allowed = rvc.resolve_target(stack="owner", host="127.0.0.1", port=None, i_am_the_owner=True)
    assert allowed.port == rvc.OWNER_PANEL_PORT
    mine = rvc.resolve_target(stack="own", host="127.0.0.1", port=None, i_am_the_owner=False)
    assert mine.port == rvc.DEFAULT_PORT != rvc.OWNER_PANEL_PORT


def test_the_refusal_happens_before_any_request(tmp_path: Path, capsys) -> None:
    """`main` returns the refusal exit code without touching the network."""

    code = rvc.main(
        ["--corpus", str(tmp_path), "--out", str(tmp_path / "run"), "--stack", "owner"]
    )
    assert code == 2
    assert "owner's stack" in capsys.readouterr().err


# ================================================ guard 2: the output path trap
def test_a_doubled_repo_relative_prefix_is_refused(tmp_path: Path) -> None:
    """SEED: live_run_1's artifacts landed under a doubled prefix. Never again."""

    doubled = tmp_path / "evals/20260820/voice_corpus_v1/evals/20260820/voice_corpus_v1/live_run_1"
    with pytest.raises(rvc.RunnerRefusal, match="repeats the segment run"):
        rvc.resolve_out_dir(str(doubled))
    clean = tmp_path / "evals/20260820/voice_corpus_v1/replay_run_1"
    assert rvc.resolve_out_dir(str(clean)) == clean
    clean.mkdir(parents=True)
    with pytest.raises(rvc.RunnerRefusal, match="already exists"):
        rvc.resolve_out_dir(str(clean))


def test_the_output_path_does_not_depend_on_the_cwd(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    assert rvc.resolve_out_dir("run_1") == tmp_path / "run_1"


# ==================================================== guard 3: e-stop hygiene
def test_an_estop_query_latches_is_released_and_the_run_continues(tmp_path: Path) -> None:
    corpus = _corpus(
        tmp_path,
        [
            ("32", "estop-pos", "Die stop.", "EMERGENCY LATCH fires locally, pre-cloud"),
            ("35", "estop-neg", "Let's stop by the store.", "NO latch; conversational handling"),
        ],
    )
    stack = FakeStack(
        [
            {"heard": ["die stop"], "latch": True},
            {"heard": ["let's stop by the store"], "said": ["We can stop by a store."]},
        ]
    )
    runner = _runner(tmp_path, stack, corpus)
    runner.run()

    assert [row["verdict"] for row in runner.results] == ["PASS", "PASS"]
    assert runner.latch_releases == 1
    assert ("/api/action", {"action": "clear_emergency_stop"}) in stack.posts
    assert stack.latched is False
    assert runner.results[0]["latch"]["fired_during_turn"] is True
    assert runner.results[0]["latch"]["released_by_runner"] is True
    # The second query really was spoken, i.e. the run continued after release.
    assert stack.injections == 2


def test_the_run_aborts_rather_than_scoring_a_frozen_robot(tmp_path: Path) -> None:
    """SEED: the runner proceeds past an unreleased latch.

    This is live_run_1's defining failure, made impossible. If the release does
    not take, the remaining queries are NOT spoken and are not scored — they are
    recorded as NOT_ATTEMPTED with the reason, because a verdict produced
    against a robot that cannot move is worse than no verdict.
    """

    corpus = _corpus(
        tmp_path,
        [
            ("32", "estop-pos", "Die stop.", "EMERGENCY LATCH fires locally, pre-cloud"),
            ("03", "nav-direct", "Walk to the bench.", "navigate_to bench; arrival NEAR"),
            ("19", "gesture", "Wave at me.", "play_gesture wave"),
        ],
    )
    stack = FakeStack([{"heard": ["die stop"], "latch": True}])
    stack.release_works = False
    runner = _runner(tmp_path, stack, corpus)
    runner.run()

    assert stack.injections == 1, "a query was spoken into a latched robot"
    assert "did not release" in runner.aborted
    assert runner.results[0]["verdict"] == "PASS"
    assert [row["verdict"] for row in runner.results[1:]] == ["NOT_ATTEMPTED", "NOT_ATTEMPTED"]
    assert all("did not release" in row["notes"] for row in runner.results[1:])


def test_a_latch_engaged_before_the_run_is_cleared_in_pre_flight(tmp_path: Path) -> None:
    """The owner's stack sat latched for 350 s after live_run_1. A run that
    starts there would score everything against a frozen robot."""

    corpus = _corpus(tmp_path, [("19", "gesture", "Wave at me.", "play_gesture wave")])
    stack = FakeStack([{"said": ["Waving!"], "tools": ["tool play_gesture: ok — wave"]}])
    stack.latched = True
    runner = _runner(tmp_path, stack, corpus)
    runner.run()
    assert runner.latch_releases == 1
    assert runner.results[0]["verdict"] == "PASS"


def test_an_estop_query_that_does_not_latch_is_a_fail(tmp_path: Path) -> None:
    corpus = _corpus(
        tmp_path, [("34", "estop-pos", "Dye. Stop.", "ASR-variant probe — SHOULD latch")]
    )
    stack = FakeStack([{"heard": ["dye stop"], "said": ["Sure, what next?"]}])
    runner = _runner(tmp_path, stack, corpus)
    runner.run()
    assert runner.results[0]["verdict"] == "FAIL"
    assert runner.latch_releases == 0


def test_a_false_latch_on_the_negative_set_is_a_fail(tmp_path: Path) -> None:
    corpus = _corpus(
        tmp_path, [("37", "estop-neg", "I love that tie-dye top.", "NO latch — trade phrase")]
    )
    stack = FakeStack([{"heard": ["i love that tie-dye top"], "latch": True}])
    runner = _runner(tmp_path, stack, corpus)
    runner.run()
    assert runner.results[0]["verdict"] == "FAIL"
    assert "FALSE LATCH" in runner.results[0]["notes"]
    assert runner.latch_releases == 1  # and it still cleans up after itself


# ============================================================ mechanical scoring
def _score(expected: str, **observed) -> tuple[str, str]:
    query = rvc.Query(id="01", category="x", query="q", expected=expected)
    observation = rvc.Observation(**observed)
    verdict, _evidence, notes = rvc.score(query, observation, rvc.parse_gold(expected))
    return verdict, notes


def test_a_fabricated_mission_fails_a_refusal_cell() -> None:
    """live_run_1's finding 3: Narnia and the moon became real missions."""

    verdict, notes = _score(
        "structured refusal naming nearest valid places; NO fabricated mission",
        said=["Okay, I'll go wait near narnia safely."],
        missions=[{"kind": "started", "goal": "narnia", "state": "searching"}],
    )
    assert verdict == "FAIL"
    assert "fabricated-mission" in notes


def test_silence_is_a_fail_and_not_a_partial() -> None:
    """live_run_1's finding 2: the dominant defect is not wrong answers, it is
    no answers. A program does not need a human to grade that."""

    assert _score("REGRESSION F3: scene answer from perception")[0] == "FAIL"
    assert _score("navigate_to bench; arrival NEAR")[0] == "FAIL"


def test_a_judgement_about_wording_is_deferred_not_invented() -> None:
    verdict, notes = _score("warm in-character reply", said=["I'm feeling playful today!"])
    assert verdict == "NEEDS_REVIEW"
    assert "judgement" in notes
    assert _score("PROBE (Korean) — record what happens", said=["네"])[0] == "NEEDS_REVIEW"


def test_the_right_tool_for_the_wrong_place_is_partial() -> None:
    verdict, _notes = _score(
        "navigate_to sidewalk; arrival INSIDE region",
        said=["On my way."],
        tools=[{"tool": "navigate_to", "status": "ok", "detail": "mission accepted: grass"}],
        missions=[{"kind": "started", "goal": "grass"}],
    )
    assert verdict == "PARTIAL"

    verdict, _notes = _score(
        "navigate_to sidewalk; arrival INSIDE region",
        said=["On my way."],
        tools=[{"tool": "navigate_to", "status": "ok", "detail": "mission accepted: sidewalk"}],
        missions=[{"kind": "started", "goal": "sidewalk"}],
    )
    assert verdict == "PASS"


def test_talking_about_a_tool_without_calling_it_is_partial() -> None:
    verdict, notes = _score("play_gesture wave", said=["Let me do a quick gesture."])
    assert verdict == "PARTIAL"
    assert "does not do it" in notes


def test_a_latched_rejection_is_blocked_not_failed() -> None:
    verdict, _notes = _score(
        "navigate_to bench; arrival NEAR",
        said=["Heading over."],
        tools=[
            {
                "tool": "navigate_to",
                "status": "rejected",
                "detail": "Motion is disabled by emergency stop",
            }
        ],
        latched_during=True,
    )
    assert verdict == "BLOCKED_BY_LATCH"


# ==================================================== corpus + audio plumbing
def test_a_query_with_no_recording_is_not_attempted_and_costs_nothing(tmp_path: Path) -> None:
    corpus = _corpus(tmp_path, [("01", "nav-direct", "Go to the sidewalk.", "navigate_to sidewalk")])
    (corpus / "01_nav-direct.wav").unlink()
    stack = FakeStack([{"said": ["hi"]}])
    runner = _runner(tmp_path, stack, corpus)
    runner.run()
    assert runner.results[0]["verdict"] == "NOT_ATTEMPTED"
    assert stack.injections == 0


def test_wavs_are_resampled_to_the_rate_the_gateway_negotiated(tmp_path: Path) -> None:
    """record.sh writes 16 kHz; the session speaks 24 kHz. One of them has to move."""

    path = _wav(tmp_path / "clip.wav", seconds=1.0, rate=16_000)
    pcm, seconds, source_hz = rvc.read_wav_as_pcm(path, 24_000)
    assert source_hz == 16_000
    assert seconds == pytest.approx(1.0, abs=0.01)
    assert len(pcm) == pytest.approx(48_000, abs=64)


# ============================================================== the run folder
def test_the_run_folder_is_written_in_the_live_run_shape(tmp_path: Path) -> None:
    corpus = _corpus(
        tmp_path,
        [
            ("03", "nav-direct", "Walk to the bench.", "navigate_to bench; arrival NEAR"),
            ("49", "persona", "How are you feeling?", "warm in-character reply"),
        ],
    )
    stack = FakeStack(
        [
            {
                "heard": ["walk to the bench"],
                "said": ["On my way to the bench."],
                "tools": ["tool navigate_to: ok — mission accepted: bench"],
                "missions": [
                    {"kind": "started", "goal": "bench", "state": "running", "reason": "route"},
                    {"kind": "ended", "goal": "bench", "state": "idle", "reason": "arrived"},
                ],
                "spend": 0.02,
            },
            {"heard": ["how are you feeling"], "said": ["Playful!"], "spend": 0.01},
        ]
    )
    runner = _runner(tmp_path, stack, corpus)
    runner.run()
    rvc.write_run_folder(
        runner, corpus_dir=corpus, tsv=corpus / "queries.tsv",
        state=stack.state(), options=runner.options,
    )

    out = runner.out
    for name in ("results.json", "README.md", "state.json", "session_slices.json"):
        assert (out / name).is_file(), f"{name} missing from the run folder"

    results = json.loads((out / "results.json").read_text(encoding="utf-8"))
    # live_run_1's own top-level keys, so one reader reads both runs.
    for key in (
        "run", "corpus", "scored_at", "scored_by", "session_window", "corpus_queries",
        "queries_attempted", "queries_not_attempted", "raw_audio_persisted",
        "verdict_totals", "category_totals", "results",
    ):
        assert key in results, f"results.json is missing live_run_1's '{key}'"
    assert results["raw_audio_persisted"] is True  # the whole point of the card
    assert results["verdict_totals"] == {"PASS": 1, "NEEDS_REVIEW": 1}
    assert results["costs"]["run_cost_usd"] == pytest.approx(0.03)
    assert results["costs"]["per_query_usd"]["03"] == pytest.approx(0.02)
    assert results["estop_hygiene"]["latched_at_end"] is False
    row = results["results"][0]
    assert row["matched_owner_turn"] == "walk to the bench"
    assert row["wav"] == "03_nav-direct.wav"
    assert any("mission started goal=bench" in line for line in row["evidence"])

    readme = (out / "README.md").read_text(encoding="utf-8")
    assert "Emergency-stop hygiene" in readme
    assert "NEEDS_REVIEW" in readme
    assert '"Walk to the bench."' in readme

    slices = json.loads((out / "session_slices.json").read_text(encoding="utf-8"))
    assert set(slices) == {"mission_log", "events", "chat"}


def test_a_mission_that_never_ends_is_waited_for_then_reported(tmp_path: Path) -> None:
    """live_run_1 could not score arrival because every mission was preempted by
    the next query 4-6 s later. The runner waits, then says what it saw."""

    corpus = _corpus(tmp_path, [("01", "nav-direct", "Go to the sidewalk.", "navigate_to sidewalk")])
    stack = FakeStack(
        [
            {
                "said": ["On my way."],
                "tools": ["tool navigate_to: ok — mission accepted: sidewalk"],
                "missions": [{"kind": "started", "goal": "sidewalk", "state": "searching"}],
            }
        ]
    )
    runner = _runner(tmp_path, stack, corpus)
    runner.run()
    row = runner.results[0]
    assert row["verdict"] == "PASS"
    assert row["elapsed_s"] >= 0.2  # it really waited for the mission-settle bound
    assert "mission still running" in row["settle_reason"]


def test_the_run_aborts_when_the_stack_stops_answering(tmp_path: Path) -> None:
    """The latch lesson, generalised — and learned from this card's own live run.

    The hosted lane went silent at q30 of the first replay and the harness
    spoke twenty more queries into it, producing twenty confident verdicts
    about a lane that was not answering anybody. A turn that produces no
    transcript, no reply, no tool and no event is not a slow turn.
    """

    rows = [(f"{index:02d}", "scene", "What do you see?", "scene answer") for index in range(1, 8)]
    corpus = _corpus(tmp_path, rows)
    stack = FakeStack([{"said": ["I see a bench."]}] + [{} for _ in range(6)])
    runner = _runner(tmp_path, stack, corpus, silence_abort=3)
    runner.run()

    assert "stopped answering" in runner.aborted
    # one answered turn, then exactly three silent ones, and then it stops.
    assert stack.injections == 4
    assert [row["verdict"] for row in runner.results[4:]] == ["NOT_ATTEMPTED"] * 3


def test_an_isolated_silent_turn_does_not_abort_the_run(tmp_path: Path) -> None:
    """One dropped turn is noise; a run of them is a dead lane."""

    rows = [(f"{index:02d}", "scene", "What do you see?", "scene answer") for index in range(1, 6)]
    corpus = _corpus(tmp_path, rows)
    stack = FakeStack(
        [{"said": ["a"]}, {}, {"said": ["b"]}, {}, {"said": ["c"]}]
    )
    runner = _runner(tmp_path, stack, corpus, silence_abort=3)
    runner.run()
    assert runner.aborted == ""
    assert stack.injections == 5
