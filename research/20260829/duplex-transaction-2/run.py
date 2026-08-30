#!/usr/bin/env python
"""Run DMC-2 against Parcel's production executive and narration evidence seams."""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import time
from dataclasses import replace
from pathlib import Path
from typing import Any

from parcel_robot.brain.contracts import (
    ExecutionResult,
    GoalSpec,
    GoalTarget,
    PlanIR,
    PlanStep,
    SuccessCondition,
    VerifiedFact,
)
from parcel_robot.brain.executive import TaskExecutive
from parcel_robot.brain.validator import PlanValidator
from parcel_robot.contracts.companion_v1 import (
    ActionReceiptV1,
    derive_action_id,
    derive_mission_id,
)
from parcel_robot.contracts.dialogue_state_v1 import (
    ConsumedActionV1,
    DialogueStateV1,
    PendingActionV1,
)
from parcel_robot.contracts.terminal_claim_v1 import TerminalClaimProposalV1
from parcel_robot.voice.companion_auth import (
    AuthenticatedActionReceiptV1,
    TrustedReceiptAuthenticatorV1,
)
from parcel_robot.voice.companion_state import (
    apply_action_receipt,
    license_terminal_claim,
)


HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[2]
MANIFEST_PATH = HERE / "manifest.json"
EXPECTED_AUTH = TrustedReceiptAuthenticatorV1(
    authenticator_id="dmc2_expected_executive",
    key=b"dmc2-expected-channel-test-key-0001",
)
OTHER_AUTH = TrustedReceiptAuthenticatorV1(
    authenticator_id="dmc2_wrong_executive",
    key=b"dmc2-wrong-channel-test-key-000002",
)


EXECUTIVE_CASES = (
    "valid_succeeded",
    "wrong_task",
    "wrong_revision",
    "wrong_step",
    "wrong_attempt",
    "not_running",
    "unverified_success",
    "post_terminal",
)
RECEIPT_CASES = (
    "valid_succeeded",
    "raw_untrusted",
    "wrong_channel",
    "wrong_action",
    "premature_terminal",
    "duplicate",
    "sequence_regression",
    "timestamp_regression",
    "future",
    "expired",
    "post_terminal",
)
CLAIM_CASES = (
    "valid_terminal",
    "start_receipt",
    "wrong_channel",
    "wrong_receipt_id",
    "wrong_mission",
    "wrong_action",
    "wrong_name",
    "wrong_manifest",
    "wrong_status",
    "unretained",
    "future_proposal",
    "stale_proposal",
    "expired_receipt",
    "unrelated_receipt",
)


def canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("ascii")


def digest(value: object) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def file_sha256(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            value.update(block)
    return value.hexdigest()


def token(namespace: str, trial: int, field: str, length: int = 24) -> str:
    return hashlib.sha256(
        f"20260829:{namespace}:{trial}:{field}".encode("ascii")
    ).hexdigest()[:length]


def _task_state(snapshot: dict[str, object]) -> str:
    tasks = snapshot["tasks"]
    assert isinstance(tasks, list) and len(tasks) == 1
    state = tasks[0]["state"]
    assert isinstance(state, str)
    return state


def _plan(trial: int) -> PlanIR:
    return PlanIR(
        schema_version=1,
        task_id=f"task-{token('executive', trial, 'task')}",
        plan_revision=1,
        source_turn_id=f"turn-{token('executive', trial, 'turn')}",
        goal=GoalSpec("hold", GoalTarget("current_pose"), 0.0),
        invariants=(),
        steps=(
            PlanStep(
                f"step-{token('executive', trial, 'step')}",
                "Hold",
                {},
                ("base_available",),
                SuccessCondition("motion_stopped"),
                5.0,
                1,
                (),
                ("base",),
                "immediate",
            ),
        ),
    )


def _execution_result(
    *,
    task_id: str,
    plan_revision: int,
    step_id: str,
    attempt: int,
    verified: bool,
    trial: int,
) -> ExecutionResult:
    return ExecutionResult(
        schema_version=1,
        task_id=task_id,
        plan_revision=plan_revision,
        step_id=step_id,
        attempt=attempt,
        status="succeeded",
        feedback_code="succeeded",
        snapshot_id=f"snapshot-{token('executive', trial, 'snapshot')}",
        verified_facts=(
            (VerifiedFact("motion_stopped", None, "controller", 1.0),)
            if verified
            else ()
        ),
        checkpoint=True,
        detail_code="motion_stopped",
        started_at_monotonic_s=1000.0 + trial,
        finished_at_monotonic_s=1000.1 + trial,
    )


def run_executive_case(trial: int, corruption: str) -> dict[str, object]:
    plan = _plan(trial)
    executive = TaskExecutive()
    executive.submit(PlanValidator().validate(plan))
    request = None
    if corruption != "not_running":
        request = executive.tick(now=1000.0 + trial)[0]

    task_id = plan.task_id if request is None else request.task_id
    revision = plan.plan_revision if request is None else request.plan_revision
    step_id = plan.steps[0].step_id if request is None else request.step_id
    attempt = 1 if request is None else request.attempt
    verified = corruption != "unverified_success"

    if corruption == "wrong_task":
        task_id = f"task-{token('executive', trial, 'wrong-task')}"
    elif corruption == "wrong_revision":
        revision += 1
    elif corruption == "wrong_step":
        step_id = f"step-{token('executive', trial, 'wrong-step')}"
    elif corruption == "wrong_attempt":
        attempt = 2

    result = _execution_result(
        task_id=task_id,
        plan_revision=revision,
        step_id=step_id,
        attempt=attempt,
        verified=verified,
        trial=trial,
    )
    setup: list[dict[str, object]] = []
    if corruption == "post_terminal":
        first = executive.report(result)
        setup.append(
            {
                "input": result.as_dict(),
                "observed": {
                    "accepted": first.accepted,
                    "action": first.action,
                    "state": first.state,
                },
            }
        )

    pre_state = executive.snapshot()
    disposition = executive.report(result)
    post_state = executive.snapshot()
    observed = {
        "accepted": disposition.accepted,
        "action": disposition.action,
        "state": _task_state(post_state),
    }
    return {
        "case_id": f"executive-{trial:04d}-{corruption}",
        "seam": "executive",
        "corruption": corruption,
        "seed": 20260829,
        "input": {"setup": setup, "tested": result.as_dict()},
        "pre_state": pre_state,
        "observed": observed,
        "post_state": post_state,
        "state_digest_before": digest(pre_state),
        "state_digest_after": digest(post_state),
    }


def _dialogue_fixture(trial: int) -> tuple[DialogueStateV1, dict[str, object]]:
    base = 1_000_000_000_000 + trial * 10_000_000
    proposal_id = f"proposal-{token('dialogue', trial, 'proposal')}"
    turn_id = f"turn-{token('dialogue', trial, 'turn')}"
    action_name = f"gesture_{token('dialogue', trial, 'name', 12)}"
    manifest_digest = token("dialogue", trial, "manifest", 64)
    mission_id = derive_mission_id(
        turn_id=turn_id,
        proposal_id=proposal_id,
        manifest_digest=manifest_digest,
    )
    action_id = derive_action_id(
        mission_id=mission_id,
        proposal_id=proposal_id,
        action_name=action_name,
    )
    pending = PendingActionV1(
        mission_id=mission_id,
        action_id=action_id,
        proposal_id=proposal_id,
        turn_id=turn_id,
        action_name=action_name,
        manifest_digest=manifest_digest,
        consent_scope="stationary_expression",
        repeatable=True,
        state="admitted",
        admitted_at_monotonic_ns=base,
    )
    consumed = ConsumedActionV1(
        mission_id=mission_id,
        action_id=action_id,
        expires_monotonic_ns=base + 3_000_000_000,
    )
    state = replace(
        DialogueStateV1.empty(
            session_id=f"session-{token('dialogue', trial, 'session')}",
            now_monotonic_ns=base,
        ),
        revision=1,
        active_turn_id=turn_id,
        pending_action=pending,
        consumed_actions=(consumed,),
    )
    return state, {
        "base": base,
        "proposal_id": proposal_id,
        "turn_id": turn_id,
        "action_name": action_name,
        "manifest_digest": manifest_digest,
        "mission_id": mission_id,
        "action_id": action_id,
    }


def _mint_receipt(
    ids: dict[str, object],
    *,
    status: str,
    sequence: int,
    issued: int,
    claimable: int | None = None,
    action_overrides: dict[str, str] | None = None,
    authenticator: TrustedReceiptAuthenticatorV1 = EXPECTED_AUTH,
) -> AuthenticatedActionReceiptV1:
    values = {
        "mission_id": str(ids["mission_id"]),
        "action_id": str(ids["action_id"]),
        "action_name": str(ids["action_name"]),
        "manifest_digest": str(ids["manifest_digest"]),
    }
    values.update(action_overrides or {})
    receipt = ActionReceiptV1.mint(
        **values,
        status=status,
        sequence=sequence,
        issued_at_monotonic_ns=issued,
        claimable_until_monotonic_ns=(
            issued + 1_000_000_000 if claimable is None else claimable
        ),
        evidence_refs=(f"evidence-{sequence}",),
        detail_code=f"dmc2_{status}",
    )
    return authenticator.authenticate(receipt)


def _receipt_trace_input(
    authenticated: ActionReceiptV1 | AuthenticatedActionReceiptV1,
) -> dict[str, object]:
    if isinstance(authenticated, AuthenticatedActionReceiptV1):
        return {
            "receipt": authenticated.receipt.as_dict(),
            "authenticator_id": authenticated.authenticator_id,
            "authenticated_by_expected_channel": EXPECTED_AUTH.verify(authenticated),
        }
    return {
        "receipt": authenticated.as_dict(),
        "authenticator_id": None,
        "authenticated_by_expected_channel": False,
    }


def _reduce(
    state: DialogueStateV1,
    receipt: ActionReceiptV1 | AuthenticatedActionReceiptV1,
    *,
    now: int,
):
    return apply_action_receipt(  # type: ignore[arg-type]
        state,
        receipt,
        receipt_authenticator=EXPECTED_AUTH,
        now_monotonic_ns=now,
    )


def _receipt_observed(reduction: Any) -> dict[str, object]:
    pending = reduction.state.pending_action
    return {
        "accepted": reduction.accepted,
        "disposition": reduction.disposition,
        "reason": reduction.reason,
        "pending_state": None if pending is None else pending.state,
        "completed": reduction.state.last_completed_action is not None,
    }


def run_receipt_case(trial: int, corruption: str) -> dict[str, object]:
    state, ids = _dialogue_fixture(trial)
    base = int(ids["base"])
    setup: list[dict[str, object]] = []

    def apply_setup(receipt: AuthenticatedActionReceiptV1, now: int) -> None:
        nonlocal state
        reduction = _reduce(state, receipt, now=now)
        if not reduction.accepted:
            raise AssertionError(f"setup receipt rejected: {reduction.reason}")
        setup.append(
            {
                "input": _receipt_trace_input(receipt),
                "observed": _receipt_observed(reduction),
            }
        )
        state = reduction.state

    start = _mint_receipt(ids, status="started", sequence=1, issued=base + 10)
    terminal = _mint_receipt(ids, status="succeeded", sequence=2, issued=base + 20)
    tested: ActionReceiptV1 | AuthenticatedActionReceiptV1
    now = base + 20

    if corruption == "valid_succeeded":
        apply_setup(start, base + 10)
        tested = terminal
    elif corruption == "raw_untrusted":
        tested = start.receipt
        now = base + 10
    elif corruption == "wrong_channel":
        tested = _mint_receipt(
            ids,
            status="started",
            sequence=1,
            issued=base + 10,
            authenticator=OTHER_AUTH,
        )
        now = base + 10
    elif corruption == "wrong_action":
        tested = _mint_receipt(
            ids,
            status="started",
            sequence=1,
            issued=base + 10,
            action_overrides={
                "action_id": f"action-{token('receipt', trial, 'wrong-action')}"
            },
        )
        now = base + 10
    elif corruption == "premature_terminal":
        tested = _mint_receipt(
            ids, status="succeeded", sequence=1, issued=base + 10
        )
        now = base + 10
    elif corruption == "duplicate":
        apply_setup(start, base + 10)
        tested = start
        now = base + 11
    elif corruption == "sequence_regression":
        start_two = _mint_receipt(
            ids, status="started", sequence=2, issued=base + 10
        )
        apply_setup(start_two, base + 10)
        tested = _mint_receipt(
            ids, status="started", sequence=1, issued=base + 20
        )
    elif corruption == "timestamp_regression":
        late_start = _mint_receipt(
            ids, status="started", sequence=1, issued=base + 20
        )
        apply_setup(late_start, base + 20)
        tested = _mint_receipt(
            ids, status="succeeded", sequence=2, issued=base + 10
        )
        now = base + 21
    elif corruption == "future":
        apply_setup(start, base + 10)
        tested = _mint_receipt(
            ids, status="succeeded", sequence=2, issued=base + 100
        )
        now = base + 50
    elif corruption == "expired":
        apply_setup(start, base + 10)
        tested = _mint_receipt(
            ids,
            status="succeeded",
            sequence=2,
            issued=base + 20,
            claimable=base + 30,
        )
        now = base + 30
    elif corruption == "post_terminal":
        apply_setup(start, base + 10)
        apply_setup(terminal, base + 20)
        tested = _mint_receipt(
            ids, status="failed", sequence=3, issued=base + 30
        )
        now = base + 30
    else:  # pragma: no cover - manifest validation catches this
        raise ValueError(corruption)

    pre_state = state.as_dict()
    reduction = _reduce(state, tested, now=now)
    post_state = reduction.state.as_dict()
    observed = _receipt_observed(reduction)
    return {
        "case_id": f"receipt-{trial:04d}-{corruption}",
        "seam": "receipt",
        "corruption": corruption,
        "seed": 20260829,
        "input": {"setup": setup, "tested": _receipt_trace_input(tested), "now": now},
        "pre_state": pre_state,
        "observed": observed,
        "post_state": post_state,
        "state_digest_before": digest(pre_state),
        "state_digest_after": digest(post_state),
    }


def _completed_dialogue(
    trial: int, *, claimable: int | None = None
) -> tuple[
    DialogueStateV1,
    dict[str, object],
    AuthenticatedActionReceiptV1,
    AuthenticatedActionReceiptV1,
]:
    state, ids = _dialogue_fixture(trial)
    base = int(ids["base"])
    start = _mint_receipt(ids, status="started", sequence=1, issued=base + 10)
    terminal = _mint_receipt(
        ids,
        status="succeeded",
        sequence=2,
        issued=base + 20,
        claimable=claimable,
    )
    started = _reduce(state, start, now=base + 10)
    if not started.accepted:
        raise AssertionError(started.reason)
    completed = _reduce(started.state, terminal, now=base + 20)
    if not completed.accepted:
        raise AssertionError(completed.reason)
    return completed.state, ids, start, terminal


def _claim(
    ids: dict[str, object],
    receipt: AuthenticatedActionReceiptV1,
    *,
    proposed: int,
    overrides: dict[str, object] | None = None,
) -> TerminalClaimProposalV1:
    values: dict[str, object] = {
        "claim_id": f"claim-{token('claim', int(ids['base']), 'claim')}",
        "mission_id": receipt.mission_id,
        "action_id": receipt.action_id,
        "action_name": receipt.action_name,
        "manifest_digest": receipt.manifest_digest,
        "terminal_receipt_id": receipt.receipt_id,
        "claimed_status": receipt.status if receipt.terminal else "succeeded",
        "proposed_at_monotonic_ns": proposed,
    }
    values.update(overrides or {})
    return TerminalClaimProposalV1(**values)  # type: ignore[arg-type]


def run_claim_case(trial: int, corruption: str) -> dict[str, object]:
    state, ids, start, terminal = _completed_dialogue(trial)
    base = int(ids["base"])
    receipt = terminal
    authenticator = EXPECTED_AUTH
    now = base + 22
    proposal = _claim(ids, receipt, proposed=base + 21)

    if corruption == "start_receipt":
        initial, ids = _dialogue_fixture(trial)
        started = _reduce(initial, start, now=base + 10)
        if not started.accepted:
            raise AssertionError(started.reason)
        state = started.state
        receipt = start
        proposal = _claim(ids, receipt, proposed=base + 11)
        now = base + 12
    elif corruption == "wrong_channel":
        authenticator = OTHER_AUTH
    elif corruption == "wrong_receipt_id":
        proposal = _claim(
            ids,
            receipt,
            proposed=base + 21,
            overrides={
                "terminal_receipt_id": f"receipt-{token('claim', trial, 'wrong-receipt')}"
            },
        )
    elif corruption == "wrong_mission":
        proposal = _claim(
            ids,
            receipt,
            proposed=base + 21,
            overrides={"mission_id": f"mission-{token('claim', trial, 'wrong-mission')}"},
        )
    elif corruption == "wrong_action":
        proposal = _claim(
            ids,
            receipt,
            proposed=base + 21,
            overrides={"action_id": f"action-{token('claim', trial, 'wrong-action')}"},
        )
    elif corruption == "wrong_name":
        proposal = _claim(
            ids,
            receipt,
            proposed=base + 21,
            overrides={"action_name": f"other_{token('claim', trial, 'wrong-name', 12)}"},
        )
    elif corruption == "wrong_manifest":
        proposal = _claim(
            ids,
            receipt,
            proposed=base + 21,
            overrides={"manifest_digest": token("claim", trial, "wrong-manifest", 64)},
        )
    elif corruption == "wrong_status":
        proposal = _claim(
            ids,
            receipt,
            proposed=base + 21,
            overrides={"claimed_status": "failed"},
        )
    elif corruption == "unretained":
        state = replace(state, last_completed_action=None, action_receipts=())
    elif corruption == "future_proposal":
        proposal = _claim(ids, receipt, proposed=base + 100)
        now = base + 50
    elif corruption == "stale_proposal":
        proposal = _claim(ids, receipt, proposed=base + 21)
        now = base + 5_000_000_022
    elif corruption == "expired_receipt":
        state, ids, start, terminal = _completed_dialogue(
            trial, claimable=base + 30
        )
        receipt = terminal
        proposal = _claim(ids, receipt, proposed=base + 21)
        now = base + 31
    elif corruption == "unrelated_receipt":
        other_state, other_ids = _dialogue_fixture(trial + 10_000)
        del other_state
        proposal = _claim(
            ids,
            receipt,
            proposed=base + 21,
            overrides={
                "mission_id": other_ids["mission_id"],
                "action_id": other_ids["action_id"],
                "action_name": other_ids["action_name"],
                "manifest_digest": other_ids["manifest_digest"],
            },
        )
    elif corruption != "valid_terminal":  # pragma: no cover
        raise ValueError(corruption)

    pre_state = state.as_dict()
    license_result = license_terminal_claim(
        proposal,
        state,
        authenticated_receipt=receipt,
        receipt_authenticator=authenticator,
        now_monotonic_ns=now,
    )
    verified_claim = False
    if license_result.licensed:
        verified_claim = license_result.as_dialogue_claim().veracity == "verified"
    post_state = state.as_dict()
    observed = {
        "licensed": license_result.licensed,
        "reason": license_result.reason,
    }
    return {
        "case_id": f"claim-{trial:04d}-{corruption}",
        "seam": "claim",
        "corruption": corruption,
        "seed": 20260829,
        "input": {
            "proposal": proposal.as_dict(),
            "receipt": _receipt_trace_input(receipt),
            "license_authenticator_id": authenticator.authenticator_id,
            "now": now,
        },
        "pre_state": pre_state,
        "observed": observed,
        "verified_claim": verified_claim,
        "post_state": post_state,
        "state_digest_before": digest(pre_state),
        "state_digest_after": digest(post_state),
    }


def validate_manifest(manifest: dict[str, object]) -> None:
    inventory = {
        "executive": EXECUTIVE_CASES,
        "receipt": RECEIPT_CASES,
        "claim": CLAIM_CASES,
    }
    seams = manifest.get("seams")
    if not isinstance(seams, dict):
        raise ValueError("manifest seams missing")
    for seam, cases in inventory.items():
        if tuple(seams.get(seam, ())) != cases:
            raise ValueError(f"manifest {seam} inventory does not match frozen runner")
    if manifest.get("seed") != 20260829:
        raise ValueError("manifest seed drift")


def summarize(traces: list[dict[str, object]]) -> dict[str, object]:
    aggregate: dict[str, object] = {}
    for seam in ("executive", "receipt", "claim"):
        rows = [row for row in traces if row["seam"] == seam]
        controls = [row for row in rows if str(row["corruption"]).startswith("valid_")]
        corruptions = [row for row in rows if row not in controls]
        accepted = sum(
            bool(row["observed"].get("accepted"))
            for row in rows
            if isinstance(row.get("observed"), dict)
        )
        licensed = sum(
            bool(row["observed"].get("licensed"))
            for row in rows
            if isinstance(row.get("observed"), dict)
        )
        reasons: dict[str, int] = {}
        actions: dict[str, int] = {}
        for row in rows:
            observed = row.get("observed")
            if not isinstance(observed, dict):
                continue
            reason = observed.get("reason")
            action = observed.get("action")
            if reason is not None:
                reasons[str(reason)] = reasons.get(str(reason), 0) + 1
            if action is not None:
                actions[str(action)] = actions.get(str(action), 0) + 1
        aggregate[seam] = {
            "cases": len(rows),
            "controls": len(controls),
            "corruptions": len(corruptions),
            "accepted": accepted,
            "licensed": licensed,
            "verified_claims": sum(bool(row.get("verified_claim")) for row in rows),
            "state_changed": sum(
                row["state_digest_before"] != row["state_digest_after"] for row in rows
            ),
            "reason_histogram": dict(sorted(reasons.items())),
            "action_histogram": dict(sorted(actions.items())),
        }
    return aggregate


def hash_chain(traces: list[dict[str, object]]) -> str:
    previous = "0" * 64
    for row in traces:
        row["previous_event_sha256"] = previous
        row["event_sha256"] = digest(row)
        previous = str(row["event_sha256"])
    return previous


def run_suite(
    manifest: dict[str, object], *, trials: int | None = None
) -> dict[str, object]:
    validate_manifest(manifest)
    frozen_trials = int(manifest["trials_per_seam"])
    count = frozen_trials if trials is None else int(trials)
    if not 1 <= count <= frozen_trials:
        raise ValueError("trials must be within the frozen manifest population")
    seams = manifest["seams"]
    assert isinstance(seams, dict)
    traces: list[dict[str, object]] = []
    for trial in range(count):
        traces.extend(
            run_executive_case(trial, corruption)
            for corruption in seams["executive"]  # type: ignore[index]
        )
        traces.extend(
            run_receipt_case(trial, corruption)
            for corruption in seams["receipt"]  # type: ignore[index]
        )
        traces.extend(
            run_claim_case(trial, corruption)
            for corruption in seams["claim"]  # type: ignore[index]
        )
    trace_chain_root = hash_chain(traces)
    aggregates = summarize(traces)
    hypotheses = {
        "H1": {
            "passed": None,
            "scope": "production TaskExecutive result integrity",
            "evaluated_by": "verify_results.py",
        },
        "H2": {
            "passed": None,
            "scope": "production authenticated receipt integrity",
            "evaluated_by": "verify_results.py",
        },
        "H3": {
            "passed": None,
            "scope": "production terminal narration-evidence integrity",
            "evaluated_by": "verify_results.py",
        },
        "H4": {
            "passed": None,
            "scope": "cross-run determinism and independent verification",
            "evaluated_by": "verify_results.py",
        },
    }
    return {
        "schema_version": 1,
        "suite_id": manifest["suite_id"],
        "seed": manifest["seed"],
        "trials_per_seam": count,
        "frozen_population_complete": count == frozen_trials,
        "manifest_sha256": file_sha256(MANIFEST_PATH),
        "environment": {
            "python": platform.python_version(),
            "platform": platform.platform(),
        },
        "source_hashes": {
            str(path.relative_to(REPO_ROOT)): file_sha256(path)
            for path in (
                MANIFEST_PATH,
                HERE / "DESIGN.md",
                HERE / "AMENDMENTS.md",
                HERE / "run.py",
                REPO_ROOT / "src/parcel_robot/brain/executive.py",
                REPO_ROOT / "src/parcel_robot/voice/companion_state.py",
                REPO_ROOT / "src/parcel_robot/voice/companion_auth.py",
            )
        },
        "aggregates": aggregates,
        "hypotheses": hypotheses,
        "architecture_gate": {
            "status": "NOT_EVALUABLE_RED",
            "missing_contracts": [
                "executive-to-receipt bridge",
                "task/revision/step/attempt binding in ActionReceiptV1",
                "source epoch and speech generation binding",
                "typed progress/blocked/suspended/resumed receipt states",
                "more than one pending dialogue action",
            ],
        },
        "trace_chain_root_sha256": trace_chain_root,
        "normalized_trace_sha256": digest(traces),
        "traces": traces,
        "does_not_prove": [
            "language or instruction generalization",
            "free-form Model-B wording quality",
            "navigation, physics, sensing, acoustics, gateway, Orin, or Go2 behavior",
            "physical mount or motion readiness",
        ],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=MANIFEST_PATH)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--trials", type=int, default=None)
    args = parser.parse_args(argv)
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    started = time.time()
    result = run_suite(manifest, trials=args.trials)
    result["started_utc"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(started))
    result["duration_s"] = round(time.time() - started, 6)
    result["result_sha256"] = digest(
        {key: value for key, value in result.items() if key != "result_sha256"}
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    summary = {
        "out": str(args.out),
        "duration_s": result["duration_s"],
        "normalized_trace_sha256": result["normalized_trace_sha256"],
        "aggregates": result["aggregates"],
        "hypotheses": result["hypotheses"],
        "architecture_gate": result["architecture_gate"],
    }
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
