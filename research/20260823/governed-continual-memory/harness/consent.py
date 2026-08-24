"""M4 / M5 through the real lane: who may grant, and what stays forgotten.

These rows are driven through the SAME rails ``tests/test_p2a_memory_probes.py``
uses — a real ``RealtimeLane`` over the repo's scripted ``FakeRealtimeServer``
on a real transport pair, the real ``RealtimeToolBroker`` with the real privacy
policy inside it, a real ``ConversationMemory`` on a scratch file, and the real
``render_developer_instruction``. The only fakes are the socket, the clock and
the speaker; no hosted model is involved and none is claimed.

The one thing this harness adds to those rails is the runtime's OT-2 door: the
``remember_fact`` door applies
``owner_model.principal.admit_consent(principal, decision.consent)`` at the last
moment before the store, exactly as ``RobotRuntime._ot2_remember_fact`` does.
Reproducing it here rather than booting a ``RobotRuntime`` is the same trade the
P2-A probe file already documents — the runtime needs a simulator backend, and
the seam is three lines.

M5 is the full grid: five OT-2 speaker labels x four channels, each a separate
lane session on its own store, each asserting the stored consent against what
``GRANTING_LABELS`` says it should be. Nothing here reads the expected value
from a literal; it is derived from the frozen set, so a sixth label added
tomorrow lands in the matrix instead of being silently outside it.

M4's lane half is the revocation matrix: for each label, store -> forget ->
**a new session on the same file** must not carry the fact into the developer
instruction. That is the cross-session half of the revocation question; the
distillation half (does a scheduled pass bring it back) is in ``facts.py``.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from parcel_robot.memory.conversation import FACT_OWNER_STATED, ConversationMemory
from parcel_robot.models import ToolResult
from parcel_robot.owner_model.notes import owner_notes_from_facts
from parcel_robot.owner_model.policy import CONSENT_GRANTED, CONSENT_PENDING
from parcel_robot.owner_model.principal import (
    CHANNEL_API,
    CHANNEL_DISTILLER,
    CHANNEL_TEXT,
    CHANNEL_VOICE,
    GRANTING_LABELS,
    LABEL_NOT_OWNER,
    LABEL_OWNER,
    LABEL_UNENROLLED,
    LABEL_UNGATED,
    LABEL_UNVERIFIED,
    admit_consent,
    principal_from_speaker_label,
)
from parcel_robot.realtime.config import RealtimeConfig
from parcel_robot.realtime.fake_server import (
    FakeRealtimeServer,
    Step,
    function_call,
    handshake,
    response_done,
)
from parcel_robot.realtime.lane import MAX_TAIL_ITEMS, RealtimeLane
from parcel_robot.realtime.prompting import (
    MAX_OWNER_NOTES,
    DeveloperFlags,
    render_developer_instruction,
)
from parcel_robot.realtime.tool_broker import TOOL_REMEMBER_FACT, RealtimeToolBroker, ToolDoors
from parcel_robot.realtime.transport import transport_pair

#: The five OT-2 labels, cycled everywhere in this module.
LABELS: tuple[str, ...] = (
    LABEL_OWNER,
    LABEL_UNENROLLED,
    LABEL_UNVERIFIED,
    LABEL_NOT_OWNER,
    LABEL_UNGATED,
)

#: The four channels a request can arrive on.
CHANNELS: tuple[str, ...] = (CHANNEL_VOICE, CHANNEL_TEXT, CHANNEL_DISTILLER, CHANNEL_API)

#: A plain keep-category fact, so the only variable in the matrix is WHO.
KEEP_FACT = "their sister is called Hana"
KEEP_KEY = "sister_name"


class _Clock:
    def __init__(self, start: float = 1_000.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now


class _Sink:
    def begin_utterance(self) -> None:
        return None

    def enqueue(self, chunk: bytes, token: object = None) -> None:
        del chunk, token

    def interrupt(self) -> None:
        return None


class LaneSession:
    """One lane + one broker + one store, with a principal on the write door."""

    def __init__(
        self,
        store_path: Path,
        *,
        script: list[Step] | None = None,
        label: str = LABEL_UNENROLLED,
        channel: str = CHANNEL_VOICE,
    ) -> None:
        self.clock = _Clock()
        self.memory = ConversationMemory(store_path)
        self.principal = principal_from_speaker_label(label, channel=channel)
        self.downgrades = 0
        self.script = script if script is not None else handshake()
        self.transports: list[Any] = []
        self.servers: list[FakeRealtimeServer] = []
        self.broker = RealtimeToolBroker(
            ToolDoors(
                validate=lambda call: ToolResult(name=call.name, accepted=True, message="ok"),
                status=dict,
                recall=lambda query: "",
                gesture=lambda name, intensity: "",
                pose=lambda name: "",
                navigate=lambda place, relation: "",
                remember_fact=self._remember,
                forget_fact=self._forget,
                known_facts=self._known,
            )
        )
        self.lane = RealtimeLane(
            config=RealtimeConfig(enabled=True, source="h5"),
            instructions="be a good dog",
            transport_factory=self._factory,
            sink=_Sink(),
            clock=self.clock,
            tool_handler=self.broker,
            memory_tail=lambda: self.memory.ledger_tail(limit=MAX_TAIL_ITEMS * 4),
            session_id_factory=lambda: "rt_h5",
            sleep=lambda _delay: None,
            jitter=lambda: 1.0,
        )

    # -- the runtime's OT-2 door, reproduced ---------------------------------
    def _remember(self, key: str, fact: str, decision: object) -> dict[str, object]:
        requested = str(getattr(decision, "consent", CONSENT_PENDING))
        admission = admit_consent(self.principal, requested)
        if admission.downgraded:
            self.downgrades += 1
        return {
            "id": self.memory.add_owner_fact(
                key=key,
                value=fact,
                provenance=FACT_OWNER_STATED,
                consent=admission.consent,
                category=str(getattr(decision, "category", "")) or None,
                reason=str(getattr(decision, "reason", "")) or None,
            ),
            "consent": admission.consent,
            **admission.as_dict(),
        }

    def _forget(self, key: str) -> dict[str, object]:
        return {"forgotten": self.memory.forget_owner_fact(key)}

    def _known(self) -> tuple[str, ...]:
        from parcel_robot.owner_model.notes import known_facts_answer

        return known_facts_answer(self.memory.owner_facts(consent=CONSENT_GRANTED))

    # -- transport / pumping --------------------------------------------------
    def _factory(self) -> Any:
        lane_end, server_end = transport_pair(clock=self.clock)
        self.transports.append(lane_end)
        self.servers.append(
            FakeRealtimeServer(transport=server_end, script=list(self.script), clock=self.clock)
        )
        return lane_end

    def open(self) -> None:
        self.lane.open_session(handshake_token="tok", mic_gesture=True)
        self.settle()

    def settle(self, rounds: int = 4) -> None:
        for _ in range(rounds):
            self.servers[-1].pump()
            self.lane.pump()

    def drive(self, count: int) -> None:
        for _ in range(count):
            self.lane.send_audio(b"\x00\x00" * 240)
            self.settle()

    def outputs(self) -> list[dict[str, Any]]:
        sent = self.transports[-1].sent
        out: list[dict[str, Any]] = []
        for frame in sent:
            item = frame.get("item") if frame.get("type") == "conversation.item.create" else None
            if isinstance(item, dict) and item.get("type") == "function_call_output":
                out.append(json.loads(item["output"]))
        return out

    def developer_instruction(self) -> str:
        return render_developer_instruction(
            DeveloperFlags(
                owner_notes=owner_notes_from_facts(
                    self.memory.owner_facts(consent=CONSENT_GRANTED), limit=MAX_OWNER_NOTES
                )
            )
        ).text

    def close(self) -> None:
        self.lane.close()
        self.memory.connection.close()


def _script(*calls: tuple[str, dict[str, Any]]) -> list[Step]:
    steps = handshake()
    for index, (call_id, arguments) in enumerate(calls):
        steps.append(
            Step(
                "input_audio_buffer.append",
                (
                    function_call(call_id, TOOL_REMEMBER_FACT, json.dumps(arguments)),
                    response_done(f"resp_{index}"),
                ),
                label=f"remember_fact:{call_id}",
            )
        )
    return steps


def consent_matrix(store_dir: Path) -> dict[str, Any]:
    """M5 — five labels x four channels, each through the real lane."""

    store_dir.mkdir(parents=True, exist_ok=True)
    cells: list[dict[str, Any]] = []
    mismatches: list[dict[str, Any]] = []
    for label in LABELS:
        for channel in CHANNELS:
            path = store_dir / f"consent_{label}_{channel}.sqlite3"
            if path.exists():
                path.unlink()
            session = LaneSession(
                path,
                script=_script(("call_a", {"fact": KEEP_FACT, "key": KEEP_KEY})),
                label=label,
                channel=channel,
            )
            session.open()
            session.drive(1)
            (result,) = session.outputs()
            (row,) = session.memory.owner_facts()
            rendered = KEEP_FACT in session.developer_instruction()
            expected = CONSENT_GRANTED if label in GRANTING_LABELS else CONSENT_PENDING
            observed = str(row["consent"])
            cell = {
                "label": label,
                "channel": channel,
                "expected_consent": expected,
                "observed_consent": observed,
                "matches": observed == expected,
                "rendered_into_developer_instruction": rendered,
                "expected_rendered": expected == CONSENT_GRANTED,
                "tool_status": result.get("status"),
                "downgraded": session.downgrades > 0,
            }
            cells.append(cell)
            if not cell["matches"] or cell["rendered_into_developer_instruction"] != cell[
                "expected_rendered"
            ]:
                mismatches.append(cell)
            session.close()
    return {
        "granting_labels": sorted(GRANTING_LABELS),
        "labels": list(LABELS),
        "channels": list(CHANNELS),
        "cells": cells,
        "cells_total": len(cells),
        "cells_matching": sum(1 for c in cells if c["matches"]),
        "mismatches": mismatches,
    }


def revocation_matrix(store_dir: Path) -> dict[str, Any]:
    """M4's lane half — forget in one session, absent in the next, per label."""

    store_dir.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, Any]] = []
    for label in LABELS:
        path = store_dir / f"revocation_{label}.sqlite3"
        if path.exists():
            path.unlink()

        first = LaneSession(
            path,
            script=_script(("call_a", {"fact": KEEP_FACT, "key": KEEP_KEY})),
            label=label,
        )
        first.open()
        first.drive(1)
        stored_consent = str(first.memory.owner_facts()[0]["consent"])
        first.close()

        second = LaneSession(
            path,
            script=_script(("call_b", {"action": "forget", "key": KEEP_KEY})),
            label=label,
        )
        second.open()
        second.drive(1)
        (forgotten,) = second.outputs()
        second.close()

        third = LaneSession(path, label=label)
        third.open()
        instruction = third.developer_instruction()
        live_rows = third.memory.owner_facts()
        deleted_rows = third.memory.owner_facts(include_deleted=True)
        third.close()

        rows.append(
            {
                "label": label,
                "stored_consent": stored_consent,
                "rows_forgotten": forgotten.get("forgotten"),
                "in_later_developer_instruction": KEEP_FACT in instruction,
                "live_rows_after": len(live_rows),
                "rows_including_deleted": len(deleted_rows),
                "sessions": 3,
            }
        )
    return {
        "labels": list(LABELS),
        "rows": rows,
        "leaks": [r for r in rows if r["in_later_developer_instruction"]],
    }


__all__ = ["CHANNELS", "LABELS", "LaneSession", "consent_matrix", "revocation_matrix"]
