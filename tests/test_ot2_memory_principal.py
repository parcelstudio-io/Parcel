"""Card OT-2 — WHO may write a durable owner fact (the DW-3 memory slice).

P2-A answered *what* the robot may keep about its owner: a table, a
deterministic privacy policy, a broker tool, a consent state. It never asked
the other half, and the half it never asked is the one anybody in the room
walks through — **who is asking**. ``remember_fact`` arrived from the hosted
lane, the policy ruled on the TEXT, and a row landed ``granted`` whether the
sentence came from the enrolled owner, from a house guest, from a voice the
verifier ran on and could not identify, or from a television.

And the consent state P2-A created had nowhere to go:
``ConversationMemory.set_owner_fact_consent`` had exactly ONE caller in the
whole tree and it was a test, so the ``pending`` row that exists so "yes,
remember that" has something to point at could never be pointed at.

Both halves are measured here **through the runtime's real hosted broker** —
``RobotRuntime.realtime_broker.handle(...)``, the same object the hosted lane
dispatches into — against a scratch SQLite store. The owner's own
``parcel_memory.sqlite3`` is never opened by this file, read or write.
"""

from __future__ import annotations

import ast
import json
import sqlite3
from pathlib import Path
from typing import Any

import pytest

from parcel_robot.audio.devices import AudioDeviceStatus
from parcel_robot.backends.base import OwnerTrack, RobotPose, SimObservation
from parcel_robot.memory.conversation import ConversationMemory
from parcel_robot.owner_model import policy as owner_policy
from parcel_robot.owner_model.principal import (
    CONSENT_DENIED,
    CONSENT_GRANTED,
    CONSENT_PENDING,
    DISTILLER_PRINCIPAL,
    GRANTING_LABELS,
    LABEL_NOT_OWNER,
    LABEL_OWNER,
    LABEL_UNENROLLED,
    LABEL_UNGATED,
    LABEL_UNVERIFIED,
    MemoryPrincipal,
    admit_consent,
    principal_from_speaker_label,
)
from parcel_robot.realtime.config import REALTIME_CONFIG_ENV
from parcel_robot.realtime.tool_broker import (
    FACT_ACTION_CONFIRM,
    FACT_ACTIONS,
    STATUS_CONSENT_REQUIRED,
    STATUS_OK,
    TOOL_REMEMBER_FACT,
)
from parcel_robot.realtime.voice_identity import SPEAKER_LABELS, SpeakerLabel
from parcel_robot.runtime import RobotRuntime

REPO = Path(__file__).resolve().parents[1]
RUNTIME_PATH = REPO / "src" / "parcel_robot" / "runtime.py"

#: One fact per policy disposition, so the 5 x 3 matrix is over REAL verdicts.
FACT_KEEP = "their sister is called Hana"
FACT_ASK = "they take medication for their blood pressure"
FACT_REFUSE = "their wifi password is hunter2"

LABELS = (LABEL_OWNER, LABEL_UNENROLLED, LABEL_UNVERIFIED, LABEL_NOT_OWNER, LABEL_UNGATED)


# ---------------------------------------------------------------------------
# fixtures — a real runtime, a real broker, a scratch store
# ---------------------------------------------------------------------------


class _Backend:
    name = "fake"

    def observe(self) -> SimObservation:
        return SimObservation(
            timestamp=0.0, robot=RobotPose(), owner=OwnerTrack(), backend="fake"
        )

    def move(self, command: object) -> None:
        pass

    def stop(self) -> None:
        pass

    def pose(self, pose: object) -> None:
        pass

    def trajectory(self, skill: object) -> None:
        pass

    def move_owner(self, dx: float, dy: float) -> None:
        pass


class _Gate:
    """A stand-in for ``VoiceIdentityGate`` that reports one chosen label.

    The real gate needs an enrolled speaker profile and an embedder, neither of
    which exists on this host (``tools/enroll_owner_voice.py`` is a pending
    owner action). What is under test is the AUTHORIZATION RULE over the label,
    so the label is supplied and the rule is measured — and
    ``test_ot2_the_principal_vocabulary_is_p2bs`` pins that these five strings
    are exactly the ones the real gate can produce.
    """

    def __init__(self, label: str) -> None:
        self._label = label

    def label(self, kind: str = "turn") -> SpeakerLabel:
        return SpeakerLabel(
            label=self._label,
            code="fixture",
            gated=self._label != LABEL_UNGATED,
            enrolled=self._label != LABEL_UNENROLLED,
            score=0.83,
            kind=kind,
        )


@pytest.fixture
def store_path(tmp_path: Path) -> Path:
    return tmp_path / "ot2-scratch.sqlite3"


@pytest.fixture
def runtime(tmp_path: Path, store_path: Path, monkeypatch: pytest.MonkeyPatch):
    realtime = tmp_path / "ot2-realtime.yaml"
    realtime.write_text("enabled: true\nmode: text\n", encoding="utf-8")
    monkeypatch.setenv(REALTIME_CONFIG_ENV, str(realtime))
    config = tmp_path / "ot2-robot.yaml"
    config.write_text(
        f"""
skills:
  root: {REPO / "configs" / "skills"}
navigation:
  enabled: false
motion:
  backend: rl
  rl:
    enabled: true
    policy_path: ""
agent:
  prompts_root: {REPO / "prompts"}
memory:
  path: {store_path}
poses: {{}}
modules: []
""",
        encoding="utf-8",
    )
    made = RobotRuntime(
        config,
        _Backend(),
        audio_status=AudioDeviceStatus(
            status="text mode",
            driver="test",
            capture_hardware=False,
            connected_input=False,
            connected_output=False,
            detail="ot2 fixture",
        ),
    )
    yield made
    made.close()


def _speak(runtime: RobotRuntime, label: str) -> None:
    """Make the turn in progress come from this speaker."""

    runtime.realtime_voice_identity = _Gate(label)  # type: ignore[assignment]


def _call(runtime: RobotRuntime, **arguments: object) -> dict[str, Any]:
    """One hosted tool call, through the runtime's own broker."""

    return json.loads(
        runtime.realtime_broker.handle(
            name=TOOL_REMEMBER_FACT,
            call_id="call_ot2",
            arguments=json.dumps(arguments),
        )
    )


def _rows(store_path: Path) -> list[dict[str, Any]]:
    connection = sqlite3.connect(f"file:{store_path}?mode=ro", uri=True)
    try:
        cursor = connection.execute(
            "SELECT key, value, consent, provenance FROM owner_facts "
            "WHERE deleted_at IS NULL ORDER BY id"
        )
        return [
            {"key": r[0], "value": r[1], "consent": r[2], "provenance": r[3]}
            for r in cursor.fetchall()
        ]
    finally:
        connection.close()


# ---------------------------------------------------------------------------
# the rule itself
# ---------------------------------------------------------------------------


def test_ot2_the_principal_vocabulary_is_p2bs() -> None:
    """One vocabulary. A sixth label must not become a silent privilege."""

    assert set(LABELS) == set(SPEAKER_LABELS)
    assert GRANTING_LABELS == frozenset({LABEL_OWNER, LABEL_UNENROLLED})
    assert GRANTING_LABELS < set(SPEAKER_LABELS)
    assert (CONSENT_GRANTED, CONSENT_PENDING, CONSENT_DENIED) == (
        owner_policy.CONSENT_GRANTED,
        owner_policy.CONSENT_PENDING,
        owner_policy.CONSENT_DENIED,
    )
    # a label nobody has taught this module about reads as "could not verify",
    # never as the owner
    unknown = principal_from_speaker_label("some_future_label")
    assert unknown.label == LABEL_UNVERIFIED
    assert not unknown.may_grant_consent


@pytest.mark.parametrize("label", LABELS)
def test_ot2_admission_only_ever_moves_a_verdict_toward_not_yet(label: str) -> None:
    """``admit_consent`` can downgrade and can never promote. Total function."""

    principal = principal_from_speaker_label(label)
    for verdict in (CONSENT_GRANTED, CONSENT_PENDING, CONSENT_DENIED):
        admission = admit_consent(principal, verdict)
        if verdict == CONSENT_GRANTED and not principal.may_grant_consent:
            assert admission.consent == CONSENT_PENDING
            assert admission.downgraded
            assert admission.reason
        else:
            assert admission.consent == verdict
            assert not admission.downgraded


def test_ot2_the_distiller_may_propose_and_never_state() -> None:
    """"A model may PROPOSE a memory fact" as a type, not as a convention."""

    assert isinstance(DISTILLER_PRINCIPAL, MemoryPrincipal)
    assert not DISTILLER_PRINCIPAL.may_grant_consent
    assert not DISTILLER_PRINCIPAL.may_confirm_consent
    assert admit_consent(DISTILLER_PRINCIPAL, CONSENT_GRANTED).consent == CONSENT_PENDING


# ---------------------------------------------------------------------------
# R8 — through the runtime's broker
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("label", LABELS)
@pytest.mark.parametrize(
    ("fact", "disposition"),
    (
        (FACT_KEEP, owner_policy.DISPOSITION_KEEP),
        (FACT_ASK, owner_policy.DISPOSITION_ASK),
        (FACT_REFUSE, owner_policy.DISPOSITION_REFUSE),
    ),
)
def test_ot2_unverified_audio_never_creates_granted_memory(
    runtime: RobotRuntime, store_path: Path, label: str, fact: str, disposition: str
) -> None:
    """R8 — the 5 x 3 matrix. Seed S4's target.

    Exactly two of the fifteen cells produce a ``granted`` row, and both of them
    are a principal that :data:`GRANTING_LABELS` admits saying something the
    policy admits keeping. Every other cell is ``pending``, refused, or absent —
    and none of them is silent: a downgraded write comes back as
    ``consent_required`` with the principal attached, so the model narrates
    "I've written that down but I need to check" rather than "I've remembered
    that".
    """

    _speak(runtime, label)
    assert owner_policy.decide(fact).disposition == disposition
    result = _call(runtime, action="remember", fact=fact)
    rows = _rows(store_path)
    # The expected set is written out HERE and not read from the product.
    # Reading ``GRANTING_LABELS`` would make this whole matrix follow whatever
    # the rule happens to say — seed S4 widened that set and this test stayed
    # green until the literal replaced it.
    granting = label in {LABEL_OWNER, LABEL_UNENROLLED}

    if disposition == owner_policy.DISPOSITION_REFUSE:
        assert result["status"] == "rejected"
        assert rows == []
        return
    if disposition == owner_policy.DISPOSITION_KEEP and granting:
        assert result["status"] == STATUS_OK
        assert result["stored"] is True
        assert [row["consent"] for row in rows] == [CONSENT_GRANTED]
        return
    # everything else: written down, not kept, and SAID so
    assert result["status"] == STATUS_CONSENT_REQUIRED
    assert result["stored"] is False
    assert [row["consent"] for row in rows] == [CONSENT_PENDING]
    if disposition == owner_policy.DISPOSITION_KEEP:
        assert result["consent_downgraded"] is True
        assert result["principal"]["label"] == label
        assert result["consent"] == CONSENT_PENDING


def test_ot2_the_matrix_grants_exactly_twice(runtime: RobotRuntime, store_path: Path) -> None:
    """The same 15 cells, counted in one place so the number is checkable."""

    granted = 0
    for label in LABELS:
        for fact in (FACT_KEEP, FACT_ASK, FACT_REFUSE):
            _speak(runtime, label)
            runtime.agent.memory.forget_owner_fact(_key(fact))
            _call(runtime, action="remember", fact=fact, key=_key(fact))
            granted += sum(
                1
                for row in _rows(store_path)
                if row["consent"] == CONSENT_GRANTED and row["key"] == _key(fact)
            )
            runtime.agent.memory.forget_owner_fact(_key(fact))
    assert granted == 2


def _key(fact: str) -> str:
    return "_".join(fact.lower().split())[:40]


def test_ot2_an_unverified_voice_may_still_talk_and_still_stop_the_dog(
    runtime: RobotRuntime,
) -> None:
    """The rule is about MEMORY and nothing else. Nothing new is refused.

    P2-B's absolute — identity is a label, not a gate — is untouched: the
    emergency class still arms with a label of ``ungated``, and this card adds
    no branch anywhere near arming. What it adds is a downgrade on one write.
    """

    from parcel_robot.realtime.voice_identity import gates_kind

    _speak(runtime, LABEL_UNVERIFIED)
    assert not runtime._ot2_memory_principal().may_grant_consent
    # the emergency class is still ungated by identity, in the module that
    # decides arming, which this card does not touch
    assert not gates_kind("emergency")
    # and conversation is untouched: a list still answers
    assert _call(runtime, action="list")["status"] == STATUS_OK


# ---------------------------------------------------------------------------
# R9/R10 — the confirmation door
# ---------------------------------------------------------------------------


def test_ot2_a_row_records_who_spoke_when_it_was_not_the_owner(
    runtime: RobotRuntime, store_path: Path
) -> None:
    """The durable row says whose voice it came from. Fable, OT-2 item 6.

    ``provenance`` is a two-value column (``owner_stated`` / ``model_proposed``)
    that P2-A owns, and for a voice the verifier said was NOT the owner,
    ``owner_stated`` asserts something nobody established. Widening the column
    is a schema change outside this card, so the fact rides in ``reason``,
    which ``add_owner_fact`` persists verbatim.
    """

    _speak(runtime, LABEL_NOT_OWNER)
    _call(runtime, action="remember", fact=FACT_KEEP, key="sister_name")
    connection = sqlite3.connect(f"file:{store_path}?mode=ro", uri=True)
    try:
        reason, provenance, consent = connection.execute(
            "SELECT reason, provenance, consent FROM owner_facts WHERE key = ?",
            ("sister_name",),
        ).fetchone()
    finally:
        connection.close()
    assert consent == CONSENT_PENDING
    assert f"[heard from: {LABEL_NOT_OWNER}]" in reason
    # the column itself is still P2-A's two-value one, and that is the gap
    assert provenance == "owner_stated"


def test_ot2_an_owners_own_row_is_not_churned_with_a_stamp(
    runtime: RobotRuntime, store_path: Path
) -> None:
    """For a granting principal ``owner_stated`` is already true — no stamp."""

    _speak(runtime, LABEL_OWNER)
    _call(runtime, action="remember", fact=FACT_KEEP, key="sister_name")
    rows = _rows(store_path)
    assert [row["consent"] for row in rows] == [CONSENT_GRANTED]
    connection = sqlite3.connect(f"file:{store_path}?mode=ro", uri=True)
    try:
        (reason,) = connection.execute(
            "SELECT reason FROM owner_facts WHERE key = ?", ("sister_name",)
        ).fetchone()
    finally:
        connection.close()
    assert "heard from" not in (reason or "")


def test_ot2_set_owner_fact_consent_has_exactly_one_product_caller() -> None:
    """R9, first half. Before this card the only caller in the tree was a test.

    Walked over the whole package rather than asserted about one file: the
    point of the row is that the product has A caller, and that it is the
    confirmation door rather than something that reached into the store from
    the side.
    """

    callers: list[str] = []
    for path in sorted((REPO / "src" / "parcel_robot").rglob("*.py")):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and node.attr == "set_owner_fact_consent":
                enclosing = [
                    fn.name
                    for fn in ast.walk(tree)
                    if isinstance(fn, ast.FunctionDef)
                    and any(inner is node for inner in ast.walk(fn))
                ]
                callers.append(f"{path.name}:{enclosing[-1] if enclosing else '<module>'}")
    assert callers == ["runtime.py:_ot2_confirm_fact"], callers


def test_ot2_the_doors_the_runtime_wires_are_the_ot2_ones() -> None:
    """R9, second half: the seam is in ``ToolDoors``, not reproduced in a test."""

    tree = ast.parse(RUNTIME_PATH.read_text())
    runtime_class = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.ClassDef) and node.name == "RobotRuntime"
    )
    init = next(
        node
        for node in ast.walk(runtime_class)
        if isinstance(node, ast.FunctionDef) and node.name == "__init__"
    )
    doors = next(
        node
        for node in ast.walk(init)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "ToolDoors"
    )
    wired = {
        keyword.arg: ast.unparse(keyword.value)
        for keyword in doors.keywords
        if keyword.arg
    }
    assert wired["remember_fact"] == "self._ot2_remember_fact"
    assert wired["confirm_fact"] == "self._ot2_confirm_fact"
    assert FACT_ACTION_CONFIRM in FACT_ACTIONS


def test_ot2_confirming_a_parked_fact_is_what_keeps_it(
    runtime: RobotRuntime, store_path: Path
) -> None:
    """R9 — pending -> granted, once, and only then does the robot say it knows."""

    _speak(runtime, LABEL_OWNER)
    parked = _call(runtime, action="remember", fact=FACT_ASK, key="medication")
    assert parked["status"] == STATUS_CONSENT_REQUIRED
    assert [row["consent"] for row in _rows(store_path)] == [CONSENT_PENDING]
    assert runtime._realtime_known_facts() == ()

    confirmed = _call(runtime, action="confirm", key="medication")
    assert confirmed["status"] == STATUS_OK
    assert confirmed["confirmed"] == 1
    assert confirmed["stored"] is True
    assert [row["consent"] for row in _rows(store_path)] == [CONSENT_GRANTED]
    answer = runtime._realtime_known_facts()
    assert any("blood pressure" in line for line in answer), answer
    assert runtime.realtime_broker.snapshot()["facts_confirmed"] == 1


def test_ot2_the_owner_may_also_say_no(runtime: RobotRuntime, store_path: Path) -> None:
    """``confirm`` carries the answer, not just the act of answering."""

    _speak(runtime, LABEL_OWNER)
    _call(runtime, action="remember", fact=FACT_ASK, key="medication")
    denied = _call(runtime, action="confirm", key="medication", consent="denied")
    assert denied["status"] == STATUS_OK
    assert denied["stored"] is False
    assert [row["consent"] for row in _rows(store_path)] == [CONSENT_DENIED]
    assert runtime._realtime_known_facts() == ()


def test_ot2_repeating_remember_fact_is_not_confirmation(
    runtime: RobotRuntime, store_path: Path
) -> None:
    """R10 — three sends, zero grants. Seed S5's target.

    The failure this shape exists to prevent is subtle and entirely plausible:
    the model is told to ask the owner, the owner says "yes", and the model —
    having no confirm verb — sends ``remember`` again. If a repeat counted, the
    consent step would be a formality the model can satisfy by itself, which is
    the one party in the exchange that must not be able to.
    """

    _speak(runtime, LABEL_OWNER)
    for _attempt in range(3):
        result = _call(runtime, action="remember", fact=FACT_ASK, key="medication")
        assert result["status"] == STATUS_CONSENT_REQUIRED
        assert result["stored"] is False
    rows = _rows(store_path)
    assert len(rows) == 1
    assert rows[0]["consent"] == CONSENT_PENDING
    assert sum(1 for row in rows if row["consent"] == CONSENT_GRANTED) == 0
    assert runtime.realtime_broker.snapshot()["facts_confirmed"] == 0


def test_ot2_an_unverified_voice_cannot_confirm_either(
    runtime: RobotRuntime, store_path: Path
) -> None:
    """Two steps must not achieve what one step was refused."""

    _speak(runtime, LABEL_OWNER)
    _call(runtime, action="remember", fact=FACT_ASK, key="medication")
    _speak(runtime, LABEL_UNVERIFIED)
    refused = _call(runtime, action="confirm", key="medication")
    assert refused["status"] == "rejected"
    assert refused["confirmed"] == 0
    assert [row["consent"] for row in _rows(store_path)] == [CONSENT_PENDING]
    assert runtime.memory_principal_snapshot()["confirmations_refused"] == 1
    # and the owner can still finish the job afterwards
    _speak(runtime, LABEL_OWNER)
    assert _call(runtime, action="confirm", key="medication")["confirmed"] == 1


def test_ot2_confirm_needs_a_key_and_never_the_sentence_again(
    runtime: RobotRuntime,
) -> None:
    """A confirmation that carried the text could be a repeat wearing a hat."""

    _speak(runtime, LABEL_OWNER)
    assert _call(runtime, action="confirm")["status"] == "rejected"


def test_ot2_the_owner_store_is_not_the_one_under_test(store_path: Path) -> None:
    """The scratch store is a scratch store. Stated as a test, not a promise."""

    from parcel_robot.memory.path import owner_store_paths

    owned = {Path(p).resolve() for p in owner_store_paths()}
    assert store_path.resolve() not in owned
    memory = ConversationMemory(store_path)
    assert Path(memory.store.path).resolve() == store_path.resolve()
