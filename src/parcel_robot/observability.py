from __future__ import annotations

import math
import statistics
import threading
import time
from collections import Counter, deque
from dataclasses import dataclass, field
from datetime import UTC, datetime

PLANNING_STAGE_DEFINITIONS = {
    "intent_routed": (
        "The deterministic intent router has classified the final user turn and "
        "produced its versioned IntentFrame."
    ),
    "observation_snapshot": (
        "A bounded, sensor-grounded ObservationSnapshot is ready for planning."
    ),
    "plan_first_output": (
        "The first output token or equivalent partial output from the planning model."
    ),
    "plan_response": (
        "The complete planning-model response has been received and parsed as PlanIR."
    ),
    "plan_validated": (
        "PlanIR has passed schema, semantic, capability, freshness, and safety validation."
    ),
    "plan_accepted": (
        "The validated plan has been admitted by the task executive for execution."
    ),
}

PLANNING_LATENCY_DEFINITIONS = {
    "UserQueryEndToFirstPlanOutput": (
        "End of final user input to the first planning-model output token; for a "
        "non-streaming provider, the complete parsed planning response."
    ),
    "UserQueryEndToAcceptedPlan": (
        "End of final user input to admission of a validated plan by the task executive."
    ),
    "IntentRouting": "End of final user input to production of IntentFrame.",
    "ObservationSnapshotBuild": (
        "IntentFrame production to completion of the bounded planning observation snapshot."
    ),
    "PlanTimeToFirstOutput": (
        "Observation snapshot completion to the first planning-model output token; for a "
        "non-streaming provider, the complete parsed planning response."
    ),
    "PlanDecode": (
        "Observation snapshot completion to receipt and parsing of the complete PlanIR."
    ),
    "PlanValidation": "Complete PlanIR parsing to successful plan validation.",
    "PlanAcceptance": "Successful plan validation to task-executive admission.",
}

# Stable names for rolling ComponentMetrics observations. The tracker remains
# deliberately open to application-specific component names, while these names
# let the runtime and dashboard agree on the split-brain/control-loop vocabulary.
COMPONENT_METRIC_DEFINITIONS = {
    "IntentRouter": "Wall-clock duration of deterministic intent routing.",
    "ObservationSnapshotBuild": (
        "Wall-clock duration of building a bounded camera/LiDAR planning snapshot."
    ),
    "PlanModel": "Wall-clock duration of the complete planning-model request.",
    "PlanValidation": "Wall-clock duration of PlanIR validation against fresh state.",
    "PlanAcceptance": "Wall-clock duration of task-executive plan admission.",
    "ExecutiveTick": "Wall-clock duration of one non-LLM task-executive tick.",
    "FillerLatency": (
        "End of final user input to the first audible duplex filler utterance "
        "(playback start / TTS enqueue audible — not filler fire time)."
    ),
    "DuplexProducer": "Wall-clock duration of one duplex frame producer tick.",
}

STAGES = frozenset(
    {
        "query_end",
        *PLANNING_STAGE_DEFINITIONS,
        "reasoning_start",
        "reasoning_first_output",
        "action_commit_start",
        "action_commit_end",
        "reasoning_response",
        "response_logged",
        "tts_start",
        "tts_text_chunk",
        "tts_first_chunk",
        "audio_first_playback",
        "tts_complete",
        "turn_complete",
        "superseded",
        "error",
        "filler_start",
        "filler_audible",
        "filler_complete",
        "filler_clause_boundary_wait",
        # System-initiated speech (Vocalize, pose-health, the yield policy's
        # ask/re-ask/give-up). Deliberately NOT filler stages: a request for
        # help is not an acknowledgement token and must not be measured
        # against the filler ceiling. See DuplexVoiceSession.speak_system.
        "system_utterance_start",
        "system_utterance_complete",
    }
)


@dataclass
class TurnTrace:
    turn_id: int
    query: str
    source: str
    query_end_monotonic: float
    query_end_utc: str
    stages: dict[str, float] = field(default_factory=dict)
    response: str = ""
    reasoning_source: str = "unknown"
    status: str = "processing"
    details: dict[str, object] = field(default_factory=dict)


class LatencyTracker:
    """Thread-safe, bounded voice-turn traces and latency aggregates.

    Absolute monotonic timestamps never leave this class. API consumers receive
    durations relative to the end of the user's final query, which is the stable
    reference point for both typed input and end-of-utterance ASR.
    """

    def __init__(self, max_turns: int = 200):
        if max_turns <= 0:
            raise ValueError("max_turns must be positive")
        self.max_turns = max_turns
        self._active: dict[int, TurnTrace] = {}
        self._recent: deque[TurnTrace] = deque(maxlen=max_turns)
        self._lock = threading.RLock()

    def start(
        self,
        turn_id: int,
        query: str,
        *,
        source: str = "text",
        now: float | None = None,
    ) -> None:
        if turn_id <= 0:
            raise ValueError("turn_id must be positive")
        clean_query = " ".join(str(query).split())
        if not clean_query:
            raise ValueError("query must not be empty")
        timestamp = time.monotonic() if now is None else float(now)
        if not math.isfinite(timestamp):
            raise ValueError("latency timestamp must be finite")
        with self._lock:
            trace = TurnTrace(
                turn_id=turn_id,
                query=clean_query,
                source=str(source),
                query_end_monotonic=timestamp,
                query_end_utc=datetime.now(UTC).isoformat(),
                stages={"query_end": timestamp},
            )
            self._active[turn_id] = trace

    def mark(
        self,
        turn_id: int,
        stage: str,
        *,
        now: float | None = None,
        details: dict[str, object] | None = None,
    ) -> None:
        if stage not in STAGES:
            raise ValueError(f"unsupported latency stage: {stage}")
        timestamp = time.monotonic() if now is None else float(now)
        if not math.isfinite(timestamp):
            raise ValueError("latency timestamp must be finite")
        with self._lock:
            trace = self._active.get(turn_id)
            if trace is None:
                return
            # First-byte/first-response metrics must remain the first observed
            # occurrence even if a provider retries or emits multiple chunks.
            if stage in {"reasoning_first_output", "plan_first_output"} and stage in trace.stages:
                trace.stages[stage] = min(trace.stages[stage], timestamp)
            else:
                trace.stages.setdefault(stage, timestamp)
            if details:
                trace.details.update(_bounded_details(details))
            if stage == "superseded":
                trace.status = "superseded"
            elif stage == "error":
                trace.status = "error"

    def finish(
        self,
        turn_id: int,
        response: str,
        *,
        reasoning_source: str = "unknown",
        status: str = "completed",
        now: float | None = None,
        details: dict[str, object] | None = None,
    ) -> None:
        timestamp = time.monotonic() if now is None else float(now)
        if not math.isfinite(timestamp):
            raise ValueError("latency timestamp must be finite")
        with self._lock:
            trace = self._active.pop(turn_id, None)
            if trace is None:
                return
            trace.response = " ".join(str(response).split())[:2000]
            trace.reasoning_source = str(reasoning_source)[:80]
            trace.status = str(status)[:40]
            trace.stages.setdefault("response_logged", timestamp)
            trace.stages.setdefault("turn_complete", timestamp)
            if details:
                trace.details.update(_bounded_details(details))
            self._recent.append(trace)

    def set_result(
        self,
        turn_id: int,
        response: str,
        *,
        reasoning_source: str = "unknown",
        status: str = "completed",
        details: dict[str, object] | None = None,
    ) -> None:
        with self._lock:
            trace = self._active.get(turn_id)
            if trace is None:
                return
            trace.response = " ".join(str(response).split())[:2000]
            trace.reasoning_source = str(reasoning_source)[:80]
            trace.status = str(status)[:40]
            if details:
                trace.details.update(_bounded_details(details))

    def finalize(
        self,
        turn_id: int,
        *,
        status: str | None = None,
        now: float | None = None,
    ) -> None:
        timestamp = time.monotonic() if now is None else float(now)
        if not math.isfinite(timestamp):
            raise ValueError("latency timestamp must be finite")
        with self._lock:
            trace = self._active.pop(turn_id, None)
            if trace is None:
                return
            trace.stages.setdefault("turn_complete", timestamp)
            if status is not None:
                trace.status = str(status)[:40]
            elif trace.status == "processing":
                trace.status = "completed"
            self._recent.append(trace)

    def snapshot(self) -> dict[str, object]:
        with self._lock:
            traces = [*self._recent, *self._active.values()]
            rows = [_trace_row(trace) for trace in reversed(traces[-self.max_turns :])]
        terminal_rows = [row for row in rows if row["status"] != "processing"]
        completed_rows = [row for row in terminal_rows if row["status"] == "completed"]
        aggregates = _aggregate_rows(completed_rows)
        aggregate_by_status = {
            status: _aggregate_rows([row for row in terminal_rows if row["status"] == status])
            for status in sorted({str(row["status"]) for row in terminal_rows})
        }
        return {
            "definitions": {
                "UserQueryEndToFirstResponse": (
                    "End of final user input to the first response made observable by logging "
                    "or audio playback, whichever occurs first."
                ),
                "UserQueryEndToFirstReasoningResponse": (
                    "End of final user input to the first model output token; for deterministic "
                    "or non-streaming paths, the complete validated reasoning result."
                ),
                "QueryEndToFirstSpokenAudio": (
                    "End of final user input to the first audio-sink handoff. This is a "
                    "software lower-bound estimate until acoustic presentation timestamps "
                    "are available."
                ),
                **PLANNING_LATENCY_DEFINITIONS,
            },
            "stage_definitions": dict(PLANNING_STAGE_DEFINITIONS),
            "component_definitions": dict(COMPONENT_METRIC_DEFINITIONS),
            "aggregate": aggregates,
            "aggregate_by_status": aggregate_by_status,
            "status_counts": dict(Counter(str(row["status"]) for row in rows)),
            "turns": rows,
        }


class ComponentMetrics:
    """Low-overhead rolling distributions for real-time robot components."""

    def __init__(self, samples_per_component: int = 512):
        if samples_per_component <= 0:
            raise ValueError("samples_per_component must be positive")
        self.samples_per_component = samples_per_component
        self._samples: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def observe_ms(self, name: str, value_ms: float) -> None:
        value = float(value_ms)
        if not name or not math.isfinite(value) or value < 0.0:
            return
        with self._lock:
            samples = self._samples.setdefault(
                str(name)[:80], deque(maxlen=self.samples_per_component)
            )
            samples.append(value)

    def elapsed(self, name: str, started: float) -> None:
        self.observe_ms(name, (time.monotonic() - started) * 1000.0)

    def snapshot(self) -> dict[str, object]:
        with self._lock:
            copied = {name: list(values) for name, values in self._samples.items()}
        return {
            name: {
                **(_aggregate(values) or {}),
                "latest_ms": round(values[-1], 3),
            }
            for name, values in sorted(copied.items())
            if values
        }


def _trace_row(trace: TurnTrace) -> dict[str, object]:
    stages = trace.stages
    query_end = trace.query_end_monotonic
    response_candidates = [
        value
        for name in ("response_logged", "audio_first_playback")
        if (value := stages.get(name)) is not None
    ]
    first_response = min(response_candidates) if response_candidates else None
    first_plan_output = (
        "plan_first_output" if "plan_first_output" in stages else "plan_response"
    )

    def delta(start: str | float, end: str | float) -> float | None:
        start_value = stages.get(start) if isinstance(start, str) else start
        end_value = stages.get(end) if isinstance(end, str) else end
        if start_value is None or end_value is None:
            return None
        return round(max(0.0, (end_value - start_value) * 1000.0), 3)

    latencies: dict[str, float | None] = {
        "UserQueryEndToFirstResponse": delta(query_end, first_response)
        if first_response is not None
        else None,
        "UserQueryEndToFirstReasoningResponse": delta(
            query_end,
            "reasoning_first_output"
            if "reasoning_first_output" in stages
            else "reasoning_response",
        ),
        "UserQueryEndToFirstPlanOutput": delta(query_end, first_plan_output),
        "UserQueryEndToAcceptedPlan": delta(query_end, "plan_accepted"),
        "IntentRouting": delta(query_end, "intent_routed"),
        "ObservationSnapshotBuild": delta("intent_routed", "observation_snapshot"),
        "PlanTimeToFirstOutput": delta("observation_snapshot", first_plan_output),
        "PlanDecode": delta("observation_snapshot", "plan_response"),
        "PlanValidation": delta("plan_response", "plan_validated"),
        "PlanAcceptance": delta("plan_validated", "plan_accepted"),
        "QueueWait": delta(query_end, "reasoning_start"),
        "Reasoning": delta(
            "reasoning_start",
            "action_commit_start" if "action_commit_start" in stages else "reasoning_response",
        ),
        "ReasoningAndCommit": delta("reasoning_start", "reasoning_response"),
        "ReasoningToResponseLog": delta("reasoning_response", "response_logged"),
        "ActionCommit": delta("action_commit_start", "action_commit_end"),
        "QueryEndToTTSStart": delta(query_end, "tts_start"),
        "TTSTimeToFirstChunk": delta("tts_start", "tts_first_chunk"),
        "QueryEndToFirstSpokenAudio": delta(query_end, "audio_first_playback"),
        "TTSTotal": delta("tts_start", "tts_complete"),
        "TurnTotal": delta(query_end, "turn_complete"),
    }
    stage_offsets = {
        name: round(max(0.0, (value - query_end) * 1000.0), 3) for name, value in stages.items()
    }
    return {
        "turn_id": trace.turn_id,
        "timestamp": trace.query_end_utc,
        "source": trace.source,
        "status": trace.status,
        "reasoning_source": trace.reasoning_source,
        "user_query": trace.query,
        "model_response": trace.response,
        "latency_ms": latencies,
        "stage_offsets_ms": stage_offsets,
        "details": dict(trace.details),
    }


def _aggregate(values: list[float]) -> dict[str, float | int] | None:
    if not values:
        return None
    ordered = sorted(values)

    def percentile(fraction: float) -> float:
        index = max(0, min(len(ordered) - 1, math.ceil(len(ordered) * fraction) - 1))
        return round(ordered[index], 3)

    return {
        "count": len(ordered),
        "mean_ms": round(statistics.fmean(ordered), 3),
        "p50_ms": percentile(0.50),
        "p95_ms": percentile(0.95),
        "p99_ms": percentile(0.99),
        "max_ms": round(max(ordered), 3),
    }


def _aggregate_rows(rows: list[dict[str, object]]) -> dict[str, object]:
    metric_names = sorted(
        {
            name
            for row in rows
            for name, value in row["latency_ms"].items()  # type: ignore[union-attr]
            if isinstance(value, (int, float))
        }
    )
    return {
        name: _aggregate(
            [
                float(row["latency_ms"][name])  # type: ignore[index]
                for row in rows
                if isinstance(row["latency_ms"].get(name), (int, float))  # type: ignore[union-attr]
            ]
        )
        for name in metric_names
    }


def _bounded_details(details: dict[str, object]) -> dict[str, object]:
    bounded: dict[str, object] = {}
    for key, value in list(details.items())[:32]:
        clean_key = str(key)[:80]
        if (
            isinstance(value, bool)
            or value is None
            or isinstance(value, (int, float))
            and math.isfinite(float(value))
        ):
            bounded[clean_key] = value
        elif isinstance(value, str):
            bounded[clean_key] = value[:500]
    return bounded
