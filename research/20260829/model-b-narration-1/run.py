#!/usr/bin/env python
"""MB-1 — run the corpus through every arm and write results.json.

    .parcel/bin/python research/20260829/model-b-narration-1/run.py \\
        --all --seed 20260829 --hosted-cap-usd 3

ORDER IS NOT NEGOTIABLE (amendment M5, and the executor brief)
--------------------------------------------------------------
``fake`` -> ``local`` -> ``hosted``.  The scripted rows prove the harness on a
real :class:`~parcel_robot.realtime.lane.RealtimeLane` over the product's own
:class:`~parcel_robot.realtime.fake_server.FakeRealtimeServer` before a cent is
spent; the local rows answer H-MB1d on hardware that costs nothing; only then
does anything reach the provider.

THE $5 CAP, AS THE PRODUCT ENFORCES IT
--------------------------------------
* ``PARCEL_REALTIME_CONFIG`` -> the wave-local ``realtime.yaml``
  (``monthly_budget_usd: 5.0``, ``gpt-realtime-2.1-mini``, ``mode: text``);
* ``PARCEL_REALTIME_SPEND_LEDGER`` -> the ONE wave ledger shared with LIT-1;
* a wave-local ``robot.yaml`` carrying ``audio.ear.governor``
  ``{envelope_usd: 5.0, reserve_usd: 0.0, warn_usd: 4.0, daily_cap_usd: 5.0,
  refuse_when_unknown: true}``;
* every hosted turn through ``runtime.submit_realtime_text``, which is the one
  product entry point that consults ``_require_hosted_budget``;
* ``CLASS_ROUTINE`` only — never ``CLASS_CRITICAL``, which is admitted before
  the governor reads the ledger;
* one session per scenario, closed at the end of it, so the arming gate
  re-reads the ledger between scenarios;
* ``governor.snapshot()`` printed before the first hosted call and after the
  last, and a hard local stop at ``--hosted-cap-usd``.

TEXT-MODE GOVERNOR STATUS
-------------------------
An earlier pilot found that the product did not construct
``HostedCallGovernor`` in text mode.  The product runtime has since been fixed
to do so.  ``build_hosted_runtime`` still contains a defensive, evidence-labelled
fallback for reproducing the historical pilot, but current rows require and
record a governor before the first provider call either way.

Paid hosted rows are also written to an atomic, lossless per-scenario
checkpoint.  A resume validates the frozen schedule/config and every entry
digest, skips completed scenarios, and refuses to retry a scenario that spent
calls before failing unless ``--hosted-retry-incomplete`` is explicit.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

FOLDER = Path(__file__).resolve().parent
REPO_ROOT = FOLDER.parents[2]
for _extra in (str(REPO_ROOT), str(REPO_ROOT / "src"), str(FOLDER)):
    if _extra not in sys.path:
        sys.path.insert(0, _extra)

HOME = Path.home()
CACHE = HOME / ".cache/parcel-0e/mb1"
WAVE_LEDGER = HOME / ".cache/parcel-0e/wave20260829/spend.jsonl"
WAVE_REALTIME_CONFIG = CACHE / "realtime.yaml"
WAVE_ROBOT_CONFIG = CACHE / "robot.yaml"
CREDENTIAL_FILE = HOME / ".config/parcel/realtime.env"

LOCAL_PORT = 8093
LOCAL_MODEL = CACHE / "models/Qwen2.5-7B-Instruct-Q4_K_M.gguf"
LLAMA_SERVER = REPO_ROOT / "third_party/llama.cpp-bin/llama-b10235/llama-server"

RUN_ID = "mb1-run-v1"
HOSTED_CHECKPOINT_SCHEMA = "parcel.mb1.hosted_checkpoint.v1"

import events as ev
import narrate as nr
import scorer as sc
import steer as st


# ------------------------------------------------------------------ replies
@dataclass
class RobotReply:
    text: str
    ttft_ms: float | None = None
    total_ms: float | None = None
    deltas: list[tuple[float, str]] = field(default_factory=list)
    usage: dict[str, object] = field(default_factory=dict)


def _canonical_json(value: object) -> bytes:
    """Stable bytes for evidence digests, never a provider request body."""

    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def _sha256(value: object) -> str:
    return hashlib.sha256(_canonical_json(value)).hexdigest()


def _safe_provider_error(error: object) -> str:
    """Product redaction plus the provider's non-secret account identifier."""

    from parcel_robot.realtime.ws_transport import redact

    return re.sub(r"\borg-[A-Za-z0-9_-]+\b", "org-[REDACTED]", redact(error))


def _turn_as_checkpoint(turn: sc.Turn) -> dict[str, object]:
    """Lossless turn representation used by the paid-wave checkpoint.

    ``ScenarioResult.as_dict`` is a publication view and intentionally omits
    role, receipt history and delta timing.  Those fields are required to
    rescore a resumed run, so the checkpoint owns a separate lossless shape.
    """

    return {
        "scenario_id": turn.scenario_id,
        "arm": turn.arm,
        "sample": turn.sample,
        "turn_index": turn.turn_index,
        "role": turn.role,
        "text": turn.text,
        "at_s": turn.at_s,
        "events_so_far": turn.events_so_far,
        "trigger_event_id": turn.trigger_event_id,
        "ttft_ms": turn.ttft_ms,
        "total_ms": turn.total_ms,
        "deltas": [[offset, text] for offset, text in turn.deltas],
    }


def _turn_from_checkpoint(row: dict[str, object]) -> sc.Turn:
    required = {
        "scenario_id", "arm", "sample", "turn_index", "role", "text", "at_s",
        "events_so_far", "trigger_event_id", "ttft_ms", "total_ms", "deltas",
    }
    missing = sorted(required - row.keys())
    if missing:
        raise ValueError(f"checkpoint turn is missing {missing}")
    role = str(row["role"])
    if role not in {"owner", "robot"}:
        raise ValueError(f"checkpoint turn has invalid role {role!r}")
    return sc.Turn(
        scenario_id=str(row["scenario_id"]),
        arm=str(row["arm"]),
        sample=int(row["sample"]),
        turn_index=int(row["turn_index"]),
        role=role,
        text=str(row["text"]),
        at_s=float(row["at_s"]),
        events_so_far=[dict(event) for event in row["events_so_far"]],
        trigger_event_id=str(row["trigger_event_id"]),
        ttft_ms=None if row["ttft_ms"] is None else float(row["ttft_ms"]),
        total_ms=None if row["total_ms"] is None else float(row["total_ms"]),
        deltas=[(float(offset), str(text)) for offset, text in row["deltas"]],
    )


# ------------------------------------------------------- the scripted server
def _scripted_reply(items: list[str], owner: str, speech_act: str) -> str:
    """A deterministic responder that READS the injected context.

    It is not a language model and does not pretend to be one.  Its only job is
    to prove the harness end to end: that the plan-queue item reaches the wire,
    that the trigger table fires exactly one ``response.create``, that the reply
    comes back through the lane, and that the scorer's bars can in principle be
    met and missed.  It is deliberately literal — it composes from the LAST
    injected item and nothing else — so a scorer bug shows up as a scored
    failure on a sentence a human can read.
    """

    context = items[-1] if items else ""
    goal = ""
    status = ""
    for line in context.splitlines():
        line = line.strip()
        if not line.startswith("- "):
            continue
        try:
            row = json.loads(line[2:])
        except json.JSONDecodeError:
            continue
        if "last_event" in row:
            status = str(row["last_event"].get("fact", ""))
            goal = str(row["last_event"].get("goal", "")) or goal
        elif row.get("status") in {"active", "queued", "suspended"}:
            goal = goal or str(row.get("goal", ""))
    pending = [
        json.loads(line[2:])
        for line in context.splitlines()
        if line.strip().startswith("- ") and '"status"' in line
    ]
    queued = [r for r in pending if r.get("status") in {"queued", "suspended"}]

    if context.startswith("The robot's navigation system reports"):
        # ARM D's context: the product whisperer's own composed sentence.  The
        # responder answers the FACT it was handed and nothing else, which is
        # precisely what arm D gives a model to work with.
        place = re.search(r"(?:beside|inside|short of|near|to) (the [a-z ]+?)[.,]", context)
        goal = place.group(1).strip() if place else goal
        if "keys" in owner.lower():
            pass
        elif "arrived" in context or "standing inside" in context or "stopped just short" in context:
            return f"I have arrived beside {goal}. What would you like next?" if goal else \
                   "I have arrived. What would you like next?"
        elif "gave up" in context or "ended" in context:
            return f"I couldn't get to {goal} — the trip ended. What would you like instead?"
        elif "blocking" in context or "in the way" in context:
            return f"Something is in the way on the route to {goal}, so I'm waiting for it to clear."
        elif "clear again" in context:
            return f"The way to {goal} is clear again, so I'm carrying on."
    if "camera" in owner.lower() or "see my keys" in owner.lower() or "keys" in owner.lower():
        tail = f" Want me to go to {goal}?" if goal else " What would you like instead?"
        return (
            "I don't have a camera, so I can't look for your keys — I only know "
            "where I have been." + tail
        )
    if speech_act.startswith("Say you have arrived"):
        line = f"I have arrived beside {goal}." if goal else "I have arrived."
        if queued:
            return line + f" Shall I go to {queued[0]['goal']} now?"
        return line + " What would you like next?"
    if speech_act.startswith("Tell the owner what is in the way"):
        return f"Something is in the way on the route to {goal}, so I'm waiting for it to clear."
    if speech_act.startswith("Tell the owner you did not get there"):
        return f"I couldn't get to {goal} — a person stayed in the way. What would you like instead?"
    if speech_act.startswith("Ask the owner exactly one short question"):
        return "Which one do you mean?"
    if owner:
        if status == "accepted" and goal:
            if any(r.get("status") == "queued" and r.get("goal") == goal for r in pending):
                return f"Sure — after that I'll check {goal}."
            return f"Okay, I'll head to {goal} now."
        if status == "running" and goal:
            return f"Okay, I'm on my way to {goal}."
        if status == "blocked" and goal:
            return f"Something is in the way on the route to {goal}, so I'm waiting."
        if status == "failed" and goal:
            return f"I couldn't get to {goal} — a person stayed in the way."
        if status == "cancelled":
            return "Okay, I've stopped."
        if status == "resumed" and goal:
            return f"Right, back to {goal} — I'm on my way."
        if status == "completed" and goal:
            return f"I'm beside {goal}. What would you like next?"
        return "Okay."
    return "Okay."


class ScriptedServer:
    """Drives one end of an :class:`InProcessTransport` pair, dynamically.

    ``FakeRealtimeServer`` is a static ``Step`` script and cannot compose a
    reply from what the lane injected, which is exactly what these rows have to
    exercise.  This class reuses the product fake's own frame builders
    (``session_created`` / ``transcript_delta`` / ``transcript_done`` /
    ``response_done``) so the wire shape is the shipped one; only the *choice*
    of reply is local.
    """

    def __init__(self, transport: object) -> None:
        from parcel_robot.realtime import fake_server as fs

        self.fs = fs
        self.transport = transport
        self.items: list[str] = []
        self.received: list[dict] = []
        self.responses = 0
        self.speech_act = ""
        self.last_owner = ""
        self.deltas: list[tuple[float, str]] = []
        self._seq = 0

    def pump(self) -> int:
        from parcel_robot.realtime.transport import TransportClosed

        handled = 0
        while True:
            try:
                frame = self.transport.receive()
            except TransportClosed:
                return handled
            if frame is None:
                return handled
            self.received.append(dict(frame))
            handled += 1
            self._handle(dict(frame))

    def _handle(self, frame: dict) -> None:
        kind = str(frame.get("type", ""))
        if kind == "session.update":
            self.transport.send(self.fs.session_created("sess_mb1_fake"))
            return
        if kind == "conversation.item.create":
            text = _item_text(frame)
            role = _item_role(frame)
            if role == "user":
                self.last_owner = text
            else:
                self.items.append(text)
                for line in text.splitlines():
                    stripped = line.strip()
                    if stripped and not stripped.startswith(("[", "- ", "The robot's own")):
                        self.speech_act = stripped
            return
        if kind == "response.create":
            self._seq += 1
            rid, iid = f"resp_{self._seq}", f"item_{self._seq}"
            reply = _scripted_reply(self.items, self.last_owner, self.speech_act)
            self.deltas = []
            start = time.perf_counter()
            for chunk in _chunks(reply):
                self.deltas.append((time.perf_counter() - start, chunk))
                self.transport.send(self.fs.transcript_delta(rid, iid, chunk))
            self.transport.send(self.fs.transcript_done(rid, iid, reply))
            self.transport.send(self.fs.audio_done(rid, iid))
            self.transport.send(
                self.fs.response_done(rid, input_tokens=0, output_tokens=0,
                                      input_audio_tokens=0, output_audio_tokens=0,
                                      cached_tokens=0)
            )
            self.responses += 1
            self.last_owner = ""
            self.speech_act = ""


def _chunks(text: str, size: int = 12) -> list[str]:
    return [text[i : i + size] for i in range(0, len(text), size)] or [text]


def _item_text(frame: dict) -> str:
    item = frame.get("item") or {}
    content = item.get("content") or []
    for part in content:
        for key in ("text", "input_text", "transcript"):
            value = part.get(key) if isinstance(part, dict) else None
            if isinstance(value, str) and value:
                return value
    return ""


def _item_role(frame: dict) -> str:
    item = frame.get("item") or {}
    return str(item.get("role", ""))


# --------------------------------------------------------------- backends
class ScriptedBackend:
    """A REAL lane over an in-process transport and the scripted server."""

    name = "fake-server"
    tier = "replay"

    def __init__(self, config) -> None:
        self.config = config
        self.lane = None
        self.server = None
        self.ledger = None
        self.injected_tokens = 0
        self.items_sent = 0
        self.response_creates = 0

    def open_session(self, scenario) -> None:
        from parcel_robot.realtime.lane import RealtimeLane, build_instructions
        from parcel_robot.realtime.prompting import GUARDRAILS
        from parcel_robot.realtime.transport import transport_pair

        client, server = transport_pair()
        self.server = ScriptedServer(server)
        instructions = build_instructions(
            personality=COMPANION_PERSONA, reply_style=(), guardrails=GUARDRAILS
        )
        self.ledger = _CaptureLedger()
        self.lane = RealtimeLane(
            config=self.config,
            instructions=instructions,
            transport_factory=lambda: client,
            sink=_DiscardSink(),
            ledger=self.ledger,
        )
        self.lane.open_session(handshake_token="mb1-fake", mic_gesture=True)
        self.server.pump()
        self.lane.pump()

    def inject_item(self, *, role: str, text: str, purpose: str) -> int:
        self.lane._send_item(role=role, text=text, purpose=purpose)
        self.items_sent += 1
        self.server.pump()
        return max(1, round(len(text) / 4))

    def owner_turn(self, text: str) -> RobotReply:
        start = time.perf_counter()
        self.lane.send_text(text)
        self.response_creates += 1
        self.server.pump()
        return self._collect(start)

    def trigger_response(self) -> RobotReply:
        from parcel_robot.realtime.protocol import ResponseCreate

        start = time.perf_counter()
        self.lane._send(ResponseCreate())
        self.response_creates += 1
        self.server.pump()
        return self._collect(start)

    def _collect(self, start: float) -> RobotReply:
        self.lane.pump()
        text = " ".join(t for _at, t in self.ledger.take_robot()).strip()
        deltas = list(self.server.deltas)
        return RobotReply(
            text=text,
            ttft_ms=round(deltas[0][0] * 1000, 3) if deltas else None,
            total_ms=round((time.perf_counter() - start) * 1000, 3),
            deltas=[(t, d) for t, d in deltas],
        )

    def close(self) -> None:
        if self.lane is not None:
            self.lane.close()
        self.lane = None
        self.server = None


class LocalBackend:
    """A local instruct model on :8093, given the same items in the same order.

    The conversation is rebuilt as chat messages because that is the only
    interface a llama-server exposes; the ITEM TEXT is byte-identical to what
    the lane would put on the wire, so the arms differ in the model and not in
    the context.
    """

    name = "local-8b"
    tier = "replay"

    def __init__(self, base_url: str, model: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.messages: list[dict[str, str]] = []
        self.injected_tokens = 0
        self.items_sent = 0
        self.response_creates = 0

    def open_session(self, scenario) -> None:
        from parcel_robot.realtime.lane import build_instructions
        from parcel_robot.realtime.prompting import GUARDRAILS

        self.messages = [
            {
                "role": "system",
                "content": build_instructions(
                    personality=COMPANION_PERSONA, reply_style=(), guardrails=GUARDRAILS
                ),
            }
        ]

    def inject_item(self, *, role: str, text: str, purpose: str) -> int:
        # Replace-not-append: a plan-queue refresh REPLACES the previous one.
        if purpose == nr.PURPOSE_PLAN_QUEUE:
            self.messages = [
                m for m in self.messages if m.get("_purpose") != nr.PURPOSE_PLAN_QUEUE
            ]
        message = {"role": "system" if role == "system" else role, "content": text}
        message["_purpose"] = purpose
        self.messages.append(message)
        self.items_sent += 1
        tokens = max(1, round(len(text) / 4))
        self.injected_tokens += tokens
        return tokens

    def owner_turn(self, text: str) -> RobotReply:
        self.messages.append({"role": "user", "content": text, "_purpose": "owner turn"})
        return self._complete()

    def trigger_response(self) -> RobotReply:
        return self._complete()

    def _complete(self) -> RobotReply:
        payload = {
            "model": self.model,
            "messages": [
                {"role": m["role"], "content": m["content"]} for m in self.messages
            ],
            "temperature": 0.0,
            "max_tokens": 120,
            "stream": True,
        }
        request = urllib.request.Request(
            f"{self.base_url}/v1/chat/completions",
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"},
        )
        start = time.perf_counter()
        deltas: list[tuple[float, str]] = []
        pieces: list[str] = []
        self.response_creates += 1
        with urllib.request.urlopen(request, timeout=180) as response:
            for raw in response:
                line = raw.decode("utf-8").strip()
                if not line.startswith("data: "):
                    continue
                body = line[6:]
                if body == "[DONE]":
                    break
                try:
                    frame = json.loads(body)
                except json.JSONDecodeError:
                    continue
                choice = (frame.get("choices") or [{}])[0]
                piece = (choice.get("delta") or {}).get("content") or ""
                if piece:
                    deltas.append((time.perf_counter() - start, piece))
                    pieces.append(piece)
        text = "".join(pieces).strip()
        self.messages.append({"role": "assistant", "content": text, "_purpose": "reply"})
        return RobotReply(
            text=text,
            ttft_ms=round(deltas[0][0] * 1000, 3) if deltas else None,
            total_ms=round((time.perf_counter() - start) * 1000, 3),
            deltas=deltas,
        )

    def close(self) -> None:
        self.messages = []


class HostedBackend:
    """The product runtime, the real lane, the real provider.  Every $ recorded.

    ``owner_turn`` is ``runtime.submit_realtime_text`` and nothing else, so
    ``_require_hosted_budget`` runs on every owner turn.  Injections and
    trigger responses go through the LANE (``_send_item`` / ``ResponseCreate``)
    because that is where amendment M6 puts them, and each one is preceded by an
    explicit ``governor.require(..., call_class=CLASS_ROUTINE)`` so no billed
    frame ever leaves without the ceiling having been asked.
    """

    name = "hosted"
    tier = "hosted-live"

    def __init__(self, runtime, *, cap_usd: float, ledger_path: Path) -> None:
        self.runtime = runtime
        self.cap_usd = float(cap_usd)
        self.ledger_path = ledger_path
        self.injected_tokens = 0
        self.items_sent = 0
        self.response_creates = 0
        self.refusals: list[dict[str, object]] = []
        self.usage_rows: list[dict[str, object]] = []
        self.ledger: _CaptureLedger | None = None
        self.ingress_detached = False
        self.tool_choice = "auto"
        self.last_session_id = ""

    @property
    def lane(self):
        return self.runtime.realtime_lane

    def _require(self, purpose: str) -> bool:
        from parcel_robot.realtime.hosted_budget import CLASS_ROUTINE, HostedCallRefused

        governor = self.runtime.realtime_governor
        if governor is None:
            raise RuntimeError("MB-1 refuses to spend with no governor attached")
        try:
            governor.require(purpose, call_class=CLASS_ROUTINE)
        except HostedCallRefused as refusal:
            self.refusals.append(
                {"purpose": purpose, "decision": refusal.decision.as_dict()}
            )
            return False
        return True

    def open_session(self, scenario) -> None:
        self.runtime.bind_panel_token("mb1-hosted")
        lane = self.lane
        if lane is not None and not isinstance(getattr(lane, "_ledger", None), _CaptureLedger):
            self.ledger = _CaptureLedger(getattr(lane, "_ledger", None))
            lane._ledger = self.ledger
        if lane is not None and getattr(lane, "_ingress", None) is not None:
            # THE INGRESS IS DETACHED FOR THESE ROWS, AND HERE IS WHY.
            #
            # ``send_text`` runs the owner's sentence through the runtime's
            # deterministic command ingress and injects the OUTCOME as an
            # ``action report`` item before the model answers (lane.py:1801-1815).
            # On this host that outcome is always a refusal — there is no robot,
            # no sim socket and no enrolled owner voice — and the pilot measured
            # what it does to the corpus: every reply became about the refusal
            # ("That request was dropped because it didn't recognize who was
            # asking"), never about the plan queue.
            #
            # MB-1's corpus SUPPLIES the executive's answers as receipts; letting
            # a second, failing executive answer the same sentence would be
            # double-counting a robot that does not exist.  ``submit_realtime_text``
            # is still the entry point, so ``_require_hosted_budget`` still runs on
            # every owner turn and the M5 chain is intact.
            self.ingress_detached = True
            lane._ingress = None
        broker = getattr(self.runtime, "realtime_broker", None)
        if broker is not None and getattr(broker, "_tool_choice", "") != "none":
            # TOOLS ARE DECLARED AND NOT CALLABLE, ON PURPOSE.
            #
            # ``tool_choice: auto`` is the shipped default, and the pilot showed
            # what it does to a narration bench on a host with no robot: the
            # model reaches for ``navigate_to`` on the FIRST owner turn, the
            # broker answers ``status=dropped`` (no sim socket, no doors), the
            # lane injects a result beat, and every reply is then about the
            # dropped request.  Three of five pilot turns were lost that way.
            #
            # ``none`` keeps the ENUM in the session — which is the whole point
            # of H-MB1c, and the QEV-1 lesson: the model must be told what body
            # it has — while making every proposed act appear as SPEECH, which
            # is exactly the surface MB-1's invented-action matcher scores.
            broker._tool_choice = "none"
            self.tool_choice = "none"

    def inject_item(self, *, role: str, text: str, purpose: str) -> int:
        lane = self.lane
        if lane is None or not lane.active:
            # No open session yet: the item is held and goes up with the first
            # owner turn's session, which is the honest ordering — a research
            # harness may not open a paid session just to inject context.
            self._pending = getattr(self, "_pending", [])
            self._pending.append((role, text, purpose))
            return max(1, round(len(text) / 4))
        lane._send_item(role=role, text=text, purpose=purpose)
        self.items_sent += 1
        tokens = max(1, round(len(text) / 4))
        self.injected_tokens += tokens
        return tokens

    def _flush_pending(self) -> None:
        pending = getattr(self, "_pending", [])
        lane = self.lane
        if not pending or lane is None or not lane.active:
            return
        for role, text, purpose in pending:
            lane._send_item(role=role, text=text, purpose=purpose)
            self.items_sent += 1
            self.injected_tokens += max(1, round(len(text) / 4))
        self._pending = []

    def owner_turn(self, text: str) -> RobotReply | None:
        from parcel_robot.realtime.hosted_budget import HostedCallRefused

        start = time.perf_counter()
        try:
            self.runtime.submit_realtime_text(text)
        except HostedCallRefused as refusal:
            self.refusals.append(
                {"purpose": "owner turn", "decision": refusal.decision.as_dict()}
            )
            return None
        self.response_creates += 1
        self._flush_pending()
        return self._await_reply(start)

    def trigger_response(self) -> RobotReply | None:
        from parcel_robot.realtime.protocol import ResponseCreate

        lane = self.lane
        if lane is None or not lane.active:
            return None
        if not self._require("MB-1 trigger-table response"):
            return None
        start = time.perf_counter()
        lane._send(ResponseCreate())
        self.response_creates += 1
        return self._await_reply(start)

    def _await_reply(self, start: float, *, timeout_s: float = 75.0) -> RobotReply | None:
        """Pump until the response settles, sampling the transcript as it grows.

        The sampled growth IS the delta stream amendment M6 asks the premature
        check to run on: ``_response_speech`` is appended to by
        ``response.output_audio_transcript.delta`` (lane.py:2244), so polling it
        gives every partial with the wall-clock offset at which it appeared.
        """

        lane = self.lane
        deadline = time.monotonic() + timeout_s
        first_at: float | None = None
        deltas: list[tuple[float, str]] = []
        seen = ""
        settled_at: float | None = None
        while time.monotonic() < deadline:
            lane.pump()
            grown = "".join(lane._response_speech)
            if grown != seen:
                deltas.append((time.perf_counter() - start, grown[len(seen):]))
                if first_at is None:
                    first_at = time.perf_counter()
                seen = grown
            # The DRIVER thread pumps this lane too, and it clears
            # ``_response_speech`` inside ``_on_response_done`` (lane.py:3502).
            # On a fast turn it wins the race and ``seen`` stays empty, which
            # cost the full 6 s patience floor on EVERY turn — measured at ~8 s
            # per response against a provider answering in ~3.  The ledger tap
            # is the other, authoritative witness that text arrived.
            heard = bool(seen) or bool(self.ledger is not None and self.ledger.rows)
            waited = time.monotonic() - (deadline - timeout_s)
            if lane._responses_pending == 0 and (heard or waited > 6.0):
                if settled_at is None:
                    settled_at = time.monotonic()
                elif time.monotonic() - settled_at > 0.8:
                    break
            else:
                settled_at = None
            time.sleep(0.02)
        lane.pump()
        rows = self.ledger.take_robot() if self.ledger is not None else []
        text = " ".join(t for _at, t in rows).strip() or seen.strip()
        usage = list(getattr(lane, "cost_rows", []) or [])
        if usage:
            self.usage_rows.append(dict(usage[-1]))
        return RobotReply(
            text=text,
            ttft_ms=round((first_at - start) * 1000, 3) if first_at else None,
            total_ms=round((time.perf_counter() - start) * 1000, 3),
            deltas=deltas,
        )

    def close(self) -> None:
        """One session per scenario, closed here (amendment M5, clause d).

        The DRIVER is stopped with it.  Left running it keeps pumping the lane
        across the hang-up and into the next session, and the first replies of
        the next scenario are consumed on its thread before this backend starts
        watching — measured, three scenarios in a row, in the second pilot.
        ``submit_realtime_text`` restarts it on the next owner turn.
        """

        driver = self.runtime.realtime_driver
        if driver is not None and driver.running:
            try:
                driver.stop()
            except Exception as error:  # noqa: BLE001 - teardown never raises here
                print(f"[hosted] driver stop: {type(error).__name__}: {error}")
        lane = self.lane
        if lane is not None:
            self.last_session_id = str(lane.session_id or "")
            lane.close()
        self._pending = []
        time.sleep(0.2)

    def spend_usd(self) -> float:
        ledger = self.runtime._realtime_spend_ledger
        if ledger is None:
            return 0.0
        return float(ledger.month_to_date(force=True).usd)


class _CaptureLedger:
    """The lane's own ledger hook, used as a transcript tap.

    ``lane._on_robot_transcript`` clears ``_response_speech`` inside
    ``_on_response_done`` (lane.py:3502), so reading that attribute after a turn
    returns nothing.  ``_write_ledger`` is the seam the product itself uses to
    record both halves of every hosted turn, and a ledger that only remembers is
    the least invasive tap there is.  ``delegate`` keeps the runtime's real
    conversation store working underneath.
    """

    def __init__(self, delegate: object | None = None) -> None:
        self.delegate = delegate
        self.rows: list[tuple[float, str, str]] = []

    def write_realtime_turn(self, *, session_id, speaker, text, origin,
                            provider_item_id=None) -> int:
        self.rows.append((time.perf_counter(), str(speaker), str(text)))
        delegate = self.delegate
        if delegate is not None:
            try:
                return delegate.write_realtime_turn(
                    session_id=session_id, speaker=speaker, text=text,
                    origin=origin, provider_item_id=provider_item_id,
                )
            except Exception:  # noqa: BLE001 - a tap never kills a turn
                return 0
        return 0

    def take_robot(self) -> list[tuple[float, str]]:
        out = [(at, text) for at, speaker, text in self.rows if speaker == "robot"]
        self.rows = []
        return out


class _DiscardSink:
    first_chunk_started_monotonic = None

    def begin_utterance(self) -> None: ...
    def enqueue(self, chunk: bytes, token: object = None) -> None: ...
    def interrupt(self) -> None: ...
    def enqueued_ms(self) -> float:
        return 0.0
    def played_ms(self) -> float:
        return 0.0


COMPANION_PERSONA = (
    "You are the voice of a small four-legged robot dog that lives with its "
    "owner. You are warm, brief and concrete. You only ever describe things "
    "your own systems have reported to you."
)


# ------------------------------------------------------------------ driver
#: A receipt this close behind an owner turn is that turn's OWN receipt: the
#: executive accepted while the owner was still finishing the sentence.  It is
#: injected BEFORE the voice answers, and the answer carries the
#: acknowledgement — amendment M3, row (i), read at its tightest.
IMMEDIATE_RECEIPT_S = 0.6


def run_scenario(scenario, backend, *, arm: str, sample: int, bands: dict) -> list[sc.Turn]:
    """Walk one scenario through one arm and return the transcript turns.

    ORDERING, WHICH IS THE WHOLE OF AMENDMENT M3
    --------------------------------------------
    The plan-queue item is UNBILLED and is consumed when a response is next
    created.  So a receipt that belongs to the owner's own sentence (the
    executive accepting it, 0.3 s later) is injected BEFORE that sentence's
    reply is asked for, and the reply is stamped at the receipt's time.  That is
    row (i): "acknowledgement on the next owner turn".

    Row (ii) is the trigger-table response: a receipt with no owner turn behind
    it (an arrival, a block, a failure) earns exactly one ``response.create``
    of its own, through the same band discipline the product whisperer uses.

    Arm D takes the identical shape with the product's own sentences, and gets
    the product's own floor gate for free: a narration that lands while the
    owner is owed an answer is not spoken twice — ``narrate_event`` returns
    False on ``_responses_pending > 0`` (lane.py:1968), which is exactly what
    "inject, do not trigger" reproduces here.
    """

    turns: list[sc.Turn] = []
    index = 0
    backend.open_session(scenario)
    pq = nr.PlanQueueWhisperer(
        max_updates_per_minute=bands["max_updates_per_minute"],
        min_gap_s=bands["min_gap_s"],
    )
    dw = nr.ProductWhisperArm.build(
        max_updates_per_minute=bands["max_updates_per_minute"],
        min_gap_s=bands["min_gap_s"],
    )
    queue: tuple[ev.QueueRecord, ...] = ()
    folded: list[dict[str, object]] = []

    def _record(role, text, at_s, reply=None, trigger="") -> None:
        nonlocal index
        turns.append(
            sc.Turn(
                scenario_id=scenario.scenario_id,
                arm=arm,
                turn_index=index,
                role=role,
                text=text,
                at_s=at_s,
                events_so_far=sc.events_so_far(scenario, at_s),
                trigger_event_id=trigger,
                ttft_ms=None if reply is None else reply.ttft_ms,
                total_ms=None if reply is None else reply.total_ms,
                deltas=[] if reply is None else list(reply.deltas),
                sample=sample,
            )
        )
        index += 1

    def _inject(receipt, *, allow_trigger: bool):
        """Refresh the context for one receipt.  Returns a reply, or None."""

        if arm.startswith("Q"):
            decision = pq.decide(receipt)
            speak = decision.speak and allow_trigger
            if decision.speak and not allow_trigger:
                folded.append(
                    {"receipt": receipt.event_id, "rule": "folded_into_the_owner_turn"}
                )
            item = pq.refresh(
                queue,
                last_receipt=receipt,
                now=receipt.t,
                speech_act=decision.speech_act if decision.speak else "",
            )
            backend.inject_item(role="system", text=item.text, purpose=nr.PURPOSE_PLAN_QUEUE)
            if speak:
                return backend.trigger_response()
            return None
        from parcel_robot.realtime.lane import ITEM_PURPOSE_NARRATION

        reply = None
        for row in dw.on_receipt(receipt):
            if not row.get("forwarded"):
                continue
            text = str(row.get("text") or "")
            if not text:
                continue
            backend.inject_item(role="system", text=text, purpose=ITEM_PURPOSE_NARRATION)
            if allow_trigger:
                reply = backend.trigger_response()
            else:
                folded.append(
                    {"receipt": receipt.event_id, "rule": "lane_floor_gate_owner_owed"}
                )
        return reply

    steps = list(scenario.steps)
    cursor = 0
    try:
        while cursor < len(steps):
            step = steps[cursor]
            if isinstance(step, ev.Receipt):
                queue = step.queue
                reply = _inject(step, allow_trigger=True)
                if reply is not None and reply.text:
                    _record("robot", reply.text, step.t, reply, step.event_id)
                cursor += 1
                continue

            if arm.startswith("Q"):
                decision = st.steer(step.text, queue)
                if decision.decision == ev.STEER_CLARIFY:
                    item = pq.refresh(
                        queue,
                        last_receipt=None,
                        now=step.t,
                        speech_act=nr.TRIGGER_TABLE["clarify"][1],
                    )
                    backend.inject_item(
                        role="system", text=item.text, purpose=nr.PURPOSE_PLAN_QUEUE
                    )
            _record("owner", step.text, step.t)

            reply_at = step.t + 0.01
            ahead = cursor + 1
            trigger_id = ""
            while (
                ahead < len(steps)
                and isinstance(steps[ahead], ev.Receipt)
                and steps[ahead].t <= step.t + IMMEDIATE_RECEIPT_S
            ):
                receipt = steps[ahead]
                queue = receipt.queue
                _inject(receipt, allow_trigger=False)
                reply_at = receipt.t + 0.01
                trigger_id = receipt.event_id
                ahead += 1

            reply = backend.owner_turn(step.text)
            if reply is not None and reply.text:
                _record("robot", reply.text, reply_at, reply, trigger_id)
            cursor = ahead
    finally:
        backend.close()
    backend.last_plan_queue = pq
    backend.last_product_whisper = dw
    backend.last_folded = folded
    return turns


# ------------------------------------------------------------------ stages
def _bands_from_config(config) -> dict:
    whisperer = getattr(config, "whisperer", None)
    return {
        "max_updates_per_minute": int(getattr(whisperer, "max_updates_per_minute", 2)),
        "min_gap_s": float(getattr(whisperer, "min_gap_s", 15.0)),
    }


def _load_realtime_config():
    from parcel_robot.realtime.config import load_realtime_config

    return load_realtime_config(WAVE_REALTIME_CONFIG)


def stage_fake(corpus, registry, *, seed: int, samples: int = 1) -> dict:
    config = _load_realtime_config()
    bands = _bands_from_config(config)
    results: list[sc.ScenarioResult] = []
    wire: dict[str, object] = {}
    for arm in ("Q", "D"):
        for sample in range(samples):
            for scenario in corpus:
                backend = ScriptedBackend(config)
                turns = run_scenario(scenario, backend, arm=arm, sample=sample, bands=bands)
                results.append(sc.score_scenario(scenario, turns, registry, sample=sample))
                row = wire.setdefault(
                    arm,
                    {"items": 0, "response_creates": 0, "plan_queue_refreshes": 0,
                     "plan_queue_tokens_approx": 0, "folded": 0},
                )
                row["items"] += backend.items_sent
                row["response_creates"] += backend.response_creates
                pq = getattr(backend, "last_plan_queue", None)
                if pq is not None:
                    row["plan_queue_refreshes"] += pq.revision
                    row["plan_queue_tokens_approx"] += pq.injected_tokens
                row["folded"] += len(getattr(backend, "last_folded", []) or [])
    return {"results": results, "bands": bands, "wire": wire}


def stage_local(corpus, registry, *, seed: int, model: str, samples: int = 1) -> dict:
    config = _load_realtime_config()
    bands = _bands_from_config(config)
    results: list[sc.ScenarioResult] = []
    for arm in ("Q-local", "D-local"):
        for sample in range(samples):
            for scenario in corpus:
                backend = LocalBackend(f"http://127.0.0.1:{LOCAL_PORT}", model)
                turns = run_scenario(scenario, backend, arm=arm, sample=sample, bands=bands)
                results.append(sc.score_scenario(scenario, turns, registry, sample=sample))
    return {"results": results, "bands": bands}


def build_hosted_runtime():
    """The product runtime, asserting a governor exists before paid work."""

    os.environ["PARCEL_REALTIME_CONFIG"] = str(WAVE_REALTIME_CONFIG)
    os.environ["PARCEL_REALTIME_SPEND_LEDGER"] = str(WAVE_LEDGER)
    os.environ.setdefault(
        "PARCEL_MEMORY_PATH", str(CACHE / "scratch/mb1_memory.sqlite3")
    )
    os.environ.setdefault("PARCEL_MEMORY_PURPOSE", "research")
    from parcel_robot.realtime.ear_gate import EarGateConfig
    from parcel_robot.realtime.hosted_budget import HostedCallGovernor
    from parcel_robot.web_panel import build_runtime

    runtime = build_runtime(
        WAVE_ROBOT_CONFIG, CACHE / "scratch/no-sim.sock", use_llm=False
    )
    if str(runtime._realtime_spend_note) != str(WAVE_LEDGER):
        raise RuntimeError(
            "the runtime's spend ledger is not the wave ledger: "
            f"{runtime._realtime_spend_note!r}"
        )
    if runtime.realtime_governor is None:
        section = runtime.store.section("audio")
        block = section.get("ear") if isinstance(section, dict) else None
        config = EarGateConfig.from_mapping(block)
        ledger = runtime._realtime_spend_ledger
        runtime.realtime_governor = HostedCallGovernor(
            config=config.governor,
            month_to_date=None if ledger is None else ledger.month_to_date,
            day_to_date=None if ledger is None else ledger.day_to_date,
            on_event=lambda message: print(f"[governor] {message}"),
        )
        runtime._mb1_governor_attached_by_harness = True
    return runtime


def _ledger_evidence(path: Path = WAVE_LEDGER) -> dict[str, object]:
    """Append-only ledger evidence at one checkpoint boundary."""

    raw = path.read_bytes() if path.exists() else b""
    rows = [json.loads(line) for line in raw.decode("utf-8").splitlines() if line]
    return {
        "path": str(path),
        "bytes": len(raw),
        "rows": len(rows),
        "estimated_usd": round(
            sum(float(row.get("estimated_usd", 0.0)) for row in rows), 8
        ),
        "sha256": hashlib.sha256(raw).hexdigest(),
    }


def _source_evidence() -> dict[str, str]:
    return {
        name: hashlib.sha256((FOLDER / name).read_bytes()).hexdigest()
        for name in ("events.py", "narrate.py", "scorer.py", "steer.py")
    }


def _hosted_fingerprint(
    corpus, *, seed: int, cap_usd: float, samples: int, arms: tuple[str, ...]
) -> tuple[str, dict[str, object]]:
    config = {
        "run_id": RUN_ID,
        "seed": seed,
        "cap_usd_absolute_wave_ledger": float(cap_usd),
        "samples": samples,
        "arms": list(arms),
        "scenario_ids": [scenario.scenario_id for scenario in corpus],
        "realtime_config_sha256": hashlib.sha256(
            WAVE_REALTIME_CONFIG.read_bytes()
        ).hexdigest(),
        "robot_config_sha256": hashlib.sha256(WAVE_ROBOT_CONFIG.read_bytes()).hexdigest(),
        "source_sha256": _source_evidence(),
    }
    return _sha256(config), config


def _atomic_json(path: Path, payload: dict[str, object]) -> None:
    """Durable replace: a crash leaves either the old or the new JSON."""

    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        with tmp.open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, ensure_ascii=False, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
        directory_fd = os.open(path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        if tmp.exists():
            tmp.unlink()


def _entry_digest(entry: dict[str, object]) -> str:
    return _sha256({k: v for k, v in entry.items() if k != "entry_sha256"})


def _read_hosted_checkpoint(
    path: Path, *, fingerprint: str, config: dict[str, object], resume: bool
) -> dict[str, object]:
    if not path.exists():
        checkpoint: dict[str, object] = {
            "schema": HOSTED_CHECKPOINT_SCHEMA,
            "fingerprint": fingerprint,
            "config": config,
            "created_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "updated_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "ledger_before": _ledger_evidence(),
            "completed": [],
            "incomplete": [],
        }
        _atomic_json(path, checkpoint)
        return checkpoint
    if not resume:
        raise RuntimeError(
            f"hosted checkpoint already exists at {path}; pass --hosted-resume "
            "to prove intentional reuse instead of duplicating paid calls"
        )
    checkpoint = json.loads(path.read_text(encoding="utf-8"))
    if checkpoint.get("schema") != HOSTED_CHECKPOINT_SCHEMA:
        raise ValueError("hosted checkpoint schema mismatch")
    if checkpoint.get("fingerprint") != fingerprint or checkpoint.get("config") != config:
        raise ValueError("hosted checkpoint does not match this frozen schedule/config")
    seen: set[str] = set()
    for entry in checkpoint.get("completed", []):
        if not isinstance(entry, dict) or entry.get("entry_sha256") != _entry_digest(entry):
            raise ValueError("hosted checkpoint completed-entry digest mismatch")
        key = str(entry.get("key", ""))
        if not key or key in seen:
            raise ValueError(f"hosted checkpoint duplicate/empty completed key {key!r}")
        seen.add(key)
    for entry in checkpoint.get("incomplete", []):
        if not isinstance(entry, dict) or entry.get("entry_sha256") != _entry_digest(entry):
            raise ValueError("hosted checkpoint incomplete-entry digest mismatch")
    return checkpoint


def _checkpoint_save(path: Path, checkpoint: dict[str, object]) -> None:
    checkpoint["updated_utc"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    _atomic_json(path, checkpoint)


def _checkpoint_result(
    entry: dict[str, object], *, scenarios: dict[str, object], registry
) -> sc.ScenarioResult:
    scenario_id = str(entry["scenario_id"])
    scenario = scenarios.get(scenario_id)
    if scenario is None:
        raise ValueError(f"checkpoint names unknown scenario {scenario_id!r}")
    turns = [_turn_from_checkpoint(dict(row)) for row in entry["turns"]]
    arm, sample = str(entry["arm"]), int(entry["sample"])
    if any(
        turn.scenario_id != scenario_id or turn.arm != arm or turn.sample != sample
        for turn in turns
    ):
        raise ValueError(f"checkpoint turn metadata mismatch for {entry['key']}")
    return sc.score_scenario(scenario, turns, registry, sample=sample)


def _completed_key(arm: str, sample: int, scenario_id: str) -> str:
    return f"{arm}:{sample}:{scenario_id}"


def stage_hosted(
    corpus,
    registry,
    *,
    seed: int,
    cap_usd: float,
    samples: int,
    arms: tuple[str, ...],
    checkpoint_path: Path,
    resume: bool,
    retry_incomplete: bool = False,
    runtime_factory: Callable[[], object] = build_hosted_runtime,
    backend_factory: Callable[..., object] = HostedBackend,
) -> dict:
    fingerprint, frozen_config = _hosted_fingerprint(
        corpus, seed=seed, cap_usd=cap_usd, samples=samples, arms=arms
    )
    checkpoint = _read_hosted_checkpoint(
        checkpoint_path, fingerprint=fingerprint, config=frozen_config, resume=resume
    )
    scenario_by_id = {scenario.scenario_id: scenario for scenario in corpus}
    results: list[sc.ScenarioResult] = [
        _checkpoint_result(entry, scenarios=scenario_by_id, registry=registry)
        for entry in checkpoint.get("completed", [])
    ]
    completed = {str(entry["key"]) for entry in checkpoint.get("completed", [])}
    config = _load_realtime_config()
    bands = _bands_from_config(config)
    incomplete_keys = {
        str(entry.get("key", "")) for entry in checkpoint.get("incomplete", [])
    }
    if incomplete_keys and not retry_incomplete:
        return {
            "results": results,
            "bands": bands,
            "status": "PARTIAL_INCOMPLETE_NEEDS_OVERRIDE",
            "reason": (
                "a prior attempt spent calls inside an incomplete scenario; refusing "
                "to duplicate them without --hosted-retry-incomplete"
            ),
            "checkpoint": str(checkpoint_path),
            "checkpoint_sha256": hashlib.sha256(checkpoint_path.read_bytes()).hexdigest(),
            "completed_scenarios": len(completed),
            "expected_scenarios": len(corpus) * samples * len(arms),
            "provenance_counts": {
                provenance: sum(
                    1
                    for entry in checkpoint.get("completed", [])
                    if entry.get("provenance", "exact_checkpoint") == provenance
                )
                for provenance in sorted(
                    {
                        str(entry.get("provenance", "exact_checkpoint"))
                        for entry in checkpoint.get("completed", [])
                    }
                )
            },
            "incomplete_keys": sorted(incomplete_keys),
            "ledger": _ledger_evidence(),
        }

    runtime = runtime_factory()
    governor = runtime.realtime_governor
    opening = governor.snapshot()
    print("[hosted] governor snapshot BEFORE the first call:")
    print(json.dumps(opening, indent=2))
    if not opening.get("month_readable"):
        return {
            "results": [],
            "status": "UNMEASURED",
            "reason": "the wave ledger does not read as a number; refuse_when_unknown "
            "would refuse every call",
            "governor_before": opening,
        }
    refusals: list[dict[str, object]] = []
    stopped = ""
    stop_status = ""
    backend = backend_factory(runtime, cap_usd=cap_usd, ledger_path=WAVE_LEDGER)
    spend_trace: list[dict[str, object]] = [
        {
            "arm": entry["arm"],
            "sample": entry["sample"],
            "scenario_id": entry["scenario_id"],
            "month_to_date_usd": entry["ledger_after"]["estimated_usd"],
            "provenance": entry.get("provenance", "exact_checkpoint"),
        }
        for entry in checkpoint.get("completed", [])
    ]
    try:
        for arm in arms:
            for sample in range(samples):
                for scenario in corpus:
                    key = _completed_key(arm, sample, scenario.scenario_id)
                    if key in completed:
                        continue
                    spent = backend.spend_usd()
                    if spent >= cap_usd:
                        stopped = (
                            f"local sub-cap reached: ${spent:.4f} >= ${cap_usd:.2f} "
                            f"at arm {arm} sample {sample} {scenario.scenario_id}"
                        )
                        raise _CapReached(stopped)
                    ledger_before = _ledger_evidence()
                    try:
                        turns = run_scenario(
                            scenario, backend, arm=arm, sample=sample, bands=bands
                        )
                    except Exception as error:
                        from parcel_robot.realtime.ws_transport import RealtimeQuotaError

                        if not isinstance(error, RealtimeQuotaError):
                            raise
                        ledger_after = _ledger_evidence()
                        incomplete = {
                            "key": key,
                            "arm": arm,
                            "sample": sample,
                            "scenario_id": scenario.scenario_id,
                            "reason": "provider_quota",
                            "error": _safe_provider_error(error),
                            "ledger_before": ledger_before,
                            "ledger_after": ledger_after,
                            "recorded_utc": time.strftime(
                                "%Y-%m-%dT%H:%M:%SZ", time.gmtime()
                            ),
                        }
                        incomplete["entry_sha256"] = _entry_digest(incomplete)
                        checkpoint.setdefault("incomplete", []).append(incomplete)
                        _checkpoint_save(checkpoint_path, checkpoint)
                        stopped = f"provider quota at {key}: {_safe_provider_error(error)}"
                        stop_status = "PARTIAL_QUOTA"
                        raise _QuotaReached(stopped) from error
                    ledger_after = _ledger_evidence()
                    if turns:
                        result = sc.score_scenario(
                            scenario, turns, registry, sample=sample
                        )
                        results.append(result)
                    entry = {
                        "key": key,
                        "arm": arm,
                        "sample": sample,
                        "scenario_id": scenario.scenario_id,
                        "session_id": backend.last_session_id,
                        "provenance": "exact_checkpoint",
                        "turns": [_turn_as_checkpoint(turn) for turn in turns],
                        "ledger_before": ledger_before,
                        "ledger_after": ledger_after,
                        "recorded_utc": time.strftime(
                            "%Y-%m-%dT%H:%M:%SZ", time.gmtime()
                        ),
                    }
                    entry["entry_sha256"] = _entry_digest(entry)
                    checkpoint.setdefault("completed", []).append(entry)
                    checkpoint["incomplete"] = [
                        prior
                        for prior in checkpoint.get("incomplete", [])
                        if prior.get("key") != key
                    ]
                    completed.add(key)
                    _checkpoint_save(checkpoint_path, checkpoint)
                    spend_trace.append(
                        {
                            "arm": arm,
                            "sample": sample,
                            "scenario_id": scenario.scenario_id,
                            "month_to_date_usd": ledger_after["estimated_usd"],
                            "provenance": "exact_checkpoint",
                        }
                    )
    except _CapReached:
        stop_status = "PARTIAL_CAP"
    except _QuotaReached:
        pass
    finally:
        refusals = list(backend.refusals)
        closing = governor.snapshot()
        try:
            runtime.close()
        except Exception as error:  # noqa: BLE001 - teardown never raises here
            print(f"[hosted] runtime close: {type(error).__name__}: {error}")
    print("[hosted] governor snapshot AFTER the last call:")
    print(json.dumps(closing, indent=2))
    return {
        "results": results,
        "bands": bands,
        "status": stop_status or ("MEASURED" if results else "UNMEASURED"),
        "stopped": stopped,
        "refusals": refusals,
        "governor_before": opening,
        "governor_after": closing,
        "spend_trace": spend_trace,
        "checkpoint": str(checkpoint_path),
        "checkpoint_sha256": hashlib.sha256(checkpoint_path.read_bytes()).hexdigest(),
        "completed_scenarios": len(completed),
        "expected_scenarios": len(corpus) * samples * len(arms),
        "provenance_counts": {
            provenance: sum(
                1
                for entry in checkpoint.get("completed", [])
                if entry.get("provenance", "exact_checkpoint") == provenance
            )
            for provenance in sorted(
                {
                    str(entry.get("provenance", "exact_checkpoint"))
                    for entry in checkpoint.get("completed", [])
                }
            )
        },
        "governor_attached_by_harness": bool(
            getattr(runtime, "_mb1_governor_attached_by_harness", False)
        ),
    }


class _CapReached(RuntimeError):
    pass


class _QuotaReached(RuntimeError):
    pass


# ------------------------------------------------------- local model server
def start_local_server(log_path: Path) -> subprocess.Popen | None:
    if not LOCAL_MODEL.exists():
        print(f"[local] no GGUF at {LOCAL_MODEL}; the local row is UNMEASURED")
        return None
    if not LLAMA_SERVER.exists():
        print(f"[local] no llama-server at {LLAMA_SERVER}; the local row is UNMEASURED")
        return None
    free = _gpu_free_mib()
    if free is not None and free < 12_000:
        print(f"[local] only {free} MiB free on the GPU (< 12 GB); refusing to start")
        return None
    log_path.parent.mkdir(parents=True, exist_ok=True)
    handle = log_path.open("w", encoding="utf-8")
    process = subprocess.Popen(
        [
            str(LLAMA_SERVER),
            "--model", str(LOCAL_MODEL),
            "--alias", "mb1-qwen2.5-7b-instruct",
            "--host", "127.0.0.1",
            "--port", str(LOCAL_PORT),
            "--ctx-size", "8192",
            "--n-gpu-layers", "99",
            "--threads", "16",
            "--no-webui",
        ],
        stdout=handle,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    deadline = time.monotonic() + 300
    while time.monotonic() < deadline:
        if process.poll() is not None:
            print("[local] llama-server died during startup; see the log")
            return None
        try:
            with urllib.request.urlopen(
                f"http://127.0.0.1:{LOCAL_PORT}/health", timeout=2
            ) as response:
                if response.status == 200:
                    print(f"[local] llama-server ready on :{LOCAL_PORT} (pid {process.pid})")
                    return process
        except (urllib.error.URLError, OSError):
            time.sleep(2)
    print("[local] llama-server never became healthy")
    stop_local_server(process)
    return None


def stop_local_server(process: subprocess.Popen | None) -> None:
    """Kill the process GROUP this harness started, on every exit path."""

    if process is None:
        return
    try:
        os.killpg(os.getpgid(process.pid), signal.SIGTERM)
    except (ProcessLookupError, PermissionError):
        return
    try:
        process.wait(timeout=20)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(os.getpgid(process.pid), signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass


def _gpu_free_mib() -> int | None:
    if shutil.which("nvidia-smi") is None:
        return None
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.free", "--format=csv,noheader,nounits"],
            capture_output=True,
            text=True,
            timeout=20,
            check=True,
        )
    except (subprocess.SubprocessError, OSError):
        return None
    return int(out.stdout.strip().splitlines()[0])


# --------------------------------------------------------------------- main
def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="MB-1 — Model B narration harness")
    parser.add_argument("--all", action="store_true", help="fake, then local, then hosted")
    parser.add_argument("--only", choices=["fake", "local", "hosted", "corpus"], default="")
    parser.add_argument("--seed", type=int, default=20260829)
    parser.add_argument("--hosted-cap-usd", type=float, default=3.0)
    parser.add_argument("--hosted-samples", type=int, default=3)
    parser.add_argument("--hosted-arms", default="Q,D")
    parser.add_argument(
        "--hosted-checkpoint",
        default="",
        help="atomic lossless per-scenario checkpoint (default: <output>.checkpoint.json)",
    )
    parser.add_argument(
        "--hosted-resume",
        action="store_true",
        help="resume an exactly matching hosted checkpoint and skip completed calls",
    )
    parser.add_argument(
        "--hosted-retry-incomplete",
        action="store_true",
        help="explicitly permit re-running a scenario that spent calls before failing; "
             "never implied by --hosted-resume",
    )
    parser.add_argument("--hosted-scenarios", type=int, default=0,
                        help="limit the hosted corpus to the first N (0 = all 40)")
    parser.add_argument("--hosted-per-family", type=int, default=0,
                        help="stratified hosted subset: N scenarios from EACH of the "
                             "8 families (0 = do not stratify)")
    parser.add_argument("--local-samples", type=int, default=1)
    parser.add_argument("--output", default=str(FOLDER / "results.json"))
    parser.add_argument(
        "--decisions", action="store_true",
        help="write the narration decision ledger (both arms, every receipt, "
             "forward/suppress + rule + injected tokens) and exit; model-free",
    )
    parser.add_argument(
        "--adjudicate", default="",
        help="path to a blind adjudication queue; runs the frozen-prompt LOCAL "
             "judge over it (report-only) and writes the adjudications",
    )
    parser.add_argument(
        "--merge", nargs="*", default=None,
        help="merge per-stage result files into one results.json and exit; the "
             "free stages are re-runnable at any time, the hosted one is not",
    )
    args = parser.parse_args(argv)

    if args.decisions:
        return _decisions(args.output)
    if args.merge is not None:
        return _merge(args.merge, args.output, seed=args.seed)
    if args.adjudicate:
        server = start_local_server(FOLDER / "logs/llama-server-judge.log")
        try:
            if server is None:
                print("[adjudicate] no local judge available; UNMEASURED")
                return 1
            summary = sc.adjudicate_blind(
                Path(args.adjudicate),
                base_url=f"http://127.0.0.1:{LOCAL_PORT}",
                model="mb1-qwen2.5-7b-instruct",
                output=Path(args.output),
            )
            print(json.dumps(summary, indent=2))
        finally:
            stop_local_server(server)
        return 0
    if os.environ.get("TMPDIR"):
        os.environ.pop("TMPDIR", None)
    os.environ["PARCEL_REALTIME_CONFIG"] = str(WAVE_REALTIME_CONFIG)
    os.environ["PARCEL_REALTIME_SPEND_LEDGER"] = str(WAVE_LEDGER)
    os.environ.setdefault("PARCEL_MEMORY_PATH", str(CACHE / "scratch/mb1_memory.sqlite3"))
    os.environ.setdefault("PARCEL_MEMORY_PURPOSE", "research")
    (CACHE / "scratch").mkdir(parents=True, exist_ok=True)

    stages = ["fake", "local", "hosted"] if args.all else ([args.only] if args.only else ["fake"])
    corpus = ev.build_corpus()
    registry = sc.default_registry()
    payload: dict[str, object] = {
        "run_id": RUN_ID,
        "seed": args.seed,
        "started_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "corpus": ev.corpus_summary(),
        "steer_self_test": st.self_test(),
        "capability_registry": registry.as_dict(),
        "keys_turn_pre_registration": ev.KEYS_TURN_BEHAVIOURS,
        "stages": {},
    }

    if "corpus" in stages:
        _write(args.output, payload)
        return 0

    all_results: list[sc.ScenarioResult] = []

    if "fake" in stages:
        print("[fake] 40 scenarios x arms Q,D through a real lane + scripted server")
        out = stage_fake(corpus, registry, seed=args.seed)
        all_results.extend(out["results"])
        payload["stages"]["fake"] = _summarise(
            out["results"], seed=args.seed, arms=("Q", "D"), tier="replay",
            extra={"bands": out["bands"], "wire": out["wire"],
                   "server": "parcel_robot.realtime.fake_server frames, dynamic responder"},
        )
        _write(args.output, payload)

    if "local" in stages:
        server = None
        try:
            server = start_local_server(FOLDER / "logs/llama-server-8093.log")
            if server is None:
                payload["stages"]["local"] = {
                    "status": "UNMEASURED",
                    "reason": "no local GGUF / llama-server / GPU headroom",
                }
            else:
                print("[local] 40 scenarios x arms Q-local,D-local")
                out = stage_local(
                    corpus, registry, seed=args.seed,
                    model="mb1-qwen2.5-7b-instruct", samples=args.local_samples,
                )
                all_results.extend(out["results"])
                payload["stages"]["local"] = _summarise(
                    out["results"], seed=args.seed, arms=("Q-local", "D-local"),
                    tier="replay",
                    extra={"bands": out["bands"], "model": LOCAL_MODEL.name,
                           "server": f"llama-server on :{LOCAL_PORT}"},
                )
        finally:
            stop_local_server(server)
            payload.setdefault("teardown", {})["local_server_stopped"] = True
        _write(args.output, payload)

    if "hosted" in stages:
        arms = tuple(a.strip() for a in args.hosted_arms.split(",") if a.strip())
        if args.hosted_per_family:
            picked: list = []
            for family, _builder in ev.FAMILIES:
                members = [s for s in corpus if s.family == family]
                picked.extend(members[: args.hosted_per_family])
            hosted_corpus = tuple(picked)
        elif args.hosted_scenarios:
            hosted_corpus = corpus[: args.hosted_scenarios]
        else:
            hosted_corpus = corpus
        out = stage_hosted(
            hosted_corpus, registry, seed=args.seed, cap_usd=args.hosted_cap_usd,
            samples=args.hosted_samples, arms=arms,
            checkpoint_path=(
                Path(args.hosted_checkpoint)
                if args.hosted_checkpoint
                else Path(args.output).with_suffix(".checkpoint.json")
            ),
            resume=args.hosted_resume,
            retry_incomplete=args.hosted_retry_incomplete,
        )
        all_results.extend(out["results"])
        summary = _summarise(
            out["results"], seed=args.seed, arms=arms, tier="hosted-live",
            extra={
                "status": out.get("status"),
                "stopped": out.get("stopped"),
                "refusals": out.get("refusals"),
                "governor_before": out.get("governor_before"),
                "governor_after": out.get("governor_after"),
                "spend_trace": out.get("spend_trace"),
                "governor_attached_by_harness": out.get("governor_attached_by_harness"),
                "bands": out.get("bands"),
                "checkpoint": out.get("checkpoint"),
                "checkpoint_sha256": out.get("checkpoint_sha256"),
                "completed_scenarios": out.get("completed_scenarios"),
                "expected_scenarios": out.get("expected_scenarios"),
                "provenance_counts": out.get("provenance_counts"),
                "reason": out.get("reason"),
                "incomplete_keys": out.get("incomplete_keys"),
            },
        )
        payload["stages"]["hosted"] = summary
        _write(args.output, payload)

    if all_results:
        # One transcript file PER STAGE, named after the output artifact, so a
        # later stage never overwrites an earlier one and CONV-1's bridge can be
        # pointed at the whole directory:
        #   bridge.py --transcripts research/20260829/model-b-narration-1/transcripts/
        stem = Path(args.output).stem
        transcripts = FOLDER / f"transcripts/{stem}.jsonl"
        rows = sc.write_conv1_transcripts(all_results, transcripts)
        queue = FOLDER / f"results/adjudication_queue-{stem}.jsonl"
        key = FOLDER / f"results/adjudication_key-{stem}.json"
        flags = sc.write_adjudication_queue(all_results, queue, key, seed=args.seed)
        payload["artifacts"] = {
            "conv1_transcripts": str(transcripts.relative_to(FOLDER)),
            "conv1_rows": rows,
            "adjudication_queue": str(queue.relative_to(FOLDER)),
            "adjudication_rows": flags,
            "adjudication_key": str(key.relative_to(FOLDER)),
        }
    payload["finished_utc"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    _write(args.output, payload)
    print(f"[done] {args.output}")
    return 0


def _decisions(output) -> int:
    """The narration decision ledger amendment M6 asks to be published.

    Model-free and deterministic: both arms' gates are pure functions of the
    receipt stream, so this can be regenerated at any time without re-spending
    a cent, and it is the row a reader checks when a turn is missing — which
    sentence was suppressed, and by which rule.
    """

    config = _load_realtime_config()
    bands = _bands_from_config(config)
    rows: list[dict[str, object]] = []
    q_totals: dict[str, int] = {}
    d_totals: dict[str, int] = {}
    q_tokens = 0
    q_refreshes = 0
    for scenario in ev.build_corpus():
        pq = nr.PlanQueueWhisperer(
            max_updates_per_minute=bands["max_updates_per_minute"],
            min_gap_s=bands["min_gap_s"],
        )
        dw = nr.ProductWhisperArm.build(
            max_updates_per_minute=bands["max_updates_per_minute"],
            min_gap_s=bands["min_gap_s"],
        )
        for receipt in scenario.receipts:
            decision = pq.decide(receipt)
            item = pq.refresh(
                receipt.queue,
                last_receipt=receipt,
                now=receipt.t,
                speech_act=decision.speech_act if decision.speak else "",
            )
            product = dw.on_receipt(receipt)
            key = f"{'forward' if decision.speak else 'suppress'}:{decision.rule}"
            q_totals[key] = q_totals.get(key, 0) + 1
            for prow in product:
                pkey = f"{'forward' if prow.get('forwarded') else 'suppress'}:{prow.get('rule')}"
                d_totals[pkey] = d_totals.get(pkey, 0) + 1
            rows.append(
                {
                    "scenario_id": scenario.scenario_id,
                    "receipt": receipt.event_id,
                    "fact": receipt.fact,
                    "narratable": receipt.narratable,
                    "arm_Q": {**decision.as_dict(), "item": item.as_dict()},
                    "arm_D": [
                        {k: v for k, v in prow.items() if k != "schema_version"}
                        for prow in product
                    ],
                }
            )
        q_tokens += pq.injected_tokens
        q_refreshes += pq.revision
    payload = {
        "decision_ledger_id": "mb1-narration-decisions-v1",
        "bands": bands,
        "arm_Q": {
            "trigger_table": {k: list(v) for k, v in nr.TRIGGER_TABLE.items()},
            "purpose_string": nr.PURPOSE_PLAN_QUEUE,
            "totals": dict(sorted(q_totals.items())),
            "refreshes": q_refreshes,
            "approx_tokens_total": q_tokens,
            "approx_tokens_per_refresh": round(q_tokens / q_refreshes, 1) if q_refreshes else 0,
        },
        "arm_D": {
            "mechanism": "product whisperer, runtime call sites",
            "totals": dict(sorted(d_totals.items())),
        },
        "rows": rows,
    }
    _write(output, payload)
    print(json.dumps({k: payload[k] for k in ("bands", "arm_Q", "arm_D")}, indent=2, default=str)[:2000])
    print(f"[decisions] {output}")
    return 0


def _merge(paths, output, *, seed: int) -> int:
    """Fold per-stage artifacts into one results.json.

    The stages are run separately here for two reasons a reader should not have
    to guess at: the free stages were re-run after each harness fix, and the
    hosted stage is metered — a re-run costs money, so it is never repeated to
    tidy up a JSON file.  ``--all`` runs all three in one process and produces
    the same shape.
    """

    merged: dict[str, object] = {"run_id": RUN_ID, "seed": seed, "merged_from": []}
    for raw in paths:
        path = Path(raw)
        payload = json.loads(path.read_text(encoding="utf-8"))
        merged["merged_from"].append(path.name)
        for key, value in payload.items():
            if key == "stages":
                stages = merged.setdefault("stages", {})
                for name, stage in value.items():
                    if name in stages:
                        stages[f"{name}:{path.stem}"] = stage
                    else:
                        stages[name] = stage
            elif key not in merged or key in {"finished_utc", "artifacts"}:
                merged[key] = value
    _write(output, merged)
    print(f"[merged] {output}")
    return 0


def _summarise(results, *, seed: int, arms, tier: str, extra: dict) -> dict:
    out: dict[str, object] = {"tier": tier, "arms": {}, **extra}
    for arm in arms:
        out["arms"][arm] = sc.aggregate(results, arm=arm, seed=seed)
    if len(arms) >= 2:
        q, d = arms[0], arms[1]
        qg = out["arms"][q].get("per_scenario_grounded", {})
        dg = out["arms"][d].get("per_scenario_grounded", {})
        point, lo, hi = sc.paired_delta_ci(qg, dg, seed=seed)
        qc = out["arms"][q].get("per_scenario_coverage", {})
        dc = out["arms"][d].get("per_scenario_coverage", {})
        cpoint, clo, chi = sc.paired_delta_ci(qc, dc, seed=seed)
        out["paired_delta"] = {
            "grounding_q_minus_d": point,
            "grounding_ci95": [lo, hi],
            "grounding_lower_bound_above_zero": lo > 0,
            "coverage_q_minus_d": cpoint,
            "coverage_ci95": [clo, chi],
        }
    return out


def _write(path: str | Path, payload: dict) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(
        json.dumps(payload, indent=2, ensure_ascii=False, default=str), encoding="utf-8"
    )


if __name__ == "__main__":
    raise SystemExit(main())
