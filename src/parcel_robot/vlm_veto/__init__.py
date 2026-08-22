"""The VLM veto seat — Qwen3-VL-2B as PG-3's subtractive signal (card P1-D).

Two modules and one rule:

* :mod:`~parcel_robot.vlm_veto.verifier` — the seat itself. Answers *is the main
  object in this crop a ``<noun>``* and *what is the main object called*.
* :mod:`~parcel_robot.vlm_veto.runner` — where it is allowed to run: never on
  the 10 Hz loop, always under the contention guard.

**Importing this package imports no tensor library.** ``torch`` and
``transformers`` are pulled in by :meth:`~verifier.Qwen3VLVerifier.load` and
nowhere else, so a shipping install without the perception extra loses the veto
and gains nothing worse than a robot that asks more often.
"""

from __future__ import annotations

from parcel_robot.vlm_veto.bureau import (
    DEFAULT_BOARD_DEPTH,
    DEFAULT_QUEUE_DEPTH,
    DEFAULT_RETRY_BACKOFF_S,
    DEFAULT_VERDICT_TTL_S,
    PublishedVerdict,
    VerdictBureau,
    bureau_for,
    clear_bureaus,
    place_revision,
)
from parcel_robot.vlm_veto.judge import (
    JUDGE_ACCEPT,
    JUDGE_MIN_SCORE,
    JUDGE_REJECT,
    JUDGE_UNAVAILABLE,
    JudgeVerdict,
    NamingJudge,
    NullNamingJudge,
    OwlV2NamingJudge,
    active_naming_judge,
    default_naming_judge,
    use_naming_judge,
)
from parcel_robot.vlm_veto.runner import (
    COLD_SEAT_ESTIMATE_MS,
    DEFAULT_VETO_ESTIMATE_MS,
    LATENCY_EMA_ALPHA,
    LOOP_FORBIDDEN_CALLS,
    NULL_SEAT_NAMES,
    WARM_UP_ANSWERS,
    ControlLoopViolation,
    VetoRunner,
    clear_control_thread,
    clear_seats,
    default_runner,
    in_control_thread,
    mark_control_thread,
    runner_for,
    use_runner,
)
from parcel_robot.vlm_veto.verifier import (
    DEFAULT_MAX_CROP_PX,
    MODEL_REPO,
    NAME_PROMPT,
    NAME_PROMPT_CLASS_ANCHORED,
    VERIFY_PROMPT_TEMPLATE,
    VETO_ABSENT,
    VETO_P_YES_PRESENT,
    VETO_PRESENT,
    VETO_UNAVAILABLE,
    NameAnswer,
    NullVerifier,
    Qwen3VLVerifier,
    VetoAnswer,
    VetoRequest,
    active_verifier,
    parse_yes_no,
    resolve_weights,
    use_verifier,
)

__all__ = [
    "COLD_SEAT_ESTIMATE_MS",
    "DEFAULT_BOARD_DEPTH",
    "DEFAULT_MAX_CROP_PX",
    "DEFAULT_QUEUE_DEPTH",
    "DEFAULT_RETRY_BACKOFF_S",
    "DEFAULT_VERDICT_TTL_S",
    "DEFAULT_VETO_ESTIMATE_MS",
    "JUDGE_ACCEPT",
    "JUDGE_MIN_SCORE",
    "JUDGE_REJECT",
    "JUDGE_UNAVAILABLE",
    "LATENCY_EMA_ALPHA",
    "LOOP_FORBIDDEN_CALLS",
    "MODEL_REPO",
    "NAME_PROMPT",
    "NAME_PROMPT_CLASS_ANCHORED",
    "NULL_SEAT_NAMES",
    "VERIFY_PROMPT_TEMPLATE",
    "VETO_ABSENT",
    "VETO_PRESENT",
    "VETO_P_YES_PRESENT",
    "VETO_UNAVAILABLE",
    "WARM_UP_ANSWERS",
    "ControlLoopViolation",
    "JudgeVerdict",
    "NameAnswer",
    "NamingJudge",
    "NullNamingJudge",
    "NullVerifier",
    "OwlV2NamingJudge",
    "PublishedVerdict",
    "Qwen3VLVerifier",
    "VerdictBureau",
    "VetoAnswer",
    "VetoRequest",
    "VetoRunner",
    "active_naming_judge",
    "active_verifier",
    "bureau_for",
    "clear_bureaus",
    "clear_control_thread",
    "clear_seats",
    "default_naming_judge",
    "default_runner",
    "in_control_thread",
    "mark_control_thread",
    "parse_yes_no",
    "place_revision",
    "resolve_weights",
    "runner_for",
    "use_naming_judge",
    "use_runner",
    "use_verifier",
]
