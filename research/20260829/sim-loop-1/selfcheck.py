"""LIT-1 self-check — the amendment claims that do NOT need a simulator.

Four of this experiment's binding amendments are claims about code paths, not
about a robot, and a reader should not have to run a two-minute MuJoCo episode
to see whether they hold:

* **L1** — the plan-queue whisper is an UNBILLED tail conversation item with its
  own purpose tag, replace-not-append, and no ``response.create``.  Checked at
  the WIRE, against the frames the product's own ``RealtimeLane`` actually sent
  through a ``FakeRealtimeServer`` transport.
* **L7** — "yes" resumes nothing by itself; the closed RESUME set is {resume,
  continue, keep going, carry on}; a confirmation is a re-issue trigger only
  against an open offer.
* **L9** — the turn predicate fires on three consecutive 100 ms samples with
  ``|vyaw| > 0.1`` and a falling heading error, and does not fire otherwise.
* **L4** — the name scan is a POSITIVE allowlist and redacts what is not on it.
* **L7 / MB-1 M7 (card C7)** — the post-terminal offer is TYPED BY THE RECEIPT:
  only ``task_succeeded`` may carry an arrival phrase; a failed / blocked /
  cancelled / missing terminal opens with that receipt's own kind and drops the
  scripted arrival sentence, keeping the capability refusal and the offer.

Run: ``.parcel/bin/python research/20260829/sim-loop-1/selfcheck.py``
Exit code 0 = every claim held; 1 = at least one did not (and it says which).
"""

from __future__ import annotations

import math
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import sim_loop as S

FAILURES: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    status = "PASS" if condition else "FAIL"
    print(f"  [{status}] {name}" + (f" — {detail}" if detail else ""))
    if not condition:
        FAILURES.append(name)


def _log() -> S.HopLog:
    return S.HopLog(
        Path(tempfile.mkdtemp()) / "selfcheck.jsonl",
        t0=time.monotonic(),
        guard=S.NameScan({"lamppost", "bench"}),
    )


def check_l1_unbilled_whisper() -> None:
    print("L1 — the whisper takes the unbilled tail seam")
    log = _log()
    voice = S.FakeVoice(log=log, reply_for=lambda text, context: "ok")
    voice.open()
    before = len(voice.lane.transport.sent)  # type: ignore[union-attr]

    whisper = S.PlanQueueWhisper(labels={}, log=log)
    whisper.admit(directive="go to the lamppost", goal="lamppost", task_id="t1", t=0.0)
    first = whisper.refresh(voice.lane)
    whisper.note_receipt(
        S.Receipt(
            t=1.0,
            kind="task_succeeded",
            source="executive",
            task_id="t1",
            action="task_succeeded",
            state="succeeded",
            plan_revision=1,
            last_detail="navigation_goal_verified",
        )
    )
    second = whisper.refresh(voice.lane)
    third = whisper.refresh(voice.lane)

    sent = [str(frame.get("type")) for frame in voice.lane.transport.sent]  # type: ignore[union-attr]
    new = sent[before:]
    items = [
        frame
        for frame in voice.lane.transport.sent  # type: ignore[union-attr]
        if frame.get("type") == "conversation.item.create"
    ]
    purposes = sorted({row["purpose"] for row in voice.lane._item_trace.values()})

    check("two refreshes send exactly two conversation items", new == [
        "conversation.item.create",
        "conversation.item.create",
    ], str(new))
    check("no response.create is sent by the whisper", "response.create" not in new)
    check("the whisper carries its own purpose tag", purposes == [S.ITEM_PURPOSE_PLAN_QUEUE],
          str(purposes))
    check("an unchanged digest sends nothing (replace-not-append)", third is None)
    check("the replacement names what it supersedes",
          bool(second and second.get("supersedes") == "lit1_pq1"))
    check("the item text opens with the supersede marker",
          items[-1]["item"]["content"][0]["text"].startswith("[plan-queue update"))
    check("the whisper rows are marked unbilled",
          bool(first) and first["billed"] is False and first["response_create"] is False)
    voice.close()
    log.close()


def check_l7_confirm_rule() -> None:
    print("L7 — 'yes' resumes nothing by itself")
    cases = (
        ("yes", True, S.KIND_REISSUE),
        ("yes", False, "none"),
        ("yeah", False, "none"),
        ("resume", False, S.KIND_REISSUE),
        ("keep going", False, S.KIND_REISSUE),
        ("carry on", False, S.KIND_REISSUE),
        ("continue", False, S.KIND_REISSUE),
        ("nice weather today", True, "none"),
    )
    for text, offer_open, want in cases:
        got, why = S.classify_confirm(text, offer_open=offer_open)
        check(f"{text!r} with offer_open={offer_open} → {want}", got == want, why)


def check_receipt_typed_offer() -> None:
    """Card C7 — the harness may not say "arrived" without an accepted terminal.

    All five recorded base runs emitted "I've reached the bench." on a
    ``task_failed`` receipt, from deterministic harness code.  These rows are
    the guard against that, settled without a simulator.
    """

    print("C7 — the post-terminal offer is typed by the receipt (L7 / MB-1 M7)")
    scripted = (
        "I've reached the bench. I can't check whether your keys are there — I "
        "have no camera, so I can't look for objects. Do you want me to head "
        "back to the lamppost?"
    )

    def receipt(kind: str, detail: str) -> S.Receipt:
        return S.Receipt(t=1.0, kind=kind, source="executive", task_id="t1",
                         action=kind, state="", plan_revision=1, last_detail=detail)

    ok = S.offer_for_terminal(scripted, receipt("task_succeeded", "arrived"), goal="bench")
    check("an ACCEPTED terminal keeps the scripted line verbatim",
          ok["text"] == scripted and ok["arrival_phrase_allowed"] and not ok["rewritten"])

    for kind, detail in (("task_failed", "semantic_target_unreachable"),
                         ("task_cancelled", "cancelled_by_owner"),
                         ("cancelled_at_checkpoint", "cancelled_at_checkpoint")):
        row = S.offer_for_terminal(scripted, receipt(kind, detail), goal="bench")
        status = S._status_for(kind)
        check(f"{kind}: no arrival phrase survives",
              not S._ARRIVAL_CLAIM_RE.search(row["text"]), row["text"][:70])
        check(f"{kind}: the receipt's own kind and detail are spoken",
              kind in row["text"] and detail in row["text"] and status in row["text"])
        check(f"{kind}: the capability refusal and the offer are kept",
              "no camera" in row["text"] and "Do you want me" in row["text"])
        check(f"{kind}: the scripted arrival sentence is recorded as dropped",
              row["dropped_sentences"] == ["I've reached the bench."])

    none_row = S.offer_for_terminal(scripted, None, goal="bench")
    check("no terminal receipt at all: still no arrival phrase",
          not S._ARRIVAL_CLAIM_RE.search(none_row["text"])
          and "no terminal receipt" in none_row["text"], none_row["text"][:70])

    check("every terminal kind maps into the wave's fact set",
          {S._status_for(k) for k in S.TERMINAL_KINDS} <= set(S.FACTS),
          str(sorted({S._status_for(k) for k in S.TERMINAL_KINDS})))
    check("exactly one terminal kind may say arrived",
          S.ACCEPTED_TERMINAL_KIND == "task_succeeded"
          and S._status_for(S.ACCEPTED_TERMINAL_KIND) == "completed")


def check_l9_turn_predicate() -> None:
    print("L9 — the turn predicate")

    def sample(t: float, yaw: float, vyaw: float) -> S.MotionSample:
        return S.MotionSample(t=t, x=0.0, y=0.0, yaw=yaw, vx=0.0, vy=0.0, vyaw=vyaw, pace=1.0)

    turning = [sample(i * 0.1, math.pi / 2 - i * 0.15, -0.5) for i in range(8)]
    t, evidence = S.first_turn_toward(turning, goal_xy=(5.0, 0.0), t_from=0.0)
    check("a real turn toward the goal fires", t is not None, str(evidence))

    still = [sample(i * 0.1, 1.0, 0.0) for i in range(8)]
    t2, evidence2 = S.first_turn_toward(still, goal_xy=(5.0, 0.0), t_from=0.0)
    check("a stationary body does not fire", t2 is None, str(evidence2.get("reason")))

    creeping = [sample(i * 0.1, math.pi / 2 - i * 0.15, -0.05) for i in range(8)]
    t3, _ = S.first_turn_toward(creeping, goal_xy=(5.0, 0.0), t_from=0.0)
    check("|vyaw| below the 0.1 rad/s floor does not fire", t3 is None)

    away = [sample(i * 0.1, 0.0 + i * 0.15, 0.5) for i in range(8)]
    t4, _ = S.first_turn_toward(away, goal_xy=(5.0, 0.0), t_from=0.0)
    check("turning AWAY from the goal does not fire", t4 is None)


def check_l4_name_scan() -> None:
    print("L4 — the name scan is a positive allowlist")
    scan = S.NameScan({"lamppost", "bench"})
    check("an allowlisted name passes", scan.scan({"text": "go to the lamppost"}) == [])
    check(
        "an unadmitted place is caught",
        scan.scan({"text": "go to the kitchen sofa"}) == ["kitchen", "sofa"],
    )
    check(
        "it is redacted, not dropped",
        scan.redact({"text": "go to the kitchen"})["text"] == "go to the [unadmitted-place]",
    )
    check("the scan walks nested structures",
          scan.scan({"a": {"b": ["the hallway"]}}) == ["hallway"])


def check_vocabulary() -> None:
    print("shared vocabulary — receipt KIND → the wave's fact set")
    facts = set(S.FACTS)
    mapped = {
        kind: S._status_for(kind)
        for kind in sorted(S.SEQUENCE_KINDS)
        if S._status_for(kind) is not None
    }
    check("every mapped status is in the wave's fact set",
          set(mapped.values()) <= facts, str(sorted(set(mapped.values()))))
    check("the two harness-authored kinds map to no product fact",
          S._status_for(S.KIND_REISSUE) is None
          and S._status_for(S.KIND_CONFIRM) is None)
    respond = {k for k, v in S.PlanQueueWhisper.TRIGGER_TABLE.items() if v == "respond"}
    check("only terminal-ish kinds spend a billed response.create",
          respond == {"task_succeeded", "task_failed", "cancelled_at_checkpoint",
                      "replacement_activated"}, str(sorted(respond)))


def main() -> int:
    print(f"LIT-1 self-check — providers: {S.PROVIDERS}\n")
    check_l1_unbilled_whisper()
    print()
    check_l7_confirm_rule()
    print()
    check_l9_turn_predicate()
    print()
    check_l4_name_scan()
    print()
    check_receipt_typed_offer()
    print()
    check_vocabulary()
    print()
    if FAILURES:
        print(f"FAILED: {len(FAILURES)} check(s): {FAILURES}")
        return 1
    print("all checks held")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
