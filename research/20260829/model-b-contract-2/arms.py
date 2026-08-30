"""MB-2 — the two arms: T (templates only) and T+P (template + local paraphrase).

ARM T
-----
MB-1's trigger table decides WHEN to speak (``arrived / blocked / failed /
clarify`` earn one response; ``accepted / running / resumed / queued /
cancelled`` are context and are acknowledged on the owner's next turn), gated by
MB-1's own band discipline.  The contract decides WHAT is said: the receipt is
mapped to a typed speech act with slots and the act is rendered by its template.
No model is involved at any point.

ARM T+P
-------
Identical, plus one local paraphrase per turn (Qwen2.5-7B-Instruct-Q4_K_M on
:8093, temperature 0.3, seed 20260829, ≤ 25 words, prompt frozen in
``prompts/paraphrase_v1.txt``).  The paraphrase is offered to the post-condition
checker; if the checker rejects it, the TEMPLATE is spoken instead and the
rejection reason is recorded.  The raw paraphrase is ALSO kept, unmodified, and
scored as a third, report-only shadow arm (``P-raw``) so a reader can see what
the checker actually caught rather than trusting that it caught something.

TURN ORDERING
-------------
Mirrors ``model-b-narration-1/run.py:run_scenario`` exactly, including
``IMMEDIATE_RECEIPT_S``: a receipt filed within 0.6 s behind an owner turn is
that turn's own receipt, is folded into the reply, and the reply is stamped at
the receipt's time.  MB-1's file is imported, never edited; the walk is
re-implemented here because MB-1's version is bound to its realtime backends and
MB-2 has no lane.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

import contract as ct
from mb1 import IMMEDIATE_RECEIPT_S, ev, nr, sc, st

ARM_T = "T"
ARM_TP = "T+P"
ARM_P_RAW = "P-raw"

_PENDING = frozenset({ev.QUEUE_QUEUED, ev.QUEUE_SUSPENDED})


def _block_class(detail: str) -> str:
    text = str(detail).lower()
    if "person" in text or "someone" in text or "somebody" in text:
        return ct.CLASS_PERSON
    return ct.CLASS_OBSTACLE


def _pending(queue: tuple[ev.QueueRecord, ...]) -> tuple[ev.QueueRecord, ...]:
    return tuple(record for record in queue if record.status in _PENDING)


def _record_for(receipt: ev.Receipt) -> ev.QueueRecord | None:
    for record in receipt.queue:
        if record.task_id == receipt.task_id:
            return record
    return None


@dataclass(frozen=True, slots=True)
class Utterance:
    """One turn's acts, its closing question and the template it renders to."""

    acts: tuple[ct.SpeechAct, ...]
    closing: str = ""

    @property
    def text(self) -> str:
        return ct.compose(self.acts, closing=self.closing)

    def as_dict(self) -> dict[str, object]:
        return {"acts": [a.as_dict() for a in self.acts], "closing": self.closing}


def acts_for_receipt(receipt: ev.Receipt) -> Utterance:
    """The act a SPOKEN receipt licenses (the trigger table has already fired)."""

    if receipt.fact == ev.FACT_COMPLETED:
        acts = [ct.SpeechAct(ct.ACT_COMPLETED, {"goal": receipt.goal})]
        pending = _pending(receipt.queue)
        if pending:
            acts.append(ct.SpeechAct(ct.ACT_RESUME_OFFER, {"goal": pending[0].goal}))
            return Utterance(tuple(acts))
        return Utterance(tuple(acts), ct.CLOSING_QUESTION)
    if receipt.fact == ev.FACT_BLOCKED:
        return Utterance(
            (
                ct.SpeechAct(
                    ct.ACT_BLOCKED,
                    {"goal": receipt.goal, "klass": _block_class(receipt.detail)},
                ),
            )
        )
    if receipt.fact == ev.FACT_FAILED:
        return Utterance(
            (
                ct.SpeechAct(
                    ct.ACT_FAILED,
                    {"goal": receipt.goal, "klass": _block_class(receipt.detail)},
                ),
            ),
            ct.CLOSING_QUESTION_FAILED,
        )
    if receipt.fact == ev.FACT_CANCELLED:
        return Utterance(
            (ct.SpeechAct(ct.ACT_CANCELLED, {"goal": receipt.goal}),), ct.CLOSING_QUESTION
        )
    if receipt.fact == ev.FACT_ACCEPTED:
        return _ack(receipt)
    if receipt.fact == ev.FACT_RESUMED:
        return Utterance((ct.SpeechAct(ct.ACT_RESUMED, {"goal": receipt.goal}),))
    return Utterance((ct.SpeechAct(ct.ACT_PROGRESS, {"goal": receipt.goal}),))


def _ack(receipt: ev.Receipt) -> Utterance:
    record = _record_for(receipt)
    queued = bool(record is not None and record.status == ev.QUEUE_QUEUED)
    return Utterance(
        (ct.SpeechAct(ct.ACT_ACK, {"goal": receipt.goal, "queued": queued}),)
    )


def acts_for_owner_turn(
    turn: ev.OwnerTurn,
    *,
    folded: tuple[ev.Receipt, ...],
    prior: tuple[ev.Receipt, ...],
    decision: st.SteerDecision,
) -> Utterance:
    """The reply to an owner turn: its own receipts, or an answer from the last.

    Three deterministic branches, in this order:

    1. the KEYS turn — a perception request this body cannot serve.  M8's
       pre-registered behaviour is arrival + explicit inability + an offer, and
       the contract says it with ``completed(goal)`` +
       ``capability_refusal(vision)`` + the closing question;
    2. an ungrounded referent — ``steer``'s clarify question, verbatim;
    3. the receipts folded into this turn, in order; and when there are none, an
       answer composed from the last terminal receipt (a cancellation, or a
       block the owner is asking about after it cleared).  When even that is
       empty the robot hands the floor back and claims nothing.
    """

    if turn.keys_turn:
        acts: list[ct.SpeechAct] = []
        arrived = [r for r in prior if r.fact == ev.FACT_COMPLETED]
        if arrived:
            acts.append(ct.SpeechAct(ct.ACT_COMPLETED, {"goal": arrived[-1].goal}))
        acts.append(ct.SpeechAct(ct.ACT_CAPABILITY_REFUSAL, {"keys": (ct.CAP_VISION,)}))
        return Utterance(tuple(acts), ct.CLOSING_QUESTION)

    if decision.decision == ev.STEER_CLARIFY:
        return Utterance(
            (ct.SpeechAct(ct.ACT_ASK_CLARIFY, {"question": decision.question}),)
        )

    if folded:
        acts = []
        for receipt in folded:
            if receipt.fact == ev.FACT_RUNNING:
                continue
            acts.extend(acts_for_receipt(receipt).acts)
        if acts:
            closing = (
                ct.CLOSING_QUESTION
                if any(a.act == ct.ACT_CANCELLED for a in acts)
                else ""
            )
            return Utterance(tuple(acts), closing)

    terminals = [
        r
        for r in prior
        if r.fact in {ev.FACT_COMPLETED, ev.FACT_FAILED, ev.FACT_CANCELLED}
    ]
    if terminals and terminals[-1].fact == ev.FACT_CANCELLED:
        return Utterance(
            (
                ct.SpeechAct(ct.ACT_CANCELLED, {"goal": terminals[-1].goal}),
                ct.SpeechAct(
                    ct.ACT_CAPABILITY_REFUSAL, {"keys": (ct.CAP_POSITION_REPORT,)}
                ),
            ),
            ct.CLOSING_QUESTION,
        )
    blocks = [r for r in prior if r.fact == ev.FACT_BLOCKED]
    if blocks and terminals:
        block = blocks[-1]
        return Utterance(
            (
                ct.SpeechAct(
                    ct.ACT_BLOCKED,
                    {
                        "goal": block.goal,
                        "klass": _block_class(block.detail),
                        "resolved": True,
                    },
                ),
            )
        )
    return Utterance((), ct.CLOSING_QUESTION)


@dataclass
class TurnRecord:
    """One robot turn as the contract produced it, before and after the gate."""

    scenario_id: str
    turn_index: int
    at_s: float
    trigger_event_id: str
    utterance: Utterance
    template: str
    candidate: str = ""
    spoken: str = ""
    check_template: ct.CheckResult | None = None
    check_candidate: ct.CheckResult | None = None
    fell_back: bool = False
    render_ms: float = 0.0
    check_ms: float = 0.0
    ttft_ms: float | None = None
    total_ms: float | None = None

    def as_dict(self) -> dict[str, object]:
        return {
            "scenario_id": self.scenario_id,
            "turn_index": self.turn_index,
            "at_s": round(self.at_s, 3),
            "trigger_event_id": self.trigger_event_id,
            "acts": self.utterance.as_dict(),
            "template": self.template,
            "candidate": self.candidate,
            "spoken": self.spoken,
            "template_check": None if self.check_template is None else self.check_template.as_dict(),
            "candidate_check": None
            if self.check_candidate is None
            else self.check_candidate.as_dict(),
            "fell_back": self.fell_back,
            "render_ms": round(self.render_ms, 4),
            "check_ms": round(self.check_ms, 4),
            "ttft_ms": self.ttft_ms,
            "total_ms": self.total_ms,
        }


def run_scenario(
    scenario: ev.Scenario,
    *,
    registry: object,
    bands: dict,
    paraphraser: object | None = None,
) -> tuple[list[sc.Turn], list[sc.Turn], list[sc.Turn], list[TurnRecord]]:
    """Walk one scenario.  Returns (T turns, T+P turns, P-raw turns, records).

    All three transcripts come from ONE walk, so the arms differ in the wording
    and in nothing else: same trigger decisions, same band ledger, same acts,
    same timestamps.  When ``paraphraser`` is None only the T list is populated.
    """

    t_turns: list[sc.Turn] = []
    tp_turns: list[sc.Turn] = []
    raw_turns: list[sc.Turn] = []
    records: list[TurnRecord] = []
    index = 0
    pq = nr.PlanQueueWhisperer(
        max_updates_per_minute=bands["max_updates_per_minute"],
        min_gap_s=bands["min_gap_s"],
    )
    queue: tuple[ev.QueueRecord, ...] = ()
    folded_log: list[dict[str, object]] = []

    def _turn(arm: str, role: str, text: str, at_s: float, record: TurnRecord | None) -> sc.Turn:
        return sc.Turn(
            scenario_id=scenario.scenario_id,
            arm=arm,
            turn_index=index,
            role=role,
            text=text,
            at_s=at_s,
            events_so_far=sc.events_so_far(scenario, at_s),
            trigger_event_id="" if record is None else record.trigger_event_id,
            ttft_ms=None if record is None else (record.render_ms if arm == ARM_T else record.ttft_ms),
            total_ms=None
            if record is None
            else ((record.render_ms + record.check_ms) if arm == ARM_T else record.total_ms),
            deltas=[],
            sample=0,
        )

    def _emit_owner(text: str, at_s: float) -> None:
        nonlocal index
        for bucket, arm in ((t_turns, ARM_T), (tp_turns, ARM_TP), (raw_turns, ARM_P_RAW)):
            if arm != ARM_T and paraphraser is None:
                continue
            bucket.append(_turn(arm, "owner", text, at_s, None))
        index += 1

    def _emit_robot(utterance: Utterance, at_s: float, trigger: str) -> None:
        nonlocal index
        start = time.perf_counter()
        template = utterance.text
        render_ms = (time.perf_counter() - start) * 1000.0
        start = time.perf_counter()
        template_check = ct.check(
            template,
            acts=utterance.acts,
            scenario=scenario,
            at_s=at_s,
            registry=registry,
            turn_index=index,
        )
        check_ms = (time.perf_counter() - start) * 1000.0
        record = TurnRecord(
            scenario_id=scenario.scenario_id,
            turn_index=index,
            at_s=at_s,
            trigger_event_id=trigger,
            utterance=utterance,
            template=template,
            spoken=template,
            check_template=template_check,
            render_ms=render_ms,
            check_ms=check_ms,
        )
        if paraphraser is not None:
            reply = paraphraser.paraphrase(utterance, template)
            record.candidate = reply.text
            record.ttft_ms = reply.ttft_ms
            record.total_ms = reply.total_ms
            start = time.perf_counter()
            candidate_check = ct.check(
                reply.text,
                acts=utterance.acts,
                scenario=scenario,
                at_s=at_s,
                registry=registry,
                turn_index=index,
            )
            record.check_ms += (time.perf_counter() - start) * 1000.0
            record.check_candidate = candidate_check
            record.fell_back = not candidate_check.ok
            record.spoken = reply.text if candidate_check.ok else template
        records.append(record)
        t_turns.append(_turn(ARM_T, "robot", template, at_s, record))
        if paraphraser is not None:
            tp_turns.append(_turn(ARM_TP, "robot", record.spoken, at_s, record))
            raw_turns.append(_turn(ARM_P_RAW, "robot", record.candidate or template, at_s, record))
        index += 1

    steps = list(scenario.steps)
    cursor = 0
    while cursor < len(steps):
        step = steps[cursor]
        if isinstance(step, ev.Receipt):
            queue = step.queue
            decision = pq.decide(step)
            if decision.speak:
                _emit_robot(acts_for_receipt(step), step.t, step.event_id)
            cursor += 1
            continue

        steer_decision = st.steer(step.text, queue)
        _emit_owner(step.text, step.t)

        reply_at = step.t + 0.01
        trigger_id = ""
        folded: list[ev.Receipt] = []
        ahead = cursor + 1
        while (
            ahead < len(steps)
            and isinstance(steps[ahead], ev.Receipt)
            and steps[ahead].t <= step.t + IMMEDIATE_RECEIPT_S
        ):
            receipt = steps[ahead]
            queue = receipt.queue
            decision = pq.decide(receipt)
            if decision.speak:
                folded_log.append(
                    {"receipt": receipt.event_id, "rule": "folded_into_the_owner_turn"}
                )
            folded.append(receipt)
            reply_at = receipt.t + 0.01
            trigger_id = receipt.event_id
            ahead += 1

        prior = tuple(r for r in scenario.receipts if r.t <= reply_at + 1e-9)
        utterance = acts_for_owner_turn(
            step, folded=tuple(folded), prior=prior, decision=steer_decision
        )
        _emit_robot(utterance, reply_at, trigger_id)
        cursor = ahead

    return t_turns, tp_turns, raw_turns, records


__all__ = [
    "ARM_P_RAW",
    "ARM_T",
    "ARM_TP",
    "TurnRecord",
    "Utterance",
    "acts_for_owner_turn",
    "acts_for_receipt",
    "run_scenario",
]
