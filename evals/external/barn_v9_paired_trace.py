"""Spawn-safe additive V9 traces for the existing paired BARN comparison.

The public wrapper calls the established paired comparison unchanged.  While
that call is active it substitutes two additive functions:

* a traced episode executor for the local ``workers=1`` path; and
* an importable process worker for the existing spawn-pool path.

The child worker installs the same traced executor inside its own interpreter,
so both arms retain the evaluator's serial lifecycle.  The established report
and immutable action-evidence pipeline receive the original execution object
with only ``v9_step_trace`` and ``v9_step_trace_sha256`` added to episode
detail.  All temporary module substitutions are restored in ``finally``.
"""

from __future__ import annotations

import threading
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from . import barn_sensor_faithful as _evaluator
from .barn_policy_specs import IsolatedPlannerProfileAuthorization
from .barn_ros2_adapter import BarnRos2Policy
from .barn_sensor_faithful import (
    CalibratedBarnConfig,
    SensorFaithfulEpisodeWithEvidence,
    V8EpisodeEvidenceCaptureSpec,
)
from .barn_v9_step_trace import (
    SensorFaithfulEpisodeWithV9Trace,
    V9StepTraceError,
    run_sensor_faithful_with_v9_step_trace,
)

_ORIGINAL_RUNNER_CLASS = _evaluator.SensorFaithfulBarnRunner
_ORIGINAL_EXECUTE_EPISODE = _evaluator._execute_episode
_ORIGINAL_PAIRED_PROCESS_WORKER = _evaluator._run_paired_process_episode

_PARENT_PATCH_LOCK = threading.Lock()
_CHILD_PATCH_LOCK = threading.Lock()
_RUNNER_FACTORY_PATCH_LOCK = threading.Lock()


class _TracingRunnerProxy:
    """Duck-compatible runner used only inside the original episode executor."""

    def __init__(
        self,
        runner: _evaluator.SensorFaithfulBarnRunner,
        captured: list[SensorFaithfulEpisodeWithV9Trace],
    ) -> None:
        self._runner = runner
        self._captured = captured

    def _remember(
        self,
        traced: SensorFaithfulEpisodeWithV9Trace,
    ) -> SensorFaithfulEpisodeWithV9Trace:
        if self._captured:
            raise V9StepTraceError("one episode executor invoked its runner more than once")
        self._captured.append(traced)
        return traced

    def run(self, policy: BarnRos2Policy) -> _evaluator.SensorFaithfulEpisodeResult:
        traced = self._remember(run_sensor_faithful_with_v9_step_trace(self._runner, policy))
        return traced.result

    def run_with_action_evidence(
        self,
        policy: BarnRos2Policy,
        evidence_capture: V8EpisodeEvidenceCaptureSpec,
    ) -> SensorFaithfulEpisodeWithEvidence:
        traced = self._remember(
            run_sensor_faithful_with_v9_step_trace(
                self._runner,
                policy,
                evidence_capture=evidence_capture,
            )
        )
        if traced.action_evidence is None:  # pragma: no cover - wrapper contract.
            raise V9StepTraceError("traced action-evidence run omitted its builder")
        return SensorFaithfulEpisodeWithEvidence(
            result=traced.result,
            action_evidence=traced.action_evidence,
        )


def execute_episode_with_v9_trace(
    *,
    world: _evaluator.BarnWorld,
    config: CalibratedBarnConfig,
    policy: BarnRos2Policy,
    trial: int,
    episode_seed: int,
    action_evidence: V8EpisodeEvidenceCaptureSpec | None = None,
) -> _evaluator._EpisodeExecution:
    """Run the original episode executor and add a full integration trace."""

    captured: list[SensorFaithfulEpisodeWithV9Trace] = []

    def runner_factory(
        runner_world: _evaluator.BarnWorld,
        runner_config: CalibratedBarnConfig | None = None,
    ) -> _TracingRunnerProxy:
        return _TracingRunnerProxy(
            _ORIGINAL_RUNNER_CLASS(runner_world, runner_config),
            captured,
        )

    with _RUNNER_FACTORY_PATCH_LOCK:
        previous_runner = _evaluator.SensorFaithfulBarnRunner
        _evaluator.SensorFaithfulBarnRunner = runner_factory
        try:
            execution = _ORIGINAL_EXECUTE_EPISODE(
                world=world,
                config=config,
                policy=policy,
                trial=trial,
                episode_seed=episode_seed,
                action_evidence=action_evidence,
            )
        finally:
            _evaluator.SensorFaithfulBarnRunner = previous_runner

    if len(captured) != 1:
        raise V9StepTraceError("original episode executor did not produce exactly one trace")
    trace = captured[0].step_trace
    detail = dict(execution.detail)
    detail["v9_step_trace"] = trace.as_dict()
    detail["v9_step_trace_sha256"] = trace.sha256
    return _evaluator._EpisodeExecution(
        detail=detail,
        latency_samples_ms=execution.latency_samples_ms,
        policy_diagnostics=execution.policy_diagnostics,
        action_evidence=execution.action_evidence,
    )


def run_v9_paired_process_episode(
    request: _evaluator._PairedEpisodeRequest,
) -> _evaluator._PairedEpisodeExecution:
    """Importable spawn worker that traces both serial arms of one pair."""

    with _CHILD_PATCH_LOCK:
        previous_executor = _evaluator._execute_episode
        _evaluator._execute_episode = execute_episode_with_v9_trace
        try:
            return _ORIGINAL_PAIRED_PROCESS_WORKER(request)
        finally:
            _evaluator._execute_episode = previous_executor


def run_sensor_faithful_paired_comparison_with_v9_traces(
    *,
    assets_root: str | Path,
    world_indices: Sequence[int],
    candidate_spec: _evaluator.BarnPolicySpec | _evaluator.CalibratedPolicySpec,
    reference_spec: (_evaluator.BarnPolicySpec | _evaluator.CalibratedPolicySpec | None) = None,
    trials: int = 1,
    suite_seed: int = 20260803,
    workers: int = 1,
    allow_experimental: bool = False,
    config: CalibratedBarnConfig | None = None,
    generated_corpus: bool = False,
    asset_manifest_sha256: str | None = None,
    long_shield_stall_steps: int = 50,
    arm_order_schedule: Sequence[str] | None = None,
    action_evidence_paths: Mapping[tuple[int, int, str], str | Path] | None = None,
    isolated_planner_profile_authorization: (
        IsolatedPlannerProfileAuthorization | None
    ) = None,
) -> dict[str, Any]:
    """Call the exact paired evaluator with full V9 traces on every arm.

    ``workers=4`` follows the evaluator's existing spawn path.  No executor,
    request, report, action-evidence, or scoring behavior is reimplemented.
    """

    with _PARENT_PATCH_LOCK:
        previous_executor = _evaluator._execute_episode
        previous_process_worker = _evaluator._run_paired_process_episode
        _evaluator._execute_episode = execute_episode_with_v9_trace
        _evaluator._run_paired_process_episode = run_v9_paired_process_episode
        try:
            return _evaluator.run_sensor_faithful_paired_comparison(
                assets_root=assets_root,
                world_indices=world_indices,
                candidate_spec=candidate_spec,
                reference_spec=reference_spec,
                trials=trials,
                suite_seed=suite_seed,
                workers=workers,
                allow_experimental=allow_experimental,
                config=config,
                generated_corpus=generated_corpus,
                asset_manifest_sha256=asset_manifest_sha256,
                long_shield_stall_steps=long_shield_stall_steps,
                arm_order_schedule=arm_order_schedule,
                action_evidence_paths=action_evidence_paths,
                isolated_planner_profile_authorization=(
                    isolated_planner_profile_authorization
                ),
            )
        finally:
            _evaluator._run_paired_process_episode = previous_process_worker
            _evaluator._execute_episode = previous_executor


__all__ = [
    "execute_episode_with_v9_trace",
    "run_sensor_faithful_paired_comparison_with_v9_traces",
    "run_v9_paired_process_episode",
]
